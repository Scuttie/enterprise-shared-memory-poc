"""Execute model-generated assertions against a sanitized repository copy.

No dataset metadata, reference implementation, or official tests are inputs.
This is a bounded native test runner, not an adversarial security sandbox.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False)
        stream.write('\n')


def child(request_path):
    request = read(request_path)
    workspace = Path(request['workspace']).resolve()
    test_path = Path(request['test_path']).resolve()
    raw = test_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != request['test_sha256']:
        raise ValueError('TEST_BYTES_CHANGED')
    code = raw.decode('utf-8')
    candidate_path = workspace / request['candidate_file']
    if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != request['candidate_file_sha256']:
        raise ValueError('CANDIDATE_FILE_CHANGED')
    module = ast.parse(code, filename=str(test_path))
    assertion_lines = {node.lineno for node in ast.walk(module) if isinstance(node, ast.Assert)}
    if len(assertion_lines) < 2:
        raise ValueError('AT_LEAST_TWO_EXPLICIT_ASSERTIONS_REQUIRED')
    executed_assertions, candidate_lines = set(), set()

    def trace(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == str(test_path) and frame.f_lineno in assertion_lines:
            executed_assertions.add(frame.f_lineno)
        if (event == 'line' and frame.f_code.co_filename == str(candidate_path)
                and request['candidate_body_start'] <= frame.f_lineno <= request['candidate_body_end']):
            candidate_lines.add(frame.f_lineno)
        return trace

    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    outcome = {'status': 'PASS', 'failure_kind': None, 'exception_type': None, 'message': None}
    sys.settrace(trace)
    try:
        exec(compile(module, str(test_path), 'exec'), {'__name__': '__main__', '__file__': str(test_path)})
    except BaseException as error:
        outcome.update(status='FAIL', failure_kind='ASSERTION' if isinstance(error, AssertionError) else 'RUNTIME',
                       exception_type=type(error).__name__, message=str(error)[:512])
    finally:
        sys.settrace(None)
    counts = {'assertions_executed': len(executed_assertions), 'candidate_executed': bool(candidate_lines),
              'candidate_executed_lines': len(candidate_lines)}
    unchanged = hashlib.sha256(candidate_path.read_bytes()).hexdigest() == request['candidate_file_sha256']
    counts['candidate_file_unchanged'] = unchanged
    if not unchanged:
        outcome.update(status='FAIL', failure_kind='CANDIDATE_FILE_MUTATED')
    elif not candidate_lines:
        outcome.update(status='FAIL', failure_kind='CANDIDATE_NOT_EXECUTED')
    elif counts['assertions_executed'] < 2 and outcome['status'] == 'PASS':
        outcome.update(status='FAIL', failure_kind='INSUFFICIENT_ASSERTIONS')
    write(request['child_receipt'], {**outcome, **counts})
    return 0 if outcome['status'] == 'PASS' else 1


def run(request_path):
    request_path = Path(request_path).resolve()
    request = read(request_path)
    folder = request_path.parent
    require_keys = {'workspace', 'test_path', 'test_sha256', 'candidate_sha256', 'task_id', 'method', 'procedure_id', 'timeout_seconds',
                    'candidate_file', 'candidate_file_sha256', 'candidate_body_start', 'candidate_body_end'}
    if set(request) != require_keys or not 1 <= request['timeout_seconds'] <= 60:
        raise ValueError('INVALID_GENERATED_REQUEST')
    candidate_relative = Path(request['candidate_file'])
    if candidate_relative.is_absolute() or '..' in candidate_relative.parts or not (
            type(request['candidate_body_start']) is int and type(request['candidate_body_end']) is int
            and 1 <= request['candidate_body_start'] <= request['candidate_body_end']):
        raise ValueError('INVALID_CANDIDATE_SPAN')
    test_path = Path(request['test_path']).resolve()
    if hashlib.sha256(test_path.read_bytes()).hexdigest() != request['test_sha256']:
        raise ValueError('TEST_BYTES_CHANGED')
    private_request = {**request, 'child_receipt': str(folder / 'child-receipt.json')}
    write(folder / 'child-request.json', private_request)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
    for key in list(env):
        if key.endswith('_API_KEY') or key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
            env.pop(key, None)
    started, timed_out = time.monotonic(), False
    with (folder / 'stdout.log').open('xb') as stdout, (folder / 'stderr.log').open('xb') as stderr:
        process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), 'child',
                                    str(folder / 'child-request.json')], cwd=request['workspace'],
            env=env, stdout=stdout, stderr=stderr, start_new_session=os.name != 'nt',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.wait(timeout=request['timeout_seconds'])
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    result_path = folder / 'child-receipt.json'
    if timed_out:
        result = {'status': 'FAIL', 'failure_kind': 'TIMEOUT', 'assertions_executed': 0, 'candidate_executed': False,
                  'candidate_executed_lines': 0, 'candidate_file_unchanged': False}
    elif result_path.exists():
        result = read(result_path)
        if (result['status'] == 'PASS') != (process.returncode == 0):
            result = {'status': 'INFRA_ERROR', 'failure_kind': 'RECEIPT_EXIT_MISMATCH', 'assertions_executed': 0}
    else:
        # Invalid test syntax/assertion declaration is model feedback, not a proof of repair.
        result = {'status': 'FAIL' if process.returncode else 'INFRA_ERROR',
                  'failure_kind': 'TEST_SETUP_ERROR', 'assertions_executed': 0}
    receipt = {'schema': 'deveval-generated-test/1', **result,
        **{key: request[key] for key in ('task_id', 'candidate_sha256', 'test_sha256', 'method', 'procedure_id')},
        'oracle_scope': 'MODEL_GENERATED_EXPECTATIONS', 'exit_code': process.returncode,
        'timed_out': timed_out, 'elapsed_seconds': time.monotonic() - started,
        'passed': {'PASS': True, 'FAIL': False, 'INFRA_ERROR': None}[result['status']]}
    receipt.setdefault('candidate_executed', False)
    receipt.setdefault('candidate_executed_lines', 0)
    receipt.setdefault('candidate_file_unchanged', False)
    receipt.update({key: request[key] for key in ('candidate_file', 'candidate_file_sha256', 'candidate_body_start', 'candidate_body_end')})
    write(folder / 'receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'child'))
    parser.add_argument('request', type=Path)
    args = parser.parse_args()
    if args.mode == 'child':
        raise SystemExit(child(args.request))
    run(args.request)


if __name__ == '__main__':
    main()
