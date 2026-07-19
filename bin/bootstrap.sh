#!/bin/bash
# herdr-cockpit: provisions the Herdr spaces, then attaches the session.
#
#   bootstrap.sh            provision + watch in background + attach the session
#   bootstrap.sh --ensure   provision only, then hand back control
#   bootstrap.sh --watch    watch loop (internal use)
#
# This is the script WezTerm runs on startup (see config/wezterm.lua).
#
# Herdr cannot protect a space against closing: the shortcut can be disabled,
# but the "close" entry in the sidebar menu cannot be hidden. Watching is
# therefore the only way to guarantee that a space closed by mistake comes
# back.
#
# Compatible with bash 3.2 (the version shipped with macOS): no associative
# array, no readarray, no ${var,,}.

set -uo pipefail

# --- Locating the repository -----------------------------------------------
# The script is called through a symlink from ~/.local/bin. We walk the chain
# of links back to find the repository root, which makes it possible to move
# the repository or update it with git pull without ever reinstalling.
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  link_target="$(readlink "$SELF")"
  case "$link_target" in
    /*) SELF="$link_target" ;;
    *)  SELF="$(cd "$(dirname "$SELF")" && pwd)/$link_target" ;;
  esac
done
COCKPIT_DIR="$(cd "$(dirname "$SELF")/.." && pwd)"

HERDR="${COCKPIT_HERDR_BIN:-}"
if [ -z "$HERDR" ]; then
  HERDR="$(command -v herdr 2>/dev/null)" || HERDR=""
fi
[ -z "$HERDR" ] && HERDR="$HOME/.local/bin/herdr"

PANEL="$COCKPIT_DIR/stats/panel.py"
SPACES_CONF="${COCKPIT_SPACES_CONF:-$COCKPIT_DIR/spaces.conf}"
STATS_LABEL="${COCKPIT_STATS_LABEL:-▦ Stats}"
# The stats space deliberately does NOT point at the repository: the sidebar
# shows the git branch under a space label, and "main" under "▦ Stats" makes
# no sense. This directory is not a repository, so nothing is displayed. The
# panel is started by absolute path, the cwd does not concern it.
STATS_CWD="${COCKPIT_STATS_CWD:-$HOME/.config/herdr-cockpit}"
INTERVAL="${COCKPIT_WATCH_INTERVAL:-2}"
SESSION="${COCKPIT_SESSION:-default}"
WATCH_PID_FILE="${COCKPIT_WATCH_PID_FILE:-$HOME/.config/herdr-cockpit/watch.pid}"

# --- Reading spaces.conf ---------------------------------------------------
# Format: an optional PROJECTS_ROOT=... directive, then lines of the form
# "label <TAB> path". Relative paths are resolved from PROJECTS_ROOT.
PROJECTS_ROOT=""
SPACES=()          # entries "label<TAB>absolute path"

expand_path() {
  # Expands ~ and resolves relative paths from PROJECTS_ROOT.
  local raw="$1"
  case "$raw" in
    "~")   printf '%s' "$HOME" ;;
    "~/"*) printf '%s' "$HOME/${raw#\~/}" ;;
    /*)    printf '%s' "$raw" ;;
    *)
      if [ -n "$PROJECTS_ROOT" ]; then
        printf '%s' "$PROJECTS_ROOT/$raw"
      else
        printf '%s' "$HOME/$raw"
      fi
      ;;
  esac
}

read_spaces_conf() {
  [ -f "$SPACES_CONF" ] || return 0
  local line label path_raw
  # Empty IFS: we preserve the spaces inside labels and paths.
  while IFS= read -r line || [ -n "$line" ]; do
    # Comments and empty lines.
    case "$line" in
      \#*|"") continue ;;
    esac
    # NAME=value directives. Only PROJECTS_ROOT concerns this script; the
    # others (GITHUB_USER, read by install.sh) are ignored silently, so that
    # this file does not have to be edited for every new directive.
    case "$line" in
      PROJECTS_ROOT=*)
        PROJECTS_ROOT="$(expand_path "${line#PROJECTS_ROOT=}")"
        continue
        ;;
      [A-Z_]*=*)
        continue
        ;;
    esac
    # Separator: a tab. A space would not do, both labels and paths commonly
    # contain spaces.
    case "$line" in
      *"	"*) ;;
      *) printf 'spaces.conf: missing tab separator, line ignored: %s\n' "$line" >&2
         continue ;;
    esac
    label="${line%%	*}"
    path_raw="${line#*	}"
    SPACES[${#SPACES[@]}]="$label	$(expand_path "$path_raw")"
  done < "$SPACES_CONF"
}

# --- Talking to the Herdr server -------------------------------------------
existing_labels() {
  # Deliberately python3 rather than jq: python3 is already a hard dependency
  # of the panel, jq is not.
  "$HERDR" workspace list 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for workspace in (data.get("result") or {}).get("workspaces") or []:
    label = workspace.get("label")
    if label:
        print(label)
' 2>/dev/null
}

server_is_up() {
  "$HERDR" status --json >/dev/null 2>&1
}

ensure_spaces() {
  server_is_up || return 0

  local labels
  labels="$(existing_labels)" || return 0

  local entry label path
  local index=0
  while [ "$index" -lt "${#SPACES[@]}" ]; do
    entry="${SPACES[$index]}"
    index=$((index + 1))
    label="${entry%%	*}"
    path="${entry#*	}"
    if printf '%s\n' "$labels" | grep -Fxq "$label"; then
      continue
    fi
    if [ ! -d "$path" ]; then
      printf 'space "%s" skipped: %s not found\n' "$label" "$path" >&2
      continue
    fi
    if "$HERDR" workspace create --cwd "$path" --label "$label" --no-focus >/dev/null 2>&1; then
      printf 'space created: %s\n' "$label"
    fi
  done

  # The stats space starts straight on the panel thanks to the HERDR_AUTOSTART
  # guard (shell/herdr-autostart.zsh). Without that guard, the first pane would
  # be a shell and the panel would open in a useless split.
  if [ -f "$PANEL" ] && ! printf '%s\n' "$labels" | grep -Fxq "$STATS_LABEL"; then
    local panel_cmd="python3 '$PANEL'"
    local env_args=("--env" "HERDR_AUTOSTART=$panel_cmd")
    if [ -n "$PROJECTS_ROOT" ]; then
      env_args[${#env_args[@]}]="--env"
      env_args[${#env_args[@]}]="COCKPIT_PROJECTS_ROOT=$PROJECTS_ROOT"
    fi
    mkdir -p "$STATS_CWD" 2>/dev/null
    if "$HERDR" workspace create \
        --cwd "$STATS_CWD" \
        --label "$STATS_LABEL" \
        "${env_args[@]}" \
        --no-focus >/dev/null 2>&1; then
      printf 'space created: %s\n' "$STATS_LABEL"
    fi
  fi
}

stats_workspace_id() {
  "$HERDR" workspace list 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for workspace in (data.get("result") or {}).get("workspaces") or []:
    if workspace.get("label") == sys.argv[1]:
        print(workspace.get("workspace_id") or "")
        break
' "$STATS_LABEL" 2>/dev/null
}

enforce_single_tab() {
  # Herdr cannot lock a space to a single tab. So we close the extra ones that
  # show up, keeping the one with the smallest number: that is the one holding
  # the panel, the following ones are necessarily later.
  local ws_id
  ws_id="$(stats_workspace_id)"
  [ -z "$ws_id" ] && return 0

  local extra
  extra="$("$HERDR" tab list --workspace "$ws_id" 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tabs = (data.get("result") or {}).get("tabs") or []
tabs.sort(key=lambda t: t.get("number") or 0)
for tab in tabs[1:]:
    if tab.get("tab_id"):
        print(tab["tab_id"])
' 2>/dev/null)"

  [ -z "$extra" ] && return 0
  local tab_id
  while IFS= read -r tab_id; do
    [ -n "$tab_id" ] && "$HERDR" tab close "$tab_id" >/dev/null 2>&1
  done <<EOF
$extra
EOF
}

watch_loop() {
  # The PID file is written by the watcher itself, and removed when it exits
  # whatever the cause.
  mkdir -p "$(dirname "$WATCH_PID_FILE")" 2>/dev/null
  printf '%s\n' "$$" > "$WATCH_PID_FILE"
  trap 'rm -f "$WATCH_PID_FILE"' EXIT INT TERM

  while true; do
    sleep "$INTERVAL"
    # The watcher does not outlive the server: without it there is nothing left
    # to do and it would spin forever for nothing.
    server_is_up || exit 0
    ensure_spaces >/dev/null
    enforce_single_tab
  done
}

start_watcher() {
  # A PID file rather than a pgrep on the script name: that name depends on the
  # path used to call it (symlink or real file), so the pattern missed a
  # watcher started another way and started a second one.
  if [ -f "$WATCH_PID_FILE" ]; then
    local existing
    existing="$(cat "$WATCH_PID_FILE" 2>/dev/null)"
    if [ -n "$existing" ] && kill -0 "$existing" 2>/dev/null; then
      return 0
    fi
    rm -f "$WATCH_PID_FILE"
  fi
  nohup "$SELF" --watch >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

# --- Entry point -----------------------------------------------------------
if [ ! -x "$HERDR" ]; then
  printf 'herdr not found (%s).\n' "$HERDR" >&2
  printf 'Install it from https://herdr.dev, then run again.\n' >&2
  exec "${SHELL:-/bin/zsh}"
fi

read_spaces_conf

case "${1:-}" in
  --watch)
    watch_loop
    ;;
  --ensure)
    ensure_spaces
    enforce_single_tab
    ;;
  --list)
    # Checks how spaces.conf is read without creating anything. Reports the
    # missing paths, the most frequent cause of a space that never shows up.
    printf 'file           : %s\n' "$SPACES_CONF"
    printf 'PROJECTS_ROOT  : %s\n' "${PROJECTS_ROOT:-(not set)}"
    printf 'spaces         : %s\n\n' "${#SPACES[@]}"
    index=0
    while [ "$index" -lt "${#SPACES[@]}" ]; do
      entry="${SPACES[$index]}"
      index=$((index + 1))
      label="${entry%%	*}"
      path="${entry#*	}"
      if [ -d "$path" ]; then
        printf '  ok       %-24s %s\n' "$label" "$path"
      else
        printf '  MISSING  %-24s %s\n' "$label" "$path"
      fi
    done
    ;;
  *)
    ensure_spaces
    start_watcher
    exec "$HERDR" session attach "$SESSION"
    ;;
esac
