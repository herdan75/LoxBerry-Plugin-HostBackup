#!/usr/bin/env python3
"""Versioned content policy for LoxBerry-managed volatile diagnostic payload.

This policy is applied while building the common, non-recursive source list,
not by ignoring rsync/TAR/repository errors afterwards. Directories, symlinks,
special files, installation audit trails and data outside the four explicitly
managed areas remain ordinary required sources. Callers must still verify the
frozen mount inventory after enumeration and copying.
"""

import os
from pathlib import Path, PurePosixPath
import re
import stat


POLICY_VERSION = 1
MAX_SAMPLE_PATHS = 20
REASON = ("Fluechtige LoxBerry-Diagnoseinhalte werden vor dem Kopieren ausgelassen; "
          "Verzeichnisse, Rechte und symbolische Links bleiben erhalten. "
          "Dauerhafte Installationsnachweise sind nicht betroffen.")
RUNTIME_SUFFIXES = (
    "/log/plugins", "/log/system_tmpfs",
    "/log/ramlog/log/plugins", "/log/ramlog/log/system_tmpfs",
)


def _canonical_absolute(value):
    return (isinstance(value, str) and value.startswith("/") and value != "/"
            and not value.startswith("//") and len(value) <= 4096
            and value == str(PurePosixPath(value))
            and not any(part in (".", "..") for part in value.split("/"))
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _beneath(path, parent):
    return path == parent or path.startswith(parent + "/")


def _is_zram_device(device):
    """Recognise a kernel zram device without trusting a mount source string."""
    if not isinstance(device, str) or not re.fullmatch(r"[0-9]+:[0-9]+", device):
        return False
    try:
        target = (Path("/sys/dev/block") / device).resolve(strict=True)
        return (target.parent == Path("/sys/devices/virtual/block")
                and re.fullmatch(r"zram[0-9]+", target.name) is not None)
    except (OSError, RuntimeError):
        return False


class RuntimePolicy:
    """Omit only payload proven to belong to a managed diagnostic directory.

    ``root`` in ``should_omit`` is a fixture seam, not a user-controlled backup
    root. ``entry`` must be the no-follow DirEntry from the source walker. Its
    regular-file observation may survive rotation between readdir and lstat;
    an unknown/missing entry is never accepted merely because of its pathname.
    """

    def __init__(self, loxberry_home="/opt/loxberry", include_runtime_logs=False,
                 mounts=(), overrides=None):
        if not _canonical_absolute(loxberry_home):
            raise ValueError("Ungueltiges LoxBerry-Home fuer die Laufzeitdaten-Regel.")
        if not isinstance(include_runtime_logs, bool):
            raise ValueError("include_runtime_logs muss true oder false sein.")
        self.home = loxberry_home
        self.include_runtime_logs = include_runtime_logs
        self.roots = tuple(loxberry_home + suffix for suffix in RUNTIME_SUFFIXES)
        self.mounts = tuple(dict(item) for item in mounts)
        # Official LoxBerry uses a RAM filesystem at log/ramlog and binds its
        # log/{plugins,system_tmpfs} subdirectories to the public log paths.
        # ext4 is allowed ONLY with kernel evidence that it is a zram device.
        self.ramlog = next((item for item in self.mounts if item.get("path") == self.home + "/log/ramlog"), None)
        if self.ramlog and (self.ramlog.get("root") != "/" or self.ramlog.get("stack")
                            or not re.fullmatch(r"[0-9]+:[0-9]+", self.ramlog.get("device", ""))
                            or not (self.ramlog.get("fstype") == "tmpfs"
                                    or self.ramlog.get("fstype") == "ext4" and _is_zram_device(self.ramlog.get("device")))):
            self.ramlog = None
        self.overrides = dict(overrides or {})
        for path, enabled in self.overrides.items():
            if not _canonical_absolute(path) or not isinstance(enabled, bool):
                raise ValueError("Ungueltige ausdrueckliche Quellenauswahl.")
        self._count = 0
        self._paths = []

    def _managed_root(self, logical):
        if self.include_runtime_logs or not _canonical_absolute(logical):
            return None
        managed = next((base for base in self.roots if logical.startswith(base + "/")), None)
        if managed is None:
            return None
        # An explicitly selected source inside a managed area is user intent,
        # not disposable diagnostic data. A broader selected disk, however,
        # still follows this documented content policy by default.
        if any(enabled and _beneath(path, managed) and _beneath(logical, path)
               for path, enabled in self.overrides.items()):
            return None
        return managed

    def _mounts_safe(self, logical):
        log_base = self.home + "/log"
        for item in self.mounts:
            target = item.get("path", "")
            if not isinstance(target, str) or not _beneath(target, log_base) or not _beneath(logical, target):
                continue
            if item.get("stack"):
                return False
            if target in self.roots and item.get("fstype") == "tmpfs" and item.get("root") == "/":
                continue
            if self.ramlog is not None:
                if target == self.ramlog["path"]:
                    continue
                front_roots = {self.home + "/log/plugins": "/log/plugins",
                               self.home + "/log/system_tmpfs": "/log/system_tmpfs"}
                if (target in front_roots and item.get("root") == front_roots[target]
                        and item.get("device") == self.ramlog["device"]
                        and item.get("fstype") == self.ramlog["fstype"]):
                    continue
            # No generic bind exemption: unrelated disk/share data at a log
            # path, nested mounts and unrecognised layouts stay required.
            return False
        return True

    def _parents_safe(self, physical, fixture_root):
        # Never classify data reached through an outward symlink, even if a
        # path spelling happens to look like the documented log hierarchy.
        try:
            relative = physical.parent.relative_to(fixture_root)
            current = fixture_root
            for part in (None, *relative.parts):
                if part is not None:
                    current = current / part
                info = current.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    return False
            return True
        except (OSError, ValueError):
            return False

    def _regular_payload(self, physical, fixture_root):
        # Production Linux traversal pins each verified parent with a directory
        # descriptor. A concurrent parent -> symlink swap cannot redirect this
        # classification into external data between two pathname lstat calls.
        if (os.name == "posix" and os.open in os.supports_dir_fd
                and os.stat in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")):
            descriptor = None
            try:
                relative = physical.parent.relative_to(fixture_root)
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                descriptor = os.open(fixture_root, flags)
                for part in relative.parts:
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = next_descriptor
                try:
                    info = os.stat(physical.name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    return True
                return stat.S_ISREG(info.st_mode)
            except (OSError, ValueError):
                return False
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        # Fixture portability; production Linux always uses the pinned path.
        if not self._parents_safe(physical, fixture_root):
            return False
        try:
            return stat.S_ISREG(physical.lstat().st_mode)
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def should_omit(self, logical, entry, root=Path("/")):
        """Return True only for an observed regular volatile diagnostic file.

        Failure to establish the type/path/ancestry means normal processing:
        the source walker will report any actual read error. No exception is
        swallowed into a successful backup here.
        """
        if self._managed_root(logical) is None or entry is None or not self._mounts_safe(logical):
            return False
        fixture_root = Path(root)
        physical = fixture_root / logical.lstrip("/")
        try:
            if Path(entry.path) != physical or not entry.is_file(follow_symlinks=False):
                return False
            if not self._regular_payload(physical, fixture_root):
                return False
        except (OSError, ValueError, AttributeError):
            return False
        self._count += 1
        if len(self._paths) < MAX_SAMPLE_PATHS:
            self._paths.append(logical)
        return True

    def report(self):
        """A bounded, self-contained description frozen into the backup."""
        return {
            "version": POLICY_VERSION,
            "enabled": not self.include_runtime_logs,
            "include_runtime_logs": self.include_runtime_logs,
            "loxberry_home": self.home,
            "managed_roots": list(self.roots),
            "omitted_regular_files": self._count,
            "sample_paths": list(self._paths),
            "samples_truncated": self._count > len(self._paths),
            "preserves": ["directories", "symlinks", "special_files", "persistent_install_audit"],
            "reason": REASON,
        }
