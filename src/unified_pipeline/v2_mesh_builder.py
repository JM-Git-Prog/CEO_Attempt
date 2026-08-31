"""V2.0 Mesh Builder — Phase 4 (Build).

For each cataloged object:
1. Crop the best reference view to the object's bounding box
2. Run SAM3 text-conditioned segmentation to get a clean RGBA cutout
3. Feed to Hunyuan3D (fallback Trellis2, fallback placeholder)
4. Automated quality gate only — no manual approval

Also generates the parametric room shell from the MetricPlan.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.stages.hunyuan3d_v2_generator import (
    _build_hunyuan3d_v2_workflow,
)
from src.photo_pipeline.stages.trellis2_generator import _build_trellis2_workflow
from src.unified_pipeline.multi_view_generator import MultiViewResult
from src.unified_pipeline.vision_catalog import CatalogEntry, ObjectCatalog

logger = logging.getLogger("live_trace")

# Mesh quality thresholds (same as V16)
MIN_FACES = 100
MIN_VERTICES = 50
HUNYUAN_TIMEOUT_S = 600
TRELLIS_TIMEOUT_S = 3600


@dataclass
class MeshResult:
    """Result of generating one object's mesh."""

    uuid: str
    name: str
    glb_path: str
    face_count: int = 0
    vertex_count: int = 0
    generation_method: str = ""
    is_placeholder: bool = False
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: float = 0.0
    dimensions: tuple[float, float, float] = (0.5, 0.5, 0.5)


async def _crop_and_isolate(
    canon_path: Path,
    bbox: list[int],
    object_name: str,
    output_dir: Path,
    object_uuid: str,
) -> Path | None:
    """Crop the object region from the Canon and run SAM3 for RGBA isolation.

    Falls back to a simple alpha-masked crop if SAM3 is unavailable.
    """
    from PIL import Image

    if not canon_path.is_file():
        return None

    # Crop the bounding box region with padding
    with Image.open(canon_path) as img:
        img_w, img_h = img.size
        x1, y1, x2, y2 = bbox
        # Add 5% padding
        pad_x = max(4, int((x2 - x1) * 0.05))
        pad_y = max(4, int((y2 - y1) * 0.05))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(img_w, x2 + pad_x)
        y2 = min(img_h, y2 + pad_y)
        crop = img.crop((x1, y1, x2, y2)).convert("RGB")

    output_dir.mkdir(parents=True, exist_ok=True)
    crop_path = output_dir / "crop.png"
    crop.save(crop_path, "PNG")

    # Try SAM3 text-conditioned segmentation via ComfyUI
    rgba_path = output_dir / "object_rgba.png"

    try:
        client = ComfyUIClient(timeout_s=120, poll_interval_s=0.75)
        if not await client.health_check():
            raise RuntimeError("ComfyUI unavailable")

        # Upload the crop
        uploaded = await client.upload_image(crop_path)

        # Build SAM3 text-conditioned workflow
        prompt_text = f"the {object_name}"
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 1], "text": prompt_text},
            },
            "4": {
                "class_type": "SAM3_Detect",
                "inputs": {
                    "model": ["2", 0],
                    "conditioning": ["3", 0],
                    "image": ["1", 0],
                    "threshold": 0.5,
                    "refine_iterations": 2,
                    "individual_masks": False,
                },
            },
            "5": {"class_type": "GrowMask", "inputs": {"mask": ["4", 0], "expand": 2, "tapered_corners": True}},
            "6": {"class_type": "InvertMask", "inputs": {"mask": ["5", 0]}},
            "7": {
                "class_type": "JoinImageWithAlpha",
                "inputs": {"image": ["1", 0], "alpha": ["6", 0]},
            },
            "8": {
                "class_type": "SaveImage",
                "inputs": {"images": ["7", 0], "filename_prefix": f"v2-obj-{object_uuid[:8]}"},
            },
        }

        prompt_id = await client.submit_workflow(workflow, client_id=f"v2-sam-{object_uuid[:16]}")
        await client.wait_for_completion(prompt_id, timeout_s=120)
        await client.get_output_image(prompt_id, output_dir, "object_rgba.png", node_id="8")

        if rgba_path.is_file():
            return rgba_path

    except Exception as exc:
        logger.warning(f"  V2 SAM3 failed for {object_name}: {exc}")

    # Fallback: create a simple RGBA by putting the crop on white with a soft edge mask
    try:
        from PIL import Image, ImageFilter

        with Image.open(crop_path) as crop_img:
            w, h = crop_img.size
            # Create a simple elliptical mask
            mask = Image.new("L", (w, h), 0)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(mask)
            draw.ellipse([w * 0.05, h * 0.05, w * 0.95, h * 0.95], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, min(w, h) // 20)))

            rgba = crop_img.convert("RGBA")
            rgba.putalpha(mask)
            rgba.save(rgba_path, "PNG")
            return rgba_path
    except Exception:
        pass

    return None


async def _prepare_mesh_input(rgba_path: Path, output_dir: Path, object_uuid: str) -> Path:
    """Prepare the RGBA image for mesh generation — composite on white, square, pad."""
    from PIL import Image

    with Image.open(rgba_path) as source:
        rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            # Empty mask — use full image
            bbox = (0, 0, rgba.width, rgba.height)
        cropped = rgba.crop(bbox)
        w, h = cropped.size

    # Pad to square with white background
    padding = max(4, int(max(w, h) * 0.05))
    side = max(w, h) + 2 * padding
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    foreground = Image.new("RGB", cropped.size, (255, 255, 255))
    foreground.paste(cropped.convert("RGB"), mask=cropped.getchannel("A"))
    canvas.paste(foreground, ((side - w) // 2, (side - h) // 2))

    prepared_path = output_dir / f"{object_uuid}_prepared.png"
    canvas.save(prepared_path, "PNG")
    return prepared_path


def _workflow_schema_errors(
    workflow: dict[str, Any], object_info: dict[str, Any]
) -> list[str]:
    """Return missing node types or invalid input names for a live ComfyUI schema."""
    errors: list[str] = []
    for node_id, node in workflow.items():
        class_type = node.get("class_type")
        schema = object_info.get(class_type)
        if not isinstance(schema, dict):
            errors.append(f"node {node_id}: missing class {class_type}")
            continue

        schema_inputs = schema.get("input", {})
        declared_inputs: set[str] = set()
        for input_group in ("required", "optional", "hidden"):
            group = schema_inputs.get(input_group, {})
            if isinstance(group, dict):
                declared_inputs.update(group)

        supplied_inputs = set(node.get("inputs", {}))
        unknown_inputs = sorted(supplied_inputs - declared_inputs)
        if unknown_inputs:
            errors.append(
                f"node {node_id} ({class_type}): unknown inputs {unknown_inputs}"
            )

        required = schema_inputs.get("required", {})
        if isinstance(required, dict):
            missing_inputs = sorted(set(required) - supplied_inputs)
            if missing_inputs:
                errors.append(
                    f"node {node_id} ({class_type}): missing inputs {missing_inputs}"
                )
    return errors


async def _preflight_mesh_lanes(client: ComfyUIClient) -> dict[str, bool]:
    """Validate both mesh workflows against one live ``/object_info`` response."""
    lanes = {
        "hunyuan3d_v2.1": _build_hunyuan3d_v2_workflow("preflight.png"),
        "trellis2": _build_trellis2_workflow("preflight.png"),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.get(f"{client.base_url}/object_info")
            response.raise_for_status()
            object_info = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("  V2 mesh schema preflight unavailable: %s", exc)
        return {lane: True for lane in lanes}

    availability: dict[str, bool] = {}
    for lane, workflow in lanes.items():
        errors = _workflow_schema_errors(workflow, object_info)
        availability[lane] = not errors
        if errors:
            logger.warning("  V2 %s preflight failed: %s", lane, "; ".join(errors))
        else:
            logger.info("  V2 %s preflight passed", lane)
    return availability


async def _generate_mesh_hunyuan(
    client: ComfyUIClient,
    prepared_path: Path,
    output_dir: Path,
    object_uuid: str,
) -> Path | None:
    """Generate a real GLB through the verified Hunyuan3D 2.1 graph."""
    uploaded = await client.upload_image(prepared_path)
    workflow = _build_hunyuan3d_v2_workflow(
        uploaded,
        steps=50,
        cfg=7.0,
        octree_resolution=384,
        seed=random.randint(1, 2**32 - 1),
    )
    workflow["9"]["inputs"]["filename_prefix"] = f"v2-mesh-{object_uuid[:12]}"

    prompt_id = await client.submit_workflow(
        workflow,
        client_id=f"v2-hunyuan-{object_uuid[:16]}",
        timeout_s=HUNYUAN_TIMEOUT_S,
    )
    await client.wait_for_completion(prompt_id, timeout_s=HUNYUAN_TIMEOUT_S)
    glb_path = await client.get_output_mesh(
        prompt_id, output_dir, f"{object_uuid}.glb", node_id="9"
    )
    return glb_path if glb_path.is_file() else None


async def _generate_mesh_trellis(
    client: ComfyUIClient,
    prepared_path: Path,
    output_dir: Path,
    object_uuid: str,
) -> Path | None:
    """Generate a textured GLB through the verified Trellis2 GGUF one-pass graph.

    Trellis2 produces mesh AND texture together — no separate paint step needed.
    The ExportMesh_GGUF node emits a STRING output (glb_path) which may not appear
    in ComfyUI's standard history outputs dict. Fallback: scan the ComfyUI output
    directory for the file by prefix.
    """
    uploaded = await client.upload_image(prepared_path)
    prefix = f"v2-trellis-{object_uuid[:12]}"
    workflow = _build_trellis2_workflow(
        uploaded,
        steps=12,
        target_triangles=30000,
        seed=random.randint(1, 2**31 - 1),
    )
    workflow["6"]["inputs"]["filename_prefix"] = prefix

    prompt_id = await client.submit_workflow(
        workflow,
        client_id=f"v2-trellis-{object_uuid[:16]}",
        timeout_s=TRELLIS_TIMEOUT_S,
    )
    await client.wait_for_completion(prompt_id, timeout_s=TRELLIS_TIMEOUT_S)

    # Primary: retrieve via standard get_output_mesh (handles file records + bare paths)
    glb_path = output_dir / f"{object_uuid}.glb"
    try:
        result = await client.get_output_mesh(
            prompt_id, output_dir, f"{object_uuid}.glb", node_id="6"
        )
        if result.is_file() and result.stat().st_size > 1000:
            return result
    except Exception:
        pass

    # Fallback: scan ComfyUI output directory for files matching our prefix
    # (Trellis2ExportMesh_GGUF writes to ComfyUI's output dir directly)
    comfy_output = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders")
    comfy_output_alt = Path(r"C:\Users\JohnM\ComfyUI-Installs\ComfyUI\ComfyUI\output")
    for search_dir in [comfy_output, comfy_output_alt]:
        if not search_dir.exists():
            continue
        candidates = sorted(
            search_dir.rglob(f"{prefix}*.glb"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            import shutil
            shutil.copy2(candidates[0], glb_path)
            if glb_path.is_file() and glb_path.stat().st_size > 1000:
                return glb_path

    return None


def _generate_placeholder(
    object_name: str,
    output_dir: Path,
    object_uuid: str,
    dimensions: tuple[float, float, float] = (0.5, 0.5, 0.5),
) -> Path:
    """Generate a simple colored box placeholder mesh."""
    import trimesh

    w, h, d = dimensions
    box = trimesh.creation.box(extents=[w, h, d])
    # Give it a neutral color
    box.visual.face_colors = [180, 160, 140, 255]

    glb_path = output_dir / f"{object_uuid}.glb"
    box.export(str(glb_path), file_type="glb")
    return glb_path


# Target for browser-friendly mesh density (30K faces balances quality vs framerate)
BROWSER_MAX_FACES = 30000


def _decimate_for_browser(glb_path: Path) -> tuple[int, int]:
    """Decimate a GLB to BROWSER_MAX_FACES if it exceeds the budget.

    Modifies the file in-place. Returns (final_faces, final_verts).
    """
    import trimesh

    try:
        loaded = trimesh.load(str(glb_path), force="scene", process=False)
        if isinstance(loaded, trimesh.Scene):
            meshes = [(n, g) for n, g in loaded.geometry.items() if isinstance(g, trimesh.Trimesh)]
        elif isinstance(loaded, trimesh.Trimesh):
            meshes = [("mesh", loaded)]
        else:
            return 0, 0

        total_faces = sum(len(g.faces) for _, g in meshes)
        if total_faces <= BROWSER_MAX_FACES:
            total_verts = sum(len(g.vertices) for _, g in meshes)
            return total_faces, total_verts

        # Proportional reduction: simplify_quadric_decimation takes a ratio (0-1)
        # where ratio = fraction of faces to REMOVE
        reduction = 1.0 - (BROWSER_MAX_FACES / total_faces)
        reduction = max(0.01, min(0.99, reduction))

        for name, geom in meshes:
            if len(geom.faces) > 200:
                if isinstance(loaded, trimesh.Scene):
                    loaded.geometry[name] = geom.simplify_quadric_decimation(reduction)
                else:
                    loaded = geom.simplify_quadric_decimation(reduction)

        # Re-export
        if isinstance(loaded, trimesh.Scene):
            loaded.export(str(glb_path), file_type="glb")
        else:
            loaded.export(str(glb_path), file_type="glb")

        # Recount
        reloaded = trimesh.load(str(glb_path), force="scene", process=False)
        if isinstance(reloaded, trimesh.Scene):
            final_meshes = [g for g in reloaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            final_faces = sum(len(m.faces) for m in final_meshes)
            final_verts = sum(len(m.vertices) for m in final_meshes)
        elif isinstance(reloaded, trimesh.Trimesh):
            final_faces = len(reloaded.faces)
            final_verts = len(reloaded.vertices)
        else:
            final_faces, final_verts = 0, 0

        logger.info(
            f"  V2 decimated mesh: {total_faces} → {final_faces} faces for browser perf"
        )
        return final_faces, final_verts
    except Exception as exc:
        logger.warning(f"  V2 decimation failed (keeping original): {exc}")
        return -1, -1  # signal to use original validation counts


def _colorize_from_canon(
    catalog: ObjectCatalog,
    canon_path: Path,
    meshes_dir: Path,
) -> None:
    """Sample average color from Canon bbox regions and apply to GLB materials."""
    from PIL import Image
    import trimesh

    canon_img = Image.open(canon_path).convert("RGB")
    img_w, img_h = canon_img.size

    for entry in catalog.entries:
        bbox = entry.bbox_in_best_view
        x1 = max(0, min(bbox[0], img_w - 1))
        y1 = max(0, min(bbox[1], img_h - 1))
        x2 = max(x1 + 1, min(bbox[2], img_w))
        y2 = max(y1 + 1, min(bbox[3], img_h))

        crop = canon_img.crop((x1, y1, x2, y2))
        arr = np.array(crop)
        mask = arr.mean(axis=2) > 30
        if mask.sum() > 0:
            avg = arr[mask].mean(axis=0).astype(int)
        else:
            avg = arr.mean(axis=(0, 1)).astype(int)
        r, g, b = int(avg[0]), int(avg[1]), int(avg[2])

        glb_path = meshes_dir / f"{entry.uuid}.glb"
        if not glb_path.is_file():
            continue

        try:
            scene = trimesh.load(str(glb_path), force="scene", process=False)
            modified = False
            for geom in scene.geometry.values():
                if hasattr(geom, "visual") and geom.visual.kind == "texture":
                    if hasattr(geom.visual, "material"):
                        geom.visual.material.baseColorFactor = np.array(
                            [r, g, b, 255], dtype=np.uint8
                        )
                        modified = True
            if modified:
                scene.export(str(glb_path), file_type="glb")
        except Exception:
            pass

    logger.info(f"  V2 colorized {len(catalog.entries)} meshes from Canon")


def _validate_mesh(glb_path: Path) -> tuple[bool, int, int]:
    """Validate mesh meets minimum quality thresholds.

    Returns (is_valid, face_count, vertex_count).
    """
    import trimesh

    try:
        loaded = trimesh.load(str(glb_path), force="scene", process=False)
        if isinstance(loaded, trimesh.Scene):
            meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                return False, 0, 0
            total_faces = sum(len(m.faces) for m in meshes)
            total_verts = sum(len(m.vertices) for m in meshes)
        elif isinstance(loaded, trimesh.Trimesh):
            total_faces = len(loaded.faces)
            total_verts = len(loaded.vertices)
        else:
            return False, 0, 0

        valid = total_faces >= MIN_FACES and total_verts >= MIN_VERTICES
        return valid, total_faces, total_verts
    except Exception:
        return False, 0, 0


def _estimate_dimensions(size_estimate: str, category: str) -> tuple[float, float, float]:
    """Estimate object dimensions based on size category."""
    size_map = {
        "large": {"furniture": (1.2, 0.8, 1.2), "appliance": (0.6, 1.5, 0.6), "architectural": (2.0, 2.4, 0.15)},
        "medium": {"furniture": (0.6, 0.75, 0.6), "appliance": (0.4, 0.5, 0.4), "lighting": (0.3, 0.4, 0.3)},
        "small": {"furniture": (0.3, 0.4, 0.3), "appliance": (0.25, 0.3, 0.2), "decor": (0.15, 0.2, 0.15)},
        "tiny": {"decor": (0.08, 0.1, 0.08), "utensil": (0.05, 0.15, 0.05)},
    }
    size_defaults = {"large": (1.0, 1.0, 1.0), "medium": (0.5, 0.6, 0.5), "small": (0.25, 0.3, 0.25), "tiny": (0.1, 0.12, 0.1)}

    category_map = size_map.get(size_estimate, {})
    return category_map.get(category, size_defaults.get(size_estimate, (0.5, 0.5, 0.5)))


async def build_meshes(
    catalog: ObjectCatalog,
    views: MultiViewResult,
    session_dir: Path,
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[MeshResult]:
    """Generate 3D meshes for all cataloged objects (Phase 4: Build).

    For each catalog entry:
    1. Crop best view to bbox → SAM3 isolation → RGBA
    2. Hunyuan3D → Trellis2 → placeholder fallback chain
    3. Automated quality gate (no manual approval)

    Also generates the room shell from MetricPlan.

    Args:
        catalog: ObjectCatalog from Phase 3.
        views: MultiViewResult from Phase 2.
        session_dir: Session output directory.
        emit_fn: Optional SSE event emitter.

    Returns:
        List of MeshResult for all generated objects.
    """
    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    meshes_dir = session_dir / "artifacts" / "meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)
    objects_dir = session_dir / "artifacts" / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)

    results: list[MeshResult] = []

    # Build view index for quick lookup
    view_map = {v.index: v for v in views.views}

    # Initialize ComfyUI client and validate both expensive lanes once.
    client = ComfyUIClient(timeout_s=HUNYUAN_TIMEOUT_S, poll_interval_s=0.75)
    comfyui_available = await client.health_check()
    mesh_lanes = {"hunyuan3d_v2.1": False, "trellis2": False}
    if comfyui_available:
        mesh_lanes = await _preflight_mesh_lanes(client)

    # Load room dimensions from the MetricPlan (spatial authority for the box).
    plan_data = {}
    plan_path = session_dir / "artifacts" / "metric_plan.json"
    if plan_path.is_file():
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    room_dims = plan_data.get("room_dimensions", [4.0, 4.0, 2.7])

    # Depth/geometry-driven placement: back-project each object's bbox through
    # its view camera onto the floor plane, using the known room box as the
    # spatial prior. Replaces the fragile name-match-to-MetricPlan path that
    # defaulted unmatched objects to the origin (empty-world bug). Each object's
    # world (x,y,z) is looked up from this dict by uuid below.
    from src.unified_pipeline.depth_placement import place_objects as _place_objects
    capture_manifest_data = None
    manifest_path = session_dir / "artifacts" / "capture_manifest.json"
    if manifest_path.is_file():
        try:
            capture_manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"  V2 placement: capture_manifest unreadable ({exc})")
    depth_placements = _place_objects(catalog.entries, capture_manifest_data, room_dims)
    _pm = {}
    for _p in depth_placements.values():
        _pm[_p.method] = _pm.get(_p.method, 0) + 1
    logger.info(f"  V2 placement: {len(depth_placements)} objects placed via depth back-projection {_pm}")

    # Generate mesh for each cataloged object
    for idx, entry in enumerate(catalog.entries):
        logger.info(f"  V2 mesh {idx+1}/{len(catalog.entries)}: {entry.name} (uuid={entry.uuid[:8]})")

        obj_dir = objects_dir / entry.uuid
        obj_dir.mkdir(parents=True, exist_ok=True)

        # Get the best view for this object
        best_view = view_map.get(entry.best_view_index)
        if best_view is None:
            best_view = views.views[0] if views.views else None
        if best_view is None:
            logger.warning(f"  V2 no view available for {entry.name}")
            continue

        # Step 1: Crop and isolate
        canon_path = Path(best_view.canon_path)
        rgba_path = await _crop_and_isolate(
            canon_path, entry.bbox_in_best_view, entry.name, obj_dir, entry.uuid
        )

        if rgba_path is None:
            logger.warning(f"  V2 crop/isolate failed for {entry.name}")
            # Generate placeholder
            dims = _estimate_dimensions(entry.size_estimate, entry.category)
            glb_path = _generate_placeholder(entry.name, meshes_dir, entry.uuid, dims)
            results.append(MeshResult(
                uuid=entry.uuid, name=entry.name, glb_path=str(glb_path),
                face_count=12, vertex_count=8, generation_method="placeholder",
                is_placeholder=True, dimensions=dims,
            ))
            emit("mesh_ready", {"uuid": entry.uuid, "name": entry.name, "face_count": 12, "method": "placeholder",
                                "glb_url": f"/api/v2/session/{session_dir.name}/artifact/mesh_{entry.uuid}"})
            continue

        # Step 2: Prepare for mesh generation
        prepared_path = await _prepare_mesh_input(rgba_path, obj_dir, entry.uuid)

        # Step 3: Mesh generation with fallback chain
        glb_path: Path | None = None
        method = ""

        if comfyui_available:
            # Try Hunyuan3D first (proven working, geometry-only).
            if mesh_lanes["hunyuan3d_v2.1"]:
                try:
                    glb_path = await _generate_mesh_hunyuan(
                        client, prepared_path, meshes_dir, entry.uuid
                    )
                    if glb_path and glb_path.is_file():
                        method = "hunyuan3d_v2.1"
                except Exception as exc:
                    logger.warning(f"  V2 Hunyuan3D failed for {entry.name}: {exc}")

            # Trellis2 fallback (textured one-pass, but GGUF has torch 2.10 compat issues).
            if (
                mesh_lanes["trellis2"]
                and (glb_path is None or not glb_path.is_file())
            ):
                try:
                    glb_path = await _generate_mesh_trellis(
                        client, prepared_path, meshes_dir, entry.uuid
                    )
                    if glb_path and glb_path.is_file():
                        method = "trellis2"
                except Exception as exc:
                    logger.warning(f"  V2 Trellis2 failed for {entry.name}: {exc}")

        # Fallback to placeholder
        if glb_path is None or not glb_path.is_file():
            dims = _estimate_dimensions(entry.size_estimate, entry.category)
            glb_path = _generate_placeholder(entry.name, meshes_dir, entry.uuid, dims)
            method = "placeholder"

        # Step 4: Validate
        is_valid, face_count, vertex_count = _validate_mesh(glb_path)
        if not is_valid and method != "placeholder":
            logger.warning(f"  V2 mesh validation failed for {entry.name} ({face_count}f/{vertex_count}v), using placeholder")
            dims = _estimate_dimensions(entry.size_estimate, entry.category)
            glb_path = _generate_placeholder(entry.name, meshes_dir, entry.uuid, dims)
            method = "placeholder"
            face_count, vertex_count = 12, 8

        # Step 5: Decimate for browser performance (in-place)
        if method != "placeholder" and face_count > BROWSER_MAX_FACES:
            dec_faces, dec_verts = _decimate_for_browser(glb_path)
            if dec_faces > 0:
                face_count, vertex_count = dec_faces, dec_verts

        # Determine position by depth back-projection (computed above).
        rotation = 0.0
        dims = _estimate_dimensions(entry.size_estimate, entry.category)
        _dp = depth_placements.get(entry.uuid)
        if _dp is not None:
            position = (_dp.x, _dp.y, _dp.z)
        else:
            position = (0.0, 0.0, 0.0)

        result = MeshResult(
            uuid=entry.uuid,
            name=entry.name,
            glb_path=str(glb_path),
            face_count=face_count,
            vertex_count=vertex_count,
            generation_method=method,
            is_placeholder=(method == "placeholder"),
            position=position,
            rotation_deg=rotation,
            dimensions=dims,
        )
        results.append(result)

        emit("mesh_ready", {
            "uuid": entry.uuid,
            "name": entry.name,
            "face_count": face_count,
            "method": method,
            "glb_url": f"/api/v2/session/{session_dir.name}/artifact/mesh_{entry.uuid}",
            "position": {"x": position[0], "y": position[1], "z": position[2]},
            "rotation": rotation,
        })

        logger.info(f"  V2 mesh done: {entry.name} → {method} ({face_count}f)")

    # Release VRAM after all mesh generation
    if comfyui_available:
        try:
            await client.release_vram()
        except Exception:
            pass

    # Generate room shell. Prefer depth-back-projected reconstruction from the
    # capture manifest (exact known cameras); fall back to the parametric shell
    # when no manifest / insufficient coverage / reconstruction fails (Req 6.7).
    emit("phase_start", {"phase": "shell", "message": "Building room shell..."})
    shell_path: Path | None = None
    capture_manifest = getattr(views, "capture_manifest", None)
    if capture_manifest is not None and views.metric_plan is not None:
        try:
            from src.unified_pipeline.room_shell_reconstruction import (
                reconstruct_room_shell,
            )

            shell_path = reconstruct_room_shell(
                views.metric_plan, capture_manifest, meshes_dir
            )
            if shell_path:
                logger.info("  V2 room shell: reconstructed from capture manifest")
        except Exception as exc:  # noqa: BLE001 - fall back to parametric
            logger.warning("  V2 reconstruction failed (%s); using parametric", exc)
            shell_path = None

    if shell_path is None:
        shell_path = _generate_room_shell(room_dims, meshes_dir)

    if shell_path:
        emit("shell_ready", {
            "glb_url": f"/api/v2/session/{session_dir.name}/artifact/mesh_room_shell",
        })

    # Colorize meshes from Canon photo (Hunyuan3D exports grey-only GLBs)
    canon_path = session_dir / "artifacts" / "canon.png"
    if canon_path.is_file():
        try:
            _colorize_from_canon(catalog, canon_path, meshes_dir)
        except Exception as exc:
            logger.warning(f"  V2 colorization failed: {exc}")

    # Save mesh manifest
    manifest = {
        "meshes": [
            {
                "uuid": m.uuid,
                "name": m.name,
                "glb_path": m.glb_path,
                "face_count": m.face_count,
                "vertex_count": m.vertex_count,
                "method": m.generation_method,
                "is_placeholder": m.is_placeholder,
                "position": list(m.position),
                "rotation_deg": m.rotation_deg,
                "dimensions": list(m.dimensions),
            }
            for m in results
        ],
        "room_shell": str(shell_path) if shell_path else "",
        "room_dimensions": room_dims,
        "total_objects": len(results),
    }
    (session_dir / "artifacts" / "mesh_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    logger.info(f"  V2 mesh builder complete: {len(results)} objects built")
    return results


def _generate_room_shell(
    room_dimensions: list[float],
    output_dir: Path,
) -> Path | None:
    """Generate a simple parametric room shell (floor + walls) as GLB."""
    try:
        import trimesh

        w, d, h = room_dimensions[0], room_dimensions[1], room_dimensions[2]

        # Floor
        floor = trimesh.creation.box(extents=[w, 0.05, d])
        floor.apply_translation([0, -0.025, 0])
        floor.visual.face_colors = [60, 50, 45, 255]

        # Ceiling
        ceiling = trimesh.creation.box(extents=[w, 0.05, d])
        ceiling.apply_translation([0, h + 0.025, 0])
        ceiling.visual.face_colors = [240, 238, 235, 255]

        # Walls (4 sides)
        # North wall (+Z)
        north = trimesh.creation.box(extents=[w, h, 0.1])
        north.apply_translation([0, h / 2, d / 2 + 0.05])
        north.visual.face_colors = [230, 225, 220, 255]

        # South wall (-Z)
        south = trimesh.creation.box(extents=[w, h, 0.1])
        south.apply_translation([0, h / 2, -d / 2 - 0.05])
        south.visual.face_colors = [230, 225, 220, 255]

        # East wall (+X)
        east = trimesh.creation.box(extents=[0.1, h, d])
        east.apply_translation([w / 2 + 0.05, h / 2, 0])
        east.visual.face_colors = [225, 220, 215, 255]

        # West wall (-X)
        west = trimesh.creation.box(extents=[0.1, h, d])
        west.apply_translation([-w / 2 - 0.05, h / 2, 0])
        west.visual.face_colors = [225, 220, 215, 255]

        # Combine into a scene
        scene = trimesh.Scene()
        scene.add_geometry(floor, node_name="floor")
        scene.add_geometry(ceiling, node_name="ceiling")
        scene.add_geometry(north, node_name="wall_north")
        scene.add_geometry(south, node_name="wall_south")
        scene.add_geometry(east, node_name="wall_east")
        scene.add_geometry(west, node_name="wall_west")

        shell_path = output_dir / "room_shell.glb"
        scene.export(str(shell_path), file_type="glb")
        logger.info(f"  V2 room shell generated: {shell_path}")
        return shell_path

    except Exception as exc:
        logger.error(f"  V2 room shell generation failed: {exc}")
        return None
