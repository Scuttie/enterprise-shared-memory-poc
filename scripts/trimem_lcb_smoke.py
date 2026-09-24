"""Check a local LiveCodeBench grader with public synthetic correct/wrong code.

This is an installation check, not a benchmark score. No model, network,
dataset download, or Docker service is used. Run with the Python environment
that contains the official evaluator dependencies; every child uses that same
interpreter. The output directory must not exist, even if it would be empty.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import trimem_lcb_grade as grader


SCHEMA = 'trimem/lcb-synthetic-smoke/1.0'
QUESTION_IDS = ['synthetic-stdio-add', 'synthetic-functional-double']
CHILD_TIMEOUT_SECONDS = 180


class SmokeValidationError(ValueError):
    """The grader did not distinguish the declared correct and wrong code."""


def _reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return _reference(path)


def synthetic_inputs():
    """Public fixtures only; no LiveCodeBench problem or test data is loaded."""
    dataset = {'schema': grader.SAMPLE_SCHEMA, 'provenance': {
        'kind': 'PUBLIC_SYNTHETIC_INSTALLATION_CHECK', 'actual_benchmark_data': False},
        'samples': [
            {'question_id': QUESTION_IDS[0], 'sample': {'input_output': json.dumps({
                'inputs': ['2 5\n', '-3 9\n'], 'outputs': ['7\n', '6\n'], 'fn_name': None})}},
            {'question_id': QUESTION_IDS[1], 'sample': {'input_output': json.dumps({
                'inputs': ['3', '-2'], 'outputs': ['6', '-4'], 'fn_name': 'double'})}},
        ]}
    bodies = {
        'correct': ['print(sum(map(int, input().split())))',
                    'class Solution:\n    def double(self, value):\n        return 2 * value'],
        'wrong': ['print(0)', 'class Solution:\n    def double(self, value):\n        return 0'],
    }
    predictions = {kind: {'schema': grader.PREDICTION_SCHEMA,
        'expected_question_ids': list(QUESTION_IDS), 'predictions': [
            {'question_id': identity, 'output': f'```python\n{body}\n```'}
            for identity, body in zip(QUESTION_IDS, code)]} for kind, code in bodies.items()}
    return dataset, predictions


def validate_report(report, *, kind, dataset_reference, predictions_reference, official_repo):
    """Require actual graded outcomes, never count infrastructure as rejection."""
    passed = kind == 'correct'
    expected_count = 2 if passed else 0
    counts = {'planned': 2, 'predictions': 2, 'graded': 2, 'passed': expected_count,
              'failed': 2 - expected_count, 'not_graded': 0, 'infra_errors': 0}
    if (kind not in {'correct', 'wrong'} or not isinstance(report, dict)
            or report.get('schema') != grader.REPORT_SCHEMA or report.get('status') != 'COMPLETE'
            or report.get('cohort_scope') != 'DECLARED_EXPECTED_IDS'
            or report.get('counts') != counts):
        raise SmokeValidationError('Grading must complete for both synthetic problems')
    if any(type(report['counts'][name]) is not int for name in counts):
        raise SmokeValidationError('Grading counts must be integers')
    for metric in ('pass_at_1', 'graded_pass_at_1'):
        value = report.get(metric)
        if type(value) not in (int, float) or value != expected_count / 2:
            raise SmokeValidationError('Synthetic success rate differs')
    rows = report.get('results')
    if (not isinstance(rows, list) or len(rows) != 2
            or any(not isinstance(row, dict) for row in rows)
            or [row.get('question_id') for row in rows] != QUESTION_IDS
            or any(row.get('status') != 'GRADED' or row.get('passed') is not passed for row in rows)):
        raise SmokeValidationError('Per-problem evidence differs from the expected outcome')
    settings = report.get('settings', {})
    if any(settings.get(key) != value for key, value in {
            'timeout_seconds': 6, 'workers': 1, 'generations_per_question': 1,
            'extraction_style': 'OpenAIChat', 'k_list': [1],
            'dataset_downloads': False, 'model_calls': 0}.items()):
        raise SmokeValidationError('Grader settings differ')
    provenance = report.get('provenance', {})
    if (provenance.get('upstream_commit') != grader.UPSTREAM_COMMIT
            or provenance.get('official_repo') != str(Path(official_repo).resolve())
            or provenance.get('dataset_reference') != dataset_reference
            or provenance.get('predictions_reference') != predictions_reference):
        raise SmokeValidationError('Grader inputs or official source binding differs')
    return counts


def run_smoke(official_repo, output_dir):
    official_repo = Path(official_repo).expanduser().resolve(strict=True)
    adapter = Path(grader.__file__).resolve()
    if not official_repo.is_dir() or not adapter.is_file():
        raise SmokeValidationError('Local source paths must exist')
    # mkdir is exclusive, including existing empty directories and symlinks.
    output_dir = Path(output_dir).expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir = output_dir.resolve()
    source_refs = {'smoke': _reference(__file__), 'adapter': _reference(adapter)}
    dataset, predictions = synthetic_inputs()
    dataset_ref = _write_json(output_dir / 'synthetic-samples.json', dataset)
    runs = {}
    for kind in ('correct', 'wrong'):
        prediction_ref = _write_json(output_dir / f'{kind}-predictions.json', predictions[kind])
        grade_path = output_dir / f'{kind}-grade.json'
        argv = [sys.executable, str(adapter), '--official-repo', str(official_repo),
                '--dataset-json', dataset_ref['path'], '--dataset-sha256', dataset_ref['sha256'],
                '--predictions', prediction_ref['path'], '--output', str(grade_path),
                '--workers', '1', '--timeout', '6']
        row = {'status': 'FAIL', 'predictions_reference': prediction_ref, 'command': argv}
        runs[kind] = row
        try:
            child = subprocess.run(argv, cwd=output_dir, capture_output=True, check=False,
                timeout=CHILD_TIMEOUT_SECONDS,
                env={**os.environ, 'HF_DATASETS_OFFLINE': '1', 'HF_HUB_OFFLINE': '1',
                     'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'})
            row['returncode'] = child.returncode
            for name, raw in [('stdout', child.stdout), ('stderr', child.stderr)]:
                path = output_dir / f'{kind}-{name}.txt'
                with path.open('xb') as stream:
                    stream.write(raw)
                row[f'{name}_reference'] = _reference(path)
            if grade_path.is_file():
                report, row['grade_reference'] = grader.read_json(grade_path)
            else:
                raise SmokeValidationError('Child did not produce a grading report')
            if child.returncode != 0:
                raise SmokeValidationError('Grader child did not complete successfully')
            row['counts'] = validate_report(report, kind=kind, dataset_reference=dataset_ref,
                predictions_reference=prediction_ref, official_repo=official_repo)
            if _reference(dataset_ref['path']) != dataset_ref or _reference(prediction_ref['path']) != prediction_ref:
                raise SmokeValidationError('Synthetic inputs changed during grading')
            row['status'] = 'PASS'
        except Exception as exc:
            row['error_type'] = type(exc).__name__
    unchanged = source_refs == {'smoke': _reference(__file__), 'adapter': _reference(adapter)}
    result = {'schema': SCHEMA, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'status': 'PASS' if unchanged and all(row['status'] == 'PASS' for row in runs.values()) else 'FAIL',
        'purpose': 'PUBLIC_SYNTHETIC_INSTALLATION_CHECK', 'actual_benchmark_score': False,
        'python_executable': sys.executable, 'python_version': sys.version.split()[0],
        'child_timeout_seconds': CHILD_TIMEOUT_SECONDS,
        'official_repo': str(official_repo), 'upstream_commit': grader.UPSTREAM_COMMIT,
        'sources': source_refs, 'sources_unchanged': unchanged, 'dataset_reference': dataset_ref,
        'expected': {'correct_passed': 2, 'wrong_passed': 0, 'questions_per_run': 2},
        'model_calls': 0, 'dataset_downloads': 0, 'docker_calls': 0, 'runs': runs}
    reference = _write_json(output_dir / 'smoke-report.json', result)
    return result, reference


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='A new directory; existing paths are rejected')
    args = parser.parse_args(argv)
    try:
        result, reference = run_smoke(args.official_repo, args.output_dir)
        print(json.dumps({'status': result['status'], 'actual_benchmark_score': False,
                          'report_reference': reference}))
        return 0 if result['status'] == 'PASS' else 2
    except Exception as exc:
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
