#!/usr/bin/env python3
"""REALBENCH-R7 §2 — G0 multi-language GHCR + grader smoke (one instance per invocation).

Faithfully reuses the pinned SWE-PolyBench harness (imported, never copied): DockerManager, the repo-specific
parser from REPO_TO_PARSER_CLASS, and instance_level_scoring. For one instance it:
  1. pulls the official GHCR image (ghcr.io/timesler/swe-polybench.eval.x86_64.<id>:latest) and resolves its digest;
  2. CLEAN BASELINE — fresh container, apply test_patch ONLY, run test_command, parse, score:
       expect NOT resolved and F2P not all-passed (the bug is present) and P2P present-in-passed;
  3. GOLD — fresh container, apply test_patch + gold `patch`, run, parse, score: expect resolved == True.
Emits a per-instance result JSON. The gold `patch`/`test_patch`/F2P/P2P are evaluator-side only; no agent runs here.

Env: R7_INSTANCE_ID, R7_CSV (pinned Verified test.csv), R7_OUT (result json path).
Mirrors run_evaluation.evaluate_instance (lines 66-260 @ commit 9c836c5) without the empty-patch early return.
"""
import os, sys, json, ast, io
import pandas as pd
import docker

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from poly_bench_evaluation.docker_utils import DockerManager
from poly_bench_evaluation.scoring import instance_level_scoring
from poly_bench_evaluation.constants import DEFAULT_TIMEOUT, JAVA_TIMEOUT, REPO_TO_PARSER_CLASS
import poly_bench_evaluation.parsers as all_parsers

INST = os.environ["R7_INSTANCE_ID"]
CSV = os.environ["R7_CSV"]
OUT = os.environ.get("R7_OUT", f"smoke_{INST}.json")


def _to_list(v):
    if isinstance(v, list):
        return v
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    return ast.literal_eval(v)


def run_leg(client, row, image_id, apply_gold):
    """One evaluation leg. apply_gold=False -> baseline (test_patch only). Returns scoring dict."""
    repo = row["repo"]
    language = row["language"]
    test_command = row["test_command"]
    test_patch = row["test_patch"]
    gold_patch = row["patch"]
    f2p = _to_list(row["F2P"])
    p2p = _to_list(row["P2P"])
    parser_class_name = REPO_TO_PARSER_CLASS[repo]

    dm = DockerManager(image_id=image_id, delete_image=False, client=client)
    digest = None
    if not dm.check_image_local(local_image_name=image_id):
        assert dm.try_pull_prebuilt_image(INST), f"GHCR pull failed for {INST}"
    try:
        pulled = client.images.get(dm.ghcr_image_name or f"ghcr.io/timesler/swe-polybench.eval.x86_64.{INST.lower()}:latest")
        digest = (pulled.attrs.get("RepoDigests") or [None])[0]
    except Exception:
        pass
    dm.create_container()
    try:
        # apply_patch_to_container returns int 0==success (and RAISES on real failure).
        rt = dm.apply_patch_to_container(patch_content=test_patch, patch_type="test")
        assert rt == 0, "test patch failed to apply"
        if apply_gold:
            rc = dm.apply_patch_to_container(patch_content=gold_patch, patch_type="code")
            assert rc == 0, "gold patch failed to apply"
        run_timeout = JAVA_TIMEOUT if language.lower() == "java" else DEFAULT_TIMEOUT
        dm.docker_run(test_command=test_command, timeout=run_timeout)
        run_logs_string = "\n".join(dm.run_logs)
        parser = getattr(all_parsers, parser_class_name)(test_content=run_logs_string)
        result = parser.parse()
        out = instance_level_scoring(instance_id=INST, result=result, f2p=f2p, p2p=p2p,
                                     patch_applied=True, generation=True)
        passed = set(getattr(out, "passed_tests", []) or [])
        failed = set(getattr(out, "failed_tests", []) or [])
        return {
            "resolved": bool(getattr(out, "resolved", False)),
            "f2p_all_passed": set(f2p).issubset(passed) if f2p else None,
            "p2p_all_passed": set(p2p).issubset(passed) if p2p else None,
            "p2p_any_failed": len(set(p2p) & failed) > 0 if p2p else None,
            "n_passed": len(passed), "n_failed": len(failed),
            "digest": digest,
        }
    finally:
        try:
            dm.__del__()
        except Exception:
            pass


def main():
    df = pd.read_csv(CSV)
    row = df[df["instance_id"] == INST]
    assert len(row) == 1, f"{INST}: {len(row)} rows"
    row = row.iloc[0]
    image_id = f"polybench_{row['language'].lower()}_{INST.lower()}"
    client = docker.from_env()

    print(f"[{INST}] language={row['language']} repo={row['repo']}")
    print(f"[{INST}] BASELINE (test_patch only)...")
    base = run_leg(client, row, image_id, apply_gold=False)
    print(f"[{INST}] baseline: {json.dumps(base)}")
    print(f"[{INST}] GOLD (test_patch + gold patch)...")
    gold = run_leg(client, row, image_id, apply_gold=True)
    print(f"[{INST}] gold: {json.dumps(gold)}")

    # G0 smoke assertions
    checks = {
        "image_pulled": bool(base.get("digest") or gold.get("digest")),
        "baseline_bug_present": base["resolved"] is False and base.get("f2p_all_passed") is not True,
        "gold_resolved": gold["resolved"] is True,
    }
    result = {"instance_id": INST, "language": row["language"], "repo": row["repo"],
              "image": f"ghcr.io/timesler/swe-polybench.eval.x86_64.{INST.lower()}:latest",
              "image_digest": gold.get("digest") or base.get("digest"),
              "baseline": base, "gold": gold, "checks": checks,
              "smoke_pass": all(checks.values())}
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[{INST}] CHECKS: {json.dumps(checks)}  SMOKE_PASS={result['smoke_pass']}")
    sys.exit(0 if result["smoke_pass"] else 1)


if __name__ == "__main__":
    main()
