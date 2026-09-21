"""Record the exact grading-blocked predecessor without changing its records."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json

REPO=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001'
OLD=Path('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v15')
TASK='swebench--matplotlib__matplotlib-20374'

def ref(path):
    path=Path(path)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def read(path):
    return json.loads(Path(path).read_bytes())

cell_path=OLD/'development/baseline/run/cells/EVALUATION'/TASK/'BASELINE/cell.json'
cell=read(cell_path)
model='trimem-v1-BASELINE'
run_id=hashlib.sha256((TASK+':'+model).encode()).hexdigest()[:20]
aggregate=Path(cell['prepared_output_root'])/'official-grader'/TASK/'report'/(model+'.'+run_id+'.json')
metadata=read(aggregate)
assert metadata['failure_reasons']=={'matplotlib__matplotlib-20374':'no_tests_collected'}
pipeline_tail=sorted((OLD/'events').glob('*.json'))[-1]
cohort=OLD/'development/baseline/run/cohort'
cohort_tail=sorted((cohort/'events').glob('*.json'))[-1]
assert read(pipeline_tail)['stage']=='PIPELINE_BLOCKED'
assert read(cohort_tail)['stage']=='INFRA_ERROR' and read(cohort_tail)['task_id']==TASK
references={'cell':ref(cell_path),'audit':ref(cell_path.parent/'execution-audit.json'),
    'pending':ref(cell_path.parent/'grader-pending.json'),'aggregate':ref(aggregate),
    'patch':ref(Path(cell['broker_root'])/'submission.diff'),
    'submission':ref(Path(cell['broker_root'])/'submission.json')}
value={'schema':'skhynix/evaluation-accounting-amendment/1.0',
    'policy':'RETAIN_TERMINAL_AMBIGUITY_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE',
    'recorded_at':datetime.now(timezone.utc).isoformat(),
    'previous_configuration_reference':ref(REPO/'configs/skhynix_v1/architecture_002_pipeline_v15.json'),
    'previous_pipeline_event_tail_reference':ref(pipeline_tail),
    'baseline_cohort_reference':ref(cohort/'cohort.json'),
    'baseline_experiment_reference':ref(OLD/'development/baseline/execution.json'),
    'baseline_event_tail_reference':ref(cohort_tail),
    'initial_held_task_id':TASK,'initial_held_evidence_references':references,
    'known_terminal_reasons':['missing_module','no_tests_collected'],
    'applies_to':['BASELINE','PDF_MEMORY'], 'applies_to_phases':['DEVELOPMENT','FINAL'],
    'native_outcome_retries':False,'official_grading_retries':False,'undetermined_as_failure':False,
    'training_memory_updates':False,'solver_runtime_changed':False,'dataset_changed':False,
    'original_journal_prefixes_preserved':True,'original_attempt_resources_retained':True,
    'paired_comparison':'ONLY_IDENTICAL_TASKS_WITH_TWO_OFFICIAL_RESULTS',
    'full_enrollment_delta_if_missing':None,
    'reason':'Continue the enrolled evaluation after a terminal official no_tests_collected ambiguity. Preserve the held grade as unknown and every official prior result; do not rerun a solver or grader. Apply the same accounting to both arms and retain full enrollment.',
    'model_calls':0,'official_grader_runs':0}
BASE.mkdir(parents=True,exist_ok=True)
path=BASE/'amendment.json'
with path.open('xb') as stream:
    stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+b'\n')
print(json.dumps(ref(path)))
