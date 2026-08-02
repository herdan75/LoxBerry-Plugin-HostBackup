#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

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
ROOT_IMPORT_DIR="$ROOT_STATE_DIR/imports"
QUARANTINE_DIR="$ROOT_STATE_DIR/import-quarantine"

for secure_dir in "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"; do
  if [ -L "$secure_dir" ]; then
    echo "Refusing unsafe symlink directory: $secure_dir" >&2
    exit 1
  fi
done

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"

chown root:root "$BACKEND" "$DISPATCHER_SOURCE" "$RESTORE" "$NOTIFY" "$CONFIG_DIR" "$CONFIG" "$LOG_DIR" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" 2>/dev/null || true
chmod 755 "$BACKEND" "$DISPATCHER_SOURCE" 2>/dev/null || true
chmod 755 "$CGI" 2>/dev/null || true
chmod 755 "$RESTORE" 2>/dev/null || true
chmod 644 "$NOTIFY" 2>/dev/null || true
chmod 755 "$CONFIG_DIR" 2>/dev/null || true
chmod 600 "$CONFIG" 2>/dev/null || true
chmod 755 "$LOG_DIR" 2>/dev/null || true
chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" 2>/dev/null || true

install -o root -g root -m 0755 "$DISPATCHER_SOURCE" "$DISPATCHER_TARGET"

"$BACKEND" install-schedule 2>/dev/null || true

exit 0
