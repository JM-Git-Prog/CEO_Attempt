/*
 * V17 split-screen — RIGHT PANEL: live walkable Three.js world.
 *
 * Pure client over the existing V16 unified pipeline API. It exposes a small
 * hook object on window.LRWorld that the left chat panel (unified_v17.js) calls;
 * the two files stay decoupled — this one never touches the chat DOM.
 *
 * Data sources (all V16 routes, no backend change):
 *   GET  /api/session/{id}/scene_graph          → { objects:[{objectId,name,position,rotation,scale,meshUrl,hasMesh,...}], ready, ... }
 *   GET  /api/session/{id}/mesh/{object_id}      → GLB (model/gltf-binary)
 *   WS   /api/session/{id}/materials             → { type:"material_update", object_id, mesh_url, pass, ... }
 *
 * Rendering strategy honours the spec's "structural integrity over instant
 * frames": meshes load through a sequential queue so a slow GLB never stalls the
 * others, and a failed load degrades to a labelled placeholder box rather than
 * crashing the session.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";

(() => {
  "use strict";

  const canvas = document.getElementById("worldCanvas");
  const worldModeChip = document.getElementById("worldMode");
  const worldObjectsChip = document.getElementById("worldObjects");
  const worldEmpty = document.getElementById("worldEmpty");
  const enterWorldBtn = document.getElementById("enterWorld");
  if (!canvas) return;

  // ─── Renderer / scene / camera ──────────────────────────────────────────

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a1713);

  const camera = new THREE.PerspectiveCamera(60, 1, 0.05, 200);
  camera.position.set(3.5, 1.7, 3.5);
  camera.lookAt(0, 1.2, 0);

  // Baseline lighting so streamed geometry is visible before contract lighting
  // (contract lighting is applied by the compiled world; here we keep it simple).
  const hemi = new THREE.HemisphereLight(0xdff0e8, 0x0a1713, 0.9);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xfff2e0, 1.1);
  key.position.set(4, 6, 3);
  key.castShadow = true;
  scene.add(key);

  const grid = new THREE.GridHelper(20, 20, 0x244238, 0x14271f);
  scene.add(grid);

  const worldRoot = new THREE.Group();
  scene.add(worldRoot);

  // ─── Controls: orbit (default) + first-person pointer lock ──────────────

  const orbit = new OrbitControls(camera, renderer.domElement);
  orbit.enableDamping = true;
  orbit.target.set(0, 1.2, 0);

  const fp = new PointerLockControls(camera, renderer.domElement);
  const keys = new Set();
  let mode = "orbit";
  const MOVE_SPEED = 3.0;       // metres / second
  const EYE_HEIGHT = 1.7;

  function setMode(next) {
    mode = next;
    worldModeChip.textContent = next === "first_person" ? "WALKING" : "ORBIT";
    orbit.enabled = next === "orbit";
  }

  function enterFirstPerson() {
    if (mode === "first_person") return;
    camera.position.y = EYE_HEIGHT;
    fp.lock();
  }
  fp.addEventListener("lock", () => setMode("first_person"));
  fp.addEventListener("unlock", () => setMode("orbit"));

  enterWorldBtn?.addEventListener("click", enterFirstPerson);
  window.addEventListener("keydown", (e) => {
    keys.add(e.code);
    if (e.code === "Escape" && mode === "first_person") fp.unlock();
  });
  window.addEventListener("keyup", (e) => keys.delete(e.code));

  function updateFirstPerson(delta) {
    if (mode !== "first_person") return;
    const step = MOVE_SPEED * delta;
    if (keys.has("KeyW")) fp.moveForward(step);
    if (keys.has("KeyS")) fp.moveForward(-step);
    if (keys.has("KeyA")) fp.moveRight(-step);
    if (keys.has("KeyD")) fp.moveRight(step);
    camera.position.y = EYE_HEIGHT;   // basic gravity: stay at eye height on the floor
  }

  // ─── Resize ──────────────────────────────────────────────────────────────

  function resize() {
    const w = canvas.clientWidth || canvas.parentElement.clientWidth;
    const h = canvas.clientHeight || canvas.parentElement.clientHeight;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(canvas.parentElement || canvas);
  window.addEventListener("resize", resize);

  // ─── Render loop ──────────────────────────────────────────────────────────

  const clock = new THREE.Clock();
  function animate() {
    const delta = Math.min(clock.getDelta(), 0.1);
    updateFirstPerson(delta);
    if (mode === "orbit") orbit.update();
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }
  resize();
  animate();

  // ─── Mesh loading (sequential queue, graceful degradation) ───────────────

  const loader = new GLTFLoader();
  const loaded = new Map();          // objectId → THREE.Object3D
  const queue = [];                  // pending { objectId, meshUrl, instance }
  let draining = false;
  let sessionId = "";

  function setObjectCount() {
    worldObjectsChip.textContent = `${loaded.size} object${loaded.size === 1 ? "" : "s"}`;
    if (loaded.size > 0) worldEmpty?.classList.add("hidden");
  }

  function applyTransform(obj, instance) {
    if (!instance) return;
    const p = instance.position || {};
    const r = instance.rotation || {};
    const s = instance.scale || {};
    obj.position.set(Number(p.x) || 0, Number(p.y) || 0, Number(p.z) || 0);
    // rotation may be Euler degrees or a quaternion-ish dict; handle both simply.
    if ("w" in r) obj.quaternion.set(Number(r.x) || 0, Number(r.y) || 0, Number(r.z) || 0, Number(r.w) || 1);
    else obj.rotation.set(deg(r.x), deg(r.y), deg(r.z));
    obj.scale.set(Number(s.x) || 1, Number(s.y) || 1, Number(s.z) || 1);
  }

  function deg(v) { return ((Number(v) || 0) * Math.PI) / 180; }

  function placeholderFor(instance) {
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.8, 0.5),
      new THREE.MeshStandardMaterial({ color: 0x2a6650, roughness: 0.9, transparent: true, opacity: 0.55 })
    );
    box.castShadow = true;
    applyTransform(box, instance);
    return box;
  }

  function enqueue(objectId, meshUrl, instance) {
    if (!objectId || !meshUrl) return;
    // Replace an existing entry (material hot-swap / regeneration).
    queue.push({ objectId, meshUrl, instance });
    drain();
  }

  async function drain() {
    if (draining) return;
    draining = true;
    while (queue.length) {
      const job = queue.shift();
      try {
        const gltf = await loader.loadAsync(`${job.meshUrl}?t=${Date.now()}`);
        const obj = gltf.scene || gltf.scenes?.[0];
        if (!obj) throw new Error("empty gltf");
        obj.traverse((n) => { if (n.isMesh) { n.castShadow = true; n.receiveShadow = true; } });
        applyTransform(obj, job.instance);
        swapIn(job.objectId, obj);
      } catch (err) {
        // Degrade to a labelled placeholder rather than stalling the queue.
        if (!loaded.has(job.objectId)) swapIn(job.objectId, placeholderFor(job.instance));
        console.warn(`world_v17: mesh ${job.objectId} failed, placeholder used`, err);
      }
    }
    draining = false;
  }

  function swapIn(objectId, obj) {
    const prev = loaded.get(objectId);
    if (prev) worldRoot.remove(prev);
    worldRoot.add(obj);
    loaded.set(objectId, obj);
    setObjectCount();
  }

  // ─── Scene graph polling ──────────────────────────────────────────────────

  let pollTimer = null;
  async function fetchSceneGraph() {
    if (!sessionId) return null;
    try {
      const r = await fetch(`/api/session/${sessionId}/scene_graph`);
      if (!r.ok) return null;
      return await r.json();
    } catch (_) {
      return null;
    }
  }

  async function refreshScene(force = false) {
    const graph = await fetchSceneGraph();
    if (!graph || !Array.isArray(graph.objects)) return;
    for (const instance of graph.objects) {
      const id = instance.objectId || instance.object_id;
      const meshUrl = instance.meshUrl || (id ? `/api/session/${sessionId}/mesh/${encodeURIComponent(id)}` : null);
      const hasMesh = instance.hasMesh !== false;
      if (!id || !meshUrl || !hasMesh) continue;
      if (force || !loaded.has(id)) enqueue(id, meshUrl, instance);
      else {
        const obj = loaded.get(id);
        if (obj) applyTransform(obj, instance);   // keep transforms in sync
      }
    }
    if (graph.ready) stopPolling();
  }

  function startPolling() {
    if (pollTimer) return;
    refreshScene();
    pollTimer = setInterval(refreshScene, 3000);
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ─── Materials WebSocket (pass-2 PBR hot-swap) ──────────────────────────

  let materialsWs = null;
  function connectMaterials() {
    if (!sessionId || materialsWs) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    try {
      materialsWs = new WebSocket(`${proto}://${location.host}/api/session/${sessionId}/materials`);
    } catch (_) {
      return;
    }
    materialsWs.addEventListener("message", (event) => {
      let payload = {};
      try { payload = JSON.parse(event.data); } catch (_) { return; }
      if (payload.type === "material_update" && payload.object_id) {
        const id = payload.object_id;
        const meshUrl = payload.mesh_url || `/api/session/${sessionId}/mesh/${encodeURIComponent(id)}`;
        const instance = { position: loaded.get(id)?.position, rotation: loaded.get(id)?.rotation, scale: loaded.get(id)?.scale };
        enqueue(id, meshUrl, instance);   // reload with pass-2 materials
      }
    });
    materialsWs.addEventListener("close", () => { materialsWs = null; });
    materialsWs.addEventListener("error", () => { try { materialsWs?.close(); } catch (_) {} });
    // Keepalive ping matching the server's ping/pong contract.
    setInterval(() => { try { materialsWs?.readyState === 1 && materialsWs.send("ping"); } catch (_) {} }, 25000);
  }

  // ─── Public hook consumed by unified_v17.js ─────────────────────────────

  window.LRWorld = {
    attach(id) {
      sessionId = id || "";
      if (!sessionId) return;
      startPolling();
      connectMaterials();
    },
    beginBuild() {
      startPolling();
      connectMaterials();
    },
    onObjectReady(_objectId) {
      // A specific object finished; a scene-graph refresh will pick up its mesh
      // once the contract binds it. Cheap to call repeatedly.
      refreshScene();
    },
    refreshScene(force = false) {
      refreshScene(force);
      connectMaterials();
    },
  };
})();
