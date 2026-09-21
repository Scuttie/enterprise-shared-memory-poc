"""Freeze public observations from completed native training cells.

This module never runs a solver, grader, command, or model client. Gate A uses
the real local episode authority. No procedure was declared before these
training runs, so Gate B is deliberately not inferred from successful patches.
The shared bank contains historical observations, not target-verified fixes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from enterprise_memory.trimem.retrieval import MemoryGraphSnapshot, MemoryKind, MemoryRecord
from enterprise_memory.trimem.skill_memory import EpisodeEvidence, SkillMemoryStore

SCHEMA = "skhynix/native-learned-bank/1.0"
MAX_PAYLOAD_BYTES = 5500
APPLICATION = "HISTORICAL_TRAINING_OBSERVATION_VALIDATE_CURRENT_CHECKOUT"


class LearnedBankError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _bounded(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _task_descriptor(value: dict) -> dict:
    task_id = value.get("task_id", value.get("target_id"))
    commit = value.get("commit", value.get("base_commit"))
    repository = value.get("repository")
    instruction_hash = value.get("instruction_sha256")
    if "instruction" in value:
        computed = sha(value["instruction"].encode("utf-8"))
        if instruction_hash is not None and instruction_hash != computed:
            raise LearnedBankError("evaluation instruction hash differs")
        instruction_hash = computed
    if (not isinstance(task_id, str) or not task_id or
            not isinstance(repository, str) or not repository or
            not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit) or
            not isinstance(instruction_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", instruction_hash)):
        raise LearnedBankError("evaluation target requires exact public identity hashes")
    return {"task_id": task_id, "repository": repository, "commit": commit,
            "instruction_sha256": instruction_hash, "language": value.get("language", "python")}


def _read_training(run: Path, cell: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cell):
        raise LearnedBankError("invalid training cell")
    run = run.resolve()
    root = run / "cells" / cell
    plan = read(run / "plan.json")
    plan_hash = sha(canonical(plan))
    if (run / "plan.sha256").read_text().strip() != plan_hash:
        raise LearnedBankError("training plan hash differs")
    public = plan["public_task"]
    submission = read(root / "submission.json")
    result = read(root / "public-result.json")
    state = read(root / "state.json")
    arm = plan["cells"].get(cell)
    for receipt in (submission, result):
        if (receipt.get("plan_sha256") != plan_hash or receipt.get("cell") != cell or
                receipt.get("arm") != arm or receipt.get("target_id") != public["task_id"]):
            raise LearnedBankError("training receipt identity differs")
    if (result.get("official") is not True or result.get("grader_status") != "success" or
            type(result.get("resolved")) is not bool or
            result.get("separate_model_api_calls") != 0 or
            result.get("agent_completed") is not True or submission.get("agent_completed") is not True or
            state.get("status") != "SUBMITTED" or state.get("pending")):
        raise LearnedBankError("training requires a completed native official grade")
    patch_hash = file_sha(root / "submission.diff")
    if (patch_hash != submission.get("patch_sha256") or patch_hash != result.get("patch_sha256") or
            (root / "submission.diff").stat().st_size != submission.get("patch_utf8_bytes") or
            file_sha(root / "grader-private.json") != result.get("grader_private_sha256")):
        raise LearnedBankError("training sealed patch or official receipt hash differs")
    events, tail = [], "0" * 64
    for sequence, raw in enumerate((root / "tool-events.jsonl").read_bytes().splitlines(), 1):
        event = json.loads(raw)
        digest = event.pop("sha256")
        if (event.get("sequence") != sequence or event.get("previous_sha256") != tail or
                digest != sha(canonical(event))):
            raise LearnedBankError("training broker event chain differs")
        events.append(event)
        tail = digest
    if (not events or state.get("tail_sha256") != tail or result.get("tool_event_tail_sha256") != tail or
            any(value.get("actions") != len(events) for value in (state, result, submission)) or
            events[-1]["request"].get("op") != "submit" or
            events[-1]["result"].get("ok") is not True or
            events[-1]["result"]["result"].get("patch_sha256") != patch_hash):
        raise LearnedBankError("training event state or final submission differs")
    paths, actions, observations = set(), [], []
    for event in events:
        request, response = event["request"], event["result"]
        if request.get("op") != "tool" or not response.get("ok"):
            continue
        name, arguments = request.get("name"), request.get("arguments", {})
        path = arguments.get("path")
        if isinstance(path, str) and path and not path.startswith(("/", "\\")) and ".." not in Path(path).parts:
            paths.add(_bounded(path, 180))
        action = {"tool": name}
        if path:
            action["path"] = path
        if name == "run_command":
            argv = arguments.get("argv", arguments.get("command"))
            output = response.get("result", {})
            if not isinstance(argv, list) or any(not isinstance(part, str) for part in argv):
                continue
            action["argv"] = argv
            text = str(output.get("stdout", "")) + "\n" + str(output.get("stderr", ""))
            passed = re.findall(r"\b(\d+) passed\b", text)
            executable = Path(argv[0]).name if argv else ""
            python = executable.startswith("python") or executable == "pypy"
            public_runner = (executable in ("pytest", "py.test") or
                (python and len(argv) >= 2 and argv[1] == "bin/test") or
                (python and len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]))
            if output.get("exit_code") == 0 and public_runner and passed and int(passed[-1]) > 0:
                command = canonical(argv).decode("utf-8")
                if len(command.encode()) <= 1800:
                    observations.append({"argv": argv, "exit_code": 0, "passed_count": int(passed[-1]),
                        "broker_sequence": event["sequence"], "observation_sha256": sha(canonical(output))})
        actions.append(canonical(action).decode("utf-8"))
    stamp = datetime.fromtimestamp(submission["submitted_at"], timezone.utc).isoformat().replace("+00:00", "Z")
    result_hash = file_sha(root / "public-result.json")
    verification = canonical(observations[-1]["argv"]).decode() if observations else "official benchmark grader; public receipt only"
    evidence = EpisodeEvidence(
        org_id=plan["experiment_id"], user_id=plan.get("solver_user_id", "native-codex-solver"),
        repository=public["repository"], task_id=public["task_id"], revision=public["commit"],
        subgoal=_bounded(public["instruction"], 1000), summary=_bounded(submission["summary"], 1800),
        actions=tuple(actions), succeeded=result["resolved"], verification_command=verification,
        verification_evidence_hash="sha256:" + result_hash, created_at=stamp,
        artifact_hashes=(("submitted_patch", "sha256:" + patch_hash),
                         ("broker_event_tail", "sha256:" + tail),
                         ("official_receipt", "sha256:" + result["grader_private_sha256"])))
    provenance = {"task_id": public["task_id"], "repository": public["repository"],
        "revision": public["commit"], "source_timestamp": stamp, "cell": cell, "arm": arm,
        "contributor_id": evidence.user_id, "contributor_kind": "NATIVE_CODEX_SESSION_NOT_HUMAN_IDENTITY",
        "run_root": str(run), "plan_sha256": plan_hash, "public_result_sha256": result_hash,
        "patch_sha256": patch_hash, "tool_event_tail_sha256": tail,
        "official_receipt_sha256": result["grader_private_sha256"], "resolved": result["resolved"]}
    payload = {"kind": "verified_training_repository_observation", "applicability": APPLICATION,
        "source_task_id": public["task_id"], "source_revision": public["commit"],
        "repository": public["repository"], "public_training_issue": _bounded(public["instruction"], 1300),
        "observed_public_paths": sorted(paths)[:12], "public_test_observations": observations[-2:],
        "official_training_resolved": result["resolved"],
        "training_solver_interpretation": _bounded(submission["summary"], 1000),
        "interpretation_verification_limit": "Official tests verified the submitted training patch, not every prose claim.",
        "transfer_rule": "Re-read the current code and reproduce its issue before adapting any training observation. No target fix or target-version applicability is verified."}
    # Drop oldest observations and shorten prose deterministically before freeze.
    while len(canonical(payload)) > MAX_PAYLOAD_BYTES and len(payload["public_test_observations"]) > 1:
        payload["public_test_observations"].pop(0)
    if len(canonical(payload)) > MAX_PAYLOAD_BYTES:
        payload["training_solver_interpretation"] = _bounded(payload["training_solver_interpretation"], 300)
        payload["public_training_issue"] = _bounded(payload["public_training_issue"], 500)
    if len(canonical(payload)) > MAX_PAYLOAD_BYTES:
        raise LearnedBankError("bounded training payload exceeds limit")
    text = canonical(payload).decode("utf-8")
    title = "Training observation: " + _bounded(public["instruction"].splitlines()[0], 160)
    return {"episode": evidence, "provenance": provenance, "title": title, "content": text,
            "admissible_shared_knowledge": result["resolved"] and bool(observations)}


def freeze_learned_bank(output_path: Path, training_cells: list[dict], evaluation_tasks: list[dict],
                        *, cold_start: bool = False) -> dict:
    """Consume actual receipts once; the independent evaluation identities are fixed first."""
    path = Path(output_path).resolve()
    private_path = path.with_name(path.stem + ".gate-a-private.sqlite3")
    if path.exists() or private_path.exists():
        raise LearnedBankError("refusing to overwrite a frozen or partial learned bank")
    targets = [_task_descriptor(row) for row in evaluation_tasks]
    target_ids = {row["task_id"] for row in targets}
    if not targets or len(target_ids) != len(targets):
        raise LearnedBankError("evaluation target identities must be nonempty and unique")
    sources = [_read_training(Path(row["run_root"]), row["cell"]) for row in training_cells]
    training_ids = {row["provenance"]["task_id"] for row in sources}
    if ((not sources and not cold_start) or (sources and cold_start) or
            len(training_ids) != len(sources) or target_ids & training_ids):
        raise LearnedBankError("training tasks must be unique and disjoint from evaluation tasks")
    path.parent.mkdir(parents=True, exist_ok=True)
    records, episodes = [], []
    with SkillMemoryStore(private_path) as store:
        for source in sources:
            episode = store.record_episode(source["episode"])
            episodes.append({"episode_id": episode.episode_id, "content_hash": episode.content_hash,
                             "source": source["provenance"]})
            if source["admissible_shared_knowledge"]:
                content = source["content"]
                records.append({"memory_id": "native-training:" + sha(canonical(source["provenance"])),
                    "title": source["title"], "content": content,
                    "content_sha256": sha(content.encode()), "content_bytes": len(content.encode()),
                    "source": source["provenance"], "language": "python"})
    manifest = {"schema": SCHEMA, "frozen": True,
        "scientific_role": "EXPLORATORY_TRANSFER_FROM_ACTUAL_NATIVE_TRAINING",
        "evaluation_targets": sorted(targets, key=lambda row: row["task_id"]),
        "evaluation_task_ids": sorted(target_ids), "cold_start": cold_start,
        "training_task_ids": sorted(training_ids), "records": sorted(records, key=lambda row: row["memory_id"]),
        "gate_a": {"status": "EMPTY_COLD_START" if cold_start else "RECORDED_BY_SKILL_MEMORY_STORE", "episode_count": len(episodes),
                   "private_store_filename": private_path.name, "private_store_sha256": file_sha(private_path),
                   "episodes": episodes},
        "gate_b": {"status": "NOT_PROMOTED", "verified_skill_count": 0,
                   "reason": "No common parameterized procedure was predeclared and independently observed; task successes do not establish a skill."},
        "evaluation_private_episode_count": 0, "knowledge_relation_count": 0,
        "knowledge_payload_identical_between_memory_arms": True,
        "target_version_applicability_verified": False,
        "application_policy": APPLICATION, "online_learning": False,
        "patch_content_imported": False, "grader_test_content_imported": False,
        "separate_model_api_calls": 0, "source_selection_uses_evaluation_outcomes": False}
    path.write_bytes(canonical(manifest) + b"\n")
    return {"path": str(path), "sha256": file_sha(path), "training_tasks": len(sources),
            "evaluation_tasks": len(targets), "shared_records": len(records),
            "gate_a_episodes": len(episodes), "verified_skills": 0}


@dataclass(frozen=True)
class FrozenLearnedBank:
    path: Path
    sha256: str
    manifest: dict
    target: dict

    @property
    def records(self):
        return tuple(row for row in self.manifest["records"] if row["source"]["repository"] == self.target["repository"])

    @property
    def promoted_skill(self):
        if self.manifest["schema"] == "skhynix/native-learned-bank/2.0":
            from trimem_skhynix_codex_skill_bank import skill_for_bank
            return skill_for_bank(self)
        return None

    @property
    def report(self):
        if self.manifest["schema"] == "skhynix/native-learned-bank/2.0":
            from trimem_skhynix_codex_skill_bank import skill_bank_report
            return skill_bank_report(self)
        return {"schema": SCHEMA, "source_evidence_label": "ACTUAL_NATIVE_TRAINING_PUBLIC_OBSERVATIONS",
            "frozen_bank_sha256": self.sha256, "records": len(self.records),
            "training_gate_a_episode_count": self.manifest["gate_a"]["episode_count"],
            "training_task_ids": self.manifest["training_task_ids"],
            "verified_skill_count": 0, "imported_episode_count": 0,
            "target_version_applicability_verified": False, "application_policy": APPLICATION,
            "same_shared_payload_between_memory_arms": True, "online_learning": False}


def _validate_observation_manifest(manifest: dict) -> list[dict]:
    """Validate schema1 observations independently of one evaluation task."""
    if (manifest.get("schema") != SCHEMA or manifest.get("frozen") is not True or
            manifest.get("gate_b", {}).get("verified_skill_count") != 0 or
            manifest.get("evaluation_private_episode_count") != 0 or manifest.get("online_learning") is not False):
        raise LearnedBankError("unsupported learned bank contract")
    targets = [_task_descriptor(row) for row in manifest["evaluation_targets"]]
    training_ids = manifest["training_task_ids"]
    if (manifest.get("evaluation_task_ids") != sorted(row["task_id"] for row in targets) or
            len({row["task_id"] for row in targets}) != len(targets) or
            len(set(training_ids)) != len(training_ids) or set(training_ids) & {row["task_id"] for row in targets}):
        raise LearnedBankError("learned bank training/evaluation split differs")
    ids = set()
    for record in manifest["records"]:
        raw = record["content"].encode()
        source = record["source"]
        if (record["memory_id"] in ids or not 0 < len(raw) <= MAX_PAYLOAD_BYTES or
                record["content_sha256"] != sha(raw) or record["content_bytes"] != len(raw) or
                source["task_id"] not in training_ids or source["resolved"] is not True or
                json.loads(record["content"]).get("source_task_id") != source["task_id"]):
            raise LearnedBankError("shared learned record hash or provenance differs")
        ids.add(record["memory_id"])
    return targets


def load_frozen_bank(path: Path, expected_sha256: str, task: Any) -> FrozenLearnedBank:
    unresolved_path = path
    path = Path(path).resolve()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or file_sha(path) != expected_sha256:
        raise LearnedBankError("frozen learned bank hash differs or is absent")
    manifest = read(path)
    if manifest.get("schema") == "skhynix/native-diagnostic-bank/1.0":
        from trimem_skhynix_codex_diagnostic_bank import load_diagnostic_bank
        return load_diagnostic_bank(unresolved_path, expected_sha256, task)
    if manifest.get("schema") == "skhynix/native-learned-bank/2.0":
        from trimem_skhynix_codex_skill_bank import load_skill_bank
        return load_skill_bank(path, expected_sha256, task)
    targets = _validate_observation_manifest(manifest)
    target = next((row for row in targets if row["task_id"] == task.task_id), None)
    if (target is None or target["repository"] != task.repository or target["commit"] != task.commit or
            target["instruction_sha256"] != sha(task.instruction.encode())):
        raise LearnedBankError("task is outside the frozen evaluation identity scope")
    return FrozenLearnedBank(path, expected_sha256, manifest, target)


class LearnedGraphStore:
    """M2's genuine retrieval interface over the frozen shared observation bytes."""
    def __init__(self, task, bank: FrozenLearnedBank):
        self.identity = task.org_id, task.user_id, task.repository
        self.execution_views = {row["memory_id"]: row["content"].encode() for row in bank.records}
        skill = bank.promoted_skill
        if skill is not None:
            self.execution_views[skill.skill_id] = skill.execution_view().encode()
        self.content_hash = sha(canonical({"bank": bank.sha256, "target": bank.target,
            "views": {key: sha(value) for key, value in self.execution_views.items()}}))
        records = {}
        for row in bank.records:
            source = row["source"]
            diagnostic = bank.manifest["schema"] == "skhynix/native-diagnostic-bank/1.0"
            metadata = {"source_task_id": source["task_id"], "source_dataset_id": "native-codex-training",
                "source_repository": source["repository"], "source_commit": source["revision"],
                "source_timestamp": source["source_timestamp"], "bank_type": "ORG_SEMANTIC",
                "verification_evidence_sha256": source["public_result_sha256"],
                "provenance_sha256": sha(canonical(source)), "payload_sha256": row["content_sha256"],
                "permission_scope": "PUBLIC_READ", "tenant_scope": "BENCHMARK_ISOLATED",
                "version_scope": "EXACT_SOURCE_COMMIT", "path_scope": "**", "quarantined": False,
                "target_derived": source["task_id"] == task.task_id if diagnostic else False,
                "namespace": task.org_id, "graph_id": self.content_hash,
                "canonical_node_hash": row["content_sha256"], "application_policy": APPLICATION}
            if diagnostic:
                metadata.update(source_dataset_id="native-codex-public-diagnostic",
                    evidence_kind="PUBLIC_DIAGNOSTIC_INTERPRETATION_OF_COMPLETED_FAILURES",
                    scenario=bank.manifest["scenario"], source_official_resolved=False)
            records[row["memory_id"]] = MemoryRecord(row["memory_id"], MemoryKind.ORG_SEMANTIC,
                row["content"], row["content"], task.org_id, repository=task.repository,
                version=source["revision"], coverage=("operation", "precondition", "verification"),
                **({"verified": False, "source_outcome": "failed"} if diagnostic else {}),
                metadata=metadata)
        if skill is not None:
            from trimem_skhynix_codex_skill_bank import semantic_skill_record
            records[skill.skill_id] = semantic_skill_record(task, bank, skill, self.content_hash)
        self._snapshot = MemoryGraphSnapshot(MemoryKind.ORG_SEMANTIC, records, graph_hash=self.content_hash,
            query_telemetry={"candidate_count_before_filter": len(records)})

    def snapshot(self, kind, *, user_id, org_id, repository):
        if self.identity != (org_id, user_id, repository):
            raise LearnedBankError("learned source query scope differs")
        kind = MemoryKind(kind)
        return self._snapshot if kind == MemoryKind.ORG_SEMANTIC else MemoryGraphSnapshot(kind, {},
            graph_hash=sha((self.content_hash + kind.value).encode()), query_telemetry={"candidate_count_before_filter": 0})


def build_learned_seeded_store(output_path, task, bank: FrozenLearnedBank):
    if str(output_path) != ":memory:" and Path(output_path).exists():
        raise LearnedBankError("refusing to overwrite learned cell memory")
    store = SkillMemoryStore(output_path)
    try:
        entries = []
        for row in bank.records:
            # The row describes a historical observation. Revision binds this
            # transfer-view projection only; its source revision stays in content.
            knowledge = store.put_repository_knowledge(org_id=task.org_id, repository=task.repository,
                title=row["title"], content=row["content"], revision=task.commit, language=row["language"])
            entries.append({"memory_id": row["memory_id"], "knowledge_id": knowledge.knowledge_id,
                "shared_source_content_sha256": row["content_sha256"],
                "shared_source_content_bytes": row["content_bytes"], "source_revision": row["source"]["revision"],
                "transfer_view_revision": task.commit})
        if bank.promoted_skill is not None:
            from trimem_skhynix_codex_skill_bank import FrozenSkillProjectionStore
            store = FrozenSkillProjectionStore(store, task, bank)
        snapshot = store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                                  revision=task.commit, language=bank.target["language"])
        return store, {**bank.report, "language": bank.target["language"],
            "seed_snapshot_sha256": snapshot.content_hash, "entries": entries,
            "repository_knowledge_count": len(snapshot.repository_knowledge), "knowledge_relation_count": 0,
            **({"seed_skill_count": len(snapshot.skills)} if bank.promoted_skill is not None else {})}
    except BaseException:
        store.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True,
                        help="JSON with training_cells [{run_root,cell}] and evaluation_tasks public identities")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cold-start", action="store_true", help="Explicit empty bank for first training tasks")
    args = parser.parse_args()
    spec = read(args.spec)
    print(json.dumps(freeze_learned_bank(args.output, spec["training_cells"], spec["evaluation_tasks"],
                                        cold_start=args.cold_start)))


if __name__ == "__main__":
    main()
