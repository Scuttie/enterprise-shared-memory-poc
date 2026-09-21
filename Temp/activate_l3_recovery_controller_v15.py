"""Activate only a source-v6-validated published recovery bank."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

REPO = Path('C:/Users/jewon/esm-r23-d115-writer')
BASE = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
ROOT = BASE / 'l3-recovery-001'


def ref(path):
    path = Path(path).resolve()
    name = path.as_posix()
    if not name.lower().startswith('c:/'):
        raise ValueError('Expected a C-drive activation artifact')
    return {'path': '/mnt/c/' + name[3:], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'


config_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v15.json'
config_ref = ref(config_path)
config = json.loads(config_path.read_bytes())
validation_path = ROOT / 'startup-validation-v15.json'
validation = json.loads(validation_path.read_bytes())
if (validation.get('status') != 'READY' or validation.get('size') != 240
        or validation.get('reflection_recovery_reference') != config['reflection_recovery_reference']
        or not validation.get('layer_counts', {}).get('L3_skills')):
    raise ValueError('Actual original-runtime validation has not confirmed a ready recovered bank')
manifest = json.loads((ROOT / 'promotion-revalidation/reflection-recovery.json').read_bytes())
if (validation.get('publication_reference') != manifest['publication_reference']
        or manifest.get('status') != 'READY'):
    raise ValueError('Startup validation and actual publication differ')
active_path = BASE / 'active-controller.json'
old_bytes = active_path.read_bytes()
old = json.loads(old_bytes)
if (old['configuration_name'] != 'architecture_002_pipeline_v13.json'
        or old['configuration_reference'] != config['supersedes_configuration_reference']):
    raise ValueError('Another controller was activated during recovery')
archive = BASE / 'active-controller-v13.json'
if archive.exists():
    if archive.read_bytes() != old_bytes:
        raise ValueError('Existing predecessor activation archive differs')
else:
    with archive.open('xb') as stream:
        stream.write(old_bytes)
value = {**old,
    'configuration_name': config_path.name,
    'configuration_reference': config_ref,
    'startup_validation_reference': ref(validation_path),
    'superseded_scale_configuration_reference': old['configuration_reference'],
    'superseded_activation_reference': ref(archive),
    'reflection_recovery_reference': config['reflection_recovery_reference'],
    'offline_promotion_revision_reference': manifest['promotion_revision_reference'],
    'launcher_reference': ref(REPO / 'scripts/Start-SkhynixScalePipeline.ps1'),
    'monitor_reference': ref(REPO / 'scripts/Watch-SkhynixScalePipeline.ps1'),
    'activated_at': datetime.now(timezone.utc).isoformat(),
    'reason': 'Evaluate the actual published bank after an explicit offline typed-template scanner correction. Preserve all 240 training sources, all original rejections and all four native proposals. Source-v6 solver/model/high/budgets/grading are unchanged; no training or native-proposal reruns.',
}
frozen = BASE / 'active-controller-v15.json'
with frozen.open('xb') as stream:
    stream.write(canonical(value))
pending = BASE / 'active-controller-v15.next.json'
with pending.open('xb') as stream:
    stream.write(canonical(value))
pending.replace(active_path)
print(json.dumps(ref(frozen)))
