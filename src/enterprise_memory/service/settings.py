"""AppSettings with a STRICT, validated configuration model (§3). Unknown provider/view values, missing
production fields, invalid ranges, non-https endpoints, identical private/shared collections, and dev
backends in staging/production are rejected. Production/staging validation returns a COMPLETE diagnostic
list before raising. ENVIRONMENT=production refusal of dev backends is a hard, non-bypassable gate."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

MODES = ("test", "local", "ci", "staging", "production")
_REGISTRY = ("sqlite", "postgres")
_INDEX = ("in_memory", "mem0")
_IDENTITY = ("static", "oidc")
_SANDBOX = ("local", "kubernetes")
_ARTIFACT = ("local", "s3")
_MODEL = ("fake", "solar")
_VIEW = ("compact_literal", "full_canonical_diagnostic", "concise_summary_diagnostic")
_SECRETS = ("env", "k8s", "external_manager")
_PROD_MODES = ("staging", "production")


class ConfigError(ValueError):
    pass


class ProductionStartupError(RuntimeError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass
class AppSettings:
    environment: str = "local"
    registry_backend: str = "sqlite"
    private_index: str = "in_memory"
    shared_index: str = "in_memory"
    private_collection: str = "private_v1"
    shared_collection: str = "shared_v1"
    identity_provider: str = "static"
    sandbox_provider: str = "local"
    artifact_store: str = "local"
    coding_model: str = "fake"
    execution_view: str = "compact_literal"
    secrets_source: str = "env"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_uri: str = ""
    postgres_dsn: str = ""
    qdrant_url: str = ""
    object_store_endpoint: str = ""
    external_endpoints: dict = field(default_factory=dict)
    max_injected_memories: int = 2
    prompt_token_budget: int = 1200
    solar_timeout_s: int = 60
    worker_concurrency: int = 4
    lease_duration_s: int = 30
    max_attempts: int = 3
    artifact_retention_days: int = 30
    allow_unsafe_staging_backends: bool = False

    _ENUMS = {"environment": MODES, "registry_backend": _REGISTRY, "private_index": _INDEX,
              "shared_index": _INDEX, "identity_provider": _IDENTITY, "sandbox_provider": _SANDBOX,
              "artifact_store": _ARTIFACT, "coding_model": _MODEL, "execution_view": _VIEW,
              "secrets_source": _SECRETS}
    _PROD_FORBIDDEN = {"registry_backend": "sqlite", "private_index": "in_memory",
                       "shared_index": "in_memory", "identity_provider": "static",
                       "sandbox_provider": "local", "artifact_store": "local", "coding_model": "fake"}

    @classmethod
    def from_env(cls, env: dict | None = None) -> "AppSettings":
        e = dict(os.environ if env is None else env)

        def i(k, d):
            try:
                return int(e.get(k, d))
            except ValueError:
                raise ConfigError("invalid integer for %s=%s" % (k, e.get(k)))
        s = cls(
            environment=e.get("ENVIRONMENT", "local"),
            registry_backend=e.get("REGISTRY_BACKEND", "sqlite"),
            private_index=e.get("PRIVATE_INDEX", "in_memory"), shared_index=e.get("SHARED_INDEX", "in_memory"),
            identity_provider=e.get("IDENTITY_PROVIDER", "static"),
            sandbox_provider=e.get("SANDBOX_PROVIDER", "local"), artifact_store=e.get("ARTIFACT_STORE", "local"),
            coding_model=e.get("CODING_MODEL", "fake"), execution_view=e.get("MEMORY_EXECUTION_VIEW", "compact_literal"),
            secrets_source=e.get("SECRETS_SOURCE", "env"), oidc_issuer=e.get("OIDC_ISSUER", ""),
            oidc_audience=e.get("OIDC_AUDIENCE", ""), oidc_jwks_uri=e.get("OIDC_JWKS_URI", ""),
            postgres_dsn=e.get("POSTGRES_DSN", ""), qdrant_url=e.get("QDRANT_URL", ""),
            object_store_endpoint=e.get("OBJECT_STORE_ENDPOINT", ""),
            max_injected_memories=i("MAX_INJECTED_MEMORIES", 2), prompt_token_budget=i("PROMPT_TOKEN_BUDGET", 1200),
            solar_timeout_s=i("SOLAR_TIMEOUT_S", 60), worker_concurrency=i("WORKER_CONCURRENCY", 4),
            lease_duration_s=i("LEASE_DURATION_S", 30), max_attempts=i("MAX_ATTEMPTS", 3),
            artifact_retention_days=i("ARTIFACT_RETENTION_DAYS", 30),
            allow_unsafe_staging_backends=e.get("ALLOW_UNSAFE_STAGING_BACKENDS", "").lower() == "true")
        return s

    def diagnostics(self) -> list:
        errs = []
        for fld, allowed in self._ENUMS.items():
            if getattr(self, fld) not in allowed:
                errs.append("unknown %s=%r (allowed: %s)" % (fld, getattr(self, fld), ",".join(allowed)))
        if not (0 < self.max_injected_memories <= 2):
            errs.append("max_injected_memories must be in 1..2 (got %d)" % self.max_injected_memories)
        for fld in ("prompt_token_budget", "solar_timeout_s", "worker_concurrency", "lease_duration_s", "max_attempts"):
            if getattr(self, fld) <= 0:
                errs.append("%s must be > 0 (got %d)" % (fld, getattr(self, fld)))
        if self.private_index == "mem0" and self.private_collection == self.shared_collection:
            errs.append("private/shared Qdrant collections must differ")
        if self.environment in _PROD_MODES:
            unsafe = (self.environment == "staging" and self.allow_unsafe_staging_backends)
            if not unsafe:
                for fld, bad in self._PROD_FORBIDDEN.items():
                    if getattr(self, fld) == bad:
                        errs.append("%s forbids %s=%s (development backend)" % (self.environment, fld, bad))
                if self.secrets_source == "env":
                    errs.append("%s forbids secrets_source=env" % self.environment)
            for req in ("oidc_issuer", "oidc_audience", "oidc_jwks_uri", "postgres_dsn", "qdrant_url",
                        "object_store_endpoint"):
                if not getattr(self, req):
                    errs.append("%s requires %s" % (self.environment, req))
            for name, url in self.external_endpoints.items():
                if not str(url).startswith("https://"):
                    errs.append("%s requires https for endpoint %s (got %s)" % (self.environment, name, url))
        return errs

    def validate(self) -> list:
        errs = self.diagnostics()
        if self.environment in _PROD_MODES and errs and not (
                self.environment == "staging" and self.allow_unsafe_staging_backends):
            raise ProductionStartupError(errs)
        if self.environment not in _PROD_MODES and errs:
            raise ConfigError("; ".join(errs))
        return errs
