"""Mesh bench — score every generated mesh against its catalogue box.

Third bench in the family (plan_bench covers placement, ortho_bench covers
measurement); this one covers mesh fit. No server, no GPU, no ComfyUI: it reads
the .glb files a session already produced and the furniture catalogue already
in the repo.

Usage:
    python tools/mesh_bench.py                  # newest session
    python tools/mesh_bench.py 39009e89         # a session id prefix

Exit code is 0 when every mesh fits its box without deformation, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.unified_pipeline.mesh_qa import evaluate, MAX_ANISOTROPY  # noqa: E402
from src.unified_pipeline.plan_generator import _furniture_dims  # noqa: E402

OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "output"


def load_plan_names(session_dir: Path) -> dict[str, str]:
    """Map object id -> manifest name using the session's own spatial plan."""
    solution = session_dir / "artifacts" / "spatial_solution.json"
    if not solution.is_file():
        return {}
    data = json.loads(solution.read_text(encoding="utf-8"))
    plan = data.get("metric_plan") or {}
    return {
        str(p.get("id", "")): str(p.get("name", ""))
        for p in plan.get("object_placements", [])
        if p.get("id")
    }


def run(session_filter: str = "") -> int:
    if not OUTPUT_ROOT.is_dir():
        print(f"no output dir: {OUTPUT_ROOT}")
        return 1

    sessions = sorted(
        (d for d in OUTPUT_ROOT.iterdir()
         if d.is_dir() and (not session_filter or d.name.startswith(session_filter))),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    sessions = [s for s in sessions if (s / "meshes" / "normalized").is_dir()]
    if not sessions:
        print("no session with generated meshes matched")
        return 1

    session = sessions[0]
    names = load_plan_names(session)
    meshes = sorted((session / "meshes" / "normalized").glob("*.glb"))
    if not meshes:
        print(f"no meshes in {session.name}")
        return 1

    print("=" * 78)
    print(f"MESH FIT — session {session.name}   threshold anisotropy <= {MAX_ANISOTROPY}")
    print("=" * 78)

    failures = 0
    for mesh in meshes:
        # Instance suffixes (-1, -2) share one manifest object.
        object_id = mesh.stem
        name = names.get(object_id) or names.get(object_id.rsplit("-", 1)[0]) or "object"
        target = _furniture_dims(name)

        try:
            result = evaluate(mesh, target)
        except ValueError as exc:
            print(f"  {name:8} {mesh.stem[:12]}  UNREADABLE: {exc}")
            failures += 1
            continue

        mark = {"PASS": "ok  ", "ROTATE": "ROT ", "REGENERATE": "FAIL"}[result["verdict"]]
        print(f"\n  [{mark}] {name:8} {mesh.stem[:12]}")
        print(f"         raw mesh   {result['raw_bbox']}")
        print(f"         target box {result['target_dims']}")
        print(
            f"         as applied  scale {result['applied_scale']}"
            f"  anisotropy {result['applied_anisotropy']}"
        )
        if result["axis_map"] != [0, 1, 2]:
            print(
                f"         best remap  scale {result['best_scale']}"
                f"  anisotropy {result['best_anisotropy']}"
            )
        print(f"         -> {result['reason']}")
        if result["verdict"] == "REGENERATE":
            failures += 1

    print()
    print("=" * 78)
    print(f"{len(meshes) - failures} of {len(meshes)} mesh(es) fit without deformation")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else ""))
