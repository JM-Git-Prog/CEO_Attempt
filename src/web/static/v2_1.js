/**
 * The Living Room — V2.1 "Panorama Room"
 * Client logic for the panorama-first walkable pipeline. Extends V2.0 with an
 * inside-out equirectangular sky-sphere rendered from the session's 360°
 * panorama artifact, so the room is immediately visible from the center even
 * before/independent of per-object meshes. Also fixes the V2.0 restore-path
 * camera aim (which faced away from the placed objects).
 */
(() => {
  "use strict";

  // ─── DOM References ─────────────────────────────────────────────────────────
  const chatOverlay = document.getElementById("chatOverlay");
  const chatMessages = document.getElementById("chatMessages");
  const chatInput = document.getElementById("chatInput");
  const chatSend = document.getElementById("chatSend");
  const buildBtn = document.getElementById("buildBtn");
  const compareBtn = document.getElementById("compareBtn");
  const inspectBtn = document.getElementById("inspectBtn");
  const statusBar = document.getElementById("statusBar");
  const heroImage = document.getElementById("heroImage");
  const compareView = document.getElementById("compareView");
  const sceneContainer = document.getElementById("scene");

  // ─── State ──────────────────────────────────────────────────────────────────
  let sessionId = "";
  let phase = "idle"; // idle | dreaming | building | complete
  let heroCanonUrl = "";
  let eventSource = null;

  // Three.js
  let scene, camera, renderer, controls;
  let moveForward = false, moveBackward = false, moveLeft = false, moveRight = false;
  const velocity = new THREE.Vector3();
  const direction = new THREE.Vector3();

  // ─── Chat UI ────────────────────────────────────────────────────────────────
  function addMessage(role, text) {
    const div = document.createElement("div");
    div.className = `chat-msg ${role}`;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function setStatus(msg) {
    statusBar.textContent = msg;
    statusBar.classList.toggle("hidden", !msg);
  }

  function showBuildButton() {
    buildBtn.classList.remove("hidden");
  }

  function showInspectButton() {
    // Reveal the Inspect Pipeline link and point it at this live session's
    // 8-stage HITL filmstrip. The session id is known the moment a session
    // exists, so no hunting for it.
    if (inspectBtn && sessionId) {
      inspectBtn.href =
        "/api/v2/inspect?session=" + encodeURIComponent(sessionId);
      inspectBtn.classList.remove("hidden");
    }
  }

  function hideBuildButton() {
    buildBtn.classList.add("hidden");
  }

  function showCompareButton() {
    compareBtn.classList.remove("hidden");
  }

  // ─── API Helpers ────────────────────────────────────────────────────────────
  async function apiPost(url, body = {}) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `Request failed (${resp.status})`);
    }
    return resp.json();
  }

  // ─── Session Lifecycle ──────────────────────────────────────────────────────
  async function startSession() {
    try {
      const data = await apiPost("/api/v2/session/start");
      sessionId = data.session_id;
      addMessage("assistant", data.opening_message || "What kind of room are you imagining?");
    } catch (err) {
      addMessage("assistant", "Welcome! Describe the room you'd like to build.");
      console.error("Session start failed:", err);
    }
  }

  async function sendDescription() {
    const msg = chatInput.value.trim();
    if (!msg || !sessionId) return;

    chatInput.value = "";
    chatSend.disabled = true;
    addMessage("user", msg);
    setStatus("DREAMING...");
    phase = "dreaming";

    try {
      const data = await apiPost(`/api/v2/session/${sessionId}/describe`, { message: msg });
      if (data.hero_image_url) {
        heroCanonUrl = data.hero_image_url;
        showHeroImage(data.hero_image_url);
        addMessage("assistant", "Here's my vision for your room. Does this look right?");
        showBuildButton();
        showInspectButton();
        setStatus("");
      } else {
        addMessage("assistant", data.message || "Generating your room...");
      }
    } catch (err) {
      addMessage("assistant", "Something went wrong generating the preview. Try again?");
      console.error("Describe failed:", err);
      setStatus("");
    }
    chatSend.disabled = false;
  }

  async function approveAndBuild() {
    if (!sessionId) return;
    hideBuildButton();
    chatOverlay.classList.add("hidden");
    setStatus("BUILDING YOUR WORLD...");
    phase = "building";

    try {
      await apiPost(`/api/v2/session/${sessionId}/approve`);
      connectSSE();
    } catch (err) {
      setStatus("Build failed — check console");
      console.error("Approve failed:", err);
    }
  }

  // ─── SSE Stream ─────────────────────────────────────────────────────────────
  function connectSSE() {
    if (!sessionId) return;
    eventSource = new EventSource(`/api/v2/session/${sessionId}/stream`);

    eventSource.addEventListener("hero_ready", (e) => {
      const data = JSON.parse(e.data);
      if (data.image_url) showHeroImage(data.image_url);
    });

    eventSource.addEventListener("view_generated", (e) => {
      const data = JSON.parse(e.data);
      setStatus(`Generating views... (${data.view_index}/5)`);
    });

    eventSource.addEventListener("catalog_complete", (e) => {
      const data = JSON.parse(e.data);
      setStatus(`Cataloged ${data.object_count} objects — building meshes...`);
    });

    eventSource.addEventListener("mesh_ready", (e) => {
      const data = JSON.parse(e.data);
      setStatus(`Built: ${data.name} (${data.face_count} faces)`);
      if (data.glb_url) loadGLB(data.glb_url, data.position, data.rotation);
    });

    eventSource.addEventListener("shell_ready", (e) => {
      const data = JSON.parse(e.data);
      setStatus("Room shell ready...");
      if (data.glb_url) loadGLB(data.glb_url);
    });

    eventSource.addEventListener("world_ready", (e) => {
      const data = JSON.parse(e.data);
      setStatus("Loading scene...");
      phase = "complete";
      heroImage.classList.add("hidden");
      // Load full scene manifest for proper lighting/camera/navigation
      if (data.scene_url) {
        loadSceneManifest(data.scene_url).then(() => {
          setStatus("");
          enableFirstPerson();
          showCompareButton();
          addMessage("assistant", "Your room is ready. Click the scene then walk around with WASD + mouse.");
          chatOverlay.classList.remove("hidden");
          setTimeout(() => chatOverlay.classList.add("hidden"), 6000);
        });
      } else {
        setStatus("");
        enableFirstPerson();
        showCompareButton();
      }
    });

    eventSource.addEventListener("error_event", (e) => {
      const data = JSON.parse(e.data);
      setStatus(`Error: ${data.message}`);
      console.error("Pipeline error:", data);
    });

    eventSource.addEventListener("phase_start", (e) => {
      const data = JSON.parse(e.data);
      setStatus(data.message || `Phase: ${data.phase}...`);
    });

    eventSource.addEventListener("world_assembled", (e) => {
      const data = JSON.parse(e.data);
      setStatus(`World assembled: ${data.object_count} objects`);
    });

    eventSource.addEventListener("depth_ready", (e) => {
      // Depth maps generated — no visible UI change needed
    });

    eventSource.onerror = () => {
      console.warn("SSE connection lost, attempting reconnect...");
    };
  }

  // ─── Hero Image Display ─────────────────────────────────────────────────────
  function showHeroImage(url) {
    heroImage.innerHTML = "";
    const img = document.createElement("img");
    img.src = url;
    img.alt = "Generated room preview";
    heroImage.appendChild(img);
    heroImage.classList.remove("hidden");
  }

  // ─── Three.js Scene ─────────────────────────────────────────────────────────
  function initScene() {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);

    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.05, 100);
    camera.position.set(0, 1.62, 0);

    renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.info.autoReset = false; // manual stats reset for perf monitoring
    sceneContainer.appendChild(renderer.domElement);

    // Ambient light
    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambient);

    // Hemisphere light (sky blue + warm ground bounce)
    const hemi = new THREE.HemisphereLight(0xfff8f0, 0x8b6914, 0.4);
    hemi.position.set(0, 10, 0);
    scene.add(hemi);

    // Point light (simulates room lighting)
    const point = new THREE.PointLight(0xfff5e6, 1.0, 10);
    point.position.set(0, 2.4, 0);
    scene.add(point);

    // PointerLock controls (enabled after world is ready)
    controls = new THREE.PointerLockControls(camera, renderer.domElement);

    window.addEventListener("resize", () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    animate();
  }

  function enableFirstPerson() {
    sceneContainer.addEventListener("click", () => {
      if (phase === "complete") controls.lock();
    });

    // Show instruction overlay
    const hint = document.createElement("div");
    hint.id = "controlHint";
    hint.style.cssText = "position:fixed;bottom:60px;left:50%;transform:translateX(-50%);z-index:90;padding:10px 20px;border-radius:8px;background:rgba(10,23,19,0.85);color:#8edbb8;font-size:13px;letter-spacing:0.03em;pointer-events:none;transition:opacity 1s;";
    hint.textContent = "Click to look around • WASD to move";
    document.body.appendChild(hint);

    controls.addEventListener("lock", () => { hint.style.opacity = "0"; });
    controls.addEventListener("unlock", () => { hint.style.opacity = "1"; });

    // Allow WASD even without pointer lock (free movement)
    document.addEventListener("keydown", (e) => {
      switch (e.code) {
        case "KeyW": case "ArrowUp": moveForward = true; break;
        case "KeyS": case "ArrowDown": moveBackward = true; break;
        case "KeyA": case "ArrowLeft": moveLeft = true; break;
        case "KeyD": case "ArrowRight": moveRight = true; break;
      }
    });

    document.addEventListener("keyup", (e) => {
      switch (e.code) {
        case "KeyW": case "ArrowUp": moveForward = false; break;
        case "KeyS": case "ArrowDown": moveBackward = false; break;
        case "KeyA": case "ArrowLeft": moveLeft = false; break;
        case "KeyD": case "ArrowRight": moveRight = false; break;
      }
    });
  }

  // ─── Clock for smooth frame-rate-independent movement ────────────────────
  const clock = new THREE.Clock();

  function animate() {
    requestAnimationFrame(animate);

    const delta = Math.min(clock.getDelta(), 0.05); // cap to prevent spiral on lag spikes

    // Movement works with or without pointer lock
    const isMoving = moveForward || moveBackward || moveLeft || moveRight;
    if (isMoving) {
      velocity.x -= velocity.x * 8.0 * delta;
      velocity.z -= velocity.z * 8.0 * delta;

      direction.z = Number(moveForward) - Number(moveBackward);
      direction.x = Number(moveRight) - Number(moveLeft);
      direction.normalize();

      if (moveForward || moveBackward) velocity.z -= direction.z * 25.0 * delta;
      if (moveLeft || moveRight) velocity.x -= direction.x * 25.0 * delta;

      controls.moveRight(-velocity.x * delta);
      controls.moveForward(-velocity.z * delta);
    } else {
      velocity.x = 0;
      velocity.z = 0;
    }

    renderer.render(scene, camera);
  }

  // ─── Mesh Optimization ─────────────────────────────────────────────────────
  const MAX_TRIANGLES_PER_OBJECT = 30000; // aggressive LOD budget for browser perf

  function optimizeModel(model) {
    model.traverse((child) => {
      if (child.isMesh) {
        // Enable frustum culling
        child.frustumCulled = true;
        // Ensure bounding sphere is computed for culling
        if (child.geometry) {
          child.geometry.computeBoundingSphere();
        }
      }
    });
  }

  function loadGLB(url, position, rotation) {
    const loader = new THREE.GLTFLoader();
    loader.load(url, (gltf) => {
      const model = gltf.scene;
      if (position) {
        model.position.set(position.x || 0, position.y || 0, position.z || 0);
      }
      if (rotation) {
        model.rotation.set(rotation.x || 0, rotation.y || 0, rotation.z || 0);
      }
      optimizeModel(model);
      scene.add(model);
    }, undefined, (err) => {
      console.error("GLB load failed:", url, err);
    });
  }

  // ─── 360° Panorama Sky-Sphere (V2.1) ─────────────────────────────────────────
  // Render the equirectangular panorama on the INSIDE of a large sphere centered
  // at the room center. This gives an immediate, non-empty 360° view of the room
  // from the middle — the "something to see the moment it loads" guarantee.
  let panoramaSphere = null;

  function loadPanorama(url, roomHeight) {
    const loader = new THREE.TextureLoader();
    loader.load(
      url,
      (texture) => {
        texture.colorSpace = THREE.sRGBEncoding; // r128: encoding on the texture
        if ("encoding" in texture) texture.encoding = THREE.sRGBEncoding;
        // Radius large enough to sit outside the room box but finite so objects
        // and shell render in front of it.
        const radius = 20;
        const geo = new THREE.SphereGeometry(radius, 60, 40);
        // Invert so we see the texture from the inside.
        geo.scale(-1, 1, 1);
        const mat = new THREE.MeshBasicMaterial({ map: texture });
        panoramaSphere = new THREE.Mesh(geo, mat);
        // Center the sphere at the room's vertical center so the horizon lines up.
        panoramaSphere.position.set(0, (roomHeight || 2.7) / 2, 0);
        panoramaSphere.userData.v2_panorama = true;
        scene.add(panoramaSphere);
        // Panorama supplies the backdrop; clear the flat background color.
        scene.background = null;
        setStatus("");
      },
      undefined,
      (err) => {
        console.warn("Panorama load failed (falling back to meshes):", url, err);
      }
    );
  }

  // ─── Scene Manifest Loading ─────────────────────────────────────────────────
  let sceneCamera = null; // Camera params from scene.json for Compare mode

  async function loadSceneManifest(url) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) return;
      const manifest = await resp.json();

      // Store camera for compare mode
      sceneCamera = manifest.camera;

      // Apply lighting from manifest
      if (manifest.lighting) {
        for (const light of manifest.lighting) {
          if (light.type === "ambient") {
            // Update existing ambient
            scene.traverse((child) => {
              if (child.isAmbientLight) {
                child.intensity = light.intensity || 0.4;
                child.color.set(light.color || "#ffffff");
              }
            });
          } else if (light.type === "point") {
            const pl = new THREE.PointLight(
              light.color || "#ffffff",
              light.intensity || 1.0,
              light.distance || 10
            );
            pl.position.set(
              light.position.x || 0,
              light.position.y || 2.4,
              light.position.z || 0
            );
            scene.add(pl);
          }
        }
      }

      // Apply navigation spawn position
      if (manifest.navigation && manifest.navigation.spawn_position) {
        const sp = manifest.navigation.spawn_position;
        camera.position.set(sp.x || 0, sp.y || 1.62, sp.z || 0);
      }

      // V2.1: load the 360° panorama sky-sphere for an immediate room backdrop.
      // Uses the manifest panorama_url if present, else the conventional artifact.
      if (!panoramaSphere) {
        const roomH = (manifest.room_dimensions && manifest.room_dimensions[2]) || 2.7;
        const panoUrl = manifest.panorama_url ||
          (sessionId ? `/api/v2/session/${sessionId}/artifact/panorama` : null);
        if (panoUrl) loadPanorama(panoUrl, roomH);
      }

      // Load room shell if not already loaded
      if (manifest.shell_url) {
        loadGLB(manifest.shell_url);
      }

      // V2.1 panorama tier: the panorama sphere + textured shell already show
      // the full room, so we SKIP loading the raw per-object GLBs here (they are
      // untextured grey Hunyuan meshes that clutter the view). Real placed
      // objects belong to the depth/splat tier (v2.2). Set window.V21_SHOW_OBJECTS
      // = true before load to re-enable them for debugging.
      const showObjects = (typeof window !== "undefined" && window.V21_SHOW_OBJECTS === true);
      if (manifest.objects && showObjects) {
        let loaded = 0;
        const total = manifest.objects.length;
        setStatus(`Loading meshes: 0/${total}...`);
        for (const obj of manifest.objects) {
          if (obj.glb_url) {
            // Only load if not already in scene (check by name)
            let found = false;
            scene.traverse((child) => {
              if (child.userData && child.userData.v2_uuid === obj.uuid) found = true;
            });
            if (!found) {
              const loader = new THREE.GLTFLoader();
              loader.load(obj.glb_url, (gltf) => {
                const model = gltf.scene;
                model.userData.v2_uuid = obj.uuid;
                if (obj.position) {
                  model.position.set(obj.position.x || 0, obj.position.y || 0, obj.position.z || 0);
                }
                if (obj.rotation_y_deg) {
                  model.rotation.y = (obj.rotation_y_deg * Math.PI) / 180;
                }
                if (obj.scale) {
                  model.scale.set(obj.scale.x || 1, obj.scale.y || 1, obj.scale.z || 1);
                }
                optimizeModel(model);
                scene.add(model);
                loaded++;
                setStatus(`Loading meshes: ${loaded}/${total}...`);
                console.log(`Loaded: ${obj.name} (${loaded}/${total})`);
                if (loaded >= total) setStatus("");
              }, undefined, (err) => {
                loaded++;
                console.error(`FAILED to load ${obj.name}: ${obj.glb_url}`, err);
                setStatus(`Loading meshes: ${loaded}/${total}...`);
                if (loaded >= total) setStatus("");
              });
            }
          }
        }
      }

      // Brighten background once scene is loaded
      scene.background = new THREE.Color(0x1a2820);

    } catch (err) {
      console.error("Scene manifest load failed:", err);
    }
  }

  // ─── Compare View ───────────────────────────────────────────────────────────
  let compareActive = false;
  let savedCameraPos = null;
  let savedCameraRot = null;

  function toggleCompare() {
    compareActive = !compareActive;
    if (compareActive) {
      // Save current camera state
      savedCameraPos = camera.position.clone();
      savedCameraRot = camera.quaternion.clone();

      // Lock camera to Canon angle (from scene manifest)
      if (sceneCamera) {
        camera.position.set(
          sceneCamera.position.x || 0,
          sceneCamera.position.y || 1.62,
          sceneCamera.position.z || 0
        );
        camera.lookAt(
          sceneCamera.target.x || 0,
          sceneCamera.target.y || 1.4,
          sceneCamera.target.z || -2
        );
      }

      // Unlock pointer if locked
      if (controls && controls.isLocked) controls.unlock();

      // Show compare view
      compareView.classList.remove("hidden");
      const leftPane = document.getElementById("compareLeft");
      if (heroCanonUrl && !leftPane.querySelector("img")) {
        const img = document.createElement("img");
        img.src = heroCanonUrl;
        img.alt = "Canon reference photo";
        leftPane.appendChild(img);
      }

      // Right pane: render a snapshot at the Canon photo's aspect ratio
      const canonAspect = 4 / 3; // 1024x768
      const snapWidth = Math.min(960, window.innerWidth / 2);
      const snapHeight = snapWidth / canonAspect;
      renderer.setSize(snapWidth, snapHeight);
      camera.aspect = canonAspect;
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
      const rightPane = document.getElementById("compareRight");
      rightPane.querySelectorAll("img").forEach(el => el.remove());
      const snapImg = document.createElement("img");
      snapImg.src = renderer.domElement.toDataURL("image/png");
      snapImg.alt = "3D world from same angle";
      rightPane.appendChild(snapImg);
      // Restore renderer to full viewport
      renderer.setSize(window.innerWidth, window.innerHeight);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();

      compareBtn.textContent = "Close Compare";
    } else {
      // Restore camera
      if (savedCameraPos) camera.position.copy(savedCameraPos);
      if (savedCameraRot) camera.quaternion.copy(savedCameraRot);
      compareView.classList.add("hidden");
      compareBtn.textContent = "Compare";
    }
  }

  // ─── Event Wiring ──────────────────────────────────────────────────────────
  chatSend.addEventListener("click", sendDescription);
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendDescription();
    }
  });
  buildBtn.addEventListener("click", approveAndBuild);
  compareBtn.addEventListener("click", toggleCompare);

  // ─── Init ───────────────────────────────────────────────────────────────────
  initScene();

  // Support restoring a completed session via ?session=<id> URL param
  const urlParams = new URLSearchParams(window.location.search);
  const restoreSessionId = urlParams.get("session");
  if (restoreSessionId) {
    // Restore mode: skip chat, load the world directly
    sessionId = restoreSessionId;
    phase = "complete";
    chatOverlay.classList.add("hidden");
    setStatus("Loading scene...");
    // Store hero canon URL for compare mode (don't show the overlay)
    heroCanonUrl = `/api/v2/session/${restoreSessionId}/artifact/hero_canon`;
    // V2.1: also load the panorama immediately (don't wait on scene.json) so the
    // room is visible even if the manifest is slow or object meshes are absent.
    loadPanorama(`/api/v2/session/${restoreSessionId}/artifact/panorama`, 2.7);
    // Load the scene manifest
    loadSceneManifest(`/api/v2/session/${restoreSessionId}/scene`).then(() => {
      showCompareButton();
      enableFirstPerson();
      // Stand at the room center at eye height and face INTO the room (-Z, the
      // hero-camera direction). V2.0 faced +Z (Math.PI) which pointed away from
      // the placed objects — that was the "empty view" on restore.
      camera.position.set(0, 1.62, 0);
      camera.rotation.set(0, 0, 0); // look down -Z
    });
  } else {
    startSession();
  }
})();
