"""Depth Anything 3 Estimator — metric depth via ComfyUI with fallback chain.

Implements the V14 depth estimation stage using Depth Anything 3 as the primary
model, with MoGe-2 as first fallback and a flat-floor heuristic as final fallback.
Produces a float32 .npy depth map in meters at source image resolution.

Validation: ≥50% valid pixels (positive, finite, <20m for indoor scenes).
VRAM-safe: assumes FLUX has been unloaded before this stage is called.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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

# Validation threshold: at least 50% pixels must be valid
_VALID_PIXEL_THRESHOLD = 0.50

# Maximum depth for indoor scenes (meters)
_MAX_INDOOR_DEPTH_M = 20.0

# Flat-floor heuristic parameters
_FLAT_FLOOR_TOP_DEPTH_M = 1.0
_FLAT_FLOOR_BOTTOM_DEPTH_M = 5.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DA3DepthResult:
    """Result of Depth Anything 3 depth estimation.

    Extends the pipeline DepthResult concept with DA3-specific metadata:
    which method actually produced the output, whether fallback was used,
    and the validation ratio.
    """

    depth_map: np.ndarray       # float32, shape (H, W), meters
    depth_path: Path            # saved .npy file path
    valid_ratio: float          # fraction of valid pixels [0.0, 1.0]
    method_used: str            # "depth_anything_3", "moge2", or "flat_floor"
    used_fallback: bool         # True if primary DA3 did not succeed


# ---------------------------------------------------------------------------
# DepthAnything3Estimator
# ---------------------------------------------------------------------------


class DepthAnything3Estimator:
    """Metric depth estimation using Depth Anything 3 via ComfyUI.

    Produces a float32 depth map in meters at source image resolution.
    Validates ≥50% valid pixels (positive, finite, <20m for indoor).
    Falls back to MoGe-2 then flat-floor heuristic on failure.

    VRAM-safe: The orchestrator is responsible for unloading FLUX before
    calling this estimator. This module simply runs its workflow.

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
        """Run DA3 depth estimation with validation and fallback chain.

        Execution order:
        1. Submit Depth Anything 3 workflow to ComfyUI
        2. Validate output (≥50% valid pixels: positive, finite, <20m)
        3. If DA3 fails or invalid → try MoGe-2
        4. If MoGe-2 also fails or invalid → generate flat-floor heuristic
        5. Save depth map as float32 .npy
        6. Return DepthResult

        Parameters
        ----------
        source_image : Path
            Path to the source RGB image (JPEG or PNG).
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        DepthResult
            Structured result with depth map path, valid pixel ratio,
            and depth range.
        """
        depth_dir = self.output_dir / "depth"
        depth_dir.mkdir(parents=True, exist_ok=True)

        # Get source image dimensions for fallback generation
        src_img = Image.open(source_image)
        img_width, img_height = src_img.size
        src_img.close()

        # --- Attempt 1: Depth Anything 3 ---
        da3_result = await self._try_depth_anything3(source_image, config)
        if da3_result is not None:
            valid_ratio = self.validate_depth_map(da3_result)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(da3_result, depth_dir)
                depth_range = self._get_depth_range(da3_result)
                logger.info(
                    "DA3 depth estimation succeeded: %.1f%% valid pixels, "
                    "range %.2f-%.2fm",
                    valid_ratio * 100,
                    depth_range[0],
                    depth_range[1],
                )
                return DepthResult(
                    depth_map_path=depth_path,
                    normal_map_path=self._save_normals(da3_result, depth_dir),
                    valid_pixel_ratio=valid_ratio,
                    depth_range_m=depth_range,
                )
            else:
                logger.warning(
                    "DA3 depth map has only %.1f%% valid pixels (need ≥%.0f%%) "
                    "— trying MoGe-2 fallback",
                    valid_ratio * 100,
                    _VALID_PIXEL_THRESHOLD * 100,
                )

        # --- Attempt 2: MoGe-2 fallback ---
        moge2_result = await self._try_moge2(source_image, config)
        if moge2_result is not None:
            valid_ratio = self.validate_depth_map(moge2_result)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(moge2_result, depth_dir)
                depth_range = self._get_depth_range(moge2_result)
                logger.info(
                    "MoGe-2 fallback succeeded: %.1f%% valid pixels, "
                    "range %.2f-%.2fm",
                    valid_ratio * 100,
                    depth_range[0],
                    depth_range[1],
                )
                return DepthResult(
                    depth_map_path=depth_path,
                    normal_map_path=self._save_normals(moge2_result, depth_dir),
                    valid_pixel_ratio=valid_ratio,
                    depth_range_m=depth_range,
                )
            else:
                logger.warning(
                    "MoGe-2 depth map has only %.1f%% valid pixels "
                    "— using flat-floor heuristic",
                    valid_ratio * 100,
                )

        # --- Attempt 3: Flat-floor heuristic (always succeeds) ---
        logger.info(
            "Using flat-floor heuristic depth map (%dx%d, %.1f-%.1fm)",
            img_width,
            img_height,
            _FLAT_FLOOR_TOP_DEPTH_M,
            _FLAT_FLOOR_BOTTOM_DEPTH_M,
        )
        flat_depth = self._generate_flat_floor(img_height, img_width)
        depth_path = self._save_depth_map(flat_depth, depth_dir)
        valid_ratio = self.validate_depth_map(flat_depth)
        depth_range = self._get_depth_range(flat_depth)

        return DepthResult(
            depth_map_path=depth_path,
            normal_map_path=self._save_normals(flat_depth, depth_dir),
            valid_pixel_ratio=valid_ratio,
            depth_range_m=depth_range,
        )

    def validate_depth_map(self, depth: np.ndarray) -> float:
        """Return valid pixel ratio (positive, finite, <20m).

        A pixel is valid if and only if:
        - depth > 0 (positive)
        - depth is finite (not inf or nan)
        - depth < 20.0 (indoor range)

        Parameters
        ----------
        depth : np.ndarray
            2D float32 array of depth values in meters.

        Returns
        -------
        float
            Ratio of valid pixels to total pixels [0.0, 1.0].
        """
        if depth.size == 0:
            return 0.0
        valid = (depth > 0) & np.isfinite(depth) & (depth < _MAX_INDOOR_DEPTH_M)
        return float(np.sum(valid)) / depth.size

    # ------------------------------------------------------------------
    # ComfyUI workflow submission: Depth Anything 3
    # ------------------------------------------------------------------

    async def _try_depth_anything3(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> np.ndarray | None:
        """Submit DA3 workflow and retrieve depth map. Returns None on failure.

        Parameters
        ----------
        source_image : Path
            Input image path.
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        np.ndarray | None
            Float32 depth map in meters, or None if DA3 is unavailable/fails.
        """
        try:
            workflow = load_workflow("depth_anything3")
        except (ValueError, FileNotFoundError) as exc:
            logger.warning("DA3 workflow not available: %s", exc)
            return None

        raw_dir = self.output_dir / "depth" / "da3_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        placeholders = {
            "INPUT_IMAGE_PATH": str(source_image).replace("\\", "/"),
            "OUTPUT_DIR": str(raw_dir).replace("\\", "/"),
        }

        try:
            prompt_id = await self.client.submit_workflow(
                workflow, placeholders=placeholders
            )
            await self.client.wait_for_completion(prompt_id)
            return self._load_depth_output(raw_dir)
        except ComfyUIError as exc:
            logger.warning("DA3 ComfyUI execution failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning("DA3 unexpected error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # ComfyUI workflow submission: MoGe-2 fallback
    # ------------------------------------------------------------------

    async def _try_moge2(
        self,
        source_image: Path,
        config: PhotoPipelineConfig,
    ) -> np.ndarray | None:
        """Submit MoGe-2 workflow as fallback. Returns None on failure.

        Parameters
        ----------
        source_image : Path
            Input image path.
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        np.ndarray | None
            Float32 depth map in meters, or None if MoGe-2 is unavailable/fails.
        """
        try:
            workflow = load_workflow("moge2_depth")
        except (ValueError, FileNotFoundError) as exc:
            logger.warning("MoGe-2 workflow not available: %s", exc)
            return None

        raw_dir = self.output_dir / "depth" / "moge2_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        placeholders = {
            "INPUT_IMAGE_PATH": str(source_image).replace("\\", "/"),
            "OUTPUT_DIR": str(raw_dir).replace("\\", "/"),
        }

        try:
            prompt_id = await self.client.submit_workflow(
                workflow, placeholders=placeholders
            )
            await self.client.wait_for_completion(prompt_id)
            return self._load_depth_output(raw_dir)
        except ComfyUIError as exc:
            logger.warning("MoGe-2 ComfyUI execution failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning("MoGe-2 unexpected error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Flat-floor heuristic
    # ------------------------------------------------------------------

    def _generate_flat_floor(
        self,
        image_height: int,
        image_width: int,
    ) -> np.ndarray:
        """Generate a flat-floor heuristic depth map.

        Linearly interpolates depth from top (1m) to bottom (5m) of the image,
        simulating a camera looking slightly downward at a floor plane.

        Parameters
        ----------
        image_height : int
            Height of the source image in pixels.
        image_width : int
            Width of the source image in pixels.

        Returns
        -------
        np.ndarray
            Float32 depth map shape (H, W) with linearly increasing depth.
        """
        # Linear interpolation: top row = 1m, bottom row = 5m
        rows = np.linspace(
            _FLAT_FLOOR_TOP_DEPTH_M,
            _FLAT_FLOOR_BOTTOM_DEPTH_M,
            image_height,
            dtype=np.float32,
        )
        # Broadcast to full width
        depth = np.tile(rows[:, np.newaxis], (1, image_width))
        return depth

    # ------------------------------------------------------------------
    # Output loading and saving
    # ------------------------------------------------------------------

    def _load_depth_output(self, output_dir: Path) -> np.ndarray:
        """Load depth map from ComfyUI output directory.

        Checks for .npy, .exr, .tif, and .png formats in order of preference.

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
        # Check for .npy format (direct numpy)
        npy_files = list(output_dir.glob("*.npy"))
        if npy_files:
            depth = np.load(npy_files[0]).astype(np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            return depth

        # Check for EXR format
        exr_files = list(output_dir.glob("*.exr"))
        if exr_files:
            return self._load_exr_depth(exr_files[0])

        # Check for TIFF format
        tiff_files = list(output_dir.glob("*.tif")) + list(
            output_dir.glob("*.tiff")
        )
        if tiff_files:
            img = Image.open(tiff_files[0])
            depth = np.array(img, dtype=np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            return depth

        # Check for PNG (16-bit depth encoded)
        png_files = list(output_dir.glob("*.png"))
        if png_files:
            img = Image.open(png_files[0])
            depth = np.array(img, dtype=np.float32)
            if depth.ndim == 3:
                depth = depth[:, :, 0]
            # DA3 outputs metric depth; if encoded as uint16, scale to meters
            if depth.max() > 100:
                depth = depth / 65535.0 * _MAX_INDOOR_DEPTH_M
            return depth

        raise ComfyUIError(
            f"No depth map output found in {output_dir}. "
            f"Expected *.npy, *.exr, *.tif, or *.png"
        )

    def _load_exr_depth(self, exr_path: Path) -> np.ndarray:
        """Load depth from an EXR file with multiple library fallbacks.

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

            channel_name = "Y" if "Y" in header["channels"] else "R"
            pt = Imath.PixelType(Imath.PixelType.FLOAT)
            raw = exr_file.channel(channel_name, pt)
            depth = np.frombuffer(raw, dtype=np.float32).reshape(height, width)
            return depth
        except ImportError:
            pass

        # Last resort: PIL
        img = Image.open(exr_path)
        depth = np.array(img, dtype=np.float32)
        if depth.ndim == 3:
            depth = depth[:, :, 0]
        return depth

    def _save_depth_map(self, depth: np.ndarray, depth_dir: Path) -> Path:
        """Save depth map as float32 .npy file.

        Parameters
        ----------
        depth : np.ndarray
            Float32 depth map to save.
        depth_dir : Path
            Output directory.

        Returns
        -------
        Path
            Path to saved .npy file.
        """
        depth_path = depth_dir / "depth_map.npy"
        np.save(depth_path, depth.astype(np.float32))
        return depth_path

    def _save_normals(self, depth: np.ndarray, depth_dir: Path) -> Path:
        """Derive and save normal map from depth using finite differences.

        Parameters
        ----------
        depth : np.ndarray
            Float32 depth map.
        depth_dir : Path
            Output directory.

        Returns
        -------
        Path
            Path to saved normal_map.npy.
        """
        normal_map = self._compute_normals(depth)
        normal_path = depth_dir / "normal_map.npy"
        np.save(normal_path, normal_map)
        return normal_path

    def _compute_normals(self, depth: np.ndarray) -> np.ndarray:
        """Compute surface normals from depth gradients via finite differences.

        Parameters
        ----------
        depth : np.ndarray
            2D float32 depth map.

        Returns
        -------
        np.ndarray
            Normal map (H, W, 3) with unit-length normals pointing toward camera.
        """
        h, w = depth.shape[:2]

        # Horizontal gradient (central differences)
        dz_dx = np.zeros_like(depth)
        dz_dx[:, 1:-1] = (depth[:, 2:] - depth[:, :-2]) / 2.0
        dz_dx[:, 0] = depth[:, 1] - depth[:, 0]
        dz_dx[:, -1] = depth[:, -1] - depth[:, -2]

        # Vertical gradient (central differences)
        dz_dy = np.zeros_like(depth)
        dz_dy[1:-1, :] = (depth[2:, :] - depth[:-2, :]) / 2.0
        dz_dy[0, :] = depth[1, :] - depth[0, :]
        dz_dy[-1, :] = depth[-1, :] - depth[-2, :]

        # Normal vectors: [-dz/dx, -dz/dy, 1.0]
        normals = np.zeros((h, w, 3), dtype=np.float32)
        normals[:, :, 0] = -dz_dx
        normals[:, :, 1] = -dz_dy
        normals[:, :, 2] = 1.0

        # Normalize to unit length
        magnitudes = np.linalg.norm(normals, axis=2, keepdims=True)
        magnitudes = np.maximum(magnitudes, 1e-8)
        normals = normals / magnitudes

        return normals

    def _get_depth_range(self, depth: np.ndarray) -> tuple[float, float]:
        """Compute min/max depth of valid pixels.

        Parameters
        ----------
        depth : np.ndarray
            Float32 depth map.

        Returns
        -------
        tuple[float, float]
            (min_depth, max_depth) of valid pixels. (0.0, 0.0) if none valid.
        """
        valid_mask = (
            (depth > 0) & np.isfinite(depth) & (depth < _MAX_INDOOR_DEPTH_M)
        )
        valid_values = depth[valid_mask]
        if valid_values.size == 0:
            return (0.0, 0.0)
        return (float(valid_values.min()), float(valid_values.max()))
