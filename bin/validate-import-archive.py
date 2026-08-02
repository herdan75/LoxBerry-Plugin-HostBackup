#!/usr/bin/env python3
"""Validate HostBackup tar archives without extracting them."""

import json
import pathlib
import sys
import tarfile


MAX_MEMBERS = 2_000_000
SAFE_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


def fail(message):
    raise SystemExit(message)


def safe_path(raw):
    path = pathlib.PurePosixPath(raw.rstrip("/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        fail("Archive contains unsafe paths.")
    return path


def validate_members(members, limit, expected_top):
    seen = set()
    symlinks = []
    regular_files = set()
    directories = set()
    top = expected_top
    total = 0
    count = 0

    for member in members:
        raw = member.name.rstrip("/")
        if not raw or raw == ".":
            continue
        path = safe_path(raw)
        current_top = path.parts[0]
        if expected_top is not None:
            if top is None:
                top = current_top
            if current_top != top:
                fail("Archive must contain exactly one top-level backup.")
        normalized = path.as_posix()
        if normalized in seen:
            fail("Archive contains duplicate members.")
        seen.add(normalized)
        count += 1
        if count > MAX_MEMBERS:
            fail("Archive contains too many members.")
        total += max(0, int(member.size or 0))
        if total > limit:
            fail("Archive exceeds the configured expanded-size limit.")
        if member.isdev() or member.isfifo():
            fail("Archive contains unsupported special files.")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            fail("Archive contains an unsupported member type.")
        if member.issym():
            symlinks.append(normalized)
        elif member.isfile():
            regular_files.add(normalized)
        elif member.isdir():
            directories.add(normalized)
        if member.islnk():
            link = safe_path(member.linkname)
            if expected_top is not None and (not link.parts or link.parts[0] != top):
                fail("Archive contains an escaping hardlink.")

    for link in symlinks:
        prefix = link + "/"
        if any(name.startswith(prefix) for name in seen):
            fail("Archive writes through a symlink member.")
    return seen, symlinks, top, regular_files, directories, total


def validate_outer(archive, limit):
    with tarfile.open(archive, mode="r|gz") as tf:
        # The empty string tells validate_members to discover one top-level id.
        members = iter(tf)
        first = next(members, None)
        if first is None:
            fail("Archive is empty.")

        def with_first():
            yield first
            yield from members

        first_path = safe_path(first.name)
        top = first_path.parts[0]
        if (
            top.startswith(".")
            or ".." in top
            or any(character not in SAFE_ID_CHARS for character in top)
        ):
            fail("Unsafe backup id in archive.")
        seen, _symlinks, discovered, regular_files, directories, total = validate_members(
            with_first(), limit, top
        )

    if not discovered:
        fail("Archive is empty.")
    rootfs_dir = f"{discovered}/rootfs" in directories
    rootfs_tar = f"{discovered}/rootfs.tar" in regular_files
    manifest = f"{discovered}/manifest.json" in regular_files
    validation = f"{discovered}/backup-validation.json" in regular_files
    if not (rootfs_dir or rootfs_tar) or not manifest or not validation:
        fail("Archive is missing rootfs, manifest or validation data.")
    return discovered, total


def validate_rootfs_tar(archive, limit):
    with tarfile.open(archive, mode="r:") as tf:
        seen, _symlinks, _top, _regular_files, _directories, _total = validate_members(
            tf, limit, None
        )
    normalized = {name[2:] if name.startswith("./") else name for name in seen}
    if not any(name == "etc" or name.startswith("etc/") for name in normalized):
        fail("Portable rootfs archive is missing /etc.")
    if not any(
        name == "opt/loxberry" or name.startswith("opt/loxberry/")
        for name in normalized
    ):
        fail("Portable rootfs archive is missing /opt/loxberry.")


def main():
    args = sys.argv[1:]
    rootfs_mode = bool(args and args[0] == "--rootfs-tar")
    if rootfs_mode:
        args = args[1:]
    json_mode = bool(args and args[0] == "--json")
    if json_mode:
        args = args[1:]
    if len(args) != 2 or not args[1].isdigit():
        fail("Usage: validate-import-archive.py [--rootfs-tar] ARCHIVE MAX_BYTES")
    archive, raw_limit = args
    limit = int(raw_limit)
    if limit <= 0:
        fail("Expanded-size limit must be positive.")
    if rootfs_mode:
        validate_rootfs_tar(archive, limit)
    else:
        top, expanded_size = validate_outer(archive, limit)
        if json_mode:
            print(json.dumps({"backup_id": top, "expanded_size": expanded_size}, sort_keys=True))
        else:
            print(top)


if __name__ == "__main__":
    main()
