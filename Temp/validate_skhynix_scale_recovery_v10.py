"""Validate source-only continuation after Pytest8447's undetermined grade."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v10.json'
OLD_CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v9.json'
ACTIVE_SHA = '50247903d970039ae9cf640305e8306151f5e942bcc7f0d6a8d594b9242c2c43'
AMBIGUOUS = 'swebench--pytest-dev__pytest-8447'
FIRST_NEW = 'swebench--pytest-dev__pytest-8950'
EXPECTED_UNDETERMINED = {AMBIGUOUS, 'swebench--pydata__xarray-7052', 'swebench--mwaskom__seaborn-2766',
                         'swebench--pytest-dev__pytest-5205', 'swebench--sphinx-doc__sphinx-7234'}


def require(value, message):
    if not value:
        raise ValueError(message)


def passed_cases(path):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    require(cases and not any(list(case.iter('failure')) or list(case.iter('error')) or
                             list(case.iter('skipped')) for case in cases),
            'The bound validation tests did not all pass')
    return len(cases)


def validate_native_binary(core, reference):
    binary = core.check(reference)
    require(binary['schema'] == 'skhynix/frozen-native-binary/1.0' and binary['model_calls'] == 0,
            'The native executable has no frozen zero-model-call receipt')
    binary_path = Path(binary['binary_reference']['path'])
    core.check(binary['binary_reference'], decode=False)
    bundle_root = Path(binary['bundle_root']).resolve(strict=True)
    require(binary_path.resolve(strict=True).parent == bundle_root and binary_path.name == 'codex.exe' and
            binary['bundle_sha256'] and set(binary['bundle_sha256']) ==
            {path.relative_to(bundle_root).as_posix() for path in bundle_root.rglob('*') if path.is_file()},
            'The frozen native bundle file inventory changed')
    for relative, sha256 in binary['bundle_sha256'].items():
        bundle_file = (bundle_root / relative).resolve(strict=True)
        require(bundle_root in bundle_file.parents and core.ref(bundle_file)['sha256'] == sha256,
                'A frozen native bundle file changed or escaped its root')
    require(str(binary_path).startswith('/mnt/c/') and
            binary['codex_binary'] == 'C:/' + str(binary_path)[len('/mnt/c/'):],
            'The Windows executable path does not bind the frozen binary')
    result = subprocess.run([str(binary_path), '--version'], capture_output=True, text=True,
                            check=True, timeout=30)
    require(result.stdout.strip() == binary['version'] == 'codex-cli 0.154.0-alpha.6.2' and
            not result.stderr.strip(), 'The frozen native executable version probe failed')
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-xml', type=Path, required=True)
    parser.add_argument('--runtime-tests-xml', type=Path, required=True)
    args = parser.parse_args()
    controller_tests = passed_cases(args.tests_xml)
    runtime_tests = passed_cases(args.runtime_tests_xml)
    config = json.loads(CONFIG.read_bytes())
    training = json.loads(Path(config['training_experiment_reference']['path']).read_bytes())
    source = Path(training['source_root'])
    sys.path[:0] = [str(source / 'scripts'), str(source / 'src')]
    spec = importlib.util.spec_from_file_location('recovery_controller_v10',
                                               config['pipeline_source_reference']['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    core = module.core
    active_reference = core.ref(PUBLIC / 'active-controller-v9.json')
    old_reference = core.ref(OLD_CONFIG)
    old = core.check(old_reference)
    require(active_reference['sha256'] == ACTIVE_SHA and
            core.ref(PUBLIC / 'active-controller.json')['sha256'] == ACTIVE_SHA and
            core.check(active_reference)['configuration_reference'] == old_reference,
            'The active predecessor differs from the reviewed v9 activation')
    pipeline = module.ScalePipeline(CONFIG)
    with pipeline._controller_locks():
        migration_reference = core.ref(PUBLIC / 'source-recovery-010.json')
        migration = core.check(migration_reference)
        require(migration['status'] == 'PREPARED_NOT_LAUNCHED' and
                migration['pipeline_reference'] == pipeline.reference and
                migration['previous_pipeline_reference'] == old_reference and
                migration['source_attempts'] == 85 and migration['official_complete'] == 80 and
                migration['official_undetermined'] == 5 and migration['solver_runs'] == 0 and
                migration['official_grader_runs'] == 0, 'Preparation receipt differs')
        continuation_ref = config['grading_continuation_reference']
        continuation = core.check(continuation_ref)
        require(continuation['schema'] == 'skhynix/architecture-scale-grading-continuation/2.0' and
                migration['grading_continuation_reference'] == continuation_ref and
                continuation['predecessor_pipeline_reference'] == old_reference and
                continuation['historical_grading_continuation_reference'] == old['grading_continuation_reference'],
                'Current and historical continuation references differ')
        module.validate_grading_continuation(config, execution=pipeline.operations.modules['cohort'].execution)
        history = core.check(continuation['historical_grading_continuation_reference'])
        for name in ('runtime_change_reference', 'loader_preflight_reference', 'native_binary_reference'):
            require(continuation[name] == history[name], 'Existing runtime, loader, or native binary changed')
            core.check(continuation[name])
        old_execution = core.check(old['training_stages'][1]['execution_reference'])
        old_cohort_root = Path(old_execution['run_root']) / 'cohort'
        old_pipeline_events = core.read_event_chain(Path(old['pipeline_root']))
        old_cohort_events = core.read_event_chain(old_cohort_root)
        require(len(old_pipeline_events) == 28 and old_pipeline_events[-1]['stage'] == 'PIPELINE_BLOCKED' and
                len(old_cohort_events) == 126 and old_cohort_events[-1]['stage'] == 'INFRA_ERROR' and
                old_cohort_events[-1]['task_id'] == AMBIGUOUS and
                core.ref(sorted((Path(old['pipeline_root']) / 'events').glob('*.json'))[-1]) ==
                continuation['predecessor_pipeline_event_tail_reference'] and
                core.ref(sorted((old_cohort_root / 'events').glob('*.json'))[-1]) ==
                continuation['predecessor_cohort_event_tail_reference'],
                'The blocked v9 journals advanced or their exact tails changed')
        for reference in migration['preserved_references']:
            core.check(reference, decode=False)
        previous_migration = core.check(core.ref(PUBLIC / 'source-recovery-009.json'))
        stages = {stage['size']: stage for stage in config['training_stages']}
        require(stages[24] == old['training_stages'][0] and stages[240] == old['training_stages'][2],
                'The inherited24 or untouched240 stage changed')
        refs24, refs120, refs240 = (pipeline._source_cells(size) for size in (24, 120, 240))
        require((len(refs24), len(refs120), len(refs240)) == (24, 85, 85), 'Retained source counts differ')
        retained = {core.check(ref)['task_public']['task_id']: ref for ref in refs120}
        require(len(retained) == 85 and sorted(refs120, key=lambda ref: ref['path']) ==
                sorted(migration['source_cell_references'], key=lambda ref: ref['path']),
                'Retained identities differ from preparation')
        replacement_ref = previous_migration['infrastructure_replacement_reference']
        replacement = core.check(replacement_ref)
        require(replacement['old_cell_reference']['path'] not in {ref['path'] for ref in refs120} and
                core.check(replacement['audit_reference'])['passed'] is False and
                core.ref(Path(replacement['old_cell_reference']['path']).parent / 'broker/submission.diff') ==
                replacement['submission_patch_reference'], 'Historical failed quota attempt changed or entered memory')
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
        require(outcome_counts == {'official_complete': 80, 'official_undetermined': 5} and
                undetermined == EXPECTED_UNDETERMINED, 'Official outcome accounting changed')
        ambiguous_row = by_id[AMBIGUOUS]
        require(core.check(ambiguous_row['audit_reference'])['passed'] is True and
                ambiguous_row['classification'] == 'AMBIGUOUS_NO_TESTS_COLLECTED',
                'The retained ambiguous source has no passing native audit or changed classification')
        summary = core.check(ambiguous_row['official_summary_reference'])
        require(summary['ambiguous_failure_instances'] == 1 and
                summary['failure_reasons'].get('pytest-dev__pytest-8447') == 'no_tests_collected',
                'The original grading ambiguity changed')
        binary_ref = continuation['native_binary_reference']
        binary = validate_native_binary(core, binary_ref)
        benchmark = importlib.import_module('trimem_benchmark_run')
        require(Path(benchmark.__file__).resolve() == (source / 'scripts/trimem_benchmark_run.py').resolve(),
                'Exact loader validation imported a different runtime snapshot')
        loader_ref = continuation['loader_preflight_reference']
        evidence = benchmark.load_official_harness_loader_preflight(Path(loader_ref['path']))
        loader_checks = []
        for size in (120, 240):
            experiment = core.check(stages[size]['execution_reference'])
            require(experiment['codex_binary'] == binary['codex_binary'] and
                    {'path': experiment['loader_preflight_path'], 'sha256': experiment['loader_preflight_sha256']} == loader_ref,
                    'A future training stage uses a different executable or loader')
            harness_root = Path(experiment['harness_root'])
            benchmark.validate_preflight_harness_root_binding(evidence, {
                'swebench_verified': harness_root / 'swebench_verified',
                'multi_swe_bench_mini': harness_root / 'multi', 'multi_swe_bench_flash': harness_root / 'multi'})
            loader_checks.append({'size': size, 'execution_reference': stages[size]['execution_reference'],
                'loader_preflight_reference': loader_ref,
                'current_exact_loader_environment': 'PASS', 'harness_root_binding': 'PASS'})
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
        print(json.dumps({'status': 'VALIDATING_COMPLETED_SOURCE_IMPORT', 'model_calls': 0,
                          'official_grader_runs': 0}), flush=True)
        import_path = pipeline.learning_root / 'source-recovery010-captures.json'
        require(migration['source_capture_reference']['path'] == str(import_path) and import_path.is_file(),
                'Expected completed source import is absent or outside the new learning root')
        core.check(migration['source_capture_reference'])
        imported = learning.capture_existing_sources(pipeline.learning_root, cell_references=refs120, output_path=import_path)
        require(imported == migration['source_capture_reference'] and len(state['cells']) == 85,
                'Completed85 source import changed')
        captures = [learning._checked_cell_receipt(ref) for ref in state['cells'].values()]
        require({row['task_id'] for row in captures} == set(retained), 'Captured identities differ')
        for row in captures:
            require(row['status'] in {'CAPTURED', 'NO_PUBLIC_ATTEMPTS'} and not row['failures'] and
                    row['source_execution_observed'] is True and
                    row['source_references']['cell.json'] == retained[row['task_id']],
                    'A retained cell receipt failed provenance validation')
        original_state = core.read(Path(old['training_stages'][1]['learning_root']) / 'learning-state.json')
        original_captures = [learning._checked_cell_receipt(ref) for ref in original_state['cells'].values()]
        require(len(original_captures) == 84 and
                {row['task_id'] for row in original_captures} == set(retained) - {AMBIGUOUS},
                'The original84 capture receipts changed or an additional source appeared')
        require(set(learning._available_captures(pipeline.learning_root, state)) == set(catalog['captures']) and
                not state['reflections'] and not state['ingestions'] and not catalog['skills'],
                'Capture catalog or publication state differs')
        require(len(enrollment['training_tasks']) == 120, 'Cumulative enrollment is not120')
        runner = pipeline._runner(stage120)
        authority = pipeline.operations.modules['cohort'].execution.execution_enrollment(experiment)
        schedule = [row['task_id'] for row in runner.schedule]
        require(schedule == authority['task_ids'] == migration['remaining_task_ids'] ==
                previous_migration['remaining_task_ids'][13:] and len(schedule) == 35 and schedule[0] == FIRST_NEW and
                not set(schedule) & set(retained) and len(set(schedule) | set(retained)) == 120,
                'The new cohort is not the exact never-started remaining35 suffix')
        status = runner.status()
        require(status['planned_cells'] == 35 and status['completed_cells'] == 0 and not pipeline.events(),
                'The new controller or a new cohort cell already ran')
        for size in (120, 240):
            run_root = Path(core.check(stages[size]['execution_reference'])['run_root'])
            require(not list(run_root.glob('cells/**/cell.json')), 'A future runtime root already has model cells')
        receipt = {
            'schema': 'skhynix/scale-recovery-startup-validation/1.0',
            'at': datetime.now(timezone.utc).isoformat(), 'status': 'VALIDATED_NOT_LAUNCHED',
            'configuration_reference': pipeline.reference, 'controller_reference': config['pipeline_source_reference'],
            'source_recovery_reference': migration_reference, 'grading_continuation_reference': continuation_ref,
            'historical_grading_continuation_reference': continuation['historical_grading_continuation_reference'],
            'runtime_change_reference': continuation['runtime_change_reference'],
            'historical_replacement_reference': replacement_ref, 'predecessor_activation_reference': active_reference,
            'predecessor_pipeline_reference': old_reference,
            'predecessor_pipeline_event_tail_reference': continuation['predecessor_pipeline_event_tail_reference'],
            'predecessor_cohort_event_tail_reference': continuation['predecessor_cohort_event_tail_reference'],
            'loader_preflight_reference': loader_ref, 'current_exact_loader_environment_validated': True,
            'loader_checks': loader_checks, 'native_binary_reference': binary_ref,
            'native_binary_file_reference': binary['binary_reference'], 'native_binary_version': binary['version'],
            'native_binary_version_probe_passed': True, 'native_binary_bundle_verified': True,
            'controller_test_reference': core.ref(args.tests_xml), 'runtime_test_reference': core.ref(args.runtime_tests_xml),
            'validator_source_reference': core.ref(Path(__file__).resolve()),
            'controller_tests_passed': controller_tests, 'runtime_tests_passed': runtime_tests,
            'captured_cells': 85, 'public_capture_records': len(catalog['captures']),
            'all_capture_receipts_validated': True, 'original_capture_receipts_preserved': 84,
            'learning_enrollment_reference': enrollment_ref, 'official_complete': 80, 'official_undetermined': 5,
            'official_result_references': result_references, 'undetermined_task_ids': sorted(undetermined),
            'remaining_training120_count': 35, 'remaining_training120_task_ids': schedule,
            'native_infrastructure_replacements_authorized': 0,
            'historical_native_infrastructure_replacements_authorized': 1,
            'official_outcome_retries': False, 'native_outcome_retries': False,
            'source_selection_changed': False, 'historical_results_reclassified': False,
            'source_runtime_changed': False, 'grading_semantics_changed': False, 'native_binary_changed': False,
            'model': 'gpt-6-astra', 'reasoning_effort': 'high', 'model_calls': 0, 'official_grader_runs': 0}
        reference = core.retain(PUBLIC / 'startup-validation-v10.json', receipt)
        print(json.dumps({'status': receipt['status'], 'reference': reference,
                          'captured_cells': 85, 'remaining_training120_count': 35}), flush=True)


if __name__ == '__main__':
    main()
