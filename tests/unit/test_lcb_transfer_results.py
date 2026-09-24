"""Synthetic redaction/counting tests; no model, source task, or grader reads."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lcb_transfer_results as results


def public(code, status='PASS'):
    request = {'tool': 'run_public_tests', 'arguments': {'code': code}}
    output = {'candidate_sha256': hashlib.sha256(code.encode()).hexdigest(), 'status': status}
    def identity(value):
        raw = results.canonical(value, newline=False)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return {'tool': 'run_public_tests', 'request_payload': request, 'result_payload': output,
            'request': identity(request), 'result': identity(output)}


def test_l1_failure_flag_is_not_official_wrong_answer():
    state = {'candidate': 'SYNTHETIC_FINAL_SECRET', 'finished': True,
             'history': [public('SYNTHETIC_OLD_SECRET')]}
    projected = results.public_verification(state)
    assert not projected['l1_succeeded'] and not projected['final_candidate_public_tested']
    assert projected['final_candidate_public_classification'] == 'NO_MATCHING_FINAL_CANDIDATE_OBSERVATION'
    assert 'SECRET' not in str(projected)
    state['history'].append(public(state['candidate']))
    assert results.public_verification(state)['l1_succeeded']


def test_matching_fail_is_distinct_from_no_matching_final_test():
    state = {'candidate': 'synthetic', 'finished': True, 'history': [public('synthetic', 'FAIL')]}
    row = results.public_verification(state)
    assert row['final_candidate_public_tested'] and not row['l1_succeeded']
    assert row['final_candidate_public_classification'] == 'MATCHED_WITHOUT_PASS'


def test_public_payload_tamper_fails_before_counts():
    state = {'candidate': 'synthetic', 'finished': True, 'history': [public('synthetic')]}
    state['history'][0]['result_payload']['status'] = 'FAIL'
    with pytest.raises(results.AuditError, match='HISTORY_PAYLOAD_HASH_CHANGED'):
        results.public_verification(state)


def test_all80_denominator_and_infrastructure_null_are_preserved():
    rows = [{'status': 'SUBMITTED', 'grade_status': 'GRADED', 'passed': True}] * 73
    rows += [{'status': 'SUBMITTED', 'grade_status': 'GRADED', 'passed': False}] * 6
    rows += [{'status': 'SUBMITTED', 'grade_status': 'GRADER_ERROR', 'passed': None}]
    value = results.totals(rows)
    assert value['scheduled'] == 80 and value['official_rate'] is None and value['official_unresolved'] == 1
    assert value['graded_only_rate'] == 73 / 79
    assert value['full_cohort_success_rate_bounds'] == [73 / 80, 74 / 80]


def test_ungraded_boolean_is_not_accepted_as_official_result():
    with pytest.raises(results.AuditError, match='UNVERIFIED_OFFICIAL_VERDICT'):
        results.grade_projection({'grade_status': 'GRADER_ERROR', 'passed': False})


def test_nonterminal_and_postgate_cells_reject_publication():
    frozen = {'schedule': [{'phase': 'DISCOVERY', 'task_id': 'synthetic', 'ordinal': 1, 'condition': 'TRAIN'}]}
    summary = {'status': 'GRADING', 'phase': 'DISCOVERY', 'reason': None, 'cells': []}
    with pytest.raises(results.AuditError, match='NOT_TERMINAL_DISCOVERY_READINESS_STOP'):
        results.terminal_gate(summary, frozen)
    summary.update(status='NOT_READY', reason='NO_PROVISIONAL_PROCEDURES', cells=[{
        'phase': 'VALID', 'task_id': 'synthetic', 'ordinal': 1, 'condition': 'TRAIN'}])
    with pytest.raises(results.AuditError, match='SCHEDULE_IDENTITY_CHANGED'):
        results.terminal_gate(summary, frozen)


def test_reference_tampering_is_rejected(tmp_path):
    source = tmp_path / 'metadata.json'; source.write_bytes(b'{}')
    ref = results.reference(source)
    source.write_bytes(b'{"changed":true}')
    with pytest.raises(results.AuditError, match='REFERENCE_BYTES_CHANGED'):
        results.checked(ref)
