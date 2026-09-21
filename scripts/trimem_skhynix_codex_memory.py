"""Local memory retrieval for fresh native Codex benchmark sessions.

No model client is constructed. M2 uses its actual pinned local embedding
retriever; SKHYNIX uses its actual skill-first controller. Native Codex owns its
chat history: this bridge does not implement or claim L0 context replacement.
All mutable state belongs to one cell. Schema2 can project an actual promoted
public workflow under an exact runtime certificate; private episodes stay local.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from enterprise_memory.trimem.agent_runtime import CodingTask, NoMemoryController
from enterprise_memory.trimem.arms import ActiveNodeTriMemController
from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
from enterprise_memory.trimem.retrieval import RetrievalConfig, TriMemoryRetriever
from enterprise_memory.trimem.skill_memory import SkillMemoryStore
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec
from trimem_skhynix_codex_learning import (
    load_frozen_bank, LearnedGraphStore, build_learned_seeded_store,
)
from trimem_skhynix_source_bank import (
    build_legacy_source_store, build_seeded_store, load_validated_source_bank,
)

ARMS = ("NO_MEMORY", "EXISTING_M2", "SKHYNIX")
SCHEMA = "skhynix/native-codex-memory/1.0"
MAX_INJECTIONS = 3
MAX_BYTES = 12_000


class MemoryBridgeError(ValueError):
    """The persisted cell identity, source, or query contract was violated."""


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def _locked(cell_root: Path):
    root = Path(cell_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    private = root / "memory-private"
    if private.is_symlink():
        raise MemoryBridgeError("private memory directory cannot be a symbolic link")
    private.mkdir(exist_ok=True)
    if private.resolve().parent != root:
        raise MemoryBridgeError("private memory directory escapes the cell")
    lock = private / "operation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MemoryBridgeError("another memory operation is active or needs recovery") from exc
    try:
        os.close(fd)
        yield private
    finally:
        lock.unlink()


@contextmanager
def _offline_embeddings():
    """Force cached weights; never silently download models during a recall."""
    names = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ[name] = "1"
    # These libraries can have been imported before this bridge in a broker.
    overrides = []
    for module_name, attribute in (("huggingface_hub.constants", "HF_HUB_OFFLINE"),
                                   ("transformers.utils.hub", "_is_offline_mode")):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, attribute):
            overrides.append((module, attribute, getattr(module, attribute)))
            setattr(module, attribute, True)
    try:
        yield
    finally:
        for module, attribute, value in overrides:
            setattr(module, attribute, value)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _m2_embedder():
    return PinnedSentenceTransformerPPR()


def _identity(cell_root, task, arm, repository_root, frozen_bank=None):
    if arm not in ARMS:
        raise MemoryBridgeError("unknown memory arm")
    value = {
        "schema": SCHEMA, "arm": arm,
        "cell_root": str(Path(cell_root).resolve()),
        "implementation_root": str(Path(repository_root).resolve()),
        "task": {name: getattr(task, name) for name in
                 ("task_id", "org_id", "user_id", "repository", "commit")},
        "public_task_sha256": _hash(task.public_payload()),
        "bridge_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "max_task_injections": MAX_INJECTIONS,
        "context_budget_bytes": MAX_BYTES,
        "native_context_replacement": False,
        "source_scope": "VALIDATED_HISTORICAL_PR_KNOWLEDGE_ONLY",
        "seed_episode_count": 0, "seed_skill_count": 0,
        "experience_writes": False, "model_api_calls": 0,
    }
    if frozen_bank is not None:
        value.update(source_scope="FROZEN_NATIVE_TRAINING_OBSERVATIONS",
                     frozen_bank_path=str(frozen_bank.path), frozen_bank_sha256=frozen_bank.sha256,
                     training_gate_a_episode_count=frozen_bank.manifest["gate_a"]["episode_count"])
        if frozen_bank.manifest["schema"] == "skhynix/native-learned-bank/2.0":
            value.update(source_scope="FROZEN_NATIVE_TRAINING_AND_PROMOTED_PUBLIC_WORKFLOW",
                         seed_skill_count=1 if arm == "SKHYNIX" else 0,
                         verified_skill_payload_count=0 if arm == "NO_MEMORY" else 1)
        elif frozen_bank.manifest["schema"] == "skhynix/native-diagnostic-bank/1.0":
            value.update(source_scope="PUBLIC_DIAGNOSTIC_INTERPRETATION_OF_COMPLETED_FAILURES",
                         diagnostic_scenario=frozen_bank.manifest["scenario"],
                         seed_skill_count=0, verified_skill_payload_count=0)
    return value


def _repository_retrieval_texts(bank, report):
    """Project only the explicitly enabled, source-validated diagnostic prose.

    Knowledge ids come from the seeded store report; execution views retain the
    complete original payload, including all failed-source provenance labels.
    """
    manifest = getattr(bank, "manifest", {})
    if "retrieval_text_policy" not in manifest:
        return None
    import trimem_skhynix_codex_diagnostic_bank as diagnostic
    if (not isinstance(bank, diagnostic.FrozenDiagnosticBank) or manifest.get("schema") != diagnostic.SCHEMA or
            manifest["retrieval_text_policy"] not in (
                diagnostic.DIAGNOSTIC_LESSON_CONTENT, diagnostic.EXACT_TASK_DIAGNOSTIC_ROUTE)):
        raise MemoryBridgeError("retrieval text policy requires a validated diagnostic bank")
    if manifest["retrieval_text_policy"] == diagnostic.EXACT_TASK_DIAGNOSTIC_ROUTE:
        # The separate route helper validates the exact task and seeded identity.
        return None
    records = {row["memory_id"]: row for row in bank.records}
    entries = report.get("entries", [])
    if (len(entries) != len(records) or {row.get("memory_id") for row in entries} != set(records) or
            len({row.get("knowledge_id") for row in entries}) != len(entries)):
        raise MemoryBridgeError("diagnostic retrieval ids differ from the seeded knowledge projection")
    texts = {}
    for entry in entries:
        record = records[entry["memory_id"]]
        payload = diagnostic._json(record["content"])
        if (not isinstance(payload, dict) or payload.get("kind") != "public_failure_diagnostic_interpretation" or
                payload.get("source_evidence_label") != diagnostic.LABEL or
                entry.get("shared_source_content_sha256") != hashlib.sha256(record["content"].encode()).hexdigest()):
            raise MemoryBridgeError("diagnostic retrieval content or source binding differs")
        lesson = diagnostic._text(payload.get("analyst_lesson"), diagnostic.MAX_LESSON_BYTES, "analyst lesson")
        texts[entry["knowledge_id"]] = record["title"] + " " + lesson
    return texts


def _repository_exact_task_routes(bank, report, task):
    """Bind one retained failure to its exact task without lexical eligibility.

    Revalidate the frozen source contract and real seed projection before deriving
    the route. A constructed bank object, changed target or fabricated knowledge
    id cannot activate an arbitrary repository record through this bridge.
    """
    manifest = getattr(bank, "manifest", {})
    import trimem_skhynix_codex_diagnostic_bank as diagnostic
    if "retrieval_text_policy" not in manifest:
        return None
    if (not isinstance(bank, diagnostic.FrozenDiagnosticBank) or manifest.get("schema") != diagnostic.SCHEMA or
            manifest["retrieval_text_policy"] not in (
                diagnostic.DIAGNOSTIC_LESSON_CONTENT, diagnostic.EXACT_TASK_DIAGNOSTIC_ROUTE)):
        raise MemoryBridgeError("exact-task routing requires a validated diagnostic bank policy")
    if manifest["retrieval_text_policy"] == diagnostic.DIAGNOSTIC_LESSON_CONTENT:
        return None
    if manifest.get("scenario") != "KNOWN_FAILURE_RECOVERY":
        raise MemoryBridgeError("exact-task routing requires KNOWN_FAILURE_RECOVERY")
    validated = diagnostic.load_diagnostic_bank(bank.path, bank.sha256, task)
    if validated.manifest != manifest or validated.target != bank.target:
        raise MemoryBridgeError("exact-task routing bank differs from its validated frozen binding")
    records = validated.records
    if (len(records) != 1 or records[0]["source"]["task_id"] != task.task_id or
            records[0]["source"]["repository"] != task.repository or
            records[0]["source"]["revision"] != task.commit):
        raise MemoryBridgeError("exact-task routing requires one matching retained failure record")
    expected_store, expected_report = build_learned_seeded_store(":memory:", task, validated)
    expected_store.close()
    if any(report.get(key) != expected_report[key] for key in ("entries", "seed_snapshot_sha256", "language")):
        raise MemoryBridgeError("exact-task routing ids or content differ from the seeded knowledge projection")
    return {expected_report["entries"][0]["knowledge_id"]: task.task_id}


def _controller(private, task, arm, repository_root, *, create, frozen_bank=None):
    if arm == "NO_MEMORY":
        return NoMemoryController(), None, {"records": 0, "verified_skill_count": 0,
                                           "imported_episode_count": 0}
    bank = frozen_bank or load_validated_source_bank(repository_root)
    source = LearnedGraphStore(task, bank) if frozen_bank is not None else build_legacy_source_store(task, bank=bank)
    projection = {
        "validation": dict(bank.report), "source_hash": source.content_hash,
        "execution_views": {key: raw.decode("utf-8")
                            for key, raw in sorted(source.execution_views.items())},
    }
    source_path = private / "historical-source-projection.json"
    if create:
        if source_path.exists():
            raise MemoryBridgeError("refusing to overwrite a prior source projection")
        _write(source_path, projection)
    elif not source_path.is_file() or _read(source_path) != projection:
        raise MemoryBridgeError("private historical source projection differs")
    if arm == "SKHYNIX":
        seed = build_learned_seeded_store if frozen_bank is not None else build_seeded_store
        path = private / "source-memory.sqlite3"
        if create:
            store, report = seed(path, task, bank=bank)
        else:
            if not path.is_file() or path.is_symlink():
                raise MemoryBridgeError("private skill memory store is missing or linked")
            expected, report = seed(":memory:", task, bank=bank)
            expected.close()
            store = SkillMemoryStore(path)
            if frozen_bank is not None and frozen_bank.promoted_skill is not None:
                from trimem_skhynix_codex_skill_bank import FrozenSkillProjectionStore
                try:
                    store = FrozenSkillProjectionStore(store, task, frozen_bank)
                except BaseException:
                    store.close()
                    raise
            snapshot = store.snapshot(org_id=task.org_id, user_id=task.user_id,
                                      repository=task.repository, revision=task.commit,
                                      language=report["language"])
            if snapshot.content_hash != report["seed_snapshot_sha256"]:
                store.close()
                raise MemoryBridgeError("private source bank differs from immutable seed")
        report = {**report, "source_projection_sha256": _hash(projection)}
        try:
            controller = SkillFirstMemoryController(
                store, task_id=task.task_id, language=report["language"],
                context_budget_bytes=MAX_BYTES, max_injections_per_task=MAX_INJECTIONS,
                repository_retrieval_texts=_repository_retrieval_texts(bank, report),
                repository_exact_task_routes=_repository_exact_task_routes(bank, report, task),
            )
        except BaseException:
            store.close()
            raise
        return controller, store, report
    policy = _read(Path(repository_root) / "configs/trimem_v1/m2_candidates/recall.json")["retrieval"]
    if (policy["max_task_injections"] != MAX_INJECTIONS or
            policy["context_budget_bytes"] != MAX_BYTES):
        raise MemoryBridgeError("historical M2 injection budget differs")
    config = RetrievalConfig(
        min_confidence=policy["min_confidence"], min_margin=policy["min_margin"],
        episode_complete_threshold=policy["episode_complete_threshold"],
        max_episodic_per_node=policy["max_episodic_per_active_node"],
        max_semantic_per_node=policy["max_semantic_per_active_node"],
        max_task_injections=MAX_INJECTIONS, context_budget_bytes=MAX_BYTES,
        embedding_dimensions=policy["embedding_dimensions"],
        embedding_weight=policy["embedding_weight"], lexical_weight=policy["lexical_weight"],
        ppr_damping=policy["ppr_damping"], ppr_iterations=policy["ppr_iterations"],
    )
    retriever = TriMemoryRetriever(source, config, embedder=_m2_embedder(),
                                  diagnostic_telemetry=True, require_safe_pool_metadata=True)
    return ActiveNodeTriMemController(retriever, task_id=task.task_id), None, {
        **(bank.report if frozen_bank is not None else {}),
        "source_hash": source.content_hash, "source_projection_sha256": _hash(projection),
        "records": len(source.execution_views), "verified_skill_count": 0,
        "imported_episode_count": 0, "embedding": retriever.manifest()["embedder"],
    }


def _budget(checkpoint):
    ledger = checkpoint.get("ledger", [])
    count, used = len(ledger), sum(row["byte_count"] for row in ledger)
    if (count > MAX_INJECTIONS or used > MAX_BYTES or used < 0 or
            any(type(row["byte_count"]) is not int or row["byte_count"] <= 0 for row in ledger)):
        raise MemoryBridgeError("persisted injection budget is invalid")
    return {"injections_used": count, "injections_remaining": MAX_INJECTIONS - count,
            "bytes_used": used, "bytes_remaining": MAX_BYTES - used,
            "max_task_injections": MAX_INJECTIONS, "context_budget_bytes": MAX_BYTES}


def _load_state(private, binding):
    path = private / "checkpoint.json"
    if not path.is_file() or path.is_symlink():
        raise MemoryBridgeError("memory must be initialized before recall")
    envelope = _read(path)
    state = envelope.get("state")
    if not isinstance(state, dict) or envelope.get("sha256") != _hash(state):
        raise MemoryBridgeError("memory checkpoint integrity differs")
    if state.get("binding") != binding:
        raise MemoryBridgeError("memory cell task, identity, source, or configuration differs")
    _budget(state["controller"])
    return state


def _save_state(private, state):
    _write(private / "checkpoint.json", {"state": state, "sha256": _hash(state)})


def _restore_controller(controller, state, private, arm):
    controller.restore(state["controller"])
    ledger = state["controller"].get("ledger", [])
    if len({row["memory_id"] for row in ledger}) != len(ledger):
        raise MemoryBridgeError("memory checkpoint repeats an injected source")
    if arm == "EXISTING_M2":
        views = _read(private / "historical-source-projection.json")["execution_views"]
        if any(views.get(row["memory_id"]) != row["exact_text"] for row in ledger):
            raise MemoryBridgeError("retained M2 injection differs from validated source")
    for node_id, record in state["queries"].items():
        if record["node_id"] != node_id or record["injections"] != [
                _injection(item) for item in controller.context_for(node_id)]:
            raise MemoryBridgeError("query receipt differs from retained controller context")
    if any(row["active_node_id"] not in state["queries"] for row in ledger):
        raise MemoryBridgeError("retained injection has no bound semantic query")


def _public_manifest(binding, checkpoint):
    return {"schema": SCHEMA, "arm": binding["arm"], "task_id": binding["task"]["task_id"],
            "binding_sha256": _hash(binding), "controller_sha256": binding["controller_sha256"],
            "bank": binding["bank"], "budget": _budget(checkpoint),
            "model_api_calls": 0, "native_context_replacement": False,
            "seed_episode_count": 0, "seed_skill_count": binding.get("seed_skill_count", 0), "experience_writes": False,
            "training_gate_a_episode_count": binding.get("training_gate_a_episode_count", 0),
            **({"diagnostic_scenario": binding["diagnostic_scenario"],
                "source_evidence_label": binding["source_scope"]}
               if "diagnostic_scenario" in binding else {}),
            **({"verified_skill_payload_count": binding["verified_skill_payload_count"]}
               if "verified_skill_payload_count" in binding else {})}


def _frozen_bank(path, expected_sha256, task):
    if path is None:
        if expected_sha256 is not None:
            raise MemoryBridgeError("frozen bank hash was provided without a path")
        return None
    return load_frozen_bank(path, expected_sha256, task)


def initialize_memory(cell_root: Path, task: CodingTask, arm: str,
                      repository_root: Path = ROOT, *, frozen_bank_path: Path | None = None,
                      frozen_bank_sha256: str | None = None) -> dict:
    """Seed/validate one private cell and persist the real controller checkpoint."""
    frozen_bank = _frozen_bank(frozen_bank_path, frozen_bank_sha256, task)
    identity = _identity(cell_root, task, arm, repository_root, frozen_bank)
    with _locked(cell_root) as private:
        create = not (private / "checkpoint.json").exists()
        if create and any(path.name != "operation.lock" for path in private.iterdir()):
            raise MemoryBridgeError("incomplete existing memory directory needs recovery")
        controller, store, report = _controller(private, task, arm, repository_root, create=create, frozen_bank=frozen_bank)
        try:
            binding = {**identity, "controller_sha256": controller.content_hash, "bank": report}
            if create:
                state = {"binding": binding, "controller": dict(controller.checkpoint_state()),
                         "queries": {}, "calls": 0}
                _save_state(private, state)
            else:
                state = _load_state(private, binding)
                _restore_controller(controller, state, private, arm)
            return _public_manifest(binding, state["controller"])
        finally:
            if store is not None:
                store.close()


def _query_graph(task, query):
    allowed = {"node_id", "objective", "operation", "symbols", "apis", "errors"}
    if not isinstance(query, dict) or set(query) - allowed:
        raise MemoryBridgeError("recall query contains unknown fields")
    if len(_bytes(query)) > 8_192:
        raise MemoryBridgeError("recall query exceeds 8192 UTF-8 bytes")
    if not isinstance(query.get("node_id"), str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", query["node_id"]):
        raise MemoryBridgeError("recall requires a stable node_id of 1 to 64 characters")
    normalized = {"node_id": query["node_id"]}
    for key in ("objective", "operation"):
        value = query.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MemoryBridgeError("recall requires non-empty objective and operation")
        normalized[key] = value.strip()
    for key in ("symbols", "apis", "errors"):
        values = query.get(key, [])
        if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
            raise MemoryBridgeError("symbols, apis and errors must be lists of strings")
        normalized[key] = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    graph = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
    graph.add_subtask(SubtaskSpec(**normalized))
    graph.activate(normalized["node_id"])
    return normalized, graph


def _injection(item):
    if not item.verify():
        raise MemoryBridgeError("retrieved injection failed byte/hash verification")
    row = asdict(item)
    row.pop("exact_utf8")
    row["kind"] = item.kind.value
    return row


def recall_memory(cell_root: Path, task: CodingTask, arm: str, query: dict,
                  repository_root: Path = ROOT, *, frozen_bank_path: Path | None = None,
                  frozen_bank_sha256: str | None = None) -> dict:
    """Recall a semantic subgoal once; identical retries replay retained context.

    The same node ID cannot represent a changed query. No-memory goes through
    the same query validation and persistence, but never opens a source bank.
    """
    frozen_bank = _frozen_bank(frozen_bank_path, frozen_bank_sha256, task)
    identity = _identity(cell_root, task, arm, repository_root, frozen_bank)
    normalized, graph = _query_graph(task, query)
    with _locked(cell_root) as private:
        if not (private / "checkpoint.json").is_file():
            raise MemoryBridgeError("memory must be initialized before recall")
        controller, store, report = _controller(private, task, arm, repository_root, create=False, frozen_bank=frozen_bank)
        try:
            binding = {**identity, "controller_sha256": controller.content_hash, "bank": report}
            state = _load_state(private, binding)
            _restore_controller(controller, state, private, arm)
            node_id = normalized["node_id"]
            query_hash = _hash(normalized)
            prior = state["queries"].get(node_id)
            if prior is not None and prior["query_sha256"] != query_hash:
                raise MemoryBridgeError("node_id was already bound to a different semantic query")
            if prior is not None:
                # Controller restore above still validates the retained source.
                context = [_injection(item) for item in controller.context_for(node_id)]
                if context != prior["injections"]:
                    raise MemoryBridgeError("retained recall context differs from its checkpoint")
                result = {**prior, "repeat": True, "new_injection_count": 0,
                          "budget": _budget(state["controller"])}
            else:
                with _offline_embeddings():
                    decision = controller.recall(graph, task)
                checkpoint = dict(controller.checkpoint_state())
                result = {"schema": SCHEMA, "arm": arm, "task_id": task.task_id,
                          "node_id": node_id, "query_sha256": query_hash,
                          "injections": [_injection(item) for item in decision.injections],
                          "decisions": list(decision.bank_trace), "rejections": list(decision.rejections),
                          "decision_telemetry": list(decision.decision_telemetry),
                          "budget": _budget(checkpoint), "repeat": False,
                          "new_injection_count": len(decision.injections),
                          "native_context_replacement": False, "model_api_calls": 0}
                state["queries"][node_id] = result
                state["controller"] = checkpoint
            state["calls"] += 1
            _save_state(private, state)
            return result
        finally:
            if store is not None:
                store.close()
