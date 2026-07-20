# Canonical Release Pass

Every release starts with a brand-new empty session. Never restore an old session as release evidence.

## Step 1 — Canonical prompt

```text
Create a compact rectangular 1950s American diner interior exactly 6 meters wide, 4 meters deep, and 2.8 meters high.

The approved composition must contain exactly one fixed 4.2-meter-long Formica counter centered parallel to the north wall. Give it rounded polished-chrome edge trim and a pale mint-green front.

Place exactly four individual red-vinyl-and-chrome swivel stools in a straight, evenly spaced row along the south side of the counter. Each stool must be a separate object. Leave a clear circulation aisle behind the stools.

Install one standard-width swinging kitchen door on the west wall near the northwest corner. Center one large storefront window on the south wall. Keep both openings unobstructed.

Hang exactly three individual polished-chrome pendant lights in an evenly spaced row directly above the counter. Use a glossy black-and-cream checkerboard linoleum floor, cream ceramic tile wainscoting, pale mint-green upper walls, and a lightly aged pressed-tin ceiling.

Set the scene after closing on a rainy evening. Warm amber light from the three pendants should illuminate the counter and red stools. Cool blue-gray rainy light should enter through the storefront window. The atmosphere should feel cinematic, nostalgic, intimate, realistic, and professionally photographed.

Place the canon camera at normal eye height in the southeast corner, looking diagonally northwest across all four stools toward the counter and kitchen door. Use a natural rectilinear architectural-photography lens with a 55-degree field of view.

The final camera view must clearly show the complete counter, all four separate stools, all three pendant lights, the kitchen door, and part of the rainy storefront window.

Do not add people, booths, tables, extra stools, extra lights, extra doors, extra windows, signs, readable text, or unrelated furniture. Do not treat the floor, walls, ceiling, doors, or windows as furniture objects. Preserve the requested object counts exactly.
```

## Required inspection

Inspect Brief, Plan, Blockout, Canon, World, and Compare when a world revision is needed. Validate the page, API routes, and static JavaScript. If any defect appears, record it, delete that test session, fix it, and restart from another empty session.

## Failure log

- 2026-07-20 — Headless Edge V7 responsive validation found the composer extended 18px below a 1440×500 viewport when the chat pane was persisted at its minimum width. Added a V7-only compact-height layout for intro, messages, and composer; no release session had been created.
- 2026-07-20 — User reported that resizing the V6 page could move chat outside the visible area and that the image preview pane could not be resized. Root cause: a fixed 72px header assumption, fixed 100vh workspace math, an abrupt stacked breakpoint with fixed pane heights, and no pane-resize control. V6 remains unchanged; the responsive, accessible splitter correction advances to V7.
- 2026-07-20 — User session `b68ba004` reported a V5 Canon regression: encoded-blockout partial denoising preserved geometry but retained labels, guide edges, flat surfaces, and a painted-blockout appearance. The user session is preserved. V5 remains pinned to that historical workflow; the photoreal full-generation correction advances to V6.
- 2026-07-20 — V6 session `37a43c24` passed Plan and Blockout geometry inspection, but its plan-stage snapshot omitted `interface_version` and `workflow_profile_id`. Fixed plan payload provenance fields. Session discarded before Canon and cannot serve as release evidence.

- 2026-07-20 — Session `b1437cfb` rejected at Canon: output drifted from approved blockout/material brief because the conditioned FLUX workflow sampled from an empty latent; candidate fix switched to the encoded blockout latent with partial denoising and enriched prompt details. Session discarded before release evidence.
- 2026-07-20 — Session `1d19a2a6` rejected at Plan/Blockout/Canon inspection: “center one large storefront window” was normalized to offset `-2.1m`, and the 3D Blockout omitted all opening geometry. Fixed centered-south wording recognition, minimum large-window width, and explicit door/window rendering. Session discarded before World.
- 2026-07-20 — Session `0622d48f` rejected at Canon: geometry, camera, counts, door, and window passed, but Blockout-like floor/walls/ceiling remained instead of checkerboard linoleum, cream tile, mint paint, and pressed tin. Session reserved only for denoise/prompt probing, then discarded.

## Clean pass log

- 2026-07-20 — Final release-evidence session `0500f42f` passed from a brand-new empty V7 state through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact 6m × 4m × 2.8m dimensions, one 4.2m counter, four stools, three pendants, one west door, one centered south window, clear aisle intent, and southeast 55-degree camera. Canon passed local vision QA with exact counts, required openings/materials/lighting, no extras, and confidence 1.0. World passed eight scene objects, three lights, one door, one window, nine meshes, Godot project, download, four immutable snapshots, two Canon manifests, V3–V7 routes, and responsive Edge checks at seven viewport sizes. The splitter passed pointer clamps, keyboard controls, reset, and fresh-session Three.js resizing. Compare was not applicable.

- 2026-07-20 — Final release-evidence session `0e7252d6` passed from a brand-new empty V6 state on the exact retained-profile-isolated code through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact dimensions, one 4.2m counter, four stools, three pendants, west door, centered south window, clear aisle, and southeast 55-degree camera. Canon passed local visual QA with exact counts/openings, geometry 8/10, finish quality 9/10, all specified finishes, and no defects. World passed eight scene objects, three lights, one door, one window, nine meshes, Godot project, download, page/static/API routes, and immutable manifest checks. Compare was not applicable.

- 2026-07-20 — Session `86c40bc8` passed from a brand-new empty V6 state through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact 6m × 4m × 2.8m dimensions, one 4.2m counter, four stools, three pendants, west door, centered south window, and the 55-degree southeast camera. Canon passed local visual QA with exact counts/openings, geometry 8/10, finish quality 9/10, every specified finish visible, and no defects. World passed scene, nine mesh, Godot project, download, retained-version page, static JavaScript, readiness, workflow API, and immutable provenance checks. Four full-state snapshots and prepared/completed generation manifests contain the pinned V6 profile, exact graph/seed, and input/output hashes. Compare was not applicable because no World revision was required.

- 2026-07-20 — Session `46452b46` passed from empty state through Brief, Plan, Blockout, Canon, and World on V4. Canon passed exact counts, geometry, camera, and finish checks. World passed scene/mesh/download routes and rendered visibly in the V4 viewer. Compare was not applicable because no World revision was required.
- 2026-07-20 — Session `71462fa9` passed from empty state through Brief, Plan, Blockout, Canon, and World on logging-enabled V5. Canon passed exact counts, geometry, camera, and finishes. World passed scene/mesh/download routes plus deterministic V5 DOM/WebGL checks. Compare was not applicable. Its log trail covers lifecycle, process, test, `awaiting_description`, `awaiting_plan_approval`, `awaiting_approval`, and `ready`.

## Workflow provenance

- Immutable profile catalog: `GET /api/workflow/profiles`.
- Per-session mutable index: `GET /api/session/{session_id}/workflow` and `output/{session_id}/workflow_manifest.json`.
- Immutable full-state records: `output/{session_id}/workflow/snapshot_NNNN_{state}.json`.
- Immutable Canon lifecycle records: prepared plus completed/failed/skipped manifests containing the pinned profile, complete inputs, exact submitted graph and random seed, provider attempts, model files, artifact hashes, dimensions, and errors.
- V3 is pinned to `v3-legacy@f982288`; V4 to `v4-reference-full@5069761`; V5 to `v5-reference-partial@964da06`; V6 to `v6-reference-full-r1`; V7 to `v7-reference-full-r1`. The unreleased V5 full-generation probe remains cataloged as `v5-reference-full-r2` for provenance but is not active.

## Revision event logs

- Append-only files: `output/logs/v3.jsonl`, `output/logs/v4.jsonl`, `output/logs/v5.jsonl`, `output/logs/v6.jsonl`, and `output/logs/v7.jsonl`.
- Events: actionable clicks, stage/work transitions, session lifecycle, session API operations, and validation tests.
- Fields: UTC timestamp, interface version, session ID when available, event type, action, and sanitized details.
- Session API records include response status, resulting pipeline state, and latest progress message.
- User-entered prompt and revision-feedback text are intentionally not logged.
- Click history before this instrumentation was installed cannot be reconstructed; logging applies from this point forward.
