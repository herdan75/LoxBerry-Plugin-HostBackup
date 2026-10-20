import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hostbackup_runtime_policy", ROOT / "bin/hostbackup-runtime-policy.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = runtime.RuntimePolicy()

    def make_file(self, logical, content="diagnostic"):
        path = self.root / logical.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def entry(self, path):
        with os.scandir(path.parent) as entries:
            return next(entry for entry in entries if entry.name == path.name)

    def omitted(self, logical, policy=None):
        path = self.make_file(logical)
        return (policy or self.policy).should_omit(logical, self.entry(path), self.root)

    def test_managed_payload_is_not_based_on_plugin_or_filename(self):
        for suffix in ("/log/plugins/new-plugin/future.txt", "/log/plugins/stats4lox/grabber.log",
                       "/log/system_tmpfs/logs_sqlite.dat", "/log/system_tmpfs/logs_sqlite.dat-wal",
                       "/log/ramlog/log/plugins/audioserver/session.log.gz",
                       "/log/ramlog/log/system_tmpfs/maintenance.log"):
            with self.subTest(suffix=suffix):
                self.assertTrue(self.omitted("/opt/loxberry" + suffix))

    def test_persistent_audit_configuration_database_and_global_logs_stay_required(self):
        for path in ("/opt/loxberry/log/system/plugininstall/install.log",
                     "/opt/loxberry/log/system/update.log", "/opt/loxberry/log/system/logs_sqlite.dat.bkp",
                     "/opt/loxberry/config/plugins/one/config.json", "/opt/loxberry/data/plugins/one/state.db",
                     "/var/lib/docker/containers/one/config.v2.json", "/var/log/example.log",
                     "/opt/loxberry/log/ramlog/log/system/plugininstall/install.log",
                     "/opt/loxberry/log/plugins-other/user.log", "/srv/other/log/plugins/one/file.log"):
            with self.subTest(path=path):
                self.assertFalse(self.omitted(path))

    def test_custom_home_has_same_policy_without_affecting_old_home(self):
        policy = runtime.RuntimePolicy("/srv/loxberry")
        self.assertTrue(self.omitted("/srv/loxberry/log/plugins/example/log", policy))
        self.assertFalse(self.omitted("/opt/loxberry/log/plugins/example/log", policy))

    def test_including_runtime_logs_disables_omission(self):
        policy = runtime.RuntimePolicy(include_runtime_logs=True)
        self.assertFalse(self.omitted("/opt/loxberry/log/plugins/example/log", policy))
        self.assertFalse(policy.report()["enabled"])

    def test_explicit_include_inside_managed_root_wins(self):
        base = "/opt/loxberry/log/plugins"
        for selected in (base, base + "/custom", base + "/custom/source"):
            policy = runtime.RuntimePolicy(overrides={selected: True})
            self.assertFalse(self.omitted(base + "/custom/source/data", policy))
        policy = runtime.RuntimePolicy(overrides={base + "/custom": True})
        self.assertTrue(self.omitted(base + "/other/log", policy))

    def test_broader_disk_include_keeps_documented_content_default(self):
        policy = runtime.RuntimePolicy(overrides={"/opt": True})
        self.assertTrue(self.omitted("/opt/loxberry/log/plugins/custom/log", policy))

    def test_directory_skeleton_and_mode_remain_unmodified(self):
        logical = "/opt/loxberry/log/plugins/custom"
        directory = self.root / logical.lstrip("/")
        directory.mkdir(parents=True)
        if os.name == "posix":
            directory.chmod(0o750)
        before = directory.stat().st_mode
        self.assertFalse(self.policy.should_omit(logical, self.entry(directory), self.root))
        self.assertEqual(directory.stat().st_mode, before)

    def test_managed_root_itself_never_omitted_even_if_replaced_with_file(self):
        self.assertFalse(self.omitted("/opt/loxberry/log/plugins"))

    def test_unobserved_missing_entry_is_not_assumed_to_be_disposable(self):
        logical = "/opt/loxberry/log/plugins/custom/missing"
        self.assertFalse(self.policy.should_omit(logical, None, self.root))
        missing = Mock(path=str(self.root / logical.lstrip("/")))
        missing.is_file.return_value = False
        self.assertFalse(self.policy.should_omit(logical, missing, self.root))

    def test_observed_regular_entry_may_rotate_before_lstat(self):
        logical = "/opt/loxberry/log/plugins/custom/rotate.log"
        path = self.make_file(logical)
        entry = self.entry(path)
        self.assertTrue(entry.is_file(follow_symlinks=False))
        path.unlink()
        self.assertTrue(self.policy.should_omit(logical, entry, self.root))

    def test_missing_parent_is_not_ignored(self):
        logical = "/opt/loxberry/log/plugins/custom/gone.log"
        path = self.make_file(logical)
        entry = self.entry(path)
        path.unlink()
        path.parent.rmdir()
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    def test_cached_regular_entry_replaced_with_directory_stays_required(self):
        logical = "/opt/loxberry/log/plugins/custom/replaced"
        path = self.make_file(logical)
        entry = self.entry(path)
        self.assertTrue(entry.is_file(follow_symlinks=False))
        path.unlink()
        path.mkdir()
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    def test_cached_regular_entry_replaced_with_symlink_stays_required(self):
        logical = "/opt/loxberry/log/plugins/custom/replaced"
        path = self.make_file(logical)
        entry = self.entry(path)
        self.assertTrue(entry.is_file(follow_symlinks=False))
        path.unlink()
        try:
            path.symlink_to(self.make_file("/data/important"))
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    def test_permission_or_io_error_is_not_an_omission(self):
        logical = "/opt/loxberry/log/plugins/custom/fail.log"
        path = self.make_file(logical)
        entry = Mock(path=str(path))
        for error in (PermissionError("denied"), OSError("I/O")):
            entry.is_file.side_effect = error
            self.assertFalse(self.policy.should_omit(logical, entry, self.root))
        entry.is_file.side_effect = None
        entry.is_file.return_value = True
        with patch.object(Path, "lstat", side_effect=PermissionError("denied")), \
                patch.object(runtime.os, "open", side_effect=PermissionError("denied")):
            self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    def test_entry_cannot_come_from_another_directory(self):
        logical = "/opt/loxberry/log/plugins/custom/log"
        entry = self.entry(self.make_file("/etc/config"))
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    @unittest.skipUnless(os.name == "posix", "Pinned directory descriptors are a POSIX safeguard")
    def test_linux_pins_ancestors_instead_of_following_pathname_checks(self):
        logical = "/opt/loxberry/log/plugins/custom/log"
        path = self.make_file(logical)
        entry = self.entry(path)
        self.assertTrue(entry.is_file(follow_symlinks=False))
        with patch.object(Path, "lstat", side_effect=AssertionError("pathname fallback used")):
            self.assertTrue(self.policy.should_omit(logical, entry, self.root))

    @unittest.skipUnless(os.name == "posix" and Path("/proc/self/fd").is_dir(), "Linux descriptor accounting")
    def test_pinned_parent_descriptors_are_closed_after_success_and_failure(self):
        logical = "/opt/loxberry/log/plugins/custom/log"
        path = self.make_file(logical)
        entry = self.entry(path)
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(30):
            self.assertTrue(self.policy.should_omit(logical, entry, self.root))
        path.unlink()
        path.parent.rmdir()
        for _ in range(30):
            self.assertFalse(self.policy.should_omit(logical, entry, self.root))
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_fifo_socket_and_devices_are_not_payload(self):
        logical = "/opt/loxberry/log/plugins/custom/special"
        path = self.make_file(logical)
        entry = Mock(path=str(path))
        entry.is_file.return_value = False
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))
        entry.is_file.assert_called_once_with(follow_symlinks=False)

    def test_symlink_object_is_not_followed_or_omitted(self):
        logical = "/opt/loxberry/log/plugins/custom/link"
        path = self.root / logical.lstrip("/")
        path.parent.mkdir(parents=True)
        target = self.make_file("/data/important")
        try:
            path.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertFalse(self.policy.should_omit(logical, self.entry(path), self.root))
        self.assertEqual(target.read_text(), "diagnostic")

    def test_symlink_parent_cannot_launder_important_data(self):
        logical = "/opt/loxberry/log/plugins/custom/data"
        parent = self.root / "opt/loxberry/log/plugins"
        parent.mkdir(parents=True)
        target = self.make_file("/data/important/data")
        try:
            (parent / "custom").symlink_to(target.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        entry = self.entry(parent / "custom/data")
        self.assertFalse(self.policy.should_omit(logical, entry, self.root))

    def test_known_tmpfs_root_is_accepted_only_with_unambiguous_root(self):
        logical = "/opt/loxberry/log/plugins/custom/log"
        mount = {"path": "/opt/loxberry/log/plugins", "fstype": "tmpfs", "root": "/"}
        self.assertTrue(self.omitted(logical, runtime.RuntimePolicy(mounts=[mount])))
        for altered in ({"root": "/user/data"}, {"fstype": "ext4"}, {"fstype": "cifs"},
                        {"stack": [1, 2]}, {"root": None}):
            with self.subTest(altered=altered):
                self.assertFalse(self.omitted(logical, runtime.RuntimePolicy(mounts=[{**mount, **altered}])))

    def test_unexpected_mount_inside_runtime_area_is_not_disposable(self):
        logical = "/opt/loxberry/log/plugins/custom/log"
        for target in ("/opt/loxberry/log", "/opt/loxberry/log/plugins/custom", logical):
            mount = {"path": target, "fstype": "tmpfs", "root": "/"}
            self.assertFalse(self.omitted(logical, runtime.RuntimePolicy(mounts=[mount])))

    def ramlog_mounts(self, fstype="tmpfs", device="0:40"):
        base = "/opt/loxberry/log"
        return [
            {"path": base + "/ramlog", "fstype": fstype, "device": device, "root": "/"},
            {"path": base + "/plugins", "fstype": fstype, "device": device, "root": "/log/plugins"},
            {"path": base + "/system_tmpfs", "fstype": fstype, "device": device, "root": "/log/system_tmpfs"},
        ]

    def test_official_tmpfs_ramlog_backing_and_front_bind_mounts(self):
        policy = runtime.RuntimePolicy(mounts=self.ramlog_mounts())
        for suffix in runtime.RUNTIME_SUFFIXES:
            self.assertTrue(self.omitted("/opt/loxberry" + suffix + "/custom/runtime", policy))

    def test_official_zram_backing_requires_kernel_device_evidence(self):
        mounts = self.ramlog_mounts("ext4", "252:0")
        for verified in (True, False):
            with patch.object(runtime, "_is_zram_device", return_value=verified):
                policy = runtime.RuntimePolicy(mounts=mounts)
            for suffix in runtime.RUNTIME_SUFFIXES:
                with self.subTest(verified=verified, suffix=suffix):
                    self.assertEqual(self.omitted("/opt/loxberry" + suffix + "/custom/runtime", policy), verified)

    def test_ramlog_bind_requires_matching_backing_device_filesystem_and_subroot(self):
        for altered in ({"device": "0:41"}, {"fstype": "ext4"}, {"root": "/data"}, {"stack": [1, 2]}):
            mounts = self.ramlog_mounts()
            mounts[1].update(altered)
            with self.subTest(altered=altered):
                self.assertFalse(self.omitted("/opt/loxberry/log/plugins/custom/log", runtime.RuntimePolicy(mounts=mounts)))

    def test_ramlog_backing_missing_stacked_wrong_root_or_network_keeps_data_required(self):
        for alteration in (None, {"root": "/data"}, {"stack": [1, 2]}, {"fstype": "cifs"}, {"device": "bad"}):
            mounts = self.ramlog_mounts()
            if alteration is None:
                mounts = mounts[1:]
            else:
                mounts[0].update(alteration)
            with self.subTest(alteration=alteration):
                self.assertFalse(self.omitted("/opt/loxberry/log/plugins/custom/log", runtime.RuntimePolicy(mounts=mounts)))

    def test_unexpected_nested_bind_remains_required_even_on_verified_ramlog(self):
        mounts = self.ramlog_mounts()
        mounts.append({"path": "/opt/loxberry/log/plugins/custom", "fstype": "tmpfs", "device": "0:40", "root": "/data"})
        self.assertFalse(self.omitted("/opt/loxberry/log/plugins/custom/log", runtime.RuntimePolicy(mounts=mounts)))

    def test_zram_identity_is_only_read_from_kernel_device_path(self):
        for value in ("", "../../data", "zram0", None):
            self.assertFalse(runtime._is_zram_device(value))
        for target, expected in (("/sys/devices/virtual/block/zram0", True),
                                 ("/sys/devices/virtual/block/zram12", True),
                                 ("/sys/devices/virtual/block/loop0", False),
                                 ("/tmp/zram0", False)):
            with patch.object(Path, "resolve", return_value=Path(target)):
                self.assertEqual(runtime._is_zram_device("252:0"), expected)
        with patch.object(Path, "resolve", side_effect=FileNotFoundError()):
            self.assertFalse(runtime._is_zram_device("252:0"))

    def test_mount_outside_runtime_area_does_not_disable_policy(self):
        for target in ("/", "/opt", "/opt/loxberry", "/mnt/nas"):
            mount = {"path": target, "fstype": "ext4", "root": "/"}
            self.assertTrue(self.omitted("/opt/loxberry/log/plugins/custom/log", runtime.RuntimePolicy(mounts=[mount])))

    def test_report_is_bounded_and_detached(self):
        for number in range(runtime.MAX_SAMPLE_PATHS + 5):
            self.assertTrue(self.omitted(f"/opt/loxberry/log/plugins/custom/{number}.log"))
        report = self.policy.report()
        self.assertEqual(report["version"], runtime.POLICY_VERSION)
        self.assertEqual(report["omitted_regular_files"], runtime.MAX_SAMPLE_PATHS + 5)
        self.assertEqual(len(report["sample_paths"]), runtime.MAX_SAMPLE_PATHS)
        self.assertTrue(report["samples_truncated"])
        report["sample_paths"].clear()
        report["managed_roots"].clear()
        self.assertEqual(len(self.policy.report()["sample_paths"]), runtime.MAX_SAMPLE_PATHS)
        self.assertEqual(len(self.policy.report()["managed_roots"]), 4)

    def test_invalid_home_and_switch_are_rejected(self):
        for value in ("/", "relative", "//opt/loxberry", "/opt/../loxberry", "/opt/loxberry/", "/opt/loxberry\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.RuntimePolicy(value)
        for value in (None, "false", 0, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.RuntimePolicy(include_runtime_logs=value)

    def test_invalid_candidate_paths_are_never_omitted(self):
        path = self.make_file("/opt/loxberry/log/plugins/custom/log")
        entry = self.entry(path)
        for logical in ("/opt/loxberry/log/plugins/../config", "//opt/loxberry/log/plugins/custom/log",
                        "/opt/loxberry/log/plugins/custom/log\n", "/opt/loxberry/log/plugins//custom/log"):
            self.assertFalse(self.policy.should_omit(logical, entry, self.root))


if __name__ == "__main__":
    unittest.main()
