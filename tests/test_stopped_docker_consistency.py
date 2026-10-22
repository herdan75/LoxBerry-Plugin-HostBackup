"""Check stopped identities without modifying containers or restart journals."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else None)
FIRST = "ab" * 32
SECOND = "cd" * 32


def function(name):
    source = (ROOT / "bin/hostbackup.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n(?=\n)", source, re.M | re.S)
    if not match:
        raise AssertionError("Missing function: " + name)
    return match.group(0)


FIXTURE = r'''
set -euo pipefail
cd -- "$DOCKER_CHECK_TEST_DIR"
log() { printf '%s\n' "$*"; }
restart_journal_update() {
  [ "$#:$1:$2" = '2:/private/journal:pending' ] || return 91
  printf 'journal-pending\n' >> calls
  [ "${JOURNAL_STATUS:-0}" = 0 ] || return "$JOURNAL_STATUS"
  printf '%s' "$JOURNAL_PENDING"
}
docker_recovery_state() {
  printf 'state:%s\n' "$1" >> calls
  case "$1" in
    ab*) printf '%s\n' "$FIRST_STATE" ;;
    cd*) printf '%s\n' "$SECOND_STATE" ;;
    *) return 92 ;;
  esac
  return "${STATE_STATUS:-0}"
}
docker() { printf 'forbidden-docker\n' >> calls; return 93; }
systemctl() { printf 'forbidden-systemctl\n' >> calls; return 94; }
'''


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is required")
class StoppedDockerConsistencyTests(unittest.TestCase):
    def check(self, pending, expected=0, extra_source="", real_recovery=False, **options):
        with tempfile.TemporaryDirectory(prefix="hostbackup-stopped-check-") as temporary:
            directory = Path(temporary).resolve()
            source = FIXTURE + "\n" + function("verify_stopped_docker_targets")
            if real_recovery:
                source += "\n" + function("docker_recovery_state")
            source += "\n" + extra_source + "\nverify_stopped_docker_targets /private/journal\n"
            result = subprocess.run(
                [BASH, "--noprofile", "--norc", "-s"], input=source,
                text=True, encoding="utf-8", capture_output=True, check=False, timeout=20,
                env={**os.environ, "DOCKER_CHECK_TEST_DIR": directory.as_posix(),
                     "JOURNAL_PENDING": pending, "FIRST_STATE": "stopped", "SECOND_STATE": "stopped",
                     **{key: str(value) for key, value in options.items()}},
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            calls_path = directory / "calls"
            calls = calls_path.read_text(encoding="utf-8").splitlines() if calls_path.exists() else []
            self.assertFalse(any(item.startswith("forbidden-") for item in calls), calls)
            return result.stdout + result.stderr, calls

    def test_empty_or_native_only_journal_never_queries_docker(self):
        for pending in ("", "systemd\tsqueezelite-lbp@inst_bad.service\tstopped\n"):
            with self.subTest(pending=pending):
                _, calls = self.check(pending)
                self.assertEqual(calls, ["journal-pending"])

    def test_only_actually_stopped_docker_entries_are_checked(self):
        pending = (f"docker\t{FIRST}\tstopped\n"
                   f"docker\t{SECOND}\tintended\n"
                   "systemd\tmosquitto.service\tstopped\n")
        _, calls = self.check(pending)
        self.assertEqual(calls, ["journal-pending", "state:" + FIRST])

    def test_short_historical_immutable_identity_is_still_accepted(self):
        _, calls = self.check(f"docker\t{FIRST[:12]}\tstopped\n")
        self.assertEqual(calls, ["journal-pending", "state:" + FIRST[:12]])

    def test_all_stopped_entries_pass_without_mutation(self):
        output, calls = self.check(f"docker\t{FIRST}\tstopped\ndocker\t{SECOND}\tstopped\n")
        self.assertEqual(calls, ["journal-pending", "state:" + FIRST, "state:" + SECOND])
        self.assertNotIn("ERROR", output)

    def test_running_missing_and_unavailable_are_distinct_failures(self):
        for state, message in (("running", "started again"), ("missing", "removed"),
                               ("unavailable", "unavailable"), ("unexpected", "unavailable")):
            with self.subTest(state=state):
                output, calls = self.check(f"docker\t{FIRST}\tstopped\n", expected=20,
                                           FIRST_STATE=state)
                self.assertIn(message, output)
                self.assertIn(FIRST, output)
                self.assertEqual(calls, ["journal-pending", "state:" + FIRST])

    def test_one_failure_cannot_be_overwritten_by_next_stopped_container(self):
        output, calls = self.check(f"docker\t{FIRST}\tstopped\ndocker\t{SECOND}\tstopped\n",
                                   expected=20, FIRST_STATE="running")
        self.assertIn("started again", output)
        self.assertEqual(calls, ["journal-pending", "state:" + FIRST, "state:" + SECOND])

    def test_journal_read_failure_aborts_without_docker_query(self):
        output, calls = self.check(f"docker\t{FIRST}\tstopped\n", expected=20, JOURNAL_STATUS=13)
        self.assertIn("Cannot read the restart journal", output)
        self.assertEqual(calls, ["journal-pending"])

    def test_failed_state_command_cannot_masquerade_as_stopped(self):
        output, _ = self.check(f"docker\t{FIRST}\tstopped\n", expected=20, STATE_STATUS=7)
        self.assertIn("unavailable", output)

    def test_names_and_invalid_stopped_ids_are_never_resolved_as_replacements(self):
        for identity in ("loxpanel", "ab", "AB" * 32, "../bad", FIRST + "\textra"):
            pending = f"docker\t{identity}\tstopped\n" if "\t" not in identity else f"docker\t{FIRST}\tstopped\textra\n"
            with self.subTest(identity=identity):
                output, calls = self.check(pending, expected=20)
                self.assertIn("Invalid stopped Docker identity", output)
                self.assertEqual(calls, ["journal-pending"])

    def test_actual_recovery_reader_uses_readonly_immutable_id_inspection(self):
        source = r'''
timeout() { shift; "$@"; }
docker() {
  printf 'docker:%s\n' "$*" >> calls
  if [ "$1:$2:$3:$4" = 'container:inspect:--format:{{.State.Running}}' ]; then
    [ "$5" = "''' + FIRST + r'''" ] || return 96
    printf 'false\n'
  else
    printf 'forbidden-docker-write\n' >> calls
    return 97
  fi
}
'''
        _, calls = self.check(f"docker\t{FIRST}\tstopped\n", extra_source=source, real_recovery=True)
        self.assertEqual(calls, ["journal-pending", "docker:container inspect --format {{.State.Running}} " + FIRST])


if __name__ == "__main__":
    unittest.main()
