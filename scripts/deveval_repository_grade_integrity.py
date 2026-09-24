"""Audit retained DevEval grade integrity without executing an evaluator.

Original receipts remain immutable. Dependency eggs are executable artifacts,
so only exact files from independent, complete reference controls are allowed.
Run on the same native Linux filesystem as the retained grade requests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

import deveval_prepare as assets


class IntegrityError(ValueError):
    pass


def require(value, code):
    if not value:
        raise IntegrityError(code)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': file_sha(path)}


def checked(ref):
    path = Path(ref['path'])
    require(not path.is_symlink() and path.is_file() and path.stat().st_size == ref['bytes']
            and file_sha(path) == ref['sha256'], 'REFERENCE_CHANGED')
    return path.resolve()


def read(path):
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value))
    return reference(path)


def safe_relative(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and value and not path.is_absolute() and '..' not in path.parts
            and '\\' not in value and '\x00' not in value, 'UNSAFE_RELATIVE_PATH')
    return path


def inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'TREE_MISSING_OR_LINKED')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'TREE_SYMLINK_FORBIDDEN')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': file_sha(path)}
        else:
            require(path.is_dir(), 'TREE_SPECIAL_FILE_FORBIDDEN')
    return result


def is_generated_metadata(name):
    parts = safe_relative(name).parts
    # Match the established control policy; executable additions still require
    # dependency authority and cannot hide inside a metadata directory.
    metadata = '.pytest_cache' in parts or any(part.endswith('.egg-info') for part in parts)
    executable = Path(name).suffix.lower() in ('.py', '.pyc', '.pyo', '.so', '.pyd', '.dll', '.exe', '.sh')
    return metadata and not executable


def validate_controls(control_receipt_reference):
    control = read(checked(control_receipt_reference))
    require(control.get('schema') == 'deveval/native-eligibility/1' and control.get('status') == 'PASS'
            and control.get('selected_tasks') == control.get('reference_pass') == control.get('negative_confirmed') == 30
            and control.get('pristine_unchanged') is True and control.get('working_source_tests_unchanged') is True,
            'INDEPENDENT_CONTROLS_INCOMPLETE')
    inputs = read(checked(control['inputs_reference']))
    require(inputs['plan_reference'] == control['plan_reference'] and inputs['selected_task_count'] == 30,
            'CONTROL_COHORT_CHANGED')
    require(len(control['cells']) == 60, 'CONTROL_CELL_COUNT_CHANGED')
    identities = set()
    for row in control['cells']:
        original = read(checked(row['receipt_reference']))
        identity = row['task_id'], row['project'], row['arm']
        require(identity not in identities, 'DUPLICATE_CONTROL_CELL')
        identities.add(identity)
        require(all(original[key] == row[key] for key in ('task_id', 'project', 'arm', 'official_result', 'source_restored', 'junit'))
                and row['source_restored'] is True and row['worker_returncode'] == 0, 'CONTROL_RECEIPT_CHANGED')
        if row['arm'] == 'reference':
            require(row['official_result'] == 'Pass', 'REFERENCE_CONTROL_FAILED')
        else:
            require(row['arm'] == 'assertion_negative' and row['official_result'] == 'Error'
                    and row['junit'].get('negative_marker_seen') is True
                    and row['junit'].get('unconfirmed_error_nodes') == 0, 'NEGATIVE_CONTROL_UNCONFIRMED')
    positives = {(task, project) for task, project, arm in identities if arm == 'reference'}
    negatives = {(task, project) for task, project, arm in identities if arm == 'assertion_negative'}
    require(len(positives) == 30 and positives == negatives, 'CONTROL_TASK_SET_CHANGED')
    return control, inputs


def build_dependency_allowlist(*, control_receipt_reference, control_workspace, project, output):
    control, inputs = validate_controls(control_receipt_reference)
    project_path = safe_relative(project)
    require(any(row['project'] == project for row in control['cells']), 'PROJECT_NOT_IN_CONTROLS')
    expected_workspace = checked(control['inputs_reference']).parent / 'Source_Code'
    workspace = Path(control_workspace).resolve()
    require(workspace == expected_workspace.resolve(), 'CONTROL_WORKSPACE_NOT_BOUND')
    project_root = workspace.joinpath(*project_path.parts)
    control_files = inventory(project_root)
    prefix = 'Source_Code/' + project + '/'
    source_rows = [row for row in inputs['files'] if row['path'].startswith(prefix)]
    require(source_rows, 'EMPTY_CONTROL_PROJECT')
    for row in source_rows:
        name = row['path'][len(prefix):]
        safe_relative(name)
        if not is_generated_metadata(name):
            require(control_files.get(name) == {key: row[key] for key in ('bytes', 'sha256')}, 'CONTROL_PROTECTED_FILE_CHANGED')
    original_names = {row['path'][len(prefix):] for row in source_rows}
    require(all(name in original_names or name.startswith('.eggs/') or is_generated_metadata(name)
                for name in control_files), 'CONTROL_UNEXPECTED_PROTECTED_FILE')
    files = [{'path': name, **value, 'control_file_reference': reference(project_root / name)}
             for name, value in control_files.items() if name.startswith('.eggs/')]
    return write_new(output, {'schema': 'deveval/grade-generated-dependencies/1', 'project': project,
        'control_receipt_reference': control_receipt_reference, 'control_inputs_reference': control['inputs_reference'],
        'control_plan_reference': control['plan_reference'], 'files': files,
        'files_sha256': hashlib.sha256(canonical([{k: row[k] for k in ('path', 'bytes', 'sha256')} for row in files])).hexdigest(),
        'model_calls': 0, 'official_grader_calls': 0})


def load_dependency_allowlist(ref, *, project, pristine_manifest_reference):
    value = read(checked(ref))
    require(value.get('schema') == 'deveval/grade-generated-dependencies/1' and value['project'] == project,
            'DEPENDENCY_ALLOWLIST_SCOPE_CHANGED')
    control, _ = validate_controls(value['control_receipt_reference'])
    require(value['control_inputs_reference'] == control['inputs_reference']
            and value['control_plan_reference'] == control['plan_reference']
            and checked(control['inputs_reference']) == checked(pristine_manifest_reference), 'DEPENDENCY_CONTROL_AUTHORITY_CHANGED')
    root = checked(control['inputs_reference']).parent / 'Source_Code' / Path(*safe_relative(project).parts)
    files = {}
    for row in value['files']:
        name = safe_relative(row['path']).as_posix()
        require(name.startswith('.eggs/') and name not in files, 'DEPENDENCY_PATH_INVALID')
        path = checked(row['control_file_reference'])
        require(path == (root / name).resolve() and row['sha256'] == row['control_file_reference']['sha256']
                and row['bytes'] == row['control_file_reference']['bytes'], 'DEPENDENCY_FILE_BINDING_CHANGED')
        files[name] = {key: row[key] for key in ('bytes', 'sha256')}
    require(value['files_sha256'] == hashlib.sha256(canonical([{k: row[k] for k in ('path', 'bytes', 'sha256')}
            for row in value['files']])).hexdigest(), 'DEPENDENCY_FILES_CHANGED')
    actual = inventory(root)
    require({name: row for name, row in actual.items() if name.startswith('.eggs/')} == files,
            'DEPENDENCY_CONTROL_SET_CHANGED')
    return value, files


def audit_working_tree(*, pristine_root, working_root, project, pristine_manifest_reference,
                       dependency_allowlist_reference=None):
    """Reusable postcondition for future grades and retained-evidence audits."""
    manifest = read(checked(pristine_manifest_reference))
    prefix = 'Source_Code/' + safe_relative(project).as_posix() + '/'
    baseline = {}
    for row in manifest['files']:
        safe_relative(row['path'])
        if row['path'].startswith(prefix):
            name = row['path'][len(prefix):]
            require(name not in baseline, 'DUPLICATE_PRISTINE_FILE')
            baseline[name] = {key: row[key] for key in ('bytes', 'sha256')}
    require(baseline, 'EMPTY_PRISTINE_PROJECT')
    original = inventory(Path(pristine_root) / Path(*safe_relative(project).parts))
    require(original == baseline, 'PRISTINE_SOURCE_CHANGED')
    current = inventory(Path(working_root) / Path(*safe_relative(project).parts))
    generated_changes, protected = [], 0
    for name, expected in baseline.items():
        if is_generated_metadata(name):
            if current.get(name) != expected:
                generated_changes.append({'path': name, 'before': expected, 'after': current.get(name)})
        else:
            require(current.get(name) == expected, 'PROTECTED_SOURCE_CHANGED_OR_MISSING')
            protected += 1
    additions = {name: row for name, row in current.items() if name not in baseline}
    eggs = {name: row for name, row in additions.items() if name.startswith('.eggs/')}
    if eggs or dependency_allowlist_reference is not None:
        require(dependency_allowlist_reference is not None, 'DEPENDENCY_ALLOWLIST_REQUIRED')
        _, allowed = load_dependency_allowlist(dependency_allowlist_reference, project=project,
                                               pristine_manifest_reference=pristine_manifest_reference)
        # A candidate may stop setup before it produces every optional cache
        # file. Every file actually produced must still match the independent
        # control exactly; protected original files may never be missing.
        require(all(allowed.get(name) == row for name, row in eggs.items()), 'DEPENDENCY_ADDITION_CHANGED')
    require(all(name in eggs or is_generated_metadata(name) for name in additions), 'UNEXPECTED_PROTECTED_FILE_ADDED')
    return {'status': 'PASS', 'project': project, 'protected_files_verified': protected,
        'pristine_files_verified': len(original), 'generated_metadata_changes': generated_changes,
        'generated_metadata_additions': [{'path': name, **row} for name, row in additions.items() if name not in eggs],
        'dependency_files_verified': len(eggs), 'working_tree_sha256': hashlib.sha256(canonical(current)).hexdigest(),
        'pristine_manifest_reference': pristine_manifest_reference,
        'dependency_allowlist_reference': dependency_allowlist_reference}


def audit_retained_grade(*, request_reference, original_grade_reference, dependency_allowlist_reference):
    request_path, original_path = checked(request_reference), checked(original_grade_reference)
    request, original = read(request_path), read(original_path)
    require(original_path == request_path.parent / 'receipt.json'
            and checked(original['request_reference']) == request_path, 'ORIGINAL_GRADE_BINDING_CHANGED')
    require(original['status'] in ('INFRA_ERROR', 'GRADED') and original['process_exit_code'] == 0
            and original['timed_out'] is False and original['source_restored'] is True
            and original['official_result'] in ('Pass', 'Error', 'TimeOut', 'OOM'), 'ORIGINAL_GRADE_NOT_COMPLETED')
    require(original['candidate_sha256'] == original['request_candidate_sha256'] == request['candidate_sha256']
            and file_sha(request['candidate_path']) == request['candidate_sha256']
            and original['task_id'] == request['task_id'] and original['project'] == request['project'], 'CANDIDATE_OR_SCOPE_CHANGED')
    child_reference = reference(request_path.parent / 'child-receipt.json')
    child = read(child_reference['path'])
    require(all(child[key] == original[key] for key in ('task_id', 'project', 'candidate_sha256', 'official_result',
            'source_restored', 'source_file_before_sha256', 'metadata_sha256', 'evaluator_reference')),
            'ORIGINAL_CHILD_RECEIPT_CHANGED')
    checked(original['evaluator_reference'])
    require(original['evaluator_reference']['sha256'] == assets.UPSTREAM_FILES['pass_k.py'], 'OFFICIAL_EVALUATOR_CHANGED')
    require(file_sha(request['metadata']) == request['metadata_sha256'] == original['metadata_sha256'], 'METADATA_CHANGED')
    pristine_manifest_reference = reference(request['source_manifest_path'])
    require(pristine_manifest_reference['sha256'] == request['source_manifest_sha256'], 'PRISTINE_MANIFEST_CHANGED')
    allowlist, _ = load_dependency_allowlist(dependency_allowlist_reference, project=request['project'],
                                           pristine_manifest_reference=pristine_manifest_reference)
    control, control_inputs = validate_controls(allowlist['control_receipt_reference'])
    require(request['metadata_sha256'] == control_inputs['metadata_reference']['sha256'], 'CONTROL_DATASET_CHANGED')
    require(any(row['task_id'] == request['task_id'] and row['project'] == request['project']
                for row in control['cells']), 'TASK_NOT_IN_CONTROL_COHORT')
    worker = read(request_path.parent / 'child-request.json')
    require(all(worker.get(key) == value for key, value in request.items())
            and worker['source_root'] == request.get('working_source_root', str(request_path.parent / 'Source_Code'))
            and Path(worker['child_receipt']).resolve() == Path(child_reference['path']), 'CHILD_REQUEST_CHANGED')
    tree = audit_working_tree(pristine_root=request['pristine_source_root'], working_root=worker['source_root'],
        project=request['project'], pristine_manifest_reference=pristine_manifest_reference,
        dependency_allowlist_reference=dependency_allowlist_reference)
    baseline = read(pristine_manifest_reference['path'])
    require(any(row['path'].startswith('Source_Code/' + request['project'] + '/')
                and not is_generated_metadata(row['path']) and row['sha256'] == original['source_file_before_sha256']
                for row in baseline['files']), 'TARGET_RESTORATION_HASH_UNBOUND')
    for ref in (request_reference, original_grade_reference, child_reference, dependency_allowlist_reference):
        checked(ref)
    return {'schema': 'deveval/retained-grade-integrity/1', 'status': 'INTEGRITY_VERIFIED',
        'task_id': request['task_id'], 'project': request['project'], 'candidate_sha256': request['candidate_sha256'],
        'official_result': original['official_result'], 'passed': original['official_result'] == 'Pass',
        'original_grade_reference': original_grade_reference, 'original_grade_status': original['status'],
        'request_reference': request_reference, 'child_receipt_reference': child_reference,
        'integrity': tree, 'checker_reference': reference(__file__),
        'model_calls': 0, 'official_grader_calls': 0, 'original_receipt_modified': False}


def amend_retained_grade(*, output, **arguments):
    report = audit_retained_grade(**arguments)
    require(not Path(output).resolve().is_relative_to(checked(arguments['original_grade_reference']).parent),
            'AMENDMENT_MUST_BE_OUTSIDE_ORIGINAL_GRADE')
    return write_new(output, report)
