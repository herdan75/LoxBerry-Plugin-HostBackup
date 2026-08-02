#!/bin/bash
set -euo pipefail
umask 077

# This dispatcher is installed root-owned at /usr/local/sbin.  The web user is
# never allowed to execute a wildcard-matched plugin path directly.
BACKEND="/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh"

fail() {
  printf 'HostBackup dispatcher: %s\n' "$1" >&2
  exit 64
}

[ -x "$BACKEND" ] || fail "trusted backend is missing"
[ ! -L "$BACKEND" ] || fail "backend must not be a symlink"
[ "$(stat -c '%u' "$BACKEND" 2>/dev/null || echo -1)" = "0" ] || fail "backend is not root-owned"
mode="$(stat -c '%a' "$BACKEND" 2>/dev/null || echo '')"
[ -n "$mode" ] || fail "backend mode cannot be read"
(( (8#$mode & 022) == 0 )) || fail "backend is writable by group or others"

action="${1:-}"
case "$action" in
  config|target-info|stop-targets|preflight-backup|tasks|list)
    [ "$#" -eq 1 ] || fail "unexpected arguments for $action"
    ;;
  start)
    [ "$#" -le 3 ] || fail "too many start arguments"
    ;;
  task-status|task-log)
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] || fail "invalid task query"
    ;;
  stop|export-info|start-export|delete-export|delete|preflight-restore|restore-plan)
    [ "$#" -eq 2 ] || fail "invalid arguments for $action"
    ;;
  start-restore)
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] || fail "invalid restore arguments"
    ;;
  browse)
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] || fail "invalid browse arguments"
    ;;
  start-import)
    [ "$#" -eq 2 ] || fail "invalid import arguments"
    ;;
  save-config)
    [ "$#" -eq 26 ] || fail "invalid configuration argument count"
    ;;
  *)
    fail "action is not permitted"
    ;;
esac

exec env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root \
  LANG=C.UTF-8 \
  "$BACKEND" "$@"
