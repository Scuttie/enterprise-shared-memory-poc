"""Credential-free in-memory repository tools used by the shared agent loop."""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import posixpath
import time
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable

from .accounting import RawEvidenceLedger, RunAccounting, ToolRecord, canonical_bytes, sha256_bytes


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicTestResult:
    passed: bool
    stdout: str
    stderr: str = ""
    exit_code: int = 0


@dataclass(frozen=True)
class PublicCommandResult:
    """Bounded public output from an isolated repository command."""

    exit_code: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False
    output_truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.exit_code, int):
            raise ValueError("command exit_code must be an integer")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ValueError("command stdout/stderr must be text")


@runtime_checkable
class SandboxCommandRunner(Protocol):
    """Runs argv without a host shell inside a separately locked sandbox."""

    content_hash: str

    def run(
        self,
        root: Any,
        argv: tuple[str, ...],
        *,
        cwd: Optional[str],
        timeout_seconds: int,
    ) -> PublicCommandResult: ...


@dataclass(frozen=True)
class WorkspaceGraderContext:
    """Repository material available to a grader, never to the model prompt."""

    kind: str
    repository_files: Mapping[str, str]
    checkout_root: Optional[str] = None
    base_commit: Optional[str] = None


@runtime_checkable
class RepositoryWorkspace(Protocol):
    """Stateful repository/tool boundary shared by replay and real checkouts."""

    @property
    def tool_names(self) -> frozenset[str]: ...

    def execute(self, tool: str, arguments: dict) -> dict: ...

    def patch(self) -> str: ...

    def checkpoint_state(self) -> Mapping[str, Any]: ...

    def restore_checkpoint(self, state: Mapping[str, Any]) -> None: ...

    def grader_context(self, *, base_commit: str) -> WorkspaceGraderContext: ...


@runtime_checkable
class WorkspaceFactory(Protocol):
    """Factory identity is included in every runtime checkpoint/config lock."""

    content_hash: str
    production_capable: bool

    def __call__(self, task: Any) -> RepositoryWorkspace: ...


class InMemoryWorkspaceFactory:
    """Credential-free factory. Benchmark orchestration must reject this type."""

    production_capable = False
    content_hash = sha256_bytes(
        canonical_bytes({
            "factory": "trimem-in-memory-workspace-v1",
            "tool_names": sorted({
                "list_files", "read_file", "search", "write_file",
                "run_public_tests", "run_command", "revise_subtask_dag", "complete_subtask",
            }),
        })
    )

    def __call__(self, task: Any) -> "InMemoryRepositoryWorkspace":
        if not task.files or not task.editable_paths:
            raise ToolExecutionError("in-memory workspace requires seeded files and editable paths")
        return InMemoryRepositoryWorkspace(
            task.files,
            editable_paths=tuple(task.editable_paths),
            public_test=task.public_test,
        )


class InMemoryRepositoryWorkspace:
    """A multi-file workspace with no hidden-test or gold-patch surface."""

    TOOL_NAMES = {
        "list_files",
        "read_file",
        "search",
        "write_file",
        "run_public_tests",
        "run_command",
        "revise_subtask_dag",
        "complete_subtask",
    }

    def __init__(
        self,
        files: Mapping[str, str],
        *,
        editable_paths: tuple[str, ...],
        public_test: Optional[Callable[[Mapping[str, str]], PublicTestResult]] = None,
    ):
        self.original_files = {_safe_path(path): value for path, value in files.items()}
        self.files = dict(self.original_files)
        self.editable_paths = tuple(_safe_path(path) for path in editable_paths)
        self.public_test = public_test

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(self.TOOL_NAMES)

    def execute(self, tool: str, arguments: dict) -> dict:
        if tool not in self.TOOL_NAMES:
            raise ToolExecutionError("unknown tool")
        if tool == "list_files":
            _exact_arguments(arguments, set())
            return {"files": sorted(self.files)}
        if tool == "read_file":
            _optional_arguments(arguments, {"path"}, {"start_line", "max_lines"})
            path = _safe_path(arguments["path"])
            if path not in self.files:
                raise ToolExecutionError("file not found")
            return _line_window(path, self.files[path], arguments)
        if tool == "search":
            if set(arguments) not in ({"query"}, {"query", "path"}):
                raise ToolExecutionError("search expects query and optional path")
            query = arguments["query"]
            if not isinstance(query, str) or not query:
                raise ToolExecutionError("search query must be non-empty")
            requested = arguments.get("path")
            paths = [_safe_path(requested)] if requested is not None else sorted(self.files)
            hits = []
            for path in paths:
                if path not in self.files:
                    raise ToolExecutionError("search path not found")
                for line_no, line in enumerate(self.files[path].splitlines(), 1):
                    if query in line:
                        hits.append({"path": path, "line": line_no, "text": line})
            return {"query": query, "hits": hits}
        if tool == "write_file":
            _exact_arguments(arguments, {"path", "content"})
            path = _safe_path(arguments["path"])
            content = arguments["content"]
            if path not in self.editable_paths:
                raise ToolExecutionError("path is not editable")
            if not isinstance(content, str):
                raise ToolExecutionError("content must be text")
            self.files[path] = content
            return {"path": path, "content_hash": sha256_bytes(content.encode()), "bytes": len(content.encode())}
        if tool == "run_public_tests":
            _exact_arguments(arguments, set())
            if self.public_test is None:
                return {"passed": False, "exit_code": 2, "stdout": "", "stderr": "public test unavailable"}
            result = self.public_test(dict(self.files))
            return {
                "passed": result.passed,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        if tool == "run_command":
            _optional_arguments(arguments, {"argv"}, {"cwd", "timeout_seconds"})
            # Credential-free replay deliberately has no process or shell.  Its
            # public-test fixture exercises the same model/tool/accounting
            # boundary.  A production-capable factory must inject a locked
            # SandboxCommandRunner and is verified separately.
            _validated_command_arguments(arguments)
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": "isolated command runner unavailable in in-memory replay",
                "timed_out": False,
                "output_truncated": False,
            }
        if tool == "revise_subtask_dag":
            return _validated_dag_revision_arguments(arguments)
        if tool == "complete_subtask":
            _exact_arguments(arguments, {"evidence"})
            evidence = arguments["evidence"]
            if not isinstance(evidence, str) or not evidence.strip():
                raise ToolExecutionError("completion evidence must be non-empty")
            return {"completed": True, "evidence": evidence.strip()}
        raise AssertionError("unreachable")

    def patch(self) -> str:
        pieces: list[str] = []
        for path in sorted(set(self.original_files) | set(self.files)):
            old = self.original_files.get(path, "")
            new = self.files.get(path, "")
            if old == new:
                continue
            pieces.extend(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        return "".join(pieces)

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {
            "kind": "trimem-in-memory-workspace-v1",
            "files": dict(sorted(self.files.items())),
        }

    def restore_checkpoint(self, state: Mapping[str, Any]) -> None:
        if set(state) != {"kind", "files"} or state.get("kind") != "trimem-in-memory-workspace-v1":
            raise ToolExecutionError("in-memory workspace checkpoint kind/shape mismatch")
        files = state.get("files")
        if not isinstance(files, Mapping):
            raise ToolExecutionError("workspace checkpoint files are invalid")
        normalized = {_safe_path(path): content for path, content in files.items()}
        if any(not isinstance(content, str) for content in normalized.values()):
            raise ToolExecutionError("workspace checkpoint contains non-text content")
        if not set(normalized) <= set(self.original_files) | set(self.editable_paths):
            raise ToolExecutionError("workspace checkpoint contains an unauthorized path")
        self.files = normalized

    def grader_context(self, *, base_commit: str) -> WorkspaceGraderContext:
        return WorkspaceGraderContext(
            kind="in_memory",
            repository_files=dict(self.files),
            checkout_root=None,
            base_commit=base_commit,
        )


class RecordingToolExecutor:
    def __init__(
        self,
        workspace: RepositoryWorkspace,
        accounting: RunAccounting,
        evidence: RawEvidenceLedger,
        *,
        task_id: str,
        arm: str,
    ):
        self.workspace = workspace
        self.accounting = accounting
        self.evidence = evidence
        self.task_id = task_id
        self.arm = arm
        self.history: list[dict] = []

    def execute(self, step_no: int, active_node_id: str, tool: str, arguments: dict) -> dict:
        request = {"tool": tool, "arguments": arguments}
        request_ref = self.evidence.put_blob(request)
        start = time.perf_counter_ns()
        status = "success"
        try:
            result = self.workspace.execute(tool, arguments)
        except Exception as exc:
            status = "error"
            result = {"error": type(exc).__name__, "message": str(exc)}
        wall_ms = max(0, (time.perf_counter_ns() - start) // 1_000_000)
        result_ref = self.evidence.put_blob(result)
        record = ToolRecord(
            task_id=self.task_id,
            arm=self.arm,
            step_no=step_no,
            active_node_id=active_node_id,
            tool_name=tool,
            request_hash=request_ref["sha256"],
            result_hash=result_ref["sha256"],
            wall_time_ms=wall_ms,
            status=status,
        )
        self.accounting.add_tool(record)
        evidence_event = {
            "task_id": self.task_id,
            "arm": self.arm,
            "step_no": step_no,
            "active_node_id": active_node_id,
            "tool": tool,
            "request": request_ref,
            "result": result_ref,
            "wall_time_ms": wall_ms,
            "status": status,
        }
        # The next model step must see the actual public tool observation, not
        # only its evidence hash.  Hidden grader material never crosses this
        # workspace boundary.  The append-only ledger remains reference-only
        # while the checkpointed working history carries the exact public data.
        self.history.append({
            **evidence_event,
            "request_payload": request,
            "result_payload": result,
        })
        self.evidence.append("tool_result", evidence_event)
        return result


def _safe_path(path: object) -> str:
    if not isinstance(path, str) or not path or "\\" in path:
        raise ToolExecutionError("invalid repository path")
    normalized = posixpath.normpath(path)
    if normalized in (".", "..") or normalized.startswith("../") or normalized.startswith("/"):
        raise ToolExecutionError("path traversal refused")
    return normalized


def _exact_arguments(arguments: object, expected: set[str]) -> None:
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ToolExecutionError(f"arguments must be exactly {sorted(expected)}")


def _optional_arguments(arguments: object, required: set[str], optional: set[str]) -> None:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("arguments must be an object")
    keys = set(arguments)
    if not required <= keys or keys - required - optional:
        raise ToolExecutionError(
            f"arguments require {sorted(required)} and allow only {sorted(optional)} as optional"
        )


def _validated_command_arguments(arguments: Mapping[str, Any]) -> tuple[tuple[str, ...], Optional[str], int]:
    argv = arguments.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or len(argv) > 64
        or any(not isinstance(item, str) or not item or "\x00" in item for item in argv)
        or sum(len(item.encode("utf-8")) for item in argv) > 32_768
    ):
        raise ToolExecutionError("argv must be 1..64 non-empty strings within 32768 UTF-8 bytes")
    cwd = arguments.get("cwd")
    if cwd in (".", "./"):
        cwd = None
    elif cwd is not None:
        cwd = _safe_path(cwd)
    timeout = arguments.get("timeout_seconds", 120)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
        raise ToolExecutionError("timeout_seconds must be an integer in 1..120")
    return tuple(argv), cwd, timeout


def _validated_dag_revision_arguments(arguments: object) -> dict[str, Any]:
    """Validate the model-requested topology delta without owning graph state.

    Workspaces expose the frozen tool surface, while ``TriMemAgentRuntime`` is
    the sole owner of the task-local graph and applies this normalized delta.
    Keeping validation here makes replay and Git checkout workspaces byte-for-
    byte equivalent at the tool boundary.
    """

    if not isinstance(arguments, dict) or set(arguments) != {
        "reason", "new_subtasks", "dependency_additions",
    }:
        raise ToolExecutionError(
            "revise_subtask_dag requires exactly reason, new_subtasks, and dependency_additions"
        )
    reason = arguments.get("reason")
    rows = arguments.get("new_subtasks")
    additions = arguments.get("dependency_additions")
    if not isinstance(reason, str) or not reason.strip() or len(reason.encode("utf-8")) > 4096:
        raise ToolExecutionError("DAG revision reason must be non-empty and at most 4096 UTF-8 bytes")
    if not isinstance(rows, list) or not isinstance(additions, list) or not rows and not additions:
        raise ToolExecutionError("DAG revision must contain at least one topology change")
    if len(rows) > 16 or len(additions) > 32:
        raise ToolExecutionError("DAG revision exceeds the frozen topology delta cap")

    required = {"id", "objective", "predicted_operation", "depends_on"}
    optional = {
        "preconditions", "invariants", "files", "symbols", "apis", "errors", "tests",
        "required_memory_facets",
    }
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional:
            raise ToolExecutionError("invalid new semantic subtask shape")
        if any(not isinstance(row[name], str) or not row[name].strip() for name in (
            "id", "objective", "predicted_operation",
        )):
            raise ToolExecutionError("semantic subtask id/objective/operation must be non-empty strings")
        normalized: dict[str, Any] = {
            "id": row["id"].strip(),
            "objective": row["objective"].strip(),
            "predicted_operation": row["predicted_operation"].strip(),
        }
        for name in ("depends_on", *sorted(optional)):
            value = row.get(name, [])
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item.strip() for item in value)
                or len(value) > 64
            ):
                raise ToolExecutionError(f"semantic subtask {name} must be a bounded string list")
            normalized[name] = [item.strip() for item in value]
        normalized_rows.append(normalized)

    normalized_additions: list[dict[str, str]] = []
    for row in additions:
        if (
            not isinstance(row, dict)
            or set(row) != {"node_id", "depends_on"}
            or any(not isinstance(row[name], str) or not row[name].strip() for name in row)
        ):
            raise ToolExecutionError("invalid dependency addition shape")
        normalized_additions.append({
            "node_id": row["node_id"].strip(),
            "depends_on": row["depends_on"].strip(),
        })
    return {
        "dag_revised": True,
        "reason": reason.strip(),
        "new_subtasks": normalized_rows,
        "dependency_additions": normalized_additions,
    }


def _line_window(path: str, content: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    start = arguments.get("start_line", 1)
    maximum = arguments.get("max_lines", 400)
    if isinstance(start, bool) or not isinstance(start, int) or start < 1:
        raise ToolExecutionError("start_line must be a positive integer")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 2000:
        raise ToolExecutionError("max_lines must be an integer in 1..2000")
    lines = content.splitlines(keepends=True)
    selected = "".join(lines[start - 1:start - 1 + maximum])
    return {
        "path": path,
        "content": selected,
        "start_line": start,
        "end_line": start + len(lines[start - 1:start - 1 + maximum]) - 1,
        "total_lines": len(lines),
        "truncated": start - 1 + maximum < len(lines),
    }
