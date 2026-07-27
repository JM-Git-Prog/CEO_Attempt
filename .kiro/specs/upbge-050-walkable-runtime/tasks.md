# Implementation Plan: UPBGE 0.50 Walkable Runtime

## Overview

This plan migrates the walkable runtime from UPBGE's legacy logic brick system to the `KX_PythonComponent` system in UPBGE 0.50. The critical path is: API probe → component source rewrite → `_configure_runtime()` update → smoke validator update → integration test. The upstream pipeline (text → interpret → plan → scene graph → WorldContract → compile → scene.blend) already works — only the runtime logic injection is broken.

All code is Python (pytest, Hypothesis for PBT, pytest-asyncio). UPBGE 0.50 is installed at `C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blender.exe`.

## Tasks

- [ ] 1. API Probe and Discovery Infrastructure
  - [ ] 1.1 Implement the API probe script (`src/assembler/api_probe_050.py`)
    - Create the headless introspection script that runs inside UPBGE 0.50 via `--background --python`
    - Discover component attachment mechanism: check `bpy.types.Object.components`, `obj.game.components`, UPBGE RNA properties
    - Discover physics configuration API: check `obj.game.physics_type` and alternatives
    - Output structured JSON report on stdout with `PROBE_RESULT=` prefix marker
    - Must NOT import `bge` module (unavailable during headless execution)
    - Must complete within 15 seconds on target hardware
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ] 1.2 Implement the `UPBGEComponentAPI` dataclass and probe result parser
    - Create frozen dataclass in `src/assembler/api_probe_050.py` (or a shared models module)
    - Parse JSON probe output into `UPBGEComponentAPI` with fields: `has_game_attr`, `has_components_attr`, `component_api_path`, `component_add_method`, `has_logic_ops`, `physics_api_path`, `has_game_physics`, `blender_version`, `upbge_detected`, `fallback_required`
    - Implement `parse_probe_output(stdout: str) -> UPBGEComponentAPI` with `PROBE_RESULT=` marker extraction
    - Handle malformed output with `probe_parse_error` reason code
    - _Requirements: 1.2, 1.3_

  - [ ]* 1.3 Write property test for probe report parsing round-trip (Property 1)
    - **Property 1: Probe Report Parsing Round-Trip**
    - For any valid JSON probe output containing probe fields, parsing into `UPBGEComponentAPI` and serializing back to dict SHALL preserve all field values
    - Generate random valid probe JSON with Hypothesis and verify round-trip consistency
    - **Validates: Requirements 1.2**

  - [ ] 1.4 Implement probe runner with timeout and error handling
    - Create `run_api_probe(upbge_path: str, timeout_s: float = 15.0) -> UPBGEComponentAPI` in the assembler module
    - Invoke UPBGE 0.50 with `--background --python api_probe_050.py`
    - Handle timeout (>15s → `probe_timeout` reason code)
    - Handle parse failure (malformed JSON → `probe_parse_error` reason code)
    - Handle version mismatch (unexpected blender version → `version_mismatch`)
    - _Requirements: 1.3, 1.4_

- [ ] 2. Component Source Templates (KX_PythonComponent)
  - [ ] 2.1 Implement PlayerComponent source template (`src/upbge_runtime.py`)
    - Rewrite the player controller as a `KX_PythonComponent` subclass with `args`, `start()`, `update()` lifecycle
    - Implement `_update_look()`: mouse delta → yaw on player (world Z), pitch on camera (local X, clamped ±1.5 rad), re-center mouse each frame
    - Implement `_update_movement()`: WASD keyboard state → directional movement relative to player orientation, normalized for diagonals, apply gravity force
    - Implement `_update_grab()`: E-key raycast, door trigger (`kiro_interact_requested`), dynamic body grab with rule validation, hold logic
    - Implement `_check_pause()` (ESC toggle) and `_check_exit()` (F10 → `bge.logic.endGame()`)
    - Expose configurable `args`: `move_speed`, `look_speed`, `gravity`, `max_grab_distance`, `grab_hold_distance`
    - Must import only from `bge`, `mathutils`, `math`, `json` — NO `bpy` imports
    - Store as `PLAYER_COMPONENT_SOURCE` string constant in `src/upbge_runtime.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ] 2.2 Implement DoorComponent source template (`src/upbge_runtime.py`)
    - Rewrite the door interaction as a `KX_PythonComponent` subclass with `args`, `start()`, `update()` lifecycle
    - In `start()`: record initial closed rotation angle from `self.object.localOrientation`
    - In `update()`: check `kiro_interact_requested` property → toggle open/closed, animate rotation at `speed_deg_s` toward target angle
    - Expose configurable `args`: `open_angle_deg` (default 90), `speed_deg_s` (default 120), `initially_open` (default False)
    - Must import only from `bge`, `math` — NO `bpy` imports
    - Store as `DOOR_COMPONENT_SOURCE` string constant in `src/upbge_runtime.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 2.3 Write property test for movement direction relative to orientation (Property 2)
    - **Property 2: Movement Direction Relative to Orientation**
    - For any keyboard state (W/A/S/D combination) and player orientation, the computed movement vector SHALL have correct direction relative to local frame, and magnitude = `move_speed / 60.0` when keys pressed, or zero otherwise
    - Factor `compute_movement_vector(keys, orientation, speed)` as pure function for testability
    - **Validates: Requirements 2.2, 2.7**

  - [ ]* 2.4 Write property test for mouse look delta with pitch clamping (Property 3)
    - **Property 3: Mouse Look Delta with Pitch Clamping**
    - For any mouse position delta (dx, dy) and current camera pitch, resulting pitch SHALL be clamped to [-1.5, 1.5] radians, yaw change SHALL be proportional to `dx * look_speed * 100.0`
    - **Validates: Requirements 2.3**

  - [ ]* 2.5 Write property test for gravity force computation (Property 4)
    - **Property 4: Gravity Force Computation**
    - For any gravity ∈ [0.0, 50.0] and mass ≥ 1.0, the applied force vector SHALL be exactly `(0.0, 0.0, -g * max(m, 1.0))`
    - **Validates: Requirements 2.4**

  - [ ]* 2.6 Write property test for pause toggle idempotence (Property 5)
    - **Property 5: Pause Toggle Idempotence**
    - Toggling pause twice SHALL return to original state; while paused, movement/look updates produce zero state change
    - **Validates: Requirements 2.5**

  - [ ]* 2.7 Write property test for movement round-trip (Property 6)
    - **Property 6: Movement Round-Trip**
    - For any valid move_speed and unit direction, N frames forward + N frames reverse → final position within 0.01 units of start (no collision/gravity)
    - **Validates: Requirements 2.9**

  - [ ]* 2.8 Write property test for door state toggle (Property 7)
    - **Property 7: Door State Toggle**
    - Setting `kiro_interact_requested = True` and executing one update SHALL flip `is_open` and clear the flag
    - **Validates: Requirements 3.3**

  - [ ]* 2.9 Write property test for door rotation convergence (Property 8)
    - **Property 8: Door Rotation Convergence**
    - For any `open_angle_deg` ∈ [-180, 180] \ {0} and `speed_deg_s` ∈ (0, 720], iterating the animation for bounded frames SHALL converge within tolerance
    - **Validates: Requirements 3.6**

  - [ ]* 2.10 Write property test for interaction hit classification (Property 9)
    - **Property 9: Interaction Hit Classification**
    - For any raycast hit object: door trigger (has `kiro_open_angle_deg`), grab (dynamic + rule match), or no action — mutually exclusive and exhaustive
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5**

  - [ ]* 2.11 Write property test for held object velocity direction (Property 10)
    - **Property 10: Held Object Velocity Direction**
    - For any grabbed object position P and camera state (C, F, D), velocity SHALL point from P toward (C + F * D) with magnitude proportional to distance
    - **Validates: Requirements 4.6**

- [ ] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Compile-Time Component Attachment (`_configure_runtime()` Update)
  - [ ] 4.1 Implement `_embed_component_source()` function
    - Create/replace Text datablocks in `bpy.data.texts` with component source code
    - Name convention: `module_name + ".py"` (e.g., `kiro_player_first_person.py`)
    - Return the text datablock name for reference
    - _Requirements: 5.4, 10.1_

  - [ ] 4.2 Implement `_attach_component_050()` function
    - Attach a `KX_PythonComponent` to an object using the discovered API from the probe report
    - Native path: use `obj.game.components` (if available per probe)
    - Fallback path: store `kiro_component_module`, `kiro_component_class`, `kiro_component_args` as ID properties on the object
    - Return True if native attachment succeeded, False if fallback used
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

  - [ ] 4.3 Implement `_configure_physics_050()` function
    - Set physics type (CHARACTER, STATIC, DYNAMIC, KINEMATIC) via discovered RNA path
    - Set collision bounds (CAPSULE for player, BOX for doors)
    - If physics API unavailable: store intent as `kiro_physics_type`, `kiro_collision_shape` properties (graceful degradation)
    - Return True if physics configured via RNA, False if degraded
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 4.4 Implement `_configure_runtime_050()` orchestrator function
    - Accept `bpy`, `plan`, `object_by_id`, `camera_obj`, `api_report` parameters
    - Embed all component source as Text datablocks
    - Create player mesh object with CHARACTER physics + CAPSULE collision
    - Attach PlayerComponent to player with configured args
    - Parent camera to player
    - For each door binding: attach DoorComponent with configured args
    - If bootstrap fallback required: embed `kiro_component_bootstrap.py` as startup script
    - On component failure: save scene-only .blend without game logic (graceful degradation)
    - Must NOT reference `bpy.types.Object.game` sensors/controllers/physics_type from the removed API
    - Save `runtime_candidate.blend` on success
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 9.1_

  - [ ]* 4.5 Write property test for interaction binding to component attachment (Property 11)
    - **Property 11: Interaction Binding to Component Attachment**
    - For any set of interaction bindings in a RuntimePlan, the compiler SHALL produce exactly one component attachment per binding with matching `args` values
    - **Validates: Requirements 5.2, 5.3**

  - [ ]* 4.6 Write property test for text datablock embedding completeness (Property 12)
    - **Property 12: Text Datablock Embedding Completeness**
    - For any set of component templates, the compiler SHALL embed exactly one Text datablock per template with correct name and byte-for-byte content match
    - **Validates: Requirements 5.4, 10.1**

  - [ ]* 4.7 Write property test for graceful degradation save (Property 14)
    - **Property 14: Graceful Degradation Save**
    - When component attachment fails, the compiler SHALL still produce a saved .blend with scene geometry and SHALL NOT raise an unhandled exception
    - **Validates: Requirements 9.1**

- [ ] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Smoke Validator Update
  - [ ] 6.1 Implement updated smoke probe script (`src/assembler/smoke_probe_050.py`)
    - Create headless validation script for UPBGE 0.50 that checks component attachment rather than logic bricks
    - Check 1: `player_component_attached` — player object has component via native API or fallback properties
    - Check 2: `text_datablocks_present` — all required `.py` Text datablocks exist in `bpy.data.texts`
    - Check 3: `physics_configured` — player has CHARACTER physics via RNA or stored intent property
    - Check 4: `door_components_attached` — door objects have DoorComponent registered
    - Check 5: `scene_loads` — .blend opens without bpy errors
    - Output structured JSON result on stdout
    - Must NOT enter game mode, launch blenderplayer, or open visible window
    - Must complete within 30 seconds
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ] 6.2 Update `src/smoke_validator.py` to use the new probe script
    - Replace logic-brick verification logic with component-attachment verification
    - Update `run_structural_smoke()` to invoke UPBGE with `smoke_probe_050.py`
    - Parse updated JSON result format with new check names: `scene_loads`, `player_component_attached`, `text_datablocks_present`, `physics_configured`, `door_components_attached`
    - Report specific failed check with diagnostic details on failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 6.3 Write property test for validator correctness (Property 13)
    - **Property 13: Validator Correctness**
    - For any mocked .blend state (objects with/without components, text datablocks), validator reports `passed=True` only when ALL checks pass; reports specific `reason_code` for first failure; includes non-empty `detail` for every failing check
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

  - [ ]* 6.4 Write property test for degradation reason codes (Property 15)
    - **Property 15: Degradation Reason Codes**
    - For any degradation event, the system SHALL produce a reason_code from the defined set and it SHALL be a non-empty string
    - **Validates: Requirements 9.4, 9.5**

  - [ ]* 6.5 Write property test for module path ↔ text datablock consistency (Property 16)
    - **Property 16: Module Path ↔ Text Datablock Consistency**
    - For any component attachment, `module_name + ".py"` SHALL exist in `bpy.data.texts`
    - **Validates: Requirements 10.2**

  - [ ]* 6.6 Write property test for component source import restriction (Property 17)
    - **Property 17: Component Source Import Restriction**
    - Parsing any component source AST SHALL yield only imports from allowed set: `{bge, mathutils, math, json}` + stdlib. No `bpy` or third-party imports
    - **Validates: Requirements 10.4, 10.5**

- [ ] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Auto-Launch and blenderplayer Integration
  - [ ] 8.1 Update auto-launch to work with runtime_candidate from new compiler
    - Verify `auto_launch_game()` in `src/auto_launch.py` works with the component-based runtime_candidate.blend
    - Ensure blenderplayer is invoked without `--background` flag
    - Verify process remains running for minimum 3 seconds (successful scene load)
    - Report failure with exit code and stderr if blenderplayer exits within 3 seconds
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 9. Integration Wiring and Final Verification
  - [ ] 9.1 Wire probe → compile → validate → launch pipeline
    - Update `_configure_runtime()` call site in `src/assembler/upbge_compile.py` to use `_configure_runtime_050()`
    - Integrate API probe into compilation flow: run probe first, pass report to configure function
    - Wire updated smoke validator into the existing parity → smoke → launch chain
    - Ensure graceful degradation chain: probe fails → attempt without probe; compile fails → scene-only .blend; smoke fails → proceed with `smoke_skipped`; launch fails → download fallback
    - _Requirements: 5.1, 5.6, 5.7, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 9.2 Write integration test for full probe → compile → validate → launch flow
    - Test end-to-end with mocked UPBGE subprocess (probe output fixture, compile success, smoke pass)
    - Verify correct data flow between stages
    - Test degradation paths: probe timeout → fallback compile, component failure → scene-only save
    - _Requirements: 1.1, 5.7, 9.1_

  - [ ]* 9.3 Write integration test against live UPBGE 0.50 binary
    - Run actual API probe against installed UPBGE 0.50
    - Verify probe completes within 15 seconds and produces parseable output
    - Verify discovered API surface matches what the compiler expects
    - _(Optional: requires UPBGE 0.50 to be available on test machine)_
    - _Requirements: 1.1, 1.4_

- [ ] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (17 properties)
- The project uses Python with pytest, Hypothesis (PBT), and pytest-asyncio
- Existing `.hypothesis/` directory confirms PBT infrastructure is in place
- The critical path is: API probe (1.1–1.4) → component source (2.1–2.2) → compile attachment (4.1–4.4) → smoke update (6.1–6.2) → integration wiring (9.1)
- The upstream pipeline (text → interpret → plan → scene graph → WorldContract → compile → scene.blend) is unchanged — only runtime logic injection is fixed
- Integration tests against the live UPBGE binary (9.3) require the installed UPBGE 0.50 and are not suitable for CI
- Grab logic is merged into PlayerComponent (not a separate GrabComponent) per design decision 3

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "2.9", "2.10", "2.11"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["4.4"] },
    { "id": 5, "tasks": ["4.5", "4.6", "4.7", "6.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3"] }
  ]
}
```
