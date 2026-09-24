"""Local, durable reference implementation of the SK hynix L1/L2/L3 proposal.

Gate A retains private verification-labelled episodes. Gate B is an explicit
offline operation over independently verified, parameterised procedures. The
SQLite authority is for local experiments; it is not a production PostgreSQL
adapter or an authentication service. Callers supply authenticated scope and
trusted verifier labels. Stored commands are data and are never executed here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter
from typing import Any, Mapping, Sequence

from enterprise_memory.promotion.security_scan import PASS, REVIEW_SOURCE_EXCERPT, scan

from .schema import canonical_hash


SCHEMA_VERSION = "skhynix/skill-memory/1.0"


class SkillMemoryError(ValueError):
    pass


class PromotionRejected(SkillMemoryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillMemoryError(f"{label} must be nonempty text")
    return value


def _strings(values: Sequence[str], label: str, *, required: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise SkillMemoryError(f"{label} must be a sequence of strings")
    result = tuple(_text(value, label) for value in values)
    if required and not result:
        raise SkillMemoryError(f"{label} cannot be empty")
    return result


def _digest(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class EpisodeEvidence:
    org_id: str
    user_id: str
    repository: str
    task_id: str
    revision: str
    subgoal: str
    summary: str
    actions: tuple[str, ...]
    succeeded: bool
    verification_command: str = ""
    verification_evidence_hash: str = ""
    created_at: str = field(default_factory=_now)
    procedure_hash: str = ""
    parameter_bindings: tuple[tuple[str, str], ...] = ()
    artifact_hashes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("org_id", "user_id", "repository", "task_id", "revision", "subgoal", "summary"):
            _text(getattr(self, name), name)
        if type(self.succeeded) is not bool:
            raise SkillMemoryError("succeeded must be boolean")
        object.__setattr__(self, "actions", _strings(self.actions, "actions"))
        bindings = tuple(tuple(row) for row in self.parameter_bindings)
        if any(len(row) != 2 for row in bindings):
            raise SkillMemoryError("parameter bindings must contain name/value pairs")
        for key, value in bindings:
            _text(key, "parameter name")
            _text(value, "parameter value")
        if len({row[0] for row in bindings}) != len(bindings):
            raise SkillMemoryError("duplicate parameter binding")
        object.__setattr__(self, "parameter_bindings", tuple(sorted(bindings)))
        artifacts = tuple(tuple(row) for row in self.artifact_hashes)
        if any(len(row) != 2 for row in artifacts):
            raise SkillMemoryError("artifact hashes must contain label/digest pairs")
        for label, digest in artifacts:
            _text(label, "artifact label")
            if not _digest(digest):
                raise SkillMemoryError("artifact hash must be a canonical SHA-256 digest")
        if len({row[0] for row in artifacts}) != len(artifacts):
            raise SkillMemoryError("duplicate artifact label")
        object.__setattr__(self, "artifact_hashes", tuple(sorted(artifacts)))
        try:
            stamp = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise SkillMemoryError("created_at must be an ISO timestamp") from exc
        if stamp.tzinfo is None:
            raise SkillMemoryError("created_at must include a timezone")
        for name in ("verification_evidence_hash", "procedure_hash"):
            value = getattr(self, name)
            if value and not _digest(value):
                raise SkillMemoryError(f"{name} must be a canonical SHA-256 digest")


@dataclass(frozen=True)
class Episode:
    episode_id: str
    evidence: EpisodeEvidence
    content_hash: str


@dataclass(frozen=True)
class RenderedProcedure:
    steps: tuple[str, ...]
    verification_command: str
    preconditions: tuple[str, ...]


@dataclass(frozen=True)
class ProcedureTemplate:
    subgoal_signature: str
    parameters: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    verification_command: str
    language: str = ""

    def __post_init__(self) -> None:
        _text(self.subgoal_signature, "subgoal_signature")
        _text(self.verification_command, "verification_command")
        object.__setattr__(self, "parameters", _strings(self.parameters, "parameters", required=True))
        object.__setattr__(self, "preconditions", _strings(self.preconditions, "preconditions", required=True))
        object.__setattr__(self, "steps", _strings(self.steps, "steps", required=True))
        if not isinstance(self.language, str):
            raise SkillMemoryError("language must be text")
        if len(set(self.parameters)) != len(self.parameters) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in self.parameters
        ):
            raise SkillMemoryError("parameters must be unique simple names")
        used: set[str] = set()
        try:
            for text in (self.subgoal_signature, *self.preconditions, *self.steps, self.verification_command):
                for _, name, spec, conversion in Formatter().parse(text):
                    if name is None:
                        continue
                    if name not in self.parameters or spec or conversion:
                        raise SkillMemoryError("only declared simple {parameter} placeholders are allowed")
                    used.add(name)
        except ValueError as exc:
            raise SkillMemoryError("invalid procedure parameter placeholder") from exc
        if used != set(self.parameters):
            raise SkillMemoryError("every declared parameter must be used")

    @property
    def content_hash(self) -> str:
        return canonical_hash(asdict(self))

    def render(self, parameters: Mapping[str, str]) -> RenderedProcedure:
        if set(parameters) != set(self.parameters):
            raise SkillMemoryError("procedure bindings must match all declared parameters exactly")
        for value in parameters.values():
            _text(value, "parameter value")
        return RenderedProcedure(
            steps=tuple(step.format_map(parameters) for step in self.steps),
            verification_command=self.verification_command.format_map(parameters),
            preconditions=tuple(step.format_map(parameters) for step in self.preconditions),
        )


def scan_procedure_template(template: ProcedureTemplate, *, skill_id: str | None = None) -> dict[str, Any]:
    """Scan public template text without treating parameter syntax as source code.

    Secrets, PII and entropy are always checked on the complete original text.
    Only the source-excerpt heuristic understands the already validated typed
    placeholders. Literal source, escaped literal braces, prose and the source
    line threshold remain subject to the existing scanner. Instance bindings
    are private evidence and are never substituted into this shared payload.
    """
    if not isinstance(template, ProcedureTemplate):
        raise SkillMemoryError("template security scan requires a typed procedure")
    formatted = (template.subgoal_signature, *template.preconditions,
                 *template.steps, template.verification_command)
    suffix = (template.language, skill_id or "")
    original = scan("\n".join((*formatted, *suffix)))
    if original["result"] != REVIEW_SOURCE_EXCERPT:
        return original
    literals = []
    for text in formatted:
        pieces = []
        for literal, name, spec, conversion in Formatter().parse(text):
            # ProcedureTemplate validates this contract on construction. Keep
            # the boundary explicit rather than stripping arbitrary braces.
            if name is not None and (name not in template.parameters or spec or conversion):
                raise SkillMemoryError("only declared simple parameter syntax can be normalized")
            pieces.append(literal)
            if name is not None:
                pieces.append(name)
        literals.append("".join(pieces))
    return scan("\n".join((*literals, *suffix)))


@dataclass(frozen=True)
class Skill:
    skill_id: str
    org_id: str
    template: ProcedureTemplate
    support_count: int
    contributor_count: int
    promoted_at: str
    evidence_set_hash: str
    content_hash: str

    def public_view(self) -> dict[str, Any]:
        """Only the pattern and aggregate validation metadata cross the boundary."""
        return {
            "skill_id": self.skill_id,
            "kind": "verified_parameterised_skill",
            **asdict(self.template),
            "support_count": self.support_count,
            "contributor_count": self.contributor_count,
        }

    def execution_view(self, parameters: Mapping[str, str] | None = None) -> str:
        value = self.public_view()
        if parameters is not None:
            rendered = self.template.render(parameters)
            value.update(asdict(rendered))
        return _json(value)


@dataclass(frozen=True)
class RepositoryKnowledge:
    knowledge_id: str
    org_id: str
    repository: str
    title: str
    content: str
    revision: str
    language: str
    content_hash: str


@dataclass(frozen=True)
class KnowledgeRelation:
    source_id: str
    target_id: str
    relation: str


@dataclass(frozen=True)
class MemorySnapshot:
    skills: tuple[Skill, ...]
    repository_knowledge: tuple[RepositoryKnowledge, ...]
    episodes: tuple[Episode, ...]
    content_hash: str
    knowledge_edges: tuple[tuple[str, str, float], ...] = ()


class SkillMemoryStore:
    """SQLite authority with explicit private/repository/organisation partitions.

    Public lookup only exposes current records. Revocations are permanent for a
    record identity; re-verification creates a new version rather than silently
    reviving cached content. No private evidence is embedded in shared rows.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self._db.close()
            raise SkillMemoryError("unsupported skill memory schema version")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_records (
                record_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                org_id TEXT NOT NULL, owner_user_id TEXT,
                repository TEXT, revision TEXT,
                payload TEXT NOT NULL, content_hash TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                revocation_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS memory_partition
                ON memory_records(org_id, kind, owner_user_id, repository);
            CREATE TABLE IF NOT EXISTS skill_support (
                skill_id TEXT NOT NULL REFERENCES memory_records(record_id),
                episode_id TEXT NOT NULL REFERENCES memory_records(record_id),
                PRIMARY KEY(skill_id, episode_id)
            );
            CREATE TABLE IF NOT EXISTS knowledge_relations (
                source_id TEXT NOT NULL REFERENCES memory_records(record_id),
                target_id TEXT NOT NULL REFERENCES memory_records(record_id),
                relation TEXT NOT NULL,
                PRIMARY KEY(source_id, target_id, relation)
            );
            CREATE TABLE IF NOT EXISTS repository_heads (
                org_id TEXT NOT NULL, repository TEXT NOT NULL, revision TEXT NOT NULL,
                PRIMARY KEY(org_id, repository)
            );
            PRAGMA user_version=1;
        """)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SkillMemoryStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _insert(self, record_id: str, kind: str, payload: dict[str, Any], *, org_id: str,
                owner_user_id: str | None = None, repository: str | None = None,
                revision: str | None = None) -> str:
        digest = canonical_hash(payload)
        old = self._db.execute("SELECT * FROM memory_records WHERE record_id=?", (record_id,)).fetchone()
        if old is not None:
            self._verify(old)
            if old["content_hash"] != digest or old["kind"] != kind or old["revoked"]:
                raise SkillMemoryError("record identity is immutable or revoked")
            return digest
        self._db.execute(
            "INSERT INTO memory_records(record_id,kind,org_id,owner_user_id,repository,revision,payload,content_hash) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (record_id, kind, org_id, owner_user_id, repository, revision, _json(payload), digest),
        )
        return digest

    @staticmethod
    def _verify(row: sqlite3.Row) -> dict[str, Any]:
        value = json.loads(row["payload"])
        if canonical_hash(value) != row["content_hash"]:
            raise SkillMemoryError("canonical memory content hash mismatch")
        identity_key = {"episode": "episode_id", "skill": "skill_id", "knowledge": "knowledge_id"}.get(row["kind"])
        if identity_key is None or value.get(identity_key) != row["record_id"]:
            raise SkillMemoryError("canonical memory kind or identity mismatch")
        # Partition columns are query indexes, not an independent authority.
        scope = value["evidence"] if row["kind"] == "episode" else value
        if scope["org_id"] != row["org_id"]:
            raise SkillMemoryError("canonical memory organisation mismatch")
        if row["kind"] == "episode" and scope["user_id"] != row["owner_user_id"]:
            raise SkillMemoryError("canonical private owner mismatch")
        if row["kind"] != "episode" and row["owner_user_id"] is not None:
            raise SkillMemoryError("shared memory has a private owner")
        if row["kind"] != "skill" and (
            scope["repository"] != row["repository"] or scope["revision"] != row["revision"]
        ):
            raise SkillMemoryError("canonical repository or revision mismatch")
        return value

    @staticmethod
    def _episode(row: sqlite3.Row) -> Episode:
        if row["kind"] != "episode":
            raise SkillMemoryError("skill support is not private episode evidence")
        value = SkillMemoryStore._verify(row)
        return Episode(value["episode_id"], EpisodeEvidence(**value["evidence"]), row["content_hash"])

    def _skill(self, row: sqlite3.Row) -> Skill:
        value = SkillMemoryStore._verify(row)
        support_rows = self._db.execute(
            "SELECT e.* FROM skill_support s JOIN memory_records e ON e.record_id=s.episode_id "
            "WHERE s.skill_id=? ORDER BY e.record_id", (row["record_id"],),
        ).fetchall()
        episodes = [self._episode(item) for item in support_rows]
        if (
            len(episodes) < 2
            or any(item.evidence.org_id != row["org_id"] for item in episodes)
            or canonical_hash([item.content_hash for item in episodes]) != value["evidence_set_hash"]
        ):
            raise SkillMemoryError("canonical skill evidence provenance mismatch")
        value["template"] = ProcedureTemplate(**value["template"])
        return Skill(**value, content_hash=row["content_hash"])

    @staticmethod
    def _knowledge(row: sqlite3.Row) -> RepositoryKnowledge:
        value = SkillMemoryStore._verify(row)
        return RepositoryKnowledge(**value, content_hash=row["content_hash"])

    def record_episode(self, evidence: EpisodeEvidence) -> Episode:
        """Gate A: automatically retain successful and failed private attempts."""
        if not isinstance(evidence, EpisodeEvidence):
            raise SkillMemoryError("Gate A requires typed episode evidence")
        episode_id = "episode:" + canonical_hash({
            key: getattr(evidence, key)
            for key in ("org_id", "user_id", "repository", "task_id", "revision", "subgoal")
        })[7:]
        payload = {"episode_id": episode_id, "evidence": asdict(evidence)}
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            previous = self._db.execute("SELECT * FROM memory_records WHERE record_id=?", (episode_id,)).fetchone()
            if previous is not None:
                existing = self._episode(previous)
                old, new = asdict(existing.evidence), asdict(evidence)
                old.pop("created_at")
                new.pop("created_at")
                if old != new or previous["revoked"]:
                    raise SkillMemoryError("task/subgoal evidence is immutable")
                return existing
            digest = self._insert(
                episode_id, "episode", payload, org_id=evidence.org_id,
                owner_user_id=evidence.user_id, repository=evidence.repository, revision=evidence.revision,
            )
        return Episode(episode_id, evidence, digest)

    def get_episode(self, episode_id: str, *, org_id: str, user_id: str) -> Episode | None:
        row = self._db.execute(
            "SELECT * FROM memory_records WHERE record_id=? AND kind='episode' AND org_id=? "
            "AND owner_user_id=? AND revoked=0", (episode_id, org_id, user_id),
        ).fetchone()
        return self._episode(row) if row is not None else None

    def promote_skill(self, template: ProcedureTemplate, evidence_ids: Sequence[str], *,
                      org_id: str, skill_id: str | None = None) -> Skill:
        """Offline Gate B; inputs are trusted verifier observations, never model claims.

        Two distinct successful tasks, contributors and verifier artifacts must
        demonstrate the exact same template under their explicit bindings. The
        evidence join remains private inside this local authority.
        """
        _text(org_id, "org_id")
        if not isinstance(template, ProcedureTemplate):
            raise PromotionRejected("Gate B requires a typed procedure template")
        ids = tuple(sorted(set(evidence_ids)))
        if len(ids) < 2:
            raise PromotionRejected("Gate B requires at least two independent verification observations")
        public_text = "\n".join((template.subgoal_signature, *template.preconditions,
                                  *template.steps, template.verification_command, template.language,
                                  skill_id or ""))
        if scan_procedure_template(template, skill_id=skill_id)["result"] != PASS:
            raise PromotionRejected("shared procedure failed privacy/security scan")
        episodes: list[Episode] = []
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            for episode_id in ids:
                row = self._db.execute(
                    "SELECT * FROM memory_records WHERE record_id=? AND org_id=? AND kind='episode' "
                    "AND revoked=0", (episode_id, org_id),
                ).fetchone()
                if row is None:
                    raise PromotionRejected("support evidence is unavailable in this organisation")
                episode = self._episode(row)
                evidence = episode.evidence
                head = self._db.execute(
                    "SELECT revision FROM repository_heads WHERE org_id=? AND repository=?",
                    (org_id, evidence.repository),
                ).fetchone()
                if head is not None and head[0] != evidence.revision:
                    raise PromotionRejected("support belongs to an invalidated repository revision")
                if not evidence.succeeded or not _digest(evidence.verification_evidence_hash):
                    raise PromotionRejected("all support must have successful verifier evidence")
                if evidence.procedure_hash != template.content_hash:
                    raise PromotionRejected("support was not verified against this procedure template")
                try:
                    rendered = template.render(dict(evidence.parameter_bindings))
                except SkillMemoryError as exc:
                    raise PromotionRejected("support has incomplete procedure bindings") from exc
                if evidence.actions != rendered.steps or evidence.verification_command != rendered.verification_command:
                    raise PromotionRejected("observed actions and verification must match the bound procedure")
                private_values = (
                    evidence.user_id, evidence.task_id, evidence.repository, evidence.revision,
                    *(value for _, value in evidence.parameter_bindings),
                )
                for value in private_values:
                    if len(value) >= 2 and value != template.language and re.search(
                        r"(?<![A-Za-z0-9_])" + re.escape(value) + r"(?![A-Za-z0-9_])", public_text,
                    ):
                        raise PromotionRejected("shared procedure contains an unparameterised private instance")
                episodes.append(episode)
            tasks = {episode.evidence.task_id for episode in episodes}
            users = {episode.evidence.user_id for episode in episodes}
            verifiers = {episode.evidence.verification_evidence_hash for episode in episodes}
            if min(len(tasks), len(users), len(verifiers)) < 2:
                raise PromotionRejected("Gate B requires distinct tasks, users and verifier artifacts")
            identity = canonical_hash({"org_id": org_id, "template": template.content_hash, "support": ids})
            identity = skill_id or "skill:" + identity[7:]
            _text(identity, "skill_id")
            old = self._db.execute("SELECT * FROM memory_records WHERE record_id=?", (identity,)).fetchone()
            promoted_at = self._verify(old)["promoted_at"] if old is not None and old["kind"] == "skill" else _now()
            payload = {
                "skill_id": identity, "org_id": org_id, "template": asdict(template),
                "support_count": len(tasks), "contributor_count": len(users), "promoted_at": promoted_at,
                "evidence_set_hash": canonical_hash([episode.content_hash for episode in episodes]),
            }
            digest = self._insert(identity, "skill", payload, org_id=org_id)
            existing = self._db.execute("SELECT episode_id FROM skill_support WHERE skill_id=?", (identity,)).fetchall()
            if existing and {row[0] for row in existing} != set(ids):
                raise PromotionRejected("skill evidence provenance is immutable")
            self._db.executemany("INSERT OR IGNORE INTO skill_support VALUES(?,?)", [(identity, eid) for eid in ids])
        return Skill(**{**payload, "template": template}, content_hash=digest)

    def put_repository_knowledge(self, *, org_id: str, repository: str, title: str, content: str,
                                 revision: str, language: str = "", knowledge_id: str | None = None) -> RepositoryKnowledge:
        """Store a revision-bound repository convention, architecture fact or owner rule."""
        payload = {"org_id": org_id, "repository": repository, "title": title,
                   "content": content, "revision": revision, "language": language}
        for name in ("org_id", "repository", "title", "content", "revision"):
            _text(payload[name], name)
        identity = knowledge_id or "knowledge:" + canonical_hash(payload)[7:]
        _text(identity, "knowledge_id")
        payload = {"knowledge_id": identity, **payload}
        with self._db:
            digest = self._insert(identity, "knowledge", payload, org_id=org_id, repository=repository, revision=revision)
        return RepositoryKnowledge(**payload, content_hash=digest)

    def link_repository_knowledge(self, source_id: str, target_id: str, relation: str, *, org_id: str,
                                  repository: str) -> KnowledgeRelation:
        _text(relation, "relation")
        if source_id == target_id:
            raise SkillMemoryError("knowledge self-relations are not allowed")
        with self._db:
            rows = [self._db.execute(
                "SELECT * FROM memory_records WHERE record_id=? AND kind='knowledge' AND org_id=? "
                "AND repository=? AND revoked=0", (identity, org_id, repository),
            ).fetchone() for identity in (source_id, target_id)]
            if any(row is None for row in rows):
                raise SkillMemoryError("knowledge relation crosses repository or organisation scope")
            entries = [self._knowledge(row) for row in rows]
            if entries[0].revision != entries[1].revision:
                raise SkillMemoryError("knowledge relation crosses revisions")
            self._db.execute("INSERT OR IGNORE INTO knowledge_relations VALUES(?,?,?)", (source_id, target_id, relation))
        return KnowledgeRelation(source_id, target_id, relation)

    def invalidate_skill(self, *, org_id: str, skill_id: str, reason: str) -> bool:
        _text(reason, "reason")
        with self._db:
            result = self._db.execute(
                "UPDATE memory_records SET revoked=1,revocation_reason=? "
                "WHERE record_id=? AND kind='skill' AND org_id=? AND revoked=0", (reason, skill_id, org_id),
            )
        return result.rowcount > 0

    def invalidate_repository(self, *, org_id: str, repository: str, current_revision: str) -> int:
        """Hard-revoke outdated repo facts and dependent skills; keep private history."""
        _text(current_revision, "current_revision")
        reason = "repository revision changed to " + current_revision
        with self._db:
            self._db.execute(
                "INSERT INTO repository_heads VALUES(?,?,?) ON CONFLICT(org_id,repository) "
                "DO UPDATE SET revision=excluded.revision", (org_id, repository, current_revision),
            )
            knowledge = self._db.execute(
                "UPDATE memory_records SET revoked=1,revocation_reason=? WHERE kind='knowledge' "
                "AND org_id=? AND repository=? AND revision<>? AND revoked=0",
                (reason, org_id, repository, current_revision),
            ).rowcount
            skills = self._db.execute(
                "UPDATE memory_records SET revoked=1,revocation_reason=? WHERE kind='skill' AND org_id=? "
                "AND revoked=0 AND record_id IN (SELECT s.skill_id FROM skill_support s JOIN memory_records e "
                "ON e.record_id=s.episode_id WHERE e.org_id=? AND e.repository=? AND e.revision<>?)",
                (reason, org_id, org_id, repository, current_revision),
            ).rowcount
        return knowledge + skills

    def snapshot(self, *, org_id: str, user_id: str, repository: str, revision: str = "",
                 language: str = "") -> MemorySnapshot:
        for name, value in (("org_id", org_id), ("user_id", user_id), ("repository", repository)):
            _text(value, name)
        # A transaction supplies a consistent read when another process is writing.
        self._db.execute("BEGIN")
        try:
            rows = self._db.execute(
                "SELECT * FROM memory_records WHERE org_id=? AND revoked=0 AND "
                "(kind='skill' OR (kind='knowledge' AND repository=?) OR "
                "(kind='episode' AND repository=? AND owner_user_id=?)) ORDER BY record_id",
                (org_id, repository, repository, user_id),
            ).fetchall()
            skills: list[Skill] = []
            knowledge: list[RepositoryKnowledge] = []
            episodes: list[Episode] = []
            for row in rows:
                if row["kind"] == "skill":
                    entry = self._skill(row)
                    stale_support = self._db.execute(
                        "SELECT 1 FROM skill_support s JOIN memory_records e ON e.record_id=s.episode_id "
                        "WHERE s.skill_id=? AND e.repository=? AND e.revision<>? LIMIT 1",
                        (entry.skill_id, repository, revision),
                    ).fetchone() if revision else None
                    if stale_support is not None:
                        continue
                    if not entry.template.language or (language and entry.template.language.lower() == language.lower()):
                        skills.append(entry)
                elif row["kind"] == "knowledge":
                    entry = self._knowledge(row)
                    # Unknown revision/language cannot establish applicability.
                    if entry.revision == revision and (not entry.language or (language and entry.language.lower() == language.lower())):
                        knowledge.append(entry)
                else:
                    episodes.append(self._episode(row))
            eligible = {entry.knowledge_id for entry in knowledge}
            edge_rows = self._db.execute("SELECT * FROM knowledge_relations ORDER BY source_id,target_id,relation").fetchall()
            edges = tuple((row["source_id"], row["target_id"], 1.0) for row in edge_rows
                          if row["source_id"] in eligible and row["target_id"] in eligible)
            episodes.sort(key=lambda entry: (entry.evidence.created_at, entry.episode_id), reverse=True)
            digest = canonical_hash({
                "schema": SCHEMA_VERSION, "org_id": org_id, "user_id": user_id,
                "repository": repository, "revision": revision, "language": language,
                "skills": [entry.content_hash for entry in skills],
                "repository_knowledge": [entry.content_hash for entry in knowledge],
                "episodes": [entry.content_hash for entry in episodes], "knowledge_edges": edges,
            })
            return MemorySnapshot(tuple(skills), tuple(knowledge), tuple(episodes), digest, edges)
        finally:
            self._db.rollback()
