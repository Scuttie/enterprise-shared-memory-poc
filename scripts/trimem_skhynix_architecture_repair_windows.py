"""Pure TRAINING repair-window projections; original captures remain authority.

This module discovers factual candidates and constructs bounded public input.
It does not register an export, infer a transferable skill, inspect official
outcomes, call a model, or mutate source memory. The existing learning adapter
must register a returned public/mapping pair and verify any later proposal.
"""
from copy import deepcopy

from enterprise_memory.trimem.accounting import canonical_bytes
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_scale_reflection as reflection


INDEX_SCHEMA = "skhynix/public-repair-window-index/1.0"
POLICY = "EXACT_RED_ALL_INTERVENING_ROWS_GREEN_WITH_BOUNDED_OBSERVED_PRE_RED_CONTEXT"
LIMIT = 190000


def _window(identity, available):
    _, capture, item, _ = available[identity]
    if capture.get("receipt", {}).get("phase") != "TRAINING":
        raise learning.LearningError("Repair windows require TRAINING public captures")
    candidate = reflection._candidate(identity, capture, item)
    if candidate is None:
        raise learning.LearningError("Capture has no unchanged public RED/edit/GREEN candidate")
    rows = [row for row in capture["history"]
            if candidate["red_step"] <= row["step_no"] <= candidate["green_step"]]
    return candidate, rows


def build_repair_window_index(available):
    """Index all earliest task/action-shape representatives, without batch gates.

    Group labels are deterministic pseudonyms. No owner-count, size, repository
    pairing, semantic similarity or official-outcome filter selects survivors.
    The index is candidate evidence, never a verified-procedure declaration.
    """
    representatives, skipped = {}, []
    for identity in sorted(available):
        try:
            candidate, rows = _window(identity, available)
        except (ValueError, KeyError, TypeError):
            skipped.append({"capture_id": identity, "reason": "NO_TRAINING_PUBLIC_REPAIR_WINDOW"})
            continue
        key = candidate["task_id"], candidate["signature_sha256"]
        previous = representatives.get(key)
        rank = candidate["cutoff_step"], identity
        if previous is not None and rank >= (previous["cutoff_step"], previous["capture_id"]):
            skipped.append({"capture_id": identity, "reason": "LATER_DUPLICATE_TASK_ACTION_SHAPE"})
            continue
        if previous is not None:
            skipped.append({"capture_id": previous["capture_id"], "reason": "LATER_DUPLICATE_TASK_ACTION_SHAPE"})
        edits = [row for row in rows if row["tool"] in {"write_file", "replace_text"}]
        representatives[key] = {**candidate,
            "window_step_numbers": [row["step_no"] for row in rows],
            "edit_steps": [row["step_no"] for row in edits],
            "edit_paths": [row["request_payload"]["arguments"]["path"] for row in edits],
            "test_argv": memory._argv(rows[-1]),
            "exact_window_sha256": memory._hash(rows),
            "exact_window_bytes": len(canonical_bytes(rows)),
            "contains_empty_replacement": any(row["tool"] == "replace_text" and
                row["request_payload"]["arguments"].get("new_text") == "" for row in edits)}
    rows = []
    for candidate in sorted(representatives.values(), key=lambda row: (row["repository"], row["capture_id"])):
        candidate = dict(candidate)
        task, owner = candidate.pop("task_id"), candidate.pop("owner_user_id")
        candidate["task_group"] = "task-" + memory._hash(task)[:24]
        candidate["contributor_group"] = "contributor-" + memory._hash(owner)[:24]
        rows.append(candidate)
    return {"schema": INDEX_SCHEMA, "policy": POLICY, "representatives": rows,
        "skipped": sorted(skipped, key=lambda row: (row["capture_id"], row["reason"])),
        "candidate_shapes_are_verification": False, "semantic_transfer_claimed": False,
        "official_outcomes_used": False, "model_calls": 0, "official_grader_runs": 0}


def build_public_repair_windows(root, enrollment, available, selected, *, max_bytes=LIMIT,
                                max_context_bytes_per_source=8000, max_context_reads_per_source=2):
    """Return an existing-schema public export and its unchanged private mapping.

    All rows from the matched RED through GREEN are mandatory. Full command and
    edit results stay exact. Optional context consists of whole successful
    read_file results for edited paths observed before RED. It is explicitly
    noncertifying. Overlarge mandatory evidence raises rather than truncating.
    This function is read-only; registration is a separate caller operation.
    """
    if type(max_bytes) is not int or not 1024 <= max_bytes <= LIMIT:
        raise learning.LearningError("Repair-window byte cap must be 1024 to 190000")
    if (type(max_context_bytes_per_source) is not int or not 0 <= max_context_bytes_per_source <= LIMIT
            or type(max_context_reads_per_source) is not int or not 0 <= max_context_reads_per_source <= 8):
        raise learning.LearningError("Invalid noncertifying read-context limits")
    identities = sorted(selected)
    if not identities or len(set(identities)) != len(identities) or not set(identities) <= set(available):
        raise learning.LearningError("Repair windows require unique available capture identities")
    windows = {}
    for identity in identities:
        capture = available[identity][1]
        task = capture["task"]["task_id"]
        if (task not in enrollment["training_tasks"] or
                memory._descriptor(enrollment["training_tasks"][task]) != capture["task"] or
                enrollment["source_owners"].get(task) != capture["owner_user_id"]):
            raise learning.LearningError("Repair-window task/owner is outside its TRAINING enrollment")
        windows[identity] = _window(identity, available)
    original, mapping = learning._reflection_documents(root, enrollment, available, identities)
    # The existing mapping continues to resolve every proposal to its full
    # original immutable capture; this compact input is never the verifier.
    contexts, options, required = {}, {}, {}
    for source, identity in zip(original["sources"], identities):
        capture = available[identity][1]
        candidate, rows = windows[identity]
        required[identity] = {row["step_no"] for row in rows}
        paths = {row["request_payload"]["arguments"]["path"] for row in rows
                 if row["tool"] in {"write_file", "replace_text"}}
        # Keep every actual observed window available for deterministic fitting,
        # preferring later observations. Never synthesize a smaller read result.
        options[identity] = sorted((row for row in capture["history"]
            if row["step_no"] < candidate["red_step"] and row["tool"] == "read_file"
            and row["status"] == "success" and row["active_node_id"] == capture["active_node_id"]
            and row["request_payload"]["arguments"].get("path") in paths),
            key=lambda row: (-row["step_no"], row["request_payload"]["arguments"]["path"]))
        contexts[identity] = []

    def render():
        public = deepcopy(original)
        retained, overrides = set(), {}
        for source, identity in zip(public["sources"], identities):
            history = available[identity][1]["history"]
            selected_steps = required[identity] | {row["step_no"] for row in contexts[identity]}
            for row, old_index in zip(history, source["history_row_indices"]):
                if row["step_no"] in selected_steps:
                    retained.add(old_index)
                if row in contexts[identity]:
                    overrides[old_index] = {**row, "task_id": source["task_group"],
                        "original_row_sha256": memory._hash(row)}
        order = sorted(retained)
        reindex = {old: new for new, old in enumerate(order)}
        public["trace_rows"] = [deepcopy(overrides.get(old, original["trace_rows"][old])) for old in order]
        for source, identity in zip(public["sources"], identities):
            capture = available[identity][1]
            candidate, rows = windows[identity]
            original_indices = source["history_row_indices"]
            selected_steps = required[identity] | {row["step_no"] for row in contexts[identity]}
            included = [(row, reindex[index]) for row, index in zip(capture["history"], original_indices)
                        if row["step_no"] in selected_steps]
            source["history_row_indices"] = [index for _, index in included]
            omitted = [row for row in capture["history"] if row["step_no"] not in selected_steps]
            omitted_results = [{"step_no": row["step_no"], **row["result"]} for row, index in included
                               if "result_payload_omission" in public["trace_rows"][index]]
            source["omitted_read_outputs"] = {"count": len(omitted_results),
                "bytes": sum(row["bytes"] for row in omitted_results), "manifest_sha256": memory._hash(omitted_results)}
            source["repair_window"] = {"red_step": candidate["red_step"], "green_step": candidate["green_step"],
                "required_step_numbers": [row["step_no"] for row in rows],
                "exact_original_window_sha256": memory._hash(rows),
                "context_step_numbers": sorted(row["step_no"] for row in contexts[identity]),
                "context_role": "NONCERTIFYING_OBSERVED_PRE_RED_SOURCE_CONTEXT",
                "available_pre_red_context_windows": len(options[identity]),
                "omitted_pre_red_context_windows": len(options[identity]) - len(contexts[identity]),
                "context_limit_bytes": max_context_bytes_per_source, "context_limit_reads": max_context_reads_per_source,
                "omitted_prefix_rows": len(omitted), "omitted_prefix_rows_sha256": memory._hash(omitted),
                "original_full_prefix_sha256": memory._hash(capture["history"]),
                "original_prefix_remains_verification_authority": True}
        public["projection"] = {**public["projection"], "policy": POLICY,
            "history_encoding": "Source history_row_indices selects the exact RED-to-GREEN interval plus optional prior source reads; it is not the full checkpoint prefix.",
            "requests": "Every retained request and every command/edit result is exact; every intervening row is retained.",
            "omissions": "Earlier unrelated prefix rows are omitted with hashes/counts. Intervening noncertifying read/search/list outputs retain original omission receipts. Optional pre-RED read results are whole observed windows, never truncated.",
            "context": "Pre-RED read_file results are optional noncertifying context only. They do not prove semantic transfer or target correctness.",
            "unique_trace_rows": len(public["trace_rows"]), "original_unique_trace_rows": len(original["trace_rows"])}
        public["purpose"] = ("Compare the exact historical repair windows for a meaningful common parameterized edit procedure. "
            "Shape similarity alone proves no transfer. Use only the supplied evidence. All original checkpoint/hash references "
            "remain bound to complete authoritative captures. Optional prior reads provide noncertifying source context.")
        return public

    public = render()
    if len(canonical_bytes(public)) + 1 > max_bytes:
        raise learning.LearningError("Exact mandatory repair windows exceed context cap; select fewer sources, never truncate evidence")
    for identity in identities:
        used_bytes = 0
        for row in options[identity]:
            if len(contexts[identity]) >= max_context_reads_per_source:
                break
            size = len(canonical_bytes(row))
            if used_bytes + size > max_context_bytes_per_source:
                continue
            contexts[identity].append(row)
            candidate_public = render()
            if len(canonical_bytes(candidate_public)) + 1 > max_bytes:
                contexts[identity].pop()
                continue
            used_bytes += size
            public = candidate_public
    return public, mapping
