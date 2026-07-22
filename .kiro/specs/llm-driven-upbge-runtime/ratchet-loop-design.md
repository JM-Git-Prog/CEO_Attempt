# The Ratchet Loop — design for the single most efficient long-running qualification test

**Status:** DESIGN — approved for implementation as the sharpened form of subtask 13.5.2.
**Owner:** Kiro implements; John approves spend gates.
**Prime directive:** every hour of loop time must either (a) prove a code defect with a deterministic repro, or (b) tighten the statistical estimate of the stochastic pass rate. Anything else is waste.

---

## 1. Objective and done-check

**Objective:** reach one clean, fresh-session, canonical-prompt V11 pass (task 13.3–13.6) in the minimum wall-clock time, while letting Kiro change code between iterations safely.

**Done-check for the loop itself:** `python tools/ratchet_loop.py --watch` runs unattended for hours; on every source change it re-verifies in tiers; it maintains `output/qualification/scoreboard.json` and `output/qualification/NEXT.md`; when the best lane's rolling pass rate crosses threshold it automatically runs the formal serialized qualification pass; on green it writes `QUALIFIED.md` and stops. A failed formal pass returns to sampling. No session is ever reused. Evidence stays append-only.

**Done-check for the product (unchanged, from tasks.md 13.3):** one brand-new empty session on the exact target commit passes Brief → Plan → Blockout → Canon → World → parity → runtime → QA → downloads, cleanly.

---

## 2. What the evidence says today (2026-07-22, last 12 iterations)

- Deterministic prefix (compileall, node-check, tests) is green except when a mid-edit landed broken code (3 of 12 runs — that is Kiro-thrash the loop must catch cheaper).
- All other failures are the two stochastic stages: **plan** (validation/composition rejects the model's layout — 6 of 12) and **canon** (camera-alignment gate — 3 of 12); one deep run failed the whole world chain after canon.
- Full iteration costs 60–170 s; the deterministic prefix ~27–30 s of that; E2E 30–145 s.
- **Pass rate at current fingerprint: 0/12.** One sample per code state — so Kiro cannot tell a helpful fix from a lucky/unlucky roll. This is the core inefficiency the Ratchet fixes.

Two measured defects in the current harness worth fixing on day one:

1. `_focused_tests()` lists several filenames that do not exist (`test_compiler_manifest.py`, `test_upbge_capability.py`, `test_export_adapters.py`, `test_structural_parity.py`, `test_runtime_smoke.py`, `test_glb_reload.py`, `test_qa_evidence.py` — actual files are named differently, e.g. `*_module.py`, `test_upbge_capabilities.py`). The list silently filters to whatever exists, then the full suite runs anyway. **Delete the focused pass; run the full suite once.** Saves ~13 s/iteration and removes false confidence.
2. One E2E sample per iteration, no aggregation across iterations, no failure taxonomy. Fixed by Tiers 2–3 below.

---

## 3. Architecture — one loop, three tiers, then the formal exam

```
source change detected (fingerprint + debounce, as today)
        │
   TIER 0 — Determinism gate (~15 s, CPU only)
   compileall · node --check · full pytest suite
   FAIL → NEXT.md: "code defect, here is the test output" · stop tier ladder
        │ pass
   TIER 1 — Mock E2E (~seconds, CPU only, fully deterministic)
   fresh session · mock LLM · mock canon provider
   Proves the entire plumbing end-to-end with zero dice.
   FAIL → always a real code defect with a deterministic repro · stop ladder
        │ pass
   TIER 2 — Stochastic sampling (GPU, parallel lanes)
   N fresh-session real-model trials per lane, scheduler-parallel
   Updates scoreboard: per-stage pass rates + failure signatures
        │ best lane rolling pass rate ≥ threshold (default 0.8 over last 10)
   TIER 3 — Formal qualification (serial, single, exactly today's adapter)
   Green → QUALIFIED.md, stage files per 13.6 (no commit), STOP
   Red  → its failure feeds the scoreboard, back to Tier 2
```

Design rules carried over from the existing loop (keep them): source fingerprinting, stale detection, ProcessLock, sanitized env, atomic writes, append-only `events.jsonl`, per-iteration immutable directories, no session reuse ever.

### Tier 1 wiring (verified against current source)

- LLM: `generate_json` falls back to `mock_generate` when Ollama and the OpenAI-compatible URL are unreachable — so `OLLAMA_URL=http://127.0.0.1:9` (dead port) + empty `OPENAI_API_URL` forces the deterministic mock. No code change.
- Canon: `COMFYUI_ENABLED=0` + empty `IMAGE_API_URL` forces the labelled mock image; a `provider_policy: mock_only` stage profile also exists. No code change.
- **Open item for Kiro:** the canon **camera-alignment gate** may legitimately reject the mock image. If it does, add a narrow, explicit bypass: when the canon provider is the mock, record alignment as `not_applicable` — never loosen the gate for real images. This is the only code change Tier 1 is allowed to make to product code.

### Tier 2 — the heart of the design

**Trials are independent fresh sessions, so they parallelize.** A small scheduler runs `K` workers (default **K=2**; raise only after measuring VRAM headroom on the 4090). Each worker: create fresh session → run the adapter stages → record per-stage outcome. While one trial's canon render holds the GPU (ComfyUI queues internally), other trials' plan/validation stages run on CPU — the pipeline overlap is where the speedup comes from, roughly 2–3× trials/hour without oversubscribing VRAM.

**Lanes.** A lane = a named model configuration for the stochastic stages, e.g.:

| Lane | Planner (`LLM_MODEL`) | Cost | Enabled |
|---|---|---|---|
| `local-llama31` | `llama3.1` via Ollama | $0 | default ON |
| `local-qwen` | e.g. `qwen2.5-coder` or other local | $0 | ON when pulled |
| `remote-<name>` | any OpenAI-compatible endpoint (`OPENAI_API_URL`) | **$** | **OFF — spend-gated** |

The stack already supports remote via `OPENAI_API_URL`/`OPENAI_API_KEY`, so remote lanes are config-only. **Hard rule (John's constitution): remote lanes ship disabled; enabling one requires showing John the per-trial and per-batch cost estimate and getting explicit approval, and the loop enforces a per-run dollar/request cap.** Local lanes are free and always allowed.

Lanes answer the decisive question cheaply: *is the remaining failure a code/prompt problem, or is the local model simply too weak?* If a stronger lane passes at high rate on the same fingerprint while `local-llama31` fails, the wall is the model — stop burning days on prompt surgery. Record per-lane winners; never re-test a settled lane (cheapest-rung rule).

**Sampling policy.** Per fingerprint per lane, run trials until either `N=5` trials complete or an early-stop triggers (all 5 pass → estimate high; first 3 all fail with the *same signature* → estimate low, move on). The scoreboard keeps a rolling window (last 10 trials per lane across fingerprints that share the failing stage's code paths — simplest correct version: rolling per lane per fingerprint only).

**Failure signatures.** Normalize every failure to `stage / rule / detail`, e.g. `plan/composition/item_out_of_bounds:sofa`, `canon/camera_alignment/yaw_drift`, `world/parity/count_mismatch:stool`. Signature = the dedup key. The scoreboard counts signatures so `NEXT.md` can say "7 of last 9 plan failures are the same bounds clamp on wall-adjacent items" instead of "plan failed again."

### Scoreboard and the ratchet rule

`scoreboard.json` (atomic-rewrite, backed by append-only events):

```json
{
  "best": {"fingerprint": "…", "lane": "local-llama31", "pass_rate": 0.6, "trials": 10},
  "current": {
    "fingerprint": "…",
    "tiers": {"t0": "pass", "t1": "pass"},
    "lanes": {
      "local-llama31": {
        "trials": 5, "passes": 2,
        "stage_pass": {"plan": 0.6, "canon": 0.75, "world": 1.0},
        "top_signatures": [["plan/composition/item_out_of_bounds:sofa", 3]]
      }
    }
  },
  "verdict": "KEEP | REVERT | INDETERMINATE"
}
```

**Ratchet rule (what "allowed to change code" means):** a source change is **KEEP** only if Tier 0 and Tier 1 pass AND its best-lane pass rate is not worse than `best` (small samples round toward INDETERMINATE, which requests more trials, not a revert). A change that fails Tier 0/1 is an immediate **REVERT** verdict in `NEXT.md`. The loop never edits code itself — Kiro does — but the verdict is computed for it, which is what prevents the thrash visible in today's 19:51–19:54 evidence (broken code landed twice mid-loop).

### NEXT.md — the single feedback artifact Kiro reads

Rewritten every iteration, ~20 lines, always the same shape: current fingerprint · tier results · per-lane pass rates vs best · **top failure signature with direct paths to its evidence files** · the one recommended next action (fix X / revert / more trials / enable lane / trigger formal pass). Kiro should not need to dig through run directories to know what to do.

### Stop conditions (a long-running loop must know when to stop)

1. **QUALIFIED** — formal pass green. Write `QUALIFIED.md`, stage per 13.6, stop. Never auto-commit.
2. **STUCK** — same failure signature ≥5 consecutive trials with no source change → write an escalation packet (signature, evidence paths, tried-fixes list from scoreboard history) and pause the GPU tiers; keep Tier 0/1 watch alive. Do not silently burn GPU forever (constitution: no silent retries of expensive operations).
3. **BUDGET** — wall-clock budget (`--budget-hours`, default 8) or remote-lane cap reached → summary + pause, same as STUCK.
4. **GPU-BUSY guard** — before any canon render, check ComfyUI isn't mid-model-download (constitution rule); if busy, hold Tier 2, keep Tier 0/1 responsive.

---

## 4. What this is NOT (minimum-code discipline)

- Not a rewrite: `ratchet_loop.py` wraps and extends `e2e_qualification.py` + `v11_e2e_adapter.py`; the formal Tier 3 pass IS today's adapter, unchanged, run serially.
- No model fine-tuning, no training pipeline. "Faster" here = more independent evidence per hour, so Kiro's fix-verify cycle converges faster. (Optional later: mine the failure corpus for few-shot repair examples in the V11 prompts — separate task, not this loop.)
- No new dashboards/UI. `NEXT.md` + `scoreboard.json` + existing report.md files only.
- No parallelism in Tier 3. Release evidence stays serialized, fresh, single.
- No loosened gates. Tier 1's mock-alignment `not_applicable` is the only permitted gate change, and only for the labelled mock provider.

## 5. Implementation order for Kiro (each step lands green through the existing loop)

1. Drop the phantom focused-tests pass; full suite only. (Tier 0 correct + faster.)
2. Add Tier 1 mock E2E as a command in `command_plan` (env-forced mock; alignment `not_applicable` fix only if proven necessary by a red mock run).
3. Add failure-signature normalization into the adapter result (`stage/rule/detail`).
4. Add `scoreboard.json` + `NEXT.md` writers keyed by fingerprint × lane.
5. Add the Tier 2 trial scheduler (K workers, N=5 policy, early-stop, GPU-busy guard).
6. Add lanes config (`lanes.json`: name → env overrides; remote lanes `"enabled": false` + cap fields).
7. Add the Tier 3 trigger + STUCK/BUDGET stops + `QUALIFIED.md`.

Steps 1–4 alone already convert the loop from "one noisy sample per change" to "statistically meaningful verdict per change" — implement in that order so value lands even if later steps wait.

## 6. Honest limits

- Pass-rate thresholds (0.8/last-10, N=5, K=2, stuck=5) are engineering defaults, not measured optima — tune against reality.
- The 2–3× parallel throughput estimate is reasoned from stage timings in today's evidence, not yet measured; VRAM on the 4090 (planner + qwen2.5vl vision + FLUX simultaneously) is the real ceiling — measure before raising K.
- Whether Tier 1 needs the alignment `not_applicable` change is unverified until the first mock run.
- If every local lane plateaus well below threshold, the finding is "the local model is the ceiling" — that decision (bigger local model vs. spend-gated remote lane for the one clean pass) belongs to John, and the scoreboard will state it plainly.
