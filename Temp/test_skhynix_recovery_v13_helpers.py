"""Exercise the preparation-only cache without importing experiment runtime."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


module = ast.parse(Path(__file__).with_name('prepare_skhynix_scale_recovery_v13.py').read_text())
nodes = [item for item in module.body if
    isinstance(item, (ast.ClassDef, ast.FunctionDef)) and item.name in
        ('PreparationExecutionCache', 'runtime_amendment', 'runtime_reference', 'approved_native_terminal', 'merge_references', 'abandoned_prelaunch', 'abandoned_prelaunch_chain')
    or isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
        ('CLASSIFIER_PATH', 'RUNTIME_CHANGED_PATHS', 'TRAINING_GRADE_HOLD_POLICY') for target in item.targets)]
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<preparation-cache>', 'exec'), globals())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ref(path):
    path = Path(path)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(reference):
    require(ref(reference['path']) == reference, 'Reference changed')
    return json.loads(Path(reference['path']).read_text())


class PreparationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config.json'
        self.path.write_text('{}')
        self.dependency = Path(self.temp.name) / 'source.py'
        self.dependency.write_text('original')
        self.reference = self.ref(self.path)
        self.protected = [self.reference, self.ref(self.dependency)]
        self.calls = []
        def original(reference):
            self.calls.append(dict(reference))
            if self.path.read_text() != '{}' or self.dependency.read_text() != 'original':
                raise ValueError('full validation rejected changed bytes')
            return dict(reference), {'nested': ['original']}
        self.original = original
        self.learning = SimpleNamespace(_execution=original)

    @staticmethod
    def ref(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_reuses_deep_copy_and_fully_revalidates_then_restores(self):
        with PreparationExecutionCache(self.learning, [self.reference], self.protected) as cache:
            first = self.learning._execution(self.reference)
            first[1]['nested'].append('mutated')
            self.assertEqual(self.learning._execution(self.reference)[1], {'nested': ['original']})
            self.assertEqual(len(self.calls), 1)
            cache.verify_complete()
            self.assertEqual(len(self.calls), 2)
        self.assertIs(self.learning._execution, self.original)
        self.assertEqual(cache.values, {})

    def test_changed_reference_rejected_and_exception_restores(self):
        with self.assertRaisesRegex(ValueError, 'reference changed'):
            with PreparationExecutionCache(self.learning, [self.reference], self.protected):
                self.learning._execution(self.reference)
                self.path.write_text('{"changed":true}')
                self.learning._execution(self.reference)
        self.assertIs(self.learning._execution, self.original)

    def test_changed_source_rejected_before_next_capture(self):
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            with PreparationExecutionCache(self.learning, [self.reference], self.protected) as cache:
                self.learning._execution(self.reference)
                self.dependency.write_text('changed bytes')
                cache.check_metadata()
        self.assertIs(self.learning._execution, self.original)

    def test_full_hash_catches_change_even_if_metadata_guard_is_bypassed(self):
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            with PreparationExecutionCache(self.learning, [self.reference], self.protected) as cache:
                self.learning._execution(self.reference)
                self.dependency.write_text('tampered')
                cache.metadata = {path: cache._stamp(path) for path in cache.protected}
                cache.verify_complete()
        self.assertIs(self.learning._execution, self.original)


class NativeTerminalTests(unittest.TestCase):
    def test_budget_terminal_does_not_rewrite_native_completion(self):
        submission = {'agent_completed': False, 'reason': 'NATIVE_WORKER_WALL_LIMIT'}
        audit = {'workers': [{'outcome': 'COMPLETE'}, {'outcome': 'BUDGET_TIMEOUT'}]}
        original = deepcopy(submission)
        self.assertTrue(approved_native_terminal(submission, audit))
        self.assertEqual(submission, original)

    def test_budget_terminal_requires_explicit_matching_native_reason_and_timeout(self):
        good = {'agent_completed': False, 'reason': 'NATIVE_WORKER_WALL_LIMIT'}
        for workers in [[], None, [{'outcome': 'COMPLETE'}], [{'outcome': 'FAILED'}],
                        [{'outcome': 'BUDGET_TIMEOUT'}, {'outcome': 'FAILED'}], [None]]:
            with self.subTest(workers=workers):
                self.assertFalse(approved_native_terminal(good, {'workers': workers}))
        for changed in [{'agent_completed': True}, {'reason': 'NATIVE_EXECUTION_FAILURE'},
                        {'agent_completed': 0}, {'agent_completed': None}]:
            with self.subTest(changed=changed):
                self.assertFalse(approved_native_terminal({**good, **changed},
                    {'workers': [{'outcome': 'BUDGET_TIMEOUT'}]}))

    def test_original_completed_terminal_remains_supported(self):
        self.assertTrue(approved_native_terminal(
            {'agent_completed': True, 'reason': 'WORKER_SUBMITTED'}, {'workers': [{'outcome': 'COMPLETE'}]}))


class RuntimeAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old_root, self.new_root = self.root / 'old', self.root / 'new'
        self.old_root.mkdir()
        self.new_root.mkdir()
        self.old_hashes, self.new_hashes = {}, {}
        for name in [*RUNTIME_CHANGED_PATHS, 'scripts/stable.py']:
            old_path, new_path = self.old_root / name, self.new_root / name
            old_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_text('original')
            new_path.write_text('changed' if name in RUNTIME_CHANGED_PATHS else 'original')
            self.old_hashes[name], self.new_hashes[name] = ref(old_path)['sha256'], ref(new_path)['sha256']
        self.old_ref = {'path': 'old-execution.json', 'sha256': 'a' * 64}
        self.old = {'source_root': str(self.old_root), 'source_sha256': self.old_hashes}
        self.freeze = {'schema': 'skhynix/grading-continuation-runtime-freeze/1.0',
            'previous_execution_reference': self.old_ref, 'old_source_root': str(self.old_root),
            'source_root': str(self.new_root), 'old_source_sha256': self.old_hashes,
            'source_sha256': self.new_hashes, 'changed_paths': RUNTIME_CHANGED_PATHS,
            'model_calls': 0, 'official_grader_runs': 0}
        self.args = SimpleNamespace(runtime_change=self.root / 'freeze.json', source_root=self.new_root,
            loader_preflight=self.root / 'loader.json')
        self.args.loader_preflight.write_text('{}')
        self.save()

    def save(self):
        self.args.runtime_change.write_text(json.dumps(self.freeze))

    def test_exact_three_file_revision_preserves_policy_binding(self):
        runtime, loader, fields = runtime_amendment(self.args, self.old_ref, self.old)
        self.assertEqual(runtime, ref(self.args.runtime_change))
        self.assertEqual(loader, ref(self.args.loader_preflight))
        self.assertEqual(fields['training_grade_hold_policy'], TRAINING_GRADE_HOLD_POLICY)
        self.assertEqual(fields['source_sha256'], self.new_hashes)
        self.assertNotIn('model', fields)

    def test_extra_source_change_is_rejected_even_when_receipt_hash_matches(self):
        path = self.new_root / 'scripts/stable.py'
        path.write_text('unreviewed')
        self.new_hashes['scripts/stable.py'] = ref(path)['sha256']
        self.save()
        with self.assertRaisesRegex(ValueError, 'unrelated files'):
            runtime_amendment(self.args, self.old_ref, self.old)

    def test_changed_source_bytes_rejected(self):
        (self.new_root / RUNTIME_CHANGED_PATHS[0]).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'runtime bytes changed'):
            runtime_amendment(self.args, self.old_ref, self.old)

    def test_revision_cannot_change_prior_execution_or_report_model_work(self):
        for key, value in [('previous_execution_reference', {'path': 'other', 'sha256': 'b' * 64}),
                           ('model_calls', 1), ('official_grader_runs', 1)]:
            with self.subTest(key=key):
                original = self.freeze[key]
                self.freeze[key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, 'reviewed training-only revision'):
                    runtime_amendment(self.args, self.old_ref, self.old)
                self.freeze[key] = original

    def test_remapped_unchanged_helper_must_stay_byte_identical(self):
        old_ref = ref(self.old_root / 'scripts/stable.py')
        self.assertEqual(runtime_reference(old_ref, self.old_root, self.new_root),
            ref(self.new_root / 'scripts/stable.py'))
        (self.new_root / 'scripts/stable.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'unrelated frozen helper'):
            runtime_reference(old_ref, self.old_root, self.new_root)


class AbortedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.art, self.cfg, self.base, self.system = [self.root / name for name in ('art', 'cfg', 'base', 'system')]
        for path in (self.art, self.cfg, self.base, self.system):
            path.mkdir()
        self.write(self.art / 'active-controller.json', {'original': 'v10'})
        self.write(self.art / 'active-controller-v10.json', {'original': 'v10'})
        self.specs, self.receipts = {}, {}
        for version, count in ((11, 0), (12, 18)):
            pipeline_root = self.base / ('pipeline-v' + str(version))
            training_root = self.base / ('training-120-v' + str(version - 2))
            execution = {'run_root': str(training_root),
                'native_control_root': str(self.system / ('skhynix-architecture-scale-001-native-v' + str(version - 1) + '/training-120')),
                'source_root': str(self.system / ('skhynix-architecture-scale-001-source-v' + str(version - 7)))}
            execution_ref = self.write(self.cfg / ('architecture_002_training_120_v' + str(version - 2) + '.json'), execution)
            controller = self.system / ('controller' + str(version) + '.py')
            controller.write_text('# immutable controller')
            pipeline = {'pipeline_root': str(pipeline_root), 'training_experiment_reference': execution_ref,
                'training_stages': [{}, {'execution_reference': execution_ref, 'learning_root': str(pipeline_root / 'learning-120')}],
                'pipeline_source_reference': ref(controller), 'reflection_native_root': str(self.system / ('reflection' + str(version))),
                'evaluation_native_root': str(self.system / ('evaluation' + str(version)))}
            pipeline_ref = self.write(self.cfg / ('architecture_002_pipeline_v' + str(version) + '.json'), pipeline)
            self.write(training_root / 'execution-authority.json', {'original_source_only': True})
            if count:
                self.write(pipeline_root / 'learning-120/learning-state.json', {'cells': {str(i): {} for i in range(count)}})
                self.write(pipeline_root / 'learning-120/catalog.json', {'captures': {str(i): {} for i in range(82)}})
            retained = self.tree_refs(pipeline_root) + self.tree_refs(training_root)
            intent_ref = self.write(self.art / ('source-recovery-' + str(version).zfill(3) + '.json.intent.json'),
                {'pipeline_reference': pipeline_ref, 'execution_reference': execution_ref,
                 'recovery_version': version, 'source_attempts': 86, 'model_calls': 0,
                 'official_grader_runs': 0, 'preserved_references': retained})
            value = {'schema': 'skhynix/aborted-prelaunch-preparation/1.0', 'status': 'ABORTED_BEFORE_NATIVE_WORK',
                'preparation_process_stopped': True, 'controller_driver_stopped': True, 'original_attempts_changed': False,
                'solver_retries': False, 'official_grader_retries': False, 'pipeline_events': 0, 'training_cells': 0,
                'native_workers': 0, 'model_calls': 0, 'official_grader_runs': 0, 'captured_source_cells': count,
                'partial_learning_outputs_consumed': False, 'captured_public_episodes': 82 if count else 0,
                'pipeline_reference': pipeline_ref, 'execution_reference': execution_ref,
                'pipeline_root': str(pipeline_root), 'training_root': str(training_root),
                'native_root': execution['native_control_root'], 'source_runtime_root': execution['source_root'],
                'active_predecessor_reference': ref(self.art / 'active-controller.json'), 'preserved_references': retained}
            name = 'prelaunch-abort-011.json' if version == 11 else 'prelaunch-abort-012-corrected.json'
            self.receipts[version] = self.write(self.art / name, value)
            self.specs[version] = {'receipt_name': name, 'receipt_sha256': self.receipts[version]['sha256'],
                'intent_sha256': intent_ref['sha256'], 'captured_source_cells': count}
        self.patcher = patch.dict(globals(), {'ART': self.art, 'CFG': self.cfg, 'BASE': self.base,
            'SYSTEM_TEMP': self.system, 'ABANDONED_PRELAUNCH_SPECS': self.specs,
            'read': lambda path: json.loads(Path(path).read_text()),
            'u': SimpleNamespace(tree_refs=self.tree_refs, verify_refs=self.verify_refs)})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        return ref(path)

    @staticmethod
    def tree_refs(root):
        return [ref(path) for path in sorted(root.rglob('*')) if path.is_file() and not path.name.endswith('.lock')]

    @staticmethod
    def verify_refs(references):
        for reference in references:
            require(ref(reference['path']) == reference, 'Preserved evidence changed')

    def test_both_aborts_preserve_the_eighteen_unused_retained_captures(self):
        values, references, preserved = abandoned_prelaunch_chain(self.receipts[12])
        self.assertEqual([value['captured_source_cells'] for value in values], [18, 0])
        self.assertEqual(references, [self.receipts[12], self.receipts[11]])
        self.assertEqual(len(preserved), len({item['path'] for item in preserved}))
        self.assertIn(self.receipts[11], preserved)

    def test_new_model_activity_is_rejected_even_without_repeating_bulk_hashes(self):
        path = self.base / 'pipeline-v12/events/00000001.json'
        self.write(path, {'unexpected': 'model work'})
        with self.assertRaisesRegex(ValueError, 'started a controller'):
            abandoned_prelaunch_chain(self.receipts[12], verify_preserved=False)

    def test_native_root_appearance_is_rejected(self):
        (self.system / 'skhynix-architecture-scale-001-native-v11/training-120').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'started a controller'):
            abandoned_prelaunch_chain(self.receipts[12], verify_preserved=False)

    def test_more_retained_captures_are_rejected(self):
        self.write(self.base / 'pipeline-v12/learning-120/learning-state.json', {'cells': {str(i): {} for i in range(19)}})
        with self.assertRaisesRegex(ValueError, 'learning advanced'):
            abandoned_prelaunch_chain(self.receipts[12], verify_preserved=False)

    def test_mutated_partial_capture_file_is_not_silently_reused(self):
        path = self.base / 'pipeline-v12/learning-120/catalog.json'
        value = json.loads(path.read_text())
        value['captures']['0'] = {'tampered': True}
        self.write(path, value)
        with self.assertRaises(ValueError):
            abandoned_prelaunch_chain(self.receipts[12])

    def test_new_unrecorded_learning_file_is_rejected(self):
        self.write(self.base / 'pipeline-v12/learning-120/new.json', {'unexpected': True})
        with self.assertRaisesRegex(ValueError, 'Unrecorded output'):
            abandoned_prelaunch_chain(self.receipts[12], verify_preserved=False)

    def test_wrong_abort_or_intent_identity_is_rejected(self):
        for version in (11, 12):
            with self.subTest(version=version):
                reference = {**self.receipts[version], 'sha256': '0' * 64}
                with self.assertRaisesRegex(ValueError, 'receipt changed'):
                    abandoned_prelaunch(reference)
        self.specs[12]['intent_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'intent bytes changed'):
            abandoned_prelaunch_chain(self.receipts[12])

    def test_conflicting_reference_hashes_fail_closed(self):
        reference = self.receipts[11]
        self.assertEqual(merge_references([reference, reference]), [reference])
        with self.assertRaisesRegex(ValueError, 'Conflicting preserved reference'):
            merge_references([reference, {**reference, 'sha256': '0' * 64}])


freeze = ast.parse(Path(__file__).with_name('freeze_skhynix_scale_runtime_v13.py').read_text())
freeze_nodes = [item for item in freeze.body if
    isinstance(item, ast.FunctionDef) and item.name == 'validate_revision_delta'
    or isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
        ('CHANGED', 'RUN_PATH') for target in item.targets)]
exec(compile(ast.Module(body=freeze_nodes, type_ignores=[]), '<freeze-delta>', 'exec'), globals())


class FreezeDeltaTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: 'original' for name in [*CHANGED, 'stable.py']}
        self.previous = {**self.original, **{name: 'v12' for name in CHANGED}}
        self.prospective = {**self.previous, RUN_PATH: 'request-local-validation'}

    def test_only_run_changes_from_v12_while_original_three_file_delta_remains(self):
        validate_revision_delta(self.original, self.previous, self.prospective)

    def test_unrelated_file_change_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_revision_delta(self.original, self.previous, {**self.prospective, 'stable.py': 'changed'})

    def test_another_reviewed_runtime_file_cannot_change_again(self):
        name = next(name for name in CHANGED if name != RUN_PATH)
        with self.assertRaisesRegex(ValueError, 'only request-local'):
            validate_revision_delta(self.original, self.previous, {**self.prospective, name: 'unreviewed'})

    def test_removing_source_file_or_omitting_run_fix_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inventory'):
            validate_revision_delta(self.original, self.previous, {RUN_PATH: 'only-file'})
        with self.assertRaisesRegex(ValueError, 'only request-local'):
            validate_revision_delta(self.original, self.previous, self.previous)


if __name__ == '__main__':
    unittest.main()


