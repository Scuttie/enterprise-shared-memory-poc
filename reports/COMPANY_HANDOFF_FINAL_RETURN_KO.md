# 회사 전달 최종 보고서

## 1. 저장소·브랜치·커밋
- GitHub: `Scuttie/enterprise-shared-memory-poc`
- 브랜치: `codex/utility-router-v0.3`
- 전달 커밋(seal): `ea4bd4a` (fresh-clone 인수 검증 완료)
- PR #2: OPEN / **DRAFT** — merge·tag 안 함
- 패키지 버전: `0.3.0.dev1`

## 2. 한국어 안내서
`docs/COMPANY_IMPLEMENTATION_GUIDE_KO.md` (README 회사 파일럿 섹션 + `docs/README.md` 인덱스에서 링크)

## 3. 설치와 인수 검사 (명령 하나)
```bash
git clone https://github.com/Scuttie/enterprise-shared-memory-poc.git
cd enterprise-shared-memory-poc
git checkout ea4bd4a
make bootstrap
make company-acceptance      # 또는: bash scripts/company_acceptance_check.sh
```
성공 출력: `COMPANY_ACCEPTANCE_PASS: true` · `DEMO_PASS: true`. 결과: `reports/company_acceptance_result.json`.

## 4. 검증 결과 (fresh clone, 커밋 ea4bd4a)
- 테스트: **60개 통과**
- 오프라인 데모: **DEMO_PASS: true**
- docs-check / package / release-check(manifest) / secret-scan: 전부 통과
- wheel: `enterprise_shared_memory_poc-0.3.0.dev1-py3-none-any.whl` (sha256 `3d29daee…`)
- sdist: `enterprise_shared_memory_poc-0.3.0.dev1.tar.gz` (sha256 `85cba1f7…`)

## 5. 구현된 기능
PostgreSQL 원본 장부 + RLS 테넌트 격리 · Qdrant/Mem0 검색 색인 · 유틸리티 라우터(USE/ABSTAIN, 감사) ·
메타데이터-only 검색 → 게이트 browse · 결과 크레딧 + 거버넌스(승격 리뷰 필수, 반복손해 quarantine) ·
MCP + 어댑터(openai/anthropic/jsonrpc/mcp) · 오프라인 데모 · 문서 · 패키지/매니페스트/SBOM.

## 6. 아직 인증되지 않은 것
- 회사 스테이징 인증: **PENDING** (회사 환경 인수 + 서면 서명 필요)
- 프로덕션 인증: **NOT CLAIMED**
- 회사 모델·하네스 연동: 아직 검증 안 됨(회사 매니페스트 필요)

## 7. 회사가 제공해야 할 값
사내 모델 ID·revision · 하네스 이름/버전 · serving protocol · endpoint · API secret 이름 · OIDC issuer · JWKS URL ·
PostgreSQL URL · Qdrant URL · 저장소 접근 정책 · 샌드박스 owner/runtime · secret manager · staging namespace ·
운영·보안 담당자. (예시 파일은 placeholder만; 시스템이 회사 모델 이름을 추측하지 않음)

## 8. Shadow 파일럿 순서
1. `MEMORY_POLICY_MODE=shadow` 로 배포 → 검색·라우터 결정만 기록, **주입 0**
2. 감사 로그 검토(USE/ABSTAIN, private 미노출, 버전 틀린 기억 거부)
3. `utility_gated` 로 전환(리뷰·승격된 카드만)

## 9. 문제 시 전체 memory 즉시 끄기
`MEMORY_POLICY_MODE=off` — 기존 코딩 에이전트는 memory 없이 계속 동작.

## 10. 알려진 연구 결과 (정직)
- 일반적인 메모리 코딩성능 향상: **입증되지 않음**(R14–R20 null)
- 유틸리티 라우터 독립 성능효과: **NULL / 입증되지 않음**(R19 소표본 양성은 R20에서 재현 실패)
- 라우터의 확인된 속성 = **안전성**(무관 메모리 100% abstain, 순손실 0), 성능 향상 아님

## 11. 지원되지 않는 주장 (쓰지 말 것)
"이 시스템이 코딩 성능을 높인다" / "router가 성능을 높인다" / "production-ready" /
"company-staging-certified" / "회사 모델 연동이 이미 검증됨".

## 12. merge/tag 권고
**merge 하지 않음, release tag 만들지 않음.** PR #2는 회사 검토까지 DRAFT 유지.
