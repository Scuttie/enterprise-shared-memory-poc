# R22 — SWE-Exp config audit (verified from code, not just the paper)

Source: `third_party_r22/swe-exp` @ `6b5c92ed0a6fc14de972c5d499673e2c4f03ce33`. Values below are read from the
pinned code and cross-checked against the paper's claimed values. File hashes are frozen in
`artifacts/r22/upstream/swe_exp_lock.json`.

| Item | Paper claim | Code (pinned) | Match |
| --- | --- | --- | --- |
| Policy model | DeepSeek-V3-0324 | `deepseek/deepseek-chat` (workflow.py:74) | PARTIAL — code uses the provider alias; the `-0324` snapshot resolves provider-side, not pinned in code |
| Policy temperature | 0.7 | 0.7 (workflow.py:74) | ✅ |
| Value / discriminator temp | — | 0.2 / 1.0 (workflow.py:75-76) | (extra detail) |
| Response format | — | REACT (workflow.py:78-80) | (code detail; `evaluation_config.py` also defines tool_call variants) |
| max_iterations | 20 | 20 (evaluation_config.py:14, README) | ✅ |
| max_expansions (MCTS) | — | 1 (evaluation_config.py:15) | (MCTS width) |
| max_finished_nodes | 2 | `main(max_finish_nodes=...)` param (workflow.py:73) | plumbed; paper value 2 |
| Embedding model | multilingual-e5-large-instruct | `intfloat/multilingual-e5-large-instruct` (select_agent.py:125) | ✅ |
| Selection / rerank | top_n 10 → rerank K 1 | e5 cosine `embeddings[:1] @ embeddings[1:].T` + LLM `select_perspective(k)` (select_agent.py) | mechanism ✅; top_n/K passed at call time |
| Experience agents | Instructor / Assistant | `Instructor` + `ExpAgent` (encode_perspective / encode_modify) + `SelectAgent` | ✅ (dual-agent) |
| Search actions | — | FindClass, FindFunction, FindCodeSnippet, SemanticSearch, ViewCode (workflow.py:97-101) | (tool set) |
| Baseline | SWE-Search 35.4% | `python workflow.py ... --max_iterations 20` (no `--experience`) | run recipe present |
| Memory arm | SWE-Exp 41.6% | `python workflow.py ... --experience --max_iterations 20` | run recipe present |
| Benchmark | SWE-bench Verified | SWE-bench Verified instance IDs via `--instance_ids` | ✅ |
| Grader | official | `moatless-testbeds` (Docker SWE-bench harness) | ✅ |

## Summary
The information structure of the positive reference is reproduced and frozen: dual-agent experience
encode/select over MCTS SWE-Search, e5 embedding selection + LLM rerank, DeepSeek policy at temp 0.7, 20 iterations,
official Docker grading. The only paper/code gap is the exact DeepSeek snapshot (`-0324`), which the code leaves to
the provider alias `deepseek/deepseek-chat`.
