"""Synthetic final metadata only; no run files, task payloads or execution."""
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('timing_supplement', HERE / 'pilot-timing-source-001.py')
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)


def fixture():
    # Include a fast ON-only solve and a both-solved pair missing one time.
    descriptions = [
        ('a', 'easy', True, True, True, True, 'SOLVED', 'SOLVED', 10, 6, 1),
        ('b', 'medium', False, True, None, True, 'MODEL_PROTOCOL_FAILURE', 'SOLVED', 40, 12, 0),
        ('c', 'hard', False, False, False, None, 'WRONG_SOLUTION', 'BUDGET_EXHAUSTED', 20, 60, 2),
        ('d', 'easy', None, False, None, None, 'INFRASTRUCTURE_UNRESOLVED', 'MODEL_PROTOCOL_FAILURE', None, 30, 0),
        ('e', 'hard', True, True, True, True, 'SOLVED', 'SOLVED', 30, None, 0),
    ]
    rows = []
    for identity, difficulty, off, on, off_pass, on_pass, off_outcome, on_outcome, off_time, on_time, injections in descriptions:
        rows.append(dict(zip(timing.CSV_FIELDS, [identity, difficulty, off, on, off_pass, on_pass,
            off_outcome, on_outcome, 'GRADED' if off_pass is not None else 'NOT_GRADED',
            'GRADED' if on_pass is not None else 'NOT_GRADED', off_time, on_time, injections,
            int(on) - int(off) if off is not None and on is not None else None,
            int(on_pass) - int(off_pass) if off_pass is not None and on_pass is not None else None])))
    off = {'planned': 5, 'recorded': 5, 'graded': 3, 'passed': 2, 'failed': 1, 'not_graded': 2,
           'resolved_outcomes': 4, 'infrastructure_or_pending': 1, 'resolved_passed': 2,
           'resolved_failed': 2, 'unresolved': 1, 'model_protocol_failures': 1, 'budget_exhausted': 0,
           'timed_cells': 4, 'mean_solve_seconds': 25, 'median_solve_seconds': 25,
           'max_solve_seconds': 40, 'solve_seconds': 100}
    on = {'planned': 5, 'recorded': 5, 'graded': 3, 'passed': 3, 'failed': 0, 'not_graded': 2,
          'resolved_outcomes': 5, 'infrastructure_or_pending': 0, 'resolved_passed': 3,
          'resolved_failed': 2, 'unresolved': 0, 'model_protocol_failures': 1, 'budget_exhausted': 1,
          'timed_cells': 4, 'mean_solve_seconds': 27, 'median_solve_seconds': 21,
          'max_solve_seconds': 60, 'solve_seconds': 108}
    report = {'schema': 'trimem/lcb-pilot-analysis/2.0', 'status': 'COMPLETE',
              'scope': 'VALIDATION_PILOT_NOT_FINAL_TEST', 'test_model_calls': 0, 'hidden_feedback_to_model': False,
              'experiment_id': 'synthetic', 'model': 'synthetic-model', 'reasoning_effort': 'low',
              'split_sha256': 'a' * 64, 'bank': {'sha256': 'b' * 64},
              'arms': {'TRAIN': {'planned': 2, 'recorded': 2, 'mean_solve_seconds': 5.5,
                                 'median_solve_seconds': 5.5, 'solve_seconds': 11}, 'OFF': off, 'ON': on},
              'paired': {'planned': 5, 'completed': 2, 'pending': 3, 'delta': None,
                         'off_fail_on_pass': 0, 'off_pass_on_fail': 0},
              'effective_paired': {'planned': 5, 'completed': 4, 'pending': 1, 'delta': None,
                                   'off_fail_on_pass': 1, 'off_pass_on_fail': 0},
              'off_fail_on_pass_ids': ['b'], 'off_pass_on_fail_ids': [],
              'exposed_target_count': 2, 'no_exposure_target_count': 3}
    return report, rows


def encode_csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=timing.CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: 'null' if value is None else str(value).lower() if type(value) is bool else value
                         for key, value in row.items()})
    return stream.getvalue().encode()


class TimingTests(unittest.TestCase):
    def result(self):
        report, rows = fixture()
        return timing.supplement(report, timing.parse_pairs(encode_csv(rows)))

    def test_all_attempt_mean_includes_failures_and_nulls_are_not_zero(self):
        result = self.result()['arms']['OFF']
        self.assertEqual(result['all_attempt_timing']['mean_seconds'], 25)
        self.assertEqual(result['all_attempt_timing']['median_seconds'], 25)
        self.assertEqual(result['all_attempt_timing']['attempts'], 5)
        self.assertEqual(result['all_attempt_timing']['timed_attempts'], 4)
        self.assertIsNone(result['all_attempt_timing']['total_seconds'])
        self.assertEqual(result['timing_by_resolved']['true']['mean_seconds'], 20)
        self.assertEqual(result['timing_by_resolved']['false']['mean_seconds'], 30)
        self.assertEqual(result['timing_by_resolved']['null']['attempts'], 1)
        self.assertIsNone(result['timing_by_resolved']['null']['mean_seconds'])

    def test_protocol_wrong_and_budget_are_separate_and_preserve_denominators(self):
        result = self.result()
        off, on = result['arms']['OFF'], result['arms']['ON']
        self.assertEqual((off['resolved_true'], off['resolved_false'], off['resolved_null']), (2, 2, 1))
        self.assertEqual((off['private_failed'], off['private_unavailable']), (1, 2))
        self.assertEqual(off['outcomes']['MODEL_PROTOCOL_FAILURE'], 1)
        self.assertEqual(off['outcomes']['WRONG_SOLUTION'], 1)
        self.assertEqual(on['outcomes']['BUDGET_EXHAUSTED'], 1)
        self.assertEqual(result['by_difficulty']['medium']['OFF']['resolved_false'], 1)
        self.assertEqual(sum(group['OFF']['attempts'] for group in result['by_difficulty'].values()), 5)

    def test_both_solved_uses_joint_timed_subset_and_signed_differences(self):
        result = self.result()['both_solved_paired_timing']
        self.assertEqual(result['task_ids'], ['a', 'e'])
        self.assertEqual((result['both_solved_pairs'], result['pairs_with_both_times']), (2, 1))
        self.assertEqual(result['off_timing_on_joint_timed_subset']['mean_seconds'], 10)
        self.assertEqual(result['on_timing_on_joint_timed_subset']['mean_seconds'], 6)
        self.assertEqual(result['on_minus_off_seconds']['mean_seconds'], -4)
        self.assertIsNone(result['pairs'][1]['on_minus_off_seconds'])

    def test_zero_time_is_a_real_observation_and_empty_subsets_remain_null(self):
        result = timing.timing([0, None])
        self.assertEqual(result['mean_seconds'], 0)
        self.assertEqual(result['timed_attempts'], 1)
        self.assertIsNone(timing.timing([])['mean_seconds'])
        self.assertIsNone(timing.timing([None])['sum_observed_seconds'])

    def test_train_detail_is_unavailable_without_opening_more_sources(self):
        train = self.result()['train']
        self.assertEqual(train['reported_aggregate_metadata']['mean_solve_seconds'], 5.5)
        self.assertIsNone(train['timing_by_resolved'])
        self.assertIsNone(train['per_difficulty'])

    def test_inconsistent_boolean_category_duration_and_duplicate_ids_reject(self):
        for field, replacement in [('off_resolved', True), ('off_passed', False), ('off_seconds', -1),
                                   ('off_seconds', float('nan')), ('off_seconds', float('inf')),
                                   ('off_resolved', 0), ('delta', 0)]:
            with self.subTest(field=field, replacement=replacement):
                _, rows = fixture()
                rows[1][field] = replacement
                with self.assertRaises(timing.TimingError):
                    timing.parse_pairs(encode_csv(rows))
        _, rows = fixture()
        rows[-1]['task_id'] = rows[0]['task_id']
        with self.assertRaisesRegex(timing.TimingError, 'DUPLICATE'):
            timing.parse_pairs(encode_csv(rows))

    def test_no_joint_success_produces_no_timing_claim(self):
        _, rows = fixture()
        pairs = timing.parse_pairs(encode_csv(rows))
        result = timing.both_solved([pairs[1], pairs[2], pairs[3]])
        self.assertEqual(result['both_solved_pairs'], 0)
        self.assertEqual(result['task_ids'], [])
        self.assertIsNone(result['on_minus_off_seconds']['mean_seconds'])

    def test_conflicting_json_csv_counts_times_and_pair_ids_reject(self):
        for mutate in (lambda value: value['arms']['OFF'].update(resolved_failed=1),
                       lambda value: value['arms']['OFF'].update(mean_solve_seconds=1),
                       lambda value: value['paired'].update(completed=5),
                       lambda value: value.update(off_fail_on_pass_ids=['wrong-id']),
                       lambda value: value.update(exposed_target_count=3)):
            report, rows = fixture()
            mutate(report)
            with self.assertRaises(timing.TimingError):
                timing.supplement(report, timing.parse_pairs(encode_csv(rows)))

    def test_incomplete_refuses_before_opening_paired_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'results.json'
            source.write_text('{"status":"RUNNING"}', encoding='utf-8')
            with self.assertRaisesRegex(timing.TimingError, 'FINAL_COMPLETE'):
                timing.load(source, Path(directory) / 'absent.csv')

    def test_load_reads_only_two_inputs_and_helper_hash_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results_path, pairs_path, output = root / 'results.json', root / 'pairs.csv', root / 'supplement.json'
            report, rows = fixture()
            # References must never be followed.
            report['summary_reference'] = {'path': 'NEVER_OPEN_STATE_OR_PRIVATE_DATA'}
            results_raw, pairs_raw = json.dumps(report).encode(), encode_csv(rows)
            results_path.write_bytes(results_raw)
            pairs_path.write_bytes(pairs_raw)
            original_reader = Path.read_bytes
            allowed = {results_path.resolve(), pairs_path.resolve(), Path(timing.__file__).resolve(), output.resolve()}
            def guarded(path):
                self.assertIn(path.resolve(), allowed)
                return original_reader(path)
            with patch.object(Path, 'read_bytes', guarded):
                result = timing.load(results_path, pairs_path)
                self.assertEqual(result['input_references'][0], timing.reference(results_path, results_raw))
                first = timing.publish(result, output)
                self.assertEqual(timing.publish(result, output), first)
            self.assertEqual(results_path.read_bytes(), results_raw)
            self.assertEqual(pairs_path.read_bytes(), pairs_raw)
            changed = copy.deepcopy(result)
            changed['valid_pairs'] = 999
            with self.assertRaisesRegex(timing.TimingError, 'EXISTING_SUPPLEMENT_DIFFERS'):
                timing.publish(changed, output)
            pairs_path.write_bytes(pairs_raw + b'\n')
            with self.assertRaisesRegex(timing.TimingError, 'INPUT_CHANGED'):
                timing.publish(result, root / 'must-not-exist.json')
            self.assertFalse((root / 'must-not-exist.json').exists())


if __name__ == '__main__':
    unittest.main()
