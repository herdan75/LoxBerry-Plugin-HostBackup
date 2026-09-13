#!/bin/bash
set -euo pipefail

PLUGIN_NAME="loxberryhostbackup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_FOLDER="$(basename "$SCRIPT_DIR")"
if [[ "$SCRIPT_DIR" == */bin/plugins/* ]]; then
  DETECTED_LBHOMEDIR="${SCRIPT_DIR%/bin/plugins/$PLUGIN_FOLDER}"
else
  DETECTED_LBHOMEDIR="/opt/loxberry"
  PLUGIN_FOLDER="${HOSTBACKUP_PLUGIN_FOLDER:-$PLUGIN_NAME}"
fi
LBHOMEDIR="${LBHOMEDIR:-$DETECTED_LBHOMEDIR}"
BACKEND="${LBPBINDIR:-$SCRIPT_DIR}/hostbackup.sh"

if [ $# -lt 1 ]; then
  echo "Usage: $0 BACKUP_ID [--confirm-degraded] [--destination DIR] [--map-json JSON] [--preview]" >&2
  echo "Portable Archive restores additionally require HOSTBACKUP_OFFLINE_RESTORE=1 from a rescue/offline environment." >&2
  exit 1
fi

confirmation=""
backup_id="$1"
shift
destination="${HOSTBACKUP_RESTORE_DEST:-/}"
mappings='[]'
preview=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --confirm-degraded) confirmation=confirm-degraded; shift ;;
    --destination) destination="${2:?Destination required}"; shift 2 ;;
    --map-json) mappings="${2:?Mapping JSON required}"; shift 2 ;;
    --preview) preview=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ "$preview" = true ]; then
  exec "$BACKEND" restore-plan "$backup_id" "$destination" "$mappings"
fi
ALLOW_RESTORE=1 "$BACKEND" restore "$backup_id" "$confirmation" "$destination" "$mappings"
