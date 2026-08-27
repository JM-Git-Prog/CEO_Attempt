"""Quick mesh size report for the refine loop."""
import json
from pathlib import Path

session = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
scene = json.loads((session / "artifacts/scene.json").read_text())

objects = scene["objects"]
total_mb = 0
for obj in sorted(objects, key=lambda o: (session / "artifacts/meshes" / (o["uuid"] + ".glb")).stat().st_size if (session / "artifacts/meshes" / (o["uuid"] + ".glb")).exists() else 0, reverse=True):
    glb = session / "artifacts/meshes" / (obj["uuid"] + ".glb")
    size_mb = glb.stat().st_size / 1048576 if glb.exists() else 0
    total_mb += size_mb
    s = obj.get("scale", {})
    print(f"  {size_mb:6.1f} MB  {obj['name']:30s}  scale=({s.get('x',1):.2f}, {s.get('y',1):.2f}, {s.get('z',1):.2f})")

print(f"\n  Total: {total_mb:.1f} MB across {len(objects)} objects")
print(f"  Room shell: {(session / 'artifacts/meshes/room_shell.glb').stat().st_size / 1024:.1f} KB")
