"""Exercise actual safety functions with disposable paths and mocked host services.

The backend entry point is never executed/sourced, no privileged service command
is run and no test copy can target the host root filesystem.
"""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else None)
SOURCE = ROOT / "bin" / "hostbackup.sh"


def function(name):
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n(?=\n)", SOURCE.read_text(encoding="utf-8"), re.M | re.S)
    if not match:
        raise AssertionError(f"Missing function {name}")
    return match.group(0)


COMMON_FUNCTIONS = (
    "log", "manifest_field", "json_escape", "valid_task_name", "task_state_path",
    "task_state_write", "task_state_value", "prepare_log_file", "write_control_marker",
    "task_failure_on_exit", "install_task_failure_trap",
)
JOURNAL_FUNCTIONS = (
    "restart_journal_path_is_safe", "restart_journal_update", "restart_journal_create",
    "restart_journal_finish", "restart_journal_retry_type", "recover_restart_journals",
    "stop_selected_systemd_targets", "stop_selected_docker_targets", "stop_docker_if_requested",
    "stop_backup_targets", "start_docker_if_needed", "start_systemd_if_needed",
    "log_restart_targets", "start_backup_targets_if_needed", "backup_cleanup_on_exit",
)
SETUP = r'''
set -euo pipefail
cd -- "$RUNTIME_TEST_DIR"
TEST_ROOT="$(pwd)"
ROOT_STATE_DIR="$TEST_ROOT/state"
TASK_DIR="$ROOT_STATE_DIR/tasks"
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
RESTART_JOURNAL_DIR="$ROOT_STATE_DIR/restart-journals"
LOCK_DIR="$ROOT_STATE_DIR/locks"
LBHOMEDIR="$TEST_ROOT/loxberry"
LBP_BINDIR="$TEST_ROOT/bin"
mkdir -p "$TASK_DIR" "$TASK_LOG_DIR" "$RESTART_JOURNAL_DIR" "$LOCK_DIR" "$TEST_ROOT/target"
require_root_for_write() { :; }
require_root_permission_ack() { :; }
require_backup_id() { :; }
process_start_ticks() { if [ "${1:-0}" -gt 1 ]; then printf '123\n'; fi; }
task_process_is_current() { return 1; }
acquire_operation_lock() { [ "${BUSY:-false}" != true ]; }
acquire_backup_lock() { :; }
recover_restart_journals() { :; }
backup_root() { printf '%s\n' "$TEST_ROOT/target"; }
strict_child_path() { printf '%s\n' "$2"; }
verify_backup_target() { :; }
protected_systemd_service() { return 1; }
run_hook() { :; }
notify_hostbackup() { :; }
timeout() { shift; "$@"; }
systemctl() {
  case "$1" in
    is-active) [ -f "$TEST_ROOT/active-$3" ] ;;
    stop)
      grep -q '"phase":"intended"' "$RESTART_JOURNAL_DIR/backup-test.log/journal.json" || return 88
      printf 'stop %s\n' "$2" >> "$TEST_ROOT/service-calls"
      rm -f -- "$TEST_ROOT/active-$2"
      ;;
    start)
      printf 'start %s\n' "$2" >> "$TEST_ROOT/service-calls"
      [ "${RESTART_FAIL:-false}" != true ] || return 1
      : > "$TEST_ROOT/active-$2"
      ;;
    *) return 99 ;;
  esac
}
docker() {
  case "$1" in
    ps) : ;;
    inspect)
      case "$3" in
        '{{.Id}}') echo abc123 ;;
        '{{.State.Running}}') [ ! -f "$TEST_ROOT/docker-active" ] || { echo true; return 0; }; echo false ;;
      esac ;;
    stop)
      grep -q '"phase":"intended"' "$RESTART_JOURNAL_DIR/backup-test.log/journal.json" || return 88
      echo docker-stop >> "$TEST_ROOT/service-calls"
      rm -f -- "$TEST_ROOT/docker-active" ;;
    start)
      echo docker-start >> "$TEST_ROOT/service-calls"
      [ "${RESTART_FAIL:-false}" != true ] || return 1
      : > "$TEST_ROOT/docker-active" ;;
    *) return 99 ;;
  esac
}
'''

PREFLIGHT_MOCKS = r'''
json_get_string() {
  case "$1" in
    backup_mode) echo "${TEST_BACKUP_MODE:-snapshot}" ;;
    schedule_mode) echo "${TEST_SCHEDULE_MODE:-daily}" ;;
    schedule_time) echo 02:00 ;;
    schedule_weekday) echo 0 ;;
    schedule_monthday) date '+%-d' ;;
  esac
}
json_get_bool() { echo true; }
json_get_array_lines() {
  case "$1" in
    schedule_weekdays) echo 0 ;;
    schedule_monthdays) date '+%-d' ;;
    schedule_months) echo '*' ;;
  esac
}
df() {
  echo 'Filesystem Total Used Available Percent Mount'
  if [ "$1" = -Pi ]; then
    printf 'mock 999999 1 %s 1 /fixture\n' "${FREE_INODES:-999998}"
  else
    printf 'mock 999999 1 %s 1 /fixture\n' "${FREE_MB:-4000}"
  fi
}
metadata_mode() { echo native-strict; }
metadata_capability_probe() { :; }
current_mount_value() { echo ext4; }
latest_complete_backup() { echo "${REFERENCE:-}"; }
latest_sized_complete_backup() { [ "${NO_ESTIMATE:-false}" = true ] || echo "$TEST_ROOT/historical"; }
backup_excludes() { echo /proc; }
rsync() { echo forbidden-copy >> "$TEST_ROOT/copy-called"; return 99; }
selected_docker_stop_count() { echo 0; }
mkdir -p "$TEST_ROOT/historical"
printf '{"size_bytes":10737418240}\n' > "$TEST_ROOT/historical/manifest.json"
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required for shell behavior tests")
class RuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-runtime-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_shell(self, script, names=(), env=None, expected=0):
        windows_setup = 'mkdir() { if [ "${1:-}" = -m ]; then shift 2; fi; command mkdir "$@"; }\n' if os.name == "nt" else ""
        source = SETUP + "\n" + windows_setup + "\n".join(function(n) for n in (*COMMON_FUNCTIONS, *names)) + "\n" + script
        result = subprocess.run(
            [BASH, "-s"], input=source, text=True, encoding="utf-8", capture_output=True,
            env={**os.environ, "RUNTIME_TEST_DIR": self.root.as_posix(), **(env or {})},
            # Journal fixtures spawn many real Bash/Perl processes; Windows
            # process startup under concurrent validation can exceed 30 seconds.
            # Keep a finite bound without altering any production timeout.
            timeout=90 if os.name == "nt" else 60, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_baseline_comparison_rejects_insufficient_space(self):
        for mode in ("snapshot", "full"):
            with self.subTest(mode=mode):
                result = self.run_shell(PREFLIGHT_MOCKS + '\npreflight_backup\n', ("baseline_space_requirement_mb", "preflight_backup"), {"TEST_BACKUP_MODE": mode})
                data = json.loads(result.stdout)
                self.assertEqual(data["status"], "error")
                self.assertEqual(data["baseline_estimate_mb"], 10240)
                self.assertEqual(data["baseline_required_mb"], 12288)

    def test_preflight_without_history_explains_estimate_limit(self):
        result = self.run_shell(PREFLIGHT_MOCKS + '\npreflight_backup\n', ("baseline_space_requirement_mb", "preflight_backup"), {"NO_ESTIMATE": "true"})
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(any("keine verlaessliche Groessenschaetzung" in item for item in data["notices"]))
        self.assertTrue(any("Quoten" in item for item in data["notices"]))

    def test_zero_inodes_is_a_real_error(self):
        result = self.run_shell(PREFLIGHT_MOCKS + '\npreflight_backup\n', ("baseline_space_requirement_mb", "preflight_backup"), {"FREE_MB": "20000", "FREE_INODES": "0"})
        self.assertEqual(json.loads(result.stdout)["status"], "error")

    def test_full_preflight_stops_worker_before_target_and_services(self):
        result = self.run_shell(PREFLIGHT_MOCKS + r'''
stop_backup_targets() { echo forbidden-stop > "$TEST_ROOT/stop-called"; return 99; }
create_backup test
''', ("baseline_space_requirement_mb", "preflight_backup", "create_backup"), expected=17)
        self.assertFalse((self.root / "stop-called").exists())
        self.assertFalse((self.root / "copy-called").exists())
        self.assertFalse((self.root / "target/test").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["phase"], "preflight_error")

    def test_backup_errexit_recovers_after_function_locals_unwind(self):
        self.run_shell(PREFLIGHT_MOCKS + r'''
FREE_MB=20000
write_backup_marker() { :; }
write_manifest() { printf '{"status":"%s","size_bytes":0,"files_count":0,"started_at":"fixture"}\n' "$3" > "$1/manifest.json"; }
stop_backup_targets() { restart_journal_update "$1" intended systemd demo.service; return 33; }
create_backup test
''', (*JOURNAL_FUNCTIONS, "baseline_space_requirement_mb", "preflight_backup", "manifest_started_at", "create_backup"), expected=33)
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        state = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit_status"], 33)

    def test_export_errexit_cleans_only_temporary_files_and_preserves_status(self):
        self.run_shell(r'''
mkdir -p "$TEST_ROOT/target/test/rootfs"
printf '{"status":"complete"}' > "$TEST_ROOT/target/test/manifest.json"
printf '{"status":"ok"}' > "$TEST_ROOT/target/test/backup-validation.json"
printf old-export > "$TEST_ROOT/target/test.tar.gz"
safe_backup_target() { printf '%s\n' "$TEST_ROOT/target/test"; }
flock() { :; }
tar_metadata_options() { :; }
run_with_heartbeat() { printf partial > "$TEST_ROOT/target/test.tar.gz.tmp.$$"; }
tar() { :; }
sha256sum() { return 32; }
export_backup test
''', ("export_cleanup_on_exit", "export_backup"), expected=32)
        self.assertEqual((self.root / "target/test.tar.gz").read_text(), "old-export")
        self.assertEqual(list((self.root / "target").glob("*.tmp.*")), [])
        state = json.loads((self.root / "state/tasks/export-test.log.json").read_text())
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit_status"], 32)

    def test_import_validation_failure_retains_archive_in_quarantine(self):
        self.run_shell(r'''
archive="$TEST_ROOT/incoming.tar.gz"
printf invalid > "$archive"
HOSTBACKUP_IMPORT_CLEANUP=1
HOSTBACKUP_TASK_ID=import-test.log
json_get_number() { echo 1024; }
validate_import_archive() { return 31; }
quarantine_import_archive() { mv -- "$1" "$TEST_ROOT/quarantine.tar.gz"; }
import_backup "$archive"
''', ("import_cleanup_on_exit", "install_import_cleanup_trap", "import_backup"), expected=31)
        self.assertFalse((self.root / "incoming.tar.gz").exists())
        self.assertEqual((self.root / "quarantine.tar.gz").read_text(), "invalid")
        state = json.loads((self.root / "state/tasks/import-test.log.json").read_text())
        self.assertEqual(state["exit_status"], 31)

    def test_fast_worker_result_cannot_be_overwritten_by_late_pid_registration(self):
        self.run_shell(r'''
definition="$(declare -f task_state_write)"
eval "${definition/task_state_write/actual_task_state_write}"
task_state_write() {
  if [ "$2:$3" = running:launched ]; then
    local attempt
    for attempt in {1..100}; do
      [ -e "$TEST_ROOT/worker-finished" ] && break
      sleep .02
    done
    [ -e "$TEST_ROOT/worker-finished" ] || return 91
  fi
  actual_task_state_write "$@"
}
nohup() { "$@"; }
setsid() { "$@"; }
fast_worker() {
  actual_task_state_write backup-fast.log finished complete "$TASK_LOG_DIR/backup-fast.log" "$BASHPID" 0
  : > "$TEST_ROOT/worker-finished"
}
launch_background backup-fast.log "$TASK_LOG_DIR/backup-fast.log" fast_worker
''', ("launch_background",))
        state = json.loads((self.root / "state/tasks/backup-fast.log.json").read_text())
        self.assertEqual(state["state"], "finished")
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(state["exit_status"], 0)

    def test_all_schedules_share_warning_error_and_busy_behavior(self):
        for mode in ("daily", "weekly", "monthly"):
            for status, busy, code, phase in (("ok", False, 0, "launched"), ("warning", False, 0, "launched"), ("error", False, 17, "preflight_error"), ("ok", True, 5, "busy")):
                with self.subTest(mode=mode, status=status, busy=busy):
                    result = self.run_shell(PREFLIGHT_MOCKS + r'''
preflight_backup() { printf '{"status":"%s","warnings":[]}\n' "$TEST_STATUS"; }
launch_background() { task_state_write "$1" running launched "$2" 4242 ''; echo 4242; }
schedule_run
''', ("start_backup", "schedule_run"), {"TEST_SCHEDULE_MODE": mode, "TEST_STATUS": status, "BUSY": str(busy).lower()}, expected=code)
                    tasks = list((self.root / "state/tasks").glob("*.json"))
                    latest = max(tasks, key=lambda p: p.stat().st_mtime_ns)
                    self.assertEqual(json.loads(latest.read_text())["phase"], phase)

    def test_cron_routes_every_schedule_through_scheduler(self):
        install = function("install_schedule").replace('local cron_file="/etc/cron.d/loxberryhostbackup"', 'local cron_file="$TEST_ROOT/cron.txt"')
        for mode in ("daily", "weekly", "monthly"):
            with self.subTest(mode=mode):
                self.run_shell(PREFLIGHT_MOCKS + '\n' + install + '\ninstall_schedule\n', env={"TEST_SCHEDULE_MODE": mode})
                self.assertIn("hostbackup.sh schedule-run", (self.root / "cron.txt").read_text())

    def test_service_stop_is_preceded_by_durable_intent(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
: > "$TEST_ROOT/active-demo.service"
printf 'systemd\tdemo.service\n' > "$TEST_ROOT/selected.tsv"
stop_selected_systemd_targets "$state_dir" "$TEST_ROOT/selected.tsv"
''', JOURNAL_FUNCTIONS)
        journal = json.loads((self.root / "state/restart-journals/backup-test.log/journal.json").read_text())
        self.assertEqual(journal["entries"][0]["phase"], "stopped")
        self.assertEqual((self.root / "service-calls").read_text().strip(), "stop demo.service")

    def test_journal_write_failure_prevents_service_stop(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
: > "$TEST_ROOT/active-demo.service"
printf 'systemd\tdemo.service\n' > "$TEST_ROOT/selected.tsv"
restart_journal_update() { return 20; }
stop_selected_systemd_targets "$state_dir" "$TEST_ROOT/selected.tsv"
''', JOURNAL_FUNCTIONS, expected=20)
        self.assertFalse((self.root / "service-calls").exists())
        self.assertTrue((self.root / "active-demo.service").exists())

    def test_docker_stop_is_preceded_by_durable_intent(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
: > "$TEST_ROOT/docker-active"
printf 'docker\tdemo\n' > "$TEST_ROOT/selected.tsv"
stop_selected_docker_targets "$state_dir" "$TEST_ROOT/selected.tsv"
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''', JOURNAL_FUNCTIONS)
        self.assertTrue((self.root / "docker-active").exists())
        self.assertEqual((self.root / "service-calls").read_text().splitlines(), ["docker-stop", "docker-start"])

    def test_cleanup_recovers_with_backup_medium_missing(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd demo.service
restart_journal_update "$state_dir" stopped systemd demo.service
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
backup_cleanup_on_exit 11 "$TEST_ROOT/vanished-medium/backup" "$log_file" false '' backup-test.log "$state_dir"
''', JOURNAL_FUNCTIONS)
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "failed")

    def test_failed_restart_is_retained_and_retried_after_new_process(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd demo.service
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
backup_cleanup_on_exit 143 "$TEST_ROOT/missing" "$log_file" false '' backup-test.log "$state_dir"
''', JOURNAL_FUNCTIONS, {"RESTART_FAIL": "true"}, expected=1)
        self.assertTrue((self.root / "state/restart-journals/backup-test.log/journal.json").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["phase"], "cleanup_failed")
        self.run_shell('recover_restart_journals\n', JOURNAL_FUNCTIONS)
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["phase"], "recovered_after_interruption")

    def test_term_runs_local_recovery_trap(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd demo.service
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
trap 'backup_cleanup_on_exit "$?" "$TEST_ROOT/missing" "$log_file" false "" backup-test.log "$state_dir"' EXIT
trap 'exit 143' TERM
kill -TERM "$BASHPID"
''', JOURNAL_FUNCTIONS, expected=143)
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_late_stop_preserves_completed_backup(self):
        self.run_shell(r'''
mkdir -p "$TEST_ROOT/target/test"
printf '{"status":"complete"}\n' > "$TEST_ROOT/target/test/manifest.json"
task_state_write backup-test.log finished complete "$TASK_LOG_DIR/backup-test.log" 0 0
write_manifest() { echo forbidden-manifest-write > "$TEST_ROOT/changed"; }
stop_backup test
''', (*JOURNAL_FUNCTIONS, "stop_backup"))
        self.assertFalse((self.root / "changed").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "finished")

    def test_signal_after_manifest_finalization_preserves_success(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
mkdir -p "$TEST_ROOT/target/test"
printf '{"status":"complete"}\n' > "$TEST_ROOT/target/test/manifest.json"
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
backup_cleanup_on_exit 143 "$TEST_ROOT/target/test" "$log_file" true '' backup-test.log "$state_dir"
''', JOURNAL_FUNCTIONS)
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "finished")
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "complete")

    def test_stop_rereads_completion_after_acquiring_lock(self):
        self.run_shell(r'''
mkdir -p "$TEST_ROOT/target/test"
printf '{"status":"running"}\n' > "$TEST_ROOT/target/test/manifest.json"
task_state_write backup-test.log running copying "$TASK_LOG_DIR/backup-test.log" 0 ''
acquire_operation_lock() {
  printf '{"status":"complete"}\n' > "$TEST_ROOT/target/test/manifest.json"
  task_state_write backup-test.log finished complete "$TASK_LOG_DIR/backup-test.log" 0 0
}
write_manifest() { echo forbidden-manifest-write > "$TEST_ROOT/changed"; }
stop_backup test
''', (*JOURNAL_FUNCTIONS, "stop_backup"))
        self.assertFalse((self.root / "changed").exists())
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "finished")

    def test_reference_hardlinks_distinguish_source_aliases(self):
        self.run_shell(r'''
mkdir -p "$TEST_ROOT/snapshot" "$TEST_ROOT/reference"
printf payload > "$TEST_ROOT/snapshot/source"
ln "$TEST_ROOT/snapshot/source" "$TEST_ROOT/snapshot/alias"
printf unrelated > "$TEST_ROOT/reference/source"
printf unrelated > "$TEST_ROOT/reference/alias"
snapshot_reference_stats "$TEST_ROOT/snapshot" "$TEST_ROOT/reference" > "$TEST_ROOT/stats.json"
''', ("snapshot_reference_stats",))
        data = json.loads((self.root / "stats.json").read_text())
        self.assertEqual(data["reference_reused_files"], 0)
        self.assertEqual(data["files_with_multiple_links"], 2)
        self.assertEqual(data["intra_snapshot_aliases"], 1)

    def test_reference_hardlinks_require_same_path_device_and_inode(self):
        self.run_shell(r'''
mkdir -p "$TEST_ROOT/snapshot" "$TEST_ROOT/reference"
printf payload > "$TEST_ROOT/reference/same"
ln "$TEST_ROOT/reference/same" "$TEST_ROOT/snapshot/same"
printf replacement > "$TEST_ROOT/snapshot/changed"
printf previous > "$TEST_ROOT/reference/changed"
snapshot_reference_stats "$TEST_ROOT/snapshot" "$TEST_ROOT/reference" > "$TEST_ROOT/stats.json"
''', ("snapshot_reference_stats",))
        data = json.loads((self.root / "stats.json").read_text())
        self.assertEqual(data["reference_reused_files"], 1)
        self.assertEqual(data["files_checked"], 2)

    @unittest.skipUnless(sys.platform == "linux", "Real metadata probe requires a Linux filesystem")
    def test_real_probe_roundtrip_for_every_profile(self):
        missing = [name for name in ("rsync", "tar", "setfacl", "getfacl", "setfattr", "getfattr", "setcap", "getcap") if not shutil.which(name)]
        if missing:
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Linux metadata test dependencies missing: " + ", ".join(missing))
            self.skipTest("Linux metadata test dependencies missing: " + ", ".join(missing))
        for mode in ("native-strict", "network-compatible", "fake-super", "portable-archive"):
            with self.subTest(mode=mode):
                result = self.run_shell(r'''
metadata_capability_probe "$TEST_ROOT/target" "$TEST_METADATA_MODE"
printf '%s\n' "$METADATA_PROBE_MESSAGE"
''', ("rsync_metadata_options", "rsync_destination", "tar_metadata_options", "metadata_capability_probe"), {"TEST_METADATA_MODE": mode})
                self.assertIn("UID/GID", result.stdout)
                self.assertIn("ACL-Werte bestaetigt", result.stdout)
                if mode != "network-compatible":
                    self.assertIn("xattr-Werte bestaetigt", result.stdout)
                if os.geteuid() == 0 and mode != "network-compatible":
                    self.assertIn("File Capabilities bestaetigt", result.stdout)


if __name__ == "__main__":
    unittest.main()
