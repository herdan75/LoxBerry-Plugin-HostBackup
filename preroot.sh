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
case "$PLUGIN_FOLDER" in
  ""|.|..|*[!A-Za-z0-9._-]*) echo "Unsafe plugin folder." >&2; exit 1 ;;
esac
case "$LBHOMEDIR" in
  /*) ;;
  *) echo "LoxBerry home must be an absolute path." >&2; exit 1 ;;
esac

CONFIG="$LBHOMEDIR/config/plugins/$PLUGIN_FOLDER/config.json"
CONFIG_DIR="${CONFIG%/*}"
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
  chown loxberry:loxberry "$CONFIG_DIR"
  chmod 0755 "$CONFIG_DIR"
  echo "Existing HostBackup configuration secured for upgrade."
fi

# LoxBerry removes/replaces plugin files as its unprivileged platform user.
# POSTROOT protects the old bin directory; release only those directory owners
# for the upcoming purge, AFTER securing the configuration. Root-owned files can
# be unlinked by their directory owner. Do not follow links or change any file
# ownership: pinned helpers in /usr/libexec and root state remain protected.
BIN_DIR="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER"
if [ -L "$BIN_DIR" ]; then
  echo "Refusing unsafe plugin bin symlink: $BIN_DIR" >&2
  exit 1
fi
if [ -e "$BIN_DIR" ]; then
  [ -d "$BIN_DIR" ] || { echo "Plugin bin path is not a directory." >&2; exit 1; }
  find -P "$BIN_DIR" -type d -exec chown -h loxberry:loxberry -- {} +
  echo "Plugin bin directories prepared for LoxBerry's unprivileged update."
fi

exit 0
