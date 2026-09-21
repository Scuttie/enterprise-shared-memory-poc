"""Manager code-file draft: test frozen skill delivery in separate synthetic cells."""
central=Path('/home/trimem-runner/skhynix-codex-007')
source=central/'eval-19954/source'
sys.path[:0]=[str(source/'scripts'),str(source/'src')]
import trimem_skhynix_codex as broker
import trimem_skhynix_codex_memory as bridge
from trimem_skhynix_codex_learning import load_frozen_bank,LearnedGraphStore
from trimem_skhynix_codex_procedures import MULTI_SOURCE_PROCEDURE_ID,MULTI_SOURCE_TEMPLATE,load_declaration
broker.block_model_client()
synthetic=central/'synthetic-delivery-cells'
if synthetic.exists() or (central/'skill-delivery-preflight.json').exists():
 raise ValueError('REFUSE_EXISTING_SYNTHETIC_DELIVERY')
contract=broker.read(central/'synthetic-query-contract.json');query=contract['query']
if (contract.get('schema')!='skhynix/native007-synthetic-delivery-contract/1.0'
  or query.get('objective')!=MULTI_SOURCE_TEMPLATE.subgoal_signature
  or contract.get('procedure_id')!=MULTI_SOURCE_PROCEDURE_ID
  or contract.get('procedure_template_hash')!=MULTI_SOURCE_TEMPLATE.content_hash
  or contract.get('synthetic_results_not_counted_as_actual_solver_injections') is not True
  or contract.get('live_solver_query_unchanged') is not True):
 raise ValueError('SYNTHETIC_QUERY_CONTRACT_DIFFERS')
launch=broker.read(central/'launch-contract.json')
declaration_path=central/'procedure-declaration.json'
declaration_sha=broker.sha(declaration_path.read_bytes())
declaration=load_declaration(declaration_path,declaration_sha)
if (declaration['procedure_id']!=MULTI_SOURCE_PROCEDURE_ID
  or declaration['template_hash']!=MULTI_SOURCE_TEMPLATE.content_hash
  or contract.get('procedure_declaration_sha256')!=declaration_sha
  or launch['procedure_declaration']['sha256']!=declaration_sha):
 raise ValueError('SYNTHETIC_DELIVERY_REQUIRES_FROZEN_V3_DECLARATION')
bank_path=central/'learned-bank.json';bank_hash=broker.sha(bank_path.read_bytes())
if broker.read(bank_path)['schema']!='skhynix/native-learned-bank/2.0':
 raise ValueError('ACTUALLY_PROMOTED_SCHEMA2_SKILL_BANK_REQUIRED')
runs=[central/('eval-'+number)/'execution' for number in ['19954','20154','20428','20438','20801','21379']]

def real_state_hashes():
 hashes={}
 for run in runs:
  hashes[str(run/'plan.json')]=broker.sha((run/'plan.json').read_bytes())
  for cell in ['A','B','C']:
   root=run/'cells'/cell;state=broker.read(root/'state.json')
   if state['actions']!=0 or state['started_at'] is not None or state['status']!='OPEN':
    raise ValueError('ACTUAL_EVALUATION_ALREADY_STARTED')
   for name in ['state.json','tool-events.jsonl','memory-private/checkpoint.json']:
    path=root/name
    hashes[str(path)]=broker.sha(path.read_bytes()) if path.exists() else None
 return hashes

before=real_state_hashes();rows=[]
for run in runs:
 plan=broker.load_plan(run);task=broker.task_from_plan(plan)
 bank=load_frozen_bank(bank_path,bank_hash,task);skill=bank.promoted_skill
 if skill is None or skill.template!=MULTI_SOURCE_TEMPLATE:
  raise ValueError('FROZEN_V3_SKILL_REQUIRED')
 view=skill.execution_view();viewsha=broker.sha(view.encode())
 graph=LearnedGraphStore(task,bank)
 if graph.execution_views[skill.skill_id]!=view.encode():raise ValueError('GRAPH_VIEW_DIFFERS')
 semantic=graph.snapshot('ORG_SEMANTIC',org_id=task.org_id,user_id=task.user_id,repository=task.repository)
 if semantic.records[skill.skill_id].execution_view!=view:raise ValueError('SEMANTIC_CANDIDATE_VIEW_DIFFERS')
 for arm in bridge.ARMS:
  cell=synthetic/task.task_id/arm
  kwargs={'frozen_bank_path':bank_path,'frozen_bank_sha256':bank_hash}
  initialized=bridge.initialize_memory(cell,task,arm,source,**kwargs)
  response=bridge.recall_memory(cell,task,arm,query,source,**kwargs)
  matches=[row for row in response['injections'] if row['memory_id']==skill.skill_id]
  if arm=='NO_MEMORY' and response['injections']:raise ValueError('NO_MEMORY_INJECTED_CONTENT')
  if arm=='SKHYNIX' and (len(matches)!=1 or matches[0]['kind']!='SKILL'):
   raise ValueError('PDF_SYNTHETIC_QUERY_DID_NOT_SELECT_THE_DECLARED_SKILL')
  for item in matches:
   if item['exact_text']!=view or item['sha256']!=viewsha:raise ValueError('INJECTED_SKILL_VIEW_DIFFERS')
  if arm!='NO_MEMORY' and initialized['verified_skill_payload_count']!=1:
   raise ValueError('MEMORY_ARM_SKILL_CANDIDATE_COUNT_DIFFERS')
  row={'target_id':task.task_id,'arm':arm,'eligible_skill_id':skill.skill_id,
   'eligible_public_view_sha256':viewsha,'eligible_public_view_bytes':len(view.encode()),
   'candidate_view_equal':True,'selected_skill':bool(matches),'synthetic_injections':response['injections'],
   'initialization':initialized,'response_budget':response['budget']}
  rows.append(row)
  print(json.dumps({'target_id':task.task_id,'arm':arm,'synthetic_selected_skill':bool(matches),
   'injections':len(response['injections'])}),flush=True)
after=real_state_hashes()
if before!=after:raise ValueError('SYNTHETIC_PREFLIGHT_CHANGED_ACTUAL_EVALUATION_STATE')
broker.write(central/'skill-delivery-preflight.json',{'schema':'skhynix/native007-synthetic-delivery/1.0',
 'status':'PASS','procedure_id':MULTI_SOURCE_PROCEDURE_ID,
 'synthetic_query_contract_sha256':broker.sha((central/'synthetic-query-contract.json').read_bytes()),
 'bank_sha256':bank_hash,'query':query,'records':rows,'actual_evaluation_state_hashes_before':before,
 'actual_evaluation_state_hashes_after':after,'actual_evaluation_actions_consumed':0,
 'synthetic_results_not_counted_as_solver_injections':True,'solver_model_calls':0,'grader_calls':0,
 'controller_source_root':str(source)})
