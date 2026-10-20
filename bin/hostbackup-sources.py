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
policy_spec = importlib.util.spec_from_file_location("hostbackup_runtime_policy", Path(__file__).with_name("hostbackup-runtime-policy.py"))
runtime_policy_module = importlib.util.module_from_spec(policy_spec)
policy_spec.loader.exec_module(runtime_policy_module)

NETWORK_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "ncpfs", "afs", "openafs", "ceph", "9p", "glusterfs", "lustre", "davfs", "davfs2", "fuse"}
SYSTEM_FS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "debugfs", "securityfs", "pstore", "tracefs", "configfs", "mqueue", "hugetlbfs", "fusectl", "rpc_pipefs", "binfmt_misc", "nsfs", "bpf"}
MAX_SELECTION_BYTES = 65536
MAX_OVERRIDES = 256
MAX_SOCKET_REPORT_PATHS = 20
MOUNT_VERIFICATION_VERSION = 2
MAX_MOUNT_CHANGE_PATHS = 10
SOCKET_OMISSION_REASON = "Unix-Sockets sind laufzeitgebundene Kommunikationsendpunkte und werden von den Diensten neu angelegt; portable Repository-Staende sichern sie nicht."


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


def automount_data_layer(item):
    """Recognise only a direct automount with one mounted data filesystem.

    mountinfo line order is not visibility order. The data layer must name
    the lower autofs layer as its parent; arbitrary overmounts stay ambiguous.
    """
    layers = item.get("stack", [])
    if len(layers) != 2:
        return None
    automounts = [layer for layer in layers if layer.get("fstype") == "autofs"]
    data = [layer for layer in layers if layer.get("fstype") and mount_kind(layer["fstype"]) in ("local", "network")]
    if len(automounts) != 1 or len(data) != 1:
        return None
    lower, upper = automounts[0], data[0]
    identifiers = {layer.get("mount_id") for layer in layers}
    if (len(identifiers) != 2 or upper.get("parent_id") != lower.get("mount_id")
            or not lower.get("parent_id") or lower["parent_id"] in identifiers):
        return None
    return upper


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
        if not re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) or not fields[0].isdigit() or not fields[1].isdigit():
            raise SourceError("Ungueltige Geraetekennung im Mount-Inventar.")
        mount_root = unescape_mount(fields[3])
        canonical_path(mount_root, allow_root=True)
        item = {"path": target, "fstype": tail[0], "kind": mount_kind(tail[0]),
                "device": fields[2], "mount_id": fields[0], "parent_id": fields[1], "root": mount_root}
        if target in mounts:
            previous = mounts[target]
            stack = previous.get("stack", [{key: previous[key] for key in ("fstype", "device", "mount_id", "parent_id", "root")}])
            item["stack"] = sorted(stack + [{key: item[key] for key in ("fstype", "device", "mount_id", "parent_id", "root")}],
                                   key=lambda layer: (int(layer["mount_id"]), layer["root"]))
        mounts[target] = item
    if "/" not in mounts:
        raise SourceError("Root-Dateisystem fehlt im Mount-Inventar.")
    for item in mounts.values():
        visible = automount_data_layer(item)
        if visible:
            item.update(visible)
            item["kind"] = mount_kind(visible["fstype"])
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
    def __init__(self, selection, mounts, excludes=(), loxberry_home=None, include_runtime_logs=False):
        self.selection = normalize_selection(selection)
        self.mounts = {item["path"]: dict(item) for item in mounts}
        if "/" not in self.mounts:
            raise SourceError("Root-Dateisystem fehlt im Mount-Inventar.")
        self.excludes = list(excludes)
        self.confirmed_directory_excludes = set()
        self.runtime_policy = (runtime_policy_module.RuntimePolicy(loxberry_home, include_runtime_logs,
                                                                  mounts=self.mounts.values(), overrides=self.selection["overrides"])
                               if loxberry_home is not None else None)
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
        self.omitted_runtime_sockets = None
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
            # A data mount may bind a regular file. A trailing-slash rule
            # cannot exclude it until lstat confirms that it is a directory.
            # Autofs mountpoints themselves are always directories.
            elif self.excluded(path, kind == "automount"):
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
        for path, item in self.mounts.items():
            visible = automount_data_layer(item)
            supported_automount = visible is not None and all(item.get(key) == value for key, value in visible.items())
            if item.get("stack") and not supported_automount and self.ambiguous_mount_relevant(path, item):
                self.errors.append(f"Mehrere Einbindungen verdecken denselben Quellpfad: {display_path(path)}. Mount-Zuordnung vor dem Backup klaeren.")

    @lru_cache(maxsize=4096)
    def nearest_mount(self, path):
        if path in self.mounts:
            return path
        return self.nearest_mount(path.rsplit("/", 1)[0] or "/")

    def excluded(self, path, is_dir):
        if any(beneath(path, directory) for directory in self.confirmed_directory_excludes):
            return True
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
        # Directory-only mount exclusions can be confirmed during enumeration.
        # Keep ancestor routes in sync instead of retaining a now-excluded
        # child's automount as a supposedly required source.
        return tuple(child for child in self.descendant_routes.get(path, ())
                     if self.included(child) and not self.excluded(child, False))

    def mount_relevant(self, path):
        """Evaluate against the frozen plan, never a fresh automatic selection.

        Old disabled mount boundaries keep shielding their underlying folders
        even after unmount. Ancestors of explicitly routed sources remain
        relevant, while a new mount in a previously selected tree is relevant
        regardless of its filesystem type or current automatic classification.
        """
        # A new mount may cover a regular file, not only a directory. A
        # directory-only exclude is insufficient evidence to ignore that
        # exact new boundary. Old excluded mounts still remain disabled via
        # included(), and descendants of excluded directories remain excluded.
        if self.excluded(path, False):
            return False
        return self.included(path) or bool(self.selected_descendants(path))

    def ambiguous_mount_relevant(self, path, item):
        if self.mount_relevant(path):
            return True
        # mountinfo order alone does not establish the visible layer. Do not
        # let an arbitrarily last network/system layer hide a potentially
        # selected local layer. Explicitly excluded stacks remain excluded.
        base = [{key: value for key, value in mount.items() if key != "stack"}
                for mount in self.mounts.values()]
        for layer in item["stack"]:
            alternative = [{**mount, **layer, "kind": mount_kind(layer["fstype"])} if mount["path"] == path else mount
                           for mount in base]
            candidate = SourcePlan(self.selection, alternative, self.excludes)
            if candidate.mount_relevant(path):
                return True
        return False

    def report(self):
        volumes = []
        for path in sorted(self.mounts):
            item = self.mounts[path]
            forced_excluded = path != "/" and self.excluded(path, item["kind"] == "automount")
            volumes.append({"path": path, "fstype": item["fstype"], "kind": item["kind"],
                            "included": self.included(path), "reason": self.reasons[path],
                            "forced_excluded": forced_excluded,
                            "selectable": path != "/" and not forced_excluded and item["kind"] not in ("system", "automount")})
        report = {"selection": self.selection, "volumes": volumes, "notices": self.notices,
                  "errors": self.errors, "status": "error" if self.errors else "ok"}
        if self.runtime_policy is not None:
            report["runtime_content_policy"] = self.runtime_policy.report()
            if report["runtime_content_policy"]["enabled"]:
                report["notices"] = report["notices"] + [report["runtime_content_policy"]["reason"]]
        if self.omitted_runtime_sockets is not None:
            report["omitted_runtime_sockets"] = {**self.omitted_runtime_sockets,
                                                 "paths": list(self.omitted_runtime_sockets["paths"])}
            if self.omitted_runtime_sockets["count"]:
                report["notices"] = report["notices"] + [
                    f"{self.omitted_runtime_sockets['count']} laufzeitgebundene Unix-Sockets fuer portable Repository-Sicherung ausgelassen; Details unter omitted_runtime_sockets."]
        return report


def enumerate_files(plan, root=Path("/"), omit_sockets=False):
    """Yield literal-safe relative paths once; never list a denied mount.

    root is injectable solely for fixture tests. Production always uses '/'.
    Explicit selected descendants are reached by their known path components,
    without scanning an excluded autofs parent and activating its siblings.
    """
    if plan.errors:
        raise SourceError(" ".join(plan.errors))
    root = Path(root)
    plan.omitted_runtime_sockets = ({"count": 0, "paths": [], "reason": SOCKET_OMISSION_REASON}
                                    if omit_sockets else None)
    if plan.runtime_policy is not None:
        plan.runtime_policy = runtime_policy_module.RuntimePolicy(
            plan.runtime_policy.home, plan.runtime_policy.include_runtime_logs,
            mounts=plan.mounts.values(), overrides=plan.selection["overrides"])

    def visit(logical, ancestors, entry=None):
        included = plan.included(logical)
        descendants = plan.selected_descendants(logical)
        if not included and not descendants:
            return
        # Rules that apply regardless of file type do not require lstat. This
        # also keeps already-excluded rotating payload out of the race window.
        if logical != "/" and plan.excluded(logical, False):
            return
        # Exclude confirmed regular diagnostic payload before its lstat can
        # race with rotation. Unknown entries, mount boundaries, directories,
        # links and special files still follow the ordinary strict path.
        if (included and not descendants and logical not in plan.mounts and plan.runtime_policy is not None
                and plan.runtime_policy.should_omit(logical, entry, root)):
            return
        physical = root if logical == "/" else root / logical.lstrip("/")
        try:
            info = physical.lstat()
        except OSError as exc:
            raise SourceError(f"Quellpfad konnte nicht gelesen werden: {logical}: {exc.strerror or exc}") from exc
        is_dir = stat.S_ISDIR(info.st_mode)
        if logical != "/" and plan.excluded(logical, is_dir):
            if is_dir and logical in plan.mounts:
                # Freeze the observed directory boundary as an ordinary exact
                # exclude. Its later removal must not expose underlying data
                # or make irrelevant mount churn abort this backup.
                plan.confirmed_directory_excludes.add(logical)
                plan.enabled[logical] = False
                plan.reasons[logical] = "Durch einen Backup-Ausschluss ausgeschlossen."
            return
        if (descendants or logical in plan.selection["overrides"] and plan.selection["overrides"][logical]) and stat.S_ISLNK(info.st_mode):
            raise SourceError(f"Ausgewaehlte Quelle darf nicht ueber einen symbolischen Link fuehren: {logical}")
        expected = plan.mounts[plan.nearest_mount(logical)].get("device")
        if expected and os.name == "posix" and f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" != expected:
            raise SourceError(f"Mount-Zuordnung hat sich geaendert: {logical}. Backup erneut pruefen.")
        if not included and not is_dir:
            raise SourceError(f"Pfad zur ausgewaehlten Quelle ist kein Verzeichnis: {logical}")
        # Only an lstat-confirmed Unix socket may be omitted, and only after
        # selection/mount checks. Never follow symlinks or suppress read errors,
        # FIFO/device entries, or errors on a route to a selected descendant.
        if omit_sockets and stat.S_ISSOCK(info.st_mode):
            plan.omitted_runtime_sockets["count"] += 1
            if len(plan.omitted_runtime_sockets["paths"]) < MAX_SOCKET_REPORT_PATHS:
                plan.omitted_runtime_sockets["paths"].append(logical)
            return
        # rsync treats even NUL-delimited files-from entries starting with '#'
        # or ';' as comments. A literal './' prefix preserves those names.
        # TAR/repository need the explicit root node. The rsync transport
        # adapter below omits it: even '.' expands immediate root contents.
        yield "." if logical == "/" else "." + logical
        if not is_dir:
            return
        identity = (info.st_dev, info.st_ino)
        if identity in ancestors:
            raise SourceError(f"Zyklische Verzeichniseinbindung entdeckt: {logical}")
        parents = ancestors | {identity}
        if included:
            try:
                with os.scandir(physical) as entries:
                    # No entry metadata yet: is_dir/stat could enter an
                    # automount before the selection decision has been made.
                    children = {entry.name: entry for entry in entries}
                    names = sorted(children)
            except OSError as exc:
                raise SourceError(f"Quellverzeichnis konnte nicht gelesen werden: {logical}: {exc.strerror or exc}") from exc
        else:
            prefix = logical.rstrip("/") + "/"
            names = sorted({path[len(prefix):].split("/", 1)[0] for path in descendants})
            children = {}
        for name in names:
            child = logical.rstrip("/") + "/" + name
            yield from visit(child, parents, children.get(name))

    yield from visit("/", set())


def rsync_list_entries(entries):
    """Keep exact selected paths; let './entry' imply root metadata only.

    rsync --dirs expands the explicit '.' even with --no-recursive. Every
    non-root entry has './', which causes rsync to send root as an implied
    directory without traversing its children. A root-only selection cannot
    preserve its metadata this way and is rejected instead of reported OK.
    """
    root_seen = False
    non_root_seen = False
    for path in entries:
        if path == ".":
            if root_seen:
                raise SourceError("Doppeltes Root-Verzeichnis in rsync-Quellenauswahl.")
            root_seen = True
            continue
        if not path.startswith("./") or path.endswith("/"):
            raise SourceError("rsync-Quellenauswahl benoetigt literale ./-Pfade ohne abschliessenden Schraegstrich.")
        non_root_seen = True
        yield path
    if not root_seen or not non_root_seen:
        raise SourceError("Keine sicherbaren Eintraege ausser dem Root-Verzeichnis ausgewaehlt.")


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


def mount_identity(mounts, legacy=False):
    result = []
    for item in mounts:
        identity = {key: item[key] for key in ("path", "fstype", "device", "mount_id")}
        if not legacy:
            # Missing root is permitted only for old caller/fixture structures.
            # Kernel mountinfo and version-2 persisted reports always include it.
            identity["root"] = item.get("root", "/")
            if "parent_id" in item:
                identity["parent_id"] = item["parent_id"]
            if item.get("stack"):
                identity["stack"] = item["stack"]
        result.append(identity)
    return sorted(result, key=lambda item: (item["path"].count("/"), item["path"]))


def display_path(path):
    # Escape controls and cap unusual path names; never show mount sources or
    # options, which may contain server credentials.
    value = json.dumps(path, ensure_ascii=True)
    return value if len(value) <= 220 else value[:217] + '..."'


def mount_summary(item):
    if item is None:
        return None
    return {**{key: item[key] for key in ("fstype", "device", "mount_id", "root")},
            **({"parent_id": item["parent_id"]} if "parent_id" in item else {}),
            "stack_layers": len(item.get("stack", []))}


def compatible_mount_identity(item, reference):
    """Older private receipts lack parent IDs; never invent their ancestry."""
    if item is None or reference is None:
        return item
    result = dict(item)
    if "parent_id" not in reference:
        result.pop("parent_id", None)
    if "stack" in item and "stack" in reference:
        old_layers = {layer["mount_id"]: layer for layer in reference["stack"]}
        result["stack"] = [compatible_mount_identity(layer, old_layers.get(layer["mount_id"]))
                           for layer in item["stack"]]
    return result


def verify_mounts(plan, current_mounts, verification_path=None):
    if plan.errors:
        raise SourceError(" ".join(plan.errors))
    before = {item["path"]: item for item in mount_identity(plan.mounts.values())}
    after = {item["path"]: item for item in mount_identity(current_mounts)}
    changes, ignored = [], []
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == compatible_mount_identity(after.get(path), before.get(path)):
            continue
        action = "entfernt" if path not in after else "neu eingebunden" if path not in before else "ersetzt/geaendert"
        record = {"path": path[:4096], "change": action,
                  "before": mount_summary(before.get(path)), "after": mount_summary(after.get(path))}
        (changes if plan.mount_relevant(path) else ignored).append(record)
    result = {"version": MOUNT_VERIFICATION_VERSION, "status": "error" if changes else "ok",
              "relevant_changes_count": len(changes), "ignored_changes_count": len(ignored),
              "relevant_changes": changes[:MAX_MOUNT_CHANGE_PATHS], "ignored_changes": ignored[:MAX_MOUNT_CHANGE_PATHS],
              "samples_truncated": len(changes) > MAX_MOUNT_CHANGE_PATHS or len(ignored) > MAX_MOUNT_CHANGE_PATHS}
    if verification_path:
        write_report(verification_path, result)
    if changes:
        details = "; ".join(f"{display_path(item['path'])} ({item['change']})" for item in changes[:MAX_MOUNT_CHANGE_PATHS])
        if len(changes) > MAX_MOUNT_CHANGE_PATHS:
            details += f"; weitere {len(changes) - MAX_MOUNT_CHANGE_PATHS} Pfade"
        raise SourceError("Gesicherte Quellen oder ihre Zugriffswege wurden waehrend des Backups geaendert: "
                          + details + ". Backup ist nicht vollstaendig bestaetigt; Quellen pruefen und erneut starten.")
    return result


def verification_report(plan):
    # Confirmed paths are literal, even if a directory name contains rsync
    # wildcard characters. Do not widen a directory-only rule to other files.
    confirmed = ["".join("\\" + char if char in "*?[\\" else char for char in path)
                 if any(char in path for char in "*?[") else path
                 for path in sorted(plan.confirmed_directory_excludes - set(plan.excludes))]
    return {**plan.report(), "mount_verification_version": MOUNT_VERIFICATION_VERSION,
            "frozen_excludes": list(plan.excludes) + confirmed,
            "mount_identity": mount_identity(plan.mounts.values())}


def verify_report(path, verification_path=None):
    report = json.loads(recovery.read_control(Path(path)))
    expected = report.get("mount_identity") if isinstance(report, dict) else None
    if not isinstance(expected, list) or not expected:
        raise SourceError("Mount-Identitaet fehlt im Quellenauswahl-Bericht.")
    version = report.get("mount_verification_version")
    if version is None:
        # Earlier reports have no frozen excludes. Do not infer exclusions and
        # accidentally bless a changed source; retain the old strict check.
        legacy = not any("root" in item for item in expected if isinstance(item, dict))
        current = mount_identity(read_mounts(), legacy=legacy)
        old_by_path = {item.get("path"): item for item in expected if isinstance(item, dict)}
        changed = expected != [compatible_mount_identity(item, old_by_path.get(item["path"])) for item in current]
        if verification_path:
            write_report(verification_path, {"version": 1, "status": "error" if changed else "ok",
                                             "legacy_full_inventory_check": True})
        if changed:
            raise SourceError("Mount-Inventar hat sich waehrend des Backups geaendert. Backup ist nicht vollstaendig bestaetigt; Quellen pruefen und erneut starten.")
        return
    if type(version) is not int or version != MOUNT_VERIFICATION_VERSION or not isinstance(report.get("frozen_excludes"), list):
        raise SourceError("Unbekannter oder unvollstaendiger Quellenauswahl-Bericht.")
    paths = set()
    for item in expected:
        if not isinstance(item, dict) or set(item) - {"path", "fstype", "device", "mount_id", "parent_id", "root", "stack"}:
            raise SourceError("Ungueltige eingefrorene Mount-Identitaet.")
        for key in ("path", "fstype", "device", "mount_id", "root"):
            if not isinstance(item.get(key), str):
                raise SourceError("Unvollstaendige eingefrorene Mount-Identitaet.")
        canonical_path(item["path"], allow_root=True)
        canonical_path(item["root"], allow_root=True)
        if item["path"] in paths or not re.fullmatch(r"[0-9]+:[0-9]+", item["device"]) or not item["mount_id"].isdigit():
            raise SourceError("Ungueltige eingefrorene Mount-Identitaet.")
        if "parent_id" in item and (not isinstance(item["parent_id"], str) or not item["parent_id"].isdigit()):
            raise SourceError("Ungueltige eingefrorene Mount-Abstammung.")
        if "stack" in item:
            if not isinstance(item["stack"], list) or len(item["stack"]) < 2:
                raise SourceError("Ungueltige gestapelte Mount-Identitaet.")
            for layer in item["stack"]:
                if (not isinstance(layer, dict) or not {"fstype", "device", "mount_id", "root"} <= set(layer)
                        or set(layer) - {"fstype", "device", "mount_id", "parent_id", "root"}
                        or any(not isinstance(value, str) for value in layer.values())
                        or not re.fullmatch(r"[0-9]+:[0-9]+", layer["device"]) or not layer["mount_id"].isdigit()
                        or "parent_id" in layer and not layer["parent_id"].isdigit()):
                    raise SourceError("Ungueltige gestapelte Mount-Identitaet.")
                canonical_path(layer["root"], allow_root=True)
        paths.add(item["path"])
    excludes = report["frozen_excludes"]
    if any(not isinstance(rule, str) or len(rule) > 4096 or "\x00" in rule or "\r" in rule or "\n" in rule for rule in excludes):
        raise SourceError("Ungueltige eingefrorene Ausschlussregeln.")
    if not isinstance(report.get("selection"), dict):
        raise SourceError("Eingefrorene Quellenauswahl fehlt.")
    return verify_mounts(SourcePlan(report["selection"], expected, excludes), read_mounts(), verification_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("source-info", "files", "validate", "verify"))
    parser.add_argument("--config")
    parser.add_argument("--excludes")
    parser.add_argument("--selection")
    parser.add_argument("--report", help="New private report file, only for files action")
    parser.add_argument("--verification-report", help="New private result sidecar, only for verify action")
    parser.add_argument("--loxberry-home", help="Explicit LoxBerry home enables the shared runtime-content policy")
    parser.add_argument("--omit-sockets", action="store_true",
                        help="For portable repository files only: omit lstat-confirmed Unix sockets; requires --report")
    parser.add_argument("--for-rsync", action="store_true",
                        help="For files action only: root metadata is implied, never enumerate root again in rsync")
    args = parser.parse_args(argv)
    try:
        if args.omit_sockets and (args.action != "files" or not args.report):
            raise SourceError("--omit-sockets ist nur fuer files mit --report erlaubt.")
        if args.for_rsync and (args.action != "files" or args.omit_sockets):
            raise SourceError("--for-rsync ist nur fuer files ohne --omit-sockets erlaubt.")
        if args.verification_report and args.action != "verify":
            raise SourceError("--verification-report ist nur fuer verify erlaubt.")
        if args.action == "verify":
            if not args.report:
                raise SourceError("Quellenauswahl-Bericht fehlt.")
            verify_report(args.report, args.verification_report)
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
            plan = SourcePlan(config.get("source_selection"), mounts, read_excludes(args.excludes),
                              loxberry_home=args.loxberry_home, include_runtime_logs=config.get("include_runtime_logs", False))
            if args.action == "files":
                paths = enumerate_files(plan, omit_sockets=args.omit_sockets)
                if args.for_rsync:
                    paths = rsync_list_entries(paths)
                for path in paths:
                    sys.stdout.buffer.write(os.fsencode(path) + b"\0")
                # Detect source mounts changed while building the list, before
                # its caller is allowed to start the actual copy.
                verify_mounts(plan, read_mounts())
                if args.report:
                    write_report(args.report, verification_report(plan))
                return 0
            result = plan.report()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Quellenauswahl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
