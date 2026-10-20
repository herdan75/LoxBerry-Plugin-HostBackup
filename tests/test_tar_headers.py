import importlib.util
import io
import os
from pathlib import Path
import struct
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hostbackup_tar_headers", ROOT / "bin/hostbackup-tar-headers.py")
headers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(headers)
TARGET = "./opt/loxberry/log/plugins/example"


def acl_bytes(entries):
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", tag, perm, uid if uid >= 0 else 0xffffffff)
                                          for tag, uid, perm in entries)


class TarDirectoryHeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "rootfs.tar"
        self.expected = {"uid": 1001, "gid": 1001, "mode": 0o750, "xattrs": {}}

    def member(self, *, name=TARGET, mode=0o750, uid=1001, gid=1001, pax=None, kind=tarfile.DIRTYPE):
        member = tarfile.TarInfo(name)
        member.uid, member.gid, member.mode, member.type = uid, gid, mode, kind
        member.pax_headers = {key: value.decode("utf-8", "surrogateescape") if isinstance(value, bytes) else value
                              for key, value in (pax or {}).items()}
        return member

    def write(self, *members, payload=False):
        with tarfile.open(self.archive, "w", format=tarfile.PAX_FORMAT, encoding="utf-8", errors="surrogateescape") as archive:
            if payload:
                member = tarfile.TarInfo("persistent.bin")
                member.size = 2 * 1024 * 1024
                archive.addfile(member, io.BytesIO(b"x" * member.size))
            for member in members:
                archive.addfile(member)

    def verify(self):
        return headers.verify_directory_headers(self.archive, {TARGET: self.expected})

    def test_base_directory_metadata_and_basic_acl_match(self):
        self.write(self.member(pax={"SCHILY.acl.access": "user::rwx\ngroup::r-x\nother::---\n"}))
        self.assertTrue(self.verify())

    def test_root_header_dot_slash_and_pax_root_do_not_block_other_directory(self):
        for pax in ({}, {"path": "./"}):
            self.write(self.member(name="./", pax=pax), self.member())
            self.assertTrue(self.verify())
            self.assertTrue(headers.verify_directory_headers(self.archive, {".": self.expected}))
        for name in ("././", "./../", "/", "../"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                headers._name(name)

    def test_permissions_ownership_and_type_mismatches_fail(self):
        for fields in ({"mode": 0o777}, {"uid": 0}, {"gid": 0}, {"kind": tarfile.SYMTYPE}, {"kind": tarfile.REGTYPE}):
            with self.subTest(fields=fields):
                self.write(self.member(**fields))
                with self.assertRaises(ValueError):
                    self.verify()

    def test_transient_chmod_reverted_before_endpoint_fingerprint_still_fails(self):
        # Both endpoint receipts say 0750, but tar captured the transient 0777.
        self.assertEqual(self.expected["mode"], 0o750)
        self.write(self.member(mode=0o777))
        with self.assertRaisesRegex(ValueError, "Besitzer/Rechte"):
            self.verify()

    def test_binary_xattrs_roundtrip_including_nul_and_invalid_utf8(self):
        self.expected["xattrs"] = {"user.binary": b"\0\xff\xfeabc\n=", "security.capability": b"\x01\0\0\x03\xff"}
        self.write(self.member(pax={"SCHILY.xattr." + key: value for key, value in self.expected["xattrs"].items()}))
        self.assertTrue(self.verify())

    def test_missing_extra_or_changed_xattrs_fail(self):
        self.expected["xattrs"] = {"user.label": b"original"}
        for pax in ({}, {"SCHILY.xattr.user.label": b"changed"},
                    {"SCHILY.xattr.user.label": b"original", "SCHILY.xattr.user.extra": b"unexpected"}):
            self.write(self.member(pax=pax))
            with self.assertRaisesRegex(ValueError, "Xattrs"):
                self.verify()

    def test_gnu_xattr_name_escaping_is_single_pass_and_collisions_fail(self):
        self.expected["xattrs"] = {"user.percent%=name": b"ok", "user.literal%3D": b"literal"}
        pax = {"SCHILY.xattr.user.percent%25%3Dname": b"ok", "SCHILY.xattr.user.literal%253D": b"literal"}
        self.write(self.member(pax=pax))
        self.assertTrue(self.verify())
        self.expected["xattrs"]["user.collision%z"] = b"collision"
        pax["SCHILY.xattr.user.collision%25z"] = b"collision"
        pax["SCHILY.xattr.user.collision%z"] = b"collision"
        self.write(self.member(pax=pax))
        with self.assertRaisesRegex(ValueError, "Xattr-Name"):
            self.verify()

    def test_extended_access_and_default_acls_match_binary_and_text(self):
        access = [(1, -1, 7), (2, 65534, 4), (4, -1, 5), (16, -1, 5), (32, -1, 0)]
        default = [(1, -1, 7), (4, -1, 5), (32, -1, 0)]
        self.expected["xattrs"] = {headers.ACL_ACCESS: acl_bytes(access), headers.ACL_DEFAULT: acl_bytes(default)}
        pax = {"SCHILY.xattr." + key: value for key, value in self.expected["xattrs"].items()}
        pax.update({"SCHILY.acl.access": "user::rwx\nuser:65534:r--\ngroup::r-x\nmask::r-x\nother::---",
                    "SCHILY.acl.default": "user::rwx,group::r-x,other::---"})
        self.write(self.member(pax=pax))
        self.assertTrue(self.verify())
        pax["SCHILY.acl.access"] = "user::rwx\nuser:65534:rw-\ngroup::r-x\nmask::r-x\nother::---"
        self.write(self.member(pax=pax))
        with self.assertRaisesRegex(ValueError, "POSIX-ACL"):
            self.verify()

    def test_acl_missing_mask_duplicate_named_ids_or_unknown_encoding_fail(self):
        for value in ("user::rwx\nuser:65534:r--\ngroup::r-x\nother::---",
                      "user::rwx\ngroup::r-x\nother::---\nuser::rwx",
                      "user::rwx\nuser:nobody:r--\ngroup::r-x\nmask::r-x\nother::---"):
            self.write(self.member(pax={"SCHILY.acl.access": value}))
            with self.assertRaises(ValueError):
                self.verify()

    def test_absent_default_acl_cannot_be_added_by_archive(self):
        self.write(self.member(pax={"SCHILY.acl.default": "user::rwx\ngroup::r-x\nother::---"}))
        with self.assertRaisesRegex(ValueError, "POSIX-ACL"):
            self.verify()

    def test_selinux_raw_and_dedicated_header_must_agree(self):
        label = b"system_u:object_r:var_log_t:s0"
        self.expected["xattrs"] = {"security.selinux": label + b"\0"}
        pax = {"SCHILY.xattr.security.selinux": label + b"\0", "RHT.security.selinux": label}
        self.write(self.member(pax=pax))
        self.assertTrue(self.verify())
        pax["RHT.security.selinux"] = b"different"
        self.write(self.member(pax=pax))
        with self.assertRaisesRegex(ValueError, "SELinux"):
            self.verify()

    def test_duplicate_directory_and_missing_directory_fail(self):
        self.write(self.member(), self.member(name=TARGET[2:] + "/"))
        with self.assertRaisesRegex(ValueError, "mehrfach"):
            self.verify()
        self.write(self.member(name="another"))
        with self.assertRaisesRegex(ValueError, "nicht archiviert"):
            self.verify()

    def test_long_unicode_pax_path_is_supported_without_extraction(self):
        global TARGET
        original = TARGET
        try:
            TARGET = "./opt/loxberry/log/plugins/" + "ü" * 130
            self.write(self.member(name=TARGET, pax={"user.note": "metadata"}))
            self.assertTrue(self.verify())
        finally:
            TARGET = original

    def test_duplicate_pax_keys_and_malformed_lengths_are_rejected(self):
        for value in (b"8 uid=1\n8 uid=2\n", b"99 uid=1\n", b"0 x=\n", b"6 a=x\r"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                headers._pax(value)

    def test_regular_payload_is_seeked_over_without_reading_contents(self):
        self.write(self.member(), payload=True)
        original = os.fdopen

        class Guarded:
            def __init__(self, raw):
                self.raw = raw
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.raw.close()
            def __getattr__(self, name):
                return getattr(self.raw, name)
            def read(self, size=-1):
                start = self.raw.tell()
                end = start + size if size >= 0 else float("inf")
                if start < 512 + 2 * 1024 * 1024 and end > 512:
                    raise AssertionError("Regular payload must not be read")
                return self.raw.read(size)

        with patch.object(headers.os, "fdopen", side_effect=lambda *args, **kwargs: Guarded(original(*args, **kwargs))):
            self.assertTrue(self.verify())

    def test_truncated_bad_checksum_or_nonzero_trailer_fail(self):
        self.write(self.member())
        valid = self.archive.read_bytes()
        for damaged in (valid[:600], b"X" + valid[1:], valid[:-1] + b"X"):
            self.archive.write_bytes(damaged)
            with self.assertRaises(ValueError):
                self.verify()

    def test_nonregular_archive_is_rejected_before_reading_headers(self):
        self.write(self.member())
        with patch.object(headers.os, "fstat", return_value=SimpleNamespace(st_mode=stat.S_IFIFO)):
            with self.assertRaisesRegex(ValueError, "keine regulaere Datei"):
                self.verify()


if __name__ == "__main__":
    unittest.main()
