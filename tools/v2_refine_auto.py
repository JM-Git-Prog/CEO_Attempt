"""V2 Autonomous Refine Loop — 50 cycles with vision feedback.

Each cycle:
1. Capture the current 3D world via Playwright (walkthrough + compare)
2. Send both captures + Canon to Qwen 2.5VL for visual assessment
3. Parse the top defect from the vision model's response
4. Apply a targeted fix to scene.json
5. Log the iteration result
6. Repeat

Runs up to MAX_CYCLES iterations or until the vision model says "PASS".
"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_ID = "8df83612-1b81-4428-b711-7fbabc9536bb"
SESSION = Path(f"output/{SESSION_ID}")
ARTIFACTS = SESSION / "artifacts"
MAX_CYCLES = 50
BASE_URL = "http://127.0.0.1:8000"
OLLAMA_URL = "http://127.0.0.1:11434"


async def capture_screenshot(session_id: str) -> Path | None:
    """Render the 3D scene server-side using trimesh for instant capture."""
    import trimesh
    import numpy as np
    from PIL import Image

    captures_dir = ARTIFACTS / "refine_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    
    scene_path = ARTIFACTS / "scene.json"
    if not scene_path.exists():
        return None
    
    scene_data = json.loads(scene_path.read_text())
    meshes_dir = ARTIFACTS / "meshes"
    
    # Build a trimesh scene from all the objects
    render_scene = trimesh.Scene()
    
    # Load room shell
    shell_path = meshes_dir / "room_shell.glb"
    if shell_path.exists():
        shell = trimesh.load(str(shell_path), force="scene", process=False)
        for name, geom in shell.geometry.items():
            render_scene.add_geometry(geom, node_name=f"shell_{name}")
    
    # Load objects with positions and scales
    for obj in scene_data.get("objects", []):
        glb_path = meshes_dir / f"{obj['uuid']}.glb"
        if not glb_path.exists():
            continue
        try:
            loaded = trimesh.load(str(glb_path), force="scene", process=False)
            pos = obj.get("position", {})
            scale = obj.get("scale", {})
            sx = scale.get("x", 1)
            sy = scale.get("y", 1) 
            sz = scale.get("z", 1)
            
            transform = np.eye(4)
            transform[0, 0] = sx
            transform[1, 1] = sy
            transform[2, 2] = sz
            transform[0, 3] = pos.get("x", 0)
            transform[1, 3] = pos.get("y", 0)
            transform[2, 3] = pos.get("z", 0)
            
            for name, geom in loaded.geometry.items():
                render_scene.add_geometry(
                    geom, node_name=f"{obj['uuid'][:8]}_{name}",
                    transform=transform
                )
        except Exception:
            pass
    
    # Render from camera position
    cam_pos = scene_data.get("camera", {}).get("position", {"x": 0, "y": 1.62, "z": 3})
    cam_target = scene_data.get("camera", {}).get("target", {"x": 0, "y": 1, "z": 0})
    
    # Use trimesh's built-in scene rendering (saves to PNG)
    screenshot_path = captures_dir / f"iter_{int(time.time())}.png"
    
    try:
        # Build camera transform manually (look_at equivalent)
        eye = np.array([cam_pos["x"], cam_pos["y"], cam_pos["z"]])
        target = np.array([cam_target["x"], cam_target["y"], cam_target["z"]])
        up = np.array([0.0, 1.0, 0.0])
        
        forward = target - eye
        forward = forward / (np.linalg.norm(forward) + 1e-8)
        right = np.cross(forward, up)
        right = right / (np.linalg.norm(right) + 1e-8)
        new_up = np.cross(right, forward)
        
        camera_transform = np.eye(4)
        camera_transform[:3, 0] = right
        camera_transform[:3, 1] = new_up
        camera_transform[:3, 2] = -forward
        camera_transform[:3, 3] = eye
        
        # Render with pyrender
        import pyrender
        
        pr_scene = pyrender.Scene(ambient_light=np.array([0.4, 0.35, 0.3]))
        
        # Add geometries
        for name, geom in render_scene.geometry.items():
            if hasattr(geom, "faces") and len(geom.faces) > 0:
                try:
                    # Get color from material
                    color = [0.7, 0.5, 0.3, 1.0]  # default warm
                    if hasattr(geom, "visual") and hasattr(geom.visual, "material"):
                        bcf = getattr(geom.visual.material, "baseColorFactor", None)
                        if bcf is not None:
                            color = [bcf[0]/255, bcf[1]/255, bcf[2]/255, 1.0]
                    elif hasattr(geom, "visual") and hasattr(geom.visual, "face_colors"):
                        fc = geom.visual.face_colors[0]
                        color = [fc[0]/255, fc[1]/255, fc[2]/255, 1.0]
                    
                    material = pyrender.MetallicRoughnessMaterial(
                        baseColorFactor=color,
                        metallicFactor=0.0,
                        roughnessFactor=0.8,
                    )
                    mesh = pyrender.Mesh.from_trimesh(geom, material=material)
                    # Get the node transform from the scene graph
                    node_name = name
                    node_transform = render_scene.graph.get(node_name)[0] if node_name in render_scene.graph else np.eye(4)
                    pr_scene.add(mesh, pose=node_transform)
                except Exception:
                    pass
        
        camera = pyrender.PerspectiveCamera(yfov=np.radians(60))
        pr_scene.add(camera, pose=camera_transform)
        
        light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
        pr_scene.add(light, pose=camera_transform)
        
        renderer = pyrender.OffscreenRenderer(1280, 720)
        color_img, _ = renderer.render(pr_scene)
        renderer.delete()
        
        img = Image.fromarray(color_img)
        img.save(str(screenshot_path))
        print(f"  [capture] Rendered {len(render_scene.geometry)} geometries")
    except Exception as e:
        print(f"  [capture] Render failed: {e}")
        # Fallback: create diagnostic info image for the vision model
        from PIL import ImageDraw
        img = Image.new("RGB", (1280, 720), (40, 30, 20))
        draw = ImageDraw.Draw(img)
        y = 20
        draw.text((20, y), f"Scene: {len(scene_data.get('objects', []))} objects", fill=(200, 200, 200))
        y += 30
        draw.text((20, y), f"Room: {scene_data['room_dimensions']}", fill=(200, 200, 200))
        y += 30
        for obj in scene_data.get("objects", [])[:15]:
            p = obj.get("position", {})
            s = obj.get("scale", {})
            draw.text((20, y), f"  {obj['name'][:25]}: pos=({p.get('x',0):.1f},{p.get('y',0):.1f},{p.get('z',0):.1f}) scale=({s.get('x',1):.1f},{s.get('y',1):.1f},{s.get('z',1):.1f})", fill=(150, 150, 150))
            y += 20
        img.save(str(screenshot_path))
    
    return screenshot_path


def vision_assess(screenshot_path: Path, canon_path: Path, extra_context: str = "") -> str:
    """Send screenshot + canon to Qwen 3.6 27B and get assessment."""
    import httpx

    screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()
    canon_b64 = base64.b64encode(canon_path.read_bytes()).decode()

    prompt = """You are a 3D scene reconstruction quality inspector. Compare these two images:
Image 1 (first): The TARGET - a Canon photo of a bohemian room.
Image 2 (second): The CURRENT STATE - a 3D reconstruction rendered via pyrender.

The room dimensions are already set. Do NOT suggest changing room dimensions.

Focus on these aspects IN ORDER of visual impact:
1. Are objects the right COLOR? (terracotta orange walls, green plants, colorful pouf, warm wood)
2. Are objects the right SIZE/SCALE relative to each other?
3. Are objects in the right POSITION? (ottoman center, chandelier hanging, cabinet left, plants on back wall)
4. Is the LIGHTING warm enough? (the Canon has warm amber tones)
5. Is anything MISSING that should be visible?
6. Is anything ROTATED wrong?

Pick the SINGLE most impactful defect that is NOT about room dimensions.
Be extremely specific with numbers.

Categories: SCALE, POSITION, COLOR, LIGHTING, MISSING, ROTATION, CAMERA
""" + extra_context + """

Respond EXACTLY in this format (two lines only):
DEFECT: <category>
DETAIL: <specific actionable fix with numbers>
"""

    response = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": "qwen3-vl:8b",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [canon_b64, screenshot_b64],
                }
            ],
            "stream": False,
        },
        timeout=180.0,
    )

    if response.status_code != 200:
        return f"ERROR: Ollama returned {response.status_code}"

    data = response.json()
    return data.get("message", {}).get("content", "ERROR: no response")


def _rebuild_room_shell(dims):
    """Regenerate room_shell.glb at the given dimensions."""
    import trimesh
    import numpy as np

    w, d, h = dims
    shell_path = ARTIFACTS / "meshes" / "room_shell.glb"

    floor = trimesh.creation.box(extents=[w, 0.05, d])
    floor.apply_translation([0, -0.025, 0])
    floor.visual.face_colors = np.array([[139, 90, 50, 255]] * len(floor.faces), dtype=np.uint8)

    ceiling = trimesh.creation.box(extents=[w, 0.05, d])
    ceiling.apply_translation([0, h + 0.025, 0])
    ceiling.visual.face_colors = np.array([[240, 235, 225, 255]] * len(ceiling.faces), dtype=np.uint8)

    wall_color = [205, 100, 45, 255]
    north = trimesh.creation.box(extents=[w, h, 0.1])
    north.apply_translation([0, h / 2, -d / 2 - 0.05])
    north.visual.face_colors = np.array([wall_color] * len(north.faces), dtype=np.uint8)

    south = trimesh.creation.box(extents=[w, h, 0.1])
    south.apply_translation([0, h / 2, d / 2 + 0.05])
    south.visual.face_colors = np.array([wall_color] * len(south.faces), dtype=np.uint8)

    east = trimesh.creation.box(extents=[0.1, h, d])
    east.apply_translation([w / 2 + 0.05, h / 2, 0])
    east.visual.face_colors = np.array([wall_color] * len(east.faces), dtype=np.uint8)

    west = trimesh.creation.box(extents=[0.1, h, d])
    west.apply_translation([-w / 2 - 0.05, h / 2, 0])
    west.visual.face_colors = np.array([wall_color] * len(west.faces), dtype=np.uint8)

    scene = trimesh.Scene()
    scene.add_geometry(floor, node_name="floor")
    scene.add_geometry(ceiling, node_name="ceiling")
    scene.add_geometry(north, node_name="wall_north")
    scene.add_geometry(south, node_name="wall_south")
    scene.add_geometry(east, node_name="wall_east")
    scene.add_geometry(west, node_name="wall_west")
    scene.export(str(shell_path), file_type="glb")
    print(f"  [fix] Rebuilt room shell: {w}x{d}x{h}m")


# Track previous assessments to avoid loops
_previous_fixes = []


def apply_fix(assessment: str) -> bool:
    """Parse the vision assessment and apply the fix to scene.json."""
    global _previous_fixes
    scene_path = ARTIFACTS / "scene.json"
    scene = json.loads(scene_path.read_text())

    lines = assessment.strip().split("\n")
    category = ""
    detail = ""
    for line in lines:
        if line.startswith("DEFECT:"):
            category = line.split(":", 1)[1].strip().upper()
        elif line.startswith("DETAIL:"):
            detail = line.split(":", 1)[1].strip()

    if not category or not detail:
        print(f"  [fix] Could not parse assessment: {assessment[:200]}")
        return False

    # Detect loops — if same fix was applied in last 3 cycles, skip
    fix_key = f"{category}:{detail[:50]}"
    if fix_key in _previous_fixes[-3:]:
        print(f"  [fix] LOOP DETECTED — same fix repeated. Skipping.")
        return False
    _previous_fixes.append(fix_key)

    print(f"  [fix] Category: {category}")
    print(f"  [fix] Detail: {detail}")

    if category == "LIGHTING":
        # Boost or reduce lighting
        if "dark" in detail.lower() or "more" in detail.lower() or "bright" in detail.lower():
            for light in scene.get("lighting", []):
                light["intensity"] = min(2.0, light.get("intensity", 0.5) * 1.5)
        elif "too bright" in detail.lower():
            for light in scene.get("lighting", []):
                light["intensity"] = max(0.1, light.get("intensity", 1.0) * 0.7)

    elif category == "CAMERA":
        # Try to extract position from detail
        import re
        nums = re.findall(r"[-+]?\d*\.?\d+", detail)
        if len(nums) >= 3:
            scene["camera"]["position"] = {"x": float(nums[0]), "y": float(nums[1]), "z": float(nums[2])}
            scene["navigation"]["spawn_position"] = {"x": float(nums[0]), "y": float(nums[1]), "z": float(nums[2])}
        if len(nums) >= 6:
            scene["camera"]["target"] = {"x": float(nums[3]), "y": float(nums[4]), "z": float(nums[5])}

    elif category == "SCALE":
        # Try to find object name and scale values
        import re
        nums = re.findall(r"[-+]?\d*\.?\d+", detail)
        for obj in scene["objects"]:
            if obj["name"].lower() in detail.lower():
                if len(nums) >= 3:
                    obj["scale"] = {"x": float(nums[-3]), "y": float(nums[-2]), "z": float(nums[-1])}
                else:
                    # Generic scale down/up
                    factor = 0.5 if "large" in detail.lower() or "big" in detail.lower() else 1.5
                    s = obj.get("scale", {"x": 1, "y": 1, "z": 1})
                    obj["scale"] = {"x": s["x"] * factor, "y": s["y"] * factor, "z": s["z"] * factor}
                break

    elif category == "POSITION":
        import re
        nums = re.findall(r"[-+]?\d*\.?\d+", detail)
        for obj in scene["objects"]:
            if obj["name"].lower() in detail.lower():
                if len(nums) >= 3:
                    obj["position"] = {"x": float(nums[-3]), "y": float(nums[-2]), "z": float(nums[-1])}
                break

    elif category == "ROOM":
        import re
        nums = re.findall(r"[-+]?\d*\.?\d+", detail)
        if len(nums) >= 3:
            scene["room_dimensions"] = [float(nums[0]), float(nums[1]), float(nums[2])]
            # Regenerate room shell at new size
            _rebuild_room_shell(scene["room_dimensions"])

    elif category == "COLOR":
        # Re-run colorization
        print("  [fix] Re-running colorization from Canon...")
        import subprocess
        subprocess.run([sys.executable, "tools/v2_colorize_meshes.py"], cwd=str(Path(__file__).parent.parent))

    elif category == "ROTATION":
        import re
        nums = re.findall(r"[-+]?\d*\.?\d+", detail)
        for obj in scene["objects"]:
            if obj["name"].lower() in detail.lower():
                if nums:
                    obj["rotation_y_deg"] = float(nums[-1])
                break

    else:
        print(f"  [fix] Unknown category: {category}")
        return False

    scene_path.write_text(json.dumps(scene, indent=2))
    return True


async def run_loop():
    """Main refine loop — up to MAX_CYCLES iterations."""
    canon_path = ARTIFACTS / "canon.png"
    if not canon_path.exists():
        print("ERROR: Canon image not found")
        return

    log_path = ARTIFACTS / "refine_log.json"
    log = []

    print(f"Starting V2 Refine Loop — {MAX_CYCLES} max cycles")
    print(f"Session: {SESSION_ID}")
    print(f"URL: {BASE_URL}/?v=2.0&session={SESSION_ID}")
    print()

    for cycle in range(1, MAX_CYCLES + 1):
        print(f"{'='*60}")
        print(f"CYCLE {cycle}/{MAX_CYCLES}")
        print(f"{'='*60}")

        # Step 1: Capture
        print("  [1] Capturing screenshot...")
        screenshot = await capture_screenshot(SESSION_ID)
        if not screenshot:
            print("  [1] Capture failed — skipping cycle")
            continue

        # Step 2: Vision assessment (include history of previous fixes)
        print("  [2] Vision assessment via qwen2.5vl...")
        history_note = ""
        if _previous_fixes:
            history_note = f"\n\nALREADY FIXED (do not repeat these): {', '.join(_previous_fixes[-5:])}"
        assessment = vision_assess(screenshot, canon_path, extra_context=history_note)
        print(f"  [2] Response: {assessment[:300]}")

        if "PASS" in assessment.upper() and "DEFECT" not in assessment.upper():
            print("\n  VISION MODEL SAYS: PASS — world matches Canon!")
            log.append({"cycle": cycle, "result": "PASS", "assessment": assessment})
            break

        # Step 3: Apply fix
        print("  [3] Applying fix...")
        success = apply_fix(assessment)
        
        log_entry = {
            "cycle": cycle,
            "screenshot": str(screenshot),
            "assessment": assessment[:500],
            "fix_applied": success,
            "timestamp": time.time(),
        }
        log.append(log_entry)

        if not success:
            print("  [3] Fix failed — continuing to next cycle")

        # Brief pause to let changes settle
        await asyncio.sleep(1)

    # Save log
    log_path.write_text(json.dumps(log, indent=2))
    print(f"\nRefine loop complete — {len(log)} cycles logged to {log_path}")


if __name__ == "__main__":
    asyncio.run(run_loop())
