"""Strict canonical WorldContract-to-Three.js browser compiler.

This compiler only changes representation. It verifies one finalized contract,
packages approved assets byte-for-byte, and emits a viewer that applies the
contract's camera, transforms, and metallic-roughness materials verbatim.
It never centers, bounds-fits, rescales, clamps, offsets, or normalizes assets.

Requirements: 21.1 and 21.4.
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
    ObjectInstance,
    WorldContract,
    serialize,
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


class BrowserCompiler:
    """Emit a standalone Three.js scene from exactly one WorldContract."""

    schema_version = "browser-world-compiler/v1"
    interface_version = 1

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

        ids = [item.object_id for item in contract.instances]
        if len(ids) != len(set(ids)):
            raise BrowserCompilerError("WorldContract instance IDs must be unique")
        for instance in contract.instances:
            _validate_instance(instance)
        for light in contract.lighting.lights:
            if light.light_type not in _SUPPORTED_LIGHTS:
                raise BrowserCompilerError(
                    f"light {light.light_id!r} type {light.light_type!r} lacks enough "
                    "contract data for an exact Three.js representation"
                )

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
            contract, assets, material_assets, room_uri
        )
        scene_file.write_text(
            json.dumps(scene, indent=2, sort_keys=True), encoding="utf-8"
        )
        index_file.write_text(_INDEX_HTML, encoding="utf-8")
        viewer_script.write_text(_VIEWER_JS, encoding="utf-8")

        core_artifacts = (
            index_file, viewer_script, scene_file, contract_file, hash_payload_file,
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
            "room_shell_ref": contract.room_shell_ref,
            "instances": [item.to_dict() for item in contract.instances],
            "authority": {
                "source": "one_canonical_world_contract",
                "asset_copy": "byte_for_byte_sha256_verified",
                "transform_policy": "exact_no_clamp_rescale_offset_or_normalization",
                "camera_policy": "exact_hash_verified_no_inference",
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
            "schema_version": "three-scene-manifest/v1",
            "interface_version": BrowserCompiler.interface_version,
            "contract_hash": contract.contract_hash,
            "plan_revision": contract.plan_revision,
            "camera_hash": contract.camera_hash,
            "camera": contract.camera.to_dict() if contract.camera else None,
            "room_shell_ref": contract.room_shell_ref,
            "room_asset_uri": room_uri,
            "instances": instances,
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
<title>Canonical World — Browser v1</title>
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
<a href="?v=1" aria-current="page">v1</a><div id="status"></div><div id="errors"></div></div>
<script type="module" src="./viewer.js"></script>
</body>
</html>
'''


_VIEWER_JS = r'''import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";

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
renderer.shadowMap.enabled = contract.lighting.lights.some(light => light.cast_shadows);
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
document.querySelector("#orbit").onclick = () => { firstPerson.unlock(); mode = "orbit"; orbit.enabled = true; };
document.querySelector("#first-person").onclick = () => { orbit.enabled = false; mode = "first-person"; firstPerson.lock(); };
addEventListener("keydown", event => keys.add(event.code));
addEventListener("keyup", event => keys.delete(event.code));
firstPerson.addEventListener("unlock", () => { mode = "orbit"; orbit.enabled = true; });

scene.add(new THREE.AmbientLight(
  new THREE.Color(contract.lighting.ambient_color), contract.lighting.ambient_intensity
));
for (const value of contract.lighting.lights) {
  if (value.light_type !== "point") fail(`Unsupported exact light representation: ${value.light_type}`);
  const light = new THREE.PointLight(new THREE.Color(value.color), value.intensity);
  light.name = value.light_id;
  light.position.set(value.position.x, value.position.y, value.position.z);
  light.castShadow = value.cast_shadows;
  light.userData.temperature = value.temperature;
  scene.add(light);
}

const gltfLoader = new GLTFLoader();
const textureLoader = new THREE.TextureLoader();
const byId = new Map(manifest.instances.map(instance => [instance.object_id, instance]));
const loaded = new Set();

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
        node.castShadow = true;
        node.receiveShadow = true;
      }
    });
    scene.add(root);
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
    const movementRateMetersPerSecond = 2.0;
    if (keys.has("KeyW")) firstPerson.moveForward(movementRateMetersPerSecond * delta);
    if (keys.has("KeyS")) firstPerson.moveForward(-movementRateMetersPerSecond * delta);
    if (keys.has("KeyA")) firstPerson.moveRight(-movementRateMetersPerSecond * delta);
    if (keys.has("KeyD")) firstPerson.moveRight(movementRateMetersPerSecond * delta);
  } else {
    orbit.update();
  }
  renderer.render(scene, camera);
}
render();
'''
