#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"
BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
CGI="$LBHOMEDIR/webfrontend/htmlauth/plugins/$PLUGIN_FOLDER/index.cgi"
RESTORE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/restore-hostbackup.sh"
SUDOERS_FILE="/etc/sudoers.d/loxberryhostbackup"
SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT

chmod 755 "$BACKEND" 2>/dev/null || true
chmod 755 "$CGI" 2>/dev/null || true
chmod 755 "$RESTORE" 2>/dev/null || true

cat > "$SUDOERS_TMP" <<EOF
# Managed by LoxBerry Host Backup.
loxberry ALL=(root) NOPASSWD: $BACKEND *
www-data ALL=(root) NOPASSWD: $BACKEND *
EOF

if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS_TMP"
fi

sudo install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS_FILE"

sudo -n "$BACKEND" install-schedule 2>/dev/null || true

exit 0
