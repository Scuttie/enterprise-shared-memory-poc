"""Synthetic public-only contract tests; no benchmark, model, or official execution."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import trimem_lcb_public as public


def task():
    return {'task_id': 'synthetic-sum', 'question_id': 'synthetic-sum',
        'prompt': 'This task prompt is not a worker input.',
        'public_test_cases': [{'input': '2 5\n', 'output': '7\n', 'testtype': 'stdin'},
                              {'input': '3 8\n', 'output': '11\n', 'testtype': 'stdin'}],
        'public_evaluation_sample': {'input_output': json.dumps({
            'inputs': ['2 5\n', '3 8\n'], 'outputs': ['7\n', '11\n'], 'fn_name': None})}}


def output(results=(True, True), error_code=None, passed=None):
    if passed is None:
        passed = all(value == 1 for value in results)
    metadata = {} if error_code is None else {'error_code': error_code,
        'inputs': 'NEVER EXPOSE', 'expected': 'NEVER EXPOSE', 'error': 'NEVER EXPOSE'}
    return [{'detail': {'pass@1': {0: float(passed)}}}, {0: [list(results)]},
            [[json.dumps(metadata)]]]


def install_launcher(monkeypatch, *, official=None, mutate=None, returncode=None):
    calls = []
    def launch(request_path, result_path, request_hash, directory, wall_timeout):
        request = public.grader.parse_json(request_path.read_bytes())
        calls.append(request)
        outcome = public._official_counts(official or output(), request['public_test_count'])
        result = {'schema': public.SCHEMA, 'request_sha256': request_hash,
            'task_id': request['task_id'], 'candidate_sha256': request['candidate_sha256'],
            'sample_sha256': request['sample_sha256'],
            'upstream_commit': public.grader.UPSTREAM_COMMIT, **outcome}
        if mutate:
            mutate(result)
        public._write(result_path, result)
        code = 2 if outcome['status'] == 'INFRA_ERROR' else 0
        return (code if returncode is None else returncode), False
    monkeypatch.setattr(public, '_launch', launch)
    return calls


def test_public_hash_preserves_export_string_and_uses_canonical_outer_lf():
    sample = task()['public_evaluation_sample']
    raw = json.dumps(sample, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode() + b'\n'
    assert public.public_tests_hash(sample) == hashlib.sha256(raw).hexdigest()
    altered = {'input_output': json.dumps(json.loads(sample['input_output']), separators=(',', ':'))}
    assert public.public_tests_hash(altered) != public.public_tests_hash(sample)


def test_public_request_whitelists_inputs_and_feedback_never_contains_examples(tmp_path, monkeypatch):
    calls = install_launcher(monkeypatch)
    payload = task()
    payload['private_reference'] = '/secret/grader-file.json'
    payload['model_credential'] = 'SENSITIVE TOKEN'
    result = public.run_public(payload, 'print(7)', tmp_path / 'official', tmp_path / 'session')
    serialized = json.dumps(result)
    assert result['schema'] == 'trimem/lcb-public-test-result/1.0'
    assert result['status'] == 'PASS' and result['passed_count'] == 2
    assert result['failed_count'] == result['not_run_count'] == result['assertion_failures'] == 0
    assert result['test_count'] == 2 and result['failure_kind'] is None
    assert result['security_sandbox'] is False
    for excluded in ('SENSITIVE TOKEN', '/secret/', 'This task prompt', 'print(7)', '2 5', '11\\n'):
        assert excluded not in serialized
    for excluded in ('SENSITIVE TOKEN', '/secret/', 'This task prompt'):
        assert excluded not in json.dumps(calls[0])
    assert set(calls[0]) == {'schema', 'task_id', 'code', 'sample', 'sample_sha256',
        'candidate_sha256', 'public_test_count', 'official_repo', 'timeout', 'workers',
        'wall_timeout', 'memory_limit_mb'}
    assert result['public_tests_sha256'] == public.public_tests_hash(payload['public_evaluation_sample'])


def test_semantic_command_stable_across_real_code_revisions_and_budget_is_persistent(tmp_path, monkeypatch):
    install_launcher(monkeypatch)
    session = tmp_path / 'session'
    first = public.run_public(task(), 'print(0)', tmp_path, session, max_steps=2)
    second = public.run_public(task(), 'print(7)', tmp_path, session, max_steps=2)
    assert first['command'] == second['command']
    assert first['candidate_sha256'] != second['candidate_sha256']
    assert [first['step'], second['step']] == [1, 2]
    with pytest.raises(public.PublicBudgetExceeded):
        public.run_public(task(), 'print(7)', tmp_path, session, max_steps=2)
    with pytest.raises(public.PublicInputError, match='scope or budget'):
        public.run_public(task(), 'print(7)', tmp_path, session, max_steps=3)


@pytest.mark.parametrize('results,code,kind,assertions', [
    ((False,), -2, 'WRONG_ANSWER', 1), ((-2,), -2, 'WRONG_ANSWER', 1),
    ((-3,), -3, 'TIMEOUT', 0), ((-4,), -4, 'RUNTIME_ERROR', 0)])
def test_failures_preserve_upstream_kind_and_unrun_cases(results, code, kind, assertions):
    result = public._official_counts(output(results, code), 2)
    assert result['status'] == 'FAIL'
    assert result['failed_count'] == result['not_run_count'] == 1
    assert result['passed_count'] == 0 and result['failure_kind'] == kind
    assert result['assertion_failures'] == assertions
    assert 'NEVER EXPOSE' not in json.dumps(result)


def test_infrastructure_error_is_not_a_wrong_answer(tmp_path, monkeypatch):
    install_launcher(monkeypatch, official=output((-5,), -5, passed=False))
    result = public.run_public(task(), 'print(7)', tmp_path, tmp_path / 'session')
    assert result['status'] == 'INFRA_ERROR' and result['passed'] is None
    assert result['failed_count'] == result['assertion_failures'] == 0
    assert result['not_run_count'] == 2 and result['error_type'] == 'TestRunnerError'


def test_wrong_answer_has_logical_exit_one_but_successful_worker_transport(tmp_path, monkeypatch):
    install_launcher(monkeypatch, official=output((False,), -2, passed=False))
    result = public.run_public(task(), 'print(0)', tmp_path, tmp_path / 'session')
    assert result['status'] == 'FAIL' and result['exit_code'] == 1
    assert result['worker_exit_code'] == 0 and result['assertion_failures'] == 1


@pytest.mark.parametrize('official', [
    output((True,), passed=True), output((True, False), -2, passed=True),
    output((False,), error_code=None), output((False,), error_code=-99),
    output((float('nan'),), -2, passed=False)])
def test_malformed_or_inconsistent_official_results_fail_closed(official):
    with pytest.raises(public.grader.GraderContractError):
        public._official_counts(official, 2)


@pytest.mark.parametrize('mutate', [
    lambda row: row.update(candidate_sha256='0' * 64),
    lambda row: row.update(passed_count=True),
    lambda row: row.update(passed=False),
    lambda row: row.update(raw_output='sensitive'),
    lambda row: row.update(assertion_failures=1)])
def test_unbound_or_malformed_child_report_is_infrastructure_failure(tmp_path, monkeypatch, mutate):
    install_launcher(monkeypatch, mutate=mutate)
    result = public.run_public(task(), 'print(7)', tmp_path, tmp_path / 'session')
    assert result['status'] == 'INFRA_ERROR' and result['passed'] is None
    assert result['failed_count'] == result['assertion_failures'] == 0


def test_worker_nonzero_exit_cannot_claim_pass(tmp_path, monkeypatch):
    install_launcher(monkeypatch, returncode=2)
    assert public.run_public(task(), 'print(7)', tmp_path, tmp_path / 'session')['status'] == 'INFRA_ERROR'


def test_timeout_consumes_attempt_without_fabricating_failed_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(public, '_launch', lambda *args: (-9, True))
    result = public.run_public(task(), 'print(7)', tmp_path, tmp_path / 'session', max_steps=1)
    assert result['status'] == 'INFRA_ERROR' and result['timed_out'] is True
    assert result['error_type'] == 'WorkerWallTimeout' and result['not_run_count'] == 2
    with pytest.raises(public.PublicBudgetExceeded):
        public.run_public(task(), 'print(7)', tmp_path, tmp_path / 'session', max_steps=1)


def test_invalid_public_sample_or_source_never_launches(tmp_path, monkeypatch):
    calls = install_launcher(monkeypatch)
    invalid = task()
    invalid['public_test_cases'][0]['output'] = 'different'
    with pytest.raises(public.PublicInputError):
        public.run_public(invalid, 'print(0)', tmp_path, tmp_path / 'session')
    with pytest.raises(public.PublicInputError):
        public.run_public(task(), 'x' * 20, tmp_path, tmp_path / 'session', max_code_bytes=10)
    assert calls == [] and not (tmp_path / 'session').exists()


def test_child_environment_contains_no_caller_secrets_or_proxy_paths(tmp_path, monkeypatch):
    for name in ('OPENAI_API_KEY', 'UPSTAGE_API_KEY', 'AWS_SECRET_ACCESS_KEY',
                 'HTTP_PROXY', 'PYTHONPATH', 'HF_TOKEN', 'PRIVATE_EVAL_PATH'):
        monkeypatch.setenv(name, 'MUST NOT PROPAGATE')
    environment = public._environment(tmp_path)
    assert 'MUST NOT PROPAGATE' not in str(environment)
    assert environment['HOME'] == str(tmp_path / 'home')
    assert environment['HF_HUB_OFFLINE'] == environment['HF_DATASETS_OFFLINE'] == '1'


def test_launch_uses_interpreter_without_shell_and_kills_on_wall_timeout(tmp_path, monkeypatch):
    calls = []
    killed = []
    class Process:
        pid = 123456
        returncode = -9
        attempts = 0
        def wait(self, timeout):
            self.attempts += 1
            if self.attempts == 1:
                raise subprocess.TimeoutExpired('worker', timeout)
            return self.returncode
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return Process()
    monkeypatch.setattr(public.subprocess, 'Popen', spawn)
    monkeypatch.setattr(public, '_terminate_group', lambda proc: killed.append(proc.pid))
    assert public._launch(tmp_path / 'request', tmp_path / 'result', 'a' * 64, tmp_path, 10) == (-9, True)
    command, kwargs = calls[0]
    assert command[:2] == [sys.executable, '-I']
    assert kwargs['shell'] is False and kwargs['close_fds'] is True
    assert kwargs['stdin'] == subprocess.DEVNULL and kwargs['cwd'] == tmp_path
    assert kwargs['env']['TMPDIR'] != str(tmp_path / 'tmp')
    assert not Path(kwargs['env']['TMPDIR']).exists()  # Temporary root cleaned after child exits.
    assert killed


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX multiprocessing socket regression')
def test_long_artifact_path_uses_short_native_temp_for_multiprocessing(tmp_path, monkeypatch):
    directory = tmp_path / ('x' * 100)
    directory.mkdir()
    script = "import multiprocessing; m=multiprocessing.Manager(); m.list([1]); m.shutdown()"
    with public.tempfile.TemporaryDirectory(prefix='lcbpub-', dir='/tmp') as temporary:
        environment = public._environment(directory, temporary=Path(temporary))
        completed = subprocess.run([sys.executable, '-I', '-c', script], env=environment,
            cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    assert completed.returncode == 0, completed.stderr.decode()


def test_worker_delegates_only_public_samples_and_one_generation(tmp_path, monkeypatch):
    request = public._public_request(task(), 'print(7)', tmp_path,
        timeout=3, workers=1, max_code_bytes=1024, wall_timeout=30, memory_limit_mb=2048)
    request_path, result_path = tmp_path / 'request.json', tmp_path / 'result.json'
    public._write(request_path, request)
    calls = []
    def metrics(samples, generations, **kwargs):
        calls.append((samples, generations, kwargs))
        return output()
    runtime = SimpleNamespace(root=tmp_path, references={}, style='synthetic',
        extract=lambda text, style: 'plain candidate', metrics=metrics)
    monkeypatch.setattr(public, '_resource_limits', lambda request: {})
    monkeypatch.setattr(public.grader, 'load_official_runtime', lambda root, raw_rows: runtime)
    monkeypatch.setattr(public.grader, 'verify_checkout', lambda root: root)
    monkeypatch.setattr(public.grader, 'validate_module_origins', lambda root: {})
    assert public._worker(request_path, public._hash(request_path.read_bytes()), result_path) == 0
    assert calls == [([task()['public_evaluation_sample']], [['plain candidate']],
        {'k_list': [1], 'num_process_evaluate': 1, 'timeout': 3, 'debug': False})]
    assert 'input_output' not in result_path.read_text()


def test_cli_writes_only_sanitized_receipt_to_stdout_and_fixed_output(tmp_path, monkeypatch, capsys):
    install_launcher(monkeypatch)
    request = tmp_path / 'cli-request.json'
    public._write(request, {'task_public': task(), 'code': 'print(7)', 'step': 3, 'max_steps': 24})
    destination = tmp_path / 'new-run'
    args = ['run', '--request', str(request), '--official-repo', str(tmp_path),
            '--output-dir', str(destination)]
    assert public.main(args) == 0
    result = public.grader.parse_json(capsys.readouterr().out)
    assert result['step'] == 3 and result['max_steps'] == 24
    assert result == public.grader.parse_json((destination / 'publicfeedback.json').read_bytes())
    assert 'print(7)' not in json.dumps(result)
    assert public.main(args) == 2
    assert public.grader.parse_json(capsys.readouterr().out)['error_type'] == 'PublicInputError'
