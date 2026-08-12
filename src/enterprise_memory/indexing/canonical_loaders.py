"""PostgreSQL canonical loaders (P2). PostgreSQL is authoritative; these functions are the ONLY source of
content a caller receives. They run under RLS through tenant_tx (org + user context), so a loader that
returns a row has already passed tenant isolation — the private_episodes RESTRICTIVE owner policy means a
private episode is only visible when app.user_id is its owner. `embed_text` is a deterministic projection
of canonical_json used to build/refresh the vector index; it is not authoritative and is never returned to
a coding model."""
from __future__ import annotations
import json
from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx


def embed_text(canonical) -> str:
    """Stable projection of a canonical object for embedding (sorted keys, compact)."""
    if isinstance(canonical, str):
        return canonical
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_obj(v):
    return v if not isinstance(v, str) else json.loads(v)


async def load_private_episode(engine, org_id, user_id, episode_id):
    """Owner-scoped load. Returns None if it does not exist for this org OR is not owned by user_id."""
    async with tenant_tx(engine, org_id, user_id) as c:
        r = (await c.execute(text(
            "SELECT id, org_id, owner_user_id, repository_id, content_hash, canonical_json, state"
            " FROM private_episodes WHERE id=:i"), {"i": episode_id})).first()
    if r is None:
        return None
    return {"object_type": "private_episode", "object_id": str(r[0]), "org_id": str(r[1]),
            "owner_user_id": str(r[2]), "repository_id": (str(r[3]) if r[3] else None),
            "content_hash": r[4], "canonical": _as_obj(r[5]), "state": r[6]}


async def load_contract_version(engine, org_id, version_id):
    """Load a contract version and whether it is the CURRENT promoted version of its contract."""
    async with tenant_tx(engine, org_id) as c:
        r = (await c.execute(text(
            "SELECT v.id, v.org_id, v.contract_id, v.version_number, v.content_hash, v.canonical_json,"
            " v.governance_state, mc.repository_id, (mc.current_version_id = v.id) AS is_current"
            " FROM memory_contract_versions v JOIN memory_contracts mc ON mc.id = v.contract_id"
            " WHERE v.id=:i"), {"i": version_id})).first()
    if r is None:
        return None
    return {"object_type": "contract_version", "object_id": str(r[0]), "org_id": str(r[1]),
            "contract_id": str(r[2]), "version_number": int(r[3]), "content_hash": r[4],
            "canonical": _as_obj(r[5]), "governance_state": r[6],
            "repository_id": (str(r[7]) if r[7] else None), "is_current": bool(r[8])}


async def can_read_repo(engine, org_id, user_id, repository_id) -> bool:
    """Org-global objects (repository_id NULL) are readable; repo-scoped objects require an explicit
    can_read permission for the user directly or via a team membership."""
    if repository_id is None:
        return True
    async with tenant_tx(engine, org_id, user_id) as c:
        n = (await c.execute(text(
            "SELECT count(*) FROM repository_permissions p WHERE p.repository_id=:r AND p.can_read"
            " AND ((p.subject_type='user' AND p.subject_id=:u)"
            "   OR (p.subject_type='team' AND p.subject_id IN"
            "        (SELECT tm.team_id FROM team_memberships tm WHERE tm.user_id=:u)))"),
            {"r": repository_id, "u": user_id})).scalar()
    return int(n or 0) > 0


async def enumerate_private(engine, org_id, user_id):
    async with tenant_tx(engine, org_id, user_id) as c:
        rows = (await c.execute(text(
            "SELECT id, owner_user_id, repository_id, content_hash, canonical_json"
            " FROM private_episodes ORDER BY created_at"))).fetchall()
    return [{"object_id": str(x[0]), "owner_user_id": str(x[1]),
             "repository_id": (str(x[2]) if x[2] else None), "content_hash": x[3],
             "canonical": _as_obj(x[4])} for x in rows]


async def enumerate_current_contract_versions(engine, org_id):
    """Every contract's current promoted version — the canonical shared set to index."""
    async with tenant_tx(engine, org_id) as c:
        rows = (await c.execute(text(
            "SELECT v.id, v.contract_id, v.version_number, v.content_hash, v.canonical_json, mc.repository_id"
            " FROM memory_contracts mc JOIN memory_contract_versions v ON v.id = mc.current_version_id"
            " WHERE v.governance_state = 'promoted' ORDER BY v.created_at"))).fetchall()
    return [{"object_id": str(x[0]), "contract_id": str(x[1]), "version_number": int(x[2]),
             "content_hash": x[3], "canonical": _as_obj(x[4]),
             "repository_id": (str(x[5]) if x[5] else None)} for x in rows]
