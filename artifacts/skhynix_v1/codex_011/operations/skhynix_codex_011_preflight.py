"""Synthetic receipt checks; no solver, issue probe, test or grade is run."""
import importlib
import time

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_text())
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n')

contract=read(central/'launch-contract.json')
assert not (central/'preflight.json').exists()
assert not (central/'batch-plan.json').exists()
first=central/contract['names'][0]/'source'
sys.path[:0]=[str(first/'scripts'),str(first/'src')]
import trimem_skhynix_codex as broker
import trimem_skhynix_codex_controlled_lessons as controlled
freeze=read(central/'source-freeze.json')
before={};after={};synthetic=[];batch=[]
for name in contract['names']:
 run=central/name/'execution'
 plan=read(run/'plan.json')
 plan_sha=sha(broker.canonical(plan))
 assert (run/'plan.sha256').read_text().strip()==plan_sha
 assert plan['limits']==broker.LIMITS and plan['controlled_lesson_manifest']['sha256']==contract['controlled_lessons_sha256']
 assert plan['source_hashes']==broker.source_hashes()
 assert plan['public_task']['task_id'] in contract['evaluation_instances']
 assert plan['base_git_head']==HEAD
 for relative,digest in freeze['sha256'].items():
  assert sha((central/name/'source'/relative).read_bytes())==digest
 bank=controlled.load_controlled_manifest(Path(plan['controlled_lesson_manifest']['path']),
    plan['controlled_lesson_manifest']['sha256'],broker.task_from_plan(plan))
 batch.append({'name':name,'target_id':plan['public_task']['task_id'],'run_root':str(run),
               'plan_sha256':plan_sha,'cells':['A','B','C']})
 for cell in ('A','B','C'):
  original=run/'cells'/cell
  state=read(original/'state.json')
  assert state['actions']==0 and state['status']=='OPEN' and state['started_at'] is None
  assert not (original/'submission.json').exists() and not (original/'public-result.json').exists()
  assert not list((original/'journal').glob('*'))
  before[name+'-'+cell]=state
  test_run=central/'preflight-control'/name
  root=test_run/'cells'/cell
  save(root/'state.json',state)
  save(root/'public-task.json',read(original/'public-task.json'))
  save(root/'bank-projection.json',controlled.projection(plan,test_run,cell,bank))
  # A diff would access the checkout if the initial-recall guard were absent.
  guard=broker.perform_action(plan,test_run,cell,{'op':'diff'})
  assert guard['ok'] is False and 'recall' in guard['error'].lower()
  info=broker.perform_action(plan,test_run,cell,{'op':'info'})
  assert info['ok'] is True
  query={'node_id':'investigate','objective':'Investigate the public issue and representation invariants.',
         'operation':'reproduce bug and verify Python regression tests','symbols':[],'apis':[],'errors':[]}
  first_recall=broker.perform_action(plan,test_run,cell,{'op':'recall','query':query})
  assert first_recall['ok'] is True,first_recall
  injections=first_recall['result']['injections']
  assert len(injections)==int(cell!='A')
  if injections:
   lesson=bank.lesson_for(cell)
   assert injections[0]['exact_text']==lesson['lesson_text']
   assert injections[0]['sha256']==lesson['lesson_sha256']
   assert injections[0]['byte_count']==1670
  repeat=broker.perform_action(plan,test_run,cell,{'op':'recall','query':query})
  assert repeat['ok'] and repeat['result']['injections']==[]
  events,_=broker.audit_events(root)
  restored=controlled.restore_delivery(plan,test_run,cell,events,bank)
  assert restored['successful_recalls']==2
  after[name+'-'+cell]=read(original/'state.json')
  assert after[name+'-'+cell]==before[name+'-'+cell]
  synthetic.append({'name':name,'cell':cell,'initial_injections':len(injections),
       'initial_bytes':sum(i['byte_count'] for i in injections),'repeat_delivery':0,
       'enforced_initial_recall':True,'event_derived_restore':'PASS'})
assert len(synthetic)==12 and before==after
save(central/'batch-plan.json',{'schema':'skhynix/native011-batch-plan/1.0',
 'contract_sha256':sha((central/'launch-contract.json').read_bytes()),'entries':batch,
 'planned_cells':12,'actual_solver_actions_at_freeze':0,'official_grades_at_freeze':0})
result={'schema':'skhynix/native011-preflight/1.0','status':'PASS',
 'contract_sha256':sha((central/'launch-contract.json').read_bytes()),
 'batch_plan_sha256':sha((central/'batch-plan.json').read_bytes()),
 'actual_states_before':before,'actual_states_after':after,'actual_solver_actions':0,
 'official_grades':0,'synthetic_results':synthetic,'batch':batch,'completed_at_unix_seconds':time.time()}
save(central/'preflight.json',result)
print(json.dumps({'status':'PASS','synthetic_cells':len(synthetic),'actual_solver_actions':0,
 'official_grades':0,'preflight_sha256':sha((central/'preflight.json').read_bytes())}))
