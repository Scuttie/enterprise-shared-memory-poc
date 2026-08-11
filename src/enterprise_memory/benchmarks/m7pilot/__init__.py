"""GovernedExecutionViewPilot-v1 — a within-contract RENDERER intervention. The canonical backend
contract and task semantics are fixed while only the reader-facing serialization changes. Fresh,
domain-scoped (internal_api + cache); NOT confirmation, NOT a rerun of E4, NOT a general-efficacy claim."""
from .bench import (  # noqa: F401
    families, safety_families, canonical_contract, DOMAINS, WORLDS, manifest, BOUNDARY, behavior_class,
)
from .renderers import (  # noqa: F401
    render, RENDERERS, semantic_gate, renderer_manifest, RENDER_META,
)
