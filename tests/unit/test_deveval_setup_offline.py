"""Synthetic dependency authority and actual guarded child process tests."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_setup_offline as offline


def support(tmp_path):
    folder = tmp_path / 'support'; folder.mkdir()
    for name, version in offline.EXPECTED.items():
        with zipfile.ZipFile(folder / (name + '.whl'), 'w') as archive:
            archive.writestr(name + '.dist-info/METADATA', 'Name: %s\nVersion: %s\n\n' % (name, version))
    return offline.create_manifest(folder, folder / 'manifest.json')


def test_support_rejects_changed_wheel_or_extra_local_file(tmp_path):
    ref = support(tmp_path)
    assert offline.validate_support(ref)['versions'] == offline.EXPECTED
    extra = Path(ref['path']).parent / 'unapproved.whl'
    extra.write_bytes(b'x')
    with pytest.raises(ValueError, match='UNENROLLED'):
        offline.validate_support(ref)
    extra.unlink()
    (Path(ref['path']).parent / 'pyyaml.whl').write_bytes(b'changed')
    with pytest.raises(ValueError, match='REFERENCE_CHANGED'):
        offline.validate_support(ref)


def test_offline_environment_has_no_inherited_index_or_cache(tmp_path):
    ref = support(tmp_path)
    env = offline.offline_environment(ref, tmp_path / 'cache', tmp_path / 'guard', inherited={
        'HOME': '/unchanged/home', 'PIP_INDEX_URL': 'https://unused.invalid',
        'PIP_EXTRA_INDEX_URL': 'https://unused.invalid', 'PIP_CACHE_DIR': '/previous',
        'PYTHONPATH': '/previous/code'})
    assert env['HOME'] == '/unchanged/home'
    assert env['PIP_NO_INDEX'] == env['PIP_NO_CACHE_DIR'] == '1'
    assert 'PIP_INDEX_URL' not in env and 'PIP_EXTRA_INDEX_URL' not in env
    assert env['PIP_FIND_LINKS'] == Path(ref['path']).parent.as_uri()
    assert not list((tmp_path / 'cache').iterdir())
    with pytest.raises(ValueError, match='MUST_BE_FRESH'):
        offline.offline_environment(ref, tmp_path / 'cache', tmp_path / 'other')


def test_guard_is_inherited_by_child_and_blocks_before_dns(tmp_path):
    ref = support(tmp_path)
    env = offline.offline_environment(ref, tmp_path / 'cache', tmp_path / 'guard')
    child = 'import socket,sys\ntry: socket.getaddrinfo("127.0.0.1",1)\nexcept PermissionError: sys.exit(0)\nsys.exit(99)'
    parent = 'import subprocess,sys;sys.exit(subprocess.call([sys.executable,"-B","-c",' + repr(child) + ']))'
    result = subprocess.run([sys.executable, '-B', '-c', parent], env=env, capture_output=True, timeout=15)
    assert result.returncode == 0
    report = offline.guard_report(tmp_path / 'guard')
    assert report['guarded_python_processes'] == 2
    assert report['blocked_network_operations'] == 1
    assert report['blocked_event_types'] == ['socket.getaddrinfo']


def test_guard_source_mismatch_exits_before_application(tmp_path):
    ref = support(tmp_path)
    env = offline.offline_environment(ref, tmp_path / 'cache', tmp_path / 'guard')
    site = tmp_path / 'guard/sitecustomize.py'
    site.write_text(site.read_text().replace(offline.file_sha(offline.__file__), '0' * 64))
    result = subprocess.run([sys.executable, '-B', '-c', 'print("APPLICATION_RAN")'], env=env, capture_output=True, timeout=15)
    assert result.returncode == 91 and not result.stdout
