"""Isolated, first-action-only submission-format ablation (no test/grader tool)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
DISABLED = ('shell_tool', 'unified_exec', 'multi_agent', 'apps', 'plugins', 'browser_use',
            'browser_use_external', 'computer_use', 'image_generation', 'view_image',
            'hooks', 'memories', 'goals', 'shell_snapshot')
SCHEMA = 'trimem/lcb-format-ablation-runner/1.0'


class RunnerError(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise RunnerError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() + b'\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def checked(ref):
    actual = reference(ref['path'])
    require(actual['sha256'] == ref['sha256'] and ('bytes' not in ref or actual['bytes'] == ref['bytes']), 'BOUND_SOURCE_CHANGED')
    return Path(ref['path'])


def atomic(path, value, *, fresh=False):
    path = Path(path)
    if fresh:
        require(not path.exists(), 'IMMUTABLE_OUTPUT_EXISTS')
    temp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    with temp.open('xb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    if fresh:
        require(not path.exists(), 'IMMUTABLE_OUTPUT_EXISTS')
    os.replace(temp, path)


def relative(root, value):
    path = Path(value)
    require(not path.is_absolute() and '..' not in path.parts, 'INPUT_PATH_NOT_RELATIVE')
    target = (root / path).resolve()
    require(target.is_relative_to(root), 'INPUT_PATH_ESCAPES_ROOT')
    cursor = root
    for part in path.parts:
        cursor /= part
        require(not cursor.is_symlink(), 'LINKED_INPUT_NOT_ALLOWED')
    return target


def load_protocol(root):
    root = Path(root).resolve()
    p = read(root / 'protocol.json')
    require(p.get('requested_model') == 'gpt-5.6-luna' and p.get('reasoning_effort') == 'low', 'MODEL_PROTOCOL_CHANGED')
    require(p.get('timeout_seconds') == 180 and p.get('max_parallel') == 2, 'BOUND_PROTOCOL_CHANGED')
    require(isinstance(p.get('codex_bin'), str) and p['codex_bin'], 'CODEX_EXECUTABLE_MISSING')
    require(isinstance(p.get('trials'), list) and p['trials'], 'TRIALS_MISSING')
    ids = []
    for trial in p['trials']:
        identity = trial.get('trial_id')
        require(isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identity), 'INVALID_TRIAL_ID')
        require(trial.get('arm') in ('KEEP', 'DROP') and type(trial.get('repeat')) is int, 'INVALID_TRIAL_ARM')
        require(isinstance(trial.get('task_id'), str), 'TASK_ID_MISSING')
        require(re.fullmatch(r'[a-f0-9]{64}', trial.get('candidate_sha256', '')) is not None, 'CANDIDATE_HASH_MISSING')
        for kind in ('packet', 'prompt', 'history'):
            path = relative(root, trial[kind + '_path'])
            require(sha(path.read_bytes()) == trial[kind + '_sha256'], 'PROTOCOL_INPUT_HASH_CHANGED')
        ids.append(identity)
    require(len(ids) == len(set(ids)), 'DUPLICATE_TRIAL_ID')
    return p


def validator():
    # Import the original validator, without editing its implementation or bank.
    for path in (REPO / 'src', REPO / 'scripts'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import trimem_lcb_memory
    require(Path(trimem_lcb_memory.__file__).resolve() == REPO / 'scripts/trimem_lcb_memory.py', 'WRONG_VALIDATOR_MODULE')
    return trimem_lcb_memory._lesson


def inputs(root, protocol, trial):
    refs = [reference(root / 'protocol.json'), reference(__file__), reference(REPO / 'scripts/trimem_lcb_memory.py')]
    for kind in ('packet', 'prompt', 'history'):
        ref = reference(relative(root, trial[kind + '_path']))
        require(ref['sha256'] == trial[kind + '_sha256'], 'INPUT_CHANGED')
        refs.append(ref)
    history = read(relative(root, trial['history_path']))
    require(isinstance(history, list) and history and all(isinstance(r, dict) and type(r.get('step_no')) is int for r in history), 'HISTORY_MALFORMED')
    require(len({r['step_no'] for r in history}) == len(history), 'HISTORY_DUPLICATE_STEPS')
    require(all(r.get('status') == 'success' for r in history), 'HISTORY_NOT_SUCCESSFUL')
    require(any(r.get('tool') == 'run_public_tests' for r in history), 'PUBLIC_TEST_PRECONDITION_MISSING')
    packet = read(relative(root, trial['packet_path']))
    require(packet.get('task_id') == trial['task_id'], 'PACKET_TASK_CHANGED')
    candidate = packet.get('current_candidate', packet.get('code'))
    require(isinstance(candidate, str) and sha(candidate.encode()) == trial['candidate_sha256'], 'PACKET_CANDIDATE_CHANGED')
    return refs, history


def initialize(root):
    root = Path(root).resolve()
    protocol = load_protocol(root)
    validator()  # Fail before a model call if this environment cannot import it.
    allrefs = {}
    for ref in protocol.get('source_references', []):
        checked(ref)
        allrefs[str(Path(ref['path']).resolve())] = reference(ref['path'])
    if protocol.get('codex_sha256'):
        require(sha(Path(protocol['codex_bin']).read_bytes()) == protocol['codex_sha256'], 'CODEX_BINARY_CHANGED')
        allrefs[str(Path(protocol['codex_bin']).resolve())] = reference(protocol['codex_bin'])
    for trial in protocol['trials']:
        refs, _ = inputs(root, protocol, trial)
        for ref in refs:
            require(ref['path'] not in allrefs or allrefs[ref['path']] == ref, 'SOURCE_AUTHORITY_CONFLICT')
            allrefs[ref['path']] = ref
    binding = {'schema': SCHEMA, 'protocol_reference': reference(root / 'protocol.json'),
               'source_references': list(allrefs.values())}
    path = root / 'run-binding.json'
    if path.exists():
        require(read(path) == binding, 'RUN_BINDING_CHANGED')
    else:
        atomic(path, binding, fresh=True)
    return protocol, binding


def trial_config(root, identity):
    # Avoid re-reading every trial's large packet in the per-call MCP broker.
    binding = read(root / 'run-binding.json')
    checked(binding['protocol_reference'])
    protocol = read(root / 'protocol.json')
    matches = [t for t in protocol['trials'] if t['trial_id'] == identity]
    require(len(matches) == 1, 'TRIAL_NOT_ENROLLED')
    trial = matches[0]
    refs, history = inputs(root, protocol, trial)
    enrolled = {r['path']: r for r in binding['source_references']}
    require(all(enrolled.get(r['path']) == r for r in refs), 'TRIAL_BINDING_CHANGED')
    return protocol, trial, refs, history


def project(request, history, candidate_sha256, *, lesson_validator=None):
    """Independent protocol/anchor/candidate metrics; never return source prose."""
    args = request.get('arguments') if isinstance(request, dict) else None
    lesson = args.get('source_lesson') if isinstance(args, dict) else None
    trace = lesson.get('trace_steps') if isinstance(lesson, dict) else None
    available = {r['step_no'] for r in history}
    anchors = (isinstance(trace, list) and bool(trace) and all(type(v) is int for v in trace)
               and trace == sorted(set(trace)) and set(trace) <= available)
    code = args.get('code') if isinstance(args, dict) else None
    same = isinstance(code, str) and sha(code.encode()) == candidate_sha256
    outcome = {'submission_valid': False, 'candidate_same': same, 'fixed_candidate_success': False,
               'anchor_valid': anchors, 'reason': 'INVALID_REQUEST',
               'trace_steps_container_type': type(trace).__name__,
               'trace_steps_element_types': sorted({type(v).__name__ for v in trace}) if isinstance(trace, list) else [],
               'trace_steps_integer_values': [v for v in trace if type(v) is int] if isinstance(trace, list) else [],
               'available_history_ids': sorted(available)}
    if not isinstance(request, dict) or set(request) != {'tool', 'arguments'} or request.get('tool') != 'finish':
        return outcome
    if not isinstance(args, dict) or set(args) != {'code', 'source_lesson'}:
        outcome['reason'] = 'INVALID_FINISH_KEYS'
        return outcome
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > 65536:
        outcome['reason'] = 'INVALID_CODE'
        return outcome
    if not isinstance(lesson, dict) or set(lesson) != {'summary', 'applicability', 'procedure', 'trace_steps'}:
        outcome['reason'] = 'INVALID_LESSON_KEYS'
        return outcome
    if len(canonical(lesson)) > 8000:
        outcome['reason'] = 'LESSON_BYTE_LIMIT'
        return outcome
    check = lesson_validator or validator()
    try:
        check(lesson, history)
    except ValueError:
        outcome['reason'] = 'LESSON_VALIDATION_REJECTED'
        return outcome
    outcome.update(submission_valid=True, fixed_candidate_success=same, reason='VALID_FINISH')
    return outcome


def seal_action(root, identity, request, *, raw_envelope=None):
    root = Path(root).resolve()
    _, trial, refs, history = trial_config(root, identity)
    folder = root / 'trials' / identity
    require((folder / 'launch.json').is_file(), 'TRIAL_NOT_STARTED')
    claim = folder / 'first-action.claim'
    try:
        with claim.open('xb') as stream:
            stream.write(b'FIRST_ACTION_RESERVED\n')
    except FileExistsError:
        return {'sealed': True, 'finished': True, 'status': 'SEALED_NO_RETRY'}
    private = folder / 'private'
    private.mkdir(exist_ok=True)
    # A separate ignored raw file is authority; action.json is metadata only.
    (private / '.gitignore').write_text('*\n', encoding='utf8', newline='\n')
    raw = {'request': request, 'mcp_arguments': raw_envelope}
    atomic(private / 'first-request.json', raw, fresh=True)
    outcome = project(request, history, trial['candidate_sha256'])
    for ref in refs:
        checked(ref)
    action = {'schema': SCHEMA, 'trial_id': identity, 'task_id': trial['task_id'],
              'first_action_only': True, 'request_sha256': sha(canonical(request)),
              'raw_request_reference': reference(private / 'first-request.json'),
              'input_references': refs, 'outcome': outcome}
    atomic(folder / 'action.json', action, fresh=True)
    return {'sealed': True, 'finished': True, 'status': 'ACCEPTED' if outcome['submission_valid'] else 'REJECTED',
            'submission_valid': outcome['submission_valid'], 'reason': outcome['reason']}


def mcp_response(message, handler):
    if 'id' not in message:
        return None
    response = {'jsonrpc': '2.0', 'id': message['id']}
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        response['result'] = {'protocolVersion': params.get('protocolVersion', '2024-11-05'), 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'lcb-format-broker', 'version': '1.0'}}
    elif method == 'ping':
        response['result'] = {}
    elif method == 'tools/list':
        response['result'] = {'tools': [{'name': 'action', 'description': 'One bounded public benchmark action. Stop after handoff_required or finished.',
            'inputSchema': {'type': 'object', 'properties': {'request': {'type': 'object'}}, 'required': ['request'], 'additionalProperties': False}}]}
    elif method == 'tools/call' and params.get('name') == 'action':
        envelope = params.get('arguments', {})
        request = envelope['request'] if isinstance(envelope, dict) and set(envelope) == {'request'} else {}
        try:
            result = handler(request, envelope)
            response['result'] = {'content': [{'type': 'text', 'text': canonical(result).decode()}], 'isError': False}
        except Exception:
            response['result'] = {'content': [{'type': 'text', 'text': 'Broker infrastructure failure; no retry permitted'}], 'isError': True}
    else:
        response['error'] = {'code': -32601, 'message': 'Method unavailable'}
    return response


def worker_command(root, protocol, trial, folder):
    command = [protocol['codex_bin'], 'exec', '--ignore-user-config', '--ephemeral', '--json',
        '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(folder / 'worker'),
        '-m', protocol['requested_model'], '-c', 'model_reasoning_effort=' + json.dumps(protocol['reasoning_effort']),
        '-c', 'forced_login_method="chatgpt"', '-c', 'web_search="disabled"',
        '-c', 'suppress_unstable_features_warning=true', '--enable', 'skip_host_skill_discovery']
    for feature in DISABLED:
        command += ['--disable', feature]
    settings = {'mcp_servers.benchmark.command': sys.executable,
        'mcp_servers.benchmark.args': [str(Path(__file__).resolve()), 'mcp', '--root', str(root), '--trial', trial['trial_id']],
        'mcp_servers.benchmark.required': True, 'mcp_servers.benchmark.startup_timeout_sec': 60,
        'mcp_servers.benchmark.tool_timeout_sec': 210, 'mcp_servers.benchmark.enabled_tools': ['action'],
        'mcp_servers.benchmark.default_tools_approval_mode': 'auto',
        'mcp_servers.benchmark.tools.action.approval_mode': 'approve'}
    for key, value in settings.items():
        command += ['-c', key + '=' + json.dumps(value)]
    return command + ['-']


def event_metadata(raw):
    calls, unexpected, errors, threads, agent_messages = [], [], 0, [], 0
    starts = []
    malformed = 0
    for line_no, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            malformed += 1
            continue
        if event.get('type') == 'thread.started':
            threads.append(sha(str(event.get('thread_id')).encode()))
        if event.get('type') in ('error', 'turn.failed'):
            errors += 1
        if event.get('type') not in ('item.started', 'item.completed'):
            continue
        item = event.get('item', {})
        kind = item.get('type')
        if kind == 'mcp_tool_call' and item.get('server') == 'benchmark' and item.get('tool') == 'action':
            args = item.get('arguments')
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, UnicodeError):
                    args = None
            request = args['request'] if isinstance(args, dict) and set(args) == {'request'} else {}
            target = starts if event['type'] == 'item.started' else calls
            target.append({'line': line_no, 'event_sha256': sha(line), 'request_sha256': sha(canonical(request))})
            if event['type'] == 'item.completed' and (item.get('status') == 'failed' or item.get('error')):
                errors += 1
        elif kind == 'agent_message':
            agent_messages += int(event['type'] == 'item.completed')
        elif kind == 'error':
            errors += int(event['type'] == 'item.completed')
        elif kind not in ('reasoning', 'todo_list', 'plan_update'):
            unexpected.append({'line': line_no, 'event_sha256': sha(line)})
    return {'benchmark_action_calls': calls, 'benchmark_action_starts': starts, 'unexpected_tools': unexpected, 'error_events': errors,
            'malformed_event_lines': malformed, 'thread_id_hashes': threads, 'agent_message_count': agent_messages}


def final_metrics(action, *, infrastructure=False, unexpected=False):
    if unexpected:
        return {'submission_valid': False, 'candidate_same': action['outcome']['candidate_same'] if action else False,
                'fixed_candidate_success': False, 'anchor_valid': action['outcome']['anchor_valid'] if action else False,
                'classification': 'UNEXPECTED_NATIVE_TOOL'}
    if action:
        return {**{k: action['outcome'][k] for k in ('submission_valid', 'candidate_same', 'fixed_candidate_success', 'anchor_valid')},
                'classification': 'FIRST_ACTION_OBSERVED'}
    return {'submission_valid': None if infrastructure else False, 'candidate_same': None if infrastructure else False,
            'fixed_candidate_success': None if infrastructure else False, 'anchor_valid': None if infrastructure else False,
            'classification': 'INFRASTRUCTURE_NO_ACTION' if infrastructure else 'NO_ACTION'}


def unexpected_before_first_action(metadata, action):
    if not metadata['unexpected_tools']:
        return False
    if action is None:
        return True
    starts = [r['line'] for r in metadata['benchmark_action_starts'] if r['request_sha256'] == action['request_sha256']]
    # Unknown ordering fails closed; a later unexpected action is separately
    # disclosed without replacing the already observed first-action metric.
    return not starts or any(r['line'] < min(starts) for r in metadata['unexpected_tools'])


def checked_action(folder, trial, refs):
    path = folder / 'action.json'
    if not path.exists():
        return None
    action = read(path)
    require(action['trial_id'] == trial['trial_id'] and action['task_id'] == trial['task_id'] and action['input_references'] == refs, 'ACTION_IDENTITY_CHANGED')
    raw = read(checked(action['raw_request_reference']))
    require(action['request_sha256'] == sha(canonical(raw['request'])), 'ACTION_REQUEST_CHANGED')
    history = read(refs[-1]['path'])
    require(action['outcome'] == project(raw['request'], history, trial['candidate_sha256']), 'ACTION_OUTCOME_CHANGED')
    return action


def start_trial(root, protocol, trial, ordinal):
    folder = root / 'trials' / trial['trial_id']
    require(not folder.exists(), 'PARTIAL_ATTEMPT_NO_AUTOMATIC_RETRY')
    bound_protocol, bound_trial, refs, _ = trial_config(root, trial['trial_id'])
    require(bound_protocol == protocol and bound_trial == trial, 'PRELAUNCH_PROTOCOL_CHANGED')
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'worker').mkdir()
    prompt = relative(root, trial['prompt_path']).read_bytes()
    command = worker_command(root, protocol, trial, folder)
    launch = {'schema': SCHEMA, 'trial_id': trial['trial_id'], 'launch_ordinal': ordinal,
              'started_at': datetime.now(timezone.utc).isoformat(), 'input_references': refs,
              'requested_model': protocol['requested_model'], 'reasoning_effort': protocol['reasoning_effort'],
              'stdin_prompt_sha256': sha(prompt), 'command_sha256': sha(canonical(command))}
    atomic(folder / 'launch.json', launch, fresh=True)
    env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'CODEX_API_KEY') and not k.upper().endswith('_API_KEY')}
    kwargs = {'stdin': subprocess.PIPE, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
              'env': env, 'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if os.name != 'nt':
        kwargs['start_new_session'] = True
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError:
        process = None
    return {'folder': folder, 'trial': trial, 'refs': refs, 'launch': launch,
            'process': process, 'prompt': prompt, 'started': started}


def finish_trial(root, protocol, started):
    folder, process = started['folder'], started['process']
    timed_out = False
    if process is None:
        stdout, stderr, returncode = b'', b'Native process launch failed\n', None
    else:
        try:
            stdout, stderr = process.communicate(started['prompt'], timeout=protocol['timeout_seconds'])
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        returncode = process.returncode
    for name, raw in (('events.jsonl', stdout), ('stderr.log', stderr)):
        with (folder / name).open('xb') as stream:
            stream.write(raw)
    metadata = event_metadata(stdout)
    unchanged = True
    try:
        for ref in started['refs']:
            checked(ref)
    except RunnerError:
        unchanged = False
    action = checked_action(folder, started['trial'], started['refs']) if unchanged else None
    infrastructure = (process is None or returncode != 0 or timed_out or metadata['error_events'] > 0
                      or metadata['malformed_event_lines'] > 0 or not unchanged)
    unexpected_before = unexpected_before_first_action(metadata, action)
    metrics = final_metrics(action, infrastructure=infrastructure, unexpected=unexpected_before)
    receipt = {'schema': SCHEMA, 'status': 'DONE', 'trial_id': started['trial']['trial_id'],
               'task_id': started['trial']['task_id'], 'repeat': started['trial']['repeat'], 'arm': started['trial']['arm'],
               'requested_model': protocol['requested_model'], 'reasoning_effort': protocol['reasoning_effort'],
               'launch_ordinal': started['launch']['launch_ordinal'], 'elapsed_seconds': time.monotonic() - started['started'],
               'returncode': returncode, 'timed_out': timed_out, 'execution_infrastructure_error': infrastructure,
               'sources_unchanged_before_after': unchanged, 'metrics': metrics, 'native': metadata,
               'unexpected_native_tool_before_first_action': unexpected_before,
               'first_action_event_confirmed': bool(action and any(c['request_sha256'] == action['request_sha256'] for c in metadata['benchmark_action_calls'])),
               'input_references': started['refs'],
               'output_references': [reference(folder / n) for n in ('launch.json', 'events.jsonl', 'stderr.log')],
               'action_reference': reference(folder / 'action.json') if action else None}
    if action:
        receipt['output_references'].append(action['raw_request_reference'])
    atomic(folder / 'receipt.json', receipt, fresh=True)
    return receipt


def reuse(root, trial, protocol):
    folder = root / 'trials' / trial['trial_id']
    path = folder / 'receipt.json'
    if not folder.exists():
        return None
    require(path.is_file(), 'PARTIAL_ATTEMPT_NO_AUTOMATIC_RETRY')
    receipt = read(path)
    require(receipt.get('status') == 'DONE' and receipt['trial_id'] == trial['trial_id'] and receipt['arm'] == trial['arm'] and receipt['task_id'] == trial['task_id'], 'DONE_IDENTITY_CHANGED')
    refs, _ = inputs(root, protocol, trial)
    require(receipt['input_references'] == refs and receipt['sources_unchanged_before_after'], 'DONE_INPUTS_CHANGED')
    for ref in receipt['output_references']:
        checked(ref)
    action = None
    if receipt['action_reference']:
        checked(receipt['action_reference'])
        action = checked_action(folder, trial, refs)
    require(receipt['native'] == event_metadata((folder / 'events.jsonl').read_bytes()), 'DONE_EVENTS_CHANGED')
    unexpected_before = unexpected_before_first_action(receipt['native'], action)
    require(receipt['unexpected_native_tool_before_first_action'] == unexpected_before, 'DONE_TOOL_ORDER_CHANGED')
    require(receipt['metrics'] == final_metrics(action, infrastructure=receipt['execution_infrastructure_error'], unexpected=unexpected_before), 'DONE_METRICS_CHANGED')
    return receipt


def run(root, *, limit=None):
    root = Path(root).resolve()
    lock = root / 'run.lock'
    try:
        lock.open('xb').close()
    except FileExistsError:
        raise RunnerError('CONTROLLER_ALREADY_LOCKED') from None
    started = time.monotonic()
    try:
        protocol, binding = initialize(root)
        results, pending = {}, []
        terminal_verified = False
        prior_pins = {}
        for name in ('progress.json', 'results.json'):
            if (root / name).exists():
                for row in read(root / name).get('trials', []):
                    prior_pins[row['trial_id']] = row['receipt_reference']
        for ordinal, trial in enumerate(protocol['trials'], 1):
            existing = reuse(root, trial, protocol)
            if existing:
                if trial['trial_id'] in prior_pins:
                    checked(prior_pins[trial['trial_id']])
                results[trial['trial_id']] = existing
            else:
                pending.append((ordinal, trial))
        if limit is not None:
            require(type(limit) is int and limit >= 0, 'INVALID_LIMIT')
            pending = pending[:limit]

        def progress():
            ordered = [results[t['trial_id']] for t in protocol['trials'] if t['trial_id'] in results]
            value = {'schema': SCHEMA, 'status': 'COMPLETE' if len(ordered) == len(protocol['trials']) and terminal_verified else 'IN_PROGRESS',
                     'planned': len(protocol['trials']), 'completed': len(ordered),
                     'elapsed_seconds_this_invocation': time.monotonic() - started,
                     'protocol_reference': binding['protocol_reference'],
                     'trials': [{'trial_id': r['trial_id'], 'task_id': r['task_id'], 'arm': r['arm'], 'repeat': r['repeat'],
                                 'launch_ordinal': r['launch_ordinal'], 'metrics': r['metrics'],
                                 'execution_infrastructure_error': r['execution_infrastructure_error'],
                                 'receipt_reference': reference(root / 'trials' / r['trial_id'] / 'receipt.json')} for r in ordered]}
            atomic(root / 'progress.json', value)
            return value

        progress()
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = {}
            for_fill = iter(pending)
            while True:
                while len(running) < 2:
                    item = next(for_fill, None)
                    if item is None:
                        break
                    ordinal, trial = item
                    attempt = start_trial(root, protocol, trial, ordinal)
                    running[pool.submit(finish_trial, root, protocol, attempt)] = trial
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    trial = running.pop(future)
                    results[trial['trial_id']] = future.result()
                    require(results[trial['trial_id']]['sources_unchanged_before_after'], 'SOURCE_CHANGED_DURING_INVOCATION')
                progress()
        for ref in binding['source_references']:
            checked(ref)
        terminal_verified = True
        result = progress()
        if result['status'] == 'COMPLETE':
            if (root / 'results.json').exists():
                previous = read(root / 'results.json')
                require(previous['trials'] == result['trials'], 'FINAL_RESULTS_CHANGED')
            else:
                atomic(root / 'results.json', result, fresh=True)
        return result
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ('run', 'mcp'):
        p = sub.add_parser(name)
        p.add_argument('--root', type=Path, required=True)
        if name == 'run':
            p.add_argument('--limit', type=int)
        else:
            p.add_argument('--trial', required=True)
    args = parser.parse_args()
    if args.operation == 'run':
        result = run(args.root, limit=args.limit)
        print(json.dumps({k: result[k] for k in ('status', 'planned', 'completed')}))
    else:
        for line in sys.stdin:
            try:
                response = mcp_response(json.loads(line), lambda request, envelope: seal_action(args.root, args.trial, request, raw_envelope=envelope))
            except Exception:
                response = None
            if response is not None:
                print(json.dumps(response), flush=True)


if __name__ == '__main__':
    try:
        main()
    except RunnerError as exc:
        raise SystemExit(str(exc)) from None
