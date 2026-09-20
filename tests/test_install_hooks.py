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
UNINSTALL = (ROOT / "uninstall" / "uninstall.sh").read_text(encoding="utf-8")
BACKEND = (ROOT / "bin" / "hostbackup.sh").read_text(encoding="utf-8")
PLUGIN_CFG = (ROOT / "plugin.cfg").read_text(encoding="utf-8")
PRERELEASE_CFG = (ROOT / "prerelease.cfg").read_text(encoding="utf-8")
RELEASE_CFG = (ROOT / "release.cfg").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
PACKAGE_SH = (ROOT / "package.sh").read_text(encoding="utf-8")
PACKAGE_PS1 = (ROOT / "package.ps1").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "build-plugin.yml").read_text(
    encoding="utf-8"
)
LAUNCHER = (ROOT / "bin" / "hostbackup-launcher.sh").read_text(encoding="utf-8")


def installer_fixture_source(text, sandbox):
    """Redirect every installer-helper system path into a private fixture."""
    return (text.replace("/var/lib/loxberryhostbackup-install-recovery", str(sandbox / "durable-recovery"))
            .replace("/var/lock/{folder}.operation.lock", str(sandbox / "operation.lock"))
            .replace('/var/lock/${PLUGIN_FOLDER}.operation.lock', str(sandbox / "operation.lock"))
            .replace('PLATFORM_USER = "loxberry"', 'PLATFORM_USER = "nobody"')
            .replace("PLATFORM_USER = 'loxberry'", "PLATFORM_USER = 'nobody'"))


def stage_installer_helper(package_root, sandbox, rewrite):
    source = ROOT / "bin" / "hostbackup-install-safety.py"
    target = package_root / "bin" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(installer_fixture_source(rewrite(source.read_text(encoding="utf-8")), sandbox), encoding="utf-8")
    target.chmod(0o755)


class InstallHookTests(unittest.TestCase):
    def test_fatal_hook_exit_mapping_preserves_other_statuses(self) -> None:
        bash = shutil.which("bash")
        if os.name == "nt":
            git_bash = pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
            if git_bash.is_file():
                bash = str(git_bash)
        if not bash:
            self.skipTest("bash is required for hook exit-status tests")
        for name, source in (("preroot", PREROOT), ("uninstall", UNINSTALL)):
            # Execute only the trap, never the actual privileged installer body.
            prefix, body = source.split('[ "$(id -u)"', 1)
            self.assertIn("trap hook_exit EXIT", prefix)
            self.assertTrue(body)
            for command, expected in (("exit 0", 0), ("false", 2), ("exit 1", 2),
                                      ("exit 2", 2), ("exit 64", 64)):
                with self.subTest(hook=name, command=command):
                    result = subprocess.run([bash, "-c", prefix + command],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stderr)

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

    def test_recovery_cron_explicitly_selects_scheduled_mode(self) -> None:
        self.assertIn(r"@reboot root %s recover-services --scheduled\n", POSTROOT)
        self.assertIn(r"*/5 * * * * root %s recover-services --scheduled\n", POSTROOT)
        self.assertIn('recover-services) shift; recover_restart_journals "$@" ;;', BACKEND)

    def test_packages_exclude_generated_python_caches(self) -> None:
        for marker in ("__pycache__", "*.pyc", "*.pyo"):
            self.assertIn(marker, PACKAGE_SH)
        self.assertIn("__pycache__", PACKAGE_PS1)
        self.assertIn("'.pyc', '.pyo'", PACKAGE_PS1)

    def test_root_hooks_preserve_existing_configuration(self) -> None:
        safety = (ROOT / "bin" / "hostbackup-install-safety.py").read_text(encoding="utf-8")
        self.assertIn("hostbackup-install-safety.py", PREROOT)
        self.assertIn("hostbackup-install-safety.py", POSTROOT)
        self.assertIn("prepare", PREROOT)
        self.assertIn("restore", POSTROOT)
        self.assertIn("complete", POSTROOT)
        self.assertIn("/var/lib/loxberryhostbackup-install-recovery", safety)
        self.assertIn("config.json", safety)
        self.assertIn("fsync", safety, "Configuration must be durable before original removal")

    def test_reinstall_removes_only_validated_stale_platform_files(self) -> None:
        safety = (ROOT / "bin" / "hostbackup-install-safety.py").read_text(encoding="utf-8")
        for primitive in ("O_NOFOLLOW", "O_DIRECTORY", "/proc/self/fd/", "--one-file-system"):
            self.assertIn(primitive, safety)
        self.assertNotIn('rm -rf', PREROOT, "Privileged removal belongs to the anchored helper")
        self.assertIn('if [ "$hook_status" -eq 1 ]; then exit 2;', PREROOT)
        self.assertNotIn('chown -R', PREROOT)

    def test_uninstall_uses_trusted_helper_without_privileged_path_handoff(self) -> None:
        self.assertIn('hostbackup-install-safety.py', UNINSTALL)
        self.assertIn('/usr/libexec/loxberryhostbackup', UNINSTALL)
        self.assertNotIn('-exec chown', UNINSTALL)
        self.assertNotIn('-exec chmod', UNINSTALL)
        self.assertNotIn('chown -R', UNINSTALL)
        self.assertNotIn('rm -f /var/lock/', UNINSTALL)

    def test_backend_identity_checked_before_activation_and_execution(self) -> None:
        marker = "grep -Fxq 'PLUGIN_NAME=\"loxberryhostbackup\"'"
        self.assertIn(marker, POSTROOT)
        self.assertLess(POSTROOT.index(marker), POSTROOT.index('mv -fT -- "$pointer"'))
        self.assertIn(marker, LAUNCHER)
        self.assertLess(LAUNCHER.index(marker), LAUNCHER.index('exec "$release/hostbackup.sh"'))
        self.assertIn('timeout --kill-after=5 30 "$LAUNCHER_TARGET" install-schedule', POSTROOT)

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

    def test_update_channels_match_their_published_versions(self) -> None:
        plugin = configparser.ConfigParser()
        plugin.read_string(PLUGIN_CFG)
        version = plugin["PLUGIN"]["VERSION"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        base = "https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases"
        # The pre-release feed may deliberately point to the current stable ZIP.
        # Check each feed against its advertised tag, not a forced beta suffix.
        for name, source in (("stable", RELEASE_CFG), ("prerelease", PRERELEASE_CFG)):
            with self.subTest(channel=name):
                channel = configparser.ConfigParser()
                channel.read_string(source)
                published = channel["AUTOUPDATE"]["VERSION"]
                self.assertRegex(published, r"^\d+\.\d+\.\d+$")
                self.assertLessEqual(tuple(map(int, published.split("."))), tuple(map(int, version.split("."))))
                tag = channel["AUTOUPDATE"]["INFOURL"].removeprefix(f"{base}/tag/")
                allowed_tags = (f"v{published}", f"v{published}-beta") if name == "prerelease" else (f"v{published}",)
                self.assertIn(tag, allowed_tags)
                archive_url = f"{base}/download/{tag}/LoxBerryHostBackup_{published}.zip"
                self.assertEqual(channel["AUTOUPDATE"]["ARCHIVEURL"], archive_url)
                self.assertEqual(channel["AUTOUPDATE"]["INFOURL"], f"{base}/tag/{tag}")
                self.assertIn(archive_url, README)
                self.assertIn(f"## [{tag[1:]}]", CHANGELOG)
        self.assertIn("prerelease: ${{ contains(github.ref_name, '-') }}", WORKFLOW)

    def test_prerelease_package_version_is_numeric_and_documented(self) -> None:
        plugin = configparser.ConfigParser()
        plugin.read_string(PLUGIN_CFG)
        version = plugin["PLUGIN"]["VERSION"]
        self.assertEqual(version, "1.1.0")
        notes = (ROOT / "docs" / f"RELEASE-{version}-beta.md").read_text(encoding="utf-8")
        self.assertTrue(notes.startswith(f"# LoxBerry Host Backup {version}-beta\n"))
        self.assertIn(f"**Version {version}", README)
        self.assertIn(f"## [{version}-beta]", CHANGELOG)
        self.assertNotIn(f"VERSION={version}-beta", PLUGIN_CFG)
        self.assertIn(f"LoxBerryHostBackup_{version}.zip", notes)

    def test_stable_channel_remains_1_0_0_during_prerelease_publication(self) -> None:
        expected_archive = "https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.0.0/LoxBerryHostBackup_1.0.0.zip"
        for source in (RELEASE_CFG,):
            channel = configparser.ConfigParser()
            channel.read_string(source)
            self.assertEqual(channel["AUTOUPDATE"]["VERSION"], "1.0.0")
            self.assertEqual(channel["AUTOUPDATE"]["ARCHIVEURL"], expected_archive)
        plugin = configparser.ConfigParser()
        plugin.read_string(PLUGIN_CFG)
        self.assertEqual(plugin["AUTOUPDATE"]["RELEASECFG"], "https://raw.githubusercontent.com/herdan75/LoxBerry-Plugin-HostBackup/main/release.cfg")
        self.assertEqual(plugin["AUTOUPDATE"]["PRERELEASECFG"], "https://raw.githubusercontent.com/herdan75/LoxBerry-Plugin-HostBackup/refs/heads/develop/prerelease.cfg")
        self.assertIn("if: github.event_name == 'release' || startsWith(github.ref, 'refs/tags/')", WORKFLOW)
        notes = (ROOT / "docs" / "RELEASE-1.0.0.md").read_text(encoding="utf-8")
        self.assertIn("Reguläres Release", notes)
        self.assertNotIn("Noch nicht veröffentlicht", notes)
        self.assertIn("stabile Kanal bleibt auf 1.0.0", README)

    def test_trusted_install_and_webuser_permissions(self) -> None:
        self.run_linux_install_child("--trusted-install-child")

    def test_real_backend_install_with_loxberry_cron_symlink(self) -> None:
        self.run_linux_install_child("--cron-install-child")

    def test_real_unprivileged_platform_upgrade_and_stale_launcher(self) -> None:
        self.run_linux_install_child("--platform-upgrade-child")

    def test_descriptor_anchored_installer_cleanup_and_mount_boundaries(self) -> None:
        self.run_linux_install_child("--installer-safety-child")

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
            return installer_fixture_source(text.replace("/usr/libexec/loxberryhostbackup", str(trusted))
                    .replace("/usr/local/sbin/loxberryhostbackup", str(launcher))
                    .replace("/etc/cron.d/loxberryhostbackup-recovery", str(recovery))
                    .replace("/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade",
                             str(sandbox / "upgrade/${INSTALL_ID}_loxberryhostbackup_upgrade"))
                    .replace("loxberry:loxberry", "nobody:nogroup"), sandbox)

        stage_installer_helper(sandbox, sandbox, rewrite)

        def install_sources(label):
            bindir.mkdir(parents=True, exist_ok=True)
            for source in (ROOT / "bin").iterdir():
                if source.suffix in (".sh", ".py", ".php"):
                    (bindir / source.name).write_text(rewrite(source.read_text(encoding="utf-8")), encoding="utf-8")
                    (bindir / source.name).chmod(0o755)
            # Calls run a harmless stub, never service control or a real backup.
            (bindir / "hostbackup.sh").write_text(
                "#!/bin/bash\nset -eu\nPLUGIN_NAME=\"loxberryhostbackup\"\nprintf '%s\\n' '" + label + "' \"$@\"\n"
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
        assert "@reboot root " + str(launcher) + " recover-services --scheduled\n" in recovery.read_text()
        assert "*/5 * * * * root " + str(launcher) + " recover-services --scheduled\n" in recovery.read_text()
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
        assert "second\nrecover-services\n" == run(dispatcher, "recover-services").stdout
        assert run(dispatcher, "recover-services", "--scheduled", success=False).returncode != 0
        assert run(dispatcher, "restore", "anything", success=False).returncode != 0
        assert run(dispatcher, "config", "extra", success=False).returncode != 0


def platform_upgrade_integration():
    """Reproduce LoxBerry's purge/copy as a real unprivileged user, not root.

    Only a private /var/lib fixture is modified. Neither real platform files nor
    user backups are involved; the real backend only reads config/installs a
    redirected schedule. A legacy blocked copy must not activate a stale shim.
    """
    import pwd

    assert os.geteuid() == 0
    nobody = pwd.getpwnam("nobody")
    with tempfile.TemporaryDirectory(prefix="hostbackup-platform-update-", dir="/var/lib") as temporary:
        sandbox = pathlib.Path(temporary)
        sandbox.chmod(0o755)
        home = sandbox / "lbh"
        trusted = sandbox / "libexec/loxberryhostbackup"
        launcher = sandbox / "sbin/loxberryhostbackup"
        cron = sandbox / "etc/cron.d"
        cron.mkdir(parents=True)
        incoming = sandbox / "package/bin"
        incoming.mkdir(parents=True)
        bindir = home / "bin/plugins/loxberryhostbackup"
        config = home / "config/plugins/loxberryhostbackup/config.json"
        cgi = home / "webfrontend/htmlauth/plugins/loxberryhostbackup/index.cgi"
        for directory in (home / "bin/plugins", home / "data/plugins", config.parent, cgi.parent):
            directory.mkdir(parents=True, exist_ok=True)
        # Platform-owned parents allow removal of the plugin directories, just
        # like LoxBerry. The protected runtime lives outside this mutable tree.
        for directory in (home, *home.rglob("*")):
            if directory.is_dir():
                os.chown(directory, nobody.pw_uid, nobody.pw_gid)
                directory.chmod(0o755)
        saved = {"backup_root": "/media/usb/PI_Backup/loxberry-hostbackup",
                 "keep_backups": 3, "metadata_mode": "native-strict",
                 "schedule_enabled": True, "schedule_mode": "daily", "schedule_time": "03:17",
                 "rsync_extra_excludes": ["/media/usb/PI_Backup"],
                 "stop_targets": ["systemd:mosquitto.service"], "backup_mode": "snapshot"}
        saved_bytes = json.dumps(saved).encode()
        config.write_bytes(saved_bytes)
        cgi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        def rewrite(text):
            return installer_fixture_source(text.replace("/usr/libexec/loxberryhostbackup", str(trusted))
                    .replace("/usr/local/sbin/loxberryhostbackup", str(launcher))
                    .replace("/etc/cron.d", str(cron))
                    .replace("/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade",
                             str(sandbox / "upgrade/${INSTALL_ID}_loxberryhostbackup_upgrade"))
                    .replace("loxberry:loxberry", "nobody:nogroup"), sandbox)

        for source in (ROOT / "bin").iterdir():
            if source.suffix in (".sh", ".py", ".php"):
                target = incoming / source.name
                target.write_text(rewrite(source.read_text(encoding="utf-8")), encoding="utf-8")
                target.chmod(0o755)
        stage_installer_helper(incoming.parent, sandbox, rewrite)
        (incoming / "runtime-version").write_text("0.7.0\n", encoding="utf-8")
        postroot, preroot = sandbox / "postroot.sh", sandbox / "preroot.sh"
        postroot.write_text(rewrite(POSTROOT), encoding="utf-8")
        preroot.write_text(rewrite(PREROOT), encoding="utf-8")
        defaults = sandbox / "default-config.json"
        defaults.write_text('{"keep_backups":10}', encoding="utf-8")

        def run(*args, platform=False, success=True):
            credentials = dict(user=nobody.pw_uid, group=nobody.pw_gid, extra_groups=[]) if platform else {}
            result = subprocess.run([str(arg) for arg in args], text=True, capture_output=True,
                                    check=False, timeout=15, cwd=sandbox, **credentials)
            if success:
                assert result.returncode == 0, result.stdout + result.stderr
            return result

        def hook(script, install_id, success=True):
            return run("bash", script, install_id, "", "loxberryhostbackup", "", home, incoming.parent, success=success)

        def copy_as_platform(success=True):
            result = run("cp", "-r", str(incoming) + "/.", bindir, platform=True, success=success)
            # LoxBerry sets owner/mode AFTER copying; do not move this ahead of
            # the copy and accidentally mask the very failure being tested.
            run("chown", "-R", "nobody:nogroup", bindir)
            run("chmod", "-R", "755", bindir)
            return result

        def assert_settings_and_backend():
            assert config.read_bytes() == saved_bytes
            assert config.stat().st_uid == 0 and config.stat().st_mode & 0o777 == 0o600
            active = (trusted / "current").resolve()
            assert (active / "hostbackup.sh").read_bytes() == (incoming / "hostbackup.sh").read_bytes()
            assert (active / "runtime-version").read_text() == "0.7.0\n"
            loaded = json.loads(run("bash", launcher, "config").stdout)
            for key, value in saved.items():
                assert loaded[key] == value, (key, loaded[key], value)
            assert "17 3 * * * root " in (cron / "loxberryhostbackup").read_text()
            assert bindir.stat().st_uid == 0
            return active

        copy_as_platform()
        hook(postroot, "first")
        first = assert_settings_and_backend()
        first_contents = {p.name: p.read_bytes() for p in first.iterdir()}
        # Explicitly reproduce the previously hidden Permission-denied copy.
        purge = run("rm", "-rf", bindir, platform=True, success=False)
        assert purge.returncode != 0 and "Permission denied" in purge.stderr
        failed_copy = copy_as_platform(success=False)
        assert failed_copy.returncode != 0 and "Permission denied" in failed_copy.stderr
        assert (bindir / "hostbackup.sh").read_bytes() == (incoming / "hostbackup-launcher.sh").read_bytes()
        rejected = hook(postroot, "stale-source", success=False)
        assert rejected.returncode != 0 and "not the backup backend" in rejected.stderr
        assert (trusted / "current").resolve() == first
        assert config.read_bytes() == saved_bytes
        # Even if a stale candidate were activated externally, the fixed root
        # launcher must refuse immediately, without spawning an exec loop.
        bad = trusted / "releases/bad-fixture"
        shutil.copytree(first, bad)
        shutil.copyfile(bad / "hostbackup-launcher.sh", bad / "hostbackup.sh")
        (trusted / "current").unlink()
        (trusted / "current").symlink_to(bad)
        refused = run("bash", launcher, "config", success=False)
        assert refused.returncode == 64 and "refusing a recursive start" in refused.stderr
        (trusted / "current").unlink()
        (trusted / "current").symlink_to(first)

        # Recover the root-owned legacy staging directory and then repeat the
        # exact same version again. All purges/copies happen as the web user.
        for install_id in ("repair", "repeat"):
            # Legacy root-owned cache directories and external links must not
            # turn this migration into a recursive chown of the trusted store.
            cache = bindir / "__pycache__"
            cache.mkdir(mode=0o700)
            (cache / "old.pyc").write_bytes(b"old")
            (bindir / "external-link").symlink_to(first, target_is_directory=True)
            hook(preroot, install_id)
            assert not bindir.exists() and not cache.exists()
            assert not config.exists()
            assert (first / "hostbackup.sh").stat().st_uid == 0
            assert {p.name: p.read_bytes() for p in first.iterdir()} == first_contents
            run("rm", "-rf", bindir, config.parent, platform=True)
            run("mkdir", "-p", config.parent, platform=True)
            run("cp", defaults, config, platform=True)
            copy_as_platform()
            previous = (trusted / "current").resolve()
            hook(postroot, install_id)
            active = assert_settings_and_backend()
            assert active != previous
            assert previous.is_dir() and first.is_dir()
            assert {p.name: p.read_bytes() for p in first.iterdir()} == first_contents

        # Old PREROOT changed directory owners only. Without the upgrade purge,
        # root-owned files still reject cp even in writable parent directories.
        for directory in (bindir, config.parent):
            os.chown(directory, nobody.pw_uid, nobody.pw_gid)
            directory.chmod(0o755)
        old_config_copy = run("cp", defaults, config, platform=True, success=False)
        old_bin_copy = run("cp", "-r", str(incoming) + "/.", bindir, platform=True, success=False)
        assert old_config_copy.returncode and "Permission denied" in old_config_copy.stderr
        assert old_bin_copy.returncode and "Permission denied" in old_bin_copy.stderr
        assert config.read_bytes() == saved_bytes
        external = sandbox / "external-helper"
        external.write_bytes(b"must remain untouched")
        external.chmod(0o600)
        os.link(external, bindir / "hardlinked-helper")
        (bindir / "external-link").symlink_to(first, target_is_directory=True)
        hook(preroot, "fresh-leftovers")
        # Deliberately NO rm/purge here: this is LoxBerry's NEW-install branch.
        run("cp", defaults, config, platform=True)
        copy_as_platform()
        hook(postroot, "fresh-leftovers")
        assert_settings_and_backend()
        assert external.read_bytes() == b"must remain untouched"
        assert external.stat().st_uid == 0 and external.stat().st_mode & 0o777 == 0o600
        assert {p.name: p.read_bytes() for p in first.iterdir()} == first_contents

        # A failed installer may leave either no config or package defaults.
        # A retry has a new installation ID; a reboot may have removed /tmp.
        # Neither event may replace the original settings with those defaults.
        for interrupted_id, replacement in (("interrupted-missing", None),
                                            ("interrupted-defaults", defaults.read_bytes()),
                                            ("interrupted-partial", b'{"keep_backups":')):
            hook(preroot, interrupted_id)
            assert not config.exists() and not bindir.exists()
            recovery_files = list((sandbox / "durable-recovery").rglob("config.json"))
            assert len(recovery_files) == 1 and recovery_files[0].read_bytes() == saved_bytes
            recovery_file = recovery_files[0]
            assert recovery_file.stat().st_uid == 0 and recovery_file.stat().st_mode & 0o777 == 0o600
            assert recovery_file.parent.stat().st_uid == 0 and recovery_file.parent.stat().st_mode & 0o777 == 0o700
            assert run("test", "-r", recovery_file, platform=True, success=False).returncode != 0
            temporary_upgrade = sandbox / "upgrade"
            if temporary_upgrade.exists():
                shutil.rmtree(temporary_upgrade)
            if replacement is not None:
                partial = sandbox / "partial-copy.json"
                partial.write_bytes(replacement)
                run("cp", partial, config, platform=True)
            hook(preroot, interrupted_id + "-new-id")
            run("cp", defaults, config, platform=True)
            copy_as_platform()
            hook(postroot, interrupted_id + "-new-id")
            assert_settings_and_backend()
            assert not list((sandbox / "durable-recovery").rglob("config.json"))
            assert external.read_bytes() == b"must remain untouched"

        # POSTROOT itself must recover a truncated config without requiring a
        # second prepare, and only clear the durable copy after it succeeded.
        hook(preroot, "interrupted-copy-only")
        config.write_bytes(b'{"incomplete":')
        copy_as_platform()
        hook(postroot, "interrupted-copy-only")
        assert_settings_and_backend()
        assert not list((sandbox / "durable-recovery").rglob("config.json"))

        # An incomplete platform copy must not activate a runtime which lacks
        # the helper required for safe uninstall/installation completion.
        before_missing_helper = (trusted / "current").resolve()
        hook(preroot, "missing-installed-helper")
        run("cp", defaults, config, platform=True)
        copy_as_platform()
        (bindir / "hostbackup-install-safety.py").unlink()
        refused = hook(postroot, "missing-installed-helper", success=False)
        assert refused.returncode != 0 and "Required installed file is missing" in refused.stderr
        assert (trusted / "current").resolve() == before_missing_helper
        assert config.read_bytes() == saved_bytes
        recovery_files = list((sandbox / "durable-recovery").rglob("config.json"))
        assert len(recovery_files) == 1 and recovery_files[0].read_bytes() == saved_bytes
        hook(preroot, "missing-installed-helper-retry")
        run("cp", defaults, config, platform=True)
        copy_as_platform()
        hook(postroot, "missing-installed-helper-retry")
        assert_settings_and_backend()
        assert not list((sandbox / "durable-recovery").rglob("config.json"))

        # Even an unusual but formerly allowed target inside the platform bin
        # tree is user data, not disposable program code. Refuse before removal.
        bin_backup = bindir / "backups"
        bin_backup.mkdir()
        (bin_backup / "sentinel").write_bytes(b"backup must survive update")
        config.write_text(json.dumps({**saved, "backup_root": str(bin_backup)}))
        refused = hook(preroot, "backup-in-bin", success=False)
        assert refused.returncode == 2 and "Backup target" in refused.stderr
        assert (bin_backup / "sentinel").read_bytes() == b"backup must survive update"
        assert json.loads(config.read_text())["backup_root"] == str(bin_backup)
        config.write_bytes(saved_bytes)
        shutil.rmtree(bin_backup)

        # Refuse a mounted file before securing/removing existing settings or
        # code. Inject only the kernel mount-ID observation into the staged
        # helper; mount no actual host paths and keep the production flow intact.
        staged_helper = incoming / "hostbackup-install-safety.py"
        original_helper = staged_helper.read_text(encoding="utf-8")
        mounted_file = bindir / "hostbackup-overview.py"
        mount_fixture = "\n_original_mount_id = mount_id\ndef mount_id(fd):\n" + (
            "    actual = os.fstat(fd)\n"
            f"    mounted = os.stat({str(mounted_file)!r})\n"
            "    changed = (actual.st_dev, actual.st_ino) == (mounted.st_dev, mounted.st_ino)\n"
            "    return _original_mount_id(fd) + (1 if changed else 0)\n"
        )
        staged_helper.write_text(original_helper.replace('\nif __name__ == "__main__":',
                                                        mount_fixture + '\nif __name__ == "__main__":'), encoding="utf-8")
        before_bin = (bindir / "hostbackup.sh").read_bytes()
        try:
            refused = hook(preroot, "mounted-bin", success=False)
            assert refused.returncode == 2 and "mounted entry" in refused.stderr
        finally:
            staged_helper.write_text(original_helper, encoding="utf-8")
        assert config.read_bytes() == saved_bytes
        assert (bindir / "hostbackup.sh").read_bytes() == before_bin
        assert not list((sandbox / "durable-recovery").rglob("config.json"))

        # Reject an ancestor link too, not merely a symlink at the final bin dir.
        bin_parent = home / "bin"
        moved_parent = home / "saved-bin-parent"
        bin_parent.rename(moved_parent)
        bin_parent.symlink_to(moved_parent, target_is_directory=True)
        try:
            refused = hook(preroot, "linked-parent", success=False)
            assert refused.returncode == 2 and "refused" in refused.stderr.lower()
            assert (bindir / "hostbackup.sh").read_bytes() == before_bin
            assert config.read_bytes() == saved_bytes
        finally:
            bin_parent.unlink()
            moved_parent.rename(bin_parent)

        # Uninstall must keep recovery capability intact until no work remains.
        uninstall = sandbox / "uninstall.sh"
        operation_lock = sandbox / "operation.lock"
        uninstall.write_text(rewrite(UNINSTALL).replace(
            '/var/lock/${PLUGIN_FOLDER}.operation.lock', str(operation_lock)
        ).replace('/etc/sudoers.d/loxberryhostbackup', str(sandbox / 'sudoers')), encoding="utf-8")
        state = home / "data/plugins/loxberryhostbackup/root-state"
        pending = state / "restart-journals/pending"
        pending.mkdir(parents=True)
        (pending / "journal.json").write_text('{"entries":[]}', encoding="utf-8")
        refused = hook(uninstall, "pending-uninstall", success=False)
        assert refused.returncode == 2 and "recover services" in refused.stderr
        assert launcher.exists() and trusted.exists() and config.read_bytes() == saved_bytes
        shutil.rmtree(pending)
        import fcntl
        with operation_lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before_active_bin = (bindir / "hostbackup.sh").read_bytes()
            refused = hook(preroot, "busy-install", success=False)
            assert refused.returncode == 2 and "operation is active" in refused.stderr
            assert config.read_bytes() == saved_bytes
            assert (bindir / "hostbackup.sh").read_bytes() == before_active_bin
            refused = hook(uninstall, "busy-uninstall", success=False)
            assert refused.returncode == 2 and "operation is active" in refused.stderr
            assert launcher.exists() and trusted.exists()
        protected_backup = home / "data/plugins/loxberryhostbackup/backups"
        protected_backup.mkdir()
        (protected_backup / "sentinel").write_bytes(b"backup")
        config.write_text(json.dumps({**saved, "backup_root": str(protected_backup)}))
        refused = hook(uninstall, "backup-uninstall", success=False)
        assert refused.returncode == 2 and "Backup target is inside" in refused.stderr
        assert (protected_backup / "sentinel").read_bytes() == b"backup"
        config.write_bytes(saved_bytes)
        shutil.rmtree(protected_backup)

        # Full root-uninstall -> platform purge -> fresh installation. The
        # disposable tree is removed with anchored root operations, not made
        # user-owned for a later privileged pathname traversal.
        cache = bindir / "__pycache__"
        cache.mkdir(mode=0o000)
        (cache / "old.pyc").write_bytes(b"old")
        os.link(external, bindir / "hardlinked-helper")
        outside_backup = sandbox / "external-backup"
        outside_backup.mkdir()
        (outside_backup / "sentinel").write_bytes(b"backup")
        (bindir / "backup-link").symlink_to(outside_backup, target_is_directory=True)
        hook(uninstall, "full-uninstall")
        assert not launcher.exists() and not trusted.exists() and not state.exists()
        assert not config.exists() and not bindir.exists() and not cache.exists()
        assert external.stat().st_uid == 0 and external.stat().st_mode & 0o777 == 0o600
        assert external.read_bytes() == b"must remain untouched"
        run("rm", "-rf", bindir, config.parent, home / "data/plugins/loxberryhostbackup", platform=True)
        assert not bindir.exists() and not config.parent.exists()
        assert (outside_backup / "sentinel").read_bytes() == b"backup"
        hook(preroot, "fresh-after-uninstall")
        run("mkdir", "-p", config.parent, platform=True)
        # A genuine uninstall intentionally removed settings; package defaults
        # apply on this fresh installation, rather than resurrecting stale ones.
        run("cp", defaults, config, platform=True)
        copy_as_platform()
        hook(postroot, "fresh-after-uninstall")
        assert json.loads(config.read_text())["keep_backups"] == 10
        assert (trusted / "current/hostbackup.sh").read_bytes() == (incoming / "hostbackup.sh").read_bytes()

        # Refuse a substituted bin-directory link without touching its target.
        first = (trusted / "current").resolve()
        original_bin = bindir.with_name("bin-saved")
        bindir.rename(original_bin)
        bindir.symlink_to(first, target_is_directory=True)
        rejected = hook(preroot, "unsafe-link", success=False)
        assert rejected.returncode == 2 and "refused" in rejected.stderr.lower()
        assert (first / "hostbackup.sh").stat().st_uid == 0
        assert {p.name: p.read_bytes() for p in first.iterdir()} == first_contents


def installer_safety_integration():
    """Exercise Linux fd anchoring, including a deterministic ancestor swap.

    Every file and deletion remains under this one private /var/lib fixture.
    Bind-mount IDs are injected at the kernel-metadata reader boundary: no real
    host mount or configuration is changed by these tests.
    """
    import importlib.util
    from unittest import mock

    assert os.geteuid() == 0
    source = ROOT / "bin" / "hostbackup-install-safety.py"
    spec = importlib.util.spec_from_file_location("installer_safety_fixture", source)
    safety = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(safety)

    with tempfile.TemporaryDirectory(prefix="hostbackup-installer-safety-", dir="/var/lib") as temporary:
        sandbox = pathlib.Path(temporary)
        outside = sandbox / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"external bytes and permissions must stay unchanged")
        sentinel.chmod(0o400)
        initial = sentinel.stat()

        def assert_outside():
            assert sentinel.read_bytes() == b"external bytes and permissions must stay unchanged"
            current = sentinel.stat()
            assert (current.st_uid, current.st_gid, current.st_mode) == (initial.st_uid, initial.st_gid, initial.st_mode)

        # A literal link in the deletion target or any ancestor is never followed.
        linked = sandbox / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        for path in (linked, linked / "child"):
            try:
                safety.open_dir(str(path))
            except OSError:
                pass
            else:
                raise AssertionError("Installer followed a directory symlink")
            assert_outside()

        disposable = sandbox / "disposable"
        disposable.mkdir()
        (disposable / "outside-link").symlink_to(outside, target_is_directory=True)
        os.link(sentinel, disposable / "hardlinked-file")
        safety.remove_tree(str(disposable))
        assert not disposable.exists()
        assert_outside()

        # Hold the old parent fd, then swap its absolute pathname immediately
        # before GNU rm executes. A path-based cleanup would delete the sentinel
        # in outside/plugin; the anchored cleanup must remove moved/plugin only.
        parent = sandbox / "parent"
        parent.mkdir()
        original = parent / "plugin"
        original.mkdir()
        (original / "old-helper").write_text("disposable")
        external_plugin = outside / "plugin"
        external_plugin.mkdir()
        protected = external_plugin / "must-remain"
        protected.write_bytes(b"do not delete through replacement parent")
        moved = sandbox / "moved-parent"
        actual_run = subprocess.run

        def replace_parent_then_run(*args, **kwargs):
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
            return actual_run(*args, **kwargs)

        with mock.patch.object(safety.subprocess, "run", side_effect=replace_parent_then_run):
            safety.remove_tree(str(original))
        assert not (moved / "plugin").exists()
        assert protected.read_bytes() == b"do not delete through replacement parent"
        assert_outside()

        # A final-component replacement link also must only be unlinked itself.
        final_parent = sandbox / "final-parent"
        final_parent.mkdir()
        final_target = final_parent / "plugin"
        final_target.mkdir()
        old_final = final_parent / "retained-original"

        def replace_final_then_run(*args, **kwargs):
            final_target.rename(old_final)
            final_target.symlink_to(outside, target_is_directory=True)
            return actual_run(*args, **kwargs)

        with mock.patch.object(safety.subprocess, "run", side_effect=replace_final_then_run):
            safety.remove_tree(str(final_target))
        assert old_final.is_dir() and not final_target.is_symlink()
        assert protected.read_bytes() == b"do not delete through replacement parent"
        assert_outside()

        # Same-device bind mounts and file mounts must be detected by mnt_id,
        # even though st_dev has not changed. Validation performs no deletion.
        mount_tree = sandbox / "mount-tree"
        mount_tree.mkdir()
        nested = mount_tree / "nested"
        nested.mkdir()
        mount_file = nested / "bind-file"
        mount_file.write_bytes(b"mounted fixture")
        actual_mount_id = safety.mount_id
        for mounted in (mount_tree, nested, mount_file):
            mounted_stat = mounted.stat()

            def changed_mount_id(fd):
                current = os.fstat(fd)
                match = (current.st_dev, current.st_ino) == (mounted_stat.st_dev, mounted_stat.st_ino)
                return actual_mount_id(fd) + (1 if match else 0)

            with mock.patch.object(safety, "mount_id", side_effect=changed_mount_id):
                try:
                    parent_fd = safety.checked_tree(str(mount_tree))
                except ValueError as error:
                    assert "mounted" in str(error)
                else:
                    if parent_fd is not None:
                        os.close(parent_fd)
                    raise AssertionError("Installer accepted a different mount ID")
            assert mount_file.read_bytes() == b"mounted fixture"
            assert_outside()

        # Existing lock inode must neither be truncated nor unlinked; aliases
        # and nonregular files are refused, with bounded FIFO opens.
        lock = sandbox / "operation.lock"
        safety.OPERATION_LOCK_TEMPLATE = str(lock)
        lock.write_bytes(b"existing lock marker")
        lock.chmod(0o600)
        lock_inode = lock.stat().st_ino
        fd = safety.acquire_lock("loxberryhostbackup")
        os.close(fd)
        assert lock.stat().st_ino == lock_inode and lock.read_bytes() == b"existing lock marker"
        lock.unlink()
        lock.symlink_to(sentinel)
        try:
            safety.acquire_lock("loxberryhostbackup")
        except (OSError, ValueError):
            pass
        else:
            raise AssertionError("Installer followed lock symlink")
        lock.unlink()
        os.link(sentinel, lock)
        try:
            safety.acquire_lock("loxberryhostbackup")
        except ValueError:
            pass
        else:
            raise AssertionError("Installer accepted a hardlinked lock")
        lock.unlink()
        assert_outside()

        # Separate child processes make a regression to blocking FIFO opens fail
        # deterministically within 3 seconds instead of hanging the CI suite.
        os.mkfifo(lock)
        fifo_config = sandbox / "fifo-config"
        fifo_config.mkdir()
        os.mkfifo(fifo_config / "config.json")
        snippet = """
import importlib.util, os, sys
spec=importlib.util.spec_from_file_location('fixture', sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
try:
    if sys.argv[2] == 'lock':
        module.OPERATION_LOCK_TEMPLATE=sys.argv[3]
        module.acquire_lock('loxberryhostbackup')
    else:
        fd=module.open_dir(sys.argv[3])
        try: module.read_config(fd)
        finally: os.close(fd)
except (OSError, ValueError):
    raise SystemExit(0)
raise SystemExit('Nonregular installer target was accepted')
"""
        for mode, target in (("lock", lock), ("config", fifo_config)):
            result = subprocess.run([sys.executable, "-c", snippet, str(source), mode, str(target)],
                                    capture_output=True, text=True, check=False, timeout=3)
            assert result.returncode == 0, result.stdout + result.stderr
            assert_outside()


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
                return installer_fixture_source(text.replace("/usr/libexec/loxberryhostbackup", str(trusted))
                        .replace("/usr/local/sbin/loxberryhostbackup", str(launcher))
                        .replace("/etc/cron.d", str(cron))
                        .replace("/tmp/${INSTALL_ID}_loxberryhostbackup_upgrade",
                                 str(sandbox / "upgrade/${INSTALL_ID}_loxberryhostbackup_upgrade"))
                        .replace("loxberry:loxberry", "nobody:nogroup"), sandbox)

            stage_installer_helper(sandbox, sandbox, rewrite)

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
            assert "@reboot root " + str(launcher) + " recover-services --scheduled\n" in recovery.read_text()
            assert "*/5 * * * * root " + str(launcher) + " recover-services --scheduled\n" in recovery.read_text()
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
    elif sys.argv[1:] == ["--platform-upgrade-child"]:
        platform_upgrade_integration()
    elif sys.argv[1:] == ["--installer-safety-child"]:
        installer_safety_integration()
    else:
        unittest.main()
