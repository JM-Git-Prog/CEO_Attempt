"""Unified mesh generators — wrappers around existing V14 generators.

Adapts the proven V14 mesh generation infrastructure to accept unified
pipeline data models (ObjectCanon → MeshApproval) while maintaining all
existing quality parameters and validation rules.

Requirements: 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.stages.hunyuan3d_v2_generator import (
    Hunyuan3DV2Generator,
)
from src.photo_pipeline.stages.trellis2_generator import Trellis2Generator
from src.photo_pipeline.stages.placeholder_generator import (
    generate_placeholder,
    select_placeholder_type,
    _average_color,
)
from src.photo_pipeline.stages.trellis2_generator import Trellis2Generator
from src.unified_pipeline.models import MeshApproval, ObjectCanon

logger = logging.getLogger(__name__)


class MeshGenerationError(Exception):
    """Raised when mesh generation fails irrecoverably.

    Used by the fallback chain — catching this error triggers the next
    generator in the chain (Hunyuan3D → Trellis2 → placeholder).
    """

    def __init__(self, message: str, object_id: str = "", method: str = "") -> None:
        super().__init__(message)
        self.object_id = object_id
        self.method = method


# ─────────────────────────────────────────────────────────────────────────────
# UnifiedHunyuan3DGenerator — Task 4.1
# ─────────────────────────────────────────────────────────────────────────────


class UnifiedHunyuan3DGenerator:
    """Unified pipeline wrapper for Hunyuan3D 2.1 mesh generation.

    Wraps the existing `Hunyuan3DV2Generator` to accept `ObjectCanon`
    input and produce `MeshApproval` output, maintaining all proven
    generation parameters:
      - 50 KSampler diffusion steps
      - cfg=7.0 classifier-free guidance
      - octree_resolution=384 for maximum mesh detail
      - 180s stall timeout (hung inference detection, not quality cap)

    Validation rules (Req 10.6):
      - ≥100 faces
      - ≥50 vertices
      - Embedded texture data
      - No fused ground sheet (M8 rule)

    On failure, raises MeshGenerationError for the fallback chain to catch.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for generated mesh artifacts.
    """

    # Fixed generation parameters — proven quality settings
    STEPS: int = 50
    CFG: float = 7.0
    OCTREE_RESOLUTION: int = 384
    STALL_TIMEOUT_S: int = 180

    # Validation thresholds
    MIN_FACES: int = 100
    MIN_VERTICES: int = 50

    def __init__(self, client: ComfyUIClient, output_dir: Path) -> None:
        self._inner = Hunyuan3DV2Generator(client=client, output_dir=output_dir)
        self._client = client
        self._output_dir = output_dir

    async def generate(self, object_canon: ObjectCanon) -> MeshApproval:
        """Generate a textured 3D mesh from an approved Object_Canon.

        Delegates to the existing Hunyuan3D 2.1 generator with fixed
        quality parameters, then validates the output and maps it to
        a MeshApproval dataclass.

        Parameters
        ----------
        object_canon : ObjectCanon
            Approved appearance reference with image_path and object metadata.

        Returns
        -------
        MeshApproval
            Approved mesh record with path, statistics, and generation method.

        Raises
        ------
        MeshGenerationError
            If generation fails, times out, or the output mesh fails validation.
            The fallback chain catches this to try the next generator.
        """
        object_id = object_canon.object_id
        image_path = Path(object_canon.image_path)

        if not image_path.exists():
            raise MeshGenerationError(
                f"Object_Canon image not found: {image_path}",
                object_id=object_id,
                method="hunyuan3d_v2.1",
            )

        logger.info(
            "Hunyuan3D 2.1 generating mesh for object %s from %s",
            object_id,
            image_path,
        )

        start_time = time.monotonic()

        # Delegate to the existing V14 generator
        result = await self._inner.generate(
            object_png=image_path,
            mask_id=object_id,
            steps=self.STEPS,
            cfg=self.CFG,
            octree_resolution=self.OCTREE_RESOLUTION,
            stall_timeout_s=self.STALL_TIMEOUT_S,
        )

        # The inner generator returns None on failure (timeout, VRAM, ComfyUI error)
        if result is None:
            elapsed = time.monotonic() - start_time
            raise MeshGenerationError(
                f"Hunyuan3D 2.1 failed for object {object_id} after {elapsed:.1f}s",
                object_id=object_id,
                method="hunyuan3d_v2.1",
            )

        # Run unified validation (stricter than inner — includes texture + ground sheet)
        validation_error = self._validate_mesh(result.mesh_path)
        if validation_error:
            raise MeshGenerationError(
                f"Mesh validation failed for object {object_id}: {validation_error}",
                object_id=object_id,
                method="hunyuan3d_v2.1",
            )

        # Map to unified MeshApproval
        return MeshApproval(
            object_id=object_id,
            mesh_path=str(result.mesh_path),
            generation_method="hunyuan3d_v2.1",
            face_count=result.face_count,
            vertex_count=result.vertex_count,
            approved=False,  # Awaits user approval gate
            rejection_reason="",
            retry_count=0,
            is_placeholder=False,
        )

    def _validate_mesh(self, mesh_path: Path) -> str | None:
        """Validate mesh meets unified pipeline requirements.

        Checks (Req 10.6):
          - ≥100 faces
          - ≥50 vertices
          - Embedded texture data present
          - No fused ground sheet (M8 rule: flat geometry at y≈0)

        Parameters
        ----------
        mesh_path : Path
            Path to the generated GLB file.

        Returns
        -------
        str | None
            None if validation passes, error description string if it fails.
        """
        if not mesh_path.exists():
            return f"Mesh file does not exist: {mesh_path}"

        try:
            loaded = trimesh.load(str(mesh_path), force="scene", process=False)
        except Exception as exc:
            return f"Failed to load mesh: {exc}"

        meshes: list[trimesh.Trimesh] = []
        has_texture = False

        if isinstance(loaded, trimesh.Scene):
            for geom in loaded.geometry.values():
                if isinstance(geom, trimesh.Trimesh):
                    meshes.append(geom)
        elif isinstance(loaded, trimesh.Trimesh):
            meshes.append(loaded)
        else:
            return f"Loaded object is not a valid mesh type: {type(loaded)}"

        if not meshes:
            return "Scene contains no mesh geometry"

        total_faces = sum(len(m.faces) for m in meshes)
        total_verts = sum(len(m.vertices) for m in meshes)

        # Check minimum geometry thresholds
        if total_faces < self.MIN_FACES:
            return f"Insufficient faces: {total_faces} (need ≥{self.MIN_FACES})"

        if total_verts < self.MIN_VERTICES:
            return f"Insufficient vertices: {total_verts} (need ≥{self.MIN_VERTICES})"

        # Check for embedded texture
        for mesh in meshes:
            visual = mesh.visual
            if hasattr(visual, "material") and visual.material is not None:
                mat = visual.material
                if (
                    hasattr(mat, "baseColorTexture")
                    and mat.baseColorTexture is not None
                ) or (
                    hasattr(mat, "image") and mat.image is not None
                ):
                    has_texture = True
                    break

        if not has_texture:
            return "No embedded texture data found"

        # Check for ground sheet (M8 rule)
        ground_sheet = self._detect_ground_sheet(meshes)
        if ground_sheet:
            return "Fused ground sheet detected (M8 rule violation)"

        return None

    def _detect_ground_sheet(self, meshes: list[trimesh.Trimesh]) -> bool:
        """Detect a fused ground sheet — flat geometry near y=0.

        A ground sheet is identified when a significant portion of vertices
        lie in a thin horizontal band at the mesh's minimum Y coordinate,
        forming a flat plane that doesn't belong to the intended object.

        Parameters
        ----------
        meshes : list[trimesh.Trimesh]
            List of mesh geometries to check.

        Returns
        -------
        bool
            True if a ground sheet pattern is detected.
        """
        for mesh in meshes:
            if len(mesh.vertices) < 20:
                continue

            verts = mesh.vertices
            y_coords = verts[:, 1]
            y_min = float(y_coords.min())
            y_range = float(y_coords.max() - y_min)

            if y_range < 1e-6:
                # Entire mesh is flat — likely a ground sheet
                continue

            # Check if >30% of vertices are within 1% of the Y range
            # at the bottom — indicates a flat ground plane
            threshold = y_min + y_range * 0.01
            bottom_verts = np.sum(y_coords <= threshold)
            bottom_ratio = bottom_verts / len(verts)

            if bottom_ratio > 0.30:
                # Check that bottom vertices form a roughly flat plane
                bottom_y_values = y_coords[y_coords <= threshold]
                y_spread = float(bottom_y_values.max() - bottom_y_values.min())

                if y_spread < y_range * 0.005:
                    logger.debug(
                        "Ground sheet detected: %.1f%% verts at y≈%.4f "
                        "(spread=%.6f, range=%.4f)",
                        bottom_ratio * 100,
                        y_min,
                        y_spread,
                        y_range,
                    )
                    return True

        return False


# ─────────────────────────────────────────────────────────────────────────────
# UnifiedPlaceholderGenerator — Task 4.3
# ─────────────────────────────────────────────────────────────────────────────


class UnifiedPlaceholderGenerator:
    """Unified pipeline wrapper for placeholder primitive generation.

    Wraps the existing `placeholder_generator.generate_placeholder()` to
    accept `ObjectCanon` input and produce `MeshApproval` output.

    Placeholders auto-approve (Req 11.5 — no shape approval needed).

    Parameters
    ----------
    output_dir : Path | None
        Output directory for generated GLBs. If None, writes alongside
        the Object_Canon image.
    """

    # Default dimensions when Plan dimensions aren't available yet
    DEFAULT_DIMENSIONS_M: tuple[float, float, float] = (0.3, 0.3, 0.3)

    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir

    def generate(
        self,
        object_canon: ObjectCanon,
        dimensions_m: tuple[float, float, float] | None = None,
    ) -> MeshApproval:
        """Generate a placeholder primitive from an Object_Canon.

        Parameters
        ----------
        object_canon : ObjectCanon
            Approved appearance reference with image_path.
        dimensions_m : tuple[float, float, float] | None
            Target dimensions from Plan. If None, uses defaults.

        Returns
        -------
        MeshApproval
            Auto-approved placeholder result.
        """
        from PIL import Image

        object_id = object_canon.object_id
        image_path = Path(object_canon.image_path)

        if not image_path.exists():
            return MeshApproval(
                object_id=object_id,
                mesh_path="",
                generation_method="placeholder",
                face_count=0,
                vertex_count=0,
                approved=False,
                rejection_reason=f"Image not found: {image_path}",
                retry_count=0,
                is_placeholder=True,
            )

        dims = dimensions_m or self.DEFAULT_DIMENSIONS_M

        try:
            # Use the existing V14 placeholder generator
            glb_path = generate_placeholder(image_path, dims)

            # If output_dir specified, move to designated location
            if self._output_dir is not None:
                self._output_dir.mkdir(parents=True, exist_ok=True)
                dest = self._output_dir / glb_path.name
                glb_path.rename(dest)
                glb_path = dest

            # Get mesh stats
            loaded = trimesh.load(str(glb_path), force="mesh", process=False)
            face_count = len(loaded.faces) if isinstance(loaded, trimesh.Trimesh) else 0
            vertex_count = len(loaded.vertices) if isinstance(loaded, trimesh.Trimesh) else 0

            return MeshApproval(
                object_id=object_id,
                mesh_path=str(glb_path),
                generation_method="placeholder",
                face_count=face_count,
                vertex_count=vertex_count,
                approved=True,  # Auto-approve (Req 11.5)
                rejection_reason="",
                retry_count=0,
                is_placeholder=True,
            )

        except Exception as exc:
            logger.warning(
                "Placeholder generation failed for %s: %s", object_id, exc
            )
            return MeshApproval(
                object_id=object_id,
                mesh_path="",
                generation_method="placeholder",
                face_count=0,
                vertex_count=0,
                approved=False,
                rejection_reason=f"Generation failed: {exc}",
                retry_count=0,
                is_placeholder=True,
            )



class UnifiedTrellis2Generator:
    """Unified pipeline wrapper for Trellis2 fallback mesh generation.

    Wraps the existing `Trellis2Generator` to accept `ObjectCanon`
    input and produce `MeshApproval` output. Used as fallback when
    Hunyuan3D fails or stalls beyond 180s.

    Maintains proven Trellis2 generation parameters:
      - 18 voxel generation steps
      - 12000 target triangles after simplification
      - GLB output with embedded textures

    Workflow chain:
      Trellis2LoadModel → Trellis2PreProcessImage →
      Trellis2MeshWithVoxelGenerator(steps=18) →
      Trellis2SimplifyMesh(triangles=12000) → Trellis2ExportMesh(GLB)

    On failure, raises MeshGenerationError for the fallback chain
    to catch and proceed to placeholder generation.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for generated mesh artifacts.

    Requirements: 10.4
    """

    # Fixed generation parameters — proven Trellis2 settings
    STEPS: int = 18
    TARGET_TRIANGLES: int = 12000

    # Validation thresholds (same as Hunyuan3D for consistency)
    MIN_FACES: int = 100
    MIN_VERTICES: int = 50

    def __init__(self, client: ComfyUIClient, output_dir: Path) -> None:
        self._inner = Trellis2Generator(client=client, output_dir=output_dir)
        self._client = client
        self._output_dir = output_dir

    async def generate(self, object_canon: ObjectCanon) -> MeshApproval:
        """Generate a textured 3D mesh from an approved Object_Canon via Trellis2.

        Used as fallback when Hunyuan3D 2.1 fails or stalls. Delegates to
        the existing Trellis2 generator with fixed quality parameters, then
        validates the output and maps it to a MeshApproval dataclass.

        Parameters
        ----------
        object_canon : ObjectCanon
            Approved appearance reference with image_path and object metadata.

        Returns
        -------
        MeshApproval
            Mesh record with path, statistics, and generation method.

        Raises
        ------
        MeshGenerationError
            If generation fails or the output mesh fails validation.
            The fallback chain catches this to try placeholder generation.
        """
        object_id = object_canon.object_id
        image_path = Path(object_canon.image_path)

        if not image_path.exists():
            raise MeshGenerationError(
                f"Object_Canon image not found: {image_path}",
                object_id=object_id,
                method="trellis2",
            )

        logger.info(
            "Trellis2 fallback generating mesh for object %s from %s",
            object_id,
            image_path,
        )

        start_time = time.monotonic()

        # Delegate to the existing V14 Trellis2 generator
        result = await self._inner.generate(
            object_png=image_path,
            mask_id=object_id,
            steps=self.STEPS,
            target_triangles=self.TARGET_TRIANGLES,
        )

        # The inner generator returns None on failure (timeout, VRAM, ComfyUI error)
        if result is None:
            elapsed = time.monotonic() - start_time
            raise MeshGenerationError(
                f"Trellis2 failed for object {object_id} after {elapsed:.1f}s",
                object_id=object_id,
                method="trellis2",
            )

        # Run unified validation
        validation_error = self._validate_mesh(result.mesh_path)
        if validation_error:
            raise MeshGenerationError(
                f"Trellis2 mesh validation failed for object {object_id}: {validation_error}",
                object_id=object_id,
                method="trellis2",
            )

        # Map to unified MeshApproval
        return MeshApproval(
            object_id=object_id,
            mesh_path=str(result.mesh_path),
            generation_method="trellis2",
            face_count=result.face_count,
            vertex_count=result.vertex_count,
            approved=False,  # Awaits user approval gate
            rejection_reason="",
            retry_count=0,
            is_placeholder=False,
        )

    def _validate_mesh(self, mesh_path: Path) -> str | None:
        """Validate mesh meets unified pipeline requirements.

        Checks (Req 10.6):
          - ≥100 faces
          - ≥50 vertices
          - Embedded texture data present (Trellis2 produces GLB with textures)
          - No fused ground sheet (M8 rule)

        Parameters
        ----------
        mesh_path : Path
            Path to the generated GLB file.

        Returns
        -------
        str | None
            None if validation passes, error description string if it fails.
        """
        if not mesh_path.exists():
            return f"Mesh file does not exist: {mesh_path}"

        try:
            loaded = trimesh.load(str(mesh_path), force="scene", process=False)
        except Exception as exc:
            return f"Failed to load mesh: {exc}"

        meshes: list[trimesh.Trimesh] = []
        has_texture = False

        if isinstance(loaded, trimesh.Scene):
            for geom in loaded.geometry.values():
                if isinstance(geom, trimesh.Trimesh):
                    meshes.append(geom)
        elif isinstance(loaded, trimesh.Trimesh):
            meshes.append(loaded)
        else:
            return f"Loaded object is not a valid mesh type: {type(loaded)}"

        if not meshes:
            return "Scene contains no mesh geometry"

        total_faces = sum(len(m.faces) for m in meshes)
        total_verts = sum(len(m.vertices) for m in meshes)

        # Check minimum geometry thresholds
        if total_faces < self.MIN_FACES:
            return f"Insufficient faces: {total_faces} (need ≥{self.MIN_FACES})"

        if total_verts < self.MIN_VERTICES:
            return f"Insufficient vertices: {total_verts} (need ≥{self.MIN_VERTICES})"

        # Check for embedded texture (Trellis2 produces textured GLBs)
        for mesh in meshes:
            visual = mesh.visual
            if hasattr(visual, "material") and visual.material is not None:
                mat = visual.material
                if (
                    hasattr(mat, "baseColorTexture")
                    and mat.baseColorTexture is not None
                ) or (
                    hasattr(mat, "image") and mat.image is not None
                ):
                    has_texture = True
                    break

        if not has_texture:
            return "No embedded texture data found"

        # Check for ground sheet (M8 rule)
        ground_sheet = self._detect_ground_sheet(meshes)
        if ground_sheet:
            return "Fused ground sheet detected (M8 rule violation)"

        return None

    def _detect_ground_sheet(self, meshes: list[trimesh.Trimesh]) -> bool:
        """Detect a fused ground sheet — flat geometry near y=0.

        A ground sheet is identified when a significant portion of vertices
        lie in a thin horizontal band at the mesh's minimum Y coordinate,
        forming a flat plane that doesn't belong to the intended object.

        Parameters
        ----------
        meshes : list[trimesh.Trimesh]
            List of mesh geometries to check.

        Returns
        -------
        bool
            True if a ground sheet pattern is detected.
        """
        import numpy as np

        for mesh in meshes:
            if len(mesh.vertices) < 20:
                continue

            verts = mesh.vertices
            y_coords = verts[:, 1]
            y_min = float(y_coords.min())
            y_range = float(y_coords.max() - y_min)

            if y_range < 1e-6:
                # Entire mesh is flat — likely a ground sheet
                continue

            # Check if >30% of vertices are within 1% of the Y range
            # at the bottom — indicates a flat ground plane
            threshold = y_min + y_range * 0.01
            bottom_verts = np.sum(y_coords <= threshold)
            bottom_ratio = bottom_verts / len(verts)

            if bottom_ratio > 0.30:
                # Check that bottom vertices form a roughly flat plane
                bottom_y_values = y_coords[y_coords <= threshold]
                y_spread = float(bottom_y_values.max() - bottom_y_values.min())

                if y_spread < y_range * 0.005:
                    logger.debug(
                        "Ground sheet detected: %.1f%% verts at y≈%.4f "
                        "(spread=%.6f, range=%.4f)",
                        bottom_ratio * 100,
                        y_min,
                        y_spread,
                        y_range,
                    )
                    return True

        return False
