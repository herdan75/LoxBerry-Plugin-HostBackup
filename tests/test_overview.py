import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hostbackup_overview", ROOT / "bin/hostbackup-overview.py")
overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overview)


class OverviewTests(unittest.TestCase):
    def test_disabled_schedule_has_no_next_run(self):
        self.assertIsNone(overview.next_run({"schedule_enabled": False}))

    def test_daily_next_day(self):
        result = overview.next_run({"schedule_enabled": True, "schedule_time": "02:00"}, datetime(2026, 9, 13, 3, 0))
        self.assertTrue(result["local"].startswith("2026-09-14T02:00"))

    def test_weekly_uses_cron_sunday_number(self):
        result = overview.next_run({"schedule_enabled": True, "schedule_time": "02:00", "schedule_mode": "weekly", "schedule_weekdays": ["0"]}, datetime(2026, 9, 12, 3, 0))
        self.assertTrue(result["local"].startswith("2026-09-13T02:00"))

    def test_monthly_short_month_falls_back_to_last_day(self):
        result = overview.next_run({"schedule_enabled": True, "schedule_time": "02:00", "schedule_mode": "monthly", "schedule_monthdays": ["31"], "schedule_months": ["2"]}, datetime(2027, 2, 1, 3, 0))
        self.assertTrue(result["local"].startswith("2027-02-28T02:00"))

    def test_monthly_respects_selected_months(self):
        result = overview.next_run({"schedule_enabled": True, "schedule_time": "02:00", "schedule_mode": "monthly", "schedule_monthdays": ["1"], "schedule_months": ["12"]}, datetime(2026, 2, 1, 3, 0))
        self.assertTrue(result["local"].startswith("2026-12-01T02:00"))

    def test_no_silent_empty_schedule_defaults(self):
        for mode, weekdays, monthdays, months in [("weekly", "", "1", "*"), ("monthly", "0", "", "*"), ("monthly", "0", "1", "")]:
            with self.subTest(mode=mode, monthdays=monthdays, months=months):
                with self.assertRaises(ValueError):
                    overview.check_settings("full", "native-strict", "true", mode, "02:00", weekdays, monthdays, months)

    def test_portable_snapshot_configuration_is_valid_runtime_is_checked_separately(self):
        overview.check_settings("snapshot", "portable-archive", "false", "daily", "02:00", "0", "1", "*")

    def test_network_snapshot_is_valid(self):
        overview.check_settings("snapshot", "network-compatible", "true", "weekly", "02:00", "0,2,4", "1", "*")

    def test_failed_or_interrupted_tasks_visible_without_selected_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "tasks").mkdir()
            task = {"task": "backup-example.log", "state": "running", "pid": 999999999, "process_start_ticks": "1", "updated_at": 10}
            (state / "tasks/backup-example.log.json").write_text(json.dumps(task))
            result = overview.overview({}, None, state)
            self.assertEqual(result["last_failure"]["state"], "interrupted")
            self.assertIsNone(result["active_task"])
            self.assertFalse(result["target"]["readable"])

    def test_current_process_is_detected_by_pid_and_start_ticks(self):
        if not Path("/proc/self/stat").is_file():
            self.skipTest("Linux /proc required")
        text = Path("/proc/self/stat").read_text()
        ticks = text[text.rfind(")") + 2:].split()[19]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "tasks").mkdir()
            task = {"state": "running", "pid": os.getpid(), "process_start_ticks": ticks, "updated_at": 10}
            (state / "tasks/backup-current.log.json").write_text(json.dumps(task))
            self.assertEqual(overview.overview({}, None, state)["active_task"], "backup-current.log")

    def test_preview_excludes_backup_stick_not_other_usb_data(self):
        mounted = {"filesystems": [{"target": "/", "fstype": "ext4"}, {"target": "/media/usb/PI_Backup", "fstype": "ext4"}, {"target": "/media/usb/USB_Loxberry", "fstype": "ext4"}]}
        with patch.object(overview.subprocess, "run", return_value=type("Result", (), {"stdout": json.dumps(mounted)})()):
            result = overview.preview({"backup_mode": "snapshot", "metadata_mode": "native-strict"}, "/media/usb/PI_Backup/hostbackup", ["/media/usb/PI_Backup"], "older", {"available_mb": 100})
        sources = {x["path"]: x for x in result["source_volumes"]}
        self.assertFalse(sources["/media/usb/PI_Backup"]["included"])
        self.assertTrue(sources["/media/usb/USB_Loxberry"]["included"])
        self.assertEqual(result["reference_id"], "older")
        self.assertFalse(result["full_baseline_required"])
        self.assertTrue(result["saved_config"])


if __name__ == "__main__":
    unittest.main()
