"""Synthetic private L3 proof: no models, benchmark payloads, or graders."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_personal_memory as memory
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec

GOOD = 'def increment(x):\n    return x + 1\nprint(increment(int(input())))\n'
BAD = 'def increment(x):\n    return x\nprint(increment(int(input())))\n'
CASES = [{'input': '0\n', 'output': '1\n'}, {'input': '2\n', 'output': '3\n'}]


def task(identity, split, family=None):
    sample = {'input_output': json.dumps({'inputs': ['1\n'], 'outputs': ['2\n'], 'fn_name': None})}
    value = {'schema': memory.base.PUBLIC_TASK_SCHEMA, 'task_id': identity, 'question_id': identity,
        'split': split, 'family_id': family or 'family-' + identity,
        'question_title': 'Synthetic increment ' + identity,
        'prompt': 'Increment an integer. Synthetic task ' + identity, 'starter_code': '',
        'public_test_cases': [{'input': '1\n', 'output': '2\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': sample}
    value['instruction_sha256'] = memory.base._hash({k: value[k] for k in ('question_title', 'prompt', 'starter_code')})
    value['public_tests_sha256'] = memory.base.public_tests_sha256(value)
    return value


def graph(row):
    value = ShortTermWorkingGraph(row['task_id'], memory.base.public_task_instruction(row), memory.base.REPOSITORY)
    value.add_subtask(SubtaskSpec('Increment integer arithmetic', 'integer arithmetic', node_id='increment'))
    value.activate('increment')
    return value


def trace_ref(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return {'sha256': memory.sha(raw), 'bytes': len(raw)}


def history_event(row, step, request, result):
    return {'task_id': row['task_id'], 'arm': 'TRAIN', 'active_node_id': 'increment',
        'step_no': step, 'tool': request['tool'], 'status': 'success',
        'request_payload': request, 'result_payload': result,
        'request': trace_ref(request), 'result': trace_ref(result)}


def generated(row, step, *, code=GOOD, passed=True, cases=None, procedure_id=None):
    request = {'code': code, 'cases': deepcopy(CASES if cases is None else cases),
               'method': 'boundary_cases', 'rationale': 'Check small integer arithmetic boundaries.'}
    if procedure_id is not None:
        request['procedure_id'] = procedure_id
    result = {'schema': memory.RESULT_SCHEMA, 'task_id': row['task_id'],
        'candidate_sha256': memory.sha(code.encode()), 'cases_sha256': memory.digest(request['cases']),
        'method': request['method'], 'procedure_id': procedure_id,
        'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS', 'status': 'PASS' if passed else 'FAIL',
        'test_count': len(request['cases']), 'passed_count': len(request['cases']) if passed else 0,
        'failed_count': 0 if passed else len(request['cases']), 'not_run_count': 0,
        'exit_code': 0 if passed else 1, 'timed_out': False,
        'failure_kind': None if passed else 'WRONG_ANSWER', 'elapsed_seconds': 0.01}
    event = {'step_no': step, 'method': request['method'], 'procedure_id': procedure_id,
             'request': request, 'result': result,
             'request_sha256': memory.digest(request), 'result_sha256': memory.digest(result)}
    return event, history_event(row, step, {'tool': 'run_command', 'arguments': request}, result)


def public(row, step, *, code=GOOD, passed=True):
    result = {'schema': memory.base.PUBLIC_RESULT_SCHEMA, 'task_id': row['task_id'],
        'candidate_sha256': memory.sha(code.encode()), 'public_tests_sha256': row['public_tests_sha256'],
        'command': ['lcb_public_tests', row['task_id'], row['public_tests_sha256']],
        'status': 'PASS' if passed else 'FAIL', 'test_count': 1,
        'passed_count': int(passed), 'failed_count': int(not passed), 'not_run_count': 0,
        'exit_code': 0 if passed else 1, 'timed_out': False,
        'failure_kind': None if passed else 'WRONG_ANSWER'}
    return history_event(row, step, {'tool': 'run_public_tests', 'arguments': {'code': code}}, result)


def capture(row, phase, *, procedure_id=None, finished=True):
    events, history = [], []
    if phase == 'DISCOVERY':
        red, trace = generated(row, 1, code=BAD, passed=False)
        events.append(red); history.append(trace)
    green, trace = generated(row, len(history) + 1, procedure_id=procedure_id)
    events.append(green); history.append(trace)
    history.append(public(row, len(history) + 1))
    lesson = {'summary': 'Check integer arithmetic using generated boundary cases and public examples.',
        'applicability': 'Increment integer arithmetic',
        'procedure': ['Check small integer arithmetic boundaries, then the original public examples.'],
        'trace_steps': [event['step_no'] for event in history]}
    return {'schema': memory.SCHEMA, 'phase': phase, 'task_public': row, 'graph': graph(row).snapshot(),
        'history': history, 'procedure_events': events, 'final_code': GOOD,
        'source_lesson': lesson if finished else None, 'finished': finished,
        'terminal_reason': None if finished else 'MissingSubmission',
        'contributor_ids': ['synthetic-thread-' + row['task_id']], 'model_id': 'gpt-5.6-luna',
        'created_at': '2026-01-01T00:00:00+00:00', 'selected_procedure_id': procedure_id}


@pytest.fixture
def setup(tmp_path):
    rows = [task('discovery', 'train'), task('verification', 'train'),
            task('validation', 'valid'), task('test', 'test')]
    root = tmp_path / 'memory'
    memory.initialize(root, org_id='synthetic-org', owner_user_id='synthetic-owner', tasks=rows,
        discovery_ids=['discovery'], verification_ids=['verification'],
        validation_ids=['validation'], test_ids=['test'])
    scope = memory.read(root / 'scope.json')
    source = capture(rows[0], 'DISCOVERY')
    candidate = memory.candidate_from(source, scope)[0]
    verification = capture(rows[1], 'VERIFICATION', procedure_id=candidate['procedure_id'])
    return SimpleNamespace(root=root, scope=scope, rows=rows, source=source,
                           verification=verification, candidate=candidate, temp=tmp_path)


def native_cell(setup, capture, *, suffix=''):
    """Corroborate each history action and finish with synthetic native JSONL."""
    identity = capture['task_public']['task_id']
    cell = setup.temp / ('native-' + identity + suffix)
    folder = cell / 'session-01'
    folder.mkdir(parents=True)
    state = {'task': capture['task_public'], 'arm': 'TRAIN' if capture['phase'] == 'DISCOVERY' else 'ON',
        'phase': capture['phase'], 'owner_user_id': setup.scope['owner_user_id'],
        'org_id': setup.scope['org_id'], 'candidate': capture['final_code'],
        'finished': capture['finished'], 'source_lesson': capture['source_lesson'],
        'graph': capture['graph'], 'history': capture['history'],
        'procedure_events': capture['procedure_events'], 'selected_procedure_id': capture['selected_procedure_id'],
        'runtime': {'native': {'model': capture['model_id']}}, 'started_at': capture['created_at']}
    events = [{'type': 'thread.started', 'thread_id': capture['contributor_ids'][0]}]
    calls = []
    for row in capture['history']:
        calls.append((row['request_payload'], {'step_no': row['step_no'], 'status': row['status'],
                                               'result': row['result_payload']}))
    if state['finished']:
        calls.append(({'tool': 'finish', 'arguments': {'code': state['candidate'],
            'source_lesson': state['source_lesson']}}, {'step_no': len(calls) + 1, 'status': 'success',
            'result': {'submitted': True, 'candidate_sha256': memory.sha(state['candidate'].encode())}}))
    for index, (request, response) in enumerate(calls, 1):
        item = {'id': 'synthetic-call-%d' % index, 'type': 'mcp_tool_call',
                'server': 'benchmark', 'tool': 'action', 'arguments': {'request': request}}
        events.append({'type': 'item.started', 'item': deepcopy(item)})
        events.append({'type': 'item.completed', 'item': {**item,
            'result': {'content': [{'type': 'text', 'text': json.dumps(response)}]}}})
    (folder / 'events.jsonl').write_bytes(b''.join(memory.canonical(row) for row in events))
    (folder / 'stderr.log').write_bytes(b'')
    session = {'session': 1, 'thread_ids': capture['contributor_ids'], 'benchmark_action_calls': len(calls),
        'events_sha256': memory.ref(folder / 'events.jsonl')['sha256'],
        'stderr_sha256': memory.ref(folder / 'stderr.log')['sha256']}
    memory.write_new(folder / 'receipt.json', session)
    memory.write_new(cell / 'state.json', state)
    solve = {'task_id': identity, 'arm': state['arm'], 'state_sha256': memory.ref(cell / 'state.json')['sha256'],
        'candidate_sha256': memory.sha(state['candidate'].encode()), 'sessions': [session],
        'status': 'SUBMITTED' if state['finished'] else 'GENERATION_ERROR',
        'error_type': capture['terminal_reason']}
    memory.write_new(cell / 'solve-receipt.json', solve)
    return cell, memory.ref(cell / 'solve-receipt.json')


def ingest(setup, capture):
    cell, solve = native_cell(setup, capture)
    return memory.ingest_cell(setup.root, phase=capture['phase'], state_path=cell / 'state.json',
                              solve_reference=solve)


def frozen(setup):
    ingest(setup, setup.source)
    ingest(setup, setup.verification)
    return memory.freeze(setup.root, setup.temp / 'final.json')


def test_two_independent_tasks_promote_only_private_testing_workflow(setup):
    value = memory.materialize(setup.scope, [setup.source, setup.verification])
    assert len(value['candidates']) == len(value['skills']) == 1
    skill = value['skills'][0]
    assert skill['support_task_ids'] == ['discovery', 'verification']
    assert skill['support_count'] == 2 and skill['owner_count'] == 1
    assert skill['sharing_scope'] == 'PRIVATE_OWNER_ONLY'
    assert skill['organisation_gate_b_satisfied'] is False
    assert skill['verification_claim'] == memory.CLAIM
    assert skill['oracle_scope'] == 'MODEL_GENERATED_EXPECTATIONS'


def test_discovery_alone_is_provisional_not_promoted(setup):
    value = memory.materialize(setup.scope, [setup.source])
    assert len(value['candidates']) == 1 and value['skills'] == []


@pytest.mark.parametrize('mutation', ['changed_cases', 'missing_red_anchor', 'same_code', 'runtime_red', 'late_green'])
def test_discovery_requires_exact_wa_repair_and_later_original_public_pass(setup, mutation):
    value = deepcopy(setup.source)
    if mutation == 'missing_red_anchor':
        value['source_lesson']['trace_steps'] = [2, 3]
    elif mutation == 'late_green':
        value['procedure_events'][1], green = generated(value['task_public'], 3)
        value['history'] = [value['history'][0], public(value['task_public'], 2), green]
    else:
        if mutation == 'changed_cases':
            generated_event, trace = generated(value['task_public'], 2,
                cases=[{'input': '8\n', 'output': '9\n'}, {'input': '9\n', 'output': '10\n'}])
            index = 1
        else:
            generated_event, trace = generated(value['task_public'], 1,
                                               code=GOOD if mutation == 'same_code' else BAD, passed=False)
            index = 0
            if mutation == 'runtime_red':
                generated_event['result']['failure_kind'] = 'RUNTIME_ERROR'
                generated_event['result_sha256'] = memory.digest(generated_event['result'])
                trace['result'] = trace_ref(trace['result_payload'])
        value['procedure_events'][index] = generated_event
        value['history'][index] = trace
    assert memory.candidate_from(value, setup.scope) == []


def test_false_generated_pass_is_rejected_even_with_consistent_hashes(setup):
    value = deepcopy(setup.source)
    event = value['procedure_events'][1]
    event['result'].update(passed_count=0, failed_count=2)
    event['result_sha256'] = memory.digest(event['result'])
    value['history'][1]['result_payload'] = event['result']
    value['history'][1]['result'] = trace_ref(event['result'])
    with pytest.raises(memory.PersonalMemoryError, match='FALSE_PROCEDURE_PASS'):
        memory.validate_capture(value, setup.scope)


def test_verification_requires_matching_preassigned_candidate_id(setup):
    value = capture(setup.rows[1], 'VERIFICATION')
    assert memory.verification_support(value, setup.scope, {setup.candidate['procedure_id']: setup.candidate}) == []
    value = deepcopy(setup.verification)
    value['selected_procedure_id'] = 'different-preassigned-id'
    with pytest.raises(memory.PersonalMemoryError, match='PROCEDURE_NOT_PREASSIGNED'):
        memory.verification_support(value, setup.scope, {setup.candidate['procedure_id']: setup.candidate})


@pytest.mark.parametrize('key,value', [('source_task_id', 'verification'), ('source_family_id', 'family-verification')])
def test_self_task_or_family_cannot_support_promotion(setup, key, value):
    candidate = {**setup.candidate, key: value}
    with pytest.raises(memory.PersonalMemoryError, match='PROCEDURE_SELF_VERIFICATION'):
        memory.verification_support(setup.verification, setup.scope, {candidate['procedure_id']: candidate})


def test_phase_family_overlap_and_evaluation_capture_rejected(setup):
    rows = deepcopy(setup.rows)
    rows[1]['family_id'] = rows[0]['family_id']
    with pytest.raises(memory.PersonalMemoryError, match='PHASE_FAMILY_OVERLAP'):
        memory.initialize(setup.temp / 'overlap', org_id='org', owner_user_id='owner', tasks=rows,
            discovery_ids=['discovery'], verification_ids=['verification'],
            validation_ids=['validation'], test_ids=['test'])
    value = capture(setup.rows[2], 'VALID')
    with pytest.raises(memory.PersonalMemoryError, match='EVALUATION_CAPTURE_FORBIDDEN'):
        memory.validate_capture(value, setup.scope)


def test_failed_attempt_retained_in_l1_and_l2_keeps_actual_candidate_revision(setup):
    failed = capture(setup.rows[0], 'DISCOVERY', finished=False)
    data = memory.materialize(setup.scope, [failed])
    assert len(data['episodes']) == 1 and data['episodes'][0]['succeeded'] is False
    assert data['episodes'][0]['summary']['provenance'] == 'MECHANICAL_TERMINAL_ATTEMPT_OBSERVATION'
    assert data['episodes'][0]['summary']['correction_verified'] is False
    assert not data['candidates'] and not data['skills'] and data['facts']
    assert {row['payload']['source_revision'] for row in data['facts']} == {'sha256:' + memory.sha(GOOD.encode())}
    assert {row['payload']['source_task_id'] for row in data['facts']} == {'discovery'}


def test_full_native_ingest_freeze_and_l1only_recall(setup):
    receipt = frozen(setup)
    assert receipt['status'] == 'READY' and receipt['layer_counts']['L3_personal_skills'] == 1
    with memory.load_bank(receipt['path'], receipt['sha256']) as bank:
        target, working = setup.rows[2], graph(setup.rows[2])
        normal = bank.recall(target, working, phase='VALID', owner_user_id='synthetic-owner')
        assert [row['kind'] for row in normal['injections']] == ['SKILL']
        l1 = bank.recall(target, working, phase='VALID', owner_user_id='synthetic-owner', enabled_layers=('L1',))
        assert [row['kind'] for row in l1['injections']] == ['EPISODIC']
        assert all('procedure_id' not in row for row in l1['injections'])
        resumed = bank.recall(target, working, phase='VALID', owner_user_id='synthetic-owner',
                              enabled_layers=('L1',), checkpoint=l1['checkpoint'])
        assert resumed['injections'] == []
        with pytest.raises(memory.PersonalMemoryError, match='WRONG_PRIVATE_OWNER'):
            bank.recall(target, working, phase='VALID', owner_user_id='other-owner')
        with pytest.raises(memory.PersonalMemoryError, match='TASK_PHASE_NOT_ENROLLED'):
            bank.recall(target, working, phase='TEST', owner_user_id='synthetic-owner')


@pytest.mark.parametrize('mutation', ['bank_bytes', 'derived_data', 'source_bytes'])
def test_frozen_bank_and_provenance_tamper_rejected(setup, mutation):
    receipt = frozen(setup)
    path = Path(receipt['path'])
    expected = receipt['sha256']
    if mutation == 'bank_bytes':
        path.write_bytes(path.read_bytes() + b' ')
    elif mutation == 'derived_data':
        value = memory.read(path)
        value['data']['skills'][0]['support_count'] = 99
        path.write_bytes(memory.canonical(value))
        expected = memory.ref(path)['sha256']
    else:
        source = setup.temp / 'native-discovery' / 'session-01/events.jsonl'
        source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(memory.PersonalMemoryError):
        memory.load_bank(path, expected)


def test_ingest_rejects_model_history_absent_from_native_events(setup):
    cell, solve_ref = native_cell(setup, setup.source)
    # Repin a syntactically valid but uncorroborated native receipt chain.
    folder = cell / 'session-01'
    events = [json.loads(raw) for raw in (folder / 'events.jsonl').read_bytes().splitlines()]
    events = [row for row in events if row.get('item', {}).get('id') != 'synthetic-call-1']
    (folder / 'events.jsonl').write_bytes(b''.join(memory.canonical(row) for row in events))
    session = memory.read(folder / 'receipt.json')
    session['events_sha256'] = memory.ref(folder / 'events.jsonl')['sha256']
    (folder / 'receipt.json').write_bytes(memory.canonical(session))
    solve = memory.read(solve_ref['path'])
    solve['sessions'] = [session]
    Path(solve_ref['path']).write_bytes(memory.canonical(solve))
    with pytest.raises(memory.PersonalMemoryError, match='TRACE_NOT_CORROBORATED_BY_NATIVE'):
        memory.ingest_cell(setup.root, phase='DISCOVERY', state_path=cell / 'state.json',
                           solve_reference=memory.ref(solve_ref['path']))


def test_missing_support_finishes_not_ready_without_promoting(setup):
    ingest(setup, setup.source)
    no_id = capture(setup.rows[1], 'VERIFICATION')
    ingest(setup, no_id)
    receipt = memory.freeze(setup.root, setup.temp / 'not-ready.json')
    assert receipt['status'] == 'NOT_READY' and receipt['layer_counts']['L3_personal_skills'] == 0
    with memory.load_bank(receipt['path'], receipt['sha256']) as bank:
        with pytest.raises(memory.PersonalMemoryError, match='PERSONAL_BANK_NOT_READY'):
            bank.recall(setup.rows[2], graph(setup.rows[2]), phase='VALID', owner_user_id='synthetic-owner')


def test_ingest_rejects_receipt_thread_not_in_native_events(setup):
    cell, solve_ref = native_cell(setup, setup.source)
    folder = cell / 'session-01'
    session = memory.read(folder / 'receipt.json')
    session['thread_ids'] = ['fabricated-not-in-events']
    (folder / 'receipt.json').write_bytes(memory.canonical(session))
    solve = memory.read(solve_ref['path'])
    solve['sessions'] = [session]
    Path(solve_ref['path']).write_bytes(memory.canonical(solve))
    with pytest.raises(memory.PersonalMemoryError, match='NATIVE_CONTRIBUTOR_NOT_CORROBORATED'):
        memory.ingest_cell(setup.root, phase='DISCOVERY', state_path=cell / 'state.json',
                           solve_reference=memory.ref(solve_ref['path']))


@pytest.mark.parametrize('passed', [False, True])
def test_ingest_rejects_omitted_successful_generated_call_including_wrong_answer(setup, passed):
    cell, solve_ref = native_cell(setup, setup.source)
    folder = cell / 'session-01'
    events = [json.loads(raw) for raw in (folder / 'events.jsonl').read_bytes().splitlines()]
    generated_event, trace = generated(setup.source['task_public'], 4, code=BAD, passed=passed)
    item = {'id': 'omitted-generated-call', 'type': 'mcp_tool_call', 'server': 'benchmark',
            'tool': 'action', 'arguments': {'request': trace['request_payload']}}
    extra = [{'type': 'item.started', 'item': deepcopy(item)},
             {'type': 'item.completed', 'item': {**item, 'result': {'content': [{
                 'type': 'text', 'text': json.dumps({'step_no': 4, 'status': 'success',
                                                   'result': generated_event['result']})}]}}}]
    # All bytes and receipts are consistently repinned. The missing historical
    # test must still fail, including a real WRONG_ANSWER with successful transport.
    response = json.loads(events[-1]['item']['result']['content'][0]['text'])
    response['step_no'] = 5
    events[-1]['item']['result']['content'][0]['text'] = json.dumps(response)
    events[-2:-2] = extra
    (folder / 'events.jsonl').write_bytes(b''.join(memory.canonical(row) for row in events))
    session = memory.read(folder / 'receipt.json')
    session['events_sha256'] = memory.ref(folder / 'events.jsonl')['sha256']
    session['benchmark_action_calls'] += 1
    (folder / 'receipt.json').write_bytes(memory.canonical(session))
    solve = memory.read(solve_ref['path'])
    solve['sessions'] = [session]
    Path(solve_ref['path']).write_bytes(memory.canonical(solve))
    with pytest.raises(memory.PersonalMemoryError, match='NATIVE_SUCCESSFUL_CALL_OMITTED_FROM_TRACE'):
        memory.ingest_cell(setup.root, phase='DISCOVERY', state_path=cell / 'state.json',
                           solve_reference=memory.ref(solve_ref['path']))
