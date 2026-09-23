"""Bounded public-only LiveCodeBench feedback in a fresh Python process.

This is NOT a security sandbox. An empty environment, private working directory,
resource limits, and the official reliability guard do not prevent filesystem
reads or network access by hostile Python. Run only in the authorized disposable
user container. Never put model credentials or private evaluation data in the
worker environment, request, or working directory. No shell command is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

# -I deliberately ignores PYTHONPATH and the caller's current directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trimem_lcb_grade as grader

SCHEMA = 'trimem/lcb-public-test-result/1.0'
REQUEST_SCHEMA = 'trimem/lcb-public-request/1.0'
ISOLATION = 'process_limits_not_security_sandbox'
MAX_SAMPLE_BYTES = 2 * 1024 * 1024
MAX_TEST_CASES = 128
MAX_REPORT_BYTES = 32 * 1024


class PublicInputError(ValueError):
    pass


class PublicBudgetExceeded(PublicInputError):
    pass


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def public_tests_hash(sample):
    """Hash canonical outer JSON + LF; preserve the exact input_output string."""
    grader.validate_sample(sample)
    return _hash(_bytes(sample) + b'\n')


def _write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(_bytes(value))


def _positive(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise PublicInputError(name + ' must be a bounded positive integer')
    return value


def _public_request(task, code, official_repo, *, timeout, workers, max_code_bytes,
                    wall_timeout, memory_limit_mb):
    if not isinstance(task, dict):
        raise PublicInputError('Public task must be an object')
    identity = task.get('task_id', task.get('question_id'))
    if (not isinstance(identity, str) or not identity.strip() or len(identity) > 256
            or task.get('question_id', identity) != identity):
        raise PublicInputError('Public task identity is missing or inconsistent')
    if not isinstance(code, str) or not code.strip() or '\x00' in code:
        raise PublicInputError('Candidate must be nonempty Python source')
    if len(code.encode('utf-8')) > max_code_bytes:
        raise PublicInputError('Candidate exceeds the source byte budget')
    sample = task.get('public_evaluation_sample')
    if len(_bytes(sample)) > MAX_SAMPLE_BYTES:
        raise PublicInputError('Public sample exceeds the byte budget')
    try:
        grader.validate_sample(sample)
        cases = grader.parse_json(sample['input_output'])
    except Exception as exc:
        raise PublicInputError('Invalid public evaluation sample') from exc
    if len(cases['inputs']) > MAX_TEST_CASES:
        raise PublicInputError('Too many public test cases')
    # When the export carries both forms, refuse a mixed public/private sample.
    public_cases = task.get('public_test_cases')
    if public_cases is not None:
        if (not isinstance(public_cases, list)
                or any(not isinstance(row, dict) for row in public_cases)
                or [row.get('input') for row in public_cases] != cases['inputs']
                or [row.get('output') for row in public_cases] != cases['outputs']):
            raise PublicInputError('Evaluation sample differs from declared public cases')
    sample = {'input_output': sample['input_output']}
    # Whitelist fields: no prompt, private-file reference, or caller metadata.
    return {'schema': REQUEST_SCHEMA, 'task_id': identity, 'code': code,
            'sample': sample, 'sample_sha256': public_tests_hash(sample),
            'candidate_sha256': _hash(code.encode('utf-8')),
            'public_test_count': len(cases['inputs']),
            'official_repo': str(Path(official_repo).resolve()),
            'timeout': timeout, 'workers': workers,
            'wall_timeout': wall_timeout, 'memory_limit_mb': memory_limit_mb}


def _reserve(outputdir, request, max_steps, step):
    root = Path(outputdir).absolute()
    if root.is_symlink():
        raise PublicInputError('Public output directory must not be a symlink')
    root.mkdir(parents=True, exist_ok=True)
    scope = {key: request[key] for key in ('task_id', 'sample_sha256', 'official_repo')}
    scope['max_steps'] = max_steps
    scope_path = root / 'scope.json'
    try:
        _write(scope_path, scope)
    except FileExistsError:
        if scope_path.is_symlink() or grader.parse_json(scope_path.read_bytes()) != scope:
            raise PublicInputError('Public session scope or budget changed')
    if step is not None:
        _positive(step, 'step', max_steps)
    for index in range(1, max_steps + 1):
        if step is not None and index != step:
            continue
        directory = root / ('step-%04d' % index)
        try:
            directory.mkdir()
            return directory, index
        except FileExistsError:
            continue
    raise PublicBudgetExceeded('Public execution budget exhausted or step already used')


def _environment(directory, *, temporary=None):
    home = directory / 'home'
    home.mkdir()
    if temporary is None:
        temporary = directory / 'tmp'
        temporary.mkdir()
    environment = {
        'PATH': os.pathsep.join((str(Path(sys.executable).parent), os.defpath)),
        'HOME': str(home), 'TMPDIR': str(temporary), 'TEMP': str(temporary), 'TMP': str(temporary),
        'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8',
        'PYTHONNOUSERSITE': '1', 'HF_DATASETS_OFFLINE': '1', 'HF_HUB_OFFLINE': '1',
        'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_TERMINAL_PROMPT': '0',
    }
    if os.name == 'nt' and 'SystemRoot' in os.environ:
        environment['SystemRoot'] = os.environ['SystemRoot']
    return environment


def _terminate_group(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()


def _launch(request_path, result_path, request_hash, directory, wall_timeout):
    command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker',
               '--request', str(request_path), '--request-sha256', request_hash,
               '--result', str(result_path)]
    # Multiprocessing.Manager binds an AF_UNIX socket below TMPDIR. A normal
    # artifact path (especially /mnt/c/...) can exceed the 108-byte socket limit.
    with tempfile.TemporaryDirectory(prefix='lcbpub-', dir='/tmp' if os.name == 'posix' else None) as temp:
        return _launch_with_temp(command, directory, wall_timeout, Path(temp))


def _launch_with_temp(command, directory, wall_timeout, temporary):
    with open(os.devnull, 'wb') as quiet:
        process = subprocess.Popen(command, cwd=directory, env=_environment(directory, temporary=temporary),
            stdin=subprocess.DEVNULL, stdout=quiet, stderr=quiet, shell=False,
            close_fds=True, start_new_session=(os.name == 'posix'))
        try:
            return process.wait(timeout=wall_timeout), False
        except subprocess.TimeoutExpired:
            _terminate_group(process)
            process.wait(timeout=10)
            return process.returncode, True
        finally:
            # Reap the entire session, including a child left by candidate code.
            _terminate_group(process)


def _resource_limits(request):
    if os.name != 'posix':
        raise PublicInputError('Public worker requires a native POSIX environment')
    import resource
    limits = {'RLIMIT_CORE': 0, 'RLIMIT_CPU': request['wall_timeout'] + 1,
              'RLIMIT_AS': request['memory_limit_mb'] * 1024 * 1024,
              'RLIMIT_FSIZE': MAX_SAMPLE_BYTES * 2, 'RLIMIT_NOFILE': 128}
    for name, value in limits.items():
        key = getattr(resource, name)
        _, hard = resource.getrlimit(key)
        bound = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(key, (bound, bound))
    return limits


def _worker(request_path, request_hash, result_path):
    raw = Path(request_path).read_bytes()
    if _hash(raw) != request_hash:
        raise PublicInputError('Public request checksum changed')
    request = grader.parse_json(raw)
    if request.get('schema') != REQUEST_SCHEMA:
        raise PublicInputError('Unknown public worker request')
    _resource_limits(request)
    with grader.quiet_grader():
        runtime = grader.load_official_runtime(request['official_repo'], raw_rows=False)
    with grader.quiet_grader():
        code = runtime.extract('```python\n' + request['code'] + '\n```', runtime.style)
        if not isinstance(code, str):
            raise grader.GraderContractError('Official extractor returned no source string')
        output = runtime.metrics([request['sample']], [[code]], k_list=[1],
            num_process_evaluate=request['workers'], timeout=request['timeout'], debug=False)
        outcome = _official_counts(output, request['public_test_count'])
    grader.verify_checkout(runtime.root)
    if (grader.validate_module_origins(runtime.root) != runtime.references
            or _hash(Path(request_path).read_bytes()) != request_hash):
        raise PublicInputError('Public inputs or official runtime changed while grading')
    result = {'schema': SCHEMA, 'request_sha256': request_hash,
              'task_id': request['task_id'], **outcome,
              'candidate_sha256': request['candidate_sha256'],
              'sample_sha256': request['sample_sha256'],
              'upstream_commit': grader.UPSTREAM_COMMIT}
    _write(result_path, result)
    return 2 if outcome['status'] == 'INFRA_ERROR' else 0


def _official_counts(output, count):
    passed = grader.official_passes(output, 1)[0]
    metadata = output[2][0][0]
    metadata = grader.parse_json(metadata) if isinstance(metadata, str) else metadata
    error_code = metadata.get('error_code')
    if passed is None:
        return {'status': 'INFRA_ERROR', 'passed': None, 'passed_count': 0,
                'failed_count': 0, 'not_run_count': count, 'error_type': 'TestRunnerError',
                'failure_kind': 'INFRA_ERROR', 'assertion_failures': 0}
    results = output[1]
    if (not isinstance(results, dict) or len(results) != 1
            or (0 in results) == ('0' in results)):
        raise grader.GraderContractError('Official raw task results are missing or ambiguous')
    generations = results[0] if 0 in results else results['0']
    if (not isinstance(generations, list) or len(generations) != 1
            or not isinstance(generations[0], list) or not 1 <= len(generations[0]) <= count):
        raise grader.GraderContractError('Official raw public case results differ')
    values = []
    for value in generations[0]:
        # Official harness may return NumPy scalars before serializing its result.
        if type(value).__module__.split('.')[0] == 'numpy' and hasattr(value, 'item'):
            value = value.item()
        if type(value) not in (bool, int, float) or value not in (True, False, -1, -2, -3, -4):
            raise grader.GraderContractError('Unknown official public case result')
        values.append(value == 1)
    successes = sum(values)
    failures = len(values) - successes
    if passed != (successes == count) or (not passed and not failures):
        raise grader.GraderContractError('Official aggregate and case outcomes disagree')
    # Exact mapping of the pinned testing_util.py. Its outer catch also reports
    # syntax/compilation failures as -4; do not infer a finer category from text.
    categories = {-2: 'WRONG_ANSWER', -3: 'TIMEOUT', -4: 'RUNTIME_ERROR'}
    if (passed and error_code is not None) or (not passed and error_code not in categories):
        raise grader.GraderContractError('Official public failure metadata is inconsistent')
    failure_kind = None if passed else categories[error_code]
    return {'status': 'PASS' if passed else 'FAIL', 'passed': passed,
            'passed_count': successes, 'failed_count': failures, 'not_run_count': count - len(values),
            'failure_kind': failure_kind,
            'assertion_failures': failures if failure_kind == 'WRONG_ANSWER' else 0}


def _checked_result(path, request, request_hash, returncode):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_REPORT_BYTES:
        raise PublicInputError('Invalid public worker report')
    result = grader.parse_json(path.read_bytes())
    expected = {'schema': SCHEMA, 'request_sha256': request_hash,
        'task_id': request['task_id'], 'candidate_sha256': request['candidate_sha256'],
        'sample_sha256': request['sample_sha256'], 'upstream_commit': grader.UPSTREAM_COMMIT}
    if (not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items())
            or set(result) - set(expected) - {'status', 'passed', 'error_type',
                                             'passed_count', 'failed_count', 'not_run_count',
                                             'failure_kind', 'assertion_failures'}):
        raise PublicInputError('Public worker report does not match this request')
    counts = {key: result.get(key) for key in ('passed_count', 'failed_count', 'not_run_count')}
    if (any(type(value) is not int or value < 0 for value in counts.values())
            or sum(counts.values()) != request['public_test_count']):
        raise PublicInputError('Invalid public case counts')
    failure = result.get('failure_kind')
    assertions = result.get('assertion_failures')
    if (type(assertions) is not int or assertions < 0
            or assertions != (counts['failed_count'] if failure == 'WRONG_ANSWER' else 0)):
        raise PublicInputError('Invalid public assertion failure count')
    if result.get('status') in {'PASS', 'FAIL'}:
        passing = result['status'] == 'PASS'
        if (returncode != 0 or type(result.get('passed')) is not bool
                or result['passed'] != passing or 'error_type' in result
                or (passing and counts['passed_count'] != request['public_test_count'])
                or (passing and failure is not None)
                or (not passing and (not counts['failed_count']
                    or failure not in {'WRONG_ANSWER', 'TIMEOUT', 'RUNTIME_ERROR'}))):
            raise PublicInputError('Public worker returned inconsistent success')
        return {'status': result['status'], 'passed': result['passed'], **counts,
                'failure_kind': failure, 'assertion_failures': assertions}
    if (returncode == 0 or result.get('status') != 'INFRA_ERROR' or result.get('passed') is not None
            or failure != 'INFRA_ERROR'
            or not isinstance(result.get('error_type'), str)
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', result['error_type'])):
        raise PublicInputError('Public worker returned an invalid failure')
    return {'status': 'INFRA_ERROR', 'passed': None, 'error_type': result['error_type'], **counts,
            'failure_kind': failure, 'assertion_failures': assertions}


def run_public(task_public_payload, code, official_repo, outputdir, *, timeout=6,
               wall_timeout=180, workers=1, max_code_bytes=65536, step=None, max_steps=8,
               memory_limit_mb=2048):
    """Execute one public-only attempt; outputdir is a broker-owned per-task session.

    Attempts consume atomically reserved slots, including failed/timed-out runs.
    Invalid inputs and exhausted budgets raise PublicInputError. Evaluator/worker
    failures return INFRA_ERROR with passed=None, never an ordinary wrong answer.
    Candidate source is plain Python, not Markdown. Feedback contains no examples,
    code, raw stdout/stderr, source prompt, filesystem paths, or hidden-test data.
    """
    for value, name, maximum in ((timeout, 'timeout', 120), (wall_timeout, 'wall_timeout', 600),
            (workers, 'workers', 4), (max_code_bytes, 'max_code_bytes', 1024 * 1024),
            (max_steps, 'max_steps', 1000), (memory_limit_mb, 'memory_limit_mb', 65536)):
        _positive(value, name, maximum)
    if wall_timeout < timeout:
        raise PublicInputError('Wall timeout must cover the per-test timeout')
    request = _public_request(task_public_payload, code, official_repo, timeout=timeout,
        workers=workers, max_code_bytes=max_code_bytes, wall_timeout=wall_timeout,
        memory_limit_mb=memory_limit_mb)
    directory, index = _reserve(outputdir, request, max_steps, step)
    request_path, result_path = directory / 'request.json', directory / 'worker-result.json'
    _write(request_path, request)
    request_hash = _hash(_bytes(request))
    started = time.monotonic()
    returncode, timed_out = None, False
    try:
        returncode, timed_out = _launch(request_path, result_path, request_hash, directory, wall_timeout)
        if timed_out:
            outcome = {'status': 'INFRA_ERROR', 'passed': None, 'error_type': 'WorkerWallTimeout'}
        else:
            outcome = _checked_result(result_path, request, request_hash, returncode)
    except Exception as exc:
        outcome = {'status': 'INFRA_ERROR', 'passed': None, 'error_type': type(exc).__name__}
    outcome.setdefault('passed_count', 0)
    outcome.setdefault('failed_count', 0)
    outcome.setdefault('not_run_count', request['public_test_count'])
    outcome.setdefault('failure_kind', 'INFRA_ERROR')
    outcome.setdefault('assertion_failures', 0)
    feedback = {'schema': SCHEMA, 'task_id': request['task_id'], **outcome,
        'candidate_sha256': request['candidate_sha256'], 'public_tests_sha256': request['sample_sha256'],
        'command': ['lcb_public_tests', request['task_id'], request['sample_sha256']],
        'test_count': request['public_test_count'], 'step': index, 'max_steps': max_steps,
        'exit_code': (0 if outcome['status'] == 'PASS' else 1 if outcome['status'] == 'FAIL' else returncode),
        'worker_exit_code': returncode, 'timed_out': timed_out,
        'wall_seconds': time.monotonic() - started, 'timeout_seconds': timeout,
        'wall_timeout_seconds': wall_timeout, 'isolation': ISOLATION,
        'security_sandbox': False, 'model_calls': 0, 'private_evaluation_inputs_supplied': False,
        'upstream_commit': grader.UPSTREAM_COMMIT}
    _write(directory / 'feedback.json', feedback)
    return feedback


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'run':
        parser = argparse.ArgumentParser(description='Run only the supplied public examples')
        parser.add_argument('--request', type=Path, required=True)
        parser.add_argument('--official-repo', type=Path, required=True)
        parser.add_argument('--output-dir', type=Path, required=True)
        args = parser.parse_args(argv[1:])
        try:
            if args.output_dir.exists() or args.output_dir.is_symlink():
                raise PublicInputError('CLI output directory must be new')
            if args.request.stat().st_size > MAX_SAMPLE_BYTES * 4:
                raise PublicInputError('Public CLI request exceeds the byte budget')
            request = grader.parse_json(args.request.read_bytes())
            if (not isinstance(request, dict)
                    or set(request) - {'task_public', 'code', 'step', 'max_steps'}
                    or not {'task_public', 'code'}.issubset(request)):
                raise PublicInputError('Invalid public CLI request')
            feedback = run_public(request['task_public'], request['code'], args.official_repo,
                args.output_dir, step=request.get('step'), max_steps=request.get('max_steps', 8))
            _write(args.output_dir / 'publicfeedback.json', feedback)
            print(_bytes(feedback).decode('utf-8'))
            return 2 if feedback['status'] == 'INFRA_ERROR' else 0
        except Exception as exc:
            print(json.dumps({'schema': SCHEMA, 'status': 'INFRA_ERROR', 'passed': None,
                              'failure_kind': 'INFRA_ERROR', 'error_type': type(exc).__name__}))
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return _worker(args.request, args.request_sha256, args.result)
    except Exception:
        # Do not serialize exception messages: they can contain test values.
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
