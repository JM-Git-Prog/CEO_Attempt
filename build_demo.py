"""
Demo script - runs the full pipeline. Produces a Godot project from a description.
Usage: python build_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.pipeline import WorldBuilder

DEMO_DESCRIPTION = """A small 1950s diner. Chrome counter with four red stools. 
One warm pendant lamp hanging low over the counter. Checkered black and white linoleum floor.
Rain streaking the storefront window. A swinging door to the kitchen on the west wall.
Cream tile wainscoting, pressed tin ceiling. A glass pie case at the end of the counter.
Coffee mug and chrome napkin dispenser on the counter."""


async def main():
    print("=" * 60)
    print("THE LIVING ROOM - Full Pipeline Demo")
    print("=" * 60)
    print(f"\nDescription: {DEMO_DESCRIPTION.strip()[:100]}...\n")

    builder = WorldBuilder(session_id="demo_diner")
    project_path = await builder.build_full(DEMO_DESCRIPTION)

    print(f"\n{'=' * 60}\nBUILD COMPLETE\n{'=' * 60}")
    print(f"\nGodot Project: {project_path}\n")
    print("Generated files:")
    for f in sorted(project_path.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(project_path)}  ({f.stat().st_size:,} bytes)")

    print(f"\nTo run: godot --path {project_path}")
    print("Controls: WASD move, Mouse look, E grab, walk into objects to push\n")

    if builder.session.scene_graph:
        sg = builder.session.scene_graph
        print(f"Scene: {sg.room.width}m x {sg.room.depth}m x {sg.room.height}m")
        print(f"Objects: {len(sg.objects)}, Lights: {len(sg.lights)}, Doors: {len(sg.doors)}")
        for obj in sg.objects:
            print(f"  - {obj.name} ({obj.physics.body_type.value}, {obj.physics.mass_kg}kg)")


if __name__ == "__main__":
    asyncio.run(main())
