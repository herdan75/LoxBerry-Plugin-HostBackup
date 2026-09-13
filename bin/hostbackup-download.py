#!/usr/bin/env python3
"""Stream validated files from a privileged, locked backend without changing permissions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def open_regular(path):
    path = Path(path)
    if not path.name:
        raise ValueError("Download benoetigt einen Dateinamen.")
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Symbolische Download-Pfadkomponente ist nicht erlaubt.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    if os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
        parent_fd = os.open(path.anchor or ".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            components = path.parts[1:] if path.is_absolute() else path.parts
            for component in components[:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            fd = os.open(components[-1], flags, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    else:
        fd = os.open(path, flags)
    handle = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        handle.close()
        raise ValueError("Download ist keine regulaere Datei.")
    return handle


def read_small(path):
    with open_regular(path) as handle:
        value = handle.read(1048577)
    if len(value) > 1048576:
        raise ValueError("Download-Kontrolldatei ist zu gross.")
    return value


def stream(path, name, kind, descriptor=None, manifest=None, checksum=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,240}", name):
        raise ValueError("Ungueltiger Downloadname.")
    with open_regular(path) as handle:
        info = os.fstat(handle.fileno())
        if kind == "export":
            data = json.loads(read_small(descriptor))
            if not isinstance(data, dict) or not isinstance(data.get("backup_id"), str):
                raise ValueError("Ungueltiger Export-Descriptor.")
            checksum_line = read_small(checksum).decode("ascii").rstrip("\n")
            expected = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(name), checksum_line)
            if not expected or data.get("archive") != name or data.get("backup_id") + ".tar.gz" != name:
                raise ValueError("Export-Descriptor passt nicht zum Archiv.")
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != expected[1] or actual != data.get("sha256"):
                raise ValueError("Export-Pruefsumme stimmt nicht. Export erneut erstellen.")
            if hashlib.sha256(read_small(manifest)).hexdigest() != data.get("manifest_sha256"):
                raise ValueError("Export gehoert nicht zum aktuellen Backup-Manifest.")
            final = os.fstat(handle.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (final.st_size, final.st_mtime_ns, final.st_ctime_ns):
                raise ValueError("Export wurde waehrend der Pruefung veraendert.")
            handle.seek(0)
        mime = "application/gzip" if kind == "export" else "text/plain; charset=utf-8"
        headers = (f"Content-Type: {mime}\r\nContent-Disposition: attachment; filename=\"{name}\"\r\n"
                   f"Content-Length: {info.st_size}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n")
        sys.stdout.buffer.write(headers.encode("ascii"))
        # Bound an active log to the validated length; do not chase a growing file forever.
        remaining = info.st_size
        while remaining:
            block = handle.read(min(1048576, remaining))
            if not block:
                raise ValueError("Download-Datei wurde waehrend des Lesens gekuerzt.")
            sys.stdout.buffer.write(block)
            remaining -= len(block)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("export", "log"))
    parser.add_argument("path")
    parser.add_argument("name")
    parser.add_argument("--descriptor")
    parser.add_argument("--manifest")
    parser.add_argument("--checksum")
    args = parser.parse_args()
    try:
        stream(args.path, args.name, args.kind, args.descriptor, args.manifest, args.checksum)
    except (OSError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(18)
