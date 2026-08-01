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
| Frontier-class cloud reasoning (user says "use Kimi K3") | `ollama_generate` or `ollama_chat` + `kimi-k3:cloud` | 2.8T MoE, 1M ctx, vision+reasoning+tools; extra usage credits required; treat as untrusted draft |
| Code boilerplate, test stubs, mechanical/repetitive refactors | `ollama_generate` + `qwen3-coder-next` (fall back to `gpt-oss:20b` if slow) | coder-tuned; you review before it lands |
| Large-scale cloud code generation (user says "use qwen3-coder cloud") | `ollama_generate` + `qwen3-coder:480b-cloud` | 480B params, 262K ctx; review before integration |
| Multi-modal reasoning with thinking (local, 26B) | `ollama_chat` + `gemma4:26b` | local, thinking+tools; good for complex local tasks |
| Vision + reasoning + thinking (local, 27B) | `ollama_chat` + `qwen3.6:27b` | local, 262K ctx, vision+thinking+tools; strong all-rounder |
| Pull JSON / fields / metrics out of text or tool output | `ollama_generate` + `nuextract` | give it the target schema |
| First-pass image / visual QA (Canon release loop) | `ollama_chat` + `qwen2.5vl:7b` (fallback `minicpm-v`, fallback `ibm/granite3.3-vision:2b`) | see gate below |
| Embeddings / semantic | already handled locally by kirograph (`nomic-embed-text`) | don't re-implement |

## Explicit cloud offload (GLM-5.2 / Kimi K3 / DeepSeek V4 / others)
- Trigger cloud use only when the user says **"use GLM"**, **"use Kimi K3"**,
  **"use DeepSeek"**, **"cloud offload"**, or otherwise explicitly requests a
  cloud model for the current task.
- Default cloud model: `glm-5.2:cloud` (general reasoning).
- Frontier cloud model: `kimi-k3:cloud` (2.8T MoE, 1M context, vision — use when
  the task needs maximum capability or very long context; costs extra credits).
- Code-heavy cloud: `qwen3-coder:480b-cloud` or `kimi-k2.7-code:cloud`.
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

---

## Validated Model Inventory (as of 2026-08-01)

### Local models (pulled, run on this machine)

| Model | Params | Quant | Context | Capabilities | Use for |
|---|---|---|---|---|---|
| `llama3.1:latest` | 8B | Q4_K_M | 131K | completion, tools | Fast summaries, triage, changelogs |
| `gpt-oss:20b` | 20.9B | MXFP4 | 131K | completion, tools, thinking | Smart-but-cheap drafts, light reasoning |
| `gemma4:26b` | 25.8B | Q4_K_M | — | completion, tools, thinking | Complex local reasoning w/ thinking |
| `qwen3.6:27b` | 27.8B | Q4_K_M | 262K | vision, completion, tools, thinking | All-rounder: vision + reasoning + tools |
| `qwen3-coder-next:latest` | 79.7B | Q4_K_M | 262K | completion, tools | Code boilerplate, test stubs, refactors |
| `qwen2.5vl:7b` | 8.3B | Q4_K_M | 128K | vision, completion | Primary vision QA |
| `minicpm-v:latest` | 7.6B | Q4_0 | 32K | completion, vision | Fallback vision QA |
| `ibm/granite3.3-vision:2b` | 2.5B | Q8_0 | 131K | completion, tools, vision | Ultra-light vision fallback |
| `nuextract:latest` | 3.8B | Q4_0 | 4K | completion | JSON/field extraction |
| `nomic-embed-text:latest` | 137M | F16 | 2K | embedding | Embeddings (kirograph) |
| `planner-probe-v1:latest` | 8B | Q4_K_M | 131K | completion | Custom planning probe (internal) |

### Cloud models (pulled references — inference on Ollama servers)

| Model | Params | Context | Capabilities | Subscription | Notes |
|---|---|---|---|---|---|
| `glm-5.2:cloud` | 756B | 1M | completion, tools, thinking | Pro/Max | Current default cloud offload |
| `qwen3-coder:480b-cloud` | 480B | 262K | completion, tools | Pro/Max | Cloud coder, large-scale generation |
| `deepseek-v3.1:671b-cloud` | 671B | 163K | completion, tools, thinking | Pro/Max | Strong reasoning alternative |
| `gpt-oss:120b-cloud` | 116.8B | 131K | completion, tools, thinking | Pro/Max | Mid-tier cloud option |

### Cloud models available (not yet pulled — `ollama run <name>` to add)

| Model | Params/Class | Context | Capabilities | Notes |
|---|---|---|---|---|
| `kimi-k3:cloud` | 2.8T MoE (104B active) | 1M | vision, reasoning, tools | Frontier-class; extra usage credits; released 2026-07-27 |
| `deepseek-v4-flash:cloud` | — | 1M | completion, tools, thinking | Fast DeepSeek v4 variant |
| `deepseek-v4-pro:cloud` | ~1.5TB | 1M | completion, tools, thinking | Full DeepSeek v4 |
| `kimi-k2.7-code:cloud` | — | 262K | vision, thinking, tools | Code-specialized Kimi |
| `kimi-k2.6:cloud` | — | 262K | vision, thinking, tools | Previous Kimi generation |
| `qwen3.5:397b-cloud` | 397B | 262K | completion, thinking, tools, vision | Qwen frontier |
| `nemotron-3-ultra:cloud` | 550B (55B active) | 262K | completion, thinking, tools | NVIDIA frontier MoE |
| `nemotron-3-super:cloud` | 120B (12B active) | 262K | completion, thinking, tools | NVIDIA mid-tier |
| `nemotron-3-nano:30b-cloud` | 30B (3B active) | 1M | completion, thinking, tools | NVIDIA lightweight, huge context |
| `minimax-m3:cloud` | — | 512K | completion, tools, thinking, vision | MiniMax frontier |
| `minimax-m2.7:cloud` | — | 196K | completion, tools, thinking | MiniMax mid-tier |
| `mistral-large-3:675b-cloud` | 675B | 262K | completion, tools, vision | Mistral flagship |
| `gemma4:31b-cloud` | 31B | 262K | completion, thinking, tools, vision | Google Gemma 4 |
| `glm-5.1:cloud` | — | 202K | thinking, completion, tools | Previous GLM generation |

### Quick reference: pulling a new cloud model

```bash
ollama run kimi-k3:cloud          # frontier reasoning, extra credits
ollama run deepseek-v4-pro:cloud  # strong reasoning alternative
ollama run nemotron-3-ultra:cloud # NVIDIA frontier
ollama run qwen3.5:397b-cloud    # Qwen frontier with vision
```

Cloud models run on Ollama's servers (Pro/Max subscription required). Some models
(notably `kimi-k3:cloud`) require additional usage credits beyond the subscription.

### Last validated: 2026-08-01 via `ollama list` + Ollama Cloud catalog cross-reference.
