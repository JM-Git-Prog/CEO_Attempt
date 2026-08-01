# Implementation Plan: Comprehensive E2E Testing Framework

## Overview

This plan implements a five-layer end-to-end testing framework for the V16 Unified World Pipeline. Each wave adds independent value: Wave 0 establishes the framework foundation, subsequent waves build test layers that can run in isolation. The existing 5 functional E2E tests in `tests/e2e/test_v16_full_pipeline.py` remain unchanged throughout.

Implementation language: Python (pytest, Hypothesis, Playwright)

## Tasks

- [ ] 1. Framework foundation — config, artifact store, deterministic render
  - [ ] 1.1 Create test framework directory structure and config loader
    - Create `tests/e2e/framework/__init__.py`
    - Create `tests/e2e/config/e2e_config.yaml` with full configuration schema (visual regression thresholds, perceptual thresholds, time budgets, cloud config)
    - Implement `tests/e2e/framework/config_loader.py` — YAML parsing into dataclasses (`VisualRegressionConfig`, `StageConfig`, `PerceptualConfig`, `VisionQAConfig`, `TimeBudgetConfig`, `CloudConfig`)
    - _Requirements: 3.4, 6.1, 22.1–22.6_

  - [ ] 1.2 Implement artifact store for per-run test output management
    - Create `tests/e2e/framework/artifact_store.py`
    - Implement `ArtifactStore` class with `init_run(run_id)`, `store_artifact(layer, filename, data)`, `get_artifact_path(layer, filename)` methods
    - Organize artifacts under `tests/e2e/artifacts/{run_id}/` with subdirectories: visual, perceptual, scene, accessibility, gpu, vision_qa
    - Include artifact directory path in pytest failure output
    - _Requirements: 23.4, 23.5_

  - [ ] 1.3 Implement deterministic render configuration module
    - Create `tests/e2e/framework/deterministic_render.py`
    - Implement `DeterministicRenderConfig` dataclass with `antialias=False`, `preserveDrawingBuffer=True`, `seed=42`, fixed viewport, explicit `SRGBColorSpace`
    - Implement hardware ID detection (GPU model + driver version hash)
    - Implement `verify_determinism(page)` helper that confirms renderer settings via `window.__qa.getRendererInfo()`
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ] 1.4 Create shared conftest.py with fixtures and markers
    - Extend `tests/e2e/conftest.py` (or create if not present for the new test modules)
    - Add pytest markers: `nightly`, `gpu`, `proposed`, `layer("visual")`, `layer("scene")`, `layer("accessibility")`
    - Add `enforce_budget` autouse fixture that applies timeout per layer from config
    - Add `artifact_store` fixture that initializes per-run artifact directory
    - Add `e2e_config` fixture that loads and validates `e2e_config.yaml`
    - _Requirements: 22.1–22.6_

  - [ ]* 1.5 Write unit tests for config loader and artifact store
    - Test config loading with valid/invalid YAML
    - Test artifact store directory creation and file storage
    - Test hardware ID generation consistency
    - _Requirements: 6.1, 23.4_

- [ ] 2. QA harness — inject into browser.py and build Python bridge
  - [ ] 2.1 Inject QA harness JavaScript into browser.py compiled viewer output
    - Modify `src/unified_pipeline/compilers/browser.py` `_VIEWER_JS` template
    - Add conditional `window.__qa` object creation gated by `?qa=1` URL parameter check
    - Implement all QA API methods: `getObjectCount()`, `getObjectPosition(id)`, `getLighting()`, `triggerInteraction(id, action)`, `getSceneGraph()`, `captureFrame()`, `getRendererInfo()`
    - Ensure zero overhead in production (QA code present but only activates on `?qa=1`)
    - Verify `window.__qa` is NOT exposed without `?qa=1`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ] 2.2 Implement QA bridge Python module for Playwright ↔ __qa protocol
    - Create `tests/e2e/framework/qa_bridge.py`
    - Implement `QABridge` class wrapping Playwright page with typed methods: `get_object_count()`, `get_object_position(object_id)`, `get_lighting()`, `trigger_interaction(object_id, action)`, `get_scene_graph()`, `capture_frame()`, `get_renderer_info()`
    - Handle JSON serialization/deserialization between Python and browser JS
    - Add timeout handling and descriptive errors when `window.__qa` is unavailable
    - _Requirements: 7.1–7.6, 8.1–8.4_

  - [ ]* 2.3 Write unit tests for QA bridge serialization and error handling
    - Test bridge methods with mocked Playwright page
    - Test error handling when `window.__qa` is undefined
    - Test JSON parsing of scene graph data
    - _Requirements: 7.1–7.6_

- [ ] 3. Checkpoint — Ensure QA harness integration works
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Visual regression — screenshot capture, pixelmatch, baselines
  - [ ] 4.1 Implement screenshot capture module
    - Create `tests/e2e/framework/screenshot_capture.py`
    - Implement `ScreenshotCapture` class with `capture_stage(page, stage_name, camera_pose)` method
    - Generate filenames encoding stage name, pipeline model version, and capture timestamp
    - Ensure deterministic render settings are applied before capture
    - Store captures via `ArtifactStore`
    - _Requirements: 2.1–2.5, 1.1_

  - [ ] 4.2 Implement baseline manager with versioned golden baselines
    - Create `tests/e2e/framework/baseline_manager.py`
    - Implement `BaselineManager` class with `get_baseline(stage, model_version, hardware_id)`, `save_baseline(stage, image, metadata)`, `baseline_exists(stage)` methods
    - Organize baselines under `tests/e2e/baselines/{model_version}/{hardware_id}/`
    - Generate JSON sidecar metadata files (creation timestamp, commit hash, model version, hardware ID, camera pose, approval info)
    - Handle "baseline created" status when no baseline exists (not a failure)
    - _Requirements: 3.3, 4.1, 4.2, 4.3_

  - [ ] 4.3 Implement pixel diff module (pixelmatch wrapper)
    - Create `tests/e2e/framework/pixel_diff.py`
    - Implement `PixelDiff` class wrapping pixelmatch comparison
    - Support per-stage threshold configuration (0.1% for Canon/World, 1.0% for Dream_Preview/Blockout)
    - Generate diff images highlighting changed pixels on failure
    - Return structured comparison result (diff_pixel_count, diff_percentage, pass/fail, diff_image_path)
    - _Requirements: 3.1, 3.2, 3.4_

  - [ ] 4.4 Implement visual regression test module
    - Create `tests/e2e/test_visual_regression.py`
    - Implement test functions for each pipeline stage (dream_preview, blockout, canon, world)
    - Use `@pytest.mark.layer("visual")` marker for budget enforcement
    - Wire together: screenshot capture → baseline compare → pass/fail with artifacts
    - Store expected baseline, actual screenshot, and diff image on failure
    - Ensure total execution within 120s budget
    - _Requirements: 2.1–2.5, 3.1–3.5, 22.1, 23.1_

  - [ ]* 4.5 Write property tests for filename encoding and threshold gate logic
    - **Property 2: Screenshot Filename Encoding Completeness** — verify stage/version/timestamp round-trip
    - **Property 3: Threshold Gate Correctness** — verify pass/fail decisions for pixelmatch thresholds
    - **Property 5: Baseline Version Isolation** — verify baselines from different versions never share directories
    - **Validates: Requirements 2.5, 3.2, 3.4, 4.1**

- [ ] 5. Scene validation — object count, positions, lighting, interactions
  - [ ] 5.1 Implement scene validation test module
    - Create `tests/e2e/test_scene_validation.py`
    - Implement `test_object_count_matches_world_contract()` — compare `qa_bridge.get_object_count()` against WorldContract ObjectInstance count
    - Implement `test_object_positions_within_tolerance()` — compare each object position with configurable tolerance (default 0.01 world units)
    - Report missing/unexpected objects and position deltas
    - Use `@pytest.mark.layer("scene")` marker
    - _Requirements: 8.1–8.4_

  - [ ] 5.2 Implement lighting validation tests
    - Add `test_lighting_matches_world_contract()` to `test_scene_validation.py`
    - Compare light type, position (tolerance 0.01), color (tolerance 0.02 per RGB), intensity (tolerance 5%)
    - Report specific parameter, expected value, actual value, and delta on failure
    - _Requirements: 9.1–9.3_

  - [ ] 5.3 Implement interaction testing
    - Add interaction tests to `test_scene_validation.py`
    - Test click-to-open door transitions (within 1s)
    - Test grab-and-release physics settling (within 2s)
    - Test pushable object displacement and settling (within 2s)
    - Report object name, interaction type, expected state, actual state on failure
    - Ensure total scene validation within 60s budget
    - _Requirements: 10.1–10.4, 22.2_

  - [ ]* 5.4 Write property tests for scene validation logic
    - **Property 7: QA Harness Object Count Consistency** — generated scene data validates count matching
    - **Property 8: QA Harness Position Fidelity** — generated positions within tolerance
    - **Property 9: Lighting Validation Tolerance Correctness** — correct tolerance per parameter type
    - **Validates: Requirements 7.3, 7.4, 8.1, 8.2, 9.1–9.3**

- [ ] 6. Accessibility — axe-core, focus, contrast, responsive, keyboard
  - [ ] 6.1 Implement accessibility test module with axe-core integration
    - Create `tests/e2e/test_accessibility.py`
    - Integrate axe-core scanning via Playwright
    - Fail on "critical" or "serious" violations, warn on "moderate"/"minor"
    - Report impact level, WCAG criterion, and affected element selectors
    - Use `@pytest.mark.layer("accessibility")` marker
    - _Requirements: 11.1–11.3_

  - [ ] 6.2 Implement focus trap validation for approval dialogs
    - Add `test_focus_trap_in_approval_dialog()` — verify Tab cycles within dialog only
    - Add `test_escape_closes_dialog()` — verify Escape closes dialog and returns focus
    - Report element that received unexpected focus on failure
    - _Requirements: 12.1–12.3_

  - [ ] 6.3 Implement color contrast checks for HUD overlays
    - Add `test_hud_overlay_contrast()` — verify all HUD text meets 4.5:1 contrast ratio
    - Check status, stageTitle, details, sessionId elements
    - Report element, foreground color, background color, actual ratio on failure
    - _Requirements: 13.1, 13.2_

  - [ ] 6.4 Implement screen reader announcement and responsive layout tests
    - Add `test_stage_transition_announcements()` — verify `aria-live="polite"` updates with human-readable stage names within 2s
    - Add `test_responsive_layout()` — validate at 1920x1080, 1366x768, 1024x768, 375x667
    - Verify no elements clipped/overlapped, conversation panel and artifact preview independently scrollable on mobile
    - _Requirements: 14.1–14.3, 15.1–15.3_

  - [ ] 6.5 Implement keyboard navigation alternative tests
    - Add `test_arrow_key_movement()` — verify arrow keys provide equivalent movement to WASD
    - Add `test_tab_focus_cycle()` — verify Tab/Shift+Tab cycles through interactive objects
    - Add `test_enter_space_activation()` — verify Enter/Space activates focused object
    - Ensure total accessibility suite within 30s budget
    - _Requirements: 16.1–16.3, 22.3_

  - [ ]* 6.6 Write property tests for accessibility assertion logic
    - **Property 10: Accessibility Violation Severity Routing** — critical/serious → fail, moderate/minor → warn
    - **Property 11: Contrast Ratio Enforcement** — 4.5:1 threshold check with failure reporting
    - **Property 12: Stage Transition Announcement** — human-readable name validation (not machine identifiers)
    - **Property 13: Arrow Key Movement Equivalence** — equivalent camera displacement
    - **Validates: Requirements 11.2, 11.3, 13.1, 13.2, 14.1, 14.3, 16.1**

- [ ] 7. Checkpoint — Ensure PR fast tier passes
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. GPU infrastructure — ComfyUI health fix, real FLUX, artifact endpoints
  - [ ] 8.1 Implement ComfyUI health check resilience with exponential backoff
    - Modify `src/photo_pipeline/comfyui_client.py` health_check() method
    - Add retry logic: 3 retries with exponential backoff (2s, 4s, 8s)
    - Increase timeout to 15s on retry attempts (from initial 5s)
    - Log warning on successful retry (retry count + total delay)
    - Report failure with attempt count, total elapsed time, last error on exhaustion
    - _Requirements: 17.1–17.4_

  - [ ] 8.2 Implement real FLUX generation E2E test
    - Create `tests/e2e/test_gpu_generation.py`
    - Add `@pytest.mark.gpu` marker
    - Test dream_preview stage with real ComfyUI FLUX workflow (20s timeout)
    - Verify generated image has valid dimensions (min 512x512) and valid PNG/JPEG encoding
    - Record failure details: queue position, elapsed time, error message
    - _Requirements: 18.1–18.4_

  - [ ] 8.3 Implement generated artifact endpoint verification tests
    - Add endpoint tests to `test_gpu_generation.py`
    - Verify `/api/session/{session_id}/dream_preview` returns HTTP 200 with correct Content-Type
    - Verify pre-completion requests return HTTP 404 with JSON error body
    - Verify file size > 1KB (not empty/corrupted)
    - Verify `Cache-Control: no-store` header present
    - _Requirements: 19.1–19.4_

  - [ ]* 8.4 Write property tests for health check retry and artifact validation
    - **Property 14: Health Check Retry Timing** — exponential backoff 2s, 4s, 8s with correct reporting
    - **Property 15: Generated Image Validity** — dimensions >= 512x512, valid encoding
    - **Property 16: Artifact Endpoint Correctness** — HTTP 200, correct Content-Type, size > 1KB, no-store header
    - **Validates: Requirements 17.1, 17.3, 18.3, 19.1, 19.3, 19.4**

- [ ] 9. Perceptual fidelity — SSIM, LPIPS, CLIP composite gate
  - [ ] 9.1 Implement perceptual metrics computation module
    - Create `tests/e2e/framework/perceptual_metrics.py`
    - Implement `compute_ssim(image_a, image_b)` — returns float (higher is more similar)
    - Implement `compute_lpips(image_a, image_b)` — returns float (lower is more similar)
    - Implement `compute_clip_cosine(image_a, image_b)` — returns float (higher is more similar)
    - Each metric acquires VRAM lease from Resource_Arbiter before model loading
    - Release leases within 5s of computation completing
    - _Requirements: 5.2–5.4, 21.1, 21.3_

  - [ ] 9.2 Implement composite gate module
    - Create `tests/e2e/framework/composite_gate.py`
    - Implement `CompositeGate` class with configurable per-metric thresholds
    - Gate passes only when ALL metrics independently pass (SSIM >= 0.85, LPIPS <= 0.3, CLIP >= 0.9)
    - Report which metric failed, measured value, threshold, and delta on failure
    - Log all metric values (pass or fail) to structured JSON report
    - _Requirements: 5.5, 5.6, 6.3_

  - [ ] 9.3 Implement perceptual fidelity test module
    - Create `tests/e2e/test_perceptual_fidelity.py`
    - Add `@pytest.mark.nightly` marker
    - Test Canon-to-World perceptual comparison from identical camera pose
    - Wait for ComfyUI generation to complete before loading perceptual models (VRAM scheduling)
    - Store JSON metric report in artifacts on pass or fail
    - Handle VRAM timeout gracefully (skip metric with "vram_contention_timeout", no suite failure)
    - _Requirements: 5.1–5.6, 21.1–21.4, 22.4, 23.2_

  - [ ]* 9.4 Write property tests for composite gate logic
    - **Property 3: Threshold Gate Correctness** — SSIM pass iff >= threshold, LPIPS pass iff <= threshold, CLIP pass iff >= threshold, composite passes iff all pass
    - **Property 4: Composite Gate Failure Reporting** — failure report contains metric name, value, threshold, delta
    - **Property 6: Metric Report Completeness** — JSON contains all values, thresholds, status, timestamp
    - **Property 18: VRAM Lease Release Timing** — lease released within 5s of computation
    - **Validates: Requirements 3.2, 3.4, 5.2–5.6, 6.3, 21.3**

- [ ] 10. AI vision QA — qwen2.5vl semantic oracle
  - [ ] 10.1 Implement vision oracle module
    - Create `tests/e2e/framework/vision_oracle.py`
    - Implement `VisionOracle` class wrapping qwen2.5vl:7b model via Ollama
    - Submit World screenshot with seven-category QA checklist (geometry, count, camera, openings, finish, mood, scale)
    - Parse structured JSON verdict: `pass` (bool), `failed_checks` (list), `confidence` (0.0–1.0)
    - Schedule vision call after ComfyUI generation completes (VRAM scheduling via Resource_Arbiter)
    - Handle unavailability gracefully: return "vision_qa_unavailable" status, no failure
    - _Requirements: 20.1–20.5, 21.5_

  - [ ] 10.2 Implement vision QA test module
    - Create `tests/e2e/test_vision_qa.py`
    - Add `@pytest.mark.gpu` marker
    - Auto-accept when `pass == true` AND `confidence >= 0.8`
    - Log failed checks as warnings (advisory gate, not blocking) when `pass == false` or `confidence < 0.8`
    - Store vision model JSON verdict alongside screenshot in artifacts
    - Create `tests/e2e/config/vision_qa_checklist.json` with the seven-category checklist
    - _Requirements: 20.1–20.5, 22.6, 23.3_

  - [ ]* 10.3 Write property tests for vision verdict structure and routing
    - **Property 17: Vision Verdict Structure** — output contains `pass` (bool), `failed_checks` (list), `confidence` (float 0.0–1.0); auto-accept only when `pass == true` AND `confidence >= 0.8`
    - **Validates: Requirements 20.2, 20.3**

- [ ] 11. Checkpoint — Ensure nightly GPU tier passes
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. VRAM resource scheduling integration
  - [ ] 12.1 Extend Resource Arbiter with test-specific resource kinds
    - Modify `src/unified_pipeline/resource_arbiter.py`
    - Add `PERCEPTUAL_LPIPS`, `PERCEPTUAL_CLIP`, `VISION_QA` to `ResourceKind` enum
    - Implement VRAM lease timeout (60s) with graceful skip on timeout
    - Ensure sequential scheduling: FLUX → perceptual models → vision QA
    - _Requirements: 21.1–21.5_

  - [ ] 12.2 Implement VRAM scheduling in perceptual and vision test fixtures
    - Add `vram_lease` fixture to conftest.py that wraps Resource_Arbiter claim/release
    - Ensure perceptual tests wait for ComfyUI generation to complete before model loading
    - Ensure lease release within 5s of metric computation (enforce via fixture teardown)
    - Log "vram_contention_timeout" and skip metric without failing suite on 60s timeout
    - _Requirements: 21.1–21.5_

  - [ ]* 12.3 Write unit tests for VRAM scheduling logic
    - Test lease acquisition and release timing
    - Test timeout behavior at 60s
    - Test sequential scheduling order enforcement
    - _Requirements: 21.1–21.5_

- [ ] 13. Perceptual metric calibration support
  - [ ] 13.1 Implement calibration run capability
    - Add `calibrate()` method to `PerceptualMetrics` class
    - Compute metrics across a corpus of known-good Canon/World pairs in `tests/e2e/calibration_corpus/`
    - Report mean, standard deviation, and recommended thresholds per metric
    - Store calibration results in structured JSON
    - _Requirements: 6.1–6.3_

  - [ ]* 13.2 Write unit tests for calibration computation
    - Test mean/std/threshold computation with generated metric distributions
    - Test empty corpus handling
    - _Requirements: 6.2_

- [ ] 14. Self-improving loop — cloud failure analysis, coverage discovery, calibration
  - [ ] 14.1 Implement failure analyzer module
    - Create `tests/e2e/improvement/__init__.py`
    - Create `tests/e2e/improvement/failure_analyzer.py`
    - Collect failure artifacts (screenshots, diffs, metrics, logs) from nightly run
    - Submit bounded analysis prompt to cloud model via Ollama (`glm-5.2:cloud` or `deepseek-v3.1:671b-cloud`)
    - Parse structured JSON: `root_cause`, `suggested_fix`, `confidence`, `category` (regression/flaky/threshold/infrastructure/genuine_bug)
    - Tag "flaky" tests (confidence >= 0.8) for retry-tolerance review
    - Propose updated threshold for "threshold" category (confidence >= 0.8)
    - Store all results in `tests/e2e/artifacts/{run_id}/cloud_analysis.json`
    - _Requirements: 24.1–24.5_

  - [ ] 14.2 Implement coverage discoverer module
    - Create `tests/e2e/improvement/coverage_discoverer.py`
    - Submit current test manifest, WorldContract schema, and QA_Harness API surface to cloud model (`qwen3-coder:480b-cloud` or `gpt-oss:120b-cloud`)
    - Request identification of untested interaction combinations, uncovered WorldContract properties, missing edge cases
    - Output proposed test cases as executable pytest stubs in `tests/e2e/proposed/` with `@pytest.mark.proposed`
    - Never auto-promote: require human review and explicit approval
    - On approval: move to appropriate test directory, remove `@pytest.mark.proposed` marker
    - _Requirements: 25.1–25.5_

  - [ ] 14.3 Implement threshold calibrator module
    - Create `tests/e2e/improvement/threshold_calibrator.py`
    - Aggregate stored perceptual metric reports (50 nightly runs trigger)
    - Compute distribution: mean, std, min, max, percentiles
    - Submit to cloud model (`deepseek-v3.1:671b-cloud`) for threshold recommendation
    - Output to `tests/e2e/config/threshold_recommendations.json` with per-metric justification
    - Never auto-apply: require human config file update
    - _Requirements: 26.1–26.4_

  - [ ] 14.4 Implement checklist evolver module
    - Create `tests/e2e/improvement/checklist_evolver.py`
    - Trigger after 20+ vision QA results accumulated
    - Submit result corpus (verdicts, failed_checks, confidence) to cloud model
    - Analyze false positive categories, missed genuine issues, potential new categories
    - Output proposed revision to `tests/e2e/config/vision_qa_checklist_proposed.json` with diff against current
    - Never auto-modify active checklist: require human approval
    - _Requirements: 27.1–27.4_

  - [ ]* 14.5 Write property tests for cloud analysis verdict routing
    - **Property 19: Test Artifact Organization** — artifacts under `{run_id}/` with correct subdirectories, failure output includes path
    - **Property 20: Cloud Analysis Verdict Routing** — "flaky" tagged for review, "threshold" proposes updated value, stored in cloud_analysis.json
    - **Property 21: Proposed Test Format Validity** — valid pytest file with `@pytest.mark.proposed`, stored in `tests/e2e/proposed/`
    - **Property 22: Threshold Recommendation Structure** — JSON with per-metric thresholds and justification text
    - **Validates: Requirements 23.4, 23.5, 24.3–24.5, 25.3, 26.3**

- [ ] 15. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between major layers
- Property tests validate universal correctness properties from the design document
- The existing `tests/e2e/test_v16_full_pipeline.py` is never modified
- Wave ordering ensures each tier is independently runnable after its checkpoint
- PR fast tier (waves 0–6) completes before nightly GPU tier (waves 7–10)
- Self-improving loop (wave 8) is lowest priority and can be deferred

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["1.5", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["4.4", "4.5", "5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3", "5.4", "6.1", "6.2", "6.3"] },
    { "id": 6, "tasks": ["6.4", "6.5", "6.6"] },
    { "id": 7, "tasks": ["8.1", "12.1"] },
    { "id": 8, "tasks": ["8.2", "8.3", "8.4", "12.2", "12.3"] },
    { "id": 9, "tasks": ["9.1", "9.2"] },
    { "id": 10, "tasks": ["9.3", "9.4", "13.1", "13.2"] },
    { "id": 11, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 12, "tasks": ["14.1", "14.2", "14.3", "14.4"] },
    { "id": 13, "tasks": ["14.5"] }
  ]
}
```
