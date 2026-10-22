"""Regression coverage for a watchdog-aware *real* backup worker lifecycle.

The worker and its guard functions are extracted, never the host entry point.
All copying, services and Docker operations target disposable doubles. The
protocol helper deliberately runs in another process: an acquisition inside
the old stop/tee pipeline cannot accidentally satisfy these assertions.
"""

import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

import test_portable_worker as portable


if (sys.platform == "linux" and os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1"
        and not (portable.BASH and Path(portable.BASH).exists())):
    raise RuntimeError("Mandatory watchdog worker regression requires Bash")


GUARD_FUNCTIONS = ("watchdog_guard_start", "watchdog_guard_check", "watchdog_guard_release")

PROTOCOL_HELPER = r'''
import argparse
import os
from pathlib import Path
import sys
import time

sys.stdout.reconfigure(newline="\n")
parser = argparse.ArgumentParser()
parser.add_argument("action")
parser.add_argument("--home")
parser.add_argument("--owner-pid")
parser.add_argument("--targets")
parser.add_argument("--legacy")
args = parser.parse_args()
root = Path(os.environ["WORKER_TEST_DIR"])
events = root / "events"
def event(value):
    with events.open("a", encoding="utf-8") as stream:
        stream.write(value + "\n")
event("guard-helper-start")
if args.action != "hold":
    raise SystemExit(91)
targets = args.targets.splitlines()
selected = "docker\tloxpanel" in targets or args.legacy == "true"
if not selected:
    event("guard-skip")
    print("SKIP", flush=True)
    raise SystemExit(0)
if os.environ.get("GUARD_START_FAILURE") == "1":
    event("guard-acquire-failed")
    print("Simulated existing watchdog lock or unsupported integration", file=sys.stderr)
    raise SystemExit(20)
marker = root / "guard-held"
marker.write_text(str(os.getpid()), encoding="ascii")
event("guard-acquired")
print("READY loxpanel manual-stop" if os.environ.get("GUARD_MANUAL_STOP") == "1" else "READY loxpanel", flush=True)
checks = 0
try:
    for line in sys.stdin:
        action = line.rstrip("\n")
        if action == "CHECK":
            checks += 1
            event("guard-check:" + str(checks))
            if os.environ.get("GUARD_CHECK_DELAY"):
                time.sleep(float(os.environ["GUARD_CHECK_DELAY"]))
            if str(checks) == os.environ.get("GUARD_CHECK_EOF", ""):
                raise SystemExit(20)
            if str(checks) == os.environ.get("GUARD_CHECK_FAILURE", ""):
                print("ERROR simulated guard was replaced", flush=True)
                raise SystemExit(20)
            print("OK", flush=True)
        elif action == "RELEASE":
            if os.environ.get("GUARD_RELEASE_HANG") == "1":
                event("guard-release-unresponsive")
                (root / "release-hang-start").write_text(str(time.monotonic()), encoding="ascii")
                # Finite fixture fallback prevents an orphan even if production
                # termination regresses. Correct code kills this process at 5s.
                time.sleep(15)
                raise SystemExit(0)
            event("guard-released")
            print("RELEASED", flush=True)
            raise SystemExit(0)
        else:
            event("guard-protocol-invalid")
            raise SystemExit(92)
finally:
    marker.unlink(missing_ok=True)
    event("guard-process-ended")
'''

WORKER_OVERRIDES = r'''
LBHOMEDIR="$TEST_ROOT/loxberry"
mkdir -p "$LBHOMEDIR/bin/plugins/loxpanel" "$LBHOMEDIR/data/plugins/loxpanel"
printf 'inert controller fixture\n' > "$LBHOMEDIR/bin/plugins/loxpanel/loxpanel-ctl.sh"
# Real exec/coproc/descriptor semantics, with only the Python executable routed
# to the test interpreter (Git Bash does not reliably provide python3 itself).
PATH="$TEST_ROOT/mock-bin:$PATH"
# Preserve the fixture's strict dispatch of source helpers and Python receipts.
eval "$(declare -f python3 | sed '1s/python3/fixture_python3/')"
python3() {
  if [ "${1:-}" = "$LBP_BINDIR/hostbackup-watchdog.py" ]; then
    shift
    "$WORKER_PYTHON" "$MOCK_WATCHDOG_HELPER" "$@"
  else
    case "${1:-}:${2:-}" in
      "$LBP_BINDIR/hostbackup-sources.py:files") watchdog_tick source-selection ;;
      "$LBP_BINDIR/hostbackup-sources.py:verify") watchdog_tick source-verification ;;
    esac
    fixture_python3 "$@"
  fi
}
eval "$(declare -f repository_helper | sed '1s/repository_helper/fixture_repository_helper/')"
repository_helper() {
  watchdog_tick copy
  [ "${SIGNAL_IN_COPY:-false}" != true ] || { kill -TERM "$$"; return 143; }
  fixture_repository_helper "$@"
}
selected_stop_targets() {
  if [ "${GUARD_SELECTED:-true}" = true ]; then printf 'docker\tloxpanel\n'; fi
}
json_get_bool() {
  if [ "$1" = stop_docker_before_backup ]; then echo "${GUARD_LEGACY:-false}"; else echo false; fi
}
json_get_string() {
  case "$1" in
    backup_mode) echo snapshot ;;
    metadata_mode) echo portable-archive ;;
    pre_backup_hook) echo pre-hook ;;
    post_backup_hook) echo post-hook ;;
  esac
}
watchdog_tick() {
  if [ "${GUARD_SELECTED:-true}" = true ] || [ "${GUARD_LEGACY:-false}" = true ]; then
    if [ -f "$TEST_ROOT/guard-held" ]; then event "watchdog-blocked:$1";
    elif [ -n "${GUARD_CHECK_FAILURE:-}" ] || [ -n "${GUARD_CHECK_EOF:-}" ]; then
      # Losing the guard is already the injected fault. Do not manufacture a
      # second unrelated source-helper failure while the worker gathers evidence
      # and recovers the services; the production CHECK must reject publication.
      event "watchdog-unavailable:$1"
    else event "watchdog-unguarded:$1"; return 96; fi
  else
    event "watchdog-unselected:$1"
  fi
}
stop_backup_targets() {
  watchdog_tick stop
  event services-stop
  : > "$TEST_ROOT/services-stopped"
  return "${STOP_STATUS:-0}"
}
start_backup_targets_if_needed() {
  # A guard acquisition failure can enter the normal EXIT cleanup even though
  # no service was stopped. Never mistake that safe empty cleanup for a stop.
  if [ -e "$TEST_ROOT/services-stopped" ]; then watchdog_tick restart; fi
  event services-start
  : > "$TEST_ROOT/services-restarted"
  return "${RESTART_STATUS:-0}"
}
verify_stopped_docker_targets() {
  local count=0
  [ ! -e "$TEST_ROOT/docker-verifications" ] || read -r count < "$TEST_ROOT/docker-verifications"
  count=$((count + 1))
  printf '%s\n' "$count" > "$TEST_ROOT/docker-verifications"
  event "docker-stop-verified:$count"
  [ "$count" != "${DOCKER_VERIFY_FAIL_ON:-}" ] || return 20
}
run_hook() {
  event "$1"
  if [ "$1" = post-hook ]; then
    # The forced-kill case validates native process death in the Python test;
    # its synthetic marker cannot be removed by a SIGKILLed process.
    [ "${GUARD_RELEASE_HANG:-}" = 1 ] || [ ! -e "$TEST_ROOT/guard-held" ] || { event guard-leaked-into-post-hook; return 96; }
  fi
}
'''


@unittest.skipUnless(portable.BASH and Path(portable.BASH).exists(), "Bash is required")
class WatchdogWorkerCoordinationTests(unittest.TestCase):
    def run_worker(self, expected=0, **options):
        temporary = tempfile.TemporaryDirectory(prefix="hostbackup-watchdog-worker-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        mock = root / "watchdog-helper.py"
        mock.write_text(PROTOCOL_HELPER, encoding="utf-8")
        bindir = root / "never-executed-bin"
        bindir.mkdir()
        (bindir / "hostbackup-watchdog.py").write_text(PROTOCOL_HELPER, encoding="utf-8")
        mockbin = root / "mock-bin"
        mockbin.mkdir()
        shim = mockbin / "python3"
        shim.write_text('#!/bin/sh\nexec "$WORKER_PYTHON" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        names = ("portable_snapshot", "checked_source_info", *GUARD_FUNCTIONS,
                 "backup_cleanup_on_exit", "create_backup")
        source = portable.FIXTURE + "\n" + WORKER_OVERRIDES + "\n"
        functions = "\n".join(portable.function(name) for name in names)
        if options.get("GUARD_TEST_SCALED_CHECK_TIMEOUT"):
            # Only the disposable extracted fixture is accelerated; production
            # keeps its bounded Docker-inventory/inspection budget unchanged.
            self.assertEqual(functions.count("read -r -t 25 reply"), 1)
            functions = functions.replace("read -r -t 25 reply", "read -r -t 1 reply")
        source += functions
        source += "\ncreate_backup portable-test\n"
        result = subprocess.run(
            [portable.BASH, "--noprofile", "--norc", "-s"], input=source,
            text=True, encoding="utf-8", capture_output=True, check=False,
            timeout=45 if options.get("GUARD_RELEASE_HANG") else (90 if os.name == "nt" else 60),
            env={**os.environ, "WORKER_TEST_DIR": root.as_posix(),
                 "WORKER_PYTHON": Path(sys.executable).as_posix(),
                 "MOCK_WATCHDOG_HELPER": mock.as_posix(),
                 **{key: str(value) for key, value in options.items()}},
        )
        events = (root / "events").read_text(encoding="utf-8").splitlines()
        log = root / "state/logs/backup-portable-test.log"
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr
                         + "\nEVENTS:" + repr(events) + "\nLOG:"
                         + (log.read_text(encoding="utf-8") if log.exists() else "missing"))
        self.assertFalse(any(event.startswith(("forbidden-", "unexpected-", "watchdog-unguarded:"))
                             for event in events), events)
        self.assertNotIn("guard-protocol-invalid", events)
        self.assertNotIn("guard-leaked-into-post-hook", events)
        marker = root / "guard-held"
        if options.get("GUARD_RELEASE_HANG"):
            # SIGKILL cannot remove this synthetic marker. It is not the actual
            # OS lock; prove the owning protocol process is gone instead.
            self.assertTrue(marker.exists(), events)
            self.assert_process_gone(int(marker.read_text(encoding="ascii")))
        else:
            self.assertFalse(marker.exists(), events)
        return root, events, result

    def assert_process_gone(self, pid):
        self.assertGreater(pid, 1)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.OpenProcess(0x1000, False, pid)  # Read-only query.
            if not handle:
                self.assertEqual(ctypes.get_last_error(), 87)  # No such PID.
            else:
                try:
                    code = wintypes.DWORD()
                    self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                    self.assertNotEqual(code.value, 259, "Watchdog helper is still active")
                finally:
                    kernel.CloseHandle(handle)
        else:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)  # POSIX existence query only, never a signal.

    def before(self, events, first, second):
        self.assertLess(events.index(first), events.index(second), events)

    def test_guard_survives_stop_pipeline_through_copy_and_source_verification(self):
        root, events, _ = self.run_worker()
        self.before(events, "guard-acquired", "services-stop")
        for phase in ("stop", "source-selection", "copy", "source-verification", "restart"):
            self.assertIn("watchdog-blocked:" + phase, events)
        self.before(events, "watchdog-blocked:source-verification", "services-start")
        self.before(events, "services-start", "guard-released")
        self.before(events, "guard-process-ended", "post-hook")
        self.assertIn("notify:success", events)
        self.assertEqual(json.loads((root / "target/portable-test/manifest.json").read_bytes())["status"], "complete")

    def test_legacy_stop_all_uses_the_same_guard_lifecycle(self):
        _, events, _ = self.run_worker(GUARD_SELECTED="false", GUARD_LEGACY="true")
        self.assertIn("guard-acquired", events)
        self.assertIn("watchdog-blocked:copy", events)
        self.before(events, "services-start", "guard-released")

    def test_manual_stop_handshake_is_supported_and_user_restart_is_explained(self):
        root, events, _ = self.run_worker(GUARD_MANUAL_STOP="1")
        self.assertIn("notify:success", events)
        self.before(events, "services-start", "guard-released")
        log = (root / "state/logs/backup-portable-test.log").read_text(encoding="utf-8")
        self.assertIn("LoxPanel ist bewusst", log)
        self.assertIn("manuell wieder einschalten", log)
        self.assertNotIn("automatic restart paused", log)

    def test_delayed_guard_checks_are_supported_within_the_protocol_budget(self):
        _, events, _ = self.run_worker(GUARD_CHECK_DELAY="0.15", GUARD_TEST_SCALED_CHECK_TIMEOUT="1")
        self.assertIn("notify:success", events)
        self.before(events, "services-start", "guard-released")

    def test_timed_out_check_cannot_be_mistaken_for_success_or_a_release_reply(self):
        root, events, _ = self.run_worker(expected=20, GUARD_CHECK_DELAY="2", GUARD_TEST_SCALED_CHECK_TIMEOUT="1")
        self.assertNotIn("repository-copy", events)
        self.assertNotIn("notify:success", events)
        self.assertIn("services-start", events)
        self.assertIn("guard-process-ended", events)
        log = (root / "state/logs/backup-portable-test.log").read_text(encoding="utf-8")
        self.assertIn("coordination was lost", log)
        self.assertIn("ended unexpectedly: OK", log)

    def test_unselected_container_has_no_guard_or_configuration_changes(self):
        _, events, _ = self.run_worker(GUARD_SELECTED="false")
        self.assertIn("guard-skip", events)
        self.assertNotIn("guard-acquired", events)
        self.assertIn("notify:success", events)

    def test_guard_failure_aborts_before_any_service_is_stopped(self):
        _, events, _ = self.run_worker(expected=20, GUARD_START_FAILURE="1")
        self.assertIn("guard-acquire-failed", events)
        self.assertNotIn("services-stop", events)
        self.assertNotIn("repository-copy", events)
        self.assertNotIn("notify:success", events)

    def test_failure_paths_restart_before_releasing_the_guard(self):
        cases = (("STOP_STATUS", 20), ("FILES_STATUS", 18),
                 ("COPY_STATUS", 23), ("VERIFY_STATUS", 18))
        for variable, status in cases:
            with self.subTest(variable=variable):
                _, events, _ = self.run_worker(expected=status, **{variable: status})
                self.assertIn("watchdog-blocked:restart", events)
                self.before(events, "services-start", "guard-released")
                self.before(events, "guard-process-ended", "post-hook")
                self.assertNotIn("notify:success", events)

    def test_lost_guard_fails_safely_and_does_not_skip_service_recovery(self):
        for option, check in (("GUARD_CHECK_FAILURE", 1), ("GUARD_CHECK_FAILURE", 2),
                              ("GUARD_CHECK_EOF", 1)):
            with self.subTest(option=option, check=check):
                _, events, _ = self.run_worker(expected=20, **{option: check})
                self.assertIn("services-start", events)
                self.assertIn("guard-process-ended", events)
                self.assertNotIn("notify:success", events)
                self.assertNotIn("published", events)
                if check == 1:
                    self.assertNotIn("repository-copy", events)

    def test_restart_failure_still_releases_guard_before_post_hook(self):
        _, events, _ = self.run_worker(expected=21, RESTART_STATUS=21)
        self.assertIn("watchdog-blocked:restart", events)
        self.before(events, "services-start", "guard-released")
        self.before(events, "guard-process-ended", "post-hook")
        self.assertNotIn("notify:success", events)

    def test_unresponsive_release_is_bounded_and_kills_only_own_helper(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(40)"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            root, events, _ = self.run_worker(expected=20, GUARD_RELEASE_HANG="1")
            self.assertIsNone(bystander.poll(), "Unrelated process was terminated")
        finally:
            if bystander.poll() is None:
                bystander.terminate()
            bystander.wait(timeout=5)
        self.assertIn("guard-release-unresponsive", events)
        self.assertNotIn("guard-process-ended", events)  # Killed, not fallback exit.
        self.before(events, "services-start", "guard-release-unresponsive")
        self.assertNotIn("notify:success", events)
        started = float((root / "release-hang-start").read_text(encoding="ascii"))
        self.assertLess(time.monotonic() - started, 13,
                        "Worker waited for the unresponsive helper instead of terminating it")
        self.assertIn("helper did not finish normally", (root / "state/logs/backup-portable-test.log").read_text())

    def test_external_restart_is_not_silently_accepted_even_with_guard_active(self):
        for check in (1, 2):
            with self.subTest(check=check):
                _, events, _ = self.run_worker(expected=20, DOCKER_VERIFY_FAIL_ON=check)
                self.assertIn("docker-stop-verified:" + str(check), events)
                self.assertIn("watchdog-blocked:restart", events)
                self.before(events, "services-start", "guard-released")
                self.assertNotIn("notify:success", events)
                self.assertNotIn("published", events)
                if check == 1:
                    self.assertNotIn("repository-copy", events)

    @unittest.skipIf(os.name == "nt", "POSIX signal delivery requires Linux")
    def test_term_during_copy_runs_recovery_and_releases_guard(self):
        _, events, _ = self.run_worker(expected=143, SIGNAL_IN_COPY="true")
        self.assertIn("watchdog-blocked:restart", events)
        self.before(events, "services-start", "guard-released")
        self.before(events, "guard-process-ended", "post-hook")
        self.assertNotIn("notify:success", events)


@unittest.skipUnless(sys.platform == "linux", "Real flock/watchdog concurrency requires Linux")
class LinuxWatchdogCoordinationTests(unittest.TestCase):
    """Run the real guard against the upstream lock/check contract.

    This fixture includes precisely the lock and check statements of LoxPanel
    controller 61bfd1d82e86f6feb06162e11e41e3fca7944bf6. Docker actions alone are
    replaced by private marker operations; no production Docker is contacted.
    """

    def setUp(self):
        if not shutil.which("flock"):
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Required Linux watchdog dependency missing: flock")
            self.skipTest("flock is unavailable")
        temporary = tempfile.TemporaryDirectory(prefix="hostbackup-watchdog-lock-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.base.chmod(0o755)
        self.home = self.base / "loxberry"
        self.controller = self.home / "bin/plugins/loxpanel/loxpanel-ctl.sh"
        self.data = self.home / "data/plugins/loxpanel"
        self.controller.parent.mkdir(parents=True)
        self.data.mkdir(parents=True)
        self.lock = self.data / ".loxpanel-ctl.lock"
        self.running = self.data / "container-running"
        self.stopped = self.data / "loxpanel_stopped.cfg"
        # CI has no installed LoxBerry account. Only map that account lookup to
        # its disposable unprivileged user; all production path/open/flock and
        # dropped-credential access checks still run unchanged.
        self.runner = self.base / "guard-runner.py"
        self.runner.write_text('''import importlib.util
import os
import pwd
import sys
spec = importlib.util.spec_from_file_location("real_watchdog", '''
                               + repr(str(portable.ROOT / "bin/hostbackup-watchdog.py")) + ''')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_lookup = pwd.getpwnam
account = original_lookup("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
pwd.getpwnam = lambda name: account if name == "loxberry" else original_lookup(name)
# Only Docker inventory is doubled; this suite never contacts the host daemon.
# The stable identity represents a present (possibly stopped) LoxPanel fixture.
module.docker_inventory = lambda: [("a" * 64, "loxpanel")]
raise SystemExit(module.main())
''', encoding="utf-8")
        self.controller.write_text('''#!/bin/bash
DATADIR="${LOXPANEL_CTL_DATADIR:-''' + self.data.as_posix() + '''}"
SPERRE="$DATADIR/.loxpanel-ctl.lock"
STOPPED="$DATADIR/loxpanel_stopped.cfg"
running() { [ -e "$DATADIR/container-running" ]; }
start() { printf 'started\\n' > "$DATADIR/container-running"; }
_sperre() {
  [ -e "$SPERRE" ] || : >"$SPERRE"
  exec 9<"$SPERRE" || return 2
  flock -n 9 || return 1
}
case "$1" in
check)
  [ -f "$STOPPED" ] && exit 0
  _sperre
  [ $? = 1 ] && { echo busy; exit 0; }
  running || start
  ;;
esac
''', encoding="utf-8")
        self.controller.chmod(0o755)

    def helper(self, targets="docker\tloxpanel", legacy=False, owner=None):
        process = subprocess.Popen(
            [sys.executable, str(self.runner), "hold",
             "--home", self.home.as_posix(), "--owner-pid", str(owner or os.getpid()),
             "--targets", targets, "--legacy", str(legacy).lower()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            # A restrictive worker umask must not create an unreadable lock.
            umask=0o077,
        )
        self.addCleanup(self.cleanup_process, process)
        return process

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def line(self, process, timeout=5):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout), "Watchdog protocol timed out")
        line = process.stdout.readline()
        return line.decode("utf-8").rstrip("\n")

    def send(self, process, value):
        process.stdin.write(value.encode("ascii") + b"\n")
        process.stdin.flush()
        return self.line(process)

    def release(self, process):
        self.assertEqual(self.send(process, "RELEASE"), "RELEASED")
        self.assertEqual(process.wait(timeout=5), 0)

    def check(self, *, unprivileged=False):
        options = {}
        if unprivileged:
            import pwd
            user = pwd.getpwnam("nobody")
            options.update(user=user.pw_uid, group=user.pw_gid, extra_groups=[])
        result = subprocess.run([portable.BASH, str(self.controller), "check"],
                                capture_output=True, check=False, timeout=5,
                                env={**os.environ, "LOXPANEL_CTL_DATADIR": self.data.as_posix()},
                                **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.decode("utf-8").strip()

    def test_upstream_negative_control_and_guarded_checks_until_release(self):
        # This is the reported collision: no persistent stopped flag is set by
        # docker stop, so the next check starts the stopped container again.
        self.check()
        self.assertTrue(self.running.exists())
        self.running.unlink()
        process = self.helper()
        self.assertEqual(self.line(process), "READY loxpanel")
        identity = self.lock.stat().st_ino
        for phase in ("selected", "copying", "verifying", "recovering"):
            with self.subTest(phase=phase):
                self.assertEqual(self.check(), "busy")
                self.assertFalse(self.running.exists())
                self.assertEqual(self.send(process, "CHECK"), "OK")
        self.release(process)
        self.assertEqual(self.lock.stat().st_ino, identity)
        self.assertFalse(self.stopped.exists())
        self.check()
        self.assertTrue(self.running.exists())

    def test_new_root_lock_remains_readable_to_unprivileged_watchdog(self):
        if os.geteuid() != 0:
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Mandatory unprivileged watchdog check requires root fixture")
            self.skipTest("Needs root to launch nobody watchdog")
        process = self.helper()
        self.assertEqual(self.line(process), "READY loxpanel")
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o644)
        self.assertEqual(self.check(unprivileged=True), "busy")
        self.assertFalse(self.running.exists())
        self.release(process)

    def test_actual_watchdog_access_rejects_private_parent_and_group_precedence(self):
        if os.geteuid() != 0:
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                self.fail("Mandatory watchdog access regression requires root fixture")
            self.skipTest("Requires root to model loxberry credentials")
        import pwd
        nobody = pwd.getpwnam("nobody")
        self.lock.write_bytes(b"preserve existing lock\n")
        self.lock.chmod(0o644)
        self.data.chmod(0o700)
        process = self.helper()
        reply = self.line(process)
        self.assertTrue(reply.startswith("ERROR "), reply)
        self.assertEqual(process.wait(timeout=5), 20)
        self.data.chmod(0o755)
        # Other-readable does not mean this particular user can open it:
        # matching group permissions take precedence over the 'other' bits.
        os.chown(self.lock, 0, nobody.pw_gid)
        self.lock.chmod(0o604)
        process = self.helper()
        reply = self.line(process)
        self.assertTrue(reply.startswith("ERROR "), reply)
        self.assertEqual(process.wait(timeout=5), 20)
        self.assertEqual(self.lock.read_bytes(), b"preserve existing lock\n")
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o604)
        self.assertFalse(self.running.exists())

    def test_unselected_watchdog_is_not_locked_and_legacy_stop_all_is(self):
        process = self.helper(targets="docker\tsonn-core")
        self.assertEqual(self.line(process), "SKIP")
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertFalse(self.lock.exists())
        process = self.helper(targets="", legacy=True)
        self.assertEqual(self.line(process), "READY loxpanel")
        self.assertEqual(self.check(), "busy")
        self.release(process)

    def test_prior_intentional_stop_and_lock_content_are_preserved(self):
        self.stopped.write_text("user intentionally stopped\n", encoding="utf-8")
        self.lock.write_bytes(b"existing lock content\n")
        self.lock.chmod(0o644)
        before = self.lock.stat()
        process = self.helper()
        self.assertEqual(self.line(process), "READY loxpanel")
        self.assertEqual(self.check(), "")
        self.release(process)
        self.assertFalse(self.running.exists())
        self.assertEqual(self.stopped.read_text(), "user intentionally stopped\n")
        self.assertEqual(self.lock.read_bytes(), b"existing lock content\n")
        self.assertEqual((self.lock.stat().st_ino, self.lock.stat().st_mode),
                         (before.st_ino, before.st_mode))

    def test_existing_lock_contention_is_bounded_and_never_unlinks_lock(self):
        import fcntl
        self.lock.write_bytes(b"owned by LoxPanel operation\n")
        self.lock.chmod(0o644)
        identity = self.lock.stat().st_ino
        with self.lock.open("rb") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            process = self.helper()
            reply = self.line(process, timeout=15)
            self.assertTrue(reply.startswith("ERROR "), reply)
            self.assertIn("busy", reply)
            self.assertEqual(process.wait(timeout=5), 20)
        self.assertEqual(self.lock.stat().st_ino, identity)
        self.assertEqual(self.lock.read_bytes(), b"owned by LoxPanel operation\n")
        self.assertFalse(self.running.exists())

    def test_guard_rechecks_replaced_lock_instead_of_reporting_ok(self):
        process = self.helper()
        self.assertEqual(self.line(process), "READY loxpanel")
        replacement = self.data / "replacement"
        replacement.write_bytes(b"new inode\n")
        replacement.chmod(0o644)
        replacement.replace(self.lock)
        reply = self.send(process, "CHECK")
        self.assertTrue(reply.startswith("ERROR "), reply)
        self.assertEqual(process.wait(timeout=5), 20)
        self.assertFalse(self.running.exists())

    def test_group_term_does_not_release_before_parent_recovery(self):
        process = self.helper()
        self.assertEqual(self.line(process), "READY loxpanel")
        process.send_signal(signal.SIGTERM)
        self.assertEqual(self.send(process, "CHECK"), "OK")
        self.assertEqual(self.check(), "busy")
        self.release(process)

    def test_owner_death_releases_even_with_inherited_control_pipe_open(self):
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.cleanup_process, owner)
        process = self.helper(owner=owner.pid)
        self.assertEqual(self.line(process), "READY loxpanel")
        owner.kill()
        owner.wait(timeout=5)
        # stdin is deliberately left open, modelling a still-alive copy child.
        self.assertEqual(process.wait(timeout=5), 0)
        self.check()
        self.assertTrue(self.running.exists())
        self.assertFalse(self.stopped.exists())


if __name__ == "__main__":
    unittest.main()
