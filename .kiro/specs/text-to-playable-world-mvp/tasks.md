# Implementation Plan: Text-to-Playable-World MVP

## Overview

This plan implements the MVP pipeline that transforms a text description into a running 3D game via UPBGE. The implementation follows the critical path: MVP tolerance validation → lane ladder routing → pipeline orchestration → compilation + smoke → auto-launch → web interface. Each task builds incrementally, wiring components together as they're completed.

All code is Python (FastAPI, Pydantic, Hypothesis). The project already has existing pipeline infrastructure — this plan adds MVP mode branching, relaxed validation, model routing, structural smoke validation, blenderplayer auto-launch, session management, and web interface enhancements.

## Tasks

- [x] 1. Core data models and interfaces
  - [x] 1.1 Create MVP data models and enums
    - Add `SessionMode` enum (`mvp`, `full`) to session models
    - Create `LaunchResult` frozen dataclass in `src/auto_launch.py`
    - Create `MVPPipelineResult` frozen dataclass
    - Create `PlanValidationWarning` frozen dataclass
    - Create `LaneDef` frozen dataclass in `src/lane_ladder.py`
    - Create `SmokeValidationResult` and `SmokeCheck` frozen dataclasses in `src/smoke_validator.py`
    - Create `StageFailure` frozen dataclass for structured error propagation
    - Extend `WorldSession` model with `mode`, `quality_label`, `game_pid` fields
    - _Requirements: 1.5, 8.5, 10.1, 12.5_

  - [x] 1.2 Extend `UPBGECapabilityReport` with blenderplayer fields
    - Add `blenderplayer_path: str | None`, `blenderplayer_available: bool`, `blenderplayer_verified: bool`, `blenderplayer_reason_code: str`, `blenderplayer_diagnostics: tuple[str, ...]` to the existing capability report dataclass in `src/upbge_capabilities.py`
    - Implement blenderplayer discovery logic: look alongside editor executable, probe with `--version` or minimal .blend test file, confirm clean exit
    - Handle states: editor+player present, editor present+player absent, editor absent
    - _Requirements: 7.1, 1.8_

- [x] 2. MVP Tolerance — Plan Validation
  - [x] 2.1 Implement MVP tolerance mode in Plan Validator
    - Modify `validate_floor_plan()` in `src/floor_plan/validator.py` to accept a `tolerance: Literal["strict", "mvp"] | None` parameter
    - Implement threshold logic: accept overlaps ≤0.1m, relationship offsets ≤0.2m, clearance violations ≤0.15m as warnings (not rejections)
    - Maintain structural impossibility rejections: vertex outside room bounds, zero-dimension room, missing dimensions, duplicate stable IDs
    - Return `PlanValidationReport` with warnings list containing type, affected ID, measured deviation
    - Default to MVP tolerance when `tolerance=None` and `strict=False`
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 Write property test for MVP tolerance acceptance/rejection (Property 2)
    - **Property 2: MVP Tolerance — Non-Critical Acceptance vs Structural Rejection**
    - Generate floor plans with Hypothesis: plans with only non-critical violations must pass; plans with structural impossibilities must reject
    - **Validates: Requirements 2.2**

  - [x] 2.3 Implement warnings recording in Compiler Manifest
    - When MVP tolerance accepts a plan with warnings, record each warning (type, affected_id, measured_deviation) in the `Compiler_Manifest` output
    - _Requirements: 2.5_

  - [x] 2.4 Write property test for warnings recorded in manifest (Property 3)
    - **Property 3: Warnings Recorded in Manifest**
    - For any plan accepted under MVP tolerance with warnings, verify every warning appears in the manifest
    - **Validates: Requirements 2.5**

- [x] 3. Lane Ladder — Model Routing
  - [x] 3.1 Implement Lane Ladder module (`src/lane_ladder.py`)
    - Define `LANE_LADDER` list: `planner-probe-v1:latest` (priority 1, 20s), `gpt-oss:20b` (priority 2, 25s), `qwen3.6:27b` (priority 3, 30s)
    - Define `CLOUD_FALLBACK` list (only used after all local lanes exhaust)
    - Implement `generate_plan_with_ladder()` async function: attempt primary lane, on structural rejection retry same model with simplified prompt, then escalate to next lane
    - Implement progressive prompt simplification: attempt 1 = full prompt, attempt 2 = remove relationship constraints, attempt 3 = escalate lane + remove relationship + clearance constraints
    - Track which model + attempt produced the accepted plan in `MVPPipelineResult.model_used` and `.attempts`
    - Integrate with local Ollama for all local lanes
    - _Requirements: 2.3, 1.7, 10.1_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Session Manager and FIFO Queue
  - [ ] 5.1 Implement Session Manager (`src/session_manager.py`)
    - `create_session(description, mode)` → generates UUID, creates isolated output directory under `output/sessions/{uuid}/` with `input/`, `output/`, `tmp/` subdirectories
    - `mark_failed_on_restart()` → on startup, mark any incomplete sessions as failed with `reason_code: "server_restart"`
    - Enforce unique session IDs (random UUID), never reuse directories even for identical descriptions
    - _Requirements: 12.2, 12.4, 12.5, 12.6_

  - [ ] 5.2 Implement FIFO compilation queue
    - `SessionQueue` class with asyncio lock: max 1 active UPBGE compilation at a time
    - `enqueue(session)` → start immediately if no active compilation, else append to deque
    - `complete(session_id)` → mark done, start next pending session from deque
    - Pre-compilation stages (interpret, plan, validate, scene graph) can proceed concurrently; only sidecar compilation is serialized
    - _Requirements: 12.1_

  - [ ]* 5.3 Write property test for FIFO queue ordering (Property 19)
    - **Property 19: FIFO Queue Ordering**
    - For any sequence of session submissions arriving while a compilation is active, verify FIFO ordering is preserved
    - **Validates: Requirements 12.1**

  - [ ]* 5.4 Write property test for session isolation (Property 18)
    - **Property 18: Session Isolation Invariant**
    - For any set of sessions (even with identical descriptions), verify unique UUIDs, exclusive output directories, no cross-session file references
    - **Validates: Requirements 12.2, 12.5**

- [ ] 6. Smoke Validator
  - [ ] 6.1 Implement Smoke Validator module (`src/smoke_validator.py`)
    - Create `smoke_probe.py` script that runs inside UPBGE_Editor `--background` mode
    - Implement 4 structural checks via bpy: (1) player controller text datablock exists and is non-empty, (2) at least one object has Character physics type, (3) logic brick controllers are wired to target objects, (4) scene loads without bpy errors
    - `run_structural_smoke(capability, blend_path, runtime_plan, timeout_s=15.0)` → invoke UPBGE_Editor with `--background blend_path --python smoke_probe.py`, parse JSON result from stdout
    - Return `SmokeValidationResult` with individual check results and overall pass/fail
    - Does NOT enter game mode, does NOT open a visible window, does NOT launch blenderplayer
    - _Requirements: 8.3, 8.4, 8.5_

- [ ] 7. Auto-Launcher
  - [ ] 7.1 Implement Auto-Launcher module (`src/auto_launch.py`)
    - `auto_launch_game(capability, blend_path, fullscreen=True, timeout_s=10.0)` → verify blend_path exists + non-zero, discover blenderplayer from `capability.blenderplayer_path`
    - Construct launch command: `blenderplayer -f 0 0 path/to/file.blend` (fullscreen) or `blenderplayer path/to/file.blend` (windowed)
    - Start subprocess non-blocking, wait up to timeout_s for process to NOT exit (confirms running)
    - Return `LaunchResult` with PID, success status, reason_code
    - On failure: generate `fallback_instructions` with platform-specific manual launch instructions
    - _Requirements: 1.1, 1.2, 1.8, 9.2_

- [ ] 8. Pipeline Orchestrator — MVP Branch
  - [ ] 8.1 Implement `run_mvp()` method in Pipeline Orchestrator
    - Add MVP mode branch to `src/pipeline.py`
    - Implement shortened pipeline: interpret → plan (lane ladder) → scene graph → WorldContract → CompilerPlan+RuntimePlan → sidecar compile → parity gate → smoke validator → auto-launch
    - Skip canon image generation and composition validation stages in MVP mode (Req 2.4)
    - Emit SSE events at each stage transition: `interpreting`, `planning`, `building_scene`, `compiling`, `validating`, `launching`, `game_running`
    - Integrate session manager for output directory isolation
    - Integrate FIFO queue — serialize only the sidecar compilation stage
    - _Requirements: 1.1, 1.3, 2.4, 10.1, 10.2_

  - [ ] 8.2 Implement input validation gate
    - Reject empty strings, strings < 3 characters, strings > 500 characters with descriptive validation error BEFORE invoking any LLM stage
    - _Requirements: 1.6_

  - [ ]* 8.3 Write property test for input length validation (Property 1)
    - **Property 1: Input Length Validation**
    - For any string input, verify rejection iff char count < 3 or > 500, and no LLM invocation occurs on rejection
    - **Validates: Requirements 1.6**

  - [ ] 8.4 Implement parity gate check
    - Verify scene inventory JSON contains all expected object IDs from CompilerPlan with no missing IDs
    - Verify total object count matches expected count
    - On failure: list each discrepancy (missing IDs, count mismatch) — hard stop
    - _Requirements: 8.1, 8.2_

  - [ ]* 8.5 Write property test for parity gate ID verification (Property 10)
    - **Property 10: Parity Gate ID Verification**
    - For any CompilerPlan with expected IDs E and inventory with actual IDs A, parity passes iff E ⊆ A AND |A| == |E|; failure lists E \ A
    - **Validates: Requirements 8.1, 8.2**

  - [ ]* 8.6 Write property test for quality label determination (Property 11)
    - **Property 11: Quality Label Determination**
    - For any (parity_passed, smoke_passed) combination, verify correct quality label assignment
    - **Validates: Requirements 8.5**

  - [ ] 8.7 Implement structured error reporting and graceful degradation
    - Every stage returns success result or `StageFailure` — no exceptions that corrupt session state
    - On pipeline failure: report stage name, reason_code, diagnostic message to web interface
    - Graceful degradation chain: smoke fails → proceed with `smoke_skipped`; launch fails → download link fallback; parity fails → hard stop
    - _Requirements: 1.5, 1.8, 9.5_

  - [ ]* 8.8 Write property test for pipeline error reporting (Property 17)
    - **Property 17: Pipeline Error Reporting Preserves Session State**
    - For any stage failure, verify result contains stage name + reason_code + diagnostic, and session state remains uncorrupted
    - **Validates: Requirements 1.5**

- [ ] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Serialization and Contract Integrity
  - [ ] 10.1 Implement canonical JSON serialization constraints
    - Ensure serializer rejects non-finite numbers (NaN, Infinity, -Infinity)
    - Enforce sorted keys, no-whitespace separators (`,` and `:`), UTF-8 encoding
    - Ensure deserialization raises validation error on non-conforming input (missing fields, unknown fields, type mismatches) identifying the first bad element
    - _Requirements: 11.4, 11.5_

  - [ ]* 10.2 Write property test for serialization round-trip (Property 12)
    - **Property 12: WorldContract Serialization Round-Trip**
    - For any valid WorldContract, serialize → deserialize produces structurally equal instance
    - **Validates: Requirements 11.1**

  - [ ]* 10.3 Write property test for CompilerPlan deterministic hash (Property 13)
    - **Property 13: CompilerPlan Deterministic Hash**
    - Building CompilerPlan twice with identical inputs produces identical SHA-256 hash
    - **Validates: Requirements 11.2**

  - [ ]* 10.4 Write property test for RuntimePlan template hash integrity (Property 14)
    - **Property 14: RuntimePlan Template Hash Integrity**
    - Each template source SHA-256 matches corresponding entry in template_hashes
    - **Validates: Requirements 11.3**

  - [ ]* 10.5 Write property test for canonical JSON format constraints (Property 15)
    - **Property 15: Canonical JSON Format Constraints**
    - Non-finite numbers rejected; keys sorted; separators are `,`/`:`; encoding is UTF-8
    - **Validates: Requirements 11.4**

  - [ ]* 10.6 Write property test for deserialization validation errors (Property 16)
    - **Property 16: Deserialization Validation Errors**
    - Non-conforming bytes raise validation error with identified element, never silently coerce
    - **Validates: Requirements 11.5**

- [ ] 11. Web Interface — SSE Progress and Auto-Launch Trigger
  - [ ] 11.1 Add MVP mode endpoints and SSE progress
    - Modify `/describe` endpoint in `src/web/app.py` to accept `mode` parameter (default: `"mvp"`)
    - Implement SSE event stream delivering stage transitions within 2 seconds of occurrence
    - Stage events: `interpreting`, `planning`, `building_scene`, `compiling`, `validating`, `launching`, `game_running`
    - On success: automatically trigger auto-launch without user interaction beyond initial "Generate"
    - On game running: display "Game Running" status with "Download .blend" secondary action
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 11.2 Implement failure display and launch fallback in web interface
    - On pipeline failure: display failed stage name and human-readable reason (not generic error)
    - On auto-launch failure: present download link with platform-specific manual launch instructions
    - Provide download link for successful compilations as secondary action
    - _Requirements: 9.4, 9.5, 1.4, 1.8_

  - [ ] 11.3 Preserve existing V3-V10 interface behavior
    - Ensure all existing routes and behavior for non-MVP sessions remain unchanged
    - Default to MVP mode when no mode specified at session creation (Req 10.4)
    - Full mode (existing V11) remains selectable via mode parameter
    - _Requirements: 10.2, 10.3, 10.4, 9.6_

- [ ] 12. Player Controller and Door Interaction (RuntimePlan validation)
  - [ ] 12.1 Implement player controller math utilities
    - Movement speed normalization: diagonal input (two keys) produces normalized direction vector so combined speed ≤ max_speed
    - Vertical look angle clamping to ±85°
    - Spawn repositioning: spiral search outward from floor center in 0.5m increments (up to 8 attempts), fallback to ceiling_height - 0.5m drop
    - _Requirements: 4.2, 4.3, 4.7_

  - [ ]* 12.2 Write property test for player movement speed normalization (Property 4)
    - **Property 4: Player Movement Speed Normalization**
    - For any WASD input combination and max_speed, resulting vector magnitude ≤ max_speed
    - **Validates: Requirements 4.2**

  - [ ]* 12.3 Write property test for vertical look angle clamping (Property 5)
    - **Property 5: Vertical Look Angle Clamping**
    - For any sequence of mouse Y-axis movements, vertical angle stays within [-85°, +85°]
    - **Validates: Requirements 4.3**

  - [ ]* 12.4 Write property test for obstructed spawn repositioning (Property 6)
    - **Property 6: Obstructed Spawn Repositioning**
    - For any room geometry with obstructed default spawn, repositioning produces a valid in-bounds, non-intersecting point
    - **Validates: Requirements 4.7**

  - [ ] 12.5 Implement door interaction parameter validation in RuntimePlan builder
    - Validate door interaction intents: `open_angle_deg` within [-180, 180] non-zero, `speed_deg_s` within (0, 720], `initially_open` boolean
    - Reject WorldContract with structured error if door subject lacks explicit physics intent or uses trigger body mode
    - _Requirements: 5.1, 5.5_

  - [ ]* 12.6 Write property test for door interaction parameter validation (Property 7)
    - **Property 7: Door Interaction Parameter Validation**
    - For any door interaction intent, RuntimePlan accepts iff open_angle_deg in [-180,180] non-zero AND speed_deg_s in (0,720] AND physics is kinematic (not trigger/dynamic)
    - **Validates: Requirements 5.1, 5.5**

  - [ ]* 12.7 Write property test for door animation step convergence (Property 8)
    - **Property 8: Door Animation Step Convergence**
    - Per-frame step advances toward target without overshooting; step = min(|target - current|, speed_deg_s / frame_rate)
    - **Validates: Requirements 5.3**

- [ ] 13. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 14. Integration wiring and final verification
  - [ ] 14.1 Wire all components into the pipeline orchestrator
    - Connect session manager → FIFO queue → lane ladder → MVP validator → scene graph → contract → sidecar → parity → smoke → auto-launch → web SSE
    - Ensure each stage builds on the previous, no orphaned code
    - Verify `run_mvp()` calls all components in correct order with proper data flow
    - Verify `run_full()` (existing V11) remains unchanged and operational
    - _Requirements: 1.1, 10.1, 10.2_

  - [ ] 14.2 Implement session cleanup with configurable TTL
    - Background task (hourly) scans session directories
    - Remove .blend artifacts after 7 days, intermediate compiler inputs after 24 hours, temporary files immediately on session complete
    - _Requirements: 12.3_

  - [ ]* 14.3 Write integration test for full MVP pipeline with mock LLM
    - Test end-to-end flow: user text → interpret → plan (mocked) → scene graph → contract → compile (mocked) → parity → smoke (mocked) → launch (mocked) → result
    - Use deterministic plan from flywheel corpus
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ]* 14.4 Write property test for sidecar structured failure (Property 9)
    - **Property 9: Sidecar Structured Failure**
    - For any invalid sidecar state, verify `SidecarResult` with `success=False`, non-empty reason_code, and captured output for process failures
    - **Validates: Requirements 7.2, 7.4, 7.7**

- [ ] 15. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (19 properties)
- Unit tests validate specific examples and edge cases
- Phase 2 stretch goals (object grab, runtime smoke via blenderplayer frame-loop) are NOT included
- The project uses Python with FastAPI, Pydantic, and Hypothesis (property-based testing)
- Existing `.hypothesis/` directory confirms PBT infrastructure is already in place
- The 8-hour critical path prioritizes: MVP tolerance → auto-launcher → smoke validator → session manager → web SSE → lane ladder → core property tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "3.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "5.2", "6.1", "7.1"] },
    { "id": 3, "tasks": ["2.4", "5.3", "5.4", "8.1", "8.2"] },
    { "id": 4, "tasks": ["8.3", "8.4", "8.7", "10.1", "11.1"] },
    { "id": 5, "tasks": ["8.5", "8.6", "8.8", "10.2", "10.3", "10.4", "10.5", "10.6", "11.2", "11.3"] },
    { "id": 6, "tasks": ["12.1", "12.5"] },
    { "id": 7, "tasks": ["12.2", "12.3", "12.4", "12.6", "12.7"] },
    { "id": 8, "tasks": ["14.1", "14.2"] },
    { "id": 9, "tasks": ["14.3", "14.4"] }
  ]
}
```
