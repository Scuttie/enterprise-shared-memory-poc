# R17 — DECODING (adaptation) of memory — preregistration

R14–R16 injected the related prior fix RAW and let the reader do the transfer; the "same-theme, different-file"
band (③) gained nothing → the reader does not bridge the analogy gap. R17 adds a DECODE step: a gpt-4o-mini call
rewrites the retrieved prior fix into guidance ADAPTED to the target issue (which files/functions/conditions it
likely maps to), then injects that instead of the raw diff. Reader = gpt-4o-2024-08-06 (mid-band 0.233), same
frozen main-60. The decoder sees ONLY the target issue text + the source example — never the target gold/tests.

## Arms
- **M1dec**: inject decode(target issue + relevant semantic prior fix). Reuses memory_M1_sem.json as the source.
- **D0 (matched control)**: inject decode(target issue ONLY, no memory) — a plan written from the issue alone.
  Same decode compute, no memory content. Isolates "extra planning" from "memory transfer".
- **M0** (reused from R16): gpt-4o, no memory, no decode.

## Endpoints (fixed in advance)
- **Primary H = M1dec − D0**: does the RELEVANT prior-fix content add value beyond equal-compute planning?
- Secondary: M1dec − M0 (decoded memory vs nothing). Exact McNemar + repo-cluster bootstrap. ITT. Null is final.
- Decision: "decoding revives transfer" iff M1dec − D0 > 0 with McNemar p < 0.05. Otherwise: decoding does not
  create transfer beyond generic planning (a valid final result). No leakage: decoder never reads target gold.
