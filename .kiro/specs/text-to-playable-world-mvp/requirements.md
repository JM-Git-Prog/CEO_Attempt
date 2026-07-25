# Requirements Document

## Introduction

This specification defines the minimum viable path to a working "type a sentence → get a playable 3D game" experience. The user types a natural-language room description, and the system **launches a playable 3D game** — not a file to download, not a project to open in an editor, not a rendered image. The game starts. The user is inside the room they described. They walk around with WASD, look with the mouse, open doors. That is the deliverable.

The MVP leverages existing pipeline stages (LLM interpretation, floor plan generation, scene graph construction, world contract, UPBGE compiler) and focuses on: (1) making the UPBGE compilation script produce a real playable runtime, (2) relaxing overly-strict validation gates so LLM plans actually pass, (3) auto-launching the compiled game so the user never touches a file manually.

### Environment Assumptions

- **Local desktop with GPU and display.** The MVP assumes a Windows workstation with an RTX 4090, a connected display, and UPBGE installed locally. It will NOT work on headless servers, cloud GPU instances without virtual framebuffers, or machines without a window manager.
- **Single-user, single-session-at-a-time.** Only one UPBGE compilation may run at any given time. Concurrent requests queue behind the active compilation.
- **Audio is out of scope.** No sound effects, ambient audio, or spatial audio in MVP.
- **Textures are out of scope.** Materials use flat Principled BSDF parameters (base_color, metallic, roughness, emission) only. No procedural textures, no image textures.
- **Object grab interaction is a stretch goal.** The core MVP delivers walking + collision + doors. Grab is included as a Phase 2 requirement that ships only if time permits after the core path is stable.

## Glossary

- **Pipeline**: The end-to-end sequence of stages that transforms a user's text description into a playable game world
- **WorldContract**: The engine-neutral, immutable Pydantic model representing a complete spatial world (room shell, instances, materials, lights, physics, interactions, camera)
- **CompilerPlan**: The deterministic, UPBGE-specific compilation plan derived from a WorldContract — consumed by the first-party compiler script
- **First_Party_Script**: The reviewed Python script (`src/assembler/upbge_compile.py`) that runs inside UPBGE's embedded Python to build the .blend scene from a CompilerPlan
- **UPBGE_Editor**: The UPBGE editor executable (a Blender fork) — used for compilation. Runs the First_Party_Script in headless/background mode using the Blender Python API (`bpy`). Produces `.blend` files. NOT used for launching games.
- **blenderplayer**: The standalone game player executable shipped alongside UPBGE — takes a `.blend` file and launches it directly in fullscreen game mode without the editor UI. Uses the BGE runtime (`bge` module). This is the Auto_Launch mechanism.
- **UPBGE**: The combined installation containing both the UPBGE_Editor and blenderplayer executables. The MVP requires BOTH to be present and compatible.
- **RuntimePlan**: The immutable plan specifying player controller, interaction templates, and physics for in-game behavior
- **Runtime_Candidate**: A `.blend` file produced by the compiler that contains both the 3D scene and embedded game logic scripts, ready to launch in game mode
- **Sidecar**: The bounded subprocess orchestrator that invokes UPBGE in background mode to execute the First_Party_Script
- **Capability_Report**: The verified evidence from probing BOTH the UPBGE_Editor executable (for compilation) AND the blenderplayer executable (for game launch). Each is discovered and probed independently. Reports product identity, version, Blender API version for the editor, and game-mode launch success for blenderplayer. A system may have the editor without blenderplayer (compilation works, launch unavailable) or vice versa.
- **Parity_Gate**: A validation step that checks the compiled output matches the WorldContract's structural expectations (object inventory, object count, physics bindings)
- **Smoke_Runner**: The bounded process that launches a Runtime_Candidate and verifies basic gameplay behaviors (load, spawn, movement, collision). Runs ASYNCHRONOUSLY — does not block Auto_Launch.
- **Workflow_Profile**: An immutable version-specific generation and compilation contract persisted with a session (pre-existing concept from V9+ pipeline versions)
- **Compiler_Manifest**: Immutable record binding inputs, versions, hashes, timings, and diagnostics to a compilation run (pre-existing provenance concept)
- **Interface_Version**: A query-versioned identifier (V3 through V11) controlling which pipeline behavior and UI a session uses. V3-V10 are retained historical versions; V11 is the current full-quality version; MVP mode is a new execution path within V11.
- **Parity_Gate**: A validation step that checks the compiled output matches the WorldContract's structural expectations (object inventory, positions, physics bindings)
- **Smoke_Runner**: The bounded process that launches a Runtime_Candidate and verifies basic gameplay behaviors (load, spawn, movement, collision)
- **Plan_Validation**: The deterministic quality checks on LLM-generated floor plans (geometry bounds, overlap detection, opening placement)
- **MVP_Tolerance**: A relaxed validation mode that accepts plans with non-critical warnings rather than rejecting them outright
- **Playable_Artifact**: The compiled `.blend` file containing the 3D world plus embedded game logic. The compiler wires an "Always" sensor → Python controller that calls `bge.logic.startGame()`, which means the same .blend works in BOTH contexts: blenderplayer direct launch AND editor P-key launch. This is a deliberate design property — blenderplayer is the user-facing launch path, editor P-key is the development/debugging path.
- **Auto_Launch**: The system's ability to invoke **blenderplayer** (not the UPBGE editor) on the compiled artifact without user intervention — the user types a sentence and the game window opens in fullscreen. The command is simply `blenderplayer path/to/file.blend`.
- **Web_Interface**: The FastAPI-served browser application where users type descriptions, see progress, and trigger game launch
- **Session**: A stateful pipeline execution identified by a unique ID, tracking all stages from description input to playable output

## Requirements

### Requirement 1: End-to-End Pipeline — Sentence In, Game Running

**User Story:** As a user, I want to type a single sentence describing a room and have a playable 3D game launch automatically, so that I immediately walk around inside the world I described without downloading files, opening editors, or running commands.

#### Acceptance Criteria

1. WHEN a user submits a text description (between 3 and 500 characters) via the Web_Interface, THE Pipeline SHALL produce a Playable_Artifact and Auto_Launch it via blenderplayer in fullscreen game mode within 180 seconds on the target hardware (RTX 4090, local Ollama, local UPBGE). The budget breakdown is: LLM stages ≤60s, compilation ≤60s, parity ≤5s, launch ≤10s, with 45s margin for overhead and retries.
2. WHEN Auto_Launch succeeds, THE user SHALL see a full-screen game window with first-person controls active — no file dialogs, no editor UI, no manual steps between typing a sentence and being inside the game
3. THE Pipeline SHALL Auto_Launch the game IMMEDIATELY after the Parity_Gate passes, WITHOUT waiting for the Smoke_Runner to complete. The Smoke_Runner runs asynchronously in the background and reports its result to the session record without blocking the user's play experience.
4. WHEN the Pipeline completes successfully, THE Web_Interface SHALL additionally present a download link for the Playable_Artifact for users who want to replay or share the game later
5. IF any pipeline stage fails, THEN THE Pipeline SHALL report the failure stage name, a machine-readable reason code, and a human-readable diagnostic message to the Web_Interface without terminating the server process or corrupting the session state
6. IF the user submits an empty string, a string shorter than 3 characters, or a string longer than 500 characters, THEN THE Pipeline SHALL reject the input with a descriptive validation error before invoking any LLM stage
7. THE Pipeline SHALL execute all stages locally without requiring cloud API calls for the core path (LLM via local Ollama, UPBGE via local executable, no external image generation required for MVP)
8. IF Auto_Launch fails (blenderplayer process cannot start, exits immediately, or is not discovered by the Capability_Report), THEN THE Pipeline SHALL fall back to presenting the download link with launch instructions rather than reporting the entire pipeline as failed

### Requirement 2: LLM Plan Generation with MVP Tolerance

**User Story:** As a user, I want the system to accept my room description even when the LLM plan isn't geometrically perfect, so that I get a playable result rather than a rejection.

#### Acceptance Criteria

1. WHEN the LLM generates a floor plan from the user description, THE Plan_Validation SHALL operate in MVP_Tolerance mode by default unless the session Workflow_Profile explicitly specifies strict validation
2. WHILE in MVP_Tolerance mode, THE Plan_Validation SHALL accept plans where non-critical warnings exist (overlapping furniture within 0.1m tolerance, furniture placed more than 0.2m from its declared relationship target, clearance violations up to 0.15m) and SHALL reject plans only when a structural impossibility is present: objects with any vertex outside room bounds, missing room width or depth or height, rooms with any dimension equal to zero, or duplicate stable identifiers
3. WHEN a plan is rejected under MVP_Tolerance mode, THE Pipeline SHALL retry LLM generation up to 2 additional times, each retry removing one optional constraint from the original prompt, and SHALL report failure to the user with the list of structural impossibilities that caused rejection if all retries are exhausted
4. WHILE in MVP_Tolerance mode, THE Pipeline SHALL skip canon image generation and composition validation stages, proceeding directly from scene graph to World_Contract generation
5. IF MVP_Tolerance mode accepts a plan containing non-critical warnings, THEN THE Pipeline SHALL record each warning type, affected instance identifier, and measured deviation in the Compiler_Manifest

### Requirement 3: UPBGE Compilation to Playable Blend

**User Story:** As a developer, I want the First_Party_Script to actually construct a valid UPBGE scene from the CompilerPlan, so that the output is a real playable .blend file rather than a stub.

#### Acceptance Criteria

1. WHEN the Sidecar invokes the First_Party_Script with a valid CompilerPlan, THE First_Party_Script SHALL create Blender mesh objects for every geometry entry (room shell segments, floor, ceiling, object instances), preserving each entry's stable ID as the Blender object name and applying the entry's position, rotation, and scale transform
2. WHEN the First_Party_Script processes material entries, THE First_Party_Script SHALL apply Principled BSDF materials with the CompilerPlan-specified base_color, metallic, roughness, and emission values and assign each material to its referenced mesh object
3. WHEN the First_Party_Script processes light entries, THE First_Party_Script SHALL create Blender light objects matching the specified type, position, color, and intensity
4. WHEN the CompilerPlan includes a RuntimePlan, THE First_Party_Script SHALL embed the player controller script and interaction component scripts as text datablocks and wire them via logic bricks to the game objects identified by stable ID in the RuntimePlan bindings
5. WHEN the First_Party_Script processes physics entries, THE First_Party_Script SHALL configure Blender game physics properties (body type, collision shape, mass, friction) on each referenced object
6. THE First_Party_Script SHALL save the resulting scene as a `.blend` file to the output directory specified by the Sidecar, and the saved file SHALL be non-zero bytes and loadable by the UPBGE Blender API without errors
7. IF the First_Party_Script encounters an unprocessable geometry, material, light, physics, or runtime entry, THEN THE First_Party_Script SHALL skip the failing entry, continue processing remaining entries, and include the skipped entry ID and failure reason in a structured diagnostics list written alongside the output

### Requirement 4: Player Controller Runtime Behavior

**User Story:** As a player, I want to walk around the generated room using standard FPS controls, so that I can explore the space I described.

#### Acceptance Criteria

1. WHEN the Playable_Artifact is launched in UPBGE game mode, THE player controller SHALL spawn the player at the geometric center of the floor bounds at 1.7m elevation (eye height) with gravity of 9.81 m/s² enabled, using a capsule collider of 1.8m height and 0.3m radius
2. WHILE the game is running, THE player controller SHALL move the player in response to WASD keys at a configurable speed (default 4.0 m/s, range 1.0–10.0 m/s) with diagonal input normalized so combined speed does not exceed the configured maximum
3. WHILE the game is running, THE player controller SHALL rotate the camera view in response to mouse movement with configurable sensitivity, bounded vertical look angle of ±85°, and unlimited horizontal rotation
4. THE player controller SHALL enforce collision detection between the player capsule and all static and kinematic physics bodies including walls, floor, ceiling, and furniture such that the capsule cannot pass through or overlap any collision surface
5. WHEN the player presses Escape, THE player controller SHALL toggle a pause state that freezes movement and look input and releases the mouse cursor, and WHEN the player presses Escape again, THE player controller SHALL resume input processing and recapture the cursor
6. WHEN the player presses F10, THE player controller SHALL exit the game and return control to the operating system
7. IF the spawn location (floor center at 1.7m) is obstructed by geometry or falls outside the room bounds, THEN THE player controller SHALL attempt a spiral search outward from center in 0.5m increments (up to 8 attempts), and IF all spiral points are obstructed, SHALL fall back to spawning at room center at ceiling_height minus 0.5m (drop from above) and let gravity resolve the position

### Requirement 5: Door Interaction

**User Story:** As a player, I want to open and close doors in the game world, so that the room feels interactive and alive.

#### Acceptance Criteria

1. WHEN the WorldContract contains door-kind interaction intents referencing a door opening subject with explicit physics intent, THE RuntimePlan SHALL include a door interaction binding using the door template with validated parameters (open_angle_deg within [-180, 180] non-zero, speed_deg_s within (0, 720], initially_open boolean)
2. WHEN the player aims at a door object within the configured interaction distance (default 3.0m raycast) and presses E, THE door component SHALL toggle the door between open and closed states by setting the interact-requested flag on the target object
3. WHILE a door is animating between open and closed positions, THE door component SHALL rotate the door object around its hinge edge (not its geometric center) at the configured speed (default 120°/s, maximum step per frame) toward the target angle (default 90° open from the closed angle) and SHALL stop advancing once the rotation reaches the target. The hinge edge SHALL be at the door's left or right bound such that a 90° open door swings clear of the doorway.
4. THE door object SHALL have kinematic physics (not trigger, not dynamic) so that the player collides with the door regardless of its current angle, and a fully-open door SHALL NOT obstruct the doorway aperture
5. IF a door interaction intent references a subject without explicit physics intent or uses a trigger body mode, THEN THE RuntimePlan builder SHALL reject the WorldContract with a structured error identifying the invalid interaction

### Requirement 6: Object Grab Interaction (STRETCH GOAL — Phase 2)

**User Story:** As a player, I want to pick up and move small objects, so that the world feels physically responsive.

**Scope note:** This requirement is a stretch goal. The core MVP ships with walking + collision + doors. Grab ships only if the core path is stable and time permits. The implementation MAY use the existing `GRAB_COMPONENT_SOURCE` template which already handles raycast, mass check, hold positioning, and release. However, the physics API manipulation (detaching from simulation, reattaching dynamic bodies, applying velocity) is UPBGE-version-sensitive and should be tested against the pinned build before shipping.

#### Acceptance Criteria

1. WHEN the WorldContract contains instances with dynamic physics bodies and grab interaction intents, THE RuntimePlan SHALL include grab interaction bindings
2. WHEN the player's camera-center raycast hits a grabbable object within range (default 3.0m) and the player presses E, THE grab component SHALL attach the object to the player's view
3. WHILE holding an object, THE grab component SHALL position the held object at the configured hold distance (default 1.5m) in front of the camera
4. WHEN the player presses E while holding an object, THE grab component SHALL release the object and restore its dynamic physics body
5. IF the player targets an object whose mass exceeds the maximum mass limit (default 25 kg), THEN THE grab component SHALL refuse the grab

### Requirement 7: UPBGE Sidecar Compilation Orchestration

**User Story:** As a developer, I want the sidecar to reliably invoke UPBGE and produce the playable output with proper error handling, so that compilation failures are diagnosable.

#### Acceptance Criteria

1. WHEN the Pipeline reaches the compilation stage, THE Sidecar SHALL verify UPBGE capability via the Capability_Report which SHALL independently probe: (a) the UPBGE_Editor executable — confirming product identity "UPBGE", version at or above the pinned minimum, logic bricks API accessible, game physics body modes available, and Character physics type present; AND (b) the blenderplayer executable — confirming it exists alongside the editor, runs a .blend test file in game mode without crash, and exits cleanly. IF the UPBGE_Editor is present but blenderplayer is absent, THE Pipeline SHALL proceed with compilation but SHALL report Auto_Launch as unavailable and pre-emptively prepare the download-link fallback path.
2. IF the Capability_Report indicates the UPBGE_Editor is absent, incompatible, missing required API surfaces, or unreachable, THEN THE Sidecar SHALL return a structured failure result identifying WHICH capability is missing without attempting compilation
3. WHEN the Sidecar invokes the UPBGE_Editor for compilation, THE Sidecar SHALL enforce wall-time limits (default 60s for MVP scenes ≤20 objects), output size limits (512MB), and combined stdout/stderr capture limits (2MB)
4. WHEN the UPBGE_Editor process exits with code 0, THE Sidecar SHALL validate that all expected output files (the `.blend` file and the scene inventory JSON) are present and that no files outside the declared output set exist in the output directory
5. IF the UPBGE_Editor process times out or exceeds resource limits, THEN THE Sidecar SHALL terminate the process, clean up the output directory, and return a structured failure result with the violated limit identified
6. THE Sidecar SHALL pass the CompilerPlan with `runtime=True` flag to produce a Runtime_Candidate rather than a static .blend. The Runtime_Candidate SHALL be a valid input to both blenderplayer (for user launch) and the UPBGE_Editor P-key (for developer debugging).
7. IF the UPBGE_Editor process exits with a non-zero code, THEN THE Sidecar SHALL capture up to 2MB of process output and return a structured failure result containing the exit code and captured output

### Requirement 8: Parity Gate and Async Smoke Validation

**User Story:** As a developer, I want lightweight validation that confirms the compiled game is structurally correct, without blocking the user from playing.

#### Acceptance Criteria

1. WHEN the Sidecar produces a Runtime_Candidate, THE Parity_Gate SHALL verify that: (a) the scene inventory JSON contains all expected object IDs from the CompilerPlan with no missing IDs, AND (b) the total object count in the inventory matches the expected count from the CompilerPlan (catches spurious extra objects)
2. IF the Parity_Gate detects missing object IDs or a count mismatch, THEN THE Pipeline SHALL reject the Runtime_Candidate and return a structured failure listing each discrepancy
3. WHEN the Parity_Gate passes, THE Pipeline SHALL IMMEDIATELY proceed to Auto_Launch without waiting for the Smoke_Runner
4. THE Smoke_Runner SHALL run ASYNCHRONOUSLY after Auto_Launch is triggered — it launches a SEPARATE blenderplayer process (the same executable used for Auto_Launch) to verify load success (process starts, loads .blend without crash, reaches game-mode frame loop within 30 seconds) and records its result to the session without blocking the user
5. IF the async Smoke_Runner reports a load failure, THE Web_Interface SHALL display a warning ("smoke test failed — game may have issues") but SHALL NOT terminate the already-running game
6. THE session record SHALL include the smoke result with quality label: "smoke_full" (load + frame loop confirmed), "smoke_partial" (load confirmed, frame loop unverified), or "smoke_skipped" (async runner not yet complete)

### Requirement 9: Web Interface — Progress and Auto-Launch

**User Story:** As a user, I want to see my game being built in real-time and have it launch automatically when ready, so the experience feels like magic — I type, I wait briefly, I'm playing.

#### Acceptance Criteria

1. WHILE the Pipeline is executing, THE Web_Interface SHALL push stage progress updates via Server-Sent Events (SSE) to the browser client, delivering each stage transition (interpreting, planning, building_scene, compiling, validating, launching, game_running) within 2 seconds of occurrence
2. WHEN the Pipeline produces a Playable_Artifact, THE Web_Interface SHALL automatically trigger Auto_Launch (invoke blenderplayer on the compiled .blend) without requiring user interaction beyond the initial "Generate" action
3. WHEN the game is running, THE Web_Interface SHALL display a "Game Running" status with a "Download .blend" secondary action for later replay
4. IF Auto_Launch fails, THEN THE Web_Interface SHALL present the download link with platform-specific instructions for manual launch
5. IF the Pipeline fails at any stage, THEN THE Web_Interface SHALL display the failed stage name and a human-readable reason rather than a generic error
6. THE Web_Interface SHALL preserve existing V3-V10 interface behavior and routing for non-MVP sessions

### Requirement 10: Existing Pipeline Preservation

**User Story:** As a developer, I want the MVP changes to not break existing pipeline functionality, so that the full-quality path remains available for non-MVP usage.

#### Acceptance Criteria

1. THE Pipeline SHALL support both MVP mode (relaxed validation, skip canon image) and full mode (existing V11 behavior) selectable per session via a mode parameter at session creation time
2. WHEN operating in full mode, THE Pipeline SHALL maintain existing Plan_Validation strictness, canon image generation, composition sidecar, and all parity gates unchanged
3. THE WorldContract schema SHALL remain unchanged — MVP mode affects only pipeline orchestration and validation thresholds, not the data model
4. IF no mode is specified at session creation, THEN THE Pipeline SHALL default to MVP mode
5. THE self-learning flywheel corpus capture SHALL continue recording all pipeline attempts (including MVP-mode runs) as training data without blocking pipeline stage progression

### Requirement 11: Serialization Round-Trip Integrity

**User Story:** As a developer, I want the WorldContract and CompilerPlan serialization to be lossless, so that the compiler receives exactly what the pipeline constructed.

#### Acceptance Criteria

1. FOR ALL valid WorldContract instances, serializing to canonical JSON bytes then deserializing SHALL produce a structurally equal WorldContract where every field value compares equal by Pydantic model equality
2. FOR ALL valid CompilerPlan instances, serializing to canonical bytes then reconstructing from a WorldContract with identical field values and compiler configuration SHALL produce an identical SHA-256 content hash
3. FOR ALL valid RuntimePlan instances, the template sources embedded in the plan SHALL match the SHA-256 hashes declared in template_hashes
4. THE canonical JSON serialization SHALL reject non-finite numbers (NaN, Infinity, -Infinity), sort keys lexicographically, use no-whitespace separators (`,` and `:`), and encode to UTF-8
5. IF deserialization receives bytes that do not conform to the canonical schema (missing required fields, unknown fields, type mismatches), THEN THE deserializer SHALL raise a validation error identifying the first non-conforming element rather than silently coercing values

### Requirement 12: Session Lifecycle, Concurrency, and Cleanup

**User Story:** As a developer, I want predictable session isolation and resource cleanup, so that concurrent users and repeated generations don't corrupt each other or leak disk space.

#### Acceptance Criteria

1. THE Pipeline SHALL enforce a maximum of ONE active UPBGE compilation at any time. IF a new session requests compilation while another is in progress, THEN the new request SHALL queue behind the active compilation (FIFO) rather than failing immediately or running concurrently.
2. EACH session SHALL have an isolated output directory. Intermediate files (compiler plan JSON, scene inventory, temporary .blend artifacts) SHALL be written exclusively within the session's output directory and SHALL NOT reference or modify files in other sessions' directories.
3. WHEN a session completes (success or failure), THE Pipeline SHALL retain the final Playable_Artifact and session metadata (session.json) but MAY clean up intermediate compiler inputs (canonical contract bytes, compiler plan JSON) after a configurable retention period (default: 24 hours).
4. IF a user submits a new description while their previous session's game is still running, THE Pipeline SHALL start a new session independently — the previous game process is NOT terminated (the user can close it manually).
5. THE Pipeline SHALL assign unique session IDs using random UUIDs and SHALL NOT reuse session output directories even if a previous session with the same description exists.
6. IF the server process restarts, THE Pipeline SHALL NOT resume in-progress compilations. Sessions that were mid-compilation at shutdown SHALL be marked as failed with reason_code "server_restart" and the user may retry.
