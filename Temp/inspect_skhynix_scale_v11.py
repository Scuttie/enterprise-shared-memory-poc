"""Read only public progress metadata for recovery v11; never read task logs."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
BASE = Path('/home/trimem-runner/skhynix-architecture-scale-001')


def read(path):
    return json.loads(path.read_bytes()) if path.is_file() else {}


def event(root):
    files = sorted((root / 'events').glob('[0-9]*.json'))
    row = read(files[-1]) if files else {}
    return {key: row.get(key) for key in ('stage', 'at', 'task_id', 'ordinal')}


def main():
    result = {'at': datetime.now(timezone.utc).isoformat()}
    driver = read(PUBLIC / 'recovery-v11-driver/state.json')
    result['driver'] = {key: driver.get(key) for key in ('phase', 'at', 'error')}
    config = read(REPO / 'configs/skhynix_v1/architecture_002_pipeline_v11.json')
    result['pipeline'] = event(BASE / 'pipeline-v11')
    result['cohort'] = event(BASE / 'training-120-v9/cohort')
    learn = BASE / 'pipeline-v11/learning-120'
    state, catalog = read(learn / 'learning-state.json'), read(learn / 'catalog.json')
    result['learning'] = {'cells': len(state.get('cells', {})),
                          'captures': len(catalog.get('captures', {})),
                          'skills': len(catalog.get('skills', {}))}
    if (learn / 'authority.sqlite3').is_file():
        with sqlite3.connect((learn / 'authority.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
            result['learning']['memory_records'] = dict(db.execute(
                'SELECT kind,COUNT(*) FROM memory_records WHERE revoked=0 GROUP BY kind'))
            result['learning']['relations'] = db.execute('SELECT COUNT(*) FROM knowledge_relations').fetchone()[0]
    task = result['cohort'].get('task_id')
    if task:
        folder = BASE / 'training-120-v9/cells/TRAINING' / task / 'PDF_MEMORY'
        broker = read(folder / 'broker/state.json')
        workers = broker.get('workers', {})
        result['broker'] = {'status': broker.get('status'), 'actions': broker.get('actions'),
                            'unfinished_actions': broker.get('unfinished_actions'), 'workers': len(workers),
                            'worker_status_counts': dict(Counter(row.get('status') for row in workers.values()))}
        result['result_present'] = (folder / 'public-result.json').is_file()
        result['undetermined_present'] = (folder / 'training-grade-undetermined.json').is_file()
        if config:
            execution = read(Path(config['training_experiment_reference']['path']))
            native = Path(execution['native_control_root']) / 'TRAINING' / task.split('--', 1)[1] / 'PDF_MEMORY'
            result['native'] = []
            for output in sorted(native.glob('worker-*/output')):
                launch, completion = read(output / 'launch.json'), read(output / 'completion.json')
                result['native'].append({'worker': output.parent.name,
                    'launch': {key: launch.get(key) for key in ('requested_model', 'reasoning_effort', 'fresh_session')},
                    'completion': {key: completion.get(key) for key in ('exit_code', 'timed_out', 'admitted')}})
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
