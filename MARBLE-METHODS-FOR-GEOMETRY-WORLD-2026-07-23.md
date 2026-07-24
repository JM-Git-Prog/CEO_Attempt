# Marble Methods for a Geometry-Driven World — Deep-Research Verdict

*2026-07-23. Question: what can we borrow from World Labs' Marble — and the neighbor systems
John named (Genie, Oasis, Minecraft, Roblox Cube, VRChat/Horizon) — for a GEOMETRY-driven
text→walkable-game pipeline that deliberately does not use splats? Researched via 5 parallel
lanes against primary sources (worldlabs.ai docs/blogs/repos, arXiv, official engine docs);
every capability claim dated; inference labeled. This document proposes; it changes nothing
by itself.*

---

## 0 · Executive verdict

**Nobody has solved John's sentence** — "a typed sentence becomes a walkable, playable,
semantically-correct game world with physics and doors." Each famous neighbor solved one
slice, and the slice everyone struggles hardest with (persistent, physics-true, editable
STRUCTURE) is the slice our pipeline owns by construction. World Labs' own 2026 essays argue
our side: they class frame models — including their own RTFM — as "renderers" with "no
explicit understanding of three-dimensional structure," and write that in 3D "a single
spatial edit propagates automatically across every rendered frame." The $1B they raised is
substantially aimed at approximating properties our WorldContract gets for free.

What IS worth taking: Marble's exact depth-conditioning recipe (they published the code),
their metric-scale asset contract, their two-tier collider discipline, four decades-deep
layout cost terms from the Fei-Fei lineage, and Roblox Cube's shape-tokenization pattern for
our eventual owned model.

## 0.5 · John's constraint ruling (mid-research, 2026-07-23) — the 12-hour bake

John: streaming is NOT the product. A user may wait **12 hours** for their world — full
asset bake: models, rigging, UV/texturing, audio/voice, a warehouse of build elements —
because the result is their **persistent per-user home world**.

This ruling decides the architecture argument outright:

- The ONLY advantage the frame-model class (Genie/Oasis/RTFM) holds is instant latency —
  the one currency John just declared worthless. Their weaknesses (forgetting, drift, no
  export, no edits, no physics guarantees) are all fatal to a persistent home world.
- A 12-hour budget makes every deterministic pass affordable: exhaustive CP-SAT layout
  search, many-candidate camera solves, multi-seed canon renders with QA-judged selection,
  full walkability execution tests, per-prop texture/rig passes. Quality gates stop being
  a cost problem.
- "Persistent home world" = the WorldContract is the save format. Build once, live in it,
  edit it parametrically ("a single spatial edit propagates automatically" — World Labs'
  own words for why explicit 3D wins).
- **Two clocks, don't confuse them:** user-facing latency is now relaxed; the RATCHET'S
  iteration speed is not — loop cycles per day = learning rate = time to the vision. The
  cloud bake-off and harvest throughput stay top priority.
- If "12-hour bake / persistent home world" is a new or sharpened product decision, it
  belongs in the owning vision document — proposed wording available on request; not edited
  here (constitution: vision changes go through John).

---

## 1 · What Marble actually is (verified, dated)

- Pano-first pipeline: text/image → panorama → 3D lift to Gaussian splats. (docs, 2026-07-23)
- **Chisel** (Nov 12, 2025): the structure-conditioned mode — user blocks out coarse 3D +
  text style prompt; "the coarse 3D scene determines the world's structure, while the text
  prompt controls its overall style."
- The documented mechanism is **depth-render conditioning, not 3D-native generation**: their
  public endpoint `pano:depth_to_rgb` takes a rendered depth panorama + prompt → RGB pano.
  Their own example app renders blockout depth from a pano camera at 1.75 m eye height,
  converts perspective→radial depth, **log-encodes** normalized depth with explicit
  `z_min`/`z_max`, empty space = 0. (docs + worldlabs-api-examples repo, verified 2026-07-23)
- Adherence is officially **loose**: "synthesizes textures that loosely adhere to that
  geometry." Blockout ≠ guarantee. (API schema, 2026-07-23)
- Exports: .spz splats + **collider GLB (100–200k tris, "optimized for simple physics")** +
  HQ mesh + pano. Worlds carry `semantics_metadata`: `metric_scale_factor` and
  `ground_plane_offset` — multiply positions to meters, subtract to put ground at y=0.
  Coordinate frame `marble_raw_opencv`, negate Y/Z for three.js. (docs, 2026-07-23)
- No published FOV convention or camera-solving math anywhere; in-product camera is
  keyframe-flying with `[`/`]` FOV nudges. RTFM (Oct 16, 2025): pose-tagged frames as
  spatial memory, "memory bounded by compute," no explicit 3D.
- Their essays (Mar 3 + Jun 3, 2026): frame models = "renderers"; entangling
  state/dynamics/rendering "weakens guarantees around physical consistency, replayability
  and determinism"; "AI-generated geometry can look correct while containing
  self-intersections or wrong scale."

## 2 · The borrow list — technique → pipeline stage → implementation

| # | Borrow | Upgrades stage | Implementation sketch | Source (date, type) |
|---|--------|----------------|----------------------|---------------------|
| 1 | **Log-radial depth conditioning recipe** | Canon image (Change 3: ControlNet on blockout) | Render blockout depth from the SOLVED camera; perspective→radial; log-encode normalized with explicit z_min/z_max; empty=0; feed as ControlNet depth to FLUX. This is Marble's shipped encoding — near-field detail survives quantization. | worldlabs-api-examples `web-chisel-depth-png` (verified 2026-07-23, official code) |
| 2 | **Loose-adherence doctrine** | QA / drift gates | Never trust the generator to honor structure. Blockout stays the ONLY truth for collision/gameplay; QA measures image-vs-blockout drift. We already believe this — Marble's own schema wording ("loosely adhere") is the receipt that even the frontier lab treats generation as advisory. | API schema (2026-07-23, official-doc) |
| 3 | **`semantics_metadata` asset contract** | WorldContract / exports | Every exported room asset carries `metric_scale_factor` + `ground_plane_offset` equivalents so any consumer can assert "meters, ground at y=0" mechanically. Kills the eyeball-alignment class of bugs (NVIDIA's own Marble tutorial had humans guessing scale by comparing to a 1 m cube). | docs rendering-spz (2026-07-23, official-doc) |
| 4 | **Two-tier mesh split + stored spawn** | World build / bridge to 5173 | Dedicated coarse collider (~5–10× lighter than visual mesh) + explicit per-room spawn transform (their demos hand-tune `startPos`/`startQuat`; we compute and STORE it in the contract). | export specs + Spark demos (2026-07-23) |
| 5 | **Walkability proven by execution** | Inspect/QA gate | Drive a kinematic capsule (Rapier — already in 5173) over the collider: fail on clip-through, gaps, unreachable floor. Marble users had to improvise this by hand (documented 10 cm floor gaps patched manually in Unity); we make it a deterministic gate. | hands-on reports + repos (2025-11→2026-07) |
| 6 | **Layout cost terms (Fei-Fei lineage + classics)** | Layout solver (solvers-own-space) | Three terms: (a) **circulation connectivity** — dilate footprints by an 18-inch person disk; free space must form ONE connected component including all doors (grid flood-fill — kills "legal but unwalkable"); (b) **plateau pairwise bands** t(d,m,M,α) with published clearances (seat-front 30", dining 36", coffee-table-to-seat 16–18"); (c) **wall alignment** −cos 4(θ−θwall). Holodeck's 10-constraint vocabulary (in-front-of, side-of, face-to…) is the proven LLM→solver schema. | Merrell SIGGRAPH 2011; Make-It-Home 2011; Holodeck CVPR 2024 (papers + repos) |
| 7 | **Pose-as-only-query camera pattern** | Composition stage | RTFM's one structural idea maps to us: pose (+FOV) is the only free variable; all consistency comes from frozen geometry. Interop note: express final FOV as three.js **vertical degrees**; convert horizontal via fov_v = 2·atan(tan(fov_h/2)/aspect). Marble publishes no FOV math — our 52–62° band is unconstrained. | RTFM blog (2025-10-16); Spark/three.js docs |
| 8 | **The positioning arsenal** | Product story / REAL-GAME toggle | Quote their own essays when explaining why we're geometry-native: renderers "cannot be trusted to design a building"; explicit 3D gives replayability/determinism; persistence costs storage, not attention. | worldlabs.ai essays (2026-03-03, 2026-06-03) |

## 3 · The neighbors John named — what each actually solved

- **Google Genie 3** (Aug 2025): text→playable video frames. Documented: interaction lasts
  "a few minutes," visual memory ~1 minute; failure modes = forgetting + drifting. Solved
  *instant playability*, not persistence, not export, not semantics. We take: nothing
  operational; a cautionary benchmark.
- **Oasis / Decart** (Oct 2024): Minecraft as a frame model. Documented: turn around and the
  landscape rearranges. Same class, same lesson.
- **Minecraft** (2009): solved *infinite plausible TERRAIN* with procedural noise (Perlin/
  simplex) — brilliant math for unauthored land, useless for "a 1980s kitchen with the
  counter against the north wall." Noise generates statistics, not semantics. We take:
  noise-based terrain for the GROUNDS phase later (build-grounds), not rooms.
- **Roblox Cube** (open-sourced Mar 2025; 4D beta Feb 2026): the real one. Trained NATIVELY
  on 3D — tokenizes shapes → text-to-mesh, shape-to-text, with interactivity ("4D") in beta
  and full **scene generation still a prototype** by their own materials. Two takes:
  (a) candidate local text→PROP mesh rung alongside Hunyuan3D on the 4090 (open weights);
  (b) **the strategic one: shape tokenization is the design pattern for our owned model** —
  when the flywheel reaches F2/F3, tokenizing WorldContract elements (openings, placements,
  relations) beats treating plans as raw text. Roblox proved 3D-native tokens work at scale.
- **VRChat / Horizon Worlds / Roblox-the-platform**: solved persistent walkable multiplayer
  worlds decades-deep — with AUTHORED GEOMETRY and real engines. They are the proof that
  walkability/persistence is an engineering-solved problem *once you own geometry*. None of
  them generate a correct furnished room from a sentence. Their solved half + our
  generative front end = the actual product thesis.

**The sorted claim:** "they all solved it" → each solved a different *component*; the union
of what they solved is exactly our architecture: procedural math for terrain (Minecraft),
3D-native generation of assets (Cube), authored-geometry persistence (platforms), instant
text-to-visual (frame models — the one component we replace with solvers + conditioned
rendering because the frame-model version provably can't hold a world together).

## 4 · Borrow-first shortlist (leverage per engineering day, vs TODAY's walls)

1. **Layout cost terms (#6)** — attacks the live wall (plan-stage illegal geometry) with
   deterministic math; slots into the solvers-own-space rebuild the architecture window
   already has queued. Circulation flood-fill alone kills a failure class our three checks
   miss. *Days: ~1–2 inside the existing solver interface.*
2. **Depth-conditioning recipe (#1 + #2)** — the exact encoding for the already-planned
   ControlNet canon switch; camera-alignment failures become impossible by construction.
   *Days: ~1 (ComfyUI workflow change + one render function).*
3. **Walkability-by-execution gate (#5)** — turns "walkable" from a claim into a measured
   verdict using Rapier we already run; becomes the bridge's acceptance test.
   *Days: ~1.*
4. **Asset metric contract (#3 + #4)** — trivial contract fields; prevents a whole future
   bug class at the 5173 bridge. *Days: <0.5.*
5. **Cube tokenization study (#3 take-b)** — F2/F3 design input, gated on the corpus
   reaching 500/2000. Zero days now; a design doc note.

## 5 · Honesty section

- Marble's consumer Chisel using exactly the public depth-pano path is strongly implied
  (feature naming, pano camera in UI, official example named "web-chisel") but the app could
  add undocumented channels — labeled inference.
- Whether Marble collider GLBs ship pre-scaled to meters is undocumented; our sandbox could
  not fetch a sample GLB to check.
- No World Labs architecture paper exists for Marble; no RTFM drift benchmarks published —
  persistence claims rest on demos.
- Cube scene-level generation status ("prototype") is from Roblox's own Feb 2026 materials;
  their cadence is fast — recheck before relying on it.
- Layout cost-term formulas were verified against the primary PDFs by the research agent,
  not re-derived; numeric clearances trace to Panero & Repetto anthropometrics via Merrell.

## 6 · Sources (primary, dated)

World Labs: [Marble launch blog](https://www.worldlabs.ai/blog/marble-world-model) (2025-11-12) ·
[World API announcement](https://www.worldlabs.ai/blog/announcing-the-world-api) (2026-01-21) ·
[depth_to_rgb API reference](https://docs.worldlabs.ai/api/reference/pano/depth_to_rgb.md) ·
[rendering-spz](https://docs.worldlabs.ai/api/rendering-spz) · [export specs](https://docs.worldlabs.ai/marble/export/specs.md) ·
[release notes](https://docs.worldlabs.ai/marble/release-notes.md) · [Chisel docs](https://docs.worldlabs.ai/marble/create/chisel-tools/chisel-basics) ·
[web-chisel-depth-png example](https://github.com/worldlabsai/worldlabs-api-examples) ·
[RTFM](https://www.worldlabs.ai/blog/rtfm) (2025-10-16) · [3D as code](https://www.worldlabs.ai/blog/3d-as-code) (2026-03-03) ·
[Taxonomy of world models](https://www.worldlabs.ai/blog/taxonomy-of-world-models) (2026-06-03) ·
[Spark 2.0](https://www.worldlabs.ai/blog/spark-2.0) (2026-04-14) · [funding](https://www.worldlabs.ai/blog/funding-2026) (2026-02-18) ·
[SceniX acquisition](https://www.worldlabs.ai/blog/scenix) (2026-07-21) ·
[Fei-Fei Li, From Words to Worlds](https://drfeifei.substack.com/p/from-words-to-worlds-spatial-intelligence) (2025-11-10)

Layout math: [Merrell et al., Interactive Furniture Layout, SIGGRAPH 2011](http://graphics.berkeley.edu/papers/Merrell-IFL-2011-08/Merrell-IFL-2011-08.pdf) ·
[Yu et al., Make It Home, SIGGRAPH 2011](https://web.cs.ucla.edu/~dt/papers/siggraph11/siggraph11.pdf) ·
[Fisher et al. 2012](https://graphics.stanford.edu/projects/scenesynth/) · [Qi et al. CVPR 2018](https://openaccess.thecvf.com/content_cvpr_2018/papers/Qi_Human-Centric_Indoor_Scene_CVPR_2018_paper.pdf) ·
[PlanIT SIGGRAPH 2019](https://dl.acm.org/doi/10.1145/3306346.3322941) · [ATISS NeurIPS 2021](https://arxiv.org/abs/2110.03675) ·
[LayoutGPT](https://arxiv.org/abs/2305.15393) · [Holodeck CVPR 2024](https://arxiv.org/abs/2312.09067) · [3D-FRONT](https://arxiv.org/abs/2011.09127)

Neighbors: [Roblox Cube announcement](https://about.roblox.com/newsroom/2025/03/introducing-roblox-cube) (2025-03) ·
[Cube 4D generation](https://about.roblox.com/newsroom/2026/02/accelerating-creation-powered-roblox-cube-foundation-model) (2026-02) ·
[Cube repo](https://github.com/Roblox/cube/) · [Cube paper](https://arxiv.org/abs/2503.15475) ·
[Oasis coverage, TechCrunch](https://techcrunch.com/2024/10/31/decarts-ai-simulates-a-real-time-playable-version-of-minecraft/) (2024-10-31) ·
[Oasis limitations](https://en.wikipedia.org/wiki/Oasis_(Minecraft_clone)) ·
[Genie 3, DeepMind](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/) (2025-08-05) ·
[NVIDIA Isaac Sim + Marble tutorial](https://developer.nvidia.com/blog/simulate-robotic-environments-faster-with-nvidia-isaac-sim-and-world-labs-marble/) (2025-12-17)
