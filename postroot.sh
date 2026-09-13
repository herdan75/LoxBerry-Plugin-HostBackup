#!/bin/bash
set -euo pipefail
umask 077

PLUGIN_NAME="loxberryhostbackup"
INSTALL_ID="${1:-}"
PLUGIN_FOLDER="${3:-$PLUGIN_NAME}"
LBHOMEDIR="${5:-${LBHOMEDIR:-/opt/loxberry}}"

[ "$(id -u)" -eq 0 ] || {
  echo "postroot.sh must be executed as root." >&2
  exit 1
}

case "$INSTALL_ID" in
  ""|*[!A-Za-z0-9._-]*)
    echo "Unsafe LoxBerry installation id." >&2
    exit 1
    ;;
esac
case "$PLUGIN_FOLDER" in
  ""|.|..|*[!A-Za-z0-9._-]*) echo "Unsafe plugin folder." >&2; exit 1 ;;
esac
case "$LBHOMEDIR" in
  /*) ;;
  *) echo "LoxBerry home must be an absolute path." >&2; exit 1 ;;
esac

BACKEND="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup.sh"
SOURCE_BIN="${BACKEND%/*}"
DISPATCHER_SOURCE="$LBHOMEDIR/bin/plugins/$PLUGIN_FOLDER/hostbackup-sudo.sh"
DISPATCHER_TARGET="/usr/local/sbin/loxberryhostbackup-sudo"
LAUNCHER_SOURCE="$SOURCE_BIN/hostbackup-launcher.sh"
LAUNCHER_TARGET="/usr/local/sbin/loxberryhostbackup"
TRUST_ROOT="/usr/libexec/loxberryhostbackup"
RECOVERY_CRON="/etc/cron.d/loxberryhostbackup-recovery"
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
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
ROOT_IMPORT_DIR="$ROOT_STATE_DIR/imports"
QUARANTINE_DIR="$ROOT_STATE_DIR/import-quarantine"
UPGRADE_DIR="/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade"
CONFIG_BACKUP="$UPGRADE_DIR/config.json"

if [ -L "$CONFIG_DIR" ]; then
  echo "Refusing unsafe symlink directory: $CONFIG_DIR" >&2
  exit 1
fi
mkdir -p "$CONFIG_DIR"

if [ -e "$UPGRADE_DIR" ]; then
  if [ ! -d "$UPGRADE_DIR" ] || [ -L "$UPGRADE_DIR" ] || [ "$(stat -c '%u' "$UPGRADE_DIR")" -ne 0 ]; then
    echo "Refusing unsafe upgrade directory: $UPGRADE_DIR" >&2
    exit 1
  fi
  if [ ! -f "$CONFIG_BACKUP" ] || [ -L "$CONFIG_BACKUP" ]; then
    echo "Upgrade configuration backup is missing or unsafe." >&2
    exit 1
  fi
  install -o root -g root -m 0600 "$CONFIG_BACKUP" "$CONFIG"
  rm -f -- "$CONFIG_BACKUP"
  rmdir -- "$UPGRADE_DIR"
  echo "Existing HostBackup configuration restored after upgrade."
fi

for required_file in "$BACKEND" "$DISPATCHER_SOURCE" "$LAUNCHER_SOURCE" "$SOURCE_BIN/validate-import-archive.py" "$CGI" "$RESTORE" "$NOTIFY" "$CONFIG"; do
  if [ ! -f "$required_file" ] || [ -L "$required_file" ]; then
    echo "Required installed file is missing or unsafe: $required_file" >&2
    exit 1
  fi
done

for secure_dir in "$SOURCE_BIN" "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"; do
  if [ -L "$secure_dir" ]; then
    echo "Refusing unsafe symlink directory: $secure_dir" >&2
    exit 1
  fi
done

mkdir -p "$DATA_DIR" "$LOG_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"

chown root:root "$BACKEND" "$DISPATCHER_SOURCE" "$RESTORE" "$NOTIFY" "$CONFIG_DIR" "$CONFIG" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"
chown loxberry:loxberry "$LOG_DIR"
chmod 755 "$BACKEND" "$DISPATCHER_SOURCE" "$CGI" "$RESTORE"
chmod 644 "$NOTIFY"
chmod 755 "$CONFIG_DIR" "$LOG_DIR"
chmod 600 "$CONFIG"
chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"

ensure_root_path() {
  local path="$1" parent mode
  parent="${path%/*}"
  [ -n "$parent" ] || parent=/
  if [ "$path" != / ]; then ensure_root_path "$parent"; fi
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    install -d -o root -g root -m 0755 "$path"
  fi
  [ -d "$path" ] && [ ! -L "$path" ] || { echo "Unsafe trusted directory: $path" >&2; exit 1; }
  mode="$(stat -c '%a' "$path")"
  [ "$(stat -c '%u' "$path")" = 0 ] && (( (8#$mode & 022) == 0 )) || {
    echo "Trusted directory must be root-owned and not writable by others: $path" >&2
    exit 1
  }
}

prepare_recovery_cron_directory() {
  local cron_dir="${RECOVERY_CRON%/*}" expected_dir resolved_dir mode owner group forbidden_write_bits
  if [ -L "$cron_dir" ]; then
    # LoxBerry deliberately redirects /etc/cron.d into its system tree. That
    # platform-managed cron directory is not an executable helper directory:
    # its ancestors belong to LoxBerry, while cron.d itself belongs to root.
    ensure_root_path "${cron_dir%/*}"
    [ "$(stat -c '%u' "$cron_dir")" = 0 ] || {
      echo "Cron directory symlink must be root-owned: $cron_dir" >&2; exit 1;
    }
    expected_dir="$(readlink -e -- "$LBHOMEDIR")" || {
      echo "Cannot resolve LoxBerry home for the system cron directory." >&2; exit 1;
    }
    expected_dir="$expected_dir/system/cron/cron.d"
    resolved_dir="$(readlink -e -- "$cron_dir")" || {
      echo "Cron directory symlink has no existing target: $cron_dir" >&2; exit 1;
    }
    [ "$resolved_dir" = "$expected_dir" ] || {
      echo "Cron directory symlink must point to the LoxBerry system cron directory: $cron_dir" >&2; exit 1;
    }
    [ -d "$resolved_dir" ] && [ ! -L "$resolved_dir" ] || {
      echo "Unsafe LoxBerry system cron directory: $resolved_dir" >&2; exit 1;
    }
    mode="$(stat -c '%a' "$resolved_dir")"
    owner="$(stat -c '%u' "$resolved_dir")"
    group="$(stat -c '%g' "$resolved_dir")"
    # LoxBerry installations can retain root:root 0775/02775 on this shared
    # system configuration directory. Trust its root group here only; the
    # stricter checks for executable helpers and their ancestors stay intact.
    forbidden_write_bits=022
    [ "$group" != 0 ] || forbidden_write_bits=002
    [ "$owner" = 0 ] && (( (8#$mode & forbidden_write_bits) == 0 )) || {
      echo "Unsafe LoxBerry system cron directory (uid=$owner gid=$group mode=$mode): $resolved_dir; root ownership required, group write allowed only for group root, no world write." >&2
      exit 1
    }
    echo "LoxBerry cron directory accepted (uid=$owner gid=$group mode=$mode): $resolved_dir"
    cron_dir="$resolved_dir"
  else
    ensure_root_path "$cron_dir"
  fi
  # Use the resolved directory path for the atomic recovery-entry installation;
  # its LoxBerry-managed ancestors remain part of the platform trust boundary.
  RECOVERY_CRON="$cron_dir/${RECOVERY_CRON##*/}"
}

ensure_root_path "$TRUST_ROOT/releases"
ensure_root_path "${LAUNCHER_TARGET%/*}"
prepare_recovery_cron_directory
[ ! -e "$TRUST_ROOT/current" ] || [ -L "$TRUST_ROOT/current" ] || {
  echo "Refusing non-symlink current release pointer." >&2; exit 1;
}
# Close the package directory to replacement before copying the complete helper
# set. The privileged runtime no longer depends on LoxBerry's mutable bin tree.
chown root:root "$SOURCE_BIN"
chmod 0755 "$SOURCE_BIN"
# A failed platform purge/copy can leave the forwarding shim at this path.
# Never publish it as the backend: it would repeatedly exec itself through
# current, blocking POSTROOT, cron and every web action. The marker also exists
# in the real older backend, so retained releases remain usable for recovery.
grep -Fxq 'PLUGIN_NAME="loxberryhostbackup"' "$BACKEND" || {
  echo "Installed hostbackup.sh is not the backup backend (launcher or incomplete copy). Keeping the previous trusted release; reinstall the corrected package." >&2
  exit 1
}
release="$(mktemp -d "$TRUST_ROOT/releases/${INSTALL_ID}.XXXXXXXX")"
pointer="$TRUST_ROOT/.current-${INSTALL_ID}-$$"
launcher_tmp="${LAUNCHER_TARGET}.install-$$"
dispatcher_tmp="${DISPATCHER_TARGET}.install-$$"
recovery_tmp=""
trap 'rm -f -- "$pointer" "$launcher_tmp" "$dispatcher_tmp" "$recovery_tmp"' EXIT
recovery_tmp="$(mktemp "${RECOVERY_CRON%/*}/.loxberryhostbackup-recovery.XXXXXXXX")"
for helper in "$SOURCE_BIN"/*.sh "$SOURCE_BIN"/*.py "$SOURCE_BIN"/*.php; do
  [ -e "$helper" ] || continue
  [ -f "$helper" ] && [ ! -L "$helper" ] || { echo "Unsafe executable helper: $helper" >&2; exit 1; }
  chown root:root "$helper"
  chmod 0755 "$helper"
  install -o root -g root -m 0755 "$helper" "$release/${helper##*/}"
done
if [ -e "$SOURCE_BIN/runtime-version" ] || [ -L "$SOURCE_BIN/runtime-version" ]; then
  [ -f "$SOURCE_BIN/runtime-version" ] && [ ! -L "$SOURCE_BIN/runtime-version" ] || {
    echo "Unsafe packaged runtime version." >&2; exit 1;
  }
  install -o root -g root -m 0644 "$SOURCE_BIN/runtime-version" "$release/runtime-version"
else
  printf 'unknown\n' > "$release/runtime-version"
fi
printf '%s\n' "$LBHOMEDIR" > "$release/runtime-home"
printf '%s\n' "$PLUGIN_FOLDER" > "$release/runtime-plugin"
chmod 0644 "$release/runtime-home" "$release/runtime-plugin"
chmod 0755 "$release"
install -o root -g root -m 0755 "$LAUNCHER_SOURCE" "$launcher_tmp"
install -o root -g root -m 0755 "$DISPATCHER_SOURCE" "$dispatcher_tmp"
ln -s -- "$release" "$pointer"
mv -fT -- "$pointer" "$TRUST_ROOT/current"
mv -fT -- "$launcher_tmp" "$LAUNCHER_TARGET"
mv -fT -- "$dispatcher_tmp" "$DISPATCHER_TARGET"
printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n@reboot root %s recover-services\n*/5 * * * * root %s recover-services\n23 * * * * root %s integrity-schedule\n' "$LAUNCHER_TARGET" "$LAUNCHER_TARGET" "$LAUNCHER_TARGET" > "$recovery_tmp"
chown root:root "$recovery_tmp"
chmod 0644 "$recovery_tmp"
mv -fT -- "$recovery_tmp" "$RECOVERY_CRON"
# Existing documented plugin CLI paths remain callable, forwarding to the same
# pinned trusted release as scheduled and web-triggered operations.
install -o root -g root -m 0755 "$LAUNCHER_SOURCE" "$BACKEND"

if timeout --kill-after=5 30 "$LAUNCHER_TARGET" install-schedule; then
  echo "HostBackup schedule installation completed."
else
  status=$?
  echo "HostBackup schedule installation failed or timed out (status $status); installation will not wait indefinitely." >&2
  exit "$status"
fi

exit 0
