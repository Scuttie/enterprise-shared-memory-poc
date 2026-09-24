"""Synthetic metadata only; no benchmark text, models, or evaluators."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_transfer_plan as planner


@pytest.fixture
def inputs():
    split = {'schema': 'trimem/lcb-split/1.0', 'dataset_id': 'synthetic',
             'source_revision': 'synthetic-pin', 'release': 'synthetic',
             'task_descriptors': [], 'task_families': {}}
    for partition, families, size in [('train', 30, 2), ('valid', 8, 3), ('test', 4, 2)]:
        ids = []
        for family in range(families):
            for member in range(size):
                identity = '%s-%02d-%d' % (partition, family, member)
                family_id = '%s-family-%02d' % (partition, family)
                ids.append(identity)
                split['task_families'][identity] = family_id
                split['task_descriptors'].append({'task_id': identity, 'family_id': family_id,
                    'split': partition, 'difficulty': planner.DIFFICULTIES[(family + member) % 3]})
        split[partition + '_ids'] = ids
    # Only one sibling is explicitly excluded; the planner must exclude both.
    split['train_pilot_ids'] = ['train-00-0']
    split['pilot_ids'] = ['valid-00-0']
    config = {'requested_model': 'gpt-5.6-luna', 'reasoning_effort': 'low',
              'workers': 2, 'limits': dict(planner.LIMITS),
              'infrastructure_control_excluded_train_ids': ['train-01-0']}
    return split, config


def build(inputs, **kwargs):
    return planner.build_plan(*inputs, discovery_size=12, verification_size=8,
                              validation_size=6, **kwargs)


def test_whole_family_selection_disjoint_with_exclusion_closure(inputs):
    plan = build(inputs)
    first, second = plan['cohorts']['discovery'], plan['cohorts']['verification']
    assert first['task_count'] == 12 and second['task_count'] == 8
    assert set(first['task_ids']).isdisjoint(second['task_ids'])
    assert set(first['family_ids']).isdisjoint(second['family_ids'])
    assert set(plan['exclusions']['train_family_closure_excluded_ids']) == {
        'train-00-0', 'train-00-1', 'train-01-0', 'train-01-1'}
    for cohort in (first, second):
        for family in cohort['family_ids']:
            source_ids = {i for i, f in inputs[0]['task_families'].items() if f == family}
            assert source_ids.issubset(set(cohort['task_ids']))
        assert set(cohort['task_ids']).isdisjoint(plan['exclusions']['train_family_closure_excluded_ids'])


def test_validation_quotas_and_test_ids_order_unchanged(inputs):
    plan = build(inputs)
    assert plan['cohorts']['validation']['difficulty_counts'] == dict.fromkeys(planner.DIFFICULTIES, 2)
    assert set(plan['cohorts']['validation']['task_ids']).isdisjoint(inputs[0]['pilot_ids'])
    assert plan['cohorts']['test']['task_ids'] == inputs[0]['test_ids']
    assert plan['validation_freshness']['eligible_unseen_tasks'] == 23
    assert plan['validation_freshness']['eligible_tasks_in_unseen_families'] == 21


def test_selection_independent_of_metadata_container_order(inputs):
    expected = build(inputs)
    split, config = deepcopy(inputs)
    split['task_descriptors'].reverse()
    split['task_families'] = dict(reversed(list(split['task_families'].items())))
    split['train_ids'].reverse()
    split['valid_ids'].reverse()
    assert planner.canonical(build((split, config))) == planner.canonical(expected)
    assert build(inputs, seed='different-preregistered-seed')['cohorts'] != expected['cohorts']


def test_schedule_once_balanced_arms_and_no_extra_model_solves(inputs):
    plan = build(inputs)
    jobs = planner.schedule(plan)
    assert len(jobs) == plan['solve_accounting']['initial_model_solves'] == 54
    assert len({(row['phase'], row['task_id'], row['condition']) for row in jobs}) == len(jobs)
    assert [row['ordinal'] for row in jobs] == list(range(1, 55))
    assert plan['solve_accounting']['additional_model_solves_preregistered'] == 0
    assert {row['native_arm'] for row in jobs if row['phase'] == 'DISCOVERY'} == {'TRAIN'}
    assert {row['native_arm'] for row in jobs if row['phase'] == 'VERIFICATION'} == {'ON'}
    valid = [row for row in jobs if row['phase'] == 'VALID']
    assert len(valid) == 18
    for offset in range(3):
        assert {condition: sum(row['condition'] == condition for row in valid[offset::3])
                for condition in ('OFF', 'ON', 'L1ONLY')} == dict.fromkeys(('OFF', 'ON', 'L1ONLY'), 2)
    assert {row['native_arm'] for row in valid if row['condition'] == 'L1ONLY'} == {'ON'}
    test = [row for row in jobs if row['phase'] == 'TEST']
    assert len(test) == 16 and sum(row['condition'] == 'OFF' for row in test[::2]) == 4
    assert all({test[i]['condition'], test[i + 1]['condition']} == {'OFF', 'ON'}
               for i in range(0, len(test), 2))
    assert plan['schedule_sha256'] == planner.digest(planner.canonical(jobs))


def test_readiness_gate_and_shared_test_budget_no_silent_expansion(inputs):
    plan = build(inputs)
    execution, memory = plan['execution_policy'], plan['memory_policy']
    shared = execution['shared_test_execution_budget']
    assert shared['limit'] == plan['limits']['public_tests'] == 4
    assert set(shared['tools']) == {'run_public_tests', 'run_command'}
    assert shared['additional_test_budget'] == 0
    assert memory['verification_candidate_assignment']['policy'] == 'round_robin'
    assert memory['verification_candidate_assignment']['candidate_order'] == 'ascending candidate_id'
    assert execution['readiness_gates']['minimum_final_private_l3_skills'] == 1
    assert 'NOT_READY' in execution['readiness_gates']['zero_promoted_private_l3_skills']
    assert memory['bank_updates_during_validation_or_test'] is False
    assert memory['private_grades_used_for_selection_or_promotion'] is False


def test_subset_sum_failure_never_splits_family_or_relaxes_size():
    with pytest.raises(planner.PlanError, match='EXACT_WHOLE_FAMILY_COHORT_UNAVAILABLE'):
        planner.whole_families({'family-a': ['a', 'b'], 'family-b': ['c', 'd']},
                               3, seed='synthetic', phase='discovery')


def test_cross_partition_family_is_rejected(inputs):
    split, _ = inputs
    identity = split['valid_ids'][0]
    family = split['task_families'][split['train_ids'][0]]
    split['task_families'][identity] = family
    next(row for row in split['task_descriptors'] if row['task_id'] == identity)['family_id'] = family
    with pytest.raises(planner.PlanError, match='FAMILY_CROSSES_EXISTING_PARTITIONS'):
        build(inputs)


def test_controls_cannot_remove_heldout_tasks(inputs):
    inputs[1]['infrastructure_control_excluded_train_ids'].append(inputs[0]['test_ids'][0])
    with pytest.raises(planner.PlanError, match='CONTROL_EXCLUSION_OUTSIDE_TRAIN'):
        build(inputs)


@pytest.mark.parametrize('mutation', ['model', 'budget', 'workers', 'repeats'])
def test_budget_model_and_repeat_contract_cannot_drift(inputs, mutation):
    config = inputs[1]
    if mutation == 'model':
        config['requested_model'] = 'different-model'
    elif mutation == 'budget':
        config['limits']['tool_actions'] += 1
    else:
        config[mutation] = 3
    with pytest.raises(planner.PlanError, match='MODEL_OR_BUDGET_CONTRACT_DIFFERS'):
        build(inputs)


def test_difficulty_shortfall_fails_without_outcome_dependent_fallback(inputs):
    split = inputs[0]
    split['pilot_ids'] = [row['task_id'] for row in split['task_descriptors']
                          if row['split'] == 'valid' and row['difficulty'] == 'hard']
    with pytest.raises(planner.PlanError, match='VALIDATION_DIFFICULTY_QUOTA_UNAVAILABLE'):
        build(inputs)


def test_source_reference_change_or_escape_rejected(tmp_path):
    source = tmp_path / 'metadata.json'
    source.write_bytes(b'{}\n')
    refs = {'metadata': planner.reference(source, tmp_path)}
    planner.verify_references(refs, tmp_path)
    source.write_bytes(b'{ }\n')
    with pytest.raises(planner.PlanError, match='SOURCE_REFERENCE_CHANGED'):
        planner.verify_references(refs, tmp_path)
    refs['metadata']['path'] = '../outside.json'
    with pytest.raises(planner.PlanError, match='SOURCE_OUTSIDE_REPOSITORY'):
        planner.verify_references(refs, tmp_path)


def test_preregistration_write_once_exact_bytes(inputs, tmp_path):
    path = tmp_path / 'plan.json'
    plan = build(inputs)
    planner.write_once(path, plan)
    original = path.read_bytes()
    planner.write_once(path, plan)
    assert original.endswith(b'\n') and json.loads(original) == plan
    altered = deepcopy(plan)
    altered['selection_seed'] = 'posthoc-change'
    with pytest.raises(planner.PlanError, match='PREREGISTRATION_ALREADY_EXISTS'):
        planner.write_once(path, altered)
    assert path.read_bytes() == original
