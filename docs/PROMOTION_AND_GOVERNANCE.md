# Promotion & governance

Private episode -> candidate -> **security scan** (secrets/PII/high-entropy/source-excerpt) -> **replay
evidence** (executable tests) -> **promotion state machine** (PROMOTED / QUARANTINED / PRIVATE_ONLY) ->
governed shared contract. No force-promote. Conflicts resolve via merge/quarantine/supersede/retain.
Every step appends to the hash-chained audit ledger. See `enterprise_memory/promotion/` and
`enterprise_memory/audit/`.
