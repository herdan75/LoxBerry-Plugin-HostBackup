"""Saved content-report retrieval: read-only, explicit and never false-green."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest import mock

import test_maintenance as fixture
from test_runtime_safety import BASH, ROOT, function


MAINT = fixture.MAINT


class VerificationReportTests(unittest.TestCase):
    setUp = fixture.MaintenanceTests.setUp
    backup = fixture.MaintenanceTests.backup

    def warning_backup(self):
        target = self.backup("warning", status="complete_with_warnings")
        (target / "backup-validation.json").write_text(json.dumps({"status": "warning", "checks": [
            {"name": "Plausibility warning", "ok": False}]}))
        return target

    def report_path(self, backup_id="warning"):
        return MAINT.integrity_paths(self.root, self.state, backup_id)[-1]

    def real_cli(self, backup_id="warning"):
        command = [sys.executable, "-B", str(Path(MAINT.__file__)), "integrity", str(self.root), backup_id,
                   "--state", str(self.state), "--report"]
        return subprocess.run(command, capture_output=True, text=True, timeout=20)

    def cgi_report(self, busy=False):
        """Real shell report action + real helper -> full CGI GET JSON route.

        Only deployment path/lock wrappers are inert fixtures. CGI subprocess
        interception supplies the exact backend exit/output and refuses every
        unexpected command, so neither sudo nor production paths can run.
        """
        if not BASH or not Path(BASH).exists():
            self.skipTest("Bash/Perl required for full CGI contract")
        config = self.state / "config.json"
        config.write_text("{}")
        backend_program = r'''
set -euo pipefail
backup_root() { printf '%s\n' "$TEST_REPORT_ROOT"; }
verify_backup_target() { :; }
require_backup_id() { [ "$1" = warning ]; }
require_root_for_write() { return 99; }
acquire_operation_lock() {
  [ "$1" = shared ] || return 99
  if [ "$TEST_REPORT_BUSY" = 1 ]; then echo 'Another HostBackup operation is active.' >&2; return 5; fi
}
acquire_backup_lock() { [ "$1:$2" = warning:shared ]; }
safe_backup_target() { printf '%s/%s\n' "$1" "$2"; }
python3() { "$TEST_REPORT_PYTHON" "$@"; }
LBP_BINDIR="$TEST_REPORT_BINDIR"
ROOT_STATE_DIR="$TEST_REPORT_STATE"
CONFIG_FILE="$TEST_REPORT_CONFIG"
'''
        backend_program += function("maintenance_helper") + function("maintenance_action")
        backend_program += "\nmaintenance_action report warning\n"
        env = {**os.environ, "TEST_REPORT_ROOT": self.root.as_posix(),
               "TEST_REPORT_STATE": self.state.as_posix(), "TEST_REPORT_CONFIG": config.as_posix(),
               "TEST_REPORT_BINDIR": (ROOT / "bin").as_posix(), "TEST_REPORT_PYTHON": Path(sys.executable).as_posix(),
               "TEST_REPORT_BUSY": "1" if busy else "0"}
        backend = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT,
                                 input=backend_program, text=True, capture_output=True, timeout=20, env=env)
        # Perl must resolve the platform CGI first; the fallback is only needed
        # for Git-for-Windows, whose bundled Perl lacks CGI.pm.
        cgi_program = r'''
BEGIN {
  eval { require CGI; 1 } or do { unshift @INC, 'tests/perl-stub'; require CGI; };
  no warnings 'redefine';
  if (!length CGI::header(-type => 'application/json')) {
    *CGI::header = sub {
      my %fields = @_;
      return 'Status: '.($fields{'-status'} || '200 OK')."\r\nContent-Type: ".$fields{'-type'}."\r\n\r\n";
    };
  }
  *CGI::param = sub {
    return 'verification-report' if ($_[1] || '') eq 'action';
    return 'warning' if ($_[1] || '') eq 'backup_id';
    return '';
  };
  *CORE::GLOBAL::readpipe = sub {
    die "Unexpected CGI subprocess: $_[0]" unless $_[0] =~ /'verification-report' 'warning' 2>&1$/;
    $? = int($ENV{TEST_REPORT_STATUS}) << 8;
    return $ENV{TEST_REPORT_OUTPUT};
  };
}
do './webfrontend/htmlauth/index.cgi'; die $@ if $@;
'''
        cgi_env = {**os.environ, "PERL5LIB": "tests/perl", "REQUEST_METHOD": "GET",
                   "QUERY_STRING": "action=verification-report&backup_id=warning",
                   "HTTP_X_HOSTBACKUP_REQUEST": "1", "LBPDATADIR": self.state.as_posix(),
                   "REMOTE_USER": "fixture", "HTTP_USER_AGENT": "fixture",
                   "TEST_REPORT_STATUS": str(backend.returncode),
                   "TEST_REPORT_OUTPUT": backend.stdout + backend.stderr}
        cgi = subprocess.run([BASH, "--noprofile", "--norc", "-s"], cwd=ROOT, env=cgi_env,
                             input="perl -e " + shlex.quote(cgi_program) + "\n", text=True,
                             capture_output=True, timeout=20)
        self.assertEqual(cgi.returncode, 0, cgi.stderr)
        headers, body = cgi.stdout.replace("\r\n", "\n").split("\n\n", 1)
        self.assertIn("Content-Type: application/json", headers)
        return headers, json.loads(body)

    def assert_not_verified(self, report, status, available):
        self.assertEqual(report["status"], status)
        self.assertIs(report["content_verified"], False)
        self.assertIs(report["report_available"], available)
        self.assertIn("message", report)

    def test_missing_report_for_warning_backup_is_readable_hint_without_scan_or_baseline(self):
        target = self.warning_backup()
        original = {name: (target / name).read_bytes() for name in ("manifest.json", "backup-validation.json")}
        with mock.patch.object(MAINT, "walk_data", side_effect=AssertionError("No payload scan allowed")):
            report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "not_checked", False)
        self.assertIn("Hinweise ansehen", report["message"])
        self.assertIn("Vergleichsbasis", report["message"])
        self.assertNotIn("checked_at", report)
        self.assertFalse(list((self.state / "integrity").glob("*.baseline.sqlite")))
        self.assertFalse(self.report_path().exists())
        for name, data in original.items():
            self.assertEqual((target / name).read_bytes(), data)
        result = self.real_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_not_verified(json.loads(result.stdout), "not_checked", False)
        self.assertEqual(result.stderr, "")

    def test_completed_warning_backup_can_still_create_and_read_valid_integrity_report(self):
        self.warning_backup()
        first = MAINT.integrity(self.root, self.state, "warning")
        self.assertEqual(first["status"], "baseline_created")
        second = MAINT.integrity(self.root, self.state, "warning")
        self.assertEqual(second["status"], "verified")
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assertTrue(report["report_available"])
        self.assertTrue(report["content_verified"])
        self.assertEqual(report["checked_at"], second["checked_at"])
        self.assertFalse(report["restore_tested"])

    def test_invalid_report_json_is_typed_error_and_is_not_overwritten(self):
        self.warning_backup()
        path = self.report_path()
        damaged = b'{"status":broken\n'
        path.write_bytes(damaged)
        result = self.real_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assert_not_verified(report, "error", False)
        self.assertTrue(report["report_error"])
        self.assertEqual(path.read_bytes(), damaged)
        self.assertFalse(list((self.state / "integrity").glob("*.baseline.sqlite")))

    def test_invalid_shapes_identity_flags_and_changes_cannot_claim_success(self):
        self.warning_backup()
        path = self.report_path()
        _, record = MAINT.backup_record(self.root, "warning", self.state)
        valid = {"backup_id": "warning", "status": "verified", "content_verified": True,
                 "manifest_sha256": record["manifest_sha256"]}
        invalid = [[], None, "text", {}, {**valid, "backup_id": "other"},
                   {**valid, "status": "unexpected"}, {**valid, "status": []},
                   {**valid, "content_verified": "true"}, {**valid, "content_verified": False},
                   {**valid, "status": "changed"}, {**valid, "changes": {}},
                   {**valid, "changes": [None]}, {**valid, "changes": [{"path": [], "change": "missing"}]},
                   {**valid, "checked_at": {}}, {**valid, "message": []}, {**valid, "manifest_sha256": "invalid"}]
        for value in invalid:
            with self.subTest(value=value):
                data = json.dumps(value).encode()
                path.write_bytes(data)
                report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
                self.assert_not_verified(report, "error", False)
                self.assertEqual(path.read_bytes(), data)

    def test_report_read_permission_failure_is_error_not_missing(self):
        self.warning_backup()
        MAINT.integrity(self.root, self.state, "warning")
        path = self.report_path()
        before = path.read_bytes()
        original_read = MAINT.read_bytes

        def denied_report(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError("Fixture report read permission denied")
            return original_read(candidate, *args, **kwargs)

        with mock.patch.object(MAINT, "read_bytes", side_effect=denied_report):
            report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "error", False)
        self.assertIn("permission denied", report["report_error"])
        self.assertEqual(path.read_bytes(), before)

    def test_verified_report_cannot_contradict_changes_or_use_invalid_counters(self):
        self.warning_backup()
        MAINT.integrity(self.root, self.state, "warning")
        valid = MAINT.integrity(self.root, self.state, "warning")
        path = self.report_path()
        for changes in ({"changes": [{"path": "etc/hosts", "change": "changed"}]},
                        {"change_count": 1}, {"changes_truncated": True},
                        {"checked_files": True}, {"checked_files": -1}, {"checked_files": 1.5},
                        {"change_count": False}, {"change_count": -1}, {"change_count": "1"},
                        {"changes_truncated": 1}, {"changes_truncated": "false"}):
            with self.subTest(changes=changes):
                data = json.dumps({**valid, **changes}).encode()
                path.write_bytes(data)
                report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
                self.assert_not_verified(report, "error", False)
                self.assertEqual(path.read_bytes(), data)

    def test_changed_manifest_is_stale_and_existing_report_can_be_downloaded_as_history(self):
        target = self.warning_backup()
        MAINT.integrity(self.root, self.state, "warning")
        verified = MAINT.integrity(self.root, self.state, "warning")
        report_bytes = self.report_path().read_bytes()
        manifest = json.loads((target / "manifest.json").read_bytes())
        manifest["finished_at"] = "changed"
        (target / "manifest.json").write_text(json.dumps(manifest))
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "stale", True)
        self.assertEqual(report["checked_at"], verified["checked_at"])
        self.assertEqual(self.report_path().read_bytes(), report_bytes)

    def test_legacy_report_without_manifest_hash_is_not_silently_trusted(self):
        self.warning_backup()
        self.report_path().write_text(json.dumps({"backup_id": "warning", "status": "verified",
                                                 "content_verified": True, "checked_at": "2020-01-01"}))
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "stale", True)
        self.assertEqual(report["checked_at"], "2020-01-01")

    def test_changed_content_report_remains_available_without_claiming_verified(self):
        target = self.warning_backup()
        MAINT.integrity(self.root, self.state, "warning")
        (target / "rootfs/etc/hosts").write_text("changed\n")
        MAINT.integrity(self.root, self.state, "warning")
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assertEqual(report["status"], "changed")
        self.assertTrue(report["report_available"])
        self.assertFalse(report["content_verified"])
        self.assertEqual(report["changes"], [{"path": "etc/hosts", "change": "changed"}])

    def test_unsafe_report_link_is_not_followed(self):
        self.warning_backup()
        path = self.report_path()
        outside = self.state / "outside-report"
        outside.write_bytes(b'PRIVATE SENTINEL')
        try:
            path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "error", False)
        self.assertNotIn("PRIVATE SENTINEL", json.dumps(report))
        self.assertTrue(path.is_symlink())

    def test_hardlinked_report_is_not_read_or_replaced(self):
        self.warning_backup()
        path = self.report_path()
        outside = self.state / "outside-report"
        outside.write_bytes(b'PRIVATE SENTINEL')
        try:
            os.link(outside, path)
        except (OSError, NotImplementedError):
            self.skipTest("Hardlinks unavailable")
        report = MAINT.integrity(self.root, self.state, "warning", report_only=True)
        self.assert_not_verified(report, "error", False)
        self.assertNotIn("PRIVATE SENTINEL", json.dumps(report))
        self.assertEqual(outside.read_bytes(), b'PRIVATE SENTINEL')

    def test_target_manifest_and_state_safety_failures_still_fail_closed(self):
        target = self.warning_backup()
        with mock.patch.object(MAINT, "state_dir", side_effect=PermissionError("Unsafe protected state")):
            with self.assertRaisesRegex(PermissionError, "Unsafe protected state"):
                MAINT.integrity(self.root, self.state, "warning", report_only=True)
        (target / "manifest.json").write_text("broken")
        with self.assertRaises(ValueError):
            MAINT.integrity(self.root, self.state, "warning", report_only=True)

    def test_real_backend_report_and_cgi_get_route_missing_corrupt_valid_busy_and_manifest_error(self):
        target = self.warning_backup()
        headers, report = self.cgi_report()
        self.assertIn("200 OK", headers)
        self.assert_not_verified(report, "not_checked", False)
        path = self.report_path()
        path.write_text("corrupt JSON")
        headers, report = self.cgi_report()
        self.assertIn("200 OK", headers)
        self.assert_not_verified(report, "error", False)
        # The check operation, not the report viewer, creates the new result.
        MAINT.integrity(self.root, self.state, "warning")
        MAINT.integrity(self.root, self.state, "warning")
        headers, report = self.cgi_report()
        self.assertIn("200 OK", headers)
        self.assertEqual(report["status"], "verified")
        self.assertTrue(report["report_available"])
        contradictory = json.loads(path.read_bytes())
        contradictory["changes"] = [{"path": "etc/hosts", "change": "changed"}]
        path.write_text(json.dumps(contradictory))
        headers, report = self.cgi_report()
        self.assertIn("200 OK", headers)
        self.assert_not_verified(report, "error", False)
        self.assertIn("contradicts", report["report_error"])
        headers, report = self.cgi_report(busy=True)
        self.assertIn("409 Conflict", headers)
        self.assertFalse(report["ok"])
        self.assertIn("Diese Aktion ist waehrend", report["error"])
        (target / "manifest.json").write_text("corrupt manifest")
        headers, report = self.cgi_report()
        self.assertIn("500 Internal Server Error", headers)
        self.assertFalse(report["ok"])
        self.assertIn("HostBackup maintenance", report["error"])


if __name__ == "__main__":
    unittest.main()
