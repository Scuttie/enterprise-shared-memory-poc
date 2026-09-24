"""Read-only, content-redacted VALID memory-delivery/finish chronology audit.

Only this helper's NEW metadata output is written. No model, grader, retrieval,
or core imports. Native reasoning, code, problems and lesson prose are never
included in output or exception messages.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


class AuditError(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise AuditError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value))


class Sources:
    def __init__(self):
        self.refs = {}

    def raw(self, path, expected=None):
        path = Path(path).resolve()
        raw = path.read_bytes()
        ref = {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
        if expected:
            require(ref['sha256'] == expected['sha256'], 'SOURCE_HASH_CHANGED')
            require('bytes' not in expected or ref['bytes'] == expected['bytes'], 'SOURCE_SIZE_CHANGED')
        if str(path) in self.refs:
            require(ref == self.refs[str(path)], 'SOURCE_CHANGED_DURING_AUDIT')
        self.refs[str(path)] = ref
        return raw

    def read(self, path, expected=None):
        return json.loads(self.raw(path, expected))

    def ref(self, path):
        return self.refs[str(Path(path).resolve())]

    def verify(self):
        for ref in list(self.refs.values()):
            self.raw(ref['path'], ref)


def typed(value):
    return type(value).__name__


def shape(request, available):
    """Allowlisted names, types and exact integers only; no arbitrary strings."""
    args = request.get('arguments')
    args = args if isinstance(args, dict) else {}
    lesson = args.get('source_lesson')
    fields = ('summary', 'applicability', 'procedure', 'trace_steps')
    trace = lesson.get('trace_steps') if isinstance(lesson, dict) else None
    integers = [v for v in trace if type(v) is int] if isinstance(trace, list) else []
    valid = (isinstance(trace, list) and bool(trace) and all(type(v) is int for v in trace)
             and trace == sorted(set(trace)) and set(trace) <= set(available))
    return {'argument_fields': [k for k in ('code', 'source_lesson') if k in args],
            'unknown_argument_field_count': len(set(args) - {'code', 'source_lesson'}),
            'source_lesson_type': typed(lesson),
            'source_lesson_fields': [k for k in fields if isinstance(lesson, dict) and k in lesson],
            'source_lesson_field_types': {k: typed(lesson[k]) for k in fields if isinstance(lesson, dict) and k in lesson},
            'unknown_lesson_field_count': len(set(lesson) - set(fields)) if isinstance(lesson, dict) else 0,
            'trace_steps_container_type': typed(trace),
            'trace_steps_element_types': dict(Counter(typed(v) for v in trace)) if isinstance(trace, list) else {},
            'trace_steps_integer_values': integers,
            'trace_steps_valid_for_target_history': valid,
            'target_available_history_ids': sorted(available)}


def request_from(item):
    args = item.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, UnicodeError):
            return None
    # A string INSIDE request is not a valid native broker request.
    if not isinstance(args, dict) or set(args) != {'request'}:
        return None
    value = args['request']
    return value if isinstance(value, dict) else None


def result_from(item):
    result = item.get('result')
    require(isinstance(result, dict), 'RESULT_ENVELOPE_MISSING')
    content = result.get('content')
    require(isinstance(content, list) and len(content) == 1 and content[0].get('type') == 'text', 'AMBIGUOUS_RESULT_CONTENT')
    try:
        value = json.loads(content[0]['text'])
    except (ValueError, UnicodeError):
        require(item.get('status') == 'failed' and result.get('structured_content') is None, 'UNPARSEABLE_SUCCESS_RESULT')
        return None
    require(isinstance(value, dict), 'BAD_RESULT_BODY')
    structured = result.get('structured_content')
    require(structured is None or structured == value, 'CONFLICTING_RESULT_BODIES')
    require(not result.get('isError'), 'CONFLICTING_MCP_ERROR')
    require(set(value) == {'step_no', 'status', 'result', 'context', 'finished', 'handoff_required'}, 'UNEXPECTED_RESULT_SHAPE')
    return value


def audit_cell(state, solve, sessions):
    """Pure audit over already hash-bound objects (also used by synthetic tests)."""
    require(state['task']['task_id'] == solve['task_id'] and state['arm'] == solve['arm'], 'CELL_IDENTITY_CHANGED')
    ledger = state['memory_injections']
    entries = {}
    for ordinal, item in enumerate(ledger):
        key = digest(item)
        require(key not in entries, 'DUPLICATE_LEDGER_ENTRY')
        require(sha(item['exact_text'].encode()) == item['sha256'] and len(item['exact_text'].encode()) == item['byte_count'], 'MEMORY_TEXT_HASH_CHANGED')
        entries[key] = {'injection_ordinal': ordinal, 'memory_id': item['memory_id'],
                        'ledger_entry_sha256': key, 'exact_text_sha256': item['sha256'], 'deliveries': []}
    if state['arm'] == 'OFF':
        require(not ledger, 'OFF_MEMORY_LEDGER_NONEMPTY')
    histories = {r['step_no']: r for r in state['history']}
    rejects = {r['step']: r for r in state.get('rejected_actions', [])}
    require(len(histories) == len(state['history']) and len(rejects) == len(state.get('rejected_actions', [])), 'DUPLICATE_TRACE_STEP')
    observed_history, observed_rejects, available, actions, finishes = set(), set(), set(), [], []
    global_order = 0
    previous_step = 0
    prior_task_deliveries = set()
    session_views = []

    def deliver(context, session, index, kind, current_seen, event_seen, event_hash=None):
        require(isinstance(context, dict) and isinstance(context.get('memory'), list), 'MEMORY_CONTEXT_MISSING')
        keys = []
        for item in context['memory']:
            key = digest(item)
            require(key in entries and ledger[entries[key]['injection_ordinal']] == item, 'DELIVERY_NOT_EXACT_LEDGER_TEXT')
            delivery = {'session': session, 'event_line': index, 'kind': kind,
                        'event_sha256': event_hash,
                        'provenance': 'ORIGINAL_SESSION_RECEIPT_EVENTS_HASH' if kind == 'ACTION_RESULT' else 'RETAINED_PROMPT_HASH_AT_AUDIT_NOT_ORIGINAL_RECEIPT_PIN'}
            entries[key]['deliveries'].append(delivery)
            current_seen.add(key)
            if kind == 'ACTION_RESULT':
                event_seen.add(key)
            prior_task_deliveries.add(key)
            keys.append(key)
        return keys

    for bundle in sessions:
        number, packet, events = bundle['session'], bundle['packet'], bundle['events']
        require(packet['task_id'] == solve['task_id'], 'PROMPT_TASK_CHANGED')
        current_seen, event_seen, starts, completed = set(), set(), {}, set()
        deliver(packet['context'], number, 0, 'SESSION_PROMPT', current_seen, event_seen)
        agent_messages = 0
        calls = 0
        for line_no, raw_event in enumerate(events, 1):
            event = json.loads(raw_event)
            global_order += 1
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                agent_messages += 1
            if item.get('type') != 'mcp_tool_call':
                continue
            require(item.get('server') == 'benchmark' and item.get('tool') == 'action', 'UNEXPECTED_TOOL')
            call_id = item.get('id')
            require(isinstance(call_id, str), 'CALL_ID_MISSING')
            if event['type'] == 'item.started':
                require(call_id not in starts, 'DUPLICATE_CALL_START')
                starts[call_id] = {'line': line_no, 'request': request_from(item), 'event_sha256': sha(raw_event),
                                  'seen': set(current_seen), 'task_seen': set(prior_task_deliveries),
                                  'event_seen': set(event_seen),
                                  'available_at_start': set(available)}
                continue
            if event['type'] != 'item.completed':
                continue
            require(call_id not in completed and call_id in starts, 'UNPAIRED_CALL_COMPLETION')
            completed.add(call_id)
            start = starts[call_id]
            req = request_from(item)
            require(req == start['request'], 'START_COMPLETION_REQUEST_CHANGED')
            response = result_from(item)
            calls += 1
            tool = req.get('tool') if isinstance(req, dict) else None
            safe_tool = tool if tool in ('finish', 'run_public_tests', 'complete_subtask', 'revise_subtask_dag') else 'INVALID_OPERATION'
            row = {'session': number, 'call_id_sha256': sha(call_id.encode()), 'tool': safe_tool,
                   'start_event_line': start['line'], 'completed_event_line': line_no,
                   'start_event_sha256': start['event_sha256'], 'completed_event_sha256': sha(raw_event),
                   'request_sha256': digest(req), 'response_sha256': digest(response) if response is not None else None,
                   'step_no': response['step_no'] if response else None,
                   'status': response['status'] if response else 'TRANSPORT_ERROR',
                   'finished': response['finished'] if response else None,
                   'handoff_required': response['handoff_required'] if response else None}
            if response is not None:
                step = response['step_no']
                require(type(step) is int and step > previous_step, 'NONMONOTONIC_BROKER_STEPS')
                previous_step = step
                require(response['status'] in ('success', 'error'), 'UNKNOWN_BROKER_STATUS')
                if response['status'] == 'error':
                    r = rejects.get(step)
                    require(r is not None and r['request'] == req and r['result'] == response['result'], 'REJECTION_TRACE_MISMATCH')
                    observed_rejects.add(step)
                    error = response['result'].get('error')
                    row['error_type'] = error if error in ('ValueError', 'LCBMemoryError', 'RuntimeError') else 'OTHER'
                elif tool != 'finish':
                    h = histories.get(step)
                    require(h is not None and h['request_payload'] == req and h['result_payload'] == response['result'] and h['tool'] == tool and h['status'] == 'success', 'PUBLIC_HISTORY_MISMATCH')
                    observed_history.add(step)
                if tool == 'finish':
                    before = sorted(k for k in histories if k < step)
                    row.update(shape(req, before))
                    row['target_history_ids_observed_before_request'] = sorted(start['available_at_start'])
                    row['accepted'] = response['status'] == 'success' and response['result'].get('submitted') is True and response['finished'] is True
                    if row['accepted']:
                        require(req['arguments']['code'] == state['candidate'] and req['arguments']['source_lesson'] == state['source_lesson'], 'ACCEPTED_SUBMISSION_CHANGED')
                    row['same_session_memory_seen_before_request'] = sorted(entries[k]['memory_id'] for k in start['seen'])
                    row['same_session_injections_seen_before_request'] = sorted(start['seen'])
                    row['same_session_event_confirmed_injections_before_request'] = sorted(start['event_seen'])
                    row['task_memory_delivered_before_request'] = sorted(entries[k]['memory_id'] for k in start['task_seen'])
                    finishes.append(row)
                row['response_memory_injection_hashes'] = deliver(response['context'], number, line_no, 'ACTION_RESULT', current_seen, event_seen, sha(raw_event))
                if response['status'] == 'success' and tool != 'finish':
                    available.add(step)
            actions.append(row)
        require(set(starts) == completed, 'UNFINISHED_TOOL_CALL')
        require(calls == bundle['receipt']['benchmark_action_calls'], 'SESSION_CALL_COUNT_CHANGED')
        session_views.append({'session': number, 'benchmark_action_calls': calls,
                              'agent_message_count': agent_messages, 'references': bundle.get('references', {})})
    require(observed_history == set(histories) and observed_rejects == set(rejects), 'TRACE_COVERAGE_INCOMPLETE')
    require(sum(f['accepted'] for f in finishes) == int(state['finished']), 'FINISH_TERMINAL_MISMATCH')
    require(previous_step == state['step'], 'TERMINAL_STEP_MISMATCH')
    return {'task_id': solve['task_id'], 'arm': solve['arm'], 'status': solve['status'],
            'error_type': solve['error_type'], 'sessions': session_views, 'actions': actions,
            'finish_attempts': finishes, 'injections': list(entries.values()),
            'injection_count': len(entries),
            'delivery_confirmed_count': sum(bool(x['deliveries']) for x in entries.values()),
            'finish_attempt_count': len(finishes), 'accepted_finish_count': sum(x['accepted'] for x in finishes),
            'rejected_finish_count': sum(not x['accepted'] for x in finishes)}


def run(pilot, audit_path):
    pilot = Path(pilot).resolve()
    sources = Sources()
    audit = sources.read(audit_path)
    require(audit['audit_status'] == 'PASS' and audit['coverage'] == 'COMPLETE', 'EXPOSURE_AUDIT_NOT_COMPLETE')
    summary = sources.read(pilot / 'summary.json', audit['summary_reference'])
    require(summary['status'] == 'COMPLETE', 'PILOT_NOT_COMPLETE')
    config = sources.read(audit['config_reference']['path'], audit['config_reference'])
    split = sources.read(audit['public_split_reference']['path'], audit['public_split_reference'])
    frozen = sources.read(pilot / 'frozen-inputs.json')
    require(frozen['model'] == config['requested_model'] and frozen['reasoning_effort'] == config['reasoning_effort'], 'FROZEN_MODEL_IDENTITY_CHANGED')
    require(any(Path(r['path']).resolve() == Path(audit['config_reference']['path']).resolve() and r['sha256'] == audit['config_reference']['sha256'] for r in frozen['references']), 'FROZEN_CONFIG_NOT_BOUND')
    for ref in frozen['implementation']:
        sources.raw(ref['path'], ref)
    sources.raw(audit['bank_reference']['path'], audit['bank_reference'])
    expected_ids = set(split['pilot_ids'])
    selected = [r for r in summary['cells'] if r['arm'] in ('OFF', 'ON')]
    require(len(selected) == len(expected_ids) * 2 and len({(r['task_id'], r['arm']) for r in selected}) == len(selected), 'PAIRED_DENOMINATOR_CHANGED')
    require(all({r['task_id'] for r in selected if r['arm'] == arm} == expected_ids for arm in ('OFF', 'ON')), 'VALID_ID_SET_CHANGED')
    # The prior audit's "injection_sha256" is the exact-text hash, not the
    # canonical hash of the entire ledger entry used for chronology here.
    expected_injections = {(x['target_task_id'], x['injection_ordinal'], x['memory_id'], x['injection_sha256']) for x in audit['exposures']}
    cells = []
    for summary_row in selected:
        solve_path = Path(summary_row['solve_reference']['path']).resolve()
        require(solve_path.is_relative_to(pilot / 'cells'), 'CELL_PATH_OUTSIDE_PILOT')
        solve = sources.read(solve_path, summary_row['solve_reference'])
        cell = solve_path.parent
        state = sources.read(cell / 'state.json', {'sha256': solve['state_sha256']})
        require(solve['task_id'] == summary_row['task_id'] and solve['arm'] == summary_row['arm'], 'SUMMARY_IDENTITY_CHANGED')
        require(state['task']['split'] == 'valid', 'NONVALID_TASK')
        bundles = []
        for position, session in enumerate(solve['sessions'], 1):
            require(session['session'] == position and session['returncode'] == 0 and not session['unexpected_tools'], 'NATIVE_SESSION_INVALID')
            require(session['requested_model'] == config['requested_model'] and session['requested_reasoning_effort'] == config['reasoning_effort'], 'MODEL_IDENTITY_CHANGED')
            folder = cell / ('session-%02d' % position)
            receipt = sources.read(folder / 'receipt.json')
            require(receipt == session, 'SESSION_SOLVE_BINDING_CHANGED')
            eventraw = sources.raw(folder / 'events.jsonl', {'sha256': receipt['events_sha256']})
            sources.raw(folder / 'stderr.log', {'sha256': receipt['stderr_sha256']})
            prompt = sources.raw(folder / 'prompt.txt').decode('utf8')
            require(prompt.count('TASK_PACKET:\n') == 1, 'PROMPT_PACKET_AMBIGUOUS')
            packet = json.loads(prompt.split('TASK_PACKET:\n', 1)[1])
            bundles.append({'session': position, 'receipt': receipt, 'packet': packet,
                            'events': eventraw.splitlines(), 'references': {name: sources.ref(folder / name) for name in ('receipt.json', 'events.jsonl', 'stderr.log', 'prompt.txt')}})
        view = audit_cell(state, solve, bundles)
        if solve['arm'] == 'ON':
            require({(solve['task_id'], i['injection_ordinal'], i['memory_id'], i['exact_text_sha256']) for i in view['injections']} == {x for x in expected_injections if x[0] == solve['task_id']}, 'EXPOSURE_LEDGER_CHANGED')
            for item in view['injections']:
                match = next(x for x in audit['exposures'] if x['target_task_id'] == solve['task_id'] and x['injection_ordinal'] == item['injection_ordinal'])
                item['source_task_id'] = match['source_task_id']
        view['state_reference'] = sources.ref(cell / 'state.json')
        view['solve_reference'] = sources.ref(solve_path)
        cells.append(view)
    aggregates = {}
    for arm in ('OFF', 'ON'):
        group = [c for c in cells if c['arm'] == arm]
        fs = [f for c in group for f in c['finish_attempts']]
        aggregates[arm] = {'cells': len(group), 'sessions': sum(len(c['sessions']) for c in group),
                           'finish_attempts': len(fs), 'accepted': sum(f['accepted'] for f in fs),
                           'rejected': sum(not f['accepted'] for f in fs),
                           'injections': sum(c['injection_count'] for c in group),
                           'delivery_confirmed_injections': sum(c['delivery_confirmed_count'] for c in group),
                           'cells_with_delivery': sum(bool(c['delivery_confirmed_count']) for c in group),
                           'finish_attempts_with_same_session_prior_delivery': sum(bool(f['same_session_memory_seen_before_request']) for f in fs),
                           'accepted_finish_with_same_session_prior_delivery': sum(f['accepted'] and bool(f['same_session_memory_seen_before_request']) for f in fs),
                           'accepted_finish_with_original_event_pinned_prior_delivery': sum(f['accepted'] and bool(f['same_session_event_confirmed_injections_before_request']) for f in fs),
                           'event_confirmed_injections': sum(any(d['kind'] == 'ACTION_RESULT' for d in i['deliveries']) for c in group for i in c['injections']),
                           'prompt_only_injections': sum(bool(i['deliveries']) and not any(d['kind'] == 'ACTION_RESULT' for d in i['deliveries']) for c in group for i in c['injections'])}
    sources.verify()
    return {'schema': 'trimem/lcb-native-delivery-timeline/1.0', 'audit_status': 'PASS',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'coverage': 'ALL_24_VALID_PAIRS',
            'aggregates': aggregates, 'cells': cells, 'source_references': list(sources.refs.values()),
            'helper_reference': {'path': str(Path(__file__).resolve()), 'sha256': sha(Path(__file__).read_bytes())},
            'source_hashes_unchanged_before_after': True, 'model_calls': 0, 'grader_calls': 0,
            'retrieval_calls': 0, 'original_writes': 0, 'private_grader_artifacts_opened': False,
            'reasoning_or_problem_code_lesson_text_in_output': False,
            'limitations': ['Delivery is recorded availability, not proof of reading, use, or causal effect.',
                'Original receipts pin native events/stderr, not prompt bytes. Prompt hashes are analysis-time observations of retained files.',
                'Chronology uses native event line order and call STARTED/COMPLETED pairing, not unrecorded per-injection timestamps.',
                'Prior-session delivery is reported separately and is not treated as same-session availability.',
                'An empty same-session structured context.memory does not exclude information paraphrased into L0 working context or handoff evidence; no semantic analysis of that prose was performed.',
                'History IDs are validator-available successful non-finish steps; projected prompt context may contain fewer IDs.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--exposure-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'OUTPUT_ALREADY_EXISTS')
    report = run(args.pilot, args.exposure_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(canonical(report) + b'\n')
    print(json.dumps({'audit_status': report['audit_status'], 'aggregates': report['aggregates'],
                      'output_sha256': sha(args.output.read_bytes())}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except AuditError as exc:
        raise SystemExit(str(exc)) from None
