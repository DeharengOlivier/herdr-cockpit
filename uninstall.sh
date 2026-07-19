#!/bin/bash
# herdr-cockpit : uninstallation.
#
#   ./uninstall.sh              interactive
#   ./uninstall.sh --yes        no confirmation
#   ./uninstall.sh --dry-run    shows what would be done
#
# Replays the install manifest backwards : every link laid down is removed,
# every backed up file is put back. Whatever existed before is therefore
# restored, including an earlier ~/.zshrc and an earlier config.toml.
#
# What this script does not touch : the repository itself, your spaces.conf,
# and Herdr, WezTerm or python3, which are independent installations.

set -uo pipefail

STATE_DIR="$HOME/.config/herdr-cockpit"
MANIFEST="$STATE_DIR/install-manifest"

ASSUME_YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)  ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown option : %s\n' "$arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '  [dry-run] %s\n' "$*"
    return 0
  fi
  "$@"
}

if [ ! -f "$MANIFEST" ]; then
  printf 'No manifest : nothing has been installed from this repository.\n' >&2
  printf 'Expected : %s\n' "$MANIFEST" >&2
  exit 1
fi

printf '\nTo be restored, according to %s :\n\n' "$MANIFEST"
while IFS="	" read -r kind target backup; do
  [ -z "${kind:-}" ] && continue
  if [ -n "${backup:-}" ]; then
    printf '  %-10s %s\n             (restored from %s)\n' "$kind" "$target" "$(basename "$backup")"
  else
    printf '  %-10s %s\n             (will simply be removed)\n' "$kind" "$target"
  fi
done <"$MANIFEST"
printf '\n'

if [ "$ASSUME_YES" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  if [ ! -t 0 ]; then
    printf 'Non interactive session : run again with --yes.\n' >&2
    exit 1
  fi
  printf 'Confirm the uninstallation ? [y/N] '
  read -r answer </dev/tty || answer=""
  case "$answer" in [oOyY]*) ;; *) printf 'Cancelled.\n'; exit 0 ;; esac
fi

printf '\n'

# Backwards : the most recent entries first, so that successive installs onto
# the same target are undone in the right order.
LINES="$(awk '{ lines[NR] = $0 } END { for (i = NR; i >= 1; i--) print lines[i] }' "$MANIFEST")"

printf '%s\n' "$LINES" | while IFS="	" read -r kind target backup; do
  [ -z "${kind:-}" ] && continue

  case "$kind" in
    zshrc)
      # We remove our block by its markers rather than restoring the backup :
      # that works even without a backup (a file we created ourselves) and it
      # preserves everything you have added to the file since the install.
      # The backup stays on disk.
      if [ -f "$target" ]; then
        if [ "$DRY_RUN" = "1" ]; then
          printf '  [dry-run] remove the herdr-cockpit block from %s\n' "$target"
        else
          python3 - "$target" <<'PY'
import sys

path = sys.argv[1]
with open(path, encoding="utf-8", errors="replace") as handle:
    lines = handle.readlines()

kept, inside_block = [], False
for line in lines:
    stripped = line.strip()
    if stripped == "# >>> herdr-cockpit >>>":
        inside_block = True
        continue
    if stripped == "# <<< herdr-cockpit <<<":
        inside_block = False
        continue
    if not inside_block:
        kept.append(line)

# We do not leave an orphan blank line where the block used to be.
while kept and not kept[-1].strip():
    kept.pop()
if kept:
    kept[-1] = kept[-1].rstrip("\n") + "\n"

with open(path, "w", encoding="utf-8") as handle:
    handle.writelines(kept)
PY
        fi
        ok "herdr-cockpit block removed from ~/.zshrc"
      fi
      ;;
    link|generated)
      if [ -e "$target" ] || [ -L "$target" ]; then
        run rm -f "$target"
      fi
      if [ -n "${backup:-}" ] && { [ -e "$backup" ] || [ -L "$backup" ]; }; then
        run mv "$backup" "$target"
        ok "$(basename "$target") restored"
      else
        ok "$(basename "$target") removed"
      fi
      ;;
    *)
      warn "unknown manifest entry, ignored : $kind"
      ;;
  esac
done

if [ "$DRY_RUN" != "1" ]; then
  rm -f "$MANIFEST"
  rmdir "$STATE_DIR" 2>/dev/null || true
fi

printf '\n  Uninstalled. The repository and your spaces.conf are untouched.\n'
printf '  Herdr may still be running : herdr server stop\n\n'
