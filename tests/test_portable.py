#!/usr/bin/env python3
"""Portable bridge guards and opt-in, fixture-only Linux disaster recovery.

HOSTBACKUP_PORTABLE_RUNTIME must point at the installed trusted release directory.
HOSTBACKUP_REQUIRE_PORTABLE_INTEGRATION=1 makes an unavailable integration fail.
An optional HOSTBACKUP_PORTABLE_TEST_TARGET uses a fresh child on a NAS mount;
source, private state, staging and restored files stay on TMPDIR's Linux filesystem.
No test reads or restores the running host's system directories.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_bridge(directory):
    spec = importlib.util.spec_from_file_location('portable_bridge_test', Path(directory) / 'hostbackup-portable.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load_bridge(ROOT / 'bin')
SID = 'a' * 64
DATA_SID = 'b' * 64


def encoded(value):
    return base64.b64encode(json.dumps(value).encode()).decode('ascii')


class PortableBridgeUnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='portable-unit-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.base.chmod(0o700)
        self.target, self.state, self.controls = [self.base / name for name in ('target', 'state', 'controls')]
        for path in (self.target, self.state, self.controls):
            path.mkdir(mode=0o700)
        self.repo = mock.Mock()
        self.repo.root = self.target
        self.repo.state_base = self.state / 'repositories'
        self.repo.state = self.state
        self.repo.descriptor = self.state / 'repository.json'
        self.repo.load.return_value = {'repository_id': SID, 'host_id': 'host-1'}
        self.repo.status.return_value = {'repository_id': SID, 'host_id': 'host-1',
                                       'key_confirmed': True, 'engine_version': bridge.repository.VERSION,
                                       'password': 'DO-NOT-EXPOSE', 'password_file': '/private/key'}

    def private_json(self, path, value):
        bridge.repository.atomic_write(path, bridge.repository.encode(value))

    def controls_for_publish(self):
        self.private_json(self.state / 'candidate.json', {'backup_id': 'backup-1'})
        self.private_json(self.controls / 'manifest.json', {'backup_id': 'backup-1', 'status': 'validating'})
        self.private_json(self.controls / 'backup-validation.json', {'status': 'ok'})
        self.private_json(self.controls / 'source-selection.json', {'volumes': []})
        bridge.repository.atomic_write(self.controls / 'rsync-excludes.txt', b'/excluded\n')
        return self.state / 'candidate.json'

    def commit_record(self, architecture=None):
        return {'format': bridge.repository.FORMAT, 'repository_id': SID, 'backup_id': 'backup-1',
                'commit_id': SID, 'commit_snapshot_id': SID, 'data_snapshot_id': DATA_SID,
                'controls': {'manifest.json': encoded({'backup_id': 'backup-1', 'status': 'complete',
                             'host': {'architecture': architecture or platform.machine()}})}}

    def fake_recovery(self):
        return SimpleNamespace(checked_directory=lambda value: Path(value), secure_destination=mock.Mock(),
                               build_plan=mock.Mock(), run_restore=mock.Mock())

    def test_status_without_repository_does_not_create_state(self):
        with mock.patch.object(bridge.repository, 'trusted_engine', return_value=Path('/trusted/restic')), \
                mock.patch.object(bridge, 'adapter') as adapter:
            result = bridge.read_only_status(self.target, self.state)
        self.assertTrue(result['available'])
        self.assertFalse(result['initialized'])
        self.assertFalse((self.state / 'repositories').exists())
        adapter.assert_not_called()

    def test_status_without_engine_is_read_only_and_unavailable(self):
        with mock.patch.object(bridge.repository, 'trusted_engine', side_effect=ValueError('not installed')), \
                mock.patch.object(bridge, 'adapter') as adapter:
            result = bridge.read_only_status(self.target, self.state)
        self.assertFalse(result['available'])
        self.assertFalse((self.state / 'repositories').exists())
        adapter.assert_not_called()

    def test_public_status_never_forwards_secrets(self):
        self.repo.descriptor.touch()
        result = bridge.public_status(self.repo)
        serialized = json.dumps(result)
        self.assertTrue(result['initialized'])
        for secret in ('DO-NOT-EXPOSE', '/private/key', 'password', 'host_id'):
            self.assertNotIn(secret, serialized)

    def test_export_receipt_is_bound_to_exported_repository(self):
        bundle = {'password': 'a-private-passphrase', 'repository_id': SID}
        content = bridge.repository.encode(bundle)

        def export(path):
            bridge.repository.atomic_write(path, content, exclusive=True)
            return {'output': str(path), 'sha256': hashlib.sha256(content).hexdigest()}

        self.repo.export_key.side_effect = export
        output = io.BytesIO()
        with mock.patch.object(bridge.sys, 'stdout', SimpleNamespace(buffer=output)):
            bridge.export_key(self.repo)
        self.assertEqual(json.loads(output.getvalue()), bundle)
        receipt = json.loads((self.state / 'export-receipt.json').read_bytes())
        self.assertEqual(receipt, {'repository_id': SID, 'sha256': hashlib.sha256(content).hexdigest()})
        self.assertNotIn('a-private-passphrase', json.dumps(receipt))
        self.assertFalse(any(path.name.startswith('key-export-') for path in self.state.iterdir()))
        bridge.confirm_key(self.repo)
        self.repo.confirm_key.assert_called_once_with(receipt['sha256'])

    def test_key_confirmation_rejects_receipt_for_other_repository(self):
        self.private_json(self.state / 'export-receipt.json', {'repository_id': 'c' * 64, 'sha256': 'd' * 64})
        with self.assertRaisesRegex(ValueError, 'herunterladen'):
            bridge.confirm_key(self.repo)
        self.repo.confirm_key.assert_not_called()

    def test_publish_marks_target_complete_only_after_authenticated_commit(self):
        candidate = self.controls_for_publish()

        def commit(backup_id, path, private):
            self.assertEqual(backup_id, 'backup-1')
            self.assertEqual(path, candidate)
            self.assertEqual(json.loads((self.controls / 'manifest.json').read_bytes())['status'], 'validating')
            self.assertFalse((self.controls / 'repository-reference.json').exists())
            manifest = json.loads((private / 'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'complete')
            record = self.commit_record()
            record['controls']['manifest.json'] = encoded(manifest)
            return record

        self.repo.commit.side_effect = commit
        result = bridge.publish(self.repo, candidate, self.controls)
        self.assertEqual(result['commit_id'], SID)
        self.assertEqual(json.loads((self.controls / 'manifest.json').read_bytes())['status'], 'complete')
        self.assertEqual(json.loads((self.controls / 'repository-reference.json').read_bytes()), result)
        self.assertFalse(any(path.name.startswith('.committed-manifest-') for path in self.controls.iterdir()))

    def test_failed_commit_leaves_manifest_incomplete_and_unpublished(self):
        candidate = self.controls_for_publish()
        self.repo.commit.side_effect = ValueError('commit interrupted')
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            bridge.publish(self.repo, candidate, self.controls)
        self.assertEqual(json.loads((self.controls / 'manifest.json').read_bytes())['status'], 'validating')
        self.assertFalse((self.controls / 'repository-reference.json').exists())

    def test_nas_wrapper_controls_cannot_override_private_controls(self):
        candidate = self.controls_for_publish()
        (self.target / 'rsync-excludes.txt').write_bytes(b'ATTACKER-CHANGED-EXCLUSIONS\n')
        def commit(backup_id, path, private):
            self.assertEqual((private / 'rsync-excludes.txt').read_bytes(), b'/excluded\n')
            result = self.commit_record()
            result['controls']['rsync-excludes.txt'] = base64.b64encode((private / 'rsync-excludes.txt').read_bytes()).decode()
            return result
        self.repo.commit.side_effect = commit
        bridge.publish(self.repo, candidate, self.controls, self.target)
        self.assertEqual((self.target / 'rsync-excludes.txt').read_bytes(), b'/excluded\n')
        self.assertEqual(json.loads((self.controls / 'manifest.json').read_bytes())['status'], 'validating')

    def test_validation_requires_system_payload_and_normalizes_fixture_prefix(self):
        for include_loxberry in (False, True):
            with self.subTest(include_loxberry=include_loxberry):
                inventory = {'/fixture': 'dir', '/fixture/etc/config': 'file'}
                if include_loxberry:
                    inventory['/fixture/opt/loxberry/config'] = 'file'
                candidate = {'backup_id': 'backup-1', 'repository_id': SID, 'data_snapshot_id': DATA_SID,
                             'inventory_sha256': bridge.repository.digest(inventory), 'source_root': '/fixture',
                             'summary': {'total_bytes_processed': 64}}
                path = self.state / 'candidate-backup-1.json'
                self.private_json(path, candidate)
                self.repo.inventory.return_value = inventory
                if not include_loxberry:
                    with self.assertRaisesRegex(ValueError, 'Systeminhalt'):
                        bridge.candidate_validation(self.repo, path, self.controls, 1, 1)
                    self.assertFalse((self.controls / 'backup-validation.json').exists())
                else:
                    result = bridge.candidate_validation(self.repo, path, self.controls, 1, 1)
                    self.assertEqual(result['status'], 'ok')
                    self.assertEqual(result['files_count'], 2)

    def test_validation_rejects_changed_private_receipt(self):
        candidate = {'backup_id': 'backup-1', 'repository_id': SID}
        self.private_json(self.state / 'candidate-backup-1.json', candidate)
        self.private_json(self.state / 'untrusted.json', {**candidate, 'extra': 'tampered'})
        with self.assertRaisesRegex(ValueError, 'Kopierbeleg'):
            bridge.candidate_validation(self.repo, self.state / 'untrusted.json', self.controls, 1, 1)
        self.repo.inventory.assert_not_called()

    def test_skipped_metadata_capabilities_do_not_count_as_verified(self):
        report = {'status': 'ok', 'message': 'capability test skipped', 'checks': [
            {'id': name, 'status': 'ok'} for name in ('uid', 'gid', 'permissions', 'symlink', 'hardlink',
                                                     'sparse-allocation', 'acl-values', 'xattr-values')]}
        with mock.patch.object(bridge.metadata, 'execute_probe', return_value=report):
            with self.assertRaisesRegex(ValueError, 'Metadaten'):
                bridge.verify_local_metadata(self.target, self.state)

    def test_executing_restore_requires_explicit_offline_environment(self):
        recovery = self.fake_recovery()
        with mock.patch.object(bridge, 'sibling', return_value=recovery), \
                mock.patch.dict(os.environ, {'HOSTBACKUP_OFFLINE_RESTORE': ''}), \
                mock.patch.object(bridge, 'stage_backup') as stage:
            with self.assertRaisesRegex(ValueError, 'offline'):
                bridge.recover(self.repo, 'backup-1', str(self.base / 'stage'), str(self.base / 'restore'), [], True)
        stage.assert_not_called()
        self.repo.list_committed.assert_not_called()
        recovery.run_restore.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'POSIX root path guard')
    def test_running_root_is_never_a_restore_destination(self):
        with mock.patch.object(bridge, 'sibling', return_value=self.fake_recovery()), \
                mock.patch.object(bridge, 'stage_backup') as stage:
            with self.assertRaisesRegex(ValueError, 'laufende'):
                bridge.recover(self.repo, 'backup-1', '/fixture/stage', '/', [], False)
        stage.assert_not_called()

    def test_architecture_mismatch_blocks_before_staging(self):
        self.repo.list_committed.return_value = [self.commit_record('definitely-other-architecture')]
        with mock.patch.object(bridge, 'sibling', return_value=self.fake_recovery()), \
                mock.patch.object(bridge, 'stage_backup') as stage:
            with self.assertRaisesRegex(ValueError, 'Architektur'):
                bridge.recover(self.repo, 'backup-1', str(self.base / 'stage'), str(self.base / 'restore'), [], False)
        stage.assert_not_called()

    def test_destination_must_not_overlap_repo_state_or_staging(self):
        self.repo.list_committed.return_value = [self.commit_record()]
        staging = self.base / 'stage'
        for destination in (self.target, self.target / 'child', self.state, staging, staging / 'child', self.base):
            with self.subTest(destination=str(destination)), \
                    mock.patch.object(bridge, 'sibling', return_value=self.fake_recovery()), \
                    mock.patch.object(bridge, 'stage_backup') as stage:
                with self.assertRaisesRegex(ValueError, 'getrennt'):
                    bridge.recover(self.repo, 'backup-1', str(staging), str(destination), [], False)
                stage.assert_not_called()

    def test_unsuitable_mapped_volume_blocks_before_any_system_restore(self):
        self.repo.list_committed.return_value = [self.commit_record()]
        recovery = self.fake_recovery()
        recovery.build_plan.return_value = {'volumes': [{'destination': str(self.base / 'mapped-volume')}]}
        with mock.patch.object(bridge, 'sibling', return_value=recovery), \
                mock.patch.object(bridge, 'stage_backup', return_value={'backup': str(self.base / 'stage/backup-1'), 'backup_root': str(self.base / 'stage')}), \
                mock.patch.object(bridge, 'verify_local_metadata', side_effect=ValueError('mapped metadata unsupported')), \
                mock.patch.dict(os.environ, {'HOSTBACKUP_OFFLINE_RESTORE': '1'}), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'mapped metadata'):
                bridge.recover(self.repo, 'backup-1', str(self.base / 'stage'), str(self.base / 'restore'), [], True)
        recovery.run_restore.assert_not_called()

    def test_all_mapped_targets_are_checked_before_restore(self):
        self.repo.list_committed.return_value = [self.commit_record()]
        recovery = self.fake_recovery()
        target = self.base / 'restore'
        volume = self.base / 'mapped-volume'
        recovery.build_plan.return_value = {'volumes': [{'destination': str(volume)}]}
        with mock.patch.object(bridge, 'sibling', return_value=recovery), \
                mock.patch.object(bridge, 'stage_backup', return_value={'backup': str(self.base / 'stage/backup-1'), 'backup_root': str(self.base / 'stage')}), \
                mock.patch.object(bridge, 'verify_local_metadata') as verify, \
                mock.patch.dict(os.environ, {'HOSTBACKUP_OFFLINE_RESTORE': '1'}), \
                contextlib.redirect_stdout(io.StringIO()):
            def restore(*args, **kwargs):
                self.assertEqual({call.args[0] for call in verify.call_args_list}, {target, volume})
            recovery.run_restore.side_effect = restore
            bridge.recover(self.repo, 'backup-1', str(self.base / 'stage'), str(target), [], True)
        recovery.run_restore.assert_called_once()


class PortableLinuxRecoveryTests(unittest.TestCase):
    def test_external_key_recovers_fixture_after_original_host_state_is_gone(self):
        runtime = os.environ.get('HOSTBACKUP_PORTABLE_RUNTIME')
        available = os.name == 'posix' and os.geteuid() == 0 and runtime
        if not available:
            message = 'Requires root Linux and HOSTBACKUP_PORTABLE_RUNTIME pointing to a trusted release.'
            if os.environ.get('HOSTBACKUP_REQUIRE_PORTABLE_INTEGRATION') == '1':
                self.fail(message)
            self.skipTest(message)
        portable = load_bridge(runtime)
        portable.repository.trusted_engine()
        for command in ('rsync', 'getfacl', 'setfacl', 'getfattr', 'setfattr', 'getcap', 'setcap'):
            self.assertIsNotNone(shutil.which(command), 'Missing required Linux metadata tool: ' + command)
        with tempfile.TemporaryDirectory(prefix='portable-recovery-e2e-') as directory:
            base = Path(directory).resolve()
            base.chmod(0o700)
            source, state, staging, restored = [base / name for name in ('source', 'state', 'stage', 'restored')]
            for path in (source, state, staging, restored):
                path.mkdir(mode=0o700)
            # A fresh child is the only data written on a supplied NAS test mount.
            with tempfile.TemporaryDirectory(prefix='portable-target-e2e-',
                                             dir=os.environ.get('HOSTBACKUP_PORTABLE_TEST_TARGET') or base) as target_dir:
                target = Path(target_dir).resolve()
                (target / portable.repository.MARKER).write_bytes(b'fixture-registered-target\n')
                for path in ('etc', 'opt/loxberry', 'var/lib'):
                    (source / path).mkdir(parents=True, exist_ok=True)
                (source / 'etc/fixture.conf').write_bytes(b'configuration from authenticated backup\n')
                (source / 'opt/loxberry/fixture.conf').write_bytes(b'loxberry fixture only\n')
                (source / 'var/lib/fixture.data').write_bytes(b'fixture application data\n')
                (source / 'excluded.txt').write_bytes(b'THIS MUST NOT BE COPIED\n')
                preparation = portable.metadata.Probe('native-strict')
                enabled = portable.metadata.prepare_source(preparation, source)
                self.assertTrue(all(enabled.values()), enabled)
                self.assertEqual(preparation.result()['status'], 'ok', preparation.result())
                os.mkfifo(source / 'fifo', 0o640)
                os.setxattr(source, 'user.hostbackup-root', b'fixture-root-attributes')
                paths = ['.']
                for current, names, files in os.walk(source):
                    for name in sorted(names + files):
                        relative = (Path(current) / name).relative_to(source)
                        if str(relative) != 'excluded.txt':
                            paths.append(str(relative))
                file_list = base / 'selection.nul'
                file_list.write_bytes(b'\0'.join(os.fsencode(path) for path in paths) + b'\0')

                repo = portable.adapter(target, state)
                repo.initialize()
                output = io.BytesIO()
                with mock.patch.object(portable.sys, 'stdout', SimpleNamespace(buffer=output)):
                    portable.export_key(repo)
                recovery_key = base / 'externally-saved-recovery.json'
                portable.repository.atomic_write(recovery_key, output.getvalue(), exclusive=True)
                key_bundle = json.loads(output.getvalue())
                self.assertTrue(portable.confirm_key(repo)['key_confirmed'])
                public = json.dumps(portable.public_status(repo))
                self.assertNotIn(key_bundle['password'], public)
                self.assertNotIn('password', public)

                candidate = repo.backup('fixture-1', file_list, 'fixture-system', source)
                candidate_path = repo.state / 'candidate-fixture-1.json'
                controls = state / 'private-controls'
                controls.mkdir(mode=0o700)
                wrapper = target / 'fixture-1'
                wrapper.mkdir()
                manifest = {'schema_version': 2, 'backup_id': 'fixture-1', 'status': 'validating',
                            'size_bytes': candidate['summary']['total_bytes_processed'],
                            'host': {'architecture': platform.machine()},
                            'backup': {'mode': 'snapshot', 'storage_format': 'portable-repository'},
                            'metadata': {'mode': 'portable-archive'}}
                portable.write_control(controls, 'manifest.json', manifest)
                portable.write_control(controls, 'source-selection.json', {'volumes': [{'path': '/', 'included': True}]})
                portable.repository.atomic_write(controls / 'rsync-excludes.txt', b'/excluded.txt\n')
                portable.repository.atomic_write(controls / 'package-list.txt', b'fixture-package\n')
                portable.repository.atomic_write(controls / 'systemd-services.txt', b'fixture.service\n')
                validation = portable.candidate_validation(repo, candidate_path, controls, 1, 1)
                self.assertEqual(validation['status'], 'ok', validation)
                self.assertEqual(json.loads((controls / 'manifest.json').read_bytes())['status'], 'validating')
                reference = portable.publish(repo, candidate_path, controls, wrapper)
                self.assertEqual(json.loads((wrapper / 'manifest.json').read_bytes())['status'], 'complete')
                self.assertEqual(reference['data_snapshot_id'], candidate['data_snapshot_id'])
                repo.check(read_data=True)

                # Make both old source pathname and old key-state pathname unavailable.
                # Neither can be the recovery source; only NAS + exported key remain.
                unavailable_source = base / 'old-source-unavailable'
                source.rename(unavailable_source)
                (unavailable_source / 'etc/fixture.conf').write_bytes(b'changed AFTER backup\n')
                lost_state = base / 'old-host-state-unavailable'
                state.rename(lost_state)
                self.assertFalse(state.exists())
                self.assertFalse(source.exists())
                new_state = base / 'new-host-state'
                new_state.mkdir(mode=0o700)
                recovered_repo = portable.adapter(target, new_state)
                recovered_repo.attach(recovery_key)
                self.assertEqual(recovered_repo.status()['repository_id'], reference['repository_id'])
                self.assertTrue(recovered_repo.password.is_file())
                self.assertNotEqual(recovered_repo.password, repo.password)
                with mock.patch.object(repo, 'load', side_effect=AssertionError('Old host state must not be used')), \
                        mock.patch.dict(os.environ, {'HOSTBACKUP_OFFLINE_RESTORE': '1'}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    result = portable.recover(recovered_repo, 'fixture-1', str(staging), str(restored), [], execute=True)
                self.assertEqual(result['status'], 'restored', result)
                for name in ('package-list.txt', 'systemd-services.txt'):
                    self.assertEqual((Path(result['stage']) / name).read_bytes(), (lost_state / 'private-controls' / name).read_bytes())
                self.assertEqual((restored / 'etc/fixture.conf').read_bytes(), b'configuration from authenticated backup\n')
                self.assertEqual((restored / 'opt/loxberry/fixture.conf').read_bytes(), b'loxberry fixture only\n')
                self.assertEqual((restored / 'var/lib/fixture.data').read_bytes(), b'fixture application data\n')
                self.assertFalse((restored / 'excluded.txt').exists())
                self.assertFalse(state.exists())
                self.assertFalse(source.exists())
                comparison = portable.metadata.Probe('native-strict')
                portable.metadata.compare_restored(comparison, unavailable_source, restored, enabled)
                self.assertEqual(comparison.result()['status'], 'ok', comparison.result())
                self.assertTrue(stat.S_ISFIFO((restored / 'fifo').lstat().st_mode))
                self.assertEqual(os.getxattr(restored, 'user.hostbackup-root'), b'fixture-root-attributes')
                self.assertEqual(stat.S_IMODE(restored.stat().st_mode), stat.S_IMODE(unavailable_source.stat().st_mode))


if __name__ == '__main__':
    unittest.main()
