#!/usr/bin/env python3
"""Coordinate selected LoxPanel containers using their installed protocol.

This helper never executes LoxPanel code, edits its configuration, or starts a
container. The parent worker remains responsible for immutable-ID recovery.
Protocol on stdout/stdin: SKIP (exit), READY loxpanel, CHECK -> OK,
RELEASE -> RELEASED (exit). Errors are one readable ERROR line and exit 20.
The parent must retain its control pipe through copying and service recovery.
EOF/owner death releases the kernel lock; no persistent stopped flag is left.
Older releases have no lock. Their existing deliberate-stop marker is only
observed, never created, removed or changed by HostBackup.
"""

import argparse
import errno
import json
import os
from pathlib import PurePosixPath
import re
import select
import signal
import stat
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:  # Pure validation tests also run on Windows.
    fcntl = None


MAX_TEXT = 131072
LOCK_NAME = ".loxpanel-ctl.lock"
CONTROLLER_SUFFIX = "/bin/plugins/loxpanel/loxpanel-ctl.sh"
DATA_SUFFIX = "/data/plugins/loxpanel"
CONFIG_SUFFIX = "/config/plugins/loxpanel"
STOP_NAME = "loxpanel_stopped.cfg"


class GuardError(Exception):
    pass


class UnsupportedController(GuardError):
    pass


def absolute_path(value):
    if (not isinstance(value, str) or not value.startswith("/") or value == "/"
            or value.startswith("//") or len(value) > 4096
            or str(PurePosixPath(value)) != value
            or any(part in (".", "..") for part in value.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise GuardError("Invalid absolute watchdog path.")
    return value


def open_directory(path):
    """Walk directories by descriptor; never follow any path-component link."""
    absolute_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.split("/")[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_regular(path, create=False, metadata_only=False):
    """Open read-only (or O_PATH metadata) without following links or truncating."""
    absolute_path(path)
    if create and metadata_only:
        raise GuardError("Metadata-only watchdog checks must not create files.")
    parent, name = path.rsplit("/", 1)
    directory = open_directory(parent)
    flags = (os.O_PATH if metadata_only else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    fd = None
    try:
        try:
            fd = os.open(name, flags, dir_fd=directory)
        except FileNotFoundError:
            if not create:
                raise
            try:
                fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=directory)
                # The watchdog opens read-only as loxberry. A root umask of 077
                # must not make it fall back to its unlocked restart path.
                os.fchmod(fd, 0o644)
            except FileExistsError:
                fd = os.open(name, flags, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise GuardError("Watchdog input must be a regular file without hardlinks.")
        return fd
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    finally:
        os.close(directory)


def read_text(path):
    fd = open_regular(path)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_TEXT + 1)
        if len(data) > MAX_TEXT:
            raise GuardError("Watchdog input is too large.")
        return data.decode("utf-8", errors="strict")
    finally:
        os.close(fd)


def parse_targets(text):
    targets = []
    if len(text) > MAX_TEXT or "\x00" in text:
        raise GuardError("Invalid stop-target list for watchdog coordination.")
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in ("docker", "systemd") or not fields[1]:
            raise GuardError("Invalid stop-target list for watchdog coordination.")
        if any(ord(char) < 32 or ord(char) == 127 for char in fields[1]):
            raise GuardError("Invalid stop-target identity for watchdog coordination.")
        if fields[0] == "docker" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", fields[1]):
            raise GuardError("Invalid Docker identity for watchdog coordination.")
        targets.append(tuple(fields))
    return targets


def docker_inventory():
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            env=dict(os.environ, LC_ALL="C"), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardError("Cannot inspect Docker containers for watchdog coordination.") from exc
    if result.returncode or len(result.stdout) > MAX_TEXT:
        raise GuardError("Cannot read Docker inventory for watchdog coordination.")
    inventory = []
    for line in result.stdout.decode("utf-8", errors="strict").splitlines():
        fields = line.split("\t")
        if (len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0])
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", fields[1])):
            raise GuardError("Invalid Docker inventory for watchdog coordination.")
        inventory.append(tuple(fields))
    return inventory


def selected_loxpanel(targets, legacy, inventory_reader=docker_inventory):
    if not targets:
        return legacy
    names = [name for kind, name in targets if kind == "docker"]
    if "loxpanel" in names:
        return True
    identities = [name for name in names if re.fullmatch(r"[a-f0-9]{12,64}", name)]
    if not identities:
        return False
    inventory = inventory_reader()
    # A hexadecimal container name takes priority over an ID-prefix match,
    # matching Docker's own name resolution without guarding an unrelated app.
    named = {name for _, name in inventory}
    return any(name == "loxpanel" and identity.startswith(candidate)
               for identity, name in inventory for candidate in identities if candidate not in named)


def container_state(identity):
    """Inspect an immutable ID, never a mutable/reused container name."""
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise GuardError("LoxPanel: ungueltige Container-ID; Status nicht bestaetigt.")
    try:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", "--format", "{{json .State}}", identity],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            env=dict(os.environ, LC_ALL="C"), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardError("LoxPanel: Docker-Status nicht erreichbar. Docker pruefen und erneut versuchen.") from exc
    if result.returncode or len(result.stdout) > MAX_TEXT:
        raise GuardError("LoxPanel: Container-Status konnte nicht sicher gelesen werden. Erneut pruefen.")
    try:
        state = json.loads(result.stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError) as exc:
        raise GuardError("LoxPanel: ungueltige Docker-Statusantwort.") from exc
    if (not isinstance(state, dict) or type(state.get("Running")) is not bool
            or state.get("Status") not in ("created", "running", "paused", "restarting", "removing", "exited", "dead")
            or ("Restarting" in state and type(state["Restarting"]) is not bool)):
        raise GuardError("LoxPanel: unvollstaendige Docker-Statusantwort.")
    if state["Status"] == "dead":
        raise GuardError("LoxPanel: Docker meldet einen defekten Containerzustand (dead). Docker pruefen und erneut versuchen.")
    return "stopped" if (state["Status"] in ("created", "exited")
                          and not state["Running"] and not state.get("Restarting", False)) else "running"


def controller_stop_path(text, home):
    """Recognise only the fixed installed stop-marker path; no shell evaluation."""
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    config = home + CONFIG_SUFFIX
    stopped = [line for line in lines if line.startswith("STOPPED=")]
    if stopped == ['STOPPED="' + config + '/' + STOP_NAME + '"']:
        return config + "/" + STOP_NAME
    configs = [line for line in lines if line.startswith("CONFIGDIR=")]
    if (stopped == ['STOPPED="$CONFIGDIR/' + STOP_NAME + '"']
            and configs in (['CONFIGDIR="' + config + '"'],
                            ['CONFIGDIR="${LOXPANEL_CTL_CONFIGDIR:-' + config + '}"'])):
        return config + "/" + STOP_NAME
    return None


def controller_profile(text, home):
    """Identify the published legacy marker protocol or the later flock protocol."""
    absolute_path(home)
    if re.search(r'[$`"\\]', home):
        raise UnsupportedController("LoxPanel: Installationspfad benoetigt eine nicht unterstuetzte Shell-Ersetzung.")
    if len(text) > MAX_TEXT or "\x00" in text:
        raise UnsupportedController("LoxPanel: Steuerdatei ist ungueltig oder nicht unterstuetzt.")
    try:
        path = validate_controller(text, home)
        return {"mode": "lock", "path": path, "stop_path": controller_stop_path(text, home)}
    except GuardError:
        pass
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    code = "\n".join(lines)
    stop_path = controller_stop_path(text, home)
    checks = list(re.finditer(r"(?:^|\n)check\)\s*\n(.*?)\n;;", code, re.S))
    check_lines = checks[0].group(1).splitlines() if len(checks) == 1 else []
    if (stop_path and len(check_lines) == 2
            and re.fullmatch(r'\[ -f "\$STOPPED" \] && exit 0(?:\s+#.*)?', check_lines[0])
            and check_lines[1] == "running || start"):
        return {"mode": "manual-stop", "path": stop_path, "stop_path": stop_path}
    raise UnsupportedController(
        "LoxPanel: Diese Steuerdatei bietet keine unterstuetzte Backup-Koordination. "
        "LoxPanel-Version und Installation pruefen; die Sicherheitspruefung nicht umgehen.")


def controller_function_body(code, name):
    """Read one plain function, rejecting overrides without evaluating shell.

    This deliberately recognises a small compatibility contract, not arbitrary
    shell syntax. Count even alternative/one-line declarations so an earlier
    harmless definition cannot hide a later override of the guarded function.
    """
    name = re.escape(name)
    declarations = re.findall(
        r"(?m)^(?:function[ \t]+" + name + r"(?=[ \t({]|$)|"
        + name + r"[ \t]*\([ \t]*\))", code)
    bodies = re.findall(r"(?:^|\n)" + name + r"[ \t]*\(\)[ \t]*\{[ \t]*\n(.*?)\n\}",
                        code, re.S)
    if len(declarations) != 1 or len(bodies) != 1:
        raise GuardError("LoxPanel watchdog function is missing, ambiguous or unsupported.")
    return bodies[0].splitlines()


def controller_check_body(code):
    """Recognise an inline check or its single synchronous function call.

    Released 0.9.9 moved check into pruefen(). The function name is immaterial;
    its complete guarded body, fixed paths and lock semantics still must match.
    No foreign code is executed and no version number grants compatibility.
    """
    # Also count quoted/alternative dispatch labels. A preceding check|boot)
    # must not hide behind a later, otherwise valid plain check) branch.
    heads = list(re.finditer(r"(?m)^(?:\([ \t]*)?(?=[^()\n]*\bcheck\b)[^()\n]*\)", code))
    if len(heads) != 1 or heads[0].group() != "check)":
        raise GuardError("LoxPanel watchdog check dispatch is missing or ambiguous.")
    tail = code[heads[0].end():]
    end = re.search(r";;[ \t]*(?:#[^\n]*)?(?:\n|$)", tail)
    if end is None:
        raise GuardError("LoxPanel watchdog check dispatch is incomplete.")
    body = tail[:end.start()].strip()
    delegate = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+\|\|[ \t]+exit[ \t]+1)?", body)
    if delegate:
        return controller_function_body(code, delegate.group(1)), "return"
    return body.splitlines(), "exit"


def validate_controller(text, home):
    """Recognise the installed controller's narrow, existing lock contract.

    This is compatibility detection, not execution or a shell interpreter. A
    modified/older implementation must be reviewed instead of guessed safe.
    """
    absolute_path(home)
    if re.search(r'[$`"\\]', home):
        raise GuardError("Unsupported shell expansion in LoxPanel installation path.")
    if len(text) > MAX_TEXT or "\x00" in text:
        raise GuardError("Unsupported LoxPanel watchdog controller.")
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    code = "\n".join(lines)
    data_path = home + DATA_SUFFIX
    assignments = ('DATADIR="${LOXPANEL_CTL_DATADIR:-' + data_path + '}"',
                   'DATADIR="' + data_path + '"')
    if [line for line in lines if line.startswith("DATADIR=")] not in ([assignments[0]], [assignments[1]]):
        raise GuardError("LoxPanel watchdog data directory is unsupported; stop LoxPanel in its own interface before backup.")
    if [line for line in lines if line.startswith("SPERRE=")] != ['SPERRE="$DATADIR/' + LOCK_NAME + '"']:
        raise GuardError("LoxPanel does not expose the supported watchdog lock; stop it in its own interface before backup.")
    expected = ('[ -e "$SPERRE" ] || : >"$SPERRE"',
                'exec 9<"$SPERRE" || return 2', 'flock -n 9 || return 1')
    body = tuple(controller_function_body(code, "_sperre"))
    check_lines, leave = controller_check_body(code)
    has_stop_check = bool(check_lines and re.fullmatch(
        r'\[ -f "\$STOPPED" \] && ' + leave + r' 0(?:\s+#.*)?', check_lines[0]))
    if leave == "return" and (not has_stop_check or not controller_stop_path(text, home)):
        raise GuardError("LoxPanel delegated watchdog requires its recognised intentional-stop marker.")
    if has_stop_check:
        check_lines = check_lines[1:]
    # A busy lock may print a literal message and leave, but never execute
    # another command (including command substitution inside the message).
    busy = r'\[ \$\? = 1 \] && \{(?: echo "[^"$`\\\n]*";)? ' + leave + r' 0; \}'
    if (body != expected or len(check_lines) != 3 or check_lines[0] != "_sperre"
            or not re.fullmatch(busy, check_lines[1])
            or check_lines[2] != "running || start"):
        raise GuardError("LoxPanel watchdog lock protocol is unsupported; stop LoxPanel in its own interface before backup.")
    return data_path + "/" + LOCK_NAME


def process_identity(text):
    _, separator, tail = text.rpartition(") ")
    fields = tail.split()
    if not separator or len(fields) < 20 or not fields[19].isdigit():
        raise GuardError("Cannot identify backup worker process.")
    return fields[0], fields[19]


class Owner:
    def __init__(self, pid):
        if pid < 2:
            raise GuardError("Invalid backup worker PID.")
        self.pid = pid
        self.start = self.identity()[1]

    def identity(self):
        with open("/proc/{}/stat".format(self.pid), "r", encoding="utf-8") as stream:
            return process_identity(stream.read(8192))

    def alive(self):
        try:
            state, started = self.identity()
            return started == self.start and state not in ("Z", "X", "x")
        except (OSError, GuardError, UnicodeError):
            return False


def watchdog_account():
    try:
        import pwd
        user = pwd.getpwnam("loxberry")
        groups = os.getgrouplist(user.pw_name, user.pw_gid)
    except (ImportError, KeyError, OSError) as exc:
        raise GuardError("Cannot identify the loxberry account for watchdog coordination.") from exc
    if user.pw_uid <= 0 or user.pw_gid < 0 or not groups or any(group < 0 for group in groups):
        raise GuardError("Unsafe loxberry account for watchdog coordination.")
    return user.pw_uid, user.pw_gid, groups


def probe_watchdog_access(path, identity, timeout=2, directory=False, metadata_only=False):
    """Prove actual watchdog access, including traversal and ACL semantics.

    The child drops to the real non-root watchdog user, opens read-only, checks
    the locked inode and exits. A legacy marker only needs the equivalent of
    shell [ -f ], not content-read permission: O_PATH verifies its type and
    identity while still requiring real parent traversal by the watchdog user.
    It never imports/executes another plugin. Mode bits alone are insufficient.
    """
    uid, gid, groups = watchdog_account()
    pid = os.fork()
    if pid == 0:
        try:
            close_inherited_descriptors()
            if os.geteuid() == 0:
                os.setgroups(groups)
                os.setgid(gid)
                os.setuid(uid)
            if (os.geteuid() != uid or os.getegid() != gid
                    or set(os.getgroups()) | {gid} != set(groups) | {gid}):
                os._exit(1)
            flags = ((os.O_PATH | os.O_DIRECTORY) if directory else
                     (os.O_PATH if metadata_only else os.O_RDONLY))
            fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            info = os.fstat(fd)
            os.close(fd)
            valid = (stat.S_ISDIR(info.st_mode) and os.access(path, os.X_OK, effective_ids=True)) if directory else (
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
            os._exit(0 if valid
                     and (info.st_dev, info.st_ino) == identity else 1)
        except BaseException:
            os._exit(1)
    deadline = time.monotonic() + timeout
    while True:
        ended, status = os.waitpid(pid, os.WNOHANG)
        if ended:
            if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
                return
            raise GuardError("LoxPanel watchdog cannot read its lock file as loxberry; permissions were not changed.")
        if time.monotonic() >= deadline:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, os.WNOHANG)
            raise GuardError("Timed out checking LoxPanel watchdog lock access; no permissions were changed.")
        time.sleep(0.025)


class LockGuard:
    def __init__(self, path, owner, timeout=10):
        self.path = path
        self.fd = open_regular(path, create=True)
        try:
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
            deadline = time.monotonic() + timeout
            while True:
                if not owner.alive():
                    raise GuardError("Backup worker exited before watchdog coordination.")
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    if time.monotonic() >= deadline:
                        raise GuardError("LoxPanel is busy with its own operation; no container was stopped. Try the backup again after it finishes.")
                    time.sleep(0.1)
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        current = os.fstat(self.fd)
        other = open_regular(self.path)
        try:
            info = os.fstat(other)
            if ((info.st_dev, info.st_ino) != self.identity
                    or (current.st_dev, current.st_ino) != self.identity):
                raise GuardError("LoxPanel watchdog lock changed during the backup; source consistency cannot be confirmed.")
        finally:
            os.close(other)
        probe_watchdog_access(self.path, self.identity)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def safe_path_present(path):
    """Existence without following links, including dangling links as present."""
    parent, name = absolute_path(path).rsplit("/", 1)
    try:
        directory = open_directory(parent)
    except FileNotFoundError:
        return False
    try:
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    finally:
        os.close(directory)


def marker_fingerprint(path):
    try:
        fd = open_regular(path, metadata_only=True)
    except FileNotFoundError as exc:
        raise GuardError(
            "LoxPanel hat noch keine bestaetigte manuelle Stopppause. "
            "LoxPanel in seiner eigenen Oberflaeche stoppen (nicht nur den Docker-Container), "
            "danach erneut pruefen. Nach dem Backup dort wieder starten.") from exc
    try:
        info = os.fstat(fd)
        identity = (info.st_dev, info.st_ino)
        try:
            probe_watchdog_access(path, identity, metadata_only=True)
        except GuardError as exc:
            raise GuardError(
                "LoxPanel kann seine Stopppause als Benutzer loxberry nicht erkennen. "
                "LoxPanel-Installation und Berechtigungen pruefen; HostBackup hat nichts geaendert.") from exc
        return identity + (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    finally:
        os.close(fd)


def loxpanel_identity(inventory):
    matches = [identity for identity, name in inventory if name == "loxpanel"]
    if len(matches) > 1:
        raise GuardError("LoxPanel: mehrdeutige Docker-Inventarliste; Status nicht bestaetigt.")
    return matches[0] if matches else None


class ManualStopGuard:
    """Observe a pre-existing user stop; never acquire ownership of that stop."""
    def __init__(self, path, expected_id):
        self.path = path
        self.expected_id = expected_id
        self.fingerprint = marker_fingerprint(path)
        self.check()

    def check(self):
        if marker_fingerprint(self.path) != self.fingerprint:
            raise GuardError(
                "LoxPanel: Die manuelle Stopppause wurde waehrend des Backups veraendert. "
                "LoxPanel erst nach dem Backup wieder starten und die Sicherung erneut ausfuehren.")
        identity = loxpanel_identity(docker_inventory())
        if identity != self.expected_id:
            raise GuardError(
                "LoxPanel: Der Container wurde waehrend der bestaetigten Stopppause entfernt oder neu erstellt. "
                "Keine Updates oder Starts waehrend des Backups ausfuehren; anschliessend erneut sichern.")
        if identity and container_state(identity) != "stopped":
            raise GuardError(
                "LoxPanel laeuft trotz gesetzter Stopppause. In der LoxPanel-Oberflaeche stoppen, "
                "auf den Abschluss warten und erneut pruefen. Waehrend des Backups nicht wieder starten.")

    def close(self):
        # A pre-existing user stop belongs to the user, on success and failure.
        pass


def resolve_coordination(home, targets_text, legacy):
    """One read-only resolver for both preflight and the actual worker."""
    absolute_path(home)
    targets = parse_targets(targets_text)
    possible = (not targets and legacy) or any(
        kind == "docker" and (name == "loxpanel" or re.fullmatch(r"[a-f0-9]{12,64}", name))
        for kind, name in targets)
    if not possible:
        return {"mode": "skip"}
    # A hexadecimal selection may belong to a completely different app. Resolve
    # its immutable ID before reading leftover/broken LoxPanel installation
    # files, so an unrelated selection cannot acquire a new dependency on them.
    inventory = None
    direct = (not targets and legacy) or ("docker", "loxpanel") in targets
    if not direct:
        inventory = docker_inventory()
        if not selected_loxpanel(targets, legacy, lambda: inventory):
            return {"mode": "skip"}
    controller_path = home + CONTROLLER_SUFFIX
    try:
        controller = read_text(controller_path)
    except FileNotFoundError:
        if safe_path_present(home + DATA_SUFFIX) or safe_path_present(home + CONFIG_SUFFIX):
            raise UnsupportedController(
                "LoxPanel: Plugin-Daten sind vorhanden, aber die Steuerdatei fehlt. "
                "LoxPanel-Installation pruefen; automatische Koordination ist nicht bestaetigt.")
        return {"mode": "skip"}
    if inventory is None:
        inventory = docker_inventory()
    if not selected_loxpanel(targets, legacy, lambda: inventory):
        return {"mode": "skip"}
    profile = controller_profile(controller, home)
    identity = loxpanel_identity(inventory)
    return dict(profile, controller_path=controller_path, controller=controller, identity=identity)


def probe_lock(path):
    """Check an existing lock read-only; absent locks are not created by preflight."""
    parent = path.rsplit("/", 1)[0]
    directory = open_directory(parent)
    try:
        info = os.fstat(directory)
        probe_watchdog_access(parent, (info.st_dev, info.st_ino), directory=True)
    finally:
        os.close(directory)
    try:
        fd = open_regular(path)
    except FileNotFoundError:
        return
    try:
        info = os.fstat(fd)
        probe_watchdog_access(path, (info.st_dev, info.st_ino))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES):
                raise GuardError(
                    "LoxPanel fuehrt gerade einen eigenen Vorgang aus. Nach dessen Abschluss erneut pruefen.") from exc
            raise
    finally:
        os.close(fd)


def probe(home, targets_text, legacy):
    """Bounded JSON-safe public receipt; negative compatibility is not a crash."""
    try:
        profile = resolve_coordination(home, targets_text, legacy)
        mode = profile["mode"]
        if mode == "skip":
            details = "Keine ausgewaehlte installierte LoxPanel-Watchdog-Koordination erforderlich."
        elif mode == "manual-stop":
            guard = ManualStopGuard(profile["path"], profile["identity"])
            guard.close()
            details = ("LoxPanel ist in seiner eigenen Oberflaeche bewusst gestoppt. "
                       "Die Stopppause bleibt unveraendert; nach dem Backup dort wieder starten.")
        else:
            probe_lock(profile["path"])
            details = ("LoxPanel unterstuetzt die automatische Watchdog-Pause. "
                       "HostBackup prueft und haelt diese beim Backup; keine Updates oder manuellen Starts waehrenddessen.")
        if mode != "skip" and read_text(profile["controller_path"]) != profile["controller"]:
            raise GuardError("LoxPanel-Steuerdatei hat sich waehrend der Pruefung geaendert. Erneut pruefen.")
        return {"ok": True, "applicable": mode != "skip", "mode": mode, "details": details}
    except (GuardError, OSError, UnicodeError, ValueError) as exc:
        message = " ".join(str(exc).split())[:600]
        return {"ok": False, "applicable": True,
                "mode": "unsupported" if isinstance(exc, UnsupportedController) else "error",
                "details": message or "LoxPanel-Koordination konnte nicht geprueft werden."}


def close_inherited_descriptors():
    # In particular, do not retain the worker's operation/backup locks (8/9).
    for name in os.listdir("/proc/self/fd"):
        if name.isdigit() and int(name) > 2:
            try:
                os.close(int(name))
            except OSError:
                pass


def serve(guard, owner, controller_path, controller, ready="READY loxpanel"):
    print(ready, flush=True)
    pending = b""
    while owner.alive():
        ready, _, _ = select.select([0], [], [], 0.25)
        if not ready:
            continue
        chunk = os.read(0, 1024)
        if not chunk:
            return
        pending += chunk
        if len(pending) > 4096:
            raise GuardError("Invalid watchdog control message.")
        while b"\n" in pending:
            command, pending = pending.split(b"\n", 1)
            if command == b"CHECK":
                guard.check()
                if read_text(controller_path) != controller:
                    raise GuardError("LoxPanel controller changed during the backup; source consistency cannot be confirmed.")
                print("OK", flush=True)
            elif command == b"RELEASE":
                guard.close()
                print("RELEASED", flush=True)
                return
            else:
                raise GuardError("Invalid watchdog control message.")


def hold(home, owner_pid, targets_text, legacy):
    profile = resolve_coordination(home, targets_text, legacy)
    if profile["mode"] == "skip":
        print("SKIP", flush=True)
        return
    owner = Owner(owner_pid)
    # A group stop signal reaches both worker and helper. Keep the guard while
    # the worker's EXIT trap restarts services; owner identity/EOF is the lease.
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, signal.SIG_IGN)
    guard = (ManualStopGuard(profile["path"], profile["identity"])
             if profile["mode"] == "manual-stop" else LockGuard(profile["path"], owner))
    try:
        if not owner.alive():
            raise GuardError("Backup worker exited before watchdog coordination.")
        if profile["mode"] == "manual-stop":
            serve(guard, owner, profile["controller_path"], profile["controller"], "READY loxpanel manual-stop")
        else:
            serve(guard, owner, profile["controller_path"], profile["controller"])
    finally:
        guard.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("hold", "probe"))
    parser.add_argument("--home", required=True)
    parser.add_argument("--owner-pid", type=int)
    parser.add_argument("--targets", required=True, help="Selected targets as literal TYPE<TAB>NAME lines")
    parser.add_argument("--legacy", choices=("true", "false"), required=True)
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or fcntl is None:
            raise GuardError("Watchdog coordination requires Linux file locks.")
        close_inherited_descriptors()
        if args.action == "probe":
            print(json.dumps(probe(args.home, args.targets, args.legacy == "true"), ensure_ascii=True), flush=True)
            return 0
        if args.owner_pid is None:
            raise GuardError("Backup worker PID is required for watchdog coordination.")
        hold(args.home, args.owner_pid, args.targets, args.legacy == "true")
        return 0
    except (GuardError, OSError, UnicodeError, ValueError) as exc:
        message = " ".join(str(exc).split())[:600]
        try:
            if args.action == "probe":
                print(json.dumps({"ok": False, "applicable": True, "mode": "error", "details": message}), flush=True)
            else:
                print("ERROR " + message, flush=True)
        except BrokenPipeError:
            pass
        return 20


if __name__ == "__main__":
    sys.exit(main())
