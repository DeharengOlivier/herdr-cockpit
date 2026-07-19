# herdr-cockpit: HERDR_AUTOSTART guard.
#
# Without this guard, a space that is supposed to start on an application (the
# statistics panel) first opens a shell, then the application in a second pane.
# We end up with a useless shell next to it. The guard intercepts the variable
# before the shell hands control back and starts the application in its place.
#
# The loop makes it possible to quit the panel without losing the space: enter
# restarts it, Ctrl-D goes back to the shell.
#
# Installed by install.sh through a "source" line added to ~/.zshrc.

if [[ -n "${HERDR_AUTOSTART:-}" ]]; then
  __herdr_cmd="$HERDR_AUTOSTART"
  unset HERDR_AUTOSTART          # avoids any recursion in sub-shells
  while true; do
    eval "$__herdr_cmd"
    printf '\n  [enter] restart   ·   [Ctrl-D] back to shell\n'
    read -r _ || break
  done
  unset __herdr_cmd
fi
