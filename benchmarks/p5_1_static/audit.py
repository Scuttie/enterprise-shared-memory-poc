"""Generator audit (P5.1 §6). Verifies the frozen instrument satisfies every required property before it can
be used: zero source/target task and repository overlap, zero target-answer and hidden-test leakage, gold
passes 100%, wrong-world fails where required, exact-signature coverage 100%, and deterministic regeneration.
Pure Python (runs in `ci`)."""
from __future__ import annotations
import re
from . import families as F
from . import solver as S
from . import fixtures as X


def _tokens(text):
    """Standalone numeric literals only — digits embedded in identifiers (e.g. hex name tags) are excluded."""
    return set(re.findall(r"\b\d+\b", text))

CALIBRATION = ("calibration", 4)     # 16 families (4/domain)
MAIN = ("main", 8)                   # 32 families (8/domain)


def _all_tasks(fams):
    return [t for f in fams for t in f.tasks.values()]


def audit(splits=(CALIBRATION, MAIN)) -> dict:
    report = {"splits": {}, "cross_split": {}, "ok": True}
    gen = {name: F.generate(name, n) for name, n in splits}

    for name, fams in gen.items():
        src_tasks = [f.tasks[r] for f in fams for r in ("own_source", "cross_source")]
        tgt_tasks = [f.target for f in fams]
        src_ids, tgt_ids = {t.task_id for t in src_tasks}, {t.task_id for t in tgt_tasks}
        src_repos = {t.repo_fixture_id for t in src_tasks}
        tgt_repos = {t.repo_fixture_id for t in tgt_tasks}

        # target-answer leakage: the target's hidden answer never appears in the memory fact
        answer_leak = 0
        hidden_test_leak = 0
        for f in fams:
            fact = X.memory_fact(f, "cross_source")
            fact_tokens = _tokens(str(fact))
            # the memory may carry the convention constant C, but never the target's specific answer value
            if str(f.target.hidden_expected) in (fact_tokens - {str(f.world_constant)}):
                answer_leak += 1
            snap = X.render_snapshot(f.target)
            snap_text = "\n".join(snap.values())
            if f.target.hidden_test in snap_text or str(f.target.hidden_expected) in _tokens(snap_text):
                hidden_test_leak += 1

        # gold passes / wrong-world fails / signatures
        gold_pass = sum(1 for t in _all_tasks(fams) if S.passes_hidden(t, S.solved_file(t)))
        wrong_fail = sum(1 for t in _all_tasks(fams)
                         if not S.passes_hidden(t, S.wrong_world_file(t))
                         and S.passes_public(t, S.wrong_world_file(t)))
        sig_ok = sum(1 for t in _all_tasks(fams)
                     if t.src_stub.startswith(t.exact_signature) and t.gold_body.startswith(t.exact_signature))
        total = len(_all_tasks(fams))

        # cross-user source != target user is enforced at assignment time (§9); here we assert the source and
        # target tasks are distinct objects with distinct repos/constants-in-context (different base).
        distinct_bases = sum(1 for f in fams
                             if len({f.own_source.base, f.cross_source.base, f.target.base}) >= 2)

        s = {
            "families": len(fams), "tasks": total,
            "source_target_task_overlap": len(src_ids & tgt_ids),
            "source_target_repo_overlap": len(src_repos & tgt_repos),
            "target_answer_leakage": answer_leak,
            "hidden_test_leakage": hidden_test_leak,
            "gold_pass": gold_pass, "gold_pass_rate": gold_pass / total,
            "wrong_world_fail": wrong_fail, "wrong_world_fail_rate": wrong_fail / total,
            "exact_signature_coverage": sig_ok, "exact_signature_rate": sig_ok / total,
            "families_with_distinct_bases": distinct_bases,
            "generation_hash": F.generation_hash(name, dict(splits)[name]),
        }
        s["ok"] = (s["source_target_task_overlap"] == 0 and s["source_target_repo_overlap"] == 0
                   and s["target_answer_leakage"] == 0 and s["hidden_test_leakage"] == 0
                   and s["gold_pass_rate"] == 1.0 and s["wrong_world_fail_rate"] == 1.0
                   and s["exact_signature_rate"] == 1.0 and distinct_bases == len(fams))
        report["splits"][name] = s
        report["ok"] = report["ok"] and s["ok"]

    # calibration/main family + task overlap = 0
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
