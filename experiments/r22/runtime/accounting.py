"""R22 §2 — usage/cost ledger with a hard-cap stop (no model calls here)."""
from __future__ import annotations

PRICES = {  # per Mtoken USD (mirror scripts/r22_recompute_paid_costs.py)
    "deepseek-chat": {"in": 0.27, "out": 1.10},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "fake-reader": {"in": 0.0, "out": 0.0},
}


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, model: str, hard_cap_usd: float):
        self.model = model
        self.hard_cap = hard_cap_usd
        self.in_tok = 0
        self.out_tok = 0
        self.calls = 0

    def price(self):
        return PRICES.get(self.model, {"in": 0.0, "out": 0.0})

    def cost(self):
        p = self.price()
        return (self.in_tok / 1e6) * p["in"] + (self.out_tok / 1e6) * p["out"]

    def add(self, prompt_tokens: int, completion_tokens: int):
        self.in_tok += int(prompt_tokens)
        self.out_tok += int(completion_tokens)
        self.calls += 1
        if self.cost() > self.hard_cap:
            raise BudgetExceeded("cumulative $%.4f exceeds hard cap $%.4f" % (self.cost(), self.hard_cap))
        return self.cost()

    def snapshot(self):
        return {"model": self.model, "calls": self.calls, "input_tokens": self.in_tok,
                "output_tokens": self.out_tok, "cost_usd": round(self.cost(), 6), "hard_cap_usd": self.hard_cap}
