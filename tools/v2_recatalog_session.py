"""Diagnostic: re-run ONLY the Phase 3 vision catalog against a session's
on-disk views (from views_meta.json), to determine whether the empty
catalog.json was a transient Phase-2/3 handoff issue or a live catalog bug.

Reconstructs a MultiViewResult from views_meta.json and calls catalog_objects.
Does NOT touch meshes/scene — writes catalog.json in place. Diagnostic only.

Usage: python tools/v2_recatalog_session.py <session_id>
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from src.unified_pipeline.multi_view_generator import MultiViewResult, ViewResult
from src.unified_pipeline.vision_catalog import catalog_objects


def load_views(session_dir: Path) -> MultiViewResult:
    meta_path = session_dir / "artifacts" / "views_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    result = MultiViewResult(
        room_dimensions=tuple(meta.get("room_dimensions", (4.0, 4.0, 2.7))),
    )
    for v in meta["views"]:
        result.views.append(
            ViewResult(
                index=v["index"],
                canon_path=v["canon_path"],
                depth_path=v["depth_path"],
                camera_position=tuple(v.get("camera_position", (0, 1.6, 0))),
                camera_target=tuple(v.get("camera_target", (0, 1.4, -1.75))),
                camera_fov=v.get("camera_fov", 60.0),
                sha256=v.get("sha256", ""),
            )
        )
    return result


async def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/v2_recatalog_session.py <session_id>")
        return 2
    session_id = sys.argv[1]
    session_dir = Path("output") / session_id
    if not session_dir.is_dir():
        print(f"session dir not found: {session_dir}")
        return 1

    views = load_views(session_dir)
    print(f"Loaded {len(views.views)} views from views_meta.json")
    for v in views.views:
        exists = Path(v.canon_path).is_file()
        print(f"  view {v.index}: canon exists={exists}  {v.canon_path}")

    brief_path = session_dir / "artifacts" / "brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8")) if brief_path.is_file() else {}

    def emit(etype, data):
        print(f"  [emit] {etype}: {json.dumps(data)[:200]}")

    catalog = await catalog_objects(views, brief, session_dir, emit_fn=emit)
    print(f"\nRESULT: {len(catalog.entries)} unique objects, "
          f"views_analyzed={catalog.views_analyzed}, "
          f"total_detections={catalog.total_detections}")
    for e in catalog.entries:
        print(f"  - {e.name} [{e.category}/{e.material}] views={e.views_visible_in}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
