# Reference Overlay Channel Emission Bugfix Design

## Overview

For generated reference images — the case where the pipeline fully controls the
camera — the Scene_Canon emission path writes only a plain 8-bit RGB PNG
(`canon_v{revision}.png`). The SAM3 "twin-layers" instance-ID mask is emitted
correctly as a separate channel (RGBA alpha), but depth (and any other overlay)
is never emitted as a real, separate, lossless channel at generation time. Depth
is either smuggled into the visible RGB pixels or omitted entirely and re-derived
later. Once the visible image passes through any lossy encode (JPEG, video, or
re-encode), smuggled overlay data is corrupted or lost, and downstream
deterministic unprojection of each cutout becomes unreliable.

The fix emits overlays "at birth" as explicit, lossless auxiliary channels in an
EXR-style multi-channel container written **beside** the visible PNG, exactly as
the instance-ID mask is already a real channel. Because the camera is fully
controlled for generated reference images, the depth channel is produced
**deterministically from the approved MetricPlan + CameraContract** (the same
controlled-camera projection the Blockout renderer already computes), never from
monocular estimation and never encoded into visible pixels. With depth and
instance-ID present as real lossless channels, each cutout can be unprojected
deterministically by reading channels directly.

The fix is scoped strictly to the generated reference-image emission path. It does
not touch the separate monocular depth-estimation path used for input photographs
whose camera the pipeline does not control, it does not disturb the already-correct
instance-ID mask emission, and it leaves the visible RGB output byte-identical.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a fully-controlled-camera
  reference-image emission where depth is NOT written as a separate lossless auxiliary
  channel (it is smuggled into visible RGB or omitted entirely).
- **Property (P)**: The desired emission behavior — depth and instance-ID written into a
  lossless multi-channel (EXR-style) container beside the visible PNG, losslessly
  persisted, survivable across lossy re-encode, and directly readable for deterministic
  unprojection, with visible RGB unchanged.
- **Preservation**: Existing behaviors that must remain unchanged — SAM3 instance-ID/alpha
  emission, the appearance-only role of the Scene_Canon, the non-controlled-camera
  monocular `.npy` depth path, RGB-only mesh input preparation, and byte-identical visible RGB.
- **Controlled camera**: A generated reference image where the pipeline owns the camera and
  the scene geometry (MetricPlan + CameraContract), so a deterministic depth render is
  available at generation time.
- **Auxiliary channel container**: The lossless EXR-style multi-channel artifact
  (e.g., `canon_v{revision}.aux.exr`) holding named float/label channels (`Z` depth,
  `instance_id`) alongside — never inside — the visible RGB.
- **`_build_canon_workflow`**: The function in `src/unified_pipeline/canon_generator.py`
  that builds the ComfyUI FLUX img2img workflow; today it terminates in a plain `SaveImage`
  (node `"9"`) emitting RGB PNG only. This is the defect site.
- **`SceneCanonGenerator.generate`**: The orchestrator in
  `src/unified_pipeline/canon_generator.py` that submits the workflow and retrieves the
  output; the aux-channel emission attaches here after RGB retrieval.
- **`_build_projector`**: The projection closure in
  `src/unified_pipeline/blockout_renderer.py` returning `(screen_x, screen_y, depth)` from
  a CameraContract; the deterministic controlled-camera depth source for the aux channel.
- **`apply_mask_to_image` / `isolate_bound_detection`**: The functions in
  `src/unified_pipeline/object_isolator.py` that write the correct instance-ID channel
  (RGBA, alpha = instance mask). Must remain unchanged.
- **`UnifiedDepthEstimator`**: The monocular DA3 estimator in
  `src/unified_pipeline/depth_bridge.py` that writes float32 `.npy`, evidence-only /
  non-authoritative under `FORBIDDEN_DEPTH_AUTHORITIES`. Must remain unchanged.
- **`prepare_generator_input`**: The consumer in `src/unified_pipeline/mesh_generators.py`
  that composites approved alpha onto white and discards hidden RGB
  (`hidden_rgb_discarded: True`). Must remain unchanged.

## Bug Details

### Bug Condition

The bug manifests when the pipeline emits a generated reference image with a fully
controlled camera. `SceneCanonGenerator.generate` builds a workflow via
`_build_canon_workflow` that terminates in a plain `SaveImage` node producing an
8-bit RGB PNG, and then retrieves only that RGB image. No node and no post-retrieval
step emits depth (or any other overlay) as a separate lossless channel. As a result,
depth is either encoded into the visible RGB pixels (steganographic-in-visible-RGB) or
omitted entirely and re-derived downstream. The instance-ID channel is emitted
correctly and is not part of the bug.

**Formal Specification:**
```
FUNCTION isBugCondition(emission)
  INPUT: emission of type ReferenceImageEmission
    emission.camera_controlled : boolean          # pipeline fully controls the camera
    emission.instance_id_channel : boolean         # SAM3 instance-ID emitted (already TRUE)
    emission.overlay_channels    : set<string>      # aux channels emitted losslessly "at birth"
    emission.overlay_encoding    : enum { SEPARATE_LOSSLESS, VISIBLE_RGB, ABSENT }
  OUTPUT: boolean

  RETURN emission.camera_controlled == TRUE
         AND "depth" NOT IN emission.overlay_channels           # depth is not a real aux channel
         AND emission.overlay_encoding IN { VISIBLE_RGB, ABSENT } # smuggled into pixels OR missing
END FUNCTION
```

### Examples

- **Depth omitted at birth**: `generate()` produces `canon_v1.png` (RGB) and a correct
  RGBA instance-ID cutout, but no depth channel exists → `overlay_encoding = ABSENT`,
  `"depth" NOT IN overlay_channels` → bug condition holds.
- **Depth smuggled into pixels**: an overlay is packed into the low bits / visible RGB of
  the reference image → `overlay_encoding = VISIBLE_RGB` → bug condition holds; after a
  JPEG/video re-encode the packed values are corrupted.
- **Lossy re-encode destroys overlay**: a cutout derived from the reference image is
  re-encoded; the visible-pixel-encoded depth is destroyed, so a downstream unprojection
  reads corrupted depth (or none) → unreliable unprojection.
- **Edge case — fully controlled, instance-ID only**: the SAM3 instance-ID channel is
  present and correct, yet depth is still absent as a separate channel → bug condition
  holds (instance-ID correctness does not satisfy the depth requirement).
- **Non-example (bug condition FALSE)**: monocular depth for an input photograph whose
  camera is NOT controlled → `camera_controlled = FALSE` → bug condition does not hold;
  the `.npy` non-authoritative path is out of scope and unchanged.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- SAM3 instance-ID masks for generated reference images continue to be emitted as a proper
  instance-ID channel, unchanged (`object_isolator.apply_mask_to_image` /
  `isolate_bound_detection`).
- Object isolation continues to carry each object's instance mask in the RGBA alpha channel
  under the current quality gates.
- Monocular depth for input photographs whose camera is NOT controlled continues to be
  produced by `UnifiedDepthEstimator` as optional, non-authoritative float32 `.npy` evidence
  under the immutable `FORBIDDEN_DEPTH_AUTHORITIES` deny-list, with no spatial authority.
- The Scene_Canon continues to own appearance only (materials, lighting, identity); the new
  depth/overlay channels are read-only geometry echoes for unprojection and do NOT override
  MetricPlan spatial authority.
- `mesh_generators.prepare_generator_input` continues to composite approved alpha onto white
  and discard hidden RGB (`hidden_rgb_discarded: True`) for RGB-only encoders.
- The visible RGB of a generated reference image (`canon_v{revision}.png`) is byte-identical
  before and after the fix.

**Scope:**
All inputs that do NOT satisfy the bug condition should be completely unaffected by this fix.
This includes:
- Monocular (non-controlled-camera) depth estimation for input photographs.
- SAM3 instance-ID / RGBA alpha emission.
- Visible-RGB appearance consumption of the Canon.
- RGB-only mesh input preparation (composite-on-white).

_The actual expected correct behavior for buggy inputs is defined in the Correctness
Properties section (Property 1)._

## Hypothesized Root Cause

Based on the module investigation and bug description, the most likely issues are:

1. **Missing auxiliary-channel emission step**: `_build_canon_workflow` terminates in a plain
   `SaveImage` node (`"9"`) that only writes RGB PNG, and `generate()` retrieves only that RGB
   via `client.get_output_image`. There is no SaveEXR / multi-channel emission and no
   post-retrieval aux-channel writer, so depth is never emitted "at birth".
   - Container node "8" → "9" is `VAEDecode` → `SaveImage`; nothing branches to a depth or
     multi-channel save.

2. **Lossless container format never adopted for emission**: the emitted PNG is 8-bit RGB and
   cannot carry float32 depth or a discrete instance-ID label channel. The emission format was
   never upgraded to an EXR-style multi-channel container, even though the codebase already
   reads EXR depth (`depth_anything3._load_exr_depth`, `depth_estimator._load_exr_depth`).

3. **Depth re-derivation / smuggling deferred to consumers**: because no controlled-camera depth
   channel exists at generation, consumers either re-estimate depth (monocular, non-authoritative)
   or read overlay data smuggled in visible pixels — data that lossy re-encode destroys.

4. **No direct-read unprojection contract**: there is no downstream reader that consumes depth +
   instance-ID directly from a lossless container, so `prepare_generator_input` composites alpha
   onto white and discards hidden RGB with no lossless depth channel available to read
   (`hidden_rgb_discarded: True`, no depth channel today).

The controlled-camera depth source needed to fix (1)–(3) already exists deterministically:
`blockout_renderer._build_projector` yields `(screen_x, screen_y, depth)` for the same
CameraContract used to frame the Canon, giving an exact controlled-camera z-render bound to
`camera_hash` + `plan_revision` without invoking monocular estimation.

## Correctness Properties

Property 1: Bug Condition - Depth and overlays emitted as real lossless auxiliary channels at generation

_For any_ generated reference-image emission with a fully controlled camera where the bug
condition holds (isBugCondition returns true — depth is not present as a separate lossless
channel, or is encoded into visible RGB), the fixed emission SHALL write depth AND the
instance-ID into a lossless multi-channel (EXR-style) container beside the visible PNG, such
that: (a) no overlay is encoded into the visible RGB pixels; (b) the overlay channels are
persisted losslessly and survive any subsequent lossy encode of the visible RGB; and (c) a
downstream consumer reads depth and instance-ID directly from the lossless channels and
unprojects each cutout deterministically.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Non-controlled-camera, instance-ID, appearance, and RGB-only paths unchanged

_For any_ input where the bug condition does NOT hold (isBugCondition returns false) — monocular
depth for a non-controlled camera, SAM3 instance-ID/alpha emission, visible-RGB appearance
consumption, and RGB-only mesh input preparation — the fixed code SHALL produce exactly the same
result as the original function, preserving: byte-identical visible RGB
(`canon_v{revision}.png`), the non-authoritative float32 `.npy` monocular depth path under the
immutable `FORBIDDEN_DEPTH_AUTHORITIES` deny-list, the RGBA instance-ID/alpha emission, the
appearance-only role of the Canon, and the composite-on-white / hidden-RGB-discard behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `src/unified_pipeline/canon_generator.py`

**Function**: `SceneCanonGenerator.generate` (and a new helper `emit_reference_aux_channels`)

**Specific Changes**:

1. **Add an "at-birth" auxiliary-channel emission step**: After the visible RGB PNG is
   retrieved in `generate()`, invoke a new `emit_reference_aux_channels(...)` that writes a
   lossless EXR-style multi-channel container beside the PNG (e.g.,
   `canon_v{revision}.aux.exr`). The PNG emission (workflow node `"9"` `SaveImage`) is left
   untouched so visible RGB stays byte-identical (Req 3.6).

2. **Produce depth deterministically from the controlled camera**: Render the depth channel
   from the approved MetricPlan + CameraContract using the existing controlled-camera
   projection (`blockout_renderer._build_projector`, which already returns per-point `depth`).
   This is a controlled-camera z-render, NOT monocular estimation, so the monocular `.npy`
   path and `FORBIDDEN_DEPTH_AUTHORITIES` are untouched (Req 3.3). The aux depth is read-only
   and does not override MetricPlan spatial authority (Req 3.4).

3. **Write channels losslessly, never into visible RGB**: Store depth as float32 `Z` and the
   instance-ID as a discrete label channel (`instance_id`) inside the EXR-style container. No
   steganographic-in-visible-RGB encoding anywhere (Req 2.2). Bind the container to
   `camera_hash` + `plan_revision` for provenance and prefer a lossless EXR compression so
   channels survive later lossy re-encode of the visible RGB (Req 2.3).

4. **Extend the SceneCanon model additively**: Add optional fields to
   `src/unified_pipeline/models.py::SceneCanon` (e.g., `aux_channel_path`, `depth_channel`,
   `instance_id_channel`) referencing the container/channels, defaulting empty so existing
   `to_dict`/`from_dict` round-trips remain backward-compatible and the visible `image_path`
   is unchanged.

5. **Add a deterministic direct-read unprojection consumer**: Provide a reader that consumes
   depth + instance-ID directly from the lossless container for deterministic unprojection of
   each cutout (Req 2.4). This is additive: `mesh_generators.prepare_generator_input` retains
   its composite-on-white / hidden-RGB-discard behavior for RGB-only encoders (Req 3.5); the
   new lossless unprojection path is a separate consumer.

6. **Leave instance-ID emission untouched**: `object_isolator.apply_mask_to_image` /
   `isolate_bound_detection` continue to emit RGBA with alpha = instance mask, unchanged
   (Req 3.1, 3.2). The aux container mirrors the instance-ID as a channel; it does not replace
   or alter the existing RGBA emission.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate the bug on unfixed code (depth absent / smuggled and destroyed by re-encode), then
verify the fix emits real lossless channels for controlled-camera reference images while
preserving every non-buggy behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm
or refute the root cause analysis (missing aux emission / lossy-destroyed smuggled depth). If we
refute, we will need to re-hypothesize.

**Test Plan**: Drive `SceneCanonGenerator.generate` (with a stubbed ComfyUI client) for a
fully-controlled-camera reference image and assert on the emitted artifacts. Inspect whether any
separate lossless depth channel exists beside the PNG, and simulate a lossy re-encode of the
visible RGB to observe overlay corruption. Run against the UNFIXED code to observe failures.

**Test Cases**:
1. **No depth channel at birth**: Generate a Canon and assert a separate lossless depth channel
   exists beside `canon_v{revision}.png` (will fail on unfixed code — only RGB PNG is emitted).
2. **Depth-in-visible-RGB does not survive re-encode**: If any overlay is packed into visible
   pixels, re-encode the visible RGB (JPEG/video) and assert recovered depth matches the source
   (will fail on unfixed code — packed values are corrupted).
3. **Unprojection cannot read depth directly**: Attempt deterministic unprojection of a cutout
   by reading a lossless depth channel and assert success (will fail on unfixed code — no channel
   to read; depth must be re-derived/monocular).
4. **Edge case — instance-ID present but depth absent**: Assert that a correct RGBA instance-ID
   channel does NOT by itself satisfy the depth-channel requirement (may fail on unfixed code).

**Expected Counterexamples**:
- No separate lossless depth channel is emitted beside the visible PNG.
- Overlay data packed into visible pixels is corrupted/destroyed by a lossy re-encode.
- Possible causes: missing aux-channel emission node/step, no lossless container format adopted,
  depth re-derivation/smuggling deferred to consumers.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed emission produces
the expected behavior (real lossless depth + instance-ID channels, no visible-RGB encoding,
survives re-encode, deterministic direct-read unprojection).

**Pseudocode:**
```
FOR ALL emission WHERE isBugCondition(emission) DO
  result := emit_reference_aux_channels(emission)   // fixed emission path
  ASSERT expectedBehavior(result)
END FOR

FUNCTION expectedBehavior(result)
  RETURN result.container_is_lossless_multichannel == TRUE
         AND "depth" IN result.channels
         AND "instance_id" IN result.channels
         AND result.overlay_encoding == SEPARATE_LOSSLESS       // never VISIBLE_RGB
         AND result.visible_rgb == original_visible_rgb          // Req 3.6, byte-identical
         AND survivesLossyReencode(result.channels) == TRUE      // Req 2.3
         AND deterministicUnprojection(result) == TRUE           // Req 2.4
END FUNCTION
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed code
produces the same result as the original code.

**Pseudocode:**
```
FOR ALL emission WHERE NOT isBugCondition(emission) DO
  ASSERT original(emission) == fixed(emission)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (controlled vs.
  non-controlled camera, varied plans/cameras, varied object configurations).
- It catches edge cases that manual unit tests might miss (e.g., degenerate cameras, empty
  masks, extreme depth ranges).
- It provides strong guarantees that non-buggy behavior is unchanged for all inputs outside the
  bug condition.

**Test Plan**: Observe behavior on UNFIXED code first for the preserved paths (monocular `.npy`
depth, RGBA instance-ID, visible-RGB appearance, composite-on-white), then write property-based
tests capturing that behavior and assert equivalence after the fix.

**Test Cases**:
1. **Monocular depth path unchanged**: Observe `UnifiedDepthEstimator` emits float32 `.npy`
   non-authoritative evidence with the immutable `FORBIDDEN_DEPTH_AUTHORITIES` deny-list on
   unfixed code, then assert byte/behavior identity after the fix.
2. **Instance-ID / alpha emission unchanged**: Observe `apply_mask_to_image` RGBA output (alpha =
   mask) on unfixed code, then assert identical output after the fix.
3. **Visible RGB byte-identical**: Observe `canon_v{revision}.png` bytes on unfixed code, then
   assert byte-for-byte identity after the fix.
4. **RGB-only mesh prep unchanged**: Observe `prepare_generator_input` composite-on-white and
   `hidden_rgb_discarded: True` evidence on unfixed code, then assert identical behavior after
   the fix.

### Unit Tests

- Aux-channel emission writes a lossless multi-channel container with `Z` (float32 depth) and
  `instance_id` channels beside the visible PNG for a controlled-camera Canon.
- Depth channel values match the deterministic controlled-camera projection
  (`_build_projector` depth) for the same CameraContract, and are bound to `camera_hash` +
  `plan_revision`.
- Visible PNG bytes are unchanged; no overlay bits are written into visible RGB.
- `SceneCanon` gains optional aux-channel fields and round-trips through `to_dict`/`from_dict`
  with backward-compatible defaults.
- Edge cases: empty/degenerate mask, extreme depth range, non-controlled camera (no aux
  emission), and missing MetricPlan/CameraContract.

### Property-Based Tests

- Generate random controlled-camera plans/cameras and assert the emitted depth channel
  reproduces the deterministic projection depth and yields deterministic unprojection.
- Generate random cutouts and assert instance-ID + depth read directly from the lossless
  container unproject deterministically and survive a simulated lossy re-encode of the visible RGB.
- Generate random non-controlled-camera inputs and assert the monocular `.npy` path and all
  preserved behaviors are byte/behavior identical to the original.

### Integration Tests

- Full generate → aux-emit → unproject flow for a controlled-camera Canon: assert the visible
  PNG is appearance-only and identical, the aux container carries lossless depth + instance-ID,
  and each cutout unprojects deterministically from direct channel reads.
- Lossy-encode survival: re-encode the visible RGB (JPEG/video) and assert the aux channels
  (stored losslessly beside it) are intact and unprojection results are unchanged.
- Non-controlled-camera regression: run the monocular input-photo path end to end and assert no
  aux-channel emission occurs and depth remains non-authoritative `.npy` evidence.
