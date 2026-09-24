"""Synthetic private-grade orchestration; no official evaluator execution."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_grade as grade


def setup_run(tmp_path, monkeypatch, *, official='Pass', exit_code=0, timeout=False,
              restored=True, mutate=False, extra=None, emit_receipt=True):
    pristine = tmp_path / 'pristine'
    target = pristine / 'Synthetic/demo/package/module.py'
    target.parent.mkdir(parents=True)
    target.write_text('def target():\n    return "synthetic original"\n')
    folder = tmp_path / 'grade'; folder.mkdir()
    request = {'pristine_source_root': str(pristine), 'project': 'Synthetic/demo',
               'task_id': 'package.module.target', 'candidate_sha256': 'a' * 64}
    path = folder / 'request.json'; grade.assets.write_new(path, request)
    kills, launched = [], []
    fake_os = SimpleNamespace(name='posix', environ=dict(os.environ), pathsep=os.pathsep,
                             killpg=lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(grade, 'os', fake_os)
    monkeypatch.setattr(grade, 'signal', SimpleNamespace(SIGKILL=9))

    class Process:
        pid = 987654321
        def __init__(self, command, **kwargs):
            self.returncode = None
            self.waits = 0
            launched.append({'command': command, **kwargs})
            child = grade.read(command[-1])
            destination = Path(child['source_root']) / request['project']
            if mutate:
                (destination / 'package/module.py').write_text('changed synthetic source')
            if extra:
                extra_path = destination / extra; extra_path.parent.mkdir(parents=True, exist_ok=True)
                extra_path.write_text('synthetic output')
            if emit_receipt:
                grade.assets.write_new(child['child_receipt'], {
                    'schema': 'deveval-private-grade/1', 'task_id': request['task_id'], 'project': request['project'],
                    'candidate_sha256': request['candidate_sha256'], 'official_result': official,
                    'source_restored': restored})
        def wait(self, timeout=None):
            self.waits += 1
            if timeout is not None and setup_run_timeout and self.waits == 1:
                raise grade.subprocess.TimeoutExpired('synthetic', timeout)
            self.returncode = exit_code
            return self.returncode

    setup_run_timeout = timeout
    monkeypatch.setattr(grade.subprocess, 'Popen', Process)
    return path, target, launched, kills


@pytest.mark.parametrize('official,passed', [('Pass', True), ('Error', False), ('TimeOut', False), ('OOM', False)])
def test_known_completed_official_outcomes_preserve_metric_and_pristine(tmp_path, monkeypatch, official, passed):
    path, original, launched, kills = setup_run(tmp_path, monkeypatch, official=official)
    before = original.read_bytes()
    result = grade.run(path)
    assert result['status'] == 'GRADED' and result['passed'] is passed
    assert original.read_bytes() == before and result['pristine_source_unchanged']
    assert launched[0]['start_new_session'] is True and kills == [(987654321, 9)]
    assert launched[0]['env']['PYTHONDONTWRITEBYTECODE'] == '1'
    assert Path(launched[0]['cwd']) == path.parent


@pytest.mark.parametrize('options', [
    {'official': 'Unknown'}, {'exit_code': 1}, {'timeout': True}, {'restored': False},
    {'mutate': True}, {'emit_receipt': False}, {'extra': 'untracked-output.txt'}])
def test_ambiguous_or_incomplete_grade_is_null_not_solver_failure(tmp_path, monkeypatch, options):
    path, _, _, kills = setup_run(tmp_path, monkeypatch, **options)
    result = grade.run(path)
    assert result['status'] == 'INFRA_ERROR' and result['passed'] is None
    assert kills  # The run-owned process group is cleaned on all terminal paths.


@pytest.mark.parametrize('extra', ['.pytest_cache/state', 'demo.egg-info/PKG-INFO'])
def test_only_known_generated_build_metadata_is_tolerated(tmp_path, monkeypatch, extra):
    path, _, _, _ = setup_run(tmp_path, monkeypatch, extra=extra)
    result = grade.run(path)
    assert result['status'] == 'GRADED' and result['unexpected_file_count'] == 0


def test_existing_private_workspace_never_retried(tmp_path, monkeypatch):
    path, _, launched, _ = setup_run(tmp_path, monkeypatch)
    grade.run(path)
    with pytest.raises(ValueError, match='GRADE_WORKSPACE_MUST_BE_FRESH'):
        grade.run(path)
    assert len(launched) == 1


def test_child_rejects_changed_official_helper_before_import(tmp_path):
    evaluator = tmp_path / 'synthetic_evaluator.py'; evaluator.write_text('# synthetic, never executed\n')
    path = tmp_path / 'request.json'; grade.assets.write_new(path, {'evaluator': str(evaluator)})
    with pytest.raises(ValueError, match='OFFICIAL_EVALUATOR_CHANGED'):
        grade.child(path)


def test_child_uses_hash_bound_task_candidate_and_checks_restoration(tmp_path, monkeypatch):
    source = tmp_path / 'Source_Code'; target = source / 'Synthetic/demo/module.py'
    target.parent.mkdir(parents=True); target.write_text('def target():\n    return 1\n')
    evaluator = tmp_path / 'synthetic_evaluator.py'; evaluator.write_text('# synthetic loader fixture\n')
    metadata = tmp_path / 'metadata.jsonl'
    row = {'namespace': 'module.target', 'project_path': 'Synthetic/demo', 'completion_path': 'Synthetic/demo/module.py',
           'tests': ['synthetic/private_selector'], 'indent': 4}
    metadata.write_bytes(grade.assets.canonical(row))
    candidate = tmp_path / 'body.txt'; candidate.write_bytes(b'return 2\r\n')
    request = {'task_id': row['namespace'], 'project': row['project_path'], 'evaluator': str(evaluator),
               'metadata': str(metadata), 'metadata_sha256': grade.assets.file_sha(metadata),
               'candidate_path': str(candidate), 'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
               'source_root': str(source), 'junit': str(tmp_path / 'absent.xml'), 'child_receipt': str(tmp_path / 'child.json')}
    path = tmp_path / 'request.json'; grade.assets.write_new(path, request)
    monkeypatch.setitem(grade.assets.UPSTREAM_FILES, 'pass_k.py', grade.assets.file_sha(evaluator))
    calls = []
    class Loader:
        def exec_module(self, module):
            def fake_correctness(args, task):
                calls.append((args.source_code_root, task['namespace'], task['completion']))
                return 'Pass'
            module.check_correctness = fake_correctness
    monkeypatch.setattr(grade.importlib.util, 'spec_from_file_location', lambda *a: SimpleNamespace(loader=Loader()))
    monkeypatch.setattr(grade.importlib.util, 'module_from_spec', lambda spec: SimpleNamespace())
    grade.child(path)
    result = grade.read(tmp_path / 'child.json')
    assert calls == [(str(source), row['namespace'], 'return 2\r\n')]
    assert result['source_restored'] and result['official_result'] == 'Pass'
    assert not {'tests', 'completion', 'testcases', 'gold'} & set(result)


def pinned_pristine_request(path):
    request = grade.read(path)
    pristine = Path(request['pristine_source_root'])
    entries = [{'path': 'Source_Code/' + p.relative_to(pristine).as_posix(),
                'bytes': p.stat().st_size, 'sha256': grade.assets.file_sha(p)}
               for p in pristine.rglob('*') if p.is_file()]
    manifest = path.parent / 'source-manifest.json'
    grade.assets.write_new(manifest, {'files': entries})
    request.update(source_manifest_path=str(manifest), source_manifest_sha256=grade.assets.file_sha(manifest))
    path.write_bytes(grade.assets.canonical(request))
    return request


def test_pinned_pristine_manifest_tamper_blocks_before_copy_or_process(tmp_path, monkeypatch):
    path, _, launched, _ = setup_run(tmp_path, monkeypatch)
    request = pinned_pristine_request(path)
    Path(request['source_manifest_path']).write_bytes(b'{"files":[]}\n')
    with pytest.raises(ValueError, match='PRISTINE_MANIFEST_CHANGED'):
        grade.run(path)
    assert not launched and not (path.parent / 'Source_Code').exists()


def test_pristine_validation_is_exact_project_scope_and_rejects_changed_selected_source(tmp_path, monkeypatch):
    path, target, _, _ = setup_run(tmp_path, monkeypatch)
    pristine = Path(grade.read(path)['pristine_source_root'])
    other = pristine / 'Synthetic/other/file.py'; other.parent.mkdir(parents=True); other.write_bytes(b'# other\n')
    request = pinned_pristine_request(path)
    other.write_bytes(b'# changed excluded project\n')
    assert grade.verify_pristine(request)['verified_files'] == 1
    target.write_bytes(b'# changed selected project\n')
    with pytest.raises(ValueError, match='PRISTINE_SOURCE_CHANGED'):
        grade.verify_pristine(request)


def test_external_grade_working_copy_is_fresh_and_bound_to_pinned_pristine(tmp_path, monkeypatch):
    path, target, launched, _ = setup_run(tmp_path, monkeypatch)
    request = pinned_pristine_request(path)
    external = tmp_path / 'native-filesystem' / 'condition-OFF' / 'Source_Code'
    request['working_source_root'] = str(external)
    path.write_bytes(grade.assets.canonical(request))
    before = target.read_bytes()
    result = grade.run(path)
    assert result['status'] == 'GRADED' and target.read_bytes() == before
    assert (external / 'Synthetic/demo/package/module.py').read_bytes() == before
    assert not (path.parent / 'Source_Code').exists()
    assert grade.read(path.parent / 'child-request.json')['source_root'] == str(external)
    with pytest.raises(ValueError, match='GRADE_WORKSPACE_MUST_BE_FRESH'):
        grade.run(path)
    assert len(launched) == 1


def test_first_attempt_tolerates_existing_generated_metadata_changes_with_explicit_scope(tmp_path, monkeypatch):
    path, target, _, _ = setup_run(tmp_path, monkeypatch, extra='demo.egg-info/SOURCES.txt')
    metadata = target.parents[1] / 'demo.egg-info/SOURCES.txt'
    metadata.parent.mkdir(); metadata.write_bytes(b'original package metadata\n')
    pinned_pristine_request(path)
    result = grade.run(path)
    assert result['status'] == 'GRADED' and result['passed'] is True
    assert result['pristine_source_unchanged'] is True
    assert result['working_tree_integrity']['protected_files_verified'] == 1
    assert len(result['working_tree_integrity']['generated_metadata_changes']) == 1
    assert result['pristine_source_unchanged_definition'] == 'ALL_PINNED_PRISTINE_BYTES_AND_ALL_PROTECTED_WORKING_SOURCE_TEST_BYTES'


def test_first_attempt_added_dependency_without_control_authority_stays_null(tmp_path, monkeypatch):
    path, _, _, _ = setup_run(tmp_path, monkeypatch, extra='.eggs/dependency.egg/library.py')
    pinned_pristine_request(path)
    result = grade.run(path)
    assert result['status'] == 'INFRA_ERROR' and result['passed'] is None
    assert result['working_tree_integrity']['error_code'] == 'DEPENDENCY_ALLOWLIST_REQUIRED'


def test_new_integrity_policy_never_excuses_protected_source_mutation(tmp_path, monkeypatch):
    path, _, _, _ = setup_run(tmp_path, monkeypatch, mutate=True)
    pinned_pristine_request(path)
    result = grade.run(path)
    assert result['status'] == 'INFRA_ERROR' and result['passed'] is None
    assert result['working_tree_integrity']['error_code'] == 'PROTECTED_SOURCE_CHANGED_OR_MISSING'


@pytest.mark.parametrize('blocked,expected', [(0, 'GRADED'), (1, 'INFRA_ERROR')])
def test_setup_network_guard_is_scoped_to_child_and_denials_remain_infrastructure(tmp_path, monkeypatch, blocked, expected):
    import deveval_setup_offline as offline
    path, _, launched, _ = setup_run(tmp_path, monkeypatch)
    request = grade.read(path); request['setup_support_reference'] = {'path': 'synthetic-support', 'sha256': 'b'*64, 'bytes': 1}
    path.write_bytes(grade.assets.canonical(request))
    validations = []
    monkeypatch.setattr(offline, 'validate_support', lambda ref: validations.append(ref))
    monkeypatch.setattr(offline, 'offline_environment', lambda ref, cache, guard, inherited: {
        **inherited, 'DEVEVAL_OFFLINE_GUARD_ROOT': str(guard), 'PIP_NO_INDEX': '1'})
    monkeypatch.setattr(offline, 'guard_report', lambda root: {'guarded_python_processes': 1,
        'blocked_network_operations': blocked, 'blocked_event_types': ['socket.connect'] if blocked else []})
    original_environment = dict(os.environ)
    result = grade.run(path)
    assert result['status'] == expected
    assert result['passed'] is (True if expected == 'GRADED' else None)
    assert launched[0]['env']['PIP_NO_INDEX'] == '1' and dict(os.environ) == original_environment
    assert validations == [request['setup_support_reference']]
    assert result['setup_offline']['blocked_network_operations'] == blocked
