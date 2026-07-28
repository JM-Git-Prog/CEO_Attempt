"""Depth Estimator — MoGe-2 metric depth estimation via ComfyUI.

This module implements the depth estimation pipeline stage: submitting the
MoGe-2 workflow to ComfyUI, retrieving the metric depth map, validating it,
deriving surface normals via finite differences, and applying the flat-floor
fallback heuristic when depth data is too noisy.

Pure computation functions (normal map derivation, validation, fallback) are
separated from ComfyUI orchestration for independent testability.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
)
from src.photo_pipeline.models import (
    DepthResult,
    PhotoPipelineConfig,
)
from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Flat-floor fallback parameters
_FALLBACK_DEPTH_M = 4.0
_FALLBACK_HEIGHT_M = 2.7

# Threshold for triggering flat-floor fallback
_INVALID_PIXEL_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Pure helper functions (testable without ComfyUI)
# ---------------------------------------------------------------------------


def validate_depth_map(depth_map: np.ndarray) -> float:
    """Compute the ratio of valid pixels in a depth map.

    A pixel is valid if its depth value is positive, finite, and non-zero.
    Invalid pixels include: 0.0, negative values, inf, nan.

    Parameters
    ----------
    depth_map : np.ndarray
        2D float32 array of depth values (meters).

    Returns
    -------
    float
        Ratio of valid pixels to total pixels (0.0 to 1.0).
    """
    total = depth_map.size
    if total == 0:
        return 0.0

    valid_mask = np.isfinite(depth_map) & (depth_map > 0.0)
    valid_count = int(np.count_nonzero(valid_mask))
    return valid_count / total


def compute_normals_from_depth(depth_map: np.ndarray) -> np.ndarray:
    """Derive a normal map from depth gradients using finite differences.

    Computes surface normals by taking horizontal (dz/dx) and vertical (dz/dy)
    differences, then constructing and normalizing the normal vector at each pixel.

    Normal formula per pixel: normalize([-dz/dx, -dz/dy, 1.0])

    Parameters
    ----------
    depth_map : np.ndarray
        2D float32 array of depth values (meters). Shape (H, W).

    Returns
    -------
    np.ndarray
        Normal map of shape (H, W, 3) with unit-length vectors at each pixel.
        Normals point toward the camera (positive Z component).
    """
    h, w = depth_map.shape[:2]

    # Compute finite differences for gradients
    # dz/dx: horizontal gradient (central differences where possible)
    dz_dx = np.zeros_like(depth_map)
    dz_dx[:, 1:-1] = (depth_map[:, 2:] - depth_map[:, :-2]) / 2.0
    dz_dx[:, 0] = depth_map[:, 1] - depth_map[:, 0]
    dz_dx[:, -1] = depth_map[:, -1] - depth_map[:, -2]

    # dz/dy: vertical gradient (central differences where possible)
    dz_dy = np.zeros_like(depth_map)
    dz_dy[1:-1, :] = (depth_map[2:, :] - depth_map[:-2, :]) / 2.0
    dz_dy[0, :] = depth_map[1, :] - depth_map[0, :]
    dz_dy[-1, :] = depth_map[-1, :] - depth_map[-2, :]

    # Build normal vectors: [-dz/dx, -dz/dy, 1.0]
    normals = np.zeros((h, w, 3), dtype=np.float32)
    normals[:, :, 0] = -dz_dx
    normals[:, :, 1] = -dz_dy
    normals[:, :, 2] = 1.0

    # Normalize to unit length
    magnitudes = np.linalg.norm(normals, axis=2, keepdims=True)
    # Avoid division by zero (shouldn't happen with z=1, but guard anyway)
    magnitudes = np.maximum(magnitudes, 1e-8)
    normals = normals / magnitudes

    return normals


def create_flat_floor_depth_map(
    image_height: int,
    image_width: int,
) -> np.ndarray:
    """Create a flat-floor fallback depth map.

    When the MoGe-2 depth map is too noisy (>50% invalid pixels), this
    produces a uniform depth map at 4.0m everywhere.

    Parameters
    ----------
    image_height : int
        Height of the source image in pixels.
    image_width : int
        Width of the source image in pixels.

    Returns
    -------
    np.ndarray
        Uniform float32 depth map filled with _FALLBACK_DEPTH_M (4.0m).
    """
    return np.full(
        (image_height, image_width), _FALLBACK_DEPTH_M, dtype=np.float32
    )


def create_flat_normals(
    image_height: int,
    image_width: int,
) -> np.ndarray:
    """Create a flat normal map for the fallback case.

    All normals point directly toward the camera: [0, 0, 1].

    Parameters
    ----------
    image_height : int
        Height in pixels.
    image_width : int
        Width in pixels.

    Returns
    -------
    np.ndarray
        Normal map of shape (H, W, 3) with all normals = [0, 0, 1].
    """
    normals = np.zeros((image_height, image_width, 3), dtype=np.float32)
    normals[:, :, 2] = 1.0
    return normals


def get_depth_range(depth_map: np.ndarray) -> tuple[float, float]:
    """Compute min and max depth of valid pixels.

    Parameters
    ----------
    depth_map : np.ndarray
        2D float32 array of depth values.

    Returns
    -------
    tuple[float, float]
        (min_depth, max_depth) of valid pixels. Returns (0.0, 0.0) if no
        valid pixels exist.
    """
    valid_mask = np.isfinite(depth_map) & (depth_map > 0.0)
    valid_values = depth_map[valid_mask]
    if valid_values.size == 0:
        return (0.0, 0.0)
    return (float(valid_values.min()), float(valid_values.max()))


# ---------------------------------------------------------------------------
# DepthEstimator class — orchestrates ComfyUI calls + delegates to helpers
# ---------------------------------------------------------------------------


class DepthEstimator:
    """Produces metric depth via MoGe-2 and derives normal maps.

    Submits the MoGe-2 depth estimation workflow to ComfyUI, validates the
    output, computes surface normals from depth gradients, and applies
    the flat-floor fallback heuristic when depth data is unreliable.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for this session's depth artifacts.
    """

    def __init__(self, client: ComfyUIClient, output_dir: Path) -> None:
        self.client = client
        self.output_dir = output_dir

    async def estimate(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> DepthResult:
        """Run the depth estimation pipeline.

        1. Submit MoGe-2 workflow to ComfyUI
        2. Retrieve depth map as float32 numpy array
        3. Validate depth map (compute valid pixel ratio)
        4. If >50% invalid: apply flat-floor fallback
        5. Derive normal map from depth gradients
        6. Save depth_map.npy and normal_map.npy
        7. Return DepthResult

        Parameters
        ----------
        source_image : Path
            Path to the source RGB image (JPEG or PNG).
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        DepthResult
            Structured result with paths, valid_pixel_ratio, depth_range.
        """
        # Ensure output directory exists
        depth_dir = self.output_dir / "depth"
        depth_dir.mkdir(parents=True, exist_ok=True)

        # Get source image dimensions for fallback
        src_img = Image.open(source_image)
        img_width, img_height = src_img.size
        src_img.close()

        # Submit MoGe-2 workflow and retrieve depth map
        try:
            depth_map = await self._submit_moge2(source_image, config)
        except (ComfyUIError, OSError, Exception) as exc:
            logger.warning(
                "MoGe-2 depth estimation failed (%s) — using flat-floor fallback",
                exc,
            )
            depth_map = None

        # Validate depth map or use fallback
        if depth_map is not None:
            valid_ratio = validate_depth_map(depth_map)
        else:
            valid_ratio = 0.0

        # Apply flat-floor fallback if depth is too noisy or estimation failed
        # Requirement 3.6: fallback when MORE THAN 50% invalid (i.e., valid < 50%)
        if valid_ratio < (1.0 - _INVALID_PIXEL_THRESHOLD):
            # More than 50% invalid pixels (valid_ratio < 0.5)
            logger.info(
                "Depth map has %.1f%% valid pixels (threshold: %.0f%%) — "
                "using flat-floor fallback (depth=%.1fm, height=%.1fm)",
                valid_ratio * 100,
                (1.0 - _INVALID_PIXEL_THRESHOLD) * 100,
                _FALLBACK_DEPTH_M,
                _FALLBACK_HEIGHT_M,
            )
            depth_map = create_flat_floor_depth_map(img_height, img_width)
            normal_map = create_flat_normals(img_height, img_width)
            valid_ratio = 1.0  # Fallback is 100% valid by definition
        else:
            # Compute normals from the valid depth map
            normal_map = compute_normals_from_depth(depth_map)

        # Compute depth range
        depth_range = get_depth_range(depth_map)

        # Save arrays to disk
        depth_map_path = depth_dir / "depth_map.npy"
        normal_map_path = depth_dir / "normal_map.npy"
        np.save(depth_map_path, depth_map)
        np.save(normal_map_path, normal_map)

        return DepthResult(
            depth_map_path=depth_map_path,
            normal_map_path=normal_map_path,
            valid_pixel_ratio=valid_ratio,
            depth_range_m=depth_range,
        )

    # ------------------------------------------------------------------
    # ComfyUI workflow submission helpers
    # ------------------------------------------------------------------

    async def _submit_moge2(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> np.ndarray:
        """Submit MoGe-2 workflow and retrieve the metric depth map.

        Parameters
        ----------
        source_image : Path
            Input image path.
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        np.ndarray
            Float32 depth map in meters, shape (H, W).

        Raises
        ------
        ComfyUIError
            If the workflow fails or produces no output.
        """
        workflow = load_workflow("moge2_depth")

        depth_output_dir = self.output_dir / "depth" / "raw"
        depth_output_dir.mkdir(parents=True, exist_ok=True)

        placeholders = {
            "INPUT_IMAGE_PATH": str(source_image).replace("\\", "/"),
            "OUTPUT_DIR": str(depth_output_dir).replace("\\", "/"),
        }

        prompt_id = await self.client.submit_workflow(
            workflow, placeholders=placeholders
        )
        await self.client.wait_for_completion(prompt_id)

        # Retrieve the depth map from ComfyUI output
        return self._load_depth_output(depth_output_dir)

    def _load_depth_output(self, output_dir: Path) -> np.ndarray:
        """Load the depth map from ComfyUI's output directory.

        MoGe-2 outputs depth as EXR or NPY files. We check for both formats.

        Parameters
        ----------
        output_dir : Path
            Directory where ComfyUI saved the depth output.

        Returns
        -------
        np.ndarray
            Float32 2D array of metric depth values.

        Raises
        ------
        ComfyUIError
            If no recognizable depth output is found.
        """
        # Check for .npy format first (direct numpy save)
        npy_files = list(output_dir.glob("*depth*.npy"))
        if npy_files:
            depth = np.load(npy_files[0]).astype(np.float32)
            if depth.ndim == 3:
                # Take first channel if multi-channel
                depth = depth[:, :, 0]
            return depth

        # Check for EXR format (common ComfyUI output for depth)
        exr_files = list(output_dir.glob("*depth*.exr"))
        if exr_files:
            return self._load_exr_depth(exr_files[0])

        # Check for .tiff/.tif format
        tiff_files = list(output_dir.glob("*depth*.tif*"))
        if tiff_files:
            img = Image.open(tiff_files[0])
            depth = np.array(img, dtype=np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            return depth

        # Check for any PNG (16-bit depth encoded as PNG)
        png_files = list(output_dir.glob("*depth*.png"))
        if png_files:
            img = Image.open(png_files[0])
            depth = np.array(img, dtype=np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            # PNG depth is often normalized — scale to meters
            # MoGe-2 outputs metric depth, so if max > 100 it's likely
            # encoded as uint16 (0-65535 → 0-max_depth)
            if depth.max() > 100:
                depth = depth / 65535.0 * 20.0  # Assume max 20m range
            return depth

        raise ComfyUIError(
            f"No depth map output found in {output_dir}. "
            f"Expected *depth*.npy, *depth*.exr, *depth*.tif, or *depth*.png"
        )

    def _load_exr_depth(self, exr_path: Path) -> np.ndarray:
        """Load depth from an EXR file.

        Attempts to use OpenEXR/Imath if available, falls back to
        imageio or PIL for basic EXR support.

        Parameters
        ----------
        exr_path : Path
            Path to the EXR file.

        Returns
        -------
        np.ndarray
            Float32 2D depth array.
        """
        try:
            import imageio.v3 as iio

            data = iio.imread(str(exr_path))
            depth = data.astype(np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            return depth
        except ImportError:
            pass

        try:
            import OpenEXR  # type: ignore[import]
            import Imath  # type: ignore[import]

            exr_file = OpenEXR.InputFile(str(exr_path))
            header = exr_file.header()
            dw = header["dataWindow"]
            width = dw.max.x - dw.min.x + 1
            height = dw.max.y - dw.min.y + 1

            # Read the first channel (Y or R)
            channel_name = "Y" if "Y" in header["channels"] else "R"
            pt = Imath.PixelType(Imath.PixelType.FLOAT)
            raw = exr_file.channel(channel_name, pt)
            depth = np.frombuffer(raw, dtype=np.float32).reshape(height, width)
            return depth
        except ImportError:
            pass

        # Last resort: try PIL which has limited EXR support
        img = Image.open(exr_path)
        depth = np.array(img, dtype=np.float32)
        if depth.ndim == 3:
            depth = depth[:, :, 0]
        return depth
