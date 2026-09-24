"""Export metadata from a completed explicit-format paired LCB experiment.

No solver state, prompt, code, memory text, or private grader payload is decoded.
Referenced files are hashed as opaque bytes. The exporter never invokes a model
or grader and never writes inside the source experiment.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'lcb-explicit-format-results/1'
TOKENS = ('input_tokens', 'cached_input_tokens', 'output_tokens')


class ResultsError(ValueError):
    pass


def require(value, code):
    if not value:
        raise ResultsError(code)


def read(path):
    return json.loads(Path(path).read_bytes())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'


def reference(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def check(ref, expected=None):
    require(isinstance(ref, dict) and set(ref) >= {'path', 'sha256', 'bytes'}, 'INVALID_SOURCE_REFERENCE')
    path = Path(ref['path']).resolve()
    require(expected is None or path == Path(expected).resolve(), 'SOURCE_PATH_CHANGED')
    require(reference(path) == ref, 'SOURCE_BYTES_CHANGED')
    return path


@contextmanager
def inactive_manager(run_root):
    """Hold the existing manager lock without changing any original bytes."""
    path = Path(run_root) / 'experiment.lock'
    require(path.is_file() and path.stat().st_size >= 1, 'MANAGER_LOCK_MISSING')
    with path.open('rb') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ResultsError('MANAGER_STILL_ACTIVE') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'INVALID_MEASUREMENT')
    return value


def metric_counts(values):
    require(all(type(v) is bool or v is None for v in values), 'INVALID_BINARY_METRIC')
    passed, failed = sum(v is True for v in values), sum(v is False for v in values)
    total = len(values)
    return {'planned': total, 'successes': passed, 'failures': failed,
            'unresolved': total - passed - failed,
            'full_cohort_rate': passed / total if total and passed + failed == total else None,
            'successes_per_scheduled_cell': passed / total if total else None}


def paired_binary(pairs):
    complete = [(a, b) for a, b in pairs if type(a) is bool and type(b) is bool]
    gains = sum(not a and b for a, b in complete)
    losses = sum(a and not b for a, b in complete)
    discordant = gains + losses
    probability = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1)) / 2**discordant) if discordant else 1.0
    return {'planned_pairs': len(pairs), 'complete_pairs': len(complete),
            'both_success': sum(a and b for a, b in complete),
            'both_failure': sum(not a and not b for a, b in complete),
            'off_failure_on_success': gains, 'off_success_on_failure': losses,
            'delta_on_minus_off': (gains - losses) / len(pairs) if pairs and len(complete) == len(pairs) else None,
            'exact_mcnemar_two_sided_p': probability if len(complete) == len(pairs) else None,
            'inference_caveat': 'Exploratory paired statistic on one 24-task development cohort; no population or causal mechanism claim and no multiplicity correction.'}


def continuous(pairs):
    off, on = [a for a, _ in pairs], [b for _, b in pairs]
    delta = [b - a for a, b in pairs]
    return {'pairs': len(pairs), 'OFF_total': sum(off), 'ON_total': sum(on),
            'OFF_mean': statistics.mean(off) if off else None,
            'ON_mean': statistics.mean(on) if on else None,
            'paired_mean_ON_minus_OFF': statistics.mean(delta) if delta else None,
            'paired_median_ON_minus_OFF': statistics.median(delta) if delta else None,
            'interpretation': 'Recorded cumulative cell measurements; concurrent cell times are not experiment wall time.'}


def primary_value(row):
    if type(row.get('passed')) is bool:
        require(row['status'] == 'SUBMITTED' and row['grade_status'] == 'GRADED', 'PRIMARY_VERDICT_WITHOUT_ACCEPTED_GRADE')
        expected = row['passed']
    elif row['status'] == 'GENERATION_ERROR' and row.get('error_type') in (
            'TaskTimeout', 'SessionBudgetExhausted', 'MissingSubmission', 'UnexpectedNativeTool', 'ActionCallBudgetExceeded'):
        expected = False
    else:
        expected = None
    require(row.get('resolved') is expected, 'PRIMARY_EFFECTIVE_OUTCOME_CHANGED')
    return expected


def index_rows(rows, identities):
    index = {(r['task_id'], r['arm']): r for r in rows}
    require(len(rows) == len(index) == 48 and set(index) == {(identity, arm) for identity in identities for arm in ('OFF', 'ON')}, 'PAIRED_COHORT_CHANGED')
    return index


def analyze(summary, diagnostic, split):
    ids = split['pilot_ids']
    require(len(ids) == len(set(ids)) == 24, 'INVALID_VALID_IDS')
    primary = index_rows(summary['cells'], ids)
    auxiliary = index_rows(diagnostic['rows'], ids)
    descriptors = {row['task_id']: row for row in split['task_descriptors']}
    records = []
    for identity in ids:
        descriptor = descriptors[identity]
        require(descriptor['split'] == 'valid' and descriptor['difficulty'] in ('easy', 'medium', 'hard'), 'TARGET_METADATA_CHANGED')
        record = {'task_id': identity, 'difficulty': descriptor['difficulty']}
        for arm in ('OFF', 'ON'):
            row, diag = primary[identity, arm], auxiliary[identity, arm]
            submitted = row['status'] == 'SUBMITTED'
            verdict = primary_value(row)
            candidate = diag['diagnostic_passed']
            require(type(candidate) is bool or candidate is None, 'INVALID_DIAGNOSTIC_OUTCOME')
            require((type(candidate) is not bool or diag['diagnostic_grade_status'] == 'GRADED') and
                    (diag['selection_status'] != 'NOT_AVAILABLE' or candidate is None), 'DIAGNOSTIC_VERDICT_WITHOUT_GRADE')
            if submitted:
                require(diag['grade_source'] == 'PRIMARY_REUSED' and candidate is row['passed'] and
                        diag['candidate_sha256'] == row['candidate_sha256'], 'SUBMITTED_DIAGNOSTIC_DIFFERS')
            record[arm] = {'primary_success': verdict, 'submission_accepted': submitted,
                           'accepted_candidate_correct': row['passed'] if submitted else None,
                           'retained_candidate_correct': candidate,
                           'retained_candidate_available': diag['selection_status'] == 'SELECTED',
                           'retained_candidate_source': diag['selection_source'],
                           'generation_status': row['status'], 'grade_status': row['grade_status'],
                           'diagnostic_grade_status': diag['diagnostic_grade_status'],
                           'solve_seconds': number(row.get('wall_seconds', 0)),
                           'public_tool_seconds': number(row.get('tool_seconds', 0)),
                           'grader_seconds': number(row.get('grader_seconds', 0)),
                           'sessions': number(row.get('session_count', 0)),
                           'public_test_runs': number(row.get('public_test_runs', 0)),
                           'tool_actions': number(row.get('tool_actions', 0)),
                           'memory_injections': number(row.get('memory_injection_count', 0)),
                           'tokens': {key: number(row.get('tokens', {}).get(key, 0)) for key in TOKENS}}
        records.append(record)
    metrics = {}
    for metric in ('primary_success', 'submission_accepted', 'retained_candidate_correct'):
        metrics[metric] = {arm: metric_counts([r[arm][metric] for r in records]) for arm in ('OFF', 'ON')}
        metrics[metric]['paired'] = paired_binary([(r['OFF'][metric], r['ON'][metric]) for r in records])
    for arm in ('OFF', 'ON'):
        unavailable = sum(not r[arm]['retained_candidate_available'] for r in records)
        metrics['retained_candidate_correct'][arm].update(
            candidate_not_available=unavailable,
            infrastructure_unresolved=metrics['retained_candidate_correct'][arm]['unresolved'] - unavailable)
    accepted = {}
    for arm in ('OFF', 'ON'):
        rows = [r[arm] for r in records if r[arm]['submission_accepted']]
        accepted[arm] = metric_counts([r['accepted_candidate_correct'] for r in rows])
        accepted[arm]['denominator_label'] = 'accepted_submissions_only_not_all_24_tasks'
    timing = {key: continuous([(r['OFF'][key], r['ON'][key]) for r in records])
              for key in ('solve_seconds', 'public_tool_seconds', 'grader_seconds', 'sessions', 'tool_actions', 'public_test_runs')}
    token_stats = {key: continuous([(r['OFF']['tokens'][key], r['ON']['tokens'][key]) for r in records]) for key in TOKENS}
    by_difficulty = {}
    for difficulty in ('easy', 'medium', 'hard'):
        selected = [r for r in records if r['difficulty'] == difficulty]
        by_difficulty[difficulty] = {'pairs': len(selected), **{
            metric: {arm: metric_counts([r[arm][metric] for r in selected]) for arm in ('OFF', 'ON')}
            for metric in metrics},
            'solve_seconds': continuous([(r['OFF']['solve_seconds'], r['ON']['solve_seconds']) for r in selected]),
            'tokens': {key: continuous([(r['OFF']['tokens'][key], r['ON']['tokens'][key]) for r in selected]) for key in TOKENS}}
    for arm in ('OFF', 'ON'):
        require(summary['arms'][arm]['planned'] == 24 and summary['arms'][arm]['passed'] == metrics['primary_success'][arm]['successes'] and
                summary['arms'][arm]['submitted'] == metrics['submission_accepted'][arm]['successes'], 'SUMMARY_COUNTS_DIFFER')
        require(diagnostic['arms'][arm]['planned'] == 24 and diagnostic['arms'][arm]['passed'] == metrics['retained_candidate_correct'][arm]['successes'], 'DIAGNOSTIC_COUNTS_DIFFER')
    return {'metrics': metrics, 'accepted_submission_correctness': accepted, 'paired_timing': timing,
            'paired_tokens': token_stats, 'difficulty': by_difficulty, 'task_pairs': records}


def export(run_root, config_path, output):
    run_root, config_path, output = Path(run_root).resolve(), Path(config_path).resolve(), Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(run_root), 'OUTPUT_MUST_BE_FRESH_AND_OUTSIDE_SOURCE')
    with inactive_manager(run_root):
        summary_ref, frozen_ref = reference(run_root / 'summary.json'), reference(run_root / 'frozen-inputs.json')
        summary, frozen, config = read(summary_ref['path']), read(frozen_ref['path']), read(config_path)
        require(summary.get('schema') == 'lcb-explicit-format-experiment/1' and summary.get('status') == 'COMPLETE' and
                summary.get('phase') == 'COMPLETE' and summary.get('diagnostic_status') == 'COMPLETE', 'RUN_NOT_COMPLETE')
        require(summary.get('new_training_cells') == 0 and frozen.get('model') == 'gpt-5.6-luna' and
                frozen.get('reasoning_effort') == 'low', 'EXPERIMENT_IDENTITY_CHANGED')
        require(reference(config_path) in frozen['references'], 'CONFIG_NOT_FROZEN')
        split_path = Path(config['split_path'])
        split_path = split_path if split_path.is_absolute() else ROOT / split_path
        split_ref = reference(split_path)
        require(split_ref['sha256'] == config['split_sha256'] and split_ref in frozen['references'], 'SPLIT_NOT_FROZEN')
        split = read(split_path)
        require(frozen['enrollment']['valid'] == split['pilot_ids'], 'ENROLLED_VALID_CHANGED')
        collection = read(check(summary['collection_reference'], run_root / 'collection.json'))
        require(collection['status'] == 'COMPLETE' and collection['completed_cells'] == collection['planned_cells'] == 48 and
                collection['frozen_inputs_reference'] == frozen_ref, 'COLLECTION_NOT_SEALED')
        diag_ref = summary['diagnostic_summary_reference']
        diagnostic = read(check(diag_ref, run_root / 'diagnostic-summary.json'))
        require(diagnostic['status'] == 'COMPLETE' and diagnostic['collection_reference'] == summary['collection_reference'] and
                diagnostic['selection_reference'] == summary['diagnostic_selection_reference'], 'DIAGNOSTIC_AUTHORITY_CHANGED')
        refs = [summary_ref, frozen_ref, reference(config_path), split_ref, diag_ref,
                summary['collection_reference'], summary['diagnostic_selection_reference'],
                *frozen['references'], *collection['source_references']]
        for row in summary['cells']:
            if 'grade_reference' in row:
                refs.append(row['grade_reference'])
        for row in diagnostic['rows']:
            refs.extend(row[key] for key in ('official_report_reference', 'primary_cell_reference') if key in row)
        old_ref = config['source_summary_reference']
        require(old_ref in frozen['references'], 'OLD_COMPARISON_NOT_FROZEN')
        old = read(check(old_ref))
        require(old['status'] == 'COMPLETE', 'OLD_COMPARISON_INCOMPLETE')
        old_index = index_rows([r for r in old['cells'] if r['arm'] in ('OFF', 'ON')], split['pilot_ids'])
        old_rates = {arm: metric_counts([primary_value(old_index[identity, arm]) for identity in split['pilot_ids']]) for arm in ('OFF', 'ON')}
        unique = {str(Path(ref['path']).resolve()): ref for ref in refs}
        require(all(unique[str(Path(ref['path']).resolve())] == ref for ref in refs), 'CONFLICTING_REFERENCES')
        for ref in unique.values():
            check(ref)
        report = {'schema': SCHEMA, 'status': 'COMPLETE', 'observed_at': datetime.now(timezone.utc).isoformat(),
                  'experiment_id': summary['experiment_id'], 'requested_model': frozen['model'],
                  'reasoning_effort': frozen['reasoning_effort'], 'valid_tasks': 24, 'evaluated_cells': 48,
                  'new_training_cells': 0, 'source_training_tasks': summary['source_training_tasks'],
                  'source_bank_reference': config['source_bank_reference'], 'source_bank_layer_counts': summary['bank']['layer_counts'],
                  'test_partition_model_calls': summary['test_partition_model_calls'],
                  'source_references': list(unique.values()), 'exporter_reference': reference(__file__),
                  'source_bytes_verified_before_and_after': True, 'decoded_payload_classes': ['aggregate_summaries', 'split_metadata', 'frozen_manifests', 'collection_metadata'],
                  'private_grader_payloads_decoded': False, 'solver_state_or_prompt_decoded': False,
                  'model_calls': 0, 'grader_calls': 0, 'source_writes': 0,
                  'manager_seconds_last_invocation': number(summary['manager_seconds_this_invocation']),
                  'previous_condition': {'experiment_id': old['experiment_id'], 'source_reference': old_ref,
                      'primary': old_rates, 'comparison_caveat': 'Separate earlier condition with underspecified common submission rules. These runs do not isolate prompt effects or establish a causal difference; no cross-run paired significance claim.'},
                  **analyze(summary, diagnostic, split)}
        for ref in unique.values():
            check(ref)
        output.mkdir(parents=True)
        with (output / 'results.json').open('xb') as stream:
            stream.write(canonical(report))
        columns = ['task_id', 'difficulty'] + [arm + '_' + key for arm in ('OFF', 'ON') for key in
            ('primary_success', 'submission_accepted', 'accepted_candidate_correct', 'retained_candidate_correct',
             'retained_candidate_available', 'retained_candidate_source', 'solve_seconds', 'sessions',
             'public_test_runs', 'tool_actions', 'memory_injections', *TOKENS)]
        with (output / 'paired-results.csv').open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for pair in report['task_pairs']:
                flat = {key: pair[key] for key in ('task_id', 'difficulty')}
                for arm in ('OFF', 'ON'):
                    values = {**pair[arm], **pair[arm]['tokens']}
                    flat.update({arm + '_' + key: value for key, value in values.items() if arm + '_' + key in columns})
                writer.writerow(flat)
        return {'status': 'COMPLETE', 'results_reference': reference(output / 'results.json'),
                'paired_csv_reference': reference(output / 'paired-results.csv'),
                'cells': 48, 'tasks': 24, 'source_references_verified': len(unique)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.run_root, args.config, args.output)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__,
                          'error_code': str(exc) if isinstance(exc, ResultsError) else 'RESULTS_EXPORT_FAILED'}))
        raise SystemExit(1) from None
