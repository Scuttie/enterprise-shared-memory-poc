"""Synthetic native/HTTP evidence only; no models, repositories, or graders."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_memory as memory
import deveval_model_gateway as gateway

OWNER = 'synthetic-owner'
PROJECT = 'synthetic-project'
GOOD = 'def target(x):\n    return x + 1\n'
BAD = 'def target(x):\n    return x\n'
TEST = 'assert target(0) == 1\nassert target(2) == 3\n'


def code_sha(code):
    return hashlib.sha256(code.encode()).hexdigest()


def lesson(steps=(1, 2)):
    return {'summary': 'Check integer arithmetic with boundary assertions.',
            'applicability': 'Integer arithmetic boundary checks',
            'procedure': ['Run small integer boundary assertions after changes.'],
            'trace_steps': list(steps)}


def generated(task_id, code=GOOD, *, test_code=TEST, procedure_id=None, passed=True, changes=None):
    args = {'code': code, 'test_code': test_code, 'method': 'boundary_cases',
            'rationale': 'Exercise integer boundaries.', 'procedure_id': procedure_id}
    result = {'task_id': task_id, 'candidate_sha256': code_sha(code), 'test_sha256': code_sha(test_code),
        'method': 'boundary_cases', 'procedure_id': procedure_id, 'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS',
        'status': 'PASS' if passed else 'FAIL', 'exit_code': 0 if passed else 1,
        'timed_out': False, 'assertions_executed': 2 if passed else 1,
        'failure_kind': None if passed else 'ASSERTION', 'candidate_executed': True,
        'candidate_file_unchanged': True}
    result.update(changes or {})
    return {'tool': 'run_command', 'arguments': args}, result


def state(name, phase, selected=None, completion_path=None):
    return {'task': {'task_id': name, 'project': PROJECT, 'completion_path': completion_path or 'pkg/' + name + '.py'},
        'phase': phase, 'owner': OWNER, 'arm': 'TRAIN' if phase == 'DISCOVERY' else 'ON',
        'bank': None if phase == 'DISCOVERY' else {'synthetic': 'provisional-bank'},
        'selected_procedure_id': selected, 'candidate': '', 'finished': False,
        'source_lesson': None, 'history': [], 'session': 0, 'step': 0, 'handoff_required': False,
        'public_test_runs': 0, 'tool_seconds': 0, 'memory_injections': [],
        'started_epoch': time.time(), 'limits': {'sessions': 4, 'task_seconds': 600,
                                                'tool_actions': 24, 'prompt_bytes': 196608},
        'runtime': {'native': {'model': 'synthetic-glm', 'reasoning_effort': 'low'}}}


def native_item(request, response, index):
    return {'type': 'item.completed', 'item': {'id': 'call-%d' % index, 'type': 'mcp_tool_call',
        'server': 'benchmark', 'tool': 'action', 'arguments': {'request': request},
        'result': {'content': [{'type': 'text', 'text': json.dumps(response)}]}}}


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(memory.canonical(value))


def build_native(tmp_path, name='source', phase='DISCOVERY', *, selected=None, completion_path=None,
                 red_changes=None, green_changes=None, green_test=TEST, red_code=BAD,
                 final_code=GOOD, source_lesson=None, accepted=True, include_red=True):
    cell = tmp_path / name
    folder = cell / 'session-01'; folder.mkdir(parents=True)
    value = state(name, phase, selected, completion_path)
    initial = deepcopy(value); initial['session'] = 1
    write(folder / 'initial-state.json', initial)
    (folder / 'prompt.txt').write_bytes(b'SYNTHETIC TASK_PACKET only.\n')
    write(folder / 'prompt-receipt.json', {
        'prompt_sha256': memory.reference(folder / 'prompt.txt')['sha256'],
        'state_before_call_sha256': memory.reference(folder / 'initial-state.json')['sha256']})
    observations = []
    if include_red and phase == 'DISCOVERY':
        observations.append(generated(name, red_code, passed=False, changes=red_changes))
    observations.append(generated(name, procedure_id=selected, test_code=green_test, changes=green_changes))
    events = [{'type': 'thread.started', 'thread_id': 'synthetic-thread-' + name}]
    for step, (request, result) in enumerate(observations, 1):
        value['history'].append({'step_no': step, 'tool': 'run_command', 'status': 'success',
                                 'request_payload': request, 'result_payload': result})
        write(cell / 'generated-tests' / ('step-%03d' % step) / 'receipt.json', result)
        events.append(native_item(request, {'step_no': step, 'status': 'success', 'result': result}, step))
    value.update(candidate=final_code, finished=True, session=1, step=len(observations) + 1,
                 source_lesson=source_lesson or lesson(range(1, len(observations) + 1)))
    finish = {'tool': 'finish', 'arguments': {'code': final_code, 'source_lesson': value['source_lesson']}}
    events.append(native_item(finish, {'step_no': value['step'], 'status': 'success',
        'result': {'submitted': True, 'candidate_sha256': code_sha(final_code)}}, value['step']))
    write(cell / 'state.json', value)
    (folder / 'events.jsonl').write_bytes(b''.join(memory.canonical(row) for row in events))
    (folder / 'stderr.log').write_bytes(b'')
    receipt = {'session': 1, 'thread_ids': ['synthetic-thread-' + name],
        'events_sha256': memory.reference(folder / 'events.jsonl')['sha256'],
        'stderr_sha256': memory.reference(folder / 'stderr.log')['sha256'],
        'benchmark_action_calls': len(observations) + 1}
    write(folder / 'receipt.json', receipt)
    write(cell / 'solve-receipt.json', {'task_id': name, 'arm': value['arm'],
        'state_sha256': memory.reference(cell / 'state.json')['sha256'], 'candidate_sha256': code_sha(final_code),
        'status': 'SUBMITTED' if accepted else 'GENERATION_ERROR',
        'error_type': None if accepted else 'NativeProcessError', 'sessions': [receipt]})
    return cell


def capture(cell, phase='DISCOVERY', **kwargs):
    return memory.capture(cell, phase=phase, owner=kwargs.get('owner', OWNER),
                           project=kwargs.get('project', PROJECT), task_id=Path(cell).name)


def repin_session(cell):
    folder = cell / 'session-01'
    receipt = memory.read(folder / 'receipt.json')
    receipt['events_sha256'] = memory.reference(folder / 'events.jsonl')['sha256']
    write(folder / 'receipt.json', receipt)
    solve = memory.read(cell / 'solve-receipt.json')
    solve['state_sha256'] = memory.reference(cell / 'state.json')['sha256']
    solve['sessions'] = [receipt]
    write(cell / 'solve-receipt.json', solve)


@pytest.fixture
def pair(tmp_path):
    source_cell = build_native(tmp_path)
    source = capture(source_cell)
    provisional = memory.derive([source], OWNER)
    candidate = provisional['candidates'][0]
    verify_cell = build_native(tmp_path, 'verification', 'VERIFICATION', selected=candidate['procedure_id'])
    verification = capture(verify_cell, 'VERIFICATION')
    return source_cell, verify_cell, source, verification


def test_independent_file_promotes_observed_workflow_not_oracle_correctness(pair):
    data = memory.derive(pair[2:], OWNER)
    assert len(data['episodes']) == 2 and len(data['skills']) == 1
    skill = data['skills'][0]
    assert skill['status'] == 'VERIFIED_PERSONAL' and skill['claim'] == memory.CLAIM
    assert skill['oracle_scope'] == 'MODEL_GENERATED_EXPECTATIONS'
    assert skill['prose_status'] == 'MODEL_AUTHORED_NOT_SEMANTICALLY_VERIFIED'
    assert skill['verification_support'][0]['task_id'] == 'verification'


@pytest.mark.parametrize('kwargs', [
    {'green_test': TEST + 'assert target(3) == 4\n'}, {'red_code': GOOD},
    {'final_code': GOOD + '# untested final edit\n'}, {'source_lesson': lesson([2])},
    {'include_red': False}, {'accepted': False},
])
def test_discovery_without_exact_accepted_repair_keeps_l1_but_no_skill(tmp_path, kwargs):
    value = capture(build_native(tmp_path, **kwargs))
    data = memory.derive([value], OWNER)
    assert len(data['episodes']) == 1 and data['candidates'] == [] and data['skills'] == []


@pytest.mark.parametrize('changes', [
    {'exit_code': 0}, {'assertions_executed': 0}, {'timed_out': True},
    {'candidate_executed': False}, {'candidate_file_unchanged': False},
])
def test_false_assertion_red_rejected_with_consistent_native_and_execution_hashes(tmp_path, changes):
    with pytest.raises(ValueError):
        capture(build_native(tmp_path, red_changes=changes))


def test_green_without_enough_executed_assertions_rejected(tmp_path):
    with pytest.raises(ValueError):
        capture(build_native(tmp_path, green_changes={'assertions_executed': 1}))


def test_same_file_cannot_be_independent_verification(tmp_path):
    source = capture(build_native(tmp_path))
    candidate = memory.derive([source], OWNER)['candidates'][0]
    other = capture(build_native(tmp_path, 'other', 'VERIFICATION',
        selected=candidate['procedure_id'], completion_path=source['completion_path']), 'VERIFICATION')
    with pytest.raises(ValueError, match='SELF_VERIFICATION'):
        memory.derive([source, other], OWNER)


def test_verification_without_preassigned_id_adds_no_support(tmp_path):
    source = capture(build_native(tmp_path))
    other = capture(build_native(tmp_path, 'other', 'VERIFICATION'), 'VERIFICATION')
    assert memory.derive([source, other], OWNER)['skills'] == []


def test_mutated_final_preassignment_cannot_override_initial_state(pair):
    _, cell, _, _ = pair
    value = memory.read(cell / 'state.json')
    value['selected_procedure_id'] = 'newly-invented-assignment'
    write(cell / 'state.json', value); repin_session(cell)
    with pytest.raises(ValueError):
        capture(cell, 'VERIFICATION')


def test_call_history_bijection_rejects_extra_successful_native_call(pair):
    cell = pair[0]; path = cell / 'session-01/events.jsonl'
    events = [json.loads(raw) for raw in path.read_bytes().splitlines()]
    events.append(native_item({'tool': 'read_file', 'arguments': {'path': 'a.py'}},
                             {'step_no': 19, 'status': 'success', 'result': {'text': 'synthetic'}}, 19))
    path.write_bytes(b''.join(memory.canonical(row) for row in events)); repin_session(cell)
    with pytest.raises(ValueError, match='TRACE_BIJECTION_CHANGED'):
        capture(cell)


def test_forged_thread_and_execution_receipt_are_rejected(pair):
    cell = pair[0]; path = cell / 'session-01/receipt.json'
    receipt = memory.read(path); receipt['thread_ids'] = ['forged-thread']
    write(path, receipt); repin_session(cell)
    with pytest.raises(ValueError, match='THREAD_NOT_CORROBORATED'):
        capture(cell)
    receipt['thread_ids'] = ['synthetic-thread-source']; write(path, receipt); repin_session(cell)
    execution = cell / 'generated-tests/step-001/receipt.json'
    value = memory.read(execution); value['assertions_executed'] += 1; write(execution, value)
    with pytest.raises(ValueError, match='EXECUTION_RECEIPT_CHANGED'):
        capture(cell)


def test_owner_phase_project_and_retrieval_isolation(pair, tmp_path):
    with pytest.raises(ValueError, match='CAPTURE_SCOPE_CHANGED'):
        capture(pair[0], owner='other')
    with pytest.raises(ValueError, match='EVALUATION_CAPTURE_FORBIDDEN'):
        capture(pair[0], phase='TEST')
    plan = tmp_path / 'plan.json'; write(plan, {'synthetic': True})
    ref = memory.freeze(tmp_path / 'bank.json', owner=OWNER, stage='FINAL', captures=list(pair[2:]), plan_reference=memory.reference(plan))
    with pytest.raises(ValueError, match='BANK_SCOPE_CHANGED'):
        memory.load(ref, owner='other')
    bank = memory.load(ref, owner=OWNER)
    target = {'project': PROJECT, 'task_id': 'target', 'completion_path': 'pkg/target.py'}
    assert memory.recall(bank, target, 'integer arithmetic boundary checks', layer='L3')['layer'] == 'L3'
    assert memory.recall(bank, target, 'integer arithmetic boundary checks', layer='L1')['layer'] == 'L1'
    assert memory.recall(bank, {**target, 'project': 'other-project'}, 'integer arithmetic', layer='L3') is None
    assert memory.recall(bank, {**target, 'completion_path': pair[2]['completion_path']}, 'integer arithmetic', layer='L3') is None


@pytest.mark.parametrize('mutation', ['capture', 'readiness', 'counts'])
def test_rehashed_bank_must_still_rederive_from_actual_source(pair, tmp_path, mutation):
    plan = tmp_path / 'plan.json'; write(plan, {'synthetic': True})
    ref = memory.freeze(tmp_path / 'bank.json', owner=OWNER, stage='FINAL', captures=list(pair[2:]), plan_reference=memory.reference(plan))
    payload = memory.read(ref['path'])
    if mutation == 'capture':
        payload['captures'][0]['lesson']['summary'] = 'Fabricated after capture.'
        payload.update(memory.derive(payload['captures'], OWNER))
    elif mutation == 'readiness':
        payload['l3_status'] = 'NOT_READY'
    else:
        payload['layer_counts']['L3'] = 99
    write(ref['path'], payload)
    with pytest.raises(ValueError):
        memory.load(memory.reference(ref['path']), owner=OWNER)


def http_source(tmp_path, monkeypatch):
    """Run the actual gateway, mocking only HTTP and candidate execution."""
    cell = tmp_path / 'http-source'; cell.mkdir(); (cell / 'worker').mkdir()
    value = state(cell.name, 'DISCOVERY')
    value['runtime']['gateway'] = {'provider': 'vllm', 'model': 'synthetic-glm',
                                   'base_url': 'http://synthetic.invalid/v1'}
    write(cell / 'state.json', value)
    requests = [generated(cell.name, BAD, passed=False)[0], generated(cell.name)[0],
                {'tool': 'finish', 'arguments': {'code': GOOD, 'source_lesson': lesson()}}]
    responses = []
    class Response:
        status = 200
        def __init__(self, value): self.raw = gateway.canonical(value)
        def read(self, limit): return self.raw[:limit]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def post(request, timeout):
        index = len(responses)
        result = {'id': 'synthetic-http-%d' % index, 'model': 'synthetic-glm',
                  'choices': [{'message': {'content': json.dumps(requests[index])}, 'finish_reason': 'stop'}],
                  'usage': {'total_tokens': 3}}
        responses.append(result)
        return Response(result)
    monkeypatch.setattr(gateway, '_http_post', post)
    def apply(path, request, *, expected_session):
        current = memory.read(path / 'state.json'); current['step'] += 1
        assert current['session'] == expected_session
        if request['tool'] == 'finish':
            current.update(candidate=request['arguments']['code'], source_lesson=request['arguments']['source_lesson'], finished=True)
            result = {'submitted': True, 'candidate_sha256': code_sha(current['candidate'])}
        else:
            current['candidate'] = request['arguments']['code']
            _, result = generated(path.name, current['candidate'], passed=current['candidate'] == GOOD)
            current['history'].append({'step_no': current['step'], 'tool': 'run_command', 'status': 'success',
                                      'request_payload': request, 'result_payload': result})
            write(path / 'generated-tests' / ('step-%03d' % current['step']) / 'receipt.json', result)
        write(path / 'state.json', current)
        return {'step_no': current['step'], 'status': 'success', 'result': result,
                'finished': current['finished'], 'handoff_required': False}
    solved = gateway.solve_vllm(cell, prompt_for=lambda state: 'Synthetic repository packet.', apply_action=apply)
    assert solved['status'] == 'SUBMITTED' and len(responses) == 3
    return cell


def test_actual_gateway_http_provenance_without_fabricated_native_threads(tmp_path, monkeypatch):
    value = capture(http_source(tmp_path, monkeypatch))
    assert value['threads'] == [] and value['accepted'] is True
    assert len(memory.derive([value], OWNER)['candidates']) == 1
    assert any(Path(ref['path']).name == 'response.json' for ref in value['references'])


@pytest.mark.parametrize('mutation', ['request', 'mixed_native'])
def test_http_action_must_come_from_bound_http_content(tmp_path, monkeypatch, mutation):
    cell = http_source(tmp_path, monkeypatch)
    path = cell / 'session-01/events.jsonl'
    events = [json.loads(raw) for raw in path.read_bytes().splitlines()]
    if mutation == 'request':
        events[0]['request']['arguments']['code'] = 'def target(x): return 999\n'
        events[0]['request_sha256'] = memory.digest(events[0]['request'])
    else:
        events[0] = native_item(events[0]['request'], events[0]['response'], 1)
    path.write_bytes(b''.join(memory.canonical(row) for row in events)); repin_session(cell)
    with pytest.raises(ValueError):
        capture(cell)
