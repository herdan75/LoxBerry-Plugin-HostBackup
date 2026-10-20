import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
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

    def test_socket_omission_flag_requires_files_action_and_a_report(self):
        command = [sys.executable, "-B", str(ROOT / "bin/hostbackup-sources.py")]
        for arguments in [
            ["validate", "--selection", '{"policy":"local","overrides":{}}', "--omit-sockets"],
            ["source-info", "--config", "/unused", "--report", "/unused-report", "--omit-sockets"],
            ["verify", "--report", "/unused-report", "--omit-sockets"],
            ["files", "--config", "/unused", "--omit-sockets"],
        ]:
            with self.subTest(arguments=arguments):
                result = subprocess.run(command + arguments, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("--omit-sockets ist nur fuer files mit --report erlaubt", result.stderr)
                self.assertEqual(result.stdout, "")

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


class FrozenMountVerificationTests(unittest.TestCase):
    def setUp(self):
        self.mounts = [self.volume("/", "1"), self.volume("/boot", "2", "vfat"),
                       self.volume("/media/smb", "3", "autofs"),
                       self.volume("/media/smb/ignored", "4", "cifs"),
                       self.volume("/run", "5", "tmpfs")]

    @staticmethod
    def volume(path, identifier, fstype="ext4", root="/"):
        return {**mount(path, fstype), "device": "8:" + identifier, "mount_id": identifier, "root": root}

    def verify(self, selection, current):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            sources.write_report(path, sources.verification_report(selection))
            with patch.object(sources, "read_mounts", return_value=current):
                sources.verify_report(path)

    def test_unselected_network_and_runtime_mount_churn_is_ignored(self):
        selected = plan(mounts=self.mounts)
        current = self.mounts[:2] + [self.volume("/media/smb", "30", "autofs"),
                                  self.volume("/media/smb/new", "31", "cifs"),
                                  self.volume("/run/private", "32", "tmpfs")]
        self.verify(selected, current)

    def test_new_network_mount_outside_old_excluded_boundary_shadows_selected_tree(self):
        selected = plan(mounts=self.mounts)
        for fstype in ["cifs", "tmpfs", "autofs", "ext4"]:
            with self.subTest(fstype=fstype), self.assertRaisesRegex(sources.SourceError, "/etc.*neu eingebunden"):
                self.verify(selected, self.mounts + [self.volume("/etc", "40", fstype)])

    def test_directory_only_rule_does_not_hide_new_bind_over_required_regular_file(self):
        selected = plan(mounts=self.mounts, excludes=["/etc/passwd/"])
        self.assertFalse(selected.excluded("/etc/passwd", False))
        with self.assertRaisesRegex(sources.SourceError, "/etc/passwd.*neu eingebunden"):
            self.verify(selected, self.mounts + [self.volume("/etc/passwd", "40")])

    def test_directory_only_rule_still_ignores_changes_beneath_excluded_directory(self):
        selected = plan(mounts=self.mounts, excludes=["/cache/"])
        self.verify(selected, self.mounts + [self.volume("/cache/child", "40")])

    def test_confirmed_directory_excludes_are_frozen_as_literal_not_wildcard_paths(self):
        for target in ("/cache/a*b", "/cache/a?b", "/cache/a[b", "/cache/a\\*b"):
            selected = plan(mounts=self.mounts, excludes=["/cache/*/"])
            selected.confirmed_directory_excludes.add(target)
            report = sources.verification_report(selected)
            frozen = plan(mounts=self.mounts, excludes=report["frozen_excludes"])
            with self.subTest(target=target):
                self.assertTrue(frozen.excluded(target, False))
                self.assertFalse(frozen.excluded("/cache/axxb", False))

    def test_selected_mount_disappearance_and_replacement_are_errors(self):
        selected = plan(mounts=self.mounts)
        for current in [self.mounts[:1] + self.mounts[2:],
                        [self.mounts[0], self.volume("/boot", "21", "vfat")] + self.mounts[2:]]:
            with self.assertRaisesRegex(sources.SourceError, "/boot"):
                self.verify(selected, current)

    def test_same_device_and_id_but_changed_bind_root_is_rejected(self):
        selected = plan(mounts=self.mounts)
        current = [dict(item) for item in self.mounts]
        current[1]["root"] = "/another-folder"
        with self.assertRaisesRegex(sources.SourceError, "/boot.*ersetzt/geaendert"):
            self.verify(selected, current)

    def test_selected_share_retains_ancestor_checks(self):
        selected = plan(mounts=self.mounts, overrides={"/media/smb/ignored": True})
        for index in [2, 3]:
            with self.subTest(index=index), self.assertRaisesRegex(sources.SourceError, "/media/smb"):
                self.verify(selected, self.mounts[:index] + self.mounts[index + 1:])

    def test_new_mount_above_explicit_child_of_disabled_path_is_rejected(self):
        mounts = self.mounts + [self.volume("/data/selected", "41", "cifs")]
        selected = plan(mounts=mounts, overrides={"/data": False, "/data/selected": True})
        with self.assertRaisesRegex(sources.SourceError, '/data.*neu eingebunden'):
            self.verify(selected, mounts + [self.volume("/data", "42", "autofs")])

    def test_frozen_user_excludes_and_disabled_absent_paths_ignore_mounts(self):
        selected = plan(mounts=self.mounts, overrides={"/not-mounted": False}, excludes=["/backup", "/cache/***"])
        current = self.mounts + [self.volume("/not-mounted", "51"), self.volume("/backup", "52", "cifs"),
                                self.volume("/cache/any", "53")]
        self.verify(selected, current)

    def test_legacy_policy_still_requires_included_network_mount(self):
        selected = plan(policy="legacy", mounts=self.mounts)
        with self.assertRaisesRegex(sources.SourceError, "/media/smb/ignored"):
            self.verify(selected, self.mounts[:3] + self.mounts[4:])

    def test_excluded_mount_disappearing_does_not_include_underlying_directory(self):
        selected = plan(mounts=self.mounts)
        self.verify(selected, self.mounts[:3] + self.mounts[4:])
        self.assertFalse(selected.included("/media/smb/ignored/local-data"))

    def test_mount_inventory_order_is_not_a_change(self):
        self.verify(plan(mounts=self.mounts), list(reversed(self.mounts)))

    def test_mount_stack_is_not_silently_collapsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mountinfo"
            path.write_text("1 0 8:1 / / rw - ext4 /dev/root rw\n"
                            "2 1 8:1 /data /etc rw - ext4 /dev/root rw\n"
                            "3 1 8:1 /secret /etc rw - ext4 /dev/root rw\n")
            mounts = sources.read_mounts(path)
            selected = plan(mounts=mounts)
            self.assertEqual(len(mounts[1]["stack"]), 2)
            self.assertEqual(selected.report()["status"], "error")
            with self.assertRaisesRegex(sources.SourceError, "Mehrere Einbindungen"):
                sources.verify_mounts(selected, mounts)
            selected = plan(mounts=mounts, excludes=["/etc"])
            self.assertEqual(selected.report()["status"], "ok")
            sources.verify_mounts(selected, mounts[:1])

    def test_new_stack_at_selected_path_is_rejected(self):
        current = [dict(item) for item in self.mounts]
        current[1]["stack"] = [{key: current[1][key] for key in ("fstype", "device", "mount_id", "root")}]
        with self.assertRaisesRegex(sources.SourceError, "/boot"):
            self.verify(plan(mounts=self.mounts), current)

    def test_stack_order_cannot_hide_a_selected_local_layer_behind_network_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mountinfo"
            path.write_text("1 0 8:1 / / rw - ext4 /dev/root rw\n"
                            "2 1 8:2 / /data rw - ext4 /dev/data rw\n"
                            "3 1 0:3 / /data rw - cifs //nas/data rw\n")
            mounts = sources.read_mounts(path)
            self.assertEqual(mounts[1]["fstype"], "cifs")
            self.assertEqual(plan(mounts=mounts).report()["status"], "error")
            self.assertEqual(plan(mounts=mounts, overrides={"/data": False}).report()["status"], "ok")

    def automount_fixture(self, reverse=False, fstype="cifs", upper_parent="20", lower_parent="1", extra=""):
        lines = ["1 0 8:1 / / rw - ext4 /dev/root rw\n",
                 f"20 {lower_parent} 0:20 / /data rw - autofs systemd-1 rw\n",
                 f"21 {upper_parent} 0:21 / /data rw - {fstype} data-source rw\n"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mountinfo"
            path.write_text("".join(reversed(lines) if reverse else lines) + extra)
            return sources.read_mounts(path)

    def test_direct_automount_data_stack_uses_parent_chain_not_table_order(self):
        for fstype in ("cifs", "nfs4", "ext4"):
            forward = self.automount_fixture(fstype=fstype)
            reverse = self.automount_fixture(reverse=True, fstype=fstype)
            self.assertEqual(forward, reverse)
            selected = plan(mounts=forward, overrides={"/data": True})
            self.assertEqual(selected.report()["status"], "ok", selected.errors)
            self.assertTrue(selected.included("/data/required-file"))
            self.assertEqual(selected.mounts["/data"]["fstype"], fstype)
            self.assertEqual(selected.mounts["/data"]["parent_id"], "20")
            self.verify(selected, reverse)

    def test_direct_automount_is_not_implicitly_selected_as_network_source(self):
        selected = plan(mounts=self.automount_fixture())
        self.assertEqual(selected.report()["status"], "ok")
        self.assertFalse(selected.included("/data/remote-file"))
        self.assertTrue(plan(mounts=self.automount_fixture(fstype="ext4")).included("/data/local-file"))

    def test_direct_automount_data_disappearance_replacement_and_reparenting_fail(self):
        original = self.automount_fixture()
        selected = plan(mounts=original, overrides={"/data": True})
        lower = original[1]["stack"][0]
        disappeared = [original[0], {"path": "/data", "kind": "automount", **lower}]
        replaced = json.loads(json.dumps(original))
        replaced[1]["mount_id"] = "22"
        replaced[1]["stack"][1]["mount_id"] = "22"
        for current in (disappeared, replaced, self.automount_fixture(upper_parent="1")):
            with self.subTest(current=current), self.assertRaisesRegex(sources.SourceError, "/data"):
                self.verify(selected, current)

    def test_direct_automount_requires_one_proven_chain_and_one_data_layer(self):
        cases = [self.automount_fixture(upper_parent="1"), self.automount_fixture(lower_parent="21"),
                 self.automount_fixture(extra="22 21 8:2 / /data rw - ext4 /dev/other rw\n"),
                 self.automount_fixture(fstype="tmpfs")]
        old = self.automount_fixture()
        old[1].pop("parent_id")
        for layer in old[1]["stack"]:
            layer.pop("parent_id")
        cases.append(old)
        for mounts in cases:
            with self.subTest(mounts=mounts):
                self.assertEqual(plan(mounts=mounts, overrides={"/data": True}).report()["status"], "error")

    def test_parent_id_is_validated_in_kernel_inventory_and_frozen_receipt(self):
        with self.assertRaises(sources.SourceError):
            self.automount_fixture(upper_parent="invalid")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection.json"
            for mutate_layer in (False, True):
                report = sources.verification_report(plan(mounts=self.automount_fixture(), overrides={"/data": True}))
                item = report["mount_identity"][1]
                (item["stack"][1] if mutate_layer else item)["parent_id"] = "invalid"
                path.write_text(json.dumps(report))
                with self.assertRaises(sources.SourceError):
                    sources.verify_report(path)

    def test_older_receipts_without_parent_ids_retain_existing_identity_checks(self):
        current = [{**item, "parent_id": "0" if item["path"] == "/" else "1"} for item in self.mounts]
        self.verify(plan(mounts=self.mounts), current)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps({"mount_identity": sources.mount_identity(self.mounts)}))
            with patch.object(sources, "read_mounts", return_value=current):
                sources.verify_report(path)
            current[1]["root"] = "/different"
            with patch.object(sources, "read_mounts", return_value=current), self.assertRaises(sources.SourceError):
                sources.verify_report(path)

    def test_old_reports_without_scope_remain_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps({"mount_identity": sources.mount_identity(self.mounts, legacy=True)}))
            with patch.object(sources, "read_mounts", return_value=self.mounts):
                sources.verify_report(path)
            with patch.object(sources, "read_mounts", return_value=self.mounts[:3] + self.mounts[4:]), \
                 self.assertRaisesRegex(sources.SourceError, "Mount-Inventar"):
                sources.verify_report(path)

    def test_invalid_frozen_reports_fail_closed(self):
        original = sources.verification_report(plan(mounts=self.mounts))
        malformed = []
        for key in ["selection", "frozen_excludes", "mount_identity"]:
            copy = json.loads(json.dumps(original))
            copy.pop(key)
            malformed.append(copy)
        for version in [0, 3, "2", True, 2.0]:
            malformed.append({**original, "mount_verification_version": version})
        copy = json.loads(json.dumps(original))
        copy["mount_identity"][0].pop("root")
        malformed.append(copy)
        copy = json.loads(json.dumps(original))
        copy["mount_identity"].append(copy["mount_identity"][0])
        malformed.append(copy)
        malformed.append({**original, "frozen_excludes": [None]})
        copy = json.loads(json.dumps(original))
        copy["mount_identity"][0]["stack"] = {"not": "layers"}
        malformed.append(copy)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            for report in malformed:
                path.write_text(json.dumps(report))
                with self.subTest(report=report), patch.object(sources, "read_mounts", return_value=self.mounts), \
                     self.assertRaises(sources.SourceError):
                    sources.verify_report(path)

    def test_mount_error_is_bounded_and_never_exports_sources_or_options(self):
        current = self.mounts + [self.volume("/etc/folder" + str(i), str(100 + i), "cifs") for i in range(30)]
        for item in current:
            item["source"] = "//username:password@server/share"
            item["options"] = "password=secret"
        with self.assertRaises(sources.SourceError) as caught:
            self.verify(plan(mounts=self.mounts), current)
        message = str(caught.exception)
        self.assertIn("weitere 20 Pfade", message)
        self.assertNotIn("password", message)
        self.assertNotIn("secret", message)
        self.assertLess(len(message), 3000)

    def test_verification_receipt_records_ignored_and_relevant_changes_on_failure(self):
        selected = plan(mounts=self.mounts)
        current = self.mounts[:3] + self.mounts[4:] + [self.volume("/etc", "60", "tmpfs")]
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "plan.json"
            receipt_path = Path(tmp) / "receipt.json"
            sources.write_report(report_path, sources.verification_report(selected))
            with patch.object(sources, "read_mounts", return_value=current), self.assertRaises(sources.SourceError):
                sources.verify_report(report_path, receipt_path)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "error")
            self.assertEqual(receipt["relevant_changes_count"], 1)
            self.assertEqual(receipt["ignored_changes_count"], 1)
            self.assertEqual(receipt["relevant_changes"][0]["path"], "/etc")
            self.assertEqual(receipt["ignored_changes"][0]["path"], "/media/smb/ignored")
            self.assertIsNone(receipt["relevant_changes"][0]["before"])
            self.assertEqual(receipt["relevant_changes"][0]["after"]["fstype"], "tmpfs")

    def test_verification_receipt_records_success_without_turning_ignored_churn_into_warning(self):
        selected = plan(mounts=self.mounts)
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.json"
            result = sources.verify_mounts(selected, self.mounts[:3] + self.mounts[4:], receipt_path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(json.loads(receipt_path.read_text()), result)
            with self.assertRaises(FileExistsError):
                sources.verify_mounts(selected, self.mounts, receipt_path)


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
        self.assertIn("./boot/data.txt", entries)
        self.assertIn("./media/usb/USB_Loxberry/data.txt", entries)
        for forbidden in ["./media/smb", "./nfs", "./tmp", "./media/usb/PI_Backup"]:
            self.assertFalse(any(value == forbidden or value.startswith(forbidden + "/") for value in entries))
        self.assertEqual(len(entries), len(set(entries)))

    def test_exact_list_prefixes_comment_and_option_names_without_directory_expansion(self):
        names = ("#comment-looking-file", ";comment-looking-file", "--literal-option", "name with spaces")
        for name in names:
            (self.root / name).write_bytes(b"required payload")
        (self.root / "#directory").mkdir()
        (self.root / "#directory/required").write_bytes(b"nested payload")
        entries = list(sources.enumerate_files(self.selection(), self.root))
        self.assertEqual(entries.count("."), 1)
        self.assertNotIn("./", entries)
        self.assertTrue(all(entry == "." or entry.startswith("./") for entry in entries))
        self.assertFalse(any(entry.endswith("/") for entry in entries))
        for name in (*names, "#directory", "#directory/required"):
            self.assertIn("./" + name, entries)
        self.assertNotIn("./tmp/data.txt", entries)
        self.assertNotIn("./media/usb/PI_Backup/data.txt", entries)

    def test_files_cli_emits_only_literal_prefixed_nul_records(self):
        (self.root / "#required").write_text("payload")
        (self.root / ";required").write_text("payload")
        enumerate_original = sources.enumerate_files
        info = self.root.stat()
        device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" if os.name == "posix" else "1:1"
        mounts = [{**value, "device": device, "mount_id": str(index + 1)} for index, value in enumerate(self.mounts)]
        selection = sources.SourcePlan({"policy": "local", "overrides": {}}, mounts)
        output = io.BytesIO()
        report = self.root / "frozen-report.json"
        with patch.object(sources, "read_config", return_value={}), \
             patch.object(sources, "read_mounts", return_value=mounts), \
             patch.object(sources, "SourcePlan", return_value=selection), \
             patch.object(sources, "enumerate_files", side_effect=lambda plan, omit_sockets=False: enumerate_original(plan, self.root, omit_sockets)), \
             patch.object(sources.sys, "stdout", SimpleNamespace(buffer=output)):
            result = sources.main(["files", "--config", "/fixture", "--report", str(report)])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue()[-1:], b"\0")
        entries = output.getvalue()[:-1].split(b"\0")
        self.assertIn(b"./#required", entries)
        self.assertIn(b"./;required", entries)
        self.assertEqual(entries.count(b"."), 1)
        self.assertTrue(all(entry == b"." or entry.startswith(b"./") for entry in entries))

    @unittest.skipUnless(os.name == "posix", "POSIX filename bytes required")
    def test_exact_list_preserves_newlines_and_non_utf8_filename_bytes(self):
        names = (b"line\nname", b"carriage\rname", b"tab\tname", b"nonutf8-\xff", b" space ")
        for name in names:
            descriptor = os.open(os.fsencode(self.root) + b"/" + name, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
        entries = list(sources.enumerate_files(self.selection(), self.root))
        encoded = b"".join(os.fsencode(value) + b"\0" for value in entries)
        for name in names:
            self.assertIn(b"./" + name, encoded.split(b"\0"))

    def test_runtime_payload_policy_keeps_directories_and_persistent_install_audit(self):
        runtime_dir = self.root / "opt/loxberry/log/plugins/new-plugin"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "arbitrary-runtime-name.bin").write_text("diagnostic")
        persistent = self.root / "opt/loxberry/log/system/install.log"
        persistent.parent.mkdir(parents=True)
        persistent.write_text("keep")
        selected = sources.SourcePlan({"policy": "local", "overrides": {}}, self.mounts,
                                      loxberry_home="/opt/loxberry")
        for _ in range(2):
            entries = list(sources.enumerate_files(selected, self.root))
            self.assertIn("./opt/loxberry/log/plugins/new-plugin", entries)
            self.assertNotIn("./opt/loxberry/log/plugins/new-plugin/arbitrary-runtime-name.bin", entries)
            self.assertIn("./opt/loxberry/log/system/install.log", entries)
            self.assertEqual(selected.report()["runtime_content_policy"]["omitted_regular_files"], 1)
            self.assertEqual(selected.report()["status"], "ok")

    def test_runtime_policy_handles_known_regular_file_rotation_before_source_lstat(self):
        runtime = self.root / "opt/loxberry/log/plugins/new-plugin/rotating.log"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("diagnostic")
        original = Path.lstat

        def disappeared(path):
            if path == runtime:
                raise FileNotFoundError("rotated")
            return original(path)

        selected = sources.SourcePlan({"policy": "local", "overrides": {}}, self.mounts,
                                      loxberry_home="/opt/loxberry")
        with patch.object(Path, "lstat", disappeared):
            entries = list(sources.enumerate_files(selected, self.root))
        self.assertNotIn("./opt/loxberry/log/plugins/new-plugin/rotating.log", entries)
        self.assertEqual(selected.report()["runtime_content_policy"]["omitted_regular_files"], 1)
        required = sources.SourcePlan({"policy": "local", "overrides": {}}, self.mounts,
                                     loxberry_home="/opt/loxberry", include_runtime_logs=True)
        with patch.object(Path, "lstat", disappeared), self.assertRaisesRegex(sources.SourceError, "rotating.log"):
            list(sources.enumerate_files(required, self.root))

    def test_runtime_policy_never_suppresses_missing_config_or_database(self):
        original = Path.lstat
        target = self.root / "etc/data.txt"

        def disappeared(path):
            if path == target:
                raise FileNotFoundError("required data disappeared")
            return original(path)

        selected = sources.SourcePlan({"policy": "local", "overrides": {}}, self.mounts,
                                      loxberry_home="/opt/loxberry")
        with patch.object(Path, "lstat", disappeared), self.assertRaisesRegex(sources.SourceError, "/etc/data.txt"):
            list(sources.enumerate_files(selected, self.root))

    def test_runtime_policy_is_opt_in_for_legacy_python_callers(self):
        runtime = self.root / "opt/loxberry/log/plugins/plugin/runtime.log"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("diagnostic")
        selected = self.selection()
        self.assertIn("./opt/loxberry/log/plugins/plugin/runtime.log", list(sources.enumerate_files(selected, self.root)))
        self.assertNotIn("runtime_content_policy", selected.report())

    def test_socket_omission_is_opt_in_lstat_only_and_keeps_other_special_types(self):
        directory = self.root / "var/lib/fixture"
        directory.mkdir(parents=True)
        kinds = {"runtime.sock": sources.stat.S_IFSOCK, "fifo": sources.stat.S_IFIFO,
                 "character": sources.stat.S_IFCHR, "block": sources.stat.S_IFBLK,
                 "socket-link": sources.stat.S_IFLNK, "regular.sock": sources.stat.S_IFREG}
        for name in kinds:
            (directory / name).write_bytes(b"fixture")
        original = Path.lstat

        def typed(path):
            value = original(path)
            if path.parent == directory and path.name in kinds:
                items = list(value)
                items[0] = kinds[path.name] | (value.st_mode & 0o777)
                return os.stat_result(items)
            return value

        selection = self.selection()
        with patch.object(Path, "lstat", typed):
            original_entries = list(sources.enumerate_files(selection, self.root))
            self.assertNotIn("omitted_runtime_sockets", selection.report())
            filtered = list(sources.enumerate_files(selection, self.root, omit_sockets=True))
        self.assertEqual(set(original_entries) - set(filtered), {"./var/lib/fixture/runtime.sock"})
        for name in kinds.keys() - {"runtime.sock"}:
            self.assertIn("./var/lib/fixture/" + name, filtered)
        omitted = selection.report()["omitted_runtime_sockets"]
        self.assertEqual(omitted["count"], 1)
        self.assertEqual(omitted["paths"], ["/var/lib/fixture/runtime.sock"])
        self.assertIn("Kommunikationsendpunkte", omitted["reason"])
        self.assertEqual(selection.report()["status"], "ok")
        self.assertTrue(any("1 laufzeitgebundene Unix-Sockets" in note for note in selection.report()["notices"]))

    def test_socket_report_bounds_paths_without_losing_total_and_resets_per_enumeration(self):
        directory = self.root / "var/lib/fixture"
        directory.mkdir(parents=True)
        for index in range(27):
            (directory / f"socket-{index:02}").touch()
        original = Path.lstat

        def typed(path):
            value = original(path)
            if path.parent == directory:
                items = list(value)
                items[0] = sources.stat.S_IFSOCK | 0o600
                return os.stat_result(items)
            return value

        selection = self.selection()
        with patch.object(Path, "lstat", typed):
            for _ in range(2):
                list(sources.enumerate_files(selection, self.root, omit_sockets=True))
                report = selection.report()["omitted_runtime_sockets"]
                self.assertEqual(report["count"], 27)
                self.assertEqual(report["paths"], [f"/var/lib/fixture/socket-{index:02}" for index in range(20)])
            list(sources.enumerate_files(selection, self.root))
            self.assertNotIn("omitted_runtime_sockets", selection.report())

    def test_socket_omission_still_fails_on_unreadable_lstat_and_directory(self):
        original_lstat = Path.lstat
        original_scandir = os.scandir

        def denied_stat(path):
            if path == self.root / "etc/data.txt":
                raise PermissionError("not a confirmed socket")
            return original_lstat(path)

        def denied_directory(path):
            if Path(path) == self.root / "etc":
                raise PermissionError("cannot enumerate directory")
            return original_scandir(path)

        with patch.object(Path, "lstat", denied_stat), self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(self.selection(), self.root, omit_sockets=True))
        with patch.object(sources.os, "scandir", side_effect=denied_directory), self.assertRaises(sources.SourceError):
            list(sources.enumerate_files(self.selection(), self.root, omit_sockets=True))

    def test_files_cli_records_socket_omission_with_mount_identity(self):
        report_path = self.root / "selection-report.json"
        root_info = self.root.stat()
        device = f"{os.major(root_info.st_dev)}:{os.minor(root_info.st_dev)}" if os.name == "posix" else "1:1"
        mounts = [{**mount("/"), "device": device, "mount_id": "1"}]
        original_enumerate = sources.enumerate_files
        seen = []

        def fixture_enumerate(selection, omit_sockets=False):
            seen.append(omit_sockets)
            yield from original_enumerate(selection, self.root, omit_sockets=omit_sockets)

        output = io.BytesIO()
        with patch.object(sources, "read_config", return_value={"source_selection": {"policy": "local", "overrides": {}}}), \
             patch.object(sources, "read_mounts", return_value=mounts), \
             patch.object(sources, "enumerate_files", side_effect=fixture_enumerate), \
             patch.object(sources.sys, "stdout", io.TextIOWrapper(output, encoding="utf-8")):
            result = sources.main(["files", "--config", "/fixture/config", "--report", str(report_path), "--omit-sockets"])
        self.assertEqual(result, 0)
        self.assertEqual(seen, [True])
        report = json.loads(report_path.read_text())
        self.assertEqual(report["omitted_runtime_sockets"]["count"], 0)
        self.assertEqual(report["omitted_runtime_sockets"]["paths"], [])
        self.assertEqual(report["mount_identity"], sources.mount_identity(mounts))

    def test_socket_omission_does_not_bypass_mount_identity_checks(self):
        selection = self.selection()
        original = Path.lstat
        target = self.root / "etc/data.txt"

        def changed_socket(path):
            value = original(path)
            if path == target:
                items = list(value)
                items[0] = sources.stat.S_IFSOCK | 0o600
                items[2] = 999
                return os.stat_result(items)
            return value

        # Exercise the Linux mount check on every platform, using synthetic
        # device values on lstat records, without touching real mounts.
        selection.mounts["/"]["device"] = "8:1"
        with patch.object(Path, "lstat", changed_socket), \
             patch.object(sources, "os", SimpleNamespace(name="posix", scandir=os.scandir,
                                                         major=lambda value: 9 if value == 999 else 8,
                                                         minor=lambda value: 1)), \
             self.assertRaisesRegex(sources.SourceError, "Mount-Zuordnung"):
            list(sources.enumerate_files(selection, self.root, omit_sockets=True))
        self.assertEqual(selection.report()["omitted_runtime_sockets"]["count"], 0)

    @unittest.skipUnless(os.name == "posix", "Real Linux Unix sockets, FIFO and symlink required")
    def test_real_runtime_socket_is_omitted_but_fifo_and_link_to_socket_remain(self):
        directory = self.root / "var/lib/fixture"
        directory.mkdir(parents=True)
        path = directory / "runtime.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
            endpoint.bind(str(path))
            os.mkfifo(directory / "fifo")
            (directory / "socket-link").symlink_to("runtime.sock")
            selection = self.selection()
            self.assertIn("./var/lib/fixture/runtime.sock", list(sources.enumerate_files(selection, self.root)))
            entries = list(sources.enumerate_files(selection, self.root, omit_sockets=True))
        self.assertNotIn("./var/lib/fixture/runtime.sock", entries)
        self.assertIn("./var/lib/fixture/fifo", entries)
        self.assertIn("./var/lib/fixture/socket-link", entries)
        self.assertEqual(selection.report()["omitted_runtime_sockets"]["paths"], ["/var/lib/fixture/runtime.sock"])

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
        self.assertIn("./media/smb/nas/data.txt", entries)
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
        self.assertFalse(any(path.startswith("./shares/") for path in default_entries))
        self.assertEqual([path for path in selected_entries if path.startswith("./shares/")], ["./shares/4", "./shares/4/payload.bin"])

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

    def test_existing_regular_file_bind_is_not_hidden_by_directory_only_exclude(self):
        mounts = self.mounts + [mount("/etc/data.txt")]
        selected = plan(mounts=mounts, excludes=["/etc/data.txt/"])
        original = Path.lstat

        def guarded(path):
            if path == self.root / "media/smb":
                raise AssertionError("Default-denied automount must remain untouched")
            return original(path)

        with patch.object(Path, "lstat", guarded):
            entries = list(sources.enumerate_files(selected, self.root))
        self.assertIn("./etc/data.txt", entries)
        self.assertTrue(selected.included("/etc/data.txt"))
        self.assertNotIn("/etc/data.txt", selected.confirmed_directory_excludes)

    def test_actual_directory_mount_exclude_is_confirmed_without_listing_and_frozen(self):
        target = "/media/usb/USB_Loxberry"
        device = (f"{os.major(self.root.stat().st_dev)}:{os.minor(self.root.stat().st_dev)}"
                  if os.name == "posix" else "8:1")
        mounts = [{**item, "device": device, "mount_id": str(index + 1), "root": "/"}
                  for index, item in enumerate(self.mounts + [mount("/media/usb", "autofs")])]
        selected = plan(mounts=mounts, excludes=[target + "/", "/media/usb/PI_Backup"])
        self.assertTrue(selected.selected_descendants("/media/usb"))
        original = os.scandir

        def guarded(path):
            if Path(path) == self.root / target.lstrip("/"):
                raise AssertionError("An excluded directory must not be enumerated")
            return original(path)

        with patch.object(sources.os, "scandir", side_effect=guarded):
            entries = list(sources.enumerate_files(selected, self.root))
        self.assertFalse(any(entry.startswith("." + target) for entry in entries))
        self.assertIn(target, selected.confirmed_directory_excludes)
        self.assertFalse(selected.included(target))
        self.assertFalse(selected.selected_descendants("/media/usb"))
        current = [item for item in mounts if item["path"] not in (target, "/media/usb")]
        sources.verify_mounts(selected, current)
        report = sources.verification_report(selected)
        self.assertIn(target, report["frozen_excludes"])
        volume = next(item for item in report["volumes"] if item["path"] == target)
        self.assertFalse(volume["included"])
        self.assertTrue(volume["forced_excluded"])
        report_path = self.root / "directory-exclude-report.json"
        sources.write_report(report_path, report)
        with patch.object(sources, "read_mounts", return_value=current):
            sources.verify_report(report_path)

    def test_type_independent_excluded_file_is_not_statted_during_rotation(self):
        original = Path.lstat

        def vanished(path):
            if path == self.root / "etc/data.txt":
                raise FileNotFoundError("excluded rotating file")
            return original(path)

        selected = plan(mounts=self.mounts, excludes=["/etc/data.txt"])
        with patch.object(Path, "lstat", vanished):
            entries = list(sources.enumerate_files(selected, self.root))
        self.assertNotIn("./etc/data.txt", entries)

    def test_known_local_usb_under_autofs_is_routed_without_listing_namespace(self):
        self.mounts.append(mount("/media/usb", "autofs"))
        original = os.scandir

        def guarded(path):
            if Path(path) == self.root / "media/usb":
                raise AssertionError("Autofs namespace must not be scanned")
            return original(path)

        with patch.object(sources.os, "scandir", side_effect=guarded):
            entries = list(sources.enumerate_files(self.selection(), self.root))
        self.assertIn("./media/usb/USB_Loxberry/data.txt", entries)
        self.assertNotIn("./media/usb/PI_Backup", entries)

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
        self.assertIn("./etc/link", entries)
        self.assertFalse(any(value.startswith("./etc/link/") for value in entries))

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
        # Frozen membership, not a later recursive rescan: newly created root
        # files and selected-directory siblings must remain outside this copy.
        (self.root / "late-root-file").write_text("not in frozen selection")
        (self.root / "etc/late-sibling").write_text("not in frozen selection")
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
            self.assertFalse((destination / "late-root-file").exists())
            self.assertFalse((destination / "etc/late-sibling").exists())
            archive = output / "rootfs.tar"
            subprocess.run(["tar", "--no-recursion", "--null", "-C", str(self.root), "-cpf", str(archive), "--files-from=" + str(file_list)], check=True, capture_output=True)
            with tarfile.open(archive) as handle:
                names = handle.getnames()
                self.assertEqual(len(names), len(set(names)))
                self.assertIn("./media/smb/nas/data.txt", names)
                self.assertNotIn("./media/smb/other", names)
                self.assertNotIn("./late-root-file", names)
                self.assertNotIn("./etc/late-sibling", names)
                self.assertTrue(handle.getmember("./etc/hardlink").islnk())
                self.assertTrue(handle.getmember("./etc/symlink").issym())
                self.assertTrue(handle.getmember("./etc/fifo").isfifo())


if __name__ == "__main__":
    unittest.main()
