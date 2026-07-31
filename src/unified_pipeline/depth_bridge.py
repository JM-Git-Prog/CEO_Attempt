"""Unified pipeline adapter for the V14 Depth Anything 3 estimator.

Bridges the existing `src/photo_pipeline/stages/depth_anything3.py`
into the unified pipeline's data model, providing a synchronous-friendly
interface that handles VRAM coordination and validation.

Key responsibilities:
- Ensure DA3 loads only after FLUX is fully unloaded (Req 14.2)
- Validate output: ≥50% valid pixels (positive, finite, <20m indoor) (Req 14.3)
- Save depth map as float32 NumPy .npy (Req 14.4)
- Fallback: flat-floor heuristic (4m depth, aspect-ratio width, 2.7m ceiling) (Req 14.5)

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validation threshold: at least 50% pixels must be valid (Req 14.3)
_VALID_PIXEL_THRESHOLD = 0.50

# Maximum depth for indoor scenes in meters (Req 14.3)
_MAX_INDOOR_DEPTH_M = 20.0

# Flat-floor heuristic parameters (Req 14.5)
_FLAT_FLOOR_DEPTH_M = 4.0
_FLAT_FLOOR_CEILING_M = 2.7


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DepthBridgeResult:
    """Result from the unified depth estimation bridge.

    Attributes:
        depth_path: Path to the saved float32 .npy depth map.
        valid_ratio: Fraction of valid pixels [0.0, 1.0].
        depth_range_m: (min_depth, max_depth) of valid pixels in meters.
        method_used: Which method produced the output:
            "depth_anything_3", "moge2", or "flat_floor".
        used_fallback: True if primary DA3 did not succeed.
        session_id: The session that produced this depth map.
    """

    depth_path: str
    valid_ratio: float
    depth_range_m: tuple[float, float]
    method_used: str
    used_fallback: bool
    session_id: str


# ---------------------------------------------------------------------------
# UnifiedDepthEstimator
# ---------------------------------------------------------------------------


class UnifiedDepthEstimator:
    """Adapter wrapping the V14 DepthAnything3Estimator for the unified pipeline.

    Delegates depth estimation to the existing implementation and adds:
    - VRAM coordination: verifies FLUX is unloaded before DA3 loads (Req 14.2)
    - Output validation: ≥50% valid pixels (Req 14.3)
    - Float32 .npy output (Req 14.4)
    - Flat-floor heuristic fallback (Req 14.5)

    The orchestrator is responsible for calling `ensure_flux_unloaded()` before
    invoking `estimate()`. This adapter enforces the check but does not itself
    perform model management.

    Usage:
        estimator = UnifiedDepthEstimator(output_dir=Path("sessions/abc/depth"))
        result = estimator.estimate(canon_path="sessions/abc/canon.png", session_id="abc")
    """

    def __init__(
        self,
        output_dir: Path | str | None = None,
        comfyui_url: str = "http://localhost:8188",
        flux_unloaded: bool = True,
    ) -> None:
        """Initialize the depth estimator bridge.

        Args:
            output_dir: Base output directory for depth artifacts.
                If None, uses a default relative path.
            comfyui_url: ComfyUI server URL for DA3/MoGe-2 workflows.
            flux_unloaded: Whether FLUX has been confirmed unloaded.
                Must be True before estimate() can proceed (Req 14.2).
        """
        self._output_dir = Path(output_dir) if output_dir else Path("output/depth")
        self._comfyui_url = comfyui_url
        self._flux_unloaded = flux_unloaded

    @property
    def flux_unloaded(self) -> bool:
        """Whether FLUX has been confirmed unloaded from VRAM."""
        return self._flux_unloaded

    @flux_unloaded.setter
    def flux_unloaded(self, value: bool) -> None:
        self._flux_unloaded = value

    def ensure_flux_unloaded(self) -> None:
        """Assert that FLUX is unloaded before DA3 can proceed.

        Raises:
            RuntimeError: If FLUX is still loaded in VRAM.
        """
        if not self._flux_unloaded:
            raise RuntimeError(
                "DA3 cannot load while FLUX is in VRAM (Req 14.2). "
                "Call VRAMManager.release_model() for FLUX before depth estimation."
            )

    def estimate(self, canon_path: str, session_id: str) -> str:
        """Run depth estimation with validation and fallback chain.

        Execution order:
        1. Verify FLUX is unloaded (Req 14.2)
        2. Attempt DA3 via the existing estimator
        3. If DA3 fails or invalid → try MoGe-2 fallback
        4. If MoGe-2 also fails → generate flat-floor heuristic (Req 14.5)
        5. Validate output: ≥50% valid pixels (Req 14.3)
        6. Save as float32 .npy (Req 14.4)
        7. Return path to saved depth map

        Args:
            canon_path: Path to the source Canon image (JPEG or PNG).
            session_id: The session ID for artifact organization.

        Returns:
            Path to the saved float32 .npy depth map.

        Raises:
            RuntimeError: If FLUX is still loaded (Req 14.2 violation).
        """
        # Req 14.2: Enforce FLUX unloaded before DA3 loads
        self.ensure_flux_unloaded()

        # Prepare output directory
        depth_dir = self._output_dir / session_id / "depth"
        depth_dir.mkdir(parents=True, exist_ok=True)

        source_path = Path(canon_path)

        # Get source image dimensions for fallback generation
        from PIL import Image

        src_img = Image.open(source_path)
        img_width, img_height = src_img.size
        src_img.close()

        # --- Attempt 1: Depth Anything 3 via existing estimator ---
        da3_depth = self._try_da3(source_path, depth_dir)
        if da3_depth is not None:
            valid_ratio = self._validate_depth_map(da3_depth)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(da3_depth, depth_dir)
                logger.info(
                    "DA3 depth estimation succeeded: %.1f%% valid pixels",
                    valid_ratio * 100,
                )
                return str(depth_path)
            else:
                logger.warning(
                    "DA3 depth map has only %.1f%% valid pixels (need ≥%.0f%%) "
                    "— trying MoGe-2 fallback",
                    valid_ratio * 100,
                    _VALID_PIXEL_THRESHOLD * 100,
                )

        # --- Attempt 2: MoGe-2 fallback ---
        moge2_depth = self._try_moge2(source_path, depth_dir)
        if moge2_depth is not None:
            valid_ratio = self._validate_depth_map(moge2_depth)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(moge2_depth, depth_dir)
                logger.info(
                    "MoGe-2 fallback succeeded: %.1f%% valid pixels",
                    valid_ratio * 100,
                )
                return str(depth_path)
            else:
                logger.warning(
                    "MoGe-2 depth map has only %.1f%% valid pixels "
                    "— using flat-floor heuristic",
                    valid_ratio * 100,
                )

        # --- Attempt 3: Flat-floor heuristic (always succeeds) (Req 14.5) ---
        logger.info(
            "Using flat-floor heuristic depth map (%dx%d, %.1fm depth, "
            "%.1fm ceiling)",
            img_width,
            img_height,
            _FLAT_FLOOR_DEPTH_M,
            _FLAT_FLOOR_CEILING_M,
        )
        flat_depth = self._generate_flat_floor(img_height, img_width)
        depth_path = self._save_depth_map(flat_depth, depth_dir)
        return str(depth_path)

    def estimate_with_details(
        self, canon_path: str, session_id: str
    ) -> DepthBridgeResult:
        """Run depth estimation and return full result with metadata.

        Same as `estimate()` but returns a DepthBridgeResult with method
        information, valid ratio, and depth range.

        Args:
            canon_path: Path to the source Canon image.
            session_id: The session ID.

        Returns:
            DepthBridgeResult with depth path and metadata.
        """
        # Req 14.2: Enforce FLUX unloaded
        self.ensure_flux_unloaded()

        # Prepare output directory
        depth_dir = self._output_dir / session_id / "depth"
        depth_dir.mkdir(parents=True, exist_ok=True)

        source_path = Path(canon_path)

        from PIL import Image

        src_img = Image.open(source_path)
        img_width, img_height = src_img.size
        src_img.close()

        # --- Attempt 1: DA3 ---
        da3_depth = self._try_da3(source_path, depth_dir)
        if da3_depth is not None:
            valid_ratio = self._validate_depth_map(da3_depth)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(da3_depth, depth_dir)
                depth_range = self._get_depth_range(da3_depth)
                return DepthBridgeResult(
                    depth_path=str(depth_path),
                    valid_ratio=valid_ratio,
                    depth_range_m=depth_range,
                    method_used="depth_anything_3",
                    used_fallback=False,
                    session_id=session_id,
                )

        # --- Attempt 2: MoGe-2 ---
        moge2_depth = self._try_moge2(source_path, depth_dir)
        if moge2_depth is not None:
            valid_ratio = self._validate_depth_map(moge2_depth)
            if valid_ratio >= _VALID_PIXEL_THRESHOLD:
                depth_path = self._save_depth_map(moge2_depth, depth_dir)
                depth_range = self._get_depth_range(moge2_depth)
                return DepthBridgeResult(
                    depth_path=str(depth_path),
                    valid_ratio=valid_ratio,
                    depth_range_m=depth_range,
                    method_used="moge2",
                    used_fallback=True,
                    session_id=session_id,
                )

        # --- Attempt 3: Flat-floor heuristic ---
        flat_depth = self._generate_flat_floor(img_height, img_width)
        depth_path = self._save_depth_map(flat_depth, depth_dir)
        valid_ratio = self._validate_depth_map(flat_depth)
        depth_range = self._get_depth_range(flat_depth)

        return DepthBridgeResult(
            depth_path=str(depth_path),
            valid_ratio=valid_ratio,
            depth_range_m=depth_range,
            method_used="flat_floor",
            used_fallback=True,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Validation (Req 14.3)
    # ------------------------------------------------------------------

    def _validate_depth_map(self, depth: np.ndarray) -> float:
        """Return fraction of valid pixels (positive, finite, <20m).

        A pixel is valid if and only if:
        - depth > 0 (positive)
        - depth is finite (not inf or nan)
        - depth < 20.0 (indoor range)

        Args:
            depth: 2D float32 array of depth values in meters.

        Returns:
            Ratio of valid pixels to total pixels [0.0, 1.0].
        """
        if depth.size == 0:
            return 0.0
        valid = (depth > 0) & np.isfinite(depth) & (depth < _MAX_INDOOR_DEPTH_M)
        return float(np.sum(valid)) / depth.size

    @staticmethod
    def validate_depth_map(depth: np.ndarray) -> float:
        """Public static method for depth validation (Req 14.3).

        A pixel is valid if and only if:
        - depth > 0 (positive)
        - depth is finite (not inf or nan)
        - depth < 20.0 (indoor range)

        Args:
            depth: 2D float32 array of depth values in meters.

        Returns:
            Ratio of valid pixels to total pixels [0.0, 1.0].
        """
        if depth.size == 0:
            return 0.0
        valid = (depth > 0) & np.isfinite(depth) & (depth < _MAX_INDOOR_DEPTH_M)
        return float(np.sum(valid)) / depth.size

    # ------------------------------------------------------------------
    # DA3 attempt (delegates to existing V14 estimator)
    # ------------------------------------------------------------------

    def _try_da3(
        self, source_image: Path, depth_dir: Path
    ) -> np.ndarray | None:
        """Attempt DA3 depth estimation via existing V14 infrastructure.

        Tries to load the DA3 workflow and run it through ComfyUI.
        Returns None on any failure (workflow not found, ComfyUI error, etc.).

        Args:
            source_image: Path to the source RGB image.
            depth_dir: Output directory for intermediate artifacts.

        Returns:
            Float32 depth map in meters, or None if DA3 fails.
        """
        try:
            from src.photo_pipeline.comfyui_client import (
                ComfyUIClient,
                ComfyUIError,
            )
            from src.photo_pipeline.models import PhotoPipelineConfig
            from src.photo_pipeline.stages.depth_anything3 import (
                DepthAnything3Estimator,
            )

            # Create a client and estimator instance
            config = PhotoPipelineConfig(comfyui_url=self._comfyui_url)
            client = ComfyUIClient(base_url=self._comfyui_url)
            estimator = DepthAnything3Estimator(
                client=client, output_dir=depth_dir.parent
            )

            # Use the estimator's internal DA3 attempt (sync wrapper for async)
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We're inside an event loop — use nest_asyncio or create task
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        estimator._try_depth_anything3(source_image, config),
                    ).result(timeout=200)
            else:
                result = asyncio.run(
                    estimator._try_depth_anything3(source_image, config)
                )

            return result

        except Exception as exc:
            logger.warning("DA3 attempt failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # MoGe-2 attempt (delegates to existing V14 estimator)
    # ------------------------------------------------------------------

    def _try_moge2(
        self, source_image: Path, depth_dir: Path
    ) -> np.ndarray | None:
        """Attempt MoGe-2 depth estimation via existing V14 infrastructure.

        Args:
            source_image: Path to the source RGB image.
            depth_dir: Output directory for intermediate artifacts.

        Returns:
            Float32 depth map in meters, or None if MoGe-2 fails.
        """
        try:
            from src.photo_pipeline.comfyui_client import (
                ComfyUIClient,
                ComfyUIError,
            )
            from src.photo_pipeline.models import PhotoPipelineConfig
            from src.photo_pipeline.stages.depth_anything3 import (
                DepthAnything3Estimator,
            )

            config = PhotoPipelineConfig(comfyui_url=self._comfyui_url)
            client = ComfyUIClient(base_url=self._comfyui_url)
            estimator = DepthAnything3Estimator(
                client=client, output_dir=depth_dir.parent
            )

            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        estimator._try_moge2(source_image, config),
                    ).result(timeout=200)
            else:
                result = asyncio.run(
                    estimator._try_moge2(source_image, config)
                )

            return result

        except Exception as exc:
            logger.warning("MoGe-2 attempt failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Flat-floor heuristic (Req 14.5)
    # ------------------------------------------------------------------

    def _generate_flat_floor(
        self, image_height: int, image_width: int
    ) -> np.ndarray:
        """Generate a flat-floor heuristic depth map.

        Creates a depth map simulating a flat floor at 4m depth with
        aspect-ratio-correct width and 2.7m ceiling height.

        The gradient runs from ~1m (top/ceiling) to 4m (bottom/floor),
        approximating a downward-looking camera in a standard-height room.

        Args:
            image_height: Height of the source image in pixels.
            image_width: Width of the source image in pixels.

        Returns:
            Float32 depth map shape (H, W) in meters.
        """
        # Linear interpolation: ceiling (~1m near top) to floor (4m at bottom)
        ceiling_depth = _FLAT_FLOOR_CEILING_M * 0.37  # ~1.0m at image top
        floor_depth = _FLAT_FLOOR_DEPTH_M  # 4.0m at image bottom

        rows = np.linspace(
            ceiling_depth,
            floor_depth,
            image_height,
            dtype=np.float32,
        )
        # Broadcast to full width
        depth = np.tile(rows[:, np.newaxis], (1, image_width))
        return depth

    # ------------------------------------------------------------------
    # Save and utility methods
    # ------------------------------------------------------------------

    def _save_depth_map(self, depth: np.ndarray, depth_dir: Path) -> Path:
        """Save depth map as float32 .npy file (Req 14.4).

        Args:
            depth: Float32 depth map to save.
            depth_dir: Output directory.

        Returns:
            Path to saved .npy file.
        """
        depth_path = depth_dir / "depth_map.npy"
        np.save(depth_path, depth.astype(np.float32))
        return depth_path

    def _get_depth_range(self, depth: np.ndarray) -> tuple[float, float]:
        """Compute min/max depth of valid pixels.

        Args:
            depth: Float32 depth map.

        Returns:
            (min_depth, max_depth) of valid pixels. (0.0, 0.0) if none valid.
        """
        valid_mask = (
            (depth > 0) & np.isfinite(depth) & (depth < _MAX_INDOOR_DEPTH_M)
        )
        valid_values = depth[valid_mask]
        if valid_values.size == 0:
            return (0.0, 0.0)
        return (float(valid_values.min()), float(valid_values.max()))
