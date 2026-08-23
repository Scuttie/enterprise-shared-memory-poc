"""§2.1 server-owned task execution policy. The client may submit only a repository id, a task id, a
natural-language request, and an optional desired ref. Everything security-relevant (editable paths,
target symbol, exact signature, test command/bundle, line budget, timeout, runtime) is resolved
server-side by TaskPolicyRepository AFTER authentication + repository authorization. Client-supplied
authoritative fields are ignored/rejected."""
from __future__ import annotations
from dataclasses import dataclass, field

# fields a client is NOT allowed to dictate (silently ignored if present, and flagged)
CLIENT_FORBIDDEN_FIELDS = ("target_file", "test_entry", "hidden_test_path", "path_allowlist",
                           "signature", "func", "writable_paths", "sandbox_command", "test_command")


class PolicyError(Exception):
    pass


@dataclass
class TaskExecutionPolicy:
    repo_id: str
    task_id: str
    editable_paths: list            # server-owned allowlist
    target_file: str
    target_symbol: str
    exact_signature: str
    test_entry: str                 # hidden-test bundle reference (server-owned)
    public_test_command: str = "python -m pytest -q"
    max_changed_lines: int = 12
    timeout_s: int = 20
    language: str = "python"
    allowed_refs: tuple = ("main",)


@dataclass
class ClientTaskRequest:
    """The ONLY authoritative client input."""
    repo_id: str
    task_id: str
    instruction: str
    desired_ref: str = "main"
    ignored_client_fields: list = field(default_factory=list)

    @classmethod
    def from_body(cls, body: dict) -> "ClientTaskRequest":
        ignored = [k for k in CLIENT_FORBIDDEN_FIELDS if k in body]
        return cls(repo_id=body["repo_id"], task_id=body["task_id"], instruction=body.get("instruction", ""),
                   desired_ref=body.get("desired_ref", "main"), ignored_client_fields=ignored)


class LocalTaskPolicyRepository:
    """Test/local policy source. Production = a Postgres task_execution_policies table."""

    def __init__(self, policies: dict):
        self._p = policies          # (repo_id, task_id) -> TaskExecutionPolicy

    async def resolve(self, req: ClientTaskRequest, authorized_repo: bool) -> TaskExecutionPolicy:
        if not authorized_repo:
            raise PolicyError("repo_not_authorized")
        pol = self._p.get((req.repo_id, req.task_id))
        if pol is None:
            raise PolicyError("no_policy_for_task")
        if req.desired_ref not in pol.allowed_refs:
            raise PolicyError("ref_not_allowed:%s" % req.desired_ref)
        return pol
