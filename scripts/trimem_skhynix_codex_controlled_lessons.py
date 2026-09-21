"""Opt-in controlled content transfer, with no retrieval, promotion or learning.

Source-only analyst prose is frozen before assignment. The broker delivers one
assigned lesson on the first valid recall and reconstructs delivery from its
audited event journal. No independent mutable checkpoint can authorize replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import trimem_skhynix_codex_diagnostic_bank as diagnostic
import trimem_skhynix_codex_learning as learning

SCHEMA = "skhynix/native011-controlled-lessons/1.0"
LESSONS_SCHEMA = "skhynix/native011-source-lessons/1.0"
ROLE = "CONTROLLED_CONTENT_TRANSFER"
TIMING = "RETROSPECTIVE_DISJOINT_TRANSFER"
LABELS = {"A": "NONE", "B": "UNRELATED_LENGTH_MATCHED", "C": "RELEVANT_LESSON"}
BROKER_ARMS = {"A": "NO_MEMORY", "B": "EXISTING_M2", "C": "SKHYNIX"}
MAX_BYTES, MAX_INJECTIONS = 12000, 3
MAX_LESSON_BYTES = 3500
POLICY = "FIRST_VALID_RECALL_ONCE_PER_CELL"


class ControlledLessonError(ValueError):
    pass


def _fail(message):
    raise ControlledLessonError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return _sha(learning.canonical(value))


def _fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        _fail(f"Controlled {name} contains missing or forbidden fields")


def _text(value, name, maximum=256):
    if (not isinstance(value, str) or not value or value != value.strip() or
            len(value.encode()) > maximum or "\x00" in value):
        _fail(f"Controlled {name} requires bounded unpadded text")
    return value


def _digest(value, name, size=64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % size, value):
        _fail(f"Controlled {name} hash differs")
    return value


def task_descriptor(value):
    """Normalize a public CodingTask or public identity dictionary."""
    value = value.public_payload() if hasattr(value, "public_payload") else value
    if not isinstance(value, dict):
        _fail("Controlled target must be a public task")
    digest = value.get("instruction_sha256")
    if "instruction" in value:
        instruction = value["instruction"]
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction.encode()) > 200000:
            _fail("Controlled instruction requires bounded public text")
        computed = _sha(instruction.encode())
        if digest is not None and digest != computed:
            _fail("Controlled public instruction hash differs")
        digest = computed
    return {"task_id": _text(value.get("task_id"), "task id"),
        "repository": _text(value.get("repository"), "repository"),
        "commit": _digest(value.get("commit"), "commit", 40),
        "instruction_sha256": _digest(digest, "instruction")}


def _load_ref(reference):
    path = diagnostic._ref(reference)
    value = diagnostic._json(path.read_bytes())
    diagnostic._ref(reference)
    return value


def load_source_lessons(reference):
    """Rebind source prose to completed public failure evidence, without promotion."""
    value = _load_ref(reference)
    _fields(value, "schema scientific_role source_spec lessons source_official_resolved "
        "analyst_interpretation_verified verified_skill target_fix_verified manual_analyst_diagnosis gate_b_count", "source lessons")
    if (value["schema"] != LESSONS_SCHEMA or value["scientific_role"] != TIMING or
            any(value[key] is not False for key in ("source_official_resolved",
                "analyst_interpretation_verified", "verified_skill", "target_fix_verified")) or
            value["manual_analyst_diagnosis"] is not True or type(value["gate_b_count"]) is not int or
            value["gate_b_count"] != 0):
        _fail("Controlled source lessons must remain unverified analyst interpretations")
    spec = _load_ref(value["source_spec"])
    _fields(spec, "evaluation_tasks retrieval_text_policy scenario sources", "source specification")
    derived, _, _ = diagnostic._derive(spec["sources"], spec["evaluation_tasks"], spec["scenario"])
    sources = {row["descriptor"]["task_id"]: row for row in derived}
    lessons = value["lessons"]
    if not isinstance(lessons, list) or not 2 <= len(lessons) <= 32:
        _fail("Controlled lessons require a bounded nonempty comparison set")
    seen = set()
    for lesson in lessons:
        _fields(lesson, "lesson_id family source_task_id repository source_commit source_instruction_sha256 "
            "source_run_root source_cell source_patch_sha256 public_probe_sha256 source_lesson_sha256 "
            "lesson_text lesson_sha256 lesson_utf8_bytes lesson_word_count", "lesson")
        identity = _text(lesson["lesson_id"], "lesson id")
        _text(lesson["family"], "lesson family")
        if identity in seen or lesson["source_task_id"] not in sources:
            _fail("Controlled lesson identities are duplicated or outside the source specification")
        seen.add(identity)
        source = sources[lesson["source_task_id"]]
        descriptor, provenance = source["descriptor"], source["source"]["provenance"]
        expected = {"repository": descriptor["repository"], "source_commit": descriptor["commit"],
            "source_instruction_sha256": descriptor["instruction_sha256"],
            "source_run_root": source["spec"]["run_root"], "source_cell": source["spec"]["cell"],
            "source_patch_sha256": provenance["patch_sha256"],
            "public_probe_sha256": source["spec"]["public_probe_evidence"]["sha256"],
            "source_lesson_sha256": _sha(source["spec"]["lesson_text"].encode())}
        if any(lesson[key] != expected_value for key, expected_value in expected.items()):
            _fail("Controlled lesson source provenance differs from frozen public evidence")
        text = _text(lesson["lesson_text"], "lesson text", MAX_LESSON_BYTES)
        if (any(line.rstrip() != line for line in text.splitlines()) or
                lesson["lesson_sha256"] != _sha(text.encode()) or
                type(lesson["lesson_utf8_bytes"]) is not int or lesson["lesson_utf8_bytes"] != len(text.encode()) or
                type(lesson["lesson_word_count"]) is not int or lesson["lesson_word_count"] != len(text.split())):
            _fail("Controlled lesson bytes, text padding or counts differ")
    if {row["source_task_id"] for row in lessons} != set(sources):
        _fail("Controlled lesson set does not cover exactly the declared source tasks")
    diagnostic._ref(reference)
    diagnostic._ref(value["source_spec"])
    return value


@dataclass(frozen=True)
class FrozenControlledLessons:
    path: Path
    sha256: str
    manifest: dict
    source_lessons: dict
    target: dict | None

    def lesson_for(self, cell):
        if cell not in LABELS or self.target is None:
            _fail("Controlled delivery requires a bound target and cell")
        if cell == "A":
            return None
        assignment = next(row for row in self.manifest["assignments"] if row["task_id"] == self.target["task_id"])
        identity = assignment["unrelated_lesson_id" if cell == "B" else "relevant_lesson_id"]
        return next(row for row in self.source_lessons["lessons"] if row["lesson_id"] == identity)


def _validate_manifest(manifest, task=None):
    _fields(manifest, "schema frozen scientific_role transfer_timing lessons_file targets assignments "
        "experimental_arms delivery_policy max_task_injections context_budget_bytes verified_skill_count "
        "online_learning patch_content_imported grader_test_content_imported", "manifest")
    if (manifest["schema"] != SCHEMA or manifest["frozen"] is not True or manifest["scientific_role"] != ROLE or
            manifest["transfer_timing"] != TIMING or manifest["experimental_arms"] != LABELS or
            manifest["delivery_policy"] != POLICY or
            type(manifest["max_task_injections"]) is not int or manifest["max_task_injections"] != MAX_INJECTIONS or
            type(manifest["context_budget_bytes"]) is not int or manifest["context_budget_bytes"] != MAX_BYTES or
            type(manifest["verified_skill_count"]) is not int or manifest["verified_skill_count"] != 0 or
            any(manifest[key] is not False for key in ("online_learning", "patch_content_imported", "grader_test_content_imported"))):
        _fail("Controlled manifest policy, limits or scientific role differ")
    source_lessons = load_source_lessons(manifest["lessons_file"])
    targets, assignments = manifest["targets"], manifest["assignments"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 64 or not isinstance(assignments, list):
        _fail("Controlled targets and assignments must be bounded lists")
    for target in targets:
        _fields(target, "task_id repository commit instruction_sha256", "target")
        if task_descriptor(target) != target:
            _fail("Controlled target identity differs")
    ids = {row["task_id"] for row in targets}
    if len(ids) != len(targets) or ids & {row["source_task_id"] for row in source_lessons["lessons"]}:
        _fail("Controlled sources and all evaluation targets must have disjoint unique task ids")
    lessons = {row["lesson_id"]: row for row in source_lessons["lessons"]}
    for assignment in assignments:
        _fields(assignment, "task_id relevant_lesson_id unrelated_lesson_id", "assignment")
        if assignment["task_id"] not in ids or any(assignment[key] not in lessons for key in ("relevant_lesson_id", "unrelated_lesson_id")):
            _fail("Controlled assignment references an unknown target or lesson")
        relevant, unrelated = lessons[assignment["relevant_lesson_id"]], lessons[assignment["unrelated_lesson_id"]]
        if (relevant["family"] == unrelated["family"] or relevant["source_task_id"] == unrelated["source_task_id"] or
                relevant["lesson_text"] == unrelated["lesson_text"] or
                relevant["lesson_utf8_bytes"] != unrelated["lesson_utf8_bytes"]):
            _fail("Controlled B/C lessons require distinct source families and exactly matched UTF-8 byte counts")
        target = next(row for row in targets if row["task_id"] == assignment["task_id"])
        if any(row["repository"] != target["repository"] for row in (relevant, unrelated)):
            _fail("Controlled assignment source and target repository differ")
    if len(assignments) != len(targets) or {row["task_id"] for row in assignments} != ids:
        _fail("Controlled assignments must identify every target exactly once")
    for lesson in lessons.values():
        if any(target[key] in lesson["lesson_text"] for target in targets
               for key in ("task_id", "commit", "instruction_sha256")):
            _fail("Controlled source-only lesson contains a target identity hint")
    target = None
    if task is not None:
        target = task_descriptor(task)
        if target not in targets:
            _fail("Task is outside the controlled frozen identity scope")
    return source_lessons, target


def freeze_controlled_manifest(output_path, *, lessons_path, targets, assignments):
    """Freeze source-only lessons and predeclared per-target assignments; no model calls."""
    path = diagnostic._path(output_path, kind=None)
    if path.exists():
        _fail("Refusing to overwrite a controlled frozen manifest")
    reference = diagnostic._reference(Path(lessons_path))
    manifest = {"schema": SCHEMA, "frozen": True, "scientific_role": ROLE, "transfer_timing": TIMING,
        "lessons_file": reference, "targets": [task_descriptor(row) for row in targets],
        "assignments": assignments, "experimental_arms": LABELS, "delivery_policy": POLICY,
        "max_task_injections": MAX_INJECTIONS, "context_budget_bytes": MAX_BYTES,
        "verified_skill_count": 0, "online_learning": False, "patch_content_imported": False,
        "grader_test_content_imported": False}
    _validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(learning.canonical(manifest) + b"\n")
    return {"path": str(path), "sha256": _sha(path.read_bytes()), "targets": len(targets),
        "scientific_role": ROLE, "experimental_arms": LABELS}


def load_controlled_manifest(path, expected_sha256, task=None):
    reference = {"path": str(path), "sha256": expected_sha256}
    manifest = _load_ref(reference)
    source_lessons, target = _validate_manifest(manifest, task)
    diagnostic._ref(reference)
    return FrozenControlledLessons(Path(path), expected_sha256, manifest, source_lessons, target)


def projection(plan, run, cell, bank):
    """An empty memory projection; assigned content is delivered only through recall."""
    from trimem_skhynix_codex import canonical, task_from_plan
    if (cell not in LABELS or bank.target != task_descriptor(task_from_plan(plan)) or
            plan["cells"] != BROKER_ARMS or plan["limits"]["memory_bytes"] != MAX_BYTES or
            plan["limits"]["memory_injections"] != MAX_INJECTIONS):
        _fail("Controlled projection task, cell or limits differ")
    binding = {"plan_sha256": _sha(canonical(plan)), "manifest_sha256": bank.sha256,
        "lessons_sha256": bank.manifest["lessons_file"]["sha256"], "task": bank.target,
        "experiment_id": plan["experiment_id"], "solver_user_id": plan.get("solver_user_id", "native-codex-solver"),
        "cell_root": str((Path(run) / "cells" / cell).resolve()), "cell": cell}
    return {"schema": SCHEMA, "scientific_role": ROLE, "transfer_timing": TIMING,
        "arm": BROKER_ARMS[cell], "experimental_arm": LABELS[cell], "binding_sha256": _hash(binding),
        "manifest_sha256": bank.sha256, "bank": {"records": 0, "verified_skill_count": 0},
        "seed_episode_count": 0, "seed_skill_count": 0, "model_api_calls": 0,
        "assigned_lesson_count": int(cell != "A"), "native_context_replacement": False,
        "experience_writes": False, "budget": _budget(None)}


def _budget(delivery):
    count, used = (0, 0) if delivery is None else (1, delivery["byte_count"])
    return {"injections_used": count, "injections_remaining": MAX_INJECTIONS - count,
        "bytes_used": used, "bytes_remaining": MAX_BYTES - used,
        "max_task_injections": MAX_INJECTIONS, "context_budget_bytes": MAX_BYTES}


def _response(plan, cell, bank, binding, query, state, sequence):
    from trimem_skhynix_codex import task_from_plan
    from trimem_skhynix_codex_memory import _query_graph
    normalized, _ = _query_graph(task_from_plan(plan), query)
    node_id, query_hash = normalized["node_id"], _hash(normalized)
    previous = state["query_hashes"].get(node_id)
    if previous is not None and previous != query_hash:
        _fail("Controlled node_id was already bound to a different semantic query")
    lesson, injections = bank.lesson_for(cell), []
    if state["successful_recalls"] == 0 and lesson is not None:
        text, digest = lesson["lesson_text"], lesson["lesson_sha256"]
        item = {"memory_id": "controlled-lesson:" + digest, "kind": "CONTROLLED_LESSON",
            "active_node_id": node_id, "exact_text": text, "sha256": digest,
            "byte_count": lesson["lesson_utf8_bytes"], "confidence": 0.0, "margin": 0.0,
            "graph_hash": bank.sha256, "memory_state_hash": digest, "canonical_node_hash": digest,
            "source_task_id": lesson["source_task_id"], "source_evidence_label": diagnostic.LABEL,
            "verified_skill": False}
        if item["byte_count"] > MAX_BYTES:
            _fail("Controlled lesson exceeds the unchanged context budget")
        injections.append(item)
        state["delivery"] = {key: item[key] for key in ("memory_id", "sha256", "byte_count", "active_node_id")}
        state["delivery_sequence"] = sequence
    state["successful_recalls"] += 1
    state["query_hashes"][node_id] = query_hash
    return {"schema": "skhynix/native-codex-memory/1.0", "scientific_role": ROLE,
        "transfer_timing": TIMING, "arm": BROKER_ARMS[cell],
        "task_id": bank.target["task_id"], "node_id": node_id, "query_sha256": query_hash,
        "injections": injections, "new_injection_count": len(injections), "repeat": previous is not None,
        "decisions": [{"bank": "CONTROLLED_LESSON", "policy": POLICY,
            "decision": "USE" if injections else "ABSTAIN",
            "reason": "PREASSIGNED_CONTENT" if injections else "NO_LESSON" if cell == "A" else "ALREADY_DELIVERED",
            "manifest_sha256": bank.sha256, "verified_skill": False}],
        "rejections": [], "decision_telemetry": [], "budget": _budget(state["delivery"]),
        "controller_state": {**state, "query_hashes": dict(state["query_hashes"]), "binding_sha256": binding},
        "native_context_replacement": False, "model_api_calls": 0}


def restore_delivery(plan, run, cell, events, bank):
    """Validate every previous recall against audited events and immutable source bytes."""
    root = Path(run) / "cells" / cell
    expected_projection = projection(plan, run, cell, bank)
    if diagnostic._json((root / "bank-projection.json").read_bytes()) != expected_projection:
        _fail("Controlled empty projection or scope binding differs")
    state = {"mode": ROLE, "successful_recalls": 0, "query_hashes": {}, "delivery": None, "delivery_sequence": None}
    for event in events:
        if event["request"].get("op") != "recall":
            continue
        from copy import deepcopy
        candidate = deepcopy(state)
        try:
            expected = _response(plan, cell, bank, expected_projection["binding_sha256"],
                event["request"].get("query"), candidate, event["sequence"])
        except ValueError as exc:
            if (event["result"].get("ok") is not False or event["result"].get("error_type") != type(exc).__name__ or
                    event["result"].get("error") != str(exc)[:2000]):
                _fail("Controlled failed recall differs from its event-derived result")
        else:
            if event["result"].get("ok") is not True or event["result"].get("result") != expected:
                _fail("Controlled delivery differs from its immutable event-derived result")
            state = candidate
    return state


def recall_controlled(plan, run, cell, query, events, bank, sequence):
    state = restore_delivery(plan, run, cell, events, bank)
    return _response(plan, cell, bank, projection(plan, run, cell, bank)["binding_sha256"], query, state, sequence)
