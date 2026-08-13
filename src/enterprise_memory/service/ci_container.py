"""Container wiring for ci/local (P5 §2). Constructs the durable service dependencies backed by REAL
PostgreSQL/Qdrant/MinIO plus credential-free fixtures (file-backed JWKS, offline repository provider, fake
execution backend, controlled local sandbox). Production/staging must NOT use these fakes — build_container
raises for a prod environment here (the real prod adapters are a separate, company-configured path)."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass

from ..persistence.database import make_engine
from ..auth.oidc import OIDCConfig, JWKSCache
from ..indexing.qdrant_indexes import QdrantIndex
from ..indexing.embeddings import DeterministicTestEmbedder
from ..artifacts.service import ArtifactService
from .p5deps import OIDCIdentityProvider, DbRepositoryAuthz, DbTaskPolicyRepository, OfflineRepositoryProvider
from .execution import FakeExecutionBackend
from .localsandbox import ControlledLocalSandbox

INDEX_DIM = int(os.environ.get("INDEX_DIM", "64"))


class ContainerError(RuntimeError):
    pass


def _artifact_store():
    endpoint = os.environ.get("MINIO_ENDPOINT")
    if endpoint:
        from ..artifacts.store import S3ArtifactStore
        return S3ArtifactStore(endpoint, os.environ.get("MINIO_BUCKET", "esm-artifacts-e2e"),
                               os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
                               os.environ.get("MINIO_SECRET_KEY", "minioadmin"), secure=False, sse=None)
    from ..artifacts.store import LocalArtifactStore
    return LocalArtifactStore(os.environ.get("ARTIFACT_DIR", "/tmp/esm-artifacts"))


def _oidc_identity(environment):
    issuer = os.environ.get("OIDC_ISSUER", "https://idp.e2e.local/")
    audience = os.environ.get("OIDC_AUDIENCE", "esm-api")
    jwks_file = os.environ["OIDC_JWKS_FILE"]                        # file-backed JWKS fixture
    config = OIDCConfig(issuer=issuer, audience=audience, jwks_uri="https://jwks.e2e.local/jwks.json",
                        environment=environment)
    cache = JWKSCache(config, fetcher=lambda: json.load(open(jwks_file, "r", encoding="utf-8")))
    return OIDCIdentityProvider(config, cache)


@dataclass
class Container:
    environment: str
    api_engine: object
    worker_engine: object
    identity: object
    repo_authz: object
    task_policy: object
    repo_provider: object
    artifacts: object
    index: object
    embedder: object
    backend: object
    sandbox: object

    async def ensure_ready(self):
        await self.index.ensure_ready()

    async def aclose(self):
        for e in (self.api_engine, self.worker_engine):
            try:
                await e.dispose()
            except Exception:
                pass
        try:
            await self.index.close()
        except Exception:
            pass


def build_container(environment=None) -> Container:
    environment = environment or os.environ.get("ENVIRONMENT", "ci")
    if environment in ("staging", "production"):
        raise ContainerError("build_container(ci) refuses to construct fakes for %s; use the company "
                             "production adapter path" % environment)
    return Container(
        environment=environment,
        api_engine=make_engine("api_service", "api_pw"),
        worker_engine=make_engine("worker_service", "worker_pw"),
        identity=_oidc_identity(environment),
        repo_authz=DbRepositoryAuthz(),
        task_policy=DbTaskPolicyRepository(),
        repo_provider=OfflineRepositoryProvider(),
        artifacts=ArtifactService(_artifact_store()),
        index=QdrantIndex.from_env(INDEX_DIM),
        embedder=DeterministicTestEmbedder(INDEX_DIM),
        backend=FakeExecutionBackend(),
        sandbox=ControlledLocalSandbox(environment))
