#!/usr/bin/env python3
"""Recognize a narrowly defined, non-fatal rsync log-rotation result.

This is NOT a generic exit-24 or *.log exception. Only complete, separate
rsync stderr consisting of known expendable LoxBerry runtime logs is accepted.
Any uncertainty keeps the normal warning. It is not a restore verification.
"""

import argparse
import json
import os
from pathlib import Path
import re
import stat


MAX_BYTES = 1024 * 1024
MAX_FILES = 4096
VANISHED = re.compile(r'file has vanished: "([^"\\]+)"')
SUMMARY = re.compile(
    r"rsync warning: some files vanished before they could be transferred "
    r"\(code 24\) at main\.c\([0-9]+\) \[(?:sender|receiver|generator)=[0-9]+(?:\.[0-9]+)+\]"
)
LOG_NAME = re.compile(
    r"(?:ramlog/log/)?(?:"
    r"plugins/stats4lox/grabber_(?:loxberry|loxone|miniserver)\.log|"
    r"plugins/miniserverbackup-ng/[0-9]{8}_[0-9]{6}_[0-9]+_Miniserverbackup NG CronJob\.log|"
    r"system_tmpfs/[0-9]{8}_[0-9]{6}_[0-9]+_Log Maintenance\.log)"
)


def _result(accepted, reason, count=0):
    return {"accepted": accepted, "reason": reason, "vanished_count": count}


def _known_log(name, home):
    # Do not normalize paths or decode rsync escapes: an ambiguous spelling
    # cannot be evidence that only a known runtime log disappeared.
    if not name.startswith("/") or any(part in ("", ".", "..") for part in name[1:].split("/")):
        return False
    prefix = str(home) + "/log/"
    if not name.startswith(prefix) or not LOG_NAME.fullmatch(name[len(prefix):]):
        return False
    path = Path(name)
    try:
        for parent in path.parents:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode):
                return False
        # Rotation can already have recreated the log. An unexpected new
        # object, especially a symlink, must not make the exception broader.
        try:
            info = path.lstat()
        except FileNotFoundError:
            return True
        return stat.S_ISREG(info.st_mode)
    except OSError:
        return False


def analyze(stderr_path: Path, exit_code: int, loxberry_home: Path) -> dict:
    if exit_code != 24:
        return _result(False, "not_rsync_exit_24")
    if not str(loxberry_home).startswith("/") or str(loxberry_home) == "/":
        return _result(False, "invalid_loxberry_home")
    # The worker creates this file exclusively in its private root-state
    # directory. O_NOFOLLOW and fstat also prevent reading a substituted link,
    # FIFO or other non-regular object here.
    fd = None
    try:
        fd = os.open(stderr_path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            return _result(False, "invalid_diagnostic_file")
        if stderr_path.is_symlink():
            return _result(False, "invalid_diagnostic_file")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (len(raw) != info.st_size or len(raw) > MAX_BYTES
                or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            return _result(False, "incomplete_diagnostic_file")
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeError, ValueError):
        return _result(False, "unreadable_diagnostic_file")
    finally:
        if fd is not None:
            os.close(fd)
    if not text.endswith("\n") or any((ord(c) < 32 and c != "\n") or ord(c) == 127 for c in text):
        return _result(False, "incomplete_or_ambiguous_diagnostics")
    lines = text[:-1].split("\n")
    if not 2 <= len(lines) <= MAX_FILES + 1 or not SUMMARY.fullmatch(lines[-1]):
        return _result(False, "missing_or_unrecognized_exit_summary")
    for line in lines[:-1]:
        match = VANISHED.fullmatch(line)
        if not match or not _known_log(match[1], loxberry_home):
            return _result(False, "unknown_file_or_additional_diagnostic")
    return _result(True, "known_runtime_logs_only", len(lines) - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--loxberry-home", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.stderr, args.exit_code, args.loxberry_home)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
