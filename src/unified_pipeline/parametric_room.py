"""Authoritative Plan-derived room adapter for Unified Pipeline Task 5.1.

The adapter validates the approved normalized MetricPlan, then delegates solid
room/opening construction to the existing deterministic compiler plan. Depth
geometry can only be attached as aligned, non-colliding appearance evidence.
Requirements: 16.1-16.7 as superseded by 31.1-31.7 and 32.1-32.4.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from src.unified_pipeline.approval_gates import ApprovalGate, ApprovalStatus
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.depth_bridge import DepthEvidence
from src.unified_pipeline.models import MetricPlan
from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
from src.unified_pipeline.plan_validator import (
    _compute_plan_hash,
    validate_plan_for_authority,
)
from src.upbge_compiler import CompilerOutputFlags, build_compiler_plan
from src.world_contract import (
    AppearanceIntent,
    CameraBinding,
    Dimensions,
    MaterialIntent,
    RoomShell,
    SourceBinding,
    Vector3,
    WorldContract as CompilerWorldContract,
    WorldOpening,
)

PLAN_AUTHORITY = "approved_normalized_metric_plan"
_SPATIAL_SCOPES = frozenset({
    "architecture", "architectural_geometry", "room_dimensions", "openings",
    "navigation", "navigation_geometry", "collision", "collision_geometry",
    "object_transforms", "camera",
})


class ParametricRoomError(ValueError):
    """Base error for fail-closed authoritative room construction."""


class PlanBindingError(ParametricRoomError):
    """Raised when Plan validation, normalization, or approval is not proven."""


class AuthorityConflictError(ParametricRoomError):
    """Raised when another source claims Plan-owned spatial authority."""


class DepthReferenceError(ParametricRoomError):
    """Raised when a depth mesh is not aligned, optional, and non-colliding."""


@dataclass(frozen=True)
class AuthorityClaim:
    source_id: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.scopes:
            raise AuthorityConflictError("authority claims require a source and scope")


@dataclass(frozen=True)
class AuthorityBinding:
    plan_revision: int
    plan_hash: str
    camera_hash: str
    spatial_authority: str = PLAN_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchitecturalElement:
    stable_id: str
    role: str
    shape: str
    position_upbge: tuple[float, float, float]
    dimensions_upbge: tuple[float, float, float]
    material_id: str
    static_collision: bool
    binding: AuthorityBinding
    metadata: tuple[tuple[str, str | bool | int | float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["binding"] = self.binding.to_dict()
        return payload


@dataclass(frozen=True)
class OpeningElement:
    stable_id: str
    kind: str
    wall: str
    position_upbge: tuple[float, float, float]
    dimensions_upbge: tuple[float, float, float]
    sill_height_m: float
    collision_enabled: bool
    binding: AuthorityBinding

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["binding"] = self.binding.to_dict()
        return payload


@dataclass(frozen=True)
class ArchitecturalCollision:
    stable_id: str
    geometry_id: str
    shape: str
    position_upbge: tuple[float, float, float]
    dimensions_upbge: tuple[float, float, float]
    body_mode: str
    binding: AuthorityBinding

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["binding"] = self.binding.to_dict()
        return payload


@dataclass(frozen=True)
class NavigableBounds:
    minimum_m: tuple[float, float, float]
    maximum_m: tuple[float, float, float]
    coordinate_system: str
    binding: AuthorityBinding

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["binding"] = self.binding.to_dict()
        return payload


@dataclass(frozen=True)
class DepthDerivedMesh:
    """Caller-provided depth mesh candidate; never an architecture source."""

    mesh_path: str
    evidence: DepthEvidence
    optional: bool = True
    collision_enabled: bool = False
    spatial_authority: bool = False
    authority_claims: tuple[str, ...] = ()
    label: str = "optional_aligned_depth_appearance_reference"

    def __post_init__(self) -> None:
        if not self.mesh_path.strip():
            raise DepthReferenceError("depth mesh path is required")
        if (
            not self.optional or self.collision_enabled or self.spatial_authority
            or self.authority_claims
        ):
            raise DepthReferenceError(
                "depth mesh must remain optional, non-colliding appearance evidence"
            )
        if self.label != "optional_aligned_depth_appearance_reference":
            raise DepthReferenceError("depth mesh must carry the honest reference label")


@dataclass(frozen=True)
class DepthAppearanceLayer:
    mesh_path: str
    mesh_sha256: str
    evidence_sha256: str
    alignment: dict[str, Any]
    label: str = "optional_aligned_depth_appearance_reference"
    optional: bool = True
    collision_enabled: bool = False
    spatial_authority: bool = False
    authority_claims: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParametricRoomResult:
    plan_revision: int
    plan_hash: str
    camera_hash: str
    compiler_input_hash: str
    elements: tuple[ArchitecturalElement, ...]
    openings: tuple[OpeningElement, ...]
    navigable_bounds: NavigableBounds
    collision: tuple[ArchitecturalCollision, ...]
    depth_reference: DepthAppearanceLayer | None = None
    spatial_authority: str = PLAN_AUTHORITY
    render_shell_path: str = ""
    render_shell_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "plan_hash": self.plan_hash,
            "camera_hash": self.camera_hash,
            "compiler_input_hash": self.compiler_input_hash,
            "elements": [item.to_dict() for item in self.elements],
            "openings": [item.to_dict() for item in self.openings],
            "navigable_bounds": self.navigable_bounds.to_dict(),
            "collision": [item.to_dict() for item in self.collision],
            "depth_reference": (
                self.depth_reference.to_dict() if self.depth_reference else None
            ),
            "spatial_authority": self.spatial_authority,
            "render_shell_path": self.render_shell_path,
            "render_shell_sha256": self.render_shell_sha256,
        }


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _revisionless(plan: MetricPlan) -> MetricPlan:
    return replace(plan, revisions=())


def _latest_hash_candidates(plan: MetricPlan) -> set[str]:
    candidates = {_compute_plan_hash(_revisionless(plan))}
    if plan.revisions:
        blank_latest = replace(plan.revisions[-1], plan_hash="")
        candidates.add(_compute_plan_hash(replace(plan, revisions=plan.revisions[:-1] + (blank_latest,))))
    return candidates


def _same_point(left: Any, right: Any) -> bool:
    try:
        return len(left) == len(right) and all(
            math.isclose(float(a), float(b), abs_tol=1e-9)
            for a, b in zip(left, right)
        )
    except (TypeError, ValueError):
        return False


def _validate_normalized_walls(plan: MetricPlan) -> None:
    expected = {
        item["id"]: item
        for item in _build_walls_from_dimensions(*plan.room_dimensions)
    }
    actual = {str(item.get("id", "")): item for item in plan.walls}
    if set(actual) != set(expected):
        raise PlanBindingError("normalized Plan must contain exactly four canonical walls")
    for wall_id, canonical in expected.items():
        wall = actual[wall_id]
        if (
            not _same_point(wall.get("start"), canonical["start"])
            or not _same_point(wall.get("end"), canonical["end"])
            or not math.isclose(
                float(wall.get("height", -1.0)), float(canonical["height"]), abs_tol=1e-9
            )
        ):
            raise PlanBindingError(
                f"wall {wall_id!r} is not normalized to approved room dimensions"
            )


def _validate_opening(opening: dict[str, Any], index: int) -> None:
    kind = opening.get("type", opening.get("kind"))
    wall = opening.get("wall")
    parameter = opening.get("parameter")
    if kind not in {"door", "window"} or wall not in {"north", "south", "east", "west"}:
        raise PlanBindingError(f"opening {index} has invalid normalized type or wall")
    if isinstance(parameter, bool) or not isinstance(parameter, (int, float)):
        raise PlanBindingError(f"opening {index} requires normalized parameter 0..1")
    if not math.isfinite(float(parameter)) or not 0.0 <= float(parameter) <= 1.0:
        raise PlanBindingError(f"opening {index} parameter is outside 0..1")


def _opening_models(plan: MetricPlan) -> tuple[WorldOpening, ...]:
    width, depth, _ = plan.room_dimensions
    kind_counts = {"door": 0, "window": 0}
    result: list[WorldOpening] = []
    seen: set[str] = set()
    for index, raw in enumerate(plan.openings):
        opening = dict(raw)
        _validate_opening(opening, index)
        kind = str(opening.get("type", opening.get("kind")))
        wall = str(opening["wall"])
        stable_id = str(opening.get("id") or f"{kind}_{kind_counts[kind]}")
        kind_counts[kind] += 1
        if stable_id in seen:
            raise PlanBindingError(f"duplicate opening identity {stable_id!r}")
        seen.add(stable_id)
        wall_length = width if wall in {"north", "south"} else depth
        result.append(WorldOpening(
            id=stable_id,
            kind=kind,
            wall=wall,
            offset_m=(float(opening["parameter"]) - 0.5) * wall_length,
            width_m=float(opening.get("width", 0.9)),
            height_m=float(opening.get("height", 2.1 if kind == "door" else 1.2)),
            sill_height_m=float(opening.get("sill_height", 0.0)),
        ))
    return tuple(result)


def _compiler_contract(
    plan: MetricPlan,
    camera: CameraContract,
    revision: int,
    plan_hash: str,
) -> CompilerWorldContract:
    width, depth, height = (float(value) for value in plan.room_dimensions)
    camera_hash = camera.compute_hash()
    appearance = AppearanceIntent(
        id="appearance:parametric-room",
        architecture_notes="procedural appearance only; Metric Plan owns geometry",
    )
    material_ids = (
        "material:room:floor", "material:room:wall", "material:room:ceiling"
    )
    return CompilerWorldContract(
        source=SourceBinding(
            session_id="unified-parametric-room",
            interface_version=16,
            profile_id="unified-world-pipeline",
            plan_revision=revision,
            plan_hash=_digest({"revision": revision, "plan_hash": plan_hash}),
            scene_graph_hash=_digest({"role": "architecture-compiler-input"}),
            camera_contract_id=f"camera:{camera_hash[:16]}",
            camera_contract_hash=camera_hash,
            appearance_intent_hash=_digest(appearance.model_dump(mode="json")),
        ),
        room=RoomShell(
            dimensions=Dimensions(width_m=width, depth_m=depth, height_m=height),
            floor_material_id=material_ids[0],
            wall_material_id=material_ids[1],
            ceiling_material_id=material_ids[2],
        ),
        openings=_opening_models(plan),
        materials=tuple(MaterialIntent(id=value) for value in material_ids),
        camera=CameraBinding(
            id=f"camera:{camera_hash[:16]}",
            source_schema_version="camera-contract/v1",
            position_m=Vector3(x=camera.position[0], y=camera.position[1], z=camera.position[2]),
            target_m=Vector3(x=camera.target[0], y=camera.target[1], z=camera.target[2]),
            up=Vector3(x=camera.up[0], y=camera.up[1], z=camera.up[2]),
            vertical_fov_deg=camera.vfov,
            aspect_ratio=camera.aspect,
            image_width_px=camera.raster_width,
            image_height_px=camera.raster_height,
            near_plane_m=camera.near,
            far_plane_m=camera.far,
        ),
        appearance=appearance,
    )


def _depth_layer(
    depth_mesh: DepthDerivedMesh | None, camera_hash: str
) -> DepthAppearanceLayer | None:
    if depth_mesh is None:
        return None
    evidence = depth_mesh.evidence
    if (
        not evidence.optional or evidence.collision_enabled
        or evidence.spatial_authority or evidence.authority_claims
    ):
        raise DepthReferenceError("depth evidence attempted authority escalation")
    alignment = evidence.alignment
    if alignment is None or evidence.evidence_kind != "aligned_appearance_reference":
        raise DepthReferenceError("depth mesh requires camera-aligned appearance evidence")
    if alignment.camera_hash != camera_hash:
        raise DepthReferenceError("depth alignment camera hash does not match CameraContract")
    mesh_path = Path(depth_mesh.mesh_path)
    if not mesh_path.is_file():
        raise DepthReferenceError("depth appearance mesh does not exist")
    return DepthAppearanceLayer(
        mesh_path=str(mesh_path),
        mesh_sha256=_file_sha256(mesh_path),
        evidence_sha256=_digest(evidence.to_dict()),
        alignment=asdict(alignment),
    )


class AuthoritativeParametricRoomAdapter:
    """Build one compiler-derived room from one approved normalized Plan."""

    def __init__(self, *, wall_thickness_m: float = 0.1) -> None:
        if not math.isfinite(wall_thickness_m) or wall_thickness_m <= 0.0:
            raise ParametricRoomError("wall_thickness_m must be positive and finite")
        self.wall_thickness_m = wall_thickness_m

    def build(
        self,
        plan: MetricPlan,
        camera: CameraContract,
        approval_gate: ApprovalGate,
        *,
        depth_mesh: DepthDerivedMesh | None = None,
        authority_claims: Iterable[AuthorityClaim] = (),
    ) -> ParametricRoomResult:
        revision, plan_hash = self._validate_plan_binding(plan, camera, approval_gate)
        self._validate_authorities(authority_claims)
        camera_hash = camera.compute_hash()
        compiler_contract = _compiler_contract(plan, camera, revision, plan_hash)
        compiler_plan = build_compiler_plan(
            compiler_contract,
            outputs=CompilerOutputFlags(render=False, blend=False, glb=False, runtime=False),
            wall_thickness_m=self.wall_thickness_m,
        )
        binding = AuthorityBinding(revision, plan_hash, camera_hash)
        elements = tuple(ArchitecturalElement(
            stable_id=item.stable_id,
            role=item.role,
            shape=item.shape,
            position_upbge=item.position_upbge,
            dimensions_upbge=item.dimensions_upbge,
            material_id=item.material_id,
            static_collision=item.role in {"floor", "ceiling", "wall_segment"},
            binding=binding,
            metadata=item.metadata,
        ) for item in compiler_plan.room_geometry)
        openings = tuple(OpeningElement(
            stable_id=item.stable_id,
            kind=item.kind,
            wall=item.wall,
            position_upbge=item.position_upbge,
            dimensions_upbge=item.dimensions_upbge,
            sill_height_m=item.sill_height_m,
            collision_enabled=False,
            binding=binding,
        ) for item in compiler_plan.opening_gaps)
        collision = tuple(ArchitecturalCollision(
            stable_id=f"collision:{item.stable_id}",
            geometry_id=item.stable_id,
            shape=item.shape,
            position_upbge=item.position_upbge,
            dimensions_upbge=item.dimensions_upbge,
            body_mode="STATIC",
            binding=binding,
        ) for item in elements if item.static_collision)
        width, depth, height = (float(value) for value in plan.room_dimensions)
        inset = self.wall_thickness_m / 2.0
        bounds = NavigableBounds(
            minimum_m=(-width / 2.0 + inset, 0.0, -depth / 2.0 + inset),
            maximum_m=(width / 2.0 - inset, height, depth / 2.0 - inset),
            coordinate_system="right-handed-x-right-y-up-z-depth",
            binding=binding,
        )
        return ParametricRoomResult(
            plan_revision=revision,
            plan_hash=plan_hash,
            camera_hash=camera_hash,
            compiler_input_hash=compiler_plan.world_contract_hash,
            elements=elements,
            openings=openings,
            navigable_bounds=bounds,
            collision=collision,
            depth_reference=_depth_layer(depth_mesh, camera_hash),
        )

    @staticmethod
    def _validate_authorities(claims: Iterable[AuthorityClaim]) -> None:
        spatial_sources = {PLAN_AUTHORITY}
        for claim in claims:
            if _SPATIAL_SCOPES.intersection(scope.strip().lower() for scope in claim.scopes):
                spatial_sources.add(claim.source_id.strip())
        if spatial_sources != {PLAN_AUTHORITY}:
            raise AuthorityConflictError(
                "more than one source claims architecture or collision authority: "
                + ", ".join(sorted(spatial_sources))
            )

    @staticmethod
    def _validate_plan_binding(
        plan: MetricPlan,
        camera: CameraContract,
        gate: ApprovalGate,
    ) -> tuple[int, str]:
        if not isinstance(camera, CameraContract):
            raise PlanBindingError("an immutable CameraContract is required")
        camera_values = (
            *camera.position, *camera.target, *camera.up,
            camera.vfov, camera.aspect, camera.near, camera.far,
        )
        if not all(math.isfinite(float(value)) for value in camera_values):
            raise PlanBindingError("CameraContract values must be finite")
        if camera.near <= 0.0 or camera.far <= camera.near:
            raise PlanBindingError("CameraContract frustum is invalid")
        if not plan.revisions:
            raise PlanBindingError("approved Plan requires a nonzero revision")
        latest = max(plan.revisions, key=lambda item: item.revision)
        if latest.revision <= 0 or not latest.plan_hash:
            raise PlanBindingError("approved Plan revision/hash must be nonzero")
        if latest is not plan.revisions[-1]:
            raise PlanBindingError("Plan revision history must be ordered")
        if latest.plan_hash not in _latest_hash_candidates(plan):
            raise PlanBindingError("latest Plan hash does not bind the current Plan")
        if not gate.is_approved():
            raise PlanBindingError("blockout approval is required")
        records = gate.records
        if not records or records[-1].decision is not ApprovalStatus.APPROVED:
            raise PlanBindingError("approval gate lacks a final approved record")
        presented = records[-1].presented_data
        if int(presented.get("plan_revision", 0)) != latest.revision:
            raise PlanBindingError("approval references a different Plan revision")
        if presented.get("camera_hash") != camera.compute_hash():
            raise PlanBindingError("approval references a different CameraContract")
        validation = validate_plan_for_authority(plan)
        if not validation.valid or validation.plan != plan:
            details = "; ".join(item.message for item in validation.violations[:3])
            raise PlanBindingError(
                "Plan must be normalized and valid before room construction"
                + (f": {details}" if details else "")
            )
        _validate_normalized_walls(plan)
        for index, opening in enumerate(plan.openings):
            _validate_opening(dict(opening), index)
        return latest.revision, latest.plan_hash


def build_authoritative_parametric_room(
    plan: MetricPlan,
    camera: CameraContract,
    approval_gate: ApprovalGate,
    *,
    depth_mesh: DepthDerivedMesh | None = None,
    authority_claims: Iterable[AuthorityClaim] = (),
    wall_thickness_m: float = 0.1,
) -> ParametricRoomResult:
    """Functional entry point for the authoritative room adapter."""
    return AuthoritativeParametricRoomAdapter(
        wall_thickness_m=wall_thickness_m
    ).build(
        plan,
        camera,
        approval_gate,
        depth_mesh=depth_mesh,
        authority_claims=authority_claims,
    )
