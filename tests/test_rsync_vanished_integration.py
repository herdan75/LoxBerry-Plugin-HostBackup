"""Exercise the classifier against real, bounded Linux rsync diagnostics.

Every source, destination and deleted file belongs to a new temporary fixture.
The tests never copy the host root, access a NAS or touch services/containers.
"""
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "hostbackup-copy-diagnostics.py"


class RealRsyncVanishedIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rsync = shutil.which("rsync")
        if not sys.platform.startswith("linux") or not cls.rsync:
            reason = "Real rsync vanished-file integration requires Linux and rsync"
            if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)

    @staticmethod
    def stop_fixture_process(process):
        # rsync forks a receiver even for local copies. Kill only the private
        # session started below, including children that might keep stdout open.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)

    def exercise_real_vanishing(self, include_unknown):
        with tempfile.TemporaryDirectory(prefix="hostbackup-real-vanished-") as directory:
            fixture = Path(directory).resolve()
            home = fixture / "loxberry"
            destination = fixture / "backup"
            home.mkdir()
            destination.mkdir()

            # --no-inc-recursive completes the source list before copying.
            # The first, rate-limited file gives us a deterministic transfer
            # window after that list exists but before later files are opened.
            trigger_name = "000-trigger.bin"
            payload = b"x" * (2 * 1024 * 1024)
            (home / trigger_name).write_bytes(payload)
            preserved = home / "zz-preserved.conf"
            preserved.write_bytes(b"unrelated persistent fixture data\n")
            vanished = [
                home / "log/plugins/stats4lox/grabber_loxberry.log",
                home / "log/plugins/miniserverbackup-ng/20261019_073001_342_Miniserverbackup NG CronJob.log",
                home / "log/ramlog/log/system_tmpfs/20261019_081301_649_Log Maintenance.log",
            ]
            if include_unknown:
                vanished.append(home / "data/plugins/stats4lox/important-config.json")
            for path in vanished:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"disposable fixture content\n")

            diagnostic = fixture / "rsync-stderr.log"
            stdout = bytearray()
            deleted_after_trigger = False
            completed = False
            deadline = time.monotonic() + 25
            with diagnostic.open("wb") as error_stream:
                process = subprocess.Popen(
                    [self.rsync, "-a", "--no-inc-recursive", "--outbuf=L",
                     "--itemize-changes", "--bwlimit=512", "--",
                     str(home) + "/", str(destination) + "/"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=error_stream,
                    env={**os.environ, "LC_ALL": "C"}, cwd=fixture,
                    start_new_session=True,
                )
                try:
                    pending = bytearray()
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while not deleted_after_trigger:
                            remaining = deadline - time.monotonic()
                            self.assertGreater(remaining, 0, "rsync transfer trigger timed out")
                            if not selector.select(min(remaining, 0.5)):
                                continue
                            chunk = os.read(process.stdout.fileno(), 65536)
                            if not chunk:
                                self.fail("rsync ended before the controlled transfer trigger: "
                                          + stdout.decode("utf-8", errors="replace"))
                            stdout.extend(chunk)
                            pending.extend(chunk)
                            while b"\n" in pending:
                                line, _, tail = pending.partition(b"\n")
                                pending = bytearray(tail)
                                if line.endswith(b" " + trigger_name.encode("ascii")):
                                    for path in vanished:
                                        # All targets were explicitly created above inside this fixture.
                                        path.unlink()
                                    deleted_after_trigger = True
                                    break
                    tail, _ = process.communicate(timeout=max(0.1, deadline - time.monotonic()))
                    stdout.extend(tail)
                    completed = True
                finally:
                    if not completed:
                        self.stop_fixture_process(process)
                    if process.stdout is not None:
                        process.stdout.close()

            details = diagnostic.read_bytes()
            evidence = (f"rsync exit={process.returncode}\n"
                        + stdout.decode("utf-8", errors="replace")
                        + details.decode("utf-8", errors="replace"))
            self.assertTrue(deleted_after_trigger, evidence)
            self.assertEqual(process.returncode, 24, evidence)
            self.assertTrue(details.endswith(b"\n"), evidence)
            for path in vanished:
                self.assertIn(f'file has vanished: "{path}"\n'.encode(), details, evidence)
                self.assertFalse((destination / path.relative_to(home)).exists())
            self.assertEqual((destination / trigger_name).read_bytes(), payload)
            self.assertEqual((destination / preserved.name).read_bytes(), preserved.read_bytes())

            result = subprocess.run(
                [sys.executable, str(HELPER), "--stderr", str(diagnostic),
                 "--exit-code", str(process.returncode), "--loxberry-home", str(home)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(result.stderr, "", evidence + result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1 if include_unknown else 0, evidence + result.stdout)
            self.assertIs(receipt["accepted"], not include_unknown, evidence + result.stdout)
            if not include_unknown:
                self.assertEqual(receipt["vanished_count"], len(vanished))
                self.assertEqual(receipt["reason"], "known_runtime_logs_only")
            else:
                self.assertEqual(receipt["reason"], "unknown_file_or_additional_diagnostic")

    def test_real_rsync_known_runtime_log_vanishing_is_accepted(self):
        self.exercise_real_vanishing(include_unknown=False)

    def test_real_rsync_unknown_file_among_known_logs_keeps_warning(self):
        self.exercise_real_vanishing(include_unknown=True)


if __name__ == "__main__":
    unittest.main()
