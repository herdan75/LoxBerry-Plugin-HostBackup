"""Run the real journal/recovery functions with disposable Docker fixtures.

No Docker daemon, real services, installed HostBackup engine, or host backup
directory is accessed. A new Bash process is used for each recovery invocation
to prove that notification suppression survives cron process boundaries.
"""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import test_runtime_safety as runtime_safety
from test_runtime_safety import BASH, JOURNAL_FUNCTIONS, ROOT


OLD_ID = "df26d4b1ade4"
FULL_ID = "a" * 64
REPLACEMENT_ID = "b" * 64
TASK = "backup-test.log"

DOCKER_MOCK = r'''
timeout() {
  printf '%s\n' "$*" >> "$TEST_ROOT/timeout-calls"
  case "${1:-}" in -k|--kill-after) shift 2 ;; --kill-after=*) shift ;; esac
  shift; "$@"
}
docker() {
  printf '%s\n' "$*" >> "$TEST_ROOT/docker-calls"
  [ "${1:-}" != container ] || shift
  local identity state format
  case "${1:-}" in
    inspect)
      format="${3:-}"; identity="${4:-}"
      if [ "$format" = '{{.Id}}' ]; then
        printf '%s\n' "${MOCK_RESOLVED_ID:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"
        return 0
      fi
      [ "$format" = '{{.State.Running}}' ] || [ "$format" = '{{.Id}} {{.State.Running}}' ] || return 99
      state="${MOCK_DOCKER_STATE:-missing}"
      if [ -f "$TEST_ROOT/docker-state-$identity" ]; then
        state="$(cat "$TEST_ROOT/docker-state-$identity")"
      fi
      if [ "$format" = '{{.Id}} {{.State.Running}}' ]; then
        printf '%s ' "${MOCK_RESOLVED_ID:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"
      fi
      case "$state" in
        running) echo true; return "${MOCK_INSPECT_STATUS:-0}" ;;
        stopped) echo false; return "${MOCK_INSPECT_STATUS:-0}" ;;
        missing) printf '%s\n' "${MOCK_MISSING_ERROR:-Error response from daemon: No such container: $identity}" >&2; return 1 ;;
        unavailable) echo 'Cannot connect to the Docker daemon' >&2; return 1 ;;
        permission) echo 'permission denied while trying to connect to the Docker daemon socket' >&2; return 1 ;;
        malformed) echo maybe ;;
        timeout) return 124 ;;
        *) return 99 ;;
      esac ;;
    ps)
      [ -z "${MOCK_PS_LIST:-}" ] || printf '%s\n' "$MOCK_PS_LIST"
      return "${MOCK_PS_STATUS:-0}" ;;
    start)
      identity="${2:-}"
      printf '%s\n' "$identity" >> "$TEST_ROOT/docker-starts"
      if [ "${MOCK_START_FAIL:-false}" = true ]; then
        echo 'Container start failed in test fixture' >&2; return 1
      fi
      printf 'running\n' > "$TEST_ROOT/docker-state-$identity"
      printf '%s\n' "$identity" ;;
    stop)
      identity="${!#}"
      grep -q '"phase":"intended"' "$RESTART_JOURNAL_DIR/${MOCK_TASK_NAME:-backup-test.log}/journal.json" || return 88
      printf '%s\n' "$identity" >> "$TEST_ROOT/docker-stops"
      printf 'stopped\n' > "$TEST_ROOT/docker-state-$identity" ;;
    *) return 99 ;;
  esac
}
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required for recovery behavior tests")
class DockerRecoveryTests(unittest.TestCase):
    # Reuse only the isolated runner, not the test class inheritance hierarchy.
    run_shell = runtime_safety.RuntimeSafetyTests.run_shell

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-docker-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def execute(self, script, env=None, expected=0):
        return self.run_shell(DOCKER_MOCK + "\n" + script, JOURNAL_FUNCTIONS, env, expected)

    def initialize(self, identities=(OLD_ID,), label="demo"):
        statements = ['state_dir="$(restart_journal_create backup-test.log)"']
        for identity in identities:
            statements.extend((
                f'restart_journal_update "$state_dir" intended docker {identity} "{label}"',
                f'restart_journal_update "$state_dir" stopped docker {identity} "{label}"',
            ))
        self.execute("\n".join(statements) + "\n")

    @property
    def journal_path(self):
        return self.root / "state/restart-journals" / TASK / "journal.json"

    @property
    def history_path(self):
        paths = self.history_paths()
        self.assertEqual(len(paths), 1, paths)
        return paths[0]

    def history_paths(self):
        return sorted((self.root / "state/recovery-history").glob(TASK + "-*/journal"))

    def journal(self):
        return json.loads(self.journal_path.read_text(encoding="utf-8"))

    def task(self):
        return json.loads((self.root / "state/tasks" / (TASK + ".json")).read_text(encoding="utf-8"))

    def state(self, identity, value):
        (self.root / ("docker-state-" + identity)).write_text(value, encoding="utf-8")

    def starts(self):
        path = self.root / "docker-starts"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def complete_selected_service_cycle(self, env=None):
        """Finish the actual stop/restart journal lifecycle, without copying data."""
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$state_dir" "$TEST_ROOT/selected.tsv"
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''', env)
        self.assertFalse(self.journal_path.exists())

    def test_state_distinguishes_running_stopped_and_confirmed_missing(self):
        for state, expected in (("running", "running"), ("stopped", "stopped"), ("missing", "missing")):
            with self.subTest(state=state):
                result = self.execute(f"docker_recovery_state {OLD_ID}\n", {"MOCK_DOCKER_STATE": state})
                self.assertEqual(result.stdout.strip(), expected)
        result = self.execute(f"docker_recovery_state {FULL_ID}\n", {
            "MOCK_PS_LIST": REPLACEMENT_ID,
            "MOCK_MISSING_ERROR": f"Error: No such object: {FULL_ID}",
        })
        self.assertEqual(result.stdout.strip(), "missing")
        self.assertEqual(self.starts(), [])

    def test_uncertain_docker_state_never_counts_as_missing(self):
        scenarios = (
            {"MOCK_DOCKER_STATE": "unavailable"},
            {"MOCK_DOCKER_STATE": "permission"},
            {"MOCK_DOCKER_STATE": "timeout"},
            {"MOCK_DOCKER_STATE": "malformed"},
            {"MOCK_DOCKER_STATE": "running", "MOCK_INSPECT_STATUS": "1"},
            {"MOCK_DOCKER_STATE": "stopped", "MOCK_INSPECT_STATUS": "1"},
            {"MOCK_PS_STATUS": "1"},
            {"MOCK_PS_STATUS": "124"},
            {"MOCK_PS_LIST": "not-a-container-id"},
            {"MOCK_PS_LIST": REPLACEMENT_ID + "\nmalformed"},
            {"MOCK_PS_LIST": OLD_ID + "0" * (64 - len(OLD_ID))},
            {"MOCK_MISSING_ERROR": "Error response from daemon: unexpected failure"},
        )
        for env in scenarios:
            with self.subTest(env=env):
                result = self.execute(f"docker_recovery_state {OLD_ID}\n", env)
                self.assertEqual(result.stdout.strip(), "unavailable")
        for identity in ("demo", "abc123", "x" * 64):
            with self.subTest(identity=identity):
                result = self.execute(f"docker_recovery_state {identity}\n")
                self.assertEqual(result.stdout.strip(), "unavailable")
        self.assertEqual(self.starts(), [])

    def test_missing_confirmation_uses_bounded_full_container_inventory(self):
        self.execute(f"docker_recovery_state {OLD_ID}\n")
        calls = (self.root / "docker-calls").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any("container inspect" in line for line in calls), calls)
        self.assertTrue(any("ps -a --no-trunc" in line for line in calls), calls)
        timeouts = (self.root / "timeout-calls").read_text(encoding="utf-8")
        self.assertIn("inspect", timeouts)
        self.assertIn("ps -a --no-trunc", timeouts)

    def test_selected_stop_records_full_id_and_label_and_never_stops_by_name(self):
        self.state("demo", "running")
        self.state(FULL_ID, "running")
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$state_dir" "$TEST_ROOT/selected.tsv"
''')
        entry = self.journal()["entries"][0]
        self.assertEqual(entry["id"], FULL_ID)
        self.assertEqual(entry["label"], "demo")
        self.assertEqual(entry["phase"], "stopped")
        self.assertEqual((self.root / "docker-stops").read_text().splitlines(), [FULL_ID])

    def test_legacy_stop_all_requests_full_ids(self):
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
json_get_bool() { echo true; }
stop_docker_if_requested "$state_dir"
''', {"MOCK_PS_LIST": FULL_ID + "\tdemo"})
        entry = self.journal()["entries"][0]
        self.assertEqual((entry["id"], entry["label"], entry["phase"]), (FULL_ID, "demo", "stopped"))
        self.assertIn("ps --no-trunc", (self.root / "docker-calls").read_text())

    def test_live_backup_does_not_silently_accept_missing_container(self):
        self.initialize()
        self.execute('start_backup_targets_if_needed "$RESTART_JOURNAL_DIR/backup-test.log"\n', expected=1)
        self.assertEqual(self.journal()["entries"][0]["phase"], "stopped")
        self.assertEqual(self.history_paths(), [])
        self.assertEqual(self.starts(), [])

    def test_inactive_missing_id_is_terminal_without_touching_replacement(self):
        self.initialize(label="demo")
        self.state(REPLACEMENT_ID, "stopped")
        result = self.execute(r'''
RECOVERY_SETTLE_MISSING=true
restart_journal_retry_type "$RESTART_JOURNAL_DIR/backup-test.log" docker
test -z "$(restart_journal_update "$RESTART_JOURNAL_DIR/backup-test.log" pending)"
restart_journal_update "$RESTART_JOURNAL_DIR/backup-test.log" missing-list
''', {"MOCK_PS_LIST": REPLACEMENT_ID})
        self.assertEqual(self.journal()["entries"][0]["phase"], "missing")
        self.assertIn("docker\t" + OLD_ID + "\tmissing", result.stdout)
        self.assertEqual(self.starts(), [])
        self.assertEqual((self.root / ("docker-state-" + REPLACEMENT_ID)).read_text(), "stopped")

    def test_active_task_journal_is_not_settled(self):
        self.initialize()
        before = self.journal_path.read_bytes()
        result = self.execute(r'''
task_process_is_current() { return 0; }
recover_restart_journals --scheduled
''')
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertEqual(self.journal_path.read_bytes(), before)
        self.assertFalse((self.root / "docker-calls").exists())

    def test_selected_container_already_stopped_is_never_started(self):
        self.state("demo", "stopped")
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$state_dir" "$TEST_ROOT/selected.tsv"
start_backup_targets_if_needed "$state_dir"
''')
        self.assertEqual(self.journal()["entries"], [])
        self.assertFalse((self.root / "docker-stops").exists())
        self.assertEqual(self.starts(), [])

    def test_container_removed_between_successful_service_cycles_does_not_block_next_backup(self):
        self.state("demo", "running")
        self.state(FULL_ID, "running")
        self.complete_selected_service_cycle()
        self.assertEqual(self.starts(), [FULL_ID])

        # Removal is AFTER the completed first cycle; the saved selection still
        # contains demo. This is not an interrupted-backup recovery scenario.
        self.state("demo", "missing")
        self.state(FULL_ID, "missing")
        self.complete_selected_service_cycle()
        self.assertEqual(self.starts(), [FULL_ID])
        self.assertEqual((self.root / "docker-stops").read_text().splitlines(), [FULL_ID])
        self.assertEqual(list((self.root / "state/restart-journals").iterdir()), [])
        scheduled = self.execute("recover_restart_journals --scheduled\n")
        self.assertEqual(scheduled.stdout + scheduled.stderr, "")

    def test_two_actual_backup_workers_finish_when_container_is_removed_between_runs(self):
        self.state("demo", "running")
        self.state(FULL_ID, "running")
        self.run_shell(DOCKER_MOCK + runtime_safety.PREFLIGHT_MOCKS + r'''
preflight_backup() { printf '{"status":"ok"}\n'; }
json_get_bool() { echo false; }
write_backup_marker() { :; }
write_manifest() { printf '{"status":"%s"}\n' "$3" > "$1/manifest.json"; }
selected_stop_targets() { printf 'docker\tdemo\n'; }
rsync_live_options() { :; }
rsync_metadata_options() { :; }
rsync_destination() { printf '%s\n' "$2"; }
# Only the copy/validation/storage dependencies are simulated. The production
# backup worker and its complete service/journal lifecycle run unchanged.
rsync() {
  assert_mock_copy_scope "$@" || return 99
  [[ "${!#}" == "$TEST_ROOT/target/"*"/rootfs/" ]]
}
calculate_size() { echo 12; }
calculate_files() { echo 1; }
validate_completed_backup() { :; }
prune_old_backups() { :; }
MOCK_TASK_NAME=backup-first.log create_backup first
printf 'missing\n' > "$TEST_ROOT/docker-state-demo"
printf 'missing\n' > "$TEST_ROOT/docker-state-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MOCK_TASK_NAME=backup-second.log create_backup second
''', (*JOURNAL_FUNCTIONS, "create_backup"))
        for name in ("first", "second"):
            task = json.loads((self.root / f"state/tasks/backup-{name}.log.json").read_text())
            manifest = json.loads((self.root / f"target/{name}/manifest.json").read_text())
            self.assertEqual((task["state"], task["phase"]), ("finished", "complete"))
            self.assertEqual(manifest["status"], "complete")
            receipt = json.loads((self.root / f"target/{name}/copy-result.json").read_text())
            self.assertEqual(receipt, {"tool": "rsync", "copy_exit_status": 0,
                                      "source_verification_status": 0, "effective_status": 0})
        self.assertEqual(self.starts(), [FULL_ID])
        self.assertEqual((self.root / "docker-stops").read_text().splitlines(), [FULL_ID])
        self.assertEqual(list((self.root / "state/restart-journals").iterdir()), [])
        scheduled = self.execute("recover_restart_journals --scheduled\n")
        self.assertEqual(scheduled.stdout + scheduled.stderr, "")

    def test_same_name_recreated_between_backups_uses_current_full_id_only(self):
        self.state("demo", "running")
        self.state(FULL_ID, "running")
        self.complete_selected_service_cycle()
        self.state(FULL_ID, "missing")
        self.state(REPLACEMENT_ID, "running")
        self.complete_selected_service_cycle({"MOCK_RESOLVED_ID": REPLACEMENT_ID})
        self.assertEqual(self.starts(), [FULL_ID, REPLACEMENT_ID])
        self.assertEqual((self.root / "docker-stops").read_text().splitlines(), [FULL_ID, REPLACEMENT_ID])
        self.assertEqual((self.root / ("docker-state-" + FULL_ID)).read_text(), "missing")
        self.assertFalse(self.journal_path.exists())

    def test_missing_selected_name_requires_reliable_inventory_before_skipping(self):
        self.execute('state_dir="$(restart_journal_create backup-test.log)"\n')
        cases = (
            {"MOCK_PS_STATUS": "1"},
            {"MOCK_PS_STATUS": "124"},
            {"MOCK_PS_LIST": "demo"},
            {"MOCK_PS_LIST": "other\ndemo"},
            {"MOCK_PS_LIST": "bad container name"},
            {"MOCK_PS_LIST": "other\n/name-with-slash"},
            {"MOCK_DOCKER_STATE": "unavailable"},
            {"MOCK_DOCKER_STATE": "permission"},
            {"MOCK_DOCKER_STATE": "timeout"},
        )
        for env in cases:
            with self.subTest(env=env):
                self.execute(r'''
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$RESTART_JOURNAL_DIR/backup-test.log" "$TEST_ROOT/selected.tsv"
''', env, expected=1)
                self.assertEqual(self.journal()["entries"], [])
        self.assertFalse((self.root / "docker-stops").exists())
        self.assertEqual(self.starts(), [])

    def test_deleted_selection_is_skipped_with_other_valid_named_containers_present(self):
        self.complete_selected_service_cycle({"MOCK_PS_LIST": "other-container\ndemo.other\ndemo2"})
        self.assertEqual(self.starts(), [])
        self.assertFalse((self.root / "docker-stops").exists())
        calls = (self.root / "docker-calls").read_text()
        self.assertIn("{{.Names}}", calls)

    def test_old_name_only_journal_is_not_retired_by_selected_name_detection(self):
        self.initialize(("demo",))
        self.execute("recover_restart_journals --scheduled\n", expected=1)
        self.assertEqual(self.journal()["entries"][0]["phase"], "stopped")
        self.assertEqual(self.history_paths(), [])
        self.assertEqual(self.starts(), [])

    @unittest.skipIf(os.name == "nt", "Production archive ownership/mode checks require Linux")
    def test_old_short_id_is_archived_without_starting_replacement_or_losing_evidence(self):
        self.initialize(label="same-name-replacement")
        evidence = self.journal_path.parent / "unexpected-diagnostic.txt"
        evidence.write_text("retain this evidence", encoding="utf-8")
        self.state(REPLACEMENT_ID, "running")
        result = self.execute("recover_restart_journals --scheduled\n", {"MOCK_PS_LIST": REPLACEMENT_ID})
        self.assertIn(OLD_ID, result.stdout + result.stderr)
        self.assertFalse(self.journal_path.exists())
        archived = json.loads((self.history_path / "journal.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["entries"][0]["phase"], "missing")
        self.assertEqual((self.history_path / evidence.name).read_text(), "retain this evidence")
        self.assertEqual((self.task()["state"], self.task()["phase"]), ("failed", "recovery_missing_containers"))
        spec = importlib.util.spec_from_file_location("docker_recovery_overview", ROOT / "bin/hostbackup-overview.py")
        overview = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overview)
        dashboard = overview.overview({}, None, self.root / "state")
        self.assertEqual(dashboard["pending_service_recovery"], 0)
        self.assertEqual(list((self.root / "state/restart-journals").iterdir()), [])
        self.assertEqual(self.starts(), [])
        self.assertEqual((self.root / ("docker-state-" + REPLACEMENT_ID)).read_text(), "running")
        later = self.execute("recover_restart_journals --scheduled\n", {"MOCK_PS_LIST": REPLACEMENT_ID})
        self.assertEqual(later.stdout + later.stderr, "")

    def test_daemon_unavailable_is_retryable_and_deduplicated_across_processes(self):
        self.initialize()
        env = {"MOCK_DOCKER_STATE": "unavailable"}
        first = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        self.assertTrue(first.stdout + first.stderr)
        second = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        self.assertEqual(second.stdout + second.stderr, "")
        self.assertEqual(self.journal()["entries"][0]["phase"], "stopped")
        self.assertEqual(self.history_paths(), [])
        manual = self.execute("recover_restart_journals\n", env, expected=1)
        self.assertTrue(manual.stdout + manual.stderr)
        self.assertEqual(self.starts(), [])

    def test_real_start_failures_still_retry_when_repeated_mail_is_suppressed(self):
        self.initialize((FULL_ID,))
        self.state(FULL_ID, "stopped")
        env = {"MOCK_START_FAIL": "true"}
        first = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        second = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        self.assertTrue(first.stdout + first.stderr)
        self.assertEqual(second.stdout + second.stderr, "")
        self.assertEqual(self.starts(), [FULL_ID, FULL_ID])
        self.assertTrue(self.journal_path.exists())
        self.execute("recover_restart_journals --scheduled\n")
        self.assertEqual(self.starts(), [FULL_ID, FULL_ID, FULL_ID])
        self.assertFalse(self.journal_path.exists())
        self.assertEqual(self.task()["phase"], "recovered_after_interruption")

    def test_changed_failure_notifies_without_waiting_for_reminder(self):
        self.initialize((FULL_ID,))
        self.execute("recover_restart_journals --scheduled\n", {"MOCK_DOCKER_STATE": "unavailable"}, expected=1)
        self.state(FULL_ID, "stopped")
        changed = self.execute("recover_restart_journals --scheduled\n", {"MOCK_START_FAIL": "true"}, expected=1)
        self.assertTrue(changed.stdout + changed.stderr)
        again = self.execute("recover_restart_journals --scheduled\n", {"MOCK_START_FAIL": "true"}, expected=1)
        self.assertEqual(again.stdout + again.stderr, "")

    def test_persisted_notification_reminds_after_one_day_and_on_clock_rollback(self):
        self.initialize()
        env = {"MOCK_DOCKER_STATE": "unavailable"}
        self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        for changed_time in (int(time.time()) - 86401, int(time.time()) + 86401):
            with self.subTest(timestamp=changed_time):
                journal = self.journal()
                journal["notification"]["at"] = changed_time
                self.journal_path.write_text(json.dumps(journal), encoding="utf-8")
                reminder = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
                self.assertTrue(reminder.stdout + reminder.stderr)
                quiet = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
                self.assertEqual(quiet.stdout + quiet.stderr, "")
        self.assertTrue(self.journal_path.exists())

    def test_missing_is_only_a_terminal_docker_state_not_systemd_success(self):
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd demo.service
if restart_journal_update "$state_dir" missing systemd demo.service; then exit 99; fi
''')
        self.assertEqual(self.journal()["entries"][0]["phase"], "intended")

    def test_failed_full_id_resolution_cannot_stop_name_or_create_false_intent(self):
        self.state("demo", "running")
        self.execute(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$state_dir" "$TEST_ROOT/selected.tsv"
''', {"MOCK_RESOLVED_ID": "not-a-full-id"}, expected=1)
        self.assertEqual(self.journal()["entries"], [])
        self.assertFalse((self.root / "docker-stops").exists())

    @unittest.skipIf(os.name == "nt", "Production archive ownership/mode checks require Linux")
    def test_mixed_missing_and_failed_start_preserves_actual_pending_recovery(self):
        self.initialize((OLD_ID, FULL_ID))
        self.state(FULL_ID, "stopped")
        env = {"MOCK_START_FAIL": "true", "MOCK_PS_LIST": FULL_ID}
        self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        entries = {entry["id"]: entry["phase"] for entry in self.journal()["entries"]}
        self.assertEqual(entries, {OLD_ID: "missing", FULL_ID: "stopped"})
        self.assertEqual(self.history_paths(), [])
        again = self.execute("recover_restart_journals --scheduled\n", env, expected=1)
        self.assertEqual(again.stdout + again.stderr, "")
        self.assertEqual(self.starts(), [FULL_ID, FULL_ID])
        self.execute("recover_restart_journals --scheduled\n", {"MOCK_PS_LIST": FULL_ID})
        self.assertFalse(self.journal_path.exists())
        archived = json.loads((self.history_path / "journal.json").read_text())
        self.assertEqual({e["id"]: e["phase"] for e in archived["entries"]}, {OLD_ID: "missing", FULL_ID: "restarted"})
        self.assertEqual(self.task()["phase"], "recovery_missing_containers")

    @unittest.skipIf(os.name == "nt", "Production archive ownership/mode checks require Linux")
    def test_repeated_task_name_archives_both_journals_without_overwriting(self):
        self.initialize()
        self.execute("recover_restart_journals --scheduled\n")
        original = self.history_path / "journal.json"
        before = original.read_bytes()
        self.initialize((FULL_ID,))
        self.execute("recover_restart_journals --scheduled\n")
        paths = self.history_paths()
        self.assertEqual(len(paths), 2)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(self.journal_path.exists())

    @unittest.skipIf(os.name == "nt", "Real directory symlinks require Linux")
    def test_history_symlink_is_rejected_without_moving_the_journal(self):
        self.initialize()
        outside = self.root / "outside-history"
        outside.mkdir()
        (self.root / "state/recovery-history").symlink_to(outside, target_is_directory=True)
        self.execute("recover_restart_journals --scheduled\n", expected=1)
        self.assertTrue(self.journal_path.exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_history_regular_file_is_rejected_without_removing_pending_evidence(self):
        self.initialize()
        history = self.root / "state/recovery-history"
        history.write_text("do not overwrite", encoding="utf-8")
        result = self.execute("recover_restart_journals --scheduled\n", expected=1)
        self.assertIn("Unsafe recovery history", result.stdout + result.stderr)
        self.assertTrue(self.journal_path.exists())
        self.assertEqual(history.read_text(), "do not overwrite")


if __name__ == "__main__":
    unittest.main()
