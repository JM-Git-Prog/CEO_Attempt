// neighbourhood_v17.js — build and KEEP BUILDING a place from the Living Room composer.
//
// John, 2026-09-02: "into the Living Room chat I already use v17".
// John, 2026-09-03: "load this world into v17 … start building from there through the chat …
//                    take advantage of all the local and cloud models available through Ollama".
//
// ONE PLACE, one composer (decision 22, John 2026-09-03: "a single persistent world for me
// with all of these homes, rooms, and minigames. Call it Mr. John's Neighborhood."):
//   every order about the grounds — a new home, a house's colour or roof, trees, the sky, the
//   street — is the NEXT VERSION of Mr. John's Neighborhood. The builder revises its brief
//   (Ollama, cloud tag first) and rebuilds it; the pane refreshes. Sentences about a ROOM,
//   or a check request ("which of these rooms do you like?"), go to the Living Room AI —
//   there is no "place mode" to be stuck in any more, and no place per sentence.
// Commands: open|load|show <place> (look at an old place) · leave (back to the neighborhood) ·
//           models|which models · use <tag>: <sentence>
//
// No longer listens to the composer: the server (/api/v17/say) decides what a sentence is;
// unified_v17.js calls the functions this file exposes on window.LRNeighbourhood. Still owns
// #nbPicture (build status) and #nbChip (which place you're on).
// Server side: src/web/v17_neighbourhood_routes.py proxies the builder on :8196.
(function () {
  const $ = (id) => document.getElementById(id);
  const composer = $("composer");
  const input = $("message");
  const messages = $("messages");
  const right = document.querySelector("section.right");
  if (!composer || !input || !messages || !right) return;

  const API = "/api/v17/neighbourhood";
  const WORLD_ORIGIN = "http://localhost:5173";
  // THE ONE PLACE every order builds on (decision 22)
  const HOME = "mr-johns-neighborhood";
  const HOME_NAME = "Mr. John's Neighborhood";

  // ── which place the pane is LOOKING at (the neighborhood unless "open <old place>") ──
  // Building always targets HOME; `place` only says what the frame shows, so the chip can
  // tell John he is looking at history. Nothing is remembered across loads any more —
  // the remembered place is what yanked the pane away twice today.
  let place = null;
  function remember(slug) {
    place = slug;
    try { localStorage.removeItem("nb.place"); } catch (e) { /* private window */ }
    const away = slug && slug !== HOME;
    chip.textContent = away ? `Looking at ${slug} (history) · type "leave" to go home · orders still build ${HOME_NAME}` : `${HOME_NAME} · say what to add or change on the grounds`;
    chip.hidden = false;
  }

  // ── UI bits (reuse the page's classes) ─────────────────────────────────────
  const panel = document.createElement("div");
  panel.className = "world-picture"; panel.id = "nbPicture"; panel.hidden = true;
  panel.innerHTML = '<img id="nbPictureImg" alt="neighbourhood" hidden><div class="world-picture-bar"><span id="nbCaption"></span>' +
    '<span class="world-picture-actions"><button type="button" class="ghost" id="nbClose">Back to the world</button></span></div>';
  right.appendChild(panel);
  const img = $("nbPictureImg"), caption = $("nbCaption");
  $("nbClose").addEventListener("click", () => { panel.hidden = true; });
  const chip = document.createElement("span");
  chip.className = "chip"; chip.id = "nbChip"; chip.hidden = true;
  chip.style.cssText = "position:absolute;top:12px;left:50%;transform:translateX(-50%);z-index:3;pointer-events:none;background:rgba(10,23,19,.86);border:1px solid #244238;padding:4px 9px;border-radius:5px;font-size:11px;color:#8edbb8;white-space:nowrap";
  right.appendChild(chip);

  function say(role, text) {
    const item = document.createElement("div");
    item.className = `message ${role}`; item.textContent = text;
    messages.appendChild(item); messages.scrollTop = messages.scrollHeight;
  }
  // The receipt (decision 22, tools/capability-gaps.CONTRACT.md §4): Got / Making / Needs a new tool —
  // never a silence. brief.gaps = the phrases the form could not hold, noted for the workshop this
  // time. "Needs a new tool" waits for the router's verdict; until then every leftover is "Making".
  function receipt(b) {
    // brief.gaps = only what NO helper of the builder can make (the builder's own parts — columns,
    // pediment, dormers, chimneys… — are built, not sent away; the "Built into the first take"
    // line after the pictures says what actually got made)
    const gaps = (b && b.gaps) || [];
    say("system", gaps.length ? `Making in the workshop: ${gaps.join(", ")} — pictures land on the garage wall when rendered.` : "Got everything the builder can make itself.");
  }
  function frame() { return right.querySelector("iframe"); }
  function walkIn(worldUrl) {
    const f = frame();
    if (!f) { say("failure", "The world pane has no frame yet — is your world (:5173) running?"); return false; }
    f.src = `${WORLD_ORIGIN}${worldUrl}${worldUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
    panel.hidden = true;
    const empty = $("worldEmpty"); if (empty) empty.hidden = true;
    return true;
  }

  // ── the build/edit job ──────────────────────────────────────────────────────
  let timer = null, job = null, walkedIn = false;
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  // What the builder could NOT use of what John asked (2026-09-03). Its order form
  // holds only 5 styles / 5 walls / 8 colours / 5 roofs, and anything off those lists
  // used to be swapped for colonial-brick-natural-clay in silence — which is why every
  // house read as the same stock house. The server now reports the swap and the
  // features it could not build; this is the only place John ever sees it. Said once
  // per job: `couldnt` arrives both on the order and again on the finished job.
  let saidCouldnt = "";
  function sayCouldnt(text) {
    const line = String(text || "").trim();
    if (!line || line === saidCouldnt) return;
    saidCouldnt = line;
    say("system", `Couldn't use: ${line}`);
  }

  async function poll(name, editing) {
    let st;
    try { st = await (await fetch(`${API}/job/${job}`)).json(); } catch (e) { return; }
    if (st.world_ready && !walkedIn) {
      walkedIn = walkIn(st.world_url || `/${st.world}`);
      remember(st.world);
      const houses = (st.houses || []).map((h) => `${h.name}: ${h.color} ${h.wall} ${h.style}, ${h.roof} roof${h.garage !== "none" ? ", garage " + h.garage : ""}`).join("; ");
      say("assistant", `${name}${editing ? ` is rebuilt (version ${st.version})` : " is in your world"} — ${st.world_seconds}s in UPBGE, ${st.glb_mb} MB. ${houses}. Click the world to look, WASD to walk, E opens doors and switches. Keep typing to change it.`);
      if ((st.fallbacks || []).length) say("system", `Textures not on the shelf yet, plain colour used: ${st.fallbacks.join(", ")}`);
      sayCouldnt(st.couldnt);
    }
    if (st.status === "building") {
      if (!walkedIn) { caption.textContent = `${editing ? "Rebuilding" : "Building"} ${name} — ${st.stage}`; panel.hidden = false; }
      return;
    }
    stop();
    if (st.status !== "done") { say("failure", `The build failed: ${(st.error || st.stage || "unknown").slice(-600)}`); panel.hidden = true; }
  }

  async function build(text, base) {
    say("user", text);
    input.value = "";
    say("system", base ? `Editing ${base}: reading your sentence (Ollama) and rebuilding it in UPBGE…` : "Reading your sentence (Ollama) and starting UPBGE in the background…");
    let r, data;
    try {
      r = await fetch(`${API}/build`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, base: base || null }) });
      data = await r.json();
    } catch (e) { say("failure", `Couldn't reach V17: ${e.message}`); return; }
    if (!r.ok) { say("failure", `${data.error || r.status}${data.hint ? " — " + data.hint : ""}`); return; }
    job = data.job;
    const b = data.brief || {};
    const name = b.name || base || "Your neighbourhood";
    say("system", `${name}: ${b.house_count} houses, ${b.layout}, ${b.sky} sky, ${b.trees} trees — plan by ${b.source}. ${base ? "The pane refreshes" : "The right pane switches to it"} the moment it's ready — about a minute.`);
    receipt(b);
    saidCouldnt = "";
    sayCouldnt(data.couldnt);
    walkedIn = false;
    caption.textContent = `${base ? "Rebuilding" : "Building"} ${name} — starting UPBGE`;
    img.removeAttribute("src"); img.hidden = true;
    panel.hidden = false;
    stop();
    timer = setInterval(() => poll(name, !!base), 3000);
    poll(name, !!base);
  }

  async function listModels() {
    try {
      const m = await (await fetch(`${API}/models`)).json();
      if (m.error) { say("failure", `${m.error}${m.hint ? " — " + m.hint : ""}`); return; }
      say("assistant", `Your Ollama garage — cloud (prepaid, the 4090 stays free): ${m.cloud.join(", ")}.\nLocal (on the 4090): ${m.local.join(", ")}.\nFor planning a place I use, in order: ${m.lane.join(" → ")}. Say "use <model>: <sentence>" to force one.`);
    } catch (e) { say("failure", `Couldn't list models: ${e.message}`); }
  }

  // ── a new house: three pictures on the garage wall, then the one he clicks is built ──────
  let orderTimer = null;
  function stopOrder() { if (orderTimer) { clearInterval(orderTimer); orderTimer = null; } }
  function walkOverLine(text) {
    const item = document.createElement("div");
    item.className = "message system gate"; item.textContent = text;
    const w = window.LRWorld;
    if (w && w.goToGarage) {
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "walk"; btn.textContent = "Walk over →";
      btn.addEventListener("click", () => w.goToGarage()); item.append(" ", btn);
    }
    messages.appendChild(item); messages.scrollTop = messages.scrollHeight;
  }
  async function order(text, reference, orderHint) {
    say("user", text);
    input.value = "";
    say("system", "A new house — I'll draw three takes on it first (about a minute) and hang them in the garage for you to choose.");
    // a picture pasted in the last 10 minutes rides with a HOUSE order — and stays available for the
    // next house order too (John re-sent his mansion sentence and the second order lost the photo:
    // the builder then read "white columns" as a white wall). A new paste replaces it.
    // unified_v17.js now peeks/takes the reference and passes it in; the peek() fallback below
    // only covers a direct call with no argument, so nothing breaks.
    if (reference === undefined) reference = (window.LRReference && (window.LRReference.peek ? window.LRReference.peek() : window.LRReference.take())) || null;
    const session = new URLSearchParams(location.search).get("session");
    let r, data;
    try {
      // orderHint is gemma4's read of the pasted photo (from /api/v17/say). The server
      // turns it into words for the builder's order form — without it, "very presidential"
      // has to carry the whole house on its own.
      r = await fetch(`${API}/order`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, base: HOME, reference, session, order_hint: orderHint || null }) });
      data = await r.json();
    } catch (e) { say("failure", `Couldn't reach V17: ${e.message}`); return; }
    if (!r.ok) { say("failure", `${data.error || r.status}${data.hint ? " — " + data.hint : ""}`); return; }
    const b = data.brief || {}, h = (b.houses || [])[0] || {};
    say("system", `Got: ${[h.wall_color, h.wall, h.style].filter(Boolean).join(" ")}${h.roof ? ", " + h.roof + " roof" : ""}${h.garage && h.garage !== "none" ? ", garage " + h.garage : ""}${h.porch ? ", porch" : ""}${h.stories ? ", " + h.stories + " storey" + (h.stories === 1 ? "" : "s") : ""} — plan by ${b.source || "?"}.`);
    receipt(b);
    saidCouldnt = "";
    sayCouldnt(data.couldnt);
    watchOrder(data.order, text);
  }
  function watchOrder(orderId, text) {
    stopOrder();
    let announced = false;
    const tick = async () => {
      let st;
      try { st = await (await fetch(`${API}/order/${orderId}`)).json(); } catch (e) { return; }
      if (st.error) { stopOrder(); say("failure", st.error); return; }
      if (st.stage === "on the wall" && !announced) {
        announced = true;
        // the honest receipt comes from the BUILD, not the wish list: what the first take has,
        // and what the builder could not make (its own words, e.g. "dormers (a flat roof has no slope)")
        try {
          const jb = await (await fetch(`${API}/job/${orderId}`)).json();
          const built = ((jb.houses || [])[0] || {}).features_built || [];
          const cant = (jb.unbuilt_features || []).filter((u) => u.house === "H1" || u.house === "grounds").map((u) => u.phrase);
          if (built.length) say("system", `Built into the first take: ${built.join(", ")}.`);
          if (cant.length) say("system", `Couldn't build: ${cant.join("; ")} — noted for the workshop.`);
        } catch (e) { /* the wall line below still says where to look */ }
        walkOverLine(`${st.count || 3} houses are on the garage wall — left-click the one you want built, right-click for three new ones.`);
      } else if (st.stage === "building") {
        stopOrder();
        const c = st.chosen || {};
        say("system", `Building your pick — ${[c.color, c.wall, c.style].filter(Boolean).join(" ")}${c.roof ? ", " + c.roof + " roof" : ""} — as the next version of ${HOME_NAME} (about a minute).`);
        job = st.build_job; walkedIn = false; stop();
        timer = setInterval(() => poll(HOME_NAME, true), 3000); poll(HOME_NAME, true);
      } else if (st.stage === "more") {
        stopOrder();
        say("system", "None of those — drawing three new takes (about a minute).");
        watchOrder(st.next_order, text);
      } else if (st.stage === "failed") {
        stopOrder(); say("failure", `The pictures failed: ${(st.error || "").slice(-400)}`);
      }
    };
    orderTimer = setInterval(tick, 3000); tick();
  }

  // reopen the remembered place once the world frame exists (world_v17.js creates it on load)
  //
  // 2026-09-03 — an EXPLICIT destination on V17's own address wins. The page opened
  // with ?garage=… (world_v17.js: the review garage, or its rehearsal) and this
  // reopen used to yank the frame to the remembered place a quarter-second later,
  // so John landed on "cul-de-sac-of-homes" with a "Building on" chip instead of
  // at the garage door, and then lost the garage's spawn/rehearsal on the way back
  // (root-caused live from his screenshot). While the page is on a garage errand the
  // place is not reopened and sentences go to the room chat; the remembered place is
  // left in storage untouched, so a plain V17 load still restores it.
  // 2026-09-03 (decision 22): world_v17.js already opens the pane on Mr. John's Neighborhood
  // (or on its garage for an errand) — nothing is reopened from storage any more.
  const explicitDestination = new URLSearchParams(location.search).get("garage");
  place = HOME;
  try { localStorage.removeItem("nb.place"); } catch (e) { /* private window */ }
  if (explicitDestination) chip.hidden = true; else remember(HOME);

  // unified_v17.js calls these once /api/v17/say has decided what kind a sentence is — the
  // browser no longer decides that itself (2026-09-03 fix).
  window.LRNeighbourhood = { order, build, walkIn, listModels, remember, HOME };
})();
