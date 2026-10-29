local wezterm = require("wezterm")
local act = wezterm.action

local config = wezterm.config_builder()

-- Appearance. These two constants are the only ones to change in order to
-- repaint everything: the window bar is recomputed from them further down, and
-- therefore cannot drift away from the terminal body.
-- Available themes: wezterm ls-fonts --list-system, and the gallery at
-- https://wezterm.org/colorschemes/index.html
local THEME = "rose-pine-moon"
local OPACITY = 0.8

config.color_scheme = THEME
config.font = wezterm.font("Hack Nerd Font")
config.font_size = 15.0
config.window_background_opacity = OPACITY
config.macos_window_background_blur = 50

-- When WezTerm opens we go through bootstrap.sh, which since 2026-08-06 does
-- one single thing: attach the existing session ("session attach default"
-- rather than a plain "herdr", which used to create an extra space on every
-- launch). It no longer provisions the spaces of spaces.conf and no longer
-- starts a watcher. Spaces are created by hand, and a closed space stays closed.
--
-- The path goes through the symlink installed by install.sh, never through the
-- repository location. That protects the config from a repository move only if
-- the symlink itself is repointed: it broke when the repository moved on
-- 2026-08-04, and was repaired on 2026-08-06.
local BOOTSTRAP = (os.getenv("HOME") or "") .. "/.local/bin/herdr-cockpit-bootstrap"

-- Draggable window bar.
-- INTEGRATED_BUTTONS draws the red/yellow/green buttons inside the WezTerm bar
-- rather than in a macOS title bar. The empty space of that bar acts as the
-- drag area used to move the window with the mouse.
config.window_decorations = "INTEGRATED_BUTTONS|RESIZE"
config.integrated_title_button_style = "MacOsNative"

-- Bar in "retro" mode: tabs are drawn as plain text, with no per-tab close
-- button. This is what lets us have no trace of a tab in the bar while still
-- keeping the window buttons.
config.use_fancy_tab_bar = false

-- The bar stays visible at all times: it is the one carrying the buttons and
-- the drag area. Hiding it would mean losing both.
config.hide_tab_bar_if_only_one_tab = false

-- The "+" button disappears: tabs are managed by Herdr, not by WezTerm
config.show_new_tab_button_in_tab_bar = false

-- The bar carries exactly one thing: which machine each page is. Herdr manages
-- its own tabs internally, so a WezTerm tab is never a tab in the usual sense
-- here; there is one per machine and never any other. Drawing their names is
-- what makes them clickable targets rather than invisible ones, and the bar is
-- also what carries the red/yellow/green buttons and the drag area, so it has
-- to stay anyway.
wezterm.on("format-tab-title", function(tab)
	local name = tab.tab_title
	if not name or name == "" then
		return ""
	end
	return {
		{ Attribute = { Intensity = tab.is_active and "Bold" or "Half" } },
		{ Text = (tab.is_active and " ▍" or "  ") .. name .. "  " },
	}
end)

-- The bar takes exactly the same color AND the same opacity as the terminal
-- body, so that the two are indistinguishable. The color comes from the theme
-- and the opacity from the same constant as the window: the two therefore
-- cannot drift apart. Painting the bar at 100% would make it darker than the
-- body.
local scheme = wezterm.color.get_builtin_schemes()[THEME]
local hex = scheme.background
local r = tonumber(hex:sub(2, 3), 16)
local v = tonumber(hex:sub(4, 5), 16)
local b = tonumber(hex:sub(6, 7), 16)
local bar_background = string.format("rgba(%d,%d,%d,%.3f)", r, v, b, OPACITY)

-- window_frame only styles the "fancy" bar. Since we switched to retro mode to
-- get rid of the close cross, colors.tab_bar is what actually counts: without
-- it the bar stays grey by default instead of following the theme.
-- We fill in both so as to stay correct if we ever switch back.
config.window_frame = {
	active_titlebar_bg = bar_background,
	inactive_titlebar_bg = bar_background,
	font = wezterm.font("Hack Nerd Font"),
	font_size = 12.0,
}

config.colors = {
	tab_bar = {
		background = bar_background,
		active_tab = { bg_color = bar_background, fg_color = scheme.foreground },
		inactive_tab = { bg_color = bar_background, fg_color = scheme.foreground },
		new_tab = { bg_color = bar_background, fg_color = scheme.foreground },
	},
}

-- Two pages in one window: LOCAL and the remote machine.
--
-- Herdr 0.9 can show Local and saved SSH machines side by side in one sidebar
-- (`herdr machine add`). That merges two machines into one column, and the
-- column is already the busiest part of the screen. A page is easier to read:
-- the whole window is one machine, the status on the right says which, and a
-- single chord swaps it. WezTerm workspaces do exactly that, so nothing here
-- needs a second window to alt-tab between.
--
-- The remote host is declared in ~/.config/herdr-cockpit/remote.conf, next to
-- the install manifest, and never in this file: the repository is public and a
-- hostname is not. Two directives, HOST and LABEL:
--
--   HOST=workbox
--   LABEL=VPS
--
-- With no such file there is no remote page and no dead shortcut.
local LOCAL_PAGE = "LOCAL"

local function read_remote()
	local path = (os.getenv("HOME") or "") .. "/.config/herdr-cockpit/remote.conf"
	local f = io.open(path, "r")
	if not f then
		return nil
	end
	local host, label
	for line in f:lines() do
		host = line:match("^%s*HOST%s*=%s*(%S+)") or host
		label = line:match("^%s*LABEL%s*=%s*(%S+)") or label
	end
	f:close()
	if not host then
		return nil
	end
	return { host = host, label = label or "REMOTE" }
end

local REMOTE = read_remote()

-- The binary is addressed by absolute path: a spawned program does not go
-- through a login shell, so ~/.local/bin may not be on its PATH.
local function herdr_bin()
	local candidate = (os.getenv("HOME") or "") .. "/.local/bin/herdr"
	local f = io.open(candidate, "r")
	if f then
		f:close()
		return candidate
	end
	return "herdr"
end

-- Neither page runs its program directly, and that is the whole point.
--
-- WezTerm closes a tab the instant its program exits, and both programs exit
-- for ordinary reasons: Ctrl-b d detaches Herdr, and an SSH connection dies
-- whenever the VPS sleeps, the network changes or the tunnel drops. The page
-- then disappears from the bar with its name and its position. Measured on
-- 2026-09-16: the remote tab opened at startup was gone by the evening, and a
-- nameless tab sat in the window in its place, invisible because an empty
-- title draws nothing in the bar.
--
-- So each page runs a loop around its program. The program comes back on its
-- own, the pane stays open in between and says what happened, and the tab
-- therefore never closes by itself. `read -t` is what holds the pty open
-- without burning a core against a host that is simply unreachable.
--
-- `set -m` is not decoration. Without job control the program runs in the
-- shell's own process group, so the terminal's foreground group stays bash and
-- `get_foreground_process_name()` below answers "bash" instead of "herdr":
-- every Cmd shortcut would go silent. With it, the program gets its own group
-- and the terminal follows. Measured on a pseudo-terminal, 2026-09-16.
local KEEPALIVE = [[
set -m
while true; do
  "$@"
  printf '\n\033[2m%s: page closed (exit %d). Enter to reopen, or wait 5 s.\033[0m\n' "$0" "$?"
  read -r -t 5 _ || true
done
]]

-- `bash -c <script> <name> <argv...>` puts <name> in $0 and the rest in "$@",
-- which is how the loop above names the page in its own message.
local function keepalive(title, argv)
	local args = { "/bin/bash", "-c", KEEPALIVE, title }
	for _, value in ipairs(argv) do
		args[#args + 1] = value
	end
	return args
end

local function local_argv()
	return { "/bin/bash", BOOTSTRAP }
end

-- `env -u` strips the markers Herdr sets inside its own panes. WezTerm spawns
-- from the GUI's environment, which is normally free of them, but a WezTerm
-- started from inside a pane would inherit them and Herdr would refuse to run
-- ("nested herdr is disabled by default"). The page would then open and close
-- in a blink, which is a miserable thing to diagnose.
local function remote_argv()
	return {
		"/usr/bin/env",
		"-u", "HERDR_ENV",
		"-u", "HERDR_PANE_ID",
		"-u", "HERDR_TAB_ID",
		"-u", "HERDR_WORKSPACE_ID",
		"-u", "HERDR_SOCKET_PATH",
		herdr_bin(),
		"--remote",
		REMOTE.host,
		"--remote-keybindings",
		"local",
	}
end

-- The pages the window must carry, in the order they take in the bar. With no
-- remote.conf there is one page, no dead shortcut and nothing to reconnect.
local function pages()
	local list = { { title = LOCAL_PAGE, argv = local_argv() } }
	if REMOTE then
		list[#list + 1] = { title = REMOTE.label, argv = remote_argv() }
	end
	return list
end

config.default_prog = keepalive(LOCAL_PAGE, local_argv())

-- One window owns the pages. update-status fires for every window, and a
-- second window opened with Cmd+N must not open a second SSH connection to the
-- VPS; it gets a local cockpit from default_prog and nothing else. The owner is
-- kept in wezterm.GLOBAL, which survives a config reload where a plain local
-- does not, and is handed over if that window is gone.
local function owns_pages(mux_window)
	local id = mux_window:window_id()
	local owner = wezterm.GLOBAL.cockpit_window
	if owner ~= nil then
		for _, other in ipairs(wezterm.mux.all_windows()) do
			if other:window_id() == owner then
				return owner == id
			end
		end
	end
	wezterm.GLOBAL.cockpit_window = id
	return true
end

-- A spawn that fails at once (VPS asleep, no network, no SSH agent) takes its
-- tab with it, and without this the reconciler would spawn again a second
-- later, forever. The keepalive loop paces its own retries; this paces the
-- window's.
local SPAWN_COOLDOWN = 10

local function spawn_page(mux_window, page)
	local key = "spawned_" .. page.title
	local now = os.time()
	local last = wezterm.GLOBAL[key]
	if last ~= nil and now - last < SPAWN_COOLDOWN then
		return nil
	end
	wezterm.GLOBAL[key] = now
	local tab = mux_window:spawn_tab({ args = keepalive(page.title, page.argv) })
	tab:set_title(page.title)
	return tab
end

-- The invariant, rechecked about once a second: every page has its tab, and no
-- tab in this window is nameless.
--
-- Nothing is ever closed here. A tab that is not a page was opened on purpose,
-- and the macOS menu bar still carries Shell > New Tab, which no keybinding can
-- intercept. Such a tab is named rather than killed: an unnamed one draws
-- nothing in the bar, which makes it a page you can neither see nor click. It
-- runs default_prog, that is the local cockpit, so it is also the natural thing
-- to promote when the local page is the one missing.
local function reconcile(mux_window)
	local present = {}
	local unnamed = {}
	for _, item in ipairs(mux_window:tabs_with_info()) do
		local title = item.tab:get_title()
		if title == "" then
			unnamed[#unnamed + 1] = item.tab
		else
			present[title] = true
		end
	end

	for _, page in ipairs(pages()) do
		if not present[page.title] then
			local adopted = nil
			if page.title == LOCAL_PAGE then
				adopted = table.remove(unnamed, 1)
			end
			if adopted then
				adopted:set_title(page.title)
			else
				spawn_page(mux_window, page)
			end
			present[page.title] = true
		end
	end

	for _, tab in ipairs(unnamed) do
		tab:set_title("extra")
	end
end

wezterm.on("gui-startup", function()
	local tab, _, window = wezterm.mux.spawn_window({ args = keepalive(LOCAL_PAGE, local_argv()) })
	tab:set_title(LOCAL_PAGE)
	wezterm.GLOBAL.cockpit_window = window:window_id()
	reconcile(window)
	tab:activate()
end)

wezterm.on("update-status", function(window)
	local mux_window = window:mux_window()
	if mux_window ~= nil and owns_pages(mux_window) then
		reconcile(mux_window)
	end
	-- An earlier version of this config drew the page names in the right-hand
	-- status. A status stays on screen until something replaces it, so that text
	-- would survive a reload and sit there looking like a pair of tabs that
	-- ignore the mouse. The tabs themselves are the clickable ones.
	window:set_right_status("")
end)

-- Go to the page. It is normally already there, since the reconciler puts it
-- back within a second; a keypress is an explicit ask, so it also clears the
-- cooldown rather than doing nothing visible.
local function goto_page(name)
	return wezterm.action_callback(function(window, pane)
		local mux_window = window:mux_window()
		for _, item in ipairs(mux_window:tabs_with_info()) do
			if item.tab:get_title() == name then
				window:perform_action(act.ActivateTab(item.index), pane)
				return
			end
		end
		for _, page in ipairs(pages()) do
			if page.title == name then
				wezterm.GLOBAL["spawned_" .. name] = nil
				local tab = spawn_page(mux_window, page)
				if tab ~= nil then
					tab:activate()
				end
			end
		end
	end)
end

-- Herdr and tmux both use Ctrl-b as their prefix, that is the byte 0x02
local PREFIX = "\x02"

-- macOS never forwards the Command key to terminal applications: neither Herdr
-- nor tmux can see it. Only WezTerm receives it. So we intercept Cmd+X here and
-- send back the sequence expected by the multiplexer currently running. The
-- action keys differ between the two, hence the two sequences per shortcut.
-- No native fallback: no shortcut creates a WezTerm tab any more.
local function mux(tmux_seq, herdr_seq)
	return wezterm.action_callback(function(window, pane)
		local proc = pane:get_foreground_process_name() or ""
		local seq = nil
		if proc:find("herdr", 1, true) then
			seq = herdr_seq
		elseif proc:find("tmux", 1, true) then
			seq = tmux_seq
		end
		if seq then
			window:perform_action(act.SendString(PREFIX .. seq), pane)
		end
	end)
end

config.keys = {
	--                                    tmux   herdr
	-- Tabs (Herdr's own, not WezTerm's)
	{ key = "t", mods = "CMD", action = mux("c", "c") },
	{ key = "w", mods = "CMD", action = mux("&", "X") },
	{ key = "LeftArrow", mods = "CMD", action = mux("p", "p") },
	{ key = "RightArrow", mods = "CMD", action = mux("n", "n") },
	{ key = "[", mods = "CMD|SHIFT", action = mux("p", "p") },
	{ key = "]", mods = "CMD|SHIFT", action = mux("n", "n") },
	{ key = "r", mods = "CMD|SHIFT", action = mux(",", "T") },

	-- Panes
	{ key = "d", mods = "CMD", action = mux("%", "v") },
	{ key = "d", mods = "CMD|SHIFT", action = mux('"', "-") },
	{ key = "Enter", mods = "CMD", action = mux("z", "z") },
	{ key = "w", mods = "CMD|SHIFT", action = mux("x", "x") },

	-- Navigating between panes: tmux expects the arrow keys, Herdr expects h/j/k/l
	{ key = "LeftArrow", mods = "CMD|ALT", action = mux("\x1b[D", "h") },
	{ key = "RightArrow", mods = "CMD|ALT", action = mux("\x1b[C", "l") },
	{ key = "UpArrow", mods = "CMD|ALT", action = mux("\x1b[A", "k") },
	{ key = "DownArrow", mods = "CMD|ALT", action = mux("\x1b[B", "j") },

	-- Herdr specific
	{ key = "g", mods = "CMD", action = mux(nil, "g") }, -- agent browser
	{ key = "p", mods = "CMD", action = mux(nil, "w") }, -- space picker
	{ key = "b", mods = "CMD", action = mux(nil, "b") }, -- collapse the sidebar

	-- Pages. Cmd+Shift+L is always the Mac; Cmd+Shift+V is the remote machine.
	-- Two explicit chords rather than one toggle: you always know where you land.
	{ key = "l", mods = "CMD|SHIFT", action = goto_page(LOCAL_PAGE) },
}

if REMOTE then
	table.insert(config.keys, { key = "v", mods = "CMD|SHIFT", action = goto_page(REMOTE.label) })
end

-- Cmd+1 to Cmd+9: jump straight to tab N (identical in both)
for i = 1, 9 do
	table.insert(config.keys, {
		key = tostring(i),
		mods = "CMD",
		action = mux(tostring(i), tostring(i)),
	})
end

return config
