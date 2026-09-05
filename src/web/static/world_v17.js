/*
 * V17 split-screen — RIGHT PANEL: THE WORLD.
 *
 * 2026-09-02, Slice 3a. This file used to be a private Three.js scene: it drew a
 * grey shell and a box per planned object for THIS session only, and forgot all
 * of it the moment John started another one. Meanwhile the real world — the
 * tower, the grounds, 128 warehouse assets, Rapier physics, walk rules, the
 * finish system — has been running at :5173 the whole time, and the two had
 * never been connected.
 *
 * John, looking at the pane: "this is where I want to see the entire game world
 * come to life... all while I steer from the chat box." So the pane now shows
 * THE world, not a sketch of one. Decision 13 (00-Vision-Product §2): the world
 * is a playable game, not a viewer.
 *
 * WHY AN IFRAME, and not a port of the world into this page:
 *   - :5173 IS the world (single-world rule, John 2026-07-07). Re-implementing
 *     it here would create the second copy that BUILD-RULES G7 forbids, and the
 *     hand-copied towerPlan drift is exactly what caused the 5173 migration.
 *   - Decision 7 already says the front end is swappable and the world sits
 *     underneath. An embed is that architecture, not a shortcut around it.
 *   - It costs nothing to keep current: the world updates, the pane updates.
 *
 * WHAT IS NOT WIRED YET, stated rather than implied:
 *   - Objects a session generates do NOT yet appear in the world; they land in
 *     the warehouse and need a scene.json write to be placed. That bridge is the
 *     next slice, and until it exists the pane shows the world as it is on disk.
 *   - :8000 and :5173 are different origins, so this page cannot reach into the
 *     world's scene. Steering it needs a postMessage channel on the world side.
 *
 * window.LRWorld keeps the same shape the chat panel already calls, so
 * unified_v17.js needs no changes.
 */
(() => {
  "use strict";

  // 127.0.0.1, NOT localhost (2026-09-04). Same server either way for John's Chrome,
  // but Claude's own in-app browser pane REFUSES http://localhost:5173 outright while
  // http://127.0.0.1:5173 loads the world fine — so the whole right-hand pane was
  // invisible to Claude, and every world problem this week needed John to screenshot it.
  const WORLD_ORIGIN = "http://127.0.0.1:5173";
  // John's call, 2026-09-02: "at the front gate, every time." The world already
  // spawns outside the tower's south entrance (GROUNDS_SPAWN in spawn.ts), so
  // loading /my-office fresh each session IS the ritual — no override needed.
  // ?mode=play: open ON FOOT at the gate, not in the builder. Without it the
  // world's remembered mode wins, and John's first screen was the Build panel
  // inside the tower — the opposite of "front gate, every time".
  // THE ONE WORLD (decision 22, John 2026-09-03: "a single persistent world for me with
  // all of these homes, rooms, and minigames. Call it Mr. John's Neighborhood."). The
  // pane opens at its entrance — the road's origin, looking down the cul-de-sac — and
  // every order from the chat is the next version of this place. The old default
  // (/my-office) is one of the places to be moved in.
  const HOME = "mr-johns-neighborhood";
  const WORLD_URL = `${WORLD_ORIGIN}/${HOME}?mode=play`;
  // THE REVIEW GARAGE (John, 2026-09-03): remade props wait on pedestals inside the
  // neighborhood's workshop garage; walk up, the door rolls up, stamp each piece. The
  // numbers are the world's own geometry — the "H1 Garage Door" node (the seed was
  // cul-de-sac-5) is centred at x −11.1, z −28.2 (read from the GLB, not typed) —
  // and the spawn stands 7 m out on the drive, looking at that door. The world
  // reads ?spawn / ?look / ?garage (modules/environment/outdoor.ts).
  const REVIEW_GARAGE = { slug: HOME, garage: "H1", spawn: "-6,1.7,-23", look: "-11.1,1.5,-28.2" };
  const GARAGE_URL = `${WORLD_ORIGIN}/${REVIEW_GARAGE.slug}?garage=${REVIEW_GARAGE.garage}&spawn=${REVIEW_GARAGE.spawn}&look=${REVIEW_GARAGE.look}`;
  // A rehearsal: four finished pieces stand in as practice — every stamp lands, nothing is
  // filed (the world skips the board when ?reviewtest= is on the address). Opened with
  // V17's own address: /?v=17&garage=rehearsal
  const REHEARSAL_IDS = ["a-file-cabinet-mk2-r1", "bankers-desk-lamp-solid-dome-shade-ro-r1", "oak-wine-barrel-thick-wooden-staves-s-r2", "rustic-wooden-step-stool-with-faded-g-r1"];
  const REHEARSAL_URL = `${GARAGE_URL}&reviewtest=${REHEARSAL_IDS.join(",")}`;
  // The paint bake-off (2026-09-03): the lamp painted by the Trellis2 projection route (66 s on
  // the GPU) on one pedestal, the regular route's lamp beside it once it lands — John picks.
  // "@paint" puts a piece's PAINTED file on the pedestal (its paint gate). /?v=17&garage=bakeoff
  // three pedestals: the hybrid lamp (Trellis2 unwrap on the GPU + Hunyuan 360 paint — appears once its
  // paint lands), the front-only Trellis2 projection lamp, and the same lamp unpainted (grey) for the shape
  // + the regular hour-long lamp (John: "keep it — I want to compare"); a pedestal stays empty until its file lands
  const BAKEOFF_IDS = ["bankers-desk-lamp-solid-dome-r1-hybrid@paint", "bankers-desk-lamp-solid-dome-shade-ro-r1@paint", "bankers-desk-lamp-solid-dome-shade-ro-r1-trellis@paint", "bankers-desk-lamp-solid-dome-shade-ro-r1"];
  const BAKEOFF_URL = `${GARAGE_URL}&reviewtest=${BAKEOFF_IDS.join(",")}`;
  const pageAsk = new URLSearchParams(window.location.search).get("garage");
  let currentUrl = pageAsk === "rehearsal" ? REHEARSAL_URL : pageAsk === "bakeoff" ? BAKEOFF_URL : pageAsk === "1" ? GARAGE_URL : WORLD_URL;
  let pendingNote = pageAsk ? "The garage ahead of you. Walk up (W) and the door rolls up. Click once to take the mouse, then left-click ✓ approve · right-click ✗ no" + (pageAsk === "rehearsal" ? " — practice only, nothing is filed." : pageAsk === "bakeoff" ? " — the bake-off: the painted lamp is the fast route, the grey one is the same mesh unpainted; nothing is filed." : ".") : ""; // shown once the place has loaded

  const holder = document.getElementById("worldHolder");
  const canvas = document.getElementById("worldCanvas");
  const empty = document.getElementById("worldEmpty");
  const note = document.getElementById("worldNote");
  const enterBtn = document.getElementById("enterWorld");
  if (!holder) return;

  // The old canvas belonged to the scratch scene. Nothing draws to it now.
  canvas?.remove();

  let frame = null;
  let ready = false;

  function setNote(text) {
    if (!note) return;
    note.textContent = text || "";
    note.hidden = !text;
  }

  function showMessage(title, detail) {
    if (!empty) return;
    empty.innerHTML = "";
    const h = document.createElement("div");
    h.style.cssText = "font-size:14px;color:#cfe6dc;margin-bottom:6px;";
    h.textContent = title;
    const p = document.createElement("div");
    p.textContent = detail || "";
    empty.append(h, p);
    empty.classList.remove("hidden");
  }

  function mount() {
    if (frame) return;
    frame = document.createElement("iframe");
    frame.id = "worldFrame";
    frame.src = currentUrl;
    frame.title = "CEO of My Life — the world";
    // NOT "pointer-lock" (2026-09-04): Chrome logs "Unrecognized feature: 'pointer-lock'"
    // because it never shipped that Permissions Policy — the Keyboard/Pointer Lock
    // permission was trialled and dropped (developer.chrome.com/blog/keyboard-lock-pointer-lock-permission).
    // Pointer lock still works: the world calls requestPointerLock() itself on a click.
    frame.allow = "fullscreen";
    frame.setAttribute("loading", "eager");
    frame.addEventListener("load", () => {
      ready = true;
      empty?.classList.add("hidden");
      setNote(pendingNote);
      if (pendingNote) setTimeout(() => setNote(""), 9000);
      pendingNote = "";
    });
    holder.appendChild(frame);
  }

  // Is the world actually up?
  //
  // The first version asked with a cross-origin `fetch(..., {mode:'no-cors'})`
  // and treated a throw as "world is down". That reported John's world dead
  // while it was demonstrably serving — some browsers (and this app's own
  // preview pane) block localhost XHR outright, so the probe was measuring the
  // browser, not the server. A probe that can be wrong about the thing it
  // probes is worse than no probe.
  //
  // So: mount the world and let IT answer. Its own load event is ground truth;
  // silence past a deadline is the only thing reported as trouble, and even
  // then the frame is left in place in case it is merely slow.
  const LOAD_DEADLINE_MS = 12000;
  let deadline = null;

  function offerRetry() {
    if (!empty || document.getElementById("worldRetry")) return;
    const retry = document.createElement("button");
    retry.id = "worldRetry";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.style.cssText = "margin-top:10px;pointer-events:auto;padding:8px 14px;border:0;border-radius:6px;background:#8edbb8;color:#07100d;font-weight:700;cursor:pointer;";
    retry.addEventListener("click", () => {
      empty.innerHTML = "";
      frame?.remove();
      frame = null;
      ready = false;
      check();
    });
    empty.appendChild(retry);
  }

  async function check() {
    if (ready) return;
    showMessage("Checking your world…", `${WORLD_ORIGIN}`);
    // Ask OUR OWN server whether the world is up. It sits on the same machine
    // with no CORS and nothing to block it — unlike the page, which cannot be
    // trusted here: a cross-origin fetch gets blocked, and an iframe's `load`
    // event fires even for Chrome's own "frame failed" error page. Both of
    // those shipped today and both lied in opposite directions.
    let health = null;
    try {
      health = await fetch("/api/v17/world-health", { cache: "no-store" }).then((r) => r.json());
    } catch (_) { /* our own server is unreachable; fall through to mounting */ }

    if (health && health.up === false) {
      showMessage(
        "Your world isn't running.",
        health.hint || `Start ${WORLD_ORIGIN} with RESTART-MY-OFFICE.bat, then click Retry.`,
      );
      offerRetry();
      return;
    }

    showMessage("Opening your world…", `${WORLD_ORIGIN} — the tower, the grounds, everything you've built.`);
    mount();
    clearTimeout(deadline);
    deadline = setTimeout(() => {
      if (ready) return;
      showMessage("Your world is taking a while…", "It may still be starting. Give it a moment, or Retry.");
      offerRetry();
    }, LOAD_DEADLINE_MS);
  }

  // "Walk in" now just focuses the world; the world owns its own controls.
  enterBtn?.addEventListener("click", () => {
    if (!ready) { check(); return; }
    frame?.focus();
    setNote("Click inside the world to look around · WASD to move · Esc to release the mouse.");
    setTimeout(() => setNote(""), 6000);
  });

  // ─── The hook the chat panel calls (unchanged shape) ─────────────────────
  //
  // These are deliberately honest no-ops for now. The session's own meshes are
  // not in the world yet — writing scene.json from a session is the next slice —
  // and claiming otherwise would be the "fake progress" this slice removed.
  // Swap the pane to another place (the review garage) or back to the front gate.
  function goTo(url) {
    if (currentUrl === url && ready) { frame?.focus(); return; }
    currentUrl = url;
    frame?.remove(); frame = null; ready = false;
    if (empty) empty.innerHTML = "";
    check();
  }

  window.LRWorld = {
    attach() { check(); },
    goToGarage() { pendingNote = "The garage ahead of you. Walk up and the door rolls up. Left-click ✓ approve · right-click ✗ no · WASD to move, click to look."; goTo(GARAGE_URL); },
    goHome() { goTo(WORLD_URL); },
    atGarage() { return currentUrl === GARAGE_URL; },
    beginBuild() {
      check();
      setNote("Building. Finished props land in the warehouse; placing them in the world is the next step.");
    },
    onObjectReady() { /* nothing to stream into the world yet */ },
    refreshScene() {
      // The world hot-reloads its own scene.json, so a finished build shows up
      // without this page doing anything.
    },
  };

  check();
})();
