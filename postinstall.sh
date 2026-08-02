#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

CONFIG_DIR="$LBHOMEDIR/config/plugins/$PLUGIN_FOLDER"
DATA_DIR="$LBHOMEDIR/data/plugins/$PLUGIN_FOLDER"
LOG_DIR="$LBHOMEDIR/log/plugins/$PLUGIN_FOLDER"

for secure_dir in "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"; do
  if [ -L "$secure_dir" ]; then
    echo "Refusing unsafe symlink directory: $secure_dir" >&2
    exit 1
  fi
done

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"

exit 0
