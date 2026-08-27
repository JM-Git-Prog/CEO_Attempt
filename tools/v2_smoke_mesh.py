import asyncio, sys, random, time
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.stages.trellis2_generator import _build_trellis2_workflow

async def main():
    client = ComfyUIClient(timeout_s=3600, poll_interval_s=3.0)
    ok = await client.health_check()
    if not ok:
        print("FAIL: ComfyUI not reachable")
        return 1

    await client.release_vram()

    # Create a fresh unique test image (white box on white BG with a colored object)
    img = Image.new("RGB", (512, 512), (255, 255, 255))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    # Draw a simple "coffee mug" shape
    draw.rectangle([160, 200, 352, 400], fill=(139, 90, 43))
    draw.ellipse([160, 180, 352, 220], fill=(139, 90, 43))
    draw.rectangle([352, 250, 400, 350], fill=(139, 90, 43))  # handle
    
    test_img = Path("output/smoke_mesh/v2_smoke_input.png")
    test_img.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(test_img))
    
    # Upload fresh image
    uploaded = await client.upload_image(test_img)
    print(f"Uploaded: {uploaded}")

    seed = int(time.time() * 1000) % (2**31 - 1)
    print(f"Using seed={seed}")

    workflow = _build_trellis2_workflow(
        uploaded,
        steps=12,
        target_triangles=12000,
        seed=seed,
    )
    workflow["6"]["inputs"]["filename_prefix"] = "v2-smoke-fresh"

    print("Submitting Trellis2 smoke workflow with fresh image...")
    prompt_id = await client.submit_workflow(
        workflow, client_id="v2-smoke-fresh", timeout_s=3600
    )
    print(f"  prompt_id={prompt_id}")

    print("Waiting for completion (up to 10 min)...")
    entry = await client.wait_for_completion(prompt_id, timeout_s=600)
    status = entry.get("status", {}).get("status_str")
    print(f"  Status: {status}")
    outputs = entry.get("outputs", {})
    print(f"  Output node keys: {list(outputs.keys())}")
    if outputs:
        for k, v in outputs.items():
            import json
            print(f"    node {k}: {json.dumps(v, default=str)[:500]}")

    # Check if the file was written to the output directory
    import httpx
    # Re-fetch history to get the full entry
    async with httpx.AsyncClient(timeout=30.0) as hc:
        resp = await hc.get(f"{client.base_url}/history/{prompt_id}")
        raw = resp.json()
    
    full_entry = raw.get(prompt_id, {})
    full_outputs = full_entry.get("outputs", {})
    import json
    print(f"\n  Raw outputs from history: {json.dumps(full_outputs, default=str)[:1000]}")

    # Try to get the mesh
    out_dir = Path("output/smoke_mesh")
    try:
        glb_path = await client.get_output_mesh(
            prompt_id, out_dir, "smoke_test.glb", node_id="6"
        )
        print(f"  get_output_mesh succeeded: {glb_path}")
    except Exception as e:
        print(f"  get_output_mesh failed: {e}")
        
        # Fallback: scan disk for the output file
        import glob
        comfy_output = Path(r"C:\Users\JohnM\ComfyUI-Installs\ComfyUI\ComfyUI\output")
        danny_output = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders")
        for base in [comfy_output, danny_output]:
            for p in sorted(base.rglob("v2-smoke-fresh*.glb"), key=lambda x: x.stat().st_mtime, reverse=True):
                print(f"  Found on disk: {p} ({p.stat().st_size:,} bytes)")
                # Copy it to our output
                import shutil
                glb_path = out_dir / "smoke_test.glb"
                shutil.copy2(p, glb_path)
                break
            else:
                continue
            break
        else:
            print("  No GLB found on disk either")
            return 1

    if not glb_path.is_file():
        print("FAIL: GLB file not found")
        return 1

    size = glb_path.stat().st_size
    print(f"  File size: {size:,} bytes")
    if size < 10_000:
        print("FAIL: GLB suspiciously small")
        return 1

    with open(glb_path, "rb") as f:
        magic = f.read(4)
    if magic != b"glTF":
        print(f"FAIL: bad magic {magic!r}")
        return 1

    import trimesh
    scene = trimesh.load(str(glb_path), force="scene", process=False)
    faces = sum(len(g.faces) for g in scene.geometry.values() if hasattr(g, "faces"))
    verts = sum(len(g.vertices) for g in scene.geometry.values() if hasattr(g, "vertices"))
    print(f"  Faces: {faces}, Vertices: {verts}")
    if faces < 100 or verts < 50:
        print("FAIL: mesh below quality gate")
        return 1

    print(f"\nPASS: valid GLB ({size:,} bytes, {faces} faces, {verts} verts)")
    return 0

sys.exit(asyncio.run(main()))
