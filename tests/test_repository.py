#!/usr/bin/env python3
"""Repository protocol/security tests plus opt-in real Linux Restic roundtrips."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hostbackup_repository_test", ROOT / "bin/hostbackup-repository.py")
repository = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repository)
SID = "a" * 64
MOUNT = {"target": "/mnt/test", "source": "//nas/backup", "fstype": "cifs"}


class FakeRestic:
    def __init__(self):
        self.calls = []
        self.rows = []
        self.nodes = {}
        self.contents = {}
        self.version = repository.VERSION
        self.backup_code = 0
        self.selection = {"/source": "dir", "/source/allowed": "file"}

    def __call__(self, argv, stdin=None):
        self.calls.append((argv, stdin))
        if argv[1] == "version":
            return 0, json.dumps({"version": self.version}).encode(), b""
        index = argv.index("--json") + 1
        args = argv[index:]
        command = args[0]
        if command == "init":
            Path(argv[argv.index("--repo") + 1]).mkdir()
        if command == "cat":
            return 0, json.dumps({"id": SID}).encode(), b""
        if command == "snapshots":
            return 0, json.dumps(self.rows).encode(), b""
        if command == "backup":
            sid = hashlib.sha256(str(len(self.rows)).encode()).hexdigest()
            tags = [args[i + 1] for i, item in enumerate(args) if item == "--tag"]
            row = {"id": sid, "tags": tags, "hostname": args[args.index("--host") + 1]}
            self.rows.append(row)
            self.nodes[sid] = {"/hostbackup-control.json": "file"} if stdin else dict(self.selection)
            if stdin:
                self.contents[sid] = stdin
            summary = {"message_type": "summary", "snapshot_id": sid, "data_added": 1024}
            return self.backup_code, json.dumps(summary).encode(), b"read error" if self.backup_code else b""
        if command == "ls":
            output = b"\n".join(json.dumps({"struct_type": "node", "path": path, "type": kind}).encode()
                                for path, kind in self.nodes[args[1]].items())
            return 0, output, b""
        if command == "dump":
            return 0, self.contents[args[1]], b""
        if command == "forget":
            self.rows = [row for row in self.rows if row["id"] != args[1]]
        return 0, b"{}", b""


class RepositoryUnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        os.chmod(self.base, 0o700)
        self.target = self.base / "target"
        self.target.mkdir(mode=0o700)
        (self.target / repository.MARKER).write_text("registered-target\n")
        self.state = self.base / "state"
        self.state.mkdir(mode=0o700)
        self.fake = FakeRestic()
        self.adapter = repository.Repository(self.target, self.state, engine="/trusted/restic", runner=self.fake,
                                             identity_reader=lambda path: dict(MOUNT))
        self.adapter.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def enable(self):
        result = self.adapter.export_key(self.base / "key.json")
        self.adapter.confirm_key(result["sha256"])

    def candidate(self, backup_id="backup-1", lineage="system"):
        attributes = {"uid": 0, "gid": 0, "mode": 0o755, "mtime_ns": 1, "atime_ns": 1, "xattrs": {}}
        with mock.patch.object(repository, "selected_paths", return_value=dict(self.fake.selection)), \
                mock.patch.object(repository, "root_metadata", return_value=attributes):
            return self.adapter.backup(backup_id, self.base / "unused", lineage)

    def commit(self, backup_id="backup-1", lineage="system"):
        receipt = self.candidate(backup_id, lineage)
        controls = self.base / ("controls-" + backup_id)
        controls.mkdir(mode=0o700)
        (controls / "manifest.json").write_text(json.dumps({"backup_id": backup_id, "status": "complete"}))
        (controls / "rsync-excludes.txt").write_text("/proc/***\n")
        (controls / "source-selection.json").write_text('{"volumes": []}')
        (controls / "backup-validation.json").write_text('{"status":"ok"}')
        candidate_path = self.adapter.state / ("candidate-" + backup_id + ".json")
        return self.adapter.commit(backup_id, candidate_path, controls)

    def test_initialization_requires_confirmed_recovery_key(self):
        self.assertFalse(self.adapter.status()["key_confirmed"])
        with self.assertRaisesRegex(repository.RepositoryError, "Wiederherstellungsschluessel"):
            self.candidate()
        self.enable()
        self.assertTrue(self.adapter.status()["key_confirmed"])

    def test_key_export_is_private_and_not_in_status(self):
        result = self.adapter.export_key(self.base / "key.json")
        bundle = json.loads((self.base / "key.json").read_bytes())
        self.assertNotIn(bundle["password"], json.dumps(self.adapter.status()))
        self.assertNotIn(bundle["password"], json.dumps(result))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.base / "key.json").stat().st_mode), 0o600)
        with self.assertRaises(repository.RepositoryError):
            self.adapter.confirm_key("0" * 64)

    def test_does_not_overwrite_existing_recovery_key(self):
        self.adapter.export_key(self.base / "key.json")
        with self.assertRaises(repository.RepositoryError):
            self.adapter.export_key(self.base / "key.json")

    def test_recovery_attachment_checks_repository_and_preserves_host(self):
        self.adapter.export_key(self.base / "key.json")
        second_state = self.base / "new-state"
        second_state.mkdir(mode=0o700)
        new = repository.Repository(self.target, second_state, engine="/trusted/restic", runner=self.fake,
                                    identity_reader=lambda path: dict(MOUNT))
        new.attach(self.base / "key.json")
        self.assertEqual(new.status()["host_id"], self.adapter.status()["host_id"])
        self.assertTrue(new.status()["key_confirmed"])

    def test_mount_replacement_is_not_local_fallback(self):
        self.adapter.identity_reader = lambda path: {**MOUNT, "source": "/dev/root", "fstype": "ext4"}
        with self.assertRaisesRegex(repository.RepositoryError, "Mount"):
            self.adapter.status()
        self.assertEqual(sum("init" in call[0] for call in self.fake.calls), 1)

    def test_target_marker_replacement_is_rejected(self):
        (self.target / repository.MARKER).write_text("different")
        with self.assertRaises(repository.RepositoryError):
            self.adapter.status()

    def test_wrong_engine_version_is_rejected(self):
        self.adapter.version_checked = False
        self.fake.version = "0.18.0"
        with self.assertRaisesRegex(repository.RepositoryError, "Version"):
            self.adapter.status()

    def test_engine_environment_ignores_user_injection(self):
        with mock.patch.dict(os.environ, {"RESTIC_PASSWORD": "secret", "RESTIC_PASSWORD_COMMAND": "evil",
                                         "LD_PRELOAD": "evil", "GODEBUG": "evil"}):
            environment = repository.clean_environment()
        self.assertNotIn("RESTIC_PASSWORD", environment)
        self.assertNotIn("RESTIC_PASSWORD_COMMAND", environment)
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertEqual(environment["GODEBUG"], "asyncpreemptoff=1")

    def test_engine_pipes_are_drained_and_bounded(self):
        code, output, error = self.adapter._subprocess([sys.executable, "-c",
            "import sys; sys.stdout.write('a'*200000); sys.stderr.write('b'*200000)"])
        self.assertEqual(code, 0)
        self.assertEqual(len(output), 200000)
        self.assertEqual(len(error), 65536)
        with mock.patch.object(repository, "MAX_LIST", 4096):
            with self.assertRaisesRegex(repository.RepositoryError, "Limit"):
                self.adapter._subprocess([sys.executable, "-c", "import sys; sys.stdout.write('a'*200000)"])

    def test_exit_three_candidate_never_becomes_complete(self):
        self.enable()
        self.fake.backup_code = 3
        with self.assertRaisesRegex(repository.RepositoryError, "Exit 3"):
            self.candidate()
        self.assertEqual(self.adapter.list_committed(), [])
        self.assertFalse((self.adapter.state / "candidate-backup-1.json").exists())

    def test_exit_zero_with_metadata_warning_is_not_published(self):
        self.enable()
        runner = self.adapter.runner
        def warning(argv, stdin=None):
            code, output, error = runner(argv, stdin)
            return (code, output, b"xattr unreadable: permission denied; password=must-hide") if "--files-from-raw" in argv else (code, output, error)
        self.adapter.runner = warning
        with self.assertRaisesRegex(repository.RepositoryError, "Warnungen") as error:
            self.candidate()
        self.assertNotIn("must-hide", str(error.exception))
        self.assertIn("permission denied", str(error.exception))
        self.assertEqual(self.adapter.list_committed(), [])

    def test_candidate_is_invisible_until_commit(self):
        self.enable()
        result = self.candidate()
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(self.adapter.list_committed(), [])
        argv = next(call[0] for call in self.fake.calls if "--files-from-raw" in call[0])
        self.assertEqual(argv[argv.index("--exclude") + 1], "**")
        self.assertIn("--force", argv)

    def test_recursive_scope_expansion_fails_receipt(self):
        self.enable()
        selected = {"/source": "dir", "/source/allowed": "file"}
        self.fake.selection["/source/forbidden-nas/file"] = "file"
        with mock.patch.object(repository, "selected_paths", return_value=selected), \
                mock.patch.object(repository, "root_metadata", return_value={}):
            with self.assertRaisesRegex(repository.RepositoryError, "Quellenauswahl"):
                self.adapter.backup("backup-1", "unused", "system")
        self.assertEqual(self.adapter.list_committed(), [])

    def test_manifest_and_candidate_ids_must_agree(self):
        self.enable()
        self.candidate()
        folder = self.base / "controls"
        folder.mkdir(mode=0o700)
        (folder / "manifest.json").write_text('{"backup_id":"other"}')
        (folder / "rsync-excludes.txt").write_text("")
        (folder / "source-selection.json").write_text("{}")
        (folder / "backup-validation.json").write_text('{"status":"ok"}')
        with self.assertRaisesRegex(repository.RepositoryError, "Manifest"):
            self.adapter.commit("backup-1", self.adapter.state / "candidate-backup-1.json", folder)

    def test_commit_is_auth_bound_and_parent_is_explicit(self):
        self.enable()
        first = self.commit()
        listed = self.adapter.list_committed()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["data_snapshot_id"], first["data_snapshot_id"])
        self.assertEqual(listed[0]["commit_snapshot_id"], first["commit_id"])
        self.candidate("backup-2")
        argv = [call[0] for call in self.fake.calls if "--files-from-raw" in call[0]][-1]
        self.assertEqual(argv[argv.index("--parent") + 1], first["data_snapshot_id"])
        self.candidate("other-line", "different-sources")
        argv = [call[0] for call in self.fake.calls if "--files-from-raw" in call[0]][-1]
        self.assertNotIn("--parent", argv)

    def test_corrupt_control_data_binding_is_rejected(self):
        self.enable()
        first = self.commit()
        data = json.loads(self.fake.contents[first["commit_id"]])
        data["data_snapshot_id"] = "f" * 64
        self.fake.contents[first["commit_id"]] = json.dumps(data).encode()
        with self.assertRaisesRegex(repository.RepositoryError, "Daten-Snapshot"):
            self.adapter.list_committed()

    def test_delete_unpublishes_before_data_and_does_not_prune(self):
        self.enable()
        first = self.commit()
        self.adapter.forget(first["commit_id"])
        ids = [call[0][-1] for call in self.fake.calls if "forget" in call[0]]
        self.assertEqual(ids, [first["commit_id"], first["data_snapshot_id"]])
        self.assertFalse(any("prune" in call[0] for call in self.fake.calls))

    def test_prune_defaults_to_preview_with_checks_and_no_repacking(self):
        self.enable()
        candidate = self.candidate()
        self.fake.calls.clear()
        result = self.adapter.prune()
        commands = [call[0][call[0].index("--json") + 1:] for call in self.fake.calls]
        relevant = [command for command in commands if command[0] in ("check", "prune")]
        self.assertEqual(relevant, [["check"], ["prune", "--max-repack-size", "0", "--dry-run"], ["check"]])
        self.assertEqual(result["status"], "preview")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["snapshots_forgotten"])
        self.assertFalse(result["candidates_removed"])
        self.assertTrue(any(row["id"] == candidate["data_snapshot_id"] for row in self.fake.rows))
        self.assertFalse(any(command[0] in ("forget", "unlock") for command in commands))

    def test_prune_execution_requires_matching_full_id_and_confirmed_key(self):
        for value in (None, "f" * 64, "latest", "abcdef", "A" * 64):
            with self.subTest(repository_id=value):
                self.fake.calls.clear()
                with self.assertRaises(repository.RepositoryError):
                    self.adapter.prune(dry_run=False, confirm_repository_id=value)
                self.assertFalse(any("prune" in call[0] for call in self.fake.calls))
        with self.assertRaisesRegex(repository.RepositoryError, "Wiederherstellungsschluessel"):
            self.adapter.prune(dry_run=False, confirm_repository_id=SID)
        self.assertFalse(any("prune" in call[0] for call in self.fake.calls))
        self.enable()
        self.fake.calls.clear()
        result = self.adapter.prune(dry_run=False, confirm_repository_id=SID)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["repository_id"], SID)
        commands = [call[0][call[0].index("--json") + 1:] for call in self.fake.calls]
        self.assertEqual([command for command in commands if command[0] in ("check", "prune")],
                         [["check"], ["prune", "--max-repack-size", "0"], ["check"]])
        self.assertFalse(any(command[0] in ("forget", "unlock") for command in commands))

    def test_prune_failed_precheck_prevents_any_cleanup(self):
        self.enable()
        self.fake.calls.clear()
        with mock.patch.object(self.adapter, "check", side_effect=repository.RepositoryError("damaged repository")):
            with self.assertRaisesRegex(repository.RepositoryError, "damaged"):
                self.adapter.prune(dry_run=False, confirm_repository_id=SID)
        self.assertFalse(any("prune" in call[0] for call in self.fake.calls))

    def test_prune_summary_is_bounded_and_does_not_return_secrets(self):
        original = self.adapter.run

        def run(arguments, **kwargs):
            if arguments[0] == "prune":
                return 0, (b"x" * 6000 + b"\npassword=do-not-disclose\n"), b""
            return original(arguments, **kwargs)

        with mock.patch.object(self.adapter, "run", side_effect=run):
            result = self.adapter.prune()
        self.assertLessEqual(len(result["summary"]), 2000)
        self.assertNotIn("do-not-disclose", json.dumps(result))
        self.assertIn("<redacted>", result["summary"])

    def test_prune_cli_only_executes_with_explicit_repository_confirmation(self):
        for confirmation in (None, SID):
            with self.subTest(confirmation=confirmation):
                adapter = mock.Mock()
                adapter.prune.return_value = {"status": "preview" if confirmation is None else "ok"}
                arguments = ["hostbackup-repository.py", "--backup-root", str(self.target),
                             "--state-dir", str(self.state), "prune"]
                if confirmation is not None:
                    arguments += ["--confirm-repository-id", confirmation]
                with mock.patch.object(repository.sys, "argv", arguments), \
                        mock.patch.object(repository.os, "name", "posix"), \
                        mock.patch.object(repository.os, "geteuid", return_value=0, create=True), \
                        mock.patch.object(repository, "Repository", return_value=adapter), \
                        mock.patch.object(repository.sys, "stdout", io.StringIO()):
                    repository.main()
                adapter.prune.assert_called_once_with(dry_run=confirmation is None,
                                                      confirm_repository_id=confirmation)

    def test_prune_failed_postcheck_is_not_reported_as_success(self):
        self.enable()
        self.fake.calls.clear()
        with mock.patch.object(self.adapter, "check", side_effect=[{}, repository.RepositoryError("postcheck failed")]):
            with self.assertRaisesRegex(repository.RepositoryError, "postcheck failed"):
                self.adapter.prune(dry_run=False, confirm_repository_id=SID)
        self.assertEqual(sum("prune" in call[0] for call in self.fake.calls), 1)

    def test_snapshot_aliases_and_prefixes_are_never_accepted(self):
        for value in ("latest", "abcdef", "--all", "A" * 64, "0" * 63):
            with self.subTest(value=value), self.assertRaises(repository.RepositoryError):
                repository.snapshot_id(value)

    def test_missing_or_extra_snapshot_paths_and_type_changes_fail(self):
        selected = {"/a": "dir", "/a/file": "file"}
        repository.Repository.inventory_matches(selected, selected)
        for actual in ({"/a": "dir"}, {**selected, "/other": "file"}, {**selected, "/a/file": "symlink"}):
            with self.assertRaises(repository.RepositoryError):
                repository.Repository.inventory_matches(selected, actual)

    def test_staging_requires_empty_separate_linux_storage(self):
        self.enable()
        record = self.commit()
        destination = self.base / "stage"
        destination.mkdir(mode=0o700)
        with self.assertRaisesRegex(repository.RepositoryError, "Linux-Staging"):
            self.adapter.stage(record["commit_id"], destination)
        (destination / "existing").write_text("protect")
        with self.assertRaisesRegex(repository.RepositoryError, "leeres"):
            self.adapter.stage(record["commit_id"], destination)
        self.assertEqual((destination / "existing").read_text(), "protect")

    def test_inventory_rejects_symlink_descendant(self):
        self.fake.nodes[SID] = {"/escape": "symlink", "/escape/file": "file"}
        with self.assertRaisesRegex(repository.RepositoryError, "Nicht-Verzeichnis"):
            self.adapter.inventory(SID)

    def test_selection_is_nul_safe_and_rejects_traversal(self):
        source = self.base / "source"
        source.mkdir()
        file_list = self.base / "files.nul"
        for raw in (b".\0../secret\0", b".\0/absolute\0", b".\0double//slash\0", b".\0.\0", b".\0file"):
            file_list.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(repository.RepositoryError):
                repository.selected_paths(file_list, source)
        (source / "normal").write_text("data")
        file_list.write_bytes(b".\0normal\0")
        self.assertEqual(len(repository.selected_paths(file_list, source)), 2)


class RealLinuxRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = os.environ.get("HOSTBACKUP_RESTIC_BINARY") or shutil.which("restic")
        available = os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0 and self.engine
        if not available:
            if os.environ.get("HOSTBACKUP_REQUIRE_REPOSITORY_INTEGRATION") == "1":
                self.fail("Root Linux with pinned Restic is required for repository integration tests.")
            self.skipTest("Requires root Linux and Restic 0.19.1; no NAS proof from mocked unit tests.")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        os.chmod(self.base, 0o700)
        self.source = self.base / "source"
        self.source.mkdir(mode=0o750)
        self.source.chmod(0o750)  # Explicit fixture mode, independent of caller umask.
        (self.source / "empty").mkdir(mode=0o710)
        (self.source / "allowed").write_text("allowed data")
        (self.source / "secret").write_text("must never be copied")
        os.symlink("allowed", self.source / "link")
        os.link(self.source / "allowed", self.source / "hardlink")
        os.mkfifo(self.source / "pipe", 0o640)
        os.setxattr(self.source, "user.hostbackup-root", b"root-attribute")
        os.setxattr(self.source / "allowed", "user.hostbackup-file", b"file-attribute")
        self.file_list = self.base / "selection.nul"
        self.file_list.write_bytes(b".\0empty\0allowed\0link\0hardlink\0pipe\0")
        self.target = Path(os.environ.get("HOSTBACKUP_REPOSITORY_TEST_TARGET", str(self.base / "target")))
        if self.target.exists():
            # User-specified parent is never reused as the actual repository.
            self.target = Path(tempfile.mkdtemp(prefix="hostbackup-repository-test-", dir=self.target))
            target_identity = (self.target.stat().st_dev, self.target.stat().st_ino)
            def clean_external_fixture():
                self.assertFalse(self.target.is_symlink())
                self.assertEqual((self.target.stat().st_dev, self.target.stat().st_ino), target_identity)
                shutil.rmtree(self.target)
            self.addCleanup(clean_external_fixture)
        else:
            self.target.mkdir(mode=0o700)
        (self.target / repository.MARKER).write_text("isolated-test-target")
        state = self.base / "state"
        state.mkdir(mode=0o700)
        self.adapter = repository.Repository(self.target, state, engine=self.engine)
        self.adapter.initialize()
        key = self.adapter.export_key(self.base / "recovery-key.json")
        self.adapter.confirm_key(key["sha256"])

    def backup_commit(self, name):
        receipt = self.adapter.backup(name, self.file_list, "fixture-v1", self.source)
        controls = self.base / ("controls-" + name)
        controls.mkdir(mode=0o700)
        (controls / "manifest.json").write_text(json.dumps({"backup_id": name, "status": "complete"}))
        (controls / "rsync-excludes.txt").write_text("secret\n")
        (controls / "source-selection.json").write_text('{"volumes": []}')
        (controls / "backup-validation.json").write_text('{"status":"ok"}')
        candidate = self.adapter.state / ("candidate-" + name + ".json")
        return self.adapter.commit(name, candidate, controls)

    def test_real_selection_metadata_incremental_restore_and_retention(self):
        first = self.backup_commit("first")
        self.assertEqual(len(self.adapter.list_committed()), 1)
        self.assertFalse(any(path.endswith("/secret") for path in self.adapter.inventory(first["data_snapshot_id"])))
        second = self.backup_commit("second")
        self.assertEqual(second["summary"].get("files_new"), 0)
        self.assertEqual(second["summary"].get("files_changed"), 0)
        (self.source / "allowed").write_text("changed data")
        third = self.backup_commit("third")
        self.adapter.check(read_data=True)
        destination = self.base / "stage"
        destination.mkdir(mode=0o700)
        # Test fixture may reside on overlayfs; it has real Linux metadata but
        # production staging intentionally uses an explicit filesystem allowlist.
        original = self.adapter.identity_reader
        self.adapter.identity_reader = lambda path: ({"target": str(path), "source": "fixture", "fstype": "ext4"}
                                                       if path == destination else original(path))
        staged = self.adapter.stage(third["commit_id"], destination)
        restored = Path(staged["rootfs"]) / str(self.source).lstrip("/")
        self.assertFalse((restored / "secret").exists())
        self.assertEqual((restored / "allowed").read_text(), "changed data")
        self.assertEqual((restored / "allowed").stat().st_ino, (restored / "hardlink").stat().st_ino)
        self.assertEqual(os.readlink(restored / "link"), "allowed")
        self.assertTrue(stat.S_ISFIFO((restored / "pipe").stat().st_mode))
        self.assertEqual(os.getxattr(restored, "user.hostbackup-root"), b"root-attribute")
        self.assertEqual(os.getxattr(restored / "allowed", "user.hostbackup-file"), b"file-attribute")
        self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o750)
        self.adapter.forget(first["commit_id"])
        preview = self.adapter.prune()
        self.assertTrue(preview["dry_run"])
        self.assertEqual({row["backup_id"] for row in self.adapter.list_committed()}, {"second", "third"})
        self.adapter.prune(dry_run=False, confirm_repository_id=self.adapter.status()["repository_id"])
        self.adapter.check(read_data=True)
        self.assertEqual({row["backup_id"] for row in self.adapter.list_committed()}, {"second", "third"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
