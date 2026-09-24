from pathlib import Path
import hashlib
import json

root = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
source_root = Path('/home/trimem-runner/skhynix-architecture-preparation/datasets')

def read_verified(path, digest):
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    return json.loads(raw)

evaluation = read_verified(root / 'configs/skhynix_v1/architecture_verified500_inventory.json',
    '437d84f2e76eaa8a2293788b7bebb0f86dbf27cd6e4acb9a6b855d4e19ac7f77')
prior = read_verified(source_root / 'test-disjoint-candidate-public-task-inventory.json',
    'd8b78e02f1f1c432c150f2839920e3c2f52a1c3f05bbe0a06f7a449f3da56ce3')
assert set(prior) == {'schema', 'dataset', 'tasks'}
assert prior['schema'] == evaluation['schema']
eval_ids = {row['instance_id'] for row in evaluation['tasks']}
eval_text = {row['instruction_sha256'] for row in evaluation['tasks']}
assert len(prior['tasks']) == 1794
assert not {row['instance_id'] for row in prior['tasks']} & eval_ids
excluded = sorted(row['instance_id'] for row in prior['tasks'] if row['instruction_sha256'] in eval_text)
assert len(excluded) == 8
filtered = {**prior, 'tasks': sorted((row for row in prior['tasks'] if row['instruction_sha256'] not in eval_text),
                                    key=lambda row: row['instance_id'])}
assert len(filtered['tasks']) == 1786
assert {row['repository'] for row in filtered['tasks']} == {row['repository'] for row in evaluation['tasks']}
destination = root / 'configs/skhynix_v1/architecture_training_candidates_inventory.json'
raw = (json.dumps(filtered, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
with destination.open('xb') as stream:
    stream.write(raw)
print(json.dumps({'status': 'CANDIDATE_INVENTORY_ONLY', 'training_enrolled': 0, 'training_executed': 0,
    'candidates': len(filtered['tasks']), 'repositories': 12, 'excluded_same_issue_text_ids': excluded,
    'path': str(destination), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
    'columns_decoded': 'PUBLIC_JSON_DESCRIPTORS_ONLY', 'model_calls': 0, 'grader_calls': 0}))
