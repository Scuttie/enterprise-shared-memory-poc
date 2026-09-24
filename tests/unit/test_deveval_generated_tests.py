"""Real standalone subprocesses on synthetic source; no official benchmark."""
import hashlib
import importlib.machinery
import json
from pathlib import Path
import sys
from types import ModuleType

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


@pytest.mark.parametrize('layout', ['flat', 'src'])
def test_repository_candidate_wins_over_installed_package_collision(tmp_path, layout):
    fallback = tmp_path / 'simulated-site-packages'
    (fallback / 'owned_package').mkdir(parents=True)
    (fallback / 'owned_package/__init__.py').write_text('def target(value):\n    return 999\n')
    test_code = ('import sys\nsys.path.append(' + repr(str(fallback)) + ')\n'
                 'from owned_package import target\nassert target(0) == 1\nassert target(2) == 3\n')
    path, request = prepare(tmp_path, test_code)
    workspace = Path(request['workspace'])
    candidate = workspace / ('src/owned_package/__init__.py' if layout == 'src' else 'owned_package/__init__.py')
    candidate.parent.mkdir(parents=True)
    (workspace / 'example.py').replace(candidate)
    request['candidate_file'] = candidate.relative_to(workspace).as_posix()
    path.write_text(json.dumps(request))
    result = generated.run(path)
    assert result['status'] == 'PASS' and result['candidate_executed'] is True
    assert result['assertions_executed'] == 2 and result['candidate_file_unchanged'] is True


def test_project_import_cannot_be_redirected_to_external_package(tmp_path):
    fallback = tmp_path / 'simulated-site-packages'; fallback.mkdir()
    marker = tmp_path / 'external-import-executed'
    (fallback / 'example.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
    path, _ = prepare(tmp_path, 'import sys\nsys.path.insert(0, ' + repr(str(fallback)) + ')\n'
                      'import example\nassert True\nassert True\n')
    result = generated.run(path)
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'PROJECT_IMPORT_ISOLATION'
    assert result['exception_type'] == 'ProjectImportError' and not marker.exists()
    assert result['candidate_executed'] is False


def test_preloaded_external_owned_module_is_rejected(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'; workspace.mkdir()
    (workspace / 'preloaded_owned.py').write_text('value = 1\n')
    external = tmp_path / 'outside.py'; external.write_text('value = 2\n')
    module = ModuleType('preloaded_owned')
    module.__spec__ = importlib.machinery.ModuleSpec('preloaded_owned', None, origin=str(external))
    monkeypatch.setitem(sys.modules, 'preloaded_owned', module)
    before = list(sys.path)
    with pytest.raises(generated.ProjectImportError, match='OUTSIDE_SANITIZED'):
        with generated.repository_imports(workspace):
            pytest.fail('A preloaded installed module must not enter the test context')
    assert sys.path == before


def test_owned_submodule_cannot_fall_back_outside_after_candidate_execution(tmp_path):
    fallback = tmp_path / 'installed-package'; fallback.mkdir()
    marker = tmp_path / 'external-submodule-executed'
    (fallback / 'other.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
    code = ('import owned_package\nassert owned_package.target(0) == 1\nassert owned_package.target(2) == 3\n'
            'owned_package.__path__.append(' + repr(str(fallback)) + ')\nimport owned_package.other\n')
    path, request = prepare(tmp_path, code)
    workspace = Path(request['workspace']); candidate = workspace / 'src/owned_package/__init__.py'
    candidate.parent.mkdir(parents=True); (workspace / 'example.py').replace(candidate)
    request['candidate_file'] = candidate.relative_to(workspace).as_posix(); path.write_text(json.dumps(request))
    result = generated.run(path)
    assert result['candidate_executed'] is True and result['assertions_executed'] == 2
    assert result['status'] == 'FAIL' and result['failure_kind'] == 'PROJECT_IMPORT_ISOLATION'
    assert not marker.exists()
