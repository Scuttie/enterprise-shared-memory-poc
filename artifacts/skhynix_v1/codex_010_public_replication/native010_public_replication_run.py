"""Replay frozen PUBLIC probes on isolated copies; no solver or grader runs."""
import ast
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

WIN = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
TEMP = Path('/mnt/c/Users/jewon/AppData/Local/Temp')
CENTRAL = Path('/home/trimem-runner/skhynix-codex-008')
OUT = Path('/home/trimem-runner/native010-public-replication')
DEST = TEMP / 'native010_public_replication_results.json'
SOURCE = CENTRAL / 'recovery-20428-r2/source'
assert not OUT.exists() and not OUT.is_symlink() and not DEST.exists()
sys.path[:0] = [str(SOURCE / 'scripts'), str(SOURCE / 'src')]
import trimem_skhynix_codex as broker
import trimem_benchmark_run as benchmark
from trimem_skhynix_environment import inspect_locked_images
from enterprise_memory.trimem.agent_runtime import CodingTask

broker.block_model_client()
def forbidden(*args, **kwargs):
    raise AssertionError('PUBLIC_REPLICATION_FORBIDS_DATASET_AND_GRADER_ACCESS')
benchmark.grader_factory = forbidden
benchmark.load_frozen_rows = forbidden

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

protected = {}
for run in ('008', '009'):
    root = WIN / 'artifacts/skhynix_v1' / ('codex_' + run)
    manifest_path = root / 'public-artifact-manifest.json'
    protected[str(manifest_path)] = sha(manifest_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    for entry in manifest['files']:
        for path in (root / entry['path'], Path(entry['source'])):
            if path.is_file():
                protected[str(path)] = sha(path.read_bytes())
for helper in ('native008_public_failure_probe.py', 'native008_public_failure_read.py',
               'native008_public_failure_summarize.py'):
    path = TEMP / helper
    protected[str(path)] = sha(path.read_bytes())
freeze = json.loads((CENTRAL / 'source-freeze.json').read_bytes())
for relative, digest in freeze['sha256'].items():
    path = SOURCE / relative
    assert sha(path.read_bytes()) == digest, relative
    protected[str(path)] = digest

probe_path = WIN / 'artifacts/skhynix_v1/codex_008/public-probe-results.json'
probe_raw = probe_path.read_bytes()
assert sha(probe_raw) == '41262bce2a86a70b255bc96c781fed4755045aa29133ce4b104acc8ff066155a'
prior = json.loads(probe_raw)
OUT.mkdir()
(OUT / 'protected-inputs-before.json').write_text(json.dumps(protected, sort_keys=True, indent=2) + '\n')
results = []
for number, name in (('20428', 'recovery-20428-r2'), ('20438', 'recovery-20438-r1')):
    local = WIN / 'artifacts/skhynix_v1/codex_008' / name / 'cells/C'
    public_raw = (local / 'public-task.json').read_bytes()
    public = json.loads(public_raw)['task']
    original_workspace = json.loads((local / 'workspace.json').read_bytes())
    submission = json.loads((local / 'submission.json').read_bytes())
    original_root = Path(original_workspace['checkout_root'])
    assert original_root.is_dir() and original_root.resolve().is_relative_to(CENTRAL)
    task = CodingTask(task_id=public['task_id'], org_id='native010-public-replication',
                      user_id='native010-public-replication', repository=public['repository'],
                      commit=public['commit'], instruction=public['instruction'],
                      files={}, editable_paths=(), public_test=None)
    old = next(row for row in prior['results'] if row['task_id'] == task.task_id)
    probe = old['probe_source']
    assert sha(probe.encode()) == old['probe_sha256']
    assert old['base_commit'] == task.commit
    assert old['image'] == original_workspace['image']
    if number == '20428':
        expression = re.search(r'f = Poly\(sympify\("(.+?)"\), x\)', public['instruction']).group(1)
        literals = [node.args[0].value for node in ast.walk(ast.parse(probe))
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'sympify' and node.args
                    and isinstance(node.args[0], ast.Constant)]
        assert literals == [expression]
        original_issue_binding = {'literal_expression_sha256': sha(expression.encode()),
                                  'exact_original_expression_matches_public_instruction': True,
                                  'original_issue_cases_in_frozen_probe': 5}
    else:
        assert 'a=FiniteSet(1,2);b=ProductSet(a,a);c=FiniteSet((1,1),(1,2),(2,1),(2,2))' in probe
        original_issue_binding = {'original_issue_cases_in_frozen_probe': 5,
                                  'original_issue_FiniteSet_and_ProductSet_example_retained': True}
    (OUT / (number + '-frozen-public-probe.py')).write_text(probe)
    instance_id = 'sympy__sympy-' + number
    target = {'target_id': task.task_id, 'instance_id': instance_id,
              'benchmark_id': 'swebench_verified', 'repository': task.repository,
              'base_commit': task.commit}
    images = {instance_id: {'image': original_workspace['image']}}
    image_evidence = inspect_locked_images([target], images, [])
    checkouts = OUT / number / 'checkouts'
    checkouts.mkdir(parents=True)
    clone_root = checkouts / task.task_id
    assert clone_root.resolve().is_relative_to(OUT)
    clone_argv = ['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', '--local',
                  str(original_root), str(clone_root)]
    clone = subprocess.run(clone_argv, capture_output=True, text=True, timeout=120)
    assert clone.returncode == 0, clone.stderr
    checkout_argv = ['git', '-C', str(clone_root), 'checkout', '--quiet', '--detach', task.commit]
    checkout = subprocess.run(checkout_argv, capture_output=True, text=True, timeout=120)
    assert checkout.returncode == 0, checkout.stderr
    factory, evidence = benchmark.prepare_checkouts([task], [target], images, checkouts, resume=False)
    workspace = factory(task)
    assert workspace.root.resolve().is_relative_to(OUT) and workspace.patch() == ''
    assert evidence[task.task_id]['initial_status'] == ''
    assert benchmark._valid_history_isolation_evidence(
        evidence[task.task_id]['history_isolation'], expected_commit=task.commit)
    patch_path = local / 'submission.diff'
    patch_raw = patch_path.read_bytes()
    assert sha(patch_raw) == submission['patch_sha256']
    assert patch_raw == (CENTRAL / name / 'execution/cells/C/submission.diff').read_bytes()
    observations = []
    for stage in ('BASE', 'NATIVE008_EXPOSED_C'):
        if stage != 'BASE':
            applied = subprocess.run(['git', '-C', str(workspace.root), 'apply', str(patch_path)],
                                     capture_output=True, text=True, timeout=120)
            assert applied.returncode == 0, applied.stderr
            assert sha(workspace.patch().encode()) == sha(patch_raw)
        before = sha(workspace.patch().encode())
        argv = ['/opt/miniconda3/envs/testbed/bin/python', '-c', probe]
        result = workspace.execute('run_command', {'argv': argv, 'timeout_seconds': 120})
        assert sha(workspace.patch().encode()) == before
        assert result['exit_code'] == 0 and not result['timed_out'] and not result['output_truncated']
        parsed = json.loads(result['stdout'])
        assert parsed['total'] == 12 and len(parsed['observations']) == 12
        observations.append({'stage': stage, 'checkout_patch_sha256': before,
                             'public_command': result, 'parsed_observations': parsed})
        print(json.dumps({'task': number, 'stage': stage, 'passed': parsed['passed'],
                          'total': parsed['total']}), flush=True)
    results.append({'task_id': task.task_id, 'native008_session': name + '/C',
                    'base_commit': task.commit, 'image': original_workspace['image'],
                    'image_evidence': image_evidence, 'new_checkout': str(workspace.root),
                    'source_original_checkout_read_only': str(original_root),
                    'clone_argv': clone_argv, 'checkout_argv': checkout_argv,
                    'checkout_preparation': evidence[task.task_id],
                    'public_task_sha256': sha(public_raw), 'probe_sha256': sha(probe.encode()),
                    'probe_source': probe, 'original_issue_binding': original_issue_binding,
                    'submission_patch_sha256': sha(patch_raw), 'observations': observations})
changed = [path for path, digest in protected.items() if sha(Path(path).read_bytes()) != digest]
assert not changed, changed
receipt = {'schema': 'skhynix/native010-public-replication/1.0',
           'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'role': 'SEPARATE_PUBLIC_DIAGNOSTIC_NOT_NATIVE010_SOLVER_MEMORY',
           'probe_source_receipt_sha256': sha(probe_raw),
           'model_calls': 0, 'solver_launches': 0, 'official_grader_calls': 0,
           'private_dataset_or_grader_payloads_read': False, 'network_fetches': 0,
           'protected_inputs_unchanged': True, 'protected_input_count': len(protected),
           'protected_input_sha256': protected, 'results': results,
           'limitations': ['Public semantic probe results do not identify remaining hidden assertions.',
                           'Diagnostic observations are not official solve rates or verified successful skills.']}
raw = (json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
(OUT / 'public-replication-results.json').write_bytes(raw)
with DEST.open('xb') as stream:
    stream.write(raw)
print(json.dumps({'receipt': str(DEST), 'sha256': sha(raw),
                  'protected_unchanged': len(protected)}), flush=True)
