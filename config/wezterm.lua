local wezterm = require("wezterm")
local act = wezterm.action

local config = wezterm.config_builder()

-- Apparence. Ces deux constantes sont les seules a changer pour repeindre
-- l'ensemble : la barre de fenetre se recalcule a partir d'elles plus bas, et
-- ne peut donc pas diverger du corps du terminal.
-- Themes disponibles : wezterm ls-fonts --list-system, et la galerie
-- https://wezterm.org/colorschemes/index.html
local THEME = "rose-pine-moon"
local OPACITE = 0.8

config.color_scheme = THEME
config.font = wezterm.font("Hack Nerd Font")
config.font_size = 15.0
config.window_background_opacity = OPACITE
config.macos_window_background_blur = 50

-- A l'ouverture de WezTerm on passe par bootstrap.sh, qui recree les spaces
-- manquants, lance la surveillance qui les remet en place s'ils sont fermes,
-- puis attache la session existante ("session attach default" plutot qu'un
-- simple "herdr", qui creait un space supplementaire a chaque ouverture).
--
-- Le chemin passe par le lien symbolique pose par install.sh, jamais par
-- l'emplacement du depot : celui-ci peut etre deplace sans casser WezTerm.
config.default_prog = {
	"/bin/bash",
	(os.getenv("HOME") or "") .. "/.local/bin/herdr-cockpit-bootstrap",
}

-- Barre de fenetre deplacable.
-- INTEGRATED_BUTTONS dessine les boutons rouge/jaune/vert dans la barre de
-- WezTerm plutot que dans une barre de titre macOS. L'espace vide de cette
-- barre sert de zone de glisser pour deplacer la fenetre a la souris.
config.window_decorations = "INTEGRATED_BUTTONS|RESIZE"
config.integrated_title_button_style = "MacOsNative"

-- Barre en mode "retro" : les onglets y sont dessines comme du texte, sans
-- bouton de fermeture par onglet. C'est ce qui permet de n'avoir aucune trace
-- d'onglet dans la barre tout en gardant les boutons de fenetre.
config.use_fancy_tab_bar = false

-- La barre reste visible en permanence : c'est elle qui porte les boutons
-- et la zone de glisser. La masquer reviendrait a perdre les deux.
config.hide_tab_bar_if_only_one_tab = false

-- Le bouton "+" disparait : les onglets sont geres par Herdr, pas par WezTerm
config.show_new_tab_button_in_tab_bar = false

-- L'onglet lui-meme n'affiche plus rien. Il n'y aura jamais qu'un seul onglet
-- WezTerm (Herdr gere les siens en interne), donc l'afficher n'apporte rien.
-- On ne peut pas simplement supprimer la barre : c'est elle qui porte les
-- boutons rouge/jaune/vert et la zone de glisser. On vide donc son contenu.
wezterm.on("format-tab-title", function()
	return ""
end)

-- La barre prend exactement la meme couleur ET la meme opacite que le corps
-- du terminal, pour qu'elles soient indiscernables. La couleur vient du theme
-- et l'opacite de la meme constante que la fenetre : les deux ne peuvent donc
-- pas diverger. Peindre la barre a 100% la rendrait plus sombre que le corps.
local scheme = wezterm.color.get_builtin_schemes()[THEME]
local hex = scheme.background
local r = tonumber(hex:sub(2, 3), 16)
local v = tonumber(hex:sub(4, 5), 16)
local b = tonumber(hex:sub(6, 7), 16)
local fond_barre = string.format("rgba(%d,%d,%d,%.3f)", r, v, b, OPACITE)

-- window_frame ne stylise que la barre "fancy". Comme on est passe en mode
-- retro pour supprimer la croix de fermeture, c'est colors.tab_bar qui fait
-- foi : sans ca la barre reste grise par defaut au lieu de suivre le theme.
-- On renseigne les deux pour rester correct si on rebascule un jour.
config.window_frame = {
	active_titlebar_bg = fond_barre,
	inactive_titlebar_bg = fond_barre,
	font = wezterm.font("Hack Nerd Font"),
	font_size = 12.0,
}

config.colors = {
	tab_bar = {
		background = fond_barre,
		active_tab = { bg_color = fond_barre, fg_color = scheme.foreground },
		inactive_tab = { bg_color = fond_barre, fg_color = scheme.foreground },
		new_tab = { bg_color = fond_barre, fg_color = scheme.foreground },
	},
}

-- Herdr et tmux utilisent tous les deux Ctrl-b comme prefixe, soit l'octet 0x02
local PREFIX = "\x02"

-- macOS ne transmet jamais la touche Commande aux applications terminal :
-- ni Herdr ni tmux ne peuvent la voir. Seul WezTerm la recoit. On intercepte
-- donc Cmd+X ici et on renvoie la sequence attendue par le multiplexeur en
-- cours. Les touches d'action different entre les deux, d'ou les deux
-- sequences par raccourci.
-- Aucun repli natif : plus aucun raccourci ne cree d'onglet WezTerm.
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
	-- Onglets (ceux de Herdr, pas ceux de WezTerm)
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

	-- Naviguer entre les panes : tmux attend les fleches, Herdr attend h/j/k/l
	{ key = "LeftArrow", mods = "CMD|ALT", action = mux("\x1b[D", "h") },
	{ key = "RightArrow", mods = "CMD|ALT", action = mux("\x1b[C", "l") },
	{ key = "UpArrow", mods = "CMD|ALT", action = mux("\x1b[A", "k") },
	{ key = "DownArrow", mods = "CMD|ALT", action = mux("\x1b[B", "j") },

	-- Specifiques a Herdr
	{ key = "g", mods = "CMD", action = mux(nil, "g") }, -- navigateur d'agents
	{ key = "p", mods = "CMD", action = mux(nil, "w") }, -- selecteur de spaces
	{ key = "b", mods = "CMD", action = mux(nil, "b") }, -- replier la barre laterale
}

-- Cmd+1 a Cmd+9 : aller directement a l'onglet N (identique dans les deux)
for i = 1, 9 do
	table.insert(config.keys, {
		key = tostring(i),
		mods = "CMD",
		action = mux(tostring(i), tostring(i)),
	})
end

return config
