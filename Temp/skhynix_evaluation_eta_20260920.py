"""Read public event timings only; never inspect solver or grader payloads."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from statistics import mean, median
import json

KST = timezone(timedelta(hours=9))
ROOT = Path('/home/trimem-runner/skhynix-architecture-scale-001')

def timings(folder):
    events = [json.loads(p.read_bytes()) for p in sorted((folder / 'events').glob('*.json'))]
    cleaned = [e['at'] for e in events if e.get('stage') == 'CLEANED']
    intervals = [(b-a)/60 for a,b in zip(cleaned, cleaned[1:])]
    statistics = {}
    for count in (10, 20):
        sample = intervals[-count:]
        if sample:
            statistics[str(count)] = dict(n=len(sample), mean_minutes=mean(sample),
                median_minutes=median(sample), min_minutes=min(sample), max_minutes=max(sample))
    return events, statistics

training, statistics = timings(ROOT / 'training-240-v1/cohort')
evaluation, _ = timings(ROOT / 'pipeline-v15/development/baseline/run/cohort')
visible = [{key: e.get(key) for key in ('stage', 'task_id', 'arm', 'at')}
           for e in evaluation if e.get('stage') in
           ('PREPARE_STARTED', 'SOLVE_STARTED', 'GRADE_STARTED', 'CELL_COMPLETE', 'CLEANED')]
for e in visible:
    e['at_kst'] = datetime.fromtimestamp(e['at'], KST).isoformat()
completed = [e for e in evaluation if e.get('stage') == 'CELL_COMPLETE']
now = datetime.now(KST)
milestones = {}
for name, total in [('baseline10',10), ('baseline60',60), ('paired_development10',70),
                    ('development_complete',120), ('final_complete',1120)]:
    remaining = max(0, total-len(completed))
    milestones[name] = {'remaining_cells':remaining, 'planning_minutes_per_cell':[15,25],
        'earliest_kst':(now+timedelta(minutes=15*remaining)).isoformat(),
        'latest_kst':(now+timedelta(minutes=25*remaining)).isoformat()}
result = {'schema':'skhynix/public-timing-estimate/1.0', 'observed_at_kst':now.isoformat(),
    'training_cleaned_interval_statistics':statistics, 'evaluation_completed_cells':len(completed),
    'evaluation_public_timings':visible, 'milestones':milestones,
    'assumptions':['Sequential uninterrupted operation', 'No quota or infrastructure pause',
        '15-25 min is a provisional planning range, not a statistical prediction interval',
        'Current completed evaluation sample is too small for a stable throughput estimate'],
    'model_calls':0, 'grader_payloads_read':0}
out = Path('/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-eta-20260920T1005.json')
with out.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps(result))
