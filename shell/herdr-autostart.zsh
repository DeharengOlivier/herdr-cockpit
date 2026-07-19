# herdr-cockpit : garde HERDR_AUTOSTART.
#
# Sans ce garde, un space qui doit demarrer sur une application (le panneau de
# statistiques) ouvre d'abord un shell, puis l'application dans un second pane.
# On se retrouve avec un shell inutile a cote. Le garde intercepte la variable
# avant que le shell ne rende la main et lance l'application a sa place.
#
# La boucle permet de quitter le panneau sans perdre le space : entree le
# relance, Ctrl-D revient au shell.
#
# Installe par install.sh via une ligne "source" ajoutee a ~/.zshrc.

if [[ -n "${HERDR_AUTOSTART:-}" ]]; then
  __herdr_cmd="$HERDR_AUTOSTART"
  unset HERDR_AUTOSTART          # evite toute recursion dans les sous-shells
  while true; do
    eval "$__herdr_cmd"
    printf '\n  [entree] relancer   ·   [Ctrl-D] revenir au shell\n'
    read -r _ || break
  done
  unset __herdr_cmd
fi
