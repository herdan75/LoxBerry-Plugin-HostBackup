"""Exercise the real read-only watchdog gate before any backup is created.

Only extracted shell functions run. The helper protocol is doubled here; its
released-controller/real-Linux-lock matrix is covered by the watchdog suites.
Docker/service mutations and the actual host filesystem are never consulted.
"""

import json
import os
from pathlib import Path
import unittest

import test_runtime_safety as runtime


STUB = r'''
selected_stop_targets() {
  printf 'selection\n' >> "$TEST_ROOT/watchdog-calls"
  printf '%s' "${TEST_TARGETS:-}"
  return "${TEST_SELECTION_EXIT:-0}"
}
json_get_bool() {
  case "$1" in
    stop_docker_before_backup) printf '%s\n' "${TEST_LEGACY:-false}" ;;
    create_export_after_backup) echo false ;;
    *) echo true ;;
  esac
}
eval "$(declare -f python3 | sed '1s/python3/fixture_python3/')"
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-watchdog.py" ]; then
    [ "$2:$3:$5:$7" = 'probe:--home:--targets:--legacy' ] || return 98
    [ "$4" = "$LBHOMEDIR" ] || return 98
    printf 'probe\nlegacy=%s\ntargets=%s\n' "$8" "$6" >> "$TEST_ROOT/watchdog-calls"
    cat -- "$TEST_ROOT/watchdog-response"
    printf '%s' "${TEST_HELPER_STDERR:-}" >&2
    return "${TEST_HELPER_EXIT:-0}"
  fi
  fixture_python3 "$@"
}
'''


def report(ok=True, mode="lock", details="LoxPanel-Watchdog kann koordiniert werden."):
    return {"ok": ok, "applicable": mode != "skip", "mode": mode, "details": details}


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required")
class WatchdogPreflightTests(unittest.TestCase):
    setUp = runtime.RuntimeSafetyTests.setUp
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def prepare(self, response=None, installed=True, **options):
        if installed:
            controller = self.root / "loxberry/bin/plugins/loxpanel/loxpanel-ctl.sh"
            controller.parent.mkdir(parents=True, exist_ok=True)
            controller.write_text("inert fixture, never executed\n", encoding="utf-8")
        if response is None:
            response = report()
        raw = response if isinstance(response, str) else json.dumps(response)
        (self.root / "watchdog-response").write_text(raw, encoding="utf-8")
        return {"NO_ESTIMATE": "true", "FREE_MB": "20000", **options}

    def probe(self, response=None, installed=True, **options):
        env = self.prepare(response, installed, **options)
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + STUB + "\nwatchdog_guard_probe\n", env=env)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", result.stdout)
        return json.loads(result.stdout)

    def preflight(self, response=None, **options):
        env = self.prepare(response, **options)
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + STUB + "\npreflight_backup\n",
                                runtime.PREFLIGHT_FUNCTIONS, env)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        check = next(item for item in data["checks"] if item["name"] == "Docker-Watchdog-Koordination")
        self.assertFalse((self.root / "service-calls").exists())
        self.assertFalse((self.root / "copy-called").exists())
        self.assertEqual(list((self.root / "state/restart-journals").iterdir()), [])
        return data, check

    def test_absent_plugin_does_not_query_selection_or_helper(self):
        data = self.probe(installed=False, TEST_SELECTION_EXIT="99", TEST_HELPER_EXIT="99")
        self.assertEqual((data["ok"], data["applicable"], data["mode"]), (True, False, "skip"))
        self.assertFalse((self.root / "watchdog-calls").exists())

    def test_only_data_directory_still_requires_checked_integration(self):
        (self.root / "loxberry/data/plugins/loxpanel").mkdir(parents=True)
        data = self.probe(report(False, "unsupported", "Unbekannter Controller: LoxPanel zuerst selbst stoppen."), installed=False)
        self.assertFalse(data["ok"])
        self.assertIn("probe", (self.root / "watchdog-calls").read_text())

    def test_only_config_directory_still_requires_checked_integration(self):
        (self.root / "loxberry/config/plugins/loxpanel").mkdir(parents=True)
        data = self.probe(report(False, "unsupported", "LoxPanel-Steuerdatei fehlt."), installed=False)
        self.assertFalse(data["ok"])
        self.assertIn("probe", (self.root / "watchdog-calls").read_text())

    def test_exact_stop_selection_and_legacy_semantics_are_preserved(self):
        cases = (("", "true", "true"), ("", "false", "false"),
                 ("docker\tloxpanel", "true", "false"),
                 ("systemd\tmosquitto.service", "true", "false"),
                 ("docker\t" + "a" * 64, "false", "false"))
        for targets, legacy, expected in cases:
            with self.subTest(targets=targets, legacy=legacy):
                data = self.probe(TEST_TARGETS=targets, TEST_LEGACY=legacy)
                self.assertTrue(data["ok"])
                lines = (self.root / "watchdog-calls").read_text().splitlines()
                self.assertIn("legacy=" + expected, lines)
                self.assertIn("targets=" + targets, lines)
                (self.root / "watchdog-calls").unlink()

    def test_selection_failure_is_blocking_without_calling_helper(self):
        data = self.probe(TEST_SELECTION_EXIT="20")
        self.assertEqual((data["ok"], data["mode"]), (False, "error"))
        self.assertEqual((self.root / "watchdog-calls").read_text().splitlines(), ["selection"])

    def test_invalid_helper_replies_and_nonzero_exits_fail_closed(self):
        invalid = ["", "{", "null", "[]", "true", 'noise\n' + json.dumps(report()),
                   {}, {**report(), "ok": "true"}, {**report(), "applicable": 1},
                   {**report(), "mode": "guess"}, report(True, "unsupported"),
                   report(False, "lock"), report(True, "skip"),
                   {**report(), "applicable": False}, {**report(), "details": []},
                   {**report(), "details": ""}, {**report(), "details": "bad\u001btext"},
                   {**report(), "details": "x" * 4001}, " " * 16385]
        # A genuine skip is allowed only with applicable=false (report() already
        # enforces that); this case deliberately violates it.
        invalid[12]["applicable"] = True
        for payload in invalid:
            with self.subTest(payload=str(payload)[:80]):
                data = self.probe(payload)
                self.assertEqual((data["ok"], data["mode"]), (False, "error"))
        for code in (1, 20, 124, 137):
            with self.subTest(exit_code=code):
                data = self.probe(TEST_HELPER_EXIT=str(code), TEST_HELPER_STDERR="Traceback: private internals")
                self.assertEqual((data["ok"], data["mode"]), (False, "error"))

    def test_unselected_skip_and_safe_lock_are_green_in_all_copy_profiles(self):
        for profile in runtime.METADATA_PROFILES:
            for backup_mode in ("full", "snapshot"):
                for mode in ("skip", "lock"):
                    with self.subTest(profile=profile, backup_mode=backup_mode, mode=mode):
                        data, check = self.preflight(report(mode=mode), TEST_METADATA_MODE=profile,
                                                     TEST_BACKUP_MODE=backup_mode)
                        self.assertEqual(data["status"], "ok")
                        self.assertTrue(check["ok"])
                        self.assertEqual(check["informational"], mode == "skip")

    def test_manual_stop_is_green_and_explains_manual_restart(self):
        message = "LoxPanel wurde bewusst gestoppt; nach dem Backup in LoxPanel wieder einschalten."
        data, check = self.preflight(report(mode="manual-stop", details=message),
                                     TEST_METADATA_MODE="portable-archive", TEST_BACKUP_MODE="full")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(check["details"], message)
        self.assertIn(message, data["notices"])

    def test_unsupported_and_unavailable_are_blocking_even_with_green_target(self):
        for mode in ("unsupported", "error"):
            with self.subTest(mode=mode):
                message = "LoxPanel zuerst in seiner eigenen Oberflaeche stoppen und erneut pruefen."
                data, check = self.preflight(report(False, mode, message))
                self.assertEqual(data["status"], "error")
                self.assertFalse(check["ok"])
                self.assertIn(message, data["warnings"])
                target = next(item for item in data["checks"] if item["name"] == "Backup-Ziel beschreibbar")
                self.assertTrue(target["ok"])

    def test_watchdog_failure_preserves_other_blocking_errors(self):
        message = "LoxPanel ist fuer die Sicherung nicht sicher angehalten."
        data, _ = self.preflight(report(False, "unsupported", message), FREE_INODES="0")
        self.assertEqual(data["status"], "error")
        self.assertEqual(len(data["warnings"]), 2)
        self.assertIn("keine freien Inodes", data["warnings"][0])
        self.assertEqual(data["warnings"][1], message)

    def test_start_and_worker_reject_before_backup_directory_and_service_stop(self):
        for entrypoint in ("start_backup", "create_backup"):
            with self.subTest(entrypoint=entrypoint):
                message = "LoxPanel zuerst selbst stoppen und erneut pruefen."
                env = self.prepare(report(False, "unsupported", message))
                script = runtime.PREFLIGHT_MOCKS + STUB + r'''
launch_background() { echo forbidden > "$TEST_ROOT/launch-called"; return 99; }
stop_backup_targets() { echo forbidden > "$TEST_ROOT/stop-called"; return 99; }
run_hook() { echo forbidden > "$TEST_ROOT/hook-called"; return 99; }
''' + f"\n{entrypoint} guard-error-{entrypoint}\n"
                result = self.run_shell(script, (*runtime.PREFLIGHT_FUNCTIONS, entrypoint), env, expected=17)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                for action in ("launch", "stop", "hook", "copy"):
                    self.assertFalse((self.root / (action + "-called")).exists())
                self.assertFalse((self.root / ("target/guard-error-" + entrypoint)).exists())
                task = json.loads((self.root / ("state/tasks/backup-guard-error-" + entrypoint + ".log.json")).read_text())
                self.assertEqual(task["phase"], "preflight_error")
                log = (self.root / ("state/logs/backup-guard-error-" + entrypoint + ".log")).read_text()
                self.assertIn(message, log)


if __name__ == "__main__":
    unittest.main()
