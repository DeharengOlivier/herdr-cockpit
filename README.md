# herdr-cockpit

A WezTerm configuration that turns your terminal into a single, dedicated
cockpit for AI coding agents, driven by [Herdr](https://herdr.dev).

Open WezTerm and you get Herdr. Nothing else. No tab bar, no shell prompt to
navigate away from, no window chrome that clashes with the theme. Your projects
are already there as spaces in the left column, and a cost panel tells you what
your agents are burning.

```
┌─────────────────────────────────────────────────────────────┐
│ ● ● ●                                                       │  <- drag area, same colour as the body
├────────────┬────────────────────────────────────────────────┤
│ SPACES     │                                                │
│  client-a  │   $ claude                                     │
│  product   │   > refactor the auth module                   │
│  dotfiles  │                                                │
│  ▦ Stats   │                                                │
│            │                                                │
│ AGENTS     │                                                │
│  claude ●  │                                                │
│  codex  ○  │                                                │
└────────────┴────────────────────────────────────────────────┘
```

## What you actually get

**A terminal with no tabs.** WezTerm's own tab bar is emptied but kept, because
it carries the traffic-light buttons and the drag area. Its colour and opacity
are computed from the theme constants, so the title bar and the body cannot
drift apart. Herdr manages tabs internally instead.

**Cmd keybindings instead of Ctrl.** macOS never delivers the Cmd modifier to
terminal applications, so Herdr can't see it. WezTerm can. This config
intercepts `Cmd+T`, `Cmd+W`, `Cmd+D` and friends, then sends Herdr the prefix
sequence it expects. It detects whether the foreground process is Herdr or tmux
and sends the right key for each.

**Your projects, always there.** `spaces.conf` declares them. A watchdog
re-creates any space you close by accident, within two seconds.

**A cost panel.** An interactive curses TUI over your Claude Code session
transcripts: tokens and cost by project, model, month or day, with cumulative
filters, search, sorting and mouse support. Bound to `Ctrl-b i` as an overlay,
and permanently open in the `▦ Stats` space.

## Requirements

| | |
|---|---|
| [Herdr](https://herdr.dev) | `brew install herdr` |
| [WezTerm](https://wezterm.org) | `brew install --cask wezterm` |
| Python 3 | for the stats panel |
| [quota-axi](https://www.npmjs.com/package/quota-axi) | optional, adds subscription quota bars |

A Nerd Font is assumed (`Hack Nerd Font` by default). Change `THEME` and the
font name at the top of `config/wezterm.lua` if you prefer others.

## Install

```sh
git clone https://github.com/DeharengOlivier/herdr-cockpit.git
cd herdr-cockpit
./install.sh
```

Then edit `spaces.conf` and open WezTerm.

Run `./install.sh --dry-run` first if you want to see every file it would
touch. Nothing is copied: the installer creates symlinks into this repository,
so `git pull` updates your setup without reinstalling. Anything it replaces is
moved to `<file>.bak-<timestamp>` and recorded in a manifest that
`./uninstall.sh` replays in reverse.

The one exception is `~/.config/herdr/config.toml`, which is generated rather
than linked because it holds an absolute path. If you already have one, the
installer refuses to guess a merge: it writes its version alongside as
`config.toml.cockpit` and shows you the diff command.

## Declaring your spaces

```conf
PROJECTS_ROOT=~/dev

client-acme	clients/acme
my-product	products/my-product
dotfiles	~/.dotfiles
```

The separator is a **tab**, not spaces, because both labels and paths routinely
contain spaces. Relative paths resolve against `PROJECTS_ROOT`; absolute ones
are taken as-is. Order is display order. A path that does not exist is reported
and skipped, never created.

Check your file without launching anything:

```sh
herdr-cockpit-bootstrap --list
```

`spaces.conf` is gitignored, so your client and product names never leave your
machine. Only `spaces.conf.example` is published.

## Your GitHub profile in the panel

Set `GITHUB_USER` in `spaces.conf` and the installer renders your avatar into
the top-right corner of the stats panel, next to your name, a clickable profile
link and your public repo count.

```conf
GITHUB_USER=your-handle
```

The avatar is drawn with Unicode upper-half blocks (`▀`), one character
carrying two pixels through its foreground and background colours, quantised to
the xterm-256 palette. That means it is ordinary coloured text: it survives
curses redraws, needs no experimental terminal flag, and works over SSH. A
12x6 badge costs about thirty colour pairs out of the 32767 a modern terminal
offers.

`bin/github-badge.py` does all the work once at install time (fetch, PNG
decode, box downsample, quantise) and writes a small JSON file. The panel only
draws it, so it stays offline and instant. Regenerate it any time:

```sh
bin/github-badge.py your-handle          # 12x6, the header height
bin/github-badge.py your-handle --size 8 # taller, if you widened the header
```

Press `p` to hide or show the badge, `o` to open the profile in a browser, or
click the URL. Below 108 columns the avatar is dropped and only the link
remains; below 74 columns the whole badge goes, so the table never gets
squeezed. No `GITHUB_USER` means no badge and no mention of one.

The rendering is a real HTTP call to `api.github.com` at install time, and
nothing else: no token, no authentication, only the public profile endpoint.

## Keybindings

Herdr's own prefix is `Ctrl-b`. These Cmd shortcuts are translated to it.

| Key | Action |
|---|---|
| `Cmd+T` | new tab |
| `Cmd+W` | close tab |
| `Cmd+←` / `Cmd+→` | previous / next tab |
| `Cmd+1..9` | go to tab N |
| `Cmd+D` | split vertically |
| `Cmd+Shift+D` | split horizontally |
| `Cmd+Opt+←↓↑→` | move between panes |
| `Cmd+Enter` | zoom the current pane |
| `Cmd+Shift+W` | close the pane |
| `Cmd+B` | collapse the sidebar |
| `Cmd+G` | agent browser |
| `Cmd+P` | space picker |
| `Ctrl-b` then `i` | cost panel overlay |

## How it works

WezTerm's `default_prog` runs `~/.local/bin/herdr-cockpit-bootstrap`, a symlink
into `bin/`. That script:

1. resolves its own real path through the symlink chain, so the repository can
   be moved without breaking anything;
2. reads `spaces.conf` and creates any missing space;
3. forks a watchdog that re-checks every two seconds and exits when the Herdr
   server does;
4. `exec`s `herdr session attach default`, rather than plain `herdr`, which
   would create a new space on every launch.

The `▦ Stats` space starts directly on the panel thanks to a `HERDR_AUTOSTART`
guard sourced from your `~/.zshrc`. Without it, Herdr opens a shell first and
the panel lands in a second, useless pane.

Herdr has no way to protect a space from being closed. `close_workspace = ""`
disables the keyboard shortcut, and `confirm_close` is deliberately left on,
but the sidebar menu's "close" entry cannot be hidden in Herdr 0.7. The
watchdog is what catches that case.

## What survives what

Worth knowing, because three different layers are involved.

**Closing the WezTerm window** kills only the client. The Herdr server keeps
running with every pane and agent alive. Reopening reattaches to the same
session.

**Stopping the Herdr server** (`herdr server stop`) kills the live processes.
The layout itself is not lost: Herdr continuously writes spaces, tabs, labels
and working directories to `~/.config/herdr/session.json`.

**Rebooting** does not restart the server automatically. The bootstrap
re-creates your spaces on the next launch regardless.

This config sets `resume_agents_on_restore = true`, which resumes agent
conversations in their native sessions after a server restart. It only works
for agents with an official integration installed:

```sh
herdr integration install claude
herdr integration status
```

Separately, Claude Code keeps its own append-only JSONL transcript per session
under `~/.claude/projects/`, chained by `parentUuid`. That is what the stats
panel reads, and it survives everything.

## A note on the cost figures

The panel multiplies token counts by Anthropic's public API rates. If you are
on a subscription plan, **those amounts are notional, not a bill**. They tell
you what the same usage would have cost through the API, which is useful for
comparison and useless as accounting.

## Optional plugins

This repository installs no third-party plugin, on purpose. Herdr's
marketplace is self-declared and unreviewed, and plugins run **unsandboxed with
your full user privileges**. Read the manifest and any `[[build]]` script
before installing, and prefer `herdr plugin link <path>` on a copy you have
audited.

That said, a few are worth the look:

| Plugin | What it adds |
|---|---|
| [`persiyanov/herdr-reviewr`](https://github.com/persiyanov/herdr-reviewr) | review an agent's diff in a sidebar and send comments back to it |
| [`yuk1ty/herdr-spreader`](https://github.com/yuk1ty/herdr-spreader) | declarative tab and pane layouts from a YAML file |
| [`JanTvrdik/herdr-command-palette`](https://github.com/JanTvrdik/herdr-command-palette) | fuzzy palette over every action of every installed plugin |
| [`smarzban/herdr-file-viewer`](https://github.com/smarzban/herdr-file-viewer) | git-aware read-only file tree |

Before reaching for any of them, note that `herdr pane report-metadata` plus
custom `[ui.sidebar.agents] rows` tokens let you build a bespoke sidebar
statusline in pure configuration, with no dependency and no risk.

## Uninstall

```sh
./uninstall.sh
```

Replays the install manifest in reverse and restores every backup. It leaves
the repository, your `spaces.conf`, and Herdr and WezTerm themselves untouched.

## Credits

The idea comes from the terminal workflow Kun Chen demonstrated on video. No
code of his was used or consulted; see [NOTICE](NOTICE) for the full provenance
statement and third-party licensing.

Herdr is dual-licensed AGPL-3.0-or-later or commercial, and is **not**
redistributed here. This repository contains configuration only.

## License

MIT. See [LICENSE](LICENSE).
