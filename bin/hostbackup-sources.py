#!/usr/bin/env python3
"""Plan backup sources without walking unselected network/automounter mounts.

The files command emits a complete, NUL-delimited, non-recursive copy list. The
caller must check its exit status before rsync/tar consumes that list. In
particular, do not pipe a partially generated list directly into a backup.
"""
import argparse
from functools import lru_cache
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


spec = importlib.util.spec_from_file_location("hostbackup_recovery", Path(__file__).with_name("hostbackup-recovery.py"))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)

NETWORK_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "ncpfs", "afs", "openafs", "ceph", "9p", "glusterfs", "lustre", "davfs", "davfs2", "fuse"}
SYSTEM_FS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "debugfs", "securityfs", "pstore", "tracefs", "configfs", "mqueue", "hugetlbfs", "fusectl", "rpc_pipefs", "binfmt_misc", "nsfs", "bpf"}
MAX_SELECTION_BYTES = 65536
MAX_OVERRIDES = 256


class SourceError(ValueError):
    pass


def canonical_path(value, allow_root=False):
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096:
        raise SourceError("Quellpfad muss ein absoluter Pfad sein.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SourceError("Steuerzeichen im Quellpfad sind nicht erlaubt.")
    if value != str(PurePosixPath(value)) or ".." in PurePosixPath(value).parts or value.startswith("//"):
        raise SourceError("Quellpfad muss ohne doppelte Schraegstriche oder Punktsegmente angegeben werden.")
    if value == "/" and not allow_root:
        raise SourceError("Das Root-Dateisystem wird immer gesichert und ist keine waehlbare Zusatzquelle.")
    return value


def normalize_selection(value):
    if value is None:
        return {"policy": "legacy", "overrides": {}}
    if not isinstance(value, dict) or set(value) - {"policy", "overrides"}:
        raise SourceError("Ungueltige Quellenauswahl.")
    if len(json.dumps(value, ensure_ascii=True).encode("utf-8")) > MAX_SELECTION_BYTES:
        raise SourceError("Quellenauswahl ist zu gross.")
    policy = value.get("policy")
    overrides = value.get("overrides", {})
    if policy not in ("local", "legacy") or not isinstance(overrides, dict) or len(overrides) > MAX_OVERRIDES:
        raise SourceError("Quellenauswahl verlangt local/legacy und maximal 256 Pfadentscheidungen.")
    checked = {}
    for path, enabled in overrides.items():
        canonical_path(path)
        if not isinstance(enabled, bool):
            raise SourceError("Eine Quellenauswahl muss true oder false enthalten.")
        checked[path] = enabled
    return {"policy": policy, "overrides": dict(sorted(checked.items()))}


def mount_kind(fstype):
    if fstype == "autofs":
        return "automount"
    if fstype in NETWORK_FS or fstype.startswith("fuse."):
        # Unknown FUSE transports may be remote. fuseblk (local NTFS) remains
        # local; individual FUSE mounts can be explicitly selected.
        return "network"
    return "system" if fstype in SYSTEM_FS else "local"


def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def read_mounts(path="/proc/self/mountinfo"):
    """Use the kernel table, not findmnt traversal or mount options/credentials."""
    try:
        content = Path(path).read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SourceError("Mount-Inventar konnte nicht gelesen werden.") from exc
    mounts = {}
    for line in content.splitlines():
        before, separator, after = line.partition(" - ")
        fields, tail = before.split(), after.split()
        if not separator or len(fields) < 6 or len(tail) < 3:
            raise SourceError("Ungueltiger Eintrag im Mount-Inventar.")
        target = unescape_mount(fields[4])
        canonical_path(target, allow_root=True)
        if not re.fullmatch(r"[0-9]+:[0-9]+", fields[2]):
            raise SourceError("Ungueltige Geraetekennung im Mount-Inventar.")
        mounts[target] = {"path": target, "fstype": tail[0], "kind": mount_kind(tail[0]),
                          "device": fields[2], "mount_id": fields[0]}
    if "/" not in mounts:
        raise SourceError("Root-Dateisystem fehlt im Mount-Inventar.")
    return sorted(mounts.values(), key=lambda item: (item["path"].count("/"), item["path"]))


def beneath(path, parent):
    return path == parent or parent == "/" or path.startswith(parent + "/")


def read_excludes(path):
    if not path:
        return []
    content = recovery.read_control(Path(path))
    if "\x00" in content or "\r" in content:
        raise SourceError("Ungueltige Ausschlussdatei.")
    rules = []
    for line in content.splitlines():
        if not line or line.startswith(("#", ";")):
            continue
        if len(line) > 4096 or ".." in PurePosixPath(line).parts or line == "!" or line.startswith(("+ ", "- ")):
            raise SourceError("Ungueltige Backup-Ausschlussregel.")
        # Validate patterns now, including those which would only affect an
        # otherwise unvisited tree. Use the same matcher as restore planning.
        recovery.wildcard_tokens(line.strip("/"))
        rules.append(line)
    return rules


class SourcePlan:
    def __init__(self, selection, mounts, excludes=()):
        self.selection = normalize_selection(selection)
        self.mounts = {item["path"]: dict(item) for item in mounts}
        if "/" not in self.mounts:
            raise SourceError("Root-Dateisystem fehlt im Mount-Inventar.")
        self.excludes = list(excludes)
        self.literal_excludes = []
        self.pattern_excludes = []
        for rule in self.excludes:
            if any(char in rule for char in "*?["):
                self.pattern_excludes.append(rule)
            else:
                expression = ("^" if rule.startswith("/") else r"(?:^|/)") + re.escape(rule.strip("/"))
                self.literal_excludes.append((re.compile(expression + r"(?=/|$)"), rule.endswith("/")))
        self.errors = []
        self.notices = []
        self.enabled = {}
        self.reasons = {}
        for path in sorted(self.mounts, key=lambda value: (value.count("/"), value)):
            item = self.mounts[path]
            kind = item.get("kind", mount_kind(item["fstype"]))
            item["kind"] = kind
            parent_paths = [p for p in self.enabled if p != path and beneath(path, p)]
            parent = max(parent_paths, key=len) if parent_paths else None
            blocked_parents = []
            for ancestor in sorted(parent_paths, key=len, reverse=True):
                if self.enabled[ancestor]:
                    break
                blocked_parents.append(ancestor)
            ancestor_overrides = [p for p in self.selection["overrides"] if p != path and beneath(path, p)]
            inherited_override = self.selection["overrides"][max(ancestor_overrides, key=len)] if ancestor_overrides else None
            local_automount_child = (
                self.selection["policy"] == "local" and kind == "local"
                and all(self.mounts[p]["kind"] == "automount" for p in blocked_parents)
                and inherited_override is not False
            )
            explicit = self.selection["overrides"].get(path)
            if path == "/":
                included, reason = True, "Root-Dateisystem: immer enthalten."
            elif self.excluded(path, True):
                included, reason = False, "Durch einen Backup-Ausschluss ausgeschlossen."
            elif explicit is False:
                included, reason = False, "In der Quellenauswahl deaktiviert."
            elif explicit is True and kind in ("automount", "system"):
                included, reason = False, "Diese System-/Automount-Quelle kann nicht pauschal aktiviert werden."
                self.errors.append(f"{path}: einzelne eingebundene Datenquelle statt System-/Automount-Verzeichnis auswaehlen.")
            elif explicit is True:
                included, reason = True, "Diese eingebundene Datenquelle ist ausdruecklich ausgewaehlt."
            elif parent and not self.enabled[parent] and not local_automount_child:
                included, reason = False, "Uebergeordnetes Laufwerk ist nicht ausgewaehlt."
            elif self.selection["policy"] == "legacy":
                included, reason = True, "Grundregel Alle eingebundenen Quellen: Quelle wird mitgesichert."
            elif kind == "local":
                included, reason = True, "Lokales Dateisystem ist in der lokalen Quellenauswahl enthalten."
            else:
                included, reason = False, "Netzwerk-/FUSE-, Automount- und Systemquellen sind nicht automatisch enthalten."
            self.enabled[path] = included
            self.reasons[path] = reason
        for path, enabled in self.selection["overrides"].items():
            if enabled and path not in self.mounts:
                self.errors.append(f"Ausgewaehlte Quelle ist nicht eingebunden: {path}. Vor dem Backup einbinden oder bewusst abwaehlen.")
            elif not enabled and path not in self.mounts:
                self.notices.append(f"Deaktivierte Quelle ist momentan nicht eingebunden: {path}.")
        if self.selection["policy"] == "legacy":
            self.notices.append("Alle eingebundenen Quellen: Auch Netzfreigaben werden mitgesichert. Fuer einen begrenzten Umfang lokale Laufwerke waehlen und Netzfreigaben einzeln aktivieren.")
        self.descendant_routes = {}
        for path in self.mounts:
            if path == "/" or not self.included(path):
                continue
            parent = path.rsplit("/", 1)[0] or "/"
            while True:
                self.descendant_routes.setdefault(parent, []).append(path)
                if parent == "/":
                    break
                parent = parent.rsplit("/", 1)[0] or "/"

    @lru_cache(maxsize=4096)
    def nearest_mount(self, path):
        if path in self.mounts:
            return path
        return self.nearest_mount(path.rsplit("/", 1)[0] or "/")

    def excluded(self, path, is_dir):
        relative = path.lstrip("/")
        for pattern, dir_only in self.literal_excludes:
            match = pattern.search(relative)
            if match and (not dir_only or is_dir or match.end() < len(relative)):
                return True
        return recovery.excluded(relative, self.pattern_excludes, is_dir)

    def included(self, path):
        # Also retain explicitly disabled paths when their mount is currently
        # absent; accidentally copying the underlying directory is not useful.
        disabled = [p for p, value in self.selection["overrides"].items() if not value and beneath(path, p)]
        selected = [p for p, value in self.selection["overrides"].items() if value and p in self.mounts and beneath(path, p)]
        if disabled and (not selected or max(map(len, disabled)) > max(map(len, selected))):
            return False
        return self.enabled[self.nearest_mount(path)]

    def selected_descendants(self, path):
        # Also route to already-mounted local USB media beneath an autofs
        # namespace. This does not enumerate/activate unknown autofs children.
        return self.descendant_routes.get(path, ())

    def report(self):
        volumes = []
        for path in sorted(self.mounts):
            item = self.mounts[path]
            forced_excluded = path != "/" and self.excluded(path, True)
            volumes.append({"path": path, "fstype": item["fstype"], "kind": item["kind"],
                            "included": self.included(path), "reason": self.reasons[path],
                            "forced_excluded": forced_excluded,
                            "selectable": path != "/" and not forced_excluded and item["kind"] not in ("system", "automount")})
        return {"selection": self.selection, "volumes": volumes, "notices": self.notices,
                "errors": self.errors, "status": "error" if self.errors else "ok"}


def enumerate_files(plan, root=Path("/")):
    """Yield relative paths exactly once; never recursively list a denied mount.

    root is injectable solely for fixture tests. Production always uses '/'.
    Explicit selected descendants are reached by their known path components,
    without scanning an excluded autofs parent and activating its siblings.
    """
    if plan.errors:
        raise SourceError(" ".join(plan.errors))
    root = Path(root)

    def visit(logical, ancestors):
        included = plan.included(logical)
        descendants = plan.selected_descendants(logical)
        if not included and not descendants:
            return
        if logical in plan.mounts and logical != "/" and plan.excluded(logical, True):
            return
        physical = root if logical == "/" else root / logical.lstrip("/")
        try:
            info = physical.lstat()
        except OSError as exc:
            raise SourceError(f"Quellpfad konnte nicht gelesen werden: {logical}: {exc.strerror or exc}") from exc
        is_dir = stat.S_ISDIR(info.st_mode)
        if logical != "/" and plan.excluded(logical, is_dir):
            return
        if (descendants or logical in plan.selection["overrides"] and plan.selection["overrides"][logical]) and stat.S_ISLNK(info.st_mode):
            raise SourceError(f"Ausgewaehlte Quelle darf nicht ueber einen symbolischen Link fuehren: {logical}")
        expected = plan.mounts[plan.nearest_mount(logical)].get("device")
        if expected and os.name == "posix" and f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != expected:
            raise SourceError(f"Mount-Zuordnung hat sich geaendert: {logical}. Backup erneut pruefen.")
        if not included and not is_dir:
            raise SourceError(f"Pfad zur ausgewaehlten Quelle ist kein Verzeichnis: {logical}")
        yield "." if logical == "/" else logical.lstrip("/")
        if not is_dir:
            return
        identity = (info.st_dev, info.st_ino)
        if identity in ancestors:
            raise SourceError(f"Zyklische Verzeichniseinbindung entdeckt: {logical}")
        parents = ancestors | {identity}
        if included:
            try:
                with os.scandir(physical) as entries:
                    # Names only: DirEntry.is_dir/stat could enter an automount
                    # before the selection decision has been made.
                    names = sorted(entry.name for entry in entries)
            except OSError as exc:
                raise SourceError(f"Quellverzeichnis konnte nicht gelesen werden: {logical}: {exc.strerror or exc}") from exc
        else:
            prefix = logical.rstrip("/") + "/"
            names = sorted({path[len(prefix):].split("/", 1)[0] for path in descendants})
        for name in names:
            child = logical.rstrip("/") + "/" + name
            yield from visit(child, parents)

    yield from visit("/", set())


def read_config(path):
    data = json.loads(recovery.read_control(Path(path)))
    if not isinstance(data, dict):
        raise SourceError("Ungueltige Konfiguration.")
    return data


def write_report(path, report):
    """Only a new private sidecar at a caller-chosen trusted path is allowed."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps(report, ensure_ascii=True, sort_keys=True).encode("ascii") + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def mount_identity(mounts):
    return [{key: item[key] for key in ("path", "fstype", "device", "mount_id")} for item in mounts]


def verify_report(path):
    report = json.loads(recovery.read_control(Path(path)))
    expected = report.get("mount_identity") if isinstance(report, dict) else None
    if not isinstance(expected, list) or not expected:
        raise SourceError("Mount-Identitaet fehlt im Quellenauswahl-Bericht.")
    if expected != mount_identity(read_mounts()):
        raise SourceError("Mount-Inventar hat sich waehrend des Backups geaendert. Backup ist nicht vollstaendig bestaetigt; Quellen pruefen und erneut starten.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("source-info", "files", "validate", "verify"))
    parser.add_argument("--config")
    parser.add_argument("--excludes")
    parser.add_argument("--selection")
    parser.add_argument("--report", help="New private report file, only for files action")
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            if not args.report:
                raise SourceError("Quellenauswahl-Bericht fehlt.")
            verify_report(args.report)
            return 0
        if args.action == "validate":
            if args.selection is None or len(args.selection.encode("utf-8")) > MAX_SELECTION_BYTES:
                raise SourceError("Quellenauswahl fehlt oder ist zu gross.")
            selection = json.loads(args.selection)
            if not isinstance(selection, dict):
                raise SourceError("Quellenauswahl muss ein JSON-Objekt sein.")
            result = normalize_selection(selection)
        else:
            if not args.config:
                raise SourceError("Konfiguration fehlt.")
            config = read_config(args.config)
            mounts = read_mounts()
            plan = SourcePlan(config.get("source_selection"), mounts, read_excludes(args.excludes))
            if args.action == "files":
                for path in enumerate_files(plan):
                    sys.stdout.buffer.write(os.fsencode(path) + b"\0")
                # Detect source mounts changed while building the list, before
                # its caller is allowed to start the actual copy.
                if mounts != read_mounts():
                    raise SourceError("Mount-Inventar hat sich waehrend der Quellenauswahl geaendert. Backup erneut starten.")
                if args.report:
                    report = plan.report()
                    report["mount_identity"] = mount_identity(mounts)
                    write_report(args.report, report)
                return 0
            result = plan.report()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Quellenauswahl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
