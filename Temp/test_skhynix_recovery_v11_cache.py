"""Exercise the preparation-only cache without importing experiment runtime."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest


module = ast.parse(Path(__file__).with_name('prepare_skhynix_scale_recovery_v11.py').read_text())
nodes = [item for item in module.body if
    isinstance(item, (ast.ClassDef, ast.FunctionDef)) and item.name in
        ('PreparationExecutionCache', 'runtime_amendment', 'runtime_reference', 'approved_native_terminal')
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


if __name__ == '__main__':
    unittest.main()
