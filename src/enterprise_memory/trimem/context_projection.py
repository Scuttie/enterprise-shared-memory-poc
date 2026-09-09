"""Deterministic, bounded model-visible views of exact tool evidence.

The runtime keeps the original request and result payloads in restricted,
content-addressed evidence and in checkpoints.  This module creates a separate
view for prompts; it never mutates the recovery copy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from .accounting import canonical_bytes, sha256_bytes


MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES = 65_536
MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES = 98_304
MAX_SOLVE_PROMPT_UTF8_BYTES = 196_608
MAX_EXTRACTION_PROMPT_UTF8_BYTES = 196_608
MODEL_REQUEST_FRAMING_ALLOWANCE = 4_096
MAX_ORDINARY_INPUT_BOUND = (
    MAX_SOLVE_PROMPT_UTF8_BYTES + MODEL_REQUEST_FRAMING_ALLOWANCE
)

_EDIT_AND_TEST_TOOLS = frozenset({
    "write_file",
    "replace_text",
    "run_public_tests",
    "run_command",
})


class ContextProjectionError(RuntimeError):
    """One task produced public context that cannot be projected safely."""


@dataclass(frozen=True)
class ModelVisibleToolObservation:
    step_no: int
    active_node_id: str
    tool: str
    status: str
    argument_summary: Mapping[str, Any]
    result_summary: Mapping[str, Any]
    exact_request_sha256: str
    exact_result_sha256: str
    exact_request_bytes: int
    exact_result_bytes: int
    content_omitted: bool
    omission_reason: str | None

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolHistoryProjection:
    observations: tuple[ModelVisibleToolObservation, ...]
    raw_history_bytes: int
    projected_history_bytes: int
    included_observation_count: int
    omitted_observation_count: int
    omitted_tool_counts: Mapping[str, int]
    projection_sha256: str
    cap: int

    def model_value(self) -> dict[str, Any]:
        return {
            "schema": "trimem/model-visible-tool-history/1.0",
            "observations": [row.public_dict() for row in self.observations],
            "omitted_observation_count": self.omitted_observation_count,
            "omitted_tool_counts": dict(sorted(self.omitted_tool_counts.items())),
        }

    def record(self, *, final_prompt: str, status: str = "BOUNDED") -> dict[str, Any]:
        raw = final_prompt.encode("utf-8")
        return {
            "schema": "trimem/prompt-projection-record/1.0",
            "raw_history_bytes": self.raw_history_bytes,
            "projected_history_bytes": self.projected_history_bytes,
            "final_prompt_bytes": len(raw),
            "included_observation_count": self.included_observation_count,
            "omitted_observation_count": self.omitted_observation_count,
            "omitted_tool_counts": dict(sorted(self.omitted_tool_counts.items())),
            "projection_sha256": self.projection_sha256,
            "final_prompt_sha256": sha256_bytes(raw),
            "cap": self.cap,
            "status": status,
        }


def _utf8_prefix(value: str, maximum: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= maximum:
        return value
    cut = raw[:maximum]
    while cut:
        try:
            return cut.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def _utf8_suffix(value: str, maximum: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= maximum:
        return value
    if maximum == 0:
        return ""
    cut = raw[-maximum:]
    while cut:
        try:
            return cut.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            cut = cut[1:]
    return ""


def bounded_text_record(value: str, *, maximum: int) -> dict[str, Any]:
    """Return intact UTF-8 head/tail text plus exact identity metadata."""

    if not isinstance(value, str) or maximum < 0:
        raise ContextProjectionError("invalid text projection input")
    raw = value.encode("utf-8")
    if len(raw) <= maximum:
        return {
            "text": value,
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
            "truncated": False,
        }
    head_budget = maximum // 2
    tail_budget = maximum - head_budget
    return {
        "head": _utf8_prefix(value, head_budget),
        "tail": _utf8_suffix(value, tail_budget),
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "truncated": True,
    }


def _exact_payload_identity(
    history_row: Mapping[str, Any],
    payload_name: str,
    reference_name: str,
) -> tuple[Any, str, int]:
    if payload_name not in history_row:
        raise ContextProjectionError(f"tool history lacks {payload_name}")
    payload = history_row[payload_name]
    raw = canonical_bytes(payload)
    digest = sha256_bytes(raw)
    reference = history_row.get(reference_name)
    if reference is not None:
        if (
            not isinstance(reference, Mapping)
            or reference.get("sha256") != digest
            or reference.get("bytes") != len(raw)
        ):
            raise ContextProjectionError(
                f"tool history {payload_name} differs from exact evidence reference"
            )
    return payload, digest, len(raw)


def _argument_summary(tool: str, arguments: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    if tool == "write_file":
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ContextProjectionError("write_file history content is invalid")
        raw = content.encode("utf-8")
        return ({
            "path": arguments.get("path"),
            "content_sha256": sha256_bytes(raw),
            "content_bytes": len(raw),
        }, True)
    if tool == "replace_text":
        old_text, new_text = arguments.get("old_text"), arguments.get("new_text")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ContextProjectionError("replace_text history content is invalid")
        old_raw, new_raw = old_text.encode("utf-8"), new_text.encode("utf-8")
        return ({
            "path": arguments.get("path"),
            "expected_file_sha256": arguments.get("expected_file_sha256"),
            "old_text_sha256": sha256_bytes(old_raw),
            "old_text_bytes": len(old_raw),
            "new_text_sha256": sha256_bytes(new_raw),
            "new_text_bytes": len(new_raw),
        }, True)
    if tool == "complete_subtask":
        evidence = arguments.get("evidence")
        if not isinstance(evidence, str):
            raise ContextProjectionError(
                "complete_subtask history evidence is invalid"
            )
        raw = evidence.encode("utf-8")
        return ({
            "evidence_sha256": sha256_bytes(raw),
            "evidence_bytes": len(raw),
        }, True)
    # Other live arguments are already schema-bounded and contain no write body.
    return dict(arguments), False


def _read_result(result: Mapping[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    content = result.get("content")
    if not isinstance(content, str):
        return dict(result), False, None
    returned_start = result.get(
        "returned_start_line", result.get("start_line", 1)
    )
    if type(returned_start) is not int or returned_start < 1:
        raise ContextProjectionError("read_file returned line range is invalid")
    lines = content.splitlines(keepends=True)
    base = {
        key: value
        for key, value in result.items()
        if key not in {"content", "next_start_line", "projection_truncated"}
    }

    def candidate(line_count: int) -> dict[str, Any]:
        projection_omitted = line_count < len(lines)
        summary = {**base, "content": "".join(lines[:line_count])}
        if projection_omitted or result.get("truncated") is True:
            # The cursor always names the first complete omitted line.  Never
            # expose a byte-fragment that the line-based read tool cannot
            # retrieve on a later call.
            summary["next_start_line"] = returned_start + line_count
        if projection_omitted:
            summary["projection_truncated"] = True
        return summary

    low, high = 0, len(lines)
    while low < high:
        middle = (low + high + 1) // 2
        if len(canonical_bytes(candidate(middle))) <= MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
            low = middle
        else:
            high = middle - 1
    if lines and low == 0:
        raise ContextProjectionError(
            "one read_file line exceeds the model-visible result cap"
        )
    summary = candidate(low)
    if len(canonical_bytes(summary)) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
        raise ContextProjectionError("read_file metadata exceeds visible result cap")
    omitted = low < len(lines)
    return summary, omitted, "READ_FILE_VISIBLE_RESULT_CAP" if omitted else None


def _search_result(result: Mapping[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    hits = result.get("hits")
    if not isinstance(hits, list):
        return dict(result), False, None
    summary = {key: value for key, value in result.items() if key != "hits"}
    selected: list[Any] = []
    for hit in hits:
        candidate = {**summary, "hits": [*selected, hit]}
        if len(canonical_bytes(candidate)) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
            break
        selected.append(hit)
    omitted = len(selected) != len(hits)
    summary.update({
        "hits": selected,
        "hit_count": len(hits),
        "visible_hit_count": len(selected),
    })
    if omitted:
        summary["next_hit_index"] = len(selected)
        summary["projection_truncated"] = True
    # The cursor/count metadata is added after selecting hits.  Account for
    # those bytes too, removing only complete hit objects until the complete
    # model-visible result satisfies the frozen 65,536-byte cap.
    while (
        selected
        and len(canonical_bytes(summary)) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES
    ):
        selected.pop()
        omitted = True
        summary.update({
            "hits": selected,
            "visible_hit_count": len(selected),
            "next_hit_index": len(selected),
            "projection_truncated": True,
        })
    if len(canonical_bytes(summary)) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
        raise ContextProjectionError("search metadata exceeds visible result cap")
    return summary, omitted, "SEARCH_VISIBLE_RESULT_CAP" if omitted else None


def _command_result(result: Mapping[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    stdout, stderr = result.get("stdout", ""), result.get("stderr", "")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise ContextProjectionError("command history output is invalid")
    stdout_raw, stderr_raw = stdout.encode("utf-8"), stderr.encode("utf-8")
    total = len(stdout_raw) + len(stderr_raw)
    base = {
        key: value
        for key, value in result.items()
        if key not in {"stdout", "stderr"}
    }

    def stream_budgets(total_budget: int) -> tuple[int, int]:
        stdout_budget = min(len(stdout_raw), (total_budget + 1) // 2)
        stderr_budget = min(len(stderr_raw), total_budget // 2)
        remaining = total_budget - stdout_budget - stderr_budget
        if remaining:
            added = min(len(stdout_raw) - stdout_budget, remaining)
            stdout_budget += added
            remaining -= added
        if remaining:
            stderr_budget += min(len(stderr_raw) - stderr_budget, remaining)
        return stdout_budget, stderr_budget

    def candidate(total_budget: int) -> dict[str, Any]:
        stdout_budget, stderr_budget = stream_budgets(total_budget)
        return {
            **base,
            "stdout": bounded_text_record(stdout, maximum=stdout_budget),
            "stderr": bounded_text_record(stderr, maximum=stderr_budget),
            "stdout_sha256": sha256_bytes(stdout_raw),
            "stderr_sha256": sha256_bytes(stderr_raw),
            "stdout_bytes": len(stdout_raw),
            "stderr_bytes": len(stderr_raw),
        }

    low, high = 0, min(total, MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES)
    if len(canonical_bytes(candidate(0))) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
        raise ContextProjectionError("command metadata exceeds visible result cap")
    while low < high:
        middle = (low + high + 1) // 2
        if len(canonical_bytes(candidate(middle))) <= MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
            low = middle
        else:
            high = middle - 1
    summary = candidate(low)
    omitted = bool(
        summary["stdout"]["truncated"] or summary["stderr"]["truncated"]
    )
    return summary, omitted, "COMMAND_VISIBLE_RESULT_CAP" if omitted else None


def _result_summary(
    tool: str,
    result: Mapping[str, Any],
    *,
    legacy_list_files_replay: bool = False,
) -> tuple[dict[str, Any], bool, str | None]:
    if "error" in result:
        message = result.get("message", "")
        summary = dict(result)
        if isinstance(message, str):
            # Account for the surrounding result fields as well as the text.
            # A 65,536-byte text slice can otherwise serialize to more than the
            # frozen 65,536-byte *result* cap once hashes and metadata are added.
            low, high = 0, min(
                len(message.encode("utf-8")),
                MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES,
            )

            def candidate(maximum: int) -> dict[str, Any]:
                return {
                    **summary,
                    "message": bounded_text_record(message, maximum=maximum),
                }

            if len(canonical_bytes(candidate(0))) > MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
                raise ContextProjectionError("tool error metadata exceeds visible result cap")
            while low < high:
                middle = (low + high + 1) // 2
                if len(canonical_bytes(candidate(middle))) <= MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES:
                    low = middle
                else:
                    high = middle - 1
            summary = candidate(low)
            bounded = summary["message"]
            omitted = bool(bounded["truncated"])
            return summary, omitted, "TOOL_ERROR_VISIBLE_RESULT_CAP" if omitted else None
        return summary, False, None
    if tool == "read_file":
        return _read_result(result)
    if tool == "search":
        return _search_result(result)
    if tool in {"run_public_tests", "run_command"}:
        return _command_result(result)
    if tool == "complete_subtask":
        evidence = result.get("evidence")
        if not isinstance(evidence, str):
            raise ContextProjectionError(
                "complete_subtask result evidence is invalid"
            )
        raw = evidence.encode("utf-8")
        return ({
            "completed": result.get("completed") is True,
            "evidence_sha256": sha256_bytes(raw),
            "evidence_bytes": len(raw),
        }, True, "COMPLETION_EVIDENCE_COMPACTED")
    if tool == "list_files":
        required = {
            "path_prefix", "start_after", "files", "returned_count",
            "total_matching_count", "next_start_after", "truncated",
            "full_matching_listing_sha256",
        }
        if set(result) == {"files"} and legacy_list_files_replay:
            files = result.get("files")
            if not isinstance(files, list) or any(
                not isinstance(path, str) for path in files
            ):
                raise ContextProjectionError(
                    "legacy list_files result is malformed"
                )
            # Importing here keeps the live workspace implementation the one
            # source of truth while making the legacy path explicit.
            from .workspace import list_files_page

            page = list_files_page(
                files,
                {"path_prefix": None, "start_after": None, "limit": 200},
            )
            return page, bool(page["truncated"]), "LEGACY_LISTING_PAGINATED"
        if set(result) != required:
            raise ContextProjectionError("list_files result is not the live paginated shape")
        return dict(result), False, None
    return dict(result), False, None


def _observation(
    history_row: Mapping[str, Any], *, legacy_list_files_replay: bool = False
) -> ModelVisibleToolObservation:
    request, request_hash, request_bytes = _exact_payload_identity(
        history_row, "request_payload", "request"
    )
    result, result_hash, result_bytes = _exact_payload_identity(
        history_row, "result_payload", "result"
    )
    if not isinstance(request, Mapping) or not isinstance(result, Mapping):
        raise ContextProjectionError("tool history payload is not an object")
    tool = request.get("tool")
    arguments = request.get("arguments")
    if not isinstance(tool, str) or not isinstance(arguments, Mapping):
        raise ContextProjectionError("tool history request is malformed")
    if history_row.get("tool") not in {None, tool}:
        raise ContextProjectionError("tool history tool identity differs")
    argument_summary, argument_omitted = _argument_summary(tool, arguments)
    result_summary, result_omitted, result_reason = _result_summary(
        tool,
        result,
        legacy_list_files_replay=legacy_list_files_replay,
    )
    omitted = argument_omitted or result_omitted
    reasons = []
    if argument_omitted:
        reasons.append(
            "EDIT_CONTENT_NOT_REINJECTED"
            if tool in {"write_file", "replace_text"}
            else "COMPLETION_EVIDENCE_NOT_REINJECTED"
        )
    if result_reason:
        reasons.append(result_reason)
    return ModelVisibleToolObservation(
        step_no=int(history_row.get("step_no", 0)),
        active_node_id=str(history_row.get("active_node_id", "")),
        tool=tool,
        status=str(history_row.get("status", "unknown")),
        argument_summary=argument_summary,
        result_summary=result_summary,
        exact_request_sha256=request_hash,
        exact_result_sha256=result_hash,
        exact_request_bytes=request_bytes,
        exact_result_bytes=result_bytes,
        content_omitted=omitted,
        omission_reason=";".join(reasons) if reasons else None,
    )


def _compact(observation: ModelVisibleToolObservation) -> ModelVisibleToolObservation:
    argument = {
        key: value
        for key, value in observation.argument_summary.items()
        if key in {
            "path", "path_prefix", "start_after", "query", "argv", "cwd",
            "content_sha256", "content_bytes", "expected_file_sha256",
            "old_text_sha256", "old_text_bytes", "new_text_sha256", "new_text_bytes",
        }
    }
    result = {
        key: value
        for key, value in observation.result_summary.items()
        if key in {
            "path", "exit_code", "passed", "timed_out", "output_truncated",
            "content_hash", "bytes", "prior_sha256", "new_sha256", "old_bytes",
            "new_bytes", "replacements", "returned_count", "total_matching_count",
            "next_start_after", "truncated", "full_matching_listing_sha256",
            "hit_count", "visible_hit_count", "total_file_bytes", "full_file_sha256",
            "returned_start_line", "returned_end_line", "total_lines", "completed",
            "dag_revised",
        }
    }
    reason = observation.omission_reason
    reason = f"{reason};OLDER_OBSERVATION_COMPACTED" if reason else "OLDER_OBSERVATION_COMPACTED"
    return replace(
        observation,
        argument_summary=argument,
        result_summary=result,
        content_omitted=True,
        omission_reason=reason,
    )


def _priority_order(
    observations: Sequence[ModelVisibleToolObservation], active_node_id: str
) -> list[ModelVisibleToolObservation]:
    active = sorted(
        (row for row in observations if row.active_node_id == active_node_id),
        key=lambda row: (-row.step_no, row.tool, row.exact_result_sha256),
    )
    inactive = sorted(
        (row for row in observations if row.active_node_id != active_node_id),
        key=lambda row: (-row.step_no, row.tool, row.exact_result_sha256),
    )
    recent, older = inactive[:8], inactive[8:]
    edit_test = [row for row in older if row.tool in _EDIT_AND_TEST_TOOLS]
    remaining = [row for row in older if row.tool not in _EDIT_AND_TEST_TOOLS]
    return [*active, *recent, *edit_test, *remaining]


def _project_observations(
    exact_rows: Sequence[Mapping[str, Any]],
    projected_rows: Sequence[ModelVisibleToolObservation],
    *,
    active_node_id: str,
    max_bytes: int,
) -> ToolHistoryProjection:
    if not isinstance(active_node_id, str) or not active_node_id:
        raise ContextProjectionError("active_node_id is required for history projection")
    if type(max_bytes) is not int or not 1_024 <= max_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
        raise ContextProjectionError("tool history projection cap is invalid")
    raw_history_bytes = len(canonical_bytes(exact_rows))
    selected: list[ModelVisibleToolObservation] = []
    omitted: list[ModelVisibleToolObservation] = []

    # Reserve deterministic room for the schema and omission metadata.  Final
    # validation below removes complete observations if an unusually diverse
    # tool set makes that metadata larger than the reserve.
    observation_budget = max(0, max_bytes - 4_096)
    for row in _priority_order(projected_rows, active_node_id):
        candidate = [item.public_dict() for item in (*selected, row)]
        if len(canonical_bytes(candidate)) <= observation_budget:
            selected.append(row)
            continue
        compact = _compact(row)
        candidate = [item.public_dict() for item in (*selected, compact)]
        if len(canonical_bytes(candidate)) <= observation_budget:
            selected.append(compact)
        else:
            omitted.append(row)

    omitted_counts: dict[str, int] = {}
    for row in omitted:
        omitted_counts[row.tool] = omitted_counts.get(row.tool, 0) + 1

    def value() -> dict[str, Any]:
        return {
            "schema": "trimem/model-visible-tool-history/1.0",
            "observations": [row.public_dict() for row in selected],
            "omitted_observation_count": len(omitted),
            "omitted_tool_counts": dict(sorted(omitted_counts.items())),
        }

    while selected and len(canonical_bytes(value())) > max_bytes:
        row = selected.pop()
        omitted.append(row)
        omitted_counts[row.tool] = omitted_counts.get(row.tool, 0) + 1
    serialized = canonical_bytes(value())
    if len(serialized) > max_bytes:
        raise ContextProjectionError("tool history metadata exceeds projection cap")
    return ToolHistoryProjection(
        observations=tuple(selected),
        raw_history_bytes=raw_history_bytes,
        projected_history_bytes=len(serialized),
        included_observation_count=len(selected),
        omitted_observation_count=len(omitted),
        omitted_tool_counts=dict(sorted(omitted_counts.items())),
        projection_sha256=sha256_bytes(serialized),
        cap=max_bytes,
    )


def project_tool_history_for_model(
    history: Sequence[Mapping[str, Any]],
    *,
    active_node_id: str,
    max_bytes: int = MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
) -> ToolHistoryProjection:
    """Project exact live tool history into a deterministic prompt-safe object."""

    exact_rows = tuple(dict(row) for row in history)
    projected_rows = tuple(_observation(row) for row in exact_rows)
    return _project_observations(
        exact_rows,
        projected_rows,
        active_node_id=active_node_id,
        max_bytes=max_bytes,
    )


def project_legacy_tool_history_for_model_replay(
    history: Sequence[Mapping[str, Any]],
    *,
    active_node_id: str,
    max_bytes: int = MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
) -> ToolHistoryProjection:
    """Read pre-D1.9 exact history through an explicit replay-only adapter."""

    if type(max_bytes) is not int or not 1_024 <= max_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
        raise ContextProjectionError("tool history projection cap is invalid")
    exact_rows = tuple(dict(row) for row in history)
    # Reuse the same selection algorithm by replacing only model-visible
    # observations. The exact payload identity fields still bind old bytes.
    projected_rows = tuple(
        _observation(row, legacy_list_files_replay=True) for row in exact_rows
    )
    return _project_observations(
        exact_rows,
        projected_rows,
        active_node_id=active_node_id,
        max_bytes=max_bytes,
    )


def model_visible_observation_projection_contract() -> dict[str, Any]:
    return {
        "schema": "trimem/model-visible-observation-projection/1.0",
        "max_model_visible_tool_result_bytes": MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES,
        "max_model_visible_tool_history_bytes": MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
        "raw_evidence": "exact-and-immutable",
        "summarizer": "deterministic-no-model",
        "write_bodies_reinjected": False,
        "command_output": "utf8-head-tail-with-exact-hashes-and-byte-counts",
        "selection_order": [
            "active_subtask",
            "most_recent",
            "edit_and_test",
            "compact_older",
        ],
    }


def prompt_context_contract() -> dict[str, Any]:
    return {
        "schema": "trimem/prompt-context-contract/1.0",
        "max_solve_prompt_utf8_bytes": MAX_SOLVE_PROMPT_UTF8_BYTES,
        "max_extraction_prompt_utf8_bytes": MAX_EXTRACTION_PROMPT_UTF8_BYTES,
        "model_request_framing_allowance": MODEL_REQUEST_FRAMING_ALLOWANCE,
        "max_ordinary_input_bound": MAX_ORDINARY_INPUT_BOUND,
        "textual_full_tool_schema": False,
        "native_function_schema": "present-and-hash-bound",
        "required_active_state": "never-silently-omitted",
        "json_compaction": "complete-objects-only",
    }


MODEL_VISIBLE_OBSERVATION_PROJECTION_SHA256 = sha256_bytes(
    canonical_bytes(model_visible_observation_projection_contract())
)
PROMPT_CONTEXT_CONTRACT_SHA256 = sha256_bytes(
    canonical_bytes(prompt_context_contract())
)
