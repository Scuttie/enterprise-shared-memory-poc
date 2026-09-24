"""Credential-free comparison of existing M2 and the SK hynix skill-first path.

The reader is an identical fixed replay in both arms. Executable fixture checks
validate integration, never coding performance or an official benchmark result.
No existing experiment artifact is overwritten and no provider is constructed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_memory.trimem.accounting import RawEvidenceLedger, canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import CodingTask, TriMemAgentRuntime
from enterprise_memory.trimem.arms import ActiveNodeTriMemController
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.gateway import ReplayModelGateway
from enterprise_memory.trimem.grader import ReplayGraderGateway
from enterprise_memory.trimem.retrieval import (
    InMemoryMemoryGraphStore, MemoryGraphSnapshot, MemoryKind, MemoryRecord,
    RetrievalConfig, TriMemoryRetriever,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.workspace import PublicTestResult


ORG = "fixture-organisation"
REPOSITORY = "fixtures/loaders"
REVISION = "fixture-revision-1"
SUBGOAL = "normalize filename case before extension allowlist validation"
SOURCE_IDS = ("source-json-casefold", "source-toml-casefold")
FIXED_CODE = (
    "def accepts(name):\n"
    "    if not name.casefold().endswith(('.yaml', '.yml')):\n"
    "        raise ValueError('unsupported extension')\n"
    "    return True\n"
)
INITIAL_CODE = FIXED_CODE.replace("name.casefold()", "name")


@dataclass(frozen=True)
class Scenario:
    name: str
    user: str = "alice"
    repository: str = REPOSITORY
    org: str = ORG
    include_skill: bool = True
    include_repository: bool = True
    revoke_skill: bool = False
    expected_existing_tier: str = "EPISODIC"
    expected_skill_tier: str = "SKILL"


SCENARIOS = (
    Scenario("skill_before_private_episode"),
    Scenario("cross_user_cross_repository", user="carol", repository="fixtures/another",
             expected_existing_tier="ORG_SEMANTIC"),
    Scenario("repository_fallback", user="carol", include_skill=False,
             expected_existing_tier="ORG_SEMANTIC", expected_skill_tier="REPOSITORY"),
    Scenario("private_episode_fallback", include_skill=False, include_repository=False,
             expected_skill_tier="EPISODIC"),
    Scenario("invalidated_skill_fallback", user="carol", revoke_skill=True,
             expected_existing_tier="ORG_SEMANTIC", expected_skill_tier="REPOSITORY"),
    Scenario("tenant_isolation", org="different-organisation",
             expected_existing_tier="NONE", expected_skill_tier="NONE"),
)


def executable_checks(files: Mapping[str, str]) -> PublicTestResult:
    """Run positive and negative behavior checks on the actual fixture code."""
    namespace: dict[str, Any] = {}
    try:
        exec(compile(files["target.py"], "target.py", "exec"), namespace)
        accepts = namespace["accepts"]
        for name in ("settings.yaml", "SETTINGS.YAML", "SETTINGS.YML"):
            if accepts(name) is not True:
                return PublicTestResult(False, "allowed extension rejected")
        for name in ("settings.txt", "SETTINGS.JSON", "yaml", "settings.yaml.exe"):
            try:
                accepts(name)
            except ValueError:
                continue
            return PublicTestResult(False, "disallowed extension accepted")
    except Exception as exc:
        return PublicTestResult(False, f"fixture execution failed: {type(exc).__name__}")
    return PublicTestResult(True, "7 executable extension assertions passed")


class EqualReaderReplay:
    """Record actual exposure while issuing exactly the same actions in both arms."""

    def __init__(self) -> None:
        self.responses: list[dict[str, Any]] = []
        self.first_solve_memory: list[dict[str, Any]] = []

    def __call__(self, request) -> str:
        if request.call_kind == "decompose":
            payload = {"subtasks": [{
                "id": "normalize-extension", "objective": SUBGOAL,
                "predicted_operation": "casefold filename before suffix comparison",
                "depends_on": [], "files": ["target.py"], "symbols": ["accepts"],
                "apis": ["str.casefold", "str.endswith"],
                "tests": ["uppercase YAML allowed and unrelated formats rejected"],
            }]}
        elif request.call_kind == "extract":
            payload = {"episode": {"summary": SUBGOAL,
                       "action": "casefold filename before suffix comparison",
                       "outcome": "passed"}, "semantic_candidate": None}
        else:
            if request.step_no == 1:
                _, marker, state = request.prompt.partition("\n\nSTATE:\n")
                if not marker:
                    raise AssertionError("active-node reader state is absent")
                self.first_solve_memory = json.loads(state).get("memory_for_active_subtask_only", [])
            actions = {
                1: {"tool": "read_file", "arguments": {"path": "target.py"}},
                2: {"tool": "write_file", "arguments": {"path": "target.py", "content": FIXED_CODE}},
                3: {"tool": "run_public_tests", "arguments": {}},
                4: {"tool": "complete_subtask", "arguments": {
                    "evidence": "Public executable uppercase and rejection checks passed."}},
            }
            payload = actions[request.step_no]
        self.responses.append({"kind": request.call_kind, "payload": payload})
        return json.dumps(payload)


def _template():
    from enterprise_memory.trimem.skill_memory import ProcedureTemplate
    return ProcedureTemplate(
        subgoal_signature=SUBGOAL,
        parameters=("extension",),
        preconditions=("The extension allowlist is case insensitive.",),
        steps=("Normalize filename with casefold before testing {extension} suffix.",
               "Keep all extensions outside {extension} rejected."),
        verification_command="check uppercase {extension} and disallowed suffixes",
        language="python",
    )


def _source_fixtures() -> list[dict[str, Any]]:
    template = _template()
    rows = []
    for index, (user, extension) in enumerate((("alice", ".json"), ("bob", ".toml"))):
        code = ("def accepts(name):\n"
                f"    if not name.casefold().endswith({extension!r}):\n"
                "        raise ValueError('unsupported extension')\n"
                "    return True\n")
        scope: dict[str, Any] = {}
        exec(compile(code, SOURCE_IDS[index], "exec"), scope)
        checks = [scope["accepts"]("DATA" + extension.upper()) is True]
        try:
            scope["accepts"]("DATA.TXT")
            checks.append(False)
        except ValueError:
            checks.append(True)
        if not all(checks):
            raise AssertionError("source evidence did not pass executable checks")
        rendered = template.render({"extension": extension})
        rows.append({"task_id": SOURCE_IDS[index], "user": user,
                     "repository": REPOSITORY if index == 0 else "fixtures/independent",
                     "extension": extension, "code": code,
                     "actions": list(rendered.steps), "command": rendered.verification_command,
                     "verification_evidence_hash": sha256_bytes(canonical_bytes({
                         "task": SOURCE_IDS[index], "code": code, "checks": checks})),
                     "checks_passed": len(checks)})
    return rows


def _seed_store(path: Path, scenario: Scenario, sources: list[dict[str, Any]]):
    from enterprise_memory.trimem.skill_memory import EpisodeEvidence, SkillMemoryStore
    store = SkillMemoryStore(path)
    template = _template()
    episodes = []
    for row in sources:
        episode = store.record_episode(EpisodeEvidence(
            org_id=ORG, user_id=row["user"], repository=row["repository"],
            task_id=row["task_id"], revision=REVISION, subgoal=SUBGOAL,
            summary=SUBGOAL, actions=tuple(row["actions"]), succeeded=True,
            verification_command=row["command"],
            verification_evidence_hash="sha256:" + row["verification_evidence_hash"],
            created_at="2026-01-01T00:00:00Z", procedure_hash=template.content_hash,
            parameter_bindings=(("extension", row["extension"]),),
        ))
        episodes.append(episode)
    ids: dict[str, str] = {ep.episode_id: "EPISODIC" for ep in episodes}
    if scenario.include_skill:
        skill = store.promote_skill(template, [ep.episode_id for ep in episodes],
                                    org_id=ORG, skill_id="fixture-casefold-skill")
        ids[skill.skill_id] = "SKILL"
        if scenario.revoke_skill:
            store.invalidate_skill(org_id=ORG, skill_id=skill.skill_id,
                                   reason="fixture revision invalidates applicability")
    if scenario.include_repository:
        knowledge = store.put_repository_knowledge(
            org_id=ORG, repository=REPOSITORY, title=SUBGOAL,
            content="Normalize filename with casefold before extension comparison; reject unrelated formats.",
            revision=REVISION, language="python", knowledge_id="fixture-repository-rule",
        )
        ids[knowledge.knowledge_id] = "REPOSITORY"
    return store, ids


def _existing_controller(task: CodingTask, scenario: Scenario, sources: list[dict[str, Any]]):
    private = {}
    for row in sources:
        memory_id = "existing-" + row["task_id"]
        private[memory_id] = MemoryRecord(
            memory_id, MemoryKind.EPISODIC, SUBGOAL, "\n".join(row["actions"]), ORG,
            owner_user_id=row["user"], repository=row["repository"],
            coverage=("operation", "precondition", "verification"),
            metadata={"source_task_id": row["task_id"]},
        )
    shared = {}
    if scenario.include_skill and not scenario.revoke_skill:
        shared["existing-shared-procedure"] = MemoryRecord(
            "existing-shared-procedure", MemoryKind.ORG_SEMANTIC, SUBGOAL,
            "\n".join(_template().render({"extension": ".yaml"}).steps), ORG,
            coverage=("operation", "precondition", "verification"),
        )
    if scenario.include_repository:
        shared["existing-repository-rule"] = MemoryRecord(
            "existing-repository-rule", MemoryKind.ORG_SEMANTIC, SUBGOAL,
            "Normalize filename with casefold before extension comparison; reject unrelated formats.",
            ORG, repository=REPOSITORY,
            coverage=("operation", "precondition", "verification"),
        )
    index = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: MemoryGraphSnapshot(MemoryKind.EPISODIC, private),
        MemoryKind.ORG_SEMANTIC: MemoryGraphSnapshot(MemoryKind.ORG_SEMANTIC, shared),
    })
    retriever = TriMemoryRetriever(index, RetrievalConfig(min_confidence=0.0, min_margin=0.0))
    return ActiveNodeTriMemController(retriever, task_id=task.task_id)


def _snapshot(store, scenario):
    return store.snapshot(org_id=scenario.org, user_id=scenario.user,
                          repository=scenario.repository, revision=REVISION, language="python")


def _run_cell(root: Path, task: CodingTask, controller, *, label: str, ids: dict[str, str]):
    reader = EqualReaderReplay()
    model = ReplayModelGateway(reader)
    def grader(files):
        result = executable_checks(files)
        return result.passed, result.stdout, ""
    evidence = RawEvidenceLedger(root / "evidence")
    runtime = TriMemAgentRuntime(
        runtime_lock=RuntimeLock(), model_gateway=model,
        grader_gateway=ReplayGraderGateway(grader, fixture_digest=sha256_bytes(FIXED_CODE.encode())),
        memory_controller=controller, evidence=evidence,
        checkpoint_store=FileCheckpointStore(root / "checkpoints"),
    )
    # M2 is the existing runtime slot; the comparison's distinct labels are external.
    result = runtime.run(task, arm="M2")
    injections = list(result.injections)
    tier = "NONE"
    if injections:
        tier = (str(injections[0]["kind"]) if label == "EXISTING_M2"
                else ids.get(str(injections[0]["memory_id"]), "UNKNOWN"))
    visible_ids = {str(row["memory_id"]) for row in reader.first_solve_memory}
    exposure_ok = visible_ids == {str(row["memory_id"]) for row in injections}
    return {
        "arm": label, "task_id": task.task_id, "selected_tier": tier,
        "injected_ids": [str(row["memory_id"]) for row in injections],
        "injections": len(injections),
        "injected_utf8_bytes": sum(int(row["byte_count"]) for row in injections),
        "injection_hashes": [str(row["sha256"]) for row in injections],
        "reader_exposure_verified": exposure_ok,
        "fixture_code_checks_passed": result.resolved,
        "cell_status": result.cell_status,
        "replay_model_calls": len(model.invocations), "paid_model_calls": 0,
        "replay_grader_calls": 1, "official_grader_calls": 0,
        "reader_response_sha256": sha256_bytes(canonical_bytes(reader.responses)),
        "runtime_lock_sha256": runtime.lock.content_hash,
        "patch_sha256": sha256_bytes(result.patch.encode()),
        "evidence_tail_hash": result.evidence_tail_hash,
        "evidence_verified": bool(evidence.verify()),
        "accounting": dict(result.accounting),
    }


class ChunkedReaderReplay(EqualReaderReplay):
    """Two concrete subgoals expose completed summaries and live observations."""

    def __init__(self):
        super().__init__()
        self.projections: list[dict[str, Any]] = []

    def __call__(self, request):
        if request.call_kind == "extract":
            return super().__call__(request)
        if request.call_kind == "decompose":
            payload = {"subtasks": [
                {"id": "locate-comparison", "objective": "locate case-sensitive extension comparison",
                 "predicted_operation": "read accepts suffix validation", "depends_on": [],
                 "files": ["target.py"], "symbols": ["accepts"]},
                {"id": "normalize-extension", "objective": SUBGOAL,
                 "predicted_operation": "casefold filename before suffix comparison",
                 "depends_on": ["locate-comparison"], "files": ["target.py"],
                 "symbols": ["accepts"], "apis": ["str.casefold", "str.endswith"]},
            ]}
        else:
            _, marker, state = request.prompt.partition("\n\nSTATE:\n")
            if not marker:
                raise AssertionError("reader state absent")
            body = json.loads(state)
            self.projections.append({"step": request.step_no,
                                     "working": body.get("subgoal_working_memory"),
                                     "active_history": body.get("tool_history")})
            actions = {
                1: {"tool": "read_file", "arguments": {"path": "target.py"}},
                2: {"tool": "complete_subtask", "arguments": {
                    "evidence": "Read accepts and located the case-sensitive suffix comparison."}},
                3: {"tool": "write_file", "arguments": {"path": "target.py", "content": FIXED_CODE}},
                4: {"tool": "run_public_tests", "arguments": {}},
                5: {"tool": "complete_subtask", "arguments": {
                    "evidence": "Public executable uppercase and rejection checks passed."}},
            }
            payload = actions[request.step_no]
        self.responses.append({"kind": request.call_kind, "payload": payload})
        return json.dumps(payload)


def _gate_a_chunked_restart(root: Path) -> dict[str, Any]:
    from enterprise_memory.trimem.skill_memory import SkillMemoryStore
    from enterprise_memory.trimem.skill_runtime import (
        GateAExperienceLifecycle, SkillFirstMemoryController, SkhynixAgentRuntime,
    )
    from enterprise_memory.trimem.subgoal_context import TaskSubgoalTraceStore
    from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph

    root.mkdir()
    path = root / "memory.sqlite3"
    task = CodingTask(
        task_id="target-yaml-gate-a-chunked", org_id=ORG, user_id="alice",
        repository=REPOSITORY, commit=REVISION,
        instruction="Accept case-insensitive YAML extensions and reject other formats.",
        files={"target.py": INITIAL_CODE}, editable_paths=("target.py",),
        public_test=executable_checks,
    )
    scenario = Scenario("gate_a_chunked_restart")
    grader_calls: list[str] = []
    def grader(files):
        grader_calls.append("replay-grade")
        checked = executable_checks(files)
        return checked.passed, checked.stdout, ""

    def make_runtime(store, reader):
        model = ReplayModelGateway(reader)
        runtime = SkhynixAgentRuntime(
            runtime_lock=RuntimeLock(), model_gateway=model,
            grader_gateway=ReplayGraderGateway(grader, fixture_digest=sha256_bytes(FIXED_CODE.encode())),
            memory_controller=SkillFirstMemoryController(store, task_id=task.task_id),
            evidence=RawEvidenceLedger(root / "evidence"),
            checkpoint_store=FileCheckpointStore(root / "checkpoints"),
            lifecycle=GateAExperienceLifecycle(store, clock=lambda: "2026-01-02T00:00:00Z"),
        )
        return runtime, model

    store = SkillMemoryStore(path)
    before = _snapshot(store, scenario)
    reader = ChunkedReaderReplay()
    runtime, model = make_runtime(store, reader)
    result = runtime.run(task, arm="M2")
    after = _snapshot(store, scenario)
    store.close()
    store = SkillMemoryStore(path)
    try:
        reopened = _snapshot(store, scenario)
        resumed_runtime, resumed_model = make_runtime(store, ChunkedReaderReplay())
        resumed = resumed_runtime.run(task, arm="M2", resume=True)
        resumed_snapshot = _snapshot(store, scenario)
        other_user = store.snapshot(org_id=ORG, user_id="bob", repository=REPOSITORY,
                                    revision=REVISION, language="python")
    finally:
        store.close()
    transition = next((row for row in reader.projections if row["step"] == 3), {})
    working = transition.get("working") or {}
    checkpoint = FileCheckpointStore(root / "checkpoints").load(
        result.run_id, required_config_hashes=None)
    recovered_graph = ShortTermWorkingGraph.from_snapshot(checkpoint.graph_snapshot)
    trace_store = TaskSubgoalTraceStore(recovered_graph, checkpoint.tool_history)
    recovered_trace = trace_store.retrieve_trace(task_id=task.task_id, subgoal_id="locate-comparison")
    patch_digest = sha256_bytes(result.patch.encode("utf-8"))
    patch_reference = dict(after.episodes[0].evidence.artifact_hashes).get("patch") if after.episodes else None
    patch_blob = root / "evidence" / "blobs" / patch_digest
    checks = {
        "executable_checks": result.resolved and resumed.resolved,
        "gate_a_retained_one_private_episode": len(before.episodes) == 0 and len(after.episodes) == 1,
        "record_binds_completed_target": bool(after.episodes) and after.episodes[0].evidence.task_id == task.task_id,
        "private_episode_retains_exact_patch_reference": patch_reference == "sha256:" + patch_digest,
        "referenced_patch_bytes_recoverable": patch_blob.is_file() and patch_blob.read_bytes() == result.patch.encode("utf-8"),
        "gate_a_did_not_publish_skill": not after.skills,
        "cross_user_private_history_hidden": not other_user.episodes,
        "restart_snapshot_identical": after.content_hash == reopened.content_hash == resumed_snapshot.content_hash,
        "restart_replayed_no_model_calls": not resumed_model.invocations,
        "restart_replayed_no_grader_calls": len(grader_calls) == 1,
        "restart_patch_identical": result.patch == resumed.patch,
        "subgoal_projection_present": all(isinstance(row["working"], dict) for row in reader.projections),
        "completed_subgoal_summary_visible": len(working.get("completed_subgoals", [])) == 1,
        "new_subgoal_has_no_previous_raw_history": not transition.get("active_history", {}).get("observations", []),
        "completed_trace_recoverable_from_persisted_checkpoint": len(recovered_trace) == 2
            and recovered_trace == [dict(row) for row in checkpoint.tool_history
                                    if row["active_node_id"] == "locate-comparison"],
        "evidence_verified": bool(RawEvidenceLedger(root / "evidence").verify()),
    }
    return {
        "scenario": "gate_a_chunked_runtime_restart", "passed": all(checks.values()), "checks": checks,
        "replay_model_calls": len(model.invocations), "paid_model_calls": 0,
        "replay_grader_calls": len(grader_calls), "official_grader_calls": 0,
        "resume_replay_model_calls": len(resumed_model.invocations),
        "private_episodes_retained": len(after.episodes),
        "retained_patch_reference": patch_reference,
        "snapshot_sha256": after.content_hash,
        "evidence_tail_hash": resumed.evidence_tail_hash,
        "projection_observations": reader.projections,
    }


def evaluate(output_root: str | Path) -> dict[str, Any]:
    from enterprise_memory.trimem.skill_memory import SkillMemoryStore
    from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    sources = _source_fixtures()
    cells, mechanisms = [], []
    if executable_checks({"target.py": INITIAL_CODE}).passed:
        raise AssertionError("unmodified fixture unexpectedly passes")
    if not executable_checks({"target.py": FIXED_CODE}).passed:
        raise AssertionError("fixed fixture does not pass")
    for scenario in SCENARIOS:
        scenario_root = root / scenario.name
        scenario_root.mkdir()
        path = scenario_root / "memory.sqlite3"
        store, ids = _seed_store(path, scenario, sources)
        before = _snapshot(store, scenario).content_hash
        store.close()
        store = SkillMemoryStore(path)
        reopened = _snapshot(store, scenario).content_hash
        task = CodingTask(
            task_id="target-yaml-" + scenario.name, org_id=scenario.org,
            user_id=scenario.user, repository=scenario.repository, commit=REVISION,
            instruction="Accept case-insensitive YAML extensions and reject other formats.",
            files={"target.py": INITIAL_CODE}, editable_paths=("target.py",),
            public_test=executable_checks,
        )
        try:
            old = _run_cell(scenario_root / "existing_m2", task,
                            _existing_controller(task, scenario, sources),
                            label="EXISTING_M2", ids={})
            new = _run_cell(scenario_root / "skhynix", task,
                            SkillFirstMemoryController(store, task_id=task.task_id,
                                                       parameters={"extension": ".yaml"}),
                            label="SKHYNIX_SKILL_FIRST", ids=ids)
            after = _snapshot(store, scenario).content_hash
        finally:
            store.close()
        cells.extend((old, new))
        checks = {
            "existing_tier_matches": old["selected_tier"] == scenario.expected_existing_tier,
            "skill_tier_matches": new["selected_tier"] == scenario.expected_skill_tier,
            "same_reader_responses": old["reader_response_sha256"] == new["reader_response_sha256"],
            "same_runtime_lock": old["runtime_lock_sha256"] == new["runtime_lock_sha256"],
            "same_patch": old["patch_sha256"] == new["patch_sha256"],
            "equal_replay_calls": old["replay_model_calls"] == new["replay_model_calls"],
            "restart_snapshot_identical": before == reopened,
            "source_bank_unchanged": before == after,
            "target_disjoint_sources": task.task_id not in SOURCE_IDS,
            "actual_reader_exposure": old["reader_exposure_verified"] and new["reader_exposure_verified"],
            "executable_checks": old["fixture_code_checks_passed"] and new["fixture_code_checks_passed"],
        }
        mechanisms.append({"scenario": scenario.name, "checks": checks,
                           "snapshot_sha256": before, "passed": all(checks.values())})
    supplemental = _gate_a_chunked_restart(root / "gate_a_chunked_restart")
    paths = [Path(__file__).resolve(), *(ROOT / "src/enterprise_memory/trimem" / filename
             for filename in ("skill_memory.py", "skill_runtime.py", "agent_runtime.py",
                              "subgoal_context.py", "retrieval.py", "runtime_lock.py",
                              "gateway.py", "grader.py"))]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()
    report = {
        "schema": "trimem/skhynix-mechanism-evaluation/1.0",
        "status": "PASS" if all(row["passed"] for row in mechanisms) and supplemental["passed"] else "FAIL",
        "scientific_role": "CREDENTIAL_FREE_INTEGRATION_AND_MECHANISM_ONLY",
        "interpretation": "Identical scripted actions fix every fixture irrespective of memory; these results cannot estimate coding lift, Pass@1, or held-out performance.",
        "baseline_mapping": "The same private source actions enter existing EPISODIC records; parameterized skills enter reviewed ORG_SEMANTIC and repository rules enter repository-bound ORG_SEMANTIC records in existing M2.",
        "git_head": head,
        "execution_identity": "Working-tree file hashes identify this execution; git_head is its base commit, not a new committed experiment freeze.",
        "source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in paths},
        "scenario_config_sha256": sha256_bytes(canonical_bytes([asdict(s) for s in SCENARIOS])),
        "source_fixture_sha256": sha256_bytes(canonical_bytes(sources)),
        "source_fixtures": sources,
        "mechanisms": mechanisms, "cells": cells, "supplemental_integration": supplemental,
        "totals": {
            "cells": len(cells) + 1, "comparison_cells": len(cells),
            "mechanisms_passed": sum(row["passed"] for row in mechanisms) + int(supplemental["passed"]),
            "comparison_mechanisms_passed": sum(row["passed"] for row in mechanisms),
            "replay_model_calls": sum(row["replay_model_calls"] for row in cells) + supplemental["replay_model_calls"],
            "comparison_replay_model_calls": sum(row["replay_model_calls"] for row in cells),
            "paid_model_calls": 0,
            "replay_grader_calls": len(cells) + supplemental["replay_grader_calls"],
            "official_grader_calls": 0,
            "injections": sum(row["injections"] for row in cells),
            "injected_utf8_bytes": sum(row["injected_utf8_bytes"] for row in cells),
            "supplemental_cells": 1,
            "supplemental_replay_model_calls": supplemental["replay_model_calls"],
            "supplemental_replay_grader_calls": supplemental["replay_grader_calls"],
        },
    }
    with (root / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="A new output directory; existing paths are refused.")
    args = parser.parse_args(argv)
    report = evaluate(args.output)
    print(json.dumps({"status": report["status"], "totals": report["totals"],
                      "report": str(args.output.resolve() / "report.json")}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
