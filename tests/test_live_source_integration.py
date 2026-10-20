#!/usr/bin/env python3
"""Opt-in real Linux coverage for a frozen live-source backup plan.

Run as root on a disposable Linux CI host with HOSTBACKUP_LIVE_SOURCE_TEST=1
and HOSTBACKUP_RESTIC_BINARY pointing to the checksum-pinned Restic engine.
Requires GNU tar, rsync, ACL/capability tools and util-linux mount namespaces.
Every copied/restored/deleted file belongs to a new private temporary fixture.
Mount tests exec a separate private namespace and never mount a production NAS.
Missing tools or namespace capabilities are failures when explicitly enabled.
"""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    spec = importlib.util.spec_from_file_location(
        "hostbackup_live_" + name.replace("-", "_"), ROOT / "bin" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sources = helper("hostbackup-sources")
repository = helper("hostbackup-repository")


def command(argv, *, timeout=60, check=True):
    result = subprocess.run([str(item) for item in argv], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=timeout, check=False,
                            env={**os.environ, "LC_ALL": "C"})
    if check and result.returncode:
        raise AssertionError("Command failed (%s): %r\n%s\n%s" % (
            result.returncode, argv, result.stdout.decode(errors="replace")[-8000:],
            result.stderr.decode(errors="replace")[-8000:]))
    return result


class OptInLinuxCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("HOSTBACKUP_LIVE_SOURCE_TEST") != "1":
            raise unittest.SkipTest("Set HOSTBACKUP_LIVE_SOURCE_TEST=1 on disposable root Linux")
        if not sys.platform.startswith("linux") or os.geteuid() != 0:
            raise AssertionError("Live-source integration requires root Linux")
        required = ("tar", "rsync", "cp", "setfacl", "getfacl", "setcap", "getcap", "unshare", "mount", "umount")
        missing = [name for name in required if not shutil.which(name)]
        if missing:
            raise AssertionError("Live-source integration tools missing: " + ", ".join(missing))
        if b"GNU tar" not in command(["tar", "--version"]).stdout:
            raise AssertionError("GNU tar is required for the production archive flags")


class LiveSourceCopyIntegrationTests(OptInLinuxCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="hostbackup-live-source-")).resolve()
        self.mounted = []
        self.addCleanup(self.cleanup_fixture)
        self.base.chmod(0o700)
        self.source = self.base / "source"
        self.source.mkdir(mode=0o750)
        self.source.chmod(0o750)
        self.home = self.source / "opt/loxberry"
        self.runtime = self.home / "log/plugins/audioserver4home"
        self.ram_runtime = self.home / "log/ramlog/log/system_tmpfs"
        self.persistent = self.home / "data/plugins/audioserver4home"
        self.audit = self.home / "log/system/plugininstall.log"
        for directory in (self.runtime, self.ram_runtime, self.persistent, self.audit.parent):
            directory.mkdir(parents=True, exist_ok=True)
        self.runtime.chmod(0o750)
        os.chown(self.runtime, 1001, 1001)
        os.setxattr(self.runtime, "user.hostbackup-skeleton", b"retained-directory")
        command(["setfacl", "-m", "u:65534:r-x", self.runtime])
        self.runtime_log = self.runtime / "unrecognised-future-plugin-filename.log"
        self.runtime_log.write_bytes(b"rotating diagnostic data\n")
        (self.ram_runtime / "cleanup.log").write_bytes(b"rotating RAM log\n")
        self.audit.write_bytes(b"persistent installation audit\n")
        self.important = self.persistent / "database.log"
        self.important.write_bytes(b"persistent transaction data must not be omitted\n")
        self.important.chmod(0o640)
        os.chown(self.important, 1001, 1001)
        command(["setfacl", "-m", "u:65534:r--", self.important])
        os.setxattr(self.important, "user.hostbackup-data", b"important")
        self.hardlink = self.persistent / "database-hardlink"
        os.link(self.important, self.hardlink)
        self.link = self.runtime / "persistent-link"
        self.link.symlink_to(os.path.relpath(self.important, self.runtime))
        self.capability = self.persistent / "capability-fixture"
        self.capability.write_bytes(b"capability test fixture; never executed\n")
        self.capability.chmod(0o750)
        command(["setcap", "cap_net_bind_service=ep", self.capability])
        self.sparse = self.persistent / "sparse.data"
        with self.sparse.open("wb") as handle:
            handle.write(b"start")
            handle.seek(8 * 1024 * 1024)
            handle.write(b"end")
        # Large enough for concurrent mutations without wasting network bandwidth.
        self.payload = self.source / "000-payload.bin"
        self.payload.write_bytes(b"live-source-fixture\n" * (1024 * 1024))
        # These are ROOT-level names: rsync treats leading # and ; in an
        # unprefixed files-from list as comments even when --from0 is present.
        self.edge_files = {}
        for name in ("#file", ";file", "--option-looking", "--checkpoint-action=exec=false",
                     " leading and trailing whitespace ", "line\nbreak\tname"):
            path = self.source / name
            payload = b"required filename edge: " + os.fsencode(name) + b"\n"
            path.write_bytes(payload)
            path.chmod(0o640)
            self.edge_files[path] = payload
        self.file_list = self.base / "selection.nul"
        self.plan = None
        self.names = None
        self.fixture_mounts = [{"path": "/", "fstype": "ext4", "kind": "local", "mount_id": "fixture"}]
        if getattr(self, "ramlog_namespace_fixture", False):
            self.install_ramlog_fixture()

    def cleanup_fixture(self):
        failures = []
        for target in reversed(self.mounted):
            if command(["umount", "--", target], check=False).returncode:
                failures.append(str(target))
        if failures:
            # There is deliberately no TemporaryDirectory finalizer which
            # could recursively remove still-mounted data after this refusal.
            self.fail("Refusing mounted fixture cleanup: " + ", ".join(failures))
        if self.base.is_dir() and not self.base.is_symlink():
            shutil.rmtree(self.base)

    def install_ramlog_fixture(self):
        parent_namespace = os.environ.get("HOSTBACKUP_PARENT_MOUNT_NS")
        if not parent_namespace or os.readlink("/proc/self/ns/mnt") == parent_namespace:
            self.fail("Real Ramlog fixture requires a private mount namespace")
        command(["mount", "--make-rprivate", "/"])
        ramlog = self.home / "log/ramlog"
        seed = self.base / "ramlog-seed"
        shutil.copytree(ramlog, seed, symlinks=True)
        command(["mount", "-t", "tmpfs", "-o", "size=32m,nodev,nosuid", "hostbackup-live-ramlog", ramlog])
        self.mounted.append(ramlog)
        command(["cp", "-a", "--", str(seed) + "/.", ramlog])
        for name in ("plugins", "system_tmpfs"):
            front = self.home / "log" / name
            front.mkdir(exist_ok=True)
            backing = ramlog / "log" / name
            backing.mkdir(parents=True, exist_ok=True)
            command(["cp", "-a", "--", str(front) + "/.", backing])
            command(["mount", "--bind", backing, front])
            self.mounted.append(front)
        # Use real kernel mount IDs/devices/roots, translated only into the
        # fixture walker's logical root. No host-root enumeration takes place.
        actual_mounts = sources.read_mounts()
        enclosing = max((item for item in actual_mounts if sources.beneath(str(self.source), item["path"])),
                        key=lambda item: len(item["path"]))
        self.fixture_mounts = [{**enclosing, "path": "/"}]
        for item in actual_mounts:
            if item["path"].startswith(str(self.source) + "/"):
                relative = "/" + str(Path(item["path"]).relative_to(self.source))
                self.fixture_mounts.append({**item, "path": relative})
        self.assertEqual(len(self.fixture_mounts), 4)
        identities = {item["path"]: item for item in self.fixture_mounts}
        self.assertEqual(identities["/opt/loxberry/log/ramlog"]["root"], "/")
        self.assertEqual(identities["/opt/loxberry/log/plugins"]["root"], "/log/plugins")
        self.assertEqual(identities["/opt/loxberry/log/system_tmpfs"]["root"], "/log/system_tmpfs")

    def freeze(self, *, include_runtime_logs=False, enumerate_during_rotation=False):
        self.plan = sources.SourcePlan(
            {"policy": "legacy" if getattr(self, "ramlog_namespace_fixture", False) else "local", "overrides": {}},
            self.fixture_mounts,
            loxberry_home="/opt/loxberry", include_runtime_logs=include_runtime_logs)
        if enumerate_during_rotation:
            with self.rotating_logs():
                raw_names = list(sources.enumerate_files(self.plan, root=self.source))
        else:
            raw_names = list(sources.enumerate_files(self.plan, root=self.source))
        self.assertIn(".", raw_names)
        self.assertNotIn("./", raw_names)  # rsync would expand trailing-slash directories.
        self.assertTrue(all(name == "." or name.startswith("./") for name in raw_names), raw_names)
        self.names = [name[2:] if name.startswith("./") else name for name in raw_names]
        self.file_list.write_bytes(b"".join(os.fsencode(path) + b"\0" for path in raw_names))
        for path in self.edge_files:
            self.assertIn("./" + str(path.relative_to(self.source)), raw_names)
        self.assertIn(str(self.important.relative_to(self.source)), self.names)
        self.assertIn(str(self.audit.relative_to(self.source)), self.names)
        self.assertIn(str(self.runtime.relative_to(self.source)), self.names)
        self.assertIn(str(self.link.relative_to(self.source)), self.names)
        if not include_runtime_logs:
            self.assertNotIn(str(self.runtime_log.relative_to(self.source)), self.names)
            self.assertFalse(any(name.endswith("cleanup.log") for name in self.names))

    @contextlib.contextmanager
    def rotating_logs(self):
        """Only mutate known disposable fixture leaves, never directories/data."""
        stop = threading.Event()
        ready = threading.Event()
        errors = []
        iterations = []

        def rotate():
            try:
                index = 0
                while not stop.is_set():
                    for directory in (self.runtime, self.ram_runtime):
                        active = directory / "live-rotation.log"
                        rotated = directory / "live-rotation.log.1"
                        active.write_bytes(("cycle %d\n" % index).encode())
                        with active.open("ab") as handle:
                            handle.write(b"appended while backup runs\n")
                        active.replace(rotated)
                        rotated.unlink()
                    self.runtime_log.unlink(missing_ok=True)
                    self.runtime_log.write_bytes(b"new diagnostic generation\n")
                    iterations.append(index)
                    index += 1
                    ready.set()
                    stop.wait(0.002)
            except BaseException as exc:
                errors.append(exc)
                ready.set()

        worker = threading.Thread(target=rotate, name="fixture-log-rotation", daemon=True)
        worker.start()
        self.assertTrue(ready.wait(5), "Fixture rotator failed to start")
        try:
            yield iterations
        finally:
            stop.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), "Fixture rotator did not stop")
            if errors:
                raise errors[0]
            self.assertGreaterEqual(len(iterations), 1)

    def add_non_utf8_filename(self):
        path = self.source / os.fsdecode(b"raw-\xff-required-name")
        payload = b"required byte-name content\n"
        path.write_bytes(payload)
        self.edge_files[path] = payload

    def tar_backup(self, extra_options=()):
        archive = self.base / "rootfs.tar"
        result = command([
            "tar", "--format=pax", "--numeric-owner", "--acls", "--xattrs", "--xattrs-include=*",
            "--selinux", "--sparse", *extra_options, "-C", self.source, "-cpf", archive,
            "--no-recursion", "--null", "--verbatim-files-from", "--files-from=" + str(self.file_list),
        ], check=False)
        return result, archive

    def rsync_backup(self, name="rsync-backup", reference=None):
        destination = self.base / name
        destination.mkdir(mode=0o700)
        argv = ["rsync", "-aHAXS", "--numeric-ids", "--from0", "--files-from=" + str(self.file_list),
                "--no-recursive", "--dirs"]
        if reference is not None:
            argv += ["--link-dest=" + str(reference)]
        argv += ["--", str(self.source) + "/", str(destination) + "/"]
        return command(argv, check=False), destination

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(result.stderr, b"")

    def assert_restored(self, restored):
        """Check inventory and real metadata, not just an exit status."""
        expected = set(self.names)
        actual = {"."}
        for current, dirs, files in os.walk(restored, followlinks=False):
            actual.update(str((Path(current) / name).relative_to(restored)) for name in dirs + files)
        self.assertEqual(actual, expected)
        for original, payload in self.edge_files.items():
            self.assertEqual((restored / original.relative_to(self.source)).read_bytes(), payload)
        for original in (self.important, self.audit, self.capability, self.payload, self.sparse):
            target = restored / original.relative_to(self.source)
            self.assertEqual(target.read_bytes(), original.read_bytes())
        for original in (self.runtime, self.important, self.capability):
            target = restored / original.relative_to(self.source)
            info, saved = original.stat(), target.stat()
            self.assertEqual((saved.st_uid, saved.st_gid, stat.S_IMODE(saved.st_mode)),
                             (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)))
            self.assertEqual(command(["getfacl", "-cpn", target]).stdout,
                             command(["getfacl", "-cpn", original]).stdout)
            expected_xattrs = {key: os.getxattr(original, key) for key in os.listxattr(original)}
            actual_xattrs = {key: os.getxattr(target, key) for key in os.listxattr(target)}
            self.assertEqual(actual_xattrs, expected_xattrs)
        target_file = restored / self.important.relative_to(self.source)
        target_link = restored / self.hardlink.relative_to(self.source)
        self.assertEqual(target_file.stat().st_ino, target_link.stat().st_ino)
        self.assertEqual(os.readlink(restored / self.link.relative_to(self.source)), os.readlink(self.link))
        restored_sparse = restored / self.sparse.relative_to(self.source)
        self.assertLess(restored_sparse.stat().st_blocks * 512, restored_sparse.stat().st_size // 2)
        self.assertEqual(set((restored / self.runtime.relative_to(self.source)).iterdir()),
                         {restored / self.link.relative_to(self.source)})

    def test_gnu_tar_rotation_copy_and_metadata_restore(self):
        self.add_non_utf8_filename()
        self.freeze(enumerate_during_rotation=True)
        with self.rotating_logs():
            result, archive = self.tar_backup()
        self.assert_success(result)
        restored = self.base / "tar-restored"
        restored.mkdir(mode=0o700)
        self.assert_success(command([
            "tar", "--numeric-owner", "--same-owner", "--same-permissions", "--acls", "--xattrs",
            "--xattrs-include=*", "--selinux", "--sparse", "-C", restored, "-xpf", archive,
        ], check=False))
        self.assert_restored(restored)

    def test_rsync_rotation_copy_and_metadata_restore(self):
        self.add_non_utf8_filename()
        self.freeze(enumerate_during_rotation=True)
        with self.rotating_logs():
            result, destination = self.rsync_backup()
        self.assert_success(result)
        self.assert_restored(destination)

    def test_rsync_incremental_reuses_persistent_files_despite_log_rotation(self):
        self.freeze()
        result, first = self.rsync_backup("first")
        self.assert_success(result)
        with self.rotating_logs():
            self.freeze()
            result, second = self.rsync_backup("second", first)
        self.assert_success(result)
        self.assert_restored(second)
        for original in (self.important, self.payload, self.audit):
            relative = original.relative_to(self.source)
            self.assertEqual((first / relative).stat().st_ino, (second / relative).stat().st_ino)

    def test_rsync_incremental_changes_preserve_previous_data_mode_and_acl(self):
        self.freeze()
        result, first = self.rsync_backup("first")
        self.assert_success(result)
        relative = self.important.relative_to(self.source)
        first_file = first / relative
        first_content = first_file.read_bytes()
        first_mode = stat.S_IMODE(first_file.stat().st_mode)
        first_acl = command(["getfacl", "-cpn", first_file]).stdout
        first_xattrs = {key: os.getxattr(first_file, key) for key in os.listxattr(first_file)}
        self.important.write_bytes(b"new required persistent database content after first snapshot\n")
        self.important.chmod(0o600)
        command(["setfacl", "-m", "u:65534:rw-", self.important])
        self.freeze()
        with self.rotating_logs():
            result, second = self.rsync_backup("second", first)
        self.assert_success(result)
        self.assert_restored(second)
        self.assertNotEqual((second / relative).stat().st_ino, first_file.stat().st_ino)
        self.assertEqual(first_file.read_bytes(), first_content)
        self.assertEqual(stat.S_IMODE(first_file.stat().st_mode), first_mode)
        self.assertEqual(command(["getfacl", "-cpn", first_file]).stdout, first_acl)
        self.assertEqual({key: os.getxattr(first_file, key) for key in os.listxattr(first_file)}, first_xattrs)
        for unchanged in (self.payload, self.audit, *self.edge_files):
            name = unchanged.relative_to(self.source)
            self.assertEqual((first / name).stat().st_ino, (second / name).stat().st_ino)

    def test_gnu_tar_required_file_changed_during_read_is_not_accepted(self):
        # The first substantial regular file is 32 MiB. Checkpoint 1024 is at
        # 10 MiB of archive output, so the mutation happens during its read,
        # not before enumeration/open or after the file has been copied.
        changing = self.source / "000!-changing-required.data"
        changing.write_bytes(b"persistent-changing-data\n" * (1400 * 1024))
        marker = self.base / "checkpoint-mutation.json"
        script = self.base / "checkpoint-mutation.py"
        script.write_text(
            "import json, os, pathlib, sys\n"
            "target, marker = map(pathlib.Path, sys.argv[1:])\n"
            "if not marker.exists():\n"
            "    before = target.stat()\n"
            "    with target.open('ab') as handle:\n"
            "        handle.write(b'changed during required-data read\\n')\n"
            "        handle.flush()\n"
            "        os.fsync(handle.fileno())\n"
            "    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 3000000000))\n"
            "    marker.write_text(json.dumps({'checkpoint': os.environ.get('TAR_CHECKPOINT'), "
            "'before': before.st_size, 'after': target.stat().st_size}))\n",
            encoding="utf-8")
        self.freeze()
        prior = self.names[:self.names.index(changing.name)]
        self.assertLess(sum((self.source / name).stat().st_size for name in prior
                            if (self.source / name).is_file()), 1024 * 1024)
        action = "exec=" + " ".join(shlex.quote(str(path)) for path in (sys.executable, script, changing, marker))
        result, _ = self.tar_backup(("--checkpoint=1024", "--checkpoint-action=" + action))
        self.assertEqual(result.returncode, 1, result.stderr.decode(errors="replace"))
        self.assertIn(b"000!-changing-required.data", result.stderr)
        self.assertIn(b"file changed as we read it", result.stderr)
        mutation = json.loads(marker.read_text())
        self.assertEqual(mutation["checkpoint"], "1024")
        self.assertGreater(mutation["after"], mutation["before"])

    def test_gnu_tar_missing_persistent_data_is_not_accepted(self):
        self.freeze()
        self.important.unlink()
        result, _ = self.tar_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"database.log", result.stderr)

    def test_rsync_missing_persistent_data_is_not_accepted(self):
        self.freeze()
        self.important.unlink()
        result, _ = self.rsync_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"database.log", result.stderr)

    def test_runtime_opt_in_reinstates_strict_archive_errors(self):
        self.freeze(include_runtime_logs=True)
        self.assertIn(str(self.runtime_log.relative_to(self.source)), self.names)
        self.runtime_log.unlink()
        result, _ = self.tar_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"unrecognised-future-plugin-filename.log", result.stderr)

    def repository_fixture(self):
        engine = os.environ.get("HOSTBACKUP_RESTIC_BINARY")
        self.assertTrue(engine and Path(engine).is_file(), "Pinned HOSTBACKUP_RESTIC_BINARY is required")
        target = self.base / "repository-target"
        target.mkdir(mode=0o700)
        (target / repository.MARKER).write_text("isolated-live-source-fixture\n")
        state = self.base / "state"
        state.mkdir(mode=0o700)
        adapter = repository.Repository(target, state, engine=engine)
        adapter.initialize()
        key = adapter.export_key(self.base / "recovery-key.json")
        adapter.confirm_key(key["sha256"])
        return adapter

    def repository_commit(self, adapter, name):
        receipt = adapter.backup(name, self.file_list, "live-source-fixture", self.source)
        controls = self.base / ("controls-" + name)
        controls.mkdir(mode=0o700)
        (controls / "manifest.json").write_text(json.dumps({"backup_id": name, "status": "complete"}))
        (controls / "rsync-excludes.txt").write_text("")
        (controls / "source-selection.json").write_text(json.dumps(self.plan.report()))
        (controls / "backup-validation.json").write_text('{"status":"ok"}')
        candidate = adapter.state / ("candidate-" + name + ".json")
        committed = adapter.commit(name, candidate, controls)
        self.assertEqual(receipt["data_snapshot_id"], committed["data_snapshot_id"])
        return committed

    def test_repository_rotation_incremental_check_and_real_restore(self):
        self.freeze(enumerate_during_rotation=True)
        adapter = self.repository_fixture()
        with self.rotating_logs():
            first = self.repository_commit(adapter, "first")
            self.freeze()
            second = self.repository_commit(adapter, "second")
        self.assertEqual(second["summary"].get("files_new"), 0)
        self.assertEqual(second["summary"].get("files_changed"), 0)
        self.assertEqual(len(adapter.list_committed()), 2)
        adapter.check(read_data=True)
        destination = self.base / "repository-restored"
        destination.mkdir(mode=0o700)
        # Match existing real-repository tests: a disposable overlayfs CI tree
        # has Linux metadata, but production staging deliberately disallows it.
        original_identity = adapter.identity_reader
        if original_identity(destination)["fstype"] == "overlay":
            adapter.identity_reader = lambda path: (
                {"target": str(path), "source": "isolated-fixture", "fstype": "ext4"}
                if path == destination else original_identity(path))
        staged = adapter.stage(second["commit_id"], destination)
        self.assert_restored(Path(staged["rootfs"]) / str(self.source).lstrip("/"))
        self.assertTrue(first["commit_id"])

    def test_repository_missing_persistent_data_never_publishes_candidate(self):
        self.freeze()
        adapter = self.repository_fixture()
        self.important.unlink()
        with self.assertRaises((OSError, ValueError)):
            adapter.backup("missing", self.file_list, "live-source-fixture", self.source)
        self.assertEqual(adapter.list_committed(), [])
        self.assertFalse((adapter.state / "candidate-missing.json").exists())

    def test_repository_non_utf8_required_name_fails_explicitly_without_publication(self):
        # Repository manifests intentionally require lossless UTF-8 names.
        # Unlike tar/rsync, do not claim byte-name support or silently omit data.
        self.add_non_utf8_filename()
        self.freeze()
        adapter = self.repository_fixture()
        with self.assertRaisesRegex(repository.RepositoryError, "UTF-8"):
            adapter.backup("byte-name", self.file_list, "live-source-fixture", self.source)
        self.assertEqual(adapter.list_committed(), [])
        self.assertFalse((adapter.state / "candidate-byte-name.json").exists())


def mount_worker(scenario):
    """Runs only after unshare; namespace teardown is the final safety net."""
    if os.environ.get("HOSTBACKUP_LIVE_SOURCE_TEST") != "1" or os.geteuid() != 0:
        raise AssertionError("Mount worker requires explicit disposable root test")
    parent_namespace = os.environ.get("HOSTBACKUP_PARENT_MOUNT_NS")
    if not parent_namespace or os.readlink("/proc/self/ns/mnt") == parent_namespace:
        raise AssertionError("Refusing to mount in the parent's namespace")
    command(["mount", "--make-rprivate", "/"])
    fixture = Path(tempfile.mkdtemp(prefix="hostbackup-live-mount-")).resolve()
    mounted = []
    try:
        backing = fixture / "backing"
        replacement = fixture / "replacement"
        target = fixture / "volume"
        nested = target / "nested"
        for path in (backing, replacement, nested):
            path.mkdir(parents=True, exist_ok=True)
        (backing / "nested").mkdir()
        (backing / "content").write_text("selected data\n")
        (replacement / "content").write_text("different backing data\n")

        def mount(source, destination):
            command(["mount", "--bind", source, destination])
            mounted.append(destination)

        def unmount(destination):
            command(["umount", "--", destination])
            mounted.remove(destination)

        excluded = scenario.startswith("excluded-")
        mount(backing, target)
        if scenario == "selected-existing-file-directory-exclude":
            mount(replacement / "content", target / "content")
        peer = None
        if scenario == "selected-propagated-from-excluded-peer":
            # Shared propagation is created ONLY inside the private namespace.
            # A mount below an excluded alias must still fail if it propagates
            # onto a selected alias of the same backing tree.
            command(["mount", "--make-shared", target])
            peer = fixture / "excluded-peer"
            peer.mkdir()
            mount(target, peer)
        initial = sources.read_mounts()
        info = next(item for item in initial if item["path"] == str(target))
        if info["kind"] != "local":
            raise AssertionError("Mount fixture must reside on a local filesystem: " + str(info))
        selection = {"policy": "local", "overrides": {str(target): not excluded}}
        if peer is not None:
            selection["overrides"][str(peer)] = False
        directory_exclude_scenarios = {"selected-file-directory-exclude", "selected-existing-file-directory-exclude"}
        excludes = [str(target / "content") + "/"] if scenario in directory_exclude_scenarios else []
        plan = sources.SourcePlan(selection, initial, excludes=excludes)
        if plan.errors:
            raise AssertionError(plan.errors)
        if excludes and plan.excluded(str(target / "content"), False):
            raise AssertionError("A directory-only exclude incorrectly excluded required regular data")
        if scenario == "selected-existing-file-directory-exclude":
            if not plan.included(str(target / "content")):
                raise AssertionError("Existing required file bind was incorrectly omitted")
            # Translate only the two fixture mount paths for a real filesystem
            # walk rooted at target. The test must never enumerate host /.
            file_mount = next(item for item in initial if item["path"] == str(target / "content"))
            walk_plan = sources.SourcePlan({"policy": "local", "overrides": {}},
                                          [{**info, "path": "/"}, {**file_mount, "path": "/content"}],
                                          excludes=["/content/"])
            if "./content" not in list(sources.enumerate_files(walk_plan, root=target)):
                raise AssertionError("Directory-only exclude silently removed a real bound regular file")
        report = fixture / "selection.json"
        report.write_text(json.dumps(sources.verification_report(plan)))
        sources.verify_report(report)

        if scenario in {"excluded-unmount", "selected-unmount"}:
            unmount(target)
        elif scenario == "selected-replacement":
            unmount(target)
            mount(replacement, target)
        elif scenario in {"excluded-new-child", "selected-new-shadow"}:
            mount(replacement, nested)
        elif scenario in {"excluded-stacked", "selected-stacked"}:
            mount(replacement, target)
        elif scenario in {"selected-file-shadow", "selected-file-directory-exclude"}:
            mount(replacement / "content", target / "content")
        elif scenario == "selected-propagated-from-excluded-peer":
            mount(replacement, peer / "nested")
            propagated = [item for item in sources.read_mounts() if item["path"] == str(nested)]
            if not propagated:
                raise AssertionError("Fixture did not produce real shared-peer mount propagation")
            mounted.append(nested)
        elif scenario not in {"selected-unchanged", "selected-existing-file-directory-exclude"}:
            raise AssertionError("Unknown mount test scenario")

        if excluded or scenario in {"selected-unchanged", "selected-existing-file-directory-exclude"}:
            sources.verify_report(report)
            if excluded:
                if plan.included(str(target / "content")):
                    raise AssertionError("Frozen excluded volume became included")
        else:
            try:
                sources.verify_report(report)
            except sources.SourceError as exc:
                if str(target) not in str(exc):
                    raise AssertionError("Mount failure must identify the affected path: " + str(exc)) from exc
            else:
                raise AssertionError("Relevant source mount change was accepted: " + scenario)
    finally:
        # Break fixture-only shared peers before unmounting each recorded alias.
        # Otherwise unmount propagation could invalidate a later cleanup entry.
        command(["mount", "--make-rprivate", "/"])
        clean = True
        for destination in reversed(mounted):
            result = command(["umount", "--", destination], check=False)
            clean = clean and result.returncode == 0
        # Never recursively delete a fixture if one of its mounts remains.
        if clean and fixture.is_dir() and not fixture.is_symlink():
            shutil.rmtree(fixture)
        if not clean:
            raise AssertionError("Fixture unmount failed; left files for namespace teardown: " + str(fixture))


class LiveMountScopeIntegrationTests(OptInLinuxCase):
    def scenario(self, name):
        result = subprocess.run(
            ["unshare", "--mount", "--propagation", "private", sys.executable, str(Path(__file__).resolve()),
             "--mount-worker", name], stdin=subprocess.DEVNULL, capture_output=True, timeout=40,
            env={**os.environ, "LC_ALL": "C", "HOSTBACKUP_PARENT_MOUNT_NS": os.readlink("/proc/self/ns/mnt")},
            check=False)
        self.assertEqual(result.returncode, 0, "Mount namespace scenario %s failed:\n%s\n%s" % (
            name, result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace")))

    def test_excluded_volume_unmount_does_not_abort(self):
        self.scenario("excluded-unmount")

    def test_new_mount_below_excluded_volume_does_not_abort(self):
        self.scenario("excluded-new-child")

    def test_stacked_mount_below_excluded_volume_does_not_abort(self):
        self.scenario("excluded-stacked")

    def test_unchanged_selected_mount_passes(self):
        self.scenario("selected-unchanged")

    def test_selected_volume_unmount_is_rejected(self):
        self.scenario("selected-unmount")

    def test_selected_volume_replacement_is_rejected(self):
        self.scenario("selected-replacement")

    def test_new_mount_shadowing_selected_data_is_rejected(self):
        self.scenario("selected-new-shadow")

    def test_stacked_selected_mount_is_rejected(self):
        self.scenario("selected-stacked")

    def test_file_bind_shadowing_required_regular_file_is_rejected(self):
        self.scenario("selected-file-shadow")

    def test_directory_only_exclude_cannot_hide_file_bind_shadow(self):
        self.scenario("selected-file-directory-exclude")

    def test_existing_file_bind_is_not_omitted_by_directory_only_exclude(self):
        self.scenario("selected-existing-file-directory-exclude")

    def test_excluded_peer_propagating_over_selected_data_is_rejected(self):
        self.scenario("selected-propagated-from-excluded-peer")


class LiveRamlogCopyIntegrationTests(OptInLinuxCase):
    def ramlog_backend(self, backend):
        result = subprocess.run(
            ["unshare", "--mount", "--propagation", "private", sys.executable, str(Path(__file__).resolve()),
             "--ramlog-copy-worker", backend], stdin=subprocess.DEVNULL, capture_output=True, timeout=240,
            env={**os.environ, "LC_ALL": "C", "HOSTBACKUP_PARENT_MOUNT_NS": os.readlink("/proc/self/ns/mnt")},
            check=False)
        self.assertEqual(result.returncode, 0, "Real Ramlog %s roundtrip failed:\n%s\n%s" % (
            backend, result.stdout.decode(errors="replace")[-12000:], result.stderr.decode(errors="replace")[-12000:]))

    def test_gnu_tar_real_ramlog_and_paired_binds_roundtrip(self):
        self.ramlog_backend("tar")

    def test_rsync_real_ramlog_and_paired_binds_roundtrip(self):
        self.ramlog_backend("rsync")

    def test_repository_real_ramlog_and_paired_binds_roundtrip(self):
        self.ramlog_backend("repository")


def ramlog_copy_worker(backend):
    method = {"tar": "test_gnu_tar_rotation_copy_and_metadata_restore",
              "rsync": "test_rsync_rotation_copy_and_metadata_restore",
              "repository": "test_repository_rotation_incremental_check_and_real_restore"}[backend]
    case = LiveSourceCopyIntegrationTests(method)
    case.ramlog_namespace_fixture = True
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
    if not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--mount-worker":
        mount_worker(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--ramlog-copy-worker":
        ramlog_copy_worker(sys.argv[2])
    else:
        unittest.main(verbosity=2)
