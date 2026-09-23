"""Publish metadata-only Luna pilot analysis after COMPLETE; no model/grader calls.

Default: python -B artifacts/skhynix_v1/lcb_002/pilot-analysis-source-001.py
Use --check-only for a read-only validation. Existing outputs must be identical.
CSV uses literal null for unavailable outcomes, distinct from false.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / 'configs/skhynix_v1/lcb_001_public_split.json').is_file())
ARMS = ('TRAIN', 'OFF', 'ON')
BUDGET_ERRORS = {'TaskTimeout', 'SessionBudgetExhausted'}
PROTOCOL_ERRORS = {'MissingSubmission', 'UnexpectedNativeTool', 'ActionCallBudgetExceeded'}
ARM_FIELDS = ('planned recorded submitted held generation_errors graded passed failed not_graded '
    'resolved_outcomes infrastructure_or_pending resolved_rate model_protocol_failures budget_exhausted '
    'pass_at_1 graded_pass_at_1_descriptive billing_cost solve_seconds public_tool_seconds grader_seconds '
    'public_test_runs public_infrastructure_errors sessions handoffs memory_injection_count '
    'memory_exposure_bytes captured capture_errors').split()


class AnalysisError(ValueError):
    pass


def need(value, code):
    if not value:
        raise AnalysisError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def effective(row):
    """Same frozen experiment policy; unknown/infra failures remain unresolved."""
    passed = row.get('passed')
    need(passed is None or type(passed) is bool, 'INVALID_PRIVATE_VERDICT')
    if type(passed) is bool:
        need(row.get('grade_status') == 'GRADED', 'VERDICT_WITHOUT_GRADED_STATUS')
        return passed, 'SOLVED' if passed else 'WRONG_SOLUTION'
    need(row.get('grade_status') != 'GRADED', 'GRADED_WITHOUT_VERDICT')
    if row.get('status') == 'GENERATION_ERROR':
        if row.get('error_type') in BUDGET_ERRORS:
            return False, 'BUDGET_EXHAUSTED'
        if row.get('error_type') in PROTOCOL_ERRORS:
            return False, 'MODEL_PROTOCOL_FAILURE'
    return None, 'PENDING_GRADING' if row.get('grade_status') == 'PENDING' else 'INFRASTRUCTURE_UNRESOLVED'


def paired_stats(pairs):
    observed = [(off, on) for off, on in pairs if type(off) is bool and type(on) is bool]
    gains = sum(on and not off for off, on in observed)
    losses = sum(off and not on for off, on in observed)
    discordant = gains + losses
    p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1)) / 2**discordant) if observed else None
    complete = len(observed) == len(pairs)
    return {'planned': len(pairs), 'completed': len(observed), 'pending': len(pairs) - len(observed),
        'off_fail_on_pass': gains, 'off_pass_on_fail': losses,
        'delta': (gains - losses) / len(pairs) if complete and pairs else None,
        'paired_complete_delta_descriptive': (gains - losses) / len(observed) if observed else None,
        'exact_mcnemar_two_sided_p': p,
        'test_scope': 'ALL_PLANNED_PAIRS' if complete else 'AVAILABLE_PAIRS_ONLY_DESCRIPTIVE'}


def summarize_cells(summary, split):
    ids = {'TRAIN': split['train_pilot_ids'], 'OFF': split['pilot_ids'], 'ON': split['pilot_ids']}
    cells = summary['cells']
    lookup = {(x['task_id'], x['arm']): x for x in cells}
    need(len(lookup) == len(cells), 'DUPLICATE_CELL')
    need(set(lookup) == {(identity, arm) for arm, values in ids.items() for identity in values}, 'CELL_ENROLLMENT_DIFFERS')
    by_arm = {}
    for arm in ARMS:
        rows = [lookup[identity, arm] for identity in ids[arm]]
        statuses = [effective(row) for row in rows]
        for row, (resolved, outcome) in zip(rows, statuses):
            need(row.get('resolved') is resolved and row.get('outcome') == outcome, 'RECORDED_OUTCOME_DIFFERS')
        graded = sum(type(row.get('passed')) is bool for row in rows)
        passed = sum(row.get('passed') is True for row in rows)
        known = sum(type(resolved) is bool for resolved, _ in statuses)
        solved = sum(resolved is True for resolved, _ in statuses)
        calculated = {'planned': len(rows), 'recorded': len(rows), 'graded': graded, 'passed': passed,
            'failed': graded - passed, 'not_graded': len(rows) - graded,
            'resolved_outcomes': known, 'infrastructure_or_pending': len(rows) - known,
            'resolved_rate': solved / len(rows) if known == len(rows) else None,
            'pass_at_1': passed / len(rows) if graded == len(rows) else None,
            'model_protocol_failures': sum(outcome == 'MODEL_PROTOCOL_FAILURE' for _, outcome in statuses),
            'budget_exhausted': sum(outcome == 'BUDGET_EXHAUSTED' for _, outcome in statuses)}
        original = summary['arms'][arm]
        need(all(original.get(k) == v for k, v in calculated.items()), 'ARM_COUNTS_DIFFER')
        safe = {k: original[k] for k in ARM_FIELDS if k in original}
        need(all(value is None or type(value) in (int, float) for value in safe.values()), 'NONNUMERIC_ARM_METADATA')
        for key in ('tokens', 'memory_injections_by_kind'):
            safe[key] = dict(original.get(key, {}))
            need(all(type(value) is int and value >= 0 for value in safe[key].values()), 'INVALID_COUNTER_METADATA')
        times = [row['wall_seconds'] for row in rows if type(row.get('wall_seconds')) in (int, float)]
        need(all(math.isfinite(value) and value >= 0 for value in times), 'INVALID_DURATION')
        safe.update(resolved_passed=solved, resolved_failed=known - solved, unresolved=len(rows) - known,
            timed_cells=len(times), mean_solve_seconds=statistics.mean(times) if times else None,
            median_solve_seconds=statistics.median(times) if times else None,
            max_solve_seconds=max(times) if times else None)
        by_arm[arm] = safe
    descriptors = {row['task_id']: row for row in split['task_descriptors']}
    pairs = []
    for identity in ids['OFF']:
        off, on = lookup[identity, 'OFF'], lookup[identity, 'ON']
        left, right = effective(off)[0], effective(on)[0]
        graded_left, graded_right = off.get('passed'), on.get('passed')
        delta = int(right) - int(left) if type(left) is bool and type(right) is bool else None
        grade_delta = int(graded_right) - int(graded_left) if type(graded_left) is bool and type(graded_right) is bool else None
        pairs.append({'task_id': identity, 'difficulty': descriptors[identity]['difficulty'],
            'off_resolved': left, 'on_resolved': right, 'off_passed': graded_left, 'on_passed': graded_right,
            'off_outcome': effective(off)[1], 'on_outcome': effective(on)[1],
            'off_grade_status': off.get('grade_status'), 'on_grade_status': on.get('grade_status'),
            'off_seconds': off.get('wall_seconds'), 'on_seconds': on.get('wall_seconds'),
            'on_memory_injections': on.get('memory_injection_count', 0), 'delta': delta, 'graded_delta': grade_delta})
    graded = paired_stats([(row['off_passed'], row['on_passed']) for row in pairs])
    resolved = paired_stats([(row['off_resolved'], row['on_resolved']) for row in pairs])
    need(all(summary['paired'].get(k) == graded[k] for k in ('planned', 'completed', 'pending', 'delta', 'off_fail_on_pass', 'off_pass_on_fail')), 'GRADED_PAIRS_DIFFER')
    need(all(summary['effective_paired'].get(k) == resolved[k] for k in ('planned', 'completed', 'pending', 'delta')), 'RESOLVED_PAIRS_DIFFER')
    return by_arm, pairs, graded, resolved


def load_run(run_root, config_path):
    run_root, config_path = Path(run_root).resolve(), Path(config_path).resolve()
    summary_path = run_root / 'summary.json'
    summary = read(summary_path)
    need(summary.get('status') == 'COMPLETE', 'PILOT_NOT_COMPLETE_NO_FINAL_OUTPUT')
    config, frozen = read(config_path), read(run_root / 'frozen-inputs.json')
    split_path = ROOT / config['split_path']
    need(reference(split_path)['sha256'] == config['split_sha256'], 'SPLIT_HASH_CHANGED')
    split = read(split_path)
    need(frozen['enrollment'] == {'train': split['train_pilot_ids'], 'valid': split['pilot_ids']}, 'FROZEN_ENROLLMENT_DIFFERS')
    need(len(split['train_pilot_ids']) == len(split['pilot_ids']) == 24, 'PILOT_SIZE_DIFFERS')
    need(summary['experiment_id'] == config['experiment_id'] == frozen['experiment_id'], 'EXPERIMENT_ID_DIFFERS')
    need(frozen['model'] == config['requested_model'] and frozen['reasoning_effort'] == config['reasoning_effort'], 'MODEL_ID_DIFFERS')
    for path in (config_path, split_path):
        current = reference(path)
        need(any(Path(ref['path']).resolve() == path.resolve() and ref['sha256'] == current['sha256'] for ref in frozen['references']), 'FROZEN_INPUT_CHANGED')
    for ref in frozen['implementation']:
        need(reference(ref['path'])['sha256'] == ref['sha256'], 'FROZEN_IMPLEMENTATION_CHANGED')
    need(summary.get('test_partition_model_calls') == 0 and summary.get('hidden_feedback_to_model') is False, 'TEST_OR_HIDDEN_FEEDBACK_SCOPE_CHANGED')
    bank_path = run_root / 'frozen-bank.json'
    need(Path(summary['bank']['path']).resolve() == bank_path and reference(bank_path)['sha256'] == summary['bank']['sha256'], 'BANK_BINDING_CHANGED')
    bank = read(bank_path)
    need(bank['layer_counts'] == summary['bank']['layer_counts'] and bank['frozen'] is True and bank['evaluation_writes'] is False, 'BANK_POLICY_CHANGED')
    arms, pairs, graded, resolved = summarize_cells(summary, split)
    need(all(arms[arm]['unresolved'] == 0 for arm in ARMS), 'COMPLETE_CONTAINS_UNRESOLVED_OUTCOMES')
    return {'run_root': run_root, 'config': config, 'frozen': frozen, 'summary': summary, 'split': split,
        'summary_reference': reference(summary_path), 'config_reference': reference(config_path),
        'arms': arms, 'pairs': pairs, 'graded_paired': graded, 'resolved_paired': resolved}


def analysis(run):
    summary, rows = run['summary'], run['pairs']
    return {'schema': 'trimem/lcb-pilot-analysis/2.0', 'status': 'COMPLETE', 'scope': 'VALIDATION_PILOT_NOT_FINAL_TEST',
        'model': run['frozen']['model'], 'reasoning_effort': run['frozen']['reasoning_effort'],
        'experiment_id': summary['experiment_id'], 'summary_sha256': run['summary_reference']['sha256'],
        'summary_reference': run['summary_reference'], 'config_reference': run['config_reference'],
        'split_sha256': run['config']['split_sha256'], 'arms': run['arms'],
        'paired': run['graded_paired'], 'effective_paired': run['resolved_paired'],
        'exact_mcnemar_two_sided_p': run['resolved_paired']['exact_mcnemar_two_sided_p'],
        'mcnemar_outcome': 'EFFECTIVE_RESOLVED_NOT_PRIVATE_GRADED_ONLY',
        'off_fail_on_pass_ids': [row['task_id'] for row in rows if row['delta'] == 1],
        'off_pass_on_fail_ids': [row['task_id'] for row in rows if row['delta'] == -1],
        'exposed_target_count': sum(row['on_memory_injections'] > 0 for row in rows),
        'no_exposure_target_count': sum(row['on_memory_injections'] == 0 for row in rows),
        'test_model_calls': summary['test_partition_model_calls'], 'hidden_feedback_to_model': False,
        'manager_seconds': summary['manager_seconds_this_invocation'],
        'bank': {k: summary['bank'][k] for k in ('sha256', 'layer_counts')},
        'notes': ['Budget/protocol failures are resolved=false with passed=null unless privately graded.',
            'Infrastructure/pending outcomes stay null; COMPLETE publication rejects them.',
            'Same observed validation pilot: exploratory comparison, not untouched test or leaderboard single-generation accuracy.']}


def comparison(current, baseline):
    for key in ('split_sha256', 'limits', 'workers', 'private_grading', 'reasoning_effort', 'transport', 'infrastructure_control_excluded_train_ids'):
        need(current['config'][key] == baseline['config'][key], 'COMPARISON_PROTOCOL_DIFFERS')
    need(current['frozen']['enrollment'] == baseline['frozen']['enrollment'], 'COMPARISON_ENROLLMENT_DIFFERS')
    need(current['frozen']['implementation'] == baseline['frozen']['implementation'], 'COMPARISON_IMPLEMENTATION_DIFFERS')
    if current['frozen']['model'] != baseline['frozen']['model']:
        need(current['summary']['bank']['sha256'] != baseline['summary']['bank']['sha256'], 'DIFFERENT_MODEL_REUSES_BANK')
    entries = []
    for run in (baseline, current):
        for arm in ARMS:
            entry = {'experiment_id': run['summary']['experiment_id'], 'model': run['frozen']['model'],
                'reasoning_effort': run['frozen']['reasoning_effort'], 'arm': arm,
                'bank_sha256': run['summary']['bank']['sha256'], **run['arms'][arm]}
            entries.append(entry)
    return {'schema': 'trimem/lcb-model-comparison/1.0', 'status': 'COMPLETE',
        'scope': 'DESCRIPTIVE_VALIDATION_PILOT_COMPARISON_SEPARATE_MODEL_TRAIN_BANKS',
        'same_enrollment_budgets_workers_grader_and_implementation': True,
        'summary_references': [baseline['summary_reference'], current['summary_reference']],
        'rows': entries, 'model_calls': 0, 'grader_calls': 0}


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: 'null' if value is None else str(value).lower() if type(value) is bool else value for key, value in row.items()})
    return stream.getvalue().encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, default=ROOT / 'data/skhynix_lcb_002/pilot-001')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_002_luna_pilot.json')
    parser.add_argument('--compare-run', type=Path, default=ROOT / 'data/skhynix_lcb_001/pilot-001')
    parser.add_argument('--compare-config', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_001_pilot.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    current = load_run(args.run_root, args.config)
    baseline = load_run(args.compare_run, args.compare_config)
    reports = {'pilot-results-001.json': analysis(current), 'model-comparison-001.json': comparison(current, baseline)}
    blobs = {name: (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode() for name, value in reports.items()}
    blobs['pilot-paired-results-001.csv'] = csv_bytes(current['pairs'])
    for run in (current, baseline):
        need(reference(run['summary_reference']['path']) == run['summary_reference'], 'SUMMARY_CHANGED_DURING_ANALYSIS')
    if not args.check_only:
        for name, raw in blobs.items():
            path = HERE / name
            need(not path.exists() or path.read_bytes() == raw, 'EXISTING_ANALYSIS_DIFFERS')
        for name, raw in blobs.items():
            path = HERE / name
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(raw)
    print(json.dumps({'status': 'PASS', 'mode': 'CHECK_ONLY' if args.check_only else 'PUBLISHED',
        'model': current['frozen']['model'], 'planned_valid_pairs': len(current['pairs']),
        'effective_paired': current['resolved_paired'], 'private_graded_paired': current['graded_paired'],
        'outputs': [] if args.check_only else [reference(HERE / name) for name in blobs]}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except AnalysisError as exc:
        print(json.dumps({'status': 'NOT_PUBLISHED', 'reason': str(exc)}))
        raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({'status': 'NOT_PUBLISHED', 'error_type': type(exc).__name__}))
        raise SystemExit(2)
