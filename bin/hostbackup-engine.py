#!/usr/bin/env python3
"""Pinned offline engine provisioning. Network is used only by package builders."""
import argparse
import bz2
import hashlib
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile
import urllib.request

VERSION = "0.19.1"
HASHES = {
    "amd64": "f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c",
    "arm": "1edc5f67b0dd0d028586ab28c34b4da7522eabce933b3f6cd04f9ea184c2a502",
    "arm64": "a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465",
}
MAX_COMPRESSED = 64 * 1024 * 1024
MAX_BINARY = 192 * 1024 * 1024


def filename(arch):
    return f"restic_{VERSION}_linux_{arch}.bz2"


def checked_blob(path, arch):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_COMPRESSED:
        raise ValueError("Missing or unsafe packaged Restic engine.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != HASHES[arch]:
        raise ValueError("Packaged Restic checksum mismatch.")
    return data


def fetch(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Unsafe engine cache.")
    for arch in HASHES:
        target = destination / filename(arch)
        if target.exists():
            checked_blob(target, arch)
            continue
        url = f"https://github.com/restic/restic/releases/download/v{VERSION}/{filename(arch)}"
        with urllib.request.urlopen(url, timeout=120) as source:
            data = source.read(MAX_COMPRESSED + 1)
        if len(data) > MAX_COMPRESSED or hashlib.sha256(data).hexdigest() != HASHES[arch]:
            raise ValueError("Downloaded Restic checksum mismatch.")
        # Exclusive output: do not overwrite existing package-builder files.
        with target.open("xb") as output:
            output.write(data)
        print(filename(arch))


def architecture():
    # Kernel architecture alone is wrong for a 32-bit userspace on ARM64.
    try:
        value = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
        return {"amd64": "amd64", "arm64": "arm64", "armhf": "arm", "armel": "arm"}[value]
    except FileNotFoundError:
        value = platform.machine().lower()
        return {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm", "armv6l": "arm"}[value]


def install(source, destination):
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Engine installation requires Linux root.")
    target = Path(destination)
    for directory in (target, *target.parents):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Engine destination must have root-protected real parents.")
    blob = checked_blob(Path(source) / filename(architecture()), architecture())
    decoder = bz2.BZ2Decompressor()
    binary = decoder.decompress(blob, max_length=MAX_BINARY + 1)
    if len(binary) > MAX_BINARY or not decoder.eof or decoder.unused_data or not binary.startswith(b"\x7fELF"):
        raise ValueError("Invalid packaged engine.")
    final = target / "restic"
    with final.open("xb") as output:
        output.write(binary)
        output.flush()
        os.fsync(output.fileno())
    final.chmod(0o755)
    result = subprocess.check_output([str(final), "version", "--json"], text=True,
                                     env={"PATH": "/usr/bin:/bin", "GODEBUG": "asyncpreemptoff=1"})
    import json
    if json.loads(result).get("version") != VERSION:
        raise ValueError("Unexpected engine version.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch").add_argument("destination")
    command = sub.add_parser("install")
    command.add_argument("source")
    command.add_argument("destination")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.destination)
    else:
        install(args.source, args.destination)
