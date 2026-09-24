> Historical snapshot retained before the user-approved scale expansion; this is not current execution status.

# SK hynix PDF 구조 구현·로컬 평가 결과

실험 구성을 다시 확인하려면 [학습·평가 방식과 저장소별 대상 표](SKHYNIX_PDF_ARCHITECTURE_COMPARISON.md), [학습 24개 목록](SKHYNIX_PDF_ARCHITECTURE_TRAINING_24.csv), [평가 500개 목록](SKHYNIX_PDF_ARCHITECTURE_EVALUATION_500.csv)을 보면 됩니다. 여기서 학습은 모델 fine-tuning이 아니라 실제 풀이 경험으로 외부 메모리를 만드는 과정입니다.

24개 경험 수집 규모의 한계와 120·240개 학습 및 별도 개발 검증 60개를 비교하는 안은 [수집 규모 검토](SKHYNIX_MEMORY_COLLECTION_SCALE_REVIEW.md)에 정리했습니다. 이는 아직 적용하지 않은 설계 제안이며, 현재 고정 실행 설정은 24개 학습입니다.

[실제 실행 기록](SKHYNIX_PDF_ARCHITECTURE_EXECUTION.md): **2026-09-14 17:38 KST 기준 학습 24문제 중 12개를 실제 풀이·공식 채점했고, 7개 성공·5개 실패입니다.** 공개 경험 52건을 수집하고 완료한 문제의 정리까지 마쳤습니다. 전체 파이프라인 v3는 정상 실행 중이며 13번째 xarray 2922의 도구 요청이 점검 중 46→49→59회로 증가했습니다. `high` 전환 후 실행·수집 오류와 미완료 정리는 0건입니다. 학습 1~8번의 `ultra` 설정과 원래 결과는 보존하며, **이후 학습·reflection·본 평가 양쪽은 `gpt-6-astra / high`**입니다. 이후 학습 24개 완료 → 공개 기록 기반 reflection·검증 스킬 승격 → bank 고정 → Verified 500문제 × OFF/ON 공식 평가 순서로 자동 진행합니다. 필수 메모리 계층의 검증 요건을 충족하지 못하면 그 상태를 기록하고 본 평가 전에 중단합니다. 현재 본 평가 0/1,000회이며 구조 OFF/ON 해결률 차이는 아직 미측정입니다. [최신 진행 수치](../artifacts/skhynix_v1/architecture_execution_001/progress.json)는 실제 공식 결과에서 갱신합니다.

완료된 `high` 4개의 실제 전체 실행 주기는 평균 **9분 37초**입니다. 같은 속도로 남은 학습 12개는 약 1시간 55분, 본 평가 1,000회는 약 160시간이며, reflection의 native 시간 예산 합계 1시간을 더하면 **9월 21일 낮 전후 완료**로 추정합니다. 문제당 10~15분을 잡는 계획용 범위는 **9월 21일 저녁~9월 25일 오전**입니다. [추정 근거](../artifacts/skhynix_v1/architecture_execution_001/runtime-estimate-high-001.json)는 원본 이벤트와 계산을 포함합니다. 표본이 Flask·Requests 4개뿐이고 reflection 내보내기·검증 시간은 별도이므로 확정 일정이나 신뢰구간은 아닙니다. 중단 없이 실행되고 실제 검증 스킬을 포함한 bank 발행 요건을 통과한다는 가정입니다.

[본 실험의 비교 조건](SKHYNIX_PDF_ARCHITECTURE_COMPARISON.md)은 **같은 에이전트의 PDF 핵심 메모리 구조 OFF/ON**입니다. SWE-bench Verified 전체 500문제와 겹치지 않는 학습 출처에서 메모리를 만든 뒤 고정하고, L0 문맥 전환·원문 복구, L1 개인 경험, L2 KG, L3 검증 스킬의 전체 적용 효과를 비교합니다. 아래 Native011의 +25%p와 현재 학습 문제의 성공을 이 구조 비교의 성능 향상으로 사용하지 않습니다.

초기 [준비 증거](../artifacts/skhynix_v1/architecture_preparation_001/summary.json)는 당시의 `NOT_EVALUATION_READY` 상태와 검사 172개 통과 기록으로 보존합니다. 이후 실제 실행 기록은 별도 `architecture_execution_001`에 추가합니다. 아직 전체 학습과 검증 스킬 승격·bank 동결이 남아 있어 본 평가를 시작한 상태는 아닙니다.

