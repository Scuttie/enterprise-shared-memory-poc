from pathlib import Path
import hashlib,json
ROOT=Path('C:/Users/jewon/esm-r23-d115-writer')
BASE=ROOT/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001'

def ref(path):
    name=path.resolve().as_posix()
    assert name.lower().startswith('c:/')
    return {'path':'/mnt/c/'+name[3:],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

old_path=BASE/'interim-results-20260920T133030Z.json'
value=json.loads(old_path.read_bytes())
sample=ROOT/'artifacts/skhynix_v1/architecture_scale_001/monitor/samples/20260920T132753.8122776Z.json'
assert ref(sample)['sha256']==value['monitor_reference']['sha256']
value['monitor_reference']=ref(sample)
value['supersedes_metadata_reference']=ref(old_path)
value['metadata_correction']='Reference the identical immutable monitor sample rather than the rolling latest.json path. Scores, source references and observation timestamp are unchanged.'
new_path=BASE/'interim-results-20260920T133030Z-v2.json'
with new_path.open('x',encoding='utf-8') as stream:
    json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2)
    stream.write('\n')
target=BASE/'evaluation-continuation-001/evaluation-hold-continuation-tests.xml'
with target.open('xb') as stream:
    stream.write((ROOT/'Temp/evaluation-hold-continuation-tests.xml').read_bytes())
print(json.dumps({'corrected_snapshot':ref(new_path),'tests':ref(target)}))
