const $ = selector => document.querySelector(selector);
const messages = $('#messages');
const input = $('#input');
const sendBtn = $('#sendBtn');
const stageBody = $('#stageBody');
const stageTitle = $('#stageTitle');
const stageState = $('#stageState');
const appVersion = Number(window.APP_VERSION || 9);
const historyApiVersion = appVersion >= 9 ? 9 : 8;
const initialParams = new URLSearchParams(window.location.search);
let sessionId = appVersion >= 4
  ? initialParams.get('session') || (appVersion < 8 ? localStorage.getItem('livingRoomSessionId') : null)
  : null;
let busy = false;
let pollTimer = null;
let activeViewer = null;
let currentDescription = '';
let currentPlanData = null;
let v9CanonAlignmentPassed = null;
let v9CanonConcept = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

async function fetchJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-App-Version', String(appVersion));
  const response = await fetch(url, {...options, headers});
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = {error: text || `HTTP ${response.status}`}; }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function logEvent(eventType, action, details = {}) {
  const payload = {app_version:appVersion, session_id:sessionId, event_type:eventType, action, details};
  fetch('/api/events', {
    method:'POST', headers:{'Content-Type':'application/json','X-App-Version':String(appVersion)},
    body:JSON.stringify(payload), keepalive:true,
  }).catch(() => {});
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
    const selected = step.dataset.stage === name;
    step.classList.toggle('active', selected);
    if (selected) step.setAttribute('aria-current', 'step');
    else step.removeAttribute('aria-current');
  });
  logEvent('process', 'stage_change', {stage:name});
}

function setBusy(value, label = 'Working') {
  busy = value;
  sendBtn.disabled = value;
  input.disabled = value;
  stageState.textContent = value ? 'WORKING' : 'READY';
  stageState.className = `stage-state ${value ? 'working' : 'ready'}`;
  if (value) stageTitle.textContent = label;
  if (appVersion >= 8) applyV8ReadOnlyState();
  if (appVersion >= 9) restartV8Telemetry();
  logEvent('process', value ? 'work_started' : 'work_finished', {label});
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
  url.searchParams.set('v', String(appVersion));
  url.searchParams.set('session', id);
  history.replaceState({}, '', url);
}

async function ensureSession() {
  if (!sessionId) {
    rememberSession((await fetchJson('/api/session', {method:'POST'})).session_id);
    if (appVersion >= 9 && busy) restartV8Telemetry();
    logEvent('lifecycle', 'session_created');
  } else {
    rememberSession(sessionId);
  }
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
  const cameraClass = appVersion >= 9 && kind === 'blockout' ? ' camera-frame' : '';
  stageTitle.textContent = title;
  stageBody.innerHTML = `<div class="plan-artifact${cameraClass}"><img src="${source}" alt="${title}">
    <div class="plan-tabs"><button class="${kind === 'floor' ? 'selected' : ''}" onclick="showPlanArtifact('floor')">${floorLabel}</button>
    <button class="${kind === 'blockout' ? 'selected' : ''}" onclick="showPlanArtifact('blockout')">${blockoutLabel}</button></div></div>`;
}

async function restoreSession({manual = false} = {}) {
  if (appVersion < 4) return;
  try {
    const endpoint = sessionId ? `/api/session/${sessionId}/snapshot` : '/api/session/latest/snapshot';
    const data = await fetchJson(endpoint);
    rememberSession(data.session_id);
    logEvent('lifecycle', 'session_restored', {artifact:data.artifact, state:data.state, manual});
    currentDescription = data.user_description || currentDescription;
    messages.innerHTML = '';
    if (data.artifact === 'plan') {
      showPlan(data);
    } else if (data.artifact === 'canon') {
      showCanon(data);
    } else if (data.artifact === 'world') {
      addMessage('assistant', '<h3>Restored world</h3>The latest generated world and revision controls are ready.');
      buildViewer(data.scene_graph, data.download_url, {cameraContract:data.camera_contract});
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
  if (appVersion >= 9 && !sessionId) {
    stageState.textContent = 'IDLE';
    stageState.className = 'stage-state';
    addMessage('assistant', '<strong>Nothing to refresh yet.</strong><br>Generate a space plan to create a live session.');
    return;
  }
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
    await refreshV9HistoryMetadata();
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
    await refreshV9HistoryMetadata();
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
    await refreshV9HistoryMetadata();
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Canon generation failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function showCanon(data) {
  setStage('canon');
  if (data.concept) v9CanonConcept = data.concept;
  if (appVersion >= 9) v9CanonAlignmentPassed = data.camera_alignment?.passed === true;
  stageTitle.textContent = 'Plan-conditioned canon';
  stageState.textContent = (data.provider || 'image').toUpperCase();
  stageState.className = 'stage-state ready';
  const cameraClass = appVersion >= 9 && data.camera_contract ? ' camera-frame' : '';
  const lockLabel = data.camera_contract ? ` · ${escapeHtml(data.camera_contract.contract_id)}` : '';
  stageBody.innerHTML = `<div class="canon-wrap${cameraClass}"><img src="${data.canon_image}" alt="Generated room concept"><div class="provider-tag">${escapeHtml(data.provider || 'unknown provider')}${lockLabel}</div></div>`;
  const alignmentBlocked = appVersion >= 9 && data.camera_alignment?.passed !== true;
  const alignmentStatus = appVersion >= 9
    ? `<span><b>Camera alignment</b>${alignmentBlocked ? 'Review required · regenerate before World' : `Passed · ${Number(data.camera_alignment?.drift_px || 0).toFixed(1)}px drift`}</span>`
    : '';
  if (alignmentBlocked) {
    stageState.textContent = 'ALIGNMENT REVIEW';
    stageState.className = 'stage-state working';
  }
  addMessage('assistant', `<h3>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</h3>
    <div class="concept-grid"><span><b>Palette</b>${escapeHtml(data.concept.palette)}</span><span><b>Lighting</b>${escapeHtml(data.concept.lighting_notes)}</span>${alignmentStatus}</div>
    <div class="actions"><button class="primary" data-v9-canon-approve onclick="approveImage()" ${alignmentBlocked ? 'disabled title="Regenerate until the camera alignment gate passes"' : ''}>Approve canon & build world</button><button class="secondary" onclick="rejectImage()">${alignmentBlocked ? 'Regenerate alignment' : 'Revise image'}</button></div>`);
  applyV8ReadOnlyState();
}

async function approveImage() {
  if (busy) return;
  if (appVersion >= 9 && v9CanonAlignmentPassed !== true) {
    stageState.textContent = 'ALIGNMENT REVIEW';
    stageState.className = 'stage-state working';
    applyV8ReadOnlyState();
    addMessage('error', '<strong>World build blocked</strong><br>Regenerate the Canon until camera alignment passes.');
    return;
  }
  setBusy(true, 'Building spatial world');
  setStage('world');
  let wait;
  try {
    wait = progress('Applying the approved plan to scene graph, meshes, physics, and Godot…');
    const data = await fetchJson(`/api/session/${sessionId}/approve`, {method:'POST'});
    wait.remove();
    addMessage('assistant', `<h3>World ready</h3>${data.scene_graph.objects.length} plan-constrained objects · ${data.scene_graph.lights.length} lights · ${data.scene_graph.doors.length} doors.`);
    buildViewer(data.scene_graph, data.download_url, {cameraContract:data.camera_contract});
    await refreshV9HistoryMetadata();
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>World build failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

async function rejectImage() {
  if (busy) return;
  // When alignment is blocked, auto-regenerate without prompting for feedback
  const alignmentBlocked = appVersion >= 9 && v9CanonAlignmentPassed !== true;
  let feedback;
  if (alignmentBlocked) {
    feedback = 'Regenerate with stricter camera alignment to the approved blockout geometry.';
  } else {
    feedback = prompt('What should change visually? The approved geometry and camera remain locked.');
    if (!feedback?.trim()) return;
  }
  addMessage('user', `Canon revision: ${escapeHtml(feedback)}`);
  setBusy(true, alignmentBlocked ? 'Regenerating for camera alignment' : 'Revising canon');
  let wait;
  try {
    wait = progress('Re-rendering appearance while preserving approved blockout geometry…');
    const data = await fetchJson(`/api/session/${sessionId}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
    wait.remove();
    showCanon({...data, concept:v9CanonConcept || {era:'Canon', mood:`Revision ${data.attempt}`, palette:'Recorded palette', lighting_notes:'Recorded lighting'}});
    stageTitle.textContent = `Canon revision ${data.attempt}`;
    await refreshV9HistoryMetadata();
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
    buildViewer(data.scene_graph, data.download_url, {cameraContract:data.camera_contract});
    await refreshV9HistoryMetadata();
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

function initWorkspaceSplitter() {
  if (![7, 8, 9].includes(appVersion)) return;
  const workspace = $('#workspace');
  const splitter = $('#workspaceSplitter');
  if (!workspace || !splitter) return;

  const storageKey = `livingRoomV${appVersion}ChatPanePx`;
  const narrowLayout = window.matchMedia('(max-width: 900px)');
  let paneWidth = Number(localStorage.getItem(storageKey));
  let pointerId = null;

  const bounds = () => {
    const width = workspace.getBoundingClientRect().width;
    const divider = splitter.getBoundingClientRect().width || 11;
    const minimum = Math.max(320, width * .25);
    const maximum = Math.max(minimum, Math.min(width - divider - 360, width * .7));
    return {width, minimum, maximum};
  };
  const applyWidth = (requested, persist = true) => {
    if (narrowLayout.matches) {
      workspace.style.removeProperty('--chat-pane');
      splitter.setAttribute('aria-disabled', 'true');
      return;
    }
    splitter.setAttribute('aria-disabled', 'false');
    const {width, minimum, maximum} = bounds();
    const fallback = width * .44;
    paneWidth = Math.min(maximum, Math.max(minimum, Number.isFinite(requested) && requested > 0 ? requested : fallback));
    workspace.style.setProperty('--chat-pane', `${Math.round(paneWidth)}px`);
    const percent = Math.round((paneWidth / Math.max(width, 1)) * 100);
    splitter.setAttribute('aria-valuemin', String(Math.round((minimum / width) * 100)));
    splitter.setAttribute('aria-valuemax', String(Math.round((maximum / width) * 100)));
    splitter.setAttribute('aria-valuenow', String(percent));
    splitter.setAttribute('aria-valuetext', `${percent}% chat width`);
    if (persist) localStorage.setItem(storageKey, String(Math.round(paneWidth)));
  };
  const finishResize = inputMethod => {
    const width = workspace.getBoundingClientRect().width;
    logEvent('click', 'workspace_splitter_resized', {
      input_method:inputMethod,
      chat_percent:Math.round((paneWidth / Math.max(width, 1)) * 100),
    });
  };
  const reset = inputMethod => {
    paneWidth = workspace.getBoundingClientRect().width * .44;
    applyWidth(paneWidth);
    finishResize(inputMethod);
  };

  splitter.addEventListener('pointerdown', event => {
    if (event.button !== 0 || narrowLayout.matches) return;
    pointerId = event.pointerId;
    splitter.setPointerCapture(pointerId);
    document.body.classList.add('workspace-resizing');
    event.preventDefault();
  });
  splitter.addEventListener('pointermove', event => {
    if (event.pointerId !== pointerId) return;
    const left = workspace.getBoundingClientRect().left;
    applyWidth(event.clientX - left, false);
  });
  const endPointerResize = event => {
    if (event.pointerId !== pointerId) return;
    if (splitter.hasPointerCapture(pointerId)) splitter.releasePointerCapture(pointerId);
    pointerId = null;
    document.body.classList.remove('workspace-resizing');
    applyWidth(paneWidth);
    finishResize('pointer');
  };
  splitter.addEventListener('pointerup', endPointerResize);
  splitter.addEventListener('pointercancel', endPointerResize);
  splitter.addEventListener('keydown', event => {
    if (narrowLayout.matches) return;
    const step = event.shiftKey ? 40 : 10;
    if (event.key === 'ArrowLeft') paneWidth -= step;
    else if (event.key === 'ArrowRight') paneWidth += step;
    else if (event.key === 'Home') { event.preventDefault(); reset('keyboard'); return; }
    else return;
    event.preventDefault();
    applyWidth(paneWidth);
    finishResize('keyboard');
  });
  splitter.addEventListener('dblclick', () => reset('pointer'));
  narrowLayout.addEventListener('change', () => applyWidth(paneWidth));
  window.addEventListener('resize', () => applyWidth(paneWidth, false));
  applyWidth(paneWidth);
}

function buildViewer(graph, downloadUrl, options = {}) {
  disposeViewer();
  setStage('world');
  stageTitle.textContent = graph.name || 'Generated world';
  stageState.textContent = '3D READY';
  stageState.className = 'stage-state ready';
  const readOnly = !!options.readOnly || isV8Historical();
  const cameraContract = options.cameraContract || null;
  const cameraLocked = appVersion >= 9 && !!cameraContract;
  const viewerActions = readOnly
    ? '<button class="revise-world" type="button" disabled>REVISE WORLD ↻</button><a class="download" aria-disabled="true" tabindex="-1">DOWNLOAD GODOT ↘</a>'
    : `<button class="revise-world" onclick="reviseWorld()">REVISE WORLD ↻</button><a class="download" href="${downloadUrl}">DOWNLOAD GODOT ↘</a>`;
  const cameraHud = cameraLocked
    ? `<div class="viewer-hud"><span id="cameraViewState">CANON VIEW · locked initial camera</span><span class="camera-help">ARROWS orbit · +/− zoom · WASD pan</span><button class="reset-camera" type="button" onclick="resetLockedCamera()">RESET CAMERA</button></div>`
    : '<div class="viewer-hud">DRAG orbit · WHEEL zoom · RIGHT-DRAG pan · ARROWS/+−/WASD keyboard</div>';
  const canvasLabel = cameraLocked ? `World preview, Canon-aligned camera ${escapeHtml(cameraContract.contract_id)}` : 'Interactive world preview';
  const canvasMarkup = cameraLocked
    ? `<div class="locked-viewer-frame"><canvas class="viewer" tabindex="0" aria-label="${canvasLabel}"></canvas></div>`
    : `<canvas class="viewer" tabindex="0" aria-label="${canvasLabel}"></canvas>`;
  stageBody.innerHTML = `${canvasMarkup}${cameraHud}${viewerActions}`;
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
  const camera = cameraLocked
    ? new THREE.PerspectiveCamera(
        cameraContract.vertical_fov_deg,
        cameraContract.aspect_ratio,
        cameraContract.near_plane || .05,
        cameraContract.far_plane || 100,
      )
    : new THREE.PerspectiveCamera(48, 1, .05, 100);
  const lockedPosition = cameraLocked
    ? new THREE.Vector3(cameraContract.position.x, cameraContract.position.y, cameraContract.position.z)
    : new THREE.Vector3(room.width * .82, room.height * .78, room.depth * 1.12);
  const lockedTarget = cameraLocked
    ? new THREE.Vector3(cameraContract.target.x, cameraContract.target.y, cameraContract.target.z)
    : new THREE.Vector3(0, room.height * .38, 0);
  camera.up.set(
    cameraLocked ? cameraContract.up.x : 0,
    cameraLocked ? cameraContract.up.y : 1,
    cameraLocked ? cameraContract.up.z : 0,
  );
  camera.position.copy(lockedPosition);
  camera.lookAt(lockedTarget);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.target.copy(lockedTarget);
  controls.enableDamping = true;
  controls.maxDistance = Math.max(room.width, room.depth) * 3;
  controls.minDistance = 1.5;
  controls.saveState();
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
  const resize = () => {
    const host = cameraLocked ? stageBody.querySelector('.locked-viewer-frame') : stageBody;
    if (cameraLocked) {
      const bounds = stageBody.getBoundingClientRect();
      const width = Math.min(bounds.width, bounds.height * cameraContract.aspect_ratio);
      const height = width / cameraContract.aspect_ratio;
      host.style.width = `${Math.max(1, width)}px`;
      host.style.height = `${Math.max(1, height)}px`;
    }
    const rect = host.getBoundingClientRect();
    camera.aspect = cameraLocked ? cameraContract.aspect_ratio : rect.width / Math.max(rect.height, 1);
    camera.updateProjectionMatrix();
    renderer.setSize(rect.width, rect.height, false);
  };
  const observer = new ResizeObserver(resize); observer.observe(stageBody); resize();
  const updateCameraHud = () => {
    if (!cameraLocked) return;
    const canonical = camera.position.distanceTo(lockedPosition) < .001 && controls.target.distanceTo(lockedTarget) < .001;
    const label = $('#cameraViewState');
    if (label) label.textContent = canonical ? 'CANON VIEW · locked initial/reset camera' : 'ORBITED VIEW · Canon camera no longer active';
  };
  const resetCamera = () => {
    const damping = controls.enableDamping;
    controls.enableDamping = false;
    controls.reset();
    camera.position.copy(lockedPosition);
    camera.up.set(
      cameraLocked ? cameraContract.up.x : 0,
      cameraLocked ? cameraContract.up.y : 1,
      cameraLocked ? cameraContract.up.z : 0,
    );
    controls.target.copy(lockedTarget);
    camera.lookAt(lockedTarget);
    camera.updateProjectionMatrix();
    controls.update();
    controls.enableDamping = damping;
    controls.saveState();
    updateCameraHud();
  };
  const adjustCamera = action => {
    const offset = camera.position.clone().sub(controls.target);
    const distance = Math.max(offset.length(), .001);
    const right = new THREE.Vector3().crossVectors(offset, camera.up).normalize();
    if (action === 'left' || action === 'right') offset.applyAxisAngle(camera.up, action === 'left' ? .08 : -.08);
    else if (action === 'up' || action === 'down') offset.applyAxisAngle(right, action === 'up' ? -.06 : .06);
    else if (action === 'zoom-in' || action === 'zoom-out') offset.multiplyScalar(action === 'zoom-in' ? .9 : 1.1);
    else {
      const step = distance * .04;
      const delta = action === 'pan-left' ? right.clone().multiplyScalar(-step)
        : action === 'pan-right' ? right.clone().multiplyScalar(step)
        : camera.up.clone().normalize().multiplyScalar(action === 'pan-up' ? step : -step);
      camera.position.add(delta);
      controls.target.add(delta);
      controls.update();
      updateCameraHud();
      return;
    }
    camera.position.copy(controls.target).add(offset);
    camera.lookAt(controls.target);
    controls.update();
    updateCameraHud();
  };
  canvas.addEventListener('keydown', event => {
    const action = ({ArrowLeft:'left', ArrowRight:'right', ArrowUp:'up', ArrowDown:'down', '+':'zoom-in', '=':'zoom-in', '-':'zoom-out', w:'pan-up', W:'pan-up', a:'pan-left', A:'pan-left', s:'pan-down', S:'pan-down', d:'pan-right', D:'pan-right'})[event.key];
    if (!action) return;
    event.preventDefault();
    adjustCamera(action);
  });
  controls.addEventListener('change', updateCameraHud);
  const state = {renderer,controls,observer,scene,camera,frame:0,resetCamera,adjustCamera,cameraContract}; activeViewer = state;
  updateCameraHud();
  const animate = () => { state.frame=requestAnimationFrame(animate); controls.update(); renderer.render(scene,camera); };
  animate();
}

function resetLockedCamera() {
  activeViewer?.resetCamera?.();
}

let v8HistorySessionId = null;
let v8CurrentStage = 'brief';
let v8StageMetadata = {};
let v8TelemetryTimer = null;
let v9StageRequestToken = 0;
let v9StageAbortController = null;
let v9TelemetryRequestToken = 0;

function isV8Historical() {
  return appVersion >= 8 && !!v8HistorySessionId;
}

function v8SelectedSessionId() {
  return v8HistorySessionId || sessionId;
}

function v8Unwrap(data) {
  if (data?.payload && typeof data.payload === 'object') return data.payload;
  if (data?.data && typeof data.data === 'object') return data.data;
  if (data?.context && typeof data.context === 'object') return {...data, ...data.context};
  return data || {};
}

function v8Value(source, keys, fallback = '') {
  for (const key of keys) {
    const value = source?.[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return fallback;
}

function v8Duration(value) {
  if (typeof value === 'string' && !/^\d+(\.\d+)?$/.test(value)) return value;
  const seconds = Math.max(0, Number(value));
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${remainder}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function v8RevisionEntries(data, stage) {
  const source = data?.stages ?? data?.stage_revisions ?? data ?? {};
  let entry;
  if (Array.isArray(source)) {
    entry = source.find(item => (item.stage || item.name || item.id) === stage);
  } else {
    entry = source[stage];
  }
  const revisions = Array.isArray(entry) ? entry : entry?.revisions ?? entry?.history ?? [];
  return Array.isArray(revisions) ? revisions : [];
}

function populateV8Revisions(stage, selectedRevision = '') {
  const select = $('#historyRevision');
  if (!select) return;
  const revisions = v8RevisionEntries(v8StageMetadata, stage);
  select.innerHTML = '<option value="">Latest</option>';
  revisions.forEach((item, index) => {
    const revision = typeof item === 'object'
      ? v8Value(item, ['revision', 'number', 'id'], index + 1)
      : item;
    const option = document.createElement('option');
    option.value = String(revision);
    option.textContent = `Revision ${revision}`;
    select.appendChild(option);
  });
  select.disabled = !v8SelectedSessionId() || revisions.length === 0;
  select.value = selectedRevision === undefined || selectedRevision === null ? '' : String(selectedRevision);
}

function applyV8ReadOnlyState() {
  if (appVersion < 8) return;
  const historical = isV8Historical();
  document.body.classList.toggle('is-historical', historical);
  const banner = $('#historyBanner');
  if (banner) banner.hidden = !historical;
  input.disabled = busy || historical;
  sendBtn.disabled = busy || historical;
  document.querySelectorAll('.actions button, .revise-world, .refresh-output').forEach(control => {
    control.disabled = historical || (appVersion >= 9 && control.hasAttribute('data-v9-canon-approve') && v9CanonAlignmentPassed !== true);
  });
  document.querySelectorAll('.download').forEach(link => {
    link.setAttribute('aria-disabled', String(historical));
    link.tabIndex = historical ? -1 : 0;
  });
}

function renderV8Brief(payload) {
  const concept = payload.concept || payload.scene_concept || {};
  const summary = v8Value(payload, ['summary', 'brief_summary', 'user_description', 'description'], 'No brief summary was recorded.');
  const summaryText = typeof summary === 'string' ? summary : JSON.stringify(summary, null, 2);
  const facts = [
    ['Era', concept.era], ['Mood', concept.mood], ['Palette', concept.palette],
    ['Lighting', concept.lighting_notes || concept.lighting],
  ].filter(([, value]) => value);
  stageTitle.textContent = 'Brief summary';
  stageBody.innerHTML = `<article class="v8-brief"><span class="eyebrow">RECORDED BRIEF</span><h3>${escapeHtml(v8Value(payload, ['title', 'name'], 'Room brief'))}</h3><p>${escapeHtml(summaryText)}</p>${facts.length ? `<dl>${facts.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl>` : ''}</article>`;
}

function renderV8Image(stage, payload) {
  const keys = {
    plan:['artifact_url', 'floor_plan_image', 'plan_image', 'image_url', 'url'],
    blockout:['artifact_url', 'blockout_image', 'blockout_url', 'image_url', 'url'],
    canon:['artifact_url', 'canon_image', 'canon_url', 'image_url', 'url'],
  }[stage];
  const nested = payload.artifact && typeof payload.artifact === 'object' ? payload.artifact : {};
  const source = v8Value(payload, keys, v8Value(nested, keys));
  const titles = {plan:'Authoritative floor plan', blockout:'Camera-matched blockout', canon:'Plan-conditioned canon'};
  stageTitle.textContent = titles[stage];
  if (!source) {
    stageBody.innerHTML = `<div class="empty-stage"><p>No ${escapeHtml(stage)} image was recorded for this revision.</p></div>`;
    return;
  }
  const cameraContract = payload.camera_contract || null;
  const cameraClass = appVersion >= 9 && cameraContract && ['blockout', 'canon'].includes(stage) ? ' camera-frame' : '';
  const lockLabel = cameraContract ? ` · ${escapeHtml(cameraContract.contract_id)}` : '';
  stageBody.innerHTML = `<figure class="v8-history-image${cameraClass}"><img src="${escapeHtml(source)}" alt="${titles[stage]}"><figcaption>${titles[stage]}${lockLabel}</figcaption></figure>`;
}

function renderV8Compare(payload) {
  const history = payload.revision_history || payload.revisions || payload.history || payload.comparisons || payload.items || [];
  const entries = Array.isArray(history) ? history : Object.values(history || {});
  stageTitle.textContent = 'Revision history';
  if (!entries.length) {
    stageBody.innerHTML = '<div class="empty-stage"><p>No comparison revisions have been recorded.</p></div>';
    return;
  }
  stageBody.innerHTML = `<div class="v8-compare-list">${entries.map((entry, index) => {
    const item = typeof entry === 'object' ? entry : {summary:entry};
    const revision = v8Value(item, ['revision', 'number', 'id'], index + 1);
    const score = v8Value(item, ['similarity_score', 'score']);
    const changes = Array.isArray(item.changes) ? item.changes : [];
    return `<article><header><strong>Revision ${escapeHtml(revision)}</strong>${score !== '' ? `<span>${escapeHtml(score)}% match</span>` : ''}</header><p>${escapeHtml(v8Value(item, ['summary', 'feedback', 'description'], 'Recorded revision'))}</p>${changes.length ? `<ul>${changes.map(change => `<li>${escapeHtml(change)}</li>`).join('')}</ul>` : ''}</article>`;
  }).join('')}</div>`;
}

function renderV8Stage(stage, response) {
  const payload = v8Unwrap(response);
  disposeViewer();
  setStage(stage);
  stageState.textContent = isV8Historical() ? 'HISTORY' : 'RECORDED';
  stageState.className = 'stage-state ready';
  if (stage === 'brief') renderV8Brief(payload);
  else if (['plan', 'blockout', 'canon'].includes(stage)) renderV8Image(stage, payload);
  else if (stage === 'world') {
    const graph = payload.scene_graph || payload.world?.scene_graph || payload.graph;
    if (graph) buildViewer(graph, v8Value(payload, ['download_url'], ''), {
      readOnly:isV8Historical(),
      cameraContract:payload.camera_contract || payload.world?.camera_contract,
    });
    else {
      stageTitle.textContent = 'Generated world';
      stageBody.innerHTML = '<div class="empty-stage"><p>No world scene graph was recorded for this revision.</p></div>';
    }
  } else renderV8Compare(payload);
  applyV8ReadOnlyState();
}

async function loadV8Stages(id = v8SelectedSessionId()) {
  if (appVersion < 8 || !id) {
    v8StageMetadata = {};
    populateV8Revisions(v8CurrentStage);
    return;
  }
  v8StageMetadata = await fetchJson(`/api/v${historyApiVersion}/session/${encodeURIComponent(id)}/stages`);
  populateV8Revisions(v8CurrentStage);
}

async function loadV8Stage(stage, revision = '') {
  if (appVersion < 8) return;
  const requestToken = appVersion >= 9 ? ++v9StageRequestToken : 0;
  if (appVersion >= 9) {
    v9StageAbortController?.abort();
    v9StageAbortController = new AbortController();
  }
  const id = v8SelectedSessionId();
  v8CurrentStage = stage;
  setStage(stage);
  populateV8Revisions(stage, revision);
  if (!id) {
    stageTitle.textContent = 'Waiting for a session';
    stageState.textContent = 'IDLE';
    stageState.className = 'stage-state';
    stageBody.innerHTML = '<div class="empty-stage"><p>Start a live run or select one from history.</p></div>';
    applyV8ReadOnlyState();
    return;
  }
  stageState.textContent = 'LOADING';
  stageState.className = 'stage-state working';
  try {
    const suffix = revision === '' || revision === undefined || revision === null ? '' : `?revision=${encodeURIComponent(revision)}`;
    const options = appVersion >= 9 ? {signal:v9StageAbortController.signal} : {};
    const data = await fetchJson(`/api/v${historyApiVersion}/session/${encodeURIComponent(id)}/stage/${encodeURIComponent(stage)}${suffix}`, options);
    if (appVersion >= 9 && requestToken !== v9StageRequestToken) return;
    renderV8Stage(stage, data);
  } catch (error) {
    if (appVersion >= 9 && (error.name === 'AbortError' || requestToken !== v9StageRequestToken)) return;
    stageState.textContent = 'UNAVAILABLE';
    stageState.className = 'stage-state';
    stageBody.innerHTML = `<div class="empty-stage"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function loadV8Sessions() {
  if (appVersion < 8) return;
  const select = $('#historyRun');
  if (!select) return;
  const selected = v8HistorySessionId || '';
  try {
    const data = await fetchJson(`/api/v${historyApiVersion}/sessions`);
    const sessions = Array.isArray(data) ? data : data.sessions || data.runs || data.items || [];
    const groups = new Map();
    sessions.forEach(run => {
      const version = String(v8Value(run, ['interface_version', 'app_version', 'version'], 'Unknown'));
      if (!groups.has(version)) groups.set(version, []);
      groups.get(version).push(run);
    });
    select.innerHTML = '<option value="">Live session</option>';
    [...groups.entries()].sort(([a], [b]) => b.localeCompare(a, undefined, {numeric:true})).forEach(([version, runs]) => {
      const group = document.createElement('optgroup');
      group.label = version.toLowerCase().startsWith('v') ? version.toUpperCase() : `V${version}`;
      runs.forEach(run => {
        const id = String(v8Value(run, ['session_id', 'id', 'run_id']));
        if (!id) return;
        const option = document.createElement('option');
        option.value = id;
        const timestamp = v8Value(run, ['updated_at', 'created_at', 'timestamp']);
        option.textContent = `${v8Value(run, ['title', 'name', 'description'], id.slice(0, 8))}${timestamp ? ` · ${timestamp}` : ''}`;
        group.appendChild(option);
      });
      select.appendChild(group);
    });
    select.value = selected;
  } catch (error) {
    select.innerHTML = `<option value="">History unavailable · ${escapeHtml(error.message)}</option>`;
  }
}

function v8Heartbeat(data) {
  let age = Number(v8Value(data, ['heartbeat_age_seconds', 'staleness_seconds', 'heartbeat_age'], NaN));
  if (!Number.isFinite(age)) {
    const stamp = v8Value(data, ['heartbeat_at', 'last_heartbeat', 'heartbeat']);
    const parsed = typeof stamp === 'string' ? Date.parse(stamp) : NaN;
    if (Number.isFinite(parsed)) age = Math.max(0, (Date.now() - parsed) / 1000);
  }
  const threshold = Number(v8Value(data, ['stale_after_seconds', 'stale_threshold_seconds'], 30));
  const stale = data.stale === true || data.is_stale === true || (Number.isFinite(age) && age > threshold);
  if (!Number.isFinite(age)) return stale ? 'stale' : 'waiting';
  return `${stale ? 'stale' : 'live'} · ${v8Duration(age)} ago`;
}

async function updateV8Telemetry() {
  const id = v8SelectedSessionId();
  if (appVersion < 8 || !id || (appVersion >= 9 && (isV8Historical() || !busy))) return;
  const requestToken = appVersion >= 9 ? ++v9TelemetryRequestToken : 0;
  try {
    const data = v8Unwrap(await fetchJson(`/api/v${historyApiVersion}/session/${encodeURIComponent(id)}/telemetry`));
    if (appVersion >= 9 && (requestToken !== v9TelemetryRequestToken || id !== sessionId || !busy || data.status !== 'active')) return;
    $('#telemetrySubstep').textContent = v8Value(data, ['current_substep', 'substep', 'current_step', 'step'], 'Waiting');
    $('#telemetryElapsed').textContent = v8Duration(v8Value(data, ['elapsed_seconds', 'elapsed'], NaN));
    const heartbeat = $('#telemetryHeartbeat');
    heartbeat.textContent = v8Heartbeat(data);
    heartbeat.classList.toggle('stale', heartbeat.textContent.startsWith('stale'));
    const eta = v8Value(data, ['eta_seconds', 'eta'], '');
    $('#telemetryEta').textContent = eta === '' ? 'collecting timing data' : v8Duration(eta);
  } catch {
    $('#telemetryHeartbeat').textContent = 'unavailable';
  }
}

function resetV9Telemetry() {
  if (appVersion < 9) return;
  v9TelemetryRequestToken += 1;
  $('#telemetrySubstep').textContent = busy ? 'Starting' : 'Waiting';
  $('#telemetryElapsed').textContent = '—';
  $('#telemetryHeartbeat').textContent = '—';
  $('#telemetryHeartbeat').classList.remove('stale');
  $('#telemetryEta').textContent = busy ? 'collecting timing data' : 'inactive';
}

function restartV8Telemetry() {
  if (v8TelemetryTimer) clearInterval(v8TelemetryTimer);
  v8TelemetryTimer = null;
  if (appVersion >= 9) {
    resetV9Telemetry();
    if (!sessionId || isV8Historical() || !busy) return;
  }
  updateV8Telemetry();
  v8TelemetryTimer = setInterval(updateV8Telemetry, 2000);
}

async function refreshV9HistoryMetadata() {
  if (appVersion < 9 || !sessionId) return;
  try {
    await Promise.all([loadV8Sessions(), loadV8Stages(sessionId)]);
  } catch {}
}

async function selectV8Run(id) {
  const wasHistorical = isV8Historical();
  v8HistorySessionId = id || null;
  if (appVersion >= 9 && wasHistorical && !v8HistorySessionId) {
    stageState.textContent = sessionId ? 'READY' : 'IDLE';
    stageState.className = sessionId ? 'stage-state ready' : 'stage-state';
    logEvent('lifecycle', 'history_returned_live', {stage:v8CurrentStage});
  }
  const bannerText = $('#historyBanner span');
  if (bannerText && v8HistorySessionId) bannerText.textContent = `Viewing read-only history · ${v8HistorySessionId}`;
  applyV8ReadOnlyState();
  try { await loadV8Stages(); }
  catch (error) { stageBody.innerHTML = `<div class="empty-stage"><p>${escapeHtml(error.message)}</p></div>`; }
  await loadV8Stage(v8CurrentStage);
  restartV8Telemetry();
}

function initV8() {
  if (appVersion < 8) return;
  document.querySelectorAll('.stage-step').forEach(step => {
    step.addEventListener('click', () => loadV8Stage(step.dataset.stage));
    step.addEventListener('keydown', event => {
      if (step.tagName !== 'BUTTON' && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        step.click();
      }
    });
  });
  $('#historyRun').addEventListener('change', event => selectV8Run(event.target.value));
  $('#historyRevision').addEventListener('change', event => loadV8Stage(v8CurrentStage, event.target.value));
  $('#returnLiveBtn').addEventListener('click', () => {
    $('#historyRun').value = '';
    selectV8Run('');
  });
  $('#historyReload').addEventListener('click', async () => {
    await loadV8Sessions();
    await loadV8Stages();
  });
  applyV8ReadOnlyState();
  loadV8Sessions();
  loadV8Stages().catch(() => {});
  restartV8Telemetry();
}

$('#composer').addEventListener('submit', event => { event.preventDefault(); sendDescription(); });
input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendDescription(); } });
document.addEventListener('click', event => {
  const target = event.target instanceof Element ? event.target.closest('button,a,[role="button"]') : null;
  if (!target) return;
  logEvent('click', 'control_activated', {
    element:target.tagName.toLowerCase(), element_id:target.id || '',
    label:(target.textContent || '').trim().slice(0, 80), href:target.getAttribute('href') || '',
    stage:target.dataset.stage || document.querySelector('.stage-step.active')?.dataset.stage || '',
  });
});
Object.assign(window, {approvePlan, revisePlan, editDescription, showPlanArtifact, refreshOutput, approveImage, rejectImage, reviseWorld, resetLockedCamera, logEvent});
logEvent('lifecycle', 'app_loaded', {path:window.location.pathname});
loadReadiness();
setInterval(loadReadiness, 15000);
initWorkspaceSplitter();
initV8();
if (appVersion >= 4 && (appVersion < 8 || sessionId)) restoreSession();
input.focus();
