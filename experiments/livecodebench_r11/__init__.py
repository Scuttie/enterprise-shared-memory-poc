"""REALBENCH_LIVECODEBENCH_R11 — one widely-used public benchmark (LiveCodeBench code generation), minimal
causal controls (M0 no-memory / M1 relevant-plain / M2 shuffled-matched / M3 relevant-actionable; primary
M1-M2). Official evaluator, official full code-generation setting, temporal source<target partition by
contest_date. Endpoint: LIVEBENCH MAIN COMPLETE regardless of positive/null/negative. No benchmark ladder.
"""
EXPERIMENT_ID = "REALBENCH_LIVECODEBENCH_R11"
STATUS = "LIVEBENCH_MAIN_COMPLETE_NULL"  # H1 M1-M2=+0.009 p=1.0; track closed; no third benchmark
