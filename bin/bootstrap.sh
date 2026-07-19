#!/bin/bash
# herdr-cockpit : provisionne les spaces Herdr, puis attache la session.
#
#   bootstrap.sh            provisionne + surveille en fond + attache la session
#   bootstrap.sh --ensure   provisionne seulement, puis rend la main
#   bootstrap.sh --watch    boucle de surveillance (usage interne)
#
# C'est ce script que WezTerm lance a l'ouverture (voir config/wezterm.lua).
#
# Herdr ne sait pas proteger un space contre la fermeture : le raccourci peut
# etre desactive, mais l'entree "close" du menu de la barre laterale n'est pas
# masquable. La surveillance est donc le seul moyen de garantir qu'un space
# ferme par megarde revienne.
#
# Compatible bash 3.2 (la version livree avec macOS) : pas de tableau
# associatif, pas de readarray, pas de ${var,,}.

set -uo pipefail

# --- Localisation du depot -------------------------------------------------
# Le script est appele via un lien symbolique depuis ~/.local/bin. On remonte
# la chaine de liens pour retrouver la racine du depot, ce qui permet de le
# deplacer ou de le mettre a jour par git pull sans jamais reinstaller.
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
# Le space de statistiques ne pointe volontairement PAS sur le depot : la barre
# laterale affiche la branche git sous le libelle d'un space, et "main" sous
# "▦ Stats" n'a aucun sens. Ce dossier n'est pas un depot, donc rien ne
# s'affiche. Le panneau est lance par chemin absolu, le cwd ne le concerne pas.
STATS_CWD="${COCKPIT_STATS_CWD:-$HOME/.config/herdr-cockpit}"
INTERVAL="${COCKPIT_WATCH_INTERVAL:-2}"
SESSION="${COCKPIT_SESSION:-default}"
WATCH_PID_FILE="${COCKPIT_WATCH_PID_FILE:-$HOME/.config/herdr-cockpit/watch.pid}"

# --- Lecture de spaces.conf ------------------------------------------------
# Format : une directive PROJECTS_ROOT=... optionnelle, puis des lignes
# "label <TAB> chemin". Les chemins relatifs sont resolus depuis PROJECTS_ROOT.
PROJECTS_ROOT=""
SPACES=()          # entrees "label<TAB>chemin absolu"

expand_path() {
  # Developpe ~ et resout les chemins relatifs depuis PROJECTS_ROOT.
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
  # IFS vide : on preserve les espaces des libelles et des chemins.
  while IFS= read -r line || [ -n "$line" ]; do
    # Commentaires et lignes vides.
    case "$line" in
      \#*|"") continue ;;
    esac
    # Directives NOM=valeur. Seule PROJECTS_ROOT concerne ce script ; les
    # autres (GITHUB_USER, lues par install.sh) sont ignorees sans bruit,
    # pour ne pas avoir a modifier ce fichier a chaque nouvelle directive.
    case "$line" in
      PROJECTS_ROOT=*)
        PROJECTS_ROOT="$(expand_path "${line#PROJECTS_ROOT=}")"
        continue
        ;;
      [A-Z_]*=*)
        continue
        ;;
    esac
    # Separateur : tabulation. L'espace ne convient pas, les libelles comme
    # les chemins en contiennent couramment.
    case "$line" in
      *"	"*) ;;
      *) printf 'spaces.conf : separateur tabulation manquant, ligne ignoree : %s\n' "$line" >&2
         continue ;;
    esac
    label="${line%%	*}"
    path_raw="${line#*	}"
    SPACES[${#SPACES[@]}]="$label	$(expand_path "$path_raw")"
  done < "$SPACES_CONF"
}

# --- Dialogue avec le serveur Herdr ----------------------------------------
existing_labels() {
  # Volontairement en python3 plutot qu'en jq : python3 est deja une
  # dependance dure du panneau, jq ne l'est pas.
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
      printf 'space "%s" ignore : %s est introuvable\n' "$label" "$path" >&2
      continue
    fi
    if "$HERDR" workspace create --cwd "$path" --label "$label" --no-focus >/dev/null 2>&1; then
      printf 'space cree : %s\n' "$label"
    fi
  done

  # Le space de statistiques demarre directement sur le panneau grace au garde
  # HERDR_AUTOSTART (shell/herdr-autostart.zsh). Sans ce garde, la premiere
  # pane serait un shell et le panneau s'ouvrirait dans un split inutile.
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
      printf 'space cree : %s\n' "$STATS_LABEL"
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
  # Herdr ne sait pas verrouiller un space sur un seul onglet. On ferme donc
  # ceux qui apparaissent en trop, en gardant celui du plus petit numero :
  # c'est celui qui porte le panneau, les suivants sont forcement posterieurs.
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
  # Le fichier de PID est ecrit par la surveillance elle-meme, et efface a sa
  # sortie quelle qu'en soit la cause.
  mkdir -p "$(dirname "$WATCH_PID_FILE")" 2>/dev/null
  printf '%s\n' "$$" > "$WATCH_PID_FILE"
  trap 'rm -f "$WATCH_PID_FILE"' EXIT INT TERM

  while true; do
    sleep "$INTERVAL"
    # La surveillance ne survit pas au serveur : sans lui elle n'a plus d'objet
    # et tournerait indefiniment dans le vide.
    server_is_up || exit 0
    ensure_spaces >/dev/null
    enforce_single_tab
  done
}

start_watcher() {
  # Un fichier de PID plutot qu'un pgrep sur le nom du script : celui-ci
  # depend du chemin d'appel (lien symbolique ou fichier reel), donc le motif
  # ratait une surveillance lancee autrement et en demarrait une deuxieme.
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

# --- Entree ----------------------------------------------------------------
if [ ! -x "$HERDR" ]; then
  printf 'herdr introuvable (%s).\n' "$HERDR" >&2
  printf 'Installez-le depuis https://herdr.dev, puis relancez.\n' >&2
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
    # Verifie la lecture de spaces.conf sans rien creer. Signale les chemins
    # absents, cause la plus frequente d'un space qui n'apparait pas.
    printf 'fichier        : %s\n' "$SPACES_CONF"
    printf 'PROJECTS_ROOT  : %s\n' "${PROJECTS_ROOT:-(non defini)}"
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
        printf '  ABSENT   %-24s %s\n' "$label" "$path"
      fi
    done
    ;;
  *)
    ensure_spaces
    start_watcher
    exec "$HERDR" session attach "$SESSION"
    ;;
esac
