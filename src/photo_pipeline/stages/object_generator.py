"""Object Generator — 3D mesh generation with fallback chain.

Implements the full fallback chain for converting Object_PNGs into textured
3D meshes (GLB): Hunyuan3D 2.0 → Unique3D → TripoSR → placeholder geometry.

Each neural generator submits a ComfyUI workflow, retrieves the GLB, and
validates the resulting mesh. On timeout or validation failure, the generator
falls through to the next method in the chain.

Pure computation functions (validate_mesh, select_placeholder_type,
create_placeholder) are separated from ComfyUI orchestration for
independent testability.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
from PIL import Image

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)
from src.photo_pipeline.models import (
    ObjectMeshResult,
    PhotoPipelineConfig,
)
from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helper functions (testable without ComfyUI)
# ---------------------------------------------------------------------------


def validate_mesh(mesh: trimesh.Trimesh) -> bool:
    """Validate that a mesh meets minimum quality requirements.

    A mesh is valid if and only if:
    - It has at least 4 faces
    - It has at least 4 vertices
    - The ratio of zero-area faces to total faces does not exceed 0.05 (5%)

    Parameters
    ----------
    mesh : trimesh.Trimesh
        The mesh to validate.

    Returns
    -------
    bool
        True if the mesh passes all validation checks.
    """
    if len(mesh.faces) < 4:
        return False
    if len(mesh.vertices) < 4:
        return False

    # Check zero-area faces
    areas = mesh.area_faces
    if len(areas) == 0:
        return False
    zero_area_ratio = np.count_nonzero(areas < 1e-10) / len(areas)
    if zero_area_ratio > 0.05:
        return False

    return True


def select_placeholder_type(
    width: int, height: int, area_px: int
) -> Literal["box", "cylinder", "sphere"]:
    """Select the placeholder primitive type based on bounding box aspect ratio.

    Selection rules:
    - Very small objects (area < 1000 px): sphere
    - Near-square (0.8 <= aspect <= 1.2): box
    - Tall/narrow (aspect < 0.5): cylinder
    - Wide/flat (aspect > 2.0): box
    - Default: box

    Parameters
    ----------
    width : int
        Width of the Object_PNG bounding box in pixels.
    height : int
        Height of the Object_PNG bounding box in pixels.
    area_px : int
        Total pixel area of the object mask.

    Returns
    -------
    Literal["box", "cylinder", "sphere"]
        The selected primitive type.
    """
    # Very small objects get a sphere
    if area_px < 1000:
        return "sphere"

    # Compute aspect ratio (width / height), guard against zero height
    if height <= 0:
        return "box"
    aspect = width / height

    # Near-square
    if 0.8 <= aspect <= 1.2:
        return "box"

    # Tall/narrow
    if aspect < 0.5:
        return "cylinder"

    # Wide/flat
    if aspect > 2.0:
        return "box"

    # Default
    return "box"


def extract_average_color(image_path: Path) -> tuple[int, int, int]:
    """Extract the average non-transparent color from an RGBA image.

    Parameters
    ----------
    image_path : Path
        Path to the RGBA Object_PNG.

    Returns
    -------
    tuple[int, int, int]
        Average RGB color of non-transparent pixels (0-255 per channel).
        Falls back to mid-gray (128, 128, 128) if no opaque pixels exist.
    """
    img = Image.open(image_path).convert("RGBA")
    data = np.array(img)

    # Mask for non-transparent pixels (alpha > 0)
    alpha = data[:, :, 3]
    opaque_mask = alpha > 0

    if not np.any(opaque_mask):
        return (128, 128, 128)

    # Compute mean of RGB channels for opaque pixels
    rgb = data[:, :, :3]
    avg_r = int(np.mean(rgb[:, :, 0][opaque_mask]))
    avg_g = int(np.mean(rgb[:, :, 1][opaque_mask]))
    avg_b = int(np.mean(rgb[:, :, 2][opaque_mask]))

    return (avg_r, avg_g, avg_b)


def create_placeholder(
    object_png_path: Path,
    bbox_width: int,
    bbox_height: int,
    area_px: int,
) -> trimesh.Trimesh:
    """Create a placeholder primitive mesh textured with the object's average color.

    Selects geometry (box, cylinder, or sphere) based on the bounding box
    aspect ratio, then applies a uniform color derived from the non-transparent
    pixels of the Object_PNG.

    Parameters
    ----------
    object_png_path : Path
        Path to the isolated RGBA Object_PNG.
    bbox_width : int
        Width of the object's bounding box in pixels.
    bbox_height : int
        Height of the object's bounding box in pixels.
    area_px : int
        Pixel area of the object mask.

    Returns
    -------
    trimesh.Trimesh
        A textured primitive mesh (box, cylinder, or sphere).
    """
    shape_type = select_placeholder_type(bbox_width, bbox_height, area_px)
    avg_color = extract_average_color(object_png_path)

    # Create unit-scale primitive (will be scaled at layout stage)
    if shape_type == "box":
        mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    elif shape_type == "cylinder":
        mesh = trimesh.creation.cylinder(radius=0.5, height=1.0, sections=16)
    else:  # sphere
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.5)

    # Apply uniform color as vertex colors (RGBA)
    color = np.array(
        [avg_color[0], avg_color[1], avg_color[2], 255], dtype=np.uint8
    )
    mesh.visual.vertex_colors = np.tile(color, (len(mesh.vertices), 1))

    return mesh


# ---------------------------------------------------------------------------
# ObjectGenerator class — orchestrates ComfyUI calls + fallback chain
# ---------------------------------------------------------------------------


class ObjectGenerator:
    """3D mesh generation with graceful fallback chain.

    Attempts neural 3D generation via ComfyUI in priority order:
    Hunyuan3D 2.0 → Unique3D → TripoSR → placeholder geometry.

    Each neural method is subject to a per-object timeout. On timeout,
    execution error, or mesh validation failure, the generator falls through
    to the next method.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for this session's object artifacts.
    """

    def __init__(self, client: ComfyUIClient, output_dir: Path) -> None:
        self.client = client
        self.output_dir = output_dir

    async def generate(
        self,
        object_png: Path,
        mask_id: str,
        config: PhotoPipelineConfig,
    ) -> ObjectMeshResult:
        """Generate a 3D mesh for a single segmented object.

        Attempts the full fallback chain. Records which method succeeded
        and the generation time.

        Parameters
        ----------
        object_png : Path
            Path to the isolated RGBA Object_PNG.
        mask_id : str
            Unique mask identifier for this object.
        config : PhotoPipelineConfig
            Pipeline configuration (contains object_gen_timeout_s).

        Returns
        -------
        ObjectMeshResult
            Result with GLB path, method used, timing, and mesh statistics.
        """
        obj_dir = self.output_dir / "objects"
        obj_dir.mkdir(parents=True, exist_ok=True)

        timeout_s = config.object_gen_timeout_s
        start_time = time.monotonic()

        # Try each neural generator in order
        methods: list[
            tuple[
                str,
                str,
            ]
        ] = [
            ("hunyuan3d", "hunyuan3d_gen"),
            ("unique3d", "unique3d_gen"),
            ("triposr", "triposr_gen"),
        ]

        for method_name, workflow_name in methods:
            mesh = await self._try_neural_generator(
                object_png=object_png,
                mask_id=mask_id,
                method_name=method_name,
                workflow_name=workflow_name,
                timeout_s=timeout_s,
                output_dir=obj_dir,
            )
            if mesh is not None:
                elapsed = time.monotonic() - start_time
                # Save mesh as GLB
                glb_path = obj_dir / f"{mask_id}.glb"
                mesh.export(str(glb_path), file_type="glb")
                return ObjectMeshResult(
                    mesh_path=glb_path,
                    method_used=method_name,  # type: ignore[arg-type]
                    generation_time_s=elapsed,
                    face_count=len(mesh.faces),
                    vertex_count=len(mesh.vertices),
                )

        # All neural methods failed — create placeholder
        logger.warning(
            "All neural generators failed for %s — using placeholder", mask_id
        )
        # Get bounding box info from the image
        img = Image.open(object_png)
        bbox_width, bbox_height = img.size
        img_data = np.array(img.convert("RGBA"))
        alpha = img_data[:, :, 3]
        area_px = int(np.count_nonzero(alpha > 0))
        img.close()

        mesh = create_placeholder(object_png, bbox_width, bbox_height, area_px)
        elapsed = time.monotonic() - start_time

        glb_path = obj_dir / f"{mask_id}.glb"
        mesh.export(str(glb_path), file_type="glb")

        return ObjectMeshResult(
            mesh_path=glb_path,
            method_used="placeholder",
            generation_time_s=elapsed,
            face_count=len(mesh.faces),
            vertex_count=len(mesh.vertices),
        )

    async def _try_neural_generator(
        self,
        object_png: Path,
        mask_id: str,
        method_name: str,
        workflow_name: str,
        timeout_s: int,
        output_dir: Path,
    ) -> trimesh.Trimesh | None:
        """Attempt a single neural 3D generation method.

        Submits the workflow to ComfyUI, waits for completion within the
        timeout, retrieves the GLB, loads it with trimesh, and validates.

        Parameters
        ----------
        object_png : Path
            Input object RGBA image.
        mask_id : str
            Object identifier.
        method_name : str
            Human-readable method name for logging.
        workflow_name : str
            Workflow template name to load.
        timeout_s : int
            Per-object timeout in seconds.
        output_dir : Path
            Directory for saving retrieved meshes.

        Returns
        -------
        trimesh.Trimesh | None
            Valid mesh if generation succeeded, None otherwise.
        """
        try:
            mesh = await asyncio.wait_for(
                self._submit_and_retrieve(
                    object_png, mask_id, workflow_name, output_dir
                ),
                timeout=timeout_s,
            )
            if mesh is not None and validate_mesh(mesh):
                logger.info(
                    "%s succeeded for %s: %d faces, %d vertices",
                    method_name,
                    mask_id,
                    len(mesh.faces),
                    len(mesh.vertices),
                )
                return mesh
            else:
                reason = "invalid mesh" if mesh is not None else "no output"
                logger.warning(
                    "%s produced %s for %s — trying next method",
                    method_name,
                    reason,
                    mask_id,
                )
                return None

        except asyncio.TimeoutError:
            logger.warning(
                "%s timed out (%ds) for %s — trying next method",
                method_name,
                timeout_s,
                mask_id,
            )
            return None

        except (ComfyUIError, ComfyUITimeoutError, OSError) as exc:
            logger.warning(
                "%s failed for %s (%s) — trying next method",
                method_name,
                mask_id,
                exc,
            )
            return None

        except Exception as exc:
            logger.warning(
                "%s unexpected error for %s (%s) — trying next method",
                method_name,
                mask_id,
                exc,
            )
            return None

    async def _submit_and_retrieve(
        self,
        object_png: Path,
        mask_id: str,
        workflow_name: str,
        output_dir: Path,
    ) -> trimesh.Trimesh | None:
        """Submit workflow, wait for completion, and load the output mesh.

        Parameters
        ----------
        object_png : Path
            Input image path.
        mask_id : str
            Object identifier for output naming.
        workflow_name : str
            Workflow template to load and submit.
        output_dir : Path
            Directory for saving the output GLB.

        Returns
        -------
        trimesh.Trimesh | None
            Loaded and parsed mesh, or None if retrieval/loading failed.
        """
        workflow = load_workflow(workflow_name)

        placeholders = {
            "INPUT_IMAGE_PATH": str(object_png).replace("\\", "/"),
            "MESH_OUTPUT_PREFIX": mask_id,
            "OUTPUT_DIR": str(output_dir).replace("\\", "/"),
        }

        prompt_id = await self.client.submit_workflow(
            workflow, placeholders=placeholders
        )
        await self.client.wait_for_completion(prompt_id)

        # Retrieve GLB from ComfyUI output
        temp_glb_path = await self.client.get_output_mesh(
            prompt_id=prompt_id,
            output_dir=output_dir,
            filename=f"{mask_id}_raw.glb",
        )

        # Load with trimesh
        loaded = trimesh.load(str(temp_glb_path), force="mesh")
        if isinstance(loaded, trimesh.Trimesh):
            return loaded
        elif isinstance(loaded, trimesh.Scene):
            # Combine scene geometries into a single mesh
            meshes = [
                g
                for g in loaded.geometry.values()
                if isinstance(g, trimesh.Trimesh)
            ]
            if meshes:
                combined = trimesh.util.concatenate(meshes)
                return combined
        return None
