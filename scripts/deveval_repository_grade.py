"""Private official DevEval grading after solver collections are sealed."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import deveval_prepare as assets


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_pristine(request):
    manifest_path = Path(request['source_manifest_path'])
    if assets.file_sha(manifest_path) != request['source_manifest_sha256']:
        raise ValueError('PRISTINE_MANIFEST_CHANGED')
    manifest = read(manifest_path)
    root = Path(request['pristine_source_root'])
    count = 0
    for item in manifest['files']:
        path = assets.safe_relative(item['path'])
        if not path.parts or path.parts[0] != 'Source_Code':
            raise ValueError('PRISTINE_MANIFEST_PATH')
        relative = Path(*path.parts[1:])
        if request.get('project') and not relative.as_posix().startswith(request['project'] + '/'):
            continue
        current = root / relative
        if current.is_symlink() or not current.is_file() or current.stat().st_size != item['bytes'] or assets.file_sha(current) != item['sha256']:
            raise ValueError('PRISTINE_SOURCE_CHANGED')
        count += 1
    if not count:
        raise ValueError('EMPTY_PRISTINE_SCOPE')
    return {'status': 'PASS', 'verified_files': count, 'source_manifest_sha256': request['source_manifest_sha256']}


def child(request_path):
    request = read(request_path)
    evaluator = Path(request['evaluator'])
    if assets.file_sha(evaluator) != assets.UPSTREAM_FILES['pass_k.py']:
        raise ValueError('OFFICIAL_EVALUATOR_CHANGED')
    metadata = Path(request['metadata'])
    if assets.file_sha(metadata) != request['metadata_sha256']:
        raise ValueError('METADATA_CHANGED')
    matches = [json.loads(line) for line in metadata.read_bytes().splitlines() if line.strip()
               and json.loads(line)['namespace'] == request['task_id']]
    if len(matches) != 1:
        raise ValueError('TASK_ID_NOT_UNIQUE')
    task = matches[0]
    if task['project_path'] != request['project']:
        raise ValueError('TASK_PROJECT_CHANGED')
    candidate_path = Path(request['candidate_path'])
    code = candidate_path.read_bytes().decode('utf-8')
    if hashlib.sha256(code.encode()).hexdigest() != request['candidate_sha256']:
        raise ValueError('CANDIDATE_CHANGED')
    task = dict(task, completion=code)
    spec = importlib.util.spec_from_file_location('deveval_pinned_private_grade', evaluator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = Path(request['source_root']).joinpath(*assets.safe_relative(task['completion_path']).parts)
    before = assets.file_sha(target)
    started = time.monotonic()
    try:
        outcome = module.check_correctness(argparse.Namespace(source_code_root=request['source_root']), task)
        error_type = None
    except BaseException as error:
        outcome, error_type = 'InfrastructureException', type(error).__name__
    restored = target.exists() and assets.file_sha(target) == before
    result = {'schema': 'deveval-private-grade/1', 'task_id': request['task_id'], 'project': request['project'],
        'candidate_sha256': request['candidate_sha256'], 'official_result': outcome, 'exception_type': error_type,
        'source_restored': restored, 'source_file_before_sha256': before,
        'elapsed_seconds': time.monotonic() - started, 'junit': assets.xml_counts(request['junit']),
        'private_selector_count': len(task['tests']), 'metadata_sha256': request['metadata_sha256'],
        'evaluator_reference': assets.reference(evaluator)}
    assets.write_new(request['child_receipt'], result)


def run(request_path):
    if os.name == 'nt':
        raise ValueError('OFFICIAL_DEVEVAL_REQUIRES_POSIX')
    request_path = Path(request_path).resolve()
    request = read(request_path)
    folder = request_path.parent
    if 'source_manifest_path' in request:
        verify_pristine(request)
    pristine = Path(request['pristine_source_root']).resolve()
    source_root = Path(request.get('working_source_root', str(folder / 'Source_Code')))
    if not source_root.is_absolute() or '..' in source_root.parts:
        raise ValueError('INVALID_GRADE_WORK_ROOT')
    project = assets.safe_relative(request['project'])
    origin = pristine.joinpath(*project.parts)
    if not origin.is_dir() or source_root.exists():
        raise ValueError('GRADE_WORKSPACE_MUST_BE_FRESH')
    files = [p for p in origin.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in origin.rglob('*')):
        raise ValueError('PRISTINE_LINK_FORBIDDEN')
    source_manifest = {p.relative_to(origin).as_posix(): assets.file_sha(p) for p in files}
    destination = source_root.joinpath(*project.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origin, destination)
    worker_request = {**request, 'source_root': str(source_root), 'junit': str(folder / 'junit.xml'),
                      'child_receipt': str(folder / 'child-receipt.json')}
    assets.write_new(folder / 'child-request.json', worker_request)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0',
        PYTEST_ADDOPTS='--junitxml=' + str(folder / 'junit.xml'))
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
    started, timed_out = time.monotonic(), False
    with (folder / 'stdout.log').open('xb') as stdout, (folder / 'stderr.log').open('xb') as stderr:
        process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'child', str(folder / 'child-request.json')],
            cwd=folder, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=85)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        finally:
            # The upstream helper only terminates its immediate setup.py child.
            # Reap descendants belonging to this grade even after normal exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    child_path = folder / 'child-receipt.json'
    result = read(child_path) if child_path.exists() else {'schema': 'deveval-private-grade/1',
        'task_id': request['task_id'], 'project': request['project'], 'candidate_sha256': request['candidate_sha256'],
        'official_result': 'OuterTimeout' if timed_out else 'MissingReceipt', 'source_restored': False}
    unchanged = all((destination / name).is_file() and assets.file_sha(destination / name) == sha for name, sha in source_manifest.items())
    unexpected_files = [p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()
        and p.relative_to(destination).as_posix() not in source_manifest
        and not assets.is_generated_build_metadata(p.relative_to(destination).as_posix())]
    official = result['official_result']
    known = (process.returncode == 0 and not timed_out and official in ('Pass', 'Error', 'TimeOut', 'OOM')
             and result.get('source_restored') and unchanged and not unexpected_files)
    # Eligibility of the unchanged reference for this exact task is checked by the manager.
    result.update(status='GRADED' if known else 'INFRA_ERROR', passed=(official == 'Pass') if known else None,
        timed_out=timed_out, process_exit_code=process.returncode, pristine_source_unchanged=unchanged,
        unexpected_file_count=len(unexpected_files), elapsed_total_seconds=time.monotonic() - started,
        request_reference=assets.reference(request_path), request_candidate_sha256=request['candidate_sha256'])
    assets.write_new(folder / 'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'child', 'verify'))
    parser.add_argument('request', type=Path)
    args = parser.parse_args()
    if args.mode == 'verify':
        request = json.loads(sys.stdin.buffer.read()) if str(args.request) == '-' else read(args.request)
        print(json.dumps(verify_pristine(request)))
    elif args.mode == 'child':
        child(args.request)
    else:
        run(args.request)


if __name__ == '__main__':
    main()
