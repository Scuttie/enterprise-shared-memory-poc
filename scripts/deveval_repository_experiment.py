"""Frozen repository-memory pilot: source, verification, VALID, TEST and grading."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

import deveval_repository_native as native
import deveval_repository_memory as memory
import deveval_repository_context as repository
import deveval_repository_plan as planner
import trimem_lcb_experiment as original_manager

ROOT = Path(__file__).resolve().parents[1]
PHASES = ('DISCOVERY', 'VERIFICATION', 'VALID', 'TEST')
MODEL_FAILURES = {'TaskTimeout', 'SessionBudgetExhausted', 'MissingSubmission', 'UnexpectedNativeTool', 'ActionCallBudgetExceeded'}


def write(path, value):
    native.core.write(path, value)


def checked_relative(ref):
    path = ROOT / ref['path']
    value = memory.reference(path)
    memory.require(value['sha256'] == ref['sha256'] and value['bytes'] == ref['bytes'], 'PLAN_INPUT_CHANGED')
    return path


def physical_path(value, runtime):
    path = Path(value)
    if path.is_absolute() and path.exists():
        return path
    normalized = str(value).replace('\\', '/')
    mappings = sorted(runtime.get('execution_path_remap', []), key=lambda row: -len(row['to']))
    for row in mappings:
        prefix = row['to'].rstrip('/')
        if normalized == prefix or normalized.startswith(prefix + '/'):
            mapped = Path(row['from'].rstrip('/\\') + normalized[len(prefix):])
            if mapped.exists():
                return mapped
    return path


def checked_foreign(ref, runtime):
    path = physical_path(ref['path'], runtime)
    actual = memory.reference(path)
    memory.require(actual['sha256'] == ref['sha256'] and actual['bytes'] == ref['bytes'], 'EXECUTION_AUTHORITY_CHANGED')
    return actual


def grade_dependency_references(runtime, projects, eligibility_reference, inputs_reference):
    """Freeze control-derived setup artifacts before any new model collection."""
    settings = runtime['deveval']
    controls = physical_path(inputs_reference['path'], runtime).parent / 'Source_Code'
    mappings = settings.get('generated_dependency_allowlists', {})
    memory.require(isinstance(mappings, dict) and (not mappings or set(mappings) == set(projects)),
                   'GRADE_DEPENDENCY_PROJECTS_CHANGED')
    refs = []
    for project in sorted(projects):
        eggs = controls / project / '.eggs'
        memory.require(not eggs.is_symlink(), 'GRADE_DEPENDENCY_LINK_FORBIDDEN')
        egg_entries = list(eggs.rglob('*')) if eggs.exists() else []
        memory.require(all(not entry.is_symlink() for entry in egg_entries), 'GRADE_DEPENDENCY_LINK_FORBIDDEN')
        actual_names = {entry.relative_to(controls / project).as_posix()
                        for entry in egg_entries if entry.is_file()}
        if project not in mappings:
            memory.require(not actual_names,
                           'CONTROL_SETUP_DEPENDENCIES_NOT_BOUND')
            continue
        actual = checked_foreign(mappings[project], runtime)
        value = memory.read(actual['path'])
        memory.require(value.get('schema') == 'deveval/grade-generated-dependencies/1'
                       and value.get('project') == project, 'GRADE_DEPENDENCY_SCOPE_CHANGED')
        control_ref = checked_foreign(value['control_receipt_reference'], runtime)
        input_ref = checked_foreign(value['control_inputs_reference'], runtime)
        memory.require(control_ref == eligibility_reference
                       and input_ref == checked_foreign(inputs_reference, runtime),
                       'GRADE_DEPENDENCY_CONTROL_CHANGED')
        memory.require(value['control_plan_reference'] == memory.read(control_ref['path'])['plan_reference'],
                       'GRADE_DEPENDENCY_PLAN_CHANGED')
        refs.extend((actual, control_ref, input_ref))
        seen = set()
        for row in value['files']:
            name = repository.relative(row['path']).as_posix()
            memory.require(name.startswith('.eggs/') and name not in seen, 'GRADE_DEPENDENCY_PATH_CHANGED')
            seen.add(name)
            dependency = checked_foreign(row['control_file_reference'], runtime)
            memory.require(Path(dependency['path']).resolve() == (controls / project / name).resolve()
                           and all(dependency[key] == row[key] for key in ('sha256', 'bytes')),
                           'GRADE_DEPENDENCY_FILE_CHANGED')
            refs.append(dependency)
        memory.require(seen == actual_names, 'GRADE_DEPENDENCY_SET_CHANGED')
        expected_digest = hashlib.sha256(memory.canonical([
            {key: row[key] for key in ('path', 'bytes', 'sha256')} for row in value['files']])).hexdigest()
        memory.require(value.get('files_sha256') == expected_digest, 'GRADE_DEPENDENCY_MANIFEST_CHANGED')
    if settings.get('setup_support_reference'):
        import deveval_setup_offline as offline
        actual = checked_foreign(settings['setup_support_reference'], runtime)
        support = offline.validate_support(actual)
        refs.append(actual)
        refs.extend(memory.reference(Path(actual['path']).parent / row['path']) for row in support['files'])
    return refs


def plan_schedule(plan):
    rows = []
    for row in plan['source_schedule'] + plan['target_schedule']:
        rows.append({**row, 'ordinal': len(rows) + 1,
            'condition': ('TRAIN' if row['phase'] == 'DISCOVERY' else 'PROVISIONAL') if row['arm'] == 'SOURCE' else row['arm']})
    return rows


def load(plan_path, runtime_path, snapshots_path, eligibility_path, output):
    plan, runtime, snapshots, eligibility = map(memory.read, (plan_path, runtime_path, snapshots_path, eligibility_path))
    memory.require(plan['schema'] == 'deveval/repository-plan/1', 'PLAN_SCHEMA_CHANGED')
    for key in ('metadata_reference', 'planner_reference', 'asset_helper_reference'):
        checked_relative(plan[key])
    rebuilt = planner.build_plan(planner.metadata_rows(checked_relative(plan['metadata_reference'])),
        metadata_reference=plan['metadata_reference'], source_archive_reference=plan['source_archive_reference'])
    rebuilt.update(planner_reference=plan['planner_reference'], asset_helper_reference=plan['asset_helper_reference'])
    memory.require(plan == rebuilt, 'PLAN_DERIVATION_CHANGED')
    # Archive authority is checked during snapshot preparation and eligibility;
    # per-model checks cover the sanitized snapshot and execution code.
    archive = ROOT / plan['source_archive_reference']['path']
    memory.require(archive.stat().st_size == plan['source_archive_reference']['bytes'], 'SOURCE_ARCHIVE_SIZE_CHANGED')
    projects = {row['project'] for row in plan['projects']}
    memory.require(set(snapshots) == projects, 'SNAPSHOT_PROJECTS_CHANGED')
    memory.require(eligibility.get('status') == 'PASS' and eligibility.get('model_calls') == 0
        and eligibility.get('pristine_unchanged') is True and eligibility.get('working_source_tests_unchanged') is True,
        'NATIVE_ELIGIBILITY_NOT_READY')
    admitted = [row for row in eligibility['cells'] if row['arm'] == 'reference']
    expected_ids = {row['task_id'] for row in plan['tasks']}
    pairs = [(row['task_id'], row['arm']) for row in eligibility['cells']]
    memory.require(len(pairs) == 2 * len(expected_ids) and set(pairs) == {
        (task_id, arm) for task_id in expected_ids for arm in ('reference', 'assertion_negative')}, 'CONTROL_PAIRS_INCOMPLETE')
    negatives = [row for row in eligibility['cells'] if row['arm'] == 'assertion_negative']
    memory.require(all(row['source_restored'] is True and row['official_result'] == 'Error'
        and row['junit']['negative_marker_seen'] is True and row['junit']['unconfirmed_error_nodes'] == 0
        and row['junit']['confirmed_negative_failure_nodes'] + row['junit']['confirmed_negative_error_nodes'] > 0
        for row in negatives), 'NEGATIVE_CONTROLS_NOT_CONFIRMED')
    memory.require(len(admitted) == len(expected_ids) and {row['task_id'] for row in admitted} == expected_ids
        and all(row['official_result'] == 'Pass' and row['source_restored'] is True for row in admitted)
        and eligibility['reference_pass'] == len(expected_ids) and eligibility['negative_confirmed'] == len(expected_ids), 'REFERENCE_ELIGIBILITY_INCOMPLETE')
    current_plan_sha = memory.reference(plan_path)['sha256']
    if eligibility['plan_reference']['sha256'] != current_plan_sha:
        bridge = memory.read(runtime['deveval']['eligibility_bridge'])
        old_plan = memory.read(checked_relative(bridge['previous_plan_reference']))
        unchanged = lambda value: {k: v for k, v in value.items() if k not in ('planner_reference', 'visibility')}
        memory.require(bridge['previous_plan_reference']['sha256'] == eligibility['plan_reference']['sha256']
            and bridge['current_plan_reference']['sha256'] == current_plan_sha
            and bridge['eligibility_reference']['sha256'] == memory.reference(eligibility_path)['sha256']
            and bridge['exact_task_ids_phase_schedule_budget_model_unchanged'] is True
            and unchanged(old_plan) == unchanged(plan) and bridge['model_calls_before_amendment'] == 0,
            'ELIGIBILITY_PLAN_CHANGED')
    provider = runtime.get('gateway', {}).get('provider', 'native_codex')
    if provider == 'native_codex':
        memory.require(runtime['native']['model'] == plan['model']['model'] and
            runtime['native']['reasoning_effort'] == plan['model']['reasoning_effort'], 'NATIVE_MODEL_CHANGED')
    else:
        memory.require(provider == 'vllm' and runtime['native']['model'] == runtime['gateway']['model'], 'INVALID_REPLICATION_MODEL')
    public_tasks = {}
    refs = [memory.reference(path) for path in (plan_path, runtime_path, snapshots_path, eligibility_path)]
    if runtime['deveval'].get('eligibility_bridge'):
        refs.append(memory.reference(runtime['deveval']['eligibility_bridge']))
    for key in ('runtime_lock_reference', 'inputs_reference'):
        refs.append(checked_foreign(eligibility[key], runtime))
    refs += grade_dependency_references(runtime, projects, memory.reference(eligibility_path),
                                        eligibility['inputs_reference'])
    if runtime['deveval'].get('source_manifest_path'):
        memory.require(runtime['deveval']['source_manifest_path'] == eligibility['inputs_reference']['path']
            and runtime['deveval']['source_manifest_sha256'] == eligibility['inputs_reference']['sha256'], 'PRISTINE_RUNTIME_AUTHORITY_CHANGED')
    pristine_manifest = memory.read(physical_path(eligibility['inputs_reference']['path'], runtime))
    pristine_root = physical_path(runtime['deveval']['pristine_source_root'], runtime)
    private_refs = []
    for row in pristine_manifest['files']:
        relative = repository.relative(row['path'])
        memory.require(relative.parts[0] == 'Source_Code', 'PRISTINE_MANIFEST_PATH')
        path = pristine_root.joinpath(*relative.parts[1:])
        expected = {**row, 'path': str(path.absolute())}
        private_refs.append(expected)
    if runtime.get('execution', {}).get('prefix'):
        request = {'source_manifest_path': eligibility['inputs_reference']['path'],
            'source_manifest_sha256': eligibility['inputs_reference']['sha256'],
            'pristine_source_root': runtime['deveval']['pristine_source_root']}
        command = native.core.execution_command(runtime, 'deveval_repository_grade.py', ['verify', '-'])
        check = subprocess.run(command, input=memory.canonical(request), capture_output=True, timeout=120)
        memory.require(check.returncode == 0 and json.loads(check.stdout)['verified_files'] == len(private_refs), 'PRISTINE_SOURCE_CHANGED')
    else:
        for ref in private_refs:
            memory.checked(ref)
    for row in eligibility['cells']:
        ref = checked_foreign(row['receipt_reference'], runtime)
        receipt = memory.read(ref['path'])
        memory.require(all(receipt[key] == row[key] for key in ('task_id', 'project', 'arm', 'official_result', 'source_restored', 'junit')),
            'CONTROL_RECEIPT_CHANGED')
        refs.append(ref)
    execution_modules = ('deveval_prepare.py', 'deveval_model_gateway.py', 'deveval_generated_tests.py',
        'deveval_repository_plan.py', 'deveval_repository_context.py', 'deveval_repository_memory.py',
        'deveval_repository_native.py', 'deveval_repository_grade.py', 'deveval_repository_experiment.py',
        'deveval_repository_grade_integrity.py', 'deveval_setup_offline.py')
    source_paths = sorted(set([*[ROOT / 'scripts' / name for name in execution_modules], ROOT / 'scripts/trimem_lcb_native.py',
        ROOT / 'scripts/trimem_lcb_memory.py', ROOT / 'scripts/trimem_lcb_experiment.py',
        *ROOT.glob('src/enterprise_memory/trimem/*.py')]))
    refs += [memory.reference(path) for path in source_paths]
    if provider == 'native_codex':
        refs.append(memory.reference(runtime['native']['codex_executable']))
    for project, ref in snapshots.items():
        view = repository.load_snapshot(ref)
        memory.require(view.manifest['project'] == project and view.manifest['plan_reference']['sha256'] == current_plan_sha,
            'SNAPSHOT_PROJECT_CHANGED')
        # The snapshot contains every official target body mask, not just the selected tasks.
        for row in plan['tasks']:
            if row['project'] == project:
                task = view.public_task(row['task_id'])
                memory.require(hashlib.sha256(memory.canonical(task['requirement'])).hexdigest() == row['public_requirement_sha256'], 'PUBLIC_REQUIREMENT_CHANGED')
                public_tasks[row['task_id']] = task
        refs.append(ref)
        refs += [memory.reference(view.root / path) for path in ('relations.json',)]
        for path, file in view.files.items():
            actual = memory.reference(view.root / 'repository' / path)
            memory.require(actual['sha256'] == file['sha256'], 'VISIBLE_SOURCE_CHANGED')
            refs.append(actual)
    frozen = {'schema': 'deveval/repository-experiment/1', 'references': refs, 'schedule': plan_schedule(plan),
        'private_references': private_refs,
        'provider': provider, 'requested_model': runtime['native']['model'],
        'reasoning_effort': runtime['native'].get('reasoning_effort') if provider == 'native_codex' else None,
        'same_task_ids_as_native_plan': True, 'glm_replication': provider == 'vllm',
        'snapshots': snapshots, 'hidden_feedback_to_model': False, 'private_grades_used_for_memory': False,
        'owner': 'skhynix-deveval-002/' + runtime['native']['model']}
    memory.write_new(output / 'frozen-inputs.json', frozen)
    context = {'plan': plan, 'plan_reference': memory.reference(plan_path), 'runtime': runtime,
        'snapshots': snapshots, 'eligibility': eligibility, 'tasks': public_tasks,
        'frozen': frozen, 'output': output, 'owner': frozen['owner']}
    verify(context)
    return context


def verify(context):
    for ref in context['frozen']['references']:
        memory.checked(ref)


def cell_path(context, job):
    identity = hashlib.sha256(job['task_id'].encode()).hexdigest()[:20]
    return context['output'] / job['phase'] / job['condition'] / identity


def collect(context, job, bank_ref, selected_id):
    verify(context)
    cell = cell_path(context, job)
    authority = {'job': job, 'bank': bank_ref, 'selected_procedure_id': selected_id,
        'frozen_inputs_reference': memory.reference(context['output'] / 'frozen-inputs.json')}
    start = context['output'] / 'starts' / ('%03d.json' % job['ordinal'])
    memory.require(start.exists() or not cell.exists(), 'UNBOUND_PREEXISTING_CELL')
    memory.write_new(start, authority)
    row_path = cell / 'cell-receipt.json'
    if (cell / 'solve-receipt.json').exists():
        memory.require(memory.read(cell / 'attempt.json') == authority, 'RESUMED_ATTEMPT_CHANGED')
        state, solve = memory.read(cell / 'state.json'), memory.read(cell / 'solve-receipt.json')
        memory.require(state['phase'] == job['phase'] and state['condition'] == job['condition']
            and state['task'] == context['tasks'][job['task_id']] and state['runtime'] == context['runtime']
            and state['bank'] == bank_ref and state['selected_procedure_id'] == selected_id
            and state['owner'] == context['owner'], 'RESUMED_CELL_SCOPE_CHANGED')
    elif cell.exists():
        return {'task_id': job['task_id'], 'project': job['project'], 'phase': job['phase'], 'condition': job['condition'],
            'ordinal': job['ordinal'], 'status': 'HELD', 'error_type': 'InterruptedAttemptNoRetry', 'passed': None}
    else:
        native.initialize(cell, snapshot_reference=context['snapshots'][job['project']], task_id=job['task_id'],
            phase=job['phase'], condition=job['condition'], runtime=context['runtime'], owner=context['owner'],
            bank_reference=bank_ref, selected_procedure_id=selected_id)
        memory.write_new(cell / 'attempt.json', authority)
        try:
            solve = native.solve(cell, before_model_call=lambda: verify(context))
        except Exception as error:
            return {'task_id': job['task_id'], 'project': job['project'], 'phase': job['phase'], 'condition': job['condition'],
                'ordinal': job['ordinal'], 'status': 'HELD', 'error_type': type(error).__name__, 'passed': None}
        state = memory.read(cell / 'state.json')
    memory.require(solve['state_sha256'] == memory.reference(cell / 'state.json')['sha256']
        and solve['candidate_sha256'] == hashlib.sha256(state['candidate'].encode()).hexdigest()
        and solve['task_id'] == job['task_id'] and solve['arm'] == state['arm'], 'SOLVE_BINDING_CHANGED')
    row = {'task_id': job['task_id'], 'project': job['project'], 'phase': job['phase'], 'condition': job['condition'],
        'ordinal': job['ordinal'], 'status': solve['status'], 'error_type': solve['error_type'],
        'passed': False if solve['status'] != 'SUBMITTED' and solve['error_type'] in MODEL_FAILURES else None,
        'grade_status': 'PENDING' if solve['status'] == 'SUBMITTED' else 'NOT_GRADED',
        'candidate_sha256': solve['candidate_sha256'], 'solve_seconds': solve['wall_seconds'],
        'tool_seconds': solve['tool_seconds'], 'sessions': len(solve['sessions']), 'tool_actions': solve['tool_actions'],
        'generated_test_runs': state['public_test_runs'], 'memory_layers': [item['layer'] for item in state['memory_injections']],
        'declared_procedure_applications': sum(h['tool'] == 'run_command' and bool(h['request_payload']['arguments'].get('procedure_id')) for h in state['history']),
        'solve_reference': memory.reference(cell / 'solve-receipt.json'), 'state_reference': memory.reference(cell / 'state.json')}
    if row_path.exists():
        old = memory.read(row_path)
        memory.require(old['solve_reference'] == row['solve_reference'] and old['state_reference'] == row['state_reference'], 'RESUMED_ROW_CHANGED')
        if 'grade_reference' in old:
            sealed = memory.reference(context['output'] / job['phase'] / 'collection.json')
            validate_grade(context, job, old, sealed)
            row.update({key: old[key] for key in ('grade_reference', 'grade_status', 'passed', 'grade_seconds')})
    write(row_path, row)
    return row


def checkpoint(context, rows, phase, status, started, bank_ref=None, reason=None):
    groups = {}
    for job in context['frozen']['schedule']:
        key = job['phase'] + '/' + job['condition']
        if key in groups:
            continue
        jobs = [j for j in context['frozen']['schedule'] if j['phase'] == job['phase'] and j['condition'] == job['condition']]
        entries = [r for r in rows if r['phase'] == job['phase'] and r['condition'] == job['condition']]
        passed, failed = sum(r['passed'] is True for r in entries), sum(r['passed'] is False for r in entries)
        groups[key] = {'planned': len(jobs), 'recorded': len(entries), 'submitted': sum(r['status'] == 'SUBMITTED' for r in entries),
            'passed': passed, 'failed': failed, 'unresolved_or_unexecuted': len(jobs)-passed-failed,
            'success_rate': passed / len(jobs) if passed+failed == len(jobs) else None,
            'solve_seconds': sum(r.get('solve_seconds', 0) for r in entries),
            'actual_layer_injections': {layer: sum(r.get('memory_layers', []).count(layer) for r in entries) for layer in ('L1', 'L2', 'L3')}}
    value = {'schema': 'deveval/repository-summary/1', 'status': status, 'phase': phase, 'reason': reason,
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'planned_cells': len(context['frozen']['schedule']),
        'recorded_cells': len(rows), 'manager_seconds': time.monotonic() - started,
        'bank': bank_ref, 'arms': groups, 'cells': rows, 'private_feedback_to_model': False,
        'l3_absence_does_not_skip_l2_evaluation': True}
    write(context['output'] / 'summary.json', value)
    return value


def seal(context, phase, rows):
    jobs = [job for job in context['frozen']['schedule'] if job['phase'] == phase]
    selected = [row for row in rows if row['phase'] == phase]
    memory.require([r['ordinal'] for r in selected] == [j['ordinal'] for j in jobs], 'COLLECTION_INCOMPLETE')
    refs = []
    for job in jobs:
        cell = cell_path(context, job)
        for name in ('state.json', 'solve-receipt.json', 'attempt.json', 'gateway-start.json', 'gateway-receipt.json'):
            if (cell / name).exists():
                refs.append(memory.reference(cell / name))
        memory.require((cell / 'solve-receipt.json').exists(), 'COLLECTION_NONTERMINAL')
        for path in sorted(cell.glob('session-*/*')):
            if path.is_file():
                refs.append(memory.reference(path))
        for path in sorted(cell.glob('session-*/http-*/*')):
            if path.is_file():
                refs.append(memory.reference(path))
        for path in sorted((cell / 'generated-tests').rglob('*')):
            if path.is_file():
                refs.append(memory.reference(path))
    destination = context['output'] / phase / 'collection.json'
    stable = [{k: v for k, v in row.items() if not k.startswith('grade_') and k != 'passed'} for row in selected]
    memory.write_new(destination, {'phase': phase, 'status': 'SEALED', 'rows': stable, 'references': refs,
        'private_grader_started': False})
    return memory.reference(destination)


def verify_collection(ref):
    value = memory.read(memory.checked(ref))
    for source in value['references']:
        memory.checked(source)


def expected_grade_request(context, job, row, collection_ref):
    folder = cell_path(context, job) / 'private-grade'
    runtime = context['runtime']
    settings = runtime['deveval']
    request = {'task_id': job['task_id'], 'project': job['project'], 'candidate_sha256': row['candidate_sha256'],
        'candidate_path': native.core.mapped_path(folder / 'candidate.py', runtime),
        'metadata': settings['metadata'], 'metadata_sha256': context['plan']['metadata_reference']['sha256'],
        'evaluator': settings['evaluator'], 'pristine_source_root': settings['pristine_source_root'],
        'collection_sha256': collection_ref['sha256']}
    if settings.get('source_manifest_path'):
        request.update(source_manifest_path=settings['source_manifest_path'], source_manifest_sha256=settings['source_manifest_sha256'])
    if settings.get('grade_work_root'):
        identity = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24]
        request['working_source_root'] = settings['grade_work_root'].rstrip('/') + '/' + identity + '/Source_Code'
    if settings.get('generated_dependency_allowlists'):
        request['generated_dependency_allowlist_reference'] = settings['generated_dependency_allowlists'][job['project']]
    if settings.get('setup_support_reference'):
        request['setup_support_reference'] = settings['setup_support_reference']
    return request


def validate_grade(context, job, row, collection_ref):
    verify_collection(collection_ref)
    memory.require(memory.read(collection_ref['path'])['phase'] == job['phase'], 'GRADE_COLLECTION_PHASE_CHANGED')
    folder = cell_path(context, job) / 'private-grade'
    grade_path, request_path = folder / 'receipt.json', folder / 'request.json'
    if 'grade_reference' in row:
        memory.require(memory.checked(row['grade_reference']).resolve() == grade_path.resolve(), 'CACHED_GRADE_PATH_CHANGED')
    receipt = memory.read(grade_path)
    memory.require(memory.read(request_path) == expected_grade_request(context, job, row, collection_ref), 'GRADE_REQUEST_CHANGED')
    request_ref = memory.reference(request_path)
    memory.require(checked_foreign(receipt['request_reference'], context['runtime']) == request_ref, 'GRADE_REQUEST_REFERENCE_CHANGED')
    memory.require(receipt['task_id'] == job['task_id'] and receipt['project'] == job['project']
        and receipt['candidate_sha256'] == row['candidate_sha256'] == receipt['request_candidate_sha256'], 'GRADE_IDENTITY_CHANGED')
    if receipt['status'] == 'GRADED':
        import deveval_prepare as assets
        memory.require(receipt['official_result'] in ('Pass', 'Error', 'TimeOut', 'OOM')
            and receipt['passed'] is (receipt['official_result'] == 'Pass')
            and receipt['process_exit_code'] == 0 and receipt['timed_out'] is False
            and receipt['source_restored'] is True and receipt['pristine_source_unchanged'] is True
            and receipt['unexpected_file_count'] == 0
            and receipt['metadata_sha256'] == context['plan']['metadata_reference']['sha256']
            and receipt['evaluator_reference']['sha256'] == assets.UPSTREAM_FILES['pass_k.py'], 'GRADE_OUTCOME_INCOHERENT')
    else:
        memory.require(receipt['status'] == 'INFRA_ERROR' and receipt['passed'] is None, 'GRADE_OUTCOME_INCOHERENT')
    if 'grade_reference' in row:
        memory.require(receipt['passed'] is row['passed'] and receipt['status'] == row['grade_status'], 'CACHED_GRADE_CHANGED')
    return receipt


def grade(context, job, row, collection_ref):
    verify(context)
    verify_collection(collection_ref)
    if not context['runtime'].get('deveval', {}).get('source_manifest_path'):
        project_component = '/' + job['project'] + '/'
        for ref in context['frozen'].get('private_references', []):
            if project_component in ref['path'].replace('\\', '/'):
                memory.checked(ref)
    if row.get('grade_status') == 'GRADED':
        validate_grade(context, job, row, collection_ref)
        return row
    if row['status'] != 'SUBMITTED':
        return row
    cell = cell_path(context, job)
    folder = cell / 'private-grade'
    request_path = folder / 'request.json'
    if folder.exists():
        if not (folder / 'receipt.json').exists():
            return {**row, 'grade_status': 'INFRA_ERROR', 'passed': None, 'grade_error_type': 'InterruptedGradeNoRetry'}
    else:
        folder.mkdir()
        state = memory.read(cell / 'state.json')
        (folder / 'candidate.py').write_bytes(state['candidate'].encode())
        runtime = context['runtime']
        request = expected_grade_request(context, job, row, collection_ref)
        write(request_path, request)
        command = native.core.execution_command(runtime, 'deveval_repository_grade.py', ['run', native.core.mapped_path(request_path, runtime)])
        started = time.monotonic()
        with (folder / 'transport.stdout.log').open('xb') as stdout, (folder / 'transport.stderr.log').open('xb') as stderr:
            try:
                result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=150,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                transport_error = result.returncode != 0
            except subprocess.TimeoutExpired:
                transport_error = True
        if transport_error or not (folder / 'receipt.json').exists():
            return {**row, 'grade_status': 'INFRA_ERROR', 'passed': None, 'grade_error_type': 'OfficialTransportFailure',
                    'grade_seconds': time.monotonic()-started}
    receipt = validate_grade(context, job, row, collection_ref)
    answer = {**row, 'grade_status': receipt['status'], 'passed': receipt['passed'],
        'grade_reference': memory.reference(folder / 'receipt.json'), 'grade_seconds': receipt['elapsed_total_seconds']}
    write(cell / 'cell-receipt.json', answer)
    return answer


def run(plan_path, runtime_path, snapshots_path, eligibility_path, output, *, prepare_only=False):
    output = Path(output).resolve()
    started = time.monotonic()
    with original_manager.exclusive_lock(output):
        context = load(plan_path, runtime_path, snapshots_path, eligibility_path, output)
        if prepare_only:
            return {'status': 'PREPARED', 'planned_cells': len(context['frozen']['schedule']), 'model_calls': 0}
        rows, captures, bank_ref, candidates = [], [], None, []
        for phase in PHASES:
            jobs = [job for job in context['frozen']['schedule'] if job['phase'] == phase]
            for index in range(0, len(jobs), 2):
                batch = jobs[index:index+2]
                # Same target arms never overlap, even when schedule interleaving changes.
                workers = 1 if len({job['task_id'] for job in batch}) < len(batch) else 2
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = []
                    for position, job in enumerate(batch, index):
                        selected_id = None
                        if phase == 'VERIFICATION':
                            available = sorted(c['procedure_id'] for c in candidates if c['project'] == job['project'])
                            prior = sum(j['project'] == job['project'] for j in jobs[:position])
                            selected_id = available[prior % len(available)] if available else None
                        active_bank = bank_ref if job['condition'] not in ('OFF', 'TRAIN') else None
                        futures.append(pool.submit(collect, context, job, active_bank, selected_id))
                    rows.extend(future.result() for future in futures)
                checkpoint(context, rows, phase, 'COLLECTING', started, bank_ref)
                if any(row['status'] == 'HELD' for row in rows):
                    return checkpoint(context, rows, phase, 'HELD', started, bank_ref, 'NO_AUTOMATIC_PARTIAL_MODEL_RETRY')
            sealed = seal(context, phase, rows)
            if phase in ('DISCOVERY', 'VERIFICATION'):
                for job in jobs:
                    captures.append(memory.capture(cell_path(context, job), phase=phase, owner=context['owner'], project=job['project'], task_id=job['task_id']))
                stage = 'PROVISIONAL' if phase == 'DISCOVERY' else 'FINAL'
                bank_ref = memory.freeze(output / ('bank-' + stage.lower() + '.json'), owner=context['owner'], stage=stage,
                    captures=captures, plan_reference=context['plan_reference'])
                candidates = memory.load(bank_ref, owner=context['owner'])['candidates']
            # All official scores, including TRAIN, are withheld until all target solves complete.
            verify_collection(sealed)
            verify(context)
        for index, row in enumerate(rows):
            job = context['frozen']['schedule'][row['ordinal']-1]
            rows[index] = grade(context, job, row, memory.reference(output / row['phase'] / 'collection.json'))
            checkpoint(context, rows, row['phase'], 'GRADING', started, bank_ref)
        verify(context)
        unresolved = any(row['passed'] is None for row in rows)
        return checkpoint(context, rows, 'COMPLETE', 'COMPLETE_WITH_UNRESOLVED' if unresolved else 'COMPLETE', started, bank_ref)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--plan', type=Path, default=ROOT / 'configs/skhynix_v1/deveval_002_plan.json')
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--eligibility', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.plan, args.runtime, args.snapshots, args.eligibility, args.output, prepare_only=args.mode == 'prepare')
        print(json.dumps({key: result[key] for key in ('status', 'phase', 'planned_cells', 'recorded_cells', 'reason') if key in result}))
    except Exception as error:
        print(json.dumps({'status': 'ERROR', 'exception_type': type(error).__name__,
            'error_code': str(error) if isinstance(error, ValueError) else 'REPOSITORY_EXPERIMENT_FAILED'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
