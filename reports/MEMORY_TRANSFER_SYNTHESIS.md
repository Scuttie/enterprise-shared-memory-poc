# Memory-transfer synthesis (REALBENCH R14–R18): why "collective intelligence" does not transfer here

## The question
Does injecting another engineer's/problem's SOLVED memory causally help an LLM solve a NEW code problem, on a
well-known public benchmark (SWE-bench Verified), under clean controls (no gold leakage, ITT, exact grader,
preregistration, disjoint confirmation)?

## The answer: no reliable benefit — robust across five independent levers
gpt-4o-mini (~8% band) and gpt-4o (~23% band). One apparent n=60 positive (R14) failed a preregistered N=180
confirmation. Every subsequent lever aimed at the strongest counter-explanation returned null:
- **Encoding** raw worked-example (real prior issue + actual gold diff), not a distilled abstraction — null.
- **Retrieval** the product's own semantic embedder, relevance ↑3–4× over recency — null.
- **Reader** a mid-band gpt-4o that can actually use context — null.
- **Decoding** an explicit step adapting the memory to the target, with a matched planning control — null; the
  control showed the tiny residual was "think-first" compute, not transfer.
- **Unit** a SET of 5 related memories (true "collective" distribution), not one anecdote — null; a relevant set
  was indistinguishable from an irrelevant set.

Individual near-duplicate cases (same file, near-same bug) can flip (e.g. sphinx-8595), but they do not aggregate
and are offset by distraction losses; adding more memory trends slightly negative.

## Why — the mechanism
1. **The strategies are already in the weights.** A large pretrained LLM has internalized the general debugging
   strategy from millions of fixes. A prior fix teaches no new strategy — the LLM already IS the compressed
   collective intelligence of public code. Marginal value of one more colleague's memory ≈ 0.
2. **What gates the task is instance-specific grounding**, not transferable strategy: which exact lines in a large
   repo, this function's contract, what the hidden tests expect. A DIFFERENT bug's fix cannot supply this; only the
   target's own code/tests contain it. Memory gives what is already known and omits what is needed.
3. **The useful middle is thin.** Information is either already-known (redundant → no help) or must-be-given
   (necessary → "help" is tautological). Human-style analogical transfer — useful-but-not-decisive experience —
   is exactly the band that keeps coming up empty for current LLMs.

## Reconciliation with prior work
Methods that report memory gains operate where a real gap exists or the reused item is directly applicable:
Reflexion (same-task self-correction), Voyager (executable verified skills reused when applicable), ExpeL
(many examples distilled within a recurring distribution), RAG QA / repo-context (retrieval that CONTAINS the
answer or needed symbols). Generic "here is how someone fixed a different bug" fills no gap for a model that
already fixes bugs well. Our clean design also strips inflation (leakage, weak baselines, cherry-picking) that can
enlarge reported memory effects.

## Where memory SHOULD pay off (not tested-positive here, and partly explored before with band problems)
Knowledge OUTSIDE pretraining: private/org conventions, post-cutoff APIs, decisions recorded nowhere public — the
actual value proposition of an enterprise shared-memory system. SWE-bench (public, static, general Python bugs) is
close to the worst case for demonstrating memory value because it sits inside the pretraining distribution.

## Honest scope
Readers ≤ gpt-4o; per-arm n=60 (confirmation N=180); single-shot forced injection; one benchmark family. Not
closed: agent-initiated retrieval only when stuck (avoiding forced-injection distraction), and readers ≫ gpt-4o.
