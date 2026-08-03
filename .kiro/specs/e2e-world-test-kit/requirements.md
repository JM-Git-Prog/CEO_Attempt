# Requirements Document

## Introduction

This specification defines the E2E World Test Kit — an LLM-driven automated playtester that exercises the V16 Unified World Pipeline as a real user would. The kit unifies all existing test layers (visual regression, perceptual fidelity, scene validation, accessibility, GPU generation, vision QA) under a single orchestrated run driven by a local LLM agent that simulates a human user journey from conversation through walkable 3D world.

The governing sentence: "Does this turn conversation into a validated place, preserve one truth per concern, let the user steer what matters, reach a walkable world, enable GAME and REAL behaviors, and compound approved work?"

The kit provides a single-command entry point (`python -m tests.e2e.world_test_kit run --prompt "..."`) that starts the server, creates a session, drives the full user journey, runs all test layers, produces a unified playtest report, and exits with pass/fail.

## Glossary

- **Playtester_Agent**: The local LLM (qwen3-coder-next via Ollama) that drives Playwright as a simulated user, making conversational decisions, evaluating AI responses, and navigating the 3D world
- **Vision_Evaluator**: The qwen2.5vl:7b model (via Ollama) used to evaluate screenshots for visual quality, scene accuracy, and subjective enjoyment criteria
- **Orchestrator**: The top-level coordinator that sequences all nine test layers, manages VRAM scheduling, collects results, and produces the unified report
- **Playtest_Report**: The structured JSON output summarizing pass/fail status, per-layer scores, detailed playtest evaluation, issues found, and improvement suggestions
- **Test_Layer**: One of nine sequential evaluation phases: health smoke, visual regression, scene validation, accessibility, perceptual fidelity, GPU generation, vision QA, LLM playtest, and self-improving loop
- **QA_Harness**: The existing `window.__qa` JavaScript object exposed in the Three.js viewer (when `?qa=1` is present) providing programmatic scene introspection
- **Canonical_Prompt**: The standard test input: "a small warm kitchen with a round table, two wooden chairs, a window with rain outside, and a door to a hallway"
- **Playtest_Session**: A complete orchestrated run from server startup through report generation, identified by a unique session ID
- **VRAM_Scheduler**: The component responsible for sequencing GPU-intensive operations (FLUX generation, vision model evaluation, perceptual metrics) to avoid OOM on the RTX 4090
- **Conversation_Turn**: A single exchange between the Playtester_Agent and the pipeline AI during the brief-building conversation phase
- **Navigation_Action**: A keyboard/mouse action issued by the Playtester_Agent to move through the 3D world (WASD, mouse look, interaction clicks)
- **Evaluation_Criterion**: One of the nine subjective quality dimensions scored by the Playtester_Agent (conversation_quality, blockout_accuracy, canon_realism, world_walkability, interaction_responsiveness, game_mode_coherence, real_mode_utility, overall_enjoyment, object_placement)
- **Layer_Result**: The pass/fail/skip outcome from a single test layer with associated metrics and artifacts
- **Graceful_Degradation**: The ability to skip unavailable test layers (GPU, vision) and still produce a valid partial report rather than failing the entire run

## Requirements

### Requirement 1: Single-Command Orchestrated Run

**User Story:** As a developer, I want to run the entire E2E playtest with a single command, so that I can validate the full pipeline without manually coordinating multiple test scripts.

#### Acceptance Criteria

1. WHEN a developer executes `python -m tests.e2e.world_test_kit run --prompt "<text>"`, THE Orchestrator SHALL start the dev server, create a fresh session, drive the full user journey, execute all applicable test layers, produce a Playtest_Report, and exit with code 0 (pass) or 1 (fail)
2. WHEN the `--prompt` flag is omitted, THE Orchestrator SHALL use the Canonical_Prompt as default input
3. WHEN the `--layers` flag is provided with a comma-separated list, THE Orchestrator SHALL execute only the specified test layers in their natural sequence order
4. WHEN the `--timeout` flag is provided, THE Orchestrator SHALL abort the entire run if the total elapsed time exceeds the specified value in seconds (default: 600)
5. IF the dev server fails to start within 30 seconds, THEN THE Orchestrator SHALL exit with code 2 and report a startup failure with the last server log lines
6. THE Orchestrator SHALL write the Playtest_Report JSON to `tests/e2e/artifacts/{session_id}/playtest_report.json` upon completion regardless of pass/fail outcome

### Requirement 2: LLM Playtester Conversation Agent

**User Story:** As a test engineer, I want an LLM agent to drive the conversation phase like a real user, so that the pipeline's conversational AI is tested end-to-end with realistic interaction patterns.

#### Acceptance Criteria

1. WHEN the Playtest_Session begins the conversation phase, THE Playtester_Agent SHALL type the provided prompt into the conversation input and submit it
2. WHEN the pipeline AI responds, THE Playtester_Agent SHALL read the response, evaluate whether the brief proposal covers all elements of the original prompt, and decide whether to approve or request changes
3. WHEN the Playtester_Agent identifies a missing or incorrect element in the AI's proposal, THE Playtester_Agent SHALL send a correction in natural language (not a command or keyword)
4. THE Playtester_Agent SHALL approve the brief within 5 conversation turns unless genuine issues remain unresolved
5. WHEN the brief is approved, THE Playtester_Agent SHALL click the approval UI element and wait for the pipeline to advance to the next stage
6. IF the conversation exceeds 8 turns without reaching brief approval, THEN THE Playtester_Agent SHALL force-approve with a note in the report that the conversation was abnormally long

### Requirement 3: Pipeline Stage Progression Monitoring

**User Story:** As a test engineer, I want the playtester to monitor and validate each pipeline stage transition, so that stage ordering and timing constraints are verified automatically.

#### Acceptance Criteria

1. WHEN the pipeline advances to a new stage (brief → plan → blockout → canon → world), THE Orchestrator SHALL record the transition timestamp and verify the stage matches the expected sequence
2. WHEN a stage transition does not occur within the configured timeout for that stage, THE Orchestrator SHALL record a timeout failure for that stage and attempt to continue to the next actionable state
3. THE Orchestrator SHALL record the wall-clock duration of each stage and include it in the Playtest_Report
4. IF any stage is skipped or occurs out of order, THEN THE Orchestrator SHALL mark the run as failed with a "stage_sequence_violation" error category
5. WHEN the pipeline presents an approval gate (blockout approval, canon approval), THE Playtester_Agent SHALL evaluate the artifact and approve within 10 seconds unless a genuine quality issue is detected

### Requirement 4: 3D World Navigation

**User Story:** As a test engineer, I want the LLM agent to navigate the rendered 3D world using keyboard controls, so that walkability and collision are tested through simulated player movement.

#### Acceptance Criteria

1. WHEN the pipeline reaches the world stage, THE Playtester_Agent SHALL issue WASD keyboard inputs via Playwright to move the player through the space
2. THE Playtester_Agent SHALL attempt to walk forward at least 3 meters, turn 90 degrees left, walk 2 meters, and turn to face the original direction — verifying basic navigation works without clipping through walls
3. WHEN the player position (reported via QA_Harness) does not change after a movement input, THE Playtester_Agent SHALL record a "movement_blocked" event with the current position and attempted direction
4. THE Playtester_Agent SHALL complete the navigation test within 30 seconds of entering the world stage
5. IF the player clips through a wall (position moves outside room bounds as defined by the WorldContract), THEN THE Playtester_Agent SHALL record a "clipping_violation" with before/after positions and the wall that was breached

### Requirement 5: Object Interaction Testing

**User Story:** As a test engineer, I want the LLM agent to trigger interactions on objects in the 3D world, so that WorldContract interaction bindings are verified through simulated user actions.

#### Acceptance Criteria

1. WHEN the world is loaded, THE Playtester_Agent SHALL query the QA_Harness for all interactive objects and attempt to interact with each one
2. WHEN a door object is present, THE Playtester_Agent SHALL click it and verify (via QA_Harness) that the door transitions to the open state within 2 seconds
3. WHEN a grabbable object is present, THE Playtester_Agent SHALL grab it, move the cursor, release it, and verify the object settles to a physics-stable state within 3 seconds
4. WHEN an interaction fails to produce the expected state change, THE Playtester_Agent SHALL record the object name, interaction type, expected outcome, and actual outcome in the Playtest_Report
5. THE Playtester_Agent SHALL complete all interaction tests within 60 seconds of entering the world stage

### Requirement 6: Screenshot Capture and Visual Evaluation

**User Story:** As a test engineer, I want the playtester to capture screenshots at key moments and evaluate them with the vision model, so that visual quality is assessed both objectively and subjectively.

#### Acceptance Criteria

1. THE Playtester_Agent SHALL capture a screenshot at each of these moments: after blockout render, after canon render, upon first world entry, after completing navigation, and after each interaction test
2. WHEN a screenshot is captured, THE Orchestrator SHALL submit it to the Vision_Evaluator (qwen2.5vl:7b) with context about what the image should depict based on the original prompt
3. THE Vision_Evaluator SHALL return a structured assessment for each screenshot including: scene_match (0-100 how well it matches the prompt), quality (0-100 render quality), and issues (list of observed problems)
4. WHEN the Vision_Evaluator is unavailable due to VRAM contention or model loading failure, THE Orchestrator SHALL skip visual evaluation for that screenshot and record "vision_unavailable" status without failing the run
5. THE Orchestrator SHALL store all captured screenshots in `tests/e2e/artifacts/{session_id}/screenshots/` with filenames encoding the capture moment

### Requirement 7: Playtest Evaluation Scoring

**User Story:** As a test engineer, I want the LLM agent to produce subjective quality scores across multiple dimensions, so that the playtest report captures a holistic assessment of the user experience.

#### Acceptance Criteria

1. WHEN the full user journey is complete, THE Playtester_Agent SHALL score each Evaluation_Criterion on a 0-100 scale based on its observations during the run
2. THE Playtester_Agent SHALL score conversation_quality based on: natural flow, absence of repetition, accurate interpretation of user intent, and completeness of the brief
3. THE Playtester_Agent SHALL score world_walkability based on: successful navigation without clipping, appropriate collision responses, and smooth movement
4. THE Playtester_Agent SHALL score interaction_responsiveness based on: proportion of interactions that succeeded, response timing, and physics behavior
5. THE Playtester_Agent SHALL compute an overall_score as the weighted average: conversation_quality (10%), blockout_accuracy (10%), canon_realism (15%), world_walkability (20%), object_placement (15%), interaction_responsiveness (15%), game_mode_coherence (5%), real_mode_utility (5%), overall_enjoyment (5%)
6. THE Orchestrator SHALL mark the playtest layer as "pass" when overall_score >= 60 and no individual criterion scores below 30

### Requirement 8: Unified Test Layer Orchestration

**User Story:** As a test engineer, I want all existing test layers unified under the orchestrator with proper sequencing and dependency management, so that one run exercises everything without conflicts.

#### Acceptance Criteria

1. THE Orchestrator SHALL execute test layers in this fixed sequence: (1) health smoke, (2) visual regression, (3) scene validation, (4) accessibility, (5) perceptual fidelity, (6) GPU generation, (7) vision QA, (8) LLM playtest, (9) self-improving loop
2. WHEN a test layer depends on artifacts from a previous layer (e.g., perceptual fidelity depends on screenshots from visual regression), THE Orchestrator SHALL pass artifact references forward rather than regenerating them
3. WHEN a non-critical layer fails, THE Orchestrator SHALL record the failure and continue to subsequent layers rather than aborting the entire run
4. THE Orchestrator SHALL classify layers as critical (health smoke, scene validation) or advisory (perceptual fidelity, vision QA, self-improving loop) — critical failures abort the run, advisory failures are recorded but do not affect the exit code
5. WHEN layers are skipped via `--layers` flag, THE Orchestrator SHALL satisfy downstream dependencies by loading cached artifacts from previous runs or marking dependent layers as "dependency_skipped"

### Requirement 9: VRAM Scheduling for Multi-Model Operations

**User Story:** As a test engineer, I want the orchestrator to schedule GPU-intensive operations sequentially to prevent OOM crashes, so that the vision model, perceptual metrics, and ComfyUI never compete for VRAM.

#### Acceptance Criteria

1. THE VRAM_Scheduler SHALL ensure that only one GPU-intensive model is loaded at any time: ComfyUI (FLUX/Hunyuan3D), qwen2.5vl:7b (vision evaluation), LPIPS model, or CLIP model
2. WHEN the Orchestrator needs to run vision evaluation, THE VRAM_Scheduler SHALL verify ComfyUI has released VRAM (below 4GB usage) before loading qwen2.5vl:7b
3. WHEN the Orchestrator transitions between GPU models, THE VRAM_Scheduler SHALL call the appropriate unload mechanism and wait for VRAM to drop below 4GB before loading the next model
4. IF VRAM cannot be freed within 60 seconds of requesting a model transition, THEN THE VRAM_Scheduler SHALL skip the pending operation and record "vram_timeout" in the layer result
5. THE VRAM_Scheduler SHALL batch all vision evaluation screenshots together into a single model-load session rather than loading/unloading the vision model per screenshot

### Requirement 10: Playtest Report Generation

**User Story:** As a developer, I want a structured JSON playtest report that summarizes all findings, so that I can quickly identify what passed, what failed, and what needs attention.

#### Acceptance Criteria

1. THE Reporter SHALL produce a JSON document containing: overall_pass (boolean), score (0-100), layers (dict mapping layer name to pass/fail/skip status), playtest (detailed evaluation object), timing (per-stage and per-layer durations), and metadata (session_id, prompt, timestamp, kit version)
2. THE playtest section SHALL contain: all nine Evaluation_Criterion scores, an issues list (strings describing specific problems found), and a suggestions list (strings with improvement recommendations)
3. WHEN the run completes, THE Reporter SHALL print a human-readable summary to stdout showing overall pass/fail, score, and any critical issues — limited to 20 lines
4. THE Reporter SHALL write the full JSON report to the artifacts directory and print the file path to stdout
5. IF any layer was skipped due to unavailability, THE Reporter SHALL include that layer in the report with status "skipped" and a reason string explaining why

### Requirement 11: Graceful Degradation

**User Story:** As a developer, I want the test kit to produce useful results even when optional infrastructure is unavailable, so that I can run partial playtests on machines without a GPU or without all Ollama models loaded.

#### Acceptance Criteria

1. WHEN the Playtester_Agent LLM (qwen3-coder-next) is unavailable, THE Orchestrator SHALL fall back to a scripted interaction mode that types the prompt, auto-approves all gates, and skips subjective evaluation — marking the playtest layer as "degraded"
2. WHEN the Vision_Evaluator (qwen2.5vl:7b) is unavailable, THE Orchestrator SHALL skip all visual evaluation steps and mark the vision QA layer as "skipped" without failing the run
3. WHEN ComfyUI is unavailable, THE Orchestrator SHALL skip GPU generation and perceptual fidelity layers, using placeholder artifacts for downstream layers that depend on generated images
4. WHEN Playwright browser automation fails to initialize, THE Orchestrator SHALL exit with code 2 and a clear error message — Playwright is a hard dependency that cannot be degraded
5. THE Orchestrator SHALL report its degradation status in the Playtest_Report metadata: a list of components that were unavailable and which layers were affected

### Requirement 12: GAME Mode Evaluation

**User Story:** As a test engineer, I want the playtester to evaluate GAME mode behavior, so that the game overlay's coherence and functionality are verified through simulated play.

#### Acceptance Criteria

1. WHEN the world is loaded and GAME mode is available, THE Playtester_Agent SHALL activate GAME mode via the mode toggle
2. THE Playtester_Agent SHALL verify that activating GAME mode does not change any visual property of the scene (geometry, materials, lighting remain identical)
3. THE Playtester_Agent SHALL attempt to trigger at least one game interaction (if game bindings exist) and verify the scoring or state change response
4. THE Playtester_Agent SHALL score game_mode_coherence based on: whether game rules are explained, whether object role bindings reference actual scene objects, and whether interactions produce meaningful game responses
5. IF GAME mode is not implemented (stubbed), THEN THE Playtester_Agent SHALL record "game_mode_stubbed" and assign a neutral score of 50 without failing

### Requirement 13: REAL Mode Evaluation

**User Story:** As a test engineer, I want the playtester to evaluate REAL mode behavior, so that tool binding responsiveness and data display are verified.

#### Acceptance Criteria

1. WHEN the world is loaded and REAL mode is available, THE Playtester_Agent SHALL activate REAL mode via the mode toggle
2. THE Playtester_Agent SHALL verify that activating REAL mode does not change any visual property of the scene (geometry, materials, lighting remain identical)
3. THE Playtester_Agent SHALL check whether bound surfaces display data indicators or placeholder content for their configured tool bindings
4. THE Playtester_Agent SHALL score real_mode_utility based on: whether bindings are configured, whether surfaces show data (even placeholder), and whether the mode clearly communicates its read-only nature
5. IF REAL mode is not implemented (stubbed), THEN THE Playtester_Agent SHALL record "real_mode_stubbed" and assign a neutral score of 50 without failing

### Requirement 14: Integration with Existing Test Framework

**User Story:** As a test engineer, I want the world test kit to integrate with pytest and the existing E2E framework, so that it can be run alongside other tests and shares configuration and artifact infrastructure.

#### Acceptance Criteria

1. THE kit SHALL expose a pytest-compatible test function in `tests/e2e/test_world_playtest.py` that runs the full orchestrated playtest and asserts on the overall_pass result
2. THE kit SHALL use the existing `tests/e2e/framework/config_loader.py` E2EConfig for shared settings (thresholds, model names, timeout values)
3. THE kit SHALL use the existing `tests/e2e/framework/artifact_store.py` for storing screenshots, reports, and diff images
4. THE kit SHALL use the existing `tests/e2e/framework/qa_bridge.py` QABridge for all window.__qa interactions in the 3D world
5. THE kit SHALL use the existing `tests/e2e/framework/vision_oracle.py` VisionOracle for seven-category vision QA checks
6. THE pytest test SHALL be marked with `@pytest.mark.e2e_playtest` so it can be selectively included or excluded from CI runs

### Requirement 15: Configuration and Extensibility

**User Story:** As a test engineer, I want the test kit to be configurable without code changes, so that prompts, timeouts, scoring weights, and model selections can be adjusted per environment.

#### Acceptance Criteria

1. THE kit SHALL load its configuration from `tests/e2e/config/world_test_kit.yaml` with sensible defaults for all values
2. THE configuration SHALL include: playtester model name, vision evaluator model name, per-stage timeouts, scoring weights for each Evaluation_Criterion, pass/fail thresholds, and layer enable/disable flags
3. WHEN a configuration value is missing from the YAML file, THE kit SHALL use a documented default value and log a warning identifying the defaulted field
4. THE configuration SHALL support environment variable overrides for CI environments using the pattern `WTK_<SECTION>_<KEY>` (e.g., `WTK_PLAYTESTER_MODEL=qwen3-coder-next`)
5. THE kit SHALL validate all configuration values at startup and fail fast with descriptive errors if any value is out of acceptable range

### Requirement 16: Self-Improving Loop Integration

**User Story:** As a test engineer, I want the orchestrator to feed playtest results into the self-improving loop, so that test coverage and evaluation criteria evolve based on accumulated findings.

#### Acceptance Criteria

1. WHEN the playtest completes, THE Orchestrator SHALL append the Playtest_Report to the improvement loop's result corpus at `tests/e2e/artifacts/playtest_corpus/`
2. WHEN the corpus accumulates 10 or more playtest reports since the last analysis, THE self-improving loop SHALL submit the corpus to a cloud reasoning model for pattern analysis
3. THE self-improving loop SHALL identify recurring issues (same object placement failures, same interaction bugs) and propose focused regression tests as pytest stubs in `tests/e2e/proposed/`
4. THE self-improving loop SHALL identify evaluation criteria that consistently score near 50 (uninformative) and propose either removal or refinement of those criteria
5. THE self-improving loop SHALL NOT modify active tests, configuration, or evaluation criteria without human approval — all proposals are stored as pending recommendations
