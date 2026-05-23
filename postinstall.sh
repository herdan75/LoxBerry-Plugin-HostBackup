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

SUDOERS_FILE="$LBHOMEDIR/system/sudoers/LoxBerryHostBackup"

echo "# Managed by LoxBerry Host Backup." > "$SUDOERS_FILE"
echo "loxberry ALL=(root) NOPASSWD: $BACKEND *" >> "$SUDOERS_FILE"
echo "www-data ALL=(root) NOPASSWD: $BACKEND *" >> "$SUDOERS_FILE"

chmod 644 "$SUDOERS_FILE"
chown root:root "$SUDOERS_FILE"

sudo -n "$BACKEND" install-schedule 2>/dev/null || true

exit 0
