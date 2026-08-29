"""Test the geometry_injection stage end-to-end against the existing session."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.unified_pipeline.geometry_injection import inject_geometry

sess = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
brief_path = sess / "artifacts" / "brief.json"
if brief_path.exists():
    brief = json.loads(brief_path.read_text())
else:
    brief = {"description": "a warm bohemian living room with terracotta walls, macrame chandelier, colorful ottoman, carved wooden sideboard, lush green living wall, persian rug"}


def emit(etype, data):
    msg = data.get("message", "")
    print(f"  [{etype}] {msg}")


result = asyncio.run(inject_geometry(brief, sess, emit_fn=emit))
print(f"\nRESULT: {result}")
