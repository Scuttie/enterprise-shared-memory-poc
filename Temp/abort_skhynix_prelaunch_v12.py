"""Stop only the identified preparation process; retain its zero-work evidence."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import time

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
ART = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
PID = 711

def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def read(path):
    return json.loads(path.read_bytes())

def main():
    proc = Path('/proc') / str(PID)
    argv = (proc / 'cmdline').read_bytes().split(b'\x00')
    assert str(REPO / 'Temp/prepare_skhynix_scale_recovery_v12.py').encode() in argv
    assert b'prepare' in argv
    config_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v12.json'
    config = read(config_path)
    execution_ref = config['training_stages'][1]['execution_reference']
    execution = read(Path(execution_ref['path']))
    pipeline_root = Path(config['pipeline_root'])
    training_root = Path(execution['run_root'])
    native_root = Path(execution['native_control_root'])
    learning_root = Path(config['training_stages'][1]['learning_root'])
    assert not list((pipeline_root / 'events').glob('*.json'))
    assert not list((training_root / 'cells').glob('**/cell.json'))
    assert not native_root.exists()
    assert not list(learning_root.glob('**/capture.json'))
    os.kill(PID, signal.SIGTERM)
    for _ in range(100):
        if not proc.exists():
            break
        time.sleep(.05)
    assert not proc.exists(), 'Preparation remains alive'
    paths = [REPO / 'Temp' / name for name in (
        'prepare_skhynix_scale_recovery_v12.py', 'validate_skhynix_scale_recovery_v12.py',
        'Activate-SkhynixScaleRecoveryV12.ps1', 'Continue-SkhynixScaleRecoveryV12.ps1')]
    paths += [ART / name for name in ('prelaunch-abort-011.json',
        'source-recovery-011.json.intent.json', 'source-recovery-012.json.intent.json',
        'runtime-freeze-012.json', 'official-harness-loader-v5.json',
        'source-adoption-increment120-012.json', 'grading-continuation-012.json')]
    paths += [config_path, Path(execution_ref['path']),
        Path(config['training_stages'][2]['execution_reference']['path'])]
    paths += [p.with_suffix('.sha256') for p in paths[-3:]]
    paths += [p for root in (pipeline_root, training_root, ART / 'recovery-v12-driver')
              for p in root.rglob('*') if p.is_file()]
    old_abort = read(ART / 'prelaunch-abort-011.json')
    paths += [Path(row['path']) for row in old_abort['preserved_references']]
    references = sorted({str(p): ref(p) for p in paths}.values(), key=lambda row: row['path'])
    result = {
        'schema': 'skhynix/aborted-prelaunch-preparation/1.0',
        'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'ABORTED_BEFORE_NATIVE_WORK',
        'reason': 'Read-only audit found recursive validation amplifies each action to 122 experiment loads and roughly 1GB of source hashing, risking admission timeout and consuming solve budget. Stop before model work; retain all artifacts; deduplicate validation only inside each request.',
        'pipeline_reference': ref(config_path), 'execution_reference': execution_ref,
        'pipeline_root': str(pipeline_root), 'training_root': str(training_root),
        'native_root': str(native_root), 'source_runtime_root': execution['source_root'],
        'controller_driver_process_id': 42540, 'controller_driver_stopped': True,
        'preparation_process_id': PID, 'preparation_process_stopped': True,
        'pipeline_events': 0, 'training_cells': 0, 'native_workers': 0,
        'captured_source_cells': 0, 'model_calls': 0, 'official_grader_runs': 0,
        'solver_retries': False, 'official_grader_retries': False,
        'original_attempts_changed': False,
        'active_predecessor_reference': ref(ART / 'active-controller.json'),
        'preserved_references': references,
    }
    output = ART / 'prelaunch-abort-012.json'
    with output.open('xb') as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(',', ':')).encode())
    print(json.dumps({'receipt': ref(output), 'preserved_files': len(references),
                      'intent': ref(ART / 'source-recovery-012.json.intent.json')}))

if __name__ == '__main__':
    main()
