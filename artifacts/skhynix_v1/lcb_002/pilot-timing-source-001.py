"""Supplement final pilot metadata; reads only results JSON and paired CSV.

No model, grader, run directory, prompt, candidate, test, or memory access.
Existing output must be byte-identical. All timing comparisons are descriptive.
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
SCHEMA = 'trimem/lcb-pilot-timing-supplement/1.0'
OUTCOMES = ('SOLVED', 'WRONG_SOLUTION', 'MODEL_PROTOCOL_FAILURE', 'BUDGET_EXHAUSTED',
            'INFRASTRUCTURE_UNRESOLVED', 'PENDING_GRADING')
CSV_FIELDS = ('task_id difficulty off_resolved on_resolved off_passed on_passed '
              'off_outcome on_outcome off_grade_status on_grade_status off_seconds '
              'on_seconds on_memory_injections delta graded_delta').split()


class TimingError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise TimingError(code)


def reference(path, raw):
    return {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def numeric(value, *, nullable=True, signed=False):
    need((nullable and value is None) or (type(value) in (int, float) and
         math.isfinite(value) and (signed or value >= 0)), 'INVALID_NUMERIC_METADATA')
    return value


def duration(text):
    if text == 'null':
        return None
    try:
        return numeric(float(text), nullable=False)
    except (TypeError, ValueError):
        raise TimingError('INVALID_DURATION') from None


def boolean(text):
    need(text in ('true', 'false', 'null'), 'INVALID_OUTCOME_BOOLEAN')
    return {'true': True, 'false': False, 'null': None}[text]


def delta(text):
    need(text in ('-1', '0', '1', 'null'), 'INVALID_PAIR_DELTA')
    return None if text == 'null' else int(text)


def parse_pairs(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''))
    need(reader.fieldnames == CSV_FIELDS, 'PAIRED_CSV_COLUMNS_DIFFER')
    pairs, seen = [], set()
    for source in reader:
        need(None not in source and all(value is not None for value in source.values()), 'MALFORMED_CSV_ROW')
        identity = source['task_id']
        need(bool(identity.strip()) and len(identity) <= 500 and identity not in seen, 'INVALID_OR_DUPLICATE_TASK_ID')
        seen.add(identity)
        need(source['difficulty'] in ('easy', 'medium', 'hard'), 'INVALID_DIFFICULTY')
        row = {'task_id': identity, 'difficulty': source['difficulty']}
        for arm in ('off', 'on'):
            resolved, passed = boolean(source[arm + '_resolved']), boolean(source[arm + '_passed'])
            outcome, grade = source[arm + '_outcome'], source[arm + '_grade_status']
            need(outcome in OUTCOMES, 'INVALID_OUTCOME_CATEGORY')
            expected = {'SOLVED': True, 'WRONG_SOLUTION': False, 'MODEL_PROTOCOL_FAILURE': False,
                        'BUDGET_EXHAUSTED': False, 'INFRASTRUCTURE_UNRESOLVED': None, 'PENDING_GRADING': None}[outcome]
            need(resolved is expected, 'RESOLVED_CATEGORY_DIFFERS')
            if outcome in ('SOLVED', 'WRONG_SOLUTION'):
                need(passed is expected and grade == 'GRADED', 'PRIVATE_VERDICT_DIFFERS')
            else:
                need(passed is None and grade != 'GRADED', 'UNAVAILABLE_PRIVATE_VERDICT_DIFFERS')
            need((grade == 'PENDING') == (outcome == 'PENDING_GRADING'), 'PENDING_CATEGORY_DIFFERS')
            row.update({arm + '_resolved': resolved, arm + '_passed': passed, arm + '_outcome': outcome,
                        arm + '_seconds': duration(source[arm + '_seconds'])})
        need(source['on_memory_injections'].isdigit(), 'INVALID_EXPOSURE_COUNT')
        row['on_memory_injections'] = int(source['on_memory_injections'])
        for key, outcome_key in (('delta', 'resolved'), ('graded_delta', 'passed')):
            left, right = row['off_' + outcome_key], row['on_' + outcome_key]
            expected = int(right) - int(left) if type(left) is bool and type(right) is bool else None
            need(delta(source[key]) == expected, 'PAIR_DELTA_DIFFERS')
        pairs.append(row)
    need(bool(pairs), 'EMPTY_PAIRED_CSV')
    return pairs


def timing(values, *, signed=False):
    values = [numeric(value, signed=signed) for value in values]
    known = [value for value in values if value is not None]
    return {'attempts': len(values), 'timed_attempts': len(known), 'missing_time_attempts': len(values) - len(known),
            'mean_seconds': statistics.mean(known) if known else None,
            'median_seconds': statistics.median(known) if known else None,
            'sum_observed_seconds': sum(known) if known else None,
            'total_seconds': sum(known) if known and len(known) == len(values) else None,
            'mean_median_denominator': 'TIMED_ATTEMPTS_ONLY'}


def arm_group(pairs, arm):
    prefix = arm.lower()
    count = lambda outcome: sum(row[prefix + '_outcome'] == outcome for row in pairs)
    durations = lambda rows: timing([row[prefix + '_seconds'] for row in rows])
    by_resolved = {label: [row for row in pairs if row[prefix + '_resolved'] is value]
                   for label, value in (('true', True), ('false', False), ('null', None))}
    return {'arm': arm, 'attempts': len(pairs), 'resolved_true': len(by_resolved['true']),
            'resolved_false': len(by_resolved['false']), 'resolved_null': len(by_resolved['null']),
            'private_passed': sum(row[prefix + '_passed'] is True for row in pairs),
            'private_failed': sum(row[prefix + '_passed'] is False for row in pairs),
            'private_unavailable': sum(row[prefix + '_passed'] is None for row in pairs),
            'outcomes': {outcome: count(outcome) for outcome in OUTCOMES},
            'all_attempt_timing': durations(pairs),
            'timing_by_resolved': {label: durations(rows) for label, rows in by_resolved.items()},
            'timing_by_outcome': {outcome: durations([row for row in pairs if row[prefix + '_outcome'] == outcome])
                                  for outcome in OUTCOMES}}


def equal_number(actual, expected):
    numeric(actual)
    need((actual is None and expected is None) or (actual is not None and expected is not None and
         math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9)), 'AGGREGATE_TIMING_DIFFERS')


def check_aggregate(report, pairs, arm):
    summary = report['arms'][arm]
    value = arm_group(pairs, arm)
    counts = {'planned': value['attempts'], 'recorded': value['attempts'],
              'graded': value['private_passed'] + value['private_failed'], 'passed': value['private_passed'],
              'failed': value['private_failed'], 'not_graded': value['private_unavailable'],
              'resolved_outcomes': value['resolved_true'] + value['resolved_false'],
              'infrastructure_or_pending': value['resolved_null'], 'resolved_passed': value['resolved_true'],
              'resolved_failed': value['resolved_false'], 'unresolved': value['resolved_null'],
              'model_protocol_failures': value['outcomes']['MODEL_PROTOCOL_FAILURE'],
              'budget_exhausted': value['outcomes']['BUDGET_EXHAUSTED'],
              'timed_cells': value['all_attempt_timing']['timed_attempts']}
    for key, expected in counts.items():
        need(type(summary.get(key)) is int and summary[key] == expected, 'AGGREGATE_COUNTS_DIFFER')
    for key, metric in (('mean_solve_seconds', 'mean_seconds'), ('median_solve_seconds', 'median_seconds')):
        equal_number(summary.get(key), value['all_attempt_timing'][metric])
    known = [row[arm.lower() + '_seconds'] for row in pairs if row[arm.lower() + '_seconds'] is not None]
    equal_number(summary.get('max_solve_seconds'), max(known) if known else None)
    if 'solve_seconds' in summary:
        equal_number(summary['solve_seconds'], sum(known))
    return value


def check_paired(report, pairs, key, column):
    observed = [(row['off_' + column], row['on_' + column]) for row in pairs
                if type(row['off_' + column]) is bool and type(row['on_' + column]) is bool]
    gains = sum(not left and right for left, right in observed)
    losses = sum(left and not right for left, right in observed)
    for field, expected in {'planned': len(pairs), 'completed': len(observed), 'pending': len(pairs) - len(observed),
                            'off_fail_on_pass': gains, 'off_pass_on_fail': losses}.items():
        need(type(report[key].get(field)) is int and report[key][field] == expected, 'AGGREGATE_PAIRS_DIFFER')
    expected_delta = (gains - losses) / len(pairs) if len(observed) == len(pairs) else None
    actual = report[key].get('delta')
    numeric(actual, signed=True)
    need(actual == expected_delta, 'AGGREGATE_PAIR_DELTA_DIFFERS')


def both_solved(pairs):
    selected = [row for row in pairs if row['off_resolved'] is True and row['on_resolved'] is True]
    timed = [row for row in selected if row['off_seconds'] is not None and row['on_seconds'] is not None]
    details = [{'task_id': row['task_id'], 'difficulty': row['difficulty'],
                'off_seconds': row['off_seconds'], 'on_seconds': row['on_seconds'],
                'on_minus_off_seconds': row['on_seconds'] - row['off_seconds']
                if row['off_seconds'] is not None and row['on_seconds'] is not None else None} for row in selected]
    return {'both_solved_pairs': len(selected), 'pairs_with_both_times': len(timed),
            'pairs_missing_either_time': len(selected) - len(timed),
            'task_ids': [row['task_id'] for row in selected], 'pairs': details,
            'off_timing_on_joint_timed_subset': timing([row['off_seconds'] for row in timed]),
            'on_timing_on_joint_timed_subset': timing([row['on_seconds'] for row in timed]),
            'on_minus_off_seconds': timing([row['on_minus_off_seconds'] for row in details], signed=True),
            'interpretation': 'DESCRIPTIVE_SELECTED_SUBSET_ONLY_NOT_CAUSAL_SPEEDUP'}


def supplement(report, pairs):
    need(report.get('schema') == 'trimem/lcb-pilot-analysis/2.0' and report.get('status') == 'COMPLETE',
         'FINAL_COMPLETE_ANALYSIS_REQUIRED')
    need(report.get('scope') == 'VALIDATION_PILOT_NOT_FINAL_TEST' and report.get('test_model_calls') == 0 and
         report.get('hidden_feedback_to_model') is False, 'ANALYSIS_SCOPE_DIFFERS')
    arms = {arm: check_aggregate(report, pairs, arm) for arm in ('OFF', 'ON')}
    check_paired(report, pairs, 'paired', 'passed')
    check_paired(report, pairs, 'effective_paired', 'resolved')
    for field, expected_delta in (('off_fail_on_pass_ids', 1), ('off_pass_on_fail_ids', -1)):
        expected = [row['task_id'] for row in pairs if type(row['off_resolved']) is bool and
                    type(row['on_resolved']) is bool and int(row['on_resolved']) - int(row['off_resolved']) == expected_delta]
        need(report.get(field) == expected, 'DISCORDANT_TASK_IDS_DIFFER')
    exposed = sum(row['on_memory_injections'] > 0 for row in pairs)
    need(report.get('exposed_target_count') == exposed and report.get('no_exposure_target_count') == len(pairs) - exposed,
         'EXPOSURE_COUNTS_DIFFER')
    train = report['arms']['TRAIN']
    train_keys = ('planned', 'recorded', 'graded', 'passed', 'failed', 'not_graded', 'resolved_passed', 'resolved_failed',
                  'unresolved', 'model_protocol_failures', 'budget_exhausted', 'timed_cells', 'mean_solve_seconds',
                  'median_solve_seconds', 'max_solve_seconds', 'solve_seconds')
    train_metadata = {key: numeric(train[key]) for key in train_keys if key in train}
    need(train_metadata.get('planned') == train_metadata.get('recorded'), 'TRAIN_DENOMINATOR_DIFFERS')
    return {'schema': SCHEMA, 'status': 'COMPLETE', 'scope': 'DESCRIPTIVE_VALIDATION_PILOT_METADATA_ONLY',
            'experiment_id': report['experiment_id'], 'model': report['model'], 'reasoning_effort': report['reasoning_effort'],
            'split_sha256': report['split_sha256'], 'bank_sha256': report['bank']['sha256'],
            'valid_pairs': len(pairs), 'arms': arms,
            'by_difficulty': {level: {arm: arm_group([row for row in pairs if row['difficulty'] == level], arm)
                                     for arm in ('OFF', 'ON')} for level in ('easy', 'medium', 'hard')},
            'both_solved_paired_timing': both_solved(pairs),
            'train': {'reported_aggregate_metadata': train_metadata, 'per_difficulty': None, 'timing_by_resolved': None,
                      'reason': 'TRAIN_CELL_DIFFICULTY_AND_TIMING_NOT_AVAILABLE_IN_THE_TWO_ALLOWED_INPUTS'},
            'model_calls': 0, 'grader_calls': 0,
            'notes': ['Times are native solve wall_seconds; they are not end-to-end runtime or grader time.',
                      'Null outcomes and missing times remain unavailable; no missing observation becomes zero or false.',
                      'Protocol/budget failures are effective failures, separate from privately graded wrong solutions.',
                      'Means and medians use explicitly counted timed attempts, including failed attempts where grouped.',
                      'Both-solved comparisons condition on both outcomes; they do not estimate causal memory speedup.',
                      'Same-machine concurrency, task order, native service latency and censoring can affect durations.',
                      'Input hashes bind these two reports. Original frozen enrollment and per-cell provenance are not re-audited.']}


def load(results_path, pairs_path):
    results_path, pairs_path = Path(results_path).resolve(), Path(pairs_path).resolve()
    need(results_path != pairs_path, 'INPUT_PATHS_OVERLAP')
    results_raw = results_path.read_bytes()
    report = json.loads(results_raw)
    need(report.get('status') == 'COMPLETE', 'FINAL_COMPLETE_ANALYSIS_REQUIRED')
    pairs_raw = pairs_path.read_bytes()
    result = supplement(report, parse_pairs(pairs_raw))
    inputs = [reference(results_path, results_raw), reference(pairs_path, pairs_raw)]
    need(results_path.read_bytes() == results_raw and pairs_path.read_bytes() == pairs_raw, 'INPUT_CHANGED_DURING_ANALYSIS')
    result['input_references'] = inputs
    result['helper_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def publish(result, output):
    output = Path(output).resolve()
    need(output not in {Path(row['path']) for row in result['input_references']} and output != Path(__file__).resolve(),
         'OUTPUT_OVERLAPS_INPUT')
    for row in result['input_references']:
        raw = Path(row['path']).read_bytes()
        need(reference(row['path'], raw) == row, 'INPUT_CHANGED_BEFORE_PUBLICATION')
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if output.exists():
        need(output.read_bytes() == raw, 'EXISTING_SUPPLEMENT_DIFFERS')
    else:
        with output.open('xb') as stream:
            stream.write(raw)
    return reference(output, raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=HERE / 'pilot-results-001.json')
    parser.add_argument('--pairs', type=Path, default=HERE / 'pilot-paired-results-001.csv')
    parser.add_argument('--output', type=Path, default=HERE / 'pilot-timing-outcomes-001.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = load(args.results, args.pairs)
        output = None if args.check_only else publish(result, args.output)
        print(json.dumps({'status': 'PASS', 'mode': 'CHECK_ONLY' if args.check_only else 'PUBLISHED',
                          'valid_pairs': result['valid_pairs'],
                          'both_solved_pairs': result['both_solved_paired_timing']['both_solved_pairs'], 'output': output}))
        return 0
    except TimingError as exc:
        print(json.dumps({'status': 'NOT_PUBLISHED', 'reason': str(exc)}))
        return 2
    except Exception as exc:
        print(json.dumps({'status': 'NOT_PUBLISHED', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
