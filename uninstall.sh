#!/bin/bash
# herdr-cockpit : desinstallation.
#
#   ./uninstall.sh              interactif
#   ./uninstall.sh --yes        sans confirmation
#   ./uninstall.sh --dry-run    montre ce qui serait fait
#
# Rejoue le manifeste d'installation a l'envers : chaque lien pose est retire,
# chaque fichier sauvegarde est remis en place. Ce qui existait avant est donc
# restaure, y compris un ~/.zshrc et un config.toml anterieurs.
#
# Ce que ce script ne touche pas : le depot lui-meme, votre spaces.conf, et
# Herdr, WezTerm ou python3, qui sont des installations independantes.

set -uo pipefail

STATE_DIR="$HOME/.config/herdr-cockpit"
MANIFEST="$STATE_DIR/install-manifest"

ASSUME_YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)  ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'option inconnue : %s\n' "$arg" >&2; exit 2 ;;
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
  printf 'Aucun manifeste : rien n a ete installe depuis ce depot.\n' >&2
  printf 'Attendu : %s\n' "$MANIFEST" >&2
  exit 1
fi

printf '\nA restaurer, d apres %s :\n\n' "$MANIFEST"
while IFS="	" read -r kind target backup; do
  [ -z "${kind:-}" ] && continue
  if [ -n "${backup:-}" ]; then
    printf '  %-10s %s\n             (restaure depuis %s)\n' "$kind" "$target" "$(basename "$backup")"
  else
    printf '  %-10s %s\n             (sera simplement retire)\n' "$kind" "$target"
  fi
done <"$MANIFEST"
printf '\n'

if [ "$ASSUME_YES" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  if [ ! -t 0 ]; then
    printf 'Sortie non interactive : relancez avec --yes.\n' >&2
    exit 1
  fi
  printf 'Confirmer la desinstallation ? [o/N] '
  read -r answer </dev/tty || answer=""
  case "$answer" in [oOyY]*) ;; *) printf 'Annule.\n'; exit 0 ;; esac
fi

printf '\n'

# A l'envers : les entrees les plus recentes d'abord, pour que des poses
# successives sur une meme cible se defassent dans le bon ordre.
LINES="$(awk '{ lines[NR] = $0 } END { for (i = NR; i >= 1; i--) print lines[i] }' "$MANIFEST")"

printf '%s\n' "$LINES" | while IFS="	" read -r kind target backup; do
  [ -z "${kind:-}" ] && continue

  case "$kind" in
    zshrc)
      # On retire notre bloc par ses marqueurs plutot que de restaurer la
      # sauvegarde : cela marche meme sans sauvegarde (fichier que nous avons
      # cree nous-memes) et cela preserve tout ce que vous avez ajoute au
      # fichier depuis l installation. La sauvegarde reste sur le disque.
      if [ -f "$target" ]; then
        if [ "$DRY_RUN" = "1" ]; then
          printf '  [dry-run] retirer le bloc herdr-cockpit de %s\n' "$target"
        else
          python3 - "$target" <<'PY'
import sys

chemin = sys.argv[1]
with open(chemin, encoding="utf-8", errors="replace") as handle:
    lignes = handle.readlines()

garde, dans_le_bloc = [], False
for ligne in lignes:
    nu = ligne.strip()
    if nu == "# >>> herdr-cockpit >>>":
        dans_le_bloc = True
        continue
    if nu == "# <<< herdr-cockpit <<<":
        dans_le_bloc = False
        continue
    if not dans_le_bloc:
        garde.append(ligne)

# On ne laisse pas une ligne vide orpheline la ou etait le bloc.
while garde and not garde[-1].strip():
    garde.pop()
if garde:
    garde[-1] = garde[-1].rstrip("\n") + "\n"

with open(chemin, "w", encoding="utf-8") as handle:
    handle.writelines(garde)
PY
        fi
        ok "bloc herdr-cockpit retire de ~/.zshrc"
      fi
      ;;
    link|generated)
      if [ -e "$target" ] || [ -L "$target" ]; then
        run rm -f "$target"
      fi
      if [ -n "${backup:-}" ] && { [ -e "$backup" ] || [ -L "$backup" ]; }; then
        run mv "$backup" "$target"
        ok "$(basename "$target") restaure"
      else
        ok "$(basename "$target") retire"
      fi
      ;;
    *)
      warn "entree de manifeste inconnue, ignoree : $kind"
      ;;
  esac
done

if [ "$DRY_RUN" != "1" ]; then
  rm -f "$MANIFEST"
  rmdir "$STATE_DIR" 2>/dev/null || true
fi

printf '\n  Desinstalle. Le depot et votre spaces.conf sont intacts.\n'
printf '  Herdr tourne peut-etre encore : herdr server stop\n\n'
