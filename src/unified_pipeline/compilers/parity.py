"""Strict compiler selection and post-compile WorldContract parity gate.

Compilation outputs remain provisional until browser and every selected engine
match the same authoritative compiler input. No value is inferred or repaired.

**Validates: Requirements 20.8, 21.4, 21.5**
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.world_contract import WorldContract, verify_hash


class CompilerParityError(RuntimeError):
    """Base error for fail-closed selection and parity failures."""


class CompilerSelectionError(CompilerParityError):
    """Raised when requested compiler targets cannot be selected exactly."""


class InvalidCompilerPayload(CompilerParityError):
    """Raised when a compiler omits or disguises authoritative parity data."""


class PublicationBlocked(CompilerParityError):
    """Raised when publication is attempted without a passing parity report."""


class CompilerTarget(str, Enum):
    BROWSER = "browser"
    GODOT = "godot"
    UPBGE = "upbge"


@dataclass(frozen=True, slots=True)
class RoomDimensions:
    """Plan-owned room dimensions in the pipeline's width/depth/height order."""

    width_m: float
    depth_m: float
    height_m: float

    def __post_init__(self) -> None:
        values = (self.width_m, self.depth_m, self.height_m)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            raise InvalidCompilerPayload("room dimensions must be explicit numbers")
        if any(value <= 0 for value in values):
            raise InvalidCompilerPayload("room dimensions must be positive")

    def to_dict(self) -> dict[str, float]:
        return {
            "width_m": self.width_m,
            "depth_m": self.depth_m,
            "height_m": self.height_m,
        }


@dataclass(frozen=True, slots=True)
class CompilerAuthority:
    """The immutable post-assembly input shared by every compiler."""

    contract: WorldContract
    camera: CameraContract
    room_dimensions: RoomDimensions
    asset_normalization_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if not verify_hash(self.contract):
            raise InvalidCompilerPayload("compiler authority requires a valid canonical WorldContract hash")
        if self.contract.camera is None:
            raise InvalidCompilerPayload("WorldContract must carry exact CameraContract values")
        if self.camera.compute_hash() != self.contract.camera_hash:
            raise InvalidCompilerPayload("CameraContract does not match WorldContract camera hash")
        if _canonical(self.contract.camera.to_dict()) != _canonical(self.camera.to_dict()):
            raise InvalidCompilerPayload("compiler authority camera differs from WorldContract camera")
        expected_ids = {instance.object_id for instance in self.contract.instances}
        counts = dict(self.asset_normalization_counts)
        if set(counts) != expected_ids:
            raise InvalidCompilerPayload("normalization evidence must exactly match WorldContract instances")
        invalid = sorted(object_id for object_id, count in counts.items() if count != 1)
        if invalid:
            raise InvalidCompilerPayload(
                f"assets must be normalized exactly once before compilation: {invalid}"
            )

    @classmethod
    def from_assembly(
        cls,
        assembly: Any,
        camera: CameraContract,
        room_dimensions: RoomDimensions,
    ) -> "CompilerAuthority":
        """Build authority from assembler evidence without normalizing again."""
        assembly.assert_unchanged()
        records = {
            (record.path, record.sha256): record.normalization_count
            for record in assembly.normalized_assets
        }
        counts: dict[str, int] = {}
        for instance in assembly.contract.instances:
            key = (instance.asset_binding.mesh_path, instance.asset_binding.asset_id)
            if key not in records:
                raise InvalidCompilerPayload(
                    f"missing normalization evidence for {instance.object_id!r}"
                )
            counts[instance.object_id] = records[key]
        return cls(assembly.contract, camera, room_dimensions, counts)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidCompilerPayload(f"payload is not canonical JSON: {exc}") from exc


def _instances(contract: WorldContract) -> tuple[dict[str, Any], ...]:
    result = []
    for instance in sorted(contract.instances, key=lambda item: item.object_id):
        result.append({
            "object_id": instance.object_id,
            "transform": {
                "position": instance.position.to_dict(),
                "rotation": instance.rotation.to_dict(),
                "scale": instance.scale.to_dict(),
            },
            "asset_binding": instance.asset_binding.to_dict(),
            "material_binding": instance.material_intent.to_dict(),
            "physics_intent": instance.physics_intent,
            "semantic_uuid": instance.object_id,
            "semantic_label": instance.semantic_label,
        })
    return tuple(result)


def _clean_derivation(authority: CompilerAuthority) -> dict[str, Any]:
    return {
        "source": "canonical_world_contract",
        "consumer_defaults": [],
        "clamps": [],
        "rescalings": [],
        "rotation_substitutions": [],
        "offset_substitutions": [],
        "camera_inferred": False,
        "asset_normalization_counts": dict(sorted(authority.asset_normalization_counts.items())),
    }


_PAYLOAD_KEYS = {
    "schema_version", "target", "contract_hash", "plan_revision", "camera",
    "room_dimensions", "instances", "lighting", "navigation", "derivation",
}


@dataclass(frozen=True, slots=True)
class CompilerParityPayload:
    """Engine-neutral parity manifest carried beside one compiled output."""

    target: str
    contract_hash: str
    plan_revision: str
    camera: Mapping[str, Any]
    room_dimensions: Mapping[str, Any]
    instances: tuple[Mapping[str, Any], ...]
    lighting: Mapping[str, Any]
    navigation: Mapping[str, Any] | None
    derivation: Mapping[str, Any]
    schema_version: str = "compiler-parity-payload/v2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "contract_hash": self.contract_hash,
            "plan_revision": self.plan_revision,
            "camera": dict(self.camera),
            "room_dimensions": dict(self.room_dimensions),
            "instances": [dict(item) for item in self.instances],
            "lighting": dict(self.lighting),
            "navigation": dict(self.navigation) if self.navigation is not None else None,
            "derivation": dict(self.derivation),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompilerParityPayload":
        if set(data) != _PAYLOAD_KEYS:
            missing = sorted(_PAYLOAD_KEYS - set(data))
            extra = sorted(set(data) - _PAYLOAD_KEYS)
            raise InvalidCompilerPayload(f"parity payload schema mismatch; missing={missing}, extra={extra}")
        if data["schema_version"] != "compiler-parity-payload/v2":
            raise InvalidCompilerPayload("unsupported compiler parity payload schema")
        for key in ("camera", "room_dimensions", "lighting", "derivation"):
            if not isinstance(data[key], Mapping):
                raise InvalidCompilerPayload(f"{key} must be an explicit object")
        if data["navigation"] is not None and not isinstance(data["navigation"], Mapping):
            raise InvalidCompilerPayload("navigation must be an explicit object or null")
        if not isinstance(data["instances"], (list, tuple)):
            raise InvalidCompilerPayload("instances must be an explicit sequence")
        instances = tuple(data["instances"])
        if any(not isinstance(item, Mapping) for item in instances):
            raise InvalidCompilerPayload("every compiled instance must be an object")
        ids = [str(item.get("object_id", "")) for item in instances]
        if not all(ids) or len(ids) != len(set(ids)):
            raise InvalidCompilerPayload("compiled instance UUIDs must be nonempty and unique")
        payload = cls(
            target=str(data["target"]),
            contract_hash=str(data["contract_hash"]),
            plan_revision=str(data["plan_revision"]),
            camera=dict(data["camera"]),
            room_dimensions=dict(data["room_dimensions"]),
            instances=instances,
            lighting=dict(data["lighting"]),
            navigation=(dict(data["navigation"]) if data["navigation"] is not None else None),
            derivation=dict(data["derivation"]),
        )
        _canonical(payload.to_dict())
        return payload


def build_parity_payload(
    authority: CompilerAuthority,
    target: CompilerTarget | str,
) -> CompilerParityPayload:
    """Create an exact payload from authority; performs no consumer conversion."""
    target_value = CompilerTarget(target).value
    return CompilerParityPayload(
        target=target_value,
        contract_hash=authority.contract.contract_hash,
        plan_revision=authority.contract.plan_revision,
        camera=authority.camera.to_dict(),
        room_dimensions=authority.room_dimensions.to_dict(),
        instances=_instances(authority.contract),
        lighting=authority.contract.lighting.to_dict(),
        navigation=(
            authority.contract.navigation.to_dict()
            if authority.contract.navigation is not None else None
        ),
        derivation=_clean_derivation(authority),
    )


@dataclass(frozen=True, slots=True)
class ParityIssue:
    target: str
    code: str
    field: str
    expected: Any
    actual: Any


@dataclass(frozen=True, slots=True)
class CompilerParityReport:
    contract_hash: str
    plan_revision: str
    targets: tuple[str, ...]
    passed: bool
    issues: tuple[ParityIssue, ...] = ()
    schema_version: str = "compiler-parity-report/v1"

    def require_passed(self) -> None:
        if not self.passed:
            details = "; ".join(
                f"{issue.target}:{issue.field}:{issue.code}" for issue in self.issues
            )
            raise PublicationBlocked(f"compiler parity failed: {details}")


def _issue(
    issues: list[ParityIssue], target: str, code: str, field: str,
    expected: Any, actual: Any,
) -> None:
    if _canonical(expected) != _canonical(actual):
        issues.append(ParityIssue(target, code, field, expected, actual))


def run_parity_gate(
    authority: CompilerAuthority,
    payloads: Sequence[CompilerParityPayload | Mapping[str, Any]],
) -> CompilerParityReport:
    """Compare every post-compile payload exactly against one authority snapshot."""
    parsed = tuple(
        item if isinstance(item, CompilerParityPayload) else CompilerParityPayload.from_dict(item)
        for item in payloads
    )
    targets = tuple(item.target for item in parsed)
    if not parsed or CompilerTarget.BROWSER.value not in targets:
        raise InvalidCompilerPayload("post-compile parity requires a browser payload")
    if len(targets) != len(set(targets)):
        raise InvalidCompilerPayload("post-compile parity payload targets must be unique")

    expected = {
        target: build_parity_payload(authority, target)
        for target in targets
    }
    issues: list[ParityIssue] = []
    operation_codes = {
        "consumer_defaults": "consumer_default",
        "clamps": "clamp",
        "rescalings": "rescaling",
        "rotation_substitutions": "rotation_substitution",
        "offset_substitutions": "offset_substitution",
        "camera_inferred": "camera_inference",
        "asset_normalization_counts": "asset_normalization",
        "source": "authority_source",
    }
    for payload in parsed:
        reference = expected[payload.target]
        _issue(issues, payload.target, "hash_mismatch", "contract_hash",
               reference.contract_hash, payload.contract_hash)
        _issue(issues, payload.target, "revision_mismatch", "plan_revision",
               reference.plan_revision, payload.plan_revision)
        _issue(issues, payload.target, "camera_drift", "camera",
               reference.camera, payload.camera)
        _issue(issues, payload.target, "room_dimension_drift", "room_dimensions",
               reference.room_dimensions, payload.room_dimensions)
        _issue(issues, payload.target, "lighting_drift", "lighting",
               reference.lighting, payload.lighting)
        _issue(issues, payload.target, "navigation_collision_drift", "navigation",
               reference.navigation, payload.navigation)

        expected_by_id = {item["object_id"]: item for item in reference.instances}
        actual_by_id = {str(item.get("object_id", "")): item for item in payload.instances}
        _issue(issues, payload.target, "instance_membership", "instance_ids",
               sorted(expected_by_id), sorted(actual_by_id))
        for object_id in sorted(set(expected_by_id) & set(actual_by_id)):
            expected_instance = expected_by_id[object_id]
            actual_instance = actual_by_id[object_id]
            for field, code in (
                ("transform", "solved_transform_drift"),
                ("asset_binding", "asset_binding_drift"),
                ("material_binding", "material_binding_drift"),
                ("physics_intent", "physics_intent_drift"),
                ("semantic_uuid", "semantic_uuid_drift"),
                ("semantic_label", "semantic_label_drift"),
            ):
                _issue(issues, payload.target, code, f"instances.{object_id}.{field}",
                       expected_instance[field], actual_instance.get(field))
        for field, code in operation_codes.items():
            _issue(issues, payload.target, code, f"derivation.{field}",
                   reference.derivation[field], payload.derivation.get(field))

    return CompilerParityReport(
        contract_hash=authority.contract.contract_hash,
        plan_revision=authority.contract.plan_revision,
        targets=targets,
        passed=not issues,
        issues=tuple(issues),
    )


def adapt_compiler_manifest(
    authority: CompilerAuthority,
    target: CompilerTarget | str,
    manifest: Mapping[str, Any],
) -> CompilerParityPayload:
    """Wrap a concurrent compiler manifest without inferring authoritative values.

    Existing compiler manifests must prove exact contract identity and exact instance
    data. The selector then carries the explicit camera, room dimensions, and
    normalization evidence supplied in its authority input beside the artifact.
    """
    target_value = CompilerTarget(target).value
    required = {
        "contract_hash", "plan_revision", "camera_hash", "room_shell_ref",
        "instances", "lighting", "navigation", "authority",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise InvalidCompilerPayload(f"{target_value} compiler manifest missing {missing}")
    contract = authority.contract
    exact = {
        "contract_hash": contract.contract_hash,
        "plan_revision": contract.plan_revision,
        "camera_hash": contract.camera_hash,
        "room_shell_ref": contract.room_shell_ref,
        "instances": [item.to_dict() for item in contract.instances],
        "lighting": contract.lighting.to_dict(),
        "navigation": contract.navigation.to_dict() if contract.navigation is not None else None,
    }
    for field, expected in exact.items():
        if _canonical(manifest[field]) != _canonical(expected):
            raise InvalidCompilerPayload(f"{target_value} compiler manifest drifted at {field}")
    policy = manifest["authority"]
    if not isinstance(policy, Mapping):
        raise InvalidCompilerPayload(f"{target_value} compiler authority declaration is missing")
    if policy.get("source") != "one_canonical_world_contract":
        raise InvalidCompilerPayload(f"{target_value} compiler used a noncanonical authority")
    if policy.get("transform_policy") != "exact_no_clamp_rescale_offset_or_normalization":
        raise InvalidCompilerPayload(f"{target_value} compiler transform policy permits consumer drift")
    return build_parity_payload(authority, target_value)


class _Compiler(Protocol):
    def compile(self, contract: WorldContract, output_dir: str | Path) -> Any: ...


@dataclass(frozen=True, slots=True)
class CompiledTarget:
    target: str
    result: Any
    parity_payload: CompilerParityPayload


@dataclass(frozen=True, slots=True)
class CompilationBatch:
    """All compilers have finished and parity has run; outputs stay provisional."""

    authority: CompilerAuthority
    outputs: tuple[CompiledTarget, ...]
    parity_report: CompilerParityReport

    def authorize_finality(self, event_system: Any, *, structural_gates_passed: bool) -> Any:
        """The only selector path to final events; parity failure raises first."""
        self.parity_report.require_passed()
        return event_system.authorize_finality(
            plan_revision=self.authority.contract.plan_revision,
            contract_hash=self.authority.contract.contract_hash,
            structural_gates_passed=structural_gates_passed,
            parity_gate_passed=True,
        )


def _adapt_upbge_plan(
    authority: CompilerAuthority,
    plan: Mapping[str, Any],
) -> CompilerParityPayload:
    """Validate UPBGE's preserved contract-domain values before parity wrapping."""
    contract = authority.contract
    identity = {
        "world_contract_hash": contract.contract_hash,
        "plan_revision": contract.plan_revision,
        "camera_hash": contract.camera_hash,
        "coordinate_mapping": "contract(x,y,z)->upbge(x,z,y)",
    }
    for field, expected in identity.items():
        if _canonical(plan.get(field)) != _canonical(expected):
            raise InvalidCompilerPayload(f"upbge compiler plan drifted at {field}")
    scene = plan.get("scene")
    if not isinstance(scene, Mapping) or not isinstance(scene.get("room_shell"), Mapping):
        raise InvalidCompilerPayload("upbge compiler plan lacks room authority")
    if scene["room_shell"].get("contract_reference") != contract.room_shell_ref:
        raise InvalidCompilerPayload("upbge compiler plan drifted at room_shell_ref")
    actual_items = plan.get("instances")
    if not isinstance(actual_items, list):
        raise InvalidCompilerPayload("upbge compiler plan lacks instance inventory")
    actual = {str(item.get("object_id", "")): item for item in actual_items if isinstance(item, Mapping)}
    expected_ids = {item.object_id for item in contract.instances}
    if set(actual) != expected_ids or len(actual_items) != len(actual):
        raise InvalidCompilerPayload("upbge compiler plan drifted at instance UUIDs")
    for instance in contract.instances:
        item = actual[instance.object_id]
        expected = {
            "transform_domain": {
                "position": [instance.position.x, instance.position.y, instance.position.z],
                "rotation_xyzw": [
                    instance.rotation.x, instance.rotation.y,
                    instance.rotation.z, instance.rotation.w,
                ],
                "scale": [instance.scale.x, instance.scale.y, instance.scale.z],
            },
            "asset": {
                "sha256": instance.asset_binding.asset_id,
                "contract_path": instance.asset_binding.mesh_path,
                "triangle_count": instance.asset_binding.triangle_count,
                "vertex_count": instance.asset_binding.vertex_count,
                "generator": instance.asset_binding.generator,
            },
            "material": instance.material_intent.to_dict(),
            "physics_intent": instance.physics_intent,
            "semantic_label": instance.semantic_label,
        }
        actual_values = {
            "transform_domain": item.get("transform_domain"),
            "asset": {
                key: item.get("asset", {}).get(key)
                for key in expected["asset"]
            } if isinstance(item.get("asset"), Mapping) else None,
            "material": item.get("material"),
            "physics_intent": (
                item.get("physics", {}).get("intent")
                if isinstance(item.get("physics"), Mapping) else None
            ),
            "semantic_label": item.get("semantic_label"),
        }
        if _canonical(actual_values) != _canonical(expected):
            raise InvalidCompilerPayload(
                f"upbge compiler plan drifted at instance {instance.object_id!r}"
            )
    return build_parity_payload(authority, CompilerTarget.UPBGE)


def _read_result_payload(
    authority: CompilerAuthority,
    target: CompilerTarget,
    result: Any,
) -> CompilerParityPayload:
    if target is CompilerTarget.UPBGE and hasattr(result, "is_upbge_ready"):
        if getattr(result, "is_upbge_ready") is not True:
            raise InvalidCompilerPayload("UPBGE output is fallback-only and remains provisional")
        plan_path = getattr(result, "plan_path", None)
        try:
            plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise InvalidCompilerPayload(f"cannot read UPBGE compiler plan: {exc}") from exc
        if not isinstance(plan, Mapping):
            raise InvalidCompilerPayload("UPBGE compiler plan must be an object")
        return _adapt_upbge_plan(authority, plan)
    direct = None
    if isinstance(result, Mapping):
        direct = result.get("parity_payload")
    else:
        direct = getattr(result, "parity_payload", None)
    if direct is not None:
        if isinstance(direct, CompilerParityPayload):
            return direct
        if not isinstance(direct, Mapping):
            raise InvalidCompilerPayload(f"{target.value} parity_payload must be an object")
        return CompilerParityPayload.from_dict(direct)

    manifest = result.get("manifest") if isinstance(result, Mapping) else getattr(result, "manifest", None)
    if manifest is None:
        manifest_path = None
        path_names = ("manifest_file", "compiler_manifest_file", "manifest_path")
        for name in path_names:
            candidate = result.get(name) if isinstance(result, Mapping) else getattr(result, name, None)
            if candidate is not None:
                manifest_path = candidate
                break
        if manifest_path is None:
            raise InvalidCompilerPayload(
                f"{target.value} result carries neither parity payload nor compiler manifest"
            )
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise InvalidCompilerPayload(
                f"cannot read {target.value} compiler manifest: {exc}"
            ) from exc
    if not isinstance(manifest, Mapping):
        raise InvalidCompilerPayload(f"{target.value} compiler manifest must be an object")
    return adapt_compiler_manifest(authority, target, manifest)


class CompilerSelector:
    """Compile browser plus selected engines, then run parity before publication."""

    def __init__(self, compilers: Mapping[CompilerTarget | str, _Compiler]) -> None:
        self._compilers = {CompilerTarget(target): compiler for target, compiler in compilers.items()}

    def compile_selected(
        self,
        authority: CompilerAuthority,
        selected_engines: Sequence[CompilerTarget | str],
        output_root: str | Path,
    ) -> CompilationBatch:
        selected = tuple(CompilerTarget(target) for target in selected_engines)
        if not selected:
            raise CompilerSelectionError("select at least one engine output")
        if CompilerTarget.BROWSER in selected:
            raise CompilerSelectionError("browser is compiled automatically; select engine outputs only")
        if len(selected) != len(set(selected)):
            raise CompilerSelectionError("selected engine outputs must be unique")
        targets = (CompilerTarget.BROWSER, *selected)
        missing = [target.value for target in targets if target not in self._compilers]
        if missing:
            raise CompilerSelectionError(f"compiler implementations unavailable: {missing}")

        root = Path(output_root)
        outputs: list[CompiledTarget] = []
        for target in targets:
            result = self._compilers[target].compile(authority.contract, root / target.value)
            payload = _read_result_payload(authority, target, result)
            if payload.target != target.value:
                raise InvalidCompilerPayload(
                    f"selected {target.value} compiler returned {payload.target!r} payload"
                )
            outputs.append(CompiledTarget(target.value, result, payload))
        report = run_parity_gate(authority, [item.parity_payload for item in outputs])
        return CompilationBatch(authority, tuple(outputs), report)

    def compile_and_authorize(
        self,
        authority: CompilerAuthority,
        selected_engines: Sequence[CompilerTarget | str],
        output_root: str | Path,
        event_system: Any,
        *,
        structural_gates_passed: bool,
    ) -> CompilationBatch:
        batch = self.compile_selected(authority, selected_engines, output_root)
        batch.authorize_finality(
            event_system, structural_gates_passed=structural_gates_passed
        )
        return batch
