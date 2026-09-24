"""Record only an actual fresh launch or the solver's completed attestation."""
from pathlib import Path
import argparse,json,subprocess,sys
p=argparse.ArgumentParser()
p.add_argument('command',choices=['launch','attest'])
for field in ['name','cell','agent']:p.add_argument('--'+field,required=True)
for field in ['sha','tests','limitations']:p.add_argument('--'+field)
a=p.parse_args()
if a.cell not in ['A','B','C']:p.error('Only declared A/B/C cells')
payload=vars(a)
if a.command=='attest' and not all([a.sha,a.tests,a.limitations]):p.error('attest requires sha/tests/limitations')
code='data='+repr(payload)+'\n'+r'''
import time
contract=json.loads((central/'launch-contract.json').read_text())
assert data['name'] in contract['names'] and data['cell'] in contract['launch_order'][data['name']]
assert json.loads((central/'preflight.json').read_text())['status']=='PASS'
out=central/'solver-launches';out.mkdir(exist_ok=True)
key=data['name']+'-'+data['cell'];path=out/(key+'.json')
if data['command']=='launch':
 template=central/'solver_prompt_template.txt'
 assert hashlib.sha256(template.read_bytes()).hexdigest()==contract['evaluation_template_sha256']
 prompt=template.read_text().replace('{{BASE}}',str(central/data['name'])).replace('{{CELL}}',data['cell'])
 row={'schema':'skhynix/native011-solver-launch/1.0','name':data['name'],'cell':data['cell'],'agent':data['agent'],
  'requested_model':'gpt-6-astra','fork_turns':'none','reasoning_effort':'INHERITED_PARENT_UNCHANGED',
  'template_sha256':hashlib.sha256(template.read_bytes()).hexdigest(),'filled_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
  'recorded_at_unix_seconds':time.time(),'root_cross_cell_feedback':False,'separate_model_api_calls':0}
 with path.open('x') as f:json.dump(row,f,indent=2,sort_keys=True);f.write('\n')
 with (out/(key+'-prompt.txt')).open('xb') as f:f.write(prompt.encode())
else:
 launch=json.loads(path.read_text());assert launch['agent']==data['agent']
 root=central/data['name']/'execution/cells'/data['cell']
 submission=json.loads((root/'submission.json').read_text())
 assert submission['patch_sha256']==data['sha'] and submission['agent_completed'] is True
 row={'agent':data['agent'],'run':data['name'],'cell':data['cell'],'patch_sha256':data['sha'],
  'public_test_summary':data['tests'],'limitations':data['limitations'],
  'only_assigned_broker':True,'no_external_access':True,'no_subagents':True}
 records=central/'attestations.json';rows=json.loads(records.read_text())
 assert not any((r['run'],r['cell'])==(data['name'],data['cell']) for r in rows)
 rows.append(row)
 temporary=records.with_suffix('.tmp');temporary.write_text(json.dumps(rows,indent=2,sort_keys=True)+'\n');temporary.replace(records)
print(json.dumps({'status':'RECORDED','operation':data['command'],'cell':key,'agent':data['agent']}))
'''
out=Path(__file__).with_name('skhynix_codex_011_record_payload.py');out.write_text(code,encoding='utf-8')
result=subprocess.run([sys.executable,str(Path(__file__).with_name('skhynix_codex_011_manage.py')),'python','--code-file',str(out)],capture_output=True)
sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr);raise SystemExit(result.returncode)
