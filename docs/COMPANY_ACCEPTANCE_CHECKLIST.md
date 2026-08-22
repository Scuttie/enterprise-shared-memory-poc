# Company Acceptance Checklist

All boxes start unchecked; each links to automated evidence. Company staging certification is granted only after
all pass **in the company's environment** plus written sign-off.

- [ ] Fresh clone: `make bootstrap && make test` green
- [ ] Offline demo: `make demo` → `DEMO_PASS: true` (`ci-company-demo`)
- [ ] Docs truth: `make docs-check` (`ci-docs`)
- [ ] Package builds: `make package` (wheel + sdist)
- [ ] Container builds + compose smoke: `make up && make smoke`
- [ ] HTTP integration example runs (`ci-mcp`)
- [ ] MCP integration example runs (`ci-mcp`)
- [ ] Schema / RLS / immutability (`ci-experience-schema`)
- [ ] Router reason codes + leakage sentinel (`ci-utility-router`)
- [ ] Search metadata-only + gated browse (`ci-agentic-search`)
- [ ] Outcome credit + governance (`ci-outcome-governance`)
- [ ] Literature provenance / no vendoring (`ci-literature-audit`)
- [ ] Security: cross-user private leakage = 0; secret/path scan clean
- [ ] Company inputs provided: model/harness manifest, OIDC issuer, staging env
- [ ] Staging sign-off recorded → then and only then: **COMPANY-STAGING-CERTIFIED**
