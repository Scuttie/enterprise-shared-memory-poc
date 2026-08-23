"""REALBENCH-R3 §3 — OFFLINE actionability forensics on persisted R1/R2 artifacts. NO new model calls.

Reads the frozen R2 main raw job records (applied_patch/arm/tid/assigned_source/injected/exec1/pass1) and the
R2 source bank AST signatures, and classifies the *remaining gap* between injected relevant source memory and
correct target code, using the evidence-based patch_forensics classifier. Purpose (§3): DEFINE candidate
representations for R3. It explicitly does NOT select a winning representation from old benchmark accuracy.

Offline-recoverable evidence: generated/applied target code, source operation/API/import/control-flow tags,
injection truth, exec/grader outcome. NOT persisted by R2 (so the corresponding gap classes are reported as
'requires-online-evidence', honestly, rather than guessed): the raw model response, the target's first failing
test, and the target's expected interface. The A-taxonomy below is populated where offline evidence suffices and
left explicitly undetermined otherwise.
"""
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments import patch_forensics as PF  # noqa: E402

ART2 = os.path.join("artifacts", "bigcode_r2")
OUT = os.path.join("artifacts", "actionable_memory_r3")

# Gap taxonomy (§3). offline=True => determinable from persisted R2 evidence.
A_CODES = {
    "A1_MISSING_API_DETAIL": True,
    "A2_MISSING_PRECONDITION": False,
    "A3_WRONG_APPLICABILITY_DECISION": False,
    "A4_PROCEDURE_NOT_REALISED": True,
    "A5_TARGET_INTERFACE_MISMATCH": True,
    "A6_SOURCE_NAMES_OR_CONSTANTS_COPIED": True,
    "A7_PROPERTY_NOT_VERIFIED": False,
    "A8_COUNTEREXAMPLE_IGNORED": False,
    "A9_UNRELATED_MODEL_ERROR": True,
    "A10_PARSER_OR_EVALUATOR": True,
    "A11_UNCLASSIFIED": True,
}
# which representation each failure mode motivates (§9 ladder) — the actual deliverable of §3
A_TO_BUNDLE = {
    "A1_MISSING_API_DETAIL": "B1 API_OPERATION_CARD",
    "A2_MISSING_PRECONDITION": "B1/B6 preconditions + property spec",
    "A3_WRONG_APPLICABILITY_DECISION": "B2 CONDITION_ACTION_TABLE / B7 contrast",
    "A4_PROCEDURE_NOT_REALISED": "B3 PROCEDURAL_PSEUDOCODE",
    "A5_TARGET_INTERFACE_MISMATCH": "B4 AST_EDIT_SCHEMA / B5 diff template",
    "A6_SOURCE_NAMES_OR_CONSTANTS_COPIED": "B4/B5 placeholder edit (forbid identifier copy)",
    "A7_PROPERTY_NOT_VERIFIED": "B6 EXECUTABLE_PROPERTY_SPEC",
    "A8_COUNTEREXAMPLE_IGNORED": "B7 POSITIVE_NEGATIVE_CONTRAST",
    "A9_UNRELATED_MODEL_ERROR": "(not representation-addressable)",
    "A10_PARSER_OR_EVALUATOR": "(engineering: applier/evaluator, not representation)",
    "A11_UNCLASSIFIED": "(insufficient evidence)",
}


def load_records():
    recs = []
    for f in sorted(glob.glob(os.path.join(ART2, "results", "main_raw.*.json"))):
        recs.extend(json.load(open(f, encoding="utf-8"))["results"])
    return recs


def source_sigs():
    facts = json.load(open(os.path.join(ART2, "source_bank.json"), encoding="utf-8"))["facts"]
    return {f["source_task"]: {k: set(f.get(k, [])) for k in ("imports", "apis", "operations", "control_flow")}
            for f in facts}


def pf_to_a(cls, exec_ok, msig, ssig):
    """Map a patch_forensics class + structural evidence onto the offline A-taxonomy."""
    if cls == "PARSER_OR_APPLY_FAILURE" or cls == "GRADER_FAILURE":
        return "A10_PARSER_OR_EVALUATOR"
    if cls == "UNCLASSIFIED":
        return "A11_UNCLASSIFIED"
    if cls in ("EXACT_SOURCE_OPERATION_ADOPTION", "PARTIAL_SOURCE_OPERATION_ADOPTION", "SOURCE_API_CALL_ADOPTION",
               "SOURCE_CONTROL_FLOW_ADOPTION"):
        # source content WAS adopted yet the task still failed -> the adopted detail didn't realise as code
        if not exec_ok:
            return "A4_PROCEDURE_NOT_REALISED"    # adopted structure but code raised/timed out
        return "A6_SOURCE_NAMES_OR_CONSTANTS_COPIED"  # adopted source element, ran, still wrong -> mis-transfer
    # UNRELATED_IMPLEMENTATION_ERROR: injected relevant source but the failing patch used none of it
    if ssig and (ssig["apis"] or ssig["imports"]) and msig is not None:
        used = (msig["apis"] | msig["imports"]) & (ssig["apis"] | ssig["imports"])
        if not used:
            return "A1_MISSING_API_DETAIL"        # relevant source API present in memory, absent from patch
    if not exec_ok:
        return "A5_TARGET_INTERFACE_MISMATCH"     # ran-fail vs raised distinguishes realise vs interface
    return "A9_UNRELATED_MODEL_ERROR"


def main():
    recs = load_records()
    ssig = source_sigs()
    by = collections.defaultdict(dict)  # tid -> arm -> rec
    for r in recs:
        by[r["tid"]][r["arm"]] = r
    # buckets
    gains = collections.defaultdict(list)          # arm -> tids memory passes, M0 fails
    losses = collections.defaultdict(list)         # arm -> tids M0 passes, memory fails
    changed_not_correct = collections.defaultdict(int)  # arm -> patch differs from M0 but same pass outcome
    adoption_failed = collections.defaultdict(int)      # arm -> adoption present yet pass1=0
    a_counts = {arm: {a: 0 for a in A_CODES} for arm in ("M1", "M2", "M3", "M5", "M7")}
    plain_vs_governed = {"both_pass": 0, "plain_only": 0, "governed_only": 0, "both_fail": 0, "n": 0}

    for tid, arms in by.items():
        m0 = arms.get("M0")
        if not m0:
            continue
        for arm in ("M1", "M2", "M3", "M5", "M7"):
            r = arms.get(arm)
            if not r:
                continue
            mp, bp = r.get("applied_patch"), m0.get("applied_patch")
            if r["pass1"] == 1 and m0["pass1"] == 0:
                gains[arm].append(tid)
            if r["pass1"] == 0 and m0["pass1"] == 1:
                losses[arm].append(tid)
            if mp != bp and r["pass1"] == m0["pass1"]:
                changed_not_correct[arm] += 1
            # classify the GAP for every failing memory-arm job (pass1==0), against M0 base
            if r["pass1"] == 0:
                cls, _ = PF.classify_loss(mp, bp, ssig.get(r.get("assigned_source")),
                                          injected=bool(r["injected"]), exec_ok=bool(r["exec1"]))
                if cls in ("EXACT_SOURCE_OPERATION_ADOPTION", "PARTIAL_SOURCE_OPERATION_ADOPTION",
                           "SOURCE_API_CALL_ADOPTION", "SOURCE_CONTROL_FLOW_ADOPTION"):
                    adoption_failed[arm] += 1
                a = pf_to_a(cls, bool(r["exec1"]), PF.patch_signature(mp) if mp else None,
                            ssig.get(r.get("assigned_source")))
                a_counts[arm][a] += 1
        # same-source plain (M2==M6 under F1_PLAIN selection) vs governed (M7)
        p, g = arms.get("M2"), arms.get("M7")
        if p and g:
            plain_vs_governed["n"] += 1
            pp, gp = p["pass1"] == 1, g["pass1"] == 1
            key = "both_pass" if pp and gp else "plain_only" if pp else "governed_only" if gp else "both_fail"
            plain_vs_governed[key] += 1

    out = {
        "experiment": "R3_ACTIONABILITY_FORENSICS",
        "source": "REALBENCH-R2 persisted main raw (offline, no model calls)",
        "n_targets": len(by),
        "gains": {a: len(v) for a, v in gains.items()},
        "losses": {a: len(v) for a, v in losses.items()},
        "changed_patch_same_outcome": dict(changed_not_correct),
        "adoption_present_but_failed": dict(adoption_failed),
        "gap_taxonomy_offline": a_counts,
        "gap_offline_determinable": {a: v for a, v in A_CODES.items()},
        "a_to_candidate_bundle": A_TO_BUNDLE,
        "plain_vs_governed_same_source": plain_vs_governed,
    }
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "r1_r2_forensics.json"), "w", encoding="utf-8", newline="\n"),
              indent=2, sort_keys=True)
    print("gap taxonomy (M2 relevant):", json.dumps(a_counts["M2"]))
    print("gains", out["gains"], "losses", out["losses"])
    print("adoption-present-but-failed", out["adoption_present_but_failed"])
    print("plain vs governed", plain_vs_governed)


if __name__ == "__main__":
    main()
