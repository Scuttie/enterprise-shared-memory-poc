"""Synthetic metadata audit checks; no real run, grading, or model access."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import lcb_explicit_format_audit as audit
import lcb_explicit_format_diagnostic as diagnostic
import trimem_lcb_memory as memory


def packet():
    return {'task_id': 'synthetic', 'current_candidate': '', 'limits': {'tool_actions': 24, 'public_tests': 4},
            'context': {'memory': [], 'remaining_actions': 24, 'remaining_public_tests': 4,
                'submission_contract': {'available_trace_steps': [], 'public_test_attempts': 0},
                'graph': {'active_node_id': 'solution', 'nodes': [{'node_id': 'solution'}], 'task_evidence': []}}}


def lesson(steps):
    return {'summary': 'Synthetic method.', 'applicability': 'Synthetic condition.',
            'procedure': ['Use synthetic public evidence.'], 'trace_steps': steps}


def call(kind, identity, request, response=None):
    item = {'id': identity, 'type': 'mcp_tool_call', 'server': 'benchmark', 'tool': 'action',
            'arguments': {'request': request}}
    if response is not None:
        item['result'] = {'content': [{'type': 'text', 'text': json.dumps(response)}]}
    return {'type': kind, 'item': item}


def test_common_prefix_and_initial_pair_ignore_only_memory():
    base = packet()
    raw = b'Instructions\nSYNTHETIC CONTRACT\nTASK_PACKET:\n' + audit.canonical(base)
    parsed, prefix = audit.parse_prompt(raw, 'synthetic', 'SYNTHETIC CONTRACT')
    assert prefix == audit.sha(b'Instructions\nSYNTHETIC CONTRACT\n')
    on = deepcopy(parsed)
    on['context']['memory'] = [{'exact_text': 'SYNTHETIC_PRIVATE_MEMORY'}]
    assert audit.first_prompt_projection(on) == audit.first_prompt_projection(base)


@pytest.mark.parametrize('change', ['candidate', 'history', 'public_tests', 'budget', 'graph'])
def test_initial_target_progress_cannot_be_mistaken_for_fresh_start(change):
    value = packet()
    if change == 'candidate':
        value['current_candidate'] = '# inherited code'
    elif change == 'history':
        value['context']['submission_contract']['available_trace_steps'] = [1]
    elif change == 'public_tests':
        value['context']['submission_contract']['public_test_attempts'] = 1
    elif change == 'budget':
        value['context']['remaining_actions'] = 23
    else:
        value['context']['graph']['task_evidence'] = [{'inherited': True}]
    with pytest.raises(audit.AuditError):
        audit.first_prompt_projection(value)


@pytest.mark.parametrize('steps,valid', [([1], True), (['1'], False), ([True], False), ([2], False), ([1, 1], False), ([], False)])
def test_format_projection_uses_original_validator_and_target_local_integer_ids(steps, valid):
    request = {'tool': 'finish', 'arguments': {'code': '# synthetic', 'source_lesson': lesson(steps)}}
    value = audit.finish_shape(request, [{'step_no': 1}], memory._lesson)
    assert value['format_valid'] is valid and value['anchor_valid'] is valid
    assert 'Synthetic method' not in json.dumps(value)


def test_finish_uses_pre_finish_history_and_started_snapshot_not_its_own_response():
    first = packet()
    first['context']['submission_contract']['available_trace_steps'] = [1]
    first['context']['submission_contract']['public_test_attempts'] = 1
    request = {'tool': 'finish', 'arguments': {'code': '# SYNTHETIC_SECRET_CODE', 'source_lesson': lesson([1])}}
    response = {'step_no': 2, 'status': 'success', 'result': {'submitted': True},
                'context': {'submission_contract': {'available_trace_steps': [1]}}}
    events = [{'type': 'thread.started', 'thread_id': 'secret-thread-id'},
              call('item.started', 'finish', request), call('item.completed', 'finish', request, response)]
    state = {'history': [{'step_no': 1}, {'step_no': 3}]}
    output = audit.project_events(b''.join(audit.canonical(e) for e in events), first, state, 1, diagnostic, memory._lesson)
    finish = output['finish_attempts'][0]
    assert finish['format_valid'] is True and finish['accepted_by_broker'] is True
    assert finish['target_available_ids_at_validation'] == [1]
    assert finish['started_event']['available_before_start'] == [1]
    assert 'SYNTHETIC_SECRET' not in json.dumps(output)
    assert 'secret-thread-id' not in json.dumps(output)


def test_future_ids_advertised_in_response_fail_the_history_binding():
    request = {'tool': 'run_public_tests', 'arguments': {'code': '# synthetic'}}
    response = {'step_no': 1, 'status': 'success', 'result': {},
                'context': {'submission_contract': {'available_trace_steps': [1, 2]}}}
    events = [call('item.completed', 'public', request, response)]
    with pytest.raises(audit.AuditError, match='RESPONSE_IDS_DIFFER_FROM_VALIDATOR_HISTORY'):
        audit.project_events(b''.join(audit.canonical(e) for e in events), packet(), {'history': [{'step_no': 1}, {'step_no': 2}]}, 1, diagnostic, memory._lesson)


def test_changed_completed_request_cannot_reuse_another_started_event():
    request = {'tool': 'finish', 'arguments': {'code': '# synthetic', 'source_lesson': lesson([1])}}
    changed = deepcopy(request)
    changed['arguments']['source_lesson']['trace_steps'] = [2]
    events = [call('item.started', 'same-id', request), call('item.completed', 'same-id', changed)]
    with pytest.raises(audit.AuditError, match='START_COMPLETION_REQUEST_CHANGED'):
        audit.project_events(b''.join(audit.canonical(e) for e in events), packet(), {'history': []}, 1, diagnostic, memory._lesson)


def test_memory_projection_hashes_text_but_never_exports_it():
    text = 'SYNTHETIC_SECRET_MEMORY'
    item = {'kind': 'EPISODIC', 'memory_id': 'synthetic-episode', 'exact_text': text,
            'sha256': audit.sha(text.encode()), 'byte_count': len(text), 'active_node_id': 'solution'}
    projected = audit.injection_metadata({'arm': 'ON', 'memory_injections': [item]})
    assert projected[0]['memory_id'] == item['memory_id']
    assert text not in json.dumps(projected)
    with pytest.raises(audit.AuditError, match='OFF_MEMORY_EXPOSURE'):
        audit.injection_metadata({'arm': 'OFF', 'memory_injections': [item]})


def test_gate_rejects_unfinished_collection_before_import_or_payload_reads(tmp_path, monkeypatch):
    (tmp_path / 'collection.json').write_bytes(audit.canonical({'schema': 'lcb-explicit-format-collection/1', 'status': 'IN_PROGRESS'}))
    monkeypatch.setattr(audit.importlib, 'import_module', lambda *args: pytest.fail('No runtime imports before COMPLETE'))
    with pytest.raises(audit.AuditError, match='COLLECTION_NOT_COMPLETE'):
        audit.audit_run(tmp_path)
