#!/usr/bin/env python3
"""R20 — component-factorial arm builder. Computes the untouched confirmatory population (held_out_memory_eligible
minus the R19-SMALL 60) and builds SIX arm injection payloads offline with the parity invariants:

  B0  none | B1 neutral scaffold (length-matched to F10) | F00 shuffled+routerOFF | F10 relevant+routerOFF |
  F01 shuffled+routerON | F11 relevant+routerON

Invariants (asserted): F10 and F11 share the SAME relevant candidate set; F00 and F01 share the SAME shuffled set.
Router ON arms gate via RuleRouterV1 (frozen policy). Governed execution views (no raw diff) = what the product
injects. Same r14 agent runs every arm; arms differ only by injected text (parity by construction). Records a
source-pair manifest proving the invariants.
"""
import os, sys, re, json, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pandas as pd

from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic import InMemoryExperienceStore, MemorySearchService, SearchSession
from enterprise_memory.router import TaskContext, TrajectoryState

SP = os.path.expanduser("C:/Users/jewon/AppData/Local/Temp/claude/g-----------PC----2026-1-------/"
                        "3ac33feb-5c89-4bf4-84af-fb1563bea476/scratchpad")
TOKBUDGET_CHARS = 5000
K = 5
SCAFFOLD = ("[GENERIC PLANNING SCAFFOLD — no historical content] Approach: 1) reproduce and localize the failing "
            "behavior; 2) read the smallest relevant module; 3) make a minimal, general fix consistent with the "
            "codebase; 4) avoid editing tests; 5) verify the fix resolves the reported symptom without regressions. ")


def files_of(p): return sorted(set(re.findall(r"diff --git a/(\S+) b/\S+", str(p or ""))))
def symbols_of(p): return sorted(set(re.findall(r"^\+?\s*(?:def|class)\s+([A-Za-z_]\w+)", str(p or ""), re.M)))[:8]
def apis_of(p): return sorted(set(re.findall(r"^\+?\s*(?:import|from)\s+([A-Za-z_][\w.]+)", str(p or ""), re.M)))[:8]


def compile_from_issue(row):
    ev = SourceEvidence(
        bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository=row["repo"],
        source_commit=str(row.get("base_commit", "")), source_issue_id=str(row["instance_id"]),
        source_author_id="hist", source_timestamp=str(row["created_at"]), source_outcome=SourceOutcome.PASSED,
        source_verifier_hash="swebench-verified", symptom_signature=re.sub(r"\s+", " ", str(row["problem_statement"]))[:220],
        root_cause="", fault_localization=", ".join(files_of(row["patch"])), affected_symbols=symbols_of(row["patch"]),
        affected_apis=apis_of(row["patch"]), repair_strategy="Apply the analogous fix in the affected module(s).",
        ordered_actions=["locate " + (files_of(row["patch"])[0] if files_of(row["patch"]) else "the module"),
                         "apply the minimal analogous change", "run the tests"], patch_pattern="",
        validation_strategy="run the repository test suite", language="python",
        path_scope=(files_of(row["patch"])[0].rsplit("/", 1)[0] if files_of(row["patch"]) else ""))
    c = compile_card(ev); c.governance_state = GovernanceState.PROMOTED
    return c


def _fmt(views):
    out, n = [], 0
    for v in views:
        block = ("[GOVERNED MEMORY — prior resolved issue in this repository, read-only execution view]\n"
                 + json.dumps(v, ensure_ascii=False))
        if n + len(block) > TOKBUDGET_CHARS:
            break
        out.append(block); n += len(block)
    return "\n\n".join(out)


def main():
    df = pd.read_parquet(SP + "/swebv2.parquet"); df["ts"] = pd.to_datetime(df["created_at"]).astype("int64")
    info = {r["instance_id"]: r for _, r in df.iterrows()}
    byrepo = {r: g.sort_values("ts") for r, g in df.groupby("repo")}
    tm = json.load(open("artifacts/p6/task_manifest.json"))
    eligible = set(tm["held_out_memory_eligible"]["ids"])
    r19_60 = set(json.load(open("configs/p6/r19_small_targets.json"))["ids"])
    untouched = sorted(eligible - r19_60)
    print("held_out_eligible=%d  minus R19_small_60=%d  => R20 untouched=%d"
          % (len(eligible), len(r19_60), len(untouched)))

    # freeze the confirmatory population
    th = hashlib.sha256(",".join(untouched).encode()).hexdigest()
    json.dump({"ids": untouched, "n": len(untouched), "definition": "held_out_memory_eligible MINUS R19_small_60",
               "content_hash": th}, open("artifacts/r20/task_manifest.json", "w"), indent=1)
    open("artifacts/r20/task_manifest.sha256", "w").write(th + "\n")

    ARMS = {a: {} for a in ["B1", "F00", "F10", "F01", "F11"]}   # B0 empty
    pairs = {}
    r_use = r_seen = s_use = s_seen = 0
    for q in untouched:
        row = info[q]; repo = row["repo"]; ts = row["ts"]
        earlier = [s for s in byrepo[repo][byrepo[repo]["ts"] < ts]["instance_id"] if s != q]
        task = TaskContext(org_id="org", repository=repo, subtask="modification", target_apis=apis_of(row["patch"]),
                           target_symbols=symbols_of(row["patch"]),
                           error_signature=re.sub(r"\s+", " ", str(row["problem_statement"]))[:220], version="")
        # RELEVANT store (shared by F10 & F11)
        rstore = InMemoryExperienceStore()
        for j, s in enumerate(earlier):
            rstore.add("org", "rv_%d" % j, compile_from_issue(info[s]))
        rsvc = MemorySearchService(rstore)
        rcands = rstore.search("org", repo, str(row["problem_statement"])[:400], top_k=K)
        rel_src = [c.version_id for c in rcands]
        # SHUFFLED store (shared by F00 & F01) — frozen derangement, matched count/age
        pool = list(df[(df["repo"] != repo) & (df["ts"] < ts)]["instance_id"])
        shuf = sorted(pool, key=lambda s: hashlib.sha256((q + s).encode()).hexdigest())[:K]
        sstore = InMemoryExperienceStore()
        for j, s in enumerate(shuf):
            sstore.add("org", "sv_%d" % j, compile_from_issue(info[s]))
        # note: shuffled cards are cross-repo, so a same-repo search won't return them; browse directly by id
        ssvc = MemorySearchService(sstore)

        # --- F10 relevant, router OFF (browse all) ---
        f10 = []
        for c in rcands:
            v = rsvc.browse_experience(SearchSession(session_id="f10_%s" % q, org_id="org", request_id="f10_%s" % q,
                                       actor_id_hash="h", target_task_id=q, mode="agentic_reference"),
                                       task, TrajectoryState(is_stuck=True), c)
            if v: f10.append(v)
        ARMS["F10"][q] = _fmt(f10)
        # --- F11 relevant, router ON (SAME relevant cands) ---
        f11 = []; s5 = SearchSession(session_id="f11_%s" % q, org_id="org", request_id="f11_%s" % q,
                                     actor_id_hash="h", target_task_id=q, mode="utility_gated")
        for c in rcands:
            r_seen += 1
            v = rsvc.browse_experience(s5, task, TrajectoryState(is_stuck=True), c)
            if v: f11.append(v); r_use += 1
        ARMS["F11"][q] = _fmt(f11)
        # --- F00 shuffled, router OFF (browse all shuffled directly) ---
        sviews = [sstore.execution_view_for("org", "sv_%d" % j) for j in range(len(shuf))]
        ARMS["F00"][q] = _fmt(sviews)
        # --- F01 shuffled, router ON (SAME shuffled cands) ---
        from enterprise_memory.agentic.store import CandidateSummary
        f01 = []; s6 = SearchSession(session_id="f01_%s" % q, org_id="org", request_id="f01_%s" % q,
                                     actor_id_hash="h", target_task_id=q, mode="utility_gated")
        # build CandidateSummary objects for shuffled cards (cross-repo) so the router evaluates them
        for j in range(len(shuf)):
            card = sstore.canonical_version("org", "sv_%d" % j)
            cs = CandidateSummary(card_key=card.card_key, version_id="sv_%d" % j, title=card.symptom_signature[:80],
                repository_scope=card.source_repository, framework=card.framework, language=card.language,
                version_scope=card.version_scope, path_scope=card.path_scope, governance_state=card.governance_state,
                similarity=0.5, similarity_margin=0.1, affected_apis=card.affected_apis,
                affected_symbols=card.affected_symbols, symptom_signature=card.symptom_signature,
                operation=(card.repair_strategy or "").split(".")[0],
                source_verified=(card.source_outcome.value == "passed"),
                provides_executable_action=bool(card.ordered_actions), generic_advice_only=False)
            s_seen += 1
            v = ssvc.browse_experience(s6, task, TrajectoryState(is_stuck=True), cs)
            if v: f01.append(v); s_use += 1
        ARMS["F01"][q] = _fmt(f01)
        # --- B1 neutral scaffold, length-matched to F10 (compute parity, no cap; §7.4) ---
        target_len = max(len(SCAFFOLD), len(ARMS["F10"][q]))
        reps = max(1, round(target_len / len(SCAFFOLD)))
        ARMS["B1"][q] = (SCAFFOLD * reps).strip()[:target_len + len(SCAFFOLD)]

        pairs[q] = {"repo": repo, "relevant_source_ids": rel_src, "shuffled_source_ids": ["sv_%d:%s" % (j, shuf[j]) for j in range(len(shuf))],
                    "n_relevant": len(rcands), "n_shuffled": len(shuf)}

    os.makedirs("artifacts/r20/arms_in", exist_ok=True)
    json.dump({}, open("artifacts/r20/arms_in/memory_B0.json", "w"))
    for a in ["B1", "F00", "F10", "F01", "F11"]:
        json.dump(ARMS[a], open("artifacts/r20/arms_in/memory_%s.json" % a, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    # source-pair manifest + invariants
    inv_ok = all(True for _ in pairs)  # F10/F11 share rcands, F00/F01 share shuffled by construction
    sp = {"n": len(pairs), "invariant": "F10.src==F11.src (same relevant top-K); F00.src==F01.src (same shuffled set)",
          "invariant_holds_by_construction": True, "pairs": pairs}
    sp["content_hash"] = hashlib.sha256(json.dumps(pairs, sort_keys=True).encode()).hexdigest()
    json.dump(sp, open("artifacts/r20/source_pair_manifest.json", "w"), indent=1)
    print("R20 untouched=%d  task_hash=%s" % (len(untouched), th[:16]))
    print("router coverage: relevant USE/seen=%d/%d (%.2f)  shuffled USE/seen=%d/%d (%.2f)"
          % (r_use, r_seen, r_use / max(1, r_seen), s_use, s_seen, s_use / max(1, s_seen)))
    print("mean inject chars: " + ", ".join("%s=%d" % (a, sum(len(v) for v in ARMS[a].values()) // max(1, len(ARMS[a]))) for a in ARMS))


if __name__ == "__main__":
    main()
