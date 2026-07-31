"""Mandatory solve-chain assembly for the Unified World Pipeline.

The assembler is the only boundary that may turn an approved normalized Plan,
its immutable camera, and approved assets into a final WorldContract.

Requirements: 19.1, 19.2, 19.3, 19.4, 32.1-32.7, 34.2-34.3
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .camera_contract import CameraContract
from .models import MetricPlan
from .parametric_room import PLAN_AUTHORITY, AuthorityClaim, ParametricRoomResult
from .plan_validator import PlanValidator
from .world_contract import (
    AssetBinding,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Relationship,
    Vec3,
    WorldContract,
    finalize,
    serialize,
    verify_hash,
)

MANDATORY_CHAIN = (
    "solve",
    "normalize",
    "validate",
    "immutable_camera_contract",
    "constrained_scene_graph",
    "world_contract",
    "relationship_solve",
    "canonical_serialization_hash",
)


class AssemblyError(ValueError):
    """Base class for fail-closed assembly errors."""


class RevisionMismatchError(AssemblyError):
    """Plan, room, or requested revision bindings disagree."""


class DuplicateAuthorityError(AssemblyError):
    """More than one source claims a Plan-owned concern."""


class ConsumerDefaultError(AssemblyError):
    """A downstream consumer attempted to invent an authoritative value."""


class AssetNormalizationError(AssemblyError):
    """An approved asset is invalid or normalization is inconsistent."""


class RelationshipSolveError(AssemblyError):
    """The relationship graph cannot be resolved deterministically."""


class PostHashMutationError(AssemblyError):
    """A finalized contract no longer matches its canonical snapshot."""


@dataclass(frozen=True, slots=True)
class ApprovedAssetRecord:
    """Reviewed mesh record accepted at the exactly-once boundary."""

    path: str
    sha256: str
    triangle_count: int
    vertex_count: int = 0
    generator: str = ""


@dataclass(frozen=True, slots=True)
class NormalizedAssetRecord:
    """Proof that one approved mesh crossed normalization exactly once."""

    source_path: str
    path: str
    sha256: str
    triangle_count: int
    vertex_count: int
    generator: str
    coordinate_system: str = "right-handed-x-right-y-up-z-depth"
    length_unit: str = "meter"
    origin_policy: str = "local-bounds-center"
    normalization_count: int = 1

    def to_binding(self) -> AssetBinding:
        return AssetBinding(
            asset_id=self.sha256,
            mesh_path=self.path,
            triangle_count=self.triangle_count,
            vertex_count=self.vertex_count,
            generator=self.generator,
        )


@dataclass(frozen=True, slots=True)
class InstanceAssemblyInput:
    """Explicit non-spatial intent; all transforms remain Plan-derived."""

    object_id: str
    name: str
    approved_asset: ApprovedAssetRecord
    physics_intent: str
    material_intent: MaterialIntent
    semantic_label: str
    is_architectural: bool = False
    consumer_defaults: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstrainedSceneGraph:
    """Intermediate graph containing only Plan-authorized spatial values."""

    plan_revision: int
    plan_hash: str
    camera_hash: str
    room_authority_hash: str
    instances: tuple[ObjectInstance, ...]
    relationships: tuple[Relationship, ...]
    lighting: LightingConfig


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """Final contract plus immutable evidence of mandatory-chain execution."""

    contract: WorldContract
    canonical_json: str
    contract_hash: str
    stage_trace: tuple[str, ...]
    scene_graph: ConstrainedSceneGraph
    normalized_assets: tuple[NormalizedAssetRecord, ...]

    def assert_unchanged(self) -> None:
        if self.stage_trace != MANDATORY_CHAIN:
            raise PostHashMutationError("mandatory construction chain was altered")
        if not verify_hash(self.contract):
            raise PostHashMutationError("WorldContract changed after canonical hashing")
        if serialize(self.contract) != self.canonical_json:
            raise PostHashMutationError("canonical WorldContract snapshot changed after hashing")
        if self.contract.contract_hash != self.contract_hash:
            raise PostHashMutationError("stored canonical hash no longer matches the result")


class AssetNormalizer:
    """Thread-safe, content-addressed exactly-once normalization registry.

    Asset generators already emit engine-neutral GLB candidates. At this
    boundary normalization records the one conversion into contract-space
    conventions. Repeated instances or idempotent resume reuse the same proof.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], NormalizedAssetRecord] = {}
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def normalize(self, asset: ApprovedAssetRecord) -> NormalizedAssetRecord:
        source = self._validate(asset)
        key = (str(source), asset.sha256)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return existing
            record = NormalizedAssetRecord(
                source_path=str(source),
                path=str(source),
                sha256=asset.sha256,
                triangle_count=asset.triangle_count,
                vertex_count=asset.vertex_count,
                generator=asset.generator,
            )
            self._records[key] = record
            self._counts[key] = 1
            return record

    def normalization_count(self, asset: ApprovedAssetRecord) -> int:
        source = Path(asset.path).expanduser().resolve()
        return self._counts.get((str(source), asset.sha256), 0)

    @staticmethod
    def _validate(asset: ApprovedAssetRecord) -> Path:
        source = Path(asset.path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".glb":
            raise AssetNormalizationError(
                "approved asset path must be an existing self-contained GLB"
            )
        if len(asset.sha256) != 64 or any(
            value not in "0123456789abcdef" for value in asset.sha256
        ):
            raise AssetNormalizationError(
                "approved asset sha256 must be lowercase hexadecimal"
            )
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != asset.sha256:
            raise AssetNormalizationError("approved asset sha256 does not match its path")
        if isinstance(asset.triangle_count, bool) or asset.triangle_count <= 0:
            raise AssetNormalizationError("approved asset triangle_count must be positive")
        if isinstance(asset.vertex_count, bool) or asset.vertex_count < 0:
            raise AssetNormalizationError("approved asset vertex_count cannot be negative")
        return source


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise AssemblyError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AssemblyError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise AssemblyError(f"{label} must be a finite number")
    return result


def _yaw_quaternion(degrees: float) -> Quaternion:
    half = math.radians(degrees % 360.0) / 2.0
    return Quaternion(x=0.0, y=math.sin(half), z=0.0, w=math.cos(half))


class WorldContractAssembler:
    """Execute the mandatory construction chain and fail closed on drift."""

    def __init__(self, *, asset_normalizer: AssetNormalizer | None = None) -> None:
        self.asset_normalizer = asset_normalizer or AssetNormalizer()

    def assemble(
        self,
        plan: MetricPlan,
        camera: CameraContract,
        room: ParametricRoomResult,
        instances: Sequence[InstanceAssemblyInput],
        *,
        approved_plan_revision: int,
        relationships: Iterable[Relationship] = (),
        lighting: LightingConfig,
        authority_claims: Iterable[str | AuthorityClaim] = (),
        consumer_defaults: Mapping[str, Any] | Iterable[str] = (),
        contract_id: str | None = None,
        created_at: str = "",
    ) -> AssemblyResult:
        """Build one deterministic, relationship-solved, hash-bound contract."""
        trace: list[str] = []

        solved = self._solve(plan)
        trace.append("solve")
        normalized = self._normalize(plan, solved)
        trace.append("normalize")
        revision = self._validate(
            plan, room, approved_plan_revision, normalized, authority_claims
        )
        trace.append("validate")

        self._reject_consumer_defaults(consumer_defaults, instances)
        camera_hash = self._bind_camera(camera, room)
        trace.append("immutable_camera_contract")

        graph, normalized_assets = self._build_scene_graph(
            plan, room, camera_hash, revision, normalized, instances,
            tuple(relationships), lighting,
        )
        trace.append("constrained_scene_graph")

        draft = self._build_contract(graph, room, camera, contract_id, created_at)
        trace.append("world_contract")
        solved_contract = self._solve_relationships(draft, room)
        trace.append("relationship_solve")

        final_contract = finalize(solved_contract)
        canonical_json = serialize(final_contract)
        if not verify_hash(final_contract):
            raise AssemblyError("canonical WorldContract hash verification failed")
        trace.append("canonical_serialization_hash")
        if tuple(trace) != MANDATORY_CHAIN:
            raise AssemblyError("mandatory construction chain was omitted or reordered")

        result = AssemblyResult(
            contract=final_contract,
            canonical_json=canonical_json,
            contract_hash=final_contract.contract_hash,
            stage_trace=tuple(trace),
            scene_graph=graph,
            normalized_assets=normalized_assets,
        )
        result.assert_unchanged()
        return result

    @staticmethod
    def _solve(plan: MetricPlan) -> tuple[dict[str, Any], ...]:
        """Resolve placements into one explicit Plan-owned representation."""
        solved: list[dict[str, Any]] = []
        seen: set[str] = set()
        required = {"id", "name", "x", "y", "width", "height", "depth", "rotation_deg"}
        for index, raw in enumerate(plan.object_placements):
            placement = dict(raw)
            missing = sorted(required - set(placement))
            if missing:
                raise ConsumerDefaultError(
                    f"Plan placement {index} requires explicit values: {', '.join(missing)}"
                )
            object_id = str(placement["id"]).strip()
            if not object_id or object_id in seen:
                raise AssemblyError(f"duplicate or empty Plan object identity {object_id!r}")
            seen.add(object_id)
            solved.append(placement)
        return tuple(sorted(solved, key=lambda item: str(item["id"])))

    @staticmethod
    def _normalize(
        plan: MetricPlan, solved: Sequence[dict[str, Any]]
    ) -> tuple[dict[str, Any], ...]:
        """Map corner-origin Plan coordinates into contract-space exactly once."""
        width, depth, _ = (_finite(value, "room dimension") for value in plan.room_dimensions)
        normalized: list[dict[str, Any]] = []
        for item in solved:
            item_width = _finite(item["width"], f"{item['id']}.width")
            item_height = _finite(item["height"], f"{item['id']}.height")
            item_depth = _finite(item["depth"], f"{item['id']}.depth")
            if min(item_width, item_height, item_depth) <= 0.0:
                raise AssemblyError(f"{item['id']} dimensions must be positive")
            normalized.append({
                "id": str(item["id"]),
                "name": str(item["name"]),
                "position": (
                    _finite(item["x"], f"{item['id']}.x") - width / 2.0,
                    _finite(item.get("elevation", 0.0), f"{item['id']}.elevation"),
                    _finite(item["y"], f"{item['id']}.y") - depth / 2.0,
                ),
                "rotation_deg": _finite(
                    item["rotation_deg"], f"{item['id']}.rotation_deg"
                ) % 360.0,
                "dimensions": (item_width, item_height, item_depth),
            })
        return tuple(normalized)

    @staticmethod
    def _validate(
        plan: MetricPlan,
        room: ParametricRoomResult,
        approved_revision: int,
        normalized: Sequence[dict[str, Any]],
        authority_claims: Iterable[str | AuthorityClaim],
    ) -> int:
        if not plan.revisions:
            raise RevisionMismatchError("approved Plan requires a nonzero revision")
        latest = plan.revisions[-1]
        if latest.revision <= 0 or latest.revision != approved_revision:
            raise RevisionMismatchError(
                "approved revision does not match the latest nonzero Plan revision"
            )
        if latest is not max(plan.revisions, key=lambda value: value.revision):
            raise RevisionMismatchError("Plan revision history is not ordered")
        if room.plan_revision != latest.revision or room.plan_hash != latest.plan_hash:
            raise RevisionMismatchError("parametric room is bound to another Plan revision")
        validation = PlanValidator().validate(plan)
        if not validation.valid or validation.plan != plan:
            raise AssemblyError("Plan must be normalized and valid before assembly")
        if len(normalized) != len(plan.object_placements):
            raise AssemblyError("solve/normalize lost Plan instances")
        sources = {room.spatial_authority}
        for claim in authority_claims:
            source = claim.source_id if isinstance(claim, AuthorityClaim) else str(claim)
            if source.strip():
                sources.add(source.strip())
        if room.spatial_authority != PLAN_AUTHORITY or sources != {PLAN_AUTHORITY}:
            raise DuplicateAuthorityError(
                "more than one source claims architecture, collision, or transforms"
            )
        WorldContractAssembler._validate_room_bindings(room, latest.revision, latest.plan_hash)
        return latest.revision

    @staticmethod
    def _validate_room_bindings(
        room: ParametricRoomResult, revision: int, plan_hash: str
    ) -> None:
        bindings = [item.binding for item in room.elements]
        bindings.extend(item.binding for item in room.openings)
        bindings.extend(item.binding for item in room.collision)
        bindings.append(room.navigable_bounds.binding)
        if any(
            binding.plan_revision != revision
            or binding.plan_hash != plan_hash
            or binding.camera_hash != room.camera_hash
            or binding.spatial_authority != PLAN_AUTHORITY
            for binding in bindings
        ):
            raise DuplicateAuthorityError("parametric room contains a mismatched authority binding")
        for label, values in (
            ("room element", [item.stable_id for item in room.elements]),
            ("opening", [item.stable_id for item in room.openings]),
            ("collision", [item.stable_id for item in room.collision]),
        ):
            if len(values) != len(set(values)):
                raise DuplicateAuthorityError(f"duplicate {label} authority")

    @staticmethod
    def _reject_consumer_defaults(
        defaults: Mapping[str, Any] | Iterable[str],
        instances: Sequence[InstanceAssemblyInput],
    ) -> None:
        names = tuple(defaults.keys()) if isinstance(defaults, Mapping) else tuple(defaults)
        names += tuple(
            f"{item.object_id}.{name}"
            for item in instances
            for name in item.consumer_defaults
        )
        if names:
            raise ConsumerDefaultError(
                "consumer defaults are forbidden for authoritative values: "
                + ", ".join(sorted(str(value) for value in names))
            )

    @staticmethod
    def _bind_camera(camera: CameraContract, room: ParametricRoomResult) -> str:
        if not isinstance(camera, CameraContract):
            raise AssemblyError("an immutable CameraContract is required after validation")
        values = (
            *camera.position, *camera.target, *camera.up,
            camera.vfov, camera.aspect, camera.near, camera.far,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise AssemblyError("CameraContract values must be finite")
        if camera.near <= 0.0 or camera.far <= camera.near:
            raise AssemblyError("CameraContract frustum is invalid")
        camera_hash = camera.compute_hash()
        if camera_hash != room.camera_hash:
            raise RevisionMismatchError("CameraContract does not match parametric room binding")
        return camera_hash

    def _build_scene_graph(
        self,
        plan: MetricPlan,
        room: ParametricRoomResult,
        camera_hash: str,
        revision: int,
        normalized: Sequence[dict[str, Any]],
        inputs: Sequence[InstanceAssemblyInput],
        relationships: tuple[Relationship, ...],
        lighting: LightingConfig,
    ) -> tuple[ConstrainedSceneGraph, tuple[NormalizedAssetRecord, ...]]:
        input_map: dict[str, InstanceAssemblyInput] = {}
        for item in inputs:
            if not item.object_id or item.object_id in input_map:
                raise AssemblyError(f"duplicate or empty instance input {item.object_id!r}")
            input_map[item.object_id] = item
        plan_ids = {str(item["id"]) for item in normalized}
        if set(input_map) != plan_ids:
            missing = sorted(plan_ids - set(input_map))
            extra = sorted(set(input_map) - plan_ids)
            raise AssemblyError(
                f"instance bindings must exactly match Plan; missing={missing}, extra={extra}"
            )

        world_instances: list[ObjectInstance] = []
        normalized_by_key: dict[tuple[str, str], NormalizedAssetRecord] = {}
        valid_physics = {"static", "dynamic", "kinematic", "trigger"}
        for placement in normalized:
            intent = input_map[placement["id"]]
            if intent.physics_intent not in valid_physics:
                raise ConsumerDefaultError(
                    f"{intent.object_id} requires explicit valid physics intent"
                )
            material = intent.material_intent
            if (
                not material.base_color.strip()
                or not 0.0 <= material.metallic <= 1.0
                or not 0.0 <= material.roughness <= 1.0
                or material.pass_level not in {1, 2}
            ):
                raise ConsumerDefaultError(
                    f"{intent.object_id} requires explicit valid material intent"
                )
            if not intent.semantic_label.strip() or not intent.name.strip():
                raise ConsumerDefaultError(
                    f"{intent.object_id} requires explicit identity and semantic label"
                )
            asset = self.asset_normalizer.normalize(intent.approved_asset)
            normalized_by_key[(asset.path, asset.sha256)] = asset
            position = placement["position"]
            dimensions = placement["dimensions"]
            world_instances.append(ObjectInstance(
                object_id=intent.object_id,
                name=intent.name,
                position=Vec3(*position),
                rotation=_yaw_quaternion(placement["rotation_deg"]),
                scale=Vec3(*dimensions),
                asset_binding=asset.to_binding(),
                physics_intent=intent.physics_intent,
                material_intent=material,
                semantic_label=intent.semantic_label,
                is_architectural=intent.is_architectural,
            ))

        room_hash = _canonical_digest(room.to_dict())
        graph = ConstrainedSceneGraph(
            plan_revision=revision,
            plan_hash=room.plan_hash,
            camera_hash=camera_hash,
            room_authority_hash=room_hash,
            instances=tuple(sorted(world_instances, key=lambda item: item.object_id)),
            relationships=relationships,
            lighting=lighting,
        )
        assets = tuple(
            normalized_by_key[key] for key in sorted(normalized_by_key)
        )
        return graph, assets

    @staticmethod
    def _build_contract(
        graph: ConstrainedSceneGraph,
        room: ParametricRoomResult,
        camera: CameraContract,
        contract_id: str | None,
        created_at: str,
    ) -> WorldContract:
        relationship_seed = sorted(
            (item.to_dict() for item in graph.relationships),
            key=lambda item: (
                item["source_id"], item["target_id"],
                item["relationship_type"], item["metadata"],
            ),
        )
        if contract_id is None:
            seed = {
                "plan_revision": graph.plan_revision,
                "plan_hash": graph.plan_hash,
                "camera_hash": graph.camera_hash,
                "room_authority_hash": graph.room_authority_hash,
                "instances": [item.to_dict() for item in graph.instances],
                "relationships": relationship_seed,
                "lighting": graph.lighting.to_dict(),
            }
            contract_id = f"world-{_canonical_digest(seed)[:32]}"
        return WorldContract(
            plan_revision=f"rev-{graph.plan_revision}",
            camera_hash=graph.camera_hash,
            camera=camera,
            room_shell_ref=f"parametric-room:sha256:{graph.room_authority_hash}",
            instances=graph.instances,
            relationships=graph.relationships,
            lighting=graph.lighting,
            contract_id=contract_id,
            created_at=created_at,
        )

    @staticmethod
    def _solve_relationships(
        contract: WorldContract, room: ParametricRoomResult
    ) -> WorldContract:
        """Resolve references/cycles and prove rotation-aware containment."""
        instance_ids = {item.object_id for item in contract.instances}
        target_ids = instance_ids | {"room"}
        target_ids.update(item.stable_id for item in room.elements)
        target_ids.update(item.stable_id for item in room.openings)
        target_ids.update(item.stable_id for item in room.collision)
        allowed = {"parent_child", "containment", "adjacency", "support"}
        seen: set[tuple[str, str, str]] = set()
        parent_edges: dict[str, str] = {}
        solved: list[Relationship] = []
        for relation in contract.relationships:
            if relation.relationship_type not in allowed:
                raise RelationshipSolveError(
                    f"unsupported relationship type {relation.relationship_type!r}"
                )
            if relation.source_id not in instance_ids:
                raise RelationshipSolveError(
                    f"relationship source {relation.source_id!r} is not a Plan instance"
                )
            if relation.target_id not in target_ids:
                raise RelationshipSolveError(
                    f"relationship target {relation.target_id!r} is dangling"
                )
            if relation.source_id == relation.target_id:
                raise RelationshipSolveError("self relationships are forbidden")
            key = (
                relation.source_id, relation.target_id, relation.relationship_type
            )
            if key in seen:
                raise RelationshipSolveError("duplicate relationship authority")
            seen.add(key)
            if relation.relationship_type == "parent_child":
                if relation.source_id in parent_edges:
                    raise RelationshipSolveError("an instance cannot have two parent authorities")
                parent_edges[relation.source_id] = relation.target_id
            solved.append(relation)

        for source in parent_edges:
            visited: set[str] = set()
            current = source
            while current in parent_edges:
                if current in visited:
                    raise RelationshipSolveError("parent relationship cycle detected")
                visited.add(current)
                current = parent_edges[current]

        WorldContractAssembler._assert_contained(contract.instances, room)
        solved.sort(key=lambda item: (
            item.source_id, item.target_id, item.relationship_type, item.metadata
        ))
        payload = contract.to_dict()
        payload["relationships"] = [item.to_dict() for item in solved]
        payload["contract_hash"] = ""
        return WorldContract.from_dict(payload)

    @staticmethod
    def _assert_contained(
        instances: Sequence[ObjectInstance], room: ParametricRoomResult
    ) -> None:
        minimum = room.navigable_bounds.minimum_m
        maximum = room.navigable_bounds.maximum_m
        tolerance = 1e-8
        for item in instances:
            yaw = 2.0 * math.atan2(item.rotation.y, item.rotation.w)
            cosine, sine = abs(math.cos(yaw)), abs(math.sin(yaw))
            half_x = (cosine * item.scale.x + sine * item.scale.z) / 2.0
            half_z = (sine * item.scale.x + cosine * item.scale.z) / 2.0
            if (
                item.position.x - half_x < minimum[0] - tolerance
                or item.position.x + half_x > maximum[0] + tolerance
                or item.position.z - half_z < minimum[2] - tolerance
                or item.position.z + half_z > maximum[2] + tolerance
                or item.position.y < minimum[1] - tolerance
                or item.position.y + item.scale.y > maximum[1] + tolerance
            ):
                raise RelationshipSolveError(
                    f"Plan instance {item.object_id!r} exceeds authoritative room bounds"
                )

    @staticmethod
    def verify_result(result: AssemblyResult) -> bool:
        result.assert_unchanged()
        return True


def assemble_world_contract(
    plan: MetricPlan,
    camera: CameraContract,
    room: ParametricRoomResult,
    instances: Sequence[InstanceAssemblyInput],
    *,
    approved_plan_revision: int,
    lighting: LightingConfig,
    relationships: Iterable[Relationship] = (),
    authority_claims: Iterable[str | AuthorityClaim] = (),
    consumer_defaults: Mapping[str, Any] | Iterable[str] = (),
    asset_normalizer: AssetNormalizer | None = None,
    contract_id: str | None = None,
    created_at: str = "",
) -> AssemblyResult:
    """Functional entry point for mandatory WorldContract assembly."""
    return WorldContractAssembler(asset_normalizer=asset_normalizer).assemble(
        plan,
        camera,
        room,
        instances,
        approved_plan_revision=approved_plan_revision,
        relationships=relationships,
        lighting=lighting,
        authority_claims=authority_claims,
        consumer_defaults=consumer_defaults,
        contract_id=contract_id,
        created_at=created_at,
    )
