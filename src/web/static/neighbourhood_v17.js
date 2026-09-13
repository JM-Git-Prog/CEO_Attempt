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
  const WORLD_ORIGIN = "http://127.0.0.1:5173";   // must match world_v17.js — see the note there
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

  // ── THE JOBSITE (2026-09-10) ────────────────────────────────────────────────
  // Every poll tick that carries a `jobsite` block (from /order/<id> or /job/<id>) is
  // forwarded to the world verbatim, the same way askWorld() in unified_v17.js reaches
  // the iframe — same frame lookup, same WORLD_ORIGIN. The world is stateless about
  // time, so this fires on every tick, not just when something changed.
  function tellWorld(js) {
    const f = frame();
    if (!f || !f.contentWindow) return;
    try { f.contentWindow.postMessage({ source: "ceo-v17", type: "jobsite.update", jobsite: js }, WORLD_ORIGIN); } catch (e) { /* iframe not ready */ }
  }
  let lastNarrated = { arrived: false, onSite: false, stepKey: null };
  function resetJobsiteNarration() { lastNarrated = { arrived: false, onSite: false, stepKey: null }; }
  function narrateJobsite(js) {
    const p = js && js.progress;
    if (!p) return;
    if (js.stage === "rendering" || js.stage === "on the wall") {
      if (!lastNarrated.arrived && p.parts_on_site > 0) {
        lastNarrated.arrived = true;
        say("system", `Jobsite: parts arriving — ${p.parts_on_site} of ${p.parts_total} on site`);
      }
      if (!lastNarrated.onSite && p.parts_total > 0 && p.parts_on_site >= p.parts_total) {
        lastNarrated.onSite = true;
        say("system", `Jobsite: all ${p.parts_total} parts on site — pick a take on the signboard`);
      }
    } else if (js.stage === "building" || js.stage === "done") {
      // keyed on stage+step, not step alone: "done" reports the same step number as
      // the last building tick, and must still narrate once of its own.
      const key = `${js.stage}:${p.step}`;
      if (lastNarrated.stepKey !== key) {
        lastNarrated.stepKey = key;
        say("system", `Jobsite: step ${p.step} of ${p.steps} — ${p.note} · assembled ${p.assembled} of ${p.parts_total}`);
      }
    }
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
  // JOHN, 2026-09-11: the plan is machinery, so it lives over here with the build it
  // describes, not in his chat. The chat column dispatches it the moment the architect
  // answers; nothing is lost, it just stops interrupting the conversation.
  window.addEventListener("v17:plan", (ev) => {
    const card = (ev && ev.detail) || {};
    if (card.summary) say("system", `The plan: ${card.summary}`);
    const parts = Array.isArray(card.parts) ? card.parts : [];
    if (parts.length) say("system", `Parts: ${parts.join(", ")}`);
    const took = Array.isArray(card.assumptions) ? card.assumptions : [];
    if (took.length) say("system", `Filled in for him: ${took.join(" ")}`);
  });

  async function sayCouldnt(text) {
    const line = String(text || "").trim();
    if (!line || line === saidCouldnt) return;
    saidCouldnt = line;
    let friendly = "";
    try {
      const r = await fetch("/api/v17/couldnt", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ couldnt: line }),
      });
      if (r.ok) friendly = String((await r.json()).said || "");
    } catch (e) { friendly = ""; }
    // DECISION 33 / card 9 (John, 2026-09-11): the same facts, said by the builder he is
    // talking to instead of by the machine. "Couldn't use: could not build: red flowerpot"
    // becomes "I got everything except the red flowerpot - the workshop is still learning
    // that one." Nothing is softened away: every phrase survives into the new sentence,
    // and if it cannot be re-said the original is printed unchanged rather than lost.
    say("system", friendly || `Couldn't use: ${line}`);
  }

  async function poll(name, editing) {
    let st;
    try { st = await (await fetch(`${API}/job/${job}`)).json(); } catch (e) { return; }
    if (st.jobsite) { tellWorld(st.jobsite); narrateJobsite(st.jobsite); }
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

  // ── a new house: four pictures on the next empty lot's signboard, then the one he clicks is built ──
  // Decision 25 (John, 2026-09-10): "Four pictures of candidate houses stand on a signboard on the
  // lot, I pick one you build it." The order answers with `lot` (the place's next empty lot, from
  // its manifest); the world hangs the wall on that lot's sign, and the pane walks John to it. A
  // place without a plat (no `lot`) still hangs the wall in the garage, as before.
  let orderTimer = null;
  function stopOrder() { if (orderTimer) { clearInterval(orderTimer); orderTimer = null; } }
  function walkOverLine(text, lot) {
    const item = document.createElement("div");
    item.className = "message system gate"; item.textContent = text;
    const w = window.LRWorld;
    const go = lot && w && w.goToLot ? () => w.goToLot(lot) : (w && w.goToGarage ? () => w.goToGarage() : null);
    if (go) {
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "walk"; btn.textContent = "Walk over →";
      btn.addEventListener("click", go); item.append(" ", btn);
    }
    messages.appendChild(item); messages.scrollTop = messages.scrollHeight;
  }
  async function order(text, reference, orderHint, cardClause, cardId) {
    say("user", text);
    input.value = "";
    resetJobsiteNarration();
    say("system", (cardClause ? "Building from the architect's plan — " : "A new house — ") + "I'll draw four takes on it first (about a minute) and stand them on the signboard on the empty lot for you to choose.");
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
      // cardClause is the architect's confirmed plan (2026-09-10) — the builder's order form is read from it too.
      // cardId is that same card's id — the server looks up its parts so the jobsite can show them arriving.
      r = await fetch(`${API}/order`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, base: HOME, reference, session, order_hint: orderHint || null, card_clause: cardClause || null, card_id: cardId || null }) });
      data = await r.json();
    } catch (e) { say("failure", `Couldn't reach V17: ${e.message}`); return; }
    if (!r.ok) { say("failure", `${data.error || r.status}${data.hint ? " — " + data.hint : ""}`); return; }
    const b = data.brief || {}, h = (b.houses || [])[0] || {};
    say("system", `Got: ${[h.wall_color, h.wall, h.style].filter(Boolean).join(" ")}${h.roof ? ", " + h.roof + " roof" : ""}${h.garage && h.garage !== "none" ? ", garage " + h.garage : ""}${h.porch ? ", porch" : ""}${h.stories ? ", " + h.stories + " storey" + (h.stories === 1 ? "" : "s") : ""} — plan by ${b.source || "?"}.`);
    receipt(b);
    saidCouldnt = "";
    sayCouldnt(data.couldnt);
    if (!data.lot) say("system", "This place has no empty lot listed, so the pictures will hang in the garage instead.");
    watchOrder(data.order, text);
  }
  function watchOrder(orderId, text) {
    stopOrder();
    let announced = false;
    const tick = async () => {
      let resp, st;
      try { resp = await fetch(`${API}/order/${orderId}`); st = await resp.json(); } catch (e) { return; }
      if (resp.status === 404) {
        // the order is gone (V17 restarted) — the world is stateless about time, so tell it
        // once that this jobsite is finished rather than leaving it waiting on parts forever.
        stopOrder();
        tellWorld({ order: orderId, name: "", stage: "done", whole: { width_cm: 0, depth_cm: 0, height_cm: 0, stories: 0 },
                    plan: [], parts: [], progress: { step: 0, steps: 0, parts_on_site: 0, parts_total: 0, assembled: 0, note: "" } });
        say("failure", st.error || "That order is gone — say it again.");
        return;
      }
      if (st.jobsite) { tellWorld(st.jobsite); narrateJobsite(st.jobsite); }
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
        const n = st.count || 4;
        if (st.lot && st.lot.id) {
          walkOverLine(`${n} pictures stand on the signboard on lot ${st.lot.id} — walk up, left-click your favorite, right-click for ${n} new ones.`, st.lot);
          const w = window.LRWorld;
          if (w && w.goToLot) w.goToLot(st.lot);   // the pane jumps to the lot (decision 25): the choice appears where the house will live
        } else {
          walkOverLine(`${n} houses are on the garage wall — left-click the one you want built, right-click for ${n} new ones.`);
        }
      } else if (st.stage === "building") {
        stopOrder();
        const c = st.chosen || {};
        say("system", `Building your pick — ${[c.color, c.wall, c.style].filter(Boolean).join(" ")}${c.roof ? ", " + c.roof + " roof" : ""} — as the next version of ${HOME_NAME} (about a minute).`);
        job = st.build_job; walkedIn = false; stop();
        timer = setInterval(() => poll(HOME_NAME, true), 3000); poll(HOME_NAME, true);
      } else if (st.stage === "more") {
        stopOrder();
        say("system", "None of those — drawing four new takes (about a minute).");
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
