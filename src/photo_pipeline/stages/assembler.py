"""WorldContract Assembler — maps photo pipeline stage outputs to WorldContract.

This module assembles all per-object and per-scene stage outputs into a single
valid WorldContract instance, ready for export to UPBGE or other engines.

Key responsibilities:
- Map RoomMeshResult → RoomShell with dimensions and placeholder materials.
- Map each ObjectMeshResult → WorldInstance with stable ID, transform, dimensions.
- Assign physics intents (STATIC for heavy/architectural, DYNAMIC otherwise).
- Map LightEstimateResult → WorldLight entries (directional + ambient).
- Derive CameraBinding from estimated image parameters.
- Set ExportPolicy targets to include UPBGE_RUNTIME.
- Validate the final WorldContract passes all Pydantic validators.

Quality classification logic:
- "full": all objects used primary method (hunyuan3d)
- "degraded": ≥1 fallback method but ≥1 mesh exists
- "minimal": zero object meshes (room-only)
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Literal

from pydantic import ValidationError

from src.photo_pipeline.models import (
    LightEstimateResult,
    LayoutResult,
    ObjectManifestEntry,
    ObjectMeshResult,
    RoomMeshResult,
    ScaleResult,
)
from src.world_contract import (
    AppearanceIntent,
    BodyMode,
    CameraBinding,
    Dimensions,
    ExportPolicy,
    ExportTarget,
    MaterialIntent,
    PhysicsIntent,
    PhysicsPolicy,
    RoomShell,
    SourceBinding,
    Transform,
    Vector3,
    WorldContract,
    WorldInstance,
    WorldLight,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Material density heuristics (kg/m³)
# ---------------------------------------------------------------------------

MATERIAL_DENSITIES: dict[str, float] = {
    "wood": 600.0,
    "metal": 7800.0,
    "glass": 2500.0,
    "fabric": 200.0,
    "ceramic": 2300.0,
    "plastic": 950.0,
}

# Default density when material category is unknown
_DEFAULT_DENSITY_KG_M3 = 600.0

# Mass threshold for STATIC classification (kg)
_STATIC_MASS_THRESHOLD_KG = 50.0

# Placeholder SHA-256 hash (64 hex chars)
_PLACEHOLDER_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Quality classification
# ---------------------------------------------------------------------------


def classify_quality(
    objects: list[ObjectManifestEntry],
) -> Literal["full", "degraded", "minimal"]:
    """Classify pipeline output quality based on mesh generation methods.

    Args:
        objects: List of object manifest entries from the pipeline.

    Returns:
        "full" if all objects used the primary method (hunyuan3d).
        "degraded" if at least one fallback was used but meshes exist.
        "minimal" if zero object meshes were produced (room-only).
    """
    if not objects:
        return "minimal"

    objects_with_mesh = [obj for obj in objects if obj.mesh_path is not None]

    if not objects_with_mesh:
        return "minimal"

    all_primary = all(obj.mesh_method == "hunyuan3d" for obj in objects_with_mesh)

    if all_primary:
        return "full"

    return "degraded"


# ---------------------------------------------------------------------------
# Helper: mass estimation
# ---------------------------------------------------------------------------


def _estimate_mass_kg(
    dimensions_m: tuple[float, float, float],
    material_category: str,
) -> float:
    """Estimate object mass from dimensions and material density heuristic.

    volume = width × height × depth (in meters)
    mass = volume × density

    Args:
        dimensions_m: (width, height, depth) in meters.
        material_category: Material type string (wood, metal, glass, etc).

    Returns:
        Estimated mass in kilograms.
    """
    width, height, depth = dimensions_m
    volume_m3 = width * height * depth
    density = MATERIAL_DENSITIES.get(
        material_category.lower(), _DEFAULT_DENSITY_KG_M3
    )
    return volume_m3 * density


# ---------------------------------------------------------------------------
# Assembler class
# ---------------------------------------------------------------------------


class PhotoWorldContractAssembler:
    """Assembles photo pipeline outputs into a validated WorldContract.

    Usage:
        assembler = PhotoWorldContractAssembler(
            session_id="photo-session-001",
            room_mesh=room_mesh_result,
            objects=manifest_entries,
            light_estimate=light_estimate_result,
            image_width_px=1920,
            image_height_px=1080,
        )
        contract = assembler.assemble()
    """

    def __init__(
        self,
        *,
        session_id: str,
        room_mesh: RoomMeshResult,
        objects: list[ObjectManifestEntry] | None = None,
        light_estimate: LightEstimateResult | None = None,
        image_width_px: int = 1920,
        image_height_px: int = 1080,
        vertical_fov_deg: float = 60.0,
    ) -> None:
        self._session_id = session_id
        self._room_mesh = room_mesh
        self._objects = objects or []
        self._light_estimate = light_estimate
        self._image_width_px = image_width_px
        self._image_height_px = image_height_px
        self._vertical_fov_deg = vertical_fov_deg

    def assemble(self) -> WorldContract:
        """Assemble all stage outputs into a validated WorldContract.

        Returns:
            A fully validated WorldContract instance.

        Raises:
            ValueError: If the assembled contract fails Pydantic validation,
                with details about which field/constraint failed.
        """
        # Build materials first (room + per-object)
        materials = self._build_materials()
        material_ids = {m.id for m in materials}

        # Build room shell
        room = self._build_room_shell()

        # Build instances and physics intents
        instances = []
        physics_intents = []
        for obj in self._objects:
            if obj.mesh_path is None:
                continue  # Skip objects without meshes
            instance = self._build_instance(obj)
            physics_intent = self._build_physics_intent(obj, instance.id)
            instances.append(instance)
            physics_intents.append(physics_intent)

        # Build lights
        lights = self._build_lights()

        # Build camera
        camera = self._build_camera()

        # Build appearance
        appearance = AppearanceIntent(
            id="appearance-photo-pipeline",
            era="",
            mood="photorealistic",
            palette="",
            architecture_notes="Reconstructed from photograph",
            lighting_notes="Estimated from image analysis",
        )

        # Build source binding with placeholder hashes
        source = SourceBinding(
            session_id=self._session_id,
            interface_version=1,
            profile_id="photo-pipeline",
            plan_revision=0,
            plan_hash=_PLACEHOLDER_HASH,
            scene_graph_hash=_PLACEHOLDER_HASH,
            camera_contract_id="camera-photo-estimate",
            camera_contract_hash=_PLACEHOLDER_HASH,
            appearance_intent_hash=_PLACEHOLDER_HASH,
        )

        # Build export policy with UPBGE_RUNTIME target
        exports = ExportPolicy(
            targets=(ExportTarget.UPBGE_RUNTIME,),
        )

        # Build physics policy
        physics_policy = PhysicsPolicy(intents=tuple(physics_intents))

        # Assemble the contract
        try:
            contract = WorldContract(
                source=source,
                room=room,
                instances=tuple(instances),
                materials=tuple(materials),
                lights=tuple(lights),
                camera=camera,
                appearance=appearance,
                physics=physics_policy,
                exports=exports,
            )
        except ValidationError as exc:
            # Re-raise with field/constraint details
            errors = exc.errors()
            details = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in errors
            )
            raise ValueError(
                f"Assembled WorldContract failed validation: {details}"
            ) from exc

        return contract

    def _build_materials(self) -> list[MaterialIntent]:
        """Build material list: room materials + one per object."""
        materials = [
            MaterialIntent(id="material:room:floor", base_color="#8B7355", roughness=0.9),
            MaterialIntent(id="material:room:wall", base_color="#F5F5DC", roughness=0.7),
            MaterialIntent(id="material:room:ceiling", base_color="#FFFFFF", roughness=0.6),
        ]

        for obj in self._objects:
            if obj.mesh_path is None:
                continue
            material_id = f"material:instance:{obj.mask_id}"
            # Map material category to a base color heuristic
            color = _material_color(obj.material_category)
            materials.append(
                MaterialIntent(id=material_id, base_color=color, roughness=0.7)
            )

        return materials

    def _build_room_shell(self) -> RoomShell:
        """Map RoomMeshResult to RoomShell with dimensions and materials."""
        width, height, depth = self._room_mesh.dimensions_m
        return RoomShell(
            dimensions=Dimensions(
                width_m=width,
                height_m=height,
                depth_m=depth,
            ),
            floor_material_id="material:room:floor",
            wall_material_id="material:room:wall",
            ceiling_material_id="material:room:ceiling",
        )

    def _build_instance(self, obj: ObjectManifestEntry) -> WorldInstance:
        """Map an ObjectManifestEntry to a WorldInstance.

        Uses mask_id as stable ID, position/rotation from layout,
        dimensions from scale calibration. geometry_strategy is "asset"
        since we have generated meshes.
        """
        instance_id = f"obj:{obj.mask_id}"
        material_id = f"material:instance:{obj.mask_id}"
        physics_id = f"physics:instance:{obj.mask_id}"

        # Determine category based on material/size heuristics
        category = _infer_category(obj)

        # Build transform from layout result
        pos = obj.position_m
        rot = obj.rotation_deg

        # Build dimensions from scale calibration
        w, h, d = obj.scale_m

        # Asset registry ID from the mesh path — only set for real meshes
        # Placeholder meshes use geometry_strategy="primitive"
        has_real_mesh = (
            obj.mesh_path is not None
            and obj.mesh_method not in (None, "placeholder")
        )
        asset_id = f"asset:{obj.mask_id}" if has_real_mesh else None
        geometry_strategy = "asset" if has_real_mesh else "primitive"

        # Determine primitive shape for placeholder geometry
        primitive_shape: str | None = None
        if geometry_strategy == "primitive":
            # Map placeholder method info or default to box
            if w > 0 and h > 0:
                aspect = w / h
                if aspect < 0.5:
                    primitive_shape = "cylinder"
                elif h < 0.2 and w < 0.2 and d < 0.2:
                    primitive_shape = "sphere"
                else:
                    primitive_shape = "box"
            else:
                primitive_shape = "box"

        return WorldInstance(
            id=instance_id,
            name=f"object-{obj.mask_id}",
            category=category,
            mount="floor",
            transform=Transform(
                position_m=Vector3(x=pos[0], y=pos[1], z=pos[2]),
                rotation_deg=Vector3(x=rot[0], y=rot[1], z=rot[2]),
                scale=Vector3(x=1.0, y=1.0, z=1.0),
            ),
            dimensions=Dimensions(width_m=w, height_m=h, depth_m=d),
            material_id=material_id,
            physics_intent_id=physics_id,
            geometry_strategy=geometry_strategy,
            primitive_shape=primitive_shape,
            asset_registry_id=asset_id,
        )

    def _build_physics_intent(
        self, obj: ObjectManifestEntry, instance_id: str
    ) -> PhysicsIntent:
        """Assign physics mode based on mass and category.

        Rules:
        - mass > 50kg OR category "architectural" → STATIC (mass_kg=0)
        - mass ≤ 50kg AND not architectural → DYNAMIC with computed mass
        """
        physics_id = f"physics:instance:{obj.mask_id}"
        category = _infer_category(obj)
        mass = _estimate_mass_kg(obj.scale_m, obj.material_category)

        if mass > _STATIC_MASS_THRESHOLD_KG or category == "architectural":
            return PhysicsIntent(
                id=physics_id,
                subject_id=instance_id,
                body_mode=BodyMode.STATIC,
                collision_shape="mesh",
                mass_kg=0.0,
                friction=0.6,
                restitution=0.1,
                can_topple=False,
            )
        else:
            rounded_mass = round(mass, 3)
            return PhysicsIntent(
                id=physics_id,
                subject_id=instance_id,
                body_mode=BodyMode.DYNAMIC,
                collision_shape="mesh",
                mass_kg=rounded_mass if rounded_mass > 0 else 0.001,
                friction=0.5,
                restitution=0.2,
                can_topple=True,
            )

    def _build_lights(self) -> list[WorldLight]:
        """Map LightEstimateResult to WorldLight entries.

        Produces one directional light (sun) and one ambient point light.
        Falls back to neutral overhead lighting if no estimate is available.
        """
        if self._light_estimate is None:
            # Fallback: neutral overhead directional + ambient
            return [
                WorldLight(
                    id="light:sun",
                    name="Sun (fallback)",
                    light_type="directional",
                    position_m=Vector3(x=0.0, y=5.0, z=0.0),
                    direction=Vector3(x=0.0, y=-1.0, z=0.0),
                    color="#FFFFFF",
                    color_temperature_k=5500,
                    intensity=50.0,
                    range_m=100.0,
                    cast_shadows=True,
                ),
                WorldLight(
                    id="light:ambient",
                    name="Ambient (fallback)",
                    light_type="point",
                    position_m=Vector3(x=0.0, y=3.0, z=0.0),
                    direction=Vector3(x=0.0, y=-1.0, z=0.0),
                    color="#E8E8E8",
                    color_temperature_k=5000,
                    intensity=20.0,
                    range_m=50.0,
                    cast_shadows=False,
                ),
            ]

        est = self._light_estimate
        dx, dy, dz = est.sun_direction

        # Directional light from estimated sun
        directional = WorldLight(
            id="light:sun",
            name="Estimated Sun",
            light_type="directional",
            position_m=Vector3(x=0.0, y=5.0, z=0.0),
            direction=Vector3(x=dx, y=dy, z=dz),
            color=_kelvin_to_hex(est.color_temperature_k),
            color_temperature_k=max(1, est.color_temperature_k),
            intensity=est.intensity,
            range_m=100.0,
            cast_shadows=True,
        )

        # Ambient light
        ambient = WorldLight(
            id="light:ambient",
            name="Ambient Fill",
            light_type="point",
            position_m=Vector3(x=0.0, y=3.0, z=0.0),
            direction=Vector3(x=0.0, y=-1.0, z=0.0),
            color=est.ambient_color if est.ambient_color else "#E8E8E8",
            color_temperature_k=max(1, est.color_temperature_k),
            intensity=est.ambient_intensity * 100.0,  # Scale to WorldContract range
            range_m=50.0,
            cast_shadows=False,
        )

        return [directional, ambient]

    def _build_camera(self) -> CameraBinding:
        """Derive CameraBinding from source image estimated parameters.

        Assumes a default perspective camera positioned at the center of
        the room looking forward along -Z (into the scene).
        """
        # Position camera at typical human eye height, at the back of room
        room_depth = self._room_mesh.dimensions_m[2]
        camera_z = room_depth / 2.0 - 0.3  # slightly inside room boundary

        aspect = self._image_width_px / self._image_height_px

        return CameraBinding(
            id="camera-photo-source",
            source_schema_version="camera-binding/v1",
            projection="perspective",
            position_m=Vector3(x=0.0, y=1.6, z=camera_z),
            target_m=Vector3(x=0.0, y=1.2, z=0.0),
            up=Vector3(x=0.0, y=1.0, z=0.0),
            vertical_fov_deg=self._vertical_fov_deg,
            aspect_ratio=aspect,
            image_width_px=self._image_width_px,
            image_height_px=self._image_height_px,
            near_plane_m=0.1,
            far_plane_m=100.0,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _infer_category(
    obj: ObjectManifestEntry,
) -> Literal["furniture", "fixture", "architectural", "decor"]:
    """Infer instance category from material and size heuristics.

    Large heavy objects or those with structural materials are architectural.
    Medium objects are furniture, small objects are decor.
    """
    mass = _estimate_mass_kg(obj.scale_m, obj.material_category)
    volume = obj.scale_m[0] * obj.scale_m[1] * obj.scale_m[2]

    # Architectural: very heavy or large structural items
    if mass > 200.0 or (obj.material_category in ("ceramic", "metal") and volume > 1.0):
        return "architectural"

    # Furniture: medium-sized objects
    if volume > 0.01:
        return "furniture"

    # Decor: small objects
    return "decor"


def _material_color(material_category: str) -> str:
    """Map material category to a heuristic base color."""
    colors = {
        "wood": "#8B6914",
        "metal": "#808080",
        "glass": "#B0E0E6",
        "fabric": "#D2691E",
        "ceramic": "#F5F5DC",
        "plastic": "#4169E1",
    }
    return colors.get(material_category.lower(), "#808080")


def _kelvin_to_hex(kelvin: int) -> str:
    """Convert color temperature (Kelvin) to approximate hex color.

    Simple linear interpolation:
    - 2000K → warm orange (#FFA500)
    - 5500K → white (#FFFFFF)
    - 8000K → blue-white (#CCE5FF)
    """
    if kelvin <= 2000:
        return "#FFA500"
    elif kelvin >= 8000:
        return "#CCE5FF"
    elif kelvin <= 5500:
        # Interpolate from orange to white
        t = (kelvin - 2000) / 3500.0
        r = 255
        g = int(165 + t * 90)
        b = int(t * 255)
        return f"#{r:02X}{g:02X}{b:02X}"
    else:
        # Interpolate from white to blue-white
        t = (kelvin - 5500) / 2500.0
        r = int(255 - t * 51)
        g = int(255 - t * 26)
        b = 255
        return f"#{r:02X}{g:02X}{b:02X}"
