#!/usr/bin/env python3
"""R19-SMALL — build A0..A5 injection payloads OFFLINE using the real compiler / agentic service / router.

Parity by construction: the SAME r14 SWE-bench agent runs every arm; arms differ ONLY by the injected memory text
(matched token budget). A0 none · A1 neutral planning scaffold (no historical content) · A2 shuffled cross-repo
execution views · A3 one static relevant execution view · A4 agentic-reference selected · A5 utility-router gated.

Cards are compiled deterministically (no LLM) from earlier same-repo issues (problem+patch evidence) into governed
execution views (no raw diff — this is what the product actually injects). Freezes 60 repo-stratified held-out
targets BEFORE running. Reduced-power confirmatory design; precision limit is stated in the prereg amendment.
"""
import os, sys, re, json, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pandas as pd

from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.experience.compiler import execution_view
from enterprise_memory.agentic import InMemoryExperienceStore, MemorySearchService, SearchSession
from enterprise_memory.router import TaskContext, TrajectoryState

SP = os.path.expanduser("C:/Users/jewon/AppData/Local/Temp/claude/g-----------PC----2026-1-------/"
                        "3ac33feb-5c89-4bf4-84af-fb1563bea476/scratchpad")
TOKBUDGET_CHARS = 5000
K = 5
SCAFFOLD = ("[GENERIC PLANNING SCAFFOLD — no historical content] Approach: 1) reproduce and localize the failing "
            "behavior; 2) read the smallest relevant module; 3) make a minimal, general fix consistent with the "
            "codebase; 4) avoid editing tests; 5) verify the fix resolves the reported symptom without regressions.")


def files_of(p):
    return sorted(set(re.findall(r"diff --git a/(\S+) b/\S+", str(p or ""))))


def symbols_of(p):
    return sorted(set(re.findall(r"^\+?\s*(?:def|class)\s+([A-Za-z_]\w+)", str(p or ""), re.M)))[:8]


def apis_of(p):
    return sorted(set(re.findall(r"^\+?\s*(?:import|from)\s+([A-Za-z_][\w.]+)", str(p or ""), re.M)))[:8]


def compile_from_issue(row, bank):
    ev = SourceEvidence(
        bank=bank, source_type="issue_fix", source_repository=row["repo"], source_commit=str(row.get("base_commit", "")),
        source_issue_id=str(row["instance_id"]), source_author_id="hist", source_timestamp=str(row["created_at"]),
        source_outcome=SourceOutcome.PASSED, source_verifier_hash="swebench-verified",
        symptom_signature=re.sub(r"\s+", " ", str(row["problem_statement"]))[:220],
        root_cause="", fault_localization=", ".join(files_of(row["patch"])),
        affected_symbols=symbols_of(row["patch"]), affected_apis=apis_of(row["patch"]),
        repair_strategy="Apply the analogous fix in the affected module(s).",
        ordered_actions=["locate " + (files_of(row["patch"])[0] if files_of(row["patch"]) else "the module"),
                         "apply the minimal analogous change", "run the tests"],
        patch_pattern="", validation_strategy="run the repository test suite", language="python",
        framework="", version_scope="", path_scope=(files_of(row["patch"])[0].rsplit("/", 1)[0] if files_of(row["patch"]) else ""))
    card = compile_card(ev)
    card.governance_state = GovernanceState.PROMOTED
    return card


def _fmt(views):
    out, n = [], 0
    for i, v in enumerate(views):
        block = ("[GOVERNED MEMORY — a prior resolved issue in this repository, compiled to a read-only execution "
                 "view (not this issue's solution)]\n" + json.dumps(v, ensure_ascii=False))
        if n + len(block) > TOKBUDGET_CHARS:
            break
        out.append(block); n += len(block)
    return "\n\n".join(out)


def main():
    df = pd.read_parquet(SP + "/swebv2.parquet"); df["ts"] = pd.to_datetime(df["created_at"]).astype("int64")
    info = {r["instance_id"]: r for _, r in df.iterrows()}
    byrepo = {r: g.sort_values("ts") for r, g in df.groupby("repo")}
    tm = json.load(open("artifacts/p6/task_manifest.json"))
    eligible = tm["held_out_memory_eligible"]["ids"]

    # freeze 60 repo-stratified held-out targets (deterministic), BEFORE running
    from collections import defaultdict, Counter
    byr = defaultdict(list)
    for q in eligible:
        byr[info[q]["repo"]].append(q)
    targets = []
    for repo, ids in byr.items():
        ids = sorted(ids, key=lambda q: hashlib.sha256(("r19s" + q).encode()).hexdigest())
        n = max(1, round(60 * len(ids) / len(eligible)))
        targets += ids[:n]
    targets = sorted(set(targets), key=lambda q: hashlib.sha256(("r19s" + q).encode()).hexdigest())[:60]
    json.dump({"ids": targets, "n": len(targets),
               "content_hash": hashlib.sha256(",".join(sorted(targets)).encode()).hexdigest()},
              open("configs/p6/r19_small_targets.json", "w"), indent=1)

    svc_store = {}
    A = {a: {} for a in ["A1", "A2", "A3", "A4", "A5"]}
    router_use = 0; router_seen = 0
    for q in targets:
        row = info[q]; repo = row["repo"]; ts = row["ts"]
        earlier = [s for s in byrepo[repo][byrepo[repo]["ts"] < ts]["instance_id"] if s != q]
        # relevant candidates: top-K earlier same-repo by problem-text similarity
        store = InMemoryExperienceStore()
        for j, s in enumerate(earlier):
            store.add("org", "v_%s_%d" % (q, j), compile_from_issue(info[s], Bank.HISTORICAL_VERIFIED))
        svc = MemorySearchService(store)
        task = TaskContext(org_id="org", repository=repo, subtask="modification",
                           target_apis=apis_of(row["patch"]), target_symbols=symbols_of(row["patch"]),
                           error_signature=re.sub(r"\s+", " ", str(row["problem_statement"]))[:220], version="")
        sess = SearchSession(session_id="s_" + q, org_id="org", request_id="r_" + q, actor_id_hash="h",
                             target_task_id=q, mode="agentic_reference")
        cands = store.search("org", repo, str(row["problem_statement"])[:400], top_k=K)

        # A3 static relevant = top-1 execution view
        if cands:
            A["A3"][q] = _fmt([store.execution_view_for("org", cands[0].version_id)])
        # A4 agentic reference (no router)
        a4 = []
        for c in cands:
            v = svc.browse_experience(SearchSession(session_id="s4_" + q, org_id="org", request_id="r4_" + q,
                                      actor_id_hash="h", target_task_id=q, mode="agentic_reference"),
                                      task, TrajectoryState(is_stuck=True), c)
            if v:
                a4.append(v)
        A["A4"][q] = _fmt(a4)
        # A5 utility-gated (router)
        a5 = []
        s5 = SearchSession(session_id="s5_" + q, org_id="org", request_id="r5_" + q, actor_id_hash="h",
                           target_task_id=q, mode="utility_gated")
        for c in cands:
            router_seen += 1
            v = svc.browse_experience(s5, task, TrajectoryState(is_stuck=True), c)
            if v:
                a5.append(v); router_use += 1
        A["A5"][q] = _fmt(a5)
        # A2 shuffled cross-repo (matched count/token budget, agentic_reference selection)
        pool = list(df[(df["repo"] != repo) & (df["ts"] < ts)]["instance_id"])
        shuf = sorted(pool, key=lambda s: hashlib.sha256((q + s).encode()).hexdigest())[:K]
        sstore = InMemoryExperienceStore()
        for j, s in enumerate(shuf):
            sstore.add("org", "sv_%d" % j, compile_from_issue(info[s], Bank.HISTORICAL_VERIFIED))
        sviews = [sstore.execution_view_for("org", "sv_%d" % j) for j in range(len(shuf))]
        A["A2"][q] = _fmt(sviews[:len(a4) or 1])
        # A1 neutral scaffold, matched token budget to A4
        A["A1"][q] = SCAFFOLD * max(1, min(6, (len(A["A4"].get(q, "")) // len(SCAFFOLD)) or 1))

    os.makedirs("artifacts/p6/arms_in", exist_ok=True)
    json.dump({}, open("artifacts/p6/arms_in/memory_A0.json", "w"))  # no memory
    for a in ["A1", "A2", "A3", "A4", "A5"]:
        json.dump(A[a], open("artifacts/p6/arms_in/memory_%s.json" % a, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("R19-SMALL targets=%d (repos=%d)" % (len(targets), len(set(info[q]['repo'] for q in targets))))
    print("router USE/seen = %d/%d (coverage %.2f)" % (router_use, router_seen, router_use / max(1, router_seen)))
    print("mean inject chars: " + ", ".join("%s=%d" % (a, sum(len(v) for v in A[a].values()) // max(1, len(A[a]))) for a in A))


if __name__ == "__main__":
    main()
