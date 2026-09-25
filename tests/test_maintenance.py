#!/usr/bin/env python3
import datetime as dt
import base64
from contextlib import closing
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("maintenance", ROOT / "bin/hostbackup-maintenance.py")
MAINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAINT)


class FakeRepository:
    def __init__(self):
        self.commits = {}
        self.forgotten = []
        self.checks = []

    def load(self):
        return {"repository_id": "a" * 64}

    def read_commit(self, sid):
        if sid not in self.commits:
            raise ValueError("Repository commit missing")
        return self.commits[sid]

    def check(self, read_data=False):
        self.checks.append(read_data)
        return {"status": "ok"}

    def forget(self, sid):
        self.forgotten.append(sid)
        del self.commits[sid]


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.root, self.state = base / "backup-target", base / "state"
        self.root.mkdir()
        self.state.mkdir(mode=0o700)
        (self.root / ".loxberry-hostbackup-target").write_text("target-marker\n")
        for name in ("logs", "tasks", "import-quarantine", "restart-journals"):
            (self.state / name).mkdir()

    def backup(self, backup_id, when="2026-09-01T12:00:00+00:00", status="complete"):
        directory = self.root / backup_id
        (directory / "rootfs/etc").mkdir(parents=True)
        (directory / "rootfs/opt/loxberry").mkdir(parents=True)
        (directory / "rootfs/etc/hosts").write_text("127.0.0.1 localhost\n")
        (directory / "rootfs/opt/loxberry/data").write_bytes(b"payload" * 1024)
        manifest = {"backup_id": backup_id, "status": status, "finished_at": when}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        (directory / "backup-validation.json").write_text(json.dumps({"status": "ok" if status == "complete" else "error"}))
        (directory / ".loxberry-hostbackup-backup").write_text(backup_id + "\n")
        return directory

    def repository_fixture(self):
        fake = FakeRepository()
        patch = mock.patch.object(MAINT, "repository_adapter", return_value=fake)
        patch.start()
        self.addCleanup(patch.stop)
        shared = self.root / ".portable-repository/data"
        shared.mkdir(parents=True)
        (shared / "shared-pack").write_bytes(b"repository bytes" * 500)
        return fake

    def repository_backup(self, fake, backup_id, when="2026-09-01T12:00:00+00:00", host="host-one"):
        directory = self.backup(backup_id, when)
        shutil.rmtree(directory / "rootfs")
        manifest = json.loads((directory / "manifest.json").read_bytes())
        manifest.update(backup={"storage_format": "portable-repository"}, metadata={"mode": "portable-archive"}, size_bytes=12345)
        (directory / "manifest.json").write_text(json.dumps(manifest))
        (directory / "rsync-excludes.txt").write_text("/proc/***\n")
        (directory / "source-selection.json").write_text('{"volumes": []}')
        sid = MAINT.hashlib.sha256(backup_id.encode()).hexdigest()
        reference = {"format": "hostbackup-restic-v1", "backup_id": backup_id, "commit_id": sid,
                     "data_snapshot_id": MAINT.hashlib.sha256((backup_id + "data").encode()).hexdigest(),
                     "repository_id": "a" * 64}
        (directory / "repository-reference.json").write_text(json.dumps(reference))
        controls = {name: base64.b64encode((directory / name).read_bytes()).decode("ascii")
                    for name in ("manifest.json", "rsync-excludes.txt", "source-selection.json", "backup-validation.json")}
        fake.commits[sid] = {**reference, "host_id": host, "lineage": "system", "controls": controls}
        return directory, reference

    def test_repository_controls_must_match_authenticated_commit(self):
        fake = self.repository_fixture()
        target, reference = self.repository_backup(fake, "repo")
        _, record = MAINT.backup_record(self.root, "repo", self.state)
        self.assertEqual(record["commit_snapshot_id"], reference["commit_id"])
        (target / "rsync-excludes.txt").write_text("different excludes")
        with self.assertRaisesRegex(ValueError, "authenticated repository copy"):
            MAINT.backup_record(self.root, "repo", self.state)
        listed, ignored = MAINT.records(self.root, self.state)
        self.assertFalse(listed)
        self.assertEqual(ignored[0]["name"], "repo")

    def test_repository_storage_counts_shared_chunks_once(self):
        fake = self.repository_fixture()
        self.repository_backup(fake, "one")
        self.repository_backup(fake, "two")
        report = MAINT.storage(self.root, self.state)
        expected_shared = MAINT.tree_storage(self.root / ".portable-repository")["allocated_bytes"]
        self.assertEqual(report["repository_shared_allocated_bytes"], expected_shared)
        self.assertEqual(report["total_unique_allocated_bytes"], expected_shared + sum(row["unique_added_bytes"] for row in report["backups"]))
        self.assertTrue(all(row["logical_bytes"] == 12345 for row in report["backups"]))

    def test_repository_structure_and_content_checks_are_distinct(self):
        fake = self.repository_fixture()
        self.repository_backup(fake, "one")
        structure = MAINT.repository_check(self.root, self.state, "one")
        self.assertFalse(structure["content_verified"])
        recorded = MAINT.integrity(self.root, self.state, "one", record_only=True)
        self.assertEqual(recorded["status"], "structure_verified")
        report = MAINT.integrity(self.root, self.state, "one")
        self.assertTrue(report["content_verified"])
        self.assertFalse(report["restore_tested"])
        self.assertEqual(report["metadata_compared"], [])
        self.assertEqual(fake.checks, [False, False, True])
        self.assertFalse(list((self.state / "integrity").glob("*.sqlite")))

    def test_repository_retention_keeps_last_old_format_and_each_host(self):
        fake = self.repository_fixture()
        self.backup("last-old-format", "2026-09-01T12:00:00+00:00")
        self.repository_backup(fake, "old-repo", "2026-09-02T12:00:00+00:00")
        self.repository_backup(fake, "another-host", "2026-09-03T12:00:00+00:00", host="host-two")
        self.repository_backup(fake, "latest", "2026-09-04T12:00:00+00:00")
        plan = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        self.assertEqual([row["backup_id"] for row in plan["delete"]], ["old-repo"])
        self.assertEqual(set(plan["protected_latest_per_format_host"]), {"last-old-format", "another-host", "latest"})
        for name in ("last-old-format", "another-host", "latest"):
            with self.assertRaisesRegex(ValueError, "geschuetzt"):
                MAINT.delete_check(self.root, self.state, name)

    def test_repository_retention_forgets_exact_commit_not_shared_packs(self):
        fake = self.repository_fixture()
        _, old = self.repository_backup(fake, "old", "2026-09-01T12:00:00+00:00")
        self.repository_backup(fake, "new", "2026-09-02T12:00:00+00:00")
        pack = self.root / ".portable-repository/data/shared-pack"
        before = pack.read_bytes()
        plan = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        result = MAINT.retention(self.root, self.state, {"keep_backups": 1}, apply=plan["preview_digest"])
        self.assertEqual(fake.forgotten, [old["commit_id"]])
        self.assertFalse((self.root / "old").exists())
        self.assertEqual(pack.read_bytes(), before)
        self.assertFalse(result["repository_space_reclaimed"])

    def test_repository_forget_failure_preserves_wrapper_and_exports(self):
        fake = self.repository_fixture()
        self.repository_backup(fake, "old", "2026-09-01T12:00:00+00:00")
        self.repository_backup(fake, "new", "2026-09-02T12:00:00+00:00")
        exported = self.root / "old.tar.gz"
        exported.write_bytes(b"keep export")
        plan = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        with mock.patch.object(fake, "forget", side_effect=ValueError("repository unavailable")):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                MAINT.retention(self.root, self.state, {"keep_backups": 1}, apply=plan["preview_digest"])
        self.assertTrue((self.root / "old").exists())
        self.assertEqual(exported.read_bytes(), b"keep export")

    def test_repository_manual_forget_preserves_wrapper_until_caller_removes_it(self):
        fake = self.repository_fixture()
        target, old = self.repository_backup(fake, "old", "2026-09-01T12:00:00+00:00")
        self.repository_backup(fake, "new", "2026-09-02T12:00:00+00:00")
        result = MAINT.repository_forget(self.root, self.state, "old")
        self.assertEqual(fake.forgotten, [old["commit_id"]])
        self.assertTrue(target.is_dir())
        self.assertFalse(result["wrapper_removed"])

    def test_storage_deduplicates_shared_snapshot_allocation(self):
        first, second = self.backup("one"), self.backup("two")
        shared = second / "rootfs/opt/loxberry/data"
        shared.unlink()
        os.link(first / "rootfs/opt/loxberry/data", shared)
        report = MAINT.storage(self.root, self.state)
        per_backup = sum(item["allocated_bytes"] for item in report["backups"])
        self.assertLess(report["backups_unique_allocated_bytes"], per_backup)
        self.assertTrue(all(item["shared_file_count"] for item in report["backups"]))

    def test_storage_reports_local_logs_quarantine_and_integrity_budget(self):
        self.backup("one")
        (self.state / "logs/task.log").write_bytes(b"log" * 4096)
        (self.state / "import-quarantine/failed.tar").write_bytes(b"archive" * 4096)
        MAINT.integrity(self.root, self.state, "one")
        report = MAINT.storage(self.root, self.state)["root_state"]
        for field in ("logs_bytes", "quarantine_bytes", "integrity_bytes"):
            self.assertGreater(report[field], 0)
        self.assertGreaterEqual(report["total_bytes"], sum(report[field] for field in (
            "logs_bytes", "quarantine_bytes", "integrity_bytes")))
        self.assertEqual(report["measurement"], "allocated_blocks")
        self.assertGreater(report["free_bytes"], 0)

    def test_integrity_first_records_then_verifies_and_detects_changed_content(self):
        directory = self.backup("one")
        first = MAINT.integrity(self.root, self.state, "one")
        self.assertEqual(first["status"], "baseline_created")
        self.assertFalse(first["content_verified"])
        second = MAINT.integrity(self.root, self.state, "one")
        self.assertEqual(second["status"], "verified")
        self.assertTrue(second["content_verified"])
        self.assertFalse(second["restore_tested"])
        (directory / "rootfs/etc/hosts").write_text("different contents\n")
        third = MAINT.integrity(self.root, self.state, "one")
        self.assertEqual(third["status"], "changed")
        self.assertEqual(third["changes"], [{"path": "etc/hosts", "change": "changed"}])
        self.assertFalse(third["content_verified"])

    def test_integrity_detects_missing_and_added_files(self):
        directory = self.backup("one")
        MAINT.integrity(self.root, self.state, "one")
        (directory / "rootfs/etc/hosts").unlink()
        (directory / "rootfs/etc/new").write_text("new")
        report = MAINT.integrity(self.root, self.state, "one")
        self.assertIn({"path": "etc/hosts", "change": "missing"}, report["changes"])
        self.assertIn({"path": "etc/new", "change": "added"}, report["changes"])

    def test_existing_baseline_is_never_silently_replaced(self):
        directory = self.backup("one")
        MAINT.integrity(self.root, self.state, "one")
        baseline = next((self.state / "integrity").glob("*.baseline.sqlite"))
        original = baseline.read_bytes()
        self.assertEqual(MAINT.integrity(self.root, self.state, "one", record_only=True)["status"], "baseline_exists")
        (directory / "manifest.json").write_text(json.dumps({"backup_id": "one", "status": "complete", "finished_at": "changed"}))
        with self.assertRaisesRegex(ValueError, "identity/manifest mismatch"):
            MAINT.integrity(self.root, self.state, "one")
        self.assertEqual(baseline.read_bytes(), original)
        self.assertEqual(MAINT.integrity(self.root, self.state, "one", report_only=True)["status"], "stale")

    def test_integrity_baseline_is_indexed_not_large_in_memory_json(self):
        self.backup("one")
        MAINT.integrity(self.root, self.state, "one")
        baseline = next((self.state / "integrity").glob("*.baseline.sqlite"))
        with closing(sqlite3.connect(baseline)) as database:
            self.assertGreater(database.execute("SELECT count(*) FROM entries").fetchone()[0], 1)
        self.assertFalse(list((self.state / "integrity").glob(".integrity-scan-*")))

    def test_manual_restore_history_is_not_a_content_or_eligibility_proof(self):
        directory = self.backup("one")
        manifest_before = (directory / "manifest.json").read_bytes()
        validation_before = (directory / "backup-validation.json").read_bytes()
        result = MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T12:00:00+01:00", "Offline test host")
        self.assertTrue(result["restore_tested"])
        self.assertEqual(result["restore_test_evidence"], "manual-user-report")
        self.assertEqual(result["restore_test"]["tested_at"], "2020-01-01T11:00:00+00:00")
        self.assertEqual(result["restore_test"]["source"], "manual-user-report")
        report = MAINT.integrity(self.root, self.state, "one", report_only=True)
        self.assertEqual(report["status"], "not_checked")
        self.assertFalse(report["content_verified"])
        self.assertTrue(report["restore_tested"])
        self.assertEqual((directory / "manifest.json").read_bytes(), manifest_before)
        self.assertEqual((directory / "backup-validation.json").read_bytes(), validation_before)

    def test_manual_restore_history_latest_test_decides_and_is_bounded(self):
        self.backup("one")
        start = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        for number in range(22):
            result = MAINT.record_restore_test(self.root, self.state, "one", "passed" if number < 21 else "failed",
                                              (start + dt.timedelta(days=number)).isoformat(), f"test {number}")
        self.assertEqual(len(result["restore_test_history"]), 20)
        self.assertFalse(result["restore_tested"])
        self.assertEqual(result["restore_test"]["note"], "test 21")
        # Recording an older successful test must not replace a later failure.
        older = MAINT.record_restore_test(self.root, self.state, "one", "passed", start.isoformat(), "old success")
        self.assertFalse(older["restore_tested"])
        self.assertEqual(older["restore_test"]["note"], "test 21")
        self.assertEqual(len(older["restore_test_history"]), 20)

    def test_manual_restore_history_rejects_future_naive_and_oversized_inputs(self):
        self.backup("one")
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        for result, when, note, pattern in (
                ("passed", future, "", "future"),
                ("passed", "2020-01-01T12:00:00", "", "timezone"),
                ("passed", "not a date", "", "Invalid restore test time"),
                ("passed", "2020-01-01T00:00:00Z", "x" * 2001, "2000"),
                ("unknown", "2020-01-01T00:00:00Z", "", "passed or failed")):
            with self.subTest(result=result, pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                MAINT.record_restore_test(self.root, self.state, "one", result, when, note)
        self.assertFalse(list((self.state / "integrity").glob("*.restore-tests.json")))

    def test_manual_restore_history_sanitizes_note_controls(self):
        self.backup("one")
        result = MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T00:00:00Z", "A\x00B\nC\x7fD\u202eE")
        self.assertEqual(result["restore_test"]["note"], "A B C D E")

    def test_manual_restore_history_cannot_claim_a_changed_manifest_was_tested(self):
        directory = self.backup("one")
        MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T00:00:00Z", "original")
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["finished_at"] = "changed"
        (directory / "manifest.json").write_text(json.dumps(manifest))
        report = MAINT.integrity(self.root, self.state, "one", report_only=True)
        self.assertFalse(report["restore_tested"])
        self.assertFalse(report["restore_test"]["applies_to_current_manifest"])
        self.assertEqual(report["restore_test"]["note"], "original")

    def test_manual_restore_history_rejects_hardlink_without_changing_other_file(self):
        self.backup("one")
        MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T00:00:00Z", "original")
        history = next((self.state / "integrity").glob("*.restore-tests.json"))
        other = self.state / "sentinel.json"
        os.link(history, other)
        original = other.read_bytes()
        with self.assertRaisesRegex(ValueError, "hardlink"):
            MAINT.record_restore_test(self.root, self.state, "one", "failed", "2020-01-02T00:00:00Z", "changed")
        self.assertEqual(other.read_bytes(), original)

    @unittest.skipUnless(os.name == "posix", "requires Linux symlink safety semantics")
    def test_manual_restore_history_rejects_symlink_without_following_it(self):
        self.backup("one")
        MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T00:00:00Z", "original")
        history = next((self.state / "integrity").glob("*.restore-tests.json"))
        other = self.state / "sentinel.json"
        other.write_bytes(history.read_bytes())
        original = other.read_bytes()
        history.unlink()
        history.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "regular file"):
            MAINT.record_restore_test(self.root, self.state, "one", "failed", "2020-01-02T00:00:00Z", "changed")
        self.assertEqual(other.read_bytes(), original)

    def test_manual_restore_history_is_local_and_not_automatically_in_diagnostics(self):
        directory = self.backup("one")
        (directory / "restore-tests.json").write_text(json.dumps({"restore_tested": True}))
        self.assertFalse(MAINT.integrity(self.root, self.state, "one", report_only=True)["restore_tested"])
        MAINT.record_restore_test(self.root, self.state, "one", "passed", "2020-01-01T00:00:00Z", "PRIVATE-RESTORE-NOTE")
        output = io.BytesIO()
        MAINT.diagnostics(self.root, self.state, {}, "unknown", output=output)
        _, data = output.getvalue().split(b"\r\n\r\n", 1)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                self.assertNotIn(b"PRIVATE-RESTORE-NOTE", archive.read(name))

    def test_forget_integrity_removes_only_matching_manual_history(self):
        directory = self.backup("one")
        self.backup("two")
        for backup_id in ("one", "two"):
            MAINT.record_restore_test(self.root, self.state, backup_id, "passed", "2020-01-01T00:00:00Z", "manual")
        shutil.rmtree(directory)
        result = MAINT.forget_integrity(self.root, self.state, "one", "one")
        self.assertEqual(len(result["removed"]), 1)
        self.assertTrue(result["removed"][0].endswith(".restore-tests.json"))
        self.assertTrue(MAINT.integrity(self.root, self.state, "two", report_only=True)["restore_tested"])

    def test_manual_restore_history_real_cli_record_and_report(self):
        self.backup("one")
        command = [sys.executable, str(ROOT / "bin/hostbackup-maintenance.py")]
        recorded = subprocess.run(command + ["record-restore-test", str(self.root), "one", "--state", str(self.state),
                                  "--result", "passed", "--tested-at", "2020-01-01T00:00:00Z", "--note", "CLI test"],
                                  capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(recorded.stdout)["restore_tested"])
        report = subprocess.run(command + ["integrity", str(self.root), "one", "--state", str(self.state), "--report"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(report.stdout)["restore_test"]["note"], "CLI test")

    def test_retention_preserves_latest_and_explicitly_protected_backups(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("middle", "2026-08-15T00:00:00+00:00")
        self.backup("latest", "2026-09-01T00:00:00+00:00")
        MAINT.protect(self.root, self.state, "old", True)
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        self.assertEqual([item["backup_id"] for item in preview["delete"]], ["middle"])
        self.assertEqual(preview["protected_latest"], "latest")
        result = MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertTrue(result["applied"])
        self.assertTrue((self.root / "old").is_dir())
        self.assertTrue((self.root / "latest").is_dir())
        self.assertFalse((self.root / "middle").exists())

    def test_changed_pin_invalidates_deletion_preview(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        MAINT.protect(self.root, self.state, "old", True)
        with self.assertRaisesRegex(ValueError, "preview is stale"):
            MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertTrue((self.root / "old").is_dir())

    def test_manual_delete_check_preserves_latest_good_and_pin(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        self.backup("failed-newer", "2026-09-13T00:00:00+00:00", status="failed")
        with self.assertRaisesRegex(ValueError, "juengste brauchbare"):
            MAINT.delete_check(self.root, self.state, "latest")
        MAINT.protect(self.root, self.state, "old", True)
        with self.assertRaisesRegex(ValueError, "geschuetzt"):
            MAINT.delete_check(self.root, self.state, "old")
        MAINT.protect(self.root, self.state, "old", False)
        self.assertTrue(MAINT.delete_check(self.root, self.state, "old")["allowed"])
        self.assertTrue(MAINT.delete_check(self.root, self.state, "failed-newer")["allowed"])

    def test_retention_removes_only_deleted_backup_integrity_state(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        for backup_id in ("old", "latest"):
            MAINT.integrity(self.root, self.state, backup_id)
        old_paths = MAINT.integrity_paths(self.root, self.state, "old")[-2:]
        latest_paths = MAINT.integrity_paths(self.root, self.state, "latest")[-2:]
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        result = MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertEqual(result["cleanup_warnings"], [])
        self.assertTrue(all(not path.exists() for path in old_paths))
        self.assertTrue(all(path.is_file() for path in latest_paths))

    def test_forget_integrity_refuses_existing_backup_and_wrong_marker(self):
        directory = self.backup("one")
        MAINT.integrity(self.root, self.state, "one")
        paths = MAINT.integrity_paths(self.root, self.state, "one")[-2:]
        with self.assertRaisesRegex(ValueError, "still exists"):
            MAINT.forget_integrity(self.root, self.state, "one", "one")
        with self.assertRaisesRegex(ValueError, "marker"):
            MAINT.forget_integrity(self.root, self.state, "one", "other")
        shutil.rmtree(directory)
        result = MAINT.forget_integrity(self.root, self.state, "one", "one")
        self.assertEqual(len(result["removed"]), 2)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_forget_integrity_checks_stored_identity_before_any_unlink(self):
        directory = self.backup("one")
        MAINT.integrity(self.root, self.state, "one")
        baseline, report = MAINT.integrity_paths(self.root, self.state, "one")[-2:]
        with closing(sqlite3.connect(baseline)) as database:
            database.execute("UPDATE metadata SET value=? WHERE name='identity'", ('{"identity": {"backup_id": "other"}}',))
            database.commit()
        shutil.rmtree(directory)
        with self.assertRaisesRegex(ValueError, "different backup identity"):
            MAINT.forget_integrity(self.root, self.state, "one", "one")
        self.assertTrue(baseline.is_file())
        self.assertTrue(report.is_file())

    def test_retention_reports_index_cleanup_error_after_actual_deletion(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        MAINT.integrity(self.root, self.state, "old")
        baseline = MAINT.integrity_paths(self.root, self.state, "old")[-2]
        baseline.write_bytes(b"invalid sqlite fixture")
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        result = MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertTrue(result["applied"])
        self.assertFalse((self.root / "old").exists())
        self.assertTrue(baseline.exists())
        self.assertEqual(result["cleanup_warnings"][0]["backup_id"], "old")

    def test_gfs_keeps_distinct_day_week_month_representatives(self):
        for number, when in enumerate(("2026-07-01", "2026-08-01", "2026-08-26", "2026-09-01", "2026-09-02")):
            self.backup(f"backup-{number}", when + "T12:00:00+00:00")
        preview = MAINT.retention(self.root, self.state, {"retention_mode": "gfs", "keep_daily": 1,
                                                        "keep_weekly": 2, "keep_monthly": 2})
        kept = {item["backup_id"] for item in preview["keep"]}
        self.assertIn("backup-4", kept)
        self.assertIn("backup-2", kept)
        self.assertNotIn("backup-0", kept)

    def test_gfs_allows_disabled_buckets_and_matches_configuration_bounds(self):
        self.backup("latest")
        report = MAINT.retention(self.root, self.state,
                                 {"retention_mode": "gfs", "keep_daily": 0,
                                  "keep_weekly": 520, "keep_monthly": 0})
        self.assertEqual(report["policy"]["weekly"], 520)
        with self.assertRaisesRegex(ValueError, "At least one GFS"):
            MAINT.policy({"retention_mode": "gfs", "keep_daily": 0, "keep_weekly": 0, "keep_monthly": 0})

    def test_incomplete_backups_not_deleted_without_explicit_review(self):
        self.backup("partial", status="failed")
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        self.assertEqual(preview["delete"], [])
        self.assertIn("incomplete-backup-review-required", preview["keep"][0]["reasons"])

    def test_pending_task_blocks_retention_and_log_cleanup(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        task = {"task": "backup-live.log", "state": "queued", "pid": 0, "updated_at": time.time()}
        (self.state / "tasks/backup-live.log.json").write_text(json.dumps(task))
        path = self.state / "logs/backup-live.log"
        path.write_text("live")
        os.utime(path, (0, 0))
        self.assertEqual(MAINT.retention(self.root, self.state, {"keep_backups": 1})["delete"], [])
        self.assertEqual(MAINT.cleanup_runtime(self.state, {})["files"], [])

    def test_retention_deletes_only_bound_associated_exports(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        for suffix in (".tar.gz", ".tar.gz.sha256", ".tar.gz.json"):
            (self.root / ("old" + suffix)).write_bytes(b"export-fixture")
        unrelated = self.root / "unrelated.tar.gz"
        unrelated.write_bytes(b"keep")
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        self.assertEqual(len(preview["delete"][0]["exports"]), 3)
        MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertFalse((self.root / "old.tar.gz").exists())
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_changed_export_invalidates_deletion_preview(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        path = self.root / "old.tar.gz"
        path.write_bytes(b"initial")
        preview = MAINT.retention(self.root, self.state, {"keep_backups": 1})
        path.write_bytes(b"changed after preview")
        with self.assertRaisesRegex(ValueError, "preview is stale"):
            MAINT.retention(self.root, self.state, {"keep_backups": 1}, preview["preview_digest"])
        self.assertTrue((self.root / "old").is_dir())

    def test_integrity_due_reads_reports_without_hashing_payload(self):
        self.backup("one")
        self.assertEqual(MAINT.integrity_due(self.root, self.state, {})["backup_ids"], [])
        self.assertEqual(MAINT.integrity_due(self.root, self.state, {"integrity_enabled": True})["backup_ids"], ["one"])
        MAINT.integrity(self.root, self.state, "one")
        self.assertEqual(MAINT.integrity_due(self.root, self.state, {"integrity_enabled": True})["backup_ids"], [])

    def test_failed_integrity_attempt_does_not_starve_other_due_backups(self):
        self.backup("first")
        self.backup("second")
        task = {"task": "verify-first-123-456.log", "state": "failed", "updated_at": time.time()}
        (self.state / "tasks/verify-first-123-456.log.json").write_text(json.dumps(task))
        self.assertEqual(MAINT.integrity_due(self.root, self.state, {"integrity_enabled": True})["backup_ids"], ["second", "first"])

    def test_scheduled_integrity_waits_for_existing_queued_check(self):
        self.backup("one")
        task = {"task": "verify-one-123-456.log", "state": "queued", "pid": 0, "updated_at": time.time()}
        (self.state / "tasks/verify-one-123-456.log.json").write_text(json.dumps(task))
        report = MAINT.integrity_due(self.root, self.state, {"integrity_enabled": True})
        self.assertEqual(report["backup_ids"], [])
        self.assertEqual(report["active_verifications"], ["verify-one-123-456.log"])

    @unittest.skipUnless(os.name == "posix" and pathlib.Path("/proc/self/stat").exists(), "requires Linux process identities")
    def test_caller_pid_ignores_only_the_identified_current_task(self):
        self.backup("old", "2026-08-01T00:00:00+00:00")
        self.backup("latest")
        ticks = pathlib.Path("/proc/self/stat").read_text().rpartition(")")[2].split()[19]
        task = {"task": "backup-self.log", "state": "running", "pid": os.getpid(), "process_start_ticks": ticks}
        (self.state / "tasks/backup-self.log.json").write_text(json.dumps(task))
        self.assertEqual(MAINT.retention(self.root, self.state, {"keep_backups": 1})["delete"], [])
        self.assertEqual(len(MAINT.retention(self.root, self.state, {"keep_backups": 1}, caller_pid=os.getpid())["delete"]), 1)

    def test_runtime_cleanup_is_bounded_and_preserves_restart_journals(self):
        log = self.state / "logs/old.log"
        log.write_text("old log")
        os.utime(log, (0, 0))
        journal = self.state / "restart-journals/restart.json"
        journal.write_text("must survive")
        os.utime(journal, (0, 0))
        preview = MAINT.cleanup_runtime(self.state, {})
        self.assertEqual([item["name"] for item in preview["files"]], ["old.log"])
        MAINT.cleanup_runtime(self.state, {}, preview["preview_digest"])
        self.assertFalse(log.exists())
        self.assertEqual(journal.read_text(), "must survive")

    def test_diagnostics_has_full_selected_log_and_redacted_settings(self):
        log = "sensitive original line\nsecond line\n"
        (self.state / "logs/backup-one.log").write_bytes(log.encode())
        output = io.BytesIO()
        config = {"metadata_mode": "network-compatible", "mail_notify_to": "private@example.com",
                  "backup_root": "/secret/path", "pre_backup_hook": "secret hook", "stop_targets": ["private-service"]}
        MAINT.diagnostics(self.root, self.state, config, "0.6.1", "backup-one.log", output)
        headers, data = output.getvalue().split(b"\r\n\r\n", 1)
        self.assertIn(b"Content-Type: application/zip", headers)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.read("selected-task.log").decode(), log)
            report_text = archive.read("diagnostics.json").decode()
            self.assertNotIn("private@example.com", report_text)
            self.assertNotIn("/secret/path", report_text)
            self.assertNotIn("secret hook", report_text)
            self.assertIn("network-compatible", report_text)
        with self.assertRaisesRegex(ValueError, "identifier"):
            MAINT.diagnostics(self.root, self.state, config, "test", "../../secret", io.BytesIO())

    def test_diagnostics_works_without_configured_backup_target(self):
        output = io.BytesIO()
        MAINT.diagnostics(None, self.state, {}, "unknown", output=output)
        _, data = output.getvalue().split(b"\r\n\r\n", 1)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            report = json.loads(archive.read("diagnostics.json"))
        self.assertFalse(report["target_configured"])
        self.assertFalse(report["target_available"])


if __name__ == "__main__":
    unittest.main()
