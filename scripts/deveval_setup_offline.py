"""Hash-bound setup dependencies and scoped offline Python subprocesses.

These four wheels are setup.py support, not additions to the solver environment.
The network guard applies only to control/test/grader children, never the model
gateway. It is a reproducibility guard for ordinary Python execution, not a
security sandbox against arbitrary native code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile

SCHEMA = 'deveval/setup-support/1'
EXPECTED = {'pyyaml': '6.0.3', 'simplejson': '4.1.2', 'ujson': '5.11.0', 'warcio': '1.8.1'}


def require(value, code):
    if not value:
        raise ValueError(code)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': file_sha(path)}


def checked(ref):
    path = Path(ref['path'])
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == ref['bytes']
            and file_sha(path) == ref['sha256'], 'SETUP_SUPPORT_REFERENCE_CHANGED')
    return path.resolve()


def wheel_identity(path):
    with zipfile.ZipFile(path) as archive:
        metadata = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        require(len(metadata) == 1, 'SETUP_WHEEL_METADATA')
        text = archive.read(metadata[0]).decode().split('\n\n', 1)[0]
    name = re.findall(r'^Name: (.+)$', text, re.MULTILINE)
    version = re.findall(r'^Version: (.+)$', text, re.MULTILINE)
    require(len(name) == len(version) == 1, 'SETUP_WHEEL_IDENTITY')
    return re.sub(r'[-_.]+', '-', name[0].strip()).lower(), version[0].strip()


def create_manifest(wheelhouse, output):
    folder, output = Path(wheelhouse).resolve(), Path(output).resolve()
    require(output.parent == folder and not output.exists(), 'SUPPORT_MANIFEST_MUST_BE_FRESH_IN_WHEELHOUSE')
    files, versions = [], {}
    for path in sorted(folder.glob('*.whl')):
        require(not path.is_symlink(), 'SETUP_WHEEL_LINK')
        name, version = wheel_identity(path)
        require(name not in versions, 'DUPLICATE_SETUP_WHEEL')
        versions[name] = version
        files.append({'path': path.name, 'bytes': path.stat().st_size, 'sha256': file_sha(path),
                      'name': name, 'version': version})
    require(versions == EXPECTED, 'SETUP_DEPENDENCY_SET_CHANGED')
    value = {'schema': SCHEMA, 'policy': 'HASH_BOUND_LOCAL_WHEELS_ONLY', 'native_packages_unchanged': True,
             'files': files, 'versions': versions}
    output.write_bytes(canonical(value))
    return reference(output)


def validate_support(ref):
    path = checked(ref)
    value = json.loads(path.read_bytes())
    require(value.get('schema') == SCHEMA and value.get('versions') == EXPECTED
            and value.get('native_packages_unchanged') is True, 'SETUP_SUPPORT_POLICY_CHANGED')
    versions, filenames = {}, set()
    for row in value['files']:
        name = row['path']
        require(isinstance(name, str) and Path(name).name == name and '/' not in name and '\\' not in name
                and name.endswith('.whl') and name not in filenames, 'SETUP_WHEEL_PATH')
        filenames.add(name)
        wheel = checked({**row, 'path': str(path.parent / name)})
        identity = wheel_identity(wheel)
        require(identity == (row['name'], row['version']) and row['name'] not in versions, 'SETUP_WHEEL_IDENTITY_CHANGED')
        versions[row['name']] = row['version']
    require(versions == EXPECTED and {p.name for p in path.parent.iterdir()} == filenames | {path.name},
            'UNENROLLED_SETUP_SUPPORT_FILE')
    return value


def activate_network_guard(guard_root):
    """Block Python socket/DNS network operations; log only event names/PIDs."""
    root = Path(guard_root).resolve()
    require(root.is_dir(), 'NETWORK_GUARD_DIRECTORY_MISSING')
    log = root / ('network-%d.jsonl' % os.getpid())

    def record(event):
        with log.open('ab') as stream:
            stream.write(canonical({'pid': os.getpid(), 'event': event}))

    blocked = {'socket.connect', 'socket.sendto', 'socket.getaddrinfo',
               'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.getnameinfo'}

    def audit(event, arguments):
        if event in blocked:
            if event in ('socket.connect', 'socket.sendto') and getattr(arguments[0], 'family', None) == 1:
                return  # AF_UNIX is local IPC, not a network endpoint.
            record(event)
            raise PermissionError('DEVEVAL_OFFLINE_NETWORK_BLOCKED')

    sys.addaudithook(audit)
    record('guard_started')


def offline_environment(support_reference, cache_root, guard_root, *, inherited=None):
    validate_support(support_reference)
    cache, guard = Path(cache_root).resolve(), Path(guard_root).resolve()
    require(not cache.exists() and not guard.exists(), 'OFFLINE_CACHE_AND_GUARD_MUST_BE_FRESH')
    cache.mkdir(parents=True)
    guard.mkdir(parents=True)
    source = Path(__file__).resolve()
    # sitecustomize import errors normally fail open. Exit immediately if this
    # pinned guard cannot initialize, before worker or pip application code runs.
    site = ('import os,sys,hashlib,importlib.util\nfrom pathlib import Path\ntry:\n'
        ' p=Path(' + repr(str(source)) + ')\n'
        ' assert hashlib.sha256(p.read_bytes()).hexdigest()==' + repr(file_sha(source)) + '\n'
        ' s=importlib.util.spec_from_file_location("_deveval_offline_guard",p)\n'
        ' m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
        ' m.activate_network_guard(' + repr(str(guard)) + ')\n'
        'except BaseException:\n os._exit(91)\n')
    (guard / 'sitecustomize.py').write_bytes(site.encode())
    base = os.environ if inherited is None else inherited
    env = {key: value for key, value in base.items() if not key.startswith('PIP_')
           and key not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PIP_NO_INDEX='1', PIP_FIND_LINKS=Path(support_reference['path']).resolve().parent.as_uri(),
               PIP_CACHE_DIR=str(cache), PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
               PIP_NO_CACHE_DIR='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(guard), DEVEVAL_OFFLINE_GUARD_ROOT=str(guard))
    return env


def guard_report(guard_root):
    events = [json.loads(line) for path in Path(guard_root).glob('network-*.jsonl')
              for line in path.read_bytes().splitlines()]
    started = {row['pid'] for row in events if row['event'] == 'guard_started'}
    denied = [row for row in events if row['event'] != 'guard_started']
    return {'guarded_python_processes': len(started), 'blocked_network_operations': len(denied),
            'blocked_event_types': sorted({row['event'] for row in denied}),
            'scope': 'PYTHON_SOCKET_DNS_AUDIT_NOT_AN_OS_NETWORK_NAMESPACE'}
