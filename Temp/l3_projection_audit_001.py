"""Read-only comparison of retained TRAINING public captures and reflection exports.

Does not import a runtime validator, inspect model/grader transcripts, mutate a
bank, or call a model. Optional output is a new diagnostic JSON only.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def ref(path):
    return {"path": str(path), "sha256": digest(Path(path).read_bytes())}


def checked(reference):
    raw = Path(reference["path"]).read_bytes()
    if digest(raw) != reference["sha256"]:
        raise ValueError("Changed diagnostic input: " + reference["path"])
    return json.loads(raw)


def argv(row):
    args = row["request_payload"]["arguments"]
    return args.get("argv", args.get("command"))


def outcome(row):
    if row["tool"] != "run_command" or row["status"] != "success":
        return "UNVERIFIED"
    command, result = argv(row), row["result_payload"]
    executable = Path(command[0]).name
    runner = executable in {"pytest", "py.test"} or (
        executable.startswith(("python", "pypy"))
        and (command[1:3] == ["-m", "pytest"] or command[1:2] == ["bin/test"]))
    text = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
    if (not runner or type(result.get("exit_code")) is not int
            or result.get("timed_out") is not False or result.get("output_truncated") is not False):
        return "UNVERIFIED"
    if result["exit_code"] == 1 and re.search(r"\b[1-9][0-9]* failed\b", text) and "AssertionError" in text:
        return "RED"
    counts = re.findall(r"\b([0-9]+) passed\b", text)
    if result["exit_code"] == 0 and counts and int(counts[-1]) > 0 and not re.search(
            r"\b[1-9][0-9]* (?:failed|errors?|skipped|xfailed)\b", text):
        return "GREEN"
    return "UNVERIFIED"


def candidate(capture):
    history = capture["history"]
    mutating = [row for row in history if row["tool"] in {"run_command", "write_file", "replace_text"}]
    green = mutating[-1]
    red = next(row for row in reversed(history) if row["step_no"] < green["step_no"]
               and row["active_node_id"] == capture["active_node_id"]
               and outcome(row) == "RED" and argv(row) == argv(green))
    edits = [row for row in history if red["step_no"] < row["step_no"] < green["step_no"]
             and row["tool"] in {"write_file", "replace_text"}]
    issues = []
    if outcome(green) != "GREEN":
        issues.append("NO_FINAL_GREEN")
    for row in edits:
        args, result = row["request_payload"]["arguments"], row["result_payload"]
        if row["status"] != "success":
            issues.append("EDIT_TOOL_ERROR")
        if row["tool"] == "replace_text":
            if (not isinstance(args.get("old_text"), str) or not args["old_text"]
                    or not isinstance(args.get("new_text"), str) or args["old_text"] == args["new_text"]
                    or result.get("replacements") != 1 or result.get("path") != args.get("path")
                    or not re.fullmatch("[a-f0-9]{64}", str(result.get("prior_sha256")))
                    or not re.fullmatch("[a-f0-9]{64}", str(result.get("new_sha256")))
                    or result.get("prior_sha256") == result.get("new_sha256")
                    or result.get("prior_sha256") != args.get("expected_file_sha256")):
                issues.append("REPLACEMENT_NOT_EXACT_GATE_B_EVIDENCE")
        elif (not isinstance(args.get("content"), str) or result.get("path") != args.get("path")
              or result.get("content_hash") != digest(args["content"].encode())
              or result.get("bytes") != len(args["content"].encode())):
            issues.append("WRITE_NOT_EXACT_GATE_B_EVIDENCE")
    return red, edits, green, issues


def audit(root, reflection):
    plan_path = reflection / "reflection-plan.json"
    plan = read(plan_path)
    catalog = read(root / "catalog.json")
    selected = {identity for job in plan["jobs"] for identity in job["capture_ids"]}
    captures = {identity: checked(catalog["captures"][identity]) for identity in selected}
    capture_refs = {identity: catalog["captures"][identity] for identity in selected}
    receipts, checkpoints = {}, {}
    for reference in plan["binding"]["source_cell_references"]:
        # Public per-cell capture receipt only, never the linked broker or grader files.
        value = checked(reference)
        needed = [item for item in value.get("captures", []) if item["receipt"]["capture_id"] in selected]
        for item in needed:
            identity = item["receipt"]["capture_id"]
            receipts[identity] = (reference, value)
            checkpoints[identity] = item
    problems, totals, jobs = [], Counter(), []
    per_capture = {}
    for identity, capture in captures.items():
        red, edits, green, issues = candidate(capture)
        edit_paths = {row["request_payload"]["arguments"].get("path") for row in edits}
        reads = [row for row in capture["history"] if row["tool"] == "read_file" and row["status"] == "success"]
        reads_of_edited_files = [row for row in reads if row["request_payload"]["arguments"].get("path") in edit_paths]
        per_capture[identity] = {"repository": capture["task"]["repository"],
            "task_id": capture["task"]["task_id"], "red_step": red["step_no"],
            "edit_steps": [row["step_no"] for row in edits], "green_step": green["step_no"],
            "syntactic_gate_b_evidence_issues": issues,
            "omitted_edited_file_read_windows": len(reads_of_edited_files),
            "omitted_edited_file_read_result_bytes": sum(row["result"]["bytes"] for row in reads_of_edited_files),
            "full_prefix_rows": len(capture["history"]),
            "candidate_sequence_rows": len(edits) + 2,
            "later_mutations": len(checkpoints[identity]["checkpoint"]["later_mutating_steps"])}
    for job in plan["jobs"]:
        export = checked(job["reflection_reference"])
        if len(export["sources"]) != len(job["capture_ids"]):
            problems.append({"job": job["job_id"], "reason": "SOURCE_COUNT_DIFFERS"})
        job_bytes = Counter()
        certifying_steps = set()
        for ordinal, identity in enumerate(sorted(job["capture_ids"])):
            source = export["sources"][ordinal]
            capture, item = captures[identity], checkpoints[identity]
            reference, cell_receipt = receipts[identity]
            expected_keys = {"source_alias": "source-" + str(ordinal + 1),
                "repository": capture["task"]["repository"], "source_revision": capture["task"]["commit"],
                "active_node_id": capture["active_node_id"], "subgoal": capture["subgoal"],
                "summary": capture["summary"], "semantic_completion": item["semantic_completion"],
                "public_test_pass_observed": capture["receipt"]["succeeded"]}
            if any(source.get(key) != value for key, value in expected_keys.items()):
                problems.append({"job": job["job_id"], "capture": identity, "reason": "SOURCE_METADATA_DIFFERS"})
            expected_ref = {"capture_sha256": capture_refs[identity]["sha256"],
                "cell_receipt_sha256": reference["sha256"], "checkpoint_sha256": digest(canonical(item["checkpoint"])),
                "sealed_state_sha256": cell_receipt["source_references"]["state.json"]["sha256"],
                "broker_event_chain_sha256": cell_receipt["source_references"]["events.jsonl"]["sha256"]}
            if source["checkpoint_reference"] != expected_ref:
                problems.append({"job": job["job_id"], "capture": identity, "reason": "CHECKPOINT_REFERENCE_DIFFERS"})
            projected = [export["trace_rows"][index] for index in source["history_row_indices"]]
            if len(projected) != len(capture["history"]):
                problems.append({"job": job["job_id"], "capture": identity, "reason": "HISTORY_LENGTH_DIFFERS"})
            for original, observed, index in zip(capture["history"], projected, source["history_row_indices"]):
                expected = {**original, "task_id": source["task_group"], "original_row_sha256": digest(canonical(original))}
                if original["tool"] in {"read_file", "list_files", "search"}:
                    del expected["result_payload"]
                    expected["result_payload_omission"] = {
                        "reason": "NONCERTIFYING_READ_OUTPUT_FULL_RESULT_RETAINED_IN_ORIGINAL_PREFIX",
                        "sha256": original["result"]["sha256"], "bytes": original["result"]["bytes"]}
                    totals["omitted_read_result_placements"] += 1
                    totals["omitted_read_result_bytes_with_placement_repeats"] += original["result"]["bytes"]
                else:
                    totals["retained_result_placements"] += 1
                totals["compared_row_placements"] += 1
                if observed != expected:
                    problems.append({"job": job["job_id"], "capture": identity,
                        "step_no": original["step_no"], "reason": "PROJECTED_ROW_DIFFERS"})
                candidate_steps = {per_capture[identity]["red_step"], per_capture[identity]["green_step"],
                                   *per_capture[identity]["edit_steps"]}
                if original["step_no"] in candidate_steps:
                    certifying_steps.add(index)
            expected_checkpoint = dict(item["checkpoint"])
            later = expected_checkpoint.pop("later_mutating_steps")
            expected_checkpoint["later_mutating_row_indices"] = source["checkpoint"]["later_mutating_row_indices"]
            projected_later = [export["later_mutations"][index] for index in source["checkpoint"]["later_mutating_row_indices"]]
            if expected_checkpoint != source["checkpoint"] or projected_later != [
                    {"task_group": source["task_group"], **row} for row in later]:
                problems.append({"job": job["job_id"], "capture": identity, "reason": "LATER_DISCLOSURE_DIFFERS"})
        for index, row in enumerate(export["trace_rows"]):
            category = "candidate_rows_bytes" if index in certifying_steps else "other_prefix_rows_bytes"
            job_bytes[category] += len(canonical(row))
        job_bytes["later_disclosure_bytes"] = len(canonical(export["later_mutations"]))
        jobs.append({"job_id": job["job_id"], "repository": job["repository"],
            "source_count": len(export["sources"]), "export_bytes": Path(job["reflection_reference"]["path"]).stat().st_size,
            "unique_rows": len(export["trace_rows"]), "candidate_rows": len(certifying_steps), **job_bytes})
    return {"schema": "skhynix/l3-projection-diagnostic/1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "TRAINING_PUBLIC_CAPTURE_AND_EXPORT_COMPARISON_ONLY", "plan_reference": ref(plan_path),
        "catalog_reference": ref(root / "catalog.json"), "selected_captures": len(captures),
        "distinct_tasks": len({capture["task"]["task_id"] for capture in captures.values()}),
        "source_capture_references": capture_refs, "projection_mismatches": problems,
        "comparison_counts": dict(totals), "capture_metadata": per_capture, "jobs": jobs,
        "model_calls": 0, "official_grader_runs": 0, "source_or_bank_mutations": 0,
        "limitations": ["No inference of model reasons from empty output", "No semantic transfer certification",
            "No official outcome selection", "Read/search/list outputs intentionally omitted", "Task instruction absent from capture descriptor and export"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--learning-root", type=Path, required=True)
    parser.add_argument("--reflection-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.learning_root, args.reflection_root)
    if args.output:
        with args.output.open("xb") as stream:
            stream.write(canonical(result) + b"\n")
    print(json.dumps({key: value for key, value in result.items()
        if key not in {"source_capture_references", "capture_metadata", "jobs"}}, indent=2))
    print("JOB_BYTE_TOTALS", dict(sum((Counter({key: row[key] for key in
        ("export_bytes", "candidate_rows_bytes", "other_prefix_rows_bytes", "later_disclosure_bytes")})
        for row in result["jobs"]), Counter())))
    print("SYNTACTIC_CANDIDATE_ISSUES", dict(Counter(reason for row in result["capture_metadata"].values()
        for reason in row["syntactic_gate_b_evidence_issues"])))
    print("SOURCES_WITH_OMITTED_EDITED_FILE_CONTEXT", sum(bool(row["omitted_edited_file_read_windows"])
        for row in result["capture_metadata"].values()))
