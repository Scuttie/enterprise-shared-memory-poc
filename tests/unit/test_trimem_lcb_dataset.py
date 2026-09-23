"""Synthetic source integrity, partition leakage, and private projection tests."""
import copy
from datetime import datetime
import gzip
import hashlib
import io
import json
from types import SimpleNamespace

import pytest

import trimem_lcb_dataset as dataset


def row(identity, date, *, prompt=None, starter='', contest='', platform='synthetic', difficulty='easy'):
    return {'task_id': identity, 'contest_date': date, 'prompt': prompt or identity,
            'starter_code': starter, 'contest_id': contest, 'platform': platform,
            'difficulty': difficulty, 'instruction_sha256': 'a' * 64, 'public_tests_sha256': 'b' * 64}


def test_temporal_boundaries_and_transitive_families_move_only_forward():
    rows = [row('a', '2024-10-01', contest='contest-1'),
            row('b', '2024-11-01', contest='contest-1', prompt='same  prompt'),
            row('c', '2025-01-01', prompt='same\nprompt'),
            row('d', '2024-10-31T23:59:59'), row('e', '2024-12-31T23:59:59'),
            row('f', '2025-01-01T00:00:00'),
            row('g', '2024-10-01', contest='contest-1', platform='different-platform')]
    result = dataset.make_split(rows, pilot_size=0)
    assert result['train_ids'] == ['g', 'd']
    assert result['valid_ids'] == ['e']
    assert result['test_ids'] == ['a', 'b', 'c', 'f']
    assert {item['task_id'] for item in result['family_reassignments']} == {'a', 'b'}
    assert len({result['task_families'][task] for task in ('a', 'b', 'c')}) == 1
    family_sets = [{result['task_families'][task] for task in result[name + '_ids']}
                   for name in ('train', 'valid', 'test')]
    assert not (family_sets[0] & family_sets[1] or family_sets[0] & family_sets[2] or family_sets[1] & family_sets[2])


def test_empty_contest_and_shared_starter_do_not_merge_distinct_prompts():
    rows = [row('train', '2024-01-01', starter='class Solution: pass'),
            row('valid', '2024-11-01', starter='class Solution: pass')]
    result = dataset.make_split(rows, pilot_size=0)
    assert result['counts']['families'] == 2
    assert result['train_ids'] == ['train'] and result['valid_ids'] == ['valid']


def test_both_pilots_are_balanced_deterministic_and_stay_inside_partition():
    rows = [row(f'{partition}-{difficulty}-{index}', date, difficulty=difficulty)
            for partition, date in [('train', '2024-01-01'), ('valid', '2024-11-01')]
            for difficulty in ('easy', 'medium', 'hard') for index in range(9)]
    forward = dataset.make_split(copy.deepcopy(rows))
    reversed_order = dataset.make_split(list(reversed(copy.deepcopy(rows))))
    assert forward == reversed_order
    for prefix, partition in [('', 'valid'), ('train_', 'train')]:
        assert len(forward[prefix + 'pilot_ids']) == 24
        assert set(forward[prefix + 'pilot_ids']) <= set(forward[partition + '_ids'])
        assert forward[prefix + 'pilot_difficulty_counts'] == {'easy': 8, 'medium': 8, 'hard': 8}
    assert not set(forward['pilot_ids']) & set(forward['train_pilot_ids'])


def test_duplicate_ids_rejected_even_across_distinct_platforms():
    with pytest.raises(dataset.DatasetPreparationError):
        dataset.make_split([row('same', '2024-01-01'), row('same', '2025-01-01', platform='other')], pilot_size=0)


def test_public_projection_does_not_access_or_emit_private_tests():
    class Problem:
        question_id = 'public-fixture'
        question_title = 'Synthetic task'
        question_content = 'Add values'
        platform = SimpleNamespace(value='synthetic')
        contest_id = 'one'
        contest_date = datetime(2024, 1, 1)
        difficulty = SimpleNamespace(value='easy')
        starter_code = ''
        public_test_cases = [SimpleNamespace(input='1', output='2', testtype=SimpleNamespace(value='functional'))]
        metadata = {'func_name': 'add', 'private_extra': 'NEVER_EXPORT_THIS'}
        @property
        def private_test_cases(self):
            pytest.fail('Public projection accessed hidden tests')
        def get_evaluation_sample(self):
            pytest.fail('Public projection requested combined private sample')
    public = dataset.public_problem(Problem(), {'file': 'synthetic.jsonl', 'line': 1})
    sample = json.loads(public['public_evaluation_sample']['input_output'])
    assert sample == {'inputs': ['1'], 'outputs': ['2'], 'fn_name': 'add'}
    assert 'NEVER_EXPORT_THIS' not in json.dumps(public)
    assert 'private_test_cases' not in public
    assert public['public_tests_sha256'] == dataset._digest(public['public_evaluation_sample'])


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def test_download_restart_validates_range_and_whole_file_hash(tmp_path):
    body = b'public synthetic source bytes'
    destination = tmp_path / 'source.jsonl'
    destination.with_suffix('.jsonl.part').write_bytes(body[:7])
    def opener(request, **kwargs):
        assert request.headers['Range'] == 'bytes=7-'
        return Response(body[7:], 206, {'Content-Range': f'bytes 7-{len(body)-1}/{len(body)}'})
    sha = hashlib.sha256(body).hexdigest()
    ref = dataset.download_file('https://synthetic.invalid/source', destination,
        expected_size=len(body), expected_sha256=sha, opener=opener)
    assert ref['sha256'] == sha and destination.read_bytes() == body
    assert not destination.with_suffix('.jsonl.part').exists()
    dataset.download_file('https://synthetic.invalid/source', destination,
        expected_size=len(body), expected_sha256=sha, opener=lambda *a, **k: pytest.fail('Already verified'))


@pytest.mark.parametrize('failure', ['wrong_hash', 'wrong_range', 'changed_final'])
def test_corrupt_download_is_never_published_or_overwrites_existing(tmp_path, failure):
    destination = tmp_path / 'source.jsonl'
    body = b'source'
    sha = hashlib.sha256(body).hexdigest()
    if failure == 'changed_final':
        destination.write_bytes(b'BROKEN')
    elif failure == 'wrong_range':
        destination.with_suffix('.jsonl.part').write_bytes(body[:2])
    def opener(*args, **kwargs):
        if failure == 'wrong_range':
            return Response(body[2:], 206, {'Content-Range': 'bytes 0-5/6'})
        return Response(b'BROKEN')
    with pytest.raises(dataset.DatasetPreparationError):
        dataset.download_file('https://synthetic.invalid/source', destination,
            expected_size=len(body), expected_sha256=sha, opener=opener)
    if failure == 'changed_final':
        assert destination.read_bytes() == b'BROKEN'
    else:
        assert not destination.exists()


def test_deterministic_private_gzip_restart_and_changed_content_rejection(tmp_path):
    path = tmp_path / 'private.json.gz'
    value = {'schema': 'synthetic', 'sample': 'private sentinel'}
    dataset._write_gzip_once(path, value)
    original = path.read_bytes()
    dataset._write_gzip_once(path, value)
    assert path.read_bytes() == original
    assert json.loads(gzip.decompress(original)) == value
    with pytest.raises(dataset.DatasetPreparationError):
        dataset._write_gzip_once(path, {'sample': 'different'})
    assert path.read_bytes() == original


def test_disk_reserve_checks_pending_write_not_only_current_free(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10 * 2**30 + 10))
    with pytest.raises(dataset.DatasetPreparationError):
        dataset._reserve([tmp_path], 10, required_bytes=11)


def test_every_source_hash_is_checked_before_official_decoder_is_loaded(tmp_path, monkeypatch):
    raw_root = tmp_path / 'raw'
    raw_root.mkdir()
    (raw_root / 'one.jsonl').write_bytes(b'valid')
    (raw_root / 'two.jsonl').write_bytes(b'BAD!')
    monkeypatch.setattr(dataset, 'SOURCES', [
        ('one.jsonl', 5, hashlib.sha256(b'valid').hexdigest()),
        ('two.jsonl', 4, hashlib.sha256(b'good').hexdigest())])
    monkeypatch.setattr(dataset.grader, 'load_official_runtime',
                        lambda *a, **k: pytest.fail('No private decoder before all source hashes pass'))
    with pytest.raises(dataset.DatasetPreparationError):
        dataset.export_dataset(tmp_path, tmp_path, tmp_path / 'split.json', min_free_gib=0)
    assert not (tmp_path / 'private').exists()
