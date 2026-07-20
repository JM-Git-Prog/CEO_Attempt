const $ = selector => document.querySelector(selector);
const messages = $('#messages');
const input = $('#input');
const sendBtn = $('#sendBtn');
const stageBody = $('#stageBody');
const stageTitle = $('#stageTitle');
const stageState = $('#stageState');
const appVersion = Number(window.APP_VERSION || 4);
const initialParams = new URLSearchParams(window.location.search);
let sessionId = appVersion >= 4 ? initialParams.get('session') || localStorage.getItem('livingRoomSessionId') : null;
let busy = false;
let pollTimer = null;
let activeViewer = null;
let currentDescription = '';
let currentPlanData = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = {error: text || `HTTP ${response.status}`}; }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function chip(id, label, ready, detail = '') {
  const element = $(id);
  element.textContent = `${label} · ${ready ? 'ready' : detail || 'offline'}`;
  element.className = `chip ${ready ? 'ok' : 'bad'}`;
}

async function loadReadiness() {
  try {
    const data = await fetchJson('/api/readiness');
    chip('#apiChip', 'API', data.api);
    chip('#llmChip', 'Ollama', data.ollama.ready, data.ollama.model);
    chip('#imageChip', 'FLUX.2', data.comfyui.ready, data.comfyui.reason ? 'offline' : 'models missing');
    chip('#gpuChip', 'GPU', data.comfyui.ready, data.comfyui.device || 'unknown');
    if (data.comfyui.device) $('#gpuChip').textContent = data.comfyui.device.replace('cuda:0 ', '').split(':')[0];
  } catch { chip('#apiChip', 'API', false, 'offline'); }
}

function addMessage(type, html) {
  const element = document.createElement('article');
  element.className = `message ${type}`;
  element.innerHTML = html;
  messages.appendChild(element);
  messages.scrollTop = messages.scrollHeight;
  return element;
}

function setStage(name) {
  document.querySelectorAll('.stage-step').forEach(step => {
    step.classList.toggle('active', step.dataset.stage === name);
  });
}

function setBusy(value, label = 'Working') {
  busy = value;
  sendBtn.disabled = value;
  input.disabled = value;
  stageState.textContent = value ? 'WORKING' : 'READY';
  stageState.className = `stage-state ${value ? 'working' : 'ready'}`;
  if (value) stageTitle.textContent = label;
}

function progress(label) {
  const element = addMessage('progress', `<span class="spinner"></span><strong>${escapeHtml(label)}</strong><div class="progress-log" id="progressLog"></div>`);
  startPolling();
  return element;
}

function startPolling() {
  stopPolling();
  if (!sessionId) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchJson(`/api/session/${sessionId}/status`);
      const log = $('#progressLog');
      if (log && data.progress?.length) log.textContent = data.progress.at(-1);
      if (data.state === 'error' && log) log.textContent = data.error || 'Build failed';
    } catch {}
  }, 900);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function rememberSession(id) {
  sessionId = id;
  if (appVersion < 4) return;
  localStorage.setItem('livingRoomSessionId', id);
  const url = new URL(window.location.href);
  url.searchParams.set('v', '4');
  url.searchParams.set('session', id);
  history.replaceState({}, '', url);
}

async function ensureSession() {
  if (!sessionId) rememberSession((await fetchJson('/api/session', {method:'POST'})).session_id);
  else rememberSession(sessionId);
  return sessionId;
}

function showPlan(data) {
  currentPlanData = data;
  setStage('plan');
  stageTitle.textContent = `Floor plan v${data.plan_revision}`;
  stageState.textContent = 'REVIEW PLAN';
  stageState.className = 'stage-state ready';
  showPlanArtifact('floor');
  const plan = data.floor_plan;
  const warnings = (data.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  addMessage('assistant', `<h3>Spatial plan ready · ${plan.room.width.toFixed(1)} × ${plan.room.depth.toFixed(1)}m</h3>
    <div class="concept-grid"><span><b>Style brief</b>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</span>
    <span><b>Layout</b>${plan.items.length} placed items · ${plan.openings.length} openings</span>
    <span><b>Canon camera</b>${plan.camera.fov_deg.toFixed(0)}° field of view</span>
    <span><b>Authority</b>Plan locks geometry; canon controls appearance</span></div>
    ${warnings ? `<ul class="plan-warnings">${warnings}</ul>` : ''}
    <div class="actions"><button class="primary" onclick="approvePlan()">Approve plan & render canon</button>
    ${appVersion >= 4 ? `<button class="secondary artifact-button" onclick="showPlanArtifact('floor')">View 2D plan</button>
    <button class="secondary artifact-button" onclick="showPlanArtifact('blockout')">View 3D blockout</button>` : ''}
    <button class="secondary" onclick="revisePlan()">Revise plan</button><button class="secondary" onclick="editDescription()">Edit brief</button>
    ${appVersion >= 4 ? '<button class="secondary" onclick="refreshOutput()">Refresh output</button>' : ''}</div>`);
}

function showPlanArtifact(kind) {
  if (!currentPlanData) return;
  setStage(kind === 'floor' ? 'plan' : 'blockout');
  const original = kind === 'floor' ? currentPlanData.floor_plan_image : currentPlanData.blockout_image;
  const source = appVersion >= 4 ? `${original}${original.includes('?') ? '&' : '?'}refresh=${Date.now()}` : original;
  const title = kind === 'floor' ? 'Authoritative floor plan' : 'Camera-matched blockout';
  const floorLabel = appVersion >= 4 ? '2D PLAN' : 'PLAN';
  const blockoutLabel = appVersion >= 4 ? '3D BLOCKOUT' : 'BLOCKOUT';
  stageTitle.textContent = title;
  stageBody.innerHTML = `<div class="plan-artifact"><img src="${source}" alt="${title}">
    <div class="plan-tabs"><button class="${kind === 'floor' ? 'selected' : ''}" onclick="showPlanArtifact('floor')">${floorLabel}</button>
    <button class="${kind === 'blockout' ? 'selected' : ''}" onclick="showPlanArtifact('blockout')">${blockoutLabel}</button></div></div>`;
}

async function restoreSession({manual = false} = {}) {
  if (appVersion < 4) return;
  try {
    const endpoint = sessionId ? `/api/session/${sessionId}/snapshot` : '/api/session/latest/snapshot';
    const data = await fetchJson(endpoint);
    rememberSession(data.session_id);
    currentDescription = data.user_description || currentDescription;
    messages.innerHTML = '';
    if (data.artifact === 'plan') {
      showPlan(data);
    } else if (data.artifact === 'canon') {
      showCanon(data);
    } else if (data.artifact === 'world') {
      addMessage('assistant', '<h3>Restored world</h3>The latest generated world and revision controls are ready.');
      buildViewer(data.scene_graph, data.download_url);
    }
  } catch (error) {
    if (manual) addMessage('error', `<strong>Refresh failed</strong><br>${escapeHtml(error.message)}`);
    if (error.message === 'Session not found') {
      localStorage.removeItem('livingRoomSessionId');
      sessionId = null;
    }
  }
}

async function refreshOutput() {
  if (busy || appVersion < 4) return;
  stageState.textContent = 'REFRESHING';
  stageState.className = 'stage-state working';
  await restoreSession({manual:true});
}

async function sendDescription() {
  const description = input.value.trim();
  if (!description || busy) return;
  currentDescription = description;
  addMessage('user', escapeHtml(description));
  input.value = '';
  setBusy(true, 'Planning the space');
  setStage('brief');
  let wait;
  try {
    await ensureSession();
    wait = progress('Interpreting the brief and producing a metric floor plan…');
    const data = await fetchJson(`/api/session/${sessionId}/describe`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({description})});
    wait.remove();
    showPlan(data);
  } catch (error) {
    wait?.remove();
    addMessage('error', `<strong>Planning failed</strong><br>${escapeHtml(error.message)}`);
    stageState.textContent = 'ERROR';
  } finally {
    stopPolling(); setBusy(false); input.focus();
  }
}

async function revisePlan() {
  if (busy) return;
  const feedback = prompt('What should change in the floor plan?');
  if (!feedback?.trim()) return;
  addMessage('user', `Plan revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Revising floor plan');
  let wait;
  try {
    wait = progress('Replanning while preserving unaffected geometry and IDs…');
    const data = await fetchJson(`/api/session/${sessionId}/revise_plan`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
    wait.remove(); showPlan(data);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Plan revision failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function editDescription() {
  input.value = currentDescription;
  input.focus();
}

async function approvePlan() {
  if (busy) return;
  setBusy(true, 'Rendering plan-conditioned canon');
  setStage('canon');
  let wait;
  try {
    wait = progress('Using the approved blockout and camera as FLUX.2 reference geometry…');
    const data = await fetchJson(`/api/session/${sessionId}/approve_plan`, {method:'POST'});
    wait.remove(); showCanon(data);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Canon generation failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function showCanon(data) {
  setStage('canon');
  stageTitle.textContent = 'Plan-conditioned canon';
  stageState.textContent = (data.provider || 'image').toUpperCase();
  stageState.className = 'stage-state ready';
  stageBody.innerHTML = `<div class="canon-wrap"><img src="${data.canon_image}" alt="Generated room concept"><div class="provider-tag">${escapeHtml(data.provider || 'unknown provider')}</div></div>`;
  addMessage('assistant', `<h3>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</h3>
    <div class="concept-grid"><span><b>Palette</b>${escapeHtml(data.concept.palette)}</span><span><b>Lighting</b>${escapeHtml(data.concept.lighting_notes)}</span></div>
    <div class="actions"><button class="primary" onclick="approveImage()">Approve canon & build world</button><button class="secondary" onclick="rejectImage()">Revise image</button></div>`);
}

async function approveImage() {
  if (busy) return;
  setBusy(true, 'Building spatial world');
  setStage('world');
  let wait;
  try {
    wait = progress('Applying the approved plan to scene graph, meshes, physics, and Godot…');
    const data = await fetchJson(`/api/session/${sessionId}/approve`, {method:'POST'});
    wait.remove();
    addMessage('assistant', `<h3>World ready</h3>${data.scene_graph.objects.length} plan-constrained objects · ${data.scene_graph.lights.length} lights · ${data.scene_graph.doors.length} doors.`);
    buildViewer(data.scene_graph, data.download_url);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>World build failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

async function rejectImage() {
  if (busy) return;
  const feedback = prompt('What should change visually? The approved geometry and camera remain locked.');
  if (!feedback?.trim()) return;
  addMessage('user', `Canon revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Revising canon');
  let wait;
  try {
    wait = progress('Re-rendering appearance while preserving approved blockout geometry…');
    const data = await fetchJson(`/api/session/${sessionId}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
    wait.remove();
    stageTitle.textContent = `Canon revision ${data.attempt}`;
    stageBody.innerHTML = `<div class="canon-wrap"><img src="${data.canon_image}" alt="Revised room concept"><div class="provider-tag">${escapeHtml(data.provider)}</div></div>`;
    addMessage('assistant', `<h3>Canon revision ${data.attempt} ready</h3><div class="actions"><button class="primary" onclick="approveImage()">Approve & build world</button><button class="secondary" onclick="rejectImage()">Revise again</button></div>`);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Revision failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not capture the 3D render')), 'image/png'));
}

async function reviseWorld() {
  if (busy || !activeViewer) return;
  const feedback = prompt('What should change in the world? The approved floor plan remains locked.');
  if (!feedback?.trim()) return;
  let render;
  try { render = await canvasBlob(activeViewer.renderer.domElement); }
  catch (error) { addMessage('error', escapeHtml(error.message)); return; }
  addMessage('user', `World revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Comparing world, canon, and plan');
  setStage('compare');
  let wait;
  try {
    wait = progress('Qwen Vision is comparing the captured render to the canon; approved plan geometry is protected…');
    const form = new FormData();
    form.append('feedback', feedback.trim());
    form.append('render', render, `world-render-${Date.now()}.png`);
    const data = await fetchJson(`/api/session/${sessionId}/revise_world`, {method:'POST', body:form});
    wait.remove();
    const report = data.report || {};
    const changes = (report.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('');
    addMessage('assistant', `<h3>World revision ${data.revision} · ${Number(report.similarity_score || 0).toFixed(0)}% similarity</h3>
      <p>${escapeHtml(report.summary || 'World revised')}</p>${changes ? `<ul>${changes}</ul>` : ''}
      <small>This is revision memory, not model-weight training.</small>`);
    buildViewer(data.scene_graph, data.download_url);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>World revision failed</strong><br>${escapeHtml(error.message)}`);
    setStage('world');
  } finally { stopPolling(); setBusy(false); }
}

function disposeViewer() {
  if (!activeViewer) return;
  cancelAnimationFrame(activeViewer.frame);
  activeViewer.observer.disconnect();
  activeViewer.controls.dispose();
  activeViewer.renderer.dispose();
  activeViewer = null;
}

function color(value, fallback) {
  try { return new THREE.Color(value || fallback); }
  catch { return new THREE.Color(fallback); }
}

function material(props = {}, fallback = '#777b84') {
  return new THREE.MeshStandardMaterial({color:color(props.base_color, fallback), roughness:props.roughness ?? .75, metalness:props.metallic ?? 0, side:THREE.DoubleSide});
}

function buildViewer(graph, downloadUrl) {
  disposeViewer();
  setStage('world');
  stageTitle.textContent = graph.name || 'Generated world';
  stageState.textContent = '3D READY';
  stageState.className = 'stage-state ready';
  stageBody.innerHTML = `<canvas class="viewer"></canvas><div class="viewer-hud">DRAG orbit · WHEEL zoom · RIGHT-DRAG pan</div>
    <button class="revise-world" onclick="reviseWorld()">REVISE WORLD ↻</button><a class="download" href="${downloadUrl}">DOWNLOAD GODOT ↘</a>`;
  if (typeof THREE === 'undefined' || !THREE.OrbitControls) {
    stageBody.innerHTML = '<div class="empty-stage"><p>Three.js could not load. Check the browser network console.</p></div>';
    return;
  }
  const canvas = stageBody.querySelector('canvas');
  const room = graph.room;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#07090d');
  scene.fog = new THREE.Fog('#07090d', 12, 28);
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:false, preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  renderer.outputEncoding = THREE.sRGBEncoding;
  const camera = new THREE.PerspectiveCamera(48, 1, .05, 100);
  camera.position.set(room.width * .82, room.height * .78, room.depth * 1.12);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.target.set(0, room.height * .38, 0);
  controls.enableDamping = true;
  controls.maxDistance = Math.max(room.width, room.depth) * 3;
  controls.minDistance = 1.5;
  const addBox = (name, size, position, meshMaterial, cast = false) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), meshMaterial);
    mesh.name = name; mesh.position.set(...position); mesh.castShadow = cast; mesh.receiveShadow = true; scene.add(mesh); return mesh;
  };
  addBox('Floor', [room.width,.08,room.depth], [0,-.04,0], material(room.floor_material,'#4e5055'));
  const wallMaterial = material(room.wall_material,'#bbb5aa');
  const halfWidth = room.width / 2, halfDepth = room.depth / 2, halfHeight = room.height / 2;
  addBox('Back wall',[room.width,room.height,.12],[0,halfHeight,-halfDepth-.06],wallMaterial);
  addBox('East wall',[.12,room.height,room.depth],[halfWidth+.06,halfHeight,0],wallMaterial);
  addBox('West wall',[.12,room.height,room.depth],[-halfWidth-.06,halfHeight,0],wallMaterial);
  const grid = new THREE.GridHelper(Math.max(room.width,room.depth), Math.ceil(Math.max(room.width,room.depth)*2), 0x313947, 0x1c222c);
  grid.position.y = .006; scene.add(grid);
  (graph.objects || []).forEach(object => {
    let geometry;
    const dimensions = object.dimensions;
    if (object.primitive_shape === 'cylinder') geometry = new THREE.CylinderGeometry(Math.min(dimensions.x,dimensions.z)/2,Math.min(dimensions.x,dimensions.z)/2,dimensions.y,24);
    else if (object.primitive_shape === 'sphere') geometry = new THREE.SphereGeometry(Math.max(dimensions.x,dimensions.y,dimensions.z)/2,24,16);
    else if (object.primitive_shape === 'capsule') geometry = new THREE.CapsuleGeometry(Math.min(dimensions.x,dimensions.z)/2,Math.max(0,dimensions.y-Math.min(dimensions.x,dimensions.z)),8,16);
    else geometry = new THREE.BoxGeometry(dimensions.x,dimensions.y,dimensions.z);
    const mesh = new THREE.Mesh(geometry, material(object.material));
    mesh.name = object.name;
    mesh.position.set(object.position.x, object.position.y + dimensions.y/2, object.position.z);
    mesh.rotation.set((object.rotation.x||0)*Math.PI/180,(object.rotation.y||0)*Math.PI/180,(object.rotation.z||0)*Math.PI/180);
    mesh.scale.set(object.scale?.x||1,object.scale?.y||1,object.scale?.z||1);
    mesh.castShadow = true; mesh.receiveShadow = true; scene.add(mesh);
  });
  (graph.doors || []).forEach(door => {
    const alongX = ['north','south'].includes(door.wall);
    const mesh = addBox(door.id, alongX?[door.width,door.height,.06]:[.06,door.height,door.width], [door.position.x,door.height/2,door.position.z], material({},'#71492f'), true);
    mesh.rotation.y = (door.wall === 'east' || door.wall === 'west') ? Math.PI/2 : 0;
  });
  (graph.windows || []).forEach(windowSpec => {
    const alongX = ['north','south'].includes(windowSpec.wall);
    const geometry = new THREE.PlaneGeometry(windowSpec.width,windowSpec.height);
    const glass = new THREE.MeshPhysicalMaterial({color:0x8fb9ce,transparent:true,opacity:.42,roughness:.18,metalness:.05,side:THREE.DoubleSide});
    const mesh = new THREE.Mesh(geometry,glass);
    mesh.position.set(windowSpec.position.x,windowSpec.sill_height+windowSpec.height/2,windowSpec.position.z);
    if (!alongX) mesh.rotation.y = Math.PI/2;
    scene.add(mesh);
  });
  scene.add(new THREE.HemisphereLight(0xb8c9df,0x251d17,.75));
  scene.add(new THREE.AmbientLight(color(graph.ambient_color,'#20283a'),Math.max(.35,graph.ambient_energy||.3)));
  (graph.lights || []).forEach(item => {
    const lightColor = color(item.color,'#ffd0a0');
    let light;
    if (item.light_type === 'directional') { light = new THREE.DirectionalLight(lightColor,item.intensity||1); light.target.position.set(item.direction?.x||0,item.direction?.y||0,item.direction?.z||0); scene.add(light.target); }
    else if (item.light_type === 'spot') light = new THREE.SpotLight(lightColor,(item.intensity||1)*1.5,item.range_meters||5,(item.spot_angle_deg||45)*Math.PI/180);
    else light = new THREE.PointLight(lightColor,(item.intensity||1)*1.6,item.range_meters||6);
    light.position.set(item.position.x,item.position.y,item.position.z); light.castShadow = !!item.cast_shadows; scene.add(light);
  });
  const resize = () => { const rect = stageBody.getBoundingClientRect(); camera.aspect = rect.width/Math.max(rect.height,1); camera.updateProjectionMatrix(); renderer.setSize(rect.width,rect.height,false); };
  const observer = new ResizeObserver(resize); observer.observe(stageBody); resize();
  const state = {renderer,controls,observer,scene,camera,frame:0}; activeViewer = state;
  const animate = () => { state.frame=requestAnimationFrame(animate); controls.update(); renderer.render(scene,camera); };
  animate();
}

$('#composer').addEventListener('submit', event => { event.preventDefault(); sendDescription(); });
input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendDescription(); } });
Object.assign(window, {approvePlan, revisePlan, editDescription, showPlanArtifact, refreshOutput, approveImage, rejectImage, reviseWorld});
loadReadiness();
setInterval(loadReadiness, 15000);
if (appVersion >= 4) restoreSession();
input.focus();
