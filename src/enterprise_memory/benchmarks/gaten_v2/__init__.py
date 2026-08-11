"""EnterpriseGateNBench-v2 — a controlled *mechanism* instrument (not a claim about unrestricted
repository-level SWE). Each family is a bounded executable contract-application task with two
counterfactual contract worlds (A/B) over a byte-identical target; only the stored contract differs, and
the world-correct behavior differs. Splits: unit / calibration / confirmation / canary (disjoint)."""
from .families import families as build_families, split_manifest, DOMAINS, SPLITS  # noqa: F401
from .harness import (  # noqa: F401
    apply_unified_diff, PatchError, run_n2, grade_n1, n1_prompt, n2_prompt, starter_file,
    contract_text, gold_patch_text, default_patch_text, hidden_test_text,
)
