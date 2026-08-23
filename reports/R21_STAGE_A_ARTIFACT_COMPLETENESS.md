# R21 Stage A — Artifact Completeness (§1)

Isolated MemGovern checkout (a8456580); 4 GPT-4o(-mini) trajectory tarballs pulled via LFS (real objects). Each
tarball holds ONE `preds.json` (instance_id → model_patch) — the authoritative released predictions.

## Released prediction coverage vs published table
| Condition | Model (recovered) | Released preds | Non-empty | Instance dirs | Published successes | Recomputable? |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| GPT-4o baseline | openai/gpt-4o t=1.0 | 99 | 96 | 100 | 116 | **NO** (116 > 99) |
| GPT-4o MemGovern | openai/gpt-4o t=1.0 (dsv31t cfg) | 99 | 97 | 100 | 163 | **NO** (163 > 99) |
| GPT-4o-mini baseline | openai/gpt-4o-mini t=1.0 | 10 | 10 | 20 | 70 | **NO** (70 > 10) |
| GPT-4o-mini MemGovern | openai/gpt-4o-mini t=1.0 (dsv31t cfg) | 128 | 119 | 500 | 86 | maybe (128 ≥ 86) |

## Finding
The released trajectory artifacts are a **partial subset**, not the 500-instance runs behind the published table.
In **3 of 4 conditions the published success count EXCEEDS the number of released predictions** (e.g. GPT-4o
baseline claims 116 successes but only 99 predictions are released; mini baseline claims 70 from only 10). It is
therefore **impossible to recompute the published table (116/163/70/86 of 500) from the released artifacts** — the
data required does not exist in the release.

The mini-MemGovern tarball lists 500 instance directories but contains only 128 non-empty predictions (the rest are
empty/absent), so even it does not carry a full 500-prediction run.

## Consequence (§1 hard stop → verdict)
Per §1, missing task manifests / predictions that cannot support the published denominators are a hard stop for
"verifying the published table". **Primary Stage-A verdict: `AUTHOR_ARTIFACT_UNAVAILABLE`** — the released
artifacts are insufficient to reproduce the published SWE-bench Verified table.

As a secondary, honest check (not a table verification), we still regrade the released predictions with the
official grader (`ci-r21-author-regrade`) to report the resolve rate ON THE RELEASED SUBSET.

## Recovered Stage-B config (from trajectory dir names, no model calls)
requested model `gpt-4o` / `gpt-4o-mini` (aliases — exact dated snapshot NOT in the string → RECOVERED_PARTIAL),
temperature `1.0` (RECOVERED_EXACT), top_p `None`, cost cap `$20`. MemGovern arms use the `dsv31t_agenticMemSearch_
1220_13w` config with the openai model overridden.
