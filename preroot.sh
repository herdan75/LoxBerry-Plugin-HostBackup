#!/bin/bash
set -euo pipefail
umask 077
# LoxBerry continues after exit 1; preparation errors must stop installation.
hook_exit() {
  local hook_status=$?
  if [ "$hook_status" -eq 1 ]; then exit 2; fi
  exit "$hook_status"
}
trap hook_exit EXIT
[ "$(id -u)" -eq 0 ] || { echo "preroot.sh must be executed as root." >&2; exit 2; }
PLUGIN_FOLDER="${3:-loxberryhostbackup}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"
# Execute the helper from the approved incoming package, never a stale mutable
# copy of the previously installed plugin.
PACKAGE_DIR="${6:-$(cd -- "$(dirname -- "$0")" && pwd)}"
python3 -I "$PACKAGE_DIR/bin/hostbackup-install-safety.py" prepare "$LBHOMEDIR" "$PLUGIN_FOLDER"
exit 0
