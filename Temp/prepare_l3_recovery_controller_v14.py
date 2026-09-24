"""Prepare a fresh evaluation controller only after actual memory publication."""
from pathlib import Path
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


previous_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v13.json'
manifest_path = ARTIFACT / 'publisher/reflection-recovery.json'
manifest = json.loads(manifest_path.read_bytes())
if manifest.get('status') != 'READY' or manifest.get('L3_skills', 0) < 1:
    raise ValueError('Actual unchanged Gate B publication has not completed')
publication_ref = manifest['publication_reference']
if reference(publication_ref['path']) != publication_ref:
    raise ValueError('Actual publication reference changed')
controller = Path('/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v14/trimem_skhynix_architecture_reflection_recovery.py')
if reference(controller)['sha256'] != '0651e1cd9277fd1fba75ab69296177e15dba57965d852710f40c2648fa682782':
    raise ValueError('Reviewed controller source changed')
config = json.loads(previous_path.read_bytes())
config.update(
    schema='skhynix/architecture-reflection-recovery-pipeline/1.0',
    pipeline_root='/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v14',
    progress_root=str(ARTIFACT / 'evaluation-progress'),
    reflection_native_root=str(ARTIFACT / 'publisher'),
    evaluation_native_root='/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-evaluation-v14',
    pipeline_source_reference=reference(controller),
    supersedes_configuration_reference=reference(previous_path),
    predecessor_pipeline_event_tail_reference=reference('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v13/events/00000427.json'),
    reflection_recovery_reference=reference(manifest_path),
    revision_reason='Preserve all 240 original training sources and original NOT_READY decisions; evaluate the separately published semantic reflection recovery with unchanged source-v6 solver, model/high, budgets and official grading. No training solver or grading reruns.')
path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v14.json'
config_ref = retain(path, config)
canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
with path.with_suffix('.sha256').open('x') as stream:
    stream.write(hashlib.sha256(canonical).hexdigest() + '\n')
print(json.dumps(config_ref))
