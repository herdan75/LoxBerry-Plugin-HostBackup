#!/bin/bash
# Disposable root-only Linux integration. Never mount a real NAS or change an
# existing Samba service. CI must install samba, cifs-utils, rsync, acl, attr,
# libcap2-bin and util-linux first. A missing kernel capability is a test failure.
set -euo pipefail
umask 077

if [ "${HOSTBACKUP_RUN_CIFS_INTEGRATION:-}" != 1 ] || [ "$(id -u)" -ne 0 ]; then
  echo 'Set HOSTBACKUP_RUN_CIFS_INTEGRATION=1 and run as root on a disposable Linux CI host.' >&2
  exit 64
fi
for tool in python3 smbd testparm mount.cifs mount umount mountpoint setsid realpath rsync tar setfacl getfacl setfattr getfattr setcap getcap; do
  command -v "$tool" >/dev/null || { echo "Required CIFS integration tool missing: $tool" >&2; exit 1; }
done
test "$(uname -s)" = Linux
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
fixture_dir="$(mktemp -d /tmp/hostbackup-cifs.XXXXXXXX)"
case "$fixture_dir" in
  /tmp/hostbackup-cifs.*) ;;
  *) echo 'Unexpected temporary directory; refusing test.' >&2; exit 1 ;;
esac
test "$(realpath -- "$fixture_dir")" = "$fixture_dir"
test ! -L "$fixture_dir"
mount_dir="$fixture_dir/source/network"
smbd_pid=""

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if mountpoint -q -- "$mount_dir"; then
    if ! umount -- "$mount_dir"; then
      echo "CIFS cleanup failed: mount retained at $mount_dir; no recursive deletion attempted." >&2
      status=1
    fi
  fi
  if [ -n "$smbd_pid" ] && kill -0 "$smbd_pid" 2>/dev/null; then
    # setsid made this test daemon the leader of its own process group.
    kill -TERM -- "-$smbd_pid" 2>/dev/null || true
    wait "$smbd_pid" 2>/dev/null || true
  fi
  if [ "$status" -ne 0 ]; then
    for diagnostic in "$fixture_dir/server.log" "$fixture_dir/logs/log.smbd" "$fixture_dir/local.json" "$fixture_dir/network.json" "$fixture_dir/archive.json"; do
      if [ -f "$diagnostic" ]; then
        printf 'CIFS diagnostic: %s\n' "${diagnostic##*/}" >&2
        tail -c 16000 -- "$diagnostic" >&2
        printf '\n' >&2
      fi
    done
  fi
  if ! mountpoint -q -- "$mount_dir" && [ ! -L "$fixture_dir" ] && [ "$(realpath -- "$fixture_dir")" = "$fixture_dir" ]; then
    # This exact mktemp path was validated above; never follow mounted content.
    rm -rf -- "$fixture_dir"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -m 700 -- "$fixture_dir/state" "$fixture_dir/local-target" "$fixture_dir/logs" \
  "$fixture_dir/pid" "$fixture_dir/lock" "$fixture_dir/samba-state" "$fixture_dir/cache" "$fixture_dir/private"
mkdir -m 755 -- "$fixture_dir/source" "$mount_dir"
mkdir -m 777 -- "$fixture_dir/share"
# Only this test fixture contains a guest share; permit traversal to it.
chmod 711 -- "$fixture_dir"
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

# Generate runtime-only fixture data, not a production configuration file.
python3 - "$fixture_dir" "$port" <<'PY'
from pathlib import Path
import sys
base, port = Path(sys.argv[1]), int(sys.argv[2])
(base / "smb.conf").write_text(f"""[global]
  workgroup = WORKGROUP
  server role = standalone server
  security = user
  map to guest = Bad User
  guest account = nobody
  interfaces = 127.0.0.1
  bind interfaces only = yes
  smb ports = {port}
  disable netbios = yes
  server min protocol = SMB2
  unix extensions = no
  load printers = no
  printcap name = /dev/null
  logging = file
  log level = 1
  max log size = 128
  log file = {base}/logs/log.%m
  pid directory = {base}/pid
  lock directory = {base}/lock
  state directory = {base}/samba-state
  cache directory = {base}/cache
  private dir = {base}/private
  passdb backend = tdbsam:{base}/private/passdb.tdb
[probe]
  path = {base}/share
  guest ok = yes
  read only = no
  browseable = no
  create mask = 0666
  directory mask = 0777
  wide links = no
""", encoding="utf-8")
PY
testparm -s "$fixture_dir/smb.conf" >/dev/null

# Baseline must pass on the local Linux filesystem before attributing anything
# to CIFS. This also proves root UID/GID, ACL, xattr, capability and sparse tools.
python3 "$repo_dir/bin/hostbackup-metadata.py" --root "$fixture_dir/local-target" \
  --state-dir "$fixture_dir/state" --mode native-strict > "$fixture_dir/local.json"

setsid smbd --foreground --no-process-group --configfile="$fixture_dir/smb.conf" > "$fixture_dir/server.log" 2>&1 &
smbd_pid=$!
python3 - "$port" <<'PY'
import socket
import sys
import time
port = int(sys.argv[1])
for attempt in range(100):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit("Disposable loopback Samba did not become ready.")
PY
mount -t cifs //127.0.0.1/probe "$mount_dir" \
  -o "guest,username=hostbackup-fixture-guest,vers=3.0,port=$port,nounix,noacl,noperm,uid=12345,gid=12345,forceuid,forcegid,file_mode=0666,dir_mode=0777,cache=none"
mountpoint -q -- "$mount_dir"

# Prove the kernel mount has the intended restrictive semantics, rather than
# accepting an unrelated helper failure as a successful regression test.
python3 - "$mount_dir" <<'PY'
from pathlib import Path
import errno
import os
import stat
import sys
target = Path(sys.argv[1]) / "fixed-attributes-proof"
target.write_text("disposable CIFS fixture\n", encoding="ascii")
try:
    os.chown(target, 1, 1)
    os.chmod(target, 0o6750)
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.EACCES, errno.EOPNOTSUPP}:
        raise
info = target.stat()
assert (info.st_uid, info.st_gid) == (12345, 12345), (info.st_uid, info.st_gid)
assert stat.S_IMODE(info.st_mode) == 0o666, oct(stat.S_IMODE(info.st_mode))
target.unlink()
print("Real CIFS fixture: forced UID/GID 12345:12345, file mode 0666, nounix/noacl.")
PY

probe_status=0
python3 "$repo_dir/bin/hostbackup-metadata.py" --root "$mount_dir" \
  --state-dir "$fixture_dir/state" --mode network-compatible > "$fixture_dir/network.json" || probe_status=$?
test "$probe_status" -eq 1
python3 "$repo_dir/bin/hostbackup-metadata.py" --root "$mount_dir" \
  --state-dir "$fixture_dir/state" --mode portable-archive > "$fixture_dir/archive.json"

python3 - "$fixture_dir" "$repo_dir" <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
base = Path(sys.argv[1])
native, network, archive = [json.loads((base / name).read_text()) for name in ("local.json", "network.json", "archive.json")]
assert native["status"] == "ok", native
assert network["status"] == "error", network
failures = [check for check in network["checks"] if check["status"] == "error"]
assert failures, network
assert all(check.get("details") for check in failures), failures
assert any(check["id"] in {"copy", "restore", "uid", "gid", "permissions", "symlink", "hardlink", "acl-values", "acl-read-restored"} for check in failures), failures
assert any("Portable Archive" in advice for advice in network["advice"]), network
assert archive["status"] == "ok", archive
for key in ("uid", "gid", "permissions", "file-content", "symlink", "hardlink", "sparse-allocation", "acl-values", "xattr-values", "capability-values"):
    assert any(check["id"] == key and check["status"] == "ok" for check in archive["checks"]), (key, archive)
assert not list((base / "source/network").iterdir()), "Probe left test files on CIFS"
assert not list((base / "state").iterdir()), "Probe left local temporary files"

# Exercise source enumeration and the exact non-recursive transport mechanism
# with this REAL CIFS mount. The injectable root confines every walk/copy to our
# tiny fixture; this test never enumerates or backs up the runner's '/'.
spec = importlib.util.spec_from_file_location("hostbackup_cifs_sources", Path(sys.argv[2]) / "bin/hostbackup-sources.py")
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)
source = base / "source"
network_path = source / "network"
mounted = next(row for row in sources.read_mounts() if row["path"] == str(network_path))
assert mounted["fstype"] in {"cifs", "smb3"}, mounted
device = source.stat().st_dev
mounts = [{"path": "/", "fstype": "ext4", "kind": "local", "device": f"{os.major(device)}:{os.minor(device)}"},
          dict(mounted, path="/network")]
(source / "local.txt").write_text("local source sentinel\n", encoding="ascii")
(network_path / "cifs-sentinel.txt").write_text("network source sentinel\n", encoding="ascii")
for included in (False, True):
    name = "selected" if included else "local-only"
    plan = sources.SourcePlan({"policy": "local", "overrides": {"/network": True} if included else {}}, mounts)
    paths = list(sources.enumerate_files(plan, root=source))
    assert "local.txt" in paths, paths
    assert ("network/cifs-sentinel.txt" in paths) == included, paths
    listing = base / (name + ".nul")
    listing.write_bytes(b"".join(os.fsencode(path) + b"\0" for path in paths))
    destination = base / (name + "-copy")
    destination.mkdir(mode=0o700)
    subprocess.run(["rsync", "-aH", "--numeric-ids", "--from0", "--files-from=" + str(listing), "--no-recursive", "--dirs",
                    str(source) + "/", str(destination) + "/"], check=True)
    assert (destination / "local.txt").is_file()
    assert (destination / "network/cifs-sentinel.txt").exists() == included
    archive_path = base / (name + ".tar")
    subprocess.run(["tar", "--format=pax", "-C", str(source), "-cpf", str(archive_path), "--no-recursion", "--null",
                    "--verbatim-files-from", "--files-from=" + str(listing)], check=True)
    with tarfile.open(archive_path) as container:
        names = container.getnames()
    assert ("network/cifs-sentinel.txt" in names) == included, names
print(json.dumps({"cifs_integration": "passed", "source_selection_real_cifs": "passed", "network_compatible": network, "portable_archive": archive}, indent=2))
PY
