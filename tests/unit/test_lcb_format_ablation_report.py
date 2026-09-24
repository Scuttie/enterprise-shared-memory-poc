"""Synthetic metadata-only tests for paired task-cluster ablation reporting."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_format_ablation_report as report


def experiment(values, controls=()):
    """Values map a synthetic task to KEEP/DROP lists of three observations."""
    trials, records = [], []
    for task, arms in values.items():
        for repeat in range(1, 4):
            for arm in ('KEEP', 'DROP'):
                trial = {'trial_id': f'{task}-{repeat}-{arm}', 'task_id': task,
                         'repeat': repeat, 'arm': arm}
                trials.append(trial)
                records.append({**trial, 'metrics': {m: arms[arm][repeat - 1] for m in report.METRICS}})
    protocol = {'trials': trials, 'task_ids': list(values), 'repeats': 3,
                'checkpoints': [{'task_id': task, 'no_memory_control': task in controls} for task in values]}
    return protocol, records


def test_nulls_remain_unknown_and_differences_use_matched_repeats_then_equal_task_weights():
    protocol, records = experiment({
        'one-pair': {'KEEP': [True, None, None], 'DROP': [False, True, None]},
        'three-pairs': {'KEEP': [False, False, False], 'DROP': [False, False, False]},
    })
    original = deepcopy((protocol, records))
    result = report.aggregate(protocol, records)
    metric = 'fixed_candidate_success'
    keep, drop = (result['arm_totals'][arm][metric] for arm in ('KEEP', 'DROP'))
    assert keep == {'successes': 1, 'observed': 4, 'null': 2, 'scheduled': 6, 'rate': .25}
    assert drop == {'successes': 1, 'observed': 5, 'null': 1, 'scheduled': 6, 'rate': .2}
    first = result['task_results'][0]['metrics'][metric]
    assert first['KEEP'] == [True, None, None]
    assert first['DROP'] == [False, True, None]
    assert first['paired_observations'] == 1
    assert first['paired_mean_difference'] == 1
    contrast = result['contrasts']['all24'][metric]
    assert contrast['tasks_scheduled'] == contrast['tasks_with_paired_observations'] == 2
    assert contrast['paired_observations'] == 4
    assert contrast['mean_task_difference'] == .5  # Not pooled-repeat 1/4.
    assert contrast['task_cluster_bootstrap_95_percentile'] == [0.0, 1.0]
    assert (protocol, records) == original


def test_no_matched_observations_stays_null_despite_observed_marginal_successes():
    protocol, records = experiment({'unmatched': {
        'KEEP': [True, None, None], 'DROP': [None, True, None]}})
    result = report.aggregate(protocol, records)
    for metric in report.METRICS:
        contrast = result['contrasts']['all24'][metric]
        assert contrast['tasks_scheduled'] == 1
        assert contrast['tasks_with_paired_observations'] == 0
        assert contrast['paired_observations'] == 0
        assert contrast['mean_task_difference'] is None
        assert contrast['task_cluster_bootstrap_95_percentile'] is None


def test_zero_memory_control_stays_in_whole_cohort_and_is_separately_reported():
    protocol, records = experiment({
        'exposed': {'KEEP': [True] * 3, 'DROP': [False] * 3},
        'control': {'KEEP': [False] * 3, 'DROP': [True] * 3}}, controls={'control'})
    result = report.aggregate(protocol, records)
    metric = 'submission_valid'
    assert result['contrasts']['all24'][metric]['mean_task_difference'] == 0
    assert result['contrasts']['memory_exposed23'][metric]['mean_task_difference'] == 1
    control = result['contrasts']['no_memory_control'][metric]
    assert control['tasks_scheduled'] == control['tasks_with_paired_observations'] == 1
    assert control['paired_observations'] == 3
    assert control['mean_task_difference'] == -1
    assert control['task_cluster_bootstrap_95_percentile'] is None


@pytest.mark.parametrize('change', ['task_id', 'arm', 'repeat', 'duplicate', 'missing', 'integer', 'string'])
def test_rejects_identity_denominator_and_nonboolean_outcome_changes(change):
    protocol, records = experiment({'synthetic': {'KEEP': [True] * 3, 'DROP': [False] * 3}})
    if change in ('task_id', 'arm', 'repeat'):
        records[0][change] = {'task_id': 'foreign', 'arm': 'DROP', 'repeat': 2}[change]
    elif change == 'duplicate':
        records[1] = deepcopy(records[0])
    elif change == 'missing':
        records.pop()
    else:
        records[0]['metrics']['anchor_valid'] = 1 if change == 'integer' else 'true'
    with pytest.raises(ValueError, match='ANALYSIS_AUDIT_FAILED'):
        report.aggregate(protocol, records)
