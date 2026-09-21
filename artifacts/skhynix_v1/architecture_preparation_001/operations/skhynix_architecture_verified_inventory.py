from pathlib import Path
import hashlib
import json
import pyarrow.parquet as pq

revision = '78f471bf655a3137b2e8a75af1501690ec009ec3'
source = Path('/opt/trimem-rehearsals/e932-preflight/datasets/swebench_verified') / revision / 'test-00000-of-00001.parquet'
destination = Path('/mnt/c/Users/jewon/esm-r23-d115-writer/configs/skhynix_v1/architecture_verified500_inventory.json')
data = source.read_bytes()
digest = hashlib.sha256(data).hexdigest()
assert len(data) == 6304616 and digest == '030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25'
# Only public identity and instruction fields are decoded. No patch/test columns.
rows = pq.read_table(source, columns=['instance_id', 'repo', 'base_commit', 'created_at', 'problem_statement']).to_pylist()
assert len(rows) == len({row['instance_id'] for row in rows}) == 500
assert all(isinstance(row['problem_statement'], str) and row['problem_statement'].strip() for row in rows)
tasks = [{'instance_id': row['instance_id'], 'repository': row['repo'], 'base_commit': row['base_commit'],
          'created_at': row['created_at'],
          'instruction_sha256': hashlib.sha256(row['problem_statement'].strip().encode('utf-8')).hexdigest()}
         for row in sorted(rows, key=lambda item: item['instance_id'])]
inventory = {'schema': 'skhynix/architecture-public-task-inventory/1.0',
             'dataset': {'dataset_id': 'princeton-nlp/SWE-bench_Verified', 'revision': revision,
                         'split': 'test', 'path': str(source), 'sha256': digest, 'bytes': len(data)},
             'tasks': tasks}
payload = (json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
with destination.open('xb') as stream:
    stream.write(payload)
assert destination.read_bytes() == payload
print(json.dumps({'status': 'PUBLIC_INVENTORY_WRITTEN', 'tasks': len(tasks),
                  'repositories': len({row['repository'] for row in tasks}), 'bytes': len(payload),
                  'sha256': hashlib.sha256(payload).hexdigest(), 'path': str(destination),
                  'restricted_columns_decoded': False, 'model_calls': 0, 'grader_calls': 0}))
