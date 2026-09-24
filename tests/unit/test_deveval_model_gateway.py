"""Fake HTTP/native transports only; no models, CLI, secrets, or network calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_model_gateway as gateway
import trimem_lcb_native as core


def cell(tmp_path, name='cell', *, provider='vllm'):
    path = tmp_path / name
    path.mkdir()
    (path / 'worker').mkdir()
    runtime = {'native': {'codex_executable': 'NEVER_RUN', 'model': 'synthetic-glm', 'reasoning_effort': 'low'}}
    if provider == 'vllm':
        runtime['gateway'] = {'provider': 'vllm', 'base_url': 'http://synthetic.invalid/v1',
            'model': 'synthetic-glm', 'api_key_env': 'SYNTHETIC_GATEWAY_KEY', 'timeout_seconds': 30}
    state = {'task': {'task_id': name}, 'arm': 'OFF', 'runtime': runtime,
        'graph': {}, 'history': [], 'step': 0, 'public_test_runs': 0,
        'tool_seconds': 0, 'finished': False, 'handoff_required': False, 'session': 0,
        'limits': dict(core.LIMITS), 'candidate': '', 'source_lesson': None,
        'memory_injections': [], 'started_epoch': time.time()}
    gateway.write(path / 'state.json', state)
    return path


def action(tool='finish', **arguments):
    return {'tool': tool, 'arguments': arguments or {'code': 'print("합계")\n'}}


def handler(calls):
    def apply(path, request, *, expected_session):
        state = gateway.read(path / 'state.json')
        assert state['session'] == expected_session
        state['step'] += 1
        calls.append(deepcopy(request))
        valid = bool(request)
        if request.get('tool') == 'finish':
            state.update(finished=True, candidate=request['arguments']['code'])
        if request.get('tool') == 'complete_subtask':
            state['handoff_required'] = True
        result = {'step_no': state['step'], 'status': 'success' if valid else 'error',
                  'result': {'submitted': state['finished']}, 'handoff_required': state['handoff_required'],
                  'finished': state['finished'], 'context': {'synthetic': '공개'}}
        gateway.write(path / 'state.json', state)
        return result
    return apply


class Response:
    status = 200
    def __init__(self, value): self.raw = gateway.canonical(value)
    def read(self, limit): return self.raw[:limit]
    def __enter__(self): return self
    def __exit__(self, *args): pass


def reply(value, index=1):
    return {'id': 'server-response-%d' % index, 'model': 'synthetic-glm',
        'choices': [{'message': {'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False)
                     if isinstance(value, dict) else value}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


@pytest.fixture(autouse=True)
def deny_unmocked_network_and_cli(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_GATEWAY_KEY', 'synthetic-secret-do-not-record')
    def forbidden(*args, **kwargs): pytest.fail('Test attempted real network or native CLI')
    monkeypatch.setattr(gateway, '_http_post', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def test_vllm_utf8_real_exchange_proof_usage_and_no_logged_key(tmp_path, monkeypatch):
    path, calls, requests = cell(tmp_path), [], []
    def post(request, timeout):
        requests.append(request)
        assert timeout <= 30 and request.full_url.endswith('/v1/chat/completions')
        assert request.get_header('Authorization') == 'Bearer synthetic-secret-do-not-record'
        assert '질문'.encode() in request.data
        assert 'tools' not in json.loads(request.data)
        return Response(reply(action()))
    monkeypatch.setattr(gateway, '_http_post', post)
    result = gateway.solve_vllm(path, prompt_for=lambda state: '공개 질문', apply_action=handler(calls))
    assert result['status'] == 'SUBMITTED' and result['tool_actions'] == 1 and len(requests) == 1
    session = result['sessions'][0]
    assert session['thread_ids'] == [] and session['response_ids'] == ['server-response-1']
    assert session['usage'][0]['total_tokens'] == 15
    exchange = gateway.read(path / 'session-01/http-001/action.json')
    assert exchange['type'] == 'gateway.action.completed' and exchange['request'] == calls[0]
    for name in ('http_request_reference', 'http_response_reference', 'http_receipt_reference'):
        assert gateway.reference(exchange[name]['path']) == exchange[name]
    response = gateway.read(exchange['http_response_reference']['path'])
    assert json.loads(response['choices'][0]['message']['content']) == exchange['request']
    assert exchange['response_sha256'] == gateway.sha(gateway.canonical(exchange['response']))
    assert not any(b'synthetic-secret-do-not-record' in p.read_bytes() for p in path.rglob('*') if p.is_file())


def test_invalid_model_json_is_charged_once_then_model_can_correct(tmp_path, monkeypatch):
    path, calls, requests = cell(tmp_path), [], []
    answers = ['```json\n{"tool":"finish"}\n```', action()]
    def post(request, timeout):
        requests.append(json.loads(request.data))
        return Response(reply(answers[len(requests) - 1], len(requests)))
    monkeypatch.setattr(gateway, '_http_post', post)
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'synthetic', apply_action=handler(calls))
    assert result['status'] == 'SUBMITTED' and calls[0] == {} and len(calls) == 2
    assert result['tool_actions'] == 2 and result['sessions'][0]['http_requests'] == 2
    assert gateway.read(path / 'session-01/http-001/action.json')['action_parse_error'] == 'INVALID_MODEL_ACTION'
    assert requests[1]['messages'][-1]['role'] == 'user'


def test_handoff_resets_messages_and_retains_actual_session_count(tmp_path, monkeypatch):
    path, calls, bodies = cell(tmp_path), [], []
    answers = [action('complete_subtask', evidence='synthetic'), action()]
    def post(request, timeout):
        bodies.append(json.loads(request.data))
        return Response(reply(answers[len(bodies) - 1], len(bodies)))
    monkeypatch.setattr(gateway, '_http_post', post)
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'session %d' % state['session'], apply_action=handler(calls))
    assert result['status'] == 'SUBMITTED' and len(result['sessions']) == 2
    assert [len(body['messages']) for body in bodies] == [2, 2]
    assert bodies[1]['messages'][1]['content'] == 'session 2'


def test_http_failure_is_once_metadata_only_and_resume_refused(tmp_path, monkeypatch):
    path, calls, attempts = cell(tmp_path), [], []
    def post(request, timeout):
        attempts.append(1)
        raise HTTPError(request.full_url, 503, 'synthetic-secret-do-not-record', {}, io.BytesIO(b'private-body'))
    monkeypatch.setattr(gateway, '_http_post', post)
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'synthetic', apply_action=handler(calls))
    assert result['status'] == 'GENERATION_ERROR' and result['error_type'] == 'HTTP_OR_RESPONSE_ERROR'
    assert attempts == [1] and calls == []
    receipt = gateway.read(path / 'session-01/http-001/receipt.json')
    assert receipt['http_status'] == 503 and receipt['automatic_retries'] == 0
    assert not any(b'synthetic-secret-do-not-record' in p.read_bytes() for p in path.rglob('*') if p.is_file())
    with pytest.raises(gateway.GatewayError, match='NO_RETRY'):
        gateway.solve_vllm(path, prompt_for=lambda state: 'unused', apply_action=handler(calls))


def test_source_hook_runs_before_every_http_call(tmp_path, monkeypatch):
    path, calls, attempts, guards = cell(tmp_path), [], [], []
    def post(request, timeout):
        attempts.append(1)
        return Response(reply(action('read_file', path='public.py')))
    def guard():
        guards.append(1)
        if len(guards) == 2: raise RuntimeError('synthetic source changed')
    monkeypatch.setattr(gateway, '_http_post', post)
    with pytest.raises(RuntimeError, match='source changed'):
        gateway.solve_vllm(path, prompt_for=lambda state: 'synthetic', apply_action=handler(calls), before_model_call=guard)
    assert attempts == [1] and len(calls) == 1
    assert not (path / 'solve-receipt.json').exists()


def test_budget_stops_before_extra_http_call(tmp_path, monkeypatch):
    path, calls, attempts = cell(tmp_path), [], []
    state = gateway.read(path / 'state.json'); state['limits']['tool_actions'] = 2
    gateway.write(path / 'state.json', state)
    def post(request, timeout):
        attempts.append(1)
        return Response(reply(action('read_file', path='public.py')))
    monkeypatch.setattr(gateway, '_http_post', post)
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'synthetic', apply_action=handler(calls))
    assert result['error_type'] == 'ActionCallBudgetExceeded' and len(attempts) == len(calls) == 2


def test_hook_consuming_deadline_prevents_http_call(tmp_path, monkeypatch):
    path = cell(tmp_path)
    clock = [gateway.read(path / 'state.json')['started_epoch']]
    monkeypatch.setattr(gateway.time, 'time', lambda: clock[0])
    def expire():
        clock[0] += 700
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'unused', apply_action=handler([]), before_model_call=expire)
    assert result['error_type'] == 'TaskTimeout' and result['sessions'][0]['http_requests'] == 0


@pytest.mark.parametrize('mutation,error', [('tool_calls', 'INVALID_CHAT_CONTENT'),
                                          ('bytes', 'HTTP_RESPONSE_BYTES_EXCEEDED')])
def test_unsupported_or_oversized_http_response_never_reaches_handler(tmp_path, monkeypatch, mutation, error):
    path, calls = cell(tmp_path), []
    value = reply(action())
    if mutation == 'tool_calls':
        value['choices'][0]['message']['tool_calls'] = [{'synthetic': True}]
    else:
        state = gateway.read(path / 'state.json')
        state['runtime']['gateway']['max_response_bytes'] = 20
        gateway.write(path / 'state.json', state)
    monkeypatch.setattr(gateway, '_http_post', lambda request, timeout: Response(value))
    result = gateway.solve_vllm(path, prompt_for=lambda state: 'synthetic', apply_action=handler(calls))
    assert result['error_type'] == error and calls == []


@pytest.mark.parametrize('value', [None, [], {'tool': 'shell', 'arguments': {}},
    {'tool': 'finish', 'arguments': {}, 'extra': 1}, {'tool': 'finish', 'arguments': 'wrong'}])
def test_action_protocol_rejects_non_bounded_shape(value):
    with pytest.raises(gateway.GatewayError, match='INVALID_MODEL_ACTION'):
        gateway.validate_action(value)


@pytest.mark.parametrize('url', ['file:///secret', 'https://user:secret@example.test/v1',
                                'https://example.test/v1?api_key=secret'])
def test_http_config_rejects_non_http_and_embedded_credentials(tmp_path, url):
    state = gateway.read(cell(tmp_path) / 'state.json')
    state['runtime']['gateway']['base_url'] = url
    with pytest.raises(gateway.GatewayError, match='INVALID_VLLM_BASE_URL'):
        gateway._config(state['runtime'])


def native_process_factory(records, barrier=None):
    class FakeProcess:
        returncode = 0
        def __init__(self, command, **kwargs):
            setting = next(arg for arg in command if arg.startswith('mcp_servers.benchmark.args='))
            self.args = json.loads(setting.split('=', 1)[1])
            self.cell = Path(self.args[self.args.index('--cell') + 1])
            records.append((command, kwargs, self.args))
        def communicate(self, prompt, timeout):
            if barrier is not None: barrier.wait(timeout=5)
            state = gateway.read(self.cell / 'state.json')
            state.update(finished=True, candidate='print(2)\n', step=1)
            gateway.write(self.cell / 'state.json', state)
            return b''.join(gateway.canonical(row) for row in [
                {'type': 'thread.started', 'thread_id': 'synthetic-native-' + self.cell.name},
                {'type': 'turn.completed', 'usage': {'input_tokens': 1, 'output_tokens': 2}}]), b''
    return FakeProcess


def test_native_preserves_original_flags_receipts_and_private_module_globals(tmp_path, monkeypatch):
    path, records = cell(tmp_path, provider='native'), []
    broker = tmp_path / 'synthetic_broker.py'; broker.write_text('# never executed\n')
    original_prompt, original_worker = core.prompt_for, core.worker_command
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-forward')
    monkeypatch.setattr(subprocess, 'Popen', native_process_factory(records))
    result = gateway.solve_native(path, prompt_for=lambda state: 'UTF8 질문', broker_path=broker)
    assert result['status'] == 'SUBMITTED'
    command, kwargs, args = records[0]
    assert Path(args[0]) == broker and args[-2:] == ['--session', '1']
    for flag in ('--ignore-user-config', '--ephemeral', '--json', '--sandbox'):
        assert flag in command
    assert command[command.index('--sandbox') + 1] == 'read-only'
    assert all(feature in command for feature in core.DISABLED)
    assert 'OPENAI_API_KEY' not in kwargs['env']
    assert core.prompt_for is original_prompt and core.worker_command is original_worker
    receipt = gateway.read(path / 'session-01/prompt-receipt.json')
    assert receipt['prompt_sha256'] == gateway.sha('UTF8 질문'.encode())
    assert receipt['broker_reference'] == gateway.reference(broker)


def test_two_native_solves_cannot_swap_prompt_or_broker_globals(tmp_path, monkeypatch):
    records, barrier = [], threading.Barrier(2)
    monkeypatch.setattr(subprocess, 'Popen', native_process_factory(records, barrier))
    jobs = []
    for name in ('left', 'right'):
        path = cell(tmp_path, name, provider='native')
        broker = tmp_path / (name + '_broker.py'); broker.write_text('# synthetic\n')
        jobs.append((path, broker, name))
    def solve(value):
        path, broker, name = value
        return gateway.solve_native(path, prompt_for=lambda state: name, broker_path=broker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(solve, jobs))
    assert all(result['status'] == 'SUBMITTED' for result in results)
    for path, broker, name in jobs:
        assert (path / 'session-01/prompt.txt').read_text() == name
        assert gateway.read(path / 'session-01/prompt-receipt.json')['broker_reference'] == gateway.reference(broker)


def test_native_source_hook_blocks_before_popen(tmp_path):
    path = cell(tmp_path, provider='native')
    broker = tmp_path / 'broker.py'; broker.write_text('# synthetic\n')
    def guard(): raise RuntimeError('synthetic source changed')
    with pytest.raises(RuntimeError, match='source changed'):
        gateway.solve_native(path, prompt_for=lambda state: 'synthetic', broker_path=broker, before_model_call=guard)
    assert (path / 'gateway-start.json').exists() and not (path / 'solve-receipt.json').exists()
