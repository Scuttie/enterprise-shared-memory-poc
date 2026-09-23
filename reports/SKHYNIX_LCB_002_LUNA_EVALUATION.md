# LiveCodeBench Luna 메모리 실험

2026-09-24 완료. 같은 VALID 24문제에서 **gpt-5.6-luna / low의 최종 제출·정답 성공률은 OFF 12/24(50.0%), ON 22/24(91.7%)로 +41.7%p**였다. 다만 큰 차이의 대부분은 제출 규약을 통과했는지에서 생겼다. 미제출 원본 코드까지 별도로 채점한 보조 비교는 OFF 22/24, ON 24/24다. 본 성적을 이 보조 수치로 바꾸지 않는다.

이 실행은 이미 관측한 VALID에서의 탐색적 파일럿이다. 최종 TEST 182문제는 사용하지 않았으며, 일반화된 성능 향상이나 L0~L3 전체의 효과를 입증한 결과는 아니다.

## 성적과 같은 문제끼리의 비교

| 모델·설정 | OFF | ON | 차이 |
| --- | ---: | ---: | ---: |
| Astra / low, 앞선 같은 24문제 | 24/24 (100%) | 24/24 (100%) | 0%p |
| Luna / low, 이번 같은 24문제 | 12/24 (50.0%) | 22/24 (91.7%) | +41.7%p |

| Luna 결과 분류 | OFF | ON |
| --- | ---: | ---: |
| 정상 제출·비공개 테스트 통과 | 12 | 22 |
| 정상 제출·비공개 테스트 실패 | 1 | 0 |
| MissingSubmission | 11 | 2 |
| 실행 환경 오류·미확정 | 0 | 0 |
| 전체 분모 | 24 | 24 |

미제출은 정해둔 성공 기준에서 `resolved=false`지만, 채점을 하지 않은 원래 `passed` 값은 `null`로 보존한다. 정답을 틀린 경우와 구분한다. 공개 테스트와 여러 세션을 허용한 도구 사용 프로토콜이므로 리더보드의 단일 생성 pass@1과 같은 지표가 아니다.

동일 ID의 OFF 실패→ON 성공 11개, OFF 성공→ON 실패 1개, 양쪽 성공 11개, 양쪽 실패 1개였다. 전체 24쌍의 exact McNemar 양측 p=0.00635이나, 반복적으로 관측한 VALID의 탐색 결과이며 다중 탐색에 대한 보정은 없다. 양쪽 모두 실제 제출·채점된 것은 12쌍이고, 그 부분집합에서는 오답→정답 1개, 정답→오답 0개다.

| 난도 | 문제 수 | OFF 성공 | ON 성공 |
| --- | ---: | ---: | ---: |
| easy | 8 | 6 | 7 |
| medium | 8 | 4 | 7 |
| hard | 8 | 2 | 8 |

[최종 결과 JSON](../artifacts/skhynix_v1/lcb_002/pilot-results-001.json), [문제별 비교 CSV](../artifacts/skhynix_v1/lcb_002/pilot-paired-results-001.csv), [Astra/Luna 비교](../artifacts/skhynix_v1/lcb_002/model-comparison-001.json). 문제 교체·실패 삭제·추가 모델 재시도 없이 원래 분모를 유지했다.

## 제출 실패와 코드 정답성을 분리한 진단

초기 두 TRAIN 실패를 확인했을 때 모델은 `finish`를 반복 호출했으나 `source_lesson.trace_steps`에 정수 step 번호 대신 문자열·객체·빈 목록을 넣어 거부됐다. 오류 메시지는 모델에 전달됐지만, 프롬프트의 `[ACTUAL_PUBLIC_TRACE_STEP]` 예시는 정수 목록 제약을 명시하지 않았다. 이는 모델의 형식 준수 실패와 공유 도구 안내의 불충분함이 함께 있는 조건이다. 이 실행 중에는 양쪽 인터페이스를 바꾸지 않았다.

비공개 채점 전에 [보조 진단 규칙](../artifacts/skhynix_v1/lcb_002/POSTHOC_SUBMISSION_DIAGNOSTIC.md)을 커밋했다. 본 실행 종료 후 모든 미제출 28건의 마지막 적격 `finish` 코드, 없으면 공개 테스트 기록으로 확인되는 마지막 후보를 선택한 뒤 원본 그대로 한 번씩 채점했다. 모든 후보를 먼저 고른 후 비공개 평가를 시작했으며, 코드 수정·모델 호출·대체 후보 재시도·본 성적 변경은 없었다.

| 미제출 시도 | 대상 | 원본 코드 통과 | 원본 코드 실패 |
| --- | ---: | ---: | ---: |
| TRAIN | 15 | 12 | 3 |
| VALID OFF | 11 | 10 | 1 |
| VALID ON | 2 | 2 | 0 |

전체 28건 모두 진단 완료, 제외·미확정 0건이다. 정상 제출 코드와 이 미제출 후보를 합쳐 기술적으로 집계하면 OFF 22/24(91.7%), ON 24/24(100%)다. 이는 **남아 있던 후보 코드의 정답성에 대한 사후 보조 비교**이며, 모델이 실제로 모두 제출했을 때의 성적이나 공식 본 성적으로 간주하지 않는다. 이 비교에서도 차이는 2문제뿐이므로 알고리즘 능력의 일반적 향상을 확정할 수 없다.

[진단 원본 메타데이터](../artifacts/skhynix_v1/lcb_002/posthoc-submission-diagnostic-001.json), [초기 제출 규약 진단](../artifacts/skhynix_v1/lcb_002/early-submission-diagnostic-001.json). 비공개 결과는 모델이나 메모리로 되먹이지 않았다.

## 실행 시간

2026-09-24 00:51:10 KST 시작, 약 01:51 KST 완료. TRAIN 수집·VALID 양쪽 풀이·본 채점을 합친 controller 시간은 **3,593.19초, 약 59분 53초**다. 아래 값은 각 풀이의 wall time이며 채점 시간과 별도다.

| 비교 집합 | OFF 평균 / 중앙값 | ON 평균 / 중앙값 |
| --- | ---: | ---: |
| 모든 24문제, 실패 포함 | 96.00 / 93.74초 | 45.92 / 39.34초 |
| 양쪽 모두 정답인 같은 11문제 | 73.44 / 63.05초 | 40.17 / 33.60초 |

양쪽 정답 11쌍의 ON−OFF 차이는 평균 −33.27초, 중앙값 −31.01초다. 성공한 부분집합을 선택한 비교이고, 같은 기기의 병렬 실행·서비스 지연·실행 순서 영향도 있으므로 메모리에 의한 인과적 속도 향상으로 단정하지 않는다. 실패·성공·난도별 시간과 문제별 값은 [시간 분석](../artifacts/skhynix_v1/lcb_002/pilot-timing-outcomes-001.json)에 보존했다.

## 실험 설정과 실제 사용한 메모리

| 항목 | 설정 |
| --- | --- |
| 요청 모델 | `gpt-5.6-luna`, reasoning `low` |
| 호출 경로 | ChatGPT 로그인 기반 Codex native, 별도 OpenAI API 키 없음 |
| 벤치마크 | LiveCodeBench code_generation_lite release_v6, 전체 1,055문제 |
| 고정 분할 | TRAIN 767 / VALID 106 / TEST 182, family 교차 없음 |
| 이번 실행 | 같은 TRAIN 24개 + 같은 VALID 24개 × OFF/ON, 총 72시도 |
| 난도 | TRAIN·VALID 각각 easy/medium/hard 8개씩 |
| 병렬·한도 | 풀이 최대 2개, 문제당 600초·도구 24회·공개 테스트 4회·세션 4개 |
| 입력 예산 | 초기 prompt 196,608B, L0 context 48,000B, 주입 메모리 12,000B, 코드 65,536B |
| 비교 | OFF 공통 L0 / ON 공통 L0 + Luna TRAIN으로 동결한 L3→L2→L1 검색 |
| 공식 채점 | pinned LiveCodeBench evaluator, 테스트당 6초, worker 1개 |
| 비공개 결과 | 전체 풀이·경험 수집 후 채점, 모델·은행에 전달하지 않음 |

[Luna 설정](../configs/skhynix_v1/lcb_002_luna_pilot.json)은 Astra와 experiment ID 및 요청 모델만 다르다. 같은 문제 순서·예산·구현·검색 및 승격 기준을 유지하고 Luna의 TRAIN 경험으로 새 은행을 만들었다. 가중치 학습이 아닌 경험 수집이다. 모델 이름은 요청값이며 서버 측 가중치 식별자를 독립 검증한 것은 아니다. 계정 카탈로그의 일반 작업용 경량 모델을 골랐고, 모든 작업에서 절대적으로 가장 약하다는 뜻은 아니다.

기존 정책에서는 정상 제출한 TRAIN 9개만 저장됐다. 동결 은행은 **L1 9개, L2 노드 28개·관계 26개, L3 0개**, 검증된 공개 실패→수정→통과 절차 0개다. VALID 24개 중 23개에 총 36회의 L1 주입이 기록됐고, L2/L3 주입은 0회였다. 따라서 이번 차이를 L2/L3 효과나 네 계층 전체의 검증으로 설명할 수 없다.

[주입 근거 감사](../artifacts/skhynix_v1/lcb_002/pilot-exposure-audit-001.json)는 PASS/COMPLETE다. 모든 주입이 실제 동결 TRAIN 출처에 연결되고, 출처와 대상의 문제 ID·family가 다르며 은행과 종료 기록이 감사 전후 동일함을 확인했다. 최초 감사기는 과거 주입 노드가 최종 graph에도 남아 있어야 한다고 가정해 실패했다. 실제로 9개 target의 초기 `solution` 노드가 최초 DAG 변경으로 교체됐다. 감사기만 수정해 동결 실행 코드·체크포인트·추가 순서·요청/결과 해시가 연결된 최초 교체에 한해 과거 노드를 인정했고, 임의 노드·위조·잘못된 순서를 거부하는 회귀 검증을 추가했다. 주입별 시각은 원래 기록되지 않았으므로 있다고 주장하지 않는다. 실행 코드나 원본 은행·trace는 수정하지 않았다.

TEST 모델 호출 0회, 비공개 결과의 모델 전달 0회, capture/public infrastructure error 0건이다. 분할 격리는 실험 내 경계를 뜻하며 모델 사전학습의 벤치마크 오염 여부를 검증한 것은 아니다.

## 추가한 제출 실패 경험 저장

사용자 제안에 따라 별도 브랜치 `codex/lcb-negative-experience-v1`에 선택 정책 `TRAIN_TRACE_STEPS_REJECTION_L1_V1`을 구현했다. 기존 실행의 은행과 점수는 바꾸지 않았다.

본평가 종료 후 같은 TRAIN 24개의 공개 실행 근거만 재생해 **제출 경험 9개 + 제출 형식 실패 경험 15개**를 별도 은행에 저장했다. 제외 0개, 추가 모델·테스트·채점 호출 0회이며 원본 참조 해시의 불변을 확인했다. private verdict로 경험을 고르지 않았다. 재생은 새 문제풀이 또는 새 OFF/ON 평가가 아니다.

새 은행은 L1 24개, L2 노드 28개·관계 26개, L3 0개다. 원본 234개 참조의 불변을 확인했고 은행 SHA256은 `1dc2246a59c97153774fc4f091b4c56e7cdaed3c27107d466f3b31fef148e71a`다. [실제 재생 근거](https://github.com/Scuttie/skhynix-memory-experiment/blob/3ea83ec/artifacts/skhynix_v1/lcb_negative_001/actual-training-replay-001.json)는 별도 브랜치 commit `3ea83ec`에 push했다.

실패 경험에는 실제 거부 필드·타입·trace 증거·검증 규칙을 저장하고 `succeeded=false`, `correction_verified=false`를 유지한다. 다른 문제에서는 그 문제의 현재 trace 번호를 사용하도록 명시한다. 실패에서 L2 관계나 L3 절차를 만들지 않는다. 관련된 최종 제출 문맥에서 기존 L1 검색으로 조회할 수 있으며, 관련 없는 문제에 강제 주입하지 않는다.

코드·테스트·전달 안내는 [별도 브랜치](https://github.com/Scuttie/skhynix-memory-experiment/tree/codex/lcb-negative-experience-v1)에 있다. 코어 검증은 190 PASS·POSIX 전용 1 SKIP, 재생 도구 합성 검증은 10 PASS였다. 실패 경험을 이용한 후속 모델 평가는 아직 실행하지 않았으므로 이 기능의 효과로 이번 상승을 설명하면 안 된다.

향후 알고리즘 성능을 비교할 때에는 제출 스키마 안내를 OFF와 ON에 똑같이 명확하게 제공해야 한다. 실패 메모리로 도구 사용 오류를 줄이는 가치는 별도로 측정하되, 불충분한 baseline 안내를 유지해 상승을 만들지는 않는다.

## 재현 근거

- 실행 구현 commit: `7b5c7e5d64e2ef11ef68e0e1b5ee0ff8fd4bcaf2`, 구현 파일 47개 동결.
- [실행 시작](../artifacts/skhynix_v1/lcb_002/execution-start-001.json), [최종 진행 기록](../artifacts/skhynix_v1/lcb_002/pilot-progress-001.json), [분석 재현 명령](../artifacts/skhynix_v1/lcb_002/ANALYSIS_HELPERS.md).
- public split SHA256: `a960fee4bd549dcec2bda5828b657b4b2cd6af76198485030c33a4a55e5a75c9`.
- frozen inputs SHA256: `972061d70b0c4744ba07c951bbed267313271c30b5f8a42794c79d2e3aeaad59`.
- 본 실험 bank SHA256: `28cab53a800811a72004cf13e64b0952bb5235b15b001543d796752637338f0d`.
- primary summary SHA256: `6ba3dfd8103aa28c37dddb7fe14044e453e3a4f0a22a520d00a3431c7547b8dc`.

GLM에서도 고정한 문제 ID와 예산을 사용하고 GLM 자체 TRAIN 경험을 새로 수집한다. 사내 Linux 컨테이너 반입·설치 및 남은 모델 연결 작업은 [전달 안내](../docs/port/LCB_CONTAINER_HANDOFF.md)를 따른다.
