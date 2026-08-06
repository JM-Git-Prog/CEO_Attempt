(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const messages = $("messages");
  const composer = $("composer");
  const input = $("message");
  const send = $("send");
  const status = $("status");
  const stageTitle = $("stageTitle");
  const sessionLabel = $("sessionId");
  const details = $("details");
  const artifact = $("artifact");
  const progressFill = $("progressFill");
  const approval = $("approval");
  let sessionId = "";
  let currentApproval = null;
  let events = null;

  // Track which artifacts have been successfully loaded
  const loadedArtifacts = new Set();
  let artifactPollInterval = null;
  let lastStage = "";

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
      headers: {"Content-Type": "application/json", "X-App-Version": "16", ...(options.headers || {})}
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
  }

  // ─── Artifact Display System ─────────────────────────────────────────────

  function showLoading(message) {
    artifact.replaceChildren();
    const container = document.createElement("div");
    container.className = "loading";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    const label = document.createElement("p");
    label.textContent = message;
    container.appendChild(spinner);
    container.appendChild(label);
    artifact.appendChild(container);
  }

  function showImage(url, alt) {
    const image = document.createElement("img");
    image.src = url;
    image.alt = alt;
    image.style.cssText = "max-width:100%;max-height:60vh;object-fit:contain;border-radius:6px;";
    image.onerror = () => {
      // Image not ready yet — retry in 3s
      setTimeout(() => {
        image.src = url + (url.includes("?") ? "&" : "?") + "retry=" + Date.now();
      }, 3000);
    };
    return image;
  }

  function showArtifact(kind, objectId = "") {
    if (!sessionId) return;
    const key = `${kind}:${objectId}`;

    const routes = {
      dream_preview: `/api/session/${sessionId}/dream_preview`,
      blockout: `/api/session/${sessionId}/blockout`,
      canon: `/api/session/${sessionId}/canon`,
      mesh: `/api/session/${sessionId}/mesh/${encodeURIComponent(objectId)}`
    };
    const url = routes[kind];
    if (!url) return;

    // Clear and show loading state
    artifact.replaceChildren();

    if (kind === "mesh") {
      const container = document.createElement("div");
      container.style.cssText = "text-align:center;padding:20px;";
      const label = document.createElement("p");
      label.style.cssText = "color:#8edbb8;font-size:14px;margin-bottom:8px;";
      label.textContent = `Mesh: ${objectId.slice(0, 8)}…`;
      const link = document.createElement("a");
      link.href = url;
      link.textContent = "Download GLB";
      link.style.cssText = "color:#8edbb8;";
      container.appendChild(label);
      container.appendChild(link);
      artifact.appendChild(container);
      loadedArtifacts.add(key);
      return;
    }

    // For images — show with retry logic
    const cacheBust = `?t=${Date.now()}`;
    const image = showImage(url + cacheBust, `${kind.replace("_", " ")} artifact`);
    artifact.appendChild(image);
    loadedArtifacts.add(key);
  }

  // Poll for the latest available artifact and display it
  function startArtifactPolling() {
    if (artifactPollInterval) return;
    artifactPollInterval = setInterval(async () => {
      if (!sessionId) return;

      // Try to load artifacts in priority order (newest first)
      const artifactOrder = ["canon", "blockout", "dream_preview"];
      for (const kind of artifactOrder) {
        const url = `/api/session/${sessionId}/${kind}`;
        try {
          const resp = await fetch(url, { method: "HEAD" });
          if (resp.ok && !loadedArtifacts.has(`${kind}:`)) {
            showArtifact(kind);
            return; // Show the newest available
          }
        } catch (_) { /* ignore */ }
      }
    }, 5000);
  }

  function stopArtifactPolling() {
    if (artifactPollInterval) {
      clearInterval(artifactPollInterval);
      artifactPollInterval = null;
    }
  }

  // ─── Pipeline Event Handling ─────────────────────────────────────────────

  function approvalFor(event) {
    const map = {
      canon_approval: "canon",
      blockout_approval: "blockout",
      mesh_approval: "mesh",
      final_world_qa: "world"
    };
    return map[event.current_stage] ? {stage: map[event.current_stage], objectId: event.object_id || ""} : null;
  }

  function handleProgress(event) {
    const state = event.state || "RUNNING";
    const stage = event.current_stage || "";

    // Map internal states to user-friendly display
    const displayState = {
      "completed": "✓ DONE",
      "running": "RUNNING",
      "awaiting_approval": "APPROVE →",
      "waiting_approval": "APPROVE →",
      "awaiting_external": "GENERATING…",
      "blocked": "BLOCKED",
      "error": "ERROR",
    }[state] || state.toUpperCase();

    status.textContent = displayState;
    stageTitle.textContent = (stage || "pipeline").replaceAll("_", " ");

    const total = Number(event.objects_total || 1);
    const complete = Number(event.objects_complete || 0);
    progressFill.style.width = `${Math.min(100, Math.round(100 * complete / total))}%`;

    const elapsed = event.elapsed_seconds?.toFixed?.(1) || "0";
    details.textContent = `Plan r${event.plan_revision || 0} · ${event.finality || "provisional"} · ${elapsed}s`;

    // ─── Show artifacts as stages complete ───
    // Show loading animation when GPU stages start
    if (stage === "dream_preview" && state === "running") {
      showLoading("Generating dream preview via FLUX…");
    }
    if (stage === "canon_generation" && state === "running") {
      showLoading("Generating photorealistic canon via FLUX…");
    }
    if (stage === "segment" && state === "running") {
      showLoading("Segmenting objects with SAM 3.1…");
    }
    if (stage === "depth_estimation" && state === "running") {
      showLoading("Estimating depth with DA3…");
    }
    if (stage === "spatial_reconstruction" && state === "running") {
      showLoading("Building spatial reconstruction…");
    }
    if (stage === "mesh_generation" && state === "running") {
      showLoading(`Generating 3D mesh${event.object_id ? " for object " + event.object_id.slice(0, 8) : ""}…`);
    }

    // Dream preview: show when dream_preview stage completes
    if (stage === "dream_preview" && state === "completed") {
      showArtifact("dream_preview");
    }
    // Canon: show when canon_generation completes OR canon_approval starts
    if ((stage === "canon_generation" && state === "completed") ||
        (stage === "canon_approval")) {
      if (!loadedArtifacts.has("canon:")) showArtifact("canon");
    }
    // Blockout (spatial reconstruction): show when spatial_reconstruction completes OR blockout_approval starts
    if ((stage === "spatial_reconstruction" && state === "completed") ||
        (stage === "blockout_approval")) {
      if (!loadedArtifacts.has("blockout:")) showArtifact("blockout");
    }
    // Mesh: show when mesh_generation completes for an object
    if (stage === "mesh_generation" && state === "completed" && event.object_id) {
      showArtifact("mesh", event.object_id);
    }

    // ─── Approval gate detection ───
    currentApproval = approvalFor(event);
    const needsApproval = currentApproval && (state === "waiting_approval" || state === "awaiting_approval");
    approval.style.display = needsApproval ? "inline-block" : "none";

    // When an approval gate shows, display the relevant artifact
    if (needsApproval) {
      if (stage === "canon_approval") showArtifact("canon");
      else if (stage === "blockout_approval") showArtifact("blockout");
      else if (stage === "mesh_approval") showArtifact("canon");
      else if (stage === "final_world_qa") showArtifact("canon");
    }

    // Track last stage for artifact polling
    if (stage !== lastStage) {
      lastStage = stage;
      // Start polling once pipeline is running
      if (!artifactPollInterval && stage) startArtifactPolling();
    }
  }

  function connectEvents(url) {
    events?.close();
    events = new EventSource(url);
    events.addEventListener("pipeline.progress", (message) => {
      try { handleProgress(JSON.parse(message.data)); } catch (error) { console.error(error); }
    });
    events.addEventListener("pipeline.terminal", (message) => {
      const terminal = JSON.parse(message.data);
      status.textContent = terminal.state === "completed" ? "✓ COMPLETED" : terminal.state.toUpperCase();
      stopArtifactPolling();

      if (terminal.state === "completed" && sessionId) {
        // Show final canon image + world link
        artifact.replaceChildren();
        const canonUrl = `/api/session/${sessionId}/canon?t=${Date.now()}`;
        const img = showImage(canonUrl, "Final scene");
        artifact.appendChild(img);

        const worldLink = document.createElement("a");
        worldLink.href = `/api/session/${sessionId}/world`;
        worldLink.target = "_blank";
        worldLink.textContent = "🌐 Walk into this world";
        worldLink.style.cssText = "display:inline-block;margin-top:12px;padding:10px 18px;background:#2a6;color:#fff;border-radius:6px;text-decoration:none;font-weight:bold;font-size:16px;";
        artifact.appendChild(worldLink);
      }
      events.close();
    });
    events.onerror = () => {
      status.textContent = "RECONNECTING";
      // Try to reconnect after 3s
      setTimeout(() => {
        if (sessionId) connectEvents(`/api/session/${sessionId}/events`);
      }, 3000);
    };
  }

  // ─── Session Lifecycle ───────────────────────────────────────────────────

  async function start() {
    const params = new URLSearchParams(location.search);
    const existingSession = params.get("session");

    if (existingSession) {
      sessionId = existingSession;
      sessionLabel.textContent = sessionId.slice(0, 8);
      status.textContent = "RESUMING";
      messages.replaceChildren();
      appendMessage("assistant", "Reconnecting to session " + sessionId.slice(0, 8) + "…");
      connectEvents(`/api/session/${sessionId}/events`);
      startArtifactPolling();

      try {
        const statusResp = await fetch(`/api/session/${sessionId}/status`);
        if (statusResp.ok) {
          const statusData = await statusResp.json();
          if (statusData.state === "error") {
            status.textContent = "ERROR";
            const reason = statusData.error?.reason_code || "unknown";
            appendMessage("assistant", "This session was interrupted: " + reason);
            events?.close();
            stopArtifactPolling();
            input.disabled = true;
            send.disabled = true;
            input.placeholder = "Session ended — start a new one";
            return;
          }
        }
      } catch (_) { /* non-fatal */ }

      input.focus();
      return;
    }

    try {
      const data = await jsonRequest("/api/session/unified/start", {method: "POST", body: "{}"});
      sessionId = data.session_id;
      const url = new URL(location.href);
      url.searchParams.set("session", sessionId);
      history.replaceState(null, "", url.toString());
      sessionLabel.textContent = sessionId.slice(0, 8);
      status.textContent = "CONVERSATION";
      messages.replaceChildren();
      appendMessage("assistant", data.opening_message);
      connectEvents(data.events_url);
      input.focus();
    } catch (error) {
      status.textContent = "ERROR";
      appendMessage("assistant", error.message);
    }
  }

  let pipelineStarted = false;

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pipelineStarted) return;
    const message = input.value.trim();
    if (!message || !sessionId) return;
    appendMessage("user", message);
    input.value = "";
    send.disabled = true;
    try {
      const data = await jsonRequest(`/api/session/${sessionId}/message`, {
        method: "POST", body: JSON.stringify({message})
      });
      if (data.error) {
        appendMessage("assistant", data.error);
      } else {
        appendMessage("assistant", data.message);
      }
      if (data.steering_stable) {
        details.textContent = "Brief ready — pipeline starting…";
        pipelineStarted = true;
        input.disabled = true;
        send.disabled = true;
        input.placeholder = "Pipeline running — use Approve button →";
        startArtifactPolling();
      }
    } catch (error) {
      if (error.message.includes("Pipeline is already")) {
        pipelineStarted = true;
        input.disabled = true;
        send.disabled = true;
        input.placeholder = "Pipeline running — use Approve button →";
        startArtifactPolling();
      }
      appendMessage("assistant", error.message);
    } finally {
      if (!pipelineStarted) {
        send.disabled = false;
        input.focus();
      }
    }
  });

  approval.addEventListener("click", async () => {
    if (!currentApproval) return;
    approval.disabled = true;
    try {
      await jsonRequest(`/api/session/${sessionId}/approve/${currentApproval.stage}`, {
        method: "POST",
        body: JSON.stringify({approved: true, object_id: currentApproval.objectId})
      });
      approval.style.display = "none";
      status.textContent = "RUNNING";
    } catch (error) {
      details.textContent = error.message;
    } finally {
      approval.disabled = false;
    }
  });

  window.addEventListener("beforeunload", () => { events?.close(); stopArtifactPolling(); });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  start();
})();
