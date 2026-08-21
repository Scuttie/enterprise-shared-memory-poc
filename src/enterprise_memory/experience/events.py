"""P6/R19 §5 — outbox event types for the experience layer (emitted onto the existing outbox_events table).

These are the durable side-effects the index/governance workers consume. No new table: the existing outbox
carries a `type` string plus a JSON payload.
"""
EXPERIENCE_INDEX = "EXPERIENCE_INDEX"                 # (re)project a promoted/probation card into Qdrant/Mem0
EXPERIENCE_DEPRECATE = "EXPERIENCE_DEPRECATE"         # version invalidated -> remove from index
EXPERIENCE_DELETE = "EXPERIENCE_DELETE"               # hard delete -> purge from index
EXPERIENCE_SUPERSEDE = "EXPERIENCE_SUPERSEDE"         # new version supersedes an older one
OUTCOME_CREDIT_RECOMPUTE = "OUTCOME_CREDIT_RECOMPUTE" # recompute usage aggregates after a graded target

ALL = (EXPERIENCE_INDEX, EXPERIENCE_DEPRECATE, EXPERIENCE_DELETE, EXPERIENCE_SUPERSEDE, OUTCOME_CREDIT_RECOMPUTE)
