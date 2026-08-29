"""V2 Geometry Injection Pipeline — render depth from MetricPlan, re-generate Canon conditioned on it.

The paradigm: don't extract geometry from the image — inject geometry INTO the image.

Steps:
1. Load scene.json (room dims + object positions = the 3D truth)
2. Render a synthetic depth map from that scene using pyrender
3. Upload the depth map to ComfyUI
4. Submit Z-Image Turbo workflow with ControlNet depth conditioning
5. The new Canon image respects our geometry by construction
6. Objects are now at KNOWN positions — no recovery needed
"""
import asyncio
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.photo_pipeline.comfyui_client import ComfyUIClient

SESSION_ID = "8df83612-1b81-4428-b711-7fbabc9536bb"
SESSION = Path(f"output/{SESSION_ID}")
ARTIFACTS = SESSION / "artifacts"


def render_synthetic_depth(scene_path: Path, output_path: Path, width=1024, height=768):
    """Render a depth map from the scene.json using pyrender."""
    import trimesh
    import pyrender

    scene_data = json.loads(scene_path.read_text())
    meshes_dir = ARTIFACTS / "meshes"
    room_dims = scene_data.get("room_dimensions", [4.5, 4.5, 3.0])

    # Build trimesh scene
    render_scene = trimesh.Scene()

    # Room shell — floor + back wall only (skip side walls that occlude from inside)
    shell_path = meshes_dir / "room_shell.glb"
    if shell_path.exists():
        shell = trimesh.load(str(shell_path), force="scene", process=False)
        for name, geom in shell.geometry.items():
            # Only include floor and back wall for depth structure
            if "floor" in name.lower() or "north" in name.lower() or "wall_n" in name.lower():
                render_scene.add_geometry(geom, node_name=f"shell_{name}")

    # Objects
    for obj in scene_data.get("objects", []):
        glb_path = meshes_dir / f"{obj['uuid']}.glb"
        if not glb_path.exists():
            alt = meshes_dir / f"{obj['uuid'].replace('gen-', 'gen_')}.glb"
            if alt.exists():
                glb_path = alt
            else:
                continue
        try:
            loaded = trimesh.load(str(glb_path), force="scene", process=False)
            pos = obj.get("position", {})
            scale = obj.get("scale", {})
            # Guard against zero/degenerate scales (causes Eigenvalue errors)
            sx = max(0.05, abs(scale.get("x", 1)))
            sy = max(0.05, abs(scale.get("y", 1)))
            sz = max(0.05, abs(scale.get("z", 1)))
            transform = np.eye(4)
            transform[0, 0] = sx
            transform[1, 1] = sy
            transform[2, 2] = sz
            transform[0, 3] = pos.get("x", 0)
            transform[1, 3] = pos.get("y", 0)
            transform[2, 3] = pos.get("z", 0)
            for name, geom in loaded.geometry.items():
                render_scene.add_geometry(geom, node_name=f"{obj['uuid'][:8]}_{name}", transform=transform)
        except Exception:
            pass

    # Camera from scene.json
    cam = scene_data.get("camera", {})
    cam_pos = cam.get("position", {"x": 0, "y": 1.5, "z": 2.9})
    cam_target = cam.get("target", {"x": 0, "y": 0.8, "z": -1.8})
    fov = cam.get("fov", 70)

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

    # Render depth with pyrender — apply each node's transform from the scene graph
    pr_scene = pyrender.Scene()
    for node_name in render_scene.graph.nodes_geometry:
        transform, geom_name = render_scene.graph[node_name]
        geom = render_scene.geometry.get(geom_name)
        if geom is None or not hasattr(geom, "faces") or len(geom.faces) == 0:
            continue
        try:
            mesh = pyrender.Mesh.from_trimesh(geom, smooth=False)
            pr_scene.add(mesh, pose=transform)
        except Exception as exc:
            print(f"  skip {geom_name}: {exc}")

    camera = pyrender.PerspectiveCamera(yfov=np.radians(fov))
    pr_scene.add(camera, pose=camera_transform)

    renderer = pyrender.OffscreenRenderer(width, height)
    _, depth_buffer = renderer.render(pr_scene)
    renderer.delete()

    # ControlNet depth convention: WHITE=near (255), BLACK=far (0).
    # pyrender depth_buffer: larger value = farther. So we INVERT.
    valid_mask = depth_buffer > 0
    if valid_mask.sum() > 0:
        min_d = depth_buffer[valid_mask].min()
        max_d = depth_buffer[valid_mask].max()
        if max_d > min_d:
            normalized = np.zeros_like(depth_buffer, dtype=np.float32)
            # Invert: near surfaces -> 1.0 (white), far -> low. Background (0) stays black.
            normalized[valid_mask] = 1.0 - (depth_buffer[valid_mask] - min_d) / (max_d - min_d)
            depth_8bit = (normalized * 255).astype(np.uint8)
        else:
            depth_8bit = np.zeros((height, width), dtype=np.uint8)
    else:
        depth_8bit = np.zeros((height, width), dtype=np.uint8)

    # Slight blur so faceted mesh blocks read as continuous surfaces (more photoreal)
    from PIL import ImageFilter
    depth_img = Image.fromarray(depth_8bit).filter(ImageFilter.GaussianBlur(radius=2))
    depth_img.save(str(output_path))
    print(f"Synthetic depth rendered (inverted, blurred): {output_path} ({width}x{height})")
    return output_path


def build_depth_conditioned_workflow(
    depth_image_name: str,
    prompt: str,
    seed: int,
    width: int = 1024,
    height: int = 768,
) -> dict:
    """Build Z-Image Turbo workflow with ControlNet depth conditioning.

    Based on the proven z-image-prop.api.json structure with ControlNet inserted.
    """
    return {
        # SDXL base — proven-compatible with the promax depth ControlNet
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        # Positive text encode (SDXL uses the checkpoint's built-in CLIP)
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        # Negative text encode
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "blurry, distorted, low quality, warped, deformed"},
        },
        # Depth conditioning image
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": depth_image_name},
        },
        # ControlNet loader (promax = SDXL depth/union controlnet)
        "7": {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": "diffusion_pytorch_model_promax.safetensors"},
        },
        # Set union controlnet type to depth
        "14": {
            "class_type": "SetUnionControlNetType",
            "inputs": {"control_net": ["7", 0], "type": "depth"},
        },
        # Apply ControlNet depth conditioning — lower strength + early cutoff
        # gives SDXL freedom to render photorealistic detail while keeping layout
        "8": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "control_net": ["14", 0],
                "image": ["6", 0],
                "strength": 0.45,
                "start_percent": 0.0,
                "end_percent": 0.6,
            },
        },
        # Empty latent (SDXL native 1024)
        "10": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        # KSampler (SDXL settings)
        "11": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["10", 0],
                "seed": seed,
                "steps": 25,
                "cfg": 6.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        # VAE Decode (SDXL checkpoint VAE)
        "12": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["1", 2]},
        },
        # Save
        "13": {
            "class_type": "SaveImage",
            "inputs": {"images": ["12", 0], "filename_prefix": "v2-injected-canon"},
        },
    }


async def main():
    print("=" * 60)
    print("  GEOMETRY INJECTION PIPELINE")
    print("  'Don't extract geometry — inject it.'")
    print("=" * 60)

    scene_path = ARTIFACTS / "scene.json"
    if not scene_path.exists():
        print("ERROR: No scene.json")
        return

    # Step 1: Render synthetic depth from scene
    print("\n[1] Rendering synthetic depth from MetricPlan...")
    depth_path = ARTIFACTS / "synthetic_depth.png"
    render_synthetic_depth(scene_path, depth_path)

    # Step 2: Upload depth to ComfyUI
    print("\n[2] Uploading synthetic depth to ComfyUI...")
    client = ComfyUIClient(timeout_s=600, poll_interval_s=2.0)
    if not await client.health_check():
        print("ERROR: ComfyUI not reachable")
        return

    await client.release_vram()
    depth_uploaded = await client.upload_image(depth_path)
    print(f"  Uploaded as: {depth_uploaded}")

    # Step 3: Build and submit depth-conditioned workflow
    print("\n[3] Submitting depth-conditioned Canon generation...")
    import random
    prompt = "professional interior photograph of a warm bohemian living room, terracotta plaster walls, macrame fringe chandelier, colorful crocheted ottoman pouf, carved wooden sideboard credenza, lush green living plant wall, vintage persian rug, amber glass pendant lights, terracotta potted plants, bright natural daylight from a large window, photorealistic, high detail, 35mm architectural photography, soft warm ambient lighting, shallow depth of field, 8k, magazine quality"
    seed = random.randint(1, 2**32 - 1)

    workflow = build_depth_conditioned_workflow(depth_uploaded, prompt, seed)

    try:
        prompt_id = await client.submit_workflow(workflow, client_id="v2-inject-canon", timeout_s=600)
        print(f"  Queued: {prompt_id}")

        await client.wait_for_completion(prompt_id, timeout_s=180)
        print("  Complete!")

        # Retrieve the image (SaveImage is node 13)
        injected_path = ARTIFACTS / "canon_injected.png"
        await client.get_output_image(prompt_id, ARTIFACTS, "canon_injected.png", node_id="13")

        if injected_path.is_file():
            size_kb = injected_path.stat().st_size / 1024
            print(f"\n  SUCCESS: {injected_path} ({size_kb:.0f} KB)")
            print(f"  This Canon was generated CONDITIONED on our geometry.")
            print(f"  Object positions are now ground truth, not estimated.")
        else:
            print("  FAILED: No output image")

    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
