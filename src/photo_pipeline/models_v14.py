"""V14 data models for the Photo-to-Real-3D-World pipeline.

All models use frozen dataclasses for immutability, extending the base
models in src/photo_pipeline/models.py. Includes field validation,
type annotations, and JSON serialization/deserialization helpers for
models requiring round-trip (AssetRegistryEntry, V14PipelineManifest).

Requirements: 1.6, 2.7, 3.1, 6.6, 7.2, 9.1, 15.1, 15.3
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.photo_pipeline.models import PhotoPipelineConfig, StageResult


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = ("props", "architecture", "foliage", "hard-surface", "set-dressing")
VALID_MATERIALS = ("wood", "metal", "glass", "fabric", "ceramic", "plastic")
VALID_CONDITIONS = ("new", "worn", "broken")
VALID_BODY_MODES = ("DYNAMIC", "STATIC")
VALID_MESH_METHODS = ("hunyuan3d_v2.1", "trellis2", "placeholder")
VALID_QUALITY_CLASSIFICATIONS = ("full", "degraded", "minimal")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class V14ValidationError(ValueError):
    """Raised when a V14 dataclass field fails validation."""


def _validate_non_negative(value: float, field_name: str) -> None:
    """Validate that a numeric value is non-negative."""
    if value < 0:
        raise V14ValidationError(f"{field_name} must be >= 0, got {value}")


def _validate_positive_int(value: int, field_name: str) -> None:
    """Validate that an integer value is positive."""
    if value < 1:
        raise V14ValidationError(f"{field_name} must be >= 1, got {value}")


def _validate_in_set(value: str, valid_set: tuple[str, ...], field_name: str) -> None:
    """Validate that a string value is in the allowed set."""
    if value not in valid_set:
        raise V14ValidationError(
            f"{field_name} must be one of {valid_set}, got '{value}'"
        )


def _validate_unit_range(value: float, field_name: str) -> None:
    """Validate that a float is in [0.0, 1.0]."""
    if value < 0.0 or value > 1.0:
        raise V14ValidationError(
            f"{field_name} must be in [0.0, 1.0], got {value}"
        )


def _validate_tuple_positive(
    value: tuple[float, ...], field_name: str
) -> None:
    """Validate all elements in a tuple are positive."""
    for i, v in enumerate(value):
        if v <= 0:
            raise V14ValidationError(
                f"{field_name}[{i}] must be > 0, got {v}"
            )


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V14PipelineConfig(PhotoPipelineConfig):
    """Extended config for V14 pipeline.

    Adds Hunyuan3D 2.1, Trellis2, Depth Anything 3, VRAM management,
    two-pass material, and asset warehouse settings.
    """

    hunyuan3d_steps: int = 50
    hunyuan3d_cfg: float = 7.0
    hunyuan3d_octree_resolution: int = 384
    hunyuan3d_stall_timeout_s: int = 180
    trellis2_steps: int = 18
    trellis2_target_triangles: int = 12000
    depth_model: str = "depth_anything_3"
    vram_free_target_gb: float = 4.0
    system_ram_pause_gb: float = 80.0
    system_ram_resume_gb: float = 72.0
    pass2_enabled: bool = True
    asset_warehouse_enabled: bool = True
    min_mesh_faces: int = 100
    min_mesh_vertices: int = 50

    def __post_init__(self) -> None:
        if self.hunyuan3d_steps < 1:
            raise V14ValidationError(
                f"hunyuan3d_steps must be >= 1, got {self.hunyuan3d_steps}"
            )
        if self.hunyuan3d_cfg <= 0:
            raise V14ValidationError(
                f"hunyuan3d_cfg must be > 0, got {self.hunyuan3d_cfg}"
            )
        if self.hunyuan3d_octree_resolution < 1:
            raise V14ValidationError(
                f"hunyuan3d_octree_resolution must be >= 1, got {self.hunyuan3d_octree_resolution}"
            )
        if self.hunyuan3d_stall_timeout_s < 1:
            raise V14ValidationError(
                f"hunyuan3d_stall_timeout_s must be >= 1, got {self.hunyuan3d_stall_timeout_s}"
            )
        if self.trellis2_steps < 1:
            raise V14ValidationError(
                f"trellis2_steps must be >= 1, got {self.trellis2_steps}"
            )
        if self.trellis2_target_triangles < 1:
            raise V14ValidationError(
                f"trellis2_target_triangles must be >= 1, got {self.trellis2_target_triangles}"
            )
        if self.vram_free_target_gb < 0:
            raise V14ValidationError(
                f"vram_free_target_gb must be >= 0, got {self.vram_free_target_gb}"
            )
        if self.system_ram_resume_gb >= self.system_ram_pause_gb:
            raise V14ValidationError(
                f"system_ram_resume_gb ({self.system_ram_resume_gb}) must be < "
                f"system_ram_pause_gb ({self.system_ram_pause_gb})"
            )
        if self.min_mesh_faces < 1:
            raise V14ValidationError(
                f"min_mesh_faces must be >= 1, got {self.min_mesh_faces}"
            )
        if self.min_mesh_vertices < 1:
            raise V14ValidationError(
                f"min_mesh_vertices must be >= 1, got {self.min_mesh_vertices}"
            )


@dataclass(frozen=True)
class VRAMState:
    """Current VRAM state snapshot for the VRAM Manager."""

    current_model: str | None
    estimated_usage_gb: float
    system_ram_gb: float

    def __post_init__(self) -> None:
        _validate_non_negative(self.estimated_usage_gb, "estimated_usage_gb")
        _validate_non_negative(self.system_ram_gb, "system_ram_gb")


@dataclass(frozen=True)
class SemanticLabel:
    """Semantic label assigned to an object by Ollama vision analysis.

    Contains the human-readable label, material, category, era, condition,
    and whether the object has architectural function.
    """

    semantic_label: str
    primary_material: str
    category: str
    estimated_era: str
    condition: str
    is_architectural: bool

    def __post_init__(self) -> None:
        if not self.semantic_label:
            raise V14ValidationError("semantic_label must not be empty")
        _validate_in_set(self.primary_material, VALID_MATERIALS, "primary_material")
        _validate_in_set(self.category, VALID_CATEGORIES, "category")
        if not self.estimated_era:
            raise V14ValidationError("estimated_era must not be empty")
        _validate_in_set(self.condition, VALID_CONDITIONS, "condition")


@dataclass(frozen=True)
class PhysicsClassification:
    """Physics classification result for a single object.

    Determines whether an object is dynamic (grabbable/pushable) or
    static (immovable) based on estimated mass and material density.
    """

    body_mode: str
    mass_kg: float
    volume_m3: float
    material_density: float
    friction: float
    restitution: float
    can_topple: bool
    override_reason: str | None

    def __post_init__(self) -> None:
        _validate_in_set(self.body_mode, VALID_BODY_MODES, "body_mode")
        _validate_non_negative(self.mass_kg, "mass_kg")
        _validate_non_negative(self.volume_m3, "volume_m3")
        _validate_non_negative(self.material_density, "material_density")
        _validate_non_negative(self.friction, "friction")
        _validate_non_negative(self.restitution, "restitution")


@dataclass(frozen=True)
class MaterialPassResult:
    """Result of a single material processing pass for an object."""

    object_id: str
    pass_number: int
    has_base_color: bool
    has_metallic_roughness: bool
    has_normal_map: bool
    texture_resolution: tuple[int, int]

    def __post_init__(self) -> None:
        if not self.object_id:
            raise V14ValidationError("object_id must not be empty")
        if self.pass_number not in (1, 2):
            raise V14ValidationError(
                f"pass_number must be 1 or 2, got {self.pass_number}"
            )
        if self.texture_resolution[0] < 1 or self.texture_resolution[1] < 1:
            raise V14ValidationError(
                f"texture_resolution dimensions must be >= 1, got {self.texture_resolution}"
            )


@dataclass(frozen=True)
class ObjectMeshResult:
    """Result of 3D mesh generation for a single segmented object (V14).

    Records the output GLB path, mask identity, which generation method
    succeeded, the time taken, mesh statistics, and whether textures are present.
    """

    mesh_path: Path
    mask_id: str
    generation_method: str  # hunyuan3d_v2.1 / trellis2 / placeholder
    generation_time_s: float
    face_count: int
    vertex_count: int
    has_texture: bool

    def __post_init__(self) -> None:
        if not self.mask_id:
            raise V14ValidationError("mask_id must not be empty")
        _validate_in_set(self.generation_method, VALID_MESH_METHODS, "generation_method")
        _validate_non_negative(self.generation_time_s, "generation_time_s")
        _validate_positive_int(self.face_count, "face_count")
        _validate_positive_int(self.vertex_count, "vertex_count")


@dataclass(frozen=True)
class RoomShellResult:
    """Result of room shell reconstruction from depth map.

    Records the GLB mesh path, room dimensions, mesh statistics,
    grid resolution used, faces removed at depth discontinuities,
    and whether the flat-box fallback was triggered.
    """

    mesh_path: Path
    dimensions_m: tuple[float, float, float]
    vertex_count: int
    face_count: int
    grid_resolution: tuple[int, int]
    faces_removed_gradient: int
    used_fallback: bool

    def __post_init__(self) -> None:
        _validate_tuple_positive(self.dimensions_m, "dimensions_m")
        _validate_positive_int(self.vertex_count, "vertex_count")
        _validate_positive_int(self.face_count, "face_count")
        if self.grid_resolution[0] < 1 or self.grid_resolution[1] < 1:
            raise V14ValidationError(
                f"grid_resolution must have positive dims, got {self.grid_resolution}"
            )
        _validate_non_negative(
            float(self.faces_removed_gradient), "faces_removed_gradient"
        )


@dataclass(frozen=True)
class V14ObjectEntry:
    """Extended object manifest entry for V14.

    Aggregates all V14-specific per-object results including mesh generation,
    semantic labeling, physics classification, material passes, and
    asset warehouse cataloging.
    """

    mask_id: str
    semantic_label: SemanticLabel
    mesh_path: Path
    mesh_method: str  # hunyuan3d_v2.1 / trellis2 / placeholder
    mesh_generation_time_s: float
    face_count: int
    vertex_count: int
    dimensions_m: tuple[float, float, float]
    position_m: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    physics: PhysicsClassification
    material_pass1: MaterialPassResult
    material_pass2: MaterialPassResult | None
    asset_warehouse_path: Path | None
    asset_registry_id: str | None

    def __post_init__(self) -> None:
        if not self.mask_id:
            raise V14ValidationError("mask_id must not be empty")
        _validate_in_set(self.mesh_method, VALID_MESH_METHODS, "mesh_method")
        _validate_non_negative(self.mesh_generation_time_s, "mesh_generation_time_s")
        _validate_positive_int(self.face_count, "face_count")
        _validate_positive_int(self.vertex_count, "vertex_count")


@dataclass(frozen=True)
class V14PipelineManifest:
    """Complete manifest for a V14 pipeline run.

    Records session identity, all stage results, room shell, per-object
    entries, depth model, quality classification, timing, and WorldContract path.
    Supports JSON round-trip serialization via to_dict()/from_dict().
    """

    session_id: str
    source_image_path: Path
    source_image_hash: str  # SHA-256
    interface_version: int  # 14
    stages: list[StageResult]
    room_shell: RoomShellResult
    objects: list[V14ObjectEntry]
    depth_model_used: str
    quality_classification: str  # full / degraded / minimal
    total_duration_s: float
    world_contract_path: Path | None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise V14ValidationError("session_id must not be empty")
        if not self.source_image_hash:
            raise V14ValidationError("source_image_hash must not be empty")
        if self.interface_version != 14:
            raise V14ValidationError(
                f"interface_version must be 14, got {self.interface_version}"
            )
        _validate_in_set(
            self.quality_classification,
            VALID_QUALITY_CLASSIFICATIONS,
            "quality_classification",
        )
        _validate_non_negative(self.total_duration_s, "total_duration_s")

    def to_dict(self) -> dict[str, Any]:
        """Serialize manifest to a JSON-compatible dictionary."""
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> V14PipelineManifest:
        """Deserialize manifest from a JSON-compatible dictionary."""
        return _reconstruct_v14_manifest(data)

    def to_json(self) -> str:
        """Serialize to canonical JSON string (sorted keys, 2-space indent, UTF-8)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> V14PipelineManifest:
        """Deserialize from JSON string."""
        data = json.loads(text)
        return cls.from_dict(data)


@dataclass(frozen=True)
class AssetRegistryEntry:
    """Metadata record for a single asset in the Asset Warehouse.

    Supports JSON round-trip serialization via to_dict()/from_dict().
    """

    name: str
    semantic_label: str
    category: str  # props/architecture/foliage/hard-surface/set-dressing
    era: str
    condition: str  # new/worn/broken
    working_status: str
    material_type: str
    dimensions_m: tuple[float, float, float]
    weight_estimate_kg: float
    generation_method: str  # hunyuan3d_v2.1 / trellis2
    source_photo_hash: str  # SHA-256
    source_session_id: str
    face_count: int
    vertex_count: int
    has_pbr_textures: bool
    created_at: str  # ISO timestamp

    def __post_init__(self) -> None:
        if not self.name:
            raise V14ValidationError("name must not be empty")
        if not self.semantic_label:
            raise V14ValidationError("semantic_label must not be empty")
        _validate_in_set(self.category, VALID_CATEGORIES, "category")
        _validate_in_set(self.condition, VALID_CONDITIONS, "condition")
        _validate_in_set(
            self.material_type, VALID_MATERIALS, "material_type"
        )
        _validate_non_negative(self.weight_estimate_kg, "weight_estimate_kg")
        if self.generation_method not in ("hunyuan3d_v2.1", "trellis2"):
            raise V14ValidationError(
                f"generation_method must be 'hunyuan3d_v2.1' or 'trellis2', "
                f"got '{self.generation_method}'"
            )
        if not self.source_photo_hash:
            raise V14ValidationError("source_photo_hash must not be empty")
        if not self.source_session_id:
            raise V14ValidationError("source_session_id must not be empty")
        _validate_positive_int(self.face_count, "face_count")
        _validate_positive_int(self.vertex_count, "vertex_count")
        if not self.created_at:
            raise V14ValidationError("created_at must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetRegistryEntry:
        """Deserialize from a JSON-compatible dictionary."""
        return cls(
            name=data["name"],
            semantic_label=data["semantic_label"],
            category=data["category"],
            era=data["era"],
            condition=data["condition"],
            working_status=data["working_status"],
            material_type=data["material_type"],
            dimensions_m=tuple(data["dimensions_m"]),
            weight_estimate_kg=data["weight_estimate_kg"],
            generation_method=data["generation_method"],
            source_photo_hash=data["source_photo_hash"],
            source_session_id=data["source_session_id"],
            face_count=data["face_count"],
            vertex_count=data["vertex_count"],
            has_pbr_textures=data["has_pbr_textures"],
            created_at=data["created_at"],
        )

    def to_json(self) -> str:
        """Serialize to canonical JSON string (sorted keys, 2-space indent, UTF-8)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> AssetRegistryEntry:
        """Deserialize from JSON string."""
        data = json.loads(text)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert a frozen dataclass to a JSON-compatible dict.

    Handles Path → posix string, tuple → list, nested dataclasses,
    None values, and primitive types.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = _dataclass_to_dict(value)
        return result
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, tuple):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _dataclass_to_dict(v) for k, v in obj.items()}
    # Primitives: str, int, float, bool, None
    return obj


def _reconstruct_v14_manifest(data: dict[str, Any]) -> V14PipelineManifest:
    """Reconstruct a V14PipelineManifest from a deserialized dictionary."""
    stages = [
        StageResult(
            stage_name=s["stage_name"],
            success=s["success"],
            duration_s=s["duration_s"],
            reason_code=s["reason_code"],
            diagnostics=s["diagnostics"],
            artifacts={k: Path(v) for k, v in s["artifacts"].items()},
            fallback_used=s.get("fallback_used"),
        )
        for s in data["stages"]
    ]

    room_shell = RoomShellResult(
        mesh_path=Path(data["room_shell"]["mesh_path"]),
        dimensions_m=tuple(data["room_shell"]["dimensions_m"]),
        vertex_count=data["room_shell"]["vertex_count"],
        face_count=data["room_shell"]["face_count"],
        grid_resolution=tuple(data["room_shell"]["grid_resolution"]),
        faces_removed_gradient=data["room_shell"]["faces_removed_gradient"],
        used_fallback=data["room_shell"]["used_fallback"],
    )

    objects = [_reconstruct_v14_object_entry(o) for o in data["objects"]]

    world_contract_path = (
        Path(data["world_contract_path"])
        if data.get("world_contract_path") is not None
        else None
    )

    return V14PipelineManifest(
        session_id=data["session_id"],
        source_image_path=Path(data["source_image_path"]),
        source_image_hash=data["source_image_hash"],
        interface_version=data["interface_version"],
        stages=stages,
        room_shell=room_shell,
        objects=objects,
        depth_model_used=data["depth_model_used"],
        quality_classification=data["quality_classification"],
        total_duration_s=data["total_duration_s"],
        world_contract_path=world_contract_path,
    )


def _reconstruct_v14_object_entry(data: dict[str, Any]) -> V14ObjectEntry:
    """Reconstruct a V14ObjectEntry from a deserialized dictionary."""
    semantic_label = SemanticLabel(
        semantic_label=data["semantic_label"]["semantic_label"],
        primary_material=data["semantic_label"]["primary_material"],
        category=data["semantic_label"]["category"],
        estimated_era=data["semantic_label"]["estimated_era"],
        condition=data["semantic_label"]["condition"],
        is_architectural=data["semantic_label"]["is_architectural"],
    )

    physics = PhysicsClassification(
        body_mode=data["physics"]["body_mode"],
        mass_kg=data["physics"]["mass_kg"],
        volume_m3=data["physics"]["volume_m3"],
        material_density=data["physics"]["material_density"],
        friction=data["physics"]["friction"],
        restitution=data["physics"]["restitution"],
        can_topple=data["physics"]["can_topple"],
        override_reason=data["physics"].get("override_reason"),
    )

    material_pass1 = _reconstruct_material_pass(data["material_pass1"])
    material_pass2 = (
        _reconstruct_material_pass(data["material_pass2"])
        if data.get("material_pass2") is not None
        else None
    )

    asset_warehouse_path = (
        Path(data["asset_warehouse_path"])
        if data.get("asset_warehouse_path") is not None
        else None
    )

    return V14ObjectEntry(
        mask_id=data["mask_id"],
        semantic_label=semantic_label,
        mesh_path=Path(data["mesh_path"]),
        mesh_method=data["mesh_method"],
        mesh_generation_time_s=data["mesh_generation_time_s"],
        face_count=data["face_count"],
        vertex_count=data["vertex_count"],
        dimensions_m=tuple(data["dimensions_m"]),
        position_m=tuple(data["position_m"]),
        rotation_deg=tuple(data["rotation_deg"]),
        physics=physics,
        material_pass1=material_pass1,
        material_pass2=material_pass2,
        asset_warehouse_path=asset_warehouse_path,
        asset_registry_id=data.get("asset_registry_id"),
    )


def _reconstruct_material_pass(data: dict[str, Any]) -> MaterialPassResult:
    """Reconstruct a MaterialPassResult from a deserialized dictionary."""
    return MaterialPassResult(
        object_id=data["object_id"],
        pass_number=data["pass_number"],
        has_base_color=data["has_base_color"],
        has_metallic_roughness=data["has_metallic_roughness"],
        has_normal_map=data["has_normal_map"],
        texture_resolution=tuple(data["texture_resolution"]),
    )
