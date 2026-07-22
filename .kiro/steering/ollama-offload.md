---
inclusion: always
---

# Ollama Offload Policy

You (the primary GPT-5.6 agent) are the **orchestrator and judge**. To iterate faster,
delegate high-volume, low-judgment subtasks to appropriate Ollama models via the
`@ollama` MCP tools, and spend your own turns on decisions, cross-file reasoning,
integration, and final validation.

**Bias: local-first, escalate.** Use fast local models by default. Use a cloud model
only when the user explicitly requests cloud offload, and escalate hard, ambiguous,
or ship-critical decisions back to yourself.

## How to call ollama
- **Text:** `ollama_generate` (single-shot) or `ollama_chat` (multi-turn).
  ALWAYS pass `format: "markdown"` — the default `json` format can return empty `{}`.
- **Vision:** `ollama_chat` with an `images` array (base64) and a vision model.
- **Extraction:** `ollama_generate` with `nuextract`.
- **Cloud coding:** when explicitly requested, use `ollama_generate` or `ollama_chat`
  with `glm-5.2:cloud` and the same bounded-prompt discipline.
- Keep each prompt **tight, single-purpose, and with an explicit output format**.
  Ollama models follow loose or multi-part instructions poorly — give them one job.

## Routing table
| Subtask | Tool + model | Notes |
|---|---|---|
| Summaries, log/error triage, commit messages, docstrings, changelog | `ollama_generate` + `llama3.1:latest` | fast, cheap |
| "Smart but cheap" drafts / light reasoning | `ollama_generate` + `gpt-oss:20b` | stronger, still local |
| Explicit cloud coding draft or bounded complex implementation | `ollama_generate` or `ollama_chat` + `glm-5.2:cloud` | only when the user says "use GLM" or "cloud offload"; review before integration |
| Code boilerplate, test stubs, mechanical/repetitive refactors | `ollama_generate` + `qwen3-coder-next` (fall back to `gpt-oss:20b` if slow) | coder-tuned; you review before it lands |
| Pull JSON / fields / metrics out of text or tool output | `ollama_generate` + `nuextract` | give it the target schema |
| First-pass image / visual QA (Canon release loop) | `ollama_chat` + `qwen2.5vl:7b` (fallback `minicpm-v`) | see gate below |
| Embeddings / semantic | already handled locally by kirograph (`nomic-embed-text`) | don't re-implement |

## Explicit GLM cloud offload
- Trigger cloud use only when the user says **"use GLM"**, **"cloud offload"**, or
  otherwise explicitly requests `glm-5.2:cloud` for the current task.
- Explain the bounded subtask in one prompt and request a concrete output format such
  as a patch, function, review findings, or implementation draft.
- Send only the minimum task-relevant context. Never send secrets, credentials, API
  keys, private user data, proprietary datasets, repository archives, or unrelated files.
- Treat cloud output as an untrusted draft: review it, adapt it to repository conventions,
  and validate the integrated result locally.
- If the cloud call fails, continue with the appropriate local model or handle the task
  directly; do not weaken privacy or validation rules to make the call succeed.

## Do NOT offload — keep on yourself when:
- The task needs architecture decisions, cross-file reasoning, or judgment about correctness.
- The output would be committed or shipped **without review**. Treat every Ollama-model
  output as a **draft** and validate it before it lands in code, config, or artifacts.
- The delegated model is uncertain, self-contradictory, or the vision gate returns borderline.

## Vision QA gate (Canon release loop)
For each generated candidate image:
1. Call `ollama_chat` with `qwen2.5vl:7b` and the Canon QA checklist
   (geometry, count, camera, opening, finish).
2. Require a strict JSON verdict: `{ "pass": bool, "failed_checks": [...], "confidence": 0-1 }`.
3. **Auto-accept only if `pass == true` and `confidence >= 0.8`.** Everything else
   escalates to you for adjudication. The local model is a screen, never the final
   judge on a release.

## Verification rule
Ollama models provide drafting capacity, not unreviewed authority. Anything that affects
code, config, or shipped artifacts gets your sanity check and the most relevant available
validation. Cloud availability or model confidence never substitutes for validation.
