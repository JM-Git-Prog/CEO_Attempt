"""Geometry validation QA gate for depth-conditioned generation.

This module is a **QA gate**. It compares an estimated depth map (produced by
DA3 monocular depth estimation on a generated image) against the conditioning
depth map (rendered from the authoritative MetricPlan) to verify that the
ControlNet depth conditioning actually held during image generation.

The gate is *diagnostic only*. It never overrides spatial authority: the
MetricPlan remains the sole source of spatial truth. When comparison fails, the
correct response is to re-generate the image (typically with increased
ControlNet conditioning strength), not to trust or promote the estimated depth.
DA3 output and any derived metric here are appearance evidence, never authority.

This module compares two arrays only. It does not invoke DA3, ComfyUI, or any
external model; that wiring is owned by the primary agent elsewhere.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

try:  # skimage is optional; fall back to a numpy SSIM implementation.
    from skimage.metrics import structural_similarity as _sk_ssim

    _HAVE_SKIMAGE = True
except ImportError:  # pragma: no cover - exercised only when skimage absent
    _sk_ssim = None
    _HAVE_SKIMAGE = False


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of comparing an estimated depth map to a conditioning map.

    Attributes:
        passed: True when every configured threshold was satisfied.
        pearson_r: Pearson correlation of scale-aligned estimated vs.
            conditioning depth over the valid region.
        scale_aligned_mae_m: Mean absolute error in meters after scale
            alignment.
        depth_ssim: Structural similarity between normalized aligned and
            conditioning depth over the valid region.
        scale_factor: Least-squares optimal scale applied to the estimated map.
        coverage_fraction: Fraction of pixels considered valid in both maps.
        failure_reason: Human-readable description of failing threshold(s);
            empty when passed.
    """

    passed: bool
    pearson_r: float
    scale_aligned_mae_m: float
    depth_ssim: float
    scale_factor: float
    coverage_fraction: float
    failure_reason: str = ""


@dataclass
class ValidationConfig:
    """Thresholds and retry policy for the geometry validation gate.

    Attributes:
        min_correlation: Minimum acceptable Pearson correlation.
        max_mae_m: Maximum acceptable scale-aligned mean absolute error (m).
        min_ssim: Minimum acceptable structural similarity.
        max_retries: Maximum re-generation attempts on failure.
        strength_increment: Amount to raise ControlNet strength per retry.
        max_strength: Upper bound for ControlNet conditioning strength.
    """

    min_correlation: float = 0.7
    max_mae_m: float = 0.5
    min_ssim: float = 0.6
    max_retries: int = 3
    strength_increment: float = 0.1
    max_strength: float = 1.0


class GeometryValidationGate:
    """Compares depth maps to confirm depth conditioning held during generation.

    This is a fail-detection gate only. It does not mutate, replace, or promote
    any depth map to spatial authority. A failing result signals the caller to
    re-generate the image.
    """

    def __init__(self, config: ValidationConfig | None = None) -> None:
        self.config = config if config is not None else ValidationConfig()

    def compare(
        self,
        estimated_depth: np.ndarray,
        conditioning_depth: np.ndarray,
    ) -> ValidationResult:
        """Compare two depth maps of identical ``HxW`` shape.

        Args:
            estimated_depth: Depth estimated from the generated image (DA3).
            conditioning_depth: Conditioning depth rendered from the MetricPlan.
                May use ``np.inf`` (or non-positive values) to mark pixels with
                no geometry; those are treated as invalid.

        Returns:
            A :class:`ValidationResult` describing the comparison. The gate never
            overrides spatial authority; a failing result means re-generate.
        """
        estimated = np.asarray(estimated_depth, dtype=np.float64)
        conditioning = np.asarray(conditioning_depth, dtype=np.float64)

        if estimated.shape != conditioning.shape:
            raise ValueError(
                "estimated_depth and conditioning_depth must share shape; "
                f"got {estimated.shape} and {conditioning.shape}"
            )

        total_pixels = estimated.size

        # 1. Validity mask: both maps finite and strictly positive.
        valid = (
            np.isfinite(estimated)
            & np.isfinite(conditioning)
            & (estimated > 0.0)
            & (conditioning > 0.0)
        )
        valid_count = int(np.count_nonzero(valid))

        # 2. Coverage fraction.
        coverage_fraction = (
            valid_count / total_pixels if total_pixels else 0.0
        )

        if valid_count < 2:
            logger.debug(
                "Geometry gate: insufficient coverage (%d valid pixels)",
                valid_count,
            )
            return ValidationResult(
                passed=False,
                pearson_r=0.0,
                scale_aligned_mae_m=float("inf"),
                depth_ssim=0.0,
                scale_factor=1.0,
                coverage_fraction=coverage_fraction,
                failure_reason="insufficient coverage",
            )

        est = estimated[valid]
        cond = conditioning[valid]

        # 3. Optimal least-squares scale: s = sum(est*cond) / sum(est*est).
        denom = float(np.sum(est * est))
        if denom <= 0.0:
            scale_factor = 1.0
        else:
            scale_factor = float(np.sum(est * cond) / denom)

        # 4. Scale-aligned estimate.
        aligned = scale_factor * est

        # 5. Pearson correlation of aligned vs conditioning.
        pearson_r = _pearson(aligned, cond)

        # 6. Scale-aligned MAE in meters.
        scale_aligned_mae_m = float(np.mean(np.abs(aligned - cond)))

        # 7. Global SSIM over the valid region (normalized).
        depth_ssim = _global_ssim(aligned, cond)

        # 8. Threshold evaluation.
        cfg = self.config
        failed: list[str] = []
        if pearson_r < cfg.min_correlation:
            failed.append(
                f"correlation {pearson_r:.3f} < min {cfg.min_correlation:.3f}"
            )
        if scale_aligned_mae_m > cfg.max_mae_m:
            failed.append(
                f"mae {scale_aligned_mae_m:.3f}m > max {cfg.max_mae_m:.3f}m"
            )
        if depth_ssim < cfg.min_ssim:
            failed.append(f"ssim {depth_ssim:.3f} < min {cfg.min_ssim:.3f}")

        passed = not failed
        failure_reason = "" if passed else "; ".join(failed)

        if not passed:
            logger.debug("Geometry gate failed: %s", failure_reason)

        return ValidationResult(
            passed=passed,
            pearson_r=pearson_r,
            scale_aligned_mae_m=scale_aligned_mae_m,
            depth_ssim=depth_ssim,
            scale_factor=scale_factor,
            coverage_fraction=coverage_fraction,
            failure_reason=failure_reason,
        )

    def next_strength(self, current_strength: float) -> float:
        """Return the next ControlNet strength, capped at ``max_strength``.

        Args:
            current_strength: The strength used for the last attempt.

        Returns:
            ``min(current + strength_increment, max_strength)``.
        """
        return min(
            current_strength + self.config.strength_increment,
            self.config.max_strength,
        )


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation coefficient; 0.0 when either input has no variance."""
    a_mean = float(np.mean(a))
    b_mean = float(np.mean(b))
    a_dev = a - a_mean
    b_dev = b - b_mean
    denom = float(np.sqrt(np.sum(a_dev * a_dev) * np.sum(b_dev * b_dev)))
    if denom <= 0.0:
        return 0.0
    return float(np.sum(a_dev * b_dev) / denom)


def _global_ssim(aligned: np.ndarray, conditioning: np.ndarray) -> float:
    """Global SSIM between two 1-D valid-region vectors after normalization.

    Both inputs are normalized to a shared [0, 1] range using their combined
    min/max so the comparison is scale-invariant. Uses
    ``skimage.metrics.structural_similarity`` when available, otherwise a compact
    numpy implementation of the standard global SSIM formula.
    """
    combined_min = float(min(aligned.min(), conditioning.min()))
    combined_max = float(max(aligned.max(), conditioning.max()))
    span = combined_max - combined_min

    if span <= 0.0:
        # Both regions are a single identical constant -> perfect similarity.
        return 1.0

    norm_aligned = (aligned - combined_min) / span
    norm_cond = (conditioning - combined_min) / span

    data_range = 1.0

    if _HAVE_SKIMAGE:
        try:
            return float(
                _sk_ssim(norm_cond, norm_aligned, data_range=data_range)
            )
        except (ValueError, RuntimeError):  # pragma: no cover - defensive
            logger.debug("skimage SSIM failed; using numpy fallback")

    return _numpy_global_ssim(norm_aligned, norm_cond, data_range)


def _numpy_global_ssim(x: np.ndarray, y: np.ndarray, dynamic_range: float) -> float:
    """Standard global SSIM using means, variances and covariance."""
    c1 = (0.01 * dynamic_range) ** 2
    c2 = (0.03 * dynamic_range) ** 2

    mu_x = float(np.mean(x))
    mu_y = float(np.mean(y))
    var_x = float(np.var(x))
    var_y = float(np.var(y))
    cov_xy = float(np.mean((x - mu_x) * (y - mu_y)))

    numerator = (2.0 * mu_x * mu_y + c1) * (2.0 * cov_xy + c2)
    denominator = (mu_x**2 + mu_y**2 + c1) * (var_x + var_y + c2)

    if denominator == 0.0:  # pragma: no cover - defensive
        return 0.0
    return float(numerator / denominator)
