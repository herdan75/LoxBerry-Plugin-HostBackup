#!/bin/bash
set -euo pipefail
umask 077

# The only production root CLI entry point. Each invocation pins one immutable
# helper release so an update cannot mix its backend with another helper version.
TRUST_ROOT="/usr/libexec/loxberryhostbackup"

fail() {
  printf 'HostBackup trusted launcher: %s\n' "$1" >&2
  exit 64
}

check_root_path() {
  local item="$1" mode
  while :; do
    [ -e "$item" ] && [ ! -L "$item" ] || fail "unsafe or missing path: $item"
    [ "$(stat -c '%u' "$item")" = "0" ] || fail "path is not root-owned: $item"
    mode="$(stat -c '%a' "$item")"
    (( (8#$mode & 022) == 0 )) || fail "path is writable by group or others: $item"
    [ "$item" = / ] && break
    item="${item%/*}"
    [ -n "$item" ] || item=/
  done
}

[ "$(id -u)" -eq 0 ] || fail "run this command as root"
check_root_path "$TRUST_ROOT"
[ -L "$TRUST_ROOT/current" ] || fail "current release pointer is missing"
[ "$(stat -c '%u' "$TRUST_ROOT/current")" = "0" ] || fail "unsafe release pointer owner"
release="$(readlink -f -- "$TRUST_ROOT/current")"
case "$release" in
  "$TRUST_ROOT/releases/"*) ;;
  *) fail "release pointer leaves trusted storage" ;;
esac
[ -d "$release" ] || fail "trusted release is missing"
check_root_path "$release"
for helper in "$release"/*; do
  [ -f "$helper" ] && [ ! -L "$helper" ] || fail "unexpected helper entry: $helper"
  check_root_path "$helper"
done
for required in hostbackup.sh validate-import-archive.py runtime-home runtime-plugin; do
  [ -f "$release/$required" ] || fail "required trusted helper is missing: $required"
done
grep -Fxq 'PLUGIN_NAME="loxberryhostbackup"' "$release/hostbackup.sh" || \
  fail "invalid backup backend (launcher or incomplete installation); refusing a recursive start"
LBHOMEDIR="$(< "$release/runtime-home")"
HOSTBACKUP_PLUGIN_FOLDER="$(< "$release/runtime-plugin")"
LBPBINDIR="$release"
export LBHOMEDIR HOSTBACKUP_PLUGIN_FOLDER LBPBINDIR
export PYTHONDONTWRITEBYTECODE=1
exec "$release/hostbackup.sh" "$@"
