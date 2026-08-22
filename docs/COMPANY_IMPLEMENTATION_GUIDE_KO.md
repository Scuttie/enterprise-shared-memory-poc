# 회사 도입·구현 안내서 (Enterprise Shared Memory)

> 이 문서는 회사 엔지니어가 연구 이력을 읽지 않고도 시스템을 **clone → 설정 → 실행 → 검사 → 통합**할 수 있도록
> 작성된 한국어 안내서입니다. 기준 원본은 GitHub의 이 Markdown 파일이며, Word 사본은 배포 편의용입니다.

## 0. 먼저 읽어야 할 정직한 경계

- **회사 전달 가능**: `COMPANY-HANDOFF-READY` — fresh clone에서 테스트·오프라인 데모가 통과합니다.
- **회사 스테이징 인증**: `PENDING / NOT CERTIFIED` — 회사 환경의 스테이징 검증·서명이 아직 없습니다.
- **프로덕션 인증**: `NOT CLAIMED`.
- **연구 결과(성능)**:
  - 서비스·거버넌스 배관 = **구현 및 CI 검증됨**
  - 일반적인 memory 성능 향상 = **입증되지 않음** (R14–R18에서 신뢰할 만한 이득 없음)
  - utility router 독립 효과 = **입증되지 않음** (R19 held-out에서 compute/무관 대조를 못 넘음)
- 따라서 이 시스템은 **성능 향상 도구가 아니라, 감사 가능한 거버넌스·안전·선택 플랫폼**으로 도입하십시오.
  성능 향상 주장은 `docs/STATUS.yaml`의 `utility_router_result`가 POSITIVE가 될 때만 가능합니다.

## 1. 이 시스템이 하는 일

- 검증된 코딩 경험(공개 이슈+PR+패치, 또는 검증된 에이전트 작업)을 **경험 카드**로 컴파일합니다.
  카드는 3가지 투영을 가집니다: canonical(정본), **neutral 검색 투영(메타데이터만)**, **execution view(실행 지침)**.
- **검색은 메타데이터만** 반환하고, **browse(실행 지침)** 는 테넌트/저장소/경로/버전/거버넌스 게이트와
  **utility router** 가 승인한 뒤에만 제공합니다.
- 각 후보를 라우터가 `USE`/`ABSTAIN`으로 판정하며(결정적·감사 가능·동결 reason code), 모든 결정이 기록됩니다.
- 결과(gain/loss/neutral/compute-only)를 크레딧하고, 카드 수명주기를 거버넌스(candidate→probation→promoted;
  반복 손해→quarantine)로 관리합니다(수동 리뷰 필수, 강제 승격 없음).

## 2. 5분 오프라인 데모 (자격증명 불필요)

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python scripts/demo_company_handoff.py --offline  # -> DEMO_PASS: true
```

데모는 전체 거버넌스 흐름(컴파일→승격→검색→라우팅→주입→크레딧→quarantine→private 격리→감사)을
인프라 없이 수행하고 `artifacts/p6/demo_evidence.json`을 남깁니다.

## 3. 설치와 검사 (현재 브랜치)

```bash
make bootstrap      # 또는: pip install -e ".[dev]"
make test           # 단위+통합+docs 검사
make demo           # DEMO_PASS: true
make docs-check     # 문서 진실성 게이트
make package        # wheel/sdist 생성
make release-check  # handoff manifest 일치
```

Windows 등 `make` 미설치 환경에서는 `Makefile`의 대응 명령을 직접 실행하십시오
(예: `python -m pytest -q tests/unit tests/integration`, `python scripts/check_docs_consistency.py`,
`python -m build`).

## 4. 회사가 설정해야 할 값

- **모델/하니스 매니페스트** (`configs/company.example.yaml`): protocol + model id (+ endpoint).
  시스템이 회사 모델 정체를 추측하지 않도록 **model id를 반드시 지정**하십시오. 자격증명은 매니페스트가 아니라
  런타임 시크릿 스토어에서 주입합니다.
- **OIDC issuer / JWKS** + tenant/org 식별자
- **PostgreSQL + Qdrant** 배포 대상 (또는 파일럿용 번들 compose)
- **저장소 접근 정책** (source/target 스코프)

## 5. 실행 모드 (`MEMORY_POLICY_MODE`)

`off` · `static_relevant` · `agentic_reference`(검색/브라우즈, 라우터 없음) · `utility_gated`(검색/브라우즈+라우터)
· `shadow`(라우터 실행·결정 기록, **주입 없음**). **권장 파일럿: `shadow` → 검토 후 `utility_gated`(승격된 카드만).**
클라이언트는 모드나 실험 arm을 선택할 수 없습니다(서버 강제).

## 6. HTTP / MCP 통합

```bash
python -m enterprise_memory.mcp.server            # stdio MCP: memory_search/browse/report_outcome/explain_decision
python examples/company_harness/http_adapter.py   # 인프라 없이 오프라인 통합 예제
```

- 프로토콜: **openai / anthropic / jsonrpc / mcp** (`examples/company_harness/`).
- **신원은 서버측 파생** — `org_id`·토큰·`policy_mode`를 도구 인자로 보내면 서버가 거부합니다.
- **검색=메타데이터만**, execution view는 browse에서 게이트 통과 후에만. verifier/hidden test는 절대 노출 안 함.

## 7. 파일럿 롤아웃

1. `MEMORY_POLICY_MODE=shadow`로 저장소 미러에 배포 → 라우터 결정·결과 크레딧을 **주입 위험 0**으로 수집
2. 감사 로그 검토 → 라우터 reason code·거버넌스 확인
3. `utility_gated`로 전환(리뷰·승격된 카드만)
4. 인수 기준: `docs/COMPANY_ACCEPTANCE_CHECKLIST.md`

## 8. 보안 요약

PostgreSQL **RLS(ENABLE+FORCE)** 테넌트 격리 · private/shared 물리·논리 분리 · OIDC/JWKS + 스코프
(`memory:search|browse|feedback|review|admin`) · append-only 감사 · 불변 버전 · 비밀/PII 미로깅 ·
verifier·hidden test 미노출. 상세: `docs/SECURITY_AND_PRIVACY.md`.

## 9. 남은 회사 인증 절차

- 회사 스테이징 환경 구성 + 인수 체크리스트를 **회사 환경에서** 통과 + 서면 서명 → 그때만 `COMPANY-STAGING-CERTIFIED`.
- 프로덕션 인증은 별도이며 현재 주장하지 않습니다.

## 10. 참고 문서

- `README.md` — 제품 개요·상태표
- `docs/STATUS.yaml` — 단일 진실원(기계판독)
- `docs/ARCHITECTURE.md` · `docs/API_AND_MCP.md` · `docs/MEMORY_POLICY.md`
- `docs/COMPANY_HANDOFF.md` — 30분 온보딩
- `docs/EVIDENCE_AND_LIMITATIONS.md` — 주장 축·한계
- `docs/RESEARCH_REPRODUCTION.md` — 동결 매니페스트·재현
