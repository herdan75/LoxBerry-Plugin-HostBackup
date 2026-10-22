"""State, race and no-write matrix for released LoxPanel manual-stop support."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compat_watchdog", ROOT / "bin/hostbackup-watchdog.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)
IDENTITY = "a" * 64
OTHER = "b" * 64
FINGERPRINT = (10, 20, 0, 30, 40)
HOME = "/fixture/loxberry"
MARKER = HOME + "/config/plugins/loxpanel/loxpanel_stopped.cfg"
LEGACY = '''#!/bin/bash
STOPPED="/fixture/loxberry/config/plugins/loxpanel/loxpanel_stopped.cfg"
case "$1" in
check)
    [ -f "$STOPPED" ] && exit 0 # user stop
    running || start
    ;;
esac
'''


class CompatibilityMatrixTests(unittest.TestCase):
    def test_actual_docker_state_schema_and_all_states(self):
        for status in ("created", "running", "paused", "restarting", "removing", "exited", "dead"):
            for running in (False, True):
                for restarting in (False, True):
                    value = {"Status": status, "Running": running, "Restarting": restarting}
                    result = types.SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())
                    with self.subTest(**value), patch.object(w.subprocess, "run", return_value=result) as run:
                        if status == "dead":
                            with self.assertRaises(w.GuardError):
                                w.container_state(IDENTITY)
                        else:
                            expected = "stopped" if status in ("created", "exited") and not running and not restarting else "running"
                            self.assertEqual(w.container_state(IDENTITY), expected)
                        args = run.call_args.args[0]
                        self.assertEqual(args[0:2], ["docker", "inspect"])
                        self.assertEqual(args[-1], IDENTITY)
                        self.assertLessEqual(run.call_args.kwargs["timeout"], 10)

    def test_docker_unavailable_or_malformed_never_means_stopped(self):
        values = [None, [], {}, {"Status": "exited", "Running": "false"},
                  {"Status": "exited", "Running": False, "Restarting": "false"},
                  {"Status": "unknown", "Running": False}, {"Running": False}]
        for value in values:
            with self.subTest(value=value), patch.object(w.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())):
                with self.assertRaises(w.GuardError):
                    w.container_state(IDENTITY)
        for code, data in ((1, b"{}"), (0, b"not json"), (0, b"\xff"), (0, b" " * (w.MAX_TEXT + 1))):
            with self.subTest(code=code, size=len(data)), patch.object(w.subprocess, "run", return_value=types.SimpleNamespace(returncode=code, stdout=data)):
                with self.assertRaises(w.GuardError):
                    w.container_state(IDENTITY)
        for exc in (FileNotFoundError(), subprocess.TimeoutExpired("docker", 5)):
            with patch.object(w.subprocess, "run", side_effect=exc), self.assertRaises(w.GuardError):
                w.container_state(IDENTITY)
        for identity in ("loxpanel", "a" * 12, "x" * 64, "--all", "a" * 65):
            with patch.object(w.subprocess, "run", side_effect=AssertionError("Invalid identity must not execute")), self.assertRaises(w.GuardError):
                w.container_state(identity)

    def test_manual_guard_accepts_only_matching_quiescent_or_absent_identity(self):
        for identity in (None, IDENTITY):
            with self.subTest(identity=identity), patch.object(w, "marker_fingerprint", return_value=FINGERPRINT), \
                    patch.object(w, "docker_inventory", return_value=[] if identity is None else [(identity, "loxpanel")]), \
                    patch.object(w, "container_state", return_value="stopped") as state:
                guard = w.ManualStopGuard(MARKER, identity)
                guard.check()
                guard.close()
                if identity is None:
                    state.assert_not_called()
                else:
                    state.assert_called_with(IDENTITY)

    def test_manual_guard_detects_restart_replacement_removal_and_new_container(self):
        for before, after in ((None, IDENTITY), (IDENTITY, None), (IDENTITY, OTHER), (IDENTITY, IDENTITY)):
            with self.subTest(before=before, after=after), patch.object(w, "marker_fingerprint", return_value=FINGERPRINT), \
                    patch.object(w, "docker_inventory", return_value=[] if before is None else [(before, "loxpanel")]) as inventory, \
                    patch.object(w, "container_state", return_value="stopped") as state:
                guard = w.ManualStopGuard(MARKER, before)
                inventory.return_value = [] if after is None else [(after, "loxpanel")]
                if before == after:
                    state.return_value = "running"
                with self.assertRaises(w.GuardError):
                    guard.check()
                guard.close()

    def test_manual_guard_missing_changed_marker_or_docker_error_never_passes(self):
        for failure in ("marker-removed", "marker-replaced", "docker-offline", "inspect-failed"):
            with self.subTest(failure=failure), patch.object(w, "marker_fingerprint", return_value=FINGERPRINT) as marker, \
                    patch.object(w, "docker_inventory", return_value=[(IDENTITY, "loxpanel")]) as inventory, \
                    patch.object(w, "container_state", return_value="stopped") as state:
                guard = w.ManualStopGuard(MARKER, IDENTITY)
                if failure == "marker-removed":
                    marker.side_effect = w.GuardError("Marker missing")
                elif failure == "marker-replaced":
                    marker.return_value = (10, 21, 0, 30, 40)
                elif failure == "docker-offline":
                    inventory.side_effect = w.GuardError("Docker unavailable")
                else:
                    state.side_effect = w.GuardError("Inspect failed")
                with self.assertRaises(w.GuardError):
                    guard.check()
                guard.close()

    def test_selection_matrix_and_old_ids_do_not_select_replacement_by_name(self):
        cases = [("docker\tloxpanel", False, True), ("", True, True), ("", False, False),
                 ("systemd\tmosquitto.service", True, False), ("docker\tsonn-core", True, False),
                 ("docker\t" + IDENTITY, False, True), ("docker\t" + IDENTITY[:12], False, True),
                 ("docker\t" + OTHER, False, False)]
        for targets, legacy, expected in cases:
            with self.subTest(targets=targets, legacy=legacy), patch.object(w, "read_text", return_value=LEGACY), \
                    patch.object(w, "docker_inventory", return_value=[(IDENTITY, "loxpanel")]):
                profile = w.resolve_coordination(HOME, targets, legacy)
                self.assertEqual(profile["mode"], "manual-stop" if expected else "skip")
        with patch.object(w, "read_text", return_value=LEGACY), patch.object(w, "docker_inventory", return_value=[(IDENTITY, "loxpanel"), (OTHER, IDENTITY[:12])]):
            self.assertEqual(w.resolve_coordination(HOME, "docker\t" + IDENTITY[:12], False)["mode"], "skip")

    def test_absent_installed_app_requires_marker_instead_of_early_success(self):
        for targets, legacy in (("docker\tloxpanel", False), ("", True)):
            with self.subTest(targets=targets), patch.object(w, "read_text", return_value=LEGACY), \
                    patch.object(w, "docker_inventory", return_value=[]), \
                    patch.object(w, "marker_fingerprint", side_effect=w.GuardError("LoxPanel bewusst stoppen")):
                result = w.probe(HOME, targets, legacy)
                self.assertFalse(result["ok"])
                self.assertTrue(result["applicable"])
                self.assertIn("stoppen", result["details"])

    def test_probe_is_read_only_preserves_manual_stop_and_detects_controller_change(self):
        with patch.object(w, "read_text", return_value=LEGACY) as controller, \
                patch.object(w, "marker_fingerprint", return_value=FINGERPRINT), \
                patch.object(w, "docker_inventory", return_value=[]), \
                patch.object(w, "LockGuard", side_effect=AssertionError("No lock for manual stop")), \
                patch.object(w.subprocess, "run", side_effect=AssertionError("No mutating command")):
            result = w.probe(HOME, "docker\tloxpanel", False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "manual-stop")
            self.assertIn("wieder starten", result["details"])
            controller.side_effect = [LEGACY, LEGACY + "\n# changed"]
            result = w.probe(HOME, "docker\tloxpanel", False)
            self.assertFalse(result["ok"])
            self.assertIn("geaendert", result["details"])

    def test_unsupported_controller_and_partial_install_are_actionable_failures(self):
        with patch.object(w, "read_text", return_value="#!/bin/bash\nexit 0\n"), patch.object(w, "docker_inventory", return_value=[]):
            result = w.probe(HOME, "docker\tloxpanel", False)
            self.assertFalse(result["ok"])
            self.assertEqual(result["mode"], "unsupported")
        for installed in (True, False):
            with patch.object(w, "read_text", side_effect=FileNotFoundError()), patch.object(w, "safe_path_present", return_value=installed):
                result = w.probe(HOME, "docker\tloxpanel", False)
                self.assertEqual(result["ok"], not installed)
                self.assertEqual(result["mode"], "unsupported" if installed else "skip")


@unittest.skipUnless(sys.platform == "linux", "Real stop-marker path and credential checks require Linux")
class ManualMarkerLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-manual-marker-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.marker = self.base / "loxpanel_stopped.cfg"
        self.marker.write_bytes(b"user stop, preserve\n")
        self.marker.chmod(0o644)
        import pwd
        account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
        for name, value in (("watchdog_account", (account.pw_uid, account.pw_gid, os.getgrouplist(account.pw_name, account.pw_gid))),
                            ("docker_inventory", [])):
            patcher = patch.object(w, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_success_failure_close_preserve_user_marker_and_mode(self):
        original = self.marker.stat()
        guard = w.ManualStopGuard(str(self.marker), None)
        guard.check()
        guard.close()
        with patch.object(w, "docker_inventory", return_value=[(OTHER, "loxpanel")]), self.assertRaises(w.GuardError):
            guard.check()
        guard.close()
        current = self.marker.stat()
        self.assertEqual((original.st_ino, original.st_mode, original.st_mtime_ns),
                         (current.st_ino, current.st_mode, current.st_mtime_ns))
        self.assertEqual(self.marker.read_bytes(), b"user stop, preserve\n")

    def test_replaced_marker_inode_is_detected_without_removing_new_file(self):
        guard = w.ManualStopGuard(str(self.marker), None)
        replacement = self.base / "new-marker"
        replacement.write_bytes(b"new user stop")
        replacement.chmod(0o644)
        replacement.replace(self.marker)
        with self.assertRaises(w.GuardError):
            guard.check()
        guard.close()
        self.assertEqual(self.marker.read_bytes(), b"new user stop")

    def test_absent_marker_is_not_created(self):
        self.marker.unlink()
        with self.assertRaises(w.GuardError):
            w.ManualStopGuard(str(self.marker), None)
        self.assertFalse(self.marker.exists())

    def test_symlink_hardlink_fifo_directory_and_symlink_parent_are_rejected(self):
        ordinary = self.base / "ordinary"
        ordinary.write_bytes(b"unchanged")
        ordinary.chmod(0o644)
        self.marker.unlink()
        for kind in ("symlink", "hardlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                if kind == "symlink": self.marker.symlink_to(ordinary)
                elif kind == "hardlink": os.link(ordinary, self.marker)
                elif kind == "fifo": os.mkfifo(self.marker)
                else: self.marker.mkdir()
                with self.assertRaises((w.GuardError, OSError)):
                    w.ManualStopGuard(str(self.marker), None)
                if kind == "directory": self.marker.rmdir()
                else: self.marker.unlink()
        actual = self.base / "actual"
        actual.mkdir()
        link = self.base / "linked"
        link.symlink_to(actual, target_is_directory=True)
        (actual / self.marker.name).write_bytes(b"preserve")
        with self.assertRaises((w.GuardError, OSError)):
            w.ManualStopGuard(str(link / self.marker.name), None)
        self.assertEqual(ordinary.read_bytes(), b"unchanged")

    def test_marker_does_not_require_read_permission_for_upstream_stat_test(self):
        self.marker.chmod(0)
        guard = w.ManualStopGuard(str(self.marker), None)
        guard.check()
        guard.close()
        self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "Root needed for a different watchdog user's path access")
    def test_marker_in_inaccessible_parent_is_not_trusted(self):
        self.base.chmod(0o700)
        with self.assertRaises((w.GuardError, OSError)):
            w.ManualStopGuard(str(self.marker), None)
        self.assertEqual(stat.S_IMODE(self.base.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
