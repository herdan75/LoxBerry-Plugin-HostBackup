"""Public preflight dispatch must not race a running backup/restore.

Exercise the actual CLI dispatch and lock function with disposable paths and
inert action bodies. Linux additionally tests real cross-process flock. No real
backup target, service, container or privileged dispatcher is accessed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_runtime_safety import BASH, SOURCE, function


BACKEND = SOURCE.read_text(encoding="utf-8")
DISPATCH = BACKEND[BACKEND.rindex('action="${1:-}"\ncase "$action" in'):]
PUBLIC_PREFLIGHTS = (("preflight-backup",), ("preflight-restore", "fixture-backup"), ("backup-preview",))
SETUP = r'''
set -euo pipefail
cd -- "$PREFLIGHT_TEST_DIR"
TEST_ROOT="$(pwd)"
OPERATION_LOCK_FILE="$TEST_ROOT/operation.lock"
unset HOSTBACKUP_OPERATION_LOCK_HELD
require_root_permission_ack() {
  printf 'permission-check\n' >> "$TEST_ROOT/calls"
  return "${ACCESS_STATUS:-0}"
}
target_work() {
  [ "${HOSTBACKUP_OPERATION_LOCK_HELD:-0}" = 1 ] || return 88
  printf 'target-work:%s\n' "$1" >> "$TEST_ROOT/calls"
  printf '{"status":"ok"}\n'
}
preflight_backup() { require_root_permission_ack || return $?; target_work backup; }
preflight_restore() { require_root_permission_ack || return $?; target_work "restore:$1"; }
backup_preview() { require_root_permission_ack || return $?; target_work preview; }
browse_backup() { printf 'browse:%s\n' "$1"; }
task_status() { printf 'status:%s\n' "$1"; }
show_task_log() { printf 'log:%s\n' "$1"; }
stop_backup() { printf 'stop:%s\n' "$1"; }
systemctl() { printf 'UNEXPECTED-SERVICE-CALL\n' >> "$TEST_ROOT/calls"; return 99; }
docker() { printf 'UNEXPECTED-CONTAINER-CALL\n' >> "$TEST_ROOT/calls"; return 99; }
'''
MOCK_FLOCK = r'''
flock() {
  printf '%s\n' "$*" >> "$TEST_ROOT/flock-calls"
  [ "$*" = '-n -E 5 -s 9' ] || return 64
  [ "${FLOCK_STATUS:-0}" -ne 64 ] || echo 'Simulated lock I/O error' >&2
  return "${FLOCK_STATUS:-0}"
}
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash required for public preflight tests")
class PreflightConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-preflight-lock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.active_marker = self.root / "running-backup"
        self.active_marker.write_text("unchanged-running-worker", encoding="utf-8")

    def run_dispatch(self, args, *, real_lock=False, extra="", env=None, expected=0):
        program = SETUP + "\n" + function("acquire_operation_lock")
        if not real_lock:
            program += MOCK_FLOCK
        program += "\n" + extra + "\n" + DISPATCH
        result = subprocess.run([BASH, "--noprofile", "--norc", "-s", "--", *args],
                                input=program, text=True, capture_output=True, timeout=10,
                                env={**os.environ, "PREFLIGHT_TEST_DIR": self.root.as_posix(), **(env or {})})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(self.active_marker.read_text(), "unchanged-running-worker")
        return result

    def test_busy_public_preflights_exit_before_permission_target_or_repository_work(self):
        for args in PUBLIC_PREFLIGHTS:
            with self.subTest(args=args):
                result = self.run_dispatch(args, env={"FLOCK_STATUS": "5"}, expected=5)
                self.assertIn("Another HostBackup operation is active.", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse((self.root / "calls").exists())
        self.assertEqual((self.root / "flock-calls").read_text().splitlines(), ["-n -E 5 -s 9"] * 3)

    def test_uncontended_public_preflights_hold_shared_lock_before_target_work(self):
        for args in PUBLIC_PREFLIGHTS:
            with self.subTest(args=args):
                result = self.run_dispatch(args)
                self.assertEqual(result.stdout.strip(), '{"status":"ok"}')
        self.assertEqual((self.root / "calls").read_text().splitlines(), [
            "permission-check", "target-work:backup", "permission-check",
            "target-work:restore:fixture-backup", "permission-check", "target-work:preview",
        ])
        self.assertEqual((self.root / "flock-calls").read_text().splitlines(), ["-n -E 5 -s 9"] * 3)

    def test_shared_lock_does_not_bypass_existing_permission_checks(self):
        for args in PUBLIC_PREFLIGHTS:
            with self.subTest(args=args):
                result = self.run_dispatch(args, env={"ACCESS_STATUS": "13"}, expected=13)
                self.assertEqual(result.stdout, "")
        self.assertEqual((self.root / "calls").read_text().splitlines(), ["permission-check"] * 3)

    def test_technical_lock_failure_is_not_hidden_or_treated_as_busy_success(self):
        for args in PUBLIC_PREFLIGHTS:
            with self.subTest(args=args):
                result = self.run_dispatch(args, env={"FLOCK_STATUS": "64"}, expected=64)
                self.assertIn("Simulated lock I/O error", result.stderr)
                self.assertNotIn("Another HostBackup operation", result.stderr)
                self.assertFalse((self.root / "calls").exists())

    def test_lock_open_error_prevents_target_work(self):
        for args in PUBLIC_PREFLIGHTS:
            with self.subTest(args=args):
                result = self.run_dispatch(args, extra='OPERATION_LOCK_FILE="$TEST_ROOT/missing/operation.lock"', expected=1)
                self.assertTrue(result.stderr)
                self.assertFalse((self.root / "calls").exists())
                self.assertFalse((self.root / "flock-calls").exists())

    def test_lock_does_not_blanket_block_browse_status_log_or_stop(self):
        for args, expected_output in (
            (("browse", "old-backup", "etc"), "browse:old-backup"),
            (("task-status", "backup-running.log"), "status:backup-running.log"),
            (("task-log", "backup-running.log"), "log:backup-running.log"),
            (("stop", "running-backup"), "stop:running-backup"),
        ):
            with self.subTest(args=args):
                result = self.run_dispatch(args, env={"FLOCK_STATUS": "5"})
                self.assertEqual(result.stdout.strip(), expected_output)
        self.assertFalse((self.root / "flock-calls").exists())
        self.assertFalse((self.root / "calls").exists())

    def test_worker_preflights_remain_inside_existing_exclusive_lock(self):
        for name in ("create_backup", "start_backup"):
            body = function(name)
            self.assertLess(body.index("acquire_operation_lock exclusive"), body.index("preflight_backup"))
        for name in ("preflight_backup", "preflight_restore", "backup_preview"):
            self.assertNotIn("acquire_operation_lock", function(name))
        self.assertNotIn("acquire_operation_lock", function("browse_backup"))
        self.assertIn('acquire_backup_lock "$backup_id" shared', function("browse_backup"))

    @unittest.skipUnless(sys.platform == "linux", "Real flock contention requires Linux")
    def test_real_exclusive_worker_lock_blocks_every_public_preflight_immediately(self):
        if not shutil.which("flock"):
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Real lock test dependency missing: flock")
            self.skipTest("Real lock test dependency missing: flock")
        import fcntl
        with (self.root / "operation.lock").open("w") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for args in PUBLIC_PREFLIGHTS:
                with self.subTest(args=args):
                    result = self.run_dispatch(args, real_lock=True, expected=5)
                    self.assertIn("Another HostBackup operation is active.", result.stderr)
                    self.assertFalse((self.root / "calls").exists())
            # The worker's lock remains held, not unlocked by failed readers.
            with (self.root / "operation.lock").open("a") as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.run_dispatch(("preflight-backup",), real_lock=True)

    @unittest.skipUnless(sys.platform == "linux", "Real flock sharing requires Linux")
    def test_real_shared_reader_allows_preflight_and_releases_on_exit(self):
        if not shutil.which("flock"):
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Real lock test dependency missing: flock")
            self.skipTest("Real lock test dependency missing: flock")
        import fcntl
        with (self.root / "operation.lock").open("w") as holder:
            fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
            for args in PUBLIC_PREFLIGHTS:
                with self.subTest(args=args):
                    self.run_dispatch(args, real_lock=True)
        with (self.root / "operation.lock").open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
