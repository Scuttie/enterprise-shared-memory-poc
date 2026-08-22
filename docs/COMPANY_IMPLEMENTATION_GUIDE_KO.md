# Enterprise Shared Memory v0.3
## 회사 도입·구현 안내서

> 이 문서는 **이 저장소를 처음 전달받은 회사 개발자·플랫폼 엔지니어·보안 담당자**가
> 무엇을 받아야 하고, 어떤 순서로 확인하고, 기존 코딩 AI 서비스에 어떻게 연결해야 하는지를 설명합니다.
> 연구 실험의 긴 이력을 읽지 않아도 도입할 수 있도록 작성했습니다.

---

## 0. 먼저 알아둘 상태

이 저장소는 다음 상태를 목표로 합니다.

```text
회사 인수·검토용 코드와 오프라인 데모: 준비됨
회사 스테이징 환경에서의 인증: 아직 필요
프로덕션 운영 인증: 아직 아님
공유 메모리가 평균 코딩 성능을 높인다는 주장: 하지 않음
```

이 시스템의 현재 가치는 다음에 있습니다.

- 사용자별 개인 기억과 조직 공유 기억을 분리합니다.
- 검증된 경험만 조직 기억 후보로 저장합니다.
- 잘못된 범위, 오래된 버전, 격리된 기억을 모델에 보여주지 않습니다.
- 어떤 기억을 왜 사용하거나 거부했는지 기록합니다.
- 반복적으로 문제를 일으킨 기억을 격리합니다.
- 기존 코딩 에이전트에 HTTP 또는 MCP로 연결할 수 있습니다.

**중요:** 이 시스템은 회사의 코딩 모델과 코드 실행 환경을 대체하지 않습니다. 회사가 이미 운영 중인
로컬 모델·Claude Code형 하네스·샌드박스는 그대로 두고, 이 서비스가 “기억 검색과 통제” 기능만 제공합니다.

---

# 1. `make test`, `make demo`는 누가 실행해야 하나

## 답: 공급자와 회사가 둘 다 실행합니다

### 1단계 — 회사에 넘기기 전

이 저장소를 준비한 쪽의 코딩 에이전트가 **먼저 새 clone에서** 아래 명령을 실행하고, 실패하면 고친 뒤 전달해야 합니다.

```bash
make bootstrap
make test
make demo
make docs-check
make package
make release-check
```

회사가 처음 저장소를 열었을 때 테스트 실패를 발견하게 해서는 안 됩니다.

코딩 에이전트가 회사에 함께 남겨야 하는 결과:

- 실행한 정확한 commit SHA
- 각 명령의 성공·실패
- `DEMO_PASS: true` 출력
- 생성된 wheel/sdist 위치와 해시
- `COMPANY_HANDOFF_MANIFEST.json` 검사 결과
- GitHub Actions 상태
- 아직 필요한 회사 입력값

### 2단계 — 회사가 전달받은 뒤

회사 담당자는 **동일한 명령을 다시 실행**해 전달물이 자기 환경에서도 재현되는지 확인합니다.

이중 실행의 의미는 다릅니다.

| 실행 주체 | 목적 |
|---|---|
| 공급자/코딩 에이전트 | 깨진 전달물을 회사에 넘기지 않기 위한 출고 검사 |
| 회사 엔지니어 | 전달된 commit이 회사 환경에서도 동작하는지 확인하는 인수 검사 |

### 각 명령이 실제로 확인하는 범위

| 명령 | 확인 내용 | 확인하지 않는 것 |
|---|---|---|
| `make test` | 단위 테스트, 회사 데모 통합 테스트, 문서 상태 일치 | 회사 실제 IdP·모델·클러스터의 운영 성능 |
| `make demo` | 외부 키 없이 기억 생성→승격→검색→판정→결과 기록→격리 흐름 | 실제 회사 모델의 코딩 성능 |
| `make docs-check` | README·상태 파일·문서 내용의 불일치 | 서비스 부하·보안 침투 테스트 |
| `make package` | Python wheel과 sdist 빌드 | 컨테이너 운영 인증 |
| `make release-check` | 위 검사와 handoff manifest 일치 | 회사 스테이징 승인 |

`make test`와 `make demo`가 통과해도 “프로덕션 준비 완료”라는 뜻은 아닙니다.

---

# 2. 회사가 전달받아야 하는 것

회사는 단순히 GitHub 주소 하나만 받아서는 안 됩니다. 아래 묶음을 받아야 합니다.

## 2.1 필수 전달 정보

```text
Repository URL
전달 브랜치
정확한 commit SHA
패키지 버전
마이그레이션 head
컨테이너 또는 wheel 해시
COMPANY_HANDOFF_MANIFEST.json
GitHub Actions 결과
알려진 제한사항
담당자 및 장애 연락처
```

정확한 commit은 메일에 적힌 임의 문자열보다 `COMPANY_HANDOFF_MANIFEST.json`을 기준으로 확인하는 것이 좋습니다.

## 2.2 GitHub 안에서 먼저 읽을 문서

```text
README.md
docs/COMPANY_HANDOFF.md
docs/COMPANY_INTEGRATION_GUIDE.md
docs/API_AND_MCP.md
docs/MEMORY_POLICY.md
docs/SECURITY_AND_PRIVACY.md
docs/OPERATIONS_RUNBOOK.md
docs/COMPANY_ACCEPTANCE_CHECKLIST.md
configs/company.example.yaml
configs/memory_policy.example.yaml
examples/company_harness/
COMPANY_HANDOFF_MANIFEST.json
```

## 2.3 한국어 매뉴얼의 권장 위치

이 문서의 Markdown 원본은 다음 경로로 GitHub에 커밋하는 것을 권장합니다.

```text
docs/COMPANY_IMPLEMENTATION_GUIDE_KO.md
```

Word 파일은 버전 관리의 기준 문서로 쓰기보다 다음 중 하나로 전달하는 편이 낫습니다.

```text
GitHub Release 첨부파일
회사 전달 메일 첨부파일
사내 문서 시스템 업로드
```

**Markdown이 기준 원본이고 Word는 배포용 사본**으로 두는 것이 변경 이력을 관리하기 쉽습니다.

---

# 3. 현재 GitHub에 무엇이 있고, 무엇이 아직 없는가

현재 브랜치에는 이미 다음 회사용 영문 문서가 있습니다.

- `docs/COMPANY_HANDOFF.md`
- `docs/COMPANY_INTEGRATION_GUIDE.md`
- `docs/COMPANY_ACCEPTANCE_CHECKLIST.md`
- `docs/API_AND_MCP.md`
- `examples/company_harness/`
- `Makefile`

반면 ChatGPT가 `/mnt/data/...`에 생성한 한국어 Markdown·Word 파일은 **자동으로 GitHub에 올라가지 않습니다.**
코딩 에이전트가 파일을 저장소의 `docs/`에 복사하고 commit/push해야 회사가 GitHub에서 볼 수 있습니다.

회사 전달 전에는 다음 세 상태가 반드시 같은 말을 해야 합니다.

```text
docs/STATUS.yaml
README.md
PR 본문 또는 handoff manifest
```

셋 중 하나라도 `IN_PROGRESS`, 다른 하나가 `COMPANY-HANDOFF-READY`라고 하면 전달을 중단하고 먼저 동기화합니다.

---

# 4. 회사가 이 시스템을 어디에 붙이는가

가장 쉬운 구조는 다음입니다.

```text
회사 개발자
   ↓
기존 코딩 에이전트 / Claude Code형 하네스
   ├─ 기존 사내 모델 호출
   ├─ 기존 코드 읽기·수정 도구
   ├─ 기존 샌드박스와 테스트
   └─ 새로 추가: 메모리 도구(MCP 또는 HTTP)
                  ↓
          Enterprise Shared Memory
                  ├─ PostgreSQL: 기억의 원본과 권한
                  ├─ Qdrant/Mem0: 검색용 색인
                  ├─ Router: 보여줄지 거부할지 판단
                  └─ Audit: 모든 결정과 결과 기록
```

회사의 GPU나 모델 서버를 이 저장소 안으로 옮길 필요는 없습니다.

이 시스템은 모델에게 다음 네 가지 도구를 제공합니다.

| 도구 | 쉬운 설명 |
|---|---|
| `memory_search` | 현재 문제와 관련 있어 보이는 기억의 제목·범위만 찾음 |
| `memory_browse` | 권한과 정책을 통과한 기억의 실제 실행 지침을 읽음 |
| `memory_report_outcome` | 기억을 사용한 뒤 성공·실패·무관 결과를 기록 |
| `memory_explain_decision` | 왜 기억을 보여주거나 거부했는지 확인 |

---

# 5. 가장 권장하는 연결 방식: MCP

회사가 Claude Code형 하네스를 사용한다면 **MCP 연결을 먼저 권장**합니다.

## 회사가 해야 할 일

1. 기존 하네스의 MCP 설정에 이 메모리 서버를 추가합니다.
2. 모델에게 `memory_search`, `memory_browse`, `memory_report_outcome` 도구를 노출합니다.
3. 사용자·조직·저장소 권한은 모델이 보내는 값이 아니라 서버가 인증 토큰에서 정하도록 합니다.
4. 첫 운영에서는 `shadow` 모드를 사용합니다.

## 로컬 MCP 서버 예시

```bash
python -m enterprise_memory.mcp.server
```

저장소 예제:

```text
examples/company_harness/mcp_stdio_config.json
examples/company_harness/mcp_http_config.json
examples/company_harness/tool_schema.json
```

## 에이전트가 따를 흐름

```text
1. 현재 작업과 오류를 파악
2. memory_search 호출
3. 메타데이터 후보 확인
4. 필요한 후보에 memory_browse 요청
5. 서버가 USE를 허용한 경우에만 실행 지침을 읽음
6. 기존 방식대로 코드 수정과 테스트
7. memory_report_outcome으로 결과 기록
```

---

# 6. HTTP로 연결하는 방법

자체 에이전트 서버가 MCP를 쓰지 않는다면 REST API를 사용합니다.

## 후보 검색

```bash
curl -X POST "$MEMORY_API/v1/experience-cards/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "loader crash after missing configuration key",
    "repository": "company/widgets",
    "subtask": "modification"
  }'
```

검색 응답은 기억의 전체 내용이 아니라 다음 메타데이터만 반환해야 합니다.

- 카드 ID
- 적용 범위
- 저장소·프레임워크
- 검증 상태
- 검색 점수
- 간단한 이유 태그

전체 지침은 별도의 browse 요청을 해야 하며, 이때 서버가 권한·버전·상태·Router 판단을 다시 확인합니다.

---

# 7. 15분 오프라인 인수 검사

## 7.1 권장 환경

- Linux 또는 WSL2
- Python 3.10 이상
- Git
- `make`
- 전체 서비스 확인 시 Docker와 Docker Compose

## 7.2 clone과 commit 고정

```bash
git clone https://github.com/Scuttie/enterprise-shared-memory-poc.git
cd enterprise-shared-memory-poc
git checkout <HANDOFF_BRANCH>
git checkout <HANDOFF_COMMIT>
```

`<HANDOFF_COMMIT>`은 `COMPANY_HANDOFF_MANIFEST.json`과 일치해야 합니다.

## 7.3 설치와 빠른 검사

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

make bootstrap
make test
make demo
```

성공 시 마지막에 다음 문구를 확인합니다.

```text
DEMO_PASS: true
```

## 7.4 패키지와 문서 검사

```bash
make docs-check
make package
make release-check
```

---

# 8. 오프라인 데모가 보여주는 것

`make demo`는 실제 회사 코드·모델 키 없이 다음 과정을 재현합니다.

1. Alice가 성공한 코딩 경험을 저장합니다.
2. 검토자가 해당 경험을 공유 가능한 상태로 승인합니다.
3. Bob의 새 작업에서 관련 기억을 검색합니다.
4. Router가 직접 적용 가능하다고 판단해 `USE`를 선택합니다.
5. 모델용 짧은 실행 지침이 만들어집니다.
6. 사용 결과가 감사 로그에 저장됩니다.
7. 비슷하지만 맞지 않는 기억은 `ABSTAIN`됩니다.
8. 반복적으로 해로운 기억은 `quarantined`됩니다.
9. Alice의 개인 기억은 Bob에게 노출되지 않습니다.

이 데모는 **배관과 통제의 동작**을 확인합니다. 실제 회사 모델의 성능 향상을 검증하지는 않습니다.

---

# 9. 회사가 준비해야 할 설정

`configs/company.example.yaml`을 복사해 실제 환경용 파일을 만듭니다.

```yaml
protocol: mcp                  # openai | anthropic | jsonrpc | mcp
model: <정확한-사내-서빙-모델-ID>
endpoint: <사내-엔드포인트>    # MCP stdio라면 생략 가능
repositories:
  - name: <org/repo>
    scope: shared
policy_mode: shadow
```

회사에서 반드시 결정해야 하는 값:

| 항목 | 회사가 정할 내용 |
|---|---|
| 모델 | 정확한 serving model ID와 revision |
| 하네스 | Claude Code, 사내 fork, 자체 agent 등의 정확한 버전 |
| 연결 | MCP / OpenAI-compatible / Anthropic / JSON-RPC |
| 인증 | OIDC issuer와 JWKS 주소 |
| 저장소 권한 | 조직·팀·repo·path별 접근 정책 |
| 샌드박스 | 코드 실행과 테스트를 담당하는 회사 시스템 |
| 비밀 관리 | API 키·DB 비밀번호를 넣을 secret manager |
| 보관 기간 | 기억·산출물·감사로그 보존 기간 |
| 검토자 | candidate 기억의 승격을 승인할 사람 |
| 중단 담당자 | 전체 memory 기능을 끌 권한을 가진 사람 |

시스템이 이 값을 추측하게 두지 않습니다.

---

# 10. 필요한 인프라

## 오프라인 데모

외부 인프라가 필요 없습니다.

## 회사 파일럿

최소한 다음이 필요합니다.

```text
PostgreSQL
Qdrant
Memory API
회사의 OIDC/JWKS
회사의 Secret Manager
기존 코딩 에이전트와 샌드박스
```

회사 모델 서버와 GPU는 기존 환경을 그대로 사용합니다.

예제 compose:

```bash
cp .env.example .env
cp configs/company.example.yaml configs/company.yaml
make up
make smoke
```

운영 데이터가 있는 환경에서 `make down`을 그대로 사용하지 마십시오. 예제 target은 volume을 제거할 수 있습니다.

---

# 11. 안전한 도입 순서

## 단계 0 — 공급자 출고 검사

코딩 에이전트가 fresh clone에서 전 테스트와 데모를 통과시킵니다.

## 단계 1 — 회사 오프라인 인수

회사 담당자가 동일 commit에서 `make test`, `make demo`, `make package`를 다시 실행합니다.

## 단계 2 — Shadow 운영

```text
MEMORY_POLICY_MODE=shadow
```

이 모드에서는 검색과 Router 판정만 기록하고 모델에는 아무 기억도 주입하지 않습니다.

확인할 것:

- 어떤 후보가 검색되는가
- USE와 ABSTAIN 비율
- private memory 노출이 0인가
- 버전이 틀린 기억이 거부되는가
- 검색·판정 지연

## 단계 3 — 검토된 기억만 제한적 사용

- 사람이 검토한 `promoted` 카드만 허용
- 내부 테스트 사용자·저장소만 허용
- 자동 승격은 끔
- 즉시 끌 수 있는 `off` 스위치 준비

## 단계 4 — 회사 스테이징 승인

`docs/COMPANY_ACCEPTANCE_CHECKLIST.md`를 회사 환경에서 모두 확인한 뒤에만 스테이징 인증을 부여합니다.

---

# 12. 어떤 경험을 기억으로 저장할 것인가

좋은 기억 후보:

- 실제 코드 변경이 테스트를 통과함
- 적용된 저장소와 버전이 분명함
- 실패 원인과 수정 작업이 구분됨
- 검증 방법이 기록됨
- 비밀·개인정보가 없음
- 다른 작업의 정답이나 hidden test가 없음

권장 상태 변화:

```text
candidate
→ source 검증
→ probation
→ 사람 검토
→ promoted
```

반복적으로 문제를 일으키면:

```text
quarantined
```

다음 상태는 모델에 노출되면 안 됩니다.

```text
deprecated
quarantined
deleted
expired
```

---

# 13. 개인 기억과 공유 기억

## 개인 기억

- 해당 사용자만 읽습니다.
- 같은 조직의 다른 사용자도 읽지 못합니다.
- 임시 작업 메모와 개인 경험을 저장합니다.

## 공유 기억

- 조직·팀·저장소·경로 권한으로 통제합니다.
- 반드시 검증과 리뷰를 통과한 `promoted` 상태여야 합니다.
- source와 provenance가 있어야 합니다.

다음 값은 항상 0이어야 합니다.

```text
cross-user private injection
wrong-tenant access
secret exposure
hidden-test exposure
quarantined memory injection
```

하나라도 0이 아니면 즉시 `MEMORY_POLICY_MODE=off`로 전환합니다.

---

# 14. 운영 중 봐야 할 지표

## 보안·격리

- 교차 사용자 개인 기억 노출
- 다른 조직 데이터 접근
- 비밀·개인정보 탐지
- 격리 기억 노출
- 잘못된 버전 기억 사용

## 사용 품질

- 검색 후보 수
- USE / ABSTAIN 비율
- 관련 없는 기억의 USE
- 유용한 기억의 잘못된 ABSTAIN
- 기억 사용 후 성공·실패·무관

## 비용·속도

- 검색 지연
- Router 판정 지연
- 주입 토큰 수
- 전체 작업 지연
- 모델 호출 비용

## 운영

- worker 실패
- outbox 적체
- Qdrant index drift
- audit chain 오류
- quarantine 증가율

---

# 15. 장애 대응

## 관련 기억이 검색되지 않음

확인 순서:

1. 조직·repository ID
2. path scope
3. `promoted` 상태
4. 유효기간
5. 현재 버전
6. Qdrant 색인
7. PostgreSQL 원본

검색 threshold부터 무작정 낮추지 않습니다.

## 관련 없는 기억이 자주 허용됨

1. `memory_explain_decision`에서 reason code 확인
2. 단순한 주제 유사성인지 확인
3. API·symbol·오류 서명이 직접 일치하는지 확인
4. `shadow`로 되돌림
5. 문제가 있는 카드를 quarantine

## 기억 사용 후 성능이 떨어짐

- target과 card ID를 audit에서 확인
- `MEMORY_LOSS` 기록
- 실제 source 작업이 코드에 채택됐는지 증거 확인
- 반복 손실이면 quarantine

## 전체 기능 즉시 중단

```text
MEMORY_POLICY_MODE=off
```

기존 코딩 에이전트는 memory 없이 계속 동작해야 합니다.

---

# 16. 회사 인수 체크리스트

새 Linux clone에서:

```bash
make bootstrap
make test
make demo
make docs-check
make package
make release-check
```

파일럿 환경에서:

```bash
make up
make smoke
make mcp-check
make openapi-check
python scripts/make_handoff_manifest.py --check
```

필수 판정:

- [ ] exact commit이 handoff manifest와 일치
- [ ] 테스트 통과
- [ ] `DEMO_PASS: true`
- [ ] wheel/sdist 생성
- [ ] HTTP 또는 MCP 예제 성공
- [ ] PostgreSQL RLS와 private isolation 확인
- [ ] metadata-only search 확인
- [ ] Router reason code 확인
- [ ] outcome credit와 quarantine 확인
- [ ] secret scan clean
- [ ] 회사 모델·하네스 manifest 작성
- [ ] 회사 OIDC와 저장소 권한 연결
- [ ] `shadow` 파일럿 완료
- [ ] 회사 스테이징 책임자 승인

마지막 항목 전에는 `COMPANY-STAGING-CERTIFIED` 또는 `production-ready`라고 부르지 않습니다.

---

# 17. 공급자에게 요구할 최종 전달 보고서

회사 담당자는 다음 항목이 없는 전달물을 인수하지 않는 것이 좋습니다.

```text
1. 전달 branch와 exact commit
2. PR 상태
3. make test 결과
4. make demo 결과와 evidence 경로
5. make package 결과와 해시
6. make release-check 결과
7. CI workflow 전체 상태
8. migration head
9. OpenAPI·MCP schema 버전
10. COMPANY_HANDOFF_MANIFEST.json 검증 결과
11. 알려진 제한사항
12. 회사에서 채워야 할 설정 목록
13. rollback 방법
14. 보안·장애 연락처
```

---

# 18. 쉬운 용어 설명

| 용어 | 쉬운 뜻 |
|---|---|
| Canonical memory | 진짜 기준이 되는 기억 원본 |
| Retrieval index | 관련 기억을 빨리 찾는 검색 색인 |
| Experience card | 한 번의 검증된 해결 경험을 정리한 카드 |
| Router | 기억을 모델에 보여줄지 정하는 문지기 |
| Execution view | 모델에게 보여주는 짧은 실행 지침 |
| Shadow mode | 판단은 기록하지만 실제로 기억을 주입하지 않는 안전 모드 |
| Promotion | 기억을 조직 공유용으로 승인하는 것 |
| Quarantine | 문제 기억을 검색과 사용에서 격리하는 것 |
| Outcome credit | 기억이 도움·방해·무관했는지 적는 결과표 |
| RLS | 데이터베이스가 조직·사용자별 접근을 직접 막는 기능 |
| MCP | 코딩 에이전트가 외부 도구를 호출하는 표준 연결 방식 |
| OIDC/JWKS | 로그인 토큰이 진짜인지 검증하는 표준 방식 |
| Outbox | DB 변경을 검색 색인 등에 안전하게 전달하는 작업함 |

---

# 19. 회사 담당자를 위한 한 문장

> 이 저장소는 기존 사내 코딩 에이전트에 “검증된 경험을 검색하고, 사용해도 되는지 판단하고, 결과에 따라 승격·격리하며, 모든 결정을 감사하는 기능”을 HTTP 또는 MCP로 추가합니다. 회사는 기존 모델과 샌드박스를 그대로 유지하면서, 먼저 오프라인 검사와 shadow 운영을 거친 뒤 검토된 기억만 제한적으로 사용할 수 있습니다.

---

## 부록 A. 회사에 전달하기 전 코딩 에이전트가 해야 할 작업

```text
1. 한국어 Markdown을 docs/COMPANY_IMPLEMENTATION_GUIDE_KO.md에 추가
2. README 회사 온보딩 섹션에서 해당 문서 링크
3. docs/STATUS.yaml, README, PR 본문의 상태를 한 커밋으로 동기화
4. fresh clone에서 make bootstrap/test/demo/docs-check/package/release-check 실행
5. COMPANY_HANDOFF_MANIFEST.json 재생성 또는 검사
6. 실패 항목 수정 후 CI 전체 green 확인
7. 정확한 commit SHA와 실행 로그를 회사에 전달
8. Word 사본은 Release 또는 전달 메일에 첨부
```

## 부록 B. 현재 전달 스냅샷에 관한 주의

이 문서는 특정 commit을 영구적으로 고정하지 않습니다. 회사는 전달 시점의
`COMPANY_HANDOFF_MANIFEST.json`과 공급자가 명시한 exact commit을 기준으로 검사해야 합니다.
