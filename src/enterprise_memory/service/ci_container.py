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
from ..indexing.embeddings import DeterministicTestEmbedder, SentenceTransformerEmbedder
from ..artifacts.service import ArtifactService
from .p5deps import OIDCIdentityProvider, DbRepositoryAuthz, DbTaskPolicyRepository, OfflineRepositoryProvider
from .execution import (FakeExecutionBackend, WholeFileModelExecutionBackend, P52WholeFileExecutionBackend,
                        InstructWholeFileExecutionBackend)
from .localsandbox import ControlledLocalSandbox

INDEX_DIM = int(os.environ.get("INDEX_DIM", "64"))
SOLAR_BASE_URL = os.environ.get("SOLAR_BASE_URL", "https://api.upstage.ai/v1/solar")
SOLAR_MODEL = os.environ.get("SOLAR_MODEL", "solar-pro2-251215")
EMBEDDER_KIND = os.environ.get("EMBEDDER", "deterministic")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_REVISION = os.environ.get("EMBED_REVISION") or None


def _embedder():
    """Retrieval embedder. Default is the credential-free deterministic test embedder. The paid REALBENCH-R2
    benchmark path sets EMBEDDER=st to use the PINNED PRODUCTION SentenceTransformerEmbedder (§6.2); the
    worker, seeding, and runner all resolve the embedder the same way so index and query vectors match."""
    if EMBEDDER_KIND in ("st", "sentence-transformers", "production"):
        return SentenceTransformerEmbedder(EMBED_MODEL_ID, revision=EMBED_REVISION)
    return DeterministicTestEmbedder(INDEX_DIM)


def _execution_backend():
    """Server-owned execution backend. Default is the deterministic fake (credential-free CI). When
    EXECUTION_BACKEND=solar the worker calls the real Solar coding model via DirectModelExecutionBackend (key
    from UPSTAGE_API_KEY, read by an EnvSecretProvider — never from any request)."""
    kind = os.environ.get("EXECUTION_BACKEND", "fake")
    if kind in ("solar", "solar_p52", "bigcode_instruct", "ds1000"):
        from ..providers.solar import SolarProvider
        from ..providers.secrets import EnvSecretProvider
        mo = int(os.environ.get("SOLAR_MAX_TOKENS", "1024"))
        # Under a large parallel benchmark the Upstage API rate-limits (429). Ride it out: many retries with
        # long, Retry-After-honoring backoff and a generous per-request deadline, so a 429'd job waits and
        # succeeds instead of exhausting. Tunable via env for the paid benchmark workflows.
        provider = SolarProvider(SOLAR_BASE_URL, SOLAR_MODEL, EnvSecretProvider(),
                                 key_name=os.environ.get("SOLAR_KEY_NAME", "UPSTAGE_API_KEY"),
                                 max_output_tokens=mo,
                                 max_attempts=int(os.environ.get("SOLAR_MAX_ATTEMPTS", "4")),
                                 total_deadline=float(os.environ.get("SOLAR_TOTAL_DEADLINE", "60")),
                                 read_timeout=float(os.environ.get("SOLAR_READ_TIMEOUT", "30")),
                                 backoff_max=float(os.environ.get("SOLAR_BACKOFF_MAX", "8")),
                                 retry_after_max=float(os.environ.get("SOLAR_RETRY_AFTER_MAX", "30")))
        if kind == "bigcode_instruct":   # REALBENCH-R2: prompt IS the NL instruct_prompt (+memory), whole file
            return InstructWholeFileExecutionBackend(provider, model_max_tokens=mo)
        if kind == "ds1000":             # REALBENCH-R3: prompt IS the DS-1000 NL problem (+memory), completion
            from .execution import DS1000ExecutionBackend
            return DS1000ExecutionBackend(provider, model_max_tokens=mo)
        if kind == "solar_p52":     # P5.2 backend: prompt shows the full snapshot (incl. public tests)
            return P52WholeFileExecutionBackend(provider, model_max_tokens=mo)
        # P5.1 whole-file output + server-side difflib diff
        return WholeFileModelExecutionBackend(provider, model_max_tokens=mo)
    return FakeExecutionBackend()


def _repo_provider():
    """Repository/task adapter. Default is the offline demo provider. The frozen experiment uses the
    FrozenExecutableBenchmarkAdapter (snapshot + server-owned hidden test) when REPO_PROVIDER=benchmark."""
    rp = os.environ.get("REPO_PROVIDER")
    if rp == "benchmark":
        from .task_adapter import FrozenExecutableBenchmarkAdapter
        return FrozenExecutableBenchmarkAdapter()
    if rp == "benchmark_p52":
        from .task_adapter import FrozenExecutableBenchmarkAdapterP52
        return FrozenExecutableBenchmarkAdapterP52()
    if rp == "mbpp":
        from experiments.realbench_r1.adapter import EvalPlusMBPPTaskAdapter
        return EvalPlusMBPPTaskAdapter()
    if rp == "bigcode":
        from experiments.bigcode_r2.adapter import BigCodeBenchTaskAdapter
        return BigCodeBenchTaskAdapter()
    if rp == "ds1000":
        from experiments.actionable_memory_r3.service_adapter import DS1000TaskAdapter
        return DS1000TaskAdapter()
    return OfflineRepositoryProvider()


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
        repo_provider=_repo_provider(),
        artifacts=ArtifactService(_artifact_store()),
        index=QdrantIndex.from_env(INDEX_DIM),
        embedder=_embedder(),
        backend=_execution_backend(),
        sandbox=ControlledLocalSandbox(environment))
