"""Freeze an additive, reviewed TRAINING-only hold-continuation runtime.

No solver, grader, image, or repository task commands are invoked.
Existing snapshots and attempts are never changed.
"""
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

REPO = Path('C:/Users/jewon/esm-r23-d115-writer')
PUBLIC = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
SOURCE = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v5')
CONTROLLER = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v12')
CHANGED = sorted('scripts/trimem_skhynix_architecture_' + name + '.py'
                 for name in ('run', 'cohort', 'cleanup'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux(path):
    value = str(path).replace('\\', '/')
    assert value.startswith('C:/')
    return '/mnt/c/' + value[3:]


def windows(path):
    assert path.startswith('/mnt/c/')
    return Path('C:/' + path[7:])


def reference(path):
    return {'path': linux(path), 'sha256': sha(path)}


def require_pass(path):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    assert cases and not any(list(row.iter(tag)) for row in cases
                             for tag in ('failure', 'error', 'skipped')), str(path)
    return len(cases)


def main():
    old_path = REPO / 'configs/skhynix_v1/architecture_002_training_120_v8.json'
    old = json.loads(old_path.read_bytes())
    prior_root = windows(old['source_root'])
    before = old['source_sha256']
    assert not SOURCE.exists() and not CONTROLLER.exists(), 'New frozen roots already exist'
    assert not (PUBLIC / 'runtime-freeze-012.json').exists(), 'Runtime receipt already exists'
    counts = {name: require_pass(PUBLIC / ('continuation-' + name + '-tests-012.xml'))
              for name in ('controller', 'runtime')}
    assert all(sha(prior_root / name) == digest for name, digest in before.items()), 'Old frozen bytes changed'
    assert set(CHANGED) <= set(before)
    assert all(sha(REPO / name) != before[name] for name in CHANGED), 'An expected reviewed change is absent'
    SOURCE.mkdir()
    for name in before:
        target = SOURCE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile((REPO if name in CHANGED else prior_root) / name, target)
    after = {name: sha(SOURCE / name) for name in before}
    assert sorted(name for name in before if before[name] != after[name]) == CHANGED
    assert all(sha(prior_root / name) == digest for name, digest in before.items())
    receipt = {'schema': 'skhynix/grading-continuation-runtime-freeze/1.0',
               'previous_execution_reference': reference(old_path),
               'old_source_root': old['source_root'], 'source_root': linux(SOURCE),
               'old_source_sha256': before, 'source_sha256': after, 'changed_paths': CHANGED,
               'model_calls': 0, 'official_grader_runs': 0}
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    output = PUBLIC / 'runtime-freeze-012.json'
    with output.open('xb') as stream:
        stream.write(payload)
    CONTROLLER.mkdir()
    controller = CONTROLLER / 'trimem_skhynix_architecture_scale_pipeline.py'
    shutil.copyfile(REPO / 'scripts' / controller.name, controller)
    shutil.copyfile(PUBLIC / 'continuation-controller-tests-012.xml', CONTROLLER / 'validation.xml')
    print(json.dumps({'runtime': reference(output), 'controller': reference(controller),
                      'source_files': len(after), 'changed_paths': CHANGED, 'tests': counts}))


if __name__ == '__main__':
    main()
