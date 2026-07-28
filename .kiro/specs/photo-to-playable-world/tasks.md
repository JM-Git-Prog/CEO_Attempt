# Implementation Plan: Photo-to-Playable-World Pipeline

## Overview

This plan implements the photo-to-playable-world pipeline that transforms a single RGB photograph of an indoor scene into a running 3D game via UPBGE 0.50. The implementation follows the critical path: input validation → scene parsing → depth estimation → object generation → audio synthesis → light/scale/layout → physics settle → WorldContract assembly → existing UPBGE compilation chain.

All code is Python 3.10+ (FastAPI, Pydantic, Hypothesis, trimesh, numpy, PyBullet). The project already has existing pipeline infrastructure — this plan adds the photo pipeline as an alternative input mode that converges at the WorldContract schema, reusing the same UPBGE compiler, parity gates, smoke validation, and blenderplayer auto-launch chain.

New code goes in `src/photo_pipeline/` with ComfyUI workflow templates in `src/photo_pipeline/workflows/`, sound bank assets in `assets/sound_bank/`, and tests in `tests/test_photo_*.py`.

## Tasks

- [x] 1. Package structure, data models, and ComfyUI client
  - [x] 1.1 Create photo_pipeline package structure and core data models
    - Create `src/photo_pipeline/__init__.py`, `src/photo_pipeline/stages/__init__.py`
    - Create `src/photo_pipeline/models.py` with all dataclasses: `PhotoPipelineConfig`, `StageResult`, `PipelineManifest`, `ObjectManifestEntry`, `SegmentedObject`, `PhotoSessionMetadata`
    - Create `src/photo_pipeline/reason_codes.py` with `ReasonCode` enum
    - Ensure `PhotoPipelineConfig` has all configurable fields (comfyui_url, max_objects, min_mask_area_pct, timeouts, concurrency limits, LOD levels, VHACD params)
    - _Requirements: 1.4, 1.7, 11.1, 11.5, 12.5, 12.6_

  - [x] 1.2 Implement ComfyUI client (`src/photo_pipeline/comfyui_client.py`)
    - Implement `ComfyUIClient` class with async HTTP methods: `health_check()`, `submit_workflow()`, `wait_for_completion()`, `get_output_image()`, `get_output_mesh()`
    - Health check hits `/system_stats` endpoint — returns True if reachable, False otherwise
    - `submit_workflow()` posts to `/prompt` endpoint with workflow JSON, returns prompt_id
    - `wait_for_completion()` polls `/history/{prompt_id}` with configurable timeout
    - Handle VRAM OOM recovery: call `/free` endpoint, wait 2s, retry once
    - _Requirements: 1.6, 11.6_


  - [x] 1.3 Create ComfyUI workflow JSON templates
    - Create `src/photo_pipeline/workflows/sam_segment.json` — SAM ViT-H segmentation workflow
    - Create `src/photo_pipeline/workflows/flux_inpaint.json` — Flux.1-Fill inpainting workflow
    - Create `src/photo_pipeline/workflows/moge2_depth.json` — MoGe-2 metric depth estimation workflow
    - Create `src/photo_pipeline/workflows/hunyuan3d_gen.json` — Hunyuan3D 2.0 mesh generation workflow
    - Create `src/photo_pipeline/workflows/unique3d_gen.json` — Unique3D fallback workflow
    - Create `src/photo_pipeline/workflows/triposr_gen.json` — TripoSR fallback workflow
    - Create `src/photo_pipeline/workflows/audio_impact.json` — ComfyUI audio impact synthesis workflow
    - Each template accepts parameterized inputs (image path, mask path, output path)
    - _Requirements: 2.1, 3.1, 4.1, 5.2_

  - [x] 1.4 Implement input validator (`src/photo_pipeline/input_validator.py`)
    - Validate file exists, file size ≤ 50MB, valid image header (JPEG or PNG)
    - Validate RGB color mode (reject grayscale-only)
    - Validate resolution within 512×512 to 8192×8192 bounds
    - Return descriptive validation error identifying the specific failure reason
    - No inference stage invoked on validation failure
    - _Requirements: 1.5_

  - [x] 1.5 Write property test for input validation (Property 1)
    - **Property 1: Invalid Input Rejection**
    - For any byte sequence that is not a valid RGB image (corrupt header, wrong format, grayscale, resolution outside bounds, size exceeding 50MB), the validator SHALL reject with descriptive error
    - **Validates: Requirements 1.5**

- [x] 2. Scene Parsing — Segmentation and Inpainting
  - [x] 2.1 Implement Scene Parser (`src/photo_pipeline/stages/scene_parser.py`)
    - Implement `SceneParser.parse()` — submits SAM ViT-H workflow via ComfyUI client
    - Build SAM workflow JSON from template with source image path
    - Parse SAM output into per-object binary masks and combined background mask
    - Filter masks by minimum area (configurable, default 0.5% of image area) and maximum count (default 30)
    - Extract each object as isolated RGBA Object_PNG (mask applied to source, transparent background)
    - Submit Flux.1-Fill inpainting workflow to produce clean Room_Plate (all objects removed)
    - Output structured `SceneParseResult` with manifest entries per object (mask_id, bbox, area, centroid, png_path)
    - Handle edge case: zero valid masks → empty object list, source becomes room plate
    - Handle edge case: inpainter failure or resolution mismatch → use source as room plate, log warning
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_


  - [x] 2.2 Write property test for mask area and count filtering (Property 2)
    - **Property 2: Mask Area and Count Filtering**
    - For any list of masks with random areas and config (min_area_pct, max_count), all output masks have area >= threshold and count <= max_count
    - **Validates: Requirements 2.2**

  - [x] 2.3 Write property test for Object PNG extraction (Property 3)
    - **Property 3: Object PNG Extraction Produces Correct Transparency**
    - For any source RGB image and binary mask of matching dimensions, extracted RGBA has transparent pixels exactly where mask is 0
    - **Validates: Requirements 2.4**

- [x] 3. Depth Estimation and Room Mesh Reconstruction
  - [x] 3.1 Implement Depth Estimator (`src/photo_pipeline/stages/depth_estimator.py`)
    - Implement `DepthEstimator.estimate()` — submits MoGe-2 workflow via ComfyUI client
    - Retrieve depth map output as float32 numpy array (meters)
    - Validate depth map: compute valid pixel ratio (non-zero, non-infinite)
    - Derive normal map from depth gradients using finite differences
    - Implement fallback: if >50% invalid pixels, use flat-floor heuristic (4m depth, width from aspect ratio, 2.7m height)
    - Save depth_map.npy and normal_map.npy to session directory
    - Return `DepthResult` with paths, valid_pixel_ratio, depth_range
    - _Requirements: 3.1, 3.2, 3.6_

  - [x] 3.2 Write property test for normal map unit vectors (Property 4)
    - **Property 4: Normal Map Contains Unit Vectors**
    - For any valid depth map (positive finite float32 values), computed normals have magnitude within [0.99, 1.01]
    - **Validates: Requirements 3.2**

  - [x] 3.3 Write property test for depth fallback threshold (Property 5)
    - **Property 5: Depth Fallback Threshold**
    - For any depth map where >50% pixels are invalid → flat-floor heuristic; ≤50% invalid → use actual depth
    - **Validates: Requirements 3.6**

  - [x] 3.4 Implement Room Mesh Reconstructor (`src/photo_pipeline/stages/room_reconstructor.py`)
    - Implement `RoomReconstructor.reconstruct()` using trimesh
    - Convert depth map to point cloud, then to mesh via Poisson or Delaunay triangulation
    - Texture mesh with Room_Plate image (UV mapping from pixel coordinates)
    - Orient in WorldContract coordinates (right-handed, Y-up, meters)
    - Enforce vertex count bounds (min 1000, max 500000) via decimation if needed
    - Implement `_flat_floor_fallback()` — box room from aspect ratio heuristic
    - Return `RoomMeshResult` with GLB path, dimensions, vertex/face counts, heuristic flag
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7_


- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Object 3D Generation with Fallback Chain
  - [x] 5.1 Implement Object Generator (`src/photo_pipeline/stages/object_generator.py`)
    - Implement `ObjectGenerator.generate()` with full fallback chain: Hunyuan3D 2.0 → Unique3D → TripoSR → placeholder
    - Each neural generator: submit ComfyUI workflow, retrieve GLB, validate mesh (≥4 faces, ≥4 vertices, ≤5% zero-area faces)
    - Per-object timeout (configurable, default 120s) — fall to next method on timeout
    - Implement `_create_placeholder()` — select primitive by aspect ratio (box for near-square, cylinder for tall/narrow, sphere for small uniform), texture with average non-transparent color
    - Record method_used and generation_time_s per object
    - Return `ObjectMeshResult` with GLB path, method, timing, face/vertex counts
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 5.2 Write property test for mesh validation (Property 6)
    - **Property 6: Mesh Validation Correctness**
    - For any mesh, validation returns True iff faces ≥ 4, vertices ≥ 4, and zero-area face ratio ≤ 0.05
    - **Validates: Requirements 4.6**

  - [x] 5.3 Write property test for placeholder geometry selection (Property 7)
    - **Property 7: Placeholder Geometry Selection by Aspect Ratio**
    - For any bounding box dimensions, placeholder type is deterministically selected by aspect ratio; textured with average color from non-transparent pixels
    - **Validates: Requirements 4.4**

- [x] 6. Audio Synthesis
  - [x] 6.1 Implement Audio Synthesizer (`src/photo_pipeline/stages/audio_synthesizer.py`)
    - Implement `AudioSynthesizer.synthesize()` — try ComfyUI audio nodes first, fallback to sound bank
    - Implement `_estimate_material()` — classify object into {wood, metal, glass, fabric, ceramic, plastic} from Object_PNG visual features (color histogram heuristic)
    - Implement `_lookup_sound_bank()` — map material category to WAV file in `assets/sound_bank/`
    - Implement `_normalize_audio()` — normalize peak amplitude to -3dBFS
    - Enforce output constraints: mono, 44100Hz, 16-bit, duration 0.1-2.0s
    - If both methods fail: assign default generic impact sound, log warning
    - Return `AudioResult` with wav_path, method_used, duration, material_category
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.2 Create sound bank assets (`assets/sound_bank/`)
    - Create placeholder WAV files for each material: `wood_impact.wav`, `metal_impact.wav`, `glass_impact.wav`, `fabric_impact.wav`, `ceramic_impact.wav`, `plastic_impact.wav`, `default_impact.wav`
    - All files: mono, 44100Hz, 16-bit, 0.1-2.0s duration, normalized to -3dBFS peak
    - _Requirements: 5.3_

  - [x] 6.3 Write property test for audio format constraints (Property 8)
    - **Property 8: Audio Output Format Constraints**
    - For any generated audio, output is mono, 44100Hz, 16-bit, duration in [0.1, 2.0] seconds
    - **Validates: Requirements 5.1**


  - [x] 6.4 Write property test for audio normalization (Property 9)
    - **Property 9: Audio Normalization to Target Peak**
    - For any WAV with at least one non-zero sample, after normalization peak amplitude is within 0.1dB of -3.0dBFS
    - **Validates: Requirements 5.5**

  - [x] 6.5 Write property test for material-to-sound mapping (Property 10)
    - **Property 10: Material-to-Sound Mapping Completeness**
    - For any valid material category in {wood, metal, glass, fabric, ceramic, plastic}, sound bank lookup returns a non-null path to an existing WAV file
    - **Validates: Requirements 5.3**

- [x] 7. Light Estimation, Scale Calibration, and Layout
  - [x] 7.1 Implement Light Estimator (`src/photo_pipeline/stages/light_estimator.py`)
    - Implement `LightEstimator.estimate()` — CPU-based heuristic from source image
    - Analyze shadow directions to estimate primary light direction vector (normalized)
    - Estimate color temperature from image white balance (1800K-12000K)
    - Estimate intensity (0.0-100.0) and ambient parameters
    - Implement `_default_light()` fallback: direction [0, -1, 0], 5500K, intensity 1.0
    - Fallback triggers on: zero intensity, zero-vector direction, or estimation failure
    - Return `LightEstimateResult` with all parameters and confidence score
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 7.2 Write property test for light estimation bounds (Property 11)
    - **Property 11: Light Estimation Output Validity**
    - For any valid RGB image, output has: sun_direction magnitude in [0.99, 1.01], color_temperature in [1800, 12000], intensity in [0.0, 100.0], and produces at minimum one directional + one ambient light
    - **Validates: Requirements 6.1, 6.2, 6.4**

  - [x] 7.3 Implement Scale Calibrator (`src/photo_pipeline/stages/scale_calibrator.py`)
    - Implement `ScaleCalibrator.calibrate()` — compute real-world dimensions from pixel footprint, depth, and FOV
    - Implement `_pixel_to_meters()` — single axis conversion using depth and focal length
    - Implement `_clamp_dimensions()` — clamp each axis to [0.01m, room_dimension_on_that_axis]
    - Record scale_factor and confidence (0.0-1.0); flag confidence < 0.3 in manifest
    - _Requirements: 7.1, 7.2, 7.7_

  - [x] 7.4 Write property test for scale calibration clamping (Property 12)
    - **Property 12: Scale Calibration Produces Clamped Metric Dimensions**
    - For any pixel footprint > 0, positive depth, valid FOV (0°-180°), and room dimensions, output dims are clamped to [0.01, room_dim] per axis
    - **Validates: Requirements 7.1, 7.2**

  - [x] 7.5 Implement Layout Estimator (`src/photo_pipeline/stages/layout_estimator.py`)
    - Implement `LayoutEstimator.estimate()` — back-project 2D centroids to 3D positions using depth + camera model
    - Implement `_back_project()` using camera intrinsics formula: x = (u-cx)*d/fx, y = -(v-cy)*d/fy, z = -d
    - Implement `_physics_settle()` using PyBullet: create convex hull shapes, simulate gravity for up to 500 iterations or 5s wall time
    - Detect and resolve interpenetration (max 0.5m displacement per iteration)
    - Flag unsettled objects (velocity > 0.01 m/s or penetration > 0.01m after limit)
    - Return list of `LayoutResult` with final position, rotation, settle status, pre-settle position
    - _Requirements: 7.3, 7.4, 7.5, 7.6_


  - [x] 7.6 Write property test for back-projection camera model inverse (Property 13)
    - **Property 13: Back-Projection Satisfies Camera Model Inverse**
    - For any pixel (u,v) within bounds, positive depth d, and valid camera params, back-projecting then re-projecting yields original pixel within ±0.5px tolerance
    - **Validates: Requirements 7.3**

  - [x] 7.7 Write property test for physics settle convergence (Property 14)
    - **Property 14: Physics Settle Convergence**
    - For any set of objects with overlapping bounding boxes, after settle the total interpenetration volume is ≤ initial (monotone non-increasing)
    - **Validates: Requirements 7.4, 10.2**

- [x] 8. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Collision Generation and LOD
  - [x] 9.1 Implement Collision and LOD Generator (`src/photo_pipeline/stages/collision_lod.py`)
    - Implement `CollisionLODGenerator.generate_collision()`:
      - For meshes with > 100 faces: run V-HACD decomposition (max 16 hulls, 10000 voxel resolution, 30s timeout)
      - For meshes with ≤ 100 faces: use direct convex hull
      - On V-HACD timeout: fallback to bounding-box collision shape, log warning
    - Implement `CollisionLODGenerator.generate_lod()`:
      - Produce 4 LOD levels via trimesh decimation: LOD0 (100%), LOD1 (50%), LOD2 (25%), LOD3 (10%)
      - Clamp minimum to 4 faces per level (never produce degenerate geometry)
    - Save collision GLB and LOD GLBs alongside source mesh in session directory
    - Return `CollisionResult` and `LODResult` with paths and metadata
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 9.2 Write property test for collision method selection (Property 17)
    - **Property 17: Collision Method Selection by Face Count**
    - For any mesh with face_count > 100 → V-HACD (max 16 hulls); face_count ≤ 100 → convex hull
    - **Validates: Requirements 9.1, 9.2**

  - [x] 9.3 Write property test for LOD generation invariants (Property 18)
    - **Property 18: LOD Generation Invariants**
    - For any input mesh, LOD produces exactly 4 levels; LOD0 = original face count; each level ≤ previous; no level < 4 faces
    - **Validates: Requirements 9.3, 9.4**

- [x] 10. WorldContract Assembly and Physics Settle Integration
  - [x] 10.1 Implement WorldContract Assembler (`src/photo_pipeline/stages/assembler.py`)
    - Implement `PhotoWorldContractAssembler.assemble()` — map all stage outputs to existing WorldContract schema
    - `_build_room_shell()`: map Room_Mesh to RoomShell entry with dimensions and material from Room_Plate texture
    - `_build_instance()`: map each Object_Mesh to WorldInstance (stable ID from mask_id, transform from layout, dimensions from scale, geometry_strategy="asset")
    - `_build_physics_intent()`: assign STATIC for objects > 50kg or architectural, DYNAMIC for lighter objects with mass = volume × material density
    - `_build_lights()`: map LightEstimateResult to WorldLight entries (directional + ambient)
    - `_build_camera()`: derive CameraBinding from source image estimated parameters
    - `_estimate_mass_kg()`: use material density heuristics (wood=600, metal=7800, glass=2500, fabric=200, ceramic=2300, plastic=950 kg/m³)
    - Set ExportPolicy targets to include "upbge_runtime"
    - Validate assembled WorldContract passes all Pydantic validators; report specific field/constraint failure if invalid
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_


  - [x] 10.2 Write property test for WorldContract assembly validity (Property 15)
    - **Property 15: WorldContract Assembly Validity**
    - For any valid combination of stage outputs (room mesh + zero or more object meshes + light params + camera), assembled WorldContract passes all Pydantic validators (coordinate system, ID uniqueness, dangling references)
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [x] 10.3 Write property test for physics mode assignment (Property 16)
    - **Property 16: Physics Mode Assignment from Material and Volume**
    - For any object with mass > 50kg → STATIC; mass ≤ 50kg and not architectural → DYNAMIC with mass = volume × density (±tolerance)
    - **Validates: Requirements 8.4**

  - [x] 10.4 Write property test for quality classification (Property 19)
    - **Property 19: Quality Classification Determinism**
    - "full" if all objects used primary method; "degraded" if ≥1 fallback but ≥1 mesh exists; "minimal" if zero object meshes
    - **Validates: Requirements 12.6**

- [x] 11. Serialization Round-Trip Integrity
  - [x] 11.1 Implement pipeline manifest JSON serialization
    - Serialize `PipelineManifest` to JSON with canonical format (sorted keys, no whitespace, UTF-8)
    - Implement custom serializers for Path objects and enums
    - Ensure round-trip: serialize → deserialize produces structurally equal manifest
    - _Requirements: 13.1, 13.4_

  - [x] 11.2 Write property test for manifest JSON round-trip (Property 20)
    - **Property 20: Pipeline Manifest JSON Round-Trip**
    - For any valid PipelineManifest, serialize → deserialize produces structurally equal instance
    - **Validates: Requirements 13.1, 13.4**

  - [x] 11.3 Write property test for GLB mesh data round-trip (Property 21)
    - **Property 21: GLB Mesh Data Round-Trip**
    - For any valid mesh (float32 vertices, unit normals, UV in [0,1]), write GLB → read GLB produces data within 1e-6 absolute tolerance
    - **Validates: Requirements 13.2**

  - [x] 11.4 Write property test for depth map NumPy round-trip (Property 22)
    - **Property 22: Depth Map NumPy Round-Trip**
    - For any float32 2D array, np.save → np.load produces bit-identical array
    - **Validates: Requirements 13.3**

  - [x] 11.5 Write property test for WorldContract canonical serialization (Property 23)
    - **Property 23: WorldContract Canonical Serialization Round-Trip**
    - For any WorldContract from photo assembler, canonical_bytes() → deserialize → canonical_bytes() produces identical bytes
    - **Validates: Requirements 13.5**

- [x] 12. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 13. Pipeline Orchestrator and Session Integration
  - [x] 13.1 Implement Pipeline Orchestrator (`src/photo_pipeline/orchestrator.py`)
    - Implement `PhotoPipelineOrchestrator.run()` — top-level coordinator
    - Implement `_validate_input()` — call input validator, reject before inference
    - Implement `_check_comfyui_health()` — fail immediately if ComfyUI unreachable
    - Execute stages in dependency order: Scene Parsing → Depth Estimation → [Object Gen parallel per object] → [Audio parallel per object] → Light Estimation → Scale Calibration → Layout Estimation → Physics Settle → WorldContract Assembly
    - Implement parallel execution: GPU stages sequential (SAM → MoGe-2 → Hunyuan3D → audio), CPU stages parallel where dependencies allow
    - Configurable concurrency: default 2 GPU tasks, 4 CPU tasks
    - Enforce total pipeline timeout (default 20 min) — terminate all in-progress tasks on timeout
    - Emit SSE progress events at each stage transition (within 2s of occurrence)
    - Persist all intermediate artifacts in session output directory with consistent naming
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 11.2, 11.3, 11.4, 11.5, 11.7_

  - [x] 13.2 Implement session integration for photo pipeline
    - Create session via existing `SessionManager.create_session()` with `source_type="photo"`
    - Store `PhotoSessionMetadata` alongside session (source_image_hash, resolution, quality classification)
    - Integrate with existing FIFO compilation queue — photo pipeline enters queue at WorldContract → UPBGE compilation stage
    - Distinguish photo sessions from text sessions via `source_type` field in session metadata
    - _Requirements: 11.1, 11.7, 14.5_

  - [x] 13.3 Implement graceful degradation logic in orchestrator
    - Object_Generator failure for single object → substitute placeholder, continue remaining objects
    - Audio_Synthesizer failure for single object → assign silent placeholder, continue
    - Depth low-confidence (>30% invalid pixels) → attempt reconstruction with valid pixels + interpolation, fallback to flat-floor only if impossible
    - Pipeline succeeds as long as: Room_Mesh generated (even heuristic) AND WorldContract passes validation
    - Zero object meshes acceptable (player explores empty room)
    - Record degradation path per object in manifest (fallbacks_triggered list)
    - Classify final output: "full", "degraded", or "minimal"
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 13.4 Wire photo pipeline to existing UPBGE compilation chain
    - After WorldContract assembly: pass to existing `upbge_compile.py` sidecar (includes V-HACD, LOD at compile time)
    - Pass through existing parity gate → smoke validation → auto-launch via `auto_launch.py`
    - No modifications to existing compilation infrastructure
    - _Requirements: 1.2, 14.2, 14.3_


- [x] 14. Physics Settle Pre-Player Validation
  - [x] 14.1 Implement Physics Settle stage (`src/photo_pipeline/stages/physics_settle.py`)
    - Dedicated pre-player simulation pass using PyBullet
    - Create simplified convex hull collision shapes per dynamic object
    - Simulate gravity for up to 500 iterations, wall-time limit 10s for ≤30 objects
    - Detect interpenetration via PyBullet contact points, apply separation impulses (max 0.5m displacement per iteration)
    - After settle: update WorldContract instance transforms with settled positions
    - Preserve original (pre-settle) positions in pipeline manifest for debugging
    - Flag unsettled objects (velocity > 0.01 m/s or penetration > 0.01m) in manifest
    - If >50% dynamic objects unsettled: log warning but do NOT reject WorldContract
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 15. Existing Pipeline Preservation and Mode Routing
  - [x] 15.1 Add photo mode to pipeline interface
    - Add "photo" input mode alongside existing "text" mode
    - Route to `PhotoPipelineOrchestrator.run()` when source_type="photo"
    - Existing text pipeline behavior (all V3-V11 interfaces, MVP mode, full mode) unchanged
    - WorldContract schema remains unchanged — photo pipeline maps into existing schema
    - Existing UPBGE compilation, parity gates, smoke validation, auto-launch reused without modification
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

- [x] 16. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Integration wiring and final verification
  - [x] 17.1 Wire complete photo pipeline end-to-end
    - Connect: input validator → scene parser → depth estimator → room reconstructor → object generator → audio synthesizer → light estimator → scale calibrator → layout estimator → physics settle → assembler → UPBGE compile → parity → smoke → auto-launch
    - Verify each stage feeds into the next with correct data flow
    - Verify session artifacts are persisted at each stage with correct naming convention
    - Verify SSE events fire at each transition
    - _Requirements: 1.1, 1.2, 1.3, 11.2_

  - [x] 17.2 Write integration test for full photo pipeline with mocked ComfyUI
    - Test end-to-end: source photo → scene parse (mocked) → depth (mocked) → objects (mocked) → audio (mocked) → assembly → WorldContract validation
    - Use deterministic test fixtures (sample masks, depth map, meshes)
    - Verify WorldContract output passes existing schema validators
    - Verify manifest records all stages and degradation paths
    - _Requirements: 1.1, 1.2, 8.1_

  - [x] 17.3 Write integration test for photo + text pipeline coexistence
    - Verify text pipeline session and photo pipeline session can run in same FIFO queue
    - Verify session isolation (different source_types, separate output directories)
    - Verify text pipeline behavior unchanged after photo pipeline addition
    - _Requirements: 14.4, 14.5_

  - [x] 17.4 Write integration test for degradation paths
    - Test: all object generators fail → placeholder geometry → "degraded" classification
    - Test: zero objects segmented → room-only → "minimal" classification
    - Test: depth estimation fails → flat-floor heuristic → pipeline still completes
    - Verify WorldContract valid in all degradation scenarios
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6_

- [x] 18. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.


## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (23 properties)
- Unit tests validate specific examples and edge cases
- The project uses Python 3.10+ with FastAPI, Pydantic, Hypothesis, trimesh, numpy, and PyBullet
- Existing `.hypothesis/` directory confirms PBT infrastructure is already in place (236 example databases)
- ComfyUI on localhost:8188 is the GPU inference server — workflow JSON templates parameterize all GPU stages
- The photo pipeline converges at WorldContract — no modifications to existing UPBGE compiler, parity, smoke, or auto-launch
- GPU stages execute sequentially (SAM → MoGe-2 → Hunyuan3D → audio) to manage VRAM; CPU stages (light, scale, layout) run in parallel
- Performance target: 5-8 minutes for 10 objects on RTX 4090, 15 minute hard cap
- Existing infrastructure reused without modification: session_manager.py, auto_launch.py, smoke_validator.py, upbge_compile.py, world_contract.py

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.5", "2.1", "6.2"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "6.1", "7.1"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5", "7.2", "7.3"] },
    { "id": 7, "tasks": ["7.4", "7.5"] },
    { "id": 8, "tasks": ["7.6", "7.7", "9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 10, "tasks": ["10.2", "10.3", "10.4", "11.1"] },
    { "id": 11, "tasks": ["11.2", "11.3", "11.4", "11.5", "14.1"] },
    { "id": 12, "tasks": ["13.1", "13.2"] },
    { "id": 13, "tasks": ["13.3", "13.4", "15.1"] },
    { "id": 14, "tasks": ["17.1"] },
    { "id": 15, "tasks": ["17.2", "17.3", "17.4"] }
  ]
}
```
