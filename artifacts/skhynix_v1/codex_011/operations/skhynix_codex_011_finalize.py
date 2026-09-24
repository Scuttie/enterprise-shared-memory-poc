"""Native011 final read-only validation, followed by finite public collection.
Run ONLY after twelve official grades and root authorization. No solver/grader calls.
"""
from pathlib import Path,PurePosixPath
from collections import Counter
import hashlib,json,re,sys,time
import xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
ROOT=Path('/home/trimem-runner/skhynix-codex-011')
WIN=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
TEMP=Path('/mnt/c/Users/jewon/AppData/Local/Temp')
RUNTIME=Path('/home/trimem-runner/native011-dataset-preparation')
DEST=WIN/'artifacts/skhynix_v1/codex_011'
NAMES=['transfer-'+str(n)+'-r1' for n in (13615,15875,18698,19495)]
ARMS={'A':'NO_MEMORY','B':'DOMAIN_MISMATCHED_LENGTH_MATCHED_LESSON','C':'PREDECLARED_RELEVANT_LESSON'}
IDS={'swebench_verified--sympy__sympy-'+str(n) for n in (13615,15875,18698,19495)}
SOURCE_IDS={'swebench_verified--sympy__sympy-'+str(n) for n in (20428,20438)}
PINNED={'launch-contract.json':'6ced64e45ae3cbeb4bee8734882feceba0c2642a3c2430ef5027f095234be645',
 'source-freeze.json':'ff459097faeda8fd0f700693a119f5506ef0f266f518412f17f874d728dc8cfc',
 'controlled-lessons.json':'05be0725684cc7ab03e852c4b288fee3a6ccf38359d28e5f471d46dd4daadba4',
 'preflight.json':'dcee2829f77ea3dfa3ebfccdc8f1c993df4f6a962c9d5a12c0512e5ea1c8388d',
 'batch-plan.json':'77c3fe346add1a291984c7e2d698e73e01b32b316750a88fa01adcc720dba94b'}
PRIOR={7:(208,'2cfe8ec11d79ca10f1025eedcc6e08ec64576701434ad24995645574801d132f'),
 8:(165,'36bc6ab2576ad248fd79165481159efd4d08ab848a4ae8ada5d8f7df6055b7ac'),
 9:(168,'5ffa28e73e65ee6fb8441a168fb8a6404deacff7bba8c6483054f64963fb3c7c'),
 10:(167,'8ffeb8b7f5cbdf70558c26240da85ad41933bfaab7d54bde786449439c701c8a')}
COUNT=0;ANCHORS={};PUBLIC={}
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(name,condition):
 global COUNT
 if not condition:raise AssertionError(name)
 COUNT+=1
def raw(path):
 path=Path(path)
 check('existing unlinked bounded input '+str(path),path.is_absolute() and path.is_file() and path.stat().st_size<64*1024*1024
  and not any(parent.is_symlink() for parent in (path,*path.parents)))
 value=path.read_bytes();digest=sha(value)
 check('input remains byte-identical '+str(path),ANCHORS.get(str(path),digest)==digest);ANCHORS[str(path)]=digest
 return value
def read(path):return json.loads(raw(path))
def digest(path):return sha(raw(path))
def agent(value):return value if value.startswith('/') else '/root/'+value
def include(label,path):
 name=PurePosixPath(label)
 check('finite contained unique publication label',isinstance(label,str) and name.as_posix()==label and not name.is_absolute()
  and '..' not in name.parts and label not in PUBLIC)
 check('never publish private grading or checkpoint payload',not any(word in label for word in
  ('grader-private','grader-pending','official-grader','memory-private','checkpoint','gate-a-private')))
 value=raw(path);PUBLIC[label]={'raw':value,'source':str(path),'sha256':sha(value),'bytes':len(value)}
def verify_prior(seal):
 expected={};summary={}
 for number,(count,anchor) in PRIOR.items():
  root=WIN/f'artifacts/skhynix_v1/codex_{number:03}';path=root/'public-artifact-manifest.json'
  check('prior manifest pinned',digest(path)==anchor);manifest=read(path);expected[str(path)]=anchor
  check('prior exact public inventory',manifest['file_count']==len(manifest['files'])==count and
   {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}=={r['path'] for r in manifest['files']}|{'public-artifact-manifest.json'})
  for row in manifest['files']:
   for path in (root/row['path'],Path(row['source'])):
    value=raw(path);check('prior original and copy bytes retained',sha(value)==row['sha256'] and len(value)==row['bytes'])
    expected[str(path)]=row['sha256']
  summary[str(number)]={'public_records':count,'manifest_sha256':anchor,'original_and_public_unchanged':True}
 check('previous evidence seal covers exactly every original/copy map',seal['schema']=='skhynix/native011-prior-preservation/1.0' and seal['files']==expected)
 return summary

def main():
 check('Linux manager and new final destination',sys.platform=='linux' and ROOT.is_dir() and not DEST.exists()
  and not any((ROOT/name).exists() for name in ('audit.json','batch-report.json')))
 for name in NAMES:
  for cell in ARMS:check('all twelve grades required before final inspection',(ROOT/name/'execution/cells'/cell/'public-result.json').is_file())
 for name,value in PINNED.items():check('prelaunch immutable raw anchor '+name,re.fullmatch(r'[0-9a-f]{64}',value) and digest(ROOT/name)==value)
 contract=read(ROOT/'launch-contract.json');freeze=read(ROOT/'source-freeze.json');bank_raw=read(ROOT/'controlled-lessons.json')
 enrollment=read(ROOT/'supplemental-manifest.json');preflight=read(ROOT/'preflight.json');batch=read(ROOT/'batch-plan.json')
 check('fixed controlled experiment scope',contract['schema']=='skhynix/native011-launch-contract/1.0'
  and contract['scientific_role']=='CONTROLLED_CONTENT_TRANSFER' and contract['scenario']=='RETROSPECTIVE_DISJOINT_TRANSFER'
  and contract['names']==NAMES and contract['arms']==ARMS and set(contract['evaluation_instances'])==IDS
  and set(contract['source_instances'])==SOURCE_IDS and not IDS.intersection(SOURCE_IDS)
  and contract['planned_evaluation_cells']==12 and contract['replicates_per_task_arm']==1
  and contract['requested_model']=='gpt-6-astra' and contract['fork_turns']=='none'
  and contract['reasoning_effort']=='INHERITED_PARENT_UNCHANGED'
  and contract['solver_model_calls_so_far']==contract['grader_calls_so_far']==contract['separate_model_api_calls']==0
  and contract['codex_tokens_and_cost'] is None)
 check('frozen budget and matched-triple launch order',contract['limits']=={'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000}
  and contract['launch_order']==dict(zip(NAMES,[['A','B','C'],['B','C','A'],['C','A','B'],['A','C','B']])))
 bindings={'supplemental-manifest.json':'manifest_sha256','source-freeze.json':'source_freeze_sha256',
  'controlled-lessons.json':'controlled_lessons_sha256','source-lessons.json':'source_lessons_sha256',
  'solver_prompt_template.txt':'evaluation_template_sha256','public-candidate-selection.json':'public_candidates_sha256',
  'previous-evidence-seal.json':'previous_evidence_seal_sha256','lesson-derivation.md':'lesson_derivation_sha256'}
 for name,key in bindings.items():check('contract-bound root evidence '+name,digest(ROOT/name)==contract[key])
 check('common source-only prose and unchanged prompt',contract['source_lessons_sha256']=='f4c1e9a529732e268d759f9d62cdc5337b2edb1ff679c4ad84bc78a27729f764'
  and contract['evaluation_template_sha256']=='745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05'
  and contract['lesson_utf8_bytes_each']==1670 and sorted(contract['lesson_word_counts'])==[231,240])
 check('explicit retrospective public cohort',enrollment['schema']=='skhynix/native-controlled-transfer-manifest/1.0'
  and enrollment['status']=='FROZEN' and {row['target_id'] for row in enrollment['targets']}==IDS
  and enrollment['chronology_claim']==contract['chronology_claim']=='RETROSPECTIVE_DISJOINT_TASKS_NO_CHRONOLOGICAL_DEPLOYMENT_CLAIM'
  and enrollment['solver_model_calls_at_selection']==enrollment['new_target_grader_runs_at_selection']==0)
 check('exact source freeze declaration',freeze['schema']=='skhynix/native011-source-freeze/1.0'
  and freeze['head']=='d4fd304339687b42c645ae84872a72eddddcda97' and freeze['source_files']==len(freeze['sha256'])
  and freeze['source_files']>0 and freeze['frozen_before_all_new_solver_calls'] is True)
 for relative,value in freeze['sha256'].items():
  rel=PurePosixPath(relative);check('safe canonical frozen path',rel.as_posix()==relative and not rel.is_absolute()
   and '..' not in rel.parts and '\\' not in relative and re.fullmatch(r'[0-9a-f]{64}',value))
 validation={}
 for label,spec in contract['validation'].items():
  check('known validation category',label in ('dataset','controlled'))
  receipt=read(ROOT/(label+'-validation.json'));xml=ET.fromstring(raw(ROOT/(label+'-validation.xml')))
  check('all public validation cases passed',receipt['status']=='PASS' and receipt['tests']==spec['tests']==len(list(xml.iter('testcase')))>0
   and not any(list(xml.iter(tag)) for tag in ('failure','error','skipped')) and digest(ROOT/(label+'-validation.xml'))==spec['xml_sha256']==receipt['xml_sha256']
   and digest(ROOT/(label+'-validation.json'))==spec['receipt_sha256'])
  for relative,value in receipt['source_sha256'].items():
   if relative in freeze['sha256']:check('validated runtime source frozen',freeze['sha256'][relative]==value)
   else:check('validation-only public test source remains exact',relative.startswith('tests/unit/test_') and relative.endswith('.py')
    and '..' not in PurePosixPath(relative).parts and digest(WIN/relative)==value)
  validation[label]=spec['tests']
 previous=verify_prior(read(ROOT/'previous-evidence-seal.json'))
 check('synthetic preflight protects actual initial state',preflight['schema']=='skhynix/native011-preflight/1.0' and preflight['status']=='PASS'
  and preflight['actual_states_before']==preflight['actual_states_after'] and preflight['actual_solver_actions']==preflight['official_grades']==0
  and set(preflight['actual_states_before'])=={name+'-'+cell for name in NAMES for cell in ARMS})
 for state in preflight['actual_states_before'].values():check('zero actions in every preflight state',state['actions']==0 and state['started_at'] is None and state['status']=='OPEN')
 check('exact twelve synthetic tests',len(preflight['synthetic_results'])==12
  and {(r['name'],r['cell']) for r in preflight['synthetic_results']}=={(name,cell) for name in NAMES for cell in ARMS})
 for row in preflight['synthetic_results']:
  check('synthetic initial delivery separate from actual outcomes',row['initial_injections']==int(row['cell']!='A')
   and row['initial_bytes']==(1670 if row['cell']!='A' else 0) and row['repeat_delivery']==0 and row['enforced_initial_recall'] is True
   and row['event_derived_restore']=='PASS')
 check('batch plan joins all frozen prerequisites',batch['schema']=='skhynix/native011-batch-plan/1.0'
  and batch['contract_sha256']==preflight['contract_sha256']==digest(ROOT/'launch-contract.json')
  and preflight['batch_plan_sha256']==digest(ROOT/'batch-plan.json') and preflight['batch']==batch['entries']
  and batch['actual_solver_actions_at_freeze']==batch['official_grades_at_freeze']==0 and batch['planned_cells']==12
  and len(batch['entries'])==4 and {r['name'] for r in batch['entries']}==set(NAMES))
 entries={r['name']:r for r in batch['entries']};source=ROOT/NAMES[0]/'source'
 for relative,value in freeze['sha256'].items():check('frozen first source before imports',digest(source/relative)==value)
 sys.path[:0]=[str(source/'scripts'),str(source/'src')]
 import trimem_skhynix_codex as broker
 import trimem_skhynix_codex_batch as batch_module
 import trimem_skhynix_codex_controlled_lessons as controlled
 from enterprise_memory.trimem.agent_runtime import CANONICAL_FAILED_CELL_NOOP
 broker.block_model_client()
 source_lessons=controlled.load_source_lessons(bank_raw['lessons_file'])
 check('source failure provenance and byte matching remain explicit',len(source_lessons['lessons'])==2
  and {r['source_task_id'] for r in source_lessons['lessons']}==SOURCE_IDS and source_lessons['gate_b_count']==0
  and source_lessons['manual_analyst_diagnosis'] is True and source_lessons['verified_skill'] is False
  and all(r['lesson_utf8_bytes']==1670==len(r['lesson_text'].encode()) and r['lesson_sha256']==sha(r['lesson_text'].encode()) for r in source_lessons['lessons']))
 attestations=read(ROOT/'attestations.json');expected={(name,cell) for name in NAMES for cell in ARMS}
 check('twelve fresh complete self-attestations',len(attestations)==12 and {(r['run'],r['cell']) for r in attestations}==expected
  and len({agent(r['agent']) for r in attestations})==12)
 check('exact launch receipt inventory',{p.name for p in (ROOT/'solver-launches').glob('*.json')}=={name+'-'+cell+'.json' for name,cell in expected})
 attests={(r['run'],r['cell']):r for r in attestations};rows=[];snapshots={};plans={};launches={};agents=set();intervals=[];triples={}
 targets={r['target_id']:r for r in enrollment['targets']};images={r['instance_id']:r for r in enrollment['images']}
 strengths={r['instance_id']:r for r in enrollment['selection']['targets']};template=raw(ROOT/'solver_prompt_template.txt')
 for name in NAMES:
  base=ROOT/name;run=base/'execution';snapshot=read(base/'source-snapshot.json')
  check('copied pipeline matches exact source freeze',snapshot['schema']=='skhynix/native011-operational-source-snapshot/1.0'
   and snapshot['source']==str(base/'source') and snapshot['copied_from']==str(WIN)
   and snapshot['source_freeze_sha256']==contract['source_freeze_sha256'] and snapshot['copied_file_sha256']==freeze['sha256'])
  for relative,value in freeze['sha256'].items():check('each pipeline source retains frozen bytes',digest(base/'source'/relative)==value)
  plan=broker.load_plan(run);plans[name]=plan;entry=entries[name];target=plan['public_task']['task_id'];task=broker.task_from_plan(plan)
  check('plan identity and exact batch binding',target=='swebench_verified--sympy__sympy-'+name.split('-')[1]
   and entry['target_id']==target and entry['run_root']==str(run) and entry['plan_sha256']==sha(canonical(plan))
   and entry['cells']==['A','B','C'] and raw(run/'plan.sha256').decode().strip()==sha(canonical(plan))
   and plan['experiment_id']=='skhynix-native-codex-011-'+name and plan['solver_user_id']=='native-codex-011-'+name
   and plan['cells']==controlled.BROKER_ARMS and plan['experimental_arms']==controlled.LABELS
   and plan['scientific_role']==controlled.ROLE and plan['requested_solver_model']=='gpt-6-astra'
   and plan['frozen_memory_bank'] is plan['procedure_declaration'] is None and plan['limits']==broker.LIMITS
   and {k:v for k,v in plan['source_hashes'].items() if k.endswith('.py')}=={k:v for k,v in freeze['sha256'].items() if k.endswith('.py')})
  check('plan frozen lesson and dataset binding',plan['controlled_lesson_manifest']=={'path':str(ROOT/'controlled-lessons.json'),'sha256':contract['controlled_lessons_sha256']}
   and plan['supplemental_manifest']=={'path':str(ROOT/'supplemental-manifest.json'),'sha256':contract['manifest_sha256']})
  bank=controlled.load_controlled_manifest(ROOT/'controlled-lessons.json',contract['controlled_lessons_sha256'],task)
  family=strengths[targets[target]['instance_id']]['family'];relevant='canonical_polynomial_zero' if family=='polynomial' else 'extensional_set_relations'
  check('predeclared relevant and domain-mismatched assignments',bank.lesson_for('C')['lesson_id']==relevant and bank.lesson_for('B')['lesson_id']!=relevant
   and bank.lesson_for('B')['family']!=bank.lesson_for('C')['family'])
  snapshots[name]={'files':len(freeze['sha256']),'snapshot_sha256':digest(base/'source-snapshot.json'),'plan_sha256':sha(canonical(plan))};triple=[]
  for cell in ARMS:
   root=run/'cells'/cell;launch=read(ROOT/'solver-launches'/(name+'-'+cell+'.json'));launches[name,cell]=launch
   prompt=template.decode().replace('\r\n','\n').replace('\r','\n').replace('{{BASE}}',str(base)).replace('{{CELL}}',cell).encode()
   check('exact fresh solver launch and prompt',launch['schema']=='skhynix/native011-solver-launch/1.0'
    and launch['name']==name and launch['cell']==cell and launch['requested_model']=='gpt-6-astra' and launch['fork_turns']=='none'
    and launch['reasoning_effort']=='INHERITED_PARENT_UNCHANGED' and launch['root_cross_cell_feedback'] is False
    and launch['separate_model_api_calls']==0 and launch['template_sha256']==sha(template) and launch['filled_prompt_sha256']==sha(prompt)
    and raw(ROOT/'solver-launches'/(name+'-'+cell+'-prompt.txt'))==prompt and agent(launch['agent']) not in agents)
   agents.add(agent(launch['agent']));events,tail=broker.audit_events(root);restored=controlled.restore_delivery(plan,run,cell,events,bank)
   row=batch_module.verify_result_receipt(plan,run,cell);submission=read(root/'submission.json');state=read(root/'state.json');patch=raw(root/'submission.diff')
   check('official completed result and exact grader patch',row['official'] is row['agent_completed'] is True and type(row['resolved']) is bool
    and row['grader_status']=='success' and row['patch_sha256']==sha(patch)==submission['patch_sha256']
    and row['grader_patch_sha256']==sha(patch if patch else CANONICAL_FAILED_CELL_NOOP.encode())
    and row['separate_model_api_calls']==0 and row['codex_tokens_and_cost'] is None)
   check('submission and protocol attestation agree',attests[name,cell]['patch_sha256']==row['patch_sha256']
    and agent(attests[name,cell]['agent'])==agent(launch['agent'])
    and attests[name,cell]['only_assigned_broker'] is attests[name,cell]['no_external_access'] is attests[name,cell]['no_subagents'] is True)
   check('one submit last, complete action accounting',len(events)==row['actions']==state['actions']<=120 and state['status']=='SUBMITTED'
    and sum(e['request'].get('op')=='submit' and e['result'].get('ok') is True for e in events)==1
    and events[-1]['request']['op']=='submit' and events[-1]['result']['ok'] is True
    and all(e['result']['budget']['actions_remaining']==120-e['sequence'] for e in events))
   check('all conditions frozen before first action',contract['frozen_at_unix_seconds']<state['started_at']
    and all((ROOT/f).stat().st_mtime<state['started_at'] for f in (*PINNED,'source-lessons.json','previous-evidence-seal.json'))
    and (ROOT/'batch-plan.json').stat().st_mtime<launch['recorded_at_unix_seconds'])
   check('wall duration and bounds',0<=row['wall_seconds']<=1200 and abs(row['wall_seconds']-(submission['submitted_at']-submission['started_at']))<0.001)
   calls=[e for e in events if e['request'].get('op')=='recall' and e['result'].get('ok') is True]
   injections=[i for e in calls for i in e['result']['result']['injections']];lesson=bank.lesson_for(cell)
   check('one forced first delivery, no repeated text',len(calls)>=1 and restored['successful_recalls']==len(calls)==row['memory_queries']
    and len(injections)==row['memory_injections']==int(cell!='A') and row['memory_bytes']==(1670 if lesson else 0)
    and len(calls[0]['result']['result']['injections'])==int(cell!='A')
    and all(not e['result']['result']['injections'] for e in calls[1:]))
   if lesson:
    item=injections[0];check('actual assigned text, provenance and length',item['exact_text']==lesson['lesson_text']
     and item['kind']=='CONTROLLED_LESSON' and item['memory_id']=='controlled-lesson:'+lesson['lesson_sha256']
     and item['sha256']==lesson['lesson_sha256']==sha(item['exact_text'].encode()) and item['byte_count']==1670
     and item['source_task_id']==lesson['source_task_id'] and item['source_task_id'] not in IDS and item['verified_skill'] is False
     and item['confidence']==0.0 and restored['delivery_sequence']==calls[0]['sequence'])
   else:check('A restored delivery empty',restored['delivery'] is None and restored['delivery_sequence'] is None)
   check('all arms share target public runtime',read(root/'workspace.json')['image']==images[targets[target]['instance_id']]['image'])
   triple.append((submission['started_at'],submission['submitted_at']));intervals.extend(((submission['started_at'],1),(submission['submitted_at'],-1)))
   rows.append({'name':name,'target_id':target,'cell':cell,'arm':ARMS[cell],**{k:row[k] for k in
    ('resolved','actions','tool_errors','wall_seconds','memory_queries','memory_injections','memory_bytes','patch_sha256','agent_completed')},
    'public_result_sha256':digest(root/'public-result.json'),'tool_event_tail_sha256':tail,
    'lesson_id':lesson['lesson_id'] if lesson else None,'lesson_sha256':lesson['lesson_sha256'] if lesson else None,
    'source_task_id':lesson['source_task_id'] if lesson else None,'declared_family':family,'match_rationale':strengths[targets[target]['instance_id']]['rationale']})
  order=contract['launch_order'][name];check('actual triple launch order retained',all(launches[name,a]['recorded_at_unix_seconds']<launches[name,b]['recorded_at_unix_seconds'] for a,b in zip(order,order[1:])))
  triples[name]=(min(a for a,b in triple),max(b for a,b in triple))
 for before,after in zip(NAMES,NAMES[1:]):check('one task triple at a time',triples[before][1]<=triples[after][0])
 active=peak=0
 for stamp,delta in sorted(intervals):active+=delta;peak=max(peak,active)
 check('maximum three active solver intervals',active==0 and peak<=3)
 comparison={}
 for cell in ARMS:
  selected=[r for r in rows if r['cell']==cell];comparison[cell]={'arm':ARMS[cell],'n':4,'resolved':sum(r['resolved'] for r in selected),
   'solve_rate':sum(r['resolved'] for r in selected)/4,**{k:sum(r[k] for r in selected) for k in ('actions','tool_errors','wall_seconds','memory_injections','memory_bytes')},
   'cells_with_memory_exposure':sum(r['memory_injections']>0 for r in selected),'max_requests':max(r['actions'] for r in selected)}
 paired=[{'name':name,'target_id':entries[name]['target_id'],**{cell:next(r['resolved'] for r in rows if r['name']==name and r['cell']==cell) for cell in ARMS}} for name in NAMES]
 report={'schema':'skhynix/native011-controlled-transfer-report/1.0','status':'COMPLETE','planned_cells':12,'completed_cells':12,
  'scientific_role':'CONTROLLED_CONTENT_TRANSFER','scenario':'RETROSPECTIVE_DISJOINT_TRANSFER','distinct_tasks':4,
  'comparison':comparison,'primary_delta_percentage_points':100*(comparison['C']['solve_rate']-comparison['A']['solve_rate']),
  'specificity_delta_percentage_points':100*(comparison['C']['solve_rate']-comparison['B']['solve_rate']),
  'paired_outcomes':paired,'cells':rows,'actual_fresh_sessions':12,'all_agent_completed':True,'peak_active_broker_intervals':peak,
  'verified_skill_count':0,'separate_model_api_calls':0,'codex_tokens_and_cost':None,
  'limitations':[contract[k] for k in ('control_limitation','length_matching_scope','memory_type','chronology_claim','selection_policy')]+[
   'Four public-issue-selected tasks and one fresh session per arm/task; no globally unseen, randomized, or confirmatory population claim.',
   'Relevant matching is a predeclared hypothesis with different strengths; 15875 changes subsystem, 18698 is broader normalization,19495 involves bound variables not explicitly taught.',
   'Forced content delivery isolates this content comparison; it does not evaluate end-to-end retrieval, automatic skill promotion or the full PDF architecture.',
   'Requested native model/context and self-attested host restrictions are protocol metadata, not independent backend/OS attestation.']}
 for name in (*bindings,'evaluation-task-descriptors.json','launch-contract.json','attestations.json','preflight.json','batch-plan.json','operations-note.json'):
  include(name,ROOT/name)
 for label in contract['validation']:
  for suffix in ('.json','.xml'):include(label+'-validation'+suffix,ROOT/(label+'-validation'+suffix))
 for name in NAMES:
  base=ROOT/name;run=base/'execution';plan=plans[name];include(name+'/source-snapshot.json',base/'source-snapshot.json')
  for file in ('plan.json','plan.sha256'):include(name+'/'+file,run/file)
  for cell in ARMS:
   for file in ('state.json','public-task.json','workspace.json','bank-projection.json','tool-events.jsonl','submission.json','submission.diff','public-result.json'):
    include(name+'/cells/'+cell+'/'+file,run/'cells'/cell/file)
   for suffix in ('.json','-prompt.txt'):include('solver-launches/'+name+'-'+cell+suffix,ROOT/'solver-launches'/(name+'-'+cell+suffix))
   for file in ('solver-sandbox-preflight.json','checkout-preflight.json'):
    rel='environment/cells/'+plan['cells'][cell]+'/'+plan['public_task']['task_id']+'/control/'+file;include(name+'/'+rel,run/rel)
  for file in ('local-environment-preflight.json','official-harness-loader-preflight.json'):include(name+'/environment/control/'+file,run/'environment/control'/file)
 for suffix in ('init','manage','record','preflight','finalize'):include('operations/skhynix_codex_011_'+suffix+'.py',TEMP/('skhynix_codex_011_'+suffix+'.py'))
 # Public preparation JSONs only; source archive hashes remain in the manifest.
 check('runtime preparation and completed public probes bound before solvers',
  digest(RUNTIME/'preparation-artifact-manifest.json')==contract['runtime_preparation_manifest_sha256']
  and digest(RUNTIME/'runtime-v2-summary.json')==contract['runtime_summary_sha256'])
 prep=read(RUNTIME/'preparation-artifact-manifest.json')
 for file in ('preparation-artifact-manifest.json','runtime-v2-summary.json','images.json'):
  include('runtime/'+file,RUNTIME/file)
 for record in prep['files']:
  if record['path'].endswith('.json'):
   path=RUNTIME/record['path'];check('public runtime receipt hash retained',digest(path)==record['sha256'])
   label='runtime/'+record['path']
   if label not in PUBLIC:include(label,path)
 failed_init=Path('/home/trimem-runner/native011-initialization-attempt-1');note=read(failed_init/'failure-note.json')
 check('pre-enrollment initialization failure is preserved and predates solvers',digest(failed_init/'failure-note.json')==contract['initialization_failure_note_sha256']
  and note['status']=='PRESERVED_PRE_ENROLLMENT_INITIALIZATION_FAILURE' and note['stage']=='PUBLIC_RUNTIME_RECEIPT_VALIDATION'
  and note['solver_calls']==note['grader_calls']==0 and note['config_created'] is note['manifest_created'] is note['source_freeze_created'] is False
  and len(note['preserved_files_sha256'])==8 and digest(failed_init/'initialization-helper.py')==note['initialization_helper_sha256'])
 for file in ('failure-note.json','initialization-helper.py',*note['preserved_files_sha256']):
  rel=PurePosixPath(file);check('initialization preservation filename bounded',not rel.is_absolute() and '..' not in rel.parts and len(rel.parts)==1)
  if file in note['preserved_files_sha256']:check('initialization original partial bytes preserved',digest(failed_init/file)==note['preserved_files_sha256'][file])
  include('initialization-attempt-1/'+file,failed_init/file)
 for path,value in list(ANCHORS.items()):check('all observed evidence unchanged before publication',sha(Path(path).read_bytes())==value)
 audit={'schema':'skhynix/native011-integrity-audit/1.0','status':'PASS_FINAL','checks_passed':COUNT,'checks_failed':0,'pending':[],
  'planned_cells':12,'completed_cells':12,'fresh_agents':len(agents),'all_agent_completed':True,'source_snapshots':snapshots,
  'previous_public_archives':previous,'previous_public_record_count':708,'validation_tests':validation,
  'event_derived_delivery_restored_for_all_cells':True,'expected_deliveries':{'A':0,'B':4,'C':4},'bytes_each':1670,
  'source_only_provenance_validated':True,'frozen_contract_sha256':digest(ROOT/'launch-contract.json'),
  'preserved_initialization_failure_sha256':contract['initialization_failure_note_sha256'],'initialization_failure_pre_solver':True,
  'finalizer_sha256':digest(TEMP/'skhynix_codex_011_finalize.py'),'first_observed_input_sha256':dict(ANCHORS),
  'solver_calls':0,'grader_calls':0,'container_calls':0,'private_payloads_exported':False,'audit_at_unix_seconds':time.time()}
 for name,value in (('batch-report.json',report),('audit.json',audit)):
  payload=canonical(value)+b'\n'
  with (ROOT/name).open('xb') as stream:stream.write(payload)
  PUBLIC[name]={'raw':payload,'source':str(ROOT/name),'sha256':sha(payload),'bytes':len(payload)}
 DEST.mkdir(parents=True,exist_ok=False);files=[]
 for label,item in sorted(PUBLIC.items()):
  path=DEST/label;check('new public copy remains contained',path.resolve().is_relative_to(DEST.resolve()))
  path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('xb') as stream:stream.write(item['raw'])
  check('copied public bytes exact',sha(path.read_bytes())==item['sha256']);files.append({k:v for k,v in {'path':label,**item}.items() if k!='raw'})
 manifest={'schema':'skhynix/native-public-manifest/1.0','file_count':len(files),'files':files,'manifest_excludes_itself':True,
  'copy_policy':'Finite public controlled-transfer evidence; no private grading/checkpoints, hidden fixtures, raw grader logs or source archives.'}
 manifest_raw=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with (DEST/'public-artifact-manifest.json').open('xb') as stream:stream.write(manifest_raw)
 for item in files:
  for path in (DEST/item['path'],Path(item['source'])):check('final original/public hash and length retained',path.stat().st_size==item['bytes'] and sha(path.read_bytes())==item['sha256'])
 check('final public inventory exact',{p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}=={r['path'] for r in files}|{'public-artifact-manifest.json'})
 print(json.dumps({'status':'PASS_FINAL_AND_PUBLIC_BYTES_VERIFIED','audit_checks_passed':audit['checks_passed'],'completed_cells':12,
  'comparison':comparison,'primary_delta_percentage_points':report['primary_delta_percentage_points'],
  'specificity_delta_percentage_points':report['specificity_delta_percentage_points'],'public_files':len(files),
  'public_bytes':sum(r['bytes'] for r in files),'manifest_sha256':sha(manifest_raw)}))

if __name__=='__main__':main()
