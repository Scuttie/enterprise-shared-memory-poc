# SK hynix 탐색 예산·안내 변경 후 실제 해결률 재평가

**평가 미완료 — 공식 채점 8/36개, 세 조건 모두 채점된 공통 대상 2/12개.**

실행 상태: `INCOMPLETE`.

중단 분류: `ModelPreflightFailure` / `PHASE_USD_CAP_EXHAUSTED`. 미실행 셀은 오답에 포함하지 않았습니다.

메모리 없음 50.00% · 기존 M2 50.00% · SK hynix 구조 50.00%.

SK hynix 구조의 관측 차이: 메모리 없음 대비 +0.00%p · 기존 M2 대비 +0.00%p.

같은 Django·SymPy에서 기본 에이전트의 해결 수는 이전 0/2에서 1/2로 늘었고,
두 메모리 조건은 1/2로 유지됐습니다. Django는 세 조건 모두 해결했고 SymPy는
모두 실패했습니다. 이 6회 실행은 모두 실제 패치를 만들었지만, 올바른 해결과
에이전트의 완료 선언은 별개입니다. 이번 결과만으로 메모리 구조의 추가 이득이나
전체 12문제의 해결률 상승을 확인했다고 볼 수 없습니다.

002에서는 하위 작업당 **24단계**, 전체 task당 **48회 solve 호출·48단계**를 허용했습니다. 모델에 남은 호출 예산과 마지막 4회의 수정·검증·완료 계획을 안내하고, 동일 검색·읽기 요청과 성공 결과가 반복되면 다른 조사·수정 경로를 권하는 안내를 추가했습니다. 기존 적응형 연장은 비활성화했습니다. 이는 도구 호출 횟수에 관한 예산이며 별도 초 단위 마감 시간을 추가한 것은 아닙니다.

공식 채점된 8개 중 6개는 단계·호출 상한에 도달했습니다. 상한 전에 확보된 패치도 공식 grader로 채점하며, 전체 API 예산·토큰 제한은 탐색 단계보다 먼저 실행을 멈출 수 있습니다.

미실행 또는 공식 채점 미완료 셀은 오답으로 계산하지 않았습니다. 아래 해결률과 비교 통계는 동일한 공통 대상만 사용합니다.

| 조건 | 공식 채점 완료 | 공통 정답/n | 해결률 | 95% Wilson 구간 | 호출 | 입력/출력 토큰 | API 비용 | 메모리 주입 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 메모리 없음 (`NO_MEMORY`) | 3/12 | 1/2 | 50.00% | 9.45%–90.55% | 116 | 1,926,376/57,914 | $1.627808 | 0 |
| 기존 M2 (`EXISTING_M2`) | 3/12 | 1/2 | 50.00% | 9.45%–90.55% | 126 | 2,371,877/82,179 | $2.054883 | 3 |
| SK hynix 구조 (`SKHYNIX`) | 2/12 | 1/2 | 50.00% | 9.45%–90.55% | 100 | 1,317,479/46,527 | $1.141926 | 2 |

호출·토큰·비용·주입량은 해당 조건에서 공식 결과가 저장된 모든 셀의 합입니다. 미완료 셀에서 이미 발생한 비용은 아래 전체 예산 장부에 별도로 포함될 수 있습니다.

| 비교 기준 | 공통 n | SK hynix − 기준(%p) | 기준 실패 → SK 성공 | 기준 성공 → SK 실패 | 정확 양측 McNemar p |
| --- | ---: | ---: | ---: | ---: | ---: |
| 메모리 없음 | 2 | +0.00 | 0 | 0 | 1 |
| 기존 M2 | 2 | +0.00 | 0 | 0 | 1 |

001 → 002의 조건별 변화는 **002에서 세 조건 모두 공식 채점된 동일 대상만** 사용해 계산했습니다. 실행 예산과 안내 정책을 함께 변경한 과거 실행과의 비교이며, 개별 변경의 인과 효과를 분리한 실험은 아닙니다.

| 동일 조건의 001 → 002 비교 | 공통 n | 001 정답/n (해결률) | 002 정답/n (해결률) | 002 − 001(%p) | 실패 → 성공 | 성공 → 실패 | 정확 양측 McNemar p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 메모리 없음 | 2 | 0/2 (0.00%) | 1/2 (50.00%) | +50.00 | 1 | 0 | 1 |
| 기존 M2 | 2 | 1/2 (50.00%) | 1/2 (50.00%) | +0.00 | 0 | 0 | 1 |
| SK hynix 구조 | 2 | 1/2 (50.00%) | 1/2 (50.00%) | +0.00 | 0 | 0 | 1 |

동일 공통 대상의 실행 진단 변화(조건별 n=2, 각 칸은 001 → 002):

| 조건 | 에이전트 완료 | 단계·호출 상한 | canonical noop |
| --- | ---: | ---: | ---: |
| 메모리 없음 | 0 → 1 | 2 → 1 | 2 → 0 |
| 기존 M2 | 0 → 1 | 2 → 1 | 1 → 0 |
| SK hynix 구조 | 0 → 0 | 2 → 2 | 0 → 0 |

아래 001 전체 12개 결과는 **참고용**이며, 위 공통 대상 비교의 분모와 섞지 않았습니다.

| 001 전체 결과(참고) | 정답/12 | 해결률 |
| --- | ---: | ---: |
| 메모리 없음 | 0/12 | 0.00% |
| 기존 M2 | 1/12 | 8.33% |
| SK hynix 구조 | 1/12 | 8.33% |

002의 중단 위치는 비용과 고정 실행 순서의 영향을 받습니다. 완료된 앞부분의 해결률을 전체 12개로 외삽하지 않습니다.

McNemar 검정은 동일 문제에서 결과가 바뀐 쌍을 사용합니다. 이 보고서의 p값은 다중 비교 보정 전 값이며, 단일 실행의 표본 변동성을 함께 고려해야 합니다.

| DEV 대상 | 메모리 없음 | 기존 M2 | SK hynix 구조 |
| --- | --- | --- | --- |
| django__django-16100 | [해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/00/NO_MEMORY/public-result.json>) | [해결](<../artifacts/skhynix_v1/live_002/cells/00/EXISTING_M2/public-result.json>) | [해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/00/SKHYNIX/public-result.json>) |
| sympy__sympy-23262 | [미해결](<../artifacts/skhynix_v1/live_002/cells/01/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/01/EXISTING_M2/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/01/SKHYNIX/public-result.json>) |
| sphinx-doc__sphinx-11445 | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/02/NO_MEMORY/public-result.json>) | [미해결 (에이전트 미완료)](<../artifacts/skhynix_v1/live_002/cells/02/EXISTING_M2/public-result.json>) | 미실행/공식 채점 미완료 |
| matplotlib__matplotlib-25311 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| mui__material-ui-29880 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| ponylang__ponyc-1981 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| clap-rs__clap-3960 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| facebook__zstd-938 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| sharkdp__bat-1276 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| catchorg__Catch2-1616 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| clap-rs__clap-3394 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |
| cli__cli-869 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 | 미실행/공식 채점 미완료 |

해결 여부는 공식 grader의 `resolved` 값으로 결정합니다. `agent_completed=false` 또는 `CELL_SCIENTIFIC_FAILURE`여도 제출된 부분 패치가 공식 테스트를 통과하면 해결로 셉니다.

| 실행 진단 | 에이전트 완료 | 에이전트 미완료 | 단계·호출 상한 | canonical noop | CELL_SCIENTIFIC_FAILURE | 모델 실패 분류 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 메모리 없음 | 1 | 2 | 2 | 1 | 2 | per-subtask step cap reached: 2 |
| 기존 M2 | 1 | 2 | 2 | 1 | 2 | per-subtask step cap reached: 1, solve-call or global step cap reached: 1 |
| SK hynix 구조 | 0 | 2 | 2 | 0 | 2 | solve-call or global step cap reached: 2 |

SymPy의 공개 도구 기록에는 성공한 로컬 테스트 증거가 없습니다. 메모리 없음은
테스트 실행을 시도하지 않았고, 기존 M2와 SK hynix는 `run_public_tests`를 각각
2회 요청했으나 모두 runner 부재로 exit 2를 받았습니다. 이 4회는 테스트를
실행한 뒤 실패한 것이 아닙니다. 기존 M2의 별도 `run_command` 1회도 CLI 오류로
끝났습니다. SK hynix는 전체 48회 제한에 도달해 1,722바이트 부분 패치를
제출했으나 공식 채점을 통과하지 못했습니다.

코드에서도 이 제약을 확인했습니다. [벤치마크 연결](../scripts/trimem_benchmark_run.py)의
`coding_tasks()`는 `public_test=None`을 설정하고 `prepare_checkouts()`는
factory에 `public_tests`를 등록하지 않습니다. 따라서
[작업공간](../src/enterprise_memory/trimem/git_workspace.py)의 `run_public_tests()`는
항상 unavailable을 반환하지만, [도구 설명](../src/enterprise_memory/trimem/function_tools.py)은
테스트를 실행할 수 있는 것처럼 안내합니다. 이 동작은 001과 002에 공통입니다.
`run_command`로 공개 저장소 테스트를 실행할 수 있는 경로는 있으나, 현재 환경
사전 검사는 저장소별 테스트 인터프리터와 의존성의 준비 상태를 확인하지 않습니다.
다음 평가에서는 공개 저장소에서 도출한 테스트 명령을 연결하고 실행 가능 여부를
확인해야 합니다. 002 실행 중에는 이 조건을 바꾸지 않았습니다.

전체 장부의 확정 API 비용은 **$4.897316**, 사전 상한은 **$5.000000**입니다. 공식 결과가 저장된 셀의 비용 합계는 $4.824616, 그 합계에 포함되지 않은 호출의 확정 비용은 $0.072700입니다. 001 비용은 이번 실행 상한에 합산하지 않았습니다.

정확한 확정 비용은 **$4.89731595**입니다. 다음 호출의 최대 입력·출력 비용을
사전 예약할 여유가 없어 $5에 도달하기 전에 중단됐습니다. 미완료 Sphinx의
SK hynix 실행에서 발생한 $0.07269975는 분해 1회·solve 7회의 비용이며,
공식 grader 결과가 없어 해결률에서 제외했습니다. 실행 프로세스는 종료됐고
진행 중인 유료 요청과 미정산 금액은 0입니다. 아래 작업·grader 예약 각 1개는
미완료 작업의 용량 예약을 뜻합니다.

전체 유료 호출 350회 · 입력 5,669,531토큰 (캐시 입력 336,256) · 출력 193,809토큰 · grader 컨테이너 8개.

장부의 미정산 예약량: `{"decomposition_calls": 0, "extraction_calls": 0, "grader_containers": 1, "input_tokens": 0, "output_tokens": 0, "paid_model_calls": 0, "solve_calls": 0, "task_arm_runs": 1, "total_usd": 0.0}`. 예약량은 확정 청구액과 구분합니다.

모델은 `gpt-5.4-mini-2026-03-17`이며 세 조건에 같은 runtime lock과 예산 제한을 적용했습니다. 대상 순서대로 메모리 없음 → 기존 M2 → SK hynix 구조를 실행하고, 각 셀은 별도 작업공간과 초기 메모리 bank를 사용했습니다. 공식 harness·데이터셋·컨테이너 digest를 고정했습니다.

이 결과는 12개 DEV 문제의 탐색 평가입니다. 기존 DEV 진단에서 선택한 과거 PR bank를 재사용했으므로 독립적인 held-out 일반화 결과가 아닙니다. 초기 개인 경험(L1)은 없고, L2 저장소 KG 간선은 **0개**, 검증된 절차형 스킬(L3)은 **0개**입니다. 과거 PR은 저장소 지식 레코드로만 사용했습니다. SK hynix 조건은 L0 문맥 관리와 L2 검색 변경을 함께 적용하므로 각 요소의 효과를 분리할 수 없습니다. 이번 실행은 Gate A/B 학습·승격이나 KG 그래프 간선의 효과를 측정하지 않았습니다. 소규모 DEV 결과로 대규모 Skill Library의 효과, 지속 학습·스킬 승격의 효과, 일반적인 해결률 상승을 주장할 수 없습니다. 12개 모두 완료했을 때 추가 해결 1개는 +8.33%p입니다. 단일 실행이며 반복 실행의 변동성은 측정하지 않았습니다.

독립 감사의 **4,074개 검사 통과·실패 0개**를 확인했습니다. 완료된 8개 공식
결과와 미완료 실행의 비용을 장부에 대조했고, 실제 유료 solve 요청 333개에
전달된 남은 예산·안내·요청 해시를 검증했습니다. 완료된 실행의 326개 solve
요청 중 71개에 반복 관측 안내가 노출됐습니다. 이는 안내가 전달됐다는 증거이며
그 안내만의 해결률 효과를 입증하지는 않습니다. 감사의 `PASS_INTERIM`은 전체
36개가 아닌 부분 평가 범위를 뜻하며, `terminal_partial_reconciliation`은
종료 상태 `INCOMPLETE`와 미완료 비용 대조 `PASS`를 별도로 명시합니다.
Windows와 Linux의 실행 소스 322개 해시가 일치하고, 기존 동결 파일 651개
검사와 001 원본 보고서 해시 보존 검사도 통과했습니다.

API 가격은 입력/캐시 입력/출력 100만 토큰당 $0.75/$0.075/$4.50을 적용했습니다. [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini). 실행 전 탐색 runtime·집계·예산·기존 연계 검증 테스트 **134개 PASS**. 기능 테스트 수는 해결률 표본 수에 포함하지 않았습니다.

실행 계획과 원본 집계: [plan.json](<../artifacts/skhynix_v1/live_002/plan.json>) · [report.json](<../artifacts/skhynix_v1/live_002/report.json>).

[탐색 재평가 JUnit 기록](<../artifacts/skhynix_v1/exploration_validation.xml>).

변경하지 않은 001 원본 증거: [001 계획](<../artifacts/skhynix_v1/live_001/plan.json>) · [001 집계](<../artifacts/skhynix_v1/live_001/report.json>).

[공식 환경 사전 검사](<../artifacts/skhynix_v1/live_002/control/local-environment-preflight.json>) · [공식 harness loader 검사](<../artifacts/skhynix_v1/live_002/control/official-harness-loader-preflight.json>) · [예산 장부](<../artifacts/skhynix_v1/live_002/budget-ledger.json>) · [실행 중단 기록](<../artifacts/skhynix_v1/live_002/failure.json>) · [독립 최종 감사](<../artifacts/skhynix_v1/live_002/audit.json>) · [공개 증거 파일 SHA-256 목록](<../artifacts/skhynix_v1/live_002/public-artifact-manifest.json>).

구조 설명: [SKHYNIX_MEMORY_V1.md](<../docs/SKHYNIX_MEMORY_V1.md>).

| 재현성 항목 | 정확한 값 |
| --- | --- |
| Git 기반 HEAD | `d4fd304339687b42c645ae84872a72eddddcda97` |
| 실행 계획 canonical SHA-256 | `77d9a124cdca38eb310b7871824907bcbfc5587e0e4aa53bca1fde7a27e7a710` |
| plan.json 파일 SHA-256 | `da7f01fbb112e3573729b7dab665dea24dfe8a2228a33e36b6aa5ffb9d3ded04` |
| report.json 파일 SHA-256 | `1971c9ebb9f5f8e7cbb7188ca33c031725c009240184fbb7fecf84f140a0f784` |
| 불변 001 계획 canonical SHA-256 | `a7e499d01263564cba3fa9183b0872778e0306ae78431cfdb9117face9176722` |
| 불변 001 report.json 파일 SHA-256 | `a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0` |
| 전체 소스 해시 목록 canonical SHA-256 (322개) | `fd544eb238c495bd26b852d09b46248501e8e3fcabcc5e4cffc895315d09d27f` |
| runtime lock canonical SHA-256 | `d0115cb756ba4fc4cd0955fd7cb4952e7b52afdb4e534b7bed839ed6cb7b51b5` |
| source bank 파일 SHA-256 | `8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309` |
| scripts/trimem_skhynix_exploration.py | `f0bea40544287bc6e3caad44115bea95d9c58392d08fa1b3fd7eb0b4f96bfa8a` |
| src/enterprise_memory/trimem/exploration_runtime.py | `aa30e32bb83e24b028cd3fed093c4e1f8a72e43b8f327b9400a77ee7cbb50bdb` |
| scripts/trimem_skhynix_environment.py | `da6ede5fcec1b32d369924fa02a720823ce8d3a58782e874716c69af44af8c49` |
| scripts/trimem_skhynix_source_bank.py | `fc2f593a0ecde053753ddbdcd8e1bded9770e68742f87af7b13b64600ef49d5a` |
| src/enterprise_memory/trimem/skill_memory.py | `ef827d2f2bc70bc15c13ea710d048c01d3365539d399e17e3ddf9b34627d3951` |
| src/enterprise_memory/trimem/skill_runtime.py | `a69ca3abdc584c58f53120c2f488d21072961116732f49b586af666a4318aaa9` |
| src/enterprise_memory/trimem/subgoal_context.py | `06e0a9efb15c256437e318e5c4957b009deb2712585a2363a4482128309deea5` |

데이터·대상·모델·검색기·전체 실행 소스의 상세 고정값은 plan.json에 보존했습니다.
해결률·비용 표는 공개 집계 JSON으로 생성했고, 실행 원장 대조와 코드 검토에
기반한 진단 설명을 덧붙였습니다. 모델 응답 원문이나 API 키는 포함하지 않습니다.
