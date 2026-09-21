"""Bind evaluation to the actual published bank and reviewed recovery controller."""
from pathlib import Path
import argparse
import hashlib
import json

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
ARTIFACT = REPO / 'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001'


def reference(path):
    path = Path(path)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def retain(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
    return reference(path)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--controller-sha256', required=True)
args = parser.parse_args()
previous_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v13.json'
manifest_path = ARTIFACT / 'promotion-revalidation/reflection-recovery.json'
manifest = json.loads(manifest_path.read_bytes())
if (manifest.get('status') != 'READY' or manifest.get('L3_skills', 0) < 1
        or not manifest.get('promotion_revision_reference')):
    raise ValueError('Actual amended offline publication has not completed')
for key in ('publication_reference', 'promotion_revision_reference'):
    if reference(manifest[key]['path']) != manifest[key]:
        raise ValueError('Actual publication or offline revision changed')
controller = Path('/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v15/trimem_skhynix_architecture_reflection_recovery.py')
if reference(controller)['sha256'] != args.controller_sha256:
    raise ValueError('Reviewed controller source changed')
config = json.loads(previous_path.read_bytes())
config.update(
    schema='skhynix/architecture-reflection-recovery-pipeline/1.0',
    pipeline_root='/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v15',
    progress_root=str(ARTIFACT / 'evaluation-progress-v15'),
    reflection_native_root=str(ARTIFACT / 'promotion-revalidation'),
    evaluation_native_root='/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-evaluation-v15',
    pipeline_source_reference=reference(controller),
    supersedes_configuration_reference=reference(previous_path),
    predecessor_pipeline_event_tail_reference=reference('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v13/events/00000427.json'),
    reflection_recovery_reference=reference(manifest_path),
    revision_reason='Retain all 240 training sources, all four native proposals and original rejections. Correct only offline typed-template source-excerpt classification, retain explicit verifier revision and revalidate all four proposals. Evaluate the published bank using unchanged source-v6 solver/model/high/budgets/official grading; no training solver, grader or proposal reruns.')
path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v15.json'
config_ref = retain(path, config)
canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
with path.with_suffix('.sha256').open('x') as stream:
    stream.write(hashlib.sha256(canonical).hexdigest() + '\n')
print(json.dumps(config_ref))
