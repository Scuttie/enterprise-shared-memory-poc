"""Trace-grounded L1/L2/L3 authority and immutable native retrieval adapter.

The authenticated broker owns public tool receipts and owner identities. This
module checks their exact bytes and derives observations; it does not execute
commands, call a model/grader, certify a target repair, or relax retrieval gates.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.native_architecture_context import HandoffError, HandoffMemory, _public_copy
from enterprise_memory.trimem.skill_memory import EpisodeEvidence, MemorySnapshot, ProcedureTemplate, SkillMemoryStore, canonical_hash
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController

SCHEMA = "skhynix/native-architecture-memory/1.0"
TRACE_SCHEMA = "skhynix/native-architecture-training-trace/1.0"
PROPOSAL_SCHEMA = "skhynix/native-architecture-skill-proposal/1.0"
PRECONDITION = "Inspect the current public checkout and validate the bound public test command; this workflow does not certify a target repair."
MUTATING = {"write_file", "replace_text", "run_command"}


class ArchitectureMemoryError(ValueError):
    pass


def _fail(message):
    raise ArchitectureMemoryError(message)


def _hash(value):
    return sha256_bytes(canonical_bytes(value))


def _file_hash(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _path(path):
    path = Path(path).absolute()
    if path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
        _fail("Memory paths must not be linked")
    return path


def _read(path):
    from trimem_skhynix_codex_diagnostic_bank import _json
    return _json(Path(path).read_bytes())


def _write(path, value, *, fresh=False):
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value) + b"\n"
    if fresh:
        with path.open("xb") as stream:
            stream.write(raw)
    else:
        temp = path.with_name(path.name + ".tmp")
        temp.write_bytes(raw)
        temp.replace(path)


def _ref(path):
    path = _path(path)
    return {"path": str(path), "sha256": _file_hash(path)}


def _check_ref(reference, *, authority=False):
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or
            not isinstance(reference["path"], str) or not Path(reference["path"]).is_absolute() or
            not isinstance(reference["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", reference["sha256"])):
        _fail("Invalid immutable memory reference")
    path = _path(reference["path"])
    if authority and any(Path(str(path) + suffix).exists() and Path(str(path) + suffix).stat().st_size
                         for suffix in ("-wal", "-journal")):
        _fail("Frozen memory authority has an active journal")
    if not path.is_file() or _file_hash(path) != reference["sha256"]:
        _fail("Frozen memory evidence changed or was revoked")
    return path


def _descriptor(task):
    value = task.public_payload() if isinstance(task, CodingTask) else task
    if not isinstance(value, dict):
        _fail("Memory task requires public identity fields")
    instruction_hash = value.get("instruction_sha256")
    if "instruction" in value:
        if not isinstance(value["instruction"], str) or not value["instruction"].strip():
            _fail("Memory requires nonempty public instruction text")
        computed = sha256_bytes(value["instruction"].encode())
        if instruction_hash is not None and computed != instruction_hash:
            _fail("Public task instruction hash differs")
        instruction_hash = computed
    row = {"task_id": value.get("task_id"), "repository": value.get("repository"),
        "commit": value.get("commit", value.get("base_commit")), "instruction_sha256": instruction_hash}
    if (any(not isinstance(row[key], str) or not row[key] for key in row) or
            not re.fullmatch("[a-f0-9]{40}", row["commit"]) or
            not re.fullmatch("[a-f0-9]{64}", row["instruction_sha256"])):
        _fail("Memory task requires exact public task/repository/revision/instruction hashes")
    return row


def _validate_scope(scope):
    if (not isinstance(scope, dict) or set(scope) != {"schema", "phase", "org_id", "training_tasks", "evaluation_tasks"} or
            scope.get("schema") != SCHEMA or scope.get("phase") not in {"TRAINING", "EVALUATION_QUARANTINE"} or
            not isinstance(scope.get("org_id"), str) or not scope["org_id"]):
        _fail("Invalid memory training or quarantine scope")
    train, evaluation = scope["training_tasks"], scope["evaluation_tasks"]
    for rows in (train, evaluation):
        if (not isinstance(rows, list) or any(_descriptor(row) != row for row in rows) or
                len({row["task_id"] for row in rows}) != len(rows)):
            _fail("Memory task identities must be unique exact descriptors")
    for key in ("task_id", "instruction_sha256"):
        if {row[key] for row in train} & {row[key] for row in evaluation}:
            _fail("Training and every evaluation identity/instruction must be disjoint")
    if {row["task_id"].split("--")[-1] for row in train} & {row["task_id"].split("--")[-1] for row in evaluation}:
        _fail("Original source instances overlap evaluation")


def initialize_training_memory(root, *, org_id, training_tasks, evaluation_tasks):
    return _initialize(root, org_id, training_tasks, evaluation_tasks, "TRAINING")


def _initialize(root, org_id, training_tasks, evaluation_tasks, phase):
    root = _path(root)
    scope = {"schema": SCHEMA, "phase": phase, "org_id": org_id,
        "training_tasks": sorted((_descriptor(row) for row in training_tasks), key=lambda r: r["task_id"]),
        "evaluation_tasks": sorted((_descriptor(row) for row in evaluation_tasks), key=lambda r: r["task_id"])}
    _validate_scope(scope)
    if root.exists() and any(root.iterdir()):
        if (root / "scope.json").is_file() and _read(root / "scope.json") == scope:
            return scope
        _fail("Memory authority requires a fresh or identically scoped root")
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "scope.json", scope, fresh=True)
    _write(root / "catalog.json", {"captures": {}, "proposals": {}, "observations": {},
        "knowledge": {}, "edges": [], "skills": {}}, fresh=True)
    SkillMemoryStore(root / "authority.sqlite3").close()
    return scope


@contextmanager
def _writer(root):
    import fcntl
    root = _path(root)
    with (root / "operation.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if (root / "frozen.json").exists():
                _fail("Frozen training memory cannot accept further writes")
            scope, catalog = _read(root / "scope.json"), _read(root / "catalog.json")
            _validate_scope(scope)
            with SkillMemoryStore(root / "authority.sqlite3") as store:
                yield root, scope, catalog, store
            _write(root / "catalog.json", catalog)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _public_trace(task, history):
    try:
        history = _public_copy(history)
    except HandoffError as exc:
        raise ArchitectureMemoryError(str(exc)) from exc
    if not isinstance(history, list) or not history or len(history) > 120:
        _fail("Training requires a bounded actual public trace")
    previous = 0
    arm = history[0].get("arm") if isinstance(history[0], dict) else None
    for row in history:
        required = {"task_id", "arm", "active_node_id", "step_no", "tool", "status", "request_payload", "result_payload", "request", "result"}
        if (not isinstance(row, dict) or set(row) != required or row["task_id"] != task["task_id"] or
                row["arm"] not in {"BASELINE", "PDF_MEMORY"} or row["arm"] != arm or type(row["step_no"]) is not int or
                row["step_no"] <= previous or row["status"] not in {"success", "error"}):
            _fail("Public trace row/task/sequence differs")
        for field in ("request", "result"):
            raw = canonical_bytes(row[field + "_payload"])
            if row[field] != {"sha256": sha256_bytes(raw), "bytes": len(raw)}:
                _fail("Public trace payload bytes or hashes differ")
        if (not isinstance(row["tool"], str) or not isinstance(row["active_node_id"], str) or
                not isinstance(row["request_payload"], dict) or not isinstance(row["result_payload"], dict) or
                row["request_payload"].get("tool") != row["tool"] or not isinstance(row["request_payload"].get("arguments"), dict)):
            _fail("Public trace tool request binding differs")
        previous = row["step_no"]
    return history


def _argv(row):
    args = row["request_payload"]["arguments"]
    argv = args.get("argv", args.get("command"))
    if not isinstance(argv, list) or not argv or any(not isinstance(v, str) or not v for v in argv):
        _fail("Public verification requires an exact argv list")
    return argv


def _test_outcome(row):
    if row["tool"] != "run_command" or row["status"] != "success":
        return "UNVERIFIED"
    argv, output = _argv(row), row["result_payload"]
    executable = Path(argv[0]).name
    runner = executable in {"pytest", "py.test"} or (executable.startswith(("python", "pypy")) and
        (argv[1:3] == ["-m", "pytest"] or argv[1:2] == ["bin/test"]))
    text = str(output.get("stdout", "")) + "\n" + str(output.get("stderr", ""))
    if (not runner or type(output.get("exit_code")) is not int or output.get("timed_out") is not False or
            output.get("output_truncated") is not False):
        return "UNVERIFIED"
    if output["exit_code"] == 1 and re.search(r"\b[1-9][0-9]* failed\b", text) and "AssertionError" in text:
        return "RED"
    counts = re.findall(r"\b([0-9]+) passed\b", text)
    if (output["exit_code"] == 0 and bool(counts) and int(counts[-1]) > 0 and
            not re.search(r"\b[1-9][0-9]* (?:failed|errors?|skipped|xfailed)\b", text)):
        return "GREEN"
    return "UNVERIFIED"


def _public_test(row):
    return _test_outcome(row) == "GREEN"


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
        _fail("Public source path must stay within the repository")
    return value


def _observed_action(row):
    tool = row["tool"]
    if row["status"] != "success":
        _fail("A verified procedure cannot include a failed tool operation")
    if tool in {"read_file", "write_file", "replace_text"}:
        args = row["request_payload"]["arguments"]
        action = tool + " " + _relative(args.get("path"))
        if tool == "replace_text":
            if not isinstance(args.get("old_text"), str) or not isinstance(args.get("new_text"), str):
                _fail("A verified replacement requires its exact old and new text")
            action += "\nold_text: " + args["old_text"] + "\nnew_text: " + args["new_text"]
        elif tool == "write_file":
            if not isinstance(args.get("content"), str):
                _fail("A verified write requires its exact content")
            action += "\ncontent: " + args["content"]
        return action
    if tool == "run_command":
        return tool + " " + canonical_bytes(_argv(row)).decode()
    _fail("The proposed skill uses an unsupported observable tool action")


def capture_training_trace(root, task_public, history, *, owner_user_id, active_node_id, subgoal,
                           summary, verification_step=None, created_at):
    """Gate A from broker-owned public receipts; success is derived, not a model flag."""
    task = _descriptor(task_public)
    history = _public_trace(task, history)
    selected = [row for row in history if row["active_node_id"] == active_node_id]
    if not selected:
        _fail("No public trace belongs to the captured active subgoal")
    verifier = next((row for row in selected if row["step_no"] == verification_step), None)
    if verification_step is not None and (type(verification_step) is not int or verifier is None or verifier["tool"] != "run_command"):
        _fail("Verification step is not a public command in this subgoal")
    capture = {"schema": TRACE_SCHEMA, "task": task, "owner_user_id": owner_user_id,
        "active_node_id": active_node_id, "subgoal": subgoal, "summary": summary,
        "verification_step": verification_step, "created_at": created_at, "history": history}
    capture_id = _hash(capture)
    with _writer(root) as (root, scope, catalog, store):
        allowed = scope["training_tasks"] if scope["phase"] == "TRAINING" else scope["evaluation_tasks"]
        if task not in allowed:
            _fail("Captured task is outside this training or quarantine scope")
        if capture_id in catalog["captures"]:
            return _read(_check_ref(catalog["captures"][capture_id]))["receipt"]
        evidence = EpisodeEvidence(org_id=scope["org_id"], user_id=owner_user_id,
            repository=task["repository"], task_id=task["task_id"], revision=task["commit"],
            subgoal=subgoal, summary=summary,
            actions=tuple(canonical_bytes(row["request_payload"]).decode() for row in selected),
            succeeded=verifier is not None and _public_test(verifier),
            verification_command=canonical_bytes(_argv(verifier)).decode() if verifier is not None else "",
            verification_evidence_hash="sha256:" + _hash(verifier) if verifier is not None else "",
            created_at=created_at, artifact_hashes=(("public_trace", "sha256:" + _hash(history)),))
        episode = store.record_episode(evidence)
        nodes = []
        if scope["phase"] == "TRAINING":
            mutated = False
            for row in history:
                if row["tool"] in MUTATING:
                    mutated = True
                if mutated or row["active_node_id"] != active_node_id or row["tool"] != "read_file" or row["status"] != "success":
                    continue
                result = row["result_payload"]
                path = _relative(row["request_payload"]["arguments"].get("path"))
                digest, content = result.get("full_file_sha256"), result.get("content")
                if (result.get("path") != path or not isinstance(content, str) or not isinstance(digest, str) or
                        not re.fullmatch("[a-f0-9]{64}", digest) or type(result.get("total_file_bytes")) is not int):
                    _fail("Source knowledge requires a broker full-file fingerprint and exact read window")
                if len(content.encode()) == result["total_file_bytes"] and sha256_bytes(content.encode()) != digest:
                    _fail("Complete source read differs from its full-file hash")
                # Exact line chunks retain source bytes; no analyst prose or fabricated lessons.
                chunks, current = [], ""
                for line in content.splitlines(keepends=True):
                    if current and len((current + line).encode()) > 2400:
                        chunks.append(current)
                        current = ""
                    if len(line.encode()) <= 2400:
                        current += line
                if current:
                    chunks.append(current)
                for index, chunk in enumerate(chunks):
                    payload = {"kind": "PUBLIC_SOURCE_FILE_OBSERVATION", "source_task_id": task["task_id"],
                        "source_revision": task["commit"], "path": path, "full_file_sha256": digest,
                        "source_trace_sha256": _hash(history), "source_step_no": row["step_no"],
                        "window_start_line": result.get("returned_start_line", result.get("start_line")),
                        "chunk_index": index, "observed_source": chunk,
                        "applicability": "EXACT_SOURCE_REVISION_OR_IDENTICAL_PUBLIC_BASE_FILE"}
                    knowledge = store.put_repository_knowledge(org_id=scope["org_id"], repository=task["repository"],
                        revision=task["commit"], title="Public source " + path,
                        content=canonical_bytes(payload).decode(), language="python")
                    nodes.append(knowledge.knowledge_id)
                    catalog["knowledge"][knowledge.knowledge_id] = {"source_episode_id": episode.episode_id,
                        "source_revision": task["commit"], "repository": task["repository"], "path": path,
                        "full_file_sha256": digest, "content_hash": knowledge.content_hash}
            for source, target in zip(nodes, nodes[1:]):
                if source == target:
                    continue
                store.link_repository_knowledge(source, target, "CO_OBSERVED_IN_PUBLIC_SUBGOAL",
                    org_id=scope["org_id"], repository=task["repository"])
                edge = {"source_id": source, "target_id": target, "relation": "CO_OBSERVED_IN_PUBLIC_SUBGOAL",
                    "source_episode_id": episode.episode_id, "trace_sha256": _hash(history)}
                if edge not in catalog["edges"]:
                    catalog["edges"].append(edge)
        receipt = {"capture_id": capture_id, "episode_id": episode.episode_id, "episode_content_hash": episode.content_hash,
            "source_task_id": task["task_id"], "source_revision": task["commit"], "owner_user_id": owner_user_id,
            "knowledge_ids": nodes, "succeeded": evidence.succeeded, "phase": scope["phase"],
            "verification_scope": "OBSERVED_PUBLIC_TEST_COMMAND_ONLY_NOT_OFFICIAL_TARGET_FIX"}
        capture.update(receipt=receipt, episode_evidence=asdict(evidence))
        path = root / "captures" / (capture_id + ".json")
        _write(path, capture, fresh=True)
        catalog["captures"][capture_id] = _ref(path)
        return receipt


def declare_skill_proposal(root, template, *, training_task_ids):
    """Register a worker-proposed workflow; independent recorded traces must verify it."""
    template = template if isinstance(template, ProcedureTemplate) else ProcedureTemplate(**template)
    if template.preconditions != (PRECONDITION,) or any(not step.startswith(("read_file ", "write_file ", "replace_text ", "run_command ")) for step in template.steps):
        _fail("A skill proposal must declare the bounded observable public-tool workflow and its verification limit")
    if any((step.startswith("replace_text ") and ("\nold_text: " not in step or "\nnew_text: " not in step)) or
            (step.startswith("write_file ") and "\ncontent: " not in step) for step in template.steps):
        _fail("A skill must preserve the actual parameterized edit transformation")
    with _writer(root) as (root, scope, catalog, store):
        if scope["phase"] != "TRAINING" or len(set(training_task_ids)) < 2 or not set(training_task_ids) <= {r["task_id"] for r in scope["training_tasks"]}:
            _fail("Skill proposals require at least two enrolled disjoint training tasks")
        proposal = {"schema": PROPOSAL_SCHEMA, "template": asdict(template), "template_hash": template.content_hash,
            "training_task_ids": sorted(set(training_task_ids)), "org_id": scope["org_id"],
            "verification_scope": "OBSERVED_PARAMETERIZED_TOOL_SEQUENCE_AND_PUBLIC_TEST_COMMAND"}
        identity = _hash(proposal)
        path = root / "proposals" / (identity + ".json")
        if identity not in catalog["proposals"]:
            _write(path, proposal, fresh=True)
            catalog["proposals"][identity] = _ref(path)
        return {"proposal_id": identity, **catalog["proposals"][identity]}


def verify_skill_observation(root, proposal_id, capture_id, *, bindings, step_numbers, red_step):
    with _writer(root) as (root, scope, catalog, store):
        if scope["phase"] != "TRAINING" or proposal_id not in catalog["proposals"] or capture_id not in catalog["captures"]:
            _fail("Unregistered training proposal or capture")
        proposal = _read(_check_ref(catalog["proposals"][proposal_id]))
        capture = _read(_check_ref(catalog["captures"][capture_id]))
        template = ProcedureTemplate(**proposal["template"])
        rendered = template.render(bindings)
        if capture["task"]["task_id"] not in proposal["training_task_ids"]:
            _fail("Source capture is outside the enrolled procedure tasks")
        history = _public_trace(capture["task"], capture["history"])
        if (not isinstance(step_numbers, (list, tuple)) or any(type(n) is not int for n in step_numbers) or
                list(step_numbers) != sorted(set(step_numbers))):
            _fail("Procedure steps must identify ordered unique actual tool events")
        selected = [row for number in step_numbers for row in history if row["step_no"] == number]
        if (len(selected) != len(step_numbers) or len(selected) != len(rendered.steps) or
                any(row["active_node_id"] != capture["active_node_id"] for row in selected) or
                tuple(_observed_action(row) for row in selected) != rendered.steps or
                not selected or not _public_test(selected[-1]) or
                canonical_bytes(_argv(selected[-1])).decode() != rendered.verification_command or
                any(row["step_no"] > selected[-1]["step_no"] and row["tool"] in MUTATING for row in history)):
            _fail("Procedure was not actually observed and verified by the final unchanged public test command")
        red = next((row for row in history if row["step_no"] == red_step), None)
        if (type(red_step) is not int or red is None or red["active_node_id"] != capture["active_node_id"] or
                _test_outcome(red) != "RED" or _argv(red) != _argv(selected[-1]) or red_step >= selected[-1]["step_no"]):
            _fail("Gate B requires an observed assertion-failing RED and the identical public test argv GREEN")
        edits = [row for row in selected if row["tool"] in {"write_file", "replace_text"} and red_step < row["step_no"] < selected[-1]["step_no"]]
        if not edits or any(row["tool"] == "run_command" for row in history if red_step < row["step_no"] < selected[-1]["step_no"]):
            _fail("Gate B requires observed edits between RED and GREEN without intervening unaccounted commands")
        if any(row["tool"] in {"write_file", "replace_text"} and row not in edits for row in history
                if red_step < row["step_no"] < selected[-1]["step_no"]):
            _fail("Every intervening source edit must belong to the verified workflow")
        for edit in edits:
            args = edit["request_payload"]["arguments"]
            result = edit["result_payload"]
            if edit["tool"] == "replace_text":
                if (not isinstance(args.get("old_text"), str) or not args["old_text"] or
                        not isinstance(args.get("new_text"), str) or args["old_text"] == args["new_text"] or
                        result.get("replacements") != 1 or result.get("path") != args.get("path") or
                        not re.fullmatch("[a-f0-9]{64}", str(result.get("prior_sha256"))) or
                        not re.fullmatch("[a-f0-9]{64}", str(result.get("new_sha256"))) or
                        result["prior_sha256"] == result["new_sha256"] or result["prior_sha256"] != args.get("expected_file_sha256")):
                    _fail("Gate B rejects an unobserved or no-op edit")
            elif (not isinstance(args.get("content"), str) or result.get("path") != args.get("path") or
                    result.get("content_hash") != sha256_bytes(args["content"].encode()) or result.get("bytes") != len(args["content"].encode())):
                _fail("Gate B requires exact observed file-write hashes")
            path = _relative(args.get("path"))
            if (any(part in {"tests", "test", "testing"} for part in PurePosixPath(path).parts) or
                    PurePosixPath(path).name.startswith("test_") or PurePosixPath(path).name.endswith("_test.py")):
                _fail("A workflow cannot pass Gate B by editing its tests")
        attestation = {"proposal_id": proposal_id, "proposal_sha256": catalog["proposals"][proposal_id]["sha256"],
            "capture_id": capture_id, "capture_sha256": catalog["captures"][capture_id]["sha256"],
            "bindings": bindings, "step_numbers": list(step_numbers), "observed_steps": [_hash(row) for row in selected],
            "red_step": red_step, "red_event_sha256": _hash(red), "verification_scope": "PUBLIC_ASSERTION_RED_EDIT_GREEN_NOT_OFFICIAL_TARGET_REPAIR"}
        digest = _hash(attestation)
        original = EpisodeEvidence(**capture["episode_evidence"])
        evidence = EpisodeEvidence(org_id=original.org_id, user_id=original.user_id, repository=original.repository,
            task_id=original.task_id, revision=original.revision,
            subgoal="Verified parameterized sequence: " + template.subgoal_signature,
            summary="The exact bound public tool sequence and its public test command were observed; no target repair is certified.",
            actions=rendered.steps, succeeded=True, verification_command=rendered.verification_command,
            verification_evidence_hash="sha256:" + digest, created_at=original.created_at,
            procedure_hash=template.content_hash, parameter_bindings=tuple(bindings.items()),
            artifact_hashes=(("public_trace", "sha256:" + _hash(history)), ("proposal", "sha256:" + proposal_id)))
        episode = store.record_episode(evidence)
        value = {"attestation": attestation, "episode_id": episode.episode_id, "episode_content_hash": episode.content_hash,
            "episode_evidence": asdict(evidence)}
        if digest not in catalog["observations"]:
            path = root / "observations" / (digest + ".json")
            _write(path, value, fresh=True)
            catalog["observations"][digest] = _ref(path)
        return {"observation_id": digest, "episode_id": episode.episode_id, "proposal_id": proposal_id}


def promote_verified_skill(root, proposal_id, observation_ids):
    with _writer(root) as (root, scope, catalog, store):
        if scope["phase"] != "TRAINING" or proposal_id not in catalog["proposals"]:
            _fail("Gate B requires an enrolled training proposal")
        proposal = _read(_check_ref(catalog["proposals"][proposal_id]))
        observations = [_read(_check_ref(catalog["observations"][identity])) for identity in observation_ids]
        if any(row["attestation"]["proposal_id"] != proposal_id for row in observations):
            _fail("Gate B observations belong to a different proposal")
        skill = store.promote_skill(ProcedureTemplate(**proposal["template"]),
            [row["episode_id"] for row in observations], org_id=scope["org_id"])
        catalog["skills"][skill.skill_id] = {"proposal_id": proposal_id, "observation_ids": sorted(set(observation_ids)),
            "content_hash": skill.content_hash}
        return {"status": "ACTUALLY_PROMOTED_BY_GATE_B", "skill_id": skill.skill_id,
            "content_hash": skill.content_hash, "support_count": skill.support_count, "contributor_count": skill.contributor_count}


class _ReadOnlyStore(SkillMemoryStore):
    def __init__(self, path):
        self.path = str(path)
        self._db = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA query_only=ON")


def _validate_authority(store, catalog, scope):
    if set(catalog) != {"captures", "proposals", "observations", "knowledge", "edges", "skills"}:
        _fail("Unsupported memory evidence catalog")
    expected = {}
    captures = {}
    for capture_id, ref in catalog["captures"].items():
        capture = _read(_check_ref(ref))
        history = _public_trace(capture["task"], capture["history"])
        evidence = capture["episode_evidence"]
        identity = capture["receipt"]["episode_id"]
        capture_body = {key: value for key, value in capture.items() if key not in {"receipt", "episode_evidence"}}
        selected = [row for row in history if row["active_node_id"] == capture["active_node_id"]]
        verifier = next((row for row in selected if row["step_no"] == capture["verification_step"]), None)
        if (capture_id != _hash(capture_body) or capture["schema"] != TRACE_SCHEMA or
                capture["task"] not in scope["training_tasks"] or not selected or
                evidence["org_id"] != scope["org_id"] or evidence["user_id"] != capture["owner_user_id"] or
                evidence["task_id"] != capture["task"]["task_id"] or evidence["repository"] != capture["task"]["repository"] or
                evidence["revision"] != capture["task"]["commit"] or evidence["subgoal"] != capture["subgoal"] or
                evidence["summary"] != capture["summary"] or evidence["created_at"] != capture["created_at"] or
                evidence["actions"] != [canonical_bytes(row["request_payload"]).decode() for row in selected] or
                evidence["succeeded"] != (verifier is not None and _public_test(verifier))):
            _fail("Private episode is not grounded in its bound public source trace")
        captures[identity] = capture
        expected[identity] = canonical_hash({"episode_id": identity, "evidence": evidence})
    for proposal_id, ref in catalog["proposals"].items():
        proposal = _read(_check_ref(ref))
        template = ProcedureTemplate(**proposal["template"])
        if (proposal_id != _hash(proposal) or proposal["schema"] != PROPOSAL_SCHEMA or
                proposal["org_id"] != scope["org_id"] or template.content_hash != proposal["template_hash"] or
                template.preconditions != (PRECONDITION,) or len(set(proposal["training_task_ids"])) < 2 or
                not set(proposal["training_task_ids"]) <= {row["task_id"] for row in scope["training_tasks"]}):
            _fail("Unbound or unsupported parameterized skill proposal")
    for observation_id, ref in catalog["observations"].items():
        observation = _read(_check_ref(ref))
        attestation = observation["attestation"]
        if (observation_id != _hash(attestation) or
                attestation["proposal_id"] not in catalog["proposals"] or attestation["capture_id"] not in catalog["captures"] or
                attestation["proposal_sha256"] != catalog["proposals"][attestation["proposal_id"]]["sha256"] or
                attestation["capture_sha256"] != catalog["captures"][attestation["capture_id"]]["sha256"] or
                observation["episode_evidence"]["verification_evidence_hash"] != "sha256:" + observation_id):
            _fail("Unbound verified skill observation")
        expected[observation["episode_id"]] = observation["episode_content_hash"]
    expected.update({key: row["content_hash"] for key, row in catalog["knowledge"].items()})
    expected.update({key: row["content_hash"] for key, row in catalog["skills"].items()})
    rows = store._db.execute("SELECT * FROM memory_records ORDER BY record_id").fetchall()
    if {row["record_id"]: row["content_hash"] for row in rows} != expected or any(row["revoked"] for row in rows):
        _fail("Memory authority contains ungrounded, changed or revoked records")
    for row in rows:
        store._verify(row)
        if row["kind"] == "skill":
            store._skill(row)
        elif row["kind"] == "knowledge":
            knowledge = store._knowledge(row)
            source = catalog["knowledge"][knowledge.knowledge_id]
            capture = captures.get(source["source_episode_id"])
            payload = json.loads(knowledge.content)
            if capture is None:
                _fail("Repository knowledge has no captured source episode")
            event = next((item for item in capture["history"] if item["step_no"] == payload.get("source_step_no")), None)
            if (event is None or event["tool"] != "read_file" or event["status"] != "success" or
                    event["active_node_id"] != capture["active_node_id"] or
                    any(item["tool"] in MUTATING for item in capture["history"] if item["step_no"] <= event["step_no"]) or
                    knowledge.revision != source["source_revision"] or knowledge.revision != capture["task"]["commit"] or
                    knowledge.repository != source["repository"] or knowledge.repository != capture["task"]["repository"] or
                    knowledge.org_id != scope["org_id"] or payload.get("source_revision") != knowledge.revision or
                    payload.get("source_task_id") != capture["task"]["task_id"] or payload.get("source_trace_sha256") != _hash(capture["history"]) or
                    payload.get("kind") != "PUBLIC_SOURCE_FILE_OBSERVATION" or
                    payload.get("applicability") != "EXACT_SOURCE_REVISION_OR_IDENTICAL_PUBLIC_BASE_FILE" or
                    payload.get("path") != source["path"] or payload.get("path") != event["result_payload"].get("path") or
                    payload.get("full_file_sha256") != source["full_file_sha256"] or source["full_file_sha256"] != event["result_payload"].get("full_file_sha256") or
                    not isinstance(payload.get("observed_source"), str) or not payload["observed_source"] or
                    payload["observed_source"] not in event["result_payload"].get("content", "")):
                _fail("Repository knowledge is not grounded in unchanged original public source bytes")
    actual_edges = {tuple(row) for row in store._db.execute("SELECT source_id,target_id,relation FROM knowledge_relations")}
    if actual_edges != {(row["source_id"], row["target_id"], row["relation"]) for row in catalog["edges"]}:
        _fail("Repository relations differ from grounded source observations")
    for edge in catalog["edges"]:
        capture = captures.get(edge["source_episode_id"])
        if (capture is None or edge["relation"] != "CO_OBSERVED_IN_PUBLIC_SUBGOAL" or edge["trace_sha256"] != _hash(capture["history"]) or
                any(catalog["knowledge"][key]["source_episode_id"] != edge["source_episode_id"] for key in (edge["source_id"], edge["target_id"]))):
            _fail("Repository edge is not a relation observed in the same public source subgoal")
    return {kind: sum(row["kind"] == kind for row in rows) for kind in ("episode", "knowledge", "skill")}


def freeze_training_bank(root, output_path, *, require_verified_skill=False):
    if type(require_verified_skill) is not bool:
        _fail("Positive Gate B requirement must be a boolean guard")
    output = _path(output_path)
    authority = output.with_name(output.stem + ".private.sqlite3")
    if output.exists() or authority.exists():
        _fail("Refusing to overwrite a frozen memory bank")
    with _writer(root) as (root, scope, catalog, store):
        if scope["phase"] != "TRAINING":
            _fail("Evaluation quarantine cannot become a retrieval bank")
        counts = _validate_authority(store, catalog, scope)
        if require_verified_skill and counts["skill"] == 0:
            _fail("The frozen bank requires at least one actually promoted Gate B skill")
        output.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(authority) as destination:
            store._db.backup(destination)
        manifest = {"schema": SCHEMA, "frozen": True, "scope": scope, "catalog": catalog,
            "authority": _ref(authority), "source_authority": _ref(root / "authority.sqlite3"),
            "layer_counts": {"L1_episodes": counts["episode"], "L2_nodes": counts["knowledge"],
                "L2_edges": len(catalog["edges"]), "L3_skills": counts["skill"]},
            "retrieval": "UNCHANGED_SKILL_REPOSITORY_EPISODE_CONTROLLER",
            "source_revisions_retagged": False, "forced_delivery": False, "evaluation_writes": "SEPARATE_QUARANTINE_ONLY"}
        _write(output, manifest, fresh=True)
        reference = _ref(output)
        _write(root / "frozen.json", reference, fresh=True)
        return {**reference, "layer_counts": manifest["layer_counts"]}


class FrozenArchitectureMemory:
    def __init__(self, path, expected_sha256, *, checkout_root=None):
        self.reference = {"path": str(_path(path)), "sha256": expected_sha256}
        self.manifest = _read(_check_ref(self.reference))
        if (set(self.manifest) != {"schema", "frozen", "scope", "catalog", "authority", "source_authority", "layer_counts", "retrieval", "source_revisions_retagged", "forced_delivery", "evaluation_writes"} or
                self.manifest.get("schema") != SCHEMA or self.manifest.get("frozen") is not True or
                self.manifest.get("retrieval") != "UNCHANGED_SKILL_REPOSITORY_EPISODE_CONTROLLER" or
                self.manifest.get("source_revisions_retagged") is not False or self.manifest.get("forced_delivery") is not False or
                self.manifest.get("evaluation_writes") != "SEPARATE_QUARANTINE_ONLY"):
            _fail("Unsupported frozen architecture bank")
        _validate_scope(self.manifest["scope"])
        if self.manifest["scope"]["phase"] != "TRAINING":
            _fail("Only executed training authority may feed evaluation retrieval")
        self._check()
        self.store = _ReadOnlyStore(_check_ref(self.manifest["authority"], authority=True))
        try:
            counts = _validate_authority(self.store, self.manifest["catalog"], self.manifest["scope"])
            if self.manifest["layer_counts"] != {"L1_episodes": counts["episode"], "L2_nodes": counts["knowledge"],
                    "L2_edges": len(self.manifest["catalog"]["edges"]), "L3_skills": counts["skill"]}:
                _fail("Frozen memory layer counts do not match real authority records")
        except BaseException:
            self.store.close()
            raise
        self.checkout_root = _path(checkout_root) if checkout_root is not None else None

    def _check(self):
        _check_ref(self.reference)
        _check_ref(self.manifest["authority"], authority=True)
        _check_ref(self.manifest["source_authority"], authority=True)
        for key in ("captures", "proposals", "observations"):
            for ref in self.manifest["catalog"][key].values():
                _check_ref(ref)

    def bind_task(self, task):
        if task.org_id != self.manifest["scope"]["org_id"] or _descriptor(task) not in self.manifest["scope"]["evaluation_tasks"]:
            _fail("Task is outside the frozen architecture evaluation scope")

    def snapshot(self, *, org_id, user_id, repository, revision="", language=""):
        self._check()
        if org_id != self.manifest["scope"]["org_id"]:
            _fail("Memory organisation scope differs")
        base = self.store.snapshot(org_id=org_id, user_id=user_id, repository=repository, revision=revision, language=language)
        knowledge = {row.knowledge_id: row for row in base.repository_knowledge}
        proofs = {}
        if self.checkout_root is not None:
            head = subprocess.run(["git", "-C", str(self.checkout_root), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True).stdout.strip()
            if head != revision:
                _fail("Applicability checkout is not at the bound target base commit")
            for identity, source in self.manifest["catalog"]["knowledge"].items():
                if identity in knowledge or source["repository"] != repository:
                    continue
                path = _relative(source["path"])
                result = subprocess.run(["git", "-C", str(self.checkout_root), "show", revision + ":" + path],
                    capture_output=True, check=False)
                if result.returncode == 0 and sha256_bytes(result.stdout) == source["full_file_sha256"]:
                    row = self.store._db.execute("SELECT * FROM memory_records WHERE record_id=?", (identity,)).fetchone()
                    item = self.store._knowledge(row)
                    if item.language and item.language.lower() != language.lower():
                        continue
                    knowledge[identity] = item
                    proofs[identity] = {"source_revision": item.revision, "target_revision": revision,
                        "path": path, "identical_public_base_file_sha256": source["full_file_sha256"]}
        ordered = tuple(knowledge[key] for key in sorted(knowledge))
        edges = tuple((row["source_id"], row["target_id"], 1.0) for row in self.manifest["catalog"]["edges"]
            if row["source_id"] in knowledge and row["target_id"] in knowledge)
        digest = canonical_hash({"base_snapshot": base.content_hash, "bank_sha256": self.reference["sha256"],
            "knowledge": [row.content_hash for row in ordered], "edges": edges, "applicability": proofs})
        return MemorySnapshot(base.skills, ordered, base.episodes, digest, edges)

    def controller(self, task, *, parameters=None):
        self.bind_task(task)
        return SkillFirstMemoryController(self, task_id=task.task_id, parameters=parameters)

    def close(self):
        self.store.close()


def load_frozen_bank(path, expected_sha256, task=None, *, checkout_root=None):
    bank = FrozenArchitectureMemory(path, expected_sha256, checkout_root=checkout_root)
    if task is not None:
        try:
            bank.bind_task(task)
        except BaseException:
            bank.close()
            raise
    return bank


def to_handoff_memory(item, bank_sha256):
    if not item.verify():
        _fail("Controller injection bytes changed before handoff")
    return HandoffMemory(item.memory_id, item.kind.value, item.active_node_id, item.exact_text,
        item.sha256, item.canonical_node_hash.removeprefix("sha256:"), bank_sha256)


def make_recall_callback(bank_path, bank_sha256, *, org_id, owner_user_id, checkout_root=None, parameters=None):
    """Native broker callback; trusted org/owner persist across fresh workers."""
    parameters = dict(parameters) if parameters is not None else None
    def recall(task_public, graph, query, checkpoint):
        task = CodingTask(task_public["task_id"], org_id, owner_user_id, task_public["repository"],
            task_public["commit"], task_public["instruction"], {}, ())
        bank = load_frozen_bank(bank_path, bank_sha256, task, checkout_root=checkout_root)
        try:
            node = graph.active_node
            if graph.objective != task.instruction.strip():
                _fail("Recall graph public task instruction differs")
            expected = None if node is None else {"node_id": node.node_id, "objective": node.objective,
                "operation": node.operation, "symbols": list(node.symbols), "apis": list(node.apis), "errors": list(node.errors)}
            if expected is None or (query is not None and (not isinstance(query, dict) or
                    any(key not in expected or expected[key] != value for key, value in query.items()))):
                _fail("Recall query must be the actual active subgoal trace")
            controller = bank.controller(task, parameters=parameters)
            binding = {"bank_sha256": bank_sha256, "task": _descriptor(task), "org_id": org_id,
                "owner_user_id": owner_user_id, "controller_sha256": controller.content_hash}
            if checkpoint:
                if checkpoint.get("binding") != binding:
                    _fail("Native memory checkpoint scope or configuration differs")
                controller.restore(checkpoint["controller"])
            decision = controller.recall(graph, task)
            return {"injections": tuple(to_handoff_memory(item, bank_sha256) for item in decision.injections),
                "checkpoint": {"binding": binding, "controller": dict(controller.checkpoint_state())},
                "decisions": [*decision.bank_trace, *({"record_type": "REJECTION", **row} for row in decision.rejections)]}
        finally:
            bank.close()
    return recall


def capture_evaluation_trace(quarantine_root, bank_path, bank_sha256, task_public, history, **kwargs):
    """Retain evaluation Gate A privately without admitting it to the retrieval bank."""
    bank = load_frozen_bank(bank_path, bank_sha256)
    try:
        root = _path(quarantine_root)
        protected = [_path(ref["path"]) for ref in (bank.reference, bank.manifest["authority"], bank.manifest["source_authority"])]
        if any(path == root or root in path.parents for path in protected):
            _fail("Evaluation quarantine must be separate from every frozen bank authority")
        _initialize(root, bank.manifest["scope"]["org_id"], [], bank.manifest["scope"]["evaluation_tasks"], "EVALUATION_QUARANTINE")
        return capture_training_trace(root, task_public, history, **kwargs)
    finally:
        bank.close()
