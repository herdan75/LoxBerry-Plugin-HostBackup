#!/bin/bash
set -e

PLUGIN_NAME="loxberryhostbackup"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
CGI="$LBHOMEDIR/webfrontend/htmlauth/plugins/$PLUGIN_FOLDER/index.cgi"
RESTORE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/restore-hostbackup.sh"

SUDOERS_SYSTEM="$LBHOMEDIR/system/sudoers/LoxBerryHostBackup"
SUDOERS_ETC="/etc/sudoers.d/LoxBerryHostBackup"

chmod 755 "$BACKEND" 2>/dev/null || true
chmod 755 "$CGI" 2>/dev/null || true
chmod 755 "$RESTORE" 2>/dev/null || true

cat > "$SUDOERS_SYSTEM" <<EOF
# Managed by LoxBerry Host Backup.
loxberry ALL=(root) NOPASSWD: $BACKEND *
www-data ALL=(root) NOPASSWD: $BACKEND *
EOF

chmod 440 "$SUDOERS_SYSTEM"
chown root:root "$SUDOERS_SYSTEM"

if [ -d /etc/sudoers.d ]; then
  cp "$SUDOERS_SYSTEM" "$SUDOERS_ETC"
  chmod 440 "$SUDOERS_ETC"
  chown root:root "$SUDOERS_ETC"
fi

if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS_SYSTEM" >/dev/null
  if [ -f "$SUDOERS_ETC" ]; then
    visudo -cf "$SUDOERS_ETC" >/dev/null
  fi
fi

"$BACKEND" install-schedule 2>/dev/null || true

exit 0
