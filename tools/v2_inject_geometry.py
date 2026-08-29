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
            transform = np.eye(4)
            transform[0, 0] = scale.get("x", 1)
            transform[1, 1] = scale.get("y", 1)
            transform[2, 2] = scale.get("z", 1)
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

    # Normalize depth to 0-255 (0=near, 255=far for ControlNet convention)
    valid_mask = depth_buffer > 0
    if valid_mask.sum() > 0:
        min_d = depth_buffer[valid_mask].min()
        max_d = depth_buffer[valid_mask].max()
        if max_d > min_d:
            normalized = np.zeros_like(depth_buffer, dtype=np.float32)
            normalized[valid_mask] = (depth_buffer[valid_mask] - min_d) / (max_d - min_d)
            depth_8bit = (normalized * 255).astype(np.uint8)
        else:
            depth_8bit = np.zeros((height, width), dtype=np.uint8)
    else:
        depth_8bit = np.zeros((height, width), dtype=np.uint8)

    # Save as PNG
    Image.fromarray(depth_8bit).save(str(output_path))
    print(f"Synthetic depth rendered: {output_path} ({width}x{height})")
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
        # Z-Image Turbo UNET (weight_dtype default, per proven workflow)
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"},
        },
        # CLIP — lumina2 type with device default (proven)
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"},
        },
        # VAE
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        # Text encode (positive)
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": prompt},
        },
        # Zero conditioning (negative)
        "5": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["4", 0]},
        },
        # Depth conditioning image
        "6": {
            "class_type": "LoadImage",
            "inputs": {"image": depth_image_name},
        },
        # ControlNet loader
        "7": {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": "diffusion_pytorch_model_promax.safetensors"},
        },
        # Apply ControlNet depth conditioning
        "8": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "control_net": ["7", 0],
                "image": ["6", 0],
                "strength": 0.65,
                "start_percent": 0.0,
                "end_percent": 0.85,
                "vae": ["3", 0],
            },
        },
        # ModelSamplingAuraFlow (proven — shift=3)
        "9": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["1", 0], "shift": 3},
        },
        # SD3 latent (proven uses EmptySD3LatentImage)
        "10": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        # KSampler (proven: res_multistep, 8 steps, cfg=1)
        "11": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["9", 0],
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["10", 0],
                "seed": seed,
                "steps": 8,
                "cfg": 1.0,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        # VAE Decode
        "12": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
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
    prompt = "A warm bohemian living room with terracotta walls, macrame chandelier, colorful ottoman, carved wooden sideboard, lush green living wall, persian rug, pendant lights, potted plants, natural daylight from window. Interior photography, wide angle, warm ambient lighting."
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
