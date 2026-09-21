"""Snapshot enrolled official public results, without reading private grader data."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from statistics import mean, median
import csv
import hashlib
import json

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
ROOT = Path('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v15')
OUT = REPO / 'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001'
KST = timezone(timedelta(hours=9))

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    return json.loads(Path(path).read_bytes())

def ref(path):
    path = Path(path)
    return {'path':str(path), 'sha256':digest(path.read_bytes())}

def checked(reference):
    path = Path(reference['path'])
    assert ref(path) == reference, path
    return read(path)

def event_chain(folder):
    paths = sorted((folder / 'events').glob('*.json'))
    chain, previous = [], '0'*64
    for i, path in enumerate(paths, 1):
        row = read(path)
        assert path.name == f'{i:08d}.json'
        assert row['sequence'] == i and row['previous_sha256'] == previous
        assert row['sha256'] == digest(canonical({k:v for k,v in row.items() if k != 'sha256'}))
        previous = row['sha256']
        chain.append(row)
    return chain, ref(paths[-1]) if paths else None

now = datetime.now(timezone.utc)
prefix = 'interim-results-' + now.strftime('%Y%m%dT%H%M%SZ')
pipeline_events, pipeline_tail = event_chain(ROOT)
rows, cohorts, source_stamps = [], [], []
for phase, name, planned, arms in [('DEVELOPMENT','baseline',60,['BASELINE']),
                                  ('DEVELOPMENT','bank-240',60,['PDF_MEMORY']),
                                  ('FINAL','verified500',1000,['BASELINE','PDF_MEMORY'])]:
    folder = ROOT / ('development' if phase == 'DEVELOPMENT' else 'final') / name / 'run/cohort'
    manifest_path = folder / 'cohort.json'
    if not manifest_path.exists():
        cohorts.append({'phase':phase, 'name':name, 'planned':planned, 'arms':arms,
                        'status':'NOT_STARTED', 'official_complete':0, 'resolved':0})
        continue
    manifest = read(manifest_path)
    assert digest(canonical(manifest)) == (folder/'cohort.sha256').read_text().strip()
    execution = checked(manifest['experiment_reference'])
    assert execution['model'] == 'gpt-6-astra' and execution['reasoning_effort'] == 'high'
    assert execution['phase'] == 'EVALUATION_RUNTIME'
    events, tail = event_chain(folder)
    before = len(rows)
    last_by_task = {}
    for event in events:
        if event.get('task_id'):
            last_by_task[(event['task_id'],event.get('arm'))] = event
    for entry in manifest['schedule']:
        task, arm = entry['task_id'], entry['arm']
        cell_path = Path(entry['cell_config'])
        result_path = cell_path.parent / 'public-result.json'
        event = last_by_task.get((task,arm))
        record = {'phase':phase, 'cohort':name, 'ordinal':entry['ordinal'], 'task_id':task,
            'repository':task.split('--',1)[1].rsplit('-',1)[0].replace('__','/'), 'arm':arm,
            'outcome':'NOT_STARTED' if event is None else 'UNSCORED',
            'last_stage':event['stage'] if event else None, 'resolved':None}
        if result_path.exists():
            result_reference = ref(result_path)
            result = read(result_path)
            assert result['official'] is True and result['grader_status'] == 'success'
            assert type(result['resolved']) is bool
            assert result['task_id'] == task and result['arm'] == arm and result['phase'] == 'EVALUATION'
            matching = [e for e in events if e.get('stage') == 'GRADED' and
                e.get('task_id') == task and e.get('arm') == arm]
            assert len(matching) == 1 and matching[0]['details']['result_reference'] == result_reference
            assert matching[0]['details']['official_resolved'] == result['resolved']
            cell = read(cell_path)
            assert result['bank_sha256'] == cell['bank_sha256']
            audit_path = cell_path.parent / 'execution-audit.json'
            audit = read(audit_path)
            assert digest(audit_path.read_bytes()) == result['execution_audit_sha256']
            assert audit['passed'] is True and audit['errors'] == []
            assert audit['event_tail_sha256'] == result['event_tail_sha256']
            assert audit['patch_sha256'] == result['patch_sha256']
            assert result['broker_status']['submission']['configuration_sha256'] == result['experiment_sha256']
            assert result['broker_status']['status'] == 'SUBMITTED'
            injections = result['broker_status']['memory_injections']
            assert arm != 'BASELINE' or injections == 0
            record.update(outcome='RESOLVED' if result['resolved'] else 'UNRESOLVED',
                resolved=result['resolved'], memory_injections=injections,
                requests=result['broker_status']['budget']['requests_used'],
                solver_seconds=result['broker_status']['budget']['elapsed_seconds'],
                grader_seconds=result['grader_wall_time_ms']/1000,
                result_reference=result_reference, execution_audit_reference=ref(audit_path),
                graded_at_kst=datetime.fromtimestamp(matching[0]['at'],KST).isoformat())
            source_stamps.extend([result_reference,ref(audit_path)])
        rows.append(record)
    selected = rows[before:]
    completed = [r for r in selected if r['resolved'] is not None]
    cleaned = [e['at'] for e in events if e.get('stage') == 'CLEANED']
    intervals = [(b-a)/60 for a,b in zip(cleaned,cleaned[1:])]
    cohorts.append({'phase':phase,'name':name,'planned':len(selected),'arms':arms,
        'status':'COMPLETE' if len(completed)==len(selected) else 'PARTIAL',
        'official_complete':len(completed),'resolved':sum(r['resolved'] for r in completed),
        'unresolved':sum(not r['resolved'] for r in completed),
        'unscored_started':sum(r['outcome']=='UNSCORED' for r in selected),
        'not_started':sum(r['outcome']=='NOT_STARTED' for r in selected),
        'solve_rate':sum(r['resolved'] for r in completed)/len(completed) if completed else None,
        'cohort_reference':ref(manifest_path), 'event_tail_reference':tail,
        'last_event':{k:events[-1].get(k) for k in ('stage','task_id','arm','at')} if events else None,
        'mean_cleanup_interval_minutes':mean(intervals) if intervals else None,
        'median_cleanup_interval_minutes':median(intervals) if intervals else None})
    assert event_chain(folder)[1] == tail, 'Cohort advanced while reading; snapshot again'

assert event_chain(ROOT)[1] == pipeline_tail
for reference in source_stamps:
    assert ref(reference['path']) == reference
by_repository = []
for key in sorted({(r['phase'],r['arm'],r['repository']) for r in rows if r['resolved'] is not None}):
    selected = [r for r in rows if (r['phase'],r['arm'],r['repository']) == key and r['resolved'] is not None]
    won = sum(r['resolved'] for r in selected)
    by_repository.append(dict(phase=key[0],arm=key[1],repository=key[2],
        official_complete=len(selected),resolved=won,unresolved=len(selected)-won,solve_rate=won/len(selected)))
paired = {}
for phase in ('DEVELOPMENT','FINAL'):
    by_task = defaultdict(dict)
    for row in rows:
        if row['phase']==phase and row['resolved'] is not None:
            by_task[row['task_id']][row['arm']]=row['resolved']
    pairs = {k:v for k,v in by_task.items() if set(v)=={'BASELINE','PDF_MEMORY'}}
    off = sum(v['BASELINE'] for v in pairs.values())
    on = sum(v['PDF_MEMORY'] for v in pairs.values())
    paired[phase] = dict(paired_tasks=len(pairs),baseline_resolved=off,memory_resolved=on,
        delta_percentage_points=100*(on-off)/len(pairs) if pairs else None)
monitor_latest = ref(REPO/'artifacts/skhynix_v1/architecture_scale_001/monitor/latest.json')
monitor_candidates = sorted((REPO/'artifacts/skhynix_v1/architecture_scale_001/monitor/samples').glob('*.json'), reverse=True)
monitor_frozen = next((ref(p) for p in monitor_candidates if ref(p)['sha256']==monitor_latest['sha256']),None)
assert monitor_frozen is not None, 'The current check must have an immutable sample'
result = {'schema':'skhynix/official-interim-results/1.0','observed_at_kst':now.astimezone(KST).isoformat(),
    'configuration_reference':ref(REPO/'configs/skhynix_v1/architecture_002_pipeline_v15.json'),
    'pipeline_event_tail_reference':pipeline_tail,
    'pipeline_last_event':{k:pipeline_events[-1].get(k) for k in ('stage','job','at','details')},
    'cohorts':cohorts,'by_repository':by_repository,'paired':paired,'rows':rows,
    'validation':'Cohort checksum and complete event chain; GRADED result SHA; official fields; execution audit SHA/patch/event tail; baseline zero injections; stable reread',
    'private_grader_payloads_read':0,'raw_model_transcripts_read':0,'model_calls':0,'grader_runs':0,
    'monitor_reference':monitor_frozen}
path = OUT/(prefix+'.json')
with path.open('x',encoding='utf-8') as stream:
    json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2)
    stream.write('\n')
csv_path = OUT/(prefix+'-tasks.csv')
fields = ['phase','cohort','ordinal','task_id','repository','arm','outcome','resolved','last_stage',
          'requests','solver_seconds','grader_seconds','memory_injections','graded_at_kst']
with csv_path.open('x',newline='',encoding='utf-8-sig') as stream:
    writer = csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps({'artifact':ref(path),'csv':ref(csv_path),
    **{k:v for k,v in result.items() if k not in ('rows','monitor_reference')}}))
