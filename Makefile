# P6/R19 §16 — company developer experience. POSIX make; targets are thin wrappers over the tooling.
.DEFAULT_GOAL := help
PY ?= python
COMPOSE ?= docker compose -f deploy/docker-compose.company.example.yml

.PHONY: help bootstrap test test-unit test-integration demo up down smoke docs-check openapi-check mcp-check \
        package release-check evaluate-reference evaluate-router

help:
	@echo "targets: bootstrap test test-unit test-integration demo up down smoke docs-check openapi-check \
mcp-check package release-check evaluate-reference evaluate-router"

bootstrap:
	$(PY) -m pip install -e ".[dev]" || $(PY) -m pip install -e .

test: test-unit test-integration docs-check

test-unit:
	$(PY) -m pytest -q tests/unit

test-integration:
	$(PY) -m pytest -q tests/integration/test_company_demo.py

demo:
	$(PY) scripts/demo_company_handoff.py --offline

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down -v

smoke:
	$(PY) scripts/demo_company_handoff.py --offline
	$(PY) examples/company_harness/http_adapter.py

docs-check:
	$(PY) scripts/check_docs_consistency.py
	$(PY) scripts/render_project_status.py --check
	$(PY) scripts/check_literature_provenance.py

openapi-check:
	@test -f openapi_v1.json && echo "openapi snapshot present" || (echo "missing openapi snapshot" && exit 1)

mcp-check:
	$(PY) -m pytest -q tests/unit/test_mcp_adapters.py

package:
	$(PY) -m pip install -q build && $(PY) -m build

release-check: test docs-check mcp-check
	$(PY) scripts/make_handoff_manifest.py --check

evaluate-reference:
	@echo "dispatch ci-r19-experiment (arm=A4 literature reference); see docs/RESEARCH_REPRODUCTION.md"

evaluate-router:
	@echo "dispatch ci-r19-experiment (arm=A5 utility-gated, held-out); see docs/P6_UTILITY_ROUTER_PREREG.md"
