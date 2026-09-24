"""Versioned private-procedure experiment over the immutable native broker.

run_command is a typed generated-case test operation, never a shell command.
Generated expectations are model-authored and never labelled ground truth.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import lcb_explicit_format_native as explicit
import trimem_lcb_native as core

_context = explicit._original_context
_prompt = explicit._original_prompt
_worker = explicit._original_worker
_solve = explicit._original_solve
_initialize = core.initialize_cell
_public_run = core.public_run
_banks = {}

PROCEDURE_CONTRACT = '''ADDITIONAL PUBLIC TEST OPERATION (same capabilities and budgets in all arms):
run_command is NOT a shell. Its only supported arguments are:
{"code":"complete Python candidate","cases":[{"input":"encoded input","output":"expected output"}],
 "method":"boundary_cases","rationale":"why these cases exercise this task","procedure_id":null}.
Provide 2 through 12 DISTINCT inputs; the whole case list must fit 32768 UTF-8 bytes.
Use the same input/output string encoding as the task's public_examples, including the function argument
encoding for function tasks. Expected outputs are YOUR assertions, not an independent correctness oracle.
method is exactly boundary_cases or differential_cases. differential_cases is a declared testing strategy;
this tool does not itself derive an independent reference solution. Explain your derivation in rationale.
procedure_id is null or omitted for your own strategy, or exactly an ID supplied in this task's memory.
The tool executes the candidate on these cases and records exact candidate/case hashes and outcomes.
All run_public_tests and run_command calls SHARE the same four-test budget. A real run_public_tests call
is still separately required to finish. Tool actions, source byte, session and time limits are unchanged.
Test meaningful real candidate implementations; do not manufacture errors or failing stubs to create memory.
After modifying a candidate in response to generated cases, recheck the final source on the public examples.
An earlier passing result does not verify a different final source. Keep source_lesson trace anchors accurate.
Source lessons may describe useful testing/repair methods and cite the actual generated-test trace IDs.
Memories labelled PROVISIONAL are proposals undergoing validation, NOT already verified procedures.
Private L3 means a personally verified execution workflow. It is not an organisation-wide certified skill,
an independently verified oracle, or proof of correctness on hidden tests. Check applicability before use.
'''


def initialize_cell(path, task, arm, runtime, *, bank=None, phase='DISCOVERY',
                    owner_user_id='lcb-personal-owner', org_id='skhynix-poc',
                    selected_procedure_id=None, enabled_layers=('L3', 'L2', 'L1')):
    state = _initialize(path, task, arm, runtime, bank=bank)
    state.update(phase=phase, owner_user_id=owner_user_id, org_id=org_id,
                 selected_procedure_id=selected_procedure_id,
                 enabled_layers=list(enabled_layers), generated_test_runs=0,
                 procedure_events=[])
    core.write(Path(path) / 'state.json', state)
    return state


def context(state, *, recall=True):
    graph = core.ShortTermWorkingGraph.from_snapshot(state['graph'])
    if state['arm'] == 'ON' and recall and graph.active_node is not None:
        import lcb_personal_memory as memory
        key = (state['bank']['path'], state['bank']['sha256'])
        if key not in _banks:
            # Full provenance is verified once per broker process. The immutable
            # bank's own bytes are rechecked by recall on each access.
            _banks[key] = memory.load_bank(*key)
        decision = _banks[key].recall(state['task'], graph, phase=state['phase'],
            owner_user_id=state['owner_user_id'], enabled_layers=tuple(state['enabled_layers']),
            procedure_id=state.get('selected_procedure_id'), checkpoint=state['memory_checkpoint'])
        state['memory_checkpoint'] = decision.get('checkpoint')
        state['memory_decisions'].append(decision.get('decisions', []))
        for item in decision.get('injections', []):
            item = {**item, 'active_node_id': graph.active_node_id}
            if core.digest(item) not in {core.digest(row) for row in state['memory_injections']}:
                state['memory_injections'].append(item)
    value = _context(state, recall=False)
    remaining = state['limits']['public_tests'] - state['public_test_runs'] - state.get('generated_test_runs', 0)
    value['remaining_public_tests'] = remaining
    value['remaining_shared_test_executions'] = remaining
    value['submission_contract'] = {
        'available_trace_steps': sorted(event['step_no'] for event in state['history']),
        'public_test_attempts': state['public_test_runs'],
        'trace_steps_type': 'nonempty_sorted_unique_array_of_target_history_integers',
    }
    return value


def prompt_for(state):
    base = _prompt(state)
    prefix, packet = base.split('TASK_PACKET:\n', 1)
    prefix = prefix.replace('"trace_steps":[ACTUAL_PUBLIC_TRACE_STEP]', '"trace_steps":[2]')
    guide = explicit.CONTRACT + '\n' + PROCEDURE_CONTRACT
    if state['phase'] == 'DISCOVERY':
        guide += '\nTRAIN discovery: use generated cases to investigate your real candidate if useful. Record actual findings in source_lesson; never invent a failure or a verification.\n'
    elif state['phase'] == 'VERIFICATION':
        guide += '\nTRAIN verification: examine the supplied provisional procedure. If applicable, explicitly identify its procedure_id in run_command before executing your task-specific cases. Report inapplicability honestly; success is not required.\n'
    value = prefix + guide + '\nTASK_PACKET:\n' + packet
    if len(value.encode('utf-8')) > state['limits']['prompt_bytes']:
        raise ValueError('Transfer prompt byte budget exceeded')
    return value


def worker_command(cell, state):
    command = _worker(cell, state)
    setting = 'mcp_servers.benchmark.args='
    indices = [i for i, arg in enumerate(command) if arg.startswith(setting)]
    if len(indices) != 1:
        raise ValueError('Unexpected native broker arguments')
    index = indices[0]
    args = json.loads(command[index][len(setting):])
    if Path(args[0]).resolve() != Path(core.__file__).resolve():
        raise ValueError('Unexpected original native script')
    args[0] = str(Path(__file__).resolve())
    command[index] = setting + json.dumps(args)
    return command


def solve_cell(cell, *, before_model_call=None):
    cell = Path(cell).resolve()
    def seal():
        if before_model_call:
            before_model_call()
        state = core.read(cell / 'state.json')
        folder = cell / ('session-%02d' % state['session'])
        prompt = (folder / 'prompt.txt').read_bytes()
        # Preserve actual before-call state, rather than an unverifiable hash alone.
        core.write(folder / 'initial-state.json', state, fresh=True)
        core.write(folder / 'prompt-receipt.json', {
            'schema': 'lcb-transfer-prompt/1', 'created_at': datetime.now(timezone.utc).isoformat(),
            'task_id': state['task']['task_id'], 'arm': state['arm'], 'phase': state['phase'],
            'session': state['session'], 'prompt_sha256': hashlib.sha256(prompt).hexdigest(),
            'prompt_bytes': len(prompt), 'common_contract_sha256': core.digest(explicit.CONTRACT + PROCEDURE_CONTRACT),
            'state_before_call_sha256': hashlib.sha256((folder / 'initial-state.json').read_bytes()).hexdigest(),
            'command_sha256': core.digest(worker_command(cell, state)),
        }, fresh=True)
    return _solve(cell, before_model_call=seal)


def generated_run(cell, state, args):
    cases = args['cases']
    shadow = deepcopy(state)
    original = json.loads(state['task']['public_evaluation_sample']['input_output'])
    sample = {key: value for key, value in original.items() if key not in ('inputs', 'outputs')}
    sample.update(inputs=[x['input'] for x in cases], outputs=[x['output'] for x in cases])
    shadow['task']['public_evaluation_sample'] = {'input_output': json.dumps(sample, ensure_ascii=False)}
    shadow['task']['public_test_cases'] = deepcopy(cases)
    shadow['task']['public_tests_sha256'] = core.digest(shadow['task']['public_evaluation_sample'])
    feedback = _public_run(Path(cell) / 'generated', shadow, args['code'])
    return {'schema': 'lcb/personal-procedure-test/1', 'task_id': state['task']['task_id'],
            'candidate_sha256': feedback['candidate_sha256'], 'cases_sha256': core.digest(cases),
            'method': args['method'], 'procedure_id': args.get('procedure_id'),
            'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS',
            **{key: feedback.get(key) for key in ('status', 'passed', 'test_count', 'passed_count',
                'failed_count', 'not_run_count', 'timed_out', 'exit_code', 'elapsed_seconds', 'failure_kind')}}


def _generated_args(args, state):
    if not {'code', 'cases', 'method', 'rationale'} <= set(args) or set(args) - {'code', 'cases', 'method', 'rationale', 'procedure_id'}:
        raise ValueError('run_command accepts only code, cases, method, rationale, optional procedure_id')
    if args['method'] not in ('boundary_cases', 'differential_cases'):
        raise ValueError('Invalid testing method')
    if not isinstance(args['rationale'], str) or not args['rationale'].strip() or len(args['rationale'].encode()) > 3000:
        raise ValueError('Provide a bounded task-specific rationale')
    if args.get('procedure_id') is not None:
        ids = {item.get('procedure_id') for item in state.get('memory_injections', [])}
        # A source procedure must actually have been offered in this cell.
        if not isinstance(args['procedure_id'], str) or args['procedure_id'] not in ids:
            raise ValueError('procedure_id was not delivered in this task')
    cases = args['cases']
    if not isinstance(cases, list) or not 2 <= len(cases) <= 12 or len(core.canonical(cases)) > 32768:
        raise ValueError('Provide 2 through 12 bounded generated cases')
    if any(not isinstance(case, dict) or set(case) != {'input', 'output'} or
           any(not isinstance(case[key], str) for key in ('input', 'output')) for case in cases):
        raise ValueError('Each generated case contains input and output strings')
    if len({case['input'] for case in cases}) != len(cases):
        raise ValueError('Generated inputs must be distinct')


def apply_action(cell, request, *, expected_session=None, public_runner=_public_run, generated_runner=generated_run):
    state_path = Path(cell) / 'state.json'
    state = core.read(state_path)
    if expected_session is not None and state['session'] != expected_session:
        raise ValueError('Expired worker session')
    if state['finished'] or state['handoff_required']:
        raise ValueError('Worker is complete; stop now')
    if state['step'] >= state['limits']['tool_actions'] or time.time() - state['started_epoch'] >= state['limits']['task_seconds']:
        raise ValueError('Task budget exhausted')
    state['step'] += 1
    core.write(state_path, state)
    graph = core.ShortTermWorkingGraph.from_snapshot(state['graph'])
    active_id = graph.active_node_id
    started, status, tool = time.monotonic(), 'success', None
    try:
        if not isinstance(request, dict) or set(request) != {'tool', 'arguments'} or not isinstance(request['arguments'], dict):
            raise ValueError('Use exactly tool and arguments')
        tool, args = request['tool'], request['arguments']
        if tool not in ('revise_subtask_dag', 'run_public_tests', 'run_command', 'complete_subtask', 'finish'):
            raise ValueError('Unknown bounded operation')
        if active_id is None and tool != 'finish':
            raise ValueError('All subtasks completed; finish the task')
        if tool == 'revise_subtask_dag':
            if state['history'] or set(args) != {'subtasks'}:
                raise ValueError('Declare the plan once before other operations')
            specs = args['subtasks']
            if not isinstance(specs, list) or not 1 <= len(specs) <= state['limits']['subtasks']:
                raise ValueError('Provide one to three semantic subtasks')
            replacement = core.ShortTermWorkingGraph(graph.task_id, graph.objective, graph.repository)
            previous = None
            for index, row in enumerate(specs):
                if not isinstance(row, dict) or set(row) - {'objective', 'operation', 'symbols', 'apis', 'invariants'}:
                    raise ValueError('Invalid subtask fields')
                node_id = 'subgoal-%d' % (index + 1)
                replacement.add_subtask(core.SubtaskSpec(node_id=node_id, objective=row['objective'],
                    operation=row['operation'], dependencies=(previous,) if previous else (), files=('solution.py',),
                    symbols=tuple(row.get('symbols', ())), apis=tuple(row.get('apis', ())),
                    invariants=tuple(row.get('invariants', ())), tests=('public_examples',)))
                previous = node_id
            replacement.activate_next()
            graph, active_id = replacement, replacement.active_node_id
            result = {'dag_revised': True, 'active_node_id': active_id}
        elif tool in ('run_public_tests', 'run_command'):
            code = args.get('code')
            if not isinstance(code, str) or not code.strip() or len(code.encode()) > state['limits']['code_bytes']:
                raise ValueError('Provide bounded complete Python source')
            if state['public_test_runs'] + state['generated_test_runs'] >= state['limits']['public_tests']:
                raise ValueError('Shared public/generated test budget exhausted')
            if tool == 'run_public_tests':
                if set(args) != {'code'}:
                    raise ValueError('run_public_tests accepts only code')
                state['public_test_runs'] += 1
            else:
                _generated_args(args, state)
                state['generated_test_runs'] += 1
            state['candidate'] = code
            core.write(state_path, state)
            result = public_runner(cell, state, code) if tool == 'run_public_tests' else generated_runner(cell, state, args)
            graph.record_evidence(core.Evidence.capture('public_test' if tool == 'run_public_tests' else 'generated_test',
                result['status'], result, source=tool, attributes={'files': ['solution.py']}))
            if tool == 'run_command':
                state['procedure_events'].append({'step_no': state['step'], 'method': args['method'],
                    'procedure_id': args.get('procedure_id'), 'rationale': args['rationale'],
                    'request': deepcopy(args), 'result': deepcopy(result),
                    'request_sha256': core.digest(args), 'result_sha256': core.digest(result)})
        elif tool == 'complete_subtask':
            if set(args) != {'evidence'} or not isinstance(args['evidence'], str) or not args['evidence'].strip():
                raise ValueError('Provide a grounded progress summary')
            summary = args['evidence'][:3000]
            evidence = core.Evidence.capture('agent_progress', summary, {'summary': summary},
                source='model_report_not_correctness_proof', supports_completion=True)
            graph.complete_active(evidence)
            graph.activate_next()
            state['handoff_required'] = graph.active_node is not None
            result = {'completed': True, 'evidence': summary, 'handoff_required': state['handoff_required']}
        else:
            if set(args) != {'code', 'source_lesson'} or not state['public_test_runs']:
                raise ValueError('Finish requires code, source_lesson and an actual public test attempt')
            code, lesson = args['code'], args['source_lesson']
            if not isinstance(code, str) or not code.strip() or len(code.encode()) > state['limits']['code_bytes']:
                raise ValueError('Invalid final source')
            if len(core.canonical(lesson)) > 8000:
                raise ValueError('Lesson exceeds byte budget')
            import trimem_lcb_memory as original_memory
            original_memory._lesson(lesson, state['history'])
            state.update(finished=True, candidate=code, source_lesson=lesson)
            result = {'submitted': True, 'candidate_sha256': hashlib.sha256(code.encode()).hexdigest()}
    except Exception as exc:
        status = 'error'
        result = {'error': type(exc).__name__, 'message': str(exc)[:240] if isinstance(exc, ValueError) else 'Bounded operation failed'}
    elapsed = time.monotonic() - started
    state['tool_seconds'] += elapsed
    if tool != 'finish' and status == 'success':
        from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
        def identity(payload):
            raw = canonical_bytes(payload)
            return {'sha256': sha256_bytes(raw), 'bytes': len(raw)}
        state['history'].append({'task_id': state['task']['task_id'],
            'arm': 'PDF_MEMORY' if state['arm'] == 'ON' else 'BASELINE', 'active_node_id': active_id,
            'step_no': state['step'], 'tool': tool, 'status': status,
            'request_payload': request, 'result_payload': result,
            'request': identity(request), 'result': identity(result), 'wall_time_ms': int(elapsed * 1000)})
    if status == 'error':
        state.setdefault('rejected_actions', []).append({'step': state['step'], 'request': request, 'result': result})
    state['graph'] = graph.snapshot()
    core.write(state_path, state)
    extra = context(state, recall=tool == 'revise_subtask_dag')
    core.write(state_path, state)
    return {'step_no': state['step'], 'status': status, 'result': result,
            'handoff_required': state['handoff_required'], 'finished': state['finished'], 'context': extra}


core.context = context
core.prompt_for = prompt_for
core.worker_command = worker_command
core.solve_cell = solve_cell
core.apply_action = apply_action


def __getattr__(name):
    return getattr(core, name)


if __name__ == '__main__':
    core.main()
