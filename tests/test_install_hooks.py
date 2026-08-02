#!/usr/bin/env python3
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTINSTALL = (ROOT / "postinstall.sh").read_text(encoding="utf-8")
PREROOT = (ROOT / "preroot.sh").read_text(encoding="utf-8")
POSTROOT = (ROOT / "postroot.sh").read_text(encoding="utf-8")
PACKAGE_SH = (ROOT / "package.sh").read_text(encoding="utf-8")
PACKAGE_PS1 = (ROOT / "package.ps1").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "build-plugin.yml").read_text(
    encoding="utf-8"
)


class InstallHookTests(unittest.TestCase):
    def test_postinstall_contains_no_root_only_operations(self) -> None:
        for forbidden in (
            "/var/lib/",
            "/usr/local/sbin/",
            "chown root:root",
            "install-schedule",
        ):
            self.assertNotIn(forbidden, POSTINSTALL)

    def test_postroot_owns_privileged_setup(self) -> None:
        for required in (
            '[ "$(id -u)" -eq 0 ]',
            'ROOT_STATE_DIR="/var/lib/$PLUGIN_FOLDER"',
            'DISPATCHER_TARGET="/usr/local/sbin/loxberryhostbackup-sudo"',
            "chown root:root",
            '"$BACKEND" install-schedule',
        ):
            self.assertIn(required, POSTROOT)

    def test_postroot_is_packaged_and_linted(self) -> None:
        self.assertIn("preroot.sh", PACKAGE_SH)
        self.assertIn("postroot.sh", PACKAGE_SH)
        self.assertIn('"preroot.sh"', PACKAGE_PS1)
        self.assertIn('"postroot.sh"', PACKAGE_PS1)
        self.assertIn("preroot.sh", WORKFLOW)
        self.assertIn("postroot.sh", WORKFLOW)

    def test_root_hooks_preserve_existing_configuration(self) -> None:
        self.assertIn("CONFIG_BACKUP", PREROOT)
        self.assertIn("cp --no-dereference", PREROOT)
        self.assertIn('install -o root -g root -m 0600 "$CONFIG_BACKUP" "$CONFIG"', POSTROOT)
        self.assertIn('rmdir -- "$UPGRADE_DIR"', POSTROOT)


if __name__ == "__main__":
    unittest.main()
