import * as THREE from "three";
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
