"""P5.1 static multi-user coding experiment harness (frozen). Server-assigned arms, deterministic multi-user
assignment, memory-bank rendering, and a frozen plan with stable hashes. Execution runs through the real
service API -> durable job -> separate worker path (never a direct benchmark runner)."""
from . import arms, assignment, memory_bank, plan

__all__ = ["arms", "assignment", "memory_bank", "plan"]
