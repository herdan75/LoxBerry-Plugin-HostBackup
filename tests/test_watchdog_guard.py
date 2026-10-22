"""Portable validation tests and Linux lock-file safety for watchdog helper."""

import importlib.util
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hostbackup_watchdog_test", ROOT / "bin/hostbackup-watchdog.py")
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def controller(home="/fixture/loxberry"):
    return '''#!/bin/bash
# This fixture implements the existing LoxPanel lock contract, never executed.
DATADIR="${LOXPANEL_CTL_DATADIR:-HOME/data/plugins/loxpanel}"
SPERRE="$DATADIR/.loxpanel-ctl.lock"
_sperre() {
    [ -e "$SPERRE" ] || : >"$SPERRE"
    exec 9<"$SPERRE" || return 2
    flock -n 9 || return 1
}
case "$1" in
check)
    [ -f "$STOPPED" ] && exit 0 # deliberate user stop
    _sperre
    [ $? = 1 ] && { echo "Backup running"; exit 0; }
    running || start
    ;;
esac
'''.replace("HOME", home)


class WatchdogValidationTests(unittest.TestCase):
    def test_canonical_paths_and_invalid_components(self):
        for value in ("/opt/loxberry", "/tmp/fixture with spaces"):
            self.assertEqual(watchdog.absolute_path(value), value)
        for value in ("relative", "/", "//srv", "/opt/../etc", "/opt/./data", "/opt//data",
                      "/opt/data/", "/opt/lo\x00x", "/opt/line\nfeed", "/" + "a" * 4096, None):
            with self.subTest(value=value), self.assertRaises(watchdog.GuardError):
                watchdog.absolute_path(value)

    def test_targets_preserve_systemd_instances_and_docker_names(self):
        text = "systemd\tsqueezelite-lbp@inst_bad.service\ndocker\tloxpanel\n"
        self.assertEqual(watchdog.parse_targets(text), [
            ("systemd", "squeezelite-lbp@inst_bad.service"), ("docker", "loxpanel")])
        for value in ("docker", "docker\t", "other\tloxpanel", "docker\t../loxpanel",
                      "docker\tlo\tx", "docker\tloxpanel\x00", "docker\tlo\rx", "x" * 131073):
            with self.subTest(value=value[:80]), self.assertRaises(watchdog.GuardError):
                watchdog.parse_targets(value)

    def test_direct_selection_and_legacy_require_no_docker_query(self):
        inventory = Mock(side_effect=AssertionError("Unexpected Docker query"))
        self.assertTrue(watchdog.selected_loxpanel([("docker", "loxpanel")], False, inventory))
        self.assertTrue(watchdog.selected_loxpanel([], True, inventory))
        self.assertFalse(watchdog.selected_loxpanel([], False, inventory))
        self.assertFalse(watchdog.selected_loxpanel([("systemd", "mosquitto.service")], True, inventory))
        self.assertFalse(watchdog.selected_loxpanel([("docker", "sonn-core")], True, inventory))

    def test_hex_id_selection_resolves_name_and_preserves_name_precedence(self):
        identity = "ab" * 32
        inventory = Mock(return_value=[(identity, "loxpanel"), ("cd" * 32, "another")])
        self.assertTrue(watchdog.selected_loxpanel([("docker", identity)], False, inventory))
        self.assertTrue(watchdog.selected_loxpanel([("docker", identity[:12])], False, inventory))
        self.assertFalse(watchdog.selected_loxpanel([("docker", "ef" * 32)], False, inventory))
        inventory.return_value.append(("ef" * 32, identity[:12]))
        self.assertFalse(watchdog.selected_loxpanel([("docker", identity[:12])], False, inventory))

    def test_docker_inventory_is_bounded_and_validated(self):
        result = types.SimpleNamespace(returncode=0, stdout=(("ab" * 32) + "\tloxpanel\n").encode())
        with patch.object(watchdog.subprocess, "run", return_value=result) as run:
            self.assertEqual(watchdog.docker_inventory(), [("ab" * 32, "loxpanel")])
            self.assertEqual(run.call_args.kwargs["timeout"], 10)
            self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")
        for data in (b"short\tloxpanel\n", b"x\n", b"x" * 131073, b"\xff"):
            with self.subTest(data=data[:40]), patch.object(watchdog.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=data)):
                with self.assertRaises((watchdog.GuardError, UnicodeError)):
                    watchdog.docker_inventory()
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("docker", 10)):
            with patch.object(watchdog.subprocess, "run", side_effect=error), self.assertRaises(watchdog.GuardError):
                watchdog.docker_inventory()

    def test_official_lock_contract_is_recognised_without_executing(self):
        self.assertEqual(watchdog.validate_controller(controller(), "/fixture/loxberry"),
                         "/fixture/loxberry/data/plugins/loxpanel/.loxpanel-ctl.lock")
        direct = controller().replace('${LOXPANEL_CTL_DATADIR:-/fixture/loxberry/data/plugins/loxpanel}',
                                      '/fixture/loxberry/data/plugins/loxpanel')
        self.assertEqual(watchdog.validate_controller(direct, "/fixture/loxberry"),
                         "/fixture/loxberry/data/plugins/loxpanel/.loxpanel-ctl.lock")

    def test_unsupported_or_moved_controller_is_not_guessed_safe(self):
        original = controller()
        variants = (
            original.replace('exec 9<"$SPERRE"', 'exec 9>"$SPERRE"'),
            original.replace('flock -n 9', 'flock -s -n 9'),
            original.replace('flock -n 9 || return 1', ':'),
            original.replace('.loxpanel-ctl.lock', '.other.lock'),
            original.replace('/fixture/loxberry/data/plugins/loxpanel', '/different/data'),
            original.replace('    _sperre\n', '    running || start\n    _sperre\n'),
            original.replace('[ $? = 1 ]', '[ $? = 2 ]'),
            original.replace('exit 0; }', 'true; }'),
            original.replace('    running || start', '    start'),
            original + '\nDATADIR="/different"\n',
            original + '\nSPERRE="/different"\n',
            original + '\x00',
        )
        for index, source in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(watchdog.GuardError):
                watchdog.validate_controller(source, "/fixture/loxberry")

    def test_process_identity_handles_parentheses_in_name(self):
        text = "123 (worker (backup)) S " + " ".join(["0"] * 18 + ["987654", "0", "0"])
        self.assertEqual(watchdog.process_identity(text), ("S", "987654"))
        with self.assertRaises(watchdog.GuardError):
            watchdog.process_identity("not a proc stat")

    def test_owner_rejects_zombies_reused_pid_and_missing_process(self):
        with patch.object(watchdog.Owner, "identity", return_value=("S", "123")):
            owner = watchdog.Owner(1234)
        for state, started, expected in (("S", "123", True), ("Z", "123", False),
                                          ("X", "123", False), ("S", "124", False)):
            with patch.object(owner, "identity", return_value=(state, started)):
                self.assertEqual(owner.alive(), expected)
        with patch.object(owner, "identity", side_effect=FileNotFoundError()):
            self.assertFalse(owner.alive())
        with self.assertRaises(watchdog.GuardError):
            watchdog.Owner(1)

    def test_uninstalled_or_unselected_plugin_skips_without_lock(self):
        with patch.object(watchdog, "read_text", side_effect=FileNotFoundError()), \
                patch.object(watchdog, "docker_inventory", return_value=[("ab" * 32, "loxpanel")]), \
                patch.object(watchdog, "LockGuard", side_effect=AssertionError("Should skip")), \
                patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            watchdog.hold("/fixture/loxberry", 1234, "docker\tloxpanel", False)
            self.assertEqual(out.getvalue(), "SKIP\n")
        with patch.object(watchdog, "read_text", side_effect=AssertionError("Unselected plugin must not be read")), \
                patch.object(watchdog, "LockGuard", side_effect=AssertionError("Should skip")), \
                patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            watchdog.hold("/fixture/loxberry", 1234, "docker\tother", False)
            self.assertEqual(out.getvalue(), "SKIP\n")
        with patch.object(watchdog, "read_text", side_effect=AssertionError("Unselected plugin must not be read")), \
                patch.object(watchdog, "docker_inventory", return_value=[("cd" * 32, "loxpanel")]), \
                patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            watchdog.hold("/fixture/loxberry", 1234, "docker\t" + "ab" * 32, False)
            self.assertEqual(out.getvalue(), "SKIP\n")

    def test_selected_stopped_container_still_gets_guard_without_docker_action(self):
        fake_signals = types.SimpleNamespace(SIGTERM=15, SIGINT=2, SIGHUP=1, SIG_IGN=1, signal=Mock())
        with patch.object(watchdog, "read_text", return_value=controller()), \
                patch.object(watchdog, "docker_inventory", return_value=[("ab" * 32, "loxpanel")]) as inventory, \
                patch.object(watchdog.subprocess, "run", side_effect=AssertionError("Do not change container state")), \
                patch.object(watchdog, "Owner") as owner, \
                patch.object(watchdog, "LockGuard") as guard, \
                patch.object(watchdog, "serve") as serve, \
                patch.object(watchdog, "signal", fake_signals):
            watchdog.hold("/fixture/loxberry", 1234, "docker\tloxpanel", False)
            guard.assert_called_once_with("/fixture/loxberry/data/plugins/loxpanel/.loxpanel-ctl.lock", owner.return_value)
            serve.assert_called_once()
            guard.return_value.close.assert_called_once_with()
            inventory.assert_called_once_with()

    def test_confirmed_absent_selection_and_legacy_skip_even_unsupported_controller(self):
        for targets, legacy in (("docker\tloxpanel", False), ("", True), ("docker\t" + "ab" * 32, False)):
            for inventory_value in ([], [("cd" * 32, "another")]):
                with self.subTest(targets=targets, legacy=legacy, inventory=inventory_value), \
                        patch.object(watchdog, "docker_inventory", return_value=inventory_value) as inventory, \
                        patch.object(watchdog, "read_text", side_effect=AssertionError("Absent LoxPanel needs no controller protocol")), \
                        patch.object(watchdog, "LockGuard", side_effect=AssertionError("Absent LoxPanel needs no guard")), \
                        patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                    watchdog.hold("/fixture/loxberry", 1234, targets, legacy)
                    self.assertEqual(out.getvalue(), "SKIP\n")
                    inventory.assert_called_once_with()

    def test_inventory_failure_is_not_treated_as_absent(self):
        for targets, legacy in (("docker\tloxpanel", False), ("", True)):
            with self.subTest(targets=targets), \
                    patch.object(watchdog, "docker_inventory", side_effect=watchdog.GuardError("Docker unavailable")), \
                    patch.object(watchdog, "read_text", side_effect=AssertionError("Must fail before reading controller")), \
                    patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                with self.assertRaisesRegex(watchdog.GuardError, "Docker unavailable"):
                    watchdog.hold("/fixture/loxberry", 1234, targets, legacy)
                self.assertNotIn("SKIP", out.getvalue())

    def test_selected_id_reuses_single_inventory_for_presence_and_resolution(self):
        fake_signals = types.SimpleNamespace(SIGTERM=15, SIGINT=2, SIGHUP=1, SIG_IGN=1, signal=Mock())
        with patch.object(watchdog, "read_text", return_value=controller()), \
                patch.object(watchdog, "docker_inventory", return_value=[("ab" * 32, "loxpanel")]) as inventory, \
                patch.object(watchdog, "Owner"), patch.object(watchdog, "LockGuard") as guard, \
                patch.object(watchdog, "serve"), patch.object(watchdog, "signal", fake_signals):
            watchdog.hold("/fixture/loxberry", 1234, "docker\t" + "ab" * 6, False)
            inventory.assert_called_once_with()
            guard.assert_called_once()

    def test_missing_or_root_watchdog_account_is_not_guessed(self):
        fake_pwd = types.SimpleNamespace(getpwnam=Mock(side_effect=KeyError("loxberry")))
        with patch.dict(sys.modules, {"pwd": fake_pwd}), self.assertRaises(watchdog.GuardError):
            watchdog.watchdog_account()
        fake_pwd.getpwnam = Mock(return_value=types.SimpleNamespace(pw_name="loxberry", pw_uid=0, pw_gid=0))
        with patch.dict(sys.modules, {"pwd": fake_pwd}), \
                patch.object(watchdog.os, "getgrouplist", return_value=[0], create=True), \
                self.assertRaises(watchdog.GuardError):
            watchdog.watchdog_account()

    def test_control_protocol_checks_and_releases_before_ack(self):
        guard = Mock()
        owner = Mock(alive=Mock(return_value=True))
        with patch.object(watchdog.select, "select", return_value=([0], [], [])), \
                patch.object(watchdog.os, "read", return_value=b"CHECK\nRELEASE\n"), \
                patch.object(watchdog, "read_text", return_value="controller"), \
                patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            watchdog.serve(guard, owner, "/controller", "controller")
            self.assertEqual(out.getvalue(), "READY loxpanel\nOK\nRELEASED\n")
            guard.check.assert_called_once_with()
            guard.close.assert_called_once_with()

    def test_control_eof_or_owner_death_returns_without_lingering(self):
        for alive in (True, False):
            with self.subTest(alive=alive), patch.object(watchdog.select, "select", return_value=([0], [], [])), \
                    patch.object(watchdog.os, "read", return_value=b""), \
                    patch.object(sys, "stdout", new_callable=io.StringIO):
                watchdog.serve(Mock(), Mock(alive=Mock(return_value=alive)), "/controller", "original")

    def test_control_errors_do_not_return_ok(self):
        for message in (b"UNKNOWN\n", b"CHECK\n"):
            with self.subTest(message=message), patch.object(watchdog.select, "select", return_value=([0], [], [])), \
                    patch.object(watchdog.os, "read", return_value=message), \
                    patch.object(watchdog, "read_text", return_value="changed"), \
                    patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                with self.assertRaises(watchdog.GuardError):
                    watchdog.serve(Mock(), Mock(alive=Mock(return_value=True)), "/controller", "original")
                self.assertNotIn("OK", out.getvalue())

    def test_inherited_operation_fds_are_closed_not_standard_streams(self):
        with patch.object(watchdog.os, "listdir", return_value=["0", "1", "2", "3", "8", "9", "42"]), \
                patch.object(watchdog.os, "close") as close:
            watchdog.close_inherited_descriptors()
            self.assertEqual([call.args[0] for call in close.call_args_list], [3, 8, 9, 42])


@unittest.skipUnless(sys.platform == "linux", "Real no-follow flock safety requires Linux.")
class WatchdogLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-watchdog-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o755)
        self.path = str(self.root / watchdog.LOCK_NAME)
        self.owner = Mock(alive=Mock(return_value=True))
        import pwd
        user = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
        account = (user.pw_uid, user.pw_gid, os.getgrouplist(user.pw_name, user.pw_gid))
        patcher = patch.object(watchdog, "watchdog_account", return_value=account)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.account = account

    def test_new_lock_readable_despite_root_umask_and_not_unlinked(self):
        previous = os.umask(0o077)
        try:
            guard = watchdog.LockGuard(self.path, self.owner)
        finally:
            os.umask(previous)
        self.addCleanup(guard.close)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        guard.close()
        self.assertTrue(Path(self.path).exists())

    def test_existing_contents_inode_mode_preserved_and_real_conflict(self):
        Path(self.path).write_text("preserve me")
        os.chmod(self.path, 0o644)
        original = os.stat(self.path)
        guard = watchdog.LockGuard(self.path, self.owner)
        self.addCleanup(guard.close)
        other = os.open(self.path, os.O_RDONLY)
        try:
            with self.assertRaises(BlockingIOError):
                watchdog.fcntl.flock(other, watchdog.fcntl.LOCK_EX | watchdog.fcntl.LOCK_NB)
            guard.check()
            guard.close()
            watchdog.fcntl.flock(other, watchdog.fcntl.LOCK_EX | watchdog.fcntl.LOCK_NB)
        finally:
            os.close(other)
        current = os.stat(self.path)
        self.assertEqual(current.st_ino, original.st_ino)
        self.assertEqual(current.st_mode, original.st_mode)
        self.assertEqual(Path(self.path).read_text(), "preserve me")

    def test_busy_lock_has_bounded_failure(self):
        first = watchdog.LockGuard(self.path, self.owner)
        self.addCleanup(first.close)
        with self.assertRaisesRegex(watchdog.GuardError, "busy"):
            watchdog.LockGuard(self.path, self.owner, timeout=0)

    def test_replaced_lock_is_detected(self):
        guard = watchdog.LockGuard(self.path, self.owner)
        self.addCleanup(guard.close)
        os.unlink(self.path)
        Path(self.path).write_text("")
        with self.assertRaises(watchdog.GuardError):
            guard.check()

    def test_symlink_fifo_hardlink_and_symlink_parent_rejected(self):
        ordinary = self.root / "ordinary"
        ordinary.write_text("unchanged")
        os.symlink(ordinary, self.path)
        with self.assertRaises((OSError, watchdog.GuardError)):
            watchdog.LockGuard(self.path, self.owner)
        os.unlink(self.path)
        os.mkfifo(self.path)
        with self.assertRaises(watchdog.GuardError):
            watchdog.LockGuard(self.path, self.owner)
        os.unlink(self.path)
        os.link(ordinary, self.path)
        with self.assertRaises(watchdog.GuardError):
            watchdog.LockGuard(self.path, self.owner)
        directory = self.root / "actual"
        directory.mkdir()
        link = self.root / "linked"
        link.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(OSError):
            watchdog.LockGuard(str(link / watchdog.LOCK_NAME), self.owner)
        self.assertEqual(ordinary.read_text(), "unchanged")

    def test_unreadable_existing_lock_not_chmodded(self):
        Path(self.path).write_text("")
        os.chmod(self.path, 0o000)
        with self.assertRaises((watchdog.GuardError, PermissionError)):
            watchdog.LockGuard(self.path, self.owner)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o000)

    def test_owner_permissions_take_precedence_over_other_read_bit(self):
        Path(self.path).write_text("")
        if os.geteuid() == 0:
            os.chown(self.path, self.account[0], self.account[1])
        os.chmod(self.path, 0o004)
        with self.assertRaises((watchdog.GuardError, PermissionError)):
            watchdog.LockGuard(self.path, self.owner)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o004)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "Root needed to simulate inaccessible parent for watchdog user.")
    def test_nontraversable_parent_does_not_claim_protection(self):
        os.chmod(self.root, 0o700)
        with self.assertRaisesRegex(watchdog.GuardError, "cannot read"):
            watchdog.LockGuard(self.path, self.owner)


if __name__ == "__main__":
    unittest.main()
