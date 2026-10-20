#!/usr/bin/env python3
"""Verify archived directory metadata before accepting runtime-only TAR churn.

The caller supplies already-proven managed directories. This module does not
classify paths, extract an archive, or read regular-file contents. It scans
checksummed headers and bounded PAX metadata, seeking across file payloads.
"""
import os
from pathlib import PurePosixPath
import re
import stat
import struct
import tarfile


BLOCK = 512
MAX_PAX_BYTES = 4 * 1024 * 1024
MAX_TRAILER_BYTES = 1024 * 1024
ACL_ACCESS = "system.posix_acl_access"
ACL_DEFAULT = "system.posix_acl_default"
XATTR_PREFIX = b"SCHILY.xattr."


def _fail(message):
    raise ValueError("TAR-Verzeichnis-Metadaten nicht bestaetigt: " + message)


def _name(value):
    if value in (".", "./"):
        return "."
    if value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    if (not value or value == "." or value.startswith("/") or "\0" in value
            or value != str(PurePosixPath(value)) or ".." in PurePosixPath(value).parts):
        _fail("ungueltiger Archivpfad")
    return value


def _pax(payload):
    records = {}
    offset = 0
    while offset < len(payload):
        separator = payload.find(b" ", offset)
        if separator < 0 or not re.fullmatch(rb"[1-9][0-9]*", payload[offset:separator]):
            _fail("ungueltige PAX-Laenge")
        length = int(payload[offset:separator])
        end = offset + length
        if end > len(payload) or end <= separator + 3 or payload[end - 1:end] != b"\n":
            _fail("unvollstaendiger PAX-Eintrag")
        key, equals, value = payload[separator + 1:end - 1].partition(b"=")
        if not equals or not key or b"\0" in key or key in records:
            _fail("doppelter oder ungueltiger PAX-Schluessel")
        records[key] = value
        offset = end
    return records


def _acl_validate(entries):
    identities = [(tag, identifier) for tag, identifier, permission in entries]
    if len(identities) != len(set(identities)):
        _fail("doppelter ACL-Eintrag")
    if entries:
        required = {(1, -1), (4, -1), (32, -1)}
        if not required <= set(identities):
            _fail("unvollstaendige POSIX-ACL")
        if any(tag in (2, 8) for tag, _, _ in entries) and (16, -1) not in identities:
            _fail("ACL-Maske fehlt")
    return tuple(sorted(entries))


def _acl_binary(value):
    if len(value) < 4 or (len(value) - 4) % 8 or struct.unpack_from("<I", value)[0] != 2:
        _fail("unbekanntes POSIX-ACL-Xattr-Format")
    entries = []
    for offset in range(4, len(value), 8):
        tag, permission, identifier = struct.unpack_from("<HHI", value, offset)
        if tag not in (1, 2, 4, 8, 16, 32) or permission > 7:
            _fail("ungueltiger POSIX-ACL-Eintrag")
        if tag in (2, 8):
            if identifier == 0xffffffff:
                _fail("ACL-Benutzerkennung fehlt")
        elif identifier != 0xffffffff:
            _fail("unerwartete ACL-Benutzerkennung")
        else:
            identifier = -1
        entries.append((tag, identifier, permission))
    return _acl_validate(entries)


def _acl_text(value):
    try:
        text = value.decode("ascii")
    except UnicodeError:
        _fail("ACL ist nicht numerisch kodiert")
    entries = []
    for line in re.split(r"[,\n]", text):
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"(user|group|mask|other):([0-9]*):([r-][w-][x-])", line)
        if not match:
            _fail("unbekannte ACL-Textdarstellung")
        kind, qualifier, permissions = match.groups()
        if qualifier and kind not in ("user", "group"):
            _fail("ungueltiger ACL-Qualifizierer")
        tag = {"user": 2 if qualifier else 1, "group": 8 if qualifier else 4,
               "mask": 16, "other": 32}[kind]
        identifier = int(qualifier) if qualifier else -1
        if identifier >= 0xffffffff:
            _fail("ungueltige ACL-Benutzerkennung")
        permission = sum(bit for char, bit in zip(permissions, (4, 2, 1)) if char != "-")
        entries.append((tag, identifier, permission))
    return _acl_validate(entries)


def _verify_member(member, pax, expected):
    if not member.isdir() or member.size != 0 or pax.get(b"size", b"0") != b"0":
        _fail("erwartetes Verzeichnis fehlt oder wurde ersetzt")
    for key in ("uid", "gid", "mode"):
        actual = int(pax.get(key.encode(), str(getattr(member, key)).encode())) if key != "mode" else member.mode
        if actual != expected[key]:
            _fail("archivierte Besitzer/Rechte stimmen nicht ueberein")
    actual_xattrs = {}
    for key, value in pax.items():
        if key.startswith(XATTR_PREFIX):
            # GNU tar xheader.c escapes only '%' and '=' in keyword names;
            # decode once, exactly as GNU tar does (not generic URL decoding).
            encoded_name = re.sub(rb"%(?:25|3D)", lambda match: b"%" if match[0] == b"%25" else b"=",
                                  key[len(XATTR_PREFIX):])
            name = encoded_name.decode("utf-8", "surrogateescape")
            if not name or "\0" in name or name in actual_xattrs:
                _fail("ungueltiger Xattr-Name")
            actual_xattrs[name] = value
        elif key.startswith(b"SCHILY.acl.") and key not in (b"SCHILY.acl.access", b"SCHILY.acl.default"):
            _fail("unbekannter ACL-Header")
        elif key.startswith(b"GNU.sparse."):
            _fail("Sparse-Header fuer Verzeichnis")
    wanted = expected["xattrs"]
    if actual_xattrs != wanted:
        _fail("archivierte Xattrs stimmen nicht ueberein")
    for key, attribute in ((b"SCHILY.acl.access", ACL_ACCESS), (b"SCHILY.acl.default", ACL_DEFAULT)):
        if attribute in wanted:
            expected_acl = _acl_binary(wanted[attribute])
            if key not in pax:
                _fail("archivierte POSIX-ACL fehlt")
        elif attribute == ACL_ACCESS:
            mode = expected["mode"]
            expected_acl = ((1, -1, (mode >> 6) & 7), (4, -1, (mode >> 3) & 7), (32, -1, mode & 7))
        else:
            expected_acl = ()
        if key in pax and _acl_text(pax[key]) != expected_acl:
            _fail("archivierte POSIX-ACL stimmt nicht ueberein")
    selinux = wanted.get("security.selinux")
    if selinux is not None:
        if pax.get(b"RHT.security.selinux") != selinux.removesuffix(b"\0"):
            _fail("archiviertes SELinux-Label stimmt nicht ueberein")
    elif b"RHT.security.selinux" in pax:
        _fail("unerwartetes SELinux-Label")


def verify_directory_headers(archive, expected):
    """Return True or raise ValueError; no extraction or data-content reads."""
    wanted = {}
    for path, receipt in expected.items():
        name = _name(path)
        if name in wanted or not isinstance(receipt, dict):
            _fail("mehrdeutige erwartete Verzeichnisse")
        if any(type(receipt.get(key)) is not int or receipt[key] < 0 for key in ("uid", "gid", "mode")):
            _fail("ungueltiger erwarteter Metadatenwert")
        if receipt["mode"] > 0o7777 or not isinstance(receipt.get("xattrs"), dict):
            _fail("ungueltige erwartete Rechte/Xattrs")
        if any(not isinstance(key, str) or not isinstance(value, bytes) for key, value in receipt["xattrs"].items()):
            _fail("ungueltige erwartete Xattrs")
        wanted[name] = receipt
    if not wanted:
        _fail("keine Verzeichnisse zur Headerpruefung")
    seen, pending, global_pax = set(), None, {}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(archive, flags)
    with os.fdopen(descriptor, "rb") as handle:
        archive_info = os.fstat(handle.fileno())
        if not stat.S_ISREG(archive_info.st_mode):
            _fail("Archiv ist keine regulaere Datei")
        archive_size = archive_info.st_size
        while True:
            block = handle.read(BLOCK)
            if len(block) != BLOCK:
                _fail("Archiv endet ohne vollstaendigen Abschluss")
            if block == bytes(BLOCK):
                if pending is not None or handle.read(BLOCK) != bytes(BLOCK):
                    _fail("Archivabschluss ist unvollstaendig")
                remaining = archive_size - handle.tell()
                if remaining < 0 or remaining > MAX_TRAILER_BYTES or any(handle.read(remaining)):
                    _fail("unerwartete Daten nach dem Archivabschluss")
                break
            try:
                member = tarfile.TarInfo.frombuf(block, "utf-8", "surrogateescape")
            except tarfile.HeaderError as exc:
                raise ValueError("Ungueltiger TAR-Header") from exc
            if member.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                if member.size < 0 or member.size > MAX_PAX_BYTES:
                    _fail("PAX-Metadaten zu gross")
                payload = handle.read(member.size)
                if len(payload) != member.size:
                    _fail("abgeschnittene PAX-Metadaten")
                values = _pax(payload)
                handle.seek((-member.size) % BLOCK, os.SEEK_CUR)
                if member.type == tarfile.XGLTYPE:
                    if pending is not None or any(key in global_pax for key in values):
                        _fail("mehrdeutige globale PAX-Metadaten")
                    global_pax.update(values)
                elif pending is not None:
                    _fail("mehrdeutige lokale PAX-Metadaten")
                else:
                    pending = values
                continue
            if member.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK, tarfile.GNUTYPE_SPARSE):
                _fail("nicht unterstuetztes Nicht-PAX-Archivformat")
            pax = {**global_pax, **(pending or {})}
            pending = None
            name = _name(pax.get(b"path", member.name.encode("utf-8", "surrogateescape")).decode("utf-8", "surrogateescape"))
            if name in wanted:
                if name in seen:
                    _fail("Verzeichnis mehrfach im Archiv")
                _verify_member(member, pax, wanted[name])
                seen.add(name)
            size_raw = pax.get(b"size")
            if size_raw is not None and not re.fullmatch(rb"[0-9]+", size_raw):
                _fail("ungueltige PAX-Dateigroesse")
            size = int(size_raw) if size_raw is not None else member.size
            end = handle.tell() + ((size + BLOCK - 1) // BLOCK) * BLOCK
            if size < 0 or end > archive_size:
                _fail("Dateiinhalt im Archiv abgeschnitten")
            handle.seek(end)
        final_info = os.fstat(handle.fileno())
        if (final_info.st_size, final_info.st_mtime_ns, final_info.st_ctime_ns) != (
                archive_size, archive_info.st_mtime_ns, archive_info.st_ctime_ns):
            _fail("Archiv waehrend der Headerpruefung veraendert")
    if seen != set(wanted):
        _fail("erwartetes Verzeichnis nicht archiviert")
    return True
