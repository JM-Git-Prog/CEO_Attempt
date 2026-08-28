# Requirements Document — SfM-Informed Capture Planning

## Introduction

This specification adds a Structure-from-Motion (SfM) measurement and capture-planning layer to the V2.0 unified world pipeline. The V2.0 pipeline currently generates multi-view images (FLUX cardinal views + MiniMax H3 video) without ensuring they contain sufficient geometric information for reliable 3D reconstruction. Each view is independently sampled with no inter-view consistency, stereo baseline, or epipolar constraint. Downstream geometry extraction (DA3 monocular depth, Hunyuan3D single-image mesh) operates on individual views in isolation, losing the multi-view triangulation signal that classical photogrammetry relies on.

This spec quantifies recoverable geometry from the pipeline's generated imagery and specifies optimal capture parameters for maximum downstream extractability — without violating the "one truth per concern" authority model where MetricPlan remains the sole spatial authority.

### Core Principles

1. **MetricPlan remains spatial authority** — this spec adds specification and evidence capabilities, never spatial claims.
2. **Empirical-first** — capture parameters are derived from measurement of actual AI-generated imagery, not theoretical assumptions about real-world photos.
3. **Video-first stereo** — MiniMax H3 video provides natural inter-frame consistency that independent FLUX samples lack.
4. **Same authority model as DA3** — stereo depth evidence carries identical constraints: non-authoritative, non-colliding, deny-listed.
5. **Spike informs production** — research measurements (Tasks 1–6) directly feed the production module (Tasks 7–9).

### Relationship to Existing Specs

- **unified-world-pipeline** — This spec extends the multi-view generation phase (Phase 2: Densify) with geometrically-informed camera planning. It does NOT modify Phases 1, 3, or 4.
- **depth_bridge.py authority model** — Stereo depth evidence follows identical `FORBIDDEN_DEPTH_AUTHORITIES` constraints as DA3 monocular evidence.
- **Scene Recovery Problem research** — This spec is the practical Rung-1 implementation bridge: measuring what geometry is actually recoverable from the pipeline's output and using that to inform generation.

### Environment Assumptions

- NVIDIA RTX 4090 (24GB VRAM), 96GB system RAM, Windows 11.
- OpenCV 4.12.0+ with contrib (ORB, SIFT, BFMatcher, RANSAC).
- Existing MiniMax H3 video generation capability via ComfyUI.
- Existing DA3 depth estimation via ComfyUI.
- Existing CameraContract (60° vFOV, 1024×768, right-handed X-right Y-up Z-depth).

---

## Requirements

### Requirement 1: Video Frame Geometry Measurement

**User Story:** As a developer, I want to measure how much 3D geometry is recoverable from MiniMax H3 video frames, so that I know whether video generation carries a usable stereo signal.

#### Acceptance Criteria

1. THE system SHALL extract frames at configurable intervals (default: every 5th frame) from MiniMax H3 MP4 video output.
2. THE system SHALL detect keypoints (ORB or SIFT via OpenCV) in each extracted frame.
3. THE system SHALL match keypoints between adjacent frame pairs using ratio test filtering (Lowe's ratio ≤ 0.75).
4. THE system SHALL estimate the fundamental matrix via RANSAC and report inlier count and ratio per pair.
5. THE system SHALL report per-frame keypoint density (keypoints per megapixel) as a generation quality metric.
6. AT LEAST 50 keypoints per frame SHALL be detectable in a 1024×768 AI-generated image for the measurement to be considered valid.
7. THE system SHALL output structured results: per-pair match count, inlier count, inlier ratio, fundamental matrix condition.

### Requirement 2: Camera Pose Recovery from Video

**User Story:** As a developer, I want to recover camera trajectory from video frame correspondences, so that I can triangulate 3D points.

#### Acceptance Criteria

1. THE system SHALL compute the essential matrix from matched keypoints using known camera intrinsics derived from CameraContract (60° vFOV, 1024×768 → fx, fy, cx, cy).
2. THE system SHALL decompose the essential matrix into rotation and translation via `cv2.recoverPose`.
3. THE system SHALL chain pairwise poses into a cumulative camera trajectory (sequence of 4×4 extrinsic matrices).
4. THE recovered trajectory SHALL be monotonically consistent with the video generation prompt's described camera motion direction.
5. THE system SHALL output camera extrinsics in the CameraContract's coordinate system (right-handed, X-right, Y-up, Z-depth).
6. THE system SHALL detect and flag degenerate cases (pure rotation, insufficient parallax) where pose recovery is unreliable.

### Requirement 3: Sparse Point Cloud Triangulation

**User Story:** As a developer, I want to triangulate 3D points from multi-view correspondences, so that I can measure scene geometry directly.

#### Acceptance Criteria

1. THE system SHALL triangulate 3D positions for features tracked across ≥2 frames using `cv2.triangulatePoints`.
2. THE system SHALL reject points behind cameras (negative depth in camera frame).
3. THE system SHALL reject points with reprojection error >2px in either view.
4. THE system SHALL reject points at depths >10m (indoor scene constraint).
5. THE system SHALL output an Nx3 numpy array of 3D positions with per-point confidence scores (inverse reprojection error).
6. THE point cloud bounding box SHALL be compared against MetricPlan room dimensions as a sanity check (ratio reported, not enforced).
7. THE system SHALL export the point cloud as PLY for external visualization (using trimesh or plyfile).

### Requirement 4: Depth Comparison Framework

**User Story:** As a developer, I want to compare triangulated stereo depth against DA3 monocular depth and MetricPlan ground truth, so that I can quantify the value of stereo measurement.

#### Acceptance Criteria

1. THE system SHALL project triangulated 3D points into the hero frame to produce sparse depth values at pixel locations.
2. THE system SHALL interpolate sparse depth to a dense map using scipy `griddata` (linear, with nearest-neighbor fill for edges).
3. THE system SHALL compute per-pixel metrics against DA3 depth: MAE (meters), relative error (%), Pearson correlation coefficient.
4. THE system SHALL compute the optimal scale factor to align SfM depth (up-to-scale) to metric depth via least-squares fitting.
5. THE system SHALL produce a side-by-side visualization PNG: Canon RGB | DA3 depth colormapped | SfM depth colormapped | absolute error map.
6. THE system SHALL report coverage percentage: fraction of hero-frame pixels with SfM depth evidence.

### Requirement 5: FLUX Multi-View Consistency Measurement

**User Story:** As a developer, I want to measure whether independently-generated FLUX views share geometric features, so that I know if depth-conditioning is necessary for multi-view consistency.

#### Acceptance Criteria

1. THE system SHALL run feature matching between all pairs of FLUX cardinal views (10 unique pairs for 5 views).
2. THE system SHALL use the identical feature detection and matching pipeline as Requirement 1 (same detector, same ratio test, same RANSAC).
3. THE system SHALL compare FLUX pair match quality against video adjacent-frame match quality using the same metrics.
4. THE system SHALL report a definitive answer: are FLUX independent views geometrically consistent enough for triangulation? Threshold: >30% inlier ratio on ≥3 of 10 pairs.
5. IF FLUX views are NOT geometrically consistent, THE system SHALL document this as the empirical rationale for video-first or depth-conditioned generation strategy.
6. THE system SHALL output a comparison table: video pairs (avg inliers, avg ratio) vs FLUX pairs (avg inliers, avg ratio).

### Requirement 6: Capture Specification Derivation

**User Story:** As a developer, I want an empirically-derived capture specification, so that the multi-view generator produces images optimized for geometry extraction.

#### Acceptance Criteria

1. THE system SHALL derive from measurements: minimum baseline (m), optimal baseline (m), minimum overlap fraction, minimum feature density (keypoints/megapixel), recommended generation method (video vs conditioned stills), and optimal frame sampling rate.
2. THE capture specification SHALL be computed from empirical measurements of Tasks 1–5, not from theoretical assumptions alone.
3. THE capture specification SHALL be represented as a frozen dataclass (`CaptureSpec`) with `__post_init__` validation.
4. ALL spec values SHALL fall within physically plausible ranges for indoor scenes: baseline 0.05–1.0m, overlap 0.3–0.8, feature density ≥50 kp/mpx.
5. THE `CaptureSpec` SHALL include a `derivation_evidence` field recording the measurement session ID and key statistics that produced each value.
6. THE system SHALL produce a human-readable derivation report explaining how each spec value was chosen.

### Requirement 7: Capture Planner Module

**User Story:** As a developer, I want a production CapturePlanner that computes optimal camera positions from MetricPlan + CaptureSpec, so that the multi-view generator produces geometrically-informed views.

#### Acceptance Criteria

1. THE `CapturePlanner` SHALL take MetricPlan (room dimensions, openings) + CameraContract (hero view) + CaptureSpec as input.
2. THE `CapturePlanner` SHALL output a `CaptureManifest` listing all planned cameras: position, target, type (hero | stereo_left | stereo_right | coverage), baseline_m (for stereo pairs).
3. ALL planned cameras SHALL be positioned inside the room with ≥0.3m clearance from every wall.
4. Stereo pairs SHALL have the baseline specified by CaptureSpec, oriented perpendicular to the viewing direction.
5. Coverage views SHALL ensure every wall surface has ≥ `CaptureSpec.min_overlap` overlap fraction with at least one adjacent view.
6. THE planner SHALL be deterministic: identical inputs produce identical CaptureManifest.
7. THE planner SHALL adapt baseline to room size: `min(spec.optimal_baseline, min_room_dimension * 0.25)`.
8. THE `CapturePlanner` SHALL NOT carry spatial authority — it specifies what to generate, not what the geometry is. MetricPlan remains the sole spatial authority.
9. THE `CaptureManifest` SHALL be backward-compatible: if no CaptureSpec is available, the planner SHALL fall back to the existing 5 cardinal cameras.

### Requirement 8: Stereo Depth Evidence Production

**User Story:** As a developer, I want video-derived stereo depth wrapped as bounded evidence, so that downstream stages can optionally consume it without violating the authority model.

#### Acceptance Criteria

1. THE system SHALL produce `StereoDepthEvidence` with identical authority constraints as DA3 `DepthEvidence`: `spatial_authority=False`, `collision_enabled=False`, `optional=True`.
2. THE `StereoDepthEvidence` SHALL carry the identical `FORBIDDEN_DEPTH_AUTHORITIES` deny-list as the existing `DepthEvidence` class, and the deny-list SHALL be immutable.
3. CONSTRUCTION of `StereoDepthEvidence` with `spatial_authority=True` SHALL raise `DepthAuthorityError`.
4. THE evidence SHALL include provenance: source video SHA-256, frame count used, total inlier count, triangulated point count, coverage percentage.
5. THE evidence SHALL include a per-pixel confidence map: high (>0.8) at directly triangulated features, medium (0.3–0.8) at interpolated regions near features, low (<0.3) at far-extrapolated regions.
6. THE `evidence_kind` SHALL be `"stereo_depth_evidence"` to distinguish from monocular `"depth_evidence"`.
7. THE evidence SHALL include the computed scale factor aligning SfM depth to metric depth (for informational purposes only, not authority).

### Requirement 9: Integration Without Authority Violation

**User Story:** As an architect, I want the SfM capture planning integrated end-to-end without breaking "one truth per concern."

#### Acceptance Criteria

1. THE `CapturePlanner` SHALL replace `_compute_cardinal_cameras` in the multi-view generator as the default camera computation.
2. THE integration SHALL NOT modify: MetricPlan spatial authority, CameraContract immutability, the `FORBIDDEN_DEPTH_AUTHORITIES` deny-list, or the `DepthEvidence` class interface.
3. AN end-to-end fast-path test SHALL verify: Brief → MetricPlan → CapturePlanner → CaptureManifest → correct camera parameters — completing in <2 seconds without GPU.
4. IF video artifacts exist locally, a `--live-gpu` integration test SHALL run the full SfM pipeline: video → frames → matches → poses → triangulation → StereoDepthEvidence.
5. THE multi-view generator SHALL remain backward-compatible: if no CaptureSpec is provided (or CapturePlanner import fails), it SHALL fall back to existing `_compute_cardinal_cameras` behavior.
6. NO existing test in the test suite SHALL break as a result of this integration.
