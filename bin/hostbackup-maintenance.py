#!/usr/bin/env python3
"""Explicit maintenance operations; the backend holds operation/backup locks.

Reports distinguish logical bytes from unique allocated blocks, a newly recorded
integrity baseline from a verified one, and inspected data from tested restores.
All durable reports and protection settings live in the root-controlled state.
"""
import argparse
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
import unicodedata
import zipfile

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
MAX_JSON = 16 * 1024 * 1024
MAX_ENTRIES = 2_000_000
MAX_LOG = 100 * 1024 * 1024
MAX_RESTORE_TESTS = 20
MAX_RESTORE_NOTE = 2000
GOOD = {("complete", "ok"), ("complete_with_warnings", "warning")}
TERMINAL_BAD = {"failed", "stopped", "cleanup_failed", "aborted"}


def fail(message):
    raise ValueError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identifier(value):
    if not ID.fullmatch(value) or ".." in value:
        fail("Invalid backup or task identifier.")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def real_dir(path):
    path = pathlib.Path(path).absolute()
    if path.is_symlink() or not path.is_dir():
        fail(f"Expected a real directory: {path.name}.")
    # Reject symlink components, including an apparently safe final directory.
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            fail("Directory path contains a symlink.")
    return path


def file_info(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        fail(f"Expected a regular file: {path.name}.")
    return info


def read_bytes(path, limit=MAX_JSON):
    info = file_info(path)
    if info.st_size > limit:
        fail(f"File exceeds the inspection limit: {path.name}.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        actual = os.fstat(source.fileno())
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            fail("File changed while opening it.")
        data = source.read(limit + 1)
    if len(data) > limit:
        fail("File grew beyond the inspection limit.")
    return data


def read_json(path, default=None):
    if not path.exists() and not path.is_symlink() and default is not None:
        return default
    data = json.loads(read_bytes(path))
    if not isinstance(data, dict):
        fail(f"JSON object required: {path.name}.")
    return data


def atomic_json(path, value):
    real_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".maintenance-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def state_dir(state, child):
    state = real_dir(state)
    info = state.stat()
    if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        fail("Maintenance state must be root-owned and protected.")
    target = state / child
    target.mkdir(mode=0o700, exist_ok=True)
    real_dir(target)
    return target


def root_identity(root):
    root = real_dir(root)
    marker = read_bytes(root / ".loxberry-hostbackup-target", 4096).decode().strip()
    if not marker:
        fail("Backup target marker is empty.")
    return {"path": str(root), "marker": marker}


def backup_record(root, backup_id):
    identifier(backup_id)
    target = real_dir(root / backup_id)
    if target.parent != root or target.stat().st_dev != root.stat().st_dev:
        fail("Backup leaves the target filesystem.")
    manifest = read_json(target / "manifest.json")
    marker = read_bytes(target / ".loxberry-hostbackup-backup", 4096).decode().strip()
    if manifest.get("backup_id") != backup_id or marker != backup_id:
        fail("Backup marker or manifest identity mismatch.")
    validation = read_json(target / "backup-validation.json", {})
    info = (target / "manifest.json").stat()
    result = {"backup_id": backup_id, "status": manifest.get("status", "unknown"),
              "validation_status": validation.get("status", "unknown"),
              "good": (manifest.get("status"), validation.get("status")) in GOOD,
              "finished_at": manifest.get("finished_at", ""),
              "mtime_ns": info.st_mtime_ns,
              "manifest_sha256": hashlib.sha256(read_bytes(target / "manifest.json")).hexdigest(),
              "inode": [target.stat().st_dev, target.stat().st_ino]}
    return target, result


def records(root):
    result, ignored = [], []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir() or entry.is_symlink():
            continue
        try:
            _, record = backup_record(root, entry.name)
            result.append(record)
        except (OSError, ValueError) as error:
            ignored.append({"name": entry.name, "reason": str(error)})
    return result, ignored


def walk_data(path):
    """Yield lstat entries without following symlinks or crossing a mount."""
    root = real_dir(path)
    device, stack, count = root.stat().st_dev, [root], 0
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            count += 1
            if count > MAX_ENTRIES:
                fail("Backup exceeds the maximum inspected entry count.")
            info = os.stat(entry.path, follow_symlinks=False)
            if info.st_dev != device:
                fail("Backup contains an unexpected mounted filesystem.")
            child = pathlib.Path(entry.path)
            yield child, child.relative_to(root).as_posix(), info
            if stat.S_ISDIR(info.st_mode):
                stack.append(child)


def allocated(info):
    return getattr(info, "st_blocks", (info.st_size + 511) // 512) * 512


def tree_storage(path, global_inodes=None):
    base_info = real_dir(path).stat()
    base_inode = (base_info.st_dev, base_info.st_ino)
    local = {base_inode}
    total, logical, rootfs_logical, shared, unique = allocated(base_info), 0, 0, 0, 0
    if global_inodes is not None and base_inode not in global_inodes:
        unique = total
        global_inodes.add(base_inode)
    for _, relative, info in walk_data(path):
        inode = (info.st_dev, info.st_ino)
        if stat.S_ISREG(info.st_mode):
            logical += info.st_size
            if relative.startswith("rootfs/"):
                rootfs_logical += info.st_size
            if info.st_nlink > 1:
                shared += 1
        if inode not in local:
            total += allocated(info)
            local.add(inode)
        if global_inodes is not None and inode not in global_inodes:
            unique += allocated(info)
            global_inodes.add(inode)
    return {"logical_bytes": logical, "rootfs_logical_bytes": rootfs_logical, "allocated_bytes": total,
            "shared_file_count": shared, "unique_added_bytes": unique}


def pins_path(root, state):
    key = digest(root_identity(root))
    return state_dir(state, "maintenance") / f"pins-{key}.json"


def pins(root, state):
    data = read_json(pins_path(root, state), {"backup_ids": []})
    values = data.get("backup_ids")
    if not isinstance(values, list) or not all(isinstance(item, str) and ID.fullmatch(item) for item in values):
        fail("Invalid backup protection settings.")
    return set(values)


def protect(root, state, backup_id, value):
    backup_record(root, backup_id)
    protected = pins(root, state)
    if value:
        protected.add(backup_id)
    else:
        protected.discard(backup_id)
    atomic_json(pins_path(root, state), {"backup_ids": sorted(protected), "updated_at": now()})
    return {"backup_id": backup_id, "pinned": value}


def runtime_storage(state):
    state = real_dir(state)
    result = {"measurement": "allocated_blocks", "free_bytes": shutil.disk_usage(state).free,
              "total_bytes": tree_storage(state)["allocated_bytes"]}
    for key, name in (("logs_bytes", "logs"), ("quarantine_bytes", "import-quarantine"),
                      ("integrity_bytes", "integrity")):
        directory = state / name
        result[key] = tree_storage(directory)["allocated_bytes"] if directory.exists() or directory.is_symlink() else 0
    return result


def storage(root, state):
    root_identity(root)
    backups, ignored = records(root)
    protected, all_inodes = pins(root, state), set()
    failed_bytes = 0
    for record in backups:
        record.update(tree_storage(root / record["backup_id"], all_inodes))
        target = root / record["backup_id"]
        if (target / "rootfs").is_dir() and not (target / "rootfs").is_symlink():
            record["logical_bytes"] = record.pop("rootfs_logical_bytes")
        elif (target / "rootfs.tar").is_file() and not (target / "rootfs.tar").is_symlink():
            with tarfile.open(target / "rootfs.tar", "r:") as container:
                record["logical_bytes"] = sum(member.size for member in container if member.isfile())
        record["pinned"] = record["backup_id"] in protected
        if record["status"] in TERMINAL_BAD:
            failed_bytes += record["allocated_bytes"]
    backup_allocation = sum(item["unique_added_bytes"] for item in backups)
    export_allocation = 0
    for entry in root.iterdir():
        if entry.name.endswith((".tar.gz", ".tar.gz.sha256", ".tar.gz.json")) and not entry.is_symlink() and entry.is_file():
            info = file_info(entry)
            inode = (info.st_dev, info.st_ino)
            if inode not in all_inodes:
                export_allocation += allocated(info)
                all_inodes.add(inode)
    return {"status": "ok", "measured_at": now(), "expensive": True, "backups": backups,
            "backups_unique_allocated_bytes": backup_allocation, "exports_bytes": export_allocation,
            "failed_bytes": failed_bytes,
            "total_unique_allocated_bytes": backup_allocation + export_allocation,
            "shared_file_count_note": "Files with nlink > 1, including links within one backup",
            "measured_scope": "Recognized backup directories and export files; other target data is not included",
            "failed_bytes_are_reclaimable": False,
            "root_state": runtime_storage(state),
            "ignored": ignored}


def file_hash(path, info):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
            fail("File changed during integrity inspection.")
        hasher = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
        after = os.fstat(source.fileno())
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            fail("File changed during integrity inspection.")
    return hasher.hexdigest()


def integrity_entries(target, connection):
    rootfs = target / "rootfs"
    if rootfs.is_symlink():
        fail("Backup rootfs must not be a symlink.")
    items = walk_data(rootfs) if rootfs.is_dir() else [(target / "rootfs.tar", "rootfs.tar", file_info(target / "rootfs.tar"))]
    for path, relative, info in items:
        value = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}
        if stat.S_ISREG(info.st_mode):
            inode = (info.st_dev, info.st_ino)
            cache_key = f"{inode[0]}:{inode[1]}"
            cached = connection.execute("SELECT hash, first_path FROM inode_cache WHERE inode=?", (cache_key,)).fetchone()
            if cached is None:
                cached = (file_hash(path, info), relative)
                connection.execute("INSERT INTO inode_cache VALUES(?,?,?)", (cache_key, *cached))
            value.update(type="file", size=info.st_size, sha256=cached[0],
                         hardlink_group=cached[1], allocated_bytes=allocated(info))
        elif stat.S_ISLNK(info.st_mode):
            value.update(type="symlink", target=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            value.update(type="directory")
        else:
            value.update(type="special", device=info.st_rdev)
        # xattrs contain ACLs/capabilities on Linux. Absence of API support is
        # explicit so a report cannot claim those values were compared.
        if hasattr(os, "listxattr"):
            try:
                value["xattrs"] = {name: hashlib.sha256(os.getxattr(path, name, follow_symlinks=False)).hexdigest()
                                   for name in sorted(os.listxattr(path, follow_symlinks=False))}
            except OSError as error:
                value["xattrs_unreadable"] = error.errno
        yield relative, value


def integrity_paths(root, state, backup_id):
    target, record = backup_record(root, backup_id)
    identity = {"root": root_identity(root), "backup_id": backup_id,
                "backup_marker": read_bytes(target / ".loxberry-hostbackup-backup", 4096).decode().strip()}
    key = digest(identity)
    directory = state_dir(state, "integrity")
    return target, record, identity, directory / f"{key}.baseline.sqlite", directory / f"{key}.report.json"


def test_timestamp(value, reject_future=False):
    if not isinstance(value, str) or not value or len(value) > 128:
        fail("Restore test time must be an ISO8601 timestamp with timezone.")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            fail("Restore test time requires an explicit timezone.")
        parsed = parsed.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError) as error:
        fail(f"Invalid restore test time: {error}")
    if reject_future and parsed > dt.datetime.now(dt.timezone.utc):
        fail("Restore test time cannot be in the future.")
    return parsed


def restore_note(value):
    if not isinstance(value, str) or len(value) > MAX_RESTORE_NOTE:
        fail("Restore test note must be at most 2000 characters.")
    return "".join(" " if unicodedata.category(character) in ("Cc", "Cf", "Cs") else character
                   for character in value).strip()


def restore_history_path(state, identity):
    return state_dir(state, "integrity") / f"{digest(identity)}.restore-tests.json"


def load_restore_history(path, identity):
    if not path.exists() and not path.is_symlink():
        return []
    if file_info(path).st_nlink != 1:
        fail("Unsafe restore test history hardlink.")
    data = json.loads(read_bytes(path, 1024 * 1024))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("identity") != identity:
        fail("Restore test history identity mismatch.")
    tests = data.get("tests")
    if not isinstance(tests, list) or len(tests) > MAX_RESTORE_TESTS:
        fail("Invalid or oversized restore test history.")
    for item in tests:
        if (not isinstance(item, dict) or item.get("result") not in ("passed", "failed")
                or item.get("source") != "manual-user-report"
                or not isinstance(item.get("manifest_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", item["manifest_sha256"])):
            fail("Invalid restore test history entry.")
        test_timestamp(item.get("tested_at"))
        test_timestamp(item.get("recorded_at"))
        if restore_note(item.get("note")) != item["note"]:
            fail("Restore test history contains unsanitized note controls.")
    return sorted(tests, key=lambda item: (test_timestamp(item["tested_at"]), test_timestamp(item["recorded_at"])), reverse=True)


def restore_test_summary(state, identity, record):
    tests = load_restore_history(restore_history_path(state, identity), identity)
    history = [{**item, "applies_to_current_manifest": item["manifest_sha256"] == record["manifest_sha256"]}
               for item in tests]
    latest = history[0] if history else None
    return {"backup_id": identity["backup_id"],
            "restore_tested": bool(latest and latest["result"] == "passed" and latest["applies_to_current_manifest"]),
            "restore_test": latest, "restore_test_history": history,
            "restore_test_evidence": "manual-user-report" if latest else "none"}


def record_restore_test(root, state, backup_id, result, tested_at, note):
    if result not in ("passed", "failed"):
        fail("Restore test result must be passed or failed.")
    tested_at = test_timestamp(tested_at, reject_future=True).isoformat()
    note = restore_note(note)
    _, record, identity, _, _ = integrity_paths(root, state, backup_id)
    path = restore_history_path(state, identity)
    tests = load_restore_history(path, identity)
    tests.append({"result": result, "tested_at": tested_at, "note": note,
                  "recorded_at": now(), "source": "manual-user-report",
                  "manifest_sha256": record["manifest_sha256"]})
    tests.sort(key=lambda item: (test_timestamp(item["tested_at"]), test_timestamp(item["recorded_at"])), reverse=True)
    # This is only the user's dated assertion, never an autonomous restore
    # certification. No backup manifest, validation or restore gate is changed.
    atomic_json(path, {"schema_version": 1, "identity": identity, "tests": tests[:MAX_RESTORE_TESTS]})
    return restore_test_summary(state, identity, record)


def forget_integrity(root, state, backup_id, marker):
    """Internal post-deletion cleanup under the backend's exclusive lock."""
    identifier(backup_id)
    if marker != backup_id:
        fail("Deleted backup marker does not match its identifier.")
    identity = {"root": root_identity(root), "backup_id": backup_id, "backup_marker": marker}
    target = root / backup_id
    if target.exists() or target.is_symlink():
        fail("Integrity state must be retained while the backup still exists.")
    directory = state_dir(state, "integrity")
    key = digest(identity)
    paths = []
    for suffix in ("baseline.sqlite", "report.json", "restore-tests.json"):
        path = directory / f"{key}.{suffix}"
        if not path.exists() and not path.is_symlink():
            continue
        info = file_info(path)
        if info.st_nlink != 1:
            fail("Unsafe integrity state hardlink.")
        if suffix == "baseline.sqlite":
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
                database.execute("PRAGMA trusted_schema=OFF")
                row = database.execute("SELECT value FROM metadata WHERE name='identity'").fetchone()
            recorded = json.loads(row[0]) if row else None
            if not isinstance(recorded, dict) or recorded.get("identity") != identity:
                fail("Integrity baseline belongs to a different backup identity.")
        elif suffix == "restore-tests.json":
            load_restore_history(path, identity)
        elif read_json(path).get("backup_id") != backup_id:
            fail("Integrity report belongs to a different backup identifier.")
        paths.append((path, info))
    # Validate every associated file before unlinking any of them. There is no
    # filename glob or scan of other backups' baselines in this operation.
    for path, previous in paths:
        fresh = file_info(path)
        if (fresh.st_dev, fresh.st_ino, fresh.st_mtime_ns, fresh.st_size, fresh.st_nlink) != (
                previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_size, 1):
            fail("Integrity state changed during deletion cleanup.")
        path.unlink()
    return {"backup_id": backup_id, "removed": [path.name for path, _ in paths]}


def integrity(root, state, backup_id, report_only=False, record_only=False):
    target, record, identity, baseline_path, report_path = integrity_paths(root, state, backup_id)
    if report_only:
        report = read_json(report_path, {"backup_id": backup_id, "status": "not_checked",
                                         "content_verified": False, "restore_tested": False})
        if report.get("manifest_sha256", record["manifest_sha256"]) != record["manifest_sha256"]:
            report = {"backup_id": backup_id, "status": "stale", "content_verified": False,
                      "message": "Manifest changed since the recorded inspection."}
        return {**report, **restore_test_summary(state, identity, record)}
    if not record["good"]:
        fail("Only completed validated backups can have an integrity baseline.")
    baseline = None
    if baseline_path.exists() or baseline_path.is_symlink():
        info = file_info(baseline_path)
        if info.st_nlink != 1:
            fail("Unsafe integrity baseline hardlink.")
        with closing(sqlite3.connect(baseline_path.as_uri() + "?mode=ro", uri=True)) as previous:
            previous.execute("PRAGMA trusted_schema=OFF")
            baseline = json.loads(previous.execute("SELECT value FROM metadata WHERE name='identity'").fetchone()[0])
        if baseline.get("identity") != identity or baseline.get("manifest_sha256") != record["manifest_sha256"]:
            fail("Integrity baseline identity/manifest mismatch; it must not be silently replaced.")
        if record_only:
            return {"backup_id": backup_id, "status": "baseline_exists", "content_verified": False,
                    "baseline_at": baseline["created_at"], **restore_test_summary(state, identity, record)}
    checked, changes, checked_files, change_count = now(), [], 0, 0
    fd, temporary = tempfile.mkstemp(prefix=".integrity-scan-", dir=baseline_path.parent)
    os.close(fd)
    connection = sqlite3.connect(temporary, uri=True)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA journal_mode=OFF")
        # Keep state storage bounded and reserve room for logs and restart
        # journals even when an optional integrity scan covers millions of files.
        database_budget = min(2 * 1024**3, shutil.disk_usage(baseline_path.parent).free - 256 * 1024**2)
        if database_budget < 16 * 1024**2:
            fail("Not enough free local state storage for the integrity index and reserve.")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={database_budget // page_size}")
        connection.execute("CREATE TABLE entries(path TEXT PRIMARY KEY,value TEXT NOT NULL)")
        connection.execute("CREATE TABLE inode_cache(inode TEXT PRIMARY KEY,hash TEXT NOT NULL,first_path TEXT NOT NULL)")
        connection.execute("CREATE TABLE metadata(name TEXT PRIMARY KEY,value TEXT NOT NULL)")
        total = 0
        for relative, value in integrity_entries(target, connection):
            connection.execute("INSERT INTO entries VALUES(?,?)", (relative, json.dumps(value, sort_keys=True)))
            total += 1
            checked_files += value["type"] == "file"
        if not total or not checked_files:
            fail("Cannot create an integrity baseline for empty backup data.")
        connection.execute("DROP TABLE inode_cache")
        if baseline is None:
            baseline = {"identity": identity, "manifest_sha256": record["manifest_sha256"], "created_at": checked}
            connection.execute("INSERT INTO metadata VALUES('identity',?)", (json.dumps(baseline),))
            status = "baseline_created"
            connection.commit()
            connection.close()
            os.chmod(temporary, 0o600)
            os.replace(temporary, baseline_path)
        else:
            connection.execute("ATTACH DATABASE ? AS baseline", (baseline_path.as_uri() + "?mode=ro",))
            query = """
SELECT current.path AS path,'added' AS change FROM entries current
 LEFT JOIN baseline.entries old ON old.path=current.path WHERE old.path IS NULL
UNION ALL SELECT old.path,'missing' FROM baseline.entries old
 LEFT JOIN entries current ON current.path=old.path WHERE current.path IS NULL
UNION ALL SELECT current.path,'changed' FROM entries current
 JOIN baseline.entries old ON old.path=current.path WHERE current.value<>old.value
"""
            change_count = connection.execute("SELECT count(*) FROM (" + query + ")").fetchone()[0]
            changes = [{"path": path, "change": change} for path, change in
                       connection.execute(query + " ORDER BY path LIMIT 1000")]
            status = "changed" if change_count else "verified"
    finally:
        connection.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
    report = {"backup_id": backup_id, "status": status, "checked_at": checked,
              "baseline_at": baseline["created_at"], "manifest_sha256": record["manifest_sha256"],
              "checked_files": checked_files,
              "changes": changes, "change_count": change_count,
              "changes_truncated": change_count > 1000, "content_verified": status == "verified",
              "metadata_compared": ["mode", "uid", "gid", "symlink-target", "xattrs-when-readable"],
              "restore_tested": False}
    atomic_json(report_path, report)
    return {**report, **restore_test_summary(state, identity, record)}


def numeric(config, key, default, low, high):
    value = config.get(key, default)
    if type(value) is not int or not low <= value <= high:
        fail(f"Invalid maintenance setting: {key}.")
    return value


def policy(config):
    mode = config.get("retention_mode", "count")
    if mode not in ("count", "gfs"):
        fail("Invalid retention mode.")
    result = {"mode": mode, "count": numeric(config, "keep_backups", 10, 1, 3650),
              "daily": numeric(config, "keep_daily", 7, 0, 3650),
              "weekly": numeric(config, "keep_weekly", 4, 0, 520),
              "monthly": numeric(config, "keep_monthly", 6, 0, 120)}
    if mode == "gfs" and not any(result[key] for key in ("daily", "weekly", "monthly")):
        fail("At least one GFS retention bucket must be greater than zero.")
    return result


def backup_time(record):
    try:
        parsed = dt.datetime.fromisoformat(record["finished_at"].replace("Z", "+00:00"))
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return dt.datetime.fromtimestamp(record["mtime_ns"] / 1e9, dt.timezone.utc)


def task_active(data):
    if data.get("state") not in ("running", "queued"):
        return False
    pid, ticks = data.get("pid"), str(data.get("process_start_ticks", ""))
    if type(pid) is not int or pid < 2:
        return data.get("state") == "queued" and time.time() - data.get("updated_at", 0) < 300
    try:
        # Linux stat's comm may contain spaces and parentheses; fields after its
        # final ')' start at field 3. Field 22 is the process start tick count.
        proc = pathlib.Path(f"/proc/{pid}/stat").read_text()
        return bool(ticks) and proc.rpartition(")")[2].split()[19] == ticks
    except (OSError, IndexError):
        return False


def active_tasks(state, caller_pid=None):
    directory = pathlib.Path(state) / "tasks"
    if not directory.exists():
        return []
    real_dir(directory)
    active = []
    for entry in directory.glob("*.json"):
        if entry.is_symlink():
            fail("Unsafe task state symlink.")
        data = read_json(entry)
        if task_active(data) and data.get("pid") != caller_pid:
            active.append(data.get("task", entry.name.removesuffix(".json")))
    return sorted(active)


def export_files(root, backup_id):
    result = []
    for suffix in (".tar.gz", ".tar.gz.sha256", ".tar.gz.json"):
        path = root / (backup_id + suffix)
        if not path.exists() and not path.is_symlink():
            continue
        info = file_info(path)
        if info.st_nlink != 1 or info.st_dev != root.stat().st_dev:
            fail("Unsafe export file in retention plan.")
        result.append({"name": path.name, "mtime_ns": info.st_mtime_ns,
                       "size_bytes": info.st_size, "inode": [info.st_dev, info.st_ino]})
    return result


def delete_check(root, state, backup_id):
    root_identity(root)
    backup_record(root, backup_id)
    if backup_id in pins(root, state):
        fail("Backup ist geschuetzt. Schutz vor dem Loeschen bewusst aufheben.")
    backups, _ = records(root)
    good = sorted((item for item in backups if item["good"]), key=backup_time, reverse=True)
    if good and good[0]["backup_id"] == backup_id:
        fail("Die juengste brauchbare Sicherung bleibt geschuetzt; zuerst ein neues erfolgreiches Backup erstellen.")
    return {"backup_id": backup_id, "allowed": True}


def retention(root, state, config, apply=None, caller_pid=None):
    identity = root_identity(root)
    selected = policy(config)
    backups, ignored = records(root)
    protected = pins(root, state)
    good = sorted((item for item in backups if item["good"]), key=backup_time, reverse=True)
    reasons = {item["backup_id"]: [] for item in backups}
    latest = good[0]["backup_id"] if good else None
    if latest:
        reasons[latest].append("latest-good-backup")
    for backup_id in protected:
        if backup_id in reasons:
            reasons[backup_id].append("user-protected")
    if selected["mode"] == "count":
        for item in good[:selected["count"]]:
            reasons[item["backup_id"]].append("count-policy")
    else:
        for name, bucket in (("daily", lambda value: value.date().isoformat()),
                             ("weekly", lambda value: value.strftime("%G-W%V")),
                             ("monthly", lambda value: value.strftime("%Y-%m"))):
            retained = set()
            for item in good:
                key = bucket(backup_time(item))
                if key not in retained and len(retained) < selected[name]:
                    retained.add(key)
                    reasons[item["backup_id"]].append(name)
    current_tasks = active_tasks(state, caller_pid)
    keep, delete = [], []
    for item in backups:
        why = reasons[item["backup_id"]]
        if not item["good"]:
            # Failed/partial backups require separate explicit selection. Never
            # infer from an age alone that an interrupted writer has finished.
            why.append("incomplete-backup-review-required")
        if current_tasks:
            why.append("active-operation")
        if why:
            keep.append({"backup_id": item["backup_id"], "reasons": why})
        else:
            usage = tree_storage(root / item["backup_id"])
            delete.append({**item, "allocated_bytes": usage["allocated_bytes"],
                           "exports": export_files(root, item["backup_id"])})
    binding = {"root": identity, "policy": selected, "pins": sorted(protected),
               "records": backups, "tasks": current_tasks, "delete": delete}
    preview_digest = digest(binding)
    cleanup_warnings = []
    if apply is not None:
        if apply != preview_digest:
            fail("Maintenance preview is stale; review the current deletion plan first.")
        for item in delete:
            target, fresh = backup_record(root, item["backup_id"])
            if fresh != next(record for record in backups if record["backup_id"] == item["backup_id"]):
                fail("Backup changed after the deletion preview.")
            # Walk first to reject mounted children and enumerate a safe tree.
            list(walk_data(target))
            if export_files(root, item["backup_id"]) != item["exports"]:
                fail("Associated export changed after the deletion preview.")
            for export in item["exports"]:
                (root / export["name"]).unlink()
            shutil.rmtree(target)
            try:
                forget_integrity(root, state, item["backup_id"], item["backup_id"])
            except (OSError, ValueError, sqlite3.Error) as error:
                # The backup has already been removed. Report a local-index
                # cleanup problem without claiming that deletion did not occur.
                cleanup_warnings.append({"backup_id": item["backup_id"], "message": str(error)})
    return {"policy": selected, "keep": keep, "delete": delete, "ignored": ignored,
            "protected_latest": latest, "preview_digest": preview_digest,
            "cleanup_warnings": cleanup_warnings,
            "active_tasks": current_tasks, "applied": apply is not None}


def integrity_due(root, state, config):
    enabled = config.get("integrity_enabled", False)
    if type(enabled) is not bool:
        fail("Invalid integrity_enabled setting.")
    interval = numeric(config, "integrity_interval_days", 7, 1, 365)
    due = []
    live_checks = [task for task in active_tasks(state) if str(task).startswith("verify-")]
    if live_checks:
        return {"enabled": enabled, "interval_days": interval, "backup_ids": [],
                "active_verifications": live_checks}
    if enabled:
        backups, _ = records(root)
        attempts = {}
        task_directory = pathlib.Path(state) / "tasks"
        if task_directory.exists():
            real_dir(task_directory)
            for path in task_directory.glob("verify-*.log.json"):
                name = re.fullmatch(r"verify-(.+)-[0-9]+-[0-9]+\.log\.json", path.name)
                if not name:
                    continue
                data = read_json(path)
                attempted = data.get("updated_at", 0)
                if isinstance(attempted, (int, float)):
                    attempts[name[1]] = max(attempts.get(name[1], 0), attempted)
        for record in backups:
            if not record["good"]:
                continue
            report = integrity(root, state, record["backup_id"], report_only=True)
            try:
                checked = dt.datetime.fromisoformat(report.get("checked_at", "")).timestamp()
            except (ValueError, TypeError):
                checked = 0
            if checked < time.time() - interval * 86400 or report.get("status") == "stale":
                due.append((max(checked, attempts.get(record["backup_id"], 0)), record["backup_id"]))
    return {"enabled": enabled, "interval_days": interval, "backup_ids": [item[1] for item in sorted(due)],
            "active_verifications": []}


def cleanup_runtime(state, config, apply=None):
    state = real_dir(state)
    active = active_tasks(state)
    # Open restart journals are deliberately outside cleanup's allowed trees.
    limits = {"logs": numeric(config, "log_retention_days", 30, 1, 3650),
              "import-quarantine": numeric(config, "quarantine_retention_days", 7, 1, 3650)}
    selected = []
    for subdir, days in limits.items():
        directory = state / subdir
        if not directory.exists():
            continue
        real_dir(directory)
        for entry in sorted(directory.iterdir()):
            if len(selected) >= 10000:
                break
            if entry.is_symlink() or not entry.is_file() or entry.name in active:
                continue
            info = file_info(entry)
            if info.st_nlink != 1 or info.st_mtime >= time.time() - days * 86400:
                continue
            selected.append({"directory": subdir, "name": entry.name,
                             "size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
                             "inode": [info.st_dev, info.st_ino]})
    preview_digest = digest({"state": str(state), "limits": limits, "active": active, "files": selected})
    if apply is not None:
        if apply != preview_digest:
            fail("Runtime cleanup preview is stale; review the current plan first.")
        for item in selected:
            path = state / item["directory"] / item["name"]
            info = file_info(path)
            if [info.st_dev, info.st_ino] != item["inode"] or info.st_mtime_ns != item["mtime_ns"]:
                fail("Runtime file changed since cleanup preview.")
            path.unlink()
    return {"files": selected, "limits_days": limits, "preview_digest": preview_digest,
            "active_tasks": active, "applied": apply is not None}


def redacted_config(config):
    allowed = {"backup_mode", "metadata_mode", "keep_backups", "retention_mode", "keep_daily",
               "keep_weekly", "keep_monthly", "schedule_enabled", "schedule_mode", "schedule_time",
               "schedule_weekdays", "schedule_monthdays", "schedule_months", "integrity_enabled",
               "integrity_interval_days", "log_retention_days", "quarantine_retention_days"}
    result = {key: value for key, value in config.items() if key in allowed}
    for name in ("rsync_extra_excludes", "stop_targets"):
        result[name + "_count"] = len(config.get(name, [])) if isinstance(config.get(name), list) else 0
    result["backup_root_configured"] = bool(config.get("backup_root"))
    result["redacted_fields"] = sorted(key for key in config if key not in allowed)
    return result


def diagnostics(root, state, config, version, task=None, output=None):
    state = real_dir(state)
    candidate = root
    if candidate is None and isinstance(config.get("backup_root"), str) and config["backup_root"]:
        candidate = pathlib.Path(config["backup_root"])
    log = None
    task_status = {}
    if task:
        identifier(task)
        log = real_dir(state / "logs") / task
        if file_info(log).st_size > MAX_LOG:
            fail("Selected log exceeds 100 MiB; download it separately.")
        if shutil.disk_usage(state).free < file_info(log).st_size + 64 * 1024**2:
            fail("Not enough local space to prepare the selected full diagnostic log.")
        task_status = read_json(real_dir(state / "tasks") / f"{task}.json", {})
        task_status.pop("log_file", None)
    mounts = []
    mountinfo = pathlib.Path("/proc/self/mountinfo")
    if mountinfo.is_file():
        for number, line in enumerate(mountinfo.read_text().splitlines(), 1):
            before, _, after = line.partition(" - ")
            fields = before.split()
            mounts.append({"mount": "root" if len(fields) > 4 and fields[4] == "/" else f"mount_{number}",
                           "filesystem": after.split()[0] if after else "unknown"})
    report = {"created_at": now(), "plugin_version": version,
              "target_configured": bool(config.get("backup_root")),
              "target_available": bool(candidate and candidate.is_dir() and not candidate.is_symlink()),
              "target_identity_verified": False,
              "configuration": redacted_config(config), "task": task_status,
              "mounts": mounts, "warning": "Selected full log may contain private paths, hostnames or addresses."}
    with tempfile.TemporaryFile(dir=state) as spool:
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps(report, indent=2, sort_keys=True))
            archive.writestr("READ-ME.txt", "Configuration and mount names are redacted. The selected original log is complete and may contain sensitive data; review before sharing.\n")
            if log:
                info = file_info(log)
                fd = os.open(log, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as source, archive.open("selected-task.log", "w") as target:
                    remaining = min(info.st_size, MAX_LOG)
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        target.write(block)
                        remaining -= len(block)
        size = spool.tell()
        spool.seek(0)
        stream = output or sys.stdout.buffer
        stream.write(("Content-Type: application/zip\r\nContent-Disposition: attachment; filename=\"HostBackup-Diagnostics.zip\"\r\n"
                      f"Content-Length: {size}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n").encode())
        shutil.copyfileobj(spool, stream, 1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("storage", "integrity", "integrity-due", "record-restore-test", "forget-integrity", "delete-check", "pins", "protect", "retention", "cleanup-runtime", "diagnostics"))
    parser.add_argument("root", nargs="?")
    parser.add_argument("backup_id", nargs="?")
    parser.add_argument("value", nargs="?", choices=("true", "false"))
    parser.add_argument("--state", required=True)
    parser.add_argument("--config")
    parser.add_argument("--version", default="unknown")
    parser.add_argument("--task")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--apply")
    parser.add_argument("--caller-pid", type=int)
    parser.add_argument("--marker")
    parser.add_argument("--result", choices=("passed", "failed"))
    parser.add_argument("--tested-at")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    config = read_json(pathlib.Path(args.config)) if args.config else {}
    root = real_dir(args.root) if args.root else None
    if args.action not in ("cleanup-runtime", "diagnostics") and root is None:
        parser.error("root is required")
    if args.action in ("integrity", "protect", "record-restore-test", "forget-integrity", "delete-check") and not args.backup_id:
        parser.error("backup_id is required")
    if args.action == "storage":
        result = storage(root, args.state)
    elif args.action == "pins":
        result = {"backup_ids": sorted(pins(root, args.state))}
    elif args.action == "integrity-due":
        result = integrity_due(root, args.state, config)
    elif args.action == "integrity":
        result = integrity(root, args.state, args.backup_id, args.report, args.record)
    elif args.action == "record-restore-test":
        result = record_restore_test(root, args.state, args.backup_id, args.result, args.tested_at, args.note)
    elif args.action == "forget-integrity":
        result = forget_integrity(root, args.state, args.backup_id, args.marker)
    elif args.action == "delete-check":
        result = delete_check(root, args.state, args.backup_id)
    elif args.action == "protect":
        if args.value is None:
            parser.error("true or false protection value is required")
        result = protect(root, args.state, args.backup_id, args.value == "true")
    elif args.action == "retention":
        result = retention(root, args.state, config, args.apply, args.caller_pid)
    elif args.action == "cleanup-runtime":
        result = cleanup_runtime(args.state, config, args.apply)
    else:
        diagnostics(root, args.state, config, args.version, args.task)
        return
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"HostBackup maintenance: {error}", file=sys.stderr)
        sys.exit(1)
