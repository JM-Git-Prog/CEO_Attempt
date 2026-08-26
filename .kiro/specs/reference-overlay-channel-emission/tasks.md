# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Depth/overlays emitted as real lossless auxiliary channels at generation
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists on the fully-controlled-camera reference-image emission path
  - **Scoped PBT Approach**: The bug is deterministic for the controlled-camera emission path. Scope the property to the concrete failing configuration - `emission.camera_controlled == TRUE` with `"depth" NOT IN overlay_channels` and `overlay_encoding IN {VISIBLE_RGB, ABSENT}` (from `isBugCondition` in design) - and generalize across varied MetricPlan/CameraContract fixtures.
  - Drive `SceneCanonGenerator.generate` in `src/unified_pipeline/canon_generator.py` with a stubbed ComfyUI client for a fully-controlled-camera Canon (from design "Exploratory Bug Condition Checking" test plan)
  - Test case 1 - **No depth channel at birth**: assert a separate lossless depth channel exists beside `canon_v{revision}.png` (fails on unfixed code - only RGB PNG from `SaveImage` node "9" is emitted)
  - Test case 2 - **Depth-in-visible-RGB does not survive re-encode**: if any overlay is packed into visible pixels, simulate a lossy re-encode (JPEG/video) of the visible RGB and assert recovered depth matches source (fails on unfixed code - packed values corrupted)
  - Test case 3 - **Unprojection cannot read depth directly**: attempt deterministic unprojection of a cutout by reading a lossless depth channel and assert success (fails on unfixed code - no channel to read)
  - Test case 4 - **Edge case, instance-ID present but depth absent**: assert a correct RGBA instance-ID channel alone does NOT satisfy the depth-channel requirement (bug condition still holds)
  - The test assertions should match the Expected Behavior Properties (`expectedBehavior` in design): container is lossless multi-channel, `"depth"` and `"instance_id"` in channels, `overlay_encoding == SEPARATE_LOSSLESS`, visible RGB byte-identical, survives lossy re-encode, deterministic unprojection
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves depth is absent/smuggled and not emitted as a real lossless channel at birth)
  - Document counterexamples found (e.g., "generate() produces only canon_v1.png RGB, no separate lossless depth channel exists"; "packed overlay corrupted after JPEG re-encode")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-controlled-camera, instance-ID, appearance, and RGB-only paths unchanged
  - **IMPORTANT**: Follow observation-first methodology - run the UNFIXED code first, record actual outputs, then assert those outputs
  - **Testing Approach**: Property-based testing is recommended (per design "Preservation Checking") - generate across controlled vs. non-controlled cameras, varied plans/cameras, and varied object configurations; catches edge cases like degenerate cameras, empty masks, and extreme depth ranges
  - Preservation domain: all inputs where `isBugCondition` returns FALSE (monocular non-controlled-camera depth, SAM3 instance-ID/alpha, visible-RGB appearance, RGB-only mesh prep)
  - Test case 1 - **Monocular depth path unchanged**: observe `UnifiedDepthEstimator` (`src/unified_pipeline/depth_bridge.py`) emits float32 `.npy` non-authoritative evidence under the immutable `FORBIDDEN_DEPTH_AUTHORITIES` deny-list on unfixed code, then assert byte/behavior identity after the fix (Req 3.3)
  - Test case 2 - **Instance-ID / alpha emission unchanged**: observe `object_isolator.apply_mask_to_image` / `isolate_bound_detection` RGBA output (alpha = instance mask) on unfixed code, then assert identical output after the fix (Req 3.1, 3.2)
  - Test case 3 - **Visible RGB byte-identical**: observe `canon_v{revision}.png` bytes on unfixed code, then assert byte-for-byte identity after the fix (Req 3.6)
  - Test case 4 - **RGB-only mesh prep unchanged**: observe `mesh_generators.prepare_generator_input` composite-on-white and `hidden_rgb_discarded: True` evidence on unfixed code, then assert identical behavior after the fix (Req 3.5)
  - Also assert the Canon appearance-only role is preserved - aux depth/overlay channels are read-only geometry echoes and do NOT override MetricPlan spatial authority (Req 3.4)
  - Write property-based tests capturing the observed behavior patterns across the non-bug-condition input domain
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix for reference-image overlay channel emission (emit depth + instance-ID as real lossless auxiliary channels at generation)

  - [x] 3.1 Add deterministic controlled-camera depth source
    - In `src/unified_pipeline/blockout_renderer.py`, use the existing `_build_projector` closure (returns `(screen_x, screen_y, depth)` from a CameraContract) as the deterministic controlled-camera z-render source for the aux depth channel
    - Render the depth channel from the approved MetricPlan + CameraContract - this is a controlled-camera z-render, NOT monocular estimation, so the monocular `.npy` path and `FORBIDDEN_DEPTH_AUTHORITIES` remain untouched
    - Bind the rendered depth to `camera_hash` + `plan_revision` for provenance
    - _Bug_Condition: isBugCondition(emission) where camera_controlled == TRUE and "depth" NOT IN overlay_channels_
    - _Expected_Behavior: expectedBehavior(result) - "depth" IN result.channels via deterministic projection_
    - _Requirements: 2.1, 3.3, 3.4_

  - [x] 3.2 Add "at-birth" auxiliary-channel emission in the Canon generator
    - In `src/unified_pipeline/canon_generator.py`, add a new helper `emit_reference_aux_channels(...)`
    - Invoke it from `SceneCanonGenerator.generate` AFTER the visible RGB PNG is retrieved
    - Write a lossless EXR-style multi-channel container beside the PNG (e.g., `canon_v{revision}.aux.exr`) holding depth as float32 `Z` and the instance-ID as a discrete `instance_id` label channel
    - Never encode any overlay into the visible RGB pixels; leave the `SaveImage` node "9" workflow path untouched so visible RGB stays byte-identical
    - Prefer a lossless EXR compression so channels survive later lossy re-encode of the visible RGB
    - _Bug_Condition: isBugCondition(emission) where overlay_encoding IN {VISIBLE_RGB, ABSENT}_
    - _Expected_Behavior: expectedBehavior(result) - container_is_lossless_multichannel, overlay_encoding == SEPARATE_LOSSLESS, visible_rgb == original_visible_rgb_
    - _Requirements: 2.1, 2.2, 2.3, 3.6_

  - [x] 3.3 Extend the SceneCanon model additively
    - In `src/unified_pipeline/models.py`, add optional fields to `SceneCanon` (e.g., `aux_channel_path`, `depth_channel`, `instance_id_channel`) referencing the container/channels
    - Default the new fields empty so existing `to_dict`/`from_dict` round-trips remain backward-compatible and the visible `image_path` is unchanged
    - _Bug_Condition: isBugCondition(emission) - depth not represented as a real channel today_
    - _Expected_Behavior: expectedBehavior(result) - channels referenced from the model additively_
    - _Requirements: 2.1, 2.2_

  - [x] 3.4 Add a deterministic direct-read unprojection consumer
    - Provide a new reader that consumes depth + instance-ID directly from the lossless container for deterministic unprojection of each cutout
    - Keep this additive and separate - `mesh_generators.prepare_generator_input` retains its composite-on-white / hidden-RGB-discard behavior for RGB-only encoders
    - Leave `object_isolator.apply_mask_to_image` / `isolate_bound_detection` instance-ID/alpha emission untouched; the aux container mirrors instance-ID as a channel, it does not replace the RGBA emission
    - _Bug_Condition: isBugCondition(emission) - downstream cannot read depth directly_
    - _Expected_Behavior: expectedBehavior(result) - deterministicUnprojection(result) == TRUE from direct channel reads_
    - _Requirements: 2.4, 3.1, 3.2, 3.5_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Depth/overlays emitted as real lossless auxiliary channels at generation
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior; when it passes it confirms the expected behavior is satisfied
    - Run the bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms depth + instance-ID are emitted as real lossless channels, no visible-RGB encoding, survives re-encode, deterministic direct-read unprojection)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-controlled-camera, instance-ID, appearance, and RGB-only paths unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions - monocular `.npy` path, RGBA instance-ID/alpha, byte-identical visible RGB, Canon appearance-only role, composite-on-white/hidden-RGB-discard all unchanged)
    - Confirm all tests still pass after the fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure the exploration test (Property 1) passes, all preservation tests (Property 2) pass, and any unit/integration tests from the design's Testing Strategy pass
  - Confirm the visible PNG remains byte-identical and no overlay bits are written into visible RGB
  - Ensure all tests pass, ask the user if questions arise
