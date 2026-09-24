"""Synthetic repository broker integration, without model or official grader."""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_native as native

_spec = importlib.util.spec_from_file_location('synthetic_context_fixtures', Path(__file__).with_name('test_deveval_repository_context.py'))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


@pytest.fixture
def cell(tmp_path):
    refs = fixtures.fixture(tmp_path)
    snapshot = native.repository.materialize_repository(refs[0], refs[1], tmp_path / 'snapshot',
        project=fixtures.PROJECT, plan_reference=refs[2])
    location = tmp_path / 'cell'
    native.initialize(location, snapshot_reference=snapshot, task_id='pkg.main.target', phase='VALID', condition='OFF',
        runtime={'native': {'model': 'synthetic', 'reasoning_effort': 'low'}}, owner='synthetic-owner')
    return location


def generated_args():
    return {'code': 'return value + 1', 'test_code': 'assert 1 == 1\nassert 2 == 2\n',
            'method': 'boundary_cases', 'rationale': 'Synthetic bounded test.'}


def synthetic_runner(cell, state, args):
    return {'schema': 'deveval-generated-test/1', 'task_id': state['task']['task_id'],
        'candidate_sha256': hashlib.sha256(args['code'].encode()).hexdigest(),
        'test_sha256': hashlib.sha256(args['test_code'].encode()).hexdigest(), 'method': args['method'],
        'procedure_id': args.get('procedure_id'), 'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS',
        'status': 'PASS', 'passed': True, 'failure_kind': None, 'exit_code': 0,
        'assertions_executed': 2, 'candidate_executed': True, 'candidate_lines_executed': 1,
        'timed_out': False, 'elapsed_seconds': 0.01}


def test_read_tools_use_sanitized_files_and_project_into_l0(cell):
    listed = native.apply_action(cell, {'tool': 'list_files', 'arguments': {}})
    assert listed['status'] == 'success' and 'checks.py' not in listed['result']['files']
    read = native.apply_action(cell, {'tool': 'read_file', 'arguments': {'path': 'pkg/main.py'}})
    assert read['status'] == 'success' and 'PRIVATE GOLD' not in read['result']['text']
    search = native.apply_action(cell, {'tool': 'search', 'arguments': {'query': 'return helper'}})
    assert search['status'] == 'success' and search['result']['matches']
    assert search['context']['available_trace_steps'] == [1, 2, 3]
    hidden = native.apply_action(cell, {'tool': 'read_file', 'arguments': {'path': 'checks.py'}})
    assert hidden['status'] == 'error'
    assert native.core.read(cell / 'state.json')['step'] == 4


def test_both_arms_share_guide_read_authority_and_l2_uses_visible_relations(cell):
    state = native.core.read(cell / 'state.json')
    off = native.prompt_for(state)
    state['condition'], state['arm'] = 'FULL', 'ON'
    state['memory_decisions'] = []
    on = native.prompt_for(state)
    assert off.split('TASK_PACKET:\n')[0] == on.split('TASK_PACKET:\n')[0]
    assert len(state['memory_injections']) == 1 and state['memory_injections'][0]['layer'] == 'L2'
    assert state['memory_injections'][0]['snapshot_id'] == state['task']['snapshot_id']
    assert state['limits']['public_tests'] == 4 and state['limits']['tool_actions'] == 24


def test_four_generated_executions_share_action_budget_and_finish_uses_original_lesson_validation(cell):
    for step in range(1, 5):
        result = native.apply_action(cell, {'tool': 'run_command', 'arguments': generated_args()}, runner=synthetic_runner)
        assert result['status'] == 'success' and result['context']['remaining_generated_tests'] == 4 - step
    fifth = native.apply_action(cell, {'tool': 'run_command', 'arguments': generated_args()}, runner=lambda *args: pytest.fail('fifth execution'))
    assert fifth['status'] == 'error'
    lesson = {'summary': 'Synthetic observed attempt.', 'applicability': 'Synthetic arithmetic.',
              'procedure': ['Exercise target on bounded checks.'], 'trace_steps': ['1']}
    finish = {'tool': 'finish', 'arguments': {'code': 'return value + 1', 'source_lesson': lesson}}
    assert native.apply_action(cell, finish)['status'] == 'error'
    lesson['trace_steps'] = [1, 4]
    assert native.apply_action(cell, finish)['result']['submitted'] is True
    with pytest.raises(ValueError, match='SESSION_ALREADY_FINISHED'):
        native.apply_action(cell, finish)


@pytest.mark.parametrize('mutation', ['shell', 'foreign_procedure', 'one_assertion', 'empty_code'])
def test_invalid_requests_cannot_reach_executor(cell, mutation):
    args = generated_args()
    if mutation == 'shell': args['command'] = 'arbitrary'
    elif mutation == 'foreign_procedure': args['procedure_id'] = 'not-delivered'
    elif mutation == 'one_assertion': args['test_code'] = 'assert True'
    else: args['code'] = ''
    result = native.apply_action(cell, {'tool': 'run_command', 'arguments': args}, runner=lambda *a: pytest.fail('invalid execution'))
    assert result['status'] == 'error'
    state = native.core.read(cell / 'state.json')
    assert state['step'] == 1 and state['public_test_runs'] == 0


def test_handoff_and_expired_worker_cannot_continue(cell):
    result = native.apply_action(cell, {'tool': 'revise_subtask_dag', 'arguments': {'subtasks': [
        {'objective': 'Understand integer helper dependencies', 'operation': 'read_repository'},
        {'objective': 'Implement integer function behavior', 'operation': 'implement_function'}]}})
    assert result['status'] == 'success'
    handoff = native.apply_action(cell, {'tool': 'complete_subtask', 'arguments': {'evidence': 'Synthetic dependency inspection completed.'}})
    assert handoff['handoff_required'] is True
    with pytest.raises(ValueError, match='SESSION_ALREADY_FINISHED'):
        native.apply_action(cell, {'tool': 'list_files', 'arguments': {}})
