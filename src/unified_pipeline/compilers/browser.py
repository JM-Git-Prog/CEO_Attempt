"""Strict canonical WorldContract-to-Three.js browser compiler.

This compiler only changes representation. It verifies one finalized contract,
packages approved assets byte-for-byte, and emits a viewer that applies the
contract's camera, transforms, and metallic-roughness materials verbatim.
It never centers, bounds-fits, rescales, clamps, offsets, or normalizes assets.

Requirements: 21.1, 21.4, 22.2, 22.3, and 22.4.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.unified_pipeline.world_contract import (
    FirstPersonNavigation,
    ObjectInstance,
    StaticCollisionBody,
    WorldContract,
    serialize,
    validate_interaction_bindings,
    validate_lighting_config,
    verify_hash,
)


class BrowserCompilerError(ValueError):
    """Raised when exact browser representation would require invented data."""


@dataclass(frozen=True)
class BrowserCompileResult:
    """Immutable inventory of one generated browser scene."""

    output_dir: Path
    index_file: Path
    viewer_script: Path
    scene_manifest_file: Path
    contract_file: Path
    hash_payload_file: Path
    compiler_manifest_file: Path
    contract_hash: str
    plan_revision: str
    artifact_paths: tuple[Path, ...]


_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SUPPORTED_LIGHTS = frozenset({"point"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise BrowserCompilerError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BrowserCompilerError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise BrowserCompilerError(f"{label} must be finite")
    return result


def _validate_lighting(contract: WorldContract) -> None:
    """Reject any lighting value that cannot be represented verbatim."""
    try:
        validate_lighting_config(
            contract.lighting, supported_light_types=_SUPPORTED_LIGHTS
        )
    except ValueError as exc:
        raise BrowserCompilerError(str(exc)) from exc


def _validate_instance(instance: ObjectInstance) -> None:
    if not instance.object_id.strip():
        raise BrowserCompilerError("contract instances require stable object IDs")
    values = {
        "position": (instance.position.x, instance.position.y, instance.position.z),
        "rotation": (
            instance.rotation.x, instance.rotation.y,
            instance.rotation.z, instance.rotation.w,
        ),
        "scale": (instance.scale.x, instance.scale.y, instance.scale.z),
    }
    for label, components in values.items():
        for component in components:
            _finite(component, f"{instance.object_id} {label}")
    if min(values["scale"]) <= 0.0:
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} scale must remain positive"
        )
    if sum(value * value for value in values["rotation"]) <= 0.0:
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} rotation cannot be a zero quaternion"
        )
    binding = instance.asset_binding
    if not binding.mesh_path.strip() or not _SHA256.fullmatch(binding.asset_id):
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} lacks a SHA-256 approved asset binding"
        )
    material = instance.material_intent
    _finite(material.metallic, f"{instance.object_id} metallic")
    _finite(material.roughness, f"{instance.object_id} roughness")
    if not 0.0 <= material.metallic <= 1.0 or not 0.0 <= material.roughness <= 1.0:
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} has invalid PBR metallic-roughness values"
        )
    if not material.base_color.strip():
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} requires explicit base color or texture"
        )
    if material.base_color.startswith("#") and not _HEX_COLOR.fullmatch(material.base_color):
        raise BrowserCompilerError(
            f"instance {instance.object_id!r} base color must be exact #RRGGBB"
        )


def _validate_interactions(contract: WorldContract) -> None:
    """Validate explicit hash-bound behavior without inspecting asset geometry."""
    try:
        validate_interaction_bindings(
            contract.instances,
            contract.interactions,
            require_dynamic_bindings=True,
        )
    except ValueError as exc:
        raise BrowserCompilerError(str(exc)) from exc

    hinged_ids = {
        binding.object_id for binding in contract.interactions
        if binding.kind == "door_hinge"
    }
    stale_door_colliders = sorted(
        body.body_id for body in contract.navigation.static_bodies
        if body.source_id in hinged_ids
    ) if contract.navigation is not None else []
    if stale_door_colliders:
        raise BrowserCompilerError(
            "hinged door cannot remain in static navigation collision: "
            + ", ".join(stale_door_colliders)
        )


def _body_aabb_half_extents(body: StaticCollisionBody) -> tuple[float, float, float]:
    """Return a conservative world AABB for a contract-authored oriented box."""
    q = body.rotation
    norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w
    if abs(norm - 1.0) > 1e-6:
        raise BrowserCompilerError(f"collision body {body.body_id!r} rotation must be unit length")
    xx, yy, zz = q.x * q.x, q.y * q.y, q.z * q.z
    xy, xz, yz = q.x * q.y, q.x * q.z, q.y * q.z
    wx, wy, wz = q.w * q.x, q.w * q.y, q.w * q.z
    rotation = (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )
    half = (body.dimensions.x / 2.0, body.dimensions.y / 2.0, body.dimensions.z / 2.0)
    return tuple(
        sum(abs(rotation[row][column]) * half[column] for column in range(3))
        for row in range(3)
    )


def _select_safe_spawn(navigation: FirstPersonNavigation) -> dict[str, float]:
    values = (
        navigation.player_radius, navigation.player_height,
        navigation.eye_height, navigation.movement_speed, navigation.gravity,
    )
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise BrowserCompilerError("first-person controller values must be positive and finite")
    if navigation.eye_height > navigation.player_height:
        raise BrowserCompilerError("first-person eye height cannot exceed player height")
    if navigation.coordinate_system != "right-handed-x-right-y-up-z-depth":
        raise BrowserCompilerError("first-person navigation coordinate system is unsupported")
    minimum = navigation.bounds_minimum
    maximum = navigation.bounds_maximum
    bounds_min = (minimum.x, minimum.y, minimum.z)
    bounds_max = (maximum.x, maximum.y, maximum.z)
    if any(not math.isfinite(value) for value in (*bounds_min, *bounds_max)) or any(
        low >= high for low, high in zip(bounds_min, bounds_max)
    ):
        raise BrowserCompilerError("first-person navigable bounds are invalid")

    body_ids: set[str] = set()
    body_boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for body in navigation.static_bodies:
        if not body.body_id or body.body_id in body_ids:
            raise BrowserCompilerError("static collision body IDs must be unique and nonempty")
        body_ids.add(body.body_id)
        if body.shape != "box" or body.body_mode != "STATIC":
            raise BrowserCompilerError(
                f"collision body {body.body_id!r} must be an explicit STATIC box"
            )
        center = (body.center.x, body.center.y, body.center.z)
        dimensions = (body.dimensions.x, body.dimensions.y, body.dimensions.z)
        if any(not math.isfinite(value) for value in (*center, *dimensions)) or min(dimensions) <= 0.0:
            raise BrowserCompilerError(f"collision body {body.body_id!r} is invalid")
        body_boxes.append((center, _body_aabb_half_extents(body)))

    radius = navigation.player_radius
    player_half = (radius, navigation.player_height / 2.0, radius)
    for candidate in navigation.spawn_candidates:
        point = (candidate.x, candidate.y, candidate.z)
        if any(not math.isfinite(value) for value in point):
            raise BrowserCompilerError("spawn candidates must be finite")
        player_center = (
            candidate.x,
            candidate.y - navigation.eye_height + player_half[1],
            candidate.z,
        )
        if any(
            player_center[index] - player_half[index] < bounds_min[index]
            or player_center[index] + player_half[index] > bounds_max[index]
            for index in range(3)
        ):
            continue
        collides = any(all(
            abs(player_center[index] - center[index])
            < player_half[index] + half[index] - 1e-9
            for index in range(3)
        ) for center, half in body_boxes)
        if not collides:
            return candidate.to_dict()
    raise BrowserCompilerError("WorldContract has no deterministic safe spawn candidate")


class BrowserCompiler:
    """Emit a standalone Three.js scene from exactly one WorldContract."""

    schema_version = "browser-world-compiler/v5"
    interface_version = 5

    def compile(
        self, contract: WorldContract, output_dir: str | Path
    ) -> BrowserCompileResult:
        if not isinstance(contract, WorldContract):
            raise TypeError(
                "BrowserCompiler requires unified_pipeline.world_contract.WorldContract"
            )
        if not verify_hash(contract):
            raise BrowserCompilerError("WorldContract hash is empty or invalid")
        if not contract.plan_revision.strip() or not contract.camera_hash.strip():
            raise BrowserCompilerError(
                "WorldContract must bind an exact Plan revision and camera hash"
            )
        if contract.camera is None:
            raise BrowserCompilerError(
                "WorldContract lacks exact CameraContract values; browser compiler will not infer them"
            )
        if contract.camera.compute_hash() != contract.camera_hash:
            raise BrowserCompilerError("CameraContract values do not match camera_hash")
        if contract.navigation is None:
            raise BrowserCompilerError(
                "WorldContract lacks exact Plan-derived navigation/collision values; "
                "browser compiler will not infer them"
            )
        selected_spawn = _select_safe_spawn(contract.navigation)

        ids = [item.object_id for item in contract.instances]
        if len(ids) != len(set(ids)):
            raise BrowserCompilerError("WorldContract instance IDs must be unique")
        for instance in contract.instances:
            _validate_instance(instance)
        _validate_interactions(contract)
        _validate_lighting(contract)

        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        assets = self._copy_assets(contract, root)
        material_assets = self._copy_material_assets(contract, root)
        room_uri = self._copy_room_shell_if_asset(contract, root)

        contract_file = root / "world_contract.json"
        hash_payload_file = root / "world_contract_payload.json"
        scene_file = root / "scene.json"
        index_file = root / "index.html"
        viewer_script = root / "viewer.js"
        interaction_runtime_file = root / "interaction_runtime.mjs"
        compiler_manifest_file = root / "compiler_manifest.json"

        contract_file.write_text(serialize(contract), encoding="utf-8")
        hash_payload = contract.to_dict()
        hash_payload.pop("contract_hash", None)
        hash_payload_file.write_text(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        if _sha256(hash_payload_file) != contract.contract_hash:
            raise BrowserCompilerError("canonical hash payload does not match WorldContract")
        scene = self._scene_manifest(
            contract, assets, material_assets, room_uri, selected_spawn
        )
        scene_file.write_text(
            json.dumps(scene, indent=2, sort_keys=True), encoding="utf-8"
        )
        index_file.write_text(_INDEX_HTML, encoding="utf-8")
        viewer_script.write_text(_VIEWER_JS, encoding="utf-8")
        interaction_runtime_file.write_text(_INTERACTION_RUNTIME_JS, encoding="utf-8")

        core_artifacts = (
            index_file, viewer_script, interaction_runtime_file,
            scene_file, contract_file, hash_payload_file,
            *sorted(set(assets.values()), key=lambda path: path.as_posix()),
            *sorted(set(material_assets.values()), key=lambda path: path.as_posix()),
        )
        if room_uri is not None:
            room_path = root / room_uri
            if room_path not in core_artifacts:
                core_artifacts = (*core_artifacts, room_path)
        manifest = {
            "schema_version": self.schema_version,
            "interface_version": self.interface_version,
            "target": {
                "engine": "Three.js",
                "loader": "GLTFLoader",
                "pbr_workflow": "metallic-roughness",
                "controls": ["OrbitControls", "PointerLockControls"],
                "progressive_transport": "SSE/EventSource",
            },
            "contract_hash": contract.contract_hash,
            "plan_revision": contract.plan_revision,
            "camera_hash": contract.camera_hash,
            "camera": contract.camera.to_dict(),
            "navigation": contract.navigation.to_dict(),
            "selected_spawn": selected_spawn,
            "room_shell_ref": contract.room_shell_ref,
            "instances": [item.to_dict() for item in contract.instances],
            "interactions": [item.to_dict() for item in contract.interactions],
            "lighting": contract.lighting.to_dict(),
            "authority": {
                "source": "one_canonical_world_contract",
                "asset_copy": "byte_for_byte_sha256_verified",
                "transform_policy": "exact_no_clamp_rescale_offset_or_normalization",
                "camera_policy": "exact_hash_verified_no_inference",
                "interaction_policy": "explicit_uuid_metadata_no_glb_inference",
                "lighting_policy": "exact_contract_values_no_inference_clamp_or_color_reinterpretation",
                "temperature_policy": "exact_kelvin_metadata_with_explicit_contract_color_as_render_authority",
                "missing_authority_policy": "fail_closed",
            },
            "artifacts": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha256(path),
                }
                for path in core_artifacts
            ],
        }
        compiler_manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        artifacts = (*core_artifacts, compiler_manifest_file)
        return BrowserCompileResult(
            output_dir=root,
            index_file=index_file,
            viewer_script=viewer_script,
            scene_manifest_file=scene_file,
            contract_file=contract_file,
            hash_payload_file=hash_payload_file,
            compiler_manifest_file=compiler_manifest_file,
            contract_hash=contract.contract_hash,
            plan_revision=contract.plan_revision,
            artifact_paths=artifacts,
        )

    @staticmethod
    def _copy_assets(
        contract: WorldContract, root: Path
    ) -> dict[str, Path]:
        asset_dir = root / "assets" / "meshes"
        asset_dir.mkdir(parents=True, exist_ok=True)
        by_hash: dict[str, Path] = {}
        result: dict[str, Path] = {}
        for instance in contract.instances:
            source = Path(instance.asset_binding.mesh_path)
            if not source.is_file():
                raise BrowserCompilerError(
                    f"approved mesh for {instance.object_id!r} does not exist: {source}"
                )
            if source.suffix.lower() != ".glb":
                raise BrowserCompilerError(
                    f"approved mesh for {instance.object_id!r} must be self-contained GLB"
                )
            actual_hash = _sha256(source)
            if actual_hash != instance.asset_binding.asset_id:
                raise BrowserCompilerError(
                    f"approved mesh hash mismatch for {instance.object_id!r}"
                )
            destination = by_hash.get(actual_hash)
            if destination is None:
                destination = asset_dir / f"{actual_hash}.glb"
                BrowserCompiler._verified_copy(source, destination, actual_hash)
                by_hash[actual_hash] = destination
            result[instance.object_id] = destination
        return result

    @staticmethod
    def _verified_copy(source: Path, destination: Path, expected_hash: str) -> None:
        if destination.exists() and _sha256(destination) != expected_hash:
            raise BrowserCompilerError(f"output asset collision at {destination}")
        if not destination.exists():
            shutil.copyfile(source, destination)
        if _sha256(destination) != expected_hash:
            raise BrowserCompilerError("byte-for-byte asset copy verification failed")

    @staticmethod
    def _copy_material_assets(
        contract: WorldContract, root: Path
    ) -> dict[str, Path]:
        texture_dir = root / "assets" / "textures"
        result: dict[str, Path] = {}
        for instance in contract.instances:
            material = instance.material_intent
            references: list[tuple[str, str]] = []
            if not _HEX_COLOR.fullmatch(material.base_color):
                references.append(("base_color", material.base_color))
            if material.normal_map_ref:
                references.append(("normal_map", material.normal_map_ref))
            for role, reference in references:
                source = Path(reference)
                if not source.is_file():
                    raise BrowserCompilerError(
                        f"{role} texture for {instance.object_id!r} does not exist: {source}"
                    )
                digest = _sha256(source)
                suffix = source.suffix.lower()
                destination = texture_dir / f"{digest}{suffix}"
                texture_dir.mkdir(parents=True, exist_ok=True)
                BrowserCompiler._verified_copy(source, destination, digest)
                result[f"{instance.object_id}:{role}"] = destination
        return result

    @staticmethod
    def _copy_room_shell_if_asset(
        contract: WorldContract, root: Path
    ) -> str | None:
        source = Path(contract.room_shell_ref)
        if not source.is_file():
            return None
        if source.suffix.lower() != ".glb":
            raise BrowserCompilerError("renderable room shell must be self-contained GLB")
        digest = _sha256(source)
        destination = root / "assets" / "room" / f"{digest}.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        BrowserCompiler._verified_copy(source, destination, digest)
        return destination.relative_to(root).as_posix()

    @staticmethod
    def _scene_manifest(
        contract: WorldContract,
        assets: dict[str, Path],
        material_assets: dict[str, Path],
        room_uri: str | None,
        selected_spawn: dict[str, float],
    ) -> dict[str, Any]:
        root = next(iter(assets.values())).parents[2] if assets else None
        instances: list[dict[str, Any]] = []
        for instance in contract.instances:
            payload = instance.to_dict()
            payload["asset_uri"] = assets[instance.object_id].relative_to(root).as_posix()
            payload["material_asset_uris"] = {
                role: path.relative_to(root).as_posix()
                for role in ("base_color", "normal_map")
                if (path := material_assets.get(f"{instance.object_id}:{role}")) is not None
            }
            instances.append(payload)
        return {
            "schema_version": "three-scene-manifest/v5",
            "interface_version": BrowserCompiler.interface_version,
            "contract_hash": contract.contract_hash,
            "plan_revision": contract.plan_revision,
            "camera_hash": contract.camera_hash,
            "camera": contract.camera.to_dict() if contract.camera else None,
            "navigation": contract.navigation.to_dict() if contract.navigation else None,
            "selected_spawn": selected_spawn,
            "safe_spawn_policy": "first_safe_contract_candidate_in_declared_order",
            "room_shell_ref": contract.room_shell_ref,
            "room_asset_uri": room_uri,
            "instances": instances,
            "interactions": [item.to_dict() for item in contract.interactions],
            "relationships": [item.to_dict() for item in contract.relationships],
            "lighting": contract.lighting.to_dict(),
            "progressive": {
                "transport": "sse",
                "endpoint": "./events",
                "identity_source": "object_id",
                "authority_policy": "events_trigger_contract_instances_only",
            },
        }


def compile_browser_scene(
    contract: WorldContract, output_dir: str | Path
) -> BrowserCompileResult:
    """Functional entry point for orchestration and compiler selection."""
    return BrowserCompiler().compile(contract, output_dir)


_INDEX_HTML = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canonical World — Browser v5</title>
<style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#111;color:#fff;font:14px system-ui}
#viewport{width:100%;height:100%;display:grid;place-items:center}canvas{max-width:100%;max-height:100%;object-fit:contain}
#hud{position:fixed;top:12px;left:12px;padding:10px;background:#000b;border:1px solid #fff4;border-radius:6px}
button,a{color:#fff;background:#222;border:1px solid #777;padding:5px 8px;margin:2px;text-decoration:none}#errors{color:#ff8c8c}
</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.168.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.168.0/examples/jsm/"}}</script>
</head>
<body>
<div id="viewport"></div>
<div id="hud"><strong id="identity">Loading canonical world…</strong><br>
<button id="orbit">Orbit</button><button id="first-person">First person</button>
<a href="?v=1">v1</a><a href="?v=2">v2</a><a href="?v=3">v3</a><a href="?v=4">v4</a><a href="?v=5" aria-current="page">v5</a><div id="status"></div><div id="errors"></div></div>
<script type="module" src="./viewer.js"></script>
</body>
</html>
'''


_VIEWER_JS = r'''import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import {
  advanceDoorAngle,
  createGrabConstraint,
  impulseVelocityDelta,
  localBoxAngularVelocityDelta,
  releasedGrabState,
  toggleDoorTarget,
} from "./interaction_runtime.mjs";

const statusNode = document.querySelector("#status");
const errorNode = document.querySelector("#errors");
const identityNode = document.querySelector("#identity");
const viewport = document.querySelector("#viewport");
const encoder = new TextEncoder();

function fail(message) {
  errorNode.textContent = String(message);
  throw new Error(String(message));
}
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
async function sha256(text) {
  const bytes = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return [...new Uint8Array(bytes)].map(v => v.toString(16).padStart(2, "0")).join("");
}

const [manifestResponse, contractResponse, hashPayloadResponse] = await Promise.all([
  fetch("./scene.json", {cache: "no-store"}),
  fetch("./world_contract.json", {cache: "no-store"}),
  fetch("./world_contract_payload.json", {cache: "no-store"}),
]);
if (!manifestResponse.ok || !contractResponse.ok || !hashPayloadResponse.ok) {
  fail("Canonical scene artifacts are unavailable");
}
const manifest = await manifestResponse.json();
const contract = await contractResponse.json();
const hashPayloadText = await hashPayloadResponse.text();
const computedHash = await sha256(hashPayloadText);
if (computedHash !== contract.contract_hash || computedHash !== manifest.contract_hash) {
  fail("Canonical WorldContract hash verification failed");
}
if (manifest.plan_revision !== contract.plan_revision || manifest.camera_hash !== contract.camera_hash) {
  fail("Plan revision or camera binding drift detected");
}
if (canonical(manifest.camera) !== canonical(contract.camera)) fail("Camera projection drift detected");
const interfaceVersion = new URLSearchParams(location.search).get("v") || "5";
if (!new Set(["1", "2", "3", "4", "5"]).has(interfaceVersion)) fail(`Unsupported browser interface v${interfaceVersion}`);
const supportsInteractions = interfaceVersion === "3" || interfaceVersion === "4" || interfaceVersion === "5";
for (const link of document.querySelectorAll("a[href^='?v=']")) {
  link.toggleAttribute("aria-current", link.getAttribute("href") === `?v=${interfaceVersion}`);
}
if (interfaceVersion !== "1") {
  if (!contract.navigation || !manifest.navigation) fail("Exact first-person navigation contract is required");
  if (canonical(manifest.navigation) !== canonical(contract.navigation)) fail("Navigation/collision drift detected");
  if (!contract.navigation.spawn_candidates.some(point => canonical(point) === canonical(manifest.selected_spawn))) {
    fail("Compiled spawn is not an exact WorldContract candidate");
  }
}
if (supportsInteractions) {
  if (!Array.isArray(contract.interactions) || !Array.isArray(manifest.interactions)) {
    fail("Explicit interaction metadata is required");
  }
  if (canonical(manifest.interactions) !== canonical(contract.interactions)) {
    fail("Interaction metadata drift detected");
  }
}
if (interfaceVersion === "5" && canonical(manifest.lighting) !== canonical(contract.lighting)) {
  fail("Lighting metadata drift detected");
}
identityNode.textContent = `${contract.plan_revision} · ${contract.contract_hash}`;

const scene = new THREE.Scene();
const cameraData = contract.camera;
if (!cameraData) fail("Exact CameraContract is required");
const camera = new THREE.PerspectiveCamera(
  cameraData.vfov, cameraData.aspect, cameraData.near, cameraData.far
);
camera.position.set(...cameraData.position);
camera.up.set(...cameraData.up);
camera.lookAt(...cameraData.target);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = false;
renderer.setSize(cameraData.raster_width, cameraData.raster_height, false);
renderer.domElement.dataset.contractHash = contract.contract_hash;
renderer.domElement.dataset.planRevision = contract.plan_revision;
viewport.appendChild(renderer.domElement);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(...cameraData.target);
orbit.enableDamping = true;
const firstPerson = new PointerLockControls(camera, renderer.domElement);
const keys = new Set();
let mode = "orbit";
let verticalVelocity = 0.0;
const orbitPosition = new THREE.Vector3(...cameraData.position);
const navigation = contract.navigation;
const selectedSpawn = manifest.selected_spawn;
const contactEpsilon = 1e-9;
const worldAxes = [
  new THREE.Vector3(1, 0, 0),
  new THREE.Vector3(0, 1, 0),
  new THREE.Vector3(0, 0, 1),
];
const staticBodies = interfaceVersion !== "1" ? navigation.static_bodies.map(value => {
  const rotation = new THREE.Quaternion(
    value.rotation.x, value.rotation.y, value.rotation.z, value.rotation.w
  );
  const half = new THREE.Vector3(
    value.dimensions.x / 2, value.dimensions.y / 2, value.dimensions.z / 2
  );
  const axes = worldAxes.map(axis => axis.clone().applyQuaternion(rotation));
  return {
    value,
    center: new THREE.Vector3(value.center.x, value.center.y, value.center.z),
    half,
    axes,
    aabbHalf: new THREE.Vector3(
      projectedRadius(axes, half, worldAxes[0]),
      projectedRadius(axes, half, worldAxes[1]),
      projectedRadius(axes, half, worldAxes[2])
    ),
  };
}) : [];
const playerHalf = interfaceVersion !== "1" ? new THREE.Vector3(
  navigation.player_radius, navigation.player_height / 2, navigation.player_radius
) : null;
const playerCenter = new THREE.Vector3();
const centerDelta = new THREE.Vector3();
const crossAxis = new THREE.Vector3();
const movement = new THREE.Vector3();
const forward = new THREE.Vector3();
const right = new THREE.Vector3();

function projectedRadius(axes, half, axis) {
  return Math.abs(axis.dot(axes[0])) * half.x
    + Math.abs(axis.dot(axes[1])) * half.y
    + Math.abs(axis.dot(axes[2])) * half.z;
}
function playerIntersectsBody(position, body) {
  playerCenter.set(
    position.x,
    position.y - navigation.eye_height + navigation.player_height / 2,
    position.z
  );
  centerDelta.copy(body.center).sub(playerCenter);
  const axes = [...worldAxes, ...body.axes];
  for (const left of worldAxes) {
    for (const other of body.axes) {
      crossAxis.crossVectors(left, other);
      if (crossAxis.lengthSq() > 1e-12) axes.push(crossAxis.clone());
    }
  }
  for (const axis of axes) {
    const playerProjection = projectedRadius(worldAxes, playerHalf, axis);
    const bodyProjection = projectedRadius(body.axes, body.half, axis);
    if (Math.abs(centerDelta.dot(axis)) >= playerProjection + bodyProjection - contactEpsilon) {
      return false;
    }
  }
  return true;
}
function canOccupy(position) {
  playerCenter.set(
    position.x,
    position.y - navigation.eye_height + navigation.player_height / 2,
    position.z
  );
  const low = navigation.bounds_minimum;
  const high = navigation.bounds_maximum;
  if (
    playerCenter.x - playerHalf.x < low.x || playerCenter.x + playerHalf.x > high.x
    || playerCenter.y - playerHalf.y < low.y || playerCenter.y + playerHalf.y > high.y
    || playerCenter.z - playerHalf.z < low.z || playerCenter.z + playerHalf.z > high.z
  ) return false;
  if (staticBodies.some(body => playerIntersectsBody(position, body))) return false;
  for (const body of [...doorBodies.values(), ...dynamicBodies.values()]) {
    if (body.held) continue;
    if (playerIntersectsBody(position, interactionObstacle(body))) return false;
  }
  return true;
}
function enterOrbit() {
  if (grabbedBody) releaseGrab();
  mode = "orbit";
  firstPerson.unlock();
  orbit.enabled = true;
  keys.clear();
  verticalVelocity = 0.0;
  if (interfaceVersion !== "1") {
    camera.position.copy(orbitPosition);
    camera.up.set(...cameraData.up);
    camera.lookAt(...cameraData.target);
    orbit.target.set(...cameraData.target);
    orbit.update();
  }
  statusNode.textContent = "Orbit preview";
}
function enterFirstPerson() {
  orbit.enabled = false;
  mode = "first-person";
  verticalVelocity = 0.0;
  if (interfaceVersion !== "1") {
    camera.position.set(selectedSpawn.x, selectedSpawn.y, selectedSpawn.z);
    if (!canOccupy(camera.position)) return fail("Compiled safe spawn failed runtime collision validation");
  }
  firstPerson.lock();
  statusNode.textContent = supportsInteractions
    ? "WASD move · mouse look · E grab/open · F push · Esc orbit"
    : "WASD to move · mouse to look · Esc for orbit";
}
document.querySelector("#orbit").onclick = enterOrbit;
document.querySelector("#first-person").onclick = enterFirstPerson;
addEventListener("keydown", event => {
  if (["KeyW", "KeyA", "KeyS", "KeyD"].includes(event.code)
      || (supportsInteractions && ["KeyE", "KeyF"].includes(event.code))) {
    event.preventDefault();
  }
  if (supportsInteractions && mode === "first-person" && !event.repeat) {
    if (event.code === "KeyE") interactWithTarget();
    if (event.code === "KeyF") pushTarget();
  }
  keys.add(event.code);
});
addEventListener("keyup", event => keys.delete(event.code));
addEventListener("blur", () => keys.clear());
firstPerson.addEventListener("unlock", () => {
  if (mode === "first-person") enterOrbit();
});

function applyContractLighting(targetScene, targetRenderer, lighting, version) {
  if (version !== "5") {
    // Retained Browser v1-v4 lighting behavior; do not change released interfaces.
    targetScene.add(new THREE.AmbientLight(
      new THREE.Color(lighting.ambient_color), lighting.ambient_intensity
    ));
    for (const value of lighting.lights) {
      if (value.light_type !== "point") fail(`Unsupported exact light representation: ${value.light_type}`);
      const light = new THREE.PointLight(new THREE.Color(value.color), value.intensity);
      light.name = value.light_id;
      light.position.set(value.position.x, value.position.y, value.position.z);
      light.castShadow = value.cast_shadows;
      light.userData.temperature = value.temperature;
      targetScene.add(light);
    }
    return;
  }

  targetRenderer.shadowMap.enabled = lighting.lights.some(light => light.cast_shadows);
  if (targetRenderer.shadowMap.enabled) {
    targetRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
  }
  const ambient = new THREE.AmbientLight();
  ambient.color.set(lighting.ambient_color);
  ambient.intensity = lighting.ambient_intensity;
  ambient.userData.contractLighting = {
    color: lighting.ambient_color,
    intensity: lighting.ambient_intensity,
  };
  targetScene.add(ambient);
  for (const value of lighting.lights) {
    if (value.light_type !== "point") fail(`Unsupported exact light representation: ${value.light_type}`);
    const light = new THREE.PointLight();
    light.name = value.light_id;
    light.color.set(value.color);
    light.intensity = value.intensity;
    light.position.set(value.position.x, value.position.y, value.position.z);
    light.castShadow = value.cast_shadows;
    light.shadow.autoUpdate = value.cast_shadows;
    if (value.cast_shadows) {
      light.shadow.mapSize.set(1024, 1024);
      light.shadow.bias = -0.001;
    }
    light.userData.temperature = value.temperature;
    light.userData.contractLighting = {
      color: value.color,
      intensity: value.intensity,
      temperature_kelvin: value.temperature,
      temperature_semantics: "metadata_only_explicit_contract_color_is_render_authority",
      cast_shadows: value.cast_shadows,
    };
    targetScene.add(light);
  }
}
applyContractLighting(scene, renderer, contract.lighting, interfaceVersion);

const gltfLoader = new GLTFLoader();
const textureLoader = new THREE.TextureLoader();
const byId = new Map(manifest.instances.map(instance => [instance.object_id, instance]));
const loaded = new Set();
const interactionByObjectId = new Map(
  (supportsInteractions ? contract.interactions : []).map(binding => [binding.object_id, binding])
);
const interactionProxies = [];
const dynamicBodies = new Map();
const doorBodies = new Map();
const interactionRaycaster = new THREE.Raycaster();
const screenCenter = new THREE.Vector2(0, 0);
const temporaryQuaternion = new THREE.Quaternion();
const temporaryAxis = new THREE.Vector3();
const temporaryVector = new THREE.Vector3();
let grabbedBody = null;
let physicsAccumulator = 0.0;
const fixedPhysicsStep = 1 / 60;

async function contractMaterial(instance) {
  const intent = instance.material_intent;
  const parameters = {metalness: intent.metallic, roughness: intent.roughness};
  const uris = instance.material_asset_uris;
  if (uris.base_color) {
    parameters.map = await textureLoader.loadAsync(uris.base_color);
    parameters.map.colorSpace = THREE.SRGBColorSpace;
    parameters.color = new THREE.Color(0xffffff);
  } else {
    parameters.color = new THREE.Color(intent.base_color);
  }
  if (uris.normal_map) parameters.normalMap = await textureLoader.loadAsync(uris.normal_map);
  const material = new THREE.MeshStandardMaterial(parameters);
  material.userData.contractMaterialIntent = intent;
  return material;
}

function updateInteractionProxy(body) {
  body.root.updateWorldMatrix(true, false);
  body.root.getWorldPosition(body.rootWorldPosition);
  body.root.getWorldQuaternion(body.rootWorldQuaternion);
  body.proxy.position.copy(body.centerOffset)
    .applyQuaternion(body.rootWorldQuaternion).add(body.rootWorldPosition);
  body.proxy.quaternion.copy(body.rootWorldQuaternion).multiply(body.colliderRotation);
  body.proxy.updateMatrixWorld(true);
}

function registerInteraction(root, instance, binding) {
  const collider = binding.collider;
  const proxy = new THREE.Mesh(
    new THREE.BoxGeometry(
      collider.dimensions.x, collider.dimensions.y, collider.dimensions.z
    ),
    new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, depthWrite: false, colorWrite: false,
    })
  );
  proxy.name = `interaction:${binding.interaction_id}`;
  proxy.userData = {
    interactionId: binding.interaction_id,
    objectId: binding.object_id,
    contractHash: contract.contract_hash,
  };
  scene.add(proxy);
  interactionProxies.push(proxy);
  const body = {
    binding,
    root,
    proxy,
    centerOffset: new THREE.Vector3(
      collider.center_offset.x, collider.center_offset.y, collider.center_offset.z
    ),
    colliderHalf: new THREE.Vector3(
      collider.dimensions.x / 2, collider.dimensions.y / 2, collider.dimensions.z / 2
    ),
    colliderRotation: new THREE.Quaternion(
      collider.rotation.x, collider.rotation.y, collider.rotation.z, collider.rotation.w
    ),
    rootWorldPosition: new THREE.Vector3(),
    rootWorldQuaternion: new THREE.Quaternion(),
  };
  proxy.userData.body = body;

  if (binding.kind === "dynamic") {
    Object.assign(body, {
      velocity: new THREE.Vector3(),
      angularVelocity: new THREE.Vector3(),
      held: false,
      grabConstraint: null,
    });
    dynamicBodies.set(binding.object_id, body);
  } else if (binding.kind === "door_hinge") {
    const metadata = binding.door;
    const pivot = new THREE.Object3D();
    pivot.name = `hinge:${binding.interaction_id}`;
    pivot.position.set(metadata.pivot.x, metadata.pivot.y, metadata.pivot.z);
    scene.add(pivot);
    pivot.attach(root);
    Object.assign(body, {
      pivot,
      axis: new THREE.Vector3(metadata.axis.x, metadata.axis.y, metadata.axis.z),
      angleDeg: metadata.initial_angle_deg,
      targetAngleDeg: metadata.initial_angle_deg,
    });
    pivot.quaternion.setFromAxisAngle(body.axis, THREE.MathUtils.degToRad(body.angleDeg));
    doorBodies.set(binding.object_id, body);
  }
  updateInteractionProxy(body);
}

function targetInteraction() {
  interactionRaycaster.setFromCamera(screenCenter, camera);
  for (const hit of interactionRaycaster.intersectObjects(interactionProxies, false)) {
    const body = hit.object.userData.body;
    if (!body) continue;
    const metadata = body.binding.kind === "dynamic"
      ? body.binding.dynamic : body.binding.door;
    const maximum = body.binding.kind === "dynamic"
      ? metadata.grab_distance_m : metadata.interaction_distance_m;
    if (hit.distance <= maximum) return {body, hit};
  }
  return null;
}

function releaseGrab() {
  if (!grabbedBody) return;
  Object.assign(grabbedBody, releasedGrabState());
  grabbedBody = null;
  statusNode.textContent = "Object released";
}

function interactWithTarget() {
  if (grabbedBody) {
    releaseGrab();
    return;
  }
  const target = targetInteraction();
  if (!target) return;
  const body = target.body;
  if (body.binding.kind === "door_hinge") {
    const metadata = body.binding.door;
    body.targetAngleDeg = toggleDoorTarget(
      body.angleDeg, metadata.lower_limit_deg, metadata.upper_limit_deg
    );
    statusNode.textContent = `Door ${body.binding.object_id} hinge engaged`;
    return;
  }
  if (body.binding.dynamic.can_grab) {
    const metadata = body.binding.dynamic;
    body.held = true;
    body.velocity.set(0, 0, 0);
    body.angularVelocity.set(0, 0, 0);
    body.grabConstraint = createGrabConstraint(metadata, contract.contract_hash);
    grabbedBody = body;
    statusNode.textContent = `Holding ${body.binding.object_id} · E to release`;
  }
}

function applyImpulse(body, impulse, worldPoint) {
  const metadata = body.binding.dynamic;
  const linearDelta = impulseVelocityDelta(
    {x: impulse.x, y: impulse.y, z: impulse.z}, metadata.mass_kg
  );
  body.velocity.add(new THREE.Vector3(linearDelta.x, linearDelta.y, linearDelta.z));
  if (!metadata.can_topple) return;

  const angularImpulse = new THREE.Vector3().crossVectors(
    worldPoint.clone().sub(body.proxy.position), impulse
  );
  const inverseOrientation = body.proxy.quaternion.clone().invert();
  angularImpulse.applyQuaternion(inverseOrientation);
  const localDelta = localBoxAngularVelocityDelta(
    {x: angularImpulse.x, y: angularImpulse.y, z: angularImpulse.z},
    body.binding.collider.dimensions,
    metadata.mass_kg
  );
  body.angularVelocity.add(
    new THREE.Vector3(localDelta.x, localDelta.y, localDelta.z)
      .applyQuaternion(body.proxy.quaternion)
  );
}

function pushTarget() {
  const target = targetInteraction();
  if (!target || target.body.binding.kind !== "dynamic") return;
  const body = target.body;
  const metadata = body.binding.dynamic;
  if (!metadata.can_push || body.held) return;
  camera.getWorldDirection(temporaryVector);
  applyImpulse(
    body,
    temporaryVector.clone().multiplyScalar(metadata.push_impulse_ns),
    target.hit.point
  );
  statusNode.textContent = `Impulse applied to ${body.binding.object_id}`;
}

function updateDoor(body, delta) {
  const metadata = body.binding.door;
  body.angleDeg = advanceDoorAngle(
    body.angleDeg,
    body.targetAngleDeg,
    metadata.angular_speed_deg_s,
    delta,
    metadata.lower_limit_deg,
    metadata.upper_limit_deg
  );
  body.pivot.quaternion.setFromAxisAngle(
    body.axis, THREE.MathUtils.degToRad(body.angleDeg)
  );
  updateInteractionProxy(body);
}

function interactionObstacle(body) {
  updateInteractionProxy(body);
  const axes = worldAxes.map(axis => axis.clone().applyQuaternion(body.proxy.quaternion));
  return {
    center: body.proxy.position,
    half: body.colliderHalf,
    axes,
    aabbHalf: new THREE.Vector3(
      projectedRadius(axes, body.colliderHalf, worldAxes[0]),
      projectedRadius(axes, body.colliderHalf, worldAxes[1]),
      projectedRadius(axes, body.colliderHalf, worldAxes[2])
    ),
  };
}

function dynamicAabbHalf(body) {
  return interactionObstacle(body).aabbHalf;
}

function resolveDynamicContact(body, delta) {
  updateInteractionProxy(body);
  const half = dynamicAabbHalf(body);
  const center = body.proxy.position;
  const low = navigation.bounds_minimum;
  const high = navigation.bounds_maximum;
  const metadata = body.binding.dynamic;
  for (const axis of ["x", "y", "z"]) {
    const minimum = low[axis] + half[axis];
    const maximum = high[axis] - half[axis];
    let correction = 0;
    if (center[axis] < minimum) correction = minimum - center[axis];
    if (center[axis] > maximum) correction = maximum - center[axis];
    if (correction) {
      body.root.position[axis] += correction;
      if (body.velocity[axis] * correction < 0) {
        body.velocity[axis] *= -metadata.restitution;
      }
      if (axis === "y") {
        body.velocity.x *= Math.max(0, 1 - metadata.friction * delta * 60);
        body.velocity.z *= Math.max(0, 1 - metadata.friction * delta * 60);
      }
      updateInteractionProxy(body);
    }
  }

  for (const obstacle of staticBodies) {
    const dx = half.x + obstacle.aabbHalf.x - Math.abs(body.proxy.position.x - obstacle.center.x);
    const dy = half.y + obstacle.aabbHalf.y - Math.abs(body.proxy.position.y - obstacle.center.y);
    const dz = half.z + obstacle.aabbHalf.z - Math.abs(body.proxy.position.z - obstacle.center.z);
    if (dx <= 0 || dy <= 0 || dz <= 0) continue;
    const penetration = Math.min(dx, dy, dz);
    const axis = penetration === dx ? "x" : penetration === dy ? "y" : "z";
    const direction = body.proxy.position[axis] >= obstacle.center[axis] ? 1 : -1;
    body.root.position[axis] += direction * penetration;
    if (body.velocity[axis] * direction < 0) {
      body.velocity[axis] *= -metadata.restitution;
    }
    if (axis === "y") {
      body.velocity.x *= Math.max(0, 1 - metadata.friction * delta * 60);
      body.velocity.z *= Math.max(0, 1 - metadata.friction * delta * 60);
    }
    updateInteractionProxy(body);
  }

  for (const other of [...doorBodies.values(), ...dynamicBodies.values()]) {
    if (other === body) continue;
    const obstacle = interactionObstacle(other);
    const dx = half.x + obstacle.aabbHalf.x
      - Math.abs(body.proxy.position.x - obstacle.center.x);
    const dy = half.y + obstacle.aabbHalf.y
      - Math.abs(body.proxy.position.y - obstacle.center.y);
    const dz = half.z + obstacle.aabbHalf.z
      - Math.abs(body.proxy.position.z - obstacle.center.z);
    if (dx <= 0 || dy <= 0 || dz <= 0) continue;
    const penetration = Math.min(dx, dy, dz);
    const axis = penetration === dx ? "x" : penetration === dy ? "y" : "z";
    const direction = body.proxy.position[axis] >= obstacle.center[axis] ? 1 : -1;
    body.root.position[axis] += direction * penetration;
    if (body.velocity[axis] * direction < 0) {
      body.velocity[axis] *= -metadata.restitution;
    }
    if (axis === "y") {
      body.velocity.x *= Math.max(0, 1 - metadata.friction * delta * 60);
      body.velocity.z *= Math.max(0, 1 - metadata.friction * delta * 60);
    }
    updateInteractionProxy(body);
  }
}

function simulateDynamic(body, delta) {
  const metadata = body.binding.dynamic;
  if (body.held) {
    const constraint = body.grabConstraint;
    if (!constraint || constraint.contractHash !== contract.contract_hash) {
      return fail("Grab constraint lost its WorldContract binding");
    }
    camera.getWorldDirection(temporaryVector);
    const desiredCenter = camera.position.clone().addScaledVector(
      temporaryVector, constraint.holdDistanceM
    );
    body.velocity.copy(desiredCenter.sub(body.proxy.position))
      .multiplyScalar(constraint.stiffness);
  } else {
    body.velocity.y -= navigation.gravity * delta;
  }
  body.root.position.addScaledVector(body.velocity, delta);
  if (metadata.can_topple && body.angularVelocity.lengthSq() > 1e-12) {
    const angularSpeed = body.angularVelocity.length();
    temporaryAxis.copy(body.angularVelocity).multiplyScalar(1 / angularSpeed);
    temporaryQuaternion.setFromAxisAngle(temporaryAxis, angularSpeed * delta);
    body.root.quaternion.premultiply(temporaryQuaternion);
  }
  body.velocity.multiplyScalar(Math.max(0, 1 - metadata.linear_damping * delta));
  body.angularVelocity.multiplyScalar(Math.max(0, 1 - metadata.angular_damping * delta));
  resolveDynamicContact(body, delta);
  if (!body.held && body.velocity.lengthSq() < 1e-8) body.velocity.set(0, 0, 0);
  if (!body.held && body.angularVelocity.lengthSq() < 1e-8) body.angularVelocity.set(0, 0, 0);
}

function simulateInteractions(delta) {
  for (const body of doorBodies.values()) updateDoor(body, delta);
  physicsAccumulator = Math.min(physicsAccumulator + delta, fixedPhysicsStep * 5);
  while (physicsAccumulator >= fixedPhysicsStep) {
    for (const body of dynamicBodies.values()) simulateDynamic(body, fixedPhysicsStep);
    physicsAccumulator -= fixedPhysicsStep;
  }
}

async function loadInstance(objectId) {
  if (loaded.has(objectId)) return;
  const instance = byId.get(objectId);
  if (!instance) return fail(`SSE referenced object outside WorldContract: ${objectId}`);
  loaded.add(objectId);
  try {
    const [gltf, material] = await Promise.all([
      gltfLoader.loadAsync(instance.asset_uri), contractMaterial(instance)
    ]);
    const root = gltf.scene;
    root.name = instance.object_id;
    root.position.set(instance.position.x, instance.position.y, instance.position.z);
    root.quaternion.set(
      instance.rotation.x, instance.rotation.y, instance.rotation.z, instance.rotation.w
    );
    root.scale.set(instance.scale.x, instance.scale.y, instance.scale.z);
    root.userData = {
      ...root.userData,
      stableId: instance.object_id,
      contractHash: contract.contract_hash,
      planRevision: contract.plan_revision,
      assetBinding: instance.asset_binding,
      materialIntent: instance.material_intent,
      physicsIntent: instance.physics_intent,
    };
    root.traverse(node => {
      if (node.isMesh) {
        node.material = material.clone();
        if (interfaceVersion === "5") {
          node.castShadow = true;
          node.receiveShadow = true;
        }
      }
    });
    scene.add(root);
    if (supportsInteractions) {
      const binding = interactionByObjectId.get(instance.object_id);
      if (binding) registerInteraction(root, instance, binding);
    }
    statusNode.textContent = `${loaded.size}/${byId.size} contract assets loaded`;
  } catch (error) {
    loaded.delete(objectId);
    fail(`GLTFLoader failed for ${objectId}: ${error}`);
  }
}

async function loadRoom() {
  if (!manifest.room_asset_uri) return;
  const gltf = await gltfLoader.loadAsync(manifest.room_asset_uri);
  gltf.scene.name = "contract-room-shell";
  gltf.scene.userData.contractRoomShellRef = contract.room_shell_ref;
  if (interfaceVersion === "5") {
    gltf.scene.traverse(node => {
      if (node.isMesh) {
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
  }
  scene.add(gltf.scene);
}
await loadRoom();

function acceptProgress(raw) {
  const event = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (event.contract_hash !== contract.contract_hash || event.plan_revision !== contract.plan_revision) {
    return;
  }
  const objectId = event.object_id || event.payload?.object_id;
  if (objectId) void loadInstance(objectId);
  if (event.event_type === "contract.ready" || event.event_type === "world.ready") {
    for (const id of byId.keys()) void loadInstance(id);
  }
}
const streamUrl = new URL(manifest.progressive.endpoint, location.href);
streamUrl.searchParams.set("contract_hash", contract.contract_hash);
streamUrl.searchParams.set("plan_revision", contract.plan_revision);
const eventSource = new EventSource(streamUrl);
eventSource.onmessage = event => acceptProgress(event.data);
eventSource.addEventListener("object.final", event => acceptProgress(event.data));
eventSource.addEventListener("contract.ready", event => acceptProgress(event.data));
let fallbackStarted = false;
eventSource.onerror = () => {
  if (fallbackStarted) return;
  fallbackStarted = true;
  eventSource.close();
  for (const id of byId.keys()) void loadInstance(id);
};

const clock = new THREE.Clock();
function render() {
  requestAnimationFrame(render);
  const delta = Math.min(clock.getDelta(), 0.1);
  if (mode === "first-person" && firstPerson.isLocked) {
    if (interfaceVersion === "1") {
      const movementRateMetersPerSecond = 2.0;
      if (keys.has("KeyW")) firstPerson.moveForward(movementRateMetersPerSecond * delta);
      if (keys.has("KeyS")) firstPerson.moveForward(-movementRateMetersPerSecond * delta);
      if (keys.has("KeyA")) firstPerson.moveRight(-movementRateMetersPerSecond * delta);
      if (keys.has("KeyD")) firstPerson.moveRight(movementRateMetersPerSecond * delta);
    } else {
      const forwardInput = Number(keys.has("KeyW")) - Number(keys.has("KeyS"));
      const rightInput = Number(keys.has("KeyD")) - Number(keys.has("KeyA"));
      if (forwardInput || rightInput) {
        camera.getWorldDirection(forward);
        forward.y = 0;
        const forwardLength = Math.hypot(forward.x, forward.z);
        if (forwardLength > 1e-12) {
          forward.multiplyScalar(1 / forwardLength);
          right.set(-forward.z, 0, forward.x);
          movement.copy(forward).multiplyScalar(forwardInput).addScaledVector(right, rightInput);
          const movementLength = Math.hypot(movement.x, movement.z);
          if (movementLength > 1e-12) movement.multiplyScalar(1 / movementLength);
          const distance = navigation.movement_speed * delta;
          const candidate = camera.position.clone();
          candidate.x += movement.x * distance;
          if (canOccupy(candidate)) camera.position.x = candidate.x;
          candidate.copy(camera.position);
          candidate.z += movement.z * distance;
          if (canOccupy(candidate)) camera.position.z = candidate.z;
        }
      }
      verticalVelocity -= navigation.gravity * delta;
      const verticalCandidate = camera.position.clone();
      verticalCandidate.y += verticalVelocity * delta;
      if (canOccupy(verticalCandidate)) {
        camera.position.y = verticalCandidate.y;
      } else {
        verticalVelocity = 0.0;
      }
    }
  } else {
    orbit.update();
  }
  if (supportsInteractions) simulateInteractions(delta);
  renderer.render(scene, camera);
}
render();

// QA Harness — only active when ?qa=1 is in the URL
if (new URLSearchParams(location.search).has("qa")) {
  window.__qa = Object.freeze({
    getObjectCount: () => {
      return loaded.size;
    },
    getObjectPosition: (objectId) => {
      const instance = byId.get(objectId);
      if (!instance) return null;
      const root = scene.getObjectByName(objectId);
      if (!root) return null;
      root.updateWorldMatrix(true, false);
      const pos = new THREE.Vector3();
      root.getWorldPosition(pos);
      return {x: pos.x, y: pos.y, z: pos.z};
    },
    getLighting: () => {
      const lights = [];
      scene.traverse(node => {
        if (node.isLight && !node.isAmbientLight) {
          const pos = new THREE.Vector3();
          node.getWorldPosition(pos);
          const color = "#" + node.color.getHexString();
          let type = "unknown";
          if (node.isPointLight) type = "point";
          else if (node.isDirectionalLight) type = "directional";
          else if (node.isSpotLight) type = "spot";
          lights.push({
            type,
            position: {x: pos.x, y: pos.y, z: pos.z},
            color,
            intensity: node.intensity,
          });
        }
      });
      return lights;
    },
    triggerInteraction: (objectId, action) => {
      return new Promise((resolve) => {
        const binding = interactionByObjectId.get(objectId);
        if (!binding) {
          resolve({success: false, state: {error: "no_interaction_binding"}});
          return;
        }
        if (action === "click" || action === "open") {
          if (binding.kind === "door_hinge") {
            const body = doorBodies.get(objectId);
            if (!body) {
              resolve({success: false, state: {error: "door_body_not_found"}});
              return;
            }
            const metadata = binding.door;
            body.targetAngleDeg = toggleDoorTarget(
              body.angleDeg, metadata.lower_limit_deg, metadata.upper_limit_deg
            );
            const targetAngle = body.targetAngleDeg;
            const checkSettled = () => {
              if (Math.abs(body.angleDeg - targetAngle) < 0.5) {
                resolve({success: true, state: {angleDeg: body.angleDeg, settled: true}});
              } else {
                requestAnimationFrame(checkSettled);
              }
            };
            setTimeout(checkSettled, 100);
          } else {
            resolve({success: false, state: {error: "unsupported_action_for_kind"}});
          }
        } else if (action === "grab") {
          if (binding.kind !== "dynamic" || !binding.dynamic.can_grab) {
            resolve({success: false, state: {error: "object_not_grabbable"}});
            return;
          }
          const body = dynamicBodies.get(objectId);
          if (!body) {
            resolve({success: false, state: {error: "dynamic_body_not_found"}});
            return;
          }
          body.held = true;
          body.velocity.set(0, 0, 0);
          body.angularVelocity.set(0, 0, 0);
          body.grabConstraint = createGrabConstraint(binding.dynamic, contract.contract_hash);
          grabbedBody = body;
          resolve({success: true, state: {held: true}});
        } else if (action === "release") {
          const body = dynamicBodies.get(objectId);
          if (!body || !body.held) {
            resolve({success: false, state: {error: "object_not_held"}});
            return;
          }
          Object.assign(body, releasedGrabState());
          grabbedBody = null;
          const waitForSettle = () => {
            setTimeout(() => {
              const settled = body.velocity.lengthSq() < 1e-6
                && body.angularVelocity.lengthSq() < 1e-6;
              if (settled) {
                updateInteractionProxy(body);
                resolve({success: true, state: {
                  settled: true,
                  position: {x: body.proxy.position.x, y: body.proxy.position.y, z: body.proxy.position.z},
                }});
              } else {
                waitForSettle();
              }
            }, 100);
          };
          waitForSettle();
        } else if (action === "push") {
          if (binding.kind !== "dynamic" || !binding.dynamic.can_push) {
            resolve({success: false, state: {error: "object_not_pushable"}});
            return;
          }
          const body = dynamicBodies.get(objectId);
          if (!body || body.held) {
            resolve({success: false, state: {error: "dynamic_body_not_available"}});
            return;
          }
          const metadata = binding.dynamic;
          const pushDir = new THREE.Vector3(0, 0, -1);
          camera.getWorldDirection(pushDir);
          applyImpulse(
            body,
            pushDir.multiplyScalar(metadata.push_impulse_ns),
            body.proxy.position.clone()
          );
          const waitForSettle = () => {
            setTimeout(() => {
              const settled = body.velocity.lengthSq() < 1e-6
                && body.angularVelocity.lengthSq() < 1e-6;
              if (settled) {
                updateInteractionProxy(body);
                resolve({success: true, state: {
                  settled: true,
                  position: {x: body.proxy.position.x, y: body.proxy.position.y, z: body.proxy.position.z},
                }});
              } else {
                waitForSettle();
              }
            }, 100);
          };
          waitForSettle();
        } else {
          resolve({success: false, state: {error: "unknown_action"}});
        }
      });
    },
    getSceneGraph: () => {
      const nodes = [];
      for (const [objectId, instance] of byId.entries()) {
        if (!loaded.has(objectId)) continue;
        const root = scene.getObjectByName(objectId);
        if (!root) continue;
        root.updateWorldMatrix(true, false);
        const pos = new THREE.Vector3();
        root.getWorldPosition(pos);
        let meshCount = 0;
        root.traverse(node => { if (node.isMesh) meshCount++; });
        nodes.push({
          objectId,
          meshCount,
          position: {x: pos.x, y: pos.y, z: pos.z},
        });
      }
      return nodes;
    },
    captureFrame: () => {
      return new Promise((resolve) => {
        requestAnimationFrame(() => {
          renderer.render(scene, camera);
          const dataUrl = renderer.domElement.toDataURL("image/png");
          resolve(dataUrl.replace(/^data:image\/png;base64,/, ""));
        });
      });
    },
    getRendererInfo: () => {
      return {
        antialias: renderer.getContext().getContextAttributes().antialias || false,
        preserveDrawingBuffer: renderer.getContext().getContextAttributes().preserveDrawingBuffer || false,
        seed: manifest.deterministic_seed || null,
      };
    },
  });
}
'''


_INTERACTION_RUNTIME_JS = r'''function finite(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be finite`);
  }
  return value;
}

export function toggleDoorTarget(currentDeg, lowerDeg, upperDeg) {
  finite(currentDeg, "current door angle");
  finite(lowerDeg, "lower door limit");
  finite(upperDeg, "upper door limit");
  if (lowerDeg >= upperDeg) throw new RangeError("door limits are invalid");
  return Math.abs(currentDeg - lowerDeg) <= Math.abs(currentDeg - upperDeg)
    ? upperDeg : lowerDeg;
}

export function advanceDoorAngle(
  currentDeg, targetDeg, speedDegPerSecond, deltaSeconds, lowerDeg, upperDeg
) {
  for (const [value, label] of [
    [currentDeg, "current door angle"], [targetDeg, "target door angle"],
    [speedDegPerSecond, "door angular speed"], [deltaSeconds, "door delta"],
    [lowerDeg, "lower door limit"], [upperDeg, "upper door limit"],
  ]) finite(value, label);
  if (lowerDeg >= upperDeg || speedDegPerSecond <= 0 || deltaSeconds < 0) {
    throw new RangeError("door integration metadata is invalid");
  }
  const boundedTarget = Math.max(lowerDeg, Math.min(upperDeg, targetDeg));
  const difference = boundedTarget - currentDeg;
  const step = speedDegPerSecond * deltaSeconds;
  const advanced = currentDeg + Math.sign(difference) * Math.min(Math.abs(difference), step);
  return Math.max(lowerDeg, Math.min(upperDeg, advanced));
}

export function createGrabConstraint(metadata, contractHash) {
  if (!metadata || typeof metadata !== "object") {
    throw new TypeError("grab metadata is required");
  }
  finite(metadata.hold_distance_m, "hold distance");
  finite(metadata.hold_stiffness, "hold stiffness");
  if (metadata.hold_distance_m <= 0 || metadata.hold_stiffness <= 0 || !contractHash) {
    throw new RangeError("grab constraint metadata is invalid");
  }
  return Object.freeze({
    holdDistanceM: metadata.hold_distance_m,
    stiffness: metadata.hold_stiffness,
    contractHash,
  });
}

export function releasedGrabState() {
  return Object.freeze({held: false, grabConstraint: null});
}

export function impulseVelocityDelta(impulse, massKg) {
  finite(massKg, "interaction mass");
  if (massKg <= 0) throw new RangeError("interaction mass must be positive");
  return Object.freeze({
    x: finite(impulse.x, "impulse.x") / massKg,
    y: finite(impulse.y, "impulse.y") / massKg,
    z: finite(impulse.z, "impulse.z") / massKg,
  });
}

export function localBoxAngularVelocityDelta(localAngularImpulse, dimensions, massKg) {
  finite(massKg, "interaction mass");
  const width = finite(dimensions.x, "collider width");
  const height = finite(dimensions.y, "collider height");
  const depth = finite(dimensions.z, "collider depth");
  if (massKg <= 0 || Math.min(width, height, depth) <= 0) {
    throw new RangeError("box inertia metadata must be positive");
  }
  const coefficient = massKg / 12;
  return Object.freeze({
    x: finite(localAngularImpulse.x, "angular impulse.x")
      / (coefficient * (height * height + depth * depth)),
    y: finite(localAngularImpulse.y, "angular impulse.y")
      / (coefficient * (width * width + depth * depth)),
    z: finite(localAngularImpulse.z, "angular impulse.z")
      / (coefficient * (width * width + height * height)),
  });
}
'''