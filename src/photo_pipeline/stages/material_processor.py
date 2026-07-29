"""Two-pass PBR material quality system for the V14 pipeline.

Pass 1: Accept native generator textures (Hunyuan3D/Trellis2) or
         photo-project Object_PNG onto placeholder geometry via camera model.
         Must complete within 2 seconds of mesh generation.

Pass 2: Estimate metallic, roughness, and normal map parameters from
         Object_PNG using material-type heuristic. Runs in background
         when GPU is free, processing largest objects first.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.1, 11.2, 11.3
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from src.photo_pipeline.models_v14 import MaterialPassResult
from src.photo_pipeline.stages.material_utils import (
    clamp_pbr_values,
    select_texture_size,
)

logger = logging.getLogger(__name__)

# Neural mesh generation methods that already have embedded textures
_NEURAL_METHODS = ("hunyuan3d_v2.1", "trellis2")

# Material-type → PBR heuristic lookup
_MATERIAL_PBR_HEURISTICS: dict[str, dict[str, float]] = {
    "metal": {"metallic": 0.9, "roughness": 0.3},
    "wood": {"metallic": 0.1, "roughness": 0.7},
    "glass": {"metallic": 0.1, "roughness": 0.1},
    "fabric": {"metallic": 0.0, "roughness": 0.9},
    "ceramic": {"metallic": 0.2, "roughness": 0.4},
    "plastic": {"metallic": 0.1, "roughness": 0.5},
}

# Default PBR values when material type is unknown
_DEFAULT_PBR = {"metallic": 0.1, "roughness": 0.5}


class MaterialProcessor:
    """Two-pass PBR material quality system.

    Pass 1: Accept native generator textures (Hunyuan3D/Trellis2) or
             photo-project for placeholder geometry. Available within 2s.
    Pass 2: Estimate metallic, roughness, normal from Object_PNG.
             Runs in background when GPU is free.
    """

    TEXTURE_SIZES: dict[str, tuple[int, int]] = {
        "small": (256, 256),  # < 2% image area
        "medium": (512, 512),  # 2-10% image area
        "large": (1024, 1024),  # > 10% image area
    }

    def apply_pass1(
        self,
        glb_path: Path,
        object_png: Path,
        generation_method: str,
        image_area_pct: float,
    ) -> MaterialPassResult:
        """Apply Pass 1 textures.

        For neural meshes (hunyuan3d_v2.1, trellis2): verify native textures
        exist and return result indicating base color is present.

        For placeholders: photo-project Object_PNG onto mesh surface using
        UV mapping and embed the texture in the GLB.

        Args:
            glb_path: Path to the generated GLB mesh file.
            object_png: Path to the isolated RGBA object image.
            generation_method: One of 'hunyuan3d_v2.1', 'trellis2', 'placeholder'.
            image_area_pct: Object's fraction of total image area (0.0-1.0).

        Returns:
            MaterialPassResult with pass_number=1 and texture status.
        """
        object_id = glb_path.stem
        tex_size = self.select_texture_size(image_area_pct)

        if generation_method in _NEURAL_METHODS:
            # Neural meshes already have native textures from generator.
            # Verify the GLB exists and has content (basic sanity check).
            if not glb_path.exists() or glb_path.stat().st_size < 100:
                logger.warning(
                    "Pass 1: GLB file missing or too small for %s, "
                    "treating as no base color",
                    object_id,
                )
                return MaterialPassResult(
                    object_id=object_id,
                    pass_number=1,
                    has_base_color=False,
                    has_metallic_roughness=False,
                    has_normal_map=False,
                    texture_resolution=tex_size,
                )

            return MaterialPassResult(
                object_id=object_id,
                pass_number=1,
                has_base_color=True,
                has_metallic_roughness=False,
                has_normal_map=False,
                texture_resolution=tex_size,
            )

        # Placeholder geometry: photo-project Object_PNG as base color texture.
        try:
            self._photo_project_texture(glb_path, object_png, tex_size)
            has_base_color = True
        except Exception as exc:
            logger.error(
                "Pass 1 photo-projection failed for %s: %s", object_id, exc
            )
            has_base_color = False

        return MaterialPassResult(
            object_id=object_id,
            pass_number=1,
            has_base_color=has_base_color,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=tex_size,
        )

    async def apply_pass2(
        self,
        glb_path: Path,
        object_png: Path,
        material_type: str,
    ) -> MaterialPassResult:
        """Estimate and apply PBR parameters (metallic, roughness, normal).

        Uses material_type heuristic to determine base metallic/roughness
        values, clamps them to valid range, and updates the GLB file with
        embedded PBR buffer views following the glTF 2.0 spec.

        If Pass 2 fails, the Pass 1 texture is retained (graceful degradation).

        Args:
            glb_path: Path to the GLB file to update with PBR materials.
            object_png: Path to the Object_PNG for normal map estimation.
            material_type: Primary material ('metal', 'wood', 'glass', etc.).

        Returns:
            MaterialPassResult with pass_number=2 and PBR texture status.
        """
        object_id = glb_path.stem

        try:
            # Get PBR values from material heuristic
            pbr_params = _MATERIAL_PBR_HEURISTICS.get(material_type, _DEFAULT_PBR)
            metallic_raw = pbr_params["metallic"]
            roughness_raw = pbr_params["roughness"]

            # Clamp to valid range
            metallic, roughness = clamp_pbr_values(metallic_raw, roughness_raw)

            # Generate metallic-roughness texture and normal map
            tex_size = self._get_texture_size_from_glb(glb_path)
            mr_texture = self._generate_metallic_roughness_texture(
                metallic, roughness, tex_size
            )
            normal_map = self._estimate_normal_map(object_png, tex_size)

            # Update GLB with embedded PBR buffer views
            self._update_glb_pbr(glb_path, mr_texture, normal_map)

            return MaterialPassResult(
                object_id=object_id,
                pass_number=2,
                has_base_color=True,
                has_metallic_roughness=True,
                has_normal_map=True,
                texture_resolution=tex_size,
            )

        except Exception as exc:
            # Pass 2 failure → retain Pass 1 texture, log warning
            logger.warning(
                "Pass 2 failed for %s: %s. Retaining Pass 1 texture.",
                object_id,
                exc,
            )
            return MaterialPassResult(
                object_id=object_id,
                pass_number=2,
                has_base_color=True,
                has_metallic_roughness=False,
                has_normal_map=False,
                texture_resolution=(512, 512),
            )

    def select_texture_size(self, area_pct: float) -> tuple[int, int]:
        """Select texture dimensions by object screen-space footprint.

        Delegates to the shared material_utils.select_texture_size function.

        Args:
            area_pct: Object area as fraction of image (0.0-1.0).

        Returns:
            Texture dimensions as (width, height) tuple.
        """
        return select_texture_size(area_pct)

    def get_pass2_queue(
        self, objects_with_areas: list[tuple[str, float]]
    ) -> list[str]:
        """Return object IDs sorted by area descending (largest first).

        Ensures the most visually prominent objects get Pass 2 PBR
        materials first during background processing.

        Args:
            objects_with_areas: List of (object_id, area_pct) tuples.

        Returns:
            List of object_ids sorted by area descending.
        """
        sorted_objects = sorted(
            objects_with_areas, key=lambda x: x[1], reverse=True
        )
        return [obj_id for obj_id, _ in sorted_objects]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _photo_project_texture(
        self,
        glb_path: Path,
        object_png: Path,
        tex_size: tuple[int, int],
    ) -> None:
        """Project Object_PNG onto placeholder mesh as base color texture.

        Opens the GLB, creates UV-mapped base color from the Object_PNG
        resized to tex_size, and embeds it in the GLB file.
        """
        import trimesh

        # Load the object image and resize to target texture size
        img = Image.open(object_png).convert("RGBA")
        img_resized = img.resize(tex_size, Image.LANCZOS)

        # Convert to RGB for base color (drop alpha for texture embedding)
        base_color_img = img_resized.convert("RGB")

        # Load the mesh
        scene = trimesh.load(str(glb_path), force="scene")

        # Get geometries from the scene
        if isinstance(scene, trimesh.Scene):
            geometries = list(scene.geometry.values())
        else:
            geometries = [scene]

        # Apply the texture to each geometry's material
        for geom in geometries:
            if not hasattr(geom, "visual"):
                continue

            # Create a PBR material with the projected texture
            material = trimesh.visual.material.PBRMaterial(
                baseColorTexture=base_color_img,
                metallicFactor=0.0,
                roughnessFactor=0.5,
            )

            # If the geometry doesn't have UV coordinates, generate simple ones
            if (
                not hasattr(geom.visual, "uv")
                or geom.visual.uv is None
                or len(geom.visual.uv) == 0
            ):
                # Generate UV coordinates from vertex positions (planar projection)
                vertices = geom.vertices
                if len(vertices) > 0:
                    mins = vertices.min(axis=0)
                    maxs = vertices.max(axis=0)
                    ranges = maxs - mins
                    ranges[ranges == 0] = 1.0  # avoid division by zero
                    # Project onto XY plane for UV
                    uv = np.zeros((len(vertices), 2), dtype=np.float64)
                    uv[:, 0] = (vertices[:, 0] - mins[0]) / ranges[0]
                    uv[:, 1] = (vertices[:, 1] - mins[1]) / ranges[1]
                    geom.visual = trimesh.visual.TextureVisuals(
                        uv=uv, material=material
                    )
            else:
                geom.visual.material = material

        # Export back to GLB with embedded textures
        if isinstance(scene, trimesh.Scene):
            scene.export(str(glb_path), file_type="glb")
        else:
            scene.export(str(glb_path), file_type="glb")

    def _get_texture_size_from_glb(
        self, glb_path: Path
    ) -> tuple[int, int]:
        """Extract texture resolution from existing GLB or default to 512x512.

        Reads the GLB to check if there's an existing base color texture
        and returns its dimensions. Falls back to (512, 512) if none found.
        """
        try:
            import trimesh

            scene = trimesh.load(str(glb_path), force="scene")
            if isinstance(scene, trimesh.Scene):
                for geom in scene.geometry.values():
                    if hasattr(geom, "visual") and hasattr(
                        geom.visual, "material"
                    ):
                        mat = geom.visual.material
                        if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                            tex = mat.baseColorTexture
                            if hasattr(tex, "size"):
                                return tex.size
            return (512, 512)
        except Exception:
            return (512, 512)

    def _generate_metallic_roughness_texture(
        self,
        metallic: float,
        roughness: float,
        tex_size: tuple[int, int],
    ) -> Image.Image:
        """Generate a metallic-roughness texture following glTF 2.0 spec.

        In glTF PBR metallic-roughness:
        - Blue channel = metallic
        - Green channel = roughness
        - Red channel = unused (occlusion if combined)

        Args:
            metallic: Metallic value [0.0, 1.0].
            roughness: Roughness value [0.0, 1.0].
            tex_size: Target texture dimensions.

        Returns:
            PIL Image with metallic-roughness packed per glTF spec.
        """
        metallic_byte = int(metallic * 255)
        roughness_byte = int(roughness * 255)

        # Create uniform metallic-roughness texture
        # glTF: R=occlusion(1.0), G=roughness, B=metallic
        img_array = np.zeros((*tex_size, 3), dtype=np.uint8)
        img_array[:, :, 0] = 255  # Occlusion = 1.0 (no occlusion)
        img_array[:, :, 1] = roughness_byte
        img_array[:, :, 2] = metallic_byte

        return Image.fromarray(img_array, mode="RGB")

    def _estimate_normal_map(
        self,
        object_png: Path,
        tex_size: tuple[int, int],
    ) -> Image.Image:
        """Estimate a normal map from the Object_PNG.

        Uses a simple gradient-based approach to generate a plausible
        normal map from the object's luminance channel. The result is
        a flat normal map with subtle surface detail.

        Args:
            object_png: Path to the RGBA object image.
            tex_size: Target texture dimensions.

        Returns:
            PIL Image representing the normal map in tangent space
            (RGB where (128,128,255) is flat normal pointing +Z).
        """
        try:
            img = Image.open(object_png).convert("L")
            img_resized = img.resize(tex_size, Image.LANCZOS)
            pixels = np.array(img_resized, dtype=np.float32) / 255.0

            # Compute gradients for normal estimation
            # Sobel-like gradients
            grad_x = np.zeros_like(pixels)
            grad_y = np.zeros_like(pixels)

            if pixels.shape[1] > 1:
                grad_x[:, 1:] = pixels[:, 1:] - pixels[:, :-1]
            if pixels.shape[0] > 1:
                grad_y[1:, :] = pixels[1:, :] - pixels[:-1, :]

            # Scale gradients (subtle effect — strength factor)
            strength = 2.0
            grad_x *= strength
            grad_y *= strength

            # Construct normal map in tangent space
            # Normal = normalize(-dz/dx, -dz/dy, 1)
            normal_map = np.zeros((*tex_size, 3), dtype=np.float32)
            normal_map[:, :, 0] = -grad_x  # X component
            normal_map[:, :, 1] = -grad_y  # Y component
            normal_map[:, :, 2] = 1.0  # Z component (always positive)

            # Normalize each normal vector
            lengths = np.sqrt(
                normal_map[:, :, 0] ** 2
                + normal_map[:, :, 1] ** 2
                + normal_map[:, :, 2] ** 2
            )
            lengths[lengths == 0] = 1.0
            normal_map[:, :, 0] /= lengths
            normal_map[:, :, 1] /= lengths
            normal_map[:, :, 2] /= lengths

            # Map from [-1,1] to [0,255] (tangent space encoding)
            normal_map_uint8 = ((normal_map + 1.0) * 0.5 * 255).astype(
                np.uint8
            )

            return Image.fromarray(normal_map_uint8, mode="RGB")

        except Exception as exc:
            logger.warning("Normal map estimation failed: %s. Using flat normal.", exc)
            # Return flat normal map (pointing straight out)
            flat = np.zeros((*tex_size, 3), dtype=np.uint8)
            flat[:, :, 0] = 128  # X = 0
            flat[:, :, 1] = 128  # Y = 0
            flat[:, :, 2] = 255  # Z = 1
            return Image.fromarray(flat, mode="RGB")

    def _update_glb_pbr(
        self,
        glb_path: Path,
        metallic_roughness_texture: Image.Image,
        normal_map: Image.Image,
    ) -> None:
        """Update GLB file with embedded PBR textures (metallic-roughness + normal).

        Loads the existing GLB, applies PBR material with the metallic-roughness
        texture and normal map as embedded buffer views, and re-exports.

        Args:
            glb_path: Path to the GLB file to update.
            metallic_roughness_texture: The metallic-roughness texture image.
            normal_map: The normal map image.
        """
        import trimesh

        scene = trimesh.load(str(glb_path), force="scene")

        if isinstance(scene, trimesh.Scene):
            geometries = list(scene.geometry.values())
        else:
            geometries = [scene]

        for geom in geometries:
            if not hasattr(geom, "visual"):
                continue

            # Get existing base color texture if available
            existing_base_color = None
            if hasattr(geom.visual, "material"):
                mat = geom.visual.material
                if hasattr(mat, "baseColorTexture"):
                    existing_base_color = mat.baseColorTexture
                elif hasattr(mat, "image"):
                    existing_base_color = mat.image

            # Create PBR material with all textures embedded
            pbr_material = trimesh.visual.material.PBRMaterial(
                baseColorTexture=existing_base_color,
                metallicRoughnessTexture=metallic_roughness_texture,
                normalTexture=normal_map,
            )

            # Preserve existing UVs
            if hasattr(geom.visual, "uv") and geom.visual.uv is not None:
                uv = geom.visual.uv
                geom.visual = trimesh.visual.TextureVisuals(
                    uv=uv, material=pbr_material
                )
            else:
                geom.visual.material = pbr_material

        # Export with embedded textures (GLB binary format)
        if isinstance(scene, trimesh.Scene):
            scene.export(str(glb_path), file_type="glb")
        else:
            scene.export(str(glb_path), file_type="glb")
