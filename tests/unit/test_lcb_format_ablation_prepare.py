"""Synthetic ablation preparation checks; no real runs, models or graders."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_format_ablation_prepare as prepare


def memory_view():
    lesson = {
        'summary': 'Synthetic narrative retains the literal trace_steps token and the number 11.',
        'applicability': 'Synthetic source-only example.',
        'procedure': ['Keep this prose mentioning step_no unchanged.', 'Synthetic second instruction.'],
        'trace_steps': [2, 11],
        'provenance': 'MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS',
        'verification_scope': 'PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER',
    }
    actions = [
        {'tool': 'run_public_tests', 'step_no': 2, 'request_sha256': 'a' * 64, 'result_sha256': 'b' * 64},
        {'tool': 'complete_subtask', 'step_no': 11, 'request_sha256': 'c' * 64, 'result_sha256': 'd' * 64},
    ]
    view = {'layer': 'EPISODIC', 'subgoal': 'Synthetic applicability',
            'summary': json.dumps(lesson, ensure_ascii=False, indent=2),
            'actions': [json.dumps(action, indent=2) for action in actions],
            'source_outcome': 'passed', 'source_revision': 'sha256:' + 'e' * 64,
            'verification_command': '["lcb_public_tests", "synthetic-source", "opaque-test-hash"]'}
    return view, lesson, actions


def decoded(text):
    view = json.loads(text)
    return view, json.loads(view['summary']), [json.loads(action) for action in view['actions']]


def test_canonical_has_exact_utf8_sorted_compact_bytes_without_newline():
    assert prepare.canonical({'z': '합성', 'a': 2}) == '{"a":2,"z":"합성"}'.encode('utf-8')
    assert prepare.digest({'a': 2}) == prepare.sha(b'{"a":2}')


def test_keep_and_drop_share_canonical_serialization_at_all_three_levels():
    original, lesson, actions = memory_view()
    original_raw = json.dumps(original, ensure_ascii=False, indent=4)
    for drop in (False, True):
        result = prepare.transformed_view(original_raw, drop=drop)
        view, actual_lesson, actual_actions = decoded(result)
        assert result.encode() == prepare.canonical(view)
        assert view['summary'].encode() == prepare.canonical(actual_lesson)
        assert [value.encode() for value in view['actions']] == [prepare.canonical(value) for value in actual_actions]
        expected_lesson, expected_actions = deepcopy(lesson), deepcopy(actions)
        if drop:
            expected_lesson.pop('trace_steps')
            for action in expected_actions:
                action.pop('step_no')
        assert actual_lesson == expected_lesson
        assert actual_actions == expected_actions


def test_drop_removes_only_two_declared_paths_and_never_rewrites_narrative():
    original, lesson, actions = memory_view()
    raw = json.dumps(original)
    keep, keep_lesson, keep_actions = decoded(prepare.transformed_view(raw, drop=False))
    drop, drop_lesson, drop_actions = decoded(prepare.transformed_view(raw, drop=True))
    assert {key: value for key, value in keep.items() if key not in ('summary', 'actions')} == {
        key: value for key, value in drop.items() if key not in ('summary', 'actions')}
    assert set(keep_lesson) - set(drop_lesson) == {'trace_steps'}
    assert keep_lesson['trace_steps'] == [2, 11]
    for left, right in zip(keep_actions, drop_actions):
        assert set(left) - set(right) == {'step_no'}
        assert right == {key: value for key, value in left.items() if key != 'step_no'}
    for key in ('summary', 'applicability', 'procedure', 'provenance', 'verification_scope'):
        assert drop_lesson[key] == lesson[key]
    assert 'trace_steps' in drop_lesson['summary']
    assert 'step_no' in drop_lesson['procedure'][0]
    assert '11' in drop_lesson['summary']
    assert 'trace_steps' not in drop_lesson  # No invalid/null placeholder.
    assert all('step_no' not in action for action in drop_actions)
    assert json.loads(raw) == original


def pair_packets(injection=True):
    view, _, _ = memory_view()
    source = {'kind': 'EPISODIC', 'memory_id': 'episode:synthetic', 'exact_text': json.dumps(view)} if injection else None
    base = {'task_id': 'synthetic-target', 'current_candidate': '# synthetic fixed candidate\n',
            'context': {'memory': [], 'remaining_actions': 1, 'remaining_public_tests': 0},
            'public_history': [{'step_no': 2, 'tool': 'run_public_tests'}]}
    keep, drop = deepcopy(base), deepcopy(base)
    keep['context']['memory'] = prepare.memory_view(source, False)
    drop['context']['memory'] = prepare.memory_view(source, True)
    return keep, drop


def restamp(item, view):
    item['exact_text'] = prepare.canonical(view).decode()
    item['sha256'] = prepare.sha(item['exact_text'].encode())
    item['byte_count'] = len(item['exact_text'].encode())


def test_pair_accepts_only_declared_difference_without_mutating_inputs():
    keep, drop = pair_packets()
    before = deepcopy((keep, drop))
    prepare.assert_pair(keep, drop)
    assert (keep, drop) == before


def test_zero_memory_control_packets_are_identical():
    keep, drop = pair_packets(injection=False)
    assert keep == drop
    assert keep['context']['memory'] == []
    prepare.assert_pair(keep, drop)


@pytest.mark.parametrize('field', ['current_candidate', 'public_history', 'context_limit'])
def test_pair_rejects_candidate_history_or_budget_changes(field):
    keep, drop = pair_packets()
    if field == 'context_limit':
        drop['context']['remaining_actions'] = 2
    elif field == 'public_history':
        drop[field].append({'step_no': 99, 'tool': 'run_public_tests'})
    else:
        drop[field] += '# changed'
    with pytest.raises(ValueError, match='NONMEMORY_PAIR_DIFFERENCE'):
        prepare.assert_pair(keep, drop)


@pytest.mark.parametrize('change', ['narrative', 'source_revision', 'memory_id', 'hash', 'bytes'])
def test_pair_rejects_extra_memory_changes_even_with_consistent_new_hash(change):
    keep, drop = pair_packets()
    item = drop['context']['memory'][0]
    if change == 'narrative':
        view = json.loads(item['exact_text'])
        lesson = json.loads(view['summary'])
        lesson['summary'] = 'Altered synthetic narrative'
        view['summary'] = prepare.canonical(lesson).decode()
        restamp(item, view)
    elif change == 'source_revision':
        view = json.loads(item['exact_text'])
        view['source_revision'] = 'sha256:' + '0' * 64
        restamp(item, view)
    elif change == 'memory_id':
        item['memory_id'] = 'episode:foreign'
    elif change == 'hash':
        item['sha256'] = '0' * 64
    else:
        item['byte_count'] += 1
    with pytest.raises(ValueError):
        prepare.assert_pair(keep, drop)


def test_pair_rejects_dropped_whole_memory_instead_of_anchor_fields():
    keep, drop = pair_packets()
    drop['context']['memory'] = []
    with pytest.raises(ValueError, match='MEMORY_CARDINALITY_CHANGED'):
        prepare.assert_pair(keep, drop)


@pytest.fixture
def checkpoint(tmp_path):
    identity = 'synthetic-target'
    candidate = '# exact first requested candidate\nprint(7)\n'
    first_request = {'tool': 'finish', 'arguments': {'code': candidate,
        'source_lesson': {'summary': 'ORIGINAL_REJECTED_LESSON_MUST_NOT_REACH', 'trace_steps': ['invalid']}}}
    before_context = {'memory': [], 'remaining_actions': 10, 'remaining_public_tests': 3,
                      'working_context': {'marker': 'LAST_DELIVERED_PUBLIC_CONTEXT'}}
    after_context = {'memory': [{'future': 'FUTURE_MEMORY_MUST_NOT_REACH'}],
                     'working_context': {'marker': 'FUTURE_CONTEXT_MUST_NOT_REACH'}}
    public_request = {'tool': 'run_public_tests', 'arguments': {'code': '# prior publicly tested candidate'}}
    result = {'step_no': 2, 'status': 'success', 'result': {'status': 'PASS'}, 'context': before_context,
              'finished': False, 'handoff_required': False}
    def started(call, request):
        return {'type': 'item.started', 'item': {'id': call, 'type': 'mcp_tool_call',
            'server': 'benchmark', 'tool': 'action', 'arguments': {'request': request}}}
    def completed(call, request, body):
        row = started(call, request)
        row['type'] = 'item.completed'
        row['item'].update(status='completed', result={'content': [{'type': 'text', 'text': json.dumps(body)}]})
        return row
    lines = [started('public', public_request), completed('public', public_request, result),
             started('first-finish', first_request),
             completed('first-finish', first_request, {**result, 'step_no': 3, 'status': 'error',
                'result': {'error': 'LCBMemoryError', 'message': 'FIRST_FINISH_FEEDBACK_MUST_NOT_REACH'}}),
             completed('future-public', public_request, {**result, 'step_no': 4, 'context': after_context})]
    event_raw = b'\n'.join(prepare.canonical(row) for row in lines) + b'\n'
    event_path = tmp_path / 'events.jsonl'
    event_path.write_bytes(event_raw)
    packet = {'task_id': identity, 'title': 'Synthetic checkpoint', 'problem': 'Synthetic public prompt.',
              'starter_code': '', 'public_examples': [], 'current_candidate': '# older candidate',
              'context': {'memory': [], 'working_context': {'marker': 'OLD_SESSION_PROMPT_CONTEXT'}}}
    prompt_raw = b'Synthetic instructions\nTASK_PACKET:\n' + prepare.canonical(packet)
    prompt_path = tmp_path / 'prompt.txt'
    prompt_path.write_bytes(prompt_raw)
    state = {'task': {'task_id': identity, 'difficulty': 'easy'}, 'arm': 'OFF',
             'candidate': '# FINAL_FUTURE_CANDIDATE_MUST_NOT_REACH',
             'source_lesson': {'summary': 'FINAL_FUTURE_LESSON_MUST_NOT_REACH'},
             'history': [
                 {'step_no': 1, 'tool': 'revise_subtask_dag', 'status': 'success'},
                 {'step_no': 2, 'tool': 'run_public_tests', 'status': 'success',
                  'request_payload': public_request, 'result_payload': {'status': 'PASS'}},
                 {'step_no': 4, 'tool': 'run_public_tests', 'status': 'success',
                  'result_payload': {'future': 'FUTURE_RESULT_MUST_NOT_REACH'}}]}
    first = {'session': 1, 'step_no': 3, 'start_event_line': 3,
             'start_event_sha256': prepare.sha(prepare.canonical(lines[2])),
             'request_sha256': prepare.digest(first_request),
             'target_history_ids_observed_before_request': [1, 2], 'target_available_history_ids': [1, 2]}
    timeline = {'task_id': identity, 'arm': 'OFF', 'finish_attempts': [first], 'sessions': [
        {'session': 1, 'references': {
            'events.jsonl': {'path': str(event_path), 'sha256': prepare.sha(event_raw)},
            'prompt.txt': {'path': str(prompt_path), 'sha256': prepare.sha(prompt_raw)}}}]}
    return state, timeline, candidate, event_path, prompt_path


def test_checkpoint_uses_first_requested_code_and_only_pre_start_public_context(checkpoint):
    state, timeline, candidate, events, prompt = checkpoint
    originals = deepcopy((state, timeline)), events.read_bytes(), prompt.read_bytes()
    packet, history, metadata = prepare.make_checkpoint(state, timeline)
    assert packet['current_candidate'] == candidate
    assert packet['context']['working_context']['marker'] == 'LAST_DELIVERED_PUBLIC_CONTEXT'
    assert packet['context']['remaining_actions'] == 1
    assert packet['context']['remaining_public_tests'] == 0
    assert [row['step_no'] for row in history] == [1, 2]
    assert packet['public_history'] == history
    assert metadata['candidate_sha256'] == prepare.sha(candidate.encode())
    assert metadata['original_source_lesson_included'] is False
    assert metadata['post_finish_feedback_included'] is False
    wire = json.dumps(packet)
    assert 'MUST_NOT_REACH' not in wire
    assert 'OLD_SESSION_PROMPT_CONTEXT' not in wire
    assert originals == ((state, timeline), events.read_bytes(), prompt.read_bytes())


def test_checkpoint_rejects_inflight_history_not_delivered_before_start(checkpoint):
    state, timeline, *_ = checkpoint
    timeline['finish_attempts'][0]['target_history_ids_observed_before_request'] = [1]
    with pytest.raises(ValueError, match='INFLIGHT_CHECKPOINT_AMBIGUITY'):
        prepare.make_checkpoint(state, timeline)


@pytest.mark.parametrize('part', ['events', 'start_event', 'request', 'prompt', 'history'])
def test_checkpoint_rejects_changed_original_references_or_missing_public_history(checkpoint, part):
    state, timeline, _, events, prompt = checkpoint
    if part == 'events':
        events.write_bytes(events.read_bytes() + b'\n')
    elif part == 'start_event':
        timeline['finish_attempts'][0]['start_event_sha256'] = '0' * 64
    elif part == 'request':
        timeline['finish_attempts'][0]['request_sha256'] = '0' * 64
    elif part == 'prompt':
        prompt.write_bytes(prompt.read_bytes() + b'\n')
    else:
        state['history'] = [row for row in state['history'] if row['step_no'] != 2]
    with pytest.raises(ValueError):
        prepare.make_checkpoint(state, timeline)


@pytest.mark.parametrize('change', ['state_task', 'timeline_task', 'state_arm', 'timeline_arm'])
def test_checkpoint_rejects_cross_task_or_on_arm(checkpoint, change):
    state, timeline, *_ = checkpoint
    if change == 'state_task':
        state['task']['task_id'] = 'foreign-task'
    elif change == 'timeline_task':
        timeline['task_id'] = 'foreign-task'
    elif change == 'state_arm':
        state['arm'] = 'ON'
    else:
        timeline['arm'] = 'ON'
    with pytest.raises(ValueError, match='CHECKPOINT_IDENTITY_CHANGED'):
        prepare.make_checkpoint(state, timeline)


def test_checkpoint_rejects_rehashed_prompt_of_a_different_task(checkpoint):
    state, timeline, _, _, prompt = checkpoint
    raw = prompt.read_bytes().replace(b'synthetic-target', b'foreign-task')
    prompt.write_bytes(raw)
    timeline['sessions'][0]['references']['prompt.txt']['sha256'] = prepare.sha(raw)
    with pytest.raises(ValueError, match='PROMPT_IDENTITY_CHANGED'):
        prepare.make_checkpoint(state, timeline)


@pytest.mark.parametrize('history_ids', [[1, 3], [1, 4], [True, 2], [1, '2']])
def test_checkpoint_rejects_current_future_or_noninteger_history_even_if_both_views_agree(checkpoint, history_ids):
    state, timeline, *_ = checkpoint
    first = timeline['finish_attempts'][0]
    first['target_history_ids_observed_before_request'] = history_ids
    first['target_available_history_ids'] = history_ids
    with pytest.raises(ValueError, match='FUTURE_HISTORY_STEP'):
        prepare.make_checkpoint(state, timeline)
