from pathlib import Path
import hashlib, json
folder = Path('/home/trimem-runner/skhynix-architecture-scale-001/pipeline-v15/development/baseline/run/cells/EVALUATION/swebench--matplotlib__matplotlib-20374/BASELINE')
cell = json.loads((folder/'cell.json').read_bytes())
task = cell['task_public']['task_id']
model = 'trimem-v1-'+cell['arm']
run_id = hashlib.sha256((task+':'+model).encode()).hexdigest()[:20]
aggregate = Path(cell['prepared_output_root'])/'official-grader'/task/'report'/(model+'.'+run_id+'.json')
value = json.loads(aggregate.read_bytes())
keys = ['schema_version','total_instances','submitted_instances','completed_instances','resolved_instances',
        'unresolved_instances','ambiguous_failure_instances','infra_failure_instances','empty_patch_instances',
        'error_instances','unstopped_instances','failure_reasons','incomplete_ids','unstopped_containers']
print(json.dumps({'aggregate_reference':{'path':str(aggregate),'sha256':hashlib.sha256(aggregate.read_bytes()).hexdigest()},
    'aggregate_metadata':{k:value.get(k) for k in keys},
    'audit_passed':json.loads((folder/'execution-audit.json').read_bytes())['passed'],
    'pending':json.loads((folder/'grader-pending.json').read_bytes()),
    'public_result_exists':(folder/'public-result.json').exists(),
    'private_result_exists':(folder/'grader-private.json').exists()}))
