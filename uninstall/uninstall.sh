#!/bin/bash
set -euo pipefail
umask 077
trap 'hook_status=$?; if [ "$hook_status" -eq 1 ]; then exit 2; fi' EXIT
[ "$(id -u)" -eq 0 ] || { echo "uninstall.sh must be executed as root." >&2; exit 2; }
PLUGIN_FOLDER="${3:-loxberryhostbackup}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"
TRUST_ROOT="/usr/libexec/loxberryhostbackup"

check_root_path() {
  local item="$1" mode
  while :; do
    [ -e "$item" ] && [ ! -L "$item" ] || { echo "Unsafe or missing trusted uninstall helper path: $item" >&2; exit 2; }
    [ "$(stat -c '%u' "$item")" = 0 ] || { echo "Uninstall helper path is not root-owned: $item" >&2; exit 2; }
    mode="$(stat -c '%a' "$item")"
    (( (8#$mode & 022) == 0 )) || { echo "Uninstall helper path is writable by others: $item" >&2; exit 2; }
    [ "$item" = / ] && break
    item="${item%/*}"
    [ -n "$item" ] || item=/
  done
}
check_root_path "$TRUST_ROOT"
[ -L "$TRUST_ROOT/current" ] && [ "$(stat -c '%u' "$TRUST_ROOT/current")" = 0 ] || {
  echo "Trusted runtime is unavailable; repair the installation before uninstalling." >&2; exit 2;
}
release="$(readlink -e -- "$TRUST_ROOT/current")"
case "$release" in
  "$TRUST_ROOT/releases/"*) ;;
  *) echo "Unsafe trusted release pointer." >&2; exit 2 ;;
esac
check_root_path "$release/hostbackup-install-safety.py"
# Keep launchers until descriptor-anchored cleanup and all safety checks succeed.
python3 -I "$release/hostbackup-install-safety.py" uninstall "$LBHOMEDIR" "$PLUGIN_FOLDER"
rm -f -- /etc/cron.d/loxberryhostbackup /etc/cron.d/loxberryhostbackup-recovery /etc/sudoers.d/loxberryhostbackup
rm -f -- /usr/local/sbin/loxberryhostbackup-sudo /usr/local/sbin/loxberryhostbackup
# The operation-lock inode is intentionally retained.
exit 0
