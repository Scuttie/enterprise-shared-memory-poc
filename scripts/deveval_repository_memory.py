"""Private repository experiences and observed generated-test workflows.

The oracle is model-authored. Promotion certifies a recorded execution pattern,
not the correctness of the prose, tests, or target implementation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'deveval-private-memory/1'
CLAIM = 'OBSERVED_MODEL_GENERATED_TEST_WORKFLOW'
METHODS = ('boundary_cases', 'invariant_checks', 'differential_cases')


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def reference(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def checked(ref):
    if reference(ref['path']) != ref:
        raise ValueError('REFERENCED_BYTES_CHANGED')
    return Path(ref['path'])


def write_new(path, value):
    path = Path(path)
    data = canonical(value)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('IMMUTABLE_BYTES_CHANGED')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def require(value, code):
    if not value:
        raise ValueError(code)


def capture(cell, *, phase, owner, project, task_id):
    """Validate actual native calls before allowing their reflections into a bank."""
    cell = Path(cell).resolve()
    state_ref, solve_ref = reference(cell / 'state.json'), reference(cell / 'solve-receipt.json')
    state, solve = read(state_ref['path']), read(solve_ref['path'])
    require(phase in ('DISCOVERY', 'VERIFICATION'), 'EVALUATION_CAPTURE_FORBIDDEN')
    require(state['phase'] == phase and state['owner'] == owner and state['task']['project'] == project
            and state['task']['task_id'] == task_id, 'CAPTURE_SCOPE_CHANGED')
    require(solve['state_sha256'] == state_ref['sha256'] and solve['task_id'] == task_id
            and solve['arm'] == state['arm'], 'SOLVE_STATE_CHANGED')
    final_sha = hashlib.sha256(state['candidate'].encode()).hexdigest()
    require(solve['candidate_sha256'] == final_sha, 'FINAL_CANDIDATE_CHANGED')
    require(solve['status'] in ('SUBMITTED', 'GENERATION_ERROR'), 'NONTERMINAL_SOLVE')
    # A process error after submission cannot contribute promotion evidence.
    accepted = solve['status'] == 'SUBMITTED' and state['finished']
    refs, calls, threads = [state_ref, solve_ref], [], []
    for number, receipt in enumerate(solve['sessions'], 1):
        directory = cell / ('session-%02d' % number)
        require(read(directory / 'receipt.json') == receipt, 'SESSION_RECEIPT_CHANGED')
        for name, key in (('events.jsonl', 'events_sha256'), ('stderr.log', 'stderr_sha256')):
            ref = reference(directory / name)
            require(ref['sha256'] == receipt[key], 'SESSION_OUTPUT_CHANGED')
            refs.append(ref)
        refs.append(reference(directory / 'receipt.json'))
        prompt_receipt = read(directory / 'prompt-receipt.json')
        require(prompt_receipt['prompt_sha256'] == reference(directory / 'prompt.txt')['sha256']
                and prompt_receipt['state_before_call_sha256'] == reference(directory / 'initial-state.json')['sha256'], 'PROMPT_STATE_CHANGED')
        initial = read(directory / 'initial-state.json')
        require(initial['task'] == state['task'] and initial['phase'] == phase and initial['owner'] == owner
                and initial.get('selected_procedure_id') == state.get('selected_procedure_id')
                and initial.get('bank') == state.get('bank'), 'PRECALL_SCOPE_CHANGED')
        refs += [reference(directory / name) for name in ('prompt-receipt.json', 'prompt.txt', 'initial-state.json')]
        observed_threads = []
        vllm = receipt.get('provider') == 'vllm'
        response_ids = []
        if vllm:
            require(solve.get('provider') == 'vllm' and receipt['thread_ids'] == [], 'VLLM_NATIVE_IDENTITY_FORBIDDEN')
            for http_folder in sorted(directory.glob('http-*')):
                http_receipt = read(http_folder / 'receipt.json')
                refs.append(reference(http_folder / 'receipt.json'))
                for field in ('request_reference', 'response_reference'):
                    if field in http_receipt:
                        checked(http_receipt[field])
                        refs.append(http_receipt[field])
                if http_receipt.get('status') == 'RECEIVED' and isinstance(http_receipt.get('response_id'), str):
                    response_ids.append(http_receipt['response_id'])
            require(receipt.get('response_ids') == response_ids, 'HTTP_RESPONSE_IDENTITIES_CHANGED')
        for raw in (directory / 'events.jsonl').read_bytes().splitlines():
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get('type') == 'gateway.action.completed':
                require(vllm and event.get('provider') == 'vllm' and event.get('session') == number, 'HTTP_EXCHANGE_SCOPE_CHANGED')
                http_receipt = read(checked(event['http_receipt_reference']))
                require(event['http_request_reference'] == http_receipt['request_reference']
                        and event['http_response_reference'] == http_receipt['response_reference']
                        and http_receipt['status'] == 'RECEIVED', 'HTTP_EXCHANGE_BINDING_CHANGED')
                request_body = read(checked(event['http_request_reference']))
                response_body = read(checked(event['http_response_reference']))
                require(request_body['model'] == state['runtime']['gateway']['model'] and len(response_body['choices']) == 1
                        and event.get('response_id') == response_body.get('id') == http_receipt.get('response_id'), 'HTTP_MODEL_RESPONSE_CHANGED')
                message = response_body['choices'][0]['message']
                require(not message.get('tool_calls') and isinstance(message.get('content'), str), 'HTTP_CONTENT_CHANGED')
                try:
                    parsed = json.loads(message['content'])
                    valid = isinstance(parsed, dict) and set(parsed) == {'tool', 'arguments'} and isinstance(parsed['tool'], str) and isinstance(parsed['arguments'], dict)
                except (ValueError, TypeError):
                    parsed, valid = None, False
                require((valid and event.get('action_parse_error') is None and event['request'] == parsed)
                        or (not valid and event.get('action_parse_error') == 'INVALID_MODEL_ACTION' and event['request'] == {}), 'ACTION_NOT_FROM_HTTP_RESPONSE')
                require(event['request_sha256'] == digest(event['request']) and event['response_sha256'] == digest(event['response']), 'HTTP_ACTION_HASH_CHANGED')
                calls.append((event['request'], event['response']))
                refs += [event[field] for field in ('http_request_reference', 'http_response_reference', 'http_receipt_reference')]
                continue
            if event.get('type') == 'thread.started':
                require(not vllm, 'MIXED_PROVIDER_PROVENANCE')
                identity = event.get('thread_id')
                require(isinstance(identity, str) and identity, 'INVALID_NATIVE_THREAD')
                if identity not in observed_threads:
                    observed_threads.append(identity)
            item = event.get('item', {})
            if event.get('type') != 'item.completed' or (item.get('type'), item.get('server'), item.get('tool')) != ('mcp_tool_call', 'benchmark', 'action'):
                continue
            require(not vllm, 'MIXED_PROVIDER_PROVENANCE')
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
        require(observed_threads == receipt['thread_ids'], 'THREAD_NOT_CORROBORATED')
        if accepted and not vllm:
            require(observed_threads, 'NATIVE_THREAD_MISSING')
        threads.extend(observed_threads)
    expected = [(request, response) for request, response in calls if isinstance(request, dict)
                and request.get('tool') != 'finish' and response.get('status') == 'success']
    actual_steps = [response['step_no'] for _, response in expected]
    require(len(actual_steps) == len(set(actual_steps)) and sorted(actual_steps) == sorted(h['step_no'] for h in state['history']), 'TRACE_BIJECTION_CHANGED')
    for row in state['history']:
        matches = [(req, res) for req, res in expected if res['step_no'] == row['step_no']]
        require(len(matches) == 1 and matches[0][0] == row['request_payload']
                and matches[0][1]['result'] == row['result_payload'], 'TRACE_PAYLOAD_CHANGED')
    if state['finished']:
        finishes = [(req, res) for req, res in calls if isinstance(req, dict) and req.get('tool') == 'finish'
                    and res.get('status') == 'success' and res.get('result', {}).get('submitted') is True]
        require(len(finishes) == 1 and finishes[0][0]['arguments'] == {'code': state['candidate'], 'source_lesson': state['source_lesson']}
                and finishes[0][1]['result']['candidate_sha256'] == final_sha, 'FINISH_NOT_CORROBORATED')
    observations = []
    for row in state['history']:
        if row['tool'] != 'run_command':
            continue
        args, result = row['request_payload']['arguments'], row['result_payload']
        execution = cell / 'generated-tests' / ('step-%03d' % row['step_no'])
        require(read(execution / 'receipt.json') == result, 'EXECUTION_RECEIPT_CHANGED')
        refs.append(reference(execution / 'receipt.json'))
        for name in ('request.json', 'generated_test.py', 'child-request.json', 'child-receipt.json',
                     'stdout.log', 'stderr.log', 'transport.stdout.log', 'transport.stderr.log'):
            if (execution / name).exists():
                refs.append(reference(execution / name))
        require(result['task_id'] == task_id and result['candidate_sha256'] == hashlib.sha256(args['code'].encode()).hexdigest()
                and result['test_sha256'] == hashlib.sha256(args['test_code'].encode()).hexdigest()
                and result['method'] == args['method'] and result.get('procedure_id') == args.get('procedure_id')
                and result['oracle_scope'] == 'MODEL_GENERATED_EXPECTATIONS', 'GENERATED_RESULT_CHANGED')
        require(result['method'] in METHODS, 'UNKNOWN_TEST_METHOD')
        require(result['status'] in ('PASS', 'FAIL', 'INFRA_ERROR') and type(result['timed_out']) is bool
                and type(result['assertions_executed']) is int and result['assertions_executed'] >= 0
                and type(result['candidate_executed']) is bool and type(result['candidate_file_unchanged']) is bool,
                'GENERATED_OUTCOME_INVALID')
        if result['status'] == 'PASS':
            require(result['exit_code'] == 0 and not result['timed_out'] and result['assertions_executed'] >= 2
                    and result['candidate_executed'] and result['candidate_file_unchanged'], 'FALSE_GENERATED_PASS')
        if result['status'] == 'FAIL' and result['failure_kind'] == 'ASSERTION':
            require(result['exit_code'] == 1 and not result['timed_out'] and result['assertions_executed'] >= 1
                    and result['candidate_executed'] and result['candidate_file_unchanged'], 'FALSE_ASSERTION_FAILURE')
        observations.append({'step_no': row['step_no'], **{key: result.get(key) for key in (
            'candidate_sha256', 'test_sha256', 'method', 'procedure_id', 'status', 'failure_kind', 'assertions_executed')}})
    lesson = state.get('source_lesson')
    if lesson is not None:
        require(set(lesson) == {'summary', 'applicability', 'procedure', 'trace_steps'}, 'LESSON_FIELDS_CHANGED')
        require(set(lesson['trace_steps']) <= {row['step_no'] for row in state['history']}, 'LESSON_TRACE_UNKNOWN')
    return {'phase': phase, 'owner': owner, 'project': project, 'task_id': task_id,
            'completion_path': state['task']['completion_path'], 'accepted': bool(accepted),
            'selected_procedure_id': state.get('selected_procedure_id'), 'final_candidate_sha256': final_sha,
            'lesson': lesson, 'observations': observations, 'references': refs, 'threads': threads}


def derive(captures, owner):
    episodes, candidates, support = [], {}, {}
    tasks = [c['task_id'] for c in captures]
    require(len(tasks) == len(set(tasks)), 'DUPLICATE_CAPTURE')
    for item in captures:
        require(item['owner'] == owner and item['phase'] in ('DISCOVERY', 'VERIFICATION'), 'CAPTURE_SCOPE_CHANGED')
        lesson = item['lesson']
        if lesson:
            episodes.append({'layer': 'L1', 'memory_id': 'episode:' + digest(item), 'project': item['project'],
                'source_task_id': item['task_id'], 'completion_path': item['completion_path'],
                'content': lesson, 'claim': 'MODEL_AUTHORED_REFLECTION', 'capture_sha256': digest(item)})
        if item['phase'] != 'DISCOVERY' or not item['accepted'] or not lesson:
            continue
        anchors = set(lesson['trace_steps'])
        for green in item['observations']:
            if green['status'] != 'PASS' or green['candidate_sha256'] != item['final_candidate_sha256'] or green['step_no'] not in anchors:
                continue
            for red in item['observations']:
                if not (red['status'] == 'FAIL' and red['failure_kind'] == 'ASSERTION'
                        and red['step_no'] < green['step_no'] and red['step_no'] in anchors
                        and red['method'] == green['method'] and red['test_sha256'] == green['test_sha256']
                        and red['candidate_sha256'] != green['candidate_sha256']):
                    continue
                content = {'method': green['method'], 'applicability': lesson['applicability'], 'procedure': lesson['procedure']}
                identity = 'repo-procedure:' + digest({'project': item['project'], 'content': content})
                candidates[identity] = {'layer': 'L3', 'memory_id': identity, 'procedure_id': identity,
                    'project': item['project'], 'source_task_id': item['task_id'], 'completion_path': item['completion_path'],
                    'content': content, 'claim': CLAIM, 'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS',
                    'prose_status': 'MODEL_AUTHORED_NOT_SEMANTICALLY_VERIFIED', 'capture_sha256': digest(item),
                    'red_step': red['step_no'], 'green_step': green['step_no'], 'status': 'PROVISIONAL'}
                break
    for item in captures:
        if item['phase'] != 'VERIFICATION' or not item['accepted']:
            continue
        identity = item['selected_procedure_id']
        if identity is None:
            continue
        require(identity in candidates, 'UNKNOWN_ASSIGNED_PROCEDURE')
        candidate = candidates[identity]
        require(candidate['project'] == item['project'] and candidate['source_task_id'] != item['task_id']
                and candidate['completion_path'] != item['completion_path'], 'SELF_VERIFICATION')
        for observation in item['observations']:
            if (observation['procedure_id'] == identity and observation['status'] == 'PASS'
                    and observation['candidate_sha256'] == item['final_candidate_sha256']
                    and observation['method'] == candidate['content']['method']):
                support.setdefault(identity, []).append({'task_id': item['task_id'], 'step_no': observation['step_no'], 'capture_sha256': digest(item)})
    skills = [{**candidate, 'status': 'VERIFIED_PERSONAL', 'verification_support': support[identity]}
              for identity, candidate in sorted(candidates.items()) if identity in support]
    return {'episodes': episodes, 'candidates': [candidates[k] for k in sorted(candidates)], 'skills': skills}


def freeze(path, *, owner, stage, captures, plan_reference):
    require(stage in ('PROVISIONAL', 'FINAL'), 'UNKNOWN_STAGE')
    checked(plan_reference)
    for capture_item in captures:
        for ref in capture_item['references']:
            checked(ref)
        rebuilt = capture(Path(capture_item['references'][0]['path']).parent, phase=capture_item['phase'],
            owner=owner, project=capture_item['project'], task_id=capture_item['task_id'])
        require(rebuilt == capture_item, 'CAPTURE_DERIVATION_CHANGED')
    data = derive(captures, owner)
    payload = {'schema': SCHEMA, 'owner': owner, 'stage': stage, 'plan_reference': plan_reference,
        'captures': captures, **data, 'l3_status': 'READY' if data['skills'] else 'NOT_READY',
        'layer_counts': {'L1': len(data['episodes']), 'L3_candidates': len(data['candidates']), 'L3': len(data['skills'])}}
    write_new(path, payload)
    return {**reference(path), 'l3_status': payload['l3_status'], 'layer_counts': payload['layer_counts']}


def load(ref, *, owner):
    plain = {key: ref[key] for key in ('path', 'sha256', 'bytes')}
    payload = read(checked(plain))
    require(payload['schema'] == SCHEMA and payload['owner'] == owner, 'BANK_SCOPE_CHANGED')
    checked(payload['plan_reference'])
    for capture_item in payload['captures']:
        for source in capture_item['references']:
            checked(source)
        rebuilt = capture(Path(capture_item['references'][0]['path']).parent, phase=capture_item['phase'],
            owner=owner, project=capture_item['project'], task_id=capture_item['task_id'])
        require(rebuilt == capture_item, 'CAPTURE_DERIVATION_CHANGED')
    derived = derive(payload['captures'], owner)
    require(all(payload[key] == value for key, value in derived.items()), 'BANK_DERIVATION_CHANGED')
    require(payload['l3_status'] == ('READY' if derived['skills'] else 'NOT_READY') and payload['layer_counts'] == {
        'L1': len(derived['episodes']), 'L3_candidates': len(derived['candidates']), 'L3': len(derived['skills'])}, 'BANK_READINESS_CHANGED')
    return payload


def tokens(text):
    return set(re.findall(r'[a-z][a-z0-9_]{2,}', text.lower()))


def recall(bank, task, query, *, layer, selected_id=None):
    if layer == 'L3':
        pool = bank['candidates'] if selected_id else bank['skills']
    elif layer == 'L1':
        pool = bank['episodes']
    else:
        raise ValueError('UNKNOWN_MEMORY_LAYER')
    eligible = [row for row in pool if row['project'] == task['project'] and row['source_task_id'] != task['task_id']
                and row['completion_path'] != task['completion_path'] and (selected_id is None or row['memory_id'] == selected_id)]
    query_tokens = tokens(query)
    ranked = []
    for row in eligible:
        memory_tokens = tokens(json.dumps(row['content'], ensure_ascii=False))
        score = len(query_tokens & memory_tokens) / max(1, len(query_tokens | memory_tokens))
        if selected_id or score >= .05:
            ranked.append((score, row['memory_id'], row))
    if not ranked:
        return None
    score, _, best = sorted(ranked, key=lambda row: (-row[0], row[1]))[0]
    return {**best, 'retrieval_score': score}
