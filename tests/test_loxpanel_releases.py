"""Compatibility against byte-pinned, actual upstream LoxPanel controllers.

The Linux tests execute only `check`, in a temporary installation with fake
sudo/docker programs. They never contact Docker or run an upstream start/stop
command against the host. See fixtures/loxpanel/README.md for provenance.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/loxpanel"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
SOURCES = MANIFEST["sources"]
SPEC = importlib.util.spec_from_file_location("watchdog_release_test", ROOT / "bin/hostbackup-watchdog.py")
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)
IDENTITY = "ab" * 32


def installed_controller(source, home):
    """Make only the two path substitutions done by the LoxBerry installer."""
    return ((FIXTURES / source["fixture"]).read_text(encoding="utf-8")
            .replace("REPLACELBPCONFIGDIR", home + "/config/plugins/loxpanel")
            .replace("REPLACELBPDATADIR", home + "/data/plugins/loxpanel"))


class ReleasedControllerTests(unittest.TestCase):
    def test_actual_published_zip_and_source_fixtures_match_recorded_hashes(self):
        releases = [source for source in SOURCES if source["kind"] == "release_asset"]
        self.assertEqual([source["ref"] for source in releases], [
            "v0.3.0", "v0.3.1", "v0.3.2", "v0.3.3", "v0.4.0", "v0.5.0", "v0.6.0", "v0.7.0"])
        self.assertEqual(len({source["sha256"] for source in releases}), 1)
        for source in SOURCES:
            with self.subTest(ref=source["ref"], kind=source["kind"]):
                content = (FIXTURES / source["fixture"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), source["sha256"])
                self.assertNotIn(b"\r", content)
                self.assertTrue(content.endswith(b"\n"))
                self.assertTrue(source["url"].startswith("https://github.com/Lenardo1/Loxpanel/"))
                if source["kind"] == "release_asset":
                    self.assertRegex(source["asset_sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(source["path"], "bin/loxpanel-ctl.sh")
                    self.assertEqual(len(content), 4237)

    def test_every_recorded_controller_is_recognised_after_real_install_substitution(self):
        for source in SOURCES:
            for home in ("/opt/loxberry", "/srv/custom-loxberry"):
                with self.subTest(ref=source["ref"], home=home):
                    profile = watchdog.controller_profile(installed_controller(source, home), home)
                    self.assertEqual(profile["mode"], source["expected_mode"])
                    suffix = ("/data/plugins/loxpanel/.loxpanel-ctl.lock" if profile["mode"] == "lock"
                              else "/config/plugins/loxpanel/loxpanel_stopped.cfg")
                    self.assertEqual(profile["path"], home + suffix)

    def test_released_controller_is_not_misrepresented_as_automatic_flock(self):
        for source in SOURCES:
            if source["expected_mode"] != "manual-stop":
                continue
            with self.subTest(ref=source["ref"]), self.assertRaises(watchdog.GuardError):
                watchdog.validate_controller(installed_controller(source, "/opt/loxberry"), "/opt/loxberry")

    def test_changed_actual_marker_contract_is_not_guessed_safe(self):
        original = installed_controller(SOURCES[0], "/opt/loxberry")
        variants = (
            original.replace('[ -f "$STOPPED" ] && exit 0', '[ -f "$STOPPED" ] && echo ignored'),
            original.replace('[ -f "$STOPPED" ] && exit 0', '# [ -f "$STOPPED" ] && exit 0'),
            original.replace('STOPPED="/opt/loxberry/config/plugins/loxpanel/loxpanel_stopped.cfg"',
                             'STOPPED="/tmp/other-marker"'),
            original + '\nSTOPPED="/tmp/override"\n',
            original.replace('\t\trunning || start\n', '\t\tstart\n'),
            original.replace('\tcheck)\n', '\tcheck)\n\t\tstart\n'),
            original + '\x00',
        )
        for number, content in enumerate(variants):
            with self.subTest(number=number), self.assertRaises(watchdog.GuardError):
                watchdog.controller_profile(content, "/opt/loxberry")


@unittest.skipUnless(sys.platform == "linux", "Actual upstream check and no-follow marker tests require Linux.")
class ReleasedControllerLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-loxpanel-release-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o755)
        self.home = self.root / "loxberry"
        self.config = self.home / "config/plugins/loxpanel"
        self.data = self.home / "data/plugins/loxpanel"
        self.binary = self.home / "bin/plugins/loxpanel"
        self.fake_bin = self.root / "fake-bin"
        for path in (self.config, self.data, self.binary, self.fake_bin):
            path.mkdir(parents=True, exist_ok=True)
        self.controller = self.binary / "loxpanel-ctl.sh"
        self.marker = self.config / "loxpanel_stopped.cfg"
        self.calls = self.root / "docker-calls.jsonl"
        # Both entry points are controlled. sudo refuses everything except
        # docker, and docker handles only the handful of dry-run fixture calls.
        stub = "#!" + sys.executable + "\n" + r'''
import json, os, pathlib, sys
args = sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == "sudo":
    if not args or args.pop(0) != "docker":
        sys.exit(97)
with open(os.environ["FIXTURE_CALLS"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")
if args and args[0] == "ps":
    if os.environ.get("FIXTURE_RUNNING") == "1":
        print("aaaaaaaaaaaa")
elif args and args[0] == "compose" and args[-1] in ("pull", "-d"):
    pass
else:
    sys.exit(98)
'''
        for name in ("sudo", "docker"):
            target = self.fake_bin / name
            target.write_text(stub, encoding="utf-8")
            target.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.fake_bin) + ":/usr/bin:/bin",
                        FIXTURE_CALLS=str(self.calls), FIXTURE_RUNNING="0",
                        LOXPANEL_CTL_CONFIGDIR=str(self.config), LOXPANEL_CTL_DATADIR=str(self.data),
                        LOXPANEL_CTL_LOCALTIME=str(self.root / "nonexistent-localtime"))
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        import pwd
        user = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
        account = (user.pw_uid, user.pw_gid, os.getgrouplist(user.pw_name, user.pw_gid))
        self.account = account
        patcher = patch.object(watchdog, "watchdog_account", return_value=account)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, source):
        self.controller.write_text(installed_controller(source, str(self.home)), encoding="utf-8")

    def check(self, unprivileged=False):
        options = ({"user": self.account[0], "group": self.account[1], "extra_groups": self.account[2]}
                   if unprivileged and os.geteuid() == 0 else {})
        result = subprocess.run([self.bash, str(self.controller), "check"], env=self.env,
                                cwd=self.root, capture_output=True, text=True, timeout=10, **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def docker_calls(self):
        return ([json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]
                if self.calls.exists() else [])

    def test_all_actual_controllers_respect_intentional_stop_without_docker_call(self):
        self.marker.write_text("owned by the user; do not modify\n", encoding="utf-8")
        before = self.marker.stat()
        for source in SOURCES:
            with self.subTest(ref=source["ref"]):
                self.install(source)
                self.check()
                self.assertEqual(self.docker_calls(), [])
                self.assertEqual(self.marker.read_text(encoding="utf-8"), "owned by the user; do not modify\n")
                self.assertEqual(self.marker.stat().st_ino, before.st_ino)
                self.assertEqual(self.marker.stat().st_mtime_ns, before.st_mtime_ns)

    def test_released_check_really_would_start_absent_container_without_marker(self):
        self.install(SOURCES[0])
        self.check()
        calls = self.docker_calls()
        self.assertEqual(calls[0][0], "ps")
        self.assertTrue(any(call[0] == "compose" and call[-1] == "pull" for call in calls))
        self.assertTrue(any(call[0] == "compose" and call[-2:] == ["up", "-d"] for call in calls))

    def test_unprivileged_real_check_respects_unreadable_but_stat_accessible_marker(self):
        self.calls.write_text("", encoding="utf-8")
        self.calls.chmod(0o666)  # Unexpected fake Docker calls remain observable.
        self.marker.write_text("owned by the manual stop\n", encoding="utf-8")
        for source in (SOURCES[0], next(source for source in SOURCES if source["expected_mode"] == "lock")):
            self.install(source)
            for mode in (0o000, 0o600):
                with self.subTest(ref=source["ref"], mode=oct(mode)):
                    self.marker.chmod(mode)
                    before = self.marker.stat()
                    self.check(unprivileged=True)
                    self.assertEqual(self.docker_calls(), [])
                    after = self.marker.stat()
                    self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode),
                                     (before.st_ino, before.st_mtime_ns, before.st_mode))
        self.marker.chmod(0o644)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), "owned by the manual stop\n")

    def test_released_check_leaves_running_container_alone(self):
        self.install(SOURCES[0])
        self.env["FIXTURE_RUNNING"] = "1"
        self.check()
        self.assertEqual([call[0] for call in self.docker_calls()], ["ps"])

    def test_current_check_really_obeys_existing_flock_and_resumes_after_release(self):
        self.install(next(source for source in SOURCES if source["expected_mode"] == "lock"))
        lock = self.data / ".loxpanel-ctl.lock"
        guard = watchdog.LockGuard(str(lock), Mock(alive=Mock(return_value=True)))
        try:
            self.check()
            self.assertEqual(self.docker_calls(), [])
        finally:
            guard.close()
        self.check()
        self.assertEqual(self.docker_calls()[0][0], "ps")
        self.assertTrue(any(call[0] == "compose" and call[-2:] == ["up", "-d"] for call in self.docker_calls()))

    def test_every_released_profile_allows_only_observed_manual_pause_and_preserves_marker(self):
        self.marker.write_text("user stop\n", encoding="utf-8")
        before = self.marker.stat()
        for source in SOURCES:
            if source["expected_mode"] != "manual-stop":
                continue
            for inventory in ([], [(IDENTITY, "loxpanel")]):
                for targets, legacy in (("docker\tloxpanel", False), ("", True)):
                    with self.subTest(ref=source["ref"], inventory=inventory, targets=targets):
                        self.install(source)
                        with patch.object(watchdog, "docker_inventory", return_value=inventory), \
                                patch.object(watchdog, "container_state", return_value="stopped"):
                            result = watchdog.probe(str(self.home), targets, legacy)
                        self.assertEqual(result["ok"], True, result)
                        self.assertEqual(result["mode"], "manual-stop")
                        self.check()
                        self.assertEqual(self.docker_calls(), [])
                        self.assertEqual(self.marker.read_text(encoding="utf-8"), "user stop\n")
                        after = self.marker.stat()
                        self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode),
                                         (before.st_ino, before.st_mtime_ns, before.st_mode))
                        self.assertFalse((self.data / ".loxpanel-ctl.lock").exists())

    def test_released_probe_explains_required_stop_before_backup_without_creating_marker(self):
        self.install(SOURCES[0])
        for inventory, state in (([], "stopped"), ([(IDENTITY, "loxpanel")], "stopped"),
                                 ([(IDENTITY, "loxpanel")], "running")):
            with self.subTest(inventory=inventory, state=state), \
                    patch.object(watchdog, "docker_inventory", return_value=inventory), \
                    patch.object(watchdog, "container_state", return_value=state):
                result = watchdog.probe(str(self.home), "docker\tloxpanel", False)
            self.assertFalse(result["ok"])
            self.assertIn("LoxPanel", result["details"])
            self.assertIn("Oberflaeche", result["details"])
            self.assertFalse(self.marker.exists())
        self.assertEqual(self.docker_calls(), [])

    def test_marker_does_not_disguise_running_container_and_is_never_removed(self):
        self.install(SOURCES[0])
        self.marker.write_text("user stop\n", encoding="utf-8")
        with patch.object(watchdog, "docker_inventory", return_value=[(IDENTITY, "loxpanel")]), \
                patch.object(watchdog, "container_state", return_value="running"):
            result = watchdog.probe(str(self.home), "docker\tloxpanel", False)
        self.assertFalse(result["ok"])
        self.assertIn("LoxPanel", result["details"])
        self.assertEqual(self.marker.read_text(encoding="utf-8"), "user stop\n")
        self.assertEqual(self.docker_calls(), [])

    def test_manual_guard_and_controller_keep_user_stop_after_check_and_cleanup(self):
        self.install(SOURCES[0])
        self.marker.write_text("user stop\n", encoding="utf-8")
        before = self.marker.stat()
        with patch.object(watchdog, "docker_inventory", return_value=[]), \
                patch.object(watchdog, "container_state", side_effect=AssertionError("No container exists")):
            guard = watchdog.ManualStopGuard(str(self.marker), None)
            self.check()
            guard.check()
            guard.close()
            guard.close()
        after = self.marker.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode),
                         (before.st_ino, before.st_mtime_ns, before.st_mode))
        self.assertEqual(self.marker.read_text(encoding="utf-8"), "user stop\n")
        self.assertEqual(self.docker_calls(), [])

    def test_modern_probe_is_read_only_and_does_not_create_lock_or_stop_marker(self):
        self.install(next(source for source in SOURCES if source["expected_mode"] == "lock"))
        with patch.object(watchdog, "docker_inventory", return_value=[(IDENTITY, "loxpanel")]):
            result = watchdog.probe(str(self.home), "docker\tloxpanel", False)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "lock")
        self.assertFalse((self.data / ".loxpanel-ctl.lock").exists())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.docker_calls(), [])


if __name__ == "__main__":
    unittest.main()
