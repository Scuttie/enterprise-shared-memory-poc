"""Validate the exact no-retry grading continuation before new execution starts."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v5.json'
OLD_CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v4.json'
ACTIVE_SHA = '296bd3f9255049d5e3c049254d0206d03c0e0a874a41fbab51714c8638c126d8'
AMBIGUOUS = 'swebench--mwaskom__seaborn-2766'
FIRST_NEW = 'swebench--mwaskom__seaborn-3190'
EXPECTED_UNDETERMINED = {AMBIGUOUS, 'swebench--pytest-dev__pytest-5205',
                         'swebench--sphinx-doc__sphinx-7234'}


def require(value, message):
    if not value:
        raise ValueError(message)


def passed_cases(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    require(cases and not any(list(case.iter('failure')) or list(case.iter('error')) or
                             list(case.iter('skipped')) for case in cases),
            'The bound validation tests did not all pass')
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-xml', type=Path, required=True)
    parser.add_argument('--runtime-tests-xml', type=Path)
    args = parser.parse_args()
    controller_test_count = passed_cases(args.tests_xml)
    runtime_test_count = passed_cases(args.runtime_tests_xml) if args.runtime_tests_xml else None
    config = json.loads(CONFIG.read_bytes())
    training = json.loads(Path(config['training_experiment_reference']['path']).read_bytes())
    source = Path(training['source_root'])
    sys.path[:0] = [str(source / 'scripts'), str(source / 'src')]
    spec = importlib.util.spec_from_file_location('recovery_controller_v5',
                                               config['pipeline_source_reference']['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    core = module.core
    active_reference = core.ref(PUBLIC / 'active-controller-v4.json')
    require(active_reference['sha256'] == ACTIVE_SHA and
            core.ref(PUBLIC / 'active-controller.json')['sha256'] == ACTIVE_SHA and
            core.check(active_reference)['configuration_reference'] == core.ref(OLD_CONFIG),
            'The active predecessor differs from the reviewed v4 activation')
    pipeline = module.ScalePipeline(CONFIG)
    with pipeline._controller_locks():
        migration_reference = core.ref(PUBLIC / 'source-recovery-005.json')
        migration = core.check(migration_reference)
        require(migration['status'] == 'PREPARED_NOT_LAUNCHED' and
                migration['pipeline_reference'] == pipeline.reference and
                migration['source_attempts'] == 60 and migration['official_complete'] == 57 and
                migration['official_undetermined'] == 3 and migration['solver_runs'] == 0 and
                migration['official_grader_runs'] == 0, 'Preparation receipt differs')
        continuation_ref = config['grading_continuation_reference']
        continuation = core.check(continuation_ref)
        require(migration['grading_continuation_reference'] == continuation_ref,
                'Preparation and controller continuation references differ')
        module.validate_grading_continuation(config,
            execution=pipeline.operations.modules['cohort'].execution)
        runtime_reference = continuation['runtime_change_reference']
        core.check(runtime_reference)
        for reference in migration['preserved_references']:
            core.check(reference, decode=False)
        previous_migration = core.check(core.ref(PUBLIC / 'source-recovery-004.json'))
        stages = {stage['size']: stage for stage in config['training_stages']}
        refs24 = pipeline._source_cells(24)
        refs120 = pipeline._source_cells(120)
        refs240 = pipeline._source_cells(240)
        require((len(refs24), len(refs120), len(refs240)) == (24, 60, 60),
                'Retained source counts differ')
        retained = {core.check(ref)['task_public']['task_id']: ref for ref in refs120}
        require(len(retained) == 60 and sorted(refs120, key=lambda ref: ref['path']) ==
                sorted(migration['source_cell_references'], key=lambda ref: ref['path']),
                'Retained identities differ from preparation')
        replacement_ref = previous_migration['infrastructure_replacement_reference']
        replacement = core.check(replacement_ref)
        require(replacement['old_cell_reference']['path'] not in {ref['path'] for ref in refs120},
                'The historical failed quota attempt entered capture sources')
        require(core.check(replacement['audit_reference'])['passed'] is False and
                core.ref(Path(replacement['old_cell_reference']['path']).parent / 'broker/submission.diff') ==
                replacement['submission_patch_reference'], 'Historical failed quota attempt changed')

        # Verify only public outcomes and aggregate reports; preserve uncertainty.
        outcome_counts, undetermined, result_references = Counter(), set(), []
        adoption_rows = []
        for ref in (migration['source_adoption_reference'], migration['increment_adoption_reference']):
            adoption_rows.extend(core.check(ref)['rows'])
        by_id = {row['task_id']: row for row in adoption_rows}
        for task_id, reference in retained.items():
            result_path = Path(reference['path']).parent / 'public-result.json'
            if result_path.is_file():
                result_ref = core.ref(result_path)
                result = core.check(result_ref)
                require(result['task_id'] == task_id and type(result['resolved']) is bool,
                        'A completed official result is malformed')
                result_references.append(result_ref)
                outcome_counts['official_complete'] += 1
            else:
                row = by_id.get(task_id)
                require(row and row.get('official_result_reference') is None and
                        row.get('official_summary_reference') is not None,
                        'A source without an official outcome has no retained aggregate')
                core.check(row['official_summary_reference'])
                undetermined.add(task_id)
                outcome_counts['official_undetermined'] += 1
        require(outcome_counts == {'official_complete': 57, 'official_undetermined': 3} and
                undetermined == EXPECTED_UNDETERMINED, 'Official outcome accounting changed')
        ambiguous_row = by_id[AMBIGUOUS]
        require(core.check(ambiguous_row['audit_reference'])['passed'] is True,
                'The retained ambiguous attempt has no passing native audit')
        summary = core.check(ambiguous_row['official_summary_reference'])
        require(summary['ambiguous_failure_instances'] == 1 and
                summary['failure_reasons'].get('mwaskom__seaborn-2766') == 'missing_module',
                'The original grading ambiguity changed')

        stage120 = stages[120]
        experiment = core.check(stage120['execution_reference'])
        pipeline.learning_root = Path(stage120.get('learning_root', pipeline.root / 'learning-120'))
        enrollment_ref = core.ref(pipeline.learning_root / 'learning-enrollment.json')
        enrollment = core.check(enrollment_ref)
        expected_order = previous_migration['learning_execution_references'] + [stage120['execution_reference']]
        require(enrollment['execution_references'] == expected_order == migration['learning_execution_references'],
                'Prepared enrollment does not retain chronological execution order')
        state = core.read(pipeline.learning_root / 'learning-state.json')
        catalog = core.read(pipeline.learning_root / 'catalog.json')
        learning = pipeline.operations.modules['learning']
        print(json.dumps({'status': 'VALIDATING_COMPLETED_SOURCE_IMPORT',
                          'model_calls': 0, 'official_grader_runs': 0}), flush=True)
        import_path = pipeline.learning_root / 'source-recovery005-captures.json'
        require(migration['source_capture_reference']['path'] == str(import_path) and import_path.is_file(),
                'Expected completed source import is absent or outside the new learning root')
        core.check(migration['source_capture_reference'])
        # This completed-import branch validates original capture receipts only.
        # It cannot invoke the costly full capture traversal or recapture tasks.
        imported = learning.capture_existing_sources(pipeline.learning_root, cell_references=refs120,
                                                     output_path=import_path)
        require(imported == migration['source_capture_reference'], 'Completed source import changed')
        require(len(state['cells']) == 60, 'Expected 60 retained learning cells')
        captures = [learning._checked_cell_receipt(ref) for ref in state['cells'].values()]
        require({row['task_id'] for row in captures} == set(retained), 'Captured identities differ')
        for row in captures:
            require(row['status'] in {'CAPTURED', 'NO_PUBLIC_ATTEMPTS'} and not row['failures'] and
                    row['source_execution_observed'] is True and
                    row['source_references']['cell.json'] == retained[row['task_id']],
                    'A retained cell receipt failed provenance validation')
        require(set(learning._available_captures(pipeline.learning_root, state)) == set(catalog['captures']),
                'Capture catalog differs from retained evidence')
        require(not state['reflections'] and not state['ingestions'] and not catalog['skills'],
                'Unexpected memory publication before launch')
        require(len(enrollment['training_tasks']) == 120, 'Cumulative enrollment is not 120')
        print(json.dumps({'status': 'VALIDATING_NEW_COHORT', 'captured_cells': 60,
                          'model_calls': 0, 'official_grader_runs': 0}), flush=True)
        runner = pipeline._runner(stage120)
        authority = pipeline.operations.modules['cohort'].execution.execution_enrollment(experiment)
        schedule = [row['task_id'] for row in runner.schedule]
        expected_remaining = previous_migration['remaining_task_ids'][15:]
        require(schedule == authority['task_ids'] == migration['remaining_task_ids'] == expected_remaining and
                len(schedule) == 60 and schedule[0] == FIRST_NEW,
                'The new cohort is not the exact never-started remaining 60-task suffix')
        require(not set(schedule) & set(retained) and len(set(schedule) | set(retained)) == 120,
                'A retained task would repeat or the cumulative enrollment changed')
        status = runner.status()
        require(status['planned_cells'] == 60 and status['completed_cells'] == 0,
                'A new cohort cell already ran')
        for size in (120, 240):
            run_root = Path(core.check(stages[size]['execution_reference'])['run_root'])
            require(not list(run_root.glob('cells/**/cell.json')), 'A new runtime root already has model cells')
        require(not pipeline.events(), 'The new controller already emitted execution events')
        receipt = {
            'schema': 'skhynix/scale-recovery-startup-validation/1.0',
            'at': datetime.now(timezone.utc).isoformat(), 'status': 'VALIDATED_NOT_LAUNCHED',
            'configuration_reference': pipeline.reference, 'controller_reference': config['pipeline_source_reference'],
            'source_recovery_reference': migration_reference, 'grading_continuation_reference': continuation_ref,
            'runtime_change_reference': runtime_reference, 'historical_replacement_reference': replacement_ref,
            'predecessor_activation_reference': active_reference,
            'controller_test_reference': core.ref(args.tests_xml),
            'runtime_test_reference': core.ref(args.runtime_tests_xml) if args.runtime_tests_xml else None,
            'validator_source_reference': core.ref(Path(__file__).resolve()),
            'controller_tests_passed': controller_test_count, 'runtime_tests_passed': runtime_test_count,
            'captured_cells': 60, 'public_capture_records': len(catalog['captures']),
            'all_capture_receipts_validated': True, 'learning_enrollment_reference': enrollment_ref,
            'official_complete': 57, 'official_undetermined': 3,
            'official_result_references': result_references,
            'undetermined_task_ids': sorted(undetermined),
            'remaining_training120_count': 60, 'remaining_training120_task_ids': schedule,
            'native_infrastructure_replacements_authorized': 0,
            'historical_native_infrastructure_replacements_authorized': 1,
            'official_outcome_retries': False, 'native_outcome_retries': False,
            'source_selection_changed': False, 'historical_results_reclassified': False,
            'source_adoption_classifier_changed': True, 'grading_semantics_changed': False,
            'model': 'gpt-6-astra', 'reasoning_effort': 'high', 'model_calls': 0, 'official_grader_runs': 0}
        reference = core.retain(PUBLIC / 'startup-validation-v5.json', receipt)
        print(json.dumps({'status': receipt['status'], 'reference': reference,
                          'captured_cells': 60, 'remaining_training120_count': 60}), flush=True)


if __name__ == '__main__':
    main()
