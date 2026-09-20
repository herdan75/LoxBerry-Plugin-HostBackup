#!/usr/bin/env python3
"""Root installer operations anchored to no-follow directory descriptors.

Only the platform program copy is disposable during prepare. Recovery settings
live outside every platform purge tree until POSTROOT completed successfully.
"""
import fcntl
import hashlib
import json
import os
import pathlib
import pwd
import re
import stat
import subprocess
import sys

TRUST_ROOT = "/usr/libexec/loxberryhostbackup"
RECOVERY_BASE = "/var/lib/loxberryhostbackup-install-recovery"
OPERATION_LOCK_TEMPLATE = "/var/lock/{folder}.operation.lock"
PLATFORM_USER = "loxberry"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def fail(message):
    raise ValueError(message)


def canonical(path):
    if not isinstance(path, str) or not path.startswith("/") or os.path.normpath(path) != path:
        fail("Installer path must be absolute and canonical.")
    if any(ord(char) < 32 for char in path):
        fail("Control character in installer path.")
    return path


def trusted_fd(fd):
    info = os.fstat(fd)
    if info.st_uid != 0 or info.st_mode & 0o022:
        fail("Install recovery path must be root-owned and not group/world writable.")


def open_dir(path, create=False, trusted=False):
    """Open every component relative to its already pinned no-follow parent."""
    canonical(path)
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in pathlib.PurePosixPath(path).parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
            if trusted:
                trusted_fd(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def optional_dir(path):
    try:
        return open_dir(path)
    except FileNotFoundError:
        return None


def mount_id(fd):
    # Unlike st_dev, mount IDs distinguish same-device bind and file mounts.
    with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as source:
        for line in source:
            if line.startswith("mnt_id:"):
                return int(line.split()[1])
    fail("Cannot establish installer mount containment.")


def check_entries(directory_fd, expected_mount):
    if mount_id(directory_fd) != expected_mount:
        fail("Refusing mounted entry in plugin tree.")
    for name in os.listdir(directory_fd):
        entry = os.open(name, os.O_PATH | os.O_NOFOLLOW, dir_fd=directory_fd)
        try:
            if mount_id(entry) != expected_mount:
                fail("Refusing mounted entry in plugin tree.")
            if stat.S_ISDIR(os.fstat(entry).st_mode):
                child = os.open(".", DIR_FLAGS, dir_fd=entry)
                try:
                    check_entries(child, expected_mount)
                finally:
                    os.close(child)
        finally:
            os.close(entry)


def checked_tree(path):
    """Return the pinned parent; callers own the descriptor until operation end."""
    canonical(path)
    parent = optional_dir(str(pathlib.PurePosixPath(path).parent))
    if parent is None:
        return None
    name = pathlib.PurePosixPath(path).name
    try:
        try:
            child = os.open(name, DIR_FLAGS, dir_fd=parent)
        except FileNotFoundError:
            return parent
        try:
            check_entries(child, mount_id(parent))
        finally:
            os.close(child)
        return parent
    except BaseException:
        os.close(parent)
        raise


def remove_tree(path, parent_fd=None):
    own_parent = parent_fd is None
    if own_parent:
        parent_fd = checked_tree(path)
    if parent_fd is None:
        return
    try:
        # GNU rm does not follow replacement links. Its cwd is the pinned parent,
        # not a mutable absolute path. No privileged chown/chmod follows handoff.
        subprocess.run(["/bin/rm", "-rf", "--one-file-system", "--", pathlib.PurePosixPath(path).name],
                       cwd=f"/proc/self/fd/{parent_fd}", pass_fds=(parent_fd,), check=True)
    finally:
        if own_parent:
            os.close(parent_fd)


def read_config(directory_fd, name="config.json", allow_invalid=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            fail("Unsafe installer configuration file.")
        data = source.read(16 * 1024 * 1024 + 1)
    try:
        valid = len(data) <= 16 * 1024 * 1024 and isinstance(json.loads(data), dict)
    except (ValueError, UnicodeError):
        valid = False
    if not valid and allow_invalid:
        return None
    if not valid:
        fail("Invalid installer configuration.")
    return data


def atomic_config(directory_fd, data):
    name = f".install-config-{os.getpid()}"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, "config.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def protect_target(data, paths):
    if data is None:
        return
    target = json.loads(data).get("backup_root", "")
    if not isinstance(target, str):
        fail("Invalid configured backup target.")
    if target:
        target = os.path.realpath(target)
        for path in paths:
            if target == path or target.startswith(path + "/"):
                fail("Backup target is inside a plugin cleanup tree; move it safely before installing/uninstalling.")


def acquire_lock(folder):
    path = OPERATION_LOCK_TEMPLATE.format(folder=folder)
    # /var/lock is a platform-managed alias on Debian; pin its resolved directory.
    parent = open_dir(os.path.realpath(os.path.dirname(path)))
    try:
        info = os.fstat(parent)
        if info.st_uid != 0 or (info.st_mode & 0o002 and not info.st_mode & stat.S_ISVTX):
            fail("Unsafe operation lock directory.")
        fd = os.open(os.path.basename(path), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            fail("Unsafe operation lock file.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("HostBackup operation is active; finish it before installing/uninstalling.")
        return fd
    except BaseException:
        os.close(fd)
        raise


def main():
    if os.geteuid() != 0 or len(sys.argv) != 4:
        fail("Installer safety helper requires root, action, home and plugin folder.")
    action, home, folder = sys.argv[1:]
    canonical(home)
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", folder) or ".." in folder:
        fail("Unsafe plugin folder.")
    if action not in ("prepare", "restore", "complete", "uninstall"):
        fail("Unknown installer safety action.")
    bin_dir = f"{home}/bin/plugins/{folder}"
    config_dir = f"{home}/config/plugins/{folder}"
    data_dir = f"{home}/data/plugins/{folder}"
    state = f"/var/lib/{folder}" if home == "/opt/loxberry" else f"{data_dir}/root-state"
    key = hashlib.sha256((home + "\0" + folder).encode()).hexdigest()
    recovery_path = RECOVERY_BASE + "/" + key
    lock = acquire_lock(folder)
    descriptors = []
    try:
        recovery = open_dir(recovery_path, create=True, trusted=True)
        descriptors.append(recovery)
        saved = read_config(recovery)
        config = optional_dir(config_dir)
        if config is not None:
            descriptors.append(config)
        current = None
        if config is not None and action not in ("restore", "complete"):
            current = read_config(config, allow_invalid=(saved is not None and action == "prepare"))
        if action == "prepare":
            parent = checked_tree(bin_dir)
            if parent is not None:
                descriptors.append(parent)
            # Validate config mount containment even though only config.json is
            # replaced. A configured backup inside bin is never disposable.
            config_parent = checked_tree(config_dir)
            if config_parent is not None:
                descriptors.append(config_parent)
            protect_target(saved, [bin_dir])
            protect_target(current, [bin_dir])
            if saved is None and current is not None:
                atomic_config(recovery, current)
                saved = current
                print("Existing HostBackup configuration secured for installation recovery.")
            if config is not None:
                try:
                    os.unlink("config.json", dir_fd=config)
                    os.fsync(config)
                except FileNotFoundError:
                    pass
                # Only this single pinned directory inode is handed to LoxBerry;
                # no privileged traversal or file-inode mutation follows it.
                user = pwd.getpwnam(PLATFORM_USER)
                os.fchown(config, user.pw_uid, user.pw_gid)
                os.fchmod(config, 0o755)
            remove_tree(bin_dir, parent)
            print("Stale plugin program copy removed for unprivileged installation.")
        elif action == "restore":
            if config is None:
                config = open_dir(config_dir, create=True)
                descriptors.append(config)
            if saved is not None:
                atomic_config(config, saved)
                print("Existing HostBackup configuration restored from durable installation recovery.")
        elif action == "complete":
            if saved is not None:
                os.unlink("config.json", dir_fd=recovery)
                os.fsync(recovery)
        else:
            journals = optional_dir(state + "/restart-journals")
            if journals is not None:
                try:
                    if os.listdir(journals):
                        fail("HostBackup recovery journal is present; recover services before uninstalling.")
                finally:
                    os.close(journals)
            paths = [bin_dir, config_dir, data_dir, state, TRUST_ROOT]
            protect_target(saved, paths)
            protect_target(current, paths)
            parents = []
            for path in paths:
                parent = checked_tree(path)
                parents.append(parent)
                if parent is not None:
                    descriptors.append(parent)
            # Verify every deletion tree before removing any of them. Root state
            # is removed before its containing data tree on custom installations.
            for index in (0, 1, 3, 2, 4):
                remove_tree(paths[index], parents[index])
            if saved is not None:
                os.unlink("config.json", dir_fd=recovery)
                os.fsync(recovery)
            print("HostBackup program/state trees removed; external backups were not changed.")
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
        os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"HostBackup installer refused: {error}", file=sys.stderr)
        sys.exit(2)
