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

  function showArtifact(kind, objectId = "") {
    const routes = {
      dream_preview: `/api/session/${sessionId}/dream_preview`,
      blockout: `/api/session/${sessionId}/blockout`,
      canon: `/api/session/${sessionId}/canon`,
      mesh: `/api/session/${sessionId}/mesh/${encodeURIComponent(objectId)}`
    };
    if (!routes[kind]) return;
    artifact.replaceChildren();
    if (kind === "mesh") {
      const note = document.createElement("p");
      const link = document.createElement("a");
      link.href = routes[kind];
      link.textContent = `Open mesh ${objectId}`;
      note.appendChild(link);
      artifact.appendChild(note);
      return;
    }
    const image = document.createElement("img");
    image.src = `${routes[kind]}?t=${Date.now()}`;
    image.alt = `${kind.replace("_", " ")} artifact`;
    artifact.appendChild(image);
  }

  function approvalFor(event) {
    const map = {
      blockout_approval: "blockout",
      canon_approval: "canon",
      object_canon_approval: "object_canon",
      mesh_approval: "mesh",
      final_world_qa: "world"
    };
    return map[event.current_stage] ? {stage: map[event.current_stage], objectId: event.object_id || ""} : null;
  }

  function handleProgress(event) {
    const state = event.state || "RUNNING";
    // Map internal states to user-friendly display
    const displayState = {
      "completed": "COMPLETED",
      "running": "RUNNING",
      "awaiting_approval": "APPROVE →",
      "waiting_approval": "APPROVE →",
      "awaiting_external": "GENERATING…",
      "blocked": "BLOCKED",
      "error": "ERROR",
    }[state] || state.toUpperCase();
    status.textContent = displayState;
    stageTitle.textContent = (event.current_stage || "pipeline").replaceAll("_", " ");
    const total = Number(event.objects_total || 1);
    const complete = Number(event.objects_complete || 0);
    progressFill.style.width = `${Math.min(100, Math.round(100 * complete / total))}%`;
    details.textContent = `Plan r${event.plan_revision || 0} · ${event.finality || "provisional"} · ${event.elapsed_seconds?.toFixed?.(1) || 0}s`;
    if (event.current_stage === "dream_preview" && state === "completed") showArtifact("dream_preview");
    if (event.current_stage === "blockout" && state === "completed") showArtifact("blockout");
    if (event.current_stage === "canon_honesty" && state === "completed") showArtifact("canon");
    if (event.current_stage === "mesh_generation" && state === "completed") showArtifact("mesh", event.object_id);
    currentApproval = approvalFor(event);
    // Show approve button for both "awaiting_approval" and "waiting_approval" states
    const needsApproval = currentApproval && (state === "waiting_approval" || state === "awaiting_approval");
    approval.style.display = needsApproval ? "inline-block" : "none";
  }

  function connectEvents(url) {
    events?.close();
    events = new EventSource(url);
    events.addEventListener("pipeline.progress", (message) => {
      try { handleProgress(JSON.parse(message.data)); } catch (error) { console.error(error); }
    });
    events.addEventListener("pipeline.terminal", (message) => {
      const terminal = JSON.parse(message.data);
      status.textContent = terminal.state.toUpperCase();
      if (terminal.state === "completed" && sessionId) {
        const worldLink = document.createElement("a");
        worldLink.href = `/api/session/${sessionId}/world`;
        worldLink.target = "_blank";
        worldLink.textContent = "🌐 View World";
        worldLink.style.cssText = "display:inline-block;margin-top:8px;padding:6px 12px;background:#2a6;color:#fff;border-radius:4px;text-decoration:none;font-weight:bold;";
        artifact.appendChild(worldLink);
      }
      events.close();
    });
    events.onerror = () => { status.textContent = "RECONNECTING"; };
  }

  async function start() {
    // Check URL for existing session: ?v=16&session=<id>
    const params = new URLSearchParams(location.search);
    const existingSession = params.get("session");

    if (existingSession) {
      // Resume existing session
      sessionId = existingSession;
      sessionLabel.textContent = sessionId.slice(0, 8);
      status.textContent = "RESUMING";
      messages.replaceChildren();
      appendMessage("assistant", "Reconnecting to session " + sessionId.slice(0, 8) + "…");
      connectEvents(`/api/session/${sessionId}/events`);

      // V16 dual-state fix: quick health check to catch dead sessions immediately
      try {
        const statusResp = await fetch(`/api/session/${sessionId}/status`);
        if (statusResp.ok) {
          const statusData = await statusResp.json();
          if (statusData.state === "error") {
            status.textContent = "ERROR";
            const reason = statusData.error?.reason_code || "unknown";
            appendMessage("assistant", "This session was interrupted: " + reason);
            events?.close();
            input.disabled = true;
            send.disabled = true;
            input.placeholder = "Session ended — start a new one";
            return;
          }
        }
      } catch (_) { /* non-fatal — SSE will catch up */ }

      input.focus();
      return;
    }

    try {
      const data = await jsonRequest("/api/session/unified/start", {method: "POST", body: "{}"});
      sessionId = data.session_id;
      // Update URL to include session ID (bookmarkable, no page reload)
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
    if (pipelineStarted) return; // Conversation phase is over
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
      }
    } catch (error) {
      // If it's a 409 (pipeline already started), disable chat
      if (error.message.includes("Pipeline is already")) {
        pipelineStarted = true;
        input.disabled = true;
        send.disabled = true;
        input.placeholder = "Pipeline running — use Approve button →";
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

  window.addEventListener("beforeunload", () => events?.close());

  // Enter submits (Shift+Enter for newline)
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  start();
})();
