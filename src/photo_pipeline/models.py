"""Core data models for the photo-to-playable-world pipeline.

All models use frozen dataclasses for immutability, matching the project
convention established in src/upbge_runtime.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class PhotoPipelineConfig:
    """Pipeline-wide configuration with sensible defaults.

    Controls ComfyUI connectivity, object limits, timeouts, concurrency,
    LOD decimation ratios, and V-HACD decomposition parameters.
    """

    comfyui_url: str = "http://localhost:8188"
    max_objects: int = 30
    min_mask_area_pct: float = 0.5
    object_gen_timeout_s: int = 120
    physics_settle_iterations: int = 500
    physics_settle_timeout_s: float = 5.0
    gpu_concurrency: int = 2
    cpu_concurrency: int = 4
    pipeline_timeout_s: int = 1200  # 20 minutes
    vhacd_timeout_s: int = 30
    vhacd_max_hulls: int = 16
    vhacd_voxel_resolution: int = 10000
    lod_levels: tuple[float, ...] = (1.0, 0.5, 0.25, 0.1)


@dataclass(frozen=True)
class StageResult:
    """Outcome of a single pipeline stage execution.

    Captures timing, success/failure, reason code, diagnostic text,
    artifact paths, and whether a fallback was used.
    """

    stage_name: str
    success: bool
    duration_s: float
    reason_code: str
    diagnostics: str
    artifacts: dict[str, Path]
    fallback_used: str | None = None


@dataclass(frozen=True)
class SegmentedObject:
    """A single object extracted from scene segmentation.

    Stores the mask identity, bounding box, pixel area, centroid,
    and path to the isolated RGBA PNG.
    """

    mask_id: str
    bbox: tuple[int, int, int, int]  # x, y, width, height in pixels
    area_px: int
    centroid_px: tuple[float, float]  # x, y in pixels
    object_png_path: Path


@dataclass(frozen=True)
class SceneParseResult:
    """Result of the scene parsing stage (SAM segmentation + inpainting).

    Contains the path to the inpainted room plate, the list of segmented
    objects, and the combined background mask.
    """

    room_plate_path: Path
    objects: list[SegmentedObject]
    background_mask_path: Path


@dataclass(frozen=True)
class ObjectManifestEntry:
    """Full manifest record for a single segmented object across all stages.

    Aggregates results from segmentation, mesh generation, audio synthesis,
    scale calibration, layout estimation, physics settle, and collision/LOD.
    """

    mask_id: str
    bbox_px: tuple[int, int, int, int]
    area_px: int
    centroid_px: tuple[float, float]
    object_png_path: Path
    mesh_path: Path | None
    mesh_method: Literal["hunyuan3d", "unique3d", "triposr", "placeholder"] | None
    mesh_gen_time_s: float
    audio_path: Path | None
    audio_method: Literal["comfyui_audio", "sound_bank", "default"] | None
    material_category: str
    scale_m: tuple[float, float, float]
    scale_confidence: float
    position_m: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    settled: bool
    collision_method: Literal["vhacd", "convex_hull", "bounding_box"] | None
    lod_levels: int
    fallbacks_triggered: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineManifest:
    """Top-level manifest capturing the entire pipeline run.

    Records session identity, all stage results, per-object entries,
    quality classification, total duration, and final WorldContract path.
    """

    session_id: str
    source_image_path: Path
    stages: list[StageResult]
    objects: list[ObjectManifestEntry]
    quality_classification: Literal["full", "degraded", "minimal"]
    total_duration_s: float
    source_type: Literal["photo"] = "photo"
    world_contract_path: Path | None = None


@dataclass(frozen=True)
class ObjectMeshResult:
    """Result of 3D mesh generation for a single segmented object.

    Records the output GLB path, which generation method succeeded,
    the time taken, and mesh statistics (face/vertex counts).
    """

    mesh_path: Path  # GLB
    method_used: Literal["hunyuan3d", "unique3d", "triposr", "placeholder"]
    generation_time_s: float
    face_count: int
    vertex_count: int


@dataclass(frozen=True)
class AudioResult:
    """Result of audio synthesis for a single segmented object.

    Records the output WAV path, generation method used, audio duration,
    and estimated material category.
    """

    wav_path: Path
    method_used: Literal["comfyui_audio", "sound_bank", "default"]
    duration_s: float
    material_category: str  # wood, metal, glass, fabric, ceramic, plastic


@dataclass(frozen=True)
class DepthResult:
    """Result of the depth estimation stage (MoGe-2 metric depth).

    Contains paths to the saved depth map and normal map arrays,
    the ratio of valid (non-zero, non-infinite) pixels, and the
    min/max depth range of valid pixels in meters.
    """

    depth_map_path: Path  # .npy float32 array, meters
    normal_map_path: Path  # .npy float32 array, [H, W, 3]
    valid_pixel_ratio: float  # 0.0-1.0
    depth_range_m: tuple[float, float]  # min, max valid depth


@dataclass(frozen=True)
class RoomMeshResult:
    """Result of room mesh reconstruction from depth map and room plate.

    Contains the path to the GLB mesh, room dimensions in meters,
    vertex/face counts, and whether the heuristic fallback was used.
    """

    mesh_path: Path  # GLB
    dimensions_m: tuple[float, float, float]  # width, height, depth
    vertex_count: int
    face_count: int
    used_heuristic: bool  # True if flat-floor fallback was used


@dataclass(frozen=True)
class LightEstimateResult:
    """Result of the light estimation stage.

    Contains estimated primary light direction, color temperature, intensity,
    ambient parameters, and a confidence score indicating estimation quality.
    """

    sun_direction: tuple[float, float, float]  # normalized 3D vector (WorldContract coords)
    color_temperature_k: int  # 1800-12000
    intensity: float  # 0.0-100.0
    ambient_intensity: float  # 0.0-1.0
    ambient_color: str  # hex color
    confidence: float  # 0.0-1.0


@dataclass(frozen=True)
class PhotoSessionMetadata:
    """Session metadata extension for photo-pipeline sessions.

    Stored alongside the session to distinguish photo runs from text runs
    and to record pipeline-level summary statistics.
    """

    source_image_path: Path
    source_image_hash: str  # SHA-256
    source_resolution: tuple[int, int]
    quality_classification: Literal["full", "degraded", "minimal"]
    object_count: int
    primary_methods_succeeded: int
    fallbacks_used: int
    total_pipeline_duration_s: float
    source_type: Literal["photo"] = "photo"
