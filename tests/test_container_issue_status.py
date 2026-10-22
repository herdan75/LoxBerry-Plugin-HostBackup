"""Persist understandable container failures through the real task/journal APIs.

The host entry point is never sourced. Only extracted production functions run,
with disposable state and a read-only Docker state double.
"""

import json
from pathlib import Path
import tempfile
import unittest

import test_runtime_safety as runtime


FIRST = "ab" * 32
SECOND = "cd" * 32
TASK = "backup-test.log"
FUNCTIONS = (
    "restart_journal_path_is_safe", "restart_journal_update", "restart_journal_create",
    "verify_stopped_docker_targets", "log_dirs", "task_log_path", "task_status",
)
FIXTURE = r'''
docker_recovery_state() {
  printf '%s\n' "$1" >> "$TEST_ROOT/inspected-ids"
  case "$1" in
    ab*) printf '%s\n' "${FIRST_STATE:-running}" ;;
    cd*) printf '%s\n' "${SECOND_STATE:-missing}" ;;
    *) return 99 ;;
  esac
}
docker() { echo forbidden-docker-write >&2; return 99; }
systemctl() { echo forbidden-systemd-write >&2; return 99; }
'''
INITIALIZE = r'''
task=backup-test.log
log_file="$TASK_LOG_DIR/$task"
prepare_log_file "$log_file" truncate
task_state_write "$task" running copying "$log_file" 0 ''
state_dir="$(restart_journal_create "$task")"
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required")
class ContainerIssueStatusTests(unittest.TestCase):
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hostbackup-container-issue-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def execute(self, source, env=None, expected=0):
        return self.run_shell(FIXTURE + source, FUNCTIONS, env=env, expected=expected)

    def initialize(self, entries=((FIRST, "loxpanel"),)):
        statements = [INITIALIZE]
        for identity, name in entries:
            for phase in ("intended", "stopped"):
                statements.append(f'restart_journal_update "$state_dir" {phase} docker {identity} "{name}"')
        self.execute("\n".join(statements))

    @property
    def task_path(self):
        return self.root / "state/tasks" / (TASK + ".json")

    def task_data(self):
        return json.loads(self.task_path.read_text(encoding="utf-8"))

    def observe(self, stage="after_copy", **env):
        self.execute(f'''
if verify_stopped_docker_targets "$RESTART_JOURNAL_DIR/{TASK}" {TASK} {stage} >> "$TASK_LOG_DIR/{TASK}"; then
  exit 99
else
  [ "$?" = 20 ]
fi
''', env=env)

    def test_original_names_multiple_states_survive_cleanup_and_short_log(self):
        self.initialize(((FIRST, "loxpanel"), (SECOND, "sonn-core")))
        journal_path = self.root / "state/restart-journals" / TASK / "journal.json"
        journal_before = journal_path.read_bytes()
        self.observe()
        self.assertEqual(journal_path.read_bytes(), journal_before)
        issues = self.task_data()["container_issues"]
        expected = [
            {"id": SECOND, "name": "sonn-core", "state": "missing", "stage": "after_copy"},
            {"id": FIRST, "name": "loxpanel", "state": "running", "stage": "after_copy"},
        ]
        self.assertEqual(issues, expected)
        result = self.execute(f'''
task_state_write {TASK} running restarting_services "$TASK_LOG_DIR/{TASK}" 0 ''
task_state_write {TASK} running post_hook "$TASK_LOG_DIR/{TASK}" 0 ''
task_state_write {TASK} failed cleanup_failed "$TASK_LOG_DIR/{TASK}" 0 20
for number in $(seq 1 150); do printf 'later cleanup line %s\n' "$number"; done >> "$TASK_LOG_DIR/{TASK}"
task_status {TASK} 1
''')
        response = json.loads(result.stdout)
        self.assertEqual(response["container_issues"], expected)
        self.assertEqual(response["phase"], "cleanup_failed")
        self.assertEqual(self.task_data()["container_issues"], expected)
        log = (self.root / "state/logs" / TASK).read_text(encoding="utf-8")
        self.assertIn("Docker-Container 'loxpanel'", log)
        self.assertIn("Der Ausloeser ist unbekannt", log)
        self.assertIn("Docker-Container 'sonn-core'", log)
        self.assertIn("nicht mehr vorhanden", log)
        self.assertEqual((self.root / "inspected-ids").read_text().splitlines(), [SECOND, FIRST])

    def test_old_journal_without_label_falls_back_to_immutable_id(self):
        self.initialize(((FIRST[:12], ""),))
        self.observe(stage="before_copy")
        self.assertEqual(self.task_data()["container_issues"], [{
            "id": FIRST[:12], "name": FIRST[:12], "state": "running", "stage": "before_copy",
        }])

    def test_invalid_legacy_label_is_not_exposed_or_used_to_query_docker(self):
        self.initialize()
        journal_path = self.root / "state/restart-journals" / TASK / "journal.json"
        for invalid in ("bad\nERROR forged", "<script>", "müller", {"name": "loxpanel"}, "x" * 256):
            with self.subTest(label=invalid):
                journal = json.loads(journal_path.read_text())
                journal["entries"][0]["label"] = invalid
                journal_path.write_text(json.dumps(journal), encoding="utf-8")
                self.observe()
                issue = self.task_data()["container_issues"][0]
                self.assertEqual(issue["name"], FIRST)
        self.assertTrue(all(item == FIRST for item in (self.root / "inspected-ids").read_text().splitlines()))

    def test_unavailable_is_not_described_as_restarted_or_removed(self):
        self.initialize()
        self.observe(FIRST_STATE="unavailable")
        self.assertEqual(self.task_data()["container_issues"][0]["state"], "unavailable")
        log = (self.root / "state/logs" / TASK).read_text()
        self.assertIn("weder einen Neustart noch eine Loeschung", log)
        self.assertNotIn("was started again", log)
        self.assertNotIn("was removed", log)

    def test_stopped_container_creates_no_issue_and_no_extra_docker_action(self):
        self.initialize()
        self.execute(f'verify_stopped_docker_targets "$RESTART_JOURNAL_DIR/{TASK}" {TASK} before_copy',
                     env={"FIRST_STATE": "stopped"})
        self.assertNotIn("container_issues", self.task_data())
        self.assertEqual((self.root / "inspected-ids").read_text().splitlines(), [FIRST])

    def test_duplicate_observation_does_not_duplicate_issue(self):
        self.initialize()
        self.observe()
        self.observe()
        self.assertEqual(len(self.task_data()["container_issues"]), 1)

    def test_invalid_direct_issue_is_rejected_without_modifying_task(self):
        self.initialize()
        before = self.task_path.read_bytes()
        for invalid in ("bad\nforged", "ä", "<script>", "x" * 256, ""):
            with self.subTest(name=invalid):
                result = self.execute(f'task_container_issue_record {TASK} {FIRST} "$BAD_NAME" running after_copy',
                                      env={"BAD_NAME": invalid}, expected=255)
                self.assertIn("Invalid container issue", result.stderr)
                self.assertEqual(self.task_path.read_bytes(), before)
        for state, stage in (("stopped", "after_copy"), ("missing", "elsewhere")):
            self.execute(f'task_container_issue_record {TASK} {FIRST} loxpanel {state} {stage}', expected=255)
            self.assertEqual(self.task_path.read_bytes(), before)
        for identity in ("", "loxpanel", "../task", "a" * 65):
            self.execute(f'task_container_issue_record {TASK} "$BAD_ID" loxpanel running after_copy',
                         env={"BAD_ID": identity}, expected=20)
            self.assertEqual(self.task_path.read_bytes(), before)

    def test_status_filters_tampered_fields_and_limits_issue_count(self):
        self.initialize()
        data = self.task_data()
        valid = {"id": FIRST, "name": "loxpanel", "state": "running", "stage": "after_copy"}
        data["container_issues"] = [None, "wrong", {**valid, "name": "x\ny"},
                                    {**valid, "state": {"bad": True}}, {**valid, "stage": "bad"}]
        data["container_issues"] += [{**valid, "id": f"{number:064x}", "private": "not exposed"} for number in range(105)]
        self.task_path.write_text(json.dumps(data), encoding="utf-8")
        response = json.loads(self.execute(f'task_status {TASK} 1').stdout)
        self.assertEqual(len(response["container_issues"]), 100)
        self.assertTrue(all(set(item) == {"id", "name", "state", "stage"} for item in response["container_issues"]))
        self.execute(f'task_state_write {TASK} failed failed "$TASK_LOG_DIR/{TASK}" 0 20')
        self.assertEqual(self.task_data()["container_issues"], response["container_issues"])

    def test_new_task_and_requeued_task_do_not_inherit_previous_issue(self):
        self.initialize()
        self.observe()
        self.execute('task_state_write backup-other.log queued queued "$TASK_LOG_DIR/backup-other.log" 0 ""')
        other = json.loads((self.root / "state/tasks/backup-other.log.json").read_text())
        self.assertNotIn("container_issues", other)
        self.execute(f'task_state_write {TASK} queued queued "$TASK_LOG_DIR/{TASK}" 0 ""')
        self.assertNotIn("container_issues", self.task_data())

    def test_expected_state_mismatch_does_not_rewrite_existing_issue(self):
        self.initialize()
        self.observe()
        before = self.task_path.read_bytes()
        self.execute(f'task_state_write {TASK} running launched "$TASK_LOG_DIR/{TASK}" 456 "" queued')
        self.assertEqual(self.task_path.read_bytes(), before)

    def test_concurrent_progress_update_keeps_recorded_issue(self):
        self.initialize()
        self.execute(f'''
(
  for number in $(seq 1 8); do task_state_write {TASK} running restarting_services "$TASK_LOG_DIR/{TASK}" 0 ''; done
) &
progress_pid=$!
task_container_issue_record {TASK} {FIRST} loxpanel running after_copy
wait "$progress_pid"
''')
        self.assertEqual(self.task_data()["container_issues"], [{
            "id": FIRST, "name": "loxpanel", "state": "running", "stage": "after_copy",
        }])


if __name__ == "__main__":
    unittest.main()
