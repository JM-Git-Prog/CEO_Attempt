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

- 2026-07-20 — Session `b1437cfb` rejected at Canon: output drifted from approved blockout/material brief because the conditioned FLUX workflow sampled from an empty latent; candidate fix switched to the encoded blockout latent with partial denoising and enriched prompt details. Session discarded before release evidence.
- 2026-07-20 — Session `1d19a2a6` rejected at Plan/Blockout/Canon inspection: “center one large storefront window” was normalized to offset `-2.1m`, and the 3D Blockout omitted all opening geometry. Fixed centered-south wording recognition, minimum large-window width, and explicit door/window rendering. Session discarded before World.
- 2026-07-20 — Session `0622d48f` rejected at Canon: geometry, camera, counts, door, and window passed, but Blockout-like floor/walls/ceiling remained instead of checkerboard linoleum, cream tile, mint paint, and pressed tin. Session reserved only for denoise/prompt probing, then discarded.

## Clean pass log

- 2026-07-20 — Session `46452b46` passed from empty state through Brief, Plan, Blockout, Canon, and World on V4. Canon passed exact counts, geometry, camera, and finish checks. World passed scene/mesh/download routes and rendered visibly in the V4 viewer. Compare was not applicable because no World revision was required.
- 2026-07-20 — Session `71462fa9` passed from empty state through Brief, Plan, Blockout, Canon, and World on logging-enabled V5. Canon passed exact counts, geometry, camera, and finishes. World passed scene/mesh/download routes plus deterministic V5 DOM/WebGL checks. Compare was not applicable. Its log trail covers lifecycle, process, test, `awaiting_description`, `awaiting_plan_approval`, `awaiting_approval`, and `ready`.

## Revision event logs

- Append-only files: `output/logs/v3.jsonl`, `output/logs/v4.jsonl`, and `output/logs/v5.jsonl`.
- Events: actionable clicks, stage/work transitions, session lifecycle, session API operations, and validation tests.
- Fields: UTC timestamp, interface version, session ID when available, event type, action, and sanitized details.
- Session API records include response status, resulting pipeline state, and latest progress message.
- User-entered prompt and revision-feedback text are intentionally not logged.
- Click history before this instrumentation was installed cannot be reconstructed; logging applies from this point forward.
