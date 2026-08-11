"""AppSettings + production-mode validation (§3). ENVIRONMENT=production MUST refuse to start with a
development backend, SQLite, static identity, the local subprocess sandbox, plaintext secrets, or an
unencrypted external endpoint. This is a hard, deterministic startup gate — never bypassable by a flag."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

MODES = ("test", "local", "staging", "production")


class ProductionStartupError(RuntimeError):
    """Raised when ENVIRONMENT=production is configured with a non-production-safe component."""


@dataclass
class AppSettings:
    environment: str = "local"
    registry_backend: str = "sqlite"          # sqlite | postgres
    private_index: str = "in_memory"          # in_memory | mem0
    shared_index: str = "in_memory"
    identity_provider: str = "static"         # static | oidc
    sandbox_provider: str = "local"           # local | kubernetes
    artifact_store: str = "local"             # local | s3
    coding_model: str = "fake"                # fake | solar
    solar_base_url: str = "https://api.upstage.ai/v1"
    solar_model: str = "solar-pro2-251215"
    external_endpoints: dict = field(default_factory=dict)   # name -> url (must be https in prod)
    secrets_source: str = "env"               # env | k8s | external_manager
    max_injected_memories: int = 2
    execution_view: str = "compact_literal"

    _PROD_FORBIDDEN = {
        "registry_backend": {"sqlite"}, "private_index": {"in_memory"}, "shared_index": {"in_memory"},
        "identity_provider": {"static"}, "sandbox_provider": {"local"}, "artifact_store": {"local"},
        "coding_model": {"fake"},
    }

    @classmethod
    def from_env(cls, env: dict | None = None) -> "AppSettings":
        e = dict(os.environ if env is None else env)
        return cls(
            environment=e.get("ENVIRONMENT", "local"),
            registry_backend=e.get("REGISTRY_BACKEND", "sqlite"),
            private_index=e.get("PRIVATE_INDEX", "in_memory"),
            shared_index=e.get("SHARED_INDEX", "in_memory"),
            identity_provider=e.get("IDENTITY_PROVIDER", "static"),
            sandbox_provider=e.get("SANDBOX_PROVIDER", "local"),
            artifact_store=e.get("ARTIFACT_STORE", "local"),
            coding_model=e.get("CODING_MODEL", "fake"),
            solar_base_url=e.get("SOLAR_BASE_URL", "https://api.upstage.ai/v1"),
            solar_model=e.get("SOLAR_MODEL", "solar-pro2-251215"),
            secrets_source=e.get("SECRETS_SOURCE", "env"),
            execution_view=e.get("MEMORY_EXECUTION_VIEW", "compact_literal"),
        )

    def validate(self) -> list:
        """Return a list of validation errors; empty list = OK. Raises for a production violation."""
        errors = []
        if self.environment not in MODES:
            errors.append("unknown ENVIRONMENT=%s" % self.environment)
        if self.max_injected_memories > 2:
            errors.append("max_injected_memories must be <= 2 (got %d)" % self.max_injected_memories)
        if self.environment == "production":
            for field_name, forbidden in self._PROD_FORBIDDEN.items():
                val = getattr(self, field_name)
                if val in forbidden:
                    errors.append("production forbids %s=%s (development backend)" % (field_name, val))
            if self.secrets_source == "env":
                errors.append("production forbids secrets_source=env (use k8s / external_manager)")
            for name, url in self.external_endpoints.items():
                if not str(url).startswith("https://"):
                    errors.append("production requires https for endpoint %s (got %s)" % (name, url))
            if errors:
                raise ProductionStartupError("; ".join(errors))
        return errors
