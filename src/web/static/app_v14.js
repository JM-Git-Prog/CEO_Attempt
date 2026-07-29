/**
 * V14 Three.js World Viewer
 *
 * Renders real textured 3D meshes using Three.js GLTFLoader with PBR
 * metallic-roughness materials, orbit + first-person navigation, progressive
 * SSE loading, and Pass 2 material hot-swap via WebSocket.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7
 */

/* global THREE */

// ---------------------------------------------------------------------------
// Imports — loaded via importmap or CDN in the HTML template
// ---------------------------------------------------------------------------
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const NAV_MODE_ORBIT = 'orbit';
const NAV_MODE_FPS = 'fps';
const MOVE_SPEED = 4.0; // meters per second
const LOOK_SPEED = 0.002;

// ---------------------------------------------------------------------------
// V14WorldViewer Class
// ---------------------------------------------------------------------------

export class V14WorldViewer {
  /**
   * @param {string} containerId - DOM element ID for the WebGL canvas container
   */
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) {
      throw new Error(`V14WorldViewer: container element '${containerId}' not found`);
    }

    // Scene state
    this.scene = new THREE.Scene();
    this.objects = new Map(); // objectId -> THREE.Group
    this.roomShell = null;
    this.sessionId = null;
    this.navMode = NAV_MODE_ORBIT;

    // Loading state
    this.totalObjects = 0;
    this.loadedObjects = 0;
    this.startTime = null;
    this.currentStage = '';
    this.isComplete = false;

    // Movement state (FPS mode)
    this._moveForward = false;
    this._moveBackward = false;
    this._moveLeft = false;
    this._moveRight = false;
    this._velocity = new THREE.Vector3();
    this._direction = new THREE.Vector3();
    this._prevTime = performance.now();

    // SSE / WebSocket connections
    this._eventSource = null;
    this._materialSocket = null;

    // Loader
    this._loader = new GLTFLoader();

    // Initialize renderer, camera, controls, lights
    this._initRenderer();
    this._initCamera();
    this._initLights();
    this._initControls();
    this._initProgressOverlay();

    // Start render loop
    this._animate = this._animate.bind(this);
    this._animate();

    // Handle window resize
    this._onResize = this._onResize.bind(this);
    window.addEventListener('resize', this._onResize);
  }

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------

  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(this.renderer.domElement);
  }

  _initCamera() {
    const aspect = this.container.clientWidth / this.container.clientHeight;
    this.camera = new THREE.PerspectiveCamera(60, aspect, 0.05, 100);
    this.camera.position.set(0, 1.6, 3); // eye-level, slightly back
  }

  _initLights() {
    // Ambient light for base illumination
    const ambient = new THREE.AmbientLight(0xffffff, 0.4);
    this.scene.add(ambient);

    // Hemisphere light for natural sky/ground fill
    const hemi = new THREE.HemisphereLight(0xb1e1ff, 0xb97a20, 0.3);
    this.scene.add(hemi);

    // Directional light (sun-like) with shadows
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(3, 5, 2);
    dir.castShadow = true;
    dir.shadow.mapSize.width = 2048;
    dir.shadow.mapSize.height = 2048;
    dir.shadow.camera.near = 0.1;
    dir.shadow.camera.far = 20;
    dir.shadow.camera.left = -5;
    dir.shadow.camera.right = 5;
    dir.shadow.camera.top = 5;
    dir.shadow.camera.bottom = -5;
    this.scene.add(dir);

    // Environment map for PBR reflections (neutral studio HDRI approximation)
    const pmremGenerator = new THREE.PMREMGenerator(this.renderer);
    pmremGenerator.compileEquirectangularShader();
    const neutralEnv = this._createNeutralEnvironment(pmremGenerator);
    this.scene.environment = neutralEnv;
    pmremGenerator.dispose();
  }

  _createNeutralEnvironment(pmremGenerator) {
    // Generate a simple gradient environment for PBR reflections
    const envScene = new THREE.Scene();
    const envGeo = new THREE.SphereGeometry(1, 32, 16);
    const envMat = new THREE.MeshBasicMaterial({
      color: 0xcccccc,
      side: THREE.BackSide,
    });
    envScene.add(new THREE.Mesh(envGeo, envMat));

    // Add a bright spot for specular highlight direction
    const spotGeo = new THREE.SphereGeometry(0.1, 8, 8);
    const spotMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const spot = new THREE.Mesh(spotGeo, spotMat);
    spot.position.set(0.5, 0.8, 0.3);
    envScene.add(spot);

    const envMap = pmremGenerator.fromScene(envScene, 0.04).texture;
    envScene.traverse(child => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) child.material.dispose();
    });
    return envMap;
  }

  _initControls() {
    // Orbit controls (default mode)
    this.orbitControls = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbitControls.enableDamping = true;
    this.orbitControls.dampingFactor = 0.1;
    this.orbitControls.target.set(0, 1, 0);
    this.orbitControls.minDistance = 0.5;
    this.orbitControls.maxDistance = 20;
    this.orbitControls.enabled = true;

    // First-person (pointer lock) controls
    this.fpsControls = new PointerLockControls(this.camera, this.renderer.domElement);
    this.fpsControls.addEventListener('lock', () => this._onPointerLock(true));
    this.fpsControls.addEventListener('unlock', () => this._onPointerLock(false));

    // Keyboard handlers for FPS movement
    this._onKeyDown = this._onKeyDown.bind(this);
    this._onKeyUp = this._onKeyUp.bind(this);
    document.addEventListener('keydown', this._onKeyDown);
    document.addEventListener('keyup', this._onKeyUp);
  }

  _initProgressOverlay() {
    // Create the progress overlay element if it doesn't already exist
    let overlay = document.getElementById('v14-progress-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'v14-progress-overlay';
      overlay.className = 'v14-progress-overlay';
      overlay.innerHTML = `
        <div class="v14-progress-content">
          <div class="v14-progress-spinner"></div>
          <div class="v14-progress-stage" id="v14-stage">Connecting...</div>
          <div class="v14-progress-objects" id="v14-objects"></div>
          <div class="v14-progress-time" id="v14-time"></div>
          <div class="v14-progress-eta" id="v14-eta"></div>
        </div>
      `;
      this.container.appendChild(overlay);
    }
    this._progressOverlay = overlay;
  }

  // -------------------------------------------------------------------------
  // Navigation Mode Switching
  // -------------------------------------------------------------------------

  /**
   * Switch to orbit controls (default mode).
   */
  enableOrbitControls() {
    this.navMode = NAV_MODE_ORBIT;
    this.fpsControls.unlock();
    this.orbitControls.enabled = true;
    this._moveForward = false;
    this._moveBackward = false;
    this._moveLeft = false;
    this._moveRight = false;
    this._emitNavModeChange();
  }

  /**
   * Switch to first-person controls (WASD + mouse look).
   */
  enableFirstPersonControls() {
    this.navMode = NAV_MODE_FPS;
    this.orbitControls.enabled = false;
    this.fpsControls.lock();
    this._emitNavModeChange();
  }

  /**
   * Toggle between orbit and first-person modes.
   */
  toggleNavigationMode() {
    if (this.navMode === NAV_MODE_ORBIT) {
      this.enableFirstPersonControls();
    } else {
      this.enableOrbitControls();
    }
  }

  _onPointerLock(locked) {
    if (!locked && this.navMode === NAV_MODE_FPS) {
      // User hit Escape — revert to orbit
      this.enableOrbitControls();
    }
  }

  _onKeyDown(event) {
    if (this.navMode !== NAV_MODE_FPS) return;
    switch (event.code) {
      case 'KeyW': case 'ArrowUp': this._moveForward = true; break;
      case 'KeyS': case 'ArrowDown': this._moveBackward = true; break;
      case 'KeyA': case 'ArrowLeft': this._moveLeft = true; break;
      case 'KeyD': case 'ArrowRight': this._moveRight = true; break;
    }
  }

  _onKeyUp(event) {
    if (this.navMode !== NAV_MODE_FPS) return;
    switch (event.code) {
      case 'KeyW': case 'ArrowUp': this._moveForward = false; break;
      case 'KeyS': case 'ArrowDown': this._moveBackward = false; break;
      case 'KeyA': case 'ArrowLeft': this._moveLeft = false; break;
      case 'KeyD': case 'ArrowRight': this._moveRight = false; break;
    }
  }

  _emitNavModeChange() {
    this.container.dispatchEvent(
      new CustomEvent('navmodechange', { detail: { mode: this.navMode } })
    );
  }

  // -------------------------------------------------------------------------
  // Mesh Loading
  // -------------------------------------------------------------------------

  /**
   * Load the room shell mesh from the server.
   * @param {string} glbUrl - URL to the room shell GLB
   * @returns {Promise<THREE.Group>}
   */
  async loadRoomShell(glbUrl) {
    const gltf = await this._loadGLTF(glbUrl);
    if (this.roomShell) {
      this.scene.remove(this.roomShell);
      this._disposeObject(this.roomShell);
    }
    this.roomShell = gltf.scene;
    this.roomShell.name = 'room_shell';

    // Ensure PBR rendering on room shell materials
    this.roomShell.traverse(child => {
      if (child.isMesh) {
        child.receiveShadow = true;
        // Keep existing material (should be MeshStandardMaterial from GLTF)
        if (child.material && !child.material.isMeshStandardMaterial) {
          const oldMat = child.material;
          child.material = new THREE.MeshStandardMaterial({
            map: oldMat.map || null,
            side: THREE.DoubleSide,
          });
          oldMat.dispose();
        }
      }
    });

    this.scene.add(this.roomShell);
    return this.roomShell;
  }

  /**
   * Load and place an object mesh into the scene.
   * @param {string} objectId - Unique object identifier
   * @param {string} glbUrl - URL to the object GLB
   * @param {number[]} position - [x, y, z] in meters
   * @param {number[]} rotation - [rx, ry, rz] in degrees
   * @param {number[]} scale - [sx, sy, sz] scale factors
   * @returns {Promise<THREE.Group>}
   */
  async loadObject(objectId, glbUrl, position = [0, 0, 0], rotation = [0, 0, 0], scale = [1, 1, 1]) {
    const gltf = await this._loadGLTF(glbUrl);
    const obj = gltf.scene;
    obj.name = `object_${objectId}`;
    obj.userData.objectId = objectId;

    // Position, rotation, scale
    obj.position.set(position[0], position[1], position[2]);
    obj.rotation.set(
      THREE.MathUtils.degToRad(rotation[0]),
      THREE.MathUtils.degToRad(rotation[1]),
      THREE.MathUtils.degToRad(rotation[2])
    );
    obj.scale.set(scale[0], scale[1], scale[2]);

    // PBR rendering setup
    obj.traverse(child => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    // Replace previous version if exists (e.g., material hot-swap)
    if (this.objects.has(objectId)) {
      const prev = this.objects.get(objectId);
      this.scene.remove(prev);
      this._disposeObject(prev);
    }

    this.objects.set(objectId, obj);
    this.scene.add(obj);
    this.loadedObjects++;
    this._updateProgress();
    return obj;
  }

  /**
   * Hot-swap material for an object when Pass 2 PBR completes.
   * Reloads the GLB and replaces the mesh in-place without page reload.
   * @param {string} objectId - Object to update
   * @param {string} updatedGlbUrl - URL to updated GLB with PBR materials
   */
  async updateMaterial(objectId, updatedGlbUrl) {
    const existing = this.objects.get(objectId);
    if (!existing) return;

    // Preserve transform from existing object
    const pos = existing.position.clone();
    const rot = existing.rotation.clone();
    const scl = existing.scale.clone();

    // Load updated mesh
    const gltf = await this._loadGLTF(updatedGlbUrl);
    const updated = gltf.scene;
    updated.name = `object_${objectId}`;
    updated.userData.objectId = objectId;

    // Apply preserved transform
    updated.position.copy(pos);
    updated.rotation.copy(rot);
    updated.scale.copy(scl);

    // PBR rendering setup
    updated.traverse(child => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    // Swap in scene
    this.scene.remove(existing);
    this._disposeObject(existing);
    this.objects.set(objectId, updated);
    this.scene.add(updated);
  }

  /**
   * Load a GLTF/GLB file via the GLTFLoader.
   * @param {string} url
   * @returns {Promise<import('three/examples/jsm/loaders/GLTFLoader.js').GLTF>}
   */
  _loadGLTF(url) {
    return new Promise((resolve, reject) => {
      this._loader.load(url, resolve, undefined, reject);
    });
  }

  /**
   * Dispose of a Three.js object and its children, freeing GPU memory.
   */
  _disposeObject(obj) {
    obj.traverse(child => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach(m => this._disposeMaterial(m));
        } else {
          this._disposeMaterial(child.material);
        }
      }
    });
  }

  _disposeMaterial(material) {
    if (material.map) material.map.dispose();
    if (material.normalMap) material.normalMap.dispose();
    if (material.roughnessMap) material.roughnessMap.dispose();
    if (material.metalnessMap) material.metalnessMap.dispose();
    if (material.aoMap) material.aoMap.dispose();
    if (material.emissiveMap) material.emissiveMap.dispose();
    material.dispose();
  }

  // -------------------------------------------------------------------------
  // SSE Integration — Progressive Loading
  // -------------------------------------------------------------------------

  /**
   * Connect to the V14 SSE endpoint and progressively load meshes as they arrive.
   * @param {string} sessionId
   */
  connectSSE(sessionId) {
    this.sessionId = sessionId;
    this.startTime = Date.now();
    this.loadedObjects = 0;
    this.isComplete = false;
    this._showProgress();

    const url = `/api/session/${sessionId}/v14/events`;
    this._eventSource = new EventSource(url);

    this._eventSource.onmessage = (event) => {
      this._handleSSEEvent(JSON.parse(event.data));
    };

    this._eventSource.onerror = () => {
      // SSE connection lost — will auto-reconnect
      this._updateStageText('Reconnecting...');
    };
  }

  /**
   * Handle an individual SSE event from the V14 pipeline.
   */
  async _handleSSEEvent(data) {
    switch (data.type) {
      case 'stage_change':
        this.currentStage = data.stage || '';
        if (data.total_objects != null) {
          this.totalObjects = data.total_objects;
        }
        this._updateProgress();
        break;

      case 'room_shell_ready':
        await this._loadRoomShellFromSession();
        this._updateProgress();
        break;

      case 'object_complete': {
        const objId = data.object_id;
        const meshUrl = data.mesh_url || `/api/session/${this.sessionId}/mesh/${objId}`;
        const position = data.position || [0, 0, 0];
        const rotation = data.rotation || [0, 0, 0];
        const scale = data.scale || [1, 1, 1];
        await this.loadObject(objId, meshUrl, position, rotation, scale);
        this._updateProgress();
        break;
      }

      case 'done':
        this.isComplete = true;
        this.totalObjects = data.object_count || this.totalObjects;
        this._hideProgress();
        this._eventSource.close();
        this._eventSource = null;
        // Connect WebSocket for Pass 2 material updates
        this._connectMaterialsWebSocket();
        break;

      case 'error':
        this._updateStageText(`Error: ${data.message || 'Pipeline failed'}`);
        if (this._eventSource) {
          this._eventSource.close();
          this._eventSource = null;
        }
        break;
    }
  }

  async _loadRoomShellFromSession() {
    const url = `/api/session/${this.sessionId}/room_shell`;
    try {
      await this.loadRoomShell(url);
    } catch (err) {
      console.warn('V14WorldViewer: Failed to load room shell:', err);
    }
  }

  // -------------------------------------------------------------------------
  // WebSocket — Pass 2 Material Hot-Swap
  // -------------------------------------------------------------------------

  /**
   * Connect to the WebSocket endpoint for Pass 2 PBR material notifications.
   */
  _connectMaterialsWebSocket() {
    if (!this.sessionId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/session/${this.sessionId}/v14/materials`;

    this._materialSocket = new WebSocket(wsUrl);

    this._materialSocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'material_update') {
        const meshUrl = data.mesh_url || `/api/session/${this.sessionId}/mesh/${data.object_id}`;
        this.updateMaterial(data.object_id, meshUrl);
      }
    };

    this._materialSocket.onclose = () => {
      // Attempt reconnect after a short delay if session is still active
      if (this.sessionId && !this._destroyed) {
        setTimeout(() => this._connectMaterialsWebSocket(), 3000);
      }
    };

    this._materialSocket.onerror = () => {
      // Silently handle — onclose will trigger reconnect
    };
  }

  // -------------------------------------------------------------------------
  // Progress Indicator
  // -------------------------------------------------------------------------

  _showProgress() {
    if (this._progressOverlay) {
      this._progressOverlay.style.display = 'flex';
    }
  }

  _hideProgress() {
    if (this._progressOverlay) {
      this._progressOverlay.style.display = 'none';
    }
  }

  _updateProgress() {
    this._updateStageText(this.currentStage || 'Processing...');
    this._updateObjectCount();
    this._updateElapsedTime();
    this._updateETA();
  }

  _updateStageText(text) {
    const el = document.getElementById('v14-stage');
    if (el) el.textContent = text;
  }

  _updateObjectCount() {
    const el = document.getElementById('v14-objects');
    if (el) {
      if (this.totalObjects > 0) {
        el.textContent = `Objects: ${this.loadedObjects} / ${this.totalObjects}`;
      } else {
        el.textContent = '';
      }
    }
  }

  _updateElapsedTime() {
    const el = document.getElementById('v14-time');
    if (el && this.startTime) {
      const elapsed = (Date.now() - this.startTime) / 1000;
      el.textContent = `Elapsed: ${this._formatDuration(elapsed)}`;
    }
  }

  _updateETA() {
    const el = document.getElementById('v14-eta');
    if (el && this.startTime && this.totalObjects > 0 && this.loadedObjects > 0) {
      const elapsed = (Date.now() - this.startTime) / 1000;
      const rate = elapsed / this.loadedObjects;
      const remaining = (this.totalObjects - this.loadedObjects) * rate;
      el.textContent = `ETA: ~${this._formatDuration(remaining)}`;
    } else if (el) {
      el.textContent = '';
    }
  }

  _formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  // -------------------------------------------------------------------------
  // Render Loop
  // -------------------------------------------------------------------------

  _animate() {
    if (this._destroyed) return;
    requestAnimationFrame(this._animate);

    const time = performance.now();
    const delta = (time - this._prevTime) / 1000;
    this._prevTime = time;

    // FPS movement
    if (this.navMode === NAV_MODE_FPS && this.fpsControls.isLocked) {
      this._velocity.x -= this._velocity.x * 10.0 * delta;
      this._velocity.z -= this._velocity.z * 10.0 * delta;

      this._direction.z = Number(this._moveForward) - Number(this._moveBackward);
      this._direction.x = Number(this._moveRight) - Number(this._moveLeft);
      this._direction.normalize();

      if (this._moveForward || this._moveBackward) {
        this._velocity.z -= this._direction.z * MOVE_SPEED * delta;
      }
      if (this._moveLeft || this._moveRight) {
        this._velocity.x -= this._direction.x * MOVE_SPEED * delta;
      }

      this.fpsControls.moveRight(-this._velocity.x * delta);
      this.fpsControls.moveForward(-this._velocity.z * delta);
    }

    // Orbit damping
    if (this.navMode === NAV_MODE_ORBIT && this.orbitControls.enabled) {
      this.orbitControls.update();
    }

    // Update elapsed time display while loading
    if (!this.isComplete && this.startTime) {
      this._updateElapsedTime();
      this._updateETA();
    }

    this.renderer.render(this.scene, this.camera);
  }

  // -------------------------------------------------------------------------
  // Resize Handling
  // -------------------------------------------------------------------------

  _onResize() {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // -------------------------------------------------------------------------
  // Cleanup
  // -------------------------------------------------------------------------

  /**
   * Destroy the viewer, releasing all resources.
   */
  destroy() {
    this._destroyed = true;

    // Close SSE
    if (this._eventSource) {
      this._eventSource.close();
      this._eventSource = null;
    }

    // Close WebSocket
    if (this._materialSocket) {
      this._materialSocket.close();
      this._materialSocket = null;
    }

    // Remove event listeners
    window.removeEventListener('resize', this._onResize);
    document.removeEventListener('keydown', this._onKeyDown);
    document.removeEventListener('keyup', this._onKeyUp);

    // Dispose controls
    this.orbitControls.dispose();
    this.fpsControls.dispose();

    // Dispose all objects
    this.objects.forEach(obj => this._disposeObject(obj));
    this.objects.clear();
    if (this.roomShell) {
      this._disposeObject(this.roomShell);
    }

    // Dispose scene environment
    if (this.scene.environment) {
      this.scene.environment.dispose();
    }

    // Dispose renderer
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }

    // Remove progress overlay
    if (this._progressOverlay && this._progressOverlay.parentNode) {
      this._progressOverlay.parentNode.removeChild(this._progressOverlay);
    }
  }
}

// ---------------------------------------------------------------------------
// Module-level initialization helper
// ---------------------------------------------------------------------------

/**
 * Initialize a V14WorldViewer for a given session. Call from the HTML template.
 * @param {string} containerId - DOM container ID
 * @param {string} sessionId - Active session ID to stream events from
 * @returns {V14WorldViewer}
 */
export function initV14Viewer(containerId, sessionId) {
  const viewer = new V14WorldViewer(containerId);
  if (sessionId) {
    viewer.connectSSE(sessionId);
  }
  return viewer;
}

// ---------------------------------------------------------------------------
// Expose globally for non-module usage (fallback)
// ---------------------------------------------------------------------------
if (typeof window !== 'undefined') {
  window.V14WorldViewer = V14WorldViewer;
  window.initV14Viewer = initV14Viewer;
}
