"""Offline engine provenance, architecture selection and optional package audit."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hostbackup_engine_test', ROOT / 'bin/hostbackup-engine.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class EngineTests(unittest.TestCase):
    def test_all_supported_architectures_have_fixed_sha256(self):
        self.assertEqual(set(engine.HASHES), {'amd64', 'arm', 'arm64'})
        for digest in engine.HASHES.values():
            self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_debian_userspace_architecture_overrides_kernel(self):
        for reported, expected in [('armhf', 'arm'), ('armel', 'arm'), ('amd64', 'amd64'), ('arm64', 'arm64')]:
            with self.subTest(reported=reported), mock.patch.object(engine.subprocess, 'check_output', return_value=reported), \
                    mock.patch.object(engine.platform, 'machine', return_value='aarch64'):
                self.assertEqual(engine.architecture(), expected)

    def test_no_dpkg_uses_known_linux_architecture(self):
        with mock.patch.object(engine.subprocess, 'check_output', side_effect=FileNotFoundError), \
                mock.patch.object(engine.platform, 'machine', return_value='x86_64'):
            self.assertEqual(engine.architecture(), 'amd64')

    def test_unsupported_architecture_fails_closed(self):
        with mock.patch.object(engine.subprocess, 'check_output', return_value='mips64'):
            with self.assertRaises((KeyError, ValueError)):
                engine.architecture()

    def test_existing_corrupt_cache_is_not_overwritten_or_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / engine.filename('amd64')
            target.write_bytes(b'not-an-engine')
            with mock.patch.object(engine.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    engine.fetch(directory)
            network.assert_not_called()
            self.assertEqual(target.read_bytes(), b'not-an-engine')

    def test_verified_cached_blobs_need_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            content = b'unit-test-only'
            with mock.patch.dict(engine.HASHES, {name: hashlib.sha256(content).hexdigest() for name in engine.HASHES}, clear=True):
                for name in engine.HASHES:
                    (Path(directory) / engine.filename(name)).write_bytes(content)
                with mock.patch.object(engine.urllib.request, 'urlopen') as network:
                    engine.fetch(directory)
                network.assert_not_called()

    def test_download_hash_mismatch_creates_no_binary(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(engine.urllib.request, 'urlopen') as network:
            network.return_value.__enter__.return_value.read.return_value = b'wrong-download'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                engine.fetch(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_built_zip_has_offline_engines_and_no_runtime_secrets(self):
        path = os.environ.get('HOSTBACKUP_PACKAGE_AUDIT')
        if not path:
            self.skipTest('Set HOSTBACKUP_PACKAGE_AUDIT to the locally built install ZIP.')
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for required in ('plugin.cfg', 'postroot.sh', 'bin/hostbackup-engine.py', 'bin/hostbackup-repository.py',
                             'bin/hostbackup-portable.py', 'docs/PORTABLE-REPOSITORY.md', 'docs/RESTIC-LICENSE.txt'):
                self.assertIn(required, names)
            for name in engine.HASHES:
                self.assertEqual(hashlib.sha256(archive.read(engine.filename(name))).hexdigest(), engine.HASHES[name])
            self.assertEqual(len(names), len(set(names)))
            self.assertFalse(any('__pycache__' in name or name.endswith(('.pyc', '.pyo')) for name in names))
            self.assertFalse(any('.portable-repository/' in name or '/repositories/' in name or 'password' in name for name in names))
            for name in names:
                self.assertFalse(name.startswith('/') or '..' in Path(name).parts)


if __name__ == '__main__':
    unittest.main()
