"""Public-training-only LiveCodeBench bridge to the existing TriMem layers.

The trusted runner supplies actual model actions and public sandbox receipts.
This module never runs a model, command, dataset loader, or private grader.
Reflections are model narratives with trace anchors, not verified factual claims.
L2 retains candidate revision scope; unrelated tasks do not inherit source facts.
The unchanged shared-skill Gate B still requires two real private owners.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.context_projection import ContextProjectionError
from enterprise_memory.trimem.skill_memory import (
    EpisodeEvidence, ProcedureTemplate, SkillMemoryStore, canonical_hash,
)
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
from enterprise_memory.trimem.subgoal_context import project_subgoal_context
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph

SCHEMA = "trimem/lcb-memory/1.0"
PUBLIC_TASK_SCHEMA = "trimem/lcb-public-task/1.0"
PUBLIC_RESULT_SCHEMA = "trimem/lcb-public-test-result/1.0"
REPOSITORY = "livecodebench/python"
MAX_CODE_BYTES = 256_000
MAX_TRACE_STEPS = 120
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class LCBMemoryError(ValueError):
    pass


def canonical_bytes(value):
    """Same JSON+LF representation as the public split exporter."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return _sha(canonical_bytes(value))


def _text(value, name, *, limit=100_000):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise LCBMemoryError("Invalid " + name)
    return value


def _path(path):
    path = Path(path).absolute()
    if path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
        raise LCBMemoryError("Linked memory paths are not allowed")
    return path


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value, *, fresh=False):
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    if fresh:
        with path.open("xb") as stream:
            stream.write(raw)
    else:
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)


def _ref(path, base):
    path = _path(path)
    return {"path": path.relative_to(_path(base)).as_posix(), "sha256": _sha(path.read_bytes())}


def _check_ref(reference, base):
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or
            not isinstance(reference["path"], str) or "\\" in reference["path"] or
            not _HEX.fullmatch(str(reference["sha256"]))):
        raise LCBMemoryError("Invalid relative memory reference")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise LCBMemoryError("Memory reference escaped its root")
    base = _path(base)
    path = _path(base / relative)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise LCBMemoryError("Memory reference escaped its root") from exc
    if not path.is_file() or _sha(path.read_bytes()) != reference["sha256"]:
        raise LCBMemoryError("Memory evidence is missing or changed")
    return path


def public_tests_sha256(row_or_sample):
    sample = row_or_sample.get("public_evaluation_sample", row_or_sample)
    return _hash(sample)


def public_task_instruction(row):
    return _text(row.get("question_title"), "question title") + "\n\n" + _text(row.get("prompt"), "public prompt")


def _reject_private_fields(value):
    forbidden = {"private_test_cases", "private_evaluation_sample", "hidden_tests", "hidden_test_cases",
        "gold", "gold_solution", "reference_solution", "official_grader", "private_grade", "private_verdict", "private_results"}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden:
                raise LCBMemoryError("Private grader fields are not accepted by public memory")
            _reject_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_private_fields(child)


def _descriptor(row):
    if not isinstance(row, dict) or row.get("schema") != PUBLIC_TASK_SCHEMA:
        raise LCBMemoryError("An exported public task is required")
    allowed = {"schema", "task_id", "question_id", "split", "family_id", "instruction_sha256",
        "public_tests_sha256", "platform", "contest_id", "contest_date", "difficulty",
        "question_title", "prompt", "starter_code", "public_test_cases", "public_evaluation_sample", "source_reference"}
    if set(row) - allowed:
        raise LCBMemoryError("Unsupported public task fields; private grader data is not accepted")
    _reject_private_fields(row)
    task_id = _text(row.get("task_id"), "task id", limit=500)
    if row.get("question_id") != task_id or row.get("split") not in {"train", "valid", "test"}:
        raise LCBMemoryError("Task identity or split differs")
    public_task_instruction(row)
    if not isinstance(row.get("starter_code"), str):
        raise LCBMemoryError("Public starter code is required")
    instruction_hash = _hash({key: row[key] for key in ("question_title", "prompt", "starter_code")})
    if row.get("instruction_sha256") != instruction_hash:
        raise LCBMemoryError("Public instruction fingerprint differs")
    sample = row.get("public_evaluation_sample")
    if not isinstance(sample, dict) or set(sample) != {"input_output"} or not isinstance(sample["input_output"], str):
        raise LCBMemoryError("An explicit public-only evaluation sample is required")
    try:
        decoded = json.loads(sample["input_output"])
    except (ValueError, TypeError) as exc:
        raise LCBMemoryError("Malformed public sample") from exc
    if (not isinstance(decoded, dict) or set(decoded) - {"inputs", "outputs", "fn_name"} or
            not isinstance(decoded.get("inputs"), list) or not isinstance(decoded.get("outputs"), list) or
            len(decoded["inputs"]) != len(decoded["outputs"])):
        raise LCBMemoryError("Malformed public sample")
    public_cases = row.get("public_test_cases")
    if (not isinstance(public_cases, list) or any(not isinstance(item, dict) for item in public_cases) or
            [item.get("input") for item in public_cases] != decoded["inputs"] or
            [item.get("output") for item in public_cases] != decoded["outputs"]):
        raise LCBMemoryError("Public evaluation sample differs from displayed examples")
    if row.get("public_tests_sha256") != public_tests_sha256(sample):
        raise LCBMemoryError("Public test fingerprint differs")
    return {"task_id": task_id, "split": row["split"], "family_id": _text(row.get("family_id"), "family id", limit=500),
        "instruction_sha256": instruction_hash, "public_tests_sha256": row["public_tests_sha256"],
        "starter_code_sha256": _sha(row["starter_code"].encode()), "public_test_count": len(public_cases)}


def _validate_scope(scope):
    if (not isinstance(scope, dict) or set(scope) != {"schema", "org_id", "owner_user_id", "repository", "tasks"} or
            scope["schema"] != SCHEMA or scope["repository"] != REPOSITORY):
        raise LCBMemoryError("Unsupported LCB memory scope")
    _text(scope["org_id"], "organisation")
    _text(scope["owner_user_id"], "owner")
    if not isinstance(scope["tasks"], list) or not scope["tasks"]:
        raise LCBMemoryError("Memory enrollment requires task descriptors")
    ids, families, instructions = set(), {}, {}
    for row in scope["tasks"]:
        if (not isinstance(row, dict) or set(row) != {"task_id", "split", "family_id", "instruction_sha256", "public_tests_sha256",
                         "starter_code_sha256", "public_test_count"} or row["split"] not in {"train", "valid", "test"}):
            raise LCBMemoryError("Invalid enrolled task descriptor")
        _text(row["task_id"], "enrolled task id", limit=500)
        _text(row["family_id"], "enrolled family id", limit=500)
        if (any(not isinstance(row[key], str) or not _HEX.fullmatch(row[key])
                for key in ("instruction_sha256", "public_tests_sha256", "starter_code_sha256")) or
                type(row["public_test_count"]) is not int or row["public_test_count"] < 0):
            raise LCBMemoryError("Invalid enrolled task fingerprints or public count")
        if row["task_id"] in ids:
            raise LCBMemoryError("Duplicate enrolled task")
        ids.add(row["task_id"])
        for table, key in ((families, row["family_id"]), (instructions, row["instruction_sha256"])):
            if key in table and table[key] != row["split"]:
                raise LCBMemoryError("Task family or instruction crosses split boundaries")
            table[key] = row["split"]
    if not any(row["split"] == "train" for row in scope["tasks"]):
        raise LCBMemoryError("Training enrollment is empty")


def initialize_training_memory(root, *, org_id, owner_user_id, tasks):
    root = _path(root)
    scope = {"schema": SCHEMA, "org_id": org_id, "owner_user_id": owner_user_id,
        "repository": REPOSITORY, "tasks": sorted((_descriptor(row) for row in tasks), key=lambda row: row["task_id"])}
    _validate_scope(scope)
    if root.exists() and any(root.iterdir()):
        if (root / "scope.json").is_file() and _read(root / "scope.json") == scope:
            return scope
        raise LCBMemoryError("Training memory requires a fresh or identically scoped directory")
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "scope.json", scope, fresh=True)
    _write(root / "catalog.json", {"captures": {}, "observations": {}, "skills": {}}, fresh=True)
    SkillMemoryStore(root / "authority.sqlite3").close()
    return scope


@contextmanager
def _writer(root):
    root = _path(root)
    with (root / "operation.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            scope, catalog = _read(root / "scope.json"), _read(root / "catalog.json")
            _validate_scope(scope)
            with SkillMemoryStore(root / "authority.sqlite3") as store:
                yield root, scope, catalog, store
            _write(root / "catalog.json", catalog)
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _bound_task(scope, row, *, split=None):
    descriptor = _descriptor(row)
    if descriptor not in scope["tasks"] or (split is not None and descriptor["split"] != split):
        raise LCBMemoryError("Task is outside the enrolled memory scope")
    return descriptor


def _validated_trace(row, graph, history):
    if not isinstance(graph, ShortTermWorkingGraph):
        raise LCBMemoryError("The actual working graph is required")
    if (graph.task_id != row["task_id"] or graph.repository != REPOSITORY or
            graph.objective != public_task_instruction(row).strip()):
        raise LCBMemoryError("Working graph task binding differs")
    if not isinstance(history, list) or not history or len(history) > MAX_TRACE_STEPS:
        raise LCBMemoryError("A bounded actual public trace is required")
    _reject_private_fields(history)
    # Existing L0 validation enforces graph membership and payload/hash bindings.
    try:
        project_subgoal_context(graph, history)
    except ContextProjectionError as exc:
        raise LCBMemoryError(str(exc)) from exc
    previous = 0
    for event in history:
        if event["step_no"] <= previous:
            raise LCBMemoryError("Public trace steps must be strictly ordered")
        previous = event["step_no"]
        if event["tool"] not in {"run_public_tests", "revise_subtask_dag", "complete_subtask"}:
            raise LCBMemoryError("Unsupported LCB public tool")
    return _observations(row, history)


def _observations(row, history):
    observations = []
    for event in history:
        if event["tool"] != "run_public_tests":
            continue
        result = event["result_payload"]
        if event["status"] == "error" and set(result) <= {"error", "message"}:
            if (not isinstance(result.get("error"), str) or
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", result["error"]) or
                    ("message" in result and not isinstance(result["message"], str))):
                raise LCBMemoryError("Invalid rejected public tool receipt")
            # A broker-rejected request has no candidate execution verdict. It
            # remains in L0/L1 provenance, and can never certify an L3 action.
            continue
        observations.append(_public_observation(row, event))
    return observations


def _public_observation(row, event):
    code = event["request_payload"]["arguments"].get("code")
    _text(code, "model candidate", limit=MAX_CODE_BYTES)
    result = event["result_payload"]
    allowed = {"schema", "task_id", "candidate_sha256", "public_tests_sha256", "command", "status",
        "test_count", "passed_count", "failed_count", "not_run_count", "exit_code", "timed_out",
        "failure_kind", "assertion_failures", "elapsed_seconds", "error_type", "passed"}
    if set(result) - allowed:
        raise LCBMemoryError("Public receipt contains unsupported fields")
    if (result.get("schema") != PUBLIC_RESULT_SCHEMA or result.get("task_id") != row["task_id"] or
            result.get("candidate_sha256") != _sha(code.encode()) or
            result.get("public_tests_sha256") != row["public_tests_sha256"] or
            result.get("command") != ["lcb_public_tests", row["task_id"], row["public_tests_sha256"]] or
            result.get("status") not in {"PASS", "FAIL", "INFRA_ERROR"} or type(result.get("timed_out")) is not bool):
        raise LCBMemoryError("Public receipt is not bound to the observed model candidate and examples")
    counts = [result.get(key, 0) for key in ("passed_count", "failed_count", "not_run_count")]
    count = result.get("test_count")
    if (type(count) is not int or count != len(row["public_test_cases"]) or
            any(type(value) is not int or value < 0 for value in counts) or sum(counts) != count):
        raise LCBMemoryError("Public receipt test counts differ")
    expected_passed = {"PASS": True, "FAIL": False, "INFRA_ERROR": None}[result["status"]]
    if "passed" in result and result["passed"] is not expected_passed:
        raise LCBMemoryError("Public receipt verdict fields disagree")
    failure = result.get("failure_kind")
    if "failure_kind" in result and ((result["status"] == "PASS" and failure is not None) or
            (result["status"] == "FAIL" and failure not in {"WRONG_ANSWER", "TIMEOUT", "RUNTIME_ERROR"}) or
            (result["status"] == "INFRA_ERROR" and failure != "INFRA_ERROR")):
        raise LCBMemoryError("Public receipt failure category differs")
    if "assertion_failures" in result and (type(result["assertion_failures"]) is not int or
            result["assertion_failures"] != (counts[1] if failure == "WRONG_ANSWER" else 0)):
        raise LCBMemoryError("Public receipt assertion count differs")
    if result["status"] == "PASS" and (event["status"] != "success" or count < 1 or counts != [count, 0, 0] or
            type(result.get("exit_code")) is not int or result["exit_code"] != 0 or result["timed_out"]):
        raise LCBMemoryError("Unverified public PASS")
    if result["status"] == "FAIL" and (event["status"] != "success" or counts[1] < 1 or
            type(result.get("exit_code")) is not int or result["exit_code"] != 1):
        raise LCBMemoryError("Unverified public FAIL")
    return {"step_no": event["step_no"], "active_node_id": event["active_node_id"], "code": code,
            "candidate_sha256": result["candidate_sha256"], "result": result, "event_sha256": _hash(event)}


def _lesson(value, history):
    if not isinstance(value, dict) or set(value) != {"summary", "applicability", "procedure", "trace_steps"}:
        raise LCBMemoryError("A model source_lesson with explicit public trace anchors is required")
    _text(value["summary"], "model reflection summary", limit=6000)
    _text(value["applicability"], "model reflection applicability", limit=3000)
    if (not isinstance(value["procedure"], list) or not 1 <= len(value["procedure"]) <= 12 or
            any(not isinstance(item, str) or not item.strip() or len(item.encode()) > 1500 for item in value["procedure"])):
        raise LCBMemoryError("Invalid model-reflected procedure")
    steps = value["trace_steps"]
    if (not isinstance(steps, list) or not steps or any(type(number) is not int for number in steps) or
            steps != sorted(set(steps)) or not set(steps) <= {event["step_no"] for event in history}):
        raise LCBMemoryError("Model reflection cites unavailable public trace steps")
    return value


def _ast_facts(code, task_id):
    revision = "sha256:" + _sha(code.encode())
    base = {"source_task_id": task_id, "source_revision": revision, "path": "solution.py",
            "applicability": "IDENTICAL_CANDIDATE_SOURCE_ONLY", "source_sha256": revision[7:]}
    nodes, edges = [], []
    def add(kind, name, node=None, parent=None):
        key = str(len(nodes))
        facts = {**base, "kind": kind, "name": name}
        if node is not None:
            facts.update(lineno=node.lineno, end_lineno=node.end_lineno)
        nodes.append((key, facts))
        if parent is not None:
            edges.append((parent, key, "CONTAINS"))
        return key
    file_key = add("PYTHON_FILE", "solution.py")
    try:
        tree = ast.parse(code, filename="solution.py")
    except SyntaxError:
        nodes[0][1]["parse_status"] = "SYNTAX_ERROR"
        return nodes, edges
    nodes[0][1]["parse_status"] = "PARSED"
    def visit(node, parent, prefix=""):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "PYTHON_CLASS" if isinstance(node, ast.ClassDef) else "PYTHON_FUNCTION"
            qualified = prefix + node.name
            key = add(kind, qualified, node, parent)
            for child in ast.iter_child_nodes(node):
                visit(child, key, qualified + ".")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module = alias.name if isinstance(node, ast.Import) else "." * node.level + (node.module or "") + ":" + alias.name
                key = add("PYTHON_IMPORT", module, node, parent)
                nodes[-1][1]["alias"] = alias.asname
                edges.append((parent, key, "IMPORTS"))
        else:
            for child in ast.iter_child_nodes(node):
                visit(child, parent, prefix)
    visit(tree, file_key)
    return nodes, edges


def _episode_evidence(scope, capture):
    selected = [event for event in capture["history"] if event["step_no"] in capture["source_lesson"]["trace_steps"]]
    observations = _observations(capture["task_public"], capture["history"])
    final_hash = _sha(capture["final_code"].encode())
    last = observations[-1] if observations else None
    succeeded = bool(last and last["candidate_sha256"] == final_hash and last["result"]["status"] == "PASS")
    # Candidate source stays in the private capture, not injected as L1 actions.
    actions = tuple(json.dumps({"tool": event["tool"], "step_no": event["step_no"],
        "request_sha256": _hash(event["request_payload"]), "result_sha256": _hash(event["result_payload"])}, sort_keys=True)
        for event in selected)
    lesson = capture["source_lesson"]
    summary = json.dumps({**lesson, "provenance": "MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS",
        "verification_scope": "PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER"}, ensure_ascii=False, sort_keys=True)
    return EpisodeEvidence(org_id=scope["org_id"], user_id=scope["owner_user_id"], repository=REPOSITORY,
        task_id=capture["task_public"]["task_id"], revision="sha256:" + final_hash,
        subgoal=lesson["applicability"], summary=summary, actions=actions, succeeded=succeeded,
        verification_command=json.dumps(last["result"]["command"]) if last else "",
        verification_evidence_hash="sha256:" + last["event_sha256"] if last else "",
        created_at=capture["created_at"], artifact_hashes=(("public_training_capture", "sha256:" + _hash(capture)),))


def _store_capture(store, scope, capture):
    episode = store.record_episode(_episode_evidence(scope, capture))
    facts, edges = _ast_facts(capture["final_code"], capture["task_public"]["task_id"])
    nodes = {}
    for key, payload in facts:
        nodes[key] = store.put_repository_knowledge(org_id=scope["org_id"], repository=REPOSITORY,
            revision=payload["source_revision"], title=payload["kind"] + " " + payload["name"],
            content=json.dumps(payload, sort_keys=True), language="python")
    relations = []
    for source, target, relation in edges:
        value = store.link_repository_knowledge(nodes[source].knowledge_id, nodes[target].knowledge_id,
            relation, org_id=scope["org_id"], repository=REPOSITORY)
        relations.append(asdict(value))
    return {"episode_id": episode.episode_id, "episode_content_hash": episode.content_hash,
        "knowledge_ids": [row.knowledge_id for row in nodes.values()], "edges": relations,
        "public_examples_passed": episode.evidence.succeeded,
        "l3_promoted": False, "verification_scope": "PUBLIC_EXAMPLES_ONLY_NOT_PRIVATE_GRADER"}


def capture_training_episode(root, task_public, history, *, graph, final_code, source_lesson,
                             contributor_id, model_id, created_at):
    """Trusted broker boundary; never pass model-claimed sandbox result objects."""
    _text(final_code, "final model candidate", limit=MAX_CODE_BYTES)
    _text(contributor_id, "actual contributor/session identity", limit=500)
    _text(model_id, "model identity", limit=500)
    _descriptor(task_public)
    _validated_trace(task_public, graph, history)
    _lesson(source_lesson, history)
    capture = {"schema": SCHEMA, "task_public": task_public, "history": history, "graph": graph.snapshot(),
        "final_code": final_code, "source_lesson": source_lesson, "contributor_id": contributor_id,
        "model_id": model_id, "created_at": created_at}
    with _writer(root) as (root, scope, catalog, store):
        _bound_task(scope, task_public, split="train")
        identity = _hash(task_public["task_id"])
        path = root / "captures" / (identity + ".json")
        if identity in catalog["captures"]:
            previous = _read(_check_ref(catalog["captures"][identity], root))
            if previous["capture"] != capture:
                raise LCBMemoryError("A recorded training outcome cannot be replaced or retried")
            return previous["receipt"]
        receipt = _store_capture(store, scope, capture)
        value = {"capture": capture, "receipt": receipt}
        if path.exists():
            if _read(path) != value:
                raise LCBMemoryError("Interrupted capture bytes differ")
        else:
            _write(path, value, fresh=True)
        catalog["captures"][identity] = _ref(path, root)
        return receipt


def _observed_action(observation):
    return "run_public_tests candidate_sha256=" + observation["candidate_sha256"] + " command=" + json.dumps(observation["result"]["command"], separators=(",", ":"))


def _skill_evidence(scope, capture, template, bindings, red_step, green_step):
    observations = _observations(capture["task_public"], capture["history"])
    red = next((row for row in observations if row["step_no"] == red_step), None)
    green = next((row for row in observations if row["step_no"] == green_step), None)
    if (red is None or green is None or red is not observations[0] or green is not observations[-1] or
            len(observations) != 2 or red_step >= green_step or red["active_node_id"] != green["active_node_id"] or
            red["result"]["status"] != "FAIL" or green["result"]["status"] != "PASS" or
            red["result"].get("failure_kind") != "WRONG_ANSWER" or red["result"]["timed_out"] or
            red["candidate_sha256"] == green["candidate_sha256"] or
            green["candidate_sha256"] != _sha(capture["final_code"].encode()) or
            red["result"]["command"] != green["result"]["command"]):
        raise LCBMemoryError("L3 requires first-model-candidate assertion RED and changed final candidate GREEN on identical public examples")
    rendered = template.render(bindings)
    actions = (_observed_action(red), _observed_action(green))
    command = json.dumps(green["result"]["command"], separators=(",", ":"))
    if rendered.steps != actions or rendered.verification_command != command:
        raise LCBMemoryError("L3 proposed procedure was not actually observed")
    original = _episode_evidence(scope, capture)
    proof = {"capture_sha256": _hash(capture), "template_sha256": template.content_hash,
        "bindings": bindings, "red_step": red_step, "green_step": green_step}
    evidence = EpisodeEvidence(org_id=scope["org_id"], user_id=scope["owner_user_id"], repository=REPOSITORY,
        task_id=original.task_id, revision=original.revision, subgoal="Verified public workflow " + template.content_hash,
        summary="Observed public RED/change/GREEN; no private correctness or semantic repair claim.",
        actions=actions, succeeded=True, verification_command=command,
        verification_evidence_hash="sha256:" + _hash(proof), created_at=original.created_at,
        procedure_hash=template.content_hash, parameter_bindings=tuple(sorted(bindings.items())),
        artifact_hashes=(("public_training_capture", "sha256:" + _hash(capture)),))
    return evidence, proof


def verify_skill_observation(root, task_id, template, *, bindings, red_step, green_step):
    template = template if isinstance(template, ProcedureTemplate) else ProcedureTemplate(**template)
    with _writer(root) as (root, scope, catalog, store):
        capture_ref = catalog["captures"].get(_hash(task_id))
        if capture_ref is None:
            raise LCBMemoryError("L3 source is not a captured training task")
        capture = _read(_check_ref(capture_ref, root))["capture"]
        evidence, proof = _skill_evidence(scope, capture, template, bindings, red_step, green_step)
        episode = store.record_episode(evidence)
        value = {"template": asdict(template), "proof": proof, "episode_id": episode.episode_id,
            "episode_content_hash": episode.content_hash, "capture_reference": capture_ref,
            "status": "PUBLIC_WORKFLOW_OBSERVED_NOT_PROMOTED"}
        identity = _hash(value)
        path = root / "observations" / (identity + ".json")
        if identity not in catalog["observations"]:
            _write(path, value, fresh=True)
            catalog["observations"][identity] = _ref(path, root)
        return {"observation_id": identity, "episode_id": episode.episode_id, "status": value["status"]}


def promote_verified_skill(root, template, observation_ids):
    """Unchanged Gate B; task/session IDs never masquerade as different users."""
    template = template if isinstance(template, ProcedureTemplate) else ProcedureTemplate(**template)
    with _writer(root) as (root, scope, catalog, store):
        values = [_read(_check_ref(catalog["observations"][identity], root)) for identity in observation_ids]
        if any(ProcedureTemplate(**value["template"]).content_hash != template.content_hash for value in values):
            raise LCBMemoryError("Observation template differs")
        skill = store.promote_skill(template, [value["episode_id"] for value in values], org_id=scope["org_id"])
        catalog["skills"][skill.skill_id] = {"template": asdict(template), "observation_ids": sorted(set(observation_ids)),
            "content_hash": skill.content_hash}
        return skill.public_view()


def observe_available_workflow(root, task_id):
    """Retain an exact public workflow, not a generalized algorithmic skill.

This mechanical trace adapter does not propose a semantic repair or promote L3.
The two actual calls must pass the same strict verifier as explicit proposals.
"""
    root = _path(root)
    catalog = _read(root / "catalog.json")
    reference = catalog["captures"].get(_hash(task_id))
    if reference is None:
        raise LCBMemoryError("Workflow source is not a captured training task")
    capture = _read(_check_ref(reference, root))["capture"]
    observations = _observations(capture["task_public"], capture["history"])
    absent = {"status": "NO_ELIGIBLE_PUBLIC_WORKFLOW", "l3_promoted": False,
        "scope": "MECHANICALLY_OBSERVED_PUBLIC_WORKFLOW_NOT_GENERALIZED_ALGORITHM"}
    if len(observations) != 2:
        return absent
    red, green = observations
    if (red["result"]["status"] != "FAIL" or red["result"].get("failure_kind") != "WRONG_ANSWER" or
            red["result"]["timed_out"] or green["result"]["status"] != "PASS" or
            red["active_node_id"] != green["active_node_id"] or red["candidate_sha256"] == green["candidate_sha256"] or
            green["candidate_sha256"] != _sha(capture["final_code"].encode())):
        return absent
    template = ProcedureTemplate(subgoal_signature="Check a changed candidate on the same public examples",
        parameters=("initial_candidate_sha256", "revised_candidate_sha256", "public_command"),
        preconditions=("These are public example observations; they do not certify private tests or a semantic repair.",),
        steps=("run_public_tests candidate_sha256={initial_candidate_sha256} command={public_command}",
               "run_public_tests candidate_sha256={revised_candidate_sha256} command={public_command}"),
        verification_command="{public_command}", language="python")
    bindings = {"initial_candidate_sha256": red["candidate_sha256"], "revised_candidate_sha256": green["candidate_sha256"],
        "public_command": json.dumps(green["result"]["command"], separators=(",", ":"))}
    result = verify_skill_observation(root, task_id, template, bindings=bindings,
        red_step=red["step_no"], green_step=green["step_no"])
    return {**result, "l3_promoted": False, "scope": absent["scope"]}


def _audit(store, root, scope, catalog):
    if set(catalog) != {"captures", "observations", "skills"}:
        raise LCBMemoryError("Unsupported memory catalog")
    # Rebuild deterministic records from exact public captures, then compare all
    # canonical rows/relations. This rejects unrelated SWE records and SQL edits.
    with SkillMemoryStore(":memory:") as expected:
        for identity, reference in catalog["captures"].items():
            value = _read(_check_ref(reference, root))
            capture = value["capture"]
            _bound_task(scope, capture["task_public"], split="train")
            if identity != _hash(capture["task_public"]["task_id"]):
                raise LCBMemoryError("Capture task identity differs")
            graph = ShortTermWorkingGraph.from_snapshot(capture["graph"])
            _validated_trace(capture["task_public"], graph, capture["history"])
            _lesson(capture["source_lesson"], capture["history"])
            if _store_capture(expected, scope, capture) != value["receipt"]:
                raise LCBMemoryError("Training capture receipt differs")
        for reference in catalog["observations"].values():
            value = _read(_check_ref(reference, root))
            if value["capture_reference"] not in catalog["captures"].values():
                raise LCBMemoryError("L3 observation escaped training captures")
            capture = _read(_check_ref(value["capture_reference"], root))["capture"]
            evidence, proof = _skill_evidence(scope, capture, ProcedureTemplate(**value["template"]),
                value["proof"]["bindings"], value["proof"]["red_step"], value["proof"]["green_step"])
            episode = expected.record_episode(evidence)
            if proof != value["proof"] or episode.episode_id != value["episode_id"] or episode.content_hash != value["episode_content_hash"]:
                raise LCBMemoryError("L3 observation provenance differs")
        # Single-owner scope cannot meet the existing two-user Gate B. Fail
        # closed if a caller inserts a skill by editing the authority/catalog.
        if catalog["skills"]:
            raise LCBMemoryError("Single-owner LCB authority cannot certify a shared L3 skill")
        for table in ("memory_records", "knowledge_relations", "skill_support", "repository_heads"):
            actual_rows = sorted(tuple(row) for row in store._db.execute("SELECT * FROM " + table))
            expected_rows = sorted(tuple(row) for row in expected._db.execute("SELECT * FROM " + table))
            if actual_rows != expected_rows:
                raise LCBMemoryError("Memory authority does not match its public training provenance")
    counts = dict(store._db.execute("SELECT kind,COUNT(*) FROM memory_records GROUP BY kind").fetchall())
    return {"L1_episodes": counts.get("episode", 0), "L2_nodes": counts.get("knowledge", 0),
        "L2_edges": store._db.execute("SELECT COUNT(*) FROM knowledge_relations").fetchone()[0],
        "L3_skills": counts.get("skill", 0), "training_tasks": len(catalog["captures"]),
        "verified_public_workflows": len(catalog["observations"])}


def freeze_training_bank(root, output_path):
    """Publish a portable immutable snapshot; later training uses another bank."""
    output = _path(output_path)
    sidecar = output.with_name(output.stem + ".data")
    if output.exists() or sidecar.exists():
        raise LCBMemoryError("Frozen bank output must be fresh")
    with _writer(root) as (root, scope, catalog, store):
        counts = _audit(store, root, scope, catalog)
        if counts["training_tasks"] < 1:
            raise LCBMemoryError("Cannot freeze an untrained memory bank")
        sidecar.mkdir(parents=True)
        with sqlite3.connect(sidecar / "authority.sqlite3") as destination:
            store._db.backup(destination)
        for kind in ("captures", "observations"):
            for reference in catalog[kind].values():
                original = _check_ref(reference, root)
                target = _path(sidecar / reference["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(original.read_bytes())
        manifest = {"schema": SCHEMA, "frozen": True, "scope": scope, "catalog": catalog,
            "data_directory": sidecar.name, "authority": _ref(sidecar / "authority.sqlite3", sidecar),
            "layer_counts": counts, "retrieval": "UNCHANGED_SKILL_REPOSITORY_EPISODE_CONTROLLER",
            "source_revisions_retagged": False, "evaluation_writes": False,
            "l2_limit": "Candidate AST facts require identical source; independent LCB tasks rarely share applicable L2.",
            "l3_limit": "The existing shared Gate B requires two real users; a single-owner run has no promoted shared skills."}
        _write(output, manifest, fresh=True)
        return {"path": str(output), "sha256": _sha(output.read_bytes()), "layer_counts": counts}


class _ReadOnlyStore(SkillMemoryStore):
    def __init__(self, path):
        self.path = str(path)
        self._db = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA query_only=ON")


class FrozenLCBMemory:
    def __init__(self, path, expected_sha256):
        self.path = _path(path)
        self.sha256 = expected_sha256
        if not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256):
            raise LCBMemoryError("A frozen bank hash is required")
        if _sha(self.path.read_bytes()) != expected_sha256:
            raise LCBMemoryError("Frozen bank manifest changed")
        self.manifest = _read(self.path)
        manifest = self.manifest
        if (manifest.get("schema") != SCHEMA or manifest.get("frozen") is not True or
                manifest.get("retrieval") != "UNCHANGED_SKILL_REPOSITORY_EPISODE_CONTROLLER" or
                manifest.get("source_revisions_retagged") is not False or manifest.get("evaluation_writes") is not False):
            raise LCBMemoryError("Unsupported frozen LCB bank")
        directory = manifest["data_directory"]
        if not isinstance(directory, str) or Path(directory).name != directory or directory in {".", ".."} or "\\" in directory:
            raise LCBMemoryError("Frozen data directory escaped bank directory")
        self.root = _path(self.path.parent / directory)
        _validate_scope(manifest["scope"])
        self._check()
        self.store = _ReadOnlyStore(_check_ref(manifest["authority"], self.root))
        try:
            if _audit(self.store, self.root, manifest["scope"], manifest["catalog"]) != manifest["layer_counts"]:
                raise LCBMemoryError("Frozen layer counts differ")
        except BaseException:
            self.store.close()
            raise

    def _check(self):
        if _sha(self.path.read_bytes()) != self.sha256:
            raise LCBMemoryError("Frozen bank manifest changed")
        authority = _check_ref(self.manifest["authority"], self.root)
        if any(Path(str(authority) + suffix).exists() and Path(str(authority) + suffix).stat().st_size
               for suffix in ("-wal", "-journal")):
            raise LCBMemoryError("Frozen authority has an active write journal")
        for kind in ("captures", "observations"):
            for reference in self.manifest["catalog"][kind].values():
                _check_ref(reference, self.root)

    def snapshot(self, *, org_id, user_id, repository, revision="", language=""):
        self._check()
        scope = self.manifest["scope"]
        if (org_id, user_id, repository) != (scope["org_id"], scope["owner_user_id"], REPOSITORY):
            raise LCBMemoryError("Frozen memory tenant or owner differs")
        return self.store.snapshot(org_id=org_id, user_id=user_id, repository=repository, revision=revision, language=language)

    def recall(self, task_public, graph, *, checkpoint=None):
        scope = self.manifest["scope"]
        descriptor = _bound_task(scope, task_public)
        if descriptor["split"] == "train":
            raise LCBMemoryError("Frozen evaluation retrieval requires valid or test task")
        if (graph.task_id != descriptor["task_id"] or graph.repository != REPOSITORY or
                graph.objective != public_task_instruction(task_public).strip()):
            raise LCBMemoryError("Recall working graph task binding differs")
        task = CodingTask(descriptor["task_id"], scope["org_id"], scope["owner_user_id"], REPOSITORY,
            "sha256:" + descriptor["starter_code_sha256"], public_task_instruction(task_public),
            {"solution.py": task_public["starter_code"]}, ("solution.py",))
        snapshot = self.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
            revision=task.commit, language="python")
        # Search actual AST identifiers without letting provenance/hash tokens
        # dilute the existing lexical PPR seeds. Exact views retain all scope.
        retrieval_texts = {row.knowledge_id: row.title + " " + json.loads(row.content)["name"]
            for row in snapshot.repository_knowledge}
        controller = SkillFirstMemoryController(self, task_id=task.task_id,
            repository_retrieval_texts=retrieval_texts)
        binding = {"bank_sha256": self.sha256, "task": descriptor, "controller_sha256": controller.content_hash}
        if checkpoint is not None:
            if not isinstance(checkpoint, dict) or checkpoint.get("binding") != binding:
                raise LCBMemoryError("Memory checkpoint task or frozen bank differs")
            controller.restore(checkpoint["controller"])
        decision = controller.recall(graph, task)
        injections = []
        for item in decision.injections:
            if not item.verify():
                raise LCBMemoryError("Memory injection bytes changed")
            row = asdict(item)
            row.pop("exact_utf8")
            row["kind"] = item.kind.value
            injections.append(row)
        return {"injections": injections, "checkpoint": {"binding": binding, "controller": dict(controller.checkpoint_state())},
            "decisions": [*decision.bank_trace, *({"record_type": "REJECTION", **row} for row in decision.rejections)]}

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_frozen_bank(path, expected_sha256):
    return FrozenLCBMemory(path, expected_sha256)


def project_context(graph, history, **kwargs):
    """Use this identical L0 projection for both OFF and ON."""
    return project_subgoal_context(graph, history, **kwargs)
