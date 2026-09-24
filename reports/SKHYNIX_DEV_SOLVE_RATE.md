# SK hynix DEV 실제 해결률 비교

**평가 완료 — 공식 채점 36/36개, 세 조건 모두 채점된 공통 대상 12/12개.**

메모리 없음 0.00% · 기존 M2 8.33% · SK hynix 구조 8.33%.

SK hynix 구조의 관측 차이: 메모리 없음 대비 +8.33%p · 기존 M2 대비 +0.00%p.

해석상 핵심 제약: 공식 채점된 36회 중 **36회가 하위 작업 단계 제한에 도달**했습니다. 제한 시점에 확보된 제출물을 공식 채점한 결과이며, 충분한 실행 단계를 제공했을 때의 성능은 이번 실험으로 추정할 수 없습니다.

후속 로그 진단에서 **32/36회는 정확히 8번의 solve 호출 후 종료**했고,
**32/36회는 실제 수정 패치가 없어 `CANONICAL_FAILED_CELL_NOOP`을 채점**한 것으로 확인했습니다.
파일 검색·읽기도 각각 한 단계를 사용합니다. 예를 들어 SymPy의 메모리 없는 실행은
검색 7회와 파일 읽기 1회로 8단계를 소진했으며, 이 중 동일 요청의 중복 실행이 4회였습니다.
현재 연장은 코드 diff 증가 또는 최초의 인정된 테스트 통과를 요구하므로 탐색 자체나
실패 재현은 연장 근거가 되지 않습니다. 모델 입력에는 남은 단계 수와 이 연장 규칙도
명시하지 않았습니다. 우선 탐색 예산·단계 안내·반복 도구 호출 대응을 검증한 뒤
같은 모델로 비교해야 모델 용량과 메모리 구조의 영향을 더 잘 구분할 수 있습니다.
[단계 계산](../src/enterprise_memory/trimem/agent_runtime.py),
[연장 규칙](../src/enterprise_memory/trimem/adaptive_horizon.py).

미실행 또는 공식 채점 미완료 셀은 오답으로 계산하지 않았습니다. 아래 해결률과 비교 통계는 동일한 공통 대상만 사용합니다.

| 조건 | 공식 채점 완료 | 공통 정답/n | 해결률 | 95% Wilson 구간 | 호출 | 입력/출력 토큰 | API 비용 | 메모리 주입 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 메모리 없음 (`NO_MEMORY`) | 12/12 | 0/12 | 0.00% | 0.00%–24.25% | 131 | 849,868/65,305 | $0.918918 | 0 |
| 기존 M2 (`EXISTING_M2`) | 12/12 | 1/12 | 8.33% | 1.49%–35.39% | 128 | 976,530/59,418 | $0.983362 | 12 |
| SK hynix 구조 (`SKHYNIX`) | 12/12 | 1/12 | 8.33% | 1.49%–35.39% | 131 | 936,835/63,485 | $0.970770 | 5 |

호출·토큰·비용·주입량은 해당 조건에서 공식 결과가 저장된 모든 셀의 합입니다. 미완료 셀에서 이미 발생한 비용은 아래 전체 예산 장부에 별도로 포함될 수 있습니다.

| 비교 기준 | 공통 n | SK hynix − 기준(%p) | 기준 실패 → SK 성공 | 기준 성공 → SK 실패 | 정확 양측 McNemar p |
| --- | ---: | ---: | ---: | ---: | ---: |
| 메모리 없음 | 12 | +8.33 | 1 | 0 | 1 |
| 기존 M2 | 12 | +0.00 | 0 | 0 | 1 |

McNemar 검정은 동일 문제에서 결과가 바뀐 쌍을 사용합니다. 두 비교의 p값은 다중 비교 보정 전 값입니다.

| DEV 대상 | 메모리 없음 | 기존 M2 | SK hynix 구조 |
| --- | --- | --- | --- |
| django__django-16100 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/00/NO_MEMORY/public-result.json>) | [해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/00/EXISTING_M2/public-result.json>) | [해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/00/SKHYNIX/public-result.json>) |
| sympy__sympy-23262 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/01/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/01/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/01/SKHYNIX/public-result.json>) |
| sphinx-doc__sphinx-11445 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/02/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/02/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/02/SKHYNIX/public-result.json>) |
| matplotlib__matplotlib-25311 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/03/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/03/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/03/SKHYNIX/public-result.json>) |
| mui__material-ui-29880 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/04/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/04/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/04/SKHYNIX/public-result.json>) |
| ponylang__ponyc-1981 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/05/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/05/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/05/SKHYNIX/public-result.json>) |
| clap-rs__clap-3960 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/06/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/06/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/06/SKHYNIX/public-result.json>) |
| facebook__zstd-938 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/07/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/07/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/07/SKHYNIX/public-result.json>) |
| sharkdp__bat-1276 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/08/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/08/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/08/SKHYNIX/public-result.json>) |
| catchorg__Catch2-1616 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/09/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/09/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/09/SKHYNIX/public-result.json>) |
| clap-rs__clap-3394 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/10/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/10/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/10/SKHYNIX/public-result.json>) |
| cli__cli-869 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/11/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/11/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_001/cells/11/SKHYNIX/public-result.json>) |

해결 여부는 공식 grader의 `resolved` 값으로 결정합니다. `agent_completed=false` 또는 `CELL_SCIENTIFIC_FAILURE`여도 제출된 부분 패치가 공식 테스트를 통과하면 해결로 셉니다.

| 실행 진단 | 에이전트 완료 | 에이전트 미완료 | CELL_SCIENTIFIC_FAILURE | 모델 실패 분류 |
| --- | ---: | ---: | ---: | --- |
| 메모리 없음 | 0 | 12 | 12 | per-subtask step cap reached: 12 |
| 기존 M2 | 0 | 12 | 12 | per-subtask step cap reached: 12 |
| SK hynix 구조 | 0 | 12 | 12 | per-subtask step cap reached: 12 |

전체 장부의 확정 API 비용은 **$2.873050**, 사전 상한은 **$5.000000**입니다. 공식 결과가 저장된 셀의 비용 합계는 $2.873050입니다.

전체 유료 호출 390회 · 입력 2,763,233토큰 (캐시 입력 68,608) · 출력 188,208토큰 · grader 컨테이너 36개.

장부의 미정산 예약량: `{"decomposition_calls": 0, "extraction_calls": 0, "grader_containers": 0, "input_tokens": 0, "output_tokens": 0, "paid_model_calls": 0, "solve_calls": 0, "task_arm_runs": 0, "total_usd": 0.0}`. 예약량은 확정 청구액과 구분합니다.

모델은 `gpt-5.4-mini-2026-03-17`이며 세 조건에 같은 runtime lock과 예산 제한을 적용했습니다. 대상 순서대로 메모리 없음 → 기존 M2 → SK hynix 구조를 실행하고, 각 셀은 별도 작업공간과 초기 메모리 bank를 사용했습니다. 공식 harness·데이터셋·컨테이너 digest를 고정했습니다.

이 결과는 12개 DEV 문제의 탐색 평가입니다. 기존 DEV 진단에서 선택한 과거 PR bank를 재사용했으므로 독립적인 held-out 일반화 결과가 아닙니다. 초기 개인 경험(L1)은 없고, L2 저장소 KG 간선은 **0개**, 검증된 절차형 스킬(L3)은 **0개**입니다. 과거 PR은 저장소 지식 레코드로만 사용했습니다. SK hynix 조건은 L0 문맥 관리와 L2 검색 변경을 함께 적용하므로 각 요소의 효과를 분리할 수 없습니다. 이번 실행은 Gate A/B 학습·승격이나 KG 그래프 간선의 효과를 측정하지 않았습니다. 소규모 DEV 결과로 대규모 Skill Library의 효과, 지속 학습·스킬 승격의 효과, 일반적인 해결률 상승을 주장할 수 없습니다. 12개 모두 완료했을 때 추가 해결 1개는 +8.33%p입니다. 단일 실행이며 반복 실행의 변동성은 측정하지 않았습니다.

API 가격은 입력/캐시 입력/출력 100만 토큰당 $0.75/$0.075/$4.50을 적용했습니다. [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini). 새 실제 평가 도우미·집계·예산·source bank 검증 테스트 50개 PASS: [JUnit 기록](<../artifacts/skhynix_v1/live_validation.xml>).

실행 계획과 원본 집계: [plan.json](<../artifacts/skhynix_v1/live_001/plan.json>) · [report.json](<../artifacts/skhynix_v1/live_001/report.json>).

[공식 환경 사전 검사](<../artifacts/skhynix_v1/live_001/control/local-environment-preflight.json>) · [공식 harness loader 검사](<../artifacts/skhynix_v1/live_001/control/official-harness-loader-preflight.json>) · [예산 장부](<../artifacts/skhynix_v1/live_001/budget-ledger.json>) · [이미지 정리](<../artifacts/skhynix_v1/live_001/image-cleanup.json>) · [독립 최종 감사](<../artifacts/skhynix_v1/live_001/audit.json>) · [공개 증거 파일 SHA-256 목록](<../artifacts/skhynix_v1/live_001/public-artifact-manifest.json>).

구조 설명: [SKHYNIX_MEMORY_V1.md](<../docs/SKHYNIX_MEMORY_V1.md>).

| 재현성 항목 | 정확한 값 |
| --- | --- |
| Git 기반 HEAD | `d4fd304339687b42c645ae84872a72eddddcda97` |
| 실행 계획 canonical SHA-256 | `a7e499d01263564cba3fa9183b0872778e0306ae78431cfdb9117face9176722` |
| plan.json 파일 SHA-256 | `c98d1a2b21313c6251a1a57722677a54aebfd69e31a482fec09c9836b5345b99` |
| report.json 파일 SHA-256 | `a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0` |
| 전체 소스 해시 목록 canonical SHA-256 (320개) | `167aca389ab2e0093a8cb93b93672f0ec33e1f4d95d0abbc4879b4d60ec0de8a` |
| runtime lock canonical SHA-256 | `c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652` |
| source bank 파일 SHA-256 | `8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309` |
| scripts/trimem_skhynix_live.py | `b50e12cdbb2c57cfb8045359d61b752f3e7434430d5f28d8dd6b5e277254637d` |
| scripts/trimem_skhynix_environment.py | `da6ede5fcec1b32d369924fa02a720823ce8d3a58782e874716c69af44af8c49` |
| scripts/trimem_skhynix_source_bank.py | `fc2f593a0ecde053753ddbdcd8e1bded9770e68742f87af7b13b64600ef49d5a` |
| src/enterprise_memory/trimem/skill_memory.py | `ef827d2f2bc70bc15c13ea710d048c01d3365539d399e17e3ddf9b34627d3951` |
| src/enterprise_memory/trimem/skill_runtime.py | `a69ca3abdc584c58f53120c2f488d21072961116732f49b586af666a4318aaa9` |
| src/enterprise_memory/trimem/subgoal_context.py | `06e0a9efb15c256437e318e5c4957b009deb2712585a2363a4482128309deea5` |

데이터·대상·모델·검색기·전체 실행 소스의 상세 고정값은 plan.json에 보존했습니다. 이 Markdown은 공개 집계 JSON만 읽어서 생성했으며 모델 응답 원문이나 API 키를 포함하지 않습니다.
