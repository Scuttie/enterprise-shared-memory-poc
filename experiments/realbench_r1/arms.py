"""REALBENCH-R1 arms (§9). Only the memory policy differs; tasks/backend/grader/service path are identical.
For MBPP the retrieval margin between diverse sources is ~0.02, so abstention uses an ABSOLUTE similarity
threshold (tau_abs) selected on the retrieval-dev split (median top-1 sim). R4 disables the abstention
threshold (always inject the CURRENT RETRIEVER's top-1 source). NOTE (REALBENCH-R2 §1.1 correction): R4 is
NOT an oracle and NOT a theoretical ceiling — the retriever's top-1 may be irrelevant; R4 only measures the
effect of always injecting the nearest source under the frozen neutral projection. A true relevance oracle
(evaluator-labelled) is a separate diagnostic arm (REALBENCH-R1.1 D8 / BigCode M-arms), not R4."""
from __future__ import annotations
from dataclasses import dataclass

TAU_ABS = 0.43          # frozen: dev median top-1 similarity (see artifacts/realbench_r1/retrieval_config.json)
TAU_MARGIN = 0.0        # margins between diverse MBPP sources are negligible -> absolute-threshold only
INDEX_DIM = 256


@dataclass(frozen=True)
class Arm:
    code: str
    name: str
    retrieval_policy: dict
    memory_form: str        # none | shared_ungoverned | shared_governed | private


R0 = Arm("R0", "NO_MEMORY", {"scopes": [], "max_injected": 0}, "none")
R2 = Arm("R2", "SHARED_UNGOVERNED",
         {"scopes": ["shared"], "max_injected": 1, "search_limit": 1,
          "abstain": {"tau_abs": TAU_ABS, "tau_margin": TAU_MARGIN}}, "shared_ungoverned")
R3 = Arm("R3", "SHARED_GOVERNED",
         {"scopes": ["shared"], "max_injected": 1, "search_limit": 1,
          "abstain": {"tau_abs": TAU_ABS, "tau_margin": TAU_MARGIN}}, "shared_governed")
R4 = Arm("R4", "ALWAYS_INJECT_TOP1",   # renamed from ORACLE_GOVERNED (§1.1); NOT an oracle — see docstring
         {"scopes": ["shared"], "max_injected": 1, "search_limit": 1,
          "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}}, "shared_governed")   # threshold off: always inject retriever top-1
R1 = Arm("R1", "PRIVATE_ONLY", {"scopes": ["private"], "max_injected": 1, "search_limit": 1}, "private")

PRIMARY = [R0, R2, R3, R4]
SECONDARY = [R1]
ALL = PRIMARY + SECONDARY
BY_CODE = {a.code: a for a in ALL}
