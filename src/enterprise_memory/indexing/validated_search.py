"""Validated search (P2 / P2.1). The vector index is a CANDIDATE GENERATOR only. Every candidate is
validated against PostgreSQL before it can be returned, and the returned content is the canonical row
loaded from PostgreSQL — never the index payload or the embedded text. Each dropped candidate carries an
explicit RejectionReason so the decision is auditable.

Authenticated identity (user_id) is REQUIRED for both private and shared searches — there is no
user_id=None permission bypass.

Per-candidate gates (in order): scope, index schema version, object kind, payload org, private owner,
PostgreSQL existence, canonical org, canonical owner, repository read permission, payload/canonical
repository equality, version equality, contract-id equality, content-hash equality, current version,
promoted/servable state, valid_from, valid_until, not superseded, path scope, retrieval-text hash."""
from __future__ import annotations
import fnmatch
from datetime import datetime, timezone
from .models import PRIVATE, SHARED, ObjectType, INDEX_SCHEMA_VERSION, RejectionReason as RR, \
    SearchResult, ValidatedHit, sha256_hex
from . import canonical_loaders as cl
from ..contracts import codec

_PRIVATE_UNSERVABLE = ("deleted", "quarantined", "tombstoned")


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _path_decision(requested_path, path_scope):
    """None = ok; else the RejectionReason. A path restriction requires a matching requested path
    (fail-closed): missing path -> PATH_REQUIRED, non-matching -> PATH_SCOPE_MISMATCH."""
    if not path_scope:
        return None
    if not requested_path:
        return RR.PATH_REQUIRED
    return None if any(fnmatch.fnmatch(requested_path, g) for g in path_scope) else RR.PATH_SCOPE_MISMATCH


async def _validate(engine, embedder, scope, org_id, user_id, requested_path, p, meta=None):
    """Return (hit_or_None, reason_or_None) for one candidate payload `p`. `meta` (if given) is filled with
    the authoritative canonical owner/hash discovered during the PostgreSQL reload, so a rejected cross-user
    candidate is still auditable (index_owner vs canonical_owner)."""
    if meta is None:
        meta = {}
    # 1 scope
    if p.get("scope") != scope:
        return None, RR.SCOPE_MISMATCH
    # 2 index schema version
    if int(p.get("index_schema_version", -1)) != INDEX_SCHEMA_VERSION:
        return None, RR.SCHEMA_VERSION_UNKNOWN
    # 3 object kind
    want_kind = ObjectType.CONTRACT_VERSION.value if scope == SHARED else ObjectType.PRIVATE_EPISODE.value
    if p.get("object_kind") != want_kind:
        return None, RR.WRONG_OBJECT_KIND
    # 4 payload org
    if str(p.get("org_id")) != str(org_id):
        return None, RR.WRONG_ORG
    # 5 payload owner (private)
    if scope == PRIVATE and str(p.get("owner_user_id")) != str(user_id):
        return None, RR.NOT_OWNER

    version_id = p.get("canonical_version_id")

    # 6 authoritative load
    if scope == PRIVATE:
        row = await cl.load_private_episode(engine, org_id, user_id, version_id)
    else:
        row = await cl.load_contract_version(engine, org_id, version_id)
    if row is None:
        return None, RR.NOT_IN_POSTGRES
    # authoritative owner/hash from PostgreSQL — recorded for auditing even if a later gate rejects
    meta["canonical_owner"] = row.get("owner_user_id")
    meta["canonical_repository"] = row.get("repository_id")
    meta["content_hash"] = row.get("content_hash")
    # 7 canonical org
    if str(row["org_id"]) != str(org_id):
        return None, RR.WRONG_ORG
    # 8 canonical owner (private)
    if scope == PRIVATE and str(row["owner_user_id"]) != str(user_id):
        return None, RR.NOT_OWNER
    # 10 repository read permission — re-checked for BOTH scopes (owner status alone is insufficient; a
    # revoked repo permission must reject a private episode the user once created)
    if not await cl.can_read_repo(engine, org_id, user_id, row.get("repository_id")):
        return None, RR.NO_READ_PERMISSION
    # 11 payload/canonical repository equality
    if str(p.get("repository_id")) != str(row.get("repository_id")):
        return None, RR.WRONG_REPOSITORY
    # 12 version equality
    want_version = int(row["version_number"]) if scope == SHARED else 1
    if int(p.get("canonical_version_number", -1)) != want_version:
        return None, RR.VERSION_MISMATCH
    # 13 contract-id equality (shared)
    if scope == SHARED and str(p.get("contract_id")) != str(row.get("contract_id")):
        return None, RR.CONTRACT_MISMATCH
    # 14 hash equality
    if str(p.get("canonical_content_hash")) != str(row["content_hash"]):
        return None, RR.HASH_MISMATCH
    # 15/16 current + promoted/servable state
    if scope == SHARED:
        if not row.get("is_current"):
            return None, RR.NOT_CURRENT_VERSION
        if row.get("governance_state") != "promoted":
            return None, RR.DEPRECATED
        # 17 valid_from
        vf = _aware(row.get("valid_from"))
        if vf is not None and vf > _now():
            return None, RR.NOT_VALID_YET
        # 18 valid_until
        vu = _aware(row.get("valid_until"))
        if vu is not None and vu <= _now():
            return None, RR.EXPIRED
        # 19 not superseded
        if row.get("superseded_by"):
            return None, RR.SUPERSEDED
    else:
        if (row.get("state") or "") in _PRIVATE_UNSERVABLE:
            return None, RR.DEPRECATED
    # 20 path scope (a restriction requires a matching requested path — fail-closed)
    pd = _path_decision(requested_path, row.get("path_scope"))
    if pd is not None:
        return None, pd
    # 21 retrieval-text hash (shared: safe codec projection; private: compact canonical)
    expected_text = codec.retrieval_text(row["canonical"]) if scope == SHARED else cl.embed_text(row["canonical"])
    if str(p.get("retrieval_text_hash")) != sha256_hex(expected_text):
        return None, RR.RETRIEVAL_HASH_MISMATCH

    hit = ValidatedHit(
        object_kind=row["object_type"], canonical_id=str(row.get("contract_id") or row["object_id"]),
        canonical_version_id=row["object_id"], org_id=row["org_id"], content_hash=row["content_hash"],
        score=0.0, canonical=row["canonical"], version_number=(row.get("version_number") or 1),
        contract_id=row.get("contract_id"), owner_user_id=row.get("owner_user_id"),
        repository_id=row.get("repository_id"))
    return hit, None


async def validated_search(engine, index, embedder, scope, org_id, query, user_id, limit=10,
                           requested_path=None, overfetch=4):
    if scope not in (PRIVATE, SHARED):
        raise ValueError("unknown scope %r" % (scope,))
    if user_id is None:
        raise ValueError("validated_search requires an authenticated user_id (no bypass)")

    result = SearchResult()
    vec = embedder.embed([query])[0]
    owner_filter = str(user_id) if scope == PRIVATE else None
    candidates = await index.search(scope, vec, org_id, owner_user_id=owner_filter,
                                    limit=max(limit * overfetch, limit))
    for cand in candidates:
        if len(result.hits) >= limit:
            break
        meta = {"pid": cand.pid, "scope": scope, "score": cand.score,
                "index_owner": cand.payload.get("owner_user_id"), "canonical_owner": None,
                "canonical_id": cand.payload.get("canonical_id"),
                "canonical_version_id": cand.payload.get("canonical_version_id"),
                "content_hash": cand.payload.get("canonical_content_hash")}
        hit, reason = await _validate(engine, embedder, scope, org_id, user_id, requested_path,
                                      cand.payload, meta)
        # audit every candidate we validated (accepted or rejected). A rejected cross-user candidate keeps
        # its authoritative canonical_owner from the reload — the owner is never inferred from query context.
        meta["accepted"] = reason is None
        meta["rejection_reason"] = (reason.value if reason is not None else None)
        result.audit.append(meta)
        if reason is not None:
            result.reject(cand.pid, reason)
        else:
            result.hits.append(ValidatedHit(
                object_kind=hit.object_kind, canonical_id=hit.canonical_id,
                canonical_version_id=hit.canonical_version_id, org_id=hit.org_id,
                content_hash=hit.content_hash, score=cand.score, canonical=hit.canonical,
                version_number=hit.version_number, contract_id=hit.contract_id,
                owner_user_id=hit.owner_user_id, repository_id=hit.repository_id))
    return result
