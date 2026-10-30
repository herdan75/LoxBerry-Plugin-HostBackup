"""Docker preflight truthfulness without connecting to any real Docker daemon."""

import json
from pathlib import Path
import shutil
import sys
import time
import unittest

import test_runtime_safety as runtime


STUB = r'''
command() {
  if [ "${1:-}" = -v ]; then
    if [ "${2:-}" = docker ] && [ "${TEST_DOCKER_STATE:-available}" = not-installed ]; then return 1; fi
    if [ "${2:-}" = timeout ] && [ "${TEST_DOCKER_STATE:-available}" = probe-unavailable ]; then return 1; fi
  fi
  builtin command "$@"
}
timeout() {
  [ "$1:$2:$3:$4:$5:$6:$7" = '-k:2:10:docker:ps:--no-trunc:-q' ] || return 99
  printf 'bounded read-only probe\n' >> "$TEST_ROOT/docker-probes"
  case "${TEST_DOCKER_STATE:-available}" in
    timeout) return 124 ;;
    killed) return 137 ;;
    unavailable) echo 'PRIVATE DAEMON ERROR' >&2; return 1 ;;
  esac
  shift 3; "$@"
}
docker() {
  [ "$*" = 'ps --no-trunc -q' ] || return 99
  if [ "${TEST_DOCKER_STATE:-available}" = invalid-response ]; then echo 'invalid output'; return 0; fi
  if [ "${TEST_RUNNING:-0}" -gt 0 ]; then printf '%064d\n' 1; fi
  if [ "${TEST_RUNNING:-0}" -gt 1 ]; then printf '%064d\n' 2; fi
}
selected_stop_targets() { printf '%s' "${TEST_TARGETS:-}"; return "${TEST_SELECTION_EXIT:-0}"; }
json_get_bool() {
  case "$1" in
    stop_docker_before_backup) echo "${TEST_LEGACY:-false}" ;;
    create_export_after_backup) echo false ;;
    *) echo true ;;
  esac
}
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required")
class DockerPreflightTests(unittest.TestCase):
    setUp = runtime.RuntimeSafetyTests.setUp
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def preflight(self, entry="preflight_backup", extra="", **options):
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + STUB + extra + "\n" + entry + "\n",
                                runtime.PREFLIGHT_FUNCTIONS,
                                {"NO_ESTIMATE": "true", "FREE_MB": "20000", **options})
        self.assertEqual(result.stderr, "")
        self.assertNotIn("PRIVATE DAEMON ERROR", result.stdout)
        data = json.loads(result.stdout)
        check = next(item for item in data["checks"] if item["name"] == "Docker im LoxBerry-Kontext")
        self.assertFalse((self.root / "service-calls").exists())
        self.assertFalse((self.root / "copy-called").exists())
        return data, check

    def test_probe_states_count_only_successful_valid_inventory(self):
        for state, expected in (("not-installed", "not-installed -1"),
                                ("probe-unavailable", "probe-unavailable -1"),
                                ("unavailable", "unavailable -1"),
                                ("timeout", "timeout -1"), ("killed", "timeout -1"),
                                ("invalid-response", "invalid-response -1"),
                                ("available", "available 0")):
            with self.subTest(state=state):
                result = self.run_shell(STUB + "\ndocker_preflight_status\n",
                                        ("docker_preflight_status",), {"TEST_DOCKER_STATE": state})
                self.assertEqual(result.stdout.strip(), expected)
                self.assertEqual(result.stderr, "")

    def test_successful_inventory_counts_all_running_containers(self):
        result = self.run_shell(STUB + "\ndocker_preflight_status\n",
                                ("docker_preflight_status",), {"TEST_RUNNING": "2"})
        self.assertEqual(result.stdout.strip(), "available 2")

    @unittest.skipUnless(sys.platform == "linux", "Real process-group deadline requires Linux")
    def test_real_timeout_bounds_a_hung_disposable_docker_client(self):
        self.assertIsNotNone(shutil.which("timeout"), "Linux CI needs coreutils timeout")
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake = fake_bin / "docker"
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$RUNTIME_TEST_DIR/client-started"\n'
                        'sleep 30\nprintf done > "$RUNTIME_TEST_DIR/client-finished"\n', encoding="utf-8")
        fake.chmod(0o755)
        started = time.monotonic()
        result = self.run_shell('''
unset -f docker timeout
PATH="$TEST_ROOT/fake-bin:$PATH"
export PATH
docker_preflight_status
''', ("docker_preflight_status",))
        elapsed = time.monotonic() - started
        self.assertEqual(result.stdout.strip(), "timeout -1")
        self.assertEqual((self.root / "client-started").read_text().strip(), "ps --no-trunc -q")
        self.assertFalse((self.root / "client-finished").exists())
        self.assertLess(elapsed, 20, "A daemon stall must not freeze the preflight")

    def test_no_local_docker_is_not_required_and_does_not_claim_zero(self):
        data, check = self.preflight(TEST_DOCKER_STATE="not-installed")
        self.assertEqual(data["status"], "ok")
        self.assertTrue(check["ok"])
        self.assertFalse(check["applicable"])
        self.assertTrue(check["informational"])
        self.assertNotIn("running=0", json.dumps(check))
        self.assertIn("separaten Host", check["details"])
        self.assertFalse((self.root / "docker-probes").exists())

    def test_reachable_zero_containers_is_confirmed_ok(self):
        data, check = self.preflight()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(check["ok"])
        self.assertTrue(check["applicable"])
        self.assertEqual(check["value"], "running=0")

    def test_unreachable_daemon_remains_json_in_all_errexit_contexts(self):
        for entry in ("preflight_backup", 'result="$(preflight_backup)"; printf "%s\\n" "$result"',
                      'if ! result="$(preflight_backup)"; then exit 91; fi; printf "%s\\n" "$result"'):
            with self.subTest(entry=entry):
                data, check = self.preflight(entry=entry, TEST_DOCKER_STATE="unavailable")
                self.assertEqual(data["status"], "warning")
                self.assertIsNone(check["ok"])
                self.assertEqual(check["value"], "running=unbekannt")
                self.assertFalse(check["required"])

    def test_timeout_or_invalid_inventory_is_not_mistaken_for_no_containers(self):
        for state in ("timeout", "invalid-response", "probe-unavailable"):
            with self.subTest(state=state):
                data, check = self.preflight(TEST_DOCKER_STATE=state)
                self.assertEqual(data["status"], "warning")
                self.assertEqual(check["value"], "running=unbekannt")
                self.assertIsNone(check["ok"])

    def test_required_docker_stops_stay_blocking_without_a_daemon(self):
        for selection in ({"TEST_TARGETS": "docker\tsonn-core"}, {"TEST_LEGACY": "true"}):
            for state in ("not-installed", "unavailable", "timeout"):
                with self.subTest(selection=selection, state=state):
                    data, check = self.preflight(TEST_DOCKER_STATE=state, **selection)
                    self.assertEqual(data["status"], "error")
                    self.assertFalse(check["ok"])
                    self.assertTrue(check["required"])
                    self.assertIn("Docker-Stopps sind konfiguriert", check["details"])

    def test_explicit_native_selection_overrides_legacy_stop_all_like_worker(self):
        data, check = self.preflight(TEST_TARGETS="systemd\tmosquitto.service", TEST_LEGACY="true",
                                     TEST_DOCKER_STATE="not-installed")
        self.assertEqual(data["status"], "ok")
        self.assertFalse(check["required"])
        self.assertFalse(check["applicable"])

    def test_malformed_selection_never_becomes_an_optional_empty_selection(self):
        for partial in ("", "systemd\tmosquitto.service"):
            with self.subTest(partial=partial):
                data, check = self.preflight(TEST_SELECTION_EXIT="18", TEST_DOCKER_STATE="not-installed", TEST_TARGETS=partial)
                self.assertEqual(data["status"], "error")
                self.assertFalse(check["ok"])
                self.assertIn("Auswahl konnte nicht geprueft", check["details"])

    def test_running_containers_without_effective_stops_still_warn(self):
        for selection in ({}, {"TEST_LEGACY": "true", "TEST_TARGETS": "systemd\tmosquitto.service"}):
            with self.subTest(selection=selection):
                data, check = self.preflight(TEST_RUNNING="2", **selection)
                self.assertEqual(data["status"], "warning")
                self.assertEqual(check["value"], "running=2")
                self.assertTrue(check["ok"])
                self.assertIn("konsistente Datenbanken", " ".join(data["warnings"]))

    def test_reachable_docker_keeps_selected_and_legacy_stops_working(self):
        for selection in ({"TEST_TARGETS": "docker\tsonn-core"}, {"TEST_LEGACY": "true"}):
            with self.subTest(selection=selection):
                data, check = self.preflight(TEST_RUNNING="2", **selection)
                self.assertEqual(data["status"], "ok")
                self.assertTrue(check["required"])
                self.assertTrue(check["ok"])

    def test_required_unavailable_docker_blocks_start_and_worker_before_mutations(self):
        for entrypoint in ("start_backup", "create_backup"):
            with self.subTest(entrypoint=entrypoint):
                script = runtime.PREFLIGHT_MOCKS + STUB + r'''
launch_background() { echo forbidden > "$TEST_ROOT/launch-called"; return 99; }
stop_backup_targets() { echo forbidden > "$TEST_ROOT/stop-called"; return 99; }
run_hook() { echo forbidden > "$TEST_ROOT/hook-called"; return 99; }
''' + f"\n{entrypoint} docker-error-{entrypoint}\n"
                self.run_shell(script, (*runtime.PREFLIGHT_FUNCTIONS, entrypoint),
                               {"NO_ESTIMATE": "true", "FREE_MB": "20000", "TEST_DOCKER_STATE": "unavailable",
                                "TEST_TARGETS": "docker\tsonn-core"}, expected=17)
                for action in ("launch", "stop", "hook", "copy"):
                    self.assertFalse((self.root / (action + "-called")).exists())
                self.assertFalse((self.root / ("target/docker-error-" + entrypoint)).exists())
                task = json.loads((self.root / ("state/tasks/backup-docker-error-" + entrypoint + ".log.json")).read_text())
                self.assertEqual(task["phase"], "preflight_error")

    def test_unavailable_optional_docker_cannot_downgrade_other_failures(self):
        cases = (
            ({"FREE_INODES": "0"}, "", "Freie Inodes"),
            ({}, "\nmetadata_capability_probe() { return 1; }\n", "Metadaten-Modus"),
            ({}, "\nsource_info() { printf '%s\\n' '{\"status\":\"error\",\"errors\":[\"unsafe source\"]}'; return 1; }\n", "Datenquellen-Auswahl"),
            ({}, "\nwatchdog_guard_probe() { printf '%s\\n' '{\"ok\":false,\"applicable\":true,\"mode\":\"error\",\"details\":\"unsafe watchdog\"}'; }\n", "Docker-Watchdog-Koordination"),
        )
        for options, extra, failure in cases:
            with self.subTest(failure=failure):
                data, _ = self.preflight(TEST_DOCKER_STATE="unavailable", extra=extra, **options)
                self.assertEqual(data["status"], "error")
                self.assertFalse(next(item for item in data["checks"] if item["name"] == failure)["ok"])


if __name__ == "__main__":
    unittest.main()
