"""Run real stop/restart functions against isolated systemd/Docker doubles.

No backend entry point is sourced and no host service command can run. The
fixtures model canonical units, aliases, partial lookups and cancelled jobs;
all mutations are confined to disposable state files.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_runtime_safety as runtime


FUNCTIONS = (*runtime.JOURNAL_FUNCTIONS, "protected_systemd_service", "selected_stop_targets")
SYSTEMD_FIXTURE = r'''
CONFIG_FILE="$TEST_ROOT/stop-config.json"
systemd_fixture_name() {
  if [[ "$1" == *:* || "$1" == *\\* ]] || [ "${#1}" -gt 200 ]; then
    printf 'id-'; printf '%s' "$1" | sha256sum | cut -d ' ' -f 1
  else printf '%s' "$1"; fi
}
systemctl() {
  printf '%s\n' "$*" >> "$TEST_ROOT/systemctl-calls"
  case "$1" in
    show)
      [ "$LC_ALL" = C ] || return 98
      [ "$#" -eq 10 ] && [ "$2:$3:$4:$5:$6:$7:$8:$9" = '--no-pager:-p:Id:-p:Names:-p:LoadState:--' ] || return 99
      local requested="$(systemd_fixture_name "${!#}")"
      [ -f "$TEST_ROOT/properties-$requested" ] || return 4
      cat "$TEST_ROOT/properties-$requested"
      [ ! -f "$TEST_ROOT/show-status-$requested" ] || return "$(cat "$TEST_ROOT/show-status-$requested")"
      ;;
    is-active)
      [ "$#:$2:$3" = '4:--quiet:--' ] || return 99
      [ -f "$TEST_ROOT/active-$(systemd_fixture_name "$4")" ]
      ;;
    stop)
      [ "$#:$2" = '3:--' ] || return 99
      grep -q '"phase":"intended"' "$RESTART_JOURNAL_DIR/backup-test.log/journal.json" || return 88
      printf 'stop %s\n' "$3" >> "$TEST_ROOT/service-calls"
      [ "${STILL_ACTIVE_UNIT:-}" = "$3" ] || rm -f -- "$TEST_ROOT/active-$(systemd_fixture_name "$3")"
      if [ "${STOP_FAIL_UNIT:-}" = "$3" ]; then
        printf 'Job for %s canceled.\n' "$3" >&2
        return 1
      fi
      ;;
    start)
      [ "$#:$2" = '3:--' ] || return 99
      printf 'start %s\n' "$3" >> "$TEST_ROOT/service-calls"
      [ "${START_FAIL_UNIT:-}" != "$3" ] || return 1
      : > "$TEST_ROOT/active-$(systemd_fixture_name "$3")"
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

SQUEEZELITE_SERVICES = (
    "mosquitto.service", "squeezelite-lbp-mixer.service",
    "squeezelite-lbp@inst_bad.service", "squeezelite-lbp@inst_wozi_k_che.service",
)

INTERRUPTIBLE_STOP = r'''
state_dir="$(restart_journal_create backup-test.log)"
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
trap 'result=$?; trap - EXIT; cp "$state_dir/journal.json" "$TEST_ROOT/before-cleanup.json"; backup_cleanup_on_exit "$result" "$TEST_ROOT/missing" "$log_file" false "" backup-test.log "$state_dir"; exit "$result"' EXIT
stop_backup_targets "$state_dir"
echo forbidden-copy > "$TEST_ROOT/copy-called"
'''


@unittest.skipUnless(runtime.BASH and Path(runtime.BASH).exists(), "Bash is required for isolated safety tests")
class SystemdStopSafetyTests(unittest.TestCase):
    run_shell = runtime.RuntimeSafetyTests.run_shell

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-systemd-safety-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def fixture_name(name):
        return "id-" + hashlib.sha256(name.encode()).hexdigest() if ":" in name or "\\" in name or len(name) > 200 else name

    def unit(self, requested, canonical=None, names=None, active=True, load_state="loaded", raw=None, status=0):
        canonical = canonical or requested
        names = names or " ".join(dict.fromkeys((canonical, requested)))
        content = raw if raw is not None else f"Id={canonical}\nNames={names}\nLoadState={load_state}\n"
        # Encode only disposable fixture paths, never original command IDs.
        (self.root / f"properties-{self.fixture_name(requested)}").write_text(content, encoding="utf-8", newline="\n")
        if active:
            (self.root / f"active-{self.fixture_name(canonical)}").touch()
        if status:
            (self.root / f"show-status-{self.fixture_name(requested)}").write_text(str(status), encoding="utf-8")

    def select(self, *targets):
        (self.root / "stop-config.json").write_text(json.dumps({"stop_targets": [
            {"type": kind, "name": name} for kind, name in targets]}), encoding="utf-8", newline="\n")

    def run_fixture(self, script=CREATE_AND_STOP, *, env=None, expected=0):
        return self.run_shell(SYSTEMD_FIXTURE + script, FUNCTIONS, env, expected)

    def lines(self, filename):
        path = self.root / filename
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def journal(self):
        return json.loads((self.root / "state/restart-journals/backup-test.log/journal.json").read_text(encoding="utf-8"))

    def prepare_squeezelite_and_docker(self):
        for name in SQUEEZELITE_SERVICES:
            self.unit(name)
        (self.root / "docker-active").touch()
        self.select(*(("systemd", name) for name in SQUEEZELITE_SERVICES), ("docker", "sonn-core"))

    def test_squeezelite_instances_and_sonn_core_complete_real_stop_journal_and_cleanup_cycle(self):
        self.prepare_squeezelite_and_docker()
        result = self.run_fixture(CREATE_AND_STOP + r'''
cp "$state_dir/journal.json" "$TEST_ROOT/stopped-journal.json"
log_file="$TASK_LOG_DIR/backup-test.log"
prepare_log_file "$log_file" truncate
backup_cleanup_on_exit 0 "$TEST_ROOT/missing" "$log_file" false '' backup-test.log "$state_dir"
''')
        journal = json.loads((self.root / "stopped-journal.json").read_text())
        self.assertEqual([(entry["type"], entry["id"], entry["phase"]) for entry in journal["entries"]],
                         [("systemd", name, "stopped") for name in SQUEEZELITE_SERVICES]
                         + [("docker", f"{123:064d}", "stopped")])
        self.assertEqual(journal["entries"][-1]["label"], "sonn-core")
        self.assertEqual(self.lines("service-calls"), [f"stop {name}" for name in SQUEEZELITE_SERVICES]
                         + ["docker-stop", "docker-start"]
                         + [f"start {name}" for name in reversed(SQUEEZELITE_SERVICES)])
        self.assertTrue(all((self.root / f"active-{name}").exists() for name in SQUEEZELITE_SERVICES))
        self.assertTrue((self.root / "docker-active").exists())
        self.assertNotIn("Invalid restart", result.stdout + result.stderr)
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_actual_backup_worker_finishes_with_squeezelite_instances_and_sonn_core(self):
        self.prepare_squeezelite_and_docker()
        source_data = b"isolated backup fixture\n"
        (self.root / "source-data.txt").write_bytes(source_data)
        result = self.run_shell(SYSTEMD_FIXTURE + runtime.PREFLIGHT_MOCKS + r'''
preflight_backup() { printf '{"status":"ok"}\n'; }
json_get_bool() { echo false; }
write_backup_marker() { :; }
write_manifest() { printf '{"status":"%s"}\n' "$3" > "$1/manifest.json"; }
rsync_live_options() { :; }
rsync_metadata_options() { :; }
rsync_destination() { printf '%s\n' "$2"; }
rsync() {
  # Never copy the host /. The production worker runs unchanged, but its copy
  # dependency is restricted to one known disposable source and destination.
  [[ "${!#}" == "$TEST_ROOT/target/test/rootfs/" ]] || return 99
  for unit in mosquitto.service squeezelite-lbp-mixer.service squeezelite-lbp@inst_bad.service squeezelite-lbp@inst_wozi_k_che.service; do
    [ ! -f "$TEST_ROOT/active-$unit" ] || return 98
  done
  [ ! -f "$TEST_ROOT/docker-active" ] || return 98
  cp "$RESTART_JOURNAL_DIR/backup-test.log/journal.json" "$TEST_ROOT/copy-journal.json"
  cp "$TASK_DIR/backup-test.log.json" "$TEST_ROOT/copy-state.json"
  cp -- "$TEST_ROOT/source-data.txt" "$TEST_ROOT/target/test/rootfs/fixture.txt"
}
calculate_size() { wc -c < "$TEST_ROOT/source-data.txt"; }
calculate_files() { echo 1; }
validate_completed_backup() {
  cmp -- "$TEST_ROOT/source-data.txt" "$TEST_ROOT/target/test/rootfs/fixture.txt" || return 1
  for unit in mosquitto.service squeezelite-lbp-mixer.service squeezelite-lbp@inst_bad.service squeezelite-lbp@inst_wozi_k_che.service; do
    [ -f "$TEST_ROOT/active-$unit" ] || return 98
  done
  [ -f "$TEST_ROOT/docker-active" ] || return 98
  cp "$TASK_DIR/backup-test.log.json" "$TEST_ROOT/validation-state.json"
}
prune_old_backups() { cp "$TASK_DIR/backup-test.log.json" "$TEST_ROOT/retention-state.json"; }
create_backup test
''', (*FUNCTIONS, "create_backup"), {"TEST_BACKUP_MODE": "full"})
        self.assertEqual((self.root / "target/test/rootfs/fixture.txt").read_bytes(), source_data)
        phases = {name: json.loads((self.root / f"{name}-state.json").read_text())
                  for name in ("copy", "validation", "retention")}
        self.assertEqual([(phases[name]["state"], phases[name]["phase"]) for name in phases],
                         [("running", "copying"), ("running", "validating"), ("running", "retention")])
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        manifest = json.loads((self.root / "target/test/manifest.json").read_text())
        self.assertEqual((task["state"], task["phase"], manifest["status"]), ("finished", "complete", "complete"))
        copy_journal = json.loads((self.root / "copy-journal.json").read_text())
        self.assertEqual([(entry["type"], entry["id"], entry["phase"]) for entry in copy_journal["entries"]],
                         [("systemd", name, "stopped") for name in SQUEEZELITE_SERVICES]
                         + [("docker", f"{123:064d}", "stopped")])
        self.assertEqual(self.lines("service-calls"), [f"stop {name}" for name in SQUEEZELITE_SERVICES]
                         + ["docker-stop", "docker-start"]
                         + [f"start {name}" for name in reversed(SQUEEZELITE_SERVICES)])
        self.assertEqual(list((self.root / "state/restart-journals").iterdir()), [])
        self.assertIn("Backup copy finished with status 0", result.stdout)
        self.assertNotIn("Invalid restart", result.stdout + result.stderr)

    def test_existing_instance_and_colon_journal_entries_recover_without_rewriting_identity(self):
        identities = ("squeezelite-lbp@inst_bad.service", "worker:zone.service", "worker@zone:one.service")
        data = {"task": "backup-test.log", "entries": [
            {"type": "systemd", "id": identity, "phase": "stopped", "updated_at": 1} for identity in identities]}
        self.run_fixture(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf '%s\n' "$SEEDED_JOURNAL" > "$state_dir/journal.json"
start_backup_targets_if_needed "$state_dir"
cp "$state_dir/journal.json" "$TEST_ROOT/restarted-journal.json"
restart_journal_finish "$state_dir"
''', env={"SEEDED_JOURNAL": json.dumps(data)})
        restarted = json.loads((self.root / "restarted-journal.json").read_text())
        self.assertEqual([(entry["id"], entry["phase"]) for entry in restarted["entries"]],
                         [(identity, "restarted") for identity in identities])
        self.assertEqual(self.lines("service-calls"), [f"start {identity}" for identity in reversed(identities)])
        self.assertTrue(all((self.root / f"active-{self.fixture_name(identity)}").exists() for identity in identities))
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())

    def test_supported_systemd_name_matrix_is_passed_literally_through_stop_journal_and_restart(self):
        names = ("_prefix.service", ":prefix.service", "-prefix.service", ".prefix.service", r"escaped\x2dname.service",
                 r"literal\q.service", "prefix@part@second.service", "a" * 247 + ".service")
        self.assertEqual(len(names[-1]), 255)
        expected_calls = []
        for name in names:
            with self.subTest(name=name):
                self.unit(name)
                self.select(("systemd", name))
                self.run_fixture(CREATE_AND_STOP + r'''
cp "$state_dir/journal.json" "$TEST_ROOT/matrix-journal.json"
start_backup_targets_if_needed "$state_dir"
restart_journal_finish "$state_dir"
''')
                entry, = json.loads((self.root / "matrix-journal.json").read_text())["entries"]
                self.assertEqual((entry["id"], entry["phase"]), (name, "stopped"))
                expected_calls.extend((f"stop {name}", f"start {name}"))
                self.assertEqual(self.lines("service-calls"), expected_calls)
                calls = self.lines("systemctl-calls")
                self.assertIn(f"stop -- {name}", calls)
                self.assertIn(f"start -- {name}", calls)
                self.assertIn(f"is-active --quiet -- {name}", calls)
                self.assertTrue((self.root / f"active-{self.fixture_name(name)}").exists())
                self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertNotIn("stop escaped-name.service", self.lines("service-calls"))

    def test_oversized_and_invalid_systemd_names_cannot_pass_real_selection_reader(self):
        invalid = ("a" * 248 + ".service", "@instance.service", "prefix@.service", ".service",
                   "white space.service", "line\nname.service", "path/name.service", "glob*.service",
                   "glob?.service", "glob[1].service", "shell;name.service", "dollar$name.service", "ümlaut.service")
        self.assertEqual(len(invalid[0]), 256)
        for name in invalid:
            with self.subTest(name=name):
                self.select(("systemd", "mosquitto.service"), ("systemd", name))
                result = self.run_fixture('selected_stop_targets\n', expected=255)
                self.assertEqual(result.stdout, "")
        self.assertEqual(self.lines("service-calls"), [])

    def test_journal_rejects_whitespace_and_injection_identities_without_changing_intents(self):
        invalid = ("", " bad.service", "bad.service ", "bad name.service", "bad\tname.service", "bad\nname.service",
                   "bad.service\r", "@leading.service", "/tmp/bad.service", "bad;touch forbidden.service",
                   "$(touch forbidden).service", "`touch forbidden`.service", "bad'quote.service", "bad\"quote.service")
        (self.root / "invalid-identities.bin").write_bytes(b"\0".join(value.encode() for value in invalid) + b"\0")
        result = self.run_fixture(r'''
state_dir="$(restart_journal_create backup-test.log)"
while IFS= read -r -d '' identity; do
  if restart_journal_update "$state_dir" intended systemd "$identity"; then
    echo 'Invalid identity unexpectedly accepted' >&2
    exit 97
  fi
  printf 'rejected\n'
done < "$TEST_ROOT/invalid-identities.bin"
''')
        self.assertEqual(result.stdout.splitlines(), ["rejected"] * len(invalid))
        self.assertEqual(result.stderr.count("Invalid restart operation"), len(invalid))
        self.assertEqual(self.journal()["entries"], [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertFalse((self.root / "forbidden").exists())

    def test_malformed_selected_identity_is_rejected_before_any_stop_or_intent(self):
        self.unit("demo.service", raw="Id=demo@inst;touch forbidden.service\nNames=demo.service\nLoadState=loaded\n")
        self.select(("systemd", "demo.service"), ("docker", "sonn-core"))
        result = self.run_fixture(expected=1)
        self.assertIn("Cannot safely resolve systemd service demo.service", result.stdout)
        self.assertEqual(self.journal()["entries"], [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertFalse((self.root / "forbidden.service").exists())

    def test_invalid_last_saved_target_aborts_before_stopping_any_valid_service(self):
        self.unit("mosquitto.service")
        self.select(("systemd", "mosquitto.service"), ("docker", "sonn-core\nsystemd\tother.service"))
        result = self.run_fixture(expected=20)
        self.assertNotEqual(result.stderr.strip(), "")
        self.assertEqual(self.journal()["entries"], [])
        self.assertEqual(self.lines("systemctl-calls"), [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertTrue((self.root / "active-mosquitto.service").exists())
        self.assertEqual((self.root / "state/restart-journals/backup-test.log/selected-stop-targets.tsv").read_text(), "")

    def test_later_unresolvable_service_aborts_before_stopping_earlier_valid_service(self):
        self.unit("mosquitto.service")
        self.unit("squeezelite-lbp@inst_bad.service", raw="Id=squeezelite-lbp@inst_bad.service\nNames=squeezelite-lbp@inst_bad.service\n")
        self.select(("systemd", "mosquitto.service"), ("systemd", "squeezelite-lbp@inst_bad.service"), ("docker", "sonn-core"))
        result = self.run_fixture(expected=1)
        self.assertIn("Cannot safely resolve systemd service squeezelite-lbp@inst_bad.service", result.stdout)
        self.assertEqual(self.journal()["entries"], [])
        self.assertEqual(self.lines("service-calls"), [])
        self.assertTrue((self.root / "active-mosquitto.service").exists())
        self.assertTrue((self.root / "active-squeezelite-lbp@inst_bad.service").exists())

    def test_real_selection_reader_rejects_invalid_final_entries_without_partial_output(self):
        invalid_targets = (
            None, "invalid", {"type": "systemd"}, {"type": "other", "name": "demo.service"},
            {"type": "systemd", "name": "demo@.service"}, {"type": "systemd", "name": "demo.service "},
            {"type": "systemd", "name": "demo\tname.service"}, {"type": "systemd", "name": "$(touch forbidden).service"},
            {"type": "systemd", "name": "demo;touch forbidden.service"}, {"type": "docker", "name": "sonn-core\nsystemd\tother.service"},
            {"type": "docker", "name": "-option"}, {"type": "docker", "name": ["sonn-core"]},
        )
        for target in invalid_targets:
            with self.subTest(target=target):
                (self.root / "stop-config.json").write_text(json.dumps({"stop_targets": [
                    {"type": "systemd", "name": "mosquitto.service"}, target]}), encoding="utf-8")
                result = self.run_fixture('selected_stop_targets\n', expected=255)
                self.assertEqual(result.stdout, "")
                self.assertNotEqual(result.stderr.strip(), "")
        self.assertEqual(self.lines("service-calls"), [])
        self.assertFalse((self.root / "forbidden").exists())

    def test_real_selection_reader_keeps_empty_legacy_config_but_rejects_malformed_settings(self):
        for content in ("{}", '{"stop_targets":[]}'):
            with self.subTest(valid=content):
                (self.root / "stop-config.json").write_text(content, encoding="utf-8")
                result = self.run_fixture('selected_stop_targets\n')
                self.assertEqual(result.stdout + result.stderr, "")
        for content in ("{broken", "[]", "null", '{"stop_targets":null}', '{"stop_targets":{}}', '{"stop_targets":"invalid"}'):
            with self.subTest(invalid=content):
                (self.root / "stop-config.json").write_text(content, encoding="utf-8")
                result = self.run_fixture('selected_stop_targets\n', expected=255)
                self.assertEqual(result.stdout, "")
                self.assertNotEqual(result.stderr.strip(), "")

    def test_invalid_existing_journal_is_preserved_and_never_executes_injected_identity(self):
        data = {"task": "backup-test.log", "entries": [{"type": "systemd", "id": "bad@inst;touch forbidden.service",
                                                         "phase": "stopped", "updated_at": 1}]}
        result = self.run_fixture(r'''
state_dir="$(restart_journal_create backup-test.log)"
printf '%s\n' "$SEEDED_JOURNAL" > "$state_dir/journal.json"
cp "$state_dir/journal.json" "$TEST_ROOT/initial-journal.json"
start_backup_targets_if_needed "$state_dir"
''', env={"SEEDED_JOURNAL": json.dumps(data)}, expected=20)
        self.assertIn("Invalid journal entry", result.stderr)
        self.assertEqual((self.root / "state/restart-journals/backup-test.log/journal.json").read_bytes(),
                         (self.root / "initial-journal.json").read_bytes())
        self.assertEqual(self.lines("service-calls"), [])
        self.assertFalse((self.root / "forbidden.service").exists())

    def test_failed_instance_stop_aborts_before_docker_and_recovers_all_stopped_native_services(self):
        self.prepare_squeezelite_and_docker()
        failed = "squeezelite-lbp@inst_bad.service"
        result = self.run_fixture(INTERRUPTIBLE_STOP, env={"STOP_FAIL_UNIT": failed}, expected=1)
        self.assertIn(f"Job for {failed} canceled.", result.stderr)
        self.assertIn(f"Stopping systemd service {failed} failed (exit status 1)", result.stdout)
        self.assertEqual(self.lines("service-calls"), [f"stop {name}" for name in SQUEEZELITE_SERVICES]
                         + [f"start {name}" for name in reversed(SQUEEZELITE_SERVICES)])
        self.assertTrue(all((self.root / f"active-{name}").exists() for name in SQUEEZELITE_SERVICES))
        self.assertTrue((self.root / "docker-active").exists())
        self.assertFalse((self.root / "copy-called").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        self.assertEqual((task["state"], task["phase"], task["exit_status"]), ("failed", "failed", 1))

    def test_failed_instance_restart_keeps_journal_until_later_recovery_succeeds(self):
        identity = "squeezelite-lbp@inst_bad.service"
        self.unit(identity)
        self.select(("systemd", identity))
        self.run_fixture(INTERRUPTIBLE_STOP, env={"STOP_FAIL_UNIT": identity, "START_FAIL_UNIT": identity}, expected=1)
        self.assertFalse((self.root / "copy-called").exists())
        entry, = self.journal()["entries"]
        self.assertEqual((entry["id"], entry["phase"], entry["problem"]), (identity, "stopped", "start-failed"))
        task = json.loads((self.root / "state/tasks/backup-test.log.json").read_text())
        self.assertEqual((task["state"], task["phase"]), ("failed", "cleanup_failed"))
        self.run_fixture('recover_restart_journals --scheduled\n')
        self.assertTrue((self.root / f"active-{identity}").exists())
        self.assertFalse((self.root / "state/restart-journals/backup-test.log").exists())
        self.assertEqual(self.lines("service-calls"), [f"stop {identity}", f"start {identity}", f"start {identity}"])

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
