# Experiment spec — what is proven, what is ruled out, what is still unknown

Mined 2026-07-29 from `CEO_Attempt` (bench/, tools/, .kiro/, .kirograph/, 532
results files, 546 qualification iterations) and `Artificial Intelligence`
(LEARNING-LEDGER.md, CLAUDE.md changelog, site-log.json, constitution-history,
verdict/debate docs).

Purpose: stop re-running experiments that already have answers, and name the
few that do not.

---

## 0. The four findings that matter most

1. **Only the repair family ever landed.** Spiral repair and near-miss nudge
   are in production. Every other placement strategy measured — sampling
   search, auto-distribute, grid assignment — is still a standalone script in
   `bench/`, including the one with the best number.

2. **The single most informative experiment has never been run.**
   `bench/grid_gen_bench.py` is fully written and has a self-test. No
   `results-GRIDGEN-*.json` exists anywhere. Every placement experiment so far
   *repairs layouts already built wrong*; this is the only one that asks the
   model to build them right.

3. **No model-side conclusion in this repo is currently defensible.**
   ~78% of all 5,313 bench rows are backend errors or timeouts, not task
   failures. The prompt experiment measured Ollama outages. The hyperparameter
   sweep never wrote a result. The fine-tune's apparent edge rests on n≈60 per
   arm with no significance test.

4. **Every solver number predates the 2026-07-28 fixes, and no run has been
   made since.** Commits `bbd97f8` (against_wall / adjacent_to),
   `ff74d8e` (synthesised-centered default) and `d197c81` (training target
   re-cut) all landed *after* the last measurement. Whether they moved the
   pass rate at all is unknown.

---

## 1. PROVEN — reuse, do not re-test

| # | Result | Evidence |
|---|---|---|
| P1 | **Spiral-search repair rescues 59 of 60** greedy-unsat contracts, 1–19 ms | `solver-proof-results.json`; shipped in `src/solver_repair.py`, wired at `pipeline.py:725` |
| P2 | **Near-miss nudge rescues 26.4%** of discarded plans (48/182), 0.6 ms mean; almost all `out_of_bounds` (42/48) | `repair-harvest-proof.json`; live in `plan_bench.py`, 49 corpus rows tagged |
| P3 | **Nudge cap 0.3 m is the right setting.** 1.5 m → 42%, but larger moves break the described layout | `nudge-sweep.txt` |
| P4 | **FOV was the binding camera constraint, not the search grid.** Pinned 55° provably stuck at −22 px; FOV free 50–62° accepted at +29.1 px in 0.7 s | 2026-07-23 sandbox proof |
| P5 | **Failure-signature taxonomy** — S1 rotation-aware boundary dominates; cascade marking inflates counts ~2× | `.kirograph/failure-signature-taxonomy-r1.md` |
| P6 | **Local Hunyuan3D on the 4090 replaces paid meshing** — a furnished room went from ~$1–2 to $0 | LEARNING-LEDGER 07-08 |
| P7 | **Octree 256 is law**; the only face lever is `VAEDecodeHunyuan3D.octree_resolution` | LEARNING-LEDGER 07-10 |
| P8 | **10-view paint with a 45° mid-elevation ring** fixes hallucinated roofs | LEARNING-LEDGER 07-10/07-19 |
| P9 | **Styled twins must be derived, never re-rendered** — derived alignment 17.1 vs 22.6 drift | LEARNING-LEDGER 07-15 |
| P10 | **ControlNet strength is the exaggeration dial**; Union promax @0.65 holds 12 elements class-stable | LEARNING-LEDGER 07-15 |
| P11 | **Paint Shop crash cure**: the four `--disable-*` flags together; 23.2 GB / 100% sustained after | LEARNING-LEDGER 07-19 |
| P12 | **Per-lane mask winners recorded so they are never retested** — SAM3 12 lanes, Qwen 0 | LEARNING-LEDGER 07-15 |
| P13 | **Live self-test harness** — 12 checks, catches schema drift before GPU spend | `selftest-report.json` |

## 2. RULED OUT — do not repeat

| # | Approach | Why it failed | Evidence |
|---|---|---|---|
| R1 | **Post-hoc geometry repair as *the* fix** | Hard ceiling: 13.7% at 1.5 m and **identical at 2.5 m** — extra budget buys nothing | `repair-ceiling.txt` |
| R2 | **Auto-distribute repeated items** | 9/687 = **1.3%**; only 127 plans even had repeats | `auto-distribute-proof.json` |
| R3 | **Sampling placement search** | 15.9% — barely above simple nudging | `placement-search-proof.json` |
| R4 | **"Rooms are over-stuffed"** | Failing plans use a median **25% of floor with 6 items**; only 2% exceed 75% | `occupancy.txt` |
| R5 | **"Clearance padding causes the overlaps"** | **414/414 (100%)** overlapping pairs genuinely intersect; zero clearance-only | `padding-analysis.txt` |
| R6 | **Prompt engineering as the lever** | control 1/15, explicit-math 0/15, self-check 0/15 — and mostly timeouts anyway | `prompt-experiment-summary-*.json` |
| R7 | **Synthesised `centered` placeholders** | Reconciler's own relations overlap **64%** vs the model's 52% — the fix was worse than the disease | `my-contribution.txt`; fixed in `ff74d8e` |
| R8 | **Box-inpaint at denoise 1.0** | Large holes obey the hole's shape, not the prompt | LEARNING-LEDGER 07-15 |
| R9 | **Restyle without a structure anchor** | Content mutated wholesale — trophies became framed pictures | LEARNING-LEDGER 07-15 |
| R10 | **Engine/harness as the blocker** | 102 of 136 failures are plan/brief stage; **not one signature names UPBGE, Godot, GLB or parity** | 2026-07-23 |
| R11 | **OmniX as the owned-model win** | Fine-tunes FLUX.1-dev (non-commercial); the Apache tag covers code only | 2026-07-17 |
| R12 | **The Ratchet qualification loop** | **106 trials, zero passes on any lane**; scoreboard verdict `REVERT`; 254 of 274 iterations never actually attempted E2E | `output/qualification/scoreboard.json` |
| R13 | **`--disable-dynamic-vram`** | No-op — needs PyTorch ≥2.8, shop runs 2.6.0 | 2026-07-28 |
| R14 | **PowerShell tee for the ComfyUI log** | UTF-16 → mojibake → UnicodeEncodeError; cp1252 stream unfixable by `PYTHONUTF8` | 2026-07-19 |

## 3. THE BEST UNTESTED IDEA

**Grid assignment produced the best number in the whole archive and was never
landed. Grid *generation* has never been run at all.**

| approach | legal | note |
|---|---|---|
| nudge repair | 14% | shipped |
| sampling search | 16% | not landed |
| auto-distribute | 1.3% | not landed |
| **grid assignment (0.75 m)** | **23.4%** | **not landed** |
| **grid generation** | **no data** | **script exists, never run** |

Grid assignment cut `physical_overlap` by **68%** (1870→594) and
`opening_blocked` by **52%** — but raised `camera_inside_geometry` by **22%**,
because the camera was never given a cell. That is a known, bounded defect.

All four rows above *repair layouts already built wrong*. The fifth asks the
model for cells from the start, which is a different question.

**Decisive experiment:** `RUN-GRID-EXPERIMENT.bat` — 30 prompts, ~20–40 min,
no training. Read against the ~25% coordinate baseline.

## 4. OPEN — genuinely unknown

| # | Question | Why it is open |
|---|---|---|
| O1 | Did the 07-28 solver fixes move the pass rate? | Every number predates them; no run since |
| O2 | Does grid-native generation beat coordinates? | Never run |
| O3 | Do the trained hyperparameters matter? | Sweep **never produced a result file**; live values (rank 16, alpha 16, lr 2e-4) are untested defaults |
| O4 | Does an accepted plan actually walk in the product? | **Not one accepted plan has ever raised a room at 5173** |
| O5 | Would capping `clearance_m` at 0.3 m help? | Would drop over-100%-footprint plans from 19% → 1%, but R5 shows it fixes no overlap. Untested end to end |
| O6 | Is the GPU lock sound? | Heartbeat can't tell a wedged client from a working one; first fix killed a healthy paint |

## 5. Corrections this sweep produced

**The dashboard under-reports comparisons.** I said all day that only *one*
real trained-vs-baseline comparison existed. **Five paired exams exist.**
`dashboard_gen.py::_scan_history` requires ≥20 prompts, an exact total match
and the literal `planner-probe-v1` lane, and silently drops the rest.

Excluding backend errors and timeouts (per the 2026-07-27 rule):

| date | llama3.1 | planner-probe-v1 |
|---|---|---|
| 07-24 | 6/21 = 29% | 7/20 = 35% |
| 07-25 | 9/20 = 45% | 8/18 = 44% |
| 07-25 | 8/22 = 36% | 9/20 = 45% |
| 07-26 | 30/30 errors | 9 errors + 21 timeouts |
| 07-28 | 1/22 = 5% | 20 timeouts |

Aggregate over the three usable runs: **base 23/63 = 36.5%, probe 24/58 =
41.4%** — about 5 points on n≈60 per arm, with no significance test. Better
than "about the same", still not evidence.

**And the harsher number:** on 45 rows it had never seen, the probe scored
**0/45**. The in-distribution 23% did not survive holdout.

**One unverified landing:** `bench/repair-landing-proof.txt` — the file that
was supposed to re-prove the shipped repair module — is **0 bytes**. P1's
landing was never re-verified.

## 6. Order of work this implies

1. **Re-run the bench** — O1. Every solver number is stale; the 07-28 fixes
   are unmeasured. Cheapest possible answer to the biggest unknown.
2. **Run `RUN-GRID-EXPERIMENT.bat`** — O2. The only experiment that tests the
   actual hypothesis rather than repairing its aftermath.
3. **Fix `_scan_history`** so the dashboard stops hiding four of five exams.
4. **Land grid assignment with the camera given a cell** — the +22% camera
   regression is the only thing between 23.4% and a shippable win.
5. **Stop trusting any model-side number** until the bench separates transport
   failures from task failures on every lane (the 07-27 rule is written but the
   archive predates it).

---

### Provenance

Family 1–6 experiment ledger and the qualification-loop figures were mined
directly from result files. The LEARNING-LEDGER sections on the prop factory,
render pipeline, GPU infrastructure and browser QA were partly summarised
through sub-sweeps and are flagged as second-hand by the agent that produced
them — spot-check any figure before building on it. No ADR-style decision
records exist in either tree; the `briefings/DECISION-DOSSIER-*` series is a
daily-briefing format and was not mined.
