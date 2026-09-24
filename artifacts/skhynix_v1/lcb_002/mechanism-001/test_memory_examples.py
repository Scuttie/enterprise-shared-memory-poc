"""Synthetic schema/provenance tests; never opens actual run payloads."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('memory_examples', HERE / 'memory-examples-source-001.py')
examples = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(examples)


def stamp_view(item, exposure, view):
    item['exact_text'] = json.dumps(view, sort_keys=True)
    raw = item['exact_text'].encode()
    item['sha256'] = exposure['injection_sha256'] = examples.sha(raw)
    item['byte_count'] = exposure['byte_count'] = len(raw)


def fixture(steps=None, narrative='SYNTHETIC_NARRATIVE_NEVER_PUBLISH'):
    steps = [2] if steps is None else steps
    lesson = {'summary': narrative, 'applicability': 'synthetic applicability',
              'procedure': ['synthetic step'], 'trace_steps': steps}
    capture = {'task_public': {'task_id': 'synthetic-train', 'split': 'train', 'family_id': 'source-family'},
               'source_lesson': copy.deepcopy(lesson), 'history': [{'step_no': 2}, {'step_no': 3}]}
    receipt = {'episode_id': 'episode:synthetic', 'episode_content_hash': 'sha256:' + 'a' * 64}
    item = {'memory_id': receipt['episode_id'], 'kind': 'EPISODIC',
            'canonical_node_hash': receipt['episode_content_hash'], 'active_node_id': 'subgoal-1'}
    exposure = {'memory_id': item['memory_id'], 'kind': 'EPISODIC',
                'canonical_memory_hash': item['canonical_node_hash'], 'source_task_id': 'synthetic-train',
                'source_family_id': 'source-family', 'capture_reference': {'path': 'synthetic-capture', 'sha256': 'b' * 64},
                'target_task_id': 'synthetic-valid-1', 'injection_ordinal': 0}
    view = {'layer': 'EPISODIC', 'summary': json.dumps({**lesson,
                'provenance': 'MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS',
                'verification_scope': 'PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER'}, sort_keys=True),
            'actions': [json.dumps({'tool': 'run_public_tests', 'step_no': step}) for step in steps]}
    stamp_view(item, exposure, view)
    return item, exposure, {'capture': capture, 'receipt': receipt}


class ProjectionTests(unittest.TestCase):
    def test_numeric_example_is_preserved_without_prose_or_causal_claim(self):
        result = examples.project_example(*fixture())
        self.assertEqual(result['embedded_trace_steps'], [2])
        self.assertEqual(result['action_step_examples'], [2])
        self.assertEqual(result['protocol_fragment'], '{"trace_steps": [2]}')
        encoded = json.dumps(result)
        self.assertNotIn('SYNTHETIC_NARRATIVE_NEVER_PUBLISH', encoded)
        self.assertIn('NOT_PROOF_OF_MODEL_COPYING_OR_CAUSAL_USE', result['interpretation'])
        self.assertFalse(any(result['narrative_literal_substring_matches'].values()))

    def test_tampered_view_hash_or_byte_count_rejects(self):
        for change in ('text', 'item_hash', 'audit_hash', 'bytes'):
            with self.subTest(change=change):
                item, exposure, envelope = fixture()
                if change == 'text':
                    item['exact_text'] += ' '
                elif change == 'item_hash':
                    item['sha256'] = '0' * 64
                elif change == 'audit_hash':
                    exposure['injection_sha256'] = '0' * 64
                else:
                    item['byte_count'] += 1
                with self.assertRaisesRegex(examples.EvidenceError, 'VIEW_HASH_CHANGED'):
                    examples.project_example(item, exposure, envelope)

    def test_foreign_eval_source_or_canonical_identity_rejects(self):
        changes = [lambda item, exposure, envelope: envelope['capture']['task_public'].update(task_id='foreign'),
                   lambda item, exposure, envelope: envelope['capture']['task_public'].update(split='valid'),
                   lambda item, exposure, envelope: envelope['receipt'].update(episode_id='foreign-episode'),
                   lambda item, exposure, envelope: envelope['receipt'].update(episode_content_hash='changed'),
                   lambda item, exposure, envelope: item.update(canonical_node_hash='changed')]
        for change in changes:
            with self.subTest(change=change):
                values = fixture()
                change(*values)
                with self.assertRaises(examples.EvidenceError):
                    examples.project_example(*values)

    def test_summary_must_equal_source_lesson_not_just_share_anchor_numbers(self):
        item, exposure, envelope = fixture()
        envelope['capture']['source_lesson']['summary'] = 'different synthetic narrative'
        with self.assertRaisesRegex(examples.EvidenceError, 'SOURCE_LESSON_CHANGED'):
            examples.project_example(item, exposure, envelope)

    def test_source_anchors_require_exact_int_sorted_unique_nonempty_and_existing(self):
        for steps in ([True], [2.0], ['2'], [], [2, 2], [3, 2], [99]):
            with self.subTest(steps=steps):
                with self.assertRaisesRegex(examples.EvidenceError, 'INVALID_SOURCE_STEP_EXAMPLE'):
                    examples.project_example(*fixture(steps=steps))

    def test_action_anchor_disagreement_rejects_after_valid_view_hash(self):
        item, exposure, envelope = fixture()
        view = json.loads(item['exact_text'])
        view['actions'] = [json.dumps({'step_no': 3})]
        stamp_view(item, exposure, view)
        with self.assertRaisesRegex(examples.EvidenceError, 'ACTION_ANCHOR_CHANGED'):
            examples.project_example(item, exposure, envelope)

    def test_narrative_flags_are_literal_casefolded_substrings_not_semantic_judgments(self):
        # "information" contains "format" but is not submission-format advice.
        result = examples.project_example(*fixture(narrative='Information is useful. SUBMIT is a quoted token.'))
        flags = result['narrative_literal_substring_matches']
        self.assertTrue(flags['format'])
        self.assertTrue(flags['submit'])
        self.assertFalse(flags['trace_steps'])  # Structural JSON key is not prose.
        self.assertNotIn('semantic_absence', result)
        self.assertNotIn('Information', json.dumps(result))

    def test_changed_capture_file_is_rejected_by_hash_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.json'
            path.write_text('{"synthetic":true}', encoding='utf-8')
            reference = examples.reference(path)
            path.write_text('{"synthetic":false}', encoding='utf-8')
            with self.assertRaisesRegex(examples.EvidenceError, 'REFERENCE_CHANGED'):
                examples.checked(reference)


class CohortTests(unittest.TestCase):
    def arrange(self, root):
        here, pilot = root / 'artifacts/mechanism', root / 'pilot'
        here.mkdir(parents=True)
        pilot.mkdir()
        def write(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(examples.canonical(value) + b'\n')
            return examples.reference(path)
        item, exposure, envelope = fixture()
        exposure['capture_reference'] = write(pilot / 'capture.json', envelope)
        summary_ref = write(pilot / 'summary.json', {'status': 'COMPLETE'})
        bank_ref = write(pilot / 'bank.json', {'synthetic': True})
        valid = ['synthetic-valid-1', 'synthetic-valid-2']
        targets = []
        for index, identity in enumerate(valid):
            state = {'task': {'task_id': identity}, 'arm': 'ON', 'memory_injections': [item] if index == 0 else []}
            state_ref = write(pilot / identity / 'state.json', state)
            solve_ref = write(pilot / identity / 'solve.json', {'task_id': identity, 'arm': 'ON', 'state_sha256': state_ref['sha256']})
            targets.append({'target_task_id': identity, 'state_reference': state_ref, 'solve_receipt_reference': solve_ref})
        frozen = {'implementation': [], 'enrollment': {'valid': valid}}
        write(pilot / 'frozen-inputs.json', frozen)
        analysis = {'status': 'COMPLETE', 'summary_reference': summary_ref, 'model': 'synthetic-model',
                    'reasoning_effort': 'low', 'experiment_id': 'synthetic-experiment'}
        audit = {'audit_status': 'PASS', 'coverage': 'COMPLETE', 'summary_reference': summary_ref,
                 'bank_reference': bank_ref, 'targets': targets, 'exposures': [exposure], 'injection_count': 1}
        write(here.parent / 'pilot-results-001.json', analysis)
        write(here.parent / 'pilot-exposure-audit-001.json', audit)
        return here, pilot, audit, write

    def test_every_enrolled_target_is_retained_including_zero_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            here, pilot, _, _ = self.arrange(Path(directory))
            with patch.object(examples, 'HERE', here), patch.object(examples, 'PILOT', pilot), contextlib.redirect_stdout(io.StringIO()):
                examples.run()
            report = json.loads((here / 'memory-examples-001.json').read_bytes())
            self.assertEqual(report['counts']['valid_targets'], 2)
            self.assertEqual(report['counts']['exposed_targets'], 1)
            self.assertEqual(report['counts']['injections'], 1)
            self.assertEqual([row['task_id'] for row in report['targets']], ['synthetic-valid-1', 'synthetic-valid-2'])
            self.assertEqual(report['targets'][1]['injections'], [])
            self.assertTrue(any('do not prove semantic absence' in note for note in report['limitations']))
            self.assertTrue(any('does not establish delivery' in note for note in report['limitations']))
            self.assertEqual((report['model_calls'], report['grader_calls'], report['original_writes']), (0, 0, 0))
            self.assertNotIn('SYNTHETIC_NARRATIVE_NEVER_PUBLISH', json.dumps(report))

    def test_omitted_unexposed_target_cannot_shrink_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            here, pilot, audit, write = self.arrange(Path(directory))
            audit['targets'].pop()
            write(here.parent / 'pilot-exposure-audit-001.json', audit)
            with patch.object(examples, 'HERE', here), patch.object(examples, 'PILOT', pilot):
                with self.assertRaisesRegex(examples.EvidenceError, 'TARGET_ENROLLMENT_OR_EXPOSURE_CHANGED'):
                    examples.run()
            self.assertFalse((here / 'memory-examples-001.json').exists())


if __name__ == '__main__':
    unittest.main()
