#!/usr/bin/env python3
"""Bounded local Restic storage adapter; only the trusted root backend calls it.

Data snapshots are candidates, never published backups. A second authenticated
snapshot commits the exact data ID and its recovery controls after the caller has
verified source/target mounts. Restoring is permitted only into empty staging;
the existing recovery planner remains responsible for writing a real system.
The caller must hold the plugin operation lock across backup and commit.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading


VERSION = "0.19.1"
FORMAT = "hostbackup-restic-v1"
REPOSITORY_NAME = ".portable-repository"
MARKER = ".loxberry-hostbackup-target"
CONTROL_NAME = "hostbackup-control.json"
MAX_CONTROL = 16 * 1024 * 1024
MAX_LIST = 256 * 1024 * 1024
ID = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
CONTROLS = frozenset({"manifest.json", "rsync-excludes.txt", "source-selection.json",
                      "source-mounts.json", "mounts.txt", "metadata-probe.json",
                      "packages.txt", "services.txt", "package-list.txt", "systemd-services.txt",
                      "docker.json", "backup-validation.json"})


class RepositoryError(ValueError):
    pass


def fail(message):
    raise RepositoryError(message)


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def token(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value) or ".." in value:
        fail("Ungueltige Sicherungsidentitaet.")
    return value


def snapshot_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail("Vollstaendige unveraenderliche Snapshot-ID erforderlich.")
    return value


def secure_dir(value, private=False):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        fail("Absoluter, normalisierter Verzeichnispfad erforderlich.")
    for part in (path, *path.parents):
        if part.is_symlink() or not part.is_dir():
            fail("Verzeichnispfad fehlt oder enthaelt symbolische Links.")
        info = part.stat()
        if private and os.name == "posix":
            if info.st_uid != os.geteuid() or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                fail("Privater Pfad muss root gehoeren und gegen fremdes Umbenennen geschuetzt sein.")
    if private and os.name == "posix" and path.stat().st_mode & 0o077:
        fail("Privates Verzeichnis darf nur fuer root zugaenglich sein.")
    return path


def read_bytes(path, limit=MAX_CONTROL, private=False):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit or before.st_nlink != 1:
        fail("Kontrolldatei muss eine einzelne begrenzte regulaere Datei sein.")
    if private and os.name == "posix" and (before.st_uid != os.geteuid() or before.st_mode & 0o077):
        fail("Geheimnis/Kontrolldatei muss root gehoeren und Modus 0600 haben.")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as source:
        after = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            fail("Kontrolldatei wurde beim Oeffnen ausgetauscht.")
        result = source.read(limit + 1)
    if len(result) > limit:
        fail("Kontrolldatei ist zu gross.")
    return result


def atomic_write(path, content, exclusive=False):
    path = Path(path)
    secure_dir(path.parent, private=True)
    if path.is_symlink() or (exclusive and path.exists()):
        fail("Ausgabedatei existiert bereits oder ist ein Link.")
    fd, temporary = tempfile.mkstemp(prefix=".repository-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        if exclusive:
            # link() does not replace a concurrently created destination.
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clean_environment():
    # Never inherit RESTIC_*, password commands, repository options, proxies,
    # LD_PRELOAD or caller-controlled Go settings into a privileged process.
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "GODEBUG": "asyncpreemptoff=1", "GOMAXPROCS": "2"}


def diagnostic(value):
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = re.sub(r"(?i)\b(password|passwd|token|secret|authorization)(\s*[:=]\s*)[^\s;,]+", r"\1\2<redacted>", text)
    return text[-2000:].strip()


def mount_identity(path):
    if os.name != "posix":
        fail("Repository-Laufzeit wird nur unter Linux unterstuetzt.")
    executable = next((value for value in ("/usr/bin/findmnt", "/bin/findmnt") if os.path.isfile(value)), None)
    if executable is None:
        fail("findmnt fehlt; Mount-Identitaet kann nicht sicher geprueft werden.")
    result = subprocess.run([executable, "--json", "-T", str(path), "-o", "TARGET,SOURCE,FSTYPE"],
                            capture_output=True, env=clean_environment(), check=False, timeout=30)
    try:
        rows = json.loads(result.stdout)["filesystems"]
        identity = {key: rows[0][key] for key in ("target", "source", "fstype")}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RepositoryError("Mount-Identitaet konnte nicht ermittelt werden.") from exc
    if result.returncode or any(not isinstance(value, str) or not value for value in identity.values()):
        fail("Mount-Identitaet ist unvollstaendig.")
    if identity["fstype"] == "autofs":
        fail("Automount-Ziel muss vor Repository-Zugriff tatsaechlich eingebunden sein.")
    return identity


def trusted_engine():
    engine = Path(__file__).resolve().with_name("restic")
    if not str(engine).startswith("/usr/libexec/loxberryhostbackup/releases/"):
        fail("Restic muss aus einer vertrauenswuerdigen installierten Laufzeit stammen.")
    for part in (engine, *engine.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            fail("Restic-Laufzeit ist nicht rootgeschuetzt.")
    if not engine.is_file() or not os.access(engine, os.X_OK):
        fail("Gepruefte Restic-Laufzeit fehlt.")
    return engine


def node_kind(mode):
    for checker, label in ((stat.S_ISREG, "file"), (stat.S_ISDIR, "dir"), (stat.S_ISLNK, "symlink"),
                           (stat.S_ISFIFO, "fifo"), (stat.S_ISBLK, "dev"), (stat.S_ISCHR, "chardev")):
        if checker(mode):
            return label
    fail("Nicht wiederherstellbarer Dateityp in Quellenauswahl (z.B. Socket); Ausschluesse pruefen.")


def root_metadata(path):
    info = Path(path).stat()
    attributes = {}
    if os.name == "posix":
        for name in sorted(os.listxattr(path, follow_symlinks=False)):
            attributes[name] = base64.b64encode(os.getxattr(path, name, follow_symlinks=False)).decode("ascii")
    return {"uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
            "mtime_ns": info.st_mtime_ns, "atime_ns": info.st_atime_ns, "xattrs": attributes}


def apply_root_metadata(path, metadata):
    for key in ("uid", "gid", "mode", "mtime_ns", "atime_ns"):
        if not isinstance(metadata.get(key), int) or isinstance(metadata[key], bool) or metadata[key] < 0:
            fail("Ungueltige Root-Metadaten im Sicherungsbeleg.")
    if metadata["mode"] > 0o7777 or not isinstance(metadata.get("xattrs"), dict):
        fail("Ungueltige Root-Dateirechte oder Dateiattribute.")
    for name, value in metadata["xattrs"].items():
        if not isinstance(name, str) or not name or len(name) > 255 or "\0" in name:
            fail("Ungueltiger Root-Dateiattributname.")
        base64.b64decode(value, validate=True)
    os.chown(path, metadata["uid"], metadata["gid"], follow_symlinks=False)
    os.chmod(path, metadata["mode"], follow_symlinks=False)
    for name in os.listxattr(path, follow_symlinks=False):
        if name not in metadata["xattrs"]:
            os.removexattr(path, name, follow_symlinks=False)
    for name, value in metadata["xattrs"].items():
        os.setxattr(path, name, base64.b64decode(value, validate=True), follow_symlinks=False)
    os.utime(path, ns=(metadata["atime_ns"], metadata["mtime_ns"]), follow_symlinks=False)
    actual = root_metadata(path)
    if actual != metadata:
        fail("Root-Metadaten konnten im Staging nicht unveraendert wiederhergestellt werden.")


def selected_paths(path, source_root):
    raw = read_bytes(path, MAX_LIST)
    if not raw or not raw.endswith(b"\0"):
        fail("Vollstaendige NUL-terminierte Quellenauswahl erforderlich.")
    root = secure_dir(source_root)
    selected = {}
    for value in raw[:-1].split(b"\0"):
        try:
            relative = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RepositoryError("Quellname kann nicht verlustfrei als UTF-8 gesichert werden.") from exc
        posix = PurePosixPath(relative)
        if not relative or posix.is_absolute() or ".." in posix.parts or relative not in (".", str(posix)):
            fail("Quellenauswahl enthaelt einen unsicheren oder nicht normalisierten Pfad.")
        physical = root if relative == "." else root / relative
        # Leaf symlinks are data; parent symlinks must never redirect selection.
        for parent in physical.parents:
            if parent == root.parent:
                break
            if parent.is_symlink():
                fail("Quellenauswahl fuehrt durch einen symbolischen Elternpfad.")
        logical = physical.as_posix()
        if logical in selected:
            fail("Doppelter Pfad in Quellenauswahl.")
        selected[logical] = node_kind(physical.lstat().st_mode)
    if root.as_posix() not in selected:
        fail("Root-Verzeichnis fehlt in der Quellenauswahl.")
    return selected


class Repository:
    def __init__(self, backup_root, state_dir, engine=None, runner=None, identity_reader=None):
        self.root = secure_dir(backup_root)
        base = secure_dir(state_dir, private=True)
        self.state_base = base
        self.state = base / hashlib.sha256(os.fsencode(str(self.root))).hexdigest()
        self.state.mkdir(mode=0o700, exist_ok=True)
        secure_dir(self.state, private=True)
        self.engine = Path(engine) if engine is not None else trusted_engine()
        self.runner = runner or self._subprocess
        self.identity_reader = identity_reader or mount_identity
        self.path = self.root / REPOSITORY_NAME
        self.password = self.state / "password"
        self.descriptor = self.state / "repository.json"
        self.cache = self.state / "cache"
        self.cache.mkdir(mode=0o700, exist_ok=True)
        secure_dir(self.cache, private=True)
        self.version_checked = False

    def _subprocess(self, argv, stdin=None):
        # Drain both pipes concurrently. Bound on-disk protocol output and RAM
        # diagnostics while the engine runs, not only after it can fill the SD.
        exceeded = threading.Event()
        diagnostics = bytearray()
        reader_errors = []
        with tempfile.TemporaryFile(dir=self.state) as output_file:
            child = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=clean_environment(), cwd="/")
            def stop_child():
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            def read_output():
                count = 0
                try:
                    for chunk in iter(lambda: child.stdout.read(65536), b""):
                        count += len(chunk)
                        if count > MAX_LIST:
                            exceeded.set()
                            stop_child()
                            break
                        output_file.write(chunk)
                except (OSError, ValueError) as error:
                    reader_errors.append(error)
                    stop_child()
                finally:
                    child.stdout.close()
            def read_error():
                try:
                    for chunk in iter(lambda: child.stderr.read(65536), b""):
                        diagnostics.extend(chunk)
                        if len(diagnostics) > 65536:
                            del diagnostics[:-65536]
                except (OSError, ValueError) as error:
                    reader_errors.append(error)
                    stop_child()
                finally:
                    child.stderr.close()
            readers = [threading.Thread(target=read_output), threading.Thread(target=read_error)]
            for reader in readers:
                reader.start()
            try:
                if stdin is not None:
                    try:
                        child.stdin.write(stdin)
                        child.stdin.close()
                    except BrokenPipeError:
                        try:
                            child.stdin.close()
                        except BrokenPipeError:
                            pass
                code = child.wait()
            except BaseException:
                stop_child()
                child.wait()
                raise
            finally:
                for reader in readers:
                    reader.join()
            output_file.seek(0)
            output = output_file.read()
        if exceeded.is_set():
            fail("Engine-Ausgabe ueberschreitet das sichere Limit; Stand bleibt unbestaetigt.")
        if reader_errors:
            fail("Engine-Protokoll konnte nicht vollstaendig gelesen/gespeichert werden; Stand bleibt unbestaetigt.")
        return code, output, bytes(diagnostics)

    def run(self, arguments, stdin=None, allow_error=False):
        if not self.version_checked:
            code, output, _ = self.runner([str(self.engine), "version", "--json"])
            try:
                version = json.loads(output)["version"]
            except (ValueError, KeyError, TypeError):
                version = None
            if code or version != VERSION:
                fail("Restic-Version ist nicht der gepruefte Stand " + VERSION + ".")
            self.version_checked = True
        read_bytes(self.password, 4096, private=True)
        argv = [str(self.engine), "--repo", str(self.path), "--password-file", str(self.password),
                "--cache-dir", str(self.cache), "--json", *arguments]
        code, output, error = self.runner(argv, stdin)
        if code and not allow_error:
            fail("Repository-Vorgang fehlgeschlagen (Exit %s); keine Freigabe des Standes. %s" % (code, diagnostic(error)))
        return code, output, error

    def identity(self):
        secure_dir(self.root)
        marker = read_bytes(self.root / MARKER, 4096).strip()
        if not marker or b"\0" in marker:
            fail("Registrierungsmarker des Backup-Ziels fehlt.")
        return {"root": str(self.root), "marker_sha256": hashlib.sha256(marker).hexdigest(),
                "mount": self.identity_reader(self.root)}

    def load(self):
        value = json.loads(read_bytes(self.descriptor, private=True))
        if value.get("format") != FORMAT or value.get("target") != self.identity():
            fail("Backup-Ziel/Mount stimmt nicht mit dem eingerichteten Repository ueberein.")
        secure_dir(self.path)
        _, data, _ = self.run(["cat", "config"])
        if json.loads(data).get("id") != value.get("repository_id"):
            fail("Repository-Identitaet hat sich geaendert; kein lokales Ersatz-Repository anlegen.")
        return value

    def initialize(self):
        if self.descriptor.exists():
            return self.status()
        identity = self.identity()
        # Fail closed on a half-created/foreign repository. Recovery is explicit.
        if self.path.exists() or self.path.is_symlink() or self.password.exists():
            fail("Repository oder Schluessel bereits vorhanden; Wiederanbindung statt Neuinitialisierung erforderlich.")
        atomic_write(self.password, secrets.token_urlsafe(48).encode("ascii") + b"\n", exclusive=True)
        self.run(["init", "--repository-version", "2"])
        if identity != self.identity():
            fail("Backup-Ziel wurde waehrend der Einrichtung gewechselt.")
        _, output, _ = self.run(["cat", "config"])
        repository_id = snapshot_id(json.loads(output).get("id"))
        descriptor = {"format": FORMAT, "repository_id": repository_id, "target": identity,
                      "host_id": secrets.token_hex(16), "key_confirmed": False}
        atomic_write(self.descriptor, encode(descriptor))
        return self.status()

    def attach(self, recovery_key):
        if self.descriptor.exists() or self.password.exists():
            fail("Lokale Repository-Zuordnung besteht bereits; nicht automatisch ueberschreiben.")
        key = json.loads(read_bytes(Path(recovery_key), private=True))
        if key.get("format") != FORMAT or key.get("repository_directory") != REPOSITORY_NAME:
            fail("Ungueltiges Wiederherstellungspaket.")
        expected = snapshot_id(key.get("repository_id"))
        token(key.get("host_id"))
        secret = key.get("password")
        if not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{64}", secret):
            fail("Ungueltiger Wiederherstellungsschluessel.")
        secure_dir(self.path)
        identity = self.identity()
        atomic_write(self.password, secret.encode("ascii") + b"\n", exclusive=True)
        try:
            _, output, _ = self.run(["cat", "config"])
            if json.loads(output).get("id") != expected or self.identity() != identity:
                fail("Wiederherstellungsschluessel und Repository stimmen nicht ueberein.")
            value = {"format": FORMAT, "repository_id": expected, "host_id": key["host_id"],
                     "target": identity, "key_confirmed": True}
            atomic_write(self.descriptor, encode(value), exclusive=True)
        except Exception:
            self.password.unlink(missing_ok=True)
            raise
        return self.status()

    def status(self):
        value = self.load()
        return {"format": FORMAT, "repository_id": value["repository_id"], "host_id": value["host_id"],
                "key_confirmed": value.get("key_confirmed") is True, "engine_version": VERSION}

    def export_key(self, output):
        value = self.load()
        secret = read_bytes(self.password, 4096, private=True).strip().decode("ascii")
        bundle = {"format": FORMAT, "repository_id": value["repository_id"], "host_id": value["host_id"],
                  "repository_directory": REPOSITORY_NAME, "password": secret,
                  "warning": "Geheim halten und ausserhalb dieses LoxBerry aufbewahren. Repository-Daten ebenfalls erforderlich."}
        content = encode(bundle) + b"\n"
        atomic_write(Path(output), content, exclusive=True)
        return {"sha256": hashlib.sha256(content).hexdigest(), "output": str(output)}

    def confirm_key(self, checksum):
        value = self.load()
        secret = read_bytes(self.password, 4096, private=True).strip().decode("ascii")
        bundle = {"format": FORMAT, "repository_id": value["repository_id"], "host_id": value["host_id"],
                  "repository_directory": REPOSITORY_NAME, "password": secret,
                  "warning": "Geheim halten und ausserhalb dieses LoxBerry aufbewahren. Repository-Daten ebenfalls erforderlich."}
        if checksum != hashlib.sha256(encode(bundle) + b"\n").hexdigest():
            fail("Bestaetigung passt nicht zum exportierten Wiederherstellungsschluessel.")
        value["key_confirmed"] = True
        atomic_write(self.descriptor, encode(value))
        return {"key_confirmed": True}

    def snapshots(self):
        _, output, _ = self.run(["snapshots"])
        result = json.loads(output)
        if not isinstance(result, list):
            fail("Ungueltige Snapshot-Liste.")
        for row in result:
            snapshot_id(row.get("id"))
        return result

    def inventory(self, sid):
        _, output, _ = self.run(["ls", snapshot_id(sid)])
        result = {}
        for line in output.splitlines():
            row = json.loads(line)
            if row.get("struct_type") != "node":
                continue
            path, kind = row.get("path"), row.get("type")
            if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                    or ".." in PurePosixPath(path).parts or path != str(PurePosixPath(path))
                    or kind not in {"file", "dir", "symlink", "fifo", "dev", "chardev"} or path in result):
                fail("Unsicherer Pfad oder Dateityp im Repository-Inventar.")
            result[path] = kind
        if not result:
            fail("Leeres Repository-Inventar.")
        for path in result:
            for parent in PurePosixPath(path).parents:
                if str(parent) in result and result[str(parent)] != "dir":
                    fail("Repository-Pfad liegt unter einem Nicht-Verzeichnis oder symbolischen Link.")
        return result

    @staticmethod
    def inventory_matches(selected, actual):
        # Restic adds intermediate directory nodes above fixture roots. These
        # may not contain any additional files, symlinks or descendants.
        expected = dict(selected)
        for path in selected:
            for parent in PurePosixPath(path).parents:
                expected.setdefault(str(parent), "dir")
        # The implicit repository tree root '/' is not emitted by all versions.
        expected.pop("/", None)
        actual = dict(actual)
        actual.pop("/", None)
        if expected != actual:
            fail("Gesicherte Pfade/Dateitypen weichen von der expliziten Quellenauswahl ab; Stand nicht freigegeben.")

    @staticmethod
    def summary(output):
        summaries = [json.loads(line) for line in output.splitlines() if line.strip()]
        summaries = [row for row in summaries if row.get("message_type") == "summary"]
        if len(summaries) != 1:
            fail("Eindeutiger Backup-Abschlussbericht fehlt.")
        snapshot_id(summaries[0].get("snapshot_id"))
        return summaries[0]

    def backup(self, backup_id, file_list, lineage, source_root=Path("/")):
        descriptor = self.load()
        if descriptor.get("key_confirmed") is not True:
            fail("Wiederherstellungsschluessel zuerst ausserhalb des LoxBerry sichern und bestaetigen.")
        token(backup_id)
        token(lineage)
        selected = selected_paths(Path(file_list), source_root)
        root_attributes = root_metadata(source_root)
        for path in selected:
            physical = Path(path)
            if physical == self.root or self.root in physical.parents or physical == self.state_base or self.state_base in physical.parents:
                fail("Repository oder privater Root-State ist in der Quellenauswahl enthalten.")
        records = self.list_committed()
        if any(row["backup_id"] == backup_id for row in records):
            fail("Sicherungs-ID existiert bereits.")
        parents = [row for row in records if row["host_id"] == descriptor["host_id"] and row["lineage"] == lineage]
        parent = max(parents, key=lambda row: row["created_at"])["data_snapshot_id"] if parents else None
        with tempfile.NamedTemporaryFile(dir=self.state, prefix="selection-", delete=False) as source:
            list_path = Path(source.name)
            for path in selected:
                source.write(path.encode("utf-8") + b"\0")
        try:
            arguments = ["backup", "--files-from-raw", str(list_path), "--exclude", "**",
                         "--host", descriptor["host_id"], "--tag", "hostbackup:candidate",
                         "--tag", "hostbackup:lineage:" + lineage, "--tag", "hostbackup:backup:" + backup_id]
            arguments += ["--parent", parent] if parent else ["--force"]
            code, output, error = self.run(arguments, allow_error=True)
            if code:
                fail("Portable Sicherung unvollstaendig/fehlgeschlagen (Exit %s); Candidate wird nicht freigegeben. %s" % (code, diagnostic(error)))
            if error.strip():
                # Restic can warn about unreadable xattrs without a nonzero exit.
                # Do not declare full metadata fidelity after any such warning.
                fail("Portable Sicherung meldet Warnungen; Metadatenerhaltung muss geklaert werden, Stand nicht freigegeben. " + diagnostic(error))
            summary = self.summary(output)
            actual = self.inventory(summary["snapshot_id"])
            self.inventory_matches(selected, actual)
            self.load()  # Detect target replacement before producing a receipt.
            receipt = {"format": FORMAT, "status": "candidate", "repository_id": descriptor["repository_id"],
                       "host_id": descriptor["host_id"], "lineage": lineage, "backup_id": backup_id,
                       "data_snapshot_id": summary["snapshot_id"], "inventory_sha256": digest(actual),
                       "source_root": str(source_root), "root_metadata": root_attributes,
                       "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "summary": summary}
            atomic_write(self.state / ("candidate-" + backup_id + ".json"), encode(receipt), exclusive=True)
            return receipt
        finally:
            list_path.unlink(missing_ok=True)

    def commit(self, backup_id, candidate, controls):
        descriptor = self.load()
        token(backup_id)
        receipt = json.loads(read_bytes(Path(candidate), private=True))
        saved = json.loads(read_bytes(self.state / ("candidate-" + backup_id + ".json"), private=True))
        if receipt != saved or receipt.get("repository_id") != descriptor["repository_id"] or receipt.get("backup_id") != backup_id:
            fail("Candidate-Beleg stimmt nicht mit dem privaten erfolgreichen Kopierlauf ueberein.")
        for published in self.list_committed():
            if published["backup_id"] == backup_id:
                if published["data_snapshot_id"] != receipt["data_snapshot_id"]:
                    fail("Sicherungs-ID ist bereits an einen anderen Datenstand gebunden.")
                return published
        sid = snapshot_id(receipt["data_snapshot_id"])
        if digest(self.inventory(sid)) != receipt.get("inventory_sha256"):
            fail("Candidate-Inventar stimmt nicht mit dem geprueften Kopierlauf ueberein.")
        directory = secure_dir(controls)
        files = {name: base64.b64encode(read_bytes(directory / name)).decode("ascii")
                 for name in sorted(CONTROLS) if (directory / name).exists() or (directory / name).is_symlink()}
        if not {"manifest.json", "rsync-excludes.txt", "source-selection.json", "backup-validation.json"}.issubset(files):
            fail("Wiederherstellungskontrollen fehlen: Manifest, Ausschluesse, Quellenauswahl und Pruefergebnis erforderlich.")
        manifest = json.loads(base64.b64decode(files["manifest.json"]))
        if manifest.get("backup_id") != backup_id:
            fail("Manifest gehoert nicht zu dieser Sicherung.")
        validation = json.loads(base64.b64decode(files["backup-validation.json"]))
        if (manifest.get("status"), validation.get("status")) not in {("complete", "ok"), ("complete_with_warnings", "warning")}:
            fail("Nur abgeschlossene und gepruefte Sicherungen duerfen veroeffentlicht werden.")
        record = {**receipt, "status": "committed", "controls": files}
        content = encode(record)
        if len(content) > MAX_CONTROL:
            fail("Wiederherstellungskontrollen sind zu gross.")
        self.load()
        _, output, _ = self.run(["backup", "--stdin", "--stdin-filename", CONTROL_NAME,
                                "--host", descriptor["host_id"], "--tag", "hostbackup:commit",
                                "--tag", "hostbackup:backup:" + backup_id], stdin=content)
        record["commit_id"] = self.summary(output)["snapshot_id"]
        record["commit_snapshot_id"] = record["commit_id"]
        self.load()
        atomic_write(self.state / ("committed-" + backup_id + ".json"), encode(record))
        return record

    def read_commit(self, sid, snapshots=None, descriptor=None):
        descriptor = self.load() if descriptor is None else descriptor
        sid = snapshot_id(sid)
        rows = self.snapshots() if snapshots is None else snapshots
        matches = [row for row in rows if row["id"] == sid and "hostbackup:commit" in row.get("tags", [])]
        if len(matches) != 1:
            fail("Commit-Snapshot fehlt oder ist nicht eindeutig.")
        _, output, _ = self.run(["dump", sid, "/" + CONTROL_NAME])
        if len(output) > MAX_CONTROL:
            fail("Commit-Kontrolldatei ist zu gross.")
        record = json.loads(output)
        if (not isinstance(record, dict) or record.get("format") != FORMAT or record.get("status") != "committed"
                or record.get("repository_id") != descriptor["repository_id"]):
            fail("Ungueltiger authentifizierter Sicherungsbeleg.")
        data = snapshot_id(record.get("data_snapshot_id"))
        token(record.get("backup_id"))
        token(record.get("host_id"))
        token(record.get("lineage"))
        expected = {"hostbackup:candidate", "hostbackup:backup:" + record["backup_id"],
                    "hostbackup:lineage:" + record["lineage"]}
        data_rows = [row for row in rows if row["id"] == data and row.get("hostname") == record["host_id"]
                     and expected.issubset(set(row.get("tags", [])))]
        if len(data_rows) != 1:
            fail("Daten-Snapshot des Sicherungsbelegs fehlt oder gehoert zu einer anderen Sicherung.")
        controls = record.get("controls")
        if not isinstance(controls, dict) or not set(controls).issubset(CONTROLS):
            fail("Ungueltige Kontrolldateinamen im Sicherungsbeleg.")
        if not {"manifest.json", "rsync-excludes.txt", "source-selection.json", "backup-validation.json"}.issubset(controls):
            fail("Sicherungsbeleg enthaelt nicht alle Wiederherstellungskontrollen.")
        for encoded in controls.values():
            base64.b64decode(encoded, validate=True)
        record["commit_id"] = sid
        record["commit_snapshot_id"] = sid
        return record

    def list_committed(self):
        descriptor = self.load()
        rows = self.snapshots()
        records = [self.read_commit(row["id"], rows, descriptor) for row in rows if "hostbackup:commit" in row.get("tags", [])]
        return sorted(records, key=lambda row: (row["created_at"], row["commit_id"]))

    def check(self, read_data=False):
        self.load()
        self.run(["check", *(["--read-data"] if read_data else [])])
        self.load()
        return {"status": "ok", "read_data": bool(read_data), "metadata_roundtrip": "not_performed"}

    def forget(self, sid):
        record = self.read_commit(sid)
        if record["host_id"] != self.load()["host_id"]:
            fail("Sicherungen eines anderen Quellsystems duerfen nicht geloescht werden.")
        # Remove publication first. A crash may leave unreachable data but never
        # a visible successful backup whose data was deliberately removed first.
        self.run(["forget", snapshot_id(sid)])
        remaining = self.list_committed()
        if not any(row["data_snapshot_id"] == record["data_snapshot_id"] for row in remaining):
            self.run(["forget", record["data_snapshot_id"]])
        self.load()
        return {"forgotten_commit_id": sid, "space_reclaimed": False}

    def prune(self, dry_run=True, confirm_repository_id=None):
        """Plan by default; reclaim only with an explicit exact repository ID.

        Keep every remaining snapshot, including unpublished candidates. A zero
        repack budget only removes wholly unused packs; it deliberately leaves
        unused blobs in partially used packs instead of requiring a large copy.
        The trusted caller holds the plugin operation lock for this entire call.
        """
        if type(dry_run) is not bool:
            fail("Repository-Bereinigung benoetigt eine ausdrueckliche Vorschau/Ausfuehrung.")
        descriptor = self.load()
        expected = snapshot_id(descriptor.get("repository_id"))
        if confirm_repository_id is not None and snapshot_id(confirm_repository_id) != expected:
            fail("Bestaetigte Repository-ID stimmt nicht mit dem eingerichteten Backup-Ziel ueberein.")
        if not dry_run:
            if confirm_repository_id is None:
                fail("Ausfuehrung erst nach Vorschau mit vollstaendiger --confirm-repository-id bestaetigen.")
            if descriptor.get("key_confirmed") is not True:
                fail("Wiederherstellungsschluessel zuerst ausserhalb des LoxBerry sichern und bestaetigen.")
        self.check(read_data=False)
        if self.load()["repository_id"] != expected:
            fail("Repository-Identitaet hat sich vor der Bereinigung geaendert.")
        arguments = ["prune", "--max-repack-size", "0"]
        if dry_run:
            arguments.append("--dry-run")
        _, output, error = self.run(arguments)
        self.check(read_data=False)
        if self.load()["repository_id"] != expected:
            fail("Repository-Identitaet hat sich waehrend der Bereinigung geaendert.")
        return {"status": "preview" if dry_run else "ok", "dry_run": dry_run,
                "repository_id": expected, "max_repack_size": 0,
                "checks": {"before": "ok", "after": "ok"},
                "snapshots_forgotten": False, "candidates_removed": False,
                "summary": diagnostic(output + b"\n" + error),
                "message": "Vorschau ohne Datenloeschung." if dry_run else
                           "Nur vollstaendig unbenutzte Datenpakete bereinigt; teilweise belegte Pakete und alle verbleibenden Sicherungs-IDs bleiben erhalten."}

    def stage(self, sid, destination):
        record = self.read_commit(sid)
        destination = secure_dir(destination, private=True)
        if str(destination) == "/" or any(destination.iterdir()):
            fail("Restore-Staging muss ein leeres privates Verzeichnis sein; niemals direkt das laufende System.")
        if (destination == self.root or self.root in destination.parents
                or destination == self.state or self.state in destination.parents
                or destination in self.root.parents or destination in self.state.parents):
            fail("Restore-Staging darf Repository oder Root-State nicht ueberlappen.")
        identity = self.identity_reader(destination)
        if identity["fstype"] not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs"}:
            fail("Vollstaendiger Restore benoetigt ausreichend grossen Linux-Staging-Speicher mit Linux-Metadaten.")
        actual = self.inventory(record["data_snapshot_id"])
        if digest(actual) != record.get("inventory_sha256"):
            fail("Snapshot-Inventar stimmt nicht mit dem freigegebenen Stand ueberein.")
        _, output, _ = self.run(["stats", record["data_snapshot_id"], "--mode", "restore-size"])
        usage = json.loads(output)
        needed, count = usage.get("total_size"), usage.get("total_file_count")
        if type(needed) is not int or needed < 0 or type(count) is not int or count < 0:
            fail("Staging-Platzbedarf konnte nicht sicher ermittelt werden.")
        filesystem = os.statvfs(destination)
        reserve = max(16 * 1024 * 1024, needed // 20)
        if filesystem.f_bavail * filesystem.f_frsize < needed + reserve:
            fail("Nicht genug freier Linux-Staging-Speicher fuer vollstaendige Wiederherstellung plus Reserve.")
        if filesystem.f_files > 0 and filesystem.f_favail >= 0 and filesystem.f_favail < count + 32:
            fail("Nicht genug freie Inodes auf dem Linux-Staging-Dateisystem.")
        rootfs = destination / "rootfs"
        rootfs.mkdir(mode=0o700)
        _, _, error = self.run(["restore", record["data_snapshot_id"], "--target", str(rootfs), "--sparse", "--verify"])
        if error.strip():
            fail("Restore meldet Warnungen; Staging wird nicht freigegeben. " + diagnostic(error))
        if identity != self.identity_reader(destination):
            fail("Staging-Mount wurde waehrend des Restore gewechselt.")
        source_root = record.get("source_root")
        if (not isinstance(source_root, str) or not source_root.startswith("/") or source_root.startswith("//")
                or ".." in PurePosixPath(source_root).parts or source_root != str(PurePosixPath(source_root))):
            fail("Ungueltiger Quellroot im Sicherungsbeleg.")
        restored_root = rootfs / source_root.lstrip("/")
        secure_dir(restored_root)
        apply_root_metadata(restored_root, record["root_metadata"])
        controls = destination / "control"
        controls.mkdir(mode=0o700)
        for name, value in record["controls"].items():
            atomic_write(controls / name, base64.b64decode(value, validate=True), exclusive=True)
        atomic_write(controls / "repository-reference.json", encode({key: record[key] for key in
                     ("format", "repository_id", "commit_id", "data_snapshot_id", "backup_id")}))
        self.load()
        return {"status": "staged", "rootfs": str(rootfs), "controls": str(controls),
                "commit_id": sid, "metadata_roundtrip": "must_be_verified_by_caller",
                "warning": "Staging ist kein System-Restore. Vorhandenen Recovery-Plan und Metadatenpruefung verwenden."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--state-dir", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "list"):
        commands.add_parser(name)
    sub = commands.add_parser("prune", help="Default: preview without deleting repository data.")
    sub.add_argument("--confirm-repository-id", help="Execute only for this exact complete repository ID.")
    sub = commands.add_parser("check")
    sub.add_argument("--read-data", action="store_true")
    sub = commands.add_parser("key-export")
    sub.add_argument("--output", required=True)
    sub = commands.add_parser("attach")
    sub.add_argument("--recovery-key", required=True)
    sub = commands.add_parser("confirm-key")
    sub.add_argument("--sha256", required=True)
    sub = commands.add_parser("backup")
    sub.add_argument("--backup-id", required=True)
    sub.add_argument("--files-from", required=True)
    sub.add_argument("--lineage", required=True)
    sub.add_argument("--source-root", default="/")
    sub = commands.add_parser("commit")
    sub.add_argument("--backup-id", required=True)
    sub.add_argument("--candidate", required=True)
    sub.add_argument("--controls", required=True)
    sub = commands.add_parser("forget")
    sub.add_argument("--commit-id", required=True)
    sub = commands.add_parser("stage")
    sub.add_argument("--commit-id", required=True)
    sub.add_argument("--destination", required=True)
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        fail("Repository-Adapter darf nur durch das vertrauenswuerdige Linux-Root-Backend aufgerufen werden.")
    adapter = Repository(args.backup_root, args.state_dir)
    actions = {"init": lambda: adapter.initialize(), "status": lambda: adapter.status(),
               "list": lambda: adapter.list_committed(),
               "prune": lambda: adapter.prune(dry_run=args.confirm_repository_id is None,
                                               confirm_repository_id=args.confirm_repository_id),
               "check": lambda: adapter.check(args.read_data), "key-export": lambda: adapter.export_key(args.output),
               "attach": lambda: adapter.attach(args.recovery_key),
               "confirm-key": lambda: adapter.confirm_key(args.sha256),
               "backup": lambda: adapter.backup(args.backup_id, args.files_from, args.lineage, Path(args.source_root)),
               "commit": lambda: adapter.commit(args.backup_id, args.candidate, args.controls),
               "forget": lambda: adapter.forget(args.commit_id),
               "stage": lambda: adapter.stage(args.commit_id, args.destination)}
    print(json.dumps(actions[args.command](), ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (RepositoryError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=True))
        sys.exit(1)
