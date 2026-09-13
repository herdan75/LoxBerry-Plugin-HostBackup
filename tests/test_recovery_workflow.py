"""Independent recovery workflow checks; all writes stay in temporary fixtures."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import test_runtime_safety as runtime_tests
from test_runtime_safety import BASH, JOURNAL_FUNCTIONS


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recovery_workflow_module", ROOT / "bin/hostbackup-recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-workflow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backup_root = self.root / "backups"
        self.backup = self.backup_root / "backup-test"
        self.backup.mkdir(parents=True)
        self.destination = self.root / "destination"
        self.destination.mkdir()
        (self.backup / "rsync-excludes.txt").write_text("/home/private\n", encoding="utf-8", newline="\n")

    def plan(self, **kwargs):
        return recovery.build_plan(self.backup, self.backup_root, self.destination, kwargs.pop("mappings", []), kwargs.pop("protected", []), mounts=[], **kwargs)

    def archive(self, files, hardlinks=()):
        # These non-privileged fixtures exercise selection and destination safety.
        # Give synthetic members the fixture owner's identity; TarInfo defaults
        # to root, which would require an unrelated privileged chown on extraction.
        owner = self.root.stat()
        with tarfile.open(self.backup / "rootfs.tar", "w", format=tarfile.PAX_FORMAT) as archive:
            for name, value in files.items():
                entry = tarfile.TarInfo(name)
                entry.uid, entry.gid = owner.st_uid, owner.st_gid
                entry.size = len(value)
                archive.addfile(entry, io.BytesIO(value))
            for name, link in hardlinks:
                entry = tarfile.TarInfo(name)
                entry.uid, entry.gid = owner.st_uid, owner.st_gid
                entry.type = tarfile.LNKTYPE
                entry.linkname = link
                archive.addfile(entry)

    def actual_tar(self, command):
        tar = shutil.which("tar")
        if os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/tar.exe"
            tar = str(candidate) if candidate.exists() else tar
        if not tar:
            self.skipTest("GNU tar unavailable")
        version = subprocess.run([tar, "--version"], text=True, capture_output=True, timeout=10)
        if "GNU tar" not in version.stdout:
            self.skipTest("GNU tar is required")
        command = [tar, *command[1:]]
        if os.name == "nt":
            # Exercise genuine tar member selection on Windows; POSIX ownership,
            # ACL/xattr restoration has separate mandatory Linux fixtures.
            excluded = {"--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--selinux", "--same-owner", "--same-permissions"}
            command = [item.replace("\\", "/") if len(item) > 2 and item[1] == ":" else item for item in command if item not in excluded]
            command.insert(1, "--force-local")
            result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], input=shlex.join(command) + "\n", text=True, capture_output=True, timeout=30)
        else:
            result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_logical_protection_and_live_host_protection_are_distinct_offline(self):
        name = "/opt/loxberry/config/plugins/loxberryhostbackup"
        logical = self.plan(protected=[name])
        live = self.plan(host_protected=[name])
        self.assertIn(name, logical["exclude_rules"])
        self.assertNotIn(name, live["exclude_rules"], "Offline copies should restore saved plugin configuration")

    def test_live_host_protection_is_rebased_when_inside_offline_target(self):
        live = self.destination / "running-state"
        plan = self.plan(host_protected=[str(live)])
        self.assertIn("/running-state", plan["exclude_rules"])

    def test_mapping_cannot_overlap_live_host_protection(self):
        (self.backup / "source-mounts.json").write_text(json.dumps([{"target": "/media/data"}]))
        live = self.destination / "running-state"
        live.mkdir()
        with self.assertRaises(recovery.RecoveryError):
            self.plan(mappings=[{"source": "/media/data", "destination": str(live)}], host_protected=[str(live)])

    def test_secure_destination_rejects_root_writable_and_user_owned_parents(self):
        class Component:
            def __init__(self, uid, mode, parents=()):
                self.info = SimpleNamespace(st_uid=uid, st_mode=mode)
                self.parents = parents
            def stat(self): return self.info
            def __str__(self): return "fixture-path"
        with mock.patch.object(recovery.os, "name", "posix"), mock.patch.object(recovery.os, "geteuid", return_value=0, create=True):
            for parent in (Component(1000, 0o700), Component(0, 0o777)):
                with self.assertRaises(recovery.RecoveryError):
                    recovery.secure_destination(Component(0, 0o700, (parent,)))
            recovery.secure_destination(Component(0, 0o700, (Component(0, 0o1777),)))

    def test_destination_symlink_parent_is_rejected(self):
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.destination, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        child = self.destination / "child"
        child.mkdir()
        with self.assertRaises(recovery.RecoveryError):
            recovery.checked_directory(str(alias / "child"))

    def test_tar_hardlink_to_omitted_target_fails_before_writing(self):
        self.archive({"home/private/keep": b"hidden", "etc/settings": b"new"}, [("etc/alias", "home/private/keep")])
        sentinel = self.destination / "sentinel"
        sentinel.write_text("unchanged")
        with mock.patch.object(recovery, "stream_command") as command, self.assertRaises(recovery.RecoveryError):
            recovery.run_restore(self.plan(), "portable-archive", "portable-tar", False)
        command.assert_not_called()
        self.assertEqual(list(self.destination.iterdir()), [sentinel])

    def test_tar_cross_volume_hardlink_fails_before_any_pass(self):
        (self.backup / "source-mounts.json").write_text(json.dumps([{"target": "/media/data"}]))
        mapped = self.destination / "data"
        mapped.mkdir()
        self.archive({"etc/source": b"system", "media/data/payload": b"volume"}, [("media/data/alias", "etc/source")])
        plan = self.plan(mappings=[{"source": "/media/data", "destination": str(mapped)}])
        with mock.patch.object(recovery, "stream_command") as command, self.assertRaises(recovery.RecoveryError):
            recovery.run_restore(plan, "portable-archive", "portable-tar", False)
        command.assert_not_called()
        self.assertFalse((self.destination / "etc/source").exists())

    def test_real_tar_restores_saved_config_offline_and_preserves_saved_exclusions(self):
        config = "opt/loxberry/config/plugins/loxberryhostbackup/config.json"
        self.archive({"./etc/settings": b"new", "./home/private/keep": b"excluded", "./" + config: b"saved config"})
        private = self.destination / "home/private/keep"
        private.parent.mkdir(parents=True)
        private.write_bytes(b"existing private data")
        with mock.patch.object(recovery, "stream_command", side_effect=self.actual_tar):
            recovery.run_restore(self.plan(host_protected=["/opt/loxberry/config/plugins/loxberryhostbackup"]), "portable-archive", "portable-tar", False)
        self.assertEqual(private.read_bytes(), b"existing private data")
        self.assertEqual((self.destination / config).read_bytes(), b"saved config")
        self.assertEqual((self.destination / "etc/settings").read_bytes(), b"new")
        if os.name == "posix":
            restored = (self.destination / config).stat()
            owner = self.root.stat()
            self.assertEqual((restored.st_uid, restored.st_gid), (owner.st_uid, owner.st_gid))

    def test_real_partial_tar_uses_fresh_directory_and_never_overwrites(self):
        self.archive({"docs/readme.txt": b"saved file"})
        existing = self.destination / "docs/readme.txt"
        existing.parent.mkdir()
        existing.write_bytes(b"existing user file")
        with mock.patch.object(recovery, "stream_command", side_effect=self.actual_tar), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                recovery.restore_files(self.backup, self.backup_root, self.destination, "docs", "portable-archive", "portable-tar", [])
        self.assertEqual(existing.read_bytes(), b"existing user file")
        restored = list(self.destination.glob("recovered-*"))
        self.assertEqual(len(restored), 2)
        for path in restored:
            self.assertEqual((path / "docs/readme.txt").read_bytes(), b"saved file")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                restored_file = (path / "docs/readme.txt").stat()
                owner = self.root.stat()
                self.assertEqual((restored_file.st_uid, restored_file.st_gid), (owner.st_uid, owner.st_gid))

    def test_tar_preview_lists_exact_selected_paths_without_writing(self):
        self.archive({"etc/settings": b"system", "docs/strange\nname": b"newline", "home/private/keep": b"omitted"})
        output = io.StringIO()
        with mock.patch.object(recovery, "stream_command") as command, contextlib.redirect_stdout(output):
            recovery.run_restore(self.plan(), "portable-archive", "portable-tar", True)
        command.assert_not_called()
        entries = [json.loads(line[2:]) for line in output.getvalue().splitlines() if line.startswith("A ")]
        self.assertEqual(entries, ["etc/settings", "docs/strange\nname"])
        self.assertFalse(list(self.destination.iterdir()))

    def test_partial_directory_rejects_symlinked_source_parent(self):
        base = self.backup / "rootfs"
        base.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "data").write_text("outside data")
        try:
            (base / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with mock.patch.object(recovery, "stream_command") as command, self.assertRaises(recovery.RecoveryError):
            recovery.restore_files(self.backup, self.backup_root, self.destination, "linked/data", "native-strict", "directory", [])
        command.assert_not_called()
        self.assertEqual((outside / "data").read_text(), "outside data")


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash required for restore worker behavior")
class RecoveryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-worker-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def worker(self, extra="", expected=0):
        script = r'''
ALLOW_RESTORE=1
mkdir -p "$TEST_ROOT/target/test"
printf '{"metadata":{"mode":"native-strict"},"backup":{"storage_format":"directory"}}' > "$TEST_ROOT/target/test/manifest.json"
restore_eligibility() { printf '%s\n' "$TEST_ROOT/target/test"; }
rsync() { echo forbidden-live-copy >> "$TEST_ROOT/forbidden"; return 99; }
stop_backup_targets() {
  echo stop >> "$TEST_ROOT/order"
  restart_journal_update "$1" intended systemd demo.service
  restart_journal_update "$1" stopped systemd demo.service
}
recovery_helper() {
  if [ "$1" = plan ]; then echo plan >> "$TEST_ROOT/order"; return 0; fi
  if [ "${!#}" = --dry-run ]; then
    echo preview >> "$TEST_ROOT/order"
    [ "${FAIL_PREVIEW:-false}" != true ] || return 18
  else
    echo copy >> "$TEST_ROOT/order"
    [ "${FAIL_COPY:-false}" != true ] || return 7
  fi
}
''' + extra + '\nrestore_backup test false "${DESTINATION:-/}"\n'
        return runtime_tests.RuntimeSafetyTests.run_shell(self, script, (*JOURNAL_FUNCTIONS, "restore_cleanup_on_exit", "restore_backup"), expected=expected)

    def test_complete_preview_precedes_service_stop(self):
        self.worker()
        self.assertEqual((self.root / "order").read_text().splitlines(), ["plan", "preview", "stop", "copy"])
        self.assertFalse((self.root / "forbidden").exists())

    def test_failed_preview_never_stops_services_or_starts_copy(self):
        self.worker("FAIL_PREVIEW=true\n", expected=18)
        self.assertEqual((self.root / "order").read_text().splitlines(), ["plan", "preview"])
        self.assertFalse((self.root / "service-calls").exists())

    def test_copy_and_restart_failure_preserves_recovery_journal(self):
        self.worker("FAIL_COPY=true\nRESTART_FAIL=true\n", expected=7)
        state = json.loads((self.root / "state/tasks/restore-test.log.json").read_text())
        self.assertEqual(state["phase"], "cleanup_failed")
        self.assertTrue((self.root / "state/restart-journals/restore-test.log/journal.json").exists())

    def test_offline_restore_does_not_stop_host_services(self):
        self.worker('DESTINATION="$TEST_ROOT/offline"\n')
        self.assertEqual((self.root / "order").read_text().splitlines(), ["plan", "preview", "copy"])
        self.assertFalse((self.root / "service-calls").exists())

    def eligibility(self, report, confirmation="false", expected=0):
        script = r'''
mkdir -p "$TEST_ROOT/target/test/rootfs"
printf '{"status":"complete","metadata":{"mode":"native-strict"},"backup":{"storage_format":"directory"}}' > "$TEST_ROOT/target/test/manifest.json"
printf '{"status":"ok"}' > "$TEST_ROOT/target/test/backup-validation.json"
safe_backup_target() { printf '%s/test\n' "$1"; }
inspect_backup_directory() { printf '%s\n' "$INSPECTION_REPORT"; }
restore_eligibility test "$INSPECTION_CONFIRMATION"
'''
        return runtime_tests.RuntimeSafetyTests.run_shell(self, script, ("restore_eligibility",),
            env={"INSPECTION_REPORT": json.dumps(report), "INSPECTION_CONFIRMATION": confirmation}, expected=expected)

    def test_local_inspection_warning_cannot_bypass_confirmation_via_manifest(self):
        self.eligibility({"status": "warning", "metadata_mode": "native-strict"}, expected=18)
        self.eligibility({"status": "warning", "metadata_mode": "native-strict"}, "confirm-degraded")

    def test_local_inspection_error_is_not_overridable(self):
        self.eligibility({"status": "error", "metadata_mode": "native-strict"}, "confirm-degraded", expected=18)

    def test_unverified_legacy_profile_requires_explicit_confirmation(self):
        self.eligibility({"status": "ok", "metadata_mode": "legacy-unknown"}, expected=18)

    def test_generic_worker_errexit_preserves_status_after_local_scope_unwinds(self):
        runtime_tests.RuntimeSafetyTests.run_shell(self, r'''
generic_worker() {
  local task=restore-files-test.log log_file="$TASK_LOG_DIR/restore-files-test.log"
  prepare_log_file "$log_file"
  install_task_failure_trap "$task" "$log_file"
  task_state_write "$task" running copying "$log_file" "$$" ''
  fail_copy() { return 17; }
  fail_copy
}
generic_worker
''', expected=17)
        state = json.loads((self.root / "state/tasks/restore-files-test.log.json").read_text())
        self.assertEqual(state["state"], "failed")


if __name__ == "__main__":
    unittest.main()
