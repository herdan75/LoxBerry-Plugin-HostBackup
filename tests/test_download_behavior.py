"""Validate download bytes/headers and the root-to-CGI streaming boundary."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/hostbackup-download.py"
spec = importlib.util.spec_from_file_location("hostbackup_download_test", HELPER)
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


class DownloadBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-download-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "backup-test.tar.gz"
        self.payload = b"archive payload\x00\xff" * 2048
        self.archive.write_bytes(self.payload)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_bytes(b'{"backup_id":"backup-test","status":"complete"}\n')
        self.checksum = self.root / "backup-test.tar.gz.sha256"
        digest = hashlib.sha256(self.payload).hexdigest()
        self.checksum.write_text(digest + "  " + self.archive.name + "\n", encoding="ascii", newline="\n")
        self.descriptor = self.root / "backup-test.tar.gz.json"
        self.descriptor.write_text(json.dumps({"backup_id": "backup-test", "archive": self.archive.name,
                                               "sha256": digest, "manifest_sha256": hashlib.sha256(self.manifest.read_bytes()).hexdigest()}))

    def stream(self, sink=None):
        sink = sink if sink is not None else io.BytesIO()
        with mock.patch.object(download.sys, "stdout", SimpleNamespace(buffer=sink)):
            download.stream(self.archive, self.archive.name, "export", self.descriptor, self.manifest, self.checksum)
        return sink.getvalue()

    def assert_rejected_before_headers(self):
        sink = io.BytesIO()
        with self.assertRaises((ValueError, OSError)):
            self.stream(sink)
        self.assertEqual(sink.getvalue(), b"", "A failed validation must emit no success HTTP headers")

    def test_valid_export_emits_matching_content_length_and_binary_body(self):
        headers, body = self.stream().split(b"\r\n\r\n", 1)
        self.assertIn(b"Content-Type: application/gzip", headers)
        self.assertIn(f"Content-Length: {len(self.payload)}".encode(), headers)
        self.assertEqual(body, self.payload)

    def test_hash_and_stream_use_one_open_file_description(self):
        original = download.open_regular
        calls = []
        def tracked(path):
            calls.append(Path(path))
            return original(path)
        with mock.patch.object(download, "open_regular", side_effect=tracked):
            body = self.stream().split(b"\r\n\r\n", 1)[1]
        self.assertEqual(calls.count(self.archive), 1)
        self.assertEqual(body, self.payload)

    @unittest.skipUnless(os.name == "posix", "Replacing an open file requires POSIX rename semantics")
    def test_path_replacement_after_headers_does_not_change_opened_download(self):
        archive = self.archive
        replacement = self.root / "replacement"
        replacement.write_bytes(b"different file")
        class ReplaceAfterHeaders(io.BytesIO):
            def write(self, content):
                if self.tell() == 0:
                    os.replace(replacement, archive)
                return super().write(content)
        body = self.stream(ReplaceAfterHeaders()).split(b"\r\n\r\n", 1)[1]
        self.assertEqual(body, self.payload)
        self.assertEqual(self.archive.read_bytes(), b"different file")

    def test_changed_archive_checksum_is_rejected_before_headers(self):
        self.archive.write_bytes(b"changed data")
        self.assert_rejected_before_headers()

    def test_stale_manifest_descriptor_is_rejected_before_headers(self):
        self.manifest.write_bytes(b'{"backup_id":"backup-test","status":"changed"}\n')
        self.assert_rejected_before_headers()

    def test_nonobject_descriptor_is_rejected_without_traceback_or_headers(self):
        self.descriptor.write_text("[]")
        self.assert_rejected_before_headers()

    def test_archive_change_during_hash_is_detected(self):
        original = hashlib.file_digest
        def change_after_digest(handle, algorithm):
            digest = original(handle, algorithm)
            previous = self.archive.stat()
            os.utime(self.archive, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1000000000))
            return digest
        with mock.patch.object(download.hashlib, "file_digest", side_effect=change_after_digest):
            self.assert_rejected_before_headers()

    def test_symlink_archive_and_parent_are_rejected(self):
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(ValueError):
            download.open_regular(alias / self.archive.name)
        link = self.root / "linked.tar.gz"
        link.symlink_to(self.archive)
        with self.assertRaises(ValueError):
            download.open_regular(link)

    @unittest.skipUnless(os.name == "posix", "FIFO safety requires POSIX")
    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        result = subprocess.run([sys.executable, str(HELPER), "log", str(fifo), "backup-test.log"], capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_active_log_download_is_bounded_to_initial_size(self):
        path = self.root / "backup-test.log"
        original = b"first line\n"
        path.write_bytes(original)
        class GrowingLog(io.BytesIO):
            def write(self, content):
                if self.tell() == 0:
                    with path.open("ab") as log: log.write(b"new line\n")
                return super().write(content)
        sink = GrowingLog()
        with mock.patch.object(download.sys, "stdout", SimpleNamespace(buffer=sink)):
            download.stream(path, path.name, "log")
        headers, body = sink.getvalue().split(b"\r\n\r\n", 1)
        self.assertEqual(body, original)
        self.assertIn(b"Content-Length: 11", headers)

    @unittest.skipUnless(sys.platform == "linux", "Root/web-user permission boundary requires Linux")
    def test_root_only_export_can_be_streamed_without_making_it_web_readable(self):
        elevation = []
        if os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo or subprocess.run([sudo, "-n", "true"], capture_output=True).returncode:
                if os.environ.get("HOSTBACKUP_REQUIRE_LINUX_INTEGRATION") == "1":
                    self.fail("Root download fixture requires passwordless sudo")
                self.skipTest("Root download fixture requires passwordless sudo")
            elevation = [sudo, "-n", "--"]
        paths = [self.archive, self.descriptor, self.checksum, self.manifest]
        script = 'import os,pathlib,sys; base=pathlib.Path(sys.argv[1]).resolve(); assert str(base)!="/"; paths=[pathlib.Path(p) for p in sys.argv[2:]]; assert all(p.parent.resolve()==base for p in paths); [(os.chown(p,0,0),os.chmod(p,0o600)) for p in paths]'
        result = subprocess.run(elevation + [sys.executable, "-c", script, str(self.root), *map(str, paths)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        if os.geteuid() != 0:
            with self.assertRaises(PermissionError): self.archive.read_bytes()
        command = [sys.executable, str(HELPER), "export", str(self.archive), self.archive.name,
                   "--descriptor", str(self.descriptor), "--manifest", str(self.manifest), "--checksum", str(self.checksum)]
        result = subprocess.run(elevation + command, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(b"\r\n\r\n", 1)[1], self.payload)
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)


class CgiDownloadRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hostbackup-cgi-download-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.perl = shutil.which("perl")
        if not self.perl and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/perl.exe"
            self.perl = str(candidate) if candidate.exists() else None
        if not self.perl:
            self.skipTest("Perl unavailable for actual CGI relay behavior")

    def relay(self, backend_body):
        source = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
        match = re.search(r"^sub relay_backend_download \{\n.*?^\}\n", source, re.M | re.S)
        self.assertIsNotNone(match, "Privileged CGI relay is missing")
        sudo = self.root / "sudo"
        sudo.write_text('#!/bin/bash\n[ "$1" = -n ] && shift\nexec "$@"\n', newline="\n")
        sudo.chmod(0o755)
        backend = self.root / "backend"
        backend.write_text("#!/bin/bash\n" + backend_body + "\n", newline="\n")
        backend.chmod(0o755)
        prefix = 'use strict; use warnings; my $backend=$ENV{TEST_DOWNLOAD_BACKEND}; sub reject_request { my ($status,$text)=@_; print "Status: $status\\r\\nContent-Type: text/plain\\r\\n\\r\\n$text"; exit; }\n'
        result = subprocess.run([self.perl, "-"], input=(prefix + match[0] + '\nrelay_backend_download("fixture");\n').encode(),
                                env={**os.environ, "PATH": str(self.root) + os.pathsep + os.environ.get("PATH", ""), "TEST_DOWNLOAD_BACKEND": backend.as_posix()},
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout

    def test_header_and_binary_body_are_relayed_exactly_once(self):
        actual = self.relay("printf 'Content-Type: application/octet-stream\\r\\nContent-Length: 5\\r\\n\\r\\na\\x00b\\r\\n'")
        self.assertEqual(actual, b"Content-Type: application/octet-stream\r\nContent-Length: 5\r\n\r\na\x00b\r\n")

    def test_no_success_headers_when_backend_fails_before_streaming(self):
        actual = self.relay("exit 18")
        self.assertTrue(actual.startswith(b"Status: 409 Conflict"), actual)
        self.assertNotIn(b"Content-Type: application/gzip", actual)

    def test_diagnostic_output_cannot_be_mistaken_for_download_headers(self):
        actual = self.relay("printf 'unsafe diagnostic\\nContent-Type: application/gzip\\r\\n\\r\\nsecret'")
        self.assertTrue(actual.startswith(b"Status: 409 Conflict"), actual)
        self.assertNotIn(b"secret", actual)

    def test_overlong_unterminated_header_is_rejected(self):
        actual = self.relay("printf 'Content-Type: '; printf '%20000s' x; printf '\\r\\n\\r\\nsecret'")
        self.assertTrue(actual.startswith(b"Status: 409 Conflict"), actual)
        self.assertNotIn(b"secret", actual)


if __name__ == "__main__":
    unittest.main()
