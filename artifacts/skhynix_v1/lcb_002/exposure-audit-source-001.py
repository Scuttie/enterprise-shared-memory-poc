"""Read-only metadata audit; never emits memory text, candidates or test bodies."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / 'configs/skhynix_v1/lcb_001_public_split.json').is_file())


class AuditError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise AuditError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def reference(path, raw=None):
    path = Path(path).resolve()
    raw = path.read_bytes() if raw is None else raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


def read(path):
    return json.loads(Path(path).read_bytes())


def bound(root, ref):
    root = Path(root).resolve()
    relative = Path(ref['path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'BAD_BANK_REFERENCE')
    path = (root / relative).resolve()
    require(path.is_relative_to(root), 'BANK_REFERENCE_ESCAPE')
    actual = reference(path)
    require(actual['sha256'] == ref['sha256'] and ('bytes' not in ref or actual['bytes'] == ref['bytes']), 'BANK_REFERENCE_CHANGED')
    return path


def stable_state(path):
    for _ in range(5):
        raw = path.read_bytes()
        value = json.loads(raw)
        if path.read_bytes() == raw:
            return value, raw
    raise AuditError('STATE_CHANGED_DURING_READ')


def captured_training_rows(summary, planned_ids):
    rows = [row for row in summary['cells'] if row['arm'] == 'TRAIN']
    require(len(rows) == len(planned_ids) and {row['task_id'] for row in rows} == set(planned_ids), 'TRAIN_SUMMARY_ENROLLMENT_CHANGED')
    captured = {row['task_id']: row for row in rows if row.get('capture_status') == 'CAPTURED'}
    require(len(captured) == summary['arms']['TRAIN']['captured'], 'TRAIN_SUMMARY_CAPTURE_COUNT_CHANGED')
    require(all(row['status'] == 'SUBMITTED' for row in captured.values()), 'CAPTURED_WITHOUT_SUBMISSION')
    return captured


def run(args):
    started = time.monotonic()
    repo, pilot = args.repo.resolve(), args.pilot.resolve()
    config_path = args.config.resolve()
    config = read(config_path)
    split_path = (repo / config['split_path']).resolve()
    require(reference(split_path)['sha256'] == config['split_sha256'], 'SPLIT_CHANGED')
    split = read(split_path)
    summary_path = pilot / 'summary.json'
    summary_ref = reference(summary_path)
    summary = read(summary_path)
    require(summary['status'] == 'COMPLETE', 'PILOT_NOT_COMPLETE')
    frozen = read(pilot / 'frozen-inputs.json')
    require(frozen['enrollment'] == {'train': split['train_pilot_ids'], 'valid': split['pilot_ids']}, 'FROZEN_ENROLLMENT_CHANGED')
    require(summary['experiment_id'] == frozen['experiment_id'] == config['experiment_id'], 'EXPERIMENT_ID_CHANGED')
    require(frozen['model'] == config['requested_model'] and frozen['reasoning_effort'] == config['reasoning_effort'], 'MODEL_ID_CHANGED')
    require(any(Path(ref['path']).resolve() == config_path and ref['sha256'] == reference(config_path)['sha256']
        for ref in frozen['references']), 'FROZEN_CONFIG_CHANGED')
    require(summary['test_partition_model_calls'] == 0 and summary['hidden_feedback_to_model'] is False, 'EVALUATION_SCOPE_CHANGED')
    bank_receipt = read(pilot / 'bank-receipt.json')
    bank_path = pilot / 'frozen-bank.json'
    bank_reference = reference(bank_path)
    require(bank_reference['sha256'] == bank_receipt['sha256'], 'BANK_MANIFEST_CHANGED')
    require(summary['bank']['sha256'] == bank_receipt['sha256'] and Path(summary['bank']['path']).resolve() == bank_path, 'SUMMARY_BANK_CHANGED')
    bank = read(bank_path)
    require(bank['frozen'] is True and bank['evaluation_writes'] is False, 'BANK_NOT_FROZEN')
    require(bank['layer_counts'] == bank_receipt['layer_counts'] == summary['bank']['layer_counts'], 'BANK_LAYER_COUNTS_CHANGED')
    bank_root = pilot / bank['data_directory']
    require(bank_root.resolve().parent == pilot, 'BAD_BANK_DIRECTORY')
    authority = bound(bank_root, bank['authority'])
    protected = [bank_reference, reference(pilot / 'bank-receipt.json'), reference(authority), summary_ref,
        reference(config_path), reference(split_path), reference(pilot / 'frozen-inputs.json')]
    for suffix in ('-wal', '-journal'):
        journal = Path(str(authority) + suffix)
        require(not journal.exists() or journal.stat().st_size == 0, 'BANK_ACTIVE_WRITE_JOURNAL')
    scope = {row['task_id']: row for row in bank['scope']['tasks']}
    train_ids, valid_ids = set(split['train_pilot_ids']), set(split['pilot_ids'])
    require(not train_ids.intersection(valid_ids), 'PARTITION_OVERLAP')
    expected_captures = captured_training_rows(summary, train_ids)
    sources, captured = {}, set()
    for ref in bank['catalog']['captures'].values():
        path = bound(bank_root, ref)
        protected.append(reference(path))
        envelope = read(path)
        capture, receipt = envelope['capture'], envelope['receipt']
        task = capture['task_public']
        task_id = task['task_id']
        require(task_id in train_ids and task['split'] == scope[task_id]['split'] == 'train', 'SOURCE_NOT_PILOT_TRAIN')
        require(task['family_id'] == scope[task_id]['family_id'], 'SOURCE_FAMILY_CHANGED')
        require(task_id not in captured, 'DUPLICATE_TRAIN_CAPTURE')
        require(task_id not in config['infrastructure_control_excluded_train_ids'], 'CONTROL_ENTERED_BANK')
        require(task_id in expected_captures, 'CAPTURE_ABSENT_FROM_TRAIN_SUMMARY')
        expected = expected_captures[task_id]
        require(capture['model_id'] == config['requested_model'], 'CAPTURE_MODEL_CHANGED')
        require(capture['contributor_id'] in expected['thread_ids'], 'CAPTURE_THREAD_CHANGED')
        require(digest(capture['final_code'].encode()) == expected['candidate_sha256'], 'CAPTURE_CANDIDATE_CHANGED')
        captured.add(task_id)
        for memory_id, kind in [(receipt['episode_id'], 'EPISODIC')] + [(key, 'REPOSITORY_SEMANTIC') for key in receipt['knowledge_ids']]:
            require(memory_id not in sources, 'DUPLICATE_MEMORY_ID')
            sources[memory_id] = {'source_task_id': task_id, 'source_family_id': task['family_id'],
                'kind': kind, 'capture_reference': reference(path),
                'expected_episode_hash': receipt['episode_content_hash'] if kind == 'EPISODIC' else None}
    require(captured == set(expected_captures), 'BANK_TRAIN_ENROLLMENT_CHANGED')
    require(bank['layer_counts']['training_tasks'] == len(captured) == bank['layer_counts']['L1_episodes'], 'BANK_CAPTURE_COUNT_CHANGED')
    for ref in bank['catalog']['observations'].values():
        protected.append(reference(bound(bank_root, ref)))
    require(not bank['catalog']['skills'] and bank['layer_counts']['L3_skills'] == 0, 'UNSUPPORTED_PROMOTED_SKILLS')
    with sqlite3.connect(authority.as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.row_factory = sqlite3.Row
        records = {row['record_id']: dict(row) for row in connection.execute('SELECT * FROM memory_records')}
    require(set(records) == set(sources), 'BANK_AUTHORITY_RECORD_SET_CHANGED')
    for identity, record in records.items():
        payload = json.loads(record['payload'])
        require(record['content_hash'] == 'sha256:' + digest(canonical(payload)), 'CANONICAL_MEMORY_HASH_CHANGED')
        require(not record['revoked'], 'REVOKED_MEMORY_SOURCE')
        source = sources[identity]
        require(record['org_id'] == bank['scope']['org_id'] and record['repository'] == bank['scope']['repository'], 'MEMORY_SCOPE_CHANGED')
        if source['kind'] == 'EPISODIC':
            evidence = payload['evidence']
            require(record['kind'] == 'episode' and evidence['task_id'] == source['source_task_id'], 'EPISODE_SOURCE_CHANGED')
            require(record['owner_user_id'] == bank['scope']['owner_user_id'], 'EPISODE_OWNER_CHANGED')
            require(record['content_hash'] == source['expected_episode_hash'], 'CAPTURE_EPISODE_HASH_CHANGED')
            view = {'layer': 'EPISODIC', 'subgoal': evidence['subgoal'], 'summary': evidence['summary'],
                'actions': evidence['actions'], 'source_outcome': 'passed' if evidence['succeeded'] else 'failed',
                'source_revision': evidence['revision'], 'verification_command': evidence['verification_command']}
        else:
            require(record['kind'] == 'knowledge' and json.loads(payload['content'])['source_task_id'] == source['source_task_id'], 'KNOWLEDGE_SOURCE_CHANGED')
            view = {'layer': 'REPOSITORY_SEMANTIC', 'title': payload['title'], 'content': payload['content'], 'revision': payload['revision']}
        source['view_sha256'] = digest(json.dumps(view, ensure_ascii=False, sort_keys=True).encode())
        source['content_hash'] = record['content_hash']

    targets, exposures = [], []
    summary_on = {row['task_id']: row for row in summary['cells'] if row['arm'] == 'ON'}
    require(set(summary_on) == valid_ids, 'ON_SUMMARY_ENROLLMENT_CHANGED')
    for identity in split['pilot_ids']:
        cell = pilot / 'cells' / ('valid-on-' + digest(identity.encode())[:20])
        path = cell / 'state.json'
        row = {'target_task_id': identity, 'target_family_id': scope[identity]['family_id'],
            'split': 'valid', 'state': 'NOT_STARTED', 'injection_count': 0}
        require(scope[identity]['split'] == 'valid', 'TARGET_NOT_VALID')
        if not path.exists():
            raise AuditError('COMPLETE_TARGET_STATE_MISSING')
        state, raw = stable_state(path)
        state_ref = reference(path, raw)
        task = state['task']
        require(state['arm'] == 'ON' and task['task_id'] == identity and task['split'] == 'valid', 'TARGET_STATE_CHANGED')
        require(task['family_id'] == scope[identity]['family_id'], 'TARGET_FAMILY_CHANGED')
        require(state['bank']['sha256'] == bank_reference['sha256'] and Path(state['bank']['path']).resolve() == bank_path, 'TARGET_BANK_CHANGED')
        items = state['memory_injections']
        require(len(items) == summary_on[identity]['memory_injection_count'], 'SUMMARY_INJECTION_COUNT_CHANGED')
        checkpoint = state['memory_checkpoint']
        if checkpoint:
            require(checkpoint['binding']['bank_sha256'] == bank_reference['sha256'] and checkpoint['binding']['task'] == scope[identity], 'CHECKPOINT_BINDING_CHANGED')
            require(checkpoint['controller']['ledger'] == items, 'LEDGER_CHECKPOINT_CHANGED')
        else:
            require(not items, 'MISSING_CHECKPOINT')
        nodes = {node['node_id'] for node in state['graph']['nodes']}
        receipt_path = cell / 'solve-receipt.json'
        row.update(state='IN_PROGRESS', state_reference=state_ref,
            finished=state['finished'], injection_count=len(items),
            current_active_node_id=state['graph']['active_node_id'],
            recall_decision_batches=len(state.get('memory_decisions', [])))
        if receipt_path.exists():
            receipt = read(receipt_path)
            require(receipt['state_sha256'] == state_ref['sha256'] and receipt['task_id'] == identity and receipt['arm'] == 'ON', 'TERMINAL_RECEIPT_CHANGED')
            require(receipt['memory_injection_count'] == len(items), 'TERMINAL_INJECTION_COUNT_CHANGED')
            row.update(state=receipt['status'], solve_receipt_reference=reference(receipt_path))
        for ordinal, item in enumerate(items):
            source = sources.get(item['memory_id'])
            require(source is not None and source['kind'] == item['kind'], 'UNBOUND_INJECTION')
            require(item['active_node_id'] in nodes, 'UNBOUND_ACTIVE_NODE')
            require(source['source_task_id'] != identity and source['source_family_id'] != task['family_id'], 'TARGET_SOURCE_ID_OR_FAMILY_OVERLAP')
            encoded = item['exact_text'].encode()
            require(digest(encoded) == item['sha256'] == source['view_sha256'] and len(encoded) == item['byte_count'], 'INJECTION_VIEW_CHANGED')
            require(item['memory_version'] == item['canonical_node_hash'] == source['content_hash'], 'INJECTION_SOURCE_HASH_CHANGED')
            require(isinstance(item['confidence'], (int, float)) and math.isfinite(item['confidence']), 'INVALID_SCORE')
            exposures.append({'target_task_id': identity, 'target_family_id': task['family_id'],
                'source_task_id': source['source_task_id'], 'source_family_id': source['source_family_id'],
                'kind': item['kind'], 'memory_id': item['memory_id'], 'active_node_id': item['active_node_id'],
                'injection_ordinal': ordinal, 'score': item['confidence'], 'score_field': 'confidence',
                'score_semantics': 'lexical relevance' if item['kind'] == 'EPISODIC' else 'repository PPR rank score',
                'injection_sha256': item['sha256'], 'canonical_memory_hash': source['content_hash'],
                'bank_snapshot_hash': item['graph_hash'], 'byte_count': item['byte_count'],
                'capture_reference': source['capture_reference'], 'target_state_reference': state_ref,
                'source_is_frozen_pilot_train': True, 'target_is_valid': True, 'different_task_and_family': True})
        targets.append(row)

    for ref in protected:
        require(reference(ref['path']) == ref, 'BANK_CHANGED_DURING_AUDIT')
    complete = sum(row['state'] in ('SUBMITTED', 'GENERATION_ERROR') for row in targets)
    require(complete == len(valid_ids), 'COMPLETE_TARGET_RECEIPT_MISSING')
    require(len(exposures) == summary['arms']['ON']['memory_injection_count'], 'SUMMARY_TOTAL_EXPOSURE_CHANGED')
    report = {'schema': 'trimem/lcb-exposure-audit/2.0', 'audit_status': 'PASS',
        'coverage': 'COMPLETE' if complete == len(valid_ids) else 'PARTIAL_LIVE_SNAPSHOT',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'helper_reference': reference(__file__),
        'bank_reference': bank_reference, 'bank_layer_counts': bank['layer_counts'],
        'config_reference': reference(config_path), 'summary_reference': summary_ref,
        'model': config['requested_model'], 'reasoning_effort': config['reasoning_effort'],
        'public_split_reference': reference(split_path), 'protected_reference_count': len(protected),
        'protected_bank_file_count': 3 + len(bank['catalog']['captures']) + len(bank['catalog']['observations']),
        'source_train_count': len(captured), 'planned_source_train_count': len(train_ids),
        'uncaptured_planned_train_count': len(train_ids) - len(captured),
        'summary_captured_train_count': summary['arms']['TRAIN']['captured'],
        'summary_train_generation_errors': summary['arms']['TRAIN']['generation_errors'],
        'summary_train_capture_errors': summary['arms']['TRAIN']['capture_errors'],
        'target_expected_count': len(valid_ids),
        'target_started_count': sum(row['state'] != 'NOT_STARTED' for row in targets),
        'target_terminal_count': complete, 'target_with_injections_count': sum(row['injection_count'] > 0 for row in targets),
        'terminal_targets_without_injections_count': sum(row['state'] in ('SUBMITTED', 'GENERATION_ERROR') and row['injection_count'] == 0 for row in targets),
        'injection_count': len(exposures), 'injections_by_kind': dict(Counter(row['kind'] for row in exposures)),
        'source_bank_membership_verified': True, 'target_valid_membership_verified': True,
        'different_source_target_ids_and_families_verified': True, 'bank_unchanged_before_after': True,
        'targets': targets, 'exposures': exposures,
        'limitations': ['Recorded injection ledger, not proof of causal model use or accuracy improvement.',
            'Per-cell stable snapshots; active experiment continues between cell reads.',
            'No injection can reflect ordinary abstention; no retrieval threshold was changed.'],
        'memory_text_or_candidate_or_task_or_test_content_in_report': False,
        'model_calls': 0, 'grader_calls': 0, 'retrieval_calls': 0,
        'live_state_or_bank_writes': 0, 'wall_seconds': time.monotonic() - started}
    if args.check_only:
        print(json.dumps({key: report[key] for key in ('audit_status', 'coverage', 'source_train_count',
            'uncaptured_planned_train_count', 'target_terminal_count', 'injection_count', 'injections_by_kind')}))
        return
    output = args.output.resolve()
    require(output.is_relative_to(HERE), 'OUTPUT_OUTSIDE_NEW_RUN_ARTIFACTS')
    if output.exists():
        previous = read(output)
        require(previous['bank_reference'] == bank_reference and previous['target_terminal_count'] <= complete, 'REPORT_UPDATE_NOT_MONOTONIC')
        previous_ref = reference(output)
        archive = Path(__file__).parent / 'lcb-exposure-audit-history' / (previous_ref['sha256'] + '.json')
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            with archive.open('xb') as stream:
                stream.write(output.read_bytes())
        report['previous_report_reference'] = reference(archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.json.tmp')
    temporary.write_bytes(canonical(report) + b'\n')
    os.replace(temporary, output)
    summary = {key: report[key] for key in ('audit_status', 'coverage', 'source_train_count', 'target_started_count',
        'target_terminal_count', 'target_with_injections_count', 'injection_count', 'injections_by_kind')}
    summary['report_reference'] = reference(output)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_002_luna_pilot.json')
    parser.add_argument('--pilot', type=Path, default=ROOT / 'data/skhynix_lcb_002/pilot-001')
    parser.add_argument('--output', type=Path, default=HERE / 'pilot-exposure-audit-001.json')
    parser.add_argument('--check-only', action='store_true')
    try:
        run(parser.parse_args())
    except AuditError as exc:
        print(json.dumps({'audit_status': 'FAIL', 'error_type': type(exc).__name__, 'error_code': str(exc)}))
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(json.dumps({'audit_status': 'FAIL', 'error_type': type(exc).__name__,
            'frames': [{'function': item.name, 'line': item.lineno} for item in traceback.extract_tb(exc.__traceback__)]}))
        sys.exit(1)
