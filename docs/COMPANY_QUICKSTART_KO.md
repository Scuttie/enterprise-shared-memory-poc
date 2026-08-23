# 회사 Quick Start (한국어)

> 목표: **10분 안에 역할 이해, 15분 안에 오프라인 인수검사.** 연구 배경지식 없이 바로 시작할 수 있습니다.

## 1. 이게 무엇인가 (한 문장)
기존 코딩 에이전트에 "검증된 경험을 검색하고, 보여줄지 판단(라우터)하고, 결과에 따라 승격·격리하며, 모든 결정을
감사"하는 기능을 **HTTP 또는 MCP**로 추가하는 거버넌스 계층입니다. **일반적인 코딩 성능 향상은 주장하지 않습니다.**

## 2. 핵심 용어 (5개만)
- **PostgreSQL** = 기억의 원본 장부(권위)
- **Qdrant/Mem0** = 빠른 검색 색인(교체 가능, 원본 아님)
- **Router** = 기억을 모델에게 보여줄지(USE) 말지(ABSTAIN) 정하는 문지기
- **Shadow 모드** = 판단만 기록하고 실제로는 주입하지 않는 안전한 시험 모드
- **Quarantine** = 문제가 반복된 기억을 검색에서 제외하는 격리 상태

## 3. 15분 오프라인 인수검사 (자격증명 불필요)
```bash
git clone https://github.com/Scuttie/enterprise-shared-memory-poc.git
cd enterprise-shared-memory-poc
git checkout <handoff-commit>          # COMPANY_HANDOFF_MANIFEST.json 참고
make bootstrap
make company-acceptance                # -> COMPANY_ACCEPTANCE_PASS: true, DEMO_PASS: true
```
결과: `reports/company_acceptance_result.json` (테스트 수·wheel/sdist SHA-256·한계·필요 입력값).

## 4. 연결 방식 선택
- **MCP** (Claude-Code형 하네스 권장): `python -m enterprise_memory.mcp.server`
- **HTTP**: `POST /v1/experience-cards/search` → 메타데이터 후보 → `/v1/memory-browse`(게이트 통과 시 실행지침)
- 예제: `examples/company_harness/` · 상세: `docs/API_AND_MCP.md`, `docs/COMPANY_INTEGRATION_GUIDE.md`

## 5. 첫 운영 = Shadow
`MEMORY_POLICY_MODE=shadow` 로 시작 → 검색·라우터 결정만 기록(주입 0) → 감사 검토 후 `utility_gated` 전환.
문제 시 즉시 `MEMORY_POLICY_MODE=off`.

## 6. 더 읽기
전체 안내서: [`docs/COMPANY_IMPLEMENTATION_GUIDE_KO.md`](COMPANY_IMPLEMENTATION_GUIDE_KO.md) ·
인수 체크리스트: [`docs/COMPANY_ACCEPTANCE_CHECKLIST.md`](COMPANY_ACCEPTANCE_CHECKLIST.md) ·
한계·근거: [`docs/EVIDENCE_AND_LIMITATIONS.md`](EVIDENCE_AND_LIMITATIONS.md)

## 7. 아직 인증 안 된 것
회사 스테이징 인증 = PENDING · 프로덕션 인증 = NOT CLAIMED · 일반 메모리/라우터 성능 향상 = 입증되지 않음.
