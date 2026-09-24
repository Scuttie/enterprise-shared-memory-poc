"""Export public completion evidence and report full versus partial denominators."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
from trimem_skhynix_architecture_native import read,write_new,digest,canonical


def counts(rows,planned):
    complete=len(rows)
    resolved=sum(row['resolved'] for row in rows)
    return {'planned':planned,'official_complete':complete,'resolved':resolved,
        'missing':planned-complete,'completed_sample_rate':resolved/complete if complete else None,
        'full_cohort_rate':resolved/planned if complete==planned else None}


def export_progress(config_paths,output_root):
    output=Path(output_root).resolve()
    results={}
    configurations_by_root={}
    for config_path in config_paths:
        config=read(config_path)
        identity=digest(canonical(config))
        if identity!=Path(config_path).with_suffix('.sha256').read_text().strip():
            raise ValueError('Execution config changed')
        root=Path(config['run_root']).resolve()
        enrolled=configurations_by_root.setdefault(root,{})
        if identity in enrolled:
            raise ValueError('Duplicate execution configuration')
        enrolled[identity]=(config,str(Path(config_path).resolve()))
    for root,enrolled in configurations_by_root.items():
        for path in sorted((root/'cells').glob('*/*/*/public-result.json')):
            value=read(path)
            if value.get('experiment_sha256') not in enrolled:
                raise ValueError('Public result belongs to an unenrolled execution configuration')
            config,config_path=enrolled[value['experiment_sha256']]
            cell=read(path.parent/'cell.json')
            if (value['official'] is not True or value['grader_status']!='success' or
                type(value['resolved']) is not bool or cell.get('experiment_config')!=config_path or
                config.get('reasoning_effort') not in {'ultra','high'} or
                value['task_id']!=cell['task_public']['task_id'] or value['arm']!=cell['arm'] or value['phase']!=cell['phase']):
                raise ValueError('Public official result binding differs')
            audit=read(path.parent/'execution-audit.json')
            if audit['passed'] is not True or digest((path.parent/'execution-audit.json').read_bytes())!=value['execution_audit_sha256']:
                raise ValueError('Public result has no matching passed execution audit')
            key=(value['phase'],value['task_id'],value['arm'])
            if key in results:
                raise ValueError('Duplicate task outcome; explicit experiment separation required')
            target=output/value['phase'].lower()/cell['target']['instance_id']/value['arm']
            target.mkdir(parents=True,exist_ok=True)
            public_refs={}
            for name,source in [('public-result.json',path),('execution-audit.json',path.parent/'execution-audit.json'),
                    ('submission.diff',path.parent/'broker/submission.diff')]:
                raw=source.read_bytes()
                destination=target/name
                if destination.exists():
                    if destination.read_bytes()!=raw:
                        raise ValueError('Preserved public result changed')
                else:
                    with destination.open('xb') as stream:stream.write(raw)
                public_refs[name]={'path':str(destination),'sha256':digest(raw)}
            usage=[]
            folder=Path(config['native_control_root'])/value['phase']/cell['target']['instance_id']/value['arm']
            for completion_path in sorted(folder.glob('worker-*/output/completion.json')):
                complete=read(completion_path)
                usage.append(complete.get('usage') or {})
            submission=value['broker_status']['submission']
            results[key]={'phase':value['phase'],'task_id':value['task_id'],'arm':value['arm'],
                'experiment_sha256':value['experiment_sha256'],'reasoning_effort':config['reasoning_effort'],
                'repository':cell['task_public']['repository'],'resolved':value['resolved'],
                'tool_requests':submission['actions'],'native_workers':value['broker_status']['workers_admitted'],
                'submission_seconds':submission['submitted_at']-submission['started_at'] if submission['started_at'] else None,
                'grader_wall_ms':value['grader_wall_time_ms'],'public_references':public_refs,
                'input_tokens':sum(item.get('input_tokens',0) for item in usage),
                'cached_input_tokens':sum(item.get('cached_input_tokens',0) for item in usage),
                'output_tokens':sum(item.get('output_tokens',0) for item in usage),
                'memory_injections':value['broker_status']['memory_injections'],'bank_sha256':value['bank_sha256']}
    rows=list(results.values())
    training=[row for row in rows if row['phase']=='TRAINING']
    evaluation={arm:[row for row in rows if row['phase']=='EVALUATION' and row['arm']==arm] for arm in ('BASELINE','PDF_MEMORY')}
    by_task={arm:{row['task_id']:row['resolved'] for row in values} for arm,values in evaluation.items()}
    paired=sorted(set(by_task['BASELINE']) & set(by_task['PDF_MEMORY']))
    efforts={arm:{row['task_id']:row['reasoning_effort'] for row in values} for arm,values in evaluation.items()}
    if any(efforts['BASELINE'][task]!=efforts['PDF_MEMORY'][task] for task in paired):
        raise ValueError('Paired evaluation reasoning settings differ')
    delta=sum(int(by_task['PDF_MEMORY'][task])-int(by_task['BASELINE'][task]) for task in paired)
    progress={'schema':'skhynix/architecture-public-progress/1.0','updated_at':datetime.now(timezone.utc).isoformat(),
        'training':counts(training,24),'evaluation':{arm:counts(values,500) for arm,values in evaluation.items()},
        'training_by_reasoning_effort':{effort:{'official_complete':len(selected),
            'resolved':sum(row['resolved'] for row in selected),
            'completed_sample_rate':sum(row['resolved'] for row in selected)/len(selected)}
            for effort in sorted({row['reasoning_effort'] for row in training})
            if (selected:=[row for row in training if row['reasoning_effort']==effort])},
        'completed_pairs':len(paired),'planned_pairs':500,
        'completed_pair_delta_percentage_points':100*delta/len(paired) if paired else None,
        'full_cohort_delta_percentage_points':100*delta/500 if len(paired)==500 else None,
        'separate_model_api_client_calls':0,'rows':rows}
    output.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot=output/'progress-history'/(stamp+'.json')
    write_new(snapshot,progress)
    temporary=output/'progress.next.json'
    temporary.write_bytes(canonical(progress)+b'\n')
    temporary.replace(output/'progress.json')
    return {**{key:value for key,value in progress.items() if key!='rows'},
        'snapshot_reference':{'path':str(snapshot),'sha256':digest(canonical(progress)+b'\n')}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-config',action='append',required=True)
    parser.add_argument('--output-root',required=True)
    args=parser.parse_args()
    print(json.dumps(export_progress(args.experiment_config,args.output_root)))
