"""Exploratory grading of fixed, unsubmitted candidates after primary completion.

No models, repairs, primary writes, memory writes, or hidden-result selection.
This file is deliberately outside the running pilot's frozen implementation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = 'trimem/lcb-missing-submission-diagnostic/1.0'
POLICY = 'last-valid-rejected-finish-else-last-public-candidate/v1'
UPSTREAM_COMMIT = '28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24'


class DiagnosticError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path), 'bytes': path.stat().st_size}


def write_new(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(canonical(value))


def validate_reference(path, ref):
    path = Path(path).resolve()
    if (not path.is_file() or file_hash(path) != ref.get('sha256') or
            ('bytes' in ref and path.stat().st_size != ref['bytes'])):
        raise DiagnosticError('REFERENCE_CHANGED')
    return path


def relative_reference(root, ref):
    relative = Path(ref['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise DiagnosticError('REFERENCE_ESCAPES_ROOT')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise DiagnosticError('REFERENCE_ESCAPES_ROOT')
    return validate_reference(path, ref)


def mapped_path(path, runtime):
    value = str(Path(path).resolve()).replace('\\', '/')
    for item in runtime.get('execution_path_remap', []):
        source = item['from'].rstrip('/').replace('\\', '/')
        if value.casefold() == source.casefold() or value.casefold().startswith(source.casefold() + '/'):
            return item['to'].rstrip('/') + value[len(source):]
    return value


@contextmanager
def primary_lock(path):
    # Lock the existing manager byte without writing primary file contents.
    with Path(path).open('r+b') as stream:
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DiagnosticError('PRIMARY_MANAGER_STILL_ACTIVE') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def eligible(row):
    return (row.get('status') == 'GENERATION_ERROR' and row.get('error_type') == 'MissingSubmission' and
        row.get('outcome') == 'MODEL_PROTOCOL_FAILURE' and row.get('resolved') is False and
        row.get('passed') is None and row.get('grade_status') == 'GENERATION_ERROR')


def select_candidate(state):
    """Return exact existing bytes plus metadata; never compile or inspect grades."""
    limit = state.get('limits', {}).get('code_bytes')
    if type(limit) is not int or limit < 1:
        raise DiagnosticError('MISSING_FROZEN_CODE_LIMIT')

    def valid(code):
        return isinstance(code, str) and bool(code.strip()) and len(code.encode('utf-8')) <= limit

    rejected = state.get('rejected_actions', [])
    if not isinstance(rejected, list):
        raise DiagnosticError('MALFORMED_REJECTION_TRACE')
    prior = 0
    for item in rejected:
        if not isinstance(item, dict) or type(item.get('step')) is not int or item['step'] <= prior:
            raise DiagnosticError('MALFORMED_REJECTION_ORDER')
        prior = item['step']
    for index in reversed(range(len(rejected))):
        item = rejected[index]
        request = item.get('request', {})
        if not isinstance(request, dict) or request.get('tool') != 'finish':
            continue
        arguments = request.get('arguments', {})
        if isinstance(arguments, dict) and valid(arguments.get('code')):
            code = arguments['code']
            return code, {'selection_status': 'SELECTED', 'selection_source': 'REJECTED_FINISH',
                'selection_path': 'state.rejected_actions[%d].request.arguments.code' % index,
                'selection_step': item['step'], 'candidate_sha256': sha(code.encode()),
                'candidate_bytes': len(code.encode())}
    code = state.get('candidate')
    if not valid(code):
        return None, {'selection_status': 'SKIPPED_NO_CANDIDATE', 'selection_source': None,
            'selection_path': None, 'candidate_sha256': None, 'candidate_bytes': 0}
    # Native stores candidate before dispatching the public runner. A successful
    # recorded tool call (PASS, FAIL, or INFRA_ERROR) corroborates actual dispatch.
    tests = [event for event in state.get('history', []) if isinstance(event, dict) and
        event.get('tool') == 'run_public_tests' and event.get('status') == 'success']
    if not tests:
        return None, {'selection_status': 'SKIPPED_UNVERIFIED_PUBLIC_CANDIDATE',
            'selection_source': 'STATE_CANDIDATE', 'selection_path': 'state.candidate',
            'candidate_sha256': sha(code.encode()), 'candidate_bytes': len(code.encode())}
    last = tests[-1]
    request, result = last.get('request_payload', {}), last.get('result_payload', {})
    if (request.get('arguments', {}).get('code') != code or
            result.get('candidate_sha256') != sha(code.encode()) or
            result.get('public_tests_sha256') != state.get('task', {}).get('public_tests_sha256') or
            result.get('status') not in ('PASS', 'FAIL', 'INFRA_ERROR')):
        return None, {'selection_status': 'SKIPPED_UNVERIFIED_PUBLIC_CANDIDATE',
            'selection_source': 'STATE_CANDIDATE', 'selection_path': 'state.candidate',
            'candidate_sha256': sha(code.encode()), 'candidate_bytes': len(code.encode())}
    for key, payload in (('request', request), ('result', result)):
        raw = canonical(payload)[:-1]  # Core public trace hashes deliberately have no LF.
        if last.get(key) != {'sha256': sha(raw), 'bytes': len(raw)}:
            raise DiagnosticError('PUBLIC_TRACE_REFERENCE_CHANGED')
    return code, {'selection_status': 'SELECTED', 'selection_source': 'STATE_PUBLIC_CANDIDATE',
        'selection_path': 'state.candidate', 'selection_step': last.get('step_no'),
        'candidate_sha256': sha(code.encode()), 'candidate_bytes': len(code.encode())}


def cell_name(task_id, arm):
    prefix = 'train' if arm == 'TRAIN' else 'valid-' + arm.lower()
    return prefix + '-' + sha(task_id.encode())[:20]


def require_complete(pilot_root):
    summary = read(Path(pilot_root) / 'summary.json')
    if summary.get('status') != 'COMPLETE':
        raise DiagnosticError('PILOT_NOT_COMPLETE')
    if summary.get('schema') != 'trimem/lcb-experiment/1.0' or summary.get('private_grading_ready') is not True:
        raise DiagnosticError('PRIMARY_AUTHORITY_INCOMPLETE')
    return summary


def freeze_selection(pilot_root, runtime_path):
    pilot_root = Path(pilot_root).resolve()
    summary = require_complete(pilot_root)  # Gate precedes state or dataset access.
    frozen = read(pilot_root / 'frozen-inputs.json')
    if summary.get('experiment_id') != frozen.get('experiment_id'):
        raise DiagnosticError('PRIMARY_EXPERIMENT_ID_CHANGED')
    runtime_path = Path(runtime_path).resolve()
    runtime_refs = [ref for ref in frozen['references'] if Path(ref['path']).resolve() == runtime_path]
    if len(runtime_refs) != 1:
        raise DiagnosticError('RUNTIME_NOT_FROZEN')
    validate_reference(runtime_path, runtime_refs[0])
    runtime = read(runtime_path)
    if (runtime['native']['model'] != frozen['model'] or
            runtime['native']['reasoning_effort'] != frozen['reasoning_effort']):
        raise DiagnosticError('RUNTIME_MODEL_CHANGED')
    refs = [reference(pilot_root / name) for name in ('summary.json', 'frozen-inputs.json')]
    for ref in frozen['references']:
        validate_reference(ref['path'], ref)
        refs.append(dict(ref))
    bank_ref = summary.get('bank')
    if not isinstance(bank_ref, dict):
        raise DiagnosticError('PRIMARY_FROZEN_BANK_MISSING')
    bank_path = validate_reference(bank_ref['path'], bank_ref)
    if not bank_path.is_relative_to(pilot_root):
        raise DiagnosticError('PRIMARY_BANK_ESCAPES_PILOT')
    bank_manifest = read(bank_path)
    data_name = bank_manifest.get('data_directory')
    if (not isinstance(data_name, str) or Path(data_name).name != data_name or
            data_name in ('.', '..') or '\\' in data_name):
        raise DiagnosticError('PRIMARY_BANK_DATA_PATH_INVALID')
    bank_data = bank_path.parent / data_name
    refs.append(reference(bank_path))
    bank_evidence = [bank_manifest['authority']]
    for kind in ('captures', 'observations'):
        bank_evidence.extend(bank_manifest['catalog'][kind].values())
    for evidence in bank_evidence:
        refs.append(reference(relative_reference(bank_data, evidence)))
    expected = {(identity, 'TRAIN') for identity in frozen['enrollment']['train']}
    expected.update((identity, arm) for identity in frozen['enrollment']['valid'] for arm in ('OFF', 'ON'))
    rows = summary.get('cells', [])
    actual = [(row.get('task_id'), row.get('arm')) for row in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise DiagnosticError('PRIMARY_ENROLLMENT_CHANGED')
    plans, candidates = [], {}
    for row in rows:
        if not eligible(row):
            continue
        identity, arm = row['task_id'], row['arm']
        name = cell_name(identity, arm)
        cell = pilot_root / 'cells' / name
        cell_path, solve_path, state_path = (cell / name for name in ('cell-receipt.json', 'solve-receipt.json', 'state.json'))
        saved, solve = read(cell_path), read(solve_path)
        for key in ('task_id', 'arm', 'status', 'error_type', 'grade_status', 'passed', 'candidate_sha256', 'solve_reference'):
            if saved.get(key) != row.get(key):
                raise DiagnosticError('PRIMARY_CELL_RECEIPT_CHANGED')
        if (Path(row['solve_reference']['path']).resolve() != solve_path.resolve() or
                solve.get('schema') != 'trimem/lcb-solve-receipt/1.0' or
                solve.get('task_id') != identity or solve.get('arm') != arm or
                solve.get('status') != 'GENERATION_ERROR' or solve.get('error_type') != 'MissingSubmission'):
            raise DiagnosticError('PRIMARY_SOLVE_IDENTITY_CHANGED')
        validate_reference(solve_path, row['solve_reference'])
        if file_hash(state_path) != solve.get('state_sha256'):
            raise DiagnosticError('PRIMARY_STATE_CHANGED')
        state = read(state_path)
        if (state.get('task', {}).get('task_id') != identity or state.get('arm') != arm or
                state.get('finished') is not False or state.get('runtime') != runtime or
                state.get('limits') != frozen['limits'] or
                sha(state.get('candidate', '').encode()) != solve.get('candidate_sha256') or
                (arm != 'ON' and state.get('bank') is not None) or
                (arm == 'ON' and state.get('bank') != summary.get('bank'))):
            raise DiagnosticError('PRIMARY_STATE_IDENTITY_CHANGED')
        code, selection = select_candidate(state)
        plan = {'task_id': identity, 'arm': arm, 'cell_key': name,
            'primary_status': 'GENERATION_ERROR', 'primary_error_type': 'MissingSubmission',
            'primary_outcome': 'MODEL_PROTOCOL_FAILURE', 'primary_resolved': False,
            'primary_passed': None, **selection, 'state_reference': reference(state_path),
            'solve_reference': reference(solve_path), 'cell_reference': reference(cell_path)}
        plans.append(plan)
        refs.extend(plan[key] for key in ('state_reference', 'solve_reference', 'cell_reference'))
        if code is not None:
            candidates[name] = code
    return {'schema': SCHEMA, 'selection_policy': POLICY, 'experiment_id': summary['experiment_id'],
        'model': frozen['model'], 'reasoning_effort': frozen['reasoning_effort'],
        'primary_summary_reference': reference(pilot_root / 'summary.json'),
        'primary_enrolled_cells': len(rows), 'eligible_missing_submission_cells': len(plans),
        'selected_candidates': len(candidates), 'helper_reference': reference(__file__),
        'rows': plans, 'model_calls': 0, 'primary_writes': 0, 'memory_writes': 0}, candidates, runtime, frozen, refs + [reference(__file__)]


def load_dataset_authority(pilot_root, frozen):
    dataset_root = Path(frozen['dataset_root']).resolve()
    authority_path = Path(pilot_root) / 'private-dataset-receipt.json'
    authority = read(authority_path)
    for ref in authority.values():
        validate_reference(ref['path'], ref)
    manifest_path = dataset_root / 'dataset-manifest.json'
    if Path(authority['manifest']['path']).resolve() != manifest_path:
        raise DiagnosticError('DATASET_ROOT_CHANGED')
    manifest = read(manifest_path)
    ready = read(authority['ready']['path'])
    if (manifest.get('schema') != 'trimem/lcb-dataset/1.0' or
            ready.get('schema') != 'trimem/lcb-dataset-ready/1.0' or ready.get('status') != 'READY' or
            ready.get('identities_verified') is not True or
            relative_reference(dataset_root, ready['manifest_reference']) != manifest_path):
        raise DiagnosticError('DATASET_NOT_READY')
    # The primary run enrolled the public split before private export finished.
    # Bind final authority back to those original frozen metadata bytes.
    public_splits, public_manifests = [], []
    for ref in frozen['references']:
        path = Path(ref['path'])
        if path.suffix.lower() != '.json':
            continue
        value = read(validate_reference(path, ref))
        if value.get('schema') == 'trimem/lcb-split/1.0':
            public_splits.append((path.resolve(), value))
        elif value.get('schema') in ('trimem/lcb-public-dataset/1.0', 'trimem/lcb-dataset/1.0'):
            public_manifests.append((path.resolve(), value))
    if len(public_splits) != 1 or len(public_manifests) != 1:
        raise DiagnosticError('FROZEN_PUBLIC_AUTHORITY_AMBIGUOUS')
    public_split_path, public_split = public_splits[0]
    public_manifest_path, public_manifest = public_manifests[0]
    final_split = read(authority['split']['path'])
    lineage_keys = ('dataset_id', 'revision', 'release', 'task_count', 'source_files', 'public_tasks_reference', 'counts')
    split_keys = ('dataset_id', 'source_revision', 'release', 'split_policy', 'pilot_policy',
        'train_ids', 'valid_ids', 'test_ids', 'pilot_ids', 'train_pilot_ids', 'counts',
        'task_descriptors', 'task_families', 'family_reassignments', 'pilot_difficulty_counts',
        'train_pilot_difficulty_counts', 'source_hashes', 'public_tasks_reference')
    if (any(manifest.get(key) != public_manifest.get(key) for key in lineage_keys) or
            any(final_split.get(key) != public_split.get(key) for key in split_keys) or
            public_split.get('train_pilot_ids') != frozen['enrollment']['train'] or
            public_split.get('pilot_ids') != frozen['enrollment']['valid'] or
            relative_reference(dataset_root, public_split['dataset_reference']) != public_manifest_path or
            relative_reference(dataset_root, final_split['dataset_reference']) != manifest_path or
            ready.get('public_split_reference', {}).get('sha256') != file_hash(public_split_path) or
            ready.get('split_reference', {}).get('sha256') != authority['split']['sha256']):
        raise DiagnosticError('PRIVATE_DATASET_DIFFERS_FROM_FROZEN_PUBLIC_LINEAGE')
    relative_reference(dataset_root, manifest['public_tasks_reference'])
    return dataset_root, manifest, [reference(authority_path), *authority.values()]


def validate_grade(report, plan, prediction_ref, sample_ref, settings):
    rows = report.get('results', [])
    if (report.get('schema') != 'trimem/lcb-grade-report/1.0' or len(rows) != 1 or
            rows[0].get('question_id') != plan['task_id']):
        raise DiagnosticError('GRADER_RESULT_IDENTITY_CHANGED')
    row, provenance = rows[0], report.get('provenance', {})
    if (provenance.get('upstream_commit') != UPSTREAM_COMMIT or
            provenance.get('predictions_reference', {}).get('sha256') != prediction_ref['sha256'] or
            provenance.get('dataset_reference', {}).get('sha256') != sample_ref['sha256'] or
            report.get('settings', {}).get('timeout_seconds') != settings['timeout'] or
            report.get('settings', {}).get('workers') != settings['workers'] or
            report.get('settings', {}).get('generations_per_question') != 1 or
            report.get('settings', {}).get('extraction_style') != 'OpenAIChat' or
            report.get('cohort_scope') != 'DECLARED_EXPECTED_IDS' or
            report.get('counts', {}).get('planned') != 1):
        raise DiagnosticError('GRADER_PROVENANCE_CHANGED')
    status, passed = row.get('status'), row.get('passed')
    if status == 'GRADED':
        if (type(passed) is not bool or report.get('status') != 'COMPLETE' or
                row.get('extracted_code_sha256') != plan['candidate_sha256'] or
                report.get('counts', {}).get('graded') != 1 or
                report.get('counts', {}).get('passed') != int(passed)):
            raise DiagnosticError('GRADER_VERDICT_CHANGED')
    elif status in ('GRADER_ERROR', 'NOT_GRADED'):
        if passed is not None or report.get('status') != 'INCOMPLETE':
            raise DiagnosticError('UNRESOLVED_GRADER_CLAIMS_VERDICT')
    else:
        raise DiagnosticError('UNEXPECTED_GRADER_STATUS')
    return {'diagnostic_grade_status': status, 'diagnostic_passed': passed,
        'official_extracted_code_sha256': row.get('extracted_code_sha256'),
        'grade_error_type': row.get('error_type') if status != 'GRADED' else None,
        'grader_counts': report['counts'], 'grader_seconds': report.get('timings', {}).get('overall_seconds')}


def grade_selected(plan, code, output, dataset_root, manifest, runtime):
    directory = Path(output) / plan['cell_key']
    directory.mkdir()
    result = {**plan, 'diagnostic_grade_status': 'GRADER_ERROR', 'diagnostic_passed': None}
    started = time.monotonic()
    try:
        pinned_sample = manifest['private_evaluation_files'][plan['task_id']]
        source = relative_reference(dataset_root, pinned_sample)
        if pinned_sample.get('format') != 'gzip-json':
            raise DiagnosticError('UNSUPPORTED_SAMPLE_FORMAT')
        (directory / 'candidate.py').write_bytes(code.encode('utf-8'))
        sample_path = directory / 'evaluation.json.gz'
        shutil.copyfile(source, sample_path)  # Opaque copy; official grader decodes it.
        sample_ref = reference(sample_path)
        if sample_ref['sha256'] != pinned_sample['sha256']:
            raise DiagnosticError('COPIED_SAMPLE_CHANGED')
        raw_output = '```python\n' + code + '\n```'
        lines = raw_output.split('\n')
        fences = [index for index, line in enumerate(lines) if '```' in line]
        if '\n'.join(lines[fences[-2] + 1:fences[-1]]) != code:
            raise DiagnosticError('OFFICIAL_EXTRACTION_WOULD_CHANGE_CANDIDATE')
        prediction_path = directory / 'predictions.json'
        write_new(prediction_path, {'schema': 'trimem/lcb-predictions/1.0', 'expected_question_ids': [plan['task_id']],
            'model': runtime['native']['model'], 'predictions': [{'question_id': plan['task_id'], 'output': raw_output}]})
        prediction_ref = reference(prediction_path)
        settings = {'timeout': 6, 'workers': 1}
        report_path = directory / 'official-report.json'
        execution = runtime['execution']
        command = [*execution.get('prefix', []), execution['python'],
            execution['scripts_root'].rstrip('/') + '/trimem_lcb_grade.py',
            '--predictions', mapped_path(prediction_path, runtime), '--dataset-json', mapped_path(sample_path, runtime),
            '--dataset-sha256', sample_ref['sha256'], '--official-repo', execution['official_repo'],
            '--output', mapped_path(report_path, runtime), '--workers', str(settings['workers']),
            '--timeout', str(settings['timeout'])]
        env = {key: value for key, value in os.environ.items() if key not in ('OPENAI_API_KEY', 'CODEX_API_KEY')}
        process = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=1800,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result['transport'] = {'returncode': process.returncode,
            'stdout_sha256': sha(process.stdout), 'stderr_sha256': sha(process.stderr)}
        if process.returncode not in (0, 2) or not report_path.is_file():
            raise DiagnosticError('GRADER_TRANSPORT_FAILED')
        validate_reference(sample_path, sample_ref)
        validate_reference(prediction_path, prediction_ref)
        report = read(report_path)
        verdict = validate_grade(report, plan, prediction_ref, sample_ref, settings)
        if (process.returncode == 0) != (report.get('status') == 'COMPLETE'):
            raise DiagnosticError('GRADER_EXIT_STATUS_DIFFERS')
        result.update(verdict, official_report_reference=reference(report_path),
            predictions_reference=prediction_ref, evaluation_reference=sample_ref)
    except Exception as exc:
        result.update(diagnostic_grade_status='GRADER_ERROR', diagnostic_passed=None,
            grade_error_type=type(exc).__name__)
    result['wall_seconds'] = time.monotonic() - started
    write_new(directory / 'diagnostic-receipt.json', result)
    return result


def run(pilot_root, runtime_path, output, report_path, *, repo_root=ROOT):
    repo_root = Path(repo_root).resolve()
    pilot_root, output, report_path = (Path(path).resolve() for path in (pilot_root, output, report_path))
    scope = repo_root / 'data' / 'skhynix_lcb_002'
    artifacts = repo_root / 'artifacts' / 'skhynix_v1' / 'lcb_002'
    if (pilot_root != scope / 'pilot-001' or output != scope / 'posthoc-001' or
            not report_path.is_relative_to(artifacts) or report_path.suffix != '.json'):
        raise DiagnosticError('OUTPUT_OR_PILOT_OUTSIDE_DECLARED_SCOPE')
    require_complete(pilot_root)  # No creation, state access, or private access before COMPLETE.
    if output.exists() or report_path.exists():
        raise DiagnosticError('FRESH_DIAGNOSTIC_OUTPUT_REQUIRED')
    with primary_lock(pilot_root / 'experiment.lock'):
        selection, candidates, runtime, frozen, guard_refs = freeze_selection(pilot_root, runtime_path)
        script_root = mapped_path(repo_root / 'scripts', runtime).replace('\\', '/').rstrip('/').casefold()
        if script_root != runtime['execution']['scripts_root'].replace('\\', '/').rstrip('/').casefold():
            raise DiagnosticError('GRADER_SOURCE_PATH_CHANGED')
        output.mkdir()
        # Every candidate is fixed and receipted before opening private authority.
        selection_path = output / 'selection-receipt.json'
        write_new(selection_path, selection)
        for ref in guard_refs:
            validate_reference(ref['path'], ref)
        dataset_root, manifest, private_refs = load_dataset_authority(pilot_root, frozen)
        guard_refs += private_refs
        rows = []
        for plan in selection['rows']:
            for ref in guard_refs:
                validate_reference(ref['path'], ref)
            if plan['cell_key'] not in candidates:
                rows.append({**plan, 'diagnostic_grade_status': 'SKIPPED', 'diagnostic_passed': None})
            else:
                rows.append(grade_selected(plan, candidates[plan['cell_key']], output,
                    dataset_root, manifest, runtime))
        for ref in guard_refs:
            validate_reference(ref['path'], ref)
        graded = sum(row['diagnostic_grade_status'] == 'GRADED' for row in rows)
        passed = sum(row['diagnostic_passed'] is True for row in rows)
        report = {'schema': SCHEMA, 'status': 'COMPLETE' if graded == len(rows) else 'INCOMPLETE',
            'label': 'EXPLORATORY_POSTHOC_UNSUBMITTED_CANDIDATES_NOT_PRIMARY_SCORE',
            'selection_policy': POLICY, 'experiment_id': selection['experiment_id'],
            'model': selection['model'], 'reasoning_effort': selection['reasoning_effort'],
            'primary_summary_reference': selection['primary_summary_reference'],
            'selection_reference': reference(selection_path), 'helper_reference': selection['helper_reference'],
            'counts': {'primary_enrolled': selection['primary_enrolled_cells'], 'eligible': len(rows),
                'selected': len(candidates), 'graded': graded, 'passed': passed, 'failed': graded - passed,
                'skipped': sum(row['diagnostic_grade_status'] == 'SKIPPED' for row in rows),
                'unresolved': len(rows) - graded},
            'eligible_candidate_pass_fraction': passed / len(rows) if rows and graded == len(rows) else None,
            'graded_candidate_pass_fraction_descriptive': passed / graded if graded else None,
            'model_calls': 0, 'candidate_generations': 0, 'candidate_modifications': 0,
            'hidden_result_based_selection': False, 'primary_writes': 0, 'memory_writes': 0, 'rows': rows}
        write_new(output / 'diagnostic-summary.json', report)
        write_new(report_path, report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run'])
    parser.add_argument('--pilot-root', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        value = run(args.pilot_root, args.runtime, args.output, args.report)
        print(json.dumps({'schema': SCHEMA, 'status': value['status'], 'counts': value['counts'],
            'report_reference': reference(args.report)}, sort_keys=True))
        return 0 if value['status'] == 'COMPLETE' else 2
    except Exception as exc:
        print(json.dumps({'schema': SCHEMA, 'status': 'ERROR', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
