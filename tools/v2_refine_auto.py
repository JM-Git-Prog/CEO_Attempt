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
    """Capture the 3D walkthrough via headless Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  [capture] playwright not installed")
        return None

    captures_dir = ARTIFACTS / "refine_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/?v=2.0&session={session_id}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(url)
        # Wait for mesh loading (status bar clears or 30s max)
        try:
            await page.wait_for_function(
                """() => {
                    const s = document.getElementById('statusBar');
                    return !s || !s.textContent || s.textContent === '';
                }""",
                timeout=30000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(3000)  # extra render time
        
        screenshot_path = captures_dir / f"iter_{int(time.time())}.png"
        await page.screenshot(path=str(screenshot_path))
        await browser.close()
        return screenshot_path


def vision_assess(screenshot_path: Path, canon_path: Path, extra_context: str = "") -> str:
    """Send screenshot + canon to Qwen 2.5VL and get assessment."""
    import httpx

    # Read and encode images
    screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()
    canon_b64 = base64.b64encode(canon_path.read_bytes()).decode()

    prompt = """You are comparing a 3D room reconstruction (the screenshot) against the target Canon photo.

The screenshot shows the current state of a Three.js walkable 3D world.
The Canon photo shows what the room SHOULD look like.

Assess the 3D world and identify the SINGLE MOST IMPORTANT defect to fix next.
Be extremely specific and actionable. Choose from these categories:

- POSITION: "object X should be at (x,y,z) but is at wrong location" 
- SCALE: "object X is too large/small, should be scale (sx,sy,sz)"
- COLOR: "objects are grey/wrong color, should show Canon colors"
- LIGHTING: "scene is too dark/bright, need more/less light"
- CAMERA: "camera should start at position (x,y,z) looking at (tx,ty,tz)"
- ROOM: "room dimensions should be (w,d,h) meters"
- MISSING: "object X from the Canon is not visible in the 3D scene"
- ROTATION: "object X should be rotated Y degrees"

If the 3D world looks very close to the Canon, respond with just: PASS
""" + extra_context + """

Respond in this exact format:
DEFECT: <category>
DETAIL: <specific fix instruction with numbers>
"""

    response = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": "qwen2.5vl:7b",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [canon_b64, screenshot_b64],
                }
            ],
            "stream": False,
        },
        timeout=120.0,
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
