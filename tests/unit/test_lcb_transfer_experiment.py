"""Synthetic phase sequencing and integrity; no model or grader execution."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_transfer_experiment as driver

base = driver.base
REAL_COLLECT = driver.collect
REAL_LOAD = driver.load


def task(identity, split):
    sample = {'input_output': json.dumps({'inputs': ['1\n'], 'outputs': ['2\n'], 'fn_name': None})}
    value = {'schema': driver.memory.base.PUBLIC_TASK_SCHEMA, 'task_id': identity, 'question_id': identity,
        'split': split, 'family_id': 'family-' + identity, 'question_title': 'Synthetic ' + identity,
        'prompt': 'Increment an integer. Synthetic task ' + identity, 'starter_code': '',
        'public_test_cases': [{'input': '1\n', 'output': '2\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': sample}
    value['instruction_sha256'] = driver.memory.base._hash({k: value[k] for k in ('question_title', 'prompt', 'starter_code')})
    value['public_tests_sha256'] = driver.memory.base.public_tests_sha256(value)
    return value


def write_cell(context, job, bank, selected):
    output = context['output']
    _, cell = driver.cell_paths(output, job)
    folder = cell / 'session-01'
    folder.mkdir(parents=True)
    row = context['tasks'][job['task_id']]
    state = {'task': row, 'arm': driver.native_arm(job), 'phase': job['phase'],
        'runtime': context['runtime'], 'bank': bank, 'candidate': 'print(2)\n', 'finished': True,
        'session': 1, 'history': [], 'memory_injections': [], 'selected_procedure_id': selected,
        'owner_user_id': context['config']['owner_user_id'], 'org_id': context['config']['org_id'],
        'enabled_layers': ['L1'] if job['condition'] == 'L1ONLY' else ['L3', 'L2', 'L1']}
    base.write(cell / 'state.json', state)
    base.write(cell / 'attempt.json', {'synthetic': True})
    base.write(output / 'starts' / ('%04d.json' % job['ordinal']), {
        'schema': driver.SCHEMA, **job, 'native_arm': driver.native_arm(job),
        'condition': driver.condition(job), 'frozen_inputs_reference': base.reference(output / 'frozen-inputs.json'),
        'bank': bank, 'selected_procedure_id': selected})
    (folder / 'prompt.txt').write_bytes(b'Synthetic public task packet only.\n')
    (folder / 'events.jsonl').write_bytes(b'{"type":"synthetic"}\n')
    (folder / 'stderr.log').write_bytes(b'')
    base.write(folder / 'initial-state.json', {**state, 'finished': False})
    session = {'session': 1, 'thread_ids': ['synthetic-' + cell.name],
               'events_sha256': base.file_hash(folder / 'events.jsonl'),
               'stderr_sha256': base.file_hash(folder / 'stderr.log')}
    base.write(folder / 'receipt.json', session)
    base.write(folder / 'prompt-receipt.json', {
        'schema': 'lcb-transfer-prompt/1', 'task_id': row['task_id'], 'arm': state['arm'],
        'phase': job['phase'], 'session': 1,
        'prompt_sha256': base.file_hash(folder / 'prompt.txt'),
        'prompt_bytes': (folder / 'prompt.txt').stat().st_size,
        'state_before_call_sha256': base.file_hash(folder / 'initial-state.json'),
        'common_contract_sha256': driver.native.core.digest(driver.native.explicit.CONTRACT + driver.native.PROCEDURE_CONTRACT),
        'command_sha256': driver.native.core.digest(driver.native.worker_command(cell, state))})
    solve = {'schema': 'trimem/lcb-solve-receipt/1.0', 'task_id': row['task_id'], 'arm': state['arm'],
        'state_sha256': base.file_hash(cell / 'state.json'), 'candidate_sha256': base.sha(state['candidate'].encode()),
        'status': 'SUBMITTED', 'sessions': [session], 'tool_actions': 2, 'public_test_runs': 1}
    base.write(cell / 'solve-receipt.json', solve)
    result = base._cell_result(cell, row, state['arm'], solve, state)
    result.update(phase=job['phase'], condition=job['condition'], ordinal=job['ordinal'],
                  generated_test_runs=0, procedure_applications=int(selected is not None))
    base.write(cell / 'cell-receipt.json', result)
    return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / 'source.py'
    source.write_text('# synthetic frozen implementation\n', encoding='utf-8')
    refs = [base.reference(source)]
    monkeypatch.setattr(base, 'implementation_references', lambda: refs)
    monkeypatch.setattr(driver.planner, 'verify_references', lambda refs: None)
    output = tmp_path / 'output'
    output.mkdir()
    cohorts = {name: {'task_ids': ['%s-%d' % (name, i) for i in range(count)]}
               for name, count in [('discovery', 2), ('verification', 2), ('validation', 3), ('test', 2)]}
    plan = {'schema': driver.planner.SCHEMA, 'experiment_id': 'synthetic-transfer',
            'cohorts': cohorts, 'source_references': {}, 'limits': driver.planner.LIMITS,
            'requested_model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'workers': 2, 'repeats': 1}
    jobs = driver.planner.schedule(plan)
    plan['schedule_sha256'] = driver.planner.digest(driver.planner.canonical(jobs))
    frozen = {'references': refs, 'implementation': refs, 'schedule': jobs}
    base.write(output / 'frozen-inputs.json', frozen)
    tasks = {identity: task(identity, 'train' if name in ('discovery', 'verification') else 'valid' if name == 'validation' else 'test')
             for name, cohort in cohorts.items() for identity in cohort['task_ids']}
    context = {'output': output, 'dataset_root': tmp_path / 'never-open-private', 'plan': plan,
        'frozen': frozen, 'tasks': tasks, 'config': {'owner_user_id': 'synthetic-owner', 'org_id': 'synthetic-org'},
        'runtime': {'native': {'model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'codex_executable': 'NEVER_RUN'}},
        'split': {}, 'public_manifest': {}}
    log, state = [], {'candidates': ['procedure-b', 'procedure-a'], 'final_status': 'READY'}
    monkeypatch.setattr(driver, 'load', lambda *args: context)
    def collect(ctx, job, bank, selected):
        if job['phase'] == 'DISCOVERY':
            assert bank is None and selected is None
        elif job['phase'] == 'VERIFICATION':
            assert bank['status'] == 'PROVISIONAL'
            assert selected == sorted(state['candidates'])[int(job['task_id'].rsplit('-', 1)[1]) % len(state['candidates'])]
        elif job['native_arm'] == 'ON':
            assert bank['status'] == 'READY' and selected is None
        else:
            assert bank is None and selected is None
        log.append(('collect', job['phase'], job['condition'], selected))
        return write_cell(ctx, job, bank, selected)
    monkeypatch.setattr(driver, 'collect', collect)
    original_seal = driver.seal_phase
    def seal(ctx, phase, rows):
        result = original_seal(ctx, phase, rows)
        log.append(('seal', phase))
        return result
    monkeypatch.setattr(driver, 'seal_phase', seal)
    def initialize(store, **kwargs):
        log.append(('initialize',))
        base.write(store / 'scope.json', {'synthetic': True})
    def ingest(store, *, phase, state_path, solve_reference):
        assert (output / phase / 'collection.json').is_file()
        assert phase in ('DISCOVERY', 'VERIFICATION')
        log.append(('ingest', phase))
    monkeypatch.setattr(driver.memory, 'initialize', initialize)
    monkeypatch.setattr(driver.memory, 'ingest_cell', ingest)
    def frozen_bank(store, destination, stage):
        phase = 'DISCOVERY' if stage == 'PROVISIONAL' else 'VERIFICATION'
        assert sum(item == ('ingest', phase) for item in log) == 2
        assert not any(item[0] == 'grade' for item in log)
        value = {'stage': stage, 'status': 'PROVISIONAL' if stage == 'PROVISIONAL' else state['final_status'],
                 'layer_counts': {'L3_personal_skills': int(state['final_status'] == 'READY')}}
        path = destination / ('bank-' + stage.lower() + '.json')
        base.write(path, value)
        log.append(('freeze', stage))
        return {**base.reference(path), **value}
    monkeypatch.setattr(driver, 'frozen_bank', frozen_bank)
    class Bank:
        def __init__(self, path): self.manifest = base.read(path)
        def candidate_ids(self): return state['candidates']
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(driver.memory, 'load_bank', lambda path, sha: Bank(path))
    def manifest(*args):
        phase = Path(args[-1]).name
        assert ('seal', phase) in log
        log.append(('private_authority', phase))
        return {'synthetic': True}
    monkeypatch.setattr(base, 'final_manifest', manifest)
    def grade(folder, identity, arm, row, *args):
        log.append(('grade', row['phase'], row['condition']))
        report_path = folder / 'private-grades' / base.cell_name(identity, arm) / 'report.json'
        base.write(report_path, {'results': [{'question_id': identity, 'status': 'GRADED', 'passed': True,
                                             'extracted_code_sha256': row['candidate_sha256']}]})
        result = {**row, 'grade_status': 'GRADED', 'passed': True, 'grade_reference': base.reference(report_path)}
        base.write(folder / 'cells' / base.cell_name(identity, arm) / 'cell-receipt.json', result)
        return result
    monkeypatch.setattr(base, 'grade_cell', grade)
    return SimpleNamespace(context=context, output=output, source=source, jobs=jobs,
                           log=log, state=state, collect=collect, grade=grade)


def run(setup, **kwargs):
    return driver.run('unused-plan', 'unused-runtime', setup.context['dataset_root'], setup.output, **kwargs)


def test_plan_api_conditions_have_distinct_cells_and_native_arm_mapping(setup):
    paths = [driver.cell_paths(setup.output, job)[1] for job in setup.jobs]
    assert len(paths) == len(set(paths)) == 17
    valid = [job for job in setup.jobs if job['phase'] == 'VALID']
    assert {driver.condition(job) for job in valid} == {'OFF', 'ON', 'L1ONLY'}
    assert {driver.native_arm(job) for job in valid if job['condition'] == 'L1ONLY'} == {'ON'}


def test_all_phases_seal_before_capture_or_grading_and_never_capture_eval(setup):
    result = run(setup)
    assert result['status'] == 'COMPLETE' and result['recorded_cells'] == 17
    assert result['planned_cells'] == 17 and result['hidden_feedback_to_model'] is False
    assert [item[1] for item in setup.log if item[0] == 'seal'] == list(driver.PHASES)
    assert [item[1] for item in setup.log if item[0] == 'ingest'] == ['DISCOVERY'] * 2 + ['VERIFICATION'] * 2
    first_grade = next(i for i, item in enumerate(setup.log) if item[0] == 'grade')
    assert setup.log.index(('freeze', 'FINAL')) < first_grade
    assert [item[1] for item in setup.log if item[0] == 'private_authority'] == ['VALID', 'TEST', 'DISCOVERY', 'VERIFICATION']
    assert all(value['unresolved_or_unexecuted'] == 0 for value in result['arms'].values())
    text = (setup.output / 'summary.json').read_text(encoding='utf-8')
    assert 'print(2)' not in text and 'Increment an integer.' not in text


@pytest.mark.parametrize('gate,recorded,reason', [
    ('no_candidates', 2, 'NO_PROVISIONAL_PROCEDURES'),
    ('no_skills', 4, 'NO_PROMOTED_PRIVATE_L3'),
])
def test_readiness_stops_without_extra_training_or_evaluation(setup, gate, recorded, reason):
    if gate == 'no_candidates': setup.state['candidates'] = []
    else: setup.state['final_status'] = 'NOT_READY'
    result = run(setup)
    assert result['status'] == 'NOT_READY' and result['reason'] == reason
    assert result['recorded_cells'] == recorded
    assert not any(item[0] == 'collect' and item[1] in ('VALID', 'TEST') for item in setup.log)
    assert all(value['rate'] is None for key, value in result['arms'].items() if key.startswith(('VALID/', 'TEST/')))


def test_prepare_has_no_collection_capture_or_private_access(setup):
    assert run(setup, prepare_only=True) == {'status': 'PREPARED', 'planned_cells': 17, 'model_calls': 0}
    assert setup.log == []


def test_partial_native_attempt_is_held_on_resume_without_second_solver(setup, monkeypatch):
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('synthetic interruption')
    monkeypatch.setattr(driver.native, 'solve_cell', interrupted)
    first = REAL_COLLECT(setup.context, setup.jobs[0], None, None)
    second = REAL_COLLECT(setup.context, setup.jobs[0], None, None)
    assert first['status'] == second['status'] == 'HELD' and calls == [1]
    assert first['passed'] is second['passed'] is None


@pytest.mark.parametrize('file', ['state.json', 'session-01/prompt.txt', 'session-01/initial-state.json', 'session-01/events.jsonl'])
def test_sealed_collection_rejects_bound_source_tamper(setup, file):
    rows = [setup.collect(setup.context, job, None, None) for job in setup.jobs if job['phase'] == 'DISCOVERY']
    ref = driver.seal_phase(setup.context, 'DISCOVERY', rows)
    _, cell = driver.cell_paths(setup.output, setup.jobs[0])
    path = cell / file
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(driver.TransferError, match='REFERENCED_BYTES_CHANGED'):
        driver.verify_collection(ref)


def test_final_source_guard_blocks_complete_after_last_grader(setup, monkeypatch):
    def changed(*args):
        result = setup.grade(*args)
        row = args[3]
        if row['phase'] == 'VERIFICATION' and row['task_id'] == 'verification-1':
            setup.source.write_text('# changed during final grading\n', encoding='utf-8')
        return result
    monkeypatch.setattr(base, 'grade_cell', changed)
    with pytest.raises(base.FrozenInputChanged):
        run(setup)
    assert base.read(setup.output / 'summary.json')['status'] != 'COMPLETE'


def test_protocol_failure_and_infrastructure_have_distinct_primary_outcomes():
    assert driver.primary({'status': 'GENERATION_ERROR', 'error_type': 'MissingSubmission'}) is False
    assert driver.primary({'status': 'GENERATION_ERROR', 'error_type': 'NativeProcessError'}) is None
    assert driver.primary({'status': 'HELD', 'passed': None}) is None
    assert driver.primary({'status': 'SUBMITTED', 'grade_status': 'GRADED', 'passed': False}) is False


@pytest.mark.parametrize('field,value', [('owner_user_id', 'wrong-owner'), ('org_id', 'wrong-org'), ('enabled_layers', ['L1'])])
def test_resumed_cell_cannot_change_private_scope_or_layer_condition(setup, field, value):
    job = next(row for row in setup.jobs if row['phase'] == 'VALID' and row['condition'] == 'ON')
    bank = {'path': 'synthetic-bank', 'sha256': 'a' * 64}
    row = write_cell(setup.context, job, bank, None)
    _, cell = driver.cell_paths(setup.output, job)
    state = base.read(cell / 'state.json')
    state[field] = value
    base.write(cell / 'state.json', state)
    solve = base.read(cell / 'solve-receipt.json')
    solve['state_sha256'] = base.file_hash(cell / 'state.json')
    base.write(cell / 'solve-receipt.json', solve)
    row['solve_reference'] = base.reference(cell / 'solve-receipt.json')
    base.write(cell / 'cell-receipt.json', row)
    with pytest.raises(driver.TransferError, match='RESUMED_CELL_SCOPE_CHANGED'):
        REAL_COLLECT(setup.context, job, bank, None)


def test_cached_grade_cannot_disagree_with_its_bound_report(setup):
    job = setup.jobs[0]
    row = write_cell(setup.context, job, None, None)
    folder, cell = driver.cell_paths(setup.output, job)
    report = folder / 'private-grades' / cell.name / 'report.json'
    base.write(report, {'results': [{'question_id': job['task_id'], 'status': 'GRADED',
                                    'passed': False, 'extracted_code_sha256': row['candidate_sha256']}]})
    row.update(grade_status='GRADED', passed=True, grade_reference=base.reference(report))
    base.write(cell / 'cell-receipt.json', row)
    with pytest.raises((driver.TransferError, base.FrozenInputChanged)):
        REAL_COLLECT(setup.context, job, None, None)


@pytest.mark.parametrize('mutation', ['cohort', 'budget'])
def test_self_consistent_plan_edit_fails_exact_derivation_before_input_loading(setup, monkeypatch, mutation):
    original = deepcopy(setup.context['plan'])
    original.update(selection_seed='synthetic-seed', source_references={
        key: {'path': 'synthetic-' + key + '.json'} for key in ('split', 'public_split', 'exclusion_config')})
    modified = deepcopy(original)
    if mutation == 'cohort':
        modified['cohorts']['validation']['task_ids'].reverse()
        modified['schedule_sha256'] = driver.planner.digest(driver.planner.canonical(driver.planner.schedule(modified)))
    else:
        modified['limits']['tool_actions'] += 1
    path = setup.output / 'tampered-plan.json'
    base.write(path, modified)
    monkeypatch.setattr(driver.planner, 'from_files', lambda *args, **kwargs: original)
    def forbidden(*args):
        pytest.fail('Altered preregistration reached dataset input loading')
    monkeypatch.setattr(base, 'load_inputs', forbidden)
    with pytest.raises(driver.TransferError, match='PLAN_DERIVATION_CHANGED'):
        REAL_LOAD(path, 'unused-runtime', setup.context['dataset_root'], setup.output)


def test_interrupted_grade_stays_null_without_invoking_grader_again(setup):
    rows = [setup.collect(setup.context, job, None, None) for job in setup.jobs if job['phase'] == 'DISCOVERY']
    ref = driver.seal_phase(setup.context, 'DISCOVERY', rows)
    _, cell = driver.cell_paths(setup.output, setup.jobs[0])
    base.write(cell / 'grade-start.json', {'collection_reference': ref,
                                         'solve_reference': rows[0]['solve_reference']})
    driver.grade_phase(setup.context, 'DISCOVERY', rows, ref, time.monotonic(), None)
    assert rows[0]['grade_status'] == 'INFRA_ERROR' and rows[0]['passed'] is None
    assert rows[0]['grade_error_type'] == 'InterruptedGradeNoRetry'
    assert driver.primary(rows[0]) is None
    assert len([item for item in setup.log if item[0] == 'grade']) == 1
