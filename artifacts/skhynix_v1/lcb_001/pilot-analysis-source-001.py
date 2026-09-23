import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT=next(path for path in Path(__file__).resolve().parents
          if (path/'configs/skhynix_v1/lcb_001_public_split.json').is_file())
source=ROOT/'data/skhynix_lcb_001/pilot-001/summary.json'
raw=source.read_bytes()
summary=json.loads(raw)
if summary['status']!='COMPLETE':
    raise SystemExit('Pilot is not complete; no final score published')
split=json.loads((ROOT/'configs/skhynix_v1/lcb_001_public_split.json').read_text(encoding='utf-8'))
descriptors={row['task_id']:row for row in split['task_descriptors']}
lookup={(row['task_id'],row['arm']):row for row in summary['cells']}
rows=[]
for identity in split['pilot_ids']:
    off,on=lookup[identity,'OFF'],lookup[identity,'ON']
    rows.append({'task_id':identity,'difficulty':descriptors[identity]['difficulty'],
        'off_resolved':off['resolved'],'on_resolved':on['resolved'],
        'off_grade_status':off['grade_status'],'on_grade_status':on['grade_status'],
        'off_seconds':off['wall_seconds'],'on_seconds':on['wall_seconds'],
        'on_memory_injections':on['memory_injection_count'],
        'delta':int(on['resolved'])-int(off['resolved'])})
gains=sum(row['delta']==1 for row in rows)
losses=sum(row['delta']==-1 for row in rows)
discordant=gains+losses
p=min(1.0,2*sum(math.comb(discordant,k) for k in range(min(gains,losses)+1))/(2**discordant))
by_arm={}
for arm in ('TRAIN','OFF','ON'):
    cells=[row for row in summary['cells'] if row['arm']==arm]
    by_arm[arm]={**summary['arms'][arm],
        'mean_solve_seconds':statistics.mean(row['wall_seconds'] for row in cells),
        'median_solve_seconds':statistics.median(row['wall_seconds'] for row in cells),
        'max_solve_seconds':max(row['wall_seconds'] for row in cells)}
metrics={'schema':'trimem/lcb-pilot-analysis/1.0','status':'COMPLETE','scope':'VALIDATION_PILOT_NOT_FINAL_TEST',
    'summary_sha256':hashlib.sha256(raw).hexdigest(),'arms':by_arm,
    'paired':summary['paired'],'effective_paired':summary['effective_paired'],
    'exact_mcnemar_two_sided_p':p,'off_fail_on_pass_ids':[row['task_id'] for row in rows if row['delta']==1],
    'off_pass_on_fail_ids':[row['task_id'] for row in rows if row['delta']==-1],
    'exposed_target_count':sum(row['on_memory_injections']>0 for row in rows),
    'no_exposure_target_count':sum(row['on_memory_injections']==0 for row in rows),
    'gain_with_exposure':sum(row['delta']==1 and row['on_memory_injections']>0 for row in rows),
    'loss_with_exposure':sum(row['delta']==-1 and row['on_memory_injections']>0 for row in rows),
    'test_model_calls':summary['test_partition_model_calls'],
    'manager_seconds':summary['manager_seconds_this_invocation'],
    'bank':{key:summary['bank'][key] for key in ('sha256','layer_counts')}}
folder=ROOT/'artifacts/skhynix_v1/lcb_001'
(folder/'pilot-results-001.json').write_text(json.dumps(metrics,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
with (folder/'pilot-paired-results-001.csv').open('w',encoding='utf-8',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps(metrics,sort_keys=True))
