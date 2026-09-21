# SK hynix 메모리 비교 평가 중간 결과

**최신 후속 상태 — 2026-09-20 23:27:31 KST:** 17번째 Matplotlib 25565는 사용량 한도에 도달해 네이티브 실행이 중단됐다. 공식 해결 13·미해결 2·채점 보류 1건의 점수는 변함없고, 이 문제는 별도 실행 중단으로 유지한다. ON·최종은 미시작이다. 앞선 연속 실행 완료 예상에는 이번 대기가 포함되지 않는다. [설정·경과·수정된 조건부 일정](SKHYNIX_MEMORY_EXPERIMENT_SUMMARY.md) · [중단 진단](../artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/evaluation-continuation-001/native-quota-stop-001.json). 아래는 이전 시점의 기록이다.

**2026-09-20 23:21:42 KST 후속 상태:** 공식 15건과 미판정 1건의 원본 검사를 통과한 v16 컨트롤러가 **23:14:52 KST부터 17번째 Matplotlib 25565를 실제로 풀고 있다.** `gpt-6-astra / high`, 도구 요청 26회·활성 작업자, 컨트롤러 `PROGRESSING`·경고 없음을 확인했다. 현재 공식 채점 15건·보류 1건·풀이 중 1건·미시작 43건이며, 아래 22:30 집계의 점수는 그대로 유지한다. [재개 처리와 근거](SKHYNIX_MEMORY_SCALE_EXECUTION.md).

기준: **2026-09-20 22:30:30 KST**, v15 개발 평가. 기존 공식 결과와 실행 기록을 읽어 집계했으며, 이 집계에서 새 모델 호출·채점 실행은 하지 않았다.

**메모리 OFF baseline 60문제 중 공식 채점 15건이 완료됐고, 해결 13·미해결 2로 확정된 결과의 해결률은 86.7%(13/15)다.** 추가 1문제는 채점 보류이고 44문제는 아직 시작하지 않았다. 개발 메모리 ON과 최종 Verified 500문제 OFF/ON은 시작 전이다. **완료된 OFF/ON 비교 쌍은 0개로, 메모리의 성능 향상은 아직 측정할 수 없다.**

| 저장소 | 공식 채점 완료 | 해결 | 미해결 | 확정 결과의 해결률 |
| --- | ---: | ---: | ---: | ---: |
| Astropy | 5 | 3 | 2 | 60.0% |
| Django | 8 | 8 | 0 | 100.0% |
| Matplotlib | 2 | 2 | 0 | 100.0% |
| 합계 | **15** | **13** | **2** | **86.7%** |

위 표는 **정해진 순서로 실행한 앞부분 15문제**의 결과다. 저장소 구성이 편중된 비무작위 부분집합이며 개발 60문제 전체나 최종 500문제의 점수로 일반화하지 않는다. 보류 1건과 미시작 44건은 해결·미해결로 분류하지 않았다. 확정된 15건의 메모리 주입은 모두 0회다.

중단된 문제는 `swebench--matplotlib__matplotlib-20374`다. 공식 채점이 `no_tests_collected`로 보류된 뒤 v15 컨트롤러는 **22:14:16 KST**에 `PIPELINE_BLOCKED`로 종료됐다. 나중에 WSL이 실행 중이지 않았다는 관측은 별도 상태이며, 이 중단의 원인으로 보지 않는다. **위 22:30 점수 집계 당시에는 재시작 전이었다.** 이후 원본 제출과 미확정 판정을 보존하고, OFF/ON에 동일한 보류 처리 기준을 적용하는 v16으로 다음 문제의 실제 풀이를 재개했다. 채점 보류는 해결·미해결 어느 쪽으로도 재분류하지 않는다.

경험 수집에 사용한 기존 **240문제의 성적은 위 평가에 합산하지 않는다.** 그 자료로 발행한 메모리는 L1 919건(원래 수집 916건 + 파생 검증 기록 3건), L2 노드 4,653개·관계 4,193개, L3 절차 1개이며 준비 검증은 `READY`다. 메모리 준비가 완료됐다는 사실과 메모리 사용에 따른 해결률 상승은 구분한다. [메모리 수량·출처](../artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/recovered-memory-inventory-001.json) · [시작 검증](../artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/startup-validation-v15.json).

- [공식 중간 집계 JSON](../artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/interim-results-20260920T133030Z-v2.json): 설정·이벤트·공식 결과·실행 감사의 해시 참조, 단계별 집계와 비교 쌍 수. v2는 같은 점검 기록의 고정 경로를 참조하도록 메타데이터만 바로잡았으며 점수는 같다.
- [개발 OFF 60문제별 CSV](../artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/interim-results-20260920T133030Z-tasks.csv): 해결·미해결·미채점·미시작을 구분한 전체 예정 목록.
- [기존 평가 기록](SKHYNIX_MEMORY_V1_EVALUATION.md) · [실행 상태](SKHYNIX_MEMORY_SCALE_EXECUTION.md).
