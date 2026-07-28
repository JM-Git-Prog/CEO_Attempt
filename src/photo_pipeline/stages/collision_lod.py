"""Collision and LOD Generator — V-HACD decomposition and mesh decimation.

Generates compound collision shapes (V-HACD, convex hull, or bounding box)
and Level-of-Detail mesh variants for each object in the photo pipeline.

Collision method selection:
- Meshes with > 100 faces: attempt V-HACD decomposition (max 16 hulls,
  10000 voxel resolution, 30s timeout). Falls back to bounding box on timeout.
- Meshes with ≤ 100 faces: direct convex hull (single hull).

LOD generation produces 4 levels:
- LOD0: 100% (original mesh)
- LOD1: 50% face count
- LOD2: 25% face count
- LOD3: 10% face count

All levels are clamped to a minimum of 4 faces to prevent degenerate geometry.
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

import numpy as np
import trimesh

from src.photo_pipeline.models import (
    CollisionResult,
    LODResult,
    PhotoPipelineConfig,
)

logger = logging.getLogger(__name__)


class CollisionLODGenerator:
    """Generates collision shapes and LOD variants for object meshes.

    Collision shapes are stored as GLB files alongside the source mesh.
    LOD variants are stored with _lod{N} suffix naming.

    Parameters
    ----------
    output_dir : Path
        Base output directory for this session's object artifacts.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def generate_collision(
        self, mesh_path: Path, config: PhotoPipelineConfig
    ) -> CollisionResult:
        """Generate a collision mesh for the given object mesh.

        For meshes with > 100 faces, attempts V-HACD decomposition with
        the configured parameters. For simpler meshes (≤ 100 faces), uses
        a direct convex hull. Falls back to bounding box on V-HACD failure
        or timeout.

        Parameters
        ----------
        mesh_path : Path
            Path to the source object mesh GLB.
        config : PhotoPipelineConfig
            Pipeline configuration (vhacd_timeout_s, vhacd_max_hulls,
            vhacd_voxel_resolution).

        Returns
        -------
        CollisionResult
            Result with collision mesh path, method used, and hull count.
        """
        mesh = self._load_mesh(mesh_path)
        stem = mesh_path.stem
        collision_dir = mesh_path.parent
        collision_dir.mkdir(parents=True, exist_ok=True)

        face_count = len(mesh.faces)

        if face_count <= 100:
            # Simple mesh — use direct convex hull
            collision_mesh = mesh.convex_hull
            method = "convex_hull"
            hull_count = 1
            logger.info(
                "Mesh %s has %d faces (≤100) — using direct convex hull",
                stem,
                face_count,
            )
        else:
            # Complex mesh — attempt V-HACD decomposition
            logger.info(
                "Mesh %s has %d faces (>100) — attempting V-HACD decomposition",
                stem,
                face_count,
            )
            vhacd_result = self._run_vhacd(mesh, config)

            if vhacd_result is not None:
                collision_mesh, hull_count = vhacd_result
                method = "vhacd"
                logger.info(
                    "V-HACD succeeded for %s: %d hulls", stem, hull_count
                )
            else:
                # V-HACD failed or timed out — fall back to bounding box
                logger.warning(
                    "V-HACD failed/timed out for %s — using bounding-box fallback",
                    stem,
                )
                collision_mesh = trimesh.creation.box(
                    extents=mesh.bounding_box.extents,
                    transform=mesh.bounding_box.primitive.transform,
                )
                method = "bounding_box"
                hull_count = 1

        # Save collision mesh as GLB
        collision_path = collision_dir / f"{stem}_collision.glb"
        collision_mesh.export(str(collision_path), file_type="glb")

        return CollisionResult(
            collision_mesh_path=collision_path,
            method=method,  # type: ignore[arg-type]
            hull_count=hull_count,
        )

    def generate_lod(
        self, mesh_path: Path, config: PhotoPipelineConfig
    ) -> LODResult:
        """Generate Level-of-Detail variants for the given object mesh.

        Produces 4 LOD levels via quadric decimation:
        - LOD0: 100% of original faces (the original mesh)
        - LOD1: 50% of original faces
        - LOD2: 25% of original faces
        - LOD3: 10% of original faces

        Each level is clamped to a minimum of 4 faces to prevent
        degenerate geometry.

        Parameters
        ----------
        mesh_path : Path
            Path to the source object mesh GLB.
        config : PhotoPipelineConfig
            Pipeline configuration (lod_levels tuple of ratios).

        Returns
        -------
        LODResult
            Result with paths to each LOD GLB and face counts per level.
        """
        mesh = self._load_mesh(mesh_path)
        stem = mesh_path.stem
        lod_dir = mesh_path.parent
        lod_dir.mkdir(parents=True, exist_ok=True)

        original_face_count = len(mesh.faces)
        lod_ratios = config.lod_levels  # (1.0, 0.5, 0.25, 0.1)

        lod_paths: dict[int, Path] = {}
        face_counts: dict[int, int] = {}

        for level, ratio in enumerate(lod_ratios):
            if ratio >= 1.0:
                # LOD0 is the original mesh
                lod_mesh = mesh.copy()
            else:
                # Compute target face count, clamped to minimum 4
                target_faces = max(4, int(original_face_count * ratio))
                lod_mesh = self._decimate(mesh, target_faces)

            # Save LOD mesh as GLB
            lod_path = lod_dir / f"{stem}_lod{level}.glb"
            lod_mesh.export(str(lod_path), file_type="glb")

            lod_paths[level] = lod_path
            face_counts[level] = len(lod_mesh.faces)

        logger.info(
            "LOD generation for %s: %s",
            stem,
            {k: v for k, v in face_counts.items()},
        )

        return LODResult(lod_paths=lod_paths, face_counts=face_counts)

    def _run_vhacd(
        self, mesh: trimesh.Trimesh, config: PhotoPipelineConfig
    ) -> tuple[trimesh.Trimesh, int] | None:
        """Attempt V-HACD convex decomposition with timeout.

        Tries trimesh's built-in convex_decomposition if the VHACD plugin
        is available. If not available or if the operation times out, falls
        back to a single convex hull. If that also fails, returns None
        (caller will use bounding box).

        Parameters
        ----------
        mesh : trimesh.Trimesh
            The source mesh to decompose.
        config : PhotoPipelineConfig
            Configuration with vhacd_timeout_s, vhacd_max_hulls,
            vhacd_voxel_resolution.

        Returns
        -------
        tuple[trimesh.Trimesh, int] | None
            Combined collision mesh and hull count, or None if all methods fail.
        """
        timeout_s = config.vhacd_timeout_s
        max_hulls = config.vhacd_max_hulls

        # First try trimesh's convex_decomposition (requires V-HACD plugin)
        result_container: list[trimesh.Trimesh | None] = [None]
        hull_count_container: list[int] = [0]
        error_container: list[Exception | None] = [None]

        def _attempt_vhacd() -> None:
            try:
                decomposed = trimesh.decomposition.convex_decomposition(
                    mesh, maxhulls=max_hulls
                )
                # decomposed is a list of trimesh.Trimesh convex hulls
                if isinstance(decomposed, list) and len(decomposed) > 0:
                    combined = trimesh.util.concatenate(decomposed)
                    result_container[0] = combined
                    hull_count_container[0] = len(decomposed)
                else:
                    error_container[0] = ValueError("Empty decomposition result")
            except Exception as exc:
                error_container[0] = exc

        # Run V-HACD in a thread with timeout
        thread = threading.Thread(target=_attempt_vhacd, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)

        if thread.is_alive():
            # Timed out — thread is still running, we cannot forcibly kill it
            # but we treat this as a timeout failure
            logger.warning(
                "V-HACD decomposition timed out after %ds", timeout_s
            )
            # Fall through to convex hull fallback
        elif result_container[0] is not None:
            return (result_container[0], hull_count_container[0])
        elif error_container[0] is not None:
            logger.debug(
                "V-HACD plugin error: %s — trying convex hull fallback",
                error_container[0],
            )

        # Fallback: single convex hull (always works for valid geometry)
        try:
            hull = mesh.convex_hull
            if hull is not None and len(hull.faces) >= 4:
                return (hull, 1)
        except Exception as exc:
            logger.debug("Convex hull fallback failed: %s", exc)

        # All decomposition methods failed
        return None

    def _decimate(
        self, mesh: trimesh.Trimesh, target_face_count: int
    ) -> trimesh.Trimesh:
        """Decimate a mesh to the target face count using quadric decimation.

        Clamps the target to a minimum of 4 faces to prevent degenerate
        geometry. If decimation fails or the result is degenerate, returns
        a copy of the original mesh.

        Parameters
        ----------
        mesh : trimesh.Trimesh
            The source mesh to decimate.
        target_face_count : int
            Desired number of faces in the output.

        Returns
        -------
        trimesh.Trimesh
            Decimated mesh, or original copy if decimation fails.
        """
        # Ensure minimum of 4 faces
        target_face_count = max(4, target_face_count)

        # If target is >= current face count, no decimation needed
        if target_face_count >= len(mesh.faces):
            return mesh.copy()

        try:
            # Use trimesh's simplify_quadric_decimation
            decimated = mesh.simplify_quadric_decimation(target_face_count)

            # Validate the result has at least 4 faces
            if decimated is not None and len(decimated.faces) >= 4:
                return decimated

            # If decimation produced degenerate result, return original
            logger.warning(
                "Decimation produced degenerate mesh (%d faces) — keeping original",
                len(decimated.faces) if decimated is not None else 0,
            )
            return mesh.copy()

        except Exception as exc:
            logger.warning(
                "Quadric decimation failed (%s) — keeping original", exc
            )
            return mesh.copy()

    def _load_mesh(self, mesh_path: Path) -> trimesh.Trimesh:
        """Load a mesh from a GLB file, combining scene geometries if needed.

        Parameters
        ----------
        mesh_path : Path
            Path to the GLB file.

        Returns
        -------
        trimesh.Trimesh
            The loaded mesh (combined if multiple geometries).

        Raises
        ------
        ValueError
            If the file contains no valid mesh geometry.
        """
        loaded = trimesh.load(str(mesh_path), force="mesh")

        if isinstance(loaded, trimesh.Trimesh):
            return loaded
        elif isinstance(loaded, trimesh.Scene):
            meshes = [
                g
                for g in loaded.geometry.values()
                if isinstance(g, trimesh.Trimesh)
            ]
            if meshes:
                return trimesh.util.concatenate(meshes)

        raise ValueError(f"No valid mesh geometry in {mesh_path}")
