#!/bin/bash
# Run only on a disposable Linux test host. No production NAS is used.
set -euo pipefail
umask 077
[ "${HOSTBACKUP_RUN_REPOSITORY_INTEGRATION:-}" = 1 ] && [ "$(id -u)" -eq 0 ] || exit 64
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
engine_cache="${1:?Path to checksum-pinned compressed Restic engines required}"
parent=/usr/libexec/loxberryhostbackup/releases
install -d -o root -g root -m 0755 "$parent"
runtime="$(mktemp -d "$parent/qualification.XXXXXXXX")"
case "$runtime" in "$parent"/qualification.*) ;; *) exit 1 ;; esac
cleanup() {
  local status=$?
  trap - EXIT
  if [ ! -L "$runtime" ] && [ "$(realpath -- "$runtime")" = "$runtime" ]; then
    rm -rf --one-file-system -- "$runtime"
  fi
  exit "$status"
}
trap cleanup EXIT
for helper in "$repo"/bin/*.py; do install -m 0755 "$helper" "$runtime/${helper##*/}"; done
python3 "$runtime/hostbackup-engine.py" install "$engine_cache" "$runtime"
HOSTBACKUP_RESTIC_BINARY="$runtime/restic" HOSTBACKUP_REQUIRE_REPOSITORY_INTEGRATION=1 python3 "$repo/tests/test_repository.py"
HOSTBACKUP_PORTABLE_RUNTIME="$runtime" HOSTBACKUP_REQUIRE_PORTABLE_INTEGRATION=1 python3 "$repo/tests/test_portable.py"
HOSTBACKUP_PORTABLE_RUNTIME="$runtime" HOSTBACKUP_RUN_CIFS_INTEGRATION=1 bash "$repo/tests/run-cifs.sh"
