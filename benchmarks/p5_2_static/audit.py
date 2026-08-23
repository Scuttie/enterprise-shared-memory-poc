"""P5.2 §4 generator audit. Verifies strata proportions, that gold passes and the memory-less prior baseline
passes exactly the prior_aligned families (nonzero-M0-baseline structurally possible; prior-conflict needs
memory), zero source/target overlap, zero target-answer/hidden-test leakage, exact signatures, and
deterministic regeneration."""
from __future__ import annotations
import re
import collections
from . import families as F
from . import solver as S
from . import fixtures as X

CALIBRATION = ("calibration", 4)
MAIN = ("main", 8)


def _tokens(text):
    return set(re.findall(r"\b\d+\b", text))


def _all_tasks(fams):
    return [t for f in fams for t in f.tasks.values()]


def audit(splits=(CALIBRATION, MAIN)):
    report = {"splits": {}, "cross_split": {}, "ok": True}
    gen = {name: F.generate(name, n) for name, n in splits}
    for name, fams in gen.items():
        src = [f.tasks[r] for f in fams for r in ("own_source", "cross_source")]
        tgt = [f.target for f in fams]
        src_ids, tgt_ids = {t.task_id for t in src}, {t.task_id for t in tgt}
        src_repos, tgt_repos = {t.repo_fixture_id for t in src}, {t.repo_fixture_id for t in tgt}

        # strata proportions per domain
        strata_ok = True
        want = {4: {"prior_aligned": 1, "context_inferable": 1, "prior_conflict": 2},
                8: {"prior_aligned": 2, "context_inferable": 2, "prior_conflict": 4}}[dict(splits)[name]]
        for dom in F.DOMAINS:
            c = collections.Counter(f.stratum for f in fams if f.domain == dom)
            if dict(c) != want:
                strata_ok = False

        gold_pass = sum(1 for t in _all_tasks(fams) if S.passes_hidden(t, S.solved_file(t)))
        # prior baseline (core-for-all): passes hidden IFF prior_aligned; passes public always
        prior_hidden_pa = sum(1 for t in _all_tasks(fams)
                              if t.stratum == "prior_aligned" and S.passes_hidden(t, S.prior_core_file(t)))
        prior_hidden_nonpa_pass = sum(1 for t in _all_tasks(fams)
                                      if t.stratum != "prior_aligned" and S.passes_hidden(t, S.prior_core_file(t)))
        prior_public = sum(1 for t in _all_tasks(fams) if S.passes_public(t, S.prior_core_file(t)))
        n_pa = sum(1 for t in _all_tasks(fams) if t.stratum == "prior_aligned")
        total = len(_all_tasks(fams))
        sig_ok = sum(1 for t in _all_tasks(fams) if t.gold_body.startswith(t.exact_signature))

        # leakage: the edge value base*K must not appear as a standalone token in the memory fact
        ans_leak = 0
        for f in fams:
            fact_tokens = _tokens(str(X.memory_fact(f)))
            for r in ("target",):
                if str(f.tasks[r].edge_value) in (fact_tokens - {str(f.edge_multiplier)}):
                    ans_leak += 1
        # hidden-test never in the snapshot
        hidden_leak = sum(1 for t in tgt if t.hidden_test in "\n".join(X.render_snapshot(t).values()))
        # families where target world differs from the common prior (non prior_aligned)
        differ = sum(1 for f in fams if f.stratum != "prior_aligned")

        s = {"families": len(fams), "tasks": total,
             "source_target_task_overlap": len(src_ids & tgt_ids),
             "source_target_repo_overlap": len(src_repos & tgt_repos),
             "strata_proportions_ok": strata_ok,
             "gold_pass_rate": gold_pass / total,
             "prior_passes_all_prior_aligned": prior_hidden_pa == n_pa,
             "prior_passes_zero_non_aligned": prior_hidden_nonpa_pass == 0,
             "prior_public_pass_rate": prior_public / total,
             "exact_signature_rate": sig_ok / total,
             "target_answer_leakage": ans_leak, "hidden_test_leakage": hidden_leak,
             "families_differ_from_prior": differ,
             "generation_hash": F.generation_hash(name, dict(splits)[name])}
        s["ok"] = (s["source_target_task_overlap"] == 0 and s["source_target_repo_overlap"] == 0
                   and strata_ok and s["gold_pass_rate"] == 1.0 and s["prior_passes_all_prior_aligned"]
                   and s["prior_passes_zero_non_aligned"] and s["prior_public_pass_rate"] == 1.0
                   and s["exact_signature_rate"] == 1.0 and ans_leak == 0 and hidden_leak == 0)
        report["splits"][name] = s
        report["ok"] = report["ok"] and s["ok"]

    names = [n for n, _ in splits]
    if len(names) == 2:
        a, b = gen[names[0]], gen[names[1]]
        fam_a = {f.family_id for f in a}; fam_b = {f.family_id for f in b}
        task_a = {t.task_id for t in _all_tasks(a)}; task_b = {t.task_id for t in _all_tasks(b)}
        cs = {"family_overlap": len(fam_a & fam_b), "task_overlap": len(task_a & task_b)}
        cs["ok"] = cs["family_overlap"] == 0 and cs["task_overlap"] == 0
        report["cross_split"] = cs
        report["ok"] = report["ok"] and cs["ok"]
    return report
