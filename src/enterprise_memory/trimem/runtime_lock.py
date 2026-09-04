"""Frozen prompt, tool, parser, and compute-ceiling contract for all benchmark arms."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .accounting import canonical_bytes, sha256_bytes


DECOMPOSITION_PROMPT = """You decompose a coding task into evidence-grounded semantic subtasks.
Return strict JSON: {"subtasks":[{"id":str,"objective":str,"predicted_operation":str,
"depends_on":[str],"files":[str],"symbols":[str],"apis":[str],"errors":[str],
"tests":[str]}]}. A subtask must describe a concrete semantic operation or invariant;
ANALYZE/REPRODUCE/EDIT/VERIFY alone are workflow stages and are forbidden as objectives.
Use only the public task and repository snapshot supplied below. Never infer hidden tests or gold patches.
"""

SOLVE_PROMPT = """You are a repository coding agent. Work only on the ACTIVE semantic subtask.
Use one tool action per response and return strict JSON with exactly `tool` and `arguments`.
Use replace_text for modifications to an existing file. Use write_file only for a new file or an
intentionally complete small-file replacement. Never emit a full large existing file merely to
change a local span.
When new error, test, symbol, API, or invariant evidence reveals additional semantic work,
call revise_subtask_dag before completing the current node; do not use generic workflow-stage subtasks.
When the active subtask has evidence of completion, call complete_subtask with that evidence.
Memory is advisory: validate it against this repository/version and ignore it when stale or inapplicable.
Never claim test success without a returned tool result. Hidden tests and gold patches are unavailable.
"""

EXTRACTION_PROMPT = """Extract reusable experience from a completed source task.
Return strict JSON with `episode` and optional `semantic_candidate`. Generalize only from the public
instruction, observed tool evidence, applied patch, and pass/fail verdict supplied below. Do not invent
hidden-test content. A failed source may produce an episode but must set semantic_candidate to null.
Semantic fields: preconditions, operation, invariant, non_applicability, verification.
Also return applicability_scope as exactly EXACT_REPOSITORY or CROSS_REPOSITORY. Use
CROSS_REPOSITORY only when the rule contains no source-repository, path, symbol, API,
or version-specific literal and its non-applicability boundary is explicit.
"""

ACTION_PARSER = {
    "name": "trimem-strict-json-action-parser",
    "version": "1.0.0",
    "unknown_fields": "reject",
    "duplicate_json_keys": "reject",
}

TOOL_SCHEMA: tuple[Mapping[str, Any], ...] = (
    {"name": "list_files", "arguments": {}},
    {
        "name": "read_file",
        "arguments": {"path": "str", "start_line": "int|null", "max_lines": "int|null"},
        "optional_arguments": ["start_line", "max_lines"],
    },
    {"name": "search", "arguments": {"query": "str", "path": "str|null"}},
    {"name": "write_file", "arguments": {"path": "str", "content": "str"}},
    {
        "name": "replace_text",
        "arguments": {
            "path": "str",
            "expected_file_sha256": "lowercase sha256",
            "old_text": "str",
            "new_text": "str",
        },
        "execution": "existing editable UTF-8 file; exact hash; old_text occurs exactly once; atomic replacement; old/new combined <=48000 bytes",
    },
    {"name": "run_public_tests", "arguments": {}},
    {
        "name": "run_command",
        "arguments": {"argv": "list[str]", "cwd": "str|null", "timeout_seconds": "int|null"},
        "optional_arguments": ["cwd", "timeout_seconds"],
        "execution": "digest-pinned isolated task image; no host shell; network disabled",
    },
    {
        "name": "revise_subtask_dag",
        "arguments": {
            "reason": "str",
            "new_subtasks": "list[{id,objective,predicted_operation,depends_on,preconditions?,invariants?,files?,symbols?,apis?,errors?,tests?,required_memory_facets?}]",
            "dependency_additions": "list[{node_id,depends_on}]",
        },
        "execution": "task-local working graph only; at least one topology change; dependency order and acyclicity enforced",
    },
    {"name": "complete_subtask", "arguments": {"evidence": "str"}},
)


@dataclass(frozen=True)
class RuntimeLimits:
    max_agent_steps: int = 24
    max_steps_per_subtask: int = 8
    max_solve_calls: int = 24
    max_decomposition_calls: int = 1
    max_extraction_calls: int = 1
    max_output_tokens_per_solve: int = 16_384
    max_total_solve_output_tokens_per_task_arm: int = 49_152
    max_total_output_tokens_per_task_arm: int = 65_536
    max_output_tokens_decomposition: int = 8192
    max_output_tokens_extraction: int = 8192
    max_memory_injections: int = 3
    max_memory_context_bytes: int = 12_000

    def __post_init__(self) -> None:
        if any(value <= 0 for value in asdict(self).values()):
            raise ValueError("all runtime limits must be positive")


@dataclass(frozen=True)
class RuntimeLock:
    version: str = "trimem-agent-v1"
    decomposer_prompt: str = DECOMPOSITION_PROMPT
    solve_prompt: str = SOLVE_PROMPT
    extraction_prompt: str = EXTRACTION_PROMPT
    tool_schema: tuple[Mapping[str, Any], ...] = TOOL_SCHEMA
    action_parser: Mapping[str, Any] = field(default_factory=lambda: dict(ACTION_PARSER))
    limits: RuntimeLimits = field(default_factory=RuntimeLimits)

    @property
    def prompt_hashes(self) -> dict[str, str]:
        return {
            "decomposer_prompt": sha256_bytes(self.decomposer_prompt.encode("utf-8")),
            "solve_prompt": sha256_bytes(self.solve_prompt.encode("utf-8")),
            "extraction_prompt": sha256_bytes(self.extraction_prompt.encode("utf-8")),
        }

    @property
    def tool_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.tool_schema))

    @property
    def parser_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.action_parser))

    def to_manifest(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "prompt_hashes": self.prompt_hashes,
            "tool_hash": self.tool_hash,
            "parser_hash": self.parser_hash,
            "limits": asdict(self.limits),
        }

    @property
    def content_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.to_manifest()))


def assert_equal_arm_limits(locks: Mapping[str, RuntimeLock]) -> None:
    if set(locks) != {"M0", "M1", "M2"}:
        raise ValueError("expected exactly M0, M1, and M2 runtime locks")
    reference = locks["M0"].to_manifest()
    mismatches = sorted(arm for arm, lock in locks.items() if lock.to_manifest() != reference)
    if mismatches:
        raise ValueError(f"arm runtime lock mismatch: {mismatches}")
