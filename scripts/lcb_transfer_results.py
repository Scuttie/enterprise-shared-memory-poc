"""Metadata-only audit of a terminal, readiness-gated LCB transfer run.

Native/source JSON is projected programmatically. No problem, candidate, lesson,
reasoning, test payload, or private per-test result is emitted. No execution
helper is imported; this exporter cannot start a model or grader.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {'revise_subtask_dag', 'run_public_tests', 'run_command', 'complete_subtask', 'finish'}
MUTABLE = {'grade_status', 'passed', 'grade_reference', 'grader_seconds', 'grade_error_type'}


class AuditError(ValueError):
    pass


def require(value, code):
    if not value:
        raise AuditError(code)


def canonical(value, *, newline=True):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + ('\n' if newline else '')).encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(path), 'sha256': h.hexdigest(), 'bytes': path.stat().st_size}


def checked(ref, expected=None):
    ref = {key: ref[key] for key in ('path', 'sha256', 'bytes')}
    require(expected is None or Path(ref['path']).resolve() == Path(expected).resolve(), 'REFERENCE_PATH_CHANGED')
    require(reference(ref['path']) == ref, 'REFERENCE_BYTES_CHANGED')
    return Path(ref['path'])


@contextmanager
def inactive(root):
    with (root / 'experiment.lock').open('rb') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AuditError('MANAGER_STILL_ACTIVE') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def terminal_gate(summary, frozen):
    require(summary.get('status') == 'NOT_READY' and summary.get('phase') == 'DISCOVERY' and
            summary.get('reason') == 'NO_PROVISIONAL_PROCEDURES', 'NOT_TERMINAL_DISCOVERY_READINESS_STOP')
    expected = [j for j in frozen['schedule'] if j['phase'] == 'DISCOVERY']
    rows = summary['cells']
    require(len(rows) == len(expected) and len({r['task_id'] for r in rows}) == len(rows), 'DISCOVERY_COVERAGE_CHANGED')
    require(all(r['phase'] == 'DISCOVERY' and r['task_id'] == j['task_id'] and r['ordinal'] == j['ordinal']
                and r['condition'] == j['condition'] for r, j in zip(rows, expected)), 'SCHEDULE_IDENTITY_CHANGED')
    return expected


def public_verification(state):
    final_sha = hashlib.sha256(state['candidate'].encode()).hexdigest()
    observations = []
    for row in state['history']:
        for field, payload_key in (('request', 'request_payload'), ('result', 'result_payload')):
            raw = canonical(row[payload_key], newline=False)
            require(row[field]['sha256'] == hashlib.sha256(raw).hexdigest() and row[field]['bytes'] == len(raw), 'HISTORY_PAYLOAD_HASH_CHANGED')
        if row['tool'] != 'run_public_tests':
            continue
        result = row['result_payload']
        require(result['candidate_sha256'] == hashlib.sha256(row['request_payload']['arguments']['code'].encode()).hexdigest(), 'PUBLIC_CANDIDATE_BINDING_CHANGED')
        observations.append(result)
    matching = [r for r in observations if r['candidate_sha256'] == final_sha]
    final_pass = any(r['status'] == 'PASS' for r in matching)
    return {'public_results': len(observations), 'public_result_statuses': dict(Counter(r['status'] for r in observations)),
        'final_candidate_public_tested': bool(matching), 'final_candidate_public_pass': final_pass,
        'l1_succeeded': bool(state['finished'] and final_pass),
        'final_candidate_public_classification': 'MATCHED_PASS' if final_pass else (
            'NO_MATCHING_FINAL_CANDIDATE_OBSERVATION' if not matching else 'MATCHED_WITHOUT_PASS')}


def native_metadata(cell, solve, state, refs):
    threads, calls = [], []
    attempts, accepted, rejected = Counter(), Counter(), Counter()
    prompt_memory_entries = response_memory_entries = unexpected = 0
    tokens = Counter()
    for number, session in enumerate(solve['sessions'], 1):
        folder = cell / ('session-%02d' % number)
        require(read(folder / 'receipt.json') == session and session['session'] == number, 'SESSION_RECEIPT_CHANGED')
        require(session['requested_model'] == 'gpt-5.6-luna' and session['requested_reasoning_effort'] == 'low', 'NATIVE_MODEL_SETTINGS_CHANGED')
        require(session['returncode'] == 0, 'NATIVE_SESSION_NOT_COMPLETED')
        for name in ('receipt.json', 'prompt-receipt.json', 'prompt.txt', 'initial-state.json', 'events.jsonl', 'stderr.log'):
            refs.append(reference(folder / name))
        require(reference(folder / 'events.jsonl')['sha256'] == session['events_sha256'] and
                reference(folder / 'stderr.log')['sha256'] == session['stderr_sha256'], 'SESSION_BYTES_CHANGED')
        prompt_receipt = read(folder / 'prompt-receipt.json')
        require(prompt_receipt['prompt_sha256'] == reference(folder / 'prompt.txt')['sha256'] and
                prompt_receipt['state_before_call_sha256'] == reference(folder / 'initial-state.json')['sha256'], 'PROMPT_BINDING_CHANGED')
        initial = read(folder / 'initial-state.json')
        require(initial['task']['task_id'] == state['task']['task_id'] and initial['phase'] == 'DISCOVERY' and
                initial['runtime']['native']['model'] == 'gpt-5.6-luna' and initial['runtime']['native']['reasoning_effort'] == 'low', 'INITIAL_STATE_SCOPE_CHANGED')
        # Programmatic packet projection only. Prose is never returned.
        packet = json.loads((folder / 'prompt.txt').read_bytes().decode().split('TASK_PACKET:\n', 1)[1])
        require(packet['task_id'] == state['task']['task_id'], 'PROMPT_TASK_CHANGED')
        prompt_memory_entries += len(packet['context']['memory'])
        actual_threads, action_items, session_unexpected = [], 0, []
        for raw in (folder / 'events.jsonl').read_bytes().splitlines():
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if event.get('type') == 'thread.started':
                actual_threads.append(event.get('thread_id'))
            if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
                tokens.update({k: v for k, v in event['usage'].items() if type(v) in (int, float) and v >= 0})
            item = event.get('item', {})
            if event.get('type') != 'item.completed':
                continue
            is_action = (item.get('type'), item.get('server'), item.get('tool')) == ('mcp_tool_call', 'benchmark', 'action')
            if not is_action:
                if item.get('type') not in ('agent_message', 'reasoning', 'error', 'todo_list', 'plan_update'):
                    session_unexpected.append(item.get('type'))
                continue
            action_items += 1
            envelope = item.get('arguments')
            if isinstance(envelope, str):
                envelope = json.loads(envelope)
            request = envelope.get('request') if isinstance(envelope, dict) else None
            tool = request.get('tool') if isinstance(request, dict) else None
            tool = tool if tool in TOOLS else 'UNKNOWN'
            attempts[tool] += 1
            for block in (item.get('result') or {}).get('content', []):
                if block.get('type') != 'text':
                    continue
                try:
                    response = json.loads(block['text'])
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(response, dict) or type(response.get('step_no')) is not int:
                    continue
                calls.append((request, response))
                response_memory_entries += len(response.get('context', {}).get('memory', []))
                (accepted if response.get('status') == 'success' else rejected)[tool] += 1
        require(actual_threads == session['thread_ids'] and actual_threads and all(isinstance(t, str) and t for t in actual_threads), 'THREAD_NOT_CORROBORATED')
        require(action_items == session['benchmark_action_calls'] and session_unexpected == session['unexpected_tools'], 'NATIVE_TOOL_ACCOUNTING_CHANGED')
        threads.extend(actual_threads)
        unexpected += len(session_unexpected)
    for row in state['history']:
        matching = [(req, res) for req, res in calls if res['step_no'] == row['step_no']]
        require(len(matching) == 1 and matching[0][0] == row['request_payload'] and matching[0][1]['result'] == row['result_payload']
                and matching[0][1]['status'] == row['status'], 'HISTORY_NOT_NATIVE_CORROBORATED')
    actual_steps = [res['step_no'] for req, res in calls if isinstance(req, dict) and req.get('tool') in TOOLS - {'finish'} and res.get('status') == 'success']
    require(sorted(actual_steps) == [r['step_no'] for r in state['history']], 'NATIVE_HISTORY_NOT_BIJECTIVE')
    finishes = [(req, res) for req, res in calls if isinstance(req, dict) and req.get('tool') == 'finish' and res.get('result', {}).get('submitted') is True]
    require(len(finishes) == int(state['finished']), 'SUBMISSION_NATIVE_IDENTITY')
    if finishes:
        require(finishes[0][0]['arguments']['code'] == state['candidate'] and
                finishes[0][0]['arguments']['source_lesson'] == state['source_lesson'], 'SEALED_SUBMISSION_CHANGED')
    return {'threads': threads, 'sessions': len(solve['sessions']), 'attempted_tool_counts': dict(attempts),
        'accepted_tool_counts': dict(accepted), 'rejected_tool_counts': dict(rejected),
        'unexpected_native_tools': unexpected, 'prompt_memory_entries': prompt_memory_entries,
        'response_memory_entries': response_memory_entries, 'recorded_tokens': dict(tokens)}


def grade_projection(row):
    if row.get('grade_status') == 'GRADED':
        require(type(row.get('passed')) is bool, 'GRADED_VERDICT_TYPE')
        return row['passed']
    require(row.get('passed') is None, 'UNVERIFIED_OFFICIAL_VERDICT')
    return None


def totals(rows):
    values = [grade_projection(r) for r in rows]
    passed, failed = sum(v is True for v in values), sum(v is False for v in values)
    n = len(rows)
    return {'scheduled': n, 'submitted': sum(r['status'] == 'SUBMITTED' for r in rows),
            'official_passed': passed, 'official_failed': failed, 'official_unresolved': n - passed - failed,
            'official_rate': passed / n if n and passed + failed == n else None,
            'graded_only_rate': passed / (passed + failed) if passed + failed else None,
            'full_cohort_success_rate_bounds': [passed / n, (n - failed) / n] if n else [None, None],
            'role': 'DESCRIPTIVE_TRAINING_SOURCE_OUTCOMES_NOT_HELDOUT_COMPARISON'}


def audit(root):
    root = Path(root).resolve()
    refs = [reference(root / name) for name in ('summary.json', 'frozen-inputs.json', 'DISCOVERY/collection.json', 'bank-provisional-receipt.json')]
    summary, frozen = read(root / 'summary.json'), read(root / 'frozen-inputs.json')
    expected = terminal_gate(summary, frozen)
    require(frozen['model'] == 'gpt-5.6-luna' and frozen['reasoning_effort'] == 'low', 'FROZEN_MODEL_CHANGED')
    for value in frozen['references']:
        checked(value); refs.append(value)
    actual_paths = {p.resolve() for p in (ROOT / 'scripts').glob('trimem_lcb_*.py')} | {p.resolve() for p in (ROOT / 'src/enterprise_memory/trimem').rglob('*.py')}
    package_init = ROOT / 'src/enterprise_memory/__init__.py'
    if package_init.is_file():
        actual_paths.add(package_init.resolve())
    actual_implementation = sorted(actual_paths)
    require([reference(p) for p in actual_implementation] == frozen['implementation'], 'FROZEN_IMPLEMENTATION_SET_CHANGED')
    collection = read(root / 'DISCOVERY/collection.json')
    require(collection['status'] == 'SEALED' and collection['cells'] == len(expected) and collection['private_grader_started'] is False, 'COLLECTION_NOT_SEALED')
    for value in collection['references']:
        checked(value); refs.append(value)
    bank_ref = summary['bank']; bank = read(checked(bank_ref))
    refs.append({k: bank_ref[k] for k in ('path', 'sha256', 'bytes')})
    require(bank['stage'] == 'PROVISIONAL' and not bank['data']['candidates'] and not bank['data']['skills'] and
            bank['evaluation_writes'] is False and bank['organisation_gate_b_changed'] is False, 'READINESS_BANK_CHANGED')
    for value in [bank['scope_reference'], bank['adapter_reference'], *bank['source_capture_references']]:
        checked(value); refs.append(value)
    episodes = {e['task_id']: e for e in bank['data']['episodes']}
    require(set(episodes) == {j['task_id'] for j in expected}, 'BANK_SOURCE_COVERAGE_CHANGED')
    rows, all_threads = [], []
    for original, sealed in zip(summary['cells'], collection['rows']):
        require({k: v for k, v in original.items() if k not in MUTABLE} == sealed, 'SEALED_GENERATION_ROW_CHANGED')
        solve_path = checked(original['solve_reference']); refs.append(original['solve_reference'])
        cell = solve_path.parent; solve, state = read(solve_path), read(cell / 'state.json')
        refs.extend(reference(cell / name) for name in ('state.json', 'cell-receipt.json', 'grade-start.json'))
        require(read(cell / 'cell-receipt.json') == original, 'CELL_RECEIPT_CHANGED')
        require(solve['state_sha256'] == reference(cell / 'state.json')['sha256'] and solve['task_id'] == original['task_id']
                and solve['candidate_sha256'] == original['candidate_sha256'] == hashlib.sha256(state['candidate'].encode()).hexdigest(), 'SOLVE_STATE_CHANGED')
        require(state['phase'] == 'DISCOVERY' and state['arm'] == 'TRAIN' and state['bank'] is None, 'SOURCE_CONDITION_CHANGED')
        start = read(cell / 'grade-start.json')
        require(start['collection_reference'] == reference(root / 'DISCOVERY/collection.json') and
                start['solve_reference'] == original['solve_reference'], 'GRADE_COLLECTION_BARRIER_CHANGED')
        if 'grade_reference' in original:
            grade_path = checked(original['grade_reference']); refs.append(original['grade_reference'])
            # Only task-level aggregate status/hash fields are consumed.
            report = read(grade_path); grades = report.get('results', [])
            require(len(grades) == 1 and grades[0]['question_id'] == original['task_id'] and
                    grades[0]['status'] == original['grade_status'] and grades[0].get('passed') is original['passed'], 'OFFICIAL_AGGREGATE_CHANGED')
            if original['grade_status'] == 'GRADED':
                require(grades[0]['extracted_code_sha256'] == original['candidate_sha256'], 'OFFICIAL_CANDIDATE_CHANGED')
        public = public_verification(state)
        require(episodes[original['task_id']]['succeeded'] is public['l1_succeeded'], 'L1_PUBLIC_VERIFICATION_FLAG_CHANGED')
        native = native_metadata(cell, solve, state, refs)
        require(native['threads'] == original['thread_ids'] and native['recorded_tokens'] == original['tokens'], 'RECORDED_NATIVE_METADATA_CHANGED')
        all_threads.extend(native.pop('threads'))
        rows.append({key: original.get(key) for key in ('task_id', 'ordinal', 'status', 'grade_status', 'grade_error_type', 'passed',
            'candidate_sha256', 'public_test_runs', 'generated_test_runs', 'procedure_applications', 'wall_seconds', 'tool_seconds', 'grader_seconds')} |
            {'difficulty': state['task']['difficulty'], **public, **native})
    require(len(all_threads) == len(set(all_threads)), 'NATIVE_THREAD_REUSED')
    require(bank['layer_counts']['L1_failed'] == sum(not r['l1_succeeded'] for r in rows), 'L1_FAILED_COUNT_CHANGED')
    for phase in ('VERIFICATION', 'VALID', 'TEST'):
        require(not (root / phase).exists(), 'POST_READINESS_PHASE_WAS_EXECUTED')
    refs = list({r['path']: r for r in refs}.values())
    for value in refs:
        checked(value)
    attempts, accepted, rejected, public_statuses, tokens = Counter(), Counter(), Counter(), Counter(), Counter()
    for row in rows:
        attempts.update(row['attempted_tool_counts']); accepted.update(row['accepted_tool_counts'])
        rejected.update(row['rejected_tool_counts']); public_statuses.update(row['public_result_statuses']); tokens.update(row['recorded_tokens'])
    return {'schema': 'lcb-transfer-results/1', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'status': summary['status'], 'reason': summary['reason'], 'model': frozen['model'], 'reasoning_effort': frozen['reasoning_effort'],
        'phase_schedule': dict(Counter(j['phase'] for j in frozen['schedule'])), 'recorded_phase': 'DISCOVERY',
        'training_outcomes': totals(rows), 'layer_counts': bank['layer_counts'],
        'unresolved_official_rows': [{k: r[k] for k in ('task_id', 'grade_status', 'grade_error_type', 'passed')}
                                     for r in rows if r['grade_status'] != 'GRADED'],
        'l1_flag_definition': 'submitted AND at least one recorded original-public PASS with exact final candidate SHA; not hidden-test correctness',
        'public_verification': {'result_statuses': dict(public_statuses),
            'final_candidate_classifications': dict(Counter(r['final_candidate_public_classification'] for r in rows))},
        'tool_evidence': {'attempted': dict(attempts), 'accepted': dict(accepted), 'rejected': dict(rejected),
            'generated_execution_count': sum(r['generated_test_runs'] for r in rows),
            'procedure_applications': sum(r['procedure_applications'] for r in rows)},
        'native_audit': {'sessions': sum(r['sessions'] for r in rows), 'unique_threads': len(set(all_threads)),
            'all_threads_fresh': True, 'all_requests_luna_low': True,
            'unexpected_tools': sum(r['unexpected_native_tools'] for r in rows),
            'prompt_memory_entries': sum(r['prompt_memory_entries'] for r in rows),
            'response_memory_entries': sum(r['response_memory_entries'] for r in rows)},
        'timing': {'manager_seconds': summary['manager_seconds'], 'source_solve_seconds_sum': sum(r['wall_seconds'] for r in rows),
            'source_solve_seconds_mean': statistics.mean(r['wall_seconds'] for r in rows)},
        'recorded_tokens': dict(tokens), 'cells': rows, 'source_references': refs,
        'audit_model_calls': 0, 'audit_official_grader_runs': 0,
        'hidden_feedback_used_for_memory': False, 'heldout_memory_effect_measured': False,
        'interpretation': 'Readiness gate stopped before verification/evaluation; no L3-effect estimate and no evidence that implemented L3 is absent.'}


def report(result):
    out, layers, tools, public = result['training_outcomes'], result['layer_counts'], result['tool_evidence'], result['public_verification']
    errors = json.dumps(result['unresolved_official_rows'], ensure_ascii=False, sort_keys=True)
    return f'''# LCB 004: 개인 L3 절차 전이 실험 결과

실제 실행은 **DISCOVERY 80문제 후 NOT_READY**로 끝났다. 등록된 중단 사유는 `{result['reason']}`다. 생성 테스트 실행이 {tools['generated_execution_count']}회여서 후보 절차가 만들어지지 않았고, 사전 규칙에 따라 VERIFICATION·VALID·TEST는 실행하지 않았다.

## 실제 실행과 공식 채점

- 모델: `{result['model']}` / `{result['reasoning_effort']}`. TRAIN 출처 {out['scheduled']}문제 중 {out['submitted']}개 제출.
- 공식 비공개 채점: 성공 {out['official_passed']}, 실패 {out['official_failed']}, 미확정 {out['official_unresolved']}. 분모는 전체 {out['scheduled']}문제다. 이는 학습 출처의 기술적 통계이며 새 held-out ON/OFF 비교가 아니다.
- 채점 완료 문제만의 비율은 {out['official_passed']}/{out['official_passed'] + out['official_failed']} ({out['graded_only_rate'] * 100:.3f}%)다. 미확정을 포함한 전체 성공률은 확정하지 않으며, 가능한 범위는 {out['full_cohort_success_rate_bounds'][0] * 100:.2f}%–{out['full_cohort_success_rate_bounds'][1] * 100:.2f}%다.
- 새로운 native 세션 {result['native_audit']['sessions']}개, 서로 다른 thread {result['native_audit']['unique_threads']}개를 해시 결속 이벤트와 대조했다. 모델/effort 기록은 모두 일치했다.
- 실제 prompt의 구조화된 memory 항목 {result['native_audit']['prompt_memory_entries']}개, 도구 응답의 항목 {result['native_audit']['response_memory_entries']}개. 이 DISCOVERY 단계에는 은행을 주입하지 않았다.

## 메모리 상태와 중단 의미

- L1 경험 {layers['L1_episodes']}개, L2 후보 코드 노드 {layers['L2_nodes']}개/관계 {layers['L2_edges']}개, 개인 L3 후보 {layers['L3_candidates']}개, 승격된 개인 L3 {layers['L3_personal_skills']}개.
- `L1_failed={layers['L1_failed']}`는 공식 오답 수가 아니다. 제출한 최종 코드 SHA와 동일한 원래 공개 테스트 PASS가 기록되어야 L1의 `succeeded=true`가 된다. 최종 코드 기준 분류는 `{json.dumps(public['final_candidate_classifications'], ensure_ascii=False, sort_keys=True)}`다.
- `run_command` 요청 {tools['attempted'].get('run_command', 0)}회, 실제 생성 테스트 {tools['generated_execution_count']}회, procedure ID 적용 {tools['procedure_applications']}회. 제공된 도구를 사용하지 않은 기록이며 모델의 내부 이유는 추론하지 않는다.
- 후보에는 실제 같은 생성 사례 RED → 코드 변경 → GREEN, 최종 코드의 공개 PASS, 실제 lesson/trace 결속이 필요하다. 별도 TRAIN 검증을 통과한 개인 절차만 승격하는 구현과 검증 코드는 존재하지만 이번 데이터는 첫 후보 조건을 충족하지 않았다.
- 따라서 개인 L3의 성능 효과가 음수라는 결과도, L3 구현이 없다는 결과도 아니다. 이번 실행은 **후보 수집 단계의 준비도 미충족**을 관찰했다.

## 실행하지 않은 사전 등록 단계

VERIFICATION 40셀, VALID 60문제×OFF/ON/L1ONLY=180셀, TEST 182문제×OFF/ON=364셀 모두 미실행이다. 이 단계를 0점으로 채점하거나 기존 LCB 002/003의 결과와 새 대조군처럼 합치지 않는다. 비공개 결과로 출처를 재선별하거나 후보를 꾸며 승격하지 않았다.

## 측정 범위와 근거

미확정 공개 집계는 `{errors}`다. `TestRunnerError`는 고정 채점기가 공식 metadata의 `error_code=-5`를 매핑한 상태다. 보존된 공개 보고서만으로 내부 원인을 더 구체화할 수 없으며 모델 오답으로 바꾸거나 자동 재채점하지 않았다.

기록된 manager 시간은 {result['timing']['manager_seconds']:.1f}초이며 병렬 셀 시간의 합과 구분한다. 토큰 수는 provider receipt에 있는 값만 합산하며 완전한 비용 계측을 주장하지 않는다. 기존 후보 코드 기반 L2의 동일 revision 제한은 그대로다. DevEval의 별도 저장소 L2 실험과 혼동하지 않는다.

근거: [`final-summary-001.json`](../artifacts/skhynix_v1/lcb_004/final-summary-001.json), [`lcb_transfer_results.py`](../scripts/lcb_transfer_results.py). exporter는 최종 manager lock 해제, 고정 입력/80셀 수집 봉인, 제출·세션·prompt·이벤트·은행·공식 집계 참조의 해시를 확인했다. 문제/답안/lesson/모델 추론/비공개 테스트 본문은 보고서에 포함하지 않았다. 감사 과정의 모델 호출과 공식 채점 재실행은 모두 0회다.
'''


def export(root, output, report_path):
    root, output, report_path = Path(root).resolve(), Path(output).resolve(), Path(report_path).resolve()
    require(not output.exists() and not report_path.exists(), 'OUTPUT_ALREADY_EXISTS')
    with inactive(root):
        result = audit(root)
        result['exporter_reference'] = reference(__file__)
        for path, raw in ((output, canonical(result)), (report_path, report(result).encode())):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
    return {'status': result['status'], 'training_outcomes': result['training_outcomes'],
            'summary_reference': reference(output), 'report_reference': reference(report_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.root, args.output, args.report)))


if __name__ == '__main__':
    main()
