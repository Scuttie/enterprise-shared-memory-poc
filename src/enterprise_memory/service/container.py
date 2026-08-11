"""ServiceContainer + wiring (§3). `build_container(settings)` validates the settings (raising on a
production dev-backend), then constructs the concrete providers. Only the local/test wiring is fully
implemented here; production adapters are constructed by their own modules and injected. `create_app`
takes (settings, container) so nothing is hard-coded."""
from __future__ import annotations
from dataclasses import dataclass

from .settings import AppSettings
from .providers_local import (FakeSolarProvider, LocalArtifactStore, LocalFixtureRepositoryProvider,
                              LocalEvaluationSandbox, ListMetrics, ListAudit, InMemoryOutcomeStore)
from .jobs import InMemoryJobRepository
from .outbox import InMemoryOutbox


@dataclass
class ServiceContainer:
    settings: AppSettings
    registry: object = None
    private_index: object = None
    shared_index: object = None
    artifact_store: object = None
    identity_provider: object = None
    repo_authz: object = None
    repo_provider: object = None
    model: object = None
    sandbox: object = None
    jobs: object = None
    outbox: object = None
    audit: object = None
    metrics: object = None
    outcome_store: object = None


def build_container(settings: AppSettings, overrides: dict | None = None) -> ServiceContainer:
    settings.validate()   # raises ProductionStartupError on a production dev-backend
    ov = overrides or {}
    if settings.environment in ("test", "local"):
        c = ServiceContainer(
            settings=settings,
            artifact_store=ov.get("artifact_store") or LocalArtifactStore(),
            repo_provider=ov.get("repo_provider") or LocalFixtureRepositoryProvider(ov.get("fixtures", {})),
            model=ov.get("model") or FakeSolarProvider(),
            sandbox=ov.get("sandbox") or LocalEvaluationSandbox(),
            jobs=ov.get("jobs") or InMemoryJobRepository(),
            outbox=ov.get("outbox") or InMemoryOutbox(),
            metrics=ov.get("metrics") or ListMetrics(),
            audit=ov.get("audit") or ListAudit(),
            outcome_store=ov.get("outcome_store") or InMemoryOutcomeStore(),
            registry=ov.get("registry"), private_index=ov.get("private_index"),
            shared_index=ov.get("shared_index"), identity_provider=ov.get("identity_provider"),
            repo_authz=ov.get("repo_authz"))
        return c
    # staging/production: adapters must be provided via overrides (Postgres/Mem0/S3/OIDC/K8s) — NOT
    # implemented as runnable here; construction is delegated to their modules once company infra exists.
    missing = [k for k in ("registry", "private_index", "shared_index", "identity_provider",
                           "repo_provider", "model", "sandbox", "jobs", "audit") if not ov.get(k)]
    if missing:
        raise RuntimeError("environment=%s requires production adapters: %s" % (settings.environment, missing))
    return ServiceContainer(settings=settings, **{k: ov[k] for k in ov})
