# Design Document — SfM-Informed Capture Planning

## Overview

This design adds an SfM measurement and capture-planning layer between MetricPlan generation and multi-view image generation. The layer has two phases: a research spike that measures geometric signal quality from existing AI-generated imagery, and a production module that uses those measurements to compute optimal camera positions for downstream extractability.

The design preserves the pipeline's "one truth per concern" architecture by operating strictly as a **specification layer** (telling the generator where to point cameras) and an **evidence layer** (producing depth evidence with identical authority constraints as DA3). It never claims spatial authority.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SPATIAL AUTHORITY (unchanged)                      │
│                         MetricPlan                                    │
│                    CameraContract (frozen)                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │ room_dimensions, hero camera
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   NEW: CapturePlanner                                 │
│                                                                       │
│  Input:  MetricPlan + CameraContract + CaptureSpec                   │
│  Output: CaptureManifest (list of cameras to generate)               │
│                                                                       │
│  Role: SPECIFICATION ONLY — tells generator WHERE to point           │
│         cameras for maximum geometric extractability.                 │
│         Does NOT carry or produce spatial authority.                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ CaptureManifest
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Multi-View Generator (modified)                        │
│                                                                       │
│  Was: 5 hardcoded cardinal cameras from _compute_cardinal_cameras    │
│  Now: Cameras from CaptureManifest (hero + stereo + coverage)        │
│       + optional MiniMax H3 video generation                         │
│                                                                       │
│  Backward compat: falls back to cardinal cameras if no CaptureSpec   │
└────────────────────────────┬────────────────────────────────────────┘
                             │ generated views + video frames
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NEW: StereoDepthEstimator                                │
│                                                                       │
│  Input:  Video frames OR view pairs with known camera transforms     │
│  Process: Feature detect → Match → Essential matrix → Triangulate    │
│  Output: StereoDepthEvidence (same deny-list as DA3 DepthEvidence)   │
│                                                                       │
│  Authority: NONE. Evidence only. Cannot override MetricPlan.         │
│  Confidence map: high at triangulated, low at interpolated.          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Video-first stereo signal

**Decision:** Use MiniMax H3 video frames as the primary stereo source rather than attempting true stereo from independent FLUX generations.

**Rationale:** A video generation maintains temporal coherence between frames — the same 3D scene is depicted with smooth camera motion. Independent FLUX text-to-image samples do not share a 3D state: the same window might be different sizes or positions in adjacent views. Video frames are the cheapest multi-view consistency source already available in the pipeline (via `canon_geometry_spike.py`'s MiniMax H3 workflow).

**Consequence:** The CaptureSpec may ultimately recommend video generation as the primary multi-view source, with individual FLUX views used only for high-resolution hero shots. Requirement 5 (FLUX consistency measurement) provides the empirical data to confirm or overturn this hypothesis.

### 2. CaptureSpec is empirically derived, not theoretical

**Decision:** All capture parameters (baseline, overlap, feature density requirements) come from actual measurements on AI-generated imagery, not from classical photogrammetry rules-of-thumb for real photos.

**Rationale:** AI-generated images have fundamentally different characteristics from real photographs:
- Cleaner, more uniform textures (fewer natural features)
- No lens distortion or chromatic aberration
- Potential geometric inconsistencies between frames (hallucinated objects, breathing walls)
- Different noise characteristics (no sensor noise, but generation artifacts)

Classical rules like "baseline = 15% of scene depth" assume real-world feature distributions. Measuring actual keypoint density and match quality from the pipeline's specific generators gives reliable spec values.

**Consequence:** Tasks 1–5 MUST complete before the CaptureSpec can be derived. The spec is not a theoretical document — it's an empirical measurement.

### 3. Same authority model as DA3 depth

**Decision:** `StereoDepthEvidence` carries identical authority constraints to `DepthEvidence`: `spatial_authority=False`, `collision_enabled=False`, same `FORBIDDEN_DEPTH_AUTHORITIES` deny-list, raises `DepthAuthorityError` on violation.

**Rationale:** The existing depth authority firewall exists for good reason — monocular depth estimation drifts under lighting/material changes and cannot be trusted for absolute spatial decisions. Stereo depth is more geometrically grounded (triangulation is a physical measurement, not a learned prior), but in this pipeline the "stereo" comes from AI-generated video which can still hallucinate. Until the evidence is proven reliable enough for bounded authority promotion (a future spec gate), it stays at the same trust level as DA3.

**Consequence:** StereoDepthEvidence can be used for:
- Visual quality assessment (does the world "look right" from novel views?)
- Object shape refinement hints (non-authoritative)
- Geometric consistency validation (does the Canon agree with MetricPlan?)

It CANNOT be used for:
- Room dimensions, openings, architectural geometry
- Collision or navigation geometry
- Object transforms or camera parameters

### 4. CapturePlanner is pure specification, not authority

**Decision:** The CapturePlanner computes WHERE to put cameras based on the MetricPlan's known room geometry and the CaptureSpec's requirements. It never claims to know what the geometry IS.

**Rationale:** The planner uses MetricPlan dimensions to ensure cameras are inside the room and have sufficient baseline. This is using spatial authority as INPUT (reading from MetricPlan), not claiming it as OUTPUT. The planner's job is analogous to a photographer choosing where to stand — it doesn't change the room, it optimizes the observation.

**Consequence:** The planner's output (CaptureManifest) is a generation instruction, not a measurement result. Downstream code that receives generated images must still extract geometry through measurement (SfM, depth estimation), not assume the manifest's geometry is truth.

### 5. Incremental: spike then production, same codebase

**Decision:** The research spike (`tools/sfm_spike/`) and production modules (`src/unified_pipeline/`) share core algorithms but differ in interface. The spike is CLI-driven for interactive measurement; the production modules are async, pipeline-integrated, and emit structured evidence.

**Rationale:** Building the spike as throwaway code creates rewrite risk. Building it directly in production creates premature integration risk. The middle path: spike code is structured cleanly enough to be imported by production modules, but lives in `tools/` where it's clearly experimental.

**Consequence:** `capture_spec.py` and core matching/triangulation functions in the spike are importable by the production `capture_planner.py` and `stereo_depth_bridge.py`. No algorithm duplication — only interface wrapping.

---

## Module Layout

```
tools/sfm_spike/                         # Research spike (Tasks 1-6)
├── __init__.py
├── frame_extractor.py                   # Req 1: video → frames at configurable interval
├── feature_matcher.py                   # Req 1: ORB/SIFT detection + BFMatcher + Lowe's ratio + RANSAC
├── pose_estimator.py                    # Req 2: essential matrix → camera trajectory
├── triangulator.py                      # Req 3: multi-view triangulation + filtering
├── depth_comparison.py                  # Req 4: stereo vs DA3 vs MetricPlan comparison
├── flux_view_matcher.py                 # Req 5: FLUX cardinal view consistency measurement
├── capture_spec.py                      # Req 6: CaptureSpec derivation from measurements
└── run_spike.py                         # CLI runner: runs all measurements, outputs CaptureSpec

src/unified_pipeline/                    # Production modules (Tasks 7-9)
├── capture_planner.py                   # Req 7: CapturePlanner + CaptureManifest
├── stereo_depth_bridge.py              # Req 8: StereoDepthEstimator + StereoDepthEvidence
└── multi_view_generator.py             # Req 7/9: modified to use CapturePlanner (backward compat)

tests/                                   # Tests
├── test_sfm_spike.py                   # Reqs 1-6 unit tests
├── test_capture_planner.py             # Req 7 unit tests
├── test_stereo_depth.py                # Req 8 unit tests
└── e2e/
    └── test_sfm_capture_planning.py    # Req 9 integration tests
```

---

## Data Flow

### Phase A: Research Spike (offline, developer-triggered)

```
MiniMax H3 Video (MP4)
    │
    ▼ frame_extractor.py (every Nth frame)
Extracted Frames (PNG[])
    │
    ▼ feature_matcher.py (ORB/SIFT + BFMatcher + RANSAC)
Match Results (keypoints, matches, inliers, fundamental matrices)
    │
    ├─▶ pose_estimator.py (essential matrix → R, t → trajectory)
    │       │
    │       ▼
    │   Camera Trajectory (4×4 extrinsics[])
    │       │
    │       ▼ triangulator.py (cv2.triangulatePoints + filtering)
    │   Sparse Point Cloud (Nx3 + confidence)
    │       │
    │       ▼ depth_comparison.py (project → interpolate → compare)
    │   Depth Comparison Report (MAE, correlation, scale factor, viz PNG)
    │
    ├─▶ flux_view_matcher.py (same pipeline on FLUX cardinal views)
    │   FLUX Consistency Report (inlier ratios, verdict)
    │
    └─▶ capture_spec.py (analyze all results → derive parameters)
        CaptureSpec (frozen dataclass: baseline, overlap, density, method)
```

### Phase B: Production Integration (pipeline runtime)

```
MetricPlan + CameraContract + CaptureSpec
    │
    ▼ capture_planner.py
CaptureManifest (cameras: hero + stereo_pairs + coverage)
    │
    ▼ multi_view_generator.py (generates views per manifest)
Generated Views + Optional MiniMax H3 Video
    │
    ├─▶ (existing) vision_catalog.py → v2_mesh_builder.py
    │
    └─▶ stereo_depth_bridge.py (video → SfM → evidence)
        StereoDepthEvidence (non-authoritative, with confidence map)
```

---

## Detailed Component Design

### CaptureSpec (frozen dataclass)

```python
@dataclass(frozen=True)
class CaptureSpec:
    """Empirically-derived capture parameters for optimal geometry extraction."""

    # Baseline
    min_baseline_m: float          # Minimum camera displacement for useful parallax
    optimal_baseline_m: float      # Best baseline for depth accuracy/coverage tradeoff
    max_baseline_m: float          # Beyond this, feature matching degrades

    # Overlap and coverage
    min_overlap_fraction: float    # Minimum shared scene fraction between adjacent views
    min_feature_density_kp_mpx: float  # Minimum keypoints per megapixel

    # Generation method
    recommended_method: str        # "video" | "depth_conditioned_stills" | "independent_stills"
    optimal_frame_interval: int    # For video: sample every Nth frame

    # Provenance
    derivation_evidence: dict      # Measurement session ID + key statistics
```

### CaptureManifest (dataclass)

```python
@dataclass
class PlannedCamera:
    """One camera position in the capture manifest."""
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    camera_type: str               # "hero" | "stereo_left" | "stereo_right" | "coverage"
    baseline_m: float = 0.0        # For stereo pairs: distance from partner
    pair_id: str = ""              # Links stereo_left and stereo_right
    fov: float = 60.0
    label: str = ""

@dataclass
class CaptureManifest:
    """Complete set of cameras to generate for a session."""
    cameras: list[PlannedCamera]
    capture_spec_hash: str         # Provenance: which CaptureSpec produced this
    room_dimensions: tuple[float, float, float]
    generation_method: str         # "video" | "stills" | "hybrid"
```

### StereoDepthEvidence (frozen dataclass)

```python
@dataclass(frozen=True)
class StereoDepthEvidence:
    """Video-derived stereo depth — same authority constraints as DA3 DepthEvidence."""

    depth_map_path: str
    confidence_map_path: str       # Per-pixel confidence (0-1)
    coverage_fraction: float       # Fraction of pixels with evidence
    scale_factor: float            # SfM → metric alignment factor
    triangulated_point_count: int

    # Provenance
    source_video_sha256: str
    frame_count_used: int
    total_inlier_count: int

    # Authority constraints (IDENTICAL to DepthEvidence)
    evidence_kind: str = "stereo_depth_evidence"
    optional: bool = True
    collision_enabled: bool = False
    spatial_authority: bool = False
    authority_claims: tuple[str, ...] = ()
    forbidden_authorities: tuple[str, ...] = FORBIDDEN_DEPTH_AUTHORITIES
```

### CapturePlanner Algorithm

```
Input: MetricPlan(w, d, h), CameraContract(hero_pos, hero_target), CaptureSpec

1. Hero camera: unchanged from CameraContract
2. Stereo pair for hero:
   - baseline = min(spec.optimal_baseline, min(w, d) * 0.25)
   - stereo_left  = hero_pos + (-baseline/2, 0, 0)  [left of hero]
   - stereo_right = hero_pos + (+baseline/2, 0, 0)  [right of hero]
   - both target hero_target
   - validate: both inside room with 0.3m clearance; clamp if needed
3. Coverage views:
   - For each wall not visible from hero (>90° from hero direction):
     compute a camera at room center looking at that wall
   - Ensure min_overlap between adjacent coverage views
4. Adapt to room size:
   - If room is small (min(w,d) < 3m): reduce baseline, reduce number of coverage views
   - If room is large (min(w,d) > 6m): increase coverage views, add intermediate stereo pairs
5. Validate all cameras: inside room, 0.3m from walls, not coincident

Output: CaptureManifest
```

---

## Camera Intrinsics Derivation

From CameraContract (60° vFOV, 1024×768):

```python
vfov_rad = math.radians(60.0)
fy = (768 / 2) / math.tan(vfov_rad / 2)  # ≈ 665.1
fx = fy  # square pixels assumed
cx = 1024 / 2  # = 512.0
cy = 768 / 2   # = 384.0

K = np.array([
    [fx,  0, cx],
    [ 0, fy, cy],
    [ 0,  0,  1]
], dtype=np.float64)
```

This intrinsic matrix is used by:
- `pose_estimator.py` for essential matrix computation
- `triangulator.py` for point unprojection
- `stereo_depth_bridge.py` for the production evidence pipeline

---

## Failure Modes and Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| AI video has no matchable features (smooth walls, uniform textures) | Keypoint count < 50/frame | Report as "insufficient feature density"; CaptureSpec records it; recommend textured generation prompts |
| Camera motion too small (pure rotation, no parallax) | `recoverPose` inlier count < 10 or translation near-zero | Flag "degenerate motion"; skip triangulation; increase frame interval |
| Hallucinated geometry between frames (object appears/disappears) | Outlier ratio > 70% in RANSAC | Use only geometrically-consistent subset; report coverage loss |
| Point cloud scale wildly wrong vs MetricPlan | Bounding box ratio > 3× or < 0.3× MetricPlan | Flag "scale alignment unreliable"; increase scale factor uncertainty in evidence |
| No video available for a session | Video path doesn't exist | Fall back to monocular DA3 only; StereoDepthEvidence not produced |
| FLUX views have zero geometric consistency | All 10 pairs < 30% inlier ratio | Confirm video-first strategy; document as empirical finding |

---

## Dependencies

### Already Available (no new installs)

- `opencv-python` (cv2) — keypoint detection, matching, essential matrix, triangulation
- `numpy` — array operations, linear algebra
- `scipy` — `griddata` for depth interpolation
- `trimesh` — PLY export (already used for room shell)
- `Pillow` (PIL) — image I/O for visualizations
- `matplotlib` — optional, for comparison plots in spike

### Not Required

- No COLMAP (too heavy for this use case; OpenCV's two-view SfM is sufficient)
- No new ML models (features are classical CV, not learned)
- No new ComfyUI nodes (video generation already available)

---

## Relationship to Scene Recovery Problem

This spec implements the **practical measurement arm** of the Scene Recovery research:

| Scene Recovery Board Node | This Spec's Contribution |
|---------------------------|--------------------------|
| B2 (null space characterization) | Req 5 measures what one FLUX view cannot tell you vs what stereo can |
| B3 (gauge group) | CaptureSpec quantifies which side information (baseline, overlap) purchases which geometry |
| C3 (information budget) | Depth comparison (Req 4) empirically measures the views × prior tradeoff |
| E1 (landscape for continuous solve) | Point cloud sanity check measures whether local optimization could converge |
| F3 (certified metric scale) | Scale factor alignment quantifies the metric gap between SfM and ground truth |
| G1 (a-posteriori certificate) | Reprojection error serves as a weak certificate: low error = consistent geometry |

This spec does NOT attempt to prove any Scene Recovery theorem. It provides **empirical data** that the theoretical program can consume, and it builds **production infrastructure** that a future certified recovery algorithm could plug into.

---

## Future Considerations (explicitly out of scope for this spec)

1. **Bounded authority promotion** — allowing stereo depth to carry spatial authority within MetricPlan's uncertainty envelope. Requires a future spec gate with defined error bounds.
2. **Multi-view diffusion conditioning** — using SfM-derived depth as ControlNet conditioning for geometrically-consistent FLUX generation. Requires ControlNet-depth integration.
3. **Real photograph input** — accepting a user's actual photo (not AI-generated) and running full scene recovery. Requires solving the Canon-from-photo pathway.
4. **Dense MVS (Multi-View Stereo)** — going beyond sparse triangulation to dense depth maps via PatchMatch or learned MVS. Only valuable once sparse signal is proven reliable.
5. **Loop closure and bundle adjustment** — full COLMAP-style optimization for large-scale scenes. Overkill for single-room indoor scenes with 5–75 frames.
