"""Synthetic delivery chronology only; no pilot files, models, or evaluators."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('synthetic_timeline', HERE / 'timeline-source-001.py')
timeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timeline)

TASK = 'synthetic-timeline-task'
CODE = '# SYNTHETIC_CODE_PROSE_MUST_NOT_APPEAR\nprint(1)\n'
LESSON = 'SYNTHETIC_LESSON_PROSE_MUST_NOT_APPEAR'
MEMORY = 'SYNTHETIC_MEMORY_PROSE_MUST_NOT_APPEAR'
PROBLEM = 'SYNTHETIC_PROBLEM_PROSE_MUST_NOT_APPEAR'
REASONING = 'SYNTHETIC_REASONING_PROSE_MUST_NOT_APPEAR'


def injection(number=1, node='solution'):
    text = json.dumps({'layer': 'EPISODIC', 'summary': MEMORY, 'ordinal': number})
    return {'memory_id': 'episode:' + str(number) * 64, 'kind': 'EPISODIC', 'active_node_id': node,
        'exact_text': text, 'sha256': timeline.sha(text.encode()), 'byte_count': len(text.encode())}


def lesson(steps):
    return {'summary': LESSON, 'applicability': LESSON, 'procedure': [LESSON], 'trace_steps': steps}


def request(tool, **arguments):
    return {'tool': tool, 'arguments': arguments}


def public_request():
    return request('run_public_tests', code=CODE)


def finish_request(steps):
    return request('finish', code=CODE, source_lesson=lesson(steps))


def body(step, *, status='success', result=None, memory=(), finished=False, handoff=False):
    return {'step_no': step, 'status': status, 'result': {} if result is None else result,
        'context': {'memory': list(memory)}, 'finished': finished, 'handoff_required': handoff}


def event(kind, identity, req, response=None, *, encoded=False):
    arguments = {'request': req}
    item = {'id': identity, 'type': 'mcp_tool_call', 'server': 'benchmark', 'tool': 'action',
        'arguments': json.dumps(arguments) if encoded else arguments}
    if kind == 'item.completed':
        item.update(status='completed', result={'content': [{'type': 'text', 'text': json.dumps(response)}], 'isError': False})
    return timeline.canonical({'type': kind, 'item': item})


def pair(identity, req, response, *, encoded=False):
    return [event('item.started', identity, req, encoded=encoded),
            event('item.completed', identity, req, response, encoded=encoded)]


def history(step, req, result):
    return {'step_no': step, 'tool': req['tool'], 'status': 'success',
        'request_payload': req, 'result_payload': result}


def rejection(step, req, result):
    return {'step': step, 'request': req, 'result': result}


def bundle(number, events, *, memory=(), calls=None):
    if calls is None:
        calls = sum(json.loads(raw)['type'] == 'item.completed' and
            json.loads(raw).get('item', {}).get('type') == 'mcp_tool_call' for raw in events)
    return {'session': number, 'packet': {'task_id': TASK, 'problem': PROBLEM, 'context': {'memory': list(memory)}},
        'events': events, 'receipt': {'benchmark_action_calls': calls}}


def inputs(*, ledger=(), histories=(), rejects=(), final=None, step=2, arm='ON'):
    state = {'task': {'task_id': TASK}, 'arm': arm, 'memory_injections': list(ledger),
        'history': list(histories), 'rejected_actions': list(rejects), 'step': step,
        'finished': final is not None, 'candidate': CODE if final else '',
        'source_lesson': final['arguments']['source_lesson'] if final else None}
    solve = {'task_id': TASK, 'arm': arm, 'status': 'SUBMITTED' if final else 'GENERATION_ERROR',
        'error_type': None if final else 'MissingSubmission'}
    return state, solve


def basic(*, prompt_memory=(), result_memory=(), finish_memory=(), encoded=False):
    public, finish = public_request(), finish_request([1])
    outcome = {'status': 'PASS'}
    ledger = []
    for item in [*prompt_memory, *result_memory, *finish_memory]:
        if item not in ledger:
            ledger.append(item)
    state, solve = inputs(ledger=ledger, histories=[history(1, public, outcome)], final=finish)
    events = pair('public', public, body(1, result=outcome, memory=result_memory), encoded=encoded)
    events += pair('finish', finish, body(2, result={'submitted': True}, memory=finish_memory, finished=True), encoded=encoded)
    return state, solve, [bundle(1, events, memory=prompt_memory)]


class ChronologyTests(unittest.TestCase):
    def test_prompt_memory_precedes_first_request_with_disclosed_provenance(self):
        item = injection()
        result = timeline.audit_cell(*basic(prompt_memory=[item]))
        finish = result['finish_attempts'][0]
        self.assertEqual(finish['same_session_memory_seen_before_request'], [item['memory_id']])
        self.assertEqual(finish['target_history_ids_observed_before_request'], [1])
        delivery = result['injections'][0]['deliveries'][0]
        self.assertEqual(delivery['kind'], 'SESSION_PROMPT')
        self.assertIn('NOT_ORIGINAL_RECEIPT_PIN', delivery['provenance'])

    def test_final_ledger_presence_alone_is_not_delivery(self):
        state, solve, sessions = basic()
        state['memory_injections'] = [injection()]
        result = timeline.audit_cell(state, solve, sessions)
        self.assertEqual(result['delivery_confirmed_count'], 0)
        self.assertEqual(result['finish_attempts'][0]['same_session_memory_seen_before_request'], [])

    def test_public_result_memory_precedes_later_finish(self):
        item = injection()
        result = timeline.audit_cell(*basic(result_memory=[item]))
        finish = result['finish_attempts'][0]
        self.assertEqual(finish['same_session_memory_seen_before_request'], [item['memory_id']])
        delivery = result['injections'][0]['deliveries'][0]
        self.assertEqual(delivery['kind'], 'ACTION_RESULT')
        self.assertLess(delivery['event_line'], finish['start_event_line'])
        self.assertEqual(delivery['provenance'], 'ORIGINAL_SESSION_RECEIPT_EVENTS_HASH')

    def test_memory_in_finish_own_response_does_not_count_as_prior_exposure(self):
        item = injection()
        result = timeline.audit_cell(*basic(finish_memory=[item]))
        self.assertEqual(result['delivery_confirmed_count'], 1)
        self.assertEqual(result['finish_attempts'][0]['same_session_memory_seen_before_request'], [])

    def test_interleaved_response_after_finish_start_is_not_prior_delivery(self):
        item = injection(node='subgoal-1')
        revise = request('revise_subtask_dag', subtasks=[{'objective': 'Synthetic algorithm invariant',
            'operation': 'validate_algorithm_invariant'}])
        finish = finish_request([1])
        revised = {'dag_revised': True, 'active_node_id': 'subgoal-1'}
        denied = {'error': 'ValueError', 'message': 'Synthetic public-test prerequisite'}
        state, solve = inputs(ledger=[item], histories=[history(1, revise, revised)],
            rejects=[rejection(2, finish, denied)])
        events = [event('item.started', 'revise', revise), event('item.started', 'finish', finish),
            event('item.completed', 'revise', revise, body(1, result=revised, memory=[item])),
            event('item.completed', 'finish', finish, body(2, status='error', result=denied, memory=[item]))]
        result = timeline.audit_cell(state, solve, [bundle(1, events)])
        finish_row = result['finish_attempts'][0]
        self.assertEqual(finish_row['same_session_memory_seen_before_request'], [])
        self.assertEqual(finish_row['target_history_ids_observed_before_request'], [])
        self.assertEqual(finish_row['target_available_history_ids'], [1])
        self.assertFalse(finish_row['accepted'])

    def test_handoff_resets_same_session_memory_but_keeps_prior_task_fact(self):
        for new_memory in ([], [injection(2, 'subgoal-2')]):
            with self.subTest(new_memory=bool(new_memory)):
                old = injection(1, 'subgoal-1')
                public, complete, finish = public_request(), request('complete_subtask', evidence=LESSON), finish_request([1, 2])
                passed, completed = {'status': 'PASS'}, {'completed': True, 'handoff_required': True}
                state, solve = inputs(ledger=[old, *new_memory], histories=[history(1, public, passed),
                    history(2, complete, completed)], final=finish, step=3)
                first = pair('public', public, body(1, result=passed, memory=[old]))
                first += pair('complete', complete, body(2, result=completed, handoff=True))
                second = pair('finish', finish, body(3, result={'submitted': True}, finished=True, memory=new_memory))
                result = timeline.audit_cell(state, solve, [bundle(1, first, memory=[old]), bundle(2, second, memory=new_memory)])
                last = result['finish_attempts'][0]
                self.assertEqual(last['same_session_memory_seen_before_request'], [row['memory_id'] for row in new_memory])
                self.assertIn(old['memory_id'], last['task_memory_delivered_before_request'])

    def test_history_includes_successful_plan_but_excludes_rejected_and_finish_steps(self):
        revise = request('revise_subtask_dag', subtasks=[{'objective': 'Validate integer recurrence before evaluation',
            'operation': 'validate_integer_recurrence'}])
        public = public_request()
        bad, good = finish_request(['2']), finish_request([1, 2, 4])
        revised, passed = {'dag_revised': True, 'active_node_id': 'subgoal-1'}, {'status': 'PASS'}
        denied = {'error': 'LCBMemoryError', 'message': LESSON}
        state, solve = inputs(histories=[history(1, revise, revised), history(2, public, passed), history(4, public, passed)],
            rejects=[rejection(3, bad, denied)], final=good, step=5)
        events = pair('revise', revise, body(1, result=revised)) + pair('public1', public, body(2, result=passed))
        events += pair('bad-finish', bad, body(3, status='error', result=denied))
        events += pair('public2', public, body(4, result=passed))
        events += pair('good-finish', good, body(5, result={'submitted': True}, finished=True))
        result = timeline.audit_cell(state, solve, [bundle(1, events)])
        first, last = result['finish_attempts']
        self.assertEqual(first['target_available_history_ids'], [1, 2])
        self.assertFalse(first['accepted'])
        self.assertFalse(first['trace_steps_valid_for_target_history'])
        self.assertEqual(last['target_available_history_ids'], [1, 2, 4])
        self.assertEqual(last['target_history_ids_observed_before_request'], [1, 2, 4])
        self.assertTrue(last['trace_steps_valid_for_target_history'])


class IdentityAndEncodingTests(unittest.TestCase):
    def test_outer_logger_json_string_is_supported_but_inner_request_string_is_not(self):
        req = finish_request([1])
        self.assertEqual(timeline.request_from({'arguments': json.dumps({'request': req})}), req)
        self.assertIsNone(timeline.request_from({'arguments': {'request': json.dumps(req)}}))
        self.assertIsNone(timeline.request_from({'arguments': json.dumps({'request': json.dumps(req)})}))
        result = timeline.audit_cell(*basic(encoded=True))
        self.assertEqual(result['accepted_finish_count'], 1)

    def test_source_exact_text_mismatch_fails_even_with_self_consistent_delivery_hash(self):
        item = injection()
        state, solve, sessions = basic(prompt_memory=[item])
        changed = deepcopy(item)
        changed['exact_text'] += ' altered'
        changed['sha256'] = timeline.sha(changed['exact_text'].encode())
        changed['byte_count'] = len(changed['exact_text'].encode())
        sessions[0]['packet']['context']['memory'] = [changed]
        with self.assertRaisesRegex(timeline.AuditError, 'DELIVERY_NOT_EXACT_LEDGER_TEXT'):
            timeline.audit_cell(state, solve, sessions)

    def test_ledger_text_hash_tamper_is_rejected(self):
        state, solve, sessions = basic(prompt_memory=[injection()])
        state['memory_injections'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(timeline.AuditError, 'MEMORY_TEXT_HASH_CHANGED'):
            timeline.audit_cell(state, solve, sessions)

    def test_changed_request_between_started_and_completed_is_rejected(self):
        state, solve, sessions = basic()
        completion = json.loads(sessions[0]['events'][3])
        completion['item']['arguments']['request']['arguments']['source_lesson']['trace_steps'] = [99]
        sessions[0]['events'][3] = timeline.canonical(completion)
        with self.assertRaisesRegex(timeline.AuditError, 'START_COMPLETION_REQUEST_CHANGED'):
            timeline.audit_cell(state, solve, sessions)

    def test_missing_started_duplicate_completed_and_bad_call_count_fail_closed(self):
        for mutation, reason in [('missing_start', 'UNPAIRED_CALL_COMPLETION'),
                                 ('duplicate_completed', 'UNPAIRED_CALL_COMPLETION'),
                                 ('wrong_count', 'SESSION_CALL_COUNT_CHANGED')]:
            with self.subTest(mutation=mutation):
                state, solve, sessions = basic()
                if mutation == 'missing_start':
                    sessions[0]['events'].pop(0)
                elif mutation == 'duplicate_completed':
                    sessions[0]['events'].insert(2, sessions[0]['events'][1])
                else:
                    sessions[0]['receipt']['benchmark_action_calls'] = 3
                with self.assertRaisesRegex(timeline.AuditError, reason):
                    timeline.audit_cell(state, solve, sessions)

    def test_conflicting_result_bodies_and_mcp_error_cannot_prove_delivery(self):
        for mutation, reason in [('different_body', 'CONFLICTING_RESULT_BODIES'), ('is_error', 'CONFLICTING_MCP_ERROR')]:
            with self.subTest(mutation=mutation):
                state, solve, sessions = basic(result_memory=[injection()])
                completion = json.loads(sessions[0]['events'][1])
                result = completion['item']['result']
                if mutation == 'different_body':
                    result['structured_content'] = {'different': True}
                else:
                    result['isError'] = True
                sessions[0]['events'][1] = timeline.canonical(completion)
                with self.assertRaisesRegex(timeline.AuditError, reason):
                    timeline.audit_cell(state, solve, sessions)

    def test_metadata_output_contains_no_problem_candidate_memory_or_lesson_prose(self):
        state, solve, sessions = basic(prompt_memory=[injection()])
        sessions[0]['events'].insert(0, timeline.canonical({'type': 'item.completed',
            'item': {'type': 'agent_message', 'text': REASONING}}))
        result = timeline.audit_cell(state, solve, sessions)
        raw = json.dumps(result, ensure_ascii=False)
        for secret in (CODE.strip(), LESSON, MEMORY, PROBLEM, REASONING):
            self.assertNotIn(secret, raw)
        self.assertEqual(result['sessions'][0]['agent_message_count'], 1)


class SourceHashTests(unittest.TestCase):
    def test_semantically_same_json_with_changed_newline_fails_original_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            original = timeline.canonical({'type': 'synthetic'}) + b'\n'
            path.write_bytes(original)
            sources = timeline.Sources()
            sources.raw(path, {'sha256': timeline.sha(original)})
            path.write_bytes(original.replace(b'\n', b'\r\n'))
            with self.assertRaisesRegex(timeline.AuditError, 'SOURCE_HASH_CHANGED'):
                sources.verify()

    def test_repeated_source_read_detects_in_audit_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.json'
            path.write_bytes(b'{"synthetic":1}\n')
            sources = timeline.Sources()
            sources.read(path)
            path.write_bytes(b'{"synthetic":2}\n')
            with self.assertRaisesRegex(timeline.AuditError, 'SOURCE_CHANGED_DURING_AUDIT'):
                sources.read(path)

    def test_declared_byte_count_is_checked_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.json'
            raw = b'{}\n'
            path.write_bytes(raw)
            with self.assertRaisesRegex(timeline.AuditError, 'SOURCE_SIZE_CHANGED'):
                timeline.Sources().raw(path, {'sha256': timeline.sha(raw), 'bytes': len(raw) + 1})


if __name__ == '__main__':
    unittest.main()
