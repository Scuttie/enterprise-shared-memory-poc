"""Synthetic metadata checks; no models, graders or real experiment inputs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('execution_audit_test_subject', Path(__file__).with_name('audit_execution.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def schedule():
    tasks = [f'synthetic-{i:02d}' for i in range(24)]
    trials = []
    for repeat in (1, 2, 3):
        for index, task in enumerate(tasks):
            for arm in (('KEEP', 'DROP') if index % 2 == 0 else ('DROP', 'KEEP')):
                trials.append({'trial_id': f'{task}-{repeat}-{arm}', 'task_id': task, 'repeat': repeat, 'arm': arm})
    result = {'status': 'COMPLETE', 'planned': 144, 'completed': 144,
              'trials': [{**t, 'launch_ordinal': i, 'metrics': {m: None for m in audit.METRICS}}
                         for i, t in enumerate(trials, 1)]}
    return {'task_ids': tasks, 'repeats': 3, 'trials': trials}, result


def test_all144_nulls_remain_admissible_but_full_paired_coverage_and_order_required():
    protocol, result = schedule()
    assert audit.validate_schedule(protocol, result) == [
        {'repeat': r, 'KEEP_first': 12, 'DROP_first': 12} for r in (1, 2, 3)]


@pytest.mark.parametrize('mutation', ['partial', 'missing', 'order', 'ordinal', 'dimension', 'numeric_boolean'])
def test_schedule_rejects_incomplete_or_identity_denominator_changes(mutation):
    protocol, result = schedule()
    if mutation == 'partial':
        result['status'] = 'IN_PROGRESS'
    elif mutation == 'missing':
        protocol['trials'].pop()
    elif mutation == 'order':
        result['trials'][0], result['trials'][1] = result['trials'][1], result['trials'][0]
    elif mutation == 'ordinal':
        result['trials'][0]['launch_ordinal'] = 2
    elif mutation == 'dimension':
        protocol['trials'][0]['arm'] = 'DROP'
    else:
        result['trials'][0]['metrics']['submission_valid'] = 1
    with pytest.raises(audit.AuditError):
        audit.validate_schedule(protocol, result)


def event(kind, identity, request):
    return {'type': kind, 'item': {'id': identity, 'type': 'mcp_tool_call',
            'server': 'benchmark', 'tool': 'action', 'arguments': {'request': request}}}


def wire(events):
    return b''.join(audit.canonical(e) for e in events)


def test_first_start_and_complete_confirm_the_same_sealed_invocation_without_payload_export():
    request = {'tool': 'finish', 'arguments': {'code': 'SYNTHETIC_SECRET_CODE',
                'source_lesson': {'summary': 'SYNTHETIC_SECRET_LESSON'}}}
    events = [event('item.started', 'call-1', request), event('item.completed', 'call-1', request)]
    report = audit.event_request_evidence(wire(events), audit.sha(audit.canonical(request)))
    assert report['first_native_invocation_confirmed'] is True
    assert report['extra_benchmark_action'] is False
    assert report['first_started']['line'] == 1
    assert report['first_completed']['line'] == 2
    assert 'SYNTHETIC_SECRET' not in json.dumps(report)
    assert 'call-1' not in json.dumps(report)


def test_later_matching_request_cannot_confirm_first_native_request():
    first, sealed = {'tool': 'other'}, {'tool': 'finish'}
    events = [event('item.started', 'first', first), event('item.started', 'sealed', sealed),
              event('item.completed', 'sealed', sealed), event('item.completed', 'first', first)]
    report = audit.event_request_evidence(wire(events), audit.sha(audit.canonical(sealed)))
    assert report['sealed_matches_first_started'] is False
    assert report['sealed_matches_first_completed'] is True
    assert report['first_start_completion_same_invocation'] is False
    assert report['first_native_invocation_confirmed'] is False
    assert report['extra_benchmark_action'] is True


@pytest.mark.parametrize('mutation', ['different_ids', 'missing_id', 'completion_before_start', 'missing_complete'])
def test_equal_request_bytes_alone_do_not_prove_same_invocation_or_chronology(mutation):
    request = {'tool': 'finish'}
    events = [event('item.started', 'one', request), event('item.completed', 'one', request)]
    if mutation == 'different_ids':
        events[1]['item']['id'] = 'two'
    elif mutation == 'missing_id':
        events[0]['item'].pop('id')
    elif mutation == 'completion_before_start':
        events.reverse()
    else:
        events.pop()
    report = audit.event_request_evidence(wire(events), audit.sha(audit.canonical(request)))
    assert report['first_native_invocation_confirmed'] is False


def test_no_action_is_unknown_evidence_not_a_fabricated_success():
    report = audit.event_request_evidence(b'', None)
    assert report['sealed_request_present'] is False
    assert report['sealed_matches_first_started'] is None
    assert report['sealed_matches_first_completed'] is None
    assert report['first_native_invocation_confirmed'] is False


def test_malformed_envelope_matches_the_original_broker_empty_request_projection():
    events = [event('item.started', 'one', {}), event('item.completed', 'one', {})]
    for item in events:
        item['item']['arguments'] = {'request': {'tool': 'finish'}, 'unexpected': True}
    report = audit.event_request_evidence(wire(events), audit.sha(audit.canonical({})))
    assert report['first_native_invocation_confirmed'] is True


def test_reference_guard_detects_mutation_without_including_file_payload(tmp_path):
    path = tmp_path / 'synthetic.json'
    path.write_bytes(b'{"opaque":"SYNTHETIC_SECRET"}')
    sources = audit.Sources()
    sources.raw(path)
    path.write_bytes(b'{"opaque":"changed"}')
    with pytest.raises(audit.AuditError, match='REFERENCE_HASH_CHANGED') as error:
        sources.verify()
    assert 'SYNTHETIC_SECRET' not in str(error.value)


def test_complete_gate_runs_before_importing_validator_or_touching_other_inputs(tmp_path, monkeypatch):
    (tmp_path / 'results.json').write_bytes(audit.canonical({'status': 'IN_PROGRESS'}))
    monkeypatch.setattr(audit, 'load_module', lambda *args: pytest.fail('Must not import before COMPLETE'))
    with pytest.raises(audit.AuditError, match='NOT_COMPLETE'):
        audit.audit_run(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['results.json']


def test_active_controller_is_rejected_before_reading_any_results(tmp_path):
    (tmp_path / 'run.lock').write_bytes(b'')
    with pytest.raises(audit.AuditError, match='CONTROLLER_STILL_ACTIVE'):
        audit.audit_run(tmp_path)


@pytest.fixture
def packet_fixture(tmp_path):
    preparer = audit.load_module('execution_audit_packet_preparer', audit.REPO / 'scripts/lcb_format_ablation_prepare.py')
    runner = audit.load_module('execution_audit_packet_runner', audit.REPO / 'scripts/lcb_format_ablation_runner.py')
    protocol, _ = schedule()
    checkpoints = []
    for task in protocol['task_ids']:
        folder = tmp_path / task
        folder.mkdir()
        history = [{'step_no': 2, 'tool': 'run_public_tests', 'status': 'success'}]
        candidate = '# Synthetic code; never executed\n'
        packet = {'task_id': task, 'current_candidate': candidate, 'public_history': history,
                  'context': {'memory': [], 'remaining_actions': 1, 'remaining_public_tests': 0}}
        (folder / 'history.json').write_bytes(audit.canonical(history))
        for arm in ('KEEP', 'DROP'):
            (folder / f'{arm}.json').write_bytes(preparer.canonical(packet) + b'\n')
            (folder / f'{arm}.txt').write_bytes(preparer.INSTRUCTIONS.encode() + preparer.canonical(packet) + b'\n')
            for trial in protocol['trials']:
                if trial['task_id'] == task and trial['arm'] == arm:
                    for kind, name in [('packet', f'{arm}.json'), ('prompt', f'{arm}.txt'), ('history', 'history.json')]:
                        trial[kind + '_path'] = f'{task}/{name}'
                        trial[kind + '_sha256'] = audit.sha((folder / name).read_bytes())
                    trial['candidate_sha256'] = audit.sha(candidate.encode())
        checkpoints.append({'task_id': task, 'no_memory_control': True,
                            'candidate_sha256': audit.sha(candidate.encode()), 'history_ids': [2]})
    protocol['checkpoints'] = checkpoints
    return tmp_path, protocol, preparer, runner


def test_every_repeat_reuses_same_packet_and_zero_memory_control_prompt_bytes(packet_fixture):
    root, protocol, preparer, runner = packet_fixture
    rows = audit.check_packets(root, protocol, preparer, runner, audit.Sources())
    assert len(rows) == 24
    assert all(row['pair_assertion_passed'] and row['identical_prompt_bytes'] and row['no_memory_control'] for row in rows)


@pytest.mark.parametrize('mutation', ['prompt', 'history', 'candidate_authority'])
def test_even_consistently_rehashed_packet_inputs_cannot_break_semantic_binding(packet_fixture, mutation):
    root, protocol, preparer, runner = packet_fixture
    task = protocol['task_ids'][0]
    if mutation == 'candidate_authority':
        protocol['checkpoints'][0]['candidate_sha256'] = '0' * 64
    else:
        name = 'KEEP.txt' if mutation == 'prompt' else 'history.json'
        path = root / task / name
        path.write_bytes(b'Altered instructions\n' if mutation == 'prompt' else audit.canonical([{'step_no': 99}]))
        for trial in protocol['trials']:
            if trial['task_id'] == task and (mutation == 'history' or trial['arm'] == 'KEEP'):
                trial[mutation + '_sha256'] = audit.sha(path.read_bytes())
    with pytest.raises(audit.AuditError):
        audit.check_packets(root, protocol, preparer, runner, audit.Sources())
