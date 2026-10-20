#!/usr/bin/env python3
"""Strict GNU TAR copy with narrowly verified runtime-directory churn.

Regular files remain subject to TAR's normal error handling. An exit status 1
may become success only when every diagnostic names a verified managed runtime
directory, its identity and security metadata are unchanged, and its archived
header contains those exact metadata. No read-failure option is enabled.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def sibling(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = sibling("hostbackup-runtime-policy")
headers = sibling("hostbackup-tar-headers")
recovery = sibling("hostbackup-recovery")
MAX_DIRECTORIES = 10000
MAX_DIAGNOSTICS = 4 * 1024 * 1024
MAX_LINE = 65536
MAX_XATTR_BYTES = 1024 * 1024
TAR_OPTIONS = ("--format=pax", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--selinux", "--sparse")


def c_quote(value):
    """GNU's fixed C quoting, compared as bytes rather than parsed log text."""
    escapes = {7: b"\\a", 8: b"\\b", 9: b"\\t", 10: b"\\n", 11: b"\\v", 12: b"\\f", 13: b"\\r",
               34: b'\\"', 92: b"\\\\"}
    return b'"' + b"".join(escapes.get(char, bytes([char]) if 32 <= char < 127 else ("\\%03o" % char).encode())
                            for char in value) + b'"'


def file_entries(path):
    """Read the frozen NUL list without decoding or interpreting filenames."""
    with Path(path).open("rb") as handle:
        pending = b""
        while block := handle.read(65536):
            pending += block
            while b"\0" in pending:
                value, pending = pending.split(b"\0", 1)
                if not value or len(value) > 4096:
                    raise ValueError("Invalid frozen TAR source entry")
                yield value
            if len(pending) > 4096:
                raise ValueError("Oversized frozen TAR source entry")
        if pending:
            raise ValueError("Frozen TAR source list is not NUL terminated")


def directory_fingerprint(logical, root):
    """Pin every parent without following symlinks; collect all Linux xattrs."""
    descriptor = None
    try:
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            return None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(root, flags)
        for part in logical.lstrip("/").split("/"):
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        before = os.fstat(descriptor)
        values = {}
        total = 0
        for key in os.listxattr(descriptor):
            value = os.getxattr(descriptor, key)
            total += len(os.fsencode(key)) + len(value)
            if total > MAX_XATTR_BYTES:
                return None
            values[key] = value
        after = os.fstat(descriptor)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
        if identity(before) != identity(after) or not stat.S_ISDIR(after.st_mode):
            return None
        return {"device": after.st_dev, "inode": after.st_ino, "mode": stat.S_IMODE(after.st_mode),
                "uid": after.st_uid, "gid": after.st_gid, "xattrs": values}
    except (OSError, ValueError, AttributeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def directory_receipts(file_list, report, root):
    content = report.get("runtime_content_policy", {})
    if (content.get("version") != runtime.POLICY_VERSION or content.get("enabled") is not True
            or content.get("include_runtime_logs") is not False):
        return {}
    policy = runtime.RuntimePolicy(content["loxberry_home"], False, report.get("mount_identity", ()),
                                   report.get("selection", {}).get("overrides", {}))
    receipts = {}
    for entry in file_entries(file_list):
        if not entry.startswith(b"./") or entry.endswith(b"/"):
            continue
        logical = os.fsdecode(entry[1:])
        # The marker asks whether this directory's ordinary payload is covered;
        # this also handles each managed root itself and explicit opt-ins.
        if (policy._managed_root(logical + "/.hostbackup-policy-check") is None
                or not policy._mounts_safe(logical)):
            continue
        fingerprint = directory_fingerprint(logical, root)
        if fingerprint is not None:
            if entry in receipts or len(receipts) >= MAX_DIRECTORIES:
                # Unusually large/ambiguous input retains ordinary strict TAR.
                return {}
            receipts[entry] = fingerprint
    return receipts


def changed_directories(stderr_path, before, root):
    """Accept only complete exact diagnostics; names cannot inject log lines."""
    expected = {b"tar: " + c_quote(name) + b": file changed as we read it\n": name for name in before}
    changed = set()
    total = 0
    with Path(stderr_path).open("rb") as handle:
        while line := handle.readline(MAX_LINE + 1):
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_DIAGNOSTICS or line not in expected:
                return None
            changed.add(expected[line])
    if not changed:
        return None
    for name in changed:
        if directory_fingerprint(os.fsdecode(name[1:]), root) != before[name]:
            return None
    return {os.fsdecode(name): before[name] for name in changed}


def show_diagnostics(path):
    # Stream the complete original diagnostics on failure without keeping an
    # unbounded command output in memory. Invalid bytes are display-escaped.
    with Path(path).open("rb") as handle:
        while block := handle.read(65536):
            sys.stdout.write(block.decode("utf-8", errors="backslashreplace"))
    sys.stdout.flush()


def create_archive(archive, file_list, source_report, state_dir, source_root=Path("/"), extra_options=()):
    report = source_report if isinstance(source_report, dict) else json.loads(recovery.read_control(Path(source_report)))
    if not isinstance(report, dict):
        raise ValueError("Invalid private source report")
    state_dir, source_root = Path(state_dir), Path(source_root)
    before = directory_receipts(file_list, report, source_root)
    stderr_path = state_dir / "tar-stderr.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(stderr_path, flags, 0o600)
    environment = {key: value for key, value in os.environ.items() if key not in ("TAR_OPTIONS", "QUOTING_STYLE")}
    environment["LC_ALL"] = "C"
    argv = ["tar", *TAR_OPTIONS, *extra_options, "--quoting-style=c", "-C", str(source_root), "-cpf", str(archive),
            "--no-recursion", "--null", "--verbatim-files-from", "--files-from=" + str(file_list)]
    with os.fdopen(descriptor, "wb") as diagnostics:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stderr=diagnostics, env=environment, check=False)
        diagnostics.flush()
        os.fsync(diagnostics.fileno())
    raw_status = result.returncode if result.returncode >= 0 else 128 - result.returncode
    effective = raw_status
    classification = "clean" if raw_status == 0 else "copy_error"
    verified_count = 0
    if raw_status == 1 and before:
        matching = changed_directories(stderr_path, before, source_root)
        if matching:
            try:
                headers.verify_directory_headers(Path(archive), matching)
                # Reading headers may take time on a remote destination; the
                # final no-follow identity/security check must still agree.
                if all(directory_fingerprint(name[1:], source_root) == metadata for name, metadata in matching.items()):
                    effective, classification, verified_count = 0, "verified_runtime_directory_churn", len(matching)
            except (OSError, ValueError):
                pass
    if classification == "verified_runtime_directory_churn":
        print("TAR: %d fluechtige Diagnoseverzeichnisse waehrend der Sicherung aktualisiert; "
              "Verzeichnisidentitaet, Rechte, ACLs und gespeicherte Metadaten unveraendert geprueft." % verified_count)
    else:
        show_diagnostics(stderr_path)
    return {"version": 1, "tool": "tar", "raw_exit_status": raw_status, "effective_exit_status": effective,
            "classification": classification, "directory_metadata_verified_count": verified_count,
            "stderr_path": str(stderr_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "files-from", "source-report", "state-dir", "receipt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    receipt = create_archive(args.archive, args.files_from, args.source_report, args.state_dir)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(args.receipt, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=True, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return receipt["effective_exit_status"]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as exc:
        print("TAR copy could not be safely completed: " + str(exc), file=sys.stderr)
        sys.exit(18)
