"""Authoritative SQLite registry (handoff §3). Mem0 is a retrieval index, NOT the source of truth.
Canonical MemoryContracts + episodes + audit live here. foreign_keys ON, WAL, explicit transactions,
optimistic version field, immutable content hashes, deterministic canonical JSON, append-only audit,
acyclic supersession graph, schema-migration versioning. Behind a Repository interface so SQLite can
be replaced by Postgres."""
from __future__ import annotations
import abc
import json
import sqlite3
import hashlib
from dataclasses import asdict

SCHEMA_TARGET = 1

_MIGRATIONS = {
    1: [
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)",
        """CREATE TABLE private_episodes (episode_id TEXT PRIMARY KEY, owner_user_id TEXT, org_id TEXT,
            repo_id TEXT, task_id TEXT, content_hash TEXT NOT NULL, canonical_json TEXT NOT NULL,
            created_at TEXT)""",
        """CREATE TABLE memory_contracts (contract_id TEXT PRIMARY KEY, org_id TEXT, state TEXT,
            schema_version TEXT, version INTEGER NOT NULL DEFAULT 1, content_hash TEXT NOT NULL,
            canonical_json TEXT NOT NULL, superseded_by TEXT, created_at TEXT, updated_at TEXT)""",
        """CREATE TABLE contract_sources (contract_id TEXT, episode_id TEXT,
            PRIMARY KEY (contract_id, episode_id),
            FOREIGN KEY (contract_id) REFERENCES memory_contracts(contract_id),
            FOREIGN KEY (episode_id) REFERENCES private_episodes(episode_id))""",
        """CREATE TABLE promotion_decisions (decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT, outcome TEXT, failed_gate TEXT, reason TEXT, evidence_hash TEXT, t TEXT)""",
        """CREATE TABLE replay_evidence (evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, contract_id TEXT,
            replay_kind TEXT, success INTEGER, detail TEXT, t TEXT,
            FOREIGN KEY (contract_id) REFERENCES memory_contracts(contract_id))""",
        """CREATE TABLE retrieval_decisions (query_id TEXT PRIMARY KEY, content_hash TEXT,
            canonical_json TEXT, t TEXT)""",
        """CREATE TABLE outcome_observations (obs_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
            condition TEXT, content_hash TEXT, canonical_json TEXT, t TEXT)""",
        """CREATE TABLE audit_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, actor TEXT,
            subject TEXT, detail TEXT, prev_hash TEXT, hash TEXT NOT NULL, t TEXT)""",
        """CREATE TABLE deletion_records (del_id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT,
            logical INTEGER, physical INTEGER, actor TEXT, t TEXT)""",
    ]
}


def _canon_json(o) -> str:
    d = asdict(o) if hasattr(o, "__dataclass_fields__") else o
    return json.dumps(d, sort_keys=True, ensure_ascii=True, default=str)


def _hash(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()[:32]


class StaleVersionError(Exception):
    pass


class Repository(abc.ABC):
    @abc.abstractmethod
    def migrate(self): ...
    @abc.abstractmethod
    def put_episode(self, ep): ...
    @abc.abstractmethod
    def put_contract(self, c): ...
    @abc.abstractmethod
    def get_contract(self, contract_id): ...
    @abc.abstractmethod
    def update_contract(self, c, expected_version): ...
    @abc.abstractmethod
    def list_contracts(self, org_id=None, state=None): ...


class SqliteRegistry(Repository):
    def __init__(self, path=":memory:"):
        # check_same_thread=False so the registry can serve FastAPI's threadpool; writes are guarded by
        # `with self.conn` transactions.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass

    def _version(self):
        try:
            r = self.conn.execute("SELECT MAX(version) v FROM schema_migrations").fetchone()
            return r["v"] or 0
        except sqlite3.Error:
            return 0

    def migrate(self):
        cur = self._version()
        for v in range(cur + 1, SCHEMA_TARGET + 1):
            with self.conn:                       # transactional; rolls back on failure
                for stmt in _MIGRATIONS[v]:
                    self.conn.execute(stmt)
                self.conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))", (v,))
        return self._version()

    # ---- episodes ----
    def put_episode(self, ep):
        cj = _canon_json(ep)
        h = _hash(cj)
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO private_episodes(episode_id,owner_user_id,org_id,repo_id,task_id,content_hash,canonical_json,created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                (ep.episode_id, ep.owner_user_id, ep.org_id, ep.repo_id, ep.task_id, h, cj))
        return h

    # ---- contracts (immutable content; optimistic version) ----
    def put_contract(self, c):
        cj = _canon_json(c)
        h = _hash(cj)
        with self.conn:
            self.conn.execute(
                "INSERT INTO memory_contracts(contract_id,org_id,state,schema_version,version,content_hash,canonical_json,superseded_by,created_at,updated_at) "
                "VALUES (?,?,?,?,1,?,?,?,datetime('now'),datetime('now'))",
                (c.contract_id, c.scope.org_id, c.governance.state, c.schema_version, h, cj,
                 c.validity.superseded_by_contract_id or None))
            for ep in c.provenance.source_episode_ids:
                self.conn.execute("INSERT OR IGNORE INTO contract_sources(contract_id,episode_id) VALUES (?,?)",
                                  (c.contract_id, ep))
        return h

    def get_contract(self, contract_id):
        r = self.conn.execute("SELECT * FROM memory_contracts WHERE contract_id=?", (contract_id,)).fetchone()
        return dict(r) if r else None

    def update_contract(self, c, expected_version):
        """A canonical update creates a NEW content hash and bumps version; rejects stale writers."""
        cur = self.conn.execute("SELECT version FROM memory_contracts WHERE contract_id=?", (c.contract_id,)).fetchone()
        if cur is None:
            raise KeyError(c.contract_id)
        if cur["version"] != expected_version:
            raise StaleVersionError("expected %s got %s" % (expected_version, cur["version"]))
        cj = _canon_json(c)
        h = _hash(cj)
        with self.conn:
            self.conn.execute(
                "UPDATE memory_contracts SET state=?, version=version+1, content_hash=?, canonical_json=?, superseded_by=?, updated_at=datetime('now') WHERE contract_id=? AND version=?",
                (c.governance.state, h, cj, c.validity.superseded_by_contract_id or None, c.contract_id, expected_version))
        return h

    def list_contracts(self, org_id=None, state=None):
        q = "SELECT contract_id,state,version,content_hash,superseded_by FROM memory_contracts WHERE 1=1"
        p = []
        if org_id:
            q += " AND org_id=?"; p.append(org_id)
        if state:
            q += " AND state=?"; p.append(state)
        return [dict(r) for r in self.conn.execute(q, p).fetchall()]

    # ---- supersession graph acyclicity ----
    def supersession_acyclic(self) -> bool:
        edges = {}
        for r in self.conn.execute("SELECT contract_id, superseded_by FROM memory_contracts WHERE superseded_by IS NOT NULL"):
            edges.setdefault(r["contract_id"], []).append(r["superseded_by"])
        WHITE, GREY, BLACK = 0, 1, 2
        color = {}
        def dfs(n):
            color[n] = GREY
            for m in edges.get(n, []):
                if color.get(m, WHITE) == GREY:
                    return False
                if color.get(m, WHITE) == WHITE and not dfs(m):
                    return False
            color[n] = BLACK
            return True
        for n in list(edges):
            if color.get(n, WHITE) == WHITE and not dfs(n):
                return False
        return True

    def audit(self, event_type, actor, subject, detail, t="now"):
        prev = self.conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = prev["hash"] if prev else "genesis"
        body = {"type": event_type, "actor": actor, "subject": subject, "detail": detail, "prev": prev_hash}
        h = _hash(json.dumps(body, sort_keys=True, default=str))
        with self.conn:
            self.conn.execute("INSERT INTO audit_events(type,actor,subject,detail,prev_hash,hash,t) VALUES (?,?,?,?,?,?,datetime('now'))",
                              (event_type, actor, subject, json.dumps(detail, default=str), prev_hash, h))
        return h

    def audit_chain_ok(self) -> bool:
        prev = "genesis"
        for r in self.conn.execute("SELECT prev_hash, hash FROM audit_events ORDER BY seq"):
            if r["prev_hash"] != prev:
                return False
            prev = r["hash"]
        return True

    def close(self):
        self.conn.close()
