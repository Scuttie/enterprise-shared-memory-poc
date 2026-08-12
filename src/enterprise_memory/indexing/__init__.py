"""P2 Postgres-authoritative indexing. Qdrant/Mem0 are replaceable CANDIDATE indexes: their payloads and
text are never authoritative and are never injected into a coding model. Validated search re-loads every
result from PostgreSQL and rejects stale/leaked candidates with an explicit reason. Vector-store imports
are lazy so the base package imports without qdrant-client or mem0 installed."""
from .models import (PRIVATE, SHARED, PRIVATE_COLLECTION, SHARED_COLLECTION, PRIVATE_ALIAS, SHARED_ALIAS,  # noqa: F401
                     ObjectType, RejectionReason, IndexRecord, Candidate, ValidatedHit, SearchResult, point_id)
from .embeddings import Embedder, DeterministicTestEmbedder  # noqa: F401
from .validated_search import validated_search  # noqa: F401
from . import canonical_loaders, drift, reindex, index_worker  # noqa: F401
