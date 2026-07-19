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

-- When WezTerm opens we go through bootstrap.sh, which recreates the missing
-- spaces, starts the watcher that puts them back if they get closed, then
-- attaches the existing session ("session attach default" rather than a plain
-- "herdr", which used to create an extra space on every launch).
--
-- The path goes through the symlink installed by install.sh, never through the
-- repository location: the repo can be moved without breaking WezTerm.
config.default_prog = {
	"/bin/bash",
	(os.getenv("HOME") or "") .. "/.local/bin/herdr-cockpit-bootstrap",
}

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

-- The tab itself no longer displays anything. There will never be more than a
-- single WezTerm tab (Herdr manages its own internally), so displaying it adds
-- nothing. We cannot simply remove the bar: it is the one carrying the
-- red/yellow/green buttons and the drag area. So we empty its contents instead.
wezterm.on("format-tab-title", function()
	return ""
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
}

-- Cmd+1 to Cmd+9: jump straight to tab N (identical in both)
for i = 1, 9 do
	table.insert(config.keys, {
		key = tostring(i),
		mods = "CMD",
		action = mux(tostring(i), tostring(i)),
	})
end

return config
