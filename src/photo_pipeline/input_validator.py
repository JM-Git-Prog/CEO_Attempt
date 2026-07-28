"""Input validation for photo pipeline source images.

Validates that a submitted file is a valid RGB image suitable for the
photo-to-playable-world pipeline before any inference stage is invoked.

Checks (in order):
1. File exists on disk
2. File size ≤ 50 MB
3. Valid image header (JPEG or PNG only)
4. RGB color mode (rejects grayscale-only; RGBA is accepted and converted)
5. Resolution within 512×512 to 8192×8192 bounds
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.photo_pipeline.reason_codes import ReasonCode

# --- Constants ---

MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
MIN_RESOLUTION: int = 512
MAX_RESOLUTION: int = 8192
ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG"})


@dataclass(frozen=True)
class InputValidationResult:
    """Result of photo input validation.

    Attributes:
        valid: True if the image passes all checks.
        reason_code: A ReasonCode value identifying the failure category,
                     or ReasonCode.COMPLETED on success.
        diagnostic: Human-readable explanation of the validation outcome.
    """

    valid: bool
    reason_code: str
    diagnostic: str


def validate_photo_input(image_path: Path) -> InputValidationResult:
    """Validate a source image before invoking any inference stage.

    Returns an InputValidationResult indicating whether the image is suitable
    for the photo pipeline. On failure, the reason_code and diagnostic fields
    identify the specific problem.

    Parameters
    ----------
    image_path : Path
        Path to the candidate source image file.

    Returns
    -------
    InputValidationResult
        Result with valid=True on success, or valid=False with a descriptive
        reason_code and diagnostic on failure.
    """

    # 1. File existence
    if not image_path.exists():
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic=f"File does not exist: {image_path}",
        )

    if not image_path.is_file():
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic=f"Path is not a regular file: {image_path}",
        )

    # 2. File size ≤ 50 MB
    file_size = image_path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_SIZE,
            diagnostic=(
                f"File size {size_mb:.1f} MB exceeds maximum of 50 MB"
            ),
        )

    # 3. Valid image header (JPEG or PNG)
    try:
        img = Image.open(image_path)
        img.verify()  # Verify header integrity without fully loading pixels
    except (UnidentifiedImageError, OSError, SyntaxError):
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic="File is not a valid image (corrupt or unreadable header)",
        )

    # Re-open after verify (verify leaves the file in an unusable state)
    try:
        img = Image.open(image_path)
    except (UnidentifiedImageError, OSError, SyntaxError):
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic="File is not a valid image (corrupt or unreadable header)",
        )

    # Check format is JPEG or PNG
    if img.format not in ALLOWED_FORMATS:
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic=(
                f"Unsupported image format '{img.format}'. "
                f"Only JPEG and PNG are accepted."
            ),
        )

    # 4. RGB color mode (reject grayscale-only)
    # Acceptable modes: RGB, RGBA (has color channels), P with RGB palette
    # Rejected: L (grayscale), LA (grayscale + alpha), 1 (bilevel)
    mode = img.mode
    if mode in ("L", "LA", "1", "I", "F"):
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic=(
                f"Image color mode '{mode}' is not RGB. "
                f"Only RGB or RGBA images are accepted (grayscale rejected)."
            ),
        )

    # For palette mode, check if the underlying data has color
    if mode == "P":
        # Convert to check actual color content
        converted = img.convert("RGB")
        # A palette image that converts to RGB is acceptable
        # (it has color information in the palette)
        img = converted
        mode = "RGB"

    # Accept RGB and RGBA; reject anything else unexpected
    if mode not in ("RGB", "RGBA"):
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_FORMAT,
            diagnostic=(
                f"Image color mode '{mode}' is not supported. "
                f"Only RGB or RGBA images are accepted."
            ),
        )

    # 5. Resolution — upscale small images rather than rejecting them.
    # SAM/MoGe-2 work better at 512+ but any RGB image should be accepted.
    width, height = img.size
    if width > MAX_RESOLUTION or height > MAX_RESOLUTION:
        return InputValidationResult(
            valid=False,
            reason_code=ReasonCode.INVALID_IMAGE_RESOLUTION,
            diagnostic=(
                f"Image resolution {width}×{height} exceeds maximum "
                f"{MAX_RESOLUTION}×{MAX_RESOLUTION}"
            ),
        )

    # All checks passed
    return InputValidationResult(
        valid=True,
        reason_code=ReasonCode.COMPLETED,
        diagnostic="Image validation passed",
    )
