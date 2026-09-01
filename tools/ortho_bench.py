"""Ortho bench - iterate on the measurement chain WITHOUT restarting the server.

The sibling of tools/plan_bench.py. That one covers placement; this one covers
everything upstream of it:

    render (already on disk) -> room outline -> uniform scale + QA residual
                             -> object segmentation -> metric placements
                             -> REAL PlanValidator

No server, no ComfyUI, no Ollama, no GPU. Runs in about a second, so the
measurement code can be iterated on directly instead of paying a restart and a
four minute pipeline run to see three numbers.

Usage:
    python tools/ortho_bench.py                 # every render in the test dir
    python tools/ortho_bench.py sep-render      # only matching filenames

Exit code is 0 when every render measures cleanly, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.unified_pipeline.ortho_plan import (  # noqa: E402
    detect_room_outline,
    segment_warm_objects,
    solve_scale_anchored,
    placements_from_ortho,
)
from src.unified_pipeline.plan_generator import _furniture_dims  # noqa: E402

RENDER_DIR = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\CEO-3D-World\workflows\ortho-test"
)

# What the brief said, so the bench can check the measurement against intent.
EXPECTED = {"table": 1, "chair": 2}
# The Brief fixes a MINIMUM footprint, so only one dimension is asserted.
KNOWN_WIDTH_M = 4.0


def name_blobs(boxes, expected):
    """Map blobs to manifest names by area rank.

    Deliberately crude, and labelled as such: this is the placeholder for the
    VLM identity pass. Geometry comes from CV, identity should come from a
    vision model that is good at naming and bad at coordinates. Anything that
    depends on ordering here is standing on sand.
    """
    ranked = sorted(boxes, key=lambda b: -((b[2] - b[0]) * (b[3] - b[1])))
    names: dict[tuple, str] = {}
    for index, box in enumerate(ranked):
        names[box] = "table" if index == 0 else "chair"
    return [names[b] for b in boxes]


def measure(path: Path) -> tuple[bool, list[str]]:
    import numpy as np
    from PIL import Image

    notes: list[str] = []
    rgb = np.array(Image.open(path).convert("RGB"))
    height, width = rgb.shape[:2]
    notes.append(f"image {width}x{height}")

    try:
        outline = detect_room_outline(rgb)
        notes.append(
            f"room outline MEASURED {outline}  "
            f"({outline[2] - outline[0]} x {outline[3] - outline[1]} px)"
        )
    except ValueError as exc:
        notes.append(f"room outline FAILED: {exc}")
        return (False, notes)

    # Anchor on the ONE dimension the Brief genuinely constrains and measure
    # the other. Asserting both over-constrains the render, which is entitled
    # to choose its own proportion above the Brief's minimum footprint.
    ortho, room_m = solve_scale_anchored(outline, KNOWN_WIDTH_M)
    notes.append(
        f"scale {ortho.scale:.5f} m/px   "
        f"room MEASURED {room_m[0]:.2f} x {room_m[1]:.2f} m (depth derived)"
    )

    boxes = segment_warm_objects(rgb)
    notes.append(f"objects segmented: {len(boxes)}")
    if not boxes:
        return (False, notes)

    names = name_blobs(boxes, EXPECTED)
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    inventory_ok = counts == EXPECTED
    notes.append(
        f"inventory {counts}  expected {EXPECTED}  "
        f"{'MATCH' if inventory_ok else 'MISMATCH'}"
    )

    detections = [
        {"id": f"{n}-{i}", "name": n, "bbox": b}
        for i, (n, b) in enumerate(zip(names, boxes))
    ]
    placements, evidence = placements_from_ortho(
        detections, ortho, _furniture_dims, room_m
    )
    for placement in placements:
        notes.append(
            f"   {placement['name']:6s} "
            f"({placement['x']:5.2f}, {placement['y']:5.2f}) m  "
            f"fp {placement['width']:.2f}x{placement['depth']:.2f}  "
            f"h {placement['height']:.2f}  rot {placement['rotation_deg']}"
        )
    notes.append(f"height source: {evidence['height_source']}")

    return (ortho.trustworthy and inventory_ok, notes)


def run(filter_text: str = "") -> int:
    if not RENDER_DIR.is_dir():
        print(f"render dir not found: {RENDER_DIR}")
        return 1

    renders = sorted(
        p for p in RENDER_DIR.glob("*.png")
        if "mask" not in p.name and (not filter_text or filter_text in p.name)
    )
    if not renders:
        print("no renders matched")
        return 1

    failures = 0
    for path in renders:
        ok, notes = measure(path)
        print("=" * 76)
        print(f"{path.name}   {'OK' if ok else 'NOT USABLE'}")
        print("=" * 76)
        for note in notes:
            print(f"  {note}")
        print()
        if not ok:
            failures += 1

    print("=" * 76)
    print(f"{len(renders) - failures} of {len(renders)} render(s) measured cleanly")
    print("=" * 76)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else ""))
