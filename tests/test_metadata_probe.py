#!/usr/bin/env python3
"""Metadata diagnostics: deterministic failures everywhere, real roundtrips on Linux."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/hostbackup-metadata.py"
REQUIRE_LINUX = os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1"


def module():
    spec = importlib.util.spec_from_file_location("hostbackup_metadata_probe_test", HELPER)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


metadata = module()


class MetadataDiagnosticTests(unittest.TestCase):
    def test_cifs_fixture_embedded_python_is_syntactically_valid(self):
        script = (ROOT / "tests/run-cifs.sh").read_text(encoding="utf-8")
        blocks = re.findall(r"<<'PY'\n(.*?)\nPY\n", script, flags=re.S)
        self.assertEqual(len(blocks), 5)
        for number, block in enumerate(blocks):
            compile(block, "run-cifs.sh Python block %s" % number, "exec")

    def test_network_compatible_only_omits_xattrs(self):
        self.assertEqual(metadata.rsync_options("network-compatible"), ["-aHA", "--numeric-ids", "--sparse"])
        self.assertIn("-aHAX", metadata.rsync_options("native-strict"))

    def test_fake_super_transport_keeps_receiver_workaround(self):
        backup = metadata.rsync_options("fake-super")
        restore = metadata.rsync_options("fake-super", restoring=True)
        self.assertIn("-M--fake-super", backup)
        self.assertIn("--fake-super", restore)
        self.assertIn("-M--super", restore)
        self.assertIn(metadata.LOCAL_TRANSPORT, backup)
        self.assertIn(metadata.LOCAL_TRANSPORT, restore)
        self.assertEqual(metadata.rsync_destination("fake-super", "/test target"), "hostbackup-local:/test target/")

    def test_failed_rsync_retains_exit_code_and_bounded_redacted_stderr(self):
        def runner(argv):
            return {"exit_code": 23, "stdout": "", "stderr": "rsync: chmod /probe/test failed: Operation not permitted (1); password=secret\n" + "x" * 8000}

        probe = metadata.Probe("network-compatible", runner=runner)
        probe.redactions = [("/probe", "<Zielprobe>")]
        probe.command("copy", "rsync: auf Ziel kopieren", ["rsync"])
        result = probe.result()
        self.assertEqual(result["status"], "error")
        check = result["checks"][0]
        self.assertEqual(check["exit_code"], 23)
        self.assertIn("Operation not permitted", check["stderr"])
        self.assertIn("<Zielprobe>", check["stderr"])
        self.assertNotIn("secret", json.dumps(result))
        self.assertLessEqual(len(check["stderr"]), metadata.OUTPUT_LIMIT + 32)
        self.assertIn("Portable Archive", " ".join(result["advice"]))
        self.assertIn("Nur Vollbackup", " ".join(result["advice"]))
        self.assertIn("offline", " ".join(result["advice"]))

    def test_command_capture_does_not_deadlock_or_retain_unbounded_output(self):
        result = metadata.run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('a'*200000); sys.stderr.write('b'*200000)"])
        self.assertEqual(result["exit_code"], 0)
        self.assertLess(len(result["stdout"]), 4200)
        self.assertLess(len(result["stderr"]), 4200)
        self.assertIn("gekuerzt", result["stderr"])

    def test_timeout_is_a_failure_with_explicit_diagnostic(self):
        result = metadata.run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        self.assertTrue(result["timed_out"])
        probe = metadata.Probe("native-strict", runner=lambda argv: result)
        probe.command("copy", "Kopieren", ["unused"])
        self.assertEqual(probe.result()["status"], "error")
        self.assertIn("Zeitlimit", probe.checks[0]["details"])

    def test_missing_binary_has_parseable_step_error(self):
        result = metadata.run_bounded(["hostbackup-deliberately-missing-test-binary"])
        self.assertEqual(result["exit_code"], 127)
        self.assertTrue(result["stderr"])

    def test_commands_stop_after_shared_budget_is_exhausted(self):
        runner = mock.Mock()
        with mock.patch.object(metadata.time, "monotonic", return_value=0):
            probe = metadata.Probe("network-compatible", runner=runner)
        with mock.patch.object(metadata.time, "monotonic", return_value=metadata.PROBE_COMMAND_BUDGET + 1):
            probe.command("restore", "Zurueckspielen", ["rsync"])
        runner.assert_not_called()
        self.assertEqual(probe.result()["status"], "error")
        self.assertTrue(probe.checks[0]["timed_out"])

    def test_fixed_cifs_ownership_modes_and_acl_are_individual_failures(self):
        probe = metadata.Probe("network-compatible")
        probe.comparison("uid", "Eigentuemer (UID)", 1, 1000)
        probe.comparison("gid", "Gruppe (GID)", 1, 1000)
        probe.comparison("permissions", "Dateirechte (Modus)", "6750", "0666")
        probe.comparison("acl-values", "ACL-Werte", "user:65534:r--", "")
        result = probe.result()
        self.assertEqual(result["status"], "error")
        self.assertEqual([check["id"] for check in result["checks"]], ["uid", "gid", "permissions", "acl-values"])
        self.assertTrue(all(check["status"] == "error" for check in result["checks"]))
        self.assertIn("6750", result["checks"][2]["details"])
        self.assertIn("0666", result["checks"][2]["details"])

    def test_actual_comparison_detects_synthetic_cifs_attributes(self):
        probe = metadata.Probe("network-compatible")
        source, restored = Path("/source"), Path("/restored")
        expected = SimpleNamespace(st_mode=stat.S_IFREG | 0o6750, st_uid=1, st_gid=1, st_dev=1, st_ino=1)
        actual = SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_uid=1000, st_gid=1000, st_dev=2, st_ino=2)
        sparse = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=1048576, st_blocks=0)

        def lstat(path):
            if path.name == "sub":
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700)
            if path.name == "sparse":
                return sparse
            return expected if "source" in path.parts else actual

        def runner(argv):
            value = "user:65534:r--\n" if "source" in Path(argv[-1]).parts else "user::rw-\n"
            return {"exit_code": 0, "stdout": value, "stderr": ""}

        probe.runner = runner
        with mock.patch.object(Path, "lstat", lstat), \
                mock.patch.object(Path, "read_bytes", return_value=b"metadata-probe\n"), \
                mock.patch.object(Path, "open", mock.mock_open(read_data=b"metadata-probe\n")), \
                mock.patch.object(os, "readlink", return_value="sub/file"):
            metadata.compare_restored(probe, source, restored, {"acl": True, "xattr": False, "capability": False})
        failures = {check["id"] for check in probe.checks if check["status"] == "error"}
        self.assertEqual(failures, {"uid", "gid", "permissions", "acl-values"})

    def test_restored_symlink_cannot_be_read_as_probe_payload(self):
        probe = metadata.Probe("network-compatible")
        with mock.patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFLNK)), \
                mock.patch.object(Path, "open") as opened:
            metadata.compare_restored(probe, Path("/source"), Path("/restored"), {"acl": False, "xattr": False, "capability": False})
        opened.assert_not_called()
        self.assertEqual(probe.result()["status"], "error")

    def test_skipped_checks_never_claim_verified_metadata(self):
        probe = metadata.Probe("network-compatible")
        probe.skipped("xattr-values", "xattrs", "Im Profil bewusst ausgelassen.")
        probe.skipped("acl-values", "ACL-Werte", "Werkzeuge fehlen.")
        result = probe.result()
        self.assertIn("Nicht geprueft", result["message"])
        self.assertNotIn("ACL-Werte bestaetigt", result["message"])
        self.assertNotIn("xattr-Werte bestaetigt", result["message"])


@unittest.skipUnless(sys.platform == "linux", "Real metadata target probe requires Linux")
class RealMetadataProbeTests(unittest.TestCase):
    def setUp(self):
        missing = [tool for tool in ("rsync", "tar", "setfacl", "getfacl", "setfattr", "getfattr", "setcap", "getcap") if not shutil.which(tool)]
        if missing:
            if REQUIRE_LINUX:
                self.fail("Linux metadata dependencies missing: " + ", ".join(missing))
            self.skipTest("Linux metadata dependencies missing: " + ", ".join(missing))
        self.workspace = tempfile.TemporaryDirectory(prefix="hostbackup-metadata-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.target, self.state = self.root / "target with ' quote", self.root / "state"
        self.target.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)

    def test_all_profiles_really_copy_and_restore_metadata(self):
        for mode in metadata.MODES:
            with self.subTest(mode=mode):
                result = metadata.execute_probe(self.target, mode, self.state)
                self.assertEqual(result["status"], "ok", json.dumps(result, indent=2))
                self.assertIn("UID/GID", result["message"])
                self.assertIn("ACL-Werte bestaetigt", result["message"])
                if mode != "network-compatible":
                    self.assertIn("xattr-Werte bestaetigt", result["message"])
                    if os.geteuid() == 0:
                        self.assertIn("File Capabilities bestaetigt", result["message"])
                self.assertEqual(list(self.target.iterdir()), [])
                self.assertEqual(list(self.state.iterdir()), [])

    def test_cli_emits_one_json_object_for_missing_target(self):
        result = subprocess.run([sys.executable, str(HELPER), "--root", str(self.root / "missing"),
                                 "--mode", "network-compatible", "--state-dir", str(self.state)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "error")
        self.assertFalse(result.stderr)

    def test_foreign_writable_state_is_rejected_without_target_writes(self):
        self.state.chmod(0o777)
        result = metadata.execute_probe(self.target, "network-compatible", self.state)
        self.assertEqual(result["status"], "error")
        self.assertEqual(list(self.target.iterdir()), [])

    def test_sticky_writable_state_itself_is_not_trusted(self):
        self.state.chmod(0o1777)
        result = metadata.execute_probe(self.target, "network-compatible", self.state)
        self.assertEqual(result["status"], "error")
        self.assertEqual(list(self.target.iterdir()), [])

    def test_real_copy_then_forced_permissions_fails_comparison(self):
        def runner(argv):
            result = metadata.run_bounded(argv)
            if argv[0] == "rsync" and ".metadata-probe." in argv[-2] and result["exit_code"] == 0:
                restored = Path(argv[-1])
                os.chmod(restored / "sub/file", 0o666)
            return result

        result = metadata.execute_probe(self.target, "network-compatible", self.state, runner=runner)
        self.assertEqual(result["status"], "error")
        permissions = next(check for check in result["checks"] if check["id"] == "permissions")
        self.assertEqual(permissions["status"], "error")
        self.assertEqual(permissions["actual"], "0666")


if __name__ == "__main__":
    unittest.main()
