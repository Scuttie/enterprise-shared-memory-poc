"""Prepare pinned LiveCodeBench data without exposing private tests or code.

Only public metadata and aggregate counts are printed. Downloads are resumable;
completed source files are checked against the pinned Hugging Face LFS hashes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request
import unicodedata

import trimem_lcb_grade as grader

DATASET_ID = 'livecodebench/code_generation_lite'
REVISION = '0fe84c3912ea0c4d4a78037083943e8f0c4dd505'
RELEASE = 'release_v6'
EXPECTED_COUNT = 1055
PILOT_SEED = 'skhynix-lcb-001/pilot/v1'
SOURCES = [
    ('test.jsonl', 1252609773, '2bd02b38beb48e8c46b5b9987095d999ff38cd8efc255ea5d58974317c48f63f'),
    ('test2.jsonl', 713377060, '095df7c5daf15f882c51a9deb84085cff1e073495a5dbcf95015a564d485f3a3'),
    ('test3.jsonl', 623360766, '28ed26cc83363ce3f1fe2d5fad9f8393077beb1907b167a31bd3b32f80801b79'),
    ('test4.jsonl', 1204644685, 'd711138ddaebfcf5f8ec6a4283ee677298c0f5c5d374a235af92aaf0584510da'),
    ('test5.jsonl', 557699297, '7f77571c2a6df0c2a72a3277650309f67e01e0008e18117e624633df53f81214'),
    ('test6.jsonl', 134303240, 'bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5'),
]


class DatasetPreparationError(ValueError):
    """A pinned source or preparation contract could not be verified."""


def _canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': _hash_file(path), 'bytes': path.stat().st_size}


def _write_once(path, raw):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != raw:
            raise DatasetPreparationError('Existing output differs')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def _check_file(path, size, sha):
    if not Path(path).is_file() or Path(path).stat().st_size != size or _hash_file(path) != sha:
        raise DatasetPreparationError('Pinned source checksum differs')


def download_file(url, destination, *, expected_size, expected_sha256, opener=urllib.request.urlopen,
                  reserve_paths=(), min_free_gib=10):
    """Resume a partial byte stream; only hash-verified bytes become final data."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _check_file(destination, expected_size, expected_sha256)
        return reference(destination)
    partial = destination.with_name(destination.name + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        raise DatasetPreparationError('Partial source exceeds the pinned size')
    if offset < expected_size:
        headers = {'User-Agent': 'trimem-lcb-dataset/1.0'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        with opener(urllib.request.Request(url, headers=headers), timeout=120) as response:
            status = response.status
            if status == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if not match or int(match[1]) != offset or int(match[3]) != expected_size:
                    raise DatasetPreparationError('Resume range does not match the pinned source')
            elif status == 200:
                offset = 0  # Server ignored Range; restart the unpublished partial file.
            else:
                raise DatasetPreparationError('Download did not return a byte stream')
            with partial.open('ab' if offset else 'wb') as stream:
                for block in iter(lambda: response.read(4 * 1024 * 1024), b''):
                    offset += len(block)
                    if offset > expected_size:
                        raise DatasetPreparationError('Download exceeds the pinned source size')
                    _reserve(reserve_paths, min_free_gib, required_bytes=len(block))
                    stream.write(block)
    _check_file(partial, expected_size, expected_sha256)
    os.link(partial, destination)  # Exclusive publication: never replace a final source.
    partial.unlink()
    return reference(destination)


def download_sources(data_root, *, reserve_paths=(), min_free_gib=10):
    data_root = Path(data_root).expanduser().resolve()
    raw_root = data_root / 'raw'
    raw_root.mkdir(parents=True, exist_ok=True)
    _write_once(data_root / 'source-authority.json', _canonical({
        'schema': 'trimem/lcb-source-authority/1.0', 'dataset_id': DATASET_ID,
        'revision': REVISION, 'release': RELEASE,
        'files': [{'name': name, 'bytes': size, 'sha256': sha} for name, size, sha in SOURCES]}))
    def fetch(item):
        name, size, sha = item
        print(json.dumps({'stage': 'DOWNLOAD', 'file': name, 'bytes': size}), flush=True)
        url = f'https://huggingface.co/datasets/{DATASET_ID}/resolve/{REVISION}/{name}?download=true'
        for attempt in range(3):
            try:
                ref = download_file(url, raw_root / name, expected_size=size, expected_sha256=sha,
                                    reserve_paths=[data_root, *reserve_paths], min_free_gib=min_free_gib)
                print(json.dumps({'stage': 'VERIFIED', 'file': name, 'bytes': size, 'sha256': sha}), flush=True)
                return ref
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        refs = list(pool.map(fetch, SOURCES))
    result = {'schema': 'trimem/lcb-source-download/1.0', 'dataset_id': DATASET_ID,
              'revision': REVISION, 'release': RELEASE, 'sources': refs}
    _write_once(data_root / 'source-download.json', _canonical(result))
    return result


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def _date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _nominal_split(value):
    date = _date(value)
    if date < datetime(2024, 11, 1, tzinfo=timezone.utc):
        return 'train'
    if date < datetime(2025, 1, 1, tzinfo=timezone.utc):
        return 'valid'
    return 'test'


def make_split(rows, *, pilot_size=24):
    """Move entire connected families forward; selection never observes outcomes."""
    ids = [row['task_id'] for row in rows]
    if len(set(ids)) != len(ids) or any(not isinstance(task, str) or not task for task in ids):
        raise DatasetPreparationError('Task identities must be globally unique')
    parents = list(range(len(rows)))
    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parents[max(left, right)] = min(left, right)
    prompts, contests = {}, {}
    for index, row in enumerate(rows):
        fingerprint = _digest([_normalize(row['prompt']), _normalize(row['starter_code'])])
        if fingerprint in prompts:
            union(index, prompts[fingerprint])
        prompts[fingerprint] = index
        contest = str(row['contest_id']).strip()
        if contest:
            key = (row['platform'], contest)
            if key in contests:
                union(index, contests[key])
            contests[key] = index
    groups = {}
    for index in range(len(rows)):
        groups.setdefault(find(index), []).append(index)
    rank = {'train': 0, 'valid': 1, 'test': 2}
    reassigned = []
    for members in groups.values():
        split = max((_nominal_split(rows[index]['contest_date']) for index in members), key=rank.get)
        family_id = _digest(sorted(rows[index]['task_id'] for index in members))
        for index in members:
            row = rows[index]
            original = _nominal_split(row['contest_date'])
            row.update(split=split, family_id=family_id)
            if original != split:
                reassigned.append({'task_id': row['task_id'], 'from': original, 'to': split, 'family_id': family_id})
    ordered = sorted(rows, key=lambda row: (_date(row['contest_date']), row['task_id']))
    splits = {name: [row['task_id'] for row in ordered if row['split'] == name] for name in rank}
    def pilot_key(row):
        return hashlib.sha256((PILOT_SEED + '\0' + row['task_id']).encode()).hexdigest(), row['task_id']
    quota = pilot_size // 3
    def select_pilot(partition):
        pool = [row for row in ordered if row['split'] == partition]
        if len(pool) < pilot_size:
            raise DatasetPreparationError('Partition cannot provide the requested pilot size')
        selected = []
        for difficulty in ('easy', 'medium', 'hard'):
            selected.extend(sorted((row for row in pool if row['difficulty'] == difficulty), key=pilot_key)[:quota])
        chosen = {row['task_id'] for row in selected}
        selected.extend(sorted((row for row in pool if row['task_id'] not in chosen), key=pilot_key)[:pilot_size - len(selected)])
        return sorted(selected, key=pilot_key)
    pilot, train_pilot = select_pilot('valid'), select_pilot('train')
    return {'schema': 'trimem/lcb-split/1.0', 'dataset_id': DATASET_ID, 'source_revision': REVISION,
        'release': RELEASE, 'split_policy': {
            'train_before_utc': '2024-11-01T00:00:00Z', 'valid_before_utc': '2025-01-01T00:00:00Z',
            'test_at_or_after_utc': '2025-01-01T00:00:00Z',
            'families': ['exact NFKC/whitespace-normalized (prompt,starter_code) pair',
                         'same (platform,nonempty contest_id)'],
            'family_partition': 'latest nominal member partition; transitive union',
            'id_order': 'contest_date UTC then task_id', 'model_calls': 0},
        'pilot_policy': {'seed': PILOT_SEED, 'size': pilot_size, 'selection': 'SHA256(seed+NUL+task_id)',
                         'difficulty_quota': quota, 'shortfall': 'fill remaining by same hash ordering'},
        **{name + '_ids': values for name, values in splits.items()},
        'pilot_ids': [row['task_id'] for row in pilot],
        'train_pilot_ids': [row['task_id'] for row in train_pilot],
        'pilot_difficulty_counts': {level: sum(row['difficulty'] == level for row in pilot)
                                    for level in ('easy', 'medium', 'hard')},
        'train_pilot_difficulty_counts': {level: sum(row['difficulty'] == level for row in train_pilot)
                                          for level in ('easy', 'medium', 'hard')},
        'counts': {**{name: len(values) for name, values in splits.items()}, 'total': len(rows),
                   'families': len(groups), 'reassigned': len(reassigned)},
        'family_reassignments': sorted(reassigned, key=lambda row: row['task_id']),
        'task_families': {row['task_id']: row['family_id'] for row in ordered},
        'task_descriptors': [{key: row[key] for key in ('task_id', 'split', 'family_id',
                             'instruction_sha256', 'public_tests_sha256', 'difficulty', 'contest_date')}
                             for row in ordered]}


def public_problem(problem, source_reference):
    """Project only public examples; never call the combined evaluation getter."""
    tests = [{'input': test.input, 'output': test.output, 'testtype': test.testtype.value}
             for test in problem.public_test_cases]
    sample = {'input_output': json.dumps({'inputs': [test['input'] for test in tests],
        'outputs': [test['output'] for test in tests], 'fn_name': problem.metadata.get('func_name')},
        ensure_ascii=False, separators=(',', ':'))}
    row = {'schema': 'trimem/lcb-public-task/1.0', 'task_id': problem.question_id,
        'question_id': problem.question_id, 'platform': problem.platform.value,
        'contest_id': problem.contest_id, 'contest_date': problem.contest_date.isoformat(),
        'difficulty': problem.difficulty.value, 'question_title': problem.question_title,
        'prompt': problem.question_content, 'starter_code': problem.starter_code,
        'public_test_cases': tests, 'public_evaluation_sample': sample, 'source_reference': source_reference}
    row['instruction_sha256'] = _digest({key: row[key] for key in ('question_title', 'prompt', 'starter_code')})
    row['public_tests_sha256'] = _digest(sample)
    return row


def _write_gzip_once(path, value, *, reserve_paths=(), min_free_gib=10):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.part')
    with temporary.open('wb') as raw:
        class ReservedWriter:
            def write(self, data):
                _reserve(reserve_paths, min_free_gib, required_bytes=len(data))
                return raw.write(data)
            def __getattr__(self, name):
                return getattr(raw, name)
        with gzip.GzipFile(filename='', fileobj=ReservedWriter(), mode='wb', mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding='utf-8', newline='\n') as stream:
                json.dump(value, stream, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
                stream.write('\n')
    if path.exists():
        if _hash_file(path) != _hash_file(temporary):
            raise DatasetPreparationError('Existing private export differs')
    else:
        os.link(temporary, path)
    temporary.unlink()


def _reserve(paths, min_free_gib, *, required_bytes=0):
    for path in paths:
        if shutil.disk_usage(path).free - required_bytes < min_free_gib * 2**30:
            raise DatasetPreparationError('Disk reserve would be exhausted')


def export_dataset(data_root, official_repo, split_output, *, reserve_paths=(), min_free_gib=10):
    data_root = Path(data_root).expanduser().resolve(strict=True)
    _reserve([data_root, *reserve_paths], min_free_gib)
    # Verify ALL raw bytes before the official constructor can decode its pickle.
    source_refs = []
    for name, size, sha in SOURCES:
        path = data_root / 'raw' / name
        _check_file(path, size, sha)
        source_refs.append({'path': 'raw/' + name, 'sha256': sha, 'bytes': size})
    runtime = grader.load_official_runtime(official_repo, raw_rows=True)
    public_rows, private_files, source_schema = [], {}, {}
    for source in source_refs:
        with (data_root / source['path']).open('rb') as stream:
            for line_number, raw_line in enumerate(stream, 1):
                if not raw_line.strip():
                    continue
                raw = grader.parse_json(raw_line)
                for key, value in raw.items():
                    source_schema.setdefault(key, set()).add(type(value).__name__)
                problem = runtime.problem_class(**raw)
                identity = problem.question_id
                if not isinstance(identity, str) or not identity or identity in private_files:
                    raise DatasetPreparationError('Source identity is missing or duplicated')
                source_ref = {'file': source['path'], 'sha256': source['sha256'], 'line': line_number,
                              'row_sha256': hashlib.sha256(raw_line).hexdigest()}
                public_rows.append(public_problem(problem, source_ref))
                filename = hashlib.sha256(identity.encode()).hexdigest() + '.json.gz'
                private_path = data_root / 'private' / filename
                envelope = {'schema': grader.SAMPLE_SCHEMA, 'provenance': {
                    'dataset_id': DATASET_ID, 'revision': REVISION, 'release': RELEASE,
                    'source_reference': source_ref, 'upstream_commit': grader.UPSTREAM_COMMIT},
                    'samples': [{'question_id': identity, 'sample': problem.get_evaluation_sample()}]}
                _write_gzip_once(private_path, envelope, reserve_paths=[data_root, *reserve_paths],
                                 min_free_gib=min_free_gib)
                private_files[identity] = {**reference(private_path), 'path': 'private/' + filename, 'format': 'gzip-json'}
                _reserve([data_root, *reserve_paths], min_free_gib)
                if len(public_rows) % 50 == 0:
                    print(json.dumps({'stage': 'EXPORTED', 'tasks': len(public_rows)}), flush=True)
                del problem, raw, envelope
    if len(public_rows) != EXPECTED_COUNT:
        raise DatasetPreparationError('Pinned release task count differs')
    split = make_split(public_rows)
    public_rows.sort(key=lambda row: (_date(row['contest_date']), row['task_id']))
    public_path = data_root / 'public' / 'tasks.jsonl'
    _write_once(public_path, b''.join(_canonical(row) for row in public_rows))
    # Catch any mutation of pinned source or official code during export.
    for name, size, sha in SOURCES:
        _check_file(data_root / 'raw' / name, size, sha)
    grader.verify_checkout(runtime.root)
    if grader.validate_module_origins(runtime.root) != runtime.references:
        raise DatasetPreparationError('Official source changed during export')
    manifest = {'schema': 'trimem/lcb-dataset/1.0', 'dataset_id': DATASET_ID, 'revision': REVISION,
        'release': RELEASE, 'task_count': len(public_rows), 'source_files': source_refs,
        'source_schema': {key: sorted(types) for key, types in sorted(source_schema.items())},
        'official_source': {'commit': grader.UPSTREAM_COMMIT, 'modules': {
            name: {'path': str(Path(ref['path']).relative_to(runtime.root)), 'sha256': ref['sha256']}
            for name, ref in runtime.references.items()}},
        'exporter_reference': {**reference(__file__), 'path': 'scripts/trimem_lcb_dataset.py'},
        'public_tasks_reference': {**reference(public_path), 'path': 'public/tasks.jsonl'},
        'private_evaluation_files': private_files, 'counts': split['counts'],
        'model_calls': 0, 'grader_runs': 0, 'docker_calls': 0}
    manifest_path = data_root / 'dataset-manifest.json'
    _write_once(manifest_path, _canonical(manifest))
    split.update(dataset_reference={**reference(manifest_path), 'path': 'dataset-manifest.json'}, source_hashes=source_refs,
                 public_tasks_reference=manifest['public_tasks_reference'],
                 exporter_reference=manifest['exporter_reference'])
    _write_once(split_output, _canonical(split))
    return {'manifest_reference': reference(manifest_path), 'split_reference': reference(split_output),
            'counts': split['counts'], 'pilot_difficulty_counts': split['pilot_difficulty_counts'],
            'train_pilot_difficulty_counts': split['train_pilot_difficulty_counts'],
            'public_bytes': public_path.stat().st_size,
            'private_compressed_bytes': sum(ref['bytes'] for ref in private_files.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['download', 'export'])
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--official-repo', type=Path)
    parser.add_argument('--split-output', type=Path)
    parser.add_argument('--reserve-path', action='append', type=Path, default=[])
    parser.add_argument('--min-free-gib', type=float, default=10)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'download':
            result = download_sources(args.data_root, reserve_paths=args.reserve_path, min_free_gib=args.min_free_gib)
            print(json.dumps({'status': 'COMPLETE', 'source_count': len(result['sources']),
                              'total_source_bytes': sum(row['bytes'] for row in result['sources'])}))
        else:
            if args.official_repo is None or args.split_output is None:
                raise DatasetPreparationError('Export requires official repository and split output')
            result = export_dataset(args.data_root, args.official_repo, args.split_output,
                                    reserve_paths=args.reserve_path, min_free_gib=args.min_free_gib)
            print(json.dumps({'status': 'COMPLETE', **result}))
        return 0
    except Exception as exc:
        # Never include a remote body, source row, or arbitrary exception message.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
