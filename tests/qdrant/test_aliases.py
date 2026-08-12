"""Durable alias routing (P2.1 §1). Aliases are the authoritative pointer — not process-local state. A
fresh adapter (and a reconnected client) sees the current alias immediately. Readiness is fail-closed."""
import os
import pytest
from conftest import run, DIM
from enterprise_memory.indexing.models import SHARED, PRIVATE, SHARED_COLLECTION, PRIVATE_COLLECTION
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex


def _new_adapter():
    ix = QdrantIndex.from_env(DIM)
    run(ix.ensure_ready())          # idempotent: creates only what's missing, never wipes
    return ix


def test_bootstrap_points_aliases_to_base(index):
    async def body():
        assert await index.resolve(PRIVATE) == PRIVATE_COLLECTION
        assert await index.resolve(SHARED) == SHARED_COLLECTION
    run(body())


def test_swap_and_rollback_single_adapter(index):
    async def body():
        new = SHARED_COLLECTION + "_v2"
        await index.create_collection(new)
        await index.swap(SHARED, new)
        assert await index.resolve(SHARED) == new
        await index.swap(SHARED, SHARED_COLLECTION)          # rollback
        assert await index.resolve(SHARED) == SHARED_COLLECTION
    run(body())


def test_swap_to_missing_collection_is_blocked(index):
    async def body():
        with pytest.raises(Exception):
            await index.swap(SHARED, "enterprise_shared_does_not_exist")
        assert await index.resolve(SHARED) == SHARED_COLLECTION   # unchanged
    run(body())


def test_absent_alias_fails_readiness_then_heals(index):
    async def body():
        from qdrant_client import models as qm
        # delete the shared alias out from under the adapter
        await __import__("asyncio").to_thread(
            index._c.update_collection_aliases,
            change_aliases_operations=[qm.DeleteAliasOperation(
                delete_alias=qm.DeleteAlias(alias_name=index.alias_for(SHARED)))])
        with pytest.raises(RuntimeError):
            await index.resolve(SHARED)                     # fail-closed: no singular alias
        await index.ensure_ready()                          # self-heals back to base
        assert await index.resolve(SHARED) == SHARED_COLLECTION
    run(body())


def test_ambiguous_alias_guard():
    # the len!=1 guard is defensive (Qdrant keeps alias names unique); unit-test it directly
    ix = QdrantIndex(client=None, dim=DIM)
    ix._alias_targets = lambda: {ix.alias_for(SHARED): ["a", "b"]}
    with pytest.raises(RuntimeError):
        ix._resolve(SHARED)


@pytest.mark.skipif(not os.environ.get("QDRANT_URL"), reason="alias persistence requires a real Qdrant server")
def test_alias_persists_across_adapter_instances(index):
    async def body():
        new = SHARED_COLLECTION + "_v9"
        await index.create_collection(new)
        await index.swap(SHARED, new)
        # a brand-new adapter (fresh client) must observe the swap durably
        other = _new_adapter()
        assert await other.resolve(SHARED) == new
        # rollback via the other adapter; a third adapter observes the rollback
        await other.swap(SHARED, SHARED_COLLECTION)
        third = _new_adapter()
        assert await third.resolve(SHARED) == SHARED_COLLECTION
        await other.close(); await third.close()
    run(body())
