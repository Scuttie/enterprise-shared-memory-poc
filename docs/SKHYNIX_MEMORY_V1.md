# SK hynix PDF 기반 메모리 실험 구현

`LLM_Agentic_Memory_SKhynix_v1.pdf` (2026-09-07, 47쪽)의 42–46쪽을
기존 TriMem 실행기에 연결한 **로컬 실험용 구현**이다. PDF SHA-256:
`48cf59041ca5cedce430cc3237c418e03c2955948f1af0ed26002d8ab48f941d`.

기존 M2의 개인 episodic → 개인 semantic → 조직 semantic 순서와 달리,
새 컨트롤러는 **검증된 스킬 → 저장소 semantic KG → 개인 episodic** 순서로
조회한다. 기존 실행 루프, 도구, 모델·grader 경계, 증거 원장과 체크포인트를
재사용한다. 기존 동결 실험의 M0/M1/M2 정의와 기록은 수정하지 않는다.

## PDF와 구현의 대응

| PDF | 구현 | 동작 |
| --- | --- | --- |
| 32, 42쪽: L0 subgoal working memory | `subgoal_context.py`, `SkhynixAgentRuntime` | 활성 하위 작업의 관측만 상세 문맥에 넣고, 완료된 작업은 실제 완료 증거·테스트 결과·artifact hash가 있는 요약으로 보존한다. |
| 42–44쪽: L1 개인 episodic, Gate A | `EpisodeEvidence`, `GateAExperienceLifecycle` | 성공·실패를 모두 개인 소유로 저장한다. 같은 작업의 재시작은 중복 경험을 만들지 않는다. |
| 42–44쪽: L2 저장소 semantic KG | `RepositoryKnowledge`, `link_repository_knowledge` | 저장소·revision·언어를 먼저 제한하고 명시적 지식 관계에 기존 PPR 검색을 적용한다. |
| 42–45쪽: L3 조직 Skill Library | `ProcedureTemplate`, `Skill` | subgoal signature, parameters, preconditions, ordered steps, verification command를 저장한다. 공유 뷰에는 개인 증거와 원래 parameter 값을 넣지 않는다. |
| 43–45쪽: 오프라인 Gate B | `promote_skill` | 서로 다른 사용자 2명, 작업 2개, verifier artifact 2개 이상을 요구한다. 각 증거는 동일한 template hash 및 실제 parameter binding·단계·검증 명령과 일치해야 한다. |
| 41, 44, 46쪽: stale memory 무효화 | `invalidate_skill`, `invalidate_repository` | 명시적 폐기와 revision 변경으로 조회를 차단한다. 이미 주입된 스킬이 폐기되면 기존 문맥을 재사용하지 않고 새 작업 시작을 요구한다. |
| 46쪽: 정책 학습은 후속 단계 | 결정적 조회·승격 규칙 | 새 경로의 정책을 학습된 정책이라고 표시하지 않는다. 기존 DQN은 보존된다. |

## 실행과 평가

저장소 루트에서 실행한다. Python 환경에 프로젝트와 개발 의존성이 설치되어
있어야 한다. 기존 작업 환경에서는 아래 명령을 검증했다.

```powershell
Set-Location 'C:\Users\jewon\esm-r23-d115-writer'
python -m pytest tests/unit/test_trimem_skill_memory.py tests/unit/test_trimem_skill_runtime.py tests/unit/test_trimem_subgoal_context.py tests/unit/test_trimem_skhynix_evaluate.py
python scripts/trimem_skhynix_evaluate.py --output artifacts/skhynix_v1/my_new_evaluation
python scripts/trimem_freeze.py --check
```

평가 출력은 **새 디렉터리**여야 한다. `report.json`, 실행별 증거 원장,
체크포인트 및 로컬 SQLite 상태가 생성된다. SQLite·원시 실행 자료는 로컬에
남기고, 검토용 결과는 [평가 보고서](../reports/SKHYNIX_MEMORY_V1_EVALUATION.md)에
정리했다. API 호출, 모델 다운로드, Docker, 외부 쓰기는 필요하지 않다.

비교 평가는 기존 `TriMemAgentRuntime`, `ReplayModelGateway`,
`ReplayGraderGateway`를 사용한다. 6개 시나리오 × 2개 경로에서 동일한
고정 응답과 동일한 도구 동작을 실행한다. 실제 Python 코드를 실행해
대소문자 확장자 처리와 잘못된 확장자 거부를 검증한다. 별도의 2-subgoal
실행으로 문맥 압축, Gate A 저장 및 재시작 무중복 처리를 확인한다.

이 평가는 **연결과 메모리 동작 검증**이다. 고정 응답이 모든 fixture를
수정하므로, 통과 개수는 모델 해결률이나 메모리 성능 향상의 추정치가 아니다.
SWE-bench 공식 채점이나 HELDOUT 평가도 아니다.

## 코드에서 연결하기

```python
from enterprise_memory.trimem.skill_memory import SkillMemoryStore
from enterprise_memory.trimem.skill_runtime import (
    GateAExperienceLifecycle, SkillFirstMemoryController, SkhynixAgentRuntime,
)

store = SkillMemoryStore("local_memory.sqlite3")
controller = SkillFirstMemoryController(
    store, task_id=task.task_id, language="python",
    parameters={"extension": ".yaml"},  # 선택: 스킬에 선언된 parameter와 정확히 일치
)
runtime = SkhynixAgentRuntime(
    runtime_lock=runtime_lock,
    model_gateway=model_gateway,
    grader_gateway=grader_gateway,
    memory_controller=controller,
    evidence=evidence_ledger,
    checkpoint_store=checkpoint_store,
    lifecycle=GateAExperienceLifecycle(store),
)
result = runtime.run(task, arm="M2")
store.close()
```

예시의 `arm="M2"`는 공통 실행기의 허용된 전달 값이다. 실제 새 경로의 식별은
컨트롤러·runtime configuration hash와 평가의 `SKHYNIX_SKILL_FIRST` 라벨로
구분된다. 이 코드를 기존 동결 M2 benchmark factory에 자동 등록하지 않는다.

Gate A가 저장한 일반 경험은 자동으로 공유 스킬이 되지 않는다. 오프라인
작업이 `ProcedureTemplate`를 만들고, 신뢰할 수 있는 검증기가 실제 실행한
동일 절차의 parameter binding, actions, verification command, artifact hash를
`EpisodeEvidence`에 기록한 다음 `store.promote_skill(...)`을 호출한다.
검증 명령은 데이터로 취급하며 라이브러리가 자동 실행하지 않는다. 조회된
전제조건은 에이전트가 현재 코드에서 확인해야 한다.

## 적용 범위와 후속 실제 평가

- SQLite는 로컬 실험의 기준 저장소다. 기존 production PostgreSQL/Qdrant,
  서비스 인증 및 조직별 접근 제어에 연결한 배포 구현은 아직 아니다.
  호출자는 인증된 scope와 신뢰할 수 있는 verifier label을 전달해야 한다.
- 개인 raw trajectory는 기존 실행 원장/체크포인트에 유지한다.
  `TaskSubgoalTraceStore.retrieve_trace(task_id=..., subgoal_id=...)`로 복구할
  수 있다. 이 API는 아직 모델이 직접 호출하는 새 native tool로 노출하지 않았다.
- 스킬의 원본 개인 증거 연결은 SQLite 내부에 유지한다. 일반 Gate A는
  patch/public-evidence의 hash를 통해 실행 원장을 참조한다. 조직 전체에
  원본 코드 artifact를 배포하는 기능은 제공하지 않는다.
- snapshot에서 저장소 revision과 언어를 검사하고 명시적 폐기를 지원한다.
  Git/CI 변경 감지 서비스가 자동으로 폐기를 호출하는 배포 연결은 후속 작업이다.
- 조회 예산은 기본 작업당 최대 3회, 총 12,000 UTF-8 bytes이며 하위 작업마다
  최대 하나의 메모리를 넣는다. 완료 작업 요약과 현재 관측의 통합 문맥 예산은
  기본 48,000 bytes이다. 현재 구현으로 token 절감률을 주장하지 않는다.
- 개인 shortcuts·팀 playbooks를 위한 별도 L3 scope, 온라인 SLM,
  자동 template 생성 및 학습된 승격/조회 정책은 아직 구현하지 않았다.

최초 GitHub DEV 진단에서는 C0=1/12, C1=0/12, C2=1/12였으며 메모리 강제
주입의 성능 개선은 확인되지 않았다. 이후 로컬 WSL 실행기에 공식 harness와
대상 컨테이너를 연결해 [실제 DEV 비교 001](../reports/SKHYNIX_DEV_SOLVE_RATE.md)을
36/36회 완료했다. 기존 진단의 실행 요청과 결과는 재사용하지 않았다.

001의 하위 작업 제한을 조사한 뒤 `ExplorationTriMemAgentRuntime`과
`ExplorationSkhynixAgentRuntime`을 추가했다. 공통 `ExplorationPolicy`는 실제
호출 기록으로 남은 작업·하위 작업 예산을 계산하고, 마지막 4회에 수정·검증·완료를
계획하도록 안내한다. 같은 요청과 성공한 관측 결과가 반복되면 다른 접근을
권하며, 도구 실행을 차단하거나 저장된 응답으로 대체하지 않는다. 변경·검증
명령 이후에는 반복 집계를 초기화한다. 정책과 안내 문맥은 체크포인트 및
실제 모델 요청 해시에 연결된다.

`scripts/trimem_skhynix_exploration.py`의 새 실험 002는 하위 작업당 24단계,
전체 48회 solve 호출을 허용하고 기존 적응형 연장은 비활성화한다. 세 조건에
같은 탐색 정책을 적용하며 모델, 대상, 과거 PR bank, 토큰 한도는 001과 같다.
실제 호출·공식 채점·비용과 001의 동일 대상 비교는
[탐색 예산 변경 재평가](../reports/SKHYNIX_EXPLORATION_EVALUATION.md)에 기록한다.
계획은 새 출력·작업 디렉터리에 동결하며, 실행 중 비용 상한을 바꾸거나 기존
001 실행물을 덮어쓰지 않는다.

이 실제 비교의 L1 경험과 L3 검증 스킬은 비어 있고 L2 KG 간선도 없다.
과거 PR을 L2 저장소 지식으로 검색하는 초기 상태를 평가한다. L3 효과를
평가하려면 대상과 분리된 CI/수정 증거로 검증 스킬 bank를 먼저 만들어야 한다.
문맥 압축과 조회 변경을 함께 적용한 결과를 조회 순서만의 효과로 해석하지 않는다.
