# Self-Learning Flywheel — toward a near-perfect scene→world model

## Overview

**North star (John, 2026-07-22):** the engine continuously learns from itself until a local
SLM/LLM is near-perfect at ONE task — converting a user's scene description into a walkable,
playable 3D world.

**Why this is credible, not hype:** this pipeline already contains the two hard parts of
self-training — a *generator* (the qualification loop mass-produces attempts) and a *free,
objective labeler* (the deterministic gates: validation, composition, alignment, parity,
runtime smoke). Attempts + verdicts = training data nobody has to hand-label. Text→typed-JSON
plan generation is exactly the narrow task small local models fine-tune well on.

**Prime guardrail:** the V11 MVP qualification (tasks.md 13.x) outranks everything here.
Only Phase F0 runs before `QUALIFIED.md` exists. Idle resources only — the loop preempts.

---

## Phases (each gated; never skip a gate)

### F0 · Corpus capture — START NOW (passive, zero GPU)
- A small extractor tool walks `output/qualification/*/v11-e2e.json` + session dirs and
  appends one JSONL record per trial to `data/flywheel/corpus.jsonl` (append-only):
  `{description, plan, world_contract?, per-gate verdicts, failure signatures, repair
  actions applied, model lane, source fingerprint, timestamps}`.
- Backfill everything already on disk tonight, then run at idle after each iteration.
- Honest inventory at design time: ~35 iterations, only ~2 accepted plans — the factory
  exists, the warehouse is nearly empty. Volume arrives as the loop runs at scale.

### F1 · Exemplar mining (after QUALIFIED.md; zero training)
- Mine the best gate-passing plans into few-shot exemplars for the V11 prompts.
- A/B through the existing lane ladder; keep only if measured pass-rate rises.

### F2 · Local LoRA fine-tune (gate: ≥500 accepted plans + ≥2,000 labeled rejections)
- LoRA on a small local base (llama3.1-8B / qwen-class) on the 4090, task-only:
  description → plan JSON. Rejected samples with signatures become contrastive data.
- Eval = gate pass-rate on a held-out prompt set, run through the normal trial machinery.
- The tuned model enters the lane ladder as a new rung; it must BEAT the incumbent lanes
  on pass-rate to be promoted (cheapest-rung discipline applies to our own model too).

### F3 · Dedicated SLM (only if F2 plateaus below target)
- Distillation + curriculum built from the signature taxonomy (hard-negative classes get
  oversampled). This is the end-state John described; do not start it on ambition alone —
  start it when F2's ceiling is measured and insufficient.

## External data lanes (John authorized web gathering, 2026-07-22)

- **L2 · Web datasets → local deep-dive repo** at `data/research-corpus/<source>/` with a
  mandatory per-source `LICENSE-NOTES.md`. Candidates to evaluate first: 3D-FRONT,
  Structured3D, HyperSim, SceneScript-style scene-language corpora, floor-plan datasets.
  **Rule: every download is proposed to John with source, size, and license BEFORE
  fetching** (constitution). Conversion into description→plan training pairs happens
  locally (AnythingLLM/qwen lanes), and converted pairs are gate-validated before they
  may enter the training corpus — web data never bypasses the labeler.
- **L3 · Play traces (later):** a Play-QA-style agent plays finished worlds (spawn, roam,
  collide, doors) and its traces label *playability* — the quality the geometry gates
  can't see. Feeds F2/F3 as preference/reward data. Borrow the pattern from the
  play-game-test-suite already proven on the CEO-3D-World project.

## Idle-GPU scheduler rules
1. Idle = watch loop quiet >10 min AND no ComfyUI model download AND no active agent turn.
2. Idle jobs (extraction, conversion, later LoRA) log to `data/flywheel/idle-jobs.log`
   and MUST yield within seconds when the loop wakes — the Ratchet always has the GPU.
3. Nothing here ever edits pipeline code or evidence; the flywheel only reads evidence
   and writes its own corpus files.

## Ownership
- Kiro: implement the F0 extractor + idle trigger now (small, isolated); F1+ blocked on
  `QUALIFIED.md`.
- Claude (Cowork): dataset scouting via AnythingLLM research lane; license verification;
  download proposals to John; corpus audits (offloaded-model output verified before it
  enters any ledger, per constitution).

## Architecture

The qualification Ratchet is the producer and deterministic labeler. F0 reads immutable trial and session evidence, normalizes it into an append-only local corpus, and yields whenever qualification resumes. F1–F3 consume only gate-qualified records and remain disabled until their phase gates are met. External datasets and play traces enter through separate provenance-preserving lanes and never bypass deterministic validation.

The dependency direction is one-way: qualification evidence → corpus capture → exemplar mining → local training → lane evaluation. Flywheel jobs never mutate qualification evidence, approved plans, WorldContracts, pipeline source, or release state.

## Components and Interfaces

- **Qualification evidence reader (`tools/flywheel_corpus.py`):** discovers completed trial results and their bound session artifacts using root-scoped paths.
- **Corpus writer:** appends deduplicated records to `data/flywheel/corpus.jsonl` and never rewrites accepted history.
- **Idle scheduler (`tools/e2e_qualification.py`):** starts F0 only after the quiet threshold and supplies a preemption callback for source, agent, or qualification activity.
- **Briefing job (`tools/qualification_briefing.py`):** produces evidence-cited, explicitly unverified summaries and non-applied local patch drafts; model failure must degrade to deterministic fallback text.
- **Lane evaluator:** uses the existing Ratchet lane configuration, fresh sessions, and deterministic gates to compare incumbents, exemplars, or tuned models.
- **External-data intake:** requires source, license, size, and local validation metadata before any converted record can enter a training corpus.

## Data Models

The F0 corpus is JSONL with one immutable record per fresh trial. Each record contains the source description, typed Plan, optional WorldContract, per-gate verdicts, stable failure signatures, applied repair metadata, model lane, source fingerprint, evidence paths, and timestamps. A deterministic identity derived from source evidence prevents duplicate appends.

Idle-job records are JSONL events containing job name, status, counts, duration, timestamp, and error totals. Later-phase datasets must additionally bind provenance, license metadata, split identity, transformation version, and deterministic gate results. Generated briefings and patch drafts are advisory artifacts, not corpus truth or release evidence.

## Correctness Properties

### Property 1: Append-only evidence

An existing corpus record is never modified or deleted by extraction.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

### Property 2: Deterministic deduplication

The same trial evidence cannot produce more than one corpus record.

**Validates: Requirements 9.1, 10.1**

### Property 3: Provenance completeness

Every record resolves to its trial/session evidence and source fingerprint.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

### Property 4: Fail-closed promotion

No exemplar or tuned lane is promoted without passing the existing deterministic gates on fresh sessions.

**Validates: Requirements 10.1, 10.2, 10.3**

### Property 5: Phase ordering

F1+ cannot run before `output/qualification/QUALIFIED.md` exists and its additional data thresholds are met.

**Validates: Requirements 10.1, 10.2**

### Property 6: Qualification priority

Active qualification, source changes, model downloads, or agent activity preempt flywheel work within seconds.

**Validates: Requirements 10.1, 10.2, 11.5**

### Property 7: Authority isolation

Flywheel jobs cannot edit pipeline code, qualification evidence, approved Plan data, or WorldContract state.

**Validates: Requirements 1.2, 2.5, 9.4**

## Error Handling

Missing, malformed, or incomplete evidence is skipped with a structured error count and log entry; it is never converted into synthetic success data. Interrupted extraction leaves previously appended JSONL records valid and resumes through deduplication. Local-model unavailability, timeout, or invalid output produces an explicitly labeled fallback briefing or `NEEDS-JUDGMENT` draft and never blocks the Ratchet. External data with unknown or unacceptable licensing is quarantined until John approves a documented intake proposal.

## Testing Strategy

- Unit-test root-scoped discovery, schema extraction, stable identities, deduplication, append-only writes, and malformed-evidence handling.
- Test idle-threshold activation and immediate preemption for source changes, agent activity, qualification ownership, and model downloads.
- Test briefing model failures, timeouts, Unicode output, evidence citations, atomic writes, and the guarantee that drafts are never applied automatically.
- Run deterministic Tier 0 and mock Tier 1 after implementation changes, followed by the full test suite and static checks.
- Evaluate F1–F3 only with held-out prompts, fresh sessions, existing lane caps, and measured gate pass rates; never use training examples as release evidence.