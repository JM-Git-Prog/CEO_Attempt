"""Room Plate Generator — Canon with objects inpainted out via FLUX.

Produces a clean Room_Plate image by inpainting all object regions from
the approved Scene_Canon using FLUX Fill via ComfyUI. The Room_Plate is
used as the texture source for room shell reconstruction.

Fallback: if inpainting fails, the Canon image is used directly (degraded
but usable for shell texturing).

Requirements: 16.2 (Room_Plate for shell texturing — Canon with objects removed)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)
from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)

# Output directory structure
DEFAULT_OUTPUT_DIR = Path("output/room_plates")

# Inpainting workflow parameters
INPAINT_TIMEOUT_S = 120


class RoomPlateGenerator:
    """Generates a Room_Plate by inpainting objects out of the Scene_Canon.

    The Room_Plate is the Canon image with all objects removed (inpainted
    with room background), used as the texture source for the room shell
    mesh. Uses FLUX Fill via ComfyUI for high-quality background fill.

    Fallback behavior: if FLUX inpainting fails for any reason (ComfyUI
    unavailable, workflow error, timeout, resolution mismatch), the Canon
    image is used directly as a degraded but usable Room_Plate.

    Parameters
    ----------
    comfyui_client : ComfyUIClient, optional
        Existing ComfyUI client instance. If None, creates a new one.
    output_dir : Path, optional
        Base directory for room plate output files.
    """

    def __init__(
        self,
        comfyui_client: ComfyUIClient | None = None,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        self._client = comfyui_client or ComfyUIClient(
            timeout_s=INPAINT_TIMEOUT_S,
            poll_interval_s=0.75,
        )
        self._output_dir = output_dir

    async def generate(
        self,
        canon_path: str,
        object_masks: list[dict],
        session_id: str,
    ) -> str:
        """Generate a Room_Plate from Canon with all objects inpainted out.

        Combines all object masks into a single inpaint mask (white where
        objects are), then runs FLUX Fill inpainting to replace object regions
        with plausible room background.

        Parameters
        ----------
        canon_path : str
            Path to the approved Scene_Canon image (the source to inpaint).
        object_masks : list[dict]
            List of object mask descriptors. Each dict must contain either:
            - "mask_path": str — path to a grayscale mask PNG (white=object)
            - "mask_array": np.ndarray — binary mask array (nonzero=object)
            At least one mask must be provided for inpainting to proceed.
        session_id : str
            Session identifier for organizing output files.

        Returns
        -------
        str
            Path to the generated Room_Plate image. On success this is the
            inpainted result; on failure this is the Canon image copied as
            a degraded fallback.
        """
        # Validate inputs
        canon = Path(canon_path)
        if not canon.exists():
            raise FileNotFoundError(
                f"Canon image not found: {canon_path}"
            )

        # Prepare output directory
        session_dir = self._output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        room_plate_path = session_dir / "room_plate.png"

        # Handle zero masks — Canon IS the room plate
        if not object_masks:
            logger.info(
                "No object masks provided — Canon is the Room_Plate"
            )
            return str(self._fallback_copy_canon(canon, room_plate_path))

        # Build combined inpaint mask from all object masks
        mask_path = self._build_inpaint_mask(object_masks, session_dir, canon)

        # Run FLUX inpainting
        result_path = await self._run_flux_inpaint(
            canon, mask_path, room_plate_path
        )

        return str(result_path)

    def _build_inpaint_mask(
        self,
        object_masks: list[dict],
        session_dir: Path,
        canon_path: Path,
    ) -> Path:
        """Build a combined inpaint mask from all object masks.

        Combines all provided object masks into a single binary mask where
        white (255) indicates regions to inpaint (object locations) and
        black (0) indicates regions to preserve (room background).

        Parameters
        ----------
        object_masks : list[dict]
            List of mask descriptors with "mask_path" or "mask_array" keys.
        session_dir : Path
            Output directory for saving the combined mask.
        canon_path : Path
            Path to Canon image (for resolving output dimensions).

        Returns
        -------
        Path
            Path to the saved combined inpaint mask PNG.
        """
        # Get target dimensions from Canon image
        canon_img = Image.open(canon_path)
        width, height = canon_img.size

        # Initialize combined mask (black = keep, white = inpaint)
        combined = np.zeros((height, width), dtype=np.uint8)

        for mask_desc in object_masks:
            mask_array = self._load_mask(mask_desc, (height, width))
            if mask_array is not None:
                # Union: white where any object exists
                combined = np.maximum(
                    combined, (mask_array > 0).astype(np.uint8) * 255
                )

        # Validate: at least some pixels are marked for inpainting
        inpaint_coverage = np.count_nonzero(combined) / (height * width)
        if inpaint_coverage < 0.001:
            logger.warning(
                "Combined inpaint mask has <0.1%% coverage (%.4f) — "
                "masks may be empty or invalid",
                inpaint_coverage,
            )
        elif inpaint_coverage > 0.90:
            logger.warning(
                "Combined inpaint mask covers >90%% of image (%.2f) — "
                "result quality may be poor",
                inpaint_coverage,
            )
        else:
            logger.info(
                "Combined inpaint mask: %.1f%% coverage (%d×%d)",
                inpaint_coverage * 100,
                width,
                height,
            )

        # Save combined mask
        mask_output_path = session_dir / "inpaint_mask_combined.png"
        Image.fromarray(combined, mode="L").save(mask_output_path)

        return mask_output_path

    async def _run_flux_inpaint(
        self,
        canon_path: Path,
        mask_path: Path,
        output_path: Path,
    ) -> Path:
        """Run FLUX Fill inpainting via ComfyUI.

        Submits the flux_inpaint workflow with the Canon image and combined
        mask, waits for completion, and retrieves the inpainted result.

        On any failure (ComfyUI unavailable, workflow error, timeout,
        resolution mismatch), falls back to using the Canon image directly.

        Parameters
        ----------
        canon_path : Path
            Path to the Canon image (source for inpainting).
        mask_path : Path
            Path to the combined inpaint mask (white = inpaint regions).
        output_path : Path
            Desired output path for the room plate image.

        Returns
        -------
        Path
            Path to the room plate image (inpainted or fallback).
        """
        # Check ComfyUI availability
        if not await self._client.health_check():
            logger.warning(
                "ComfyUI unavailable — falling back to Canon as Room_Plate"
            )
            return self._fallback_copy_canon(canon_path, output_path)

        try:
            # Upload images to ComfyUI input folder
            canon_filename = await self._client.upload_image(canon_path)
            mask_filename = await self._client.upload_image(mask_path)

            # Build inpainting workflow
            workflow = self._build_inpaint_workflow(
                canon_filename, mask_filename
            )

            # Submit and wait
            prompt_id = await self._client.submit_workflow(
                workflow,
                client_id="room-plate-inpaint",
                timeout_s=INPAINT_TIMEOUT_S,
            )

            await self._client.wait_for_completion(
                prompt_id, timeout_s=INPAINT_TIMEOUT_S
            )

            # Retrieve output image
            retrieved_path = await self._client.get_output_image(
                prompt_id=prompt_id,
                output_dir=output_path.parent,
                filename=output_path.name,
            )

            # Validate resolution matches Canon
            canon_img = Image.open(canon_path)
            result_img = Image.open(retrieved_path)
            if result_img.size != canon_img.size:
                logger.warning(
                    "Inpainted Room_Plate resolution mismatch: "
                    "canon=%s, result=%s — falling back to Canon",
                    canon_img.size,
                    result_img.size,
                )
                return self._fallback_copy_canon(canon_path, output_path)

            logger.info(
                "Room_Plate generated successfully: %s", retrieved_path
            )
            return retrieved_path

        except (ComfyUIError, ComfyUITimeoutError) as exc:
            logger.warning(
                "FLUX inpainting failed (%s) — falling back to Canon "
                "as Room_Plate",
                exc,
            )
            return self._fallback_copy_canon(canon_path, output_path)
        except (OSError, Exception) as exc:
            logger.warning(
                "Unexpected error during inpainting (%s) — falling back "
                "to Canon as Room_Plate",
                exc,
            )
            return self._fallback_copy_canon(canon_path, output_path)

    # ─── Internal Helpers ──────────────────────────────────────────────────

    def _build_inpaint_workflow(
        self,
        canon_filename: str,
        mask_filename: str,
    ) -> dict[str, Any]:
        """Build a FLUX Fill inpainting workflow for ComfyUI.

        Uses the same node structure as the existing flux_inpaint.json
        workflow template but with uploaded filenames instead of
        path placeholders.

        Parameters
        ----------
        canon_filename : str
            Filename of the Canon image in ComfyUI's input folder
            (returned by upload_image).
        mask_filename : str
            Filename of the mask in ComfyUI's input folder.

        Returns
        -------
        dict
            ComfyUI workflow graph ready for submission.
        """
        return {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": canon_filename},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": mask_filename},
            },
            "3": {
                "class_type": "FluxFillModelLoader",
                "inputs": {
                    "model_name": "flux1-fill-dev.safetensors",
                    "dtype": "float16",
                },
            },
            "4": {
                "class_type": "FluxFillInpaint",
                "inputs": {
                    "model": ["3", 0],
                    "image": ["1", 0],
                    "mask": ["2", 0],
                    "steps": 20,
                    "cfg_scale": 7.0,
                    "denoise_strength": 1.0,
                    "seed": 42,
                },
            },
            "5": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["4", 0],
                    "filename_prefix": "room_plate",
                },
            },
        }

    def _load_mask(
        self,
        mask_desc: dict,
        target_shape: tuple[int, int],
    ) -> np.ndarray | None:
        """Load a single mask from a descriptor dict.

        Supports two formats:
        - "mask_path": path to a grayscale PNG (loaded and thresholded)
        - "mask_array": numpy array (used directly)

        Parameters
        ----------
        mask_desc : dict
            Mask descriptor with either "mask_path" or "mask_array".
        target_shape : tuple[int, int]
            Expected (height, width) for validation.

        Returns
        -------
        np.ndarray | None
            Binary mask array (uint8, nonzero=object), or None if invalid.
        """
        if "mask_array" in mask_desc:
            arr = mask_desc["mask_array"]
            if isinstance(arr, np.ndarray):
                # Resize if dimensions don't match
                if arr.shape[:2] != target_shape:
                    logger.warning(
                        "Mask array shape %s != target %s — resizing",
                        arr.shape[:2],
                        target_shape,
                    )
                    mask_img = Image.fromarray(
                        (arr > 0).astype(np.uint8) * 255, mode="L"
                    )
                    mask_img = mask_img.resize(
                        (target_shape[1], target_shape[0]),
                        Image.Resampling.NEAREST,
                    )
                    return np.array(mask_img)
                return (arr > 0).astype(np.uint8) * 255
            logger.warning("mask_array is not ndarray — skipping")
            return None

        if "mask_path" in mask_desc:
            mask_file = Path(mask_desc["mask_path"])
            if not mask_file.exists():
                logger.warning("Mask file not found: %s — skipping", mask_file)
                return None
            try:
                mask_img = Image.open(mask_file).convert("L")
                # Resize if dimensions don't match
                if mask_img.size != (target_shape[1], target_shape[0]):
                    logger.warning(
                        "Mask %s size %s != target (%d, %d) — resizing",
                        mask_file.name,
                        mask_img.size,
                        target_shape[1],
                        target_shape[0],
                    )
                    mask_img = mask_img.resize(
                        (target_shape[1], target_shape[0]),
                        Image.Resampling.NEAREST,
                    )
                # Threshold at 128 to produce clean binary mask
                arr = np.array(mask_img)
                return (arr > 128).astype(np.uint8) * 255
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Failed to load mask %s: %s — skipping", mask_file, exc
                )
                return None

        logger.warning(
            "Mask descriptor missing both 'mask_path' and 'mask_array' — "
            "skipping: %s",
            mask_desc,
        )
        return None

    def _fallback_copy_canon(self, canon_path: Path, output_path: Path) -> Path:
        """Copy Canon image as a degraded Room_Plate fallback.

        When FLUX inpainting cannot run, the Canon image itself is used
        as the room plate. Objects remain visible in the texture, which is
        degraded but usable for shell reconstruction.

        Parameters
        ----------
        canon_path : Path
            Path to the Canon image.
        output_path : Path
            Destination for the room plate copy.

        Returns
        -------
        Path
            The output_path with the Canon image saved as Room_Plate.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(canon_path).convert("RGB")
        img.save(output_path)
        logger.info(
            "Room_Plate fallback: Canon copied to %s (objects not removed)",
            output_path,
        )
        return output_path
