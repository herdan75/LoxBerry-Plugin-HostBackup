#!/usr/bin/env python3
"""Validate extraction paths and independently inspect imported backups.

The archive's validation report is a declaration, never proof of completeness.
--backup-dir inspects the actual extracted data; the backend installs its report
atomically after this process succeeds.
"""
import argparse
import datetime
import json
import os
import pathlib
import stat
import sys
import tarfile

MAX_MEMBERS = 2_000_000
MAX_CONTROL_BYTES = 2 * 1024 * 1024
SAFE_ID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
PROFILES = {"native-strict", "network-compatible", "fake-super", "portable-archive"}


def fail(message):
    raise ValueError(message)


def safe_id(value):
    if (not isinstance(value, str) or not value or value.startswith(".")
            or ".." in value or any(char not in SAFE_ID_CHARS for char in value)):
        fail("Unsafe backup id in archive.")
    return value


def safe_path(raw):
    if not isinstance(raw, str) or any(char in raw for char in ("\x00", "\r", "\n")):
        fail("Archive contains unsafe paths.")
    path = pathlib.PurePosixPath(raw.rstrip("/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        fail("Archive contains unsafe paths.")
    return path


def validate_members(members, limit, expected_top):
    seen, symlinks, regular_files, directories = set(), set(), set(), set()
    hardlinks = {}
    total = count = member_count = 0
    for member in members:
        member_count += 1
        raw = member.name.rstrip("/")
        if raw in ("", "."):
            if not member.isdir():
                fail("Archive root must be a directory.")
            continue
        path = safe_path(raw)
        if expected_top is not None and path.parts[0] != expected_top:
            fail("Archive must contain exactly one top-level backup.")
        normalized = path.as_posix()
        if normalized in seen:
            fail("Archive contains duplicate members.")
        seen.add(normalized)
        count += 1
        if count > MAX_MEMBERS:
            fail("Archive contains too many members.")
        if member.size < 0:
            fail("Archive contains an invalid member size.")
        total += member.size
        if total > limit:
            fail("Archive exceeds the configured expanded-size limit.")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            fail("Archive contains unsupported special files or member types.")
        if expected_top is not None:
            # Sidecars must never redirect a later privileged read or write.
            # Regular sidecars are allowed so a previously imported backup can
            # be re-exported, including its generated import-source.sha256.
            if len(path.parts) == 1 and not member.isdir():
                fail("Top-level backup must be a real directory.")
            if len(path.parts) == 2 and path.parts[1] != "rootfs" and not member.isfile():
                fail("Backup control files must be regular files, not links or directories.")
            if len(path.parts) > 2 and path.parts[1] != "rootfs":
                fail("Only rootfs may contain nested backup data.")
            if len(path.parts) == 2 and path.parts[1] == "rootfs" and not member.isdir():
                fail("Imported rootfs must be a real directory.")
        if member.issym():
            symlinks.add(normalized)
        elif member.isfile():
            regular_files.add(normalized)
        elif member.isdir():
            directories.add(normalized)
        elif member.islnk():
            link = safe_path(member.linkname).as_posix()
            if expected_top is not None and not link.startswith(expected_top + "/rootfs/"):
                fail("Archive contains an escaping hardlink or a hardlink to control data.")
            hardlinks[normalized] = link
    # Linear in total path components, rather than symlinks times all members.
    # Parent and child archive order does not affect the result.
    for name in seen:
        parent = name.rpartition("/")[0]
        while parent:
            if parent in symlinks:
                fail("Archive writes through a symlink member.")
            if parent in seen and parent not in directories:
                fail("Archive writes through a non-directory member.")
            parent = parent.rpartition("/")[0]
    for target in hardlinks.values():
        if target not in regular_files:
            fail("Archive hardlinks must refer to a regular file in the same data tree.")
    return {"seen": seen, "symlinks": symlinks, "files": regular_files,
            "hardlinks": hardlinks, "directories": directories,
            "expanded_size": total, "member_count": member_count}


def require_payload(files, prefix=""):
    for required in ("etc/", "opt/loxberry/"):
        if not any(name.startswith(prefix + required) for name in files):
            fail(f"Backup has no regular file content below /{required.rstrip('/')}.")


def validate_outer(archive, limit):
    with tarfile.open(archive, mode="r|gz") as tf:
        members = iter(tf)
        first = next(members, None)
        if first is None:
            fail("Archive is empty.")
        top = safe_id(safe_path(first.name).parts[0])

        def with_first():
            yield first
            yield from members

        result = validate_members(with_first(), limit, top)
    rootfs_dir = f"{top}/rootfs" in result["directories"]
    rootfs_tar = f"{top}/rootfs.tar" in result["files"]
    if rootfs_dir == rootfs_tar:
        fail("Archive must contain exactly one rootfs directory or rootfs.tar.")
    if not all(f"{top}/{name}" in result["files"]
               for name in ("manifest.json", "backup-validation.json")):
        fail("Archive is missing rootfs, manifest or validation data.")
    if rootfs_dir:
        require_payload(result["files"] | result["hardlinks"].keys(), f"{top}/rootfs/")
    return top, result["expanded_size"]


def validate_rootfs_tar(archive, limit):
    # HostBackup creates padded tar containers. tarfile alone can accept seeks
    # beyond a truncated file, so also verify the physical end marker and size.
    with open(archive, "rb") as source:
        size = os.fstat(source.fileno()).st_size
        if size < 1024 or size % 512:
            fail("Portable rootfs archive is truncated or not a complete tar container.")
        source.seek(-1024, os.SEEK_END)
        if source.read(1024) != b"\0" * 1024:
            fail("Portable rootfs archive has no complete end marker.")
    with tarfile.open(archive, mode="r:") as tf:
        def bounded_members():
            for member in tf:
                stored_size = member.size
                if member.sparse is not None:
                    end = stored_size = 0
                    for offset, length in member.sparse:
                        if offset < end or length < 0 or offset + length > member.size:
                            fail("Portable rootfs archive contains an invalid sparse map.")
                        end = offset + length
                        stored_size += length
                if member.offset_data + stored_size > size - 1024:
                    fail("Portable rootfs archive contains truncated file data.")
                yield member
        result = validate_members(bounded_members(), limit, None)
    require_payload(result["files"] | result["hardlinks"].keys())
    return result


def read_control(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail(f"Unsafe control file: {path.name}.")
    if info.st_size > MAX_CONTROL_BYTES:
        fail(f"Control file is too large: {path.name}.")
    with path.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        fail(f"Control file must contain a JSON object: {path.name}.")
    return data


def positive_integer(value, name):
    if type(value) is not int or value < 1:
        fail(f"Manifest {name} must be a positive integer.")
    return value


def inspect_directory(rootfs, limit):
    if not stat.S_ISDIR(rootfs.lstat().st_mode):
        fail("Imported rootfs must be a real directory.")
    files, stack = set(), [rootfs]
    total = count = 0
    device = rootfs.stat().st_dev
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                count += 1
                if count > MAX_MEMBERS:
                    fail("Imported rootfs contains too many entries.")
                # Explicit stat also supplies st_dev on Windows (the cached
                # DirEntry stat may leave it zero); do not follow data links.
                info = os.stat(entry.path, follow_symlinks=False)
                if info.st_dev != device:
                    fail("Imported rootfs crosses an unexpected mounted filesystem.")
                if stat.S_ISDIR(info.st_mode):
                    stack.append(pathlib.Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    files.add(pathlib.Path(entry.path).relative_to(rootfs).as_posix())
                    total += info.st_size
                elif not stat.S_ISLNK(info.st_mode):
                    fail("Imported rootfs contains unsupported special files.")
                if total > limit:
                    fail("Imported rootfs exceeds the configured expanded-size limit.")
    require_payload(files)
    return len(files), total


def validate_backup_dir(directory, limit):
    directory = pathlib.Path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        fail("Imported backup must be a real directory.")
    top = safe_id(directory.name)
    for entry in directory.iterdir():
        if entry.name == "rootfs":
            continue
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"Unsafe control file in imported backup: {entry.name}.")
    manifest = read_control(directory / "manifest.json")
    source_validation = read_control(directory / "backup-validation.json")
    if manifest.get("backup_id") != top:
        fail("Imported manifest id mismatch.")
    schema = manifest.get("schema_version")
    if type(schema) is not int or schema not in (1, 2):
        fail("Unsupported manifest schema_version.")
    source_status = source_validation.get("status")
    if (manifest.get("status"), source_status) not in (
        ("complete", "ok"), ("complete_with_warnings", "warning")
    ):
        fail("Imported backup does not declare a completed, validated copy.")
    backup = manifest.get("backup")
    if not isinstance(backup, dict) or backup.get("mode") not in ("full", "snapshot"):
        fail("Invalid manifest backup mode.")
    legacy = schema == 1
    if legacy:
        profile, storage_format = "legacy-unknown", "directory"
        if "metadata" in manifest or backup.get("storage_format", "directory") != "directory":
            fail("Legacy manifest contains inconsistent format or metadata information.")
    else:
        metadata = manifest.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("mode") not in PROFILES:
            fail("Manifest metadata profile is invalid.")
        profile = metadata["mode"]
        storage_format = backup.get("storage_format")
        expected = "portable-tar" if profile == "portable-archive" else "directory"
        if storage_format != expected or (profile == "portable-archive" and backup["mode"] != "full"):
            fail("Manifest metadata profile and storage format are inconsistent.")
    rootfs, container = directory / "rootfs", directory / "rootfs.tar"
    has_directory = rootfs.exists() or rootfs.is_symlink()
    has_container = container.exists() or container.is_symlink()
    if has_directory == has_container or has_directory != (storage_format == "directory"):
        fail("Backup data does not match the declared storage format.")
    expected_files = positive_integer(manifest.get("files_count"), "files_count")
    positive_integer(manifest.get("size_bytes"), "size_bytes")
    if storage_format == "directory":
        actual_files, logical_bytes = inspect_directory(rootfs, limit)
        counted_entries = actual_files
    else:
        result = validate_rootfs_tar(container, limit)
        actual_files = len(result["files"]) + len(result["hardlinks"])
        logical_bytes = result["expanded_size"]
        # Existing portable manifests count tar -tf entries, including root,
        # directories and links; directory backups use find -type f counts.
        counted_entries = result["member_count"]
    if counted_entries != expected_files:
        fail(f"Imported file count mismatch: manifest {expected_files}, inspected {counted_entries}.")
    plausible = actual_files >= 100 and logical_bytes >= 100 * 1024 * 1024
    status = "warning" if source_status == "warning" or legacy or not plausible else "ok"
    checks = [
        {"name": "Manifest und Profil lokal geprueft", "ok": True},
        {"name": "Sicherungsinhalt unabhaengig eingelesen", "ok": True, "value": actual_files},
        {"name": "Dateianzahl mit Manifest abgeglichen", "ok": True, "value": counted_entries},
        {"name": "Hostbackup-Umfang plausibel", "ok": plausible,
         "value": {"files": actual_files, "logical_bytes": logical_bytes}},
        {"name": "Quelldeklaration", "ok": source_status == "ok", "value": source_status,
         "informational": True},
    ]
    if legacy:
        checks.append({"name": "Altes Backup ohne Metadaten-Profil", "ok": False,
                       "value": "Metadatenumfang nicht nachweisbar"})
    return {"schema_version": 1, "backup_id": top, "status": status,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "validation_source": "local-import-inspection", "metadata_mode": profile,
            "storage_format": storage_format, "files_count": actual_files,
            "manifest_count": expected_files, "logical_bytes": logical_bytes,
            "content_hashes_verified": False, "restore_tested": False, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--rootfs-tar", action="store_true")
    modes.add_argument("--backup-dir", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("archive")
    parser.add_argument("max_bytes", type=int)
    args = parser.parse_args()
    if args.max_bytes <= 0:
        fail("Expanded-size limit must be positive.")
    if args.backup_dir:
        result = validate_backup_dir(args.archive, args.max_bytes)
    elif args.rootfs_tar:
        info = validate_rootfs_tar(args.archive, args.max_bytes)
        result = {"status": "ok", "expanded_size": info["expanded_size"]}
    else:
        top, expanded_size = validate_outer(args.archive, args.max_bytes)
        result = {"backup_id": top, "expanded_size": expanded_size}
    if args.json or args.backup_dir:
        print(json.dumps(result, sort_keys=True))
    elif not args.rootfs_tar:
        print(result["backup_id"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError, EOFError) as error:
        print(f"Import validation: {error}", file=sys.stderr)
        sys.exit(1)
