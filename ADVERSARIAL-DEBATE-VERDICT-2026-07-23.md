# Adversarial Debate Verdict — Path v2

*2026-07-23. John's order: run the path through GLM-5.2 and Nemotron. Nemotron is not
installed (needs one `ollama pull` — deferred list); substitution disclosed: two GLM-5.2
sessions with orthogonal mandates — RED ENGINEER (technical correctness) and BLACK
SCHEDULER (sequencing/opportunity cost). Same weights ⇒ agreement is discounted unless
independently triangulated. Their outputs are unverified drafts; every adopted point below
was checked against repo evidence (Kiro's touch-point map, the mined experiment ledger)
before adoption. This document records the ruling; it changes no code by itself.*

## 1 · Where the critics landed hits (adopted)

1. **Solver inversion jumps the queue.** Red: "You're polishing a funnel that's blocked at
   the top" — every other item patches symptoms of *LLMs can't do geometry*. Black: cloud
   bake-off "selects the best of 5 wrong answers" if the ceiling is reasoning. Triangulated
   by independent evidence (76/136 failures at plan stage; 0% pass on every lane ever; the
   architecture window's own sandbox experiment). ADOPTED: inversion is W2's next surgery
   after the FOV fix closes — not gated on the bake-off verdict.
2. **The bridge is a PROBE, not a demo.** Black's sharpest point: walking ONE
   already-accepted contract in the 5173 app is the decisive experiment — if it walks,
   generation is fine and scoring/model choice matters; if it doesn't, geometry is the only
   critical path. ADOPTED, upgraded: build it **app-side** (5173 repo) so it causes ZERO
   fingerprint churn in CEO_Attempt — better than the isolated-branch idea.
3. **No injections into open surgery; batch the landings.** Black's churn math (~40 min of
   doomed free-rung trials per merge) is real. ADOPTED with modification: Kiro prepares
   diffs now (context already gathered) and lands them **batched with** W2's surgery close —
   one ladder reset instead of three.
4. **Don't copy Marble's wire format.** Red: FLUX depth ControlNets are trained on
   metric/inverse-depth (MiDaS-style), not Marble's log-radial house format. ADOPTED:
   borrow Marble's *discipline* (explicit bounds, empty-space sentinel), emit what OUR
   ControlNet expects, and extend the EXISTING renderer (it already computes per-item z)
   rather than building a second renderer. Verify exact expected encoding at implementation.
5. **Height-aware circulation + published weights.** Red: a flat 2D flood-fill false-fails
   chairs under tables and needs a weighting scheme. ADOPTED: mask only footprints that
   block a capsule at walking height; use Merrell's published mixture weights
   (w_clearance=2, w_circulation=1, w_alignment=2.5) instead of inventing tradeoffs.
6. **Capsule gate: dynamic, advisory-first.** Red: kinematic probes miss momentum/CCD
   failures — use a real Rapier dynamic capsule. Black: a gate that rejects 100% of a
   0%-pass pipeline is noise. ADOPTED: register as an ADVISORY compiler gate (evidence
   only — Kiro's safe route, no schema break); flips to blocking when pass rate > 0.
7. **Bridge scope: Three.js/5173 only.** Red: "100 lines" holds only for one target; door
   semantics differ per engine. ADOPTED — 5173 IS the product; UPBGE/Godot stay export rungs.
8. **Corpus-era tagging.** Black: pre-inversion training data may go stale. PARTIAL ADOPT:
   accepted CONTRACTS stay valid regardless of who computed coordinates; rejections are
   era-specific. Keep banking (free), tag records with pipeline era, stop watching the
   counter this week.

## 2 · Where the critics were wrong (rejected, with reasons)

1. **"DROP the cloud bake-off."** Both missed its cost structure: it is ALREADY armed and
   runs unattended at $0 marginal — killing it saves nothing. Demoted, not dropped: it no
   longer gates the inversion decision; it still crowns the cheapest capable
   meaning-emitter for the post-inversion era (the inversion still needs an LLM to choose
   templates/relations — cheapest-rung law applies).
2. **"Depth work is polish on a broken pipe."** Half-right on timing only. It targets the
   NEXT wall (canon alignment), sequenced after inversion — not dropped.
3. **Black's absolutist "no landings until surgery closes."** Advisory validator codes in
   disjoint files change no pass/fail behavior; the batch-landing rule captures the real
   cost without a fake freeze.

## 3 · Path v2 (supersedes this morning's ordering)

1. **NOW — Bridge probe** (arch window, app-side, zero churn): load one accepted
   WorldContract into 5173; walk it; record the binary. *24h question: does it walk?*
2. **NOW — W2 closes FOV surgery.** No new injections until close.
3. **NEXT — One batched landing** (Kiro + W2 coordinated): solver inversion + three cost
   terms (height-aware circulation, clearance bands, wall alignment, Merrell weights) +
   advisory capsule gate. One fingerprint churn.
4. **CONTINUOUS — Cloud bake-off runs itself.** Pre-committed rule: if all 5 cloud rungs
   score 0%, freeze ALL model-seeking until inversion lands (no new lanes, no pulls, no
   APIs) — the evidence would then be conclusive that geometry, not models, is the wall.
5. **AFTER inversion — depth-conditioned canon** (correct encoding for our ControlNet),
   then blocking capsule gate, then harvest at scale with the crowned planner.
6. **Deferred (unchanged):** local pulls, Kimi K3, specialized 3D VLMs — reclassified as
   post-inversion QA/judge candidates, not infrastructure.

## 4 · Pre-committed decision rules (Black's demand, adopted)

- Bridge walks fine → scoring/selection is the bottleneck; bake-off result matters more.
- Bridge fails spatially → inversion confirmed as sole critical path; everything else waits.
- All 5 cloud rungs 0% → model-seeking frozen until post-inversion.
- W2 surgery still open at +6h → nothing lands; Kiro keeps diffs staged.
- Corpus pace still 0/day at +48h → counter ignored until pass > 0 (already policy).

## 5 · Honesty note

My original path was structurally right about the bridge, batching, and two clocks, but
wrong twice: I sequenced the solver inversion behind the bake-off verdict (both critics +
prior evidence say it IS the critical path), and I proposed copying Marble's depth wire
format instead of its discipline. The Red Engineer's workspace RAG also surfaced prior
debate rounds from 2026-07-17 that reached the same inversion-first conclusion — this is
now a three-times-confirmed finding and should not be re-litigated.
