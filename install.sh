#!/bin/bash
# herdr-cockpit : installation.
#
#   ./install.sh              interactive
#   ./install.sh --yes        answers yes to everything (non interactive)
#   ./install.sh --force      overwrites config.toml instead of asking
#   ./install.sh --dry-run    shows what would be done, writes nothing
#   ./install.sh --check      reports on an existing installation, writes nothing
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

AUTOSTART_SCRIPT="$COCKPIT_DIR/shell/herdr-autostart.zsh"
GUARD_LINE="[ -f \"$AUTOSTART_SCRIPT\" ] && source \"$AUTOSTART_SCRIPT\""
BLOCK_START="# >>> herdr-cockpit >>>"
BLOCK_END="# <<< herdr-cockpit <<<"

ASSUME_YES=0
FORCE=0
DRY_RUN=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)  ASSUME_YES=1 ;;
    --force)   FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --check)   CHECK_ONLY=1 ;;
    --help|-h) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# --- 0. Checking an existing installation ----------------------------------
# Everything laid down here can be undone by something else: a clone that moved
# leaves dangling links, a dotfile manager overwrites ~/.zshrc, a package
# replaces wezterm.lua with a real file. From the outside all of those look the
# same, the cockpit simply stops behaving. This says which one happened.

guard_is_present() {
  [ -f "$1" ] || return 1
  grep -Fq -e "$BLOCK_START" -e "herdr-autostart.zsh" -e "HERDR_AUTOSTART" "$1"
}

panel_referenced_by() {
  # The command the generated config.toml runs for the popup panel. It carries
  # an absolute path, which is exactly what a moved repository breaks while
  # `herdr config check` still passes.
  python3 - "$1" <<'PY'
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        content = handle.read()
except OSError:
    sys.exit(0)
match = re.search("command = \"python3 '([^']*)'\"", content)
if match:
    print(match.group(1))
PY
}

check_link() {
  local target="$1" pointed_at name
  name="$(basename "$target")"
  if [ -L "$target" ]; then
    pointed_at="$(readlink "$target")"
    if [ ! -e "$target" ]; then
      err "$name points at $pointed_at, which does not exist (repository moved?)"
      return 1
    fi
    case "$pointed_at" in
      "$COCKPIT_DIR"/*) ok "$name links into this repository"; return 0 ;;
      *) err "$name points outside this repository: $pointed_at"; return 1 ;;
    esac
  elif [ -e "$target" ]; then
    err "$name is no longer a link: a real file has taken its place"
    return 1
  else
    err "$name is gone from $(dirname "$target")"
    return 1
  fi
}

check_generated() {
  local target="$1" name panel
  name="$(basename "$target")"
  if [ ! -e "$target" ]; then
    err "$name is gone from $(dirname "$target")"
    return 1
  fi
  case "$target" in
    */config.toml)
      panel="$(panel_referenced_by "$target")"
      if [ -z "$panel" ]; then
        err "$name no longer names the cockpit panel"
        return 1
      fi
      if [ ! -e "$panel" ]; then
        err "$name points at a panel that does not exist: $panel"
        return 1
      fi
      ok "$name names a panel that exists"
      ;;
    *) ok "$name present" ;;
  esac
  return 0
}

check_installation() {
  if [ ! -f "$MANIFEST" ]; then
    printf 'No manifest: nothing was installed from this repository.\n' >&2
    printf 'Expected: %s\n' "$MANIFEST" >&2
    return 1
  fi

  step "Installation"
  # The manifest is append-only, so installing twice leaves two lines for the
  # same target. Only the last one describes the state on disk: reporting the
  # earlier ones again is noise that hides a real problem further down. awk
  # keeps the last line per target while preserving the manifest's order.
  #
  # zshrc entries are dropped here and the guard is checked once, below: it is
  # a property of the installation rather than of a manifest line, and
  # declining the prompt and pasting the line by hand leaves no entry at all.
  local entries
  entries="$(awk -F'\t' '
    $1 != "zshrc" && !($2 in seen) { order[++count] = $2 }
    $1 != "zshrc" { seen[$2] = $1 }
    END { for (i = 1; i <= count; i++) print seen[order[i]] "\t" order[i] }
  ' "$MANIFEST")"

  local problems=0 kind target
  while IFS="	" read -r kind target; do
    [ -z "${kind:-}" ] && continue
    case "$kind" in
      link)      check_link "$target"      || problems=$((problems + 1)) ;;
      generated) check_generated "$target" || problems=$((problems + 1)) ;;
      *) warn "unknown manifest entry, ignored: $kind" ;;
    esac
  done <<EOF
$entries
EOF

  # Declining the guard is a supported choice, so its absence is reported
  # without failing the check: the panel still works, it just opens in a
  # second pane behind a useless shell.
  if guard_is_present "$ZSHRC"; then
    ok "autostart guard present in $(basename "$ZSHRC")"
  else
    warn "no autostart guard in $ZSHRC: the Stats space will open a shell first"
  fi

  printf '\n'
  if [ "$problems" = 0 ]; then
    printf '  Installation intact, nothing to repair.\n\n'
    return 0
  fi
  printf '  %s problem(s). Run ./install.sh again to lay it back down,\n' "$problems"
  printf '  or ./uninstall.sh to remove what is left.\n\n'
  return 1
}

if [ "$CHECK_ONLY" = "1" ]; then
  check_installation
  exit $?
fi

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

# Three shapes count as "already installed", and all three are searched for in
# the ~/.zshrc itself : our marked block, a source line pasted by hand, and a
# guard someone inlined around the variable.
#
# Probing for HERDR_AUTOSTART alone used to miss our own block. That variable
# lives in shell/herdr-autostart.zsh, which the .zshrc only sources, so the
# probe never matched the line the installer had just written : a second run
# appended a second block, and a second autostart loop behind it. The block is
# now written from the same BLOCK_START the probe reads, so the two cannot
# drift apart again.
if guard_is_present "$ZSHRC"; then
  ok "autostart guard already present in ~/.zshrc"
elif confirm "Add the autostart guard to ~/.zshrc ? (without it, the Stats space opens twice)"; then
  backup="$(backup_copy "$ZSHRC")"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] add the guard to %s\n' "$ZSHRC"
  else
    # Marked block : uninstall.sh removes it by its markers, which works even
    # when this ~/.zshrc did not exist before and therefore has no backup, and
    # without ever touching the rest of the file.
    {
      printf '\n%s\n' "$BLOCK_START"
      printf '# Launches an application straight into a space.\n'
      printf '%s\n' "$GUARD_LINE"
      printf '%s\n' "$BLOCK_END"
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
