"""Read-only metadata audit of a sealed explicit-format OFF/ON collection.

Run after collection.json and diagnostic-selection.json exist. No model,
retrieval, grading, bank write, or cell write is performed. Payloads are parsed
only for validation; output contains hashes, IDs, counts and bounded categories.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
LAYERS = {'EPISODIC': 'L1', 'REPOSITORY_SEMANTIC': 'L2', 'SKILL': 'L3'}


class AuditError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise AuditError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() + b'\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Sources:
    def __init__(self):
        self.refs = {}

    def raw(self, path, expected=None):
        path = Path(path).resolve()
        raw = path.read_bytes()
        ref = {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
        if expected is not None:
            require(ref['sha256'] == expected['sha256'] and ('bytes' not in expected or ref['bytes'] == expected['bytes']), 'BOUND_SOURCE_CHANGED')
            require('path' not in expected or Path(expected['path']).resolve() == path, 'BOUND_PATH_CHANGED')
        require(str(path) not in self.refs or self.refs[str(path)] == ref, 'SOURCE_CHANGED_DURING_AUDIT')
        self.refs[str(path)] = ref
        return raw

    def read(self, path, expected=None):
        return json.loads(self.raw(path, expected))

    def ref(self, path):
        return self.refs[str(Path(path).resolve())]

    def verify(self):
        for ref in list(self.refs.values()):
            self.raw(ref['path'], ref)


def parse_prompt(raw, task_id, contract):
    prefix, body = raw.decode('utf-8').split('TASK_PACKET:\n', 1)
    require(prefix.count(contract) == 1 and 'ACTUAL_PUBLIC_TRACE_STEP' not in prefix, 'COMMON_GUIDANCE_CHANGED')
    packet = json.loads(body)
    require(packet['task_id'] == task_id, 'PROMPT_TASK_CHANGED')
    rules = packet['context']['submission_contract']
    ids = rules['available_trace_steps']
    require(isinstance(ids, list) and all(type(n) is int for n in ids) and ids == sorted(set(ids)), 'PROMPT_TRACE_IDS_INVALID')
    return packet, sha(prefix.encode())


def first_prompt_projection(packet):
    require(packet['current_candidate'] == '', 'NONEMPTY_INITIAL_CANDIDATE')
    require(packet['context']['submission_contract']['available_trace_steps'] == []
            and packet['context']['submission_contract']['public_test_attempts'] == 0, 'NONEMPTY_INITIAL_PUBLIC_HISTORY')
    require(packet['context']['remaining_actions'] == packet['limits']['tool_actions']
            and packet['context']['remaining_public_tests'] == packet['limits']['public_tests'], 'INITIAL_BUDGET_CONSUMED')
    graph = packet['context']['graph']
    require(graph['active_node_id'] == 'solution' and len(graph['nodes']) == 1
            and graph.get('task_evidence') == [], 'NONINITIAL_GRAPH')
    common = deepcopy(packet)
    common['context']['memory'] = []
    return sha(canonical(common))


def finish_shape(request, history, lesson_validator):
    """Syntax/lesson validity, separately from public-test prerequisite or outcome."""
    result = {'format_valid': False, 'anchor_valid': False, 'reason': 'REQUEST_SHAPE',
              'trace_steps_type': None, 'trace_element_types': [], 'trace_integer_values': []}
    if not isinstance(request, dict) or set(request) != {'tool', 'arguments'} or request.get('tool') != 'finish':
        return result
    args = request.get('arguments')
    if not isinstance(args, dict) or set(args) != {'code', 'source_lesson'}:
        return result
    code, lesson = args['code'], args['source_lesson']
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > 65536:
        result['reason'] = 'CODE_SHAPE_OR_SIZE'
        return result
    if not isinstance(lesson, dict) or set(lesson) != {'summary', 'applicability', 'procedure', 'trace_steps'}:
        result['reason'] = 'LESSON_KEYS'
        return result
    trace = lesson['trace_steps']
    result.update(trace_steps_type=type(trace).__name__,
                  trace_element_types=sorted({type(v).__name__ for v in trace}) if isinstance(trace, list) else [],
                  trace_integer_values=[v for v in trace if type(v) is int] if isinstance(trace, list) else [])
    available = {h['step_no'] for h in history}
    result['anchor_valid'] = (isinstance(trace, list) and bool(trace) and all(type(n) is int for n in trace)
                              and trace == sorted(set(trace)) and set(trace) <= available)
    if len(canonical(lesson)) > 8000:
        result['reason'] = 'LESSON_BYTE_LIMIT'
        return result
    try:
        lesson_validator(lesson, history)
    except ValueError:
        result['reason'] = 'ANCHOR_INVALID' if not result['anchor_valid'] else 'LESSON_VALUE_INVALID'
        return result
    result.update(format_valid=True, reason='VALID_FORMAT')
    return result


def project_events(raw, packet, state, session, diagnostic, lesson_validator):
    """Project completed requests and bind their STARTED requests without prose."""
    starts, finishes, threads, tools = {}, [], [], Counter()
    malformed, native_errors, action_calls = 0, 0, 0
    available = list(packet['context']['submission_contract']['available_trace_steps'])
    history_ids = {r['step_no'] for r in state['history']}
    require(set(available) <= history_ids, 'PROMPT_IDS_NOT_IN_FINAL_HISTORY')
    initial_available = list(available)
    response_context_count = 0
    for line_no, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        if event.get('type') == 'thread.started':
            identity = event.get('thread_id')
            require(isinstance(identity, str) and bool(identity), 'EMPTY_NATIVE_THREAD')
            threads.append(sha(identity.encode()))
        if event.get('type') in ('error', 'turn.failed'):
            native_errors += 1
        if event.get('type') not in ('item.started', 'item.completed'):
            continue
        item = event.get('item', {})
        require(isinstance(item, dict), 'MALFORMED_NATIVE_ITEM')
        is_action = (item.get('type'), item.get('server'), item.get('tool')) == ('mcp_tool_call', 'benchmark', 'action')
        if not is_action:
            if item.get('type') not in ('agent_message', 'reasoning', 'error', 'todo_list', 'plan_update'):
                tools['UNEXPECTED_NATIVE_TOOL'] += 1
            continue
        request = diagnostic.request_from(item)
        key = item.get('id')
        if event['type'] == 'item.started':
            require(key is not None and key not in starts, 'DUPLICATE_OR_MISSING_CALL_ID')
            starts[key] = {'request_sha256': sha(canonical(request)), 'event_line': line_no,
                           'event_sha256': sha(line), 'available_before_start': list(available)}
            continue
        action_calls += 1
        response = diagnostic.response_from(item)
        start = starts.get(key)
        if start:
            require(start['request_sha256'] == sha(canonical(request)), 'START_COMPLETION_REQUEST_CHANGED')
        if isinstance(request, dict) and request.get('tool') == 'finish':
            step = response.get('step_no') if response else None
            eligible = [h for h in state['history'] if type(step) is int and h['step_no'] < step]
            shape = finish_shape(request, eligible, lesson_validator) if type(step) is int else {
                'format_valid': None, 'anchor_valid': None, 'reason': 'NO_BROKER_STEP',
                'trace_steps_type': None, 'trace_element_types': [], 'trace_integer_values': []}
            finishes.append({'session': session, 'event_line': line_no, 'event_sha256': sha(line),
                'request_sha256': sha(canonical(request)), 'step_no': step,
                'started_event': start, 'target_available_ids_at_validation': [h['step_no'] for h in eligible],
                'accepted_by_broker': bool(response and response.get('status') == 'success'
                                           and response.get('result', {}).get('submitted') is True),
                'broker_response_present': response is not None, **shape})
        if response and 'context' in response:
            response_context_count += 1
            visible = response['context']['submission_contract']['available_trace_steps']
            require(all(type(n) is int for n in visible) and visible == sorted(set(visible)), 'RESPONSE_TRACE_IDS_INVALID')
            step = response['step_no']
            require(visible == sorted(h['step_no'] for h in state['history'] if h['step_no'] <= step), 'RESPONSE_IDS_DIFFER_FROM_VALIDATOR_HISTORY')
            available = visible
    return {'thread_id_hashes': threads, 'benchmark_action_calls': action_calls,
            'unexpected_native_tool_events': tools['UNEXPECTED_NATIVE_TOOL'], 'malformed_event_lines': malformed,
            'native_error_events': native_errors, 'response_contexts_verified': response_context_count,
            'initial_available_trace_ids': initial_available, 'finish_attempts': finishes}


def injection_metadata(state):
    rows = []
    for item in state.get('memory_injections', []):
        kind = item['kind']
        require(kind in LAYERS, 'UNKNOWN_MEMORY_LAYER')
        require(sha(item['exact_text'].encode()) == item['sha256']
                and len(item['exact_text'].encode()) == item['byte_count'], 'MEMORY_VIEW_CHANGED')
        rows.append({k: item[k] for k in ('kind', 'memory_id', 'sha256', 'byte_count', 'active_node_id')})
    require(state['arm'] == 'ON' or not rows, 'OFF_MEMORY_EXPOSURE')
    return rows


def audit_run(root):
    root = Path(root).resolve()
    sources = Sources()
    sources.raw(__file__)
    collection = sources.read(root / 'collection.json')
    require(collection.get('schema') == 'lcb-explicit-format-collection/1' and collection.get('status') == 'COMPLETE'
            and collection.get('planned_cells') == collection.get('completed_cells') == len(collection['rows']) == 48, 'COLLECTION_NOT_COMPLETE')
    frozen = sources.read(collection['frozen_inputs_reference']['path'], collection['frozen_inputs_reference'])
    for ref in frozen['references'] + collection['source_references']:
        sources.raw(ref['path'], ref)
    frozen_paths = {str(Path(r['path']).resolve()) for r in frozen['references']}
    for name in ('lcb_explicit_format_native.py', 'lcb_explicit_format_experiment.py', 'lcb_explicit_format_diagnostic.py', 'trimem_lcb_memory.py'):
        require(str(REPO / 'scripts' / name) in frozen_paths, 'AUDIT_VALIDATOR_NOT_FROZEN')
    sys.dont_write_bytecode = True
    for folder in (REPO / 'scripts', REPO / 'src'):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    manager = importlib.import_module('lcb_explicit_format_experiment')
    native = manager.native
    diagnostic = importlib.import_module('lcb_explicit_format_diagnostic')
    memory = importlib.import_module('trimem_lcb_memory')
    for module in (manager, native, diagnostic, memory):
        require(str(Path(module.__file__).resolve()) in frozen_paths, 'WRONG_IMPORTED_MODULE')
    collection_ref = sources.ref(root / 'collection.json')
    require(manager.verify_collection(root, collection_ref) == collection, 'COLLECTION_VALIDATOR_DISAGREEMENT')
    selection_path = root / 'diagnostic-selection.json'
    require(selection_path.is_file(), 'DIAGNOSTIC_SELECTION_PENDING')
    sources.raw(selection_path)
    selection_ref = sources.ref(selection_path)
    selection = diagnostic.selection_guard(root, selection_ref, collection_ref)
    for row in selection['rows']:
        if row['candidate_reference']:
            sources.raw(row['candidate_reference']['path'], row['candidate_reference'])
    identities = [(r['task_id'], r['arm']) for r in collection['rows']]
    scheduled = [(r['task_id'], r['arm']) for r in frozen['schedule']]
    task_ids = {r['task_id'] for r in collection['rows']}
    require(identities == scheduled and len(set(identities)) == 48 and len(task_ids) == 24
            and set(identities) == {(t, arm) for t in task_ids for arm in ('OFF', 'ON')}, 'PAIRED_COHORT_CHANGED')
    rows, all_threads, guidance, first_common = [], [], set(), {}
    first_prompt_times = []
    for ordinal, generation in enumerate(collection['rows'], 1):
        name = manager.exp.cell_name(generation['task_id'], generation['arm'])
        cell = root / 'cells' / name
        state = sources.read(cell / 'state.json')
        solve = sources.read(cell / 'solve-receipt.json', generation['solve_reference'])
        if generation['arm'] == 'ON':
            require(all(state['bank'].get(k) == frozen['source_bank_reference'][k] for k in ('path', 'sha256')), 'TARGET_BANK_CHANGED')
        else:
            require(state.get('bank') is None, 'OFF_BANK_CONFIGURED')
        require(sources.ref(cell / 'state.json')['sha256'] == solve['state_sha256'], 'TERMINAL_STATE_CHANGED')
        rebuilt = manager.exp._cell_result(cell, state['task'], state['arm'], solve, state)
        require(manager.generation_row(rebuilt) == generation, 'GENERATION_METADATA_CHANGED')
        exposures = injection_metadata(state)
        session_rows, finish_rows = [], []
        for index, receipt in enumerate(solve['sessions'], 1):
            require(receipt['session'] == index, 'SESSION_SEQUENCE_CHANGED')
            folder = cell / ('session-%02d' % index)
            raw = sources.raw(folder / 'prompt.txt')
            proof = sources.read(folder / 'prompt-receipt.json')
            require(proof['task_id'] == generation['task_id'] and proof['arm'] == generation['arm']
                    and proof['session'] == index and proof['prompt_sha256'] == sha(raw)
                    and proof['prompt_bytes'] == len(raw) and proof['contract_sha256'] == sha(native.CONTRACT.encode()), 'PROMPT_PROOF_CHANGED')
            require(proof['command_sha256'] == sha(native.canonical(native.worker_command(cell, {**state, 'session': index}))), 'PROMPT_COMMAND_CHANGED')
            packet, prefix_hash = parse_prompt(raw, generation['task_id'], native.CONTRACT)
            guidance.add(prefix_hash)
            if index == 1:
                first_common[generation['task_id'], generation['arm']] = first_prompt_projection(packet)
                first_prompt_times.append(proof['created_at'])
            prompt_memory = packet['context']['memory']
            require(all(any(item == known for known in state['memory_injections']) for item in prompt_memory), 'PROMPT_MEMORY_NOT_IN_LEDGER')
            events = sources.raw(folder / 'events.jsonl', {'sha256': receipt['events_sha256']})
            sources.raw(folder / 'stderr.log', {'sha256': receipt['stderr_sha256']})
            require(sources.read(folder / 'receipt.json') == receipt, 'SESSION_RECEIPT_CHANGED')
            projected = project_events(events, packet, state, index, diagnostic, memory._lesson)
            require(projected['benchmark_action_calls'] == receipt['benchmark_action_calls'], 'ACTION_COUNT_CHANGED')
            require(projected['thread_id_hashes'] == [sha(t.encode()) for t in receipt['thread_ids']], 'THREAD_IDS_CHANGED')
            all_threads.extend(projected['thread_id_hashes'])
            finish_rows.extend(projected.pop('finish_attempts'))
            session_rows.append({'session': index, 'prompt_reference': sources.ref(folder / 'prompt.txt'),
                                 'prompt_receipt_reference': sources.ref(folder / 'prompt-receipt.json'),
                                 'common_guidance_sha256': prefix_hash, 'returncode': receipt['returncode'],
                                 'wall_seconds': receipt['wall_seconds'], **projected})
        first_finish = finish_rows[0] if finish_rows else None
        rows.append({'task_id': generation['task_id'], 'arm': generation['arm'], 'scheduled_ordinal': ordinal,
                     'generation_status': generation['status'], 'generation_error_type': generation.get('error_type'),
                     'candidate_sha256': generation['candidate_sha256'], 'session_count': len(session_rows),
                     'wall_seconds': generation['wall_seconds'], 'tool_seconds': generation['tool_seconds'],
                     'tool_actions': generation['tool_actions'], 'public_test_runs': generation['public_test_runs'],
                     'public_infrastructure_errors': generation['public_infrastructure_errors'], 'tokens': generation['tokens'],
                     'initial_candidate_and_history_empty': bool(session_rows), 'memory_injections': exposures,
                     'memory_injections_by_layer': dict(Counter(LAYERS[r['kind']] for r in exposures)),
                     'unique_episode_count': len({r['memory_id'] for r in exposures if r['kind'] == 'EPISODIC'}),
                     'first_finish_format_valid': first_finish['format_valid'] if first_finish else None,
                     'finish_count': len(finish_rows), 'finish_format_errors': sum(f['format_valid'] is False for f in finish_rows),
                     'finish_attempts': finish_rows, 'sessions': session_rows})
    require(len(guidance) <= 1, 'COMMON_GUIDANCE_DIFFERS_BETWEEN_CALLS')
    comparable = [t for t in task_ids if (t, 'OFF') in first_common and (t, 'ON') in first_common]
    require(all(first_common[t, 'OFF'] == first_common[t, 'ON'] for t in comparable), 'INITIAL_NONMEMORY_PAIR_DIFFERS')
    grade_starts = []
    for path in sorted((root / 'primary-grade-starts').glob('*.json')):
        value = sources.read(path)
        require(value['collection_reference'] == collection_ref, 'GRADE_NOT_BOUND_TO_COLLECTION')
        match = next((r for r in collection['rows'] if r['task_id'] == value['task_id'] and r['arm'] == value['arm']), None)
        require(match is not None and value['generation_row_sha256'] == sha(canonical(match)), 'GRADE_GENERATION_CHANGED')
        require(not first_prompt_times or value['recorded_at'] >= max(first_prompt_times), 'GRADE_PRECEDES_COLLECTION_STARTS')
        grade_starts.append({'task_id': value['task_id'], 'arm': value['arm'], 'recorded_at': value['recorded_at'], 'reference': sources.ref(path)})
    sources.verify()
    require(manager.verify_collection(root, collection_ref) == collection, 'COLLECTION_CHANGED_AFTER_AUDIT')
    flags = {'duplicate_thread_hashes': len(all_threads) - len(set(all_threads)),
             'cells_without_native_sessions': sum(not r['sessions'] for r in rows),
             'sessions_without_exactly_one_thread': sum(len(s['thread_id_hashes']) != 1 for r in rows for s in r['sessions']),
             'unexpected_native_tool_events': sum(s['unexpected_native_tool_events'] for r in rows for s in r['sessions']),
             'malformed_native_event_lines': sum(s['malformed_event_lines'] for r in rows for s in r['sessions']),
             'native_error_events': sum(s['native_error_events'] for r in rows for s in r['sessions']),
             'finish_requests_without_started_evidence': sum(f['started_event'] is None for r in rows for f in r['finish_attempts'])}
    arms = {}
    for arm in ('OFF', 'ON'):
        selected = [r for r in rows if r['arm'] == arm]
        tokens = Counter()
        for row in selected:
            tokens.update(row['tokens'])
        arms[arm] = {'planned': 24, 'submitted': sum(r['generation_status'] == 'SUBMITTED' for r in selected),
                     'first_finish_format_valid': sum(r['first_finish_format_valid'] is True for r in selected),
                     'first_finish_format_invalid': sum(r['first_finish_format_valid'] is False for r in selected),
                     'first_finish_unavailable': sum(r['first_finish_format_valid'] is None for r in selected),
                     'cells_with_any_finish_format_error': sum(r['finish_format_errors'] > 0 for r in selected),
                     'finish_attempts': sum(r['finish_count'] for r in selected),
                     'wall_seconds_sum': sum(r['wall_seconds'] for r in selected),
                     'tool_actions': sum(r['tool_actions'] for r in selected),
                     'public_test_runs': sum(r['public_test_runs'] for r in selected), 'tokens': dict(tokens),
                     'memory_injections_by_layer': dict(Counter(LAYERS[item['kind']] for r in selected for item in r['memory_injections'])),
                     'unique_episode_ids': sorted({item['memory_id'] for r in selected for item in r['memory_injections'] if item['kind'] == 'EPISODIC'})}
    return {'schema': 'lcb-explicit-format-execution-audit/1',
            'audit_status': 'PASS' if not any(flags.values()) else 'PROVENANCE_VALID_WITH_EXECUTION_FLAGS',
            'created_at': datetime.now(timezone.utc).isoformat(), 'collection_reference': collection_ref,
            'selection_reference': selection_ref, 'source_bank_reference': frozen['source_bank_reference'],
            'task_count': 24, 'cell_count': 48, 'native_session_count': len(all_threads),
            'common_guidance_sha256': next(iter(guidance), None), 'common_contract_sha256': sha(native.CONTRACT.encode()),
            'initial_nonmemory_pairs_verified': len(comparable),
            'initial_nonmemory_packets_identical_per_pair': True if len(comparable) == 24 else None,
            'first_session_candidate_and_history_empty': True if len(first_common) == 48 else None,
            'original_state_and_source_hashes_unchanged': True, 'flags': flags, 'arms': arms, 'cells': rows,
            'ordering_evidence': {'collection_complete': True, 'all48_diagnostic_choices_sealed': True,
                'primary_grade_starts_bound_to_collection': len(grade_starts), 'primary_grade_starts': grade_starts,
                'frozen_manager_enforces_selection_before_grading': True,
                'primary_grade_start_records_pin_selection_hash': False,
                'limitation': 'Ordering is enforced by pinned manager code and reference dependencies. Primary grade starts pin collection, not the selection digest; no independent selection timestamp or original pre-call state snapshot is claimed.'},
            'new_model_calls': 0, 'new_grader_calls': 0, 'memory_writes': 0, 'original_cell_writes': 0,
            'payloads_exported': False, 'source_references': list(sources.refs.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists() and not args.output.resolve().is_relative_to(args.root.resolve()), 'FRESH_EXTERNAL_OUTPUT_REQUIRED')
    result = audit_run(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n')
    print(json.dumps({k: result[k] for k in ('audit_status', 'task_count', 'cell_count', 'flags', 'arms')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'audit_status': 'FAIL', 'error_class': type(exc).__name__,
                          'error_code': str(exc) if isinstance(exc, AuditError) else 'VALIDATION_EXCEPTION'}))
        raise SystemExit(1) from None
