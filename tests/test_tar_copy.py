"""Strict archive exit handling; no system backup or real service is started."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hostbackup_tar", ROOT / "bin/hostbackup-tar.py")
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


class TarCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.counter = 0
        self.name = b"./opt/loxberry/log/plugins/example"
        self.metadata = {"device": 1, "inode": 27, "uid": 1001, "gid": 1001, "mode": 0o2750,
                         "xattrs": {"user.example": b"value"}}
        self.before = {self.name: self.metadata}

    def warning(self, name=None):
        return b"tar: " + archive.c_quote(name or self.name) + b": file changed as we read it\n"

    def run_copy(self, status=1, diagnostic=None, metadata=None, header_error=None, before=None):
        self.counter += 1
        state = self.base / ("state-%d" % self.counter)
        state.mkdir()
        commands = []

        def tar(argv, **kwargs):
            commands.append((argv, kwargs))
            kwargs["stderr"].write(self.warning() if diagnostic is None else diagnostic)
            return SimpleNamespace(returncode=status)

        with patch.object(archive, "directory_receipts", return_value=self.before if before is None else before), \
                patch.object(archive, "directory_fingerprint", return_value=self.metadata if metadata is None else metadata,
                             side_effect=metadata if isinstance(metadata, list) else None), \
                patch.object(archive.headers, "verify_directory_headers", side_effect=header_error) as verifier, \
                patch.object(archive.subprocess, "run", side_effect=tar), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = archive.create_archive(state / "rootfs.tar", self.base / "files.nul", {}, state,
                                            source_root=self.base / "source")
        self.assertEqual(Path(result["stderr_path"]).read_bytes(), self.warning() if diagnostic is None else diagnostic)
        return result, output.getvalue(), verifier, commands

    def test_verified_directory_only_churn_keeps_raw_status_and_is_success(self):
        result, output, verifier, _ = self.run_copy()
        self.assertEqual((result["raw_exit_status"], result["effective_exit_status"]), (1, 0))
        self.assertEqual(result["classification"], "verified_runtime_directory_churn")
        self.assertEqual(result["directory_metadata_verified_count"], 1)
        self.assertIn("unveraendert geprueft", output)
        self.assertNotIn("file changed as we read it", output)
        verifier.assert_called_once()
        self.assertEqual(verifier.call_args.args[1], {self.name.decode(): self.metadata})

    def test_clean_copy_does_not_scan_archive_headers(self):
        result, _, verifier, _ = self.run_copy(status=0, diagnostic=b"")
        self.assertEqual(result["classification"], "clean")
        self.assertEqual(result["effective_exit_status"], 0)
        verifier.assert_not_called()

    def test_non_one_status_and_signals_never_become_success(self):
        for code, expected in ((2, 2), (24, 24), (127, 127), (-15, 143)):
            with self.subTest(code=code):
                result, output, verifier, _ = self.run_copy(status=code)
                self.assertEqual(result["effective_exit_status"], expected)
                self.assertIn("file changed as we read it", output)
                verifier.assert_not_called()

    def test_mixed_unknown_missing_regular_and_truncated_diagnostics_remain_errors(self):
        for diagnostic in (self.warning() + self.warning(b"./var/lib/database"),
                           self.warning() + b"tar: Cannot open: Permission denied\n",
                           self.warning() + b"tar: Exiting with failure status due to previous errors\n",
                           self.warning()[:-1], b"", b"x" * (archive.MAX_LINE + 1)):
            with self.subTest(diagnostic=diagnostic[:70]):
                result, _, verifier, _ = self.run_copy(diagnostic=diagnostic)
                self.assertEqual(result["effective_exit_status"], 1)
                verifier.assert_not_called()

    def test_security_metadata_change_or_archive_header_mismatch_is_not_accepted(self):
        for changed in ({**self.metadata, "mode": 0o777}, {**self.metadata, "uid": 0},
                        {**self.metadata, "gid": 0}, {**self.metadata, "inode": 28},
                        {**self.metadata, "device": 2}, {**self.metadata, "xattrs": {}}):
            with self.subTest(changed=changed):
                result, _, verifier, _ = self.run_copy(metadata=changed)
                self.assertEqual(result["effective_exit_status"], 1)
                verifier.assert_not_called()
        result, _, _, _ = self.run_copy(header_error=ValueError("temporary mode change preserved in archive"))
        self.assertEqual(result["effective_exit_status"], 1)

    def test_metadata_change_while_reading_archive_headers_still_fails(self):
        result, _, verifier, _ = self.run_copy(metadata=[self.metadata, {**self.metadata, "mode": 0o777}])
        verifier.assert_called_once()
        self.assertEqual(result["effective_exit_status"], 1)

    def test_diagnostic_budget_cannot_turn_truncated_evidence_into_success(self):
        with patch.object(archive, "MAX_DIAGNOSTICS", len(self.warning())):
            result, _, verifier, _ = self.run_copy(diagnostic=self.warning() * 2)
        self.assertEqual(result["effective_exit_status"], 1)
        verifier.assert_not_called()

    def test_no_eligible_directories_means_strict_tar_even_for_plausible_warning(self):
        result, _, verifier, _ = self.run_copy(before={})
        self.assertEqual(result["effective_exit_status"], 1)
        verifier.assert_not_called()

    def test_c_quoted_names_cannot_inject_a_second_diagnostic(self):
        hostile = b'./opt/loxberry/log/plugins/a"\\:\n' + self.warning()
        quoted = archive.c_quote(hostile)
        self.assertNotIn(b"\n", quoted)
        self.assertIn(b"\\n", quoted)
        self.assertIn(b'\\"', quoted)
        self.assertIn(b"\\\\", quoted)
        result, _, verifier, _ = self.run_copy(diagnostic=self.warning(hostile))
        self.assertEqual(result["effective_exit_status"], 1)
        verifier.assert_not_called()

    def test_tar_options_cannot_weaken_strict_copy_and_quoting_is_fixed(self):
        with patch.dict(os.environ, {"TAR_OPTIONS": "--ignore-failed-read --warning=none", "QUOTING_STYLE": "literal", "LC_ALL": "de_CH.UTF-8"}):
            _, _, _, commands = self.run_copy(status=0, diagnostic=b"")
        argv, options = commands[0]
        self.assertNotIn("TAR_OPTIONS", options["env"])
        self.assertNotIn("QUOTING_STYLE", options["env"])
        self.assertEqual(options["env"]["LC_ALL"], "C")
        for flag in ("--format=pax", "--acls", "--xattrs", "--xattrs-include=*", "--sparse", "--quoting-style=c", "--no-recursion", "--null", "--verbatim-files-from"):
            self.assertIn(flag, argv)
        self.assertNotIn("--ignore-failed-read", argv)

    def test_frozen_byte_list_is_literal_and_requires_complete_terminator(self):
        path = self.base / "files"
        expected = [b".", b"./#file", b"./;file", b"./-file", b"./line\nname", b"./nonutf8-\xff"]
        path.write_bytes(b"\0".join(expected) + b"\0")
        self.assertEqual(list(archive.file_entries(path)), expected)
        path.write_bytes(b"./unterminated")
        with self.assertRaises(ValueError):
            list(archive.file_entries(path))

    def test_opt_in_unknown_policy_and_explicit_overrides_have_no_eligible_directory(self):
        path = self.base / "files"
        path.write_bytes(self.name + b"\0")
        content = {"version": 1, "enabled": True, "include_runtime_logs": False, "loxberry_home": "/opt/loxberry"}
        for changed in ({"enabled": False}, {"include_runtime_logs": True}, {"version": 900}):
            with patch.object(archive, "directory_fingerprint", return_value=self.metadata) as fingerprint:
                self.assertEqual(archive.directory_receipts(path, {"runtime_content_policy": {**content, **changed}}, self.base), {})
                fingerprint.assert_not_called()
        for logical in ("/opt/loxberry/log/plugins", "/opt/loxberry/log/plugins/example"):
            with patch.object(archive, "directory_fingerprint", return_value=self.metadata) as fingerprint:
                report = {"runtime_content_policy": content, "selection": {"overrides": {logical: True}}}
                self.assertEqual(archive.directory_receipts(path, report, self.base), {})
                fingerprint.assert_not_called()

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "listxattr"), "Linux descriptor/xattr proof")
    def test_real_directory_fingerprint_rejects_replacement_and_symlink_ancestors(self):
        path = self.base / "opt/loxberry/log/plugins/example"
        path.mkdir(parents=True)
        path.chmod(0o2750)
        os.setxattr(path, "user.test", b"metadata")
        logical = "/opt/loxberry/log/plugins/example"
        receipt = archive.directory_fingerprint(logical, self.base)
        self.assertEqual(receipt["mode"], 0o2750)
        self.assertEqual(receipt["xattrs"]["user.test"], b"metadata")
        (path / "rotating.log").write_bytes(b"logs")
        self.assertEqual(archive.directory_fingerprint(logical, self.base), receipt)
        path.rename(path.with_name("old"))
        path.mkdir()
        self.assertNotEqual(archive.directory_fingerprint(logical, self.base), receipt)
        path.rmdir()
        path.symlink_to(path.with_name("old"), target_is_directory=True)
        self.assertIsNone(archive.directory_fingerprint(logical, self.base))
        path.unlink()
        path.parent.rename(path.parent.with_name("real"))
        path.parent.symlink_to(path.parent.with_name("real"), target_is_directory=True)
        self.assertIsNone(archive.directory_fingerprint(logical, self.base))


if __name__ == "__main__":
    unittest.main()
