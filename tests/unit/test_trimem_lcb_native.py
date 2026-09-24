"""Synthetic native-controller boundaries; no model, public evaluator, or network."""
import hashlib
import json
from types import SimpleNamespace

import pytest

import trimem_lcb_native as native
from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph


def task():
    sample = {'input_output': json.dumps({'inputs': ['2 5\n'], 'outputs': ['7\n'], 'fn_name': None})}
    return {'schema': 'trimem/lcb-public-task/1.0', 'task_id': 'synthetic-add',
        'question_id': 'synthetic-add', 'question_title': 'Add two values',
        'prompt': 'Read two integers and print their sum.', 'starter_code': '',
        'public_test_cases': [{'input': '2 5\n', 'output': '7\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': sample, 'public_tests_sha256': native.digest(sample),
        'instruction_sha256': 'a' * 64, 'family_id': 'b' * 64,
        'platform': 'synthetic', 'contest_id': '', 'contest_date': '2024-01-01',
        'difficulty': 'easy', 'split': 'train'}


def runtime():
    return {'execution': {'python': 'synthetic-python', 'scripts_root': '/synthetic/scripts',
                           'official_repo': '/synthetic/official', 'prefix': []},
            'native': {'codex_executable': 'never-invoked', 'model': 'synthetic-model',
                       'reasoning_effort': 'high'}}


@pytest.fixture
def cell(tmp_path):
    path = tmp_path / 'cell'
    native.initialize_cell(path, task(), 'OFF', runtime())
    return path


def request(tool, **arguments):
    return {'tool': tool, 'arguments': arguments}


def feedback(row, code):
    tests = native.digest(row['public_evaluation_sample'])
    return {'schema': 'trimem/lcb-public-test-result/1.0', 'task_id': row['task_id'],
        'candidate_sha256': hashlib.sha256(code.encode()).hexdigest(), 'public_tests_sha256': tests,
        'command': ['lcb_public_tests', row['task_id'], tests], 'status': 'PASS',
        'test_count': 1, 'passed_count': 1, 'failed_count': 0, 'not_run_count': 0,
        'exit_code': 0, 'timed_out': False, 'failure_kind': None, 'assertion_failures': 0,
        'passed': True}


def mock_public(cell, state, code):
    return feedback(state['task'], code)


def lesson(steps):
    return {'summary': 'Checked signed integer addition against the public examples.',
        'applicability': 'Tasks asking for the sum of two signed integers.',
        'procedure': ['Parse integer tokens, add both values, and print the result.'],
        'trace_steps': steps}


def mutate_state(cell, change):
    state = native.read(cell / 'state.json')
    change(state)
    native.write(cell / 'state.json', state)
    return state


@pytest.mark.parametrize('arm,bank', [('OFF', {'path': 'bank', 'sha256': 'a' * 64}),
                                   ('TRAIN', {'path': 'bank', 'sha256': 'a' * 64}), ('ON', None)])
def test_memory_arm_contract_blocks_off_bank_and_requires_on_bank(tmp_path, arm, bank):
    with pytest.raises(ValueError):
        native.initialize_cell(tmp_path / 'invalid', task(), arm, runtime(), bank=bank)
    assert not (tmp_path / 'invalid').exists()


def test_off_context_never_opens_a_frozen_bank(cell, monkeypatch):
    import trimem_lcb_memory as memory
    monkeypatch.setattr(memory, 'load_frozen_bank', lambda *args: pytest.fail('OFF opened a bank'))
    state = native.read(cell / 'state.json')
    assert native.context(state)['memory'] == []
    prompt = native.prompt_for(state)
    assert 'synthetic-add' in prompt and 'hidden tests' in prompt
    assert state['memory_checkpoint'] is None and state['memory_decisions'] == []


def test_only_active_subgoal_memory_is_exposed_but_ledger_is_retained(cell):
    state = native.read(cell / 'state.json')
    state['memory_injections'] = [
        {'active_node_id': 'previous', 'exact_text': 'old subgoal'},
        {'active_node_id': 'solution', 'exact_text': 'current subgoal'},
    ]
    assert native.context(state, recall=False)['memory'] == [state['memory_injections'][1]]
    assert len(state['memory_injections']) == 2


def test_source_guard_runs_before_a_model_process_starts(cell, monkeypatch):
    monkeypatch.setattr(native.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Model started after guard rejection'))
    def reject():
        raise ValueError('Frozen implementation changed')
    with pytest.raises(ValueError, match='Frozen implementation changed'):
        native.solve_cell(cell, before_model_call=reject)


def test_context_and_source_verification_time_counts_against_task_deadline(cell, monkeypatch):
    started = native.read(cell / 'state.json')['started_epoch']
    now = [started + 1]
    monkeypatch.setattr(native.time, 'time', lambda: now[0])
    monkeypatch.setattr(native.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Model started after deadline'))
    def slow_guard():
        now[0] = started + native.LIMITS['task_seconds'] + 1
    receipt = native.solve_cell(cell, before_model_call=slow_guard)
    assert receipt['status'] == 'GENERATION_ERROR' and receipt['error_type'] == 'TaskTimeout'


def test_malformed_mcp_envelope_consumes_action_budget(cell):
    result = native.mcp_response({'id': 1, 'method': 'tools/call',
        'params': {'name': 'action', 'arguments': {'request': request('finish'), 'unexpected': True}}},
        lambda value: native.apply_action(cell, value))
    assert result['result']['isError'] is True
    assert native.read(cell / 'state.json')['step'] == 1


def test_public_trace_uses_core_hash_without_lf_and_public_sample_hash_with_lf(cell):
    action = request('run_public_tests', code='print(7)')
    answer = native.apply_action(cell, action, public_runner=mock_public)
    assert answer['status'] == 'success'
    state = native.read(cell / 'state.json')
    event = state['history'][0]
    assert event['request'] == {'sha256': sha256_bytes(canonical_bytes(action)), 'bytes': len(canonical_bytes(action))}
    assert event['request']['sha256'] != native.digest(action)
    assert event['result_payload']['public_tests_sha256'] == native.digest(task()['public_evaluation_sample'])
    assert event['result']['sha256'] == sha256_bytes(canonical_bytes(event['result_payload']))


def test_plan_completion_persists_handoff_and_blocks_old_session(cell):
    plan = request('revise_subtask_dag', subtasks=[
        {'objective': 'Parse signed input integers', 'operation': 'parse_integer_tokens'},
        {'objective': 'Add parsed values and format their sum', 'operation': 'compute_sum'}])
    assert native.apply_action(cell, plan)['status'] == 'success'
    completed = native.apply_action(cell, request('complete_subtask', evidence='Parsed signed tokens preserve sign.'))
    assert completed['status'] == 'success' and completed['handoff_required'] is True
    state = native.read(cell / 'state.json')
    graph = ShortTermWorkingGraph.from_snapshot(state['graph'])
    assert graph.active_node_id == 'subgoal-2'
    assert state['handoff_required'] is True
    with pytest.raises(ValueError, match='complete'):
        native.apply_action(cell, request('run_public_tests', code='print(7)'), public_runner=mock_public)


def test_plan_cannot_be_replaced_after_public_history(cell):
    native.apply_action(cell, request('run_public_tests', code='print(7)'), public_runner=mock_public)
    before = native.read(cell / 'state.json')['graph']
    answer = native.apply_action(cell, request('revise_subtask_dag', subtasks=[
        {'objective': 'Replace the observed algorithm', 'operation': 'replace_sum'}]))
    assert answer['status'] == 'error'
    assert native.read(cell / 'state.json')['graph'] == before


def test_public_test_budget_does_not_execute_an_extra_candidate(cell):
    mutate_state(cell, lambda state: state['limits'].update(public_tests=1))
    calls = []
    def runner(cell, state, code):
        calls.append(code)
        return mock_public(cell, state, code)
    native.apply_action(cell, request('run_public_tests', code='print(7)'), public_runner=runner)
    answer = native.apply_action(cell, request('run_public_tests', code='print(8)'), public_runner=runner)
    assert answer['status'] == 'error' and calls == ['print(7)']
    state = native.read(cell / 'state.json')
    assert state['public_test_runs'] == 1 and state['step'] == 2


def test_expired_session_does_not_mutate_or_execute(cell):
    mutate_state(cell, lambda state: state.update(session=2))
    before = (cell / 'state.json').read_bytes()
    with pytest.raises(ValueError, match='Expired'):
        native.apply_action(cell, request('run_public_tests', code='print(7)'), expected_session=1,
                            public_runner=lambda *args: pytest.fail('Expired session executed'))
    assert (cell / 'state.json').read_bytes() == before


@pytest.mark.parametrize('exhaustion', ['actions', 'time'])
def test_exhausted_task_budget_is_checked_before_execution(cell, exhaustion):
    mutate_state(cell, lambda state: state.update(
        step=state['limits']['tool_actions']) if exhaustion == 'actions' else state.update(started_epoch=0))
    with pytest.raises(ValueError, match='budget'):
        native.apply_action(cell, request('run_public_tests', code='print(7)'),
                            public_runner=lambda *args: pytest.fail('Exhausted task executed'))


@pytest.mark.parametrize('field,value', [('task_id', 'foreign'), ('candidate_sha256', '0' * 64),
                                       ('public_tests_sha256', '0' * 64)])
def test_public_transport_rejects_identity_drift(cell, monkeypatch, field, value):
    state = mutate_state(cell, lambda state: state.update(step=1))
    result = feedback(state['task'], 'print(7)')
    result[field] = value
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(stdout=json.dumps(result).encode(), stderr=b'', returncode=0))
    with pytest.raises(RuntimeError):
        native.public_run(cell, state, 'print(7)')


def test_public_transport_nonzero_exit_cannot_claim_pass(cell, monkeypatch):
    state = mutate_state(cell, lambda state: state.update(step=1))
    result = feedback(state['task'], 'print(7)')
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(stdout=json.dumps(result).encode(), stderr=b'', returncode=2))
    with pytest.raises(RuntimeError):
        native.public_run(cell, state, 'print(7)')


def test_public_transport_projects_only_observation_fields(cell, monkeypatch):
    state = mutate_state(cell, lambda state: state.update(step=1))
    result = {**feedback(state['task'], 'print(7)'), 'private_reference': '/must/not/enter/trace',
              'security_sandbox': False, 'model_calls': 0}
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(stdout=json.dumps(result).encode(), stderr=b'', returncode=0))
    visible = native.public_run(cell, state, 'print(7)')
    assert 'private_reference' not in visible and 'security_sandbox' not in visible
    assert visible['status'] == 'PASS'


def test_finish_without_public_attempt_is_blocked(cell):
    answer = native.apply_action(cell, request('finish', code='print(7)', source_lesson=lesson([1])))
    assert answer['status'] == 'error' and answer['finished'] is False


def test_finish_cannot_forge_a_nonexistent_trace_anchor(cell):
    native.apply_action(cell, request('run_public_tests', code='print(7)'), public_runner=mock_public)
    answer = native.apply_action(cell, request('finish', code='print(7)', source_lesson=lesson([999])))
    assert answer['status'] == 'error' and answer['finished'] is False
    assert native.read(cell / 'state.json')['source_lesson'] is None
    valid = native.apply_action(cell, request('finish', code='print(7)', source_lesson=lesson([1])))
    assert valid['status'] == 'success' and valid['finished'] is True


def test_unknown_bounded_operation_is_rejected_and_consumes_action_budget(cell):
    before = native.read(cell / 'state.json')
    with pytest.raises(ValueError, match='Unknown'):
        native.apply_action(cell, request('shell', command='never execute'))
    after = native.read(cell / 'state.json')
    assert after['step'] == before['step'] + 1
    assert after['history'] == before['history'] and after['candidate'] == before['candidate']


def test_mcp_exposes_no_unlisted_tool_or_extra_arguments():
    handler = lambda value: pytest.fail('Unexpected tool reached controller')
    answer = native.mcp_response({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'shell', 'arguments': {'request': {}}}}, handler)
    assert answer['error']['code'] == -32601
    def reject_malformed(value):
        assert value == {}
        raise ValueError('Malformed envelope')
    answer = native.mcp_response({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': 'action', 'arguments': {'request': {}, 'extra': 'not allowed'}}}, reject_malformed)
    assert answer['result']['isError'] is True


def test_native_event_guard_rejects_unexpected_execution_even_after_submission(cell, monkeypatch):
    class Process:
        returncode = 0
        def communicate(self, prompt, timeout):
            mutate_state(cell, lambda state: state.update(finished=True, candidate='print(7)'))
            events = [{'type': 'thread.started', 'thread_id': 'synthetic-thread'},
                      {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'forbidden'}}]
            return b'\n'.join(json.dumps(event).encode() for event in events), b''
    monkeypatch.setattr(native.subprocess, 'Popen', lambda *args, **kwargs: Process())
    result = native.solve_cell(cell)
    assert result['status'] == 'GENERATION_ERROR' and result['error_type'] == 'UnexpectedNativeTool'
    assert result['sessions'][0]['unexpected_tools'] == ['command_execution']
