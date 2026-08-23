"""REALBENCH-R3 §9 — matched DECODERS. Each representation bundle ships with a matched reader procedure (the
"how to use this memory" instruction). The bundle (representation + matched decoder) is the experimental unit.
These texts are FROZEN and hashed; the §13 ablation swaps decoders to separate representation value from decoder
value. A GENERIC decoder is provided for that ablation (same for every representation).
"""
from __future__ import annotations
import hashlib

DECODERS = {
    "B0": ("How to use this lesson: (1) decide whether the technique applies to THIS task; (2) adapt it to the "
           "target's variables and types; (3) verify the result against the task before finalising."),
    "B1": ("How to use this API card: (1) confirm the listed APIs are available and imported; (2) check every "
           "precondition holds; (3) implement the ordered API operations; (4) avoid the listed misuse; "
           "(5) verify the output type/shape."),
    "B2": ("How to use this condition-action table: (1) evaluate each target condition; (2) select exactly ONE "
           "matching row; (3) execute that row's action; (4) if no row matches, REJECT the memory and solve "
           "directly; (5) verify the edge-case action."),
    "B3": ("How to use this procedure: (1) map the placeholders to the target variables; (2) preserve the "
           "operation order and control flow; (3) adapt only names and target-specific constants; (4) verify "
           "the listed edge cases."),
    "B4": ("How to use this AST-edit schema: (1) locate the matching target AST nodes; (2) apply ONLY the "
           "declared edit operations; (3) preserve the signature/interface; (4) reject any unmatched "
           "operation; (5) verify the resulting code and tests."),
    "B5": ("How to use this diff template: (1) bind the placeholders to the target symbols; (2) instantiate the "
           "template; (3) do NOT copy any source identifier or constant; (4) validate the final edit against "
           "the task."),
    "B6": ("How to use this property spec: (1) turn each property into an implementation requirement; "
           "(2) implement code satisfying ALL properties; (3) check for conflicts with the task; (4) reject the "
           "memory if a property conflicts with the instruction."),
    "B7": ("How to use this positive/negative contrast: (1) identify which condition the target satisfies; "
           "(2) implement the POSITIVE pattern; (3) explicitly avoid the NEGATIVE pattern; (4) verify the "
           "discriminating edge case."),
    "B8": ("How to use this hybrid memory: (1) check applicability; (2) map the API/AST operations to the "
           "target; (3) implement; (4) check the properties; (5) compare against the negative counterexample "
           "and verify."),
    "B9": ("How to use this worked trace: treat it as ONE example, not a template; do NOT copy its identifiers "
           "or constants; re-derive the method for the target and verify the transfer."),
}
GENERIC_DECODER = ("How to use this memory: read it as advisory prior knowledge, decide if it applies, adapt it "
                   "to the target, and verify the result before finalising.")


def decoder_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def manifest() -> dict:
    m = {k: {"text": v, "hash": decoder_hash(v)} for k, v in DECODERS.items()}
    m["GENERIC"] = {"text": GENERIC_DECODER, "hash": decoder_hash(GENERIC_DECODER)}
    return m
