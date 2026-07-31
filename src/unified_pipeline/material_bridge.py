"""Unified pipeline adapter for the V14 two-pass material processor.

Bridges the existing `src/photo_pipeline/stages/material_processor.py`
into the unified pipeline's data model (ObjectCanon, MeshApproval).

Pass 1: Immediate — accept native generator textures or photo-project
         Object_Canon onto placeholder geometry. Completes within 2s.
Pass 2: Background — estimate metallic, roughness, normal map from
         Object_Canon when GPU is free. Largest objects processed first.
Hot-swap: Pass 2 results delivered via WebSocket without page reload.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.photo_pipeline.models_v14 import MaterialPassResult
from src.photo_pipeline.stages.material_processor import MaterialProcessor
from src.unified_pipeline.models import ObjectCanon

logger = logging.getLogger(__name__)

# Generation methods that produce native textures (no photo-projection needed)
_NATIVE_TEXTURE_METHODS = ("hunyuan3d_v2.1", "trellis2")


@dataclass(frozen=True)
class MaterialBridgeResult:
    """Result from the unified material bridge for one object."""

    object_id: str
    mesh_path: str
    pass_number: int
    has_base_color: bool
    has_metallic_roughness: bool
    has_normal_map: bool
    texture_resolution: tuple[int, int]
    success: bool
    error: str | None = None


class UnifiedMaterialProcessor:
    """Adapter that wraps the V14 MaterialProcessor for the unified pipeline.

    Delegates all texture generation, PBR estimation, and GLB embedding
    to the existing implementation. Does NOT duplicate logic.

    Usage:
        processor = UnifiedMaterialProcessor()
        result = processor.apply_pass_1(mesh_path, object_canon)
        result = await processor.apply_pass_2(mesh_path, object_canon)
    """

    def __init__(self) -> None:
        self._processor = MaterialProcessor()

    def apply_pass_1(
        self,
        mesh_path: str,
        object_canon: ObjectCanon,
        generation_method: str = "placeholder",
    ) -> str:
        """Apply Pass 1 materials — immediate texturing.

        For Hunyuan3D/Trellis2 meshes: verifies native generator textures
        are present (already conditioned on Object_Canon).
        For placeholders: photo-projects the Object_Canon image onto the
        mesh surface using UV mapping.

        Must complete within 2 seconds (Req 12.1).

        Args:
            mesh_path: Path to the GLB mesh file.
            object_canon: The approved ObjectCanon with image_path and
                mask_coverage for texture size selection.
            generation_method: One of 'hunyuan3d_v2.1', 'trellis2', or
                'placeholder'.

        Returns:
            Updated mesh path (same path — GLB modified in place).
        """
        glb_path = Path(mesh_path)
        object_png = Path(object_canon.image_path)
        image_area_pct = object_canon.mask_coverage

        result: MaterialPassResult = self._processor.apply_pass1(
            glb_path=glb_path,
            object_png=object_png,
            generation_method=generation_method,
            image_area_pct=image_area_pct,
        )

        if not result.has_base_color:
            logger.warning(
                "Pass 1 did not produce base color for %s (method=%s)",
                object_canon.object_id,
                generation_method,
            )

        return mesh_path

    async def apply_pass_2(
        self,
        mesh_path: str,
        object_canon: ObjectCanon,
        material_type: str = "plastic",
    ) -> str:
        """Apply Pass 2 materials — background PBR estimation.

        Estimates metallic, roughness, and normal map from the Object_Canon
        image using material-type heuristics. Runs when GPU is free.
        Processes largest objects first (caller is responsible for ordering).

        If Pass 2 fails, Pass 1 textures are retained (Req 12.4).

        Args:
            mesh_path: Path to the GLB mesh file (already has Pass 1).
            object_canon: The approved ObjectCanon with image_path.
            material_type: Primary material type for PBR heuristic
                ('metal', 'wood', 'glass', 'fabric', 'ceramic', 'plastic').

        Returns:
            Updated mesh path (same path — GLB modified in place with PBR).
        """
        glb_path = Path(mesh_path)
        object_png = Path(object_canon.image_path)

        result: MaterialPassResult = await self._processor.apply_pass2(
            glb_path=glb_path,
            object_png=object_png,
            material_type=material_type,
        )

        if not result.has_metallic_roughness:
            logger.warning(
                "Pass 2 did not produce metallic-roughness for %s. "
                "Pass 1 textures retained.",
                object_canon.object_id,
            )

        return mesh_path

    def get_texture_size(self, image_area_fraction: float) -> tuple[int, int]:
        """Determine texture resolution from object screen-space footprint.

        Per Req 12.6:
            - <2% image area  → 256×256
            - 2-10% image area → 512×512
            - >10% image area  → 1024×1024

        Args:
            image_area_fraction: Object area as fraction of image (0.0-1.0).

        Returns:
            Texture dimensions as (width, height) tuple.
        """
        return self._processor.select_texture_size(image_area_fraction)

    def get_pass2_queue(
        self, objects_with_areas: list[tuple[str, float]]
    ) -> list[str]:
        """Return object IDs sorted by area descending for Pass 2 scheduling.

        Largest objects are processed first (Req 12.2) so the most
        visually prominent assets get PBR materials earliest.

        Args:
            objects_with_areas: List of (object_id, area_fraction) tuples.

        Returns:
            Object IDs sorted by area descending (largest first).
        """
        return self._processor.get_pass2_queue(objects_with_areas)

    async def process_all_pass2(
        self,
        objects: list[tuple[str, ObjectCanon, str]],
        websocket_notify: Any | None = None,
    ) -> list[MaterialBridgeResult]:
        """Process Pass 2 for multiple objects in priority order.

        Processes largest objects first and optionally notifies via
        WebSocket after each object completes (Req 12.3 hot-swap).

        Args:
            objects: List of (mesh_path, object_canon, material_type) tuples,
                pre-sorted by priority (largest first).
            websocket_notify: Optional async callable that accepts a dict
                payload to push material updates to V14+ viewers. Called
                after each successful Pass 2 with:
                    {"type": "material_update", "object_id": ...,
                     "pass": 2, "mesh_path": ..., "has_pbr": True}

        Returns:
            List of MaterialBridgeResult for each object processed.
        """
        results: list[MaterialBridgeResult] = []

        for mesh_path, object_canon, material_type in objects:
            try:
                updated_path = await self.apply_pass_2(
                    mesh_path=mesh_path,
                    object_canon=object_canon,
                    material_type=material_type,
                )

                result = MaterialBridgeResult(
                    object_id=object_canon.object_id,
                    mesh_path=updated_path,
                    pass_number=2,
                    has_base_color=True,
                    has_metallic_roughness=True,
                    has_normal_map=True,
                    texture_resolution=self.get_texture_size(
                        object_canon.mask_coverage
                    ),
                    success=True,
                )
                results.append(result)

                # Hot-swap notification via WebSocket (Req 12.3)
                if websocket_notify is not None:
                    try:
                        await websocket_notify(
                            {
                                "type": "material_update",
                                "object_id": object_canon.object_id,
                                "pass": 2,
                                "mesh_path": updated_path,
                                "has_pbr": True,
                                "texture_resolution": list(
                                    result.texture_resolution
                                ),
                            }
                        )
                    except Exception as ws_exc:
                        logger.warning(
                            "WebSocket notify failed for %s: %s",
                            object_canon.object_id,
                            ws_exc,
                        )

            except Exception as exc:
                # Pass 2 failure → Pass 1 textures retained (Req 12.4)
                logger.warning(
                    "Pass 2 failed for %s: %s. Retaining Pass 1.",
                    object_canon.object_id,
                    exc,
                )
                results.append(
                    MaterialBridgeResult(
                        object_id=object_canon.object_id,
                        mesh_path=mesh_path,
                        pass_number=2,
                        has_base_color=True,
                        has_metallic_roughness=False,
                        has_normal_map=False,
                        texture_resolution=self.get_texture_size(
                            object_canon.mask_coverage
                        ),
                        success=False,
                        error=str(exc),
                    )
                )

        return results
