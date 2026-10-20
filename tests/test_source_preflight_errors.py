"""Real shell source checks fail closed without an infrastructure traceback.

Only isolated test paths and mocked host services are used. The actual wrapper,
preflight, start gate and worker EXIT cleanup come from hostbackup.sh.
"""

import json
import os
from pathlib import Path
import stat
import unittest

import test_runtime_safety as runtime


VALID = {"status": "ok", "selection": {"policy": "local", "overrides": {}},
         "errors": [], "notices": ["Quellen sicher ermittelt."], "volumes": []}
SOURCE_STUB = r'''
source_info() {
  printf 'called\n' >> "$TEST_ROOT/source-called"
  cat -- "$TEST_ROOT/source-response"
  cat -- "$TEST_ROOT/source-diagnostic" >&2
  return "$SOURCE_EXIT"
}
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required")
class SourcePreflightErrorTests(unittest.TestCase):
    setUp = runtime.RuntimeSafetyTests.setUp
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def prepare(self, payload=b"", diagnostic=b"", code=0):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload).encode("utf-8")
        if not isinstance(diagnostic, bytes):
            diagnostic = diagnostic.encode("utf-8")
        (self.root / "source-response").write_bytes(payload)
        (self.root / "source-diagnostic").write_bytes(diagnostic)
        return {"SOURCE_EXIT": str(code), "NO_ESTIMATE": "true", "FREE_MB": "20000"}

    def assert_clean(self, result, error_report=False):
        if error_report:
            self.assertEqual(json.loads(result.stderr)["status"], "error")
        else:
            self.assertEqual(result.stderr, "", result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertNotIn("JSONDecodeError", result.stdout + result.stderr)
        self.assertEqual(list((self.root / "state").glob(".source-check.*")), [])
        self.assertFalse((self.root / "copy-called").exists())
        self.assertFalse((self.root / "service-calls").exists())

    def preflight(self, payload=b"", diagnostic=b"", code=0, snapshot=False):
        env = self.prepare(payload, diagnostic, code)
        if snapshot:
            env.update(TEST_METADATA_MODE="portable-archive", TEST_BACKUP_MODE="snapshot")
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + SOURCE_STUB + "\npreflight_backup\n",
                                runtime.PREFLIGHT_FUNCTIONS, env)
        self.assert_clean(result)
        data = json.loads(result.stdout)
        check = next(item for item in data["checks"] if item["name"] == "Datenquellen-Auswahl")
        return data, check

    def test_valid_result_preserves_selection_and_notices(self):
        for snapshot in (False, True):
            with self.subTest(snapshot=snapshot):
                data, check = self.preflight(VALID, snapshot=snapshot)
                self.assertEqual(data["status"], "ok")
                self.assertTrue(check["ok"])
                self.assertEqual(data["source_selection"], VALID)
                # The Windows Python shim emits CRLF into Bash read; Linux,
                # the production platform, emits the original LF only.
                notices = [item.removesuffix("\r") for item in data["notices"]] if os.name == "nt" else data["notices"]
                self.assertIn(VALID["notices"][0], notices)

    def test_empty_helper_failure_preserves_actionable_reason_in_all_modes(self):
        reason = 'Quellenauswahl: Ausgewaehlte Quelle ist nicht eingebunden: /mnt/NAS "Daten".'
        for snapshot in (False, True):
            with self.subTest(snapshot=snapshot):
                data, check = self.preflight(diagnostic=reason + "\n", code=1, snapshot=snapshot)
                self.assertEqual(data["status"], "error")
                self.assertFalse(check["ok"])
                self.assertIn(reason, check["details"])
                self.assertIn("Exit-Code 1", check["details"])
                self.assertEqual(data["warnings"], data["source_selection"]["errors"])
                self.assertEqual(data["source_selection"]["volumes"], [])

    def test_traceback_frame_is_not_published_but_domain_error_is(self):
        diagnostic = ('Traceback (most recent call last):\n'
                      '  File "/private/engine.py", line 99, in main\n'
                      '    raise ValueError("details")\n'
                      'ValueError: Ausgewaehlte Quelle ist nicht eingebunden: /mnt/NAS\n')
        data, check = self.preflight(diagnostic=diagnostic, code=1)
        self.assertEqual(data["status"], "error")
        self.assertIn("Ausgewaehlte Quelle", check["details"])
        self.assertNotIn("/private/engine.py", check["details"])
        self.assertNotIn("ValueError", check["details"])

    def test_valid_json_error_keeps_inventory_for_correction(self):
        report = {"status": "error", "errors": ["Bewusst gewaehlte Quelle /mnt/nas fehlt."],
                  "volumes": [{"path": "/", "included": True}], "notices": []}
        for code in (0, 1):
            with self.subTest(code=code):
                data, check = self.preflight(report, "less useful infrastructure detail", code)
                self.assertEqual(data["status"], "error")
                self.assertIn(report["errors"][0], check["details"])
                self.assertNotIn("infrastructure", check["details"])
                self.assertEqual(data["source_selection"]["volumes"], report["volumes"])

    def test_unsuccessful_exit_cannot_be_overridden_by_ok_payload(self):
        data, check = self.preflight(VALID, code=7, snapshot=True)
        self.assertEqual(data["status"], "error")
        self.assertFalse(check["ok"])
        self.assertEqual(data["source_selection"]["status"], "error")
        self.assertIn("Exit-Code 7", check["details"])

    def test_real_source_info_empty_error_does_not_trigger_json_traceback(self):
        env = self.prepare()
        script = runtime.PREFLIGHT_MOCKS + runtime.function("source_info") + r'''
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-sources.py" ]; then
    printf 'Quellenauswahl: Mountpunkt enthaelt einen ungueltigen Pfad.\n' >&2
    return 1
  fi
  "$RUNTIME_PYTHON" "$@"
}
preflight_backup
'''
        result = self.run_shell(script, runtime.PREFLIGHT_FUNCTIONS, env)
        self.assert_clean(result)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "error")
        self.assertIn("Mountpunkt", data["warnings"][0])
        self.assertEqual(list((self.root / "state").glob(".source-rules.*")), [])

    def test_empty_malformed_and_wrong_shape_results_are_structured_errors(self):
        cases = [b"", b" \n", b"{", b"null", b"[]", b"true", b'"ok"', b"1",
                 {}, {"status": "unknown"}, {"status": "ok"},
                 {**VALID, "selection": []}, {**VALID, "selection": {"policy": "local"}},
                 {**VALID, "selection": {"policy": "local", "overrides": {"/": "true"}}},
                 {**VALID, "errors": "failed"}, {**VALID, "errors": [1]},
                 {**VALID, "notices": None}, {**VALID, "volumes": {}},
                 {**VALID, "status": "error", "errors": []},
                 b'{"status":"ok","value":NaN}', b"\xff", b"{}\0"]
        for payload in cases:
            with self.subTest(payload=payload):
                env = self.prepare(payload)
                result = self.run_shell(runtime.PREFLIGHT_MOCKS + SOURCE_STUB + "\nchecked_source_info\n",
                                        env=env, expected=18)
                self.assert_clean(result)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "error")
                self.assertTrue(report["errors"])
                self.assertIsInstance(report["volumes"], list)

    def test_full_preflight_rejects_malformed_or_missing_selection_without_lineage_traceback(self):
        for payload in (b"{", {"status": "ok"}, {**VALID, "notices": [None]}):
            with self.subTest(payload=payload):
                data, check = self.preflight(payload, snapshot=True)
                self.assertEqual(data["status"], "error")
                self.assertFalse(check["ok"])
                self.assertIn("kein gueltiges", check["details"])

    def test_malformed_payload_with_failed_helper_remains_error(self):
        data, check = self.preflight(b"{", code=1, snapshot=True)
        self.assertEqual(data["status"], "error")
        self.assertFalse(check["ok"])
        self.assertIn("kein gueltiges", check["details"])
        self.assertIn("Exit-Code 1", check["details"])

    def test_mktemp_failure_is_structured_and_does_not_invoke_helper(self):
        env = self.prepare(VALID)
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + SOURCE_STUB + r'''
mktemp() { return 1; }
checked_source_info
''', env=env, expected=18)
        self.assert_clean(result)
        self.assertIn("Pruefdateien", json.loads(result.stdout)["errors"][0])
        self.assertFalse((self.root / "source-called").exists())

    def test_capture_is_private_and_cleaned_after_helper_failure(self):
        env = self.prepare(code=1)
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + r'''
source_info() {
  printf 'temporary\n'
  printf 'domain error\n' >&2
  cp -a -- "$ROOT_STATE_DIR"/.source-check.* "$TEST_ROOT/capture-evidence"
  return 1
}
checked_source_info
''', env=env, expected=18)
        self.assert_clean(result)
        evidence = self.root / "capture-evidence"
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o700)
            for name in ("stdout", "stderr"):
                self.assertEqual(stat.S_IMODE((evidence / name).stat().st_mode), 0o600)

    def test_failed_source_preflight_blocks_start_and_worker_before_service_stop(self):
        for entrypoint in ("start_backup", "create_backup"):
            with self.subTest(entrypoint=entrypoint):
                env = self.prepare(diagnostic="Quellenauswahl: Datenquelle /mnt/nas fehlt.\n", code=1)
                result = self.run_shell(runtime.PREFLIGHT_MOCKS + SOURCE_STUB + r'''
launch_background() { echo forbidden > "$TEST_ROOT/launch-called"; return 99; }
stop_backup_targets() { echo forbidden > "$TEST_ROOT/stop-called"; return 99; }
''' + f"\n{entrypoint} source-error-{entrypoint}\n",
                                        (*runtime.PREFLIGHT_FUNCTIONS, entrypoint), env, expected=17)
                self.assert_clean(result, error_report=entrypoint == "start_backup")
                task = json.loads((self.root / f"state/tasks/backup-source-error-{entrypoint}.log.json").read_text())
                self.assertEqual(task["phase"], "preflight_error")
                self.assertFalse((self.root / "launch-called").exists())
                self.assertFalse((self.root / "stop-called").exists())
                self.assertFalse((self.root / f"target/source-error-{entrypoint}").exists())

    def test_worker_source_failure_after_stop_is_logged_and_recovers_services(self):
        reason = "Quellenauswahl: Ausgewaehlte Quelle /mnt/nas wurde zwischenzeitlich entfernt."
        env = self.prepare(diagnostic=reason + "\n", code=1)
        result = self.run_shell(runtime.PREFLIGHT_MOCKS + SOURCE_STUB + r'''
preflight_backup() { printf '%s\n' '{"status":"ok"}'; }
write_backup_marker() { :; }
write_manifest() { printf '{"status":"%s","size_bytes":0,"files_count":0,"started_at":"fixture"}\n' "$3" > "$1/manifest.json"; }
: > "$TEST_ROOT/active-demo.service"
stop_backup_targets() {
  restart_journal_update "$1" intended systemd demo.service
  systemctl stop -- demo.service
  restart_journal_update "$1" stopped systemd demo.service
}
create_backup test
''', (*runtime.JOURNAL_FUNCTIONS, "manifest_started_at", "create_backup"), env, expected=18)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", result.stdout)
        self.assertTrue((self.root / "active-demo.service").exists())
        self.assertEqual((self.root / "service-calls").read_text().splitlines(),
                         ["stop demo.service", "start demo.service"])
        self.assertFalse((self.root / "copy-called").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual(list((self.root / "state").glob(".source-check.*")), [])
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        self.assertEqual((task["state"], task["exit_status"]), ("failed", 18))
        log = (self.root / "state/logs/backup-test.log").read_text()
        self.assertIn("ERROR: " + reason, log)
        self.assertNotIn("Traceback", log)


if __name__ == "__main__":
    unittest.main()
