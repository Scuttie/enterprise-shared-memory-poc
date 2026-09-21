"""Activate only the validated unchanged-runtime evaluation continuation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
REPO=Path('C:/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001'
ROOT=BASE/'l3-recovery-001/evaluation-continuation-001'

def ref(path):
    path=Path(path).resolve()
    name=path.as_posix()
    assert name.lower().startswith('c:/')
    return {'path':'/mnt/c/'+name[3:],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

config_path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'
config=json.loads(config_path.read_bytes())
validation_path=ROOT/'startup-validation-v16.json'
validation=json.loads(validation_path.read_bytes())
assert validation['status']=='READY_FOR_RUN'
assert validation['configuration_reference']==ref(config_path)
assert validation['controller_reference']==config['pipeline_source_reference']
assert validation['amendment_reference']==config['evaluation_continuation_reference']
source_path=Path('C:/'+config['pipeline_source_reference']['path'][7:])
assert ref(source_path)==config['pipeline_source_reference']
active=BASE/'active-controller.json'
prior=json.loads(active.read_bytes())
assert prior['configuration_name']=='architecture_002_pipeline_v15.json'
assert prior['configuration_reference']==config['supersedes_configuration_reference']
archive=BASE/'active-controller-v15.json'
assert archive.read_bytes()==active.read_bytes()
value={**prior,'configuration_name':config_path.name,'configuration_reference':ref(config_path),
    'superseded_scale_configuration_reference':prior['configuration_reference'],
    'superseded_activation_reference':ref(archive),'startup_validation_reference':ref(validation_path),
    'evaluation_continuation_reference':config['evaluation_continuation_reference'],
    'launcher_reference':ref(REPO/'scripts/Start-SkhynixScalePipeline.ps1'),
    'monitor_reference':ref(REPO/'scripts/Watch-SkhynixScalePipeline.ps1'),
    'health_helper_reference':ref(REPO/'scripts/trimem_skhynix_scale_health.py'),
    'activated_at':datetime.now(timezone.utc).isoformat(),
    'reason':config['revision_reason']}
raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+b'\n'
path=BASE/'active-controller-v16.json'
with path.open('xb') as stream:
    stream.write(raw)
pending=BASE/'active-controller-v16.next.json'
with pending.open('xb') as stream:
    stream.write(raw)
pending.replace(active)
print(json.dumps(ref(path)))
