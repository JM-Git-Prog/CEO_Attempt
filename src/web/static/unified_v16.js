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
    status.textContent = event.state || "RUNNING";
    stageTitle.textContent = (event.current_stage || "pipeline").replaceAll("_", " ");
    const total = Number(event.objects_total || 1);
    const complete = Number(event.objects_complete || 0);
    progressFill.style.width = `${Math.min(100, Math.round(100 * complete / total))}%`;
    details.textContent = `Plan r${event.plan_revision || 0} · ${event.finality || "provisional"} · ${event.elapsed_seconds?.toFixed?.(1) || 0}s`;
    if (event.current_stage === "dream_preview" && event.state === "completed") showArtifact("dream_preview");
    if (event.current_stage === "blockout" && event.state === "completed") showArtifact("blockout");
    if (event.current_stage === "canon_honesty" && event.state === "completed") showArtifact("canon");
    if (event.current_stage === "mesh_generation" && event.state === "completed") showArtifact("mesh", event.object_id);
    currentApproval = approvalFor(event);
    approval.style.display = currentApproval && event.state === "waiting_approval" ? "inline-block" : "none";
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
      events.close();
    });
    events.onerror = () => { status.textContent = "RECONNECTING"; };
  }

  async function start() {
    try {
      const data = await jsonRequest("/api/session/unified/start", {method: "POST", body: "{}"});
      sessionId = data.session_id;
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

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || !sessionId) return;
    appendMessage("user", message);
    input.value = "";
    send.disabled = true;
    try {
      const data = await jsonRequest(`/api/session/${sessionId}/message`, {
        method: "POST", body: JSON.stringify({message})
      });
      appendMessage("assistant", data.message);
      if (data.steering_stable) details.textContent = "Brief ready. The durable pipeline can advance from this approved conversation.";
    } catch (error) {
      appendMessage("assistant", error.message);
    } finally {
      send.disabled = false;
      input.focus();
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
  start();
})();
