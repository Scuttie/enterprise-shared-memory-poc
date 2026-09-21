import copy
import pytest
import trimem_skhynix_architecture_semantic_reflection as grouping


@pytest.fixture
def case():
    public = {'candidates': [{'candidate_id': 'a', 'task_group': 't1', 'contributor_group': 'u1'},
                             {'candidate_id': 'b', 'task_group': 't2', 'contributor_group': 'u2'},
                             {'candidate_id': 'c', 'task_group': 't3', 'contributor_group': 'u1'}]}
    response = {'schema': grouping.SCHEMA, 'input_sha256': 'hash',
        'groups': [{'candidate_ids': ['a', 'b'], 'shared_transformation': 'Normalize optional values before comparing.',
                    'applicability': 'Only when missing and explicit None have the same documented meaning.'}],
        'ungrouped': [{'candidate_id': 'c', 'reason_code': 'NO_SEMANTIC_PARTNER', 'evidence_note': 'Different edit invariant.'}]}
    return public, response


def test_candidate_groups_are_unverified_and_every_source_is_accounted(case):
    public, response = case
    assert grouping.validate_response(public, response, 'hash') == {
        'groups': 1, 'grouped_candidates': 2, 'ungrouped_candidates': 1, 'verified_skills': 0}


@pytest.mark.parametrize('change', ['input', 'unknown', 'missing', 'same_task', 'same_owner', 'duplicate', 'both'])
def test_wrong_evidence_binding_and_nondependent_support_fail(case, change):
    public, response = copy.deepcopy(case)
    if change == 'input': response['input_sha256'] = 'other'
    if change == 'unknown': response['groups'][0]['candidate_ids'][1] = 'foreign'
    if change == 'missing': response['ungrouped'] = []
    if change == 'same_task': public['candidates'][1]['task_group'] = 't1'
    if change == 'same_owner': public['candidates'][1]['contributor_group'] = 'u1'
    if change == 'duplicate': response['groups'].append(response['groups'][0])
    if change == 'both': response['ungrouped'][0]['candidate_id'] = 'a'
    with pytest.raises(ValueError): grouping.validate_response(public, response, 'hash')


def test_honest_empty_discovery_is_allowed_with_source_accounting(case):
    public, response = case
    response['groups'] = []
    response['ungrouped'] = [{'candidate_id': r['candidate_id'], 'reason_code': 'NO_SEMANTIC_PARTNER',
                             'evidence_note': 'No supported common transformation in this inventory.'} for r in public['candidates']]
    assert grouping.validate_response(public, response, 'hash')['groups'] == 0
