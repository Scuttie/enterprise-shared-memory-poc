"""Synthetic publication and evidence checks; no live runs or evaluator calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import deveval_repository_results as auditor
import deveval_prepare as assets

manager, memory = auditor.manager, auditor.memory
SECRET_CODE = 'return x + 12345  # SYNTHETIC_SOLUTION_MARKER\n'
SECRET_REQUIREMENT = 'SYNTHETIC_TASK_PROSE_MARKER'
SECRET_MESSAGE = 'SYNTHETIC_PRIVATE_EXCEPTION_TEXT_MARKER'


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(memory.canonical(value))


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def call(request, response):
    return {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'benchmark', 'tool': 'action',
        'arguments': {'request': request}, 'result': {'content': [{'type': 'text', 'text': json.dumps(response)}]}}}


@pytest.fixture
def complete_run(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    root.mkdir()
    (root / 'experiment.lock').write_bytes(b'0')
    implementation = tmp_path / 'synthetic-source.py'
    implementation.write_text('# frozen synthetic source\n', encoding='utf-8')
    executable = tmp_path / 'synthetic-native.exe'
    executable.write_bytes(b'never execute this synthetic binary')
    runtime = {'native': {'model': 'synthetic-model', 'reasoning_effort': 'low', 'codex_executable': str(executable)},
        'deveval': {'metadata': 'NEVER_READ_PRIVATE_METADATA', 'evaluator': 'NEVER_RUN_GRADER', 'pristine_source_root': 'NEVER_OPEN_PRIVATE'}}
    tasks = [{'task_id': identity, 'project': project, 'phase': phase} for identity, project, phase in (
        ('source', 'alpha', 'DISCOVERY'), ('verify', 'alpha', 'VERIFICATION'),
        ('valid-alpha', 'alpha', 'VALID'), ('valid-beta', 'beta', 'VALID'),
        ('test-alpha', 'alpha', 'TEST'), ('test-beta', 'beta', 'TEST'))]
    plan = {'schema': 'deveval/repository-plan/1', 'experiment_id': 'synthetic-results', 'tasks': tasks,
        'model': {'model': 'synthetic-model', 'reasoning_effort': 'low'}, 'metadata_reference': {'sha256': 'a' * 64},
        'budgets': {'task_seconds': 600, 'tool_actions': 24, 'generated_test_runs': 4, 'native_sessions': 4},
        'source_schedule': [{**row, 'arm': 'SOURCE'} for row in tasks[:2]],
        'target_schedule': [{**row, 'arm': arm} for row in tasks[2:] for arm in auditor.ARMS]}
    plan_path, runtime_path = tmp_path / 'plan.json', tmp_path / 'runtime.json'
    write(plan_path, plan)
    write(runtime_path, runtime)
    snapshots = {}
    for project in ('alpha', 'beta'):
        path = tmp_path / (project + '-snapshot.json')
        write(path, {'project': project})
        snapshots[project] = memory.reference(path)
    jobs = manager.plan_schedule(plan)
    frozen = {'schema': 'deveval/repository-experiment/1', 'owner': 'synthetic-owner', 'requested_model': 'synthetic-model',
        'provider': 'native_codex', 'reasoning_effort': 'low', 'schedule': jobs, 'snapshots': snapshots,
        'references': [memory.reference(path) for path in (plan_path, runtime_path, implementation, executable)],
        'hidden_feedback_to_model': False, 'private_grades_used_for_memory': False}
    write(root / 'frozen-inputs.json', frozen)
    bank = {'stage': 'FINAL', 'plan_reference': memory.reference(plan_path), 'skills': [], 'l3_status': 'NOT_READY',
        'layer_counts': {'L1': 0, 'L3_candidates': 0, 'L3': 0},
        'captures': [{'phase': row['phase'], 'task_id': row['task_id']} for row in tasks[:2]]}
    write(root / 'bank-final.json', bank)
    bank_ref = memory.reference(root / 'bank-final.json')
    # Bank derivation has its own full fixture suite. Keep its hash and cohort
    # checks here, while exercising real manager/collection/grade validators.
    monkeypatch.setattr(memory, 'load', lambda ref, **kwargs: memory.read(memory.checked(auditor.plain(ref))))
    context = {'output': root, 'frozen': frozen, 'runtime': runtime, 'plan': plan, 'owner': frozen['owner']}
    rows = []
    for job in jobs:
        cell = manager.cell_path(context, job)
        layer = [{'layer': 'L2', 'memory_id': 'synthetic-relation', 'active_node_id': 'node',
                  'content': {'safe_metadata': True}}] if job['condition'] in ('FULL', 'NO_L3') else []
        task = {'task_id': job['task_id'], 'project': job['project'], 'requirement': SECRET_REQUIREMENT}
        state = {'task': task, 'phase': job['phase'], 'condition': job['condition'], 'owner': frozen['owner'],
            'runtime': runtime, 'snapshot_reference': snapshots[job['project']],
            'bank': None if job['condition'] in ('OFF', 'TRAIN') else bank_ref, 'selected_procedure_id': None,
            'arm': 'TRAIN' if job['condition'] == 'TRAIN' else 'OFF' if job['condition'] == 'OFF' else 'ON',
            'candidate': SECRET_CODE, 'source_lesson': {'summary': 'SYNTHETIC_LESSON_PROSE_MARKER'}, 'finished': True,
            'memory_injections': layer, 'public_test_runs': 1, 'step': 2, 'history': []}
        request = {'tool': 'run_command', 'arguments': {'code': SECRET_CODE, 'test_code': 'assert target(1) == 2', 'procedure_id': None}}
        result = {'status': 'FAIL', 'failure_kind': 'CANDIDATE_NOT_EXECUTED', 'exception_type': 'NameError',
            'message': SECRET_MESSAGE, 'candidate_executed': False, 'assertions_executed': 0}
        state['history'] = [{'step_no': 1, 'tool': 'run_command', 'request_payload': request, 'result_payload': result}]
        write(cell / 'generated-tests/step-001/receipt.json', result)
        write(cell / 'state.json', state)
        authority = {'job': job, 'bank': state['bank'], 'selected_procedure_id': None,
                     'frozen_inputs_reference': memory.reference(root / 'frozen-inputs.json')}
        write(cell / 'attempt.json', authority)
        write(root / 'starts' / ('%03d.json' % job['ordinal']), authority)
        session = cell / 'session-01'
        write(session / 'initial-state.json', {**state, 'finished': False})
        packet = {'task': task, 'context': {'memory': layer}}
        prompt = b'Synthetic instruction\nTASK_PACKET:\n' + memory.canonical(packet)
        (session / 'prompt.txt').write_bytes(prompt)
        (session / 'stderr.log').write_bytes(b'')
        usage = {'input_tokens': 10, 'cached_input_tokens': 2, 'output_tokens': 4}
        events = [{'type': 'thread.started', 'thread_id': 'thread-' + str(job['ordinal'])},
            call(request, {'step_no': 1, 'status': 'success', 'result': result, 'context': {'memory': layer}}),
            call({'tool': 'finish', 'arguments': {'code': SECRET_CODE, 'source_lesson': state['source_lesson']}},
                 {'step_no': 2, 'status': 'success', 'result': {'submitted': True, 'candidate_sha256': sha(SECRET_CODE)}, 'context': {'memory': []}}),
            {'type': 'turn.completed', 'usage': usage}]
        (session / 'events.jsonl').write_bytes(b''.join(memory.canonical(event) for event in events))
        receipt = {'session': 1, 'requested_model': 'synthetic-model', 'requested_reasoning_effort': 'low',
            'thread_ids': ['thread-' + str(job['ordinal'])], 'usage': [usage], 'benchmark_action_calls': 2,
            'events_sha256': memory.reference(session / 'events.jsonl')['sha256'],
            'stderr_sha256': memory.reference(session / 'stderr.log')['sha256']}
        write(session / 'receipt.json', receipt)
        write(session / 'prompt-receipt.json', {'task_id': job['task_id'], 'arm': state['arm'],
            'prompt_sha256': hashlib.sha256(prompt).hexdigest(), 'prompt_bytes': len(prompt),
            'state_before_call_sha256': memory.reference(session / 'initial-state.json')['sha256']})
        solve = {'task_id': job['task_id'], 'arm': state['arm'], 'status': 'SUBMITTED', 'error_type': None,
            'state_sha256': memory.reference(cell / 'state.json')['sha256'], 'candidate_sha256': sha(SECRET_CODE),
            'sessions': [receipt], 'tool_actions': 2, 'wall_seconds': 1.5, 'tool_seconds': .2}
        write(cell / 'solve-receipt.json', solve)
        row = {key: job[key] for key in ('phase', 'task_id', 'project', 'condition', 'ordinal')}
        row.update(status='SUBMITTED', error_type=None, grade_status='PENDING', passed=None,
            candidate_sha256=sha(SECRET_CODE), solve_seconds=1.5, tool_seconds=.2, sessions=1, tool_actions=2,
            generated_test_runs=1, declared_procedure_applications=0, memory_layers=[item['layer'] for item in layer],
            solve_reference=memory.reference(cell / 'solve-receipt.json'), state_reference=memory.reference(cell / 'state.json'))
        write(cell / 'cell-receipt.json', row)
        rows.append(row)
    collections = {phase: manager.seal(context, phase, rows) for phase in manager.PHASES}
    for job, row in zip(jobs, rows):
        cell = manager.cell_path(context, job)
        folder = cell / 'private-grade'
        folder.mkdir()
        if job['task_id'] == 'test-beta' and job['condition'] == 'NO_L2':
            row.update(grade_status='INFRA_ERROR', passed=None, grade_error_type='InterruptedGradeNoRetry')
            continue
        request = manager.expected_grade_request(context, job, row, collections[job['phase']])
        write(folder / 'request.json', request)
        passed = job['condition'] == 'FULL'
        receipt = {'task_id': job['task_id'], 'project': job['project'], 'candidate_sha256': sha(SECRET_CODE),
            'request_candidate_sha256': sha(SECRET_CODE), 'request_reference': memory.reference(folder / 'request.json'),
            'status': 'GRADED', 'passed': passed, 'official_result': 'Pass' if passed else 'Error',
            'process_exit_code': 0, 'timed_out': False, 'source_restored': True, 'pristine_source_unchanged': True,
            'unexpected_file_count': 0, 'metadata_sha256': 'a' * 64,
            'evaluator_reference': {'sha256': assets.UPSTREAM_FILES['pass_k.py']}, 'elapsed_total_seconds': .3}
        write(folder / 'receipt.json', receipt)
        row.update(grade_status='GRADED', passed=passed, grade_reference=memory.reference(folder / 'receipt.json'), grade_seconds=.3)
        write(cell / 'cell-receipt.json', row)
    summary = manager.checkpoint(context, rows, 'COMPLETE', 'COMPLETE_WITH_UNRESOLVED', time.monotonic(), bank_ref)
    return SimpleNamespace(root=root, context=context, rows=rows, jobs=jobs, summary=summary,
                           implementation=implementation, collections=collections, output=tmp_path / 'report.json')


def test_completed_audit_preserves_paired_denominators_and_reports_generated_failure_mechanism(complete_run):
    fixture = complete_run
    report = auditor.audit(fixture.root)
    assert report['status'] == 'AUDITED' and report['planned_cells'] == 22
    assert set(report['source_phases']) == {'DISCOVERY', 'VERIFICATION'}
    assert set(report['heldout_phases']) == {'VALID', 'TEST'}
    test = report['heldout_phases']['TEST']
    assert test['arms']['NO_L2']['planned'] == 2 and test['arms']['NO_L2']['unresolved'] == 1
    assert test['arms']['NO_L2']['success_rate'] is None
    assert test['paired_vs_off']['NO_L2']['planned_pairs'] == 2
    assert test['paired_vs_off']['NO_L2']['delta_all_planned'] is None
    assert test['paired_vs_off']['FULL']['gain'] == 2 and test['paired_vs_off']['FULL']['loss'] == 0
    assert test['arms']['FULL']['usage']['reported_fields']['input_tokens'] == 20
    assert test['arms']['FULL']['delivered_layer_injections']['L2'] == 2
    assert test['arms']['FULL']['generated_tests']['failure_kind_counts'] == {'CANDIDATE_NOT_EXECUTED': 2}
    assert test['arms']['FULL']['generated_tests']['exception_type_counts'] == {'NameError': 2}
    assert test['arms']['FULL']['generated_tests']['candidate_executed'] == 0
    assert report['bank']['l3_effect_claim'] == 'NOT_ESTIMABLE_ZERO_SKILLS'
    assert '1825' in report['scope'] and report['repository_held_out_generalization'] is False


def test_report_contains_only_metadata_and_publishing_does_not_modify_run(complete_run):
    fixture = complete_run
    before = {p.relative_to(fixture.root): memory.reference(p) for p in fixture.root.rglob('*') if p.is_file()}
    first = auditor.publish(fixture.root, fixture.output)
    assert auditor.publish(fixture.root, fixture.output) == first
    after = {p.relative_to(fixture.root): memory.reference(p) for p in fixture.root.rglob('*') if p.is_file()}
    assert before == after
    text = fixture.output.read_text(encoding='utf-8')
    assert all(secret not in text for secret in (SECRET_CODE, SECRET_REQUIREMENT, SECRET_MESSAGE, 'SYNTHETIC_LESSON_PROSE_MARKER'))
    assert sha(SECRET_MESSAGE) in text


@pytest.mark.parametrize('status', ['COLLECTING', 'HELD', 'GRADING'])
def test_nonterminal_summaries_cannot_publish(complete_run, status):
    fixture = complete_run
    write(fixture.root / 'summary.json', {**fixture.summary, 'status': status})
    with pytest.raises(auditor.AuditError, match='RUN_NOT_TERMINAL'):
        auditor.publish(fixture.root, fixture.output)
    assert not fixture.output.exists()


def test_manager_lock_must_be_released_before_publication(complete_run):
    fixture = complete_run
    with manager.original_manager.exclusive_lock(fixture.root):
        with pytest.raises(manager.original_manager.ExperimentError):
            auditor.publish(fixture.root, fixture.output)
    assert not fixture.output.exists()


@pytest.mark.parametrize('change', ['source', 'events', 'generated_receipt', 'grade_request'])
def test_changed_evidence_cannot_be_published(complete_run, change):
    fixture = complete_run
    cell = manager.cell_path(fixture.context, fixture.jobs[-1])
    path = fixture.implementation if change == 'source' else cell / {
        'events': 'session-01/events.jsonl', 'generated_receipt': 'generated-tests/step-001/receipt.json',
        'grade_request': 'private-grade/request.json'}[change]
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError):
        auditor.publish(fixture.root, fixture.output)
    assert not fixture.output.exists()


def test_summary_cannot_convert_unresolved_trial_to_pass(complete_run):
    fixture = complete_run
    value = deepcopy(fixture.summary)
    row = next(row for row in value['cells'] if row['passed'] is None)
    row['passed'] = True
    write(fixture.root / 'summary.json', value)
    with pytest.raises(auditor.AuditError, match='PRIMARY_OUTCOME_CHANGED'):
        auditor.audit(fixture.root)


def test_missing_arm_is_not_silently_removed_from_pairs(complete_run):
    fixture = complete_run
    value = deepcopy(fixture.summary)
    value['cells'].pop()
    value['recorded_cells'] -= 1
    write(fixture.root / 'summary.json', value)
    with pytest.raises(auditor.AuditError, match='SUMMARY_ENROLLMENT_CHANGED'):
        auditor.audit(fixture.root)


def test_publication_cannot_overwrite_any_primary_run_artifact(complete_run):
    with pytest.raises(auditor.AuditError, match='PUBLICATION_MUST_NOT_MUTATE_RUN'):
        auditor.publish(complete_run.root, complete_run.root / 'new-report.json')


def test_reported_usage_filters_non_numeric_fields_and_preserves_nested_token_counts():
    assert auditor.token_fields({'prompt_tokens': 20, 'completion_tokens_details': {'reasoning_tokens': 3},
                                'secret prose': 'must never print', 'output_tokens': True}) == {
        'prompt_tokens': 20, 'completion_tokens_details.reasoning_tokens': 3}


def test_import_isolation_failure_is_reported_without_exception_prose(tmp_path):
    result = {'status': 'FAIL', 'failure_kind': 'PROJECT_IMPORT_ISOLATION', 'exception_type': 'ProjectImportError',
              'message': SECRET_MESSAGE, 'candidate_executed': False, 'assertions_executed': 0}
    write(tmp_path / 'generated-tests/step-001/receipt.json', result)
    state = {'public_test_runs': 1, 'history': [{'step_no': 1, 'tool': 'run_command', 'result_payload': result}]}
    metadata = auditor.generated_evidence(tmp_path, state)
    assert metadata['failure_kind_counts'] == {'PROJECT_IMPORT_ISOLATION': 1}
    assert metadata['exception_type_counts'] == {'ProjectImportError': 1}
    assert metadata['candidate_not_executed'] == 1
    assert metadata['exception_message_sha256_counts'] == {sha(SECRET_MESSAGE): 1}
    assert SECRET_MESSAGE not in json.dumps(metadata)


@pytest.mark.parametrize('response_id', [None, 'synthetic-http-response'])
def test_actual_gateway_http_evidence_has_no_native_cli_or_thread_requirement(tmp_path, monkeypatch, response_id):
    import deveval_model_gateway as gateway
    cell = tmp_path / 'http-cell'
    state = {'task': {'task_id': 'synthetic-http', 'project': 'synthetic-project'},
        'phase': 'VALID', 'condition': 'OFF', 'arm': 'OFF', 'owner': 'synthetic-owner',
        'bank': None, 'selected_procedure_id': None, 'candidate': '', 'source_lesson': None,
        'runtime': {'native': {'model': 'synthetic-company-glm', 'reasoning_effort': 'low'},
            'gateway': {'provider': 'vllm', 'base_url': 'http://synthetic.invalid/v1', 'model': 'synthetic-company-glm'}},
        'session': 0, 'step': 0, 'finished': False, 'handoff_required': False,
        'history': [], 'memory_injections': [], 'public_test_runs': 0, 'tool_seconds': 0,
        'started_epoch': time.time(), 'limits': {'sessions': 4, 'tool_actions': 24, 'task_seconds': 600, 'prompt_bytes': 196608}}
    write(cell / 'state.json', state)
    action = {'tool': 'finish', 'arguments': {'code': SECRET_CODE, 'source_lesson': {'summary': 'Synthetic observation.'}}}
    body = {'model': 'synthetic-company-glm', 'choices': [{'message': {'content': json.dumps(action)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 17, 'completion_tokens': 4}}
    if response_id is not None:
        body['id'] = response_id
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, bound): return memory.canonical(body)
    calls = []
    def post(request, timeout):
        payload = json.loads(request.data)
        assert payload['model'] == 'synthetic-company-glm'
        calls.append(1)
        return Response()
    monkeypatch.setattr(gateway, '_http_post', post)
    monkeypatch.setattr(gateway, 'solve_native', lambda *a, **kw: pytest.fail('HTTP provider must not use native CLI'))
    def prompt(current):
        return 'Synthetic instruction\nTASK_PACKET:\n' + memory.canonical({'task': current['task'], 'context': {'memory': []}}).decode()
    def apply(path, request, **kwargs):
        current = memory.read(path / 'state.json')
        current.update(candidate=request['arguments']['code'], source_lesson=request['arguments']['source_lesson'], finished=True)
        current['step'] += 1
        write(path / 'state.json', current)
        return {'step_no': current['step'], 'status': 'success', 'result': {'submitted': True, 'candidate_sha256': sha(current['candidate'])},
                'context': {'memory': []}}
    solve = gateway.solve_vllm(cell, prompt_for=prompt, apply_action=apply)
    evidence = auditor.session_evidence(cell, memory.read(cell / 'state.json'), solve, 'vllm')
    assert calls == [1] and solve['status'] == 'SUBMITTED'
    assert evidence['thread_count'] == 0
    assert auditor.add_usage(evidence['usage_records'])['reported_fields'] == {'prompt_tokens': 17, 'completion_tokens': 4}
