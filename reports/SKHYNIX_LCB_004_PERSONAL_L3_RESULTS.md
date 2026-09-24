# LCB 004: 개인 L3 절차 전이 실험 결과

실제 실행은 **DISCOVERY 80문제 후 NOT_READY**로 끝났다. 등록된 중단 사유는 `NO_PROVISIONAL_PROCEDURES`다. 생성 테스트 실행이 0회여서 후보 절차가 만들어지지 않았고, 사전 규칙에 따라 VERIFICATION·VALID·TEST는 실행하지 않았다.

## 실제 실행과 공식 채점

- 모델: `gpt-5.6-luna` / `low`. TRAIN 출처 80문제 중 80개 제출.
- 공식 비공개 채점: 성공 73, 실패 6, 미확정 1. 분모는 전체 80문제다. 이는 학습 출처의 기술적 통계이며 새 held-out ON/OFF 비교가 아니다.
- 채점 완료 문제만의 비율은 73/79 (92.405%)다. 미확정을 포함한 전체 성공률은 확정하지 않으며, 가능한 범위는 91.25%–92.50%다.
- 새로운 native 세션 85개, 서로 다른 thread 85개를 해시 결속 이벤트와 대조했다. 모델/effort 기록은 모두 일치했다.
- 실제 prompt의 구조화된 memory 항목 0개, 도구 응답의 항목 0개. 이 DISCOVERY 단계에는 은행을 주입하지 않았다.

## 메모리 상태와 중단 의미

- L1 경험 80개, L2 후보 코드 노드 292개/관계 289개, 개인 L3 후보 0개, 승격된 개인 L3 0개.
- `L1_failed=37`는 공식 오답 수가 아니다. 제출한 최종 코드 SHA와 동일한 원래 공개 테스트 PASS가 기록되어야 L1의 `succeeded=true`가 된다. 최종 코드 기준 분류는 `{"MATCHED_PASS": 43, "NO_MATCHING_FINAL_CANDIDATE_OBSERVATION": 37}`다.
- `run_command` 요청 0회, 실제 생성 테스트 0회, procedure ID 적용 0회. 제공된 도구를 사용하지 않은 기록이며 모델의 내부 이유는 추론하지 않는다.
- 후보에는 실제 같은 생성 사례 RED → 코드 변경 → GREEN, 최종 코드의 공개 PASS, 실제 lesson/trace 결속이 필요하다. 별도 TRAIN 검증을 통과한 개인 절차만 승격하는 구현과 검증 코드는 존재하지만 이번 데이터는 첫 후보 조건을 충족하지 않았다.
- 따라서 개인 L3의 성능 효과가 음수라는 결과도, L3 구현이 없다는 결과도 아니다. 이번 실행은 **후보 수집 단계의 준비도 미충족**을 관찰했다.

## 실행하지 않은 사전 등록 단계

VERIFICATION 40셀, VALID 60문제×OFF/ON/L1ONLY=180셀, TEST 182문제×OFF/ON=364셀 모두 미실행이다. 이 단계를 0점으로 채점하거나 기존 LCB 002/003의 결과와 새 대조군처럼 합치지 않는다. 비공개 결과로 출처를 재선별하거나 후보를 꾸며 승격하지 않았다.

## 측정 범위와 근거

미확정 공개 집계는 `[{"grade_error_type": "TestRunnerError", "grade_status": "GRADER_ERROR", "passed": null, "task_id": "3233"}]`다. `TestRunnerError`는 고정 채점기가 공식 metadata의 `error_code=-5`를 매핑한 상태다. 보존된 공개 보고서만으로 내부 원인을 더 구체화할 수 없으며 모델 오답으로 바꾸거나 자동 재채점하지 않았다.

기록된 manager 시간은 2150.0초이며 병렬 셀 시간의 합과 구분한다. 토큰 수는 provider receipt에 있는 값만 합산하며 완전한 비용 계측을 주장하지 않는다. 기존 후보 코드 기반 L2의 동일 revision 제한은 그대로다. DevEval의 별도 저장소 L2 실험과 혼동하지 않는다.

근거: [`final-summary-001.json`](../artifacts/skhynix_v1/lcb_004/final-summary-001.json), [`lcb_transfer_results.py`](../scripts/lcb_transfer_results.py). exporter는 최종 manager lock 해제, 고정 입력/80셀 수집 봉인, 제출·세션·prompt·이벤트·은행·공식 집계 참조의 해시를 확인했다. 문제/답안/lesson/모델 추론/비공개 테스트 본문은 보고서에 포함하지 않았다. 감사 과정의 모델 호출과 공식 채점 재실행은 모두 0회다.
