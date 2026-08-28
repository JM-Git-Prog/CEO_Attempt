# Tasks — SfM-Informed Capture Planning

## Task 1: SfM Measurement Spike — Video Frame Extraction and Feature Matching

**Requirements:** 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7

**Description:** Create the foundational measurement tools that extract frames from MiniMax H3 video and quantify feature-matching quality between adjacent frames. This establishes whether AI-generated video carries usable stereo signal.

### Subtasks

- [ ] 1.1. Create `tools/sfm_spike/__init__.py` (empty, marks package)
- [ ] 1.2. Create `tools/sfm_spike/frame_extractor.py`:
  - `extract_frames(video_path: Path, interval: int = 5, max_frames: int = 50) -> list[Path]`
  - Uses `cv2.VideoCapture` to read MP4 and save every Nth frame as PNG
  - Returns list of extracted frame paths
  - Validates video opens successfully and has ≥2 extractable frames
- [ ] 1.3. Create `tools/sfm_spike/feature_matcher.py`:
  - `detect_keypoints(image_path: Path, method: str = "ORB", max_keypoints: int = 2000) -> tuple[list[cv2.KeyPoint], np.ndarray]`
  - `match_pair(desc1: np.ndarray, desc2: np.ndarray, ratio_threshold: float = 0.75) -> list[cv2.DMatch]`
  - `estimate_fundamental(kp1, kp2, matches) -> tuple[np.ndarray, np.ndarray, int, float]` — returns F, inlier_mask, inlier_count, inlier_ratio
  - `MatchResult` dataclass: frame_i, frame_j, total_keypoints_i, total_keypoints_j, raw_matches, inlier_count, inlier_ratio, fundamental_matrix_rank
  - `match_sequence(frame_paths: list[Path]) -> list[MatchResult]` — runs matching on all adjacent pairs
- [ ] 1.4. Create `tests/test_sfm_spike.py`:
  - `test_frame_extractor_count` — synthetic video (10 frames) → extracts correct count at interval=2
  - `test_feature_matcher_self_match` — identical image → 100% inlier ratio
  - `test_feature_matcher_shifted` — synthetically shifted image → high inlier ratio, correct F
  - `test_min_keypoints_threshold` — 1024×768 textured image → ≥50 keypoints
  - `test_match_result_dataclass` — all fields populated correctly
- [ ] 1.5. Create synthetic test video fixture: 10 frames of a shifted checkerboard pattern (no GPU needed)
- [ ] 1.6. Run tests, verify all pass. Report: keypoints per frame, matches per pair, inlier ratio on synthetic data.

### Done Criteria
- `frame_extractor.py` extracts frames from MP4 at configurable interval
- `feature_matcher.py` detects ≥50 keypoints on 1024×768 images, matches with Lowe's ratio test, estimates fundamental matrix via RANSAC
- All unit tests pass
- On synthetic shifted-checkerboard video: inlier ratio > 80%

---

## Task 2: Camera Pose Estimation from Video Frames

**Requirements:** 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

**Description:** Build the essential matrix decomposition and pose chaining pipeline that recovers a camera trajectory from matched features. Uses CameraContract intrinsics (60° vFOV, 1024×768) to go from pixel correspondences to calibrated poses.

### Subtasks

- [ ] 2.1. Create `tools/sfm_spike/pose_estimator.py`:
  - `camera_intrinsics_from_contract(vfov_deg: float = 60.0, width: int = 1024, height: int = 768) -> np.ndarray` — returns 3×3 K matrix
  - `estimate_pose_pair(kp1, kp2, matches, inlier_mask, K) -> tuple[np.ndarray, np.ndarray, int]` — returns R (3×3), t (3×1 unit), inlier_count from `cv2.recoverPose`
  - `PoseResult` dataclass: frame_i, frame_j, R, t, inlier_count, is_degenerate (bool)
  - `chain_poses(pose_results: list[PoseResult]) -> list[np.ndarray]` — cumulative 4×4 extrinsic matrices
  - `detect_degenerate(R, t, inlier_count) -> bool` — flags pure rotation (|t| < 1e-6) or insufficient inliers (<10)
- [ ] 2.2. Add to `tests/test_sfm_spike.py`:
  - `test_intrinsics_from_contract` — fx ≈ 665.1, cx=512, cy=384
  - `test_pose_recovery_synthetic` — known R, t on synthetic correspondences → recovered within 5° rotation error and 10° translation direction error
  - `test_pose_chain_length` — N pose results → N+1 extrinsic matrices
  - `test_degenerate_detection` — near-zero translation flagged
- [ ] 2.3. Verify: on synthetic stereo pair with 10cm baseline, recovered translation direction matches ground truth within 10°
- [ ] 2.4. Output format: list of 4×4 matrices in CameraContract coordinate system (X-right, Y-up, Z-depth)

### Done Criteria
- `pose_estimator.py` computes camera intrinsics from CameraContract, decomposes essential matrix, chains into trajectory
- Degenerate cases (pure rotation, low inliers) detected and flagged
- Synthetic test with known geometry: translation direction error < 10°, rotation error < 5°
- All unit tests pass

---

## Task 3: Sparse Point Cloud Triangulation

**Requirements:** 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7

**Description:** Triangulate 3D points from multi-view feature correspondences, filter bad points, and export the result as a point cloud with per-point confidence.

### Subtasks

- [ ] 3.1. Create `tools/sfm_spike/triangulator.py`:
  - `triangulate_pair(kp1, kp2, matches, P1: np.ndarray, P2: np.ndarray, K: np.ndarray) -> np.ndarray` — returns Nx4 homogeneous points
  - `filter_points(points_4d: np.ndarray, P1, P2, kp1, kp2, matches, K, max_reproj_px: float = 2.0, max_depth_m: float = 10.0) -> tuple[np.ndarray, np.ndarray]` — returns filtered Nx3 + confidence scores
  - `PointCloud` dataclass: points (Nx3), confidence (N,), frame_pairs (provenance), bounding_box (min_xyz, max_xyz)
  - `triangulate_sequence(frame_paths, match_results, pose_results, K) -> PointCloud`
  - `export_ply(cloud: PointCloud, output_path: Path) -> Path` — using trimesh
  - `compare_to_metric_plan(cloud: PointCloud, room_dimensions: tuple[float, float, float]) -> dict` — bounding box ratio, scale estimate
- [ ] 3.2. Add to `tests/test_sfm_spike.py`:
  - `test_triangulate_synthetic_pair` — two cameras 0.1m apart, known 3D point → triangulated within 1% depth error
  - `test_filter_behind_camera` — point behind either camera rejected
  - `test_filter_high_reproj_error` — point with >2px reprojection rejected
  - `test_filter_far_depth` — point at 15m rejected (indoor constraint)
  - `test_export_ply` — file written, non-empty, valid PLY header
  - `test_bounding_box_comparison` — known cloud vs known room dims → ratio computed correctly
- [ ] 3.3. Confidence score: `1.0 / (1.0 + reproj_error_px)` — high at well-triangulated features, decays with error
- [ ] 3.4. PLY export includes RGB color from source frame pixel (for visualization)

### Done Criteria
- `triangulator.py` triangulates points, filters by behind-camera/reprojection/depth, exports PLY
- Synthetic stereo pair: triangulation error < 1% of depth
- Per-point confidence computed and stored
- Bounding box compared to MetricPlan dimensions (ratio reported)
- All unit tests pass

---

## Task 4: Depth Comparison — Stereo vs DA3 vs MetricPlan

**Requirements:** 4.1, 4.2, 4.3, 4.4, 4.5, 4.6

**Description:** Build the comparison framework that projects the sparse point cloud into the hero frame, interpolates to a dense depth map, and computes quantitative metrics against DA3 monocular depth and MetricPlan controlled-camera depth.

### Subtasks

- [ ] 4.1. Create `tools/sfm_spike/depth_comparison.py`:
  - `project_to_hero(cloud: PointCloud, K: np.ndarray, hero_extrinsic: np.ndarray, img_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]` — returns pixel_coords (Mx2) and depth_values (M,) for points visible in hero
  - `interpolate_depth(pixel_coords, depth_values, img_shape, method: str = "linear") -> np.ndarray` — dense depth map via scipy griddata
  - `compute_scale_factor(sfm_depth: np.ndarray, reference_depth: np.ndarray) -> float` — least-squares optimal scale s: min ||s*sfm - ref||²
  - `DepthComparisonMetrics` dataclass: mae_m, relative_error_pct, pearson_r, scale_factor, coverage_fraction, valid_pixel_count
  - `compare_depths(sfm_depth: np.ndarray, reference_depth: np.ndarray) -> DepthComparisonMetrics`
  - `render_comparison_png(canon_path: Path, da3_depth: np.ndarray, sfm_depth: np.ndarray, error_map: np.ndarray, output_path: Path) -> Path` — 4-panel side-by-side visualization
- [ ] 4.2. Add to `tests/test_sfm_spike.py`:
  - `test_project_to_hero_visibility` — points behind hero camera not projected
  - `test_interpolate_dense` — sparse input → dense output with correct shape
  - `test_scale_factor_identity` — identical depths → scale 1.0
  - `test_scale_factor_doubled` — one depth 2× the other → scale 2.0
  - `test_comparison_metrics_perfect` — identical depths → MAE=0, correlation=1.0
  - `test_comparison_handles_sparse` — only 10% coverage → still computes valid metrics on available pixels
- [ ] 4.3. Handle edge cases: NaN/inf in depth maps, zero-coverage regions, mismatched resolutions
- [ ] 4.4. Visualization uses matplotlib colormaps (viridis for depth, RdBu for error)

### Done Criteria
- `depth_comparison.py` projects, interpolates, computes metrics, renders visualization
- Scale factor computed correctly on synthetic examples
- Handles sparse coverage (as low as 5% of pixels) without crashing
- Comparison PNG renders cleanly with colormapped depth and error
- All unit tests pass

---

## Task 5: FLUX Multi-View Consistency Measurement

**Requirements:** 5.1, 5.2, 5.3, 5.4, 5.5, 5.6

**Description:** Measure whether the pipeline's independently-generated FLUX cardinal views share enough geometric features for triangulation, using the same matching pipeline as Task 1. This provides the empirical basis for choosing video-first vs depth-conditioned stills.

### Subtasks

- [ ] 5.1. Create `tools/sfm_spike/flux_view_matcher.py`:
  - `load_flux_views(session_dir: Path) -> list[Path]` — find all FLUX cardinal view PNGs from a V2 session
  - `match_all_pairs(view_paths: list[Path]) -> list[MatchResult]` — run feature_matcher on all N*(N-1)/2 unique pairs
  - `FluxConsistencyReport` dataclass: pairs_tested, pairs_above_threshold, avg_inlier_ratio, max_inlier_ratio, verdict (str: "consistent" | "inconsistent"), video_comparison (dict with video avg for context)
  - `assess_consistency(flux_results: list[MatchResult], video_results: list[MatchResult] | None = None, threshold: float = 0.30) -> FluxConsistencyReport`
- [ ] 5.2. Add to `tests/test_sfm_spike.py`:
  - `test_flux_matcher_self_consistency` — same image in all slots → perfect matches (baseline sanity)
  - `test_flux_matcher_random_images` — unrelated images → near-zero inlier ratio
  - `test_consistency_verdict_threshold` — mock results above/below 30% → correct verdict
  - `test_comparison_table_format` — output includes both video and FLUX statistics
- [ ] 5.3. If no real FLUX views available, tests use synthetic images with known overlap/no-overlap
- [ ] 5.4. Report format: markdown table comparing video pairs vs FLUX pairs on same metrics

### Done Criteria
- `flux_view_matcher.py` matches all FLUX view pairs, computes consistency verdict
- Threshold-based decision: ≥3 of 10 pairs with >30% inliers → "consistent"
- Comparison against video baseline included in report
- All unit tests pass
- Expected empirical finding documented: video >> FLUX for geometric consistency

---

## Task 6: Derive Optimal Capture Specification

**Requirements:** 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

**Description:** Analyze all measurements from Tasks 1–5 and derive the `CaptureSpec` frozen dataclass containing empirically-determined optimal parameters for the pipeline's multi-view generation.

### Subtasks

- [ ] 6.1. Create `tools/sfm_spike/capture_spec.py`:
  - `CaptureSpec` frozen dataclass (as defined in design.md): min_baseline_m, optimal_baseline_m, max_baseline_m, min_overlap_fraction, min_feature_density_kp_mpx, recommended_method, optimal_frame_interval, derivation_evidence
  - `__post_init__` validation: all values positive, overlap in [0, 1], baselines ordered (min < optimal < max), baseline range 0.05–1.0m
  - `derive_from_measurements(match_results: list[MatchResult], pose_results: list[PoseResult], depth_metrics: DepthComparisonMetrics, flux_report: FluxConsistencyReport, room_dimensions: tuple[float, float, float]) -> CaptureSpec`
  - Derivation logic:
    - `min_baseline`: smallest frame interval with ≥100 inliers × estimated per-frame displacement
    - `optimal_baseline`: frame interval with lowest depth MAE × estimated displacement
    - `min_overlap`: 1 - (1 / avg_inlier_ratio) clamped to [0.3, 0.8]
    - `min_feature_density`: observed minimum across valid frames
    - `recommended_method`: "video" if FLUX verdict is "inconsistent", else "depth_conditioned_stills"
    - `optimal_frame_interval`: interval with best depth accuracy from Task 4
- [ ] 6.2. Create `tools/sfm_spike/run_spike.py`:
  - CLI entry point: `python -m tools.sfm_spike.run_spike --video <path> [--flux-session <dir>] [--da3-depth <path>] [--room-dims W,D,H]`
  - Runs Tasks 1→2→3→4→(5 if FLUX available)→6 in sequence
  - Outputs: `CaptureSpec` JSON, measurement report (markdown), comparison PNG
  - Handles missing optional inputs gracefully (no FLUX views → skip Task 5; no DA3 → skip comparison)
- [ ] 6.3. Add to `tests/test_sfm_spike.py`:
  - `test_capture_spec_validation` — invalid values (negative baseline, overlap > 1) raise ValueError
  - `test_capture_spec_frozen` — cannot assign attributes after construction
  - `test_derive_from_measurements_plausible` — mock measurements → spec values in valid ranges
  - `test_run_spike_cli_help` — `--help` flag works without crashing
- [ ] 6.4. Human-readable derivation report format: one paragraph per spec value explaining the measurement that produced it

### Done Criteria
- `CaptureSpec` is a validated frozen dataclass with all required fields
- `derive_from_measurements` produces plausible values from mock data
- `run_spike.py` CLI runs end-to-end (on synthetic data) and outputs CaptureSpec JSON + report
- All values traceable to specific measurements (derivation_evidence populated)
- All unit tests pass

---

## Task 7: CapturePlanner Module Integrated into Multi-View Generator

**Requirements:** 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9

**Description:** Create the production `CapturePlanner` that computes optimal camera positions from MetricPlan + CaptureSpec, and integrate it into the multi-view generator with backward compatibility.

### Subtasks

- [ ] 7.1. Create `src/unified_pipeline/capture_planner.py`:
  - `PlannedCamera` dataclass: position, target, camera_type ("hero"|"stereo_left"|"stereo_right"|"coverage"), baseline_m, pair_id, fov, label
  - `CaptureManifest` dataclass: cameras (list[PlannedCamera]), capture_spec_hash, room_dimensions, generation_method
  - `CapturePlanner` class:
    - `__init__(self, metric_plan: MetricPlan, camera_contract: CameraContract, capture_spec: CaptureSpec | None = None)`
    - `plan(self) -> CaptureManifest`
    - `_plan_hero(self) -> PlannedCamera` — unchanged from CameraContract
    - `_plan_stereo_pair(self, hero: PlannedCamera) -> list[PlannedCamera]` — left/right at spec.optimal_baseline, clamped to room
    - `_plan_coverage(self, hero: PlannedCamera) -> list[PlannedCamera]` — walls not visible from hero
    - `_adapt_baseline(self, baseline: float) -> float` — min(baseline, min_room_dim * 0.25)
    - `_validate_camera_inside_room(self, pos: tuple) -> tuple` — clamp to room with 0.3m clearance
  - Fallback: if `capture_spec` is None, produce the same 5 cardinal cameras as current `_compute_cardinal_cameras`
- [ ] 7.2. Modify `src/unified_pipeline/multi_view_generator.py`:
  - Import `CapturePlanner` (with try/except ImportError for backward compat)
  - In `generate_multi_views`: if `CaptureSpec` available, use `CapturePlanner.plan()` instead of `_compute_cardinal_cameras`
  - `_compute_cardinal_cameras` remains as fallback (not deleted)
  - New parameter: `capture_spec: CaptureSpec | None = None`
- [ ] 7.3. Create `tests/test_capture_planner.py`:
  - `test_hero_matches_contract` — hero camera position/target equals CameraContract
  - `test_stereo_pair_baseline` — left-right distance equals adapted baseline
  - `test_cameras_inside_room_4x4` — all cameras ≥0.3m from walls in 4×4×2.7m room
  - `test_cameras_inside_room_small` — all cameras ≥0.3m from walls in 2×2×2.4m room (baseline reduced)
  - `test_coverage_all_walls` — every wall has ≥1 camera looking at it
  - `test_deterministic` — same inputs → same manifest (run twice, compare)
  - `test_fallback_no_spec` — CaptureSpec=None → 5 cardinal cameras (existing behavior)
  - `test_manifest_structure` — all required fields populated, types correct
  - `test_baseline_adaptation` — small room baseline < large room baseline
- [ ] 7.4. Verify: existing multi-view generation tests still pass (backward compatibility)

### Done Criteria
- `CapturePlanner` produces a valid `CaptureManifest` with hero + stereo + coverage cameras
- All cameras inside room with 0.3m clearance
- Baseline adapts to room size
- Deterministic for same inputs
- Backward compatible: no CaptureSpec → existing cardinal behavior
- Multi-view generator accepts optional CaptureSpec
- All new and existing tests pass

---

## Task 8: Video-Derived Stereo Depth as Bounded Evidence

**Requirements:** 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7

**Description:** Create the production `StereoDepthEstimator` that runs the full SfM pipeline on video frames and produces `StereoDepthEvidence` with identical authority constraints as DA3 `DepthEvidence`.

### Subtasks

- [ ] 8.1. Create `src/unified_pipeline/stereo_depth_bridge.py`:
  - Import spike modules: `frame_extractor`, `feature_matcher`, `pose_estimator`, `triangulator`, `depth_comparison`
  - `StereoDepthEvidence` frozen dataclass (as defined in design.md):
    - Same authority fields as `DepthEvidence`: spatial_authority=False, collision_enabled=False, optional=True, forbidden_authorities=FORBIDDEN_DEPTH_AUTHORITIES
    - `__post_init__` validation: raises `DepthAuthorityError` if spatial_authority=True or collision_enabled=True or forbidden_authorities modified
    - evidence_kind = "stereo_depth_evidence"
    - Additional: depth_map_path, confidence_map_path, coverage_fraction, scale_factor, triangulated_point_count, source_video_sha256, frame_count_used, total_inlier_count
  - `StereoDepthEstimator` class:
    - `__init__(self, output_dir: Path, frame_interval: int = 5)`
    - `async def estimate(self, video_path: Path, camera_contract: CameraContract, *, session_id: str) -> StereoDepthEvidence`
    - Pipeline: extract frames → match → pose → triangulate → project to hero → interpolate → save .npy → wrap as evidence
    - `async def estimate_optional(self, ...) -> StereoDepthEvidence | None` — suppresses non-authority errors
  - Confidence map: float32 ndarray, high (>0.8) at triangulated features, decays with distance from nearest feature
- [ ] 8.2. Create `tests/test_stereo_depth.py`:
  - `test_cannot_construct_with_authority` — spatial_authority=True raises DepthAuthorityError
  - `test_cannot_construct_with_collision` — collision_enabled=True raises DepthAuthorityError
  - `test_deny_list_immutable` — modified forbidden_authorities raises DepthAuthorityError
  - `test_evidence_kind_correct` — evidence_kind == "stereo_depth_evidence"
  - `test_provenance_fields_required` — empty source_video_sha256 raises validation error
  - `test_coverage_bounds` — coverage_fraction must be in [0, 1]
  - `test_confidence_map_shape` — matches depth map shape
  - `test_estimate_optional_suppresses_errors` — file-not-found returns None, authority error still raises
- [ ] 8.3. Ensure `StereoDepthEvidence.to_dict()` serializes cleanly to JSON (matching DepthEvidence pattern)
- [ ] 8.4. SHA-256 computation for video file provenance (same pattern as depth_bridge.py)

### Done Criteria
- `StereoDepthEvidence` has identical authority constraints as `DepthEvidence`
- Cannot construct with spatial_authority=True (raises)
- Deny-list is identical and immutable
- `StereoDepthEstimator` runs the full pipeline: video → evidence
- Confidence map produced with correct semantics
- Provenance fully populated
- All unit tests pass

---

## Task 9: End-to-End Integration Test

**Requirements:** 9.1, 9.2, 9.3, 9.4, 9.5, 9.6

**Description:** Create integration tests verifying the full pipeline works end-to-end without breaking existing functionality, the authority model, or backward compatibility.

### Subtasks

- [ ] 9.1. Create `tests/e2e/test_sfm_capture_planning.py`:
  - **Fast-path test** (no GPU, <2s):
    - Construct Brief (Danny's kitchenette: 4×3.5×2.7m, round table, 2 chairs, counter, coffee maker)
    - Generate MetricPlan via `MetricPlanGenerator.generate_deterministic(brief)`
    - Construct CameraContract (standard 60° vFOV)
    - Construct CaptureSpec (hardcoded plausible values for test)
    - Run `CapturePlanner.plan()` → CaptureManifest
    - Assert: all cameras inside room with 0.3m clearance
    - Assert: stereo pair baseline within spec range
    - Assert: manifest has hero + stereo + coverage cameras
    - Assert: deterministic (run twice, compare)
    - Assert: completes in <2 seconds
  - **Authority preservation test**:
    - Verify MetricPlan not mutated after CapturePlanner runs
    - Verify CameraContract hash unchanged
    - Verify FORBIDDEN_DEPTH_AUTHORITIES unchanged in StereoDepthEvidence
    - Attempt to construct StereoDepthEvidence with spatial_authority=True → assert raises
  - **Backward compatibility test**:
    - Call multi_view_generator path with capture_spec=None
    - Assert: produces 5 cardinal cameras (existing behavior)
    - Assert: no import errors if capture_planner module missing (try/except path)
- [ ] 9.2. Add `--live-gpu` pytest marker for full-pipeline tests:
  - IF video artifact exists at expected path: run full SfM pipeline
  - Assert: StereoDepthEvidence produced with coverage > 0
  - Assert: depth map is float32, correct shape
  - Assert: confidence map has values in [0, 1]
  - Skip with informative message if no video available
- [ ] 9.3. Verify no existing tests broken:
  - Run full test suite: `pytest tests/ -x --ignore=tests/e2e` (unit tests)
  - Run existing e2e tests: `pytest tests/e2e/ -x --ignore=tests/e2e/test_sfm_capture_planning.py`
  - All must pass unchanged
- [ ] 9.4. Create `tools/sfm_spike/demo.py`:
  - If video available: run full measurement, print CaptureSpec, save comparison PNG
  - If no video: print "No video found. Run with --video <path> or generate via MiniMax H3."
  - Print CaptureManifest for Danny's kitchenette as a demonstration

### Done Criteria
- Fast-path test passes in <2 seconds (no GPU)
- Authority model preserved: MetricPlan, CameraContract, deny-list all unchanged
- Backward compatibility: multi_view_generator works with and without CaptureSpec
- No existing tests broken
- `--live-gpu` test runs successfully when video is available
- Demo script shows complete measurement-to-manifest flow
