"""Run once, after public runtime and code validation, before any Native011 solver."""
import time
import xml.etree.ElementTree as ET

win = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
temp = Path('/mnt/c/Users/jewon/AppData/Local/Temp')
runtime_root = Path('/home/trimem-runner/native011-dataset-preparation')
sys.path[:0] = [str(win/'scripts'), str(win/'src')]
import trimem_skhynix_native_controlled_dataset as enrollment
import trimem_skhynix_native_dataset as dataset
import trimem_skhynix_codex_controlled_lessons as lessons

def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_text())
def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2); stream.write('\n')
def copy(path, name):
    raw = path.read_bytes()
    out = central/name
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream: stream.write(raw)
    return sha(raw)

assert central == Path('/home/trimem-runner/skhynix-codex-011')
assert not central.exists() and not central.is_symlink(), 'REFUSE_EXISTING_EXPERIMENT'
config = win/'configs/skhynix_v1/codex_011_manifest.json'
assert not config.exists() and not config.is_symlink(), 'REFUSE_EXISTING_CONFIG'
lesson_draft = win/'Temp/native011_lessons_draft.json'
assert sha(lesson_draft.read_bytes()) == 'f4c1e9a529732e268d759f9d62cdc5337b2edb1ff679c4ad84bc78a27729f764'
candidate_path = temp/'native011_public_candidates.json'
assert sha(candidate_path.read_bytes()) == '351974c275075ea689d272abb2ca3f9faba358bd9ae80e3880402a678f7f409b'
validation = {}
for label in ('dataset', 'controlled'):
    suffix = '_final_v2' if label == 'dataset' else ''
    receipt_path = temp/f'native011_{label}_validation{suffix}.json'
    xml_path = temp/f'native011_{label}_validation{suffix}.xml'
    receipt = read(receipt_path)
    xml = ET.fromstring(xml_path.read_bytes())
    assert receipt['status'] == 'PASS'
    assert receipt['tests'] == len(list(xml.iter('testcase')))
    assert not any(list(xml.iter(tag)) for tag in ('failure','error','skipped'))
    assert receipt['xml_sha256'] == sha(xml_path.read_bytes())
    assert all(sha((win/p).read_bytes()) == digest for p,digest in receipt['source_sha256'].items())
    validation[label] = {'tests':receipt['tests'], 'xml_sha256':sha(xml_path.read_bytes()),
                         'receipt_sha256':sha(receipt_path.read_bytes())}

# Preserve original completed experiments and their public copies before setup.
protected = {}
for number in (7,8,9,10):
    public = win/f'artifacts/skhynix_v1/codex_{number:03}'
    manifest_path = public/'public-artifact-manifest.json'
    manifest = read(manifest_path)
    protected[str(manifest_path)] = sha(manifest_path.read_bytes())
    for item in manifest['files']:
        for path in (public/item['path'], Path(item['source'])):
            assert path.is_file() and not path.is_symlink(), 'PREVIOUS_ARTIFACT_MISSING'
            raw = path.read_bytes()
            assert sha(raw) == item['sha256'] and len(raw) == item['bytes'], 'PREVIOUS_ARTIFACT_CHANGED'
            protected[str(path)] = sha(raw)

runtime_summary = read(runtime_root/'runtime-v2-summary.json')
assert runtime_summary['status'] == 'COMPLETE' and not runtime_summary['failures']
assert all(row['runtime_compatible'] is True for row in runtime_summary['results'])
images = read(runtime_root/'images.json')
if isinstance(images, dict): images = images['images']
runtime = []
for row in runtime_summary['results']:
    runtime.append({'instance_id':row['instance_id'],'image':row['image'],
        'python_executable':row['public_python'],'python_version':'Python '+row['python_version'],
        'runner_sha256':row['runner_sha256'],'probe_sha256':row['runtime_probe_sha256'],
        'status':'PASS_PUBLIC_RUNTIME_ONLY',
        'runtime_receipt_path':str(runtime_root/'runtime-v2'/row['instance_id']/'result.json'),
        'runtime_receipt_sha256':sha((runtime_root/'runtime-v2'/row['instance_id']/'result.json').read_bytes())})
numbers = (13615,15875,18698,19495)
ids = [f'sympy__sympy-{n}' for n in numbers]
images_map = {row['instance_id']:row for row in images}
runtime_map = {row['instance_id']:row for row in runtime}
assert set(images_map) == set(runtime_map) == set(ids)
selection = {'method':'PUBLIC_ISSUE_MECHANISM_MATCH_BEFORE_SOLVER_OUTCOMES',
 'source_instance_ids':list(enrollment.SOURCES),
 'targets':[
  {'instance_id':ids[0],'family':'sets','rationale':'Public finite-set complement loses undecidable symbolic membership. Direct unknown-state preservation hypothesis.'},
  {'instance_id':ids[1],'family':'polynomial','rationale':'Public algebraically zero expression incorrectly has is_zero False. Zero semantics transfer from polynomial normalization to core assumptions; different subsystem.'},
  {'instance_id':ids[2],'family':'polynomial','rationale':'Public sqf and sqf_list disagree on canonical multiplicity grouping. Broader normalization-across-sibling-operations hypothesis, not the original dense-zero bug.'},
  {'instance_id':ids[3],'family':'sets','rationale':'Public ConditionSet substitution differs across FiniteSet and ImageSet representations. Broader representation-consistency hypothesis; bound-variable mechanism is not explicitly taught.'}
 ]}
central.mkdir()
save(central/'previous-evidence-seal.json', {'schema':'skhynix/native011-prior-preservation/1.0','files':protected})
copy(lesson_draft, 'source-lessons.json')
copy(win/'Temp/native011_lesson_derivation.md', 'lesson-derivation.md')
copy(candidate_path,'public-candidate-selection.json')
for label in validation:
    suffix = '_final_v2' if label == 'dataset' else ''
    copy(temp/f'native011_{label}_validation{suffix}.json',f'{label}-validation.json')
    copy(temp/f'native011_{label}_validation{suffix}.xml',f'{label}-validation.xml')
manifest = enrollment.build_controlled_manifest(cache_root=Path('/opt/trimem-rehearsals/e932-preflight/datasets'),
    output_path=central/'supplemental-manifest.json', selection=selection,
    images=[images_map[i] for i in ids], runtime=[runtime_map[i] for i in ids], root=win)
raw = (central/'supplemental-manifest.json').read_bytes()
with config.open('xb') as stream: stream.write(raw)
targets, rows, _, loaded = dataset.load_supplemental_rows(central/'supplemental-manifest.json',
    Path('/opt/trimem-rehearsals/e932-preflight/datasets'),expected_sha256=sha(raw),root=win)
assert manifest == loaded and [t['instance_id'] for t in targets] == ids
descriptors = [{'task_id':t['target_id'], 'repository':t['repository'], 'commit':t['base_commit'],
                'instruction_sha256':t['public_instruction_sha256']} for t in targets]
assignments = []
for target, selected in zip(targets,selection['targets']):
    relevant, unrelated = ('canonical_polynomial_zero','extensional_set_relations')
    if selected['family'] == 'sets': relevant,unrelated = unrelated,relevant
    assignments.append({'task_id':target['target_id'],'relevant_lesson_id':relevant,'unrelated_lesson_id':unrelated})
bank = lessons.freeze_controlled_manifest(central/'controlled-lessons.json',
    lessons_path=central/'source-lessons.json',targets=descriptors,assignments=assignments)
save(central/'evaluation-task-descriptors.json',descriptors)
prompt_sha = copy(win/'artifacts/skhynix_v1/codex_010/solver_prompt_template.txt','solver_prompt_template.txt')
assert prompt_sha == '745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05'
source_paths = sorted([*win.glob('src/enterprise_memory/**/*.py'),*win.glob('scripts/*.py'),
                       *win.glob('configs/skhynix_v1/*manifest.json')])
source_hashes = {}
for path in source_paths:
    assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(win.resolve())
    source_hashes[str(path.relative_to(win))] = sha(path.read_bytes())
save(central/'source-freeze.json',{'schema':'skhynix/native011-source-freeze/1.0','head':HEAD,
    'sha256':source_hashes,'source_files':len(source_hashes),'frozen_before_all_new_solver_calls':True})
names = [f'transfer-{n}-r1' for n in numbers]
contract = {'schema':'skhynix/native011-launch-contract/1.0','scientific_role':'CONTROLLED_CONTENT_TRANSFER',
 'scenario':'RETROSPECTIVE_DISJOINT_TRANSFER','requested_model':'gpt-6-astra','fork_turns':'none',
 'reasoning_effort':'INHERITED_PARENT_UNCHANGED','evaluation_template_sha256':prompt_sha,
 'manifest_sha256':sha(raw),'source_freeze_sha256':sha((central/'source-freeze.json').read_bytes()),
 'controlled_lessons_sha256':sha((central/'controlled-lessons.json').read_bytes()),
 'source_lessons_sha256':sha((central/'source-lessons.json').read_bytes()),
 'public_candidates_sha256':sha(candidate_path.read_bytes()),'validation':validation,
 'previous_evidence_seal_sha256':sha((central/'previous-evidence-seal.json').read_bytes()),
 'lesson_derivation_sha256':sha((central/'lesson-derivation.md').read_bytes()),
 'runtime_preparation_manifest_sha256':sha((runtime_root/'preparation-artifact-manifest.json').read_bytes()),
 'runtime_summary_sha256':sha((runtime_root/'runtime-v2-summary.json').read_bytes()),
 'initialization_failure_note_sha256':sha(Path('/home/trimem-runner/native011-initialization-attempt-1/failure-note.json').read_bytes()),
 'arms':{'A':'NO_MEMORY','B':'DOMAIN_MISMATCHED_LENGTH_MATCHED_LESSON','C':'PREDECLARED_RELEVANT_LESSON'},
 'names':names,'evaluation_instances':[t['task_id'] for t in descriptors],
 'source_instances':['swebench_verified--'+i for i in enrollment.SOURCES],
 'planned_evaluation_cells':12,'replicates_per_task_arm':1,
 'launch_order':dict(zip(names,[['A','B','C'],['B','C','A'],['C','A','B'],['A','C','B']])),
 'concurrency':'At most three fresh solvers; one matched task triple at a time.',
 'limits':{'actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000},
 'delivery':'One initial recall required in every arm. A empty, B/C one assigned lesson independently of lexical score. No repeated delivery.',
 'lesson_utf8_bytes_each':1670,'lesson_word_counts':[231,240],
 'length_matching_scope':'Exact lesson-text UTF8 bytes; words approximately matched, model tokens not measured.',
 'control_limitation':'Opposite-domain lesson shares generic verification and symbolic caution; it is not proven to have zero relevance.',
 'memory_type':'Source-only analyst generalization from public failed episodes, GateB0. Not an automated verified skill or end-to-end retrieval evaluation.',
 'chronology_claim':enrollment.CHRONOLOGY,
 'primary_metric':'Official issue resolution C minus A over all four fixed tasks.',
 'specificity_control':'Official issue resolution C minus B, reported separately from C minus A.',
 'secondary_metrics':['broker actions','wall seconds','actual delivered bytes'],
 'outcome_policy':'All12 cells retained; one fresh solver, submission and official grade each. No outcome-based retries, exclusions, replacements, memory edits or extra hints.',
 'selection_policy':'Public issue/mechanism selection and runtime feasibility only, no target solve/test outcomes. Scope and match strength declared before solvers.',
 'frozen_at_unix_seconds':time.time(),'solver_model_calls_so_far':0,'grader_calls_so_far':0,
 'separate_model_api_calls':0,'codex_tokens_and_cost':None}
save(central/'launch-contract.json',contract)
save(central/'attestations.json',[])
save(central/'operations-note.json',{'schema':'skhynix/native011-operations/1.0',
 'pre_solver_runtime_notes':'Partial public history archive failed before runtime probes; same pinned public bases fetched by codeload. All attempts preserved.',
 'pre_enrollment_initialization_note':'First initialization stopped at public runtime help validation before manifest/config/sourcefreeze/plans/solvers. Original partial artifacts preserved; corrected validator accepts both optparse and argparse help formats.',
 'launch_rejections':[],'solver_outcome_retries':0,'grader_retries':0})
print(json.dumps({'status':'FROZEN_BEFORE_TWELVE_TRANSFER_SOLVERS','contract_sha256':sha((central/'launch-contract.json').read_bytes()),
 'manifest_sha256':sha(raw),'source_files':len(source_hashes),'previous_protected_files':len(protected),'bank':bank}))
