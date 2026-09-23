"""Opaque test-count audit and runnable negative controls; no model calls."""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
BASE = Path('/home/trimem-runner/skhynix-lcb-001')
DATA = BASE / 'data'
WORK = BASE / 'official-controls-002'
REPORTS = REPO / 'artifacts/skhynix_v1/lcb_001/official-controls-002'
CONTROL_IDS = ['abc372_a', '3593']

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canon(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()

def ref(path):
    raw = Path(path).read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}

def read(path):
    return json.loads(Path(path).read_bytes())

def checked(path, expected):
    raw = Path(path).read_bytes()
    assert sha(raw) == expected['sha256']
    if 'bytes' in expected:
        assert len(raw) == expected['bytes']
    return raw

def write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canon(value))

def run():
    started = time.monotonic()
    WORK.mkdir(exist_ok=False)
    REPORTS.mkdir(exist_ok=False)
    sys.path.insert(0, str(REPO / 'scripts'))
    import trimem_lcb_grade as grader
    config = read(REPO / 'configs/skhynix_v1/lcb_001_pilot.json')
    split_path = REPO / 'configs/skhynix_v1/lcb_001_public_split.json'
    split = json.loads(checked(split_path, {'sha256': config['split_sha256']}))
    old_receipt_path = REPO / 'artifacts/skhynix_v1/lcb_001/official-controls-001/control-receipt.json'
    old = json.loads(checked(old_receipt_path, {'sha256': config['official_control_receipt_sha256']}))
    assert old['status'] == 'PASS' and old['model_calls'] == 0
    assert ref(REPO / 'scripts/trimem_lcb_grade.py')['sha256'] == old['grader_reference']['sha256']
    public_ref = split['public_tasks_reference']
    public = {row['task_id']: row for line in checked(DATA / public_ref['path'], public_ref).splitlines()
              if line for row in [json.loads(line)]}
    samples, predictions, controls = [], [], []
    for identity in CONTROL_IDS:
        prior = next(row for row in old['control_tasks'] if row['question_id'] == identity)
        assert identity in config['infrastructure_control_excluded_train_ids']
        assert identity not in split['train_pilot_ids'] and public[identity]['split'] == 'train'
        sample_ref = prior['new_official_sample_reference']
        envelope = json.loads(gzip.decompress(checked(sample_ref['path'], sample_ref)))
        sample = envelope['samples'][0]
        assert sample['question_id'] == identity
        public_decoded = json.loads(public[identity]['public_evaluation_sample']['input_output'])
        fn_name = public_decoded.get('fn_name')
        if fn_name:
            assert fn_name.isidentifier()
            code = "class Solution:\n    def " + fn_name + "(self, *args, **kwargs):\n        return '__LCB_NEGATIVE_CONTROL_NO_MATCH__'\n"
        else:
            code = "print('__LCB_NEGATIVE_CONTROL_NO_MATCH__')\n"
        ast.parse(code)
        compile(code, '<infrastructure-negative-control>', 'exec')
        predictions.append({'question_id': identity, 'output': '```python\n' + code + '```'})
        samples.append(sample)
        controls.append({'question_id': identity, 'interface': 'FUNCTIONAL' if fn_name else 'STDIN',
            'public_function_name_used': bool(fn_name), 'syntax_valid': True,
            'candidate_sha256': sha(code.encode()), 'prior_pinned_sample_reference': sample_ref})
    dataset = {'schema': grader.SAMPLE_SCHEMA, 'samples': samples}
    prediction = {'schema': grader.PREDICTION_SCHEMA, 'expected_question_ids': CONTROL_IDS, 'predictions': predictions}
    write(WORK / 'runnable-wrong-predictions.json', prediction)
    with (WORK / 'official-control-samples.json.gz').open('xb') as stream:
        stream.write(gzip.compress(canon(dataset), mtime=0))
    with grader.quiet_grader():
        runtime = grader.load_official_runtime(BASE / 'LiveCodeBench', raw_rows=False)
    observations = []
    def observed_metrics(*args, **kwargs):
        result = runtime.metrics(*args, **kwargs)
        for index, item in enumerate(result[2]):
            meta = json.loads(item[0]) if isinstance(item[0], str) else item[0]
            observations.append({'question_id': CONTROL_IDS[index], 'official_error_code': meta.get('error_code')})
        return result
    instrumented = SimpleNamespace(**{**runtime.__dict__, 'metrics': observed_metrics})
    report = grader.grade_predictions(prediction, dataset, instrumented, workers=1, timeout=6)
    assert report['counts'] == {'planned': 2, 'predictions': 2, 'graded': 2, 'passed': 0, 'failed': 2, 'not_graded': 0, 'infra_errors': 0}
    assert len(observations) == 2 and all(row['official_error_code'] == -2 for row in observations)
    grader.verify_checkout(runtime.root)
    assert grader.validate_module_origins(runtime.root) == runtime.references
    receipt = {'schema': 'trimem/lcb-runnable-wrong-answer-control/1.0', 'status': 'PASS',
        'purpose': 'DIAGNOSTIC_INFRASTRUCTURE_CONTROL_NOT_MODEL_ACCURACY_OR_MEMORY_TRAINING',
        'original_control_receipt_reference': ref(old_receipt_path), 'helper_reference': ref(__file__),
        'grader_reference': ref(REPO / 'scripts/trimem_lcb_grade.py'), 'official_commit': grader.UPSTREAM_COMMIT,
        'official_modules': runtime.references, 'controls': controls, 'grade_report': report,
        'official_observations': observations, 'both_failed_as_wrong_answer': True,
        'control_predictions_reference': ref(WORK / 'runnable-wrong-predictions.json'),
        'control_dataset_reference': ref(WORK / 'official-control-samples.json.gz'),
        'model_calls': 0, 'memory_writes': 0, 'pilot_or_source_changes': 0,
        'private_content_printed_or_written_to_repository': False, 'wall_seconds': time.monotonic() - started}
    control_path = REPORTS / 'wrong-answer-control-002.json'
    write(control_path, receipt)
    print(json.dumps({'stage': 'RUNNABLE_WRONG_ANSWER_CONTROL', 'status': 'PASS', 'counts': report['counts'],
        'official_error_codes': [-2, -2], 'receipt_reference': ref(control_path)}), flush=True)

    ready = read(DATA / 'dataset-ready.json')
    manifest = json.loads(checked(DATA / 'dataset-manifest.json', ready['manifest_reference']))
    rows = []
    for role, identities in [('train', split['train_pilot_ids']), ('valid', split['pilot_ids'])]:
        for identity in identities:
            source = manifest['private_evaluation_files'][identity]
            packed = checked(DATA / source['path'], source)
            raw = gzip.decompress(packed)
            envelope = json.loads(raw)
            sample = envelope['samples'][0]
            assert sample['question_id'] == identity and len(envelope['samples']) == 1
            full = json.loads(sample['sample']['input_output'])
            visible = json.loads(public[identity]['public_evaluation_sample']['input_output'])
            n = len(visible['inputs'])
            assert len(full['inputs']) == len(full['outputs'])
            assert full['inputs'][:n] == visible['inputs'] and full['outputs'][:n] == visible['outputs']
            assert full.get('fn_name') == visible.get('fn_name') and len(full['inputs']) > n
            graded = []
            for arm in (['TRAIN'] if role == 'train' else ['OFF', 'ON']):
                prefix = 'train' if arm == 'TRAIN' else 'valid-' + arm.lower()
                path = REPO / 'data/skhynix_lcb_001/pilot-001/private-grades' / (prefix + '-' + sha(identity.encode())[:20]) / 'report.json'
                if path.exists():
                    actual = read(path)
                    assert actual['provenance']['dataset_reference']['sha256'] == sha(raw)
                    assert actual['provenance']['upstream_commit'] == grader.UPSTREAM_COMMIT
                    graded.append({'arm': arm, 'report_reference': ref(path), 'graded_exact_full_sample': True})
            rows.append({'task_id': identity, 'role': role, 'public_count': n,
                'official_all_count': len(full['inputs']), 'additional_private_count': len(full['inputs']) - n,
                'public_prefix_exactly_matches': True, 'manifest_sample_reference': source,
                'decompressed_sample_sha256': sha(raw), 'existing_pilot_grade_bindings': graded})
            del packed, raw, envelope, sample, full, visible
        print(json.dumps({'stage': 'TEST_COUNT_AUDIT', 'role': role, 'tasks': len(identities), 'status': 'PASS'}), flush=True)
    summaries = {}
    for role in ('train', 'valid'):
        selected = [row for row in rows if row['role'] == role]
        summaries[role] = {'tasks': len(selected), 'public_tests': sum(row['public_count'] for row in selected),
            'all_official_tests': sum(row['official_all_count'] for row in selected),
            'additional_private_tests': sum(row['additional_private_count'] for row in selected),
            'minimum_additional_private_tests_per_task': min(row['additional_private_count'] for row in selected)}
    counts = {'schema': 'trimem/lcb-private-test-count-audit/1.0', 'status': 'PASS',
        'helper_reference': ref(__file__), 'public_split_reference': ref(split_path),
        'dataset_manifest_reference': ref(DATA / 'dataset-manifest.json'), 'dataset_ready_reference': ref(DATA / 'dataset-ready.json'),
        'all_48_tasks_include_additional_private_tests': True, 'summaries': summaries,
        'existing_pilot_grade_reports_bound_to_exact_full_sample': sum(len(row['existing_pilot_grade_bindings']) for row in rows),
        'tasks': rows, 'test_contents_in_report': False, 'model_calls': 0,
        'pilot_accuracy_or_enrollment_changes': 0, 'overall_seconds': time.monotonic() - started}
    counts_path = REPORTS / 'pilot-test-count-audit-002.json'
    write(counts_path, counts)
    print(json.dumps({'stage': 'TEST_COUNT_AUDIT_COMPLETE', 'status': 'PASS', 'summaries': summaries,
        'bound_pilot_grade_reports': counts['existing_pilot_grade_reports_bound_to_exact_full_sample'],
        'receipt_reference': ref(counts_path)}), flush=True)

if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        import traceback
        print(json.dumps({'status': 'FAIL', 'error_type': type(exc).__name__,
            'frames': [{'function': item.name, 'line': item.lineno} for item in traceback.extract_tb(exc.__traceback__)]}), flush=True)
        sys.exit(1)
