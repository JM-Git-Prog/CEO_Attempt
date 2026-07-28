const $ = selector => document.querySelector(selector);
const messages = $('#messages');
const input = $('#input');
const sendBtn = $('#sendBtn');
const stageBody = $('#stageBody');
const stageTitle = $('#stageTitle');
const stageState = $('#stageState');
const appVersion = Number(window.APP_VERSION || 11);
const historyApiVersion = appVersion >= 11 ? 11 : appVersion >= 10 ? 10 : appVersion >= 9 ? 9 : 8;
const initialParams = new URLSearchParams(window.location.search);
let sessionId = appVersion >= 4
  ? initialParams.get('session') || (appVersion < 8 ? localStorage.getItem('livingRoomSessionId') : null)
  : null;
let busy = false;
let pollTimer = null;
let activeViewer = null;
let currentDescription = '';
let currentPlanData = null;
let lastSceneGraph = null;
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
  const mvpBtn = $('#mvpBtn');
  if (mvpBtn) mvpBtn.disabled = value;
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
  const validation = appVersion >= 10 ? data.validation_report : null;
  const blockers = (validation?.blockers || []).map(issue =>
    `<li><b>${escapeHtml(issue.code)}</b> · ${escapeHtml(issue.message)}</li>`
  ).join('');
  const approvalBlocked = appVersion >= 10 && validation?.valid === false;
  addMessage('assistant', `<h3>Spatial plan ready · ${plan.room.width.toFixed(1)} × ${plan.room.depth.toFixed(1)}m</h3>
    <div class="concept-grid"><span><b>Style brief</b>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</span>
    <span><b>Layout</b>${plan.items.length} placed items · ${plan.openings.length} openings</span>
    <span><b>Canon camera</b>${plan.camera.fov_deg.toFixed(0)}° field of view</span>
    <span><b>Authority</b>Plan locks geometry; canon controls appearance</span></div>
    ${warnings ? `<ul class="plan-warnings">${warnings}</ul>` : ''}
    ${blockers ? `<div class="plan-validation" role="alert"><strong>Approval blocked · unresolved geometry</strong><ul class="plan-warnings">${blockers}</ul><small>Revise the plan to clear every blocker.</small></div>` : ''}
    <div class="actions"><button class="primary" onclick="approvePlan()" ${approvalBlocked ? 'disabled title="Resolve all geometry blockers before approval"' : ''}>Approve plan & render canon</button>
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
      addMessage('assistant', `<h3>Restored world</h3>The latest generated world and revision controls are ready.${v11RuntimeDetails(data)}`);
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
  if (busy) return;
  if (!description) {
    input.classList.add('input-error');
    input.setAttribute('aria-invalid', 'true');
    input.placeholder = 'Please describe a room first — include layout, era, materials, lighting.';
    setTimeout(() => { input.classList.remove('input-error'); input.removeAttribute('aria-invalid'); input.placeholder = 'A sunken 1970s lounge with walnut walls, amber lamps and rain against a wide window…'; }, 3000);
    return;
  }
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
  if (appVersion >= 10 && currentPlanData?.validation_report?.valid === false) {
    stageState.textContent = 'PLAN BLOCKED';
    stageState.className = 'stage-state working';
    addMessage('error', '<strong>Plan approval blocked</strong><br>Revise the plan until every geometry blocker is cleared.');
    return;
  }
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

function v11RuntimeDetails(data) {
  if (appVersion < 11) return '';
  const details = data.runtime_details || {};
  const compiler = details.compiler || data.compiler_result || {};
  const capability = compiler.capability || {};
  const versions = compiler.versions || {};
  const parity = details.parity ?? data.parity_report;
  const runtime = details.runtime ?? data.runtime_smoke_report;
  const qa = details.qa || data.qa_evidence || [];
  const exports = details.exports || data.export_results || {};
  const artifacts = details.artifacts || data.artifact_downloads || [];
  const failures = compiler.failures || [];
  const target = compiler.target || 'not compiled';
  const execution = compiler.execution || 'not_started';
  const versionText = [versions.product, versions.product_version, versions.compiler_version]
    .filter(Boolean).join(' · ') || 'not recorded';
  const qaEntries = Array.isArray(qa) ? qa : [qa];
  const qaLatest = qaEntries.at(-1) || {};
  const exportSummary = Object.entries(exports).map(([name, result]) =>
    `${escapeHtml(name)}: ${escapeHtml(result?.status || 'recorded')}`
  ).join(' · ') || 'none recorded';
  const failureMarkup = failures.length
    ? `<details><summary>${failures.length} compiler diagnostic${failures.length === 1 ? '' : 's'}</summary><ul>${failures.map(item => `<li>${escapeHtml(item.message || item.stderr_tail || item.reason_code || item.code || 'Recorded compiler failure')}</li>`).join('')}</ul></details>`
    : '<span><b>Failures</b>None recorded</span>';
  const artifactMarkup = artifacts.length
    ? `<ul>${artifacts.map(item => `<li><a class="download" href="${escapeHtml(item.download_url)}">${escapeHtml(item.role)} · ${escapeHtml(item.filename)}</a> <small>${escapeHtml(item.integrity)} · ${escapeHtml(item.sha256)}</small></li>`).join('')}</ul>`
    : '<p>No compiler/export artifacts recorded yet.</p>';
  const qaActions = qaLatest.decision === 'human_required'
    ? '<div class="actions"><button class="primary" onclick="adjudicateV11QA(\'approved\')">Approve QA evidence</button><button class="secondary" onclick="adjudicateV11QA(\'rejected\')">Reject QA evidence</button></div>'
    : '';
  return `<section class="v11-runtime-details" aria-label="V11 compiler and quality evidence">
    <h4>UPBGE primary · declared Godot fallback</h4>
    <div class="concept-grid">
      <span><b>Compiler</b>${escapeHtml(target)} · ${escapeHtml(compiler.status || 'not_started')} · ${escapeHtml(execution)}</span>
      <span><b>Capability</b>${capability.compatible === true ? 'verified compatible' : escapeHtml(capability.reason_code || 'not recorded')}</span>
      <span><b>Versions</b>${escapeHtml(versionText)}</span>
      <span><b>Parity gate</b>${parity ? (parity.passed === true ? 'passed' : 'failed') : 'not run'}</span>
      <span><b>Runtime smoke</b>${runtime ? escapeHtml(runtime.status || (runtime.passed ? 'passed' : 'failed')) : 'not applicable / not run'}</span>
      <span><b>QA</b>${escapeHtml(qaLatest.decision || qaLatest.status || 'not recorded')}</span>
      <span><b>Exports</b>${exportSummary}</span>
      <span><b>Manifests</b>${Number((compiler.manifests || data.compiler_manifests || []).length)} recorded</span>
      ${failureMarkup}
    </div>
    <h4>Verified compiler/export artifacts</h4>${artifactMarkup}${qaActions}
  </section>`;
}

async function adjudicateV11QA(verdict) {
  if (appVersion < 11 || !sessionId || busy) return;
  const rationale = prompt(`Why should this world be ${verdict}?`);
  if (!rationale?.trim()) return;
  setBusy(true, `Recording ${verdict} QA verdict`);
  try {
    const data = await fetchJson(`/api/session/${sessionId}/qa`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({reviewer_id:'user', verdict, rationale:rationale.trim()}),
    });
    addMessage('assistant', `<h3>QA ${escapeHtml(verdict)}</h3>${v11RuntimeDetails(data)}`);
    stageState.textContent = data.state === 'ready' ? '3D READY' : 'QA REJECTED';
    stageState.className = `stage-state ${data.state === 'ready' ? 'ready' : 'working'}`;
  } catch (error) {
    addMessage('error', `<strong>QA adjudication failed</strong><br>${escapeHtml(error.message)}`);
  } finally { setBusy(false); }
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
    wait = progress(appVersion >= 11
      ? 'Compiling the WorldContract with UPBGE primary and the declared Godot fallback policy…'
      : 'Applying the approved plan to scene graph, meshes, physics, and Godot…');
    const data = await fetchJson(`/api/session/${sessionId}/approve`, {method:'POST'});
    wait.remove();
    addMessage('assistant', `<h3>World ready</h3>${data.scene_graph.objects.length} plan-constrained objects · ${data.scene_graph.lights.length} lights · ${data.scene_graph.doors.length} doors.${v11RuntimeDetails(data)}`);
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

function buildSceneFromGraph(graph) {
  const room = graph.room;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#07090d');
  scene.fog = new THREE.Fog('#07090d', 20, 50);
  const addBox = (name, size, position, meshMaterial, cast = false) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), meshMaterial);
    mesh.name = name; mesh.position.set(...position); mesh.castShadow = cast; mesh.receiveShadow = true; scene.add(mesh); return mesh;
  };
  // Large floor extending beyond room walls so player has ground to walk on
  const floorSize = Math.max(room.width, room.depth) + 10;
  addBox('Floor', [floorSize,.08,floorSize], [0,-.04,0], material(room.floor_material,'#4e5055'));
  const wallMaterial_ = material(room.wall_material,'#bbb5aa');
  const halfWidth = room.width / 2, halfDepth = room.depth / 2, halfHeight = room.height / 2;
  addBox('Back wall',[room.width,room.height,.12],[0,halfHeight,-halfDepth-.06],wallMaterial_);
  addBox('East wall',[.12,room.height,room.depth],[halfWidth+.06,halfHeight,0],wallMaterial_);
  addBox('West wall',[.12,room.height,room.depth],[-halfWidth-.06,halfHeight,0],wallMaterial_);
  const grid = new THREE.GridHelper(floorSize, Math.ceil(floorSize * 2), 0x313947, 0x1c222c);
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
  return scene;
}

class FPSControls {
  constructor(camera, domElement) {
    this.camera = camera;
    this.domElement = domElement;
    this.isLocked = false;
    this.euler = new THREE.Euler(0, 0, 0, 'YXZ');
    this.PI_2 = Math.PI / 2;
    this.onMouseMove = (event) => {
      if (!this.isLocked) return;
      const dx = event.movementX || 0;
      const dy = event.movementY || 0;
      this.euler.setFromQuaternion(this.camera.quaternion);
      this.euler.y -= dx * 0.002;
      this.euler.x -= dy * 0.002;
      this.euler.x = Math.max(-this.PI_2, Math.min(this.PI_2, this.euler.x));
      this.camera.quaternion.setFromEuler(this.euler);
    };
    this.onPointerlockChange = () => {
      this.isLocked = document.pointerLockElement === this.domElement;
      this.domElement.dispatchEvent(new CustomEvent('lockchange', {detail:{locked:this.isLocked}}));
    };
    domElement.addEventListener('click', () => { if (!this.isLocked) domElement.requestPointerLock(); });
    document.addEventListener('mousemove', this.onMouseMove);
    document.addEventListener('pointerlockchange', this.onPointerlockChange);
  }
  dispose() {
    document.removeEventListener('mousemove', this.onMouseMove);
    document.removeEventListener('pointerlockchange', this.onPointerlockChange);
    if (this.isLocked) document.exitPointerLock();
  }
  getDirection() {
    return new THREE.Vector3(0, 0, -1).applyQuaternion(this.camera.quaternion);
  }
}

function buildGameViewer(graph) {
  disposeViewer();
  setStage('game');
  stageTitle.textContent = 'First-person exploration';
  stageState.textContent = 'GAME';
  stageState.className = 'stage-state ready';

  stageBody.innerHTML = `<canvas class="viewer" tabindex="0" aria-label="First-person game view"></canvas><div class="game-overlay" id="gameOverlay">Click to play</div><div class="game-hud">WASD move · MOUSE look · ESC exit · SHIFT run · SPACE jump</div>`;

  if (typeof THREE === 'undefined') {
    stageBody.innerHTML = '<div class="empty-stage"><p>Three.js could not load.</p></div>';
    return;
  }

  const canvas = stageBody.querySelector('canvas');
  const overlay = stageBody.querySelector('#gameOverlay');
  const scene = buildSceneFromGraph(graph);

  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:false});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  renderer.outputEncoding = THREE.sRGBEncoding;

  const camera = new THREE.PerspectiveCamera(75, 1, .05, 100);
  camera.position.set(0, 1.7, 0);

  const controls = new FPSControls(camera, canvas);

  canvas.addEventListener('lockchange', (e) => {
    overlay.classList.toggle('hidden', e.detail.locked);
  });
  overlay.addEventListener('click', () => canvas.requestPointerLock());

  const keys = {};
  const onKeyDown = e => { keys[e.code] = true; };
  const onKeyUp = e => { keys[e.code] = false; };
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('keyup', onKeyUp);

  const velocity = new THREE.Vector3();
  let onFloor = false;
  const SPEED = 4.0;
  const GRAVITY = 9.8;
  const PLAYER_HEIGHT = 1.7;
  const raycaster = new THREE.Raycaster();
  const clock = new THREE.Clock();

  // Room boundaries for clamping (keep player inside walls)
  const room = graph.room;
  const HALF_W = (room.width || 6) / 2 + 2.0;  // 2m beyond walls for exploration room
  const HALF_D = (room.depth || 6) / 2 + 2.0;
  const ROOM_HEIGHT = (room.height || 3) + 2;
  const FALL_RESET_Y = -10;  // If player falls below this, respawn

  const resize = () => {
    const rect = stageBody.getBoundingClientRect();
    camera.aspect = rect.width / Math.max(rect.height, 1);
    camera.updateProjectionMatrix();
    renderer.setSize(rect.width, rect.height, false);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(stageBody);
  resize();

  const state = {renderer, controls, observer, scene, camera, frame:0};
  activeViewer = state;

  const animate = () => {
    state.frame = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.1);

    if (controls.isLocked) {
      const speed = keys['ShiftLeft'] || keys['ShiftRight'] ? SPEED * 2 : SPEED;
      const direction = new THREE.Vector3();
      const right = new THREE.Vector3();
      camera.getWorldDirection(direction);
      direction.y = 0;
      direction.normalize();
      right.crossVectors(direction, camera.up).normalize();

      velocity.x = 0;
      velocity.z = 0;
      if (keys['KeyW']) { velocity.x += direction.x * speed; velocity.z += direction.z * speed; }
      if (keys['KeyS']) { velocity.x -= direction.x * speed; velocity.z -= direction.z * speed; }
      if (keys['KeyA']) { velocity.x -= right.x * speed; velocity.z -= right.z * speed; }
      if (keys['KeyD']) { velocity.x += right.x * speed; velocity.z += right.z * speed; }

      // Gravity
      velocity.y -= GRAVITY * delta;

      // Apply movement
      camera.position.x += velocity.x * delta;
      camera.position.z += velocity.z * delta;
      camera.position.y += velocity.y * delta;

      // Floor collision (raycast down)
      raycaster.set(camera.position, new THREE.Vector3(0, -1, 0));
      const intersects = raycaster.intersectObjects(scene.children, true);
      if (intersects.length > 0 && intersects[0].distance <= PLAYER_HEIGHT + 0.1) {
        camera.position.y = intersects[0].point.y + PLAYER_HEIGHT;
        velocity.y = 0;
        onFloor = true;
      } else if (camera.position.y <= PLAYER_HEIGHT) {
        // Fallback: if no raycast hit but at floor level, stay on floor
        camera.position.y = PLAYER_HEIGHT;
        velocity.y = 0;
        onFloor = true;
      } else {
        onFloor = false;
      }

      // Boundary clamping — keep player inside the room walls
      camera.position.x = Math.max(-HALF_W, Math.min(HALF_W, camera.position.x));
      camera.position.z = Math.max(-HALF_D, Math.min(HALF_D, camera.position.z));
      camera.position.y = Math.min(camera.position.y, ROOM_HEIGHT - 0.2);

      // Fall reset — if player somehow falls into the void, respawn at center
      if (camera.position.y < FALL_RESET_Y) {
        camera.position.set(0, PLAYER_HEIGHT, 0);
        velocity.set(0, 0, 0);
        onFloor = true;
      }

      // Jump
      if (keys['Space'] && onFloor) {
        velocity.y = 5.0;
        onFloor = false;
      }
    }

    renderer.render(scene, camera);
  };
  animate();
  logEvent('process', 'game_entered', {room: graph.room?.width});
}

function enterGame() {
  if (!lastSceneGraph) return;
  buildGameViewer(lastSceneGraph);
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
  if (![7, 8, 9, 10, 11].includes(appVersion)) return;
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
  lastSceneGraph = graph;
  setStage('world');
  stageTitle.textContent = graph.name || 'Generated world';
  stageState.textContent = '3D READY';
  stageState.className = 'stage-state ready';
  const readOnly = !!options.readOnly || isV8Historical();
  const cameraContract = options.cameraContract || null;
  const cameraLocked = appVersion >= 9 && !!cameraContract;
  const viewerActions = readOnly
    ? '<button class="revise-world" type="button" disabled>REVISE WORLD ↻</button><a class="download" aria-disabled="true" tabindex="-1">DOWNLOAD GODOT ↘</a>'
    : `<button class="revise-world" onclick="reviseWorld()">REVISE WORLD ↻</button><button class="enter-game" onclick="enterGame()">ENTER GAME ▶</button><a class="download" href="${downloadUrl}">DOWNLOAD GODOT ↘</a>`;
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
  } else if (stage === 'game') {
    const graph = payload.scene_graph || payload.world?.scene_graph || payload.graph || lastSceneGraph;
    if (graph) buildGameViewer(graph);
    else {
      stageTitle.textContent = 'Game mode';
      stageBody.innerHTML = '<div class="empty-stage"><p>Generate a world first, then enter game mode.</p></div>';
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
  // GAME is a client-side-only stage — no server fetch needed
  if (stage === 'game') {
    setStage('game');
    v8CurrentStage = 'game';
    if (lastSceneGraph) {
      buildGameViewer(lastSceneGraph);
    } else {
      stageTitle.textContent = 'Game mode';
      stageState.textContent = 'WAITING';
      stageState.className = 'stage-state';
      stageBody.innerHTML = '<div class="empty-stage"><p>Build a world first, then enter game mode to walk around with WASD + mouse look.</p></div>';
    }
    return;
  }
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
// ─── MVP Pipeline Mode ─────────────────────────────────────────────────────
// Implements Req 9.4, 9.5, 1.4, 1.8: SSE-driven pipeline progress,
// structured failure display, download links, and launch fallback.
// This is additive — existing V3-V11 full-mode behavior is unchanged.

const MVP_STAGES = ['interpreting', 'planning', 'building_scene', 'compiling', 'validating', 'launching'];

let mvpEventSource = null;

function mvpStageLabel(stage) {
  const labels = {
    interpreting: 'Interpreting',
    planning: 'Planning',
    building_scene: 'Building Scene',
    compiling: 'Compiling',
    validating: 'Validating',
    launching: 'Launching',
    done: 'Complete',
  };
  return labels[stage] || stage;
}

function renderMvpProgress(currentStage, elapsed) {
  const steps = MVP_STAGES.map(s => {
    const active = s === currentStage;
    const done = MVP_STAGES.indexOf(s) < MVP_STAGES.indexOf(currentStage);
    const cls = active ? 'mvp-step active' : done ? 'mvp-step done' : 'mvp-step';
    return `<span class="${cls}" data-stage="${escapeHtml(s)}">${mvpStageLabel(s)}</span>`;
  }).join('');
  const elapsedText = elapsed ? ` · ${escapeHtml(String(elapsed).replace(/s$/, ''))}s` : '';
  return `<div class="mvp-progress-bar">${steps}</div><div class="mvp-progress-status"><span class="spinner"></span> <strong>${mvpStageLabel(currentStage)}</strong>${elapsedText}</div>`;
}

function renderMvpSuccess(data) {
  const downloadUrl = escapeHtml(data.download_url || '');
  const qualityLabel = data.quality_label ? `<span class="mvp-quality">${escapeHtml(data.quality_label)}</span>` : '';
  return `<div class="mvp-result mvp-success">
    <div class="mvp-result-icon">&#x2714;</div>
    <h3>Game Running</h3>
    <p>Your world is alive and running in UPBGE. ${qualityLabel}</p>
    ${downloadUrl ? `<a class="mvp-download-link secondary-action" href="${downloadUrl}" download>Download .blend file</a>` : ''}
  </div>`;
}

function renderMvpLaunchFallback(data) {
  const downloadUrl = escapeHtml(data.download_url || '');
  const instructions = data.fallback_instructions || 'Open the .blend file in UPBGE blenderplayer or Blender with the game engine enabled.';
  return `<div class="mvp-result mvp-launch-fallback">
    <div class="mvp-result-icon">&#x26A0;</div>
    <h3>Compilation Succeeded — Auto-Launch Failed</h3>
    <p>Your game was compiled successfully but could not be launched automatically.</p>
    ${downloadUrl ? `<a class="mvp-download-link primary-action" href="${downloadUrl}" download>Download .blend file</a>` : ''}
    <div class="mvp-instructions-box">
      <strong>Manual Launch Instructions</strong>
      <p>${escapeHtml(instructions)}</p>
    </div>
  </div>`;
}

function renderMvpFailure(data) {
  const failureStage = data.failure_stage || 'unknown';
  const reason = data.error || 'An unspecified error occurred.';
  const reasonCode = data.reason_code || '';
  return `<div class="mvp-result mvp-failure">
    <div class="mvp-result-icon">&#x2718;</div>
    <h3>Pipeline Failed at: ${escapeHtml(mvpStageLabel(failureStage))}</h3>
    <p class="mvp-failure-reason">${escapeHtml(reason)}</p>
    ${reasonCode ? `<span class="mvp-reason-code">${escapeHtml(reasonCode)}</span>` : ''}
  </div>`;
}

function closeMvpEventSource() {
  if (mvpEventSource) {
    mvpEventSource.close();
    mvpEventSource = null;
  }
}

async function sendDescriptionMvp() {
  const description = input.value.trim();
  if (busy) return;
  if (!description) {
    input.classList.add('input-error');
    input.setAttribute('aria-invalid', 'true');
    input.placeholder = 'Please describe a room first — include layout, era, materials, lighting.';
    setTimeout(() => { input.classList.remove('input-error'); input.removeAttribute('aria-invalid'); input.placeholder = 'A sunken 1970s lounge with walnut walls, amber lamps and rain against a wide window…'; }, 3000);
    return;
  }
  currentDescription = description;
  addMessage('user', escapeHtml(description));
  input.value = '';
  setBusy(true, 'MVP Pipeline');
  logEvent('process', 'mvp_pipeline_started', {description: description.slice(0, 120)});

  let progressElement = null;
  try {
    await ensureSession();

    // POST to MVP describe endpoint
    const data = await fetchJson(`/api/session/${sessionId}/describe_mvp`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description, mode: 'mvp'}),
    });

    // Show initial progress
    progressElement = addMessage('progress', renderMvpProgress('interpreting', ''));

    // Connect to SSE events endpoint
    closeMvpEventSource();
    const eventsUrl = data.events_url || `/api/session/${sessionId}/events`;
    mvpEventSource = new EventSource(eventsUrl);

    mvpEventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        if (payload.stage === 'done') {
          // Terminal event — pipeline finished
          closeMvpEventSource();

          if (progressElement) progressElement.remove();
          progressElement = null;

          if (payload.state === 'ready') {
            if (payload.launch_failed) {
              // Req 1.8, 9.4: auto-launch failed, show download + instructions
              addMessage('assistant', renderMvpLaunchFallback(payload));
              stageState.textContent = 'LAUNCH FAILED';
              stageState.className = 'stage-state working';
              logEvent('process', 'mvp_launch_failed', {download_url: payload.download_url});
            } else {
              // Req 1.4: full success — game running
              addMessage('assistant', renderMvpSuccess(payload));
              stageState.textContent = 'GAME RUNNING';
              stageState.className = 'stage-state ready';
              logEvent('process', 'mvp_success', {quality_label: payload.quality_label});
            }
          } else if (payload.state === 'error') {
            // Req 9.5: pipeline failure — show stage + reason, NOT generic error
            addMessage('error', renderMvpFailure(payload));
            stageState.textContent = 'PIPELINE FAILED';
            stageState.className = 'stage-state working';
            logEvent('process', 'mvp_pipeline_failed', {
              failure_stage: payload.failure_stage,
              reason_code: payload.reason_code,
            });
          }

          // Update the right panel (stage area) with the result
          stageTitle.textContent = payload.game_running ? 'Game Running' : 'Walkable World Ready';
          
          // Fetch scene graph so GAME tab can build a first-person view
          if (payload.state === 'ready') {
            fetchJson(`/api/session/${sessionId}/scene_data`).then(sceneData => {
              if (sceneData && sceneData.room) {
                lastSceneGraph = sceneData;
                buildViewer(sceneData, payload.download_url || '');
              }
            }).catch(() => {
              // Scene fetch failed — show static result instead
              stageBody.innerHTML = `<div class="mvp-stage-result">
                  <div class="mvp-stage-icon">${payload.game_running ? '🎮' : '📦'}</div>
                  <h3>${payload.game_running ? 'Game is running in fullscreen' : 'Your world is compiled and ready'}</h3>
                  <p>${payload.quality_label ? 'Quality: ' + payload.quality_label : ''}</p>
                  <p class="game-cta">Click <b>GAME</b> tab or <b>ENTER GAME ▶</b> to walk around in first person.</p>
                  ${payload.download_url ? `<a class="download" href="${payload.download_url}" download>Download .blend</a>` : ''}
                </div>`;
            });
          } else {
            stageBody.innerHTML = `<div class="mvp-stage-result mvp-stage-error">
                <h3>Pipeline Failed: ${payload.failure_stage || 'unknown'}</h3>
                <p>${payload.error || 'An error occurred'}</p>
              </div>`;
          }

          setBusy(false);
          input.focus();
        } else {
          // Progress event — update the stage indicator
          setStage('world');  // MVP mode always targets the "world" stage in the rail
          if (progressElement) {
            progressElement.innerHTML = renderMvpProgress(payload.stage, payload.elapsed);
          }
          logEvent('process', 'mvp_stage_progress', {stage: payload.stage, elapsed: payload.elapsed});
        }
      } catch (parseError) {
        // Silently ignore malformed SSE payloads
      }
    };

    mvpEventSource.onerror = () => {
      closeMvpEventSource();
      if (progressElement) progressElement.remove();
      progressElement = null;
      addMessage('error', '<strong>Connection lost</strong><br>The real-time pipeline connection was interrupted. Check the session status.');
      stageState.textContent = 'DISCONNECTED';
      stageState.className = 'stage-state working';
      setBusy(false);
      input.focus();
    };

  } catch (error) {
    closeMvpEventSource();
    if (progressElement) progressElement.remove();
    addMessage('error', `<strong>MVP pipeline failed to start</strong><br>${escapeHtml(error.message)}`);
    stageState.textContent = 'ERROR';
    stageState.className = 'stage-state working';
    setBusy(false);
    input.focus();
  }
}

// ─── End MVP Pipeline Mode ────────────────────────────────────────────────────

// --- V12 Photo Mode ---

let inputMode = 'text';
let selectedPhotoFile = null;

function setInputMode(mode) {
  inputMode = mode;
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  const composer = $('#composer');
  const photoZone = $('#photoUploadZone');
  if (!composer || !photoZone) return;
  if (mode === 'photo') {
    composer.style.display = 'none';
    photoZone.style.display = '';
  } else {
    composer.style.display = '';
    photoZone.style.display = 'none';
  }
  logEvent('click', 'input_mode_change', {mode});
}

function initPhotoUpload() {
  if (appVersion < 12) return;
  const dropzone = $('#uploadDropzone');
  const fileInput = $('#photoFileInput');
  if (!dropzone || !fileInput) return;

  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });

  dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && (file.type === 'image/jpeg' || file.type === 'image/png')) handlePhotoSelect(file);
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handlePhotoSelect(fileInput.files[0]);
  });
}

function handlePhotoSelect(file) {
  selectedPhotoFile = file;
  const preview = $('#photoPreview');
  const previewImg = $('#photoPreviewImg');
  const generateBtn = $('#photoGenerateBtn');
  const dropzone = $('#uploadDropzone');

  previewImg.src = URL.createObjectURL(file);
  preview.hidden = false;
  dropzone.style.display = 'none';
  generateBtn.disabled = false;
  logEvent('click', 'photo_selected', {name: file.name, size: file.size});
}

function removePhoto() {
  selectedPhotoFile = null;
  const preview = $('#photoPreview');
  const dropzone = $('#uploadDropzone');
  const generateBtn = $('#photoGenerateBtn');
  const fileInput = $('#photoFileInput');

  preview.hidden = true;
  dropzone.style.display = '';
  generateBtn.disabled = true;
  fileInput.value = '';
  logEvent('click', 'photo_removed');
}

async function sendPhoto() {
  if (!selectedPhotoFile || busy) return;
  setBusy(true, 'Processing photo');
  setStage('brief');
  addMessage('user', `<span class="photo-indicator">📷</span> Uploaded: ${escapeHtml(selectedPhotoFile.name)}`);

  const wait = progress('Uploading photo and starting photo-to-world pipeline…');

  try {
    // Upload the file to the server first
    const formData = new FormData();
    formData.append('photo', selectedPhotoFile);

    const uploadResp = await fetch('/api/session/photo/upload', {
      method: 'POST',
      headers: {'X-App-Version': String(appVersion)},
      body: formData,
    });
    if (!uploadResp.ok) {
      const err = await uploadResp.json().catch(() => ({error: 'Upload failed'}));
      throw new Error(err.error || `Upload failed (${uploadResp.status})`);
    }
    const uploadResult = await uploadResp.json();

    wait.remove();

    // Show pipeline progress
    const pipelineWait = progress('Running photo pipeline: segmentation → depth → objects → audio → assembly…');

    // V13: use browser endpoint (no external launch), V12: use standard photo endpoint
    const endpoint = appVersion >= 13 ? '/api/session/photo/browser' : '/api/session/photo';

    const data = await fetchJson(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_image: uploadResult.path, mode: 'mvp'}),
    });

    pipelineWait.remove();
    sessionId = data.session_id;

    // V13: render in-browser 3D game
    if (appVersion >= 13 && data.scene_url) {
      const quality = data.quality_classification || 'unknown';
      const objects = data.object_count || 0;
      const duration = data.total_duration_s ? data.total_duration_s.toFixed(1) : '?';
      addMessage('system', `
        <strong>Photo pipeline complete</strong><br>
        Quality: <code>${escapeHtml(quality)}</code> · Objects: ${objects} · Duration: ${duration}s<br>
        Launching in-browser 3D…
      `);
      await renderBrowserGame(data.scene_url);
    } else {
      // V12 fallback: show result panel
      const quality = data.quality_classification || 'unknown';
      const objects = data.object_count || 0;
      const duration = data.total_duration_s ? data.total_duration_s.toFixed(1) : '?';
      const compiled = data.compilation_success ? '✓ Game launched' : '⚠ Compilation pending';

      addMessage('system', `
        <strong>Photo pipeline complete</strong><br>
        Quality: <code>${escapeHtml(quality)}</code> · Objects: ${objects} · Duration: ${duration}s<br>
        ${compiled}
      `);

      setStage('game');
      stageTitle.textContent = 'Photo World Ready';
      stageBody.innerHTML = `
        <div class="photo-result">
          <div class="photo-result-summary">
            <h3>Photo → Playable World</h3>
            <dl>
              <dt>Session</dt><dd>${escapeHtml(data.session_id)}</dd>
              <dt>Quality</dt><dd>${escapeHtml(quality)}</dd>
              <dt>Objects detected</dt><dd>${objects}</dd>
              <dt>Pipeline duration</dt><dd>${duration}s</dd>
              <dt>Compilation</dt><dd>${data.compilation_success ? 'Success' : 'Failed: ' + escapeHtml(data.compilation_reason_code || '')}</dd>
              ${data.launch_pid ? `<dt>Game PID</dt><dd>${data.launch_pid}</dd>` : ''}
            </dl>
          </div>
        </div>
      `;
    }

  } catch (error) {
    wait?.remove();
    addMessage('error', `<strong>Photo pipeline failed</strong><br>${escapeHtml(error.message)}`);
    stageState.textContent = 'ERROR';
  } finally {
    stopPolling();
    setBusy(false);
  }
}

// --- V13: In-browser 3D game renderer ---

async function renderBrowserGame(sceneUrl) {
  const resp = await fetch(sceneUrl);
  const scene = await resp.json();

  setStage('game');
  stageTitle.textContent = 'Your World';
  stageState.textContent = 'PLAYING';
  stageState.className = 'stage-state ready';

  const container = document.createElement('div');
  container.className = 'browser-game-container';
  container.id = 'gameContainer';
  container.innerHTML = '<div class="game-overlay" id="gameOverlay"><p>Click to enter</p><p class="game-controls-hint">WASD to move · Mouse to look · ESC to exit</p></div>';
  stageBody.innerHTML = '';
  stageBody.appendChild(container);

  // Initialize Three.js scene
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  const threeScene = new THREE.Scene();
  threeScene.background = new THREE.Color(0x1a1a2e);

  // Camera — frame the whole room from a sensible viewpoint (V7's behavior)
  const camera = new THREE.PerspectiveCamera(scene.camera.fov, container.clientWidth / container.clientHeight, 0.1, 100);
  // Position camera at room center, eye height, looking forward
  camera.position.set(0, 1.6, room.depth * 0.4);

  // Room geometry
  const room = scene.room;
  // Floor
  const floorGeo = new THREE.PlaneGeometry(room.width, room.depth);
  const floorMat = new THREE.MeshStandardMaterial({color: room.floor_color, roughness: 0.9});
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  threeScene.add(floor);

  // Walls
  const wallMat = new THREE.MeshStandardMaterial({color: room.wall_color, roughness: 0.7, side: THREE.DoubleSide});
  // Back wall
  const backWall = new THREE.Mesh(new THREE.PlaneGeometry(room.width, room.height), wallMat);
  backWall.position.set(0, room.height/2, -room.depth/2);
  threeScene.add(backWall);
  // Left wall
  const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(room.depth, room.height), wallMat);
  leftWall.position.set(-room.width/2, room.height/2, 0);
  leftWall.rotation.y = Math.PI/2;
  threeScene.add(leftWall);
  // Right wall
  const rightWall = new THREE.Mesh(new THREE.PlaneGeometry(room.depth, room.height), wallMat);
  rightWall.position.set(room.width/2, room.height/2, 0);
  rightWall.rotation.y = -Math.PI/2;
  threeScene.add(rightWall);
  // Ceiling
  const ceilGeo = new THREE.PlaneGeometry(room.width, room.depth);
  const ceilMat = new THREE.MeshStandardMaterial({color: room.ceiling_color, roughness: 0.6});
  const ceiling = new THREE.Mesh(ceilGeo, ceilMat);
  ceiling.rotation.x = Math.PI / 2;
  ceiling.position.y = room.height;
  threeScene.add(ceiling);

  // Objects
  for (const obj of scene.objects) {
    let geo;
    const [w, h, d] = obj.dimensions;
    if (obj.shape === 'cylinder') geo = new THREE.CylinderGeometry(w/2, w/2, h, 16);
    else if (obj.shape === 'sphere') geo = new THREE.SphereGeometry(Math.max(w,h,d)/2, 16, 16);
    else geo = new THREE.BoxGeometry(w, h, d);

    const mat = new THREE.MeshStandardMaterial({
      color: obj.color,
      roughness: obj.roughness,
      metalness: obj.metallic,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    mesh.rotation.set(
      obj.rotation[0] * Math.PI/180,
      obj.rotation[1] * Math.PI/180,
      obj.rotation[2] * Math.PI/180
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    threeScene.add(mesh);
  }

  // Lights — balanced ambient + scene lights for correct material color reading
  const ambient = new THREE.AmbientLight(0xffffff, 0.4);
  threeScene.add(ambient);
  // Hemisphere light for natural indoor fill
  const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 0.3);
  threeScene.add(hemi);
  for (const light of scene.lights) {
    if (light.type === 'directional') {
      const dl = new THREE.DirectionalLight(light.color, Math.min(light.intensity / 100, 2.0));
      dl.position.set(...light.position);
      dl.castShadow = true;
      threeScene.add(dl);
    } else {
      const pl = new THREE.PointLight(light.color, Math.min(light.intensity / 100, 2.0), 20);
      pl.position.set(...light.position);
      threeScene.add(pl);
    }
  }

  // First-person controls (pointer lock)
  const velocity = new THREE.Vector3();
  const direction = new THREE.Vector3();
  const keys = {w: false, a: false, s: false, d: false};
  let euler = new THREE.Euler(0, 0, 0, 'YXZ');
  let locked = false;

  const overlay = document.getElementById('gameOverlay');

  renderer.domElement.addEventListener('click', () => {
    if (document.pointerLockElement === renderer.domElement) return;
    try {
      renderer.domElement.requestPointerLock();
    } catch (e) {
      // Pointer lock unavailable — show fallback message
      overlay.innerHTML = '<p>⚠️ Your browser blocked pointer lock.</p><p class="game-controls-hint">Try clicking the game area again, or use a different browser. Some browsers require a user gesture or fullscreen first.</p>';
      overlay.style.display = '';
    }
  });

  document.addEventListener('pointerlockchange', () => {
    locked = document.pointerLockElement === renderer.domElement;
    overlay.style.display = locked ? 'none' : '';
  });

  document.addEventListener('pointerlockerror', () => {
    locked = false;
    overlay.innerHTML = '<p>⚠️ Pointer lock failed</p><p class="game-controls-hint">Your browser may require clicking the game area while in fullscreen. Try pressing F11 first, then click again.</p>';
    overlay.style.display = '';
  });

  document.addEventListener('mousemove', (e) => {
    if (!locked) return;
    euler.setFromQuaternion(camera.quaternion);
    euler.y -= e.movementX * 0.002;
    euler.x -= e.movementY * 0.002;
    euler.x = Math.max(-Math.PI/2, Math.min(Math.PI/2, euler.x));
    camera.quaternion.setFromEuler(euler);
  });

  document.addEventListener('keydown', (e) => { if (keys.hasOwnProperty(e.key.toLowerCase())) keys[e.key.toLowerCase()] = true; });
  document.addEventListener('keyup', (e) => { if (keys.hasOwnProperty(e.key.toLowerCase())) keys[e.key.toLowerCase()] = false; });

  // Animation loop
  function animate() {
    requestAnimationFrame(animate);

    if (locked) {
      const speed = 0.05;
      direction.set(0, 0, 0);
      if (keys.w) direction.z -= 1;
      if (keys.s) direction.z += 1;
      if (keys.a) direction.x -= 1;
      if (keys.d) direction.x += 1;
      direction.normalize();

      // Move relative to camera orientation (Y-locked)
      const forward = new THREE.Vector3();
      camera.getWorldDirection(forward);
      forward.y = 0;
      forward.normalize();
      const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0));

      camera.position.addScaledVector(forward, -direction.z * speed);
      camera.position.addScaledVector(right, direction.x * speed);
      camera.position.y = 1.6; // Lock to eye height
    }

    renderer.render(threeScene, camera);
  }
  animate();

  // Handle resize
  const resizeObserver = new ResizeObserver(() => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });
  resizeObserver.observe(container);

  logEvent('process', 'browser_game_entered', {objects: scene.objects.length, quality: scene.quality});
}

// Initialize photo upload on load
if (appVersion >= 12) {
  document.addEventListener('DOMContentLoaded', initPhotoUpload);
}

// ─── End V12 Photo Mode ───────────────────────────────────────────────────────

Object.assign(window, {approvePlan, revisePlan, editDescription, showPlanArtifact, refreshOutput, approveImage, rejectImage, reviseWorld, adjudicateV11QA, resetLockedCamera, logEvent, sendDescriptionMvp, enterGame, setInputMode, removePhoto, sendPhoto, renderBrowserGame});
logEvent('lifecycle', 'app_loaded', {path:window.location.pathname});
loadReadiness();
setInterval(loadReadiness, 15000);
initWorkspaceSplitter();
initV8();
if (appVersion >= 4 && (appVersion < 8 || sessionId)) restoreSession();
input.focus();
