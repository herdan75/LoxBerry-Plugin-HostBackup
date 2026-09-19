"""Exercise the actual save function against temporary configuration, never live mounts."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_runtime_safety import BASH, ROOT, function


@unittest.skipUnless(BASH, "Bash is required")
class SettingsWorkflowTests(unittest.TestCase):
    def run_save(self, metadata="native-strict", mode="full", schedule="false", weekdays="0", monthdays="1", months="*", selection=None, previous_selection=None):
        with tempfile.TemporaryDirectory(prefix="hostbackup-settings-") as tmp:
            base = Path(tmp)
            original = {"backup_root": "", "keep_backups": 3, "metadata_mode": "native-strict",
                        "retention_mode": "gfs", "keep_daily": 0, "keep_weekly": 8, "keep_monthly": 12,
                        "integrity_enabled": True, "integrity_interval_days": 14,
                        "log_retention_days": 60, "quarantine_retention_days": 21}
            if previous_selection is not None:
                original["source_selection"] = previous_selection
            (base / "config.json").write_text(json.dumps(original), encoding="utf-8")
            args = ["", "/media/usb/PI_Backup", "false", "false", "5", schedule, "weekly" if schedule == "true" else "daily", "02:00", "0", "1", months, weekdays, monthdays, "", "", "true", mode, "", "false", "", "true", "true", "true", "true", metadata]
            if selection is not None:
                args.append(json.dumps(selection))
            source = r'''
set -euo pipefail
cd "$SETTINGS_TEST_DIR"
CONFIG_FILE="$(pwd)/config.json"
LBP_BINDIR="$SETTINGS_HELPERS"
require_root_for_write() { :; }
acquire_operation_lock() { :; }
prepare_target_registration() {
  printf registered > registration-called
  REGISTERED_ROOT=''; REGISTERED_MARKER=fixture; REGISTERED_MOUNTPOINT=/fixture
  REGISTERED_SOURCE=fixture; REGISTERED_FSTYPE=ext4; REGISTERED_MAJMIN=''
}
install_schedule() { printf installed > schedule-called; }
'''
            source += function("show_config") + function("save_config")
            source += "save_config " + " ".join(map(shlex.quote, args)) + "\n"
            env = os.environ.copy()
            env.update(SETTINGS_TEST_DIR=str(base), SETTINGS_HELPERS=(ROOT / "bin").as_posix(), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([BASH, "--noprofile", "--norc", "-s"], input=source, env=env, capture_output=True, text=True)
            return result, json.loads((base / "config.json").read_text()), (base / "registration-called").exists(), (base / "schedule-called").exists(), original

    def test_main_save_retains_separate_maintenance_settings(self):
        result, saved, registered, scheduled, original = self.run_save()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(saved["keep_backups"], 5)
        self.assertEqual(saved["rsync_extra_excludes"], ["/media/usb/PI_Backup"])
        for key in ("retention_mode", "keep_daily", "keep_weekly", "keep_monthly", "integrity_enabled", "integrity_interval_days", "log_retention_days", "quarantine_retention_days"):
            self.assertEqual(saved[key], original[key], key)
        self.assertTrue(registered)
        self.assertTrue(scheduled)

    def test_incompatible_profile_rejected_before_registration_or_write(self):
        result, saved, registered, scheduled, original = self.run_save(metadata="portable-archive", mode="snapshot")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved, original)
        self.assertFalse(registered)
        self.assertFalse(scheduled)

    def test_empty_weekday_rejected_before_registration_or_write(self):
        result, saved, registered, scheduled, original = self.run_save(schedule="true", weekdays="")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved, original)
        self.assertFalse(registered)
        self.assertFalse(scheduled)

    def test_old_save_preserves_source_scope(self):
        result, saved, _, _, _ = self.run_save()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved["source_selection"], {"policy": "legacy", "overrides": {}})
        selection = {"policy": "local", "overrides": {"/mnt/nas": True}}
        result, saved, _, _, _ = self.run_save(previous_selection=selection)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved["source_selection"], selection)

    def test_explicit_source_save_is_persisted(self):
        selection = {"policy": "local", "overrides": {"/mnt/nas": True, "/media/usb/PI_Backup": False}}
        result, saved, _, _, _ = self.run_save(selection=selection)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved["source_selection"], selection)

    def test_invalid_source_selection_is_rejected_before_registration(self):
        result, saved, registered, scheduled, original = self.run_save(selection={"policy": "local", "overrides": {"/mnt/nas": "true"}})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved, original)
        self.assertFalse(registered)
        self.assertFalse(scheduled)


if __name__ == "__main__":
    unittest.main()
