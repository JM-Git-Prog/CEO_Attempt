"""Room Shell Reconstructor — displaced-grid depth mesh reconstruction.

Reconstructs the room environment from a depth map using a displaced-grid method:
1. Create regular grid at image resolution (max 500 vertices per dimension)
2. Displace each vertex along camera ray by its depth value
3. Remove faces where depth gradient > 0.5m per cell
4. Apply Room_Plate as UV-mapped texture
5. Orient in WorldContract coords (Y-up, camera at origin, -Z forward)
6. Face winding produces inward-facing normals
7. Export as GLB with embedded texture

Includes flat-box fallback (4m depth, aspect-ratio width, 2.7m ceiling)
for invalid depth maps (>50% invalid pixels).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from src.photo_pipeline.models_v14 import RoomShellResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Camera model defaults
_DEFAULT_FOV_V_DEG = 60.0

# Grid limits
_DEFAULT_MAX_GRID_DIM = 500

# Depth gradient threshold for face removal
_DEFAULT_GRADIENT_THRESHOLD_M = 0.5

# Flat-box fallback dimensions
_FALLBACK_DEPTH_M = 4.0
_FALLBACK_HEIGHT_M = 2.7

# Depth validity threshold — fallback if >50% pixels are invalid
_INVALID_PIXEL_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class RoomShellReconstructor:
    """Reconstruct room environment from depth map using displaced-grid method.

    Algorithm:
    1. Create regular grid at image resolution (max 500 vertices per dimension)
    2. Displace each vertex along camera ray by its depth value
    3. Remove/split faces where depth gradient > 0.5m per cell
    4. Apply Room_Plate as UV-mapped texture
    5. Orient in WorldContract coords (Y-up, camera at origin, -Z forward)
    6. Face winding produces inward-facing normals

    Parameters
    ----------
    output_dir : Path
        Directory where the output GLB will be saved.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def reconstruct(
        self,
        depth_map: np.ndarray,
        room_plate_path: Path,
        image_width: int,
        image_height: int,
        *,
        fov_v_deg: float = _DEFAULT_FOV_V_DEG,
        max_grid_dim: int = _DEFAULT_MAX_GRID_DIM,
        gradient_threshold_m: float = _DEFAULT_GRADIENT_THRESHOLD_M,
    ) -> RoomShellResult:
        """Produce a textured GLB mesh of the room shell.

        Parameters
        ----------
        depth_map : np.ndarray
            Float32 depth map (H, W) in meters.
        room_plate_path : Path
            Path to the Room_Plate PNG texture.
        image_width : int
            Width of the source image in pixels.
        image_height : int
            Height of the source image in pixels.
        fov_v_deg : float
            Vertical field of view in degrees (default 60°).
        max_grid_dim : int
            Maximum vertices per grid dimension (default 500).
        gradient_threshold_m : float
            Max depth difference between adjacent vertices before
            a face is removed (default 0.5m).

        Returns
        -------
        RoomShellResult
            Result containing GLB path, dimensions, mesh stats, etc.
        """
        # Check depth validity — fallback if >50% invalid
        valid_mask = (
            np.isfinite(depth_map)
            & (depth_map > 0.0)
            & (~np.isinf(depth_map))
        )
        valid_ratio = float(np.sum(valid_mask)) / max(depth_map.size, 1)

        if valid_ratio < _INVALID_PIXEL_THRESHOLD:
            logger.info(
                "Depth map has %.1f%% valid pixels (< 50%%) — using flat-box fallback",
                valid_ratio * 100,
            )
            return self._flat_box_fallback(
                room_plate_path, image_width, image_height
            )

        # Compute grid dimensions (downsample if needed)
        grid_h, grid_w = self._compute_grid_dims(
            image_height, image_width, max_grid_dim
        )

        # Create the regular grid
        grid_coords = self._create_grid(grid_w, grid_h, image_width, image_height)

        # Sample depth at grid positions
        sampled_depth = self._sample_depth(depth_map, grid_coords, grid_h, grid_w)

        # Displace vertices along camera rays
        vertices = self._displace_vertices(
            grid_coords, sampled_depth, fov_v_deg, image_width, image_height
        )

        # Create faces from grid connectivity
        faces = self._create_faces(grid_h, grid_w)

        # Remove stretched faces where depth gradient exceeds threshold
        faces, faces_removed = self._remove_stretched_faces(
            vertices, faces, sampled_depth, grid_h, grid_w, gradient_threshold_m
        )

        # Flip face winding for inward-facing normals
        # Normals should point toward camera origin (inward for interior rendering)
        faces = self._orient_normals_inward(vertices, faces)

        # Compute UV coordinates
        uvs = self._compute_uvs(grid_coords, image_width, image_height)

        # Load Room_Plate texture
        texture_img = Image.open(room_plate_path).convert("RGB")
        # Limit texture size for performance
        max_tex = 2048
        if texture_img.width > max_tex or texture_img.height > max_tex:
            ratio = min(max_tex / texture_img.width, max_tex / texture_img.height)
            new_size = (int(texture_img.width * ratio), int(texture_img.height * ratio))
            texture_img = texture_img.resize(new_size, Image.LANCZOS)

        # Build trimesh with texture
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=texture_img,
        )
        visuals = trimesh.visual.TextureVisuals(
            uv=uvs,
            material=material,
        )

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            visual=visuals,
            process=False,
        )

        # Compute bounding box dimensions
        bounds = mesh.bounds  # shape (2, 3): [min, max]
        extents = bounds[1] - bounds[0]
        # Ensure all dimensions are positive (uniform depth can produce 0 extent)
        dimensions_m = (
            max(float(extents[0]), 0.001),  # width (X)
            max(float(extents[1]), 0.001),  # height (Y)
            max(float(extents[2]), 0.001),  # depth (Z)
        )

        # Export to GLB
        self.output_dir.mkdir(parents=True, exist_ok=True)
        glb_path = self.output_dir / "room_shell.glb"
        mesh.export(str(glb_path), file_type="glb")

        return RoomShellResult(
            mesh_path=glb_path,
            dimensions_m=dimensions_m,
            vertex_count=len(mesh.vertices),
            face_count=len(mesh.faces),
            grid_resolution=(grid_h, grid_w),
            faces_removed_gradient=faces_removed,
            used_fallback=False,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _compute_grid_dims(
        self, image_height: int, image_width: int, max_grid_dim: int
    ) -> tuple[int, int]:
        """Compute grid dimensions, downsampling if necessary.

        If either dimension exceeds max_grid_dim, scale both proportionally
        so neither exceeds max_grid_dim.

        Enforces a minimum grid size to guarantee vertex count >= 10,000.
        Minimum per dimension: ceil(sqrt(10000)) = 100.

        Returns
        -------
        tuple[int, int]
            (grid_height, grid_width)
        """
        # Minimum grid dimensions to ensure >= 10000 vertices
        min_grid_dim = 100

        grid_h = image_height
        grid_w = image_width

        if grid_h > max_grid_dim or grid_w > max_grid_dim:
            scale = max_grid_dim / max(grid_h, grid_w)
            grid_h = max(min_grid_dim, int(grid_h * scale))
            grid_w = max(min_grid_dim, int(grid_w * scale))
        else:
            # Ensure minimum dimensions even for small images
            grid_h = max(min_grid_dim, grid_h)
            grid_w = max(min_grid_dim, grid_w)

        return (grid_h, grid_w)

    def _create_grid(
        self,
        grid_w: int,
        grid_h: int,
        image_width: int,
        image_height: int,
    ) -> np.ndarray:
        """Create a regular grid of pixel coordinates.

        Maps grid indices to pixel positions in the original image.

        Parameters
        ----------
        grid_w, grid_h : int
            Grid dimensions (may be downsampled from image dims).
        image_width, image_height : int
            Original image dimensions.

        Returns
        -------
        np.ndarray
            Array of shape (grid_h * grid_w, 2) with (u, v) pixel coords.
        """
        # Linearly space grid coords across the image
        u_coords = np.linspace(0, image_width - 1, grid_w)
        v_coords = np.linspace(0, image_height - 1, grid_h)

        uu, vv = np.meshgrid(u_coords, v_coords)  # (grid_h, grid_w)
        # Stack as (N, 2) array of (u, v) pairs
        coords = np.column_stack([uu.ravel(), vv.ravel()])
        return coords

    def _sample_depth(
        self,
        depth_map: np.ndarray,
        grid_coords: np.ndarray,
        grid_h: int,
        grid_w: int,
    ) -> np.ndarray:
        """Sample depth values at grid positions using nearest-neighbor.

        Parameters
        ----------
        depth_map : np.ndarray
            Full resolution depth map (H, W).
        grid_coords : np.ndarray
            Grid pixel coordinates, shape (N, 2) as (u, v).
        grid_h, grid_w : int
            Grid dimensions.

        Returns
        -------
        np.ndarray
            Sampled depth values, shape (grid_h, grid_w).
        """
        h, w = depth_map.shape[:2]
        # Convert pixel coords to integer indices (nearest neighbor)
        u_idx = np.clip(np.round(grid_coords[:, 0]).astype(int), 0, w - 1)
        v_idx = np.clip(np.round(grid_coords[:, 1]).astype(int), 0, h - 1)
        sampled = depth_map[v_idx, u_idx]
        return sampled.reshape(grid_h, grid_w)

    def _displace_vertices(
        self,
        grid_coords: np.ndarray,
        sampled_depth: np.ndarray,
        fov_v_deg: float,
        image_width: int,
        image_height: int,
    ) -> np.ndarray:
        """Back-project grid vertices using pinhole camera model.

        For each grid vertex at pixel position (u, v) with depth d:
            x = (u - cx) * d / fx
            y = -(v - cy) * d / fy
            z = -d

        Parameters
        ----------
        grid_coords : np.ndarray
            Pixel coordinates, shape (N, 2).
        sampled_depth : np.ndarray
            Depth values at grid positions, shape (grid_h, grid_w).
        fov_v_deg : float
            Vertical FOV in degrees.
        image_width, image_height : int
            Image dimensions for intrinsics computation.

        Returns
        -------
        np.ndarray
            3D vertex positions, shape (N, 3).
        """
        # Compute camera intrinsics from FOV
        fov_v_rad = math.radians(fov_v_deg)
        fy = image_height / (2.0 * math.tan(fov_v_rad / 2.0))
        fx = fy  # Square pixels assumed
        cx = image_width / 2.0
        cy = image_height / 2.0

        u = grid_coords[:, 0]
        v = grid_coords[:, 1]
        d = sampled_depth.ravel()

        # Replace invalid depths with a reasonable default (won't be rendered
        # as their faces get removed, but need valid positions for face filtering)
        valid = np.isfinite(d) & (d > 0.0)
        d_safe = np.where(valid, d, 4.0)  # default 4m for invalid

        x = (u - cx) * d_safe / fx
        y = -(v - cy) * d_safe / fy
        z = -d_safe

        vertices = np.column_stack([x, y, z])
        return vertices

    def _create_faces(self, grid_h: int, grid_w: int) -> np.ndarray:
        """Create triangle faces from grid connectivity.

        For each quad in the grid, create two triangles.
        Winding order: counter-clockwise when viewed from the front.

        Returns
        -------
        np.ndarray
            Face indices, shape (num_faces, 3).
        """
        faces = []
        for r in range(grid_h - 1):
            for c in range(grid_w - 1):
                # Vertex indices in the flattened grid
                tl = r * grid_w + c           # top-left
                tr = r * grid_w + (c + 1)     # top-right
                bl = (r + 1) * grid_w + c     # bottom-left
                br = (r + 1) * grid_w + (c + 1)  # bottom-right

                # Two triangles per quad
                # Winding for front-facing (toward camera): CCW
                faces.append([tl, bl, tr])
                faces.append([tr, bl, br])

        return np.array(faces, dtype=np.int64)

    def _remove_stretched_faces(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        sampled_depth: np.ndarray,
        grid_h: int,
        grid_w: int,
        threshold: float,
    ) -> tuple[np.ndarray, int]:
        """Remove faces where depth gradient exceeds threshold.

        For each face, check the maximum depth difference between any
        two vertices of the face. If it exceeds the threshold, the face
        is removed.

        Parameters
        ----------
        vertices : np.ndarray
            Vertex positions, shape (N, 3).
        faces : np.ndarray
            Face indices, shape (F, 3).
        sampled_depth : np.ndarray
            Depth grid, shape (grid_h, grid_w).
        grid_h, grid_w : int
            Grid dimensions.
        threshold : float
            Maximum allowed depth difference in meters.

        Returns
        -------
        tuple[np.ndarray, int]
            (filtered_faces, num_removed)
        """
        depth_flat = sampled_depth.ravel()

        # For each face, get the depth at each vertex
        v0_depth = depth_flat[faces[:, 0]]
        v1_depth = depth_flat[faces[:, 1]]
        v2_depth = depth_flat[faces[:, 2]]

        # Replace invalid (nan/inf/negative) with large value to trigger removal
        for arr in [v0_depth, v1_depth, v2_depth]:
            invalid = ~(np.isfinite(arr) & (arr > 0))
            arr[invalid] = 1e6

        # Compute max depth difference across each face's vertices
        max_diff = np.maximum(
            np.maximum(
                np.abs(v0_depth - v1_depth),
                np.abs(v1_depth - v2_depth),
            ),
            np.abs(v0_depth - v2_depth),
        )

        # Also remove faces with any invalid vertex
        any_invalid = (v0_depth >= 1e5) | (v1_depth >= 1e5) | (v2_depth >= 1e5)

        # Keep faces where gradient is within threshold and all vertices valid
        keep_mask = (max_diff <= threshold) & ~any_invalid

        filtered_faces = faces[keep_mask]
        num_removed = int(np.sum(~keep_mask))

        return filtered_faces, num_removed

    def _orient_normals_inward(
        self, vertices: np.ndarray, faces: np.ndarray
    ) -> np.ndarray:
        """Orient face winding so normals point toward camera origin.

        The camera is at (0, 0, 0). For each face, the normal should
        point toward the origin — i.e., dot(normal, centroid_to_origin) > 0.

        If the dot product is negative, flip the face winding.

        Parameters
        ----------
        vertices : np.ndarray
            Vertex positions, shape (N, 3).
        faces : np.ndarray
            Face indices, shape (F, 3).

        Returns
        -------
        np.ndarray
            Faces with corrected winding for inward-facing normals.
        """
        if len(faces) == 0:
            return faces

        # Get face vertices
        v0 = vertices[faces[:, 0]]
        v1 = vertices[faces[:, 1]]
        v2 = vertices[faces[:, 2]]

        # Compute face normals (cross product of edges)
        edge1 = v1 - v0
        edge2 = v2 - v0
        normals = np.cross(edge1, edge2)

        # Compute face centroids
        centroids = (v0 + v1 + v2) / 3.0

        # Vector from centroid to origin
        centroid_to_origin = -centroids  # origin is (0,0,0)

        # Dot product: should be positive for inward-facing
        dots = np.sum(normals * centroid_to_origin, axis=1)

        # Flip winding where dot is negative
        flip_mask = dots < 0
        flipped = faces.copy()
        # Swap columns 1 and 2 to reverse winding
        flipped[flip_mask, 1], flipped[flip_mask, 2] = (
            faces[flip_mask, 2],
            faces[flip_mask, 1],
        )

        return flipped

    def _compute_uvs(
        self,
        grid_coords: np.ndarray,
        image_width: int,
        image_height: int,
    ) -> np.ndarray:
        """Map grid positions to [0,1] UV range for texture mapping.

        Parameters
        ----------
        grid_coords : np.ndarray
            Pixel coordinates, shape (N, 2) as (u, v).
        image_width, image_height : int
            Image dimensions.

        Returns
        -------
        np.ndarray
            UV coordinates, shape (N, 2).
        """
        u_uv = grid_coords[:, 0] / max(image_width - 1, 1)
        v_uv = grid_coords[:, 1] / max(image_height - 1, 1)
        return np.column_stack([u_uv, v_uv])

    def _flat_box_fallback(
        self,
        room_plate_path: Path,
        image_width: int,
        image_height: int,
    ) -> RoomShellResult:
        """Create a flat box room when depth map is invalid.

        Creates a box room with:
        - depth: 4m
        - width: 4m × aspect_ratio
        - height: 2.7m

        Uses planar UV projection from the camera viewpoint.
        Open on camera-facing side (no front wall).

        Parameters
        ----------
        room_plate_path : Path
            Path to the Room_Plate texture.
        image_width, image_height : int
            Image dimensions for aspect ratio calculation.

        Returns
        -------
        RoomShellResult
            Result with fallback mesh.
        """
        aspect_ratio = image_width / max(image_height, 1)
        width = _FALLBACK_DEPTH_M * aspect_ratio
        height = _FALLBACK_HEIGHT_M
        depth = _FALLBACK_DEPTH_M

        hw = width / 2.0  # half-width

        # 8 corners of the box room
        # Camera at origin looking along -Z
        # Room floor at Y=0, extends into -Z
        vertices = np.array([
            [-hw, 0.0, 0.0],        # 0: front-bottom-left
            [hw, 0.0, 0.0],         # 1: front-bottom-right
            [-hw, height, 0.0],     # 2: front-top-left
            [hw, height, 0.0],      # 3: front-top-right
            [-hw, 0.0, -depth],     # 4: back-bottom-left
            [hw, 0.0, -depth],      # 5: back-bottom-right
            [-hw, height, -depth],  # 6: back-top-left
            [hw, height, -depth],   # 7: back-top-right
        ], dtype=np.float64)

        # Faces — open front (no face between vertices 0,1,2,3)
        # Winding for inward-facing normals
        faces = np.array([
            # Floor (Y=0): normal pointing up (+Y) inward
            [0, 1, 5],
            [0, 5, 4],
            # Ceiling (Y=height): normal pointing down (-Y) inward
            [2, 7, 3],
            [2, 6, 7],
            # Back wall (Z=-depth): normal pointing forward (+Z) inward
            [4, 5, 7],
            [4, 7, 6],
            # Left wall (X=-hw): normal pointing right (+X) inward
            [0, 4, 6],
            [0, 6, 2],
            # Right wall (X=+hw): normal pointing left (-X) inward
            [1, 3, 7],
            [1, 7, 5],
        ], dtype=np.int64)

        # UV coordinates: planar projection from camera viewpoint
        # Map each vertex to [0,1] based on its position in the box
        uvs = np.array([
            [0.0, 1.0],   # 0: front-bottom-left
            [1.0, 1.0],   # 1: front-bottom-right
            [0.0, 0.0],   # 2: front-top-left
            [1.0, 0.0],   # 3: front-top-right
            [0.0, 1.0],   # 4: back-bottom-left
            [1.0, 1.0],   # 5: back-bottom-right
            [0.0, 0.0],   # 6: back-top-left
            [1.0, 0.0],   # 7: back-top-right
        ], dtype=np.float64)

        # Load texture
        texture_img = Image.open(room_plate_path).convert("RGB")
        max_tex = 2048
        if texture_img.width > max_tex or texture_img.height > max_tex:
            ratio = min(max_tex / texture_img.width, max_tex / texture_img.height)
            new_size = (int(texture_img.width * ratio), int(texture_img.height * ratio))
            texture_img = texture_img.resize(new_size, Image.LANCZOS)

        # Build textured mesh
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=texture_img,
        )
        visuals = trimesh.visual.TextureVisuals(
            uv=uvs,
            material=material,
        )

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            visual=visuals,
            process=False,
        )

        # Export to GLB
        self.output_dir.mkdir(parents=True, exist_ok=True)
        glb_path = self.output_dir / "room_shell.glb"
        mesh.export(str(glb_path), file_type="glb")

        dimensions_m = (width, height, depth)

        return RoomShellResult(
            mesh_path=glb_path,
            dimensions_m=dimensions_m,
            vertex_count=len(mesh.vertices),
            face_count=len(mesh.faces),
            grid_resolution=(1, 1),  # Fallback uses no grid
            faces_removed_gradient=0,
            used_fallback=True,
        )
