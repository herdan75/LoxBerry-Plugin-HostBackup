#!/usr/bin/env python3
"""Coordinate a selected LoxPanel container with its existing watchdog lock.

This helper never executes LoxPanel code, edits its configuration, or starts a
container. The parent worker remains responsible for immutable-ID recovery.
Protocol on stdout/stdin: SKIP (exit), READY loxpanel, CHECK -> OK,
RELEASE -> RELEASED (exit). Errors are one readable ERROR line and exit 20.
The parent must retain its control pipe through copying and service recovery.
EOF/owner death releases the kernel lock; no persistent stopped flag is left.
"""

import argparse
import errno
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


class GuardError(Exception):
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


def open_regular(path, create=False):
    """Open read-only without following links, blocking on FIFOs, or truncating."""
    absolute_path(path)
    parent, name = path.rsplit("/", 1)
    directory = open_directory(parent)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
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


def validate_controller(text, home):
    """Recognise the installed controller's narrow, existing lock contract.

    This is compatibility detection, not execution or a shell interpreter. A
    modified/older implementation must be reviewed instead of guessed safe.
    """
    absolute_path(home)
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
    match = re.search(r"(?:^|\n)_sperre\(\)\s*\{\s*\n(.*?)\n\}", code, re.S)
    expected = ('[ -e "$SPERRE" ] || : >"$SPERRE"',
                'exec 9<"$SPERRE" || return 2', 'flock -n 9 || return 1')
    body = tuple(line.strip() for line in match.group(1).splitlines()) if match else ()
    check = re.search(r"(?:^|\n)check\)\s*\n(.*?)\n;;", code, re.S)
    check_lines = check.group(1).splitlines() if check else []
    if check_lines and re.fullmatch(r'\[ -f "\$STOPPED" \] && exit 0(?:\s+#.*)?', check_lines[0]):
        check_lines = check_lines[1:]
    if (body != expected or len(check_lines) != 3 or check_lines[0] != "_sperre"
            or not re.fullmatch(r"\[ \$\? = 1 \] && \{[^\n]*exit 0; \}", check_lines[1])
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


def probe_watchdog_access(path, identity, timeout=2):
    """Prove actual read access, including parent traversal and ACL semantics.

    The child drops to the real non-root watchdog user, opens read-only, checks
    the locked inode and exits. It never imports/executes another plugin. Mode
    bits alone are insufficient (owner/group precedence and named ACLs matter).
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
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            info = os.fstat(fd)
            os.close(fd)
            os._exit(0 if stat.S_ISREG(info.st_mode) and info.st_nlink == 1
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


def close_inherited_descriptors():
    # In particular, do not retain the worker's operation/backup locks (8/9).
    for name in os.listdir("/proc/self/fd"):
        if name.isdigit() and int(name) > 2:
            try:
                os.close(int(name))
            except OSError:
                pass


def serve(guard, owner, controller_path, controller):
    print("READY loxpanel", flush=True)
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
    absolute_path(home)
    targets = parse_targets(targets_text)
    possible = (not targets and legacy) or any(
        kind == "docker" and (name == "loxpanel" or re.fullmatch(r"[a-f0-9]{12,64}", name))
        for kind, name in targets)
    if not possible:
        print("SKIP", flush=True)
        return
    # LoxPanel's own stop performs compose down, removing its container. A
    # saved selection (or the legacy all-Docker option) must not require an old
    # controller's lock protocol when no LoxPanel container remains. Only a
    # successful, validated full inventory establishes absence; daemon errors
    # must never be mistaken for a stopped/removed application.
    inventory = docker_inventory()
    if (not any(name == "loxpanel" for _, name in inventory)
            or not selected_loxpanel(targets, legacy, lambda: inventory)):
        print("SKIP", flush=True)
        return
    controller_path = home + CONTROLLER_SUFFIX
    try:
        controller = read_text(controller_path)
    except FileNotFoundError:
        print("SKIP", flush=True)
        return
    path = validate_controller(controller, home)
    owner = Owner(owner_pid)
    # A group stop signal reaches both worker and helper. Keep the guard while
    # the worker's EXIT trap restarts services; owner identity/EOF is the lease.
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, signal.SIG_IGN)
    guard = LockGuard(path, owner)
    try:
        serve(guard, owner, controller_path, controller)
    finally:
        guard.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("hold",))
    parser.add_argument("--home", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    parser.add_argument("--targets", required=True, help="Selected targets as literal TYPE<TAB>NAME lines")
    parser.add_argument("--legacy", choices=("true", "false"), required=True)
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or fcntl is None:
            raise GuardError("Watchdog coordination requires Linux file locks.")
        close_inherited_descriptors()
        hold(args.home, args.owner_pid, args.targets, args.legacy == "true")
        return 0
    except (GuardError, OSError, UnicodeError, ValueError) as exc:
        message = " ".join(str(exc).split())[:600]
        try:
            print("ERROR " + message, flush=True)
        except BrokenPipeError:
            pass
        return 20


if __name__ == "__main__":
    sys.exit(main())
