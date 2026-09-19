import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hostbackup_sources", ROOT / "bin/hostbackup-sources.py")
sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sources)


def mount(path, fstype="ext4"):
    return {"path": path, "fstype": fstype, "kind": sources.mount_kind(fstype)}


def plan(policy="local", overrides=None, mounts=None, excludes=()):
    return sources.SourcePlan({"policy": policy, "overrides": overrides or {}}, mounts or [mount("/")], excludes)


class SourceSelectionTests(unittest.TestCase):
    def test_missing_legacy_configuration_is_not_silently_changed(self):
        result = sources.SourcePlan(None, [mount("/"), mount("/media/smb/nas", "cifs")]).report()
        self.assertEqual(result["selection"], {"policy": "legacy", "overrides": {}})
        self.assertTrue(result["volumes"][1]["included"])
        self.assertTrue(result["notices"])

    def test_local_preserves_root_boot_and_usb_data_but_not_remote_system_autofs(self):
        mounts = [mount("/"), mount("/boot", "vfat"), mount("/media/usb/USB_Loxberry"),
                  mount("/media/smb", "autofs"), mount("/media/smb/nas", "cifs"),
                  mount("/nfs", "nfs4"), mount("/proc", "proc")]
        result = plan(mounts=mounts).report()
        included = {item["path"] for item in result["volumes"] if item["included"]}
        self.assertEqual(included, {"/", "/boot", "/media/usb/USB_Loxberry"})
        self.assertEqual(result["status"], "ok")

    def test_explicit_network_share_can_be_selected_below_autofs(self):
        selection = plan(overrides={"/media/smb/nas": True}, mounts=[mount("/"), mount("/media/smb", "autofs"), mount("/media/smb/nas", "cifs")])
        self.assertTrue(selection.included("/media/smb/nas/file"))
        self.assertFalse(selection.included("/media/smb/other/file"))
        self.assertEqual(selection.report()["errors"], [])

    def test_already_mounted_local_usb_below_autofs_remains_included(self):
        mounts = [mount("/"), mount("/media/usb", "autofs"), mount("/media/usb/USB_Loxberry")]
        selection = plan(mounts=mounts)
        self.assertFalse(selection.included("/media/usb"))
        self.assertTrue(selection.included("/media/usb/USB_Loxberry/data"))
        self.assertFalse(plan(mounts=mounts, overrides={"/media/usb": False}).included("/media/usb/USB_Loxberry/data"))

    def test_local_child_is_not_reenabled_below_excluded_network_parent(self):
        mounts = [mount("/"), mount("/network", "nfs"), mount("/network/auto", "autofs"), mount("/network/auto/local")]
        self.assertFalse(plan(mounts=mounts).included("/network/auto/local/data"))

    def test_explicit_local_child_clears_older_false_override_for_its_local_autofs_descendant(self):
        mounts = [mount("/"), mount("/data"), mount("/data/selected"), mount("/data/selected/auto", "autofs"), mount("/data/selected/auto/usb")]
        selection = plan(mounts=mounts, overrides={"/data": False, "/data/selected": True})
        self.assertTrue(selection.included("/data/selected/auto/usb/file"))

    def test_autofs_container_cannot_be_enabled_as_unknown_bulk_source(self):
        result = plan(overrides={"/media/smb": True}, mounts=[mount("/"), mount("/media/smb", "autofs")]).report()
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["volumes"][1]["selectable"])

    def test_explicit_missing_share_fails_closed(self):
        selection = plan(overrides={"/media/smb/offline": True})
        self.assertEqual(selection.report()["status"], "error")
        with self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(selection))

    def test_absent_disabled_mount_does_not_copy_underlying_directory(self):
        selection = plan(overrides={"/media/old": False})
        self.assertFalse(selection.included("/media/old/leftovers"))
        self.assertTrue(selection.report()["notices"])

    def test_custom_exclude_wins_over_explicit_selection(self):
        selection = plan(overrides={"/media/smb/nas": True}, mounts=[mount("/"), mount("/media/smb/nas", "cifs")], excludes=["/media"])
        self.assertFalse(selection.included("/media/smb/nas"))
        self.assertIn("Ausschluss", selection.report()["volumes"][1]["reason"])
        self.assertTrue(selection.report()["volumes"][1]["forced_excluded"])
        self.assertFalse(selection.report()["volumes"][1]["selectable"])

    def test_disabled_parent_requires_explicit_child_selection(self):
        mounts = [mount("/"), mount("/media/data"), mount("/media/data/child")]
        self.assertFalse(plan(overrides={"/media/data": False}, mounts=mounts).included("/media/data/child/file"))
        self.assertTrue(plan(overrides={"/media/data": False, "/media/data/child": True}, mounts=mounts).included("/media/data/child/file"))

    def test_root_cannot_be_disabled(self):
        with self.assertRaises(sources.SourceError):
            plan(overrides={"/": False})

    def test_invalid_paths_types_and_unknown_policies_are_rejected(self):
        invalid = ["relative", "/media/../etc", "/media/./share", "//media", "/media//share", "/media/share/", "/media/a\nshare", "/media/a\tshare"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(sources.SourceError):
                plan(overrides={value: True})
        for value in [1, "true", None, [], {}]:
            with self.subTest(value=value), self.assertRaises(sources.SourceError):
                plan(overrides={"/media/share": value})
        with self.assertRaises(sources.SourceError):
            plan(policy="all")
        with self.assertRaises(sources.SourceError):
            plan(overrides={f"/share/{index}": True for index in range(257)})

    def test_paths_with_spaces_and_metacharacters_remain_literal_selection_paths(self):
        selection = plan(overrides={"/media/My NAS [2]": True}, mounts=[mount("/"), mount("/media/My NAS [2]", "cifs")])
        self.assertTrue(selection.included("/media/My NAS [2]/data"))

    def test_mount_inventory_decodes_paths_and_never_exports_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "mountinfo"
            inventory.write_text("23 1 8:1 / / rw - ext4 /dev/sda1 rw\n24 23 0:8 / /media/My\\040NAS rw - cifs //user:secret@host/share rw,password=secret\n")
            mounts = sources.read_mounts(inventory)
            result = plan(mounts=mounts).report()
            self.assertEqual(mounts[1]["path"], "/media/My NAS")
            self.assertNotIn("secret", json.dumps(result))
            self.assertNotIn("user", json.dumps(result))

    def test_invalid_or_rootless_mount_inventory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "mountinfo"
            for content in ["broken", "23 1 8:1 / /media rw - ext4 /dev/sda1 rw\n"]:
                inventory.write_text(content)
                with self.assertRaises(sources.SourceError):
                    sources.read_mounts(inventory)

    def test_common_remote_filesystems_are_not_treated_as_local(self):
        for fstype in ["cifs", "smb3", "nfs4", "fuse", "fuse.sshfs", "fuse.rclone", "ceph", "9p"]:
            self.assertEqual(sources.mount_kind(fstype), "network")
        self.assertEqual(sources.mount_kind("fuseblk"), "local")
        self.assertEqual(sources.mount_kind("ext4"), "local")

    def test_literal_exclude_optimization_matches_restore_rules(self):
        for rules in [["/proc"], ["cache/"], ["/cache/"], ["one/two"], ["/literal\\name"], ["*.log"], ["/media/***"]]:
            selection = plan(excludes=rules)
            for value in ["proc", "proc/file", "proc2", "cache", "cache/a", "a/cache", "a/cache/b", "one/two/file", "other/one/two", "literal\\name", "var/app.log", "media", "media/a/b"]:
                for is_dir in [True, False]:
                    with self.subTest(rules=rules, value=value, is_dir=is_dir):
                        self.assertEqual(selection.excluded(value, is_dir), sources.recovery.excluded(value, rules, is_dir))

    def test_validation_cli_has_no_mount_or_filesystem_dependency(self):
        command = [sys.executable, "-B", str(ROOT / "bin/hostbackup-sources.py"), "validate", "--selection"]
        result = subprocess.run(command + ['{"policy":"local","overrides":{"/media/nas":true}}'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["overrides"], {"/media/nas": True})
        result = subprocess.run(command + ["null"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_report_is_private_exclusive_and_mount_identity_is_verified(self):
        mounts = [{**mount("/"), "device": "8:1", "mount_id": "23"}]
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "source-selection.json"
            report = plan(mounts=mounts).report()
            report["mount_identity"] = sources.mount_identity(mounts)
            sources.write_report(report_path, report)
            if os.name == "posix":
                self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                sources.write_report(report_path, report)
            with patch.object(sources, "read_mounts", return_value=mounts):
                sources.verify_report(report_path)
            changed = [{**mounts[0], "mount_id": "24"}]
            with patch.object(sources, "read_mounts", return_value=changed), self.assertRaises(sources.SourceError):
                sources.verify_report(report_path)

    def test_report_without_mount_identity_is_not_treated_as_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "source-selection.json"
            report_path.write_text("{}")
            with self.assertRaises(sources.SourceError):
                sources.verify_report(report_path)


class EnumerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ["etc", "boot", "media/usb/USB_Loxberry", "media/usb/PI_Backup", "media/smb/nas", "media/smb/other", "nfs", "tmp"]:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
            (self.root / directory / "data.txt").write_text(directory)
        self.mounts = [mount("/"), mount("/boot", "vfat"), mount("/media/usb/USB_Loxberry"), mount("/media/usb/PI_Backup"),
                       mount("/media/smb", "autofs"), mount("/media/smb/nas", "cifs"), mount("/media/smb/other", "cifs"), mount("/nfs", "nfs4")]

    def selection(self, overrides=None):
        return plan(overrides=overrides, mounts=self.mounts, excludes=["/media/usb/PI_Backup", "/tmp"])

    def test_local_list_includes_boot_and_usb_data_without_network_or_backup_target(self):
        entries = list(sources.enumerate_files(self.selection(), self.root))
        self.assertIn("boot/data.txt", entries)
        self.assertIn("media/usb/USB_Loxberry/data.txt", entries)
        for forbidden in ["media/smb", "nfs", "tmp", "media/usb/PI_Backup"]:
            self.assertFalse(any(value == forbidden or value.startswith(forbidden + "/") for value in entries))
        self.assertEqual(len(entries), len(set(entries)))

    def test_selected_share_does_not_scan_autofs_parent_or_siblings(self):
        original = os.scandir
        scanned = []

        def guarded(path):
            relative = Path(path).relative_to(self.root).as_posix()
            scanned.append(relative)
            if relative in ["media/smb", "media/smb/other", "nfs"]:
                raise AssertionError("Unselected network directory was touched")
            return original(path)

        with patch.object(sources.os, "scandir", side_effect=guarded):
            entries = list(sources.enumerate_files(self.selection({"/media/smb/nas": True}), self.root))
        self.assertIn("media/smb/nas/data.txt", entries)
        self.assertNotIn("media/smb/other", scanned)
        self.assertNotIn("media/smb", scanned)

    def test_ten_nas_shares_are_excluded_and_only_one_explicit_share_adds_bytes(self):
        (self.root / "shares").mkdir()
        mounts = list(self.mounts) + [mount("/shares", "autofs")]
        for index in range(10):
            directory = self.root / "shares" / str(index)
            directory.mkdir()
            (directory / "payload.bin").write_bytes(b"x" * (1000 + index))
            mounts.append(mount(f"/shares/{index}", "cifs"))
        default_plan = plan(mounts=mounts, excludes=["/media/usb/PI_Backup", "/tmp"])
        selected_plan = plan(overrides={"/shares/4": True}, mounts=mounts, excludes=["/media/usb/PI_Backup", "/tmp"])
        default_entries = list(sources.enumerate_files(default_plan, self.root))
        selected_entries = list(sources.enumerate_files(selected_plan, self.root))
        self.assertFalse(any(path.startswith("shares/") for path in default_entries))
        self.assertEqual([path for path in selected_entries if path.startswith("shares/")], ["shares/4", "shares/4/payload.bin"])

        def byte_count(entries):
            return sum((self.root / path).stat().st_size for path in entries if (self.root / path).is_file())

        self.assertEqual(byte_count(selected_entries) - byte_count(default_entries), 1004)

    def test_excluded_share_is_not_even_statted(self):
        original = Path.lstat

        def guarded(path):
            if path == self.root / "media/smb":
                raise AssertionError("Autofs stat can activate mounts")
            return original(path)

        with patch.object(Path, "lstat", guarded):
            list(sources.enumerate_files(self.selection(), self.root))

    def test_known_local_usb_under_autofs_is_routed_without_listing_namespace(self):
        self.mounts.append(mount("/media/usb", "autofs"))
        original = os.scandir

        def guarded(path):
            if Path(path) == self.root / "media/usb":
                raise AssertionError("Autofs namespace must not be scanned")
            return original(path)

        with patch.object(sources.os, "scandir", side_effect=guarded):
            entries = list(sources.enumerate_files(self.selection(), self.root))
        self.assertIn("media/usb/USB_Loxberry/data.txt", entries)
        self.assertNotIn("media/usb/PI_Backup", entries)

    def test_unreadable_directory_fails_instead_of_silent_incomplete_backup(self):
        original = os.scandir

        def guarded(path):
            if Path(path) == self.root / "etc":
                raise PermissionError("denied")
            return original(path)

        with patch.object(sources.os, "scandir", side_effect=guarded), self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(self.selection(), self.root))

    def test_vanished_selected_mount_fails_instead_of_copying_missing_path(self):
        selection = self.selection({"/media/smb/nas": True})
        original = Path.lstat

        def vanished(path):
            if path == self.root / "media/smb/nas":
                raise FileNotFoundError("mount disappeared")
            return original(path)

        with patch.object(Path, "lstat", vanished), self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(selection, self.root))

    @unittest.skipUnless(os.name == "posix", "Real symlinks required")
    def test_symlinks_are_listed_but_never_followed(self):
        (self.root / "etc/link").symlink_to(self.root / "nfs", target_is_directory=True)
        entries = list(sources.enumerate_files(self.selection(), self.root))
        self.assertIn("etc/link", entries)
        self.assertFalse(any(value.startswith("etc/link/") for value in entries))

    @unittest.skipUnless(os.name == "posix", "Real symlinks required")
    def test_selected_share_reached_through_symlink_is_rejected(self):
        (self.root / "link").symlink_to(self.root / "media/smb", target_is_directory=True)
        selection = plan(overrides={"/link/nas": True}, mounts=self.mounts + [mount("/link/nas", "cifs")])
        with self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(selection, self.root))

    @unittest.skipUnless(os.name == "posix", "Linux device identifiers required")
    def test_unexpected_device_change_fails_closed(self):
        self.mounts[0]["device"] = "999:999"
        with self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(self.selection(), self.root))

    @unittest.skipUnless(os.name == "posix" and shutil.which("rsync") and shutil.which("tar"), "Linux rsync and tar required")
    def test_real_rsync_and_tar_copy_explicit_list_without_recursing_into_siblings(self):
        (self.root / "etc/name\nwith newline").write_text("nul-safe")
        os.link(self.root / "etc/data.txt", self.root / "etc/hardlink")
        (self.root / "etc/symlink").symlink_to("data.txt")
        os.mkfifo(self.root / "etc/fifo")
        selection = self.selection({"/media/smb/nas": True})
        entries = list(sources.enumerate_files(selection, self.root))
        with tempfile.TemporaryDirectory() as output:
            output = Path(output)
            file_list = output / "files.list"
            file_list.write_bytes(b"".join(os.fsencode(value) + b"\0" for value in entries))
            destination = output / "copy"
            destination.mkdir()
            subprocess.run(["rsync", "-aH", "--from0", "--files-from=" + str(file_list), "--no-recursive", "--dirs", str(self.root) + "/", str(destination) + "/"], check=True, capture_output=True)
            self.assertEqual((destination / "etc/name\nwith newline").read_text(), "nul-safe")
            self.assertEqual((destination / "etc/data.txt").stat().st_ino, (destination / "etc/hardlink").stat().st_ino)
            self.assertTrue((destination / "etc/symlink").is_symlink())
            self.assertTrue(sources.stat.S_ISFIFO((destination / "etc/fifo").stat().st_mode))
            self.assertTrue((destination / "media/smb/nas/data.txt").is_file())
            self.assertFalse((destination / "media/smb/other").exists())
            self.assertFalse((destination / "media/usb/PI_Backup").exists())
            archive = output / "rootfs.tar"
            subprocess.run(["tar", "--no-recursion", "--null", "-C", str(self.root), "-cpf", str(archive), "--files-from=" + str(file_list)], check=True, capture_output=True)
            with tarfile.open(archive) as handle:
                names = handle.getnames()
                self.assertEqual(len(names), len(set(names)))
                self.assertIn("media/smb/nas/data.txt", names)
                self.assertNotIn("media/smb/other", names)
                self.assertTrue(handle.getmember("etc/hardlink").islnk())
                self.assertTrue(handle.getmember("etc/symlink").issym())
                self.assertTrue(handle.getmember("etc/fifo").isfifo())


if __name__ == "__main__":
    unittest.main()
