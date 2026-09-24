"""Synthetic contract and transport checks: no model or private/public grader."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_explicit_format_native as native
import trimem_lcb_memory as memory


def task():
    sample = {'input_output': json.dumps({'inputs': ['2 5\n'], 'outputs': ['7\n'], 'fn_name': None})}
    return {'schema': 'trimem/lcb-public-task/1.0', 'task_id': 'synthetic-explicit',
            'question_id': 'synthetic-explicit', 'question_title': 'Synthetic integer sum',
            'prompt': 'Read two integers and print the sum.', 'starter_code': '',
            'public_test_cases': [{'input': '2 5\n', 'output': '7\n', 'testtype': 'stdin'}],
            'public_evaluation_sample': sample, 'public_tests_sha256': native.digest(sample),
            'instruction_sha256': 'a' * 64, 'family_id': 'b' * 64, 'platform': 'synthetic',
            'contest_id': '', 'contest_date': '2024-01-01', 'difficulty': 'easy', 'split': 'valid'}


def runtime():
    return {'native': {'codex_executable': 'NEVER_INVOKED', 'model': 'gpt-5.6-luna', 'reasoning_effort': 'low'},
            'execution': {'python': 'unused', 'scripts_root': '/unused', 'official_repo': '/unused'}}


@pytest.fixture
def cell(tmp_path):
    path = tmp_path / 'cell'
    native.initialize_cell(path, task(), 'OFF', runtime())
    return path


def public_ok(cell, state, code):
    return {'status': 'PASS', 'passed': True}


def test_same_contract_bytes_for_both_arms_and_fresh_empty_state(cell, monkeypatch):
    state = native.read(cell / 'state.json')
    off = native.prompt_for(state)
    state['arm'] = 'ON'
    # Isolate the prompt comparison from real retrieval, whose treatment differs.
    monkeypatch.setattr(native, '_original_context', lambda state, recall=True: {'memory': []})
    on = native.prompt_for(state)
    assert off.split('TASK_PACKET:\n')[0] == on.split('TASK_PACKET:\n')[0]
    assert native.CONTRACT in off
    assert 'ACTUAL_PUBLIC_TRACE_STEP' not in off
    assert state['candidate'] == '' and state['history'] == []
    packet = json.loads(on.split('TASK_PACKET:\n')[1])
    assert packet['context']['submission_contract']['available_trace_steps'] == []


def test_available_ids_include_graph_and_tests_but_exclude_rejection(cell):
    graph = {'tool': 'revise_subtask_dag', 'arguments': {'subtasks': [{'objective': 'Compute the integer sum', 'operation': 'integer_sum'}]}}
    first = native.apply_action(cell, graph)
    assert first['context']['submission_contract']['available_trace_steps'] == [1]
    rejected = native.apply_action(cell, {'tool': 'finish', 'arguments': {}})
    assert rejected['context']['submission_contract']['available_trace_steps'] == [1]
    third = native.apply_action(cell, {'tool': 'run_public_tests', 'arguments': {'code': 'print(7)'}}, public_runner=public_ok)
    assert third['context']['submission_contract'] == {
        'available_trace_steps': [1, 3], 'public_test_attempts': 1,
        'trace_steps_type': 'nonempty_sorted_unique_array_of_target_history_integers'}
    packet = json.loads(native.prompt_for(native.read(cell / 'state.json')).split('TASK_PACKET:\n')[1])
    assert packet['context']['submission_contract']['available_trace_steps'] == [1, 3]


def example():
    return json.loads(next(line for line in native.CONTRACT.splitlines() if line.startswith('{"request":')))


def test_documented_example_passes_actual_lesson_validator():
    lesson = example()['request']['arguments']['source_lesson']
    assert memory._lesson(lesson, [{'step_no': 2}]) == lesson


@pytest.mark.parametrize('trace', [['2'], [True], [{'step_no': 2}], [2, 2], [3, 2], [9], []])
def test_documented_disallowed_trace_examples_rejected(trace):
    lesson = example()['request']['arguments']['source_lesson']
    lesson['trace_steps'] = trace
    with pytest.raises(ValueError):
        memory._lesson(lesson, [{'step_no': 2}, {'step_no': 3}])


def test_worker_uses_explicit_adapter_and_preserves_isolation(cell):
    state = native.read(cell / 'state.json')
    state['session'] = 1
    cmd = native.worker_command(cell, state)
    args = json.loads(next(x.split('=', 1)[1] for x in cmd if x.startswith('mcp_servers.benchmark.args=')))
    assert Path(args[0]).resolve() == Path(native.__file__).resolve()
    assert args[1:] == ['mcp', '--cell', str(cell.resolve()), '--session', '1']
    assert '--ignore-user-config' in cmd and '--ephemeral' in cmd and 'read-only' in cmd
    assert native.LIMITS['task_seconds'] == 600 and native.LIMITS['public_tests'] == 4


def test_actual_mcp_uses_binary_utf8_even_under_cp949(cell):
    native.apply_action(cell, {'tool': 'run_public_tests', 'arguments': {'code': 'print(7)'}}, public_runner=public_ok)
    state = native.read(cell / 'state.json')
    state['session'] = 1
    native.write(cell / 'state.json', state)
    request = example()['request']
    request['arguments']['code'] = "print('한글')"
    request['arguments']['source_lesson']['summary'] = '합성 검증 — UTF-8 보존'
    request['arguments']['source_lesson']['trace_steps'] = [1]
    message = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'action', 'arguments': {'request': request}}}
    env = dict(os.environ, PYTHONIOENCODING='cp949:surrogateescape')
    result = subprocess.run([sys.executable, '-B', str(Path(native.__file__).resolve()), 'mcp', '--cell', str(cell), '--session', '1'],
                            input=json.dumps(message, ensure_ascii=False).encode() + b'\n', capture_output=True, env=env, timeout=30)
    assert result.returncode == 0
    response = json.loads(result.stdout)
    value = json.loads(response['result']['content'][0]['text'])
    assert value['finished'] is True and value['status'] == 'success'
    after = native.read(cell / 'state.json')
    assert after['source_lesson']['summary'] == request['arguments']['source_lesson']['summary']
    assert after['candidate'] == request['arguments']['code']


def test_prompt_hash_sealed_before_process(cell, monkeypatch):
    observed = []
    class Process:
        returncode = 0
        def communicate(self, prompt, timeout):
            receipt = native.read(cell / 'session-01' / 'prompt-receipt.json')
            assert receipt['prompt_sha256'] == hashlib.sha256(prompt).hexdigest()
            assert receipt['contract_sha256'] == hashlib.sha256(native.CONTRACT.encode()).hexdigest()
            observed.append(receipt)
            return b'{"type":"thread.started","thread_id":"synthetic-only"}\n', b''
    monkeypatch.setattr(native.core.subprocess, 'Popen', lambda *args, **kwargs: Process())
    result = native.solve_cell(cell)
    assert result['error_type'] == 'MissingSubmission' and len(observed) == 1
