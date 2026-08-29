# Security

This repository is a configuration for a terminal on your own machine. There is
no server, no account, no credential, and nothing multi-user: every line of it
runs as you, with your privileges, on your laptop. There is therefore no
privilege boundary inside it to break. What follows is what it actually does,
so you can decide whether you want it doing that.

## What leaves your machine

One request, once, and only if you ask for it.

`bin/github-badge.py` fetches `https://api.github.com/users/<login>` when
`GITHUB_USER` is set in `spaces.conf`. It is the public endpoint, sent with no
token and no cookie, and it carries your GitHub handle and the `User-Agent`
string `herdr-cockpit`. It writes four public fields (login, display name,
profile URL, public repository count) to
`~/.config/herdr-cockpit/github-badge.json`. Leave `GITHUB_USER` empty and no
request is made at all.

Nothing else in this repository opens a socket. The statistics panel reads your
Claude Code transcripts from disk and never sends anything anywhere.

## What is read, and what is kept

The panel walks `~/.claude/projects/**/*.jsonl`, which is where Claude Code
writes your conversations. It reads only four things per line: the timestamp,
the model name, the token counts, and the session's working directory. The
message content is never parsed, never displayed, and never stored.

Its cache, at `~/.cache/agent-stats/usage-cache.json` (or under
`$HERDR_PLUGIN_STATE_DIR`), therefore holds file paths, dates, model names and
numbers. It holds no conversation text. If your project paths are themselves
sensitive, that file is the one to know about.

`spaces.conf` is deliberately not tracked by git, because it carries client and
product names. Only `spaces.conf.example` is published.

## The eval, stated plainly

`shell/herdr-autostart.zsh` runs `eval "$HERDR_AUTOSTART"` in every interactive
zsh, once the guard is installed in your `~/.zshrc`. That is the sharpest edge
in the repository, and it is deliberate: it is how a space starts directly on
an application instead of on a shell.

It grants nothing new. Anything able to set an environment variable in your
shell is already running as you and can already run whatever it likes. The
variable is unset immediately after being read, so it does not survive into
sub-shells. Herdr sets it when creating the `▦ Stats` space, and the value it
sets is built by `bootstrap.sh` from a path inside this repository.

If you would rather not have an `eval` in your shell startup, decline the
prompt during installation. The panel still works; the statistics space just
opens a shell first and the panel in a second pane.

## Inputs that are validated

`GITHUB_USER` is checked against the shape of a GitHub username before it ever
reaches a URL. It used to be interpolated straight into the API path, where a
value carrying a slash reached a different endpoint and one carrying a newline
put a control character in the request.

`spaces.conf` entries are read as label and path, tab-separated, and a path
that does not exist is reported and skipped rather than created. Labels reach
`herdr workspace create` as separate `execve` arguments, never through a shell.
`panel.py` opens a profile URL through `subprocess.run` with an argument list,
for the same reason.

## What the installer touches

`install.sh` creates symlinks in `~/.local/bin`, links `~/.config/wezterm/wezterm.lua`,
generates `~/.config/herdr/config.toml`, and appends a marked block to
`~/.zshrc`. Every file it moves aside is kept as `<file>.bak-<timestamp>` and
recorded in `~/.config/herdr-cockpit/install-manifest`.

`./install.sh --dry-run` prints all of it and writes nothing.
`./uninstall.sh` replays the manifest backwards. That round trip is covered by
the test suite, against a throwaway `HOME`, rather than being asserted here.

## Where the real risk is

Herdr plugins. They are distributed through a self-declared, unreviewed
marketplace and run unsandboxed with your full user privileges. This repository
installs none, on purpose. If you add one, read its manifest and any
`[[build]]` script first, and prefer `herdr plugin link <path>` on a copy you
have audited yourself.

Herdr and WezTerm are separate projects with their own security processes. This
repository redistributes neither.

## Reporting something

Open an issue at
<https://github.com/DeharengOlivier/herdr-cockpit/issues>. Given the scope
above, nothing here can compromise anyone but the person who installed it, so
there is no embargo process: a public issue is the right place.
