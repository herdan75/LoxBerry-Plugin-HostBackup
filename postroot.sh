#!/bin/bash
set -euo pipefail
umask 077

PLUGIN_NAME="loxberryhostbackup"
INSTALL_ID="${1:-}"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

[ "$(id -u)" -eq 0 ] || {
  echo "postroot.sh must be executed as root." >&2
  exit 1
}

case "$INSTALL_ID" in
  ""|*[!A-Za-z0-9._-]*)
    echo "Unsafe LoxBerry installation id." >&2
    exit 1
    ;;
esac

BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
DISPATCHER_SOURCE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup-sudo.sh"
DISPATCHER_TARGET="/usr/local/sbin/loxberryhostbackup-sudo"
CGI="$LBHOMEDIR/webfrontend/htmlauth/plugins/$PLUGIN_FOLDER/index.cgi"
RESTORE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/restore-hostbackup.sh"
NOTIFY="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/notify-hostbackup.php"
CONFIG_DIR="$LBHOMEDIR/config/plugins/$PLUGIN_FOLDER"
CONFIG="$CONFIG_DIR/config.json"
DATA_DIR="$LBHOMEDIR/data/plugins/$PLUGIN_FOLDER"
LOG_DIR="$LBHOMEDIR/log/plugins/$PLUGIN_FOLDER"
if [ "$LBHOMEDIR" = "/opt/loxberry" ]; then
  ROOT_STATE_DIR="/var/lib/$PLUGIN_FOLDER"
else
  ROOT_STATE_DIR="$DATA_DIR/root-state"
fi
LOCK_DIR="$ROOT_STATE_DIR/locks"
TASK_DIR="$ROOT_STATE_DIR/tasks"
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
ROOT_IMPORT_DIR="$ROOT_STATE_DIR/imports"
QUARANTINE_DIR="$ROOT_STATE_DIR/import-quarantine"
UPGRADE_DIR="/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade"
CONFIG_BACKUP="$UPGRADE_DIR/config.json"

if [ -L "$CONFIG_DIR" ]; then
  echo "Refusing unsafe symlink directory: $CONFIG_DIR" >&2
  exit 1
fi
mkdir -p "$CONFIG_DIR"

if [ -e "$UPGRADE_DIR" ]; then
  if [ ! -d "$UPGRADE_DIR" ] || [ -L "$UPGRADE_DIR" ] || [ "$(stat -c '%u' "$UPGRADE_DIR")" -ne 0 ]; then
    echo "Refusing unsafe upgrade directory: $UPGRADE_DIR" >&2
    exit 1
  fi
  if [ ! -f "$CONFIG_BACKUP" ] || [ -L "$CONFIG_BACKUP" ]; then
    echo "Upgrade configuration backup is missing or unsafe." >&2
    exit 1
  fi
  install -o root -g root -m 0600 "$CONFIG_BACKUP" "$CONFIG"
  rm -f -- "$CONFIG_BACKUP"
  rmdir -- "$UPGRADE_DIR"
  echo "Existing HostBackup configuration restored after upgrade."
fi

for required_file in "$BACKEND" "$DISPATCHER_SOURCE" "$CGI" "$RESTORE" "$NOTIFY" "$CONFIG"; do
  if [ ! -f "$required_file" ] || [ -L "$required_file" ]; then
    echo "Required installed file is missing or unsafe: $required_file" >&2
    exit 1
  fi
done

for secure_dir in "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"; do
  if [ -L "$secure_dir" ]; then
    echo "Refusing unsafe symlink directory: $secure_dir" >&2
    exit 1
  fi
done

mkdir -p "$DATA_DIR" "$LOG_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"

chown root:root "$BACKEND" "$DISPATCHER_SOURCE" "$RESTORE" "$NOTIFY" "$CONFIG_DIR" "$CONFIG" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"
chown loxberry:loxberry "$LOG_DIR"
chmod 755 "$BACKEND" "$DISPATCHER_SOURCE" "$CGI" "$RESTORE"
chmod 644 "$NOTIFY"
chmod 755 "$CONFIG_DIR" "$LOG_DIR"
chmod 600 "$CONFIG"
chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"

install -o root -g root -m 0755 "$DISPATCHER_SOURCE" "$DISPATCHER_TARGET"

"$BACKEND" install-schedule

exit 0
