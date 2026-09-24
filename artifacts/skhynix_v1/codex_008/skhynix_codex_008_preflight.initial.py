central=Path('/home/trimem-runner/skhynix-codex-008')
source=central/'recovery-20428-r1/source'
sys.path[:0]=[str(source/'scripts'),str(source/'src')]
import trimem_skhynix_codex as broker
import trimem_skhynix_codex_memory as bridge
from trimem_skhynix_codex_learning import load_frozen_bank, LearnedGraphStore
broker.block_model_client()
contract=broker.read(central/'launch-contract.json')
bank_path=central/'diagnostic-bank.json';bank_sha=broker.sha(bank_path.read_bytes())
assert bank_sha==contract['diagnostic_bank_sha256']
assert broker.sha((central/'source-freeze.json').read_bytes())==contract['source_freeze_sha256']
assert not (central/'preflight.json').exists()
assert not (central/'batch-plan.json').exists()
def protected():
 rows={}
 for name in contract['names']:
  run=central/name/'execution'
  for cell in ['A','B','C']:
   root=run/'cells'/cell;state=broker.read(root/'state.json')
   assert state['actions']==0 and state['started_at'] is None and state['status']=='OPEN'
   for filename in ['state.json','tool-events.jsonl','memory-private/checkpoint.json']:
    p=root/filename;rows[str(p)]=broker.sha(p.read_bytes()) if p.exists() else None
  rows[str(run/'plan.json')]=broker.sha((run/'plan.json').read_bytes())
 return rows
before=protected();entries=[];synthetic=[]
for name in contract['names']:
 run=central/name/'execution';plan=broker.load_plan(run);task=broker.task_from_plan(plan)
 bank=load_frozen_bank(bank_path,bank_sha,task)
 assert bank.manifest['scenario']=='KNOWN_FAILURE_RECOVERY' and bank.promoted_skill is None
 assert len(bank.records)==1 and bank.records[0]['source']['task_id']==task.task_id
 assert bank.records[0]['source']['resolved'] is False
 assert plan['frozen_memory_bank']['sha256']==bank_sha
 entries.append({'name':name,'target_id':task.task_id,'replicate':int(name[-1]),'plan_sha256':broker.sha((run/'plan.json').read_bytes()),'run_root':str(run),'cells':contract['launch_order'][name]})
 query={'node_id':'investigate','objective':bank.records[0]['title'][:180],
  'operation':'reproduce bug and verify Python regression tests','symbols':[],'apis':[],'errors':[]}
 for arm in ['NO_MEMORY','SKHYNIX']:
  cell=central/'synthetic-delivery'/name/arm
  kwargs={'frozen_bank_path':bank_path,'frozen_bank_sha256':bank_sha}
  initial=bridge.initialize_memory(cell,task,arm,source,**kwargs)
  response=bridge.recall_memory(cell,task,arm,query,source,**kwargs)
  injections=response['injections']
  assert initial.get('verified_skill_payload_count',0)==0
  if arm=='NO_MEMORY':assert not injections
  else:
   assert len(injections)==1
   assert injections[0]['exact_text']==bank.records[0]['content']
   assert injections[0]['sha256']==bank.records[0]['content_sha256']
  synthetic.append({'name':name,'arm':arm,'query':query,'injections':injections,'budget':response['budget']})
after=protected();assert before==after
broker.write(central/'preflight.json',{'schema':'skhynix/native008-preflight/1.0','status':'PASS',
 'bank_sha256':bank_sha,'source_freeze_sha256':contract['source_freeze_sha256'],'synthetic':synthetic,
 'actual_states_before':before,'actual_states_after':after,'actual_solver_actions':0,
 'synthetic_results_not_actual_solver_injections':True,'official_grades':0})
broker.write(central/'batch-plan.json',{'schema':'skhynix/native008-recovery-batch/1.0','scenario':'KNOWN_FAILURE_RECOVERY',
 'launch_contract_sha256':broker.sha((central/'launch-contract.json').read_bytes()),
 'preflight_sha256':broker.sha((central/'preflight.json').read_bytes()),'planned_cells':8,'entries':entries})
print(json.dumps({'status':'PASS_PRE_EVALUATION','planned_cells':8,'synthetic_checks':len(synthetic),'actual_actions':0,
 'batch_sha256':broker.sha((central/'batch-plan.json').read_bytes())}))
