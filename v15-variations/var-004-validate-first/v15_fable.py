"""v15_Fable — Fable's standalone prompt→blueprint→walkable-world pipeline.

STANDALONE by design (John, 2026-07-30): new file, new routes, new template.
Touches NOTHING in v3–v14 beyond two additive hooks in app.py.

The one law learned the hard way across this project:
  THE PLAN IS THE ONLY GEOMETRY TRUTH. Images never vote on geometry.
Flow: prompt → 3 plan variants (real Ollama, honest fallback) → sanitize →
user locks one → world builds FROM THE PLAN → props come from John's real
painted warehouse when a match exists, clean placeholders otherwise.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api/v15fable", tags=["v15_fable"])

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "output"
# John's REAL prop warehouse (read-only — painted GLBs from the CEO-3D-World factory).
WAREHOUSE = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\CEO-3D-World\worlds\warehouse\output"
)

# ---------------------------------------------------------------- LLM (real, with honest fallback)

OLLAMA = "http://127.0.0.1:11434"

PLAN_SCHEMA_HINT = """Return ONLY JSON, no prose, exactly this shape:
{"name": "short room name",
 "width_m": 6.0, "depth_m": 8.0, "height_m": 3.0,
 "vibe": {"era": "1970s", "style": "worn Americana", "condition": "lived-in"},
 "palette": {"wall": "#d8cfc0", "floor": "#7a5c3e", "accent": "#b33a2f", "mood": "warm"},
 "doors":   [{"wall": "S", "offset_m": 3.0, "width_m": 1.0}],
 "windows": [{"wall": "E", "offset_m": 2.0, "width_m": 1.6, "sill_m": 0.9}],
 "objects": [{"name": "bed", "category": "object", "x_m": 1.5, "z_m": 2.0, "w_m": 1.6, "d_m": 2.0, "h_m": 0.6, "rot_deg": 0}]}
Walls are N,S,E,W. offset_m measures along the wall from its left end.
x_m,z_m is the object's CENTER from the room's north-west corner. 3-9 objects.
category is one of: object (interactive movables: chair, bed, TV),
appliance (functional machines: stove, fridge), fixture (permanent: sink,
counter, lamp), decoration (rug, painting, plant, mirror), clutter (tiny
dressing: magazines, tissue box). Include 1-2 decorations and 1-2 clutter."""

# taxonomy defaults by name (John's 2026-07-30 category system) — the sanitizer's
# safety net when a planner omits or invents categories
_CATEGORIES = ("object", "appliance", "fixture", "decoration", "clutter")
_CATEGORY_BY_NAME = {
    "appliance": ["stove", "fridge", "refrigerator", "oven", "washer", "dryer", "coffee machine",
                  "dishwasher", "microwave", "jukebox"],
    "fixture": ["sink", "toilet", "counter", "bathtub", "lamp", "light", "chandelier",
                "workbench", "shelf", "bookshelf", "cash register", "booth"],
    "decoration": ["rug", "painting", "plant", "mirror", "trophy", "curtain", "poster",
                   "clock", "vase", "for sale sign"],
    "clutter": ["magazine", "tissue", "spice", "book stack", "ashtray", "mug", "bottle",
                "papers", "napkin"],
}


def _default_category(name: str) -> str:
    for cat, words in _CATEGORY_BY_NAME.items():
        if any(w in name for w in words):
            return cat
    return "object"


def _ollama_model() -> str | None:
    """First installed model, or None. Never raises."""
    try:
        r = httpx.get(f"{OLLAMA}/api/tags", timeout=3.0)
        models = [m["name"] for m in r.json().get("models", [])]
        for m in models:  # prefer small/instruct-ish models first
            if any(k in m.lower() for k in ("llama3", "qwen", "mistral", "phi", "gemma")):
                return m
        return models[0] if models else None
    except Exception:
        return None


def _llm_plan(prompt: str, variant_hint: str, model: str) -> dict | None:
    """One plan from Ollama. None on any failure — fallback handles it."""
    try:
        r = httpx.post(
            f"{OLLAMA}/api/generate",
            json={
                "model": model,
                "prompt": (
                    f"You are an architect. Design ONE room for: {prompt}\n"
                    f"Variation directive: {variant_hint}\n{PLAN_SCHEMA_HINT}"
                ),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.9, "num_predict": 700},
            },
            timeout=25.0,
        )
        return json.loads(r.json()["response"])
    except Exception:
        return None


# ---------------------------------------------------------------- fallback planner (deterministic, keyword-driven)

_THEMES = {
    "diner": dict(palette={"wall": "#efe6d8", "floor": "#9daaa2", "accent": "#c62828", "mood": "retro"},
                  objects=["counter", "stool", "stool", "stool", "booth", "jukebox", "cash register", "coffee machine"]),
    "bedroom": dict(palette={"wall": "#e8ddc8", "floor": "#8a6a4a", "accent": "#b23b3b", "mood": "warm"},
                    objects=["bed", "desk", "chair", "rug", "lamp", "bookshelf"]),
    "office": dict(palette={"wall": "#dcdcd4", "floor": "#6f5b43", "accent": "#2f5d8a", "mood": "focused"},
                   objects=["desk", "chair", "file cabinet", "bookshelf", "plant", "safe"]),
    "garage": dict(palette={"wall": "#c9c9c9", "floor": "#8c8c8c", "accent": "#e0a020", "mood": "industrial"},
                   objects=["workbench", "car", "toolbox", "shelf", "barrel"]),
    "default": dict(palette={"wall": "#ddd6c6", "floor": "#7d6446", "accent": "#3e7a5e", "mood": "calm"},
                    objects=["table", "chair", "chair", "sofa", "rug", "plant", "lamp"]),
}


def _fallback_plan(prompt: str, seed: int) -> dict:
    rng = random.Random(seed)
    p = prompt.lower()
    theme = next((v for k, v in _THEMES.items() if k in p), None)
    if theme is None:
        for k, v in _THEMES.items():
            if any(w in p for w in k.split()):
                theme = v
                break
    theme = theme or _THEMES["default"]
    w = round(rng.uniform(5.0, 9.0), 1)
    d = round(rng.uniform(6.0, 11.0), 1)
    objs = []
    for name in theme["objects"]:
        # real footprints per family (QA 2026-07-30: uniform 0.9-cubes made prop
        # scale "wildly inconsistent" once real GLBs stood next to them)
        bw, bd, bh = next((s for k, s in _DEFAULT_SIZES.items() if k in name), (0.8, 0.8, 0.9))
        objs.append({
            "name": name,
            "x_m": round(rng.uniform(0.8, w - 0.8), 2),
            "z_m": round(rng.uniform(0.8, d - 0.8), 2),
            "w_m": bw, "d_m": bd, "h_m": bh,
            "rot_deg": rng.choice([0, 90, 180, 270]),
        })
    _VIBES = {"retro": {"era": "1950s", "style": "chrome-and-vinyl American diner", "condition": "lovingly kept"},
              "warm": {"era": "1990s", "style": "cozy suburban", "condition": "lived-in"},
              "focused": {"era": "1980s", "style": "wood-panel office", "condition": "tidy"},
              "industrial": {"era": "1970s", "style": "workshop utilitarian", "condition": "well used"}}
    return {
        "name": f"variant {seed}", "width_m": w, "depth_m": d, "height_m": 3.0,
        "vibe": _VIBES.get(theme["palette"]["mood"], {"era": "present day", "style": "simple and calm", "condition": "well kept"}),
        "palette": theme["palette"],
        "doors": [{"wall": "S", "offset_m": round(w * 0.5, 1), "width_m": 1.1}],
        "windows": [{"wall": "E", "offset_m": round(d * 0.3, 1), "width_m": 1.8, "sill_m": 0.9},
                    {"wall": "N", "offset_m": round(w * 0.4, 1), "width_m": 1.4, "sill_m": 0.9}],
        "objects": objs,
    }


# ---------------------------------------------------------------- sanitizer (never trust ANY planner)

_DEFAULT_SIZES = {  # w, d, h in meters — believable footprints per object family
    "bed": (1.6, 2.0, 0.6), "desk": (1.4, 0.7, 0.75), "chair": (0.55, 0.55, 0.9),
    "sofa": (2.0, 0.9, 0.8), "couch": (2.0, 0.9, 0.8), "table": (1.4, 0.9, 0.75),
    "rug": (2.0, 1.5, 0.02), "lamp": (0.4, 0.4, 1.5), "bookshelf": (1.0, 0.35, 1.9),
    "counter": (3.0, 0.7, 1.0), "stool": (0.45, 0.45, 0.75), "booth": (1.8, 1.4, 1.1),
    "jukebox": (0.9, 0.7, 1.5), "cash register": (0.5, 0.5, 0.45), "coffee machine": (0.6, 0.5, 0.7),
    "file cabinet": (0.5, 0.6, 1.3), "safe": (0.7, 0.7, 1.0), "plant": (0.5, 0.5, 1.3),
    "workbench": (2.0, 0.8, 0.95), "car": (1.9, 4.6, 1.4), "toolbox": (0.7, 0.4, 0.8),
    "shelf": (1.2, 0.4, 1.8), "barrel": (0.6, 0.6, 0.9),
}


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except Exception:
        return default
    return max(lo, min(hi, v))


def sanitize_plan(raw: dict, idx: int) -> dict:
    """Clamp every number, bound every count, guarantee a legal walkable room."""
    p = raw if isinstance(raw, dict) else {}
    w = _clamp(p.get("width_m"), 3.0, 14.0, 6.0)
    d = _clamp(p.get("depth_m"), 3.0, 14.0, 8.0)
    h = _clamp(p.get("height_m"), 2.4, 4.5, 3.0)
    vb = p.get("vibe") if isinstance(p.get("vibe"), dict) else {}
    vibe = {"era": str(vb.get("era", "present day"))[:32],
            "style": str(vb.get("style", "simple and clean"))[:48],
            "condition": str(vb.get("condition", "well kept"))[:32]}
    pal = p.get("palette") if isinstance(p.get("palette"), dict) else {}
    hexre = re.compile(r"^#[0-9a-fA-F]{6}$")
    palette = {
        "wall": pal.get("wall") if hexre.match(str(pal.get("wall", ""))) else "#ddd6c6",
        "floor": pal.get("floor") if hexre.match(str(pal.get("floor", ""))) else "#7d6446",
        "accent": pal.get("accent") if hexre.match(str(pal.get("accent", ""))) else "#3e7a5e",
        "mood": str(pal.get("mood", "calm"))[:24],
    }
    def _openings(items, is_door):
        out = []
        for o in (items if isinstance(items, list) else [])[:4]:
            wall = str(o.get("wall", "S")).upper()
            wall = wall if wall in ("N", "S", "E", "W") else "S"
            length = w if wall in ("N", "S") else d
            width = _clamp(o.get("width_m"), 0.7, 3.0, 1.0)
            off = _clamp(o.get("offset_m"), 0.3 + width / 2, length - 0.3 - width / 2, length / 2)
            item = {"wall": wall, "offset_m": round(off, 2), "width_m": round(width, 2)}
            if not is_door:
                item["sill_m"] = _clamp(o.get("sill_m"), 0.4, h - 1.2, 0.9)
            out.append(item)
        return out
    doors = _openings(p.get("doors"), True) or [{"wall": "S", "offset_m": round(w / 2, 2), "width_m": 1.1}]
    windows = _openings(p.get("windows"), False)
    objs = []
    for o in (p.get("objects") if isinstance(p.get("objects"), list) else [])[:12]:
        name = re.sub(r"[^a-z0-9 \-]", "", str(o.get("name", "prop")).lower()).strip()[:32] or "prop"
        base = next((s for k, s in _DEFAULT_SIZES.items() if k in name), (0.8, 0.8, 0.9))
        ow = _clamp(o.get("w_m"), 0.2, min(4.8, w - 1), base[0])
        od = _clamp(o.get("d_m"), 0.2, min(4.8, d - 1), base[1])
        oh = _clamp(o.get("h_m"), 0.02, h - 0.3, base[2])
        margin = max(ow, od) / 2 + 0.15
        cat = str(o.get("category", "")).lower()
        objs.append({
            "name": name,
            "category": cat if cat in _CATEGORIES else _default_category(name),
            "x_m": round(_clamp(o.get("x_m"), margin, w - margin, w / 2), 2),
            "z_m": round(_clamp(o.get("z_m"), margin, d - margin, d / 2), 2),
            "w_m": round(ow, 2), "d_m": round(od, 2), "h_m": round(oh, 2),
            "rot_deg": _clamp(o.get("rot_deg"), 0, 359, 0),
        })
    # keep the door approach clear: shove objects out of a 1.2m door clearance zone
    for door in doors:
        dx, dz = _door_xy(door, w, d)
        for o in objs:
            if abs(o["x_m"] - dx) < 1.2 and abs(o["z_m"] - dz) < 1.2:
                o["x_m"] = round(min(w - 1, max(1.0, o["x_m"] + (2.0 if dx < w / 2 else -2.0))), 2)
    # de-overlap pass (QA 2026-07-30: "the jukebox visibly intersects the sofa") —
    # push apart along the smallest-penetration axis, a few bounded iterations
    for _ in range(24):
        moved = False
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                a, b = objs[i], objs[j]
                ox = (a["w_m"] + b["w_m"]) / 2 + 0.12 - abs(a["x_m"] - b["x_m"])
                oz = (a["d_m"] + b["d_m"]) / 2 + 0.12 - abs(a["z_m"] - b["z_m"])
                if ox > 0 and oz > 0:
                    moved = True
                    if ox < oz:
                        s = ox / 2 + .01
                        a["x_m"], b["x_m"] = a["x_m"] + (s if a["x_m"] >= b["x_m"] else -s), b["x_m"] + (s if b["x_m"] > a["x_m"] else -s)
                    else:
                        s = oz / 2 + .01
                        a["z_m"], b["z_m"] = a["z_m"] + (s if a["z_m"] >= b["z_m"] else -s), b["z_m"] + (s if b["z_m"] > a["z_m"] else -s)
        for o in objs:  # re-clamp into the room after each shuffle
            mx = max(o["w_m"], o["d_m"]) / 2 + 0.15
            o["x_m"] = round(min(w - mx, max(mx, o["x_m"])), 2)
            o["z_m"] = round(min(d - mx, max(mx, o["z_m"])), 2)
        if not moved:
            break
    return {
        "name": str(p.get("name", f"variant {idx}"))[:48],
        "width_m": round(w, 2), "depth_m": round(d, 2), "height_m": round(h, 2),
        "vibe": vibe, "palette": palette, "doors": doors, "windows": windows, "objects": objs,
    }


def _door_xy(door, w, d):
    wall, off = door["wall"], door["offset_m"]
    return {"N": (off, 0.0), "S": (off, d), "W": (0.0, off), "E": (w, off)}[wall]


# ---------------------------------------------------------------- warehouse (REAL painted props)

_wh_cache: dict[str, str] | None = None


def _warehouse_index() -> dict[str, str]:
    """slug -> absolute painted-GLB path. Scanned once, painted files only."""
    global _wh_cache
    if _wh_cache is None:
        idx = {}
        if WAREHOUSE.exists():
            for d in WAREHOUSE.iterdir():
                g = d / f"0-{d.name}_painted.glb"
                if g.exists():
                    idx[d.name] = str(g)
        _wh_cache = idx
    return _wh_cache


# adjectives/colors carry zero identity — "big red sofa" must NOT match a red car
# (walkthrough QA 2026-07-30: a Chevy Caprice matched a sofa on the word "red",
#  and a tissue box got a jukebox because "box" is a SUBSTRING of "jukebox")
_STOPWORDS = {"red", "blue", "green", "teal", "brown", "black", "white", "gold", "silver",
              "brass", "chrome", "big", "small", "little", "large", "old", "new", "vintage",
              "worn", "classic", "antique", "the", "with", "and"}


def match_asset(name: str, category: str = "object") -> str | None:
    """Best warehouse slug by WHOLE-WORD noun overlap, category-compatible. None = placeholder."""
    words = {w for w in re.split(r"[\s\-]+", name.lower()) if len(w) >= 2 and w not in _STOPWORDS}
    if not words:
        return None
    best, score = None, 0
    for slug in _warehouse_index():
        slug_words = set(slug.split("-"))
        s = len(words & slug_words)                     # exact word equality only
        if s == 0:
            continue
        slug_cat = _default_category(slug.replace("-", " "))
        if slug_cat != category and s < 2:              # cross-category needs strong evidence
            continue
        if s > score:
            best, score = slug, s
    return best


# ---------------------------------------------------------------- routes

@router.post("/plans")
async def make_plans(body: dict):
    prompt = str(body.get("prompt", "")).strip()[:500]
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, status_code=400)
    t0 = time.time()
    model = _ollama_model()
    hints = ["cozy and compact", "spacious and dramatic", "unconventional layout, bold shapes"]
    plans, engines = [], []
    for i, hint in enumerate(hints):
        raw = _llm_plan(prompt, hint, model) if model else None
        engines.append(f"ollama:{model}" if raw is not None else "fallback:procedural")
        plans.append(sanitize_plan(raw if raw is not None else _fallback_plan(prompt, i + 1), i + 1))
    return {"plans": plans, "engines": engines, "elapsed_s": round(time.time() - t0, 1),
            "warehouse_assets": len(_warehouse_index())}


@router.post("/lock")
async def lock_plan(body: dict):
    plan = sanitize_plan(body.get("plan", {}), 0)   # re-sanitize: the client is not trusted either
    prompt = str(body.get("prompt", ""))[:500]
    sid = uuid.uuid4().hex[:8]
    sdir = OUT_DIR / f"v15f_{sid}"
    sdir.mkdir(parents=True, exist_ok=True)
    assets = {}
    for i, o in enumerate(plan["objects"]):
        slug = match_asset(o["name"], o.get("category", "object"))
        if slug:
            assets[str(i)] = {"slug": slug, "url": f"/api/v15fable/asset/{slug}"}
    plan_bytes = json.dumps(plan, indent=1).encode()
    (sdir / "plan.json").write_bytes(plan_bytes)
    manifest = {
        "session": sid, "prompt": prompt,
        "locked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "engine": str(body.get("engine", "?")), "assets": assets,
        "law": "the plan is the only geometry truth; images never vote on geometry",
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return {"session_id": sid, "plan": plan, "assets": assets}


@router.get("/asset/{slug}")
async def asset(slug: str):
    if not re.fullmatch(r"[a-z0-9\-]{1,64}", slug):
        return JSONResponse({"error": "bad slug"}, status_code=400)
    path = _warehouse_index().get(slug)
    if not path:
        return JSONResponse({"error": "not in warehouse"}, status_code=404)
    return FileResponse(path, media_type="model/gltf-binary")


# ---------------------------------------------------------------- canon (style truth, painted FROM the plan)

COMFY_MAIN = "http://127.0.0.1:8188"  # John's Mesh/Z-Image engine (Z-Image Turbo lives here)


def _canon_graph(prompt: str, seed: int) -> dict:
    """Z-Image Turbo graph, same proven shape as the hyw-gate canon shots (1536x864, 8 steps)."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1536, "height": 864, "batch_size": 1}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
              "latent_image": ["6", 0], "seed": seed, "steps": 8, "cfg": 1, "sampler_name": "res_multistep",
              "scheduler": "simple", "denoise": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "v15fable-canon"}},
    }


def _canon_prompt(plan: dict, user: str = "") -> str:
    """John 2026-07-30: the render must match the DESCRIPTION — his words go in
    VERBATIM. The plan's object list rides along only so the census can check it.
    No template furniture he didn't ask for."""
    v, pal = plan.get("vibe", {}), plan.get("palette", {})
    objs = ", ".join(o["name"] for o in plan.get("objects", []) if o.get("category") != "clutter")
    user = (user or "").strip()
    lead = user if user else (f"a {v.get('era','')} {v.get('style','room')}, "
                              f"{v.get('condition','')}, {pal.get('mood','calm')} mood")
    return (f"Interior photograph. {lead} "
            f"A {plan.get('width_m')}x{plan.get('depth_m')} meter room containing {objs}. "
            f"Every object fully visible and separated, furniture feet visible. "
            f"Eye-level wide angle, photorealistic, highly detailed")


@router.post("/canon/{sid}")
async def make_canon(sid: str, roll: int = 0):
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    plan_path = sdir / "plan.json"
    if not plan_path.exists():
        return JSONResponse({"error": "unknown session"}, status_code=404)
    dest = sdir / "canon.png"
    pending_f = sdir / "canon-pending.json"
    if dest.exists() and int(roll) == 0 and not pending_f.exists():
        return {"ok": True, "cached": True}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    try:                                                 # his EXACT words drive the picture
        user_words = json.loads((sdir / "manifest.json").read_text(encoding="utf-8")).get("prompt", "")
    except Exception:
        user_words = ""
    prompt = _canon_prompt(plan, user_words)
    seed = int(hashlib.sha256(sid.encode()).hexdigest()[:12], 16) + int(roll)
    import asyncio
    try:
        async with httpx.AsyncClient(timeout=15.0) as cl:
            pid = None
            if pending_f.exists():                       # RESUME the in-flight render — never resubmit
                try:
                    pend = json.loads(pending_f.read_text(encoding="utf-8"))
                    if int(pend.get("roll", -1)) == int(roll):
                        pid = pend.get("prompt_id")      # same dream: resume it
                    # different roll = John explicitly re-aimed: submit fresh below
                except Exception:
                    pid = None
            if not pid:
                sub = await cl.post(f"{COMFY_MAIN}/prompt", json={"prompt": _canon_graph(prompt, seed)})
                pid = sub.json()["prompt_id"]
                pending_f.write_text(json.dumps({"prompt_id": pid, "roll": int(roll),
                                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}))
            for _ in range(160):                         # ~4 min — the census may hold the engine first
                await asyncio.sleep(1.5)
                h = (await cl.get(f"{COMFY_MAIN}/history/{pid}")).json()
                rec = h.get(pid)
                if rec and rec.get("outputs"):
                    for node in rec["outputs"].values():
                        for im in node.get("images", []):
                            img = await cl.get(f"{COMFY_MAIN}/view",
                                               params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                       "type": im.get("type", "output")})
                            if dest.exists():            # refine, never destroy: swap only AFTER success
                                dest.rename(sdir / f"canon.re-dream-{int(time.time())}.bak.png")
                            dest.write_bytes(img.content)
                            try:
                                pending_f.unlink()
                            except Exception:
                                pass
                            man_path = sdir / "manifest.json"           # re-read + merge, never from memory
                            man = json.loads(man_path.read_text(encoding="utf-8"))
                            man["canon"] = {"prompt": prompt, "seed": seed,
                                            "sha256": hashlib.sha256(img.content).hexdigest(),
                                            "engine": f"z-image-turbo@{COMFY_MAIN}"}
                            man_path.write_text(json.dumps(man, indent=1))
                            return {"ok": True, "bytes": len(img.content)}
            return JSONResponse({"error": "still rendering — click ↻ Re-dream to RESUME this same render (it will not start over)"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": f"canon engine unreachable: {exc}"}, status_code=502)


DANNY_RESTYLE = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\CEO-3D-World\workflows\controlnet-colorize.api.json"
)  # John's PROVEN danny-v4 restyle: SDXL + lucasarts LoRA + ControlNet canny 0.65 anchor


@router.post("/canon/{sid}/restyle")
async def restyle_canon(sid: str):
    """Stage 2 of the danny-v4 recipe: photoreal canon -> painted LucasArts canon.
    The ControlNet structure anchor is NON-NEGOTIABLE (ledger 2026-07-15:
    'a restyle never runs without its structure anchor' - trophies became cacti)."""
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    base = sdir / "canon.png"
    if not base.exists():
        return JSONResponse({"error": "photoreal canon must exist first"}, status_code=409)
    dest = sdir / "canon-lucasarts.png"
    if dest.exists():
        return {"ok": True, "cached": True}
    if not DANNY_RESTYLE.exists():
        return JSONResponse({"error": "danny restyle workflow not found"}, status_code=500)
    plan = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    v = plan.get("vibe", {})
    prompt = (f"vibrant painted adventure game background, LucasArts style, bold saturated colors, "
              f"{v.get('era','')} {v.get('style','room')}, clean confident brushwork")
    graph = json.loads(DANNY_RESTYLE.read_text(encoding="utf-8"))
    try:
        import asyncio
        async with httpx.AsyncClient(timeout=20.0) as cl:
            up = await cl.post(f"{COMFY_MAIN}/upload/image",
                               files={"image": (f"v15f-{sid}-canon.png", base.read_bytes(), "image/png")},
                               data={"overwrite": "true"})
            graph["3"]["inputs"]["image"] = up.json()["name"]
            graph["6"]["inputs"]["text"] = prompt
            sub = await cl.post(f"{COMFY_MAIN}/prompt", json={"prompt": graph})
            pid = sub.json()["prompt_id"]
            for _ in range(80):  # SDXL 30 steps + first model load can take a while
                await asyncio.sleep(2.0)
                h = (await cl.get(f"{COMFY_MAIN}/history/{pid}")).json()
                rec = h.get(pid)
                if rec and rec.get("outputs"):
                    for node in rec["outputs"].values():
                        for im in node.get("images", []):
                            img = await cl.get(f"{COMFY_MAIN}/view",
                                               params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                       "type": im.get("type", "output")})
                            dest.write_bytes(img.content)
                            man_path = sdir / "manifest.json"
                            man = json.loads(man_path.read_text(encoding="utf-8"))
                            man["canon_lucasarts"] = {"prompt": prompt,
                                                      "sha256": hashlib.sha256(img.content).hexdigest(),
                                                      "recipe": "danny-v4: SDXL + lucasarts LoRA + ControlNet canny 0.65"}
                            man_path.write_text(json.dumps(man, indent=1))
                            return {"ok": True, "bytes": len(img.content)}
            return JSONResponse({"error": "restyle timed out"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": f"restyle failed: {exc}"}, status_code=502)


@router.get("/canon/{sid}")
async def get_canon(sid: str, style: str = "photo"):
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    name = "canon-lucasarts.png" if style == "lucasarts" else "canon.png"
    path = OUT_DIR / f"v15f_{sid}" / name
    if not path.exists():
        return JSONResponse({"error": "no canon yet"}, status_code=404)
    return FileResponse(path, media_type="image/png")


# ------------------------------------------------------- identify: canon -> cutouts -> factory queue

CEO_3D = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World")


def _slugify(subject: str) -> str:
    """EXACTLY make-prop.mjs's id rule, so the raw cutout lands where it looks."""
    return re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:40]


def _sam3_graph(canon_name: str, target: str) -> dict:
    """One object's extraction — the proven Starlite recipe, node for node."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": canon_name}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": f"the {target}"}},
        "4": {"class_type": "SAM3_Detect", "inputs": {"model": ["2", 0], "conditioning": ["3", 0], "image": ["1", 0],
              "threshold": 0.5, "refine_iterations": 2, "individual_masks": False}},
        "5": {"class_type": "GrowMask", "inputs": {"mask": ["4", 0], "expand": 4, "tapered_corners": True}},
        "6": {"class_type": "InvertMask", "inputs": {"mask": ["5", 0]}},
        "7": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["6", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": f"v15f-cut-{_slugify(target)[:20]}"}},
    }


def _prep_for_factory(cut_bytes: bytes) -> bytes | None:
    """make-prop's clean gate expects a RENDER: subject on white, filling 20-80%.
    A sparse transparent cutout reads as blank (proven 2026-07-30, all 5 props
    gate-FAILed). Crop to the object, pad, composite on white, fit a 1024 square."""
    import io
    from PIL import Image
    import numpy as np
    im = Image.open(io.BytesIO(cut_bytes)).convert("RGBA")
    a = np.array(im)[:, :, 3]
    ys, xs = np.nonzero(a > 128)
    if len(xs) < 500:                                    # SAM3 found nothing usable
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pw, ph = int((x1 - x0) * 0.06) + 6, int((y1 - y0) * 0.06) + 6
    crop = im.crop((max(0, x0 - pw), max(0, y0 - ph), min(im.width, x1 + pw), min(im.height, y1 + ph)))
    # The gate measures silhouette AREA (20-80% of frame). A fixed square canvas
    # fails wide sofas and tall lamps (measured 7.5%-18% live 2026-07-30). Fix:
    # wrap a NON-SQUARE canvas tightly around the object — fill becomes the
    # object's own density inside its box, which furniture comfortably passes.
    scale = min(950 / crop.width, 950 / crop.height, 3.0)
    crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
    cw, ch = max(512, int(crop.width * 1.12)), max(512, int(crop.height * 1.12))
    canvas = Image.new("RGB", (cw, ch), (255, 255, 255))
    canvas.paste(crop, ((cw - crop.width) // 2, (ch - crop.height) // 2), crop)
    out = io.BytesIO(); canvas.save(out, "PNG")
    return out.getvalue()


def _factory_subject(name: str, vibe: dict, model: str | None) -> str:
    """The LLM writes the prop factory prompt; honest fallback composes one."""
    if model:
        try:
            r = httpx.post(f"{OLLAMA}/api/generate", json={
                "model": model, "stream": False,
                "prompt": (f"Write ONE line (max 14 words) describing a '{name}' as a single 3D game prop, "
                           f"era {vibe.get('era','')}, style {vibe.get('style','')}. Physical description only, "
                           f"no scene, no background. Example: 'worn leather recliner with plump cushions on a solid base'"),
                "options": {"temperature": 0.7, "num_predict": 40}}, timeout=20.0)
            line = r.json()["response"].strip().strip('"').splitlines()[0][:90]
            if len(line) > 8:
                return line
        except Exception:
            pass
    return f"{vibe.get('era','')} {name}, {vibe.get('style','simple')} style, single object"


@router.post("/identify/{sid}")
async def identify(sid: str):
    """Close the loop: every placeholder gets cut from the canon, named, prompted,
    and queued for John's real prop factory (make-prop skips its hero pick when a
    raw cutout already exists — this is that entrance)."""
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    canon = sdir / "canon.png"
    if not canon.exists():
        return JSONResponse({"error": "canon required first"}, status_code=409)
    plan = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    man = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
    matched = {a["slug"] for a in man.get("assets", {}).values()}
    missing = [o for i, o in enumerate(plan["objects"])
               if str(i) not in man.get("assets", {}) and o.get("category") not in ("clutter",)]
    if not missing:
        return {"ok": True, "queued": 0, "note": "no placeholders — warehouse covered everything"}
    model = _ollama_model()
    cut_dir = sdir / "cutouts"; cut_dir.mkdir(exist_ok=True)
    queue = []
    import asyncio
    try:
        async with httpx.AsyncClient(timeout=20.0) as cl:
            up = await cl.post(f"{COMFY_MAIN}/upload/image",
                               files={"image": (f"v15f-{sid}-canon.png", canon.read_bytes(), "image/png")},
                               data={"overwrite": "true"})
            canon_name = up.json()["name"]
            for o in missing:
                sub = await cl.post(f"{COMFY_MAIN}/prompt", json={"prompt": _sam3_graph(canon_name, o["name"])})
                pid = sub.json()["prompt_id"]
                cut_bytes = None
                for _ in range(30):
                    await asyncio.sleep(1.0)
                    h = (await cl.get(f"{COMFY_MAIN}/history/{pid}")).json()
                    rec = h.get(pid)
                    if rec and rec.get("outputs"):
                        for node in rec["outputs"].values():
                            for im in node.get("images", []):
                                img = await cl.get(f"{COMFY_MAIN}/view",
                                                   params={"filename": im["filename"],
                                                           "subfolder": im.get("subfolder", ""),
                                                           "type": im.get("type", "output")})
                                cut_bytes = img.content
                        break
                subject = _factory_subject(o["name"], plan.get("vibe", {}), model)
                slug = _slugify(subject)
                entry = {"object": o["name"], "category": o["category"], "subject": subject, "slug": slug}
                if cut_bytes:
                    (cut_dir / f"{slug}.png").write_bytes(cut_bytes)       # full-frame, for the record
                    prepped = _prep_for_factory(cut_bytes)                 # gate-shaped: white, cropped, 64%
                    if prepped:
                        raw = CEO_3D / "worlds" / "warehouse" / "source" / "cutouts" / "raw"
                        raw.mkdir(parents=True, exist_ok=True)
                        (raw / f"{slug}.png").write_bytes(prepped)         # v15-staged intake; ours to refresh
                        # board-era paperwork: without picks/<id>/request.json the Pick
                        # Board FILTERS the prop off the inspection line (found live
                        # 2026-07-30 — the chair sat invisible in MESH CHECK). The canon
                        # cutout IS the pick, so we file both request and decision.
                        pick_dir = CEO_3D / "worlds" / "warehouse" / "source" / "cutouts" / "picks" / slug
                        pick_dir.mkdir(parents=True, exist_ok=True)
                        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                        if not (pick_dir / "request.json").exists():
                            (pick_dir / "request.json").write_text(json.dumps(
                                {"what": o["name"], "source": "v15_Fable canon identification",
                                 "pre_hero": True, "seeds": [], "at": ts}, indent=1))
                        if not (pick_dir / "decision.json").exists():
                            (pick_dir / "decision.json").write_text(json.dumps(
                                {"winner": "canon-cutout",
                                 "decided_by": "v15_Fable (the canon cutout IS the pick)", "at": ts}, indent=1))
                        entry["cutout"] = True
                    else:
                        entry["cutout"] = False; entry["note"] = "SAM3 found no usable region"
                queue.append(entry)
    except Exception as exc:
        return JSONResponse({"error": f"extraction failed: {exc}"}, status_code=502)
    (sdir / "factory-queue.json").write_text(json.dumps(queue, indent=1))
    bat = CEO_3D / f"RUN-FABLE-FACTORY-{sid}.bat"
    lines = ["@echo off", "setlocal", f"title Fable factory run - session {sid} - {len(queue)} props",
             "cd /d \"%~dp0\"",
             "echo ============================================================",
             f"echo   v15_Fable session {sid}: building {len(queue)} props identified",
             "echo   from the canon. Cutouts are pre-placed, so make-prop skips",
             "echo   its hero pick: clean - mesh - paint (6-view), one at a time.",
             "echo   $0 - local GPU. The warehouse grows with every finish.",
             "echo ============================================================", "echo."]
    for e in queue:
        lines += [f"echo --- {e['object']} -> {e['slug']} ---",
                  f"node tools\\make-prop.mjs \"{e['subject']}\"",
                  "echo."]
    lines += ["echo DONE - re-lock the plan in v15_Fable to pick up the new props.", "pause", ""]
    bat.write_text("\r\n".join(lines), encoding="ascii", errors="replace")
    man["factory_queue"] = queue
    (sdir / "manifest.json").write_text(json.dumps(man, indent=1))
    return {"ok": True, "queued": len(queue), "bat": str(bat),
            "items": [{"object": e["object"], "subject": e["subject"]} for e in queue]}


@router.post("/reconcile/{sid}")
async def reconcile(sid: str):
    """Measure the APPROVED canon with SAM3 and rewrite the plan's layout from it,
    then hand down a PRE-VERDICT on the pairing (John 2026-07-30: never present a
    canon+blueprint pair the machine hasn't judged first). Evidence saved per run."""
    import math
    import asyncio
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    canon = sdir / "canon.png"
    if not canon.exists():
        return JSONResponse({"error": "canon required first"}, status_code=409)
    plan = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    prog = sdir / "reconcile-progress.json"
    targets = [(i, o) for i, o in enumerate(plan["objects"]) if o.get("category") != "clutter"]
    cuts_dir = sdir / "cutouts-measure"; cuts_dir.mkdir(exist_ok=True)

    def _bbox(png_bytes):
        import io as _io
        from PIL import Image as _Im
        import numpy as _np
        im = _Im.open(_io.BytesIO(png_bytes)).convert("RGBA")
        a = _np.array(im)[:, :, 3]
        ys, xs = _np.nonzero(a > 128)
        if len(xs) < 400:
            return None
        return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

    boxes = {}
    found: dict = {}                                     # name -> bool, streamed to the progress file
    try:
        async with httpx.AsyncClient(timeout=20.0) as cl:
            up = await cl.post(f"{COMFY_MAIN}/upload/image",
                               files={"image": (f"v15f-{sid}-canon.png", canon.read_bytes(), "image/png")},
                               data={"overwrite": "true"})
            canon_name = up.json()["name"]
            for n, (i, o) in enumerate(targets):
                prog.write_text(json.dumps({"done": n, "total": len(targets), "current": o["name"], "found": found}))
                sub = await cl.post(f"{COMFY_MAIN}/prompt", json={"prompt": _sam3_graph(canon_name, o["name"])})
                pid = sub.json()["prompt_id"]
                cut = None
                for _ in range(30):
                    await asyncio.sleep(1.0)
                    h = (await cl.get(f"{COMFY_MAIN}/history/{pid}")).json()
                    rec = h.get(pid)
                    if rec and rec.get("outputs"):
                        for node in rec["outputs"].values():
                            for im in node.get("images", []):
                                img = await cl.get(f"{COMFY_MAIN}/view",
                                                   params={"filename": im["filename"],
                                                           "subfolder": im.get("subfolder", ""),
                                                           "type": im.get("type", "output")})
                                cut = img.content
                        break
                if cut:
                    (cuts_dir / f"obj-{i}.png").write_bytes(cut)
                    bb = _bbox(cut)
                    if bb:
                        boxes[i] = bb
                found[o["name"]] = i in boxes            # PROMPT-FIDELITY: is the asked-for object IN the picture?
                prog.write_text(json.dumps({"done": n + 1, "total": len(targets), "current": o["name"], "found": found}))
    except Exception as exc:
        prog.write_text(json.dumps({"done": 0, "total": 0, "error": str(exc)}))
        return JSONResponse({"error": f"measurement failed: {exc}"}, status_code=502)

    # single-view floor projection: eye 1.65 m, level camera, hfov ~66°, 1536x864
    W_img, H_img = 1536.0, 864.0
    f = (W_img / 2) / math.tan(math.radians(66) / 2)
    cx, cy = W_img / 2, H_img / 2
    raw = {}
    for i, (x0, x1, y0, y1) in boxes.items():
        if y1 <= cy + 8:                                 # bottom above horizon: wall-hung, unmeasurable
            continue
        Z = 1.65 * f / (y1 - cy)
        X = ((x0 + x1) / 2 - cx) * Z / f
        wm = (x1 - x0) * Z / f
        raw[i] = {"X": X, "Z": Z, "w": wm}
    W, D = plan["width_m"], plan["depth_m"]
    applied = 0
    if len(raw) >= 3:                                    # too few points = no honest layout
        xs = [v["X"] for v in raw.values()]; zs = [v["Z"] for v in raw.values()]
        x_lo, x_hi = min(xs), max(xs); z_lo, z_hi = min(zs), max(zs)
        sx = (W - 1.2) / max(0.5, x_hi - x_lo); sz = (D - 1.2) / max(0.5, z_hi - z_lo)
        for i, v in raw.items():
            o = plan["objects"][i]
            o["x_m"] = round(0.6 + (v["X"] - x_lo) * sx, 2)
            o["z_m"] = round(0.6 + (v["Z"] - z_lo) * sz, 2)
            if 0.3 <= v["w"] <= 3.5:
                o["w_m"] = round(v["w"], 2)
            applied += 1
    new_plan = sanitize_plan(plan, 0)
    # PRE-VERDICT: does the blueprint still tell the photo's story after sanitize?
    measured = [i for i in raw]
    inversions = 0
    for a in range(len(measured)):
        for b in range(a + 1, len(measured)):
            ia, ib = measured[a], measured[b]
            if abs(raw[ia]["X"] - raw[ib]["X"]) < 0.4:
                continue
            photo = raw[ia]["X"] < raw[ib]["X"]
            board = new_plan["objects"][ia]["x_m"] < new_plan["objects"][ib]["x_m"]
            if photo != board:
                inversions += 1
    coverage = len(raw) / max(1, len(targets))
    present = [plan["objects"][i]["name"] for i, _ in targets if i in boxes]
    missing = [plan["objects"][i]["name"] for i, _ in targets if i not in boxes]
    prompt_fidelity = len(present) / max(1, len(targets))
    order_ok = inversions == 0
    verdict = "green" if coverage >= 0.6 and order_ok and len(raw) >= 3 and prompt_fidelity >= 0.75 else \
              "amber" if coverage >= 0.35 and inversions <= 1 else "red"
    evidence = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "verdict": verdict,
                "coverage": round(coverage, 2), "measured": len(raw), "of": len(targets),
                "present": present, "missing": missing,
                "prompt_fidelity": round(prompt_fidelity, 2),
                "order_inversions": inversions,
                "objects": [{"i": i, "name": plan["objects"][i]["name"], "bbox": boxes.get(i),
                             "projected": raw.get(i)} for i, _ in targets]}
    (sdir / "reconcile-evidence.json").write_text(json.dumps(evidence, indent=1))
    if verdict != "red":                                 # red = never apply a broken measurement
        (sdir / "plan.json").write_text(json.dumps(new_plan, indent=1))
        plan_out = new_plan
    else:
        plan_out = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    man_path = sdir / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))   # re-read + merge
    man["reconcile"] = {k: evidence[k] for k in ("at", "verdict", "coverage", "measured", "of")}
    man_path.write_text(json.dumps(man, indent=1))
    prog.write_text(json.dumps({"done": len(targets), "total": len(targets), "verdict": verdict}))
    return {"ok": True, "plan": plan_out, "verdict": verdict, "measured": len(raw),
            "of": len(targets), "applied": applied, "order_ok": order_ok,
            "present": present, "missing": missing, "prompt_fidelity": round(prompt_fidelity, 2)}


@router.get("/reconcile-progress/{sid}")
async def reconcile_progress(sid: str):
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    try:
        return json.loads((OUT_DIR / f"v15f_{sid}" / "reconcile-progress.json").read_text(encoding="utf-8"))
    except Exception:
        return {"done": 0, "total": 0}


@router.get("/session/{sid}")
async def session_state(sid: str):
    """Restore a session after a page refresh — the disk is the memory."""
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    if not (sdir / "plan.json").exists():
        return JSONResponse({"error": "unknown session"}, status_code=404)
    plan = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    try:
        man = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        man = {}
    evidence = None
    try:
        ev = json.loads((sdir / "reconcile-evidence.json").read_text(encoding="utf-8"))
        evidence = {k: ev.get(k) for k in ("verdict", "coverage", "measured", "of", "present", "missing")}
    except Exception:
        pass
    return {"session_id": sid, "plan": plan, "assets": man.get("assets", {}),
            "prompt": man.get("prompt", ""),
            "has_canon": (sdir / "canon.png").exists(),
            "has_queue": (sdir / "factory-queue.json").exists(),
            "evidence": evidence}


@router.post("/branch/{sid}")
async def branch_session(sid: str):
    """⑂ Fork a session (John 2026-07-30): forward = branch. The copy carries the
    plan + canon + queue; the original stays pristine; ancestry is recorded."""
    import shutil
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    src = OUT_DIR / f"v15f_{sid}"
    if not (src / "plan.json").exists():
        return JSONResponse({"error": "unknown session"}, status_code=404)
    new_sid = uuid.uuid4().hex[:8]
    dst = OUT_DIR / f"v15f_{new_sid}"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("plan.json", "canon.png", "canon-lucasarts.png", "factory-queue.json",
                 "reconcile-evidence.json"):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    if (src / "cutouts").exists():
        shutil.copytree(src / "cutouts", dst / "cutouts", dirs_exist_ok=True)
    try:
        man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        man = {}
    man["session"] = new_sid
    man["branched_from"] = sid
    man["branched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (dst / "manifest.json").write_text(json.dumps(man, indent=1))
    return {"ok": True, "session_id": new_sid, "branched_from": sid}


@router.get("/sessions")
async def list_sessions():
    """Every session on disk, newest first — the forward button's ride list."""
    rows = []
    try:
        for d in OUT_DIR.glob("v15f_*"):
            if not (d / "plan.json").exists():
                continue
            try:
                man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            except Exception:
                man = {}
            rows.append({"session": d.name.replace("v15f_", ""),
                         "prompt": man.get("prompt", ""),
                         "locked_at": man.get("locked_at", ""),
                         "branched_from": man.get("branched_from"),
                         "reconcile": man.get("reconcile"),
                         "has_canon": (d / "canon.png").exists(),
                         "has_queue": (d / "factory-queue.json").exists()})
    except Exception:
        pass
    rows.sort(key=lambda r: r.get("locked_at", ""), reverse=True)
    return {"sessions": rows[:40]}


# ---------------------------------------------------------------- THE LINE
# Canon-first staged factory (John, 2026-07-30): the room canon is the room's
# own PHOTO CHECK; each object cut from it then walks
#   photo -> (amodal complete?) -> John's photo verdict -> OBJECT CANON
#   -> hero mesh -> mesh verdict -> paint -> paint verdict -> seated in the room
# with every verdict made inside the single v15 view. Mesh/paint approvals are
# PROXIED to the Pick Board (:8194) so there is exactly ONE approval writer.

import subprocess
import sys

PAINTSHOP_PY = Path(r"C:\Users\JohnM\ComfyUI-Installs\ComfyUI-PaintShop\.venv\Scripts\python.exe")
RAW_INTAKE = CEO_3D / "worlds" / "warehouse" / "source" / "cutouts" / "raw"
WAREHOUSE_OUT = CEO_3D / "worlds" / "warehouse" / "output"
OBJ_CANON_DIR = CEO_3D / "worlds" / "warehouse" / "source" / "object-canon"
PICKBOARD = "http://127.0.0.1:8194"
_RUNNER: dict = {"proc": None, "slug": None}


def _queue_entry(sdir: Path, slug: str) -> dict | None:
    try:
        for e in json.loads((sdir / "factory-queue.json").read_text(encoding="utf-8")):
            if e.get("slug") == slug:
                return e
    except Exception:
        pass
    return None


@router.get("/photo/{sid}/{slug}")
async def line_photo(sid: str, slug: str, which: str = "cutout"):
    if not (re.fullmatch(r"[0-9a-f]{8}", sid) and re.fullmatch(r"[a-z0-9\-]{2,40}", slug)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    path = {"cutout": sdir / "cutouts" / f"{slug}.png",
            "completed": RAW_INTAKE / f"{slug}.png",
            "original": RAW_INTAKE / f"{slug}.pre-amodal.bak.png"}.get(which)
    if which == "original" and path is not None and not path.exists():
        path = RAW_INTAKE / f"{slug}.png"                # never amodal'd: the intake IS the original
    if path is None or not path.exists():
        return JSONResponse({"error": "no such image yet"}, status_code=404)
    return FileResponse(path, media_type="image/png")


@router.post("/amodal/{sid}/{slug}")
async def line_amodal(sid: str, slug: str, roll: int = 0):
    """Flux-Fill imagines the cutout's hidden parts — subprocess of the PROVEN tool."""
    if not (re.fullmatch(r"[0-9a-f]{8}", sid) and re.fullmatch(r"[a-z0-9\-]{2,40}", slug)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    src = OUT_DIR / f"v15f_{sid}" / "cutouts" / f"{slug}.png"
    if not src.exists():
        return JSONResponse({"error": "no cutout for this object"}, status_code=404)
    py = PAINTSHOP_PY if PAINTSHOP_PY.exists() else Path(sys.executable)
    seed = 20260730 + int(roll)
    import asyncio

    def run():
        return subprocess.run([str(py), str(CEO_3D / "tools" / "amodal-fill.py"), str(src), slug, str(seed)],
                              cwd=str(CEO_3D), capture_output=True, text=True, timeout=420)
    try:
        r = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "completion timed out — is the Mesh engine (8188) up?"}, status_code=504)
    done = (RAW_INTAKE / f"{slug}.png").exists() and r.returncode == 0
    if done:                                             # PRE-VERDICT: a blank completion never reaches John
        try:
            import io as _io
            from PIL import Image as _Im
            import numpy as _np
            arr = _np.array(_Im.open(RAW_INTAKE / f"{slug}.png").convert("L"))
            if float(arr.std()) < 8.0:
                done = False
                r.stdout = (r.stdout or "") + "\ncompletion came back blank — re-roll (fresh seed) or approve the original"
        except Exception:
            pass
    tail = [ln for ln in (r.stdout or "").strip().splitlines()[-3:]]
    if not done:
        tail += (r.stderr or "").strip().splitlines()[-3:]
        return JSONResponse({"error": " / ".join(tail) or "completion failed"}, status_code=502)
    return {"ok": True, "seed": seed, "log": tail}


@router.post("/photo-approve/{sid}/{slug}")
async def photo_approve(sid: str, slug: str, body: dict | None = None):
    """John's photo verdict — the approved image BECOMES the object's canon."""
    if not (re.fullmatch(r"[0-9a-f]{8}", sid) and re.fullmatch(r"[a-z0-9\-]{2,40}", slug)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    choice = str((body or {}).get("choice", "completed"))
    cur = RAW_INTAKE / f"{slug}.png"
    bak = RAW_INTAKE / f"{slug}.pre-amodal.bak.png"
    if not cur.exists():
        return JSONResponse({"error": "no intake image to approve"}, status_code=404)
    if choice == "original" and bak.exists():            # completion rejected: rewind it, keep both
        cur.rename(RAW_INTAKE / f"{slug}.amodal-rejected-{int(time.time())}.bak.png")
        bak.rename(cur)
    e = _queue_entry(OUT_DIR / f"v15f_{sid}", slug) or {}
    OBJ_CANON_DIR.mkdir(parents=True, exist_ok=True)
    (OBJ_CANON_DIR / f"{slug}.png").write_bytes(cur.read_bytes())
    prov = {"slug": slug, "object": e.get("object"), "subject": e.get("subject"),
            "birth": "canon-cut", "room_session": sid,
            "room_canon": f"output/v15f_{sid}/canon.png",
            "completer": None if choice == "original" else {"model": "flux1-fill-dev", "tool": "amodal-fill.py"},
            "choice": choice, "approved_by": "John",
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "law": "the approved photo IS the object's identity; mesh and paint derive from it"}
    (OBJ_CANON_DIR / f"{slug}.provenance.json").write_text(json.dumps(prov, indent=1))
    return {"ok": True, "object_canon": f"{slug}.png", "provenance": prov}


@router.post("/line-run/{sid}/{slug}")
async def line_run(sid: str, slug: str):
    """Mesh+paint this ONE approved object via make-prop (gates honored). One GPU job at a time."""
    if not (re.fullmatch(r"[0-9a-f]{8}", sid) and re.fullmatch(r"[a-z0-9\-]{2,40}", slug)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    if not (OBJ_CANON_DIR / f"{slug}.png").exists():
        return JSONResponse({"error": "photo not approved yet — the object canon comes first"}, status_code=409)
    p = _RUNNER.get("proc")
    if p is not None and p.poll() is None:
        return JSONResponse({"error": f"factory busy with {_RUNNER.get('slug')}"}, status_code=409)
    e = _queue_entry(OUT_DIR / f"v15f_{sid}", slug)
    if not e:
        return JSONResponse({"error": "object not in this session's queue"}, status_code=404)
    log = open(OUT_DIR / f"v15f_{sid}" / f"line-{slug}.log", "ab")
    proc = subprocess.Popen(["node", "tools/make-prop.mjs", e["subject"]],
                            cwd=str(CEO_3D), stdout=log, stderr=subprocess.STDOUT)
    _RUNNER["proc"], _RUNNER["slug"] = proc, slug
    return {"ok": True, "pid": proc.pid, "subject": e["subject"]}


@router.post("/verdict/{slug}")
async def line_verdict(slug: str, body: dict):
    """Proxy John's mesh/paint verdict to the Pick Board — ONE approval writer everywhere."""
    if not re.fullmatch(r"[a-z0-9\-]{2,40}", slug):
        return JSONResponse({"error": "bad slug"}, status_code=400)
    stage = str((body or {}).get("stage", ""))
    good = bool((body or {}).get("ok", False))
    if stage not in ("mesh", "paint"):
        return JSONResponse({"error": "stage must be mesh or paint"}, status_code=400)
    payload = {"slug": "warehouse", "id": slug, "stage": stage}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cl:
            if good:
                r = await cl.post(f"{PICKBOARD}/api/approve", json=payload)
            else:
                payload["reason"] = str((body or {}).get("reason", "flagged from the v15 line"))[:120]
                payload["note"] = str((body or {}).get("note", ""))[:500]
                r = await cl.post(f"{PICKBOARD}/api/flag", json=payload)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"Pick Board unreachable: {exc} — is 8194 up?"}, status_code=502)


@router.get("/line/{sid}")
async def line_status(sid: str):
    """File-presence truth for every object on this session's line (the poll target)."""
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    try:
        queue = json.loads((sdir / "factory-queue.json").read_text(encoding="utf-8"))
    except Exception:
        queue = []
    out = []
    for e in queue:
        slug = e.get("slug", "")
        d = WAREHOUSE_OUT / slug
        mesh, painted = d / f"0-{slug}.glb", d / f"0-{slug}_painted.glb"
        out.append({
            "slug": slug, "object": e.get("object"), "subject": e.get("subject"),
            "cutout": (sdir / "cutouts" / f"{slug}.png").exists(),
            "completed": (RAW_INTAKE / f"{slug}.pre-amodal.bak.png").exists(),
            "intake": (RAW_INTAKE / f"{slug}.png").exists(),
            "photo_approved": (OBJ_CANON_DIR / f"{slug}.png").exists(),
            "mesh": mesh.exists(),
            "mesh_kb": round(mesh.stat().st_size / 1024) if mesh.exists() else 0,
            "mesh_approved": (d / "mesh-approval.json").exists(),
            "painted": painted.exists(),
            "painted_kb": round(painted.stat().st_size / 1024) if painted.exists() else 0,
            "paint_approved": (d / "paint-approval.json").exists(),
        })
    p = _RUNNER.get("proc")
    return {"objects": out,
            "runner": {"busy": p is not None and p.poll() is None, "slug": _RUNNER.get("slug")}}


@router.get("/line-glb/{slug}")
async def line_glb(slug: str, kind: str = "mesh"):
    """Serve this prop's mesh (unpainted) or painted GLB for the in-view spin verdict."""
    if not re.fullmatch(r"[a-z0-9\-]{2,40}", slug):
        return JSONResponse({"error": "bad slug"}, status_code=400)
    d = WAREHOUSE_OUT / slug
    path = d / (f"0-{slug}_painted.glb" if kind == "painted" else f"0-{slug}.glb")
    if not path.exists():
        return JSONResponse({"error": "not there yet"}, status_code=404)
    return FileResponse(path, media_type="model/gltf-binary")


@router.post("/rematch/{sid}")
async def rematch(sid: str):
    """Re-run warehouse matching after new props finish — the room seats its own children."""
    if not re.fullmatch(r"[0-9a-f]{8}", sid):
        return JSONResponse({"error": "bad session"}, status_code=400)
    sdir = OUT_DIR / f"v15f_{sid}"
    try:
        plan = json.loads((sdir / "plan.json").read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "unknown session"}, status_code=404)
    assets = {}
    for i, o in enumerate(plan["objects"]):
        slug = match_asset(o["name"], o.get("category", "object"))
        if slug:
            assets[str(i)] = {"slug": slug, "url": f"/api/v15fable/asset/{slug}"}
    man_path = sdir / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))   # re-read + merge, never from memory
    man["assets"] = assets
    man_path.write_text(json.dumps(man, indent=1))
    return {"ok": True, "plan": plan, "assets": assets}


@router.get("/health")
async def health():
    canon_up = False
    try:
        canon_up = httpx.get(f"{COMFY_MAIN}/system_stats", timeout=2.0).status_code == 200
    except Exception:
        pass
    return {"ok": True, "ollama_model": _ollama_model(), "warehouse_assets": len(_warehouse_index()),
            "canon_engine_8188": canon_up}
