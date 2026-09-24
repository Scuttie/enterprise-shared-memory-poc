"""Synthetic manager sequencing and provenance; no models or official grading."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_experiment as driver

memory = driver.memory
REAL_COLLECT = driver.collect
REAL_GRADE = driver.grade
REAL_LOAD = driver.load


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(memory.canonical(value))


def synthetic_jobs():
    rows = [
        ('DISCOVERY', 'alpha-source', 'alpha', 'SOURCE'),
        ('DISCOVERY', 'beta-source', 'beta', 'SOURCE'),
        ('VERIFICATION', 'alpha-verify-0', 'alpha', 'SOURCE'),
        ('VERIFICATION', 'alpha-verify-1', 'alpha', 'SOURCE'),
        ('VERIFICATION', 'beta-verify', 'beta', 'SOURCE'),
    ]
    for phase, identities in [('VALID', ['alpha-valid', 'beta-valid']), ('TEST', ['alpha-test'])]:
        rows.extend((phase, identity, identity.split('-')[0], arm)
                    for identity in identities for arm in ('OFF', 'FULL'))
    return [{'phase': phase, 'task_id': task_id, 'project': project, 'arm': arm}
            for phase, task_id, project, arm in rows]


def authority(context, job, bank, selected):
    return {'job': job, 'bank': bank, 'selected_procedure_id': selected,
            'frozen_inputs_reference': memory.reference(context['output'] / 'frozen-inputs.json')}


def make_cell(context, job, bank=None, selected=None, *, status='SUBMITTED', error=None):
    """Write one complete synthetic native solve, then use the real row reducer."""
    cell = driver.cell_path(context, job)
    state = {'schema': 'deveval/repository-cell/1', 'task': context['tasks'][job['task_id']],
        'phase': job['phase'], 'condition': job['condition'],
        'arm': 'TRAIN' if job['condition'] == 'TRAIN' else ('OFF' if job['condition'] == 'OFF' else 'ON'),
        'runtime': context['runtime'], 'owner': context['owner'], 'bank': bank,
        'snapshot_reference': context['snapshots'][job['project']], 'selected_procedure_id': selected,
        'candidate': 'def target(x):\n    return x + 1\n', 'finished': status == 'SUBMITTED',
        'history': [], 'memory_injections': [], 'memory_decisions': [], 'source_lesson': None,
        'step': 1, 'session': 1, 'public_test_runs': 1, 'tool_seconds': .01,
        'limits': dict(driver.native.core.LIMITS)}
    initial = {**state, 'candidate': '', 'finished': False, 'step': 0, 'session': 0, 'public_test_runs': 0}
    write(cell / 'state.json', state)
    proof = authority(context, job, bank, selected)
    write(context['output'] / 'starts' / ('%03d.json' % job['ordinal']), proof)
    write(cell / 'attempt.json', proof)
    session = cell / 'session-01'
    write(session / 'initial-state.json', initial)
    (session / 'prompt.txt').write_text('Synthetic public prompt packet.\n', encoding='utf-8')
    (session / 'events.jsonl').write_bytes(memory.canonical({'type': 'thread.started', 'thread_id': 'synthetic-thread'}))
    (session / 'stderr.log').write_bytes(b'')
    receipt = {'session': 1, 'thread_ids': ['synthetic-thread'], 'benchmark_action_calls': 1,
        'events_sha256': memory.reference(session / 'events.jsonl')['sha256'],
        'stderr_sha256': memory.reference(session / 'stderr.log')['sha256']}
    write(session / 'receipt.json', receipt)
    write(session / 'prompt-receipt.json', {'task_id': job['task_id'], 'arm': state['arm'], 'session': 1,
        'prompt_sha256': memory.reference(session / 'prompt.txt')['sha256'],
        'prompt_bytes': (session / 'prompt.txt').stat().st_size,
        'state_before_call_sha256': memory.reference(session / 'initial-state.json')['sha256']})
    write(cell / 'generated-tests/step-001/receipt.json', {'status': 'PASS', 'synthetic': True})
    (cell / 'generated-tests/step-001/request.py').write_text('assert target(0) == 1\n', encoding='utf-8')
    solve = {'schema': 'trimem/lcb-solve-receipt/1.0', 'task_id': job['task_id'], 'arm': state['arm'],
        'state_sha256': memory.reference(cell / 'state.json')['sha256'],
        'candidate_sha256': hashlib.sha256(state['candidate'].encode()).hexdigest(),
        'status': status, 'error_type': error, 'sessions': [receipt], 'wall_seconds': .1,
        'tool_seconds': .01, 'tool_actions': 1}
    write(cell / 'solve-receipt.json', solve)
    return REAL_COLLECT(context, job, bank, selected)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    output.mkdir()
    source = tmp_path / 'synthetic-source.py'
    source.write_text('# frozen synthetic implementation\n', encoding='utf-8')
    raw = synthetic_jobs()
    plan = {'source_schedule': [r for r in raw if r['arm'] == 'SOURCE'],
            'target_schedule': [r for r in raw if r['arm'] != 'SOURCE']}
    jobs = driver.plan_schedule(plan)
    snapshots = {}
    for project in ('alpha', 'beta'):
        snapshot = tmp_path / (project + '-snapshot.json')
        write(snapshot, {'project': project})
        snapshots[project] = memory.reference(snapshot)
    frozen = {'references': [memory.reference(source)], 'schedule': jobs}
    write(output / 'frozen-inputs.json', frozen)
    context = {'output': output, 'frozen': frozen, 'owner': 'synthetic-owner', 'plan': plan,
        'plan_reference': memory.reference(output / 'frozen-inputs.json'), 'snapshots': snapshots,
        'runtime': {'native': {'model': 'synthetic-model', 'reasoning_effort': 'low'},
                    'deveval': {'metadata': 'NEVER_OPEN', 'evaluator': 'NEVER_RUN', 'pristine_source_root': 'NEVER_OPEN'}},
        'tasks': {row['task_id']: {'task_id': row['task_id'], 'project': row['project'],
            'namespace': row['task_id'], 'completion_path': row['project'] + '/' + row['task_id'] + '.py',
            'requirement': {'Functionality': 'Synthetic integer increment.', 'Arguments': 'x: int'}} for row in jobs}}
    log, state = [], {'candidates': [{'procedure_id': 'procedure-z', 'project': 'alpha'},
                                   {'procedure_id': 'procedure-a', 'project': 'alpha'}], 'l3_status': 'READY'}
    monkeypatch.setattr(driver, 'load', lambda *args: context)
    def collect(ctx, job, bank, selected):
        log.append(('collect', job['phase'], job['task_id'], job['condition'], selected, bank))
        return make_cell(ctx, job, bank, selected)
    monkeypatch.setattr(driver, 'collect', collect)
    real_seal = driver.seal
    def seal(ctx, phase, rows):
        ref = real_seal(ctx, phase, rows)
        log.append(('seal', phase))
        return ref
    monkeypatch.setattr(driver, 'seal', seal)
    def capture(cell, **kwargs):
        assert kwargs['phase'] in ('DISCOVERY', 'VERIFICATION')
        assert ('seal', kwargs['phase']) in log
        assert not any(item[0] == 'grade' for item in log)
        log.append(('capture', kwargs['phase'], kwargs['task_id']))
        return {'task_id': kwargs['task_id'], 'phase': kwargs['phase']}
    monkeypatch.setattr(memory, 'capture', capture)
    def freeze(path, *, owner, stage, captures, plan_reference):
        assert owner == context['owner']
        assert all(row['phase'] in ('DISCOVERY', 'VERIFICATION') for row in captures)
        assert len(captures) == (2 if stage == 'PROVISIONAL' else 5)
        assert not any(item[0] == 'grade' for item in log)
        write(path, {'stage': stage, 'candidates': state['candidates'], 'l3_status': state['l3_status']})
        log.append(('freeze', stage))
        return memory.reference(path)
    monkeypatch.setattr(memory, 'freeze', freeze)
    monkeypatch.setattr(memory, 'load', lambda ref, **kwargs: memory.read(memory.checked(ref)))
    def grade(ctx, job, row, collection_ref):
        assert all(('seal', phase) in log for phase in driver.PHASES)
        assert len([entry for entry in log if entry[0] == 'collect']) == len(jobs)
        driver.verify_collection(collection_ref)
        log.append(('grade', job['phase'], job['task_id'], job['condition']))
        return {**row, 'grade_status': 'GRADED', 'passed': True}
    monkeypatch.setattr(driver, 'grade', grade)
    return SimpleNamespace(context=context, output=output, source=source, jobs=jobs,
        log=log, state=state, collect=collect, grade=grade)


def run(setup, **kwargs):
    return driver.run('unused-plan', 'unused-runtime', 'unused-snapshots', 'unused-eligibility', setup.output, **kwargs)


def test_source_conditions_and_target_arms_have_distinct_cell_identity(setup):
    assert [j['condition'] for j in setup.jobs[:5]] == ['TRAIN'] * 2 + ['PROVISIONAL'] * 3
    assert len({driver.cell_path(setup.context, j) for j in setup.jobs}) == len(setup.jobs)
    assert [j['ordinal'] for j in setup.jobs] == list(range(1, 12))


def test_all_collections_sealed_before_any_private_grading_and_only_source_captured(setup):
    result = run(setup)
    assert result['status'] == 'COMPLETE' and result['recorded_cells'] == result['planned_cells'] == 11
    assert [item[1] for item in setup.log if item[0] == 'seal'] == list(driver.PHASES)
    assert [item[1] for item in setup.log if item[0] == 'capture'] == ['DISCOVERY'] * 2 + ['VERIFICATION'] * 3
    assert [item[1] for item in setup.log if item[0] == 'freeze'] == ['PROVISIONAL', 'FINAL']
    assert result['private_feedback_to_model'] is False
    assert all(group['success_rate'] == 1 for group in result['arms'].values())
    summary = (setup.output / 'summary.json').read_text(encoding='utf-8')
    assert 'def target' not in summary and 'Synthetic integer increment' not in summary


def test_verification_preassignment_is_sorted_project_local_and_off_has_no_bank(setup):
    run(setup)
    collected = [item for item in setup.log if item[0] == 'collect']
    verification = [item for item in collected if item[1] == 'VERIFICATION']
    assert [item[4] for item in verification] == ['procedure-a', 'procedure-z', None]
    for _, phase, _, condition, selected, bank in collected:
        if condition in ('TRAIN', 'OFF'):
            assert bank is None and selected is None
        elif phase != 'VERIFICATION':
            assert memory.read(bank['path'])['stage'] == 'FINAL' and selected is None


def test_no_l3_candidates_does_not_cancel_repository_context_evaluation(setup):
    setup.state.update(candidates=[], l3_status='NOT_READY')
    result = run(setup)
    assert result['status'] == 'COMPLETE' and result['recorded_cells'] == 11
    assert result['l3_absence_does_not_skip_l2_evaluation'] is True
    assert all(item[4] is None for item in setup.log if item[0] == 'collect')


def test_two_workers_allowed_but_same_task_arms_never_overlap(setup, monkeypatch):
    original = driver.ThreadPoolExecutor
    workers = []
    def factory(*args, **kwargs):
        workers.append(kwargs['max_workers'])
        return original(*args, **kwargs)
    monkeypatch.setattr(driver, 'ThreadPoolExecutor', factory)
    run(setup)
    assert max(workers) == 2 and workers[-3:] == [1, 1, 1]


def test_prepare_performs_no_collection_capture_or_grading(setup):
    assert run(setup, prepare_only=True) == {'status': 'PREPARED', 'planned_cells': 11, 'model_calls': 0}
    assert setup.log == []


@pytest.mark.parametrize('relative', [
    'state.json', 'session-01/prompt.txt', 'session-01/initial-state.json',
    'session-01/events.jsonl', 'generated-tests/step-001/receipt.json',
])
def test_sealed_collection_detects_solver_and_generated_evidence_tamper(setup, relative):
    jobs = [j for j in setup.jobs if j['phase'] == 'DISCOVERY']
    rows = [make_cell(setup.context, j) for j in jobs]
    ref = driver.seal(setup.context, 'DISCOVERY', rows)
    path = driver.cell_path(setup.context, jobs[0]) / relative
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='REFERENCED_BYTES_CHANGED'):
        driver.verify_collection(ref)


def test_incomplete_or_duplicated_collection_cannot_be_sealed(setup):
    row = make_cell(setup.context, setup.jobs[0])
    for rows in ([row], [row, row]):
        with pytest.raises(ValueError, match='COLLECTION_INCOMPLETE'):
            driver.seal(setup.context, 'DISCOVERY', rows)


def test_partial_attempt_held_without_automatic_model_retry(setup, monkeypatch):
    calls = []
    def initialize(cell, **kwargs):
        Path(cell).mkdir(parents=True)
        write(Path(cell) / 'state.json', {'synthetic_partial': True})
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('Synthetic transport interruption')
    monkeypatch.setattr(driver.native, 'initialize', initialize)
    monkeypatch.setattr(driver.native, 'solve', interrupted)
    first = REAL_COLLECT(setup.context, setup.jobs[0], None, None)
    second = REAL_COLLECT(setup.context, setup.jobs[0], None, None)
    assert first['status'] == second['status'] == 'HELD' and calls == [1]
    assert first['passed'] is second['passed'] is None


def test_held_batch_prevents_capture_and_all_private_grading(setup, monkeypatch):
    def held(ctx, job, bank, selected):
        return {**job, 'status': 'HELD', 'passed': None, 'error_type': 'InterruptedAttemptNoRetry'}
    monkeypatch.setattr(driver, 'collect', held)
    result = run(setup)
    assert result['status'] == 'HELD' and result['recorded_cells'] == 2
    assert not any(item[0] in ('seal', 'capture', 'freeze', 'grade') for item in setup.log)


@pytest.mark.parametrize('error,expected', [('MissingSubmission', False), ('TaskTimeout', False), ('NativeProcessError', None)])
def test_model_protocol_failure_and_infrastructure_have_distinct_fixed_denominator_outcomes(setup, error, expected):
    row = make_cell(setup.context, setup.jobs[0], status='GENERATION_ERROR', error=error)
    assert row['passed'] is expected and row['grade_status'] == 'NOT_GRADED'
    summary = driver.checkpoint(setup.context, [row], 'DISCOVERY', 'COLLECTING', time.monotonic())
    group = summary['arms']['DISCOVERY/TRAIN']
    assert group['planned'] == 2 and group['success_rate'] is None
    assert group['failed'] == int(expected is False)


@pytest.mark.parametrize('field,value', [('owner', 'other-owner'), ('condition', 'L1_ONLY'), ('bank', {'forged': True})])
def test_completed_solve_reuse_cannot_change_owner_condition_or_bank(setup, field, value):
    job = setup.jobs[0]
    make_cell(setup.context, job)
    cell = driver.cell_path(setup.context, job)
    state = memory.read(cell / 'state.json')
    state[field] = value
    write(cell / 'state.json', state)
    solve = memory.read(cell / 'solve-receipt.json')
    solve['state_sha256'] = memory.reference(cell / 'state.json')['sha256']
    write(cell / 'solve-receipt.json', solve)
    with pytest.raises(ValueError, match='RESUMED_CELL_SCOPE_CHANGED'):
        REAL_COLLECT(setup.context, job, None, None)


def test_interrupted_grade_remains_null_and_never_starts_second_subprocess(setup, monkeypatch):
    rows = [make_cell(setup.context, j) for j in setup.jobs[:2]]
    ref = driver.seal(setup.context, 'DISCOVERY', rows)
    (driver.cell_path(setup.context, setup.jobs[0]) / 'private-grade').mkdir()
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: pytest.fail('Partial grade must not retry'))
    for _ in range(2):
        result = REAL_GRADE(setup.context, setup.jobs[0], rows[0], ref)
        assert result['grade_status'] == 'INFRA_ERROR' and result['passed'] is None
        assert result['grade_error_type'] == 'InterruptedGradeNoRetry'


def test_final_source_guard_blocks_complete_when_last_grader_changes_source(setup, monkeypatch):
    def changed(ctx, job, row, ref):
        answer = setup.grade(ctx, job, row, ref)
        if job['ordinal'] == len(setup.jobs):
            setup.source.write_text('# changed after grading\n', encoding='utf-8')
        return answer
    monkeypatch.setattr(driver, 'grade', changed)
    with pytest.raises(ValueError, match='REFERENCED_BYTES_CHANGED'):
        run(setup)
    assert memory.read(setup.output / 'summary.json')['status'] != 'COMPLETE'


def test_existing_cell_cannot_invent_its_start_authority_on_resume(setup):
    job = setup.jobs[0]
    make_cell(setup.context, job)
    (setup.output / 'starts' / ('%03d.json' % job['ordinal'])).unlink()
    with pytest.raises(ValueError, match='UNBOUND_PREEXISTING_CELL'):
        REAL_COLLECT(setup.context, job, None, None)


@pytest.fixture
def authority_inputs(tmp_path, monkeypatch):
    """Complete local authority with fake metadata derivation, never real tasks."""
    root = tmp_path / 'authority'
    root.mkdir()
    monkeypatch.setattr(driver, 'ROOT', root)
    for name in ('trimem_lcb_native.py', 'trimem_lcb_memory.py', 'trimem_lcb_experiment.py',
                 'deveval_prepare.py', 'deveval_model_gateway.py', 'deveval_generated_tests.py',
                 'deveval_repository_plan.py', 'deveval_repository_context.py',
                 'deveval_repository_memory.py', 'deveval_repository_native.py',
                 'deveval_repository_grade.py', 'deveval_repository_experiment.py',
                 'deveval_repository_grade_integrity.py', 'deveval_setup_offline.py'):
        path = root / 'scripts' / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('# synthetic implementation\n', encoding='utf-8')
    def portable(path):
        ref = memory.reference(path)
        return {**ref, 'path': path.relative_to(root).as_posix()}
    for name in ('metadata.jsonl', 'planner.py', 'asset.py', 'source.tar', 'fake-codex.exe'):
        (root / name).write_bytes(b'synthetic fixture bytes\n')
    task = {'task_id': 'alpha.target', 'namespace': 'alpha.target', 'project': 'alpha',
        'completion_path': 'alpha/main.py', 'requirement': {'Functionality': 'Synthetic function.', 'Arguments': 'x'}}
    plan = {'schema': 'deveval/repository-plan/1',
        'metadata_reference': portable(root / 'metadata.jsonl'),
        'planner_reference': portable(root / 'planner.py'), 'asset_helper_reference': portable(root / 'asset.py'),
        'source_archive_reference': portable(root / 'source.tar'),
        'projects': [{'project': 'alpha'}], 'tasks': [{
            'task_id': task['task_id'], 'project': 'alpha',
            'public_requirement_sha256': hashlib.sha256(memory.canonical(task['requirement'])).hexdigest()}],
        'source_schedule': [{'phase': 'DISCOVERY', 'task_id': task['task_id'], 'project': 'alpha', 'arm': 'SOURCE'}],
        'target_schedule': [], 'model': {'model': 'synthetic-model', 'reasoning_effort': 'low'}}
    plan_path = root / 'plan.json'
    write(plan_path, plan)
    plan_ref = memory.reference(plan_path)
    monkeypatch.setattr(driver.planner, 'metadata_rows', lambda path: [{'synthetic': True}])
    monkeypatch.setattr(driver.planner, 'build_plan', lambda *args, **kwargs: deepcopy(plan))
    view_root = root / 'snapshot'
    write(view_root / 'snapshot.json', {'project': 'alpha', 'plan_reference': plan_ref})
    write(view_root / 'relations.json', {'relations': []})
    visible = view_root / 'repository/helper.py'
    visible.parent.mkdir()
    visible.write_text('def helper(x):\n    return x + 1\n', encoding='utf-8')
    view = SimpleNamespace(root=view_root,
        manifest={'project': 'alpha', 'plan_reference': plan_ref},
        files={'helper.py': memory.reference(visible)}, public_task=lambda identity: deepcopy(task))
    monkeypatch.setattr(driver.repository, 'load_snapshot', lambda ref: view)
    snapshots_path = root / 'snapshots.json'
    write(snapshots_path, {'alpha': memory.reference(view_root / 'snapshot.json')})
    for name, value in [('runtime-lock.json', {'synthetic': True}), ('inputs.json', {'files': []})]:
        write(root / name, value)
    runtime = {'native': {'model': 'synthetic-model', 'reasoning_effort': 'low',
                          'codex_executable': str(root / 'fake-codex.exe')},
        'deveval': {'pristine_source_root': str(root / 'unused-pristine')}}
    runtime_path = root / 'runtime.json'
    write(runtime_path, runtime)
    cells = []
    for arm in ('reference', 'assertion_negative'):
        negative = arm == 'assertion_negative'
        value = {'schema': 'deveval-native-control-cell/1', 'task_id': task['task_id'], 'project': 'alpha',
            'arm': arm, 'official_result': 'Error' if negative else 'Pass', 'source_restored': True,
            'junit': {'negative_marker_seen': negative, 'unconfirmed_error_nodes': 0,
                      'confirmed_negative_failure_nodes': int(negative), 'confirmed_negative_error_nodes': 0,
                      'failures': int(negative), 'errors': 0}}
        path = root / ('control-' + arm + '.json')
        write(path, value)
        cells.append({**value, 'receipt_reference': memory.reference(path)})
    eligibility = {'status': 'PASS', 'model_calls': 0, 'pristine_unchanged': True,
        'working_source_tests_unchanged': True, 'cells': cells, 'reference_pass': 1, 'negative_confirmed': 1,
        'plan_reference': plan_ref, 'runtime_lock_reference': memory.reference(root / 'runtime-lock.json'),
        'inputs_reference': memory.reference(root / 'inputs.json')}
    eligibility_path = root / 'eligibility.json'
    write(eligibility_path, eligibility)
    return SimpleNamespace(root=root, plan=plan, plan_path=plan_path, runtime_path=runtime_path,
        snapshots_path=snapshots_path, eligibility=eligibility, eligibility_path=eligibility_path,
        visible=visible, output=root / 'output')


def authority_load(fixture):
    return REAL_LOAD(fixture.plan_path, fixture.runtime_path, fixture.snapshots_path,
                     fixture.eligibility_path, fixture.output)


def test_frozen_authority_includes_visible_repository_files_before_model_call(authority_inputs):
    context = authority_load(authority_inputs)
    assert memory.reference(authority_inputs.visible) in context['frozen']['references']
    authority_inputs.visible.write_text('def helper(x):\n    return 999\n', encoding='utf-8')
    with pytest.raises(ValueError, match='REFERENCED_BYTES_CHANGED'):
        driver.verify(context)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate'])
def test_negative_control_count_cannot_replace_exact_per_task_evidence(authority_inputs, mutation):
    value = deepcopy(authority_inputs.eligibility)
    negative = value['cells'][1]
    value['cells'] = value['cells'][:1] if mutation == 'missing' else [value['cells'][0], negative, negative]
    write(authority_inputs.eligibility_path, value)
    with pytest.raises(ValueError, match='ELIGIBILITY|CONTROL'):
        authority_load(authority_inputs)


@pytest.mark.parametrize('mutation', ['model', 'schedule'])
def test_plan_edits_reject_exact_derivation_before_eligibility(authority_inputs, mutation):
    plan = deepcopy(authority_inputs.plan)
    if mutation == 'model':
        plan['model']['reasoning_effort'] = 'high'
    else:
        plan['source_schedule'][0]['phase'] = 'VERIFICATION'
    write(authority_inputs.plan_path, plan)
    with pytest.raises(ValueError, match='PLAN_DERIVATION_CHANGED'):
        authority_load(authority_inputs)


@pytest.fixture
def cached_grade(setup):
    import deveval_prepare as assets
    rows = [make_cell(setup.context, job) for job in setup.jobs[:2]]
    ref = driver.seal(setup.context, 'DISCOVERY', rows)
    job, row = setup.jobs[0], rows[0]
    cell = driver.cell_path(setup.context, job)
    folder = cell / 'private-grade'
    setup.context['plan']['metadata_reference'] = {'sha256': 'a' * 64}
    request = {'task_id': job['task_id'], 'project': job['project'], 'candidate_sha256': row['candidate_sha256'],
        'candidate_path': driver.native.core.mapped_path(folder / 'candidate.py', setup.context['runtime']),
        'metadata': 'NEVER_OPEN', 'metadata_sha256': 'a' * 64, 'evaluator': 'NEVER_RUN',
        'pristine_source_root': 'NEVER_OPEN', 'collection_sha256': ref['sha256']}
    write(folder / 'request.json', request)
    (folder / 'candidate.py').write_bytes(memory.read(cell / 'state.json')['candidate'].encode())
    receipt = {'schema': 'deveval-private-grade/1', 'task_id': job['task_id'], 'project': job['project'],
        'candidate_sha256': row['candidate_sha256'], 'request_candidate_sha256': row['candidate_sha256'],
        'request_reference': memory.reference(folder / 'request.json'), 'status': 'GRADED', 'passed': True,
        'official_result': 'Pass', 'process_exit_code': 0, 'timed_out': False, 'source_restored': True,
        'pristine_source_unchanged': True, 'unexpected_file_count': 0, 'metadata_sha256': 'a' * 64,
        'evaluator_reference': {'sha256': assets.UPSTREAM_FILES['pass_k.py']}, 'elapsed_total_seconds': .2}
    write(folder / 'receipt.json', receipt)
    row.update(grade_status='GRADED', passed=True, grade_reference=memory.reference(folder / 'receipt.json'), grade_seconds=.2)
    write(cell / 'cell-receipt.json', row)
    return SimpleNamespace(setup=setup, job=job, row=row, ref=ref, cell=cell, folder=folder,
                           request=request, receipt=receipt)


def test_valid_completed_grade_reused_without_model_or_grader(cached_grade, monkeypatch):
    fixture = cached_grade
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: pytest.fail('Cached grade must not execute'))
    assert REAL_GRADE(fixture.setup.context, fixture.job, fixture.row, fixture.ref) == fixture.row
    assert REAL_COLLECT(fixture.setup.context, fixture.job, None, None)['passed'] is True


@pytest.mark.parametrize('mutation', ['other_condition_path', 'metadata', 'collection', 'null_graded'])
def test_cached_grade_cannot_change_condition_request_authority_or_verdict(cached_grade, mutation):
    fixture = cached_grade
    row = deepcopy(fixture.row)
    if mutation == 'other_condition_path':
        elsewhere = fixture.setup.output / 'other-condition/receipt.json'
        write(elsewhere, fixture.receipt)
        row['grade_reference'] = memory.reference(elsewhere)
    else:
        request, receipt = deepcopy(fixture.request), deepcopy(fixture.receipt)
        if mutation == 'metadata':
            request['metadata'] = 'SUBSTITUTED_TEST_AUTHORITY'
        elif mutation == 'collection':
            request['collection_sha256'] = 'b' * 64
        else:
            receipt['passed'] = row['passed'] = None
        write(fixture.folder / 'request.json', request)
        receipt['request_reference'] = memory.reference(fixture.folder / 'request.json')
        write(fixture.folder / 'receipt.json', receipt)
        row['grade_reference'] = memory.reference(fixture.folder / 'receipt.json')
    with pytest.raises(ValueError, match='GRADE'):
        REAL_GRADE(fixture.setup.context, fixture.job, row, fixture.ref)


@pytest.mark.parametrize('field', ['source_manifest_path', 'source_manifest_sha256'])
def test_runtime_pristine_authority_must_match_eligibility_manifest(authority_inputs, field):
    fixture = authority_inputs
    runtime = memory.read(fixture.runtime_path)
    pinned = fixture.eligibility['inputs_reference']
    runtime['deveval'].update(source_manifest_path=pinned['path'], source_manifest_sha256=pinned['sha256'])
    runtime['deveval'][field] = str(fixture.root / 'substituted-inputs.json') if field.endswith('path') else 'b' * 64
    write(fixture.runtime_path, runtime)
    with pytest.raises(ValueError, match='PRISTINE_RUNTIME_AUTHORITY_CHANGED'):
        authority_load(fixture)


def test_grade_request_binds_manifest_and_uses_distinct_native_workspaces_per_condition(setup):
    context = setup.context
    settings = context['runtime']['deveval']
    settings.update(grade_work_root='/native-ext4/synthetic-grade-work',
                    source_manifest_path='/native-ext4/pinned-inputs.json', source_manifest_sha256='a' * 64)
    context['plan']['metadata_reference'] = {'sha256': 'b' * 64}
    jobs = [job for job in setup.jobs if job['task_id'] == 'alpha-valid']
    requests = [driver.expected_grade_request(context, job, {'candidate_sha256': 'c' * 64}, {'sha256': 'd' * 64})
                for job in jobs]
    assert len(requests) == 2
    assert requests[0]['working_source_root'] != requests[1]['working_source_root']
    for request in requests:
        assert request['working_source_root'].startswith('/native-ext4/synthetic-grade-work/')
        assert request['working_source_root'].endswith('/Source_Code')
        assert request['source_manifest_path'] == settings['source_manifest_path']
        assert request['source_manifest_sha256'] == settings['source_manifest_sha256']
    assert driver.expected_grade_request(context, jobs[0], {'candidate_sha256': 'c' * 64}, {'sha256': 'd' * 64}) == requests[0]


def dependency_authority(tmp_path):
    inputs = tmp_path / 'controls/inputs.json'
    control = tmp_path / 'eligibility.json'
    write(inputs, {'synthetic': True})
    plan_reference = {'path': 'synthetic-plan.json', 'sha256': 'a' * 64, 'bytes': 1}
    write(control, {'synthetic': True, 'plan_reference': plan_reference})
    package = inputs.parent / 'Source_Code/alpha/.eggs/dependency/module.py'
    package.parent.mkdir(parents=True)
    package.write_text('VALUE = 1\n', encoding='utf-8')
    file = memory.reference(package)
    row = {'path': '.eggs/dependency/module.py', 'sha256': file['sha256'], 'bytes': file['bytes'],
           'control_file_reference': file}
    value = {'schema': 'deveval/grade-generated-dependencies/1', 'project': 'alpha',
             'control_plan_reference': plan_reference,
             'control_receipt_reference': memory.reference(control), 'control_inputs_reference': memory.reference(inputs),
             'files': [row], 'files_sha256': hashlib.sha256(memory.canonical([
                 {key: row[key] for key in ('path', 'bytes', 'sha256')}])).hexdigest()}
    allowlist = tmp_path / 'allowlist.json'
    write(allowlist, value)
    runtime = {'deveval': {'generated_dependency_allowlists': {'alpha': memory.reference(allowlist)}}}
    return runtime, memory.reference(control), memory.reference(inputs), allowlist, package


def test_control_setup_dependencies_cannot_be_omitted_before_model_collection(tmp_path):
    runtime, control, inputs, _, _ = dependency_authority(tmp_path)
    runtime['deveval'].clear()
    with pytest.raises(ValueError, match='CONTROL_SETUP_DEPENDENCIES_NOT_BOUND'):
        driver.grade_dependency_references(runtime, {'alpha'}, control, inputs)


def test_dependency_control_scope_and_bytes_are_frozen(tmp_path):
    runtime, control, inputs, _, package = dependency_authority(tmp_path)
    refs = driver.grade_dependency_references(runtime, {'alpha'}, control, inputs)
    assert memory.reference(package) in refs
    driver.verify({'frozen': {'references': refs}})
    package.write_text('VALUE = 2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='REFERENCED_BYTES_CHANGED'):
        driver.verify({'frozen': {'references': refs}})


def test_dependency_allowlist_must_bind_the_admitted_control_cohort(tmp_path):
    runtime, control, inputs, allowlist, _ = dependency_authority(tmp_path)
    alternate = tmp_path / 'alternate-controls.json'
    write(alternate, {'synthetic': 'other cohort'})
    value = memory.read(allowlist)
    value['control_receipt_reference'] = memory.reference(alternate)
    write(allowlist, value)
    runtime['deveval']['generated_dependency_allowlists']['alpha'] = memory.reference(allowlist)
    with pytest.raises(ValueError, match='GRADE_DEPENDENCY_CONTROL_CHANGED'):
        driver.grade_dependency_references(runtime, {'alpha'}, control, inputs)


def test_rehashed_allowlist_cannot_omit_existing_control_dependency(tmp_path):
    runtime, control, inputs, allowlist, _ = dependency_authority(tmp_path)
    value = memory.read(allowlist)
    value['files'] = []
    value['files_sha256'] = hashlib.sha256(memory.canonical([])).hexdigest()
    write(allowlist, value)
    runtime['deveval']['generated_dependency_allowlists']['alpha'] = memory.reference(allowlist)
    with pytest.raises(ValueError, match='GRADE_DEPENDENCY_SET_CHANGED'):
        driver.grade_dependency_references(runtime, {'alpha'}, control, inputs)


def test_allowlist_historical_plan_must_match_control_authority(tmp_path):
    runtime, control, inputs, allowlist, _ = dependency_authority(tmp_path)
    value = memory.read(allowlist)
    value['control_plan_reference']['sha256'] = 'b' * 64
    write(allowlist, value)
    runtime['deveval']['generated_dependency_allowlists']['alpha'] = memory.reference(allowlist)
    with pytest.raises(ValueError, match='GRADE_DEPENDENCY_PLAN_CHANGED'):
        driver.grade_dependency_references(runtime, {'alpha'}, control, inputs)


def test_grade_request_binds_project_allowlist_and_offline_support(setup):
    context = setup.context
    context['plan']['metadata_reference'] = {'sha256': 'a' * 64}
    allow = {'path': '/native/alpha-allowlist.json', 'sha256': 'b' * 64, 'bytes': 10}
    support = {'path': '/native/support/manifest.json', 'sha256': 'c' * 64, 'bytes': 20}
    context['runtime']['deveval'].update(generated_dependency_allowlists={'alpha': allow},
                                        setup_support_reference=support)
    request = driver.expected_grade_request(context, setup.jobs[0], {'candidate_sha256': 'd' * 64}, {'sha256': 'e' * 64})
    assert request['generated_dependency_allowlist_reference'] == allow
    assert request['setup_support_reference'] == support
