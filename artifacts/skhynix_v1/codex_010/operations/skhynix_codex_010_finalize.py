"""Run through native010 manager python --code-file only after all eight grades.
All validators are read-only. Publication starts only after complete integrity checks.
"""
from pathlib import Path, PurePosixPath
from collections import Counter
import hashlib,json,re,sys,time
import xml.etree.ElementTree as ET
sys.dont_write_bytecode=True

CENTRAL=Path('/home/trimem-runner/skhynix-codex-010')
WIN=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
PUBLIC=WIN/'artifacts/skhynix_v1'
DEST=PUBLIC/'codex_010'
TEMP=Path('/mnt/c/Users/jewon/AppData/Local/Temp')
NAMES=['recovery-20428-r1','recovery-20428-r2','recovery-20438-r1','recovery-20438-r2']
IDS={'swebench_verified--sympy__sympy-'+n for n in ('20428','20438')}
SOURCE_IDS={'swebench_verified--sympy__sympy-'+n for n in ('20428','20438')}
PRIOR008_SHA='36bc6ab2576ad248fd79165481159efd4d08ab848a4ae8ada5d8f7df6055b7ac'
PRIOR009_SHA='5ffa28e73e65ee6fb8441a168fb8a6404deacff7bba8c6483054f64963fb3c7c'
CONTRACT_SHA='db5d5e6ea064e3573ce5e7578c54c2df70f25bfd5b7068aeb9be757490030a2f'
FREEZE_SHA='71c08c94f081dd379be5e0cbe5147490e6f78e7b1a804e016415e5fc2d2d0da2'
BANK_SHA='74b72888e09b5ed45cbde118a8f7811a80882c3dbd1a9800d551ba488d06e6a4'
PREFLIGHT_SHA='d45b5a433a9f5fc7328a446966dd357194dab3dec97896f5a4573eaa3c41fb98'
BATCH_SHA='14ccadf133fc618dbe7e94422c31a4d6bd40035c09d60b4b379f9b36c2bc3ef7'
ARMS={'A':'NO_MEMORY','C':'SKHYNIX_WITH_PUBLIC_DIAGNOSTIC_KNOWLEDGE'}
PRIOR_SHA='2cfe8ec11d79ca10f1025eedcc6e08ec64576701434ad24995645574801d132f'
PROBE_SHA='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
CHECKS=0
ANCHORS={}
ITEMS={}

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(name,condition):
 global CHECKS
 if not condition:raise AssertionError(name)
 CHECKS+=1

def raw_file(path):
 path=Path(path)
 check('unlinked existing bounded evidence: '+str(path),path.is_absolute() and path.is_file()
  and not any(p.is_symlink() for p in (path,*path.parents)) and path.stat().st_size<64*1024*1024)
 raw=path.read_bytes();digest=sha(raw)
 check('immutable evidence throughout finalization: '+str(path),ANCHORS.get(str(path),digest)==digest)
 ANCHORS[str(path)]=digest
 return raw

def read(path):return json.loads(raw_file(path))
def digest(path):return sha(raw_file(path))
def agent(value):return value if isinstance(value,str) and value.startswith('/') else '/root/'+value

def include(label,path):
 name=PurePosixPath(label)
 check('finite canonical public output path',isinstance(label,str) and name.as_posix()==label
  and not name.is_absolute() and '..' not in name.parts and label not in ITEMS)
 check('private payload never exported',not any(part in ('memory-private','official-grader') for part in name.parts)
  and not any(text in label for text in ('grader-private','gate-a-private','checkpoint.json')))
 raw=raw_file(path)
 ITEMS[label]={'raw':raw,'source':str(path),'sha256':sha(raw),'bytes':len(raw)}

def verify_original007():
 root=PUBLIC/'codex_007';manifest_path=root/'public-artifact-manifest.json'
 check('original007 manifest pinned',digest(manifest_path)==PRIOR_SHA)
 manifest=read(manifest_path)
 check('original007 exact208 public files',manifest['file_count']==len(manifest['files'])==208)
 check('original007 exact public inventory',{p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
  =={row['path'] for row in manifest['files']}|{'public-artifact-manifest.json'})
 for row in manifest['files']:
  copied=root/row['path'];check('original007 copy containment',copied.resolve().is_relative_to(root.resolve()))
  for path in (copied,Path(row['source'])):
   raw=raw_file(path);check('original007 source and copy bytes retained',len(raw)==row['bytes'] and sha(raw)==row['sha256'])
 return {'file_count':208,'manifest_sha256':PRIOR_SHA,'original_and_copy_bytes_unchanged':True}

def verify_original008():
 root=PUBLIC/'codex_008';manifest_path=root/'public-artifact-manifest.json'
 check('original008 manifest pinned',digest(manifest_path)==PRIOR008_SHA)
 manifest=read(manifest_path)
 check('original008 exact165 public files',manifest['file_count']==len(manifest['files'])==165)
 check('original008 exact public inventory',{p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
  =={row['path'] for row in manifest['files']}|{'public-artifact-manifest.json'})
 for row in manifest['files']:
  copied=root/row['path'];check('original008 copy containment',copied.resolve().is_relative_to(root.resolve()))
  for path in (copied,Path(row['source'])):
   raw=raw_file(path);check('original008 source and copy bytes retained',len(raw)==row['bytes'] and sha(raw)==row['sha256'])
 return {'file_count':165,'manifest_sha256':PRIOR008_SHA,'original_and_copy_bytes_unchanged':True}

def verify_original009():
 root=PUBLIC/'codex_009';manifest_path=root/'public-artifact-manifest.json'
 check('original009 manifest pinned',digest(manifest_path)==PRIOR009_SHA)
 manifest=read(manifest_path)
 check('original009 exact168 public files',manifest['file_count']==len(manifest['files'])==168)
 check('original009 exact public inventory',{p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
  =={row['path'] for row in manifest['files']}|{'public-artifact-manifest.json'})
 for row in manifest['files']:
  copied=root/row['path'];check('original009 copy containment',copied.resolve().is_relative_to(root.resolve()))
  for path in (copied,Path(row['source'])):
   raw=raw_file(path);check('original009 source and copy bytes retained',len(raw)==row['bytes'] and sha(raw)==row['sha256'])
 return {'file_count':168,'manifest_sha256':PRIOR009_SHA,'original_and_copy_bytes_unchanged':True}

def verify_checkpoint(root,task,arm,source,bank):
 # Build an ephemeral controller from the frozen bank. Existing bridge validators
 # read the real checkpoint/query receipts without opening its mutable SQLite DB.
 import trimem_skhynix_codex_memory as bridge
 import trimem_skhynix_codex_learning as learning
 from enterprise_memory.trimem.agent_runtime import NoMemoryController
 from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
 private=root/'memory-private';digest(private/'checkpoint.json');store=None
 if arm=='NO_MEMORY':
  controller=NoMemoryController();report={'records':0,'verified_skill_count':0,'imported_episode_count':0}
 else:
  check('checkpoint validation arm is declared C',arm=='SKHYNIX')
  graph=learning.LearnedGraphStore(task,bank)
  projection={'validation':dict(bank.report),'source_hash':graph.content_hash,
   'execution_views':{key:raw.decode() for key,raw in sorted(graph.execution_views.items())}}
  check('private source projection is exactly the full immutable candidate content',
   read(private/'historical-source-projection.json')==projection)
  store,report=learning.build_learned_seeded_store(':memory:',task,bank)
  report={**report,'source_projection_sha256':bridge._hash(projection)}
  controller=SkillFirstMemoryController(store,task_id=task.task_id,language=report['language'],
   context_budget_bytes=12000,max_injections_per_task=3,
   repository_retrieval_texts=bridge._repository_retrieval_texts(bank,report),
   repository_exact_task_routes=bridge._repository_exact_task_routes(bank,report,task))
 try:
  identity=bridge._identity(root,task,arm,source,bank)
  binding={**identity,'controller_sha256':controller.content_hash,'bank':report}
  state=bridge._load_state(private,binding)
  bridge._restore_controller(controller,state,private,arm)
  public=read(root/'bank-projection.json')
  check('public projection and frozen matching configuration join checkpoint',
   public['binding_sha256']==bridge._hash(binding) and public['controller_sha256']==controller.content_hash
   and public['bank']==report)
  return state
 finally:
  if store is not None:store.close()

def main():
 check('manager Linux execution only',sys.platform=='linux' and CENTRAL.is_dir())
 check('refuse existing final outputs',not (CENTRAL/'batch-report.json').exists() and not (CENTRAL/'audit.json').exists()
  and not DEST.exists())
 # No partial outcomes or authority imports are inspected before all eight results exist.
 for name in NAMES:
  for cell in ARMS:check('all8 official grades required', (CENTRAL/name/'execution/cells'/cell/'public-result.json').is_file())
 contract=read(CENTRAL/'launch-contract.json');freeze=read(CENTRAL/'source-freeze.json')
 batch=read(CENTRAL/'batch-plan.json');preflight=read(CENTRAL/'preflight.json')
 bank=read(CENTRAL/'diagnostic-bank.json');probe=read(CENTRAL/'public-probe-results.json')
 check('immutable root010 launch freeze and bank anchors',digest(CENTRAL/'launch-contract.json')==CONTRACT_SHA
  and digest(CENTRAL/'source-freeze.json')==FREEZE_SHA and digest(CENTRAL/'diagnostic-bank.json')==BANK_SHA
  and digest(CENTRAL/'preflight.json')==PREFLIGHT_SHA and digest(CENTRAL/'batch-plan.json')==BATCH_SHA)
 expected_keys={(name,cell) for name in NAMES for cell in ARMS}
 check('frozen010 explicit known-failure recovery scope',contract['schema']=='skhynix/native010-launch-contract/1.0'
  and contract['scenario']=='KNOWN_FAILURE_RECOVERY' and contract['names']==NAMES
  and set(contract['evaluation_instances'])==IDS and contract['planned_evaluation_cells']==8
  and contract['replicates_per_task_arm']==2 and contract['arms']==ARMS
  and contract['requested_model']=='gpt-6-astra' and contract['fork_turns']=='none'
  and contract['reasoning_effort']=='INHERITED_PARENT_UNCHANGED'
  and contract['solver_model_calls_so_far']==contract['grader_calls_so_far']==contract['separate_model_api_calls']==0
  and contract['codex_tokens_and_cost'] is None and contract['root_cross_cell_feedback'] is False)
 check('exact counterbalanced launch order',contract['launch_order']==dict(zip(NAMES,[['A','C'],['C','A'],['C','A'],['A','C']])))
 check('fixed limits',contract['limits']=={'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000})
 for name,key in (('source-freeze.json','source_freeze_sha256'),('diagnostic-bank.json','diagnostic_bank_sha256'),
  ('public-probe-results.json','public_probe_sha256'),('validation.xml','validation_sha256'),
  ('solver_prompt_template.txt','evaluation_template_sha256'),('supplemental-manifest.json','manifest_sha256'),
  ('diagnostic-source-continuity.json','diagnostic_source_continuity_sha256'),
  ('validation-evidence.json','validation_evidence_sha256'),
  ('retrieval-policy-development.json','retrieval_policy_development_sha256'),
  ('native008-diagnostic-validation.xml','native008_diagnostic_validation_sha256')):
  check('root input bound to prelaunch contract '+name,digest(CENTRAL/name)==contract[key])
 check('unchanged005 manifest and common007 prompt',contract['manifest_sha256']=='57f369ee641b923ec551698fb52f043e7cf8569e4872f0f691883f47d399f6b9'
  and contract['evaluation_template_sha256']=='745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05')
 check('exact freeze declaration',freeze['schema']=='skhynix/native010-source-freeze/1.0'
  and freeze['head']=='d4fd304339687b42c645ae84872a72eddddcda97'
  and freeze['source_files']==len(freeze['sha256']) and freeze['source_files']>0 and freeze['frozen_before_all_new_solver_calls'] is True)
 for relative,value in freeze['sha256'].items():
  rel=PurePosixPath(relative)
  check('canonical contained freeze entry',isinstance(relative,str) and rel.as_posix()==relative and not rel.is_absolute()
   and '..' not in rel.parts and '\\' not in relative and isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value))
 check('batch exact frozen joins',batch['schema']=='skhynix/native010-recovery-batch/1.0'
  and batch['scenario']=='KNOWN_FAILURE_RECOVERY' and batch['planned_cells']==8 and len(batch['entries'])==4
  and batch['launch_contract_sha256']==digest(CENTRAL/'launch-contract.json')
  and batch['preflight_sha256']==digest(CENTRAL/'preflight.json')
  and {entry['name'] for entry in batch['entries']}==set(NAMES))
 receipt=read(CENTRAL/'validation-evidence.json');xml=ET.fromstring(raw_file(CENTRAL/'validation.xml'))
 check('declared native010 public validation clean and receipt bound',contract['validation_tests']>0
  and len(list(xml.iter('testcase')))==contract['validation_tests']
  and not any(list(xml.iter(tag)) for tag in ('failure','error','skipped'))
  and receipt['status']=='PASS' and receipt['tests']==contract['validation_tests']
  and receipt['xml_sha256']==digest(CENTRAL/'validation.xml'))
 check('validation source map nonempty',isinstance(receipt['source_sha256'],dict) and bool(receipt['source_sha256']))
 validation_runtime=[];validation_public_tests=[]
 for relative,value in receipt['source_sha256'].items():
  if relative in freeze['sha256']:
   check('validated production code is byte-identically source-frozen',freeze['sha256'][relative]==value)
   validation_runtime.append(relative)
  else:
   rel=PurePosixPath(relative)
   check('validation-only source is an explicit public Python unit test',isinstance(relative,str)
    and rel.as_posix()==relative and relative.startswith('tests/unit/test_') and relative.endswith('.py')
    and not rel.is_absolute() and '..' not in rel.parts and '\\' not in relative)
   check('validation-only test bytes match sealed receipt',digest(WIN/relative)==value)
   validation_public_tests.append(relative)
 check('production validation is present',bool(validation_runtime))
 continuity=read(CENTRAL/'diagnostic-source-continuity.json');development=read(CENTRAL/'retrieval-policy-development.json')
 old_central=Path('/home/trimem-runner/skhynix-codex-008')
 old_spec=read(old_central/'diagnostic-source-spec.json');source_spec=read(CENTRAL/'diagnostic-source-spec.json')
 old_bank=read(old_central/'diagnostic-bank.json')
 check('source lessons and provenance retained from native007 via native008',
  bank['records']==old_bank['records']
  and bank['source_specs']==source_spec['sources']==old_spec['sources']==old_bank['source_specs']
  and source_spec['scenario']=='KNOWN_FAILURE_RECOVERY' and source_spec['retrieval_text_policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE'
  and continuity['exact_source_specs_reused'] is continuity['exact_content_bytes_reused'] is True
  and continuity['sources_canonical_sha256']==contract['source_specs_canonical_sha256']==sha(canonical(bank['source_specs']))
  and continuity['source_native008_bank_sha256']==digest(old_central/'diagnostic-bank.json')
  and continuity['source_native008_spec_sha256']==digest(old_central/'diagnostic-source-spec.json')
  ==digest(CENTRAL/'native008-frozen-diagnostic-source-spec.json')
  and continuity['probe_sha256']==PROBE_SHA and continuity['source_run']=='native007'
  and continuity['source_cells']=={'eval-20428':'A','eval-20438':'A'} and continuity['gate_b_verified_skills']==0)
 check('explicit scoped same-task route development',contract['retrieval_text_policy']==development['policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE'
  and contract['native008_outputs_used_for_knowledge_content'] is continuity['native008_outputs_used_for_knowledge_content'] is False
  and contract['prior_public_retrieval_used_for_routing_design'] is continuity['prior_public_retrieval_used_for_routing_design'] is True
  and contract['expected_actual_C_injections_per_cell']==1
  and development['native008_C_cells_with_memory']==2 and development['native008_C_total_cells']==4
  and development['native009_C_cells_with_memory']==0 and development['native009_C_total_cells']==4
  and development['lessons_changed'] is development['prompt_changed'] is development['budgets_changed'] is development['production_default_changed'] is False
  and development['separate_transfer_effect_not_tested'] is True
  and digest(CENTRAL/'native008-diagnostic-validation.xml')==digest(old_central/'validation.xml'))
 check('diagnostic failure provenance remains explicit',bank['schema']=='skhynix/native-diagnostic-bank/1.0'
  and bank['scenario']=='KNOWN_FAILURE_RECOVERY' and bank['frozen'] is True
  and bank['source_official_resolved'] is bank['analyst_interpretations_verified'] is bank['target_fix_verified'] is False
  and bank['gate_b']=={'status':'NOT_PROMOTED','verified_skill_count':0}
  and bank['gate_a']['episode_count']==2 and all(row['succeeded'] is False for row in bank['gate_a']['episodes'])
  and bank['knowledge_relation_count']==0 and bank['evaluation_private_episode_count']==0 and bank['online_learning'] is False
  and bank['patch_content_imported'] is bank['grader_test_content_imported'] is False
  and set(bank['source_target_overlap_task_ids'])==set(bank['training_task_ids'])==set(bank['evaluation_task_ids'])==IDS==SOURCE_IDS
  and bank['retrieval_text_policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE'
  and bank['source_selection_uses_evaluation_outcomes'] is True)
 check('public probe original32 protected inputs',digest(CENTRAL/'public-probe-results.json')==PROBE_SHA
  and probe['schema']=='skhynix/native008-public-failure-diagnostic/1.0'
  and probe['originals_unchanged'] is True and probe['hidden_test_text_or_names_accessed'] is False
  and probe['model_calls']==probe['official_grader_calls']==0 and len(probe['protected_original_sha256'])==32)
 for path,value in probe['protected_original_sha256'].items():check('protected public-probe source bytes unchanged',digest(Path(path))==value)
 previous=verify_original007();previous008=verify_original008();previous009=verify_original009()
 check('synthetic preflight kept actual state unchanged',preflight['schema']=='skhynix/native010-preflight/1.0' and preflight['status']=='PASS'
  and preflight['bank_sha256']==contract['diagnostic_bank_sha256'] and preflight['source_freeze_sha256']==contract['source_freeze_sha256']
  and preflight['actual_states_before']==preflight['actual_states_after']
  and preflight['actual_solver_actions']==preflight['official_grades']==0
  and preflight['synthetic_results_not_actual_solver_injections'] is True
  and preflight['retrieval_text_policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE' and preflight['zero_lexical_overlap_queries'] is True)
 source=CENTRAL/NAMES[0]/'source'
 for relative,value in freeze['sha256'].items():
  check('first frozen source verified before any source imports',digest(source/relative)==value)
 sys.path[:0]=[str(source/'scripts'),str(source/'src')]
 import trimem_skhynix_codex as broker
 import trimem_skhynix_codex_batch as batch_module
 import trimem_skhynix_codex_learning as learning
 from enterprise_memory.trimem.agent_runtime import CANONICAL_FAILED_CELL_NOOP
 from enterprise_memory.trimem.skill_memory import canonical_hash
 from enterprise_memory.trimem.skill_runtime import _tokens
 from enterprise_memory.trimem.ppr import lexical_similarity
 broker.block_model_client()
 entries={row['name']:row for row in batch['entries']};plans={};records={};wire_records={};loaded_banks={};snapshot_summary={}
 frozen_py={k:v for k,v in freeze['sha256'].items() if k.endswith('.py')}
 state_paths=set()
 for name in NAMES:
  base=CENTRAL/name;run=base/'execution';snap=read(base/'source-snapshot.json')
  check('exact operational source snapshot '+name,snap['schema']=='skhynix/native010-operational-source-snapshot/1.0'
   and snap['source']==str(base/'source') and snap['copied_from']==str(WIN)
   and snap['source_freeze_sha256']==contract['source_freeze_sha256'] and snap['copied_file_sha256']==freeze['sha256'])
  for relative,value in freeze['sha256'].items():
   path=base/'source'/relative;check('snapshot remains contained',path.resolve().is_relative_to((base/'source').resolve()))
   check('snapshot bytes identical to frozen map '+name+':'+relative,digest(path)==value)
  plan=broker.load_plan(run);plans[name]=plan;entry=entries[name];target='swebench_verified--sympy__sympy-'+name.split('-')[1]
  check('plan loader and raw/canonical batch hashes '+name,read(run/'plan.json')==plan
   and raw_file(run/'plan.sha256').decode().strip()==sha(canonical(plan))
   and entry['plan_sha256']==digest(run/'plan.json') and entry['run_root']==str(run)
   and entry['target_id']==plan['public_task']['task_id']==target and entry['replicate']==int(name[-1])
   and entry['cells']==contract['launch_order'][name])
  check('fresh unique recovery identity and no procedure '+name,
   plan['experiment_id']=='skhynix-native-codex-010-'+name and plan['solver_user_id']=='native-codex-010-'+name
   and plan['requested_solver_model']=='gpt-6-astra' and plan['procedure_declaration'] is None
   and plan['cells']=={'A':'NO_MEMORY','B':'EXISTING_M2','C':'SKHYNIX'}
   and plan['limits']=={'repository_actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000}
   and plan['public_python']=='/opt/miniconda3/envs/testbed/bin/python'
   and {k:v for k,v in plan['source_hashes'].items() if k.endswith('.py')}==frozen_py)
  check('plan uses exact frozen diagnostic inputs',plan['frozen_memory_bank']=={'path':str(CENTRAL/'diagnostic-bank.json'),'sha256':contract['diagnostic_bank_sha256']}
   and plan['supplemental_manifest']['path']==str(CENTRAL/'supplemental-manifest.json')
   and plan['supplemental_manifest']['sha256']==contract['manifest_sha256'])
  loaded=learning.load_frozen_bank(CENTRAL/'diagnostic-bank.json',contract['diagnostic_bank_sha256'],broker.task_from_plan(plan))
  check('actual read-only diagnostic source/probe/GateA validator accepts '+name,loaded.promoted_skill is None
   and len(loaded.records)==1 and {r['source']['task_id'] for r in loaded.records}=={target}
   and all(r['source']['resolved'] is False and r['source']['task_id']==target for r in loaded.records)
   and loaded.manifest['scenario']=='KNOWN_FAILURE_RECOVERY'
   and loaded.manifest['retrieval_text_policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE')
  loaded_banks[name]=loaded;records[name]={r['memory_id']:r for r in loaded.records};wire_records[name]={}
  task=broker.task_from_plan(plan);expected_entries=[]
  for record in loaded.records:
   knowledge_payload={'org_id':task.org_id,'repository':task.repository,'title':record['title'],'content':record['content'],'revision':task.commit,'language':record['language']}
   memory_id='knowledge:'+canonical_hash(knowledge_payload)[7:]
   view={'layer':'REPOSITORY_SEMANTIC','title':record['title'],'content':record['content'],'revision':task.commit}
   wire=json.dumps(view,ensure_ascii=False,sort_keys=True)
   wire_records[name][memory_id]={'view':view,'exact_text':wire,'sha256':sha(wire.encode()),'byte_count':len(wire.encode()),
    'source_memory_id':record['memory_id'],'source_task_id':record['source']['task_id'],'source_content_sha256':record['content_sha256']}
   expected_entries.append({'memory_id':record['memory_id'],'knowledge_id':memory_id,
    'shared_source_content_sha256':record['content_sha256'],'shared_source_content_bytes':record['content_bytes'],
    'source_revision':record['source']['revision'],'transfer_view_revision':task.commit})
  projection=read(run/'cells/C/bank-projection.json')
  check('public repository-knowledge projection joins the exact original same-task diagnostic source',
   projection['bank']['entries']==expected_entries and projection['bank']['retrieval_text_policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE')
  snapshot_summary[name]={'copied_files':len(freeze['sha256']),'source_snapshot_sha256':digest(base/'source-snapshot.json'),'plan_sha256':sha(canonical(plan))}
  for cell in ('A','B','C'):
   root=run/'cells'/cell
   for filename in ('state.json','tool-events.jsonl','memory-private/checkpoint.json'):state_paths.add(str(root/filename))
  state_paths.add(str(run/'plan.json'))
  idle=run/'cells/B';state=read(idle/'state.json');idle_events,_=broker.audit_events(idle)
  check('unusedB remains empty '+name,state['status']=='OPEN' and state['actions']==0 and state['started_at'] is None and not idle_events
   and not any((idle/file).exists() for file in ('public-result.json','grader-private.json','grader-pending.json','submission.json','submission.diff'))
   and not (CENTRAL/'solver-launches'/(name+'-B.json')).exists())
  for filename in ('state.json','tool-events.jsonl','memory-private/checkpoint.json'):
   path=idle/filename;value=digest(path) if path.exists() else None
   check('unusedB matches original preflight bytes',preflight['actual_states_before'].get(str(path))==value)
 check('exact preflight40 protected state/plan entries',set(preflight['actual_states_before'])==state_paths and len(state_paths)==40)
 synthetic=preflight['synthetic']
 check('exact8 separate synthetic cells',len(synthetic)==8 and {(r['name'],r['arm']) for r in synthetic}=={(name,arm) for name in NAMES for arm in ('NO_MEMORY','SKHYNIX')})
 for row in synthetic:
  items=row['injections'];allowed=wire_records[row['name']]
  synthetic_query=row['query']
  query_text=' '.join((synthetic_query['objective'],synthetic_query['operation'],*synthetic_query['symbols'],*synthetic_query['apis'],*synthetic_query['errors']))
  check('synthetic independent preflight query really has zero lexical overlap',
   all(not _tokens(query_text).intersection(_tokens(wire['view']['title']+' '+wire['view']['content'])) for wire in allowed.values()))
  if row['arm']=='NO_MEMORY':check('synthetic baseline contains no memory',items==[] and row['new_injection_count']==0)
  else:
   check('synthetic selected the exact declared same-task diagnostic record',len(items)==1 and items[0]['memory_id'] in allowed)
   item=items[0];wire=allowed[item['memory_id']]
   check('synthetic actual repository-knowledge wrapper and wire bytes',item['kind']=='REPOSITORY_SEMANTIC'
    and json.loads(item['exact_text'])==wire['view'] and item['exact_text']==wire['exact_text']
    and item['sha256']==wire['sha256'] and item['byte_count']==wire['byte_count']
    and item['confidence']==0.0 and row['new_injection_count']==1)
   check('synthetic route explicitly selects bound task without fabricated similarity',
    any(decision['bank']=='REPOSITORY_SEMANTIC' and decision['decision']=='USE'
     and decision['policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE' and decision['exact_task_route']=={
      'policy':'EXACT_TASK_DIAGNOSTIC_ROUTE','task_id':wire['source_task_id'],
      'candidate_ids':[item['memory_id']],'selected':True} for decision in row['decisions']))
 attestations=read(CENTRAL/'attestations.json');launch_files=list((CENTRAL/'solver-launches').glob('*.json'))
 check('exact8 unique attestations',len(attestations)==8 and {(row['run'],row['cell']) for row in attestations}==expected_keys
  and len({agent(row['agent']) for row in attestations})==8)
 check('exact8 unique launch receipts',len(launch_files)==8 and {path.name for path in launch_files}=={name+'-'+cell+'.json' for name,cell in expected_keys})
 attest={(row['run'],row['cell']):row for row in attestations};rows=[];launches={};seen_agents=set()
 for name in NAMES:
  plan=plans[name];run=CENTRAL/name/'execution'
  for cell in ARMS:
   root=run/'cells'/cell;launch=read(CENTRAL/'solver-launches'/(name+'-'+cell+'.json'));launches[name,cell]=launch
   template=raw_file(CENTRAL/'solver_prompt_template.txt');prompt=template.decode().replace('\r\n','\n').replace('\r','\n').replace('{{BASE}}',str(CENTRAL/name)).replace('{{CELL}}',cell).encode()
   filled=CENTRAL/'solver-launches'/(name+'-'+cell+'-prompt.txt')
   check('fresh exact native launch and prompt '+name+cell,launch['schema']=='skhynix/native010-solver-launch/1.0'
    and launch['name']==name and launch['cell']==cell and launch['requested_model']=='gpt-6-astra'
    and launch['fork_turns']=='none' and launch['reasoning_effort']=='INHERITED_PARENT_UNCHANGED'
    and launch['root_cross_cell_feedback'] is False and launch['separate_model_api_calls']==0
    and launch['template_sha256']==sha(template) and launch['filled_prompt_sha256']==sha(prompt)==digest(filled)
    and raw_file(filled)==prompt and agent(launch['agent']) not in seen_agents)
   seen_agents.add(agent(launch['agent']))
   row=batch_module.verify_result_receipt(plan,run,cell);submission=read(root/'submission.json');state=read(root/'state.json')
   result_raw=raw_file(root/'public-result.json');events,tail=broker.audit_events(root)
   submitted_patch=raw_file(root/'submission.diff')
   expected_graded_patch=submitted_patch if submitted_patch else CANONICAL_FAILED_CELL_NOOP.encode()
   check('official receipt resolved status patch and completion '+name+cell,row['agent_completed'] is True
    and row['official'] is True and row['grader_status']=='success' and type(row['resolved']) is bool
    and row['patch_sha256']==digest(root/'submission.diff')==submission['patch_sha256']
    and row['grader_patch_sha256']==sha(expected_graded_patch)
    and row['grader_patch_source']==('NATIVE_CODEX_PATCH' if submitted_patch else 'CANONICAL_FAILED_CELL_NOOP')
    and row['separate_model_api_calls']==0 and row['codex_tokens_and_cost'] is None)
   check('bound completion attestation '+name+cell,agent(attest[name,cell]['agent'])==agent(launch['agent'])
    and attest[name,cell]['patch_sha256']==row['patch_sha256']
    and attest[name,cell]['only_assigned_broker'] is attest[name,cell]['no_external_access'] is attest[name,cell]['no_subagents'] is True)
   check('no actions after single submission '+name+cell,len(events)==state['actions']==row['actions']<=120
    and sum(event['request'].get('op')=='submit' and event['result'].get('ok') is True for event in events)==1
    and events[-1]['request']['op']=='submit' and events[-1]['result']['ok'] is True and state['status']=='SUBMITTED')
   check('actual wall/memory bounds '+name+cell,0<=row['wall_seconds']<=1200 and row['memory_injections']<=3 and row['memory_bytes']<=12000
    and abs(row['wall_seconds']-(submission['submitted_at']-submission['started_at']))<0.001)
   check('all frozen prerequisites precede actual actions '+name+cell,contract['frozen_at_unix_seconds']<state['started_at']
    and all((CENTRAL/file).stat().st_mtime<state['started_at'] for file in ('source-freeze.json','launch-contract.json','diagnostic-bank.json','preflight.json','batch-plan.json'))
    and (CENTRAL/'batch-plan.json').stat().st_mtime<launch['recorded_at_unix_seconds'])
   unique={};exposures=Counter();new_count=0;queries=0;source_exposures=Counter()
   for event in events:
    response=event['result'];check('event budget action accounting',response['budget']['actions_remaining']==120-event['sequence'])
    if event['request'].get('op')!='recall' or response.get('ok') is not True:continue
    call=response['result'];queries+=1;new_count+=call['new_injection_count']
    check('native recall no model call',call.get('model_api_calls',0)==0)
    for item in call['injections']:
     check('actual injection is the frozen same-task diagnostic record',cell=='C' and item['memory_id'] in wire_records[name])
     wire=wire_records[name][item['memory_id']]
     check('every actual injection retains full provenance and exact frozen wrapper bytes',item['kind']=='REPOSITORY_SEMANTIC'
      and json.loads(item['exact_text'])==wire['view'] and item['exact_text']==wire['exact_text']
      and item['sha256']==wire['sha256']==sha(item['exact_text'].encode())
      and item['byte_count']==wire['byte_count']==len(item['exact_text'].encode()))
     query=event['request']['query'];query_text=' '.join((query['objective'],query['operation'],*query.get('symbols',[]),*query.get('apis',[]),*query.get('errors',[])))
     expected_lexical=lexical_similarity(' '.join(sorted(_tokens(query_text))),
      ' '.join(sorted(_tokens(wire['view']['title']+' '+wire['view']['content']))))
     check('actual exact-task delivery retains real lexical score',item['confidence']==expected_lexical)
     check('actual route trace declares exact-task use rather than similarity eligibility',
      any(decision['bank']=='REPOSITORY_SEMANTIC' and decision['decision']=='USE'
       and decision['policy']=='EXACT_TASK_DIAGNOSTIC_ROUTE' and decision['exact_task_route']=={
        'policy':'EXACT_TASK_DIAGNOSTIC_ROUTE','task_id':row['target_id'],
        'candidate_ids':[item['memory_id']],'selected':True} for decision in call['decisions']))
     source_exposures[wire['source_task_id']]+=1
     if item['memory_id'] in unique:check('retained same memory bytes on replay',
      all(unique[item['memory_id']][key]==item[key] for key in ('memory_id','exact_text','sha256','byte_count','kind')))
     unique[item['memory_id']]=item;exposures[item['kind']]+=1
   check('official memory counters match live broker only',row['memory_injections']==len(unique) and row['memory_bytes']==sum(item['byte_count'] for item in unique.values())
    and row['memory_queries']==queries and new_count==len(unique))
   checkpoint=verify_checkpoint(root,broker.task_from_plan(plan),plan['cells'][cell],CENTRAL/name/'source',loaded_banks[name])
   check('real controller checkpoint joins all successful live recalls',checkpoint['calls']==queries
    and {item['memory_id']:item for item in checkpoint['controller'].get('ledger',[])}==unique)
   if cell=='A':check('baseline zero memory',not unique and not exposures and row['memory_bytes']==0)
   else:check('exact-task route delivered once and only exact-task source',len(unique)==new_count==row['memory_injections']==1
    and set(source_exposures)=={row['target_id']} and row['memory_bytes']>0)
   rows.append({'name':name,'target_id':row['target_id'],'replicate':int(name[-1]),'cell':cell,'arm':ARMS[cell],
    **{key:row[key] for key in ('resolved','actions','tool_errors','wall_seconds','agent_completed','memory_queries','memory_injections','memory_bytes','patch_sha256')},
    'official_public_result_sha256':sha(result_raw),'new_injection_count':new_count,
    'unique_injections_by_kind':dict(Counter(item['kind'] for item in unique.values())),
    'exposures_by_kind_including_replay':dict(exposures),
    'candidate_source_task_ids':sorted({r['source']['task_id'] for r in records[name].values()}),'injected_source_task_ids':sorted(source_exposures),
    'exposures_by_source_task_including_replay':dict(source_exposures),
    'injected_records':[{'memory_id':key,'source_memory_id':wire_records[name][key]['source_memory_id'],
     'source_task_id':wire_records[name][key]['source_task_id'],'content_sha256':wire_records[name][key]['source_content_sha256'],
     'wire_sha256':item['sha256'],'bytes':item['byte_count'],'kind':item['kind'],'original_lexical_score':item['confidence']} for key,item in sorted(unique.items())],
    'source_evidence_kind':'PUBLIC_DIAGNOSTIC_INTERPRETATION_OF_COMPLETED_FAILURES','verified_skill_exposures':0})
  order=contract['launch_order'][name]
  check('actual launch order matches frozen pair order',launches[name,order[0]]['recorded_at_unix_seconds']<launches[name,order[1]]['recorded_at_unix_seconds'])
 comparison={}
 for cell in ARMS:
  selected=[row for row in rows if row['cell']==cell];kinds=Counter();exposures=Counter();source_counts=Counter();source_exposures=Counter()
  for row in selected:
   kinds.update(row['unique_injections_by_kind']);exposures.update(row['exposures_by_kind_including_replay'])
   source_counts.update(item['source_task_id'] for item in row['injected_records'])
   source_exposures.update(row['exposures_by_source_task_including_replay'])
  comparison[cell]={'arm':ARMS[cell],'n':4,'resolved':sum(row['resolved'] for row in selected),'solve_rate':sum(row['resolved'] for row in selected)/4,
   'actions':sum(row['actions'] for row in selected),'max_requests':max(row['actions'] for row in selected),
   'tool_errors':sum(row['tool_errors'] for row in selected),'wall_seconds':sum(row['wall_seconds'] for row in selected),
   'memory_injections':sum(row['memory_injections'] for row in selected),'memory_bytes':sum(row['memory_bytes'] for row in selected),
   'new_injection_count':sum(row['new_injection_count'] for row in selected),'unique_injections_by_kind':dict(kinds),
   'exposures_by_kind_including_replay':dict(exposures),'unique_injections_by_source_task':dict(source_counts),
   'exposures_by_source_task_including_replay':dict(source_exposures),
   'cells_with_memory_exposure':sum(bool(row['exposures_by_kind_including_replay']) for row in selected)}
 intervals=[];pair_intervals={}
 for name in NAMES:
  pair=[]
  for cell in ARMS:
   submission=read(CENTRAL/name/'execution/cells'/cell/'submission.json')
   pair.append((submission['started_at'],submission['submitted_at']))
   intervals.extend(((submission['started_at'],1),(submission['submitted_at'],-1)))
  pair_intervals[name]=(min(start for start,end in pair),max(end for start,end in pair))
 for previous_name,next_name in zip(NAMES,NAMES[1:]):
  check('each matched pair completes before next pair starts',pair_intervals[previous_name][1]<=pair_intervals[next_name][0])
 active=0;peak=0
 for stamp,delta in sorted(intervals):active+=delta;peak=max(peak,active)
 check('at most two active broker solver intervals',active==0 and peak<=2)
 paired=[{'name':name,'target_id':entries[name]['target_id'],'replicate':int(name[-1]),
  **{cell:next(row['resolved'] for row in rows if row['name']==name and row['cell']==cell) for cell in ARMS}} for name in NAMES]
 by_task={task:{cell:{'n':2,'resolved':sum(row['resolved'] for row in rows if row['target_id']==task and row['cell']==cell),
  'replicate_outcomes':[row['resolved'] for row in rows if row['target_id']==task and row['cell']==cell]} for cell in ARMS} for task in sorted(IDS)}
 diagnostic=read(CENTRAL/'native010_grader_integrity_diagnostic.json')
 diagnostic_helper_sha=digest(TEMP/'native010_grader_integrity_diagnostic.py')
 check('secondary posthoc diagnostic helper and contract are bound',
  diagnostic_helper_sha=='93d49c40288e2014acd14ac2402db1f425d71243cc39c4784911c4b3f69c9101'
  and diagnostic['diagnostic_helper_sha256']==diagnostic_helper_sha
  and diagnostic['frozen_launch_contract_sha256']==CONTRACT_SHA
  and digest(TEMP/'native010_grader_integrity_diagnostic.json')==digest(CENTRAL/'native010_grader_integrity_diagnostic.json'))
 check('secondary sanitized grading diagnostic identity',diagnostic['schema']=='skhynix/native010-grader-integrity-count-diagnostic/1.0'
  and diagnostic['scientific_role']=='SECONDARY_POSTHOC_GRADING_INTEGRITY_DIAGNOSTIC'
  and diagnostic['scope']=='EXACT_EIGHT_COMPLETED_NATIVE010_RECOVERY_CELLS'
  and diagnostic['status']=='COMPLETE_READ_ONLY' and diagnostic['model_calls']==diagnostic['official_grader_calls']==0
  and diagnostic['test_commands_executed']==diagnostic['evidence_mutations']==0
  and diagnostic['primary_issue_solve_rate_unchanged'] is diagnostic['replicates_are_not_independent_task_samples'] is True
  and diagnostic['distinct_reused_tasks']==2
  and diagnostic['hidden_fixture_or_gold_patch_files_opened'] is diagnostic['test_names_or_paths_exported'] is diagnostic['raw_test_logs_exported'] is False
  and diagnostic['expected_identifiers_used_only_for_opaque_status_counts'] is True
  and len(diagnostic['rows'])==8 and {(r['run'],r['cell']) for r in diagnostic['rows']}==expected_keys)
 for item in diagnostic['rows']:
  actual=next(r for r in rows if r['name']==item['run'] and r['cell']==item['cell'])
  public=read(CENTRAL/item['run']/'execution/cells'/item['cell']/'public-result.json')
  check('secondary diagnostic joins actual immutable public grade and patch',item['source_hashes']['public_result']==actual['official_public_result_sha256']
   and item['source_hashes']['private_grade_envelope']==public['grader_private_sha256']
   and item['submitted_patch_sha256']==actual['patch_sha256'] and item['official_resolved']==actual['resolved']
   and item['grader_patch_sha256']==public['grader_patch_sha256'] and item['grader_patch_source']==public['grader_patch_source']
   and item['submitted_patch_matches_grader_execution_contract'] is item['agent_completed'] is True)
  for domain in ('FAIL_TO_PASS','PASS_TO_PASS'):
   counts=item['domains'][domain];hist=counts['parsed_status_histogram'];opaque=counts['status_identifier_sha256']
   check('secondary expected domain count arithmetic is complete',
    all(type(counts[key]) is int and counts[key]>=0 for key in ('expected','official_success','official_failure'))
    and counts['expected']==counts['official_success']+counts['official_failure']==sum(hist.values())
    and set(hist)<=set(('PASSED','FAILED','ERROR','XFAIL','SKIPPED','MISSING'))
    and all(type(value) is int and value>=0 for value in hist.values()))
   check('secondary status keys contain only opaque hash counts',set(opaque)==set(hist)
    and all(len(opaque[key])==hist[key] for key in hist)
    and all(isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) for values in opaque.values() for value in values)
    and len({value for values in opaque.values() for value in values})==counts['expected']
    and counts['missing_identifier_sha256']==sorted(opaque.get('MISSING',[])))
 for task in sorted(IDS):
  selected=[item for item in diagnostic['rows'] if entries[item['run']]['target_id']==task]
  for domain in ('FAIL_TO_PASS','PASS_TO_PASS'):
   check('all four repetitions/arms retain identical official expected test domains',len(selected)==4
    and len({item['domains'][domain]['expected_id_set_sha256'] for item in selected})==1
    and len({item['domains'][domain]['expected'] for item in selected})==1
    and len({tuple(sorted(value for values in item['domains'][domain]['status_identifier_sha256'].values() for value in values)) for item in selected})==1)
 integrity_clear=all(item['patch_applied'] and not item['infra_failure'] and item['test_markers_present']
  and not any(item['bad_execution_marker_counts'].values())
  and not any(domain['parsed_status_histogram'].get('MISSING',0) for domain in item['domains'].values()) for item in diagnostic['rows'])
 check('secondary integrity findings include every observed issue without exclusion',type(diagnostic['integrity_findings_all_clear']) is bool
  and diagnostic['integrity_findings_all_clear']==integrity_clear)
 for cell in ARMS:
  selected=[r for r in diagnostic['rows'] if r['cell']==cell];aggregate=diagnostic['aggregate'][cell]
  check('secondary aggregate recomputes from all four retained observations',aggregate['completed_attempts']==4
   and aggregate['official_resolved']==comparison[cell]['resolved']
   and aggregate['fail_to_pass_expected']==sum(r['domains']['FAIL_TO_PASS']['expected'] for r in selected)
   and aggregate['fail_to_pass_passed']==sum(r['domains']['FAIL_TO_PASS']['official_success'] for r in selected)
   and aggregate['pass_to_pass_expected']==sum(r['domains']['PASS_TO_PASS']['expected'] for r in selected)
   and aggregate['pass_to_pass_passed']==sum(r['domains']['PASS_TO_PASS']['official_success'] for r in selected)
   and aggregate['expected_identifiers_missing']==sum(domain['parsed_status_histogram'].get('MISSING',0) for r in selected for domain in r['domains'].values()))
 report={'schema':'skhynix/native010-recovery-report/1.0','status':'COMPLETE','scenario':'KNOWN_FAILURE_RECOVERY',
  'planned_cells':8,'completed_cells':8,'distinct_tasks':2,'matched_task_replicate_observations':4,
  'comparison':comparison,'primary_delta_percentage_points':100*(comparison['C']['solve_rate']-comparison['A']['solve_rate']),
  'paired_outcomes':paired,'per_task':by_task,'cells':rows,'all_agent_completed':True,'actual_fresh_sessions':8,
  'gate_a_failed_source_episodes':2,'gate_b_verified_skills':0,'knowledge_relation_count':0,
  'separate_model_api_calls':0,'codex_tokens_and_cost':None,
  'peak_active_broker_intervals':peak,
  'secondary_posthoc_official_test_counts':{'aggregate':diagnostic['aggregate'],
   'diagnostic_sha256':digest(CENTRAL/'native010_grader_integrity_diagnostic.json'),
   'diagnostic_helper_sha256':diagnostic_helper_sha,'integrity_findings_all_clear':integrity_clear,
   'interpretation':'Secondary official test-execution counts; not issue resolution or independent new tasks. Every fixed cell retained; inspect recorded integrity findings before interpreting partial progress.'},
  'candidate_source_content_sha256':{row['source']['task_id']:row['content_sha256'] for row in bank['records']},
  'cohort_scope':contract['cohort_scope'],'retrieval_text_policy':'EXACT_TASK_DIAGNOSTIC_ROUTE',
  'native008_and_native009_delivery_findings_used_for_route_design':True,'native008_outputs_used_for_knowledge_content':False,
  'limitations':['Known prior failures selected using outcomes; same-task analyst diagnostic memory. This is development recovery, not unseen transfer.',
   'Four task-replicate observations comprise only two distinct tasks; repetitions are not independent new issues.',
   'The exact-task delivery policy addresses observed native008 and native009 delivery failures; original native007 source lessons and common prompt were retained. No native010 solver outcome informed this frozen design.',
   'Source patches remained officially unresolved; probe expectations and analyst lessons are not verified successful skills.',
   'Synthetic preflight injections are excluded from actual solver exposure counts.',
   'Native model and host restrictions are requested/self-reported protocol metadata, not independent backend or OS attestation.']}
 # Finite public allowlist. Public broker journals and submitted patches are explicitly authorized;
 # grader-private records, private databases/checkpoints and grader logs never enter this collection.
 for name in ('supplemental-manifest.json','solver_prompt_template.txt','evaluation-task-descriptors.json','public-probe-results.json',
  'diagnostic-source-spec.json','diagnostic-bank.json','source-freeze.json','validation.xml','validation-evidence.json','native008-diagnostic-validation.xml',
  'native008-frozen-diagnostic-source-spec.json','diagnostic-source-continuity.json','retrieval-policy-development.json',
  'launch-contract.json','attestations.json','preflight.json','batch-plan.json','native010_grader_integrity_diagnostic.json'):
  include(name,CENTRAL/name)
 if (CENTRAL/'operations-note.json').is_file():include('operations-note.json',CENTRAL/'operations-note.json')
 for name in NAMES:
  base=CENTRAL/name;run=base/'execution';plan=plans[name]
  include(name+'/source-snapshot.json',base/'source-snapshot.json')
  for file in ('plan.json','plan.sha256'):include(name+'/'+file,run/file)
  for cell in ('A','B','C'):
   root=run/'cells'/cell
   for file in ('state.json','public-task.json','workspace.json','bank-projection.json'):
    include(name+'/cells/'+cell+'/'+file,root/file)
   if cell in ARMS:
    for file in ('tool-events.jsonl','submission.json','submission.diff','public-result.json'):
     include(name+'/cells/'+cell+'/'+file,root/file)
    for suffix in ('.json','-prompt.txt'):
     label='solver-launches/'+name+'-'+cell+suffix;include(label,CENTRAL/label)
   for file in ('solver-sandbox-preflight.json','checkout-preflight.json'):
    rel='environment/cells/'+plan['cells'][cell]+'/'+plan['public_task']['task_id']+'/control/'+file
    include(name+'/'+rel,run/rel)
  for file in ('local-environment-preflight.json','official-harness-loader-preflight.json'):
   rel='environment/control/'+file;include(name+'/'+rel,run/rel)
 include('operations/native010_grader_integrity_diagnostic.py',TEMP/'native010_grader_integrity_diagnostic.py')
 for suffix in ('init','preflight','record','manage','finalize'):
  name='skhynix_codex_010_'+suffix+'.py';include('operations/'+name,TEMP/name)
 # Last pass verifies that all read-only validation and collection reads preserved every anchor.
 for path,value in list(ANCHORS.items()):check('all observed input bytes retained before publication',sha(Path(path).read_bytes())==value)
 audit={'schema':'skhynix/native010-integrity-audit/1.0','status':'PASS_FINAL','checks_passed':CHECKS,'checks_failed':0,'pending':[],
  'planned_cells':8,'completed_cells':8,'all_agent_completed':True,'distinct_fresh_launch_agents':len(seen_agents),
  'source_snapshots':snapshot_summary,'prior007_public_archive':previous,'prior008_public_archive':previous008,'prior009_public_archive':previous009,'probe_protected_input_count':32,
  'failed_source_episode_count':2,'verified_skill_count':0,'knowledge_relation_count':0,
  'retrieval_text_policy':'EXACT_TASK_DIAGNOSTIC_ROUTE','all_C_checkpoints_restore_under_frozen_exact_task_route':True,
  'validation_runtime_files':validation_runtime,'validation_public_test_files':validation_public_tests,
  'synthetic_wire_wrapper_validated':True,'secondary_grading_diagnostic_sha256':digest(CENTRAL/'native010_grader_integrity_diagnostic.json'),
  'secondary_grading_integrity_findings_all_clear':integrity_clear,
  'frozen_bank_sha256':contract['diagnostic_bank_sha256'],'frozen_contract_sha256':digest(CENTRAL/'launch-contract.json'),
  'batch_plan_sha256':digest(CENTRAL/'batch-plan.json'),'finalizer_sha256':digest(TEMP/'skhynix_codex_010_finalize.py'),
  'first_observed_artifact_hashes':dict(ANCHORS),'unused_B_cells_verified':4,
  'solver_model_calls':0,'official_grader_calls':0,'container_calls':0,'authority_mutations':0,
  'private_payloads_exported':False,'audit_at_unix_seconds':time.time()}
 audit['checks_passed']=CHECKS
 final_payloads={'batch-report.json':canonical(report)+b'\n','audit.json':canonical(audit)+b'\n'}
 for name,raw in final_payloads.items():
  check('final output still absent',not (CENTRAL/name).exists())
  ITEMS[name]={'raw':raw,'source':str(CENTRAL/name),'sha256':sha(raw),'bytes':len(raw)}
 check('destination still absent',not DEST.exists())
 # No frozen evidence is overwritten. These are new final outputs only.
 for name,raw in final_payloads.items():
  with (CENTRAL/name).open('xb') as stream:stream.write(raw)
 DEST.mkdir(parents=True,exist_ok=False)
 manifest=[]
 for label,item in sorted(ITEMS.items()):
  path=DEST/label;check('public output stays within destination',path.resolve().is_relative_to(DEST.resolve()))
  path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('xb') as stream:stream.write(item['raw'])
  check('new public copy exact byte hash',sha(path.read_bytes())==item['sha256'])
  manifest.append({'path':label,'source':item['source'],'bytes':item['bytes'],'sha256':item['sha256']})
 public_manifest={'schema':'skhynix/native-public-manifest/1.0','file_count':len(manifest),'files':manifest,'manifest_excludes_itself':True,
  'copy_policy':'Finite scoped known-failure recovery public evidence including authorized broker journals and submitted patches; no private graders, private authority/checkpoints, hidden fixtures or raw grader logs.'}
 manifest_raw=(json.dumps(public_manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with (DEST/'public-artifact-manifest.json').open('xb') as stream:stream.write(manifest_raw)
 check('final exact public inventory',{p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}=={row['path'] for row in manifest}|{'public-artifact-manifest.json'})
 for row in manifest:
  for path in (DEST/row['path'],Path(row['source'])):
   check('final source and copied public bytes identical',path.stat().st_size==row['bytes'] and sha(path.read_bytes())==row['sha256'])
 print(json.dumps({'status':'PASS_FINAL_AND_PUBLIC_BYTES_VERIFIED','audit_checks_passed':audit['checks_passed'],
  'completed_cells':8,'comparison':comparison,'primary_delta_percentage_points':report['primary_delta_percentage_points'],
  'public_files':len(manifest),'public_bytes':sum(row['bytes'] for row in manifest),'manifest_sha256':sha(manifest_raw),
  'all_agent_completed':True,'max_requests':max(row['actions'] for row in rows),'prior007_unchanged':True,'prior008_unchanged':True,'prior009_unchanged':True,'probe32_unchanged':True}))

if __name__=='__main__':main()
