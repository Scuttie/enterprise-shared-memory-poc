"""Plan/prepare one quota-interrupted source replacement. Never launch or grade.

Only NEW recovery artifacts and a new learning authority may be written by
prepare. Original sources, failed attempt, grades, banks and runtime stay intact.
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
TASK = 'swebench--django__django-16686'
PRIOR_HELPER = SYSTEM_TEMP / 'skhynix_scale_recovery003_prepare.py'
PRIOR_HELPER_SHA = 'e76722a7067e5ba4a61d5f8e12a9c29af9f857de6d6aa1fefab7d7152cb93175'
OLD_PIPELINE_SHA = '7915f668ebce850c82e95464de963694e4c5e9b65be7efb4d37789ca87e010b1'
OLD_TAIL_SHA = 'c571ba160e35dbf2f22cedec5de9673a064658b9409bee03996b32496fde4105'
COHORT_TAIL_SHA = '8683ecf33bed0910c0b6042a97f26d784312a757b7258e893e23e8e7e53d7dfb'
HEALTH_PATH = SYSTEM_TEMP / 'skhynix-codex-quota-health-20260915T070932Z-e4cd0f6a/receipt.json'
HEALTH_SHA = '1b9434afdae745eb7589f3b2a57bc5d19850476dc25b5d334681b051930b2ca6'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


assert hashlib.sha256(PRIOR_HELPER.read_bytes()).hexdigest() == PRIOR_HELPER_SHA
u = load('_recovery003_primitives', PRIOR_HELPER)
require, ref, checked, read = u.require, u.ref, u.checked, u.read
retain, canonical, digest, future_ref, chain = u.retain, u.canonical, u.digest, u.future_ref, u.chain


def source_row(path, *, execution_ref, target):
    """Only official-complete original increment sources enter stage adoption."""
    path = Path(path)
    cell, audit, submission, result = (read(path.parent / name) for name in
        ('cell.json', 'execution-audit.json', 'broker/submission.json', 'public-result.json'))
    execution = checked(execution_ref)
    task_id = target['task_id']
    patch = ref(path.parent / 'broker/submission.diff')
    require(path == Path(execution['run_root']) / 'cells/TRAINING' / task_id / 'PDF_MEMORY/cell.json', 'Source cell left original root')
    require(cell['experiment_config'] == execution_ref['path'] and cell['task_public']['task_id'] == task_id
        and cell['phase'] == 'TRAINING' and cell['arm'] == 'PDF_MEMORY' and cell['bank_reference'] is None,
        'Source execution/task/arm changed')
    require(digest(canonical(cell)) == path.with_suffix('.sha256').read_text().strip(), 'Source cell checksum changed')
    require(audit['passed'] is True and audit['errors'] == [] and audit['task_id'] == task_id
        and audit['configuration_sha256'] == digest(canonical(execution)) and audit['patch_sha256'] == patch['sha256'],
        'Adopted source lacks matching passed native audit')
    require(submission['task_id'] == task_id and submission['patch_sha256'] == patch['sha256']
        and submission['configuration_sha256'] == audit['configuration_sha256'], 'Original sealed submission differs')
    require(result['official'] is True and result['grader_status'] == 'success' and type(result['resolved']) is bool
        and result['task_id'] == task_id and result['patch_sha256'] == patch['sha256']
        and result['experiment_sha256'] == audit['configuration_sha256']
        and result['execution_audit_sha256'] == ref(path.parent / 'execution-audit.json')['sha256'],
        'Original official result is incomplete or mismatched')
    return {'task_id': task_id, 'cell_reference': ref(path), 'audit_reference': ref(path.parent / 'execution-audit.json'),
        'submission_reference': ref(path.parent / 'broker/submission.json'), 'submission_patch_reference': patch,
        'official_result_reference': ref(path.parent / 'public-result.json'), 'official_summary_reference': None,
        'classification': 'OFFICIAL_COMPLETE'}


def build(args):
    old_ref = ref(args.previous_pipeline)
    require(old_ref['sha256'] == OLD_PIPELINE_SHA, 'Only reviewed scale pipeline-v3 may be replaced')
    old = checked(old_ref)
    stage24, stage120, stage240 = old['training_stages']
    old_execution_ref = stage120['execution_reference']
    old_execution = checked(old_execution_ref)
    global_adoption = checked(old['source_adoption_reference'])
    require(global_adoption['source_count'] == 21 and global_adoption['official_complete'] == 19,
        'Global adoption21 must remain unchanged')
    controller_ref = ref(args.controller)
    require(controller_ref['sha256'] == args.controller_sha256, 'New controller SHA differs from reviewed freeze')
    execution, learning, controller = u.modules(old_execution, args.controller)
    require(hasattr(controller, 'validate_infrastructure_replacement'), 'Controller lacks one-time replacement validation')
    execution.load_experiment(old_execution_ref['path'])
    original_authority = execution.execution_enrollment(old_execution)
    require(original_authority['purpose'] == 'TRAINING_INCREMENT' and len(original_authority['task_ids']) == 96,
        'Original increment authority differs')
    cohort_root = Path(old_execution['run_root']) / 'cohort'
    cohort = read(cohort_root / 'cohort.json')
    schedule = cohort['schedule']
    require([row['task_id'] for row in schedule] == original_authority['task_ids'] and schedule[21]['task_id'] == TASK,
        'Frozen schedule or failed source ordinal changed')
    events, event_refs = chain(old['pipeline_root'])
    cohort_events, cohort_refs = chain(cohort_root)
    require(len(events) == 52 and event_refs[-1]['sha256'] == OLD_TAIL_SHA and events[-1]['stage'] == 'PIPELINE_BLOCKED',
        'Previous pipeline advanced or changed')
    require(len(cohort_events) == 214 and cohort_refs[-1]['sha256'] == COHORT_TAIL_SHA
        and cohort_events[-1]['stage'] == 'INFRA_ERROR' and cohort_events[-1]['task_id'] == TASK,
        'Previous training increment advanced or changed')
    for row in schedule[:21]:
        own = [event for event in cohort_events if event.get('task_id') == row['task_id']]
        require(own[-1]['stage'] == 'CLEANED' and any(event['stage'] == 'CELL_COMPLETE' for event in own),
            'An adopted increment source has unfinished workflow/cleanup')
    for row in schedule[22:]:
        require(not Path(row['cell_config']).parent.parent.exists(), 'A later original source already has artifacts')
    rows = [source_row(row['cell_config'], execution_ref=old_execution_ref, target=row) for row in schedule[:21]]
    adoption = {'schema': 'skhynix/architecture-scale-source-adoption/1.0', 'source_count': 21, 'official_complete': 21,
        'predecessor_configrefs': [old_execution_ref], 'rows': rows, 'model_calls': 0, 'official_grader_runs': 0,
        'outcome_retries': False, 'scope': 'ORIGINAL_TRAINING_INCREMENT120_ONLY',
        'reason': 'Retain completed increment ordinals1-21; the quota-interrupted ordinal22 remains separately excluded.'}
    adoption_ref = future_ref(args.adoption_output, adoption)
    remaining = original_authority['task_ids'][21:]
    require(len(remaining) == 75 and remaining[0] == TASK, 'Recovery must retain exact ordered remaining75')
    authority = {**deepcopy(original_authority), 'task_ids': remaining, 'source_adoption_reference': adoption_ref,
        'adopted_source_task_ids': [row['task_id'] for row in rows]}
    authority_ref = future_ref(args.authority_output, authority)
    new_execution = {**deepcopy(old_execution), 'run_root': str(args.training_root),
        'native_control_root': str(args.native_root), 'scale_authority_reference': authority_ref,
        'prelaunch_revision': {'previous_configuration_reference': old_execution_ref,
            'reason': 'Explicit one-time infrastructure replacement of quota-interrupted django16686; original21 actions retained as separate overhead; no official outcome retried.',
            'protocol_amendment': 'ONE_NATIVE_INFRASTRUCTURE_REPLACEMENT_WITH_FRESH_BUDGET',
            'original_failed_attempt_preserved': True, 'official_outcome_retries': False}}
    new_execution_ref = future_ref(args.execution_output, new_execution)
    failed = Path(schedule[21]['cell_config']).parent
    failed_cell, audit, failure, submission, state = (read(failed / name) for name in
        ('cell.json', 'execution-audit.json', 'native-execution-failure.json', 'broker/submission.json', 'broker/state.json'))
    native_root = Path(old_execution['native_control_root']) / 'TRAINING/django__django-16686/PDF_MEMORY/worker-003/output'
    completion_ref, native_events_ref = ref(native_root / 'completion.json'), ref(native_root / 'events.jsonl')
    completion = checked(completion_ref)
    patch_ref = ref(failed / 'broker/submission.diff')
    require(failed_cell['experiment_config'] == old_execution_ref['path'] and failed_cell['task_public']['task_id'] == TASK,
        'Failed attempt binding changed')
    require(audit['passed'] is False and audit['task_id'] == TASK and audit['patch_sha256'] == patch_ref['sha256']
        and audit['configuration_sha256'] == digest(canonical(old_execution)), 'Failed audit was changed or relabelled')
    require(submission['reason'] == 'NATIVE_WORKER_INFRASTRUCTURE_FAILURE' and submission['actions'] == 21
        and submission['agent_completed'] is False and submission['patch_sha256'] == patch_ref['sha256']
        and state['status'] == 'SUBMITTED' and state['unfinished_actions'] == 0, 'Expected sealed failed attempt21 actions')
    require(failure == {'completion_sha256': completion_ref['sha256'], 'launcher_returncode': 1,
        'worker_id': 'pdf_memory-django__django-16686-3'}, 'Native infrastructure failure differs')
    require(completion['exit_code'] == 1 and completion['admitted'] is True and completion['timed_out'] is False
        and all(completion[key] == [] for key in ('errors', 'transport_errors', 'outside_broker_tool_events'))
        and completion['events_sha256'] == native_events_ref['sha256'], 'Failure was not the reviewed admitted quota failure')
    quota_lines = []
    for number, raw in enumerate((native_root / 'events.jsonl').read_bytes().splitlines(), 1):
        if b'usage limit' in raw.lower() or b'usage_limit' in raw.lower():
            event = json.loads(raw)
            require(event['type'] in ('error', 'turn.failed'), 'Quota marker is not a provider error event')
            quota_lines.append({'line': number, 'sha256': digest(raw), 'event_type': event['type'], 'classification': 'CODEX_USAGE_LIMIT'})
    require(quota_lines and not (failed / 'public-result.json').exists() and not (failed / 'grader-pending.json').exists(),
        'Quota proof missing or an official grading attempt already exists')
    require(ref(HEALTH_PATH)['sha256'] == HEALTH_SHA, 'Independent successful quota-health receipt changed')
    health = read(HEALTH_PATH)
    require(health['classification'] == 'SUCCESS' and health['response_is_exact_OK'] is True
        and health['native_session_attempts'] == 1 and health['tool_event_count'] == 0, 'Quota recovery was not observed')
    replacement = {'schema': 'skhynix/architecture-scale-infrastructure-replacement/1.0',
        'operation': 'AUTHORIZE_ONE_QUOTA_REPLACEMENT', 'task_id': TASK,
        'old_execution_reference': old_execution_ref, 'new_execution_reference': new_execution_ref,
        'old_cell_reference': ref(failed / 'cell.json'), 'audit_reference': ref(failed / 'execution-audit.json'),
        'native_failure_reference': ref(failed / 'native-execution-failure.json'),
        'submission_reference': ref(failed / 'broker/submission.json'), 'submission_patch_reference': patch_ref,
        'native_completion_reference': completion_ref, 'native_events_reference': native_events_ref,
        'predecessor_pipeline_reference': old_ref, 'predecessor_pipeline_event_tail_reference': event_refs[-1],
        'predecessor_cohort_event_tail_reference': cohort_refs[-1], 'historical_actions': 21,
        'fresh_task_requests': 120, 'fresh_task_seconds': 1200, 'replacement_limit': 1, 'reason': 'CODEX_USAGE_LIMIT',
        'original_attempt_excluded_from_memory': True, 'official_outcome_retries': False,
        'protocol_amendment': 'ONE_NATIVE_INFRASTRUCTURE_REPLACEMENT_WITH_FRESH_BUDGET',
        'model_calls': 0, 'official_grader_runs': 0, 'quota_error_line_references': quota_lines,
        'successful_health_probe_reference': ref(HEALTH_PATH), 'helper_reference': ref(__file__)}
    replacement_ref = future_ref(args.replacement_output, replacement)
    bank_events = [(reference, event) for reference, event in zip(event_refs, events)
        if event['stage'] == 'BANK_NOT_READY' and event['job'] == 'bank-24']
    require(len(bank_events) == 1, 'Exactly one prior24 NOT_READY result must be inherited')
    result_ref = bank_events[0][1]['details']['reference']
    bank_status = checked(result_ref)
    require(bank_status['status'] == 'NOT_READY' and bank_status['size'] == 24 and bank_status['source_attempts'] == 24,
        'Stage24 result is not the original completed NOT_READY bank')
    inheritance = {'schema': 'skhynix/architecture-scale-bank-inheritance/1.0',
        'predecessor_pipeline_reference': old_ref, 'event_reference': bank_events[0][0], 'result_reference': result_ref,
        'learning_enrollment_reference': ref(Path(stage24['learning_root']) / 'learning-enrollment.json')}
    inheritance_ref = future_ref(args.inheritance_output, inheritance)
    config = {**deepcopy(old), 'pipeline_root': str(args.pipeline_root), 'pipeline_source_reference': controller_ref,
        'infrastructure_replacement_reference': replacement_ref, 'supersedes_configuration_reference': old_ref,
        'training_stages': [{**deepcopy(stage24), 'inherited_bank_reference': inheritance_ref},
            {'size': 120, 'execution_reference': new_execution_ref, 'learning_root': str(Path(args.pipeline_root) / 'learning-120')},
            deepcopy(stage240)],
        'reflection_native_root': str(args.reflection_native_root), 'evaluation_native_root': str(args.evaluation_native_root),
        'revision_reason': 'Preserve completed24 bank and45 valid public sources; replace only quota-interrupted16686 once under an explicit separate infrastructure-budget amendment.'}
    # The top training template remains the exact inherited24 execution.
    require(config['training_experiment_reference'] == stage24['execution_reference'], 'Top template unexpectedly changed')
    prior24_execution = checked(stage24['execution_reference'])
    prior24_cohort = read(Path(prior24_execution['run_root']) / 'cohort/cohort.json')
    prior24_events, prior24_refs = chain(Path(prior24_execution['run_root']) / 'cohort')
    require(prior24_events[-1]['stage'] == 'CLEANED' and prior24_events[-1]['ordinal'] == 3,
        'Original24 remainder is not completed')
    sources = [row['cell_reference'] for row in global_adoption['rows']]
    sources += [ref(row['cell_config']) for row in prior24_cohort['schedule']]
    sources += [row['cell_reference'] for row in rows]
    require(len(sources) == 45 and len({read(item['path'])['task_public']['task_id'] for item in sources}) == 45
        and TASK not in {read(item['path'])['task_public']['task_id'] for item in sources}, 'Existing45 source composition differs')
    references = global_adoption['predecessor_configrefs'] + [stage24['execution_reference'], old_execution_ref, new_execution_ref]
    outputs = [(args.adoption_output, adoption), (args.authority_output, authority), (args.execution_output, new_execution),
        (args.replacement_output, replacement), (args.inheritance_output, inheritance), (args.pipeline_output, config)]
    preserved = event_refs + cohort_refs + prior24_refs + [old_ref, old_execution_ref, stage24['execution_reference'],
        stage240['execution_reference'], old['source_adoption_reference'], result_ref, ref(failed / 'broker/state.json'),
        ref(failed / 'broker/events.jsonl'), ref(failed / 'cell.sha256'), ref(HEALTH_PATH)]
    preserved += [value for key, value in replacement.items() if key.endswith('_reference') and key != 'new_execution_reference']
    preserved += [value for row in rows for key, value in row.items() if key.endswith('_reference') and value]
    for size in (24, 120):
        previous_learning = Path(old['pipeline_root']) / ('learning-' + str(size))
        require(not (previous_learning / 'learning-frozen.json').exists(), 'Published-memory recovery requires another protocol')
        preserved += [ref(previous_learning / name) for name in ('learning-enrollment.json', 'learning-state.json', 'catalog.json', 'scope.json', 'authority.sqlite3')]
    require(not any((Path(checked(stage240['execution_reference'])['run_root']) / 'cells').glob('TRAINING/*')),
        'Stage240 already started')
    new_roots = list(map(Path, (args.pipeline_root, args.training_root, args.native_root, args.reflection_native_root, args.evaluation_native_root)))
    require(all(path.is_absolute() for path in new_roots), 'Recovery roots must be explicit absolute paths')
    new_roots = [path.resolve() for path in new_roots]
    protected = [Path(value).resolve() for value in (old['pipeline_root'], old_execution['run_root'],
        prior24_execution['run_root'], old_execution['native_control_root'], prior24_execution['native_control_root'],
        old['reflection_native_root'], old['evaluation_native_root'], old_execution['source_root'])]
    for index, new_root in enumerate(new_roots):
        require(all(new_root != other and other not in new_root.parents and new_root not in other.parents
            for other in protected + new_roots[index + 1:]), 'Recovery roots overlap preserved work or each other')
    require(not list(Path(args.pipeline_root).glob('events/*.json')) and not (Path(args.training_root) / 'cohort').exists()
        and not (Path(args.training_root) / 'cells').exists() and not Path(args.native_root).exists()
        and not Path(args.reflection_native_root).exists() and not Path(args.evaluation_native_root).exists(),
        'Recovery has already launched; preparation must not be replayed')
    for path, value in outputs:
        if Path(path).exists():
            require(ref(path) == future_ref(path, value), 'Existing recovery output differs')
    plan = {'schema': 'skhynix/architecture-scale-source-recovery-preparation/1.0', 'operation': 'PREPARE_ONLY',
        'recovery_version': 4, 'helper_reference': ref(__file__), 'previous_pipeline_reference': old_ref,
        'pipeline_reference': future_ref(args.pipeline_output, config), 'execution_reference': new_execution_ref,
        'source_adoption_reference': old['source_adoption_reference'], 'increment_adoption_reference': adoption_ref,
        'infrastructure_replacement_reference': replacement_ref, 'inherited_bank_reference': inheritance_ref,
        'source_attempts': 45, 'official_complete': 43, 'official_undetermined': 2,
        'replacement_task_id': TASK, 'remaining_task_ids': remaining, 'original_failed_actions_overhead': 21,
        'failed_attempt_excluded_from_memory': True, 'learning_root': str(Path(args.pipeline_root) / 'learning-120'),
        'learning_execution_references': references, 'source_cell_references': sources,
        'guarded_predecessor_tails': [global_adoption['original_pipeline_event_tail_reference'],
            *global_adoption.get('predecessor_pipeline_event_tail_references', []), event_refs[-1]],
        'guarded_predecessor_cohort_tail': cohort_refs[-1],
        'preserved_references': sorted({item['path']: item for item in preserved}.values(), key=lambda item: item['path']),
        'source_runtime_unchanged': True, 'source_selection_changed': False, 'stage24_bank_rerun': False,
        'activation_performed': False, 'model_calls': 0, 'solver_runs': 0, 'official_grader_runs': 0, 'cleanup_runs': 0,
        'activation_requirements': ['Parent reviews controller tests and preparation receipt.',
            'Parent verifies all original launchers stopped and launches only new pipelinev4 with a new immutable launch intent.',
            'All predecessor controller/cohort locks and hashes remain guarded for the full replacement execution.']}
    return plan, outputs, execution, learning, controller


def prepare(args, plan, outputs, execution, learning, controller):
    intent = Path(str(args.migration_output) + '.intent.json')
    retain(intent, plan)
    for path, value in outputs:
        if Path(path) in (Path(args.execution_output), Path(args.pipeline_output)):
            controller.write_execution(Path(path), value)
        else:
            retain(path, value)
    config = read(args.pipeline_output)
    new_execution = execution.load_experiment(args.execution_output)
    require(execution.execution_enrollment(new_execution) == read(args.authority_output), 'Runtime rejected remaining75 authority')
    controller.validate_config(config, executing_source=Path(args.controller))
    controller.validate_infrastructure_replacement(config, execution=execution)
    enrollment = learning.initialize_learning(plan['learning_root'], execution_references=plan['learning_execution_references'],
        dataset_reference=new_execution['dataset_manifest'])
    captures = learning.capture_existing_sources(plan['learning_root'], cell_references=plan['source_cell_references'],
        output_path=Path(plan['learning_root']) / 'source-recovery004-captures.json')
    receipt = checked(captures)
    require(receipt['status'] == 'COMPLETE' and len(receipt['sources']) == 45
        and TASK not in {row['task_id'] for row in receipt['sources']}, 'Original45 sources must capture; failed attempt must not')
    u.verify_refs(plan['preserved_references'])
    for tail in [*plan['guarded_predecessor_tails'], plan['guarded_predecessor_cohort_tail']]:
        require(chain(Path(tail['path']).parent.parent)[1][-1] == tail, 'A predecessor advanced during preparation')
    return retain(args.migration_output, {**plan, 'status': 'PREPARED_NOT_LAUNCHED',
        'preparation_intent_reference': ref(intent), 'learning_enrollment_reference': enrollment,
        'source_capture_reference': captures, 'preserved_evidence_rechecked': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'prepare'), nargs='?', default='plan')
    parser.add_argument('--controller', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-controller-v4/trimem_skhynix_architecture_scale_pipeline.py')
    parser.add_argument('--controller-sha256', required=True)
    parser.add_argument('--previous-pipeline', type=Path, default=CFG / 'architecture_002_pipeline_v3.json')
    parser.add_argument('--adoption-output', type=Path, default=ART / 'source-adoption-increment120-004.json')
    parser.add_argument('--replacement-output', type=Path, default=ART / 'infrastructure-replacement-004.json')
    parser.add_argument('--inheritance-output', type=Path, default=ART / 'bank-inheritance24-004.json')
    parser.add_argument('--execution-output', type=Path, default=CFG / 'architecture_002_training_120_v2.json')
    parser.add_argument('--pipeline-output', type=Path, default=CFG / 'architecture_002_pipeline_v4.json')
    parser.add_argument('--authority-output', type=Path, default=BASE / 'training-120-v2/execution-authority.json')
    parser.add_argument('--pipeline-root', type=Path, default=BASE / 'pipeline-v4')
    parser.add_argument('--training-root', type=Path, default=BASE / 'training-120-v2')
    parser.add_argument('--native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-native-v3/training-120')
    parser.add_argument('--reflection-native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-reflection-v3')
    parser.add_argument('--evaluation-native-root', type=Path, default=SYSTEM_TEMP / 'skhynix-architecture-scale-001-evaluation-v3')
    parser.add_argument('--migration-output', type=Path, default=ART / 'source-recovery-004.json')
    args = parser.parse_args()
    old = read(args.previous_pipeline)
    adoption = checked(old['source_adoption_reference'])
    tails = [adoption['original_pipeline_event_tail_reference'], *adoption.get('predecessor_pipeline_event_tail_references', [])]
    roots = [Path(tail['path']).parent.parent for tail in tails] + [Path(old['pipeline_root']), BASE / 'training-120-v1/cohort', BASE / 'training-24-v2/cohort']
    with u.inactive_predecessors(roots):
        plan, outputs, execution, learning, controller = build(args)
        result = {'status': 'PREPARED_NOT_LAUNCHED', 'receipt_reference': prepare(args, plan, outputs, execution, learning, controller)} if args.command == 'prepare' else {
            key: value for key, value in plan.items() if key not in ('preserved_references', 'source_cell_references', 'remaining_task_ids')}
        if args.command == 'plan':
            result.update(status='PLAN_ONLY_NO_FILES_WRITTEN', remaining_count=len(plan['remaining_task_ids']), first_remaining_task=plan['remaining_task_ids'][0])
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
