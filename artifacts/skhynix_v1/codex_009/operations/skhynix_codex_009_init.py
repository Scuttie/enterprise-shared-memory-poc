"""DRAFT: executed only when the root starts native009; never run by the preparer."""
import time
import xml.etree.ElementTree as ET

central=Path('/home/trimem-runner/skhynix-codex-009')
previous=Path('/home/trimem-runner/skhynix-codex-007')
development=Path('/home/trimem-runner/skhynix-codex-008')
win=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
sys.path[:0]=[str(win/'scripts'),str(win/'src')]
import trimem_skhynix_native_dataset as dataset
import trimem_skhynix_native_transfer_dataset as transfer
import trimem_skhynix_codex_learning as learning
from trimem_skhynix_codex_diagnostic_bank import freeze_diagnostic_bank

def sha(raw):return hashlib.sha256(raw).hexdigest()

config=win/'configs/skhynix_v1/codex_009_manifest.json'
assert not central.exists() and not central.is_symlink(), 'REFUSE_EXISTING_EXPERIMENT'
assert not config.exists() and not config.is_symlink(), 'REFUSE_EXISTING_NATIVE009_CONFIG'
assert json.loads((previous/'audit.json').read_text())['status']=='PASS_FINAL'
validation=Path('/mnt/c/Users/jewon/AppData/Local/Temp/native009_transfer_dataset_validation_final.xml')
xml=ET.fromstring(validation.read_bytes())
assert len(list(xml.iter('testcase')))==168 and not any(list(xml.iter(k)) for k in ['failure','error','skipped'])
validation_receipt=Path('/mnt/c/Users/jewon/AppData/Local/Temp/native009_transfer_dataset_validation.json')
validation_evidence=json.loads(validation_receipt.read_text())
assert validation_evidence['status']=='PASS' and validation_evidence['tests']==168
assert validation_evidence['xml_sha256']==sha(validation.read_bytes())
assert all(sha((win/relative).read_bytes())==digest for relative,digest in validation_evidence['source_sha256'].items())
drycheck=json.loads(Path('/mnt/c/Users/jewon/AppData/Local/Temp/native009_transfer_real_cache_drycheck.json').read_text())
assert drycheck['status']=='PASS_REAL_CACHE_TRANSFER_BUILD_LOAD_DRYCHECK'

# The knowledge source specs, cohort and common prompt remain unchanged.
# Matching policy is an explicit development change informed by the PUBLIC
# native008 C1 initial recall, which abstained because of metadata dilution.
development_launch=json.loads((development/'launch-contract.json').read_text())
development_source=json.loads((development/'source-freeze.json').read_text())
assert sha((development/'source-freeze.json').read_bytes())==development_launch['source_freeze_sha256']
source_spec_raw=(development/'diagnostic-source-spec.json').read_bytes()
source_spec=json.loads(source_spec_raw)
old_bank_raw=(development/'diagnostic-bank.json').read_bytes()
old_bank=json.loads(old_bank_raw)
assert sha(old_bank_raw)==development_launch['diagnostic_bank_sha256']
assert source_spec['scenario']==old_bank['scenario']=='KNOWN_FAILURE_RECOVERY'
sources=source_spec['sources']
assert sources==old_bank['source_specs'] and len(sources)==2
assert [(s['run_root'],s['cell']) for s in sources]==[
 (str(previous/'eval-20428/execution'),'A'),(str(previous/'eval-20438/execution'),'A')]
assert all(s['public_probe_evidence']['sha256']=='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
           for s in sources)
for relative in ('scripts/trimem_skhynix_codex_learning.py','scripts/trimem_skhynix_codex.py'):
 assert sha((win/relative).read_bytes())==development_source['sha256'][relative], 'TRANSFER_TREATMENT_CODE_CHANGED'
retrieval_validation=Path('/mnt/c/Users/jewon/AppData/Local/Temp/native009_diagnostic_matching_validation.xml')
retrieval_receipt=Path('/mnt/c/Users/jewon/AppData/Local/Temp/native009_diagnostic_matching_validation.json')
retrieval_evidence=json.loads(retrieval_receipt.read_text())
retrieval_xml=ET.fromstring(retrieval_validation.read_bytes())
assert retrieval_evidence['status']=='PASS' and retrieval_evidence['xml_sha256']==sha(retrieval_validation.read_bytes())
assert not any(list(retrieval_xml.iter(k)) for k in ['failure','error','skipped'])
assert all(sha((win/relative).read_bytes())==digest for relative,digest in retrieval_evidence['source_sha256'].items())
assert sha((previous/'solver_prompt_template.txt').read_bytes())=='745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05'
assert (development/'solver_prompt_template.txt').read_bytes()==(previous/'solver_prompt_template.txt').read_bytes()

central.mkdir()

def save(name,value):
 with (central/name).open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n')

def copy(source,name):
 raw=source.read_bytes()
 with (central/name).open('xb') as stream:stream.write(raw)
 return sha(raw)

# Enrollment is written before the source/config freeze. This is the only call
# that creates the actual native009 manifest; the earlier drycheck used /tmp.
manifest=transfer.build_transfer_manifest(cache_root=Path('/opt/trimem-rehearsals/e932-preflight/datasets'),
 history=Path('/home/trimem-runner/skhynix-codex-002/dataset-preparation/sympy-history.git'),
 output_path=central/'supplemental-manifest.json',root=win)
manifest_raw=(central/'supplemental-manifest.json').read_bytes()
manifest_sha=sha(manifest_raw)
assert manifest_sha==drycheck['temporary_manifest_sha256'], 'ACTUAL_MANIFEST_DIFFERS_FROM_PUBLIC_CACHE_DRYCHECK'
with config.open('xb') as stream:stream.write(manifest_raw)
targets,rows,images,loaded=dataset.load_supplemental_rows(central/'supplemental-manifest.json',
 Path('/opt/trimem-rehearsals/e932-preflight/datasets'),expected_sha256=manifest_sha,root=win)
assert manifest==loaded and [t['instance_id'] for t in targets]==list(transfer.TARGET_IDS)
evaluation=[learning._task_descriptor({'task_id':t['target_id'],'repository':t['repository'],
 'commit':t['base_commit'],'instruction_sha256':t['public_instruction_sha256'],'language':t['language']}) for t in targets]
save('evaluation-task-descriptors.json',evaluation)
prompt_sha=copy(previous/'solver_prompt_template.txt','solver_prompt_template.txt')
copy(development/'diagnostic-source-spec.json','native008-frozen-diagnostic-source-spec.json')
probe_sha=copy(development/'public-probe-results.json','public-probe-results.json')
assert probe_sha=='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
save('diagnostic-source-spec.json',{'sources':sources,'evaluation_tasks':evaluation,'scenario':'DISJOINT_TRANSFER','retrieval_text_policy':'DIAGNOSTIC_LESSON_CONTENT'})
bank=freeze_diagnostic_bank(central/'diagnostic-bank.json',sources,evaluation,scenario='DISJOINT_TRANSFER',retrieval_text_policy='DIAGNOSTIC_LESSON_CONTENT')
frozen_bank=json.loads((central/'diagnostic-bank.json').read_text())
assert frozen_bank['source_specs']==sources and frozen_bank['source_target_overlap_task_ids']==[]
assert frozen_bank['gate_b']['verified_skill_count']==0
assert frozen_bank['source_selection_uses_evaluation_outcomes'] is False

source_paths=sorted([*win.glob('src/enterprise_memory/**/*.py'),*win.glob('scripts/*.py'),
                     *win.glob('configs/skhynix_v1/*manifest.json')])
source_hashes={}
for path in source_paths:
 assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(win.resolve())
 source_hashes[str(path.relative_to(win))]=sha(path.read_bytes())
assert source_hashes['configs/skhynix_v1/codex_009_manifest.json']==manifest_sha
save('source-freeze.json',{'schema':'skhynix/native009-source-freeze/1.0',
 'head':'d4fd304339687b42c645ae84872a72eddddcda97','sha256':source_hashes,
 'source_files':len(source_hashes),'frozen_before_all_new_solver_calls':True})
copy(validation,'validation.xml')
copy(validation_receipt,'validation-evidence.json')
copy(retrieval_validation,'retrieval-validation.xml')
copy(retrieval_receipt,'retrieval-validation-evidence.json')
diagnostic_validation_sha=copy(development/'validation.xml','native008-diagnostic-validation.xml')
save('retrieval-policy-development.json',{'policy':'DIAGNOSTIC_LESSON_CONTENT','min_score':0.05,
 'matching_document':'Validated diagnostic title plus analyst_lesson; seeding and ranking use the same document. Full immutable provenance and lesson remain in the delivered wire view.',
 'development_source':'native008 recovery-20428-r1 C public initial recall; no transfer target trajectory or result used',
 'event_sha256':'92f2a8b3a0400153ecc910ef12d92514f82faf3aab841ecc00aebcfdc57d78d0',
 'query_sha256':'515a2781d9209a07676ed8078ae76ca4941029a5c190da06865ae09508341473',
 'known_query_full_record':{'overlap':9,'union':219,'score':9/219},
 'known_query_lesson_only':{'overlap':9,'union':163,'score':9/163},
 'diagnosis':'56 metadata tokens increased denominator without additional query overlap; original initial recall abstained.',
 'native008_frozen_experiment_changed':False,'native009_cohort_source_lessons_prompt_changed':False,
 'general_retrieval_or_solve_rate_improvement_not_yet_established':True})
save('diagnostic-source-continuity.json',{'source_native008_spec_sha256':sha(source_spec_raw),
 'source_native008_bank_sha256':sha(old_bank_raw),'sources_canonical_sha256':sha(learning.canonical(sources)),
 'exact_source_specs_reused':True,'probe_sha256':probe_sha,
 'native008_outputs_used_for_knowledge_content':False,'native008_public_recall_used_for_retrieval_design':True,'source_run':'native007',
 'source_cells':{'eval-20428':'A','eval-20438':'A'},'gate_b_verified_skills':0})
names=['transfer-'+number+'-r1' for number in ['21612','21847','22714','24661']]
contract={'schema':'skhynix/native009-launch-contract/1.0','scenario':'DISJOINT_TRANSFER',
 'requested_model':'gpt-6-astra','fork_turns':'none','reasoning_effort':'INHERITED_PARENT_UNCHANGED',
 'evaluation_template_sha256':prompt_sha,'manifest_sha256':manifest_sha,
 'source_freeze_sha256':sha((central/'source-freeze.json').read_bytes()),
 'diagnostic_bank_sha256':sha((central/'diagnostic-bank.json').read_bytes()),
 'diagnostic_source_continuity_sha256':sha((central/'diagnostic-source-continuity.json').read_bytes()),
 'source_specs_canonical_sha256':sha(learning.canonical(sources)),'public_probe_sha256':probe_sha,
 'validation_sha256':sha(validation.read_bytes()),'validation_tests':len(list(xml.iter('testcase'))),
 'validation_evidence_sha256':sha(validation_receipt.read_bytes()),
 'retrieval_validation_sha256':sha(retrieval_validation.read_bytes()),
 'retrieval_validation_evidence_sha256':sha(retrieval_receipt.read_bytes()),
 'retrieval_policy_development_sha256':sha((central/'retrieval-policy-development.json').read_bytes()),
 'retrieval_text_policy':'DIAGNOSTIC_LESSON_CONTENT',
 'native008_diagnostic_validation_sha256':diagnostic_validation_sha,
 'cohort_scope':manifest['scope_claim'],
 'memory_type':'Same frozen public diagnostic lessons and failed native007 A source episodes used by native008. Analyst interpretation, not a verified successful v3 skill. Gate B=0; KG relations=0.',
 'native008_outputs_used_for_knowledge_content':False,
 'native008_public_recall_used_for_retrieval_design':True,
 'arms':{'A':'NO_MEMORY','C':'SKHYNIX_WITH_PUBLIC_DIAGNOSTIC_KNOWLEDGE'},
 'unused_arm':'B may be prepared by the three-cell broker but is never launched, graded or included in the denominator.',
 'names':names,'evaluation_instances':[d['task_id'] for d in evaluation],
 'replicates_per_task_arm':1,'planned_evaluation_cells':8,
 'launch_order':dict(zip(names,[['A','C'],['C','A'],['A','C'],['C','A']])),
 'concurrency':'At most two fresh independent solvers, one matched task pair at a time.',
 'outcome_policy':'All eight fixed cells retained, one submission and official grade each. No outcome-based retries, memory edits, prompt changes, extra guidance, replacements or exclusions. Freeze before first transfer solver.',
 'primary_metric':'Official resolved C minus A over four disjoint matched issues; report all eight outcomes. Small exploratory transfer sample, not a global solve-rate estimate.',
 'limits':{'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000},
 'frozen_at_unix_seconds':time.time(),'separate_model_api_calls':0,'codex_tokens_and_cost':None,
 'solver_model_calls_so_far':0,'grader_calls_so_far':0,'root_cross_cell_feedback':False}
save('launch-contract.json',contract)
save('attestations.json',[])
print(json.dumps({'status':'FROZEN_BEFORE_EIGHT_TRANSFER_SOLVERS','bank':bank,
 'manifest_sha256':manifest_sha,'contract_sha256':sha((central/'launch-contract.json').read_bytes()),
 'source_files':len(source_hashes),'native008_public_recall_used_for_retrieval_design':True}))
