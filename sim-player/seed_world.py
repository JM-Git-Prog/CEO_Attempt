"""sim-player/seed_world.py — give Sam his own copy of the neighborhood, and take it back between rounds.

`worlds/<sim slug>/` is seeded from the LATEST version of Mr. John's Neighborhood (read, never written):
its `<N>-world.json` becomes the sim's `0-world.json` (slug and name rewritten; the `brief` inside is
what the Neighbourhood Builder edits to make the next version — `place_brief()` in
neighbourhood-service.py reads exactly that), and the GLB / sky / thumbnail beside it are copied so the
5173 viewer can show the sim world. `project.json` says it is not the home.

`reset()` removes every sim version above 0 — the loop's own artifacts, never John's (this file
refuses to touch any slug that does not start with "sim-"). Versions the loop wants to keep are
copied into the round folder by the loop before reset (manifest + thumbnail only; a GLB is 36 MB).

    python seed_world.py --seed            # (re)seed from the home world
    python seed_world.py --reset           # drop sim versions > 0
    python seed_world.py --status
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SIM_ONLY = re.compile(r"^sim-[a-z0-9-]{2,40}$")


def _versions(world_dir: Path) -> list[int]:
    wd = world_dir / "output" / "world"
    try:
        return sorted(int(f.name.split("-")[0]) for f in wd.iterdir() if re.match(r"^\d+-world\.json$", f.name))
    except OSError:
        return []


def _guard(slug: str) -> None:
    if not SIM_ONLY.match(slug or ""):
        raise RuntimeError(f"refusing to touch {slug!r}: only a sim- world may be seeded or reset")


def seed(worlds: Path = common.WORLDS, home: str = common.HOME_SLUG, slug: str = common.SIM_SLUG, *, force: bool = False) -> dict:
    """Copy the home world's latest version in as the sim's version 0. Idempotent unless force."""
    _guard(slug)
    src_dir = worlds / home
    idx = _versions(src_dir)
    if not idx:
        raise RuntimeError(f"the home world {home} has no <N>-world.json under {src_dir / 'output' / 'world'}")
    n = idx[-1]
    dst = worlds / slug
    dst_wd = dst / "output" / "world"
    if _versions(dst) and not force:
        return {"slug": slug, "seeded": False, "why": "already seeded", "versions": _versions(dst), "from": f"{home} v{n}"}
    if dst.exists() and force:
        shutil.rmtree(dst)
    dst_wd.mkdir(parents=True, exist_ok=True)
    man = json.loads((src_dir / "output" / "world" / f"{n}-world.json").read_text(encoding="utf-8"))
    man["slug"] = slug
    if "display_name" in man:
        man["display_name"] = "Sam's Neighborhood (sim)"
    man["_sim"] = {"seeded_from": f"{home} v{n}", "at": common.now_iso(), "note": "Sam's copy — reset by sim-player/seed_world.py between rounds; never the home world"}
    copied = []
    for f in (src_dir / "output" / "world").iterdir():
        if not f.name.startswith(f"{n}-world"):
            continue
        target = dst_wd / f.name.replace(f"{n}-world", "0-world", 1)
        if f.suffix == ".json":
            target.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            shutil.copy2(f, target)
        copied.append(target.name)
    (dst / "project.json").write_text(json.dumps({
        "schema_version": 1, "slug": slug, "display_name": "Sam's Neighborhood (sim)", "home": False,
        "created_at": common.now_iso(),
        "notes": f"The Sam Loop's copy of {home} (seeded from v{n}). Sam builds here; the loop resets it every round. Never John's neighborhood (decision 23).",
    }, indent=2), encoding="utf-8")
    return {"slug": slug, "seeded": True, "from": f"{home} v{n}", "files": copied}


def reset(worlds: Path = common.WORLDS, slug: str = common.SIM_SLUG, *, keep_manifests_to: Path | None = None) -> dict:
    """Drop every sim version above 0. Optionally keep each dropped version's manifest + thumbnail in `keep_manifests_to`."""
    _guard(slug)
    wd = worlds / slug / "output" / "world"
    dropped = []
    for v in _versions(worlds / slug):
        if v == 0:
            continue
        for f in list(wd.iterdir()):
            if not f.name.startswith(f"{v}-world"):
                continue
            if keep_manifests_to and f.suffix in (".json", ".png"):
                keep_manifests_to.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, keep_manifests_to / f.name)
            f.unlink()
            dropped.append(f.name)
    return {"slug": slug, "dropped": dropped, "versions": _versions(worlds / slug)}


def status(worlds: Path = common.WORLDS, slug: str = common.SIM_SLUG) -> dict:
    return {"slug": slug, "versions": _versions(worlds / slug), "home": common.HOME_SLUG, "home_versions": _versions(worlds / common.HOME_SLUG)}


def selftest() -> int:
    import tempfile
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        worlds = Path(td)
        home = worlds / "mr-johns-neighborhood" / "output" / "world"
        home.mkdir(parents=True)
        for v in (8, 9):
            (home / f"{v}-world.json").write_text(json.dumps({"slug": "mr-johns-neighborhood", "display_name": "Mr. John's", "brief": {"houses": [1, 2, 3, 4]}}))
            (home / f"{v}-world.glb").write_bytes(b"GLB" * 10)
            (home / f"{v}-world-thumbnail.png").write_bytes(b"PNG")
        out = seed(worlds, "mr-johns-neighborhood", "sim-neighborhood")
        check("seeds version 0 from the home's latest (v9)", out["seeded"] and out["from"].endswith("v9") and sorted(out["files"]) == ["0-world-thumbnail.png", "0-world.glb", "0-world.json"], str(out))
        man = json.loads((worlds / "sim-neighborhood" / "output" / "world" / "0-world.json").read_text())
        check("the manifest is renamed and keeps the brief", man["slug"] == "sim-neighborhood" and man["brief"]["houses"] == [1, 2, 3, 4] and man["_sim"]["seeded_from"] == "mr-johns-neighborhood v9")
        check("project.json says not home", json.loads((worlds / "sim-neighborhood" / "project.json").read_text())["home"] is False)
        check("seeding again is a no-op", seed(worlds, "mr-johns-neighborhood", "sim-neighborhood")["seeded"] is False)
        check("the home world was not written", sorted(f.name for f in home.iterdir()) == ["8-world-thumbnail.png", "8-world.glb", "8-world.json", "9-world-thumbnail.png", "9-world.glb", "9-world.json"])
        sim = worlds / "sim-neighborhood" / "output" / "world"
        (sim / "1-world.json").write_text("{}"); (sim / "1-world.glb").write_bytes(b"x"); (sim / "1-world-thumbnail.png").write_bytes(b"p")
        keep = worlds / "keep"
        r = reset(worlds, "sim-neighborhood", keep_manifests_to=keep)
        check("reset drops v1 and keeps its manifest + thumbnail", r["versions"] == [0] and sorted(r["dropped"]) == ["1-world-thumbnail.png", "1-world.glb", "1-world.json"] and (keep / "1-world.json").exists() and not (keep / "1-world.glb").exists(), str(r))
        try:
            reset(worlds, "mr-johns-neighborhood"); check("  trips: reset refuses the home world", False)
        except RuntimeError as e:
            check("  trips: reset refuses the home world", "sim-" in str(e))
        try:
            seed(worlds, "mr-johns-neighborhood", "mr-johns-neighborhood", force=True); check("  trips: seed refuses a non-sim target", False)
        except RuntimeError:
            check("  trips: seed refuses a non-sim target", True)
        try:
            seed(worlds, "nowhere", "sim-x"); check("  trips: a missing home world is an error, not an empty seed", False)
        except RuntimeError:
            check("  trips: a missing home world is an error, not an empty seed", True)
    print(f"\n{'ALL GREEN' if not fails else 'FAILED: ' + ', '.join(fails)} — {len(fails)} of 9 checks failed")
    return 1 if fails else 0


if __name__ == "__main__":
    common.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--reset", action="store_true"); ap.add_argument("--status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.seed:
        print(json.dumps(seed(force=a.force), indent=1))
    if a.reset:
        print(json.dumps(reset(), indent=1))
    if a.status or not (a.seed or a.reset):
        print(json.dumps(status(), indent=1))
