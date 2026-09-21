"""Freeze the reviewed orchestration only; retain the source-v6 solver."""
from pathlib import Path
import hashlib,json

REPO=Path('C:/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'

def ref(path):
    path=Path(path).resolve()
    name=path.as_posix()
    assert name.lower().startswith('c:/')
    return {'path':'/mnt/c/'+name[3:],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

source=REPO/'scripts/trimem_skhynix_evaluation_continuation.py'
frozen=Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v16')/source.name
frozen.parent.mkdir(parents=True,exist_ok=True)
with frozen.open('xb') as stream:
    stream.write(source.read_bytes())
old_path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v15.json'
old=json.loads(old_path.read_bytes())
value={**old,'schema':'skhynix/evaluation-continuation-pipeline/1.0',
    'pipeline_source_reference':ref(frozen),
    'pipeline_root':'/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v16',
    'progress_root':'/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001/progress',
    'evaluation_native_root':'/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-evaluation-v16',
    'supersedes_configuration_reference':ref(old_path),
    'evaluation_continuation_reference':ref(BASE/'amendment.json'),
    'revision_reason':'Explicit symmetric evaluation accounting: preserve known terminal grading ambiguities as unscored, retain all official results and enrolled tasks, and continue without native or grading retries. Original baseline config/attempts and source-v6 solver/model/high/budget/bank are unchanged.'}
path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'
with path.open('xb') as stream:
    stream.write(canonical(value)+b'\n')
with path.with_suffix('.sha256').open('x',encoding='ascii') as stream:
    stream.write(hashlib.sha256(canonical(value)).hexdigest()+'\n')
print(json.dumps({'configuration_reference':ref(path),'controller_reference':ref(frozen)}))
