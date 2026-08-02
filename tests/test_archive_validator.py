#!/usr/bin/env python3
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "bin" / "validate-import-archive.py"
LIMIT = str(16 * 1024 * 1024)


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
        self.assertIn("missing rootfs, manifest or validation", result.stderr)

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


if __name__ == "__main__":
    unittest.main()
