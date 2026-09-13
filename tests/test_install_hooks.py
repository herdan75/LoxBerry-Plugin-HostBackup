#!/usr/bin/env python3
import pathlib
import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
            '"$LAUNCHER_TARGET" install-schedule',
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
        plugin = configparser.ConfigParser()
        channel = configparser.ConfigParser()
        plugin.read_string(PLUGIN_CFG)
        channel.read_string(PRERELEASE_CFG)
        version = plugin["PLUGIN"]["VERSION"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        tag = f"v{version}-beta"
        base = "https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases"
        archive_url = f"{base}/download/{tag}/LoxBerryHostBackup_{version}.zip"
        self.assertEqual(channel["AUTOUPDATE"]["VERSION"], version)
        self.assertEqual(channel["AUTOUPDATE"]["ARCHIVEURL"], archive_url)
        self.assertEqual(channel["AUTOUPDATE"]["INFOURL"], f"{base}/tag/{tag}")
        self.assertIn(archive_url, README)
        self.assertIn(f"## [{version}-beta]", CHANGELOG)
        self.assertIn("prerelease: ${{ contains(github.ref_name, '-') }}", WORKFLOW)

    def test_trusted_install_and_webuser_permissions(self) -> None:
        self.run_linux_install_child("--trusted-install-child")

    def test_real_backend_install_with_loxberry_cron_symlink(self) -> None:
        self.run_linux_install_child("--cron-install-child")

    def run_linux_install_child(self, child_mode: str) -> None:
        required = os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1"
        if sys.platform != "linux":
            if required:
                self.fail("Mandatory root/web-user integration requires Linux")
            self.skipTest("Linux root/web-user integration requires Linux")
        prefix = []
        if os.geteuid() != 0:
            if not shutil.which("sudo") or subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, check=False
            ).returncode:
                if required:
                    self.fail("Mandatory root/web-user integration requires passwordless sudo")
                self.skipTest("Linux root/web-user integration requires passwordless sudo")
            prefix = ["sudo", "-n"]
        result = subprocess.run(
            [*prefix, sys.executable, str(pathlib.Path(__file__).resolve()), child_mode],
            text=True, capture_output=True, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def trusted_install_integration():
    """Execute the actual installer/launcher, confined to one temporary tree.

    /var/lib is used because /tmp is world-writable and must correctly fail the
    production ancestor trust check. No actual cron or system launcher is changed.
    """
    import pwd

    assert os.geteuid() == 0
    with tempfile.TemporaryDirectory(prefix="hostbackup-install-test-", dir="/var/lib") as temporary:
        sandbox = pathlib.Path(temporary)
        sandbox.chmod(0o755)
        trusted = sandbox / "libexec/loxberryhostbackup"
        launcher = sandbox / "sbin/loxberryhostbackup"
        dispatcher = sandbox / "sbin/loxberryhostbackup-sudo"
        recovery = sandbox / "cron.d/loxberryhostbackup-recovery"
        home = sandbox / "lbh"
        bindir = home / "bin/plugins/loxberryhostbackup"
        config = home / "config/plugins/loxberryhostbackup/config.json"
        cgi = home / "webfrontend/htmlauth/plugins/loxberryhostbackup/index.cgi"
        bindir.mkdir(parents=True)
        config.parent.mkdir(parents=True)
        cgi.parent.mkdir(parents=True)
        cgi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        config.write_text('{"keep_backups":3}', encoding="utf-8")
        (sandbox / "upgrade").mkdir()

        def rewrite(text):
            return (text.replace("/usr/libexec/loxberryhostbackup", str(trusted))
                    .replace("/usr/local/sbin/loxberryhostbackup", str(launcher))
                    .replace("/etc/cron.d/loxberryhostbackup-recovery", str(recovery))
                    .replace("/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade",
                             str(sandbox / "upgrade/${INSTALL_ID}_loxberryhostbackup_upgrade"))
                    .replace("loxberry:loxberry", "nobody:nogroup"))

        def install_sources(label):
            for source in (ROOT / "bin").iterdir():
                if source.suffix in (".sh", ".py", ".php"):
                    (bindir / source.name).write_text(rewrite(source.read_text(encoding="utf-8")), encoding="utf-8")
                    (bindir / source.name).chmod(0o755)
            # Calls run a harmless stub, never service control or a real backup.
            (bindir / "hostbackup.sh").write_text(
                "#!/bin/bash\nset -eu\nprintf '%s\\n' '" + label + "' \"$@\"\n"
                "if [ \"${1:-}\" = cache-test ]; then\n"
                "python3 -c 'import importlib.util, os; spec=importlib.util.spec_from_file_location(\"validator\", os.environ[\"LBPBINDIR\"]+\"/validate-import-archive.py\"); spec.loader.exec_module(importlib.util.module_from_spec(spec))'\n"
                "fi\n", encoding="utf-8"
            )
            (bindir / "hostbackup.sh").chmod(0o755)
            (bindir / "runtime-version").write_text("0.6.1\n", encoding="utf-8")

        postroot = sandbox / "postroot.sh"
        preroot = sandbox / "preroot.sh"
        postroot.write_text(rewrite(POSTROOT), encoding="utf-8")
        preroot.write_text(rewrite(PREROOT), encoding="utf-8")

        def run(script, *args, success=True):
            result = subprocess.run(["bash", str(script), *args], text=True,
                                    capture_output=True, check=False, timeout=15)
            if success:
                assert result.returncode == 0, result.stdout + result.stderr
            return result

        install_sources("first")
        install_args = ["fixture1", "", "loxberryhostbackup", "", str(home)]
        run(postroot, *install_args)
        first_release = (trusted / "current").resolve()
        assert first_release.is_relative_to(trusted / "releases")
        assert "first\nconfig\n" == run(dispatcher, "config").stdout
        run(launcher, "cache-test")
        assert not (first_release / "__pycache__").exists()
        assert "first\nconfig\n" == run(dispatcher, "config").stdout
        assert (first_release / "runtime-version").read_text().strip() == "0.6.1"
        assert "@reboot root " + str(launcher) + " recover-services\n" in recovery.read_text()
        assert "*/5 * * * * root " + str(launcher) + " recover-services\n" in recovery.read_text()
        assert "23 * * * * root " + str(launcher) + " integrity-schedule\n" in recovery.read_text()
        assert (recovery.stat().st_mode & 0o777) == 0o644
        helper = first_release / "validate-import-archive.py"
        assert helper.stat().st_uid == 0
        nobody = pwd.getpwnam("nobody")
        # Attempt actual writes, unlink/replacement and symlink creation as the
        # unprivileged web identity. Every attempt must fail with PermissionError.
        attacks = """
import os, pathlib, sys
p=pathlib.Path(sys.argv[1])
for action in (lambda: p.write_text('injected'), lambda: p.unlink(),
               lambda: (p.parent/'replacement.py').symlink_to('/etc/passwd')):
    try: action()
    except PermissionError: continue
    raise SystemExit('web user modified trusted tree')
"""
        attack = subprocess.run([sys.executable, "-c", attacks, str(helper)],
                                user=nobody.pw_uid, group=nobody.pw_gid, extra_groups=[],
                                capture_output=True, text=True, check=False)
        assert attack.returncode == 0, attack.stdout + attack.stderr
        for unsafe_mode in (0o775, 0o2775, 0o777):
            helper.chmod(unsafe_mode)
            assert run(dispatcher, "config", success=False).returncode != 0
        helper.chmod(0o755)
        first_release.chmod(0o775)
        assert run(dispatcher, "config", success=False).returncode != 0
        first_release.chmod(0o755)
        helper.rename(first_release / "validator.saved")
        helper.symlink_to(first_release / "validator.saved")
        assert run(dispatcher, "config", success=False).returncode != 0
        helper.unlink()
        (first_release / "validator.saved").rename(helper)
        # Upgrade restores saved settings and replaces the pointer atomically;
        # old running backends retain their complete helper directory.
        second_args = ["fixture2", "", "loxberryhostbackup", "", str(home)]
        run(preroot, *second_args)
        config.write_text('{"keep_backups":10}', encoding="utf-8")
        install_sources("second")
        run(postroot, *second_args)
        assert config.read_text() == '{"keep_backups":3}'
        assert first_release.is_dir()
        assert first_release != (trusted / "current").resolve()
        assert "first\nconfig\n" == run(first_release / "hostbackup.sh", "config").stdout
        assert "second\nconfig\n" == run(dispatcher, "config").stdout
        assert run(dispatcher, "restore", "anything", success=False).returncode != 0
        assert run(dispatcher, "config", "extra", success=False).returncode != 0


def cron_install_integration():
    """Install the real backend with native and LoxBerry-managed cron layouts.

    All system paths are redirected below a private /var/lib test directory.
    No service, real cron configuration, backup or host settings are changed.
    """
    import pwd

    assert os.geteuid() == 0
    nobody = pwd.getpwnam("nobody")
    for layout, cron_mode in (
        ("regular", 0o755),
        ("loxberry-link", 0o755),
        ("loxberry-link", 0o775),
        ("loxberry-link", 0o2755),
        ("loxberry-link", 0o2775),
    ):
        with tempfile.TemporaryDirectory(prefix="hostbackup-cron-test-", dir="/var/lib") as temporary:
            sandbox = pathlib.Path(temporary)
            sandbox.chmod(0o755)
            home = sandbox / "lbh"
            trusted = sandbox / "libexec/loxberryhostbackup"
            launcher = sandbox / "sbin/loxberryhostbackup"
            cron = sandbox / "etc/cron.d"
            cron.parent.mkdir()
            cron.parent.chmod(0o755)
            managed = home / "system/cron/cron.d"
            managed.mkdir(parents=True)
            # LoxBerry resetpermissions.sh owns cron.d as root, but only chmods
            # its files, not the directory. The reported LoxBerry 4 installation
            # has root:root 0775 here; its parents still belong to loxberry.
            for parent in (home, home / "system", managed.parent):
                parent.chmod(0o755)
                os.chown(parent, nobody.pw_uid, nobody.pw_gid)
            managed.chmod(cron_mode)
            if layout == "loxberry-link":
                cron.symlink_to(managed, target_is_directory=True)
            else:
                cron.mkdir(mode=0o755)
            bindir = home / "bin/plugins/loxberryhostbackup"
            bindir.mkdir(parents=True)
            config = home / "config/plugins/loxberryhostbackup/config.json"
            config.parent.mkdir(parents=True)
            saved = {
                "backup_root": "/media/usb/PI_Backup/loxberry-hostbackup",
                "metadata_mode": "network-compatible", "keep_backups": 3,
                "schedule_enabled": True, "schedule_mode": "daily",
                "schedule_time": "03:17", "rsync_extra_excludes": ["/media/usb/PI_Backup"],
            }
            config.write_text(json.dumps(saved), encoding="utf-8")
            cgi = home / "webfrontend/htmlauth/plugins/loxberryhostbackup/index.cgi"
            cgi.parent.mkdir(parents=True)
            cgi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            def rewrite(text):
                return (text.replace("/usr/libexec/loxberryhostbackup", str(trusted))
                        .replace("/usr/local/sbin/loxberryhostbackup", str(launcher))
                        .replace("/etc/cron.d", str(cron))
                        .replace("/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade",
                                 str(sandbox / "upgrade/${INSTALL_ID}_loxberryhostbackup_upgrade"))
                        .replace("loxberry:loxberry", "nobody:nogroup"))

            def install_sources():
                for source in (ROOT / "bin").iterdir():
                    if source.suffix in (".sh", ".py", ".php"):
                        target = bindir / source.name
                        target.write_text(rewrite(source.read_text(encoding="utf-8")), encoding="utf-8")
                        target.chmod(0o755)
                (bindir / "runtime-version").write_text("0.7.0\n", encoding="utf-8")

            postroot = sandbox / "postroot.sh"
            postroot.write_text(rewrite(POSTROOT), encoding="utf-8")
            install_sources()

            def run_install(expected_success=True):
                result = subprocess.run(
                    ["bash", str(postroot), "fixture-cron", "", "loxberryhostbackup", "", str(home)],
                    text=True, capture_output=True, check=False, timeout=15,
                )
                if expected_success:
                    assert result.returncode == 0, result.stdout + result.stderr
                else:
                    assert result.returncode != 0, "Unsafe cron layout was accepted"
                return result

            if layout == "loxberry-link" and cron_mode == 0o755:
                # Reproduce the first POSTROOT failure: even a safe platform
                # symlink was rejected by the original executable-path policy.
                legacy_text = rewrite(POSTROOT).replace(
                    "\nprepare_recovery_cron_directory\n",
                    '\nensure_root_path "${RECOVERY_CRON%/*}"\n',
                )
                assert legacy_text != rewrite(POSTROOT)
                legacy = sandbox / "postroot-previous-cron-policy.sh"
                legacy.write_text(legacy_text, encoding="utf-8")
                result = subprocess.run(
                    ["bash", str(legacy), "fixture-cron", "", "loxberryhostbackup", "", str(home)],
                    text=True, capture_output=True, check=False, timeout=15,
                )
                assert result.returncode != 0
                assert "Unsafe trusted directory: " + str(cron) in result.stderr
                assert json.loads(config.read_text()) == saved
            if layout == "loxberry-link" and cron_mode == 0o775:
                # Reproduce the SECOND real installation failure independently:
                # accepting the symlink still rejected root:root mode 0775.
                old_guard = '''    [ "$(stat -c '%u' "$resolved_dir")" = 0 ] && (( (8#$mode & 022) == 0 )) || {
      echo "LoxBerry system cron directory must be root-owned and not writable by others: $resolved_dir" >&2
      exit 1
    }
'''
                previous_text = rewrite(POSTROOT)
                start_marker = '    mode="$(stat -c \'%a\' "$resolved_dir")"\n'
                start = previous_text.index(start_marker) + len(start_marker)
                end = previous_text.index('    cron_dir="$resolved_dir"', start)
                previous_text = previous_text[:start] + old_guard + previous_text[end:]
                previous = sandbox / "postroot-previous-cron-mode-policy.sh"
                previous.write_text(previous_text, encoding="utf-8")
                result = subprocess.run(
                    ["bash", str(previous), "fixture-cron", "", "loxberryhostbackup", "", str(home)],
                    text=True, capture_output=True, check=False, timeout=15,
                )
                assert result.returncode != 0
                assert "LoxBerry system cron directory must be root-owned and not writable by others: " + str(managed) in result.stderr
                assert json.loads(config.read_text()) == saved
            run_install()
            assert json.loads(config.read_text()) == saved
            assert "17 3 * * * root " in (cron / "loxberryhostbackup").read_text()
            recovery = cron / "loxberryhostbackup-recovery"
            assert "@reboot root " + str(launcher) + " recover-services\n" in recovery.read_text()
            assert "*/5 * * * * root " + str(launcher) + " recover-services\n" in recovery.read_text()
            assert "23 * * * * root " + str(launcher) + " integrity-schedule\n" in recovery.read_text()
            def assert_cron_permissions():
                for entry in (cron / "loxberryhostbackup", recovery):
                    assert not entry.is_symlink()
                    assert entry.stat().st_uid == 0
                    assert entry.stat().st_gid == 0
                    assert entry.stat().st_mode & 0o7777 == 0o644
                assert cron.stat().st_uid == 0
                assert cron.stat().st_gid == 0
                assert cron.stat().st_mode & 0o7777 == cron_mode
                if layout == "loxberry-link":
                    assert cron.is_symlink() and cron.resolve() == managed
                    assert cron.lstat().st_uid == 0
                    assert cron.lstat().st_gid == 0
            assert_cron_permissions()
            result = subprocess.run(["bash", str(launcher), "config"], text=True,
                                    capture_output=True, check=False, timeout=15)
            assert result.returncode == 0, result.stdout + result.stderr
            loaded = json.loads(result.stdout)
            for key, value in saved.items():
                assert loaded[key] == value, (key, loaded[key], value)
            for parent in (home, home / "system", managed.parent):
                assert parent.stat().st_uid == nobody.pw_uid
                assert parent.stat().st_mode & 0o777 == 0o755
            if layout == "loxberry-link":
                assert cron.is_symlink() and cron.resolve() == managed
                # Reinstall the same package version after an interrupted update.
                # A fresh source backend must replace the installed forwarding shim.
                install_sources()
                run_install()
                assert json.loads(config.read_text()) == saved
                assert_cron_permissions()
                assert "17 3 * * * root " in (cron / "loxberryhostbackup").read_text()
            if layout == "loxberry-link" and cron_mode == 0o2775:
                good_pointer = (trusted / "current").resolve()
                for unsafe in (
                    "wrong-target", "dangling", "link-owner", "target-owner",
                    "target-group", "target-mode",
                ):
                    cron.unlink()
                    target = managed
                    if unsafe == "wrong-target":
                        target = sandbox / "other-cron"
                        target.mkdir()
                    elif unsafe == "dangling":
                        target = sandbox / "missing-cron"
                    cron.symlink_to(target, target_is_directory=True)
                    if unsafe == "link-owner":
                        os.lchown(cron, nobody.pw_uid, nobody.pw_gid)
                    elif unsafe == "target-owner":
                        os.chown(managed, nobody.pw_uid, nobody.pw_gid)
                    elif unsafe == "target-group":
                        os.chown(managed, 0, nobody.pw_gid)
                        managed.chmod(0o775)
                    elif unsafe == "target-mode":
                        managed.chmod(0o777)
                    install_sources()
                    run_install(expected_success=False)
                    assert (trusted / "current").resolve() == good_pointer
                    assert json.loads(config.read_text()) == saved
                    if target != managed and target.exists():
                        assert not list(target.iterdir())
                    os.chown(managed, 0, 0)
                    managed.chmod(cron_mode)


if __name__ == "__main__":
    if sys.argv[1:] == ["--trusted-install-child"]:
        trusted_install_integration()
    elif sys.argv[1:] == ["--cron-install-child"]:
        cron_install_integration()
    else:
        unittest.main()
