"""Exercise the preparation-only cache without importing experiment runtime."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest


module = ast.parse(Path(__file__).with_name('prepare_skhynix_scale_recovery_v6.py').read_text())
node = next(item for item in module.body if isinstance(item, ast.ClassDef) and item.name == 'PreparationExecutionCache')
exec(compile(ast.Module(body=[node], type_ignores=[]), '<preparation-cache>', 'exec'), globals())


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


if __name__ == '__main__':
    unittest.main()
