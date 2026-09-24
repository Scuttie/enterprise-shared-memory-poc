"""Grade saved LiveCodeBench predictions with a local, pinned official harness.

No model client, dataset downloader, Docker, or service database is used. Raw
official JSON/JSONL rows need the upstream datasets import; an already exported
trimem/lcb-evaluation-samples/1.0 envelope avoids that loader dependency.

Prediction format: {"schema":"trimem/lcb-predictions/1.0", "predictions":
[{"question_id":"id", "output":"raw fenced model response"}],
"expected_question_ids":["id"]}. The expected list is optional; without it the
report covers only supplied prediction IDs and cannot detect omitted tasks.
Generation failures use status="GENERATION_ERROR", error_type="TimeoutError"
instead of output. Reports never include candidate code, tests, or raw errors.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import gzip
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace

UPSTREAM_COMMIT = '28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24'
PREDICTION_SCHEMA = 'trimem/lcb-predictions/1.0'
SAMPLE_SCHEMA = 'trimem/lcb-evaluation-samples/1.0'
REPORT_SCHEMA = 'trimem/lcb-grade-report/1.0'


class GradeInputError(ValueError):
    """Invalid local input or frozen evaluator authority."""


class GraderContractError(RuntimeError):
    """Official output does not contain one coherent result per candidate."""


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GradeInputError('Duplicate JSON object key')
        result[key] = value
    return result


def _reject_constant(value):
    raise GradeInputError('Non-finite JSON number')


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def read_json(path):
    raw = Path(path).read_bytes()
    return parse_json(raw), {'path': str(Path(path).resolve()), 'sha256': sha256(raw)}


def read_dataset(path, expected_sha256):
    raw = Path(path).read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256) or sha256(raw) != expected_sha256:
        raise GradeInputError('Local dataset checksum differs')
    decoded = gzip.decompress(raw) if str(path).lower().endswith('.gz') else raw
    if str(path).lower().endswith(('.jsonl', '.jsonl.gz')):
        value = [parse_json(line) for line in decoded.splitlines() if line.strip()]
    else:
        value = parse_json(decoded)
    return value, {'path': str(Path(path).resolve()), 'sha256': sha256(raw)}


def _ids(values):
    if (not isinstance(values, list) or not values
            or any(not isinstance(item, str) or not item.strip() for item in values)
            or len(set(values)) != len(values)):
        raise GradeInputError('Question IDs must be unique nonempty strings')
    return values


def validate_predictions(value):
    if (not isinstance(value, dict) or value.get('schema') != PREDICTION_SCHEMA
            or set(value) - {'schema', 'predictions', 'expected_question_ids', 'model'}
            or not isinstance(value.get('predictions'), list)):
        raise GradeInputError('Unsupported prediction document')
    rows = value['predictions']
    if any(not isinstance(row, dict) for row in rows):
        raise GradeInputError('Prediction records must be objects')
    ids = [row.get('question_id') for row in rows]
    if ids:
        _ids(ids)
    expected = _ids(value['expected_question_ids']) if 'expected_question_ids' in value else _ids(ids)
    if set(ids) - set(expected):
        raise GradeInputError('Prediction lies outside declared cohort')
    for row in rows:
        status = row.get('status', 'OK')
        if status == 'OK':
            if set(row) - {'question_id', 'output', 'status'} or not isinstance(row.get('output'), str):
                raise GradeInputError('Successful prediction requires exactly one raw output')
        elif status == 'GENERATION_ERROR':
            if (set(row) != {'question_id', 'status', 'error_type'}
                    or not isinstance(row['error_type'], str)
                    or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', row['error_type'])):
                raise GradeInputError('Generation failure may contain only an exception class')
        else:
            raise GradeInputError('Unknown generation status')
    return expected, {row['question_id']: row for row in rows}


def index_dataset(value):
    exported = isinstance(value, dict) and value.get('schema') == SAMPLE_SCHEMA
    if exported:
        if set(value) - {'schema', 'samples', 'provenance'}:
            raise GradeInputError('Unsupported exported sample document')
        rows = value.get('samples')
    else:
        rows = value
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise GradeInputError('Dataset must contain local official rows or exported samples')
    _ids([row.get('question_id') for row in rows])
    if exported and any(set(row) != {'question_id', 'sample'} for row in rows):
        raise GradeInputError('Exported sample record has unexpected fields')
    return {row['question_id']: row for row in rows}, exported


def validate_sample(sample):
    if not isinstance(sample, dict) or set(sample) != {'input_output'} or not isinstance(sample['input_output'], str):
        raise GradeInputError('Invalid official evaluation sample')
    value = parse_json(sample['input_output'])
    if (not isinstance(value, dict) or set(value) != {'inputs', 'outputs', 'fn_name'}
            or not isinstance(value['inputs'], list) or not value['inputs']
            or not isinstance(value['outputs'], list) or len(value['inputs']) != len(value['outputs'])
            or any(not isinstance(item, str) for item in value['inputs'] + value['outputs'])
            or (value['fn_name'] is not None and not isinstance(value['fn_name'], str))):
        raise GradeInputError('Official evaluation sample has no matching nonempty test set')
    return sample


def verify_checkout(path):
    root = Path(path).resolve(strict=True)
    def git(*args):
        completed = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise GradeInputError('Cannot verify official evaluator checkout')
        return completed.stdout.strip()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root or git('rev-parse', 'HEAD') != UPSTREAM_COMMIT:
        raise GradeInputError('Official evaluator commit differs from the R11 pin')
    if git('status', '--porcelain', '--untracked-files=all', '--', 'lcb_runner'):
        raise GradeInputError('Official evaluator runtime has local changes')
    return root


def validate_module_origins(root):
    package = Path(root).resolve() / 'lcb_runner'
    references = {}
    for name, module in tuple(sys.modules.items()):
        if name != 'lcb_runner' and not name.startswith('lcb_runner.'):
            continue
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if not path.is_relative_to(package):
                raise GradeInputError('Imported official module escaped the pinned checkout')
            references[name] = {'path': str(path), 'sha256': sha256(path.read_bytes())}
        else:
            paths = list(getattr(module, '__path__', []))
            if not paths or any(not Path(item).resolve().is_relative_to(package) for item in paths):
                raise GradeInputError('Imported namespace escaped the pinned checkout')
    return references


def load_official_runtime(root, *, raw_rows):
    root = verify_checkout(root)
    validate_module_origins(root)
    sys.path.insert(0, str(root))
    # Imports are local; the upstream load_dataset entrypoint is never invoked.
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    os.environ['HF_HUB_OFFLINE'] = '1'
    extraction = importlib.import_module('lcb_runner.utils.extraction_utils')
    styles = importlib.import_module('lcb_runner.lm_styles')
    grading = importlib.import_module('lcb_runner.evaluation.compute_code_generation_metrics')
    problem_class = None
    if raw_rows:
        problem_class = importlib.import_module('lcb_runner.benchmarks.code_generation').CodeGenerationProblem
    references = validate_module_origins(root)
    return SimpleNamespace(extract=extraction.extract_code, style=styles.LMStyle.OpenAIChat,
        metrics=grading.codegen_metrics, problem_class=problem_class, references=references, root=root)


@contextmanager
def quiet_grader():
    """Suppress Python and inherited child FDs: upstream errors may contain tests."""
    saved = [os.dup(1), os.dup(2)]
    with open(os.devnull, 'w', encoding='utf-8') as target:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(target.fileno(), 1)
            os.dup2(target.fileno(), 2)
            with redirect_stdout(target), redirect_stderr(target):
                yield
        finally:
            target.flush()
            for original, descriptor in zip(saved, (1, 2)):
                os.dup2(original, descriptor)
                os.close(original)


def official_passes(output, count):
    """Use official per-problem pass@1; never infer success from truthy negatives."""
    if not isinstance(output, (list, tuple)) or len(output) != 3:
        raise GraderContractError('Official result tuple differs')
    metrics, results, metadata = output
    detail = metrics.get('detail', {}).get('pass@1', {}) if isinstance(metrics, dict) else {}
    if not isinstance(detail, dict) or len(detail) != count or not isinstance(metadata, list) or len(metadata) != count:
        raise GraderContractError('Official per-problem result count differs')
    answer = []
    for index in range(count):
        if (index in detail) == (str(index) in detail):
            raise GraderContractError('Official task index is missing or ambiguous')
        passed = float(detail[index] if index in detail else detail[str(index)])
        if not math.isfinite(passed) or passed not in (0.0, 1.0):
            raise GraderContractError('Pass@1 must describe exactly one generation')
        meta = metadata[index]
        if not isinstance(meta, list) or len(meta) != 1:
            raise GraderContractError('Official metadata generation count differs')
        meta = parse_json(meta[0]) if isinstance(meta[0], str) else meta[0]
        if not isinstance(meta, dict):
            raise GraderContractError('Official metadata is malformed')
        # The official wrapper uses -5 for its own TestRunnerError. This is
        # ungraded infrastructure, unlike official wrong answers or timeouts.
        answer.append(None if meta.get('error_code') == -5 else passed == 1.0)
    return answer


def grade_predictions(predictions, dataset, runtime, *, workers=1, timeout=6):
    started = time.perf_counter()
    if type(workers) is not int or workers < 1 or type(timeout) is not int or timeout < 1:
        raise GradeInputError('Workers and timeout must be positive integers')
    expected, supplied = validate_predictions(predictions)
    rows, exported = index_dataset(dataset)
    if set(expected) - set(rows):
        raise GradeInputError('Declared question IDs are missing from the local dataset')
    report_rows, samples, generations, pending = [], [], [], []
    for identity in expected:
        record = {'question_id': identity, 'status': 'NOT_GRADED', 'passed': None}
        report_rows.append(record)
        prediction = supplied.get(identity)
        if prediction is None:
            record['error_type'] = 'MissingPrediction'
            continue
        if prediction.get('status') == 'GENERATION_ERROR':
            record.update(status='GENERATION_ERROR', error_type=prediction['error_type'])
            continue
        record['output_sha256'] = sha256(prediction['output'].encode('utf-8'))
        try:
            with quiet_grader():
                sample = rows[identity]['sample'] if exported else runtime.problem_class(**rows[identity]).get_evaluation_sample()
                sample = validate_sample(sample)
                code = runtime.extract(prediction['output'], runtime.style)
            if not isinstance(code, str):
                raise GraderContractError('Official extractor returned no string')
        except Exception as exc:
            record.update(status='GRADER_ERROR', error_type=type(exc).__name__)
            continue
        record['extracted_code_sha256'] = sha256(code.encode('utf-8'))
        samples.append(sample)
        generations.append([code])
        pending.append(record)
    prepared = time.perf_counter()
    grading_seconds = 0.0
    if pending:
        grading_started = time.perf_counter()
        try:
            with quiet_grader():
                output = runtime.metrics(samples, generations, k_list=[1], num_process_evaluate=workers,
                    timeout=timeout, debug=False)
                grades = official_passes(output, len(pending))
        except Exception as exc:
            for record in pending:
                record.update(status='GRADER_ERROR', error_type=type(exc).__name__)
        else:
            for record, grade in zip(pending, grades):
                if grade is None:
                    record.update(status='GRADER_ERROR', error_type='TestRunnerError')
                else:
                    record.update(status='GRADED', passed=grade)
        grading_seconds = time.perf_counter() - grading_started
    graded = sum(row['status'] == 'GRADED' for row in report_rows)
    passed = sum(row['passed'] is True for row in report_rows)
    return {'schema': REPORT_SCHEMA, 'status': 'COMPLETE' if graded == len(expected) else 'INCOMPLETE',
        'cohort_scope': 'DECLARED_EXPECTED_IDS' if 'expected_question_ids' in predictions else 'PREDICTION_IDS_ONLY',
        'counts': {'planned': len(expected), 'predictions': len(supplied), 'graded': graded, 'passed': passed,
            'failed': graded - passed, 'not_graded': len(expected) - graded,
            'infra_errors': sum(row['status'] in {'GENERATION_ERROR', 'GRADER_ERROR'} for row in report_rows)},
        'pass_at_1': passed / len(expected) if graded == len(expected) else None,
        'graded_pass_at_1': passed / graded if graded else None,
        'timings': {'preparation_seconds': prepared - started, 'official_grading_seconds': grading_seconds,
            'total_grading_seconds': time.perf_counter() - started},
        'settings': {'timeout_seconds': timeout, 'workers': workers, 'generations_per_question': 1,
            'extraction_style': 'OpenAIChat', 'k_list': [1], 'dataset_downloads': False, 'model_calls': 0},
        'results': report_rows}


def main(argv=None):
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', required=True, type=Path)
    parser.add_argument('--dataset-json', required=True, type=Path, help='Pinned local JSON or .jsonl; never downloaded')
    parser.add_argument('--dataset-sha256', required=True)
    parser.add_argument('--official-repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--timeout', type=int, default=6)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.resolve() in {args.predictions.resolve(), args.dataset_json.resolve()}:
            raise GradeInputError('Output must be a new file')
        predictions, prediction_ref = read_json(args.predictions)
        validate_predictions(predictions)
        dataset, dataset_ref = read_dataset(args.dataset_json, args.dataset_sha256)
        _, exported = index_dataset(dataset)
        with quiet_grader():
            runtime = load_official_runtime(args.official_repo, raw_rows=not exported)
        report = grade_predictions(predictions, dataset, runtime, workers=args.workers, timeout=args.timeout)
        verify_checkout(runtime.root)
        if validate_module_origins(runtime.root) != runtime.references:
            raise GradeInputError('Official runtime changed while grading')
        if sha256(args.dataset_json.read_bytes()) != dataset_ref['sha256'] or sha256(args.predictions.read_bytes()) != prediction_ref['sha256']:
            raise GradeInputError('Inputs changed while grading')
        report['provenance'] = {'upstream_commit': UPSTREAM_COMMIT, 'official_repo': str(runtime.root),
            'official_modules': runtime.references, 'predictions_reference': prediction_ref, 'dataset_reference': dataset_ref}
        report['timings']['overall_seconds'] = time.perf_counter() - started
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        print(json.dumps({'status': report['status'], 'counts': report['counts'], 'pass_at_1': report['pass_at_1'],
            'report_reference': {'path': str(args.output.resolve()), 'sha256': sha256(args.output.read_bytes())}}))
        return 0 if report['status'] == 'COMPLETE' else 2
    except Exception as exc:
        # Do not include str(exc): malformed dataset/grader errors may quote tests.
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
