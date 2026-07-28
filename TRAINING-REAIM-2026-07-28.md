# Re-aiming the training loop — what the data actually says

All numbers below are measured against the real archive (687 failing plans,
195 passing) on 2026-07-28. Nothing here is estimated.

---

## 1. The current target is partly aimed at nothing

`solve_explicit_plan` walks the relationship graph and **recomputes every
item's `x`/`z` from its relation**. The schema forces exactly one relation per
item, so every position is solver-derived. The model's coordinates never
survive.

The training target still contains `x`, `z` and `rotation_deg` for every item —
about **8% of each target** teaching numbers the pipeline immediately
overwrites.

---

## 2. Post-hoc geometry repair cannot save these plans

Three separate deterministic repairs, each measured on all 687 failures:

| approach | rescued | note |
|---|---|---|
| nudge repair (0.3 m cap) | 48 / 664 (7%) | current shipped behaviour |
| nudge repair (2.5 m, 8 passes) | 91 / 664 (14%) | plateaus — bigger moves stop helping |
| sampling placement search | 109 / 686 (16%) | nearest-first spiral, validator as objective |
| auto-distribute repeated items | 9 / 687 (1.3%) | only 127 plans even had repeats |

REST3D reports 93–96% for constrained optimisation. We reach 16%. **The gap is
not the search algorithm.** These layouts are wrong in ways geometry cannot
repair.

Two hypotheses tested and **rejected**:

- *Rooms are over-stuffed* — no. Failing plans use a median of **25% of the
  floor with 6 items**. Only 2% are genuinely impossible.
- *Clearance padding inflates footprints* — no. **100%** of overlapping pairs
  genuinely intersect; zero are clearance-only artefacts.

---

## 3. The failures concentrate in specific relation kinds

Relation mix, passing vs failing plans:

| relation | passing | failing | |
|---|---|---|---|
| `adjacent_to` | 5.3% | **17.6%** | **3.3× over-represented in failures** |
| `centered` | 15.0% | 22.2% | |
| `above` | 13.7% | 17.0% | |
| `against_wall` | 31.4% | 22.3% | |
| `south_of` | **20.4%** | 8.5% | **the relation that works** |

Each blocker attributed to the relation that placed the offending item:

| count | relation → failure |
|---|---|
| 555 | `centered` → overlap |
| 415 | `against_wall` → blocks a door/window |
| 401 | `adjacent_to` → out of bounds |
| 332 | `against_wall` → overlap |
| 330 | `adjacent_to` → overlap |
| 310 | `above` → overlap |

These are **three distinct problems with three different owners.**

---

## 4. Owner A — solver defects (deterministic, no training)

**`against_wall` ignores openings.** The solver places an item flat against the
named wall and never checks the door/window keep-clear volumes, even though
`_opening_volumes()` already computes them. 415 blockers. Fix: slide along the
wall to the nearest clear span.

**`adjacent_to` chains walk out of the room.** The solver implements it as
"immediately east of", so `a adjacent_to b adjacent_to c` marches east until it
exits the room; the bounds clamp then squashes them into each other. That is
401 out-of-bounds *plus* 330 overlaps from the same cause.

Neither needs a model. Both are bounded, testable changes.

## 5. Owner B — a bad default I introduced (fix first)

My relation reconciler synthesises `centered` for any item left without a
placement. `centered` with no offsets places an item at the room's exact
centre, so every synthesised item lands on the same spot.

| centered relations | count | overlapping |
|---|---|---|
| written by the model | 539 | 278 (52%) |
| **synthesised by my reconciler** | **430** | **277 (64%)** |

My placeholder overlaps *more often than the model's own choices*, and it
contributed 430 of the 969 centered relations in the failing set. **This made
the single largest blocker class worse.** It must be changed before any
training run consumes more of this corpus — either assign a free wall slot, or
decline to synthesise and mark the row untrainable rather than poison it.

## 6. Owner C — the actual training target

The signal that separates a passing plan from a failing one is **which relation
kind the model chooses**: `south_of` 20.4% in passing vs 8.5% in failing;
`adjacent_to` 5.3% vs 17.6%. A model that reaches for `south_of` where it means
"in front of" produces legal layouts; one that reaches for `adjacent_to`
produces chains that leave the room.

That is a **lexical/semantic choice**, not spatial arithmetic — exactly what
fine-tuning teaches well, and exactly what the current coordinate-predicting
target does not teach at all.

**Proposed target change:**

1. Drop `x`, `z`, `rotation_deg` from what the model is graded on.
2. Keep relations, dimensions, openings, camera intent — what the solver reads.
3. Record failures against the *relation* that caused them, so the corpus
   teaches "`adjacent_to` in this situation is wrong", not "this layout failed".

---

## 7. Order of work

1. **Fix the synthesised-`centered` default** (Owner B) — it is actively
   degrading the corpus every hour the loop runs.
2. **Fix `against_wall` vs openings and `adjacent_to` chaining** (Owner A) —
   1,478 attributed blockers between them, no GPU required.
3. **Re-cut the training target** (Owner C) — same corpus, aimed at the
   decision that actually determines legality.
4. **Then measure**, at 150+ prompts per arm. A 30-prompt exam cannot see a
   10-point change; that is why four cycles read "about the same".

Items 1 and 2 are deterministic and verifiable offline against these same 687
plans. Nothing needs to be trained to know whether they worked.
