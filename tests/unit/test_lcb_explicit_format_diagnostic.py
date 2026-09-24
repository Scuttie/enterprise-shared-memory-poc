"""Synthetic selection/provenance and grading-gate checks; no real graders."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_explicit_format_diagnostic as diagnostic


def event(step, request, result, status):
    return {'type': 'item.completed', 'item': {'id': f'synthetic-{step}', 'type': 'mcp_tool_call',
        'server': 'benchmark', 'tool': 'action', 'arguments': {'request': request},
        'result': {'content': [{'type': 'text', 'text': json.dumps({'step_no': step, 'status': status, 'result': result})}]}}}


def make_cell(output, task='synthetic-a', arm='OFF', mode='rejected'):
    cell = output / 'cells' / diagnostic.cell_name(task, arm)
    folder = cell / 'session-01'
    folder.mkdir(parents=True)
    state = {'task': {'task_id': task, 'split': 'valid', 'public_tests_sha256': 'a' * 64},
             'arm': arm, 'limits': {'code_bytes': 65536}, 'step': 1, 'finished': mode == 'submitted',
             'candidate': '# unrelated current state candidate\n', 'history': [], 'rejected_actions': []}
    events = []
    if mode != 'none':
        request = {'tool': 'run_public_tests', 'arguments': {'code': '# public candidate\n'}}
        result = {'status': 'FAIL', 'candidate_sha256': diagnostic.sha(request['arguments']['code'].encode()),
                  'public_tests_sha256': 'a' * 64}
        row = {'step_no': 1, 'tool': 'run_public_tests', 'status': 'success', 'task_id': task,
               'arm': 'PDF_MEMORY' if arm == 'ON' else 'BASELINE', 'request_payload': request, 'result_payload': result}
        for key, payload in [('request', request), ('result', result)]:
            raw = diagnostic.canonical(payload)[:-1]
            row[key] = {'sha256': diagnostic.sha(raw), 'bytes': len(raw)}
        state['history'].append(row)
        events.append(event(1, request, result, 'success'))
    if mode == 'rejected':
        for step, code in [(2, '# earlier candidate\n'), (3, '# last valid candidate\n'), (4, '')]:
            request = {'tool': 'finish', 'arguments': {'code': code, 'source_lesson': {'trace_steps': ['invalid']}}}
            result = {'error': 'ValueError', 'message': 'Synthetic rejection'}
            state['rejected_actions'].append({'step': step, 'request': request, 'result': result})
            events.append(event(step, request, result, 'error'))
        state['step'] = 4
    elif mode == 'submitted':
        state.update(candidate='# accepted candidate\n', step=2)
        request = {'tool': 'finish', 'arguments': {'code': state['candidate']}}
        events.append(event(2, request, {'submitted': True, 'candidate_sha256': diagnostic.sha(state['candidate'].encode())}, 'success'))
    (folder / 'events.jsonl').write_bytes(b''.join(diagnostic.canonical(e) for e in events))
    (folder / 'stderr.log').write_bytes(b'')
    session = {'session': 1, 'events_sha256': diagnostic.file_hash(folder / 'events.jsonl'),
               'stderr_sha256': diagnostic.file_hash(folder / 'stderr.log')}
    diagnostic.write_new(folder / 'receipt.json', session)
    diagnostic.write_new(cell / 'state.json', state)
    solve = {'schema': 'trimem/lcb-solve-receipt/1.0', 'task_id': task, 'arm': arm,
             'status': 'SUBMITTED' if mode == 'submitted' else 'GENERATION_ERROR',
             'error_type': None if mode == 'submitted' else 'MissingSubmission',
             'candidate_sha256': diagnostic.sha(state['candidate'].encode()),
             'state_sha256': diagnostic.file_hash(cell / 'state.json'), 'sessions': [session]}
    diagnostic.write_new(cell / 'solve-receipt.json', solve)
    row = {k: solve[k] for k in ('task_id', 'arm', 'status', 'error_type', 'candidate_sha256')}
    row.update(solve_reference=diagnostic.reference(cell / 'solve-receipt.json'), passed=None,
               grade_status='PENDING' if mode == 'submitted' else 'GENERATION_ERROR')
    return cell, state, row


@pytest.mark.parametrize('mode,source,expected', [
    ('submitted', 'ACCEPTED_SUBMISSION', '# accepted candidate\n'),
    ('rejected', 'REJECTED_FINISH', '# last valid candidate\n'),
    ('public', 'PUBLIC_TEST_REQUEST', '# public candidate\n'),
    ('none', None, None)])
def test_policy_uses_exact_event_corroborated_candidate_not_arbitrary_state(tmp_path, mode, source, expected):
    cell, state, row = make_cell(tmp_path, mode=mode)
    before = {p: p.read_bytes() for p in cell.rglob('*') if p.is_file()}
    metadata, code = diagnostic.select_candidate(cell, row=row)
    assert code == expected
    assert metadata['selection_source'] == source
    assert metadata['selection_status'] == ('SELECTED' if expected is not None else 'NOT_AVAILABLE')
    assert 'candidate\n' not in json.dumps(metadata)
    assert {p: p.read_bytes() for p in before} == before


def test_last_valid_finish_skips_later_oversize_or_nonstring_and_is_outcome_independent(tmp_path):
    _, state, _ = make_cell(tmp_path)
    state['rejected_actions'][-1]['request']['arguments']['code'] = 'x' * 65537
    code, _ = diagnostic.source_choice(state, False)
    assert code == '# last valid candidate\n'
    for grade in (True, False, None):
        changed = deepcopy(state)
        changed['passed'] = grade
        changed['private_grade'] = {'passed': grade, 'best_candidate': '# never select'}
        changed['candidate'] = '# arbitrary terminal candidate'
        assert diagnostic.source_choice(changed, False)[0] == code


@pytest.mark.parametrize('mutation', ['future', 'unordered', 'boolean', 'limit'])
def test_future_or_ambiguous_trace_is_not_silently_selected(tmp_path, mutation):
    _, state, _ = make_cell(tmp_path)
    if mutation == 'future':
        state['rejected_actions'][-1]['step'] = state['step'] + 1
    elif mutation == 'unordered':
        state['rejected_actions'].reverse()
    elif mutation == 'boolean':
        state['rejected_actions'][0]['step'] = True
    else:
        state['limits']['code_bytes'] = 999999
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.source_choice(state, False)


@pytest.mark.parametrize('file', ['state.json', 'session-01/events.jsonl', 'session-01/stderr.log'])
def test_changed_original_evidence_blocks_selection(tmp_path, file):
    cell, _, row = make_cell(tmp_path)
    path = cell / file
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.select_candidate(cell, row=row)


def reseal_state(cell, row, state):
    (cell / 'state.json').write_bytes(diagnostic.canonical(state))
    solve = diagnostic.read(cell / 'solve-receipt.json')
    solve['state_sha256'] = diagnostic.file_hash(cell / 'state.json')
    (cell / 'solve-receipt.json').write_bytes(diagnostic.canonical(solve))
    row['solve_reference'] = diagnostic.reference(cell / 'solve-receipt.json')


def test_consistently_rehashed_rejected_code_still_requires_original_native_event(tmp_path):
    cell, state, row = make_cell(tmp_path)
    state['rejected_actions'][1]['request']['arguments']['code'] = '# forged candidate'
    reseal_state(cell, row, state)
    with pytest.raises(diagnostic.DiagnosticError, match='REJECTED_FINISH_NOT_CORROBORATED'):
        diagnostic.select_candidate(cell, row=row)


def test_public_trace_core_hash_is_required_even_with_resealed_state(tmp_path):
    cell, state, row = make_cell(tmp_path, mode='public')
    state['history'][0]['request']['sha256'] = '0' * 64
    reseal_state(cell, row, state)
    with pytest.raises(diagnostic.DiagnosticError, match='PUBLIC_TRACE_HASH_CHANGED'):
        diagnostic.select_candidate(cell, row=row)


@pytest.fixture
def collected(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostic, 'EXPECTED_CELLS', 4)
    output = tmp_path / 'run'
    output.mkdir()
    rows, refs = [], []
    for task, arm, mode in [('synthetic-a', 'OFF', 'submitted'), ('synthetic-a', 'ON', 'rejected'),
                            ('synthetic-b', 'OFF', 'public'), ('synthetic-b', 'ON', 'none')]:
        cell, _, row = make_cell(output, task, arm, mode)
        rows.append(row)
        refs.extend(diagnostic.reference(p) for p in sorted(cell.rglob('*')) if p.is_file())
    frozen = output / 'frozen.json'
    diagnostic.write_new(frozen, {'schema': 'synthetic-frozen-inputs'})
    collection = {'schema': 'lcb-explicit-format-collection/1', 'status': 'COMPLETE',
                  'planned_cells': 4, 'completed_cells': 4, 'rows': rows, 'source_references': refs,
                  'frozen_inputs_reference': diagnostic.reference(frozen)}
    diagnostic.write_new(output / 'collection.json', collection)
    return output, rows, diagnostic.reference(output / 'collection.json'), lambda: collection


def test_all_candidates_are_sealed_before_private_access_and_resume_preserves_exact_bytes(collected):
    output, rows, collection_ref, verify = collected
    before = {p: p.read_bytes() for p in (output / 'cells').rglob('*') if p.is_file()}
    ref = diagnostic.prepare_diagnostics(output, rows, collection_reference=collection_ref, verify_collection=verify)
    manifest = diagnostic.read(ref['path'])
    assert manifest['selection_complete'] is True
    assert manifest['planned_cells'] == 4 and manifest['selected_candidates'] == 3
    assert not (output / 'private-grades').exists()
    assert not (output / 'diagnostic-grades').exists()
    assert diagnostic.prepare_diagnostics(output, rows, collection_reference=collection_ref, verify_collection=verify) == ref
    assert {p: p.read_bytes() for p in before} == before


def test_creation_after_primary_grading_is_forbidden(collected):
    output, rows, ref, verify = collected
    (output / 'private-grades').mkdir()
    with pytest.raises(diagnostic.DiagnosticError, match='SELECTION_MUST_PRECEDE_PRIVATE_GRADING'):
        diagnostic.prepare_diagnostics(output, rows, collection_reference=ref, verify_collection=verify)


def test_changed_candidate_file_cannot_be_accepted_on_resume(collected):
    output, rows, ref, verify = collected
    selected = diagnostic.prepare_diagnostics(output, rows, collection_reference=ref, verify_collection=verify)
    manifest = diagnostic.read(selected['path'])
    path = Path(manifest['rows'][0]['candidate_reference']['path'])
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(diagnostic.DiagnosticError, match='REFERENCE_CHANGED'):
        diagnostic.prepare_diagnostics(output, rows, collection_reference=ref, verify_collection=verify)


def test_private_dataset_guard_never_runs_without_complete_selection(collected, monkeypatch):
    output, rows, ref, verify = collected
    calls = []
    monkeypatch.setattr(diagnostic, 'dataset_guard', lambda *args: calls.append(args))
    with pytest.raises(FileNotFoundError):
        diagnostic.grade_diagnostics(output, {'path': str(output / 'diagnostic-selection.json'), 'sha256': '0' * 64},
            {}, 'never-open-private', {}, {}, rows, collection_reference=ref, verify_collection=verify)
    assert calls == []


def test_missing_candidate_and_infra_stay_separate_with_full_denominator():
    rows = [{'arm': 'OFF', 'selection_status': selected, 'diagnostic_passed': passed}
            for selected, passed in [('SELECTED', True), ('SELECTED', False), ('SELECTED', None), ('NOT_AVAILABLE', None)]]
    summary = diagnostic.summarize(rows)['OFF']
    assert summary == {'planned': 4, 'candidate_available': 3, 'not_available': 1, 'graded': 2,
                       'passed': 1, 'failed': 1, 'infrastructure_unresolved': 1,
                       'successes_per_scheduled_cell': .25, 'graded_candidate_fraction_descriptive': .5,
                       'full_cohort_candidate_correctness': None}


def test_grade_orchestration_requires_all_selections_then_reuses_submitted_primary(collected, monkeypatch):
    output, original, collection_ref, verify = collected
    manifest_ref = diagnostic.prepare_diagnostics(output, original, collection_reference=collection_ref, verify_collection=verify)
    before = {p: p.read_bytes() for p in (output / 'cells').rglob('*') if p.is_file()}
    events = []
    def private_guard(*args):
        manifest = diagnostic.read(diagnostic.check(manifest_ref))
        assert manifest['selection_complete'] and len(manifest['rows']) == 4
        assert all(r['candidate_reference'] or r['selection_status'] == 'NOT_AVAILABLE' for r in manifest['rows'])
        events.append('private-access-after-all-four-sealed')
        return []
    def reuse(_output, plan, *args):
        assert plan['primary_generation_status'] == 'SUBMITTED'
        events.append('reuse-primary')
        return {'diagnostic_grade_status': 'GRADED', 'diagnostic_passed': True, 'grade_source': 'PRIMARY_REUSED'}
    def grade(_output, plan, *args):
        assert plan['primary_generation_status'] != 'SUBMITTED'
        events.append('grade-selected-missing')
        return {'diagnostic_grade_status': 'GRADED', 'diagnostic_passed': False, 'grade_source': 'AUXILIARY_OFFICIAL_GRADER'}
    monkeypatch.setattr(diagnostic, 'dataset_guard', private_guard)
    monkeypatch.setattr(diagnostic, 'reuse_primary', reuse)
    monkeypatch.setattr(diagnostic, 'grade_selected', grade)
    result = diagnostic.grade_diagnostics(output, manifest_ref, {}, 'never-open-real-private', {}, {}, original,
                                         collection_reference=collection_ref, verify_collection=verify)
    assert events == ['private-access-after-all-four-sealed', 'reuse-primary', 'grade-selected-missing', 'grade-selected-missing']
    assert len(result['rows']) == 4 and result['original_cell_writes'] == result['model_calls'] == 0
    assert result['arms']['OFF']['planned'] == result['arms']['ON']['planned'] == 2
    assert result['arms']['OFF']['passed'] == 1
    assert result['arms']['ON']['not_available'] == 1
    assert {p: p.read_bytes() for p in before} == before


def test_primary_grade_reuse_verifies_saved_candidate_and_report_without_new_grader(collected, monkeypatch):
    output, rows, collection_ref, verify = collected
    manifest_ref = diagnostic.prepare_diagnostics(output, rows, collection_reference=collection_ref, verify_collection=verify)
    plan = diagnostic.read(manifest_ref['path'])['rows'][0]
    code = diagnostic.read(plan['candidate_reference']['path'])['code']
    runtime = {'native': {'model': 'synthetic-model'}}
    directory = output / 'private-grades' / plan['cell_key']
    directory.mkdir(parents=True)
    sample = b'{"synthetic":"opaque fixture"}'
    (directory / 'evaluation.json').write_bytes(sample)
    diagnostic.write_new(directory / 'predictions.json', diagnostic.expected_prediction(plan, code, runtime))
    dataset_root = output / 'synthetic-dataset'
    dataset_root.mkdir()
    source = dataset_root / 'synthetic.json.gz'
    source.write_bytes(gzip.compress(sample))
    source_ref = diagnostic.reference(source)
    source_ref.update(path=source.name, format='gzip-json')
    report = {'schema': 'trimem/lcb-grade-report/1.0', 'status': 'COMPLETE', 'cohort_scope': 'DECLARED_EXPECTED_IDS',
              'settings': {'timeout_seconds': 6, 'workers': 1, 'generations_per_question': 1, 'extraction_style': 'OpenAIChat'},
              'counts': {'planned': 1, 'graded': 1, 'passed': 1},
              'provenance': {'upstream_commit': diagnostic.UPSTREAM_COMMIT,
                  'predictions_reference': diagnostic.reference(directory / 'predictions.json'),
                  'dataset_reference': diagnostic.reference(directory / 'evaluation.json')},
              'results': [{'question_id': plan['task_id'], 'status': 'GRADED', 'passed': True,
                           'extracted_code_sha256': plan['candidate_sha256']}]}
    diagnostic.write_new(directory / 'report.json', report)
    primary = {**rows[0], 'grade_status': 'GRADED', 'passed': True, 'grade_reference': diagnostic.reference(directory / 'report.json')}
    diagnostic.write_new(output / 'cells' / plan['cell_key'] / 'cell-receipt.json', primary)
    monkeypatch.setattr(diagnostic.subprocess, 'run', lambda *a, **kw: pytest.fail('Primary reuse must never grade again'))
    result = diagnostic.reuse_primary(output, plan, primary, {'private_evaluation_files': {plan['task_id']: source_ref}}, dataset_root, runtime, {})
    assert result['grade_source'] == 'PRIMARY_REUSED' and result['diagnostic_passed'] is True
    assert not (output / 'diagnostic-grades').exists()
    report['results'][0]['extracted_code_sha256'] = '0' * 64
    (directory / 'report.json').write_bytes(diagnostic.canonical(report))
    with pytest.raises(diagnostic.DiagnosticError, match='REFERENCE_CHANGED'):
        diagnostic.reuse_primary(output, plan, primary, {'private_evaluation_files': {plan['task_id']: source_ref}}, dataset_root, runtime, {})
