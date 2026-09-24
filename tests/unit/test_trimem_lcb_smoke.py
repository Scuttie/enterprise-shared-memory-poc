"""Portable smoke contract tests; the official grader process is not launched."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import trimem_lcb_grade as grader
import trimem_lcb_smoke as smoke


def install_child(monkeypatch, *, modify=None, returncode=0, missing=False):
    calls = []

    def child(argv, **kwargs):
        calls.append((argv, kwargs))
        flags = dict(zip(argv[2::2], argv[3::2]))
        prediction_path = Path(flags['--predictions'])
        predictions, prediction_ref = grader.read_json(prediction_path)
        dataset, dataset_ref = grader.read_dataset(flags['--dataset-json'], flags['--dataset-sha256'])
        kind = prediction_path.name.split('-')[0]
        good = kind == 'correct'

        def metrics(samples, generations, **settings):
            assert len(samples) == len(generations) == 2
            return [{'detail': {'pass@1': {0: float(good), 1: float(good)}}},
                    {0: [[good]], 1: [[good]]}, [['{}'], ['{}']]]

        runtime = SimpleNamespace(extract=lambda output, style: output, style='synthetic', metrics=metrics)
        report = grader.grade_predictions(predictions, dataset, runtime)
        report['provenance'] = {'upstream_commit': grader.UPSTREAM_COMMIT,
            'official_repo': flags['--official-repo'], 'dataset_reference': dataset_ref,
            'predictions_reference': prediction_ref}
        if modify:
            modify(kind, report)
        if not missing:
            Path(flags['--output']).write_text(json.dumps(report), encoding='utf-8')
        return SimpleNamespace(returncode=returncode, stdout=b'child summary\n', stderr=b'')

    monkeypatch.setattr(smoke.subprocess, 'run', child)
    return calls


def test_success_checks_both_modes_and_binds_artifacts(tmp_path, monkeypatch):
    calls = install_child(monkeypatch)
    result, reference = smoke.run_smoke(tmp_path, tmp_path / 'new output')
    assert result['status'] == 'PASS'
    assert result['actual_benchmark_score'] is False
    assert result['runs']['correct']['counts']['passed'] == 2
    assert result['runs']['wrong']['counts']['passed'] == 0
    assert len(calls) == 2
    for argv, kwargs in calls:
        assert argv[0] == sys.executable
        assert Path(argv[1]).name == 'trimem_lcb_grade.py'
        assert kwargs['cwd'] == tmp_path / 'new output'
        assert kwargs['timeout'] == 180
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        assert kwargs['env']['HF_DATASETS_OFFLINE'] == '1'
    assert hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest() == reference['sha256']
    for row in result['runs'].values():
        for key in ('grade_reference', 'stdout_reference', 'stderr_reference', 'predictions_reference'):
            ref = row[key]
            assert hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest() == ref['sha256']


def test_wrong_candidate_passing_is_failed_smoke_not_success(tmp_path, monkeypatch):
    def modify(kind, report):
        if kind == 'wrong':
            report['counts'].update(passed=2, failed=0)
            report['pass_at_1'] = report['graded_pass_at_1'] = 1.0
            for row in report['results']:
                row['passed'] = True
    install_child(monkeypatch, modify=modify)
    result, _ = smoke.run_smoke(tmp_path, tmp_path / 'out')
    assert result['status'] == 'FAIL'
    assert result['runs']['correct']['status'] == 'PASS'
    assert result['runs']['wrong']['error_type'] == 'SmokeValidationError'


def test_infrastructure_failure_does_not_count_as_wrong_rejection(tmp_path, monkeypatch):
    def modify(kind, report):
        if kind == 'wrong':
            report['status'] = 'INCOMPLETE'
            report['counts'].update(graded=0, failed=0, not_graded=2, infra_errors=2)
            report['pass_at_1'] = report['graded_pass_at_1'] = None
            for row in report['results']:
                row.update(status='GRADER_ERROR', passed=None, error_type='TestRunnerError')
    install_child(monkeypatch, modify=modify)
    result, ref = smoke.run_smoke(tmp_path, tmp_path / 'out')
    assert result['status'] == 'FAIL'
    assert result['runs']['wrong']['status'] == 'FAIL'
    assert Path(ref['path']).is_file()


@pytest.mark.parametrize('change', ['duplicate_id', 'contradictory_row', 'boolean_count', 'input_hash', 'source_commit'])
def test_coherent_aggregate_cannot_hide_invalid_evidence(tmp_path, monkeypatch, change):
    def modify(kind, report):
        if kind != 'wrong':
            return
        if change == 'duplicate_id':
            report['results'][1]['question_id'] = report['results'][0]['question_id']
        elif change == 'contradictory_row':
            report['results'][0]['passed'] = True
        elif change == 'boolean_count':
            report['counts']['infra_errors'] = False
        elif change == 'input_hash':
            report['provenance']['predictions_reference']['sha256'] = '0' * 64
        else:
            report['provenance']['upstream_commit'] = '0' * 40
    install_child(monkeypatch, modify=modify)
    result, _ = smoke.run_smoke(tmp_path, tmp_path / 'out')
    assert result['status'] == 'FAIL'
    assert result['runs']['wrong']['status'] == 'FAIL'


@pytest.mark.parametrize('missing,returncode', [(True, 0), (False, 2)])
def test_child_failure_or_missing_report_cannot_pass(tmp_path, monkeypatch, missing, returncode):
    install_child(monkeypatch, missing=missing, returncode=returncode)
    result, _ = smoke.run_smoke(tmp_path, tmp_path / 'out')
    assert result['status'] == 'FAIL'
    assert all(row['status'] == 'FAIL' for row in result['runs'].values())


@pytest.mark.parametrize('with_file', [False, True])
def test_existing_output_is_preserved_without_child_launch(tmp_path, monkeypatch, with_file, capsys):
    out = tmp_path / 'existing'
    out.mkdir()
    if with_file:
        (out / 'smoke-report.json').write_bytes(b'preserved')
    before = {str(p): p.read_bytes() for p in out.iterdir()}
    monkeypatch.setattr(smoke.subprocess, 'run', lambda *a, **k: pytest.fail('Child must not run'))
    code = smoke.main(['--official-repo', str(tmp_path), '--output-dir', str(out)])
    assert code == 2
    assert {str(p): p.read_bytes() for p in out.iterdir()} == before
    assert json.loads(capsys.readouterr().err)['error_type'] == 'FileExistsError'


def test_cli_reports_failed_discrimination_with_nonzero_exit(tmp_path, monkeypatch, capsys):
    install_child(monkeypatch, returncode=2)
    code = smoke.main(['--official-repo', str(tmp_path), '--output-dir', str(tmp_path / 'out')])
    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'FAIL' and output['actual_benchmark_score'] is False


def test_child_timeout_is_retained_as_failure(tmp_path, monkeypatch):
    def timeout(argv, **kwargs):
        raise smoke.subprocess.TimeoutExpired(argv, kwargs['timeout'])
    monkeypatch.setattr(smoke.subprocess, 'run', timeout)
    result, reference = smoke.run_smoke(tmp_path, tmp_path / 'out')
    assert result['status'] == 'FAIL'
    assert all(row['error_type'] == 'TimeoutExpired' for row in result['runs'].values())
    assert Path(reference['path']).is_file()
