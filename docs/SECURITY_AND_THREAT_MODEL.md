# Security & threat model

Threats addressed in the PoC: private cross-user leakage (physically separated stores + per-user
retrieval), unauthorized retrieval (permission/scope gates), secret/PII promotion (security scanner blocks
before promotion), stale/out-of-scope fix propagation (validity gates + compiler refusal), and sandbox
escape (env allow-list, path-traversal/network guards, process-tree kill).

**Not yet addressed** (see PRODUCTIONIZATION_CHECKLIST.md): malicious prompt injection at scale, adversarial
contributors, production-grade container isolation, managed secrets, SSO/RBAC, retention/deletion
guarantees. This PoC has had no penetration test; do not treat it as production-safe.
