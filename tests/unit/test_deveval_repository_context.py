"""Synthetic only: no real benchmark source, models, or grader execution."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_context as context

PROJECT = 'Synthetic/package'
MAIN = ('from .helpers import helper\n\n'
        'def target(value):\n'
        '    THIS IS PRIVATE GOLD $$$ NOT PARSEABLE\n'
        '    return helper(value) + 9000\n\n'
        'def sibling(value):\n'
        '    return value + 7000  # SIBLING_GOLD\n\n'
        'def visible(value):\n'
        '    return helper(value)\n')
HELPER = ('def helper(value):\n    return value + 1\n\n'
          'class Owner:\n    def method(self, value):\n        return helper(value)\n')


def metadata():
    common = {'project_path': PROJECT, 'completion_path': PROJECT + '/pkg/main.py', 'indent': 4,
              'requirement': {'Arguments': 'Synthetic integer input.', 'Functionality': 'Synthetic required behavior.'},
              'tests': ['checks.py::private_test'], 'type': 'function',
              'dependency': {'cross_file': ['PRIVATE_ANNOTATION_NOT_L2']}}
    return [{**deepcopy(common), 'namespace': 'pkg.main.target', 'signature_position': [3, 3], 'body_position': [4, 5]},
            {**deepcopy(common), 'namespace': 'pkg.main.sibling', 'signature_position': [7, 7], 'body_position': [8, 8]}]


def fixture(tmp_path, *, mutate_rows=None, extras=()):
    source = tmp_path / 'source.tar.gz'
    members = [('pkg/main.py', MAIN), ('pkg/helpers.py', HELPER),
               ('pkg/__init__.py', ''), ('checks.py', 'PRIVATE_TEST $$$'),
               ('tests/example.py', 'PRIVATE_TEST $$$'), ('pkg/conftest.py', 'PRIVATE_FIXTURE $$$'),
               ('fixture.json', '{"private":true}')]
    with tarfile.open(source, 'w:gz') as archive:
        for name, text in members:
            info = tarfile.TarInfo('Source_Code/' + PROJECT + '/' + name)
            raw = text.encode()
            info.size = len(raw)
            archive.addfile(info, BytesIO(raw))
        for info, raw in extras:
            archive.addfile(info, BytesIO(raw) if raw is not None else None)
    rows = metadata()
    if mutate_rows:
        mutate_rows(rows)
    metadata_path = tmp_path / 'metadata.jsonl'
    metadata_path.write_bytes(b''.join(context.canonical(row) for row in rows))
    archive_ref, metadata_ref = context.reference(source), context.reference(metadata_path)
    plan = {'schema': 'deveval/repository-plan/1', 'source_archive_reference': archive_ref,
            'metadata_reference': metadata_ref,
            'projects': [{'project': PROJECT, 'all_benchmark_target_count': 2}],
            'tasks': [{'task_id': 'pkg.main.target', 'project': PROJECT, 'phase': 'VALID'}]}
    plan_path = tmp_path / 'plan.json'
    plan_path.write_bytes(context.canonical(plan))
    return archive_ref, metadata_ref, context.reference(plan_path)


def materialize(tmp_path, **kwargs):
    archive, metadata_ref, plan = fixture(tmp_path, **kwargs)
    reference = context.materialize_repository(archive, metadata_ref, tmp_path / 'snapshot', project=PROJECT, plan_reference=plan)
    return context.load_snapshot(reference)


def test_all_project_bodies_masked_before_ast_and_private_tests_excluded(tmp_path):
    snapshot = materialize(tmp_path)
    text = snapshot.read_file('pkg/main.py')['text']
    assert 'PRIVATE GOLD' not in text and 'SIBLING_GOLD' not in text and '9000' not in text and '7000' not in text
    assert text.count('BENCHMARK_TARGET_BODY_WITHHELD') == 2
    assert set(snapshot.files) == {'pkg/main.py', 'pkg/helpers.py', 'pkg/__init__.py'}
    assert snapshot.manifest['counts']['masked_target_bodies'] == 2
    assert snapshot.manifest['gold_bodies_parsed_by_ast'] is False
    # Invalid syntax in a gold body succeeds only because it was redacted first.
    assert 'PRIVATE_ANNOTATION' not in json.dumps(snapshot.relations)
    for name in ('checks.py', 'tests/example.py', 'pkg/conftest.py', 'fixture.json'):
        with pytest.raises(context.RepositoryContextError, match='FILE_NOT_IN_VISIBLE_AUTHORITY'):
            snapshot.read_file(name)


def test_public_task_is_selected_requirement_signature_only(tmp_path):
    snapshot = materialize(tmp_path)
    task = snapshot.public_task('pkg.main.target')
    assert task['signature'] == 'def target(value):\n'
    assert task['masked_body_start'] == 4 and task['masked_body_end'] == 5 and task['body_indent'] == 4
    assert set(task['requirement']) == {'Arguments', 'Functionality'}
    assert not {'dependency', 'tests', 'gold', 'body'} & set(task)
    with pytest.raises(context.RepositoryContextError, match='TASK_NOT_SELECTED_BY_PLAN'):
        snapshot.public_task('pkg.main.sibling')


def test_visible_import_call_ownership_and_ppr_are_snapshot_bound(tmp_path):
    snapshot = materialize(tmp_path)
    edges = snapshot.relations['edges']
    assert any(e['kind'] == 'IMPORTS' and e['target'] == 'symbol:pkg/helpers.py:helper' for e in edges)
    assert any(e['kind'] == 'CALLS' and e['source'] == 'symbol:pkg/main.py:visible' and
               e['target'] == 'symbol:pkg/helpers.py:helper' for e in edges)
    assert any(e['kind'] == 'OWNS' and e['target'] == 'symbol:pkg/helpers.py:Owner.method' for e in edges)
    result = snapshot.retrieve('helper integer', task_id='pkg.main.target')
    assert any(r['path'] == 'pkg/helpers.py' for r in result['matches'])
    assert all(r['file_sha256'] == snapshot.files[r['path']]['sha256'] and
               r['snapshot_id'] == snapshot.manifest['snapshot_id'] for r in result['matches'])
    assert snapshot.search('return helper')['matches'][0]['path'] in snapshot.files


def test_candidate_copy_changes_only_target_and_preserves_original(tmp_path):
    snapshot = materialize(tmp_path)
    before = snapshot._bytes('pkg/main.py')
    result = context.apply_candidate(snapshot, 'pkg.main.target', 'return helper(value)\n', tmp_path / 'candidate')
    changed = (tmp_path / 'candidate/pkg/main.py').read_text()
    assert changed.count('BENCHMARK_TARGET_BODY_WITHHELD') == 1 and 'return helper(value)' in changed
    assert snapshot._bytes('pkg/main.py') == before
    assert not (tmp_path / 'candidate/checks.py').exists()
    assert result['other_benchmark_bodies_remain_masked'] and not result['private_tests_present']
    assert result['candidate_body_start'] == result['candidate_body_end'] == 4
    with pytest.raises(context.RepositoryContextError, match='CANDIDATE_OUTPUT_MUST_BE_FRESH'):
        context.apply_candidate(snapshot, 'pkg.main.target', 'return 1', tmp_path / 'candidate')


@pytest.mark.parametrize('mutation', ['visible_source', 'index', 'manifest'])
def test_post_materialization_tampering_fails_closed(tmp_path, mutation):
    snapshot = materialize(tmp_path)
    target = {'visible_source': snapshot.root / 'repository/pkg/main.py', 'index': snapshot.root / 'relations.json',
              'manifest': snapshot.root / 'snapshot.json'}[mutation]
    if mutation == 'index':
        value = json.loads(target.read_bytes()); value['nodes'] = []
        target.write_bytes(context.canonical(value))
    else:
        target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(context.RepositoryContextError):
        snapshot.retrieve('target helper', task_id='pkg.main.target')


@pytest.mark.parametrize('name', ['../outside.py', '/absolute.py', 'C:/escape.py', r'pkg\escape.py'])
def test_reader_never_escapes_visible_authority(tmp_path, name):
    snapshot = materialize(tmp_path)
    with pytest.raises(context.RepositoryContextError, match='UNSAFE_RELATIVE_PATH'):
        snapshot.read_file(name)


def test_bad_source_hash_blocks_before_materialization(tmp_path):
    archive, metadata_ref, plan = fixture(tmp_path)
    Path(archive['path']).write_bytes(b'changed')
    with pytest.raises(context.RepositoryContextError, match='REFERENCE_CHANGED'):
        context.materialize_repository(archive, metadata_ref, tmp_path / 'snapshot', project=PROJECT, plan_reference=plan)
    assert not (tmp_path / 'snapshot').exists()


def test_link_and_duplicate_archive_entries_rejected(tmp_path):
    info = tarfile.TarInfo('Source_Code/' + PROJECT + '/pkg/link.py')
    info.type = tarfile.SYMTYPE; info.linkname = '../../outside'
    with pytest.raises(context.RepositoryContextError, match='SOURCE_LINK_OR_SPECIAL_ENTRY'):
        materialize(tmp_path, extras=[(info, None)])
    assert not (tmp_path / 'snapshot').exists()


def test_overlapping_gold_bodies_and_extra_requirement_keys_rejected(tmp_path):
    def overlap(rows):
        rows[1]['signature_position'] = [3, 3]; rows[1]['body_position'] = [4, 5]
    with pytest.raises(context.RepositoryContextError, match='OVERLAPPING_TARGET_BODIES'):
        materialize(tmp_path, mutate_rows=overlap)


def test_same_pinned_inputs_produce_same_snapshot_identity(tmp_path):
    archive, metadata_ref, plan = fixture(tmp_path)
    refs = [context.materialize_repository(archive, metadata_ref, tmp_path / name,
            project=PROJECT, plan_reference=plan) for name in ('first', 'second')]
    snapshots = list(map(context.load_snapshot, refs))
    assert snapshots[0].manifest['snapshot_id'] == snapshots[1].manifest['snapshot_id']
    assert snapshots[0].relations == snapshots[1].relations


def test_leading_original_docstring_is_removed_before_ast():
    raw = b'def target(value):\n    """PRIVATE_ORIGINAL_DOCSTRING"""\n    return 9000\n'
    row = {'signature_position': [1, 1], 'body_position': [3, 3], 'indent': 4}
    sanitized, removed, total = context._redact(raw, [row])
    assert b'PRIVATE_ORIGINAL_DOCSTRING' not in sanitized and b'9000' not in sanitized
    assert removed == 2 and total == 3
    assert sanitized.count(b'BENCHMARK_TARGET_BODY_WITHHELD') == 1


def test_public_testing_utility_is_distinct_from_private_tests():
    assert not context._private_path('package/testing.py', set())
    assert context._private_path('package/testing.py', {'package/testing.py'})
    assert context._private_path('package/test_helpers.py', set())


def test_nonpython_fixture_paths_never_get_materialized(tmp_path):
    info = tarfile.TarInfo('Source_Code/' + PROJECT + '/assets/hostname:port/blob.data')
    info.size = 4
    snapshot = materialize(tmp_path, extras=[(info, b'data')])
    assert not any('hostname' in path for path in snapshot.files)


def test_benchmark_target_module_is_kept_but_never_overrides_private_test_policy():
    assert not context._private_path('setup.py', set(), target_file=True)
    assert not context._private_path('examples/helper.py', set(), target_file=True)
    assert context._private_path('checks.py', {'checks.py'}, target_file=True)
    assert context._private_path('tests/helper.py', set(), target_file=True)
