from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import base64
import json

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.context_projection import ContextProjectionError
from enterprise_memory.trimem.native_architecture_context import (
    HandoffError, HandoffLimits, HandoffMemory, TaskHandoffContext, validate_handoff,
)
from enterprise_memory.trimem.working_graph import Evidence, ShortTermWorkingGraph, SubtaskSpec


TASK = {"task_id": "task", "repository": "org/repo", "commit": "a" * 40,
        "instruction": "Repair timeout and retry handling"}
TOOLS = {"read_file": {"type": "object", "properties": {"path": {"type": "string"}}}}
CONFIG, BANK = "c" * 64, "b" * 64


def _row(step, node, text, arm="PDF_MEMORY"):
    request = {"tool": "read_file", "arguments": {"path": "client.py"}}
    result = {"path": "client.py", "content": text}
    return {"task_id": "task", "arm": arm, "step_no": step, "active_node_id": node,
            "tool": "read_file", "status": "success", "request_payload": request,
            "result_payload": result,
            "request": {"sha256": sha256_bytes(canonical_bytes(request)), "bytes": len(canonical_bytes(request))},
            "result": {"sha256": sha256_bytes(canonical_bytes(result)), "bytes": len(canonical_bytes(result))}}


def _graph():
    graph = ShortTermWorkingGraph(TASK["task_id"], TASK["instruction"], TASK["repository"])
    graph.add_subtask(SubtaskSpec(node_id="first", objective="Propagate timeout to callers", operation="forward timeout"))
    graph.add_subtask(SubtaskSpec(node_id="second", objective="Repair retry exception boundary",
                                operation="check retry limit", dependencies=("first",)))
    graph.activate("first")
    return graph


def _context(graph, history=(), task=None, tools=None):
    return TaskHandoffContext(task=task or TASK, graph=graph, history=list(history), tool_schema=tools or TOOLS)


def _build(context, arm="PDF_MEMORY", **kwargs):
    return context.build_handoff(**{
        "arm": arm, "worker_id": "worker-1", "configuration_sha256": CONFIG,
        "bank_sha256": BANK, **kwargs,
    })


def _fixture(arm="PDF_MEMORY", *, limits=HandoffLimits(), extra_text=""):
    graph = _graph()
    first = _build(_context(graph), arm, limits=limits)
    history = [_row(1, "first", "COMPLETED_RAW_SENTINEL\n" + extra_text, arm)]
    request = {"tool": "run_public_tests", "arguments": {}}
    result = {"exit_code": 1, "passed": False, "stdout": "COMPLETED_FAILED_TEST_OUTPUT", "stderr": ""}
    history.append({"task_id": "task", "arm": arm, "step_no": 2, "active_node_id": "first",
        "tool": "run_public_tests", "status": "success", "request_payload": request, "result_payload": result})
    graph.complete_active(Evidence.capture("tool_result", "Timeout forwarded; public tests still failed",
        result, supports_completion=True))
    graph.activate("second")
    history.append(_row(3, "second", "ACTIVE_RAW_SENTINEL\n", arm))
    context = _context(graph, history)
    second = _build(context, arm, worker_id="worker-2", previous_packet=first, limits=limits)
    return context, graph, history, first, second


def _accept(packet, **kwargs):
    return validate_handoff(packet.public_dict(), **{
        "expected_binding": packet.binding, "expected_sha256": packet.sha256,
        "fork_turns": "none", "new_worker": True, **kwargs,
    })


def _trace(context, packet, **kwargs):
    return context.retrieve_trace(packet.public_dict(), **{
        "expected_binding": packet.binding, "expected_sha256": packet.sha256,
        "worker_id": "worker-2", "task_id": "task", "subgoal_id": "first", "max_bytes": 48_000,
        **kwargs,
    })


def _chunk(context, packet, **kwargs):
    return context.retrieve_trace_chunk(packet.public_dict(), **{
        "expected_binding": packet.binding, "expected_sha256": packet.sha256,
        "worker_id": "worker-2", "task_id": "task", "subgoal_id": "first",
        "step_no": 1, "offset_bytes": 0, "max_bytes": 8192, **kwargs,
    })


def test_pdf_hides_completed_raw_history_and_explicit_retrieval_restores_exact_rows():
    context, graph, history, first, packet = _fixture()
    raw = packet.utf8.decode("utf-8")
    assert "COMPLETED_RAW_SENTINEL" not in raw
    assert "COMPLETED_FAILED_TEST_OUTPUT" not in raw
    assert "ACTIVE_RAW_SENTINEL" in raw
    summary = packet.public_dict()["body"]["working_context"]["completed_subgoals"][0]
    assert summary["tool_results"][1]["result_facts"]["passed"] is False
    assert summary["tool_results"][1]["result_facts"]["exit_code"] == 1
    assert summary["completion_evidence"][0]["summary"]["text"] == "Timeout forwarded; public tests still failed"
    trace = _trace(context, packet)
    assert trace["rows"] == history[:2]
    assert trace["trace_reference"] == summary["trace_reference"]
    assert trace["trace_reference"]["sha256"] == sha256_bytes(canonical_bytes(history[:2]))
    assert trace["remaining_observation_count"] == 0 and trace["next_after_step"] is None
    assert packet.binding.reason == "SUBGOAL_CHANGE"
    assert packet.binding.previous_packet_sha256 == first.sha256
    assert packet.binding.graph_sha256 == graph.content_hash()


def test_baseline_keeps_flat_completed_observations_when_budget_fits_without_pdf_summaries():
    context, _, _, _, baseline = _fixture("BASELINE")
    _, _, _, _, pdf = _fixture("PDF_MEMORY")
    raw = baseline.utf8.decode("utf-8")
    assert "COMPLETED_RAW_SENTINEL" in raw and "COMPLETED_FAILED_TEST_OUTPUT" in raw
    assert "ACTIVE_RAW_SENTINEL" in raw
    body, other = baseline.public_dict()["body"], pdf.public_dict()["body"]
    assert body["memory_injections"] == []
    assert "completed_subgoals" not in body["working_context"]
    assert body["trace_retrieval"]["enabled"] is False
    for field in ("task", "graph", "tool_schema", "limits", "worker_launch"):
        assert body[field] == other[field]
    with pytest.raises(HandoffError, match="baseline has no"):
        _trace(context, baseline)


def test_initial_packet_and_actual_launch_require_new_worker_without_forked_history():
    packet = _build(_context(_graph()))
    assert packet.binding.reason == "INITIAL" and packet.binding.previous_worker_id is None
    assert packet.binding.history_count == 0
    body = _accept(packet)["body"]
    assert body["worker_launch"] == {"fork_turns": "none", "new_worker_required": True,
                                     "existing_conversation_erased": False}
    for change in ({"fork_turns": "all"}, {"fork_turns": "1"}, {"new_worker": False}, {"new_worker": 1}):
        with pytest.raises(HandoffError, match="new worker"):
            _accept(packet, **change)


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_empty_planner_graph_can_handoff_to_its_first_semantic_subgoal(arm):
    graph = ShortTermWorkingGraph(TASK["task_id"], TASK["instruction"], TASK["repository"])
    first = _build(_context(graph), arm)
    assert first.binding.active_node_id is None and first.binding.history_count == 0
    assert first.public_dict()["body"]["graph"]["nodes"] == []
    graph.add_subtask(SubtaskSpec(node_id="timeout", objective="Propagate timeout to callers", operation="forward timeout"))
    graph.activate("timeout")
    packet = _build(_context(graph), arm, worker_id="worker-2", previous_packet=first)
    assert packet.binding.reason == "SUBGOAL_CHANGE"


def test_external_memory_requires_pdf_current_subgoal_and_exact_frozen_bank():
    context = _context(_graph())
    text = "Read the caller contract before changing timeout propagation."
    item = HandoffMemory("lesson-1", "REPOSITORY_SEMANTIC", "first", text,
                         sha256_bytes(text.encode()), "a" * 64, BANK)
    packet = _build(context, memory_injections=[item])
    assert packet.public_dict()["body"]["memory_injections"] == [item.public_dict()]
    for changes, match in [
        ({"arm": "BASELINE"}, "zero external memory"),
        ({"bank_sha256": "d" * 64}, "frozen-bank"),
        ({"memory_injections": [replace(item, active_node_id="second")]}, "active-subgoal"),
        ({"memory_injections": [item, item]}, "duplicate"),
        ({"limits": HandoffLimits(max_memory_bytes=2)}, "budget"),
        ({"limits": HandoffLimits(max_memory_injections=0)}, "budget"),
    ]:
        with pytest.raises(HandoffError, match=match):
            _build(context, **{"memory_injections": [item], **changes})
    with pytest.raises(HandoffError, match="text hash"):
        replace(item, exact_text="tampered")


@pytest.mark.parametrize("field,value", [
    ("task_sha256", "d" * 64), ("arm", "BASELINE"), ("worker_id", "other-worker"),
    ("configuration_sha256", "d" * 64), ("bank_sha256", "d" * 64),
    ("graph_sha256", "d" * 64), ("history_sha256", "d" * 64),
    ("tool_schema_sha256", "d" * 64), ("limits_sha256", "d" * 64),
])
def test_expected_binding_rejects_foreign_or_stale_packets(field, value):
    packet = _build(_context(_graph()))
    with pytest.raises(HandoffError, match="binding differs"):
        _accept(packet, expected_binding=replace(packet.binding, **{field: value}))


def test_packet_tampering_and_unknown_fields_are_rejected_even_if_hash_is_recomputed():
    packet = _build(_context(_graph()))
    for unknown in (False, True):
        value = packet.public_dict()
        if unknown:
            value["body"]["extra"] = "unregistered field"
        else:
            value["body"]["task"]["instruction"] = "changed"
        value["sha256"] = sha256_bytes(canonical_bytes(value["body"]))
        with pytest.raises(HandoffError, match="schema|hash"):
            validate_handoff(value, expected_binding=packet.binding, expected_sha256=packet.sha256,
                             fork_turns="none", new_worker=True)


@pytest.mark.parametrize("changes", [
    {"arm": "BASELINE"}, {"configuration_sha256": "d" * 64},
    {"bank_sha256": "d" * 64}, {"limits": HandoffLimits(task_requests=121)},
    {"worker_id": "worker-1"},
])
def test_subgoal_transition_rejects_cross_condition_changes_or_worker_reuse(changes):
    context, _, _, first, _ = _fixture()
    with pytest.raises(HandoffError, match="binding differs|different worker"):
        _build(context, **{"previous_packet": first, "worker_id": "worker-2", **changes})


@pytest.mark.parametrize("arm,foreign", [("BASELINE", "PDF_MEMORY"), ("PDF_MEMORY", "BASELINE"),
                                        ("BASELINE", "M0"), ("PDF_MEMORY", None)])
def test_transition_rejects_new_foreign_or_missing_arm_rows_even_with_valid_prior_packet(arm, foreign):
    _, graph, history, first, _ = _fixture(arm)
    # These rows were not part of the initial empty packet. A prior-packet arm
    # comparison alone cannot catch contamination introduced at this boundary.
    if foreign is None:
        history[-1].pop("arm")
    else:
        history[-1]["arm"] = foreign
    with pytest.raises(HandoffError, match="history row.*arm binding"):
        _build(_context(graph, history), arm, worker_id="worker-2", previous_packet=first)


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_history_arm_binding_covers_every_row_and_later_appends(arm):
    _, graph, history, _, second = _fixture(arm)
    graph.complete_active(Evidence.capture("inspection", "Retry boundary observed", {}, supports_completion=True))
    graph.add_subtask(SubtaskSpec(node_id="third", objective="Check timeout callers together", operation="run caller checks"))
    graph.activate("third")
    history.append(_row(4, "third", "OTHER_CONDITION_INFORMATION", "PDF_MEMORY" if arm == "BASELINE" else "BASELINE"))
    with pytest.raises(HandoffError, match="history row.*arm binding"):
        _build(_context(graph, history), arm, worker_id="worker-3", previous_packet=second)


def test_transition_cannot_skip_completion_or_reset_exact_prior_history():
    graph = _graph()
    initial = _build(_context(graph))
    with pytest.raises(HandoffError, match="completed prior subgoal"):
        _build(_context(graph), worker_id="worker-2", previous_packet=initial)
    context, graph, history, _, second = _fixture()
    with pytest.raises(HandoffError, match="empty history"):
        _build(context)
    graph.complete_active(Evidence.capture("inspection", "Retry boundary observed", {}, supports_completion=True))
    graph.add_subtask(SubtaskSpec(node_id="third", objective="Check timeout callers together", operation="run caller checks"))
    graph.activate("third")
    altered = deepcopy(history)
    altered[0] = _row(1, "first", "altered old observation")
    with pytest.raises(HandoffError, match="exact prefix"):
        _build(_context(graph, altered), worker_id="worker-3", previous_packet=second)


def test_completion_evidence_is_required_and_existing_failed_test_outcome_is_preserved():
    _, graph, history, _, _ = _fixture()
    graph.nodes["first"].completion_evidence.clear()
    with pytest.raises(HandoffError, match="graph state"):
        _context(graph, history)
    graph = _graph()
    evidence = Evidence.capture("inspection", "Explicit completion claim", {}, supports_completion=True)
    graph.complete_active(evidence)
    graph.nodes["first"].completion_evidence[0] = replace(evidence, supports_completion="true")
    with pytest.raises(HandoffError, match="boolean"):
        _context(graph)


def test_graph_evidence_attributes_and_merged_anchors_cannot_bypass_pdf_projection():
    graph = _graph()
    first = _build(_context(graph))
    history = [_row(1, "first", "COMPLETED_RAW_SENTINEL")]
    evidence = Evidence.capture("inspection", "Timeout caller inspected", history[0]["result_payload"],
        supports_completion=True, attributes={
            "nested": {"raw_output": "RAW_ATTRIBUTE_SENTINEL"},
            "files": ["RAW_MERGED_FILE_SENTINEL"],
            "predicted_operation": "RAW_MERGED_OPERATION_SENTINEL",
        })
    graph.complete_active(evidence)
    graph.record_evidence(Evidence.capture("inspection", "Task observation", {},
                                          attributes={"raw": "RAW_TASK_EVIDENCE_SENTINEL"}))
    graph.activate("second")
    packet = _build(_context(graph, history), worker_id="worker-2", previous_packet=first)
    raw = packet.utf8.decode()
    for sentinel in ("COMPLETED_RAW_SENTINEL", "RAW_ATTRIBUTE_SENTINEL", "RAW_MERGED_FILE_SENTINEL",
                     "RAW_MERGED_OPERATION_SENTINEL", "RAW_TASK_EVIDENCE_SENTINEL"):
        assert sentinel not in raw
    assert packet.public_dict()["body"]["implementation_status"]["runtime_wired"] is False


@pytest.mark.parametrize("mutation", [
    lambda h: h[0].update(task_id="other"),
    lambda h: h[0].update(active_node_id="unknown"),
    lambda h: h[0].update(hidden_grader={"secret": "data"}),
    lambda h: h[0]["result_payload"].update(gold_patch="data"),
    lambda h: h[0].update(tool="grader"),
    lambda h: h[0]["result_payload"].update(content="changed reference"),
    lambda h: h.reverse(),
])
def test_public_history_validation_is_applied_to_both_arms(mutation):
    _, graph, history, _, _ = _fixture()
    mutation(history)
    with pytest.raises(ContextProjectionError):
        _context(graph, history)


@pytest.mark.parametrize("kwargs", [
    {"max_packet_bytes": 4095}, {"max_history_bytes": 1023}, {"max_trace_bytes": 98_305},
    {"max_memory_bytes": -1}, {"max_memory_injections": True},
    {"task_requests": 1.5}, {"task_seconds": 0},
])
def test_invalid_budget_values_are_rejected(kwargs):
    with pytest.raises(HandoffError):
        HandoffLimits(**kwargs)


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_complete_packet_unicode_and_context_share_one_enforced_byte_cap(arm):
    limits = HandoffLimits(max_packet_bytes=12_000, max_history_bytes=9_000)
    context, graph, history, first, packet = _fixture(arm, limits=limits, extra_text="한글 🦋\n" * 600)
    assert len(packet.utf8) <= limits.max_packet_bytes
    assert len(canonical_bytes(packet.public_dict()["body"]["working_context"])) <= limits.max_history_bytes
    again = _build(context, arm, worker_id="worker-2", previous_packet=first, limits=limits)
    assert again.utf8 == packet.utf8
    oversized = {**TASK, "files": {"large.py": "x" * 15_000}}
    with pytest.raises(HandoffError, match="metadata exceeds"):
        _build(_context(_graph(), task=oversized), arm, limits=limits)


def test_explicit_trace_pages_preserve_exact_rows_and_do_not_claim_partial_rows():
    context, _, history, _, packet = _fixture(extra_text="trace detail\n" * 100)
    first_row_size = len(canonical_bytes(history[0]))
    page = _trace(context, packet, max_bytes=first_row_size + 550)
    assert page["rows"] == history[:1]
    assert page["next_after_step"] == 1 and page["remaining_observation_count"] == 1
    next_page = _trace(context, packet, start_after_step=page["next_after_step"])
    assert page["rows"] + next_page["rows"] == history[:2]
    assert page["trace_reference"] == next_page["trace_reference"]
    assert next_page["next_after_step"] is None
    with pytest.raises(HandoffError, match="one exact trace row"):
        _trace(context, packet, max_bytes=1024)


def test_oversized_multibyte_public_row_reassembles_from_bounded_exact_byte_chunks():
    context, _, history, _, packet = _fixture(extra_text="한글 🦋 observation\n" * 5000)
    expected = canonical_bytes(history[0])
    assert len(expected) > 48_000
    with pytest.raises(HandoffError, match="retrieve_trace_chunk"):
        _trace(context, packet)
    offset, blocks, pages = 0, [], []
    while offset is not None:
        page = _chunk(context, packet, offset_bytes=offset, max_bytes=8192)
        assert len(canonical_bytes(page)) <= 8192
        assert page["schema"] == "skhynix/native-architecture-trace-chunk/1.0"
        assert page["complete_observation"] is False and page["requires_reassembly"] is True
        assert page["row_sha256"] == sha256_bytes(expected) and page["row_total_bytes"] == len(expected)
        assert page["offset_bytes"] == offset
        block = base64.b64decode(page["chunk_base64"], validate=True)
        assert len(block) == page["chunk_bytes"] and len(block) > 0
        assert block == expected[offset:offset + len(block)]
        assert page["next_offset_bytes"] in (offset + len(block), None)
        if page["next_offset_bytes"] is None:
            assert offset + len(block) == len(expected)
        blocks.append(block)
        pages.append(page)
        offset = page["next_offset_bytes"]
    assert len(pages) > 1
    assert b"".join(blocks) == expected
    assert json.loads(b"".join(blocks)) == history[0]
    assert all(page["trace_reference"] == pages[0]["trace_reference"] for page in pages)


@pytest.mark.parametrize("changes", [
    {"task_id": "other"}, {"worker_id": "other"}, {"subgoal_id": "unknown"},
    {"step_no": 3}, {"step_no": 99}, {"step_no": 0}, {"step_no": True},
    {"offset_bytes": -1}, {"offset_bytes": True}, {"offset_bytes": 10**9},
    {"max_bytes": 48_001}, {"max_bytes": True},
])
def test_chunk_requests_reject_foreign_scopes_steps_cursors_and_excess_budget(changes):
    context, _, _, _, packet = _fixture()
    with pytest.raises(ContextProjectionError):
        _chunk(context, packet, **changes)


def test_chunk_retrieval_shares_baseline_bank_and_stale_snapshot_rejections():
    baseline_context, _, _, _, baseline = _fixture("BASELINE")
    with pytest.raises(HandoffError, match="baseline has no"):
        _chunk(baseline_context, baseline)
    context, graph, history, _, packet = _fixture()
    with pytest.raises(HandoffError, match="binding differs"):
        _chunk(context, packet, expected_binding=replace(packet.binding, bank_sha256="d" * 64))
    with pytest.raises(HandoffError, match="outside the exact row"):
        _chunk(context, packet, offset_bytes=len(canonical_bytes(history[0])))
    history.append(_row(4, "second", "new observation"))
    with pytest.raises(HandoffError, match="stale"):
        _chunk(_context(graph, history), packet)


@pytest.mark.parametrize("changes", [
    {"task_id": "other"}, {"worker_id": "other"}, {"subgoal_id": "unknown"},
    {"max_bytes": 48_001}, {"max_bytes": True}, {"start_after_step": 99}, {"start_after_step": True},
])
def test_trace_requests_reject_foreign_identities_unknown_cursors_and_excess_budget(changes):
    context, _, _, _, packet = _fixture()
    with pytest.raises(ContextProjectionError):
        _trace(context, packet, **changes)


def test_trace_rejects_stale_owner_snapshot_and_packet_bank_binding():
    _, graph, history, _, packet = _fixture()
    history.append(_row(4, "second", "new observation"))
    with pytest.raises(HandoffError, match="stale"):
        _trace(_context(graph, history), packet)
    with pytest.raises(HandoffError, match="binding differs"):
        _trace(_context(graph, history[:-1]), packet,
               expected_binding=replace(packet.binding, bank_sha256="d" * 64))


def test_returned_values_and_input_mutation_cannot_change_retained_owner_trace():
    context, graph, history, _, packet = _fixture()
    exact_history = deepcopy(history)
    wire = packet.public_dict()
    wire["body"]["task"]["instruction"] = "mutated packet copy"
    history[0]["result_payload"]["content"] = "mutated caller input"
    graph.nodes["first"].objective = "mutated caller graph"
    page = _trace(context, packet)
    page["rows"][0]["result_payload"]["content"] = "mutated returned trace"
    assert _trace(context, packet)["rows"] == exact_history[:2]
    assert _accept(packet)["body"]["task"]["instruction"] == TASK["instruction"]


@pytest.mark.parametrize("change", [
    {"hidden_grader": {}}, {"instruction": "different task objective"},
    {"files": {"bad.py": 1}}, {"editable_paths": [None]}, {"commit": ""},
])
def test_task_input_must_be_public_and_match_the_working_graph(change):
    with pytest.raises(HandoffError):
        _context(_graph(), task={**TASK, **change})
