"""Synthetic eval-only orchestration; no models, datasets, or graders run."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_explicit_format_experiment as manager

exp = manager.exp


def task(identity):
    return {'task_id': identity, 'question_id': identity,
            'question_title': 'Synthetic addition', 'prompt': 'Synthetic fixture only.',
            'starter_code': '', 'public_evaluation_sample': {'input_output': '{}'}}


def make_cell(output, row, arm, runtime, bank=None, *, missing=False):
    """Write a model-free, internally hash-bound solve and one session."""
    cell = output / 'cells' / exp.cell_name(row['task_id'], arm)
    cell.mkdir(parents=True, exist_ok=True)
    folder = cell / 'session-01'
    folder.mkdir(exist_ok=True)
    state = {'task': row, 'arm': arm, 'runtime': runtime, 'bank': bank,
             'candidate': 'print(1 + 2)\n', 'finished': not missing,
             'session': 1, 'history': [], 'memory_injections': []}
    exp.write(cell / 'state.json', state)
    exp.write(cell / 'attempt.json', {'synthetic': True})
    (folder / 'events.jsonl').write_bytes(b'{"type":"synthetic-only"}\n')
    (folder / 'stderr.log').write_bytes(b'')
    (folder / 'prompt.txt').write_bytes(b'SYNTHETIC PROMPT: not benchmark data.\n')
    session = {'session': 1, 'thread_ids': ['synthetic-thread-' + cell.name],
               'usage': [{'input_tokens': 2, 'output_tokens': 3}],
               'events_sha256': exp.file_hash(folder / 'events.jsonl'),
               'stderr_sha256': exp.file_hash(folder / 'stderr.log')}
    exp.write(folder / 'receipt.json', session)
    exp.write(folder / 'prompt-receipt.json', {
        'task_id': row['task_id'], 'arm': arm, 'session': 1,
        'prompt_sha256': exp.file_hash(folder / 'prompt.txt'),
        'prompt_bytes': (folder / 'prompt.txt').stat().st_size,
        'contract_sha256': exp.sha(manager.native.CONTRACT.encode()),
        'command_sha256': exp.sha(manager.native.canonical(manager.native.worker_command(cell, state)))})
    solve = {'schema': 'trimem/lcb-solve-receipt/1.0', 'task_id': row['task_id'],
             'arm': arm, 'status': 'GENERATION_ERROR' if missing else 'SUBMITTED',
             'error_type': 'MissingSubmission' if missing else None,
             'state_sha256': exp.file_hash(cell / 'state.json'),
             'candidate_sha256': exp.sha(state['candidate'].encode()),
             'sessions': [session], 'wall_seconds': 1, 'tool_actions': 2,
             'public_test_runs': 1}
    exp.write(cell / 'solve-receipt.json', solve)
    result = exp._cell_result(cell, row, arm, solve, state)
    exp.write(cell / 'cell-receipt.json', result)
    return result


@pytest.fixture
def harness(tmp_path, monkeypatch):
    source = tmp_path / 'implementation.py'
    source.write_text('# synthetic source\n', encoding='utf-8')
    refs = [exp.reference(source)]
    monkeypatch.setattr(exp, 'implementation_references', lambda: refs)
    output = tmp_path / 'output'
    output.mkdir()
    valid_ids = ['valid-%02d' % i for i in range(24)]
    train_ids = ['train-%02d' % i for i in range(24)]
    jobs = manager.schedule(valid_ids)
    runtime = {'native': {'model': 'gpt-5.6-luna', 'reasoning_effort': 'low',
                          'codex_executable': 'NEVER_RUN'}, 'execution': {}}
    bank_file = tmp_path / 'synthetic-bank.json'
    exp.write(bank_file, {'synthetic': True})
    bank = {'path': str(bank_file), 'sha256': exp.file_hash(bank_file),
            'layer_counts': {'training_tasks': 9}}
    config = {'experiment_id': 'synthetic-explicit', 'workers': 2,
              'requested_model': 'gpt-5.6-luna', 'reasoning_effort': 'low',
              'source_bank_reference': exp.reference(bank_file),
              'org_id': 'synthetic-org', 'owner_user_id': 'synthetic-owner'}
    frozen = {'references': refs, 'implementation': refs,
              'enrollment': {'train': train_ids, 'valid': valid_ids},
              'schedule': [{'ordinal': i, 'task_id': identity, 'arm': arm}
                           for i, (identity, arm) in enumerate(jobs, 1)]}
    exp.write(output / 'frozen-inputs.json', frozen)
    context = {'config': config, 'runtime': runtime, 'split': {
        'pilot_ids': valid_ids, 'train_pilot_ids': train_ids},
        'public_manifest': {}, 'tasks': {identity: task(identity) for identity in valid_ids},
        'frozen': frozen, 'bank': bank, 'jobs': jobs}
    log = []

    def collect(destination, row, arm, actual_runtime, actual_bank, actual_frozen):
        assert actual_runtime == runtime and actual_frozen == frozen
        assert actual_bank == (bank if arm == 'ON' else None)
        assert arm in ('OFF', 'ON')
        log.append(('collect', row['task_id'], arm))
        return make_cell(destination, row, arm, runtime, actual_bank)

    def prepare_diagnostics(destination, rows, *, collection_reference, verify_collection):
        assert len([event for event in log if event[0] == 'collect']) == 48
        assert len(rows) == 48 and verify_collection()['completed_cells'] == 48
        assert all(row['passed'] is None for row in rows)
        assert not any(event[0] == 'grade' for event in log)
        log.append(('select',))
        path = destination / 'diagnostic-selection.json'
        exp.write(path, {'synthetic': True, 'collection_reference': collection_reference})
        return exp.reference(path)

    def final_manifest(*args):
        assert log[-1] == ('select',)
        log.append(('private_authority',))
        return {'synthetic': True}

    def grade(destination, identity, arm, row, *args):
        assert ('select',) in log and ('private_authority',) in log
        assert len([event for event in log if event[0] == 'collect']) == 48
        log.append(('grade', identity, arm))
        result = {**row, 'passed': True, 'grade_status': 'GRADED'}
        # Mirror the original grader's mutable receipt, outside the collection seal.
        exp.write(destination / 'cells' / exp.cell_name(identity, arm) / 'cell-receipt.json', result)
        return result

    def grade_diagnostics(destination, selection_ref, *args, **kwargs):
        assert len([event for event in log if event[0] == 'grade']) == 48
        kwargs['verify_collection']()
        log.append(('grade_diagnostics',))
        summary = {'status': 'COMPLETE', 'synthetic': True}
        exp.write(destination / 'diagnostic-summary.json', summary)
        return summary

    auxiliary = SimpleNamespace(prepare_diagnostics=prepare_diagnostics,
                                grade_diagnostics=grade_diagnostics)
    context['auxiliary'] = auxiliary
    monkeypatch.setattr(manager, '_prepare', lambda *args: context)
    monkeypatch.setattr(exp, 'collect_cell', collect)
    monkeypatch.setattr(exp, 'final_manifest', final_manifest)
    monkeypatch.setattr(exp, 'grade_cell', grade)
    def forbidden(*args, **kwargs):
        pytest.fail('Evaluation-only manager invoked training, capture, or model execution')
    monkeypatch.setattr(exp, 'capture_cell', forbidden)
    monkeypatch.setattr(exp, 'freeze_bank', forbidden)
    monkeypatch.setattr(manager.memory, 'initialize_training_memory', forbidden)
    monkeypatch.setattr(manager.native.core, 'solve_cell', forbidden)
    return SimpleNamespace(output=output, data=tmp_path / 'data', context=context,
        jobs=jobs, frozen=frozen, tasks=context['tasks'], runtime=runtime, bank=bank,
        source=source, log=log, auxiliary=auxiliary, collect=collect)


def run(harness, **kwargs):
    # Direct tests below exercise every bound-source check. Sequencing tests need
    # one full audit, not dozens of identical 400-file audits on Windows.
    original, verified = manager.verify_collection, []
    def verify(output, reference):
        exp.verify_frozen(harness.frozen)
        if not verified:
            verified.append(original(output, reference))
        manager.checked(reference)
        return deepcopy(verified[0])
    with patch.object(manager, 'verify_collection', side_effect=verify):
        return manager.run_experiment('unused-config', 'unused-runtime', harness.data,
                                      harness.output, **kwargs)


def populated(harness):
    result = []
    for ordinal, (identity, arm) in enumerate(harness.jobs, 1):
        manager._scheduled_start(harness.output, harness.frozen, ordinal, identity, arm)
        result.append(make_cell(harness.output, harness.tasks[identity], arm,
                               harness.runtime, harness.bank if arm == 'ON' else None))
    return result


def test_schedule_has_exact_48_cells_and_balanced_pair_order():
    ids = ['synthetic-%02d' % i for i in range(24)]
    jobs = manager.schedule(ids)
    assert len(jobs) == len(set(jobs)) == 48
    assert [identity for identity, _ in jobs[::2]] == ids
    assert sum(arm == 'OFF' for _, arm in jobs[::2]) == 12
    assert sum(arm == 'ON' for _, arm in jobs[::2]) == 12
    assert all({jobs[i][1], jobs[i + 1][1]} == {'OFF', 'ON'} for i in range(0, 48, 2))


@pytest.mark.parametrize('ids', [['x'] * 24, ['x%d' % i for i in range(23)]])
def test_schedule_rejects_duplicate_or_incomplete_enrollment(ids):
    with pytest.raises(manager.ExplicitExperimentError, match='VALID_COHORT'):
        manager.schedule(ids)


def test_full_run_seals_then_selects_then_grades_without_training(harness):
    result = run(harness)
    assert result['status'] == result['phase'] == 'COMPLETE'
    assert result['new_training_cells'] == 0 and result['source_training_tasks'] == 9
    assert set(result['arms']) == {'OFF', 'ON'}
    assert result['paired']['completed'] == 24
    assert [item[0] for item in harness.log] == ['collect'] * 48 + [
        'select', 'private_authority'] + ['grade'] * 48 + ['grade_diagnostics']
    collection = manager.verify_collection(harness.output, result['collection_reference'])
    assert all(row['passed'] is None and row['grade_status'] == 'PENDING'
               for row in collection['rows'])
    assert all(Path(ref['path']).name != 'cell-receipt.json'
               for ref in collection['source_references'])
    summary_text = (harness.output / 'summary.json').read_text(encoding='utf-8')
    assert 'print(1 + 2)' not in summary_text and 'Synthetic fixture only.' not in summary_text


def test_collect_only_never_selects_or_opens_private_authority(harness):
    result = run(harness, collect_only=True)
    assert result['phase'] == 'COLLECTED' and result['status'] == 'INCOMPLETE'
    assert [item[0] for item in harness.log] == ['collect'] * 48
    assert (harness.output / 'collection.json').is_file()


def test_missing_private_data_still_selects_only_after_seal(harness, monkeypatch):
    monkeypatch.setattr(exp, 'final_manifest', lambda *args: None)
    result = run(harness)
    assert result['phase'] == 'WAITING_FOR_PRIVATE_DATA'
    assert harness.log[-1] == ('select',)
    assert all(row['passed'] is None for row in result['cells'])


def test_held_cell_stops_collection_and_resume_never_launches_solver(harness, monkeypatch):
    # Use the original collector's actual partial-directory guard.
    import importlib.util
    spec = importlib.util.spec_from_file_location('_synthetic_original_collector', exp.__file__)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    monkeypatch.setattr(original, 'verify_frozen', exp.verify_frozen)
    for ordinal, (identity, arm) in enumerate(harness.jobs[:2], 1):
        manager._scheduled_start(harness.output, harness.frozen, ordinal, identity, arm)
        (harness.output / 'cells' / exp.cell_name(identity, arm)).mkdir(parents=True)
    monkeypatch.setattr(exp, 'collect_cell', original.collect_cell)
    first = run(harness)
    second = run(harness)
    assert first['status'] == second['status'] == 'HELD'
    assert first['evaluation_cells_recorded'] == second['evaluation_cells_recorded'] == 2
    assert not harness.log and not (harness.output / 'collection.json').exists()


def test_final_source_change_prevents_complete_report(harness, monkeypatch):
    original = harness.auxiliary.grade_diagnostics
    def change(*args, **kwargs):
        value = original(*args, **kwargs)
        harness.source.write_text('# changed after last grading stage\n', encoding='utf-8')
        return value
    monkeypatch.setattr(harness.auxiliary, 'grade_diagnostics', change)
    with pytest.raises(exp.FrozenInputChanged):
        run(harness)
    assert exp.read(harness.output / 'summary.json')['phase'] != 'COMPLETE'


@pytest.mark.parametrize('name', ['state.json', 'session-01/prompt.txt', 'session-01/events.jsonl'])
def test_collection_rejects_tampered_bound_source(harness, name):
    rows = populated(harness)
    ref = manager.seal_collection(harness.output, rows, harness.frozen, harness.tasks)
    identity, arm = harness.jobs[0]
    path = harness.output / 'cells' / exp.cell_name(identity, arm) / name
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(manager.ExplicitExperimentError, match='REFERENCED_SOURCE_CHANGED'):
        manager.verify_collection(harness.output, ref)


def test_collection_receipt_itself_is_hash_bound(harness):
    rows = populated(harness)
    ref = manager.seal_collection(harness.output, rows, harness.frozen, harness.tasks)
    value = exp.read(ref['path'])
    value['rows'][0]['passed'] = True
    exp.write(ref['path'], value)
    with pytest.raises(manager.ExplicitExperimentError, match='REFERENCED_SOURCE_CHANGED'):
        manager.verify_collection(harness.output, ref)


@pytest.mark.parametrize('mutation,code', [
    ('missing_row', 'COLLECTION_COHORT_INCOMPLETE'),
    ('held', 'UNSEALED_OR_HELD_NATIVE_ATTEMPT'),
    ('wrong_prompt_contract', 'PROMPT_CONTRACT_CHANGED'),
    ('wrong_launch_command', 'PROMPT_LAUNCH_COMMAND_CHANGED'),
])
def test_collection_cannot_seal_incomplete_or_unbound_runs(harness, mutation, code):
    rows = populated(harness)
    if mutation == 'missing_row':
        rows.pop()
    elif mutation == 'held':
        rows[0]['status'] = 'HELD'
    else:
        identity, arm = harness.jobs[0]
        path = harness.output / 'cells' / exp.cell_name(identity, arm) / 'session-01/prompt-receipt.json'
        prompt = exp.read(path)
        prompt['contract_sha256' if mutation == 'wrong_prompt_contract' else 'command_sha256'] = '0' * 64
        exp.write(path, prompt)
    with pytest.raises(manager.ExplicitExperimentError, match=code):
        manager.seal_collection(harness.output, rows, harness.frozen, harness.tasks)
    assert not (harness.output / 'collection.json').exists()


def test_generation_projection_keeps_failures_null_and_removes_grade_evidence():
    row = {'task_id': 'synthetic', 'arm': 'ON', 'status': 'GENERATION_ERROR',
           'error_type': 'MissingSubmission', 'passed': True, 'grade_status': 'GRADED',
           'grade_reference': {'synthetic': True}, 'grader_seconds': 3,
           'resolved': True, 'outcome': 'SOLVED'}
    before = deepcopy(row)
    result = manager.generation_row(row)
    assert row == before and result['passed'] is None
    assert result['grade_status'] == 'GENERATION_ERROR'
    assert result['error_type'] == 'MissingSubmission'
    assert not {'grade_reference', 'grader_seconds', 'resolved', 'outcome'} & result.keys()


@pytest.fixture
def source_bank(harness, monkeypatch):
    """Nine synthetic captures, with the original cohort verifier still active."""
    root = harness.output.parent / 'source-run'
    root.mkdir()
    authority = root / 'authority.sqlite3'
    authority.write_bytes(b'Synthetic authority: no database is opened.')
    train_ids = harness.context['split']['train_pilot_ids']
    captures, training = {}, []
    for index, identity in enumerate(train_ids):
        row = {'task_id': identity, 'arm': 'TRAIN', 'capture_status': 'NOT_APPLICABLE'}
        if index < 9:
            cell = root / identity
            cell.mkdir()
            code = 'print(3)\n'
            exp.write(cell / 'state.json', {'candidate': code, 'synthetic': True})
            solve = {'task_id': identity, 'arm': 'TRAIN', 'status': 'SUBMITTED',
                     'candidate_sha256': exp.sha(code.encode()),
                     'state_sha256': exp.file_hash(cell / 'state.json')}
            exp.write(cell / 'solve-receipt.json', solve)
            exp.write(cell / 'capture-receipt.json', {'synthetic': True})
            capture_path = cell / 'capture.json'
            exp.write(capture_path, {'capture': {'task_public': {'task_id': identity},
                'model_id': 'gpt-5.6-luna', 'contributor_id': 'synthetic-thread-' + identity,
                'final_code': code}})
            captures[identity] = {**exp.reference(capture_path),
                                  'path': capture_path.relative_to(root).as_posix()}
            row.update(capture_status='CAPTURED', candidate_sha256=solve['candidate_sha256'],
                thread_ids=['synthetic-thread-' + identity],
                solve_reference=exp.reference(cell / 'solve-receipt.json'),
                capture_reference=exp.reference(cell / 'capture-receipt.json'))
        training.append(row)
    summary = {'status': 'COMPLETE', 'bank': harness.bank, 'cells': training}
    old_frozen = {**harness.frozen, 'model': 'gpt-5.6-luna', 'reasoning_effort': 'low'}
    config = deepcopy(harness.context['config'])
    for key, name, value in [
        ('source_bank_receipt_reference', 'bank-receipt.json', harness.bank),
        ('source_summary_reference', 'summary.json', summary),
        ('source_frozen_inputs_reference', 'frozen-inputs.json', old_frozen),
    ]:
        exp.write(root / name, value)
        config[key] = exp.reference(root / name)
    descriptor = lambda row: {'task_id': row['task_id']}
    manifest = {'scope': {'org_id': config['org_id'], 'owner_user_id': config['owner_user_id'],
                         'tasks': [descriptor(row) for row in harness.tasks.values()]},
                'authority': {**exp.reference(authority), 'path': authority.name},
                'catalog': {'captures': captures, 'observations': {}}}
    class SyntheticBank:
        def __init__(self):
            self.root, self.manifest = root, manifest
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(manager.memory, '_descriptor', descriptor)
    monkeypatch.setattr(manager.memory, 'load_frozen_bank', lambda *args: SyntheticBank())
    return SimpleNamespace(root=root, config=config, frozen=old_frozen,
                           summary=summary, manifest=manifest)


def validate(harness, source_bank):
    return manager.validate_source_bank(source_bank.config, harness.runtime,
                                        harness.tasks, harness.context['split'])


def test_source_bank_has_nine_pinned_captures_and_same_model_cohort(harness, source_bank):
    bank, refs = validate(harness, source_bank)
    assert bank == harness.bank and bank['layer_counts']['training_tasks'] == 9
    assert len([r for r in refs if Path(r['path']).name == 'capture.json']) == 9
    assert exp.reference(source_bank.root / 'authority.sqlite3') in refs


@pytest.mark.parametrize('mutation,code', [
    ('model', 'SOURCE_MODEL_DIFFERS'), ('cohort', 'SOURCE_SPLIT_DIFFERS'),
    ('training_identity', 'SOURCE_TRAIN_COHORT_DIFFERS'),
])
def test_source_bank_rejects_repinned_model_or_cohort_mismatch(harness, source_bank, mutation, code):
    if mutation == 'training_identity':
        source_bank.summary['cells'][-1]['task_id'] = 'out-of-cohort'
        key, value = 'source_summary_reference', source_bank.summary
    else:
        key, value = 'source_frozen_inputs_reference', source_bank.frozen
        if mutation == 'model':
            value['model'] = 'different-model'
        else:
            value['enrollment']['train'] = ['different-train'] * 24
    path = source_bank.config[key]['path']
    exp.write(path, value)
    source_bank.config[key] = exp.reference(path)
    with pytest.raises(manager.ExplicitExperimentError, match=code):
        validate(harness, source_bank)


def test_source_bank_checks_actual_capture_model_not_only_summary(harness, source_bank):
    ref = next(iter(source_bank.manifest['catalog']['captures'].values()))
    path = source_bank.root / ref['path']
    capture = exp.read(path)
    capture['capture']['model_id'] = 'different-model'
    exp.write(path, capture)
    ref.update(sha256=exp.file_hash(path), bytes=path.stat().st_size)
    with pytest.raises(exp.FrozenInputChanged, match='training cells'):
        validate(harness, source_bank)


def test_primary_grading_claim_prevents_partial_retry_but_allows_report_reuse(harness, monkeypatch):
    row = {'task_id': harness.jobs[0][0], 'arm': 'OFF', 'status': 'SUBMITTED',
           'grade_status': 'PENDING', 'passed': None}
    calls = []
    def grade(*args):
        calls.append(args)
        return row
    monkeypatch.setattr(exp, 'grade_cell', grade)
    ref = {'path': 'synthetic-collection', 'sha256': 'a' * 64, 'bytes': 1}
    invoke = lambda: manager.grade_primary(harness.output, row, {}, harness.data,
        harness.runtime, harness.context['config'], ref)
    invoke()
    assert len(calls) == 1
    with pytest.raises(manager.ExplicitExperimentError, match='PARTIAL_PRIMARY_GRADING_NO_RETRY'):
        invoke()
    assert len(calls) == 1
    folder = harness.output / 'private-grades' / exp.cell_name(row['task_id'], row['arm'])
    folder.mkdir(parents=True)
    exp.write(folder / 'report.json', {'synthetic': True})
    # The unchanged original grader, mocked here, owns strict report validation.
    invoke()
    assert len(calls) == 2
