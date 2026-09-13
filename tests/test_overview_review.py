import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overview_review", ROOT / "bin/hostbackup-overview.py")
overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overview)


class OverviewReviewTests(unittest.TestCase):
    def test_new_queued_task_is_selected_and_old_queue_is_interrupted(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / "tasks").mkdir()
            path = state / "tasks/backup-queued.log.json"
            task = {"state": "queued", "pid": 0, "updated_at": time.time()}
            path.write_text(json.dumps(task))
            self.assertEqual(overview.overview({}, None, state)["active_task"], "backup-queued.log")
            task["updated_at"] = 0
            path.write_text(json.dumps(task))
            report = overview.overview({}, None, state)
            self.assertIsNone(report["active_task"])
            self.assertEqual(report["last_failure"]["state"], "interrupted")

    def test_nonobject_validation_does_not_crash_entire_overview(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "backup-one"
            backup.mkdir()
            (backup / "manifest.json").write_text(json.dumps({"backup_id": "backup-one", "status": "complete"}))
            (backup / "backup-validation.json").write_text("[]")
            report = overview.overview({}, root, root)
            self.assertIsNone(report["last_success"])


if __name__ == "__main__":
    unittest.main()
