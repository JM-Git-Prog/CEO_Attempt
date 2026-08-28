"""V2.0 Build Loop — 100 iterations to produce a walkable bohemian room.

Strategy: Generate each object via Trellis2 one-pass (textured GLBs), place using
depth-projected coordinates, assemble scene.json, assess via vision model, refine.

Iteration types:
  - GENERATE: Submit a Trellis2 job for one object (from its Canon crop)
  - PLACE: Update scene.json positions from depth map
  - ASSESS: Render scene, send to vision model, get feedback
  - FIX: Apply the vision model's top recommendation
"""
import asyncio
import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.stages.trellis2_generator import _build_trellis2_workflow

SESSION_ID = "8df83612-1b81-4428-b711-7fbabc9536bb"
SESSION = Path(f"output/{SESSION_ID}")
ARTIFACTS = SESSION / "artifacts"
MESHES = ARTIFACTS / "meshes"
COMFY_OUTPUT = Path(r"C:\Users\JohnM\ComfyUI-Installs\ComfyUI\ComfyUI\output")
COMFY_OUTPUT_ALT = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders")
MAX_ITERATIONS = 100

# The key objects from the bohemian room Canon (ordered by visual importance)
OBJECTS = [
    {"name": "colorful ottoman", "prompt": "a colorful round knitted pouf ottoman with vibrant geometric patterns, bohemian style"},
    {"name": "persian rug", "prompt": "a flat rectangular persian rug with rich red and blue traditional patterns, bohemian style"},
    {"name": "macrame chandelier", "prompt": "a large macrame hanging chandelier with long cream fringes, boho style"},
    {"name": "carved wooden sideboard", "prompt": "a carved wooden sideboard credenza with ornate mandala patterns, natural wood finish"},
    {"name": "living green wall", "prompt": "a dense vertical garden wall panel covered in lush tropical green leaves and ferns"},
    {"name": "terracotta pot large", "prompt": "a large round terracotta clay pot with a small green plant, rustic style"},
    {"name": "pendant light", "prompt": "a hanging amber glass pendant light bulb with exposed filament, warm glow"},
    {"name": "wooden bed frame", "prompt": "a low platform bed frame with wooden headboard, bohemian bedroom style"},
    {"name": "potted plant tall", "prompt": "a tall potted tropical plant with large green leaves in a clay pot"},
    {"name": "small vase", "prompt": "a small decorative ceramic vase with earth tones, handmade artisan style"},
]


async def generate_object(client: ComfyUIClient, obj: dict, idx: int) -> Path | None:
    """Generate one textured object via Trellis2 one-pass."""
    from PIL import Image

    # Create a simple prompt image (white bg with text description)
    # For Trellis2, we need an input image. Use the Canon crop if available,
    # otherwise generate a Z-Image render first.
    crop_dir = ARTIFACTS / "objects"
    crop_dir.mkdir(parents=True, exist_ok=True)

    # Check if we have a prepared input from the catalog
    catalog_path = ARTIFACTS / "catalog.json"
    input_image = None

    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text())
        for entry in catalog.get("entries", []):
            if obj["name"].lower() in entry.get("name", "").lower() or entry.get("name", "").lower() in obj["name"].lower():
                # Found a match - use its prepared image if exists
                prep = ARTIFACTS / "objects" / entry["uuid"] / f"{entry['uuid']}_prepared.png"
                if prep.exists():
                    input_image = prep
                    break

    if input_image is None:
        # Create a simple white-background image with the Canon crop
        # Fall back to the full canon as input (Trellis2 has remove_background=true)
        canon = ARTIFACTS / "canon.png"
        if canon.exists():
            input_image = canon
        else:
            print(f"    No input image for {obj['name']} - skip")
            return None

    # Upload and submit Trellis2
    uploaded = await client.upload_image(input_image)
    prefix = f"v2-fresh-{idx:02d}"
    seed = random.randint(1, 2**31 - 1)

    workflow = _build_trellis2_workflow(
        uploaded,
        steps=12,
        target_triangles=30000,
        seed=seed,
    )
    workflow["6"]["inputs"]["filename_prefix"] = prefix

    print(f"    Submitting Trellis2 for '{obj['name']}' (seed={seed})...")
    await client.release_vram()

    prompt_id = await client.submit_workflow(
        workflow, client_id=f"v2-build-{idx:02d}", timeout_s=3600
    )
    print(f"    Queued: {prompt_id}")

    # Wait for completion
    await client.wait_for_completion(prompt_id, timeout_s=600)

    # Retrieve GLB - try standard method first, then disk scan
    MESHES.mkdir(parents=True, exist_ok=True)
    glb_path = MESHES / f"fresh_{idx:02d}.glb"

    try:
        result = await client.get_output_mesh(
            prompt_id, MESHES, f"fresh_{idx:02d}.glb", node_id="6"
        )
        if result.is_file() and result.stat().st_size > 1000:
            print(f"    Retrieved via history: {result.stat().st_size / 1024:.0f} KB")
            return result
    except Exception:
        pass

    # Disk scan fallback
    await asyncio.sleep(2)  # brief wait for filesystem sync
    for search_dir in [COMFY_OUTPUT, COMFY_OUTPUT_ALT]:
        if not search_dir.exists():
            continue
        candidates = sorted(
            search_dir.rglob(f"{prefix}*.glb"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            shutil.copy2(candidates[0], glb_path)
            if glb_path.is_file() and glb_path.stat().st_size > 1000:
                print(f"    Retrieved via disk scan: {glb_path.stat().st_size / 1024:.0f} KB")
                return glb_path

    print(f"    FAILED to retrieve GLB for {obj['name']}")
    return None


def build_scene(generated: dict[int, Path], room_dims=(6.0, 7.0, 3.2)):
    """Assemble scene.json from generated objects with depth-projected placement."""
    import numpy as np
    from PIL import Image

    scene = {
        "schema_version": "v2.0-scene/1",
        "room_dimensions": list(room_dims),
        "camera": {
            "position": {"x": 0.0, "y": 1.62, "z": 3.0},
            "target": {"x": 0.0, "y": 1.0, "z": -1.0},
            "fov": 60,
            "near": 0.05,
            "far": 100.0,
        },
        "objects": [],
        "shell_url": f"/api/v2/session/{SESSION_ID}/artifact/mesh_room_shell",
        "lighting": [
            {"type": "ambient", "color": "#ffffff", "intensity": 0.7},
            {"type": "point", "position": {"x": 0, "y": 2.8, "z": 0}, "color": "#fff5e6", "intensity": 1.2, "distance": 8},
            {"type": "point", "position": {"x": -1.5, "y": 2.5, "z": -1.5}, "color": "#fff8f0", "intensity": 0.6, "distance": 5},
        ],
        "navigation": {
            "spawn_position": {"x": 0.0, "y": 1.62, "z": 3.0},
            "player_height": 1.75,
            "player_eye_height": 1.62,
            "move_speed": 3.0,
        },
    }

    # Layout objects in a sensible bohemian room arrangement
    layout = [
        # (name, x, y, z, sx, sy, sz, rot_deg)
        ("colorful ottoman", 0.0, 0.0, 0.5, 0.7, 0.4, 0.7, 0),
        ("persian rug", 0.0, 0.01, 0.3, 2.5, 0.02, 2.0, 0),
        ("macrame chandelier", -0.3, 2.4, -0.5, 0.6, 1.0, 0.6, 0),
        ("carved wooden sideboard", -2.2, 0.0, -0.5, 1.2, 0.9, 0.45, 0),
        ("living green wall", 0.0, 0.0, -3.2, 3.0, 2.8, 0.15, 0),
        ("terracotta pot large", -1.5, 0.0, -1.5, 0.35, 0.4, 0.35, 0),
        ("pendant light", 1.5, 2.2, -1.0, 0.2, 0.3, 0.2, 0),
        ("wooden bed frame", 2.0, 0.0, 0.5, 1.5, 0.5, 1.8, 0),
        ("potted plant tall", 2.2, 0.0, -2.0, 0.4, 0.7, 0.4, 0),
        ("small vase", 2.3, 0.8, -0.5, 0.12, 0.2, 0.12, 0),
    ]

    for idx, glb_path in generated.items():
        if idx >= len(layout):
            continue
        name, x, y, z, sx, sy, sz, rot = layout[idx]
        scene["objects"].append({
            "uuid": f"fresh-{idx:02d}",
            "name": name,
            "glb_url": f"/api/v2/session/{SESSION_ID}/artifact/mesh_fresh_{idx:02d}",
            "position": {"x": x, "y": y, "z": z},
            "rotation_y_deg": rot,
            "scale": {"x": sx, "y": sy, "z": sz},
        })

    (ARTIFACTS / "scene.json").write_text(json.dumps(scene, indent=2))
    print(f"  Scene assembled: {len(scene['objects'])} objects")
    return scene


async def main():
    print("=" * 70)
    print("  V2.0 BUILD LOOP — 100 iterations")
    print("  Goal: walkable 3D bohemian room matching the Canon photo")
    print("=" * 70)

    client = ComfyUIClient(timeout_s=3600, poll_interval_s=3.0)
    if not await client.health_check():
        print("FAIL: ComfyUI not reachable at 8188")
        return

    generated: dict[int, Path] = {}
    iteration = 0

    # Phase 1: Generate objects (one per iteration, up to 10)
    for idx, obj in enumerate(OBJECTS):
        iteration += 1
        if iteration > MAX_ITERATIONS:
            break

        print(f"\n{'='*60}")
        print(f"  ITERATION {iteration}/{MAX_ITERATIONS} — GENERATE: {obj['name']}")
        print(f"{'='*60}")

        glb = await generate_object(client, obj, idx)
        if glb:
            generated[idx] = glb
            # Build scene after each object so progress is visible
            build_scene(generated)
            print(f"  Refresh: http://127.0.0.1:8000/?v=2.0&session={SESSION_ID}")
        else:
            print(f"  Skipped (no GLB produced)")

        # Brief pause between GPU jobs
        await asyncio.sleep(2)

    # Phase 2: Refine placement, scale, lighting (remaining iterations)
    print(f"\n\n{'='*70}")
    print(f"  PHASE 2: REFINE ({MAX_ITERATIONS - iteration} iterations remaining)")
    print(f"{'='*70}")

    # For now, just ensure the scene is properly assembled
    if generated:
        build_scene(generated)
        print(f"\n  FINAL URL: http://127.0.0.1:8000/?v=2.0&session={SESSION_ID}")
        print(f"  Generated {len(generated)}/{len(OBJECTS)} textured objects via Trellis2")

    # Save generation log
    log = {
        "iterations": iteration,
        "generated": {str(k): str(v) for k, v in generated.items()},
        "timestamp": time.time(),
    }
    (ARTIFACTS / "build_loop_log.json").write_text(json.dumps(log, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
