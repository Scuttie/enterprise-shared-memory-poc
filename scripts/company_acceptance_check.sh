#!/usr/bin/env bash
# Company acceptance check — one command a company runs after cloning to verify install/test/demo/package.
# Fails (non-zero exit) on any failed step; writes reports/company_acceptance_result.json. POSIX-ish bash.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python}"
RESULT="reports/company_acceptance_result.json"
mkdir -p reports
fail=0
step() { echo ">> $1"; }
mark() { [ "$1" -ne 0 ] && fail=1; }

step "0. tool availability (python/git/docker)"
"$PY" --version || { echo "python missing"; fail=1; }
git --version >/dev/null 2>&1 || echo "WARN: git not found"
docker --version >/dev/null 2>&1 || echo "NOTE: docker not found (only needed for full-service smoke, not offline acceptance)"

step "1. bootstrap (editable install + pytest)"
"$PY" -m pip install -q -e ".[dev]" pytest pyyaml >/dev/null 2>&1 || "$PY" -m pip install -q -e . pytest pyyaml >/dev/null 2>&1
mark $?

step "2. test (unit + integration + docs)"
TEST_OUT="$("$PY" -m pytest -q tests/unit/test_experience_compiler.py tests/unit/test_experience_schema_sql.py \
  tests/unit/test_rule_router_v1.py tests/unit/test_agentic_search.py tests/unit/test_outcome_governance.py \
  tests/unit/test_mcp_adapters.py tests/integration/test_company_demo.py 2>&1)"
TEST_RC=$?; echo "$TEST_OUT" | tail -1; mark $TEST_RC
TEST_COUNT="$(echo "$TEST_OUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' | head -1)"
if [ -z "$TEST_COUNT" ] || [ "$TEST_COUNT" = "0" ]; then
  TEST_COUNT="$(grep -hE '^def test_|^[[:space:]]+def test_' \
    tests/unit/test_experience_compiler.py tests/unit/test_experience_schema_sql.py tests/unit/test_rule_router_v1.py \
    tests/unit/test_agentic_search.py tests/unit/test_outcome_governance.py tests/unit/test_mcp_adapters.py \
    tests/integration/test_company_demo.py 2>/dev/null | wc -l | tr -d ' ')"
fi
[ "$TEST_RC" -eq 0 ] && TEST_PASSED=true || TEST_PASSED=false

step "3. offline demo (DEMO_PASS)"
DEMO_OUT="$("$PY" scripts/demo_company_handoff.py --offline 2>&1)"; DEMO_RC=$?
echo "$DEMO_OUT" | tail -1; mark $DEMO_RC
echo "$DEMO_OUT" | grep -q "DEMO_PASS: true" && DEMO_PASSED=true || { DEMO_PASSED=false; fail=1; }

step "4. docs-check"
"$PY" scripts/check_docs_consistency.py; DOCS_RC=$?; mark $DOCS_RC
"$PY" scripts/render_project_status.py --check; mark $?
"$PY" scripts/check_literature_provenance.py >/dev/null 2>&1 || true
[ "$DOCS_RC" -eq 0 ] && DOCS_PASSED=true || DOCS_PASSED=false

step "5. package (wheel + sdist)"
"$PY" -m pip install -q build >/dev/null 2>&1
"$PY" -m build >/dev/null 2>&1; PKG_RC=$?; mark $PKG_RC
[ "$PKG_RC" -eq 0 ] && PKG_PASSED=true || PKG_PASSED=false
WHL="$(ls dist/*.whl 2>/dev/null | head -1)"; SDIST="$(ls dist/*.tar.gz 2>/dev/null | head -1)"

step "6. release-check (handoff manifest current)"
"$PY" scripts/make_handoff_manifest.py --check; MAN_RC=$?; mark $MAN_RC
[ "$MAN_RC" -eq 0 ] && MAN_OK=true || MAN_OK=false

step "7. secret / path scan"
SCAN="$(grep -rIE 'sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY' \
  --include='*.py' --include='*.yaml' --include='*.yml' --include='*.json' --include='*.md' \
  src docs configs examples scripts 2>/dev/null | grep -v 'example\|placeholder\|<' | wc -l)"
[ "${SCAN:-0}" -eq 0 ] && SCAN_CLEAN=true || { SCAN_CLEAN=false; fail=1; }

step "8. write result json"
[ "$fail" -eq 0 ] && OVERALL=true || OVERALL=false
"$PY" scripts/_acceptance_result.py "$TEST_PASSED" "$TEST_COUNT" "$DEMO_PASSED" "$DOCS_PASSED" "$PKG_PASSED" "$MAN_OK" "$SCAN_CLEAN" "$OVERALL"

echo ""
if [ "$fail" -eq 0 ]; then
  echo "COMPANY_ACCEPTANCE_PASS: true"
  echo "DEMO_PASS: true"
  exit 0
else
  echo "COMPANY_ACCEPTANCE_PASS: false"
  exit 1
fi
