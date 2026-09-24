"""Build/verify a curated offline DevEval handoff; never invoke a model itself.

Runtime assets are Linux x86_64 only. Model execution is a separate, explicit
manager command printed as metadata after company preparation. All target source
and tests remain opaque files; no payloads are printed or shipped into Git.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'deveval/offline-package/1'
CORE = ('deveval_prepare', 'deveval_model_gateway', 'deveval_generated_tests',
        'deveval_repository_plan', 'deveval_repository_context',
        'deveval_repository_memory', 'deveval_repository_native',
        'deveval_repository_grade', 'deveval_repository_experiment')
PLAN = 'configs/skhynix_v1/deveval_002_plan.json'
ELIGIBILITY = 'scripts/deveval_repository_eligibility.py'
VERSIONS = {'native': '3.9.18', 'driver': '3.10.21'}
ENVIRONMENT_LOCKS = {'native': 'artifacts/skhynix_v1/deveval_002/runtime-pip-freeze-002.txt',
                     'driver': 'configs/skhynix_v1/lcb_runtime_py310.lock'}


def require(value, code):
    if not value:
        raise ValueError(code)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value))


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            result.update(block)
    return result.hexdigest()


def relative(name):
    path = PurePosixPath(name)
    require(isinstance(name, str) and name and not path.is_absolute()
            and '..' not in path.parts and '\\' not in name and ':' not in name,
            'UNSAFE_PACKAGE_PATH')
    return path


def reference(path, base):
    path, base = Path(path).resolve(), Path(base).resolve()
    require(path.is_relative_to(base), 'REFERENCE_OUTSIDE_PACKAGE')
    return {'path': path.relative_to(base).as_posix(), 'bytes': path.stat().st_size,
            'sha256': file_sha(path)}


def checked(base, ref):
    base = Path(base).resolve()
    path = base.joinpath(*relative(ref['path']).parts)
    require(path.resolve().is_relative_to(base) and not path.is_symlink()
            and not any(parent.is_symlink() for parent in path.parents if parent != base and parent.is_relative_to(base)),
            'PACKAGE_SYMLINK_PATH')
    require(path.is_file() and path.stat().st_size == ref['bytes'] and
            file_sha(path) == ref['sha256'], 'PACKAGE_FILE_CHANGED')
    return path


def reserve(path, extra=0):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    require(shutil.disk_usage(path).free >= 10 * 1024**3 + extra, 'DISK_RESERVE_BELOW_10_GIB')


def copy_bytes(source, target, *, hardlink=False):
    """No chmod/copymode dependency on Windows-mounted build destinations."""
    source, target = Path(source), Path(target)
    require(source.is_file() and not target.exists(), 'COPY_SOURCE_OR_DESTINATION_INVALID')
    target.parent.mkdir(parents=True, exist_ok=True)
    if hardlink:
        try:
            os.link(source, target)
            return
        except OSError:
            pass
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1048576)


def wheel_lock(folder):
    """Bind the actual offline wheels, including locally built source wheels."""
    result, seen = [], set()
    for wheel in sorted(Path(folder).glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            require(len(names) == 1, 'INVALID_WHEEL_METADATA')
            header = archive.read(names[0]).decode('utf-8').split('\n\n', 1)[0]
        name = re.search(r'^Name: (.+)$', header, re.MULTILINE)
        version = re.search(r'^Version: (.+)$', header, re.MULTILINE)
        require(name and version, 'MISSING_WHEEL_IDENTITY')
        name, version = name[1].strip(), version[1].strip()
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and re.fullmatch(r'[A-Za-z0-9_.+!-]+', version),
                'INVALID_WHEEL_IDENTITY')
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        require(normalized not in seen, 'DUPLICATE_WHEEL_DISTRIBUTION')
        seen.add(normalized)
        result.append((normalized, version, file_sha(wheel)))
    require(result, 'EMPTY_WHEELHOUSE')
    return ''.join('%s==%s --hash=sha256:%s\n' % item for item in sorted(result))


def pinned_versions(text):
    result = {}
    for name, version in re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', text, re.MULTILINE):
        name = re.sub(r'[-_.]+', '-', name).lower()
        require(name not in result, 'DUPLICATE_ENVIRONMENT_PIN')
        result[name] = version
    require(result, 'EMPTY_ENVIRONMENT_PINS')
    return result


def verify_wheel_versions(lock, original):
    require(pinned_versions(lock) == pinned_versions(original), 'WHEELS_DIFFER_FROM_PINNED_ENVIRONMENT')


def pack_python(source, destination, name):
    """Dereference only internal interpreter links; resulting tar has no links."""
    source = Path(source).resolve()
    for path in source.rglob('*'):
        if path.is_symlink():
            require(path.resolve().is_relative_to(source), 'INTERPRETER_EXTERNAL_SYMLINK')
    require(not Path(destination).exists(), 'INTERPRETER_ARCHIVE_EXISTS')
    with tarfile.open(destination, 'w:gz', dereference=True) as archive:
        archive.add(source, arcname=name, recursive=True)


def unpack_python(archive_path, destination, expected_name):
    destination = Path(destination).resolve()
    require(not destination.exists(), 'INTERPRETER_DESTINATION_EXISTS')
    destination.mkdir(parents=True)
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for item in archive:
            path = relative(item.name)
            require(path.parts[0] == expected_name and item.name not in seen
                    and (item.isdir() or item.isreg()), 'UNSAFE_INTERPRETER_MEMBER')
            seen.add(item.name)
            target = destination.joinpath(*path.parts)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1048576)
                target.chmod(item.mode & 0o777)
    python = destination / expected_name / 'bin/python3'
    require(python.is_file(), 'INTERPRETER_BINARY_MISSING')
    return python


def command(args, log, *, cwd=None, env=None):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('xb') as output:
        status = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                                stdout=output, stderr=subprocess.STDOUT).returncode
    require(status == 0, 'OFFLINE_COMMAND_FAILED')


def import_sources(root):
    """Collect imports without initializing experiments or reading benchmark rows."""
    root = Path(root).resolve()
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root / 'scripts'), str(root / 'src')]
    for name in CORE:
        importlib.import_module(name)
    paths = {root / 'scripts' / (name + '.py') for name in CORE}
    paths.update(root.glob('src/enterprise_memory/trimem/*.py'))
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path and Path(path).resolve().is_relative_to(root):
            path = Path(path).resolve()
            require(path.suffix == '.py', 'UNEXPECTED_LOCAL_IMPORT_TYPE')
            paths.add(path)
    return paths


def build(root, output, *, native_python, driver_python, native_wheels, driver_wheels, draft=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(root == ROOT, 'RUN_BUILDER_FROM_SOURCE_REPOSITORY')
    require(not output.exists(), 'PACKAGE_OUTPUT_MUST_BE_FRESH')
    reserve(output, 2 * 1024**3)
    paths = import_sources(root)
    required = [root / p for p in (PLAN, ELIGIBILITY, 'scripts/deveval_offline_package.py',
        'scripts/deveval_repository_results.py',
        'docs/SKHYNIX_DEVEVAL_GLM_REPRODUCTION.md', 'configs/skhynix_v1/deveval_002_glm_runtime.example.json')]
    require(all(path.is_file() for path in required), 'REQUIRED_PACKAGE_SOURCE_MISSING')
    paths.update(required)
    paths.update(root / name for name in ENVIRONMENT_LOCKS.values())
    paths.update(path for pattern in ('LICENSE*', 'COPYING*', 'NOTICE*') for path in root.glob(pattern) if path.is_file())
    paths.update(root / 'data/deveval_001/upstream' / name for name in
        ('data.jsonl', 'data.tar.gz', 'pass_k.py', 'utils.py', 'README.md',
         'requirement.txt', 'environment.txt', 'check_source_code.py', 'run_pass_k.sh'))
    paths.add(root / 'data/deveval_001/Source_Code.tar.gz')
    # Do not collect outputs, training banks, original run inputs, or whole Git history.
    require(all(path.is_file() for path in paths), 'REQUIRED_PACKAGE_ASSET_MISSING')
    plan = read(root / PLAN)
    for key in ('planner_reference', 'asset_helper_reference', 'metadata_reference', 'source_archive_reference'):
        checked(root, plan[key])
    assets_module = importlib.import_module('deveval_prepare')
    for name, expected_sha in assets_module.UPSTREAM_FILES.items():
        path = root / 'data/deveval_001/upstream' / name
        if path in paths:
            require(file_sha(path) == expected_sha, 'OFFICIAL_UPSTREAM_ASSET_CHANGED')
    source_authority = {path.relative_to(root).as_posix(): reference(path, root) for path in sorted(paths)}
    # Trust only this explicitly selected build root for these read-only Git calls;
    # do not alter global safe.directory configuration on a shared machine.
    git = ['git', '-c', 'safe.directory=' + str(root)]
    head = subprocess.check_output(git + ['rev-parse', 'HEAD'], cwd=root, text=True).strip()
    curated = [path.relative_to(root).as_posix() for path in sorted(paths) if not path.relative_to(root).as_posix().startswith('data/')]
    tree = subprocess.check_output(git + ['ls-tree', '-rz', 'HEAD', '--', *curated], cwd=root)
    committed = {item.split(b'\t', 1)[1].decode(): item.split(b'\t', 1)[0].split()[2].decode()
                 for item in tree.split(b'\0') if item}
    object_format = subprocess.check_output(git + ['rev-parse', '--show-object-format'], cwd=root, text=True).strip()
    require(object_format in ('sha1', 'sha256'), 'UNKNOWN_GIT_OBJECT_FORMAT')
    uncommitted = []
    for name in curated:
        raw = (root / name).read_bytes()
        blob = hashlib.new(object_format, b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if committed.get(name) != blob:
            uncommitted.append(name)
    require(draft or not uncommitted, 'FINAL_PACKAGE_REQUIRES_COMMITTED_CURATED_SOURCES')
    output.mkdir(parents=True)
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        copy_bytes(path, output / 'repo' / name, hardlink=name.endswith('Source_Code.tar.gz'))
    runtimes = {}
    for role, source, wheels in (('native', native_python, native_wheels), ('driver', driver_python, driver_wheels)):
        assets = output / 'assets' / role
        assets.mkdir(parents=True)
        folder = assets / 'wheelhouse'
        folder.mkdir()
        for path in sorted(Path(wheels).glob('*.whl')):
            copy_bytes(path, folder / path.name)
        lock = wheel_lock(folder)
        verify_wheel_versions(lock, (root / ENVIRONMENT_LOCKS[role]).read_text(encoding='utf-8'))
        (assets / 'requirements.lock').write_bytes(lock.encode())
        pack_python(source, assets / 'python.tar.gz', role + '-python')
        runtimes[role] = {'version': VERSIONS[role], 'wheel_count': len(lock.splitlines()),
                          'python_archive': 'assets/%s/python.tar.gz' % role,
                          'requirements': 'assets/%s/requirements.lock' % role,
                          'source_environment_lock': 'repo/' + ENVIRONMENT_LOCKS[role]}
    files = [reference(p, output) for p in sorted(output.rglob('*')) if p.is_file()]
    for name, ref in source_authority.items():
        checked(root, ref)
        checked(output / 'repo', ref)
    manifest = {'schema': SCHEMA, 'status': 'DRAFT_UNCOMMITTED_SOURCE' if uncommitted else 'COMMITTED_SOURCE',
        'git_commit': head, 'uncommitted_curated_paths': uncommitted, 'files': files,
        'runtimes': runtimes, 'platform': 'linux-x86_64', 'minimum_glibc': '2.28',
        'logical_bytes': sum(ref['bytes'] for ref in files),
        'plan_reference': reference(output / 'repo' / PLAN, output),
        'model_calls': 0, 'grading_calls': 0, 'learned_banks_included': False,
        'source_files_unchanged_during_build': True,
        'notes': ['Full official source archive is grader-only; solver snapshots are rebuilt after masking.',
                  'Verify this manifest SHA256 against the transfer receipt before installation.',
                  'GLM replication starts its own DISCOVERY/VERIFICATION memory; no Luna bank is included.']}
    write(output / 'manifest.json', manifest)
    return manifest


def verify(bundle):
    bundle = Path(bundle).resolve()
    value = read(bundle / 'manifest.json')
    require(value.get('schema') == SCHEMA and value.get('learned_banks_included') is False,
            'INVALID_PACKAGE_MANIFEST')
    names = [row['path'] for row in value['files']]
    require(len(names) == len(set(names)), 'DUPLICATE_PACKAGE_PATH')
    for row in value['files']:
        checked(bundle, row)
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    require(actual == set(names) | {'manifest.json'}, 'UNMANIFESTED_PACKAGE_FILE')
    require(value['plan_reference'] in value['files'], 'PLAN_NOT_MANIFESTED')
    for role in VERSIONS:
        require(value['runtimes'][role]['version'] == VERSIONS[role], 'RUNTIME_VERSION_CHANGED')
        assets = bundle / 'assets' / role
        require((assets / 'requirements.lock').read_text() == wheel_lock(assets / 'wheelhouse'),
                'WHEEL_LOCK_CHANGED')
        original = value['runtimes'][role].get('source_environment_lock')
        require(original is not None or value.get('status') != 'COMMITTED_SOURCE', 'SOURCE_ENVIRONMENT_LOCK_REQUIRED')
        if original is not None:
            require(original == 'repo/' + ENVIRONMENT_LOCKS[role] and original in names, 'SOURCE_ENVIRONMENT_NOT_MANIFESTED')
            verify_wheel_versions((assets / 'requirements.lock').read_text(), (bundle / original).read_text())
    return value


def install_offline(bundle, output):
    require(os.name == 'posix' and platform.machine() == 'x86_64', 'LINUX_X86_64_REQUIRED')
    libc, version = platform.libc_ver()
    require(libc == 'glibc' and tuple(int(p) for p in version.split('.')[:2]) >= (2, 28), 'GLIBC_228_REQUIRED')
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    manifest = verify(bundle)
    require(not output.exists(), 'OFFLINE_INSTALL_OUTPUT_MUST_BE_FRESH')
    reserve(output, 2 * 1024**3)
    output.mkdir(parents=True)
    environment = {key: value for key, value in os.environ.items() if not key.startswith('PIP_')}
    environment.update(PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
                       PYTHONDONTWRITEBYTECODE='1', PIP_CONFIG_FILE=os.devnull)
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    runtimes = {}
    for role in VERSIONS:
        source = bundle / 'assets' / role
        standalone = unpack_python(source / 'python.tar.gz', output / role / 'standalone', role + '-python')
        version = subprocess.check_output([str(standalone), '-I', '-c', 'import platform;print(platform.python_version())'], env=environment, text=True).strip()
        require(version == VERSIONS[role], 'RELOCATED_PYTHON_VERSION_CHANGED')
        venv = output / role / 'venv'
        # Standalone builds locate bundled libpython relative to the real binary;
        # copying that binary into venv/bin breaks this loader relationship.
        command([standalone, '-I', '-m', 'venv', '--symlinks', venv], output / (role + '-venv.log'), env=environment)
        python = venv / 'bin/python'
        command([python, '-I', '-m', 'pip', 'install', '--no-index', '--no-deps', '--require-hashes',
                 '--find-links', source / 'wheelhouse', '-r', source / 'requirements.lock'],
                output / (role + '-install.log'), env=environment)
        command([python, '-I', '-m', 'pip', 'check'], output / (role + '-pip-check.log'), env=environment)
        runtimes[role] = str(python)
    repo = bundle / 'repo'
    # Current imports only; no environment eligibility, graders, or model calls.
    code = 'import sys;sys.path[:0]=' + repr([str(repo / 'scripts'), str(repo / 'src')]) + ';import deveval_repository_experiment,deveval_model_gateway,deveval_repository_results;print("DRIVER_IMPORTS_PASS")'
    command([runtimes['driver'], '-I', '-B', '-c', code], output / 'driver-imports.log', env=environment)
    code = 'import importlib.util; s=importlib.util.spec_from_file_location("official",' + repr(str(repo / 'data/deveval_001/upstream/pass_k.py')) + ');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);import pytest,func_timeout,numpy,scipy,sklearn;print("NATIVE_IMPORTS_PASS")'
    command([runtimes['native'], '-I', '-B', '-c', code], output / 'native-imports.log', env=environment)
    verify(bundle)
    receipt = {'schema': 'deveval/offline-install/1', 'status': 'PASS',
        'package_manifest_sha256': file_sha(bundle / 'manifest.json'), 'package_status': manifest['status'],
        'installer_source_sha256': file_sha(__file__),
        'python': runtimes, 'runtime_versions': VERSIONS, 'wheel_counts': {k: manifest['runtimes'][k]['wheel_count'] for k in VERSIONS},
        'network_install': False, 'pip_require_hashes': True, 'pip_check_pass': True,
        'relocated_interpreters': True, 'driver_imports_pass': True, 'native_imports_pass': True,
        'model_calls': 0, 'official_grading_calls': 0, 'platform': platform.platform(),
        'logs': [reference(p, output) for p in sorted(output.glob('*.log'))]}
    write(output / 'installation.json', receipt)
    return receipt


def prepare_company(bundle, installed, output, gateway_path):
    """Fresh fixed-reference eligibility + manager prepare; never manager run."""
    bundle, installed, output = (Path(p).resolve() for p in (bundle, installed, output))
    verify(bundle)
    receipt = read(installed / 'installation.json')
    require(receipt['status'] == 'PASS' and receipt['package_manifest_sha256'] == file_sha(bundle / 'manifest.json'),
            'INSTALLATION_NOT_BOUND_TO_PACKAGE')
    require(not output.exists(), 'COMPANY_OUTPUT_MUST_BE_FRESH')
    reserve(output)
    repo = bundle / 'repo'
    require(ROOT == repo, 'PREPARE_WITH_BUNDLED_HELPER')
    require(Path(sys.executable).resolve() == Path(receipt['python']['driver']).resolve(), 'USE_INSTALLED_DRIVER_PYTHON')
    output.mkdir(parents=True)
    sys.path[:0] = [str(repo / 'scripts'), str(repo / 'src')]
    context = importlib.import_module('deveval_repository_context')
    gateway = importlib.import_module('deveval_model_gateway')
    gateway_settings = read(gateway_path)['gateway']
    runtime = {'execution': {'python': receipt['python']['native'], 'scripts_root': str(repo / 'scripts'), 'prefix': []},
        'execution_path_remap': [], 'native': {'model': gateway_settings['model']}, 'gateway': gateway_settings,
        'deveval': {'metadata': str(repo / 'data/deveval_001/upstream/data.jsonl'),
                    'evaluator': str(repo / 'data/deveval_001/upstream/pass_k.py'),
                    'pristine_source_root': str(output / 'eligibility/pristine/Source_Code')}}
    gateway._config(runtime)  # Validate endpoint/model/bounds without opening a connection.
    plan_path = repo / PLAN
    plan = read(plan_path)
    mapping = {}
    for row in plan['projects']:
        project = row['project']
        folder = output / 'snapshots' / project.replace('/', '--')
        ref = context.materialize_repository(plan['source_archive_reference'], plan['metadata_reference'], folder,
                    project=project, plan_reference=context.reference(plan_path))
        mapping[project] = ref
    write(output / 'snapshots.local.json', mapping)
    command([receipt['python']['native'], '-B', repo / ELIGIBILITY, '--plan', plan_path,
             '--private-root', output / 'eligibility', '--report', output / 'eligibility.json'],
            output / 'eligibility.log', cwd=repo)
    eligibility = read(output / 'eligibility.json')
    require(eligibility['status'] == 'PASS' and eligibility['reference_pass'] == eligibility['negative_confirmed'] == 30,
            'ELIGIBILITY_FAILED_NO_TASK_SUBSTITUTION')
    runtime['deveval'].update(grade_work_root=str(output / 'grade-work'),
        source_manifest_path=eligibility['inputs_reference']['path'],
        source_manifest_sha256=eligibility['inputs_reference']['sha256'])
    write(output / 'runtime.local.json', runtime)
    base = [receipt['python']['driver'], '-B', str(repo / 'scripts/deveval_repository_experiment.py')]
    arguments = ['--plan', str(plan_path), '--runtime', str(output / 'runtime.local.json'),
        '--snapshots', str(output / 'snapshots.local.json'), '--eligibility', str(output / 'eligibility.json'),
        '--output', str(output / 'experiment')]
    command(base + ['prepare'] + arguments, output / 'manager-prepare.log', cwd=repo)
    verify(bundle)
    result = {'schema': 'deveval/company-preparation/1', 'status': 'PREPARED_NO_MODEL_CALLS',
        'package_manifest_sha256': file_sha(bundle / 'manifest.json'), 'model_calls': 0,
        'official_reference_controls': 30, 'official_negative_controls': 30, 'fresh_model_memory_required': True,
        'run_command': base + ['run'] + arguments, 'local_runtime': str(output / 'runtime.local.json')}
    write(output / 'company-preparation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('build', 'verify', 'install-offline', 'prepare-company'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--gateway', type=Path)
    parser.add_argument('--native-python', type=Path)
    parser.add_argument('--driver-python', type=Path)
    parser.add_argument('--native-wheels', type=Path)
    parser.add_argument('--driver-wheels', type=Path)
    parser.add_argument('--draft', action='store_true')
    args = parser.parse_args()
    if args.mode == 'build':
        result = build(ROOT, args.bundle, native_python=args.native_python, driver_python=args.driver_python,
                       native_wheels=args.native_wheels, driver_wheels=args.driver_wheels, draft=args.draft)
    elif args.mode == 'verify':
        result = verify(args.bundle)
    elif args.mode == 'install-offline':
        result = install_offline(args.bundle, args.output)
    else:
        result = prepare_company(args.bundle, args.installed, args.output, args.gateway)
    print(json.dumps({k: result[k] for k in ('schema', 'status', 'logical_bytes', 'wheel_counts', 'model_calls') if k in result}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}', str(error)) else 'DETAIL_WITHHELD'
        print(json.dumps({'status': 'ERROR', 'exception_type': type(error).__name__, 'code': code}))
        raise SystemExit(1) from None
