"""Exercise the backend report contract consumed by the CGI JSON route."""
import json
import shlex
import subprocess
import unittest

from test_runtime_safety import BASH, function


@unittest.skipUnless(BASH, "Bash is required")
class MaintenanceApiTests(unittest.TestCase):
    def report(self, helper, args=("report", "20260913-120000")):
        source = r'''
set -euo pipefail
backup_root() { printf '/fixture\n'; }
verify_backup_target() { :; }
require_root_for_write() { printf 'require-root\n' >&2; }
acquire_operation_lock() { printf 'operation:%s\n' "$1" >&2; }
require_backup_id() { :; }
acquire_backup_lock() { :; }
safe_backup_target() { printf '/fixture/20260913-120000\n'; }
'''
        source += "maintenance_helper() { " + helper + "; }\n"
        source += function("maintenance_action")
        source += "maintenance_action " + shlex.join(args) + "\n"
        return subprocess.run([BASH, "--noprofile", "--norc", "-s"], input=source,
                              capture_output=True, text=True, timeout=30)

    def test_report_is_plain_json_for_cgi_not_http_headers(self):
        result = self.report("printf '%s\\n' '{\"status\":\"verified\",\"restore_tested\":false}'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "verified", "restore_tested": False})

    def test_report_failure_does_not_emit_success_headers(self):
        result = self.report("printf '%s\\n' 'report unavailable' >&2; return 17")
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, "")

    def test_manual_restore_record_requires_write_guard_and_preserves_arguments(self):
        result = self.report("printf '%s\\n' \"$@\"", (
            "record-restore-test", "20260913-120000", "passed",
            "2026-09-12T12:00:00Z", "Offline copy; service start checked"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("require-root\noperation:exclusive", result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "record-restore-test", "/fixture", "20260913-120000", "--result", "passed",
            "--tested-at", "2026-09-12T12:00:00Z", "--note", "Offline copy; service start checked"])


if __name__ == "__main__":
    unittest.main()
