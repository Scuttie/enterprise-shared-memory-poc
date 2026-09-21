"""Read public progress metadata for the transition to cumulative240."""
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path('/home/trimem-runner/skhynix-architecture-scale-001')

def read(path):
    return json.loads(path.read_bytes()) if path.is_file() else {}

def main():
    learning = ROOT / 'pipeline-v13/learning-240'
    state, catalog = read(learning / 'learning-state.json'), read(learning / 'catalog.json')
    enrollment = read(learning / 'learning-enrollment.json')
    events = sorted((ROOT / 'training-240-v1/cohort/events').glob('[0-9]*.json'))
    event = read(events[-1]) if events else {}
    print(json.dumps({
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'learning_root_exists': learning.is_dir(),
        'enrollment_exists': bool(enrollment),
        'enrolled_training_tasks': len(enrollment.get('training_tasks', {})),
        'captured_source_cells': len(state.get('cells', {})),
        'episodes': len(catalog.get('captures', {})),
        'skills': len(catalog.get('skills', {})),
        'cohort_event_count': len(events),
        'latest_cohort_event': {key: event.get(key) for key in ('stage', 'task_id', 'at')},
    }, sort_keys=True))

if __name__ == '__main__':
    main()
