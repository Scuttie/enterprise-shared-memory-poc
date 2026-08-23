"""REALBENCH-R1 experiment definition (§6/§7/§8/§9). Deterministic disjoint split of the official MBPP+ tasks
into a retrieval-dev set, a verified-source pool, a calibration target set and a held-out main target set;
verified source-memory rendering (M2 ungoverned summary / M3 governed contract from the SAME source fact, plus
R1 private); a shared retrieval bank (all source memories) with a frozen abstention threshold; and the arms.
Fully deterministic (SHA-256), no RNG/clock. No target reference solution or augmented test ever enters a
source memory; source ∩ target = 0; near-duplicate source/target pairs excluded."""
from __future__ import annotations
import hashlib

from . import grader as G

# split sizes (disjoint; drawn from the 378 official MBPP+ tasks in deterministic id order)
N_RETRIEVAL_DEV = 40
N_SOURCE = 150
N_CALIBRATION = 48
N_MAIN = 120
NEAR_DUP_JACCARD = 0.6          # exclude a target whose prompt overlaps a source above this (leakage guard)


def _prompt_tokens(tid):
    p = G.task(tid)["prompt"].lower()
    import re
    return set(re.findall(r"[a-z_]{3,}", p))


def _ordered_ids():
    # deterministic numeric order of Mbpp/<n>
    return sorted(G.all_task_ids(), key=lambda t: int(t.split("/")[-1]))


def build_split():
    ids = _ordered_ids()
    dev = ids[:N_RETRIEVAL_DEV]
    rest = ids[N_RETRIEVAL_DEV:]
    source = rest[:N_SOURCE]
    pool = rest[N_SOURCE:]
    src_tokens = {t: _prompt_tokens(t) for t in source}

    def near_dup(tid):
        tt = _prompt_tokens(tid)
        for s, st in src_tokens.items():
            u = len(tt | st) or 1
            if len(tt & st) / u >= NEAR_DUP_JACCARD:
                return True
        return False

    src_funcs = {G.task(t)["entry_point"] for t in source}
    clean = [t for t in pool if not near_dup(t) and G.task(t)["entry_point"] not in src_funcs]
    calibration = clean[:N_CALIBRATION]
    main = clean[N_CALIBRATION:N_CALIBRATION + N_MAIN]
    return {"retrieval_dev": dev, "source": source, "calibration": calibration, "main": main,
            "excluded_near_dup": [t for t in pool if near_dup(t)][:50]}


def audit_split(split):
    s = set(split["source"]); cal = set(split["calibration"]); mn = set(split["main"]); dev = set(split["retrieval_dev"])
    fn = lambda ids: {G.task(t)["entry_point"] for t in ids}
    return {"source_target_task_overlap": len((cal | mn) & s),
            "calibration_main_overlap": len(cal & mn),
            "dev_overlap": len(dev & (s | cal | mn)),
            "source_target_funcname_overlap": len(fn(cal | mn) & fn(s)),
            "n_source": len(s), "n_calibration": len(cal), "n_main": len(mn), "n_dev": len(dev)}


# ---------------------------------------------------------------- memory rendering (§7)
def source_fact(source_tid):
    """A target-free fact record derived from a VERIFIED source solution (canonical passes official tests)."""
    p = G.task(source_tid)
    desc = p["prompt"].strip().strip('"').strip().splitlines()[0] if p["prompt"].strip() else source_tid
    approach = p["canonical_solution"].strip().splitlines()
    approach = " ".join(l.strip() for l in approach if l.strip())[:240]
    return {"source_task": source_tid, "entry_point": p["entry_point"], "description": desc,
            "approach": approach, "tokens": " ".join(sorted(_prompt_tokens(source_tid))[:30])}


def ungoverned_text(fact):
    return ("prior solved coding example — %s. approach: %s. keywords: %s"
            % (fact["description"], fact["approach"], fact["tokens"]))


def governed_summary(fact):
    return ("Reusable coding lesson from a verified prior task (%s). Applies when: a similar problem — %s. "
            "Recommended approach: %s. Keywords: %s. Verify by running the target's own tests."
            % (fact["source_task"], fact["description"], fact["approach"], fact["tokens"]))


def _h(*p):
    return int(hashlib.sha256("|".join(str(x) for x in p).encode()).hexdigest(), 16)


def split_hash(split):
    h = hashlib.sha256()
    for k in ("retrieval_dev", "source", "calibration", "main"):
        h.update(("%s:%s" % (k, ",".join(split[k]))).encode())
    return h.hexdigest()
