---
inclusion: always
---

# Ollama Offload Policy

You (the primary GPT-5.6 agent) are the **orchestrator and judge**. To iterate faster,
delegate high-volume, low-judgment subtasks to local Ollama models via the `@ollama`
MCP tools, and spend your own turns only on decisions, cross-file reasoning, and
final validation.

**Bias: local-first, escalate.** Use fast local models by default; escalate hard,
ambiguous, or ship-critical cases back to yourself.

## How to call ollama
- **Text:** `ollama_generate` (single-shot) or `ollama_chat` (multi-turn).
  ALWAYS pass `format: "markdown"` — the default `json` format can return empty `{}`.
- **Vision:** `ollama_chat` with an `images` array (base64) and a vision model.
- **Extraction:** `ollama_generate` with `nuextract`.
- Keep each prompt **tight, single-purpose, and with an explicit output format**.
  Local models follow loose or multi-part instructions poorly — give them one job.

## Routing table
| Subtask | Tool + model | Notes |
|---|---|---|
| Summaries, log/error triage, commit messages, docstrings, changelog | `ollama_generate` + `llama3.1:latest` | fast, cheap |
| "Smart but cheap" drafts / light reasoning | `ollama_generate` + `gpt-oss:20b` | stronger, still local |
| Code boilerplate, test stubs, mechanical/repetitive refactors | `ollama_generate` + `qwen3-coder-next` (fall back to `gpt-oss:20b` if slow) | coder-tuned; you review before it lands |
| Pull JSON / fields / metrics out of text or tool output | `ollama_generate` + `nuextract` | give it the target schema |
| First-pass image / visual QA (Canon release loop) | `ollama_chat` + `qwen2.5vl:7b` (fallback `minicpm-v`) | see gate below |
| Embeddings / semantic | already handled locally by kirograph (`nomic-embed-text`) | don't re-implement |

## Do NOT offload — keep on yourself when:
- The task needs architecture decisions, cross-file reasoning, or judgment about correctness.
- The output would be committed or shipped **without review**. Treat every local-model
  output as a **draft** and validate it before it lands in code, config, or artifacts.
- The local model is uncertain, self-contradictory, or the vision gate returns borderline.

## Vision QA gate (Canon release loop)
For each generated candidate image:
1. Call `ollama_chat` with `qwen2.5vl:7b` and the Canon QA checklist
   (geometry, count, camera, opening, finish).
2. Require a strict JSON verdict: `{ "pass": bool, "failed_checks": [...], "confidence": 0-1 }`.
3. **Auto-accept only if `pass == true` and `confidence >= 0.8`.** Everything else
   escalates to you for adjudication. The local model is a screen, never the final
   judge on a release.

## Verification rule
Local models buy you cheap, unrate-limited grunt work — not unreviewed authority.
Anything that affects code, config, or shipped artifacts gets your sanity check.
