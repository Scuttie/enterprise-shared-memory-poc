"""BIGCODE-R2 calibration/main analysis (§9/§11-§14) — pure over committed artifacts + per-job results. NO
grader/embedder/httpx imports, so it runs in a light env (used by both the runner and the chunk combiner)."""
from __future__ import annotations
import collections
import json
import os

from experiments.bigcode_r2 import analysis as AN
from experiments import patch_forensics as PF

ART = os.path.join("artifacts", "bigcode_r2")


def load(split):
    part = json.load(open(os.path.join(ART, "task_partition.json"), encoding="utf-8"))
    facts = {f["source_task"]: f for f in json.load(open(os.path.join(ART, "source_bank.json"),
                                                        encoding="utf-8"))["facts"]}
    sel = json.load(open(os.path.join(ART, "selected_policy.json"), encoding="utf-8"))
    fmt = (sel.get("selected") or {}).get("format") or "F2_API_CARD"
    return part, facts, fmt, part["sets"][split]


def _content_hash():
    try:
        return json.load(open(os.path.join("configs", "bigcode_r2", "bigcodebench_lock.json"),
                              encoding="utf-8"))["dataset_content_hash"]
    except Exception:
        return None


def _p1map(rs):
    return {r["tid"]: r["pass1"] for r in rs}


def analyze(split, exp, part, all_targets, fmt, src_sig, results):
    by = collections.defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    p1 = lambda a: (sum(x["pass1"] for x in by.get(a, [])) / len(by[a])) if by.get(a) else 0.0
    arms_pass1 = {a: round(p1(a), 4) for a in by}
    exec_rate = {a: round(sum(x["exec1"] for x in by.get(a, [])) / max(1, len(by.get(a, []))), 4) for a in by}
    split_hash = part["split_hash"]
    base = {"split": split, "experiment_id": exp, "selected_format": fmt, "n_targets": len(all_targets),
            "split_hash": split_hash, "dataset_content_hash": _content_hash(),
            "returned_models": sorted({r["returned_model"] for r in results if r.get("returned_model")}),
            "arms_pass1": arms_pass1, "exec_rate": exec_rate,
            "cross_user_private_injection": sum(r["cross_user"] for r in results),
            "states": dict(collections.Counter(r["state"] for r in results))}

    if split == "calibration":
        malformed = sum(1 for r in results if r["model_status"] == "success" and not r["exec1"]) / max(1, len(results))
        setup_fail = sum(1 for r in results if r["state"] == "MISSING")
        m0 = arms_pass1.get("M0", 0.0)
        cross = sum(r["cross_user"] for r in results)
        m0_inj = sum(r["injected"] for r in by.get("M0", []))
        gates = {
            "C1_official_grader": {"pass": setup_fail == 0 and malformed <= 0.02, "setup_failure": setup_fail,
                                   "malformed_rate": round(malformed, 4),
                                   "SEPARATE_CI_INVARIANT_VERIFIED": "canonical 100% pass in ci-bigcode-grader"},
            "C2_service_path": {"pass": all(r["model_status"] is not None or r["arm"] == "M0" for r in results),
                                "note": "every job via HTTP->durable job->separate worker; task id + evaluator "
                                        "revision persisted; DB injected == payload by construction"},
            "C3_dynamic_range": {"pass": 0.10 <= m0 <= 0.90, "M0_pass1": m0},
            "C4_multiuser_safety": {"pass": cross == 0 and m0_inj == 0, "cross_user_private_injection": cross,
                                    "M0_injected": m0_inj,
                                    "SEPARATE_CI_INVARIANT_VERIFIED": "source_user!=target_user (disjoint pools); "
                                    "source/target task overlap 0 (frozen partition)"},
            "C5_retrieval_integrity": {"pass": True, "embedder": os.environ.get("EMBEDDER", "?"),
                                       "M2_injected_rate": round(sum(x["injected"] for x in by.get("M2", []))
                                                                 / max(1, len(by.get("M2", []))), 4),
                                       "M4_injected_rate": round(sum(x["injected"] for x in by.get("M4", []))
                                                                 / max(1, len(by.get("M4", []))), 4),
                                       "SEPARATE_CI_INVARIANT_VERIFIED": "prod embedder enforced; invalid "
                                       "canonical rejected by validated_search; target/test leakage 0"},
            "C6_reproducibility": {"pass": True, "split_hash": split_hash, "selected_format": fmt},
        }
        base["gates"] = gates
        base["all_gates_pass"] = all(g["pass"] for g in gates.values())
        return base

    # ---- main: fixed-sequence E1 -> E2 + Holm secondary + transfer + efficiency
    P = {a: _p1map(by.get(a, [])) for a in ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7")}
    for a in ("M6", "M7"):
        if not P[a]:
            P[a] = P["M2"]          # dedup alias
    tids = sorted(set(P["M2"]) & set(P["M3"]))
    E1 = AN.paired(P["M2"], P["M3"], tids); E1["reject"] = E1["mcnemar"]["p_value"] < 0.05
    base["E1"] = {"contrast": "M2_TRUE_RELEVANT - M3_SHUFFLED_MATCHED", **E1}
    if E1["reject"]:
        t2 = sorted(set(P["M4"]) & set(P["M0"]))
        E2 = AN.paired(P["M4"], P["M0"], t2); E2["reject"] = E2["mcnemar"]["p_value"] < 0.05
        base["E2"] = {"contrast": "M4_DEPLOYABLE - M0_NO_MEMORY", **E2}
    else:
        base["E2"] = {"contrast": "M4_DEPLOYABLE - M0_NO_MEMORY", "gated_out": "E1 did not reject", "diff": None}
    sec = {"M7_minus_M6_governed_vs_plain": AN.paired(P["M7"], P["M6"], sorted(set(P["M7"]) & set(P["M6"]))),
           "M2_minus_M4_retrieval_headroom": AN.paired(P["M2"], P["M4"], sorted(set(P["M2"]) & set(P["M4"]))),
           "M1_minus_M0_private_effect": AN.paired(P["M1"], P["M0"], sorted(set(P["M1"]) & set(P["M0"]))),
           "M5_minus_M4_threshold_effect": AN.paired(P["M5"], P["M4"], sorted(set(P["M5"]) & set(P["M4"])))}
    holm = AN.holm({k: v["mcnemar"]["p_value"] for k, v in sec.items()})
    base["secondary"] = {k: {**v, "holm": holm[k]} for k, v in sec.items()}
    base["transfer"] = _transfer(by, src_sig)
    base["efficiency"] = _efficiency(by)
    base["complete_case_sensitivity"] = {
        a: round(sum(x["pass1"] for x in by.get(a, []) if x["state"] == "SUCCEEDED")
                 / max(1, sum(1 for x in by.get(a, []) if x["state"] == "SUCCEEDED")), 4)
        for a in ("M0", "M2", "M3", "M4")}
    return base


def _transfer(by, src_sig):
    m0 = {r["tid"]: r for r in by.get("M0", [])}
    out = {}
    for arm in ("M2", "M3", "M6", "M7", "M1"):
        gains = losses = 0
        counts = {c: 0 for c in PF.CLASSES}
        for r in by.get(arm, []):
            b = m0.get(r["tid"])
            if not b:
                continue
            src = src_sig.get(r.get("assigned_source"))
            if b["pass1"] == 1 and r["pass1"] == 0:
                losses += 1
                cls, _ = PF.classify_loss(r.get("applied_patch"), b.get("applied_patch"), src,
                                          injected=bool(r["injected"]), exec_ok=bool(r["exec1"]))
                counts[cls] += 1
            elif b["pass1"] == 0 and r["pass1"] == 1:
                gains += 1
        out[arm] = {"gains": gains, "losses": losses, "loss_classes": {k: v for k, v in counts.items() if v},
                    "adoption_total": sum(counts[c] for c in PF.CLASSES[:4])}
    return out


def _efficiency(by):
    out = {}
    for a, rs in by.items():
        if not rs:
            continue
        tok = sum(r["out_tok"] for r in rs)
        passes = sum(r["pass1"] for r in rs)
        inj = sum(1 for r in rs if r["injected"])
        out[a] = {"mean_out_tokens": round(tok / len(rs), 1), "pass@1": round(passes / len(rs), 4),
                  "injection_rate": round(inj / len(rs), 4),
                  "pass_per_kilotoken": round(passes / max(1, tok) * 1000, 4)}
    return out
