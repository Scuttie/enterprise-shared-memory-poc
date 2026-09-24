"""Preflight the immutable recovery without invoking workers or grading."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
CONFIG = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v3.json'
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'


def main():
    configuration = json.loads(CONFIG.read_bytes())
    training = json.loads(Path(configuration['training_experiment_reference']['path']).read_bytes())
    root = Path(training['source_root'])
    sys.path[:0] = [str(root / 'scripts'), str(root / 'src')]
    source = configuration['pipeline_source_reference']['path']
    spec = importlib.util.spec_from_file_location('recovery_controller_v3', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    pipeline = module.ScalePipeline(CONFIG)
    with pipeline._controller_locks():
        for stage in configuration['training_stages']:
            config = module.core.check(stage['execution_reference'])
            authority = pipeline.operations.modules['cohort'].execution.execution_enrollment(config)
            assert len(authority['task_ids']) == {24: 3, 120: 96, 240: 120}[stage['size']]
        stage = configuration['training_stages'][0]
        print(json.dumps({'status': 'VALIDATING_RETAINED_PUBLIC_SOURCES', 'source_attempts': 21,
                          'model_calls': 0, 'official_grader_runs': 0}), flush=True)
        migration_reference = module.core.ref(PUBLIC / 'source-recovery-003.json')
        migration = module.core.check(migration_reference)
        assert migration['status'] == 'PREPARED_NOT_LAUNCHED'
        assert migration['pipeline_reference'] == pipeline.reference
        assert migration['source_adoption_reference'] == configuration['source_adoption_reference']
        pipeline.learning_root = Path(stage['learning_root'])
        assert migration['learning_root'] == str(pipeline.learning_root)
        assert module.core.ref(pipeline.learning_root / 'learning-enrollment.json') == migration['learning_enrollment_reference']
        runner = pipeline._runner(stage)
        expected = {'swebench--sphinx-doc__sphinx-7268',
                    'swebench--sympy__sympy-11232', 'swebench--sympy__sympy-11384'}
        assert {row['task_id'] for row in runner.schedule} == expected
        assert all(row['arm'] == 'PDF_MEMORY' for row in runner.schedule)
        assert len(pipeline._source_cells(24)) == 21
        state = module.core.read(pipeline.learning_root / 'learning-state.json')
        catalog = module.core.read(pipeline.learning_root / 'catalog.json')
        assert len(state['cells']) == 21
        learning = pipeline.operations.modules['learning']
        captures = [learning._checked_cell_receipt(ref) for ref in state['cells'].values()]
        adopted = {row['task_id']: row['cell_reference'] for row in pipeline.adoption['rows']}
        assert {row.get('task_id') for row in captures} == set(adopted)
        for row in captures:
            assert row['status'] in {'CAPTURED', 'NO_PUBLIC_ATTEMPTS'} and not row['failures']
            assert row['source_execution_observed'] is True
            assert row['cell_path'] == adopted[row['task_id']]['path']
            assert row['source_references']['cell.json'] == adopted[row['task_id']]
        available = learning._available_captures(pipeline.learning_root, state)
        assert set(available) == set(catalog['captures'])
        assert not state['reflections'] and not state['ingestions'] and not catalog['skills']
        status = runner.status()
        assert status['planned_cells'] == 3 and status['completed_cells'] == 0
        event_count = len(pipeline.events())
        assert event_count == 0
        for size in (24, 120, 240):
            config = module.core.check(next(s['execution_reference'] for s in configuration['training_stages'] if s['size'] == size))
            assert not list((Path(config['run_root']) / 'cells').glob('**/cell.json'))
        # A progress write reflects prepared source import, never claims model activity.
        progress = pipeline.progress()
        receipt = {
            'schema': 'skhynix/scale-recovery-startup-validation/1.0',
            'at': datetime.now(timezone.utc).isoformat(), 'status': 'VALIDATED_NOT_LAUNCHED',
            'configuration_reference': module.core.ref(CONFIG),
            'controller_reference': configuration['pipeline_source_reference'],
            'source_adoption_reference': configuration['source_adoption_reference'],
            'source_recovery_reference': migration_reference,
            'retained_grader_diagnostic_reference': module.core.ref(PUBLIC / 'retained-grader-diagnostic-001.json'),
            'validator_source_reference': module.core.ref(Path(__file__).resolve()),
            'controller_test_reference': module.core.ref(Path('/mnt/c/Users/jewon/AppData/Local/Temp/native_architecture_scale_pipeline_recovery_v3.xml')),
            'controller_tests_passed': 22, 'adopted_source_attempts': 21,
            'official_complete': 19, 'official_undetermined': 2,
            'captured_cells': len(state['cells']), 'public_capture_records': len(catalog['captures']),
            'all_capture_receipts_validated': True, 'all_checkpoint_prefixes_revalidated': True,
            'learning_root': str(pipeline.learning_root),
            'remaining_training24_task_ids': sorted(expected),
            'scheduled_increments': {'24': 3, '120': 96, '240': 120},
            'model': 'gpt-6-astra', 'reasoning_effort': 'high',
            'model_calls': 0, 'official_grader_runs': 0, 'outcome_retries': False,
            'learning_enrollment_reference': module.core.ref(pipeline.learning_root / 'learning-enrollment.json'),
            'progress_reference': progress,
        }
        reference = module.core.retain(PUBLIC / 'startup-validation-v3.json', receipt)
        print(json.dumps({'status': receipt['status'], 'reference': reference,
                          'captured_cells': receipt['captured_cells'],
                          'public_capture_records': receipt['public_capture_records']}), flush=True)


if __name__ == '__main__':
    main()
