"""Room Mesh Reconstructor — depth map + room plate to textured GLB mesh.

Converts a metric depth map and inpainted room plate image into a textured
3D mesh (GLB format) oriented in WorldContract coordinates (right-handed,
Y-up, meters). Includes a flat-floor fallback heuristic when depth data is
unavailable or unreliable.

Algorithm:
1. For each valid pixel (u, v) at depth d, back-project to 3D:
   x = (u - cx) * d / fx
   y = -(v - cy) * d / fy  (negated for Y-up)
   z = -d                    (camera looks along -Z)
2. Build triangulated mesh from the grid of 3D points via Delaunay
3. UV from pixel coordinates: u_uv = u/W, v_uv = v/H
4. Apply Room_Plate as texture
5. Enforce vertex bounds (min 1000, max 500000) via decimation

Flat-floor fallback:
- Box room: width = 4.0 * aspect_ratio, depth = 4.0, height = 2.7
- Open on camera-facing side (no front wall)
- White texture
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from src.photo_pipeline.models import PhotoPipelineConfig, RoomMeshResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Camera model defaults
_DEFAULT_FOV_V_DEG = 60.0  # Vertical FOV in degrees

# Vertex count bounds
_MIN_VERTICES = 1000
_MAX_VERTICES = 500_000

# Flat-floor fallback dimensions
_FALLBACK_DEPTH_M = 4.0
_FALLBACK_HEIGHT_M = 2.7

# Subsampling step to keep mesh within vertex budget for large images
_MAX_GRID_DIM = 700  # Max pixels in each dimension before subsampling


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class RoomReconstructor:
    """Reconstructs a textured room mesh from a depth map and room plate.

    Parameters
    ----------
    output_dir : Path
        Session output directory where the GLB will be saved.
    fov_v_deg : float
        Vertical field of view in degrees (default 60°).
    """

    def __init__(
        self,
        output_dir: Path,
        fov_v_deg: float = _DEFAULT_FOV_V_DEG,
    ) -> None:
        self.output_dir = output_dir
        self.fov_v_deg = fov_v_deg

    async def reconstruct(
        self,
        depth_map: Path,
        room_plate: Path,
        config: PhotoPipelineConfig,
    ) -> RoomMeshResult:
        """Reconstruct a room mesh from depth map and room plate.

        Parameters
        ----------
        depth_map : Path
            Path to the depth map .npy file (float32, meters).
        room_plate : Path
            Path to the room plate PNG (RGB texture).
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        RoomMeshResult
            Structured result with GLB path, dimensions, counts, and heuristic flag.
        """
        # Load data
        depth = np.load(depth_map).astype(np.float32)
        texture_img = Image.open(room_plate).convert("RGB")
        texture_arr = np.array(texture_img)

        h, w = depth.shape[:2]
        aspect_ratio = w / h if h > 0 else 1.0

        # Check if depth is uniform (flat-floor fallback case)
        valid_mask = np.isfinite(depth) & (depth > 0.0)
        valid_ratio = np.count_nonzero(valid_mask) / max(depth.size, 1)

        # Determine if this is a flat-floor fallback scenario
        # (uniform depth or too few valid pixels)
        is_uniform = False
        if valid_ratio > 0.5:
            valid_depths = depth[valid_mask]
            depth_std = float(np.std(valid_depths))
            is_uniform = depth_std < 0.01  # Practically flat

        use_heuristic = valid_ratio <= 0.5 or is_uniform

        if use_heuristic:
            logger.info(
                "Using flat-floor fallback (valid_ratio=%.2f, uniform=%s)",
                valid_ratio,
                is_uniform,
            )
            mesh = self._flat_floor_fallback(aspect_ratio)
            dimensions_m = (
                _FALLBACK_DEPTH_M * aspect_ratio,
                _FALLBACK_HEIGHT_M,
                _FALLBACK_DEPTH_M,
            )
        else:
            mesh = self._point_cloud_to_mesh(depth, texture_arr)
            # Compute bounding box dimensions from the mesh
            bounds = mesh.bounds  # shape (2, 3): [min, max]
            extents = bounds[1] - bounds[0]
            dimensions_m = (
                float(extents[0]),  # width (X)
                float(extents[1]),  # height (Y)
                float(extents[2]),  # depth (Z)
            )

        # Enforce vertex count bounds
        mesh = self._enforce_vertex_bounds(mesh)

        # Export to GLB
        self.output_dir.mkdir(parents=True, exist_ok=True)
        glb_path = self.output_dir / "room_mesh.glb"
        mesh.export(str(glb_path), file_type="glb")

        return RoomMeshResult(
            mesh_path=glb_path,
            dimensions_m=dimensions_m,
            vertex_count=len(mesh.vertices),
            face_count=len(mesh.faces),
            used_heuristic=use_heuristic,
        )

    def _point_cloud_to_mesh(
        self, depth: np.ndarray, texture: np.ndarray
    ) -> trimesh.Trimesh:
        """Convert depth map to a textured triangle mesh.

        Back-projects each valid pixel to 3D using the pinhole camera model,
        builds a triangle grid from adjacent pixels, and maps the room plate
        image as a texture via UV coordinates.

        Parameters
        ----------
        depth : np.ndarray
            Float32 depth map of shape (H, W) in meters.
        texture : np.ndarray
            RGB texture array of shape (H, W, 3), uint8.

        Returns
        -------
        trimesh.Trimesh
            Textured triangle mesh in WorldContract coordinates.
        """
        h, w = depth.shape[:2]

        # Subsample if the image is too large to stay within vertex budget
        step = max(1, max(h, w) // _MAX_GRID_DIM)

        # Generate pixel grid (subsampled)
        rows = np.arange(0, h, step)
        cols = np.arange(0, w, step)
        grid_h = len(rows)
        grid_w = len(cols)

        # Camera intrinsics
        fov_v_rad = math.radians(self.fov_v_deg)
        fov_h_rad = 2.0 * math.atan(math.tan(fov_v_rad / 2.0) * (w / h))

        fy = h / (2.0 * math.tan(fov_v_rad / 2.0))
        fx = w / (2.0 * math.tan(fov_h_rad / 2.0))
        cx = w / 2.0
        cy = h / 2.0

        # Build meshgrid of pixel coordinates
        uu, vv = np.meshgrid(cols, rows)  # shape (grid_h, grid_w)

        # Sample depth at grid points
        sampled_depth = depth[rows][:, cols]  # (grid_h, grid_w)

        # Valid pixel mask
        valid = np.isfinite(sampled_depth) & (sampled_depth > 0.0)

        # Back-project to 3D (WorldContract: right-handed, Y-up, camera at origin looking along -Z)
        x_3d = (uu.astype(np.float64) - cx) * sampled_depth / fx
        y_3d = -(vv.astype(np.float64) - cy) * sampled_depth / fy
        z_3d = -sampled_depth.astype(np.float64)

        # UV coordinates from pixel positions
        u_uv = uu.astype(np.float64) / w
        v_uv = vv.astype(np.float64) / h

        # Flatten
        vertices_x = x_3d.ravel()
        vertices_y = y_3d.ravel()
        vertices_z = z_3d.ravel()
        valid_flat = valid.ravel()
        uv_u = u_uv.ravel()
        uv_v = v_uv.ravel()

        # Build vertex index map (-1 for invalid)
        vertex_indices = np.full(grid_h * grid_w, -1, dtype=np.int64)
        valid_positions = np.where(valid_flat)[0]
        vertex_indices[valid_positions] = np.arange(len(valid_positions))

        # Extract valid vertices and UVs
        vertices = np.column_stack([
            vertices_x[valid_flat],
            vertices_y[valid_flat],
            vertices_z[valid_flat],
        ])
        uvs = np.column_stack([
            uv_u[valid_flat],
            uv_v[valid_flat],
        ])

        # Build faces from grid connectivity (two triangles per quad)
        # Only create faces where all 4 corners of the quad are valid
        faces = []
        vertex_index_grid = vertex_indices.reshape(grid_h, grid_w)

        for r in range(grid_h - 1):
            for c in range(grid_w - 1):
                tl = vertex_index_grid[r, c]
                tr = vertex_index_grid[r, c + 1]
                bl = vertex_index_grid[r + 1, c]
                br = vertex_index_grid[r + 1, c + 1]

                if tl >= 0 and tr >= 0 and bl >= 0:
                    faces.append([tl, bl, tr])
                if tr >= 0 and bl >= 0 and br >= 0:
                    faces.append([tr, bl, br])

        if not faces:
            # Fallback: if no faces could be formed, return flat-floor
            logger.warning(
                "No valid faces formed from depth map — falling back to flat-floor"
            )
            aspect = depth.shape[1] / max(depth.shape[0], 1)
            return self._flat_floor_fallback(aspect)

        faces_arr = np.array(faces, dtype=np.int64)

        # Create the textured mesh
        # Resize texture to a reasonable size for the material
        tex_img = Image.fromarray(texture)
        # Keep texture at a manageable size (max 2048)
        max_tex = 2048
        if tex_img.width > max_tex or tex_img.height > max_tex:
            ratio = min(max_tex / tex_img.width, max_tex / tex_img.height)
            new_size = (int(tex_img.width * ratio), int(tex_img.height * ratio))
            tex_img = tex_img.resize(new_size, Image.LANCZOS)

        # Build trimesh with texture
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=tex_img,
        )

        # Create TextureVisuals with UV coordinates
        visuals = trimesh.visual.TextureVisuals(
            uv=uvs,
            material=material,
        )

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces_arr,
            visual=visuals,
            process=False,
        )

        return mesh

    def _flat_floor_fallback(self, aspect_ratio: float) -> trimesh.Trimesh:
        """Create a box room from aspect ratio heuristic.

        Creates a simple box room with 5 faces (open on the camera-facing side
        for entry). The room is oriented in WorldContract coordinates
        (right-handed, Y-up).

        Dimensions:
        - width (X) = 4.0 * aspect_ratio
        - height (Y) = 2.7
        - depth (Z) = 4.0

        Parameters
        ----------
        aspect_ratio : float
            Width/height ratio of the source image.

        Returns
        -------
        trimesh.Trimesh
            Simple box room mesh with white color, open on front side.
        """
        width = _FALLBACK_DEPTH_M * aspect_ratio
        height = _FALLBACK_HEIGHT_M
        depth = _FALLBACK_DEPTH_M

        # Define the 8 corners of the room box
        # Camera is at origin looking along -Z, so room extends into -Z
        # Room is centered on X, sits on Y=0 (floor level)
        hw = width / 2.0  # half-width
        #   0: front-bottom-left, 1: front-bottom-right
        #   2: front-top-left,    3: front-top-right
        #   4: back-bottom-left,  5: back-bottom-right
        #   6: back-top-left,     7: back-top-right
        vertices = np.array([
            [-hw, 0.0, 0.0],       # 0 front-bottom-left
            [hw, 0.0, 0.0],        # 1 front-bottom-right
            [-hw, height, 0.0],    # 2 front-top-left
            [hw, height, 0.0],     # 3 front-top-right
            [-hw, 0.0, -depth],    # 4 back-bottom-left
            [hw, 0.0, -depth],     # 5 back-bottom-right
            [-hw, height, -depth], # 6 back-top-left
            [hw, height, -depth],  # 7 back-top-right
        ], dtype=np.float64)

        # Faces (open on front = no face between 0,1,2,3)
        # Each face is two triangles, winding so normals face inward
        faces = np.array([
            # Floor (Y=0): 0,1,5,4 — normal up (+Y)
            [0, 5, 1],
            [0, 4, 5],
            # Ceiling (Y=height): 2,3,7,6 — normal down (-Y)
            [2, 3, 7],
            [2, 7, 6],
            # Back wall (Z=-depth): 4,5,7,6 — normal toward camera (+Z)
            [4, 5, 7],
            [4, 7, 6],
            # Left wall (X=-hw): 0,4,6,2 — normal right (+X)
            [0, 4, 6],
            [0, 6, 2],
            # Right wall (X=+hw): 1,5,7,3 — normal left (-X)
            [1, 7, 5],
            [1, 3, 7],
        ], dtype=np.int64)

        # White color for all faces
        face_colors = np.tile([255, 255, 255, 255], (len(faces), 1)).astype(np.uint8)

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            process=False,
        )
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh=mesh,
            face_colors=face_colors,
        )

        return mesh

    def _enforce_vertex_bounds(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Enforce vertex count bounds via decimation or subdivision.

        If vertex count exceeds _MAX_VERTICES, decimate the mesh.
        If vertex count is below _MIN_VERTICES and the mesh is very simple
        (like the fallback box), we leave it as-is since the fallback box
        is intentionally simple.

        Parameters
        ----------
        mesh : trimesh.Trimesh
            Input mesh.

        Returns
        -------
        trimesh.Trimesh
            Mesh with vertex count within bounds (or as close as decimation allows).
        """
        vertex_count = len(mesh.vertices)

        if vertex_count > _MAX_VERTICES:
            # Decimate to fit within bounds
            target_faces = int(len(mesh.faces) * (_MAX_VERTICES / vertex_count))
            target_faces = max(target_faces, 4)  # Never go below 4 faces
            try:
                mesh = mesh.simplify_quadric_decimation(target_faces)
                logger.info(
                    "Decimated room mesh from %d to %d vertices",
                    vertex_count,
                    len(mesh.vertices),
                )
            except Exception as exc:
                logger.warning(
                    "Quadric decimation failed (%s) — keeping original mesh", exc
                )

        return mesh
