"""Independent read-only audit of native002 evidence; writes only audit JSON.

No solver, grader, Docker command, model API or mutable repository import is
used. SQLite opens immutable read-only URIs. Git commands inspect public commit
objects or existing checkouts only. Restricted artifacts are hashed, not logged.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

BASE = Path('/home/trimem-runner/skhynix-codex-002')
MANIFEST_SHA = 'e074530fb006834d95aee2c4aff23aeb90a18b99c9136eff91fa22aa3fd65814'
ARMS = {'A': 'NO_MEMORY', 'B': 'EXISTING_M2', 'C': 'SKHYNIX'}
TRAIN = {'swebench_verified--sympy__sympy-23262', 'swebench_verified--sympy__sympy-23413'}
EVAL = {'swebench_verified--sympy__sympy-' + str(n) for n in (23534, 23824, 23950)}
EXPECTED_OLD = {
    '/home/trimem-runner/skhynix-live-001/execution/report.json': 'a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0',
    '/home/trimem-runner/skhynix-live-002/execution/report.json': '1971c9ebb9f5f8e7cbb7188ca33c031725c009240184fbb7fecf84f140a0f784',
}

def canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

class Audit:
    def __init__(self):
        self.passed = 0
        self.failures = []
        self.incomplete = []
        self.cells = []
        self.sources = {}
        self.summaries = {}

    def check(self, condition, label):
        if condition:
            self.passed += 1
        else:
            self.failures.append(label)
        return condition

    def section(self, label, call):
        try:
            return call()
        except FileNotFoundError as exc:
            self.incomplete.append(label + ':' + Path(exc.filename or 'missing').name)
        except Exception as exc:
            # Exception values can embed task bodies or sensitive paths.
            self.failures.append(label + ':exception:' + type(exc).__name__)


def git(root, *args):
    env = {'PATH': os.environ.get('PATH', ''), 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_ATTR_NOSYSTEM': '1',
           'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_NO_LAZY_FETCH': '1',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'LC_ALL': 'C'}
    return subprocess.run(['git', '--no-replace-objects', '-c', 'core.fsmonitor=false',
                           '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args],
                          capture_output=True, check=False, timeout=120, env=env)


def audit_manifest(a, base):
    path = base / 'supplemental-manifest.json'
    a.check(digest(path) == MANIFEST_SHA, 'manifest.fixed_raw_hash')
    value = read(path)
    train = {row['target_id'] for row in value['targets'] if row['role'] == 'TRAINING'}
    train.add(value['prior_training_target']['target_id'])
    evaluate = {row['target_id'] for row in value['targets'] if row['role'] == 'EVALUATION'}
    a.check(train == TRAIN and evaluate == EVAL and not train & evaluate, 'manifest.exact_disjoint_split')
    a.check([row['instance_id'] for row in value['targets']] == [
        'sympy__sympy-' + str(n) for n in (23413, 23534, 23824, 23950)], 'manifest.identity_order')
    history = Path(value['history_path'])
    a.check(len(value['ancestry']) == 7, 'manifest.seven_ancestry_pairs')
    for i, proof in enumerate(value['ancestry']):
        result = git(history, 'merge-base', '--is-ancestor', proof['source_base_commit'], proof['target_base_commit'])
        a.check(result.returncode == proof['returncode'] == 0, f'ancestry.{i}.actual_git')
        for side in ('source', 'target'):
            result = git(history, 'cat-file', 'commit', proof[side + '_base_commit'])
            match = re.search(rb'^committer .+ ([0-9]+) [+-][0-9]{4}$', result.stdout.split(b'\n\n', 1)[0], re.M)
            a.check(result.returncode == 0 and match is not None and int(match.group(1)) ==
                    proof[side + '_commit_unix_seconds'], f'ancestry.{i}.{side}.timestamp')
        a.check(proof['source_commit_unix_seconds'] < proof['target_commit_unix_seconds'], f'ancestry.{i}.order')
    # Only identity columns are used to reproduce selection. Entire selected
    # rows are subsequently hashed opaquely, never included in the audit output.
    import pyarrow.parquet as pq
    spec = value['dataset']
    cache = Path('/opt/trimem-rehearsals/e932-preflight/datasets')
    parquet = cache / spec['benchmark_id'] / spec['dataset_revision'] / Path(spec['path']).name
    a.check(parquet.stat().st_size == spec['bytes'] and digest(parquet) == spec['sha256'], 'dataset.pinned_parquet')
    root = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
    excluded = set()
    for entry in value['excluded_manifests']:
        source = root / entry['path']
        a.check(digest(source) == entry['raw_sha256'], 'original_manifest.' + source.name)
        excluded.update(row['instance_id'] for row in read(source)['targets'])
    identities = pq.read_table(parquet, columns=['instance_id', 'repo']).to_pylist()
    selected = sorted((row['instance_id'] for row in identities if row['repo'] == 'sympy/sympy'
                       and row['instance_id'] not in excluded and int(row['instance_id'].rsplit('-', 1)[1]) > 23262),
                      key=lambda item: int(item.rsplit('-', 1)[1]))[:4]
    a.check(selected == [row['instance_id'] for row in value['targets']], 'dataset.identity_only_selection_reproduced')
    wanted = {row['instance_id']: row for row in value['targets']}
    for row in pq.read_table(parquet).to_pylist():
        if row['instance_id'] in wanted:
            target = wanted[row['instance_id']]
            a.check(sha(canon(row)) == target['source_row_sha256'] and row['base_commit'] == target['base_commit'],
                    'dataset.selected_opaque_row.' + row['instance_id'])
    a.summaries['manifest'] = {'sha256': MANIFEST_SHA, 'ancestry_pairs': 7, 'identity_only_selection': True}
    return value


def audit_plan(a, run):
    plan = read(run / 'plan.json')
    plan_sha = sha(canon(plan))
    a.check((run / 'plan.sha256').read_text().strip() == plan_sha, 'plan.hash.' + run.parent.name)
    source = run.parent / 'source'
    for relative, expected in plan['source_hashes'].items():
        a.check(digest(source / relative) == expected, 'source.' + run.parent.name + '.' + relative)
    a.sources[str(run)] = {'files': len(plan['source_hashes']), 'plan_sha256': plan_sha,
                          'source_set_sha256': sha(canon(plan['source_hashes']))}
    a.check(plan['requested_solver_model'] == 'gpt-6-astra', 'plan.model.' + run.parent.name)
    a.check(plan['cells'] == ARMS and plan['limits'] == {'repository_actions': 120, 'wall_seconds': 1200,
             'memory_injections': 3, 'memory_bytes': 12000}, 'plan.equal_limits.' + run.parent.name)
    a.check(plan.get('codex_tokens_and_cost') is None and plan.get('separate_model_api_calls') == 0,
            'plan.no_direct_api_and_unknown_native_cost.' + run.parent.name)
    for key in ('supplemental_manifest', 'frozen_memory_bank'):
        binding = plan.get(key)
        if binding:
            a.check(digest(binding['path']) == binding['sha256'], 'plan.frozen_input.' + run.parent.name + '.' + key)
    return plan


def restricted_hashes(a, value, root, label):
    if isinstance(value, dict):
        if value.get('access') == 'RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS' and {'path', 'sha256', 'bytes'} <= value.keys():
            path = (root / value['path']).resolve()
            if not path.exists():
                # Gateways retain restricted evidence in their invocation
                # directory; reports use paths relative to that directory.
                matches = [candidate for candidate in root.rglob(Path(value['path']).name)
                           if candidate.as_posix().endswith('/' + value['path'])]
                matches = [candidate for candidate in matches if candidate.stat().st_size == value['bytes']
                           and digest(candidate) == value['sha256']]
                if matches:
                    path = matches[0].resolve()
            safe = root.resolve() in path.parents
            a.check(safe, label + '.restricted_path_boundary')
            if safe:
                a.check(path.stat().st_size == value['bytes'] and digest(path) == value['sha256'], label + '.restricted_hash')
        for item in value.values():
            restricted_hashes(a, item, root, label)
    elif isinstance(value, list):
        for item in value:
            restricted_hashes(a, item, root, label)


def audit_cell(a, run, cell, plan, bank=None, launch=None):
    root = run / 'cells' / cell
    label = run.parent.name + '.' + cell
    result, submission, state = [read(root / name) for name in ('public-result.json', 'submission.json', 'state.json')]
    patch = (root / 'submission.diff').read_bytes()
    plan_sha = sha(canon(plan))
    for kind, receipt in [('result', result), ('submission', submission)]:
        a.check(receipt.get('cell') == cell and receipt.get('arm') == ARMS[cell]
                and receipt.get('target_id') == plan['public_task']['task_id']
                and receipt.get('plan_sha256') == plan_sha
                and receipt.get('experiment_id', plan['experiment_id']) == plan['experiment_id'], label + '.' + kind + '.identity')
        a.check(receipt.get('patch_sha256') == sha(patch) and receipt.get('patch_utf8_bytes') == len(patch), label + '.' + kind + '.patch')
    a.check(result.get('official') is True and result.get('grader_status') == 'success'
            and type(result.get('resolved')) is bool, label + '.official_status')
    a.check(state.get('status') == 'SUBMITTED' and not state.get('pending'), label + '.sealed_state')
    tail, events = '0' * 64, []
    for sequence, raw in enumerate((root / 'tool-events.jsonl').read_bytes().splitlines(), 1):
        event = json.loads(raw)
        retained = event.pop('sha256')
        a.check(event['sequence'] == sequence and event['previous_sha256'] == tail and sha(canon(event)) == retained,
                label + f'.event.{sequence}.hash_chain')
        tail = retained
        events.append(event)
    a.check(all(item.get('actions') == len(events) for item in (state, submission, result)) and
            state['tail_sha256'] == result['tool_event_tail_sha256'] == tail, label + '.event_totals')
    a.check(len(events) <= 120 and result['wall_seconds'] <= 1200, label + '.action_wall_limits')
    a.check(submission['agent_completed'] == result['agent_completed'], label + '.completion_agrees')
    if result['agent_completed']:
        a.check(events[-1]['request'].get('op') == 'submit' and events[-1]['result'].get('ok') is True and
                events[-1]['result']['result'].get('patch_sha256') == sha(patch), label + '.final_submit')
    private_path = root / 'grader-private.json'
    private = read(private_path)
    meta = private['report']['_trimem']
    a.check(digest(private_path) == result['grader_private_sha256'], label + '.grader_receipt_hash')
    a.check(private['resolved'] == meta['scientific_resolved'] == meta['official_final_report_resolved'] == result['resolved'],
            label + '.official_resolution_agrees')
    a.check(meta['harness_revision'] == '7a21e05772954cc81471ae19d56f436cecf43c54'
            and meta['source_row_sha256'] == plan['target']['source_row_sha256']
            and meta['dataset_revision'] == plan['target']['dataset_revision'], label + '.grader_pinned_inputs')
    a.check(meta['execution_contract']['submitted_patch_sha256'] == result['grader_patch_sha256'], label + '.grader_submitted_patch')
    image = next(item for item in meta['image_evidence'] if item['role'] == 'TARGET')
    a.check(image['image'] == result['container_digest'] and image['observed'] == [image['expected']]
            and image['inspect_exit_code'] == 0, label + '.official_image_digest')
    official_root = run / 'environment'
    restricted_hashes(a, meta, official_root, label)
    memories = [e['result']['result'] for e in events if e['request'].get('op') == 'recall' and e['result'].get('ok')]
    injections = {item['memory_id']: item for memory in memories for item in memory.get('injections', [])}
    for memory in memories:
        a.check(memory.get('model_api_calls') == 0 and memory.get('native_context_replacement') is False,
                label + '.memory.no_model_no_l0')
    for item in injections.values():
        raw = item['exact_text'].encode()
        a.check(item['sha256'] == sha(raw) and item['byte_count'] == len(raw), label + '.memory.exact_injection_hash')
    a.check(result['memory_queries'] == len(memories) and result['memory_injections'] == len(injections)
            and result['memory_bytes'] == sum(row['byte_count'] for row in injections.values()), label + '.memory.total_receipts')
    a.check(len(injections) <= 3 and result['memory_bytes'] <= 12000 and (cell != 'A' or not injections), label + '.memory.bounds')
    checkpoint = read(root / 'memory-private/checkpoint.json')
    a.check(checkpoint['sha256'] == sha(canon(checkpoint['state'])), label + '.memory.checkpoint')
    ledger = checkpoint['state']['controller'].get('ledger', [])
    a.check(len(ledger) == len(injections) and sum(row['byte_count'] for row in ledger) == result['memory_bytes'],
            label + '.memory.persisted_budget')
    commands = [e for e in events if e['request'].get('name') == 'run_command']
    public_tests = []
    for event in commands:
        if not event['result'].get('ok'):
            continue
        output = event['result']['result']
        text = str(output.get('stdout', '')) + '\n' + str(output.get('stderr', ''))
        passed = re.findall(r'\b(\d+) passed\b', text)
        if passed:
            public_tests.append({'broker_sequence': event['sequence'], 'passed': int(passed[-1]),
                                 'exit_code': output.get('exit_code'), 'output_sha256': sha(canon(output))})
    a.check(result['command_count'] == len(commands), label + '.public_command_count')
    a.check(result.get('codex_tokens_and_cost') is None and result.get('separate_model_api_calls') == 0,
            label + '.no_direct_api_unknown_native_cost')
    if bank is not None:
        a.check(checkpoint['state']['binding']['frozen_bank_sha256'] == digest(BASE / 'learned-bank.json'), label + '.frozen_bank_binding')
        valid_texts = {row['content'] for row in bank['records']}
        if cell == 'B':
            a.check(all(item['exact_text'] in valid_texts for item in injections.values()), label + '.m2.exact_learned_injections')
        a.check(submission['started_at'] >= (BASE / 'learned-bank.json').stat().st_mtime
                and submission['started_at'] >= (BASE / 'batch-plan.json').stat().st_mtime,
                label + '.bank_and_batch_mtime_before_first_action')
        if launch is not None:
            a.check(submission['started_at'] >= launch['frozen_at_unix_seconds'], label + '.explicit_launch_before_first_action')
    a.cells.append({'run': str(run), 'cell': cell, 'target_id': result['target_id'], 'resolved': result['resolved'],
                    'actions': len(events), 'tool_errors': sum(not e['result'].get('ok') for e in events),
                    'memory_queries': len(memories), 'memory_injections': len(injections), 'memory_bytes': result['memory_bytes'],
                    'patch_sha256': sha(patch), 'public_tests': public_tests, 'started_at': submission['started_at']})
    return result


def sqlite_records(a, path, label):
    before = digest(path)
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute('SELECT * FROM memory_records')]
        relations = connection.execute('SELECT COUNT(*) FROM knowledge_relations').fetchone()[0]
        supports = connection.execute('SELECT COUNT(*) FROM skill_support').fetchone()[0]
    a.check(before == digest(path), label + '.sqlite_unchanged_by_read')
    for row in rows:
        row['decoded'] = json.loads(row['payload'])
        a.check(row['content_hash'] == 'sha256:' + sha(canon(row['decoded'])), label + '.sqlite_payload_hash')
    return rows, relations, supports


def audit_bank(a, base, batch):
    path = base / 'learned-bank.json'
    bank = read(path)
    a.check(digest(path) == batch['contract']['frozen_memory_bank']['sha256'], 'bank.frozen_hash')
    a.check(set(bank['training_task_ids']) == TRAIN and set(bank['evaluation_task_ids']) == EVAL,
            'bank.disjoint_exact_split')
    a.check(bank['cold_start'] is False and bank['gate_b']['verified_skill_count'] == 0
            and bank['gate_b']['status'] == 'NOT_PROMOTED' and bank['evaluation_private_episode_count'] == 0
            and bank['knowledge_relation_count'] == 0 and bank['online_learning'] is False, 'bank.honest_l1_l3_boundaries')
    gate = bank['gate_a']
    private = path.with_name(gate['private_store_filename'])
    a.check(digest(private) == gate['private_store_sha256'], 'bank.gate_a_private_hash')
    rows, relations, supports = sqlite_records(a, private, 'bank.gate_a')
    a.check(len(rows) == gate['episode_count'] == len(gate['episodes']) == 2 and
            all(row['kind'] == 'episode' for row in rows) and relations == supports == 0, 'bank.two_private_gate_a_no_skills')
    actual_episodes = {row['record_id']: row['content_hash'] for row in rows}
    a.check(actual_episodes == {row['episode_id']: row['content_hash'] for row in gate['episodes']}, 'bank.gate_a_episode_id_hash')
    for record in bank['records']:
        raw = record['content'].encode()
        a.check(record['content_sha256'] == sha(raw) and record['content_bytes'] == len(raw)
                and record['source']['task_id'] in TRAIN and record['source']['resolved'] is True,
                'bank.shared_record_provenance')
    for episode in gate['episodes']:
        provenance = episode['source']
        root = Path(provenance['run_root']) / 'cells' / provenance['cell']
        a.check(provenance['cell'] == 'A' and provenance['arm'] == 'NO_MEMORY', 'bank.only_independent_training_a')
        for filename, field in [('public-result.json', 'public_result_sha256'), ('submission.diff', 'patch_sha256'),
                                ('grader-private.json', 'official_receipt_sha256')]:
            a.check(digest(root / filename) == provenance[field], 'bank.training_source.' + filename)
    a.summaries['bank'] = {'sha256': digest(path), 'shared_records': len(bank['records']),
                            'gate_a_episodes': gate['episode_count'], 'verified_skills': 0,
                            'gate_a_private_store_sha256': gate['private_store_sha256']}
    return bank


def audit_equal_views(a, run, bank):
    expected = {row['memory_id']: row['content'] for row in bank['records']}
    views = []
    for cell in ('B', 'C'):
        projection = read(run / 'cells' / cell / 'memory-private/historical-source-projection.json')
        views.append(projection['execution_views'])
        a.check(projection['execution_views'] == expected, run.parent.name + '.' + cell + '.exact_frozen_payload_projection')
    a.check(views[0] == views[1], run.parent.name + '.m2_sk_payload_bytes_equal')
    rows, relations, supports = sqlite_records(a, run / 'cells/C/memory-private/source-memory.sqlite3', run.parent.name + '.sk_store')
    a.check(all(row['kind'] == 'knowledge' for row in rows) and relations == supports == 0,
            run.parent.name + '.sk_no_l1_l3_edges')
    a.check(sorted(row['decoded']['content'] for row in rows) == sorted(expected.values()), run.parent.name + '.sk_canonical_payloads_equal_bank')


def main():
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    base = args.base.resolve()
    BASE = base
    a = Audit()
    a.section('manifest', lambda: audit_manifest(a, base))
    for path, expected in EXPECTED_OLD.items():
        a.section('old_report.' + Path(path).parts[-3], lambda path=path, expected=expected:
                  a.check(digest(path) == expected, 'old_report_unchanged.' + Path(path).parts[-3]))
    def whole_batch():
        batch = read(base / 'batch-plan.json')
        batch_sha = sha(canon(batch))
        a.check((base / 'batch-plan.json.sha256').read_text().strip() == batch_sha, 'batch.frozen_hash')
        a.check(batch['planned_targets'] == 3 and batch['planned_cells'] == 9, 'batch.fixed_three_by_three')
        a.check({row['target_id'] for row in batch['training']} == TRAIN and len(batch['training']) == 2
                and all(row['cell'] == 'A' for row in batch['training']), 'batch.only_two_training_a')
        a.check({row['target_id'] for row in batch['evaluation']} == EVAL and len(batch['evaluation']) == 3,
                'batch.evaluation_exact_three')
        bank = audit_bank(a, base, batch)
        launch = read(base / 'launch-contract.json')
        a.check(launch['batch_plan_sha256'] == batch_sha, 'launch.batch_hash')
        a.check(launch['frozen_at_unix_seconds'] >= (base / 'learned-bank.json').stat().st_mtime,
                'launch.frozen_after_bank')
        for entry in batch['training']:
            def training(entry=entry):
                run = Path(entry['run_root'])
                plan = audit_plan(a, run)
                a.check(sha(canon(plan)) == entry['plan_sha256'] and
                        digest(run / 'cells' / entry['cell'] / 'public-result.json') == entry['result_sha256'],
                        'batch.training_receipt_binding.' + entry['target_id'])
                audit_cell(a, run, entry['cell'], plan)
            a.section('training.' + entry['target_id'], training)
        common = None
        for entry in batch['evaluation']:
            run = Path(entry['run_root'])
            plan = a.section('eval.plan.' + entry['target_id'], lambda run=run: audit_plan(a, run))
            if plan is None:
                continue
            a.check(sha(canon(plan)) == entry['plan_sha256'], 'batch.eval_plan_hash.' + entry['target_id'])
            a.check(plan['source_hashes'] == batch['contract']['source_hashes'], 'batch.eval_source_hashes.' + entry['target_id'])
            if common is not None:
                a.check(plan['source_hashes'] == common, 'batch.eval_source_equal.' + entry['target_id'])
            common = plan['source_hashes']
            a.section('eval.views.' + entry['target_id'], lambda run=run: audit_equal_views(a, run, bank))
            for cell in ARMS:
                a.section('eval.cell.' + entry['target_id'] + '.' + cell,
                          lambda run=run, cell=cell, plan=plan: audit_cell(a, run, cell, plan, bank, launch))
        report = read(base / 'batch-report.json')
        a.check(report['status'] == 'COMPLETE' and report['completed_cells'] == 9
                and report['batch_plan_sha256'] == batch_sha, 'report.complete_nine')
        actual = [row for row in a.cells if row['target_id'] in EVAL]
        a.check(len(actual) == 9, 'audit.all_nine_eval_cells')
        if len(actual) == 9:
            for cell, arm in ARMS.items():
                selected = [row for row in actual if row['cell'] == cell]
                resolved = sum(row['resolved'] for row in selected)
                comparison = report['comparison'][arm]
                a.check(comparison['resolved'] == resolved and comparison['n'] == 3
                        and comparison['solve_rate'] == resolved / 3, 'report.recomputed_resolution.' + cell)
                for field in ('actions', 'memory_injections', 'memory_bytes'):
                    a.check(comparison[field] == sum(row[field] for row in selected), 'report.recomputed.' + cell + '.' + field)
            a.summaries['comparison'] = report['comparison']
        a.check(report.get('codex_tokens_and_cost') is None and report.get('separate_model_api_calls') == 0,
                'report.no_direct_api_unknown_native_cost')
        a.summaries['batch_plan_sha256'] = batch_sha
        a.summaries['batch_report_sha256'] = digest(base / 'batch-report.json')
    a.section('batch', whole_batch)
    value = {'schema': 'skhynix/native002-independent-audit/1.0',
             'status': 'FAIL' if a.failures else 'INCOMPLETE' if a.incomplete else 'PASS_FINAL',
             'checked_at_unix_seconds': time.time(), 'checks_passed': a.passed,
             'checks_failed': len(a.failures), 'failures': a.failures, 'incomplete': a.incomplete,
             'sources': a.sources, 'cells': a.cells, **a.summaries,
             'audit_helper_sha256': digest(Path(__file__)),
             'audit_execution': {'model_api_calls': 0, 'solver_runs': 0, 'grader_runs': 0, 'container_runs': 0,
                                 'repository_source_mutations': 0, 'sqlite_mode': 'ro,immutable'},
             'limitations': ['Native host-tool access is restricted by protocol, not OS-denied.',
                             'Requested model is Astra; immutable model snapshot is not independently attested.',
                             'Exact native token usage and cost are unavailable, not zero.',
                             'Filesystem and launch timestamps are local evidence, not a signed clock.',
                             'Training base ancestry does not prove native patches were merged upstream.',
                             'Three deterministic SymPy targets do not establish population-level or causal memory gains.',
                             'L3 skills remain zero; the audit does not establish full PDF architecture effectiveness.']}
    output = args.output or base / 'audit.json'
    output.write_bytes(canon(value) + b'\n')
    print(json.dumps({'status': value['status'], 'checks_passed': a.passed, 'checks_failed': len(a.failures),
                      'incomplete': a.incomplete, 'output': str(output)}))
    return 0 if value['status'] == 'PASS_FINAL' else 1


if __name__ == '__main__':
    raise SystemExit(main())
