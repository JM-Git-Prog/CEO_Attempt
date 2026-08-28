# Tasks — Geometry-Injected Capture Planning

> **Architecture correction (2026-08-28):** This task list replaces the SfM-based approach from commit `f27e2ff`. Adversarial review demonstrated that extracting geometry from AI-generated video is mathematically invalid. The corrected architecture injects MetricPlan geometry into generation via ControlNet, then validates and back-projects with known poses.

---

## Task 1: Conditioning Fidelity Spike — Does ControlNet Depth Hold?

**Requirements:** 8.1, 8.2, 8.3, 8.4, 8.5, 8.6

**Description:** Before building the full pipeline, measure whether ControlNet depth conditioning actually constrains FLUX output geometry. This answers the foundational question: when we inject a depth map, does the generated image follow it?

### Subtasks

- [ ] 1.1. Create `tools/conditioning_spike/__init__.py`
- [ ] 1.2. Create `tools/conditioning_spike/conditioning_tester.py`:
  - `test_conditioning_fidelity(depth_map_path: Path, prompt: str, strength: float, comfyui_url: str) -> FidelityResult`
  - Workflow: upload depth map → ControlNet depth conditioning → FLUX generation → DA3 on output → compare DA3 depth vs input depth
  - `FidelityResult` dataclass: conditioning_strength, pearson_r, mae_m, ssim, scale_factor, conditioning_held (bool)
  - Use existing `blockout_renderer.py` depth render as the conditioning input
  - Use existing `depth_bridge.py` DA3 estimator for output comparison
- [ ] 1.3. Create `tools/conditioning_spike/strength_sweep.py`:
  - `sweep_strengths(depth_map_path: Path, prompt: str, strengths: list[float]) -> list[FidelityResult]`
  - Test strengths: [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  - Report: which strength gives best geometry fidelity without destroying visual quality
  - Detect conditioning collapse (correlation < 0.3) vs conditioning bleed (correlation > 0.8 but textures flat/grey)
- [ ] 1.4. Create `tools/conditioning_spike/run.py`:
  - CLI: `python -m tools.conditioning_spike.run --depth <path> --prompt <text> [--strengths 0.5,0.7,0.9]`
  - If no depth map provided, generate one from a default Danny's kitchenette MetricPlan
  - Output: JSON results + comparison PNG (conditioning depth | generated image | DA3 depth | error map)
- [ ] 1.5. Verify ControlNet depth node availability in ComfyUI:
  - Check for `ControlNetLoader` + `ControlNetApply` nodes
  - Check for depth ControlNet model (e.g., `control_v11f1p_sd15_depth` or FLUX-compatible depth ControlNet)
  - Document which model files are needed and where to place them
- [ ] 1.6. Run the spike on Danny's kitchenette (existing blockout depth + standard prompt):
  - Record: does correlation exceed 0.7? What's the optimal strength?
  - If ControlNet depth nodes are missing: document what's needed, provide install instructions, skip to Task 3 with img2img fallback

### Done Criteria
- Measured ControlNet depth fidelity at multiple strengths
- Know whether correlation ≥ 0.7 is achievable (the validation gate threshold)
- Know the recommended default conditioning strength
- Know which ControlNet models are available/needed in the local ComfyUI install
- Results documented in spike output JSON

---

## Task 2: CapturePlanner — Deterministic Camera Trajectory from MetricPlan

**Requirements:** 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7

**Description:** Create the production CapturePlanner that computes a deterministic camera trajectory from MetricPlan room geometry. Each camera has exact known intrinsics and extrinsics — no estimation anywhere.

### Subtasks

- [ ] 2.1. Create `src/unified_pipeline/capture_planner.py`:
  - `PlannedCamera` frozen dataclass: position, target, extrinsic (4×4), intrinsic (3×3), camera_type, label, hash
  - `CaptureManifest` dataclass: cameras list, room_dimensions, plan_revision_hash, total_surface_coverage
  - `CapturePlanner` class:
    - `__init__(self, metric_plan: MetricPlan, camera_contract: CameraContract)`
    - `plan(self) -> CaptureManifest`
    - `_plan_hero(self) -> PlannedCamera` — from CameraContract, exact K/R/t
    - `_plan_coverage(self) -> list[PlannedCamera]` — one per wall not visible from hero
    - `_plan_transitions(self, cameras: list[PlannedCamera]) -> list[PlannedCamera]` — interpolated between coverage views for video continuity
    - `_compute_extrinsic(position, target, up) -> np.ndarray` — look-at → 4×4 world-to-camera
    - `_compute_intrinsic() -> np.ndarray` — from CameraContract (60° vFOV, 1024×768)
    - `_validate_inside_room(pos, room_dims, clearance=0.3) -> tuple` — clamp to room
  - Deterministic: no random component, same inputs → same output
  - Fallback: if called without MetricPlan, produce 5 cardinal cameras (backward compat)
- [ ] 2.2. Create `tests/test_capture_planner.py`:
  - `test_hero_matches_contract` — hero position/target/intrinsics match CameraContract
  - `test_extrinsic_is_valid_rotation` — R is orthonormal, det(R)=1
  - `test_intrinsic_matches_vfov` — fy ≈ 665.1 for 60° vFOV at 768 height
  - `test_cameras_inside_room` — all positions ≥0.3m from walls (4×4×2.7m room)
  - `test_cameras_inside_small_room` — all positions ≥0.3m from walls (2×2×2.4m room)
  - `test_coverage_all_walls` — every wall has ≥1 camera looking at it (dot product with wall normal > 0.5)
  - `test_deterministic` — run twice, compare: identical manifests
  - `test_manifest_hashes_unique` — each camera has a distinct hash
  - `test_fallback_no_plan` — backward compat with existing 5-cardinal behavior
- [ ] 2.3. Integration with `multi_view_generator.py`:
  - Add `capture_manifest: CaptureManifest | None = None` parameter to `generate_multi_views`
  - If manifest provided, use its cameras instead of `_compute_cardinal_cameras`
  - Preserve `_compute_cardinal_cameras` as fallback (not deleted)

### Done Criteria
- CapturePlanner produces deterministic manifest with exact K, R, t per camera
- All cameras inside room, all walls covered
- Extrinsics are valid (orthonormal rotation, proper homogeneous form)
- Backward compatible with existing multi-view generation
- All unit tests pass

---

## Task 3: Depth Sequence Renderer — MetricPlan Geometry to Depth Maps

**Requirements:** 1.1, 1.2, 1.3, 1.4, 1.5, 1.6

**Description:** Render float32 depth maps from MetricPlan geometry at each camera position in the CaptureManifest. Reuses existing `blockout_renderer.py` projection infrastructure.

### Subtasks

- [ ] 3.1. Create `src/unified_pipeline/depth_sequence_renderer.py`:
  - `DepthSequenceRenderer` class:
    - `__init__(self, metric_plan: MetricPlan)`
    - `render_all(self, manifest: CaptureManifest) -> list[DepthRender]`
    - `render_one(self, camera: PlannedCamera) -> DepthRender`
  - `DepthRender` dataclass: depth_map (float32 ndarray HxW), normal_map (float32 HxWx3), camera_hash, plan_revision, path (if saved)
  - Reuse `blockout_renderer.py`'s `_build_projector` closure for the actual projection math
  - Project all MetricPlan geometry: walls (4 sides), floor, ceiling, openings (as depth discontinuities/voids), object bounding boxes
  - Depth in meters, inf where no geometry hit (sky/void)
  - Normal maps: per-pixel surface normal in world space
  - Resolution: match camera's target resolution (1024×768 from CameraContract)
- [ ] 3.2. Create `tests/test_depth_sequence_renderer.py`:
  - `test_render_shape` — output is float32, shape (768, 1024)
  - `test_depth_range_indoor` — all valid values between 0.1m and 15m
  - `test_walls_at_correct_distance` — center pixel depth ≈ room_depth/2 for forward-looking camera
  - `test_floor_depth` — floor pixels have depth consistent with camera height and angle
  - `test_normal_map_unit_vectors` — all normals have magnitude ≈ 1.0
  - `test_provenance_binding` — camera_hash and plan_revision populated
  - `test_render_all_count` — produces one DepthRender per manifest camera
- [ ] 3.3. Save rendered depth maps as float32 .npy files beside session artifacts (matching DA3 output format)
- [ ] 3.4. Optionally render colormapped PNG visualization of each depth map for debugging

### Done Criteria
- Renders depth maps at 1024×768 from any camera in the manifest
- Uses existing blockout projection infrastructure
- Depth values are metric (meters), range plausible for indoor scenes
- Normal maps produced alongside depth
- Provenance (camera hash, plan revision) bound to each render
- All unit tests pass

---

## Task 4: ControlNet Depth-Conditioned Generation

**Requirements:** 3.1, 3.2, 3.3, 3.4, 3.5, 3.6

**Description:** Wire the rendered MetricPlan depth maps into ComfyUI as ControlNet depth conditioning for FLUX image generation. This forces generated images to follow MetricPlan geometry.

### Subtasks

- [ ] 4.1. Create `src/unified_pipeline/controlnet_conditioner.py`:
  - `ControlNetConditioner` class:
    - `__init__(self, comfyui_url: str = "http://localhost:8188", default_strength: float = 0.8)`
    - `async def generate_conditioned(self, depth_render: DepthRender, prompt: str, *, strength: float | None = None, seed: int = -1) -> Path`
    - `async def check_availability(self) -> bool` — verifies ControlNet nodes + depth model exist
    - `_build_conditioned_workflow(depth_filename, prompt, strength, seed) -> dict` — ComfyUI workflow JSON
  - Workflow structure:
    - `LoadImage` (depth map as conditioning)
    - `ControlNetLoader` (depth model)
    - `ControlNetApply` (strength parameter)
    - Standard FLUX pipeline (UNETLoader → CLIPTextEncode → KSampler → VAEDecode → SaveImage)
  - Conditioning strength from Task 1 spike results (default 0.8, adjustable)
  - Depth map preprocessing: normalize to 0–1 range for ControlNet input (ControlNet expects disparity-like images)
- [ ] 4.2. Handle ControlNet unavailability gracefully:
  - If `check_availability()` returns False: log warning, fall back to existing img2img with blockout conditioning (current Canon generator behavior)
  - Never crash the pipeline due to missing ControlNet
- [ ] 4.3. Modify `multi_view_generator.py`:
  - If CaptureManifest + DepthRenders available: use ControlNetConditioner for each view
  - If not available: use existing text-to-image generation (unchanged)
  - Wire depth renders from Task 3 into the generation loop
- [ ] 4.4. Create `tests/test_controlnet_conditioner.py`:
  - `test_workflow_structure` — built workflow has ControlNet nodes in correct order
  - `test_depth_normalization` — float32 meters → 0–1 range for ControlNet
  - `test_fallback_on_unavailable` — missing nodes → graceful degradation, no crash
  - `test_strength_parameter` — strength correctly wired into ControlNetApply
- [ ] 4.5. Identify and document which ControlNet depth model works with FLUX:
  - FLUX-compatible ControlNet depth (e.g., `flux-depth-controlnet-v3` or similar)
  - If none available: document the gap and use strength=0 (effectively unconditioned) until model is obtained

### Done Criteria
- ComfyUI workflow with ControlNet depth conditioning builds correctly
- Generated images respect depth conditioning (verified by Task 1 spike measurements)
- Graceful fallback when ControlNet unavailable
- Conditioning strength configurable
- Depth map properly normalized for ControlNet input
- All unit tests pass

---

## Task 5: Geometry Validation Gate

**Requirements:** 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7

**Description:** Build the automated validation gate that compares generated image depth (DA3) against the injected conditioning depth, catching cases where ControlNet conditioning failed to hold.

### Subtasks

- [ ] 5.1. Create `src/unified_pipeline/geometry_validation_gate.py`:
  - `ValidationResult` frozen dataclass: passed, pearson_r, scale_aligned_mae_m, depth_ssim, scale_factor, coverage_fraction, failure_reason
  - `ValidationConfig` dataclass: min_correlation (0.7), max_mae_m (0.5), min_ssim (0.6), max_retries (3), strength_increment (0.1), max_strength (1.0)
  - `GeometryValidationGate` class:
    - `__init__(self, config: ValidationConfig = ValidationConfig(), depth_estimator: UnifiedDepthEstimator = None)`
    - `async def validate(self, generated_view: Path, conditioning_depth: np.ndarray, session_id: str) -> ValidationResult`
    - `_compute_scale_factor(estimated, reference) -> float` — least-squares optimal scale
    - `_compute_metrics(aligned_estimated, reference) -> tuple[float, float, float]` — correlation, MAE, SSIM
  - Validation logic:
    1. Run DA3 on generated view → estimated_depth
    2. Compute optimal scale factor (SfM-style scale alignment)
    3. Apply scale: aligned = scale * estimated
    4. Compute metrics: pearson_r, MAE, SSIM
    5. PASS if all thresholds met, FAIL otherwise
- [ ] 5.2. Create retry logic in the generation loop:
  - On FAIL: increment conditioning strength by 0.1, re-generate
  - After max_retries failures: accept with warning (use existing unconditioned generation path)
  - Log all attempts with metrics for debugging
- [ ] 5.3. Create `tests/test_geometry_validation_gate.py`:
  - `test_perfect_match_passes` — identical depths → passed=True, correlation≈1.0, MAE≈0
  - `test_scaled_match_passes` — depth × 2.0 → passes after scale alignment
  - `test_uncorrelated_fails` — random depth → passed=False, correlation≈0
  - `test_high_mae_fails` — shifted depth (MAE > 0.5m) → fails
  - `test_retry_increments_strength` — mock failing generation → strength increases each retry
  - `test_max_retries_fallback` — after 3 failures → falls back gracefully
  - `test_coverage_fraction` — sparse DA3 (50% valid) → coverage correctly reported
- [ ] 5.4. Wire into multi-view generation loop: validate each generated view before proceeding to next

### Done Criteria
- Validation gate compares DA3 depth against conditioning depth with configurable thresholds
- Scale alignment handles DA3's affine ambiguity
- Retry logic with progressive strength increase
- Graceful fallback after max retries
- Metrics recorded for quality tracking
- All unit tests pass

---

## Task 6: Dense Back-Projection and Volumetric Reconstruction

**Requirements:** 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7

**Description:** Back-project validated DA3 depth maps into 3D using exact known camera matrices from the CaptureManifest, fuse multi-view point clouds, and reconstruct a mesh to replace the parametric room shell.

### Subtasks

- [ ] 6.1. Create `src/unified_pipeline/depth_backprojector.py`:
  - `DepthBackprojector` class:
    - `backproject(depth_map, intrinsic, extrinsic, rgb_image=None, min_depth=0.1, max_depth=15.0) -> tuple[np.ndarray, np.ndarray | None]` — returns (Nx3 points, Nx3 colors)
    - `fuse(clouds, colors, merge_radius_m=0.02) -> tuple[np.ndarray, np.ndarray | None]` — merge overlapping points
    - `export_ply(points, colors, output_path) -> Path` — save for inspection
  - Back-projection math:
    ```
    K_inv = np.linalg.inv(K)
    R = extrinsic[:3, :3]
    t = extrinsic[:3, 3]
    for each valid pixel (u, v) with depth d:
        ray_camera = K_inv @ [u, v, 1]^T
        P_camera = ray_camera * d
        P_world = R.T @ (P_camera - t)
    ```
  - Vectorized numpy implementation (no per-pixel loop)
  - Filter: reject depth < min or > max, reject NaN/inf
- [ ] 6.2. Create `src/unified_pipeline/volumetric_reconstructor.py`:
  - `VolumetricReconstructor` class:
    - `reconstruct(points, colors=None, method="poisson") -> trimesh.Trimesh`
    - `_poisson_reconstruct(points, normals) -> trimesh.Trimesh` — via trimesh or Open3D
    - `_tsdf_reconstruct(depth_maps, cameras) -> trimesh.Trimesh` — via Open3D (if available)
    - `_postprocess(mesh) -> trimesh.Trimesh` — remove bridge triangles, orient normals inward, decimate to 10K–250K verts
    - `export_glb(mesh, output_path) -> Path`
  - Normal estimation: from point cloud neighborhood (PCA) or from DA3 normal maps
  - Bridge triangle removal: faces spanning > 0.5m depth gradient between vertices
  - Inward normal orientation: flip normals pointing away from room center
  - Decimation: target vertex count based on room surface area (≈50 verts/m²)
- [ ] 6.3. Create `tests/test_depth_backprojector.py`:
  - `test_backproject_flat_wall` — depth=3.0m everywhere, forward camera → all points at z=3.0
  - `test_backproject_known_geometry` — synthetic depth of a box room → points match box corners
  - `test_filter_invalid` — NaN, inf, <0.1m, >15m all rejected
  - `test_fuse_deduplicates` — overlapping clouds merge within 2cm radius
  - `test_export_ply_valid` — PLY file written, non-empty, has correct point count
  - `test_vectorized_performance` — 1024×768 back-projection completes in <1 second
- [ ] 6.4. Create `tests/test_volumetric_reconstructor.py`:
  - `test_poisson_produces_mesh` — point cloud of a box → mesh with >100 faces
  - `test_normals_inward` — reconstructed room mesh normals point toward center
  - `test_bridge_triangle_removal` — faces spanning depth discontinuity removed
  - `test_decimation_bounds` — output between 10K and 250K vertices
  - `test_export_glb_valid` — GLB file written, loadable by trimesh
  - `test_fallback_on_failure` — degenerate input → returns None (caller uses parametric shell)
- [ ] 6.5. Wire into `v2_mesh_builder.py`:
  - Replace `_generate_room_shell` parametric boxes with volumetric reconstruction output
  - Only when: validation passed + sufficient coverage (≥3 views with valid back-projection)
  - Fallback: existing parametric shell if reconstruction unavailable or fails

### Done Criteria
- Back-projection produces 3D points from DA3 depth + known cameras
- Vectorized implementation (<1s for 1024×768)
- Multi-view fusion merges overlapping points
- Mesh reconstruction produces watertight, inward-facing geometry
- Bridge triangles removed
- Decimated to target vertex count
- Replaces parametric room shell when available
- Falls back gracefully on failure
- All unit tests pass

---

## Task 7: End-to-End Integration Test

**Requirements:** 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7

**Description:** Wire everything together and verify the complete inject-then-validate flow works end-to-end without breaking existing functionality or the authority model.

### Subtasks

- [ ] 7.1. Create `tests/e2e/test_inject_validate_pipeline.py`:
  - **Fast path (no GPU, <3s):**
    - Construct Danny's kitchenette Brief + MetricPlan (deterministic)
    - Run CapturePlanner → CaptureManifest
    - Assert: all cameras inside room, exact K/R/t, walls covered
    - Run DepthSequenceRenderer → depth maps
    - Assert: float32, correct shape, plausible depth range
    - Mock ControlNet generation (return Canon image)
    - Mock DA3 (return conditioning depth × 1.05 scale factor)
    - Run ValidationGate → assert PASS (within thresholds)
    - Run BackProjector on mock depth + known cameras → point cloud
    - Assert: point cloud bounding box matches room dimensions (±20%)
    - Assert: all transforms came from manifest (no estimation)
  - **Authority preservation tests:**
    - Assert MetricPlan not mutated after full pipeline run
    - Assert CameraContract hash unchanged
    - Assert DA3's `FORBIDDEN_DEPTH_AUTHORITIES` deny-list unchanged
    - Assert back-projection authority comes from known cameras (manifest hash bound)
  - **Backward compatibility tests:**
    - multi_view_generator with no CaptureManifest → existing 5 cardinal views
    - v2_mesh_builder with no reconstruction → existing parametric shell
    - No import errors if controlnet_conditioner import fails (try/except path)
- [ ] 7.2. Add `--live-gpu` pytest marker for full integration:
  - Run CapturePlanner → DepthSequenceRenderer → ControlNetConditioner (real FLUX) → ValidationGate (real DA3) → BackProjector → VolumetricReconstructor
  - Assert: room_shell.glb produced with >10K vertices
  - Assert: validation passed with correlation ≥ 0.7
  - Skip with informative message if ComfyUI unavailable
- [ ] 7.3. Verify no existing tests broken:
  - `pytest tests/ -x --ignore=tests/e2e` (unit tests)
  - `pytest tests/e2e/ -x --ignore=tests/e2e/test_inject_validate_pipeline.py` (existing e2e)
  - All must pass unchanged
- [ ] 7.4. Performance validation:
  - CapturePlanner + DepthSequenceRenderer: <2 seconds (CPU only)
  - BackProjector (per view): <1 second
  - Full pipeline (mocked generation): <5 seconds
  - Full pipeline (real GPU): <10 minutes (dominated by FLUX generation)

### Done Criteria
- Fast-path integration test passes in <3 seconds (no GPU)
- Authority model preserved at every stage
- Backward compatibility with existing pipeline paths
- No existing tests broken
- Live-GPU test produces a real room_shell.glb when ComfyUI is available
- Performance targets met
