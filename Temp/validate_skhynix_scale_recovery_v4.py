"""Validate the prepared quota recovery before any new solver or grader starts."""
import argparse
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import json
import xml.etree.ElementTree as ET

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v4.json'
QUOTA = Path('/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-codex-quota-health-20260915T070932Z-e4cd0f6a/receipt.json')
FAILED = 'swebench--django__django-16686'


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-xml', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(CONFIG.read_bytes())
    training = json.loads(Path(config['training_experiment_reference']['path']).read_bytes())
    source = Path(training['source_root'])
    sys.path[:0] = [str(source / 'scripts'), str(source / 'src')]
    spec = importlib.util.spec_from_file_location('recovery_controller_v4', config['pipeline_source_reference']['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    core = module.core
    pipeline = module.ScalePipeline(CONFIG)
    test_xml = ET.parse(args.tests_xml)
    cases = list(test_xml.getroot().iter('testcase'))
    require(cases and not any(list(case.iter('failure')) or list(case.iter('error')) or
                             list(case.iter('skipped')) for case in cases), 'Controller tests did not all pass')
    quota = core.read(QUOTA)
    require(quota['classification'] == 'SUCCESS' and quota['exit_code'] == 0 and
            quota['response_is_exact_OK'] and quota['requested_model'] == 'gpt-6-astra' and
            quota['reasoning_effort'] == 'high' and quota['native_session_attempts'] == 1,
            'The matching native quota probe did not pass')
    with pipeline._controller_locks():
        migration_reference = core.ref(PUBLIC / 'source-recovery-004.json')
        migration = core.check(migration_reference)
        require(migration['status'] == 'PREPARED_NOT_LAUNCHED' and
                migration['pipeline_reference'] == pipeline.reference, 'Preparation receipt differs')
        replacement_ref = config['infrastructure_replacement_reference']
        replacement = core.check(replacement_ref)
        require(replacement['task_id'] == FAILED and replacement['replacement_limit'] == 1 and
                replacement['historical_actions'] == 21, 'Replacement scope differs')
        stages = {stage['size']: stage for stage in config['training_stages']}
        refs24 = pipeline._source_cells(24)
        refs120 = pipeline._source_cells(120)
        refs240 = pipeline._source_cells(240)
        require(len(refs24) == 24 and len(refs120) == 45 and len(refs240) == 45,
                'Retained valid source counts differ')
        retained = {core.check(ref)['task_public']['task_id']: ref for ref in refs120}
        require(len(retained) == 45 and FAILED not in retained, 'Failed attempt entered capture sources')
        stage120 = stages[120]
        experiment = core.check(stage120['execution_reference'])
        print(json.dumps({'status': 'VALIDATING_COMPLETED_SOURCE_IMPORT',
                          'model_calls': 0, 'official_grader_runs': 0}), flush=True)
        pipeline.learning_root = Path(stage120.get('learning_root', pipeline.root / 'learning-120'))
        enrollment_ref = core.ref(pipeline.learning_root / 'learning-enrollment.json')
        enrollment = core.check(enrollment_ref)
        expected_order = core.check(config['source_adoption_reference'])['predecessor_configrefs'] + [
            stages[24]['execution_reference'], replacement['old_execution_reference'], stage120['execution_reference']]
        require(enrollment['execution_references'] == expected_order == migration['learning_execution_references'],
                'Prepared enrollment does not retain the reviewed chronological execution order')
        state = core.read(pipeline.learning_root / 'learning-state.json')
        catalog = core.read(pipeline.learning_root / 'catalog.json')
        learning = pipeline.operations.modules['learning']
        # The completed-import branch revalidates every original capture receipt
        # without repeating45 full frozen-source/configuration traversals.
        import_path = pipeline.learning_root / 'source-recovery004-captures.json'
        require(migration['source_capture_reference']['path'] == str(import_path) and import_path.is_file(),
                'Expected completed source import is absent or outside the new learning root')
        core.check(migration['source_capture_reference'])
        imported = learning.capture_existing_sources(pipeline.learning_root, cell_references=refs120,
            output_path=import_path)
        require(imported == migration['source_capture_reference'], 'Completed source import changed')
        require(len(state['cells']) == 45, 'Expected45 retained learning cells')
        captures = [learning._checked_cell_receipt(ref) for ref in state['cells'].values()]
        require({row['task_id'] for row in captures} == set(retained), 'Captured identities differ')
        for row in captures:
            require(row['status'] in {'CAPTURED', 'NO_PUBLIC_ATTEMPTS'} and not row['failures'] and
                    row['source_execution_observed'] is True and
                    row['source_references']['cell.json'] == retained[row['task_id']],
                    'A retained cell receipt failed its provenance check')
        require(set(learning._available_captures(pipeline.learning_root, state)) == set(catalog['captures']),
                'Capture catalog differs from retained evidence')
        require(not state['reflections'] and not state['ingestions'] and not catalog['skills'],
                'Unexpected new memory publication before launch')
        require(len(enrollment['training_tasks']) == 120, 'Cumulative enrollment is not120')
        print(json.dumps({'status': 'VALIDATING_NEW_COHORT', 'captured_cells': 45,
                          'model_calls': 0, 'official_grader_runs': 0}), flush=True)
        runner = pipeline._runner(stage120)
        authority = pipeline.operations.modules['cohort'].execution.execution_enrollment(experiment)
        schedule = [row['task_id'] for row in runner.schedule]
        require(schedule == authority['task_ids'] and len(schedule) == 75 and schedule[0] == FAILED,
                'New cohort is not the exact remaining75 with the named replacement first')
        require(not set(schedule) & set(retained), 'A valid completed task would be repeated')
        status = runner.status()
        require(status['planned_cells'] == 75 and status['completed_cells'] == 0,
                'A new cohort cell already ran')
        for size in (120, 240):
            run_root = Path(core.check(stages[size]['execution_reference'])['run_root'])
            require(not list(run_root.glob('cells/**/cell.json')), 'New runtime root already has model cells')
        require(not pipeline.events(), 'New controller already emitted execution events')
        require(core.check(replacement['audit_reference'])['passed'] is False,
                'Original failed audit was changed')
        require(core.ref(Path(replacement['old_cell_reference']['path']).parent / 'broker/submission.diff') ==
                replacement['submission_patch_reference'], 'Original partial patch changed')
        receipt = {'schema': 'skhynix/scale-recovery-startup-validation/1.0',
            'at': datetime.now(timezone.utc).isoformat(), 'status': 'VALIDATED_NOT_LAUNCHED',
            'configuration_reference': pipeline.reference, 'controller_reference': config['pipeline_source_reference'],
            'source_recovery_reference': migration_reference, 'replacement_reference': replacement_ref,
            'quota_probe_reference': core.ref(QUOTA), 'controller_test_reference': core.ref(args.tests_xml),
            'validator_source_reference': core.ref(Path(__file__).resolve()), 'controller_tests_passed': len(cases),
            'captured_cells': 45, 'public_capture_records': len(catalog['captures']),
            'all_capture_receipts_validated': True, 'learning_enrollment_reference': enrollment_ref,
            'remaining_training120_count': 75, 'remaining_training120_task_ids': schedule,
            'replacement_task_id': FAILED, 'native_infrastructure_replacements_authorized': 1,
            'historical_extra_task_actions': 21, 'official_outcome_retries': False,
            'source_selection_changed': False, 'grading_semantics_changed': False,
            'model': 'gpt-6-astra', 'reasoning_effort': 'high', 'model_calls': 0, 'official_grader_runs': 0}
        reference = core.retain(PUBLIC / 'startup-validation-v4.json', receipt)
        print(json.dumps({'status': receipt['status'], 'reference': reference,
                          'captured_cells': 45, 'remaining_training120_count': 75}), flush=True)


if __name__ == '__main__':
    main()
