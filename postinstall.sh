#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"
BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
CGI="$LBHOMEDIR/webfrontend/htmlauth/plugins/$PLUGIN_FOLDER/index.cgi"
RESTORE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/restore-hostbackup.sh"

chmod 755 "$BACKEND" 2>/dev/null || true
chmod 755 "$CGI" 2>/dev/null || true
chmod 755 "$RESTORE" 2>/dev/null || true

sudo -n "$BACKEND" install-schedule 2>/dev/null || true

exit 0
