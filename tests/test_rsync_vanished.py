"""Historical rsync-24 classifier and current validation/worker regressions.

All source/target data and commands are confined to temporary fixtures. No real
rsync, service, Docker command, host-root backup, or NAS access is performed.
"""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import test_runtime_safety as runtime


HELPER = runtime.ROOT / "bin/hostbackup-copy-diagnostics.py"
SUMMARY = "rsync warning: some files vanished before they could be transferred (code 24) at main.c(1394) [sender=3.5.0]"
RELATIVE_LOGS = (
    "plugins/miniserverbackup-ng/20261019_073001_342_Miniserverbackup NG CronJob.log",
    "plugins/miniserverbackup-ng/20261019_080001_698_Miniserverbackup NG CronJob.log",
    "plugins/stats4lox/grabber_loxberry.log",
    "plugins/stats4lox/grabber_loxone.log",
    "plugins/stats4lox/grabber_miniserver.log",
    "system_tmpfs/20261019_081301_649_Log Maintenance.log",
    "system_tmpfs/20261019_081301_862_Log Maintenance.log",
)


def load_helper():
    specification = importlib.util.spec_from_file_location("hostbackup_copy_diagnostics", HELPER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def fixture_logs(home):
    paths = [home / "log" / prefix / name for prefix in ("", "ramlog/log") for name in RELATIVE_LOGS]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    return paths


def diagnostic(paths, summary=SUMMARY):
    return ("".join(f'file has vanished: "{path}"\n' for path in paths) + summary + "\n").encode()


@unittest.skipUnless(os.name == "posix", "Production classifier deliberately requires real absolute POSIX paths")
class RsyncVanishedClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hostbackup-vanished-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "loxberry"
        self.paths = fixture_logs(self.home)
        self.stderr = self.root / "rsync-stderr.log"

    def analyze(self, data=None, code=24, accepted=False, home=None):
        self.stderr.write_bytes(diagnostic([self.paths[0].as_posix()]) if data is None else data)
        result = self.helper.analyze(self.stderr, code, home or self.home)
        self.assertIs(result["accepted"], accepted, result)
        self.assertIsInstance(result["reason"], str)
        self.assertTrue(result["reason"])
        self.assertIsInstance(result["vanished_count"], int)
        return result

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"Creating a fixture symlink is unavailable: {exc}")

    def test_fourteen_reported_log_paths_are_accepted_without_broad_directory_exclusion(self):
        result = self.analyze(diagnostic([path.as_posix() for path in self.paths]), accepted=True)
        self.assertEqual(result["vanished_count"], 14)

    def test_supported_rsync_summary_roles_are_accepted(self):
        for role in ("sender", "receiver", "generator"):
            with self.subTest(role=role):
                self.analyze(diagnostic([self.paths[0].as_posix()], SUMMARY.replace("sender=", role + "=")), accepted=True)

    def test_regular_leaf_recreated_by_log_rotation_is_allowed(self):
        self.paths[0].write_text("new current log", encoding="utf-8")
        self.analyze(accepted=True)

    def test_unknown_critical_and_similarly_named_paths_are_not_accepted(self):
        paths = (self.home / "config/plugins/stats4lox/config.json", self.home / "data/plugins/stats4lox/data.log",
                 self.home / "log/plugins/unknown/backup.log", self.home / "log/plugins/stats4lox/database.log",
                 self.home / "log/plugins/stats4lox/grabber_loxberry.log.1",
                 self.home / "log/plugins/miniserverbackup-ng/invalid_Miniserverbackup NG CronJob.log",
                 self.home / "log/system_tmpfs/20261019_081301_649_Other Job.log",
                 self.root / "loxberry-other/log/plugins/stats4lox/grabber_loxberry.log")
        for path in paths:
            with self.subTest(path=path):
                path.parent.mkdir(parents=True, exist_ok=True)
                self.analyze(diagnostic([path.as_posix()]))

    def test_one_unknown_file_among_known_logs_keeps_warning(self):
        self.analyze(diagnostic([self.paths[0].as_posix(), "/etc/important.conf", self.paths[1].as_posix()]))

    def test_paths_are_never_normalized_decoded_or_treated_as_shell_input(self):
        ordinary = self.paths[2].as_posix()
        invalid = (ordinary.replace("/plugins/", "/plugins/../plugins/"), ordinary.replace("/plugins/", "//plugins/"),
                   ordinary.replace("/plugins/", "/./plugins/"), ordinary + "/", "relative/grabber_loxberry.log",
                   ordinary.replace("stats4lox", r"stats4l\157x"), ordinary + '";touch forbidden', ordinary + "\t",
                   ordinary + "\r", ordinary + "\x00")
        for path in invalid:
            with self.subTest(path=path):
                self.analyze(diagnostic([path]))
        self.assertFalse((self.root / "forbidden").exists())

    def test_only_exact_complete_diagnostics_are_accepted(self):
        good = diagnostic([self.paths[0].as_posix()])
        cases = (b"", (SUMMARY + "\n").encode(), good[:-1], good.replace(b"\n", b"\r\n"), b"\xff\n" + good,
                 b"\x00" + good, b"\x1b[0m" + good, b"unexpected diagnostic\n" + good,
                 b"rsync: permission denied\n" + good, good + b"extra diagnostic\n", good + b"\n",
                 good + (SUMMARY + "\n").encode(), good.replace(b"file has vanished:", b"file has vanished :"),
                 good.replace(b"(code 24)", b"(code 23)"), good.replace(b"[sender=3.5.0]", b"[unknown=3.5.0]"),
                 good.replace(b'"\nrsync warning', b'\nrsync warning'),
                 (SUMMARY + "\n").encode() + good.split(b"\n", 1)[0] + b"\n")
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.analyze(data)

    def test_non_24_copy_status_is_never_downgraded(self):
        for code in (0, 1, 12, 18, 23, 30, 255, -1):
            with self.subTest(code=code):
                self.analyze(code=code)

    def test_missing_parent_is_not_considered_safe(self):
        self.paths[0].parent.rmdir()
        self.analyze()

    def test_symlink_leaf_is_not_considered_safe(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        self.symlink(self.paths[0], outside)
        self.analyze()

    def test_directory_leaf_is_not_considered_safe(self):
        self.paths[0].mkdir()
        self.analyze()

    def test_symlink_log_parent_is_not_considered_safe(self):
        original = self.paths[0].parent
        relocated = self.root / "outside-logs"
        original.rename(relocated)
        self.symlink(original, relocated, directory=True)
        self.analyze()

    def test_symlink_home_and_home_ancestor_are_not_considered_safe(self):
        alias = self.root / "alias"
        self.symlink(alias, self.home, directory=True)
        alias_path = alias / "log" / RELATIVE_LOGS[0]
        self.analyze(diagnostic([alias_path.as_posix()]), home=alias)
        parent_alias = self.root / "parent-alias"
        self.symlink(parent_alias, self.root, directory=True)
        aliased_home = parent_alias / "loxberry"
        self.analyze(diagnostic([(aliased_home / "log" / RELATIVE_LOGS[0]).as_posix()]), home=aliased_home)

    def test_missing_unreadable_shape_and_oversized_diagnostic_fail_closed(self):
        result = self.helper.analyze(self.stderr, 24, self.home)
        self.assertFalse(result["accepted"], result)
        self.stderr.mkdir()
        result = self.helper.analyze(self.stderr, 24, self.home)
        self.assertFalse(result["accepted"], result)
        self.stderr.rmdir()
        self.analyze(b"x" * (1024 * 1024 + 1))

    def test_symlink_and_fifo_diagnostics_are_rejected_without_following_or_waiting(self):
        real = self.root / "real-stderr.log"
        real.write_bytes(diagnostic([self.paths[0].as_posix()]))
        self.symlink(self.stderr, real)
        self.assertFalse(self.helper.analyze(self.stderr, 24, self.home)["accepted"])
        self.stderr.unlink()
        os.mkfifo(self.stderr)
        self.assertFalse(self.helper.analyze(self.stderr, 24, self.home)["accepted"])

    def test_vanished_count_bound_is_enforced(self):
        path = self.paths[2].as_posix()
        result = self.analyze(diagnostic([path] * 4096), accepted=True)
        self.assertEqual(result["vanished_count"], 4096)
        self.analyze(diagnostic([path] * 4097))

    def test_cli_returns_machine_receipt_and_success_only_for_accepted_logs(self):
        for accepted, data in ((True, diagnostic([self.paths[0].as_posix()])),
                               (False, diagnostic(["/etc/important.conf"]))):
            with self.subTest(accepted=accepted):
                self.stderr.write_bytes(data)
                result = subprocess.run([sys.executable, str(HELPER), "--stderr", str(self.stderr),
                                         "--exit-code", "24", "--loxberry-home", str(self.home)],
                                        text=True, capture_output=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0 if accepted else 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["accepted"], accepted)
                self.assertEqual(result.stderr, "")


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash/Perl required")
class RsyncVanishedValidationTests(unittest.TestCase):
    run_shell = runtime.RuntimeSafetyTests.run_shell
    setUp = runtime.RuntimeSafetyTests.setUp

    def validate(self, mode="native-strict", backup_mode="full", code=24, known=False, defect="", expected=0):
        script = r'''
metadata_mode() { printf '%s\n' "$PROFILE"; }
snapshot_reference_stats() { printf '%s\n' '{"reference_reused_files":1,"files_checked":1,"intra_snapshot_aliases":0}'; }
mkdir -p "$TEST_ROOT/target/rootfs/etc" "$TEST_ROOT/target/rootfs/opt/loxberry" "$TEST_ROOT/target/rootfs/var/lib" "$TEST_ROOT/previous/rootfs"
printf '{}' > "$TEST_ROOT/target/manifest.json"
size=200000000; files=200
case "$DEFECT" in
  etc) rmdir "$TEST_ROOT/target/rootfs/etc" ;;
  varlib) rmdir "$TEST_ROOT/target/rootfs/var/lib" ;;
  size) size=0 ;;
  files) files=0 ;;
esac
validate_completed_backup "$TEST_ROOT/target" "$BACKUP_MODE" "$TEST_ROOT/previous" "$size" "$files" "$COPY_CODE" "$KNOWN"
'''
        self.run_shell(script, ("validate_completed_backup",),
                       {"PROFILE": mode, "BACKUP_MODE": backup_mode, "COPY_CODE": str(code),
                        "KNOWN": str(known).lower(), "DEFECT": defect}, expected=expected)
        return json.loads((self.root / "target/backup-validation.json").read_bytes())

    def test_known_runtime_logs_are_information_for_all_file_copy_profiles_and_modes(self):
        for profile in ("native-strict", "network-compatible", "fake-super"):
            for mode in ("full", "snapshot"):
                with self.subTest(profile=profile, mode=mode):
                    data = self.validate(mode=profile, backup_mode=mode, known=True)
                    self.assertEqual(data["status"], "ok")
                    checks = {row["name"]: row for row in data["checks"]}
                    self.assertTrue(checks["Quelldateien erfasst"]["ok"])
                    self.assertTrue(checks["Metadaten-Fidelitaet"]["ok"])

    def test_unknown_vanished_files_warn_separately_from_metadata(self):
        for profile in ("native-strict", "network-compatible", "fake-super"):
            with self.subTest(profile=profile):
                data = self.validate(mode=profile, expected=1)
                checks = {row["name"]: row for row in data["checks"]}
                self.assertEqual(data["status"], "warning")
                self.assertFalse(checks["Quelldateien erfasst"]["ok"])
                self.assertTrue(checks["Metadaten-Fidelitaet"]["ok"])

    def test_known_runtime_logs_never_hide_structural_or_plausibility_failures(self):
        for defect, expected, status in (("etc", 2, "error"), ("varlib", 1, "warning"),
                                         ("size", 1, "warning"), ("files", 1, "warning")):
            with self.subTest(defect=defect):
                self.assertEqual(self.validate(known=True, defect=defect, expected=expected)["status"], status)

    def test_portable_copy_warning_and_success_keep_existing_meaning(self):
        self.assertEqual(self.validate(mode="portable-archive", expected=1)["status"], "warning")
        self.assertEqual(self.validate(mode="portable-archive", known=True, expected=1)["status"], "warning")
        self.assertEqual(self.validate(mode="portable-archive", code=0)["status"], "ok")

    def test_normal_zero_status_remains_ok_without_diagnostic_receipt(self):
        self.assertEqual(self.validate(code=0)["status"], "ok")


WORKER_FIXTURE = r'''
set -euo pipefail
umask 077
cd -- "$VANISHED_TEST_DIR"
TEST_ROOT="$(pwd)"
ROOT_STATE_DIR="$TEST_ROOT/state"
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
RESTART_JOURNAL_DIR="$ROOT_STATE_DIR/journals"
LBHOMEDIR="$VANISHED_TEST_DIR/loxberry"
LBP_BINDIR="$VANISHED_HELPER_DIR"
CONFIG_FILE="$TEST_ROOT/config.json"
EVENTS="$TEST_ROOT/events"
mkdir -p "$TASK_LOG_DIR" "$RESTART_JOURNAL_DIR" "$TEST_ROOT/target" "$TEST_ROOT/previous/rootfs"
event() { printf '%s\n' "$1" >> "$EVENTS"; }
require_root_for_write() { :; }
require_root_permission_ack() { :; }
require_backup_id() { [ "$1" = vanished-test ]; }
acquire_operation_lock() { :; }
acquire_backup_lock() { :; }
strict_child_path() { printf '%s\n' "$2"; }
backup_root() { printf '%s\n' "$TEST_ROOT/target"; }
verify_backup_target() { [ "$1" = "$TEST_ROOT/target" ]; }
json_get_string() { case "$1" in backup_mode) echo "$BACKUP_MODE" ;; esac; }
json_get_bool() { echo false; }
metadata_mode() { echo "$PROFILE"; }
portable_snapshot() { return 1; }
preflight_backup() { printf '%s\n' '{"status":"ok"}'; }
prepare_log_file() { : >> "$1"; }
write_backup_marker() { :; }
backup_excludes() { printf '%s\n' /proc /sys /dev /run /tmp; }
write_manifest() {
  event "manifest:$3"
  printf '{"backup_id":"%s","status":"%s","started_at":"fixture","size_bytes":%s,"files_count":%s}\n' "$2" "$3" "$6" "$7" > "$1/manifest.json"
}
manifest_field() { "$VANISHED_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$1" "$2"; }
manifest_started_at() { echo fixture; }
log() { printf '%s\n' "$*"; }
task_state_write() { event "task:$2:$3"; }
restart_journal_create() {
  mkdir -p "$RESTART_JOURNAL_DIR/$1"
  if [ "$CAPTURE_COLLISION" = true ]; then printf 'preserved existing capture\n' > "$RESTART_JOURNAL_DIR/$1/rsync-stderr.log"; fi
  printf '%s\n' "$RESTART_JOURNAL_DIR/$1"
}
restart_journal_finish() { event journal-finished; }
write_control_marker() { : > "$1"; }
run_hook() { :; }
notify_hostbackup() { event "notify:$1"; }
stop_backup_targets() { event services-stop; : > "$TEST_ROOT/services-stopped"; }
verify_stopped_docker_targets() { :; }
start_backup_targets_if_needed() { event services-start; : > "$TEST_ROOT/services-restarted"; }
source_info() { printf '{"status":"ok","selection":{"policy":"%s","overrides":{}}}\n' "$SELECTION"; }
rsync_live_options() { :; }
rsync_metadata_options() { :; }
rsync_destination() { printf '%s\n' "$2"; }
latest_complete_backup() { echo "$TEST_ROOT/previous"; }
snapshot_reference_stats() { printf '%s\n' '{"reference_reused_files":1,"files_checked":1,"intra_snapshot_aliases":0}'; }
calculate_size() { echo 200000000; }
calculate_files() { echo 200; }
prune_old_backups() {
  [ -e "$TEST_ROOT/services-restarted" ] && [ -f "$TEST_ROOT/target/vanished-test/backup-validation.json" ] || return 93
  event retention
}
rsync() {
  [ "${!#}" = "$TEST_ROOT/target/vanished-test/rootfs/" ] || return 94
  [ -f "$TEST_ROOT/services-stopped" ] && [ ! -f "$TEST_ROOT/services-restarted" ] || return 94
  if [ "$MUTATE_PUBLIC_EXCLUDES" = true ]; then
    printf '/etc\n' > "$TEST_ROOT/target/vanished-test/rsync-excludes.txt"
    local option private_excludes='' files='' from0=false no_recursive=false dirs=false
    for option in "$@"; do
      case "$option" in
        --exclude-from=*) private_excludes="${option#--exclude-from=}" ;;
        --files-from=*) files="${option#--files-from=}" ;;
        --from0) from0=true ;;
        --no-recursive) no_recursive=true ;;
        --dirs) dirs=true ;;
      esac
    done
    [ -z "$private_excludes" ] && [ "$from0:$no_recursive:$dirs" = true:true:true ] || return 94
    [ "$files" = "$RESTART_JOURNAL_DIR/backup-vanished-test.log/source-files.nul" ] || return 94
    cmp -- "$files" <(printf './etc/fixture.txt\0') || return 94
    [ "$(command cat "$RESTART_JOURNAL_DIR/backup-vanished-test.log/source-excludes.txt")" = $'/proc\n/sys\n/dev\n/run\n/tmp' ] || return 94
    event private-frozen-list-used
  fi
  event copy
  mkdir -p "$TEST_ROOT/target/vanished-test/rootfs/etc" "$TEST_ROOT/target/vanished-test/rootfs/opt/loxberry" "$TEST_ROOT/target/vanished-test/rootfs/var/lib"
  cp -- "$TEST_ROOT/source.txt" "$TEST_ROOT/target/vanished-test/rootfs/etc/fixture.txt"
  printf '\r1M 10%%\r2M 20%%\n'
  command cat -- "$TEST_ROOT/diagnostic.log" >&2
  return "$COPY_CODE"
}
# The only tar copy is a known fixture tree, never the production argument '/'.
tar() {
  if [ "${1:-}" = -tf ]; then command tar "$@"; return $?; fi
  [ "$PROFILE" = portable-archive ] || return 94
  event portable-copy
  command tar -C "$TEST_ROOT/portable-source" -cf "$TEST_ROOT/target/vanished-test/rootfs.tar" .
  return "$COPY_CODE"
}
tar_metadata_options() { :; }
timeout() {
  [ "$1:$2:$3" = '-k:2:15' ] || return 96
  event classifier-time-bound
  shift 3
  [ "$CLASSIFIER_TIMEOUT" != true ] || return 124
  "$@"
}
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-copy-diagnostics.py" ]; then
    event classifier
    [ "$HELPER_FAILURE" != true ] || return 70
    "$VANISHED_PYTHON" "$@"
  elif [ "${1:-}" = "$LBP_BINDIR/hostbackup-tar.py" ]; then
    shift
    local archive='' receipt='' state='' files='' report='' raw="$COPY_CODE"
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --archive) archive="$2" ;;
        --receipt) receipt="$2" ;;
        --state-dir) state="$2" ;;
        --files-from) files="$2" ;;
        --source-report) report="$2" ;;
        *) return 95 ;;
      esac
      shift 2
    done
    [ "$archive" = "$TEST_ROOT/target/vanished-test/rootfs.tar" ] || return 94
    [ "$state" = "$RESTART_JOURNAL_DIR/backup-vanished-test.log" ] || return 94
    [ "$files" = "$state/source-files.nul" ] && [ "$report" = "$state/source-selection.json" ] || return 94
    [ "$receipt" = "$state/tar-result.json" ] || return 94
    event portable-copy
    command tar -C "$TEST_ROOT/portable-source" -cf "$archive" . || return $?
    printf 'fixture TAR diagnostics\n' > "$state/tar-stderr.log"
    [ "$TAR_RECEIPT_MISSING" != true ] || return 18
    [ "$TAR_DIRECTORY_VERIFIED" != true ] || raw=1
    printf '{"raw_exit_status":%s,"effective_exit_status":%s}\n' "$raw" "$COPY_CODE" > "$receipt"
    printf 'fixture TAR diagnostics\n'
    return "$COPY_CODE"
  elif [ "${1:-}" = "$LBP_BINDIR/hostbackup-sources.py" ]; then
    case "${2:-}" in
      files)
        shift 2
        local private_excludes='' for_rsync=false
        while [ "$#" -gt 0 ]; do
          if [ "$1" = --excludes ]; then
            private_excludes="$2"
            [ "$private_excludes" = "$RESTART_JOURNAL_DIR/backup-vanished-test.log/source-excludes.txt" ] || return 94
            [ "$(command cat "$private_excludes")" = $'/proc\n/sys\n/dev\n/run\n/tmp' ] || return 94
          fi
          if [ "$1" = --report ]; then
            printf '%s\n' '{"status":"ok","selection":{"policy":"local","overrides":{}},"runtime_content_policy":{"version":1,"omitted_regular_files":1}}' > "$2"
          fi
          [ "$1" != --for-rsync ] || for_rsync=true
          shift
        done
        [ -n "$private_excludes" ] || return 94
        event private-source-excludes-used
        if [ "$for_rsync" = true ]; then printf './etc/fixture.txt\0'; else printf '.\0./etc/fixture.txt\0'; fi
        ;;
      verify)
        event source-verify
        shift 2
        while [ "$#" -gt 0 ]; do
          if [ "$1" = --verification-report ]; then
            printf '{"status":"%s","changed_paths":[]}\n' "$VERIFY_STATUS" > "$2"
            break
          fi
          shift
        done
        return "$VERIFY_STATUS"
        ;;
      *) event forbidden-python; return 95 ;;
    esac
  elif [ "${1:-}" = -c ]; then
    "$VANISHED_PYTHON" "$@"
  else
    event forbidden-python; return 95
  fi
}
cat() {
  if [ "$CAT_FAILURE" = true ] && [[ "${!#}" == */rsync-stderr.log ]]; then event simulated-stderr-read-failure; return 1; fi
  command cat "$@"
}
tee() {
  if [ "$TEE_COPY_FAILURE" = true ]; then
    local text
    text="$(command cat)"
    if [[ "$text" == *'1M 10%'* ]]; then event simulated-copy-tee-failure; return 1; fi
    printf '%s\n' "$text" | command tee "$@"
  else
    command tee "$@"
  fi
}
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash/Perl required")
class RsyncVanishedWorkerTests(unittest.TestCase):
    def worker(self, code=24, known=True, mode="full", profile="native-strict", verify=0, expected=0,
               malformed=False, capture_collision=False, tee_failure=False, cat_failure=False, helper_failure=False,
               classifier_timeout=False, mutate_public_excludes=False, tar_directory_verified=False,
               tar_receipt_missing=False):
        temporary = tempfile.TemporaryDirectory(prefix="hostbackup-vanished-worker-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        paths = fixture_logs(root / "loxberry")
        (root / "source.txt").write_text("only disposable data\n", encoding="utf-8")
        for name in ("etc", "opt/loxberry", "var/lib"):
            (root / "portable-source" / name).mkdir(parents=True)
        data = diagnostic([paths[0].as_posix() if known else "/etc/important.conf"])
        (root / "diagnostic.log").write_bytes(data[:-1] if malformed else data)
        script = WORKER_FIXTURE + "\n" + "\n".join(runtime.function(name) for name in
                    ("checked_source_info", "watchdog_guard_start", "watchdog_guard_check", "watchdog_guard_release",
                     "validate_completed_backup", "backup_cleanup_on_exit", "create_backup")) + "\ncreate_backup vanished-test\n"
        result = subprocess.run([runtime.BASH, "--noprofile", "--norc", "-s"], input=script,
                                text=True, encoding="utf-8", capture_output=True, check=False,
                                timeout=90 if os.name == "nt" else 60,
                                env={**os.environ, "VANISHED_TEST_DIR": root.as_posix(), "VANISHED_HELPER_DIR": HELPER.parent.as_posix(),
                                     "VANISHED_PYTHON": Path(sys.executable).as_posix(), "COPY_CODE": str(code),
                                     "BACKUP_MODE": mode, "PROFILE": profile, "VERIFY_STATUS": str(verify),
                                     "CAPTURE_COLLISION": str(capture_collision).lower(), "TEE_COPY_FAILURE": str(tee_failure).lower(),
                                     "CAT_FAILURE": str(cat_failure).lower(), "HELPER_FAILURE": str(helper_failure).lower(),
                                     "CLASSIFIER_TIMEOUT": str(classifier_timeout).lower(),
                                     "MUTATE_PUBLIC_EXCLUDES": str(mutate_public_excludes).lower(),
                                     "TAR_DIRECTORY_VERIFIED": str(tar_directory_verified).lower(),
                                     "TAR_RECEIPT_MISSING": str(tar_receipt_missing).lower(),
                                     "SELECTION": "local" if verify else "legacy"})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        events = (root / "events").read_text().splitlines()
        self.assertNotIn("forbidden-python", events)
        manifest = json.loads((root / "target/vanished-test/manifest.json").read_bytes())
        return root, result, events, manifest

    def test_worker_never_reclassifies_a_required_vanished_file_by_its_name(self):
        for mode, profile in (("full", "native-strict"), ("snapshot", "native-strict"),
                              ("full", "network-compatible"), ("snapshot", "network-compatible")):
            with self.subTest(mode=mode, profile=profile):
                root, result, events, manifest = self.worker(mode=mode, profile=profile)
                self.assertEqual(manifest["status"], "complete_with_warnings")
                self.assertNotIn("notify:failure", events)
                self.assertNotIn("classifier", events)
                self.assertLess(events.index("services-stop"), events.index("copy"))
                self.assertLess(events.index("copy"), events.index("services-start"))
                self.assertLess(events.index("services-start"), events.index("retention"))
                self.assertIn("Backup copy finished with status 24", result.stdout)
                self.assertEqual((root / "target/vanished-test/rootfs/etc/fixture.txt").read_bytes(), (root / "source.txt").read_bytes())
                capture = root / "state/journals/backup-vanished-test.log/rsync-stderr.log"
                self.assertEqual(capture.read_bytes(), (root / "diagnostic.log").read_bytes())
                self.assertNotIn(b"\r", capture.read_bytes(), "CR progress on stdout must not enter stderr evidence")
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(capture.stat().st_mode), 0o600)
                log = (root / "state/logs/backup-vanished-test.log").read_bytes()
                self.assertIn((root / "diagnostic.log").read_bytes(), log)
                receipt = json.loads((root / "target/vanished-test/copy-result.json").read_bytes())
                self.assertEqual(receipt, {"tool": "rsync", "copy_exit_status": 24,
                                          "source_verification_status": 0, "effective_status": 24})

    def test_unknown_or_incomplete_diagnostic_keeps_completed_warning(self):
        for known, malformed in ((False, False), (True, True)):
            with self.subTest(known=known, malformed=malformed):
                root, _, events, manifest = self.worker(known=known, malformed=malformed)
                self.assertEqual(manifest["status"], "complete_with_warnings")
                self.assertEqual(json.loads((root / "target/vanished-test/backup-validation.json").read_bytes())["status"], "warning")
                self.assertIn("services-start", events)
                self.assertIn("retention", events)

    def test_copy_error_23_is_failed_and_never_classified_as_harmless(self):
        _, _, events, manifest = self.worker(code=23, expected=23)
        self.assertEqual(manifest["status"], "failed")
        self.assertNotIn("classifier", events)
        self.assertIn("notify:failure", events)
        self.assertNotIn("notify:success", events)
        self.assertIn("services-start", events)
        self.assertNotIn("retention", events)

    def test_source_verification_failure_dominates_known_log_diagnostics(self):
        root, _, events, manifest = self.worker(verify=18, expected=18)
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("source-verify", events)
        self.assertIn("services-start", events)
        self.assertNotIn("retention", events)
        self.assertNotIn("notify:success", events)
        receipt = json.loads((root / "target/vanished-test/copy-result.json").read_bytes())
        self.assertEqual(receipt, {"tool": "rsync", "copy_exit_status": 24,
                                  "source_verification_status": 18, "effective_status": 18})

    def test_successful_copy_does_not_invoke_exception_classifier(self):
        _, _, events, manifest = self.worker(code=0)
        self.assertEqual(manifest["status"], "complete")
        self.assertNotIn("classifier", events)

    def test_public_nas_excludes_cannot_change_private_copy_boundaries(self):
        root, _, events, manifest = self.worker(code=0, mutate_public_excludes=True)
        self.assertEqual(manifest["status"], "complete")
        self.assertIn("private-source-excludes-used", events)
        self.assertIn("private-frozen-list-used", events)
        self.assertTrue((root / "target/vanished-test/rootfs/etc/fixture.txt").is_file())

    def test_diagnostic_capture_collision_fails_without_overwriting_prior_evidence(self):
        root, _, events, manifest = self.worker(capture_collision=True, expected=23)
        self.assertEqual(manifest["status"], "failed")
        self.assertNotIn("copy", events)
        self.assertNotIn("classifier", events)
        self.assertIn("services-start", events)
        self.assertIn("notify:failure", events)
        self.assertEqual((root / "state/journals/backup-vanished-test.log/rsync-stderr.log").read_text(),
                         "preserved existing capture\n")

    def test_copy_output_capture_failure_is_not_mistaken_for_harmless_exit_24(self):
        _, _, events, manifest = self.worker(tee_failure=True, expected=23)
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("simulated-copy-tee-failure", events)
        self.assertNotIn("classifier", events)
        self.assertIn("services-start", events)
        self.assertIn("notify:failure", events)

    def test_stderr_recording_failure_is_not_mistaken_for_harmless_exit_24(self):
        _, _, events, manifest = self.worker(cat_failure=True, expected=23)
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("simulated-stderr-read-failure", events)
        self.assertNotIn("classifier", events)
        self.assertIn("services-start", events)
        self.assertIn("notify:failure", events)

    def test_obsolete_classifier_failure_cannot_suppress_warning(self):
        _, _, events, manifest = self.worker(helper_failure=True)
        self.assertEqual(manifest["status"], "complete_with_warnings")
        self.assertNotIn("classifier", events)
        self.assertIn("services-start", events)
        self.assertIn("retention", events)

    def test_obsolete_classifier_timeout_is_not_part_of_current_worker(self):
        _, _, events, manifest = self.worker(classifier_timeout=True)
        self.assertEqual(manifest["status"], "complete_with_warnings")
        self.assertNotIn("classifier-time-bound", events)
        self.assertNotIn("classifier", events)
        self.assertIn("services-start", events)
        self.assertIn("retention", events)

    def test_portable_tar_does_not_use_rsync_log_exception(self):
        for code, status in ((0, "complete"), (24, "failed")):
            with self.subTest(code=code):
                root, _, events, manifest = self.worker(code=code, profile="portable-archive", expected=code)
                self.assertEqual(manifest["status"], status)
                self.assertIn("portable-copy", events)
                self.assertNotIn("classifier", events)
                self.assertEqual(json.loads((root / "target/vanished-test/copy-result.json").read_bytes())["tool"], "tar")

    def test_portable_verified_directory_result_keeps_raw_status_and_restarts_services(self):
        root, _, events, manifest = self.worker(code=0, profile="portable-archive", tar_directory_verified=True)
        self.assertEqual(manifest["status"], "complete")
        receipt = json.loads((root / "target/vanished-test/copy-result.json").read_bytes())
        self.assertEqual((receipt["tool"], receipt["copy_exit_status"], receipt["effective_status"]), ("tar", 1, 0))
        self.assertEqual(json.loads((root / "target/vanished-test/tar-result.json").read_bytes())["raw_exit_status"], 1)
        self.assertLess(events.index("portable-copy"), events.index("source-verify"))
        self.assertLess(events.index("source-verify"), events.index("services-start"))
        self.assertLess(events.index("services-start"), events.index("retention"))

    def test_portable_directory_receipt_cannot_override_changed_source_mount(self):
        root, _, events, manifest = self.worker(code=0, profile="portable-archive", verify=18,
                                               expected=18, tar_directory_verified=True)
        self.assertEqual(manifest["status"], "failed")
        receipt = json.loads((root / "target/vanished-test/copy-result.json").read_bytes())
        self.assertEqual((receipt["copy_exit_status"], receipt["source_verification_status"],
                          receipt["effective_status"]), (1, 18, 18))
        self.assertIn("services-start", events)
        self.assertNotIn("retention", events)

    def test_missing_tar_receipt_fails_and_retains_unrecorded_private_diagnostics(self):
        root, _, events, manifest = self.worker(code=0, profile="portable-archive",
                                               expected=23, tar_receipt_missing=True)
        self.assertEqual(manifest["status"], "failed")
        journal = root / "state/journals/backup-vanished-test.log"
        self.assertTrue((journal / "tar-stderr.log").is_file())
        self.assertFalse((journal / "tar-stderr.logged").exists())
        self.assertIn("services-start", events)
        self.assertNotIn("retention", events)


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash/Perl required")
class RsyncVanishedJournalCleanupTests(unittest.TestCase):
    run_shell = runtime.RuntimeSafetyTests.run_shell
    setUp = runtime.RuntimeSafetyTests.setUp
    functions = ("restart_journal_path_is_safe", "restart_journal_update", "restart_journal_create",
                 "restart_journal_finish", "restart_journal_archive")

    def test_actual_journal_finish_removes_private_capture_after_recovery(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'known captured diagnostics\n' > "$state_dir/rsync-stderr.log"
printf 'persisted public task log\nknown captured diagnostics\n' > "$TASK_LOG_DIR/backup-test.log"
write_control_marker "$state_dir/rsync-stderr.logged"
restart_journal_finish "$state_dir"
''', self.functions)
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual((self.root / "state/logs/backup-test.log").read_text(),
                         "persisted public task log\nknown captured diagnostics\n")

    def test_actual_interrupted_cleanup_recovers_diagnostics_not_yet_appended(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'diagnostics captured before TERM\n' > "$state_dir/rsync-stderr.log"
printf 'earlier task output\n' > "$TASK_LOG_DIR/backup-test.log"
backup_cleanup_on_exit 143 "$TEST_ROOT/missing-backup" "$TASK_LOG_DIR/backup-test.log" true '' backup-test.log "$state_dir"
''', (*self.functions, "backup_cleanup_on_exit"))
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        log = (self.root / "state/logs/backup-test.log").read_text()
        self.assertTrue(log.startswith("earlier task output\n"))
        self.assertIn("Recovered rsync diagnostics", log)
        self.assertEqual(log.count("diagnostics captured before TERM"), 1)
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_bytes())
        self.assertEqual((task["state"], task["phase"]), ("failed", "failed"))

    def test_interrupted_tar_recording_recovers_diagnostics_and_cleans_only_known_receipts(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'TAR diagnostics captured before TERM\n' > "$state_dir/tar-stderr.log"
printf '{"raw_exit_status":1,"effective_exit_status":1}\n' > "$state_dir/tar-result.json"
printf 'earlier task output\n' > "$TASK_LOG_DIR/backup-test.log"
backup_cleanup_on_exit 143 "$TEST_ROOT/missing-backup" "$TASK_LOG_DIR/backup-test.log" true '' backup-test.log "$state_dir"
''', (*self.functions, "backup_cleanup_on_exit"))
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        log = (self.root / "state/logs/backup-test.log").read_text()
        self.assertIn("Recovered tar diagnostics", log)
        self.assertEqual(log.count("TAR diagnostics captured before TERM"), 1)

    def test_failed_recovery_append_retains_capture_and_journal_for_later_process(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'must remain available for retry\n' > "$state_dir/rsync-stderr.log"
printf 'earlier task output\n' > "$TASK_LOG_DIR/backup-test.log"
cat() { return 1; }
restart_journal_finish "$state_dir"
''', self.functions, expected=20)
        directory = self.root / "state/restart-journals/backup-test.log"
        self.assertTrue((directory / "journal.json").is_file())
        self.assertEqual((directory / "rsync-stderr.log").read_text(), "must remain available for retry\n")
        self.assertFalse((directory / "rsync-stderr.logged").exists())
        self.run_shell('restart_journal_finish "$RESTART_JOURNAL_DIR/backup-test.log"\n', self.functions)
        self.assertFalse(directory.exists())
        log = (self.root / "state/logs/backup-test.log").read_text()
        self.assertTrue(log.startswith("earlier task output\n"))
        self.assertEqual(log.count("must remain available for retry"), 1)

    def test_log_preparation_failure_keeps_unrecorded_diagnostics(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'unrecorded diagnostics\n' > "$state_dir/rsync-stderr.log"
prepare_log_file() { return 1; }
restart_journal_finish "$state_dir"
''', self.functions, expected=20)
        directory = self.root / "state/restart-journals/backup-test.log"
        self.assertTrue((directory / "journal.json").is_file())
        self.assertEqual((directory / "rsync-stderr.log").read_text(), "unrecorded diagnostics\n")

    def test_actual_journal_finish_retains_capture_while_service_restart_is_pending(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd fixture.service
restart_journal_update "$state_dir" stopped systemd fixture.service
printf 'pending captured diagnostics\n' > "$state_dir/rsync-stderr.log"
restart_journal_finish "$state_dir"
''', self.functions, expected=20)
        directory = self.root / "state/restart-journals/backup-test.log"
        self.assertTrue((directory / "journal.json").is_file())
        self.assertEqual((directory / "rsync-stderr.log").read_text(), "pending captured diagnostics\n")

    @unittest.skipUnless(os.name == "posix", "Journal symlink behavior requires real POSIX symlinks")
    def test_actual_journal_finish_rejects_substituted_capture_link(self):
        self.run_shell(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf 'external evidence\n' > "$TEST_ROOT/external-evidence.log"
ln -s "$TEST_ROOT/external-evidence.log" "$state_dir/rsync-stderr.log"
restart_journal_finish "$state_dir"
''', self.functions, expected=20)
        directory = self.root / "state/restart-journals/backup-test.log"
        self.assertTrue((directory / "journal.json").is_file())
        self.assertTrue((directory / "rsync-stderr.log").is_symlink())
        self.assertEqual((self.root / "external-evidence.log").read_text(), "external evidence\n")


if __name__ == "__main__":
    unittest.main()
