#!/usr/bin/env python3
import io
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "bin" / "validate-import-archive.py"
LIMIT = str(16 * 1024 * 1024)
SPEC = importlib.util.spec_from_file_location("archive_validator", VALIDATOR)
VALIDATOR_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR_MODULE)


def add_bytes(tf: tarfile.TarFile, name: str, data: bytes = b"x") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def add_dir(tf: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    tf.addfile(info)


class ArchiveValidatorTests(unittest.TestCase):
    def run_validator(self, archive: pathlib.Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *extra, str(archive), LIMIT],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

    def make_outer(self, mutate=None, portable: bytes | None = None) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        tmp.close()
        path = pathlib.Path(tmp.name)
        with tarfile.open(path, "w:gz") as tf:
            add_dir(tf, "backup-1")
            add_bytes(tf, "backup-1/manifest.json", json.dumps({"backup_id": "backup-1"}).encode())
            add_bytes(tf, "backup-1/backup-validation.json", b"{}")
            if portable is None:
                add_dir(tf, "backup-1/rootfs")
                add_dir(tf, "backup-1/rootfs/etc")
                add_dir(tf, "backup-1/rootfs/opt/loxberry")
                add_bytes(tf, "backup-1/rootfs/etc/hosts", b"127.0.0.1 localhost\n")
                add_bytes(tf, "backup-1/rootfs/opt/loxberry/system.txt", b"fixture\n")
            else:
                add_bytes(tf, "backup-1/rootfs.tar", portable)
            if mutate:
                mutate(tf)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def make_rootfs_tar(self, mutate=None) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
        tmp.close()
        path = pathlib.Path(tmp.name)
        with tarfile.open(path, "w") as tf:
            add_dir(tf, "./etc")
            add_bytes(tf, "./etc/hosts")
            add_dir(tf, "./opt/loxberry")
            add_bytes(tf, "./opt/loxberry/system.txt")
            if mutate:
                mutate(tf)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_valid_directory_archive(self) -> None:
        result = self.run_validator(self.make_outer())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "backup-1")

    def test_json_mode_reports_expanded_size(self) -> None:
        result = self.run_validator(self.make_outer(), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["backup_id"], "backup-1")
        self.assertGreater(payload["expanded_size"], 0)

    def test_rejects_path_traversal(self) -> None:
        result = self.run_validator(
            self.make_outer(lambda tf: add_bytes(tf, "backup-1/../../escape"))
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe paths", result.stderr)

    def test_rejects_symlink_write_through(self) -> None:
        def mutate(tf: tarfile.TarFile) -> None:
            link = tarfile.TarInfo("backup-1/rootfs/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/tmp"
            tf.addfile(link)
            add_bytes(tf, "backup-1/rootfs/link/payload")

        result = self.run_validator(self.make_outer(mutate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)

    def test_rejects_escaping_hardlink(self) -> None:
        def mutate(tf: tarfile.TarFile) -> None:
            link = tarfile.TarInfo("backup-1/rootfs/hardlink")
            link.type = tarfile.LNKTYPE
            link.linkname = "../outside"
            tf.addfile(link)

        result = self.run_validator(self.make_outer(mutate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe paths", result.stderr)

    def test_rejects_duplicate_member(self) -> None:
        result = self.run_validator(
            self.make_outer(lambda tf: add_bytes(tf, "backup-1/manifest.json", b"duplicate"))
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate", result.stderr)

    def test_rejects_symlink_control_file(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        tmp.close()
        archive = pathlib.Path(tmp.name)
        self.addCleanup(archive.unlink, missing_ok=True)
        with tarfile.open(archive, "w:gz") as tf:
            add_dir(tf, "backup-1")
            manifest = tarfile.TarInfo("backup-1/manifest.json")
            manifest.type = tarfile.SYMTYPE
            manifest.linkname = "/etc/passwd"
            tf.addfile(manifest)
            add_bytes(tf, "backup-1/backup-validation.json", b"{}")
            add_dir(tf, "backup-1/rootfs")
        result = self.run_validator(archive)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("control files must be regular", result.stderr)

    def test_valid_portable_rootfs(self) -> None:
        rootfs = self.make_rootfs_tar()
        inner = self.run_validator(rootfs, "--rootfs-tar")
        self.assertEqual(inner.returncode, 0, inner.stderr)
        outer = self.run_validator(self.make_outer(portable=rootfs.read_bytes()))
        self.assertEqual(outer.returncode, 0, outer.stderr)

    def test_rejects_unsafe_portable_rootfs(self) -> None:
        def mutate(tf: tarfile.TarFile) -> None:
            link = tarfile.TarInfo("./etc/unsafe")
            link.type = tarfile.SYMTYPE
            link.linkname = "/tmp"
            tf.addfile(link)
            add_bytes(tf, "./etc/unsafe/payload")

        result = self.run_validator(self.make_rootfs_tar(mutate), "--rootfs-tar")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)

    def test_rejects_all_linked_sidecars_and_preserves_outside_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sentinel = pathlib.Path(temporary) / "sentinel"
            sentinel.write_bytes(b"must not change")
            for name in ("import-source.sha256", ".loxberry-hostbackup-backup",
                         "rsync-excludes.txt", "import-validation.json", "restart.done"):
                for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    with self.subTest(name=name, kind=kind):
                        def mutate(tf):
                            link = tarfile.TarInfo(f"backup-1/{name}")
                            link.type = kind
                            link.linkname = str(sentinel) if kind == tarfile.SYMTYPE else "backup-1/rootfs/etc/hosts"
                            tf.addfile(link)
                        result = self.run_validator(self.make_outer(mutate))
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("control files must be regular", result.stderr)
                        self.assertEqual(sentinel.read_bytes(), b"must not change")

    def test_accepts_regular_generated_sidecar_for_reexport(self) -> None:
        result = self.run_validator(self.make_outer(
            lambda tf: add_bytes(tf, "backup-1/import-source.sha256", b"a" * 64 + b"  original.tar.gz\n")
        ))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_child_before_symlink_parent(self) -> None:
        def mutate(tf):
            add_bytes(tf, "backup-1/rootfs/link/payload")
            link = tarfile.TarInfo("backup-1/rootfs/link")
            link.type, link.linkname = tarfile.SYMTYPE, "/tmp"
            tf.addfile(link)
        result = self.run_validator(self.make_outer(mutate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)

    def test_rejects_hardlink_to_symlink(self) -> None:
        def mutate(tf):
            link = tarfile.TarInfo("backup-1/rootfs/link")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(link)
            hardlink = tarfile.TarInfo("backup-1/rootfs/hardlink")
            hardlink.type, hardlink.linkname = tarfile.LNKTYPE, "backup-1/rootfs/link"
            tf.addfile(hardlink)
        result = self.run_validator(self.make_outer(mutate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must refer to a regular file", result.stderr)

    def test_prefix_validation_scales_with_entries(self) -> None:
        def members():
            for number in range(20000):
                info = tarfile.TarInfo(f"backup-1/rootfs/data/file-{number}")
                info.size = 1
                yield info
            for number in range(2000):
                info = tarfile.TarInfo(f"backup-1/rootfs/links/link-{number}")
                info.type, info.linkname = tarfile.SYMTYPE, "/usr/bin/example"
                yield info
        started = time.monotonic()
        result = VALIDATOR_MODULE.validate_members(members(), int(LIMIT), "backup-1")
        self.assertEqual(len(result["symlinks"]), 2000)
        # The previous per-symlink full scan took ~19 s for this fixture.
        self.assertLess(time.monotonic() - started, 8.0)

    def make_backup_directory(self, portable=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = pathlib.Path(temporary.name) / "backup-1"
        directory.mkdir()
        if portable:
            container = self.make_rootfs_tar()
            (directory / "rootfs.tar").write_bytes(container.read_bytes())
            with tarfile.open(container) as tf:
                count = len(tf.getmembers())
        else:
            (directory / "rootfs/etc").mkdir(parents=True)
            (directory / "rootfs/opt/loxberry").mkdir(parents=True)
            (directory / "rootfs/etc/hosts").write_bytes(b"127.0.0.1 localhost\n")
            (directory / "rootfs/opt/loxberry/system.txt").write_bytes(b"fixture\n")
            count = 2
        manifest = {
            "schema_version": 2, "backup_id": directory.name, "status": "complete",
            "size_bytes": 10240, "files_count": count,
            "backup": {"mode": "full", "storage_format": "portable-tar" if portable else "directory"},
            "metadata": {"mode": "portable-archive" if portable else "native-strict"},
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "backup-validation.json").write_text('{"status":"ok"}', encoding="utf-8")
        return directory

    def test_locally_inspects_real_directory_payload(self) -> None:
        result = self.run_validator(self.make_backup_directory(), "--backup-dir", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["validation_source"], "local-import-inspection")
        self.assertEqual(report["files_count"], 2)
        self.assertEqual(report["status"], "warning")
        self.assertGreater(report["logical_bytes"], 0)
        self.assertFalse(report["content_hashes_verified"])
        self.assertFalse(report["restore_tested"])

    def test_empty_data_cannot_inherit_source_ok_status(self) -> None:
        directory = self.make_backup_directory()
        for path in directory.glob("rootfs/**/*"):
            if path.is_file():
                path.unlink()
        result = self.run_validator(directory, "--backup-dir")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no regular file content", result.stderr)

    def test_missing_file_is_rejected_by_manifest_count(self) -> None:
        directory = self.make_backup_directory()
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files_count"] = 3
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_validator(directory, "--backup-dir")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("file count mismatch", result.stderr)

    def test_rejects_invalid_schema_and_profile_format(self) -> None:
        for change in ({"schema_version": 999}, {"schema_version": True},
                       {"files_count": "2"}, {"backup_id": "different"},
                       {"metadata": {"mode": "unknown"}},
                       {"metadata": {"mode": "portable-archive"}}):
            with self.subTest(change=change):
                directory = self.make_backup_directory()
                path = directory / "manifest.json"
                manifest = json.loads(path.read_text())
                manifest.update(change)
                path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertNotEqual(self.run_validator(directory, "--backup-dir").returncode, 0)

    def test_locally_inspects_portable_member_count(self) -> None:
        result = self.run_validator(self.make_backup_directory(portable=True), "--backup-dir")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["files_count"], 2)
        self.assertEqual(report["manifest_count"], 4)

    def test_rejects_truncated_portable_container(self) -> None:
        container = self.make_rootfs_tar()
        container.write_bytes(container.read_bytes()[:1300])
        result = self.run_validator(container, "--rootfs-tar")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("truncated", result.stderr)

    def test_valid_portable_sparse_data_uses_physical_extent_size(self) -> None:
        def mutate(tf):
            info = tarfile.TarInfo("./var/lib/sparse-data")
            info.size = 1
            info.pax_headers = {"GNU.sparse.map": "0,1", "GNU.sparse.size": "1048576"}
            tf.addfile(info, io.BytesIO(b"x"))
        container = self.make_rootfs_tar(mutate)
        with tarfile.open(container) as tf:
            member = tf.getmember("./var/lib/sparse-data")
            self.assertEqual(member.size, 1048576)
            self.assertEqual(member.sparse, [(0, 1)])
        result = self.run_validator(container, "--rootfs-tar")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_locally_hardlinked_control_file(self) -> None:
        directory = self.make_backup_directory()
        os.link(directory / "manifest.json", directory / "import-source.sha256")
        result = self.run_validator(directory, "--backup-dir")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsafe control file", result.stderr)

    def test_legacy_metadata_uncertainty_remains_visible(self) -> None:
        directory = self.make_backup_directory()
        path = directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = 1
        del manifest["metadata"]
        del manifest["backup"]["storage_format"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_validator(directory, "--backup-dir")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["metadata_mode"], "legacy-unknown")


if __name__ == "__main__":
    unittest.main()
