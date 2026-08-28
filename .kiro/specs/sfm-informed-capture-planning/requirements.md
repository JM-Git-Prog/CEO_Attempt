# Requirements Document — Geometry-Injected Capture Planning

## Introduction

This specification adds a geometry-injection and validation layer to the V2.0 unified world pipeline. The previous revision (commit `f27e2ff`) proposed extracting geometry from AI-generated video via classical SfM. Adversarial review (GLM-5.2 cloud, 2026-08-28) unanimously concluded that approach is mathematically invalid: AI video generators use latent-space interpolation, not pinhole camera simulation, so essential matrix decomposition yields poses corresponding to no physical reality.

**The corrected architecture inverts the flow:** instead of extracting geometry from hallucinated content, we **inject** MetricPlan's known geometry into the generation process via depth conditioning, then **validate** that the conditioning held in the output. The geometry flows downhill from authority to generation — never uphill from hallucination to evidence.

### Core Principles

1. **Inject, don't extract** — MetricPlan renders depth maps along a planned camera trajectory; these condition the AI generator directly. No SfM, no feature matching, no triangulation from AI content.
2. **MetricPlan remains sole spatial authority** — unchanged. The depth renders ARE MetricPlan's geometry, projected through known cameras.
3. **Known poses, not estimated poses** — camera matrices come from MetricPlan + CameraContract. There is no pose estimation step. Back-projection uses exact known transforms.
4. **Validation, not discovery** — the pipeline validates that ControlNet conditioning held (generation matches the injected depth), it does not discover new geometry.
5. **Fail closed** — if validation detects the generation diverged from the conditioning, trigger re-generation, not authority override.

### Why the Previous Architecture Was Wrong

| Previous (SfM-based) | Problem | Corrected (Inject-then-Validate) |
|---|---|---|
| Extract geometry from AI video | AI video has no real epipolar geometry | Inject geometry via ControlNet depth |
| Classical feature matching (ORB/SIFT) | Fails on AI textures (repetitive, shimmer) | No feature matching needed |
| Derive CaptureSpec from video measurements | Circular — measuring hallucinations to guide hallucinations | CaptureSpec = deterministic camera trajectory from MetricPlan |
| StereoDepthEvidence from triangulation | Triangulation of non-rigid hallucinated content = noise | Back-project DA3 depth using known camera matrices |
| Evidence denied by authority anyway | Wasted effort — output structurally discarded | Validation triggers re-roll on failure, not authority override |

### Relationship to Existing Specs

- **unified-world-pipeline** — This spec extends Phase 2 (Densify) with geometry-conditioned multi-view generation and adds a validation gate between generation and Phase 3 (Catalog).
- **depth_bridge.py authority model** — DA3 depth remains non-authoritative evidence. But back-projected with known poses, it becomes a dense mesh source (authority comes from the known camera matrices, not from DA3's output).
- **canon_generator.py aux channels** — The controlled-camera depth render from MetricPlan (already implemented in the aux channel emission) is exactly the depth map needed for ControlNet conditioning. This spec connects that existing capability to generation conditioning.
- **Scene Recovery Problem research** — This spec implements the B3 gauge-pricing insight: known camera geometry (from MetricPlan) collapses the depth-scale ambiguity completely, making monocular depth metrically useful without stereo.

### Environment Assumptions

- NVIDIA RTX 4090 (24GB VRAM), 96GB system RAM, Windows 11.
- ComfyUI on localhost:8188 with ControlNet depth models, FLUX, MiniMax H3, DA3.
- Existing `blockout_renderer.py` already renders depth from MetricPlan + CameraContract.
- Existing `canon_generator.py` already emits aux depth channels beside Canon PNG.
- OpenCV, numpy, scipy, trimesh already available.

---

## Requirements

### Requirement 1: MetricPlan Depth Sequence Rendering

**User Story:** As a developer, I want MetricPlan's geometry rendered as a sequence of depth maps along a planned camera trajectory, so that I have precise geometric conditioning for the AI generator.

#### Acceptance Criteria

1. THE system SHALL render float32 depth maps from MetricPlan geometry at each camera position in the CaptureManifest.
2. THE depth maps SHALL use the existing `blockout_renderer.py` projection pipeline (`_build_projector` closure) for deterministic, controlled-camera rendering.
3. EACH depth map SHALL be at the same resolution as the target generation (1024×768).
4. THE depth maps SHALL include all MetricPlan geometry: walls, floor, ceiling, openings (as voids), and object placement bounding boxes.
5. THE depth maps SHALL be bound to their camera matrix via SHA-256 hash for provenance.
6. THE system SHALL also render corresponding normal maps for optional ControlNet normal conditioning.

### Requirement 2: Camera Trajectory Planning from MetricPlan

**User Story:** As a developer, I want a deterministic camera trajectory computed from MetricPlan room dimensions, so that the generated multi-view set covers the room with known, exact camera poses.

#### Acceptance Criteria

1. THE `CapturePlanner` SHALL compute a deterministic camera trajectory from MetricPlan room dimensions + CameraContract hero view.
2. THE trajectory SHALL include: the hero view (unchanged from CameraContract), additional views covering all walls with ≥60% surface visibility, and transition frames between views for video generation.
3. ALL camera positions SHALL be inside the room with ≥0.3m clearance from walls.
4. ALL camera matrices SHALL be exact (not estimated) — position, rotation, and intrinsics are known to floating-point precision.
5. THE trajectory SHALL be deterministic: identical MetricPlan → identical trajectory.
6. THE `CaptureManifest` SHALL include for each camera: 4×4 extrinsic matrix, 3×3 intrinsic matrix, target generation resolution, and a stable hash.
7. THE planner SHALL adapt trajectory density to room size: more views for larger rooms, fewer for small rooms.

### Requirement 3: ControlNet Depth-Conditioned Generation

**User Story:** As a developer, I want the AI generator (FLUX/MiniMax H3) conditioned on MetricPlan depth maps via ControlNet, so that generated images are geometrically consistent with the spatial authority by construction.

#### Acceptance Criteria

1. THE system SHALL upload MetricPlan depth renders to ComfyUI and use them as ControlNet depth conditioning for FLUX image generation.
2. THE ControlNet conditioning strength SHALL be configurable (default: 0.7–0.9 range) to balance geometric fidelity against visual quality.
3. FOR video generation (MiniMax H3), THE system SHALL condition the first frame with MetricPlan depth and verify geometric drift across subsequent frames.
4. THE system SHALL support both single-view conditioning (hero Canon) and multi-view conditioning (full trajectory).
5. IF ControlNet depth nodes are unavailable in ComfyUI, THE system SHALL fall back to img2img conditioning with the blockout render (existing behavior) and log the degradation.
6. THE conditioning depth map SHALL be the same MetricPlan render used for aux channel emission — no separate depth computation.

### Requirement 4: Generation Geometry Validation Gate

**User Story:** As a developer, I want an automated gate that verifies generated images conform to the injected geometry, so that hallucinated divergence is caught before downstream stages consume it.

#### Acceptance Criteria

1. THE system SHALL run DA3 depth estimation on each generated view.
2. THE system SHALL compare DA3's estimated depth against the MetricPlan conditioning depth using: Pearson correlation, scale-aligned MAE, and structural similarity (SSIM on depth maps).
3. THE validation SHALL PASS if: correlation ≥ 0.7 AND scale-aligned MAE ≤ 0.5m AND depth SSIM ≥ 0.6.
4. THE validation SHALL FAIL if any threshold is violated, triggering: (a) log the failure with metrics, (b) increment re-generation counter, (c) re-generate with increased ControlNet strength (+0.1, capped at 1.0).
5. AFTER 3 consecutive failures, THE system SHALL fall back to the existing non-conditioned generation path and log a warning.
6. THE validation gate SHALL NOT carry spatial authority — it detects generation failures, it does not override MetricPlan.
7. VALIDATION metrics SHALL be recorded in the session artifacts for quality tracking.

### Requirement 5: Dense Depth Back-Projection with Known Poses

**User Story:** As a developer, I want DA3 depth maps back-projected into 3D using the exact known camera matrices, so that I get a dense point cloud without any pose estimation.

#### Acceptance Criteria

1. THE system SHALL back-project each validated DA3 depth map into 3D space using the exact camera intrinsics and extrinsics from the CaptureManifest.
2. THE back-projection SHALL use the standard pinhole model: `P_world = R^T * (K^{-1} * [u, v, 1]^T * depth - t)`.
3. THE system SHALL filter back-projected points: reject pixels with depth < 0.1m or > 15m, reject pixels where DA3 confidence is below threshold.
4. THE system SHALL fuse back-projected point clouds from multiple views into a unified dense point cloud using simple nearest-neighbor deduplication (merge points within 2cm).
5. THE fused point cloud SHALL be exportable as PLY for inspection.
6. THE back-projection step SHALL NOT estimate any camera parameters — all transforms come from the CaptureManifest's exact known matrices.

### Requirement 6: Volumetric Mesh Reconstruction

**User Story:** As a developer, I want the fused point cloud converted into a watertight mesh suitable for the walkable world, so that the room shell has actual depth-derived geometry rather than flat parametric boxes.

#### Acceptance Criteria

1. THE system SHALL reconstruct a mesh from the fused point cloud using either TSDF volumetric fusion (Open3D) or Poisson surface reconstruction (trimesh/Open3D).
2. THE mesh SHALL be oriented Y-up, meters, right-handed (matching CameraContract conventions).
3. THE mesh SHALL have inward-facing normals for correct interior rendering.
4. THE mesh vertex count SHALL be between 10,000 and 250,000 (matching Requirement 16 of unified-world-pipeline).
5. FACES with depth gradient > 0.5m between adjacent vertices SHALL be removed (no bridge triangles across depth discontinuities).
6. THE mesh SHALL be textured using the generated Canon/view images via UV projection from the known camera matrices.
7. IF reconstruction fails (insufficient coverage, degenerate geometry), THE system SHALL fall back to the existing parametric room shell.

### Requirement 7: Integration Without Authority Violation

**User Story:** As an architect, I want the geometry-injection pipeline integrated end-to-end without breaking "one truth per concern."

#### Acceptance Criteria

1. THE depth conditioning comes FROM MetricPlan (reading authority, not claiming it). MetricPlan is not modified.
2. THE camera matrices come FROM CameraContract + CapturePlanner (deterministic derivation, not estimation).
3. THE validation gate does NOT override MetricPlan — it triggers re-generation on failure, never spatial correction.
4. DA3 depth remains non-authoritative evidence — its back-projection is authoritative only because the camera matrices are exact (authority flows from known cameras, not from DA3).
5. THE system SHALL be backward-compatible: if ControlNet nodes are unavailable, fall back to existing unconditioned generation.
6. NO existing test SHALL break as a result of this integration.
7. THE reconstructed mesh replaces the parametric room shell in `_generate_room_shell` only when validation passes.

### Requirement 8: Conditioning Fidelity Measurement (Replaces SfM Spike)

**User Story:** As a developer, I want to measure how well ControlNet depth conditioning holds across different generation scenarios, so that I can tune conditioning strength and detect failure modes.

#### Acceptance Criteria

1. THE system SHALL measure conditioning fidelity: what fraction of MetricPlan's injected geometry survives in the generated output?
2. THE measurement SHALL be computed as: DA3(generated_image) vs MetricPlan_depth, using correlation, MAE, and per-region analysis (walls, floor, objects).
3. THE system SHALL test conditioning fidelity across: (a) different ControlNet strengths (0.5, 0.7, 0.9, 1.0), (b) different scene complexities (empty room vs furnished), (c) video vs single-image generation.
4. THE measurement results SHALL produce a recommended `conditioning_strength` value for the pipeline's default configuration.
5. THE system SHALL detect "conditioning collapse" (ControlNet ignored entirely) vs "conditioning bleed" (geometry correct but textures destroyed) as distinct failure modes.
6. THE measurement tool SHALL be runnable as a standalone CLI: `python -m tools.conditioning_spike.run --canon <path> --plan <path>`.
