"""Machine-readable reason codes for photo pipeline stage outcomes."""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    """Reason codes reported by pipeline stages in StageResult.reason_code.

    Each code maps to a specific success or failure mode so that callers can
    programmatically branch on outcome without parsing diagnostic text.
    """

    # Success codes
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FALLBACK = "COMPLETED_WITH_FALLBACK"

    # Input validation failures
    INVALID_IMAGE_FORMAT = "INVALID_IMAGE_FORMAT"
    INVALID_IMAGE_RESOLUTION = "INVALID_IMAGE_RESOLUTION"
    INVALID_IMAGE_SIZE = "INVALID_IMAGE_SIZE"

    # ComfyUI connectivity / workflow errors
    COMFYUI_UNREACHABLE = "COMFYUI_UNREACHABLE"
    COMFYUI_WORKFLOW_ERROR = "COMFYUI_WORKFLOW_ERROR"

    # Stage-specific failures
    SEGMENTATION_FAILED = "SEGMENTATION_FAILED"
    INPAINTING_FAILED = "INPAINTING_FAILED"
    DEPTH_ESTIMATION_FAILED = "DEPTH_ESTIMATION_FAILED"
    OBJECT_GENERATION_FAILED = "OBJECT_GENERATION_FAILED"
    OBJECT_GENERATION_TIMEOUT = "OBJECT_GENERATION_TIMEOUT"
    AUDIO_SYNTHESIS_FAILED = "AUDIO_SYNTHESIS_FAILED"
    LIGHT_ESTIMATION_FAILED = "LIGHT_ESTIMATION_FAILED"
    SCALE_CALIBRATION_FAILED = "SCALE_CALIBRATION_FAILED"
    LAYOUT_ESTIMATION_FAILED = "LAYOUT_ESTIMATION_FAILED"

    # Physics / collision failures
    PHYSICS_SETTLE_TIMEOUT = "PHYSICS_SETTLE_TIMEOUT"
    VHACD_TIMEOUT = "VHACD_TIMEOUT"

    # Assembly / validation failures
    WORLDCONTRACT_VALIDATION_FAILED = "WORLDCONTRACT_VALIDATION_FAILED"

    # Compilation chain failures
    COMPILATION_FAILED = "COMPILATION_FAILED"

    # Pipeline-level timeout
    PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
