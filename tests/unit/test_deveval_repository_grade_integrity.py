"""Synthetic retained-evidence checks; no evaluator, model, or benchmark data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_grade_integrity as integrity


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(integrity.canonical(value))


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    project = 'System/example'
    control_root = tmp_path / 'control'
    pristine = control_root / 'pristine/Source_Code'
    origin = pristine / project
    for name, raw in {'example.py': b'def target():\n    return 1\n', 'tests/test_example.py': b'assert True\n',
                      'example.egg-info/SOURCES.txt': b'original metadata\n', '.pytest_cache/v/cache/nodeids': b'[]\n'}.items():
        path = origin / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    control_workspace = control_root / 'Source_Code'; shutil.copytree(pristine, control_workspace)
    egg = control_workspace / project / '.eggs/dependency-1.0.egg/dependency.py'
    egg.parent.mkdir(parents=True); egg.write_bytes(b'value = 1\n')
    metadata = tmp_path / 'metadata.json'; metadata.write_bytes(b'opaque synthetic dataset\n')
    plan = {'path': 'old-retained-plan.json', 'sha256': 'a'*64, 'bytes': 10}
    inputs = {'plan_reference': plan, 'selected_task_count': 30, 'metadata_reference': integrity.reference(metadata),
              'files': [{'path': 'Source_Code/' + project + '/' + name, **row} for name, row in integrity.inventory(origin).items()]}
    input_path = control_root / 'inputs.json'; write(input_path, inputs)
    cells = []
    for ordinal in range(30):
        for arm in ('reference', 'assertion_negative'):
            cell = {'task_id': 'synthetic-%02d' % ordinal, 'project': project, 'arm': arm,
                    'official_result': 'Pass' if arm == 'reference' else 'Error', 'source_restored': True,
                    'junit': {'negative_marker_seen': arm == 'assertion_negative', 'unconfirmed_error_nodes': 0}}
            path = control_root / ('%02d-%s/receipt.json' % (ordinal, arm)); write(path, cell)
            cells.append({**cell, 'receipt_reference': integrity.reference(path), 'worker_returncode': 0})
    controls = {'schema': 'deveval/native-eligibility/1', 'status': 'PASS', 'selected_tasks': 30,
                'reference_pass': 30, 'negative_confirmed': 30, 'pristine_unchanged': True,
                'working_source_tests_unchanged': True, 'plan_reference': plan,
                'inputs_reference': integrity.reference(input_path), 'cells': cells}
    control_path = control_root / 'eligibility.json'; write(control_path, controls)
    allowlist = integrity.build_dependency_allowlist(control_receipt_reference=integrity.reference(control_path),
        control_workspace=control_workspace, project=project, output=tmp_path / 'allowlist.json')
    working = tmp_path / 'grade-work/Source_Code'; shutil.copytree(control_workspace, working)
    (working / project / 'example.egg-info/SOURCES.txt').write_bytes(b'generated metadata\n')
    (working / project / '.pytest_cache/v/cache/nodeids').write_bytes(b'[1]\n')
    folder = tmp_path / 'private-grade'; folder.mkdir()
    candidate = folder / 'candidate.py'; candidate.write_bytes(b'return 1\n')
    evaluator = tmp_path / 'evaluator.py'; evaluator.write_bytes(b'# synthetic evaluator never executed\n')
    monkeypatch.setitem(integrity.assets.UPSTREAM_FILES, 'pass_k.py', integrity.file_sha(evaluator))
    request = {'task_id': 'synthetic-00', 'project': project, 'candidate_path': str(candidate),
        'candidate_sha256': integrity.file_sha(candidate), 'metadata': str(metadata), 'metadata_sha256': integrity.file_sha(metadata),
        'evaluator': str(evaluator), 'pristine_source_root': str(pristine), 'working_source_root': str(working),
        'source_manifest_path': str(input_path), 'source_manifest_sha256': integrity.file_sha(input_path)}
    request_path = folder / 'request.json'; write(request_path, request)
    child = {'task_id': request['task_id'], 'project': project, 'candidate_sha256': request['candidate_sha256'],
        'official_result': 'Pass', 'source_restored': True, 'source_file_before_sha256': integrity.file_sha(origin / 'example.py'),
        'metadata_sha256': request['metadata_sha256'], 'evaluator_reference': integrity.reference(evaluator)}
    write(folder / 'child-receipt.json', child)
    write(folder / 'child-request.json', {**request, 'source_root': str(working), 'child_receipt': str(folder / 'child-receipt.json')})
    original = {**child, 'status': 'INFRA_ERROR', 'passed': None, 'process_exit_code': 0, 'timed_out': False,
        'pristine_source_unchanged': False, 'unexpected_file_count': 1, 'request_reference': integrity.reference(request_path),
        'request_candidate_sha256': request['candidate_sha256']}
    original_path = folder / 'receipt.json'; write(original_path, original)
    args = {'request_reference': integrity.reference(request_path), 'original_grade_reference': integrity.reference(original_path),
            'dependency_allowlist_reference': allowlist}
    return {'args': args, 'working': working, 'project': project, 'origin': origin, 'original': original_path,
            'controls': control_path, 'control_workspace': control_workspace, 'allowlist': allowlist,
            'input_path': input_path, 'pristine': pristine, 'tmp': tmp_path}


def test_reclassification_preserves_original_and_verifies_exact_control_dependencies(evidence):
    before = evidence['original'].read_bytes()
    ref = integrity.amend_retained_grade(output=evidence['tmp'] / 'amendments/001.json', **evidence['args'])
    result = integrity.read(ref['path'])
    assert result['status'] == 'INTEGRITY_VERIFIED' and result['passed'] is True
    assert result['original_grade_status'] == 'INFRA_ERROR'
    assert result['integrity']['protected_files_verified'] == 2 and result['integrity']['dependency_files_verified'] == 1
    assert len(result['integrity']['generated_metadata_changes']) == 2
    assert evidence['original'].read_bytes() == before
    assert result['model_calls'] == result['official_grader_calls'] == 0


@pytest.mark.parametrize('mutation', ['source', 'test', 'missing', 'added_executable', 'dependency'])
def test_source_test_and_dependency_mutations_are_never_excused_as_metadata(evidence, mutation):
    root = evidence['working'] / evidence['project']
    paths = {'source': 'example.py', 'test': 'tests/test_example.py', 'missing': 'tests/test_example.py',
             'added_executable': 'example.egg-info/injected.py', 'dependency': '.eggs/dependency-1.0.egg/dependency.py',
             'dependency_missing': '.eggs/dependency-1.0.egg/dependency.py'}
    path = root / paths[mutation]
    if mutation == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'changed\n')
    with pytest.raises(integrity.IntegrityError):
        integrity.audit_retained_grade(**evidence['args'])


def test_optional_dependency_files_not_created_by_early_setup_failure_are_not_required(evidence):
    path = evidence['working'] / evidence['project'] / '.eggs/dependency-1.0.egg/dependency.py'
    path.unlink()
    result = integrity.audit_retained_grade(**evidence['args'])
    assert result['status'] == 'INTEGRITY_VERIFIED' and result['integrity']['dependency_files_verified'] == 0
    assert result['integrity']['protected_files_verified'] == 2


def test_dependency_allowlist_cannot_be_omitted(evidence):
    with pytest.raises(integrity.IntegrityError, match='ALLOWLIST_REQUIRED'):
        integrity.audit_working_tree(pristine_root=evidence['pristine'], working_root=evidence['working'],
            project=evidence['project'], pristine_manifest_reference=integrity.reference(evidence['input_path']))


def test_tampered_or_wrong_project_allowlist_is_rejected(evidence):
    path = Path(evidence['allowlist']['path']); value = integrity.read(path); value['project'] = 'Other/project'; write(path, value)
    with pytest.raises(integrity.IntegrityError, match='REFERENCE_CHANGED'):
        integrity.audit_retained_grade(**evidence['args'])
    with pytest.raises(integrity.IntegrityError, match='SCOPE_CHANGED'):
        integrity.audit_retained_grade(**{**evidence['args'], 'dependency_allowlist_reference': integrity.reference(path)})


def test_incomplete_control_cohort_cannot_authorize_generated_dependencies(evidence):
    value = integrity.read(evidence['controls']); value['reference_pass'] = 29; write(evidence['controls'], value)
    with pytest.raises(integrity.IntegrityError, match='CONTROLS_INCOMPLETE'):
        integrity.build_dependency_allowlist(control_receipt_reference=integrity.reference(evidence['controls']),
            control_workspace=evidence['control_workspace'], project=evidence['project'], output=evidence['tmp'] / 'invalid.json')


def test_unrelated_task_and_incomplete_outer_process_cannot_be_recovered(evidence):
    value = integrity.read(evidence['original']); value['timed_out'] = True; write(evidence['original'], value)
    with pytest.raises(integrity.IntegrityError, match='NOT_COMPLETED'):
        integrity.audit_retained_grade(**{**evidence['args'], 'original_grade_reference': integrity.reference(evidence['original'])})


def test_unmutated_pristine_bytes_are_required_separately(evidence):
    (evidence['origin'] / 'example.py').write_bytes(b'changed pristine\n')
    with pytest.raises(integrity.IntegrityError, match='PRISTINE_SOURCE_CHANGED'):
        integrity.audit_retained_grade(**evidence['args'])


def test_original_grade_directory_is_never_written(evidence):
    with pytest.raises(integrity.IntegrityError, match='OUTSIDE_ORIGINAL'):
        integrity.amend_retained_grade(output=evidence['original'].parent / 'amended.json', **evidence['args'])
