#!/bin/bash
set -euo pipefail

PLUGIN_NAME="loxberryhostbackup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_FOLDER="$(basename "$SCRIPT_DIR")"
if [[ "$SCRIPT_DIR" == */bin/plugins/* ]]; then
  DETECTED_LBHOMEDIR="${SCRIPT_DIR%/bin/plugins/$PLUGIN_FOLDER}"
else
  DETECTED_LBHOMEDIR="/opt/loxberry"
  PLUGIN_FOLDER="$PLUGIN_NAME"
fi
LBHOMEDIR="${LBHOMEDIR:-$DETECTED_LBHOMEDIR}"
BACKEND="${LBPBINDIR:-$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER}/hostbackup.sh"

if [ $# -ne 1 ]; then
  echo "Usage: $0 BACKUP_ID" >&2
  exit 1
fi

ALLOW_RESTORE=1 "$BACKEND" restore "$1"
