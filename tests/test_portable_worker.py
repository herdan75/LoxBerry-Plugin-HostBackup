#!/usr/bin/env python3
"""Exercise the real portable shell worker using isolated orchestration doubles.

Only create_backup, portable_snapshot and its EXIT cleanup are extracted. The
backend entry point is never sourced. File selection/copy, services and target
registration are intercepted: no host-root enumeration, backup or restore runs.
Real repository/metadata/recovery tests live in test_repository/test_portable.
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash') or (r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else None)


def function(name):
    source = (ROOT / 'bin/hostbackup.sh').read_text(encoding='utf-8')
    match = re.search(rf'^{re.escape(name)}\(\) \{{\n.*?^\}}\n(?=\n)', source, re.M | re.S)
    if not match:
        raise AssertionError('Missing actual shell function: ' + name)
    return match.group(0)


FIXTURE = r'''
set -euo pipefail
umask 077
cd -- "$WORKER_TEST_DIR"
TEST_ROOT="$(pwd)"
ROOT_STATE_DIR="$TEST_ROOT/state"
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
RESTART_JOURNAL_DIR="$ROOT_STATE_DIR/journals"
LBP_BINDIR="$TEST_ROOT/never-executed-bin"
CONFIG_FILE="$TEST_ROOT/config.json"
EVENTS="$TEST_ROOT/events"
mkdir -p "$TASK_LOG_DIR" "$RESTART_JOURNAL_DIR" "$TEST_ROOT/target"
event() { printf '%s\n' "$1" >> "$EVENTS"; }
require_root_for_write() { :; }
require_root_permission_ack() { :; }
require_backup_id() { [ "$1" = portable-test ]; }
acquire_operation_lock() { :; }
acquire_backup_lock() { :; }
strict_child_path() { printf '%s\n' "$2"; }
backup_root() { printf '%s\n' "$TEST_ROOT/target"; }
verify_backup_target() { [ "$1" = "$TEST_ROOT/target" ]; }
json_get_string() {
  case "$1" in backup_mode) echo snapshot ;; metadata_mode) echo portable-archive ;; esac
}
json_get_bool() { echo false; }
metadata_mode() { echo portable-archive; }
preflight_backup() { printf '%s\n' '{"status":"ok"}'; }
prepare_log_file() { : >> "$1"; }
write_backup_marker() { printf '%s\n' "$2" > "$1/.loxberry-hostbackup-backup"; }
backup_excludes() { printf '%s\n' /proc /sys /dev /run /tmp; }
write_manifest() {
  event "manifest:$3"
  printf '{"backup_id":"%s","status":"%s","started_at":"fixture","size_bytes":%s,"files_count":%s}\n' \
    "$2" "$3" "$6" "$7" > "$1/manifest.json"
}
manifest_field() {
  "$WORKER_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$1" "$2"
}
manifest_started_at() { echo fixture; }
log() { printf '%s\n' "$*"; }
task_state_write() { event "task:$2:$3"; }
restart_journal_create() {
  mkdir -p "$RESTART_JOURNAL_DIR/$1"
  printf '%s\n' "$RESTART_JOURNAL_DIR/$1"
}
restart_journal_finish() { event journal-finished; }
write_control_marker() { : > "$1"; }
run_hook() { :; }
notify_hostbackup() { event "notify:$1"; }
stop_backup_targets() { event services-stop; : > "$TEST_ROOT/services-stopped"; }
start_backup_targets_if_needed() { event services-start; : > "$TEST_ROOT/services-restarted"; }
source_info() { printf '%s\n' '{"status":"ok","selection":{"policy":"legacy","overrides":{}}}'; }
rsync_live_options() { :; }
rsync_metadata_options() { :; }
calculate_size() { echo 4096; }
calculate_files() { echo 3; }
prune_old_backups() {
  [ -e "$TEST_ROOT/published" ] || return 93
  event retention
}
# Never run any real host copy command, even if worker dispatch regresses.
tar() { event forbidden-tar; return 94; }
rsync() { event forbidden-rsync; return 94; }
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-sources.py" ]; then
    shift
    local action="$1" report="" excludes="" sockets=false
    shift
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --report) report="$2"; shift 2 ;;
        --excludes) excludes="$2"; shift 2 ;;
        --omit-sockets) sockets=true; shift ;;
        --config) shift 2 ;;
        *) event unexpected-source-argument; return 95 ;;
      esac
    done
    [ "$report" = "$RESTART_JOURNAL_DIR/backup-portable-test.log/repository-controls/source-selection.json" ] || return 98
    case "$action" in
      files)
        [ "$sockets" = true ] || { event missing-socket-flag; return 96; }
        [ "$excludes" = "$RESTART_JOURNAL_DIR/backup-portable-test.log/repository-controls/rsync-excludes.txt" ] || return 98
        grep -Fxq /proc "$excludes" || return 98
        [ -e "$TEST_ROOT/services-stopped" ] || return 97
        event source-files-with-omit-sockets
        [ "${FILES_STATUS:-0}" = 0 ] || return "$FILES_STATUS"
        printf '%s\n' '{"omitted_runtime_sockets":{"count":1,"paths":["/var/lib/fixture.sock"]}}' > "$report"
        # Untrusted NAS-side controls may change but must never feed validation
        # or the later authenticated commit.
        printf '%s\n' /attacker-controlled-rule > "$TEST_ROOT/target/portable-test/rsync-excludes.txt"
        event nas-control-tampered
        printf '.\0etc/config\0opt/loxberry/config\0'
        ;;
      verify) event sources-verify; return "${VERIFY_STATUS:-0}" ;;
      *) event forbidden-source-action; return 95 ;;
    esac
  elif [ "${1:-}" = -c ]; then
    "$WORKER_PYTHON" "$@"
  else
    event forbidden-python-script
    return 95
  fi
}
repository_helper() {
  [ "$1" = backup ] || return 95
  [ -e "$TEST_ROOT/services-stopped" ] && [ ! -e "$TEST_ROOT/services-restarted" ] || return 97
  event repository-copy
  if [ "${COPY_STATUS:-0}" != 0 ]; then return "$COPY_STATUS"; fi
  printf '%s\n' '{"backup_id":"portable-test","summary":{"total_bytes_processed":2048}}'
}
portable_helper() {
  local action="$1" controls="" destination="" candidate=""
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --controls) controls="$2"; shift 2 ;;
      --destination) destination="$2"; shift 2 ;;
      --candidate) candidate="$2"; shift 2 ;;
      --min-files|--min-bytes) shift 2 ;;
      *) event unexpected-portable-argument; return 95 ;;
    esac
  done
  [ "$controls" = "$RESTART_JOURNAL_DIR/backup-portable-test.log/repository-controls" ] || return 98
  [ "$candidate" = "$RESTART_JOURNAL_DIR/backup-portable-test.log/repository-candidate.json" ] || return 98
  grep -Fxq /proc "$controls/rsync-excludes.txt" || return 98
  [ -f "$controls/source-selection.json" ] || return 98
  case "$action" in
    validate-candidate)
      [ -e "$TEST_ROOT/services-restarted" ] || return 97
      event validation
      printf '%s\n' '{"status":"ok","size_bytes":2048,"files_count":3}'
      ;;
    publish)
      [ "$destination" = "$TEST_ROOT/target/portable-test" ] || return 98
      [ "$(manifest_field "$controls/manifest.json" status)" = validating ] || return 98
      [ "$(manifest_field "$destination/manifest.json" status)" = validating ] || return 98
      event publish-attempt-with-validating-manifest
      [ "${PUBLISH_STATUS:-0}" = 0 ] || return "$PUBLISH_STATUS"
      printf '%s\n' '{"backup_id":"portable-test","status":"complete","size_bytes":2048,"files_count":3}' \
        > "$destination/manifest.json"
      cp -- "$controls/rsync-excludes.txt" "$destination/rsync-excludes.txt"
      : > "$TEST_ROOT/published"
      event published
      ;;
    *) event forbidden-portable-action; return 95 ;;
  esac
}
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is required for worker orchestration tests')
class PortableWorkerTests(unittest.TestCase):
    def run_worker(self, expected=0, **options):
        temporary = tempfile.TemporaryDirectory(prefix='hostbackup-portable-worker-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        script = FIXTURE + '\n' + '\n'.join(function(name) for name in (
            'portable_snapshot', 'backup_cleanup_on_exit', 'create_backup'))
        script += '\ncreate_backup portable-test\n'
        result = subprocess.run([BASH, '-s'], input=script, text=True, encoding='utf-8',
                                capture_output=True, check=False, timeout=60,
                                env={**os.environ, 'WORKER_TEST_DIR': root.as_posix(),
                                     'WORKER_PYTHON': Path(sys.executable).as_posix(),
                                     **{key: str(value) for key, value in options.items()}})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        events = (root / 'events').read_text().splitlines()
        self.assertFalse(any(value.startswith('forbidden-') or value.startswith('unexpected-') for value in events), events)
        manifest_path = root / 'target/portable-test/manifest.json'
        return events, json.loads(manifest_path.read_bytes()), root

    def assert_before(self, events, first, second):
        self.assertLess(events.index(first), events.index(second), events)

    def assert_failed_without_publication(self, events, manifest):
        self.assertEqual(manifest['status'], 'failed')
        self.assertNotIn('published', events)
        self.assertNotIn('retention', events)
        self.assertNotIn('task:finished:complete', events)
        self.assertTrue(any(item.startswith('task:failed:') for item in events), events)

    def test_success_stops_services_before_selection_and_publishes_before_retention(self):
        events, manifest, root = self.run_worker()
        self.assertEqual(manifest['status'], 'complete')
        self.assert_before(events, 'services-stop', 'source-files-with-omit-sockets')
        self.assert_before(events, 'source-files-with-omit-sockets', 'repository-copy')
        self.assert_before(events, 'repository-copy', 'sources-verify')
        self.assert_before(events, 'sources-verify', 'services-start')
        self.assert_before(events, 'services-start', 'validation')
        self.assert_before(events, 'validation', 'publish-attempt-with-validating-manifest')
        self.assert_before(events, 'publish-attempt-with-validating-manifest', 'published')
        self.assert_before(events, 'published', 'retention')
        self.assert_before(events, 'retention', 'task:finished:complete')
        # Completion belongs to publish, never a premature worker manifest write.
        self.assertNotIn('manifest:complete', events)
        self.assertEqual(events.count('services-start'), 1)
        self.assertFalse((root / 'target/portable-test/rootfs').exists())
        self.assertIn('nas-control-tampered', events)
        self.assertNotIn('attacker-controlled-rule', (root / 'target/portable-test/rsync-excludes.txt').read_text())
        if os.name == 'posix':
            private = root / 'state/journals/backup-portable-test.log/repository-controls'
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
            for name in ('manifest.json', 'source-selection.json', 'rsync-excludes.txt'):
                self.assertEqual(stat.S_IMODE((private / name).stat().st_mode), 0o600, name)

    def test_copy_failure_restarts_services_and_never_validates_or_publishes(self):
        events, manifest, _ = self.run_worker(expected=3, COPY_STATUS=3)
        self.assert_before(events, 'repository-copy', 'services-start')
        self.assertEqual(events.count('services-start'), 1)
        self.assertNotIn('validation', events)
        self.assert_failed_without_publication(events, manifest)

    def test_selection_failure_uses_real_exit_trap_to_restart_services(self):
        events, manifest, _ = self.run_worker(expected=18, FILES_STATUS=12)
        self.assert_before(events, 'services-stop', 'source-files-with-omit-sockets')
        self.assert_before(events, 'source-files-with-omit-sockets', 'services-start')
        self.assertEqual(events.count('services-start'), 1)
        self.assertNotIn('repository-copy', events)
        self.assert_failed_without_publication(events, manifest)

    def test_mount_verification_failure_restarts_services_and_blocks_publication(self):
        events, manifest, _ = self.run_worker(expected=18, VERIFY_STATUS=1)
        self.assert_before(events, 'sources-verify', 'services-start')
        self.assertNotIn('validation', events)
        self.assert_failed_without_publication(events, manifest)

    def test_failed_publish_cannot_mark_task_complete_or_start_retention(self):
        events, manifest, _ = self.run_worker(expected=19, PUBLISH_STATUS=91)
        self.assertIn('publish-attempt-with-validating-manifest', events)
        self.assertEqual(events.count('services-start'), 1)
        self.assertNotIn('manifest:complete', events)
        self.assert_failed_without_publication(events, manifest)


@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is required for journal cleanup tests')
class PortableJournalCleanupTests(unittest.TestCase):
    CONTROL_NAMES = ('manifest.json', 'rsync-excludes.txt', 'source-selection.json',
                     'source-mounts.json', 'mounts.txt', 'metadata-probe.json',
                     'package-list.txt', 'systemd-services.txt', 'docker.json', 'backup-validation.json')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hostbackup-portable-journal-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journal = self.root / 'journals/backup-portable-test.log'
        self.controls = self.journal / 'repository-controls'
        self.controls.mkdir(parents=True)
        self.journal_bytes = b'{"task":"backup-portable-test.log","entries":[]}\n'
        (self.journal / 'journal.json').write_bytes(self.journal_bytes)
        for name in self.CONTROL_NAMES:
            (self.controls / name).write_bytes(b'fixture\n')
        for name in ('repository-candidate.json', 'source-files.nul', 'selected-stop-targets.tsv',
                     'docker-to-stop.tsv', 'post-hook.started', 'post-hook.done', 'restart.done'):
            (self.journal / name).write_bytes(b'fixture\n')
        self.keep = self.root / 'never-delete.json'
        self.keep.write_bytes(b'protected outside journal\n')

    def run_finish(self, expected):
        script = r'''
set -euo pipefail
cd -- "$WORKER_TEST_DIR"
RESTART_JOURNAL_DIR="$(pwd)/journals"
restart_journal_update() { [ "$2" = pending ]; }
log() { printf '%s\n' "$*"; }
'''
        script += '\n'.join(function(name) for name in (
            'valid_task_name', 'restart_journal_path_is_safe', 'restart_journal_finish'))
        script += '\nrestart_journal_finish "$RESTART_JOURNAL_DIR/backup-portable-test.log"\n'
        result = subprocess.run([BASH, '-s'], input=script, text=True, encoding='utf-8',
                                capture_output=True, check=False, timeout=30,
                                env={**os.environ, 'WORKER_TEST_DIR': self.root.as_posix()})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(self.keep.read_bytes(), b'protected outside journal\n')
        if expected:
            self.assertTrue((self.journal / 'journal.json').is_file(), 'Recovery journal must remain on refusal')
            self.assertEqual((self.journal / 'journal.json').read_bytes(), self.journal_bytes)

    def make_symlink(self, path, target, is_directory=False):
        try:
            path.symlink_to(target, target_is_directory=is_directory)
        except (OSError, NotImplementedError) as error:
            if os.name == 'posix':
                raise
            self.skipTest('Native symlink permission unavailable: ' + str(error))

    def test_known_repository_controls_and_candidate_are_completely_removed(self):
        self.run_finish(0)
        self.assertFalse(self.journal.exists())

    def test_unknown_control_file_blocks_before_journal_removal(self):
        unexpected = self.controls / 'keep-unknown.json'
        unexpected.write_bytes(b'unknown controls must survive\n')
        self.run_finish(20)
        self.assertEqual(unexpected.read_bytes(), b'unknown controls must survive\n')

    def test_unknown_top_level_file_blocks_before_journal_removal(self):
        unexpected = self.journal / 'keep-unknown.json'
        unexpected.write_bytes(b'unknown journal data must survive\n')
        self.run_finish(20)
        self.assertEqual(unexpected.read_bytes(), b'unknown journal data must survive\n')

    def test_symlink_control_file_is_rejected_without_following_target(self):
        path = self.controls / 'manifest.json'
        path.unlink()
        self.make_symlink(path, self.keep)
        self.run_finish(20)
        self.assertTrue(path.is_symlink())

    def test_symlink_candidate_is_rejected_before_journal_removal(self):
        path = self.journal / 'repository-candidate.json'
        path.unlink()
        self.make_symlink(path, self.keep)
        self.run_finish(20)
        self.assertTrue(path.is_symlink())

    def test_symlink_control_directory_is_rejected_without_recursing(self):
        original = self.journal / 'original-controls'
        self.controls.rename(original)
        self.make_symlink(self.controls, original, is_directory=True)
        self.run_finish(20)
        self.assertTrue((original / 'manifest.json').is_file())

    def test_directory_instead_of_regular_control_file_is_rejected(self):
        path = self.controls / 'manifest.json'
        path.unlink()
        path.mkdir()
        (path / 'keep').write_bytes(b'not a regular control file\n')
        self.run_finish(20)
        self.assertEqual((path / 'keep').read_bytes(), b'not a regular control file\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
