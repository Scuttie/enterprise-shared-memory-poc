# Contributing

Thanks for your interest! This project is a governed shared-memory control plane for coding agents.

## Dev environment
```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Tests
```bash
make test                 # unit + integration + docs
make demo                 # offline demo -> DEMO_PASS: true
make company-acceptance   # one-command acceptance (tests/demo/docs/package/license/secret-scan)
```

## Sign-off (DCO)
All commits must be signed off (Developer Certificate of Origin):
```bash
git commit -s -m "..."
```

## PR checklist
- [ ] `make company-acceptance` passes on a fresh clone
- [ ] docs stay consistent (`make docs-check`); update `docs/STATUS.yaml` before changing user-facing claims
- [ ] no secrets/credentials/private data; examples are fictional
- [ ] no upstream unlicensed code/data vendored (`ci-literature-audit`)
- [ ] the product wheel still ships only `enterprise_memory` (`scripts/check_wheel_scope.py`)

## Claim rule (important)
**Benchmark results may not be presented as product/feature performance claims** without a preregistered,
controlled evaluation. This repository does not claim a general coding-performance lift (see `reports/` R14-R21).
Security-relevant changes require extra review (tenancy/RLS, private/shared isolation, secret handling).
