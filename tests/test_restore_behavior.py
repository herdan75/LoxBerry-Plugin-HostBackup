#!/usr/bin/env python3
"""Restore behavior checks; every copy destination is a disposable directory.

The full backend is never sourced: its startup creates runtime directories.
Only the pure option-producing functions are extracted for metadata fixtures.
Linux CI requires real rsync/ACL/xattr coverage; other hosts skip those checks
explicitly while still exercising the recovery helper's file validation.
"""

import importlib.util
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "bin" / "hostbackup-recovery.py"
BACKEND = ROOT / "bin" / "hostbackup.sh"
REQUIRE_LINUX = os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1"


def backend_function(name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        BACKEND.read_text(encoding="utf-8"),
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Backend function missing: {name}")
    return match.group(0)


def recovery_module():
    spec = importlib.util.spec_from_file_location("hostbackup_recovery_test", RECOVERY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetadataTransportOptionsTests(unittest.TestCase):
    def test_fake_super_transport_is_local_and_preserves_protocol_paths(self) -> None:
        recovery = recovery_module()
        options = recovery.copy_options("fake-super")
        self.assertIn("--fake-super", options)
        self.assertIn("-M--super", options)
        self.assertIn("--protect-args", options)
        self.assertIn("--whole-file", options)
        transport = next(value.split("=", 1)[1] for value in options if value.startswith("--rsh="))
        self.assertEqual(shlex.split(transport), ["/bin/sh", "-c", 'shift; exec "$@"', "hostbackup-local"])
        self.assertEqual(recovery.rsync_destination("fake-super", "/backup with ' quotes/"),
                         "hostbackup-local:/backup with ' quotes/")
        for mode in ("native-strict", "network-compatible"):
            self.assertFalse(any(value.startswith("--rsh=") for value in recovery.copy_options(mode)))
            self.assertEqual(recovery.rsync_destination(mode, "/backup/"), "/backup/")


class RecoveryExclusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory(prefix="hostbackup-recovery-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = pathlib.Path(self.workspace.name)
        self.backup_root = self.root / "backups"
        self.backup = self.backup_root / "backup-1"
        self.backup.mkdir(parents=True)
        self.destination = self.root / "restore"
        self.destination.mkdir()
        self.excludes = self.backup / "rsync-excludes.txt"
        self.output = self.root / "restore-excludes.txt"

    def recovery(self, command: str = "excludes", *extra: str) -> subprocess.CompletedProcess[str]:
        args = [
            sys.executable, str(RECOVERY), command,
            "--backup", str(self.backup),
            "--backup-root", str(self.backup_root),
            "--destination", str(self.destination),
        ]
        if command == "excludes":
            args.extend(["--output", str(self.output)])
        args.extend(extra)
        return subprocess.run(args, text=True, capture_output=True, check=False, timeout=30)

    def test_saved_user_exclusions_are_retained(self) -> None:
        self.excludes.write_text("/home/private\n/var/log/*.log\n/proc\n", encoding="utf-8", newline="\n")
        result = self.recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.output.read_text(encoding="utf-8").splitlines()
        self.assertIn("/home/private", rules)
        self.assertIn("/var/log/*.log", rules)
        self.assertIn("/proc", rules)

    def test_missing_saved_exclusions_fail_closed(self) -> None:
        result = self.recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists(), "A failed validation must not publish restore rules")

    def test_nul_in_saved_exclusions_is_rejected(self) -> None:
        self.excludes.write_bytes(b"/home/private\x00/other\n")
        result = self.recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_embedded_carriage_return_cannot_split_an_exclusion(self) -> None:
        self.excludes.write_bytes(b"/home/private\r/other\n")
        result = self.recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_saved_exclusion_symlink_is_rejected(self) -> None:
        source = self.root / "foreign-rules"
        source.write_text("/home/private\n", encoding="utf-8", newline="\n")
        try:
            self.excludes.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symlinks is not permitted on this host")
        result = self.recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_explicit_runtime_protection_is_included(self) -> None:
        self.excludes.write_text("/home/private\n", encoding="utf-8", newline="\n")
        result = self.recovery("excludes", "--protect", "/opt/loxberry/config/plugins/loxberryhostbackup")
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = self.output.read_text(encoding="utf-8").splitlines()
        self.assertIn("/opt/loxberry/config/plugins/loxberryhostbackup", rules)

    def plan(self, mappings: list, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.recovery("plan", "--map-json", json.dumps(mappings), *extra)

    def record_mounts(self, *paths: str) -> None:
        self.excludes.write_text("/home/private\n", encoding="utf-8", newline="\n")
        (self.backup / "source-mounts.json").write_text(
            json.dumps([{"target": path} for path in paths]), encoding="utf-8",
        )

    def test_recorded_volume_requires_explicit_mapping(self) -> None:
        self.record_mounts("/media/data")
        result = self.plan([])
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn("/media/data", plan["excluded_mounts"])
        self.assertIn("/media/data", plan["exclude_rules"])
        self.assertEqual(plan["volumes"], [])

    def test_recorded_volume_maps_inside_offline_destination(self) -> None:
        self.record_mounts("/media/data")
        mapped = self.destination / "media" / "data"
        mapped.mkdir(parents=True)
        result = self.plan([{"source": "/media/data", "destination": str(mapped)}])
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["volumes"], [{"source": "/media/data", "destination": str(mapped.resolve())}])
        self.assertNotIn("/media/data", plan["excluded_mounts"])
        self.assertIn("/media/data", plan["exclude_rules"], "Mapped volume must not also be copied by the root pass")

    def test_unrecorded_volume_mapping_is_rejected(self) -> None:
        self.record_mounts("/media/data")
        mapped = self.destination / "data"
        mapped.mkdir()
        result = self.plan([{"source": "/unrecorded", "destination": str(mapped)}])
        self.assertNotEqual(result.returncode, 0)

    def test_mapping_cannot_write_into_backup_store(self) -> None:
        self.record_mounts("/media/data")
        result = self.plan([{"source": "/media/data", "destination": str(self.backup)}])
        self.assertNotEqual(result.returncode, 0)

    def test_mapping_cannot_overlap_protected_runtime(self) -> None:
        self.record_mounts("/media/data")
        mapped = self.destination / "plugin-runtime"
        mapped.mkdir()
        result = self.plan(
            [{"source": "/media/data", "destination": str(mapped)}],
            "--protect", str(mapped.resolve()),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_overlapping_source_volume_mappings_are_rejected(self) -> None:
        self.record_mounts("/media/data", "/media/data/photos")
        first = self.destination / "data"
        second = self.destination / "photos"
        first.mkdir()
        second.mkdir()
        result = self.plan([
            {"source": "/media/data", "destination": str(first)},
            {"source": "/media/data/photos", "destination": str(second)},
        ])
        self.assertNotEqual(result.returncode, 0)


class PortableExclusionSemanticsTests(unittest.TestCase):
    def test_gnu_tar_volume_transform_handles_mixed_prefixes(self) -> None:
        tar = shutil.which("tar")
        if os.name == "nt":
            bundled_tar = pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "usr" / "bin" / "tar.exe"
            if bundled_tar.exists():
                tar = str(bundled_tar)
        if not tar:
            self.skipTest("GNU tar is unavailable")
        version = subprocess.run([tar, "--version"], text=True, capture_output=True, check=False, timeout=10)
        if "GNU tar" not in version.stdout:
            self.skipTest("Volume transformation requires GNU tar")
        recovery = recovery_module()
        with tempfile.TemporaryDirectory(prefix="hostbackup-tar-prefix-test-") as directory:
            root = pathlib.Path(directory).resolve()
            destination = root / "restore"
            destination.mkdir()
            archive_path = root / "source.tar"
            volume = "media/data[1],set"
            members = [("./" + volume + "/a.txt", b"alpha"), (volume + "/b.txt", b"beta")]
            with tarfile.open(archive_path, "w", format=tarfile.PAX_FORMAT) as archive:
                for name, content in members:
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            selected = root / "members.nul"
            selected.write_bytes(b"".join(name.encode("utf-8") + b"\0" for name, _ in members))
            command = [tar, "--force-local", "--no-recursion", "--null", "--verbatim-files-from",
                       "-C", destination.as_posix(), "-xvpf", archive_path.as_posix(), "--show-transformed-names",
                       "--transform=" + recovery.tar_volume_transform(volume), "-T", selected.as_posix()]
            if os.name == "nt":
                # Send the expression through MSYS Bash stdin: native Windows
                # argv parsing otherwise changes backslashes in GNU tar's regex.
                bash = pathlib.Path(tar).parents[2] / "bin" / "bash.exe"
                result = subprocess.run(
                    [str(bash), "--noprofile", "--norc", "-s"],
                    input=shlex.join(command) + "\n", text=True,
                    capture_output=True, check=False, timeout=30,
                )
            else:
                result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((destination / "a.txt").exists(), result.stdout + repr(list(destination.rglob("*"))))
            self.assertEqual((destination / "a.txt").read_bytes(), b"alpha")
            self.assertEqual((destination / "b.txt").read_bytes(), b"beta")

    def test_wildcards_match_rsync_path_rules(self) -> None:
        recovery = recovery_module()
        cases = [
            ("nested/foo/bar", "foo/bar", True),
            ("nested/foo/bar", "/foo/bar", False),
            ("foo/bar", "/foo/**/bar", False),
            ("foo/nested/bar", "/foo/**/bar", True),
            ("foo1", "foo[[:digit:]]", True),
            ("foox", "foo[[:digit:]]", False),
            ("foo9", "foo[!0-9]", False),
            ("foox", "foo[!0-9]", True),
            ("foo/x", "foo?x", False),
            ("data/[raw]12", r"data/\[raw\]*", True),
            ("data/raw12", r"data/\[raw\]*", False),
            ("nested/cache/item", "cache/***", True),
            ("nested/caches/item", "cache/***", False),
        ]
        for relative, rule, expected in cases:
            with self.subTest(relative=relative, rule=rule):
                self.assertEqual(recovery.excluded(relative, [rule]), expected)

    def test_single_star_does_not_span_path_components(self) -> None:
        recovery = recovery_module()
        self.assertTrue(recovery.excluded("home/alex/cache/data", ["/home/*/cache"]))
        self.assertFalse(recovery.excluded("home/alex/nested/cache/data", ["/home/*/cache"]))

    def test_double_star_matches_nested_paths(self) -> None:
        recovery = recovery_module()
        self.assertTrue(recovery.excluded("home/alex/nested/cache/data", ["/home/**/cache"]))

    def test_directory_only_pattern_keeps_same_named_regular_file(self) -> None:
        recovery = recovery_module()
        self.assertTrue(recovery.excluded("home/alex/cache/item", ["cache/"]))
        self.assertFalse(recovery.excluded("home/alex/cache", ["cache/"], False))

    def test_unanchored_name_matches_each_directory_level(self) -> None:
        recovery = recovery_module()
        self.assertTrue(recovery.excluded("home/alex/cache/item", ["cache"]))
        self.assertTrue(recovery.excluded("cache/item", ["cache"]))
        self.assertFalse(recovery.excluded("home/alex/cached/item", ["cache"]))


class LinuxRestoreRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not sys.platform.startswith("linux"):
            if REQUIRE_LINUX:
                raise AssertionError("Linux integration was required but the runner is not Linux")
            raise unittest.SkipTest("Real rsync/ACL/xattr fixtures require Linux")
        required = ("bash", "rsync", "tar", "setfacl", "getfacl", "setfattr", "getfattr")
        missing = [program for program in required if not shutil.which(program)]
        if missing:
            message = "Missing Linux integration tools: " + ", ".join(missing)
            if REQUIRE_LINUX:
                raise AssertionError(message)
            raise unittest.SkipTest(message)

    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory(prefix="hostbackup-roundtrip-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = pathlib.Path(self.workspace.name).resolve()
        self.source = self.root / "source"
        self.copy = self.root / "copy"
        self.destination = self.root / "restore"
        for path in (self.source, self.copy, self.destination):
            path.mkdir()
        self.environment = os.environ.copy()
        self.environment.update(
            FIXTURE_ROOT=str(self.root), SOURCE=str(self.source),
            COPY=str(self.copy), DESTINATION=str(self.destination),
        )

    def bash(self, script: str) -> subprocess.CompletedProcess[str]:
        # There are no backend startup side effects and no destination at /.
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-s"],
            input="set -euo pipefail\n" + script,
            env=self.environment, cwd=self.root, text=True, capture_output=True, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def make_metadata_fixture(self) -> None:
        (self.source / "payload").write_bytes(b"HostBackup metadata fixture\n")
        os.chmod(self.source / "payload", 0o6750)
        os.link(self.source / "payload", self.source / "hardlink")
        (self.source / "symlink").symlink_to("payload")
        with (self.source / "sparse").open("wb") as output:
            output.seek(4 * 1024 * 1024)
            output.write(b"x")
        self.bash('setfacl -m u:65534:r-- "$SOURCE/payload"\nsetfattr -n user.hostbackup_test -v sample "$SOURCE/payload"\n')

    def assert_metadata_roundtrip(self, *, xattrs: bool) -> None:
        source = self.source / "payload"
        restored = self.destination / "payload"
        self.assertEqual(restored.read_bytes(), source.read_bytes())
        self.assertEqual(stat.S_IMODE(restored.stat().st_mode), stat.S_IMODE(source.stat().st_mode))
        self.assertEqual(restored.stat().st_uid, source.stat().st_uid)
        self.assertEqual(restored.stat().st_gid, source.stat().st_gid)
        self.assertEqual(restored.stat().st_ino, (self.destination / "hardlink").stat().st_ino)
        self.assertEqual(os.readlink(self.destination / "symlink"), "payload")
        sparse = (self.destination / "sparse").stat()
        self.assertEqual(sparse.st_size, 4 * 1024 * 1024 + 1)
        self.assertLess(sparse.st_blocks * 512, sparse.st_size)
        self.bash('diff <(getfacl -cn "$SOURCE/payload") <(getfacl -cn "$DESTINATION/payload")\n')
        if xattrs:
            self.assertEqual(os.getxattr(restored, "user.hostbackup_test"), b"sample")
        else:
            self.assertNotIn("user.hostbackup_test", os.listxattr(restored))

    def copy_and_restore(self, mode: str) -> None:
        self.environment["METADATA_MODE"] = mode
        self.bash(backend_function("rsync_metadata_options") + backend_function("rsync_destination") + r'''
declare -a backup_options=() restore_options=()
while IFS= read -r option; do backup_options+=("$option"); done < <(rsync_metadata_options "$METADATA_MODE" backup)
while IFS= read -r option; do restore_options+=("$option"); done < <(rsync_metadata_options "$METADATA_MODE" restore)
rsync "${backup_options[@]}" "$SOURCE/" "$(rsync_destination "$METADATA_MODE" "$COPY/")"
test -f "$COPY/payload" || { echo 'Backup payload missing despite rsync success' >&2; exit 1; }
cmp "$SOURCE/payload" "$COPY/payload"
if [ "$METADATA_MODE" = fake-super ]; then
  getfattr --only-values -n 'user.rsync.%stat' "$COPY/payload"
fi
rsync "${restore_options[@]}" "$COPY/" "$(rsync_destination "$METADATA_MODE" "$DESTINATION/")"
test -f "$DESTINATION/payload" || { echo 'Restore payload missing despite rsync success' >&2; exit 1; }
''')

    def test_native_strict_metadata_roundtrip(self) -> None:
        self.make_metadata_fixture()
        self.copy_and_restore("native-strict")
        self.assert_metadata_roundtrip(xattrs=True)

    def test_network_compatible_intentionally_omits_xattrs(self) -> None:
        self.make_metadata_fixture()
        self.copy_and_restore("network-compatible")
        self.assert_metadata_roundtrip(xattrs=False)

    def test_fake_super_decodes_preserved_metadata(self) -> None:
        self.make_metadata_fixture()
        self.copy_and_restore("fake-super")
        self.assert_metadata_roundtrip(xattrs=True)
        self.assertTrue(any(name.startswith("user.rsync.") for name in os.listxattr(self.copy / "payload")))
        self.assertFalse(any(name.startswith("user.rsync.") for name in os.listxattr(self.destination / "payload")))

    def test_fake_super_snapshot_and_python_restore_keep_exact_local_paths(self) -> None:
        self.make_metadata_fixture()
        name = "data with spaces 'quotes' $() [brackets] ;.txt"
        (self.source / name).write_text("literal pathname", encoding="utf-8")
        # A shell evaluation would create this sentinel; protocol arguments must
        # instead preserve this complete name as the destination directory.
        tricky = self.root / "snapshot '$(touch SHOULD_NOT_EXIST)' ; [literal]"
        tricky.mkdir()
        self.environment["SNAPSHOT"] = str(tricky)
        self.environment["METADATA_MODE"] = "fake-super"
        self.copy_and_restore("fake-super")
        self.bash(backend_function("rsync_metadata_options") + backend_function("rsync_destination") + r'''
declare -a options=()
while IFS= read -r option; do options+=("$option"); done < <(rsync_metadata_options fake-super backup)
rsync "${options[@]}" --link-dest="$COPY" "$SOURCE/" "$(rsync_destination fake-super "$SNAPSHOT/")"
''')
        self.assertEqual((self.copy / "payload").stat().st_ino, (tricky / "payload").stat().st_ino)
        self.assertEqual((tricky / name).read_text(encoding="utf-8"), "literal pathname")
        backup_root = self.root / "backups"
        backup = backup_root / "backup-1"
        backup.mkdir(parents=True)
        tricky.rename(backup / "rootfs")
        (backup / "rsync-excludes.txt").write_text("", encoding="utf-8")
        self.destination = self.root / "restored '$(touch SHOULD_NOT_EXIST)' ; [literal]"
        self.destination.mkdir()
        self.environment["DESTINATION"] = str(self.destination)
        command = [sys.executable, str(RECOVERY), "execute", "--backup", str(backup),
                   "--backup-root", str(backup_root), "--destination", str(self.destination), "--mode", "fake-super"]
        result = subprocess.run(command, cwd=self.root, text=True, capture_output=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_metadata_roundtrip(xattrs=True)
        self.assertEqual((self.destination / name).read_text(encoding="utf-8"), "literal pathname")
        partial = self.root / "partial '$(touch SHOULD_NOT_EXIST)' ; [literal]"
        partial.mkdir()
        result = subprocess.run(
            [sys.executable, str(RECOVERY), "files", "--backup", str(backup), "--backup-root", str(backup_root),
             "--destination", str(partial), "--mode", "fake-super", "--relative", name],
            cwd=self.root, text=True, capture_output=True, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folders = list(partial.glob("recovered-*"))
        self.assertEqual(len(folders), 1)
        self.assertEqual((folders[0] / name).read_text(encoding="utf-8"), "literal pathname")
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertFalse(any(ord(char) < 32 for path in self.root.iterdir() for char in path.name))

    def test_portable_archive_metadata_roundtrip(self) -> None:
        self.make_metadata_fixture()
        self.bash(backend_function("tar_metadata_options") + r'''
declare -a options=()
while IFS= read -r option; do options+=("$option"); done < <(tar_metadata_options)
tar "${options[@]}" -C "$SOURCE" -cpf "$FIXTURE_ROOT/rootfs.tar" .
tar "${options[@]}" --same-owner --same-permissions --delay-directory-restore -C "$DESTINATION" -xpf "$FIXTURE_ROOT/rootfs.tar"
''')
        self.assert_metadata_roundtrip(xattrs=True)

    def test_native_strict_preserves_file_capabilities(self) -> None:
        self.assert_privileged_roundtrip("native-strict")

    def test_fake_super_preserves_privileged_ownership_and_file_capabilities(self) -> None:
        self.assert_privileged_roundtrip("fake-super")

    def assert_privileged_roundtrip(self, mode: str) -> None:
        missing = [program for program in ("setcap", "getcap") if not shutil.which(program)]
        if missing:
            if REQUIRE_LINUX:
                self.fail("Missing capability tools: " + ", ".join(missing))
            self.skipTest("Capability tools are not available")
        privilege = []
        if os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo or subprocess.run(
                [sudo, "-n", "true"], capture_output=True, check=False, timeout=10,
            ).returncode:
                if REQUIRE_LINUX:
                    self.fail("Capability integration requires root or passwordless sudo")
                self.skipTest("Root or passwordless sudo is needed for security.capability")
            privilege = [sudo, "-n", "--"]
        (self.source / "payload").write_bytes(b"Non-executable capability test fixture\n")
        # Elevated operations can only touch the paths created by this fixture.
        assignments = "\n".join(
            f"{name}={shlex.quote(str(value))}" for name, value in (
                ("FIXTURE_ROOT", self.root), ("SOURCE", self.source),
                ("COPY", self.copy), ("DESTINATION", self.destination),
                ("METADATA_MODE", mode),
            )
        )
        script = "set -euo pipefail\n" + assignments + "\n" + backend_function("rsync_metadata_options") + backend_function("rsync_destination") + r'''
test "$FIXTURE_ROOT" != /
test "$SOURCE" = "$FIXTURE_ROOT/source"
test "$COPY" = "$FIXTURE_ROOT/copy"
test "$DESTINATION" = "$FIXTURE_ROOT/restore"
chown 1:1 "$SOURCE/payload"
setcap cap_net_bind_service=ep "$SOURCE/payload"
declare -a options=() restore_options=()
while IFS= read -r option; do options+=("$option"); done < <(rsync_metadata_options "$METADATA_MODE" backup)
while IFS= read -r option; do restore_options+=("$option"); done < <(rsync_metadata_options "$METADATA_MODE" restore)
rsync "${options[@]}" "$SOURCE/" "$(rsync_destination "$METADATA_MODE" "$COPY/")"
test -f "$COPY/payload"
rsync "${restore_options[@]}" "$COPY/" "$(rsync_destination "$METADATA_MODE" "$DESTINATION/")"
getcap "$DESTINATION/payload"
'''
        result = subprocess.run(
            privilege + ["bash", "--noprofile", "--norc", "-s"], input=script,
            cwd=self.root, text=True, capture_output=True, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cap_net_bind_service=ep", result.stdout)
        self.assertEqual((self.destination / "payload").stat().st_uid, 1)
        self.assertEqual((self.destination / "payload").stat().st_gid, 1)
        self.assertEqual(
            os.getxattr(self.destination / "payload", "security.capability"),
            os.getxattr(self.source / "payload", "security.capability"),
        )

    def test_rsync_delete_preserves_saved_exclusions(self) -> None:
        backup_root = self.root / "backups"
        backup = backup_root / "backup-1"
        backup.mkdir(parents=True)
        (backup / "rsync-excludes.txt").write_text("/home/private\n", encoding="utf-8", newline="\n")
        source = backup / "rootfs"
        self.source.rename(source)
        self.source = source
        (self.source / "home").mkdir()
        (self.source / "home" / "included").write_text("restored value", encoding="utf-8")
        private = self.destination / "home" / "private"
        private.mkdir(parents=True)
        (private / "keep-me").write_text("original excluded value", encoding="utf-8")
        extra = self.destination / "home" / "obsolete"
        extra.write_text("obsolete included file", encoding="utf-8")
        command = [sys.executable, str(RECOVERY), "execute", "--backup", str(backup),
                   "--backup-root", str(backup_root), "--destination", str(self.destination)]
        preview = subprocess.run(command + ["--dry-run"], text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertTrue(extra.exists(), "Dry-run must not delete files")
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((private / "keep-me").read_text(encoding="utf-8"), "original excluded value")
        self.assertEqual((self.destination / "home" / "included").read_text(encoding="utf-8"), "restored value")
        self.assertFalse(extra.exists())
        self.assertIn("obsolete", preview.stdout)
        self.assertNotIn("private/keep-me", preview.stdout)

    def test_portable_restore_preserves_excluded_and_protected_files(self) -> None:
        backup_root = self.root / "backups"
        backup = backup_root / "backup-1"
        backup.mkdir(parents=True)
        (backup / "rsync-excludes.txt").write_text("/home/private\n", encoding="utf-8", newline="\n")
        protected = "opt/loxberry/config/plugins/loxberryhostbackup/config.json"
        for relative in ("home/private/keep-me", protected, "etc/settings"):
            original = self.source / relative
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_text("archive value", encoding="utf-8")
        for relative in ("home/private/keep-me", protected):
            existing = self.destination / relative
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("keep existing value", encoding="utf-8")
        with tarfile.open(backup / "rootfs.tar", "w", format=tarfile.PAX_FORMAT) as archive:
            archive.add(self.source, arcname=".")
        command = [sys.executable, str(RECOVERY), "execute", "--backup", str(backup),
                   "--backup-root", str(backup_root), "--destination", str(self.destination),
                   "--storage-format", "portable-tar", "--mode", "portable-archive",
                   "--protect", "/opt/loxberry/config/plugins/loxberryhostbackup"]
        preview = subprocess.run(command + ["--dry-run"], text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertFalse((self.destination / "etc" / "settings").exists())
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.destination / "etc" / "settings").read_text(encoding="utf-8"), "archive value")
        for relative in ("home/private/keep-me", protected):
            self.assertEqual((self.destination / relative).read_text(encoding="utf-8"), "keep existing value")

    def test_portable_mapped_volume_handles_mixed_dot_prefixes_and_links(self) -> None:
        backup_root = self.root / "backups"
        backup = backup_root / "backup-1"
        backup.mkdir(parents=True)
        volume = "media/data[1],set"
        (backup / "rsync-excludes.txt").write_text("/home/private\n", encoding="utf-8", newline="\n")
        (backup / "source-mounts.json").write_text(json.dumps([{"target": "/" + volume}]), encoding="utf-8")
        mapped = self.destination / "data"
        mapped.mkdir()
        # This is an unprivileged path/link transformation test. Synthetic tar
        # entries must have the current fixture's owner, including directories
        # and links; privileged metadata roundtrips are covered separately.
        owner = self.root.stat()

        def fixture_member(name):
            member = tarfile.TarInfo(name)
            member.uid, member.gid = owner.st_uid, owner.st_gid
            return member

        with tarfile.open(backup / "rootfs.tar", "w", format=tarfile.PAX_FORMAT) as archive:
            for directory in ("media", volume):
                member = fixture_member(directory)
                member.type = tarfile.DIRTYPE
                # TarInfo defaults to 0644 even for directories. Give the
                # synthetic directory searchable permissions like a real source.
                member.mode = 0o750
                archive.addfile(member)
            for name, content in (("./" + volume + "/a.txt", b"alpha"), (volume + "/b.txt", b"beta")):
                member = fixture_member(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            link = fixture_member(volume + "/hardlink")
            link.type = tarfile.LNKTYPE
            link.linkname = "./" + volume + "/a.txt"
            archive.addfile(link)
            symlink = fixture_member("./" + volume + "/symlink")
            symlink.type = tarfile.SYMTYPE
            symlink.linkname = "a.txt"
            archive.addfile(symlink)
        result = subprocess.run(
            [sys.executable, str(RECOVERY), "execute", "--backup", str(backup),
             "--backup-root", str(backup_root), "--destination", str(self.destination),
             "--storage-format", "portable-tar", "--mode", "portable-archive",
             "--map-json", json.dumps([{"source": "/" + volume, "destination": str(mapped)}])],
            text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((mapped / "a.txt").read_bytes(), b"alpha")
        self.assertEqual((mapped / "b.txt").read_bytes(), b"beta")
        self.assertEqual(stat.S_IMODE(mapped.stat().st_mode), 0o750)
        self.assertEqual((mapped / "a.txt").stat().st_ino, (mapped / "hardlink").stat().st_ino)
        restored = (mapped / "a.txt").stat()
        self.assertEqual((restored.st_uid, restored.st_gid), (owner.st_uid, owner.st_gid))
        self.assertEqual(os.readlink(mapped / "symlink"), "a.txt")
        self.assertFalse((self.destination / volume / "a.txt").exists())


if __name__ == "__main__":
    unittest.main()
