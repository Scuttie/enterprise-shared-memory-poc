"""Shared token primitives for P5.2 retrieval-relevance engineering (§3/§5). The deterministic bag-of-tokens
embedder ranks by token overlap, so the query carries the domain vocabulary + a repeated technique-family tag,
and the relevant memory carries the same; same-domain near-misses share the domain but a different tag, and
cross-domain decoys share little. Imported by both retrieval.py and memory_bank.py (no cycle)."""
from __future__ import annotations
import hashlib

DIM = 128
QUERY_TAG_REPEAT = 14
MEM_TAG_REPEAT = 18
DOMAINS = ("internal_api", "cache", "config", "schema")

_DOMAIN_VOCAB = {
    "internal_api": "retry backoff attempt request timeout idempotency",
    "cache": "cache ttl tier eviction lookup invalidation",
    "config": "config precedence branch environment override profile",
    "schema": "schema field normalization mapping version compatibility",
}


def tag(split, domain, family_idx):
    return "technique_%s_%s_%d" % (domain, hashlib.sha256(split.encode()).hexdigest()[:4], family_idx)


def mem_text(domain, the_tag, extra="convention applies_when edge case branch"):
    return "%s %s %s" % (_DOMAIN_VOCAB[domain], " ".join([the_tag] * MEM_TAG_REPEAT), extra)


def query_text(domain, the_tag):
    return "%s %s task edit function implement" % (_DOMAIN_VOCAB[domain], " ".join([the_tag] * QUERY_TAG_REPEAT))
