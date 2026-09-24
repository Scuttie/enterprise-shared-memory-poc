# Codex Astra로 실행한 메모리 비교 파일럿

**공식 채점 3/3회 완료. SymPy 한 문제를 세 조건 모두 해결했다.**

별도 모델 API 클라이언트 없이 새 문맥의 Codex 에이전트가 수정하고, 기존 공식 grader가 제출 패치를 채점했다. 이번 결과는 실행 연결의 작동 확인이며 메모리의 해결률 상승을 보여준 결과는 아니다.

| 조건 | 공식 해결 | 도구 요청 | 풀이 시간¹ | 메모리 조회 / 실제 주입 | 주입 bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 메모리 없음 | 1/1 | 15 | 138.9초 | 1 / 0 | 0 |
| 기존 M2 | 1/1 | 14 | 136.0초 | 1 / 1 | 5,806 |
| PDF 기반 조회 | 1/1 | 16 | 144.0초 | 1 / 0 | 0 |

¹첫 도구 요청부터 제출까지의 시간. 에이전트 생성·환경 준비·공식 채점 시간은 제외했다. 병렬 실행한 단일 표본이므로 속도 우위를 주장하지 않는다.

세 조건 모두 싱글턴 tuple 직렬화 문제를 수정하고 관련 공개 lambdify 테스트에서 **64개 통과·54개 건너뜀**을 확인했다. 문제 수정 전 공개 assertion 실패도 기록했다. 공식 채점은 제출 후 별도 컨테이너에서 시행했다. 에이전트 완료 선언이나 공개 테스트 통과만으로 해결 판정을 대신하지 않았다.

기존 M2는 과거 PR 지식 1개(5,806 bytes)를 실제로 받았다. PDF 기반 조회는 실제 `SkillFirstMemoryController`를 호출했지만, 저장소 지식 후보 1개 중 적합 후보가 0개여서 주입하지 않았다. SKILL과 EPISODIC 후보는 각각 0개였다. 세부 탈락 사유는 해당 controller가 기록하지 않아 더 세분하지 않았다. **PDF 조건의 성공을 메모리 도움으로 해석할 수 없다.**

## 무엇을 구현했나

- 실제 메모리 조회와 복구: 기존 M2 controller와 SK hynix controller를 각각 호출하며 scope·내용·조회 예산을 검사한다.
- 공개 도구 중계: 검색, 읽기, 수정, Docker 명령 실행과 제출을 기록한다. 요청마다 남은 시간과 횟수를 반환한다.
- 제출 및 채점: 패치와 요청 기록을 고정한 후 공식 grader를 한 번 실행한다. 제출 후 수정과 중복 채점은 거부한다.
- 결과 집계: 세 조건이 모두 공식 채점됐을 때만 같은 문제의 비교를 만든다.

코드와 실행법: [SKHYNIX_CODEX_PILOT.md](../docs/SKHYNIX_CODEX_PILOT.md).

## 실험 조건

- 대상: `swebench_verified--sympy__sympy-23262`. 이전 진단에서도 사용한 DEV 문제다.
- 모델 요청: `gpt-6-astra`. 세 에이전트 모두 같은 부모의 reasoning 설정을 상속했다. 내부 날짜별 모델 snapshot은 별도로 확인하지 못했다.
- 실행: 문제×조건마다 새 서브에이전트, `fork_turns="none"`. 기존 대화와 다른 풀이를 전달하지 않았다.
- 예산: 조건마다 도구 요청 120회, 첫 요청부터 20분. 하위 작업별 제한은 없다. 실제 요청 수는 합계 45회다.
- 메모리: 실제 controller별 task 예산 3개·12,000 bytes. 같은 과거 PR bank를 사용했다. 초기 L1 경험·L3 검증 스킬·L2 KG 간선은 0개다.
- 문맥: Codex 기본 문맥 관리. 기존 `SkhynixAgentRuntime`의 L0 문맥 투영을 재현한 실험은 아니다.
- 학습: 실행 사이 Gate A/B 저장·승격과 스킬 누적은 하지 않았다.
- 별도 모델 API 호출: **0회**. Codex 자체 사용량은 발생하며 정확한 토큰·비용을 관측하지 못해 `null`로 기록했다.

각 도구 명령은 별도 초기 checkout을 고정 컨테이너에서 실행했다. 컨테이너는 비관리자·네트워크 차단이며 문제 풀이에 공식 정답 패치나 grader 전용 테스트를 제공하지 않는다. 그러나 새 Codex 스레드는 호스트 도구를 상속한다. 따라서 중계기 외 접근 금지는 **실험 지침과 에이전트 자기 확인**으로 적용됐고, 호스트 전체에 대한 강제 OS 격리 증명은 아니다. 기록된 요청과 컨테이너 경계는 감사했지만 기록되지 않은 호스트 활동의 부재까지 단정하지 않는다.

이전 mini 모델의 SymPy 결과는 세 조건 모두 실패였고 이번에는 모두 성공했다. 모델·실행기·문맥·공개 테스트 안내가 함께 바뀌었으므로 이 차이를 메모리의 인과 효과나 모델만의 효과로 계산하지 않는다. 문제 1개당 실행 1회이며 무작위 표본·독립 heldout·반복 실행이 아니므로 일반적인 100% 해결률을 주장하지 않는다.

## 사용자가 다음에 할 일

이번 연결 확인에는 추가 API 키 설정이나 수동 세션 생성이 필요하지 않았다. 같은 대화에서 실험을 관리하면 된다. 현재 CLI는 이 SymPy 파일럿에 고정돼 있으므로, 다음 단계에서는 대상 선택 기능을 먼저 확장한다.

PDF 구조의 효과를 확인하려면 먼저 **학습용 문제와 평가용 문제를 분리하고, 실제 검증 증거가 있는 스킬 bank를 만든다.** 그 bank를 동결한 뒤 동일한 Astra 모델과 도구 환경에서 메모리 없음·기존 조회·PDF 조회를 여러 평가 문제에 비교한다. 평가 문제의 정답이나 실행 결과를 학습 bank에 넣지 않는다.

사용자는 비교할 저장소·문제 범위와 실행 규모를 정해 전달하면 된다. 예를 들어 “이 방식으로 대상 선택을 확장하고, 학습·평가 문제를 분리한 뒤 메모리 bank를 만들고 평가해줘”라고 요청하면 된다. 새 에이전트 생성·작업공간 준비·메모리 연결·채점·기록은 관리자가 처리한다.

## 검증과 증거

메모리 연결 테스트 30개와 중계기·예산·제출 검증 테스트 32개, 총 **62개 테스트 PASS**. [통합 실행 기록](../artifacts/skhynix_v1/codex_validation.xml)과 [최종 중계기 검사](../artifacts/skhynix_v1/codex_broker_validation.xml)를 보존했다. 실제 캐시된 MiniLM 검색과 공개 Python 테스트 준비 검사도 통과했다.

[실행 계획](../artifacts/skhynix_v1/codex_001/plan.json) · [최종 집계](../artifacts/skhynix_v1/codex_001/report.json) · [에이전트 실행 기록](../artifacts/skhynix_v1/codex_001/launch.json) · [독립 감사](../artifacts/skhynix_v1/codex_001/audit.json) · [공개 테스트 준비](../artifacts/skhynix_v1/codex_001/public-python-readiness.json) · [실제 M2 검색 준비](../artifacts/skhynix_v1/codex_001/memory-preflight.json) · [증거 파일 해시](../artifacts/skhynix_v1/codex_001/public-artifact-manifest.json).

| 조건 | 패치 SHA-256 | 공식 결과 |
| --- | --- | --- |
| 메모리 없음 | `d4e3d524ea43b1c322cbf5755fb538c3c61319569f368aa55e12a17c66675be4` | [public-result.json](../artifacts/skhynix_v1/codex_001/cells/A/public-result.json) |
| 기존 M2 | `0b2d9bf34331a48dc19ca52655689df30602ad7ef84803621faba6b1479bb70d` | [public-result.json](../artifacts/skhynix_v1/codex_001/cells/B/public-result.json) |
| PDF 기반 조회 | `99587ce7a319a1238a4f56db2d4a5b1f514e460cbe07480271ef8bfddb873441` | [public-result.json](../artifacts/skhynix_v1/codex_001/cells/C/public-result.json) |

실행 계획 canonical SHA-256: `986574b19caf981da361ea7451763392b35dab2768a40f8c7b9f9d6c1472b9e3`.
실행 소스 324개 파일의 해시를 계획에 기록했다. 원본 실행 위치: `/home/trimem-runner/skhynix-codex-001`.

이전 [001 보고서](SKHYNIX_DEV_SOLVE_RATE.md)와 [002 보고서](SKHYNIX_EXPLORATION_EVALUATION.md)는 별도 실험으로 보존했다.
