"""Read only metadata from a running LCB pilot; never print task/code/test data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def status(output):
    output = Path(output)
    cells = []
    for path in sorted((output / 'cells').glob('*/state.json')):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            cell = {'task_id': state['task']['task_id'], 'arm': state['arm'],
                'session': state['session'], 'tool_actions': state['step'],
                'public_test_runs': state['public_test_runs'], 'submitted': state['finished'],
                'age_seconds': max(0, time.time() - state['started_epoch']),
                'seconds_since_state_update': max(0, time.time() - path.stat().st_mtime),
                'solve_receipt_exists': (path.parent / 'solve-receipt.json').is_file()}
            cells.append(cell)
        except (ValueError, OSError, KeyError):
            cells.append({'cell': path.parent.name, 'metadata_status': 'READ_UNAVAILABLE'})
    summary = None
    path = output / 'summary.json'
    if path.is_file():
        value = json.loads(path.read_text(encoding='utf-8'))
        summary = {key: value.get(key) for key in ('status', 'private_grading_ready', 'arms', 'paired', 'effective_paired')}
        if value.get('bank'):
            summary['bank'] = {key: value['bank'].get(key) for key in ('sha256', 'layer_counts')}
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'summary': summary,
            'cells_started': len(cells), 'cells': cells,
            'liveness_note': 'File activity is evidence of progress; process liveness must be checked separately.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(status(args.output), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
