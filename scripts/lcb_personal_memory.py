"""Owner-private LCB experience and independently demonstrated testing workflows.

This additive authority does not change organisation skill promotion. Procedure
verification certifies observable execution patterns with model-authored expected
outputs, not algorithm semantics, oracle correctness, or hidden-test correctness.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re

import trimem_lcb_memory as base
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph
from enterprise_memory.trimem.subgoal_context import project_subgoal_context

SCHEMA = 'lcb/personal-memory/1'
RESULT_SCHEMA = 'lcb/personal-procedure-test/1'
METHODS = ('boundary_cases', 'differential_cases')
PHASES = ('DISCOVERY', 'VERIFICATION', 'VALID', 'TEST')
POLICY = 'PRIVATE_OWNER_TWO_TASK_DISCOVERY_AND_VERIFICATION'
CLAIM = 'OBSERVED_TESTING_WORKFLOW_NOT_ALGORITHM_OR_ORACLE_CORRECTNESS'


class PersonalMemoryError(ValueError):
    pass


def require(value, code):
    if not value:
        raise PersonalMemoryError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(canonical(value))


def read(path):
    return json.loads(Path(path).read_bytes())


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def checked(reference):
    require(isinstance(reference, dict) and set(reference) >= {'path', 'sha256', 'bytes'}, 'INVALID_REFERENCE')
    path = Path(reference['path']).resolve()
    require(ref(path) == reference, 'REFERENCED_BYTES_CHANGED')
    return path


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    if path.exists():
        require(path.read_bytes() == raw, 'IMMUTABLE_RECORD_DIFFERS')
    else:
        with path.open('xb') as stream:
            stream.write(raw)


@contextmanager
def lock(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'memory.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PersonalMemoryError('MEMORY_BUSY') from None
        try:
            yield root
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def initialize(root, *, org_id, owner_user_id, tasks, discovery_ids, verification_ids,
               validation_ids=(), test_ids=(), source_references=()):
    require(all(isinstance(v, str) and v.strip() for v in (org_id, owner_user_id)), 'INVALID_OWNER')
    descriptors = {task['task_id']: base._descriptor(task) for task in tasks}
    require(len(descriptors) == len(tasks), 'DUPLICATE_TASK')
    groups = dict(zip(PHASES, map(list, (discovery_ids, verification_ids, validation_ids, test_ids))))
    seen, family_phase, instruction_phase = set(), {}, {}
    for phase, ids in groups.items():
        require(len(ids) == len(set(ids)) and not seen.intersection(ids), 'PHASE_TASK_OVERLAP')
        seen.update(ids)
        for identity in ids:
            require(identity in descriptors, 'TASK_NOT_ENROLLED')
            row = descriptors[identity]
            expected = 'train' if phase in ('DISCOVERY', 'VERIFICATION') else ('valid' if phase == 'VALID' else 'test')
            require(row['split'] == expected, 'TASK_SPLIT_CHANGED')
            family = row['family_id']
            require(family not in family_phase or family_phase[family] == phase, 'PHASE_FAMILY_OVERLAP')
            family_phase[family] = phase
            instruction = row['instruction_sha256']
            require(instruction not in instruction_phase or instruction_phase[instruction] == phase, 'PHASE_INSTRUCTION_OVERLAP')
            instruction_phase[instruction] = phase
    require(groups['DISCOVERY'] and groups['VERIFICATION'], 'TWO_TRAINING_PHASES_REQUIRED')
    require(seen == set(descriptors), 'UNSCHEDULED_TASK_DESCRIPTOR')
    for reference in source_references:
        checked(reference)
    value = {'schema': SCHEMA, 'org_id': org_id, 'owner_user_id': owner_user_id,
             'repository': base.REPOSITORY, 'tasks': [descriptors[k] for k in sorted(descriptors)],
             'phases': groups, 'source_references': list(source_references),
             'promotion_policy': POLICY, 'verification_claim': CLAIM}
    with lock(root) as root:
        write_new(root / 'scope.json', value)
        return ref(root / 'scope.json')


def scope_task(scope, task, phase):
    require(phase in PHASES and task['task_id'] in scope['phases'][phase], 'TASK_PHASE_NOT_ENROLLED')
    require(base._descriptor(task) in scope['tasks'], 'PUBLIC_TASK_DESCRIPTOR_CHANGED')


def procedure_observation(task, event, history):
    require(type(event.get('step_no')) is int and event['step_no'] > 0, 'INVALID_PROCEDURE_STEP')
    request, result = event.get('request'), event.get('result')
    require(isinstance(request, dict) and set(request) <= {'code', 'cases', 'method', 'rationale', 'procedure_id'} and
            set(request) >= {'code', 'cases', 'method', 'rationale'}, 'PROCEDURE_REQUEST_SHAPE')
    method = request['method']
    require(method in METHODS and event.get('method') == method, 'PROCEDURE_METHOD_CHANGED')
    require(isinstance(request['code'], str) and request['code'].strip() and len(request['code'].encode()) <= 65536, 'PROCEDURE_CODE_INVALID')
    require(isinstance(request['rationale'], str) and 0 < len(request['rationale'].encode()) <= 6000, 'PROCEDURE_RATIONALE_INVALID')
    cases = request['cases']
    require(isinstance(cases, list) and 2 <= len(cases) <= 12 and len(canonical(cases)) <= 32768, 'PROCEDURE_CASE_BUDGET')
    require(all(isinstance(c, dict) and set(c) == {'input', 'output'} and
                all(isinstance(v, str) for v in c.values()) for c in cases), 'PROCEDURE_CASE_SHAPE')
    require(len({c['input'] for c in cases}) == len(cases), 'DUPLICATE_GENERATED_INPUT')
    procedure_id = request.get('procedure_id')
    require(procedure_id is None or isinstance(procedure_id, str), 'PROCEDURE_ID_TYPE')
    require(event.get('procedure_id') == procedure_id, 'PROCEDURE_ID_CHANGED')
    require(event.get('request_sha256', digest(request)) == digest(request) and
            event.get('result_sha256', digest(result)) == digest(result), 'PROCEDURE_PAYLOAD_HASH_CHANGED')
    require(result.get('schema') == RESULT_SCHEMA and result.get('task_id') == task['task_id'] and
            result.get('candidate_sha256') == sha(request['code'].encode()) and
            result.get('cases_sha256') == digest(cases) and result.get('method') == method and
            result.get('procedure_id') == procedure_id and result.get('oracle_scope') == 'MODEL_GENERATED_EXPECTATIONS', 'PROCEDURE_RESULT_BINDING')
    counts = [result.get(k) for k in ('passed_count', 'failed_count', 'not_run_count')]
    require(result.get('test_count') == len(cases) and all(type(v) is int and v >= 0 for v in counts) and
            sum(counts) == len(cases) and type(result.get('timed_out')) is bool, 'PROCEDURE_COUNTS_INVALID')
    status = result.get('status')
    require(status in ('PASS', 'FAIL', 'INFRA_ERROR'), 'PROCEDURE_STATUS_INVALID')
    require('passed' not in result or result['passed'] is {'PASS': True, 'FAIL': False, 'INFRA_ERROR': None}[status], 'PROCEDURE_VERDICT_DISAGREEMENT')
    if status == 'PASS':
        require(counts == [len(cases), 0, 0] and result.get('exit_code') == 0 and not result['timed_out'], 'FALSE_PROCEDURE_PASS')
    elif status == 'FAIL':
        require(counts[1] > 0 and result.get('exit_code') == 1 and not result['timed_out'], 'UNVERIFIED_PROCEDURE_FAIL')
    elapsed = result.get('elapsed_seconds')
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0, 'PROCEDURE_ELAPSED_INVALID')
    matches = [h for h in history if h['step_no'] == event['step_no']]
    require(len(matches) == 1 and matches[0]['tool'] == 'run_command' and matches[0]['status'] == 'success' and
            matches[0]['request_payload'] == {'tool': 'run_command', 'arguments': request} and
            matches[0]['result_payload'] == result, 'PROCEDURE_NOT_IN_ACTUAL_TRACE')
    return {'step_no': event['step_no'], 'method': method, 'procedure_id': procedure_id,
            'candidate_sha256': result['candidate_sha256'], 'cases_sha256': result['cases_sha256'],
            'status': status, 'failure_kind': result.get('failure_kind'),
            'event_sha256': digest(event), 'case_count': len(cases)}


def validate_capture(capture, scope):
    task, history = capture['task_public'], capture['history']
    phase = capture['phase']
    require(phase in ('DISCOVERY', 'VERIFICATION'), 'EVALUATION_CAPTURE_FORBIDDEN')
    scope_task(scope, task, phase)
    graph = ShortTermWorkingGraph.from_snapshot(capture['graph'])
    require(graph.task_id == task['task_id'] and graph.repository == base.REPOSITORY and
            graph.objective == base.public_task_instruction(task).strip(), 'GRAPH_SCOPE_CHANGED')
    base._reject_private_fields(history)
    project_subgoal_context(graph, history)
    steps = [h['step_no'] for h in history]
    require(len(history) <= 24 and all(type(n) is int and n > 0 for n in steps) and steps == sorted(set(steps)), 'TRACE_ORDER_INVALID')
    require(all(h['tool'] in ('run_public_tests', 'revise_subtask_dag', 'complete_subtask', 'run_command') for h in history), 'UNSUPPORTED_PUBLIC_OPERATION')
    public = base._observations(task, history)
    events = capture['procedure_events']
    require(isinstance(events, list) and len(events) <= 4, 'PROCEDURE_EVENT_BUDGET')
    observations = [procedure_observation(task, e, history) for e in events]
    require([e['step_no'] for e in observations] == sorted({e['step_no'] for e in observations}), 'PROCEDURE_EVENT_ORDER')
    require({h['step_no'] for h in history if h['tool'] == 'run_command'} == {e['step_no'] for e in observations}, 'UNACCOUNTED_PROCEDURE_OPERATION')
    if phase == 'VERIFICATION':
        require(all(e['procedure_id'] in (None, capture.get('selected_procedure_id')) for e in observations),
                'PROCEDURE_NOT_PREASSIGNED')
    require(len(public) + len(events) <= 4, 'SHARED_EXECUTION_BUDGET_EXCEEDED')
    code = capture['final_code']
    require(isinstance(code, str) and len(code.encode()) <= 65536, 'FINAL_CODE_INVALID')
    lesson = capture.get('source_lesson')
    if lesson is not None:
        base._lesson(lesson, history)
    require(type(capture['finished']) is bool and (not capture['finished'] or lesson is not None), 'SUBMISSION_LESSON_MISSING')
    final_sha = sha(code.encode())
    public_green = [r for r in public if r['result']['status'] == 'PASS' and r['candidate_sha256'] == final_sha]
    return observations, public_green


def candidate_from(capture, scope):
    observations, public_green = validate_capture(capture, scope)
    if capture['phase'] != 'DISCOVERY' or not capture['finished'] or not public_green or not capture.get('source_lesson'):
        return []
    lesson = capture['source_lesson']
    anchors = set(lesson['trace_steps'])
    final_sha = sha(capture['final_code'].encode())
    candidates = []
    for green in observations:
        if green['status'] != 'PASS' or green['candidate_sha256'] != final_sha or green['step_no'] not in anchors:
            continue
        final_checks = [p for p in public_green if p['step_no'] > green['step_no']]
        if not final_checks:
            continue
        for red in observations:
            if not (red['status'] == 'FAIL' and red['failure_kind'] == 'WRONG_ANSWER' and
                    red['step_no'] < green['step_no'] and red['step_no'] in anchors and
                    red['method'] == green['method'] and red['cases_sha256'] == green['cases_sha256'] and
                    red['candidate_sha256'] != green['candidate_sha256']):
                continue
            # Full original lesson remains evidence. Its prose is not certified.
            text = {'method': green['method'], 'model_procedure': lesson['procedure'],
                    'model_applicability': lesson['applicability']}
            identity = 'personal-procedure:' + digest(text)
            candidates.append({'procedure_id': identity, **text, 'owner_user_id': scope['owner_user_id'],
                'normalized_actions': ['RUN_GENERATED_CASES(method,candidate,cases)', 'RUN_ORIGINAL_PUBLIC_EXAMPLES(final_candidate)'],
                'verification_claim': CLAIM, 'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS',
                'prose_status': 'MODEL_AUTHORED_NOT_SEMANTICALLY_VERIFIED',
                'source_task_id': capture['task_public']['task_id'], 'source_family_id': capture['task_public']['family_id'],
                'source_lesson_sha256': digest(lesson), 'capture_sha256': digest(capture),
                'red_step': red['step_no'], 'green_step': green['step_no'],
                'public_green_step': final_checks[-1]['step_no'], 'status': 'PROVISIONAL_NOT_PROMOTED'})
            break
    return list({r['procedure_id']: r for r in candidates}.values())


def verification_support(capture, scope, candidates):
    observations, public_green = validate_capture(capture, scope)
    if capture['phase'] != 'VERIFICATION' or not capture['finished'] or not public_green:
        return []
    final_sha = sha(capture['final_code'].encode())
    result = []
    for event in observations:
        identity = event['procedure_id']
        if identity is None:
            continue
        require(identity in candidates, 'DECLARED_PROCEDURE_UNKNOWN')
        candidate = candidates[identity]
        require(candidate['source_task_id'] != capture['task_public']['task_id'] and
                candidate['source_family_id'] != capture['task_public']['family_id'], 'PROCEDURE_SELF_VERIFICATION')
        final_checks = [p for p in public_green if p['step_no'] > event['step_no']]
        if event['method'] == candidate['method'] and event['status'] == 'PASS' and event['candidate_sha256'] == final_sha and final_checks:
            result.append({'procedure_id': identity, 'task_id': capture['task_public']['task_id'],
                'family_id': capture['task_public']['family_id'], 'phase': 'VERIFICATION',
                'capture_sha256': digest(capture), 'generated_green_step': event['step_no'],
                'public_green_step': final_checks[-1]['step_no'],
                'verification_sha256': digest({'capture': digest(capture), 'event': event, 'public': final_checks[-1]['event_sha256']}),
                'verification_claim': CLAIM, 'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS'})
    return list({r['procedure_id']: r for r in result}.values())


def native_sources(state_path, solve_reference):
    state_path = Path(state_path).resolve()
    cell = state_path.parent
    solve = read(checked(solve_reference))
    require(Path(solve_reference['path']).resolve() == cell / 'solve-receipt.json' and
            solve.get('state_sha256') == ref(state_path)['sha256'], 'SOLVE_STATE_BINDING_CHANGED')
    state = read(state_path)
    require(solve.get('task_id') == state['task']['task_id'] and solve.get('arm') == state['arm'] and
            solve.get('candidate_sha256') == sha(state.get('candidate', '').encode()), 'SOLVE_IDENTITY_CHANGED')
    require(solve.get('status') in ('SUBMITTED', 'GENERATION_ERROR'), 'NONTERMINAL_ATTEMPT')
    require(bool(state.get('finished')) == (solve['status'] == 'SUBMITTED'), 'SUBMISSION_STATE_DIFFERS')
    refs = [ref(state_path), solve_reference]
    threads, calls = [], []
    for index, session in enumerate(solve.get('sessions', []), 1):
        folder = cell / ('session-%02d' % index)
        require(session.get('session') == index and read(folder / 'receipt.json') == session, 'SESSION_RECEIPT_CHANGED')
        for name, key in (('events.jsonl', 'events_sha256'), ('stderr.log', 'stderr_sha256')):
            reference = ref(folder / name)
            require(reference['sha256'] == session[key], 'NATIVE_OUTPUT_CHANGED')
            refs.append(reference)
        refs.append(ref(folder / 'receipt.json'))
        observed_threads = []
        for raw in (folder / 'events.jsonl').read_bytes().splitlines():
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get('type') == 'thread.started':
                identity = event.get('thread_id')
                require(isinstance(identity, str) and bool(identity), 'NATIVE_CONTRIBUTOR_MISSING')
                if identity not in observed_threads:
                    observed_threads.append(identity)
            item = event.get('item', {})
            if event.get('type') != 'item.completed' or (item.get('type'), item.get('server'), item.get('tool')) != ('mcp_tool_call', 'benchmark', 'action'):
                continue
            envelope = item.get('arguments')
            if isinstance(envelope, str):
                envelope = json.loads(envelope)
            request = envelope.get('request') if isinstance(envelope, dict) else None
            for block in (item.get('result') or {}).get('content', []):
                if block.get('type') != 'text':
                    continue
                try:
                    response = json.loads(block['text'])
                except (ValueError, UnicodeError):
                    continue
                if isinstance(response, dict) and type(response.get('step_no')) is int:
                    calls.append((request, response))
        require(observed_threads and session.get('thread_ids') == observed_threads,
                'NATIVE_CONTRIBUTOR_NOT_CORROBORATED')
        threads.extend(observed_threads)
    require(threads and all(isinstance(t, str) and t for t in threads), 'NATIVE_CONTRIBUTOR_MISSING')
    for row in state['history']:
        matches = [(req, res) for req, res in calls if res['step_no'] == row['step_no']]
        require(len(matches) == 1 and matches[0][0] == row['request_payload'] and
                matches[0][1].get('result') == row['result_payload'] and matches[0][1].get('status') == row['status'], 'TRACE_NOT_CORROBORATED_BY_NATIVE')
    supported = {'revise_subtask_dag', 'run_public_tests', 'run_command', 'complete_subtask'}
    actual_steps = [response['step_no'] for request, response in calls
                    if isinstance(request, dict) and request.get('tool') in supported
                    and response.get('status') == 'success']
    require(len(actual_steps) == len(set(actual_steps)) and
            sorted(actual_steps) == sorted(row['step_no'] for row in state['history']),
            'NATIVE_SUCCESSFUL_CALL_OMITTED_FROM_TRACE')
    if state.get('finished'):
        finishes = [(req, res) for req, res in calls if isinstance(req, dict) and req.get('tool') == 'finish'
                    and res.get('status') == 'success' and res.get('result', {}).get('submitted') is True]
        require(len(finishes) == 1 and finishes[0][0].get('arguments') == {
            'code': state['candidate'], 'source_lesson': state['source_lesson']} and
            finishes[0][1]['result'].get('candidate_sha256') == solve['candidate_sha256'], 'REFLECTION_NOT_NATIVE_SUBMISSION')
    return state, solve, refs, threads


def episode_view(capture, scope):
    observations, green = validate_capture(capture, scope)
    lesson = capture.get('source_lesson')
    succeeded = bool(capture['finished'] and green)
    if lesson is not None:
        summary = {**lesson, 'provenance': 'MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS',
                   'verification_scope': 'PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER'}
        subgoal = lesson['applicability']
    else:
        summary = {'provenance': 'MECHANICAL_TERMINAL_ATTEMPT_OBSERVATION',
                   'terminal_reason': capture['terminal_reason'], 'submitted': False,
                   'public_history_steps': [h['step_no'] for h in capture['history']],
                   'correction_verified': False, 'source_task_only_trace_ids': True}
        subgoal = 'Unsuccessful public programming attempt and verification workflow'
    return {'episode_id': 'personal-episode:' + digest(capture), 'owner_user_id': scope['owner_user_id'],
            'task_id': capture['task_public']['task_id'], 'family_id': capture['task_public']['family_id'],
            'phase': capture['phase'], 'subgoal': subgoal, 'summary': summary, 'succeeded': succeeded,
            'source_revision': 'sha256:' + sha(capture['final_code'].encode()), 'created_at': capture['created_at']}


def materialize(scope, captures):
    episodes, facts, relations, candidates, supports = [], [], [], {}, []
    for capture in captures:
        episodes.append(episode_view(capture, scope))
        nodes, edges = (base._ast_facts(capture['final_code'], capture['task_public']['task_id'])
                        if capture['final_code'].strip() else ([], []))
        node_ids = {key: 'personal-knowledge:' + digest([digest(capture), key]) for key, _ in nodes}
        for key, payload in nodes:
            facts.append({'knowledge_id': node_ids[key],
                          'payload': payload, 'family_id': capture['task_public']['family_id'],
                          'source_capture_sha256': digest(capture)})
        relations.extend({'source': node_ids[source], 'target': node_ids[target], 'relation': relation}
                         for source, target, relation in edges)
        for candidate in candidate_from(capture, scope):
            # Same proposed text/method may recur; keep a deterministic source.
            identity = candidate['procedure_id']
            if identity not in candidates or candidate['source_task_id'] < candidates[identity]['source_task_id']:
                candidates[identity] = candidate
    for capture in captures:
        supports.extend(verification_support(capture, scope, candidates))
    skills = []
    for identity, candidate in sorted(candidates.items()):
        independent = [s for s in supports if s['procedure_id'] == identity]
        if not independent:
            continue
        skills.append({**candidate, 'status': 'PRIVATE_VERIFIED_TESTING_WORKFLOW',
                       'support_task_ids': sorted({candidate['source_task_id'], *(s['task_id'] for s in independent)}),
                       'support_count': 1 + len({s['task_id'] for s in independent}),
                       'owner_count': 1, 'sharing_scope': 'PRIVATE_OWNER_ONLY',
                       'organisation_gate_b_satisfied': False, 'verification_support': independent})
    return {'episodes': episodes, 'facts': facts, 'relations': relations, 'candidates': candidates, 'skills': skills}


def layer_counts(data):
    return {'L1_episodes': len(data['episodes']), 'L1_failed': sum(not e['succeeded'] for e in data['episodes']),
            'L2_nodes': len(data['facts']), 'L2_edges': len(data['relations']), 'L3_candidates': len(data['candidates']),
            'L3_personal_skills': len(data['skills']), 'L3_organisation_skills': 0,
            'captured_training_tasks': len(data['episodes'])}


def _captures(root, scope):
    rows, refs, identities = [], [], set()
    for path in sorted((Path(root) / 'captures').glob('*.json')):
        record = read(path)
        require(record['scope_reference'] == ref(Path(root) / 'scope.json'), 'CAPTURE_SCOPE_CHANGED')
        checked(record['adapter_reference'])
        capture = record['capture']
        require(record['capture_sha256'] == digest(capture), 'CAPTURE_HASH_CHANGED')
        validate_capture(capture, scope)
        identity = capture['task_public']['task_id']
        require(identity not in identities, 'DUPLICATE_CAPTURE_TASK')
        identities.add(identity)
        for reference in record['source_references']:
            checked(reference)
        rows.append(capture); refs.append(ref(path))
    return rows, refs


def ingest_cell(root, *, phase, state_path, solve_reference, task_authority=None):
    require(phase in ('DISCOVERY', 'VERIFICATION'), 'EVALUATION_CAPTURE_FORBIDDEN')
    state, solve, sources, threads = native_sources(state_path, solve_reference)
    if task_authority is not None:
        require(task_authority == {'task_id': state['task']['task_id'], 'phase': phase}, 'TASK_AUTHORITY_CHANGED')
    capture = {'schema': SCHEMA, 'phase': phase, 'task_public': state['task'], 'history': state['history'],
               'graph': state['graph'], 'procedure_events': state.get('procedure_events', []),
               'final_code': state.get('candidate', ''), 'source_lesson': state.get('source_lesson'),
               'finished': bool(state.get('finished')), 'terminal_reason': solve.get('error_type'),
               'contributor_ids': threads, 'model_id': state['runtime']['native']['model'],
               'created_at': state['started_at'], 'selected_procedure_id': state.get('selected_procedure_id')}
    with lock(root) as root:
        scope = read(root / 'scope.json')
        require(state.get('phase') == phase and state.get('owner_user_id') == scope['owner_user_id'] and
                state.get('org_id') == scope['org_id'], 'CELL_PRIVATE_SCOPE_CHANGED')
        validate_capture(capture, scope)
        existing, _ = _captures(root, scope)
        other = [c for c in existing if c['task_public']['task_id'] != state['task']['task_id']]
        derived = materialize(scope, [*other, capture])
        value = {'schema': SCHEMA, 'capture': capture, 'capture_sha256': digest(capture),
                 'source_references': sources, 'scope_reference': ref(root / 'scope.json'),
                 'adapter_reference': ref(__file__)}
        path = root / 'captures' / (sha(state['task']['task_id'].encode()) + '.json')
        write_new(path, value)
        for reference in sources:
            checked(reference)
        return {'schema': SCHEMA, 'status': 'CAPTURED', 'task_id': state['task']['task_id'], 'phase': phase,
                'capture_reference': ref(path), 'succeeded': episode_view(capture, scope)['succeeded'],
                'candidate_count': len(derived['candidates']), 'promoted_private_skills': len(derived['skills']),
                'claim': CLAIM, 'organisation_gate_b_changed': False}


def freeze(root, output, *, stage='FINAL'):
    require(stage in ('PROVISIONAL', 'FINAL'), 'UNKNOWN_FREEZE_STAGE')
    output = Path(output).resolve()
    with lock(root) as root:
        scope = read(root / 'scope.json')
        captures, references = _captures(root, scope)
        expected = set(scope['phases']['DISCOVERY'])
        if stage == 'FINAL':
            expected.update(scope['phases']['VERIFICATION'])
        selected = [(capture, reference) for capture, reference in zip(captures, references)
                    if capture['task_public']['task_id'] in expected]
        captures, references = [c for c, _ in selected], [r for _, r in selected]
        actual = {c['task_public']['task_id'] for c in captures}
        require(actual == expected, 'TRAINING_COVERAGE_INCOMPLETE')
        data = materialize(scope, captures)
        counts = layer_counts(data)
        status = 'PROVISIONAL' if stage == 'PROVISIONAL' else ('READY' if data['skills'] else 'NOT_READY')
        manifest = {'schema': SCHEMA, 'stage': stage, 'status': status, 'scope': scope,
                    'scope_reference': ref(root / 'scope.json'), 'source_capture_references': references,
                    'adapter_reference': ref(__file__), 'layer_counts': counts, 'data': data,
                    'private_owner_only': True, 'evaluation_writes': False, 'claim': CLAIM,
                    'source_revisions_retagged': False, 'organisation_gate_b_changed': False}
        write_new(output, manifest)
        return {**ref(output), 'status': status, 'layer_counts': counts}


def _tokens(value):
    return set(re.findall(r'[a-z][a-z0-9_]{1,}', value.lower()))


class PersonalFrozenBank:
    def __init__(self, path, expected_sha256):
        self.path = Path(path).resolve()
        self.reference = ref(self.path)
        require(self.reference['sha256'] == expected_sha256, 'FROZEN_BANK_CHANGED')
        self.manifest = read(self.path)
        require(self.manifest.get('schema') == SCHEMA and self.manifest.get('private_owner_only') is True and
                self.manifest.get('evaluation_writes') is False and self.manifest.get('organisation_gate_b_changed') is False,
                'FROZEN_BANK_POLICY_CHANGED')
        require(self.manifest.get('stage') in ('PROVISIONAL', 'FINAL'), 'FROZEN_STAGE_CHANGED')
        scope_path = checked(self.manifest['scope_reference']); checked(self.manifest['adapter_reference'])
        require(read(scope_path) == self.manifest['scope'], 'FROZEN_SCOPE_CHANGED')
        captures = []
        for reference in self.manifest['source_capture_references']:
            record = read(checked(reference))
            require(record['scope_reference'] == self.manifest['scope_reference'], 'CAPTURE_SCOPE_CHANGED')
            checked(record['adapter_reference'])
            require(record['capture_sha256'] == digest(record['capture']), 'CAPTURE_HASH_CHANGED')
            for source in record['source_references']:
                checked(source)
            captures.append(record['capture'])
        expected = set(self.manifest['scope']['phases']['DISCOVERY'])
        if self.manifest['stage'] == 'FINAL':
            expected.update(self.manifest['scope']['phases']['VERIFICATION'])
        require({c['task_public']['task_id'] for c in captures} == expected and len(captures) == len(expected), 'FROZEN_COVERAGE_CHANGED')
        require(materialize(self.manifest['scope'], captures) == self.manifest['data'], 'FROZEN_DERIVATION_CHANGED')
        require(layer_counts(self.manifest['data']) == self.manifest['layer_counts'], 'FROZEN_COUNTS_CHANGED')
        status = ('PROVISIONAL' if self.manifest['stage'] == 'PROVISIONAL' else
                  ('READY' if self.manifest['data']['skills'] else 'NOT_READY'))
        require(self.manifest.get('status') == status, 'FROZEN_READINESS_CHANGED')

    def candidate_ids(self):
        return sorted(self.manifest['data']['candidates'])

    def candidate_view(self, identity):
        candidate = self.manifest['data']['candidates'][identity]
        return {k: deepcopy(candidate[k]) for k in ('procedure_id', 'method', 'model_procedure',
                'model_applicability', 'normalized_actions', 'verification_claim', 'oracle_scope', 'prose_status', 'status')}

    def recall(self, task_public, graph, *, phase, owner_user_id=None, enabled_layers=('L3', 'L2', 'L1'),
               procedure_id=None, checkpoint=None):
        checked(self.reference)
        scope = self.manifest['scope']
        require(owner_user_id in (None, scope['owner_user_id']), 'WRONG_PRIVATE_OWNER')
        require(phase in ('VERIFICATION', 'VALID', 'TEST'), 'DISCOVERY_RETRIEVAL_FORBIDDEN')
        scope_task(scope, task_public, phase)
        require(graph.task_id == task_public['task_id'] and graph.repository == base.REPOSITORY and graph.active_node is not None, 'RECALL_GRAPH_MISMATCH')
        require(set(enabled_layers) <= {'L1', 'L2', 'L3'} and len(enabled_layers) == len(set(enabled_layers)), 'INVALID_ENABLED_LAYERS')
        binding = {'bank_sha256': self.reference['sha256'], 'task_id': task_public['task_id'],
                   'phase': phase, 'owner_user_id': scope['owner_user_id'], 'enabled_layers': list(enabled_layers)}
        prior = deepcopy(checkpoint) if checkpoint is not None else {'binding': binding, 'nodes': [], 'memory_ids': [], 'bytes': 0}
        require(prior['binding'] == binding, 'RECALL_CHECKPOINT_CHANGED')
        node = graph.active_node
        if node.node_id in prior['nodes']:
            return {'injections': [], 'checkpoint': prior, 'decisions': [{'decision': 'RESUME'}]}
        query = _tokens(' '.join((node.objective, node.operation, *node.symbols, *node.apis)))
        data = self.manifest['data']
        choices, decisions = [], []
        if phase == 'VERIFICATION':
            require(self.manifest['stage'] == 'PROVISIONAL', 'VERIFICATION_REQUIRES_PROVISIONAL_BANK')
            if procedure_id is not None:
                require(procedure_id in data['candidates'], 'UNKNOWN_PROVISIONAL_PROCEDURE')
                c = data['candidates'][procedure_id]
                require(c['source_family_id'] != task_public['family_id'], 'SOURCE_FAMILY_LEAKAGE')
                choices.append(('PERSONAL_PROCEDURE_CANDIDATE', procedure_id, self.candidate_view(procedure_id)))
        else:
            require(self.manifest['stage'] == 'FINAL' and self.manifest['status'] == 'READY', 'PERSONAL_BANK_NOT_READY')
            require(procedure_id is None, 'EVALUATION_CANNOT_FORCE_PROCEDURE')
        for layer in ('L3', 'L2', 'L1'):
            if choices or layer not in enabled_layers:
                continue
            ranked = []
            if layer == 'L3' and phase != 'VERIFICATION':
                for skill in data['skills']:
                    words = _tokens(skill['method'] + ' ' + skill['model_applicability'] + ' ' + ' '.join(skill['model_procedure']))
                    score = len(query & words) / max(1, len(query | words))
                    if score >= .05:
                        view = {**self.candidate_view(skill['procedure_id']), 'status': skill['status'],
                                'support_count': skill['support_count'], 'sharing_scope': 'PRIVATE_OWNER_ONLY'}
                        ranked.append((score, skill['procedure_id'], view, 'SKILL'))
            elif layer == 'L2':
                revision = 'sha256:' + sha(task_public['starter_code'].encode())
                for fact in data['facts']:
                    if fact['payload']['source_revision'] != revision:
                        continue
                    words = _tokens(fact['payload']['name'])
                    score = len(query & words) / max(1, len(query | words))
                    if score >= .05:
                        ranked.append((score, fact['knowledge_id'], fact['payload'], 'REPOSITORY_SEMANTIC'))
            elif layer == 'L1':
                for episode in data['episodes']:
                    if episode['task_id'] == task_public['task_id'] or episode['family_id'] == task_public['family_id']:
                        continue
                    words = _tokens(episode['subgoal'] + ' ' + json.dumps(episode['summary'], ensure_ascii=False))
                    score = len(query & words) / max(1, len(query | words))
                    if score >= .05:
                        view = {k: episode[k] for k in ('subgoal', 'summary', 'succeeded', 'source_revision')}
                        ranked.append((score, episode['episode_id'], view, 'EPISODIC'))
            ranked.sort(key=lambda item: (-item[0], item[1]))
            decisions.append({'layer': layer, 'eligible_count': len(ranked)})
            for _, identity, view, kind in ranked:
                if identity not in prior['memory_ids']:
                    choices.append((kind, identity, view)); break
        injections = []
        for kind, identity, view in choices[:1]:
            text = canonical(view).decode().rstrip('\n')
            raw = text.encode()
            if identity not in prior['memory_ids'] and len(prior['memory_ids']) < 3 and prior['bytes'] + len(raw) <= 12000:
                injections.append({'kind': kind, 'memory_id': identity, 'active_node_id': node.node_id,
                                   'exact_text': text, 'byte_count': len(raw), 'sha256': sha(raw),
                                   **({'procedure_id': view['procedure_id']} if 'procedure_id' in view else {})})
                prior['memory_ids'].append(identity); prior['bytes'] += len(raw)
        prior['nodes'].append(node.node_id)
        return {'injections': injections, 'checkpoint': prior, 'decisions': decisions}

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_bank(path, sha256):
    return PersonalFrozenBank(path, sha256)
