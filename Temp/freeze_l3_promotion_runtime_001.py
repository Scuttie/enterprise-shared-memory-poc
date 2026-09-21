"""Freeze a one-file offline scanner correction; leave solver source-v6 intact."""
from pathlib import Path
import hashlib
import json
import shutil

REPO = Path('C:/Users/jewon/esm-r23-d115-writer')
ARTIFACT = REPO / 'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001'
OLD = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v6')
NEW = Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-promotion-v1')
CHANGED = 'src/enterprise_memory/trimem/skill_memory.py'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linux(path):
    value = Path(path).resolve().as_posix()
    if not value.lower().startswith('c:/'):
        raise ValueError('Expected explicit C-drive artifact')
    return '/mnt/c/' + value[3:]


def ref(path):
    return {'path': linux(path), 'sha256': digest(path)}


previous = json.loads((REPO / 'configs/skhynix_v1/architecture_002_pipeline_v13.json').read_bytes())
execution_ref = previous['training_experiment_reference']
execution_path = Path('C:/' + execution_ref['path'][7:])
if digest(execution_path) != execution_ref['sha256']:
    raise ValueError('Original execution configuration changed')
execution = json.loads(execution_path.read_bytes())
old_map = execution['source_sha256']
if execution['source_root'] != linux(OLD) or len(old_map) != 391 or CHANGED not in old_map:
    raise ValueError('Unexpected frozen source authority')
test_path = ARTIFACT / 'typed-template-security-tests-001.xml'
test_ref = ref(test_path)
# The XML is retained as evidence, and all test suites must have completed cleanly.
import xml.etree.ElementTree as ET
tree = ET.parse(test_path)
if any(int(s.get('failures', 0)) or int(s.get('errors', 0)) or int(s.get('skipped', 0))
       for s in tree.iter('testsuite')):
    raise ValueError('Typed-template regression checks did not all pass')
NEW.mkdir(parents=True, exist_ok=False)
for name, expected in old_map.items():
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or digest(OLD / relative) != expected:
        raise ValueError('Original frozen source reference changed')
    target = NEW / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OLD / relative, target)
shutil.copyfile(REPO / CHANGED, NEW / CHANGED)
new_map = {name: digest(NEW / name) for name in old_map}
if [name for name in old_map if old_map[name] != new_map[name]] != [CHANGED]:
    raise ValueError('Offline promotion snapshot must change only the reviewed scanner caller')
value = {
    'schema': 'skhynix/offline-promotion-runtime/1.0',
    'previous_execution_reference': execution_ref,
    'old_source_root': linux(OLD), 'source_root': linux(NEW),
    'old_source_sha256': old_map, 'source_sha256': new_map,
    'changed_paths': [CHANGED], 'test_references': [test_ref],
    'model_calls': 0, 'solver_runs': 0, 'official_grader_runs': 0,
    'solver_source_unchanged': True,
    'source_excerpt_threshold_unchanged': True,
    'raw_secret_pii_entropy_scan_unchanged': True,
    'red_edit_green_evidence_rules_unchanged': True,
    'correction': 'For an already validated typed template, classify declared parameter syntax separately from literal source. Scan the entire original text for sensitive data first. No REVIEW waiver or threshold change.',
    'freeze_helper_reference': ref(Path(__file__)),
}
path = ARTIFACT / 'offline-promotion-runtime-001.json'
with path.open('xb') as stream:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n')
print(json.dumps(ref(path)))
