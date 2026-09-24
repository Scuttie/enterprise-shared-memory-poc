"""Prepare source-only continuation after Pytest8950's undetermined grade.

This helper never launches, solves, grades or rewrites retained attempts. It
revalidates their public traces in a fresh learning authority and preserves the
exact unattempted suffix of the fixed training schedule.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
SYSTEM_TEMP = Path('/mnt/c/Users/jewon/AppData/Local/Temp')
BASE = Path('/home/trimem-runner/skhynix-architecture-scale-001')
ART = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
CFG = REPO / 'configs/skhynix_v1'
TASK = 'swebench--pytest-dev__pytest-8950'
PRIOR_HELPER = SYSTEM_TEMP / 'skhynix_scale_recovery003_prepare.py'
PRIOR_HELPER_SHA = 'e76722a7067e5ba4a61d5f8e12a9c29af9f857de6d6aa1fefab7d7152cb93175'
OLD_PIPELINE_SHA = '428b062830eb5de92874c40bdcd0a86dd3963efce2e523819a26f84a7a7dda85'
OLD_TAIL_SHA = '02f1a55aa355e43f7aa2fa004288b3505ecfb375930575086d6963a93291f989'
COHORT_TAIL_SHA = 'c917480059a39d5f1264f5e10f90723ab4f083da6bfe31c4e9a91f535c5219a2'
SUMMARY_SHA = '82e64f874a51dee6f6a08e6cd7a9191d0398f80459534ca42c728ea12ef66988'
ABANDONED_PRELAUNCH_SHA = '3b9e35ab3d425dfc63d3ddd91073bbc0ae262b1c47822b3fc13b67c29ca1f8ad'
ABANDONED_INTENT_SHA = '0bb6e6835c5c8cf57af3f58c9217ed5ea4c0169c5fdc6f3b6282f8cd15e4de05'
CLASSIFIER_PATH = 'scripts/trimem_skhynix_architecture_run.py'
RUNTIME_CHANGED_PATHS = sorted([
    CLASSIFIER_PATH,
    'scripts/trimem_skhynix_architecture_cohort.py',
    'scripts/trimem_skhynix_architecture_cleanup.py',
])
TRAINING_GRADE_HOLD_POLICY = 'CAPTURE_KNOWN_TERMINAL_AMBIGUITY_AND_CONTINUE'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


assert hashlib.sha256(PRIOR_HELPER.read_bytes()).hexdigest() == PRIOR_HELPER_SHA
u = load('_recovery012_primitives', PRIOR_HELPER)
require, ref, checked, read = u.require, u.ref, u.checked, u.read
retain, canonical, digest, future_ref, chain = u.retain, u.canonical, u.digest, u.future_ref, u.chain


def progress(stage, **fields):
    print(json.dumps({'recovery_version': 12, 'stage': stage, **fields}, sort_keys=True), flush=True)


class PreparationExecutionCache:
    """Process-local validation reuse during public capture, never native work.

    Every cached access hashes its configuration. All dependencies retain their
    size, inode and timestamps during capture; all bytes and the full original
    validator are checked again before a preparation receipt can be published.
    """
    def __init__(self, learning, references, protected_references):
        self.learning = learning
        self.references = references
        self.protected = {item['path']: item for item in protected_references}
        self.original = learning._execution
        self.values = {}
        self.metadata = {}

    @staticmethod
    def _stamp(path):
        value = Path(path).stat()
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def check_bytes(self):
        for path, reference in self.protected.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != reference['sha256']:
                raise ValueError('Preparation dependency changed: ' + path)

    def check_metadata(self):
        for path, stamp in self.metadata.items():
            if self._stamp(path) != stamp:
                raise ValueError('Preparation dependency metadata changed: ' + path)

    def _cached(self, reference):
        if hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest() != reference['sha256']:
            raise ValueError('Preparation execution reference changed')
        key = (reference['path'], reference['sha256'])
        if key not in self.values:
            self.values[key] = self.original(reference)
        return deepcopy(self.values[key])

    def __enter__(self):
        self.check_bytes()
        self.metadata = {path: self._stamp(path) for path in self.protected}
        self.learning._execution = self._cached
        return self

    def verify_complete(self):
        self.check_metadata()
        self.check_bytes()
        # Direct calls avoid this cache and exercise the full original loader,
        # including every recursive source-adoption validation.
        for reference in self.references:
            expected = self._cached(reference)
            if self.original(reference) != expected:
                raise ValueError('Full preparation validation changed')
        self.check_metadata()
        self.check_bytes()

    def __exit__(self, exc_type, exc, traceback):
        self.learning._execution = self.original
        self.values.clear()


def preparation_dependencies(plan):
    references = list(plan['preserved_references'])
    references.extend([plan['execution240_reference'],
        ref(Path(plan['execution240_reference']['path']).with_suffix('.sha256'))])
    for execution_ref in plan['learning_execution_references']:
        config = checked(execution_ref)
        references.extend([execution_ref, ref(Path(execution_ref['path']).with_suffix('.sha256')),
            config['dataset_manifest'], config['image_index'],
            {'path': config['loader_preflight_path'], 'sha256': config['loader_preflight_sha256']}])
        references.extend({'path': str(Path(config['source_root']) / name), 'sha256': sha}
            for name, sha in config['source_sha256'].items())
        if config.get('scale_authority_reference'):
            authority_ref = config['scale_authority_reference']
            references.append(authority_ref)
            authority = checked(authority_ref)
            if authority.get('source_adoption_reference'):
                adoption_ref = authority['source_adoption_reference']
                references.append(adoption_ref)
                adoption = checked(adoption_ref)
                references.extend(adoption['predecessor_configrefs'])
                references.extend(value for row in adoption['rows'] for key, value in row.items()
                    if key.endswith('_reference') and value)
    return list({item['path']: item for item in references}.values())


def approved_native_terminal(submission, audit):
    """Keep native completion and an audited budget seal distinct and faithful."""
    if submission.get('agent_completed') is True and submission.get('reason') == 'WORKER_SUBMITTED':
        return True
    workers = audit.get('workers')
    return (submission.get('agent_completed') is False
        and submission.get('reason') == 'NATIVE_WORKER_WALL_LIMIT'
        and isinstance(workers, list) and bool(workers)
        and all(isinstance(worker, dict) and worker.get('outcome') in ('COMPLETE', 'BUDGET_TIMEOUT')
            for worker in workers)
        and any(worker['outcome'] == 'BUDGET_TIMEOUT' for worker in workers))


def source_row(path, *, execution_ref, task_id, summary=None):
    path = Path(path)
    cell, audit, submission, state = (read(path.parent / name) for name in
        ('cell.json', 'execution-audit.json', 'broker/submission.json', 'broker/state.json'))
    execution = checked(execution_ref)
    patch = ref(path.parent / 'broker/submission.diff')
    require(path == Path(execution['run_root']) / 'cells/TRAINING' / task_id / 'PDF_MEMORY/cell.json', 'Source cell left original root')
    require(cell['experiment_config'] == execution_ref['path'] and cell['task_public']['task_id'] == task_id
        and cell['phase'] == 'TRAINING' and cell['arm'] == 'PDF_MEMORY' and cell['bank_reference'] is None,
        'Source execution/task/arm changed')
    require(digest(canonical(cell)) == path.with_suffix('.sha256').read_text().strip(), 'Source checksum changed')
    require(audit['passed'] is True and audit['errors'] == [] and audit['task_id'] == task_id
        and audit['configuration_sha256'] == digest(canonical(execution)) and audit['patch_sha256'] == patch['sha256'],
        'Source lacks matching passed native audit')
    require(submission['task_id'] == task_id and submission['patch_sha256'] == patch['sha256']
        and submission['configuration_sha256'] == audit['configuration_sha256']
        and state['status'] == 'SUBMITTED' and state['unfinished_actions'] == 0, 'Source is not sealed')
    result_path = path.parent / 'public-result.json'
    if summary is None:
        result = read(result_path)
        require(result['official'] is True and result['grader_status'] == 'success' and type(result['resolved']) is bool
            and result['task_id'] == task_id and result['patch_sha256'] == patch['sha256']
            and result['experiment_sha256'] == audit['configuration_sha256']
            and result['execution_audit_sha256'] == ref(path.parent / 'execution-audit.json')['sha256'],
            'Official result is incomplete or mismatched')
    else:
        require(task_id == TASK and not result_path.exists() and (path.parent / 'grader-pending.json').is_file()
            and not (path.parent / 'native-execution-failure.json').exists()
            and (path.parent / 'broker/submission.diff').stat().st_size > 0
            and approved_native_terminal(submission, audit),
            'Undetermined source lifecycle changed')
        pending = read(path.parent / 'grader-pending.json')
        require(pending['patch_sha256'] == patch['sha256'], 'Pending grader patch binding changed')
    return {'task_id': task_id, 'cell_reference': ref(path), 'audit_reference': ref(path.parent / 'execution-audit.json'),
        'submission_reference': ref(path.parent / 'broker/submission.json'), 'submission_patch_reference': patch,
        'official_result_reference': ref(result_path) if summary is None else None,
        'official_summary_reference': ref(summary) if summary is not None else None,
        'classification': 'AMBIGUOUS_NO_TESTS_COLLECTED' if summary is not None else 'OFFICIAL_COMPLETE'}


def runtime_reference(reference, old_root, new_root, changed_paths=()):
    relative = Path(reference['path']).relative_to(old_root)
    updated = ref(new_root / relative)
    require(str(relative) in changed_paths or updated['sha256'] == reference['sha256'],
        'An unrelated frozen helper changed: ' + str(relative))
    return updated


def runtime_amendment(args, old_execution_ref, old_execution):
    runtime_ref = ref(args.runtime_change)
    runtime = checked(runtime_ref)
    require(runtime['schema'] == 'skhynix/grading-continuation-runtime-freeze/1.0'
        and runtime['previous_execution_reference'] == old_execution_ref
        and runtime['old_source_root'] == old_execution['source_root']
        and runtime['old_source_sha256'] == old_execution['source_sha256']
        and runtime['source_root'] == str(args.source_root)
        and runtime['changed_paths'] == RUNTIME_CHANGED_PATHS
        and runtime['model_calls'] == 0 and runtime['official_grader_runs'] == 0,
        'Runtime amendment is not the reviewed training-only revision')
    old_hashes, new_hashes = runtime['old_source_sha256'], runtime['source_sha256']
    require(set(old_hashes) == set(new_hashes)
        and sorted(name for name in old_hashes if old_hashes[name] != new_hashes[name]) == RUNTIME_CHANGED_PATHS,
        'Runtime amendment changed unrelated files')
    require(Path(runtime['source_root']).is_absolute()
        and Path(runtime['source_root']).resolve() != Path(runtime['old_source_root']).resolve(),
        'Runtime amendment must use a fresh frozen source')
    for name, expected in new_hashes.items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts
            and ref(args.source_root / name)['sha256'] == expected, 'Frozen runtime bytes changed: ' + name)
    loader_ref = ref(args.loader_preflight)
    checked(loader_ref)
    fields = {'source_root': runtime['source_root'], 'source_sha256': deepcopy(new_hashes),
        'loader_preflight_path': loader_ref['path'], 'loader_preflight_sha256': loader_ref['sha256'],
        'training_grade_hold_policy': TRAINING_GRADE_HOLD_POLICY}
    return runtime_ref, loader_ref, fields


def abandoned_prelaunch(reference, *, verify_preserved=True):
    """Preserve the never-launched v11 preparation without adopting its outputs."""
    require(reference['sha256'] == ABANDONED_PRELAUNCH_SHA, 'Abandoned preparation receipt changed')
    value = checked(reference)
    require(value['schema'] == 'skhynix/aborted-prelaunch-preparation/1.0'
        and value['status'] == 'ABORTED_BEFORE_NATIVE_WORK'
        and value['preparation_process_stopped'] is True and value['controller_driver_stopped'] is True
        and value['original_attempts_changed'] is False and value['solver_retries'] is False
        and value['official_grader_retries'] is False
        and all(type(value.get(key)) is int and value[key] == 0 for key in
            ('pipeline_events', 'training_cells', 'native_workers', 'model_calls',
             'official_grader_runs', 'captured_source_cells')), 'Abandoned preparation had actual experiment work')
    require(value['pipeline_reference']['path'] == str(CFG / 'architecture_002_pipeline_v11.json')
        and value['execution_reference']['path'] == str(CFG / 'architecture_002_training_120_v9.json'),
        'Abandoned preparation configuration identity differs')
    pipeline, execution = checked(value['pipeline_reference']), checked(value['execution_reference'])
    require(pipeline['training_experiment_reference'] == value['execution_reference']
        and pipeline['training_stages'][1]['execution_reference'] == value['execution_reference']
        and pipeline['pipeline_root'] == value['pipeline_root'] == str(BASE / 'pipeline-v11')
        and execution['run_root'] == value['training_root'] == str(BASE / 'training-120-v9')
        and execution['native_control_root'] == value['native_root'] ==
            str(SYSTEM_TEMP / 'skhynix-architecture-scale-001-native-v10/training-120')
        and execution['source_root'] == value['source_runtime_root'] ==
            str(SYSTEM_TEMP / 'skhynix-architecture-scale-001-source-v4'),
        'Abandoned preparation root binding differs')
    archived_active = ref(ART / 'active-controller-v10.json')
    require(archived_active['sha256'] == value['active_predecessor_reference']['sha256']
        and ref(ART / 'active-controller.json') == value['active_predecessor_reference'],
        'The active predecessor changed after the abandoned preparation')
    intent_ref = ref(ART / 'source-recovery-011.json.intent.json')
    require(intent_ref['sha256'] == ABANDONED_INTENT_SHA, 'Abandoned preparation intent bytes changed')
    intent = checked(intent_ref)
    require(intent['pipeline_reference'] == value['pipeline_reference']
        and intent['execution_reference'] == value['execution_reference']
        and intent['recovery_version'] == 11 and intent['source_attempts'] == 86
        and intent['model_calls'] == 0 and intent['official_grader_runs'] == 0,
        'The abandoned preparation intent differs from its retained configuration')
    preserved = [reference, archived_active, intent_ref, pipeline['pipeline_source_reference'],
        *value['preserved_references'], *intent['preserved_references']]
    preserved = sorted({item['path']: item for item in preserved}.values(), key=lambda item: item['path'])
    if verify_preserved:
        u.verify_refs(preserved)
    pipeline_root, training_root = Path(value['pipeline_root']), Path(value['training_root'])
    require(not list((pipeline_root / 'events').glob('*.json'))
        and not (pipeline_root / 'pipeline-binding.json').exists()
        and not (training_root / 'cohort').exists()
        and not list((training_root / 'cells').glob('**/cell.json'))
        and not Path(value['native_root']).exists()
        and not Path(pipeline['reflection_native_root']).exists()
        and not Path(pipeline['evaluation_native_root']).exists(),
        'The abandoned preparation started a controller or model cell')
    for path in (ART / 'processes').glob('*'):
        require('architecture_002_pipeline_v11' not in path.name,
            'A launcher artifact appeared for the abandoned preparation')
    require(not (ART / 'active-controller-v11.json').exists()
        and not (ART / 'startup-validation-v11.json').exists()
        and not (ART / 'source-recovery-011.json').exists(), 'Abandoned preparation was activated or completed')
    actual = [*u.tree_refs(pipeline_root), *u.tree_refs(training_root)]
    indexed = {item['path']: item for item in preserved}
    require(all(indexed.get(item['path']) == item for item in actual),
        'Unrecorded output appeared in the abandoned preparation tree')
    return value, preserved


def build(args):
    progress('VALIDATE_PREDECESSOR')
    old_ref = ref(args.previous_pipeline)
    require(old_ref['sha256'] == OLD_PIPELINE_SHA, 'Only exact reviewed pipeline-v10 may continue')
    old = checked(old_ref)
    abandoned_ref = ref(args.abandoned_prelaunch)
    abandoned, abandoned_refs = abandoned_prelaunch(abandoned_ref)
    stage24, stage120, stage240 = old['training_stages']
    old_execution_ref = stage120['execution_reference']
    old_execution = checked(old_execution_ref)
    old_recovery_ref = ref(args.previous_recovery)
    old_recovery = checked(old_recovery_ref)
    require(old_recovery['pipeline_reference'] == old_ref and old_recovery['source_attempts'] == 85
        and old_recovery['official_complete'] == 80 and old_recovery['official_undetermined'] == 5,
        'Original v10 recovery authority changed')
    historical_ref = old['grading_continuation_reference']
    historical = checked(historical_ref)
    global_adoption = checked(old['source_adoption_reference'])
    require(global_adoption['source_count'] == 21 and global_adoption['official_complete'] == 19,
        'Original21 adoption changed')
    controller_ref = ref(args.controller)
    require(controller_ref['sha256'] == args.controller_sha256, 'Controller differs from reviewed freeze')
    runtime_ref, loader_ref, runtime_fields = runtime_amendment(args, old_execution_ref, old_execution)
    execution, learning, controller = u.modules({**old_execution, **runtime_fields}, args.controller)
    require(hasattr(controller, 'validate_grading_continuation'), 'Controller lacks grading-continuation validation')
    original_authority = checked(old_execution['scale_authority_reference'])
    require(original_authority['purpose'] == 'TRAINING_INCREMENT' and len(original_authority['task_ids']) == 35,
        'Original35 authority changed')
    prior_adoption_ref = original_authority['source_adoption_reference']
    prior_adoption = checked(prior_adoption_ref)
    require(prior_adoption['source_count'] == 61 and prior_adoption['official_complete'] == 58,
        'Prior increment adoption61 changed')
    cohort_root = Path(old_execution['run_root']) / 'cohort'
    cohort = read(cohort_root / 'cohort.json')
    schedule = cohort['schedule']
    require([row['task_id'] for row in schedule] == original_authority['task_ids']
        and schedule[0]['task_id'] == TASK, 'Original fixed schedule changed')
    events, event_refs = chain(old['pipeline_root'])
    cohort_events, cohort_refs = chain(cohort_root)
    require(len(events) == 4 and event_refs[-1]['sha256'] == OLD_TAIL_SHA
        and events[-1]['stage'] == 'PIPELINE_BLOCKED', 'Predecessor pipeline advanced or changed')
    require(len(cohort_events) == 6 and cohort_refs[-1]['sha256'] == COHORT_TAIL_SHA
        and cohort_events[-1]['stage'] == 'INFRA_ERROR' and cohort_events[-1]['task_id'] == TASK
        and cohort_events[-1]['details']['error_type'] == 'GraderInvocationFailure',
        'Predecessor cohort advanced or changed')
    require(not any(event['stage'] == 'CELL_COMPLETE' for event in cohort_events),
        'A completed source appeared after the reviewed first-task grading interruption')
    targets = {row['target_id']: row for row in checked(old_execution['dataset_manifest'])['targets']}
    for row in schedule[1:]:
        require(not Path(row['cell_config']).parent.parent.exists(), 'A remaining source already has cell artifacts')
        require(not (Path(old_execution['native_control_root']) / 'TRAINING' / targets[row['task_id']]['instance_id']).exists(),
            'A remaining source already has native artifacts')
    folder = Path(schedule[0]['cell_config']).parent
    summary = Path(old_execution['run_root']) / ('environment/TRAINING/cells/PDF_MEMORY/' + TASK +
        '/official-grader/' + TASK + '/report/trimem-v1-PDF_MEMORY.0b52011f71e9ff87fb1c.json')
    require(ref(summary)['sha256'] == SUMMARY_SHA, 'Retained aggregate changed')
    diagnostic_ref = ref(args.diagnostic)
    diagnostic = checked(diagnostic_ref)
    require(diagnostic['configuration_reference'] == old_ref and diagnostic['task_id'] == TASK and
        diagnostic['classification'] == 'AMBIGUOUS_NO_TESTS_COLLECTED' and
        diagnostic['pipeline_event_tail_reference'] == event_refs[-1] and
        diagnostic['cohort_event_tail_reference'] == cohort_refs[-1] and
        diagnostic['aggregate_reference'] == ref(summary), 'The diagnostic differs from the exact retained stop')
    for key, name in (('cell_reference', 'cell.json'), ('audit_reference', 'execution-audit.json'),
                     ('grader_pending_reference', 'grader-pending.json'),
                     ('submission_patch_reference', 'broker/submission.diff')):
        require(diagnostic[key] == ref(folder / name), 'Retained diagnostic evidence changed: ' + key)
    aggregate = read(summary)
    instance = 'pytest-dev__pytest-8950'
    require(all(aggregate.get(key) == 1 for key in ('total_instances', 'submitted_instances', 'completed_instances',
        'unresolved_instances', 'ambiguous_failure_instances'))
        and all(aggregate.get(key) == 0 for key in ('resolved_instances', 'infra_failure_instances',
        'empty_patch_instances', 'error_instances', 'unstopped_instances'))
        and aggregate.get('failure_reasons') == {instance: 'no_tests_collected'}
        and aggregate.get('ambiguous_failure_ids') == [instance]
        and aggregate.get('incomplete_ids') == [] and aggregate.get('unstopped_containers') == [],
        'Expected exact terminal ambiguous aggregate')
    added = [source_row(row['cell_config'], execution_ref=old_execution_ref, task_id=row['task_id'],
        summary=summary if row['task_id'] == TASK else None) for row in schedule[:1]]
    rows = deepcopy(prior_adoption['rows']) + added
    adoption = {'schema': 'skhynix/architecture-scale-source-adoption/1.0', 'source_count': 62, 'official_complete': 58,
        'predecessor_configrefs': prior_adoption['predecessor_configrefs'] + [old_execution_ref], 'rows': rows,
        'model_calls': 0, 'official_grader_runs': 0, 'outcome_retries': False,
        'scope': 'ORIGINAL_TRAINING_INCREMENT120_ONLY',
        'reason': 'Retain the prior61 plus the next sealed source; Pytest8950 remains officially undetermined; execute only unattempted remaining34.'}
    adoption_ref = future_ref(args.adoption_output, adoption)
    remaining = original_authority['task_ids'][1:]
    require(len(remaining) == 34 and remaining[0] == 'swebench--pytest-dev__pytest-6116', 'Exact remaining34 suffix changed')
    authority = {**deepcopy(original_authority), 'task_ids': remaining, 'source_adoption_reference': adoption_ref,
        'adopted_source_task_ids': [row['task_id'] for row in rows]}
    authority_ref = future_ref(args.authority_output, authority)
    new_execution = {**deepcopy(old_execution), **runtime_fields, 'run_root': str(args.training_root),
        'native_control_root': str(args.native_root), 'scale_authority_reference': authority_ref,
        'prelaunch_revision': {'previous_configuration_reference': old_execution_ref,
            'reason': 'Retain the audited budget-terminal Pytest8950 attempt as officially undetermined; continue the fixed unattempted suffix under the explicit training-only grade-hold policy.',
            'native_outcome_retries': False, 'official_outcome_retries': False, 'original_attempts_preserved': True}}
    new_execution_ref = future_ref(args.execution_output, new_execution)
    old240 = checked(stage240['execution_reference'])
    require(old240['source_root'] == old_execution['source_root']
        and old240['source_sha256'] == old_execution['source_sha256'], 'Unused stage240 runtime differs')
    require(not any((Path(old240['run_root']) / 'cells').glob('TRAINING/*'))
        and not list((Path(old240['run_root']) / 'cohort/events').glob('*.json')),
        'Stage240 already started')
    new240 = {**deepcopy(old240), **runtime_fields}
    new240_ref = future_ref(args.execution240_output, new240)
    continuation = {'schema': 'skhynix/architecture-scale-grading-continuation/3.0',
        'operation': 'CONTINUE_AFTER_UNDETERMINED_SOURCE_GRADE', 'task_id': TASK,
        'official_outcome': 'UNDETERMINED', 'resolved': None, 'classification': 'AMBIGUOUS_NO_TESTS_COLLECTED',
        'source_only': True, 'native_retries': False, 'official_grader_retries': False,
        'model_calls': 0, 'official_grader_runs': 0,
        'predecessor_pipeline_reference': old_ref, 'historical_grading_continuation_reference': historical_ref,
        'predecessor_pipeline_event_tail_reference': event_refs[-1],
        'predecessor_cohort_event_tail_reference': cohort_refs[-1],
        'old_execution_reference': old_execution_ref, 'new_execution_reference': new_execution_ref,
        'source_adoption_reference': adoption_ref, 'old_cell_reference': ref(folder / 'cell.json'),
        'audit_reference': ref(folder / 'execution-audit.json'), 'submission_reference': ref(folder / 'broker/submission.json'),
        'submission_patch_reference': ref(folder / 'broker/submission.diff'),
        'grader_pending_reference': ref(folder / 'grader-pending.json'), 'official_summary_reference': ref(summary),
        'runtime_change_reference': runtime_ref, 'loader_preflight_reference': loader_ref,
        'native_binary_reference': historical['native_binary_reference']}
    continuation_ref = future_ref(args.continuation_output, continuation)
    config = {**deepcopy(old), 'pipeline_root': str(args.pipeline_root), 'pipeline_source_reference': controller_ref,
        'grading_continuation_reference': continuation_ref, 'supersedes_configuration_reference': old_ref,
        'training_experiment_reference': new_execution_ref,
        'training_stages': [deepcopy(stage24), {'size': 120, 'execution_reference': new_execution_ref,
            'learning_root': str(Path(args.pipeline_root) / 'learning-120')},
            {**deepcopy(stage240), 'execution_reference': new240_ref}],
        'helper_references': {name: runtime_reference(value, Path(old_execution['source_root']), args.source_root,
            RUNTIME_CHANGED_PATHS if name in ('cohort', 'cleanup') else ())
            for name, value in old['helper_references'].items()},
        'reflection_source_reference': runtime_reference(old['reflection_source_reference'],
            Path(old_execution['source_root']), args.source_root),
        'reflection_native_root': str(args.reflection_native_root), 'evaluation_native_root': str(args.evaluation_native_root),
        'revision_reason': 'Retain86 sealed sources, including six undetermined grades; continue remaining34 without retries, with an explicit training-only terminal-grade-hold policy.'}
    prior24 = checked(stage24['execution_reference'])
    prior24_cohort = read(Path(prior24['run_root']) / 'cohort/cohort.json')
    prior24_events, prior24_refs = chain(Path(prior24['run_root']) / 'cohort')
    require(prior24_events[-1]['stage'] == 'CLEANED' and prior24_events[-1]['ordinal'] == 3, 'Stage24 completion changed')
    sources = [row['cell_reference'] for row in global_adoption['rows']]
    sources += [ref(row['cell_config']) for row in prior24_cohort['schedule']]
    sources += [row['cell_reference'] for row in rows]
    require(len(sources) == 86 and len({read(item['path'])['task_public']['task_id'] for item in sources}) == 86,
        'Retained86 source composition differs')
    quota = checked(old['infrastructure_replacement_reference'])
    require(quota['old_cell_reference'] not in sources, 'Quota-failed attempt entered memory sources')
    old_learning = Path(stage120['learning_root'])
    enrollment = read(old_learning / 'learning-enrollment.json')
    references = enrollment['execution_references'] + [new_execution_ref]
    require(len(references) == 10 and not (old_learning / 'learning-frozen.json').exists(),
        'Learning authority changed or is already published')
    registry = read(old_learning / 'learning-state.json')
    require(len(registry['cells']) == 85, 'Retained learning count changed')
    catalog = read(old_learning / 'catalog.json')
    require(not catalog['skills'] and not catalog['proposals'] and not catalog['observations'], 'Reflection/promotion already exists')
    outputs = [(args.adoption_output, adoption), (args.authority_output, authority), (args.execution_output, new_execution),
        (args.execution240_output, new240),
        (args.continuation_output, continuation), (args.pipeline_output, config)]
    # Retain the entire already-validated history of quota, preparation and
    # pre-admission launch failures; only the new v10 tails are added to it.
    preserved = list(old_recovery['preserved_references']) + event_refs + cohort_refs + prior24_refs + abandoned_refs
    preserved += [old_ref, old_execution_ref, old_recovery_ref, historical_ref, diagnostic_ref, old['source_adoption_reference'],
        old['infrastructure_replacement_reference'], stage24['execution_reference'], stage24['inherited_bank_reference'],
        stage240['execution_reference'], prior_adoption_ref, ref(folder / 'grader-pending.json'), runtime_ref, loader_ref]
    preserved += [ref(args.source_root / name) for name in runtime_fields['source_sha256']]
    preserved += [value for row in [*global_adoption['rows'], *rows] for key, value in row.items()
        if key.endswith('_reference') and value]
    for source in sources:
        source_folder = Path(source['path']).parent
        preserved += [ref(source_folder / name) for name in ('cell.sha256', 'broker/state.json', 'broker/events.jsonl')]
    preserved += u.tree_refs(old_learning)
    new_roots = [Path(path).resolve() for path in (args.pipeline_root, args.training_root, args.native_root,
        args.reflection_native_root, args.evaluation_native_root)]
    protected = [Path(value).resolve() for value in (old['pipeline_root'], old_execution['run_root'], old_learning,
        prior24['run_root'], old_execution['native_control_root'], prior24['native_control_root'],
        old['reflection_native_root'], old['evaluation_native_root'], old_execution['source_root'], args.source_root)]
    protected += [Path(abandoned[key]).resolve() for key in
        ('pipeline_root', 'training_root', 'native_root', 'source_runtime_root')]
    for index, new_root in enumerate(new_roots):
        require(new_root.is_absolute() and all(new_root != other and other not in new_root.parents and new_root not in other.parents
            for other in protected + new_roots[index + 1:]), 'Recovery roots overlap retained work')
    require(not list(Path(args.pipeline_root).glob('events/*.json')) and not (Path(args.training_root) / 'cohort').exists()
        and not (Path(args.training_root) / 'cells').exists() and not Path(args.native_root).exists()
        and not Path(args.reflection_native_root).exists() and not Path(args.evaluation_native_root).exists(),
        'Recovery already launched; preparation cannot replay')
    for path, value in outputs:
        if Path(path).exists():
            require(ref(path) == future_ref(path, value), 'Existing recovery output differs')
    tails = list(old_recovery['guarded_predecessor_tails']) + [old_recovery['guarded_predecessor_cohort_tail'], event_refs[-1]]
    tails = list({item['path']: item for item in tails}.values())
    plan = {'schema': 'skhynix/architecture-scale-source-recovery-preparation/1.0', 'operation': 'PREPARE_ONLY',
        'recovery_version': 12, 'helper_reference': ref(__file__), 'previous_pipeline_reference': old_ref,
        'previous_recovery_reference': old_recovery_ref, 'pipeline_reference': future_ref(args.pipeline_output, config),
        'aborted_prelaunch_reference': abandoned_ref,
        'aborted_preparation_intent_reference': ref(ART / 'source-recovery-011.json.intent.json'),
        'aborted_prelaunch_preserved_references': abandoned_refs,
        'aborted_prelaunch_outputs_consumed': False,
        'execution_reference': new_execution_ref, 'execution240_reference': new240_ref,
        'source_adoption_reference': old['source_adoption_reference'], 'increment_adoption_reference': adoption_ref,
        'grading_continuation_reference': continuation_ref, 'historical_grading_continuation_reference': historical_ref,
        'runtime_change_reference': runtime_ref, 'loader_preflight_reference': loader_ref,
        'native_binary_reference': historical['native_binary_reference'],
        'infrastructure_replacement_reference': old['infrastructure_replacement_reference'],
        'inherited_bank_reference': stage24['inherited_bank_reference'], 'source_attempts': 86,
        'official_complete': 80, 'official_undetermined': 6, 'undetermined_task_id': TASK,
        'diagnostic_reference': diagnostic_ref,
        'remaining_task_ids': remaining, 'failed_attempt_excluded_from_memory': True,
        'learning_root': str(Path(args.pipeline_root) / 'learning-120'), 'learning_execution_references': references,
        'source_cell_references': sources, 'guarded_predecessor_tails': tails,
        'guarded_predecessor_cohort_tail': cohort_refs[-1],
        'preserved_references': sorted({item['path']: item for item in preserved}.values(), key=lambda item: item['path']),
        'source_runtime_unchanged': False, 'runtime_changed_paths': RUNTIME_CHANGED_PATHS,
        'training_grade_hold_policy': TRAINING_GRADE_HOLD_POLICY, 'grading_semantics_changed': False,
        'source_selection_changed': False,
        'stage24_bank_rerun': False, 'activation_performed': False, 'model_calls': 0, 'solver_runs': 0,
        'official_grader_runs': 0, 'cleanup_runs': 0}
    progress('PLAN_VALIDATED', source_attempts=86, remaining=34, official_undetermined=6)
    return plan, outputs, execution, learning, controller


def prepare(args, plan, outputs, execution, learning, controller):
    intent = Path(str(args.migration_output) + '.intent.json')
    retain(intent, plan)
    for path, value in outputs:
        if Path(path) in (Path(args.execution_output), Path(args.execution240_output), Path(args.pipeline_output)):
            controller.write_execution(Path(path), value)
        else:
            retain(path, value)
    progress('VALIDATE_NEW_AUTHORITY')
    config = read(args.pipeline_output)
    new_execution = execution.load_experiment(args.execution_output)
    require(checked(new_execution['scale_authority_reference']) == read(args.authority_output), 'New authority binding changed')
    controller.validate_config(config, executing_source=Path(args.controller))
    progress('INITIALIZE_PUBLIC_LEARNING')
    with PreparationExecutionCache(learning, plan['learning_execution_references'], preparation_dependencies(plan)) as cache:
        enrollment = learning.initialize_learning(plan['learning_root'], execution_references=plan['learning_execution_references'],
            dataset_reference=new_execution['dataset_manifest'])
        original_capture, captured_count = learning.capture_cell, 0
        def capture_progress(root, path):
            nonlocal captured_count
            cache.check_metadata()
            capture = original_capture(root, path)
            value = checked(capture)
            require(value['status'] in ('CAPTURED', 'NO_PUBLIC_ATTEMPTS'), 'Retained source capture failed')
            captured_count += 1
            progress('SOURCE_CAPTURED', completed=captured_count, total=86,
                task_id=value['task_id'], captures=len(value['captures']))
            return capture
        learning.capture_cell = capture_progress
        try:
            captures = learning.capture_existing_sources(plan['learning_root'], cell_references=plan['source_cell_references'],
                output_path=Path(plan['learning_root']) / 'source-recovery012-captures.json')
        finally:
            learning.capture_cell = original_capture
        progress('FULL_REVALIDATE_EXECUTIONS')
        cache.verify_complete()
    receipt = checked(captures)
    require(receipt['status'] == 'COMPLETE' and len(receipt['sources']) == 86
        and sum(row['task_id'] == TASK for row in receipt['sources']) == 1, 'Retained86 source capture incomplete')
    progress('RECHECK_PRESERVED_EVIDENCE', files=len(plan['preserved_references']))
    u.verify_refs(plan['preserved_references'])
    # The complete preserved list above includes every abandoned-preparation
    # reference; repeat its zero-work/inventory guards without hashing it twice.
    _, abandoned_refs = abandoned_prelaunch(plan['aborted_prelaunch_reference'], verify_preserved=False)
    require(abandoned_refs == plan['aborted_prelaunch_preserved_references'],
        'The abandoned preparation changed while building the new memory authority')
    for tail in [*plan['guarded_predecessor_tails'], plan['guarded_predecessor_cohort_tail']]:
        require(chain(Path(tail['path']).parent.parent)[1][-1] == tail, 'A predecessor advanced during preparation')
    return retain(args.migration_output, {**plan, 'status': 'PREPARED_NOT_LAUNCHED',
        'preparation_intent_reference': ref(intent), 'learning_enrollment_reference': enrollment,
        'source_capture_reference': captures, 'preserved_evidence_rechecked': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'prepare'), nargs='?', default='plan')
    parser.add_argument('--controller', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-controller-v12/trimem_skhynix_architecture_scale_pipeline.py')
    parser.add_argument('--controller-sha256', required=True)
    parser.add_argument('--previous-pipeline', type=Path, default=CFG / 'architecture_002_pipeline_v10.json')
    parser.add_argument('--previous-recovery', type=Path, default=ART / 'source-recovery-010.json')
    parser.add_argument('--diagnostic', type=Path, default=ART / 'retained-grader-diagnostic-005.json')
    parser.add_argument('--abandoned-prelaunch', type=Path, default=ART / 'prelaunch-abort-011.json')
    parser.add_argument('--source-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-source-v5')
    parser.add_argument('--runtime-change', type=Path, default=ART / 'runtime-freeze-012.json')
    parser.add_argument('--loader-preflight', type=Path, default=ART / 'official-harness-loader-v5.json')
    parser.add_argument('--adoption-output', type=Path, default=ART / 'source-adoption-increment120-012.json')
    parser.add_argument('--continuation-output', type=Path, default=ART / 'grading-continuation-012.json')
    parser.add_argument('--execution-output', type=Path, default=CFG / 'architecture_002_training_120_v10.json')
    parser.add_argument('--execution240-output', type=Path, default=CFG / 'architecture_002_training_240_v7.json')
    parser.add_argument('--pipeline-output', type=Path, default=CFG / 'architecture_002_pipeline_v12.json')
    parser.add_argument('--authority-output', type=Path, default=BASE / 'training-120-v10/execution-authority.json')
    parser.add_argument('--pipeline-root', type=Path, default=BASE / 'pipeline-v12')
    parser.add_argument('--training-root', type=Path, default=BASE / 'training-120-v10')
    parser.add_argument('--native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-native-v11/training-120')
    parser.add_argument('--reflection-native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-reflection-v11')
    parser.add_argument('--evaluation-native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-evaluation-v11')
    parser.add_argument('--migration-output', type=Path, default=ART / 'source-recovery-012.json')
    args = parser.parse_args()
    old = read(args.previous_pipeline)
    old_recovery = read(args.previous_recovery)
    tails = [*old_recovery['guarded_predecessor_tails'], old_recovery['guarded_predecessor_cohort_tail']]
    roots = [Path(tail['path']).parent.parent for tail in tails] + [Path(old['pipeline_root']),
        Path(checked(old['training_stages'][1]['execution_reference'])['run_root']) / 'cohort', BASE / 'training-24-v2/cohort']
    with u.inactive_predecessors(roots):
        plan, outputs, execution, learning, controller = build(args)
        if args.command == 'prepare':
            result = {'status': 'PREPARED_NOT_LAUNCHED', 'receipt_reference': prepare(args, plan, outputs, execution, learning, controller)}
        else:
            result = {key: value for key, value in plan.items() if key not in
                ('preserved_references', 'source_cell_references', 'remaining_task_ids')}
            result.update(status='PLAN_ONLY_NO_FILES_WRITTEN', remaining_count=len(plan['remaining_task_ids']),
                first_remaining_task=plan['remaining_task_ids'][0])
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
