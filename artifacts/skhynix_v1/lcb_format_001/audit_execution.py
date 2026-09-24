"""Read-only COMPLETE-run audit; export hashes, counts and flags, never payloads.

Run with the original Windows Python environment after the controller exits:
  python -B artifacts/skhynix_v1/lcb_format_001/audit_execution.py --root data/lcb_format_001/run-001
This calls only frozen read/validation functions, never initialize/run/prepare.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
EXPECTED_PROTOCOL_SHA256 = '6e7c52625d6043eedfcecf787859d7ad091a23528352253823825fd9ed742e65'
METRICS = ('submission_valid', 'candidate_same', 'fixed_candidate_success', 'anchor_valid')


class AuditError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise AuditError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() + b'\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


class Sources:
    def __init__(self):
        self.refs = {}

    def raw(self, path, expected=None):
        path = Path(path).resolve()
        raw = path.read_bytes()
        ref = {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
        if expected is not None:
            require(ref['sha256'] == expected['sha256'], 'REFERENCE_HASH_CHANGED')
            require('bytes' not in expected or ref['bytes'] == expected['bytes'], 'REFERENCE_SIZE_CHANGED')
            require('path' not in expected or Path(expected['path']).resolve() == path, 'REFERENCE_PATH_CHANGED')
        require(str(path) not in self.refs or self.refs[str(path)] == ref, 'SOURCE_CHANGED_DURING_AUDIT')
        self.refs[str(path)] = ref
        return raw

    def read(self, path, expected=None):
        return json.loads(self.raw(path, expected))

    def verify(self):
        for ref in list(self.refs.values()):
            self.raw(ref['path'], ref)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_schedule(protocol, results):
    ids = protocol['task_ids']
    require(len(ids) == len(set(ids)) == 24 and protocol['repeats'] == 3, 'COHORT_CHANGED')
    trials = protocol['trials']
    require(len(trials) == 144 and len({t['trial_id'] for t in trials}) == 144, 'TRIAL_COVERAGE_CHANGED')
    expected = {(task, repeat, arm) for task in ids for repeat in (1, 2, 3) for arm in ('KEEP', 'DROP')}
    require({(t['task_id'], t['repeat'], t['arm']) for t in trials} == expected, 'PAIRED_COVERAGE_CHANGED')
    require(results['status'] == 'COMPLETE' and results['planned'] == results['completed'] == 144, 'NOT_COMPLETE')
    require([r['trial_id'] for r in results['trials']] == [t['trial_id'] for t in trials], 'RESULT_ORDER_CHANGED')
    for ordinal, (trial, row) in enumerate(zip(trials, results['trials']), 1):
        require(all(row[k] == trial[k] for k in ('task_id', 'repeat', 'arm')), 'RESULT_IDENTITY_CHANGED')
        require(type(row['launch_ordinal']) is int and row['launch_ordinal'] == ordinal, 'RESULT_ORDINAL_CHANGED')
        require(all(row['metrics'][key] is None or type(row['metrics'][key]) is bool for key in METRICS), 'NONBOOLEAN_METRIC')
    balance = []
    for repeat in (1, 2, 3):
        rows = [t for t in trials if t['repeat'] == repeat]
        first = Counter()
        for index in range(0, len(rows), 2):
            left, right = rows[index:index + 2]
            require(left['task_id'] == right['task_id'] and left['arm'] != right['arm'], 'NONADJACENT_PAIR')
            first[left['arm']] += 1
        require(first == {'KEEP': 12, 'DROP': 12}, 'LAUNCH_ORDER_UNBALANCED')
        balance.append({'repeat': repeat, 'KEEP_first': first['KEEP'], 'DROP_first': first['DROP']})
    return balance


def event_request_evidence(raw, sealed_sha256):
    """Request hashes and event positions only; the broker claim stays primary."""
    starts, completions = [], []
    for line_no, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue  # The frozen runner separately counts malformed lines.
        if not isinstance(event, dict) or event.get('type') not in ('item.started', 'item.completed'):
            continue
        item = event.get('item', {})
        if not isinstance(item, dict) or (item.get('type'), item.get('server'), item.get('tool')) != ('mcp_tool_call', 'benchmark', 'action'):
            continue
        envelope = item.get('arguments')
        if isinstance(envelope, str):
            try:
                envelope = json.loads(envelope)
            except (ValueError, UnicodeError):
                envelope = None
        request = envelope['request'] if isinstance(envelope, dict) and set(envelope) == {'request'} else {}
        identity = item.get('id')
        row = {'line': line_no, 'event_sha256': sha(line), 'request_sha256': sha(canonical(request)),
               'item_id_sha256': sha(str(identity).encode()) if identity is not None else None}
        (starts if event['type'] == 'item.started' else completions).append(row)
    first_start = starts[0] if starts else None
    first_complete = completions[0] if completions else None
    start_match = first_start['request_sha256'] == sealed_sha256 if first_start and sealed_sha256 else None
    complete_match = first_complete['request_sha256'] == sealed_sha256 if first_complete and sealed_sha256 else None
    same_call = bool(first_start and first_complete and first_start['item_id_sha256'] is not None
                     and first_start['item_id_sha256'] == first_complete['item_id_sha256']
                     and first_start['line'] < first_complete['line'])
    confirmed = bool(sealed_sha256 and start_match is True and complete_match is True and same_call)
    return {'started_count': len(starts), 'completed_count': len(completions),
            'first_started': first_start, 'first_completed': first_complete,
            'sealed_matches_first_started': start_match, 'sealed_matches_first_completed': complete_match,
            'first_start_completion_same_invocation': same_call,
            'first_native_invocation_confirmed': confirmed,
            'sealed_request_present': sealed_sha256 is not None,
            'extra_benchmark_action': len(starts) > 1 or len(completions) > 1}


def check_packets(root, protocol, preparer, runner, sources):
    checkpoints = {r['task_id']: r for r in protocol['checkpoints']}
    require(len(checkpoints) == 24 and set(checkpoints) == set(protocol['task_ids']), 'CHECKPOINT_COVERAGE_CHANGED')
    rows = []
    for task in protocol['task_ids']:
        packets, prompts, histories, refs = {}, {}, {}, {}
        trials = [t for t in protocol['trials'] if t['task_id'] == task]
        for arm in ('KEEP', 'DROP'):
            copies = [t for t in trials if t['arm'] == arm]
            require(len(copies) == 3, 'REPEAT_COVERAGE_CHANGED')
            keys = ('packet_path', 'packet_sha256', 'prompt_path', 'prompt_sha256', 'history_path', 'history_sha256', 'candidate_sha256')
            require(all(all(t[k] == copies[0][k] for k in keys) for t in copies), 'REPEAT_INPUT_CHANGED')
            trial = copies[0]
            packet_path = runner.relative(root, trial['packet_path'])
            packet_raw = sources.raw(packet_path, {'sha256': trial['packet_sha256']})
            packets[arm] = json.loads(packet_raw)
            require(packet_raw == preparer.canonical(packets[arm]) + b'\n', 'PACKET_SERIALIZER_CHANGED')
            history_raw = sources.raw(runner.relative(root, trial['history_path']), {'sha256': trial['history_sha256']})
            histories[arm] = json.loads(history_raw)
            require(packets[arm]['public_history'] == histories[arm], 'PROMPT_VALIDATOR_HISTORY_CHANGED')
            require(packets[arm]['task_id'] == task, 'PACKET_TASK_CHANGED')
            require(sha(packets[arm]['current_candidate'].encode()) == trial['candidate_sha256'] == checkpoints[task]['candidate_sha256'], 'FIXED_CANDIDATE_CHANGED')
            require([h['step_no'] for h in histories[arm]] == checkpoints[task]['history_ids'], 'CHECKPOINT_HISTORY_CHANGED')
            prompt_path = runner.relative(root, trial['prompt_path'])
            prompts[arm] = sources.raw(prompt_path, {'sha256': trial['prompt_sha256']})
            require(prompts[arm] == preparer.INSTRUCTIONS.encode() + preparer.canonical(packets[arm]) + b'\n', 'PROMPT_PACKET_CHANGED')
            refs[arm] = {'packet_reference': sources.refs[str(packet_path.resolve())],
                         'prompt_reference': sources.refs[str(prompt_path.resolve())], 'prompt_bytes': len(prompts[arm])}
        preparer.assert_pair(packets['KEEP'], packets['DROP'])
        require(histories['KEEP'] == histories['DROP'], 'PAIR_HISTORY_CHANGED')
        control = checkpoints[task]['no_memory_control']
        require(type(control) is bool and control == (not packets['KEEP']['context']['memory']), 'CONTROL_LABEL_CHANGED')
        if control:
            require(prompts['KEEP'] == prompts['DROP'], 'ZERO_MEMORY_CONTROL_DIFFERS')
        rows.append({'task_id': task, 'no_memory_control': control,
                     'candidate_sha256': checkpoints[task]['candidate_sha256'],
                     'history_ids': checkpoints[task]['history_ids'],
                     'pair_assertion_passed': True, 'identical_prompt_bytes': prompts['KEEP'] == prompts['DROP'], 'inputs': refs})
    return rows


def audit_run(root):
    root = Path(root).resolve()
    require(not (root / 'run.lock').exists(), 'CONTROLLER_STILL_ACTIVE')
    require((root / 'results.json').is_file(), 'COMPLETE_RESULTS_REQUIRED')
    sources = Sources()
    sources.raw(__file__)
    results = sources.read(root / 'results.json')
    require(results.get('status') == 'COMPLETE', 'NOT_COMPLETE')
    protocol = sources.read(root / 'protocol.json', {'sha256': EXPECTED_PROTOCOL_SHA256})
    protocol_ref = sources.refs[str(root / 'protocol.json')]
    require(results['protocol_reference'] == protocol_ref, 'RESULT_PROTOCOL_CHANGED')
    binding = sources.read(root / 'run-binding.json')
    require(binding['protocol_reference'] == protocol_ref, 'BINDING_PROTOCOL_CHANGED')
    balance = validate_schedule(protocol, results)
    for ref in protocol['source_references'] + binding['source_references']:
        sources.raw(ref['path'], ref)
    bound = {str(Path(r['path']).resolve()): r for r in binding['source_references']}
    for name in ('lcb_format_ablation_runner.py', 'lcb_format_ablation_prepare.py', 'trimem_lcb_memory.py'):
        require(str((REPO / 'scripts' / name).resolve()) in bound, 'VALIDATOR_NOT_BOUND')
    # Verify all pinned imports before executing any module import code.
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        runner = load_module('execution_audit_frozen_runner', REPO / 'scripts/lcb_format_ablation_runner.py')
        preparer = load_module('execution_audit_frozen_preparer', REPO / 'scripts/lcb_format_ablation_prepare.py')
        require(runner.load_protocol(root) == protocol, 'RUNNER_PROTOCOL_DISAGREEMENT')
        packet_rows = check_packets(root, protocol, preparer, runner, sources)
        rows, threads = [], []
        expected_folders = {t['trial_id'] for t in protocol['trials']}
        require({p.name for p in (root / 'trials').iterdir() if p.is_dir()} == expected_folders, 'EXTRA_OR_MISSING_TRIAL_FOLDER')
        for ordinal, (trial, result) in enumerate(zip(protocol['trials'], results['trials']), 1):
            folder = root / 'trials' / trial['trial_id']
            receipt = sources.read(folder / 'receipt.json', result['receipt_reference'])
            refs, _ = runner.inputs(root, protocol, trial)
            require(all(bound.get(r['path']) == r for r in refs), 'TRIAL_NOT_BOUND')
            require(runner.reuse(root, trial, protocol) == receipt, 'FROZEN_VALIDATOR_DISAGREEMENT')
            require(receipt['repeat'] == trial['repeat'] and receipt['launch_ordinal'] == ordinal, 'RECEIPT_ORDER_CHANGED')
            require(receipt['metrics'] == result['metrics'] and receipt['execution_infrastructure_error'] == result['execution_infrastructure_error'], 'RESULT_RECEIPT_CHANGED')
            for ref in receipt['input_references'] + receipt['output_references']:
                sources.raw(ref['path'], ref)
            launch = sources.read(folder / 'launch.json')
            require(launch['trial_id'] == trial['trial_id'] and launch['launch_ordinal'] == ordinal, 'LAUNCH_ORDER_CHANGED')
            require(launch['input_references'] == refs, 'LAUNCH_INPUT_CHANGED')
            for k in ('requested_model', 'reasoning_effort'):
                require(launch[k] == receipt[k] == protocol[k], 'MODEL_CHANGED')
            require(launch['stdin_prompt_sha256'] == trial['prompt_sha256'], 'STDIN_PROMPT_CHANGED')
            require(launch['command_sha256'] == sha(runner.canonical(runner.worker_command(root, protocol, trial, folder))), 'LAUNCH_COMMAND_CHANGED')
            action = None
            if receipt['action_reference'] is not None:
                action = sources.read(folder / 'action.json', receipt['action_reference'])
                require(action['first_action_only'] is True, 'ACTION_NOT_FIRST_ONLY')
                require(sources.raw(folder / 'first-action.claim') == b'FIRST_ACTION_RESERVED\n', 'FIRST_ACTION_CLAIM_CHANGED')
                raw = sources.read(action['raw_request_reference']['path'], action['raw_request_reference'])
                envelope = raw['mcp_arguments']
                projected = envelope['request'] if isinstance(envelope, dict) and set(envelope) == {'request'} else {}
                require(projected == raw['request'], 'BROKER_ENVELOPE_CHANGED')
            else:
                require(not (folder / 'action.json').exists(), 'UNREPORTED_SEALED_ACTION')
            raw_events = sources.raw(folder / 'events.jsonl')
            evidence = event_request_evidence(raw_events, action['request_sha256'] if action else None)
            native = receipt['native']
            require(evidence['started_count'] == len(native['benchmark_action_starts']) and evidence['completed_count'] == len(native['benchmark_action_calls']), 'EVENT_PROJECTION_DISAGREEMENT')
            confirmed_complete = bool(action and any(c['request_sha256'] == action['request_sha256'] for c in native['benchmark_action_calls']))
            require(receipt['first_action_event_confirmed'] == confirmed_complete, 'EVENT_CONFIRMATION_CHANGED')
            threads.extend(native['thread_id_hashes'])
            rows.append({'trial_id': trial['trial_id'], 'task_id': trial['task_id'], 'repeat': trial['repeat'], 'arm': trial['arm'],
                         'launch_ordinal': ordinal, 'receipt_reference': result['receipt_reference'], 'metrics': receipt['metrics'],
                         'native_thread_count': len(native['thread_id_hashes']), 'thread_id_hashes': native['thread_id_hashes'],
                         'execution_infrastructure_error': receipt['execution_infrastructure_error'],
                         'error_event_count': native['error_events'], 'malformed_event_lines': native['malformed_event_lines'],
                         'unexpected_tool_event_count': len(native['unexpected_tools']),
                         'unexpected_before_first_action': receipt['unexpected_native_tool_before_first_action'],
                         'first_action_evidence': evidence})
    finally:
        sys.dont_write_bytecode = old_bytecode
    require(not (root / 'run.lock').exists(), 'CONTROLLER_BECAME_ACTIVE')
    sources.verify()
    flags = {'extra_benchmark_action_trials': sum(r['first_action_evidence']['extra_benchmark_action'] for r in rows),
             'sealed_action_not_first_native_confirmed': sum(r['first_action_evidence']['sealed_request_present'] and not r['first_action_evidence']['first_native_invocation_confirmed'] for r in rows),
             'trials_without_sealed_action': sum(not r['first_action_evidence']['sealed_request_present'] for r in rows),
             'infrastructure_error_trials': sum(r['execution_infrastructure_error'] for r in rows),
             'unexpected_tool_trials': sum(r['unexpected_tool_event_count'] > 0 for r in rows),
             'trials_without_exactly_one_native_thread': sum(r['native_thread_count'] != 1 for r in rows),
             'duplicate_native_thread_hashes': len(threads) - len(set(threads))}
    return {'schema': 'lcb-format-execution-audit/1',
            'audit_status': 'PASS' if not any(flags.values()) else 'PROVENANCE_VALID_WITH_EXECUTION_FLAGS',
            'created_at': datetime.now(timezone.utc).isoformat(), 'protocol_reference': protocol_ref,
            'results_reference': sources.refs[str(root / 'results.json')], 'source_and_input_hashes_unchanged': True,
            'protocol_source_count': len(protocol['source_references']), 'bound_source_count': len(binding['source_references']),
            'verified_reference_count': len(sources.refs), 'task_count': 24, 'trial_count': 144,
            'frozen_runner_receipts_revalidated': 144,
            'sealed_request_outcomes_recomputed': sum(r['first_action_evidence']['sealed_request_present'] for r in rows),
            'native_thread_count': len(threads),
            'new_model_calls': 0, 'new_grader_calls': 0, 'raw_payloads_exported': False,
            'provider_internal_request_count': None,
            'interpretation': 'First broker reservation remains primary. Native event order is separate corroboration; flags never rewrite the preregistered metrics. Launch order is not completion order. Provider-internal request counts are not observable.',
            'flags': flags, 'launch_order_balance': balance, 'paired_inputs': packet_rows, 'trials': rows,
            'verified_references': list(sources.refs.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('audit-001.json'))
    args = parser.parse_args()
    require(not args.output.exists(), 'AUDIT_OUTPUT_EXISTS')
    require(not args.output.resolve().is_relative_to(args.root.resolve()), 'OUTPUT_INSIDE_RUN_FORBIDDEN')
    result = audit_run(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')
    print(json.dumps({k: result[k] for k in ('audit_status', 'task_count', 'trial_count', 'flags', 'verified_reference_count')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Exception strings may contain parsed payloads or filenames; do not leak them.
        print(json.dumps({'audit_status': 'FAIL', 'error_class': type(exc).__name__,
                          'error_code': str(exc) if isinstance(exc, AuditError) else 'VALIDATION_EXCEPTION'}))
        raise SystemExit(1) from None
