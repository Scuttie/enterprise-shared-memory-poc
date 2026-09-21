"""Collect finite public preparation evidence only; never start evaluation."""
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

repo = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
temp = Path('/mnt/c/Users/jewon/AppData/Local/Temp')
data = Path('/home/trimem-runner/skhynix-architecture-preparation/datasets')
destination = repo / 'artifacts/skhynix_v1/architecture_preparation_001'
assert not destination.exists()
sys.path.insert(0, str(repo / 'scripts'))
import trimem_skhynix_architecture_plan as architecture

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

inputs = {}
def include(label, path, expected=None):
    assert label not in inputs and '..' not in Path(label).parts and not Path(label).is_absolute()
    path = Path(path)
    assert path.is_absolute() and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) < 32_000_000
    if expected:
        assert sha(raw) == expected, str(path)
    inputs[label] = {'source': str(path), 'sha256': sha(raw), 'bytes': len(raw), 'raw': raw}

design_ref = {'path': str(repo / 'configs/skhynix_v1/architecture_001_preparation.json'),
              'sha256': '6454391df77910daf5102be056a420207b0b154eb10a465422f1f719e54224f5'}
design = architecture.load_architecture_design(design_ref['path'], design_ref['sha256'])
context_receipt = temp / 'native_architecture_context_validation.json'
readiness = architecture.inspect_readiness(design_ref,
    {'native_context_handoff': {'path': str(context_receipt), 'sha256': sha(context_receipt.read_bytes())}})
assert readiness['status'] == 'NOT_EVALUATION_READY' and not readiness['live_integration_verified']
assert len(readiness['pending_reasons']) == 7
assert design['evaluation']['task_count'] == 500 and design['evaluation']['paired_cells'] == 1000
assert design['training']['candidate_task_count'] == 1786

validation = {}
for name in ('context', 'plan'):
    receipt_path = temp / ('native_architecture_' + name + '_validation.json')
    xml_path = temp / ('native_architecture_' + name + '_validation.xml')
    receipt = read(receipt_path)
    assert receipt['status'] == 'PASS' and receipt['failures'] == receipt['errors'] == receipt['skipped'] == 0
    assert sha(xml_path.read_bytes()) == receipt['xml_sha256']
    cases = ET.fromstring(xml_path.read_bytes()).findall('.//testcase')
    assert len(cases) == receipt['tests'] and all(not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')) for case in cases)
    for relative, digest in receipt['source_sha256'].items():
        assert sha((repo / relative).read_bytes()) == digest, relative
        label = 'source/' + relative
        if label not in inputs:
            include(label, repo / relative, digest)
    include('validation/' + name + '.json', receipt_path)
    include('validation/' + name + '.xml', xml_path, receipt['xml_sha256'])
    validation[name] = {'tests': len(cases), 'status': 'PASS', 'failures': 0,
                        'receipt_sha256': sha(receipt_path.read_bytes()), 'xml_sha256': receipt['xml_sha256']}
for row in read(context_receipt)['preserved_preliminary_artifacts']:
    # The receipt was produced on Windows; resolve only the basename in the
    # same explicitly selected Temp directory when collecting from WSL.
    name = row['path'].replace('\\', '/').rsplit('/', 1)[-1]
    assert name.startswith('native_architecture_context_') and '/' not in name
    include('validation/initial/' + name, temp / name, row['sha256'])
initial_plan = temp / 'native_architecture_plan_validation.initial.xml'
if initial_plan.exists():
    include('validation/initial/' + initial_plan.name, initial_plan)

for name in ('architecture_verified500_inventory.json', 'architecture_training_candidates_inventory.json', 'architecture_001_preparation.json'):
    include('configuration/' + name, repo / 'configs/skhynix_v1' / name)
for name, digest in {
    'public-source-inventory.json': '05686f535e20b369af3ea28062cda0a123c528ad84eb5cac3fe7bfed24272b7c',
    'public-source-overlap-audit.json': '0d111e3caa2b5f8172f34a8803850fc94e1be7cd5d6fe92be3cfb3647dd14ffc',
    'provenance.json': '23e1fbb88c8111eb6b69bc4ea1dec3507226482d7b0c4eb141335737f573396a',
}.items():
    include('dataset-preparation/' + name, data / name, digest)
for name in ('file-manifest.json', 'public-analysis-files.json'):
    include('dataset-preparation/' + name, data / name)
for name in ('skhynix_architecture_verified_inventory.py', 'skhynix_architecture_filter_candidates.py', 'skhynix_architecture_collect_preparation.py'):
    include('operations/' + name, temp / name)

previous_root = repo / 'artifacts/skhynix_v1/codex_011'
previous_manifest = previous_root / 'public-artifact-manifest.json'
assert sha(previous_manifest.read_bytes()) == '728c4a1c24cd1229eb70ffa2864822e85c98666af272158b1d35c2343dccc815'
previous = read(previous_manifest)
assert len(previous['files']) == previous['file_count'] == 251
for row in previous['files']:
    assert sha((previous_root / row['path']).read_bytes()) == row['sha256']
    assert (previous_root / row['path']).stat().st_size == row['bytes']

summary = {'schema': 'skhynix/pdf-architecture-preparation-summary/1.0',
    'status': 'NOT_EVALUATION_READY', 'comparison': {'A': 'BASELINE', 'C': 'PDF_MEMORY'},
    'evaluation_tasks': 500, 'planned_task_attempts': 1000, 'actual_worker_count': 0,
    'training_eligible_candidates': 1786, 'training_enrolled': 0, 'training_runs': 0,
    'model_calls': 0, 'official_grades': 0, 'evaluation_results': None, 'trained_bank': None,
    'validation': validation, 'pending_requirements': readiness['pending_reasons'],
    'prior_native011_public_files_unchanged': 251,
    'scope': 'PREPARATION_CONTRACT_AND_CONTEXT_PACKET_FOUNDATION_ONLY',
    'manual_lessons_used': False, 'live_runtime_wired': False, 'separate_model_api_calls': 0,
    'evaluation_inventory_sha256': '437d84f2e76eaa8a2293788b7bebb0f86dbf27cd6e4acb9a6b855d4e19ac7f77',
    'training_candidate_inventory_sha256': 'b92a1399cc5c51882e48449f508a6609ae82df4c7e0816f4f198cc135d83a8a5',
    'preparation_design_sha256': design_ref['sha256']}

for label, item in inputs.items():
    assert sha(Path(item['source']).read_bytes()) == item['sha256'], label
destination.mkdir(parents=True, exist_ok=False)
files = []
for label, item in sorted(inputs.items()):
    path = destination / label
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(item['raw'])
    files.append({'path': label, **{k: v for k, v in item.items() if k != 'raw'}})
for label, value in (('readiness.json', readiness), ('summary.json', summary)):
    raw = architecture.canonical(value) + b'\n'
    with (destination / label).open('xb') as stream:
        stream.write(raw)
    files.append({'path': label, 'sha256': sha(raw), 'bytes': len(raw), 'source': 'GENERATED_PREPARATION_REPORT'})
manifest = {'schema': 'skhynix/public-preparation-artifact-manifest/1.0', 'status': 'PREPARATION_ONLY',
    'files': sorted(files, key=lambda item: item['path']), 'file_count': len(files),
    'manifest_excludes_itself': True, 'raw_datasets_or_grader_payloads_exported': False}
raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
with (destination / 'public-artifact-manifest.json').open('xb') as stream:
    stream.write(raw)
for row in files:
    copied = destination / row['path']
    assert copied.stat().st_size == row['bytes'] and sha(copied.read_bytes()) == row['sha256']
assert {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} == {r['path'] for r in files} | {'public-artifact-manifest.json'}
print(json.dumps({'status': 'PREPARATION_EVIDENCE_COLLECTED', 'evaluation_ready': False,
    'evaluation_tasks': 500, 'planned_task_attempts': 1000, 'training_candidates': 1786,
    'tests_passed': sum(item['tests'] for item in validation.values()), 'model_calls': 0, 'official_grades': 0,
    'public_files': len(files), 'manifest_sha256': sha(raw), 'path': str(destination)}))
