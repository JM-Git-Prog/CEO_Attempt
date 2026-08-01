# Requirements Document

## Introduction

This specification defines a comprehensive end-to-end testing framework for the V16 Unified World Pipeline. The pipeline converts natural language conversation into a Three.js walkable 3D world with physics, interactions, and mode overlays. The testing framework adds five layers atop the existing functional E2E tests (`tests/e2e/test_v16_full_pipeline.py`): visual regression, perceptual fidelity, 3D scene validation, accessibility, and real GPU generation testing.

The framework targets a PR CI budget of under 5 minutes for fast-feedback tests and a nightly schedule for GPU-intensive perceptual tests.

## Glossary

- **Pipeline**: The V16 Unified World Pipeline that transforms conversation into a walkable 3D world
- **Visual_Regression_Suite**: The Playwright screenshot + pixelmatch comparison layer that detects per-stage rendering changes against golden baselines
- **Perceptual_Fidelity_Gate**: The multi-metric comparison system (SSIM, LPIPS, CLIP) that validates Canon-to-World render identity
- **QA_Harness**: The `window.__qa` JavaScript object exposed in the Three.js viewer when the `?qa=1` URL parameter is present, providing programmatic scene introspection
- **WorldContract**: The finalized spatial authority document describing object instances, lighting, camera, and interactions for the compiled 3D scene
- **Canon**: The approved reference image representing the intended visual appearance of the final world from a specific camera pose
- **Dream_Preview**: A provisional FLUX-generated mood image produced during conversation (not spatial authority)
- **Blockout**: The plan-derived rough 3D layout render used for spatial approval
- **Golden_Baseline**: A versioned, PR-approved reference screenshot or metric snapshot used for regression detection
- **ComfyUI_Client**: The async HTTP client (`src/photo_pipeline/comfyui_client.py`) interfacing with ComfyUI on localhost:8188
- **Pixelmatch**: A pixel-level image comparison library that outputs diff pixel count against a configurable threshold
- **SSIM**: Structural Similarity Index Measure — perceptual metric comparing luminance, contrast, and structure
- **LPIPS**: Learned Perceptual Image Patch Similarity — deep network perceptual distance metric (lower is more similar)
- **CLIP_Cosine**: Cosine similarity between CLIP embeddings of two images (higher is more similar)
- **Deterministic_Render**: A Three.js render produced with antialiasing disabled, RNG seeded, and `preserveDrawingBuffer: true` to ensure frame-identical output across runs
- **Composite_Gate**: A pass/fail decision combining multiple perceptual metrics with independently calibrated thresholds
- **Accessibility_Suite**: The axe-core + custom assertion layer validating WCAG 2.1 AA compliance for the pipeline UI
- **VRAM_Contention**: A condition where GPU memory is shared across concurrent processes (ComfyUI, LPIPS, CLIP), causing timeouts or OOM errors
- **Resource_Arbiter**: The VRAM scheduling system (`src/unified_pipeline/resource_arbiter.py`) that manages GPU memory leases across concurrent operations (FLUX generation, vision models, perceptual metrics)
- **Seven_Category_QA**: The structured vision screening checklist (geometry, count, camera, openings, finish, mood, scale) evaluated by qwen2.5vl:7b against rendered images
- **Test_Improvement_Loop**: An automated process that leverages cloud reasoning models (via Ollama) to analyze test failures, discover coverage gaps, calibrate thresholds, and propose checklist improvements — all requiring human approval before changes take effect
- **Cloud_Reasoning_Model**: A large-parameter model accessed via the Ollama cloud channel (glm-5.2:cloud, deepseek-v3.1:671b-cloud, qwen3-coder:480b-cloud, gpt-oss:120b-cloud) used for test analysis and improvement tasks that exceed local model capacity

## Requirements

### Requirement 1: Deterministic Rendering Configuration

**User Story:** As a test engineer, I want the Three.js viewer to produce deterministic renders during test runs, so that pixel-level comparisons are reliable across executions.

#### Acceptance Criteria

1. WHEN the Visual_Regression_Suite initializes a test browser context, THE Pipeline SHALL configure the Three.js renderer with antialiasing disabled, a fixed random seed, and `preserveDrawingBuffer: true`
2. WHEN a Deterministic_Render is captured at a fixed camera pose, THE Visual_Regression_Suite SHALL produce a byte-identical PNG across consecutive runs on the same hardware and driver version
3. IF the renderer fails to initialize with deterministic settings, THEN THE Visual_Regression_Suite SHALL abort the test with a descriptive error identifying the missing capability

### Requirement 2: Per-Stage Screenshot Capture

**User Story:** As a test engineer, I want to capture screenshots at each pipeline stage from fixed camera poses, so that I can detect visual regressions in Dream_Preview, Blockout, Canon, and final World renders.

#### Acceptance Criteria

1. WHEN the Pipeline completes the dream_preview stage, THE Visual_Regression_Suite SHALL capture a screenshot at the configured camera pose for that stage
2. WHEN the Pipeline completes the blockout stage, THE Visual_Regression_Suite SHALL capture a screenshot at the configured camera pose for that stage
3. WHEN the Pipeline completes the canon stage, THE Visual_Regression_Suite SHALL capture a screenshot at the configured camera pose for that stage
4. WHEN the Pipeline reaches the final world render, THE Visual_Regression_Suite SHALL capture a screenshot from the WorldContract-defined first-person camera pose
5. THE Visual_Regression_Suite SHALL store each captured screenshot with a filename encoding the stage name, pipeline model version, and capture timestamp

### Requirement 3: Pixel-Level Regression Detection

**User Story:** As a test engineer, I want to compare stage screenshots against golden baselines using pixelmatch, so that I can detect unintended visual changes with configurable sensitivity.

#### Acceptance Criteria

1. WHEN a stage screenshot is captured, THE Visual_Regression_Suite SHALL compare the screenshot against the corresponding Golden_Baseline using Pixelmatch
2. WHEN the Pixelmatch diff pixel count exceeds the configured threshold for that stage, THE Visual_Regression_Suite SHALL fail the test and emit a diff image highlighting changed pixels
3. WHEN no Golden_Baseline exists for a stage, THE Visual_Regression_Suite SHALL save the current screenshot as the new baseline and mark the test as "baseline created" rather than failed
4. THE Visual_Regression_Suite SHALL support per-stage threshold configuration with defaults of 0.1% diff pixels for Canon and World, and 1.0% for Dream_Preview and Blockout
5. IF a Golden_Baseline update is required, THEN THE Visual_Regression_Suite SHALL require explicit PR approval before the new baseline replaces the existing one

### Requirement 4: Baseline Versioning

**User Story:** As a test engineer, I want golden baselines versioned per pipeline model, so that model upgrades produce new baseline sets without invalidating prior ones.

#### Acceptance Criteria

1. THE Visual_Regression_Suite SHALL organize Golden_Baselines in a directory structure keyed by pipeline model version identifier
2. WHEN the pipeline model version changes, THE Visual_Regression_Suite SHALL create a new baseline directory and treat all comparisons as "baseline created" until approved
3. THE Visual_Regression_Suite SHALL store baseline metadata (creation timestamp, commit hash, model version, hardware identifier) in a JSON sidecar file alongside each Golden_Baseline

### Requirement 5: Canon-to-World Perceptual Comparison

**User Story:** As a test engineer, I want to validate that the final 3D World render perceptually matches the approved Canon reference image, so that the "three-view identity" contract is enforced automatically.

#### Acceptance Criteria

1. WHEN the Pipeline completes the final world render, THE Perceptual_Fidelity_Gate SHALL render a World screenshot from the identical camera pose used for the Canon reference image
2. THE Perceptual_Fidelity_Gate SHALL compute SSIM between the Canon image and the World screenshot with a pass threshold of 0.85
3. THE Perceptual_Fidelity_Gate SHALL compute LPIPS distance between the Canon image and the World screenshot with a pass threshold of 0.3 (lower is better)
4. THE Perceptual_Fidelity_Gate SHALL compute CLIP_Cosine similarity between the Canon image and the World screenshot with a pass threshold of 0.9
5. THE Composite_Gate SHALL pass only when all three metrics (SSIM, LPIPS, CLIP_Cosine) independently meet their configured thresholds
6. IF any single metric in the Composite_Gate fails, THEN THE Perceptual_Fidelity_Gate SHALL report which metric failed, the measured value, the threshold, and the delta

### Requirement 6: Perceptual Metric Calibration

**User Story:** As a test engineer, I want perceptual thresholds to be empirically calibrated and configurable, so that the Composite_Gate reflects real pipeline quality without false positives.

#### Acceptance Criteria

1. THE Perceptual_Fidelity_Gate SHALL load metric thresholds from a configuration file allowing per-stage override without code changes
2. WHEN a calibration run is requested, THE Perceptual_Fidelity_Gate SHALL compute metrics across a corpus of known-good Canon/World pairs and report mean, standard deviation, and recommended thresholds
3. THE Perceptual_Fidelity_Gate SHALL log all computed metric values (pass or fail) to a structured JSON report for trend analysis

### Requirement 7: QA Harness Injection

**User Story:** As a test engineer, I want a programmatic QA harness exposed in the Three.js viewer, so that automated tests can introspect scene state without modifying the production viewer.

#### Acceptance Criteria

1. WHEN the URL contains the `?qa=1` query parameter, THE Pipeline SHALL expose a `window.__qa` object in the Three.js viewer providing scene introspection methods
2. WHEN the URL does not contain `?qa=1`, THE Pipeline SHALL not expose `window.__qa` or any QA-related code paths
3. THE QA_Harness SHALL provide a method to retrieve the count of loaded 3D objects in the scene
4. THE QA_Harness SHALL provide a method to retrieve the position (x, y, z) of any named object instance
5. THE QA_Harness SHALL provide a method to retrieve the current lighting configuration (type, position, color, intensity for each light)
6. THE QA_Harness SHALL provide a method to trigger an interaction on a named object (click, grab, release, push) and return the resulting state change

### Requirement 8: 3D Scene Object Validation

**User Story:** As a test engineer, I want to validate that the compiled Three.js scene contains the correct objects at the correct positions, so that WorldContract compliance is verified automatically.

#### Acceptance Criteria

1. WHEN a 3D scene validation test runs, THE QA_Harness SHALL report an object count matching the number of ObjectInstance entries in the WorldContract
2. WHEN a 3D scene validation test runs, THE QA_Harness SHALL report each object position within a configurable tolerance (default 0.01 world units) of the WorldContract-specified position
3. IF the scene object count does not match the WorldContract, THEN THE QA_Harness SHALL report which objects are missing or unexpected
4. IF an object position exceeds the configured tolerance, THEN THE QA_Harness SHALL report the object name, expected position, actual position, and Euclidean distance delta

### Requirement 9: 3D Scene Lighting Validation

**User Story:** As a test engineer, I want to validate that scene lighting matches the WorldContract specification, so that visual fidelity is maintained through the compilation step.

#### Acceptance Criteria

1. WHEN a lighting validation test runs, THE QA_Harness SHALL report each light's type, position, color, and intensity
2. THE QA_Harness SHALL compare reported lighting against the WorldContract lighting configuration with tolerances of 0.01 for position, 0.02 for RGB color components, and 5% for intensity
3. IF any lighting parameter exceeds its tolerance, THEN THE QA_Harness SHALL report the specific parameter, expected value, actual value, and delta

### Requirement 10: 3D Scene Interaction Testing

**User Story:** As a test engineer, I want to validate that interactive objects respond correctly to user actions, so that the WorldContract interaction bindings are verified.

#### Acceptance Criteria

1. WHEN a door object with a "click-to-open" interaction binding is clicked via the QA_Harness, THE Pipeline SHALL transition the door to the open state within 1 second
2. WHEN a grabbable object is grabbed and released via the QA_Harness, THE Pipeline SHALL return the object to a physics-stable resting state within 2 seconds
3. WHEN a pushable object is pushed via the QA_Harness, THE Pipeline SHALL move the object in the push direction and settle to a physics-stable state within 2 seconds
4. IF an interaction binding defined in the WorldContract fails to produce the expected state change, THEN THE QA_Harness SHALL report the object name, interaction type, expected state, and actual state

### Requirement 11: Accessibility — Axe-Core Integration

**User Story:** As a test engineer, I want automated accessibility scanning via axe-core, so that WCAG 2.1 AA violations are caught during CI.

#### Acceptance Criteria

1. WHEN an accessibility test runs against the pipeline UI, THE Accessibility_Suite SHALL execute an axe-core scan and report all violations with impact level, WCAG criterion, and affected element selectors
2. THE Accessibility_Suite SHALL fail the test when any "critical" or "serious" axe-core violation is detected
3. THE Accessibility_Suite SHALL log "moderate" and "minor" violations as warnings without failing the test

### Requirement 12: Accessibility — Focus Trap in Approval Dialogs

**User Story:** As a test engineer, I want to verify that approval dialogs trap keyboard focus correctly, so that keyboard users cannot accidentally interact with background content during approval gates.

#### Acceptance Criteria

1. WHEN an approval dialog is displayed, THE Accessibility_Suite SHALL verify that pressing Tab cycles focus only within the dialog elements
2. WHEN an approval dialog is displayed, THE Accessibility_Suite SHALL verify that pressing Escape closes the dialog and returns focus to the previously focused element
3. IF focus escapes the approval dialog while it is open, THEN THE Accessibility_Suite SHALL fail the test with the element that received unexpected focus

### Requirement 13: Accessibility — Color Contrast for HUD Overlays

**User Story:** As a test engineer, I want to verify that HUD overlay text meets WCAG AA color contrast requirements, so that status information is readable for users with low vision.

#### Acceptance Criteria

1. THE Accessibility_Suite SHALL verify that all text elements in the HUD overlay (status, stageTitle, details, sessionId) meet a minimum contrast ratio of 4.5:1 against their background
2. WHEN a HUD overlay text element fails the contrast check, THE Accessibility_Suite SHALL report the element, computed foreground color, computed background color, and actual contrast ratio

### Requirement 14: Accessibility — Screen Reader Announcements

**User Story:** As a test engineer, I want to verify that stage transitions are announced to screen readers, so that visually impaired users are informed of pipeline progress.

#### Acceptance Criteria

1. WHEN the Pipeline transitions between stages, THE Pipeline SHALL update an `aria-live="polite"` region with the new stage name
2. THE Accessibility_Suite SHALL verify that each stage transition produces a screen reader announcement within 2 seconds of the stage change event
3. THE Accessibility_Suite SHALL verify that the `aria-live` region contains the human-readable stage name (not a machine identifier)

### Requirement 15: Accessibility — Responsive Layout Validation

**User Story:** As a test engineer, I want to verify that the pipeline UI is usable across common viewport sizes, so that the interface works on varied display configurations.

#### Acceptance Criteria

1. THE Accessibility_Suite SHALL validate the pipeline UI layout at viewport sizes of 1920x1080, 1366x768, 1024x768, and 375x667
2. WHEN the viewport is resized, THE Accessibility_Suite SHALL verify that no interactive element is clipped, overlapped, or rendered off-screen
3. WHEN the viewport is 375x667 (mobile), THE Accessibility_Suite SHALL verify that the conversation panel and artifact preview remain independently scrollable

### Requirement 16: Accessibility — Keyboard Navigation Alternatives

**User Story:** As a test engineer, I want to verify that keyboard-only users have alternatives to WASD mouse-look navigation in the 3D world, so that the world is explorable without a pointing device.

#### Acceptance Criteria

1. THE Accessibility_Suite SHALL verify that arrow keys provide equivalent movement to WASD keys in the 3D world view
2. THE Accessibility_Suite SHALL verify that Tab and Shift+Tab cycle focus through interactive objects in the 3D world
3. THE Accessibility_Suite SHALL verify that Enter or Space activates the currently focused interactive object

### Requirement 17: ComfyUI Health Check Resilience

**User Story:** As a test engineer, I want the ComfyUI health check to tolerate VRAM contention during concurrent GPU operations, so that tests do not fail due to transient unavailability.

#### Acceptance Criteria

1. WHEN the ComfyUI_Client performs a health check and receives no response within 5 seconds, THE ComfyUI_Client SHALL retry the health check up to 3 times with exponential backoff (2s, 4s, 8s delays)
2. WHEN VRAM_Contention causes the health check to timeout, THE ComfyUI_Client SHALL increase the individual request timeout to 15 seconds for retry attempts
3. IF all health check retries fail, THEN THE ComfyUI_Client SHALL report the failure with the number of attempts, total elapsed time, and last error received
4. WHEN the health check succeeds after retries, THE ComfyUI_Client SHALL log a warning indicating the retry count and total delay incurred

### Requirement 18: Real FLUX Image Generation in Tests

**User Story:** As a test engineer, I want E2E tests to exercise real FLUX image generation through ComfyUI, so that the dream_preview stage is validated with actual GPU output rather than placeholders.

#### Acceptance Criteria

1. WHEN a GPU E2E test exercises the dream_preview stage, THE Pipeline SHALL submit a FLUX workflow to ComfyUI and receive a generated image within 20 seconds
2. WHEN ComfyUI returns a generated image, THE Pipeline SHALL serve the image at the `/api/session/{session_id}/dream_preview` endpoint with correct Content-Type headers
3. THE Pipeline SHALL verify that the generated dream_preview image has valid dimensions (minimum 512x512 pixels) and valid PNG or JPEG encoding
4. IF ComfyUI fails to generate an image within the timeout, THEN THE Pipeline SHALL record the failure with ComfyUI queue position, elapsed time, and error message

### Requirement 19: Generated Artifact Endpoint Verification

**User Story:** As a test engineer, I want to verify that generated artifacts are served correctly via API endpoints, so that the frontend receives valid images throughout the pipeline.

#### Acceptance Criteria

1. WHEN a stage artifact is generated, THE Pipeline SHALL serve the artifact at the corresponding API endpoint with HTTP 200 and correct Content-Type (image/png or image/jpeg)
2. WHEN a test requests an artifact endpoint before the stage has completed, THE Pipeline SHALL respond with HTTP 404 and a JSON error body indicating the stage is not yet complete
3. THE Pipeline SHALL verify that served artifact file sizes are greater than 1KB (ruling out empty or corrupted files)
4. WHEN a generated artifact is served, THE Pipeline SHALL include cache-busting headers (Cache-Control: no-store) to prevent stale artifact caching during tests

### Requirement 20: AI Vision Model Semantic Validation

**User Story:** As a test engineer, I want to use the local qwen2.5vl:7b vision model as a semantic test oracle, so that E2E tests can verify that rendered scenes match the conversation intent beyond pixel-level metrics.

#### Acceptance Criteria

1. WHEN an E2E test completes the final world render, THE Visual_Regression_Suite SHALL submit the World screenshot to the qwen2.5vl:7b model with the seven-category QA checklist (geometry, count, camera, openings, finish, mood, scale)
2. THE Visual_Regression_Suite SHALL require a structured JSON verdict from the vision model containing `pass` (boolean), `failed_checks` (list), and `confidence` (0.0-1.0)
3. WHEN the vision model returns `pass: true` and `confidence >= 0.8`, THE Visual_Regression_Suite SHALL accept the semantic validation without further review
4. WHEN the vision model returns `pass: false` or `confidence < 0.8`, THE Visual_Regression_Suite SHALL log the failed checks as warnings without failing the test (advisory gate, not blocking)
5. IF the vision model is unavailable due to VRAM_Contention or timeout, THEN THE Visual_Regression_Suite SHALL skip semantic validation with a "vision_qa_unavailable" status and continue without failure

### Requirement 21: VRAM Resource Scheduling for Tests

**User Story:** As a test engineer, I want GPU-intensive tests to respect VRAM scheduling, so that concurrent GPU operations (ComfyUI FLUX, LPIPS, CLIP, qwen2.5vl) do not cause OOM failures.

#### Acceptance Criteria

1. WHEN a perceptual test requires LPIPS or CLIP model loading, THE Perceptual_Fidelity_Gate SHALL acquire a VRAM lease from the Resource_Arbiter before loading the model
2. WHEN ComfyUI is actively generating (FLUX or Hunyuan3D), THE Perceptual_Fidelity_Gate SHALL wait for the generation to complete before loading perceptual models into VRAM
3. THE Perceptual_Fidelity_Gate SHALL release VRAM leases (unload models) within 5 seconds of completing metric computation
4. IF a VRAM lease cannot be acquired within 60 seconds, THEN THE Perceptual_Fidelity_Gate SHALL skip the metric and report "vram_contention_timeout" without failing the overall test suite
5. WHEN the qwen2.5vl:7b vision model is needed for semantic validation, THE Visual_Regression_Suite SHALL schedule the vision call after ComfyUI generation completes to avoid the combined 12GB (FLUX) + 8GB (vision) VRAM requirement

### Requirement 22: Test Execution Time Budgets

**User Story:** As a test engineer, I want test suites segmented by execution time, so that PR CI completes within 5 minutes while heavier tests run nightly.

#### Acceptance Criteria

1. THE Visual_Regression_Suite SHALL complete all per-stage screenshot captures and Pixelmatch comparisons within 120 seconds for a single pipeline run
2. THE QA_Harness 3D validation tests SHALL complete within 60 seconds for a single pipeline run
3. THE Accessibility_Suite SHALL complete all checks within 30 seconds
4. THE Perceptual_Fidelity_Gate (SSIM, LPIPS, CLIP) SHALL be marked with a `@pytest.mark.nightly` marker and excluded from default PR CI runs
5. THE GPU generation tests SHALL be marked with a `@pytest.mark.gpu` marker and run only on CI runners with NVIDIA GPU access
6. THE AI vision semantic validation tests SHALL be marked with a `@pytest.mark.gpu` marker since they require the qwen2.5vl:7b model loaded into VRAM

### Requirement 23: Test Report and Artifact Storage

**User Story:** As a test engineer, I want structured test reports and artifacts stored per run, so that failures are diagnosable and trends are trackable.

#### Acceptance Criteria

1. WHEN a Visual_Regression_Suite test fails, THE Visual_Regression_Suite SHALL store the expected baseline, actual screenshot, and diff image in a test artifacts directory
2. WHEN a Perceptual_Fidelity_Gate test completes (pass or fail), THE Perceptual_Fidelity_Gate SHALL store a JSON report with all computed metrics, thresholds, and pass/fail status
3. WHEN an AI vision semantic validation completes, THE Visual_Regression_Suite SHALL store the vision model JSON verdict alongside the screenshot in the test artifacts directory
4. THE Pipeline SHALL organize test artifacts under `tests/e2e/artifacts/{run_id}/` with subdirectories for each test layer (visual, perceptual, scene, accessibility, gpu, vision_qa)
5. WHEN any test fails, THE Pipeline SHALL include the artifact directory path in the pytest failure output for immediate developer access

### Requirement 24: Cloud Model Test Failure Analysis

**User Story:** As a test engineer, I want cloud reasoning models to analyze test failures and suggest fixes, so that the test suite becomes self-diagnosing and reduces manual triage time.

#### Acceptance Criteria

1. WHEN a nightly test run produces failures, THE Test_Improvement_Loop SHALL collect failure artifacts (screenshots, diff images, metric reports, error logs) and submit a bounded analysis prompt to a cloud model via Ollama (glm-5.2:cloud or deepseek-v3.1:671b-cloud)
2. THE Test_Improvement_Loop SHALL request structured JSON output containing `root_cause` (string), `suggested_fix` (string), `confidence` (0.0-1.0), and `category` (one of: regression, flaky, threshold, infrastructure, genuine_bug)
3. WHEN the cloud model identifies a failure as "flaky" with confidence >= 0.8, THE Test_Improvement_Loop SHALL tag the test for retry-tolerance review
4. WHEN the cloud model identifies a failure as "threshold" with confidence >= 0.8, THE Test_Improvement_Loop SHALL propose an updated threshold value based on the metric distribution
5. THE Test_Improvement_Loop SHALL store all cloud analysis results in `tests/e2e/artifacts/{run_id}/cloud_analysis.json` for human review

### Requirement 25: Cloud Model Test Coverage Discovery

**User Story:** As a test engineer, I want cloud reasoning models to discover coverage gaps and propose new test scenarios, so that the test suite evolves to cover edge cases humans might miss.

#### Acceptance Criteria

1. WHEN a weekly coverage analysis is triggered, THE Test_Improvement_Loop SHALL submit the current test manifest, WorldContract schema, and QA_Harness API surface to a cloud reasoning model (qwen3-coder:480b-cloud or gpt-oss:120b-cloud)
2. THE Test_Improvement_Loop SHALL request the cloud model to identify untested interaction combinations, uncovered WorldContract properties, and missing edge cases
3. THE Test_Improvement_Loop SHALL output proposed test cases as executable pytest stubs in `tests/e2e/proposed/` with `@pytest.mark.proposed` markers
4. THE Test_Improvement_Loop SHALL not promote proposed tests to the active suite without human review and explicit approval
5. WHEN a proposed test is approved, THE Test_Improvement_Loop SHALL move the test file to the appropriate test directory and remove the `@pytest.mark.proposed` marker

### Requirement 26: Perceptual Threshold Calibration via Cloud Models

**User Story:** As a test engineer, I want cloud models to recommend optimal perceptual thresholds based on accumulated metric data, so that the Composite_Gate balances sensitivity against false positives.

#### Acceptance Criteria

1. WHEN a calibration cycle is triggered (monthly or after 50 nightly runs), THE Test_Improvement_Loop SHALL aggregate all stored perceptual metric reports (SSIM, LPIPS, CLIP values from passing and failing runs)
2. THE Test_Improvement_Loop SHALL submit the metric distribution (mean, std, min, max, percentiles) to a cloud reasoning model with the instruction to recommend thresholds that reject genuine regressions while accepting normal variance
3. THE Test_Improvement_Loop SHALL output recommended thresholds to `tests/e2e/config/threshold_recommendations.json` with justification text for each metric
4. THE Test_Improvement_Loop SHALL not apply threshold changes automatically; recommendations require human review and config file update

### Requirement 27: Vision QA Checklist Evolution

**User Story:** As a test engineer, I want the seven-category vision QA checklist to improve over time based on failure patterns, so that the vision oracle catches more real issues and generates fewer false signals.

#### Acceptance Criteria

1. WHEN 20 or more vision QA results have accumulated since the last evolution cycle, THE Test_Improvement_Loop SHALL submit the result corpus (verdicts, failed_checks, confidence scores, and corresponding screenshots described textually) to a cloud reasoning model
2. THE Test_Improvement_Loop SHALL request analysis of which categories produce the most false positives, which categories miss genuine issues, and what new categories might be valuable
3. THE Test_Improvement_Loop SHALL output a proposed checklist revision to `tests/e2e/config/vision_qa_checklist_proposed.json` with change justification
4. THE Test_Improvement_Loop SHALL not modify the active checklist without human approval; the proposed revision includes a diff against the current checklist
