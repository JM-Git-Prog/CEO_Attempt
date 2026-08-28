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
    """Render the 3D scene and create a side-by-side Compare image (Canon | 3D)."""
    import trimesh
    import numpy as np
    from PIL import Image

    captures_dir = ARTIFACTS / "refine_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    
    scene_path = ARTIFACTS / "scene.json"
    canon_path = ARTIFACTS / "canon.png"
    if not scene_path.exists() or not canon_path.exists():
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
            # Try gen_ prefix for generated objects
            alt_name = obj.get("uuid", "").replace("gen-", "gen_") + ".glb"
            glb_path = meshes_dir / alt_name
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
    
    # Camera from scene.json (same as Compare view uses)
    cam = scene_data.get("camera", {})
    cam_pos = cam.get("position", {"x": 0, "y": 1.5, "z": 1.8})
    cam_target = cam.get("target", {"x": 0, "y": 0.8, "z": -1.2})
    
    # Render at Canon aspect ratio (4:3)
    render_w, render_h = 768, 576  # 4:3, manageable size
    screenshot_path = captures_dir / f"compare_{int(time.time())}.png"
    
    try:
        # Build camera transform
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
        
        pr_scene = pyrender.Scene(
            ambient_light=np.array([0.5, 0.4, 0.3]),
            bg_color=np.array([0.0, 0.0, 0.0, 1.0]),
        )
        
        for name, geom in render_scene.geometry.items():
            if hasattr(geom, "faces") and len(geom.faces) > 0:
                try:
                    color = [0.7, 0.5, 0.3, 1.0]
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
                    pr_scene.add(mesh)
                except Exception:
                    pass
        
        camera = pyrender.PerspectiveCamera(yfov=np.radians(60))
        pr_scene.add(camera, pose=camera_transform)
        
        light = pyrender.DirectionalLight(color=np.array([1.0, 0.9, 0.8]), intensity=3.0)
        pr_scene.add(light, pose=camera_transform)
        
        renderer = pyrender.OffscreenRenderer(render_w, render_h)
        color_img, _ = renderer.render(pr_scene)
        renderer.delete()
        
        render_pil = Image.fromarray(color_img)
        
        # Create side-by-side composite: Canon (left) | 3D Render (right)
        canon_img = Image.open(canon_path).convert("RGB")
        canon_resized = canon_img.resize((render_w, render_h), Image.LANCZOS)
        
        composite = Image.new("RGB", (render_w * 2, render_h), (0, 0, 0))
        composite.paste(canon_resized, (0, 0))
        composite.paste(render_pil, (render_w, 0))
        composite.save(str(screenshot_path))
        
        print(f"  [capture] Compare image: {render_w*2}x{render_h}, {len(render_scene.geometry)} geometries")
    except Exception as e:
        print(f"  [capture] Render failed: {e}")
        # Fallback: just use Canon alone
        from PIL import ImageDraw
        canon_img = Image.open(canon_path).convert("RGB").resize((render_w, render_h))
        composite = Image.new("RGB", (render_w * 2, render_h), (0, 0, 0))
        composite.paste(canon_img, (0, 0))
        draw = ImageDraw.Draw(composite)
        draw.text((render_w + 20, 20), f"Render failed: {str(e)[:60]}", fill=(255, 100, 100))
        composite.save(str(screenshot_path))
    
    return screenshot_path


def vision_assess(screenshot_path: Path, canon_path: Path, extra_context: str = "") -> str:
    """Send the side-by-side Compare image to Qwen 3 VL for assessment."""
    import httpx

    # The screenshot IS already a side-by-side composite (Canon left | 3D right)
    screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()

    prompt = """You are looking at a side-by-side comparison image.
LEFT HALF: The target Canon photo of a bohemian room.
RIGHT HALF: The current 3D reconstruction from the same camera angle.

Your job: identify the SINGLE most impactful difference between left and right that needs fixing.

The room dimensions are already set. Do NOT suggest changing room dimensions.

Look for these IN ORDER of visual impact:
1. POSITION: An object on the right is in the wrong location compared to where it appears on the left. Give the direction and estimated distance to move it (e.g. "move ottoman 0.5m to the left and 0.3m forward").
2. SCALE: An object on the right is too big or too small compared to the left.
3. MISSING: Something clearly visible on the left is completely absent on the right.
4. COLOR: The colors on the right don't match the left (wrong hue, too dark, too bright).
5. LIGHTING: The overall brightness or warmth differs between the two halves.
6. ROTATION: An object is facing the wrong direction.

Be VERY specific with measurements (meters for position, multipliers for scale).
Name the exact object.
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
                    "images": [screenshot_b64],
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


async def apply_fix(assessment: str) -> bool:
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

    elif category == "MISSING":
        # Generate a new mesh for the missing object via Hunyuan3D
        import re
        import asyncio
        print(f"  [fix] Generating missing object mesh...")

        # Extract object name from detail
        obj_name = detail.split("(")[0].strip().lower()
        # Clean up common prefixes
        for prefix in ["add ", "add the ", "include ", "place "]:
            if obj_name.startswith(prefix):
                obj_name = obj_name[len(prefix):]
        obj_name = obj_name.strip()

        # Create a crop from the Canon for this object (center region as approximation)
        from PIL import Image
        canon = Image.open(ARTIFACTS / "canon.png").convert("RGB")
        # Use center crop as input for the mesh (best approximation without bbox)
        w, h = canon.size
        crop = canon.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
        # Put on white background
        canvas = Image.new("RGB", (max(crop.size), max(crop.size)), (255, 255, 255))
        canvas.paste(crop, ((canvas.width - crop.width) // 2, (canvas.height - crop.height) // 2))

        obj_id = obj_name.replace(" ", "_")[:20]
        input_path = ARTIFACTS / "meshes" / f"gen_{obj_id}_input.png"
        canvas.save(str(input_path))

        # Submit Hunyuan3D via the existing builder
        try:
            from src.photo_pipeline.comfyui_client import ComfyUIClient
            from src.photo_pipeline.stages.hunyuan3d_v2_generator import _build_hunyuan3d_v2_workflow
            import random

            client = ComfyUIClient(timeout_s=600, poll_interval_s=2.0)
            if await client.health_check():
                await client.release_vram()
                uploaded = await client.upload_image(input_path)
                workflow = _build_hunyuan3d_v2_workflow(
                    uploaded, steps=30, cfg=5.0, octree_resolution=256,
                    seed=random.randint(1, 2**32 - 1),
                )
                workflow["9"]["inputs"]["filename_prefix"] = f"v2-gen-{obj_id}"
                prompt_id = await client.submit_workflow(workflow, client_id=f"v2-gen-{obj_id}", timeout_s=600)
                await client.wait_for_completion(prompt_id, timeout_s=600)
                glb_path = ARTIFACTS / "meshes" / f"gen_{obj_id}.glb"
                await client.get_output_mesh(prompt_id, ARTIFACTS / "meshes", f"gen_{obj_id}.glb", node_id="9")

                if glb_path.is_file() and glb_path.stat().st_size > 1000:
                    # Add to scene
                    nums = re.findall(r"[-+]?\d*\.?\d+", detail)
                    pos_x = float(nums[0]) if len(nums) >= 1 else 0.0
                    pos_y = float(nums[1]) if len(nums) >= 2 else 0.0
                    pos_z = float(nums[2]) if len(nums) >= 3 else 0.0
                    scene["objects"].append({
                        "uuid": f"gen-{obj_id}",
                        "name": obj_name,
                        "glb_url": f"/api/v2/session/{SESSION_ID}/artifact/mesh_gen_{obj_id}",
                        "position": {"x": pos_x, "y": pos_y, "z": pos_z},
                        "rotation_y_deg": 0,
                        "scale": {"x": 0.5, "y": 0.5, "z": 0.5},
                    })
                    print(f"  [fix] Generated and placed: {obj_name}")
                else:
                    print(f"  [fix] GLB not produced for {obj_name}")
                    return False
            else:
                print(f"  [fix] ComfyUI not available for mesh generation")
                return False
        except Exception as e:
            print(f"  [fix] Mesh generation failed: {e}")
            return False

    elif category == "REGENERATE":
        # Re-generate an existing object with Hunyuan3D
        print(f"  [fix] Regeneration not yet implemented — skipping")
        return False

    else:
        print(f"  [fix] Unknown category: {category}")
        return False

    scene_path.write_text(json.dumps(scene, indent=2))
    return True


# ─── Learning Layer: Embed outcomes, query past successes ─────────────────────

LEARNING_DB = ARTIFACTS / "learning_db.json"


def _load_learning_db() -> list[dict]:
    """Load the learning database (cycle outcomes with embeddings)."""
    if LEARNING_DB.exists():
        return json.loads(LEARNING_DB.read_text())
    return []


def _save_learning_db(db: list[dict]):
    LEARNING_DB.write_text(json.dumps(db, indent=2))


def _embed_text(text: str) -> list[float] | None:
    """Embed text via Ollama's nomic-embed-text model."""
    import httpx
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": "nomic-embed-text", "input": text},
            timeout=30.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            embeddings = data.get("embeddings", [])
            return embeddings[0] if embeddings else None
    except Exception:
        pass
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def record_outcome(cycle: int, category: str, detail: str, success: bool):
    """Record a cycle outcome with its embedding for future retrieval."""
    db = _load_learning_db()
    text = f"{category}: {detail} (success={success})"
    embedding = _embed_text(text)
    db.append({
        "cycle": cycle,
        "category": category,
        "detail": detail[:200],
        "success": success,
        "timestamp": time.time(),
        "embedding": embedding,
    })
    _save_learning_db(db)


def query_past_successes(current_assessment: str, top_k: int = 3) -> str:
    """Query learning DB for past successful fixes similar to the current defect."""
    db = _load_learning_db()
    if not db:
        return ""

    # Embed the current assessment
    query_emb = _embed_text(current_assessment)
    if not query_emb:
        return ""

    # Find most similar successful fixes
    scored = []
    for entry in db:
        if not entry.get("success") or not entry.get("embedding"):
            continue
        sim = _cosine_similarity(query_emb, entry["embedding"])
        scored.append((sim, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    if not top:
        return ""

    lines = ["\n\nPAST SUCCESSFUL FIXES (use these as guidance):"]
    for sim, entry in top:
        lines.append(f"  - [{entry['category']}] {entry['detail']} (similarity={sim:.2f})")
    return "\n".join(lines)


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

        # Step 2: Vision assessment (include history + learned successes)
        print("  [2] Vision assessment via qwen3-vl...")
        history_note = ""
        if _previous_fixes:
            history_note = f"\n\nALREADY TRIED (do not repeat): {', '.join(_previous_fixes[-5:])}"
        # Query learning DB for past successes similar to what we might need
        learned_context = query_past_successes(f"3D room reconstruction defect")
        assessment = vision_assess(screenshot, canon_path, extra_context=history_note + learned_context)
        print(f"  [2] Response: {assessment[:300]}")

        if "PASS" in assessment.upper() and "DEFECT" not in assessment.upper():
            print("\n  VISION MODEL SAYS: PASS — world matches Canon!")
            log.append({"cycle": cycle, "result": "PASS", "assessment": assessment})
            break

        # Step 3: Apply fix
        print("  [3] Applying fix...")
        success = await apply_fix(assessment)

        # Step 4: Record outcome for learning
        category = ""
        detail = ""
        for line in assessment.strip().split("\n"):
            if line.startswith("DEFECT:"):
                category = line.split(":", 1)[1].strip()
            elif line.startswith("DETAIL:"):
                detail = line.split(":", 1)[1].strip()
        if category:
            record_outcome(cycle, category, detail, success)
            print(f"  [4] Recorded: {category} success={success}")
        
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
