#!/usr/bin/env python3
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTINSTALL = (ROOT / "postinstall.sh").read_text(encoding="utf-8")
PREROOT = (ROOT / "preroot.sh").read_text(encoding="utf-8")
POSTROOT = (ROOT / "postroot.sh").read_text(encoding="utf-8")
BACKEND = (ROOT / "bin" / "hostbackup.sh").read_text(encoding="utf-8")
PLUGIN_CFG = (ROOT / "plugin.cfg").read_text(encoding="utf-8")
PRERELEASE_CFG = (ROOT / "prerelease.cfg").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
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

    def test_packages_exclude_generated_python_caches(self) -> None:
        for marker in ("__pycache__", "*.pyc", "*.pyo"):
            self.assertIn(marker, PACKAGE_SH)
        self.assertIn("__pycache__", PACKAGE_PS1)
        self.assertIn("'.pyc', '.pyo'", PACKAGE_PS1)

    def test_root_hooks_preserve_existing_configuration(self) -> None:
        self.assertIn("CONFIG_BACKUP", PREROOT)
        self.assertIn("cp --no-dereference", PREROOT)
        self.assertIn('chown loxberry:loxberry "$CONFIG_DIR"', PREROOT)
        self.assertIn('install -o root -g root -m 0600 "$CONFIG_BACKUP" "$CONFIG"', POSTROOT)
        self.assertIn('rmdir -- "$UPGRADE_DIR"', POSTROOT)
        self.assertLess(
            POSTROOT.index('install -o root -g root -m 0600 "$CONFIG_BACKUP" "$CONFIG"'),
            POSTROOT.index('for required_file in'),
        )

    def test_reboot_safe_logs_use_persistent_root_state(self) -> None:
        self.assertIn('TASK_LOG_DIR="$ROOT_STATE_DIR/logs"', BACKEND)
        self.assertIn('TASK_LOG_DIR="$ROOT_STATE_DIR/logs"', POSTROOT)
        self.assertIn('"$TASK_LOG_DIR"/*', BACKEND)
        self.assertIn('log_file="$TASK_LOG_DIR/', BACKEND)
        self.assertNotIn('for secure_dir in "$LBP_LOGDIR"', BACKEND)
        self.assertIn('chown loxberry:loxberry "$LOG_DIR"', POSTROOT)
        self.assertIn(
            'chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR"',
            POSTROOT,
        )

    def test_prerelease_version_and_download_are_consistent(self) -> None:
        self.assertIn("VERSION=0.6.1", PLUGIN_CFG)
        self.assertIn("VERSION=0.6.1", PRERELEASE_CFG)
        self.assertIn("v0.6.1-beta/LoxBerryHostBackup_0.6.1.zip", PRERELEASE_CFG)
        self.assertIn("Vorabversion 0.6.1-beta", README)
        self.assertIn("## [0.6.1-beta]", CHANGELOG)
        self.assertIn("prerelease: ${{ contains(github.ref_name, '-') }}", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
