# R5-A0 — Solar Reader Integration (finding + fork)

Establishing the R5 reader (Solar-pro2 repository-agent) through BenchFlow, before the A0 no-skill calibration.
All paid probes/smokes were on 1 task (dialogue-parser); no confirmatory arms were run.

## Solar reader capability — VERIFIED GOOD
Direct raw probes of Upstage Solar `solar-pro2-251215` at `https://api.upstage.ai/v1/chat/completions`:
| request | HTTP | result |
|---|---|---|
| plain completion | 200 | ok |
| + `tools` (function) | 200 | **correct `tool_calls: run_shell{"cmd":"ls"}`** |
| + `tool_choice: required` | 200 | tool_calls |
| + `stream: true` + tools | 200 | streamed tool_calls |
| + `parallel_tool_calls: true` | 200 | tool_calls |
| system msg + 6 tools + **28,258-token** prompt | 200 | ok |

**Solar supports OpenAI function-calling, streaming, parallel tool calls, and large (28k) contexts.** It is a
capable tool-using reader — this is NOT a Solar limitation.

## BenchFlow off-the-shelf agent matrix — none cleanly binds Solar
| agent | protocol | outcome with `--model openai/solar-pro2-251215` |
|---|---|---|
| claude-agent-acp (default) | acp / anthropic-messages | **rejects** — requires `anthropic-messages`; Solar is openai-completions |
| goose | acp (external) | **rc=127** — `goose: command not found` (external binary not installed) |
| openhands | acp | **ACP -32603** internal error (its own env/model config) |
| codex-acp | acp / openai | **"Failed to set model … ACP -32603"** — can't bind an arbitrary Upstage model |
| **deepagents** | acp / openai-compatible | **connects + delivers prompt**, then Solar returns **HTTP 500** on deepagents' single tool-augmented request → `end_turn, 0 tool calls` |

deepagents is the only agent that fully connects to Solar and sends the task prompt. Its request 500s Solar —
but every common request feature (tools, `tool_choice`, stream, `parallel_tool_calls`, 28k context, 6 tools +
system msg) returns 200 in isolation, so the 500 is idiosyncratic to deepagents' exact request shape (some field
/ message-history structure I did not replicate), not a Solar capability gap.

## The fork (needs a decision — real engineering effort)
A0 calibration (and thus the R5 main) is blocked only on the reader↔harness integration, not on Solar, the
benchmark, or the pool (audit PASS; oracle repro 30/31; pool = 30 frozen). Options:
1. **Build a minimal custom Solar repository-agent** (the §4 `SWESkillsHarnessAdapter`): a small tool-loop using
   Solar's verified clean tool-calling (run_shell/read/write inside the SkillsBench sandbox) + the official
   verifier. Full control over the request → avoids deepagents' 500. **Faithful to §4, but a real build**
   (agent loop + sandbox integration + BenchFlow verifier hookup).
2. **Debug deepagents' exact 500 trigger** (instrument/capture its request) — could be a one-line config fix or
   a rabbit hole; uncertain.
3. **Company harness/model** as the reader — the §14 replication path — but it is `PENDING_CONFIGURATION` (no
   manifest supplied; GLM not guessed).
4. **Pause R5** at the completed state: audit PASS + oracle repro 30/31 + **reader capability verified**; record
   the off-the-shelf-agent integration gap honestly and resume when a reader harness is settled.

**Recommendation:** Option 1 — Solar's tool-calling is verified working, so a minimal custom agent is the
faithful, controllable path; but it is meaningful engineering, so it needs an explicit go-ahead. No fabricated
results either way; no paid confirmatory arms until the reader is settled and the R5 preregistration is approved.
**P6 not started; R1–R4 frozen.**
