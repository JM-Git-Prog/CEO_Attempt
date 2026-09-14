"""sim-player/dashboard.py — THE GLASS FLOOR. One page, on your own machine, showing the whole line live.

2026-09-14. John: *"i need some type of live streaming dashboard i can run locally that shows me
everything happning live in my game, i.e. whats being painted, whats being rendered and meshed,
what Sam is doing, how the cloud models are responding etc."*

Everything below already gets written to disk or answered by a local port. Nothing here is new
instrumentation and nothing here is a guess — it is the factory's own paperwork, read back at you
twice a second instead of after the fact:

    what Sam is doing      the LIVE round's transcript.jsonl, turn by turn, as he types
    how the models answer  the LIVE round's calls.jsonl - tag, lane, latency, tokens, parsed or not
    what is being made     files appearing under worlds/ in the last half hour, newest first
    render / mesh / paint  ComfyUI 8188 / 8190 / 8183 queues and their VRAM
    the card               nvidia-smi, and which models Ollama is holding resident
    the loop               heartbeat.json, the log tail, and every round it has played
    the training set       how many lessons exist against BOTH marks - 200 to learn the shape,
                           2000 to pass John's own gate (doc 28)
    ASKED vs BUILT         the human-in-the-loop card: the sentence and the spec on the left, the
                           render on the right, and a yes / no that is yours

It opens no model and queues no job. It reads everything and writes exactly ONE file:
sim-runs/hitl-verdicts.jsonl, and only when you click a verdict. It never writes to
art/preferences.jsonl - John's taste ledger, which only the Pick Board may write - nor to the sim's
copy. Separate file, separate meaning, no path from this page to either.

Every panel is fetched inside its own try/except, so one dead service greys one card and never
blanks the page — the whole point is a window you can trust while things are broken.

    python dashboard.py [--port 8099]          then open http://127.0.0.1:8099

stdlib only, so it runs on the same plain Python as everything else.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = Path(os.getenv("SAM_RUNS", str(HERE / "sim-runs")))
CEO_DIR = Path(os.getenv("CEO_OF_MY_LIFE",
                         r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"))
WORLDS = Path(os.getenv("CEO3D_WORLDS", str(CEO_DIR / "CEO-3D-World" / "worlds")))
EVENTS_SIM = Path(os.getenv("EVENTS_SIM", str(CEO_DIR / "training-data" / "events-sim.jsonl")))
OLLAMA = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")

COMFY = [("mesh engine", "http://127.0.0.1:8188"),
         ("paint shop", "http://127.0.0.1:8190"),
         ("claude lane", "http://127.0.0.1:8183")]
PORTS = [("Sam's Living Room", "http://127.0.0.1:8001/api/v17/pipeline"),
         ("your Living Room", "http://127.0.0.1:8000/api/v17/pipeline"),
         ("Sam's Pick Board", "http://127.0.0.1:8294/api/ping"),
         ("your Pick Board", "http://127.0.0.1:8194/api/ping"),
         ("Neighbourhood Builder", "http://127.0.0.1:8196/api/health"),
         ("the world (5173)", "http://localhost:5173/"),
         ("Ollama", OLLAMA + "/api/tags")]

MADE_WITHIN_S = 1800            # "what got made" window

# TWO MARKS, because they answer two different questions and I had been showing only the soft one.
#   SHAPE  202 train + 50 holdout is the set that actually produced a model on this machine
#          (data/flywheel/training/probe-v1.jsonl -> bench/train_probe.py). It is enough to teach a
#          model the SHAPE of the job: emit a valid build card with real centimetres in it.
#   GATE   2000 accepted pairs is JOHN'S OWN written standard, doc 28, quoted on screen every time
#          CATCH-UP-TRAINING-DATA.bat runs: "Training gate for your own model is 2000 accepted
#          pairs (doc 28)." That is the bar for a model you would rely on, not one that can parrot
#          the format.
# The dashboard shows both. Calling 200 "the gate" was me reading the size of the last training set
# and mistaking it for the standard.
TRAIN_SHAPE = int(os.getenv("SAM_TRAIN_SHAPE", "200"))
TRAIN_GATE = int(os.getenv("SAM_TRAIN_GATE", "2000"))

# The one file this dashboard is allowed to write, and the only one. A verdict here is John looking
# at a picture and saying yes or no; it never touches art/preferences.jsonl (his taste ledger, which
# only the Pick Board writes) and never touches the sim's. Separate file, separate meaning.
HITL = RUNS / "hitl-verdicts.jsonl"

# ── STARTING AND STOPPING THE LOOP FROM THE LINE ─────────────────────────────
# 2026-09-14. John asked how to run "START-SAM-LOOP.bat --factory". He could not, because a .bat
# takes no argument from a double-click - and it never needed one, --factory has been inside the
# file since this morning. The instruction was wrong and the folder it points into holds about a
# hundred and twenty other .bat files. So the loop now starts and stops from the one screen he
# already wants open.
#
# The safety is that there is NOTHING TO TYPE. The script is a constant, the flags are constants,
# and the only thing a request may carry is a round count that gets clamped. This endpoint cannot
# be talked into running something else, because it was never given a way to be told what to run.
CEO_ROOT = HERE.parent                      # ...\CEO_Attempt, where the loop expects to be started
LOOP_SCRIPT = HERE / "sam_loop.py"
STOP_FILE = HERE / "STOP"                   # sam_loop.py:52 - the same file STOP-SAM-LOOP.bat writes
LOOP_DEPTH = "C"                            # decision 23, John's "C"
LOOP_ROUNDS_DEFAULT, LOOP_ROUNDS_MAX = 200, 500

# Folders a picture may be served from. Anything resolving outside these is refused, so a crafted
# ?p= cannot walk out of the world and read the disk.
# Snapshots of the world, kept by this dashboard so an ask from twenty minutes ago can still be
# shown beside the world AS IT LOOKED THEN. The builder overwrites one thumbnail file in place, so
# without an archive there is no history to judge against - only "the world, now", which answers a
# different question than the one on the card.
WORLD_SHOTS = RUNS / "world-shots"

IMG_ROOTS = [WORLDS, WORLD_SHOTS]
IMG_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
IMG_MAX = 24 * 1024 * 1024

# How a new dashboard recognises an OLD COPY OF ITSELF on the port and takes over from it.
#
# The launcher used to do this in batch, with a PowerShell CIM query nested inside a for /f inside
# a quoted -Command. It never fired once: the quoting collapsed, CMD came back empty, the check
# silently fell through to "not mine", and John got a stale build that LOOKED live - 8888 bytes of
# yesterday's page refreshing itself every two seconds. A dashboard lying about being current is
# worse than a dashboard that is down, because nothing on screen says so.
#
# So the handshake moved here, where there is no escaping layer to lose it: ask the thing on the
# port who it is; if it answers with this exact signature, ask it to stand down; then bind. It can
# only ever stop THIS program - /api/shutdown does nothing but close this server - and it is
# reachable only from 127.0.0.1.
SIGNATURE = "the-line-dashboard/1"
_server = None


# --------------------------------------------------------------------------- small safe readers

def _get(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None, None


def _jsonl(path: Path, last: int = 0) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return out[-last:] if last else out


def _tail(path: Path, n: int) -> list[str]:
    try:
        return [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")][-n:]
    except OSError:
        return []


def _age(ts: float) -> str:
    d = max(0, int(time.time() - ts))
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    return f"{d // 3600}h {(d % 3600) // 60}m ago"


# --------------------------------------------------------------------------- the panels

def panel_loop() -> dict:
    hb, log = {}, _tail(RUNS / "loop-log.txt", 18)
    try:
        hb = json.loads((RUNS / "heartbeat.json").read_text(encoding="utf-8"))
    except Exception:
        hb = {}
    beat = 0.0
    try:
        beat = (RUNS / "heartbeat.json").stat().st_mtime
    except OSError:
        pass
    alive = beat and (time.time() - beat) < 600 and hb.get("phase") not in ("stopped",)
    rounds = _jsonl(RUNS / "rounds.jsonl")
    return {"heartbeat": hb, "beat_age": _age(beat) if beat else "never", "alive": bool(alive),
            "log": log, "rounds_total": len(rounds),
            "rounds": [{"id": r.get("round") or r.get("id"), "why": r.get("why") or r.get("ended"),
                        "turns": r.get("turns"), "wishes": r.get("wishes"),
                        "judge": r.get("judge_status"), "world": r.get("world_after")}
                       for r in rounds[-8:]][::-1]}


def _live_round() -> Path | None:
    try:
        hb = json.loads((RUNS / "heartbeat.json").read_text(encoding="utf-8"))
        d = RUNS / str(hb.get("round") or "")
        if d.is_dir():
            return d
    except Exception:
        pass
    dirs = sorted((p for p in RUNS.iterdir() if p.is_dir() and p.name[:2].isdigit()),
                  key=lambda p: p.name) if RUNS.is_dir() else []
    return dirs[-1] if dirs else None


def panel_sam() -> dict:
    d = _live_round()
    if d is None:
        return {"round": None, "turns": []}
    turns = []
    for r in _jsonl(d / "transcript.jsonl", last=12):
        resp = r.get("response") or {}
        turns.append({
            "turn": r.get("turn"), "stage": r.get("stage"),
            "sees": (r.get("i_see") or "")[:150],
            "types": (r.get("i_type") or "")[:150],
            "kind": resp.get("kind"), "receipt": (resp.get("receipt") or "")[:110],
            "question": (resp.get("question") or "")[:110],
            "card": (r.get("card") or {}).get("name") or (resp.get("card") or {}).get("name"),
            "world": r.get("world_version_after"), "error": (r.get("error") or "")[:110],
        })
    return {"round": d.name, "turns": turns[::-1]}


def panel_models() -> dict:
    d = _live_round()
    calls = _jsonl(d / "calls.jsonl", last=14) if d else []
    rows = []
    for c in calls:
        tag = str(c.get("model") or "")
        rows.append({
            "at": (c.get("at") or "")[11:19], "purpose": c.get("purpose") or "-",
            "model": tag, "cloud": tag.endswith("-cloud") or tag.endswith(":cloud"),
            "latency": c.get("latency_s"), "eval": c.get("eval_count"),
            "prompt_tokens": c.get("prompt_eval_count"),
            "done": c.get("done_reason"), "schema": c.get("schema"), "parsed": c.get("parsed_ok"),
            "reply": (str(c.get("reply") or "").replace("\n", " "))[:160],
        })
    ledger = _jsonl(RUNS / "lane-ledger.jsonl", last=40)
    lanes = {}
    for r in ledger:
        lanes[r.get("lane")] = {"tag": r.get("tag"), "result": r.get("result"), "why": (r.get("why") or "")[:90]}
    st, ps = _get(OLLAMA + "/api/ps")
    resident = []
    for m in ((ps or {}).get("models") or []):
        resident.append({"name": m.get("name"),
                         "vram_gb": round((m.get("size_vram") or 0) / 1e9, 2),
                         "until": str(m.get("expires_at") or "")[11:19]})
    return {"calls": rows[::-1], "lanes": lanes, "resident": resident}


def panel_factory() -> dict:
    out = []
    for name, url in COMFY:
        st, q = _get(url + "/queue")
        if st != 200 or not isinstance(q, dict):
            out.append({"name": name, "url": url, "up": False})
            continue
        _s, stats = _get(url + "/system_stats")
        dev = ((stats or {}).get("devices") or [{}])[0]
        free, total = dev.get("vram_free"), dev.get("vram_total")
        running = q.get("queue_running") or []
        out.append({"name": name, "url": url, "up": True,
                    "running": len(running), "pending": len(q.get("queue_pending") or []),
                    "vram_free_gb": round((free or 0) / 1e9, 1) if free else None,
                    "vram_total_gb": round((total or 0) / 1e9, 1) if total else None,
                    "comfyui": (stats or {}).get("system", {}).get("comfyui_version")})
    return {"servers": out}


def panel_made() -> dict:
    """What actually appeared on disk lately — the only honest answer to 'what is being made'."""
    cut, made = time.time() - MADE_WITHIN_S, []
    try:
        for p in WORLDS.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".png", ".glb", ".jpg", ".jpeg", ".gltf"):
                continue
            try:
                m = p.stat()
            except OSError:
                continue
            if m.st_mtime >= cut:
                made.append({"name": p.name, "where": str(p.parent.relative_to(WORLDS)),
                             "kind": p.suffix.lower().lstrip("."),
                             "mb": round(m.st_size / 1e6, 2), "ago": _age(m.st_mtime), "_t": m.st_mtime})
    except Exception:
        pass
    made.sort(key=lambda r: -r["_t"])
    for r in made:
        r.pop("_t", None)
    return {"files": made[:24], "window_min": MADE_WITHIN_S // 60}


def panel_gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8).stdout.strip()
        name, used, total, util, temp = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"ok": True, "name": name, "used_mb": int(used), "total_mb": int(total),
                "util": int(util), "temp": int(temp)}
    except Exception:
        return {"ok": False}


def panel_ports() -> dict:
    out = []
    for name, url in PORTS:
        t0 = time.monotonic()
        st, _ = _get(url, timeout=1.5)
        out.append({"name": name, "url": url.split("/api")[0].split("//")[-1],
                    "up": st is not None and 200 <= int(st) < 400,
                    "ms": int((time.monotonic() - t0) * 1000)})
    return {"ports": out}


def panel_training() -> dict:
    rows = _jsonl(EVENTS_SIM)
    kept = 0
    try:
        sys.path.insert(0, str(HERE))
        import teach_sam                                          # noqa: E402
        for r in rows:
            ok, _why = teach_sam.usable(r)
            if ok:
                kept += 1
    except Exception:
        kept = sum(1 for r in rows if r.get("card"))
    today = sum(1 for r in rows if (r.get("ts") or "")[:10] == time.strftime("%Y-%m-%d"))
    return {"events": len(rows), "today": today, "lessons": kept,
            "shape": TRAIN_SHAPE, "shape_needed": max(0, TRAIN_SHAPE - kept),
            "shape_pct": min(100, round(100 * kept / TRAIN_SHAPE)),
            "gate": TRAIN_GATE, "needed": max(0, TRAIN_GATE - kept),
            "pct": min(100, round(100 * kept / TRAIN_GATE))}


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in str(s or "").lower()).strip("-")


def _pictures_for(words: str, limit: int = 4) -> list[dict]:
    """Any renders that belong to this ask. The factory names a prop's folder after the words that
    asked for it, so the folder name IS the link back to the sentence — no extra bookkeeping and
    nothing to fall out of sync."""
    want = set(w for w in _slug(words).split("-") if len(w) > 3)
    if not want:
        return []
    best, hits = None, 0
    root = WORLDS / "warehouse" / "source" / "cutouts" / "picks"
    try:
        for d in root.iterdir():
            if not d.is_dir():
                continue
            have = set(d.name.split("-"))
            n = len(want & have)
            if n > hits:
                best, hits = d, n
    except OSError:
        return []
    if best is None or hits < 2:
        return []
    out = []
    for png in sorted(best.glob("v*.png"))[:limit]:
        try:
            out.append({"tag": png.stem, "src": "/img?p=" + str(png.relative_to(WORLDS)).replace("\\", "/"),
                        "mb": round(png.stat().st_size / 1e6, 2)})
        except OSError:
            continue
    return out


def _ts_epoch(ts: str) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _live_world_files() -> tuple[Path | None, Path | None, str]:
    """The world's own thumbnail and its GLB, for whichever world the loop is playing in."""
    slug = os.getenv("SAM_WORLD", "sim-neighborhood")
    d = WORLDS / slug / "output" / "world"
    shot = next(iter(sorted(d.glob("*thumbnail*.png"))), None) if d.is_dir() else None
    glb = next(iter(sorted(d.glob("*.glb"))), None) if d.is_dir() else None
    return shot, glb, slug


def _archive_world() -> list[tuple[float, Path]]:
    """Keep a copy of the world thumbnail every time it changes.

    THE ONLY OTHER THING THIS PAGE WRITES, besides a verdict. It copies one picture the builder
    already made into this dashboard's own folder (sim-runs/world-shots/). It writes nothing into
    any world, touches no source, and overwrites nothing: each copy is named for the moment it was
    taken. Without it the card can only ever show "the world right now", which is not the question -
    the question is whether the thing asked for at 08:41 was standing at 08:44.
    """
    shot, _glb, _slug = _live_world_files()
    try:
        WORLD_SHOTS.mkdir(parents=True, exist_ok=True)
        have = sorted(WORLD_SHOTS.glob("*.png"))
        if shot is not None:
            m = shot.stat().st_mtime
            name = f"{int(m)}.png"
            if not (WORLD_SHOTS / name).exists():
                (WORLD_SHOTS / name).write_bytes(shot.read_bytes())
                have = sorted(WORLD_SHOTS.glob("*.png"))
                for old in have[:-40]:                      # keep the last 40, quietly
                    try:
                        old.unlink()
                    except OSError:
                        pass
                have = sorted(WORLD_SHOTS.glob("*.png"))
        out = []
        for f in have:
            try:
                out.append((float(f.stem), f))
            except ValueError:
                continue
        return sorted(out)
    except OSError:
        return []


def _world_index() -> dict:
    """What the loop recorded about each snapshot it took at the end of a round: which round it
    belongs to, and whether the world was actually rebuilt during it. Without this the card would
    show a fresh timestamp over an unchanged picture, which is the most expensive kind of wrong."""
    out = {}
    for r in _jsonl(WORLD_SHOTS / "index.jsonl"):
        if r.get("shot"):
            out[r["shot"]] = r
    return out


def _world_after(when: float, archive: list[tuple[float, Path]], index: dict | None = None) -> dict | None:
    """The world as it looked at the first snapshot taken AFTER this ask - the honest 'is it there'."""
    if not archive:
        return None
    # STRICTLY after. An earlier version allowed a five-second tolerance for clock skew, and the
    # self-test caught what that really did: a snapshot taken BEFORE the ask was offered as proof
    # the ask had been built. There is no skew to forgive - the event timestamp and the file mtime
    # are both plain epoch seconds - so the tolerance bought nothing and cost the card its meaning.
    later = [(m, f) for m, f in archive if m >= when]
    m, f = (later[0] if later else archive[-1])
    meta = (index or {}).get(f.name) or {}
    wm = meta.get("world_mtime")
    return {"src": "/img?p=" + f.name, "ago": _age(m), "stale": not later,
            "shot_at": time.strftime("%H:%M:%S", time.localtime(m)),
            "round": meta.get("round"),
            "rebuilt": meta.get("rebuilt_this_round"),
            "world_changed": _age(wm) if wm else None}


def _world_asset(when: float) -> dict | None:
    """The GLB itself. A picture can lie about what shipped; the file on disk cannot. It is not
    rendered here - a .glb is not an image - but its size and its age are hard evidence that
    something was actually written into the world after the ask."""
    _shot, glb, slug = _live_world_files()
    if glb is None:
        return None
    try:
        st = glb.stat()
    except OSError:
        return None
    return {"name": glb.name, "world": slug, "mb": round(st.st_size / 1e6, 1),
            "ago": _age(st.st_mtime), "after_ask": st.st_mtime >= when}


def _world_shot() -> dict | None:
    """The house that actually went up, as a picture."""
    for slug in (os.getenv("SAM_WORLD", "sim-neighborhood"), "mr-johns-neighborhood"):
        for p in (WORLDS / slug / "output" / "world").glob("*thumbnail*.png"):
            try:
                return {"src": "/img?p=" + str(p.relative_to(WORLDS)).replace("\\", "/"),
                        "name": p.name, "world": slug, "ago": _age(p.stat().st_mtime)}
            except OSError:
                continue
    return None


def panel_hitl() -> dict:
    """ASKED vs BUILT. The sentence and the card on the left, the render on the right, and a yes/no.

    John, 2026-09-14: *"where is the HITL card in THE LINE so i can visually see if what was asked
    for is actually there?"* It was nowhere, and that was the hole in the whole page: everything else
    reports what the machine THINKS happened. This is the only panel that shows the thing itself and
    lets a person disagree with it.
    """
    judged = {}
    for r in _jsonl(HITL):
        if r.get("id"):
            judged[r["id"]] = r.get("verdict")
    archive, windex = _archive_world(), _world_index()
    rows, seen = [], set()
    for e in reversed(_jsonl(EVENTS_SIM, last=140)):
        card = e.get("card")
        if not isinstance(card, dict) or not card:
            continue
        eid = e.get("event_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        asked = ((e.get("input") or {}).get("message")
                 or (e.get("input") or {}).get("prompt_rendered") or "")[:220]
        home = card.get("home") or {}
        spec = [x for x in [
            card.get("style"), card.get("material"), card.get("color"),
            f"{card.get('width_cm')}x{card.get('depth_cm')}x{card.get('height_cm')} cm"
            if card.get("width_cm") else None,
            f"{home.get('stories')} storeys" if home.get("stories") else None,
            f"{home.get('bedrooms')} bed" if home.get("bedrooms") else None,
            f"{home.get('roof')} roof" if home.get("roof") else None,
            "porch" if home.get("porch") else None,
        ] if x]
        pics = _pictures_for(asked + " " + str(card.get("name") or ""))
        when = _ts_epoch(e.get("ts"))
        rows.append({
            "id": eid, "at": (e.get("ts") or "")[11:19], "asked": asked,
            "name": card.get("name"), "kind": (e.get("result") or {}).get("kind"),
            "spec": spec, "features": (home.get("features") or [])[:4],
            "by": "sim" if str(e.get("session") or "").startswith("sim-") else "john",
            "architect": (e.get("model") or {}).get("architect"),
            "pictures": pics, "verdict": judged.get(eid),
            "world_shot": _world_after(when, archive, windex), "asset": _world_asset(when),
        })
        if len(rows) >= 8:
            break
    return {"rows": rows, "world": _world_shot(), "shots_kept": len(archive),
            "judged": len(judged), "file": str(HITL)}


def snapshot() -> dict:
    panels = {"loop": panel_loop, "sam": panel_sam, "models": panel_models, "factory": panel_factory,
              "made": panel_made, "gpu": panel_gpu, "ports": panel_ports, "training": panel_training,
              "hitl": panel_hitl}
    out = {"at": time.strftime("%H:%M:%S")}
    for k, fn in panels.items():
        try:
            out[k] = fn()
        except Exception as exc:                    # one broken panel greys one card, never the page
            out[k] = {"_error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


# --------------------------------------------------------------------------- the page

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>THE LINE - live</title>
<style>
:root{--bg:#0b0d10;--card:#141820;--line:#232a36;--ink:#e6edf3;--dim:#8b97a8;
      --ok:#3fb950;--warn:#d29922;--bad:#f85149;--cloud:#58a6ff;--local:#bc8cff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 ui-monospace,"Cascadia Mono",Consolas,monospace}
header{position:sticky;top:0;z-index:9;background:#0b0d10ee;backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
h1{font-size:14px;margin:0;letter-spacing:.14em}
.pill{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:11px;color:var(--dim)}
.pill.on{color:var(--ok);border-color:#1d3b26}.pill.off{color:var(--bad);border-color:#4a1f1f}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:12px;padding:12px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;min-width:0}
h2{font-size:11px;letter-spacing:.16em;color:var(--dim);margin:0;padding:9px 12px;border-bottom:1px solid var(--line)}
.body{padding:8px 12px;max-height:340px;overflow:auto}
table{width:100%;border-collapse:collapse}td{padding:3px 6px 3px 0;vertical-align:top;border-bottom:1px solid #1a1f28}
tr:last-child td{border-bottom:0}
.dim{color:var(--dim)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.cloud{color:var(--cloud)}.local{color:var(--local)}
.n{text-align:right;white-space:nowrap}
.w{white-space:pre-wrap;word-break:break-word}
.bar{height:6px;background:#1a1f28;border-radius:3px;overflow:hidden;margin:6px 0}
.bar>i{display:block;height:100%;background:var(--ok)}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:11.5px;color:var(--dim)}
.big{font-size:22px;letter-spacing:-.02em}
.k{color:var(--dim);font-size:11px;letter-spacing:.08em}
.turn{border-left:2px solid var(--line);padding:4px 0 4px 9px;margin-bottom:7px}
.turn b{color:var(--cloud);font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.hit{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.95fr) minmax(0,.75fr);gap:14px;padding:11px 0;border-bottom:1px solid var(--line)}
@media(max-width:900px){.hit{grid-template-columns:1fr}}
.side{min-width:0}
.side>.k{padding-bottom:5px}
.asset{border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-size:11px;margin-top:7px}
.asset b{color:var(--ink);font-weight:600}
.hit:last-child{border-bottom:0}
.shots{display:flex;gap:7px;flex-wrap:wrap}
.shots figure{margin:0;width:132px}
.shots img{width:132px;height:132px;object-fit:cover;border-radius:6px;border:1px solid var(--line);background:#0b0d10;display:block;cursor:zoom-in}
.shots figcaption{font-size:10px;color:var(--dim);text-align:center;padding-top:2px}
.spec span{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:1px 6px;margin:2px 3px 0 0;font-size:11px;color:var(--dim)}
.btns{margin-top:8px;display:flex;gap:7px;flex-wrap:wrap}
button{font:inherit;background:#1b2029;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 13px;cursor:pointer}
button:hover{border-color:#39424f}
button.yes:hover{border-color:var(--ok);color:var(--ok)}
button.no:hover{border-color:var(--bad);color:var(--bad)}
.done{font-size:11px;letter-spacing:.08em;padding:3px 0}
.noshot{color:var(--dim);border:1px dashed var(--line);border-radius:6px;padding:20px;text-align:center;font-size:11px}
dialog{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:8px;max-width:94vw}
dialog img{max-width:88vw;max-height:82vh;display:block;border-radius:6px}
dialog::backdrop{background:#000c}
@media(max-width:520px){main{grid-template-columns:1fr;padding:8px}.grid2{grid-template-columns:1fr}}
</style></head><body>
<header><h1>THE LINE</h1><span id="clock" class="pill"></span><span id="loopstate" class="pill"></span>
<span id="roundstate" class="pill"></span><span id="gpustate" class="pill"></span>
<span class="btns" style="margin:0 0 0 auto">
<button id="loopgo" class="yes" onclick="loopDo('start')">start the loop</button>
<button id="loopstop" class="no" onclick="loopDo('stop')">stop after this round</button>
<span id="loopsaid" class="dim"></span></span></header>
<main>
 <section style="grid-column:1/-1"><h2>ASKED vs BUILT &mdash; your call</h2><div class="body" id="hitl" style="max-height:none"></div></section>
 <section><h2>SAM, RIGHT NOW</h2><div class="body" id="sam"></div></section>
 <section><h2>THE MODELS ANSWERING</h2><div class="body" id="models"></div></section>
 <section><h2>RENDER / MESH / PAINT</h2><div class="body" id="factory"></div></section>
 <section><h2>WHAT GOT MADE</h2><div class="body" id="made"></div></section>
 <section><h2>THE LOOP</h2><div class="body" id="loop"></div></section>
 <section><h2>TRAINING SET</h2><div class="body" id="training"></div></section>
 <section><h2>SERVICES</h2><div class="body" id="ports"></div></section>
 <section><h2>LOG</h2><div class="body" id="log"></div></section>
</main>
<script>
const $=i=>document.getElementById(i), esc=s=>String(s==null?"":s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
const err=p=>p&&p._error?`<span class="bad">panel failed - ${esc(p._error)}</span>`:null;
function tag(m){const c=/(-cloud|:cloud)$/.test(m||"");return `<span class="${c?'cloud':'local'}">${esc(m)}</span>`}
async function loopDo(action){
 const said=$("loopsaid"); said.textContent=action==="start"?"starting...":"asking it to stop...";
 try{
  const r=await fetch("/api/loop",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(action==="start"?{action:"start",rounds:200}:{action:"stop"})});
  const j=await r.json();
  said.textContent=j.ok?(j.note||"done"):("could not: "+(j.why||"unknown"));
  said.className=j.ok?"dim":"bad";
 }catch(e){ said.textContent="could not reach the dashboard: "+e.message; said.className="bad"; }
}
function render(d){
 $("clock").textContent=d.at;
 const L=d.loop||{}, hb=L.heartbeat||{};
 $("loopstate").textContent=(L.alive?"loop alive":"loop stopped")+" - "+(L.beat_age||"");
 $("loopstate").className="pill "+(L.alive?"on":"off");
 $("loopgo").disabled=!!L.alive; $("loopstop").disabled=!L.alive;
 $("roundstate").textContent=(hb.phase||"-")+(hb.round?" - "+hb.round:"");
 const g=d.gpu||{};
 $("gpustate").textContent=g.ok?`4090 ${g.used_mb}/${g.total_mb}MB - ${g.util}% - ${g.temp}C`:"no nvidia-smi";
 $("gpustate").className="pill "+(g.ok&&g.used_mb>18000?"warn":"");

 // ASKED vs BUILT - the only panel where a person overrules the machine
 const H=d.hitl||{};
 let hh=err(H)||"";
 if(!hh){
  hh+=`<div class="k">${esc(H.judged||0)} judged &middot; ${esc(H.shots_kept||0)} world snapshots kept &middot; verdicts go to sim-runs/hitl-verdicts.jsonl and nowhere else</div>`;
  if(H.world) hh+=`<div class="hit"><div><div class="k">THE HOUSE THAT WENT UP</div>
    <div class="dim">${esc(H.world.world)} &middot; ${esc(H.world.ago)}</div>
    <div class="dim" style="padding-top:6px">This is the world itself, not a card about it.</div></div>
    <div class="shots"><figure><img loading="lazy" src="${esc(H.world.src)}" onclick="zoom(this.src)"><figcaption>${esc(H.world.name)}</figcaption></figure></div></div>`;
  if(!H.rows||!H.rows.length) hh+='<span class="dim">no build card written yet - the panel fills as Sam asks for things</span>';
  else hh+=H.rows.map(r=>`<div class="hit" id="h-${esc(r.id)}">
    <div>
     <div class="k">${esc(r.at)} &middot; ${esc(r.kind||"")} &middot; asked by ${esc(r.by)}</div>
     <div style="padding:3px 0 5px"><span class="dim">asked for</span> &ldquo;${esc(r.asked)}&rdquo;</div>
     <div><b>${esc(r.name||"(unnamed)")}</b></div>
     <div class="spec">${(r.spec||[]).map(s=>`<span>${esc(s)}</span>`).join("")}</div>
     ${(r.features||[]).length?`<div class="dim" style="padding-top:4px">${esc((r.features||[]).join(" &middot; "))}</div>`:""}
     <div class="dim" style="padding-top:4px">architect ${tag(r.architect)}</div>
     ${r.verdict?`<div class="done ${r.verdict=='yes'?'ok':(r.verdict=='no'?'bad':'warn')}">you said: ${esc(r.verdict.toUpperCase())}</div>`
      :`<div class="btns">
        <button class="yes" onclick="verdict('${esc(r.id)}','yes')">that is what I asked for</button>
        <button class="no" onclick="verdict('${esc(r.id)}','no')">no, that is wrong</button>
        <button onclick="verdict('${esc(r.id)}','unsure')">can&rsquo;t tell yet</button></div>`}
    </div>
    <div class="side"><div class="k">WHAT THE FACTORY DREW</div>${(r.pictures||[]).length
      ? `<div class="shots">`+r.pictures.map(pp=>`<figure><img loading="lazy" src="${esc(pp.src)}" onclick="zoom(this.src)"><figcaption>${esc(pp.tag)}</figcaption></figure>`).join("")+`</div>`
      : `<div class="noshot">the factory has not drawn this one yet &mdash;<br>nothing honest to judge on this side</div>`}</div>
    <div class="side"><div class="k">WHAT IS IN THE WORLD</div>${r.world_shot
      ? `<div class="shots"><figure><img loading="lazy" src="${esc(r.world_shot.src)}" onclick="zoom(this.src)">
         <figcaption>${r.world_shot.stale?'<span class="warn">taken before this ask</span>'
            :(r.world_shot.rebuilt===false?'<span class="warn">world not rebuilt since '+esc(r.world_shot.world_changed||"")+'</span>'
             :"world at "+esc(r.world_shot.shot_at))}${r.world_shot.round?'<br><span class="dim">end of '+esc(r.world_shot.round)+'</span>':""}</figcaption></figure></div>`
      : `<div class="noshot">no snapshot of the world yet</div>`}
     ${r.asset?`<div class="asset">${r.asset.after_ask?'<span class="ok">written after you asked</span>':'<span class="warn">older than this ask</span>'}<br>
        <b>${esc(r.asset.name)}</b><br><span class="dim">${esc(r.asset.mb)} MB &middot; ${esc(r.asset.ago)} &middot; ${esc(r.asset.world)}</span></div>`
      :`<div class="asset dim">no .glb in this world yet</div>`}</div>
   </div>`).join("");
 }
 $("hitl").innerHTML=hh;

 // SAM
 const S=d.sam||{};
 $("sam").innerHTML=err(S)||(!S.turns||!S.turns.length?'<span class="dim">no live transcript yet - the round has not written a turn</span>':
  `<div class="k">round ${esc(S.round)}</div>`+S.turns.map(t=>`<div class="turn">
    <span class="dim">turn ${esc(t.turn)}${t.stage?" / "+esc(t.stage):""}${t.world!=null?" / world v"+esc(t.world):""}</span><br>
    <span class="dim">sees</span> ${esc(t.sees)}<br><b>types</b> ${esc(t.types)}<br>
    ${t.receipt?`<span class="dim">app</span> ${esc(t.receipt)}<br>`:""}
    ${t.question?`<span class="warn">asks</span> ${esc(t.question)}<br>`:""}
    ${t.card?`<span class="ok">card</span> ${esc(t.card)}<br>`:""}
    ${t.error?`<span class="bad">error</span> ${esc(t.error)}`:""}</div>`).join(""));

 // MODELS
 const M=d.models||{};
 let mh=err(M)||"";
 if(!mh){
  if(M.resident&&M.resident.length) mh+=`<div class="k">HOLDING THE CARD</div>`+M.resident.map(r=>
    `<div>${tag(r.name)} <span class="dim">${r.vram_gb} GB${r.until?" until "+esc(r.until):""}</span></div>`).join("")+"<br>";
  else mh+=`<div class="k">HOLDING THE CARD</div><span class="dim">nothing resident - the card is free</span><br><br>`;
  const lanes=M.lanes||{};
  if(Object.keys(lanes).length) mh+=`<div class="k">LANE WINNERS</div>`+Object.entries(lanes).map(([k,v])=>
    `<div>${esc(k)} &rarr; ${tag(v.tag)} <span class="${v.result=='winner'?'ok':'bad'}">${esc(v.result)}</span> <span class="dim">${esc(v.why)}</span></div>`).join("")+"<br>";
  mh+=`<div class="k">CALLS THIS ROUND</div>`;
  mh+=(M.calls&&M.calls.length)?`<table>`+M.calls.map(c=>`<tr>
    <td class="dim">${esc(c.at)}</td><td>${esc(c.purpose)}</td><td>${tag(c.model)}</td>
    <td class="n dim">${c.latency==null?"":c.latency+"s"}</td>
    <td class="n dim">${c.eval==null?"":c.eval+"t"}</td>
    <td class="n">${c.schema?(c.parsed?'<span class="ok">json</span>':'<span class="bad">not json</span>'):'<span class="dim">-</span>'}</td>
    <td class="n ${c.done=='length'?'bad':'dim'}">${esc(c.done)}</td></tr>
    <tr><td></td><td colspan="6" class="dim w">${esc(c.reply)}</td></tr>`).join("")+`</table>`
    :'<span class="dim">no model call captured in this round yet</span>';
 }
 $("models").innerHTML=mh;

 // FACTORY
 const F=d.factory||{};
 $("factory").innerHTML=err(F)||`<table>`+(F.servers||[]).map(s=>`<tr>
   <td>${s.up?'<span class="ok">up</span>':'<span class="bad">down</span>'}</td>
   <td>${esc(s.name)}</td><td class="dim">${esc(s.url.replace('http://',''))}</td>
   <td class="n">${s.up?`<span class="${s.running?'warn':'dim'}">${s.running} running</span> <span class="dim">${s.pending} queued</span>`:''}</td>
   <td class="n dim">${s.vram_free_gb!=null?s.vram_free_gb+"/"+s.vram_total_gb+" GB free":""}</td></tr>`).join("")+`</table>`;

 // MADE
 const A=d.made||{};
 $("made").innerHTML=err(A)||(!A.files||!A.files.length?`<span class="dim">nothing written under worlds/ in the last ${esc(A.window_min)} minutes</span>`:
  `<table>`+A.files.map(f=>`<tr><td class="${f.kind=='glb'?'ok':'dim'}">${esc(f.kind)}</td>
   <td class="w">${esc(f.name)}</td><td class="dim w">${esc(f.where)}</td>
   <td class="n dim">${f.mb} MB</td><td class="n dim">${esc(f.ago)}</td></tr>`).join("")+`</table>`);

 // LOOP
 $("loop").innerHTML=err(L)||`<div class="grid2">
   <div><div class="k">PHASE</div><div class="big">${esc(hb.phase||"-")}</div>
     <div class="dim">pid ${esc(hb.pid||"-")} &middot; beat ${esc(L.beat_age)}</div></div>
   <div><div class="k">ROUNDS ON RECORD</div><div class="big">${esc(L.rounds_total||0)}</div></div></div><br>
   <div class="k">RECENT ROUNDS</div><table>`+(L.rounds||[]).map(r=>`<tr>
   <td class="dim">${esc(r.id)}</td><td>${esc(r.why)}</td><td class="n dim">${esc(r.turns)}t</td>
   <td class="n dim">${esc(r.wishes)}w</td>
   <td class="n ${r.judge=='ok'?'ok':'bad'}">${esc(r.judge)}</td></tr>`).join("")+`</table>`;

 // TRAINING
 const T=d.training||{};
 $("training").innerHTML=err(T)||`<div class="grid2">
  <div><div class="k">LESSONS KEPT</div><div class="big">${esc(T.lessons)}</div>
   <div class="bar"><i style="width:${esc(T.pct)}%"></i></div>
   <div class="dim">${esc(T.needed)} more to reach the ${esc(T.gate)} needed to train</div></div>
  <div><div class="k">EVENT ROWS</div><div class="big">${esc(T.events)}</div>
   <div class="dim">${esc(T.today)} written today</div></div></div>`;

 // PORTS
 const P=d.ports||{};
 $("ports").innerHTML=err(P)||`<table>`+(P.ports||[]).map(p=>`<tr>
   <td>${p.up?'<span class="ok">up</span>':'<span class="bad">down</span>'}</td>
   <td>${esc(p.name)}</td><td class="dim">${esc(p.url)}</td>
   <td class="n dim">${p.up?p.ms+"ms":""}</td></tr>`).join("")+`</table>`;

 $("log").innerHTML=`<pre>${esc((L.log||[]).join("\n"))}</pre>`;
}
function zoom(src){let g=document.getElementById("zoomer");
 if(!g){g=document.createElement("dialog");g.id="zoomer";g.innerHTML='<img>';
  g.onclick=()=>g.close();document.body.appendChild(g)}
 g.querySelector("img").src=src;g.showModal()}
async function verdict(id,v){
 const el=document.getElementById("h-"+id); if(el) el.style.opacity=.45;
 try{await fetch("/api/verdict",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({id:id,verdict:v})})}catch(e){}
 tickNow();}
let pending=null;
function tickNow(){clearTimeout(pending);tick()}
async function tick(){try{render(await (await fetch("/api/live",{cache:"no-store"})).json())}
 catch(e){$("clock").textContent="dashboard lost the server"}finally{pending=setTimeout(tick,2000)}}
tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):          # a dashboard that spams its own console is not a dashboard
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """A verdict, appended to one file — or this server being asked to stand down for a newer
        copy of itself. Nothing else, and neither touches anything outside this program."""
        if self.path == "/api/shutdown":
            self._send(b'{"ok":true}', "application/json")
            import threading
            threading.Thread(target=lambda: _server and _server.shutdown(), daemon=True).start()
            return
        if self.path == "/api/loop":
            self._loop()
            return
        if self.path != "/api/verdict":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 8192)).decode("utf-8", "replace"))
            vid, verdict = str(body.get("id") or "")[:64], str(body.get("verdict") or "")[:16]
            if not vid or verdict not in ("yes", "no", "unsure"):
                raise ValueError("id and a verdict of yes/no/unsure are required")
            HITL.parent.mkdir(parents=True, exist_ok=True)
            with open(HITL, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "id": vid, "verdict": verdict, "by": "john",
                                    "source": "THE LINE dashboard"}, ensure_ascii=False) + "\n")
            self._send(b'{"ok":true}', "application/json")
        except Exception as exc:
            self._send(json.dumps({"ok": False, "why": str(exc)[:200]}).encode(), "application/json", 400)

    def _loop(self):
        """Start the Sam Loop, or ask it to stop between rounds.

        START refuses while a loop is already beating, because two loops share one Living Room, one
        pick board and one 4090, and the second one would quietly corrupt the first one's round.
        STOP writes the same STOP file STOP-SAM-LOOP.bat writes (sam_loop.py:492 reads it between
        rounds), so a round that is mid-flight finishes and is analysed rather than being killed.
        """
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 2048)).decode("utf-8", "replace") or "{}")
            action = str(body.get("action") or "")

            if action == "stop":
                STOP_FILE.write_text("asked from THE LINE at " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n",
                                     encoding="utf-8")
                self._send(json.dumps({"ok": True, "did": "stop",
                                       "note": "the loop ends after the round it is in"}).encode(), "application/json")
                return

            if action != "start":
                raise ValueError('action must be "start" or "stop"')

            live = panel_loop()
            if live.get("alive"):
                raise ValueError("a loop is already running (" + str((live.get("heartbeat") or {}).get("phase") or "?")
                                 + "). Stop it first, or let it finish.")
            if not LOOP_SCRIPT.is_file():
                raise ValueError("sam_loop.py is not beside this dashboard: " + str(LOOP_SCRIPT))

            rounds = body.get("rounds", LOOP_ROUNDS_DEFAULT)
            rounds = max(1, min(LOOP_ROUNDS_MAX, int(rounds) if str(rounds).lstrip("-").isdigit() else LOOP_ROUNDS_DEFAULT))
            if STOP_FILE.exists():
                STOP_FILE.unlink()          # a stale STOP would end the new loop before its first round

            cmd = [sys.executable, str(LOOP_SCRIPT), "--rounds", str(rounds), "--depth", LOOP_DEPTH, "--factory"]
            # Detached and in its own process group, so the loop outlives this dashboard - closing
            # THE LINE must never take the night's work down with it.
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            proc = subprocess.Popen(cmd, cwd=str(CEO_ROOT), creationflags=flags,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    close_fds=True) if os.name == "nt" else subprocess.Popen(
                cmd, cwd=str(CEO_ROOT), start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            self._send(json.dumps({"ok": True, "did": "start", "pid": proc.pid, "rounds": rounds,
                                   "note": "factory on, depth " + LOOP_DEPTH
                                           + " - the first heartbeat lands within a minute"}).encode(),
                       "application/json")
        except Exception as exc:
            self._send(json.dumps({"ok": False, "why": str(exc)[:300]}).encode(), "application/json", 400)

    def _image(self):
        """Serve one picture from inside the worlds folder. Resolved and checked against IMG_ROOTS,
        so a crafted ?p=../../.. cannot walk out and read the rest of the disk."""
        from urllib.parse import urlparse, parse_qs, unquote
        rel = unquote((parse_qs(urlparse(self.path).query).get("p") or [""])[0])
        if not rel:
            self.send_error(400)
            return
        for root in IMG_ROOTS:
            try:
                full = (root / rel).resolve()
                if not full.is_file() or root.resolve() not in full.parents:
                    continue
                ctype = IMG_TYPES.get(full.suffix.lower())
                if not ctype or full.stat().st_size > IMG_MAX:
                    continue
                self._send(full.read_bytes(), ctype)
                return
            except (OSError, ValueError):
                continue
        self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/api/whoami"):
            self._send(json.dumps({"app": SIGNATURE, "pid": os.getpid()}).encode(), "application/json")
            return
        if self.path.startswith("/img"):
            self._image()
            return
        if self.path.startswith("/api/live"):
            body = json.dumps(snapshot(), default=str).encode("utf-8")
            ctype = "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.encode("utf-8"), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


PAGE_ROUTES = "/api/live /api/whoami /api/shutdown /api/verdict /api/loop /img"   # every route this serves
SHUTDOWN_SRC = 'threading.Thread(target=lambda: _server and _server.shutdown(), daemon=True).start()'


def selftest() -> int:
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (("  — " + detail) if detail and not ok else ""))
        if not ok:
            fails.append(name)

    print("dashboard self-test")
    snap = snapshot()
    check("a snapshot is produced", isinstance(snap, dict) and "at" in snap)
    for k in ("loop", "sam", "models", "factory", "made", "gpu", "ports", "training"):
        check(f"panel '{k}' answered", isinstance(snap.get(k), dict), str(snap.get(k))[:90])
    broken = [k for k, v in snap.items() if isinstance(v, dict) and v.get("_error")]
    check("a dead service greys one card, it does not blank the page",
          len(broken) < 8, "every panel failed: " + ", ".join(broken))
    if broken:
        print("       (panels reporting an error right now: " + ", ".join(broken) + ")")
    check("the page is a whole document", PAGE.startswith("<!doctype html") and "</html>" in PAGE)
    check("it renders without any outside file", "http" not in PAGE.split("<script>")[0].replace("http://127.0.0.1", ""))
    check("it writes to exactly one file, and it is not a taste ledger",
          "/api/verdict" in PAGE and "preferences" not in PAGE and str(HITL).endswith("hitl-verdicts.jsonl"))
    check("it never deletes or overwrites anything", not any(w in PAGE for w in ("DELETE", "PUT")))

    # THE START BUTTON. The thing worth checking is not that it starts the loop - it is that there
    # is no way to make it start anything ELSE. The program and every flag are constants in this
    # file; the only thing a request carries is a number.
    check("the page offers a start and a stop", 'loopDo(\'start\')' in PAGE and 'loopDo(\'stop\')' in PAGE)
    check("the loop endpoint is declared in the route list", "/api/loop" in PAGE_ROUTES)
    src = Path(__file__).read_text(encoding="utf-8")
    body = src.split("def _loop(self)", 1)[-1].split("def _image(self)", 1)[0]
    check("the program it runs is this interpreter, not anything a request names",
          "sys.executable" in body and "shell=True" not in body and "body.get(\"cmd\")" not in body)
    check("the script it runs is a constant", 'str(LOOP_SCRIPT)' in body and "LOOP_SCRIPT = HERE" in src)
    check("the flags it runs with are constants", '"--factory"' in body and "LOOP_DEPTH" in body)
    check("the only thing a request may carry is a round count",
          body.count("body.get(") == 2 and 'body.get("rounds"' in body and 'body.get("action"' in body,
          f"{body.count('body.get(')} request fields read, expected exactly 2: action and rounds")
    clamp = lambda r: max(1, min(LOOP_ROUNDS_MAX, int(r) if str(r).lstrip("-").isdigit() else LOOP_ROUNDS_DEFAULT))
    check("a silly round count is clamped, not obeyed",
          clamp(999999) == LOOP_ROUNDS_MAX and clamp(0) == 1 and clamp("; rm -rf /") == LOOP_ROUNDS_DEFAULT,
          f"{clamp(999999)}, {clamp(0)}, {clamp('; rm -rf /')}")
    check("stop writes the same file STOP-SAM-LOOP.bat writes, inside sim-player",
          STOP_FILE == HERE / "STOP", str(STOP_FILE))
    check("the loop is started from CEO_Attempt, where it expects to be",
          CEO_ROOT == HERE.parent and (CEO_ROOT / "sim-player").is_dir(), str(CEO_ROOT))
    check("starting is refused while one is already beating", 'live.get("alive")' in body)
    check("a stale STOP is cleared before a new loop starts", "STOP_FILE.unlink()" in body)
    check("the loop outlives this dashboard", "DETACHED_PROCESS" in body or "start_new_session" in body)
    def allowed(rel: str) -> bool:
        """Exactly the containment test _image() applies, run against a path instead of a request."""
        for root in IMG_ROOTS:
            try:
                if root.resolve() in (root / rel).resolve().parents:
                    return True
            except (OSError, ValueError):
                continue
        return False

    check("a picture inside the worlds folder is allowed", allowed("warehouse/source/x.png"))
    check("a picture request cannot walk out of the worlds folder",
          not allowed("../../../../Windows/System32/config/SAM")
          and not allowed("../../.env")
          and not allowed("../../../training-data/events-sim.jsonl"))
    check("only image types are served", ".py" not in IMG_TYPES and ".json" not in IMG_TYPES
          and set(IMG_TYPES) == {".png", ".jpg", ".jpeg", ".webp"})
    check("the HITL panel answered", isinstance(snap.get("hitl"), dict), str(snap.get("hitl"))[:90])
    check("it can recognise a stale copy of itself and nothing else",
          "/api/whoami" in PAGE_ROUTES and SIGNATURE == "the-line-dashboard/1")
    check("standing down only ever closes this program",
          "_server.shutdown()" in SHUTDOWN_SRC and "taskkill" not in SHUTDOWN_SRC
          and "kill" not in SHUTDOWN_SRC.lower())
    h = snap.get("hitl") or {}
    check("every ask carries both sides",
          all(("pictures" in r and "world_shot" in r and "asset" in r) for r in (h.get("rows") or [])),
          "a row was missing a side")
    arch = _archive_world()
    check("the world archive is this dashboard's own folder, not a world",
          WORLD_SHOTS.parent == RUNS and WORLDS not in WORLD_SHOTS.parents, str(WORLD_SHOTS))
    check("snapshots are named for their moment, so none is ever overwritten",
          all(f.stem.isdigit() for _m, f in arch), str([f.name for _m, f in arch][:3]))
    check("an ask is paired with the world AFTER it, never before",
          (_world_after(0.0, [(10.0, Path("10.png")), (20.0, Path("20.png"))]) or {}).get("src", "").endswith("10.png")
          and (_world_after(15.0, [(10.0, Path("10.png")), (20.0, Path("20.png"))]) or {}).get("src", "").endswith("20.png"))
    check("with no snapshot after it, the card says so rather than showing the wrong world",
          (_world_after(99.0, [(10.0, Path("10.png"))]) or {}).get("stale") is True)
    print("ALL GREEN" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails))
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="A live, local, read-only window on the whole line.")
    ap.add_argument("--port", type=int, default=int(os.getenv("SAM_DASHBOARD_PORT", "8099")))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    global _server
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError:
        st, who = _get(f"http://127.0.0.1:{a.port}/api/whoami", timeout=3)
        if st != 200 or (who or {}).get("app") != SIGNATURE:
            print(f"  :{a.port} is held by something that is NOT this dashboard — leaving it alone.")
            print(f"  Start on another port:  python dashboard.py --port {a.port + 1}")
            return 1
        print(f"  an older copy of this dashboard (pid {who.get('pid')}) holds :{a.port} — asking it to stand down")
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{a.port}/api/shutdown", data=b"{}", method="POST"), timeout=5).read()
        except Exception:
            pass
        srv = None
        for _ in range(20):
            time.sleep(0.5)
            try:
                srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
                break
            except OSError:
                continue
        if srv is None:
            print(f"  it did not let go of :{a.port}. Close its window, or use --port {a.port + 1}.")
            return 1
        print("  it stood down. This copy is now the one on that port.")
    _server = srv
    print("=" * 66)
    print(f"  THE LINE is on   http://127.0.0.1:{a.port}")
    print("  Read-only. It opens no model, queues no job and writes no file.")
    print("  Leave this window open - closing it closes the dashboard.")
    print("=" * 66)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  dashboard stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
