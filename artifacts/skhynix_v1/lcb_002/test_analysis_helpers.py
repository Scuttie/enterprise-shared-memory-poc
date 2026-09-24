"""Synthetic metadata tests only; no benchmark samples, model or grader calls."""
import csv
import copy
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lcb_final_analysis', HERE / 'pilot-analysis-source-001.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
exposure_spec = importlib.util.spec_from_file_location('lcb_exposure_analysis', HERE / 'exposure-audit-source-001.py')
exposure = importlib.util.module_from_spec(exposure_spec)
exposure_spec.loader.exec_module(exposure)


class OutcomeTests(unittest.TestCase):
    def test_private_wrong_answer_is_false(self):
        self.assertEqual(analysis.effective({'passed': False, 'grade_status': 'GRADED', 'status': 'SUBMITTED'}),
                         (False, 'WRONG_SOLUTION'))

    def test_budget_and_protocol_failures_are_false_without_private_verdict(self):
        for kind in analysis.BUDGET_ERRORS | analysis.PROTOCOL_ERRORS:
            with self.subTest(kind=kind):
                value = analysis.effective({'passed': None, 'grade_status': 'GENERATION_ERROR',
                    'status': 'GENERATION_ERROR', 'error_type': kind})
                self.assertIs(value[0], False)

    def test_transport_grader_and_interrupted_failures_remain_null(self):
        for status, grade, error in [('HELD', 'NOT_GRADED', 'InterruptedNativeAttempt'),
            ('GENERATION_ERROR', 'GENERATION_ERROR', 'NativeProcessError'),
            ('SUBMITTED', 'GRADER_ERROR', 'TestRunnerError')]:
            with self.subTest(error=error):
                self.assertEqual(analysis.effective({'status': status, 'grade_status': grade,
                    'passed': None, 'error_type': error}), (None, 'INFRASTRUCTURE_UNRESOLVED'))

    def test_truthy_number_is_not_a_private_verdict(self):
        with self.assertRaises(analysis.AnalysisError):
            analysis.effective({'passed': 1, 'grade_status': 'GRADED'})

    def test_missing_pair_preserves_denominator_and_null_overall_delta(self):
        result = analysis.paired_stats([(None, True), (False, False), (False, True)])
        self.assertEqual((result['planned'], result['completed'], result['pending']), (3, 2, 1))
        self.assertIsNone(result['delta'])
        self.assertEqual(result['paired_complete_delta_descriptive'], 0.5)
        self.assertEqual(result['test_scope'], 'AVAILABLE_PAIRS_ONLY_DESCRIPTIVE')

    def test_all_unresolved_has_no_statistical_result(self):
        result = analysis.paired_stats([(None, False), (True, None)])
        self.assertEqual(result['completed'], 0)
        self.assertIsNone(result['exact_mcnemar_two_sided_p'])
        self.assertIsNone(result['paired_complete_delta_descriptive'])

    def test_complete_pairs_use_budget_failures_as_effective_false(self):
        result = analysis.paired_stats([(False, True), (True, False), (False, False)])
        self.assertEqual((result['completed'], result['delta'], result['exact_mcnemar_two_sided_p']), (3, 0, 1))

    def test_incomplete_run_refuses_before_loading_other_files(self):
        with patch.object(analysis, 'read', return_value={'status': 'INCOMPLETE'}) as reader:
            with self.assertRaisesRegex(analysis.AnalysisError, 'PILOT_NOT_COMPLETE'):
                analysis.load_run(HERE / 'synthetic-missing-run', HERE / 'synthetic-missing-config.json')
            self.assertEqual(reader.call_count, 1)

    def test_csv_null_and_false_are_distinct(self):
        raw = analysis.csv_bytes([{'off_resolved': None, 'on_resolved': False, 'delta': None}])
        row = next(csv.DictReader(io.StringIO(raw.decode())))
        self.assertEqual(row, {'off_resolved': 'null', 'on_resolved': 'false', 'delta': 'null'})

    def test_partial_training_bank_uses_actual_captured_count(self):
        summary = {'cells': [
            {'arm': 'TRAIN', 'task_id': 'a', 'status': 'SUBMITTED', 'capture_status': 'CAPTURED'},
            {'arm': 'TRAIN', 'task_id': 'b', 'status': 'GENERATION_ERROR', 'capture_status': 'NOT_APPLICABLE'},
            {'arm': 'ON', 'task_id': 'v', 'status': 'SUBMITTED', 'capture_status': 'NOT_APPLICABLE'}],
            'arms': {'TRAIN': {'captured': 1}}}
        self.assertEqual(set(exposure.captured_training_rows(summary, {'a', 'b'})), {'a'})

    def test_training_capture_count_cannot_hide_failure(self):
        summary = {'cells': [{'arm': 'TRAIN', 'task_id': 'a', 'status': 'GENERATION_ERROR',
            'capture_status': 'NOT_APPLICABLE'}], 'arms': {'TRAIN': {'captured': 1}}}
        with self.assertRaises(exposure.AuditError):
            exposure.captured_training_rows(summary, {'a'})

    def test_foreign_or_evaluation_id_is_not_a_training_capture(self):
        summary = {'cells': [{'arm': 'TRAIN', 'task_id': 'foreign-valid', 'status': 'SUBMITTED',
            'capture_status': 'CAPTURED'}], 'arms': {'TRAIN': {'captured': 1}}}
        with self.assertRaises(exposure.AuditError):
            exposure.captured_training_rows(summary, {'a'})


class HistoricalInjectionNodeTests(unittest.TestCase):
    def state(self):
        request = {'tool': 'revise_subtask_dag', 'arguments': {'subtasks': [
            {'objective': 'synthetic first', 'operation': 'first'},
            {'objective': 'synthetic second', 'operation': 'second'}]}}
        result = {'dag_revised': True, 'active_node_id': 'subgoal-1'}
        def identity(payload):
            raw = exposure.canonical(payload)
            return {'sha256': exposure.digest(raw), 'bytes': len(raw)}
        event = {'task_id': 'synthetic-valid', 'arm': 'PDF_MEMORY', 'step_no': 1,
                 'tool': 'revise_subtask_dag', 'status': 'success', 'active_node_id': 'subgoal-1',
                 'request_payload': request, 'result_payload': result,
                 'request': identity(request), 'result': identity(result)}
        item = {'memory_id': 'synthetic-episode', 'canonical_node_hash': 'sha256:' + 'a' * 64,
                'active_node_id': 'solution'}
        return {'task': {'task_id': 'synthetic-valid'}, 'limits': {'subtasks': 3},
                'graph': {'nodes': [{'node_id': 'subgoal-1'}, {'node_id': 'subgoal-2'}]},
                'history': [event], 'memory_injections': [item],
                'memory_checkpoint': {'controller': {'ledger': [copy.deepcopy(item)],
                    'source_hashes': {item['memory_id']: item['canonical_node_hash']},
                    'recalled_nodes': ['solution', 'subgoal-1']}}}

    def test_initial_recall_survives_verified_one_time_graph_replacement(self):
        state = self.state()
        binding = exposure.injection_node_bindings(state)['solution']
        self.assertEqual(binding['scope'], 'RETIRED_INITIAL_NODE_BEFORE_FIRST_DAG_REPLACEMENT')
        self.assertEqual(binding['replacement_step_no'], 1)
        self.assertEqual(binding['replacement_event_sha256'], exposure.digest(exposure.canonical(state['history'][0])))
        self.assertIs(binding['per_injection_timestamp_available'], False)

    def test_terminal_node_still_needs_recalled_checkpoint_membership(self):
        state = self.state()
        state['memory_injections'][0]['active_node_id'] = 'subgoal-1'
        state['memory_checkpoint']['controller']['ledger'] = copy.deepcopy(state['memory_injections'])
        self.assertEqual(exposure.injection_node_bindings(state)['subgoal-1']['scope'], 'TERMINAL_GRAPH_NODE')
        state['memory_checkpoint']['controller']['recalled_nodes'] = ['solution']
        with self.assertRaisesRegex(exposure.AuditError, 'NOT_RECALLED'):
            exposure.injection_node_bindings(state)

    def test_arbitrary_missing_node_is_never_admitted(self):
        state = self.state()
        state['memory_injections'][0]['active_node_id'] = 'invented-old-node'
        state['memory_checkpoint']['controller']['ledger'] = copy.deepcopy(state['memory_injections'])
        state['memory_checkpoint']['controller']['recalled_nodes'].append('invented-old-node')
        with self.assertRaisesRegex(exposure.AuditError, 'UNBOUND_ACTIVE_NODE'):
            exposure.injection_node_bindings(state)

    def test_initial_injection_after_replacement_injection_is_rejected(self):
        state = self.state()
        item = {'memory_id': 'synthetic-second', 'canonical_node_hash': 'sha256:' + 'b' * 64,
                'active_node_id': 'subgoal-1'}
        state['memory_injections'].insert(0, item)
        controller = state['memory_checkpoint']['controller']
        controller['ledger'] = copy.deepcopy(state['memory_injections'])
        controller['source_hashes'][item['memory_id']] = item['canonical_node_hash']
        with self.assertRaisesRegex(exposure.AuditError, 'INITIAL_INJECTION_ORDER_CHANGED'):
            exposure.injection_node_bindings(state)

    def test_checkpoint_name_alone_does_not_prove_initial_replacement(self):
        state = self.state()
        state['history'] = []
        with self.assertRaisesRegex(exposure.AuditError, 'TRACE_MISSING'):
            exposure.injection_node_bindings(state)

    def test_forged_changed_or_later_replacement_and_source_hash_are_rejected(self):
        def later(state):
            event = copy.deepcopy(state['history'][0])
            event['tool'] = 'run_public_tests'
            state['history'].insert(0, event)
        changes = [later,
            lambda state: state['history'][0].update(status='error'),
            lambda state: state['history'][0].update(task_id='foreign'),
            lambda state: state['history'][0]['request'].update(sha256='0' * 64),
            lambda state: state['history'][0]['result_payload'].update(dag_revised=False),
            lambda state: state['graph']['nodes'].append({'node_id': 'unexplained-node'}),
            lambda state: state['history'].append(copy.deepcopy(state['history'][0])),
            lambda state: state['memory_checkpoint']['controller']['source_hashes'].clear()]
        for change in changes:
            with self.subTest(change=change):
                state = self.state()
                change(state)
                with self.assertRaises(exposure.AuditError):
                    exposure.injection_node_bindings(state)


if __name__ == '__main__':
    unittest.main()
