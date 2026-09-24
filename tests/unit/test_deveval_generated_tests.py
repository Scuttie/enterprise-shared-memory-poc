"""Real standalone subprocesses on synthetic source; no official benchmark."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_generated_tests as generated


def prepare(tmp_path, test_code, *, candidate='def target(value):\n    return value + 1\n', timeout=5):
    workspace = tmp_path / 'repository'; workspace.mkdir()
    source = workspace / 'example.py'; source.write_bytes(candidate.encode())
    tests = tmp_path / 'generated_test.py'; tests.write_bytes(test_code.encode())
    request = {'workspace': str(workspace), 'test_path': str(tests),
        'test_sha256': hashlib.sha256(test_code.encode()).hexdigest(),
        'candidate_sha256': hashlib.sha256(candidate.split('\n', 1)[1].encode()).hexdigest(),
        'task_id': 'synthetic', 'method': 'boundary_cases', 'procedure_id': None, 'timeout_seconds': timeout,
        'candidate_file': 'example.py', 'candidate_file_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
        'candidate_body_start': 2, 'candidate_body_end': len(candidate.splitlines())}
    path = tmp_path / 'request.json'; generated.write(path, request)
    return path, request


def test_actual_candidate_and_two_distinct_assertions_produce_public_pass(tmp_path):
    path, request = prepare(tmp_path, 'from example import target\nassert target(0) == 1\nassert target(2) == 3\n')
    result = generated.run(path)
    assert result['status'] == 'PASS' and result['passed'] is True
    assert result['assertions_executed'] == 2 and result['candidate_executed'] is True
    assert result['candidate_file_unchanged'] is True and result['candidate_executed_lines'] == 1
    assert result['candidate_file_sha256'] == request['candidate_file_sha256']
    assert result['oracle_scope'] == 'MODEL_GENERATED_EXPECTATIONS'


def test_trivial_assertions_without_candidate_execution_do_not_pass(tmp_path):
    path, _ = prepare(tmp_path, 'assert True\nassert True\n')
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'CANDIDATE_NOT_EXECUTED'
    assert result['candidate_executed'] is False and result['assertions_executed'] == 2


def test_assertion_failure_records_actual_candidate_execution(tmp_path):
    path, _ = prepare(tmp_path, 'from example import target\nassert target(0) == 999\nassert target(2) == 3\n')
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'ASSERTION'
    assert result['candidate_executed'] is True and result['assertions_executed'] == 1


def test_repeated_same_assert_line_does_not_count_as_two_distinct_checks(tmp_path):
    path, _ = prepare(tmp_path, 'from example import target\nfor value in (0, 1):\n    assert target(value) == value + 1\nif False:\n    assert False\n')
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'INSUFFICIENT_ASSERTIONS'
    assert result['assertions_executed'] == 1 and result['candidate_executed']


def test_candidate_file_mutation_invalidates_passing_assertions(tmp_path):
    path, _ = prepare(tmp_path, 'from example import target\nassert target(0) == 1\nassert target(2) == 3\nfrom pathlib import Path\nPath("example.py").write_text("# changed")\n')
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'CANDIDATE_FILE_MUTATED'
    assert result['candidate_file_unchanged'] is False


def test_pinned_test_tamper_rejected_before_child_creation(tmp_path):
    path, request = prepare(tmp_path, 'assert True\nassert True\n')
    Path(request['test_path']).write_text('changed')
    with pytest.raises(ValueError, match='TEST_BYTES_CHANGED'):
        generated.run(path)
    assert not (tmp_path / 'child-request.json').exists()


def test_pinned_candidate_tamper_cannot_pass(tmp_path):
    path, request = prepare(tmp_path, 'from example import target\nassert target(0) == 1\nassert target(2) == 3\n')
    (Path(request['workspace']) / 'example.py').write_text('def target(value):\n    return value + 10\n')
    result = generated.run(path)
    assert result['status'] != 'PASS' and not result['candidate_executed']


def test_timeout_is_bounded_nonpassing_feedback(tmp_path):
    path, _ = prepare(tmp_path, 'from example import target\nassert target(0) == 1\nassert target(2) == 3\nwhile True: pass\n', timeout=1)
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'TIMEOUT' and result['timed_out']
