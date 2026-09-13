#!/usr/bin/env python3
"""Build bounded recovery plans. All paths are supplied by the trusted backend."""
import argparse
from functools import lru_cache
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid


class RecoveryError(ValueError):
    pass


def within(path, base):
    return path == base or base in path.parents


def checked_directory(value):
    if not value or any(c in value for c in "\x00\r\n"):
        raise RecoveryError("Leerer oder ungueltiger Verzeichnispfad.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise RecoveryError("Pfad muss absolut sein und darf kein '..' enthalten.")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RecoveryError(f"Symbolische Pfadkomponente nicht erlaubt: {component}")
    if not path.is_dir():
        raise RecoveryError(f"Verzeichnis fehlt: {path}")
    return path.resolve()


def secure_destination(path):
    """A root restore must not write through a renameable, unprivileged parent."""
    if os.name != "posix" or os.geteuid() != 0:
        return
    for component in (path, *path.parents):
        info = component.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise RecoveryError(f"Restore-Zielpfad muss root gehoeren und gegen fremdes Umbenennen geschuetzt sein: {component}")


def read_control(path, limit=1048576):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise RecoveryError(f"Unsichere Kontrolldatei: {path.name}")
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RecoveryError(f"Kontrolldatei fehlt oder ist nicht lesbar: {path.name}") from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise RecoveryError(f"Ungueltige Kontrolldatei: {path.name}")
        return handle.read(limit + 1).decode("utf-8", errors="strict")


def saved_excludes(backup):
    content = read_control(backup / "rsync-excludes.txt")
    if "\x00" in content or "\r" in content:
        raise RecoveryError("NUL oder CR in Backup-Ausschluessen.")
    rules = []
    for line in content.splitlines():
        if not line or line.startswith(("#", ";")):
            continue
        if len(line) > 4096 or ".." in PurePosixPath(line).parts or line == "!" or line.startswith(("+ ", "- ")):
            raise RecoveryError("Ungueltige Backup-Ausschlussregel.")
        rules.append(line)
    return rules


def current_mounts():
    if os.name != "posix":
        return []
    result = subprocess.run(["findmnt", "-rn", "--raw", "-o", "TARGET"],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("Aktuelle Mounts konnten nicht gelesen werden.")
    return [re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), value)
            for value in result.stdout.splitlines() if value and value != "/"]


def captured_mounts(backup):
    path = backup / "source-mounts.json"
    if path.exists() or path.is_symlink():
        data = json.loads(read_control(path))
        if not isinstance(data, list):
            raise RecoveryError("Ungueltiges Mount-Inventar.")
        return [item["target"] for item in data if isinstance(item, dict)
                and isinstance(item.get("target"), str) and item["target"].startswith("/")]
    path = backup / "mounts.txt"
    if not path.exists():
        return []
    return [re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), match[1])
            for line in read_control(path).splitlines()
            if (match := re.search(r" on (.+) type ", line))]


@lru_cache(maxsize=4096)
def wildcard_tokens(pattern):
    """Compile rsync wildcards without an unbounded backtracking expression."""
    posix_classes = {
        "alnum": "A-Za-z0-9", "alpha": "A-Za-z", "blank": " \\t",
        "cntrl": "\\x00-\\x1f\\x7f", "digit": "0-9", "graph": "!-~",
        "lower": "a-z", "print": " -~", "punct": "!-/:-@\\[-`{-~",
        "space": " \\t-\\r", "upper": "A-Z", "xdigit": "A-Fa-f0-9",
    }
    tokens = []
    index = 0
    has_wildcard = any(char in pattern for char in "*?[")
    while index < len(pattern):
        char = pattern[index]
        index += 1
        if char == "*":
            start = index - 1
            while index < len(pattern) and pattern[index] == "*":
                index += 1
            tokens.append(("globstar" if index - start > 1 else "star", None))
        elif char == "?":
            tokens.append(("one", None))
        elif char == "\\" and has_wildcard:
            if index == len(pattern):
                raise RecoveryError("Unvollstaendige Escape-Sequenz in Ausschlussregel.")
            tokens.append(("literal", pattern[index]))
            index += 1
        elif char == "[":
            negate = index < len(pattern) and pattern[index] in "!^"
            if negate:
                index += 1
            content = []
            if index < len(pattern) and pattern[index] == "]":
                content.append(r"\]")
                index += 1
            while index < len(pattern) and pattern[index] != "]":
                if pattern.startswith("[:", index):
                    end = pattern.find(":]", index + 2)
                    name = pattern[index + 2:end] if end >= 0 else ""
                    if name not in posix_classes:
                        raise RecoveryError("Unbekannte Zeichenklasse in Ausschlussregel.")
                    content.append(posix_classes[name])
                    index = end + 2
                else:
                    value = pattern[index]
                    if value == "\\" and index + 1 < len(pattern):
                        index += 1
                        content.append(re.escape(pattern[index]))
                    else:
                        content.append("\\" + value if value in "[^&~|" else value)
                    index += 1
            if index == len(pattern) or not content:
                raise RecoveryError("Unvollstaendige Zeichenklasse in Ausschlussregel.")
            index += 1
            try:
                compiled = re.compile("[" + ("^" if negate else "") + "".join(content) + "]")
            except re.error as exc:
                raise RecoveryError("Ungueltige Zeichenklasse in Ausschlussregel.") from exc
            tokens.append(("class", compiled))
        else:
            tokens.append(("literal", char))
    return tuple(tokens)


def wildcard_match(value, pattern):
    positions = {0}
    for kind, argument in wildcard_tokens(pattern):
        if not positions:
            return False
        if kind == "globstar":
            positions = set(range(min(positions), len(value) + 1))
        elif kind == "star":
            expanded = set()
            for position in sorted(positions):
                while position not in expanded:
                    expanded.add(position)
                    if position == len(value) or value[position] == "/":
                        break
                    position += 1
            positions = expanded
        else:
            positions = {
                position + 1 for position in positions if position < len(value) and (
                    kind == "literal" and value[position] == argument
                    or kind == "one" and value[position] != "/"
                    or kind == "class" and value[position] != "/" and argument.fullmatch(value[position])
                )
            }
    return len(value) in positions


def glob_matches(relative, rule, is_dir=False):
    """Apply rsync exclusion semantics, including excluded ancestor directories."""
    if rule.endswith("/***"):
        return glob_matches(relative, rule[:-3], is_dir)
    relative = relative.strip("/")
    anchored = rule.startswith("/")
    dir_only = rule.endswith("/")
    pattern = rule.strip("/")
    parts = relative.split("/")
    for count in range(1, len(parts) + 1):
        if dir_only and count == len(parts) and not is_dir:
            continue
        if anchored:
            candidates = ["/".join(parts[:count])]
        elif "/" not in pattern and "**" not in pattern:
            candidates = [parts[count - 1]]
        else:
            candidates = ["/".join(parts[start:count]) for start in range(count)]
        if any(wildcard_match(candidate, pattern) for candidate in candidates):
            return True
    return False


def excluded(relative, rules, is_dir=False):
    return any(glob_matches(relative, rule, is_dir) for rule in rules)


def literal_rule(value):
    # Escape rsync glob metacharacters in actual filesystem paths.
    return "".join("[" + c + "]" if c in "*?[" else c for c in value)


def build_plan(backup, backup_root, destination, mappings, protected, mounts=None, host_protected=()):
    backup = checked_directory(str(backup))
    backup_root = checked_directory(str(backup_root))
    destination = checked_directory(str(destination))
    secure_destination(destination)
    if not within(backup, backup_root) or backup == backup_root:
        raise RecoveryError("Backup liegt nicht unter dem registrierten Ziel.")
    if within(destination, backup_root) or within(backup_root, destination) and str(destination) != "/":
        raise RecoveryError("Restore-Ziel und Backup-Speicher duerfen sich nicht ueberlappen.")
    if str(destination) != "/":
        for name in ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/dev", "/proc", "/sys", "/run", "/opt/loxberry", "/var/lib/loxberryhostbackup"):
            if within(destination, Path(name)):
                raise RecoveryError("Alternatives Restore-Ziel darf kein aktives Systemverzeichnis sein.")
    if not isinstance(mappings, list) or len(mappings) > 32:
        raise RecoveryError("Volume-Zuordnung muss eine Liste mit maximal 32 Eintraegen sein.")
    base_rules = saved_excludes(backup)
    live_mounts = current_mounts() if mounts is None else mounts
    captured = captured_mounts(backup)
    pseudo = ["/proc", "/sys", "/dev", "/run", "/tmp", "/lost+found"]
    reserved = [*pseudo, *protected, *host_protected, str(backup_root), str(backup)]
    for name in pseudo:
        base_rules.append(literal_rule(name))
    for name in protected:
        base_rules.append(literal_rule(name))
    for name in [*protected, *host_protected, str(backup_root), str(backup)]:
        actual = Path(name)
        if str(destination) == "/":
            base_rules.append(literal_rule(name))
        elif within(actual, destination):
            base_rules.append(literal_rule("/" + actual.relative_to(destination).as_posix()))
    volumes = []
    for item in mappings:
        if not isinstance(item, dict) or set(item) != {"source", "destination"}:
            raise RecoveryError("Jede Zuordnung benoetigt source und destination.")
        source = str(item["source"])
        if not source.startswith("/") or source == "/" or ".." in PurePosixPath(source).parts or any(c in source for c in "\x00\r\n"):
            raise RecoveryError("Ungueltiger Volume-Quellpfad.")
        source = source.rstrip("/")
        if source not in captured:
            raise RecoveryError(f"Kein aufgezeichnetes Quell-Volume: {source}")
        if excluded(source.lstrip("/"), base_rules, True):
            raise RecoveryError(f"Ausgeschlossenes oder geschuetztes Volume: {source}")
        mapped = checked_directory(str(item["destination"]))
        secure_destination(mapped)
        if str(mapped) == "/" or within(mapped, backup_root) or within(backup_root, mapped):
            raise RecoveryError("Volume-Ziel darf weder / noch Backup-Speicher betreffen.")
        for name in [*protected, *host_protected]:
            p = Path(name)
            if within(mapped, p) or within(p, mapped):
                raise RecoveryError("Volume-Ziel ueberlappt geschuetzte Plugin-Pfade.")
        if str(destination) == "/" and str(mapped) not in live_mounts:
            raise RecoveryError("Online-Volume-Restore erfordert einen eingehängten Ziel-Mount.")
        if str(destination) != "/" and not within(mapped, destination) and str(mapped) not in live_mounts:
            raise RecoveryError("Volume-Ziel muss im Offline-Ziel oder auf einem eigenen Mount liegen.")
        for previous in volumes:
            a, b = Path(previous["destination"]), PurePosixPath(previous["source"])
            if within(mapped, a) or within(a, mapped) or within(PurePosixPath(source), b) or within(b, PurePosixPath(source)):
                raise RecoveryError("Volume-Zuordnungen duerfen nicht ueberlappen.")
        volumes.append({"source": source, "destination": str(mapped)})
    root_rules = list(base_rules)
    omitted = []
    for name in dict.fromkeys([*captured, *live_mounts]):
        if name == "/":
            continue
        root_rules.append(literal_rule(name))
        if name in live_mounts and within(Path(name), destination):
            root_rules.append(literal_rule("/" + Path(name).relative_to(destination).as_posix()))
        if not any(v["source"] == name for v in volumes) and name not in reserved:
            omitted.append(name)
    for volume in volumes:
        root_rules.append(literal_rule(volume["source"]))
        mapped = Path(volume["destination"])
        if within(mapped, destination):
            root_rules.append(literal_rule("/" + mapped.relative_to(destination).as_posix()))
    return {"destination": str(destination), "backup": str(backup), "volumes": volumes,
            "excluded_mounts": sorted(set(omitted)), "exclude_rules": list(dict.fromkeys(root_rules)),
            "base_rules": list(dict.fromkeys(base_rules)), "source_mounts": captured}


def write_rules(path, rules):
    with open(path, "x", encoding="utf-8", newline="\n") as out:
        for rule in rules:
            out.write(rule + "\n")


def mapped_rules(plan, volume):
    prefix = volume["source"].rstrip("/")
    rules = []
    for rule in plan["base_rules"]:
        if rule.startswith(prefix + "/"):
            rules.append(rule[len(prefix):])
        elif not rule.startswith("/"):
            rules.append(rule)
        elif any(c in rule for c in "*?["):
            # A root-anchored wildcard cannot be safely rebased by trimming text.
            raise RecoveryError("Volume-Restore mit verankerten Wildcard-Ausschluessen erfordert eine konkrete Ausschlussregel.")
    for mount in plan["source_mounts"]:
        if mount.startswith(prefix + "/"):
            rules.append(literal_rule(mount[len(prefix):]))
    return rules


def copy_options(mode):
    if mode == "network-compatible":
        return ["-aHA", "--numeric-ids", "--sparse"]
    if mode == "fake-super":
        # Avoid rsync <= 3.2.7/popt 1.19 local -M destination corruption (#505).
        # This fixed transport only execs a local receiver; it never uses a
        # network shell or eval. --protect-args preserves paths via protocol.
        return ["-aHAX", "--numeric-ids", "--sparse", "--fake-super", "-M--super",
                "--whole-file", "--protect-args", "--rsh=/bin/sh -c 'shift; exec \"$@\"' hostbackup-local"]
    if mode == "native-strict":
        return ["-aHAX", "--numeric-ids", "--sparse"]
    raise RecoveryError("Unbekanntes Verzeichnis-Metadatenprofil.")


def rsync_destination(mode, path):
    return ("hostbackup-local:" if mode == "fake-super" else "") + path


def stream_command(command):
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise RecoveryError(f"Kopierwerkzeug abgebrochen (Status {result.returncode}).")


def tar_volume_transform(prefix):
    delimiter = next((char for char in "|,@%~;=#" if char not in prefix), None)
    if delimiter is None:
        raise RecoveryError("Volume-Quellpfad enthaelt keine sicher transformierbare Trennzeichenkombination.")
    escaped = "".join("\\" + char if char in r"\.^$[*]()+?{}" else char for char in prefix)
    return "s" + delimiter + "^([.]/)?" + escaped + "/?" + delimiter * 2 + "xrh"


def selected_portable_members(archive_path, prefix, rules, base_rules, relative=None):
    """Reject links to omitted data before invoking tar or modifying any destination."""
    selected = {}
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            rel = member.name.removeprefix("./").rstrip("/")
            if not rel or rel == ".":
                continue
            if rel.startswith("/") or ".." in PurePosixPath(rel).parts:
                raise RecoveryError("Unsicherer Pfad im Portable-Archiv.")
            if relative is not None and rel != relative and not rel.startswith(relative + "/"):
                continue
            if prefix and rel != prefix and not rel.startswith(prefix + "/"):
                continue
            subpath = rel[len(prefix):].lstrip("/") if prefix else rel
            if excluded(subpath, rules, member.isdir()) or prefix and excluded(rel, base_rules, member.isdir()):
                continue
            if rel in selected:
                raise RecoveryError("Doppelter Portable-Archiveintrag.")
            selected[rel] = member
    for rel, member in selected.items():
        for parent in PurePosixPath(rel).parents:
            ancestor = selected.get(parent.as_posix())
            if ancestor is not None and not ancestor.isdir():
                raise RecoveryError("Portable-Archiv schreibt durch eine Verknuepfung oder Datei.")
        if member.islnk():
            link = member.linkname.removeprefix("./").rstrip("/")
            target = selected.get(link)
            if target is None or not target.isfile():
                raise RecoveryError("Hardlink-Ziel liegt ausserhalb des ausgewaehlten Restore-Bereichs oder ist ausgeschlossen: " + rel)
    return [member.name for member in selected.values()]


def run_restore(plan, mode, storage_format, dry_run):
    backup = Path(plan["backup"])
    if storage_format == "portable-tar" and plan["destination"] == "/":
        raise RecoveryError("Portable Restore erfordert ein ausdrueckliches Offline-Ziel ungleich /.")
    passes = [{"source": "/", "destination": plan["destination"], "rules": plan["exclude_rules"]}]
    passes += [dict(v, rules=mapped_rules(plan, v)) for v in plan["volumes"]]
    with tempfile.TemporaryDirectory(prefix="hostbackup-restore-plan-") as temp:
        prepared = []
        for index, part in enumerate(passes):
            if storage_format == "portable-tar":
                selected = Path(temp) / f"members-{index}.nul"
                prefix = part["source"].strip("/")
                members = selected_portable_members(backup / "rootfs.tar", prefix, part["rules"], plan["base_rules"])
                selected.write_bytes(b"".join(name.encode("utf-8", "surrogateescape") + b"\0" for name in members))
                command = ["tar", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--selinux", "--sparse",
                           "--same-owner", "--same-permissions", "--delay-directory-restore", "--no-recursion",
                           "--null", "--verbatim-files-from", "-C", part["destination"], "-xpf", str(backup / "rootfs.tar")]
                if prefix:
                    # Normalize both './volume/file' and 'volume/file' in one pass.
                    # Only member names and hardlink targets change; symlinks retain
                    # their original targets, as with the directory restore path.
                    command += ["--transform=" + tar_volume_transform(prefix)]
                prepared.append((part, command + ["-T", str(selected)], members))
            else:
                source = backup / "rootfs" / part["source"].lstrip("/")
                source = checked_directory(str(source))
                if not within(source, backup / "rootfs"):
                    raise RecoveryError("Volume-Quelle verlaesst das Backup.")
                rules_file = Path(temp) / f"excludes-{index}.txt"
                write_rules(rules_file, part["rules"])
                command = ["rsync", *copy_options(mode), "--one-file-system", "--delete", "--itemize-changes",
                           "--exclude-from=" + str(rules_file)]
                if dry_run:
                    command.append("--dry-run")
                prepared.append((part, command + [str(source) + "/", rsync_destination(mode, part["destination"].rstrip("/") + "/")], None))
        for part, command, members in prepared:
            print(f"{'Vorschau' if dry_run else 'Restore'}: {part['source']} -> {part['destination']}", flush=True)
            if dry_run and members is not None:
                print(f"{len(members)} Archiveintraege; keine Loeschungen durch tar.", flush=True)
                for name in members:
                    print("A " + json.dumps(name, ensure_ascii=True), flush=True)
            else:
                stream_command(command)
    if plan["excluded_mounts"]:
        print("Nicht wiederhergestellte Volumes: " + ", ".join(plan["excluded_mounts"]), flush=True)


def restore_files(backup, backup_root, destination, relative, mode, storage_format, protected, host_protected=()):
    backup, backup_root, destination = map(lambda x: checked_directory(str(x)), (backup, backup_root, destination))
    secure_destination(destination)
    if not within(backup, backup_root) or backup == backup_root:
        raise RecoveryError("Backup liegt nicht unter dem registrierten Ziel.")
    if within(destination, backup_root) or within(backup_root, destination):
        raise RecoveryError("Einzeldatei-Ziel darf den Backup-Speicher nicht ueberlappen.")
    for name in ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/dev", "/proc", "/sys", "/run", *protected, *host_protected):
        if within(destination, Path(name)) or within(Path(name), destination):
            raise RecoveryError("Einzeldatei-Ziel ueberlappt geschuetzte System- oder Plugin-Pfade.")
    if not relative or relative.startswith("/") or ".." in PurePosixPath(relative).parts or any(c in relative for c in "\x00\r\n"):
        raise RecoveryError("Ungueltiger relativer Dateipfad.")
    relative = PurePosixPath(relative).as_posix().rstrip("/")
    if relative in ("", "."):
        raise RecoveryError("Fuer eine gesamte Systemwiederherstellung den Restore-Assistenten verwenden.")
    rules = saved_excludes(backup)
    if excluded(relative, rules, True):
        raise RecoveryError("Der angefragte Pfad ist im Backup ausgeschlossen.")
    created = destination / ("recovered-" + backup.name + "-" + uuid.uuid4().hex[:12])
    # Always use a brand-new 0700 directory. A failed copy remains inspectable; never overwrite user data.
    created.mkdir(mode=0o700)
    print(f"Wiederherstellungsverzeichnis (bleibt auch bei Fehlern erhalten): {created}", flush=True)
    if storage_format == "portable-tar":
        with tempfile.TemporaryDirectory(prefix="hostbackup-partial-") as temp:
            selected = Path(temp) / "members.nul"
            members = selected_portable_members(backup / "rootfs.tar", "", rules, rules, relative)
            selected.write_bytes(b"".join(name.encode("utf-8", "surrogateescape") + b"\0" for name in members))
            if not members:
                raise RecoveryError("Pfad nicht im Archiv gefunden.")
            stream_command(["tar", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*", "--selinux", "--sparse",
                            "--same-owner", "--same-permissions", "--delay-directory-restore", "--no-recursion", "--null",
                            "--verbatim-files-from", "-C", str(created), "-xpf", str(backup / "rootfs.tar"), "-T", str(selected)])
    else:
        base = checked_directory(str(backup / "rootfs"))
        source = base / relative
        checked_directory(str(source.parent))
        if not source.exists() and not source.is_symlink():
            raise RecoveryError("Datei oder Verzeichnis fehlt im Backup.")
        with tempfile.TemporaryDirectory(prefix="hostbackup-partial-") as temp:
            exclude_file = Path(temp) / "excludes.txt"
            write_rules(exclude_file, rules)
            stream_command(["rsync", *copy_options(mode), "--one-file-system", "--relative", "--itemize-changes",
                            "--exclude-from=" + str(exclude_file), str(base) + "/./" + relative, rsync_destination(mode, str(created) + "/")])
    print("Einzeldatei-Restore abgeschlossen; vorhandene Dateien am Ziel wurden nicht ersetzt.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "excludes", "execute", "files"))
    parser.add_argument("--backup", required=True)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--destination", default="/")
    parser.add_argument("--map-json", default="[]")
    parser.add_argument("--protect", action="append", default=[])
    parser.add_argument("--protect-host", action="append", default=[],
                        help="Protect a live host path; rebase only when it is inside the restore destination")
    parser.add_argument("--output")
    parser.add_argument("--mode", default="native-strict")
    parser.add_argument("--storage-format", default="directory", choices=("directory", "portable-tar"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--relative")
    args = parser.parse_args()
    if args.action == "files":
        restore_files(args.backup, args.backup_root, args.destination, args.relative, args.mode, args.storage_format, args.protect, args.protect_host)
        return
    plan = build_plan(args.backup, args.backup_root, args.destination, json.loads(args.map_json), args.protect, host_protected=args.protect_host)
    if args.action == "excludes":
        if not args.output:
            parser.error("excludes erfordert --output")
        write_rules(Path(args.output), plan["exclude_rules"])
    elif args.action == "execute":
        run_restore(plan, args.mode, args.storage_format, args.dry_run)
    else:
        print(json.dumps(plan, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RecoveryError, OSError, ValueError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(18)
