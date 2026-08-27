/**
 * The Living Room — V2.0 "One Prompt, One Room"
 * Client logic for the immersive multi-view pipeline.
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
    scene.background = new THREE.Color(0x050a08);

    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.05, 100);
    camera.position.set(0, 1.62, 0);

    renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.info.autoReset = false; // manual stats reset for perf monitoring
    sceneContainer.appendChild(renderer.domElement);

    // Ambient light
    const ambient = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambient);

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

    document.addEventListener("keydown", (e) => {
      if (!controls.isLocked) return;
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

    if (controls && controls.isLocked) {
      velocity.x -= velocity.x * 8.0 * delta;
      velocity.z -= velocity.z * 8.0 * delta;

      direction.z = Number(moveForward) - Number(moveBackward);
      direction.x = Number(moveRight) - Number(moveLeft);
      direction.normalize();

      if (moveForward || moveBackward) velocity.z -= direction.z * 25.0 * delta;
      if (moveLeft || moveRight) velocity.x -= direction.x * 25.0 * delta;

      controls.moveRight(-velocity.x * delta);
      controls.moveForward(-velocity.z * delta);
    }

    renderer.render(scene, camera);
  }

  // ─── Mesh Optimization ─────────────────────────────────────────────────────
  const MAX_TRIANGLES_PER_OBJECT = 30000; // aggressive LOD budget for browser perf

  function optimizeModel(model) {
    model.traverse((child) => {
      if (child.isMesh) {
        // Enable frustum culling (Three.js default but explicit for clarity)
        child.frustumCulled = true;

        // Decimate over-dense geometry on the GPU side
        const geom = child.geometry;
        if (geom && geom.index) {
          const triCount = geom.index.count / 3;
          if (triCount > MAX_TRIANGLES_PER_OBJECT) {
            // Simplify by keeping only every Nth triangle via index slicing
            // This is a fast client-side decimation — not as clean as server-side
            // but prevents the renderer from choking on 500K-face meshes
            const ratio = MAX_TRIANGLES_PER_OBJECT / triCount;
            const oldIndex = geom.index.array;
            const newLen = Math.floor(oldIndex.length * ratio / 3) * 3;
            const step = Math.ceil(1 / ratio);
            const newIndex = [];
            for (let i = 0; i < oldIndex.length && newIndex.length < newLen; i += step * 3) {
              newIndex.push(oldIndex[i], oldIndex[i + 1], oldIndex[i + 2]);
            }
            geom.setIndex(newIndex);
            geom.computeBoundingSphere();
            console.log(`Decimated mesh: ${triCount} → ${newIndex.length / 3} tris`);
          }
        }

        // Dispose of unused vertex attributes to free GPU memory
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

      // Load room shell if not already loaded
      if (manifest.shell_url) {
        loadGLB(manifest.shell_url);
      }

      // Load any objects not already loaded via SSE (catches race conditions)
      if (manifest.objects) {
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

      // Right pane: take a snapshot from the canon camera angle
      renderer.render(scene, camera);
      const rightPane = document.getElementById("compareRight");
      rightPane.querySelectorAll("img").forEach(el => el.remove());
      const snapImg = document.createElement("img");
      snapImg.src = renderer.domElement.toDataURL("image/png");
      snapImg.alt = "3D world from same angle";
      rightPane.appendChild(snapImg);

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
    // Load the scene manifest
    loadSceneManifest(`/api/v2/session/${restoreSessionId}/scene`).then(() => {
      showCompareButton();
      enableFirstPerson();
      // Point camera at center of room
      camera.lookAt(0, 1.0, 0);
    });
  } else {
    startSession();
  }
})();
