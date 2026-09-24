"""Synthetic bounded-tool checks; no model calls or hidden grading."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_transfer_native as native


def task():
    sample = {'input_output': json.dumps({'inputs': ['2 5\n'], 'outputs': ['7\n'], 'fn_name': None})}
    return {'schema': 'trimem/lcb-public-task/1.0', 'task_id': 'synthetic-transfer',
        'question_id': 'synthetic-transfer', 'question_title': 'Synthetic sum',
        'prompt': 'Print the sum of two integers.', 'starter_code': '',
        'public_test_cases': [{'input': '2 5\n', 'output': '7\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': sample, 'public_tests_sha256': native.digest(sample),
        'instruction_sha256': 'a' * 64, 'family_id': 'b' * 64,
        'platform': 'synthetic', 'contest_id': '', 'contest_date': '2024-01-01',
        'difficulty': 'easy', 'split': 'train'}


@pytest.fixture
def cell(tmp_path):
    path = tmp_path / 'cell'
    runtime = {'native': {'codex_executable': 'NEVER_CALLED', 'model': 'gpt-5.6-luna', 'reasoning_effort': 'low'},
               'execution': {'python': 'unused', 'scripts_root': '/unused', 'official_repo': '/unused'}}
    native.initialize_cell(path, task(), 'TRAIN', runtime)
    return path


def args():
    return {'code': 'a,b=map(int,input().split());print(a+b)',
        'cases': [{'input': '0 0\n', 'output': '0\n'}, {'input': '-2 2\n', 'output': '0\n'}],
        'method': 'boundary_cases', 'rationale': 'Check zero and cancellation.'}


def custom_ok(cell, state, arg):
    return {'schema': 'lcb/personal-procedure-test/1', 'task_id': state['task']['task_id'],
        'candidate_sha256': hashlib.sha256(arg['code'].encode()).hexdigest(),
        'cases_sha256': native.digest(arg['cases']), 'method': arg['method'],
        'procedure_id': arg.get('procedure_id'), 'status': 'PASS', 'passed': True,
        'test_count': 2, 'passed_count': 2, 'failed_count': 0, 'not_run_count': 0,
        'timed_out': False, 'exit_code': 0, 'elapsed_seconds': 0.1,
        'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS'}


def public_ok(cell, state, code):
    return {'status': 'PASS', 'passed': True}


def run_custom(cell, arg=None):
    return native.apply_action(cell, {'tool': 'run_command', 'arguments': arg or args()}, generated_runner=custom_ok)


def test_generated_cases_bound_to_actual_history_and_do_not_count_as_public(cell):
    result = run_custom(cell)
    state = native.read(cell / 'state.json')
    event = state['procedure_events'][0]
    assert result['status'] == 'success'
    assert state['generated_test_runs'] == 1 and state['public_test_runs'] == 0
    assert event['request_sha256'] == native.digest(args())
    assert event['result_sha256'] == native.digest(result['result'])
    assert state['history'][0]['request_payload']['arguments'] == event['request']
    assert result['context']['submission_contract']['available_trace_steps'] == [1]
    assert result['context']['remaining_shared_test_executions'] == 3


def test_generated_and_public_executions_share_four_call_budget(cell):
    for _ in range(3):
        assert run_custom(cell)['status'] == 'success'
    request = {'tool': 'run_public_tests', 'arguments': {'code': args()['code']}}
    assert native.apply_action(cell, request, public_runner=public_ok)['status'] == 'success'
    assert run_custom(cell)['status'] == 'error'
    state = native.read(cell / 'state.json')
    assert state['step'] == 5 and state['generated_test_runs'] + state['public_test_runs'] == 4


def test_generated_only_is_insufficient_to_finish(cell):
    run_custom(cell)
    request = {'tool': 'finish', 'arguments': {'code': args()['code'], 'source_lesson': {
        'summary': 'Check cancellation.', 'applicability': 'Integer sums',
        'procedure': ['Test cancellation inputs.'], 'trace_steps': [1]}}}
    assert native.apply_action(cell, request)['status'] == 'error'
    native.apply_action(cell, {'tool': 'run_public_tests', 'arguments': {'code': args()['code']}}, public_runner=public_ok)
    request['arguments']['source_lesson']['trace_steps'] = [1, 3]
    assert native.apply_action(cell, request)['result']['submitted']


@pytest.mark.parametrize('mutation', ['shell', 'duplicate', 'too_many', 'foreign_id', 'wrong_method', 'missing_rationale', 'invalid_case'])
def test_invalid_requests_never_execute_and_still_consume_action(cell, mutation):
    value = args()
    if mutation == 'shell': value['command'] = 'rm -rf /'
    elif mutation == 'duplicate': value['cases'][1]['input'] = value['cases'][0]['input']
    elif mutation == 'too_many': value['cases'] = [{'input': str(i), 'output': '0'} for i in range(13)]
    elif mutation == 'foreign_id': value['procedure_id'] = 'not-injected'
    elif mutation == 'wrong_method': value['method'] = 'execute_shell'
    elif mutation == 'missing_rationale': del value['rationale']
    else: value['cases'][0]['output'] = 0
    def forbidden(*a): raise AssertionError('Invalid arguments reached executor')
    result = native.apply_action(cell, {'tool': 'run_command', 'arguments': value}, generated_runner=forbidden)
    state = native.read(cell / 'state.json')
    assert result['status'] == 'error' and state['step'] == 1
    assert state['generated_test_runs'] == 0 and state['procedure_events'] == []


def test_custom_sample_preserves_function_mode_without_using_original_examples(cell, monkeypatch):
    state = native.read(cell / 'state.json')
    state['task']['public_evaluation_sample']['input_output'] = json.dumps({'inputs': ['2\n5'], 'outputs': ['7'], 'fn_name': 'add'})
    original = json.dumps(state, sort_keys=True)
    def transport(path, shadow, code):
        sample = json.loads(shadow['task']['public_evaluation_sample']['input_output'])
        assert sample['fn_name'] == 'add'
        assert sample['inputs'] == [c['input'] for c in args()['cases']]
        assert shadow['task']['public_tests_sha256'] == native.digest(shadow['task']['public_evaluation_sample'])
        return custom_ok(path, state, args())
    monkeypatch.setattr(native, '_public_run', transport)
    result = native.generated_run(cell, state, args())
    assert result['oracle_scope'] == 'MODEL_GENERATED_EXPECTATIONS'
    assert json.dumps(state, sort_keys=True) == original


def test_common_guide_and_model_capabilities_equal_between_evaluation_arms(cell, monkeypatch):
    state = native.read(cell / 'state.json')
    state['phase'] = 'VALID'
    state['arm'] = 'OFF'
    off = native.prompt_for(state)
    state['arm'] = 'ON'
    # Retrieval is independently tested by the bank. Preserve identical nonmemory guide.
    monkeypatch.setattr(native.core, 'context', lambda state: native._context(state, recall=False))
    on = native.prompt_for(state)
    assert off.split('TASK_PACKET:\n')[0] == on.split('TASK_PACKET:\n')[0]
    assert native.PROCEDURE_CONTRACT in on


def test_worker_routes_only_to_transfer_broker(cell):
    state = native.read(cell / 'state.json')
    command = native.worker_command(cell, state)
    value = json.loads(next(s.split('=', 1)[1] for s in command if s.startswith('mcp_servers.benchmark.args=')))
    assert Path(value[0]).resolve() == Path(native.__file__).resolve()
    assert '--ignore-user-config' in command and '--ephemeral' in command
    assert 'read-only' in command and 'web_search="disabled"' in command
