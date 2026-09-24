"""Predeclared retained-candidate diagnostic, separate from primary outcomes.

Selection reads sealed public solver evidence only. All 48 selections are bound
before any private grading. This module never calls a model or writes a cell.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

SCHEMA = 'lcb-explicit-format-diagnostic/1'
POLICY = 'accepted-else-last-valid-rejected-finish-else-last-successful-public-request/1'
UPSTREAM_COMMIT = '28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24'
EXPECTED_CELLS = 48
CODE_BYTES = 65536


class DiagnosticError(ValueError):
    pass


class GraderTransportError(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise DiagnosticError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path), 'bytes': path.stat().st_size}


def check(ref, expected_path=None):
    path = Path(ref['path']).resolve()
    require(expected_path is None or path == Path(expected_path).resolve(), 'REFERENCE_PATH_CHANGED')
    actual = reference(path)
    require(actual['sha256'] == ref['sha256'] and ('bytes' not in ref or actual['bytes'] == ref['bytes']), 'REFERENCE_CHANGED')
    return path


def read(path):
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value))


def cell_name(task_id, arm):
    require(arm in ('OFF', 'ON'), 'NONVALID_ARM')
    return 'valid-' + arm.lower() + '-' + sha(task_id.encode())[:20]


def code_valid(code):
    if not isinstance(code, str) or not code.strip():
        return False
    try:
        return len(code.encode('utf-8')) <= CODE_BYTES
    except UnicodeEncodeError:
        return False


def ordered(rows, key, terminal_step):
    require(isinstance(rows, list), 'MALFORMED_PUBLIC_TRACE')
    steps = [r.get(key) if isinstance(r, dict) else None for r in rows]
    require(all(type(s) is int and 0 < s <= terminal_step for s in steps), 'FUTURE_OR_INVALID_TRACE_STEP')
    require(steps == sorted(set(steps)), 'TRACE_ORDER_CHANGED')


def source_choice(state, submitted):
    """Pure, grade-independent policy. Returned code must still be corroborated."""
    require(state.get('limits', {}).get('code_bytes') == CODE_BYTES, 'CODE_LIMIT_CHANGED')
    terminal_step = state.get('step')
    require(type(terminal_step) is int and terminal_step >= 0, 'INVALID_TERMINAL_STEP')
    history, rejected = state.get('history', []), state.get('rejected_actions', [])
    ordered(history, 'step_no', terminal_step)
    ordered(rejected, 'step', terminal_step)
    if submitted:
        code = state.get('candidate')
        require(state.get('finished') is True and code_valid(code), 'ACCEPTED_CANDIDATE_INVALID')
        return code, {'selection_status': 'SELECTED', 'selection_source': 'ACCEPTED_SUBMISSION', 'selection_step': terminal_step}
    for item in reversed(rejected):
        request = item.get('request')
        args = request.get('arguments') if isinstance(request, dict) else None
        if isinstance(args, dict) and request.get('tool') == 'finish' and code_valid(args.get('code')):
            return args['code'], {'selection_status': 'SELECTED', 'selection_source': 'REJECTED_FINISH', 'selection_step': item['step']}
    tests = [h for h in history if h.get('tool') == 'run_public_tests' and h.get('status') == 'success']
    if tests:
        event = tests[-1]
        request = event.get('request_payload', {})
        args = request.get('arguments') if isinstance(request, dict) else None
        require(isinstance(args, dict) and code_valid(args.get('code')), 'PUBLIC_CANDIDATE_INVALID')
        return args['code'], {'selection_status': 'SELECTED', 'selection_source': 'PUBLIC_TEST_REQUEST', 'selection_step': event['step_no']}
    return None, {'selection_status': 'NOT_AVAILABLE', 'selection_source': None, 'selection_step': None}


def request_from(item):
    envelope = item.get('arguments')
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    return envelope.get('request') if isinstance(envelope, dict) and set(envelope) == {'request'} else None


def response_from(item):
    content = item.get('result', {}).get('content', [])
    values = []
    for block in content:
        if block.get('type') == 'text':
            try:
                value = json.loads(block.get('text', ''))
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and 'step_no' in value:
                values.append(value)
    require(len(values) <= 1, 'AMBIGUOUS_BROKER_RESPONSE')
    return values[0] if values else None


def public_calls(cell, solve):
    calls, refs, numbers = [], [], []
    for session in solve.get('sessions', []):
        number = session.get('session')
        require(type(number) is int and number > 0, 'INVALID_SESSION_ID')
        numbers.append(number)
        folder = cell / ('session-%02d' % number)
        saved = read(folder / 'receipt.json')
        require(saved == session, 'SESSION_RECEIPT_CHANGED')
        for name, key in (('events.jsonl', 'events_sha256'), ('stderr.log', 'stderr_sha256')):
            ref = reference(folder / name)
            require(ref['sha256'] == session[key], 'SESSION_FILE_CHANGED')
            refs.append(ref)
        refs.append(reference(folder / 'receipt.json'))
        for line_no, raw in enumerate((folder / 'events.jsonl').read_bytes().splitlines(), 1):
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict) or event.get('type') != 'item.completed':
                continue
            item = event.get('item', {})
            if not isinstance(item, dict) or (item.get('type'), item.get('server'), item.get('tool')) != ('mcp_tool_call', 'benchmark', 'action'):
                continue
            response = response_from(item)
            if response is not None:
                calls.append({'request': request_from(item), 'response': response, 'session': number,
                              'event_line': line_no, 'event_sha256': sha(raw)})
    require(numbers == sorted(set(numbers)), 'SESSION_ORDER_CHANGED')
    return calls, refs


def select_candidate(cell_path, *, row):
    """Return (metadata, exact code or None), bound to original public receipts."""
    cell = Path(cell_path).resolve()
    solve = read(check(row['solve_reference'], cell / 'solve-receipt.json'))
    state_path = cell / 'state.json'
    require(file_hash(state_path) == solve['state_sha256'], 'STATE_CHANGED')
    state = read(state_path)
    require(solve.get('schema') == 'trimem/lcb-solve-receipt/1.0', 'SOLVE_SCHEMA_CHANGED')
    require(all(solve.get(k) == row.get(k) for k in ('task_id', 'arm', 'status', 'candidate_sha256')), 'SOLVE_ROW_CHANGED')
    require(solve['status'] in ('SUBMITTED', 'GENERATION_ERROR'), 'SOLVE_NOT_TERMINAL')
    require(state.get('task', {}).get('task_id') == row['task_id'] and state.get('arm') == row['arm'], 'STATE_IDENTITY_CHANGED')
    require(state['task'].get('split') == 'valid' and row['arm'] in ('OFF', 'ON'), 'TARGET_SCOPE_CHANGED')
    require(sha(state.get('candidate', '').encode()) == solve['candidate_sha256'], 'SOLVE_CANDIDATE_CHANGED')
    calls, refs = public_calls(cell, solve)
    code, choice = source_choice(state, solve['status'] == 'SUBMITTED')
    proof = None
    if code is not None:
        step = choice['selection_step']
        if choice['selection_source'] == 'ACCEPTED_SUBMISSION':
            matches = [c for c in calls if c['response'].get('status') == 'success'
                       and c['response'].get('result', {}).get('submitted') is True
                       and isinstance(c['request'], dict) and c['request'].get('tool') == 'finish'
                       and c['request'].get('arguments', {}).get('code') == code
                       and c['response'].get('result', {}).get('candidate_sha256') == sha(code.encode())]
        else:
            matches = [c for c in calls if c['response'].get('step_no') == step]
        require(len(matches) == 1, 'SELECTED_EVENT_NOT_UNIQUE')
        proof = matches[0]
        if choice['selection_source'] == 'REJECTED_FINISH':
            rejected = next(r for r in state['rejected_actions'] if r['step'] == step)
            require(proof['request'] == rejected['request'] and proof['response'].get('status') == 'error'
                    and proof['response'].get('result') == rejected['result'], 'REJECTED_FINISH_NOT_CORROBORATED')
        elif choice['selection_source'] == 'PUBLIC_TEST_REQUEST':
            event = next(h for h in state['history'] if h['step_no'] == step)
            request, result = event['request_payload'], event['result_payload']
            require(event.get('task_id') == row['task_id'] and event.get('arm') == ('PDF_MEMORY' if row['arm'] == 'ON' else 'BASELINE'), 'PUBLIC_TRACE_IDENTITY_CHANGED')
            for key, payload in (('request', request), ('result', result)):
                raw = canonical(payload)[:-1]
                require(event.get(key) == {'sha256': sha(raw), 'bytes': len(raw)}, 'PUBLIC_TRACE_HASH_CHANGED')
            require(proof['request'] == request and proof['response'].get('status') == 'success'
                    and proof['response'].get('result') == result, 'PUBLIC_REQUEST_NOT_CORROBORATED')
            require(result.get('candidate_sha256') == sha(code.encode())
                    and result.get('public_tests_sha256') == state['task']['public_tests_sha256']
                    and result.get('status') in ('PASS', 'FAIL', 'INFRA_ERROR'), 'PUBLIC_RESULT_IDENTITY_CHANGED')
        else:
            require(proof['response'].get('step_no') == step, 'ACCEPTED_STEP_CHANGED')
    refs.extend([reference(state_path), dict(row['solve_reference'])])
    for ref in refs:
        check(ref)
    metadata = {'task_id': row['task_id'], 'arm': row['arm'], 'cell_key': cell.name,
                'primary_generation_status': row['status'], 'primary_generation_error_type': row.get('error_type'),
                'generation_row_sha256': sha(canonical(row)), **choice,
                'candidate_sha256': sha(code.encode()) if code is not None else None,
                'candidate_bytes': len(code.encode()) if code is not None else 0,
                'source_references': refs,
                'selection_event': {k: proof[k] for k in ('session', 'event_line', 'event_sha256')} if proof else None}
    return metadata, code


def collection_guard(output, collection_reference, verify_collection):
    output = Path(output).resolve()
    collection = read(check(collection_reference, output / 'collection.json'))
    require(collection.get('schema') == 'lcb-explicit-format-collection/1' and collection.get('status') == 'COMPLETE'
            and collection.get('planned_cells') == collection.get('completed_cells') == EXPECTED_CELLS, 'COLLECTION_NOT_COMPLETE')
    rows = collection.get('rows', [])
    identities = {(r['task_id'], r['arm']) for r in rows}
    tasks = {r['task_id'] for r in rows}
    require(len(rows) == len(identities) == EXPECTED_CELLS and len(tasks) * 2 == EXPECTED_CELLS
            and identities == {(task, arm) for task in tasks for arm in ('OFF', 'ON')}, 'COLLECTION_COHORT_CHANGED')
    for ref in collection['source_references']:
        check(ref)
    check(collection['frozen_inputs_reference'])
    require(callable(verify_collection), 'COLLECTION_VERIFIER_REQUIRED')
    verified = verify_collection()
    require(verified is None or verified == collection, 'COLLECTION_VERIFIER_DISAGREEMENT')
    check(collection_reference)
    return collection


def selection_guard(output, manifest_reference, collection_reference):
    output = Path(output).resolve()
    manifest = read(check(manifest_reference, output / 'diagnostic-selection.json'))
    require(manifest.get('schema') == SCHEMA and manifest.get('selection_policy') == POLICY
            and manifest.get('selection_complete') is True and manifest.get('planned_cells') == EXPECTED_CELLS
            and manifest.get('collection_reference') == collection_reference, 'SELECTION_NOT_SEALED')
    check(manifest['helper_reference'], __file__)
    require(len(manifest['rows']) == EXPECTED_CELLS, 'SELECTION_COHORT_CHANGED')
    collection = read(check(collection_reference))
    expected = {(r['task_id'], r['arm']): sha(canonical(r)) for r in collection['rows']}
    require(len({(r['task_id'], r['arm']) for r in manifest['rows']}) == EXPECTED_CELLS, 'DUPLICATE_SELECTION')
    for row in manifest['rows']:
        require(expected.get((row['task_id'], row['arm'])) == row['generation_row_sha256'], 'SELECTION_GENERATION_CHANGED')
        require(row['cell_key'] == cell_name(row['task_id'], row['arm']), 'SELECTION_CELL_CHANGED')
        original = next(r for r in collection['rows'] if (r['task_id'], r['arm']) == (row['task_id'], row['arm']))
        derived, selected_code = select_candidate(output / 'cells' / row['cell_key'], row=original)
        require(all(row.get(k) == v for k, v in derived.items()), 'SELECTION_POLICY_CHANGED')
        for ref in row['source_references']:
            check(ref)
        if row['selection_status'] == 'SELECTED':
            record = read(check(row['candidate_reference'], output / 'diagnostic-candidates' / (row['cell_key'] + '.json')))
            require(record['task_id'] == row['task_id'] and record['arm'] == row['arm']
                    and record['code'] == selected_code and code_valid(record['code'])
                    and sha(record['code'].encode()) == row['candidate_sha256'], 'SEALED_CANDIDATE_CHANGED')
        else:
            require(row['selection_status'] == 'NOT_AVAILABLE' and row.get('candidate_reference') is None
                    and row['candidate_sha256'] is None, 'UNKNOWN_SELECTION_STATE')
    return manifest


def prepare_diagnostics(output, rows, *, collection_reference, verify_collection):
    output = Path(output).resolve()
    collection = collection_guard(output, collection_reference, verify_collection)
    require(rows == collection['rows'], 'COLLECTION_ROWS_CHANGED')
    path = output / 'diagnostic-selection.json'
    if path.exists():
        ref = reference(path)
        selection_guard(output, ref, collection_reference)
        return ref
    require(not (output / 'private-grades').exists() and not (output / 'diagnostic-grades').exists(), 'SELECTION_MUST_PRECEDE_PRIVATE_GRADING')
    folder = output / 'diagnostic-candidates'
    require(not folder.exists(), 'PARTIAL_SELECTION_NO_REWRITE')
    selected = []
    enrolled = {str(Path(r['path']).resolve()): r for r in collection['source_references']}
    for row in rows:
        require(row.get('passed') is None and row.get('grade_status') in ('PENDING', 'GENERATION_ERROR', 'NOT_GRADED'), 'SELECTION_SAW_PRIVATE_VERDICT')
        name = cell_name(row['task_id'], row['arm'])
        metadata, code = select_candidate(output / 'cells' / name, row=row)
        require(all(enrolled.get(str(Path(r['path']).resolve())) == r for r in metadata['source_references']), 'SELECTION_SOURCE_NOT_IN_COLLECTION')
        selected.append((metadata, code))
    collection_guard(output, collection_reference, verify_collection)
    folder.mkdir()
    (folder / '.gitignore').write_text('*\n', encoding='utf-8')
    plans = []
    for metadata, code in selected:
        if code is not None:
            candidate_path = folder / (metadata['cell_key'] + '.json')
            write_new(candidate_path, {'task_id': metadata['task_id'], 'arm': metadata['arm'], 'code': code})
            metadata['candidate_reference'] = reference(candidate_path)
        else:
            metadata['candidate_reference'] = None
        plans.append(metadata)
    manifest = {'schema': SCHEMA, 'selection_policy': POLICY, 'selection_complete': True,
                'planned_cells': EXPECTED_CELLS, 'collection_reference': collection_reference,
                'helper_reference': reference(__file__), 'selected_candidates': sum(r['selection_status'] == 'SELECTED' for r in plans),
                'private_grader_calls_before_selection': 0, 'model_calls': 0, 'original_cell_writes': 0,
                'hidden_result_based_selection': False, 'rows': plans}
    write_new(path, manifest)
    ref = reference(path)
    selection_guard(output, ref, collection_reference)
    return ref


def private_source(dataset_root, manifest, task_id):
    root = Path(dataset_root).resolve()
    ref = manifest['private_evaluation_files'][task_id]
    part = Path(ref['path'])
    require(not part.is_absolute() and '..' not in part.parts and ref.get('format') == 'gzip-json', 'PRIVATE_SOURCE_PATH_INVALID')
    path = (root / part).resolve()
    require(path.is_relative_to(root), 'PRIVATE_SOURCE_ESCAPES_ROOT')
    actual = reference(path)
    require(actual['sha256'] == ref['sha256'] and ('bytes' not in ref or actual['bytes'] == ref['bytes']), 'PRIVATE_SOURCE_CHANGED')
    return path


def expected_prediction(plan, code, runtime):
    wrapped = '```python\n' + code + '\n```'
    lines = wrapped.split('\n')
    fences = [i for i, line in enumerate(lines) if '```' in line]
    require(len(fences) >= 2 and '\n'.join(lines[fences[-2] + 1:fences[-1]]) == code, 'OFFICIAL_EXTRACTION_WOULD_CHANGE_CODE')
    return {'schema': 'trimem/lcb-predictions/1.0', 'expected_question_ids': [plan['task_id']],
            'model': runtime['native']['model'], 'predictions': [{'question_id': plan['task_id'], 'output': wrapped}]}


def validate_grade(report, plan, prediction_ref, sample_ref, config):
    settings = config.get('private_grading', {})
    rows, provenance = report.get('results', []), report.get('provenance', {})
    require(report.get('schema') == 'trimem/lcb-grade-report/1.0' and len(rows) == 1
            and rows[0].get('question_id') == plan['task_id'], 'GRADE_IDENTITY_CHANGED')
    require(provenance.get('upstream_commit') == UPSTREAM_COMMIT
            and provenance.get('predictions_reference', {}).get('sha256') == prediction_ref['sha256']
            and provenance.get('dataset_reference', {}).get('sha256') == sample_ref['sha256'], 'GRADE_PROVENANCE_CHANGED')
    require(report.get('settings', {}).get('timeout_seconds') == settings.get('timeout_seconds_per_case', 6)
            and report.get('settings', {}).get('workers') == settings.get('workers_per_cell', 1)
            and report.get('settings', {}).get('generations_per_question') == 1
            and report.get('settings', {}).get('extraction_style') == 'OpenAIChat'
            and report.get('cohort_scope') == 'DECLARED_EXPECTED_IDS'
            and report.get('counts', {}).get('planned') == 1, 'GRADE_SETTINGS_CHANGED')
    row = rows[0]
    status, passed = row.get('status'), row.get('passed')
    if status == 'GRADED':
        require(type(passed) is bool and report.get('status') == 'COMPLETE'
                and row.get('extracted_code_sha256') == plan['candidate_sha256']
                and report['counts'].get('graded') == 1 and report['counts'].get('passed') == int(passed), 'GRADE_VERDICT_CHANGED')
    else:
        require(status in ('GENERATION_ERROR', 'GRADER_ERROR', 'NOT_GRADED') and passed is None
                and report.get('status') == 'INCOMPLETE', 'UNGRADED_VERDICT_CLAIM')
    return {'diagnostic_grade_status': status, 'diagnostic_passed': passed}


def decompressed_hash(path):
    value = hashlib.sha256()
    with gzip.open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def dataset_guard(output, dataset_manifest, dataset_root):
    path = Path(output) / 'private-dataset-receipt.json'
    authority = read(path)
    require(set(authority) == {'manifest', 'split', 'ready'}, 'PRIVATE_AUTHORITY_CHANGED')
    check(authority['manifest'], Path(dataset_root) / 'dataset-manifest.json')
    require(read(authority['manifest']['path']) == dataset_manifest, 'PRIVATE_MANIFEST_ARGUMENT_CHANGED')
    for ref in authority.values():
        check(ref)
    return [reference(path), *authority.values()]


def reuse_primary(output, plan, primary, dataset_manifest, dataset_root, runtime, config):
    require(primary.get('status') == 'SUBMITTED' and primary.get('candidate_sha256') == plan['candidate_sha256'], 'PRIMARY_CANDIDATE_CHANGED')
    cell_receipt = Path(output) / 'cells' / plan['cell_key'] / 'cell-receipt.json'
    require(read(cell_receipt) == primary, 'PRIMARY_ROW_CHANGED')
    if 'grade_reference' not in primary:
        require(primary.get('passed') is None and primary.get('grade_status') in ('GRADER_ERROR', 'NOT_GRADED'), 'PRIMARY_GRADE_EVIDENCE_MISSING')
        return {'diagnostic_grade_status': primary['grade_status'], 'diagnostic_passed': None,
                'grade_source': 'PRIMARY_REUSED', 'primary_row_sha256': sha(canonical(primary)),
                'primary_cell_reference': reference(cell_receipt)}
    directory = Path(output) / 'private-grades' / plan['cell_key']
    report_path = check(primary['grade_reference'], directory / 'report.json')
    code = read(check(plan['candidate_reference']))['code']
    prediction = expected_prediction(plan, code, runtime)
    prediction_ref, sample_ref = reference(directory / 'predictions.json'), reference(directory / 'evaluation.json')
    require(prediction_ref['sha256'] == sha(canonical(prediction)), 'PRIMARY_PREDICTION_CHANGED')
    source = private_source(dataset_root, dataset_manifest, plan['task_id'])
    require(sample_ref['sha256'] == decompressed_hash(source), 'PRIMARY_SAMPLE_CHANGED')
    verdict = validate_grade(read(report_path), plan, prediction_ref, sample_ref, config)
    require(primary.get('grade_status') == verdict['diagnostic_grade_status'] and primary.get('passed') is verdict['diagnostic_passed'], 'PRIMARY_VERDICT_CHANGED')
    return {**verdict, 'grade_source': 'PRIMARY_REUSED', 'official_report_reference': primary['grade_reference'],
            'primary_row_sha256': sha(canonical(primary)), 'primary_cell_reference': reference(cell_receipt),
            'predictions_reference': prediction_ref, 'evaluation_reference': sample_ref}


def grade_selected(output, plan, dataset_manifest, dataset_root, runtime, config):
    """Exactly one official grading attempt per sealed missing-submission code."""
    from trimem_lcb_native import execution_command, mapped_path
    directory = Path(output) / 'diagnostic-grades' / plan['cell_key']
    receipt_path = directory / 'diagnostic-receipt.json'
    if directory.exists():
        require(receipt_path.is_file(), 'PARTIAL_DIAGNOSTIC_NO_RETRY')
        saved = read(receipt_path)
        require(saved['selection_row_sha256'] == sha(canonical(plan)), 'DIAGNOSTIC_SELECTION_CHANGED')
        for ref in saved.get('references', []):
            check(ref)
        if saved.get('official_report_reference'):
            verdict = validate_grade(read(check(saved['official_report_reference'])), plan, saved['predictions_reference'], saved['evaluation_reference'], config)
            require(all(saved[k] == v for k, v in verdict.items()), 'DIAGNOSTIC_VERDICT_CHANGED')
        return saved
    directory.mkdir(parents=True)
    result = {'selection_row_sha256': sha(canonical(plan)), 'grade_source': 'AUXILIARY_OFFICIAL_GRADER',
              'diagnostic_grade_status': 'GRADER_ERROR', 'diagnostic_passed': None, 'references': []}
    started = time.monotonic()
    try:
        code = read(check(plan['candidate_reference']))['code']
        require(sha(code.encode()) == plan['candidate_sha256'], 'SEALED_CANDIDATE_CHANGED')
        source = private_source(dataset_root, dataset_manifest, plan['task_id'])
        sample = directory / 'evaluation.json'
        with gzip.open(source, 'rb') as src, sample.open('xb') as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                dst.write(chunk)
        predictions = directory / 'predictions.json'
        write_new(predictions, expected_prediction(plan, code, runtime))
        sample_ref, prediction_ref = reference(sample), reference(predictions)
        require(sample_ref['sha256'] == decompressed_hash(source), 'DIAGNOSTIC_SAMPLE_CHANGED')
        result['references'] = [sample_ref, prediction_ref]
        settings = config.get('private_grading', {})
        report_path = directory / 'report.json'
        command = execution_command(runtime, 'trimem_lcb_grade.py', [
            '--predictions', mapped_path(predictions, runtime), '--dataset-json', mapped_path(sample, runtime),
            '--dataset-sha256', sample_ref['sha256'], '--official-repo', runtime['execution']['official_repo'],
            '--output', mapped_path(report_path, runtime), '--workers', str(settings.get('workers_per_cell', 1)),
            '--timeout', str(settings.get('timeout_seconds_per_case', 6))])
        env = {k: v for k, v in os.environ.items() if not k.upper().endswith('_API_KEY')}
        process = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=1800,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result['transport'] = {'returncode': process.returncode, 'stdout_sha256': sha(process.stdout), 'stderr_sha256': sha(process.stderr)}
        if process.returncode not in (0, 2) or not report_path.is_file():
            raise GraderTransportError('GRADER_TRANSPORT_FAILED')
        check(sample_ref)
        check(prediction_ref)
        report = read(report_path)
        verdict = validate_grade(report, plan, prediction_ref, sample_ref, config)
        require((process.returncode == 0) == (report['status'] == 'COMPLETE'), 'GRADER_EXIT_STATUS_CHANGED')
        result.update(verdict, official_report_reference=reference(report_path), predictions_reference=prediction_ref, evaluation_reference=sample_ref)
        result['references'].append(result['official_report_reference'])
    except DiagnosticError:
        raise  # Authority violations are blockers, never converted to ordinary infra.
    except Exception as exc:
        result['grade_error_type'] = type(exc).__name__
    result['wall_seconds'] = time.monotonic() - started
    write_new(receipt_path, result)
    return result


def summarize(rows):
    result = {}
    for arm in ('OFF', 'ON'):
        selected = [r for r in rows if r['arm'] == arm]
        planned = len(selected)
        passed = sum(r['diagnostic_passed'] is True for r in selected)
        failed = sum(r['diagnostic_passed'] is False for r in selected)
        absent = sum(r['selection_status'] == 'NOT_AVAILABLE' for r in selected)
        unresolved = planned - passed - failed - absent
        result[arm] = {'planned': planned, 'candidate_available': planned - absent, 'not_available': absent,
                       'graded': passed + failed, 'passed': passed, 'failed': failed, 'infrastructure_unresolved': unresolved,
                       'successes_per_scheduled_cell': passed / planned if planned else None,
                       'graded_candidate_fraction_descriptive': passed / (passed + failed) if passed + failed else None,
                       'full_cohort_candidate_correctness': passed / planned if not unresolved and not absent and planned else None}
    return result


def grade_diagnostics(output, manifest_reference, dataset_manifest, dataset_root, runtime, config, primary_rows,
                      *, collection_reference, verify_collection):
    output = Path(output).resolve()
    collection_guard(output, collection_reference, verify_collection)
    manifest = selection_guard(output, manifest_reference, collection_reference)  # Gate before private authority access.
    primary = {(r['task_id'], r['arm']): r for r in primary_rows}
    require(len(primary) == len(primary_rows) == EXPECTED_CELLS
            and set(primary) == {(r['task_id'], r['arm']) for r in manifest['rows']}, 'PRIMARY_COHORT_CHANGED')
    source_refs = [manifest_reference, collection_reference, *dataset_guard(output, dataset_manifest, dataset_root)]
    path = output / 'diagnostic-summary.json'
    rows = []
    for plan in manifest['rows']:
        check(manifest_reference)
        check(collection_reference)
        if plan['selection_status'] == 'NOT_AVAILABLE':
            verdict = {'diagnostic_grade_status': 'NOT_AVAILABLE', 'diagnostic_passed': None, 'grade_source': 'NO_CANDIDATE'}
        elif plan['primary_generation_status'] == 'SUBMITTED':
            verdict = reuse_primary(output, plan, primary[plan['task_id'], plan['arm']], dataset_manifest, dataset_root, runtime, config)
        else:
            verdict = grade_selected(output, plan, dataset_manifest, dataset_root, runtime, config)
        rows.append({**{k: plan[k] for k in ('task_id', 'arm', 'cell_key', 'selection_status', 'selection_source', 'selection_step', 'candidate_sha256')}, **verdict})
    collection_guard(output, collection_reference, verify_collection)
    selection_guard(output, manifest_reference, collection_reference)
    for ref in source_refs:
        check(ref)
    report = {'schema': SCHEMA, 'status': 'COMPLETE', 'label': 'RETAINED_CODE_DIAGNOSTIC_NOT_PRIMARY_END_TO_END_SCORE',
              'selection_policy': POLICY, 'selection_reference': manifest_reference, 'collection_reference': collection_reference,
              'planned_cells': EXPECTED_CELLS, 'arms': summarize(rows), 'rows': rows,
              'model_calls': 0, 'candidate_generations': 0, 'candidate_modifications': 0,
              'hidden_result_based_selection': False, 'original_cell_writes': 0, 'memory_writes': 0}
    if path.exists():
        require(read(path) == report, 'DIAGNOSTIC_SUMMARY_CHANGED')
    else:
        write_new(path, report)
    return report
