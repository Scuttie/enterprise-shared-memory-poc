"""REALBENCH-R3 §6 — source-bank record building. Two explicitly-labelled banks:

  USER_SUCCESS_BANK (deployable): for each SOURCE task the source USER actually solved (verified by the official
    evaluator), the source user's OWN verified solution is abstracted into the canonical memory object. This is
    real user experience; only successful source outcomes enter it.
  GOLD_VERIFIED_BANK (diagnostic upper bound): the official reference solution's canonical facts. Used only as a
    verified-fact oracle / relevance anchor; NEVER presented as deployable user memory.

The canonical object is derived once (structural AST + one temp-0 Solar abstraction), then persisted; renderers
project it deterministically (§8). Raw source solutions are kept only under `evidence`, never in the fact
surface, and target values/names/tests are absent by construction (assert_no_target_leakage).
"""
from __future__ import annotations
import dataclasses

from enterprise_memory.providers.base import ModelRequest
from experiments.actionable_memory_r3 import canonical_builder as CB


async def abstract_canonical(provider, task: dict, solution_code: str, source_user: str, evaluator_hash: str,
                             *, org_id: str, logical_request_id: str):
    """One memory-formation call: abstract the verified source into semantic fields, then assemble the canonical
    object. On any failure the source still yields a structural-only canonical object."""
    semantic = {}
    if provider is not None:
        md = task.get("metadata", {})
        prompt = CB.build_prompt(md.get("library", ""), task.get("prompt", ""), solution_code)
        try:
            req = ModelRequest(messages=[{"role": "user", "content": prompt}], max_output_tokens=900)
            resp, _ = await provider.generate(req, logical_request_id=logical_request_id, org_id=org_id)
            semantic = CB.parse_abstraction(resp.text)
        except Exception:
            semantic = {}
    return CB.assemble(task, solution_code, source_user, evaluator_hash, semantic)


def user_success_record(cam) -> dict:
    d = cam.fact_fields()
    d["canonical_hash"] = cam.canonical_hash()
    d["executable_properties"] = list(cam.evidence.get("executable_properties", []))
    d["owner_user"] = cam.source_user_id
    return d


def gold_record(cam) -> dict:
    d = cam.fact_fields()
    d["canonical_hash"] = cam.canonical_hash()
    d["bank"] = "GOLD_VERIFIED"
    return d


def coverage_by_library(records: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in records:
        for lib in r.get("libraries", []):
            out[lib] = out.get(lib, 0) + 1
    return out
