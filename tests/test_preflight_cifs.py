#!/usr/bin/env python3
"""Actual shared preflight on the disposable CIFS fixture, never on host data.

Normal unit-test discovery skips this opt-in Linux/root integration. run-cifs.sh
supplies HOSTBACKUP_PREFLIGHT_CIFS_TARGET and HOSTBACKUP_REQUIRE_CIFS_PREFLIGHT=1.
Only fresh child directories on that loopback mount are touched. Metadata probes,
df, mount lookup and (when supplied) the trusted portable runtime are real.
Configuration/target registration, source enumeration, history and Docker are
fixture-only substitutes; the backend entry point/backup worker is never sourced.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TARGET = os.environ.get("HOSTBACKUP_PREFLIGHT_CIFS_TARGET", "")
RUNTIME = os.environ.get("HOSTBACKUP_PORTABLE_RUNTIME", "")
REQUIRED = os.environ.get("HOSTBACKUP_REQUIRE_CIFS_PREFLIGHT") == "1"
ENABLED = bool(TARGET) and sys.platform.startswith("linux") and os.geteuid() == 0
FUNCTIONS = (
    "json_escape", "current_mount_value", "metadata_mode", "portable_snapshot",
    "portable_helper", "metadata_capability_probe", "require_root_permission_ack",
    "baseline_space_requirement_mb", "backup_inode_status", "preflight_backup",
)


def extracted_functions():
    source = (ROOT / "bin/hostbackup.sh").read_text(encoding="utf-8")
    result = []
    for name in FUNCTIONS:
        match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n(?=\n)", source, re.M | re.S)
        if not match:
            raise AssertionError("Missing production function: " + name)
        result.append(match.group(0))
    return "\n".join(result)


SETUP = r'''
set -euo pipefail
umask 077
json_get_string() {
  case "$1" in
    backup_root) printf '%s\n' "$TEST_TARGET" ;;
    backup_mode) printf '%s\n' "$TEST_BACKUP_MODE" ;;
    metadata_mode) printf '%s\n' "$TEST_METADATA_MODE" ;;
  esac
}
json_get_bool() {
  case "$1" in
    root_permission_ack|stop_docker_before_backup) echo true ;;
    *) echo false ;;
  esac
}
backup_root() { printf '%s\n' "$TEST_TARGET"; }
verify_backup_target() { [ "$1" = "$TEST_TARGET" ] && [ -d "$1" ] && [ -w "$1" ]; }
source_info() { printf '%s\n' '{"status":"ok","selection":{"policy":"local","overrides":{}},"volumes":[],"notices":[],"errors":[]}'; }
latest_complete_backup() { :; }
latest_sized_complete_backup() { :; }
backup_excludes() { printf '%s\n' /proc /sys /dev; }
selected_docker_stop_count() { echo 0; }
docker() { [ "$1" = ps ] || { echo 'Forbidden host Docker operation' >&2; exit 97; }; }
systemctl() { echo 'Forbidden host service operation' >&2; exit 97; }
'''

EXHAUSTED_INODES = r'''
# Only this negative control substitutes inode capacity. Space remains real;
# the three NAS regression cases use the unmodified system df command.
df() {
  if [ "${1:-}" = --output=itotal,iavail ]; then
    printf 'Inodes IFree\n10 0\n'
  else
    command df "$@"
  fi
}
'''


class CifsPreflightHarnessTests(unittest.TestCase):
    def test_extracted_harness_contains_real_gate_and_real_metadata_probe(self):
        source = extracted_functions()
        self.assertIn('LC_ALL=C df --output=itotal,iavail', source)
        self.assertIn('metadata_capability_probe "$root" "$mode"', source)
        self.assertIn('hostbackup-metadata.py', source)
        self.assertIn('portable_helper probe', source)
        self.assertNotIn('create_backup() {', source)
        self.assertNotIn('stop_backup_targets() {', source)

    def test_required_integration_cannot_silently_skip(self):
        if REQUIRED:
            self.assertTrue(ENABLED, "CIFS preflight integration requires Linux, root and the disposable test target")
            if os.environ.get("HOSTBACKUP_RUN_REPOSITORY_INTEGRATION") == "1":
                self.assertTrue(RUNTIME, "Mandatory repository CI must supply its trusted portable runtime")
                for name in ("hostbackup-portable.py", "hostbackup-metadata.py", "restic"):
                    self.assertTrue((Path(RUNTIME) / name).is_file(), "Incomplete portable CI runtime: " + name)
                self.assertTrue(os.access(Path(RUNTIME) / "restic", os.X_OK), "Portable CI engine must be executable")


@unittest.skipUnless(ENABLED, "Opt-in disposable Linux CIFS preflight integration")
class CifsPreflightIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mount = Path(TARGET)
        cls.assert_fixture_path()
        for tool in ("bash", "df", "findmnt", "python3", "perl", "rsync", "tar"):
            if not shutil.which(tool):
                raise AssertionError("Missing required CIFS preflight tool: " + tool)
        mounted = subprocess.run(
            ["findmnt", "-rn", "-T", str(cls.mount), "-o", "TARGET,FSTYPE,SOURCE"],
            capture_output=True, text=True, check=True,
        ).stdout.strip().split()
        if mounted != [str(cls.mount), "cifs", "//127.0.0.1/probe"]:
            raise AssertionError("Only run-cifs.sh's exact loopback CIFS fixture is allowed: " + repr(mounted))
        cls.shell_functions = extracted_functions()

    @classmethod
    def assert_fixture_path(cls):
        # No production/NAS path can be supplied accidentally. The parent runner
        # owns this exact mktemp tree and performs the only mount/unmount actions.
        if not re.fullmatch(r"/tmp/hostbackup-cifs\.[A-Za-z0-9]+/source/network", str(cls.mount)):
            raise AssertionError("Not a disposable run-cifs.sh fixture: " + str(cls.mount))
        if cls.mount.resolve() != cls.mount or not os.path.ismount(cls.mount):
            raise AssertionError("CIFS fixture must be a canonical mountpoint")

    def setUp(self):
        self.local = tempfile.TemporaryDirectory(prefix="hostbackup-preflight-local-")
        self.addCleanup(self.local.cleanup)
        self.state = Path(self.local.name) / "state"
        self.state.mkdir(mode=0o700)
        self.remote = tempfile.TemporaryDirectory(prefix="preflight-", dir=self.mount)
        self.addCleanup(self.remote.cleanup)
        self.target = Path(self.remote.name)
        self.raw_df = subprocess.run(
            ["df", "--output=itotal,iavail", "--", str(self.target)], capture_output=True, text=True,
            env={**os.environ, "LC_ALL": "C"}, check=True,
        ).stdout
        columns = self.raw_df.splitlines()[1].split()
        self.assertEqual((int(columns[0]), int(columns[1])), (0, 0),
                         "Fixture did not reproduce NAS unreported inode capacity:\n" + self.raw_df)

    def portable(self, action):
        result = subprocess.run(
            [sys.executable, str(Path(RUNTIME) / "hostbackup-portable.py"),
             "--root", str(self.target), "--state-dir", str(self.state), action],
            capture_output=True, timeout=180, check=False,
        )
        # Never print recovery keys to CI output, including assertion diagnostics.
        self.assertEqual(result.returncode, 0, "Portable fixture setup failed: " + action + "\n" + result.stderr.decode())
        if action == "key-export":
            (Path(self.local.name) / "recovery-key.json").write_bytes(result.stdout)
            return None
        return json.loads(result.stdout)

    def preflight(self, mode="portable-archive", backup_mode="full", exhausted=False):
        result = subprocess.run(
            ["bash", "-s"], input=SETUP + "\n" + self.shell_functions +
            (EXHAUSTED_INODES if exhausted else "") + "\npreflight_backup\n",
            text=True, encoding="utf-8", capture_output=True, timeout=240, check=False,
            env={**os.environ, "TEST_TARGET": str(self.target), "ROOT_STATE_DIR": str(self.state),
                 "LBP_BINDIR": RUNTIME or str(ROOT / "bin"), "TEST_METADATA_MODE": mode,
                 "TEST_BACKUP_MODE": backup_mode},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["backup_root"], str(self.target))
        self.assertEqual(json.loads((self.state / "metadata-probe.json").read_text()), data["metadata_probe"])
        print(json.dumps({"cifs_preflight": self._testMethodName, "raw_inode_df": self.raw_df.strip(),
                          "inode_capacity_stubbed": exhausted, "result": data}, ensure_ascii=True))
        return data

    def assert_unknown_inodes(self, data):
        check = next(item for item in data["checks"] if item["name"] == "Freie Inodes")
        self.assertTrue(check["ok"], check)
        self.assertTrue(check["informational"], check)
        self.assertIn("unbekannt", check["value"].lower())
        self.assertTrue(any("inode" in item.lower() and "unbekannt" in item.lower()
                            for item in data["notices"]), data)
        self.assertFalse(any("keine freien Inodes" in item for item in data["warnings"]), data)

    def assert_metadata_ok(self, data):
        self.assertEqual(data["metadata_probe"]["status"], "ok", data)
        for key in ("uid", "gid", "permissions", "symlink", "hardlink", "acl-values", "xattr-values", "capability-values"):
            self.assertTrue(any(check["id"] == key and check["status"] == "ok"
                                for check in data["metadata_probe"]["checks"]), (key, data))

    def test_real_cifs_unknown_inodes_allow_portable_full_preflight(self):
        data = self.preflight()
        self.assertEqual(data["status"], "ok", data)
        self.assert_metadata_ok(data)
        self.assert_unknown_inodes(data)

    @unittest.skipUnless(RUNTIME, "Trusted portable runtime required for real repository preflight")
    def test_real_cifs_unknown_inodes_allow_portable_snapshot_preflight(self):
        (self.target / ".loxberry-hostbackup-target").write_bytes(b"disposable-preflight-fixture\n")
        self.portable("init")
        self.portable("key-export")
        self.assertTrue(self.portable("confirm-key")["key_confirmed"])
        data = self.preflight(backup_mode="snapshot")
        self.assertEqual(data["status"], "ok", data)
        self.assert_metadata_ok(data)
        self.assert_unknown_inodes(data)
        self.assertTrue(next(item for item in data["checks"]
                             if item["name"] == "Portable Repository und Wiederherstellungsschluessel")["ok"])

    def test_real_cifs_unknown_inodes_do_not_hide_metadata_failure(self):
        data = self.preflight(mode="network-compatible")
        self.assertEqual(data["status"], "error", data)
        self.assertEqual(data["metadata_probe"]["status"], "error", data)
        self.assertTrue(any(check["id"] in {"uid", "gid", "permissions", "symlink", "hardlink", "acl-values", "copy", "restore"}
                            and check["status"] == "error" for check in data["metadata_probe"]["checks"]), data)
        self.assertFalse(next(item for item in data["checks"] if item["name"] == "Metadaten-Modus")["ok"])
        self.assert_unknown_inodes(data)

    def test_known_exhausted_inodes_still_block_with_successful_portable_probe(self):
        data = self.preflight(exhausted=True)
        self.assertEqual(data["status"], "error", data)
        self.assert_metadata_ok(data)
        self.assertFalse(next(item for item in data["checks"] if item["name"] == "Freie Inodes")["ok"])
        self.assertTrue(any("keine freien Inodes" in item for item in data["warnings"]), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
