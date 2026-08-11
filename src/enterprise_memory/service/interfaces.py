"""Service interfaces (§3) as typing Protocols. Concrete local/test implementations live in
`providers_local`; staging/production adapters (Postgres, Mem0/Qdrant, S3, OIDC, GitHub App, Kubernetes)
are separate modules that must satisfy these Protocols. Keeping these as Protocols lets `create_app`
inject any conforming implementation without the production code depending on a concrete backend."""
from __future__ import annotations
from typing import Protocol, Any, Optional, runtime_checkable


@runtime_checkable
class Registry(Protocol):
    def get_contract(self, contract_id: str) -> Optional[dict]: ...
    def put_contract(self, contract: Any) -> str: ...
    def list_contracts(self, org_id: str | None = None, state: str | None = None) -> list: ...


@runtime_checkable
class MemoryIndex(Protocol):
    """A retrieval index (private or shared). Returns canonical IDs only — never authoritative text."""
    def add_view(self, scope_id: str, memory_id: str, text: str, metadata: dict) -> None: ...
    def search(self, scope_id: str, query: str, k: int, filters: dict) -> list: ...


class PrivateMemoryIndex(MemoryIndex, Protocol): ...
class SharedMemoryIndex(MemoryIndex, Protocol): ...


@runtime_checkable
class ArtifactStore(Protocol):
    def put(self, tenant_id: str, key: str, data: bytes, retention_class: str = "default") -> str: ...
    def get(self, tenant_id: str, key: str) -> bytes: ...


@runtime_checkable
class IdentityProvider(Protocol):
    def authenticate(self, authorization_header: str | None) -> "Any": ...   # -> IdentityContext


@runtime_checkable
class RepositoryAuthorizationProvider(Protocol):
    def can_read(self, ident: Any, repo_id: str) -> bool: ...
    def can_modify(self, ident: Any, repo_id: str) -> bool: ...
    def readable_repos(self, ident: Any) -> list: ...


@runtime_checkable
class RepositoryProvider(Protocol):
    def resolve_commit(self, repo_id: str, ref: str) -> str: ...
    def snapshot(self, repo_id: str, commit_sha: str, path_allowlist: list) -> dict: ...


@runtime_checkable
class CodingModelProvider(Protocol):
    def generate(self, logical_request_id: str, prompt: str) -> dict: ...   # {text, usage, latency_ms, ...}


@runtime_checkable
class SandboxProvider(Protocol):
    def run(self, snapshot: dict, patch_files: dict, test_entry: str, timeout_s: int) -> dict: ...


@runtime_checkable
class JobRepository(Protocol):
    def create(self, spec: dict, idempotency_key: str | None = None) -> dict: ...
    def claim(self, worker_id: str) -> Optional[dict]: ...
    def transition(self, job_id: str, to_state: str, detail: dict | None = None) -> dict: ...
    def get(self, job_id: str) -> Optional[dict]: ...


@runtime_checkable
class AuditSink(Protocol):
    def emit(self, event_type: str, actor: str, subject: str, detail: dict) -> str: ...


@runtime_checkable
class MetricsSink(Protocol):
    def incr(self, name: str, value: int = 1, tags: dict | None = None) -> None: ...
    def observe(self, name: str, value: float, tags: dict | None = None) -> None: ...
