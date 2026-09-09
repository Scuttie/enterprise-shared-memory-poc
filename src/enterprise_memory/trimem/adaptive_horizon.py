"""Deterministic, checkpointable per-subtask horizon extensions.

The legacy agent always stops a subtask at ``max_steps_per_subtask``.  A
diagnostic run may opt into this tracker to grant two four-step extensions,
but only after durable, non-repeated repository or test progress.  The state
is JSON-shaped so it can be carried inside the existing authenticated runtime
checkpoint without creating a second recovery surface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ntpath
from typing import Any, Mapping, Optional

from .accounting import canonical_bytes, sha256_bytes


ADAPTIVE_HORIZON_SCHEMA = "trimem/adaptive-horizon-state/1.0"
ADAPTIVE_HORIZON_TERMINAL_KEY = "adaptive_horizon"


@dataclass(frozen=True)
class AdaptiveHorizonPolicy:
    """Frozen opt-in contract; disabled preserves historical behavior."""

    enabled: bool = False
    extension_steps: int = 4
    maximum_steps_per_subtask: int = 16
    maximum_extensions_per_subtask: int = 2

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("adaptive horizon enabled must be boolean")
        if (
            type(self.extension_steps) is not int
            or type(self.maximum_steps_per_subtask) is not int
            or type(self.maximum_extensions_per_subtask) is not int
            or self.extension_steps <= 0
            or self.maximum_steps_per_subtask <= 0
            or self.maximum_extensions_per_subtask <= 0
        ):
            raise ValueError("adaptive horizon limits must be positive integers")

    def manifest(self, *, base_steps_per_subtask: int) -> dict[str, Any]:
        return {
            **asdict(self),
            "base_steps_per_subtask": base_steps_per_subtask,
            "progress_contract_sha256": ADAPTIVE_PROGRESS_CONTRACT_SHA256,
        }


# This declarative record is hashed into an enabled runtime lock.  It keeps the
# meaning of "recognized test command" reviewable instead of relying on a
# platform-specific shell parser.
ADAPTIVE_PROGRESS_CONTRACT = {
    "schema": "trimem/adaptive-horizon-progress-contract/1.0",
    "observation_boundary": "successful_tool_result_only",
    "patch_progress": "canonical_git_diff_utf8_byte_high_water_strictly_increases",
    "test_progress": "recognized_test_command_changes_task_test_high_water_to_pass",
    "repeated_identical_progress": "does_not_extend",
    "extension_requires": "unconsumed_progress_since_previous_extension",
    "recognized_commands": [
        "run_public_tests",
        "pytest|py.test [args]",
        "python|python3|py -m pytest|unittest [args]",
        "tox|nox [args]",
        "go test [args]",
        "cargo test|nextest [args]",
        "npm|pnpm|yarn|bun test [args]",
        "npm|pnpm|yarn|bun run test|test:* [args]",
        "mvn|mvnw test|verify [args]",
        "gradle|gradlew test|check|*:test|*:check [args]",
        "dotnet test [args]",
        "rspec [args]",
        "bundle exec rspec [args]",
        "make test|check [args]",
    ],
}
ADAPTIVE_PROGRESS_CONTRACT_SHA256 = sha256_bytes(
    canonical_bytes(ADAPTIVE_PROGRESS_CONTRACT)
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _command_name(value: str) -> str:
    return ntpath.basename(value).casefold().removesuffix(".exe")


def recognized_test_command(arguments: Mapping[str, Any]) -> bool:
    """Return whether one shell-free ``run_command`` argv is test-shaped."""

    argv = arguments.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
    ):
        return False
    command = _command_name(argv[0])
    lowered = [item.casefold() for item in argv]
    if command in {"pytest", "py.test", "tox", "nox", "rspec"}:
        return True
    if command in {"python", "python3", "py"}:
        return len(lowered) >= 3 and lowered[1] == "-m" and lowered[2] in {
            "pytest", "unittest",
        }
    if command == "go":
        return len(lowered) >= 2 and lowered[1] == "test"
    if command == "cargo":
        return len(lowered) >= 2 and lowered[1] in {"test", "nextest"}
    if command in {"npm", "pnpm", "yarn", "bun"}:
        if len(lowered) >= 2 and lowered[1] == "test":
            return True
        return (
            len(lowered) >= 3
            and lowered[1] == "run"
            and (lowered[2] == "test" or lowered[2].startswith("test:"))
        )
    if command in {"mvn", "mvnw"}:
        return any(item in {"test", "verify"} for item in lowered[1:])
    if command in {"gradle", "gradlew"}:
        return any(
            item in {"test", "check"}
            or item.endswith(":test")
            or item.endswith(":check")
            for item in lowered[1:]
        )
    if command == "dotnet":
        return len(lowered) >= 2 and lowered[1] == "test"
    if command == "bundle":
        return len(lowered) >= 3 and lowered[1:3] == ["exec", "rspec"]
    if command == "make":
        return any(item in {"test", "check"} for item in lowered[1:])
    return False


def _successful_test_identity(
    tool: str,
    arguments: Mapping[str, Any],
    result: Mapping[str, Any],
) -> Optional[str]:
    if tool == "run_public_tests":
        if result.get("passed") is not True:
            return None
        identity = {"tool": tool, "arguments": {}}
    elif tool == "run_command":
        if (
            not recognized_test_command(arguments)
            or type(result.get("exit_code")) is not int
            or result.get("exit_code") != 0
            or result.get("timed_out") is True
        ):
            return None
        identity = {
            "tool": tool,
            "argv": list(arguments["argv"]),
            "cwd": arguments.get("cwd"),
        }
    else:
        return None
    return sha256_bytes(canonical_bytes(identity))


class AdaptiveHorizonTracker:
    """Mutable runtime view with strict JSON checkpoint serialization."""

    _NODE_FIELDS = {
        "current_step_limit",
        "extension_count",
        "latest_progress_ordinal",
        "consumed_progress_ordinal",
    }
    _STATE_FIELDS = {
        "schema",
        "base_steps_per_subtask",
        "extension_steps",
        "maximum_steps_per_subtask",
        "maximum_extensions_per_subtask",
        "patch_bytes_high_water",
        "test_status_high_water",
        "progress_events",
        "extension_events",
        "nodes",
    }

    def __init__(
        self,
        policy: AdaptiveHorizonPolicy,
        *,
        base_steps_per_subtask: int,
        checkpoint_state: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.policy = policy
        self.base_steps = base_steps_per_subtask
        if checkpoint_state is None:
            self._state: dict[str, Any] = {
                "schema": ADAPTIVE_HORIZON_SCHEMA,
                "base_steps_per_subtask": base_steps_per_subtask,
                "extension_steps": policy.extension_steps,
                "maximum_steps_per_subtask": policy.maximum_steps_per_subtask,
                "maximum_extensions_per_subtask": (
                    policy.maximum_extensions_per_subtask
                ),
                "patch_bytes_high_water": 0,
                "test_status_high_water": 0,
                "progress_events": [],
                "extension_events": [],
                "nodes": {},
            }
        else:
            self._state = self._validate_and_copy(checkpoint_state)

    def _validate_and_copy(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if set(value) != self._STATE_FIELDS:
            raise ValueError("adaptive horizon checkpoint field set differs")
        expected = {
            "schema": ADAPTIVE_HORIZON_SCHEMA,
            "base_steps_per_subtask": self.base_steps,
            "extension_steps": self.policy.extension_steps,
            "maximum_steps_per_subtask": self.policy.maximum_steps_per_subtask,
            "maximum_extensions_per_subtask": (
                self.policy.maximum_extensions_per_subtask
            ),
        }
        if any(value.get(name) != expected_value for name, expected_value in expected.items()):
            raise ValueError("adaptive horizon checkpoint policy differs")
        for field_name in ("patch_bytes_high_water", "test_status_high_water"):
            if type(value.get(field_name)) is not int or value[field_name] < 0:
                raise ValueError("adaptive horizon checkpoint high-water is invalid")
        if value["test_status_high_water"] not in {0, 1}:
            raise ValueError("adaptive horizon test high-water is invalid")
        progress_events = value.get("progress_events")
        extension_events = value.get("extension_events")
        nodes = value.get("nodes")
        if not isinstance(progress_events, list) or not isinstance(extension_events, list):
            raise ValueError("adaptive horizon checkpoint events are invalid")
        if not isinstance(nodes, Mapping):
            raise ValueError("adaptive horizon checkpoint nodes are invalid")
        for index, row in enumerate(progress_events, 1):
            if not isinstance(row, Mapping) or row.get("ordinal") != index:
                raise ValueError("adaptive horizon progress evidence is invalid")
            kind = row.get("kind")
            required = {
                "ordinal", "kind", "step_no", "node_id",
                "patch_bytes", "patch_sha256",
            } if kind == "PATCH_DIFF_HIGH_WATER" else {
                "ordinal", "kind", "step_no", "node_id",
                "test_command_sha256", "status",
            }
            if (
                kind not in {"PATCH_DIFF_HIGH_WATER", "TEST_PASS_HIGH_WATER"}
                or set(row) != required
                or type(row.get("step_no")) is not int
                or row["step_no"] < 1
                or not isinstance(row.get("node_id"), str)
                or not row["node_id"]
            ):
                raise ValueError("adaptive horizon progress evidence is invalid")
            if kind == "PATCH_DIFF_HIGH_WATER":
                if (
                    type(row.get("patch_bytes")) is not int
                    or row["patch_bytes"] <= 0
                    or not _is_sha256(row.get("patch_sha256"))
                ):
                    raise ValueError("adaptive horizon patch evidence is invalid")
            elif row.get("status") != "PASS" or not _is_sha256(
                row.get("test_command_sha256")
            ):
                raise ValueError("adaptive horizon test evidence is invalid")
        for index, row in enumerate(extension_events, 1):
            if (
                not isinstance(row, Mapping)
                or set(row) != {
                    "extension_ordinal", "node_id", "observed_node_steps",
                    "next_step_no", "prior_step_limit", "extended_step_limit",
                    "trigger_progress_ordinal", "trigger_kind",
                }
                or row.get("extension_ordinal") != index
                or not isinstance(row.get("node_id"), str)
                or not row["node_id"]
                or any(
                    type(row.get(name)) is not int or row[name] < 1
                    for name in (
                        "observed_node_steps", "next_step_no",
                        "prior_step_limit", "extended_step_limit",
                        "trigger_progress_ordinal",
                    )
                )
                or row["trigger_progress_ordinal"] > len(progress_events)
            ):
                raise ValueError("adaptive horizon extension evidence is invalid")
            trigger = progress_events[row["trigger_progress_ordinal"] - 1]
            if (
                row.get("trigger_kind") != trigger.get("kind")
                or row.get("node_id") != trigger.get("node_id")
                or row["observed_node_steps"] != row["prior_step_limit"]
                or row["extended_step_limit"]
                != row["prior_step_limit"] + self.policy.extension_steps
                or row["extended_step_limit"]
                > self.policy.maximum_steps_per_subtask
            ):
                raise ValueError("adaptive horizon extension evidence is inconsistent")
        copied_nodes: dict[str, dict[str, int]] = {}
        for node_id, row in nodes.items():
            if not isinstance(node_id, str) or not node_id or not isinstance(row, Mapping):
                raise ValueError("adaptive horizon node state is invalid")
            if set(row) != self._NODE_FIELDS or any(
                type(row.get(name)) is not int or row[name] < 0
                for name in self._NODE_FIELDS
            ):
                raise ValueError("adaptive horizon node state is invalid")
            count = row["extension_count"]
            if (
                count > self.policy.maximum_extensions_per_subtask
                or row["current_step_limit"]
                != self.base_steps + count * self.policy.extension_steps
                or row["current_step_limit"]
                > self.policy.maximum_steps_per_subtask
                or row["consumed_progress_ordinal"]
                > row["latest_progress_ordinal"]
                or row["latest_progress_ordinal"] > len(progress_events)
            ):
                raise ValueError("adaptive horizon node state is inconsistent")
            copied_nodes[node_id] = {name: int(row[name]) for name in self._NODE_FIELDS}
        if sum(row["extension_count"] for row in copied_nodes.values()) != len(extension_events):
            raise ValueError("adaptive horizon extension count differs from evidence")
        if any(row["node_id"] not in copied_nodes for row in progress_events):
            raise ValueError("adaptive horizon progress node is absent")
        if any(row["node_id"] not in copied_nodes for row in extension_events):
            raise ValueError("adaptive horizon extension node is absent")
        expected_patch_high_water = max(
            (
                row["patch_bytes"] for row in progress_events
                if row["kind"] == "PATCH_DIFF_HIGH_WATER"
            ),
            default=0,
        )
        expected_test_high_water = int(
            any(row["kind"] == "TEST_PASS_HIGH_WATER" for row in progress_events)
        )
        if (
            value["patch_bytes_high_water"] != expected_patch_high_water
            or value["test_status_high_water"] != expected_test_high_water
        ):
            raise ValueError("adaptive horizon global high-water differs from evidence")
        for node_id, node in copied_nodes.items():
            node_progress = [
                row["ordinal"] for row in progress_events
                if row["node_id"] == node_id
            ]
            node_extensions = [
                row for row in extension_events if row["node_id"] == node_id
            ]
            if (
                node["latest_progress_ordinal"] != max(node_progress, default=0)
                or node["extension_count"] != len(node_extensions)
                or node["consumed_progress_ordinal"]
                != (
                    node_extensions[-1]["trigger_progress_ordinal"]
                    if node_extensions else 0
                )
            ):
                raise ValueError("adaptive horizon node ledger differs from evidence")
            for offset, event in enumerate(node_extensions):
                expected_prior = self.base_steps + offset * self.policy.extension_steps
                if (
                    event["prior_step_limit"] != expected_prior
                    or event["extended_step_limit"]
                    != expected_prior + self.policy.extension_steps
                ):
                    raise ValueError("adaptive horizon extension sequence is invalid")
        return {
            **expected,
            "patch_bytes_high_water": int(value["patch_bytes_high_water"]),
            "test_status_high_water": int(value["test_status_high_water"]),
            "progress_events": [dict(row) for row in progress_events],
            "extension_events": [dict(row) for row in extension_events],
            "nodes": copied_nodes,
        }

    def _node(self, node_id: str) -> dict[str, int]:
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("adaptive horizon requires a non-empty node id")
        nodes = self._state["nodes"]
        if node_id not in nodes:
            nodes[node_id] = {
                "current_step_limit": self.base_steps,
                "extension_count": 0,
                "latest_progress_ordinal": 0,
                "consumed_progress_ordinal": 0,
            }
        return nodes[node_id]

    def current_limit(self, node_id: str) -> int:
        return self._node(node_id)["current_step_limit"]

    def observe_successful_tool_result(
        self,
        *,
        node_id: str,
        step_no: int,
        tool: str,
        arguments: Mapping[str, Any],
        result: Mapping[str, Any],
        canonical_git_diff: str,
    ) -> tuple[Mapping[str, Any], ...]:
        """Capture only strict high-water increases; repetitions are inert."""

        node = self._node(node_id)
        observed: list[dict[str, Any]] = []
        patch_raw = canonical_git_diff.encode("utf-8")
        patch_bytes = len(patch_raw)
        if patch_bytes > self._state["patch_bytes_high_water"]:
            self._state["patch_bytes_high_water"] = patch_bytes
            observed.append({
                "kind": "PATCH_DIFF_HIGH_WATER",
                "step_no": step_no,
                "node_id": node_id,
                "patch_bytes": patch_bytes,
                "patch_sha256": sha256_bytes(patch_raw),
            })
        test_identity = _successful_test_identity(tool, arguments, result)
        if test_identity is not None and self._state["test_status_high_water"] < 1:
            self._state["test_status_high_water"] = 1
            observed.append({
                "kind": "TEST_PASS_HIGH_WATER",
                "step_no": step_no,
                "node_id": node_id,
                "test_command_sha256": test_identity,
                "status": "PASS",
            })
        for row in observed:
            ordinal = len(self._state["progress_events"]) + 1
            event = {"ordinal": ordinal, **row}
            self._state["progress_events"].append(event)
            node["latest_progress_ordinal"] = ordinal
        return tuple(dict(row) for row in observed)

    def extend_at_boundary(
        self,
        *,
        node_id: str,
        observed_node_steps: int,
        next_step_no: int,
    ) -> Optional[Mapping[str, Any]]:
        """Consume fresh progress and return one durable extension event."""

        node = self._node(node_id)
        if observed_node_steps != node["current_step_limit"]:
            if observed_node_steps > node["current_step_limit"]:
                raise ValueError("adaptive horizon checkpoint exceeded its current limit")
            return None
        if (
            node["latest_progress_ordinal"] <= node["consumed_progress_ordinal"]
            or node["extension_count"] >= self.policy.maximum_extensions_per_subtask
            or node["current_step_limit"] >= self.policy.maximum_steps_per_subtask
        ):
            return None
        prior = node["current_step_limit"]
        extended = min(
            prior + self.policy.extension_steps,
            self.policy.maximum_steps_per_subtask,
        )
        if extended != prior + self.policy.extension_steps:
            raise ValueError("adaptive horizon maximum is not extension-aligned")
        node["current_step_limit"] = extended
        node["extension_count"] += 1
        node["consumed_progress_ordinal"] = node["latest_progress_ordinal"]
        trigger = self._state["progress_events"][
            node["latest_progress_ordinal"] - 1
        ]
        event = {
            "extension_ordinal": len(self._state["extension_events"]) + 1,
            "node_id": node_id,
            "observed_node_steps": observed_node_steps,
            "next_step_no": next_step_no,
            "prior_step_limit": prior,
            "extended_step_limit": extended,
            "trigger_progress_ordinal": trigger["ordinal"],
            "trigger_kind": trigger["kind"],
        }
        self._state["extension_events"].append(event)
        return dict(event)

    @property
    def extension_count(self) -> int:
        return len(self._state["extension_events"])

    def checkpoint_state(self) -> dict[str, Any]:
        return {
            **{
                name: self._state[name]
                for name in (
                    "schema",
                    "base_steps_per_subtask",
                    "extension_steps",
                    "maximum_steps_per_subtask",
                    "maximum_extensions_per_subtask",
                    "patch_bytes_high_water",
                    "test_status_high_water",
                )
            },
            "progress_events": [dict(row) for row in self._state["progress_events"]],
            "extension_events": [dict(row) for row in self._state["extension_events"]],
            "nodes": {
                node_id: dict(row)
                for node_id, row in sorted(self._state["nodes"].items())
            },
        }
