# Company configuration required (for real staging deployment)

Missing company values do NOT block local development; they MUST block `ENVIRONMENT=production` startup
with a clear validation report. Required inputs: OIDC issuer / audience / JWKS endpoint; scope-role
mapping; Git provider + app credentials; repository-to-team mapping; PostgreSQL endpoint; Qdrant
endpoint; object-store endpoint; secret-manager integration; Kubernetes cluster/namespace; container
registry; retention periods; deletion policy; audit-log retention; allowed repository classes; approved
sandbox runtime (gVisor/Kata/Firecracker require security approval); network egress policy; incident
contacts; data-classification rules. See `deploy/values-company.example.yaml`.
