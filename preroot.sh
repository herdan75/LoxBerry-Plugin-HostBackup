#!/bin/bash
set -euo pipefail
umask 077

INSTALL_ID="${1:-}"
PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

[ "$(id -u)" -eq 0 ] || {
  echo "preroot.sh must be executed as root." >&2
  exit 1
}

case "$INSTALL_ID" in
  ""|*[!A-Za-z0-9._-]*)
    echo "Unsafe LoxBerry installation id." >&2
    exit 1
    ;;
esac

CONFIG="$LBHOMEDIR/config/plugins/$PLUGIN_FOLDER/config.json"
UPGRADE_DIR="/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade"
CONFIG_BACKUP="$UPGRADE_DIR/config.json"

if [ -e "$CONFIG" ]; then
  if [ ! -f "$CONFIG" ] || [ -L "$CONFIG" ]; then
    echo "Refusing unsafe existing configuration: $CONFIG" >&2
    exit 1
  fi
  if [ -e "$UPGRADE_DIR" ] || [ -L "$UPGRADE_DIR" ]; then
    echo "Refusing pre-existing upgrade directory: $UPGRADE_DIR" >&2
    exit 1
  fi
  install -d -o root -g root -m 0700 "$UPGRADE_DIR"
  cp --no-dereference --preserve=mode,timestamps "$CONFIG" "$CONFIG_BACKUP"
  chown root:root "$CONFIG_BACKUP"
  chmod 0600 "$CONFIG_BACKUP"
  echo "Existing HostBackup configuration secured for upgrade."
fi

exit 0
