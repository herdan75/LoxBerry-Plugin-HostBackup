"""Run real stop/restart functions against isolated systemd/Docker doubles.

No backend entry point is sourced and no host service command can run. The
fixtures model canonical units, aliases, partial lookups and cancelled jobs;
all mutations are confined to disposable state files.
"""

import json
from pathlib import Path
import tempfile
import unittest

import test_runtime_safety as runtime


FUNCTIONS = (*runtime.JOURNAL_FUNCTIONS, "protected_systemd_service")
SYSTEMD_FIXTURE = r'''
systemctl() {
  printf '%s\n' "$*" >> "$TEST_ROOT/systemctl-calls"
  case "$1" in
    show)
      [ "$LC_ALL" = C ] || return 98
      [ "$#" -eq 10 ] && [ "$2:$3:$4:$5:$6:$7:$8:$9" = '--no-pager:-p:Id:-p:Names:-p:LoadState:--' ] || return 99
      local requested="${!#}"
      [ -f "$TEST_ROOT/properties-$requested" ] || return 4
      cat "$TEST_ROOT/properties-$requested"
      [ ! -f "$TEST_ROOT/show-status-$requested" ] || return "$(cat "$TEST_ROOT/show-status-$requested")"
      ;;
    is-active)
      [ "$#:$2" = '3:--quiet' ] || return 99
      [ -f "$TEST_ROOT/active-$3" ]
      ;;
    stop)
      [ "$#" -eq 2 ] || return 99
      grep -q '"phase":"intended"' "$RESTART_JOURNAL_DIR/backup-test.log/journal.json" || return 88
      printf 'stop %s\n' "$2" >> "$TEST_ROOT/service-calls"
      [ "${STILL_ACTIVE_UNIT:-}" = "$2" ] || rm -f -- "$TEST_ROOT/active-$2"
      if [ "${STOP_FAIL_UNIT:-}" = "$2" ]; then
        printf 'Job for %s canceled.\n' "$2" >&2
        return 1
      fi
      ;;
    start)
      [ "$#" -eq 2 ] || return 99
      printf 'start %s\n' "$2" >> "$TEST_ROOT/service-calls"
      [ "${START_FAIL_UNIT:-}" != "$2" ] || return 1
      : > "$TEST_ROOT/active-$2"
      ;;
    *) echo 'Unexpected systemctl operation; host access forbidden' >&2; return 99 ;;
  esac
}
timeout() {
  printf '%s\n' "$*" >> "$TEST_ROOT/timeout-calls"
  if [ "${1:-}" = -k ]; then
    [ "$1:$2:$3:$4:$5" = '-k:2s:15s:systemctl:show' ] || return 99
    [ "${LOOKUP_TIMEOUT:-false}" != true ] || return 124
    shift 3
  else
    case "$1:$2" in 45:systemctl|45:docker|15:docker) ;; *) return 99 ;; esac
    shift
  fi
  "$@"
}
selected_stop_targets() { cat "$TEST_ROOT/selections.tsv"; }
'''

CREATE_AND_STOP = r'''
state_dir="$(restart_journal_create backup-test.log)"
stop_backup_targets "$state_dir"
'''

NO_SYSTEMCTL = r'''
command() {
  if [ "${1:-}:${2:-}" = '-v:systemctl' ]; then return 1; fi
  builtin command "$@"
}
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required for isolated safety tests")
class SystemdStopSafetyTests(unittest.TestCase):
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-systemd-safety-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def unit(self, requested, canonical=None, names=None, active=True, load_state="loaded", raw=None, status=0):
        canonical = canonical or requested
        names = names or " ".join(dict.fromkeys((canonical, requested)))
        content = raw if raw is not None else f"Id={canonical}\nNames={names}\nLoadState={load_state}\n"
        (self.root / f"properties-{requested}").write_text(content, encoding="utf-8", newline="\n")
        if active:
            (self.root / f"active-{canonical}").touch()
        if status:
            (self.root / f"show-status-{requested}").write_text(str(status), encoding="utf-8")

    def select(self, *targets):
        (self.root / "selections.tsv").write_text("".join(f"{kind}\t{name}\n" for kind, name in targets), encoding="utf-8", newline="\n")

    def run_fixture(self, script=CREATE_AND_STOP, *, env=None, expected=0):
        return self.run_shell(SYSTEMD_FIXTURE + script, FUNCTIONS, env, expected)

    def lines(self, filename):
        path = self.root / filename
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def journal(self):
        return json.loads((self.root / "state/restart-journals/backup-test.log/journal.json").read_text(encoding="utf-8"))

    def test_saved_known_protected_units_are_skipped_without_any_systemd_query(self):
        protected = ("avahi-daemon.service", "dbus-org.freedesktop.Avahi.service", "ModemManager.service",
                     "dbus-org.freedesktop.ModemManager1.service", "dbus-broker.service", "ssh.service")
        self.select(*(("systemd", unit) for unit in protected))
        result = self.run_fixture()
        self.assertEqual(self.lines("systemctl-calls"), [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])
        self.assertEqual(result.stdout.count("Skipping protected systemd service"), len(protected))

    def test_unknown_alias_cannot_bypass_protected_canonical_or_alias_identity(self):
        self.unit("unrecognised-avahi.service", "avahi-daemon.service")
        self.unit("unrecognised-modem.service", "ModemManager.service")
        self.unit("renamed.service", names="renamed.service dbus-org.freedesktop.Avahi.service")
        self.select(*(("systemd", unit) for unit in ("unrecognised-avahi.service", "unrecognised-modem.service", "renamed.service")))
        result = self.run_fixture()
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])
        self.assertTrue(all(call.startswith("show ") for call in self.lines("systemctl-calls")))
        self.assertEqual(result.stdout.count("Skipping protected systemd service"), 3)

    def test_legacy_protected_selection_does_not_block_application_and_docker_backup(self):
        self.unit("mqtt-alias.service", "mosquitto.service")
        (self.root / "docker-active").touch()
        self.select(("systemd", "dbus-org.freedesktop.Avahi.service"), ("systemd", "ModemManager.service"),
                    ("systemd", "mqtt-alias.service"), ("docker", "database"))
        self.run_fixture(CREATE_AND_STOP + r'''
cp "$state_dir/journal.json" "$TEST_ROOT/stopped-journal.json"
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''')
        journal = json.loads((self.root / "stopped-journal.json").read_text())
        self.assertEqual({(entry["type"], entry["id"], entry["phase"]) for entry in journal["entries"]},
                         {("systemd", "mosquitto.service", "stopped"), ("docker", f"{123:064d}", "stopped")})
        self.assertEqual(self.lines("service-calls"), ["stop mosquitto.service", "docker-stop", "docker-start", "start mosquitto.service"])
        self.assertTrue((self.root / "active-mosquitto.service").exists())
        self.assertTrue((self.root / "docker-active").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_aliases_are_stopped_once_and_journal_records_canonical_identity(self):
        names = "influxd.service influxdb.service metrics.service"
        for requested in names.split():
            self.unit(requested, "influxd.service", names)
        self.select(*(("systemd", unit) for unit in ("metrics.service", "influxdb.service", "influxd.service")))
        self.run_fixture()
        self.assertEqual(self.lines("service-calls"), ["stop influxd.service"])
        self.assertEqual([(entry["type"], entry["id"], entry["phase"]) for entry in self.journal()["entries"]],
                         [("systemd", "influxd.service", "stopped")])

    def test_custom_dbus_alias_for_database_is_allowed_and_stopped_canonically(self):
        self.unit("dbus-custom-database.service", "postgresql.service")
        self.select(("systemd", "dbus-custom-database.service"))
        self.run_fixture()
        self.assertEqual(self.lines("service-calls"), ["stop postgresql.service"])

    def test_valid_escaped_alias_metadata_does_not_block_canonical_stop_and_recovery(self):
        self.unit("ordinary.service", names=r"ordinary.service ordinary\x2dalias.service")
        self.select(("systemd", "ordinary.service"))
        self.run_fixture(CREATE_AND_STOP + r'''
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''')
        self.assertEqual(self.lines("service-calls"), ["stop ordinary.service", "start ordinary.service"])
        self.assertTrue((self.root / "active-ordinary.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_missing_systemctl_rejects_unprotected_native_selection_before_docker(self):
        self.unit("ordinary.service")
        (self.root / "docker-active").touch()
        self.select(("systemd", "ordinary.service"), ("docker", "database"))
        result = self.run_fixture(NO_SYSTEMCTL + CREATE_AND_STOP, expected=1)
        self.assertIn("systemctl", result.stdout + result.stderr)
        self.assertEqual(self.lines("systemctl-calls"), [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])
        self.assertTrue((self.root / "active-ordinary.service").exists())
        self.assertTrue((self.root / "docker-active").exists())

    def test_missing_systemctl_does_not_block_protected_only_selection(self):
        self.select(("systemd", "dbus-org.freedesktop.Avahi.service"), ("systemd", "ModemManager.service"))
        result = self.run_fixture(NO_SYSTEMCTL + CREATE_AND_STOP)
        self.assertEqual(result.stdout.count("Skipping protected systemd service"), 2)
        self.assertEqual(self.lines("systemctl-calls"), [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])

    def test_missing_systemctl_does_not_block_docker_only_selection(self):
        (self.root / "docker-active").touch()
        self.select(("docker", "database"))
        self.run_fixture(NO_SYSTEMCTL + CREATE_AND_STOP + r'''
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''')
        self.assertEqual(self.lines("systemctl-calls"), [])
        self.assertEqual(self.lines("service-calls"), ["docker-stop", "docker-start"])
        self.assertTrue((self.root / "docker-active").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_valid_loaded_and_masked_identity_responses_are_accepted_and_bounded(self):
        for state in ("loaded", "masked"):
            with self.subTest(state=state):
                self.unit("alias.service", "canonical.service", load_state=state, active=False)
                result = self.run_fixture('systemd_stop_identity alias.service\n')
                self.assertEqual(result.stdout, "allowed\tcanonical.service\n")
        self.assertTrue(all(line.startswith("-k 2s 15s systemctl show ") for line in self.lines("timeout-calls")))

    def test_partial_duplicate_malformed_or_unrelated_identity_is_rejected(self):
        cases = (
            "Id=alias.service\nNames=alias.service\n",
            "Id=alias.service\nLoadState=loaded\n",
            "Names=alias.service\nLoadState=loaded\n",
            "Id=alias.service\nNames=alias.service\nLoadState=loaded\nId=alias.service\n",
            "Id=alias.service\nNames=alias.service\nLoadState=not-found\n",
            "Id=alias.service\nNames=alias.service\nLoadState=error\n",
            "Id=other.service\nNames=other.service\nLoadState=loaded\n",
            "Id=alias.service\nNames=alias.service invalid/name.service\nLoadState=loaded\n",
            "Id=demo@.service\nNames=alias.service demo@.service\nLoadState=loaded\n",
            "Id=alias.service\nNames=alias.service\nLoadState=loaded\nUnexpected=data\n",
            "Id=alias.service\nNames=alias.service $(touch forbidden)\nLoadState=loaded\n",
            "Id=alias.service\nNames=\nLoadState=loaded\n",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.unit("alias.service", raw=raw, active=False)
                result = self.run_fixture('systemd_stop_identity alias.service\n', expected=1)
                self.assertEqual(result.stdout, "")
                self.assertFalse((self.root / "forbidden").exists())
        self.assertEqual(self.lines("service-calls"), [])

    def test_nonzero_lookup_does_not_trust_otherwise_valid_output(self):
        self.unit("demo.service", status=7)
        self.select(("systemd", "demo.service"))
        result = self.run_fixture(expected=1)
        self.assertIn("Cannot safely resolve systemd service demo.service", result.stdout)
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])

    def test_missing_and_timed_out_lookup_never_proceed_to_docker(self):
        self.select(("systemd", "missing.service"), ("docker", "database"))
        result = self.run_fixture(expected=1)
        self.assertIn("Cannot safely resolve systemd service missing.service", result.stdout)
        self.assertEqual(self.lines("service-calls"), [])
        self.assertEqual(self.journal()["entries"], [])
        self.unit("demo.service")
        result = self.run_fixture('systemd_stop_identity demo.service\n', env={"LOOKUP_TIMEOUT": "true"}, expected=1)
        self.assertEqual(result.stdout, "")

    def test_cancelled_stop_remains_failed_even_when_unit_became_inactive_and_cleanup_restarts_it(self):
        self.unit("application.service")
        self.unit("telegraf.service")
        self.select(("systemd", "application.service"), ("systemd", "telegraf.service"), ("docker", "database"))
        result = self.run_fixture(r'''
state_dir="$(restart_journal_create backup-test.log)"
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
trap 'result=$?; trap - EXIT; backup_cleanup_on_exit "$result" "$TEST_ROOT/missing" "$log_file" false "" backup-test.log "$state_dir"; exit "$result"' EXIT
stop_backup_targets "$state_dir"
echo forbidden-copy > "$TEST_ROOT/copy-called"
''', env={"STOP_FAIL_UNIT": "application.service"}, expected=1)
        self.assertIn("Job for application.service canceled.", result.stderr)
        self.assertIn("failed (exit status 1); backup will not continue", result.stdout)
        self.assertFalse((self.root / "copy-called").exists())
        self.assertEqual(self.lines("service-calls"), ["stop application.service", "stop telegraf.service",
                                                      "start telegraf.service", "start application.service"])
        self.assertTrue((self.root / "active-application.service").exists())
        self.assertTrue((self.root / "active-telegraf.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        self.assertEqual((task["state"], task["phase"]), ("failed", "failed"))

    def test_success_exit_without_actual_stop_is_still_an_error(self):
        self.unit("demo.service")
        self.select(("systemd", "demo.service"))
        result = self.run_fixture(env={"STILL_ACTIVE_UNIT": "demo.service"}, expected=1)
        self.assertIn("systemd service demo.service is still active", result.stdout)
        self.assertEqual(self.journal()["entries"][0]["phase"], "intended")

    def test_preexisting_protected_alias_journal_can_still_restore_previously_stopped_service(self):
        self.run_fixture(r'''
state_dir="$(restart_journal_create backup-test.log)"
restart_journal_update "$state_dir" intended systemd dbus-org.freedesktop.Avahi.service
restart_journal_update "$state_dir" stopped systemd dbus-org.freedesktop.Avahi.service
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''')
        self.assertEqual(self.lines("service-calls"), ["start dbus-org.freedesktop.Avahi.service"])
        self.assertTrue((self.root / "active-dbus-org.freedesktop.Avahi.service").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())


if __name__ == "__main__":
    unittest.main()
