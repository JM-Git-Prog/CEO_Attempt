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
 * plus two additive routes from Slice 1 (2026-09-02):
 *   GET  /api/session/{id}/conversation      (saved turns + real state, for reloads)
 *   POST /api/session/{id}/retry             ("Try again" after a failed stage)
 *
 * Slice 1 (2026-09-02, from V17-FIRST-90-SECONDS + V17-STEERING-DESIGN):
 *   - the stage strip speaks in words, never codes (CONNECTING/RESUMING/ERROR are gone)
 *   - a failure is a sentence in the chat naming the engine, with a Try again button
 *   - you can type before the AI is ready; the message goes the moment it is
 *   - a reload restores the conversation and the right lane instead of RESUMING forever
 *   - the picture to approve appears big on the RIGHT (John's call), with Approve under it
 *   - after every reply, the exact prompt it would render is shown under the reply
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
  const worldNote = $("worldNote");
  const picture = $("worldPicture");
  const pictureImg = $("worldPictureImg");
  const pictureCaption = $("worldPictureCaption");
  const pictureApprove = $("worldPictureApprove");
  const pictureReject = $("worldPictureReject");
  const pictureFix = $("worldPictureFix");
  const pictureReason = $("worldPictureReason");

  let sessionId = "";
  let events = null;
  let currentApproval = null;   // {stage, object_id} when an approval gate is open
  let pipelineStarted = false;
  let lastStage = "";
  let pendingMessage = null;    // typed before the session existed; sent when it does
  let lastReference = null;     // id of a pasted/dropped picture waiting for its sentence
  let lastReferenceAt = 0;      // when it was added; it rides on the next message within 10 min
  let worldState = null;        // last { place, version, outdoors, garage, standing, at } the world iframe reported
  const shownArtifacts = new Set();

  const APP_VERSION = String(window.APP_VERSION || 16);
  const WORLD_ORIGIN = "http://localhost:5173"; // world_v17.js's origin literal for its iframe — kept in sync there

  // ─── Words, not codes ───────────────────────────────────────────────────

  const STAGE_WORDS = {
    conversation: "the conversation",
    brief: "the brief",
    art_bible: "the art direction",
    dream_preview: "the first picture",
    canon_generation: "the final picture",
    canon_approval: "the picture",
    segment: "finding the objects in the picture",
    depth_estimation: "measuring depth",
    spatial_reconstruction: "the floor plan",
    blockout_approval: "the floor plan",
    object_isolation: "cutting out each object",
    object_canon_approval: "the object cut-outs",
    mesh_generation: "meshing the objects",
    mesh_approval: "a mesh",
    material_pass_1: "materials",
    parametric_room: "the room shell",
    physics_classification: "physics",
    physics_settle: "settling the objects",
    world_contract: "the world contract",
    compile: "compiling the world",
    automated_final_validation: "final checks",
    final_world_qa: "the finished world",
    mode_toggle: "the mode switch",
  };
  // Which box to look at when a stage fails. Ports from the machine table in the brief.
  const ENGINE = {
    dream_preview: "the image engine (ComfyUI on 8188)",
    canon_generation: "the image engine (ComfyUI on 8188)",
    segment: "the vision model (Ollama on 11434)",
    depth_estimation: "the depth model (ComfyUI on 8188)",
    object_isolation: "the cut-out model (ComfyUI on 8188)",
    mesh_generation: "the mesh engine (ComfyUI on 8188)",
  };
  const stageWord = (stage) => STAGE_WORDS[stage] || (stage || "the build").replaceAll("_", " ");
  const capitalize = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
  function setStrip(word, detail) {
    status.textContent = word;
    stageTitle.textContent = detail || "";
  }
  // The rail's model chip (John 2026-09-03: "auto, but let me override with a
  // word"). Shows who answered; a forced sentence is marked so he can tell.
  const railModel = $("railModel");
  // clicking the chip asks "models" — the lane and the override word come back as a reply
  railModel?.addEventListener("click", () => { if (sessionId && !send.disabled) sendMessage("models"); });
  function setModel(name, sentence) {
    if (!railModel || !name) return;
    const forced = /^\s*use\s+\S+\s*:/i.test(sentence || "");
    railModel.textContent = name.replace(/:latest$/, "") + (forced ? " (forced)" : "");
    railModel.title = forced ? "you forced this model for that sentence" : "picked by the house rule: cloud for talking, the 4090 for pictures";
  }
  function setWorldNote(text) {
    if (!worldNote) return;
    worldNote.textContent = text || "";
    worldNote.hidden = !text;
  }

  // ─── Helpers ───────────────────────────────────────────────────────────

  function appendMessage(role, text) {
    const item = document.createElement("div");
    item.className = `message ${role}`;
    item.textContent = text;
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
    return item;
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

  // ─── The world reports where it is (postMessage from the :5173 iframe) ──
  // world_v17.js posts { source:"ceo-world", type:"world.state", state } on
  // mount and whenever place/outdoors/garage change. Accept only that origin
  // and that exact shape — an unchecked listener takes messages from any page.
  window.addEventListener("message", (event) => {
    if (event.origin !== WORLD_ORIGIN) return;
    if (!event.data || event.data.source !== "ceo-world" || event.data.type !== "world.state") return;
    worldState = event.data.state;
  });

  // Ask once on load; if nothing has arrived yet, ask again a couple of times
  // a second or two apart, then stop — never poll forever.
  // Ask, then wait a moment for the answer — used before the greeting is written so
  // the AI knows where John is standing instead of having to ask him. Resolves the
  // instant the world reports, or when the budget runs out; never blocks longer.
  function waitForWorld(budgetMs) {
    if (worldState) return Promise.resolve(worldState);
    askWorld(0);
    return new Promise((resolve) => {
      const started = Date.now();
      const tick = setInterval(() => {
        if (worldState || Date.now() - started >= budgetMs) {
          clearInterval(tick);
          resolve(worldState);
        } else {
          askWorld(0);   // the iframe may only just have appeared
        }
      }, 250);
    });
  }

  function askWorld(retriesLeft = 2) {
    const frame = document.querySelector("section.right iframe");
    if (frame) frame.contentWindow.postMessage({ source: "ceo-v17", type: "world.state?" }, WORLD_ORIGIN);
    if (worldState === null && retriesLeft > 0) setTimeout(() => askWorld(retriesLeft - 1), 1500);
  }

  // ─── The proposal under each reply: what it would render, and its ideas ──

  // John, 2026-09-03 ("is this how the chat should be responding?" — no): the 900-character
  // render prompt and the game/tool pitches were the busiest lines in the pane. The prompt is
  // shown as one short line (the full text is a click away on the title); the pitches stay in
  // the brief and are not read out.
  function showProposal(data) {
    if (!data) return;
    if (data.render_prompt) {
      const full = String(data.render_prompt);
      const item = appendMessage("prompt", `It will render: “${full.length > 160 ? full.slice(0, 157).trimEnd() + "…" : full}”`);
      item.title = full;
    }
  }

  // ─── Pictures: small thumbnails in the strip, the current one big on the right ──

  function artifactUrl(kind) {
    return {
      dream_preview: `/api/session/${sessionId}/dream_preview`,
      blockout: `/api/session/${sessionId}/blockout`,
      canon: `/api/session/${sessionId}/canon`,
    }[kind];
  }

  function showArtifactThumb(kind) {
    if (!sessionId || shownArtifacts.has(kind)) return;
    const url = artifactUrl(kind);
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
    img.addEventListener("click", () => showPicture(kind, `${capitalize(img.alt)} — the yellow chip above the box approves it.`, false));
    artifactStrip.appendChild(img);
    shownArtifacts.add(kind);
  }

  function showPicture(kind, caption, retry = true) {
    if (!picture || !sessionId) return;
    const url = artifactUrl(kind);
    if (!url) return;
    pictureImg.alt = kind.replace("_", " ");
    pictureImg.src = `${url}?t=${Date.now()}`;
    pictureImg.onerror = () => {
      const tries = (Number(pictureImg.dataset.tries) || 0) + 1;
      pictureImg.dataset.tries = String(tries);
      if (retry && tries <= 5) setTimeout(() => { pictureImg.src = `${url}?retry=${Date.now()}`; }, 2500);
    };
    pictureCaption.textContent = caption || "";
    picture.hidden = false;
    setWorldNote("");
  }

  function hidePicture() {
    if (picture) picture.hidden = true;
    if (pictureFix) pictureFix.hidden = true;
  }

  // ─── "Something's wrong" → the reason is rendered next (Slice 2a) ────────

  pictureReject?.addEventListener("click", () => {
    pictureFix.hidden = false;
    pictureReason.focus();
  });

  pictureFix?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const reason = pictureReason.value.trim();
    if (!reason) { pictureReason.focus(); return; }
    const submit = pictureFix.querySelector("button");
    submit.disabled = true;
    try {
      await jsonRequest(`/api/session/${sessionId}/revise`, {
        method: "POST",
        body: JSON.stringify({ reason, stage: "canon_generation" }),
      });
      appendMessage("user", `What's wrong with the picture: ${reason}`);
      appendMessage("system", "Rendering it again with that requirement (~10 s).");
      pictureReason.value = "";
      pictureFix.hidden = true;
      pictureReject.hidden = true;
      pictureApprove.hidden = true;
      approval.style.display = "none";
      pictureCaption.textContent = "Re-rendering with your correction…";
      setStrip("Building", "the picture, with your correction");
      connectEvents(`/api/session/${sessionId}/events`);
    } catch (error) {
      appendMessage("system", `Couldn't re-render: ${error.message}`);
    } finally {
      submit.disabled = false;
    }
  });

  // ─── The garage wall (the station kit, 2026-09-03) ─────────────────────
  // When John asked "which of these rooms do you like?", the picture gate is not
  // a picture with an Approve chip — it is three pictures on the garage wall.
  // This watcher polls the wall while the build waits, tells him to walk over,
  // and reports what his click did. "None of these" (right-click) renders new
  // ones straight away AND asks what should change (John: "#2 while in the
  // background working on #1") — his next sentence goes to the re-render.
  let wallTimer = null;
  let wallShown = "";
  let askFix = false;
  const WALL_WORDS = { c1: "the first", c2: "the second", c3: "the third", c4: "the fourth" };
  function stopWallWatch() { if (wallTimer) { clearInterval(wallTimer); wallTimer = null; } }
  function wallLine(text, walk) {
    const item = appendMessage("system gate", text);
    if (walk && world()?.goToGarage) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "walk";
      btn.textContent = "Walk over →";
      btn.addEventListener("click", () => world().goToGarage());
      item.append(" ", btn);
    }
    return item;
  }
  async function checkWall() {
    if (!sessionId) return;
    let data;
    try { data = await fetch(`/api/session/${sessionId}/wall`).then((r) => (r.ok ? r.json() : null)); } catch (_) { return; }
    if (!data) return;
    if (data.wall && !data.answer) {
      if (queuedFix && wallShown !== data.wall.id) {
        // the plain batch landed while a fix was waiting: render the fix on top of it now
        wallShown = data.wall.id;
        const fix = queuedFix;
        queuedFix = "";
        void sendFix(fix);
        return;
      }
      if (wallShown !== data.wall.id) {
        wallShown = data.wall.id;
        const n = (data.wall.tags || []).length;
        wallLine(`${n} picture${n === 1 ? "" : "s"} of your room ${n === 1 ? "is" : "are"} on the garage wall — choose the one you like there.`, true);
        hidePicture();
        approval.style.display = "none";
        if (pictureApprove) pictureApprove.hidden = true;
        if (pictureReject) pictureReject.hidden = true;
        setStrip("Waiting for you", "choose a picture in the garage");
      }
      return;
    }
    if (data.applied && data.action === "choose") {
      stopWallWatch();
      askFix = false;
      queuedFix = "";
      appendMessage("system", `You chose ${WALL_WORDS[data.answer?.tag] || data.answer?.tag} — building the room from it.`);
      setStrip("Building", "from the picture you chose");
      connectEvents(`/api/session/${sessionId}/events`);
    } else if (data.applied && data.action === "more") {
      stopWallWatch();
      askFix = true;
      appendMessage("system", "None of those — new ones are rendering now (~30 s). Meanwhile: what should change? Say it in one line and I'll render that too.");
      setStrip("Building", "new pictures for the wall");
      connectEvents(`/api/session/${sessionId}/events`);
    } else if (data.answer && data.applied === false) {
      // answered, but the build is mid-run — it applies on the next poll
    }
  }
  function startWallWatch() {
    if (wallTimer) return;
    void checkWall();
    wallTimer = setInterval(checkWall, 4000);
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
    lastStage = stage;
    const waiting = state === "awaiting_approval" || state === "waiting_approval";

    if (waiting) setStrip("Waiting for you", `approve ${stageWord(stage)}`);
    else if (state === "completed") setStrip("Building", `${stageWord(stage)} — done`);
    else if (state === "awaiting_external") setStrip("Building", `${stageWord(stage)} — on the GPU`);
    else if (state === "failed" || state === "error") setStrip("Failed", stageWord(stage));
    else if (state === "blocked") setStrip("Stopped", stageWord(stage));
    else setStrip("Building", stageWord(stage));

    const total = Number(event.objects_total || 1);
    const complete = Number(event.objects_complete || 0);
    progressFill.style.width = `${Math.min(100, Math.round((100 * complete) / total))}%`;

    const elapsed = event.elapsed_seconds?.toFixed?.(1) || "0";
    details.textContent = `Plan revision ${event.plan_revision || 0} · ${event.finality || "provisional"} · ${elapsed}s`;

    // Pictures: thumbnails in the strip, the current one big on the right.
    if (stage === "dream_preview" && state === "completed") {
      showArtifactThumb("dream_preview");
      showPicture("dream_preview", "First picture. The final one is rendering now (~10 s).");
    }
    if ((stage === "canon_generation" && state === "completed") || stage === "canon_approval") {
      if (waiting) startWallWatch(); // a wall up → the garage owns this gate; no wall → the picture below
      showArtifactThumb("canon");
      showPicture("canon", waiting
        ? "Is this the room? Approve it, or say what's wrong in the chat."
        : "The picture the room will be built from.");
    }
    if ((stage === "spatial_reconstruction" && state === "completed") || stage === "blockout_approval") {
      showArtifactThumb("blockout");
      hidePicture();   // the 3D floor plan draws on the canvas from here on
      setWorldNote(waiting ? "Waiting for you — approve the floor plan (the yellow chip above the box)."
        : "Floor plan drawn. Each object fills in as its mesh lands (~1 min each).");
    }
    if (stage === "mesh_generation") setWorldNote(`Meshing ${complete} of ${total}… each takes about a minute.`);
    if (stage === "compile" && state === "completed") setWorldNote("Assembling the world…");

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
    const needsApproval = Boolean(currentApproval && waiting);
    approval.style.display = needsApproval ? "inline-block" : "none";
    if (needsApproval) approval.textContent = `Approve ${stageWord(stage)}`;
    const pictureGate = Boolean(needsApproval && currentApproval.stage === "canon");
    if (pictureApprove) pictureApprove.hidden = !pictureGate;
    if (pictureReject) pictureReject.hidden = !pictureGate;
    if (pictureFix && !pictureGate) pictureFix.hidden = true;
  }

  // ─── Failure: a sentence, the engine to look at, and Try again ─────────

  async function showFailure(reason) {
    let why = String(reason || "").trim();
    if (!why && sessionId) {
      try {
        const h = await fetch(`/api/session/${sessionId}/health`).then((r) => (r.ok ? r.json() : null));
        why = String((h && h.error) || "").trim();
      } catch (_) { /* the sentence below still names the stage */ }
    }
    if (why.length > 220) why = `${why.slice(0, 217)}…`;
    const stage = lastStage;
    setStrip("Failed", stageWord(stage));
    setWorldNote("Stopped — see the chat.");
    hidePicture();

    const item = document.createElement("div");
    item.className = "message system failure";
    const text = document.createElement("div");
    text.textContent = `${capitalize(stageWord(stage))} failed — ${why || "no reason was reported"}.`
      + (ENGINE[stage] ? ` Check ${ENGINE[stage]}.` : "");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Try again";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await jsonRequest(`/api/session/${sessionId}/retry`, { method: "POST", body: "{}" });
        item.remove();
        appendMessage("system", "Trying again from where it stopped…");
        setStrip("Building", stageWord(stage));
        setWorldNote(`Retrying ${stageWord(stage)}…`);
        pipelineStarted = true;
        connectEvents(`/api/session/${sessionId}/events`);
      } catch (error) {
        btn.disabled = false;
        appendMessage("system", `Couldn't retry: ${error.message}`);
      }
    });
    item.append(text, btn);
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
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
      events?.close();
      if (state === "completed" || state === "ready") {
        setStrip("Done", "your room is ready");
        setWorldNote("Done — click Walk in.");
        hidePicture();
        if (sessionId) {
          appendMessage("system", "World complete — walk in on the right (Walk in / WASD).");
          world()?.refreshScene(true);
        }
        return;
      }
      showFailure(terminal.reason);
    });
    events.onerror = () => {
      // The stream dropped (server restart, sleep). Say so in words and retry quietly.
      setStrip("Reconnecting", "the Living Room stopped answering — retrying");
      setTimeout(() => { if (sessionId) connectEvents(`/api/session/${sessionId}/events`); }, 3000);
    };
  }

  // ─── Approval action ────────────────────────────────────────────────────

  approval.addEventListener("click", async () => {
    if (!sessionId || !currentApproval) return;
    approval.disabled = true;
    if (pictureApprove) pictureApprove.disabled = true;
    try {
      const body = { approved: true };
      // Blockout approval maps selected DETECTION ids to required Plan
      // placements. The backend rejects (409) any detection that lacks a
      // required plan_binding_id, so send ONLY detections flagged required.
      if (currentApproval.stage === "blockout") {
        const picker = await fetch(`/api/session/${sessionId}/object_picker`).then((r) => (r.ok ? r.json() : null));
        const objects = picker && Array.isArray(picker.objects) ? picker.objects : [];
        const requiredIds = objects
          .filter((o) => o.required === true && (o.object_id || o.id))
          .map((o) => o.object_id || o.id);
        if (requiredIds.length === 0) {
          // No detection binds to a required Plan object — the canon did not
          // contain the Brief's required objects (canon/Brief mismatch). Fail
          // loudly instead of looping a doomed approval.
          appendMessage(
            "system",
            "Cannot approve the floor plan: the picture has none of the objects the brief asked for. " +
              "This is a picture/brief mismatch — the picture needs to be regenerated.",
          );
          approval.disabled = false;
          if (pictureApprove) pictureApprove.disabled = false;
          return;
        }
        body.selected_object_ids = requiredIds;
      }
      if (currentApproval.object_id) body.object_id = currentApproval.object_id;
      await jsonRequest(`/api/session/${sessionId}/approve/${currentApproval.stage}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      appendMessage("system", `Approved ${stageWord(lastStage)}. Continuing…`);
      setStrip("Building", `after ${stageWord(lastStage)}`);
      approval.style.display = "none";
      if (pictureApprove) pictureApprove.hidden = true;
      if (pictureReject) pictureReject.hidden = true;
      if (pictureFix) pictureFix.hidden = true;
      if (currentApproval.stage === "canon") {
        pictureCaption.textContent = "Approved. Finding the objects and drawing the floor plan (~30 s)…";
      }
      currentApproval = null;
    } catch (error) {
      appendMessage("system", `Approval failed: ${error.message}`);
    } finally {
      approval.disabled = false;
      if (pictureApprove) pictureApprove.disabled = false;
    }
  });
  pictureApprove?.addEventListener("click", () => approval.click());

  // ─── Sending ────────────────────────────────────────────────────────────

  // After "none of these" on the wall, the next sentence is the fix — it goes to
  // the re-render, not the chat. If the same-words batch is still rendering the
  // fix waits for it and then renders on top (John: both, #2 asked, #1 ready).
  let queuedFix = "";
  async function sendFix(reason) {
    try {
      await jsonRequest(`/api/session/${sessionId}/revise`, { method: "POST", body: JSON.stringify({ reason, stage: "canon_generation" }) });
      askFix = false;
      queuedFix = "";
      appendMessage("system", `Rendering new pictures with that: “${reason}” — they'll go up on the wall (~30 s).`);
      setStrip("Building", "the pictures, with your fix");
      connectEvents(`/api/session/${sessionId}/events`);
      return true;
    } catch (error) {
      if (/still running/i.test(error.message)) {
        queuedFix = reason;
        appendMessage("system", "Got it — the plain re-render is still going; your fix renders right after it.");
        return true;
      }
      appendMessage("system", `Couldn't re-render: ${error.message}`);
      return false;
    }
  }

  async function sendMessage(message, pictureSummary) {
    if (askFix && pipelineStarted) {
      send.disabled = true;
      try { await sendFix(message); } finally { send.disabled = false; input.focus(); }
      return;
    }
    send.disabled = true;
    if (!pipelineStarted) setStrip("Thinking", "usually 3–10 s");
    try {
      // Once the pipeline is building, further chat is game-design conversation
      // (parallel to the GPU work), matching the V16 adapter's two-lane design.
      const endpoint = pipelineStarted
        ? `/api/session/${sessionId}/game_message`
        : `/api/session/${sessionId}/message`;
      const body = { message };
      const reference = takeReference();
      if (reference !== null) body.reference = reference;
      // What the router's vision pass actually saw in the photo. The room brain has
      // no eyes of its own; without this line it answers "this one" from its own
      // defaults (2026-09-03: a brick mansion became a teal living room).
      if (pictureSummary) body.picture_summary = pictureSummary;
      // Where John is actually standing in the world right now, so this doesn't
      // propose a reading nook to a man looking at a street.
      const where = worldState && worldState.standing;
      if (where) body.where = where;
      const data = await jsonRequest(endpoint, { method: "POST", body: JSON.stringify(body) });
      if (data.message) appendMessage("assistant", data.message);
      // the rail shows who answered (model_router.py); "models" and a missing
      // "use <model>:" come back as plain answers without a turn
      if (data.model_used) setModel(data.model_used, message);
      if (data.command) return; // "models" / a missing override: answered, no turn taken

      if (!pipelineStarted && data.brief) {
        pipelineStarted = true;
        if (data.render_prompt) appendMessage("prompt", `Rendering: “${data.render_prompt}”`);
        // What the warehouse already holds, and what has to be made (Slice 2b).
        if (data.warehouse_message) {
          appendMessage("system", data.warehouse_message);
          const started = (data.warehouse && data.warehouse.started) || [];
          if (started.length) {
            appendMessage("system",
              `Started the prop factory for ${started.length} of them: ${started.join(", ")}. ` +
              "When one needs your eye it stands in the garage, and the rail says so.");
          }
        }
        appendMessage(
          "system",
          "Brief locked. Building: a first picture (~10 s), then the final picture for you to approve (~10 s), " +
            "then the floor plan and each object (~1 min each). Watch the right.",
        );
        setStrip("Building", "the first picture (~10 s)");
        setWorldNote("Rendering the first picture (~10 s)…");
        world()?.beginBuild();
      } else if (!pipelineStarted) {
        showProposal(data);
        setStrip("Your move", "steer it, or say “build it”");
      }
    } catch (error) {
      appendMessage("system", error.message);
      if (!pipelineStarted) setStrip("Your move", "that didn't go through — try again");
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  // A line starting with @claude is a note about the APP, not the room. It is
  // filed for Claude to read next session (Slice 2a) — same box, no second
  // input, no live agent inside the page.
  async function fileNote(text) {
    const note = text.replace(/^@claude\b[:,\s]*/i, "").trim();
    if (!note) {
      appendMessage("system", "Nothing after @claude — the note was empty.");
      return;
    }
    try {
      await jsonRequest(`/api/session/${sessionId || "none"}/note`, {
        method: "POST",
        body: JSON.stringify({ note: note, text: note, context: `${status.textContent} · ${stageTitle.textContent}` }),
      });
      appendMessage("system", "Filed for Claude — it will be read at the start of the next session. Nothing was sent to the room.");
    } catch (error) {
      appendMessage("system", `Couldn't file that note: ${error.message}`);
    }
  }

  // ─── The router (2026-09-03 fix): one door for every sentence ──────────
  // /api/v17/say decides what a sentence is now — no regex here any more. That silent
  // fallthrough (anything the old regexes missed went straight to the room chat) is the
  // exact bug this replaces: "none of them looked like the picture" (a brick mansion
  // that came back as a teal living room).

  function neighbourhood() {
    return window.LRNeighbourhood || null;
  }

  function receiptLine(r) {
    if (!r) return "";
    const parts = [];
    if (r.got) parts.push(`Got: ${r.got}`);
    if (r.making) parts.push(`Making: ${r.making}`);
    if (r.needs) parts.push(`Needs a new tool: ${r.needs}`);
    return parts.join(" · ");
  }

  async function routeMessage(message) {
    // the reference picture id rides with this sentence; it is only taken (cleared) once
    // we actually know which lane is going to use it, so a rejected/unknown sentence
    // leaves it in place for the next try.
    const reference = window.LRReference ? window.LRReference.peek() : null;
    send.disabled = true;
    try {
      let data;
      try {
        data = await jsonRequest("/api/v17/say", {
          method: "POST",
          body: JSON.stringify({ session: sessionId, message, reference, world: worldState }),
        });
      } catch (error) {
        appendMessage("system", `Couldn't reach the router: ${error.message}. Nothing was sent.`);
        return;
      }

      const receipt = receiptLine(data.receipt);
      if (receipt) appendMessage("system", receipt);
      if (data.picture && data.picture.summary) appendMessage("system", `Looking at your photo: ${data.picture.summary}`);

      const nb = neighbourhood();
      switch (data.kind) {
        case "house":
        case "grounds":
          if (!nb) { appendMessage("system", "The neighbourhood builder isn't loaded — reload the page."); return; }
          if (window.LRReference) window.LRReference.take();
          // gemma4's read of the photo goes to the builder too — showing it to John and
          // then dropping it was the waste found on review (2026-09-03).
          await nb.order(message, reference, data.order_hint);
          return;
        case "room":
        case "question":
        case "check":
        case "gap":
          // carry what the router SAW into the room brain — it has no eyes of its own
          await sendMessage(message, data.picture && data.picture.summary);
          return;
        case "command": {
          if (!nb) { appendMessage("system", "The neighbourhood builder isn't loaded — reload the page."); return; }
          const cmd = data.command || {};
          if (cmd.name === "open") { nb.walkIn("/" + cmd.arg); nb.remember(cmd.arg); }
          else if (cmd.name === "leave") { nb.walkIn("/" + nb.HOME + "?mode=play"); nb.remember(nb.HOME); }
          else if (cmd.name === "models") { await nb.listModels(); }
          else appendMessage("system", `Unknown command "${cmd.name}" — nothing happened.`);
          return;
        }
        case "unknown":
          appendMessage("system", `${data.reason || "Not sure what that means."} Did you mean something inside a room, or something out on the block?`);
          return;
        default:
          appendMessage("system", `The router returned a kind I don't know ("${data.kind}") — nothing was sent.`);
          return;
      }
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    appendMessage("user", message);
    input.value = "";
    if (/^@claude\b/i.test(message)) { await fileNote(message); input.focus(); return; }
    if (!sessionId) {
      // Typed before the session existed (John's call, 2026-09-02): keep it and
      // send it the moment the AI is ready, instead of silently ignoring Enter.
      pendingMessage = message;
      appendMessage("system", "Sending as soon as the AI is ready…");
      return;
    }
    await routeMessage(message);
  });

  // Enter submits; Shift+Enter newlines.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  // ─── A reference picture (2026-09-03): paste or drop it on the box, then say what it's for ──

  const REFERENCE_TTL_MS = 10 * 60 * 1000;

  // The picture id to send with THIS message: one added in the last 10 minutes, used once.
  function takeReference() {
    const fresh = lastReference !== null && Date.now() - lastReferenceAt <= REFERENCE_TTL_MS;
    const n = fresh ? lastReference : null;
    lastReference = null;
    return n;
  }
  // Other page scripts (neighbourhood_v17.js) hand the pending picture to a different lane.
  window.LRReference = { take: takeReference, peek: () => (lastReference !== null && Date.now() - lastReferenceAt < REFERENCE_TTL_MS ? lastReference : null) };

  async function addReference(file) {
    if (!sessionId) { appendMessage("system", "Wait for the AI to be ready, then paste the picture again."); return; }
    if (!/^image\/(png|jpeg)$/.test(file.type)) { appendMessage("system", "PNG or JPEG pictures only."); return; }
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error || new Error("could not read the picture"));
        reader.readAsDataURL(file);
      });
      const data = await jsonRequest(`/api/session/${sessionId}/reference`, {
        method: "POST",
        body: JSON.stringify({ image: dataUrl, name: file.name || "" }),
      });
      const item = appendMessage("user", "");
      const img = document.createElement("img");
      img.className = "ref-thumb";
      img.src = data.url;
      img.alt = `Reference picture #${data.id}`;
      item.append(img, `Reference picture #${data.id} — say what it's for (e.g. 'a house like this')`);
      messages.scrollTop = messages.scrollHeight;
      lastReference = data.id;
      lastReferenceAt = Date.now();
    } catch (error) {
      appendMessage("system", `Couldn't save the picture: ${error.message}`);
    }
    input.focus();
  }

  input.addEventListener("paste", (event) => {
    const item = Array.from(event.clipboardData?.items || []).find((i) => i.type.startsWith("image/"));
    if (!item) return;                // plain text pastes as usual
    event.preventDefault();
    const file = item.getAsFile();
    if (file) addReference(file);
  });
  // dragover must be cancelled or the browser opens the file instead of dropping it
  composer.addEventListener("dragover", (event) => {
    if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault();
  });
  composer.addEventListener("drop", (event) => {
    const file = Array.from(event.dataTransfer?.files || []).find((f) => f.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault();
    addReference(file);
  });

  // ─── Session lifecycle ──────────────────────────────────────────────────

  async function resume(id) {
    sessionId = id;
    sessionLabel.textContent = id.slice(0, 8);
    setStrip("Resuming", "reading the saved conversation");
    let conv = null;
    try {
      conv = await jsonRequest(`/api/session/${id}/conversation`);
    } catch (error) {
      setStrip("Couldn't resume", "that session isn't on the server");
      appendMessage("system", `Couldn't resume session ${id.slice(0, 8)}: ${error.message}. ` +
        "Open V17 without the session in the address bar to start fresh.");
      return;
    }
    // Keep the page's own front-door question (the first, static child); it is not a saved turn.
    messages.replaceChildren(...(messages.firstElementChild ? [messages.firstElementChild] : []));
    for (const t of conv.turns || []) appendMessage(t.role === "user" ? "user" : "assistant", t.content);
    if ((conv.game_turns || []).length) appendMessage("system", "— game design, while the room builds —");
    for (const t of conv.game_turns || []) appendMessage(t.role === "user" ? "user" : "assistant", t.content);
    if (conv.model) setModel(conv.model);

    const state = conv.state || "";
    pipelineStarted = !["", "unknown", "awaiting_description"].includes(state);
    if (!pipelineStarted) {
      showProposal(conv);
      setStrip("Your move", "resumed — still designing");
      setWorldNote("");   // the pane's own centre text already says "Empty on purpose"
    } else if (state === "error") {
      lastStage = conv.pending_stage || lastStage;
      appendMessage("system", conv.restarted
        ? "Resumed — the Living Room was restarted while this was building, so it stopped where it was."
        : "Resumed — the build had stopped.");
      await showFailure(conv.error);
    } else if (state === "completed" || state === "ready") {
      setStrip("Done", "your room is ready");
      setWorldNote("Done — click Walk in.");
    } else if (state === "awaiting_approval") {
      setStrip("Waiting for you", `approve ${stageWord(conv.pending_stage || "")}`);
    } else {
      setStrip("Building", `resumed — ${stageWord(conv.pending_stage || "")}`);
    }
    if (pipelineStarted && conv.pipeline_attached === false && state !== "completed") {
      appendMessage("system", "Note: the Living Room was restarted since this build started, so approvals " +
        "may not go through until the build is retried.");
    }
    // The event stream replays every progress event, which redraws the pictures
    // and the approval button exactly as they were.
    connectEvents(`/api/session/${id}/events`);
    world()?.attach(id);
    input.focus();
  }

  async function start() {
    const params = new URLSearchParams(location.search);
    const existing = params.get("session");
    if (existing) { await resume(existing); return; }

    setStrip("Getting the AI ready", "a few seconds — you can type now");
    try {
      // Give the world a moment to say where John is standing BEFORE the greeting is
      // written — otherwise the AI greets him knowing nothing and has to ask. Capped
      // hard at 1.5 s: a slow world delays the hello, it never blocks it.
      await waitForWorld(1500);
      const data = await jsonRequest("/api/session/unified/start", {
        method: "POST",
        body: JSON.stringify({ where: worldState && worldState.standing }),
      });
      sessionId = data.session_id;
      const url = new URL(location.href);
      url.searchParams.set("session", sessionId);
      history.replaceState(null, "", url.toString());
      sessionLabel.textContent = sessionId.slice(0, 8);
      // The front-door question is already on the page; the AI's greeting goes under it.
      appendMessage("assistant", data.opening_message || "Describe the space you'd like to create.");
      if (data.model) setModel(data.model);
      setStrip("Your move", "describe the place, or answer the question above");
      connectEvents(data.events_url || `/api/session/${sessionId}/events`);
      world()?.attach(sessionId);
      askWorld();
      if (pendingMessage) {
        const queued = pendingMessage;
        pendingMessage = null;
        // through the router, like every other sentence (2026-09-03): typed-before-ready
        // used to go straight to the room brain, so "add a red brick house" in the first
        // few seconds became a room — the exact bug Phase 1 removes.
        await routeMessage(queued);
      }
      input.focus();
    } catch (error) {
      setStrip("Couldn't start", "the Living Room didn't answer");
      appendMessage("system", `Couldn't start a session: ${error.message}. ` +
        "Is the Living Room (:8000) up? LIVING-ROOM.bat restarts it.");
    }
  }

  // Kick off once the world panel has registered its hook (or after a short
  // wait if it hasn't — start() degrades gracefully when window.LRWorld is null).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
