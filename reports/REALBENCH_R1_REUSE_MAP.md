# REALBENCH-R1 — reuse map

§4 requires reusing exact prior MBPP code/manifests where compatible. Search results:
- The production repo (`Scuttie/enterprise-shared-memory-poc`) contains **no** MBPP / EvalPlus code
  (`grep -rils "mbpp\|evalplus\|get_mbpp" src/ benchmarks/` → none). Its benchmarks are the P5.x synthetic
  instruments only.
- The accessible colab working directories (`colab-memory-v8/v81/v9`) contain **no** MBPP / EvalPlus code
  (`grep -rils "get_mbpp_plus\|evalplus\|mbpp_serialize"` → none).
- The separate durable-memory research worktree is **not modified** (a standing constraint) and its ledgers
  are **not copied**.

**Conclusion:** no compatible prior MBPP code/manifest was available in the accessible repositories, so
REALBENCH-R1 is built directly on the **official EvalPlus package** (the authoritative source), not
reconstructed from paper prose. The official protocol properties required by §4 — source/target disjointness,
near-duplicate exclusion, full-function generation, sandboxed executable grading — are implemented against the
official dataset + evaluator and audited in `ci-realbench-adapter` / `ci-realbench-grader`.

Reused files/commits: none (documented absence). Built-fresh files: `experiments/realbench_r1/*`,
`configs/realbench_r1/*`, `artifacts/realbench_r1/*`.
