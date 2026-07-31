"""Object Isolator — SAM-based segmentation producing RGBA Object_PNGs.

Segments the approved Scene_Canon using SAM ViT-H to produce one
RGBA Object_PNG per object on a transparent background. Each segment
maps to a Brief manifest UUID.

Requirements:
- Req 9.1: Segment Canon using SAM → one RGBA Object_PNG per object
- Req 9.2: Each Object_PNG corresponds to exactly one Brief manifest UUID
- Req 9.3: Detect empty/broken segmentations (<1% coverage) automatically
- Req 9.4: Object_PNG used directly as mesh generation input (raw segmentation for MVP)
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from src.unified_pipeline.models import ManifestObject, ObjectCanon

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────────

COMFYUI_URL = "http://127.0.0.1:8188"
SAM_TIMEOUT_S = 120
MIN_COVERAGE_THRESHOLD = 0.01  # 1% of image pixels
OUTPUT_BASE_DIR = Path("output/objects")


# ─── Errors ─────────────────────────────────────────────────────────────────────


class SegmentationError(Exception):
    """Raised when SAM segmentation fails."""


class QualityGateError(Exception):
    """Raised when a mask fails the quality gate."""


# ─── SAM ComfyUI Workflow Builder ───────────────────────────────────────────────


def _build_sam_workflow(image_filename: str) -> dict[str, Any]:
    """Build a ComfyUI workflow for SAM ViT-H auto-segmentation.

    This workflow:
    1. Loads the input image
    2. Loads SAM ViT-H model
    3. Runs auto-segmentation (no point/box prompts — full scene)
    4. Returns all masks as individual segments

    Args:
        image_filename: Filename of the image in ComfyUI's input folder.

    Returns:
        ComfyUI workflow dict ready for submission.
    """
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {
                "image": image_filename,
            },
        },
        "2": {
            "class_type": "SAMModelLoader (Segment Anything)",
            "inputs": {
                "model_name": "sam_vit_h_4b8939.pth",
            },
        },
        "3": {
            "class_type": "SAMAutoSegmentation",
            "inputs": {
                "sam_model": ["2", 0],
                "image": ["1", 0],
                "points_per_side": 32,
                "pred_iou_thresh": 0.88,
                "stability_score_thresh": 0.95,
                "min_mask_region_area": 100,
            },
        },
        "4": {
            "class_type": "PreviewImage",
            "inputs": {
                "images": ["3", 0],
            },
        },
    }


# ─── Mask Matching Heuristics ───────────────────────────────────────────────────


def _compute_mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    """Compute the centroid (center of mass) of a binary mask.

    Args:
        mask: 2D boolean/uint8 array representing the mask.

    Returns:
        (y_normalized, x_normalized) centroid in [0, 1] range.
    """
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return (0.5, 0.5)
    h, w = mask.shape
    return (float(ys.mean()) / h, float(xs.mean()) / w)


def _compute_mask_area_fraction(mask: np.ndarray) -> float:
    """Compute the fraction of the image covered by this mask.

    Args:
        mask: 2D boolean/uint8 array.

    Returns:
        Fraction in [0, 1] of total image pixels that are non-zero.
    """
    total = mask.shape[0] * mask.shape[1]
    if total == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / total


def _compute_mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Compute bounding box (y_min, x_min, y_max, x_max) of a mask.

    Args:
        mask: 2D boolean/uint8 array.

    Returns:
        (y_min, x_min, y_max, x_max) bounding box of non-zero pixels.
        Returns (0, 0, 0, 0) for empty masks.
    """
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return (0, 0, 0, 0)
    return (int(ys.min()), int(xs.min()), int(ys.max()), int(xs.max()))


def _match_masks_to_manifest(
    masks: list[np.ndarray],
    manifest: list[ManifestObject],
    image_shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    """Match segmentation masks to manifest objects using position/size heuristics.

    Strategy:
    - Sort masks by area (largest first — architectural elements tend to be big).
    - Sort manifest objects: architectural first, then by position hints.
    - Greedy assignment: largest unmatched mask → next unmatched manifest object,
      preferring architectural objects for large masks.

    For MVP, this uses a simple area-ranked assignment. Post-MVP, semantic
    matching via vision models would improve accuracy.

    Args:
        masks: List of 2D binary masks from SAM.
        manifest: List of ManifestObject from the Brief.
        image_shape: (height, width) of the source image.

    Returns:
        Dict mapping manifest object UUID → best-matching mask.
        Objects without a matching mask are omitted.
    """
    if not masks or not manifest:
        return {}

    # Compute properties for each mask
    mask_info: list[dict[str, Any]] = []
    for i, mask in enumerate(masks):
        area = _compute_mask_area_fraction(mask)
        centroid = _compute_mask_centroid(mask)
        bbox = _compute_mask_bbox(mask)
        mask_info.append({
            "index": i,
            "area": area,
            "centroid": centroid,
            "bbox": bbox,
            "mask": mask,
        })

    # Sort masks by area descending (largest segments first)
    mask_info.sort(key=lambda m: m["area"], reverse=True)

    # Separate architectural vs non-architectural manifest objects
    arch_objects = [o for o in manifest if o.is_architectural]
    prop_objects = [o for o in manifest if not o.is_architectural]

    # Ordered assignment: architectural objects get largest masks first
    ordered_objects = arch_objects + prop_objects

    result: dict[str, np.ndarray] = {}
    used_mask_indices: set[int] = set()

    for obj in ordered_objects:
        # Find the largest unused mask for this object
        for info in mask_info:
            if info["index"] not in used_mask_indices:
                result[obj.id] = info["mask"]
                used_mask_indices.add(info["index"])
                break

    return result


# ─── Quality Gate ───────────────────────────────────────────────────────────────


def quality_gate(mask: np.ndarray, object_id: str) -> bool:
    """Check if a mask meets minimum quality requirements.

    Req 9.3: Detect empty/broken segmentations (<1% coverage) automatically.

    Args:
        mask: 2D binary mask array.
        object_id: UUID of the object (for logging).

    Returns:
        True if the mask passes (coverage >= 1%), False otherwise.
    """
    coverage = _compute_mask_area_fraction(mask)

    if coverage < MIN_COVERAGE_THRESHOLD:
        logger.warning(
            "Quality gate FAILED for object %s: coverage %.4f%% < %.1f%% threshold",
            object_id,
            coverage * 100,
            MIN_COVERAGE_THRESHOLD * 100,
        )
        return False

    logger.info(
        "Quality gate PASSED for object %s: coverage %.2f%%",
        object_id,
        coverage * 100,
    )
    return True


# ─── RGBA PNG Application ───────────────────────────────────────────────────────


def apply_mask_to_image(
    image: np.ndarray,
    mask: np.ndarray,
    output_path: Path,
) -> Path:
    """Apply a binary mask to an RGB image, producing an RGBA PNG.

    The output has:
    - RGB channels from the original image where mask is True
    - Alpha channel = 255 where mask is True, 0 elsewhere
    - Transparent background where mask is False

    Req 9.1: Produce one RGBA Object_PNG per object on transparent background.

    Args:
        image: Source RGB image as (H, W, 3) uint8 numpy array.
        mask: Binary mask as (H, W) boolean or uint8 array.
        output_path: Where to save the resulting RGBA PNG.

    Returns:
        Path to the saved RGBA PNG file.
    """
    from PIL import Image

    h, w = image.shape[:2]
    # Ensure mask matches image dimensions
    if mask.shape != (h, w):
        # Resize mask to match image
        from PIL import Image as PILImage

        mask_img = PILImage.fromarray((mask > 0).astype(np.uint8) * 255)
        mask_img = mask_img.resize((w, h), PILImage.NEAREST)
        mask = np.array(mask_img) > 0

    # Create RGBA image
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    mask_bool = mask > 0
    rgba[mask_bool, :3] = image[mask_bool, :3]
    rgba[mask_bool, 3] = 255  # Full opacity where mask is True

    # Save as PNG
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(rgba, mode="RGBA")
    img.save(str(output_path), format="PNG")

    logger.info("Saved Object_PNG: %s", output_path)
    return output_path


# ─── Main ObjectIsolator Class ──────────────────────────────────────────────────


class ObjectIsolator:
    """Segments Scene_Canon into individual RGBA Object_PNGs using SAM.

    This class orchestrates:
    1. Running SAM auto-segmentation via ComfyUI
    2. Matching masks to Brief manifest objects by UUID
    3. Applying quality gates (reject <1% coverage)
    4. Producing RGBA PNGs on transparent backgrounds

    Req 9.1: Segment Canon using SAM → one RGBA Object_PNG per object.
    Req 9.2: Each Object_PNG corresponds to exactly one Brief manifest UUID.
    Req 9.3: Detect empty/broken segmentations (<1% coverage).
    Req 9.4: Object_PNG used directly as mesh generation input (raw segmentation).

    Usage:
        isolator = ObjectIsolator()
        results = await isolator.segment(canon_path, manifest, session_id="abc123")
        # results: list[ObjectCanon] — one per successfully isolated object
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        comfyui_url: str = COMFYUI_URL,
        timeout_s: int = SAM_TIMEOUT_S,
    ) -> None:
        """Initialize the ObjectIsolator.

        Args:
            output_dir: Base directory for Object_PNG output.
                Defaults to output/objects/.
            comfyui_url: ComfyUI server URL for SAM inference.
            timeout_s: Timeout for SAM workflow in seconds.
        """
        self._output_dir = output_dir or OUTPUT_BASE_DIR
        self._comfyui_url = comfyui_url
        self._timeout_s = timeout_s

    async def segment(
        self,
        canon_path: str,
        manifest: list[ManifestObject],
        *,
        session_id: str = "default",
    ) -> list[ObjectCanon]:
        """Segment the Canon image and produce RGBA Object_PNGs.

        Req 9.1: SAM segmentation → RGBA Object_PNGs.
        Req 9.2: Each Object_PNG maps to one Brief manifest UUID.
        Req 9.3: Reject masks with <1% coverage.
        Req 9.4: Raw segmentation output is the Object_Canon (no inpainting).

        Args:
            canon_path: Path to the approved Scene_Canon image.
            manifest: List of ManifestObject from the Brief.
            session_id: Session identifier for organizing output.

        Returns:
            List of ObjectCanon, one per successfully isolated object.
            Objects that fail the quality gate are omitted with a warning.

        Raises:
            SegmentationError: If SAM segmentation completely fails.
        """
        from PIL import Image

        canon_file = Path(canon_path)
        if not canon_file.exists():
            raise SegmentationError(f"Canon image not found: {canon_path}")

        # Load the source image
        source_image = np.array(Image.open(canon_file).convert("RGB"))
        image_h, image_w = source_image.shape[:2]
        logger.info(
            "Starting object isolation: %s (%dx%d), %d manifest objects",
            canon_path,
            image_w,
            image_h,
            len(manifest),
        )

        # Run SAM segmentation
        masks = await self._run_sam(canon_path)
        logger.info("SAM returned %d masks", len(masks))

        if not masks:
            raise SegmentationError(
                "SAM segmentation returned no masks. "
                "Check that SAM ViT-H model is loaded in ComfyUI."
            )

        # Match masks to manifest objects
        uuid_to_mask = _match_masks_to_manifest(
            masks, manifest, (image_h, image_w)
        )
        logger.info(
            "Matched %d masks to %d manifest objects",
            len(uuid_to_mask),
            len(manifest),
        )

        # Apply masks and produce Object_PNGs
        session_dir = self._output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        results: list[ObjectCanon] = []
        for obj in manifest:
            if obj.id not in uuid_to_mask:
                logger.warning(
                    "No mask matched for object %s (%s) — skipping",
                    obj.id,
                    obj.name,
                )
                continue

            mask = uuid_to_mask[obj.id]

            # Quality gate (Req 9.3)
            if not quality_gate(mask, obj.id):
                logger.warning(
                    "Object %s (%s) failed quality gate — skipping",
                    obj.id,
                    obj.name,
                )
                continue

            # Apply mask to create RGBA PNG (Req 9.1)
            output_path = session_dir / f"{obj.id}.png"
            apply_mask_to_image(source_image, mask, output_path)

            # Compute coverage for metadata
            coverage = _compute_mask_area_fraction(mask)

            # Create ObjectCanon (Req 9.4: raw segmentation = Object_Canon)
            object_canon = ObjectCanon(
                object_id=obj.id,
                object_name=obj.name,
                image_path=str(output_path),
                mask_coverage=coverage,
                approved=False,
                provenance="raw_segmentation",
            )
            results.append(object_canon)
            logger.info(
                "Isolated object %s (%s): coverage=%.2f%%",
                obj.id,
                obj.name,
                coverage * 100,
            )

        logger.info(
            "Object isolation complete: %d/%d objects isolated",
            len(results),
            len(manifest),
        )
        return results

    async def _run_sam(self, image_path: str) -> list[np.ndarray]:
        """Run SAM auto-segmentation on the Canon image via ComfyUI.

        Calls the SAM ViT-H workflow through ComfyUI, waits for completion,
        and returns a list of binary masks.

        Args:
            image_path: Local path to the image to segment.

        Returns:
            List of 2D binary numpy arrays (one per detected segment).

        Raises:
            SegmentationError: If SAM workflow fails or times out.
        """
        from src.photo_pipeline.comfyui_client import (
            ComfyUIClient,
            ComfyUIError,
            ComfyUITimeoutError,
        )

        client = ComfyUIClient(
            base_url=self._comfyui_url,
            timeout_s=self._timeout_s,
        )

        # Upload image to ComfyUI
        try:
            uploaded_filename = await client.upload_image(Path(image_path))
        except ComfyUIError as exc:
            raise SegmentationError(
                f"Failed to upload Canon to ComfyUI for SAM: {exc}"
            ) from exc

        # Build and submit SAM workflow
        workflow = _build_sam_workflow(uploaded_filename)

        try:
            prompt_id = await client.submit_workflow(workflow)
            await client.wait_for_completion(
                prompt_id, timeout_s=self._timeout_s
            )
        except ComfyUITimeoutError as exc:
            raise SegmentationError(
                f"SAM segmentation timed out after {self._timeout_s}s: {exc}"
            ) from exc
        except ComfyUIError as exc:
            raise SegmentationError(
                f"SAM segmentation failed: {exc}"
            ) from exc

        # Retrieve masks from ComfyUI output
        # SAM outputs composite preview images; extract individual masks
        # via the history/output API
        masks = await self._extract_masks_from_output(client, prompt_id)
        return masks

    async def _extract_masks_from_output(
        self,
        client: Any,
        prompt_id: str,
    ) -> list[np.ndarray]:
        """Extract individual binary masks from SAM ComfyUI output.

        ComfyUI SAM nodes typically output a combined mask image or
        multiple mask layers. This method retrieves and separates them.

        For the MVP, if ComfyUI returns a labeled composite, we
        separate unique label regions into individual masks.

        Args:
            client: ComfyUIClient instance.
            prompt_id: The completed workflow prompt_id.

        Returns:
            List of 2D binary numpy arrays.
        """
        import httpx
        from PIL import Image

        # Query ComfyUI history for this prompt's outputs
        try:
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                resp = await http_client.get(
                    f"{self._comfyui_url}/history/{prompt_id}"
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Failed to get history for prompt %s: %d",
                        prompt_id,
                        resp.status_code,
                    )
                    return []

                history = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Error fetching SAM output history: %s", exc)
            return []

        # Navigate ComfyUI history structure to find mask outputs
        prompt_data = history.get(prompt_id, {})
        outputs = prompt_data.get("outputs", {})

        masks: list[np.ndarray] = []

        # Look for mask outputs from the SAM node (node "3")
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                for img_info in node_output["images"]:
                    filename = img_info.get("filename", "")
                    subfolder = img_info.get("subfolder", "")
                    img_type = img_info.get("type", "output")

                    # Download the mask image from ComfyUI
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as http_client:
                            params = {
                                "filename": filename,
                                "subfolder": subfolder,
                                "type": img_type,
                            }
                            resp = await http_client.get(
                                f"{self._comfyui_url}/view",
                                params=params,
                            )
                            if resp.status_code == 200:
                                import io

                                img = Image.open(io.BytesIO(resp.content))
                                mask_array = np.array(img.convert("L"))
                                # Separate unique regions from composite mask
                                region_masks = self._separate_regions(
                                    mask_array
                                )
                                masks.extend(region_masks)
                    except (httpx.HTTPError, OSError) as exc:
                        logger.warning(
                            "Error downloading mask image %s: %s",
                            filename,
                            exc,
                        )

        return masks

    def _separate_regions(self, label_image: np.ndarray) -> list[np.ndarray]:
        """Separate a label/composite mask into individual binary masks.

        Handles two cases:
        1. Binary mask (0/255) — returns as a single mask.
        2. Multi-label composite — each unique non-zero value is a region.

        Args:
            label_image: 2D grayscale array from SAM output.

        Returns:
            List of 2D binary masks (uint8, 0 or 255).
        """
        unique_values = np.unique(label_image)
        # Remove background (0)
        unique_values = unique_values[unique_values > 0]

        if len(unique_values) == 0:
            return []

        # If it's a simple binary mask (only one non-zero value)
        if len(unique_values) == 1:
            binary = (label_image > 0).astype(np.uint8) * 255
            return [binary]

        # Multi-label: separate each region
        masks: list[np.ndarray] = []
        for val in unique_values:
            region = (label_image == val).astype(np.uint8) * 255
            # Only include regions with meaningful area
            area_frac = np.count_nonzero(region) / (
                region.shape[0] * region.shape[1]
            )
            if area_frac >= MIN_COVERAGE_THRESHOLD:
                masks.append(region)

        return masks

    def complete_inpainting(self, object_canon: ObjectCanon) -> ObjectCanon:
        """Complete hidden portions of an object via inpainting (POST-MVP STUB).

        This method is defined for interface completeness but is not
        implemented in the marathon MVP. Raw segmentation output is used
        directly as Object_Canon per Req 9.4.

        Post-MVP implementation will:
        - Use FLUX controlled inpainting to complete occluded portions
        - Apply corner purity and subject coverage checks (Req 9.6)
        - Offer user choice between original and completed version (Req 9.7)
        - Record provenance (original vs inpainted regions) (Req 9.8)

        Args:
            object_canon: The raw segmentation ObjectCanon to complete.

        Returns:
            The same ObjectCanon unchanged (stub — no inpainting applied).
        """
        logger.info(
            "Inpainting completion STUBBED for MVP — returning raw "
            "segmentation for object %s (%s)",
            object_canon.object_id,
            object_canon.object_name,
        )
        # Post-MVP: implement FLUX inpainting here
        return object_canon
