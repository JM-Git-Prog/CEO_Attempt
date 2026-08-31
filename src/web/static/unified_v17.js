/*
 * V17 split-screen — LEFT PANEL: builder-agent chat + pipeline event wiring.
 *
 * This is a pure client over the existing V16 unified pipeline API. It sends the
 * X-App-Version:16 header (the page ?v=17 is a UI skin; the pipeline is V16) and
 * reuses every V16 route verbatim:
 *   POST /api/session/unified/start
 *   POST /api/session/{id}/message
 *   POST /api/session/{id}/game_message
 *   POST /api/session/{id}/approve/{stage}
 *   GET  /api/session/{id}/events            (SSE, event: pipeline.progress / pipeline.terminal)
 *   GET  /api/session/{id}/{dream_preview|blockout|canon}
 *
 * It hands progress + terminal signals to the right-panel world viewer through
 * window.LRWorld (defined by world_v17.js). The two panels stay decoupled: this
 * file never touches Three.js; world_v17.js never touches the chat DOM.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const messages = $("messages");
  const composer = $("composer");
  const input = $("message");
  const send = $("send");
  const approval = $("approval");
  const status = $("status");
  const stageTitle = $("stageTitle");
  const sessionLabel = $("sessionId");
  const details = $("details");
  const progressFill = $("progressFill");
  const artifactStrip = $("artifactStrip");

  let sessionId = "";
  let events = null;
  let currentApproval = null;   // {stage, object_id} when an approval gate is open
  let pipelineStarted = false;
  let lastStage = "";
  const shownArtifacts = new Set();

  const APP_VERSION = String(window.APP_VERSION || 16);

  // ─── Helpers ───────────────────────────────────────────────────────────

  function appendMessage(role, text) {
    const item = document.createElement("div");
    item.className = `message ${role}`;
    item.textContent = text;
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
  }

  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-App-Version": APP_VERSION,
        ...(options.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
  }

  function world() {
    return window.LRWorld || null;
  }

  // ─── Artifact thumbnails (dream/blockout/canon) ─────────────────────────

  function showArtifactThumb(kind) {
    if (!sessionId || shownArtifacts.has(kind)) return;
    const routes = {
      dream_preview: `/api/session/${sessionId}/dream_preview`,
      blockout: `/api/session/${sessionId}/blockout`,
      canon: `/api/session/${sessionId}/canon`,
    };
    const url = routes[kind];
    if (!url) return;
    const img = document.createElement("img");
    img.alt = kind.replace("_", " ");
    img.title = kind.replace("_", " ");
    img.src = `${url}?t=${Date.now()}`;
    img.onerror = () => {
      // Not ready yet — retry a few times, then drop it silently.
      const tries = (Number(img.dataset.tries) || 0) + 1;
      img.dataset.tries = String(tries);
      if (tries <= 5) setTimeout(() => { img.src = `${url}?retry=${Date.now()}`; }, 2500);
      else img.remove();
    };
    img.addEventListener("click", () => window.open(`${url}?t=${Date.now()}`, "_blank"));
    artifactStrip.appendChild(img);
    shownArtifacts.add(kind);
  }

  // ─── Approval gate mapping (mirror of the V16 adapter's _APPROVAL_STAGES) ─

  function approvalFor(event) {
    const stage = event.current_stage || "";
    const map = {
      canon_approval: "canon",
      blockout_approval: "blockout",
      object_canon_approval: "object_canon",
      mesh_approval: "mesh",
      final_world_qa: "world",
    };
    const key = map[stage];
    if (!key) return null;
    return { stage: key, object_id: event.object_id || null };
  }

  // ─── Progress handling ──────────────────────────────────────────────────

  function handleProgress(event) {
    const stage = event.current_stage || "";
    const state = event.state || "running";

    const displayState = {
      completed: "✓ DONE",
      running: "RUNNING",
      awaiting_approval: "APPROVE →",
      waiting_approval: "APPROVE →",
      awaiting_external: "GENERATING…",
      blocked: "BLOCKED",
      error: "ERROR",
    }[state] || state.toUpperCase();

    status.textContent = displayState;
    stageTitle.textContent = (stage || "pipeline").replaceAll("_", " ");

    const total = Number(event.objects_total || 1);
    const complete = Number(event.objects_complete || 0);
    progressFill.style.width = `${Math.min(100, Math.round((100 * complete) / total))}%`;

    const elapsed = event.elapsed_seconds?.toFixed?.(1) || "0";
    details.textContent = `Plan r${event.plan_revision || 0} · ${event.finality || "provisional"} · ${elapsed}s`;

    // Artifact thumbnails as stages complete.
    if (stage === "dream_preview" && state === "completed") showArtifactThumb("dream_preview");
    if ((stage === "canon_generation" && state === "completed") || stage === "canon_approval") showArtifactThumb("canon");
    if ((stage === "spatial_reconstruction" && state === "completed") || stage === "blockout_approval") showArtifactThumb("blockout");

    // Tell the world panel to (re)load meshes when object stages progress or
    // when the world contract is assembled/compiled.
    const w = world();
    if (w) {
      if (stage === "mesh_generation" && state === "completed" && event.object_id) {
        w.onObjectReady(event.object_id);
      }
      if ((stage === "world_contract" || stage === "compile" || stage === "material_pass_1") && state === "completed") {
        w.refreshScene();
      }
    }

    // Approval gate detection.
    currentApproval = approvalFor(event);
    const needsApproval = currentApproval && (state === "waiting_approval" || state === "awaiting_approval");
    approval.style.display = needsApproval ? "inline-block" : "none";
    if (needsApproval) {
      approval.textContent = `Approve ${currentApproval.stage.replace("_", " ")}`;
    }

    if (stage !== lastStage) lastStage = stage;
  }

  function connectEvents(url) {
    events?.close();
    events = new EventSource(url);
    events.addEventListener("pipeline.progress", (message) => {
      try { handleProgress(JSON.parse(message.data)); } catch (error) { console.error(error); }
    });
    events.addEventListener("pipeline.terminal", (message) => {
      let terminal = {};
      try { terminal = JSON.parse(message.data); } catch (_) { /* ignore */ }
      const state = terminal.state || "completed";
      status.textContent = state === "completed" ? "✓ COMPLETED" : state.toUpperCase();
      if (state === "completed" && sessionId) {
        appendMessage("system", "World complete — walk in on the right (Walk in / WASD).");
        world()?.refreshScene(true);
      }
      events?.close();
    });
    events.onerror = () => {
      status.textContent = "RECONNECTING";
      setTimeout(() => { if (sessionId) connectEvents(`/api/session/${sessionId}/events`); }, 3000);
    };
  }

  // ─── Approval action ────────────────────────────────────────────────────

  approval.addEventListener("click", async () => {
    if (!sessionId || !currentApproval) return;
    approval.disabled = true;
    try {
      const body = { approved: true };
      // Blockout approval requires a selected-objects list; approve all detected.
      if (currentApproval.stage === "blockout") {
        try {
          const picker = await fetch(`/api/session/${sessionId}/object_picker`).then((r) => (r.ok ? r.json() : null));
          if (picker && Array.isArray(picker.objects)) {
            body.selected_object_ids = picker.objects.map((o) => o.object_id || o.id).filter(Boolean);
          }
        } catch (_) { /* fall through — server will 409 if it truly needs selection */ }
      }
      if (currentApproval.object_id) body.object_id = currentApproval.object_id;
      await jsonRequest(`/api/session/${sessionId}/approve/${currentApproval.stage}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      appendMessage("system", `Approved ${currentApproval.stage.replace("_", " ")}. Continuing…`);
      approval.style.display = "none";
      currentApproval = null;
    } catch (error) {
      appendMessage("system", `Approval failed: ${error.message}`);
    } finally {
      approval.disabled = false;
    }
  });

  // ─── Session lifecycle ──────────────────────────────────────────────────

  async function start() {
    const params = new URLSearchParams(location.search);
    const existing = params.get("session");

    if (existing) {
      sessionId = existing;
      sessionLabel.textContent = sessionId.slice(0, 8);
      status.textContent = "RESUMING";
      messages.replaceChildren();
      appendMessage("system", `Reconnecting to session ${sessionId.slice(0, 8)}…`);
      pipelineStarted = true;
      connectEvents(`/api/session/${sessionId}/events`);
      world()?.attach(sessionId);
      input.focus();
      return;
    }

    try {
      const data = await jsonRequest("/api/session/unified/start", { method: "POST", body: "{}" });
      sessionId = data.session_id;
      const url = new URL(location.href);
      url.searchParams.set("session", sessionId);
      history.replaceState(null, "", url.toString());
      sessionLabel.textContent = sessionId.slice(0, 8);
      status.textContent = "CONVERSATION";
      messages.replaceChildren();
      appendMessage("assistant", data.opening_message || "Describe the space you'd like to create.");
      connectEvents(data.events_url || `/api/session/${sessionId}/events`);
      world()?.attach(sessionId);
      input.focus();
    } catch (error) {
      status.textContent = "ERROR";
      appendMessage("system", error.message);
    }
  }

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || !sessionId) return;
    appendMessage("user", message);
    input.value = "";
    send.disabled = true;

    try {
      // Once the pipeline is building, further chat is game-design conversation
      // (parallel to the GPU work), matching the V16 adapter's two-lane design.
      const endpoint = pipelineStarted
        ? `/api/session/${sessionId}/game_message`
        : `/api/session/${sessionId}/message`;
      const data = await jsonRequest(endpoint, { method: "POST", body: JSON.stringify({ message }) });
      if (data.message) appendMessage("assistant", data.message);

      if (!pipelineStarted && data.brief) {
        pipelineStarted = true;
        appendMessage("system", "Brief locked. Building the world — watch the right panel.");
        world()?.beginBuild();
      }
    } catch (error) {
      appendMessage("system", error.message);
    } finally {
      send.disabled = false;
      input.focus();
    }
  });

  // Enter submits; Shift+Enter newlines.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  // Kick off once the world panel has registered its hook (or after a short
  // wait if it hasn't — start() degrades gracefully when window.LRWorld is null).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
