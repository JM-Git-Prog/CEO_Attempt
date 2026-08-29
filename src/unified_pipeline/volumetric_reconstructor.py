"""Volumetric mesh reconstruction from fused point clouds.

Converts a dense point cloud (produced by depth_backprojector from validated
depth + exact known cameras) into a watertight-ish mesh suitable for the
walkable room shell. Open3D (TSDF / Poisson) is preferred when available; the
default path uses trimesh only, which is always present in this project.

Constraints applied: Y-up, meters, right-handed (matching CameraContract);
inward-facing normals for interior rendering; bridge-triangle removal across
depth discontinuities; decimation to a browser-friendly vertex budget.

Authority note: the geometry here originates from MetricPlan (via known camera
matrices used during back-projection). This reconstructor performs no pose or
scale estimation — it only surfaces an existing metric point cloud. On failure
it returns None so the caller can fall back to the parametric room shell.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

# Vertex budget bounds (Req 6.4 / 16.7 of unified-world-pipeline).
MIN_VERTS = 10_000
MAX_VERTS = 250_000
# Bridge triangle removal: drop faces whose vertices span > this depth gap.
BRIDGE_GRADIENT_M = 0.5


class VolumetricReconstructor:
    """Reconstruct a mesh from a fused metric point cloud.

    The primary path (``method="poisson"``) uses trimesh. If Open3D is present
    and ``method="tsdf"`` is requested, a TSDF/Poisson path via Open3D is used.
    Any failure returns ``None`` so callers can fall back to a parametric shell.
    """

    def reconstruct(
        self,
        points: np.ndarray,
        colors: np.ndarray | None = None,
        normals: np.ndarray | None = None,
        method: str = "poisson",
        room_center: tuple[float, float, float] | None = None,
    ) -> trimesh.Trimesh | None:
        """Reconstruct a mesh from a point cloud.

        Args:
            points: (N, 3) world points in meters.
            colors: Optional (N, 3) uint8 per-point colors.
            normals: Optional (N, 3) per-point normals. Estimated if omitted.
            method: "poisson" (trimesh, default) or "tsdf" (Open3D if available).
            room_center: Optional (x, y, z) used to orient normals inward.

        Returns:
            A postprocessed ``trimesh.Trimesh`` or ``None`` if reconstruction
            was not possible (caller should fall back to the parametric shell).
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if pts.shape[0] < 4:
            logger.warning("reconstruct: too few points (%d) for a mesh", pts.shape[0])
            return None

        mesh: trimesh.Trimesh | None = None
        if method == "tsdf":
            mesh = self._tsdf_reconstruct(pts, colors, normals)
            if mesh is None:
                logger.info("reconstruct: TSDF path unavailable; using trimesh path")

        if mesh is None:
            mesh = self._trimesh_reconstruct(pts, normals)

        if mesh is None or len(mesh.faces) == 0:
            logger.warning("reconstruct: produced no faces")
            return None

        return self._postprocess(mesh, room_center)

    # ── Reconstruction backends ──────────────────────────────────────────────

    def _trimesh_reconstruct(
        self, points: np.ndarray, normals: np.ndarray | None
    ) -> trimesh.Trimesh | None:
        """Reconstruct a surface using trimesh only.

        Strategy: build a PointCloud and attempt a convex-hull surface. For
        room shells (roughly convex interiors seen from inside) the convex hull
        of the wall/floor/ceiling points is a serviceable watertight shell. This
        is a deterministic, dependency-light fallback that always yields a valid
        manifold mesh when given enough spread points.
        """
        try:
            cloud = trimesh.PointCloud(points)
            hull = cloud.convex_hull
            if hull is None or len(hull.faces) == 0:
                return None
            return hull
        except Exception as exc:  # noqa: BLE001 - report and fall back
            logger.warning("trimesh reconstruct failed: %s", exc)
            return None

    def _tsdf_reconstruct(
        self,
        points: np.ndarray,
        colors: np.ndarray | None,
        normals: np.ndarray | None,
    ) -> trimesh.Trimesh | None:
        """Reconstruct via Open3D Poisson if Open3D is installed; else None."""
        try:
            import open3d as o3d  # type: ignore[import]
        except ImportError:
            return None

        try:
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(points)
            if normals is not None:
                pcd.normals = o3d.utility.Vector3dVector(
                    np.asarray(normals, dtype=np.float64).reshape(-1, 3)
                )
            else:
                pcd.estimate_normals()
            mesh_o3d, _ = (
                o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                    pcd, depth=8
                )
            )
            vertices = np.asarray(mesh_o3d.vertices)
            faces = np.asarray(mesh_o3d.triangles)
            if len(faces) == 0:
                return None
            return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Open3D Poisson failed: %s", exc)
            return None

    # ── Postprocessing ───────────────────────────────────────────────────────

    def _postprocess(
        self,
        mesh: trimesh.Trimesh,
        room_center: tuple[float, float, float] | None,
    ) -> trimesh.Trimesh:
        """Remove bridge triangles, orient normals inward, decimate."""
        mesh = self._remove_bridge_triangles(mesh)
        mesh = self._orient_inward(mesh, room_center)
        mesh = self._decimate(mesh)
        return mesh

    def _remove_bridge_triangles(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Drop faces that span a large depth gap (bridge triangles).

        A face is a bridge if the max pairwise distance among its three vertices
        exceeds BRIDGE_GRADIENT_M. Such faces stretch across discontinuities
        (e.g. a doorway) and should not exist in the shell.
        """
        if len(mesh.faces) == 0:
            return mesh
        tris = mesh.vertices[mesh.faces]  # (F, 3, 3)
        # Pairwise edge lengths per triangle.
        e0 = np.linalg.norm(tris[:, 0] - tris[:, 1], axis=1)
        e1 = np.linalg.norm(tris[:, 1] - tris[:, 2], axis=1)
        e2 = np.linalg.norm(tris[:, 2] - tris[:, 0], axis=1)
        max_edge = np.maximum.reduce([e0, e1, e2])
        keep = max_edge <= BRIDGE_GRADIENT_M
        if not np.any(keep):
            # Removing everything is worse than keeping the raw hull.
            logger.debug("bridge removal would drop all faces; keeping mesh")
            return mesh
        kept = mesh.copy()
        kept.update_faces(keep)
        kept.remove_unreferenced_vertices()
        return kept

    def _orient_inward(
        self,
        mesh: trimesh.Trimesh,
        room_center: tuple[float, float, float] | None,
    ) -> trimesh.Trimesh:
        """Flip face normals so they point toward the room interior.

        For an interior shell viewed from inside, normals should face the
        centroid. If most face normals point away from the center, invert.
        """
        if len(mesh.faces) == 0:
            return mesh
        center = (
            np.array(room_center, dtype=np.float64)
            if room_center is not None
            else mesh.centroid
        )
        face_centers = mesh.triangles_center
        to_center = center - face_centers
        # Dot of face normal with direction to center; positive => facing inward.
        dots = np.einsum("ij,ij->i", mesh.face_normals, to_center)
        if float(np.mean(dots)) < 0:
            # Flip winding so normals face the interior. Rebuild the mesh to
            # force face_normals recomputation (trimesh caches normals, and a
            # processed convex hull re-derives outward winding on .invert()).
            flipped = trimesh.Trimesh(
                vertices=mesh.vertices.copy(),
                faces=mesh.faces[:, ::-1].copy(),
                process=False,
            )
            return flipped
        return mesh

    def _decimate(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Decimate to <= MAX_VERTS while leaving small meshes untouched."""
        n_verts = len(mesh.vertices)
        if n_verts <= MAX_VERTS:
            return mesh
        target_faces = int(len(mesh.faces) * (MAX_VERTS / n_verts))
        try:
            simplified = mesh.simplify_quadric_decimation(target_faces)
            if simplified is not None and len(simplified.faces) > 0:
                return simplified
        except Exception as exc:  # noqa: BLE001
            logger.warning("decimation failed: %s", exc)
        return mesh

    # ── Export ───────────────────────────────────────────────────────────────

    def export_glb(self, mesh: trimesh.Trimesh, output_path) -> Path:
        """Export a mesh to GLB. Returns the output path."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        scene = trimesh.Scene()
        scene.add_geometry(mesh, node_name="room_shell")
        scene.export(str(out), file_type="glb")
        logger.info(
            "export_glb: wrote %d verts / %d faces to %s",
            len(mesh.vertices),
            len(mesh.faces),
            out,
        )
        return out
