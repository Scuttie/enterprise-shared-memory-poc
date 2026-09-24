# PDF 메모리 구조 실제 실행 기록

현재 상태(2026-09-14 17:38 KST): **학습 24문제 중 12문제 실제 풀이·공식 채점 완료, 7개 성공·5개 실패**. 공개 경험 52건을 수집했고, 완료한 12문제의 정리까지 마쳤다. 전체 파이프라인 v3의 프로세스 `37908`이 실행 중이며, 13번째 xarray 2922의 broker 요청이 점검 중 46→49→59회로 증가했다. `high` 전환 이후 실행 오류·수집 오류·미완료 정리는 0건이고 C 드라이브 여유는 약 50 GiB다. **학습 1~8번은 원래 `ultra` 기록을 보존하며, 9~24번·공개 reflection·본 평가 양쪽은 `high`**다. 본 비교 500쌍은 아직 시작 전이다. 기계가 갱신하는 최신 수치는 [progress.json](../artifacts/skhynix_v1/architecture_execution_001/progress.json)에 보존한다.

현재 완료된 `high` 4문제 전체를 기준으로 준비·풀이·채점·수집·정리와 다음 문제까지의 지연을 합친 실행 주기는 **평균 9분 37초**다. [실제 상태 점검과 high 시간 추정 근거](../artifacts/skhynix_v1/architecture_execution_001/runtime-estimate-high-001.json)에 원본 이벤트와 계산을 연결했다. 같은 속도를 가정하면 남은 학습 12개는 약 1시간 55분, 본 평가 1,000회는 약 160시간이다. 공개 reflection 12개의 native 시간 예산 합계 1시간을 더한 중심 예상은 **9월 21일 낮 12시 43분 KST 전후**이며, reflection 내보내기·검증 등의 미측정 시간은 추가된다. 현재 진행 중인 학습 문제도 평균 1회 전체 시간으로 계산했다.

계획용으로 이후 문제당 10~15분을 배정하면 **9월 21일 저녁~9월 25일 오전** 정도다. 이는 신뢰구간이 아닌 여유를 둔 시나리오다. 실측 표본은 Flask·Requests 4개뿐이므로 더 무거운 저장소, 본 평가의 메모리 문맥, 이미지 준비와 채점에 따라 달라진다. 서로 다른 문제의 측정값으로 `ultra` 대비 `high`의 인과적 속도 향상을 주장하지 않는다. 이 예상은 연속 실행 및 검증된 bank 발행을 전제로 한다. 현재 L3 스킬 0개는 아직 reflection 전인 상태이며, 학습 후에도 실제 Gate B 검증을 통과한 스킬이 없으면 본 평가 전에 명시적으로 중단한다.

| 실제 실행 | 현재 결과 |
| --- | --- |
| 학습 Astropy 6938 / PDF_MEMORY / 빈 지속 bank | 공식 `resolved: true`, 요청 64회, native 세션 3개, 제출까지 692.1초 |
| 학습 Astropy 7008 / PDF_MEMORY | 공식 `resolved: true`, 요청 75회, native 세션 3개, 제출까지 809.5초 |
| 학습 Django 5158 / PDF_MEMORY | 공식 `resolved: false`, 요청 45회, native 세션 3개, 제출까지 520.0초 |
| 학습 Django 5470 / PDF_MEMORY | 공식 `resolved: true`, 요청 56회, native 세션 3개, 제출까지 527.7초 |
| 학습 Matplotlib 13859 / PDF_MEMORY | 공식 `resolved: false`, 요청 62회, native 세션 3개, 제출까지 667.3초 |
| 학습 Matplotlib 13908 / PDF_MEMORY | 공식 `resolved: false`, 요청 86회, native 세션 3개, 제출까지 816.1초 |
| 학습 Seaborn 2389 / PDF_MEMORY | 공식 `resolved: true`, 요청 39회, native 세션 3개, 제출까지 427.8초 |
| 학습 Seaborn 2457 / PDF_MEMORY | 공식 `resolved: true`, 요청 43회, native 세션 3개, 제출까지 491.0초 |
| 학습 Flask 4045 / PDF_MEMORY / high | 공식 `resolved: false`, 요청 35회, native 세션 3개, 제출까지 314.8초 |
| 학습 Flask 4074 / PDF_MEMORY / high | 공식 `resolved: false`, 요청 68회, native 세션 3개, 제출까지 614.8초 |
| 학습 Requests 774 / PDF_MEMORY / high | 공식 `resolved: true`, 요청 30회, native 세션 3개, 제출까지 232.8초 |
| 학습 Requests 863 / PDF_MEMORY / high | 공식 `resolved: true`, 요청 41회, native 세션 3개, 제출까지 351.3초 |
| 학습 xarray 2922 / PDF_MEMORY / high | 실행 중; broker 요청 46→49→59회 증가 확인, 공식 결과 없음 |
| 학습 경험 수집 | 실제 공개 테스트 관찰·subgoal 종료 기록 52건 수집, 수집 오류 0건 |
| 검증된 공유 스킬 | 아직 0건; 공개 테스트 성공과 Gate B 승격을 구분 |
| 본 평가 500쌍 | 아직 시작 전, OFF/ON 해결률 차이 미측정 |

공식 결과·제출 패치·실행 감사의 해시는 progress.json의 `rows[].public_references`에서 확인할 수 있다. 현재 완료한 학습 표본의 7/12 성공을 메모리 사용에 따른 성능 향상이나 전체 학습 해결률로 해석하지 않는다. 학습 풀이는 빈 지속 bank에서 실행하며, 학습을 마친 뒤 공개 기록으로 만든 bank를 본 평가에 사용한다. 각 행의 `reasoning_effort`와 `training_by_reasoning_effort`로 실제 설정을 구분한다. 완료된 `high` 학습 4개 중 2개가 해결됐으며, 앞선 `ultra` 8개와는 문제가 달라 설정별 성능 비교가 아니다.

경험 수집 v2는 실제 공개 테스트가 관찰된 시점의 기록과 이후 수정 기록을 구분한다. 원본 전체 이력과 v1 기록은 보존하며, Gate B 판정 규칙은 변경하지 않았다. [수집 방식 변경 기록](../artifacts/skhynix_v1/architecture_execution_001/learning-revision-002.json)은 새 모델 풀이·새 공식 채점 없이 기존 공개 이력을 재수집했음을 명시한다.

완료된 작업의 자동 정리 중 이미지 해제 실패가 발생했고, 이미 삭제한 checkout을 상태 집계기가 다시 열려는 오류가 확인됐다. 고정된 원래 코드·설정·실패 기록을 보존한 채 controller v2를 별도 등록했다. 원래 공식 채점·수집 증거를 다시 검증하고 이미지가 없음을 확인하는 기록을 남겨, **풀이·채점 반복 없이 4개 작업의 정리와 집계를 완료**했다.

15:20 KST에 [실행 영수증](../artifacts/skhynix_v1/architecture_execution_001/processes/20260914T062004.1988129Z.launch.json)을 남기고 숨겨진 WSL 프로세스 `16896`으로 전체 파이프라인을 시작했다. 시작 명령이 반환된 뒤에도 프로세스가 유지됨을 확인했고, 두 번째 시작 명령은 같은 PID를 확인해 중복 생성을 차단했다. 이 기록은 파이프라인 시작 증거이며 전체 평가 완료 증거가 아니다.

이 프로세스는 Matplotlib 13859의 환경 구성 중 `official harness loader preflight invocation-construction identity differs`로 중단됐다. publisher 모듈 import가 바꾼 검색 경로 때문에 지연 import한 채점기 경로가 원래 loader 증거와 달라진 것이 원인이다. 해당 문제의 cell·checkout·준비 결과·native 세션 경로가 모두 없음을 확인했고, 모델 풀이·공식 채점은 0회다. [준비 단계 중단 진단](../artifacts/skhynix_v1/architecture_execution_001/preparation-abort-005.json)을 남겨 이 중단을 솔버 실패나 재풀이로 취급하지 않는다.

[명시적 준비 복구 기록](../artifacts/skhynix_v1/architecture_execution_001/preparation-recovery-005.json)을 먼저 남기고, 앞선 4문제와 같은 source-v4/config-v5의 직접 실행 경로로 환경 준비를 완료했다. 이후에야 이 문제의 첫 native 세션을 시작했다. 기존 cohort의 `PREPARE_STARTED` 복구 경로는 완성된 동일 cell 설정을 검증해 이어받도록 유지한다.

후속 pipeline v2는 다섯 번째 문제의 제출물을 검증해 공식 채점·경험 4건 수집·정리를 실제 완료했다. 15:55 KST에 [v2 실행 영수증](../artifacts/skhynix_v1/architecture_execution_001/processes/20260914T065532.7066394Z.launch.json)을 남기고 숨겨진 WSL 프로세스 `39536`으로 전체 실행을 이어갔다. 이후 cohort 이벤트 42·43에서 여섯 번째 문제의 자동 준비 완료와 풀이 시작을 확인했고, broker 상태는 `RUNNING`, 실제 요청은 56회였다. 이 기록은 자동 진행 증거이며 전체 학습이나 본 평가의 완료를 뜻하지 않는다.

v2는 여덟 번째 문제까지 공식 채점·수집·정리를 완료했다. 사용자의 `high` 변경 요청에 따라 여덟 번째 문제의 `CLEANED` 이벤트 70과 이후 문제의 준비 이력이 없음을 확인한 시점에 관리자만 멈췄다. [중단 영수증](../artifacts/skhynix_v1/architecture_execution_001/reasoning-high-stop-completion-001.json)은 활성 native worker 중단 0건을 기록한다. 원래 설정·cohort·결과는 보존하고, [변경 경계](../artifacts/skhynix_v1/architecture_execution_001/reasoning-effort-transition-001.json)가 1~8번 `ultra`와 9~24번 `high`를 연결한다. 원래 공개 경험은 새 learning-v3 authority에 [첫 7개](../artifacts/skhynix_v1/architecture_execution_001/learning-high-migration-completion-001.json)와 [마지막 1개](../artifacts/skhynix_v1/architecture_execution_001/learning-high-migration-completion-002.json)로 나누어 재수집했다. 새 풀이·공식 재채점은 0회다. 16:44 KST에 [v3 실행 영수증](../artifacts/skhynix_v1/architecture_execution_001/processes/20260914T074425.8154580Z.launch.json)을 남기고 프로세스 `37908`으로 전체 실행을 재개했다. [첫 high 실행 확인](../artifacts/skhynix_v1/architecture_execution_001/native-high-activation-001.json)에는 실제 설정·native 실행 영수증과 진행 중 broker 요청 21회가 연결된다.

비교 설계는 [PDF 구조 OFF/ON 설정](SKHYNIX_PDF_ARCHITECTURE_COMPARISON.md)을 따른다. 평가 대상은 Verified 전체 500문제, 두 조건에서 각 한 번씩 총 1,000회 풀이이며, 평가 결과로 교훈이나 검색 규칙을 조정하지 않는다.

- 평가와 ID·문제 설명 해시가 겹치지 않는 학습 후보에서 저장소별 PR 생성 시각이 가장 이른 두 문제를 선택해 **24개 학습 출처**를 등록했다. PR 생성 시각은 커밋 조상 관계의 증명이 아니다.
- 학습 24개와 평가 500개, 총 **524개** 공식 실행 이미지의 digest를 확보했다. 최초 조회의 HTTP 429 오류 35건은 속도를 낮춰 재확인했으며 원래 응답 기록을 보존했다.
- 실제 로컬 Codex CLI 0.153.4가 ChatGPT 로그인으로 `gpt-6-astra`를 사용한다. 초기 연결 검사와 학습 1~8번은 `ultra`이며, 위의 사용자 요청 변경 경계 이후에는 `high`를 사용한다. 별도 모델 API 클라이언트는 사용하지 않는다.
- native 실행에서는 별도 셸·브라우저·앱·플러그인·하위 에이전트·호스트 메모리 도구를 끄고, 해당 문제의 고정 broker에 연결된 MCP 도구만 제공한다. 실제 thread ID와 전달 prompt의 hash를 입장 기록에 연결한다.
- 문맥 상한 196,608 UTF-8 바이트는 **새 worker에게 전달하는 사용자 prompt 전체**에 적용하며 공통 지시문도 포함한다. Codex 내부 지시문·추론·같은 worker 안에서 누적되는 전체 대화에 대한 엄격한 바이트 상한은 아니다. 실제 Codex 토큰 사용량은 별도로 기록한다.
- subgoal이 바뀌어도 전체 120회 요청·1,200초 예산을 유지한다. 다른 조건의 이력과 기존 worker의 재진입을 거부한다. 공식 채점은 제출한 패치를 고정한 후 관리자만 실행한다.

현재 코드 검증은 각 범위별로 다음과 같다. 범위가 겹치므로 합산한 고유 테스트 수로 표현하지 않는다.

| 범위 | 결과 |
| --- | --- |
| 실제 broker와 문맥 기반 | 103개 통과 |
| 공개 dataset·실행 환경 및 기존 환경 검사 | 55개 통과 |
| native MCP 전달과 실행 관리자 | 최종 33개 통과 |
| Git checkout 원본 검증 | 49개 통과 |
| L1/L2/L3 adapter와 기존 memory/runtime/procedure/broker 검사 | 282개 통과 |
| 후속 전체 실행기·진행 집계·native publisher | [high 전환 검사 95개 통과](../artifacts/skhynix_v1/architecture_execution_001/pipeline-v3-unit-validation.json), [실제 모듈 101개·변경 경계·공식 loader 검사 통과](../artifacts/skhynix_v1/architecture_execution_001/pipeline-v3-final-import-smoke.json) |
| 후속 cohort·정리·실행기 호환성 | [high 전환 검사 193개 통과](../artifacts/skhynix_v1/architecture_execution_001/cohort-high-unit-validation.json); 앞 행과 일부 범위가 겹침 |

학습은 먼저 빈 bank에서 실제 문제를 풀어 공개 실행 기록을 만들고, Gate A 경험과 저장소 관계를 수집한다. 스킬은 서로 다른 문제·합성 소유자의 실제 실패→수정→동일 공개 테스트 통과 증거를 확인한 후 Gate B로 승격한다. 단순 종료 코드 0이나 사후 성공 선언을 검증으로 사용하지 않는다. 평가에 사용하는 bank는 이 과정을 마친 뒤 고정하며, 평가 중 기록은 별도 보관한다.

실행 준비 중 확인한 문제와 처리:

| 문제 | 처리 상태 | 풀이·해결률 영향 |
| --- | --- | --- |
| Windows 명령줄 길이 때문에 큰 편집 JSON을 전달할 수 없음 | bounded stdin 전송으로 수정·검증 | 솔버 시작 전 수정 |
| 제출 뒤 native 이벤트 오류를 정상 종료처럼 취급할 수 있음 | 제출 여부와 무관하게 전달 감사 확인 | 솔버 시작 전 수정 |
| 과거 채점기 사전 검사와 새 실행 소스의 호출 바인딩이 다름 | 새 소스에 맞춰 공식 loader 사전 검사 재실행·통과 | 솔버·채점 실행 전 확인 |
| Astropy 6938의 정상적인 `eol=crlf` 변환을 기존 checkout 검사기가 거부 | 정확한 Git 변환을 인정하도록 수정, 실제 Astropy 환경 준비 통과 | 환경 준비 오류이며 풀이 실패로 계산하지 않음 |
| MCP의 `auto` 설정이 쓰기 가능한 혼합 도구에 승인을 요구 | `action` 하나에만 `approve` 지정, 실제 새 세션 도구 호출 통과 | 최초 SymPy 시도는 broker 요청 0회·패치 0바이트·채점 0회로 연결 실패 기록에 격리 |
| MCP 내부 manager 오류·외부 launcher 실패가 재시작 또는 직접 채점에서 누락될 수 있음 | 실패 기록 영속화, 제출·재시작·채점의 모든 경로에서 실행 감사 검증 | 수정 전에는 본 평가를 시작하지 않음 |

도구 연결 확인 세션 `01a09e43-41cb-7d22-a02c-a21cfc82c470`은 synthetic `info` 1회 호출로 `MCP_TRANSPORT_READY`를 실제로 받았다. 이는 문제 풀이 점수가 아니다. 초기 실패 기록은 [commissioning-exclusion-001.json](../artifacts/skhynix_v1/architecture_execution_001/commissioning-exclusion-001.json)에 보존했다. 초기 코드·설정·실패한 실행과 준비만 완료한 checkout은 수정하거나 삭제하지 않았다.

학습·평가 수치와 실제 결과는 실행 기록이 생기는 대로 이 문서에 추가한다. 현재 문서의 테스트 통과 수는 소프트웨어 검증 결과이며 벤치마크 해결 건수가 아니다.

전환 전 `ultra`의 초기 추정은 [이전 시간 추정 근거](../artifacts/skhynix_v1/architecture_execution_001/runtime-estimate-ultra-001.json)에 보존했다. 준비 오류 복구가 개입하지 않은 학습 6·7번의 준비 시작부터 다음 문제 준비 시작까지 각각 17분 43초와 10분 16초, 평균 약 14분이었다. 이 속도로 순차 실행 1,000회를 단순 환산한 9.7일은 당시의 추정이며, 현재 `high`의 추정은 문서 상단과 새 근거 파일을 따른다.

현재 전체 실행 설정은 [architecture_001_pipeline_v3.json](../configs/skhynix_v1/architecture_001_pipeline_v3.json)에 고정했다. 이전 v2 설정·마지막 이벤트와 effort 변경 경계를 명시적으로 연결한다. 원래 솔버 코드·학습 대상·예산·모델·학습 메모리 출처를 유지하며, 새 [실행 설정 v6](../configs/skhynix_v1/architecture_001_training_execution_v6.json)의 `high`를 아직 시작하지 않은 작업에 적용한다. 별도 모델 API 클라이언트 호출 없이 학습 24개 → 공개 학습 기록만 받는 새 reflection 세션 → 실제 Gate B 검증과 bank 고정 → Verified 500문제 × 두 조건의 공식 채점 순서로 진행한다. 검증된 L3 스킬 등 필수 계층이 채워지지 않으면 `TRAINING_COMPLETE_NOT_EVALUATION_READY`를 남기며 전체 구조 평가 성공으로 표시하지 않는다.

후속 실행기는 보조 모듈 import 후 검색 경로를 복원하고, 지연 import하는 환경·채점기까지 정확한 source-v4 경로인지 확인한다. 완료·정리된 작업의 검증 결과는 프로세스 내부에서만 재사용하며 파일·디렉터리·이벤트 변경 시 무효화한다. 현재 문제와 전체 종료 시점은 원본 증거를 모두 검증한다. 진행 집계는 방금 생성한 snapshot을 직접 참조해, 과거 snapshot 전체를 매번 해시하는 중복 작업을 제거했다.

저장소 위치에서 다음 명령으로 백그라운드 프로세스와 공식 결과 집계를 조회할 수 있다. `ExecutionPolicy Bypass`는 이 PowerShell 프로세스에만 적용하며 컴퓨터의 기본 실행 정책을 변경하지 않는다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-SkhynixArchitecturePipeline.ps1 -Mode Status
```

동일 스크립트의 `-Mode Start`는 고정된 파이프라인을 숨겨진 WSL 프로세스로 실행한다. 중복 시작은 잠금과 PID·시작 시각으로 차단한다. 프로세스 생성 여부가 불명확한 이전 intent가 있으면 새 프로세스를 자동 생성하지 않는다. 실행·중단 원인은 pipeline 이벤트와 `artifacts/skhynix_v1/architecture_execution_001/processes`의 로그에 남는다. 컴퓨터와 WSL이 계속 실행되어야 백그라운드 작업이 진행된다.
