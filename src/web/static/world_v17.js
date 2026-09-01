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
    // Count provisional boxes too: the room is genuinely on screen once the
    // Plan is drawn, and reporting 0 objects while three boxes are visible is
    // the kind of counter/observation disagreement that wastes an afternoon.
    const provisional = planBoxes.size;
    const total = loaded.size + provisional;
    const suffix = provisional > 0 ? ` (${provisional} planned)` : "";
    worldObjectsChip.textContent =
      `${total} object${total === 1 ? "" : "s"}${suffix}`;
    if (total > 0) worldEmpty?.classList.add("hidden");
  }

  function applyTransform(obj, instance) {
    if (!instance) return;
    const p = instance.position || {};
    const r = instance.rotation || {};
    const s = instance.scale || {};
    obj.position.set(Number(p.x) || 0, Number(p.y) || 0, Number(p.z) || 0);
    // rotation may be Euler degrees or a quaternion-ish dict; handle both simply.
    // w must use ?? not || — a 180-degree turn is w === 0, and `0 || 1` would
    // silently rewrite it to the identity rotation.
    if ("w" in r) obj.quaternion.set(Number(r.x) || 0, Number(r.y) || 0, Number(r.z) || 0, Number(r.w ?? 1));
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
    dropPlanBox(objectId);   // the real mesh replaces its provisional box
    setObjectCount();
  }

  // ─── Provisional plan preview ─────────────────────────────────────────────
  //
  // /scene_graph stays empty until world_contract (stage 17), so the panel used
  // to sit black for almost the whole run while the header promised the world
  // would assemble as approvals passed. The Plan has known the room and every
  // placement since spatial_reconstruction (stage 9), so draw THAT first: a real
  // room shell and one grey box per object. Each box is replaced the moment its
  // actual mesh lands, so the room fills in rather than appearing all at once.

  const planRoot = new THREE.Group();
  scene.add(planRoot);
  const planBoxes = new Map();        // objectId -> placeholder Object3D
  let planRoom = null;                // {width, depth, height}

  const SHELL_COLOR = 0x9aa8a0;
  const BOX_COLOR = 0xd8b57a;

  function clearGroup(group) {
    while (group.children.length) group.remove(group.children[0]);
  }

  // Plan space: x across 0..width, y down 0..depth, origin at a room corner.
  // Three space: x across, z into the screen, y up, room centred on the origin.
  function planToWorld(x, y, room) {
    return { x: x - room.width / 2, z: y - room.depth / 2 };
  }

  // Windows carry a height but no sill in the Plan, so assume a conventional
  // sill. Stated here rather than buried as a magic number, because it IS an
  // assumption: if the Plan ever grows a sill field, read that instead.
  const WINDOW_SILL_M = 0.9;

  let planOpenings = [];

  function buildWall(span, height, wallId, material) {
    // A wall is built as rectangles AROUND its openings rather than one plane,
    // so a door is a hole you can see (and walk) through. Solid walls made the
    // door invisible, which in a walkable room means walking into a wall.
    const group = new THREE.Group();
    const mine = planOpenings
      .filter((o) => String(o.wall || "") === wallId)
      .map((o) => {
        const w = Number(o.width) || 0.9;
        const h = Number(o.height) || 2.1;
        const centre = (Number(o.parameter) ?? 0.5) * span;
        const sill = String(o.type || o.kind) === "door" ? 0 : WINDOW_SILL_M;
        return {
          left: Math.max(0, centre - w / 2),
          right: Math.min(span, centre + w / 2),
          sill,
          top: Math.min(height, sill + h),
        };
      })
      .sort((a, b) => a.left - b.left);

    const piece = (pieceSpan, pieceHeight, alongCentre, upCentre) => {
      if (pieceSpan <= 0.001 || pieceHeight <= 0.001) return;
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(pieceSpan, pieceHeight), material
      );
      // Local frame: x runs along the wall from -span/2, y is up.
      mesh.position.set(alongCentre - span / 2, upCentre, 0);
      mesh.receiveShadow = true;
      group.add(mesh);
    };

    let cursor = 0;
    for (const hole of mine) {
      piece(hole.left - cursor, height, (cursor + hole.left) / 2, height / 2);
      const holeSpan = hole.right - hole.left;
      const alongCentre = (hole.left + hole.right) / 2;
      if (hole.sill > 0) piece(holeSpan, hole.sill, alongCentre, hole.sill / 2);
      piece(holeSpan, height - hole.top, alongCentre, (hole.top + height) / 2);
      cursor = hole.right;
    }
    piece(span - cursor, height, (cursor + span) / 2, height / 2);
    return group;
  }

  function buildRoomShell(room) {
    const { width, depth, height } = room;
    const floor = new THREE.Mesh(
      new THREE.BoxGeometry(width, 0.04, depth),
      new THREE.MeshStandardMaterial({ color: 0x8a8378, roughness: 0.95 })
    );
    floor.position.set(0, -0.02, 0);
    floor.receiveShadow = true;
    planRoot.add(floor);

    // The dollhouse cutaway: each wall is a single-sided PLANE facing into the
    // room. A wall between the camera and the room is therefore back-facing and
    // gets culled, so you always look straight in from any orbit angle.
    //
    // This has to be planes, not slabs. BoxGeometry walls still draw their own
    // inner face toward the camera, which renders the room as one solid block
    // however the material is sided.
    const wallMaterial = new THREE.MeshStandardMaterial({
      color: SHELL_COLOR, roughness: 0.95, side: THREE.FrontSide,
    });
    const halfW = width / 2, halfD = depth / 2;
    const walls = [
      ["north", width, 0, -halfD, 0],
      ["south", width, 0, halfD, Math.PI],
      ["west", depth, -halfW, 0, Math.PI / 2],
      ["east", depth, halfW, 0, -Math.PI / 2],
    ];
    for (const [id, span, px, pz, rotY] of walls) {
      const group = buildWall(span, height, id, wallMaterial);
      group.position.set(px, 0, pz);
      group.rotation.y = rotY;
      planRoot.add(group);
    }

    grid.visible = false;   // the real floor replaces the placeholder grid

    // Frame the camera to THIS room. The default (3.5, 1.7, 3.5) was set for an
    // empty scene and lands outside a 4.98m room, looking at it edge-on through
    // a wall. Pull back and up so the whole floor plan is legible at a glance.
    const reach = Math.max(width, depth);
    camera.position.set(reach * 0.85, reach * 0.80, reach * 0.85);
    camera.near = 0.05;
    camera.far = Math.max(200, reach * 12);
    camera.updateProjectionMatrix();
    orbit.target.set(0, Math.min(0.9, height / 3), 0);
    orbit.update();
  }

  function buildPlanBox(placement, room) {
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(placement.width, placement.height, placement.depth),
      // Opaque and warm, so a planned object reads clearly against the shell
      // instead of dissolving into it.
      new THREE.MeshStandardMaterial({ color: BOX_COLOR, roughness: 0.7 })
    );
    const world = planToWorld(placement.x, placement.y, room);
    box.position.set(world.x, placement.height / 2, world.z);
    box.rotation.y = -(Number(placement.rotationDeg) || 0) * Math.PI / 180;
    box.castShadow = true;
    return box;
  }

  async function refreshPlanPreview() {
    if (!sessionId) return;
    let plan = null;
    try {
      const response = await fetch(`/api/session/${sessionId}/plan_preview`);
      if (!response.ok) return;
      plan = await response.json();
    } catch (_) {
      return;
    }
    if (!plan || !plan.ready || !plan.room) return;

    const room = plan.room;
    const changed = !planRoom
      || planRoom.width !== room.width
      || planRoom.depth !== room.depth
      || planRoom.height !== room.height;
    const openingsKey = JSON.stringify(plan.openings || []);
    if (changed || openingsKey !== JSON.stringify(planOpenings)) {
      clearGroup(planRoot);
      planBoxes.clear();
      planRoom = room;
      planOpenings = plan.openings || [];
      buildRoomShell(room);
    }

    for (const placement of plan.objects || []) {
      const id = placement.objectId;
      if (!id || loaded.has(id) || planBoxes.has(id)) continue;
      const box = buildPlanBox(placement, room);
      planRoot.add(box);
      planBoxes.set(id, box);
    }
    setObjectCount();
  }

  function dropPlanBox(objectId) {
    const box = planBoxes.get(objectId);
    if (!box) return;
    planRoot.remove(box);
    planBoxes.delete(objectId);
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
    // Draw the Plan first so the room appears at blockout, not at compile.
    await refreshPlanPreview();
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
        // .quaternion (carries w), NOT .rotation — that is a THREE.Euler in radians, and
        // applyTransform's degree branch would scale it by pi/180 and flatten the object.
        const instance = { position: loaded.get(id)?.position, rotation: loaded.get(id)?.quaternion, scale: loaded.get(id)?.scale };
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

  // Self-attach when the page was opened with ?session=... .
  //
  // unified_v17.js is a classic deferred script and runs BEFORE this module, so
  // on the resume path it reaches world()?.attach() while window.LRWorld is
  // still undefined and silently no-ops - the 3D panel then never polls at all.
  // The fresh-session path only works by accident, because its awaited POST to
  // /session/unified/start gives this module time to register first.
  //
  // Reading the session from the URL here removes the ordering dependency
  // entirely rather than relying on that timing.
  const urlSession = new URLSearchParams(location.search).get("session");
  if (urlSession) {
    window.LRWorld.attach(urlSession);
  }
})();
