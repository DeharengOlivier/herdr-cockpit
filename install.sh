#!/bin/bash
# herdr-cockpit : installation.
#
#   ./install.sh              interactif
#   ./install.sh --yes        repond oui a tout (non interactif)
#   ./install.sh --force      ecrase config.toml au lieu de demander
#   ./install.sh --dry-run    montre ce qui serait fait, n'ecrit rien
#
# Principe : rien n'est copie, tout est lie. Le depot reste la source de
# verite, un "git pull" met donc a jour l'installation sans la refaire.
# Seul ~/.config/herdr/config.toml est genere, parce qu'il contient un chemin
# absolu et qu'il vous appartient : il peut deja porter vos propres reglages.
#
# Tout fichier existant est deplace en <fichier>.bak-<horodatage> et consigne
# dans un manifeste, que uninstall.sh sait rejouer a l'envers.

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
    --help|-h) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'option inconnue : %s\n' "$arg" >&2; exit 2 ;;
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
  printf '    %s [o/N] ' "$1"
  read -r answer </dev/tty || return 1
  case "$answer" in [oOyY]*) return 0 ;; *) return 1 ;; esac
}

run() {
  # Toute ecriture passe par ici, pour que --dry-run soit reellement sur.
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] %s\n' "$*"
    return 0
  fi
  "$@"
}

record() {
  # type <TAB> cible <TAB> sauvegarde ("" si la cible n'existait pas)
  [ "$DRY_RUN" = "1" ] && return 0
  printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" >>"$MANIFEST"
}

backup_if_present() {
  # Deplace un fichier ou lien existant, renvoie le chemin de sauvegarde.
  local target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    local backup="$target.bak-$STAMP"
    run mv "$target" "$backup"
    printf '%s' "$backup"
  fi
}

backup_copy() {
  # Sauvegarde en laissant l'original en place : pour les fichiers qu'on
  # complete (~/.zshrc) plutot que remplace.
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
    err "$label : source introuvable ($source)"
    return 1
  fi
  # Deja pointe au bon endroit : on ne touche a rien.
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    ok "$label deja lie"
    return 0
  fi
  local backup
  backup="$(backup_if_present "$target")"
  run mkdir -p "$(dirname "$target")"
  run ln -s "$source" "$target"
  record link "$target" "$backup"
  if [ -n "$backup" ]; then
    ok "$label lie (ancien fichier sauvegarde en $(basename "$backup"))"
  else
    ok "$label lie"
  fi
}

# --- 1. Dependances --------------------------------------------------------
step "Dependances"

missing=0
if command -v herdr >/dev/null 2>&1; then
  ok "herdr $(herdr --version 2>/dev/null | awk '{print $2}')"
else
  err "herdr absent. Installez-le : brew install herdr   (ou https://herdr.dev)"
  missing=1
fi

if command -v wezterm >/dev/null 2>&1 || [ -d "/Applications/WezTerm.app" ]; then
  ok "WezTerm present"
else
  err "WezTerm absent. Installez-le : brew install --cask wezterm"
  missing=1
fi

if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
else
  err "python3 absent. Requis par le panneau de statistiques."
  missing=1
fi

if command -v quota-axi >/dev/null 2>&1; then
  ok "quota-axi present (quotas d'abonnement actifs)"
else
  warn "quota-axi absent : le panneau marchera, sans la section des quotas."
  warn "  Pour l'ajouter : npm install -g quota-axi"
fi

if [ "$missing" != "0" ]; then
  printf '\nInstallation interrompue : une dependance obligatoire manque.\n' >&2
  exit 1
fi

[ "$DRY_RUN" = "1" ] || mkdir -p "$STATE_DIR" "$BIN_DIR"

# --- 2. spaces.conf --------------------------------------------------------
step "Vos spaces"

SPACES_CREATED=0
if [ -f "$COCKPIT_DIR/spaces.conf" ]; then
  count="$(grep -c "$(printf '\t')" "$COCKPIT_DIR/spaces.conf" 2>/dev/null || echo 0)"
  ok "spaces.conf present ($count space(s) declare(s))"
else
  run cp "$COCKPIT_DIR/spaces.conf.example" "$COCKPIT_DIR/spaces.conf"
  SPACES_CREATED=1
  warn "spaces.conf cree depuis l'exemple. Il contient des chemins fictifs."
fi

# --- 3. Badge GitHub -------------------------------------------------------
step "Profil GitHub"

GITHUB_USER=""
if [ -f "$COCKPIT_DIR/spaces.conf" ]; then
  GITHUB_USER="$(sed -n 's/^GITHUB_USER=[[:space:]]*//p' "$COCKPIT_DIR/spaces.conf" \
    | head -1 | tr -d '[:space:]')"
fi

if [ -z "$GITHUB_USER" ]; then
  warn "Pas de GITHUB_USER dans spaces.conf, donc pas de badge dans le panneau."
  warn "  Renseignez-le puis relancez ./install.sh pour l'ajouter."
elif [ "$DRY_RUN" = "1" ]; then
  printf '    [dry-run] generer le badge GitHub pour %s\n' "$GITHUB_USER"
else
  if badge_output="$(python3 "$COCKPIT_DIR/bin/github-badge.py" "$GITHUB_USER" 2>&1)"; then
    ok "badge genere pour $GITHUB_USER"
    record generated "$STATE_DIR/github-badge.json" ""
  else
    # Jamais bloquant : le panneau fonctionne sans badge.
    warn "badge non genere : $badge_output"
  fi
fi

# --- 4. Commandes ----------------------------------------------------------
step "Commandes"

run chmod +x "$COCKPIT_DIR/bin/bootstrap.sh" "$COCKPIT_DIR/stats/panel.py"
link "$COCKPIT_DIR/bin/bootstrap.sh" "$BIN_DIR/herdr-cockpit-bootstrap" "herdr-cockpit-bootstrap"
link "$COCKPIT_DIR/stats/panel.py"   "$BIN_DIR/herdr-cockpit-panel"     "herdr-cockpit-panel"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR n'est pas dans votre PATH. Ce n'est pas bloquant : WezTerm"
     warn "  et Herdr utilisent des chemins absolus." ;;
esac

# --- 5. WezTerm ------------------------------------------------------------
step "WezTerm"
link "$COCKPIT_DIR/config/wezterm.lua" "$WEZTERM_CONF" "wezterm.lua"

# --- 6. Herdr --------------------------------------------------------------
step "Herdr"

generate_herdr_conf() {
  # Le seul fichier genere plutot que lie : il porte un chemin absolu.
  # La destination est passee en argument, jamais lue depuis une globale.
  local destination_final="$1"
  local tmp="$destination_final.tmp-$STAMP"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] generer %s\n' "$destination_final"
    return 0
  fi
  mkdir -p "$(dirname "$destination_final")"
  # Substitution en python3 : sed casserait sur les chemins contenant / ou &.
  COCKPIT_PANEL="$COCKPIT_DIR/stats/panel.py" python3 - "$COCKPIT_DIR/config/herdr/config.toml" "$tmp" <<'PY'
import os, sys
source, destination = sys.argv[1], sys.argv[2]
with open(source, encoding="utf-8") as handle:
    content = handle.read()
content = content.replace("@@COCKPIT_PANEL@@", os.environ["COCKPIT_PANEL"])
with open(destination, "w", encoding="utf-8") as handle:
    handle.write(content)
PY
  mv "$tmp" "$destination_final"
}

if [ ! -e "$HERDR_CONF" ]; then
  generate_herdr_conf "$HERDR_CONF"
  record generated "$HERDR_CONF" ""
  ok "config.toml genere"
elif [ "$FORCE" = "1" ] || confirm "config.toml existe deja. Le remplacer ? (sauvegarde faite)"; then
  backup="$(backup_if_present "$HERDR_CONF")"
  generate_herdr_conf "$HERDR_CONF"
  record generated "$HERDR_CONF" "$backup"
  ok "config.toml remplace (ancien en $(basename "${backup:-aucun}"))"
else
  # On ne fusionne pas a l'aveugle : ce fichier peut porter vos propres
  # reglages, et une fusion TOML approximative casserait les deux.
  sidecar="$HERDR_CONF.cockpit"
  generate_herdr_conf "$sidecar"
  warn "config.toml conserve. Version cockpit ecrite a cote :"
  warn "  $sidecar"
  warn "Comparez puis fusionnez a la main :"
  warn "  diff -u $HERDR_CONF $sidecar"
fi

if command -v herdr >/dev/null 2>&1 && [ "$DRY_RUN" != "1" ]; then
  if herdr config check >/dev/null 2>&1; then
    ok "herdr config check : ok"
  else
    err "herdr config check signale un probleme :"
    herdr config check 2>&1 | sed 's/^/      /' >&2
  fi
fi

# --- 7. Garde zsh ----------------------------------------------------------
step "Shell"

GUARD_LINE="[ -f \"$COCKPIT_DIR/shell/herdr-autostart.zsh\" ] && source \"$COCKPIT_DIR/shell/herdr-autostart.zsh\""

# On cherche la variable, pas le nom du fichier : un garde ecrit a la main
# directement dans le .zshrc compte tout autant, et en ajouter un second ne
# ferait que dupliquer la boucle.
if [ -f "$ZSHRC" ] && grep -Fq "HERDR_AUTOSTART" "$ZSHRC"; then
  ok "garde HERDR_AUTOSTART deja present dans ~/.zshrc"
elif confirm "Ajouter le garde HERDR_AUTOSTART a ~/.zshrc ? (sans lui, le space Stats s'ouvre en double)"; then
  backup="$(backup_copy "$ZSHRC")"
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] ajouter le garde a %s\n' "$ZSHRC"
  else
    {
      printf '\n# herdr-cockpit : lance une application directement dans un space.\n'
      printf '%s\n' "$GUARD_LINE"
    } >>"$ZSHRC"
  fi
  record zshrc "$ZSHRC" "$backup"
  ok "garde ajoute a ~/.zshrc"
else
  warn "Garde non installe. Le space Stats ouvrira un shell puis le panneau"
  warn "  dans un second pane. Pour l'ajouter plus tard, mettez dans ~/.zshrc :"
  warn "  $GUARD_LINE"
fi

# --- 8. Suite --------------------------------------------------------------
step "Termine"

if [ "$SPACES_CREATED" = "1" ]; then
  printf '\n  1. Declarez vos projets  :  %s\n' "$COCKPIT_DIR/spaces.conf"
  printf '  2. Ouvrez WezTerm.\n\n'
else
  printf '\n  Ouvrez WezTerm : Herdr demarre avec vos spaces.\n\n'
fi
printf '  Raccourcis : Cmd+T onglet, Cmd+D split, Cmd+fleches navigation,\n'
printf '               Cmd+B barre laterale, Ctrl-b puis i panneau de couts.\n'
printf '  Desinstaller : %s/uninstall.sh\n\n' "$COCKPIT_DIR"
