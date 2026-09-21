central=Path('/home/trimem-runner/skhynix-codex-008')
previous=Path('/home/trimem-runner/skhynix-codex-007')
win=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
import time
import xml.etree.ElementTree as ET
sys.path[:0]=[str(win/'scripts'),str(win/'src')]
from trimem_skhynix_codex_diagnostic_bank import freeze_diagnostic_bank
assert json.loads((previous/'audit.json').read_text())['status']=='PASS_FINAL'
assert not central.exists(), 'REFUSE_EXISTING_EXPERIMENT'
validation=win/'artifacts/skhynix_v1/codex_008_validation.xml'
xml=ET.fromstring(validation.read_bytes())
assert list(xml.iter('testcase')) and not any(list(xml.iter(k)) for k in ['failure','error','skipped'])
central.mkdir()
def save(name,value):
 with (central/name).open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def copy(source,name):
 raw=source.read_bytes()
 with (central/name).open('xb') as f:f.write(raw)
 return hashlib.sha256(raw).hexdigest()
manifest_sha=copy(previous/'supplemental-manifest.json','supplemental-manifest.json')
assert manifest_sha=='57f369ee641b923ec551698fb52f043e7cf8569e4872f0f691883f47d399f6b9'
prompt_sha=copy(previous/'solver_prompt_template.txt','solver_prompt_template.txt')
evaluation=[d for d in json.loads((previous/'evaluation-task-descriptors.json').read_text()) if d['task_id'].rsplit('-',1)[1] in ['20428','20438']]
assert len(evaluation)==2
save('evaluation-task-descriptors.json',evaluation)
probe_sha=copy(Path('/home/trimem-runner/native008-public-failure-diagnostic/public-probe-results.json'),'public-probe-results.json')
assert probe_sha=='41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
lessons={
 '20428':('Canonical polynomial representation after coefficient simplification, multiplication and quotient',
 '''A completed earlier patch fixed the literal public clear_denoms issue and public tests by stripping leading zeros in dup_mul_ground/dmp_mul_ground, yet its official task remained unresolved. Additional independent PUBLIC probes showed five surviving normalization defects; these are not identified hidden assertions or a verified successful repair.
 Dense polynomial zero has canonical shape [] (one variable) and [[]] at recursive level 1. In the EX domain, z=EX((a+1)**2-a**2-2*a-1) may become zero during scalar arithmetic. With scalar EX(2), dup_quo_ground([z], EX(2), EX) and dup_exquo_ground([z], EX(2), EX) still returned [EX(0)] after that multiplication-only patch; recursive dmp counterparts returned [[EX(0)]]. dup_quo_ground([ZZ.one, ZZ.one], ZZ(2), ZZ) returned [0,0]. Expected canonical outputs are [] or [[]]. Multiplication siblings need the same invariant. Relevant public code: sympy/polys/densearith.py ground arithmetic helpers, densebasic.py strip/zero helpers, densetools.py clear_denoms.
 Analyst lesson: trace the invariant across every sibling operation that changes coefficients, both univariate and recursive variants. Inspect domain equality/zero semantics rather than treating expression truthiness as proof. Preserve exact-division errors and ordinary nonzero behavior. Test leading zeros, all-zero and nonzero tails plus downstream Poly.is_zero, representation, degree/terms_gcd/primitive; a rendered expression of zero alone is insufficient. Reproduce and verify these claims in your own checkout; there is no supplied patch and no guarantee of official success.'''),
 '20438':('Extensional set equality, ProductSet finite iteration, Range and proper subset semantics',
 '''A completed earlier patch repaired all literal public ProductSet/FiniteSet examples and relevant public tests, yet its official task remained unresolved. It special-cased the FiniteSet class. Seven independently executed neighboring PUBLIC checks still failed; these are not identified hidden assertions or a verified successful repair.
 Let a=FiniteSet(1,2), b=ProductSet(a,a), c=FiniteSet((1,1),(1,2),(2,1),(2,2)). They are extensionally equal. Both ordinary subset directions should be True and all four proper subset/superset directions should be False. The earlier patch incorrectly returned True for every proper relation: generic methods used structural self != other, which is insufficient for extensional inequality.
 Replacing b with ProductSet(Range(1,3), Range(1,3)) represents the same four values. The earlier FiniteSet-only implementation left b.is_subset(c) as None, Eq(b,c).simplify() raising the public Complement.equals AttributeError, and b.rewrite(FiniteSet) unchanged. ProductSet already exposes is_finite_set and is_iterable; Range is a different concrete finite iterable representation. Relevant public code: sympy/sets/sets.py subset/proper relations and ProductSet; sympy/sets/handlers/comparison.py equality; fancysets.py Range.
 Analyst lesson: implement extensional set behavior using justified capabilities and both operand orders, rather than one concrete class or Python structural inequality. For enumeration require known finite and iterable inputs; do not enumerate infinite or unknown sets. Preserve None/unknown symbolic outcomes and use fuzzy logic where appropriate. Test subset/superset, proper relations, equality simplification, intersection symmetry and explicit finite rewrite for alternate representations, equal/unequal sets and symbolic membership. Reproduce and verify the claims in your own checkout; no supplied patch or guarantee of official success.''')}
sources=[]
for number,(title,lesson) in lessons.items():
 sources.append({'run_root':str(previous/('eval-'+number)/'execution'),'cell':'A','title':title,'lesson_text':lesson,
  'public_probe_evidence':{'path':str(central/'public-probe-results.json'),'sha256':probe_sha}})
save('diagnostic-source-spec.json',{'sources':sources,'evaluation_tasks':evaluation,'scenario':'KNOWN_FAILURE_RECOVERY'})
bank=freeze_diagnostic_bank(central/'diagnostic-bank.json',sources,evaluation,scenario='KNOWN_FAILURE_RECOVERY')
source_paths=sorted([*win.glob('src/enterprise_memory/**/*.py'),*win.glob('scripts/*.py'),*win.glob('configs/skhynix_v1/*manifest.json')])
source_hashes={str(p.relative_to(win)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
save('source-freeze.json',{'schema':'skhynix/native008-source-freeze/1.0','head':'d4fd304339687b42c645ae84872a72eddddcda97','sha256':source_hashes,'source_files':len(source_hashes),'frozen_before_all_new_solver_calls':True})
copy(validation,'validation.xml')
names=['recovery-20428-r1','recovery-20428-r2','recovery-20438-r1','recovery-20438-r2']
contract={'schema':'skhynix/native008-launch-contract/1.0','scenario':'KNOWN_FAILURE_RECOVERY',
 'requested_model':'gpt-6-astra','fork_turns':'none','reasoning_effort':'INHERITED_PARENT_UNCHANGED',
 'evaluation_template_sha256':prompt_sha,'manifest_sha256':manifest_sha,
 'source_freeze_sha256':hashlib.sha256((central/'source-freeze.json').read_bytes()).hexdigest(),
 'diagnostic_bank_sha256':hashlib.sha256((central/'diagnostic-bank.json').read_bytes()).hexdigest(),
 'public_probe_sha256':probe_sha,'validation_sha256':hashlib.sha256(validation.read_bytes()).hexdigest(),
 'validation_tests':len(list(xml.iter('testcase'))),
 'prior_result':{'run':'native007','A':{'solved':4,'total':6},'B':{'solved':4,'total':6},'C':{'solved':4,'total':6},'preserved':True},
 'cohort_scope':'BOTH KNOWN NATIVE007 FAILURE TASKS SELECTED USING PRIOR OUTCOMES. ANALYST-DERIVED MEMORY FROM THE SAME TASKS. DEVELOPMENT RECOVERY, NOT UNSEEN TRANSFER OR A CONFIRMATORY GLOBAL SOLVE RATE.',
 'memory_type':'Human-directed analyst interpretation of bound public failure probes, not an automatically promoted successful skill. Gate A has failed sources; Gate B=0; KG relations=0.',
 'arms':{'A':'NO_MEMORY','C':'SKHYNIX_WITH_PUBLIC_DIAGNOSTIC_KNOWLEDGE'},
 'unused_arm':'B is prepared by the three-cell broker but never launched, graded, or included in denominator. Existing M2 safe-pool intentionally rejects these failed same-target records.',
 'names':names,'evaluation_instances':[d['task_id'] for d in evaluation],
 'replicates_per_task_arm':2,'planned_evaluation_cells':8,
 'launch_order':dict(zip(names,[['A','C'],['C','A'],['C','A'],['A','C']])),
 'concurrency':'At most two fresh independent solvers, one task/replicate pair at a time.',
 'outcome_policy':'All eight fixed cells retained, one submission and official grade each. No outcome-based retries, memory edits, prompt changes, extra guidance or exclusions. Public diagnostic memory is frozen before first solver.',
 'primary_metric':'Resolved C minus A over the four matched task-replicate observations; also report per-task two-replicate outcomes. Repeated tasks are not independent new issues.',
 'next_phase':'Separate prospectively frozen transfer experiment on 21612/21847/22714/24661; no claim yet.',
 'limits':{'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000},
 'frozen_at_unix_seconds':time.time(),'separate_model_api_calls':0,'codex_tokens_and_cost':None,
 'solver_model_calls_so_far':0,'grader_calls_so_far':0,'root_cross_cell_feedback':False}
save('launch-contract.json',contract)
save('attestations.json',[])
print(json.dumps({'status':'FROZEN_BEFORE_EIGHT_SOLVERS','bank':bank,'contract_sha256':hashlib.sha256((central/'launch-contract.json').read_bytes()).hexdigest(),'source_files':len(source_hashes)}))
