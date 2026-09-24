"""Synthetic posthoc-selection tests. No live cells, datasets, models, or grader."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('posthoc_submission', HERE / 'posthoc-submission-source-001.py')
posthoc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(posthoc)


def state(code='', rejected=None, with_trace=True):
    row = {'limits': {'code_bytes': 1000}, 'candidate': code, 'rejected_actions': rejected or [],
        'task': {'task_id': 'synthetic', 'public_tests_sha256': 'b' * 64}, 'history': []}
    if with_trace and code:
        request = {'tool': 'run_public_tests', 'arguments': {'code': code}}
        result = {'candidate_sha256': posthoc.sha(code.encode()), 'public_tests_sha256': 'b' * 64,
            'status': 'FAIL'}
        event = {'tool': 'run_public_tests', 'status': 'success', 'step_no': 1,
            'request_payload': request, 'result_payload': result}
        for key, payload in [('request', request), ('result', result)]:
            raw = posthoc.canonical(payload)[:-1]
            event[key] = {'sha256': posthoc.sha(raw), 'bytes': len(raw)}
        row['history'].append(event)
    return row


def rejected(step, code):
    return {'step': step, 'request': {'tool': 'finish', 'arguments': {'code': code, 'source_lesson': {}}},
        'result': {'error': 'ValueError', 'message': 'Synthetic lesson rejected'}}


def eligible_row():
    return {'status': 'GENERATION_ERROR', 'error_type': 'MissingSubmission',
        'outcome': 'MODEL_PROTOCOL_FAILURE', 'resolved': False, 'passed': None,
        'grade_status': 'GENERATION_ERROR'}


class SelectionTests(unittest.TestCase):
    def test_last_valid_rejected_finish_wins_over_public_candidate(self):
        value = state('print(0)', [rejected(2, 'print(1)'), rejected(3, 'print(2)')])
        code, receipt = posthoc.select_candidate(value)
        self.assertEqual(code, 'print(2)')
        self.assertEqual(receipt['selection_path'], 'state.rejected_actions[1].request.arguments.code')
        self.assertEqual(receipt['selection_step'], 3)

    def test_later_empty_or_nonstring_finish_does_not_replace_last_valid_code(self):
        value = state('print(0)', [rejected(2, 'print(1)'), rejected(3, '  '), rejected(4, 42)])
        self.assertEqual(posthoc.select_candidate(value)[0], 'print(1)')

    def test_preserves_whitespace_and_exact_utf8_bytes(self):
        original = '\n# 합성 fixture\nprint(1)\n\n'
        code, receipt = posthoc.select_candidate(state(rejected=[rejected(1, original)]))
        self.assertEqual(code.encode(), original.encode())
        self.assertEqual(receipt['candidate_sha256'], posthoc.sha(original.encode()))

    def test_size_limit_is_utf8_bytes_and_falls_back_without_truncating(self):
        value = state('pass', [rejected(2, '한' * 4)])
        value['limits']['code_bytes'] = 10
        code, receipt = posthoc.select_candidate(value)
        self.assertEqual(code, 'pass')
        self.assertEqual(receipt['selection_source'], 'STATE_PUBLIC_CANDIDATE')

    def test_state_candidate_fallback_is_exact_last_public_candidate(self):
        code, receipt = posthoc.select_candidate(state('print(3)', [rejected(2, None)]))
        self.assertEqual(code, 'print(3)')
        self.assertEqual(receipt['selection_path'], 'state.candidate')

    def test_empty_candidate_is_skipped_not_failed(self):
        code, receipt = posthoc.select_candidate(state('  '))
        self.assertIsNone(code)
        self.assertEqual(receipt['selection_status'], 'SKIPPED_NO_CANDIDATE')
        self.assertIsNone(receipt['candidate_sha256'])

    def test_candidate_without_completed_public_receipt_is_skipped(self):
        code, receipt = posthoc.select_candidate(state('print(3)', with_trace=False))
        self.assertIsNone(code)
        self.assertEqual(receipt['selection_status'], 'SKIPPED_UNVERIFIED_PUBLIC_CANDIDATE')

    def test_candidate_different_from_last_public_receipt_is_skipped(self):
        value = state('print(3)')
        value['candidate'] = 'print(4)'
        self.assertIsNone(posthoc.select_candidate(value)[0])

    def test_tampered_public_trace_hash_is_rejected(self):
        value = state('print(3)')
        value['history'][0]['request']['sha256'] = '0' * 64
        with self.assertRaisesRegex(posthoc.DiagnosticError, 'PUBLIC_TRACE_REFERENCE_CHANGED'):
            posthoc.select_candidate(value)

    def test_rejection_order_is_not_reinterpreted(self):
        with self.assertRaisesRegex(posthoc.DiagnosticError, 'MALFORMED_REJECTION_ORDER'):
            posthoc.select_candidate(state(rejected=[rejected(3, 'pass'), rejected(2, 'pass')]))

    def test_selection_ignores_any_unsupported_hidden_claims(self):
        value = state(rejected=[rejected(1, 'print(1)'), rejected(2, 'print(2)')])
        value['private_verdict'] = {'preferred_candidate': 'print(1)', 'passed': True}
        self.assertEqual(posthoc.select_candidate(value)[0], 'print(2)')


class BoundaryTests(unittest.TestCase):
    def test_only_missing_submission_model_protocol_failures_are_eligible(self):
        row = eligible_row()
        self.assertTrue(posthoc.eligible(row))
        for key, value in [('error_type', 'TaskTimeout'), ('error_type', 'NativeProcessError'),
            ('error_type', 'UnexpectedNativeTool'), ('status', 'SUBMITTED'),
            ('outcome', 'BUDGET_EXHAUSTED'), ('passed', False), ('resolved', None), ('resolved', 0)]:
            with self.subTest(key=key, value=value):
                self.assertFalse(posthoc.eligible({**row, key: value}))

    def test_incomplete_blocks_before_state_runtime_or_private_access(self):
        with patch.object(posthoc, 'read', return_value={'status': 'INCOMPLETE'}) as reader:
            with self.assertRaisesRegex(posthoc.DiagnosticError, 'PILOT_NOT_COMPLETE'):
                posthoc.freeze_selection(Path('synthetic-pilot'), Path('synthetic-runtime.json'))
        self.assertEqual(reader.call_count, 1)

    def test_error_stdout_never_contains_exception_data(self):
        output = io.StringIO()
        with patch.object(posthoc, 'run', side_effect=ValueError('SECRET synthetic contents')):
            with contextlib.redirect_stdout(output):
                code = posthoc.main(['run', '--pilot-root', 'p', '--runtime', 'r', '--output', 'o', '--report', 'a'])
        self.assertEqual(code, 2)
        self.assertNotIn('SECRET', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_type'], 'ValueError')

    def test_existing_primary_lock_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'experiment.lock'
            path.write_bytes(b'0')
            before = path.read_bytes()
            with posthoc.primary_lock(path):
                with self.assertRaises(posthoc.DiagnosticError):
                    with posthoc.primary_lock(path):
                        self.fail('Concurrent primary lock acquired')
            self.assertEqual(path.read_bytes(), before)


class GradeTests(unittest.TestCase):
    def report(self, status='GRADED', passed=True):
        return {'schema': 'trimem/lcb-grade-report/1.0',
            'status': 'COMPLETE' if status == 'GRADED' else 'INCOMPLETE',
            'cohort_scope': 'DECLARED_EXPECTED_IDS',
            'counts': {'planned': 1, 'graded': int(status == 'GRADED'), 'passed': int(passed is True)},
            'results': [{'question_id': 'synthetic', 'status': status, 'passed': passed,
                'extracted_code_sha256': 'c' * 64}],
            'provenance': {'upstream_commit': posthoc.UPSTREAM_COMMIT,
                'predictions_reference': {'sha256': 'p' * 64}, 'dataset_reference': {'sha256': 'd' * 64}},
            'settings': {'timeout_seconds': 6, 'workers': 1, 'generations_per_question': 1,
                'extraction_style': 'OpenAIChat'}}

    def validate(self, report):
        return posthoc.validate_grade(report, {'task_id': 'synthetic', 'candidate_sha256': 'c' * 64},
            {'sha256': 'p' * 64}, {'sha256': 'd' * 64}, {'timeout': 6, 'workers': 1})

    def test_official_wrong_answer_is_false(self):
        self.assertIs(self.validate(self.report(passed=False))['diagnostic_passed'], False)

    def test_grader_error_is_null(self):
        value = self.validate(self.report(status='GRADER_ERROR', passed=None))
        self.assertIsNone(value['diagnostic_passed'])

    def test_ungraded_cannot_claim_false_or_true(self):
        for passed in (False, True):
            with self.subTest(passed=passed):
                with self.assertRaises(posthoc.DiagnosticError):
                    self.validate(self.report(status='GRADER_ERROR', passed=passed))

    def test_truthy_integer_is_not_a_boolean_verdict(self):
        with self.assertRaises(posthoc.DiagnosticError):
            self.validate(self.report(passed=1))

    def test_candidate_identity_mismatch_is_rejected(self):
        value = self.report()
        value['results'][0]['extracted_code_sha256'] = 'x' * 64
        with self.assertRaises(posthoc.DiagnosticError):
            self.validate(value)

    def test_prediction_or_sample_hash_mismatch_is_rejected(self):
        for key in ('predictions_reference', 'dataset_reference'):
            with self.subTest(key=key):
                value = self.report()
                value['provenance'][key]['sha256'] = 'x' * 64
                with self.assertRaises(posthoc.DiagnosticError):
                    self.validate(value)


class OrchestrationTests(unittest.TestCase):
    def test_all_selection_is_saved_before_private_access_and_skips_remain_null(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            pilot = repo / 'data' / 'skhynix_lcb_002' / 'pilot-001'
            output = pilot.parent / 'posthoc-001'
            artifacts = repo / 'artifacts' / 'skhynix_v1' / 'lcb_002'
            pilot.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            (pilot / 'experiment.lock').write_bytes(b'0')
            summary_path = pilot / 'summary.json'
            primary = posthoc.canonical({'schema': 'trimem/lcb-experiment/1.0',
                'status': 'COMPLETE', 'private_grading_ready': True})
            summary_path.write_bytes(primary)
            plans = [{'task_id': 'synthetic-one', 'arm': 'TRAIN', 'cell_key': 'synthetic-one',
                'selection_status': 'SELECTED', 'candidate_sha256': posthoc.sha(b'print(1)'),
                'primary_resolved': False, 'primary_passed': None},
                {'task_id': 'synthetic-two', 'arm': 'ON', 'cell_key': 'synthetic-two',
                'selection_status': 'SKIPPED_NO_CANDIDATE', 'candidate_sha256': None,
                'primary_resolved': False, 'primary_passed': None}]
            selection = {'experiment_id': 'synthetic-diagnostic', 'model': 'synthetic-model',
                'reasoning_effort': 'low', 'rows': plans, 'primary_enrolled_cells': 6,
                'primary_summary_reference': posthoc.reference(summary_path),
                'helper_reference': posthoc.reference(posthoc.__file__)}
            runtime = {'execution': {'scripts_root': str(repo / 'scripts')}}
            order = []

            def private_authority(*args):
                saved = posthoc.read(output / 'selection-receipt.json')
                self.assertEqual(saved['rows'], plans)
                self.assertNotIn('print(1)', (output / 'selection-receipt.json').read_text())
                order.append('private-authority')
                return repo / 'synthetic-dataset', {}, []

            def grade(plan, code, *args):
                self.assertEqual(code, 'print(1)')
                order.append('grade')
                return {**plan, 'diagnostic_grade_status': 'GRADED', 'diagnostic_passed': True}

            with patch.object(posthoc, 'freeze_selection', return_value=(selection,
                {'synthetic-one': 'print(1)'}, runtime, {}, [posthoc.reference(summary_path)])):
                with patch.object(posthoc, 'load_dataset_authority', side_effect=private_authority):
                    with patch.object(posthoc, 'grade_selected', side_effect=grade) as grader:
                        result = posthoc.run(pilot, repo / 'runtime.json', output,
                            artifacts / 'diagnostic.json', repo_root=repo)
            self.assertEqual(order, ['private-authority', 'grade'])
            self.assertEqual(grader.call_count, 1)
            self.assertEqual(result['counts']['eligible'], 2)
            self.assertEqual(result['counts']['skipped'], 1)
            self.assertIsNone(result['eligible_candidate_pass_fraction'])
            self.assertIsNone(result['rows'][1]['diagnostic_passed'])
            self.assertEqual(summary_path.read_bytes(), primary)
            self.assertFalse(result['rows'][0]['primary_resolved'])
            self.assertNotIn('print(1)', (artifacts / 'diagnostic.json').read_text())
            with self.assertRaisesRegex(posthoc.DiagnosticError, 'FRESH_DIAGNOSTIC_OUTPUT_REQUIRED'):
                posthoc.run(pilot, repo / 'runtime.json', output,
                    artifacts / 'diagnostic.json', repo_root=repo)


class AuthorityTests(unittest.TestCase):
    def authority_fixture(self, temporary, *, changed_revision=False, changed_split=False):
        root = Path(temporary)
        data, pilot = root / 'data', root / 'pilot'
        data.mkdir()
        pilot.mkdir()
        public_tasks = data / 'public-tasks.jsonl'
        public_tasks.write_bytes(b'opaque synthetic public fixture\n')

        def relative(path):
            return {**posthoc.reference(path), 'path': path.relative_to(data).as_posix()}

        public = {'schema': 'trimem/lcb-public-dataset/1.0', 'dataset_id': 'synthetic',
            'revision': 'original-revision', 'release': 'synthetic', 'task_count': 3,
            'source_files': [], 'counts': {'total': 3}, 'public_tasks_reference': relative(public_tasks)}
        public_path = data / 'public-manifest.json'
        posthoc.write_new(public_path, public)
        manifest = {**public, 'schema': 'trimem/lcb-dataset/1.0', 'private_evaluation_files': {}}
        if changed_revision:
            manifest['revision'] = 'replaced-revision'
        manifest_path = data / 'dataset-manifest.json'
        posthoc.write_new(manifest_path, manifest)
        split = {'schema': 'trimem/lcb-split/1.0', 'train_pilot_ids': ['train'], 'pilot_ids': ['valid'],
            'train_ids': ['train'], 'valid_ids': ['valid'], 'test_ids': ['test'],
            'dataset_reference': relative(public_path)}
        public_split = root / 'public-split.json'
        posthoc.write_new(public_split, split)
        final_split_value = {**split, 'dataset_reference': relative(manifest_path)}
        if changed_split:
            final_split_value['train_ids'] = ['replacement-train']
        final_split = root / 'final-split.json'
        posthoc.write_new(final_split, final_split_value)
        ready_path = data / 'dataset-ready.json'
        posthoc.write_new(ready_path, {'schema': 'trimem/lcb-dataset-ready/1.0', 'status': 'READY',
            'identities_verified': True, 'manifest_reference': relative(manifest_path),
            'public_split_reference': posthoc.reference(public_split), 'split_reference': posthoc.reference(final_split)})
        posthoc.write_new(pilot / 'private-dataset-receipt.json', {'manifest': posthoc.reference(manifest_path),
            'split': posthoc.reference(final_split), 'ready': posthoc.reference(ready_path)})
        return pilot, {'dataset_root': str(data),
            'references': [posthoc.reference(public_path), posthoc.reference(public_split)],
            'enrollment': {'train': ['train'], 'valid': ['valid']}}

    def test_final_private_authority_matches_original_public_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            pilot, frozen = self.authority_fixture(temporary)
            _, manifest, _ = posthoc.load_dataset_authority(pilot, frozen)
            self.assertEqual(manifest['revision'], 'original-revision')

    def test_self_consistent_replacement_authority_is_rejected(self):
        for mutation in ('changed_revision', 'changed_split'):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temporary:
                    pilot, frozen = self.authority_fixture(temporary, **{mutation: True})
                    with self.assertRaisesRegex(posthoc.DiagnosticError, 'PRIVATE_DATASET_DIFFERS'):
                        posthoc.load_dataset_authority(pilot, frozen)

    def test_sample_copy_is_bound_to_manifest_not_current_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, output = root / 'data', root / 'output'
            data.mkdir()
            output.mkdir()
            source = data / 'synthetic.json.gz'
            source.write_bytes(b'original opaque gzip fixture')
            pinned = {**posthoc.reference(source), 'path': source.name, 'format': 'gzip-json'}
            plan = {'task_id': 'synthetic', 'cell_key': 'synthetic-cell', 'candidate_sha256': posthoc.sha(b'pass')}

            def replacement(src, dst):
                Path(src).write_bytes(b'replacement opaque fixture')
                Path(dst).write_bytes(b'replacement opaque fixture')

            with patch.object(posthoc.shutil, 'copyfile', side_effect=replacement):
                with patch.object(posthoc.subprocess, 'run') as runner:
                    result = posthoc.grade_selected(plan, 'pass', output, data,
                        {'private_evaluation_files': {'synthetic': pinned}}, {})
            runner.assert_not_called()
            self.assertEqual(result['diagnostic_grade_status'], 'GRADER_ERROR')
            self.assertIsNone(result['diagnostic_passed'])


if __name__ == '__main__':
    unittest.main()
