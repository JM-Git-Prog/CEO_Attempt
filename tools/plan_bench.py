"""Plan bench — iterate on room layout WITHOUT restarting the server.

Why this exists
---------------
Every change to plan_generator.py used to cost a server restart, a killed
session, and a ~4 minute pipeline re-run just to see three numbers. Worse, the
throwaway checks used during that loop reimplemented the validator's rules by
hand, so a layout could "pass" here and still be rejected by the real gate.

This bench runs the REAL generator against the REAL PlanValidator with no
server, no Ollama, no ComfyUI and no GPU. It is the same code path the pipeline
takes (canon_first_authority -> generate_deterministic -> _fallback_generate),
so a green run here means the spatial_reconstruction stage will accept the plan.

Usage
-----
    python tools/plan_bench.py              # run every scenario
    python tools/plan_bench.py table        # only scenarios matching "table"

Exit code is 0 when every scenario validates, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.unified_pipeline.models import Brief, ManifestObject  # noqa: E402
from src.unified_pipeline.plan_generator import MetricPlanGenerator  # noqa: E402
from src.unified_pipeline.plan_validator import PlanValidator  # noqa: E402


# ─── Scenarios ─────────────────────────────────────────────────────────────────
# (label, room_purpose, [(name, count, is_architectural), ...])

SCENARIOS: list[tuple[str, str, list[tuple[str, int, bool]]]] = [
    ("table + 2 chairs (the ask)", "casual meeting or workspace",
     [("table", 1, False), ("chair", 2, False)]),
    ("table + 4 chairs", "dining",
     [("table", 1, False), ("chair", 4, False)]),
    ("table + 6 chairs", "dining",
     [("table", 1, False), ("chair", 6, False)]),
    ("desk + chair + bookshelf", "study",
     [("desk", 1, False), ("chair", 1, False), ("bookshelf", 1, False)]),
    ("sofa + 2 lamps", "living room",
     [("sofa", 1, False), ("lamp", 2, False)]),
    ("bed + lamp", "bedroom",
     [("bed", 1, False), ("lamp", 1, False)]),
    ("table + 2 chairs + shelf + lamp", "casual meeting or workspace",
     [("table", 1, False), ("chair", 2, False),
      ("bookshelf", 1, False), ("lamp", 1, False)]),
    ("unknown objects (default box)", "generic",
     [("widget", 3, False)]),
    ("single chair (no anchor)", "generic",
     [("chair", 1, False)]),
    ("architectural fixture", "kitchen",
     [("counter", 2, True), ("table", 1, False), ("chair", 2, False)]),
]


def build_brief(purpose: str, objects: list[tuple[str, int, bool]]) -> Brief:
    return Brief(
        room_purpose=purpose,
        object_manifest=tuple(
            ManifestObject(
                id=f"{name}-{index}",
                name=name,
                role="furniture",
                count=count,
                is_architectural=architectural,
            )
            for index, (name, count, architectural) in enumerate(objects)
        ),
    )


# ─── Top-down ASCII plan ───────────────────────────────────────────────────────

def render(plan, cols: int = 62, rows: int = 24) -> str:
    """Draw the plan looking straight down. x runs right, y runs down."""
    width, depth, _ = plan.room_dimensions
    grid = [[" "] * cols for _ in range(rows)]

    for row in range(rows):
        for col in range(cols):
            edge = row in (0, rows - 1) or col in (0, cols - 1)
            if edge:
                grid[row][col] = "."

    for index, placement in enumerate(plan.object_placements):
        mark = str(index % 10)
        left = placement["x"] - placement["width"] / 2.0
        right = placement["x"] + placement["width"] / 2.0
        top = placement["y"] - placement["depth"] / 2.0
        bottom = placement["y"] + placement["depth"] / 2.0
        c0 = max(0, min(cols - 1, int(left / width * (cols - 1))))
        c1 = max(0, min(cols - 1, int(right / width * (cols - 1))))
        r0 = max(0, min(rows - 1, int(top / depth * (rows - 1))))
        r1 = max(0, min(rows - 1, int(bottom / depth * (rows - 1))))
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                grid[row][col] = mark

    legend = "\n".join(
        f"    {index % 10} = {p['name']:<10} "
        f"({p['x']:5.2f},{p['y']:5.2f})  "
        f"{p['width']:.2f} x {p['depth']:.2f} x {p['height']:.2f}  "
        f"rot={p['rotation_deg']}"
        for index, p in enumerate(plan.object_placements)
    )
    body = "\n".join("    " + "".join(row) for row in grid)
    return f"{body}\n\n{legend}"


# ─── Runner ────────────────────────────────────────────────────────────────────

def run(filter_text: str = "") -> int:
    generator = MetricPlanGenerator()
    validator = PlanValidator()
    failures = 0
    ran = 0

    for label, purpose, objects in SCENARIOS:
        if filter_text and filter_text.lower() not in label.lower():
            continue
        ran += 1
        print("=" * 74)
        print(label)
        print("=" * 74)

        brief = build_brief(purpose, objects)
        try:
            plan = generator.generate_deterministic(brief)
        except Exception as exc:  # noqa: BLE001 - the bench reports, never hides
            failures += 1
            print(f"  GENERATE RAISED  {type(exc).__name__}: {exc}\n")
            continue

        width, depth, ceiling = plan.room_dimensions
        result = validator.validate(plan)
        verdict = "VALID" if result.valid else "INVALID"
        print(f"  room {width:.2f} x {depth:.2f} x {ceiling:.2f} m"
              f"   objects={len(plan.object_placements)}   {verdict}")
        print()
        print(render(plan))
        print()

        if not result.valid:
            failures += 1
            for violation in result.violations:
                severity = getattr(violation, "severity", "?")
                message = getattr(violation, "message", violation)
                print(f"    [{severity}] {message}")
            print()

    print("=" * 74)
    if failures:
        print(f"FAIL — {failures} of {ran} scenario(s) rejected by PlanValidator")
    else:
        print(f"PASS — all {ran} scenario(s) accepted by the real PlanValidator")
    print("=" * 74)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else ""))
