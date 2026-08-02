"""Perceptual metrics computation module for E2E fidelity testing.

Provides SSIM, LPIPS, and CLIP cosine similarity computations for
Canon-to-World perceptual comparison in the V16 Unified World Pipeline.

Each metric function:
- Accepts two images (as file paths or numpy arrays)
- Acquires a VRAM lease from the Resource Arbiter before loading GPU models
- Releases the VRAM lease within 5 seconds of computation completing
- Returns a float metric value (or None if GPU/model is unavailable)

Graceful fallback: when CUDA or the required models are unavailable,
functions return None rather than raising, allowing the caller to
skip the metric without failing the test suite.

Requirements: 5.2–5.4, 21.1, 21.3
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Union

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Type for image inputs: file path or HxWxC uint8 numpy array
ImageInput = Union[str, Path, "NDArray[np.uint8]"]

# Maximum seconds allowed between computation end and VRAM lease release (Req 21.3)
_LEASE_RELEASE_DEADLINE_S: float = 5.0


class PerceptualMetricsError(RuntimeError):
    """Raised when a perceptual metric computation fails irrecoverably."""


class GPUUnavailableError(PerceptualMetricsError):
    """Raised when CUDA/GPU is required but not available.

    Callers should catch this and treat as a graceful skip.
    """


def _load_image_as_numpy(image: ImageInput) -> "NDArray[np.uint8]":
    """Load an image input into a HxWxC uint8 numpy array.

    Args:
        image: File path (str/Path) or pre-loaded numpy array.

    Returns:
        HxWxC uint8 numpy array in RGB color order.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If image cannot be decoded or has invalid shape.
    """
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            return np.array(img, dtype=np.uint8)
        except Exception as exc:
            raise ValueError(f"Failed to load image from {path}: {exc}") from exc
    elif isinstance(image, np.ndarray):
        if image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError(
                f"Expected HxWxC image array with 3 or 4 channels, "
                f"got shape {image.shape}"
            )
        # Convert RGBA to RGB if needed
        if image.shape[2] == 4:
            image = image[:, :, :3]
        return image.astype(np.uint8)
    else:
        raise TypeError(
            f"Expected str, Path, or numpy array, got {type(image).__name__}"
        )


def _validate_image_pair(
    img_a: "NDArray[np.uint8]", img_b: "NDArray[np.uint8]"
) -> None:
    """Validate that two images have compatible dimensions for comparison.

    Raises:
        ValueError: If images have different dimensions.
    """
    if img_a.shape != img_b.shape:
        raise ValueError(
            f"Image dimensions must match for perceptual comparison. "
            f"Got {img_a.shape} vs {img_b.shape}"
        )


def compute_ssim(
    image_a: ImageInput,
    image_b: ImageInput,
) -> float | None:
    """Compute Structural Similarity Index (SSIM) between two images.

    SSIM measures perceptual similarity based on luminance, contrast, and
    structure. Higher values indicate greater similarity (range 0.0–1.0).

    This metric uses CPU computation (scikit-image) and does NOT require
    a VRAM lease — it runs without GPU.

    Args:
        image_a: First image (Canon reference).
        image_b: Second image (World screenshot).

    Returns:
        Float SSIM value in [0.0, 1.0] where higher is more similar.
        Returns None if the computation cannot be performed (missing deps).

    Validates: Requirement 5.2
    """
    try:
        from skimage.metrics import structural_similarity
    except ImportError:
        logger.warning(
            "scikit-image not available — SSIM computation skipped. "
            "Install with: pip install scikit-image"
        )
        return None

    try:
        img_a = _load_image_as_numpy(image_a)
        img_b = _load_image_as_numpy(image_b)
        _validate_image_pair(img_a, img_b)

        # Compute SSIM over the full multichannel image
        score = structural_similarity(
            img_a,
            img_b,
            channel_axis=2,  # HxWxC format, channel is last axis
            data_range=255,
        )
        logger.info("SSIM computed: %.6f", score)
        return float(score)

    except (FileNotFoundError, ValueError, TypeError) as exc:
        logger.error("SSIM computation failed: %s", exc)
        raise PerceptualMetricsError(f"SSIM computation failed: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected error during SSIM computation: %s", exc)
        return None


def compute_lpips(
    image_a: ImageInput,
    image_b: ImageInput,
    *,
    vram_lease=None,
) -> float | None:
    """Compute LPIPS (Learned Perceptual Image Patch Similarity) distance.

    LPIPS uses a deep network (AlexNet by default) to measure perceptual
    distance. Lower values indicate greater similarity.

    This metric requires CUDA/GPU for model inference. A VRAM lease from
    the Resource Arbiter must be acquired before calling this function.
    The lease is released within 5 seconds of computation completing.

    Args:
        image_a: First image (Canon reference).
        image_b: Second image (World screenshot).
        vram_lease: Optional VRAMLeaseFacade from the vram_lease fixture.
            If provided, the function will acquire/release the PERCEPTUAL_LPIPS
            lease. If None, the caller is responsible for VRAM management.

    Returns:
        Float LPIPS distance where lower is more similar (typically 0.0–1.0).
        Returns None if GPU/CUDA is unavailable or model cannot be loaded.

    Validates: Requirements 5.3, 21.1, 21.3
    """
    # Check CUDA availability first
    try:
        import torch
        if not torch.cuda.is_available():
            logger.warning(
                "CUDA not available — LPIPS computation skipped. "
                "LPIPS requires GPU for model inference."
            )
            return None
    except ImportError:
        logger.warning(
            "PyTorch not available — LPIPS computation skipped. "
            "Install with: pip install torch"
        )
        return None

    try:
        import lpips as lpips_module
    except ImportError:
        logger.warning(
            "lpips package not available — LPIPS computation skipped. "
            "Install with: pip install lpips"
        )
        return None

    # Acquire VRAM lease if facade is provided (Req 21.1)
    lease_result = None
    if vram_lease is not None:
        try:
            from src.unified_pipeline.resource_arbiter import ResourceKind
            lease_result = vram_lease.acquire(ResourceKind.PERCEPTUAL_LPIPS)
            if not lease_result.acquired:
                logger.warning(
                    "VRAM lease not acquired for LPIPS: %s — metric skipped",
                    lease_result.status,
                )
                return None
        except Exception as exc:
            logger.warning(
                "VRAM lease acquisition failed for LPIPS: %s — proceeding without lease",
                exc,
            )

    computation_start = time.monotonic()
    try:
        img_a = _load_image_as_numpy(image_a)
        img_b = _load_image_as_numpy(image_b)
        _validate_image_pair(img_a, img_b)

        # Convert images to torch tensors: NxCxHxW, float, range [-1, 1]
        def _to_tensor(img: "NDArray[np.uint8]") -> "torch.Tensor":
            t = torch.from_numpy(img.copy()).permute(2, 0, 1).unsqueeze(0).float()
            t = t / 127.5 - 1.0  # Normalize to [-1, 1]
            return t.cuda()

        tensor_a = _to_tensor(img_a)
        tensor_b = _to_tensor(img_b)

        # Load LPIPS model (AlexNet backbone — lightweight, 2GB VRAM)
        loss_fn = lpips_module.LPIPS(net="alex").cuda()

        with torch.no_grad():
            distance = loss_fn(tensor_a, tensor_b)

        score = float(distance.item())
        logger.info("LPIPS computed: %.6f (lower is more similar)", score)

        # Mark computation done for release timing (Req 21.3)
        if vram_lease is not None:
            vram_lease.mark_computation_done()

        return score

    except (FileNotFoundError, ValueError, TypeError) as exc:
        logger.error("LPIPS computation failed: %s", exc)
        raise PerceptualMetricsError(f"LPIPS computation failed: {exc}") from exc
    except RuntimeError as exc:
        if "CUDA" in str(exc) or "out of memory" in str(exc).lower():
            logger.warning("LPIPS CUDA error — metric skipped: %s", exc)
            return None
        raise PerceptualMetricsError(f"LPIPS computation failed: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected error during LPIPS computation: %s", exc)
        return None
    finally:
        # Release VRAM lease within 5s deadline (Req 21.3)
        if vram_lease is not None and lease_result and lease_result.acquired:
            elapsed = time.monotonic() - computation_start
            if elapsed > _LEASE_RELEASE_DEADLINE_S:
                logger.warning(
                    "LPIPS: computation took %.2fs, release may exceed 5s deadline",
                    elapsed,
                )
            vram_lease.release()

        # Explicit GPU cleanup
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass


def compute_clip_cosine(
    image_a: ImageInput,
    image_b: ImageInput,
    *,
    vram_lease=None,
) -> float | None:
    """Compute CLIP cosine similarity between two images.

    Uses OpenAI's CLIP model to embed both images into a shared semantic
    space and computes cosine similarity. Higher values indicate greater
    semantic similarity (range -1.0 to 1.0, typically 0.5–1.0 for similar images).

    This metric requires CUDA/GPU for model inference. A VRAM lease from
    the Resource Arbiter must be acquired before calling this function.

    Args:
        image_a: First image (Canon reference).
        image_b: Second image (World screenshot).
        vram_lease: Optional VRAMLeaseFacade from the vram_lease fixture.
            If provided, the function will acquire/release the PERCEPTUAL_CLIP
            lease. If None, the caller is responsible for VRAM management.

    Returns:
        Float cosine similarity where higher is more similar (typically 0.5–1.0).
        Returns None if GPU/CUDA is unavailable or model cannot be loaded.

    Validates: Requirements 5.4, 21.1, 21.3
    """
    # Check CUDA availability first
    try:
        import torch
        if not torch.cuda.is_available():
            logger.warning(
                "CUDA not available — CLIP cosine computation skipped. "
                "CLIP requires GPU for model inference."
            )
            return None
    except ImportError:
        logger.warning(
            "PyTorch not available — CLIP cosine computation skipped. "
            "Install with: pip install torch"
        )
        return None

    # Check for transformers (Hugging Face CLIP) or open_clip
    clip_backend = None
    try:
        import transformers  # noqa: F401
        clip_backend = "transformers"
    except ImportError:
        pass

    if clip_backend is None:
        try:
            import open_clip  # noqa: F401
            clip_backend = "open_clip"
        except ImportError:
            pass

    if clip_backend is None:
        logger.warning(
            "Neither transformers nor open_clip available — CLIP cosine skipped. "
            "Install with: pip install transformers or pip install open_clip_torch"
        )
        return None

    # Acquire VRAM lease if facade is provided (Req 21.1)
    lease_result = None
    if vram_lease is not None:
        try:
            from src.unified_pipeline.resource_arbiter import ResourceKind
            lease_result = vram_lease.acquire(ResourceKind.PERCEPTUAL_CLIP)
            if not lease_result.acquired:
                logger.warning(
                    "VRAM lease not acquired for CLIP: %s — metric skipped",
                    lease_result.status,
                )
                return None
        except Exception as exc:
            logger.warning(
                "VRAM lease acquisition failed for CLIP: %s — proceeding without lease",
                exc,
            )

    computation_start = time.monotonic()
    try:
        from PIL import Image as PILImage

        img_a = _load_image_as_numpy(image_a)
        img_b = _load_image_as_numpy(image_b)
        _validate_image_pair(img_a, img_b)

        pil_a = PILImage.fromarray(img_a)
        pil_b = PILImage.fromarray(img_b)

        if clip_backend == "transformers":
            score = _compute_clip_cosine_transformers(pil_a, pil_b)
        else:
            score = _compute_clip_cosine_open_clip(pil_a, pil_b)

        logger.info("CLIP cosine computed: %.6f (higher is more similar)", score)

        # Mark computation done for release timing (Req 21.3)
        if vram_lease is not None:
            vram_lease.mark_computation_done()

        return score

    except (FileNotFoundError, ValueError, TypeError) as exc:
        logger.error("CLIP cosine computation failed: %s", exc)
        raise PerceptualMetricsError(
            f"CLIP cosine computation failed: {exc}"
        ) from exc
    except RuntimeError as exc:
        if "CUDA" in str(exc) or "out of memory" in str(exc).lower():
            logger.warning("CLIP CUDA error — metric skipped: %s", exc)
            return None
        raise PerceptualMetricsError(
            f"CLIP cosine computation failed: {exc}"
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error during CLIP cosine computation: %s", exc)
        return None
    finally:
        # Release VRAM lease within 5s deadline (Req 21.3)
        if vram_lease is not None and lease_result and lease_result.acquired:
            elapsed = time.monotonic() - computation_start
            if elapsed > _LEASE_RELEASE_DEADLINE_S:
                logger.warning(
                    "CLIP: computation took %.2fs, release may exceed 5s deadline",
                    elapsed,
                )
            vram_lease.release()

        # Explicit GPU cleanup
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass


def _compute_clip_cosine_transformers(pil_a, pil_b) -> float:
    """Compute CLIP cosine similarity using Hugging Face transformers."""
    import torch
    from transformers import CLIPModel, CLIPProcessor

    model_name = "openai/clip-vit-base-patch32"
    processor = CLIPProcessor.from_pretrained(model_name)
    model = CLIPModel.from_pretrained(model_name).cuda()

    with torch.no_grad():
        inputs_a = processor(images=pil_a, return_tensors="pt")
        inputs_b = processor(images=pil_b, return_tensors="pt")

        # Move inputs to GPU
        inputs_a = {k: v.cuda() for k, v in inputs_a.items()}
        inputs_b = {k: v.cuda() for k, v in inputs_b.items()}

        embed_a = model.get_image_features(**inputs_a)
        embed_b = model.get_image_features(**inputs_b)

    # Normalize embeddings
    embed_a = embed_a / embed_a.norm(dim=-1, keepdim=True)
    embed_b = embed_b / embed_b.norm(dim=-1, keepdim=True)

    # Cosine similarity
    cosine_sim = torch.nn.functional.cosine_similarity(embed_a, embed_b)
    return float(cosine_sim.item())


def _compute_clip_cosine_open_clip(pil_a, pil_b) -> float:
    """Compute CLIP cosine similarity using open_clip."""
    import torch
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model = model.cuda()

    with torch.no_grad():
        tensor_a = preprocess(pil_a).unsqueeze(0).cuda()
        tensor_b = preprocess(pil_b).unsqueeze(0).cuda()

        embed_a = model.encode_image(tensor_a)
        embed_b = model.encode_image(tensor_b)

    # Normalize embeddings
    embed_a = embed_a / embed_a.norm(dim=-1, keepdim=True)
    embed_b = embed_b / embed_b.norm(dim=-1, keepdim=True)

    # Cosine similarity
    cosine_sim = torch.nn.functional.cosine_similarity(embed_a, embed_b)
    return float(cosine_sim.item())


# ---------------------------------------------------------------------------
# Calibration support (Task 13.1 — Requirement 6.1–6.3)
# ---------------------------------------------------------------------------


@dataclass
class CalibrationResult:
    """Result of a calibration run across a corpus of known-good pairs.

    Attributes:
        metric_name: Name of the metric (ssim, lpips, clip_cosine).
        mean: Mean value across the corpus.
        std: Standard deviation across the corpus.
        min_value: Minimum observed value.
        max_value: Maximum observed value.
        recommended_threshold: Recommended threshold (mean - 2*std for high-is-good,
                               mean + 2*std for low-is-good).
        sample_count: Number of image pairs evaluated.
        values: All individual metric values computed.
    """

    metric_name: str
    mean: float
    std: float
    min_value: float
    max_value: float
    recommended_threshold: float
    sample_count: int
    values: list[float]


@dataclass
class CalibrationReport:
    """Full calibration report containing results for all metrics.

    Attributes:
        ssim: Calibration result for SSIM metric.
        lpips: Calibration result for LPIPS metric.
        clip_cosine: Calibration result for CLIP cosine metric.
        corpus_dir: Path to the calibration corpus used.
        timestamp: ISO timestamp of when calibration was performed.
        pair_count: Number of Canon/World pairs evaluated.
    """

    ssim: CalibrationResult | None
    lpips: CalibrationResult | None
    clip_cosine: CalibrationResult | None
    corpus_dir: str
    timestamp: str
    pair_count: int

    def to_dict(self) -> dict:
        """Serialize the report to a dictionary for JSON storage."""
        def _result_dict(r: CalibrationResult | None) -> dict | None:
            if r is None:
                return None
            return {
                "metric_name": r.metric_name,
                "mean": r.mean,
                "std": r.std,
                "min_value": r.min_value,
                "max_value": r.max_value,
                "recommended_threshold": r.recommended_threshold,
                "sample_count": r.sample_count,
                "values": r.values,
            }

        return {
            "ssim": _result_dict(self.ssim),
            "lpips": _result_dict(self.lpips),
            "clip_cosine": _result_dict(self.clip_cosine),
            "corpus_dir": self.corpus_dir,
            "timestamp": self.timestamp,
            "pair_count": self.pair_count,
        }



def _compute_calibration_stats(
    values: list[float], metric_name: str, higher_is_better: bool
) -> CalibrationResult:
    """Compute calibration statistics from a list of metric values.

    Args:
        values: List of computed metric values.
        metric_name: Name of the metric.
        higher_is_better: If True, recommended threshold is mean - 2*std;
                          if False, threshold is mean + 2*std.

    Returns:
        CalibrationResult with statistics and recommended threshold.
    """
    arr = np.array(values, dtype=np.float64)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    if higher_is_better:
        # For SSIM, CLIP: threshold is below the mean (we want >= threshold)
        recommended = mean - 2.0 * std
    else:
        # For LPIPS: threshold is above the mean (we want <= threshold)
        recommended = mean + 2.0 * std

    return CalibrationResult(
        metric_name=metric_name,
        mean=mean,
        std=std,
        min_value=float(np.min(arr)),
        max_value=float(np.max(arr)),
        recommended_threshold=recommended,
        sample_count=len(values),
        values=values,
    )


def calibrate(
    corpus_dir: Union[str, Path],
    *,
    output_path: Union[str, Path, None] = None,
) -> CalibrationReport:
    """Run calibration across a corpus of known-good Canon/World image pairs.

    Scans `corpus_dir` for paired images following the naming convention:
    - `{name}_canon.png` / `{name}_world.png`
    - Or subdirectories each containing `canon.png` and `world.png`

    Computes SSIM (and LPIPS/CLIP if GPU is available) across all pairs,
    then reports mean, standard deviation, and recommended thresholds.

    Args:
        corpus_dir: Path to the calibration corpus directory containing
                    known-good Canon/World pairs.
        output_path: If provided, writes calibration results as JSON to this path.

    Returns:
        CalibrationReport with per-metric statistics and recommendations.

    Raises:
        FileNotFoundError: If corpus_dir does not exist.
        ValueError: If no valid image pairs are found in the corpus.

    Validates: Requirements 6.1, 6.2, 6.3
    """
    import json
    from datetime import datetime, timezone

    corpus_path = Path(corpus_dir)
    if not corpus_path.exists():
        raise FileNotFoundError(f"Calibration corpus directory not found: {corpus_path}")

    # Discover Canon/World pairs
    pairs = _discover_image_pairs(corpus_path)
    if not pairs:
        raise ValueError(
            f"No valid Canon/World image pairs found in {corpus_path}. "
            f"Expected either {{name}}_canon.png/{{name}}_world.png files "
            f"or subdirectories with canon.png/world.png."
        )

    logger.info("Calibration: found %d Canon/World pairs in %s", len(pairs), corpus_path)

    # Compute metrics across all pairs
    ssim_values: list[float] = []
    lpips_values: list[float] = []
    clip_values: list[float] = []

    for canon_path, world_path in pairs:
        # SSIM (CPU-based, always available)
        ssim_val = compute_ssim(canon_path, world_path)
        if ssim_val is not None:
            ssim_values.append(ssim_val)

        # LPIPS (GPU-required)
        lpips_val = compute_lpips(canon_path, world_path)
        if lpips_val is not None:
            lpips_values.append(lpips_val)

        # CLIP cosine (GPU-required)
        clip_val = compute_clip_cosine(canon_path, world_path)
        if clip_val is not None:
            clip_values.append(clip_val)

    # Compute statistics per metric
    ssim_result = (
        _compute_calibration_stats(ssim_values, "ssim", higher_is_better=True)
        if ssim_values
        else None
    )
    lpips_result = (
        _compute_calibration_stats(lpips_values, "lpips", higher_is_better=False)
        if lpips_values
        else None
    )
    clip_result = (
        _compute_calibration_stats(clip_values, "clip_cosine", higher_is_better=True)
        if clip_values
        else None
    )

    timestamp = datetime.now(timezone.utc).isoformat()

    report = CalibrationReport(
        ssim=ssim_result,
        lpips=lpips_result,
        clip_cosine=clip_result,
        corpus_dir=str(corpus_path),
        timestamp=timestamp,
        pair_count=len(pairs),
    )

    # Store calibration results as JSON if output path is provided
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.info("Calibration results written to %s", output)

    return report


def _discover_image_pairs(corpus_dir: Path) -> list[tuple[Path, Path]]:
    """Discover Canon/World image pairs in the corpus directory.

    Supports two naming conventions:
    1. Flat: {name}_canon.png + {name}_world.png in the corpus directory
    2. Subdirectory: {subdir}/canon.png + {subdir}/world.png

    Returns:
        List of (canon_path, world_path) tuples.
    """
    pairs: list[tuple[Path, Path]] = []

    # Strategy 1: Look for subdirectories with canon.png and world.png
    for subdir in sorted(corpus_dir.iterdir()):
        if subdir.is_dir():
            canon = _find_image(subdir, "canon")
            world = _find_image(subdir, "world")
            if canon and world:
                pairs.append((canon, world))

    # Strategy 2: Look for {name}_canon.{ext} and {name}_world.{ext} pairs
    canon_files: dict[str, Path] = {}
    world_files: dict[str, Path] = {}

    for f in sorted(corpus_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
            stem = f.stem.lower()
            if stem.endswith("_canon"):
                name = stem[:-6]  # Remove _canon
                canon_files[name] = f
            elif stem.endswith("_world"):
                name = stem[:-6]  # Remove _world
                world_files[name] = f

    for name in sorted(set(canon_files.keys()) & set(world_files.keys())):
        pairs.append((canon_files[name], world_files[name]))

    return pairs


def _find_image(directory: Path, prefix: str) -> Path | None:
    """Find an image file with the given prefix in a directory."""
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = directory / f"{prefix}{ext}"
        if candidate.exists():
            return candidate
    return None
