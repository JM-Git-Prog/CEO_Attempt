"""Unified World Pipeline data models.

All models are frozen dataclasses (immutable after creation) with
to_dict() / from_dict() for JSON round-trip serialization.

Requirements: 2.1, 2.2, 2.3, 2.4, 19.1, 29.2
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


def _new_uuid() -> str:
    """Generate a stable UUID4 string."""
    return str(uuid.uuid4())


# ─── Sub-structures for Brief ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Atmosphere:
    """Brief atmosphere: mood + lighting_direction + time_of_day."""

    mood: str = ""
    lighting_direction: str = ""
    time_of_day: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Atmosphere:
        return cls(
            mood=data.get("mood", ""),
            lighting_direction=data.get("lighting_direction", ""),
            time_of_day=data.get("time_of_day", ""),
        )


@dataclass(frozen=True)
class Era:
    """Brief era: period + style_exclusions."""

    period: str = ""
    style_exclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["style_exclusions"] = list(self.style_exclusions)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Era:
        return cls(
            period=data.get("period", ""),
            style_exclusions=tuple(data.get("style_exclusions", ())),
        )


@dataclass(frozen=True)
class Palette:
    """Brief palette: primary + accent + material_finishes."""

    primary: str = ""
    accent: str = ""
    material_finishes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["material_finishes"] = list(self.material_finishes)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Palette:
        return cls(
            primary=data.get("primary", ""),
            accent=data.get("accent", ""),
            material_finishes=tuple(data.get("material_finishes", ())),
        )


@dataclass(frozen=True)
class ManifestObject:
    """One object in the Brief's object_manifest. Req 2.1, 2.2."""

    id: str = field(default_factory=_new_uuid)
    name: str = ""
    role: str = ""
    count: int = 1
    material_hint: str = ""
    is_architectural: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestObject:
        return cls(
            id=data.get("id", _new_uuid()),
            name=data.get("name", ""),
            role=data.get("role", ""),
            count=data.get("count", 1),
            material_hint=data.get("material_hint", ""),
            is_architectural=data.get("is_architectural", False),
        )


@dataclass(frozen=True)
class GameConcept:
    """Brief game_concept: theme + mechanics + scoring + win_condition."""

    theme: str = ""
    mechanics: str = ""
    scoring: str = ""
    win_condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameConcept:
        return cls(
            theme=data.get("theme", ""),
            mechanics=data.get("mechanics", ""),
            scoring=data.get("scoring", ""),
            win_condition=data.get("win_condition", ""),
        )


@dataclass(frozen=True)
class RealCapability:
    """One REAL capability binding. Req 2.1."""

    tool_type: str = ""
    surface_binding: str = ""
    read_only_v1: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RealCapability:
        return cls(
            tool_type=data.get("tool_type", ""),
            surface_binding=data.get("surface_binding", ""),
            read_only_v1=data.get("read_only_v1", True),
        )


# ─── Primary Models ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Brief:
    """Structured interpretation of user intent. Req 2.1, 2.2, 2.3, 2.4."""

    room_purpose: str = ""
    atmosphere: Atmosphere = field(default_factory=Atmosphere)
    era: Era = field(default_factory=Era)
    palette: Palette = field(default_factory=Palette)
    object_manifest: tuple[ManifestObject, ...] = ()
    game_concept: GameConcept = field(default_factory=GameConcept)
    real_capabilities: tuple[RealCapability, ...] = ()
    success_criteria: str = ""
    provenance: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_purpose": self.room_purpose,
            "atmosphere": self.atmosphere.to_dict(),
            "era": self.era.to_dict(),
            "palette": self.palette.to_dict(),
            "object_manifest": [o.to_dict() for o in self.object_manifest],
            "game_concept": self.game_concept.to_dict(),
            "real_capabilities": [r.to_dict() for r in self.real_capabilities],
            "success_criteria": self.success_criteria,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Brief:
        return cls(
            room_purpose=data.get("room_purpose", ""),
            atmosphere=Atmosphere.from_dict(data.get("atmosphere", {})),
            era=Era.from_dict(data.get("era", {})),
            palette=Palette.from_dict(data.get("palette", {})),
            object_manifest=tuple(
                ManifestObject.from_dict(o)
                for o in data.get("object_manifest", [])
            ),
            game_concept=GameConcept.from_dict(data.get("game_concept", {})),
            real_capabilities=tuple(
                RealCapability.from_dict(r)
                for r in data.get("real_capabilities", [])
            ),
            success_criteria=data.get("success_criteria", ""),
            provenance=dict(data.get("provenance", {})),
        )


@dataclass(frozen=True)
class ArtBible:
    """Style reference derived from Brief + Dream_Preview. Req 4.1, 4.2."""

    era_rules: dict[str, Any] = field(default_factory=dict)
    material_palette: tuple[str, ...] = ()
    lighting_direction: dict[str, Any] = field(default_factory=dict)
    color_palette: tuple[str, ...] = ()
    prop_style: dict[str, Any] = field(default_factory=dict)
    era_exclusions: tuple[str, ...] = ()
    immutable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "era_rules": dict(self.era_rules),
            "material_palette": list(self.material_palette),
            "lighting_direction": dict(self.lighting_direction),
            "color_palette": list(self.color_palette),
            "prop_style": dict(self.prop_style),
            "era_exclusions": list(self.era_exclusions),
            "immutable": self.immutable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtBible:
        return cls(
            era_rules=dict(data.get("era_rules", {})),
            material_palette=tuple(data.get("material_palette", ())),
            lighting_direction=dict(data.get("lighting_direction", {})),
            color_palette=tuple(data.get("color_palette", ())),
            prop_style=dict(data.get("prop_style", {})),
            era_exclusions=tuple(data.get("era_exclusions", ())),
            immutable=data.get("immutable", False),
        )


@dataclass(frozen=True)
class PlanRevision:
    """A single revision of the MetricPlan. Req 5.5."""

    revision: int = 1
    changed: str = ""
    reason: str = ""
    plan_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanRevision:
        return cls(
            revision=data.get("revision", 1),
            changed=data.get("changed", ""),
            reason=data.get("reason", ""),
            plan_hash=data.get("plan_hash", ""),
        )


@dataclass(frozen=True)
class MetricPlan:
    """Validated spatial layout. Req 5.1, 5.2, 5.6."""

    room_dimensions: tuple[float, float, float] = (4.0, 3.0, 2.7)
    walls: tuple[dict[str, Any], ...] = ()
    openings: tuple[dict[str, Any], ...] = ()
    object_placements: tuple[dict[str, Any], ...] = ()
    circulation_paths: tuple[dict[str, Any], ...] = ()
    relationships: tuple[dict[str, Any], ...] = ()
    revisions: tuple[PlanRevision, ...] = ()
    template_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_dimensions": list(self.room_dimensions),
            "walls": [dict(w) for w in self.walls],
            "openings": [dict(o) for o in self.openings],
            "object_placements": [dict(p) for p in self.object_placements],
            "circulation_paths": [dict(c) for c in self.circulation_paths],
            "relationships": [dict(r) for r in self.relationships],
            "revisions": [r.to_dict() for r in self.revisions],
            "template_id": self.template_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricPlan:
        return cls(
            room_dimensions=tuple(data.get("room_dimensions", (4.0, 3.0, 2.7))),
            walls=tuple(dict(w) for w in data.get("walls", [])),
            openings=tuple(dict(o) for o in data.get("openings", [])),
            object_placements=tuple(
                dict(p) for p in data.get("object_placements", [])
            ),
            circulation_paths=tuple(
                dict(c) for c in data.get("circulation_paths", [])
            ),
            relationships=tuple(
                dict(r) for r in data.get("relationships", [])
            ),
            revisions=tuple(
                PlanRevision.from_dict(r) for r in data.get("revisions", [])
            ),
            template_id=data.get("template_id", ""),
        )


@dataclass(frozen=True)
class CameraContract:
    """Immutable camera projection. Req 6.1, 6.2, 6.3, 6.4, 6.5."""

    position: tuple[float, float, float] = (0.0, 1.6, 3.0)
    target: tuple[float, float, float] = (0.0, 1.0, 0.0)
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    vfov: float = 60.0
    aspect: float = 1024.0 / 768.0
    near: float = 0.1
    far: float = 100.0
    raster_width: int = 1024
    raster_height: int = 768
    camera_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": list(self.position),
            "target": list(self.target),
            "up": list(self.up),
            "vfov": self.vfov,
            "aspect": self.aspect,
            "near": self.near,
            "far": self.far,
            "raster_width": self.raster_width,
            "raster_height": self.raster_height,
            "camera_hash": self.camera_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraContract:
        return cls(
            position=tuple(data.get("position", (0.0, 1.6, 3.0))),
            target=tuple(data.get("target", (0.0, 1.0, 0.0))),
            up=tuple(data.get("up", (0.0, 1.0, 0.0))),
            vfov=data.get("vfov", 60.0),
            aspect=data.get("aspect", 1024.0 / 768.0),
            near=data.get("near", 0.1),
            far=data.get("far", 100.0),
            raster_width=data.get("raster_width", 1024),
            raster_height=data.get("raster_height", 768),
            camera_hash=data.get("camera_hash", ""),
        )


@dataclass(frozen=True)
class BlockoutResult:
    """Result of blockout rendering from validated Plan. Req 7.1, 7.2."""

    image_path: str = ""
    plan_revision: int = 1
    camera_hash: str = ""
    approved: bool = False
    feedback: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlockoutResult:
        return cls(
            image_path=data.get("image_path", ""),
            plan_revision=data.get("plan_revision", 1),
            camera_hash=data.get("camera_hash", ""),
            approved=data.get("approved", False),
            feedback=data.get("feedback", ""),
        )


@dataclass(frozen=True)
class SceneCanon:
    """Approved photorealistic reference image. Req 8.1-8.7."""

    image_path: str = ""
    plan_revision: int = 1
    camera_hash: str = ""
    canon_hash: str = ""
    object_verdicts: dict[str, str] = field(default_factory=dict)
    approved: bool = False
    art_bible_hash: str = ""
    # ─── Auxiliary channel references (Req 2.1, 2.2) ──────────────────────
    # Path to the lossless EXR-style multi-channel container beside the PNG.
    # Empty when no controlled-camera aux emission occurred (backward compat).
    aux_channel_path: str = ""
    # Name of the depth channel in the aux container (default "Z" when present).
    depth_channel: str = ""
    # Name of the instance-ID channel in the aux container.
    instance_id_channel: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "plan_revision": self.plan_revision,
            "camera_hash": self.camera_hash,
            "canon_hash": self.canon_hash,
            "object_verdicts": dict(self.object_verdicts),
            "approved": self.approved,
            "art_bible_hash": self.art_bible_hash,
            "aux_channel_path": self.aux_channel_path,
            "depth_channel": self.depth_channel,
            "instance_id_channel": self.instance_id_channel,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SceneCanon:
        return cls(
            image_path=data.get("image_path", ""),
            plan_revision=data.get("plan_revision", 1),
            camera_hash=data.get("camera_hash", ""),
            canon_hash=data.get("canon_hash", ""),
            object_verdicts=dict(data.get("object_verdicts", {})),
            approved=data.get("approved", False),
            art_bible_hash=data.get("art_bible_hash", ""),
            aux_channel_path=data.get("aux_channel_path", ""),
            depth_channel=data.get("depth_channel", ""),
            instance_id_channel=data.get("instance_id_channel", ""),
        )


@dataclass(frozen=True)
class ObjectCanon:
    """Approved appearance reference for one object. Req 9.1-9.4."""

    object_id: str = ""
    object_name: str = ""
    image_path: str = ""
    mask_coverage: float = 0.0
    approved: bool = False
    provenance: str = "raw_segmentation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectCanon:
        return cls(
            object_id=data.get("object_id", ""),
            object_name=data.get("object_name", ""),
            image_path=data.get("image_path", ""),
            mask_coverage=data.get("mask_coverage", 0.0),
            approved=data.get("approved", False),
            provenance=data.get("provenance", "raw_segmentation"),
        )


@dataclass(frozen=True)
class MeshApproval:
    """Mesh shape approval record. Req 11.1-11.5."""

    object_id: str = ""
    mesh_path: str = ""
    generation_method: str = ""
    face_count: int = 0
    vertex_count: int = 0
    approved: bool = False
    rejection_reason: str = ""
    retry_count: int = 0
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeshApproval:
        return cls(
            object_id=data.get("object_id", ""),
            mesh_path=data.get("mesh_path", ""),
            generation_method=data.get("generation_method", ""),
            face_count=data.get("face_count", 0),
            vertex_count=data.get("vertex_count", 0),
            approved=data.get("approved", False),
            rejection_reason=data.get("rejection_reason", ""),
            retry_count=data.get("retry_count", 0),
            is_placeholder=data.get("is_placeholder", False),
        )


@dataclass(frozen=True)
class ObjectInstance:
    """One object instance in the WorldContract. Req 19.1."""

    object_id: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    asset_path: str = ""
    physics_intent: str = "static"
    material_intent: str = ""
    semantic_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "position": list(self.position),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
            "asset_path": self.asset_path,
            "physics_intent": self.physics_intent,
            "material_intent": self.material_intent,
            "semantic_label": self.semantic_label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectInstance:
        return cls(
            object_id=data.get("object_id", ""),
            position=tuple(data.get("position", (0.0, 0.0, 0.0))),
            rotation=tuple(data.get("rotation", (0.0, 0.0, 0.0))),
            scale=tuple(data.get("scale", (1.0, 1.0, 1.0))),
            asset_path=data.get("asset_path", ""),
            physics_intent=data.get("physics_intent", "static"),
            material_intent=data.get("material_intent", ""),
            semantic_label=data.get("semantic_label", ""),
        )


@dataclass(frozen=True)
class WorldContract:
    """Hash-bound engine-neutral contract. Req 19.1-19.6."""

    plan_revision: int = 1
    camera_hash: str = ""
    room_shell_ref: str = ""
    instances: tuple[ObjectInstance, ...] = ()
    lighting: dict[str, Any] = field(default_factory=dict)
    relationship_graph: dict[str, Any] = field(default_factory=dict)
    contract_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "camera_hash": self.camera_hash,
            "room_shell_ref": self.room_shell_ref,
            "instances": [i.to_dict() for i in self.instances],
            "lighting": dict(self.lighting),
            "relationship_graph": dict(self.relationship_graph),
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldContract:
        return cls(
            plan_revision=data.get("plan_revision", 1),
            camera_hash=data.get("camera_hash", ""),
            room_shell_ref=data.get("room_shell_ref", ""),
            instances=tuple(
                ObjectInstance.from_dict(i)
                for i in data.get("instances", [])
            ),
            lighting=dict(data.get("lighting", {})),
            relationship_graph=dict(data.get("relationship_graph", {})),
            contract_hash=data.get("contract_hash", ""),
        )


@dataclass(frozen=True)
class GameOverlay:
    """Per-room game behavior bindings. Req 23.1-23.3."""

    rules: str = ""
    scoring: str = ""
    win_condition: str = ""
    object_role_bindings: dict[str, str] = field(default_factory=dict)
    theme: str = ""
    mechanics: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": self.rules,
            "scoring": self.scoring,
            "win_condition": self.win_condition,
            "object_role_bindings": dict(self.object_role_bindings),
            "theme": self.theme,
            "mechanics": self.mechanics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameOverlay:
        return cls(
            rules=data.get("rules", ""),
            scoring=data.get("scoring", ""),
            win_condition=data.get("win_condition", ""),
            object_role_bindings=dict(
                data.get("object_role_bindings", {})
            ),
            theme=data.get("theme", ""),
            mechanics=data.get("mechanics", ""),
        )


@dataclass(frozen=True)
class RealOverlay:
    """Per-room REAL behavior bindings. Req 24.1-24.5."""

    tool_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_bindings": {
                k: dict(v) for k, v in self.tool_bindings.items()
            },
            "read_only": self.read_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RealOverlay:
        return cls(
            tool_bindings={
                k: dict(v)
                for k, v in data.get("tool_bindings", {}).items()
            },
            read_only=data.get("read_only", True),
        )


@dataclass(frozen=True)
class ModeState:
    """Per-room mode state. Req 25.1-25.5."""

    current_mode: str = "real"
    persisted: bool = True
    announced: bool = False
    room_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeState:
        return cls(
            current_mode=data.get("current_mode", "real"),
            persisted=data.get("persisted", True),
            announced=data.get("announced", False),
            room_id=data.get("room_id", ""),
        )


@dataclass(frozen=True)
class QualificationResult:
    """Qualification harness result. Req 30.1-30.6."""

    session_id: str = ""
    canonical_prompt: str = ""
    stages_passed: tuple[str, ...] = ()
    stages_failed: tuple[str, ...] = ()
    overall_pass: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "canonical_prompt": self.canonical_prompt,
            "stages_passed": list(self.stages_passed),
            "stages_failed": list(self.stages_failed),
            "overall_pass": self.overall_pass,
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualificationResult:
        return cls(
            session_id=data.get("session_id", ""),
            canonical_prompt=data.get("canonical_prompt", ""),
            stages_passed=tuple(data.get("stages_passed", ())),
            stages_failed=tuple(data.get("stages_failed", ())),
            overall_pass=data.get("overall_pass", False),
            diagnostics=dict(data.get("diagnostics", {})),
        )


@dataclass(frozen=True)
class ControlledCameraDepth:
    """Deterministic controlled-camera depth render from MetricPlan + CameraContract.

    This is a geometry echo — it carries no spatial authority and does NOT override
    MetricPlan spatial authority. It provides a per-pixel camera-space z-depth for
    deterministic unprojection of cutouts when the pipeline fully controls the camera.

    NOT monocular estimation. The monocular .npy path and FORBIDDEN_DEPTH_AUTHORITIES
    remain untouched.

    Requirements: 2.1, 3.3, 3.4
    """

    depth_map: Any = None  # np.ndarray float32 (height, width), np.inf = no geometry
    camera_hash: str = ""
    plan_revision: int = 1
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_hash": self.camera_hash,
            "plan_revision": self.plan_revision,
            "provenance": dict(self.provenance),
            "depth_map_shape": list(self.depth_map.shape) if self.depth_map is not None else [],
            "depth_map_dtype": str(self.depth_map.dtype) if self.depth_map is not None else "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ControlledCameraDepth:
        return cls(
            depth_map=None,  # depth_map must be loaded separately (binary data)
            camera_hash=data.get("camera_hash", ""),
            plan_revision=data.get("plan_revision", 1),
            provenance=dict(data.get("provenance", {})),
        )
