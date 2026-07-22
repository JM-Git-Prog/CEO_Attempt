"""Isolated WorldContract-native portable export adapters.

These adapters deliberately do not call or modify the retained SceneGraph Godot assembler.
They emit deterministic target metadata and truthfully report representation gaps.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.world_contract import WorldContract


class ExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ExportArtifact(ExportModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    target_role: str

    @classmethod
    def from_path(cls, path: str | Path, *, media_type: str, target_role: str) -> "ExportArtifact":
        artifact = Path(path)
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(
            path=str(artifact), bytes=artifact.stat().st_size, sha256=digest.hexdigest(),
            media_type=media_type, target_role=target_role,
        )


class AdapterCapabilities(ExportModel):
    adapter_id: str
    target: Literal["godot", "glb_three"]
    native_features: tuple[str, ...] = ()
    sidecar_features: tuple[str, ...] = ()
    target_specific_features: tuple[str, ...] = ()
    metadata_schema_version: str


class UnsupportedFeature(ExportModel):
    feature_id: str
    reason_code: str
    message: str
    required: bool = True
    preserved_in_sidecar: bool = False


class FeatureRepresentation(ExportModel):
    feature_id: str
    disposition: Literal["native", "sidecar_metadata", "target_specific", "unsupported"]
    declaration_version: str | None = None

    @model_validator(mode="after")
    def versioned_non_native_representation(self) -> "FeatureRepresentation":
        requires_version = self.disposition in {"sidecar_metadata", "target_specific"}
        if requires_version != bool(self.declaration_version):
            raise ValueError(
                "sidecar and target-specific representations require a declaration version"
            )
        return self


class AdapterDiagnostic(ExportModel):
    stage: Literal["contract", "export", "package", "feature"]
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    feature_id: str | None = None


class ExportAdapterResult(ExportModel):
    schema_version: Literal["export-adapter-result/v1"] = "export-adapter-result/v1"
    adapter_id: str
    target: Literal["godot", "glb_three"]
    status: Literal["success", "partial", "rejected"]
    world_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[ExportArtifact, ...] = ()
    capabilities: AdapterCapabilities
    feature_representations: tuple[FeatureRepresentation, ...] = ()
    unsupported_features: tuple[UnsupportedFeature, ...] = ()
    diagnostics: tuple[AdapterDiagnostic, ...] = ()
    manifests: tuple[ExportArtifact, ...] = ()

    @model_validator(mode="after")
    def truthful_status(self) -> "ExportAdapterResult":
        if self.capabilities.adapter_id != self.adapter_id or self.capabilities.target != self.target:
            raise ValueError("result identity must match adapter capabilities")
        feature_ids = [item.feature_id for item in self.feature_representations]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("each feature must have exactly one representation")
        dispositions = {
            item.feature_id: item.disposition for item in self.feature_representations
        }
        for item in self.unsupported_features:
            if dispositions.get(item.feature_id) != "unsupported":
                raise ValueError("unsupported features require an unsupported disposition")
        required = any(item.required for item in self.unsupported_features)
        if required and self.status != "rejected":
            raise ValueError("required unsupported features require rejected status")
        if self.status == "success" and self.unsupported_features:
            raise ValueError("success cannot conceal unsupported features")
        if self.status == "partial" and not self.unsupported_features:
            raise ValueError("partial status requires an explicit unsupported feature")
        return self


class ExportAdapter(Protocol):
    capabilities: AdapterCapabilities

    def export(self, contract: WorldContract, output_dir: str | Path) -> ExportAdapterResult: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> Path:
    """Create one immutable manifest; callers must choose a fresh output directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_canonical_bytes(value))
    return path


def _copy_immutable(source: Path, target: Path) -> Path:
    """Copy an artifact into its portable package without overwriting evidence."""
    source = source.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("portable artifact source must be a regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
    return target


def _representation(
    feature_id: str,
    disposition: Literal["native", "sidecar_metadata", "target_specific", "unsupported"],
    declaration_version: str | None = None,
) -> FeatureRepresentation:
    return FeatureRepresentation(
        feature_id=feature_id,
        disposition=disposition,
        declaration_version=declaration_version,
    )


def _unsupported(
    contract: WorldContract,
    feature_id: str,
    reason_code: str,
    message: str,
    *,
    preserved_in_sidecar: bool,
) -> UnsupportedFeature:
    return UnsupportedFeature(
        feature_id=feature_id,
        reason_code=reason_code,
        message=message,
        required=contract.exports.unsupported_behavior == "reject",
        preserved_in_sidecar=preserved_in_sidecar,
    )


def _common_metadata(contract: WorldContract) -> dict[str, object]:
    """Return complete target-independent metadata without reinterpreting authority."""
    contract_payload = contract.model_dump(mode="json")
    return {
        "schema_version": "portable-world-metadata/v1",
        "world_contract_version": contract.schema_version,
        "world_contract_hash": contract.content_hash(),
        "world_contract": contract_payload,
        "source": contract.source.model_dump(mode="json"),
        "coordinate_system": contract.coordinate_system,
        "length_unit": contract.length_unit,
        "angle_unit": contract.angle_unit,
        "room": contract.room.model_dump(mode="json"),
        "openings": [item.model_dump(mode="json") for item in contract.openings],
        "instances": [item.model_dump(mode="json") for item in contract.instances],
        "materials": [item.model_dump(mode="json") for item in contract.materials],
        "lights": [item.model_dump(mode="json") for item in contract.lights],
        "camera": contract.camera.model_dump(mode="json"),
        "appearance": contract.appearance.model_dump(mode="json"),
        "physics": contract.physics.model_dump(mode="json"),
        "interactions": [item.model_dump(mode="json") for item in contract.interactions],
        "export_policy": contract.exports.model_dump(mode="json"),
    }


def _status(unsupported: tuple[UnsupportedFeature, ...]) -> Literal["success", "partial", "rejected"]:
    if any(item.required for item in unsupported):
        return "rejected"
    return "partial" if unsupported else "success"


class GodotWorldContractAdapter:
    """Package a contract-native Godot project and its lossless semantic sidecar."""

    capabilities = AdapterCapabilities(
        adapter_id="godot-world-contract/v1",
        target="godot",
        native_features=(
            "stable_ids", "metric_transforms", "coordinate_system", "perspective_camera",
            "point_spot_directional_lights", "collision_bodies",
        ),
        sidecar_features=("materials", "relations", "interactions", "area_lights"),
        metadata_schema_version="godot-world-metadata/v1",
    )

    def __init__(self, project_dir: str | Path | None = None):
        self.project_dir = Path(project_dir) if project_dir is not None else None

    def export(self, contract: WorldContract, output_dir: str | Path) -> ExportAdapterResult:
        root = Path(output_dir)
        unsupported: list[UnsupportedFeature] = []
        representations = [
            _representation("stable_ids", "native"),
            _representation("metric_units", "native"),
            _representation("coordinate_system", "native"),
            _representation("camera", "native"),
            _representation("physics", "native"),
            _representation("materials", "sidecar_metadata", "portable-world-metadata/v1"),
            _representation("relations", "sidecar_metadata", "portable-world-metadata/v1"),
            _representation("interactions", "sidecar_metadata", "portable-world-metadata/v1"),
        ]
        project_artifacts: list[ExportArtifact] = []
        if self.project_dir is None:
            feature_id = "godot.project"
            unsupported.append(_unsupported(
                contract, feature_id, "project_not_supplied",
                "No contract-native Godot project was supplied; only metadata was emitted.",
                preserved_in_sidecar=False,
            ))
            representations.append(_representation(feature_id, "unsupported"))
        else:
            project_dir = self.project_dir.resolve(strict=True)
            required_files = {
                "project.godot": "godot_project",
                "main.tscn": "godot_main_scene",
                "player.tscn": "godot_player_scene",
                "player.gd": "godot_player_script",
            }
            missing = sorted(name for name in required_files if not (project_dir / name).is_file())
            if missing:
                feature_id = "godot.project"
                unsupported.append(_unsupported(
                    contract, feature_id, "incomplete_project",
                    "Godot project is missing: " + ", ".join(missing),
                    preserved_in_sidecar=False,
                ))
                representations.append(_representation(feature_id, "unsupported"))
            else:
                representations.append(_representation("godot.project", "native"))
                for name, role in required_files.items():
                    media_type = "text/x-gdscript" if name.endswith(".gd") else "text/plain"
                    project_artifacts.append(ExportArtifact.from_path(
                        project_dir / name, media_type=media_type, target_role=role,
                    ))

        for opening in contract.openings:
            representations.append(_representation(f"opening_aperture:{opening.id}", "native"))
        for light in contract.lights:
            feature_id = f"light:{light.id}"
            if light.light_type == "area":
                unsupported.append(_unsupported(
                    contract, feature_id, "godot_area_light_no_equivalent",
                    f"Area light {light.id} has no equivalent in the generated Godot scene.",
                    preserved_in_sidecar=True,
                ))
                representations.append(_representation(feature_id, "unsupported"))
            else:
                representations.append(_representation(feature_id, "native"))
        for interaction in contract.interactions:
            feature_id = f"interaction_runtime:{interaction.id}"
            unsupported.append(_unsupported(
                contract, feature_id, "godot_interaction_template_unavailable",
                f"Interaction {interaction.id} is preserved as target-independent metadata but "
                "has no parameter-equivalent Godot runtime component.",
                preserved_in_sidecar=True,
            ))
            representations.append(_representation(feature_id, "unsupported"))

        payload = _common_metadata(contract)
        payload.update({
            "schema_version": "godot-world-metadata/v1",
            "target_independent_schema_version": "portable-world-metadata/v1",
            "artifact_scope": "project_bound_metadata" if project_artifacts else "metadata_only",
            "target": {
                "engine": "Godot", "major_version": 4,
                "domain_axis_mapping": "identity:x-right-y-up-z-depth",
                "meters_per_unit": 1.0,
            },
            "representations": [item.model_dump(mode="json") for item in representations],
        })
        manifest_path = _write_json(root / "godot_world_metadata.json", payload)
        manifest = ExportArtifact.from_path(
            manifest_path, media_type="application/json", target_role="godot_world_metadata",
        )
        unsupported_tuple = tuple(unsupported)
        return ExportAdapterResult(
            adapter_id=self.capabilities.adapter_id, target="godot",
            status=_status(unsupported_tuple), world_contract_hash=contract.content_hash(),
            artifacts=(*project_artifacts, manifest), capabilities=self.capabilities,
            feature_representations=tuple(representations),
            unsupported_features=unsupported_tuple,
            diagnostics=tuple(AdapterDiagnostic(
                stage="feature", code=item.reason_code, severity="error" if item.required else "warning",
                message=item.message, feature_id=item.feature_id,
            ) for item in unsupported_tuple),
            manifests=(manifest,),
        )


class GLBThreeMetadataAdapter:
    """Bind an optional GLB to complete Three.js sidecar metadata.

    The adapter never claims to create geometry. If ``glb_path`` is omitted it emits only
    the loader metadata; when supplied, the existing GLB is hash-bound as an artifact.
    """

    capabilities = AdapterCapabilities(
        adapter_id="glb-three-metadata/v1",
        target="glb_three",
        native_features=(
            "meshes", "pbr_materials", "perspective_camera", "punctual_lights",
            "node_extras", "metric_units",
        ),
        sidecar_features=("physics", "interactions", "relations", "area_lights"),
        metadata_schema_version="three-world-metadata/v1",
    )

    def __init__(self, glb_path: str | Path | None = None):
        self.glb_path = Path(glb_path) if glb_path is not None else None

    def export(self, contract: WorldContract, output_dir: str | Path) -> ExportAdapterResult:
        root = Path(output_dir)
        unsupported: list[UnsupportedFeature] = []
        diagnostics: list[AdapterDiagnostic] = []
        artifacts: list[ExportArtifact] = []
        representations = [
            _representation("metric_units", "native"),
            _representation("coordinate_system", "native"),
            _representation("camera", "native"),
            _representation("punctual_lights", "native"),
            _representation("materials", "native"),
        ]
        glb_artifact: ExportArtifact | None = None
        if self.glb_path is not None:
            if self.glb_path.is_file():
                packaged_glb = _copy_immutable(self.glb_path, root / "scene.glb")
                glb_artifact = ExportArtifact.from_path(
                    packaged_glb, media_type="model/gltf-binary", target_role="neutral_scene",
                )
                artifacts.append(glb_artifact)
                representations.extend((
                    _representation("glb.geometry", "native"),
                    _representation("stable_id_extras", "native"),
                ))
            else:
                feature_id = "glb.geometry"
                unsupported.append(UnsupportedFeature(
                    feature_id=feature_id, reason_code="missing_glb",
                    message=f"GLB does not exist: {self.glb_path}", required=True,
                ))
                representations.append(_representation(feature_id, "unsupported"))
        else:
            feature_id = "glb.geometry"
            unsupported.append(_unsupported(
                contract, feature_id, "glb_not_supplied",
                "No GLB was supplied; only target-independent loader metadata was emitted.",
                preserved_in_sidecar=False,
            ))
            representations.append(_representation(feature_id, "unsupported"))

        sidecar_enabled = contract.exports.include_metadata_sidecar
        sidecar_features = (
            ("physics", bool(contract.physics.intents)),
            ("interactions", bool(contract.interactions)),
            ("relations", any(item.relations for item in contract.instances)),
            ("area_lights", any(item.light_type == "area" for item in contract.lights)),
        )
        for feature, present in sidecar_features:
            if not present:
                continue
            if sidecar_enabled:
                representations.append(_representation(
                    feature, "sidecar_metadata", "portable-world-metadata/v1",
                ))
            else:
                unsupported.append(_unsupported(
                    contract, feature, "sidecar_disabled",
                    f"glTF has no portable {feature} representation and sidecar is disabled",
                    preserved_in_sidecar=False,
                ))
                representations.append(_representation(feature, "unsupported"))

        metadata = _common_metadata(contract) if sidecar_enabled else {
            "world_contract_version": contract.schema_version,
            "world_contract_hash": contract.content_hash(),
            "source": contract.source.model_dump(mode="json"),
        }
        metadata.update({
            "schema_version": "three-world-metadata/v1",
            "target_independent_schema_version": (
                "portable-world-metadata/v1" if sidecar_enabled else None
            ),
            "artifact_scope": "glb_bound_metadata" if glb_artifact else "metadata_only",
            "target": {
                "loader": "Three.js GLTFLoader",
                "asset_uri": "scene.glb" if glb_artifact else None,
                "asset_axis": "glTF:+x-right,+y-up,+z-forward",
                "domain_axis": contract.coordinate_system,
                "meters_per_unit": 1.0,
                "stable_id_extra_keys": ["kiro_stable_id", "stable_id", "id"],
                "camera_source": contract.camera.id,
                "punctual_light_extension": "KHR_lights_punctual",
            },
            "glb": glb_artifact.model_dump(mode="json") if glb_artifact else None,
            "sidecar_enabled": sidecar_enabled,
            "representations": [item.model_dump(mode="json") for item in representations],
        })
        manifest_path = _write_json(root / "three_world_metadata.json", metadata)
        manifest = ExportArtifact.from_path(
            manifest_path, media_type="application/json", target_role="three_loader_metadata",
        )
        artifacts.append(manifest)
        unsupported_tuple = tuple(unsupported)
        diagnostics.extend(AdapterDiagnostic(
            stage="feature", code=item.reason_code,
            severity="error" if item.required else "warning", message=item.message,
            feature_id=item.feature_id,
        ) for item in unsupported_tuple)
        return ExportAdapterResult(
            adapter_id=self.capabilities.adapter_id, target="glb_three",
            status=_status(unsupported_tuple), world_contract_hash=contract.content_hash(),
            artifacts=tuple(artifacts), capabilities=self.capabilities,
            feature_representations=tuple(representations),
            unsupported_features=unsupported_tuple, diagnostics=tuple(diagnostics),
            manifests=(manifest,),
        )


def export_godot_metadata(
    contract: WorldContract,
    output_dir: str | Path,
    *,
    project_dir: str | Path | None = None,
) -> ExportAdapterResult:
    return GodotWorldContractAdapter(project_dir).export(contract, output_dir)


def export_glb_three_metadata(
    contract: WorldContract, output_dir: str | Path, *, glb_path: str | Path | None = None,
) -> ExportAdapterResult:
    return GLBThreeMetadataAdapter(glb_path).export(contract, output_dir)


def scene_graph_from_world_contract(contract: WorldContract):
    """Map one approved contract into the retained Godot assembler input without inference."""
    from src.models import (
        DoorSpec, LightType, MaterialProps, PhysicsBody, PhysicsProps, RoomShell,
        SceneGraph, SceneLight, SceneObject, Vec3, WindowSpec,
    )

    materials = {item.id: item for item in contract.materials}
    physics = {item.id: item for item in contract.physics.intents}

    def material(identity: str) -> MaterialProps:
        item = materials[identity]
        return MaterialProps(
            base_color=item.base_color, metallic=item.metallic, roughness=item.roughness,
            emission_color=item.emission_color, emission_strength=item.emission_strength,
        )

    body_types = {
        "static": PhysicsBody.STATIC,
        "dynamic": PhysicsBody.RIGID,
        "kinematic": PhysicsBody.KINEMATIC,
        "trigger": PhysicsBody.STATIC,
    }

    def physics_props(identity: str) -> PhysicsProps:
        item = physics[identity]
        return PhysicsProps(
            body_type=body_types[item.body_mode.value], mass_kg=item.mass_kg,
            friction=item.friction, restitution=item.restitution, can_topple=item.can_topple,
        )

    room = contract.room.dimensions
    objects = [SceneObject(
        id=item.id, name=item.id, object_type=item.category,
        position=Vec3(**item.transform.position_m.model_dump()),
        rotation=Vec3(**item.transform.rotation_deg.model_dump()),
        scale=Vec3(**item.transform.scale.model_dump()),
        dimensions=Vec3(
            x=item.dimensions.width_m, y=item.dimensions.height_m,
            z=item.dimensions.depth_m,
        ),
        physics=physics_props(item.physics_intent_id), material=material(item.material_id),
        mesh_type=item.geometry_strategy, primitive_shape=item.primitive_shape,
        description=item.description,
    ) for item in contract.instances]

    def opening_position(item):
        half_w, half_d = room.width_m / 2, room.depth_m / 2
        if item.wall.value == "north":
            return Vec3(x=item.offset_m, y=item.sill_height_m, z=half_d)
        if item.wall.value == "south":
            return Vec3(x=item.offset_m, y=item.sill_height_m, z=-half_d)
        if item.wall.value == "east":
            return Vec3(x=half_w, y=item.sill_height_m, z=item.offset_m)
        return Vec3(x=-half_w, y=item.sill_height_m, z=item.offset_m)

    doors = [DoorSpec(
        id=item.id, position=opening_position(item), wall=item.wall.value,
        width=item.width_m, height=item.height_m,
        physics=(physics_props(item.physics_intent_id) if item.physics_intent_id else PhysicsProps(
            body_type=PhysicsBody.STATIC, mass_kg=0.0
        )),
    ) for item in contract.openings if item.kind == "door"]
    windows = [WindowSpec(
        id=item.id, position=opening_position(item), wall=item.wall.value,
        width=item.width_m, height=item.height_m, sill_height=item.sill_height_m,
    ) for item in contract.openings if item.kind == "window"]
    lights = [SceneLight(
        id=item.id, name=item.id, light_type=LightType(item.light_type),
        position=Vec3(**item.position_m.model_dump()),
        direction=Vec3(**item.direction.model_dump()), color=item.color,
        color_temperature_k=item.color_temperature_k, intensity=item.intensity,
        range_meters=item.range_m, spot_angle_deg=item.spot_angle_deg,
        cast_shadows=item.cast_shadows,
    ) for item in contract.lights]
    return SceneGraph(
        name=f"world_{contract.source.session_id}",
        description=contract.appearance.architecture_notes or contract.appearance.mood,
        room=RoomShell(
            width=room.width_m, depth=room.depth_m, height=room.height_m,
            floor_material=material(contract.room.floor_material_id),
            wall_material=material(contract.room.wall_material_id),
            ceiling_material=material(contract.room.ceiling_material_id),
        ),
        objects=objects, lights=lights, doors=doors, windows=windows,
        ambient_color="#1a1a2e", ambient_energy=0.3,
    )


def assemble_godot_world_contract(
    contract: WorldContract,
    output_dir: str | Path,
    mesh_paths: dict[str, Path],
) -> tuple[Path, ExportAdapterResult]:
    """Build the V11 Godot fallback from WorldContract and emit portable metadata."""
    from src.assembler.godot_project import assemble_godot_project

    root = Path(output_dir)
    scene = scene_graph_from_world_contract(contract)
    project = assemble_godot_project(
        scene,
        root,
        mesh_paths,
        contract_mode=True,
        world_contract=contract,
    )
    result = GodotWorldContractAdapter(project).export(
        contract, root / "exports" / "godot",
    )
    return project, result
