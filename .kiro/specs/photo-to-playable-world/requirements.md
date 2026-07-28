# Requirements Document

## Introduction

This specification defines the "Photo-to-Playable-World" pipeline — a local-only system that accepts a single RGB photograph of an indoor scene and produces a fully interactive, physics-driven 3D game sandbox via UPBGE 0.50. The pipeline segments objects from the photo, reconstructs geometry via metric depth estimation, generates textured 3D meshes per object, estimates lighting and scale, assembles a WorldContract, and launches the game through the existing UPBGE compilation and auto-launch infrastructure.

The photo pipeline coexists alongside the existing text-to-playable-world pipeline as an alternative input mode. Both pipelines converge at the WorldContract schema — reusing the same UPBGE compiler, parity gates, smoke validation, and blenderplayer auto-launch chain.

### Environment Assumptions

- **NVIDIA RTX 3090+ (24GB VRAM), 32GB+ RAM, Windows 11.** Local GPU inference for segmentation, depth estimation, inpainting, and 3D generation.
- **ComfyUI on localhost:8188** with SAM ViT-H, Flux.1-Fill, MoGe-2, and Hunyuan3D 2.0 nodes installed and operational.
- **UPBGE 0.50 installed** (blender.exe + blenderplayer.exe) with Python Components (`KX_PythonComponent` with `start()`/`update()` lifecycle).
- **Python 3.10+, CUDA 12.1+** for all local inference stages.
- **Single-user, single-session-at-a-time** compilation (existing FIFO queue applies).
- **No cloud API calls** — all inference runs locally.
- **No neural scene representations** — standard polygonal GLB meshes only (no NeRF, no Gaussian splatting).

## Glossary

- **Photo_Pipeline**: The end-to-end sequence of stages that transforms a source photograph into a playable game world via WorldContract assembly
- **Source_Image**: The single RGB photograph provided as input — must depict an indoor scene
- **Scene_Parser**: The stage that performs SAM segmentation to produce per-object masks and a background mask, then inpaints occluded regions to produce a clean room plate and isolated object PNGs
- **SAM**: Segment Anything Model (ViT-H variant) — produces instance segmentation masks from an input image
- **Inpainter**: Flux.1-Fill model running via ComfyUI — fills masked regions to produce clean background plates and isolated object textures
- **Room_Plate**: The inpainted background image with all foreground objects removed — used as texture source for the room mesh
- **Object_PNG**: An isolated RGBA image of a single segmented object on transparent background
- **Depth_Estimator**: MoGe-2 metric depth estimation model — produces metric depth maps (meters) from a single image
- **Normal_Map**: Surface normal estimates derived from the depth map — used for room mesh reconstruction
- **Room_Mesh**: A textured GLB mesh representing the room shell (floor, walls, ceiling) reconstructed from the depth map and room plate
- **Object_Generator**: The 3D mesh generation stage — attempts Hunyuan3D 2.0 first, with fallback chain to Unique3D, TripoSR, or placeholder geometry
- **Object_Mesh**: A textured GLB mesh for a single segmented object produced by the Object_Generator
- **Audio_Synthesizer**: The stage that produces per-object impact WAV files — either via ComfyUI audio nodes or a material-based sound bank lookup
- **Light_Estimator**: The stage that estimates sun direction, color temperature, intensity, and ambient parameters from the source image
- **Scale_Calibrator**: The stage that converts pixel footprints to real-world dimensions using metric depth, camera FOV, and known reference heuristics
- **Layout_Estimator**: The stage that back-projects 2D object positions into 3D coordinates using depth data and performs physics settle optimization
- **Fallback_Chain**: The ordered list of alternative methods attempted when a primary stage fails (Hunyuan3D → Unique3D → TripoSR → placeholder)
- **Placeholder_Geometry**: A primitive mesh (box, cylinder, or sphere) with the object's extracted average color used when all 3D generation methods fail
- **LOD_Generator**: Level-of-Detail generation via Blender's Decimate modifier — produces 4 levels (100%, 50%, 25%, 10% face count)
- **V-HACD**: Volumetric Hierarchical Approximate Convex Decomposition — generates compound collision shapes from arbitrary meshes
- **Physics_Settle**: A pre-player simulation pass that drops objects under gravity to find stable resting positions before the player spawns
- **WorldContract**: The existing engine-neutral Pydantic schema (positions, materials, physics, interactions, lights, cameras) in meters, right-handed Y-up coordinates
- **Pipeline_Orchestrator**: The `run_photo_pipeline.py` script that coordinates all stages and integrates with existing session management
- **ComfyUI**: The local node-based inference server on localhost:8188 used for image segmentation, inpainting, depth estimation, and 3D generation
- **UPBGE_Compiler**: The existing `upbge_compile.py` sidecar that converts a WorldContract into a playable .blend file using UPBGE 0.50 Python Components

## Requirements

### Requirement 1: End-to-End Photo Pipeline — Image In, Game Running

**User Story:** As a user, I want to provide a single photograph of an indoor room and have a playable 3D game launch automatically, so that I can walk around inside a digital recreation of the photographed space.

#### Acceptance Criteria

1. WHEN a user submits a valid Source_Image (RGB, JPEG or PNG, resolution between 512×512 and 8192×8192 pixels, file size under 50MB) via the pipeline interface, THE Photo_Pipeline SHALL produce a WorldContract and pass it to the existing UPBGE compilation and auto-launch chain
2. WHEN the Photo_Pipeline completes successfully, THE system SHALL auto-launch the compiled game via blenderplayer in fullscreen game mode using the existing Auto_Launch mechanism
3. THE Photo_Pipeline SHALL complete all stages (segmentation through WorldContract assembly) within 15 minutes for scenes containing up to 10 segmented objects, with a target of 5-8 minutes on an RTX 4090
4. IF any pipeline stage fails and no fallback is available, THEN THE Photo_Pipeline SHALL report the failure stage name, a machine-readable reason code, and a human-readable diagnostic message without corrupting the session state
5. IF the submitted file is not a valid RGB image (corrupt header, unsupported format, grayscale-only, resolution outside bounds, or file size exceeds 50MB), THEN THE Photo_Pipeline SHALL reject the input with a descriptive validation error before invoking any inference stage
6. THE Photo_Pipeline SHALL execute all stages locally without cloud API calls — all inference models run on the local GPU via ComfyUI or direct Python invocation
7. THE Photo_Pipeline SHALL integrate with the existing session management system (unique session ID, isolated output directory, FIFO compilation queue, TTL cleanup)

### Requirement 2: Scene Parsing — Segmentation and Inpainting

**User Story:** As a pipeline stage, I want to segment the source photo into individual objects and produce clean isolated images, so that downstream stages can process each object independently.

#### Acceptance Criteria

1. WHEN the Scene_Parser receives a valid Source_Image, THE Scene_Parser SHALL invoke SAM (ViT-H) via ComfyUI to produce per-object instance segmentation masks and a combined background mask
2. WHEN SAM produces segmentation masks, THE Scene_Parser SHALL filter masks by minimum area (configurable, default 0.5% of image area) and maximum count (configurable, default 30 objects) to discard noise segments
3. WHEN segmentation produces valid object masks, THE Scene_Parser SHALL invoke the Inpainter (Flux.1-Fill via ComfyUI) to fill masked regions in the Source_Image producing a clean Room_Plate with all foreground objects removed
4. WHEN segmentation produces valid object masks, THE Scene_Parser SHALL extract each object as an isolated RGBA Object_PNG with transparent background by applying the corresponding mask to the Source_Image
5. THE Scene_Parser SHALL output a structured manifest listing each segmented object with: mask ID, bounding box (pixel coordinates), area (pixels), centroid (pixel coordinates), and the file path to its Object_PNG
6. IF SAM segmentation produces zero valid masks after area filtering, THEN THE Scene_Parser SHALL treat the entire image as a single room with no foreground objects and proceed with an empty object list
7. IF the Inpainter fails or produces output that differs in resolution from the Source_Image, THEN THE Scene_Parser SHALL fall back to using the Source_Image directly as the Room_Plate and log a warning

### Requirement 3: Environment Reconstruction — Depth and Room Mesh

**User Story:** As a pipeline stage, I want to estimate metric depth from the photo and reconstruct a textured room mesh, so that the player has a navigable 3D environment.

#### Acceptance Criteria

1. WHEN the Depth_Estimator receives the Source_Image, THE Depth_Estimator SHALL invoke MoGe-2 via ComfyUI to produce a metric depth map with values in meters at the same resolution as the Source_Image
2. WHEN the Depth_Estimator produces a valid depth map, THE system SHALL derive a normal map from the depth gradients for use in mesh reconstruction
3. WHEN the depth map and Room_Plate are available, THE system SHALL reconstruct a Room_Mesh (GLB format) representing floor, walls, and ceiling surfaces textured with the Room_Plate image
4. THE Room_Mesh SHALL be oriented in the WorldContract coordinate system (right-handed, Y-up, meters) with the camera viewpoint corresponding to the Source_Image's perspective
5. THE Room_Mesh SHALL have vertex count within configurable bounds (default minimum 1000, maximum 500000) to balance reconstruction fidelity against runtime performance
6. IF MoGe-2 fails or produces a depth map where more than 50% of pixels have invalid (zero or infinite) depth values, THEN THE Depth_Estimator SHALL fall back to a flat-floor heuristic (room depth = 4m, width derived from image aspect ratio, height = 2.7m) and log a warning
7. THE reconstructed Room_Mesh dimensions (width, depth, height in meters) SHALL be recorded for use by the Scale_Calibrator and Layout_Estimator

### Requirement 4: Object 3D Generation with Fallback Chain

**User Story:** As a pipeline stage, I want to generate textured 3D meshes for each segmented object with graceful degradation, so that every object in the scene has geometry even if the primary generator fails.

#### Acceptance Criteria

1. WHEN the Object_Generator receives an Object_PNG, THE Object_Generator SHALL attempt Hunyuan3D 2.0 (via ComfyUI) to produce a textured GLB mesh
2. IF Hunyuan3D 2.0 fails or produces a mesh with zero faces, THEN THE Object_Generator SHALL attempt Unique3D as the second fallback
3. IF Unique3D fails or produces a mesh with zero faces, THEN THE Object_Generator SHALL attempt TripoSR as the third fallback
4. IF all neural 3D generators fail, THEN THE Object_Generator SHALL produce a Placeholder_Geometry (box, cylinder, or sphere selected by aspect ratio of the Object_PNG bounding box) textured with the average color extracted from the Object_PNG
5. THE Object_Generator SHALL record which method succeeded for each object in the pipeline manifest (hunyuan3d, unique3d, triposr, or placeholder) along with generation time
6. WHEN a neural generator produces a valid mesh, THE Object_Generator SHALL validate that the mesh has at least 4 faces, at least 4 vertices, and non-degenerate geometry (no zero-area faces exceeding 5% of total face count)
7. THE Object_Generator SHALL enforce a per-object generation timeout (configurable, default 120 seconds per object) and fall to the next method in the chain on timeout

### Requirement 5: Audio Synthesis — Per-Object Impact Sounds

**User Story:** As a pipeline stage, I want to generate impact audio for each object, so that physics interactions in the game produce appropriate sounds.

#### Acceptance Criteria

1. WHEN the Audio_Synthesizer processes an object, THE Audio_Synthesizer SHALL produce a WAV file (mono, 44100Hz, 16-bit, duration 0.1-2.0 seconds) representing the object's impact sound
2. THE Audio_Synthesizer SHALL select the sound generation method based on availability: ComfyUI audio nodes if installed, otherwise a material-based sound bank lookup using the object's estimated material category
3. WHEN using the material-based sound bank, THE Audio_Synthesizer SHALL map object categories to predefined impact sounds (wood, metal, glass, fabric, ceramic, plastic) based on visual material estimation from the Object_PNG
4. IF both ComfyUI audio nodes and sound bank lookup fail for an object, THEN THE Audio_Synthesizer SHALL assign a default generic impact sound and log a warning
5. THE Audio_Synthesizer SHALL normalize all generated WAV files to peak amplitude of -3dBFS to prevent clipping during simultaneous playback

### Requirement 6: Light Estimation

**User Story:** As a pipeline stage, I want to estimate the lighting conditions from the source photo, so that the 3D recreation has realistic illumination matching the original scene.

#### Acceptance Criteria

1. WHEN the Light_Estimator receives the Source_Image, THE Light_Estimator SHALL estimate primary light direction (as a 3D vector in WorldContract coordinates), color temperature (Kelvin), and relative intensity
2. THE Light_Estimator SHALL produce at minimum one directional light (sun/key light) and one ambient light term for the WorldContract
3. WHEN the Source_Image exhibits strong directional shadows, THE Light_Estimator SHALL orient the primary directional light to be consistent with observed shadow directions
4. THE Light_Estimator SHALL bound output intensity values within the WorldContract's valid range (0.0 to maximum 100.0) and color temperature within physically plausible bounds (1800K to 12000K)
5. IF light estimation fails or produces degenerate results (zero intensity on all lights, or light direction is a zero vector), THEN THE Light_Estimator SHALL fall back to a default overhead neutral light (direction [0, -1, 0], 5500K, intensity 1.0) and log a warning

### Requirement 7: Scale Calibration and Layout Estimation

**User Story:** As a pipeline stage, I want to determine real-world sizes and 3D positions for each object, so that the WorldContract contains physically plausible dimensions and placement.

#### Acceptance Criteria

1. WHEN the Scale_Calibrator processes a segmented object, THE Scale_Calibrator SHALL compute real-world dimensions (width, height, depth in meters) by combining the object's pixel footprint, its metric depth value from the depth map, and the estimated camera FOV
2. THE Scale_Calibrator SHALL clamp computed object dimensions to physically plausible bounds (minimum 0.01m, maximum equal to the room dimension on that axis) to prevent degenerate scales from depth noise
3. WHEN the Layout_Estimator receives calibrated object dimensions and depth data, THE Layout_Estimator SHALL compute 3D positions by back-projecting each object's centroid through the camera model using the metric depth value at that pixel
4. WHEN initial 3D positions are computed, THE Layout_Estimator SHALL run a physics settle optimization (gravity simulation, maximum 500 iterations or 5 seconds wall time) to resolve floating objects and interpenetration
5. THE Layout_Estimator SHALL output each object's final position (x, y, z in meters) and rotation (degrees) in WorldContract coordinates after settle completes
6. IF the physics settle fails to converge within the iteration or time limit, THEN THE Layout_Estimator SHALL use the pre-settle back-projected positions and log a warning identifying unconverged objects
7. THE Scale_Calibrator SHALL record the scale factor and confidence metric (0.0-1.0) for each object, where confidence below 0.3 triggers a flag in the pipeline manifest

### Requirement 8: WorldContract Assembly from Photo Pipeline

**User Story:** As a pipeline stage, I want to map all upstream stage outputs into the existing WorldContract schema, so that the existing UPBGE compiler, parity gates, and auto-launch chain work without modification.

#### Acceptance Criteria

1. WHEN all upstream stages complete, THE WorldContract assembler SHALL produce a valid WorldContract instance that passes all existing schema validators (coordinate system, ID uniqueness, dangling reference checks, material graph integrity)
2. THE WorldContract assembler SHALL map the Room_Mesh to a RoomShell entry with dimensions matching the reconstructed room extents and material IDs referencing materials derived from the Room_Plate texture
3. THE WorldContract assembler SHALL map each Object_Mesh to a WorldInstance entry with: stable ID derived from the segmentation mask ID, transform from the Layout_Estimator, dimensions from the Scale_Calibrator, material from the object's extracted texture, and geometry_strategy set to "asset"
4. THE WorldContract assembler SHALL map each object's physics properties based on its estimated material category and dimensions: static bodies for objects estimated above 50kg or marked as architectural, dynamic bodies for lighter objects with mass derived from volume and material density heuristics
5. THE WorldContract assembler SHALL include light entries from the Light_Estimator and a camera binding derived from the source image's estimated camera parameters
6. THE WorldContract assembler SHALL set the ExportPolicy targets to include "upbge_runtime" to trigger the existing compilation path
7. IF the assembled WorldContract fails schema validation, THEN THE assembler SHALL report which field or constraint failed with the specific validation error from the Pydantic model

### Requirement 9: Collision Generation and LOD

**User Story:** As a pipeline stage, I want each object mesh to have appropriate collision shapes and level-of-detail variants, so that the runtime maintains 60 FPS with accurate physics.

#### Acceptance Criteria

1. WHEN processing an Object_Mesh, THE system SHALL generate a V-HACD compound collision decomposition (maximum 16 convex hulls, minimum 10000 voxel resolution) for objects with non-trivial geometry (more than 100 faces)
2. WHEN processing an Object_Mesh with 100 or fewer faces, THE system SHALL use the mesh directly as a convex hull collision shape rather than running V-HACD decomposition
3. THE LOD_Generator SHALL produce 4 level-of-detail variants for each Object_Mesh using the Decimate modifier: LOD0 (100% original), LOD1 (50% faces), LOD2 (25% faces), LOD3 (10% faces)
4. WHEN a Decimate operation would reduce face count below 4, THE LOD_Generator SHALL clamp to 4 faces minimum to prevent degenerate geometry
5. THE collision shapes and LOD meshes SHALL be stored alongside the source Object_Mesh GLB and referenced in the WorldContract physics intent entries
6. IF V-HACD decomposition fails or times out (default 30 seconds per object), THEN THE system SHALL fall back to a bounding-box collision shape and log a warning

### Requirement 10: Physics Settle and Pre-Player Validation

**User Story:** As a developer, I want objects to be physically stable before the player spawns, so that the world doesn't explode with collisions on first frame.

#### Acceptance Criteria

1. WHEN the WorldContract is assembled and before UPBGE compilation, THE Physics_Settle stage SHALL simulate all dynamic objects under gravity for up to 500 iterations to find stable resting positions
2. THE Physics_Settle SHALL detect and resolve interpenetration between objects by applying separation impulses, with a maximum displacement of 0.5m per object per iteration
3. WHEN Physics_Settle completes, THE system SHALL update the WorldContract instance transforms with the settled positions, preserving the original positions in the pipeline manifest for debugging
4. THE Physics_Settle SHALL flag objects that remain in an unstable state (linear velocity above 0.01 m/s or penetration depth above 0.01m) after the iteration limit as "unsettled" in the manifest
5. IF more than 50% of dynamic objects are flagged as unsettled, THEN THE system SHALL log a warning but SHALL NOT reject the WorldContract — the UPBGE runtime physics will resolve remaining instabilities at game start
6. THE Physics_Settle stage SHALL complete within 10 seconds wall time for scenes with up to 30 objects

### Requirement 11: Pipeline Orchestration and Session Integration

**User Story:** As a developer, I want the photo pipeline to integrate with the existing session management and FIFO compilation queue, so that it operates consistently alongside the text-to-world pipeline.

#### Acceptance Criteria

1. THE Pipeline_Orchestrator SHALL create a new session (unique UUID, isolated output directory) when a photo submission is received, following the same session lifecycle as the text-to-world pipeline
2. THE Pipeline_Orchestrator SHALL execute stages in dependency order: Scene Parsing → Depth Estimation → Object Generation (parallel per object) → Audio Synthesis (parallel per object) → Light Estimation → Scale Calibration → Layout Estimation → Physics Settle → WorldContract Assembly → UPBGE Compilation → Auto-Launch
3. WHEN stages have no data dependencies between them (Object Generation per different objects, Audio Synthesis per different objects), THE Pipeline_Orchestrator SHALL execute them in parallel with configurable concurrency (default: 2 concurrent GPU tasks, 4 concurrent CPU tasks)
4. THE Pipeline_Orchestrator SHALL push stage progress events via the existing SSE mechanism, delivering each stage transition within 2 seconds of occurrence
5. THE Pipeline_Orchestrator SHALL persist intermediate artifacts (masks, depth maps, Object_PNGs, GLB meshes, WAV files) in the session output directory with consistent naming conventions
6. IF ComfyUI on localhost:8188 is unreachable at pipeline start, THEN THE Pipeline_Orchestrator SHALL fail immediately with a clear diagnostic rather than timing out on the first inference call
7. THE Pipeline_Orchestrator SHALL enforce a total pipeline timeout (configurable, default 20 minutes) and SHALL terminate all in-progress inference tasks if the timeout is exceeded

### Requirement 12: Fallback and Degradation Strategy

**User Story:** As a user, I want the pipeline to produce a playable result even when individual stages partially fail, so that I always get something I can walk around in.

#### Acceptance Criteria

1. WHEN the Object_Generator fails for a specific object (all methods in the Fallback_Chain exhausted), THE Photo_Pipeline SHALL substitute Placeholder_Geometry and continue processing remaining objects rather than aborting the entire pipeline
2. WHEN the Audio_Synthesizer fails for a specific object, THE Photo_Pipeline SHALL assign a silent placeholder (zero-length WAV) and continue without blocking other objects
3. WHEN the Depth_Estimator produces a low-confidence result (more than 30% invalid pixels), THE Photo_Pipeline SHALL still attempt room reconstruction using valid pixels with interpolation for gaps, degrading gracefully to the flat-floor heuristic only when reconstruction is impossible
4. THE Photo_Pipeline SHALL produce a valid WorldContract and launch the game as long as: (a) the Room_Mesh was generated (even via flat-floor heuristic), AND (b) the WorldContract passes schema validation. Zero successfully generated Object_Meshes is acceptable — the player can still explore an empty room.
5. THE pipeline manifest SHALL record the degradation path for each object (which fallbacks were triggered, which stages used heuristics) for diagnostic purposes
6. THE Photo_Pipeline SHALL classify its final output quality as one of: "full" (all primary methods succeeded), "degraded" (one or more fallbacks triggered), or "minimal" (room-only, no object meshes) and include this classification in the session metadata

### Requirement 13: Serialization Round-Trip Integrity for Photo Pipeline Artifacts

**User Story:** As a developer, I want the photo pipeline's intermediate artifacts to serialize and deserialize losslessly, so that pipeline stages can be re-run independently without data corruption.

#### Acceptance Criteria

1. FOR ALL pipeline manifest instances, serializing to JSON then deserializing SHALL produce a structurally equal manifest where every field value compares equal
2. FOR ALL Object_Mesh GLB files produced by the pipeline, the vertex positions, normals, and UV coordinates SHALL survive a round-trip through the GLB read/write path without exceeding 1e-6 absolute tolerance per component
3. FOR ALL depth maps produced by MoGe-2, serializing to NumPy .npy format then loading SHALL produce bit-identical float32 arrays
4. THE pipeline manifest JSON serialization SHALL use the same canonical format as the existing WorldContract serialization (sorted keys, no whitespace, UTF-8 encoding)
5. FOR ALL WorldContract instances produced by the photo pipeline assembler, the contract SHALL pass the existing `canonical_world_contract()` round-trip validation (serialize → deserialize → serialize produces identical bytes)

### Requirement 14: Existing Pipeline Preservation

**User Story:** As a developer, I want the photo pipeline to coexist with the text-to-world pipeline without breaking existing functionality.

#### Acceptance Criteria

1. THE Photo_Pipeline SHALL operate as a separate input mode alongside the existing text-to-world pipeline — both accessible from the same interface with mode selection
2. THE WorldContract schema SHALL remain unchanged — the photo pipeline maps its outputs into the existing schema without requiring schema modifications
3. THE existing UPBGE compilation path (upbge_compile.py), parity gates, smoke validation, and auto-launch chain SHALL be reused without modification by the photo pipeline
4. THE existing text-to-world pipeline behavior (all V3-V11 interfaces, MVP mode, full mode) SHALL continue to function identically after the photo pipeline is added
5. THE session management system SHALL distinguish photo-pipeline sessions from text-pipeline sessions via a "source_type" field ("photo" or "text") in the session metadata, while using the same FIFO queue and concurrency limits

