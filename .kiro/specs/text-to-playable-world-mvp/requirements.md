# Requirements Document

## Introduction

This specification defines the minimum viable path from the existing "Living Room" pipeline to a working "type a sentence → play a 3D game" experience. The user types a natural-language room description into the browser, and the system returns a launchable UPBGE game with first-person controls, collision, gravity, interactive doors, and object grabbing — all running locally on the user's machine without cloud dependencies.

The MVP leverages existing pipeline stages (LLM interpretation, floor plan generation, scene graph construction, world contract, UPBGE compiler planning) and focuses on making the UPBGE compilation script produce a real playable `.blend` file, relaxing overly-strict validation gates for "good enough" plans, and delivering the playable artifact back to the user through the web interface.

## Glossary

- **Pipeline**: The end-to-end sequence of stages that transforms a user's text description into a playable game world
- **WorldContract**: The engine-neutral, immutable Pydantic model representing a complete spatial world (room shell, instances, materials, lights, physics, interactions, camera)
- **CompilerPlan**: The deterministic, UPBGE-specific compilation plan derived from a WorldContract — consumed by the first-party compiler script
- **First_Party_Script**: The reviewed Python script (`src/assembler/upbge_compile.py`) that runs inside UPBGE's embedded Python to build the .blend scene from a CompilerPlan
- **UPBGE**: UpBGE (Uchronia Project Blender Game Engine) — a Blender fork with an integrated game runtime engine, installed locally
- **RuntimePlan**: The immutable plan specifying player controller, interaction templates, and physics for in-game behavior
- **Runtime_Candidate**: A `.blend` file produced by the compiler that contains both the 3D scene and embedded game logic scripts, ready to launch in game mode
- **Sidecar**: The bounded subprocess orchestrator that invokes UPBGE in background mode to execute the First_Party_Script
- **Capability_Report**: The verified evidence from probing a UPBGE executable — confirms product identity, version, and feature support
- **Parity_Gate**: A validation step that checks the compiled output matches the WorldContract's structural expectations (object inventory, positions, physics bindings)
- **Smoke_Runner**: The bounded process that launches a Runtime_Candidate and verifies basic gameplay behaviors (load, spawn, movement, collision)
- **Plan_Validation**: The deterministic quality checks on LLM-generated floor plans (geometry bounds, overlap detection, opening placement)
- **MVP_Tolerance**: A relaxed validation mode that accepts plans with non-critical warnings rather than rejecting them outright
- **Playable_Artifact**: The final published `.blend` file that a user can double-click to launch UPBGE in game mode, or download from the web interface
- **Web_Interface**: The FastAPI-served browser application where users type descriptions and receive results
- **Session**: A stateful pipeline execution identified by a unique ID, tracking all stages from description input to playable output

## Requirements

### Requirement 1: End-to-End Pipeline Execution

**User Story:** As a user, I want to type a single sentence describing a room and receive a playable 3D game world, so that I can immediately walk around and interact with the environment I described.

#### Acceptance Criteria

1. WHEN a user submits a text description (between 3 and 500 characters) via the Web_Interface, THE Pipeline SHALL produce a Playable_Artifact within 120 seconds on the target hardware (RTX 4090, local Ollama, local UPBGE)
2. WHEN the Pipeline completes successfully, THE Playable_Artifact SHALL be a non-zero-byte `.blend` file that loads without error in the discovered UPBGE executable and contains at minimum: a room shell with floor, walls, and ceiling geometry; a player spawn object; an embedded player controller script; and game physics configured on all collision-bearing objects
3. WHEN the Pipeline completes successfully, THE Web_Interface SHALL present a download link for the Playable_Artifact and display a "Launch Game" action that invokes the local UPBGE executable in game mode
4. IF any pipeline stage fails, THEN THE Pipeline SHALL report the failure stage name, a machine-readable reason code, and a human-readable diagnostic message to the Web_Interface without terminating the server process or corrupting the session state
5. IF the user submits an empty string, a string shorter than 3 characters, or a string longer than 500 characters, THEN THE Pipeline SHALL reject the input with a descriptive validation error before invoking any LLM stage
6. THE Pipeline SHALL execute all stages locally without requiring cloud API calls for the core path (LLM via local Ollama, UPBGE via local executable, no external image generation required for MVP)

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
7. IF the spawn location is obstructed by geometry or falls outside the room bounds, THEN THE player controller SHALL reposition the player to the nearest unobstructed point within room bounds at the configured eye height before enabling input

### Requirement 5: Door Interaction

**User Story:** As a player, I want to open and close doors in the game world, so that the room feels interactive and alive.

#### Acceptance Criteria

1. WHEN the WorldContract contains door-kind interaction intents referencing a door opening subject with explicit physics intent, THE RuntimePlan SHALL include a door interaction binding using the door template with validated parameters (open_angle_deg within [-180, 180] non-zero, speed_deg_s within (0, 720], initially_open boolean)
2. WHEN the player aims at a door object within the configured interaction distance (default 3.0m raycast) and presses E, THE door component SHALL toggle the door between open and closed states by setting the interact-requested flag on the target object
3. WHILE a door is animating between open and closed positions, THE door component SHALL rotate the door object at the configured speed (default 120°/s, maximum step per frame) toward the target angle (default 90° open from the closed angle) and SHALL stop advancing once the rotation reaches the target
4. THE door object SHALL have kinematic or dynamic physics (not trigger) so that the player collides with the door regardless of its current angle
5. IF a door interaction intent references a subject without explicit physics intent or uses a trigger body mode, THEN THE RuntimePlan builder SHALL reject the WorldContract with a structured error identifying the invalid interaction

### Requirement 6: Object Grab Interaction

**User Story:** As a player, I want to pick up and move small objects, so that the world feels physically responsive.

#### Acceptance Criteria

1. WHEN the WorldContract contains instances with dynamic physics bodies and grab interaction intents, THE RuntimePlan SHALL include grab interaction bindings
2. WHEN the player's camera-center raycast hits a grabbable object within range (default 3.0m) and the player presses E, THE grab component SHALL attach the object to the player's view using a positional constraint that removes the object from world physics simulation while held
3. WHILE holding an object, THE grab component SHALL position the held object at the configured hold distance (default 1.5m, minimum 0.5m, maximum 3.0m) in front of the camera, oriented to face the camera's forward direction
4. WHEN the player presses E while holding an object, THE grab component SHALL release the object, restore its dynamic physics body, and apply the player's current movement velocity to the released object
5. IF the player targets an object whose mass exceeds the maximum mass limit specified in the interaction parameters (default 25 kg), THEN THE grab component SHALL refuse the grab and provide a visual or auditory indication that the object is too heavy
6. IF the held object is destroyed or its physics body becomes invalid while held, THEN THE grab component SHALL release the grab state without applying velocity and return to the idle interaction state

### Requirement 7: UPBGE Sidecar Compilation Orchestration

**User Story:** As a developer, I want the sidecar to reliably invoke UPBGE and produce the playable output with proper error handling, so that compilation failures are diagnosable.

#### Acceptance Criteria

1. WHEN the Pipeline reaches the compilation stage, THE Sidecar SHALL verify UPBGE capability via the Capability_Report (product identity, version, and runtime support) before attempting compilation
2. IF the Capability_Report indicates UPBGE is absent, incompatible, or unreachable, THEN THE Sidecar SHALL return a structured failure result identifying the missing capability without attempting compilation
3. WHEN the Sidecar invokes UPBGE, THE Sidecar SHALL enforce wall-time limits (default 180s), output size limits (512MB), and combined stdout/stderr capture limits (2MB)
4. WHEN the UPBGE process exits with code 0, THE Sidecar SHALL validate that all expected output files (the `.blend` file and the scene inventory JSON) are present and that no files outside the declared output set exist in the output directory
5. IF the UPBGE process times out or exceeds resource limits, THEN THE Sidecar SHALL terminate the process, clean up the output directory, and return a structured failure result with the violated limit identified
6. THE Sidecar SHALL pass the CompilerPlan with `runtime=True` flag to produce a Runtime_Candidate rather than a static .blend
7. IF the UPBGE process exits with a non-zero code, THEN THE Sidecar SHALL capture up to 2MB of process output and return a structured failure result containing the exit code and captured output

### Requirement 8: Parity and Smoke Validation for MVP

**User Story:** As a developer, I want lightweight validation that confirms the compiled game actually works, so that users don't receive broken artifacts.

#### Acceptance Criteria

1. WHEN the Sidecar produces a Runtime_Candidate, THE Parity_Gate SHALL verify that the scene inventory JSON contains all expected object IDs from the CompilerPlan and that no expected ID is missing
2. IF the Parity_Gate detects missing object IDs, THEN THE Pipeline SHALL reject the Runtime_Candidate and return a structured failure listing each missing ID
3. WHEN the Parity_Gate passes, THE Smoke_Runner SHALL launch the Runtime_Candidate in UPBGE and verify basic load success (UPBGE process starts, loads the .blend without crash, and reaches game-mode frame loop within 30 seconds)
4. IF the Smoke_Runner cannot verify interactive behaviors (movement, collision) within 30 seconds of successful load, THEN THE Pipeline SHALL still publish the artifact with a "smoke_partial" quality label rather than blocking delivery
5. WHILE in MVP mode, THE Pipeline SHALL treat parity pass + successful load as sufficient for publishing the Playable_Artifact (full interactive smoke is desirable but not blocking)

### Requirement 9: Web Interface Delivery

**User Story:** As a user, I want to see my game's progress and download the result from the same browser page where I typed my description, so that the experience is seamless.

#### Acceptance Criteria

1. WHILE the Pipeline is executing, THE Web_Interface SHALL display stage progress updates (interpreting, planning, building scene, compiling, validating, ready) within 2 seconds of each stage transition
2. WHEN the Pipeline produces a Playable_Artifact, THE Web_Interface SHALL present a download button that serves the `.blend` file
3. WHEN the Pipeline produces a Playable_Artifact, THE Web_Interface SHALL display launch instructions explaining how to open the file in UPBGE game mode (double-click or `upbge --game <file>`)
4. IF the Pipeline fails at any stage, THEN THE Web_Interface SHALL display the failed stage name and a human-readable reason rather than a generic error
5. THE Web_Interface SHALL preserve existing V3-V10 interface behavior and routing for non-MVP sessions

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
