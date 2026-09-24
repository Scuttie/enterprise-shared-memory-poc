"""Synthetic package boundaries; no benchmark bodies, models, or grading."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('deveval_offline_package', ROOT / 'scripts/deveval_offline_package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def make_wheel(path, name='example', version='1.0'):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name + '.dist-info/METADATA', 'Name: %s\nVersion: %s\n\n' % (name, version))


def bundle_fixture(tmp_path):
    root = tmp_path / 'bundle'
    root.mkdir()
    package.write(root / 'repo' / package.PLAN, {'synthetic': True})
    runtimes = {}
    for role, version in package.VERSIONS.items():
        assets = root / 'assets' / role
        (assets / 'wheelhouse').mkdir(parents=True)
        make_wheel(assets / 'wheelhouse/example-1.0-py3-none-any.whl')
        (assets / 'requirements.lock').write_text(package.wheel_lock(assets / 'wheelhouse'))
        runtimes[role] = {'version': version}
    support = root / 'assets/setup-support'; support.mkdir(parents=True)
    for name, version in package.setup.EXPECTED.items():
        make_wheel(support / (name + '.whl'), name, version)
    package.setup.create_manifest(support, support / 'manifest.json')
    (root / 'repo' / package.SUPPORT_LOCK).write_text(package.wheel_lock(support))
    files = [package.reference(p, root) for p in sorted(root.rglob('*')) if p.is_file()]
    package.write(root / 'manifest.json', {'schema': package.SCHEMA, 'learned_banks_included': False,
        'files': files, 'runtimes': runtimes, 'plan_reference': package.reference(root / 'repo' / package.PLAN, root),
        'setup_support_separate_from_native_79': True,
        'setup_support_reference': package.reference(support / 'manifest.json', root)})
    return root


def test_manifest_detects_changed_and_extra_files(tmp_path):
    bundle = bundle_fixture(tmp_path)
    assert package.verify(bundle)['schema'] == package.SCHEMA
    (bundle / 'unknown.json').write_text('{}')
    with pytest.raises(ValueError, match='UNMANIFESTED'):
        package.verify(bundle)
    (bundle / 'unknown.json').unlink()
    (bundle / 'repo' / package.PLAN).write_text('{}')
    with pytest.raises(ValueError, match='PACKAGE_FILE_CHANGED'):
        package.verify(bundle)


def test_committed_manifest_cannot_omit_environment_lineage(tmp_path):
    bundle = bundle_fixture(tmp_path)
    manifest = package.read(bundle / 'manifest.json')
    manifest['status'] = 'COMMITTED_SOURCE'
    (bundle / 'manifest.json').write_bytes(package.canonical(manifest))
    with pytest.raises(ValueError, match='SOURCE_ENVIRONMENT_LOCK_REQUIRED'):
        package.verify(bundle)


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'C:/other', 'x\\y'])
def test_package_path_cannot_escape(path):
    with pytest.raises(ValueError, match='UNSAFE_PACKAGE_PATH'):
        package.relative(path)


def test_wheel_lock_uses_bytes_and_rejects_duplicate_distribution(tmp_path):
    make_wheel(tmp_path / 'a.whl', name='Example_Name')
    lock = package.wheel_lock(tmp_path)
    assert lock == 'example-name==1.0 --hash=sha256:' + package.file_sha(tmp_path / 'a.whl') + '\n'
    make_wheel(tmp_path / 'b.whl', name='example-name')
    with pytest.raises(ValueError, match='DUPLICATE_WHEEL'):
        package.wheel_lock(tmp_path)


def test_wheels_must_match_pinned_environment_versions_and_denominator():
    original = 'Example_Name==1.0 \\\n+    --hash=sha256:abcd\nsecond==2.0\n'
    package.verify_wheel_versions('example-name==1.0 --hash=sha256:new\nsecond==2.0\n', original)
    for replaced in ('example-name==1.1\nsecond==2.0\n', 'example-name==1.0\n'):
        with pytest.raises(ValueError, match='WHEELS_DIFFER_FROM_PINNED_ENVIRONMENT'):
            package.verify_wheel_versions(replaced, original)


@pytest.mark.parametrize('kind', ['traversal', 'symlink', 'hardlink', 'duplicate'])
def test_interpreter_extraction_rejects_unsafe_members(tmp_path, kind):
    source = tmp_path / 'python.tar.gz'
    with tarfile.open(source, 'w:gz') as archive:
        item = tarfile.TarInfo('../escape' if kind == 'traversal' else 'driver-python/bin/python3')
        if kind in ('symlink', 'hardlink'):
            item.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
            item.linkname = '/outside'
            archive.addfile(item)
        else:
            item.size = 1
            archive.addfile(item, io.BytesIO(b'x'))
            if kind == 'duplicate':
                archive.addfile(item, io.BytesIO(b'x'))
    with pytest.raises(ValueError, match='UNSAFE_'):
        package.unpack_python(source, tmp_path / 'out', 'driver-python')
    assert not (tmp_path / 'escape').exists()


def test_runtime_install_commands_are_hash_locked_and_offline(tmp_path, monkeypatch):
    bundle = bundle_fixture(tmp_path)
    manifest = package.read(bundle / 'manifest.json')
    manifest['status'] = 'DRAFT_UNCOMMITTED_SOURCE'
    for role in package.VERSIONS:
        manifest['runtimes'][role]['wheel_count'] = 1
    monkeypatch.setattr(package, 'verify', lambda path: manifest)
    monkeypatch.setattr(package, 'reserve', lambda *args: None)
    monkeypatch.setattr(package, 'os', SimpleNamespace(name='posix', environ=dict(package.os.environ), devnull=package.os.devnull))
    monkeypatch.setattr(package.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(package.platform, 'libc_ver', lambda: ('glibc', '2.28'))
    monkeypatch.setattr(package.platform, 'platform', lambda: 'synthetic-linux')
    monkeypatch.setattr(package, 'unpack_python', lambda archive, dest, name: Path('/fake') / name / 'python')
    monkeypatch.setattr(package.subprocess, 'check_output', lambda args, **kw: ('3.9.18\n' if 'native' in args[0] else '3.10.21\n'))
    calls = []
    monkeypatch.setattr(package, 'command', lambda args, log, **kw: calls.append((list(map(str, args)), kw['env'])))
    result = package.install_offline(bundle, tmp_path / 'install')
    assert result['official_grading_calls'] == result['model_calls'] == 0
    installs = [args for args, env in calls if 'install' in args]
    assert len(installs) == 2
    assert all('--no-index' in args and '--no-deps' in args and '--require-hashes' in args for args in installs)
    assert all(env['PIP_NO_INDEX'] == '1' for args, env in calls)
    assert all('--symlinks' in args for args, env in calls if 'venv' in args)
    assert not any('run' in args or 'prepare-company' in args for args, env in calls)


@pytest.mark.parametrize('eligible,offline_error', [(True, None), (False, None),
    (True, 'missing'), (True, 'blocked'), (True, 'nonlocal')])
def test_company_preparation_final_plan_controls_then_prepare_only(tmp_path, monkeypatch, eligible, offline_error):
    bundle = bundle_fixture(tmp_path)
    repo = bundle / 'repo'
    plan = {'projects': [{'project': 'kind/example'}], 'source_archive_reference': {}, 'metadata_reference': {}}
    (repo / package.PLAN).write_bytes(package.canonical(plan))
    installed = tmp_path / 'installed'
    package.write(installed / 'installation.json', {'status': 'PASS',
        'package_manifest_sha256': package.file_sha(bundle / 'manifest.json'),
        'python': {'driver': sys.executable, 'native': '/fake/native/python'}})
    gateway = tmp_path / 'gateway.json'
    package.write(gateway, {'gateway': {'provider': 'vllm', 'model': 'synthetic-model'}})
    manifest = package.read(bundle / 'manifest.json')
    monkeypatch.setattr(package, 'verify', lambda path: manifest)
    monkeypatch.setattr(package, 'reserve', lambda *args: None)
    monkeypatch.setattr(package, 'ROOT', repo)
    context = SimpleNamespace(reference=lambda path: {'path': str(path)},
        materialize_repository=lambda *args, **kw: {'path': 'synthetic-snapshot', 'sha256': '0'*64})
    gateway_module = SimpleNamespace(_config=lambda runtime: None)
    allowlists = []
    def build_allowlist(**kwargs):
        allowlists.append(kwargs)
        return {'path': str(kwargs['output']), 'sha256': '1'*64, 'bytes': 123}
    integrity = SimpleNamespace(build_dependency_allowlist=build_allowlist)
    monkeypatch.setattr(package.importlib, 'import_module', lambda name: context if name.endswith('context')
        else integrity if name.endswith('integrity') else gateway_module)
    output = tmp_path / 'prepared'
    calls = []

    def command(args, log, **kwargs):
        calls.append(list(map(str, args)))
        if '--private-root' in args:
            evidence = {'support_reference': package.setup.reference(bundle / manifest['setup_support_reference']['path']),
                'pip_no_index': True, 'pip_find_links_local_only': True, 'pip_cache_disabled': True,
                'pip_cache_empty_at_start': True, 'initial_eggs_files': 0,
                'worker_and_setup_guard_process_count_sufficient': True, 'blocked_network_operations': 0}
            if offline_error == 'missing':
                evidence = {}
            elif offline_error == 'blocked':
                evidence['blocked_network_operations'] = 1
            elif offline_error == 'nonlocal':
                evidence['pip_find_links_local_only'] = False
            package.write(output / 'eligibility.json', {'status': 'PASS' if eligible else 'BLOCKED',
                'reference_pass': 30 if eligible else 29, 'negative_confirmed': 30,
                'inputs_reference': {'path': str(output / 'eligibility/inputs.json'), 'sha256': '0'*64},
                'setup_offline': evidence})

    monkeypatch.setattr(package, 'command', command)
    if not eligible or offline_error:
        code = 'ELIGIBILITY_FAILED_NO_TASK_SUBSTITUTION' if not eligible else 'FRESH_OFFLINE_CONTROLS_REQUIRED'
        with pytest.raises(ValueError, match=code):
            package.prepare_company(bundle, installed, output, gateway)
        assert len(calls) == 1
        assert not (output / 'runtime.local.json').exists()
        assert not allowlists
    else:
        result = package.prepare_company(bundle, installed, output, gateway)
        assert result['model_calls'] == 0
        assert len(calls) == 2 and 'prepare' in calls[1] and 'run' not in calls[1]
        assert str(repo / package.PLAN) in calls[0]
        assert 'run' in result['run_command']
        runtime = package.read(output / 'runtime.local.json')
        assert runtime['native']['model'] == 'synthetic-model'
        assert 'eligibility_bridge' not in runtime['deveval']
        assert runtime['deveval']['source_manifest_sha256'] == '0'*64
        assert runtime['deveval']['grade_work_root'] == str(output / 'grade-work')
        assert len(allowlists) == 1 and allowlists[0]['project'] == 'kind/example'
        assert set(runtime['deveval']['generated_dependency_allowlists']) == {'kind/example'}
        assert '--setup-support-sha256' in calls[0]
        assert 'bank' not in runtime


def test_portable_eligibility_extracts_without_windows_mount(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('portable_eligibility_test', ROOT / package.ELIGIBILITY)
    eligibility = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eligibility)
    monkeypatch.setattr(eligibility, 'REPOSITORY', tmp_path)
    metadata = tmp_path / 'metadata.jsonl'
    row = {'namespace': 'synthetic.task'}
    metadata.write_bytes(package.canonical(row))
    source = tmp_path / 'source.tar.gz'
    with tarfile.open(source, 'w:gz') as archive:
        item = tarfile.TarInfo('Source_Code/kind/project/pkg/synthetic.py')
        item.size = 5
        archive.addfile(item, io.BytesIO(b'pass\n'))
    code = tmp_path / 'helper.py'
    code.write_text('# synthetic authority\n')
    ref = lambda path: package.reference(path, tmp_path)
    plan = {'schema': 'deveval/repository-plan/1', 'planner_reference': ref(code),
        'asset_helper_reference': ref(code), 'metadata_reference': ref(metadata),
        'source_archive_reference': ref(source), 'projects': [{'project': 'kind/project'}],
        'tasks': [{'task_id': 'synthetic.task', 'metadata_row_sha256': package.hashlib.sha256(package.canonical(row)).hexdigest()}]}
    plan_path = tmp_path / 'plan.json'
    package.write(plan_path, plan)
    output = tmp_path / 'private-control-root'
    disks = []

    def disk_usage(path):
        assert Path(path) == output
        disks.append(str(path))
        return SimpleNamespace(free=20 * 1024**3)

    monkeypatch.setattr(eligibility.shutil, 'disk_usage', disk_usage)
    result, tasks, files = eligibility.prepare(plan_path, output)
    assert len(tasks) == len(files) == 1 and disks == [str(output)]
    assert (output / 'inputs.json').is_file()
    assert not (output / 'execution-started.json').exists()
    assert (output / 'Source_Code/kind/project/pkg/synthetic.py').read_bytes() == b'pass\n'
