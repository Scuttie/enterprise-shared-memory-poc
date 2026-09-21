"""Opt-in SK hynix memory adapters for the existing TriMem execution loop.

The SQLite library is an experimental local backend. These adapters do not
change the frozen production arms, their PostgreSQL schema, or benchmark locks.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from .accounting import canonical_bytes, sha256_bytes
from .agent_runtime import CellScientificFailure, RuntimeFailure, TriMemAgentRuntime
from .context_projection import MAX_SOLVE_PROMPT_UTF8_BYTES, ContextProjectionError
from .ppr import DeterministicHashEmbedder, GraphNode, SeedSignal, lexical_similarity, rank_graph
from .retrieval import MemoryInjection, RecallDecision
from .skill_memory import EpisodeEvidence, SkillMemoryStore


class SkillLayer(str, Enum):
    """Explicit layer labels on the common runtime's injection wire format."""

    SKILL = "SKILL"
    REPOSITORY_SEMANTIC = "REPOSITORY_SEMANTIC"
    EPISODIC = "EPISODIC"


def _hash(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w]+", text.casefold()))


def _injection_row(item: MemoryInjection) -> dict[str, Any]:
    row = asdict(item)
    row.pop("exact_utf8")
    row["kind"] = item.kind.value
    return row


class SkillFirstMemoryController:
    """Skill library -> repository KG -> personal history, one view per node.

    Applicability/tenant filtering precedes ranking. Repository ranking uses
    the existing PPR implementation over explicit knowledge edges. Episodes
    use recency after a subgoal relevance check, including labelled failures.
    Retrieval never executes a procedure or exposes its private support rows.
    """

    def __init__(self, store: SkillMemoryStore, *, task_id: str, language: str = "python",
                 context_budget_bytes: int = 12_000, max_injections_per_task: int = 3,
                 min_score: float = 0.05, parameters: Mapping[str, str] | None = None,
                 repository_retrieval_texts: Mapping[str, str] | None = None,
                 repository_exact_task_routes: Mapping[str, str] | None = None):
        if not task_id or context_budget_bytes <= 0 or max_injections_per_task <= 0:
            raise ValueError("task id and positive injection budgets are required")
        if not math.isfinite(min_score) or not 0 <= min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        self.store = store
        self.task_id = task_id
        self.language = language
        self.context_budget_bytes = context_budget_bytes
        self.max_injections_per_task = max_injections_per_task
        self.min_score = min_score
        self.parameters = dict(parameters) if parameters is not None else None
        if repository_retrieval_texts is not None and (
                not isinstance(repository_retrieval_texts, Mapping) or
                any(not isinstance(key, str) or not key.startswith("knowledge:") or
                    not isinstance(value, str) or not value.strip()
                    for key, value in repository_retrieval_texts.items())):
            raise ValueError("repository retrieval texts require knowledge ids and nonempty text")
        self._repository_retrieval_texts = (MappingProxyType(dict(repository_retrieval_texts))
            if repository_retrieval_texts is not None else None)
        if repository_exact_task_routes is not None and (
                not isinstance(repository_exact_task_routes, Mapping) or
                any(not isinstance(key, str) or not key.startswith("knowledge:") or
                    not isinstance(value, str) or not value.strip()
                    for key, value in repository_exact_task_routes.items())):
            raise ValueError("repository exact-task routes require knowledge ids and task ids")
        self._repository_exact_task_routes = (MappingProxyType(dict(repository_exact_task_routes))
            if repository_exact_task_routes is not None else None)
        self._identity: dict[str, str] | None = None
        self._recalled: set[str] = set()
        self._ledger: list[MemoryInjection] = []
        self._source_hashes: dict[str, str] = {}
        self._task = None

    @property
    def content_hash(self) -> str:
        value = {
            "adapter": "skhynix-skill-first/1.0", "language": self.language,
            "order": [layer.value for layer in SkillLayer],
            "context_budget_bytes": self.context_budget_bytes,
            "max_injections_per_task": self.max_injections_per_task,
            "min_score": self.min_score, "parameters": self.parameters,
            "embedder": DeterministicHashEmbedder().provenance(),
            "personal_retrieval": "relevance-filter-then-recency",
        }
        # Omit the opt-in field entirely to retain the original configuration hash.
        if self._repository_retrieval_texts is not None:
            value["repository_retrieval_texts"] = dict(self._repository_retrieval_texts)
        if self._repository_exact_task_routes is not None:
            value["repository_exact_task_routes"] = dict(self._repository_exact_task_routes)
        return _hash(value)

    def _snapshot(self, task):
        return self.store.snapshot(org_id=task.org_id, user_id=task.user_id,
                                   repository=task.repository, revision=task.commit,
                                   language=self.language)

    def _bind(self, task) -> None:
        identity = {key: getattr(task, key) for key in
                    ("task_id", "org_id", "user_id", "repository", "commit")}
        if task.task_id != self.task_id or (self._identity is not None and identity != self._identity):
            raise RuntimeFailure("SK hynix memory task/scope identity changed")
        self._identity = identity
        self._task = task

    @staticmethod
    def _canonical_records(snapshot) -> dict[str, str]:
        return {**{row.skill_id: row.content_hash for row in snapshot.skills},
                **{row.knowledge_id: row.content_hash for row in snapshot.repository_knowledge},
                **{row.episode_id: row.content_hash for row in snapshot.episodes}}

    def _check_exact_task_routes(self, snapshot, task_id: str) -> None:
        routes = self._repository_exact_task_routes
        if routes is not None and (
                any(target != task_id for target in routes.values()) or
                not set(routes).issubset(row.knowledge_id for row in snapshot.repository_knowledge)):
            raise RuntimeFailure("repository exact-task routes are outside the bound task or memory scope")

    def _check_retained(self, snapshot, *, ledger=None, source_hashes=None) -> None:
        ledger = self._ledger if ledger is None else ledger
        source_hashes = self._source_hashes if source_hashes is None else source_hashes
        current = self._canonical_records(snapshot)
        if any(current.get(key) != digest for key, digest in source_hashes.items()):
            # Fail closed: a revoked view must not survive in a resumed prompt.
            raise RuntimeFailure("injected memory changed or was revoked; start a fresh task")
        views = {**{row.skill_id: (row, SkillLayer.SKILL) for row in snapshot.skills},
                 **{row.knowledge_id: (row, SkillLayer.REPOSITORY_SEMANTIC)
                    for row in snapshot.repository_knowledge},
                 **{row.episode_id: (row, SkillLayer.EPISODIC) for row in snapshot.episodes}}
        for item in ledger:
            row, layer = views[item.memory_id]
            if item.kind != layer or item.exact_text != self._execution_view(row, layer):
                raise RuntimeFailure("injected view does not match canonical memory")

    def _execution_view(self, row, layer) -> str:
        if layer == SkillLayer.SKILL:
            return row.execution_view(self.parameters)
        if layer == SkillLayer.REPOSITORY_SEMANTIC:
            value = {"layer": layer.value, "title": row.title,
                     "content": row.content, "revision": row.revision}
        else:
            evidence = row.evidence
            value = {"layer": layer.value, "subgoal": evidence.subgoal,
                     "summary": evidence.summary, "actions": evidence.actions,
                     "source_outcome": "passed" if evidence.succeeded else "failed",
                     "source_revision": evidence.revision,
                     "verification_command": evidence.verification_command}
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def recall(self, graph, task) -> RecallDecision:
        self._bind(task)
        node = graph.active_node
        if node is None or graph.task_id != self.task_id or graph.repository != task.repository:
            raise RuntimeFailure("skill recall requires the bound task's active subgoal")
        snapshot = self._snapshot(task)
        if (self._repository_retrieval_texts is not None and
                not set(self._repository_retrieval_texts).issubset(
                    row.knowledge_id for row in snapshot.repository_knowledge)):
            raise RuntimeFailure("repository retrieval texts are outside the current memory scope")
        self._check_retained(snapshot)
        self._check_exact_task_routes(snapshot, task.task_id)
        if node.node_id in self._recalled:
            return RecallDecision(node.node_id, (), ({"bank": "ALL", "decision": "RESUME"},), ())
        query = " ".join((node.objective, node.operation, *node.symbols, *node.apis, *node.errors))
        traces: list[dict] = []
        rejected: list[dict] = []
        chosen: list[MemoryInjection] = []
        banks = ((SkillLayer.SKILL, snapshot.skills),
                 (SkillLayer.REPOSITORY_SEMANTIC, snapshot.repository_knowledge),
                 (SkillLayer.EPISODIC, snapshot.episodes))
        for layer, records in banks:
            candidates = []
            exact_candidates = []
            for row in records:
                if layer == SkillLayer.SKILL:
                    identity, text = row.skill_id, row.template.subgoal_signature
                elif layer == SkillLayer.REPOSITORY_SEMANTIC:
                    identity, text = row.knowledge_id, row.title + " " + row.content
                    if self._repository_retrieval_texts is not None:
                        text = self._repository_retrieval_texts.get(identity, text)
                else:
                    identity, text = row.episode_id, row.evidence.subgoal + " " + row.evidence.summary
                    if row.evidence.task_id == task.task_id:
                        rejected.append({"bank": layer.value, "memory_id": identity,
                                         "reason": "TARGET_DERIVED"})
                        continue
                # Hash embeddings alone can collide for completely unrelated text.
                score = lexical_similarity(" ".join(sorted(_tokens(query))),
                                           " ".join(sorted(_tokens(text))))
                if (layer == SkillLayer.REPOSITORY_SEMANTIC and
                        self._repository_exact_task_routes is not None and
                        identity in self._repository_exact_task_routes):
                    # The bridge opts in only for an exactly bound retained failure.
                    # Route by that identity, preserving the measured lexical score;
                    # this is neither a similarity seed nor evidence of a verified fix.
                    exact_candidates.append((row, identity, text, score))
                    continue
                if (layer != SkillLayer.REPOSITORY_SEMANTIC and
                        (score < self.min_score or not _tokens(query).intersection(_tokens(text)))):
                    continue
                candidates.append((row, identity, text, score))
            if layer == SkillLayer.EPISODIC:
                candidates.sort(key=lambda c: (c[0].evidence.created_at, c[1]), reverse=True)
            elif layer == SkillLayer.REPOSITORY_SEMANTIC and candidates:
                # Keep unseeded but reachable records in the graph: pruning them
                # by lexical overlap would erase the associative search path.
                seeded = {c[1] for c in candidates if c[3] >= self.min_score and
                          _tokens(query).intersection(_tokens(c[2]))}
                nodes = {c[1]: GraphNode(c[1], c[2]) for c in candidates}
                adjacency: dict[str, dict[str, float]] = {key: {} for key in nodes}
                for edge in snapshot.knowledge_edges:
                    source, target = edge[0], edge[1]
                    if source in nodes and target in nodes:
                        adjacency[source][target] = float(edge[2]) if len(edge) > 2 else 1.0
                reachable = set(seeded)
                pending = list(seeded)
                while pending:
                    for neighbor in adjacency[pending.pop()]:
                        if neighbor not in reachable:
                            reachable.add(neighbor)
                            pending.append(neighbor)
                nodes = {key: value for key, value in nodes.items() if key in reachable}
                adjacency = {key: value for key, value in adjacency.items() if key in reachable}
                # Lexical-only seeds prevent feature-hash collisions seeding an
                # unrelated graph component in this local reference backend.
                ranking = rank_graph(nodes, adjacency, [SeedSignal("subgoal", query)],
                                     embedding_weight=0.0, lexical_weight=1.0)
                order = {item.node_id: index for index, item in enumerate(ranking)}
                scores = {item.node_id: item.score for item in ranking}
                candidates = [(c[0], c[1], c[2], scores[c[1]]) for c in candidates if c[1] in order]
                candidates.sort(key=lambda c: (order[c[1]], c[1]))
            else:
                candidates.sort(key=lambda c: (-c[3], c[1]))
            candidates = sorted(exact_candidates, key=lambda c: c[1]) + candidates
            for row, identity, _, score in candidates:
                if identity in self._source_hashes:
                    rejected.append({"bank": layer.value, "memory_id": identity,
                                     "reason": "ALREADY_INJECTED"})
                    continue
                try:
                    view = self._execution_view(row, layer)
                except ValueError:
                    rejected.append({"bank": layer.value, "memory_id": identity,
                                     "reason": "PARAMETER_BINDING_REJECTED"})
                    continue
                raw = view.encode("utf-8")
                if (not raw or len(self._ledger) >= self.max_injections_per_task or
                        sum(x.byte_count for x in self._ledger) + len(raw) > self.context_budget_bytes):
                    rejected.append({"bank": layer.value, "memory_id": identity,
                                     "reason": "CONTEXT_INJECTION_BUDGET"})
                    continue
                # MemoryInjection is a value container; the experimental wire
                # labels stay distinct without extending the frozen V1 enum.
                item = MemoryInjection(identity, layer, node.node_id, view, raw, len(raw),
                                       sha256_bytes(raw), score, 0.0, snapshot.content_hash,
                                       row.content_hash, canonical_node_hash=row.content_hash)
                chosen.append(item)
                self._ledger.append(item)
                self._source_hashes[identity] = row.content_hash
                break
            exact_ids = [c[1] for c in exact_candidates]
            exact_selected = bool(chosen and chosen[-1].memory_id in exact_ids)
            traces.append({"bank": layer.value, "candidate_count": len(records),
                           "eligible_count": len(candidates),
                           "decision": "USE" if chosen else "ABSTAIN",
                           "policy": "EXACT_TASK_DIAGNOSTIC_ROUTE" if exact_selected else "SKILL_REPO_EPISODE",
                           "snapshot_sha256": snapshot.content_hash,
                           **({"exact_task_route": {"policy": "EXACT_TASK_DIAGNOSTIC_ROUTE",
                               "task_id": task.task_id, "candidate_ids": exact_ids,
                               "selected": exact_selected}} if exact_ids else {})})
            if chosen:
                break
        self._recalled.add(node.node_id)
        return RecallDecision(node.node_id, tuple(chosen), tuple(traces), tuple(rejected))

    def context_for(self, active_node_id: str) -> tuple[MemoryInjection, ...]:
        if self._identity is not None:
            scope = self._identity
            snapshot = self.store.snapshot(
                org_id=scope["org_id"], user_id=scope["user_id"], repository=scope["repository"],
                revision=scope["commit"], language=self.language)
            self._check_retained(snapshot)
            self._check_exact_task_routes(snapshot, scope["task_id"])
        return tuple(item for item in self._ledger if item.active_node_id == active_node_id)

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {"mode": "SKHYNIX", "task_id": self.task_id, "config_hash": self.content_hash,
                "identity": self._identity, "recalled_nodes": sorted(self._recalled),
                "ledger": [_injection_row(item) for item in self._ledger],
                "source_hashes": dict(self._source_hashes)}

    def restore(self, value: Mapping[str, Any]) -> None:
        if (value.get("mode") != "SKHYNIX" or value.get("task_id") != self.task_id or
                value.get("config_hash") != self.content_hash):
            raise RuntimeFailure("SK hynix memory checkpoint configuration mismatch")
        ledger = []
        try:
            for row in value.get("ledger", ()):
                fields = dict(row)
                fields["kind"] = SkillLayer(fields["kind"])
                fields["exact_utf8"] = fields["exact_text"].encode("utf-8")
                item = MemoryInjection(**fields)
                if not item.verify():
                    raise ValueError("hash")
                ledger.append(item)
            source_hashes = dict(value.get("source_hashes", {}))
            recalled = set(value.get("recalled_nodes", ()))
            if (len(ledger) > self.max_injections_per_task or
                    sum(x.byte_count for x in ledger) > self.context_budget_bytes or
                    len({x.memory_id for x in ledger}) != len(ledger) or
                    len({x.active_node_id for x in ledger}) != len(ledger) or
                    any(x.active_node_id not in recalled for x in ledger) or
                    source_hashes != {x.memory_id: x.canonical_node_hash for x in ledger}):
                raise ValueError("ledger budgets or identities")
            identity = value.get("identity")
            if identity is not None:
                if set(identity) != {"task_id", "org_id", "user_id", "repository", "commit"}:
                    raise ValueError("identity")
                if identity["task_id"] != self.task_id:
                    raise ValueError("task identity")
                snapshot = self.store.snapshot(org_id=identity["org_id"], user_id=identity["user_id"],
                                               repository=identity["repository"], revision=identity["commit"],
                                               language=self.language)
                current = self._canonical_records(snapshot)
                if any(current.get(key) != digest for key, digest in source_hashes.items()):
                    raise ValueError("revoked or changed source")
                self._check_retained(snapshot, ledger=ledger, source_hashes=source_hashes)
                self._check_exact_task_routes(snapshot, identity["task_id"])
            elif ledger or recalled:
                raise ValueError("missing scope identity")
        except (KeyError, TypeError, ValueError, RuntimeFailure) as exc:
            raise RuntimeFailure("invalid SK hynix memory checkpoint") from exc
        self._ledger, self._source_hashes, self._recalled = ledger, source_hashes, recalled
        self._identity = dict(identity) if identity else None


class GateAExperienceLifecycle:
    """Automatically retain terminal outcomes privately; sharing is offline."""

    content_hash = _hash({"lifecycle": "skhynix-gate-a/1.0", "sharing": "offline-only"})

    def __init__(self, store: SkillMemoryStore, *, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def store_experience(self, task, graph, extraction, grade, injections):
        summary = str(extraction.episode.get("summary", "Completed coding attempt"))
        action = str(extraction.episode.get("action", "See retained public task evidence"))
        verification = str(extraction.episode.get("verification", ""))
        # Only public extraction and the verdict/hash cross the grader boundary.
        evidence = EpisodeEvidence(
            org_id=task.org_id, user_id=task.user_id, repository=task.repository,
            task_id=task.task_id, revision=task.commit,
            subgoal="; ".join(n.objective for n in graph.nodes.values()),
            summary=summary, actions=(action,), succeeded=bool(grade.resolved),
            verification_command=verification,
            verification_evidence_hash="sha256:" + extraction.public_evidence_hash, created_at=self.clock(),
            artifact_hashes=(("patch", "sha256:" + extraction.patch_hash),
                             ("public_evidence", "sha256:" + extraction.public_evidence_hash)),
        )
        episode = self.store.record_episode(evidence)
        return {"storage_action": "GATE_A_PRIVATE_EPISODE", "memory_id": episode.episode_id,
                "retained_records": 1, "archived_records": 0, "net_memory_growth": 1,
                "shared_records": 0}

    def credit_outcome(self, task, grade, injections, *, outcome_metrics):
        # A task verdict alone does not prove that a retrieved procedure's exact
        # instantiation ran. Gate B consumes independently verified evidence.
        return {"credited": 0, "policy_training": False}


class SkhynixAgentRuntime(TriMemAgentRuntime):
    """The existing execution/grading loop with subgoal-chunked solve context."""

    def _configuration_hashes(self, task):
        result = super()._configuration_hashes(task)
        result["skhynix_subgoal_context"] = _hash({"schema": "skhynix-subgoal-context/1.0"})
        return result

    def _solve_prompt_projection(self, task, graph, history, injections):
        from .subgoal_context import project_subgoal_context

        base_prompt, _ = super()._solve_prompt_projection(task, graph, [], injections)
        prefix, payload = base_prompt.rsplit("\n\nSTATE:\n", 1)
        body = json.loads(payload)
        cap = min(48_000, MAX_SOLVE_PROMPT_UTF8_BYTES - len(base_prompt.encode("utf-8")) - 2_048)
        if cap < 2_048:
            raise CellScientificFailure("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED")
        try:
            projection = project_subgoal_context(graph, history, max_bytes=cap)
        except ContextProjectionError as exc:
            raise CellScientificFailure("TASK_TOOL_RESULT_PROJECTION_FAILURE") from exc
        body["subgoal_working_memory"] = projection.public_dict()
        body["tool_history"] = body["subgoal_working_memory"]["active_history"]
        # Keep one copy of the observations in the established reader location.
        body["subgoal_working_memory"].pop("active_history")
        prompt = self._json_prompt(prefix, "\n\nSTATE:\n", body)
        if len(prompt.encode("utf-8")) > MAX_SOLVE_PROMPT_UTF8_BYTES:
            raise CellScientificFailure("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED")
        return prompt, projection.record(final_prompt=prompt)
