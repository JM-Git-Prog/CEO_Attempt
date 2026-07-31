# THE LINE — as-built architecture of the v15_Fable proving line
**Recorded 2026-07-31 (the crash-night rebuild).** This documents what IS RUNNING.
Authority note: `00-Vision-Index.md` says which doc owns what — doc 30 owns *what to
build next*, `BUILD-RULES.md` owns *how 5173 code is written*. This file owns neither;
it is the honest as-built record of the :8000 proving line so it can be rebuilt,
debugged, or handed to a future session without re-discovery.

---

## 1. The one line

```
prompt → PLAN (llama3.1) → CANON (Z-Image) → CENSUS (SAM3 measures photo)
       → WORLD (three.js, walkable) → THE LINE per object:
         cut → complete (Qwen-Edit) → John's photo verdict  = OBJECT CANON
         → mesh (Hunyuan3D) → mesh verdict → paint (MultiViews PBR) → paint verdict
         → SEATED in the room · warehoused for every future room
```

**The three-view identity law (John, 2026-07-31): the canon photo, the 2D blueprint,
and the first-person walkthrough must look identical.** One geometry feeds all three.

**The identity chain law: the approved photo IS the object's identity** — mesh and
paint derive from it; provenance.json records the chain.

## 2. Services and ports

| Port | What | Launcher | Notes |
|---|---|---|---|
| :8000 | v15_Fable server — `src/v15_fable.py` (FastAPI, uvicorn **StatReload**) | RESTART-LIVING-ROOM-8000.bat | Reload wipes `_RUNNER` (see §7 laws). ONE listener law — orphaned spawn workers serve stale code |
| — | `src/web/templates/index_v15_fable.html` | served per-request | Hot: edits live on refresh, no restart |
| :8188 | Mesh/render engine (ComfyUI) — Z-Image canon, SAM3 census, Qwen-Edit completion, Hunyuan3D blast | START-MESH-ENGINE.bat | Never killed by restart bats (G9) |
| :8190 | Paint Shop (ComfyUI sidecar, venv python) — MultiViews PBR | START-PAINT-SHOP.bat / KILL-8190-AND-START.bat | aimdo.dll renamed .bak 2026-07-31 (abort class); Chrome sometimes can't fetch it while httpx can |
| :8194 | Pick Board — `tools/pick-server.mjs` | START-PICK-BOARD.bat | **The ONE approval writer**: v15 verdicts proxy here; writes mesh-/paint-approval.json + prop-flags.json |
| :11434 | Ollama (llama3.1:latest planner) | Ollama app (auto-starts; died in the 3:19 crash) | 14GB resident when loaded — see GPU handoff law |

## 3. Data on disk (disk IS memory — sessions survive crashes)

```
CEO_Attempt/output/v15f_<sid>/          one session = one room ride (rewindable, branchable)
  plan.json                             THE geometry truth (see §5 schema)
  canon.png (+ canon.re-dream-<ts>.bak) the room's photo identity; re-dreams preserved
  canon-pending.json                    resumable render marker
  reconcile-evidence.json               census verdict + per-object bboxes + projections + shell_boxes
  reconcile-progress.json               live census progress the page streams
  cutouts/<slug>.png                    SAM3 full-frame RGBA cuts
  factory-queue.json                    the line's object queue
  line-<slug>.log / amodal-<slug>.log   per-object runner + completion logs

CEO-3D-World/worlds/warehouse/
  source/cutouts/raw/<slug>.png         factory intake (completed photo, refit + whitened)
  source/cutouts/<slug>.png             rembg-cleaned cutout the gate measures
  source/object-canon/<slug>.png        the APPROVED identity + <slug>.provenance.json
  output/<slug>/0-<slug>.glb            raw mesh · _clean.glb (normalized) · _painted.glb
  output/<slug>/mesh-approval.json      written ONLY by the Pick Board
  output/<slug>/paint-approval.json     "
CEO-3D-World/tools/prop-flags.json      flag ledger — see §7 gap
```

## 4. The measurement chain (what makes the three views identical)

1. **Projection** (single view): eye 1.65 m, hfov 66°, f = 768/tan 33°; each SAM3
   bbox bottom → Z = 1.65·f/(y−cy), X = (cx_px−cx)·Z/f.
2. **Calibration k**: the guessed camera reads ~2× far. k = median(prior_width /
   projected_width) over `_DEFAULT_SIZES` families, clamped [0.35, 1.6]. (Workshop
   measured k=0.495 across a 0.445–0.50 spread — one global camera error, proven.)
3. **Camera-anchored similarity transform** — NEVER min-max (constitution rule
   2026-07-31): `x_m = door_x + X·k`, `z_m = spawn_z − Z·k`, translate-to-fit only.
   The spawn (S door / personnel entry) IS the canon camera, so the first-person
   view meets exactly what the canon framed.
4. **Structural census** (photo-truth only): probes window/door/skylight/pillar/
   roll-up with geometric sanity gates (pillar: spans horizon + 3:1 slender + must
   NOT overlap a censused object ≥40%; roll-up: ≥8% frame width + w≥0.9h — distant
   doors read square; skylight: fully above horizon). Census OWNS its plan fields —
   none proven = cleared (stale writes must not survive). Floor material measured
   from palette pixels (low-sat mid-grey = concrete). A measured roll-up moves to
   its photo wall; spawn stays on a S personnel entry (doors[0] = spawn).
5. **Blueprint + world render from the same plan.json** — planSVG and buildWorld
   read identical x_m/z_m/shell/pillars/doors; identity is by construction.

## 5. plan.json schema (as of 2026-07-31)

`name, width_m, depth_m, height_m, vibe{}, palette{wall,floor,accent,mood}`
`shell{floor: wood-plank|concrete|tile|metal-plate|carpet; walls: drywall|metal-siding|brick|concrete-block|wood-panel; ceiling: flat|steel-trusses|exposed-rafters|corrugated-metal; trim: baseboard|baseboard+crown|none}`
`doors[{wall,offset_m,width_m,type: standard|roll-up|fire|sliding-gate|double}]`
`windows[{wall,offset_m,width_m,sill_m,type}]` · `pillars[{x_m,z_m}]` · `skylight: bool`
`objects[{name,category,x_m,z_m,w_m,d_m,h_m,rot_deg,_measured}]`
Categories: object|appliance|fixture|decoration|clutter. Known physical families
(`_DEFAULT_SIZES` names) can never be demoted to clutter/decoration by the planner.
Planner: 3 variants, num_predict 1600 (the schema outgrew 700), keep_alive 10m
across the burst, **VRAM released the moment planning ends**, anti-echo instruction
(the example JSON is shape-only — llama once furnished a warehouse with a bed).

## 6. The completion lane (amodal-fill.py, rebuilt 2026-07-31)

FluxFill is NOT installed; the lane runs **Qwen-Image-Edit-2511** (twin-layers pins:
20 steps / cfg 2.5 / euler / denoise 1.0) with an instruction naming the cut-off
sides (`touches` → words, no mask). Post-pass `refit`: autocrop → **whiten clamp
(min-channel ≥218 → pure white; ground shadows mesh into floor slabs)** → re-canvas
at 38% bbox area (clean-cutout's gate wants 20–80%; rembg trims ~20% further).

## 7. Hard-won operational laws (all constitutional as of 2026-07-31)

- **One GPU user at a time — including the planner.** llama + Z-Image = sysmem spill,
  116W @ 100% util, wedged [0%] renders that interrupts can't reach (they only land
  at node boundaries). Cure for a wedged op: evict llama (`keep_alive:0`) → the op
  completes → interrupt lands.
- **Similarity transforms, never min-max** for measured space (13.6× noise stretch).
- **Windows children detach** (`CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW`) — console
  CTRL events killed children silently (exit 0xC000013A).
- **Cache skips compare mtime, never bare existence** (the stale-cutout regate).
- **Never edit a watched server file mid-job** — StatReload wipes `_RUNNER`, the
  busy-guard goes blind, spawns race (the bench painted twice).
- **A flagged mesh blocks the line until its flag is resolved** — and the board has
  **no resolve API** (doApprove doesn't close flags). Current practice: fix the root
  cause, shelve the bad GLB as `.bak` (never delete), mark the flag `resolved` in
  prop-flags.json with a resolution note. GAP: the board needs a resolve button/route.
- **Remakes must shelve the old GLB first** — blast-local is resume-safe and will
  SKIP an existing mesh (the flagged slab got "re-meshed" into itself).
- Verdict proxy: v15 → board `/api/approve|/api/flag {slug:"warehouse", id, stage}`;
  render-stage is flag-only; a mesh flag kills+verifies the runner (`runner_freed`).
- Warehouse reuse: `match_asset` pairs plan objects to painted GLBs by whole-word
  noun overlap, category-symmetric (both sides derive via `_default_category`),
  adjective stopwords ignored; `_wh_cache` busts on rematch. Loop 5's drum seated
  loop 4's barrel with zero GPU spend — the flywheel working.

## 8. Where the code is

- `src/v15_fable.py` — everything server-side (planner, canon, census+transform,
  line endpoints, verdict proxy, sessions/branch). ~70KB, single file by design.
- `src/web/templates/index_v15_fable.html` — the single view: staged panels, planSVG
  blueprint, three.js world (procedural shell textures §, trim/casings, door types,
  trusses/rafters/corrugated, pillars, skylight), THE LINE dock, in-game flag modal.
- `CEO-3D-World/tools/amodal-fill.py` — completion lane (§6).
- `CEO-3D-World/tools/clean-cutout.py` — rembg clean + pixel gate (freshness-aware).
- `CEO-3D-World/tools/make-prop.mjs` (+prop-pipeline-lib.mjs) — the factory runner:
  clean→gate→blast→normalize→mesh-gate-wait→paint→done, GPU-locked.
- `CEO-3D-World/tools/pick-server.mjs` — the board (approvals, flags, MAKE-PROP).
- Variations shelf: `v15-variations/var-00N/` + per-variation RESTORE bats.

## 9. Open items (as of this writing)

- Board: flag **resolve** route + button (see §7 gap).
- Task #32: annotate tool (box+label on canon → cut/repair/learn).
- The line's "Seated" chip reads approval state, not live world placement.
- Barrel/dark-prop paints read dark in warm room light — finish/lighting pass topic.
- Loop 5 in flight: tires painting; crate queued. Loops 6–8 owed on the mandate.
