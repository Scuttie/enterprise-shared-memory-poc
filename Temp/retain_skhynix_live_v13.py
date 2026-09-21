"""Retain public metadata only after genuine native actions are observed."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
ART = REPO / 'artifacts/skhynix_v1/architecture_scale_001'

def read(path):
    return json.loads(path.read_bytes())

def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--monitor-sample', type=Path, required=True)
    args = parser.parse_args()
    config_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v13.json'
    config = read(config_path)
    execution = read(Path(config['training_experiment_reference']['path']))
    assert read(ART / 'active-controller.json')['configuration_name'] == config_path.name
    task = 'swebench--pytest-dev__pytest-6116'
    folder = Path(execution['run_root']) / 'cells/TRAINING' / task / 'PDF_MEMORY'
    broker = read(folder / 'broker/state.json')
    assert broker['actions'] > 0
    workers = broker['workers']
    native = Path(execution['native_control_root']) / 'TRAINING/pytest-dev__pytest-6116/PDF_MEMORY'
    launches = sorted(native.glob('worker-*/output/launch.json'))
    assert launches
    for path in launches:
        launch = read(path)
        assert launch['requested_model'] == 'gpt-6-astra' and launch['reasoning_effort'] == 'high'
    learning = Path(config['training_stages'][1]['learning_root'])
    state, catalog = read(learning / 'learning-state.json'), read(learning / 'catalog.json')
    with sqlite3.connect((learning / 'authority.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        counts = dict(db.execute('SELECT kind,COUNT(*) FROM memory_records WHERE revoked=0 GROUP BY kind'))
        relations = db.execute('SELECT COUNT(*) FROM knowledge_relations').fetchone()[0]
    launch_refs = [ref(p) for p in sorted((ART / 'processes').glob('*.launch.json'))
                   if read(p)['configuration_sha256'] == ref(config_path)['sha256']]
    assert len(launch_refs) == 1
    result = {
        'schema': 'skhynix/resume-live-validation/1.0',
        'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'MODEL_WORK_OBSERVED',
        'configuration_reference': ref(config_path),
        'controller_launch_reference': launch_refs[0],
        'startup_validation_reference': ref(ART / 'startup-validation-v13.json'),
        'source_recovery_reference': ref(ART / 'source-recovery-013.json'),
        'monitor_sample_reference': ref(args.monitor_sample),
        'task_id': task, 'model': 'gpt-6-astra', 'reasoning_effort': 'high',
        'broker_snapshot': {'actions': broker['actions'], 'state': broker['status'],
            'workers': len(workers), 'worker_status_counts': dict(Counter(row['status'] for row in workers.values()))},
        'native_launch_references': [ref(p) for p in launches],
        'learning_snapshot': {'cells': len(state['cells']), 'L1_episodes': counts.get('episode', 0),
            'L2_nodes': counts.get('knowledge', 0), 'L2_relations': relations, 'L3_skills': len(catalog['skills'])},
        'retained_official_complete': 80, 'retained_official_undetermined': 6,
        'remaining_source_schedule': 34, 'new_solver_retries': False, 'new_grader_retries': False,
        'official_evaluation_started': False,
    }
    output = ART / 'resume-live-validation-013.json'
    with output.open('xb') as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(',', ':')).encode())
    print(json.dumps({'receipt': ref(output), 'snapshot': result['broker_snapshot'],
                      'learning_snapshot': result['learning_snapshot']}))

if __name__ == '__main__':
    main()
