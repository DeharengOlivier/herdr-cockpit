#!/bin/bash
# herdr-cockpit : installation.
#
#   ./install.sh              interactive
#   ./install.sh --yes        answers yes to everything (non interactive)
#   ./install.sh --force      overwrites config.toml instead of asking
#   ./install.sh --dry-run    shows what would be done, writes nothing
#
# Principle : nothing is copied, everything is linked. The repository stays the
# source of truth, so a "git pull" updates the installation without redoing it.
# Only ~/.config/herdr/config.toml is generated, because it carries an absolute
# path and because it is yours : it may already hold your own settings.
#
# Any pre-existing file is moved to <file>.bak-<timestamp> and recorded in a
# manifest, which uninstall.sh knows how to replay backwards.

set -uo pipefail

COCKPIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
STATE_DIR="$HOME/.config/herdr-cockpit"
MANIFEST="$STATE_DIR/install-manifest"
STAMP="$(date +%Y%m%d-%H%M%S)"

WEZTERM_CONF="$HOME/.config/wezterm/wezterm.lua"
HERDR_CONF="$HOME/.config/herdr/config.toml"
ZSHRC="$HOME/.zshrc"

ASSUME_YES=0
FORCE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)  ASSUME_YES=1 ;;
    --force)   FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown option : %s\n' "$arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  [ -t 0 ] || return 1
  local answer
  printf '    %s [y/N] ' "$1"
  read -r answer </dev/tty || return 1
  case "$answer" in [oOyY]*) return 0 ;; *) return 1 ;; esac
}

run() {
  # Every write goes through here, so that --dry-run is genuinely safe.
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] %s\n' "$*"
    return 0
  fi
  "$@"
}

record() {
  # type <TAB> target <TAB> backup ("" when the target did not exist)
  [ "$DRY_RUN" = "1" ] && return 0
  printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" >>"$MANIFEST"
}

backup_if_present() {
  # Moves an existing file or link aside, returns the backup path.
  local target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    local backup="$target.bak-$STAMP"
    run mv "$target" "$backup"
    printf '%s' "$backup"
  fi
}

backup_copy() {
  # Backs up while leaving the original in place : for the files we append to
  # (~/.zshrc) rather than replace.
  local target="$1"
  if [ -e "$target" ]; then
    local backup="$target.bak-$STAMP"
    run cp "$target" "$backup"
    printf '%s' "$backup"
  fi
}

link() {
  local source="$1" target="$2" label="$3"
  if [ ! -e "$source" ]; then
    err "$label : source not found ($source)"
    return 1
  fi
  # Already pointing at the right place : we touch nothing.
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    ok "$label already linked"
    return 0
  fi
  local backup
  backup="$(backup_if_present "$target")"
  run mkdir -p "$(dirname "$target")"
  run ln -s "$source" "$target"
  record link "$target" "$backup"
  if [ -n "$backup" ]; then
    ok "$label linked (previous file backed up as $(basename "$backup"))"
  else
    ok "$label linked"
  fi
}

# --- 1. Dependencies -------------------------------------------------------
step "Dependencies"

missing=0
if command -v herdr >/dev/null 2>&1; then
  ok "herdr $(herdr --version 2>/dev/null | awk '{print $2}')"
else
  err "herdr missing. Install it : brew install herdr   (or https://herdr.dev)"
  missing=1
fi

if command -v wezterm >/dev/null 2>&1 || [ -d "/Applications/WezTerm.app" ]; then
  ok "WezTerm present"
else
  err "WezTerm missing. Install it : brew install --cask wezterm"
  missing=1
fi

if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
else
  err "python3 missing. Required by the statistics panel."
  missing=1
fi

if command -v quota-axi >/dev/null 2>&1; then
  ok "quota-axi present (subscription quotas enabled)"
else
  warn "quota-axi missing : the panel will work, without the quotas section."
  warn "  To add it : npm install -g quota-axi"
fi

if [ "$missing" != "0" ]; then
  printf '\nInstallation aborted : a required dependency is missing.\n' >&2
  exit 1
fi

[ "$DRY_RUN" = "1" ] || mkdir -p "$STATE_DIR" "$BIN_DIR"

# --- 2. spaces.conf --------------------------------------------------------
step "Your spaces"

SPACES_CREATED=0
if [ -f "$COCKPIT_DIR/spaces.conf" ]; then
  count="$(grep -c "$(printf '\t')" "$COCKPIT_DIR/spaces.conf" 2>/dev/null || echo 0)"
  ok "spaces.conf present ($count space(s) declared)"
else
  run cp "$COCKPIT_DIR/spaces.conf.example" "$COCKPIT_DIR/spaces.conf"
  SPACES_CREATED=1
  warn "spaces.conf created from the example. It holds placeholder paths."
fi

# --- 3. GitHub badge -------------------------------------------------------
step "GitHub profile"

GITHUB_USER=""
if [ -f "$COCKPIT_DIR/spaces.conf" ]; then
  GITHUB_USER="$(sed -n 's/^GITHUB_USER=[[:space:]]*//p' "$COCKPIT_DIR/spaces.conf" \
    | head -1 | tr -d '[:space:]')"
fi

if [ -z "$GITHUB_USER" ]; then
  warn "No GITHUB_USER in spaces.conf, so no badge in the panel."
  warn "  Fill it in then run ./install.sh again to add it."
elif [ "$DRY_RUN" = "1" ]; then
  printf '    [dry-run] generate the GitHub badge for %s\n' "$GITHUB_USER"
else
  if badge_output="$(python3 "$COCKPIT_DIR/bin/github-badge.py" "$GITHUB_USER" 2>&1)"; then
    ok "badge generated for $GITHUB_USER"
    record generated "$STATE_DIR/github-badge.json" ""
  else
    # Never blocking : the panel works without a badge.
    warn "badge not generated : $badge_output"
  fi
fi

# --- 4. Commands -----------------------------------------------------------
step "Commands"

run chmod +x "$COCKPIT_DIR/bin/bootstrap.sh" "$COCKPIT_DIR/stats/panel.py"
link "$COCKPIT_DIR/bin/bootstrap.sh" "$BIN_DIR/herdr-cockpit-bootstrap" "herdr-cockpit-bootstrap"
link "$COCKPIT_DIR/stats/panel.py"   "$BIN_DIR/herdr-cockpit-panel"     "herdr-cockpit-panel"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not in your PATH. This is not blocking : WezTerm"
     warn "  and Herdr use absolute paths." ;;
esac

# --- 5. WezTerm ------------------------------------------------------------
step "WezTerm"
link "$COCKPIT_DIR/config/wezterm.lua" "$WEZTERM_CONF" "wezterm.lua"

# --- 6. Herdr --------------------------------------------------------------
step "Herdr"

generate_herdr_conf() {
  # The only file generated rather than linked : it carries an absolute path.
  # The destination is passed as an argument, never read from a global.
  local final_destination="$1"
  local tmp="$final_destination.tmp-$STAMP"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] generate %s\n' "$final_destination"
    return 0
  fi
  mkdir -p "$(dirname "$final_destination")"
  # Substitution done in python3 : sed would break on paths containing / or &.
  COCKPIT_PANEL="$COCKPIT_DIR/stats/panel.py" python3 - "$COCKPIT_DIR/config/herdr/config.toml" "$tmp" <<'PY'
import os, sys
source, destination = sys.argv[1], sys.argv[2]
with open(source, encoding="utf-8") as handle:
    content = handle.read()
content = content.replace("@@COCKPIT_PANEL@@", os.environ["COCKPIT_PANEL"])
with open(destination, "w", encoding="utf-8") as handle:
    handle.write(content)
PY
  mv "$tmp" "$final_destination"
}

if [ ! -e "$HERDR_CONF" ]; then
  generate_herdr_conf "$HERDR_CONF"
  record generated "$HERDR_CONF" ""
  ok "config.toml generated"
elif [ "$FORCE" = "1" ] || confirm "config.toml already exists. Replace it ? (a backup is kept)"; then
  backup="$(backup_if_present "$HERDR_CONF")"
  generate_herdr_conf "$HERDR_CONF"
  record generated "$HERDR_CONF" "$backup"
  ok "config.toml replaced (previous one in $(basename "${backup:-none}"))"
else
  # We do not merge blindly : this file may carry your own settings, and an
  # approximate TOML merge would break both of them.
  sidecar="$HERDR_CONF.cockpit"
  generate_herdr_conf "$sidecar"
  warn "config.toml kept. Cockpit version written next to it :"
  warn "  $sidecar"
  warn "Compare then merge by hand :"
  warn "  diff -u $HERDR_CONF $sidecar"
fi

if command -v herdr >/dev/null 2>&1 && [ "$DRY_RUN" != "1" ]; then
  if herdr config check >/dev/null 2>&1; then
    ok "herdr config check : ok"
  else
    err "herdr config check reports a problem :"
    herdr config check 2>&1 | sed 's/^/      /' >&2
  fi
fi

# --- 7. zsh guard ----------------------------------------------------------
step "Shell"

GUARD_LINE="[ -f \"$COCKPIT_DIR/shell/herdr-autostart.zsh\" ] && source \"$COCKPIT_DIR/shell/herdr-autostart.zsh\""

# We look for the variable, not for the file name : a guard written by hand
# straight into the .zshrc counts just as much, and adding a second one would
# only duplicate the loop.
if [ -f "$ZSHRC" ] && grep -Fq "HERDR_AUTOSTART" "$ZSHRC"; then
  ok "HERDR_AUTOSTART guard already present in ~/.zshrc"
elif confirm "Add the HERDR_AUTOSTART guard to ~/.zshrc ? (without it, the Stats space opens twice)"; then
  backup="$(backup_copy "$ZSHRC")"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] add the guard to %s\n' "$ZSHRC"
  else
    # Marked block : uninstall.sh removes it by its markers, which works even
    # when this ~/.zshrc did not exist before and therefore has no backup, and
    # without ever touching the rest of the file.
    {
      printf '\n# >>> herdr-cockpit >>>\n'
      printf '# Launches an application straight into a space.\n'
      printf '%s\n' "$GUARD_LINE"
      printf '# <<< herdr-cockpit <<<\n'
    } >>"$ZSHRC"
  fi
  record zshrc "$ZSHRC" "$backup"
  ok "guard added to ~/.zshrc"
else
  warn "Guard not installed. The Stats space will open a shell, then the panel"
  warn "  in a second pane. To add it later, put this in ~/.zshrc :"
  warn "  $GUARD_LINE"
fi

# --- 8. What next ----------------------------------------------------------
step "Done"

if [ "$SPACES_CREATED" = "1" ]; then
  printf '\n  1. Declare your projects :  %s\n' "$COCKPIT_DIR/spaces.conf"
  printf '  2. Open WezTerm.\n\n'
else
  printf '\n  Open WezTerm : Herdr starts with your spaces.\n\n'
fi
printf '  Shortcuts : Cmd+T tab, Cmd+D split, Cmd+arrows navigation,\n'
printf '              Cmd+B sidebar, Ctrl-b then i cost panel.\n'
printf '  Uninstall : %s/uninstall.sh\n\n' "$COCKPIT_DIR"
