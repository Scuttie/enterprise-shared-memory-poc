"""Freeze one declared exact-task recovery batch before every actual solver."""
import time
import xml.etree.ElementTree as ET

central=Path('/home/trimem-runner/skhynix-codex-010')
development=Path('/home/trimem-runner/skhynix-codex-008')
previous=Path('/home/trimem-runner/skhynix-codex-007')
transfer=Path('/home/trimem-runner/skhynix-codex-009')
win=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
temp=Path('/mnt/c/Users/jewon/AppData/Local/Temp')
sys.path[:0]=[str(win/'scripts'),str(win/'src')]
import trimem_skhynix_codex_learning as learning
from trimem_skhynix_codex_diagnostic_bank import freeze_diagnostic_bank, EXACT_TASK_DIAGNOSTIC_ROUTE

def sha(raw):return hashlib.sha256(raw).hexdigest()
assert EXACT_TASK_DIAGNOSTIC_ROUTE=='EXACT_TASK_DIAGNOSTIC_ROUTE'
assert not central.exists() and not central.is_symlink(), 'REFUSE_EXISTING_EXPERIMENT'
for prior in [previous,development,transfer]:
 assert json.loads((prior/'audit.json').read_text())['status']=='PASS_FINAL'
validation=temp/'native010_exact_task_validation.xml'
receipt=temp/'native010_exact_task_validation.json'
xml=ET.fromstring(validation.read_bytes());evidence=json.loads(receipt.read_text())
assert evidence['status']=='PASS' and evidence['tests']==len(list(xml.iter('testcase')))>0
assert not any(list(xml.iter(k)) for k in ['failure','error','skipped'])
assert evidence['xml_sha256']==sha(validation.read_bytes())
assert all(sha((win/relative).read_bytes())==digest for relative,digest in evidence['source_sha256'].items())
production=['src/enterprise_memory/trimem/skill_runtime.py','scripts/trimem_skhynix_codex_diagnostic_bank.py','scripts/trimem_skhynix_codex_memory.py']
assert set(production)<=set(evidence['source_sha256'])
old_contract=json.loads((development/'launch-contract.json').read_text())
old_freeze=json.loads((development/'source-freeze.json').read_text())
assert sha((development/'source-freeze.json').read_bytes())==old_contract['source_freeze_sha256']
old_bank_raw=(development/'diagnostic-bank.json').read_bytes();old_bank=json.loads(old_bank_raw)
assert sha(old_bank_raw)==old_contract['diagnostic_bank_sha256']
source_spec_raw=(development/'diagnostic-source-spec.json').read_bytes();source_spec=json.loads(source_spec_raw)
sources=source_spec['sources'];evaluation=source_spec['evaluation_tasks']
assert sources==old_bank['source_specs'] and len(sources)==len(evaluation)==2
assert source_spec['scenario']==old_bank['scenario']=='KNOWN_FAILURE_RECOVERY'
assert [(s['run_root'],s['cell']) for s in sources]==[(str(previous/'eval-20428/execution'),'A'),(str(previous/'eval-20438/execution'),'A')]
assert all(s['public_probe_evidence']['sha256']=='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a' for s in sources)
for relative in ['scripts/trimem_skhynix_codex_learning.py','scripts/trimem_skhynix_codex.py']:
 assert sha((win/relative).read_bytes())==old_freeze['sha256'][relative]
assert sha((development/'solver_prompt_template.txt').read_bytes())=='745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05'
assert (development/'supplemental-manifest.json').read_bytes()==(win/'configs/skhynix_v1/codex_005_manifest.json').read_bytes()

central.mkdir()
def save(name,value):
 with (central/name).open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n')
def copy(source,name):
 raw=source.read_bytes()
 with (central/name).open('xb') as stream:stream.write(raw)
 return sha(raw)

manifest_sha=copy(development/'supplemental-manifest.json','supplemental-manifest.json')
prompt_sha=copy(development/'solver_prompt_template.txt','solver_prompt_template.txt')
save('evaluation-task-descriptors.json',evaluation)
copy(development/'diagnostic-source-spec.json','native008-frozen-diagnostic-source-spec.json')
probe_sha=copy(development/'public-probe-results.json','public-probe-results.json')
assert manifest_sha=='57f369ee641b923ec551698fb52f043e7cf8569e4872f0f691883f47d399f6b9'
assert probe_sha=='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
save('diagnostic-source-spec.json',{'sources':sources,'evaluation_tasks':evaluation,'scenario':'KNOWN_FAILURE_RECOVERY','retrieval_text_policy':EXACT_TASK_DIAGNOSTIC_ROUTE})
bank=freeze_diagnostic_bank(central/'diagnostic-bank.json',sources,evaluation,scenario='KNOWN_FAILURE_RECOVERY',retrieval_text_policy=EXACT_TASK_DIAGNOSTIC_ROUTE)
frozen_bank=json.loads((central/'diagnostic-bank.json').read_text())
assert frozen_bank['source_specs']==sources
assert {r['source']['task_id']:r['content'] for r in frozen_bank['records']}=={r['source']['task_id']:r['content'] for r in old_bank['records']}
assert frozen_bank['gate_b']['verified_skill_count']==0
assert frozen_bank['source_selection_uses_evaluation_outcomes'] is True
source_paths=sorted([*win.glob('src/enterprise_memory/**/*.py'),*win.glob('scripts/*.py'),*win.glob('configs/skhynix_v1/*manifest.json')])
source_hashes={}
for path in source_paths:
 assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(win.resolve())
 source_hashes[path.relative_to(win).as_posix()]=sha(path.read_bytes())
save('source-freeze.json',{'schema':'skhynix/native010-source-freeze/1.0','head':HEAD,'sha256':source_hashes,'source_files':len(source_hashes),'frozen_before_all_new_solver_calls':True})
copy(validation,'validation.xml');copy(receipt,'validation-evidence.json')
old_validation_sha=copy(development/'validation.xml','native008-diagnostic-validation.xml')
save('diagnostic-source-continuity.json',{'source_native008_spec_sha256':sha(source_spec_raw),'source_native008_bank_sha256':sha(old_bank_raw),
 'sources_canonical_sha256':sha(learning.canonical(sources)),'exact_source_specs_reused':True,'exact_content_bytes_reused':True,'probe_sha256':probe_sha,
 'native008_outputs_used_for_knowledge_content':False,'prior_public_retrieval_used_for_routing_design':True,'source_run':'native007',
 'source_cells':{'eval-20428':'A','eval-20438':'A'},'gate_b_verified_skills':0})
save('retrieval-policy-development.json',{'policy':EXACT_TASK_DIAGNOSTIC_ROUTE,'scope':'KNOWN_FAILURE_RECOVERY only; exact task/repository/base/public instruction and bound knowledge id',
 'routing':'Exact same-task historical diagnostic record is delivered without lexical eligibility; measured lexical score and full original provenance remain unchanged.',
 'development_source':'Completed native008 recovery exposure and native009 transfer coverage public records; no new native010 outcomes observed.',
 'native008_C_cells_with_memory':2,'native008_C_total_cells':4,'native009_C_cells_with_memory':0,'native009_C_total_cells':4,
 'lessons_changed':False,'prompt_changed':False,'budgets_changed':False,'production_default_changed':False,'separate_transfer_effect_not_tested':True,
 'hypothesis':'Improve exposure consistency and test whether the same public failure lessons change recovery outcomes in new independent sessions.'})
names=['recovery-20428-r1','recovery-20428-r2','recovery-20438-r1','recovery-20438-r2']
contract={'schema':'skhynix/native010-launch-contract/1.0','scenario':'KNOWN_FAILURE_RECOVERY',
 'requested_model':'gpt-6-astra','fork_turns':'none','reasoning_effort':'INHERITED_PARENT_UNCHANGED','evaluation_template_sha256':prompt_sha,
 'manifest_sha256':manifest_sha,'source_freeze_sha256':sha((central/'source-freeze.json').read_bytes()),'diagnostic_bank_sha256':sha((central/'diagnostic-bank.json').read_bytes()),
 'diagnostic_source_continuity_sha256':sha((central/'diagnostic-source-continuity.json').read_bytes()),'source_specs_canonical_sha256':sha(learning.canonical(sources)),
 'public_probe_sha256':probe_sha,'validation_sha256':sha(validation.read_bytes()),'validation_tests':evidence['tests'],'validation_evidence_sha256':sha(receipt.read_bytes()),
 'native008_diagnostic_validation_sha256':old_validation_sha,'retrieval_policy_development_sha256':sha((central/'retrieval-policy-development.json').read_bytes()),
 'retrieval_text_policy':EXACT_TASK_DIAGNOSTIC_ROUTE,
 'cohort_scope':'Both known native007/native008 failure tasks, each twice per arm. Same-task historical diagnostic recovery chosen using prior outcomes, not unseen transfer or a confirmatory global solve rate.',
 'memory_type':'Exactly unchanged native008 public analyst diagnostic content and failed native007 A episodes. Gate A failed sources=2; Gate B=0; KG relations=0.',
 'native008_outputs_used_for_knowledge_content':False,'prior_public_retrieval_used_for_routing_design':True,
 'arms':{'A':'NO_MEMORY','C':'SKHYNIX_WITH_PUBLIC_DIAGNOSTIC_KNOWLEDGE'},
 'unused_arm':'B is prepared only; never launched, graded or counted. Its existing failed/same-target safe-pool rejection is unchanged.',
 'names':names,'evaluation_instances':[d['task_id'] for d in evaluation],'replicates_per_task_arm':2,'planned_evaluation_cells':8,
 'launch_order':dict(zip(names,[['A','C'],['C','A'],['C','A'],['A','C']])),
 'concurrency':'At most two fresh independent solvers, one matched task-replicate pair at a time.',
 'outcome_policy':'All eight fixed cells retained, one submission and official grade each. No outcome-based retries, prompt changes, extra guidance, replacements, exclusions or memory updates.',
 'primary_metric':'Official resolved C minus A over four matched task-replicate observations. Also publish both task-specific repetitions; these are two distinct issues, not four.',
 'limits':{'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000},'expected_actual_C_injections_per_cell':1,
 'frozen_at_unix_seconds':time.time(),'separate_model_api_calls':0,'codex_tokens_and_cost':None,'solver_model_calls_so_far':0,'grader_calls_so_far':0,'root_cross_cell_feedback':False}
save('launch-contract.json',contract);save('attestations.json',[])
print(json.dumps({'status':'FROZEN_BEFORE_EIGHT_RECOVERY_SOLVERS','bank':bank,'contract_sha256':sha((central/'launch-contract.json').read_bytes()),'source_files':len(source_hashes),'unchanged_native008_content':True}))
