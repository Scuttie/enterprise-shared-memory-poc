"""Provider adapters for one bounded, public-only repository agent cell.

Native execution reuses an isolated copy of the unchanged CLI driver. vLLM uses
ordinary Chat Completions HTTP with JSON actions in content, not tool parsing.
The experiment owns action execution and private grading; neither is exposed by
this module. Raw model exchanges stay in the cell; receipts contain metadata.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
NATIVE_SOURCE = ROOT / 'scripts/trimem_lcb_native.py'
SCHEMA = 'deveval/model-gateway/1'
ACTIONS = frozenset(('revise_subtask_dag', 'list_files', 'read_file', 'search',
                     'run_command', 'complete_subtask', 'finish'))
ACTION_BYTES = 262144
HTTP_CONTRACT = ('Return exactly one JSON object with exactly tool and arguments keys. '
    'tool names an available bounded operation and arguments is an object. '
    'Do not use Markdown fences, commentary, parallel calls, or a tools API. '
    'The next user message is the actual action result. Stop only by calling finish.')


class GatewayError(ValueError):
    """Only fixed metadata error codes are safe to surface."""


def require(value, code):
    if not value:
        raise GatewayError(code)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value, *, fresh=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fresh:
        with path.open('xb') as stream:
            stream.write(canonical(value))
    else:
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_bytes(canonical(value))
        temporary.replace(path)


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def _sources(broker_path=None):
    paths = [Path(__file__).resolve(), NATIVE_SOURCE]
    if broker_path is not None:
        paths.append(Path(broker_path).resolve())
    return [reference(path) for path in paths]


def _verify_sources(refs):
    for ref in refs:
        require(reference(ref['path']) == ref, 'GATEWAY_SOURCE_CHANGED')


def _isolated_native():
    # Each solve owns its globals; two worker threads cannot replace one another's
    # prompt callback or broker command, and imported LCB adapters are untouched.
    spec = importlib.util.spec_from_file_location('_deveval_isolated_native', NATIVE_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _claim(cell, provider, refs):
    cell = Path(cell).resolve()
    require((cell / 'state.json').is_file(), 'CELL_NOT_INITIALIZED')
    require(not (cell / 'gateway-start.json').exists() and
            not (cell / 'solve-receipt.json').exists() and
            not any(cell.glob('session-*')), 'PARTIAL_OR_COMPLETED_GATEWAY_NO_RETRY')
    state = read(cell / 'state.json')
    require(state.get('session') == 0 and not state.get('finished'), 'CELL_NOT_FRESH')
    write(cell / 'gateway-start.json', {'schema': SCHEMA, 'provider': provider,
        'state_reference': reference(cell / 'state.json'), 'source_references': refs}, fresh=True)
    return cell


def _gateway_receipt(cell, provider, result, refs):
    value = {'schema': SCHEMA, 'provider': provider, 'task_id': result['task_id'],
        'status': result['status'], 'error_type': result.get('error_type'),
        'source_references': refs, 'solve_reference': reference(cell / 'solve-receipt.json'),
        'sessions': len(result['sessions']), 'tool_actions': result['tool_actions'],
        'model_calls': sum(s.get('http_requests', 1) for s in result['sessions']),
        'billing_cost': None, 'automatic_transport_retries': 0}
    write(cell / 'gateway-receipt.json', value, fresh=True)


def solve_native(cell, *, prompt_for, broker_path, before_model_call=None):
    refs = _sources(broker_path)
    cell = _claim(cell, 'native_codex', refs)
    native = _isolated_native()
    original_worker = native.worker_command
    broker_path = Path(broker_path).resolve()

    def worker(path, state):
        command = original_worker(path, state)
        prefix = 'mcp_servers.benchmark.args='
        indices = [i for i, arg in enumerate(command) if arg.startswith(prefix)]
        require(len(indices) == 1, 'UNEXPECTED_NATIVE_BROKER_SETTING')
        index = indices[0]
        args = json.loads(command[index][len(prefix):])
        require(Path(args[0]).resolve() == NATIVE_SOURCE.resolve(), 'UNEXPECTED_NATIVE_BROKER_SOURCE')
        args[0] = str(broker_path)
        command[index] = prefix + json.dumps(args)
        return command

    def guard():
        if before_model_call is not None:
            before_model_call()
        _verify_sources(refs)
        state = read(cell / 'state.json')
        folder = cell / ('session-%02d' % state['session'])
        write(folder / 'initial-state.json', state, fresh=True)
        prompt = (folder / 'prompt.txt').read_bytes()
        write(folder / 'prompt-receipt.json', {'schema': SCHEMA, 'provider': 'native_codex',
            'task_id': state['task']['task_id'], 'arm': state['arm'], 'session': state['session'],
            'prompt_sha256': sha(prompt), 'prompt_bytes': len(prompt),
            'state_before_call_sha256': reference(folder / 'initial-state.json')['sha256'],
            'command_sha256': sha(canonical(worker(cell, state))),
            'broker_reference': reference(broker_path)}, fresh=True)

    native.prompt_for, native.worker_command = prompt_for, worker
    result = native.solve_cell(cell, before_model_call=guard)
    _verify_sources(refs)
    _gateway_receipt(cell, 'native_codex', result, refs)
    return result


def validate_action(value):
    require(isinstance(value, dict) and set(value) == {'tool', 'arguments'} and
            isinstance(value['tool'], str) and value['tool'] in ACTIONS and
            isinstance(value['arguments'], dict), 'INVALID_MODEL_ACTION')
    require(len(canonical(value)) <= ACTION_BYTES, 'MODEL_ACTION_BYTES_EXCEEDED')
    return value


def _config(runtime):
    value = runtime.get('gateway')
    require(isinstance(value, dict) and value.get('provider') == 'vllm', 'VLLM_CONFIG_REQUIRED')
    allowed = {'provider', 'base_url', 'model', 'api_key_env', 'timeout_seconds', 'max_tokens',
               'temperature', 'max_request_bytes', 'max_response_bytes'}
    require(not set(value) - allowed, 'UNSUPPORTED_GATEWAY_CONFIG')
    url = urlsplit(value.get('base_url', ''))
    require(url.scheme in ('http', 'https') and url.hostname and not url.username and
            not url.password and not url.query and not url.fragment, 'INVALID_VLLM_BASE_URL')
    require(isinstance(value.get('model'), str) and 0 < len(value['model'].encode()) <= 512,
            'INVALID_VLLM_MODEL')
    require(runtime.get('native', {}).get('model') == value['model'], 'RUNTIME_MODEL_IDENTITY_DIFFERS')
    env = value.get('api_key_env')
    require(env is None or isinstance(env, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env),
            'INVALID_API_KEY_ENV_NAME')
    config = {'timeout_seconds': 180, 'max_tokens': 4096, 'temperature': 0,
              'max_request_bytes': 1048576, 'max_response_bytes': 1048576, **value}
    for name in ('timeout_seconds', 'max_tokens', 'max_request_bytes', 'max_response_bytes'):
        require(type(config[name]) is int and config[name] > 0, 'INVALID_GATEWAY_BOUND')
    require(config['timeout_seconds'] <= 600 and config['max_tokens'] <= 65536 and config['max_request_bytes'] <= 4194304 and
            config['max_response_bytes'] <= 4194304, 'GATEWAY_BOUND_EXCEEDED')
    require(type(config['temperature']) in (int, float) and math.isfinite(config['temperature'])
            and 0 <= config['temperature'] <= 2, 'INVALID_TEMPERATURE')
    config['endpoint'] = value['base_url'].rstrip('/') + '/chat/completions'
    return config


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward authentication to a redirected endpoint or silently retry.
        return None


def _http_post(request, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def _usage(value):
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str) and
            type(item) in (int, float) and math.isfinite(item) and item >= 0}


def _http_turn(config, messages, folder, *, remaining):
    require(remaining > 0, 'TaskTimeout')
    payload = {'model': config['model'], 'messages': messages, 'stream': False, 'n': 1,
               'max_tokens': config['max_tokens'], 'temperature': config['temperature']}
    raw = canonical(payload)
    require(len(raw) <= config['max_request_bytes'], 'ModelContextBudgetExceeded')
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'request.json').write_bytes(raw)
    headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}
    key_name = config.get('api_key_env')
    if key_name:
        key = os.environ.get(key_name)
        require(isinstance(key, str) and key and '\r' not in key and '\n' not in key, 'API_KEY_UNAVAILABLE')
        headers['Authorization'] = 'Bearer ' + key
    request = Request(config['endpoint'], data=raw, headers=headers, method='POST')
    started = time.monotonic()
    receipt = {'schema': SCHEMA, 'provider': 'vllm', 'endpoint': config['endpoint'],
        'requested_model': config['model'], 'request_reference': reference(folder / 'request.json'),
        'timeout_seconds': min(remaining, config['timeout_seconds']), 'automatic_retries': 0}
    try:
        with _http_post(request, receipt['timeout_seconds']) as response:
            receipt['http_status'] = response.status
            require(200 <= response.status < 300, 'HTTP_STATUS_ERROR')
            response_raw = response.read(config['max_response_bytes'] + 1)
        require(len(response_raw) <= config['max_response_bytes'], 'HTTP_RESPONSE_BYTES_EXCEEDED')
        (folder / 'response.json').write_bytes(response_raw)
        receipt['response_reference'] = reference(folder / 'response.json')
        response = json.loads(response_raw.decode('utf-8'))
        require(isinstance(response, dict), 'INVALID_CHAT_RESPONSE')
        choices = response.get('choices')
        require(isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict), 'INVALID_CHAT_RESPONSE')
        message = choices[0].get('message', {})
        require(isinstance(message, dict) and not message.get('tool_calls') and
                isinstance(message.get('content'), str), 'INVALID_CHAT_CONTENT')
        receipt.update(status='RECEIVED', response_id=response.get('id'),
            reported_model=response.get('model'), usage=_usage(response.get('usage')),
            finish_reason=choices[0].get('finish_reason'))
        return message['content'], receipt
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
        code = str(exc) if isinstance(exc, GatewayError) else 'HTTP_OR_RESPONSE_ERROR'
        receipt.update(status='INFRA_ERROR', error_type=type(exc).__name__, error_code=code)
        if isinstance(exc, HTTPError):
            receipt['http_status'] = exc.code
        raise GatewayError(code) from None
    finally:
        receipt['elapsed_seconds'] = time.monotonic() - started
        write(folder / 'receipt.json', receipt, fresh=True)


def solve_vllm(cell, *, prompt_for, apply_action, before_model_call=None):
    refs = _sources()
    cell = _claim(cell, 'vllm', refs)
    state_path = cell / 'state.json'
    config = _config(read(state_path)['runtime'])
    sessions, issue = [], None
    while True:
        state = read(state_path)
        if state['finished'] or state['session'] >= state['limits']['sessions']:
            break
        if time.time() >= state['started_epoch'] + state['limits']['task_seconds']:
            issue = 'TaskTimeout'; break
        if state['step'] >= state['limits']['tool_actions']:
            issue = 'ActionCallBudgetExceeded'; break
        state['session'] += 1
        state['handoff_required'] = False
        prompt = prompt_for(state)
        require(isinstance(prompt, str) and len(prompt.encode()) <= state['limits']['prompt_bytes'], 'PROMPT_BYTES_EXCEEDED')
        write(state_path, state)
        number = state['session']
        folder = cell / ('session-%02d' % number)
        folder.mkdir(exist_ok=False)
        (folder / 'prompt.txt').write_bytes(prompt.encode('utf-8'))
        write(folder / 'initial-state.json', state, fresh=True)
        write(folder / 'prompt-receipt.json', {'schema': SCHEMA, 'provider': 'vllm',
            'task_id': state['task']['task_id'], 'arm': state['arm'], 'session': number,
            'prompt_sha256': reference(folder / 'prompt.txt')['sha256'],
            'prompt_bytes': len(prompt.encode('utf-8')),
            'state_before_call_sha256': reference(folder / 'initial-state.json')['sha256'],
            'http_contract_sha256': sha(HTTP_CONTRACT.encode('utf-8')),
            'requested_model': config['model']}, fresh=True)
        messages = [{'role': 'system', 'content': HTTP_CONTRACT}, {'role': 'user', 'content': prompt}]
        logs, turns, usages, response_ids = [], 0, [], []
        while True:
            state = read(state_path)
            if state['finished'] or state['handoff_required']:
                break
            if state['step'] >= state['limits']['tool_actions']:
                issue = 'ActionCallBudgetExceeded'; break
            if before_model_call is not None:
                before_model_call()
            _verify_sources(refs)
            remaining = state['started_epoch'] + state['limits']['task_seconds'] - time.time()
            if remaining <= 0:
                issue = 'TaskTimeout'; break
            turns += 1
            turn_dir = folder / ('http-%03d' % turns)
            try:
                content, receipt = _http_turn(config, messages, turn_dir, remaining=remaining)
            except GatewayError as exc:
                issue = str(exc); break
            usages.append(receipt['usage'])
            if isinstance(receipt.get('response_id'), str):
                response_ids.append(receipt['response_id'])
            if time.time() >= state['started_epoch'] + state['limits']['task_seconds']:
                issue = 'TaskTimeout'; break
            try:
                action = validate_action(json.loads(content))
                action_error = None
            except (ValueError, TypeError):
                action, action_error = {}, 'INVALID_MODEL_ACTION'
            # Invalid model JSON is a real rejected action, charged by the same
            # handler as native malformed requests; never a free transport retry.
            before = state['step']
            result = apply_action(cell, action, expected_session=number)
            after = read(state_path)
            require(after['step'] == before + 1, 'ACTION_HANDLER_BUDGET_MISMATCH')
            exchange = {'type': 'gateway.action.completed', 'schema': SCHEMA, 'provider': 'vllm', 'session': number,
                'http_turn': turns, 'response_id': receipt.get('response_id'),
                'http_receipt_reference': reference(turn_dir / 'receipt.json'),
                'http_request_reference': receipt['request_reference'],
                'http_response_reference': receipt['response_reference'],
                'request': action, 'response': result, 'action_parse_error': action_error,
                'request_sha256': sha(canonical(action)), 'response_sha256': sha(canonical(result))}
            write(turn_dir / 'action.json', exchange, fresh=True)
            logs.append(exchange)
            messages.extend([{'role': 'assistant', 'content': content},
                             {'role': 'user', 'content': canonical(result).decode('utf-8')}])
        (folder / 'events.jsonl').write_bytes(b''.join(canonical(item) for item in logs))
        (folder / 'stderr.log').write_bytes(b'')
        session = {'schema': SCHEMA, 'provider': 'vllm', 'session': number, 'thread_ids': [],
            'response_ids': response_ids, 'requested_model': config['model'], 'usage': usages,
            'http_requests': turns, 'benchmark_action_calls': len(logs), 'error_type': issue,
            'events_sha256': reference(folder / 'events.jsonl')['sha256'],
            'stderr_sha256': sha(b''), 'prompt_sha256': reference(folder / 'prompt.txt')['sha256']}
        write(folder / 'receipt.json', session, fresh=True)
        sessions.append(session)
        if issue or read(state_path)['finished']:
            break
    state = read(state_path)
    _verify_sources(refs)
    result = {'schema': 'trimem/lcb-solve-receipt/1.0', 'provider': 'vllm',
        'task_id': state['task']['task_id'], 'arm': state['arm'],
        'status': 'SUBMITTED' if state['finished'] and not issue else 'GENERATION_ERROR',
        'error_type': issue or (None if state['finished'] else 'SessionBudgetExhausted'),
        'candidate_sha256': sha(state['candidate'].encode()), 'sessions': sessions,
        'tool_actions': state['step'], 'public_test_runs': state['public_test_runs'],
        'wall_seconds': time.time() - state['started_epoch'], 'tool_seconds': state['tool_seconds'],
        'memory_injection_count': len(state['memory_injections']), 'state_sha256': reference(state_path)['sha256']}
    write(cell / 'solve-receipt.json', result, fresh=True)
    _gateway_receipt(cell, 'vllm', result, refs)
    return result
