/* Pipeline Inspector — horizontal HITL filmstrip for the V2.0 pipeline.
 *
 * Read-only post-hoc review: fetches /inspect-data for a session, renders one
 * panel per pipeline stage left-to-right, with expand modals, a mesh
 * count+expand grid, loading skeletons, and per-panel error boundaries.
 * HITL verdicts persist to localStorage (no server gating in this phase).
 */
(function () {
  "use strict";

  // ─── SVG icon set ─────────────────────────────────────────────────────────
  const ICON = {
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    expand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>',
    cube: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/></svg>',
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 11l5-5 5 5M7 18l5-5 5 5"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  };

  const STAGES = [
    { key: "brief", n: 1 },
    { key: "plan", n: 2 },
    { key: "capture", n: 3 },
    { key: "views", n: 4 },
    { key: "catalog", n: 5 },
    { key: "meshes", n: 6 },
    { key: "shell", n: 7 },
    { key: "world", n: 8 },
  ];

  // ─── DOM helpers ────────────────────────────────────────────────────────────
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function num(v, d) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 2 : d });
  }

  // ─── Session id from query ────────────────────────────────────────────────
  const params = new URLSearchParams(location.search);
  const sessionId = params.get("session") || params.get("s") || "";

  const strip = document.getElementById("strip");
  const sessionLabel = document.getElementById("sessionLabel");
  const statePill = document.getElementById("statePill");
  const stateText = document.getElementById("stateText");

  // ─── Modal ──────────────────────────────────────────────────────────────────
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  document.getElementById("modalClose").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  function openImageModal(title, url) {
    modalTitle.textContent = title;
    modalBody.innerHTML = "";
    const img = el("img");
    img.src = url;
    img.alt = title;
    modalBody.appendChild(img);
    modal.classList.add("open");
  }
  function openModelModal(title, url) {
    modalTitle.textContent = title;
    modalBody.innerHTML = "";
    const mv = document.createElement("model-viewer");
    mv.setAttribute("src", url);
    mv.setAttribute("camera-controls", "");
    mv.setAttribute("auto-rotate", "");
    mv.setAttribute("shadow-intensity", "1");
    mv.setAttribute("exposure", "1.1");
    mv.style.width = "100%";
    mv.style.height = "100%";
    modalBody.appendChild(mv);
    modal.classList.add("open");
  }
  function closeModal() {
    modal.classList.remove("open");
    // Clear after the transition so a heavy model-viewer stops rendering.
    setTimeout(() => { modalBody.innerHTML = ""; }, 220);
  }

  // ─── HITL verdicts (server-persisted, localStorage fallback) ─────────────────
  // In-memory cache populated from the server at boot; each change is written
  // through to the server AND mirrored to localStorage as an offline fallback.
  let VERDICTS = {};
  function verdictKey() { return "hitl:" + sessionId; }

  function loadVerdicts() { return VERDICTS; }

  async function fetchVerdicts() {
    // Prefer the server copy; fall back to localStorage if the call fails.
    try {
      const r = await fetch(
        "/api/v2/session/" + encodeURIComponent(sessionId) + "/verdicts");
      if (r.ok) {
        const d = await r.json();
        VERDICTS = d.verdicts || {};
        return;
      }
    } catch (_) { /* fall through to localStorage */ }
    try { VERDICTS = JSON.parse(localStorage.getItem(verdictKey()) || "{}"); }
    catch (_) { VERDICTS = {}; }
  }

  function saveVerdict(stageKey, value) {
    VERDICTS[stageKey] = value;
    // Local mirror (instant, offline-safe).
    try { localStorage.setItem(verdictKey(), JSON.stringify(VERDICTS)); } catch (_) {}
    // Write through to the server (best-effort; UI already reflects the change).
    fetch("/api/v2/session/" + encodeURIComponent(sessionId) + "/verdicts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: stageKey, verdict: value }),
    }).catch(() => { /* offline: localStorage mirror holds it */ });
  }

  // ─── Panel builders (per kind) ───────────────────────────────────────────────
  function buildMedia(url, title, opts) {
    opts = opts || {};
    const m = el("div", "media" + (url ? " clickable" : ""));
    if (url) {
      const img = el("img");
      img.loading = "lazy";
      img.src = url;
      img.alt = title;
      img.addEventListener("error", () => {
        m.innerHTML = '<div class="thumb-3d"><div class="lbl">image unavailable</div></div>';
      });
      m.appendChild(img);
      const ov = el("div", "media-overlay",
        '<span class="icon">' + ICON.expand + " Expand</span>");
      m.appendChild(ov);
      m.addEventListener("click", () => openImageModal(title, url));
    }
    return m;
  }

  function buildThumb3D(title, glbUrl, label) {
    const m = el("div", "media clickable");
    // Cube placeholder shown until the model-viewer loads (or if GLB is a
    // scene manifest URL rather than a direct .glb — then we keep the cube).
    const isDirectGlb = /\/room-shell$|\.glb($|\?)/.test(glbUrl || "");
    m.innerHTML =
      '<div class="thumb-3d">' +
      '<span class="cube">' + ICON.cube + "</span>" +
      '<span class="lbl">' + esc(label || "3D model") + "</span>" +
      "</div>" +
      '<div class="media-overlay"><span class="icon">' + ICON.expand + " View 3D</span></div>";

    if (isDirectGlb) {
      // Inline live preview: a small auto-rotating model-viewer as the thumbnail.
      const mv = document.createElement("model-viewer");
      mv.setAttribute("src", glbUrl);
      mv.setAttribute("auto-rotate", "");
      mv.setAttribute("rotation-per-second", "24deg");
      mv.setAttribute("camera-controls", "");
      mv.setAttribute("disable-zoom", "");
      mv.setAttribute("interaction-prompt", "none");
      mv.setAttribute("shadow-intensity", "0.6");
      mv.setAttribute("exposure", "1.05");
      mv.style.position = "absolute";
      mv.style.inset = "0";
      mv.style.width = "100%";
      mv.style.height = "100%";
      mv.style.setProperty("--poster-color", "transparent");
      // When the model loads, drop the cube placeholder underneath it.
      mv.addEventListener("load", () => {
        const ph = m.querySelector(".thumb-3d");
        if (ph) ph.style.opacity = "0";
      });
      mv.addEventListener("error", () => {
        // keep the cube placeholder; expand modal still works
      });
      // Insert the viewer beneath the overlay so the "View 3D" hint stays on top.
      m.insertBefore(mv, m.querySelector(".media-overlay"));
    }

    m.addEventListener("click", () => openModelModal(title, glbUrl));
    return m;
  }

  function renderBody(stage) {
    const body = el("div", "card-body");
    try {
      switch (stage.kind) {
        case "json": { // Brief
          const d = stage.data || {};
          const objs = d.object_manifest || [];
          const kv = el("dl", "kv");
          kv.innerHTML =
            "<dt>Purpose</dt><dd>" + esc(d.room_purpose || "—") + "</dd>" +
            "<dt>Mood</dt><dd>" + esc((d.atmosphere || {}).mood || "—") + "</dd>" +
            "<dt>Era</dt><dd>" + esc((d.era || {}).period || "—") + "</dd>" +
            "<dt>Objects</dt><dd>" + objs.length + "</dd>";
          body.appendChild(kv);
          if (objs.length) {
            const tags = el("div", "taglist");
            objs.slice(0, 8).forEach((o) =>
              tags.appendChild(el("span", "tag", esc(o.name || "?"))));
            body.appendChild(tags);
          }
          break;
        }
        case "plan": { // MetricPlan
          const d = stage.data || {};
          const dims = d.room_dimensions || [];
          const kv = el("dl", "kv");
          kv.innerHTML =
            "<dt>Template</dt><dd>" + esc(d.template_id || "—") + "</dd>" +
            "<dt>Width</dt><dd>" + num(dims[0], 1) + " m</dd>" +
            "<dt>Depth</dt><dd>" + num(dims[1], 1) + " m</dd>" +
            "<dt>Ceiling</dt><dd>" + num(dims[2], 1) + " m</dd>" +
            "<dt>Placements</dt><dd>" + (d.object_placements || []).length + "</dd>" +
            "<dt>Openings</dt><dd>" + (d.openings || []).length + "</dd>";
          body.appendChild(kv);
          break;
        }
        case "capture": { // CaptureManifest
          const d = stage.data || {};
          const cams = d.cameras || [];
          const kv = el("dl", "kv");
          kv.innerHTML =
            "<dt>Cameras</dt><dd>" + cams.length + "</dd>" +
            "<dt>Poses</dt><dd>exact K/R/t</dd>";
          body.appendChild(kv);
          const tags = el("div", "taglist");
          cams.slice(0, 6).forEach((c, i) =>
            tags.appendChild(el("span", "tag", "cam " + i)));
          body.appendChild(tags);
          body.appendChild(el("div", "note",
            "Deterministic cameras rendered from the MetricPlan — the geometry is injected, not estimated."));
          break;
        }
        case "views": { // Views + depth
          const views = stage.views || [];
          if (!views.length) { body.appendChild(el("div", "note", "No views generated.")); break; }
          // Show first view canon as the media; list depth availability.
          body.appendChild(buildMedia(views[0].canon_url, "View " + views[0].index, {}));
          const tags = el("div", "taglist");
          views.forEach((v) => {
            const t = el("span", "tag", "view " + v.index + (v.depth_url ? " +depth" : ""));
            t.style.cursor = "pointer";
            t.addEventListener("click", () => openImageModal("View " + v.index, v.canon_url));
            tags.appendChild(t);
          });
          body.appendChild(tags);
          break;
        }
        case "catalog": { // Detected objects
          const d = stage.data || {};
          const entries = d.entries || [];
          body.appendChild(el("div", "count-badge",
            '<span class="n">' + entries.length + "</span> detected"));
          const tags = el("div", "taglist");
          entries.slice(0, 10).forEach((e) =>
            tags.appendChild(el("span", "tag", esc(e.name || "?"))));
          body.appendChild(tags);
          if (entries.length > 10)
            body.appendChild(el("div", "note", "+" + (entries.length - 10) + " more"));
          break;
        }
        case "meshes": { // Object meshes — count + expand grid
          const meshes = stage.meshes || [];
          const real = meshes.filter((m) => !m.is_placeholder).length;
          const badge = el("div", "count-badge",
            '<span class="n">' + meshes.length + "</span> Objects " + ICON.down);
          badge.querySelector("svg").classList.add("chev");
          body.appendChild(badge);
          body.appendChild(el("div", "note",
            real + " real · " + (meshes.length - real) + " placeholder"));
          const grid = el("div", "mesh-grid");
          meshes.forEach((m) => {
            const chip = el("div", "mesh-chip");
            chip.innerHTML =
              '<span class="name">' + esc(m.name) + "</span>" +
              '<span class="meta">' + num(m.face_count, 0) + " faces</span>" +
              (m.is_placeholder
                ? '<span class="badge-ph">PLACEHOLDER</span>'
                : '<span class="badge-real">' + esc(m.method || "mesh") + "</span>");
            chip.addEventListener("click", () => openModelModal(m.name, m.glb_url));
            grid.appendChild(chip);
          });
          body.appendChild(grid);
          badge.addEventListener("click", () => {
            const open = grid.classList.toggle("open");
            badge.classList.toggle("open", open);
          });
          break;
        }
        case "glb": { // Room shell
          body.appendChild(buildThumb3D("Room Shell", stage.glb_url, "Reconstructed shell"));
          body.appendChild(el("div", "note",
            "Depth-back-projected room shell (reconstructed, not parametric)."));
          break;
        }
        case "world": { // Assembled world
          body.appendChild(buildThumb3D("Assembled World", stage.scene_url, "Walkable scene"));
          const kv = el("dl", "kv");
          kv.innerHTML = "<dt>Objects placed</dt><dd>" + (stage.object_count || 0) + "</dd>";
          body.appendChild(kv);
          if (stage.world_url) {
            const link = el("div", "count-badge", "Open walkable world " + ICON.arrow);
            link.addEventListener("click", () => window.open(stage.world_url, "_blank"));
            body.appendChild(link);
          }
          break;
        }
        default:
          body.appendChild(el("div", "note", "No preview for this stage."));
      }
    } catch (err) {
      body.innerHTML = "";
      body.appendChild(el("div", "err-box",
        '<span class="t">Render error</span><span>' + esc(err.message || err) + "</span>"));
    }
    return body;
  }

  function buildVerdict(stageKey, present) {
    const foot = el("div", "verdict");
    const approve = el("button", "vbtn approve",
      ICON.up.replace("<svg", '<svg width="15" height="15"') + " Approve");
    const reject = el("button", "vbtn reject",
      ICON.down.replace("<svg", '<svg width="15" height="15"') + " Reject");
    if (!present) { approve.disabled = true; reject.disabled = true; }
    const saved = loadVerdicts()[stageKey];
    if (saved === "approve") approve.classList.add("active");
    if (saved === "reject") reject.classList.add("active");
    approve.addEventListener("click", () => {
      approve.classList.add("active"); reject.classList.remove("active");
      saveVerdict(stageKey, "approve");
    });
    reject.addEventListener("click", () => {
      reject.classList.add("active"); approve.classList.remove("active");
      saveVerdict(stageKey, "reject");
    });
    foot.appendChild(approve);
    foot.appendChild(reject);
    return foot;
  }

  function buildCard(stage, n) {
    const present = stage.status === "complete";
    const card = el("div", "card" + (present ? "" : " absent"));

    const head = el("div", "card-head");
    head.appendChild(el("div", "card-num", String(n)));
    head.appendChild(el("div", "card-title", esc(stage.title)));
    const dot = el("div", "status-dot " + (present ? "complete" : "absent"));
    head.appendChild(dot);
    card.appendChild(head);

    if (present) {
      card.appendChild(renderBody(stage));
    } else {
      const body = el("div", "card-body");
      body.appendChild(el("div", "note", "Not produced yet."));
      card.appendChild(body);
    }

    card.appendChild(buildVerdict(stage.key, present));
    return card;
  }

  function buildStageWrapper(card, isLast) {
    const wrap = el("div", "stage");
    wrap.appendChild(card);
    const conn = el("div", "connector", isLast ? "" : ICON.arrow);
    wrap.appendChild(conn);
    return wrap;
  }

  // ─── Skeleton (loading) ──────────────────────────────────────────────────────
  function renderSkeletons() {
    strip.innerHTML = "";
    STAGES.forEach((s, i) => {
      const card = el("div", "card");
      const head = el("div", "card-head");
      head.appendChild(el("div", "card-num", String(s.n)));
      head.appendChild(el("div", "card-title skeleton sk-line", "&nbsp;"));
      card.appendChild(head);
      const body = el("div", "card-body");
      body.appendChild(el("div", "skeleton sk-media"));
      body.appendChild(el("div", "skeleton sk-line"));
      body.appendChild(el("div", "skeleton sk-line"));
      card.appendChild(body);
      strip.appendChild(buildStageWrapper(card, i === STAGES.length - 1));
    });
  }

  function renderFatal(msg) {
    strip.innerHTML =
      '<div class="fatal"><h2>Could not load session</h2><p>' + esc(msg) +
      '</p><p>Append <code>?session=&lt;id&gt;</code> to the URL.</p></div>';
  }

  // ─── Boot ─────────────────────────────────────────────────────────────────────
  async function boot() {
    if (!sessionId) { renderFatal("No session id provided."); return; }
    sessionLabel.textContent = sessionId;
    renderSkeletons();

    let data;
    try {
      // Fetch stage data + persisted verdicts in parallel; verdicts must be
      // loaded before panels render so saved Approve/Reject states show.
      const [resp] = await Promise.all([
        fetch("/api/v2/session/" + encodeURIComponent(sessionId) + "/inspect-data"),
        fetchVerdicts(),
      ]);
      if (!resp.ok) {
        const e = await resp.json().catch(() => ({}));
        throw new Error(e.error || ("HTTP " + resp.status));
      }
      data = await resp.json();
    } catch (err) {
      renderFatal(err.message || String(err));
      return;
    }

    // State pill
    const st = data.state || "unknown";
    stateText.textContent = st;
    statePill.classList.remove("ok", "building");
    if (st === "complete" || (data.stages || []).every((s) => s.status === "complete")) {
      statePill.classList.add("ok");
    } else if (st === "building") {
      statePill.classList.add("building");
    }

    // Map returned stages by key, render in canonical order.
    const byKey = {};
    (data.stages || []).forEach((s) => { byKey[s.key] = s; });

    strip.innerHTML = "";
    STAGES.forEach((meta, i) => {
      const stage = byKey[meta.key] || { key: meta.key, title: meta.key, status: "absent" };
      let card;
      try {
        card = buildCard(stage, meta.n);
      } catch (err) {
        // Per-panel error boundary: one bad stage never blanks the whole strip.
        card = el("div", "card");
        const head = el("div", "card-head");
        head.appendChild(el("div", "card-num", String(meta.n)));
        head.appendChild(el("div", "card-title", esc(stage.title || meta.key)));
        head.appendChild(el("div", "status-dot absent"));
        card.appendChild(head);
        const body = el("div", "card-body");
        body.appendChild(el("div", "err-box",
          '<span class="t">Panel error</span><span>' + esc(err.message || err) + "</span>"));
        card.appendChild(body);
      }
      strip.appendChild(buildStageWrapper(card, i === STAGES.length - 1));
    });
  }

  boot();
})();
