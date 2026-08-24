"""R22 §4/§11 — dynamic stage memory tools: search (metadata only) → browse (gated execution view) → report.

Budgets (frozen): ≤2 searches per stage, ≤2 browses total, ≤1 execution memory at a time, ≤440 execution tokens
total. Search never returns execution content; only browse (after a candidate id) reveals it. Every call is audited.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ..experience.stage_schema import Stage
from ..retrieval.stage_query import StageQuery
from ..retrieval.stage_pipeline import retrieve_stage
from .stage_state import StageState

MAX_SEARCH_PER_STAGE = 2
MAX_BROWSE_TOTAL = 2
MAX_EXEC_TOKENS_TOTAL = 440


class BudgetError(Exception):
    pass


class StageMemoryTools:
    def __init__(self, state: StageState, index_views: List[dict], ctx: dict,
                 exec_view_of: Callable[[str], dict], embed_score: Optional[Callable] = None,
                 rank_l: Optional[Callable] = None):
        self.state = state
        self.index_views = index_views
        self.ctx = ctx
        self.exec_view_of = exec_view_of        # memory_id -> ExecutionView dict (already token-capped)
        self.embed_score = embed_score
        self.rank_l = rank_l
        self._exec_tokens = 0

    def memory_search_stage(self, query: StageQuery) -> Dict:
        st = query.stage
        if not self.state.can_search(st):
            self.state.audit.append({"event": "search_refused", "stage": st.value, "reason": "stage_precondition"})
            return {"decision": "ABSTAIN", "reason": "stage_precondition", "candidates": []}
        used = self.state.search_calls.get(st.value, 0)
        if used >= MAX_SEARCH_PER_STAGE:
            raise BudgetError("search budget exhausted for stage %s" % st.value)
        self.state.search_calls[st.value] = used + 1
        res = retrieve_stage(query, self.index_views, self.ctx,
                             embed_score=self.embed_score, rank_l=self.rank_l)
        # metadata only in the search result (never the execution view)
        cand = res.get("candidate")
        self.state.audit.append({"event": "search", "stage": st.value, "decision": res["decision"],
                                 "gated": len(res["gated"])})
        return {"decision": res["decision"],
                "candidates": [] if cand is None else [{"memory_id": cand["memory_id"], "stage": cand["stage"],
                                                        "rank_d_score": cand.get("rank_d_score")}],
                "reason": res["reason"]}

    def memory_browse_stage(self, candidate_id: str) -> Dict:
        if self.state.browse_calls >= MAX_BROWSE_TOTAL:
            raise BudgetError("browse budget exhausted")
        view = self.exec_view_of(candidate_id)
        tok = int(view.get("approx_tokens", 0))
        if self._exec_tokens + tok > MAX_EXEC_TOKENS_TOTAL:
            self.state.audit.append({"event": "browse_refused", "reason": "token_budget", "candidate": candidate_id})
            return {"granted": False, "reason": "token_budget"}
        self.state.browse_calls += 1
        self._exec_tokens += tok
        self.state.audit.append({"event": "browse", "candidate": candidate_id, "tokens": tok})
        return {"granted": True, "execution_view": view}

    def memory_report_stage_outcome(self, memory_id: str, outcome: str, adoption: str) -> Dict:
        self.state.audit.append({"event": "report_outcome", "memory_id": memory_id,
                                 "outcome": outcome, "adoption": adoption})
        return {"recorded": True}
