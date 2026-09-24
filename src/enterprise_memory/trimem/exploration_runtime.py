"""Opt-in exploration guidance shared by all arms of a bounded diagnostic.

Budgets come from the same accounting that enforces the runtime limits.  No
second mutable tracker is needed: checkpoint recovery reconstructs both the
budget and duplicate observations from authenticated accounting/tool history.
The original runtime and its tool execution semantics remain unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from typing import Any, Mapping, Sequence

from .accounting import canonical_bytes, sha256_bytes
from .agent_runtime import CellScientificFailure, TriMemAgentRuntime
from .checkpoint import CheckpointMismatch
from .context_projection import MAX_SOLVE_PROMPT_UTF8_BYTES, bounded_text_record
from .skill_runtime import SkhynixAgentRuntime


_READ_TOOLS = frozenset({"read_file", "search", "list_files"})
_GRAPH_ONLY_TOOLS = frozenset({"complete_subtask", "revise_subtask_dag"})
_GUIDANCE = (
    "Every solve model call consumes one action allowance, including invalid "
    "arguments and unsuccessful tool executions. The remaining counts include "
    "the action you are selecting now. Other model/input/output budget limits "
    "can stop execution earlier.",
    "Use targeted searches, then read relevant hits and implement the grounded "
    "change. Reserve the indicated final actions for the necessary edit, a "
    "focused test, and complete_subtask. This is planning guidance; do not skip "
    "required investigation or claim unsupported success.",
    "If a repeated observation warning appears, use a different query or page, "
    "read a relevant hit, or implement the change supported by the observations. "
    "Complete a semantic subtask only when returned evidence supports completion. "
    "A failed test is evidence to investigate, not proof of success.",
)


@dataclass(frozen=True)
class ExplorationPolicy:
    """Hash-bound advisory behavior; compute ceilings live in RuntimeLock."""

    reserve_final_actions: int = 4
    repetition_threshold: int = 2
    max_repeat_warnings: int = 4

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.repetition_threshold < 2:
            raise ValueError("repetition_threshold must be at least two")
        if self.max_repeat_warnings > 16:
            raise ValueError("max_repeat_warnings must be at most sixteen")

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": "trimem/exploration-policy/1.0",
            **asdict(self),
            "guidance": list(_GUIDANCE),
            "counting": "accounted_solve_calls_all_statuses_including_current_allowance",
            "adaptive_horizon": "disabled_required",
            "repetition": {
                "tools": sorted(_READ_TOOLS),
                "identity": "exact_canonical_request_and_result",
                "status": "success_only",
                "epoch_reset": "any_tool_except_reads_and_graph_only_tools_regardless_of_status",
                "observed_result_change": "reset_all_observation_counts",
                "action": "advisory_only_no_tool_suppression",
                "argument_preview_utf8_bytes": 512,
            },
        }

    @property
    def content_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.manifest()))


def repeated_observation_summary(
    history: Sequence[Mapping[str, Any]], policy: ExplorationPolicy,
) -> dict[str, Any]:
    """Conservative duplicate detection, including across subtask transitions.

    Tests and commands may modify files even when they fail, so any such attempt
    clears all remembered reads. A changed result for the same request also
    starts a new epoch. We never suppress a tool or reuse a fabricated result.
    """
    seen: dict[str, dict[str, Any]] = {}
    epoch_start_step = 0
    successful_reads = 0
    for row in history:
        tool = row.get("tool")
        if tool not in _READ_TOOLS:
            if tool not in _GRAPH_ONLY_TOOLS:
                seen.clear()
                successful_reads = 0
                epoch_start_step = int(row["step_no"])
            continue
        if row.get("status") != "success":
            continue
        request = row["request_payload"]
        request_hash = sha256_bytes(canonical_bytes(request))
        result_hash = sha256_bytes(canonical_bytes(row["result_payload"]))
        previous = seen.get(request_hash)
        if previous is not None and previous["result_sha256"] != result_hash:
            seen.clear()
            successful_reads = 0
            epoch_start_step = int(row["step_no"])
            previous = None
        successful_reads += 1
        if previous is None:
            previous = {
                "tool": tool,
                "request_sha256": request_hash,
                "result_sha256": result_hash,
                "argument_preview": bounded_text_record(
                    canonical_bytes(request["arguments"]).decode("utf-8"), maximum=512,
                ),
                "first_step": int(row["step_no"]),
                "successful_execution_count": 0,
            }
            seen[request_hash] = previous
        previous["successful_execution_count"] += 1
        previous["last_step"] = int(row["step_no"])
        previous["last_active_node_id"] = row["active_node_id"]
    repeated = sorted(
        (value for value in seen.values()
         if value["successful_execution_count"] >= policy.repetition_threshold),
        key=lambda value: (-value["last_step"], value["request_sha256"]),
    )
    return {
        "epoch_start_step": epoch_start_step,
        "successful_read_executions_in_epoch": successful_reads,
        "repeated_request_count": len(repeated),
        "extra_identical_read_executions": sum(
            value["successful_execution_count"] - 1 for value in seen.values()
        ),
        "warnings": repeated[:policy.max_repeat_warnings],
        "omitted_warning_count": max(0, len(repeated) - policy.max_repeat_warnings),
        "scope": "successful_exact_requests_and_results_since_possible_mutation",
    }


class ExplorationRuntimeMixin:
    """Place before either runtime in the MRO to augment its final solve request."""

    def __init__(self, *, exploration_policy: ExplorationPolicy | None = None, **kwargs):
        self.exploration_policy = ExplorationPolicy() if exploration_policy is None else exploration_policy
        if not isinstance(self.exploration_policy, ExplorationPolicy):
            raise TypeError("exploration_policy must be ExplorationPolicy")
        if kwargs["runtime_lock"].adaptive_horizon.enabled:
            raise ValueError("exploration guidance requires adaptive horizon disabled")
        super().__init__(**kwargs)

    def _configuration_hashes(self, task):
        hashes = super()._configuration_hashes(task)
        hashes["exploration_policy"] = self.exploration_policy.content_hash
        return hashes

    @staticmethod
    def _solve_context_identity(task, graph, history, injections):
        injection_rows = []
        for item in injections:
            fields = asdict(item)
            fields["kind"] = item.kind.value
            fields["exact_utf8"] = item.exact_utf8.hex()
            injection_rows.append(fields)
        return sha256_bytes(canonical_bytes({
            "task": task.public_payload(), "org_id": task.org_id, "user_id": task.user_id,
            "graph": graph.snapshot(), "history": history,
            "injections": injection_rows,
        }))

    def _solve_prompt(self, task, graph, history, injections):
        # The frozen recovery loop invokes this older, accounting-free hook
        # after _build_solve_request has already reconstructed and verified the
        # RECALL_PREPARED binding. Reuse only that exact context's full prompt.
        # We cannot derive truthful counters from tool history (errors and
        # incomplete model/tool crash windows have different row counts).
        prepared = getattr(self, "_exploration_prepared_prompt", None)
        identity = self._solve_context_identity(task, graph, history, injections)
        if prepared is None or prepared[0] != identity:
            raise CheckpointMismatch("exploration solve prompt requires the exact prepared context")
        return prepared[1]

    def _build_solve_request(self, task, arm, graph, history, injections, accounting, next_step):
        request, projection = super()._build_solve_request(
            task, arm, graph, history, injections, accounting, next_step,
        )
        node = graph.active_node
        solve = [call for call in accounting.calls if call.call_kind == "solve"]
        node_used = sum(call.active_node_id == node.node_id for call in solve)
        limits = self.lock.limits
        task_left = max(0, limits.max_solve_calls - len(solve))
        node_left = max(0, limits.max_steps_per_subtask - node_used)
        step_left = max(0, limits.max_agent_steps - next_step + 1)
        effective_left = min(task_left, node_left, step_left)
        guidance = {
            "schema": "trimem/exploration-guidance/1.0",
            "policy_sha256": self.exploration_policy.content_hash,
            "budget": {
                "active_node_id": node.node_id,
                "next_step_no": next_step,
                "task_solve_calls_used": len(solve),
                "task_solve_call_limit": limits.max_solve_calls,
                "task_solve_calls_remaining": task_left,
                "active_subtask_solve_calls_used": node_used,
                "active_subtask_solve_call_limit": limits.max_steps_per_subtask,
                "active_subtask_solve_calls_remaining": node_left,
                "global_step_limit": limits.max_agent_steps,
                "global_steps_remaining": step_left,
                "effective_active_subtask_actions_remaining": effective_left,
                "remaining_counts_include_current_action": True,
                "adaptive_extension_enabled": False,
                "solve_output_tokens_remaining": max(0,
                    limits.max_total_solve_output_tokens_per_task_arm
                    - sum(int(call.output_tokens or 0) for call in solve)),
                "suggested_final_actions_to_reserve": min(
                    self.exploration_policy.reserve_final_actions, effective_left,
                ),
                "final_action_reserve_reached": (
                    effective_left <= self.exploration_policy.reserve_final_actions
                ),
            },
            "repetition": repeated_observation_summary(history, self.exploration_policy),
            "guidance": list(_GUIDANCE),
        }
        prefix, payload = request.prompt.rsplit("\n\nSTATE:\n", 1)
        body = json.loads(payload)
        body["exploration_guidance"] = guidance
        prompt = self._json_prompt(prefix, "\n\nSTATE:\n", body)
        raw = prompt.encode("utf-8")
        if len(raw) > MAX_SOLVE_PROMPT_UTF8_BYTES:
            raise CellScientificFailure("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED")
        # projection_sha256 continues to identify the unchanged history/context
        # projection. The added advisory has its own hash, while final_prompt_*
        # binds the actual full provider input, including this advisory.
        record = {
            **projection,
            "final_prompt_bytes": len(raw),
            "final_prompt_sha256": sha256_bytes(raw),
            "exploration_policy_sha256": self.exploration_policy.content_hash,
            "exploration_guidance_bytes": len(canonical_bytes(guidance)),
            "exploration_guidance_sha256": sha256_bytes(canonical_bytes(guidance)),
        }
        self._exploration_prepared_prompt = (
            self._solve_context_identity(task, graph, history, injections), prompt,
        )
        return replace(request, prompt=prompt, prompt_projection=record), record


class ExplorationTriMemAgentRuntime(ExplorationRuntimeMixin, TriMemAgentRuntime):
    """Baseline/original memory runtime with bounded exploration guidance."""


class ExplorationSkhynixAgentRuntime(ExplorationRuntimeMixin, SkhynixAgentRuntime):
    """SK hynix subgoal context with identical exploration guidance."""
