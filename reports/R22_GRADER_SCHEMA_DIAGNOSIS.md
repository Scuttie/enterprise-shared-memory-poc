# R22 §1 — corrected grader diagnosis (KeyError:'image')

## Previous wording (too strong — retracted)
> "swebench 5.0.2 internal KeyError:'image' in the Python image-spec path."

## Corrected diagnosis
swebench 5.0.2 received a dataset row **without the required `image` field**. The previous router used the
**legacy `princeton-nlp/*`** Lite/Verified dataset IDs, whose rows do **not** carry the enriched evaluation schema
(`image`, `eval_script`, `log_parser`, `eval_type`) that swebench 5.0.2 expects. The current official
**`SWE-bench/*`** datasets provide that enriched schema. This was a **dataset/harness schema-compatibility issue**,
not a fundamental harness defect.

Evidence: the 9 Multilingual instances (routed to the enriched `SWE-bench/SWE-bench_Multilingual`) graded correctly
in the prior run, while only the 3 python instances (routed to legacy `princeton-nlp/*`) hit `KeyError:'image'`.
The enriched `SWE-bench/SWE-bench_Verified` (rev `78f471bf`) and `_Lite` (rev `b0dde109`) both carry a non-empty
`image` field for these instances (verified). The mixed grader is re-run against the enriched datasets before any
"defect" conclusion; only if the enriched rerun still fails is a harness defect declared
(`R22_SWEBENCH_5_0_2_REPRODUCIBLE_DEFECT`).
