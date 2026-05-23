#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"
BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
CGI="$LBHOMEDIR/webfrontend/htmlauth/plugins/$PLUGIN_FOLDER/index.cgi"
RESTORE="$LBHOMEDIR/sbin/plugins/$PLUGIN_FOLDER/restore-hostbackup.sh"
SUDOERS_FILE="/etc/sudoers.d/loxberryhostbackup"

chmod 755 "$BACKEND" 2>/dev/null || true
chmod 755 "$CGI" 2>/dev/null || true
chmod 755 "$RESTORE" 2>/dev/null || true

cat > "$SUDOERS_FILE" <<EOF
# Managed by LoxBerry Host Backup.
loxberry ALL=(root) NOPASSWD: $BACKEND *
www-data ALL=(root) NOPASSWD: $BACKEND *
EOF

chmod 440 "$SUDOERS_FILE"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS_FILE"
fi

"$BACKEND" install-schedule 2>/dev/null || true

exit 0
