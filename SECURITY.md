# Security Policy

## Supported versions
The `0.3.x` line (current development / handoff release candidate) receives security fixes.

## Reporting a vulnerability
**Do not open a public GitHub Issue for security reports.** Use GitHub's **Private Vulnerability Reporting**
(Security tab → "Report a vulnerability") or contact the maintainers privately at `<security-contact-placeholder>`.
Target acknowledgement: within a few business days.

## Highest-priority classes
- **Cross-user / cross-tenant private-memory leakage** (RLS bypass, private→shared exposure).
- **Secret or PII exposure** in logs, memory cards, retrieval projections, or execution views.
- **Verifier / hidden-test exposure** to a model.
- Injection of quarantined/expired/wrong-version memory.

## Reproduction data
Never include real credentials, private repository data, or customer data in a report or reproduction. Use
synthetic/fictional data (all examples in this repo are fictional).
