"""Read-only evidence audit and metadata-only publication for the DevEval pilot.

No model, generated test, official grader, or capture writer is invoked. Final
publication acquires the manager's existing lock and requires terminal evidence.
"""
from __future__ import annotations

import argparse
import builtins
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import deveval_repository_experiment as manager
import deveval_repository_memory as memory

SCHEMA = 'deveval/repository-results/1'
ARMS = ('OFF', 'L1_ONLY', 'NO_L2', 'NO_L3', 'FULL')
TERMINAL = ('COMPLETE', 'COMPLETE_WITH_UNRESOLVED')
TOKEN_KEYS = {'input_tokens', 'cached_input_tokens', 'output_tokens', 'prompt_tokens',
              'completion_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens',
              'audio_tokens', 'accepted_prediction_tokens', 'rejected_prediction_tokens'}
FAILURE_KINDS = {'ASSERTION', 'RUNTIME', 'CANDIDATE_FILE_MUTATED', 'CANDIDATE_NOT_EXECUTED',
                 'INSUFFICIENT_ASSERTIONS', 'TIMEOUT', 'RECEIPT_EXIT_MISMATCH', 'TEST_SETUP_ERROR',
                 'CANDIDATE_SYNTAX', 'PROJECT_IMPORT_ISOLATION'}
EXCEPTION_TYPES = {name for name, value in vars(builtins).items() if isinstance(value, type) and issubclass(value, BaseException)} | {'ProjectImportError'}


class AuditError(ValueError):
    pass


def require(value, code):
    if not value:
        raise AuditError(code)


def plain(ref):
    return {key: ref[key] for key in ('path', 'sha256', 'bytes')}


def identity(row):
    return row['phase'], row['task_id'], row['condition']


def projection(row):
    return {key: value for key, value in row.items() if not key.startswith('grade_') and key != 'passed'}


def token_fields(value, prefix=''):
    result = {}
    if not isinstance(value, dict):
        return result
    for key, number in value.items():
        path = prefix + key
        if key in TOKEN_KEYS and type(number) in (int, float) and math.isfinite(number) and number >= 0:
            result[path] = number
        elif key in ('prompt_tokens_details', 'completion_tokens_details', 'input_tokens_details', 'output_tokens_details'):
            result.update(token_fields(number, path + '.'))
    return result


def add_usage(values):
    total, available = Counter(), Counter()
    for value in values:
        for key, number in value.items():
            total[key] += number
            available[key] += 1
    return {'reported_fields': dict(sorted(total.items())), 'field_observations': dict(sorted(available.items()))}


def json_events(path):
    result = []
    for line in Path(path).read_bytes().splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue  # Native receipts use the same tolerance for diagnostic lines.
        if isinstance(event, dict):
            result.append(event)
    return result


def _memories(context):
    return context.get('memory', []) if isinstance(context, dict) else []


def session_evidence(cell, state, solve, provider):
    calls, deliveries, usages, observed_threads = [], [], [], []
    for number, receipt in enumerate(solve['sessions'], 1):
        folder = cell / ('session-%02d' % number)
        require(receipt['session'] == number and memory.read(folder / 'receipt.json') == receipt, 'SESSION_RECEIPT_CHANGED')
        for name, key in [('events.jsonl', 'events_sha256'), ('stderr.log', 'stderr_sha256')]:
            require(memory.reference(folder / name)['sha256'] == receipt[key], 'SESSION_BYTES_CHANGED')
        prompt = (folder / 'prompt.txt').read_bytes()
        proof, initial = memory.read(folder / 'prompt-receipt.json'), memory.read(folder / 'initial-state.json')
        require(proof['prompt_sha256'] == hashlib.sha256(prompt).hexdigest() and proof['prompt_bytes'] == len(prompt)
            and proof['state_before_call_sha256'] == memory.reference(folder / 'initial-state.json')['sha256'], 'PROMPT_BINDING_CHANGED')
        for key in ('task', 'phase', 'condition', 'runtime', 'owner', 'bank', 'selected_procedure_id'):
            require(initial[key] == state[key], 'SESSION_SCOPE_CHANGED')
        require(receipt['requested_model'] == state['runtime']['native']['model'], 'SESSION_MODEL_CHANGED')
        require(proof['task_id'] == state['task']['task_id'] and proof['arm'] == state['arm'], 'PROMPT_SCOPE_CHANGED')
        packet = json.loads(prompt.decode('utf-8').split('\nTASK_PACKET:\n', 1)[1])
        require(packet['task'] == state['task'], 'PROMPT_TASK_CHANGED')
        deliveries.extend(_memories(packet.get('context')))
        events = json_events(folder / 'events.jsonl')
        session_calls = []
        if provider == 'native_codex':
            require(receipt['requested_reasoning_effort'] == state['runtime']['native']['reasoning_effort'], 'SESSION_EFFORT_CHANGED')
            threads = [event.get('thread_id') for event in events if event.get('type') == 'thread.started']
            require(threads == receipt['thread_ids'] and all(isinstance(t, str) and t for t in threads), 'NATIVE_THREAD_CHANGED')
            if solve['status'] == 'SUBMITTED':
                require(threads, 'NATIVE_THREAD_MISSING')
            observed_threads.extend(threads)
            expected_usage = [event.get('usage') for event in events if event.get('type') == 'turn.completed']
            require(expected_usage == receipt.get('usage', []), 'NATIVE_USAGE_CHANGED')
            usages.extend(token_fields(value) for value in expected_usage)
            items = [event.get('item', {}) for event in events if event.get('type') == 'item.completed']
            native_calls = [item for item in items if (item.get('type'), item.get('server'), item.get('tool')) == ('mcp_tool_call', 'benchmark', 'action')]
            require(len(native_calls) == receipt['benchmark_action_calls'], 'ACTION_ACCOUNTING_CHANGED')
            for item in native_calls:
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
                        session_calls.append((request, response))
        else:
            require(provider == receipt.get('provider') == 'vllm' and receipt['thread_ids'] == [], 'HTTP_PROVIDER_CHANGED')
            response_ids, expected_usage = [], []
            for path in sorted(folder.glob('http-*/receipt.json')):
                http = memory.read(path)
                memory.checked(http['request_reference'])
                if 'response_reference' in http:
                    memory.checked(http['response_reference'])
                if http.get('status') == 'RECEIVED':
                    if isinstance(http.get('response_id'), str):
                        response_ids.append(http['response_id'])
                    expected_usage.append(http.get('usage', {}))
            require(response_ids == receipt['response_ids'] and expected_usage == receipt['usage'], 'HTTP_USAGE_CHANGED')
            usages.extend(token_fields(value) for value in expected_usage)
            for event in events:
                require(event.get('type') != 'thread.started' and event.get('item', {}).get('type') != 'mcp_tool_call', 'MIXED_PROVIDER_EVIDENCE')
                if event.get('type') != 'gateway.action.completed':
                    continue
                http = memory.read(memory.checked(event['http_receipt_reference']))
                require(event.get('provider') == 'vllm' and event.get('session') == number and http.get('status') == 'RECEIVED'
                    and event['http_request_reference'] == http['request_reference'] and event['http_response_reference'] == http['response_reference'], 'HTTP_ACTION_BINDING_CHANGED')
                request_body = memory.read(memory.checked(event['http_request_reference']))
                response_body = memory.read(memory.checked(event['http_response_reference']))
                require(request_body['model'] == state['runtime']['gateway']['model']
                    and response_body.get('id') == event.get('response_id') == http.get('response_id'), 'HTTP_MODEL_CHANGED')
                from deveval_model_gateway import validate_action
                try:
                    action = validate_action(json.loads(response_body['choices'][0]['message']['content']))
                except (ValueError, TypeError, KeyError):
                    action = {}
                require(action == event['request'] and memory.digest(action) == event['request_sha256']
                    and memory.digest(event['response']) == event['response_sha256'], 'HTTP_ACTION_CHANGED')
                session_calls.append((action, event['response']))
            require(len(session_calls) == receipt['benchmark_action_calls'], 'ACTION_ACCOUNTING_CHANGED')
        calls.extend(session_calls)
        for _, response in session_calls:
            deliveries.extend(_memories(response.get('context')))
    successes = [(request, response) for request, response in calls if isinstance(request, dict)
                 and request.get('tool') != 'finish' and response.get('status') == 'success']
    require(len(successes) == len(state['history']), 'HISTORY_CALLS_CHANGED')
    for entry in state['history']:
        matches = [(request, response) for request, response in successes if response['step_no'] == entry['step_no']]
        require(len(matches) == 1 and matches[0][0] == entry['request_payload']
            and matches[0][1]['result'] == entry['result_payload'], 'HISTORY_CALLS_CHANGED')
    if solve['status'] == 'SUBMITTED':
        finishes = [(request, response) for request, response in calls if isinstance(request, dict)
            and request.get('tool') == 'finish' and response.get('status') == 'success' and response.get('result', {}).get('submitted') is True]
        require(state['finished'] is True and solve['error_type'] is None and len(finishes) == 1
            and finishes[0][0]['arguments'] == {'code': state['candidate'], 'source_lesson': state['source_lesson']}
            and finishes[0][1]['result']['candidate_sha256'] == solve['candidate_sha256'], 'SUBMISSION_NOT_CORROBORATED')
    known = {memory.digest(item) for item in state['memory_injections']}
    require(all(memory.digest(item) in known for item in deliveries), 'UNBOUND_MEMORY_DELIVERY')
    delivered = {memory.digest(item) for item in deliveries}
    allowed = manager.native.LAYERS[state['condition']]
    require(all(item['layer'] in allowed for item in state['memory_injections']), 'DISABLED_LAYER_EXPOSURE')
    return {'usage_records': usages, 'thread_count': len(observed_threads),
        'recorded_layer_injections': dict(Counter(item['layer'] for item in state['memory_injections'])),
        'delivered_layer_injections': dict(Counter(item['layer'] for item in state['memory_injections'] if memory.digest(item) in delivered)),
        'undelivered_injections': len(known - delivered)}


def generated_evidence(cell, state):
    status, failures, exceptions, messages = Counter(), Counter(), Counter(), Counter()
    executed = not_executed = unknown_execution = assertions = count = 0
    for entry in state['history']:
        if entry['tool'] != 'run_command':
            continue
        result = entry['result_payload']
        receipt = cell / 'generated-tests' / ('step-%03d' % entry['step_no']) / 'receipt.json'
        require(memory.read(receipt) == result, 'GENERATED_RECEIPT_CHANGED')
        count += 1
        status[result['status'] if result['status'] in ('PASS', 'FAIL', 'INFRA_ERROR') else 'UNKNOWN'] += 1
        if result.get('failure_kind') is not None:
            kind = result['failure_kind']
            failures[kind if kind in FAILURE_KINDS else 'UNKNOWN'] += 1
        if result.get('exception_type') is not None:
            name = result['exception_type']
            exceptions[name if name in EXCEPTION_TYPES else 'CUSTOM_EXCEPTION'] += 1
        message = result.get('message')
        if isinstance(message, str) and message:
            messages[hashlib.sha256(message.encode()).hexdigest()] += 1
        executed += result.get('candidate_executed') is True
        not_executed += result.get('candidate_executed') is False
        unknown_execution += type(result.get('candidate_executed')) is not bool
        number = result.get('assertions_executed', 0)
        require(type(number) is int and number >= 0, 'INVALID_ASSERTION_COUNT')
        assertions += number
    require(count <= state['public_test_runs'], 'GENERATED_ATTEMPTS_CHANGED')
    return {'attempted': state['public_test_runs'], 'recorded_receipts': count,
        'unrecorded_receipts': state['public_test_runs'] - count, 'candidate_executed': executed,
        'candidate_not_executed': not_executed, 'candidate_execution_unknown': unknown_execution,
        'assertions_executed': assertions,
        'status_counts': dict(status), 'failure_kind_counts': dict(failures),
        'exception_type_counts': dict(exceptions), 'exception_message_sha256_counts': dict(messages)}


def generated_metrics(rows):
    names = ('attempted', 'recorded_receipts', 'unrecorded_receipts', 'candidate_executed',
             'candidate_not_executed', 'candidate_execution_unknown', 'assertions_executed')
    result = {key: sum(row['generated_tests'][key] for row in rows) for key in names}
    for key in ('status_counts', 'failure_kind_counts', 'exception_type_counts', 'exception_message_sha256_counts'):
        count = Counter()
        for row in rows:
            count.update(row['generated_tests'][key])
        result[key] = dict(sorted(count.items()))
    return result


def group_metrics(rows):
    total = len(rows)
    passed, failed = sum(r['primary_passed'] is True for r in rows), sum(r['primary_passed'] is False for r in rows)
    unresolved = total - passed - failed
    return {'planned': total, 'submitted': sum(r['submitted'] for r in rows), 'passed': passed, 'failed': failed,
        'unresolved': unresolved, 'success_rate': passed / total if total and not unresolved else None,
        'success_rate_bounds': [passed / total, (passed + unresolved) / total] if total else None,
        'solve_seconds': sum(r['solve_seconds'] for r in rows), 'tool_seconds': sum(r['tool_seconds'] for r in rows),
        'grade_seconds_reported': sum(r['grade_seconds'] or 0 for r in rows), 'sessions': sum(r['sessions'] for r in rows),
        'tool_actions': sum(r['tool_actions'] for r in rows), 'generated_test_runs': sum(r['generated_test_runs'] for r in rows),
        'declared_procedure_applications': sum(r['declared_procedure_applications'] for r in rows),
        'delivered_layer_injections': {layer: sum(r['delivered_layer_injections'].get(layer, 0) for r in rows) for layer in ('L1', 'L2', 'L3')},
        'generated_tests': generated_metrics(rows),
        'usage': add_usage([usage for row in rows for usage in row['usage_records']])}


def paired(rows, arm):
    off = {row['task_id']: row['primary_passed'] for row in rows if row['condition'] == 'OFF'}
    other = {row['task_id']: row['primary_passed'] for row in rows if row['condition'] == arm}
    require(set(off) == set(other), 'PAIRED_ENROLLMENT_CHANGED')
    counts = Counter()
    for task_id, baseline in off.items():
        outcome = other[task_id]
        counts['unresolved' if baseline is None or outcome is None else
               'both_pass' if baseline and outcome else 'both_fail' if not baseline and not outcome else
               'gain' if outcome else 'loss'] += 1
    total, complete = len(off), len(off) - counts['unresolved']
    return {'baseline': 'OFF', 'condition': arm, 'planned_pairs': total, 'complete_pairs': complete,
        **{key: counts[key] for key in ('both_pass', 'both_fail', 'gain', 'loss', 'unresolved')},
        'delta_all_planned': (counts['gain'] - counts['loss']) / total if total and complete == total else None,
        'delta_complete_pairs_descriptive': (counts['gain'] - counts['loss']) / complete if complete else None}


def _audit(run_root, plan_path=None, runtime_path=None):
    summary_ref, frozen_ref = memory.reference(run_root / 'summary.json'), memory.reference(run_root / 'frozen-inputs.json')
    summary, frozen = memory.read(summary_ref['path']), memory.read(frozen_ref['path'])
    require(summary['schema'] == 'deveval/repository-summary/1' and summary['status'] in TERMINAL and summary['phase'] == 'COMPLETE', 'RUN_NOT_TERMINAL')
    require(frozen['schema'] == 'deveval/repository-experiment/1', 'FROZEN_SCHEMA_CHANGED')
    context = {'output': run_root, 'frozen': frozen, 'owner': frozen['owner']}
    manager.verify(context)
    plan_ref, runtime_ref = frozen['references'][:2]
    require(plan_path is None or Path(plan_path).resolve() == Path(plan_ref['path']).resolve(), 'PLAN_REFERENCE_CHANGED')
    require(runtime_path is None or Path(runtime_path).resolve() == Path(runtime_ref['path']).resolve(), 'RUNTIME_REFERENCE_CHANGED')
    plan, runtime = memory.read(plan_ref['path']), memory.read(runtime_ref['path'])
    context.update(plan=plan, runtime=runtime)
    jobs = manager.plan_schedule(plan)
    require(jobs == frozen['schedule'] and len({identity(j) for j in jobs}) == len(jobs), 'SCHEDULE_CHANGED')
    require(frozen['requested_model'] == runtime['native']['model'], 'REQUESTED_MODEL_CHANGED')
    provider = runtime.get('gateway', {}).get('provider', 'native_codex')
    require(provider == frozen['provider'], 'PROVIDER_CHANGED')
    if provider == 'native_codex':
        require(runtime['native']['model'] == plan['model']['model'] and runtime['native']['reasoning_effort'] == plan['model']['reasoning_effort'], 'MODEL_PLAN_CHANGED')
        executable_ref = memory.reference(runtime['native']['codex_executable'])
        require(executable_ref in frozen['references'], 'EXECUTABLE_NOT_FROZEN')
    else:
        require(provider == 'vllm' and runtime['native']['model'] == runtime['gateway']['model'], 'REPLICATION_MODEL_CHANGED')
        executable_ref = None
    require(summary['planned_cells'] == summary['recorded_cells'] == len(jobs)
        and [identity(row) for row in summary['cells']] == [identity(job) for job in jobs]
        and [row['ordinal'] for row in summary['cells']] == [job['ordinal'] for job in jobs], 'SUMMARY_ENROLLMENT_CHANGED')
    collections = {}
    for phase in manager.PHASES:
        ref = memory.reference(run_root / phase / 'collection.json')
        manager.verify_collection(ref)
        value = memory.read(ref['path'])
        expected = [projection(row) for row in summary['cells'] if row['phase'] == phase]
        require(value['phase'] == phase and value['status'] == 'SEALED' and value['rows'] == expected, 'SEALED_ENROLLMENT_CHANGED')
        collections[phase] = ref
    bank_ref = summary['bank']
    require(Path(bank_ref['path']).resolve() == (run_root / 'bank-final.json').resolve(), 'FINAL_BANK_PATH_CHANGED')
    bank = memory.load(bank_ref, owner=frozen['owner'])
    require(bank['stage'] == 'FINAL' and bank['plan_reference'] == plan_ref, 'BANK_PLAN_CHANGED')
    source_jobs = [job for job in jobs if job['phase'] in ('DISCOVERY', 'VERIFICATION')]
    require({(row['phase'], row['task_id']) for row in bank['captures']} == {(job['phase'], job['task_id']) for job in source_jobs}
        and len(bank['captures']) == len(source_jobs), 'BANK_SOURCE_COHORT_CHANGED')
    results = []
    for job, row in zip(jobs, summary['cells']):
        cell = manager.cell_path(context, job)
        require(row['state_reference'] == memory.reference(cell / 'state.json') and row['solve_reference'] == memory.reference(cell / 'solve-receipt.json'), 'CELL_REFERENCE_CHANGED')
        state, solve, stored = memory.read(cell / 'state.json'), memory.read(cell / 'solve-receipt.json'), memory.read(cell / 'cell-receipt.json')
        require(projection(stored) == projection(row), 'CELL_ROW_CHANGED')
        require(state['task']['task_id'] == job['task_id'] and state['task']['project'] == job['project']
            and state['phase'] == job['phase'] and state['condition'] == job['condition']
            and state['owner'] == frozen['owner'] and state['runtime'] == runtime, 'CELL_SCOPE_CHANGED')
        require(state['snapshot_reference'] == frozen['snapshots'][job['project']], 'CELL_SNAPSHOT_CHANGED')
        expected_arm = 'TRAIN' if job['condition'] == 'TRAIN' else 'OFF' if job['condition'] == 'OFF' else 'ON'
        require(state['arm'] == solve['arm'] == expected_arm and solve['task_id'] == job['task_id'], 'CELL_ARM_CHANGED')
        require(solve['state_sha256'] == row['state_reference']['sha256'] and solve['candidate_sha256'] == row['candidate_sha256']
            == hashlib.sha256(state['candidate'].encode()).hexdigest() and solve['status'] == row['status']
            and solve['error_type'] == row['error_type'], 'SOLVE_BINDING_CHANGED')
        expected_authority = {'job': job, 'bank': state['bank'], 'selected_procedure_id': state['selected_procedure_id'], 'frozen_inputs_reference': frozen_ref}
        require(memory.read(cell / 'attempt.json') == memory.read(run_root / 'starts' / ('%03d.json' % job['ordinal'])) == expected_authority, 'START_AUTHORITY_CHANGED')
        if job['condition'] in ('OFF', 'TRAIN'):
            require(state['bank'] is None, 'BASELINE_BANK_PRESENT')
        elif job['phase'] in ('VALID', 'TEST'):
            require(state['bank'] == bank_ref and state['selected_procedure_id'] is None, 'TARGET_BANK_CHANGED')
        evidence = session_evidence(cell, state, solve, provider)
        generated = generated_evidence(cell, state)
        official = None
        if row['status'] == 'SUBMITTED':
            if 'grade_reference' in row:
                receipt = manager.validate_grade(context, job, row, collections[job['phase']])
                official = receipt.get('official_result') if receipt['status'] == 'GRADED' else None
                primary = receipt['passed'] if receipt['status'] == 'GRADED' else None
            else:
                require(row['grade_status'] == 'INFRA_ERROR' and row.get('grade_error_type') in ('InterruptedGradeNoRetry', 'OfficialTransportFailure')
                    and (cell / 'private-grade').is_dir(), 'UNBOUND_PRIVATE_OUTCOME')
                primary = None
        else:
            require(row['status'] == 'GENERATION_ERROR' and row['grade_status'] == 'NOT_GRADED' and 'grade_reference' not in row, 'UNEXPECTED_TERMINAL_SOLVE')
            primary = False if row['error_type'] in manager.MODEL_FAILURES else None
        require(type(primary) is bool or primary is None, 'INVALID_PRIMARY_TYPE')
        require(row['passed'] is primary, 'PRIMARY_OUTCOME_CHANGED')
        declared = sum(entry['tool'] == 'run_command' and bool(entry['request_payload']['arguments'].get('procedure_id')) for entry in state['history'])
        require(row['sessions'] == len(solve['sessions']) and row['tool_actions'] == solve['tool_actions']
            and row['generated_test_runs'] == state['public_test_runs'] and row['declared_procedure_applications'] == declared
            and row['solve_seconds'] == solve['wall_seconds'] and row['tool_seconds'] == solve['tool_seconds']
            and row['memory_layers'] == [item['layer'] for item in state['memory_injections']], 'SUMMARY_ACCOUNTING_CHANGED')
        results.append({**{key: job[key] for key in ('ordinal', 'phase', 'task_id', 'project', 'condition')},
            'candidate_sha256': row['candidate_sha256'], 'submitted': row['status'] == 'SUBMITTED',
            'primary_passed': primary, 'official_result': official,
            'outcome': 'GRADED_PASS' if primary is True else 'GRADED_FAIL' if official else 'MODEL_PROTOCOL_FAILURE' if primary is False else 'UNRESOLVED_INFRASTRUCTURE',
            'solve_seconds': solve['wall_seconds'], 'tool_seconds': solve['tool_seconds'], 'grade_seconds': row.get('grade_seconds'),
            'sessions': len(solve['sessions']), 'tool_actions': solve['tool_actions'], 'generated_test_runs': state['public_test_runs'],
            'declared_procedure_applications': declared, 'generated_tests': generated, **evidence})
    unresolved = any(row['primary_passed'] is None for row in results)
    require(summary['status'] == ('COMPLETE_WITH_UNRESOLVED' if unresolved else 'COMPLETE'), 'TERMINAL_STATUS_CHANGED')
    phases = {}
    for phase in manager.PHASES:
        rows = [row for row in results if row['phase'] == phase]
        conditions = sorted({row['condition'] for row in rows})
        if phase in ('VALID', 'TEST'):
            expected_ids = {task['task_id'] for task in plan['tasks'] if task['phase'] == phase}
            require(set(conditions) == set(ARMS) and all({r['task_id'] for r in rows if r['condition'] == arm} == expected_ids for arm in ARMS), 'FIVE_ARM_ENROLLMENT_CHANGED')
        phase_result = {'task_count': len({row['task_id'] for row in rows}),
            'arms': {arm: group_metrics([row for row in rows if row['condition'] == arm]) for arm in conditions},
            'per_repository': {project: {arm: group_metrics([row for row in rows if row['project'] == project and row['condition'] == arm]) for arm in conditions}
                               for project in sorted({row['project'] for row in rows})}}
        if phase in ('VALID', 'TEST'):
            phase_result['paired_vs_off'] = {arm: paired(rows, arm) for arm in ARMS if arm != 'OFF'}
            phase_result['paired_per_repository'] = {project: {arm: paired([row for row in rows if row['project'] == project], arm)
                for arm in ARMS if arm != 'OFF'} for project in phase_result['per_repository']}
        phases[phase] = phase_result
    heldout = [row for row in results if row['phase'] in ('VALID', 'TEST')]
    exposure = sum(row['delivered_layer_injections'].get('L3', 0) for row in heldout)
    report = {'schema': SCHEMA, 'status': 'AUDITED', 'run_status': summary['status'], 'experiment_id': plan['experiment_id'],
        'scope': 'SMALL_REPOSITORY_LOCAL_PILOT_NOT_FULL_1825_TASK_BENCHMARK', 'repository_held_out_generalization': False,
        'primary_metric': 'ACCEPTED_SUBMISSION_AND_OFFICIAL_PRIVATE_PASS', 'planned_cells': len(jobs),
        'requested_model': frozen['requested_model'], 'provider': provider, 'reasoning_effort': frozen['reasoning_effort'],
        'executable_sha256': executable_ref['sha256'] if executable_ref else None, 'budgets': plan['budgets'],
        'source_phases': {phase: phases[phase] for phase in ('DISCOVERY', 'VERIFICATION')},
        'heldout_phases': {phase: phases[phase] for phase in ('VALID', 'TEST')},
        'bank': {'sha256': bank_ref['sha256'], 'l3_status': bank['l3_status'], 'layer_counts': bank['layer_counts'],
                 'heldout_l3_delivered_injections': exposure,
                 'l3_effect_claim': 'NOT_ESTIMABLE_ZERO_SKILLS' if not bank['skills'] else 'NOT_ESTIMABLE_NO_EXPOSURE' if not exposure else 'DESCRIPTIVE_PILOT_ONLY'},
        'manager_seconds': summary['manager_seconds'], 'usage_and_cost_notes': {
            'token_fields_are_reported_not_billing': True, 'token_fields_may_overlap': True,
            'billing_cost': None, 'tool_seconds_included_in_solve_seconds': True},
        'evidence': {'summary_sha256': summary_ref['sha256'], 'frozen_inputs_sha256': frozen_ref['sha256'],
            'plan_sha256': plan_ref['sha256'], 'runtime_sha256': runtime_ref['sha256'],
            'collection_sha256': {phase: ref['sha256'] for phase, ref in collections.items()},
            'implementation': [{'file': Path(ref['path']).name, 'sha256': ref['sha256']} for ref in frozen['references'] if Path(ref['path']).suffix == '.py'],
            'auditor_sha256': memory.reference(__file__)['sha256']},
        'cells': [{key: value for key, value in row.items() if key != 'usage_records'} | {'usage': add_usage(row['usage_records'])} for row in results]}
    manager.verify(context)
    for ref in (summary_ref, frozen_ref, plain(bank_ref), *collections.values()):
        memory.checked(ref)
    for ref in collections.values():
        manager.verify_collection(ref)
    return report


def audit(run_root, *, plan_path=None, runtime_path=None):
    root = Path(run_root).resolve()
    require((root / 'experiment.lock').is_file(), 'EXPERIMENT_LOCK_MISSING')
    with manager.original_manager.exclusive_lock(root):
        return _audit(root, plan_path, runtime_path)


def publish(run_root, output, *, plan_path=None, runtime_path=None):
    root, output = Path(run_root).resolve(), Path(output).resolve()
    require(not output.is_relative_to(root), 'PUBLICATION_MUST_NOT_MUTATE_RUN')
    require((root / 'experiment.lock').is_file(), 'EXPERIMENT_LOCK_MISSING')
    with manager.original_manager.exclusive_lock(root):
        report = _audit(root, plan_path, runtime_path)
        memory.write_new(output, report)
        return memory.reference(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('audit', 'publish'))
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--runtime', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'publish':
            require(args.output is not None, 'OUTPUT_REQUIRED')
            ref = publish(args.run_root, args.output, plan_path=args.plan, runtime_path=args.runtime)
            print(json.dumps({'status': 'PUBLISHED', 'sha256': ref['sha256'], 'bytes': ref['bytes']}))
        else:
            result = audit(args.run_root, plan_path=args.plan, runtime_path=args.runtime)
            print(json.dumps({'status': result['status'], 'run_status': result['run_status'], 'planned_cells': result['planned_cells']}))
    except Exception as error:
        print(json.dumps({'status': 'ERROR', 'error_type': type(error).__name__,
                          'error_code': str(error) if isinstance(error, AuditError) else 'AUDIT_PROVENANCE_REJECTED'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
