#!/bin/bash
set -euo pipefail

PLUGIN_NAME="loxberryhostbackup"
LBHOMEDIR="${LBHOMEDIR:-/opt/loxberry}"
BACKEND="${LBPBINDIR:-$LBHOMEDIR/bin/plugins/$PLUGIN_NAME}/hostbackup.sh"

if [ $# -ne 1 ]; then
  echo "Usage: $0 BACKUP_ID" >&2
  exit 1
fi

ALLOW_RESTORE=1 "$BACKEND" restore "$1"
