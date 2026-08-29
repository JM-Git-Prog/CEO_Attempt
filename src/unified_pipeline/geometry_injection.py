"""V2.0 Geometry Injection stage — inject geometry into content, don't extract it.

After the walkable world is assembled (room + objects at known 3D positions),
this stage:
1. Renders a synthetic depth map from the scene (pyrender)
2. Re-generates a photorealistic Canon conditioned on that depth (SDXL + promax ControlNet)
3. Textures the meshes by projecting each object's 3D bbox into the injected Canon

Because the image is generated to match the geometry, object positions are
ground truth — no lossy recovery. This inverts the scene-recovery problem.

Proven-compatible depth conditioning: SDXL base + promax union ControlNet (depth).
Z-Image/Lumina2 + promax is INCOMPATIBLE (architecture mismatch).
"""
from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

from src.photo_pipeline.comfyui_client import ComfyUIClient

logger = logging.getLogger("live_trace")

DEPTH_STRENGTH = 0.45
DEPTH_END_PERCENT = 0.6


def render_synthetic_depth(
    scene_data: dict[str, Any],
    meshes_dir: Path,
    output_path: Path,
    width: int = 1024,
    height: int = 768,
) -> Path | None:
    """Render a depth map from the scene's object positions using pyrender.

    ControlNet depth convention: WHITE=near, BLACK=far. Objects get their
    per-node transforms applied (trimesh Scene iteration otherwise loses them).
    """
    import trimesh
    import pyrender

    room_dims = scene_data.get("room_dimensions", [5.0, 6.0, 3.0])
    render_scene = trimesh.Scene()

    # Room shell — floor + back wall only (side walls occlude inside-room camera)
    shell_path = meshes_dir / "room_shell.glb"
    if shell_path.exists():
        shell = trimesh.load(str(shell_path), force="scene", process=False)
        for name, geom in shell.geometry.items():
            if "floor" in name.lower() or "north" in name.lower() or "wall_n" in name.lower():
                render_scene.add_geometry(geom, node_name=f"shell_{name}")

    # Objects with transforms
    for obj in scene_data.get("objects", []):
        glb_path = meshes_dir / f"{obj['uuid']}.glb"
        if not glb_path.exists():
            continue
        try:
            loaded = trimesh.load(str(glb_path), force="scene", process=False)
            pos = obj.get("position", {})
            scale = obj.get("scale", {})
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

    cam = scene_data.get("camera", {})
    cam_pos = cam.get("position", {"x": 0, "y": 1.5, "z": 2.6})
    cam_target = cam.get("target", {"x": 0, "y": 1.0, "z": -2.0})
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

    try:
        pr_scene = pyrender.Scene()
        for node_name in render_scene.graph.nodes_geometry:
            transform, geom_name = render_scene.graph[node_name]
            geom = render_scene.geometry.get(geom_name)
            if geom is None or not hasattr(geom, "faces") or len(geom.faces) == 0:
                continue
            try:
                mesh = pyrender.Mesh.from_trimesh(geom, smooth=False)
                pr_scene.add(mesh, pose=transform)
            except Exception:
                pass

        camera = pyrender.PerspectiveCamera(yfov=np.radians(fov))
        pr_scene.add(camera, pose=camera_transform)
        renderer = pyrender.OffscreenRenderer(width, height)
        _, depth_buffer = renderer.render(pr_scene)
        renderer.delete()
    except Exception as exc:
        logger.warning(f"  V2 depth render failed: {exc}")
        return None

    valid_mask = depth_buffer > 0
    if valid_mask.sum() == 0:
        return None
    min_d = depth_buffer[valid_mask].min()
    max_d = depth_buffer[valid_mask].max()
    normalized = np.zeros_like(depth_buffer, dtype=np.float32)
    if max_d > min_d:
        normalized[valid_mask] = 1.0 - (depth_buffer[valid_mask] - min_d) / (max_d - min_d)
    depth_8bit = (normalized * 255).astype(np.uint8)

    depth_img = Image.fromarray(depth_8bit).filter(ImageFilter.GaussianBlur(radius=2))
    depth_img.save(str(output_path))
    logger.info(f"  V2 synthetic depth rendered: {output_path.name}")
    return output_path


def _build_depth_workflow(depth_image_name: str, prompt: str, seed: int, width=1024, height=768) -> dict:
    """SDXL + promax depth ControlNet workflow (proven-compatible pair)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "blurry, distorted, low quality, warped, deformed, cartoon, illustration"}},
        "6": {"class_type": "LoadImage", "inputs": {"image": depth_image_name}},
        "7": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "diffusion_pytorch_model_promax.safetensors"}},
        "14": {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["7", 0], "type": "depth"}},
        "8": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0], "control_net": ["14", 0], "image": ["6", 0],
            "strength": DEPTH_STRENGTH, "start_percent": 0.0, "end_percent": DEPTH_END_PERCENT,
        }},
        "10": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "11": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["8", 0], "negative": ["8", 1], "latent_image": ["10", 0],
            "seed": seed, "steps": 25, "cfg": 6.5, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
        }},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["1", 2]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "v2-injected-canon"}},
    }


def _project_point(point_3d, cam_pos, cam_target, fov_deg, aspect):
    """Project 3D point to normalized screen [0,1], or None if behind camera."""
    eye = np.array(cam_pos)
    target = np.array(cam_target)
    point = np.array(point_3d)
    forward = target - eye
    forward = forward / (np.linalg.norm(forward) + 1e-8)
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, up)
    right = right / (np.linalg.norm(right) + 1e-8)
    cam_up = np.cross(right, forward)
    p_local = point - eye
    x = np.dot(p_local, right)
    y = np.dot(p_local, cam_up)
    z = np.dot(p_local, forward)
    if z <= 0.01:
        return None
    tan_half = math.tan(math.radians(fov_deg) / 2)
    return ((x / (z * tan_half * aspect) + 1) / 2, (1 - y / (z * tan_half)) / 2)


def _sample_region_color(canon_img, screen_bbox):
    w, h = canon_img.size
    sb = [max(0.0, min(1.0, v)) for v in screen_bbox]
    x1 = max(0, min(int(sb[0] * w), w - 1))
    y1 = max(0, min(int(sb[1] * h), h - 1))
    x2 = max(x1 + 1, min(int(sb[2] * w), w))
    y2 = max(y1 + 1, min(int(sb[3] * h), h))
    region = np.array(canon_img.crop((x1, y1, x2, y2)))
    if region.size == 0:
        return (128, 128, 128)
    pixels = region.reshape(-1, region.shape[-1])[:, :3]
    brightness = pixels.mean(axis=1)
    mask = (brightness > 25) & (brightness < 245)
    med = np.median(pixels[mask] if mask.sum() > 0 else pixels, axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2]))


def texture_meshes_from_canon(scene_data: dict, meshes_dir: Path, canon_path: Path) -> int:
    """Project each object into the injected Canon and color its mesh accordingly."""
    import trimesh

    canon_img = Image.open(canon_path).convert("RGB")
    aspect = canon_img.width / canon_img.height
    cam = scene_data["camera"]
    cam_pos = [cam["position"]["x"], cam["position"]["y"], cam["position"]["z"]]
    cam_target = [cam["target"]["x"], cam["target"]["y"], cam["target"]["z"]]
    fov = cam.get("fov", 70)

    textured = 0
    for obj in scene_data.get("objects", []):
        glb = meshes_dir / f"{obj['uuid']}.glb"
        if not glb.exists():
            continue
        try:
            loaded = trimesh.load(str(glb), force="scene", process=False)
            all_v = [np.array(g.vertices) for g in loaded.geometry.values() if hasattr(g, "vertices")]
            if not all_v:
                continue
            verts = np.vstack(all_v)
            vmin, vmax = verts.min(axis=0), verts.max(axis=0)
            scale = obj.get("scale", {})
            sx, sy, sz = scale.get("x", 1), scale.get("y", 1), scale.get("z", 1)
            pos = obj.get("position", {})
            px, py, pz = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)

            pts = []
            for cx in (vmin[0], vmax[0]):
                for cy in (vmin[1], vmax[1]):
                    for cz in (vmin[2], vmax[2]):
                        p = _project_point([cx * sx + px, cy * sy + py, cz * sz + pz], cam_pos, cam_target, fov, aspect)
                        if p:
                            pts.append(p)
            if len(pts) < 2:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            rgb = _sample_region_color(canon_img, (min(xs), min(ys), max(xs), max(ys)))

            r, g, b = rgb
            modified = False
            for geom in loaded.geometry.values():
                if not hasattr(geom, "visual"):
                    continue
                v = geom.visual
                if v.kind == "texture" and hasattr(v, "material"):
                    v.material.baseColorFactor = np.array([r, g, b, 255], dtype=np.uint8)
                    modified = True
                elif v.kind == "vertex":
                    geom.visual.vertex_colors = np.full((len(geom.vertices), 4), [r, g, b, 255], dtype=np.uint8)
                    modified = True
                elif v.kind == "face":
                    geom.visual.face_colors = np.full((len(geom.faces), 4), [r, g, b, 255], dtype=np.uint8)
                    modified = True
            if modified:
                loaded.export(str(glb), file_type="glb")
                textured += 1
        except Exception:
            pass

    logger.info(f"  V2 textured {textured} meshes from injected Canon")
    return textured


async def inject_geometry(
    brief: dict[str, Any],
    session_dir: Path,
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> Path | None:
    """Full geometry injection: render depth -> generate Canon -> texture meshes.

    Returns the path to the injected Canon, or None on failure.
    """
    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    artifacts = session_dir / "artifacts"
    scene_path = artifacts / "scene.json"
    meshes_dir = artifacts / "meshes"
    if not scene_path.is_file():
        logger.warning("  V2 inject: no scene.json — skipping")
        return None

    scene_data = json.loads(scene_path.read_text(encoding="utf-8"))

    # Step 1: render synthetic depth
    emit("phase_start", {"phase": "inject_depth", "message": "Rendering geometry depth..."})
    depth_path = artifacts / "synthetic_depth.png"
    if render_synthetic_depth(scene_data, meshes_dir, depth_path) is None:
        logger.warning("  V2 inject: depth render failed")
        return None

    # Step 2: re-generate Canon conditioned on depth
    emit("phase_start", {"phase": "inject_canon", "message": "Injecting geometry into photorealistic Canon..."})
    client = ComfyUIClient(timeout_s=300, poll_interval_s=2.0)
    if not await client.health_check():
        logger.warning("  V2 inject: ComfyUI unavailable")
        return None

    await client.release_vram()
    # Unique filename per run so ComfyUI doesn't dedupe-rename
    depth_upload_name = f"v2-depth-{session_dir.name[:8]}-{random.randint(1000, 9999)}.png"
    import shutil
    unique_depth = artifacts / depth_upload_name
    shutil.copy2(depth_path, unique_depth)
    uploaded = await client.upload_image(unique_depth)

    prompt = _build_prompt_from_brief(brief)
    seed = random.randint(1, 2**32 - 1)
    workflow = _build_depth_workflow(uploaded, prompt, seed)

    injected_path = artifacts / "canon_injected.png"
    try:
        prompt_id = await client.submit_workflow(workflow, client_id=f"v2-inject-{session_dir.name[:8]}", timeout_s=300)
        await client.wait_for_completion(prompt_id, timeout_s=180)
        await client.get_output_image(prompt_id, artifacts, "canon_injected.png", node_id="13")
    except Exception as exc:
        logger.warning(f"  V2 inject: Canon generation failed: {exc}")
        return None

    if not injected_path.is_file():
        return None

    emit("canon_injected", {"image_url": f"/api/v2/session/{session_dir.name}/artifact/canon_injected"})

    # Step 3: texture meshes from the injected Canon
    emit("phase_start", {"phase": "inject_texture", "message": "Texturing objects from injected Canon..."})
    textured = texture_meshes_from_canon(scene_data, meshes_dir, injected_path)
    emit("meshes_textured", {"count": textured})

    logger.info(f"  V2 geometry injection complete: Canon + {textured} textured meshes")
    return injected_path


def _build_prompt_from_brief(brief: dict[str, Any]) -> str:
    """Build a photorealistic prompt from the Brief's room description."""
    desc = brief.get("description") or brief.get("room_type") or "a bohemian living room"
    objects = brief.get("objects", [])
    obj_str = ", ".join(o.get("name", "") for o in objects[:10] if isinstance(o, dict)) if objects else ""
    base = f"professional interior photograph of {desc}"
    if obj_str:
        base += f", featuring {obj_str}"
    base += ", photorealistic, high detail, 35mm architectural photography, soft warm ambient lighting, magazine quality, 8k"
    return base
