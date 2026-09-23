"""Synthetic-only adapter tests; no benchmark dataset, model, or network calls."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_lcb_grade as grader


def predictions(rows=None, expected=None):
    value = {'schema': grader.PREDICTION_SCHEMA, 'predictions': rows if rows is not None else [
        {'question_id': 'synthetic-1', 'output': '```python\nprint(2)\n```'}]}
    if expected is not None:
        value['expected_question_ids'] = expected
    return value


def sample(identity='synthetic-1'):
    return {'question_id': identity, 'sample': {'input_output': json.dumps({
        'inputs': ['1\n'], 'outputs': ['2\n'], 'fn_name': None})}}


def dataset(*ids):
    return {'schema': grader.SAMPLE_SCHEMA, 'samples': [sample(identity) for identity in (ids or ('synthetic-1',))]}


def official_output(values, metadata=None):
    # Matches pinned official [metrics, results, list[list[JSON metadata]]].
    return [{'pass@1': sum(values) / len(values), 'detail': {'pass@1': {i: float(v) for i, v in enumerate(values)}}},
        {i: [[bool(v)]] for i, v in enumerate(values)},
        [[json.dumps(row)] for row in (metadata if metadata is not None else [{} for _ in values])]]


def runtime(values=(True,), metadata=None):
    calls = []
    style = object()
    def extract(output, actual_style):
        assert actual_style is style
        calls.append(('extract', output))
        return 'synthetic candidate'
    def metrics(samples, generations, **kwargs):
        calls.append(('metrics', samples, generations, kwargs))
        return official_output(values, metadata)
    return SimpleNamespace(extract=extract, style=style, metrics=metrics, calls=calls)


def test_delegates_official_extraction_and_one_generation_metric():
    official = runtime((True, False))
    value = predictions([{'question_id': identity, 'output': identity} for identity in ('b', 'a')], ['a', 'b'])
    report = grader.grade_predictions(value, dataset('a', 'b'), official, workers=2, timeout=7)
    assert [row['question_id'] for row in report['results']] == ['a', 'b']
    assert [row['passed'] for row in report['results']] == [True, False]
    assert report['pass_at_1'] == .5
    assert report['status'] == 'COMPLETE'
    call = official.calls[-1]
    assert call[2] == [['synthetic candidate'], ['synthetic candidate']]
    assert call[3] == {'k_list': [1], 'num_process_evaluate': 2, 'timeout': 7, 'debug': False}
    assert report['timings']['total_grading_seconds'] >= report['timings']['official_grading_seconds'] >= 0
    assert 'synthetic candidate' not in json.dumps(report)
    assert 'input_output' not in json.dumps(report)


def test_missing_and_generation_errors_preserve_denominator():
    value = predictions([{'question_id': 'a', 'output': 'candidate'},
        {'question_id': 'b', 'status': 'GENERATION_ERROR', 'error_type': 'TimeoutError'}], ['a', 'b', 'c'])
    report = grader.grade_predictions(value, dataset('a', 'b', 'c'), runtime())
    assert report['counts'] == {'planned': 3, 'predictions': 2, 'graded': 1, 'passed': 1,
        'failed': 0, 'not_graded': 2, 'infra_errors': 1}
    assert report['pass_at_1'] is None and report['graded_pass_at_1'] == 1
    assert report['results'][1]['passed'] is None
    assert report['results'][2]['status'] == 'NOT_GRADED'
    assert report['cohort_scope'] == 'DECLARED_EXPECTED_IDS'


def test_absent_expected_ids_explicitly_limits_cohort_scope():
    report = grader.grade_predictions(predictions(), dataset('synthetic-1', 'unrequested'), runtime())
    assert report['cohort_scope'] == 'PREDICTION_IDS_ONLY'
    assert report['counts']['planned'] == 1


def test_no_predictions_with_expected_ids_does_not_invoke_grader():
    official = runtime()
    report = grader.grade_predictions(predictions([], ['synthetic-1']), dataset(), official)
    assert report['status'] == 'INCOMPLETE' and report['counts']['graded'] == 0
    assert report['timings']['official_grading_seconds'] == 0
    assert official.calls == []


@pytest.mark.parametrize('value', [
    predictions([{'question_id': 'x', 'output': 'one'}, {'question_id': 'x', 'output': 'two'}]),
    predictions([{'question_id': 'x', 'output': 'one'}], ['other']),
    predictions([{'question_id': 'x', 'output': ['multiple generations']}]),
    predictions([{'question_id': 'x', 'status': 'GENERATION_ERROR', 'error_type': 'Oops', 'message': 'secret'}]),
    predictions([{'question_id': 'x', 'status': 'GENERATION_ERROR', 'error_type': 'Oops: secret'}]),
    predictions([], []),
])
def test_invalid_or_ambiguous_prediction_contract_rejected(value):
    with pytest.raises(grader.GradeInputError):
        grader.validate_predictions(value)


def test_unknown_local_dataset_id_rejected_before_any_grading():
    official = runtime()
    with pytest.raises(grader.GradeInputError):
        grader.grade_predictions(predictions(), dataset('other'), official)
    assert official.calls == []


def test_raw_rows_use_official_problem_factory_without_dataset_loader():
    official = runtime()
    seen = []
    def problem(**row):
        seen.append(row)
        return SimpleNamespace(get_evaluation_sample=lambda: sample()['sample'])
    official.problem_class = problem
    raw = [{'question_id': 'synthetic-1', 'synthetic_field': 'local only'}]
    report = grader.grade_predictions(predictions(), raw, official)
    assert seen == raw and report['status'] == 'COMPLETE'


def test_empty_test_set_cannot_vacuously_pass():
    local = dataset()
    local['samples'][0]['sample']['input_output'] = json.dumps({'inputs': [], 'outputs': [], 'fn_name': None})
    official = runtime()
    report = grader.grade_predictions(predictions(), local, official)
    assert report['results'][0]['status'] == 'GRADER_ERROR'
    assert report['results'][0]['passed'] is None
    assert not any(row[0] == 'metrics' for row in official.calls)


def test_grader_exception_is_ungraded_and_never_exposes_exception_message(capfd):
    official = runtime()
    def broken(*args, **kwargs):
        print('SYNTHETIC_HIDDEN_SENTINEL')
        os.write(2, b'SYNTHETIC_HIDDEN_SENTINEL')
        raise RuntimeError('SYNTHETIC_HIDDEN_SENTINEL')
    official.metrics = broken
    report = grader.grade_predictions(predictions(), dataset(), official)
    assert report['counts']['failed'] == 0 and report['counts']['infra_errors'] == 1
    assert report['results'][0]['error_type'] == 'RuntimeError'
    assert report['results'][0]['passed'] is None
    assert 'SYNTHETIC_HIDDEN_SENTINEL' not in json.dumps(report)
    captured = capfd.readouterr()
    assert 'SYNTHETIC_HIDDEN_SENTINEL' not in captured.out + captured.err


def test_upstream_test_runner_error_not_scored_as_wrong_answer():
    official = runtime((False, False), [{'error_code': -5, 'error': 'SYNTHETIC_HIDDEN'},
        {'error_code': -2, 'expected': 'SYNTHETIC_HIDDEN'}])
    value = predictions([{'question_id': identity, 'output': 'candidate'} for identity in ('a', 'b')])
    report = grader.grade_predictions(value, dataset('a', 'b'), official)
    assert [row['status'] for row in report['results']] == ['GRADER_ERROR', 'GRADED']
    assert [row['passed'] for row in report['results']] == [None, False]
    assert report['counts']['failed'] == 1 and report['pass_at_1'] is None
    assert 'SYNTHETIC_HIDDEN' not in json.dumps(report)


@pytest.mark.parametrize('change', ['missing', 'ambiguous', 'fractional', 'metadata', 'nan'])
def test_malformed_official_result_is_fail_closed(change):
    result = official_output([True])
    if change == 'missing':
        result[0]['detail']['pass@1'] = {}
    elif change == 'ambiguous':
        result[0]['detail']['pass@1']['0'] = 1
    elif change == 'fractional':
        result[0]['detail']['pass@1'][0] = .5
    elif change == 'nan':
        result[0]['detail']['pass@1'][0] = float('nan')
    else:
        result[2] = []
    with pytest.raises(grader.GraderContractError):
        grader.official_passes(result, 1)


def test_dataset_hash_and_jsonl_load(tmp_path):
    path = tmp_path / 'rows.jsonl'
    raw = b'{"question_id":"synthetic-1"}\n'
    path.write_bytes(raw)
    rows, ref = grader.read_dataset(path, grader.sha256(raw))
    assert rows == [{'question_id': 'synthetic-1'}]
    assert ref['sha256'] == grader.sha256(raw)
    with pytest.raises(grader.GradeInputError):
        grader.read_dataset(path, '0' * 64)


def test_duplicate_json_keys_rejected():
    with pytest.raises(grader.GradeInputError):
        grader.parse_json('{"question_id":"one","question_id":"two"}')


def test_imported_module_origin_cannot_escape_checkout(tmp_path, monkeypatch):
    import sys
    outside = tmp_path / 'foreign.py'
    outside.write_text('')
    monkeypatch.setitem(sys.modules, 'lcb_runner.synthetic', SimpleNamespace(__file__=str(outside)))
    with pytest.raises(grader.GradeInputError):
        grader.validate_module_origins(tmp_path / 'official')


@pytest.mark.parametrize('changed', ['commit', 'dirty', 'nested'])
def test_official_repository_pin_and_clean_tree_required(tmp_path, monkeypatch, changed):
    def fake_run(argv, **kwargs):
        args = argv[3:]
        output = (str(tmp_path / 'other') if changed == 'nested' else str(tmp_path)) if args[-1] == '--show-toplevel' else (
            'f' * 40 if changed == 'commit' else grader.UPSTREAM_COMMIT) if args[-1] == 'HEAD' else (
            ' M lcb_runner/evaluation/testing_util.py' if changed == 'dirty' else '')
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(grader.subprocess, 'run', fake_run)
    with pytest.raises(grader.GradeInputError):
        grader.verify_checkout(tmp_path)


def test_cli_no_output_overwrite(tmp_path, capsys):
    output = tmp_path / 'existing.json'
    output.write_text('preserved')
    code = grader.main(['--predictions', str(tmp_path / 'missing'), '--dataset-json', str(tmp_path / 'missing-data'),
        '--dataset-sha256', '0' * 64, '--official-repo', str(tmp_path), '--output', str(output)])
    assert code == 2 and output.read_text() == 'preserved'
    assert json.loads(capsys.readouterr().err) == {'status': 'ERROR', 'error_type': 'GradeInputError'}
