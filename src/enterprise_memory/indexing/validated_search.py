"""Validated search (P2). The vector index is a CANDIDATE GENERATOR only. Every candidate is validated
against PostgreSQL before it can be returned, and the returned content is the canonical row loaded from
PostgreSQL — never the index payload or the embedded text. Each dropped candidate carries an explicit
RejectionReason so the decision is auditable.

The pipeline (13 steps):
  1. resolve scope -> physical collection (private requires user_id)
  2. embed the query with the SAME embedder used to index
  3. vector search in the scope's physical collection with a store-side org (+owner) filter, over-fetching
  4. payload scope must equal the requested scope            -> SCOPE_MISMATCH
  5. payload.org_id must equal the caller org                -> WRONG_ORG
  6. private: payload.owner_user_id must equal the caller    -> NOT_OWNER
  7. load the canonical row from PostgreSQL (RLS-scoped)     -> NOT_IN_POSTGRES if absent
  8. loaded org must equal the caller org                    -> WRONG_ORG
  9. private: loaded owner must equal the caller             -> NOT_OWNER
 10. payload.content_hash must equal the canonical hash      -> HASH_MISMATCH (stale index)
 11. shared: version must be the contract's current version  -> NOT_CURRENT_VERSION
 12. shared: governance_state must be promoted (not deleted) -> DEPRECATED
 13. repository read permission for the caller               -> NO_READ_PERMISSION
Survivors become ValidatedHit(canonical=...) up to `limit`."""
from __future__ import annotations
from .models import (PRIVATE, SHARED, ObjectType, RejectionReason as RR,
                     SearchResult, ValidatedHit)
from . import canonical_loaders as cl


async def validated_search(engine, index, embedder, scope, org_id, query, limit=10, user_id=None,
                           overfetch=4):
    result = SearchResult()

    # 1. scope resolution
    if scope not in (PRIVATE, SHARED):
        raise ValueError("unknown scope %r" % (scope,))
    if scope == PRIVATE and user_id is None:
        raise ValueError("private search requires user_id")

    # 2. embed with the indexing embedder
    vec = embedder.embed([query])[0]

    # 3. candidate generation with store-side filtering (defence in depth)
    owner_filter = str(user_id) if scope == PRIVATE else None
    candidates = await index.search(scope, vec, org_id, owner_user_id=owner_filter,
                                    limit=max(limit * overfetch, limit))

    for cand in candidates:
        if len(result.hits) >= limit:
            break
        p = cand.payload

        # 4. scope integrity
        if p.get("scope") != scope:
            result.reject(cand.pid, RR.SCOPE_MISMATCH); continue
        # 5. payload org
        if str(p.get("org_id")) != str(org_id):
            result.reject(cand.pid, RR.WRONG_ORG); continue
        # 6. payload owner (private)
        if scope == PRIVATE and str(p.get("owner_user_id")) != str(user_id):
            result.reject(cand.pid, RR.NOT_OWNER); continue

        object_id = p.get("object_id")

        # 7. authoritative load from PostgreSQL
        if scope == PRIVATE:
            row = await cl.load_private_episode(engine, org_id, user_id, object_id)
        else:
            row = await cl.load_contract_version(engine, org_id, object_id)
        if row is None:
            result.reject(cand.pid, RR.NOT_IN_POSTGRES); continue

        # 8. loaded org
        if str(row["org_id"]) != str(org_id):
            result.reject(cand.pid, RR.WRONG_ORG); continue
        # 9. loaded owner (private)
        if scope == PRIVATE and str(row["owner_user_id"]) != str(user_id):
            result.reject(cand.pid, RR.NOT_OWNER); continue

        # 10. staleness: index hash vs canonical hash
        if str(p.get("content_hash")) != str(row["content_hash"]):
            result.reject(cand.pid, RR.HASH_MISMATCH); continue

        # 11 & 12. shared governance
        if scope == SHARED:
            if not row.get("is_current"):
                result.reject(cand.pid, RR.NOT_CURRENT_VERSION); continue
            if row.get("governance_state") != "promoted":
                result.reject(cand.pid, RR.DEPRECATED); continue

        # 13. repository read permission
        repo = row.get("repository_id")
        reader = user_id if scope == PRIVATE else user_id
        if scope == SHARED and reader is not None:
            if not await cl.can_read_repo(engine, org_id, reader, repo):
                result.reject(cand.pid, RR.NO_READ_PERMISSION); continue

        result.hits.append(ValidatedHit(
            object_type=row["object_type"], object_id=row["object_id"], org_id=row["org_id"],
            content_hash=row["content_hash"], score=cand.score, canonical=row["canonical"],
            version_number=row.get("version_number", 1), contract_id=row.get("contract_id")))

    return result
