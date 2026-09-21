"""Freeze reviewed quota accounting only; retain the existing native runtime."""
from pathlib import Path
import hashlib,json

REPO=Path('C:/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-002'
def ref(p):
    p=Path(p).resolve(); name=p.as_posix(); assert name.startswith('C:/')
    return {'path':'/mnt/c/'+name[3:],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

source=REPO/'scripts/trimem_skhynix_evaluation_quota_continuation.py'
frozen=Path('C:/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v17')/source.name
frozen.parent.mkdir(parents=True,exist_ok=True)
with frozen.open('xb') as stream:stream.write(source.read_bytes())
old_path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'
old=json.loads(old_path.read_bytes())
value={**old,'schema':'skhynix/evaluation-quota-continuation-pipeline/1.0',
 'pipeline_source_reference':ref(frozen),
 'pipeline_root':'/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v17',
 'progress_root':'/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-002/progress',
 'evaluation_native_root':'/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-evaluation-v17',
 'supersedes_configuration_reference':ref(old_path),
 'native_quota_continuation_reference':ref(BASE/'amendment.json'),
 'revision_reason':'Preserve the explicitly retained native usage-limit interruption as separately unscored, preserve original enrollment and all prior results, and continue the next untouched task without native/grading retries. Apply the same accounting to both arms, retain paired resources, and pause on newly observed quota errors. Solver, model/high, budget and frozen memory remain unchanged.'}
path=REPO/'configs/skhynix_v1/architecture_002_pipeline_v17.json'
with path.open('xb') as stream:stream.write(canonical(value)+b'\n')
with path.with_suffix('.sha256').open('x',encoding='ascii') as stream:
    stream.write(hashlib.sha256(canonical(value)).hexdigest()+'\n')
print(json.dumps({'configuration_reference':ref(path),'controller_reference':ref(frozen)}))
