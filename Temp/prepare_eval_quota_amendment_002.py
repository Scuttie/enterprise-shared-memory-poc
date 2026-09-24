"""Pin the retained quota-failed attempt without changing original records."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json

REPO=Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE=REPO/'artifacts/skhynix_v1/architecture_scale_001'
OUT=BASE/'l3-recovery-001/evaluation-continuation-002'
PRIOR=Path('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v16')
COHORT=Path('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v15/development/baseline/run/cohort')
TASK='swebench--matplotlib__matplotlib-25565'
CELL=COHORT.parent/'cells/EVALUATION'/TASK/'BASELINE/cell.json'

def read(p):return json.loads(Path(p).read_bytes())
def ref(p):
    p=Path(p)
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

cell=read(CELL)
config=read(cell['experiment_config'])
broker=Path(cell['broker_root'])
failure=read(CELL.parent/'native-execution-failure.json')
audit=read(CELL.parent/'execution-audit.json')
assert audit['passed'] is False and failure['launcher_returncode']==1
assert not (CELL.parent/'public-result.json').exists()
assert not (CELL.parent/'grader-pending.json').exists()
prior_tail=sorted((PRIOR/'events').glob('*.json'))[-1]
cohort_tail=sorted((COHORT/'events').glob('*.json'))[-1]
assert read(prior_tail)['stage']=='PIPELINE_BLOCKED'
assert read(cohort_tail)['stage']=='INFRA_ERROR' and read(cohort_tail)['task_id']==TASK
native=Path(config['native_control_root'])/cell['phase']/cell['target']['instance_id']/cell['arm']
refs={'cell':ref(CELL),'audit':ref(CELL.parent/'execution-audit.json'),
      'failure':ref(CELL.parent/'native-execution-failure.json'),
      'patch':ref(broker/'submission.diff'),'submission':ref(broker/'submission.json')}
for key,name in [('manifest','manifest.json'),('manifest_checksum','manifest.sha256'),
                 ('initial_state','initial-state.json'),('state','state.json'),('events','events.jsonl')]:
    refs['broker_'+key]=ref(broker/name)
workers=sorted(native.glob('worker-*'))
assert len(workers)==3
for number,worker in enumerate(workers,1):
    for key,name in [('config','config.json'),('packet','packet.json'),('admission','admission.json'),
                     ('launch','output/launch.json'),('completion','output/completion.json'),
                     ('events','output/events.jsonl')]:
        refs[f'worker_{number}_{key}']=ref(worker/name)
value={'schema':'skhynix/evaluation-native-quota-amendment/1.0',
 'policy':'RETAIN_NATIVE_SERVICE_USAGE_LIMIT_UNSCORED_AND_CONTINUE_FIXED_SCHEDULE',
 'recorded_at':datetime.now(timezone.utc).isoformat(),
 'previous_configuration_reference':ref(REPO/'configs/skhynix_v1/architecture_002_pipeline_v16.json'),
 'previous_pipeline_event_tail_reference':ref(prior_tail),
 'previous_activation_reference':ref(BASE/'active-controller-v16-health2.json'),
 'baseline_cohort_reference':ref(COHORT/'cohort.json'),
 'baseline_experiment_reference':ref(cell['experiment_config']),
 'baseline_event_tail_reference':ref(cohort_tail),
 'initial_held_task_id':TASK,'initial_held_arm':'BASELINE','initial_held_evidence_references':refs,
 'applies_to':['BASELINE','PDF_MEMORY'],'applies_to_phases':['DEVELOPMENT','FINAL'],
 'native_outcome_retries':False,'official_grading_retries':False,'undetermined_as_failure':False,
 'training_memory_updates':False,'solver_runtime_changed':False,'dataset_changed':False,
 'pause_on_new_native_quota':True,'original_journal_prefixes_preserved':True,
 'original_attempt_resources_retained':True,
 'paired_comparison':'ONLY_IDENTICAL_TASKS_WITH_TWO_OFFICIAL_RESULTS',
 'full_enrollment_delta_if_missing':None,
 'original_graded_undetermined':1,'original_native_quota_undetermined':1,
 'original_official_counts':{'official_complete':15,'resolved':13,'unresolved':2},
 'availability_probe_reference':ref(BASE/'l3-recovery-001/evaluation-continuation-001/availability-20260921T005434Z/receipt.json'),
 'reason':'User authorized continuation after native model availability was verified with existing ChatGPT credits. Preserve the original quota-interrupted attempt as unscored, without solver/grader retry, retain all enrolled tasks and prior grades, and continue the next original task. Pause again on any newly observed native quota failure rather than cascading through untouched tasks.',
 'model_calls':0,'official_grader_runs':0}
OUT.mkdir(parents=True,exist_ok=True)
path=OUT/'amendment.json'
with path.open('xb') as stream:
    stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+b'\n')
print(json.dumps({'amendment_reference':ref(path),'prior_pipeline_tail':ref(prior_tail),'cohort_prefix':ref(cohort_tail),'evidence_count':len(refs)}))
