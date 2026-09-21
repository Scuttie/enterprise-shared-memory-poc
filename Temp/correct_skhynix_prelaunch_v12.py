"""Correct retained-source capture count without replacing the original receipt."""
import datetime
import hashlib
import json
from pathlib import Path

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
ART = REPO / 'artifacts/skhynix_v1/architecture_scale_001'

def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    old_path = ART / 'prelaunch-abort-012.json'
    value = json.loads(old_path.read_bytes())
    root = Path(value['pipeline_root'])
    learning = root / 'learning-120'
    state = json.loads((learning / 'learning-state.json').read_bytes())
    catalog = json.loads((learning / 'catalog.json').read_bytes())
    assert len(state['cells']) == 18 and len(catalog['captures']) == 82
    assert not list((root / 'events').glob('*.json'))
    assert not list((Path(value['training_root']) / 'cells').glob('**/cell.json'))
    assert not Path(value['native_root']).exists()
    for item in value['preserved_references']:
        assert ref(Path(item['path'])) == item
    value.update(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 supersedes_reference=ref(old_path),
                 correction='The earlier receipt checked a nonmatching capture filename. Preparation reconstructed18 historical source cells and82 episodes before stopping; these are retained partial outputs, not new solver attempts, and are not consumed by the successor.',
                 captured_source_cells=18, captured_public_episodes=82,
                 partial_learning_outputs_consumed=False)
    value['preserved_references'].append(ref(old_path))
    value['preserved_references'].sort(key=lambda row: row['path'])
    output = ART / 'prelaunch-abort-012-corrected.json'
    with output.open('xb') as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
    print(json.dumps({'receipt': ref(output), 'captured_source_cells': 18,
                      'captured_public_episodes': 82, 'model_calls': 0}))

if __name__ == '__main__':
    main()
