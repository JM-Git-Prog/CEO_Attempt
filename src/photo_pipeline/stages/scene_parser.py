"""Scene Parser — SAM segmentation and Flux.1-Fill inpainting via ComfyUI.

This module implements the first pipeline stage: segmenting a source photograph
into individual object masks, extracting isolated RGBA Object_PNGs, and inpainting
the background to produce a clean Room_Plate.

The implementation separates pure computation (mask filtering, PNG extraction) from
the ComfyUI orchestration (SAM submission, inpainting submission) to enable
independent testing of the algorithmic core.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
)
from src.photo_pipeline.models import (
    PhotoPipelineConfig,
    SceneParseResult,
    SegmentedObject,
)
from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helper functions (testable without ComfyUI)
# ---------------------------------------------------------------------------


def filter_masks(
    masks: list[np.ndarray],
    image_area: int,
    config: PhotoPipelineConfig,
) -> list[np.ndarray]:
    """Filter segmentation masks by minimum area and maximum count.

    Parameters
    ----------
    masks : list[np.ndarray]
        Binary masks (2D boolean or uint8 arrays, nonzero = foreground).
    image_area : int
        Total image pixel count (width × height).
    config : PhotoPipelineConfig
        Pipeline configuration providing min_mask_area_pct and max_objects.

    Returns
    -------
    list[np.ndarray]
        Filtered masks sorted by area descending, capped at max_objects.
    """
    min_area = (config.min_mask_area_pct / 100.0) * image_area

    # Compute area for each mask and filter by minimum
    scored: list[tuple[int, np.ndarray]] = []
    for mask in masks:
        area = int(np.count_nonzero(mask))
        if area >= min_area:
            scored.append((area, mask))

    # Sort by area descending (largest first) and cap at max_objects
    scored.sort(key=lambda t: t[0], reverse=True)
    return [mask for _, mask in scored[: config.max_objects]]


def extract_object_png(
    source_image: np.ndarray,
    mask: np.ndarray,
    output_path: Path,
) -> Path:
    """Extract a single object as an RGBA PNG using the provided mask.

    Applies the binary mask to the source RGB image, producing an RGBA image
    where transparent pixels correspond to mask value 0.

    Parameters
    ----------
    source_image : np.ndarray
        Source image as RGB uint8 array of shape (H, W, 3).
    mask : np.ndarray
        Binary mask of shape (H, W). Nonzero = object, zero = background.
    output_path : Path
        Destination path for the saved RGBA PNG.

    Returns
    -------
    Path
        The output_path (same as input, for convenience in chaining).
    """
    h, w = mask.shape[:2]
    # Ensure mask is binary uint8
    binary_mask = (mask > 0).astype(np.uint8) * 255

    # Build RGBA: source RGB + alpha channel from mask
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = source_image[:h, :w, :3]
    rgba[:, :, 3] = binary_mask

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(output_path)
    return output_path


def _compute_mask_metadata(
    mask: np.ndarray,
    mask_id: str,
) -> dict[str, Any]:
    """Compute bounding box, area, and centroid for a mask.

    Parameters
    ----------
    mask : np.ndarray
        Binary mask (H, W). Nonzero = object.
    mask_id : str
        Identifier for this mask.

    Returns
    -------
    dict
        Keys: mask_id, bbox (x, y, w, h), area_px, centroid_px (cx, cy).
    """
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return {
            "mask_id": mask_id,
            "bbox": (0, 0, 0, 0),
            "area_px": 0,
            "centroid_px": (0.0, 0.0),
        }

    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    bbox = (x_min, y_min, x_max - x_min + 1, y_max - y_min + 1)
    area_px = int(len(xs))
    centroid_px = (float(xs.mean()), float(ys.mean()))

    return {
        "mask_id": mask_id,
        "bbox": bbox,
        "area_px": area_px,
        "centroid_px": centroid_px,
    }


def _build_combined_foreground_mask(
    masks: list[np.ndarray],
    shape: tuple[int, int],
) -> np.ndarray:
    """Combine multiple object masks into a single foreground mask.

    Parameters
    ----------
    masks : list[np.ndarray]
        Per-object binary masks.
    shape : tuple[int, int]
        (height, width) of the output mask.

    Returns
    -------
    np.ndarray
        Combined binary mask (uint8, 255 = foreground, 0 = background).
    """
    combined = np.zeros(shape, dtype=np.uint8)
    for mask in masks:
        combined = np.maximum(combined, (mask > 0).astype(np.uint8) * 255)
    return combined


# ---------------------------------------------------------------------------
# SceneParser class — orchestrates ComfyUI calls + delegates to helpers
# ---------------------------------------------------------------------------


class SceneParser:
    """Performs scene segmentation and inpainting via ComfyUI.

    Submits SAM ViT-H for instance segmentation, filters masks by area/count,
    extracts per-object RGBA PNGs, and inpaints the background via Flux.1-Fill.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for this session's artifacts.
    """

    def __init__(self, client: ComfyUIClient, output_dir: Path) -> None:
        self.client = client
        self.output_dir = output_dir

    async def parse(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> SceneParseResult:
        """Run the full scene parsing pipeline.

        1. Submit SAM workflow → retrieve segmentation masks
        2. Filter masks by area/count
        3. Extract per-object RGBA PNGs
        4. Combine masks into foreground mask
        5. Submit inpainting workflow → retrieve Room_Plate
        6. Handle edge cases (zero masks, inpainter failure)

        Parameters
        ----------
        source_image : Path
            Path to the source RGB image (JPEG or PNG).
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        SceneParseResult
            Structured result with room plate path, object list, and
            background mask path.
        """
        # Load source image for dimensions and extraction
        src_img = Image.open(source_image).convert("RGB")
        src_array = np.array(src_img)
        h, w = src_array.shape[:2]
        image_area = h * w

        # --- Step 1: SAM segmentation ---
        raw_masks = await self._submit_sam(source_image, config)

        # --- Step 2: Filter masks ---
        filtered_masks = filter_masks(raw_masks, image_area, config)

        # --- Edge case: zero valid masks ---
        if not filtered_masks:
            logger.info(
                "Zero valid masks after filtering — treating as room-only"
            )
            return self._build_zero_mask_result(source_image, (h, w))

        # --- Step 3: Extract object PNGs and compute metadata ---
        objects: list[SegmentedObject] = []
        masks_dir = self.output_dir / "masks"
        masks_dir.mkdir(parents=True, exist_ok=True)
        objects_dir = self.output_dir / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)

        for idx, mask in enumerate(filtered_masks):
            mask_id = f"{idx + 1:03d}"

            # Save binary mask
            mask_png_path = masks_dir / f"mask_{mask_id}.png"
            Image.fromarray(
                (mask > 0).astype(np.uint8) * 255, mode="L"
            ).save(mask_png_path)

            # Extract object PNG
            obj_png_path = objects_dir / f"obj_{mask_id}.png"
            extract_object_png(src_array, mask, obj_png_path)

            # Compute metadata
            meta = _compute_mask_metadata(mask, mask_id)
            objects.append(
                SegmentedObject(
                    mask_id=meta["mask_id"],
                    bbox=meta["bbox"],
                    area_px=meta["area_px"],
                    centroid_px=meta["centroid_px"],
                    object_png_path=obj_png_path,
                )
            )

        # --- Step 4: Combined foreground mask + background mask ---
        combined_fg = _build_combined_foreground_mask(filtered_masks, (h, w))
        background_mask = 255 - combined_fg
        bg_mask_path = masks_dir / "background.png"
        Image.fromarray(background_mask, mode="L").save(bg_mask_path)

        # Save combined foreground mask for inpainting
        fg_mask_path = masks_dir / "foreground_combined.png"
        Image.fromarray(combined_fg, mode="L").save(fg_mask_path)

        # --- Step 5: Inpaint to produce Room_Plate ---
        room_plate_path = await self._submit_inpaint(
            source_image, fg_mask_path, config
        )

        return SceneParseResult(
            room_plate_path=room_plate_path,
            objects=objects,
            background_mask_path=bg_mask_path,
        )

    # ------------------------------------------------------------------
    # ComfyUI workflow submission helpers
    # ------------------------------------------------------------------

    async def _submit_sam(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> list[np.ndarray]:
        """Submit SAM ViT-H workflow and retrieve per-object masks.

        Tries ComfyUI first; if it fails (missing nodes), falls back to
        running SAM locally in Python, then to OpenCV contour detection.
        """
        # Try ComfyUI path first
        try:
            workflow = load_workflow("sam_segment")
            placeholders = {
                "INPUT_IMAGE_PATH": str(source_image).replace("\\", "/"),
                "OUTPUT_DIR": str(self.output_dir / "sam_raw").replace("\\", "/"),
            }
            prompt_id = await self.client.submit_workflow(
                workflow, placeholders=placeholders
            )
            await self.client.wait_for_completion(prompt_id)
            return self._load_sam_output_masks()
        except (ComfyUIError, Exception) as exc:
            logger.warning(
                "ComfyUI SAM failed (%s) — trying local SAM", exc
            )

        # Fallback: run SAM locally via segment_anything
        return await self._run_local_sam(source_image, config)

    async def _run_local_sam(
        self, source_image: Path, config: PhotoPipelineConfig
    ) -> list[np.ndarray]:
        """Run SAM ViT-H locally when ComfyUI nodes unavailable."""
        import asyncio

        try:
            import torch
            from segment_anything import SamAutomaticMaskGenerator, sam_model_registry

            sam_path = self._find_sam_model()
            if sam_path is None:
                logger.warning("SAM model not found — using contour fallback")
                return await self._run_contour_fallback(source_image)

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("Loading SAM ViT-H on %s from %s", device, sam_path)

            def _run():
                sam = sam_model_registry["vit_h"](checkpoint=str(sam_path))
                sam.to(device=device)
                gen = SamAutomaticMaskGenerator(
                    sam,
                    points_per_side=32,
                    pred_iou_thresh=0.86,
                    stability_score_thresh=0.92,
                    min_mask_region_area=100,
                )
                img = np.array(Image.open(source_image).convert("RGB"))
                logger.info("Running SAM automatic mask generation...")
                results = gen.generate(img)
                logger.info("SAM produced %d masks", len(results))
                return [(m["segmentation"].astype(np.uint8) * 255) for m in results]

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _run)

        except ImportError:
            logger.warning("segment_anything not installed — contour fallback")
            return await self._run_contour_fallback(source_image)
        except Exception as exc:
            logger.warning("Local SAM failed (%s) — contour fallback", exc)
            return await self._run_contour_fallback(source_image)

    def _find_sam_model(self) -> Path | None:
        """Search standard locations for SAM ViT-H checkpoint."""
        candidates = [
            Path("C:/Users/JohnM/ComfyUI-Installs/ComfyUI/ComfyUI/models/sams/sam_vit_h_4b8939.pth"),
            Path("models/sams/sam_vit_h_4b8939.pth"),
            Path.home() / ".cache" / "sam" / "sam_vit_h_4b8939.pth",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    async def _run_contour_fallback(self, source_image: Path) -> list[np.ndarray]:
        """Improved contour/color fallback segmentation (no ML models needed)."""
        import asyncio
        import cv2

        def _detect():
            img = cv2.imread(str(source_image))
            if img is None:
                return []
            h, w = img.shape[:2]
            image_area = h * w

            # Method 1: Color-based segmentation via K-means
            pixels = img.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            k = min(6, max(3, int(image_area / 50000)))  # Adaptive k
            _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
            labels = labels.reshape(h, w)

            # Method 2: Edge-aware contours
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)
            edges = cv2.Canny(blurred, 50, 150)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

            masks = []
            min_area = int(0.02 * image_area)  # 2% minimum
            max_area = int(0.40 * image_area)  # 40% maximum

            # Extract masks from color clusters (skip background/largest cluster)
            cluster_areas = [(np.sum(labels == i), i) for i in range(k)]
            cluster_areas.sort(reverse=True)
            # Skip the largest cluster (likely background/walls)
            for area, cluster_id in cluster_areas[1:]:
                if area < min_area or area > max_area:
                    continue
                mask = ((labels == cluster_id).astype(np.uint8)) * 255
                # Clean up with morphology
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
                if np.sum(mask > 0) >= min_area:
                    masks.append(mask)

            # Also add edge-based contours
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area or area > max_area:
                    continue
                mask = np.zeros((h, w), dtype=np.uint8)
                cv2.drawContours(mask, [contour], -1, 255, -1)
                masks.append(mask)

            # Deduplicate overlapping masks (keep larger ones)
            unique_masks = []
            for mask in sorted(masks, key=lambda m: np.sum(m > 0), reverse=True)[:10]:
                # Check IoU with existing masks
                overlap = False
                for existing in unique_masks:
                    intersection = np.sum((mask > 0) & (existing > 0))
                    union = np.sum((mask > 0) | (existing > 0))
                    if union > 0 and intersection / union > 0.5:
                        overlap = True
                        break
                if not overlap:
                    unique_masks.append(mask)

            logger.info("Improved contour fallback found %d regions", len(unique_masks))
            return unique_masks

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _detect)

    def _load_sam_output_masks(self) -> list[np.ndarray]:
        """Load binary masks from SAM's output directory.

        SAM outputs are expected as individual PNG files in the sam_raw/
        subdirectory, where each file is a single-channel mask.

        Returns
        -------
        list[np.ndarray]
            Binary masks as uint8 arrays.
        """
        sam_dir = self.output_dir / "sam_raw"
        if not sam_dir.exists():
            logger.warning("SAM output directory not found: %s", sam_dir)
            return []

        masks: list[np.ndarray] = []
        for mask_file in sorted(sam_dir.glob("*.png")):
            mask_img = Image.open(mask_file).convert("L")
            mask_array = np.array(mask_img)
            # Threshold at 128 to get clean binary mask
            masks.append((mask_array > 128).astype(np.uint8) * 255)

        return masks

    async def _submit_inpaint(
        self,
        source_image: Path,
        mask_path: Path,
        config: PhotoPipelineConfig,
    ) -> Path:
        """Submit Flux.1-Fill inpainting workflow and retrieve Room_Plate.

        Handles failure gracefully: if inpainting fails or produces a
        resolution mismatch, falls back to using the source image directly.

        Parameters
        ----------
        source_image : Path
            Original source image path.
        mask_path : Path
            Combined foreground mask path.
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        Path
            Path to the room plate image (inpainted or source fallback).
        """
        room_plate_path = self.output_dir / "room_plate.png"

        try:
            workflow = load_workflow("flux_inpaint")

            placeholders = {
                "INPUT_IMAGE_PATH": str(source_image).replace("\\", "/"),
                "MASK_PATH": str(mask_path).replace("\\", "/"),
                "OUTPUT_DIR": str(self.output_dir).replace("\\", "/"),
            }

            prompt_id = await self.client.submit_workflow(
                workflow, placeholders=placeholders
            )
            await self.client.wait_for_completion(prompt_id)

            # Retrieve the inpainted image
            retrieved_path = await self.client.get_output_image(
                prompt_id, self.output_dir, filename="room_plate.png"
            )

            # Validate resolution matches source
            src_img = Image.open(source_image)
            inpainted_img = Image.open(retrieved_path)
            if inpainted_img.size != src_img.size:
                logger.warning(
                    "Inpainter resolution mismatch: source=%s, inpainted=%s "
                    "— falling back to source as room plate",
                    src_img.size,
                    inpainted_img.size,
                )
                return self._fallback_room_plate(source_image, room_plate_path)

            return retrieved_path

        except (ComfyUIError, OSError, Exception) as exc:
            logger.warning(
                "Inpainting failed (%s) — using source as room plate",
                exc,
            )
            return self._fallback_room_plate(source_image, room_plate_path)

    # ------------------------------------------------------------------
    # Edge case handlers
    # ------------------------------------------------------------------

    def _build_zero_mask_result(
        self,
        source_image: Path,
        shape: tuple[int, int],
    ) -> SceneParseResult:
        """Build result for the zero-valid-masks edge case.

        Source image becomes the room plate directly; empty object list;
        background mask is all-white (entire image is background).

        Parameters
        ----------
        source_image : Path
            Original source image path.
        shape : tuple[int, int]
            (height, width) of the source image.

        Returns
        -------
        SceneParseResult
            Result with empty objects and source as room plate.
        """
        masks_dir = self.output_dir / "masks"
        masks_dir.mkdir(parents=True, exist_ok=True)

        # Room plate is just the source
        room_plate_path = self.output_dir / "room_plate.png"
        Image.open(source_image).convert("RGB").save(room_plate_path)

        # Background mask is all white (entire image = background)
        bg_mask = np.ones(shape, dtype=np.uint8) * 255
        bg_mask_path = masks_dir / "background.png"
        Image.fromarray(bg_mask, mode="L").save(bg_mask_path)

        return SceneParseResult(
            room_plate_path=room_plate_path,
            objects=[],
            background_mask_path=bg_mask_path,
        )

    def _fallback_room_plate(
        self,
        source_image: Path,
        room_plate_path: Path,
    ) -> Path:
        """Use source image as room plate fallback.

        Parameters
        ----------
        source_image : Path
            Original source image.
        room_plate_path : Path
            Destination path for the room plate copy.

        Returns
        -------
        Path
            Path to the copied/saved room plate.
        """
        room_plate_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(source_image).convert("RGB")
        img.save(room_plate_path)
        return room_plate_path
