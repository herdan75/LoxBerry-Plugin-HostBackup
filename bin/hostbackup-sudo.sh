#!/bin/bash
set -euo pipefail
umask 077

# This dispatcher is installed root-owned at /usr/local/sbin.  The web user is
# never allowed to execute a wildcard-matched plugin path directly.
BACKEND="/usr/local/sbin/loxberryhostbackup"

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
parent="${BACKEND%/*}"
while :; do
  [ -d "$parent" ] && [ ! -L "$parent" ] || fail "unsafe backend parent"
  [ "$(stat -c '%u' "$parent")" = "0" ] || fail "backend parent is not root-owned"
  mode="$(stat -c '%a' "$parent")"
  (( (8#$mode & 022) == 0 )) || fail "backend parent is writable by group or others"
  [ "$parent" = / ] && break
  parent="${parent%/*}"
  [ -n "$parent" ] || parent=/
done

action="${1:-}"
case "$action" in
  config|target-info|stop-targets|preflight-backup|tasks|list|recover-services|task-overview|backup-preview|storage-info|maintenance-preview|runtime-cleanup-preview)
    [ "$#" -eq 1 ] || fail "unexpected arguments for $action"
    ;;
  start)
    [ "$#" -le 3 ] || fail "too many start arguments"
    ;;
  task-status|task-log)
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] || fail "invalid task query"
    ;;
  stop|export-info|start-export|delete-export|delete|preflight-restore|download-export|download-log|inspect-backup|verification-report|verify-backup|recovery-sheet|maintenance-config|maintenance-run|runtime-cleanup-run)
    [ "$#" -eq 2 ] || fail "invalid arguments for $action"
    ;;
  restore-plan)
    [ "$#" -ge 2 ] && [ "$#" -le 4 ] || fail "invalid restore plan arguments"
    ;;
  start-restore)
    [ "$#" -ge 2 ] && [ "$#" -le 5 ] || fail "invalid restore arguments"
    ;;
  restore-files)
    [ "$#" -eq 4 ] || fail "invalid file restore arguments"
    ;;
  protect-backup)
    [ "$#" -eq 3 ] || fail "invalid backup protection arguments"
    ;;
  record-restore-test)
    [ "$#" -eq 5 ] || fail "invalid restore test record arguments"
    ;;
  diagnostics)
    [ "$#" -ge 1 ] && [ "$#" -le 2 ] || fail "invalid diagnostics arguments"
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
