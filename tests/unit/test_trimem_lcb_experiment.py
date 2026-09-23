"""Synthetic pilot orchestration; no model, benchmark, network, or grader runs."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_lcb_experiment as experiment
import trimem_lcb_memory as memory
import trimem_lcb_native as native


def task(identity, partition):
    sample = {'input_output': json.dumps({'inputs': ['1\n'], 'outputs': ['2\n'], 'fn_name': None})}
    row = {'schema': memory.PUBLIC_TASK_SCHEMA, 'task_id': identity, 'question_id': identity,
        'split': partition, 'family_id': 'family-' + identity, 'question_title': 'Synthetic ' + identity,
        'prompt': 'Increment one integer. Synthetic identity ' + identity, 'starter_code': '',
        'public_test_cases': [{'input': '1\n', 'output': '2\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': sample}
    row['instruction_sha256'] = memory._hash({key: row[key] for key in ('question_title', 'prompt', 'starter_code')})
    row['public_tests_sha256'] = memory.public_tests_sha256(row)
    return row


def localref(path, root):
    ref = experiment.reference(path)
    ref['path'] = Path(path).relative_to(root).as_posix()
    return ref


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, 'EXPECTED_TASKS', 5)
    monkeypatch.setattr(experiment, 'PILOT_SIZE', 2)
    source = tmp_path / 'implementation.py'
    source.write_text('# synthetic implementation\n')
    monkeypatch.setattr(experiment, 'implementation_references', lambda: [experiment.reference(source)])
    data = tmp_path / 'data'
    (data / 'public').mkdir(parents=True)
    rows = [task('train-a', 'train'), task('train-b', 'train'), task('valid-a', 'valid'),
            task('valid-b', 'valid'), task('test-a', 'test')]
    public = data / 'public' / 'tasks.jsonl'
    public.write_bytes(b''.join(experiment.canonical(row) for row in rows))
    manifest = {'schema': 'trimem/lcb-public-dataset/1.0', 'dataset_id': 'synthetic',
        'revision': 'synthetic-pin', 'release': 'synthetic', 'task_count': 5, 'source_files': [],
        'public_tasks_reference': localref(public, data), 'counts': {'train': 2, 'valid': 2, 'test': 1, 'total': 5}}
    manifest_path = data / 'public-manifest.json'
    experiment.write(manifest_path, manifest)
    split = {'schema': 'trimem/lcb-split/1.0', 'dataset_id': 'synthetic', 'source_revision': 'synthetic-pin',
        'release': 'synthetic', 'train_ids': ['train-a', 'train-b'], 'valid_ids': ['valid-a', 'valid-b'],
        'test_ids': ['test-a'], 'train_pilot_ids': ['train-a', 'train-b'], 'pilot_ids': ['valid-a', 'valid-b'],
        'task_descriptors': [{key: row[key] for key in ('task_id', 'split', 'family_id', 'instruction_sha256', 'public_tests_sha256')} for row in rows],
        'dataset_reference': localref(manifest_path, data), 'public_tasks_reference': manifest['public_tasks_reference'],
        'source_hashes': [], 'counts': manifest['counts']}
    split_path = tmp_path / 'public_split.json'
    experiment.write(split_path, split)
    control = {'schema': 'trimem/lcb-official-infrastructure-controls/1.0', 'status': 'PASS',
        'model_calls': 0, 'memory_writes': 0, 'official_commit': experiment.UPSTREAM_COMMIT,
        'split_reference': {'sha256': experiment.file_hash(split_path)},
        'grader_reference': {'sha256': experiment.file_hash(experiment.ROOT / 'scripts' / 'trimem_lcb_grade.py')},
        'exclude_from_all_model_training_and_memory_capture': [],
        'runs': [{'label': label, 'status': 'COMPLETE', 'returncode': 0,
            'counts': {'graded': 2, 'passed': passed, 'not_graded': 0}}
            for label, passed in [('saved-positive', 2), ('invalid-syntax-negative', 0)]]}
    control_path = tmp_path / 'control.json'
    experiment.write(control_path, control)
    config = {'schema': 'trimem/lcb-pilot-config/1.0', 'experiment_id': 'synthetic-pilot',
        'org_id': 'synthetic-org', 'owner_user_id': 'fixed-owner', 'workers': 2,
        'requested_model': 'synthetic-model', 'reasoning_effort': 'low', 'limits': native.LIMITS,
        'split_path': str(split_path), 'split_sha256': experiment.file_hash(split_path),
        'final_split_path': str(tmp_path / 'final_split.json'),
        'official_control_receipt': str(control_path), 'official_control_receipt_sha256': experiment.file_hash(control_path),
        'infrastructure_control_excluded_train_ids': []}
    config_path, runtime_path = tmp_path / 'config.json', tmp_path / 'runtime.json'
    experiment.write(config_path, config)
    runtime = {'native': {'model': 'synthetic-model', 'reasoning_effort': 'low', 'codex_executable': 'never-run'},
        'execution': {'official_repo': '/synthetic/official', 'python': 'never-run',
            'scripts_root': str(experiment.ROOT / 'scripts'), 'prefix': []}}
    experiment.write(runtime_path, runtime)
    return SimpleNamespace(data=data, tasks=rows, config=config, config_path=config_path,
        runtime=runtime, runtime_path=runtime_path, split=split, split_path=split_path,
        manifest=manifest, source=source, output=tmp_path / 'output')


def public_result(cell, state, code):
    row = state['task']
    return {'schema': memory.PUBLIC_RESULT_SCHEMA, 'task_id': row['task_id'],
        'candidate_sha256': experiment.sha(code.encode()), 'public_tests_sha256': row['public_tests_sha256'],
        'command': ['lcb_public_tests', row['task_id'], row['public_tests_sha256']], 'status': 'PASS',
        'test_count': 1, 'passed_count': 1, 'failed_count': 0, 'not_run_count': 0,
        'exit_code': 0, 'timed_out': False, 'failure_kind': None, 'assertion_failures': 0}


def fake_solver(calls, *, failure=None):
    def solve(cell, before_model_call=None):
        before_model_call()
        state = native.read(cell / 'state.json')
        calls.append((state['task']['task_id'], state['arm']))
        if failure and failure(state):
            raise RuntimeError('synthetic interruption')
        code = 'print(int(input()) + 1)\n'
        native.apply_action(cell, {'tool': 'run_public_tests', 'arguments': {'code': code}}, public_runner=public_result)
        native.apply_action(cell, {'tool': 'finish', 'arguments': {'code': code, 'source_lesson': {
            'summary': 'Increment integer arithmetic after checking the public example.',
            'applicability': 'Increment integer arithmetic', 'procedure': ['Check the public integer example.'], 'trace_steps': [1]}}})
        state = native.read(cell / 'state.json')
        assert state['finished']
        result = {'schema': 'trimem/lcb-solve-receipt/1.0', 'task_id': state['task']['task_id'], 'arm': state['arm'],
            'status': 'SUBMITTED', 'error_type': None, 'candidate_sha256': experiment.sha(code.encode()),
            'state_sha256': experiment.file_hash(cell / 'state.json'),
            'sessions': [{'thread_ids': ['synthetic-thread-' + cell.name], 'usage': [{'input_tokens': 3, 'output_tokens': 2}]}],
            'wall_seconds': 1, 'tool_seconds': .25, 'tool_actions': 2, 'public_test_runs': 1}
        native.write(cell / 'solve-receipt.json', result)
        return result
    return solve


def run(value):
    return experiment.run_experiment(value.config_path, value.runtime_path, value.data, value.output)


def test_public_only_collection_captures_freezes_pairs_and_resumes_without_calls(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(native, 'solve_cell', fake_solver(calls))
    first = run(setup)
    assert len(calls) == 6
    assert first['status'] == 'INCOMPLETE' and first['private_grading_ready'] is False
    assert first['arms']['TRAIN']['captured'] == 2
    assert first['bank']['layer_counts']['training_tasks'] == 2
    assert first['arms']['OFF']['memory_injection_count'] == 0
    assert first['arms']['ON']['planned'] == 2 and first['paired']['pending'] == 2
    second = run(setup)
    assert len(calls) == 6 and second['bank'] == first['bank']
    scope = experiment.read(setup.output / 'training-memory' / 'scope.json')
    assert len(scope['tasks']) == 5 and scope['owner_user_id'] == 'fixed-owner'
    summary = (setup.output / 'summary.json').read_text()
    assert 'Increment one integer.' not in summary and 'print(int(input())' not in summary


def test_interrupted_solve_is_held_and_never_retried(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(native, 'solve_cell', fake_solver(calls, failure=lambda state: state['task']['task_id'] == 'valid-a' and state['arm'] == 'ON'))
    first = run(setup)
    assert first['arms']['ON']['held'] == 1
    run(setup)
    assert calls.count(('valid-a', 'ON')) == 1


def test_frozen_source_change_blocks_before_next_call(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(native, 'solve_cell', fake_solver(calls))
    run(setup)
    setup.source.write_text('# changed\n')
    with pytest.raises(experiment.FrozenInputChanged):
        run(setup)
    assert len(calls) == 6


def test_each_session_callback_detects_source_change(setup, monkeypatch):
    setup.config['workers'] = 1
    experiment.write(setup.config_path, setup.config)
    attempts = []
    def solve(cell, before_model_call):
        before_model_call()
        attempts.append('first-session')
        setup.source.write_text('# changed during session\n')
        before_model_call()
        pytest.fail('second session must not start')
    monkeypatch.setattr(native, 'solve_cell', solve)
    with pytest.raises(experiment.FrozenInputChanged):
        run(setup)
    assert attempts == ['first-session']


def test_exclusive_manager_lock(setup):
    with experiment.exclusive_lock(setup.output):
        with pytest.raises(experiment.ExperimentError):
            with experiment.exclusive_lock(setup.output):
                pytest.fail('concurrent manager acquired lock')


@pytest.mark.parametrize('field,value', [('requested_model', 'different'), ('reasoning_effort', 'high'), ('workers', 3)])
def test_configuration_identity_checked_before_model(setup, monkeypatch, field, value):
    setup.config[field] = value
    experiment.write(setup.config_path, setup.config)
    monkeypatch.setattr(native, 'solve_cell', lambda *a, **k: pytest.fail('model called'))
    with pytest.raises(experiment.ExperimentError):
        run(setup)


def publish_private(value):
    private_files = {}
    for row in value.tasks:
        path = value.data / 'private' / (row['task_id'] + '.json.gz')
        path.parent.mkdir(exist_ok=True)
        raw = experiment.canonical({'schema': 'trimem/lcb-evaluation-samples/1.0',
            'samples': [{'question_id': row['task_id'], 'sample': row['public_evaluation_sample']}]})
        path.write_bytes(gzip.compress(raw, mtime=0))
        private_files[row['task_id']] = {**localref(path, value.data), 'format': 'gzip-json'}
    manifest = {**value.manifest, 'schema': 'trimem/lcb-dataset/1.0', 'private_evaluation_files': private_files}
    manifest_path = value.data / 'dataset-manifest.json'
    experiment.write(manifest_path, manifest)
    final_split = {**value.split, 'dataset_reference': localref(manifest_path, value.data)}
    final_split_path = Path(value.config['final_split_path'])
    experiment.write(final_split_path, final_split)
    experiment.write(value.data / 'dataset-ready.json', {'schema': 'trimem/lcb-dataset-ready/1.0',
        'status': 'READY', 'identities_verified': True, 'private_file_count': 5,
        'manifest_reference': localref(manifest_path, value.data),
        'split_reference': experiment.reference(final_split_path),
        'public_split_reference': {'sha256': value.config['split_sha256']}})


def fake_grader(command, **kwargs):
    def arg(name):
        return command[command.index(name) + 1]
    predictions = experiment.read(arg('--predictions'))
    identity = predictions['expected_question_ids'][0]
    output = predictions['predictions'][0]['output']
    code = '\n'.join(output.split('\n')[1:-1])
    report = {'schema': 'trimem/lcb-grade-report/1.0',
        'results': [{'question_id': identity, 'status': 'GRADED', 'passed': True, 'extracted_code_sha256': experiment.sha(code.encode())}],
        'provenance': {'upstream_commit': experiment.UPSTREAM_COMMIT,
            'dataset_reference': {'sha256': arg('--dataset-sha256')},
            'predictions_reference': {'sha256': experiment.file_hash(arg('--predictions'))}},
        'settings': {'timeout_seconds': 6, 'workers': 1}, 'timings': {'overall_seconds': .2}}
    experiment.write(arg('--output'), report)
    return SimpleNamespace(returncode=0, stdout=b'{}', stderr=b'')


def test_pending_grades_resume_without_any_new_solves(setup, monkeypatch):
    calls, grades = [], []
    monkeypatch.setattr(native, 'solve_cell', fake_solver(calls))
    run(setup)
    publish_private(setup)
    def grade(command, **kwargs):
        grades.append(command)
        return fake_grader(command, **kwargs)
    monkeypatch.setattr(experiment.subprocess, 'run', grade)
    result = run(setup)
    assert len(calls) == 6 and len(grades) == 6
    assert result['status'] == 'COMPLETE' and result['paired']['completed'] == 2
    assert result['arms']['ON']['pass_at_1'] == 1
    again = run(setup)
    assert again['status'] == 'COMPLETE' and len(calls) == len(grades) == 6


def test_cached_verdict_tamper_is_rejected(setup, monkeypatch):
    monkeypatch.setattr(native, 'solve_cell', fake_solver([]))
    publish_private(setup)
    monkeypatch.setattr(experiment.subprocess, 'run', fake_grader)
    run(setup)
    path = setup.output / 'cells' / experiment.cell_name('train-a', 'TRAIN') / 'cell-receipt.json'
    value = experiment.read(path)
    value['passed'] = False
    experiment.write(path, value)
    with pytest.raises(experiment.FrozenInputChanged):
        run(setup)


@pytest.mark.parametrize('mutation', [
    {'passed': True, 'grade_status': 'GRADED'},
    {'capture_status': 'CAPTURED'},
])
def test_cached_claim_without_bound_reference_is_rejected(setup, monkeypatch, mutation):
    monkeypatch.setattr(native, 'solve_cell', fake_solver([]))
    run(setup)
    path = setup.output / 'cells' / experiment.cell_name('train-a', 'TRAIN') / 'cell-receipt.json'
    value = experiment.read(path)
    value.pop('capture_reference', None)
    value.update(mutation)
    experiment.write(path, value)
    with pytest.raises(experiment.FrozenInputChanged):
        run(setup)


def test_final_split_drift_rejected(setup, monkeypatch):
    monkeypatch.setattr(native, 'solve_cell', fake_solver([]))
    run(setup)
    publish_private(setup)
    path = Path(setup.config['final_split_path'])
    changed = experiment.read(path)
    changed['pilot_ids'] = list(reversed(changed['pilot_ids']))
    experiment.write(path, changed)
    with pytest.raises(experiment.FrozenInputChanged):
        run(setup)


def test_partial_manifest_without_ready_receipt_is_pending(setup, monkeypatch):
    (setup.data / 'dataset-manifest.json').write_text('{partial')
    monkeypatch.setattr(native, 'solve_cell', fake_solver([]))
    assert run(setup)['private_grading_ready'] is False


def test_protocol_failures_are_false_but_infrastructure_is_null():
    rows = [{'task_id': 'one', 'arm': 'OFF', 'status': 'GENERATION_ERROR', 'error_type': 'MissingSubmission', 'passed': None},
            {'task_id': 'one', 'arm': 'ON', 'status': 'GENERATION_ERROR', 'error_type': 'NativeProcessError', 'passed': None}]
    value = experiment.summarize({'experiment_id': 'synthetic'}, {'train_pilot_ids': ['train'], 'pilot_ids': ['one']},
        rows, None, private_ready=False, manager_seconds=0)
    assert rows[0]['resolved'] is False and rows[1]['resolved'] is None
    assert value['arms']['OFF']['resolved_rate'] == 0
    assert value['arms']['ON']['resolved_rate'] is None
    assert value['paired']['planned'] == 1 and value['paired']['completed'] == 0
