"""Synthetic first-action ablation contracts; every native process is mocked."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import lcb_format_ablation_runner as runner


CODE = '# SYNTHETIC_CANDIDATE_PROSE\nprint(1)\n'
PROSE = 'SYNTHETIC_LESSON_PROSE'
HISTORY = [{'step_no': 1, 'tool': 'run_public_tests', 'status': 'success'}]


def lesson():
    return {'summary': PROSE, 'applicability': PROSE, 'procedure': [PROSE], 'trace_steps': [1]}


def request():
    return {'tool': 'finish', 'arguments': {'code': CODE, 'source_lesson': lesson()}}


def project(value):
    return runner.project(value, HISTORY, runner.sha(CODE.encode()))


def save(path, value):
    Path(path).write_bytes(runner.canonical(value))


@pytest.fixture
def trial(tmp_path):
    root = tmp_path / 'format'
    root.mkdir()
    packet_path, history_path, prompt_path = root / 'packet.json', root / 'history.json', root / 'prompt.txt'
    save(packet_path, {'task_id': 'synthetic-task', 'current_candidate': CODE})
    save(history_path, HISTORY)
    prompt_path.write_text('SYNTHETIC_FORMAT_PROMPT\n', encoding='utf-8')
    item = {'trial_id': 'synthetic-KEEP-1', 'arm': 'KEEP', 'repeat': 1, 'task_id': 'synthetic-task',
        'candidate_sha256': runner.sha(CODE.encode())}
    for name, path in [('packet', packet_path), ('history', history_path), ('prompt', prompt_path)]:
        item[name + '_path'] = path.name
        item[name + '_sha256'] = runner.sha(path.read_bytes())
    protocol = {'requested_model': 'gpt-5.6-luna', 'reasoning_effort': 'low',
        'codex_bin': 'SYNTHETIC_NEVER_EXECUTED', 'timeout_seconds': 180, 'max_parallel': 2, 'trials': [item]}
    save(root / 'protocol.json', protocol)
    runner.initialize(root)
    return SimpleNamespace(root=root, protocol=protocol, item=item,
        folder=root / 'trials' / item['trial_id'])


def launch_placeholder(trial):
    (trial.folder / 'worker').mkdir(parents=True)
    save(trial.folder / 'launch.json', {'synthetic': True})


def fake_process(raw=b'', returncode=0):
    return SimpleNamespace(returncode=returncode, pid=987654,
        communicate=lambda *args, **kwargs: (raw, b''))


def action_events(req):
    return runner.canonical({'type': 'item.completed', 'item': {'type': 'mcp_tool_call',
        'server': 'benchmark', 'tool': 'action', 'arguments': {'request': req}}})


def test_valid_finish_uses_original_lesson_validator():
    result = project(request())
    assert result['submission_valid'] is True
    assert result['anchor_valid'] is True
    assert result['candidate_same'] is True and result['fixed_candidate_success'] is True


def test_anchors_are_independent_of_other_lesson_failures():
    value = request()
    value['arguments']['source_lesson']['summary'] = ''
    result = project(value)
    assert result['anchor_valid'] is True
    assert result['submission_valid'] is False and result['candidate_same'] is True
    assert result['fixed_candidate_success'] is False


def test_anchor_exact_integer_order_membership_rules():
    for anchors in ([], ['1'], [True], [1.0], [2], [1, 1], [2, 1], {'step': 1}):
        value = request()
        value['arguments']['source_lesson']['trace_steps'] = anchors
        outcome = project(value)
        assert outcome['anchor_valid'] is False
        assert outcome['submission_valid'] is False


def test_exact_request_finish_and_lesson_keys():
    mutations = [lambda value: value.update(extra=True),
        lambda value: value['arguments'].update(extra=True),
        lambda value: value['arguments'].pop('code'),
        lambda value: value['arguments']['source_lesson'].update(extra=True),
        lambda value: value['arguments']['source_lesson'].pop('applicability')]
    for mutate in mutations:
        value = request()
        mutate(value)
        assert project(value)['submission_valid'] is False
    assert project({'tool': 'run_public_tests', 'arguments': {'code': CODE}})['submission_valid'] is False


def test_native_aggregate_lesson_limit_counts_utf8_and_final_lf():
    value = request()
    item = value['arguments']['source_lesson']
    item.update(summary='A' * 5000, applicability='B' * 2800, procedure=['C'])
    item['summary'] += 'A' * (8000 - len(runner.canonical(item)))
    assert len(runner.canonical(item)) == 8000
    runner.validator()(item, HISTORY)
    assert project(value)['submission_valid'] is True
    item['summary'] += 'A'
    assert len(runner.canonical(item)) == 8001
    runner.validator()(item, HISTORY)  # All per-field checks still pass.
    assert project(value)['reason'] == 'LESSON_BYTE_LIMIT'
    assert project(value)['anchor_valid'] is True


def test_native_code_byte_limit_and_unchanged_candidate_are_separate():
    for code, expected in [('x' * 65536, True), ('x' * 65537, False),
                            ('한' * 21845 + 'x', True), ('한' * 21846, False), (' \n', False)]:
        value = request()
        value['arguments']['code'] = code
        outcome = project(value)
        assert outcome['submission_valid'] is expected
        assert outcome['candidate_same'] is False
        assert outcome['fixed_candidate_success'] is False
        assert outcome['anchor_valid'] is True


def test_original_field_byte_procedure_limits_are_not_relaxed():
    cases = [('summary', '한' * 2001), ('applicability', '한' * 1001),
             ('procedure', []), ('procedure', ['x'] * 13), ('procedure', ['한' * 501])]
    for name, value in cases:
        req = request()
        req['arguments']['source_lesson'][name] = value
        assert project(req)['submission_valid'] is False
        assert project(req)['anchor_valid'] is True


def test_invalid_first_action_seals_before_later_valid_repair(trial):
    launch_placeholder(trial)
    first = runner.seal_action(trial.root, trial.item['trial_id'], {'tool': 'run_public_tests', 'arguments': {'code': CODE}})
    before = (trial.folder / 'action.json').read_bytes()
    second = runner.seal_action(trial.root, trial.item['trial_id'], request())
    assert first['status'] == 'REJECTED' and second['status'] == 'SEALED_NO_RETRY'
    assert (trial.folder / 'action.json').read_bytes() == before
    assert runner.read(trial.folder / 'action.json')['outcome']['submission_valid'] is False


def test_handshake_does_not_seal_but_malformed_first_action_does(trial):
    launch_placeholder(trial)
    handler = lambda req, envelope: runner.seal_action(trial.root, trial.item['trial_id'], req, raw_envelope=envelope)
    for method in ('initialize', 'ping', 'tools/list'):
        runner.mcp_response({'id': 1, 'method': method}, handler)
        assert not (trial.folder / 'first-action.claim').exists()
    malformed = {'id': 2, 'method': 'tools/call', 'params': {'name': 'action',
        'arguments': {'request': request(), 'extra': 'SYNTHETIC'}}}
    runner.mcp_response(malformed, handler)
    action = runner.read(trial.folder / 'action.json')
    assert action['request_sha256'] == runner.sha(runner.canonical({}))
    assert action['outcome']['submission_valid'] is False
    assert runner.seal_action(trial.root, trial.item['trial_id'], request())['status'] == 'SEALED_NO_RETRY'


def test_competing_calls_have_exactly_one_first_action(trial):
    launch_placeholder(trial)
    requests = [request(), {}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda req: runner.seal_action(trial.root, trial.item['trial_id'], req), requests))
    assert sum(row['status'] == 'SEALED_NO_RETRY' for row in results) == 1
    action = runner.read(trial.folder / 'action.json')
    raw = runner.read(Path(action['raw_request_reference']['path']))
    assert raw['request'] in requests
    assert action['request_sha256'] == runner.sha(runner.canonical(raw['request']))


def test_sealed_action_survives_later_transport_failure_but_missing_action_is_null():
    action = {'outcome': project(request())}
    assert runner.final_metrics(action, infrastructure=True)['submission_valid'] is True
    assert runner.final_metrics(None, infrastructure=True)['submission_valid'] is None
    assert runner.final_metrics(None, infrastructure=False)['submission_valid'] is False
    assert runner.final_metrics(action, infrastructure=True, unexpected=True)['submission_valid'] is False


def test_bound_source_change_before_launch_prevents_process(trial, monkeypatch):
    path = trial.root / 'protocol.json'
    path.write_bytes(path.read_bytes() + b'\n')
    calls = []
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args) or fake_process())
    with pytest.raises(runner.RunnerError):
        runner.start_trial(trial.root, trial.protocol, trial.item, 1)
    assert calls == []


def test_post_launch_source_change_cannot_publish_true(trial, monkeypatch):
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *args, **kwargs: fake_process(action_events(request())))
    attempt = runner.start_trial(trial.root, trial.protocol, trial.item, 1)
    runner.seal_action(trial.root, trial.item['trial_id'], request())
    path = trial.root / 'protocol.json'
    path.write_bytes(path.read_bytes() + b'\n')
    receipt = runner.finish_trial(trial.root, trial.protocol, attempt)
    assert receipt['sources_unchanged_before_after'] is False
    assert receipt['execution_infrastructure_error'] is True
    assert receipt['metrics']['submission_valid'] is None


def test_partial_attempt_has_no_automatic_retry(trial, monkeypatch):
    launch_placeholder(trial)
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: pytest.fail('Partial attempt launched again'))
    with pytest.raises(runner.RunnerError, match='PARTIAL_ATTEMPT_NO_AUTOMATIC_RETRY'):
        runner.reuse(trial.root, trial.item, trial.protocol)
    with pytest.raises(runner.RunnerError, match='PARTIAL_ATTEMPT_NO_AUTOMATIC_RETRY'):
        runner.start_trial(trial.root, trial.protocol, trial.item, 1)


def test_completed_receipt_reuses_without_process_and_tampered_request_is_rejected(trial, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: calls.append(a) or fake_process(action_events(request())))
    attempt = runner.start_trial(trial.root, trial.protocol, trial.item, 1)
    runner.seal_action(trial.root, trial.item['trial_id'], request())
    receipt = runner.finish_trial(trial.root, trial.protocol, attempt)
    assert receipt['first_action_event_confirmed'] is True
    assert runner.reuse(trial.root, trial.item, trial.protocol) == receipt
    assert len(calls) == 1
    raw_path = trial.folder / 'private' / 'first-request.json'
    raw_path.write_bytes(raw_path.read_bytes() + b'\n')
    with pytest.raises(runner.RunnerError, match='BOUND_SOURCE_CHANGED'):
        runner.reuse(trial.root, trial.item, trial.protocol)


def test_worker_route_and_environment_are_restricted(trial, monkeypatch):
    observed = {}
    monkeypatch.setenv('SYNTHETIC_API_KEY', 'MUST_NOT_INHERIT')
    monkeypatch.setenv('OPENAI_API_KEY', 'MUST_NOT_INHERIT')
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda command, **kwargs:
        observed.update(command=command, kwargs=kwargs) or fake_process())
    runner.start_trial(trial.root, trial.protocol, trial.item, 1)
    command = observed['command']
    assert '--ignore-user-config' in command and '--ephemeral' in command
    assert command[command.index('--sandbox') + 1] == 'read-only'
    for feature in runner.DISABLED:
        assert any(command[index:index + 2] == ['--disable', feature] for index in range(len(command) - 1))
    mcp = next(value for value in command if value.startswith('mcp_servers.benchmark.args='))
    args = json.loads(mcp.split('=', 1)[1])
    assert Path(args[0]).resolve() == Path(runner.__file__).resolve()
    assert args[1:] == ['mcp', '--root', str(trial.root), '--trial', trial.item['trial_id']]
    assert 'SYNTHETIC_API_KEY' not in observed['kwargs']['env']
    assert 'OPENAI_API_KEY' not in observed['kwargs']['env']
    assert not observed['kwargs'].get('shell', False)


def test_native_launch_failure_without_action_is_infrastructure_null(trial, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('Synthetic unavailable executable')
    monkeypatch.setattr(runner.subprocess, 'Popen', unavailable)
    attempt = runner.start_trial(trial.root, trial.protocol, trial.item, 1)
    result = runner.finish_trial(trial.root, trial.protocol, attempt)
    assert result['execution_infrastructure_error'] is True
    assert result['metrics']['submission_valid'] is None
    assert result['metrics']['fixed_candidate_success'] is None


def test_action_and_event_metadata_do_not_expose_candidate_or_lesson_prose(trial):
    launch_placeholder(trial)
    runner.seal_action(trial.root, trial.item['trial_id'], request())
    action_raw = (trial.folder / 'action.json').read_text(encoding='utf-8')
    assert PROSE not in action_raw and 'SYNTHETIC_CANDIDATE_PROSE' not in action_raw
    raw = action_events(request()) + runner.canonical({'type': 'item.completed',
        'item': {'type': 'agent_message', 'text': PROSE + CODE}})
    metadata = json.dumps(runner.event_metadata(raw))
    assert PROSE not in metadata and 'SYNTHETIC_CANDIDATE_PROSE' not in metadata


def test_unexpected_tool_before_first_action_disqualifies_its_metric():
    req = request()
    unexpected = runner.canonical({'type': 'item.completed', 'item': {'type': 'command_execution',
        'command': 'SYNTHETIC_NEVER_EXECUTED'}})
    start = runner.canonical({'type': 'item.started', 'item': {'type': 'mcp_tool_call',
        'server': 'benchmark', 'tool': 'action', 'arguments': {'request': req}}})
    action = {'request_sha256': runner.sha(runner.canonical(req)), 'outcome': project(req)}
    metadata = runner.event_metadata(unexpected + start + action_events(req))
    disqualified = runner.unexpected_before_first_action(metadata, action)
    assert disqualified is True
    assert runner.final_metrics(action, unexpected=disqualified)['submission_valid'] is False


def test_later_unexpected_tool_preserves_sealed_metric_but_unknown_order_fails_closed():
    req = request()
    unexpected = runner.canonical({'type': 'item.completed', 'item': {'type': 'command_execution',
        'command': 'SYNTHETIC_NEVER_EXECUTED'}})
    start = runner.canonical({'type': 'item.started', 'item': {'type': 'mcp_tool_call',
        'server': 'benchmark', 'tool': 'action', 'arguments': {'request': req}}})
    action = {'request_sha256': runner.sha(runner.canonical(req)), 'outcome': project(req)}
    metadata = runner.event_metadata(start + action_events(req) + unexpected)
    assert metadata['unexpected_tools']
    disqualified = runner.unexpected_before_first_action(metadata, action)
    assert disqualified is False
    assert runner.final_metrics(action, unexpected=disqualified)['submission_valid'] is True
    unknown = runner.event_metadata(action_events(req) + unexpected)
    assert runner.unexpected_before_first_action(unknown, action) is True
