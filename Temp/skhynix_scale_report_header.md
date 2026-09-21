# SK hynix PDF 구조 구현·로컬 평가 결과

현재 실험은 사용자 승인에 따라 **경험 수집 24 → 120 → 240개, 별도 개발 검증 60개, 최종 Verified 500개 × 구조 OFF/ON**으로 확대했습니다. 학습은 모델 가중치 fine-tuning이 아니라 실제 풀이 경험으로 외부 메모리를 만드는 과정입니다.

[확대 실행 설정·대상·상태](SKHYNIX_MEMORY_SCALE_EXECUTION.md), [수집 240개와 중첩 집합 표시](SKHYNIX_PDF_ARCHITECTURE_TRAINING_240.csv), [개발 검증 60개](SKHYNIX_PDF_ARCHITECTURE_DEVELOPMENT_60.csv), [최종 평가 500개](SKHYNIX_PDF_ARCHITECTURE_EVALUATION_500.csv)를 확인할 수 있습니다. 새로운 풀이·reflection·개발 검증·최종 평가 모두 `gpt-6-astra / high`입니다. 이전 첫 8개의 `ultra` 기록은 그대로 보존합니다.

기존 실행은 18번째 제출 후 공식 채점이 `no_tests_collected`로 확정되지 않아 멈췄습니다. 18개 풀이 중 공식 결과가 확정된 것은 17개(해결 9·미해결 8)입니다. 불확실한 1개를 성공이나 실패로 단정하지 않으며, 18개의 공개 풀이 경험을 재사용하고 미실행 6개부터 이어갑니다. 이후 96개·120개를 추가로 수집합니다.

개발 기준선은 동일 60문제에서 한 번만 실행하고, 준비된 24·120·240개 기반 메모리와 비교합니다. 개발 해결 수가 가장 큰 메모리를 선택하며 동점이면 작은 규모를 택합니다. 선택과 설정을 고정한 뒤 최종 500문제를 양쪽에서 평가합니다. 작은 메모리가 검증 요건을 충족하지 못해도 다음 수집 단계는 계속하며, 검증 요건 자체를 낮추지는 않습니다. 평가 경험은 조회용 메모리에 합치지 않습니다.

[현재 진행 수치](../artifacts/skhynix_v1/architecture_scale_001/progress.json)는 확대 실행의 별도 기록입니다. **2026-09-14 21:02 KST에 실행을 시작했고, 21:08 KST에 첫 미실행 문제 scikit-learn 3840의 실제 새 high 세션·도구 사용을 확인했습니다.** 기존 경험은 18문제·82건을 승계했습니다. 현재 경험 수집 단계이며 본 평가 해결률 차이는 아직 미측정입니다. [실제 시작 검증](../artifacts/skhynix_v1/architecture_scale_001/live-start-validation-001.json)과 [기존 24개 설정의 과거 상태와 예상 일정](SKHYNIX_PILOT_STATUS_BEFORE_SCALE.md)을 따로 보존했습니다. 과거 예상 일정은 현재 일정이 아닙니다. [수집 규모 검토](SKHYNIX_MEMORY_COLLECTION_SCALE_REVIEW.md)의 확대안을 적용한 정확한 실행 범위는 위의 확대 실행 문서를 기준으로 합니다.

아래는 이전 소규모 실험 결과입니다. 이를 현재 전체 PDF 구조 비교의 성능 향상으로 사용하지 않습니다.
