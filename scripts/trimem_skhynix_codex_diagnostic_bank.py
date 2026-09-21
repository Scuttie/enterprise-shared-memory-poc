"""Explicit recovery/transfer views of failed attempts and public diagnostics.

Gate A retains the original failed episode. Analyst prose and probe expectations
remain interpretations; neither creates a successful patch or a verified skill.
All referenced source/probe/authority bytes are checked again on every load.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

import trimem_skhynix_codex_learning as learning
from enterprise_memory.trimem.skill_memory import SkillMemoryStore, canonical_hash

SCHEMA = "skhynix/native-diagnostic-bank/1.0"
PROBE_SCHEMA = "skhynix/native008-public-failure-diagnostic/1.0"
LABEL = "PUBLIC_DIAGNOSTIC_INTERPRETATION_OF_COMPLETED_FAILURES"
SCENARIOS = ("KNOWN_FAILURE_RECOVERY", "DISJOINT_TRANSFER")
MAX_LESSON_BYTES = 3500
MAX_EVIDENCE_BYTES = 32_000_000
APPLICATION = "PUBLIC_DIAGNOSTIC_HYPOTHESES_REPRODUCE_AND_VALIDATE_CURRENT_CHECKOUT"
DIAGNOSTIC_LESSON_CONTENT = "DIAGNOSTIC_LESSON_CONTENT"
EXACT_TASK_DIAGNOSTIC_ROUTE = "EXACT_TASK_DIAGNOSTIC_ROUTE"
SOURCE_FILES = ("plan.json", "plan.sha256", "cells/{cell}/submission.json", "cells/{cell}/submission.diff",
    "cells/{cell}/public-result.json", "cells/{cell}/grader-private.json", "cells/{cell}/state.json",
    "cells/{cell}/tool-events.jsonl", "cells/{cell}/workspace.json")


class DiagnosticBankError(learning.LearnedBankError):
    pass


def _fail(message: str):
    raise DiagnosticBankError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _json(raw: bytes | str):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail("nonfinite JSON is not allowed"))
        learning.canonical(value)
        return value
    except (ValueError, TypeError, UnicodeError) as exc:
        if isinstance(exc, DiagnosticBankError):
            raise
        raise DiagnosticBankError("invalid diagnostic JSON") from exc


def _path(value: Any, *, kind: str | None = "file") -> Path:
    if not isinstance(value, (str, Path)) or not str(value) or ".." in Path(value).parts:
        _fail("invalid diagnostic evidence path")
    path = Path(value).absolute()
    if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)()
           for item in (path, *path.parents)) or path.resolve() != path:
        _fail("linked diagnostic paths are not allowed")
    if kind == "file" and (not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES):
        _fail("diagnostic evidence file is absent or oversized")
    if kind == "directory" and not path.is_dir():
        _fail("diagnostic source directory is absent")
    return path


def _ref(value: dict, *, authority: bool = False) -> Path:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"} or
            not isinstance(value.get("path"), str) or not Path(value["path"]).is_absolute() or
            not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])):
        _fail("invalid diagnostic frozen reference")
    path = _path(value["path"])
    if authority and any(Path(str(path) + suffix).exists() and Path(str(path) + suffix).stat().st_size
                         for suffix in ("-wal", "-journal")):
        _fail("diagnostic authority has an active journal")
    if learning.file_sha(path) != value["sha256"]:
        _fail("diagnostic evidence hash differs")
    return path


def _reference(path: Path) -> dict:
    path = _path(path)
    return {"path": str(path), "sha256": learning.file_sha(path)}


def _text(value: Any, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        _fail(f"{label} must be nonempty bounded text")
    return value


def _stamp(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            _fail("diagnostic timestamp requires a timezone")
        return stamp
    except (AttributeError, ValueError, TypeError) as exc:
        raise DiagnosticBankError("invalid diagnostic timestamp") from exc


def _probe_observation(row: dict, source_code: str, public_python: str) -> dict:
    result = row.get("public_probe", {})
    if (result.get("argv") != [public_python, "-c", source_code] or result.get("cwd") != "." or
            type(result.get("exit_code")) is not int or result["exit_code"] != 0 or
            result.get("timed_out") is not False or result.get("output_truncated") is not False or
            not isinstance(result.get("stdout"), str) or result.get("stderr") != ""):
        _fail("public diagnostic process receipt differs")
    observed = _json(result["stdout"])
    if not isinstance(observed, dict) or set(observed) != {"observations", "passed", "total"}:
        _fail("public diagnostic observation summary differs")
    rows = observed["observations"]
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 100 or
            type(observed["passed"]) is not int or type(observed["total"]) is not int):
        _fail("public diagnostic counts are invalid")
    names = set()
    for case in rows:
        if (not isinstance(case, dict) or set(case) != {"case", "actual", "expected", "passed", "exception"} or
                not isinstance(case["case"], str) or not case["case"] or len(case["case"]) > 200 or
                case["case"] in names or type(case["passed"]) is not bool or
                not isinstance(case["expected"], str) or
                (case["actual"] is not None and not isinstance(case["actual"], str)) or
                (case["exception"] is not None and not isinstance(case["exception"], str))):
            _fail("public diagnostic cases are ambiguous or malformed")
        names.add(case["case"])
    if observed["total"] != len(rows) or observed["passed"] != sum(case["passed"] for case in rows):
        _fail("public diagnostic summary does not match its cases")
    return observed


def _probe(reference: dict, source: dict, run: Path, cell: str) -> dict:
    path = _ref(reference)
    value = _json(path.read_bytes())
    if (not isinstance(value, dict) or value.get("schema") != PROBE_SCHEMA or
            value.get("hidden_test_text_or_names_accessed") is not False or value.get("originals_unchanged") is not True or
            type(value.get("model_calls")) is not int or value["model_calls"] != 0 or
            type(value.get("official_grader_calls")) is not int or value["official_grader_calls"] != 0):
        _fail("unsupported public diagnostic evidence contract")
    if _stamp(value.get("created_utc")) < _stamp(source["provenance"]["source_timestamp"]):
        _fail("public diagnostic predates the failed submission")
    protected = value.get("protected_original_sha256")
    if not isinstance(protected, dict) or not protected:
        _fail("public diagnostic lacks original file protection")
    for original, digest in protected.items():
        _ref({"path": original, "sha256": digest})
    required = [run / "plan.json", *[run / "cells" / cell / name for name in
        ("public-result.json", "state.json", "submission.diff", "tool-events.jsonl", "workspace.json")]]
    if any(protected.get(str(original)) != learning.file_sha(original) for original in required):
        _fail("public diagnostic is not bound to the selected failed source files")
    plan = _json((run / "plan.json").read_bytes())
    workspace = _json((run / "cells" / cell / "workspace.json").read_bytes())
    candidates = value.get("results", [])
    if (not isinstance(candidates, list) or any(not isinstance(row, dict) or
            not isinstance(row.get("task_id"), str) or not row["task_id"] for row in candidates) or
            len({row.get("task_id") for row in candidates}) != len(candidates)):
        _fail("public diagnostic task identities are duplicated or malformed")
    matches = [row for row in candidates if row.get("task_id") == source["provenance"]["task_id"]]
    if len(matches) != 1:
        _fail("public diagnostic does not identify the selected failed task")
    row = matches[0]
    # The original public diagnostic generator used json.dumps defaults here.
    public_hash = learning.sha(json.dumps(plan["public_task"], sort_keys=True).encode())
    if (row.get("base_commit") != source["provenance"]["revision"] or row.get("public_task_sha256") != public_hash or
            workspace.get("plan_sha256") != source["provenance"]["plan_sha256"] or
            row.get("image") != workspace.get("image") or not isinstance(row.get("image"), str) or
            not re.search(r"@sha256:[0-9a-f]{64}$", row["image"])):
        _fail("public diagnostic task, revision, instruction or image differs")
    code = _text(row.get("probe_source"), 100_000, "public probe source")
    if not isinstance(plan.get("public_python"), str) or not plan["public_python"].startswith("/"):
        _fail("public diagnostic requires the original absolute public Python")
    if row.get("probe_sha256") != learning.sha(code.encode()):
        _fail("public probe source hash differs")
    observations = row.get("observations", [])
    if (not isinstance(observations, list) or any(not isinstance(item, dict) or
            not isinstance(item.get("cell"), str) or not item["cell"] for item in observations) or
            len({item.get("cell") for item in observations}) != len(observations)):
        _fail("public diagnostic cell identities are duplicated or malformed")
    baseline = next((item for item in observations if item.get("cell") == "BASE"), None)
    selected = next((item for item in observations if item.get("cell") == cell), None)
    if (baseline is None or selected is None or baseline.get("submission_patch_sha256") is not None or
            selected.get("submission_patch_sha256") != source["provenance"]["patch_sha256"]):
        _fail("public diagnostic baseline or selected submitted patch differs")
    original = _probe_observation(baseline, code, plan.get("public_python"))
    patched = _probe_observation(selected, code, plan.get("public_python"))
    if ([(case["case"], case["expected"]) for case in original["observations"]] !=
            [(case["case"], case["expected"]) for case in patched["observations"]] or
            original["passed"] == original["total"] or patched["passed"] == patched["total"]):
        _fail("public diagnostic requires stable expectations and residual failure observations")
    _ref(reference)
    return {"created_utc": value["created_utc"], "probe_source_sha256": row["probe_sha256"],
        "base_observation_sha256": learning.sha(learning.canonical(baseline)),
        "submitted_observation_sha256": learning.sha(learning.canonical(selected)),
        "baseline_passed": original["passed"], "submitted_passed": patched["passed"], "total": patched["total"],
        "residual_public_cases": [case["case"] for case in patched["observations"] if not case["passed"]]}


def _source(spec: dict, scenario: str) -> dict:
    fields = {"run_root", "cell", "title", "lesson_text", "public_probe_evidence"}
    if not isinstance(spec, dict) or set(spec) != fields:
        _fail("diagnostic source requires only run, cell, title, lesson and public probe reference")
    run = _path(spec["run_root"], kind="directory")
    cell = spec["cell"]
    if not isinstance(cell, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cell):
        _fail("invalid diagnostic source cell")
    title = _text(spec["title"], 240, "diagnostic title")
    lesson = _text(spec["lesson_text"], MAX_LESSON_BYTES, "analyst lesson")
    references = {name.format(cell=cell): _reference(run / name.format(cell=cell)) for name in SOURCE_FILES}
    for relative, reference in references.items():
        if relative.endswith(".json") and not relative.endswith("grader-private.json"):
            _json(_ref(reference).read_bytes())
        elif relative.endswith(".jsonl"):
            for line in _ref(reference).read_bytes().splitlines():
                _json(line)
    source = learning._read_training(run, cell)
    if source["provenance"]["resolved"] is not False or source["episode"].succeeded is not False:
        _fail("diagnostic source must be an actual completed officially unresolved attempt")
    evidence = spec["public_probe_evidence"]
    probe = _probe(evidence, source, run, cell)
    payload = {"kind": "public_failure_diagnostic_interpretation", "source_evidence_label": LABEL,
        "scenario": scenario, "source_task_id": source["provenance"]["task_id"],
        "source_revision": source["provenance"]["revision"], "repository": source["provenance"]["repository"],
        "source_official_resolved": False, "source_public_result_sha256": source["provenance"]["public_result_sha256"],
        "submitted_patch_sha256": source["provenance"]["patch_sha256"],
        "public_probe_evidence_sha256": evidence["sha256"], "public_probe": probe,
        "analyst_lesson": lesson, "analyst_interpretation_verified": False,
        "probe_expectations": "ANALYST_SELECTED_PUBLIC_EXPECTATIONS_NOT_A_BENCHMARK_ORACLE",
        "target_fix_verified": False, "verified_skill": False,
        "application_policy": APPLICATION}
    content = learning.canonical(payload).decode()
    if len(content.encode()) > learning.MAX_PAYLOAD_BYTES:
        _fail("diagnostic payload exceeds the shared memory byte bound")
    normalized = {**spec, "run_root": str(run), "public_probe_evidence": dict(evidence)}
    record = {"memory_id": "native-diagnostic:" + learning.sha(learning.canonical({"source": source["provenance"],
            "probe": evidence, "lesson_sha256": learning.sha(lesson.encode()), "scenario": scenario})),
        "title": "Public failure diagnostic: " + title, "content": content,
        "content_sha256": learning.sha(content.encode()), "content_bytes": len(content.encode()),
        "source": source["provenance"], "language": "python"}
    for reference in references.values():
        _ref(reference)
    return {"spec": normalized, "source": source, "record": record, "references": references,
        "descriptor": learning._task_descriptor(_json((run / "plan.json").read_bytes())["public_task"])}


def _derive(sources: list[dict], evaluation_tasks: list[dict], scenario: str) -> tuple[list[dict], list[dict], list[str]]:
    if scenario not in SCENARIOS:
        _fail("an explicit known diagnostic scenario is required")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        _fail("diagnostic bank requires bounded nonempty source evidence")
    if not isinstance(evaluation_tasks, list) or not evaluation_tasks:
        _fail("diagnostic bank requires evaluation identities")
    targets = sorted((learning._task_descriptor(row) for row in evaluation_tasks), key=lambda row: row["task_id"])
    if len({row["task_id"] for row in targets}) != len(targets):
        _fail("diagnostic evaluation task identities must be unique")
    derived = sorted((_source(spec, scenario) for spec in sources), key=lambda row: row["descriptor"]["task_id"])
    identities = {row["descriptor"]["task_id"]: row["descriptor"] for row in derived}
    if len(identities) != len(derived):
        _fail("diagnostic source task identities must be unique")
    overlap = sorted(set(identities) & {row["task_id"] for row in targets})
    if scenario == "DISJOINT_TRANSFER" and overlap:
        _fail("diagnostic transfer source and evaluation tasks must be disjoint")
    if scenario == "KNOWN_FAILURE_RECOVERY" and (not overlap or
            any(target["task_id"] not in identities for target in targets)):
        _fail("known failure recovery requires explicitly retained source task identities")
    if any(target != identities[target["task_id"]] for target in targets if target["task_id"] in identities):
        _fail("retained failure target differs in repository, revision or public instruction")
    return derived, targets, overlap


def _retrieval_text_policy(value: Any, *, optional: bool = False, scenario: str | None = None) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or value not in (DIAGNOSTIC_LESSON_CONTENT, EXACT_TASK_DIAGNOSTIC_ROUTE):
        _fail("unsupported diagnostic retrieval text policy")
    if value == EXACT_TASK_DIAGNOSTIC_ROUTE and scenario != "KNOWN_FAILURE_RECOVERY":
        _fail("exact-task diagnostic retrieval text policy requires KNOWN_FAILURE_RECOVERY")
    return value


def _manifest(derived: list[dict], targets: list[dict], overlap: list[str], scenario: str, gate_a: dict,
              retrieval_text_policy: str | None = None) -> dict:
    value = {"schema": SCHEMA, "frozen": True, "scenario": scenario, "scientific_role": scenario,
        "source_evidence_label": LABEL, "source_specs": [row["spec"] for row in derived],
        "source_evidence_references": [row["references"] for row in derived],
        "evaluation_targets": targets, "evaluation_task_ids": [row["task_id"] for row in targets],
        "training_task_ids": [row["descriptor"]["task_id"] for row in derived],
        "source_target_overlap_task_ids": overlap,
        "record_selection_policy": "EXACT_RETAINED_FAILURE_TASK" if scenario == "KNOWN_FAILURE_RECOVERY" else "SAME_REPOSITORY_DISJOINT_SOURCE_TASKS",
        "records": sorted((row["record"] for row in derived), key=lambda row: row["memory_id"]),
        "gate_a": gate_a, "gate_b": {"status": "NOT_PROMOTED", "verified_skill_count": 0},
        "source_official_resolved": False, "analyst_interpretations_verified": False,
        "target_fix_verified": False, "target_version_applicability_verified": False,
        "evaluation_private_episode_count": 0, "knowledge_relation_count": 0,
        "knowledge_payload_identical_between_memory_arms": True, "application_policy": APPLICATION,
        "online_learning": False, "patch_content_imported": False, "grader_test_content_imported": False,
        "separate_model_api_calls": 0, "source_selection_uses_prior_source_outcomes": True,
        "source_selection_uses_evaluation_outcomes": bool(overlap)}
    if retrieval_text_policy is not None:
        value["retrieval_text_policy"] = _retrieval_text_policy(retrieval_text_policy, scenario=scenario)
    return value


def freeze_diagnostic_bank(output_path: Path, sources: list[dict], evaluation_tasks: list[dict], *, scenario: str,
                           retrieval_text_policy: str | None = None) -> dict:
    retrieval_text_policy = _retrieval_text_policy(retrieval_text_policy, optional=True, scenario=scenario)
    path = _path(output_path, kind=None)
    private = _path(path.with_name(path.stem + ".gate-a-private.sqlite3"), kind=None)
    if path.exists() or private.exists():
        _fail("refusing to overwrite a frozen or partial diagnostic bank")
    derived, targets, overlap = _derive(sources, evaluation_tasks, scenario)
    path.parent.mkdir(parents=True, exist_ok=True)
    episodes = []
    with SkillMemoryStore(private) as store:
        for row in derived:
            episode = store.record_episode(row["source"]["episode"])
            episodes.append({"episode_id": episode.episode_id, "content_hash": episode.content_hash,
                "source": row["source"]["provenance"], "succeeded": False})
    gate_a = {"status": "RECORDED_FAILED_EPISODES_BY_SKILL_MEMORY_STORE", "episode_count": len(episodes),
        "private_store_filename": private.name, "private_store_sha256": learning.file_sha(private), "episodes": episodes}
    manifest = _manifest(derived, targets, overlap, scenario, gate_a, retrieval_text_policy)
    with path.open("xb") as stream:
        stream.write(learning.canonical(manifest) + b"\n")
    return {"path": str(path), "sha256": learning.file_sha(path), "scenario": scenario,
        "source_tasks": len(derived), "evaluation_tasks": len(targets), "shared_records": len(derived),
        "gate_a_episodes": len(episodes), "verified_skills": 0}


def _authority(path: Path, gate_a: dict, derived: list[dict]) -> None:
    if (not isinstance(gate_a, dict) or set(gate_a) != {"status", "episode_count", "private_store_filename", "private_store_sha256", "episodes"} or
            gate_a["status"] != "RECORDED_FAILED_EPISODES_BY_SKILL_MEMORY_STORE" or
            type(gate_a["episode_count"]) is not int or gate_a["episode_count"] != len(derived) or
            gate_a["private_store_filename"] != path.stem + ".gate-a-private.sqlite3"):
        _fail("diagnostic Gate A authority declaration differs")
    reference = {"path": str(path.with_name(gate_a["private_store_filename"])), "sha256": gate_a["private_store_sha256"]}
    private = _ref(reference, authority=True)
    expected_episodes = []
    try:
        with closing(sqlite3.connect(private.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute("SELECT * FROM memory_records ORDER BY record_id").fetchall()
            if (connection.execute("PRAGMA user_version").fetchone()[0] != 1 or len(rows) != len(derived) or
                    connection.execute("SELECT COUNT(*) FROM skill_support").fetchone()[0] != 0):
                _fail("diagnostic authority must contain only the original failed episodes")
            by_id = {row["record_id"]: row for row in rows}
            for item in derived:
                evidence = item["source"]["episode"]
                episode_id = "episode:" + canonical_hash({key: getattr(evidence, key)
                    for key in ("org_id", "user_id", "repository", "task_id", "revision", "subgoal")})[7:]
                expected = {"episode_id": episode_id, "evidence": asdict(evidence)}
                row = by_id.get(episode_id)
                if (row is None or row["kind"] != "episode" or row["revoked"] != 0 or
                        row["org_id"] != evidence.org_id or row["owner_user_id"] != evidence.user_id or
                        row["repository"] != evidence.repository or row["revision"] != evidence.revision or
                        learning.canonical(_json(row["payload"])) != learning.canonical(expected) or
                        row["content_hash"] != canonical_hash(expected)):
                    _fail("diagnostic Gate A episode or original failed provenance differs")
                expected_episodes.append({"episode_id": episode_id, "content_hash": row["content_hash"],
                    "source": item["source"]["provenance"], "succeeded": False})
    except sqlite3.Error as exc:
        raise DiagnosticBankError("diagnostic authority cannot be verified") from exc
    if learning.canonical(expected_episodes) != learning.canonical(gate_a["episodes"]):
        _fail("diagnostic Gate A episode list differs")
    _ref(reference, authority=True)


@dataclass(frozen=True)
class FrozenDiagnosticBank:
    path: Path
    sha256: str
    manifest: dict
    target: dict

    @property
    def records(self):
        return tuple(row for row in self.manifest["records"]
            if row["source"]["repository"] == self.target["repository"] and
            (self.manifest["scenario"] != "KNOWN_FAILURE_RECOVERY" or row["source"]["task_id"] == self.target["task_id"]))

    @property
    def promoted_skill(self):
        return None

    @property
    def report(self):
        value = {"schema": SCHEMA, "source_evidence_label": LABEL, "scenario": self.manifest["scenario"],
            "frozen_bank_sha256": self.sha256, "records": len(self.records),
            "training_gate_a_episode_count": self.manifest["gate_a"]["episode_count"],
            "training_task_ids": self.manifest["training_task_ids"], "source_official_resolved": False,
            "source_target_overlap_task_ids": self.manifest["source_target_overlap_task_ids"],
            "record_selection_policy": self.manifest["record_selection_policy"],
            "verified_skill_count": 0, "imported_episode_count": 0, "knowledge_relation_count": 0,
            "analyst_interpretations_verified": False, "target_fix_verified": False,
            "target_version_applicability_verified": False, "application_policy": APPLICATION,
            "same_shared_payload_between_memory_arms": True, "online_learning": False,
            "m2_safe_pool_compatibility": "EXISTING_SUCCESS_AND_DISJOINT_PROVENANCE_GATES_REMAIN_REQUIRED"}
        if "retrieval_text_policy" in self.manifest:
            value["retrieval_text_policy"] = self.manifest["retrieval_text_policy"]
        return value


def load_diagnostic_bank(path: Path, expected_sha256: str, task: Any) -> FrozenDiagnosticBank:
    path = _path(path)
    reference = {"path": str(path), "sha256": expected_sha256}
    _ref(reference)
    manifest = _json(path.read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        _fail("unsupported diagnostic bank schema")
    retrieval_text_policy = (_retrieval_text_policy(manifest["retrieval_text_policy"], scenario=manifest.get("scenario"))
        if "retrieval_text_policy" in manifest else None)
    try:
        derived, targets, overlap = _derive(manifest["source_specs"], manifest["evaluation_targets"], manifest["scenario"])
        _authority(path, manifest["gate_a"], derived)
        expected = _manifest(derived, targets, overlap, manifest["scenario"], manifest["gate_a"], retrieval_text_policy)
        if learning.canonical(manifest) != learning.canonical(expected):
            _fail("diagnostic bank bytes, provenance, interpretation or scope differ from its sources")
        target = next((row for row in targets if row["task_id"] == task.task_id), None)
        if (target is None or target["repository"] != task.repository or target["commit"] != task.commit or
                target["instruction_sha256"] != learning.sha(task.instruction.encode())):
            _fail("task is outside the frozen diagnostic evaluation identity scope")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, learning.LearnedBankError):
            raise
        raise DiagnosticBankError("invalid diagnostic bank contract") from exc
    _ref(reference)
    return FrozenDiagnosticBank(path, expected_sha256, manifest, target)
