"""Optional Docker inventory must not invalidate an otherwise usable backup.

Use the real manifest writer and worker, not the minimal manifest doubles used
by unrelated runtime tests. Host services and file copies remain disposable
fixtures; no Docker daemon or host root is contacted.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_runtime_safety as runtime
import test_portable_worker as portable_worker


SUMMARY_FUNCTIONS = ("docker_summary_json", "write_manifest")
INVENTORY_STUB = r'''
command() {
  if [ "${1:-}" = -v ]; then
    if [ "${2:-}" = docker ] && [ "${INVENTORY_STATE:-available}" = not-installed ]; then return 1; fi
    if [ "${2:-}" = timeout ] && [ "${INVENTORY_STATE:-available}" = probe-unavailable ]; then return 1; fi
  fi
  builtin command "$@"
}
timeout() {
  case "$1" in
    -k) shift 2 ;;
  esac
  shift
  if [ "${1:-}" = docker ]; then
    case "${INVENTORY_STATE:-available}" in timeout) return 124 ;; killed) return 137 ;; esac
  fi
  "$@"
}
docker() {
  printf '%s\n' "$*" >> "$TEST_ROOT/docker-calls"
  [ "$1" = ps ] || return 98
  case "${INVENTORY_STATE:-available}" in
    unavailable) echo 'PRIVATE DAEMON DETAILS' >&2; return 1 ;;
    late-unavailable) [ ! -e "$TEST_ROOT/copy-called" ] || return 1 ;;
  esac
  if [ "$*" = 'ps --no-trunc -q' ]; then return 0; fi
  [ "$*" = 'ps -a --no-trunc --format {{json .}}' ] || return 97
  case "${INVENTORY_STATE:-available}" in
    empty) return 0 ;;
    invalid-json) printf 'not-json\n'; return 0 ;;
    invalid-object) printf '[]\n'; return 0 ;;
    null-object) printf 'null\n'; return 0 ;;
    missing-id) printf '{"Names":"sonn-core"}\n'; return 0 ;;
    short-id) printf '{"ID":"abc123","Names":"sonn-core"}\n'; return 0 ;;
  esac
  printf '{"ID":"%064d","Names":"sonn-core","State":"running","Status":"Up 3 hours"}\n' 1
  case "${INVENTORY_STATE:-available}" in
    partial-error) return 1 ;;
    partial-invalid) printf '{bad-json\n' ;;
    blank-line) printf '\n{"ID":"%064d","Names":"second"}\n' 2 ;;
  esac
}
host_os_pretty() { echo 'Fixture Linux'; }
host_arch() { echo x86_64; }
loxberry_version() { echo 4.0.1.1; }
'''

WORKER_STUB = r'''
json_get_bool() { echo false; }
selected_stop_targets() {
  if [ "${TEST_NATIVE:-false}" = true ]; then printf 'systemd\tdemo.service\n'; fi
  if [ "${TEST_REQUIRED_DOCKER:-false}" = true ]; then printf 'docker\tsonn-core\n'; fi
}
write_backup_marker() {
  # Avoid unrelated host inventory calls; real manifest/docker.json writes stay.
  : > "$1/package-list.txt"
  : > "$1/systemd-services.txt"
  : > "$1/mounts.txt"
}
rsync_live_options() { :; }
rsync_metadata_options() { :; }
rsync_destination() { printf '%s\n' "$2"; }
rsync() {
  assert_mock_copy_scope "$@" || return 99
  : > "$TEST_ROOT/copy-called"
  return "${COPY_STATUS:-0}"
}
calculate_size() { echo 12; }
calculate_files() { echo 1; }
validate_completed_backup() { :; }
prune_old_backups() { :; }
tar_metadata_options() { :; }
# Only the portable copy helper is intercepted, never real TAR against '/'.
definition="$(declare -f python3)"
eval "${definition/python3/fixture_python3}"
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-tar.py" ]; then
    shift
    local archive="" files="" receipt="" report="" state=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --archive) archive="$2" ;;
        --files-from) files="$2" ;;
        --receipt) receipt="$2" ;;
        --source-report) report="$2" ;;
        --state-dir) state="$2" ;;
        *) return 99 ;;
      esac
      shift 2
    done
    [ "$archive" = "$TEST_ROOT/target/test/rootfs.tar" ] || return 99
    [ "$state" = "$RESTART_JOURNAL_DIR/backup-test.log" ] || return 99
    [ "$files" = "$state/source-files.nul" ] && [ "$report" = "$state/source-selection.json" ] || return 99
    [ "$receipt" = "$state/tar-result.json" ] || return 99
    printf fixture-archive > "$archive"
    printf '{"raw_exit_status":0,"effective_exit_status":0}\n' > "$receipt"
    : > "$TEST_ROOT/copy-called"
  else
    fixture_python3 "$@"
  fi
}
if [ "${TEST_NATIVE:-false}" = true ]; then : > "$TEST_ROOT/active-demo.service"; fi
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required")
class DockerManifestTests(unittest.TestCase):
    setUp = runtime.RuntimeSafetyTests.setUp
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def test_inventory_states_are_complete_json_and_never_partial_success(self):
        states = ("not-installed", "probe-unavailable", "unavailable", "timeout", "killed",
                  "empty", "available", "invalid-json", "invalid-object", "null-object",
                  "missing-id", "short-id", "partial-error", "partial-invalid", "blank-line")
        result = self.run_shell(INVENTORY_STUB + '\nfor INVENTORY_STATE in ' + ' '.join(states) +
                                '; do docker_summary_json; done\nprintf "%s\\n" survived\n',
                                ("docker_summary_json",))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[-1], "survived")
        self.assertEqual(result.stderr, "")
        self.assertNotIn("PRIVATE", result.stdout)
        self.assertEqual(len(lines), len(states) + 1)
        for state, line in zip(states, lines):
            with self.subTest(state=state):
                data = json.loads(line)
                if state in ("empty", "available"):
                    self.assertTrue(data["available"])
                    self.assertTrue(data["inventory_complete"])
                    self.assertEqual(len(data["containers"]), int(state == "available"))
                else:
                    self.assertFalse(data["inventory_complete"])
                    self.assertEqual(data["containers"], [])
                    self.assertEqual(data["available"], False if state == "not-installed" else None)
                    expected = ("timeout" if state == "killed" else "unavailable" if state == "partial-error"
                                else "invalid-response" if state in ("invalid-json", "invalid-object", "null-object",
                                                                     "missing-id", "short-id", "partial-invalid", "blank-line")
                                else state)
                    self.assertEqual(data["state"], expected)

    def test_real_manifest_preserves_known_inventory_and_unknown_on_later_update(self):
        self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + r'''
mkdir -p "$TEST_ROOT/target/test"
write_backup_marker() { :; }
touch "$TEST_ROOT/target/test/package-list.txt" "$TEST_ROOT/target/test/systemd-services.txt" "$TEST_ROOT/target/test/mounts.txt"
write_manifest "$TEST_ROOT/target/test" test running fixture '' 0 0
cp "$TEST_ROOT/target/test/docker.json" "$TEST_ROOT/first-inventory.json"
INVENTORY_STATE=unavailable
write_manifest "$TEST_ROOT/target/test" test complete fixture finished 12 1
''', SUMMARY_FUNCTIONS)
        initial = json.loads((self.root / "first-inventory.json").read_text())["docker"]
        self.assertTrue(initial["inventory_complete"])
        self.assertEqual(initial["containers"][0]["Names"], "sonn-core")
        final = json.loads((self.root / "target/test/docker.json").read_text())
        self.assertTrue(final["captured_at"])
        self.assertEqual(final["docker"]["state"], "unavailable")
        self.assertIsNone(final["docker"]["available"])
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "complete")
        self.assertEqual(list((self.root / "target/test").glob(".docker-*")), [])

    def test_manifest_and_sidecar_write_errors_remain_errors_in_guarded_calls(self):
        self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + r'''
mkdir -p "$TEST_ROOT/target/bad-manifest/manifest.json" "$TEST_ROOT/target/bad-sidecar/docker.json"
for target in "$TEST_ROOT/target/bad-manifest" "$TEST_ROOT/target/bad-sidecar"; do
  touch "$target/package-list.txt" "$target/systemd-services.txt" "$target/mounts.txt"
  if write_manifest "$target" test running fixture '' 0 0; then exit 92; fi
done
''', SUMMARY_FUNCTIONS)
        self.assertFalse((self.root / "target/bad-manifest/docker.json").exists())
        self.assertTrue((self.root / "target/bad-sidecar/docker.json").is_dir())
        self.assertEqual(list((self.root / "target/bad-sidecar").glob(".docker-*")), [])

    def test_fixed_nas_permissions_do_not_become_a_new_documentation_requirement(self):
        (self.root / "NoChmod.pm").write_text('package NoChmod;\nBEGIN { *CORE::GLOBAL::chmod = sub { $! = 95; return 0; }; }\n1;\n')
        self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + r'''
perl() { command perl -I"$TEST_ROOT" -MNoChmod "$@"; }
mkdir -p "$TEST_ROOT/target/test"
touch "$TEST_ROOT/target/test/package-list.txt" "$TEST_ROOT/target/test/systemd-services.txt" "$TEST_ROOT/target/test/mounts.txt"
write_manifest "$TEST_ROOT/target/test" test complete fixture finished 12 1
''', SUMMARY_FUNCTIONS)
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "complete")
        self.assertTrue(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["inventory_complete"])

    def test_failed_sidecar_replace_keeps_previous_complete_document(self):
        (self.root / "NoDockerRename.pm").write_text(
            'package NoDockerRename;\nBEGIN { *CORE::GLOBAL::rename = sub ($$) {\n'
            'if ($_[1] =~ /docker\\.json$/) { $! = 5; return 0; } return CORE::rename($_[0], $_[1]);\n}; }\n1;\n')
        self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + r'''
mkdir -p "$TEST_ROOT/target/test"
touch "$TEST_ROOT/target/test/package-list.txt" "$TEST_ROOT/target/test/systemd-services.txt" "$TEST_ROOT/target/test/mounts.txt"
write_manifest "$TEST_ROOT/target/test" test running fixture '' 0 0
cp "$TEST_ROOT/target/test/docker.json" "$TEST_ROOT/before.json"
perl() { command perl -I"$TEST_ROOT" -MNoDockerRename "$@"; }
INVENTORY_STATE=unavailable
if write_manifest "$TEST_ROOT/target/test" test complete fixture finished 12 1; then exit 92; fi
''', SUMMARY_FUNCTIONS)
        self.assertEqual((self.root / "target/test/docker.json").read_bytes(), (self.root / "before.json").read_bytes())
        self.assertEqual(list((self.root / "target/test").glob(".docker-*")), [])

    def worker(self, **env):
        return self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + WORKER_STUB + '\ncreate_backup test\n',
                              (*runtime.JOURNAL_FUNCTIONS, *runtime.PREFLIGHT_FUNCTIONS,
                               *SUMMARY_FUNCTIONS, "manifest_started_at", "create_backup"),
                              {"TEST_BACKUP_MODE": "full", "FREE_MB": "20000", "NO_ESTIMATE": "true", **env},
                              expected=int(env.get("COPY_STATUS", "0")))

    def test_actual_worker_finishes_with_unavailable_optional_docker(self):
        result = self.worker(INVENTORY_STATE="unavailable")
        self.assertTrue((self.root / "copy-called").exists())
        self.assertNotIn("PRIVATE", result.stdout + result.stderr)
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "complete")
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "finished")
        self.assertEqual(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["state"], "unavailable")

    def test_actual_snapshot_worker_finishes_without_docker_client(self):
        self.worker(INVENTORY_STATE="not-installed", TEST_BACKUP_MODE="snapshot")
        self.assertTrue((self.root / "copy-called").exists())
        manifest = json.loads((self.root / "target/test/manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["backup"]["mode"], "snapshot")
        self.assertEqual(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["state"], "not-installed")

    def test_actual_portable_full_worker_finishes_with_optional_docker_timeout(self):
        self.worker(INVENTORY_STATE="timeout", TEST_METADATA_MODE="portable-archive")
        self.assertTrue((self.root / "copy-called").exists())
        manifest = json.loads((self.root / "target/test/manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["backup"]["storage_format"], "portable-tar")
        self.assertEqual(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["state"], "timeout")

    def test_portable_repository_worker_writes_real_manifests_with_optional_docker(self):
        # The existing portable fixture intercepts repository I/O/publication,
        # but the real writer must also succeed for private repository controls.
        script = portable_worker.FIXTURE + '\n' + INVENTORY_STUB + r'''
dpkg-query() { :; }
systemctl() { :; }
mount() { printf 'fixture\n'; }
'''
        script += '\n'.join(runtime.function(name) for name in (*SUMMARY_FUNCTIONS,
            'portable_snapshot', 'checked_source_info', 'watchdog_guard_start',
            'watchdog_guard_check', 'watchdog_guard_release', 'backup_cleanup_on_exit', 'create_backup'))
        script += '\ncreate_backup portable-test\n'
        result = subprocess.run([runtime.BASH, '-s'], input=script, text=True, encoding='utf-8',
                                capture_output=True, check=False, timeout=90,
                                env={**os.environ, 'WORKER_TEST_DIR': self.root.as_posix(),
                                     'WORKER_PYTHON': Path(sys.executable).as_posix(),
                                     'INVENTORY_STATE': 'unavailable'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / 'published').exists())
        for folder in ('target/portable-test', 'state/journals/backup-portable-test.log/repository-controls'):
            self.assertEqual(json.loads((self.root / folder / 'docker.json').read_text())["docker"]["state"], "unavailable")
        controls = json.loads((self.root / 'state/journals/backup-portable-test.log/repository-controls/manifest.json').read_text())
        self.assertEqual(controls['backup']['storage_format'], 'portable-repository')
        self.assertEqual(controls['status'], 'validating')

    def test_actual_worker_keeps_native_stop_and_recovery_when_docker_fails_later(self):
        self.worker(INVENTORY_STATE="late-unavailable", TEST_NATIVE="true")
        self.assertEqual((self.root / "service-calls").read_text().splitlines(), ["stop demo.service", "start demo.service"])
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "complete")
        self.assertEqual(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["state"], "unavailable")

    def test_optional_inventory_does_not_hide_copy_failure_and_recovery(self):
        self.worker(INVENTORY_STATE="unavailable", TEST_NATIVE="true", COPY_STATUS="23")
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertEqual(json.loads((self.root / "target/test/manifest.json").read_text())["status"], "failed")
        self.assertEqual(json.loads((self.root / "state/tasks/backup-test.log.json").read_text())["state"], "failed")
        self.assertEqual(json.loads((self.root / "target/test/docker.json").read_text())["docker"]["state"], "unavailable")

    def test_required_docker_still_blocks_before_manifest_or_stops(self):
        self.run_shell(runtime.PREFLIGHT_MOCKS + INVENTORY_STUB + WORKER_STUB + '\ncreate_backup test\n',
                       (*runtime.JOURNAL_FUNCTIONS, *runtime.PREFLIGHT_FUNCTIONS, *SUMMARY_FUNCTIONS, "create_backup"),
                       {"TEST_REQUIRED_DOCKER": "true", "INVENTORY_STATE": "unavailable", "NO_ESTIMATE": "true", "FREE_MB": "20000"},
                       expected=17)
        self.assertFalse((self.root / "target/test").exists())
        self.assertFalse((self.root / "service-calls").exists())
        self.assertFalse((self.root / "copy-called").exists())

    @unittest.skipUnless(sys.platform == "linux", "Real process-group deadline requires Linux")
    def test_real_timeout_ends_hung_inventory_without_partial_json(self):
        self.assertIsNotNone(shutil.which("timeout"))
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake = fake_bin / "docker"
        fake.write_text('#!/bin/sh\necho \'{"partial":"private"}\'\nsleep 30\necho done > "$RUNTIME_TEST_DIR/late-client"\n')
        fake.chmod(0o755)
        start = time.monotonic()
        result = self.run_shell('unset -f docker timeout\nPATH="$TEST_ROOT/fake-bin:$PATH"\nexport PATH\ndocker_summary_json\n',
                                ("docker_summary_json",))
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(json.loads(result.stdout)["state"], "timeout")
        self.assertNotIn("private", result.stdout)
        self.assertFalse((self.root / "late-client").exists())


if __name__ == "__main__":
    unittest.main()
