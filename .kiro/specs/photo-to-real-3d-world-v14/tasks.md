# Implementation Plan: Photo-to-Real-3D-World V14

## Overview

This plan builds the V14 pipeline incrementally: starting with data models and pure logic (testable via property-based tests), then layering in ComfyUI-backed generators, VRAM management, room shell reconstruction, asset cataloging, orchestration, and finally the Three.js web interface. Each task builds on the previous, and property tests run close to implementation to catch errors early.

## Tasks

- [ ] 1. Data models, configuration, and core interfaces
  - [x] 1.1 Create V14 data models and configuration dataclasses
    - Create `src/photo_pipeline/models_v14.py` with all frozen dataclasses: `V14PipelineConfig`, `ObjectMeshResult`, `RoomShellResult`, `V14ObjectEntry`, `V14PipelineManifest`, `MaterialPassResult`, `PhysicsClassification`, `SemanticLabel`, `AssetRegistryEntry`, `VRAMState`
    - Include field validators and type annotations matching the design signatures
    - _Requirements: 1.6, 2.7, 3.1, 6.6, 7.2, 9.1, 15.1, 15.3_

  - [x] 1.2 Write property test for Asset Registry JSON round-trip
    - **Property 16: Asset Registry JSON Round-Trip**
    - **Validates: Requirements 15.1, 15.5**

  - [x] 1.3 Write property test for Pipeline Manifest JSON round-trip
    - **Property 18: Pipeline Manifest JSON Round-Trip**
    - **Validates: Requirements 15.3**

  - [x] 1.4 Write property test for Depth Map NumPy round-trip
    - **Property 19: Depth Map NumPy Round-Trip**
    - **Validates: Requirements 15.4**

- [ ] 2. Physics classification and mesh validation (pure logic)
  - [x] 2.1 Implement PhysicsClassifier
    - Create `src/photo_pipeline/stages/physics_classifier.py` with the `PhysicsClassifier` class
    - Implement `classify()` method with density table lookup, volume × density mass calculation, 25kg threshold, architectural override, and correct friction/restitution values per body_mode
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 2.2 Write property test for physics classification correctness
    - **Property 11: Physics Classification Correctness**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**

  - [x] 2.3 Implement mesh validation utility
    - Create `src/photo_pipeline/stages/mesh_validator.py` with `validate_mesh(mesh_path) -> bool` checking ≥100 faces, ≥50 vertices, and embedded texture data using trimesh
    - _Requirements: 1.2_

  - [x] 2.4 Write property test for mesh validation correctness
    - **Property 1: Mesh Validation Correctness**
    - **Validates: Requirements 1.2**

  - [x] 2.5 Implement placeholder geometry selection
    - Create `src/photo_pipeline/stages/placeholder_generator.py` with `select_placeholder_type(width, height, area)` returning sphere/cylinder/box based on aspect ratio rules, and `generate_placeholder(object_png, dimensions_m) -> Path` producing a colored GLB
    - _Requirements: 1.5_

  - [x] 2.6 Write property test for placeholder geometry selection
    - **Property 2: Placeholder Geometry Selection**
    - **Validates: Requirements 1.5**

- [ ] 3. Camera math and position clamping (pure logic)
  - [x] 3.1 Implement back-projection and position clamping utilities
    - Create `src/photo_pipeline/stages/camera_math.py` with `back_project(u, v, d, fx, fy, cx, cy) -> (x, y, z)` implementing x=(u-cx)*d/fx, y=-(v-cy)*d/fy, z=-d, and `clamp_to_bounds(position, bbox_min, bbox_max, margin=0.05) -> (x, y, z)`
    - _Requirements: 4.1, 4.2, 4.4_

  - [x] 3.2 Write property test for back-projection formula
    - **Property 9: Back-Projection Formula Correctness**
    - **Validates: Requirements 4.1, 4.2**

  - [x] 3.3 Write property test for position clamping
    - **Property 10: Position Clamping to Room Bounds**
    - **Validates: Requirements 4.4**

- [ ] 4. Texture size selection and material utilities (pure logic)
  - [x] 4.1 Implement texture size selection and PBR value utilities
    - Create `src/photo_pipeline/stages/material_utils.py` with `select_texture_size(area_pct) -> (int, int)` implementing the three-tier thresholds (256/512/1024), and `clamp_pbr_values(metallic, roughness) -> (float, float)` ensuring [0.0, 1.0] range
    - _Requirements: 11.4, 5.3_

  - [x] 4.2 Write property test for texture size selection
    - **Property 14: Texture Size Selection**
    - **Validates: Requirements 11.4**

  - [x] 4.3 Write property test for PBR value ranges
    - **Property 13: PBR Value Ranges**
    - **Validates: Requirements 5.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Semantic labeling and heuristic fallback
  - [x] 6.1 Implement SemanticLabeler with Ollama integration and heuristic fallback
    - Create `src/photo_pipeline/stages/semantic_labeler.py` with `SemanticLabeler.label(object_png)` sending structured prompt to Ollama (flash attention enabled), JSON response parsing and validation, 10s timeout, and `fallback_label(width, height, area_px)` producing valid SemanticLabel from heuristics
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 6.2 Write property test for semantic label validation
    - **Property 22: Semantic Label Validation**
    - **Validates: Requirements 13.5**

  - [x] 6.3 Write property test for heuristic labeling fallback
    - **Property 23: Heuristic Labeling Fallback Produces Valid Output**
    - **Validates: Requirements 13.3**

- [ ] 7. VRAM Manager
  - [x] 7.1 Implement VRAMManager state machine
    - Create `src/photo_pipeline/vram_manager.py` with `VRAMManager` class: `acquire_model(model_name, estimated_gb)` enforcing single-model exclusion via `/free` + wait for <4GB, `release_model()`, `check_system_ram()` pause at >80GB/resume at <72GB, flash attention enable flag, and OOM retry logic (call /free, wait 5s, retry once)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 7.2 Write property test for VRAM model exclusion invariant
    - **Property 3: VRAM Model Exclusion Invariant**
    - **Validates: Requirements 2.1, 14.2**

  - [x] 7.3 Write property test for system RAM pause/resume threshold
    - **Property 4: System RAM Pause/Resume Threshold**
    - **Validates: Requirements 2.7**

- [ ] 8. Room shell reconstruction
  - [x] 8.1 Implement RoomShellReconstructor
    - Create `src/photo_pipeline/stages/room_shell_reconstructor.py` with displaced-grid method: create regular grid (max 500 per dimension), displace vertices by depth along camera rays, remove faces where gradient > 0.5m, apply Room_Plate UV texture, orient Y-up with inward-facing normals, export as GLB with embedded texture
    - Include flat-box fallback (4m depth, aspect-ratio width, 2.7m ceiling) for invalid depth maps
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 8.2 Write property test for room shell vertex count bounds
    - **Property 5: Room Shell Vertex Count Bounds**
    - **Validates: Requirements 3.6**

  - [x] 8.3 Write property test for room shell inward-facing normals
    - **Property 6: Room Shell Inward-Facing Normals**
    - **Validates: Requirements 3.8**

  - [x] 8.4 Write property test for depth gradient face removal
    - **Property 7: Depth Gradient Face Removal**
    - **Validates: Requirements 3.7**

  - [x] 8.5 Write property test for depth validity threshold
    - **Property 8: Depth Validity Threshold**
    - **Validates: Requirements 3.5, 14.3**

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Mesh generators (Hunyuan3D 2.1 + Trellis2)
  - [x] 10.1 Implement Hunyuan3DV2Generator
    - Create `src/photo_pipeline/stages/hunyuan3d_v2_generator.py` with ComfyUI workflow submission (ImageOnlyCheckpointLoader → ModelSamplingAuraFlow → CLIPVisionEncode → Hunyuan3Dv2Conditioning → KSampler steps=50, cfg=7.0 → VAEDecodeHunyuan3D octree_resolution=384 → VoxelToMesh → SaveGLB), 180s stall timeout, mesh validation, and generation metadata recording
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 9.3, 9.7_

  - [x] 10.2 Implement Trellis2Generator
    - Create `src/photo_pipeline/stages/trellis2_generator.py` with ComfyUI workflow (Trellis2LoadModel → Trellis2PreProcessImage → Trellis2MeshWithVoxelGenerator steps=18 → Trellis2SimplifyMesh triangles=12000 → Trellis2ExportMesh GLB), validation, and metadata recording
    - _Requirements: 1.4, 1.5_

  - [x] 10.3 Write unit tests for mesh generators with mocked ComfyUI
    - Test workflow parameter passing, validation, timeout/fallback triggers, and metadata recording
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

- [ ] 11. Depth Anything 3 estimator
  - [x] 11.1 Implement DepthAnything3Estimator
    - Create `src/photo_pipeline/stages/depth_anything3.py` with ComfyUI DA3 workflow submission, float32 .npy output, validation (≥50% valid pixels: positive, finite, <20m), fallback to MoGe-2 then flat-floor heuristic, and VRAM-safe loading (after FLUX unload)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 11.2 Write unit tests for depth estimator with validation and fallback logic
    - Test valid pixel ratio computation, fallback chain order, .npy file save/load
    - _Requirements: 14.1, 14.3, 14.5_

- [ ] 12. Two-pass material processor
  - [x] 12.1 Implement MaterialProcessor with Pass 1 and Pass 2 logic
    - Create `src/photo_pipeline/stages/material_processor.py` with `apply_pass1()` (accept native textures for Hunyuan3D/Trellis2 meshes; photo-project for placeholders using camera model; must complete within 2s), `apply_pass2()` (estimate metallic/roughness/normal from Object_PNG; background priority by area descending), texture size selection integration, and GLB update with embedded PBR buffer views
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.1, 11.2, 11.3_

  - [x] 12.2 Write property test for Pass 2 priority ordering
    - **Property 12: Pass 2 Priority Ordering**
    - **Validates: Requirements 5.2**

  - [x] 12.3 Write property test for GLB embedded textures (no external references)
    - **Property 15: GLB Embedded Textures (No External References)**
    - **Validates: Requirements 11.1**

  - [x] 12.4 Write property test for GLB mesh vertex round-trip
    - **Property 17: GLB Mesh Vertex Round-Trip**
    - **Validates: Requirements 11.5, 15.2**

- [ ] 13. Asset Warehouse
  - [x] 13.1 Implement AssetWarehouse
    - Create `src/photo_pipeline/asset_warehouse.py` with five category directories (props/architecture/foliage/hard-surface/set-dressing), `save_asset()` copying GLB + writing JSON registry, `ensure_structure()` for first-run directory creation, filename generation using `{semantic_label_slug}_{session_short}_{mask_id}.glb` pattern, append-only behavior (never overwrite/delete)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.3_

  - [x] 13.2 Write property test for Asset Warehouse append-only invariant
    - **Property 20: Asset Warehouse Append-Only Invariant**
    - **Validates: Requirements 7.4, 10.3**

  - [x] 13.3 Write property test for Asset Warehouse filename uniqueness
    - **Property 21: Asset Warehouse Filename Uniqueness**
    - **Validates: Requirements 7.7**

- [x] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. V14 Pipeline Orchestrator
  - [x] 15.1 Implement V14Orchestrator extending PhotoPipelineOrchestrator
    - Update `src/photo_pipeline/orchestrator.py` (or create `src/photo_pipeline/orchestrator_v14.py`) integrating all new stages in VRAM-safe order: SAM → FLUX inpaint → FLUX unload → DA3 → DA3 unload → Hunyuan3D per object (sequential, max quality) → unload → Pass 1 → layout + physics settle → physics classification → WorldContract assembly
    - Include SSE progress events at each stage transition, per-object completion, elapsed time and "X of N" counters
    - Support up to 15 objects, no hard time cap, 180s stall detection only
    - Record session_id, source_image_hash (SHA-256), quality_classification
    - Implement always-fresh-generation (no Asset Warehouse lookup before generation)
    - Pass 2 starts only after all Pass 1 meshes loaded in V14 interface
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.2, 10.3, 10.4, 12.2_

  - [ ] 15.2 Write integration tests for V14 orchestrator with mocked stages
    - Test VRAM-safe stage ordering, fallback chain execution, SSE event emission, quality classification, session metadata
    - _Requirements: 9.1, 9.2, 9.4, 10.4_

- [ ] 16. V14 Web interface - backend routes
  - [ ] 16.1 Add V14 Flask routes and SSE/WebSocket endpoints
    - Update `src/web/app.py` with: `GET /?v=14` (default when no `?v=` param), `POST /api/session/v14/photo`, `GET /api/session/{id}/mesh/{object_id}`, `GET /api/session/{id}/room_shell`, `SSE /api/session/{id}/v14/events`, `WS /api/session/{id}/v14/materials` for Pass 2 hot-swap notifications
    - Maintain V3-V13 routes unchanged and accessible via `?v=N`
    - Session metadata includes interface_version=14, same FIFO queue and TTL cleanup
    - _Requirements: 8.4, 8.5, 8.6, 8.7, 12.1, 12.3, 12.4, 12.5_

  - [ ] 16.2 Write unit tests for V14 web routes
    - Test URL routing (`?v=14` default, `?v=13` still works), GLB serving, SSE event format, session metadata
    - _Requirements: 8.6, 12.4, 12.5_

- [ ] 17. V14 Web interface - Three.js frontend
  - [ ] 17.1 Create V14 Three.js viewer (`src/web/static/app_v14.js`)
    - Implement `V14WorldViewer` class with: GLTFLoader for room shell and object meshes, PBR metallic-roughness rendering, orbit controls + first-person WASD/mouse-look navigation, progressive loading via SSE (display objects as they arrive), loading progress indicator (stage name, objects X/N, elapsed time, ETA), Pass 2 material hot-swap via WebSocket without page reload
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7_

  - [ ] 17.2 Create V14 HTML template
    - Create `src/web/templates/index_v14.html` with Three.js imports (GLTFLoader, OrbitControls, PointerLockControls), WebGL canvas, progress overlay, navigation mode toggle, and version switching links
    - _Requirements: 8.1, 8.6_

- [ ] 18. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Integration wiring and WorldContract mapping
  - [ ] 19.1 Wire V14 outputs into WorldContract schema
    - Map real mesh GLB → `WorldInstance.geometry_strategy="asset"` + `asset_registry_id`, object position/rotation/scale → transform fields, PBR → MaterialIntent, dynamic/static physics → PhysicsIntent with collision_shape="mesh", room shell → RoomShell reference
    - Ensure existing UPBGE compilation path, parity gates, smoke validation remain compatible with V14 WorldContract output
    - _Requirements: 12.2, 12.3, 4.6_

  - [ ] 19.2 Implement layout estimation updates for V14
    - Update layout estimator to use back-projection with DA3 depth, scale generated meshes from normalized bounding box to `ScaleResult.dimensions_m`, clamp positions within room shell bounds with 0.05m margin, handle invalid depth at centroid by averaging mask region
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ] 19.3 Write integration tests for end-to-end WorldContract production
    - Test with 3-5 mocked objects: correct WorldContract field mapping, physics intent values, asset references, V3-V13 coexistence
    - _Requirements: 12.2, 12.3, 12.5_

- [ ] 20. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design (23 total across 15 sub-tasks)
- Unit tests validate specific examples and edge cases
- The design uses Python — all implementation uses Python for backend, JavaScript for the Three.js frontend
- Hypothesis is already available in this project (`.hypothesis/` directory present)
- Tests go in the `tests/` directory following the organization in the design document
- The pipeline builds incrementally: pure logic first (testable without external services), then ComfyUI-backed stages, then orchestration, then web interface

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1", "2.3", "2.5", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.4", "2.6", "3.2", "3.3", "4.2", "4.3"] },
    { "id": 3, "tasks": ["6.1", "7.1", "8.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "7.2", "7.3", "8.2", "8.3", "8.4", "8.5"] },
    { "id": 5, "tasks": ["10.1", "10.2", "11.1"] },
    { "id": 6, "tasks": ["10.3", "11.2", "12.1", "13.1"] },
    { "id": 7, "tasks": ["12.2", "12.3", "12.4", "13.2", "13.3"] },
    { "id": 8, "tasks": ["15.1"] },
    { "id": 9, "tasks": ["15.2", "16.1"] },
    { "id": 10, "tasks": ["16.2", "17.1", "17.2"] },
    { "id": 11, "tasks": ["19.1", "19.2"] },
    { "id": 12, "tasks": ["19.3"] }
  ]
}
```
