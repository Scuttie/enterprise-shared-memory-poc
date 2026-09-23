# LiveCodeBench Luna 메모리 실험

2026-09-24. Astra/low에서 OFF와 ON이 모두 24/24였으므로, 동일하게 고정한 문제를
**gpt-5.6-luna / low**로 다시 평가한다. 현재 계정 카탈로그에서 일반 작업용으로 노출된
경량 모델과 최소 추론 설정을 선택했다. 모든 작업에 대한 절대 성능 최하위라는 뜻은 아니다.
숨겨진 내부 서비스·승인 검토 모델은 비교 후보에서 제외했다.

현재 상태: **설정 동결 및 연결 검증 완료, 본 실행 준비**. 합성 연결 확인은 성공했지만
아래 pilot의 실제 문제 성적은 아직 없다. 모델 요청은 ChatGPT 로그인 기반 Codex native이며
별도 OpenAI API 키는 사용하지 않는다. 실행 로그가 서버 측 가중치 식별자를 독립적으로
보증하지는 않으므로 모델 이름은 요청값으로 보고한다.

## 같은 조건에서 새 은행 수집

| 항목 | 설정 |
| --- | --- |
| 모델 | `gpt-5.6-luna`, reasoning `low` |
| 전체 분할 | train 767 / valid 106 / test 182 |
| 이번 수집·평가 | 같은 train 24개 / 같은 valid 24개 × OFF·ON / test 0개 |
| 병렬 | 문제 풀이 최대 2개 |
| 문제당 한도 | 600초, 도구 24회, 공개 테스트 4회, 세션 4개 |
| 메모리 | OFF 공통 L0, ON 공통 L0 + Luna 자체 train 경험으로 동결한 기존 L3→L2→L1 검색 |
| 공식 채점 | 기존 고정 commit, 테스트당 6초, worker 1개 |
| 숨은 성적 | 모든 문제 풀이·경험 수집 완료 뒤 일괄 채점, 모델·은행에 되먹이지 않음 |

[Luna 설정](../configs/skhynix_v1/lcb_002_luna_pilot.json)은 Astra 설정과
`experiment_id`, `requested_model`만 다르다. 문제 ID 순서, 난이도 각 8개, 예산, 메모리 정책과
관련성·승격 기준은 유지한다. 두 arm을 동시에 실행하므로 호출 목록의 교대가 실제 완료
순서를 보장하지는 않는다.

[고정 분할](../configs/skhynix_v1/lcb_001_public_split.json) SHA256:
`a960fee4bd549dcec2bda5828b657b4b2cd6af76198485030c33a4a55e5a75c9`.
새 출력 `data/skhynix_lcb_002/pilot-001` 아래의 training-memory와 frozen-bank를 사용하며
Astra 은행·답안은 재사용하지 않는다. 실제 소유자는 같은 `experiment-owner`다.
train은 가중치 학습이 아니라 문제풀이 경험 수집이다.

## 검증과 해석

- [계정 카탈로그 관측](../artifacts/skhynix_v1/lcb_002/model-catalog-observation.json)
- [합성 연결 검증](../artifacts/skhynix_v1/lcb_002/native-availability/receipt.json): Luna/low 요청 성공, 벤치마크 문제 0개
- [입력 사전 검증](../artifacts/skhynix_v1/lcb_002/preflight-001.json): 기존 구현 47개, 동일 분할·예산, 새 출력 분리
- [Astra 비교 결과](SKHYNIX_LCB_001_EVALUATION.md)

공식 [모델 안내](https://learn.chatgpt.com/docs/models)는 모델 선택과 계정별 접근 권한을
구분한다. 실제 접근성은 위 카탈로그와 연결 검증으로 확인했다.

이미 결과를 본 valid의 모델 비교이므로 탐색적 개발 평가다. 최종 test 182개는 보류한다.
모델의 실패·미제출·예산 소진은 그대로 기록하며 성적을 높이기 위한 재시도나 문제 교체는
하지 않는다. L1/L2/L3 저장 건수와 실제 주입 건수도 성적과 함께 보고한다.

GLM에서도 이 분할과 예산을 사용하고 자기 train 경험을 새로 수집한다.
Linux 반입·설치와 남은 GLM 연결 작업은 [전달 안내](../docs/port/LCB_CONTAINER_HANDOFF.md)를 따른다.
