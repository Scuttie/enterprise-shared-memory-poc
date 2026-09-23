"""Resumable public-only pilot collection, frozen memory, and separate grading.

Run receipts contain metadata only. Native cell directories contain public task
and model traces; private grader material stays in a separate manager directory.
An interrupted native attempt is held, never automatically submitted again.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time

import trimem_lcb_memory as memory
import trimem_lcb_native as native
from trimem_lcb_grade import UPSTREAM_COMMIT

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'trimem/lcb-experiment/1.0'
EXPECTED_TASKS = 1055
PILOT_SIZE = 24
SPLIT_KEYS = ('dataset_id', 'source_revision', 'release', 'split_policy', 'pilot_policy',
    'train_ids', 'valid_ids', 'test_ids', 'pilot_ids', 'train_pilot_ids', 'counts',
    'task_descriptors', 'task_families', 'family_reassignments',
    'pilot_difficulty_counts', 'train_pilot_difficulty_counts', 'source_hashes',
    'public_tasks_reference')


class ExperimentError(ValueError):
    pass


class FrozenInputChanged(ExperimentError):
    pass


def canonical(value):
    return native.canonical(value)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    native.write(Path(path), value)


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path), 'bytes': path.stat().st_size}


def checked_reference(root, ref):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        raise ExperimentError('Invalid file reference')
    relative = Path(ref['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ExperimentError('File reference escaped its root')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or file_hash(path) != ref.get('sha256'):
        raise FrozenInputChanged('Referenced file is missing or changed')
    if 'bytes' in ref and path.stat().st_size != ref['bytes']:
        raise FrozenInputChanged('Referenced file size changed')
    return path


@contextmanager
def exclusive_lock(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'experiment.lock').open('a+b') as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ExperimentError('Another manager holds this experiment') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def implementation_references():
    paths = set((ROOT / 'scripts').glob('trimem_lcb_*.py'))
    paths.update((ROOT / 'src' / 'enterprise_memory' / 'trimem').rglob('*.py'))
    package_init = ROOT / 'src' / 'enterprise_memory' / '__init__.py'
    if package_init.is_file():
        paths.add(package_init)
    return [reference(path) for path in sorted(paths)]


def verify_frozen(frozen):
    for ref in frozen['references']:
        path = Path(ref['path'])
        if not path.is_file() or file_hash(path) != ref['sha256'] or path.stat().st_size != ref['bytes']:
            raise FrozenInputChanged('Frozen implementation or input changed')
    if implementation_references() != frozen['implementation']:
        raise FrozenInputChanged('Implementation file set changed')


def _repo_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def validate_control(config, split):
    path = _repo_path(config['official_control_receipt'])
    if file_hash(path) != config['official_control_receipt_sha256']:
        raise FrozenInputChanged('Official control receipt changed')
    receipt = read(path)
    runs = {row.get('label'): row for row in receipt.get('runs', [])}
    positive, negative = runs.get('saved-positive', {}), runs.get('invalid-syntax-negative', {})
    if (receipt.get('schema') != 'trimem/lcb-official-infrastructure-controls/1.0' or
            receipt.get('status') != 'PASS' or receipt.get('model_calls') != 0 or receipt.get('memory_writes') != 0 or
            receipt.get('official_commit') != UPSTREAM_COMMIT or
            receipt.get('split_reference', {}).get('sha256') != config['split_sha256'] or
            receipt.get('grader_reference', {}).get('sha256') != file_hash(ROOT / 'scripts' / 'trimem_lcb_grade.py') or
            any(row.get('status') != 'COMPLETE' or row.get('returncode') != 0 or
                row.get('counts', {}).get('graded') != 2 or row.get('counts', {}).get('not_graded') != 0
                for row in (positive, negative)) or
            positive.get('counts', {}).get('passed') != 2 or negative.get('counts', {}).get('passed') != 0):
        raise ExperimentError('Official positive and negative controls are not verified')
    exclusions = set(receipt.get('exclude_from_all_model_training_and_memory_capture', []))
    if (exclusions != set(config.get('infrastructure_control_excluded_train_ids', [])) or
            exclusions.intersection(split['train_pilot_ids']) or exclusions.intersection(split['pilot_ids'])):
        raise ExperimentError('Official control tasks overlap model enrollment')
    return path


def load_inputs(config_path, runtime_path, dataset_root):
    config, runtime = read(config_path), read(runtime_path)
    if config.get('schema') != 'trimem/lcb-pilot-config/1.0':
        raise ExperimentError('Unsupported experiment configuration')
    if (config.get('workers', 2) not in (1, 2) or
            config.get('requested_model') != runtime['native']['model'] or
            config.get('reasoning_effort') != runtime['native']['reasoning_effort'] or
            config.get('limits') != native.LIMITS):
        raise ExperimentError('Model, reasoning effort, workers, or limits differ')
    if (native.mapped_path(ROOT / 'scripts', runtime).replace('\\', '/').rstrip('/').casefold() !=
            runtime['execution']['scripts_root'].replace('\\', '/').rstrip('/').casefold()):
        raise ExperimentError('Execution scripts differ from the frozen implementation')
    for key in ('experiment_id', 'org_id', 'owner_user_id'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ExperimentError('Missing experiment identity')
    split_path = _repo_path(config['split_path'])
    if file_hash(split_path) != config['split_sha256']:
        raise FrozenInputChanged('Configured split changed')
    split = read(split_path)
    if split.get('schema') != 'trimem/lcb-split/1.0':
        raise ExperimentError('Unsupported split')
    manifest_path = checked_reference(dataset_root, split['dataset_reference'])
    manifest = read(manifest_path)
    if (manifest.get('schema') not in ('trimem/lcb-public-dataset/1.0', 'trimem/lcb-dataset/1.0') or
            manifest.get('task_count') != EXPECTED_TASKS or
            manifest.get('revision') != split.get('source_revision') or
            manifest.get('dataset_id') != split.get('dataset_id') or
            manifest.get('release') != split.get('release') or
            manifest.get('public_tasks_reference') != split.get('public_tasks_reference') or
            manifest.get('source_files') != split.get('source_hashes')):
        raise ExperimentError('Public source identities differ')
    public_path = checked_reference(dataset_root, manifest['public_tasks_reference'])
    tasks = {}
    with public_path.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            memory._descriptor(row)
            identity = row['task_id']
            if identity in tasks:
                raise ExperimentError('Duplicate public task identity')
            tasks[identity] = row
    partitions = [split[name + '_ids'] for name in ('train', 'valid', 'test')]
    all_ids = [identity for partition in partitions for identity in partition]
    if len(tasks) != EXPECTED_TASKS or len(all_ids) != len(set(all_ids)) or set(all_ids) != set(tasks):
        raise ExperimentError('Task partition coverage differs')
    for name, partition in zip(('train', 'valid', 'test'), partitions):
        if any(tasks[identity]['split'] != name for identity in partition):
            raise ExperimentError('Public task partition differs')
    for selected, partition in (('train_pilot_ids', 'train_ids'), ('pilot_ids', 'valid_ids')):
        ids = split[selected]
        if len(ids) != PILOT_SIZE or len(set(ids)) != PILOT_SIZE or not set(ids) <= set(split[partition]):
            raise ExperimentError('Pilot enrollment differs')
    descriptors = {item['task_id']: item for item in split['task_descriptors']}
    if len(descriptors) != len(tasks):
        raise ExperimentError('Task descriptors differ')
    for identity, row in tasks.items():
        if identity not in descriptors or any(row.get(key) != value for key, value in descriptors[identity].items()):
            raise ExperimentError('Task descriptor fingerprint differs')
    control_path = validate_control(config, split)
    # The memory initializer also enforces family/instruction split disjointness.
    sources = implementation_references()
    frozen = {'schema': SCHEMA, 'experiment_id': config['experiment_id'],
        'dataset_root': str(Path(dataset_root).resolve()), 'implementation': sources,
        'references': sources + [reference(path) for path in
            (config_path, runtime_path, split_path, manifest_path, public_path, control_path)],
        'enrollment': {'train': split['train_pilot_ids'], 'valid': split['pilot_ids']},
        'model': runtime['native']['model'], 'reasoning_effort': runtime['native']['reasoning_effort'],
        'limits': dict(native.LIMITS), 'workers': config.get('workers', 2)}
    return config, runtime, split, manifest, tasks, frozen


def cell_name(task_id, arm):
    prefix = 'train' if arm == 'TRAIN' else 'valid-' + arm.lower()
    return prefix + '-' + sha(task_id.encode())[:20]


def _cell_result(cell, task, arm, receipt, state):
    if (receipt.get('schema') != 'trimem/lcb-solve-receipt/1.0' or
            receipt.get('task_id') != task['task_id'] or receipt.get('arm') != arm or
            state.get('task') != task or state.get('arm') != arm or
            receipt.get('state_sha256') != file_hash(cell / 'state.json') or
            receipt.get('candidate_sha256') != sha(state.get('candidate', '').encode()) or
            receipt.get('status') not in ('SUBMITTED', 'GENERATION_ERROR') or
            (receipt['status'] == 'SUBMITTED' and not state.get('finished'))):
        raise ExperimentError('Native solve receipt identity differs')
    usage = {}
    threads = []
    for session in receipt.get('sessions', []):
        threads.extend(value for value in session.get('thread_ids', []) if isinstance(value, str) and value)
        for item in session.get('usage', []):
            if isinstance(item, dict):
                for key, value in item.items():
                    if type(value) in (int, float) and value >= 0:
                        usage[key] = usage.get(key, 0) + value
    injections = state.get('memory_injections', [])
    kinds = {}
    for item in injections:
        kind = item.get('kind', 'unknown')
        kinds[kind] = kinds.get(kind, 0) + 1
    return {'task_id': task['task_id'], 'arm': arm, 'status': receipt['status'],
        'error_type': receipt.get('error_type'), 'candidate_sha256': receipt['candidate_sha256'],
        'solve_reference': reference(cell / 'solve-receipt.json'),
        'thread_ids': threads, 'session_count': len(receipt.get('sessions', [])), 'tokens': usage,
        'wall_seconds': receipt.get('wall_seconds', 0), 'tool_seconds': receipt.get('tool_seconds', 0),
        'tool_actions': receipt.get('tool_actions', 0), 'public_test_runs': receipt.get('public_test_runs', 0),
        'public_infrastructure_errors': sum(event.get('tool') == 'run_public_tests' and
            event.get('result_payload', {}).get('status') == 'INFRA_ERROR' for event in state.get('history', [])),
        'memory_injection_count': len(injections), 'memory_injections_by_kind': kinds,
        'handoff_count': max(0, len(receipt.get('sessions', [])) - 1),
        'memory_exposure_bytes': len(canonical(injections)) if injections else 0,
        'capture_status': 'PENDING' if arm == 'TRAIN' and receipt['status'] == 'SUBMITTED' else 'NOT_APPLICABLE',
        'grade_status': 'PENDING' if receipt['status'] == 'SUBMITTED' else 'GENERATION_ERROR', 'passed': None}


def collect_cell(output, task, arm, runtime, bank, frozen):
    verify_frozen(frozen)
    cell = Path(output) / 'cells' / cell_name(task['task_id'], arm)
    result_path = cell / 'cell-receipt.json'
    if (cell / 'solve-receipt.json').is_file():
        receipt, state = read(cell / 'solve-receipt.json'), read(cell / 'state.json')
        if state.get('runtime') != runtime or state.get('bank') != bank:
            raise ExperimentError('Resumed cell runtime or frozen bank differs')
        result = _cell_result(cell, task, arm, receipt, state)
        if result_path.exists():
            previous = read(result_path)
            if ((previous.get('grade_status') == 'GRADED' or previous.get('passed') is not None) and
                    'grade_reference' not in previous):
                raise FrozenInputChanged('Cached verdict lacks grader evidence')
            if previous.get('grade_status') != 'GRADED' and previous.get('passed') is not None:
                raise FrozenInputChanged('Ungraded outcome claims a verdict')
            if previous.get('capture_status') == 'CAPTURED' and 'capture_reference' not in previous:
                raise FrozenInputChanged('Cached capture lacks evidence')
            mutable = {'capture_status', 'grade_status', 'passed'}
            for key in set(result) - mutable:
                if previous.get(key) != result.get(key):
                    raise ExperimentError('Recorded cell identity differs')
            for key, filename in (('capture_reference', 'capture-receipt.json'), ('grade_reference', None)):
                if key in previous:
                    path = cell / filename if filename else Path(output) / 'private-grades' / cell.name / 'report.json'
                    if previous[key] != reference(path):
                        raise FrozenInputChanged('Cached evidence changed')
            if 'grade_reference' in previous:
                rows = read(previous['grade_reference']['path']).get('results', [])
                if (len(rows) != 1 or rows[0].get('question_id') != task['task_id'] or
                        rows[0].get('passed') != previous.get('passed') or
                        rows[0].get('status') != previous.get('grade_status')):
                    raise FrozenInputChanged('Cached verdict differs from evidence')
            return previous
        write(result_path, result)
        return result
    if cell.exists():
        result = {'task_id': task['task_id'], 'arm': arm, 'status': 'HELD',
            'error_type': 'InterruptedNativeAttempt', 'passed': None,
            'grade_status': 'NOT_GRADED', 'capture_status': 'NOT_APPLICABLE'}
        write(result_path, result)
        return result
    native.initialize_cell(cell, task, arm, runtime, bank=bank)
    write(cell / 'attempt.json', {'task_id': task['task_id'], 'arm': arm,
        'frozen_sha256': sha(canonical(frozen)), 'started_at': datetime.now(timezone.utc).isoformat()})
    try:
        receipt = native.solve_cell(cell, before_model_call=lambda: verify_frozen(frozen))
    except FrozenInputChanged:
        raise
    except Exception as exc:
        result = {'task_id': task['task_id'], 'arm': arm, 'status': 'HELD',
            'error_type': type(exc).__name__, 'passed': None, 'grade_status': 'NOT_GRADED',
            'capture_status': 'NOT_APPLICABLE'}
    else:
        verify_frozen(frozen)
        result = _cell_result(cell, task, arm, receipt, read(cell / 'state.json'))
    write(result_path, result)
    return result


def capture_cell(output, task, result, runtime):
    if result['status'] != 'SUBMITTED' or result.get('capture_status') != 'PENDING':
        return result
    cell = Path(output) / 'cells' / cell_name(task['task_id'], 'TRAIN')
    state = read(cell / 'state.json')
    try:
        threads = result['thread_ids']
        if not threads:
            raise ExperimentError('Actual native contributor identity is missing')
        receipt = memory.capture_training_episode(Path(output) / 'training-memory', task, state['history'],
            graph=native.ShortTermWorkingGraph.from_snapshot(state['graph']), final_code=state['candidate'],
            source_lesson=state['source_lesson'], contributor_id=threads[-1],
            model_id=runtime['native']['model'], created_at=state['started_at'])
        write(cell / 'capture-receipt.json', receipt)
        result.update(capture_status='CAPTURED', capture_reference=reference(cell / 'capture-receipt.json'))
    except Exception as exc:
        result.update(capture_status='CAPTURE_ERROR', capture_error_type=type(exc).__name__)
    write(cell / 'cell-receipt.json', result)
    return result


def freeze_bank(output):
    output = Path(output)
    receipt_path = output / 'bank-receipt.json'
    bank_path = output / 'frozen-bank.json'
    if receipt_path.exists():
        result = read(receipt_path)
    elif bank_path.exists():
        # A crash after atomic bank publication must not recollect training.
        manifest = read(bank_path)
        result = {'path': str(bank_path), 'sha256': file_hash(bank_path), 'layer_counts': manifest['layer_counts']}
        with memory.load_frozen_bank(result['path'], result['sha256']):
            pass
        write(receipt_path, result)
    else:
        result = memory.freeze_training_bank(output / 'training-memory', bank_path)
        write(receipt_path, result)
    with memory.load_frozen_bank(result['path'], result['sha256']):
        pass
    return result


def verify_bank_cohort(bank, results, runtime):
    expected = {row['task_id']: row for row in results
        if row['arm'] == 'TRAIN' and row.get('capture_status') == 'CAPTURED'}
    with memory.load_frozen_bank(bank['path'], bank['sha256']) as frozen:
        actual = set()
        for ref in frozen.manifest['catalog']['captures'].values():
            capture = read(checked_reference(frozen.root, ref))['capture']
            identity = capture['task_public']['task_id']
            if (identity not in expected or capture['model_id'] != runtime['native']['model'] or
                    capture['contributor_id'] not in expected[identity]['thread_ids'] or
                    sha(capture['final_code'].encode()) != expected[identity]['candidate_sha256']):
                raise FrozenInputChanged('Frozen bank differs from collected training cells')
            actual.add(identity)
        if actual != set(expected):
            raise FrozenInputChanged('Frozen bank training enrollment differs')


def final_manifest(config, split, public_manifest, dataset_root, output):
    path = Path(dataset_root) / 'dataset-manifest.json'
    ready_path = Path(dataset_root) / 'dataset-ready.json'
    if not ready_path.exists():
        return None
    ready = read(ready_path)
    if (ready.get('schema') != 'trimem/lcb-dataset-ready/1.0' or ready.get('status') != 'READY' or
            ready.get('identities_verified') is not True or ready.get('private_file_count') != EXPECTED_TASKS or
            checked_reference(dataset_root, ready['manifest_reference']) != path.resolve()):
        raise FrozenInputChanged('Private dataset readiness is invalid')
    final_split_path = _repo_path(config.get('final_split_path', config['split_path'].replace('_public_split', '_split')))
    if not final_split_path.exists():
        raise FrozenInputChanged('Published final split is missing')
    if (file_hash(final_split_path) != ready['split_reference']['sha256'] or
            ready.get('public_split_reference', {}).get('sha256') != config['split_sha256']):
        raise FrozenInputChanged('Ready dataset split differs')
    final_split, manifest = read(final_split_path), read(path)
    if (manifest.get('schema') != 'trimem/lcb-dataset/1.0' or
            any(manifest.get(key) != public_manifest.get(key) for key in
                ('dataset_id', 'revision', 'release', 'task_count', 'source_files', 'public_tasks_reference', 'counts')) or
            any(final_split.get(key) != split.get(key) for key in SPLIT_KEYS) or
            checked_reference(dataset_root, final_split['dataset_reference']) != path.resolve()):
        raise FrozenInputChanged('Final dataset differs from enrolled public dataset')
    refs = {'manifest': reference(path), 'split': reference(final_split_path), 'ready': reference(ready_path)}
    saved = Path(output) / 'private-dataset-receipt.json'
    if saved.exists() and read(saved) != refs:
        raise FrozenInputChanged('Final private dataset changed')
    write(saved, refs)
    return manifest


def grade_cell(output, task_id, arm, result, manifest, dataset_root, runtime, config):
    if result['status'] != 'SUBMITTED' or (result.get('grade_status') != 'PENDING' and 'grade_reference' not in result):
        return result
    cell = Path(output) / 'cells' / cell_name(task_id, arm)
    directory = Path(output) / 'private-grades' / cell_name(task_id, arm)
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / 'report.json'
    started = time.monotonic()
    try:
        source = checked_reference(dataset_root, manifest['private_evaluation_files'][task_id])
        state = read(cell / 'state.json')
        if sha(state['candidate'].encode()) != result['candidate_sha256']:
            raise FrozenInputChanged('Submitted candidate changed')
        sample_path = directory / 'evaluation.json'
        prediction_path = directory / 'predictions.json'
        prediction = {'schema': 'trimem/lcb-predictions/1.0',
            'expected_question_ids': [task_id], 'model': runtime['native']['model'],
            'predictions': [{'question_id': task_id, 'output': '```python\n' + state['candidate'] + '\n```'}]}
        settings = config.get('private_grading', {})
        if not report_path.exists():
            with gzip.open(source, 'rb') as src, sample_path.open('wb') as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    dst.write(chunk)
            write(prediction_path, prediction)
            command = native.execution_command(runtime, 'trimem_lcb_grade.py', [
                '--predictions', native.mapped_path(prediction_path, runtime),
                '--dataset-json', native.mapped_path(sample_path, runtime), '--dataset-sha256', file_hash(sample_path),
                '--official-repo', runtime['execution']['official_repo'],
                '--output', native.mapped_path(report_path, runtime),
                '--workers', str(settings.get('workers_per_cell', 1)),
                '--timeout', str(settings.get('timeout_seconds_per_case', 6))])
            env = {key: value for key, value in os.environ.items() if key not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
            transport = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=1800,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            write(directory / 'transport.json', {'returncode': transport.returncode,
                'stdout_sha256': sha(transport.stdout), 'stderr_sha256': sha(transport.stderr),
                'wall_seconds': time.monotonic() - started})
            if transport.returncode not in (0, 2) or not report_path.is_file():
                raise ExperimentError('Private grader transport failed')
        report = read(report_path)
        rows = report.get('results', [])
        sample_hash = hashlib.sha256()
        with gzip.open(source, 'rb') as src:
            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                sample_hash.update(chunk)
        provenance = report.get('provenance', {})
        if (provenance.get('upstream_commit') != UPSTREAM_COMMIT or
                provenance.get('dataset_reference', {}).get('sha256') != sample_hash.hexdigest() or
                file_hash(sample_path) != sample_hash.hexdigest() or
                provenance.get('predictions_reference', {}).get('sha256') != sha(canonical(prediction)) or
                file_hash(prediction_path) != sha(canonical(prediction)) or
                report.get('settings', {}).get('timeout_seconds') != settings.get('timeout_seconds_per_case', 6) or
                report.get('settings', {}).get('workers') != settings.get('workers_per_cell', 1)):
            raise FrozenInputChanged('Private grader inputs or settings differ')
        if (report.get('schema') != 'trimem/lcb-grade-report/1.0' or len(rows) != 1 or
                rows[0].get('question_id') != task_id or
                rows[0].get('status') not in ('GRADED', 'GENERATION_ERROR', 'GRADER_ERROR', 'NOT_GRADED') or
                (rows[0]['status'] == 'GRADED' and type(rows[0].get('passed')) is not bool) or
                (rows[0]['status'] == 'GRADED' and rows[0].get('extracted_code_sha256') != result['candidate_sha256']) or
                (rows[0]['status'] != 'GRADED' and rows[0].get('passed') is not None)):
            raise ExperimentError('Private grader report identity differs')
        result.update(grade_status=rows[0]['status'], passed=rows[0]['passed'],
            grade_reference=reference(report_path), grader_seconds=report.get('timings', {}).get('overall_seconds', time.monotonic() - started))
        if rows[0].get('error_type'):
            result['grade_error_type'] = rows[0]['error_type']
    except FrozenInputChanged:
        raise
    except Exception as exc:
        result.update(grade_status='GRADER_ERROR', passed=None, grade_error_type=type(exc).__name__,
            grader_seconds=time.monotonic() - started)
    write(cell / 'cell-receipt.json', result)
    return result


def summarize(config, split, results, bank, *, private_ready, manager_seconds):
    def effective(row):
        if type(row.get('passed')) is bool:
            return row['passed'], 'SOLVED' if row['passed'] else 'WRONG_SOLUTION'
        if row['status'] == 'GENERATION_ERROR':
            if row.get('error_type') in ('TaskTimeout', 'SessionBudgetExhausted'):
                return False, 'BUDGET_EXHAUSTED'
            if row.get('error_type') in ('MissingSubmission', 'UnexpectedNativeTool', 'ActionCallBudgetExceeded'):
                return False, 'MODEL_PROTOCOL_FAILURE'
        return None, 'PENDING_GRADING' if row.get('grade_status') == 'PENDING' else 'INFRASTRUCTURE_UNRESOLVED'
    for row in results:
        row['resolved'], row['outcome'] = effective(row)
    arms = {}
    for arm, planned in (('TRAIN', len(split['train_pilot_ids'])), ('OFF', len(split['pilot_ids'])), ('ON', len(split['pilot_ids']))):
        rows = [row for row in results if row['arm'] == arm]
        graded = sum(type(row.get('passed')) is bool for row in rows)
        passed = sum(row.get('passed') is True for row in rows)
        tokens = {}
        kinds = {}
        for row in rows:
            for key, value in row.get('tokens', {}).items():
                tokens[key] = tokens.get(key, 0) + value
            for key, value in row.get('memory_injections_by_kind', {}).items():
                kinds[key] = kinds.get(key, 0) + value
        resolved_count = sum(type(row['resolved']) is bool for row in rows)
        resolved_passes = sum(row['resolved'] is True for row in rows)
        arms[arm] = {'planned': planned, 'recorded': len(rows),
            'submitted': sum(row['status'] == 'SUBMITTED' for row in rows),
            'held': sum(row['status'] == 'HELD' for row in rows),
            'generation_errors': sum(row['status'] == 'GENERATION_ERROR' for row in rows),
            'graded': graded, 'passed': passed, 'failed': graded - passed, 'not_graded': planned - graded,
            'resolved_outcomes': resolved_count, 'infrastructure_or_pending': planned - resolved_count,
            'resolved_rate': resolved_passes / planned if resolved_count == planned else None,
            'model_protocol_failures': sum(row['outcome'] == 'MODEL_PROTOCOL_FAILURE' for row in rows),
            'budget_exhausted': sum(row['outcome'] == 'BUDGET_EXHAUSTED' for row in rows),
            'pass_at_1': passed / planned if graded == planned else None,
            'graded_pass_at_1_descriptive': passed / graded if graded else None,
            'tokens': tokens, 'billing_cost': None,
            'solve_seconds': sum(row.get('wall_seconds', 0) for row in rows),
            'public_tool_seconds': sum(row.get('tool_seconds', 0) for row in rows),
            'grader_seconds': sum(row.get('grader_seconds', 0) for row in rows),
            'public_test_runs': sum(row.get('public_test_runs', 0) for row in rows),
            'public_infrastructure_errors': sum(row.get('public_infrastructure_errors', 0) for row in rows),
            'sessions': sum(row.get('session_count', 0) for row in rows),
            'handoffs': sum(row.get('handoff_count', 0) for row in rows),
            'memory_injection_count': sum(row.get('memory_injection_count', 0) for row in rows),
            'memory_injections_by_kind': kinds,
            'memory_exposure_bytes': sum(row.get('memory_exposure_bytes', 0) for row in rows),
            'captured': sum(row.get('capture_status') == 'CAPTURED' for row in rows),
            'capture_errors': sum(row.get('capture_status') == 'CAPTURE_ERROR' for row in rows)}
    paired = {(row['task_id'], row['arm']): row.get('passed') for row in results}
    deltas, gains, losses = [], 0, 0
    for identity in split['pilot_ids']:
        off, on = paired.get((identity, 'OFF')), paired.get((identity, 'ON'))
        if type(off) is bool and type(on) is bool:
            deltas.append(int(on) - int(off))
            gains += int(on and not off)
            losses += int(off and not on)
    interval = None
    if deltas:
        rng = random.Random('trimem/lcb-paired-bootstrap/v1')
        samples = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(10000))
        interval = [samples[249], samples[9749]]
    effective_rows = {(row['task_id'], row['arm']): row['resolved'] for row in results}
    effective_deltas = [int(effective_rows[(identity, 'ON')]) - int(effective_rows[(identity, 'OFF')])
        for identity in split['pilot_ids']
        if type(effective_rows.get((identity, 'ON'))) is bool and type(effective_rows.get((identity, 'OFF'))) is bool]
    complete = all(arms[arm]['resolved_outcomes'] == arms[arm]['planned'] for arm in arms)
    return {'schema': SCHEMA, 'experiment_id': config['experiment_id'],
        'status': 'COMPLETE' if complete else 'INCOMPLETE', 'private_grading_ready': private_ready,
        'label': config.get('report_label', 'Development pilot with public repair; not leaderboard single-generation scoring'),
        'arms': arms, 'paired': {'planned': len(split['pilot_ids']), 'completed': len(deltas),
            'pending': len(split['pilot_ids']) - len(deltas), 'off_fail_on_pass': gains, 'off_pass_on_fail': losses,
            'delta': sum(deltas) / len(deltas) if len(deltas) == len(split['pilot_ids']) else None,
            'paired_complete_delta_descriptive': sum(deltas) / len(deltas) if deltas else None,
            'exploratory_paired_complete_bootstrap_95pct': interval, 'bootstrap_samples': 10000,
            'bootstrap_seed': 'trimem/lcb-paired-bootstrap/v1'},
        'effective_paired': {'planned': len(split['pilot_ids']), 'completed': len(effective_deltas),
            'pending': len(split['pilot_ids']) - len(effective_deltas),
            'delta': sum(effective_deltas) / len(effective_deltas) if len(effective_deltas) == len(split['pilot_ids']) else None},
        'bank': bank, 'manager_seconds_this_invocation': manager_seconds,
        'hidden_feedback_to_model': False, 'test_partition_model_calls': 0,
        'cells': results}


def run_experiment(config_path, runtime_path, dataset_root, output):
    started = time.monotonic()
    output = Path(output).resolve()
    dataset_root = Path(dataset_root).resolve()
    with exclusive_lock(output):
        config, runtime, split, public_manifest, tasks, frozen = load_inputs(config_path, runtime_path, dataset_root)
        frozen_path = output / 'frozen-inputs.json'
        if frozen_path.exists():
            if read(frozen_path) != frozen:
                raise FrozenInputChanged('Resumed experiment inputs differ')
        else:
            if any(output.iterdir()) and any(path.name != 'experiment.lock' for path in output.iterdir()):
                raise ExperimentError('Unrecognized preexisting experiment output')
            write(frozen_path, frozen)
        verify_frozen(frozen)
        memory.initialize_training_memory(output / 'training-memory', org_id=config['org_id'],
            owner_user_id=config['owner_user_id'], tasks=tasks.values())
        results, bank = [], None

        def checkpoint(private_ready=False):
            value = summarize(config, split, results, bank, private_ready=private_ready,
                manager_seconds=time.monotonic() - started)
            write(output / 'summary.json', value)
            return value

        # Batches bound simultaneous model sessions; captures remain ordered and serial.
        def batch(jobs, bank_argument):
            for offset in range(0, len(jobs), config.get('workers', 2)):
                verify_frozen(frozen)
                current = jobs[offset:offset + config.get('workers', 2)]
                with ThreadPoolExecutor(max_workers=config.get('workers', 2)) as pool:
                    futures = [pool.submit(collect_cell, output, tasks[identity], arm, runtime, bank_argument, frozen)
                        for identity, arm in current]
                    rows = [future.result() for future in futures]
                for (identity, arm), row in zip(current, rows):
                    if arm == 'TRAIN':
                        row = capture_cell(output, tasks[identity], row, runtime)
                    results.append(row)
                checkpoint()

        batch([(identity, 'TRAIN') for identity in split['train_pilot_ids']], None)
        verify_frozen(frozen)
        bank = freeze_bank(output)
        verify_bank_cohort(bank, results, runtime)
        # Alternate which arm starts first without changing task enrollment.
        jobs = []
        for index, identity in enumerate(split['pilot_ids']):
            jobs.extend((identity, arm) for arm in (('OFF', 'ON') if index % 2 == 0 else ('ON', 'OFF')))
        for offset in range(0, len(jobs), config.get('workers', 2)):
            verify_frozen(frozen)
            current = jobs[offset:offset + config.get('workers', 2)]
            with ThreadPoolExecutor(max_workers=config.get('workers', 2)) as pool:
                futures = [pool.submit(collect_cell, output, tasks[identity], arm, runtime,
                    bank if arm == 'ON' else None, frozen) for identity, arm in current]
                results.extend(future.result() for future in futures)
            checkpoint()
        verify_frozen(frozen)
        manifest = final_manifest(config, split, public_manifest, dataset_root, output)
        if manifest is not None:
            # All generation is over before any hidden evaluation is opened.
            for index, row in enumerate(results):
                verify_frozen(frozen)
                results[index] = grade_cell(output, row['task_id'], row['arm'], row,
                    manifest, dataset_root, runtime, config)
                checkpoint(private_ready=True)
        return checkpoint(private_ready=manifest is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run'])
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--dataset-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_experiment(args.config, args.runtime, args.dataset_root, args.output)
        print(json.dumps({'schema': SCHEMA, 'status': result['status'], 'arms': result['arms'],
            'paired': result['paired'], 'summary_reference': reference(args.output / 'summary.json')}, sort_keys=True))
        return 0 if result['status'] == 'COMPLETE' else 2
    except Exception as exc:
        # Never stringify exceptions originating from task, memory, or private data.
        print(json.dumps({'schema': SCHEMA, 'status': 'ERROR', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
