#!/usr/bin/env python3
"""Plugin integration for authenticated portable repositories (trusted root only)."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tempfile


def sibling(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repository = sibling('hostbackup-repository')
metadata = sibling('hostbackup-metadata')


def adapter(root, state):
    repository.secure_dir(state, private=True)
    directory = Path(state) / 'repositories'
    directory.mkdir(mode=0o700, exist_ok=True)
    return repository.Repository(root, directory)


def write_control(directory, name, value):
    """NAS controls can have fixed modes: no trust is derived from these modes."""
    directory = repository.secure_dir(directory)
    path = directory / name
    if path.exists() or path.is_symlink():
        raise ValueError('Kontrolldatei existiert bereits: ' + name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(repository.encode(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def public_status(repo):
    if not repo.descriptor.exists():
        return {'initialized': False, 'key_confirmed': False, 'key_exported': False,
                'available': True, 'engine_version': repository.VERSION,
                'message': 'Repository einrichten und Wiederherstellungsschluessel extern sichern.'}
    data = repo.status()
    return {'initialized': True, 'available': True, 'key_exported': (repo.state / 'export-receipt.json').is_file(),
            'key_confirmed': data['key_confirmed'], 'repository_id': data['repository_id'],
            'engine_version': data['engine_version'], 'message': 'Repository ist an dieses Backup-Ziel gebunden.'}


def read_only_status(root, state):
    repository.secure_dir(root)
    repository.secure_dir(state, private=True)
    try:
        repository.trusted_engine()
    except (OSError, ValueError):
        return {'available': False, 'initialized': False, 'key_confirmed': False, 'key_exported': False,
                'message': 'Die gepruefte portable Laufzeit ist nicht installiert.'}
    directory = Path(state) / 'repositories' / hashlib.sha256(os.fsencode(str(root))).hexdigest()
    if not (directory / 'repository.json').exists():
        return {'available': True, 'initialized': False, 'key_confirmed': False, 'key_exported': False,
                'engine_version': repository.VERSION, 'message': 'Repository noch nicht eingerichtet.'}
    return public_status(adapter(root, state))


def export_key(repo):
    with tempfile.TemporaryDirectory(prefix='key-export-', dir=repo.state) as directory:
        result = repo.export_key(Path(directory) / 'recovery.json')
        content = repository.read_bytes(Path(result['output']), private=True)
        repository.atomic_write(repo.state / 'export-receipt.json', repository.encode({
            'sha256': result['sha256'], 'repository_id': repo.load()['repository_id']}))
        # Only the dedicated no-store attachment endpoint receives this output.
        sys.stdout.buffer.write(content)


def confirm_key(repo):
    receipt = json.loads(repository.read_bytes(repo.state / 'export-receipt.json', private=True))
    if receipt['repository_id'] != repo.load()['repository_id']:
        raise ValueError('Zuerst den aktuellen Wiederherstellungsschluessel herunterladen.')
    repo.confirm_key(receipt['sha256'])
    return public_status(repo)


def probe(root, state):
    """Real disposable target roundtrip; never write into the production repo."""
    result = metadata.Probe('portable-archive')
    directories = []
    try:
        root = repository.secure_dir(root)
        state = repository.secure_dir(state, private=True)
        for parent in (state, root):
            path = Path(tempfile.mkdtemp(prefix='.repository-probe-', dir=parent))
            info = path.lstat()
            directories.append((path, (info.st_dev, info.st_ino)))
        local, target = (item[0] for item in directories)
        private, source, destination = (local / name for name in ('private', 'source', 'restored'))
        for path in (private, source, destination):
            path.mkdir(mode=0o700)
        (target / repository.MARKER).write_bytes(b'disposable-hostbackup-probe\n')
        enabled = metadata.prepare_source(result, source)
        for name, verified in enabled.items():
            if not verified:
                result.add('required-' + name, 'Erforderliche Metadatenwerkzeuge: ' + name, False,
                           'Portable Sicherungsstaende werden nur mit vollstaendig geprueften Metadaten aktiviert.')
        os.mkfifo(source / 'fifo', 0o640)
        os.mknod(source / 'device', stat.S_IFCHR | 0o600, os.makedev(1, 3))
        os.setxattr(source, 'user.hostbackup-root', b'root-directory')
        paths = ['.']
        for directory, names, files in os.walk(source):
            paths.extend(str((Path(directory) / name).relative_to(source)) for name in names + files)
        file_list = local / 'files.nul'
        file_list.write_bytes(b'\0'.join(os.fsencode(path) for path in paths) + b'\0')
        repo = repository.Repository(target, private)
        repo.initialize()
        exported = repo.export_key(local / 'key.json')
        repo.confirm_key(exported['sha256'])
        candidate = repo.backup('probe', file_list, 'probe', source)
        receipt = local / 'candidate.json'
        repository.atomic_write(receipt, repository.encode(candidate))
        controls = local / 'controls'
        controls.mkdir(mode=0o700)
        write_control(controls, 'manifest.json', {'backup_id': 'probe', 'status': 'complete'})
        write_control(controls, 'backup-validation.json', {'status': 'ok'})
        write_control(controls, 'source-selection.json', {})
        (controls / 'rsync-excludes.txt').write_bytes(b'')
        record = repo.commit('probe', receipt, controls)
        repo.stage(record['commit_id'], destination)
        restored = destination / 'rootfs' / str(source).lstrip('/')
        metadata.compare_restored(result, source, restored, enabled)
        result.add('fifo', 'FIFO wiederhergestellt', stat.S_ISFIFO((restored / 'fifo').lstat().st_mode), 'Dateityp verglichen.')
        expected, actual = (source / 'device').lstat(), (restored / 'device').lstat()
        result.add('device', 'Geraeteknoten wiederhergestellt', stat.S_ISCHR(actual.st_mode) and actual.st_rdev == expected.st_rdev,
                   'Typ und Geraetenummer verglichen; Geraet wurde nicht geoeffnet.')
        repo.check(read_data=True)
        result.add('repository-content', 'Repository-Inhalt', True, 'Vollstaendig gelesen und kryptografisch geprueft.')
    except (OSError, ValueError, KeyError) as error:
        result.add('repository-roundtrip', 'Repository-Roundtrip', False, str(error))
    finally:
        for path, identity in reversed(directories):
            try:
                info = path.lstat()
                if path.is_symlink() or (info.st_dev, info.st_ino) != identity:
                    raise ValueError('Testverzeichnis wurde ausgetauscht; keine Bereinigung.')
                shutil.rmtree(path)
            except (OSError, ValueError) as error:
                result.add('cleanup', 'Testdaten bereinigen', False, str(error))
    return result.result()


def candidate_validation(repo, path, controls, min_files, min_bytes):
    candidate = json.loads(repository.read_bytes(Path(path), private=True))
    saved = json.loads(repository.read_bytes(repo.state / ('candidate-' + repository.token(candidate['backup_id']) + '.json'), private=True))
    if candidate != saved or candidate['repository_id'] != repo.load()['repository_id']:
        raise ValueError('Privater Kopierbeleg stimmt nicht.')
    inventory = repo.inventory(candidate['data_snapshot_id'])
    if repository.digest(inventory) != candidate['inventory_sha256']:
        raise ValueError('Dateninventar stimmt nicht.')
    counts = candidate['summary']
    files = sum(kind == 'file' for kind in inventory.values())
    size = counts['total_bytes_processed']
    source_prefix = candidate['source_root'].rstrip('/')
    logical = {name[len(source_prefix):] or '/': kind for name, kind in inventory.items()
               if not source_prefix or name == source_prefix or name.startswith(source_prefix + '/')}
    required = all(any(name.startswith(prefix) and kind == 'file' for name, kind in logical.items())
                   for prefix in ('/etc/', '/opt/loxberry/'))
    if not required:
        raise ValueError('Systeminhalt /etc oder /opt/loxberry fehlt.')
    plausible = files >= min_files and size >= min_bytes
    validation = {'status': 'ok' if plausible else 'warning', 'checks': [
        {'name': 'Exakte Quellenauswahl im Daten-Snapshot', 'ok': True},
        {'name': 'Systeminhalt vorhanden', 'ok': required},
        {'name': 'Umfang plausibel', 'ok': plausible, 'value': {'files': files, 'bytes': size}},
        {'name': 'Vollstaendiger Wiederherstellungstest', 'ok': False, 'informational': True,
         'value': 'Nicht durch eine Strukturpruefung ersetzt; separat durchfuehren.'}]}
    write_control(controls, 'backup-validation.json', validation)
    return {'status': validation['status'], 'size_bytes': size, 'files_count': files}


def publish(repo, path, controls, destination=None):
    candidate = json.loads(repository.read_bytes(Path(path), private=True))
    # A NAS manifest must not declare completion before its authenticated commit.
    # Prepare the completed control set privately, commit it, then publish the
    # cache reference and completed manifest LAST on the target.
    # Never authenticate controls read back from a writable NAS. Their source
    # must remain private on the trusted host until the commit exists.
    controls = repository.secure_dir(controls, private=True)
    destination = repository.secure_dir(destination or controls)
    with tempfile.TemporaryDirectory(prefix='commit-controls-', dir=repo.state) as directory:
        private = Path(directory)
        for name in repository.CONTROLS:
            source = controls / name
            if source.exists() or source.is_symlink():
                repository.atomic_write(private / name, repository.read_bytes(source, private=True))
        manifest = json.loads(repository.read_bytes(private / 'manifest.json', private=True))
        validation = json.loads(repository.read_bytes(private / 'backup-validation.json', private=True))
        if validation['status'] not in ('ok', 'warning'):
            raise ValueError('Sicherung ist nicht erfolgreich geprueft.')
        manifest['status'] = 'complete' if validation['status'] == 'ok' else 'complete_with_warnings'
        repository.atomic_write(private / 'manifest.json', repository.encode(manifest) + b'\n')
        record = repo.commit(candidate['backup_id'], path, private)
    reference = {key: record[key] for key in ('format', 'repository_id', 'backup_id', 'commit_id',
                                             'commit_snapshot_id', 'data_snapshot_id')}
    # Publish only bytes from the authenticated commit, manifest LAST. Existing
    # wrapper metadata is an untrusted cache and cannot override these bytes.
    cached = {name: base64.b64decode(value, validate=True) for name, value in record['controls'].items()
              if name != 'manifest.json'}
    cached['repository-reference.json'] = repository.encode(reference) + b'\n'
    cached['manifest.json'] = base64.b64decode(record['controls']['manifest.json'], validate=True)
    for name, content in cached.items():
        fd, temporary = tempfile.mkstemp(prefix='.committed-control-', dir=destination)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            existing = destination / name
            if existing.exists() or existing.is_symlink():
                repository.read_bytes(existing)
            repo.load()
            os.replace(temporary, existing)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return reference


def parent(repo, lineage):
    host = repo.load()['host_id']
    rows = [row for row in repo.list_committed() if row['host_id'] == host and row['lineage'] == lineage]
    latest = max(rows, key=lambda row: row['created_at']) if rows else {}
    return {'backup_id': latest.get('backup_id'), 'data_snapshot_id': latest.get('data_snapshot_id')}


def stage_backup(repo, backup_id, destination):
    matches = [record for record in repo.list_committed() if record['backup_id'] == backup_id]
    if len(matches) != 1:
        raise ValueError('Eindeutiger authentifizierter Stand erforderlich.')
    record = matches[0]
    manifest = json.loads(base64.b64decode(record['controls']['manifest.json']))
    destination = repository.secure_dir(destination, private=True)
    if any(destination.iterdir()):
        raise ValueError('Staging muss leer sein; vorhandene Daten werden nicht entfernt.')
    required = int(manifest['size_bytes']) * 12 // 10 + 1024 ** 3
    if shutil.disk_usage(destination).free < required:
        raise ValueError('Linux-Staging benoetigt mindestens %d Bytes freien Speicher einschliesslich Reserve.' % required)
    # ext4 alone is not enough (for example a noacl mount). Test the actual
    # staging filesystem before claiming that restoring Linux metadata works.
    verify_local_metadata(destination, repo.state_base.parent)
    staged = repo.stage(record['commit_id'], destination)
    wrapper = destination / backup_id
    wrapper.mkdir(mode=0o700)
    restored_source = destination / 'rootfs' / record['source_root'].lstrip('/')
    os.rename(restored_source, wrapper / 'rootfs')
    # Keep original authenticated controls separately. The materialized wrapper
    # becomes an ordinary Linux-directory backup for the existing recovery tool.
    for name in record['controls']:
        if name == 'manifest.json':
            continue
        shutil.copyfile(destination / 'control' / name, wrapper / name)
        (wrapper / name).chmod(0o600)
    manifest['backup'] = {**manifest['backup'], 'storage_format': 'directory'}
    manifest['metadata'] = {**manifest['metadata'], 'mode': 'native-strict'}
    manifest['repository_origin'] = {key: record[key] for key in ('repository_id', 'data_snapshot_id', 'commit_id')}
    write_control(wrapper, 'manifest.json', manifest)
    (wrapper / '.loxberry-hostbackup-backup').write_text(backup_id + '\n')
    return {'status': 'staged', 'backup': str(wrapper), 'backup_root': str(destination),
            'warning': 'Noch kein System-Restore. Offline-Recovery-Plan und Volume-Zuordnung pruefen.'}


def verify_local_metadata(destination, state):
    result = metadata.execute_probe(destination, 'native-strict', state)
    required = {'uid', 'gid', 'permissions', 'symlink', 'hardlink', 'sparse-allocation',
                'acl-values', 'xattr-values', 'capability-values'}
    actual = {row['id'] for row in result['checks'] if row['status'] == 'ok'}
    if result['status'] != 'ok' or not required.issubset(actual):
        raise ValueError('Linux-Ziel kann erforderliche Metadaten nicht nachweislich erhalten: ' + result['message'])


def recover(repo, backup_id, staging, destination, mappings, execute=False):
    recovery = sibling('hostbackup-recovery')
    destination = recovery.checked_directory(destination)
    if str(destination) == '/':
        raise ValueError('Portable Systemwiederherstellung niemals direkt auf das laufende /.')
    if execute and os.environ.get('HOSTBACKUP_OFFLINE_RESTORE') != '1':
        raise ValueError('System-Restore nur offline: HOSTBACKUP_OFFLINE_RESTORE=1 und bewusst --execute angeben.')
    records = [row for row in repo.list_committed() if row['backup_id'] == backup_id]
    if len(records) != 1:
        raise ValueError('Eindeutiger authentifizierter Stand erforderlich.')
    manifest = json.loads(base64.b64decode(records[0]['controls']['manifest.json']))
    arch = manifest.get('host', {}).get('architecture')
    if not arch or arch != platform.machine():
        raise ValueError('Backup- und Rescue-Architektur passen nicht. Kein automatischer Architektur-/Hardwarewechsel.')
    protected = [str(repo.root), str(repo.state_base.parent), '/usr/libexec/loxberryhostbackup',
                 '/usr/local/sbin/loxberryhostbackup', '/usr/local/sbin/loxberryhostbackup-sudo']
    recovery.secure_destination(destination)
    # Validate target separation before downloading potentially large data.
    for path in (repo.root, Path(staging), repo.state_base.parent):
        if destination == path or destination in path.parents or path in destination.parents:
            raise ValueError('Restore-Ziel, Staging, Repository und Root-State muessen getrennt sein.')
    staged = stage_backup(repo, backup_id, staging)
    plan = recovery.build_plan(Path(staged['backup']), Path(staged['backup_root']), destination,
                               mappings, protected)
    print(json.dumps({'plan': plan, 'executing': execute}, ensure_ascii=True), flush=True)
    if execute:
        if manifest.get('status') != 'complete':
            raise ValueError('Stand mit Warnungen zuerst gesondert untersuchen; automatischer System-Restore bleibt gesperrt.')
        # Validate every mapped filesystem before the first system file is
        # overwritten. A suitable root target says nothing about a NAS/USB
        # volume mounted below it (or at a separate destination).
        destinations = {str(destination), *(volume['destination'] for volume in plan['volumes'])}
        for target in sorted(destinations):
            verify_local_metadata(Path(target), repo.state_base.parent)
    recovery.run_restore(plan, 'native-strict', 'directory', dry_run=not execute)
    return {'status': 'restored' if execute else 'preview', 'backup_id': backup_id,
            'stage': staged['backup'], 'destination': str(destination),
            'warning': 'Dateiwiederherstellung; Partitionierung, Bootloader und erfolgreicher Systemstart bleiben separat zu pruefen.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--state-dir', required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('status', 'init', 'key-export', 'confirm-key', 'probe'):
        sub.add_parser(name)
    command = sub.add_parser('validate-candidate')
    command.add_argument('--candidate', required=True)
    command.add_argument('--controls', required=True)
    command.add_argument('--min-files', type=int, default=100)
    command.add_argument('--min-bytes', type=int, default=104857600)
    command = sub.add_parser('publish')
    command.add_argument('--candidate', required=True)
    command.add_argument('--controls', required=True)
    command.add_argument('--destination', required=True)
    command = sub.add_parser('stage')
    command.add_argument('--backup-id', required=True)
    command.add_argument('--destination', required=True)
    command = sub.add_parser('parent')
    command.add_argument('--lineage', required=True)
    command = sub.add_parser('recover')
    command.add_argument('--backup-id', required=True)
    command.add_argument('--staging', required=True)
    command.add_argument('--destination', required=True)
    command.add_argument('--map-json', default='[]')
    command.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('Nur das vertrauenswuerdige Linux-Root-Backend darf diesen Helfer aufrufen.')
    if args.action == 'status':
        result = read_only_status(args.root, args.state_dir)
    elif args.action == 'probe':
        result = probe(args.root, args.state_dir)
    else:
        repo = adapter(args.root, args.state_dir)
        if args.action == 'key-export':
            export_key(repo)
            return
        actions = {'status': lambda: public_status(repo), 'init': lambda: (repo.initialize(), public_status(repo))[1],
                   'confirm-key': lambda: confirm_key(repo),
                   'validate-candidate': lambda: candidate_validation(repo, args.candidate, args.controls, args.min_files, args.min_bytes),
                   'publish': lambda: publish(repo, args.candidate, args.controls, args.destination),
                   'parent': lambda: parent(repo, args.lineage),
                   'recover': lambda: recover(repo, args.backup_id, args.staging, args.destination, json.loads(args.map_json), args.execute),
                   'stage': lambda: stage_backup(repo, args.backup_id, args.destination)}
        result = actions[args.action]()
    print(json.dumps(result, ensure_ascii=True))
    if result.get('status') == 'error':
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=True))
        sys.exit(1)
