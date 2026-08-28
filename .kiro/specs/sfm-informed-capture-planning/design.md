# Design Document — Geometry-Injected Capture Planning

## Overview

This design implements the **inject-then-validate** architecture for geometry-informed multi-view generation. The previous design (commit `f27e2ff`) attempted to extract geometry from AI-generated video via classical SfM. Adversarial review conclusively demonstrated that approach is invalid: AI video lacks real epipolar geometry, classical feature matchers fail on AI textures, and the extracted "evidence" was structurally discarded by the authority model anyway.

The corrected architecture:
1. **Inject** — MetricPlan renders depth maps along a planned camera trajectory; these directly condition the AI generator via ControlNet.
2. **Generate** — FLUX/MiniMax H3 produces images forced to follow MetricPlan geometry.
3. **Validate** — DA3 depth on the output is compared against the injected conditioning to verify fidelity.
4. **Back-project** — validated depth maps are unprojected into 3D using exact known camera matrices (no pose estimation).
5. **Fuse** — multi-view point clouds merge into a dense mesh replacing the parametric room shell.

No SfM. No feature matching. No essential matrix. No triangulation from hallucinated content.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SPATIAL AUTHORITY (unchanged)                      │
│                         MetricPlan                                    │
│                    CameraContract (frozen)                            │
└────────────┬───────────────────────────────────────┬────────────────┘
             │ room geometry                          │ hero camera
             ▼                                        ▼
┌────────────────────────┐              ┌─────────────────────────────┐
│   CapturePlanner       │              │  Depth Sequence Renderer     │
│                        │              │                              │
│ MetricPlan + hero →    │──────────────▶ For each planned camera:    │
│ deterministic camera   │   cameras     │ render float32 depth map   │
│ trajectory (exact)     │              │ from MetricPlan geometry     │
└────────────────────────┘              └──────────────┬──────────────┘
                                                       │ depth_maps[]
                                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ControlNet Depth-Conditioned Generation                  │
│                                                                       │
│  FLUX img2img:  blockout + depth ControlNet → Canon                  │
│  Multi-view:    depth[i] + ControlNet → view[i]                      │
│  Video:         depth[0] conditions frame 0; verify drift            │
│                                                                       │
│  Conditioning strength: configurable (default 0.8)                   │
│  Fallback: unconditioned generation if ControlNet unavailable        │
└────────────────────────────┬────────────────────────────────────────┘
                             │ generated views[]
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Geometry Validation Gate                                 │
│                                                                       │
│  For each generated view:                                            │
│    1. Run DA3 → estimated depth                                      │
│    2. Compare estimated vs conditioning depth                        │
│    3. PASS if: corr ≥ 0.7 AND MAE ≤ 0.5m AND SSIM ≥ 0.6           │
│    4. FAIL → re-generate with stronger conditioning (max 3 tries)    │
│                                                                       │
│  Role: QA gate. Does NOT override MetricPlan.                        │
│  Triggers re-roll on failure, never spatial correction.              │
└────────────────────────────┬────────────────────────────────────────┘
                             │ validated views[] + DA3 depth[]
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Dense Back-Projection (known poses)                      │
│                                                                       │
│  For each validated view:                                            │
│    P_world = R^T * (K^{-1} * [u,v,1]^T * depth - t)                │
│                                                                       │
│  Camera matrices: EXACT from CaptureManifest (not estimated)         │
│  Filter: depth 0.1–15m, DA3 confidence threshold                    │
│  Deduplicate: merge points within 2cm                                │
│                                                                       │
│  Output: dense fused point cloud (PLY)                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ fused point cloud
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Volumetric Mesh Reconstruction                           │
│                                                                       │
│  Method: TSDF fusion (Open3D) or Poisson (trimesh)                   │
│  Constraints: Y-up, meters, inward normals, 10K–250K verts          │
│  Texture: UV-project generated views using known cameras             │
│  Fallback: parametric room shell if reconstruction fails             │
│                                                                       │
│  Output: room_shell.glb (replaces flat-box shell)                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Inject geometry, don't extract it

**Decision:** MetricPlan renders depth maps that directly condition the AI generator. No geometry is ever extracted from AI-generated content.

**Rationale (from adversarial review):**
- AI video generators use latent-space interpolation, not pinhole camera simulation
- Essential matrix decomposition on AI frames yields poses corresponding to no physical reality
- Classical feature matchers (ORB/SIFT) fail catastrophically on AI textures
- Two independent hallucinations (SfM + DA3) of a non-existent scene do not produce meaningful correlation

**Consequence:** The entire SfM pipeline from the previous design (feature matching, pose estimation, triangulation) is eliminated. Camera poses are **declared**, not **estimated**.

### 2. Known poses eliminate the hardest problem in 3D reconstruction

**Decision:** All camera matrices are exact, deterministic, and derived from MetricPlan + CameraContract. There is no pose estimation step anywhere in the pipeline.

**Rationale:** The single hardest problem in multi-view reconstruction is accurate camera pose estimation. By declaring poses from the spatial authority (which we control), we skip this entirely. DA3's monocular depth — normally only useful as relative depth — becomes metrically useful when back-projected through exact known transforms because the scale ambiguity is resolved by the known camera baseline.

**Consequence:** DA3 depth goes from "non-authoritative evidence" to "dense geometry source" — not because DA3 gained authority, but because the known camera matrices provide the missing scale and alignment that DA3 alone cannot. The authority flows from MetricPlan (via known cameras), not from DA3.

### 3. Validation gate fails closed

**Decision:** If the generated image diverges from the conditioning depth, trigger re-generation — never override MetricPlan or accept divergent geometry.

**Rationale:** ControlNet conditioning is not a hard constraint — it's a soft bias in the diffusion process. The generator can (and sometimes does) ignore or partially follow conditioning. The validation gate catches these failures before downstream stages consume garbage geometry.

**Failure modes detected:**
- **Conditioning collapse** — ControlNet ignored entirely (correlation near 0)
- **Partial drift** — walls correct but furniture displaced (regional MAE spikes)
- **Conditioning bleed** — geometry correct but textures destroyed (visual quality failure, not geometry failure)

### 4. CapturePlanner survives but changes role

**Decision:** The CapturePlanner computes optimal camera positions from MetricPlan — same concept as before, but the cameras now serve two purposes: (1) render depth maps for conditioning, and (2) define the exact back-projection transforms for depth fusion.

**Previous role:** Compute cameras for "optimal stereo triangulation"
**New role:** Compute cameras for "maximum room coverage with known transforms for depth fusion"

The optimization criterion changes from "baseline-to-depth ratio for triangulation" to "surface coverage with minimum occlusion for back-projection completeness."

### 5. Existing infrastructure is reused, not rebuilt

**Decision:** The controlled-camera depth render already exists in `blockout_renderer.py`. The aux channel emission already writes depth beside Canon PNGs. The ControlNet depth nodes exist in ComfyUI. DA3 is already integrated. We're connecting existing capabilities, not building from scratch.

**Reused components:**
| Component | Already exists in | New role |
|---|---|---|
| Depth render from MetricPlan | `blockout_renderer.py` `_build_projector` | Conditioning input for ControlNet |
| Aux depth channel emission | `canon_generator.py` `emit_reference_aux_channels` | Provenance binding for conditioning |
| DA3 depth estimation | `depth_bridge.py` `UnifiedDepthEstimator` | Validation comparison + back-projection source |
| ComfyUI ControlNet | ComfyUI PaintShop install | Depth conditioning for FLUX |
| Camera intrinsics | `camera_contract.py` (60° vFOV, 1024×768) | Back-projection K matrix |
| trimesh | Already a dependency | Mesh export + Poisson reconstruction |

---

## Module Layout

```
tools/conditioning_spike/                # Research spike (Task 1-2)
├── __init__.py
├── conditioning_tester.py              # Req 8: test ControlNet fidelity
├── strength_sweep.py                   # Req 8: sweep conditioning strengths
└── run.py                              # CLI runner

src/unified_pipeline/                    # Production modules (Tasks 3-7)
├── capture_planner.py                  # Req 2: CapturePlanner + CaptureManifest (rewritten)
├── depth_sequence_renderer.py          # Req 1: render MetricPlan depth along trajectory
├── controlnet_conditioner.py           # Req 3: ControlNet depth conditioning for FLUX/MiniMax
├── geometry_validation_gate.py         # Req 4: DA3 vs conditioning comparison
├── depth_backprojector.py              # Req 5: back-project DA3 depth with known poses
├── volumetric_reconstructor.py         # Req 6: point cloud → mesh
└── multi_view_generator.py             # Modified: uses CapturePlanner + conditioning

tests/
├── test_capture_planner.py             # Req 2 unit tests
├── test_depth_sequence_renderer.py     # Req 1 unit tests
├── test_geometry_validation_gate.py    # Req 4 unit tests
├── test_depth_backprojector.py         # Req 5 unit tests
├── test_volumetric_reconstructor.py    # Req 6 unit tests
└── e2e/
    └── test_inject_validate_pipeline.py  # Req 7 integration tests
```

---

## Data Flow (Detailed)

### Phase 1: Plan + Render (deterministic, no GPU)

```
MetricPlan
    │ room_dimensions, walls, openings, placements
    ▼
CapturePlanner.plan()
    │ CaptureManifest: list of PlannedCamera (position, target, K, R, t)
    ▼
DepthSequenceRenderer.render_all(manifest, metric_plan)
    │ For each camera in manifest:
    │   project MetricPlan geometry → float32 depth map (1024×768)
    │   project MetricPlan geometry → float32 normal map
    │   bind: camera_hash + plan_revision
    ▼
Output: depth_maps[] + normal_maps[] + manifest (all deterministic)
```

### Phase 2: Conditioned Generation (GPU, ComfyUI)

```
depth_maps[i] + text_prompt + Art_Bible
    │
    ▼
ControlNetConditioner.generate(depth_map, prompt, strength=0.8)
    │ ComfyUI workflow:
    │   LoadImage(depth_map) → ControlNetApply(strength) →
    │   CLIPTextEncode(prompt) → KSampler → VAEDecode → SaveImage
    ▼
Output: generated_view[i] (PNG, 1024×768)
```

### Phase 3: Validation Gate (GPU, DA3)

```
generated_view[i] + conditioning_depth[i]
    │
    ▼
GeometryValidationGate.validate(view, conditioning_depth)
    │ 1. DA3(view) → estimated_depth
    │ 2. scale_align(estimated, conditioning) → aligned_depth
    │ 3. metrics = compare(aligned_depth, conditioning_depth)
    │    - pearson_r ≥ 0.7?
    │    - scale_aligned_MAE ≤ 0.5m?
    │    - depth_SSIM ≥ 0.6?
    │ 4. PASS or FAIL
    ▼
Output: ValidationResult(pass/fail, metrics, aligned_da3_depth)
```

### Phase 4: Back-Projection + Fusion (CPU, numpy)

```
For each validated view:
    aligned_da3_depth[i] + known_camera[i] (from manifest)
        │
        ▼
    DepthBackprojector.backproject(depth, K, R, t)
        │ For each valid pixel (u, v):
        │   ray = K^{-1} * [u, v, 1]^T
        │   P_camera = ray * depth[v, u]
        │   P_world = R^T * (P_camera - t)
        ▼
    point_cloud[i] (Nx3 + RGB from generated view)

All point_cloud[i]:
    │
    ▼
DepthBackprojector.fuse(clouds, merge_radius=0.02)
    │ Merge overlapping points within 2cm
    ▼
fused_cloud (Mx3 + RGB)
    │
    ▼
VolumetricReconstructor.reconstruct(fused_cloud)
    │ TSDF or Poisson → watertight mesh
    │ Filter bridge triangles (gradient > 0.5m)
    │ Orient normals inward
    │ Decimate to 10K–250K verts
    │ UV-project textures from generated views
    ▼
Output: room_shell.glb (replaces parametric box shell)
```

---

## Component Designs

### CapturePlanner (rewritten)

```python
@dataclass(frozen=True)
class PlannedCamera:
    """One camera in the planned trajectory with exact known transforms."""
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    extrinsic: np.ndarray      # 4×4 world-to-camera [R|t]
    intrinsic: np.ndarray      # 3×3 camera matrix K
    camera_type: str           # "hero" | "coverage" | "transition"
    label: str
    hash: str                  # SHA-256 of canonical serialization

@dataclass
class CaptureManifest:
    """Complete camera trajectory with exact known transforms."""
    cameras: list[PlannedCamera]
    room_dimensions: tuple[float, float, float]
    plan_revision_hash: str
    total_surface_coverage: float  # estimated fraction of room surfaces visible
```

**Planning algorithm:**
1. Hero camera: from CameraContract (unchanged)
2. Coverage cameras: one per wall not fully visible from hero. Position at room center, rotate to face each wall.
3. Transition cameras: interpolate between coverage views (for video conditioning continuity)
4. All cameras at eye height (1.62m or 60% ceiling height, whichever is lower)
5. Validate: all inside room with 0.3m clearance; clamp if needed
6. Compute exact K, R, t for each camera

### GeometryValidationGate

```python
@dataclass(frozen=True)
class ValidationResult:
    """Result of comparing generated geometry against conditioning."""
    passed: bool
    pearson_r: float           # depth correlation
    scale_aligned_mae_m: float # mean absolute error after scale alignment
    depth_ssim: float          # structural similarity of depth maps
    scale_factor: float        # optimal s: min ||s*estimated - conditioning||²
    coverage_fraction: float   # fraction of pixels with valid DA3 depth
    failure_reason: str = ""   # empty if passed

@dataclass
class ValidationConfig:
    min_correlation: float = 0.7
    max_mae_m: float = 0.5
    min_ssim: float = 0.6
    max_retries: int = 3
    strength_increment: float = 0.1
    max_strength: float = 1.0
```

### DepthBackprojector

```python
class DepthBackprojector:
    """Back-project depth maps into 3D using exact known camera matrices."""

    def backproject(
        self,
        depth_map: np.ndarray,       # float32 (H, W)
        intrinsic: np.ndarray,       # 3×3
        extrinsic: np.ndarray,       # 4×4 [R|t] world-to-camera
        rgb_image: np.ndarray = None,  # optional (H, W, 3) for coloring
        min_depth: float = 0.1,
        max_depth: float = 15.0,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Returns (Nx3 points, Nx3 colors or None)."""
        ...

    def fuse(
        self,
        clouds: list[np.ndarray],
        colors: list[np.ndarray | None],
        merge_radius_m: float = 0.02,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Merge overlapping points from multiple views."""
        ...
```

---

## Camera Intrinsics (from CameraContract)

```python
import math
import numpy as np

vfov_deg = 60.0
width, height = 1024, 768

fy = (height / 2) / math.tan(math.radians(vfov_deg) / 2)  # ≈ 665.1
fx = fy  # square pixels
cx = width / 2   # 512.0
cy = height / 2  # 384.0

K = np.array([
    [fx,  0, cx],
    [ 0, fy, cy],
    [ 0,  0,  1]
], dtype=np.float64)
```

---

## Failure Modes and Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| ControlNet nodes not installed in ComfyUI | Health check at pipeline start | Fall back to img2img with blockout (existing behavior) |
| ControlNet conditioning ignored (collapse) | Validation gate: correlation < 0.3 | Increase strength and retry (max 3×) |
| ControlNet strength too high (texture destruction) | Visual QA / Canon presence validation | Reduce strength by 0.1 |
| DA3 fails on generated image | < 50% valid pixels in DA3 output | Skip validation for that view; use conditioning depth directly |
| Back-projected point cloud too sparse | < 30% room surface coverage | Add more camera positions to manifest |
| Mesh reconstruction degenerate | < 10K vertices or non-manifold output | Fall back to parametric room shell |
| VRAM contention (ControlNet + DA3) | OOM exception | Sequential execution with VRAM release between stages |

---

## Dependencies

### Already Available (no new installs needed)

- `opencv-python` (cv2) — depth map manipulation, image I/O
- `numpy` — back-projection math, array operations
- `scipy` — SSIM computation, point cloud processing
- `trimesh` — mesh export, Poisson reconstruction fallback
- `Pillow` (PIL) — depth map visualization
- ComfyUI ControlNet nodes — depth conditioning (verify availability)

### May Need Installation

- `open3d` — TSDF volumetric fusion (preferred for multi-view fusion). If unavailable, fall back to trimesh Poisson.

### Not Needed (eliminated by architecture correction)

- ~~COLMAP~~ — no pose estimation
- ~~SuperPoint/SuperGlue/LoFTR~~ — no feature matching
- ~~SfM libraries~~ — no structure from motion
- ~~Optical flow~~ — no frame-to-frame correspondence

---

## Relationship to Scene Recovery Problem

This design implements several insights from the theoretical program:

| Scene Recovery Node | This Design's Implementation |
|---|---|
| B3 (gauge group + side information pricing) | Known camera matrices collapse the depth-scale gauge completely — one known baseline purchases metric depth from monocular estimation |
| F3 (certified metric scale) | Scale comes from MetricPlan via exact known cameras, not from estimation — certified by construction |
| G1 (a-posteriori certificate) | Validation gate is a weak G1: render conditioning vs DA3 comparison serves as a "does this image match the geometry?" check |
| E2 (amortized inversion with certificates) | DA3 is the amortized inverse; validation gate is the certificate; known cameras provide the missing guarantee |
| C3 (information budget) | Adding ControlNet conditioning is adding "prior strength" in the information budget sense — more prior → less ambiguity → better reconstruction |

The key insight: **you don't need to solve the Scene Recovery Problem if you control the generation process.** The difficulty of photo→3D comes from not knowing the camera, the scene, or the rendering process. When you own all three (MetricPlan owns scene, CameraContract owns camera, FLUX owns rendering), the "inversion" becomes trivial back-projection.

---

## What Changed From Previous Design

| Previous (f27e2ff) | This Design | Why |
|---|---|---|
| SfM pipeline (detect, match, decompose, triangulate) | Eliminated entirely | AI video lacks epipolar geometry |
| Pose estimation from correspondences | Known poses from CaptureManifest | No estimation needed when you declare the camera |
| CaptureSpec from empirical measurements | CaptureManifest from MetricPlan geometry | Parameters come from authority, not from measuring hallucinations |
| StereoDepthEvidence (non-authoritative) | Back-projected DA3 depth (authority from known cameras) | Authority flows from MetricPlan via exact cameras |
| 9 tasks (6 spike + 3 production) | 7 tasks (2 spike + 5 production) | Less research needed — the approach is well-understood |
| Classical feature matchers | None needed | No correspondence problem to solve |
| FLUX consistency measurement | Conditioning fidelity measurement | Right question: "did ControlNet hold?" not "do views agree?" |
