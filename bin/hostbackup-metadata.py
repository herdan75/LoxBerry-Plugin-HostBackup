#!/usr/bin/env python3
"""Probe a registered target with disposable metadata, never user backup files.

The trusted caller must verify target identity before and after this helper.
Only JSON is written to stdout; no diagnostics or credentials are persisted.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time


MODES = ("native-strict", "network-compatible", "fake-super", "portable-archive")
OUTPUT_LIMIT = 4096
COMMAND_TIMEOUT = 45
PROBE_COMMAND_BUDGET = 90
LOCAL_TRANSPORT = "--rsh=/bin/sh -c 'shift; exec \"$@\"' hostbackup-local"
TAR_OPTIONS = ["--format=pax", "--numeric-owner", "--acls", "--xattrs",
               "--xattrs-include=*", "--selinux", "--sparse"]


def rsync_options(mode, restoring=False):
    options = ["-aHA" if mode == "network-compatible" else "-aHAX",
               "--numeric-ids", "--sparse"]
    if mode == "fake-super":
        options += ["--fake-super", "-M--super"] if restoring else ["-M--fake-super"]
        # Keep the production workaround for local rsync/popt -M corruption.
        options += ["--whole-file", "--protect-args", LOCAL_TRANSPORT]
    return options


def rsync_destination(mode, path):
    return ("hostbackup-local:" if mode == "fake-super" else "") + str(path) + "/"


def run_bounded(argv, timeout=COMMAND_TIMEOUT):
    """Drain both pipes but retain only bounded text; kill all local children on timeout."""
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=(os.name == "posix"))
    except OSError as exc:
        return {"exit_code": 127, "stdout": "", "stderr": str(exc), "timed_out": False}
    outputs = {}
    deadline = time.monotonic() + timeout

    def stop_children():
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()

    def drain(name, stream):
        retained = bytearray()
        total = 0
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                retained.extend(chunk[:max(0, OUTPUT_LIMIT - len(retained))])
        finally:
            stream.close()
        outputs[name] = retained.decode("utf-8", errors="replace")
        if total > OUTPUT_LIMIT:
            outputs[name] += "\n[Ausgabe gekuerzt]"

    threads = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_children()
        process.wait()
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        # A child can keep its parent's pipes open after the parent has exited.
        timed_out = True
        stop_children()
        for thread in threads:
            thread.join(timeout=2)
    return {"exit_code": process.returncode, "stdout": outputs.get("stdout", ""),
            "stderr": outputs.get("stderr", ""), "timed_out": timed_out}


class Probe:
    def __init__(self, mode, runner=run_bounded):
        self.mode = mode
        self.runner = runner
        self.checks = []
        self.redactions = []
        self.command_deadline = time.monotonic() + PROBE_COMMAND_BUDGET

    def clean(self, value):
        text = str(value)
        for path, replacement in self.redactions:
            text = text.replace(str(path), replacement)
        text = re.sub(r"(?i)\b(password|passwd|pass|credentials|username|user)=([^\s,;]+)",
                      r"\1=<entfernt>", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "?", text)
        return text[:OUTPUT_LIMIT + 32]

    def add(self, key, name, ok, details, **extra):
        check = {"id": key, "name": name, "status": "ok" if ok else "error",
                 "ok": bool(ok), "details": self.clean(details)}
        check.update({key: self.clean(value) if isinstance(value, str) else value
                      for key, value in extra.items()})
        self.checks.append(check)
        return check

    def skipped(self, key, name, reason):
        self.checks.append({"id": key, "name": name, "status": "skipped",
                            "details": reason})

    def command(self, key, name, argv):
        remaining = self.command_deadline - time.monotonic()
        if remaining <= 0:
            result = {"exit_code": 124, "stdout": "", "stderr": "Gesamtzeitlimit fuer externe Pruefschritte erreicht.", "timed_out": True}
        elif self.runner is run_bounded:
            result = self.runner([str(arg) for arg in argv], timeout=min(COMMAND_TIMEOUT, remaining))
        else:
            result = self.runner([str(arg) for arg in argv])
        ok = result["exit_code"] == 0 and not result.get("timed_out")
        details = "Erfolgreich." if ok else "Befehl fehlgeschlagen (Exit-Code %s)." % result["exit_code"]
        if result.get("timed_out"):
            details += " Zeitlimit der Metadatenprobe ueberschritten."
        if result.get("stderr", "").strip():
            details += " " + result["stderr"].strip()
        self.add(key, name, ok, details, exit_code=result["exit_code"],
                 stderr=result.get("stderr", ""), timed_out=bool(result.get("timed_out")))
        return result

    def comparison(self, key, name, expected, actual):
        return self.add(key, name, expected == actual,
                        "Erwartet: %s; erhalten: %s." % (expected, actual),
                        expected=expected, actual=actual)

    def result(self):
        failed = [check for check in self.checks if check["status"] == "error"]
        skipped = [check["name"] for check in self.checks if check["status"] == "skipped"]
        message = "Metadaten-Roundtrip fuer Modus %s " % self.mode
        advice = []
        if failed:
            message += "ist fehlgeschlagen: " + "; ".join(check["name"] for check in failed) + "."
            advice.append("Details zeigen den fehlgeschlagenen Kopier- oder Wiederherstellungsschritt; die Sicherheitspruefung bleibt aktiv.")
            if self.mode != "portable-archive":
                advice.append("Bei CIFS/NFS feste UID/GID, file_mode/dir_mode sowie Unterstuetzung fuer Rechte, ACLs, Links und Sparse-Dateien pruefen. Network Compatible laesst nur xattrs und File Capabilities weg.")
                advice.append("Falls das Ziel Linux-Metadaten nicht erhalten kann: Portable Archive speichert sie im Archiv. Nur Vollbackup, keine inkrementellen Snapshots; Restore nur offline/in einer Rescue-Umgebung. Dieses Profil muss ebenfalls die Zielpruefung bestehen.")
        else:
            message += "erfolgreich: Dateninhalt, UID/GID, Rechte, Symlink, Hardlinks und Sparse-Datei zurueckgespielt und verglichen."
            for key, label in (("acl-values", "ACL-Werte"), ("xattr-values", "xattr-Werte"),
                               ("capability-values", "File Capabilities")):
                if any(check["id"] == key and check["status"] == "ok" for check in self.checks):
                    message += " %s bestaetigt." % label
        if skipped:
            message += " Nicht geprueft: " + ", ".join(skipped) + "."
        return {"status": "error" if failed else "ok", "mode": self.mode,
                "message": message, "checks": self.checks, "advice": advice}


def checked_directory(value, private=False):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or any(char in str(path) for char in "\x00\r\n"):
        raise ValueError("Absoluter, eindeutiger Verzeichnispfad erforderlich.")
    for component in (path, *path.parents):
        if component.is_symlink() or not component.is_dir():
            raise ValueError("Fehlende oder symbolische Verzeichniskomponente.")
        if private and os.name == "posix":
            info = component.stat()
            safe_sticky_parent = component != path and info.st_mode & stat.S_ISVTX
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not safe_sticky_parent):
                raise ValueError("Lokales Arbeitsverzeichnis ist nicht gegen fremde Schreibzugriffe geschuetzt.")
    return path.resolve()


def prepare_source(probe, source):
    (source / "sub").mkdir()
    payload = source / "sub/file"
    payload.write_bytes(b"metadata-probe\n")
    os.link(payload, source / "sub/hardlink")
    os.symlink("sub/file", source / "symlink")
    with (source / "sparse").open("wb") as handle:
        handle.truncate(1048576)
    if os.geteuid() == 0:
        os.chown(payload, 1, 1)
    os.chmod(payload, 0o6750)
    probe.add("source-fixture", "Lokale Testdateien", True, "Private Testdaten mit UID/GID, Rechten, Links und Sparse-Datei angelegt.")
    enabled = {"acl": False, "xattr": False, "capability": False}
    if probe.mode == "network-compatible":
        probe.skipped("xattr-values", "xattrs", "Im Profil Network Compatible bewusst ausgelassen.")
        probe.skipped("capability-values", "File Capabilities", "Im Profil Network Compatible bewusst ausgelassen.")
    else:
        if all(shutil.which(tool) for tool in ("setfattr", "getfattr")):
            enabled["xattr"] = True
            probe.command("source-xattr", "Test-xattr setzen", ["setfattr", "-n", "user.loxberryhostbackup", "-v", "probe", payload])
        else:
            probe.skipped("xattr-values", "xattrs", "setfattr/getfattr fehlen; nicht verifiziert.")
        if os.geteuid() == 0 and all(shutil.which(tool) for tool in ("setcap", "getcap")):
            enabled["capability"] = True
            capability = source / "capability"
            capability.write_bytes(b"capability-probe\n")
            probe.command("source-capability", "Test-File-Capability setzen", ["setcap", "cap_net_bind_service=ep", capability])
        else:
            probe.skipped("capability-values", "File Capabilities", "Root oder setcap/getcap fehlen; nicht verifiziert.")
    if all(shutil.which(tool) for tool in ("setfacl", "getfacl")):
        enabled["acl"] = True
        probe.command("source-acl", "Test-ACL setzen", ["setfacl", "-m", "u:65534:r--", payload])
    else:
        probe.skipped("acl-values", "ACL-Werte", "setfacl/getfacl fehlen; nicht verifiziert.")
    return enabled


def compare_restored(probe, source, restored, enabled):
    payload = source / "sub/file"
    actual_file = restored / "sub/file"
    try:
        if (not stat.S_ISDIR((restored / "sub").lstat().st_mode)
                or not stat.S_ISREG(actual_file.lstat().st_mode)):
            raise ValueError("Wiederhergestellte Testdatei oder ihr Verzeichnis ist ein Link oder hat einen unerwarteten Typ.")
    except (OSError, ValueError) as exc:
        probe.add("restored-file", "Wiederhergestellte Testdatei", False, str(exc))
        return

    def inspect(key, name, action):
        try:
            action()
        except (OSError, ValueError) as exc:
            probe.add(key, name, False, "Vergleich nicht moeglich: " + str(exc))

    def regular_file():
        with actual_file.open("rb") as handle:
            actual = handle.read(64)
        probe.comparison("file-content", "Dateiinhalt", payload.read_bytes().hex(), actual.hex())

    inspect("file-content", "Dateiinhalt", regular_file)
    inspect("symlink", "Symbolischer Link", lambda: probe.comparison("symlink", "Symbolischer Link", "sub/file", os.readlink(restored / "symlink")))

    def ownership():
        expected, actual = payload.lstat(), actual_file.lstat()
        probe.comparison("uid", "Eigentuemer (UID)", expected.st_uid, actual.st_uid)
        probe.comparison("gid", "Gruppe (GID)", expected.st_gid, actual.st_gid)
        probe.comparison("permissions", "Dateirechte (Modus)", format(stat.S_IMODE(expected.st_mode), "04o"), format(stat.S_IMODE(actual.st_mode), "04o"))

    inspect("ownership", "UID/GID und Dateirechte", ownership)

    def hardlink():
        left, right = actual_file.lstat(), (restored / "sub/hardlink").lstat()
        probe.add("hardlink", "Hardlinks", stat.S_ISREG(right.st_mode) and (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino), "Beide Testdateien muessen denselben Inode auf demselben Dateisystem haben.")

    inspect("hardlink", "Hardlinks", hardlink)

    def sparse():
        info = (restored / "sparse").lstat()
        probe.comparison("sparse-size", "Sparse-Dateigroesse", 1048576, info.st_size)
        allocated = info.st_blocks * 512
        probe.add("sparse-allocation", "Sparse-Speicherbelegung", stat.S_ISREG(info.st_mode) and allocated < 1048576,
                  "Belegte Bytes: %s; erforderlich: weniger als 1048576." % allocated,
                  expected="<1048576", actual=allocated)

    inspect("sparse-allocation", "Sparse-Datei", sparse)
    if enabled["acl"]:
        expected = probe.command("acl-read-source", "Quell-ACL lesen", ["getfacl", "-cpn", payload])
        actual = probe.command("acl-read-restored", "Wiederhergestellte ACL lesen", ["getfacl", "-cpn", actual_file])
        probe.comparison("acl-values", "ACL-Werte", expected["stdout"].rstrip(), actual["stdout"].rstrip())
    if enabled["xattr"]:
        actual = probe.command("xattr-read", "Wiederhergestelltes xattr lesen", ["getfattr", "--only-values", "-n", "user.loxberryhostbackup", actual_file])
        probe.comparison("xattr-values", "xattr-Werte", "probe", actual["stdout"].rstrip("\n"))
    if enabled["capability"]:
        capability = restored / "capability"
        actual = probe.command("capability-read", "Wiederhergestellte File Capability lesen", ["getcap", capability])
        value = actual["stdout"].strip()
        prefix = str(capability) + " "
        if value.startswith(prefix):
            value = value[len(prefix):]
        probe.comparison("capability-values", "File Capabilities", "cap_net_bind_service=ep", value)


def execute_probe(root, mode, state_dir, runner=run_bounded):
    probe = Probe(mode, runner=runner)
    directories = []
    try:
        if os.name != "posix":
            raise ValueError("Die reale Metadatenprobe benoetigt Linux.")
        root = checked_directory(root)
        state_dir = checked_directory(state_dir, private=True)
        if root == state_dir or root in state_dir.parents or state_dir in root.parents:
            raise ValueError("Ziel und lokales Arbeitsverzeichnis muessen getrennt sein.")
        for parent, prefix in ((state_dir, ".metadata-roundtrip."), (root, ".metadata-probe.")):
            directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
            info = directory.lstat()
            directories.append((directory, (info.st_dev, info.st_ino)))
        work, target = [item[0] for item in directories]
        source, restored = work / "source", work / "restored"
        source.mkdir(mode=0o700)
        restored.mkdir(mode=0o700)
        probe.redactions = [(source, "<Quelle>"), (restored, "<Wiederherstellung>"),
                            (target, "<Zielprobe>"), (work, "<Arbeitsverzeichnis>")]
        enabled = prepare_source(probe, source)
        if mode == "portable-archive":
            archive = target / "rootfs.tar"
            probe.command("copy", "Archiv auf Ziel schreiben", ["tar", *TAR_OPTIONS, "-C", source, "-cpf", archive, "."])
            probe.command("restore", "Archiv zurueckspielen", ["tar", *TAR_OPTIONS, "-C", restored, "-xpf", archive])
        else:
            probe.command("copy", "rsync: auf Ziel kopieren", ["rsync", *rsync_options(mode), str(source) + "/", rsync_destination(mode, target)])
            probe.command("restore", "rsync: vom Ziel zurueckspielen", ["rsync", *rsync_options(mode, restoring=True), str(target) + "/", rsync_destination(mode, restored)])
            if mode == "fake-super":
                values = probe.command("fake-super-read", "Fake-Super-Metadaten auf Ziel lesen", ["getfattr", "-d", "-m", r"^user\.rsync\.", target / "sub/file"])
                probe.add("fake-super-values", "Fake-Super-Metadaten", "user.rsync." in values["stdout"], "Erforderliche user.rsync.*-Attribute auf dem Ziel " + ("vorhanden." if "user.rsync." in values["stdout"] else "fehlen."))
        compare_restored(probe, source, restored, enabled)
    except (OSError, ValueError) as exc:
        probe.add("probe-setup", "Vorbereitung der Metadatenprobe", False, str(exc))
    finally:
        for directory, identity in reversed(directories):
            try:
                info = directory.lstat()
                if stat.S_ISLNK(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                    raise ValueError("Identitaet des Testverzeichnisses hat sich geaendert; keine automatische Bereinigung.")
                shutil.rmtree(directory)
            except (OSError, ValueError) as exc:
                probe.add("cleanup", "Testdateien entfernen", False, str(exc))
    return probe.result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = execute_probe(args.root, args.mode, args.state_dir)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
