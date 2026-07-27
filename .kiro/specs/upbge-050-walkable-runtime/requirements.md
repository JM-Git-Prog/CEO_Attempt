# Requirements Document

## Introduction

This specification addresses the broken UPBGE 0.50 runtime integration in the text-to-playable-world pipeline. UPBGE 0.50 (based on Blender 5.0.1) removed the `bpy.types.Object.game` API that the existing `_configure_runtime()` function relies on for physics configuration, logic brick wiring, and player controller activation. The consequence is that `runtime_candidate.blend` either fails to save or lacks game logic, blenderplayer exits immediately, and auto-launch fails.

The fix migrates from the legacy logic brick system to UPBGE 0.50's Python Component system (`KX_PythonComponent`), which provides an object-scoped `start()`/`update()` lifecycle that replaces the Always sensor → Python controller pattern. The `bge` module remains fully functional at game runtime; only the compile-time wiring mechanism has changed.

### Scope

- Migrate player controller, door interaction, and grab interaction from free-function logic-brick scripts to `KX_PythonComponent` subclasses
- Update `_configure_runtime()` to attach components via `bpy.types.Object.components` (or the UPBGE 0.50 equivalent API surface)
- Update the smoke validator to verify component attachment rather than logic brick wiring
- Ensure blenderplayer stays running with WASD+mouse walkable gameplay
- Preserve the existing pipeline's graceful degradation and immutability guarantees

### Environment Assumptions

- UPBGE 0.50 installed at `C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blender.exe`
- blenderplayer.exe in the same directory
- Windows workstation with RTX 4090 and connected display
- Single-user, single-session pipeline execution

## Glossary

- **UPBGE_050**: The UPBGE 0.50 release (based on Blender 5.0.1) which removed the `bpy.types.Object.game` API and introduced Python Components and Logic Nodes as replacement systems
- **Python_Component**: A Python class subclassing `bge.types.KX_PythonComponent` with `args`, `start()`, and `update()` methods, attached to an object and automatically invoked by the UPBGE runtime each frame
- **Logic_Brick**: The legacy sensor → controller → actuator system from UPBGE 0.2x, configured at compile time via `bpy.types.Object.game`. Unavailable in UPBGE 0.50 via `bpy`
- **Logic_Node**: A visual scripting node-based system registered at UPBGE 0.50 startup. Not used by this spec due to the difficulty of constructing node graphs headlessly
- **Component_Registry**: The `bpy.types.Object.components` collection (or equivalent UPBGE 0.50 API) that allows headless attachment of Python Components to objects at compile time
- **Runtime_Candidate**: The `.blend` file produced by the compiler containing both the 3D scene and embedded Python Component scripts, ready for blenderplayer launch
- **BGE_Module**: The `bge` Python package (`bge.logic`, `bge.events`, `bge.render`, `bge.types`) available at game runtime inside blenderplayer but NOT during headless `bpy` compilation
- **Player_Component**: The `KX_PythonComponent` subclass implementing WASD movement, mouse look, gravity, pause, and exit behaviors
- **Door_Component**: The `KX_PythonComponent` subclass implementing E-key door toggle with rotation animation
- **Grab_Component**: The `KX_PythonComponent` subclass implementing E-key object grab via raycasting
- **Smoke_Validator**: The compile-time structural check that opens Runtime_Candidate headlessly via `bpy` and verifies component attachment, text datablock presence, and scene integrity
- **Auto_Launch**: The system's invocation of blenderplayer on the compiled Runtime_Candidate without user intervention
- **First_Party_Script**: The reviewed `src/assembler/upbge_compile.py` that runs inside UPBGE's embedded Python to build the .blend
- **API_Probe**: A headless introspection script run inside UPBGE 0.50 to discover the actual available API surface for component attachment and physics configuration

## Requirements

### Requirement 1: UPBGE 0.50 API Discovery

**User Story:** As a pipeline developer, I want to discover and document the actual UPBGE 0.50 API surface for component attachment and physics configuration, so that the compiler uses verified API calls rather than guessing at removed interfaces.

#### Acceptance Criteria

1. WHEN the pipeline starts, THE API_Probe SHALL execute a headless introspection script inside UPBGE 0.50 that reports the available mechanism for attaching Python Components to objects
2. WHEN the API_Probe completes, THE API_Probe SHALL produce a structured report containing: whether `bpy.types.Object.components` exists, the method signature for adding components, and any physics configuration API replacements
3. IF the API_Probe fails to find a component attachment mechanism, THEN THE API_Probe SHALL report the failure with diagnostic details including available `bpy.types.Object` attributes
4. THE API_Probe SHALL complete within 15 seconds on the target hardware
5. THE API_Probe SHALL NOT import or reference the `bge` module (which is unavailable during headless execution)

### Requirement 2: Player Controller Migration to Python Component

**User Story:** As a user, I want the player controller to work in UPBGE 0.50 so that I can walk around the generated world using WASD and mouse look.

#### Acceptance Criteria

1. THE Player_Component SHALL subclass `bge.types.KX_PythonComponent` and implement `start()` and `update()` methods
2. WHEN the `update()` method executes each frame, THE Player_Component SHALL read keyboard state for W, A, S, D keys and apply directional movement relative to the player orientation
3. WHEN the `update()` method executes each frame, THE Player_Component SHALL read mouse position delta and apply yaw rotation to the player object and pitch rotation to the camera
4. WHEN the `update()` method executes each frame, THE Player_Component SHALL apply gravity force downward on the player object
5. WHEN the ESC key is pressed, THE Player_Component SHALL toggle the pause state (freezing movement and look)
6. WHEN the F10 key is pressed, THE Player_Component SHALL call `bge.logic.endGame()` to exit
7. THE Player_Component SHALL expose configurable `args` for move_speed, look_speed, and gravity magnitude
8. THE Player_Component SHALL center the mouse cursor each frame to provide continuous mouse-look without edge boundaries
9. FOR ALL valid Player_Component configurations, applying movement then reversing direction SHALL return the player position to within 0.01 units of origin (round-trip movement property)

### Requirement 3: Door Interaction Migration to Python Component

**User Story:** As a user, I want doors to open and close when I press E, so that I can navigate through doorways in the generated world.

#### Acceptance Criteria

1. THE Door_Component SHALL subclass `bge.types.KX_PythonComponent` and implement `start()` and `update()` methods
2. WHEN `start()` executes, THE Door_Component SHALL record the initial closed rotation angle from the object's local orientation
3. WHEN the `kiro_interact_requested` property becomes True on the owner object, THE Door_Component SHALL toggle the door between open and closed states
4. WHILE the door is transitioning, THE Door_Component SHALL animate rotation at the configured speed (degrees per second) toward the target angle
5. THE Door_Component SHALL expose configurable `args` for open_angle_deg (default 90), speed_deg_s (default 120), and initially_open (default False)
6. FOR ALL open_angle_deg values in [-180, 180] excluding zero, the door rotation SHALL reach the target angle and stop (convergence property)

### Requirement 4: Grab Interaction Migration to Python Component

**User Story:** As a user, I want to pick up and release dynamic objects by pressing E, so that I can interact with the generated world beyond walking.

#### Acceptance Criteria

1. THE Grab_Component SHALL subclass `bge.types.KX_PythonComponent` and implement `start()` and `update()` methods
2. WHEN E is pressed and no object is currently grabbed, THE Grab_Component SHALL raycast from the camera forward and attempt to interact with the hit object
3. WHEN the raycasted hit object has a `kiro_open_angle_deg` property, THE Grab_Component SHALL set `kiro_interact_requested = True` on that object (door trigger)
4. WHEN the raycasted hit object is a dynamic body within grab rules, THE Grab_Component SHALL attach the object (store its name and hold distance)
5. WHEN E is pressed and an object is currently grabbed, THE Grab_Component SHALL release the object
6. WHILE an object is grabbed, THE Grab_Component SHALL apply velocity to move the grabbed object toward the hold position in front of the camera
7. THE Grab_Component SHALL expose configurable `args` for max_distance_m (default 3.0) and hold_distance_m (default 1.5)

### Requirement 5: Compile-Time Component Attachment

**User Story:** As a pipeline developer, I want the compiler to attach Python Components to objects at compile time using the UPBGE 0.50 API, so that runtime_candidate.blend has working game logic without relying on the removed `.game` property.

#### Acceptance Criteria

1. WHEN `_configure_runtime()` executes, THE First_Party_Script SHALL attach the Player_Component to the player object using the UPBGE 0.50 component attachment API
2. WHEN a door interaction binding exists, THE First_Party_Script SHALL attach the Door_Component to the door object with the configured parameters
3. WHEN a grab interaction binding exists, THE First_Party_Script SHALL attach the Grab_Component to the player object with the configured parameters
4. THE First_Party_Script SHALL embed each component's source code as a Text datablock in the .blend file
5. THE First_Party_Script SHALL NOT reference `bpy.types.Object.game`, `game.sensors`, `game.controllers`, or `game.physics_type`
6. IF the UPBGE 0.50 component attachment API is unavailable (version mismatch), THEN THE First_Party_Script SHALL raise a clear error with diagnostic information rather than silently producing a non-functional .blend
7. WHEN component attachment succeeds, THE First_Party_Script SHALL save the Runtime_Candidate .blend file to disk

### Requirement 6: Physics Configuration Without Legacy API

**User Story:** As a pipeline developer, I want the compiler to configure physics properties on objects using UPBGE 0.50's current API, so that the player has collision and gravity works correctly.

#### Acceptance Criteria

1. WHEN configuring the player object, THE First_Party_Script SHALL set the physics type to CHARACTER (or equivalent UPBGE 0.50 physics enum) using the current API surface
2. WHEN configuring the player object, THE First_Party_Script SHALL enable collision bounds with CAPSULE shape
3. WHEN configuring door objects, THE First_Party_Script SHALL set the appropriate physics type for kinematic rotation
4. WHEN configuring dynamic grab targets, THE First_Party_Script SHALL set the physics type to DYNAMIC with the specified mass
5. IF the UPBGE 0.50 physics API differs from the discovered probe results, THEN THE First_Party_Script SHALL report the discrepancy and halt compilation

### Requirement 7: Smoke Validator Update

**User Story:** As a pipeline developer, I want the smoke validator to verify Python Component attachment instead of logic brick wiring, so that the quality gate correctly identifies functional runtime_candidate.blend files.

#### Acceptance Criteria

1. WHEN validating a Runtime_Candidate, THE Smoke_Validator SHALL open the .blend file headlessly via `bpy` and verify that the player object has a registered Python Component
2. WHEN validating a Runtime_Candidate, THE Smoke_Validator SHALL verify that all required Text datablocks (component source files) are present in `bpy.data.texts`
3. WHEN validating a Runtime_Candidate, THE Smoke_Validator SHALL verify that door objects have the Door_Component attached
4. WHEN validating a Runtime_Candidate, THE Smoke_Validator SHALL verify that the player object has physics configuration appropriate for character movement
5. IF any mandatory check fails, THEN THE Smoke_Validator SHALL report the specific failed check with diagnostic details
6. THE Smoke_Validator SHALL NOT enter game mode, launch blenderplayer, or open a visible window
7. THE Smoke_Validator SHALL complete validation within 30 seconds

### Requirement 8: blenderplayer Launch and Persistence

**User Story:** As a user, I want blenderplayer to launch the generated world and stay running so that I can walk around inside it.

#### Acceptance Criteria

1. WHEN auto-launch is triggered with a valid Runtime_Candidate, THE Auto_Launch SHALL invoke blenderplayer with the Runtime_Candidate path
2. WHEN blenderplayer starts, THE Auto_Launch SHALL verify the process remains running for a minimum of 3 seconds (indicating successful scene load rather than immediate exit)
3. IF blenderplayer exits within 3 seconds, THEN THE Auto_Launch SHALL report the failure with the process exit code and any captured stderr output
4. WHILE blenderplayer is running, THE Player_Component SHALL process input and render frames (the game loop is active)
5. WHEN the user presses F10, THE Player_Component SHALL terminate the game cleanly via `bge.logic.endGame()`
6. THE Auto_Launch SHALL NOT pass the `--background` flag to blenderplayer (which would prevent rendering)

### Requirement 9: Graceful Degradation Preservation

**User Story:** As a pipeline developer, I want the system to degrade gracefully when UPBGE 0.50's component API is not available or behaves unexpectedly, so that users still receive a viewable scene even if walkability fails.

#### Acceptance Criteria

1. IF component attachment fails during compilation, THEN THE First_Party_Script SHALL still save the scene .blend file (without game logic) as the fallback artifact
2. IF the Runtime_Candidate cannot be produced, THEN THE Pipeline SHALL serve the scene.blend via download link with a clear message that walkability is unavailable
3. IF blenderplayer is not found alongside the editor, THEN THE Pipeline SHALL report auto-launch as unavailable without crashing
4. THE Pipeline SHALL log all degradation events with machine-readable reason codes for diagnostic purposes
5. WHEN degradation occurs, THE Pipeline SHALL include the specific UPBGE 0.50 API error in diagnostics to aid future debugging

### Requirement 10: Component Source Portability

**User Story:** As a pipeline developer, I want the Python Component source code to be self-contained within the .blend file, so that blenderplayer can find and instantiate the components without external file dependencies.

#### Acceptance Criteria

1. THE First_Party_Script SHALL embed each component class as a named Text datablock within the .blend file (e.g., `kiro_player_first_person.py`)
2. THE component module path registered on the object SHALL reference the embedded Text datablock name
3. WHEN blenderplayer loads the .blend, THE BGE_Module runtime SHALL locate the component class via the embedded Text datablock without requiring files on the filesystem
4. FOR ALL component Text datablocks, the source code SHALL be valid Python that imports only from `bge`, `mathutils`, `math`, `json`, and Python standard library modules
5. THE component source SHALL NOT import from `bpy` (unavailable at game runtime) or any third-party packages

