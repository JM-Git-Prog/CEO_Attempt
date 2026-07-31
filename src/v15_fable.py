"""v15_Fable — Fable's standalone prompt→blueprint→walkable-world pipeline.

STEERING (version law, John 2026-07-31): this code implements THE LINE.
Architecture doc: CEO_Attempt/THE-LINE-ARCHITECTURE.md · reviewable canvas:
CEO-3D-World/workflows/THE-LINE.ui.json · version manifest (append-only):
CEO-3D-World/workflows/THE-LINE-VERSIONS.json. After each VALIDATED full run,
snapshot doc+canvas into workflows/line-history/ and bump the manifest — the
live files always point at the newest validated version.

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
 "shell": {"floor": "concrete", "walls": "drywall", "ceiling": "flat", "trim": "baseboard"},
 "doors":   [{"wall": "S", "offset_m": 3.0, "width_m": 1.0, "type": "standard"}],
 "windows": [{"wall": "E", "offset_m": 2.0, "width_m": 1.6, "sill_m": 0.9, "type": "standard"}],
 "pillars": [],
 "objects": [{"name": "bed", "category": "object", "x_m": 1.5, "z_m": 2.0, "w_m": 1.6, "d_m": 2.0, "h_m": 0.6, "rot_deg": 0}]}
Walls are N,S,E,W. offset_m measures along the wall from its left end.
shell.floor: concrete|wood-plank|tile|metal-plate|carpet. shell.walls: drywall|metal-siding|brick|concrete-block|wood-panel.
shell.ceiling: flat|steel-trusses|exposed-rafters|corrugated-metal. shell.trim: baseboard|baseboard+crown|none.
door type: standard|roll-up|fire|sliding-gate|double. window type: standard|loading-dock.
pillars: support columns as [{"x_m": 2.0, "z_m": 4.0}] when the space needs them.
x_m,z_m is the object's CENTER from the room's north-west corner. 3-9 objects.
CRITICAL: the JSON above is a SHAPE EXAMPLE ONLY — every value (objects, shell,
doors, windows) MUST come from the room description you were given. If the room
is a garage, there is no bed. Name the objects the description names.
category is one of: object (interactive movables: chair, bed, TV),
appliance (functional machines: stove, fridge), fixture (permanent: sink,
counter, lamp), decoration (rug, painting, plant, mirror), clutter (tiny
dressing: magazines, tissue box). Objects: ONLY what the description names, plus
at most 1-2 small clutter items that FIT the room's purpose (a garage gets an oil
can, never a rug)."""

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
                "keep_alive": "10m",   # 2026-07-31: survive all 3 variant calls — a mid-sequence
                                       # reload under render VRAM pressure lands on CPU and times out
                "prompt": (
                    f"You are an architect. Design ONE room for: {prompt}\n"
                    f"Variation directive: {variant_hint}\n{PLAN_SCHEMA_HINT}"
                ),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.9, "num_predict": 1600},  # 2026-07-31: the shell/type/pillar
                # schema outgrew 700 — a 7-object plan truncates mid-JSON and parses to fallback
            },
            timeout=75.0,  # 2026-07-31: 25s starved under GPU contention — a canon render on 8188
                           # owns the GPU while plans generate, and llama3.1 needs ~7s idle but
                           # 30-60s contended. Three straight fallback:procedural plans proved it.
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
    "tire": (0.7, 0.7, 0.8), "crate": (0.9, 0.9, 0.9), "drum": (0.6, 0.6, 0.9),
    "pallet": (1.2, 1.0, 0.15),
}

# 2026-07-31 (John): structural + finish elements are catalog citizens like props —
# the planner proposes them, the census verifies what the photo shows, the world
# renders them, the blueprint draws them. First entry of each tuple = the default.
_SHELL_CATALOG = {
    "floor":   ("wood-plank", "concrete", "tile", "metal-plate", "carpet"),
    "walls":   ("drywall", "metal-siding", "brick", "concrete-block", "wood-panel"),
    "ceiling": ("flat", "steel-trusses", "exposed-rafters", "corrugated-metal"),
    "trim":    ("baseboard", "baseboard+crown", "none"),
    "door_types":   ("standard", "roll-up", "fire", "sliding-gate", "double"),
    "window_types": ("standard", "loading-dock"),
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
            wmax = 4.2 if is_door else 3.0               # roll-up shipping doors are WIDE
            width = _clamp(o.get("width_m"), 0.7, wmax, 1.0)
            off = _clamp(o.get("offset_m"), 0.3 + width / 2, length - 0.3 - width / 2, length / 2)
            item = {"wall": wall, "offset_m": round(off, 2), "width_m": round(width, 2)}
            tkey = "door_types" if is_door else "window_types"
            t = str(o.get("type", "")).lower().strip()
            item["type"] = t if t in _SHELL_CATALOG[tkey] else _SHELL_CATALOG[tkey][0]
            if not is_door:
                item["sill_m"] = _clamp(o.get("sill_m"), 0.4, h - 1.2, 0.9)
            out.append(item)
        return out
    doors = _openings(p.get("doors"), True) or [{"wall": "S", "offset_m": round(w / 2, 2), "width_m": 1.1, "type": "standard"}]
    windows = _openings(p.get("windows"), False)
    sh = p.get("shell") if isinstance(p.get("shell"), dict) else {}
    shell = {}
    for key in ("floor", "walls", "ceiling", "trim"):
        v = str(sh.get(key, "")).lower().strip()
        shell[key] = v if v in _SHELL_CATALOG[key] else _SHELL_CATALOG[key][0]
    pillars = []
    for pl in (p.get("pillars") if isinstance(p.get("pillars"), list) else [])[:6]:
        pillars.append({"x_m": round(_clamp(pl.get("x_m"), 0.4, w - 0.4, w / 2), 2),
                        "z_m": round(_clamp(pl.get("z_m"), 0.4, d - 0.4, d / 2), 2)})
    objs = []
    for o in (p.get("objects") if isinstance(p.get("objects"), list) else [])[:12]:
        name = re.sub(r"[^a-z0-9 \-]", "", str(o.get("name", "prop")).lower()).strip()[:32] or "prop"
        base = next((s for k, s in _DEFAULT_SIZES.items() if k in name), (0.8, 0.8, 0.9))
        ow = _clamp(o.get("w_m"), 0.2, min(4.8, w - 1), base[0])
        od = _clamp(o.get("d_m"), 0.2, min(4.8, d - 1), base[1])
        oh = _clamp(o.get("h_m"), 0.02, h - 0.3, base[2])
        margin = max(ow, od) / 2 + 0.15
        cat = str(o.get("category", "")).lower()
        cat = cat if cat in _CATEGORIES else _default_category(name)
        if cat in ("clutter", "decoration") and any(kk in name for kk in _DEFAULT_SIZES):
            cat = _default_category(name)   # 2026-07-31: a known physical family (tires, crates)
                                            # is never mere dressing — the factory must mesh it
        objs.append({
            "name": name,
            "category": cat,
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
        "vibe": vibe, "palette": palette, "shell": shell, "pillars": pillars,
        "skylight": bool(p.get("skylight")),
        "doors": doors, "windows": windows, "objects": objs,
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
    if category == "object":                # 2026-07-31: symmetry — the slug side derives its
        category = _default_category(name)  # category from words; a generic plan side must too,
                                            # or "workbench"(object) never matches workbench(fixture)
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
    if model:
        try:  # 2026-07-31 one-GPU-user law: release llama's VRAM before the canon render —
            #  a 14GB resident model + Z-Image = sysmem spill and a wedged [0%] render
            httpx.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=8.0)
        except Exception:
            pass
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
    _free_engine(8190)                                   # hotswap law: shop cache out before Z-Image in
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
    shell_found: dict = {}                               # window/door -> bool: the SHELL census
    try:
        async with httpx.AsyncClient(timeout=20.0) as cl:
            up = await cl.post(f"{COMFY_MAIN}/upload/image",
                               files={"image": (f"v15f-{sid}-canon.png", canon.read_bytes(), "image/png")},
                               data={"overwrite": "true"})
            canon_name = up.json()["name"]

            async def _run_sam(target: str):
                sub = await cl.post(f"{COMFY_MAIN}/prompt", json={"prompt": _sam3_graph(canon_name, target)})
                pid = sub.json()["prompt_id"]
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
                                return img.content
                        return None
                return None

            for n, (i, o) in enumerate(targets):
                prog.write_text(json.dumps({"done": n, "total": len(targets), "current": o["name"], "found": found}))
                cut = await _run_sam(o["name"])
                if cut:
                    (cuts_dir / f"obj-{i}.png").write_bytes(cut)
                    bb = _bbox(cut)
                    if bb:
                        boxes[i] = bb
                found[o["name"]] = i in boxes            # PROMPT-FIDELITY: is the asked-for object IN the picture?
                prog.write_text(json.dumps({"done": n + 1, "total": len(targets), "current": o["name"], "found": found}))
            shell_boxes = {}
            for probe in ("window", "door", "skylight", "support pillar", "roll-up door"):  # SHELL census: what does the photo ACTUALLY have?
                prog.write_text(json.dumps({"done": len(targets), "total": len(targets),
                                            "current": f"checking the photo for {probe}s", "found": found}))
                cut = await _run_sam(probe)
                bb = _bbox(cut) if cut else None
                shell_found[probe] = bool(bb)
                shell_boxes[probe] = bb                  # kept: the wall it sits on is MEASURED below
    except Exception as exc:
        prog.write_text(json.dumps({"done": 0, "total": 0, "error": str(exc)}))
        return JSONResponse({"error": f"measurement failed: {exc}"}, status_code=502)

    # single-view floor projection: eye 1.65 m, level camera, hfov ~66°, 1536x864
    W_img, H_img = 1536.0, 864.0
    f = (W_img / 2) / math.tan(math.radians(66) / 2)
    cx, cy = W_img / 2, H_img / 2
    raw = {}
    for i, (x0, x1, y0, y1) in boxes.items():
        if y1 <= cy + 8:                                 # bottom above horizon: wall-hung, unplaceable
            continue
        Z = 1.65 * f / (y1 - cy)
        X = ((x0 + x1) / 2 - cx) * Z / f
        raw[i] = {"X": X, "Z": Z, "w": (x1 - x0) * Z / f, "h": (y1 - y0) * Z / f}
    W, D = plan["width_m"], plan["depth_m"]
    notes = []
    applied = 0
    if len(raw) >= 3:                                    # too few points = no honest layout
        # 2026-07-31 identical-views law (John): canon, blueprint and walkthrough must MATCH.
        # (a) ONE global scale k calibrates the guessed camera (hfov/eye read ~2x far):
        #     median of prior-width / projected-width across known object families.
        ratios = []
        for i, v in raw.items():
            nm = plan["objects"][i]["name"].lower()
            prior = next((s for kk, s in _DEFAULT_SIZES.items() if kk in nm), None)
            if prior and v["w"] > 0.05:
                ratios.append(prior[0] / v["w"])
        k = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
        k = min(1.6, max(0.35, k))
        # (b) Camera-anchored similarity transform — NEVER min-max: the workshop's 0.35m
        #     projected depth band was once stretched 13.6x across the room (noise must
        #     stay noise-sized), and its sign ran backward. The spawn IS the S door
        #     looking N, so: x_m = door_x + X·k, z_m = spawn_z − Z·k — what the canon
        #     camera saw is exactly what the first-person camera meets.
        door0 = (plan.get("doors") or [{}])[0]
        door_x = door0.get("offset_m", W / 2) if door0.get("wall", "S") == "S" else W / 2
        pos = {i: {"x": door_x + v["X"] * k, "z": (D - 1.4) - v["Z"] * k} for i, v in raw.items()}
        for ax, lo_lim, hi_lim in (("x", 0.6, W - 0.6), ("z", 0.6, D - 0.6)):
            lo = min(p[ax] for p in pos.values()); hi = max(p[ax] for p in pos.values())
            shift = (lo_lim - lo) if lo < lo_lim else ((hi_lim - hi) if hi > hi_lim else 0.0)
            for p in pos.values():
                p[ax] += shift                           # translate to fit; sanitize clamps residue
        for i, v in raw.items():
            o = plan["objects"][i]
            o["x_m"] = round(pos[i]["x"], 2)
            o["z_m"] = round(pos[i]["z"], 2)
            if 0.3 <= v["w"] * k <= 3.5:
                o["w_m"] = round(v["w"] * k, 2)
            if 0.2 <= v["h"] * k <= 2.4:                 # photo sets HEIGHT too (calibrated)
                o["h_m"] = round(v["h"] * k, 2)
            applied += 1
        for i in raw:                                    # canon rooms hug their walls: snap near-wall objects flush
            o = plan["objects"][i]
            dists = {"W": o["x_m"], "E": W - o["x_m"], "N": o["z_m"], "S": D - o["z_m"]}
            wall, dist = min(dists.items(), key=lambda kv: kv[1])
            lim = max(0.9, 0.12 * (W if wall in ("W", "E") else D))
            half = max(0.1, float(o.get("d_m", 0.5)) / 2)
            if dist <= lim:
                if wall == "W":   o["x_m"] = round(half + 0.18, 2)
                elif wall == "E": o["x_m"] = round(W - half - 0.18, 2)
                elif wall == "N": o["z_m"] = round(half + 0.18, 2)
                else:             o["z_m"] = round(D - half - 0.18, 2)
        # (c) The window lives where the PHOTO put it — wall from its bbox third.
        wb = shell_boxes.get("window") if shell_found.get("window") else None
        if wb and plan.get("windows"):
            wx = (wb[0] + wb[1]) / 2
            wwall = "W" if wx < W_img / 3 else ("E" if wx > 2 * W_img / 3 else "N")
            win0 = plan["windows"][0]
            if win0.get("wall") != wwall:
                notes.append(f"window moved to the {wwall} wall — measured from the photo")
            win0["wall"] = wwall
            win0["offset_m"] = round(D / 2, 2) if wwall in ("W", "E") else round(W * wx / W_img, 2)
        # (d) structural census — geometric sanity gates so SAM3 semantic collisions
        #     (a barrel is NOT a pillar) can't invent architecture the photo lacks.
        def _overlaps_object(bb):
            """SAM3 loves re-grabbing censused objects — reject any 'pillar' that mostly IS one."""
            bx0, bx1, by0, by1 = bb
            area = max(1, (bx1 - bx0) * (by1 - by0))
            for (ox0, ox1, oy0, oy1) in boxes.values():
                ix = max(0, min(bx1, ox1) - max(bx0, ox0))
                iy = max(0, min(by1, oy1) - max(by0, oy0))
                if ix * iy > 0.4 * area:
                    return True
            return False
        pb = shell_boxes.get("support pillar")
        if (pb and pb[3] > cy + 40 and pb[2] < cy - 60          # spans the horizon: floor-standing AND tall
                and (pb[3] - pb[2]) >= 3.0 * (pb[1] - pb[0])    # pillar-slender
                and not _overlaps_object(pb)):
            pZ = 1.65 * f / (pb[3] - cy)
            pX = ((pb[0] + pb[1]) / 2 - cx) * pZ / f
            plan["pillars"] = [{"x_m": round(door_x + pX * k, 2), "z_m": round((D - 1.4) - pZ * k, 2)}]
            notes.append("support pillar measured from the photo")
        else:
            plan["pillars"] = []                         # the census OWNS pillars: none proven = none
        sk = shell_boxes.get("skylight")
        if sk and sk[3] < cy:                            # a skylight lives entirely above the horizon
            plan["skylight"] = True
            notes.append("skylight measured from the photo")
        else:
            plan["skylight"] = False                     # ditto — stale census writes must not survive
        rb = shell_boxes.get("roll-up door")
        if rb and plan.get("doors") and (rb[1] - rb[0]) > 0.08 * W_img and (rb[1] - rb[0]) >= 0.9 * (rb[3] - rb[2]):
            # 2026-07-31: a BACK-wall roll-up at depth is small in frame — the old 15%/1.2 gate
            # rejected the warehouse canon's own door and llama's wrong wall stood uncorrected
            rx_c = (rb[0] + rb[1]) / 2
            rwall = "W" if rx_c < W_img / 3 else ("E" if rx_c > 2 * W_img / 3 else "N")
            rolld = dict(plan["doors"][0])
            rolld.update({"type": "roll-up", "wall": rwall,
                          "offset_m": round((D if rwall in ("W", "E") else W) / 2, 2),
                          "width_m": max(rolld.get("width_m", 1.0), 2.6)})
            if rwall != "S":                             # spawn stays at a personnel entry on S —
                entry = {"wall": "S", "offset_m": round(W / 2, 2), "width_m": 1.1, "type": "standard"}
                plan["doors"] = [entry, rolld]           # doors[0] = spawn; the roll-up rides second
            else:
                plan["doors"] = [rolld]
            notes.append(f"roll-up door on the {rwall} wall — measured from the photo")
    if not shell_found.get("window", True) and plan.get("windows"):
        notes.append(f"photo shows no windows — removed {len(plan['windows'])} invented window(s)")
        plan["windows"] = []
    if not shell_found.get("door", True):
        notes.append("no door visible in the photo — one kept for playability")
    try:                                                 # palette: floor/wall colors sampled from the photo itself
        from PIL import Image as _Im, ImageStat as _St
        cim = _Im.open(canon).convert("RGB")
        wpx, hpx = cim.size
        fl = _St.Stat(cim.crop((int(wpx * .35), int(hpx * .88), int(wpx * .65), hpx))).mean
        wl = _St.Stat(cim.crop((int(wpx * .30), int(hpx * .06), int(wpx * .70), int(hpx * .18)))).mean
        plan.setdefault("palette", {})
        plan["palette"]["floor"] = "#%02x%02x%02x" % tuple(int(x) for x in fl)
        plan["palette"]["wall"] = "#%02x%02x%02x" % tuple(int(x) for x in wl)
        notes.append("floor/wall colors sampled from the photo")
        spread = max(fl) - min(fl)                       # material CLASS measured, not guessed:
        if spread < 16 and 60 < sum(fl) / 3 < 205:       # low-sat mid-grey floor = bare concrete
            plan.setdefault("shell", {})["floor"] = "concrete"
            notes.append("floor reads as bare concrete in the photo")
        elif fl[0] > fl[2] + 22:                         # warm red-over-blue = wood
            plan.setdefault("shell", {})["floor"] = "wood-plank"
    except Exception:
        pass
    new_plan = sanitize_plan(plan, 0)
    if not shell_found.get("window", True):
        new_plan["windows"] = []                         # sanitize must not re-invent them
    for i, _ in targets:                                 # honesty flags ride in the shipped plan
        if i < len(new_plan.get("objects", [])):
            new_plan["objects"][i]["_measured"] = i in raw
    # PRE-VERDICT v2 (report 2026-07-30): GREEN must MEAN it — everything present,
    # everything photo-placed, order true, zero overlaps. Anything less is labeled.
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
    objs_np = [o for o in new_plan.get("objects", []) if o.get("category") != "clutter"]
    overlaps_n = 0
    for a in range(len(objs_np)):
        for b in range(a + 1, len(objs_np)):
            oa, ob = objs_np[a], objs_np[b]
            if (abs(oa["x_m"] - ob["x_m"]) < (oa["w_m"] + ob["w_m"]) / 2 - 0.02 and
                    abs(oa["z_m"] - ob["z_m"]) < (oa["d_m"] + ob["d_m"]) / 2 - 0.02):
                overlaps_n += 1
    coverage = len(raw) / max(1, len(targets))
    present = [plan["objects"][i]["name"] for i, _ in targets if i in boxes]
    missing = [plan["objects"][i]["name"] for i, _ in targets if i not in boxes]
    unplaced = [plan["objects"][i]["name"] for i, _ in targets if i in boxes and i not in raw]
    prompt_fidelity = len(present) / max(1, len(targets))
    order_ok = inversions == 0
    if missing:
        notes.append("missing from photo: " + ", ".join(missing))
    if unplaced:
        notes.append("in photo but not floor-placed (dashed = guess): " + ", ".join(unplaced))
    if overlaps_n:
        notes.append(f"{overlaps_n} footprint overlap(s) survived layout")
    green_ok = (not missing) and (not unplaced) and order_ok and overlaps_n == 0 and len(raw) >= 3
    verdict = "green" if green_ok else \
              "amber" if coverage >= 0.35 and inversions <= 1 else "red"
    evidence = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "verdict": verdict,
                "coverage": round(coverage, 2), "measured": len(raw), "of": len(targets),
                "present": present, "missing": missing, "unplaced": unplaced,
                "overlaps": overlaps_n, "notes": notes, "shell": shell_found,
                "shell_boxes": shell_boxes,              # diagnostic: what SAM3 actually grabbed
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
            "present": present, "missing": missing, "unplaced": unplaced,
            "overlaps": overlaps_n, "notes": notes,
            "prompt_fidelity": round(prompt_fidelity, 2)}


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
        evidence = {k: ev.get(k) for k in ("verdict", "coverage", "measured", "of",
                                           "present", "missing", "unplaced", "notes", "overlaps")}
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


def _free_engine(port: int) -> None:
    """96GB-RAM hotswap law (John, 2026-07-31): freeing a ComfyUI's VRAM is cheap —
    weights reload from the OS file cache in seconds, not from disk. Clear the OTHER
    engine before heavy GPU work so the two factories never spill each other into
    the 24GB card (tonight's wedge class: shop cache + Qwen job = 23.8GB thrash)."""
    try:
        httpx.post(f"http://127.0.0.1:{port}/free",
                   json={"unload_models": True, "free_memory": True}, timeout=6.0)
    except Exception:
        pass
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
    _free_engine(8190)                                   # hotswap law: shop cache out before Qwen in
    import asyncio

    def run():
        # 2026-07-31: detach from the server console's signal group — a stray CTRL event
        # killed a child at `import uuid` with exit 0xC000013A while the server lived on.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.run([str(py), str(CEO_3D / "tools" / "amodal-fill.py"), str(src), slug, str(seed)],
                              cwd=str(CEO_3D), capture_output=True, text=True, timeout=560,
                              creationflags=flags)
    log_f = OUT_DIR / f"v15f_{sid}" / f"amodal-{slug}.log"
    try:
        r = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired as exc:
        log_f.write_text(f"TIMEOUT 560s\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}", encoding="utf-8")
        return JSONResponse({"error": "completion timed out — is the Mesh engine (8188) up?"}, status_code=504)
    log_f.write_text(f"exit={r.returncode}\nstdout:\n{r.stdout or ''}\nstderr:\n{r.stderr or ''}",
                     encoding="utf-8")                   # the failure is never lost again
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


@router.post("/photo-unapprove/{sid}/{slug}")
async def photo_unapprove(sid: str, slug: str):
    """↩ Reverse a photo approval (John 2026-07-30: every stage needs a back).
    Renames only — nothing is ever destroyed."""
    if not (re.fullmatch(r"[0-9a-f]{8}", sid) and re.fullmatch(r"[a-z0-9\-]{2,40}", slug)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    oc = OBJ_CANON_DIR / f"{slug}.png"
    prov = OBJ_CANON_DIR / f"{slug}.provenance.json"
    if not oc.exists():
        return JSONResponse({"error": "nothing to un-approve"}, status_code=404)
    ts = int(time.time())
    oc.rename(OBJ_CANON_DIR / f"{slug}.unapproved-{ts}.bak.png")
    if prov.exists():
        prov.rename(OBJ_CANON_DIR / f"{slug}.provenance-{ts}.bak.json")
    return {"ok": True, "note": "photo approval reversed — the object is back at its photo stage"}


@router.post("/line-run/{sid}/{slug}")
async def line_run(sid: str, slug: str, lane: str = ""):
    """Mesh+paint this ONE approved object (gates honored). One GPU job at a time.
    lane="" → prod: make-prop.mjs (Hunyuan blast → MultiViews paint).
    lane="trellis" → The Line v1.1_Dev: TRELLIS 2 one-pass (mesh+texture together
    on 8188) via tools/trellis-prop.py. Same output contract (0-slug.glb +
    0-slug_painted.glb), so line-status, gates and seat are identical."""
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
    # 2026-07-31: same detachment as the amodal spawn — a stray console CTRL event killed
    # runner #4 silently mid-flight (log ends at SKIP render, no FAIL line, exit unseen).
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if lane == "trellis":
        import sys as _sys
        cmd = [_sys.executable, "-u", "tools/trellis-prop.py", slug]  # -u: unbuffered — a silent log hid the Q6_K failure for 2 min
    else:
        cmd = ["node", "tools/make-prop.mjs", e["subject"]]
    proc = subprocess.Popen(cmd, cwd=str(CEO_3D), stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags)
    _RUNNER["proc"], _RUNNER["slug"] = proc, slug
    return {"ok": True, "pid": proc.pid, "subject": e["subject"], "lane": lane or "prod"}


@router.post("/verdict/{slug}")
async def line_verdict(slug: str, body: dict):
    """Proxy John's mesh/paint verdict to the Pick Board — ONE approval writer everywhere."""
    if not re.fullmatch(r"[a-z0-9\-]{2,40}", slug):
        return JSONResponse({"error": "bad slug"}, status_code=400)
    stage = str((body or {}).get("stage", ""))
    good = bool((body or {}).get("ok", False))
    if stage not in ("render", "mesh", "paint"):
        return JSONResponse({"error": "stage must be render, mesh or paint"}, status_code=400)
    if good and stage == "render":
        return JSONResponse({"error": "render stage is flag-only here"}, status_code=400)
    payload = {"slug": "warehouse", "id": slug, "stage": stage}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cl:
            if good:
                r = await cl.post(f"{PICKBOARD}/api/approve", json=payload)
            else:
                payload["reason"] = str((body or {}).get("reason", "flagged from the v15 line"))[:120]
                payload["note"] = str((body or {}).get("note", ""))[:500]
                r = await cl.post(f"{PICKBOARD}/api/flag", json=payload)
        out = r.json()
        # a flagged mesh means the runner is waiting on an approval that will NEVER
        # come (found live 2026-07-30: the sofa's runner blocked the rug) — free it,
        # then VERIFY the kill actually cleared (constitution: never assume a kill).
        p = _RUNNER.get("proc")
        if (not good) and stage == "mesh" and p is not None and p.poll() is None and _RUNNER.get("slug") == slug:
            import asyncio
            p.kill()
            await asyncio.sleep(0.5)
            out["runner_freed"] = p.poll() is not None
        return JSONResponse(out, status_code=r.status_code)
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
    global _wh_cache
    _wh_cache = None                                     # a JUST-painted prop must seat NOW (2026-07-31)
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


@router.get("/engine-nodes")
async def engine_nodes(pat: str = ""):
    """Diagnostic: which node families + model files each engine actually has RIGHT NOW.
    Exists so a missing custom node is a one-GET fact, never a guess (2026-07-30)."""
    out = {}
    for label, port in (("mesh_8188", 8188), ("paint_8190", 8190)):
        try:
            async with httpx.AsyncClient(timeout=20.0) as cl:
                o = (await cl.get(f"http://127.0.0.1:{port}/object_info")).json()
            keys = list(o.keys())
            def _grab(pat):
                rx = re.compile(pat, re.I)
                return [k for k in keys if rx.search(k)][:12]
            def _opts(node, field):
                try:
                    return [x for x in o[node]["input"]["required"][field][0]]
                except Exception:
                    return []
            out[label] = {
                "up": True, "total_nodes": len(keys),
                "pat_matches": _grab(pat)[:40] if pat else [],
                "flux": _grab(r"flux"), "sam3": _grab(r"sam3"),
                "hunyuan": _grab(r"hy3d|hunyuan"),
                "inpaint_model_conditioning": "InpaintModelConditioning" in o,
                "dualclip": "DualCLIPLoader" in o,
                "unet_files": _opts("UNETLoader", "unet_name"),
                "ckpt_files": _opts("CheckpointLoaderSimple", "ckpt_name")[:20],
                "clip_files": [x for x in _opts("DualCLIPLoader", "clip_name1") if re.search(r"clip_l|t5", x, re.I)][:8],
                "vae_files": [x for x in _opts("VAELoader", "vae_name")][:8],
                "sam_ckpts": [x for x in _opts("CheckpointLoaderSimple", "ckpt_name") if re.search(r"sam3", x, re.I)],
            }
        except Exception as exc:
            out[label] = {"up": False, "error": str(exc)[:200]}
    return out


@router.get("/line-activity")
async def line_activity():
    """2026-07-31 (John): which stage of THE LINE is firing RIGHT NOW — feeds the
    live illuminator on the ComfyUI 'The Line' canvas. Derived from real state,
    never guessed: engine queues + runner + newest session's flags."""
    act = {"stage": "idle", "detail": ""}
    try:
        dirs = sorted((d for d in OUT_DIR.glob("v15f_*") if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        sdir = dirs[0] if dirs else None
        sid = sdir.name[5:] if sdir else None
        act["sid"] = sid
        prog = {}
        if sdir and (sdir / "reconcile-progress.json").exists():
            age = time.time() - (sdir / "reconcile-progress.json").stat().st_mtime
            prog = json.loads((sdir / "reconcile-progress.json").read_text(encoding="utf-8"))
            if age < 25 and "verdict" not in prog:
                return {**act, "stage": "census", "detail": prog.get("current", "measuring")}
        r8188 = {"queue_running": [], "queue_pending": []}
        try:
            async with httpx.AsyncClient(timeout=2.5) as cl:
                r8188 = (await cl.get("http://127.0.0.1:8188/queue")).json()
        except Exception:
            pass
        busy_8188 = bool(r8188.get("queue_running"))
        p = _RUNNER.get("proc")
        runner_busy = p is not None and p.poll() is None
        slug = _RUNNER.get("slug")
        if runner_busy:
            d = WAREHOUSE_OUT / (slug or "")
            if slug and (d / f"0-{slug}.glb").exists() and (d / "mesh-approval.json").exists():
                return {**act, "stage": "paint", "detail": slug or ""}
            if slug and (d / f"0-{slug}.glb").exists():
                return {**act, "stage": "gate-mesh", "detail": slug or ""}
            return {**act, "stage": "mesh", "detail": slug or ""}
        if sdir and (sdir / "canon-pending.json").exists() and busy_8188:
            return {**act, "stage": "canon", "detail": "Z-Image rendering"}
        if busy_8188:
            return {**act, "stage": "complete", "detail": "Qwen/SAM3 on 8188"}
        if sdir and (sdir / "factory-queue.json").exists():
            try:
                q = json.loads((sdir / "factory-queue.json").read_text(encoding="utf-8"))
                for e in (q if isinstance(q, list) else q.get("queue", [])):
                    s2 = e.get("slug", "")
                    d2 = WAREHOUSE_OUT / s2
                    if (RAW_INTAKE / f"{s2}.png").exists() and not (OBJ_CANON_DIR / f"{s2}.png").exists():
                        return {**act, "stage": "gate-photo", "detail": s2}
                    if (d2 / f"0-{s2}.glb").exists() and not (d2 / "mesh-approval.json").exists():
                        return {**act, "stage": "gate-mesh", "detail": s2}
                    if (d2 / f"0-{s2}_painted.glb").exists() and not (d2 / "paint-approval.json").exists():
                        return {**act, "stage": "gate-paint", "detail": s2}
            except Exception:
                pass
        if sdir and not (sdir / "canon.png").exists():
            return {**act, "stage": "plan", "detail": "llama planning / canon pending"}
    except Exception as exc:
        act["error"] = str(exc)[:120]
    return act


@router.get("/health")
async def health():
    canon_up = False
    try:
        canon_up = httpx.get(f"{COMFY_MAIN}/system_stats", timeout=2.0).status_code == 200
    except Exception:
        pass
    return {"ok": True, "ollama_model": _ollama_model(), "warehouse_assets": len(_warehouse_index()),
            "canon_engine_8188": canon_up}
