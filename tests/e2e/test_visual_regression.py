"""Visual regression tests for the V16 Unified World Pipeline.

Tests each pipeline stage (dream_preview, blockout, canon, world) by:
1. Capturing a screenshot at a configured camera pose using ScreenshotCapture
2. Checking if a golden baseline exists via BaselineManager
3. If no baseline: saving the current capture as a new baseline (not failure)
4. If baseline exists: comparing via PixelDiff with per-stage thresholds
5. On pass: test passes
6. On fail: storing expected baseline, actual screenshot, and diff image in artifacts

All tests use @pytest.mark.layer("visual") for 120s budget enforcement.

Requirements: 2.1–2.5, 3.1–3.5, 22.1, 23.1
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.baseline_manager import BaselineManager
from tests.e2e.framework.config_loader import E2EConfig, StageConfig
from tests.e2e.framework.deterministic_render import detect_hardware_id
from tests.e2e.framework.pixel_diff import PixelDiff
from tests.e2e.framework.screenshot_capture import CameraPose, ScreenshotCapture


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default camera poses per stage (used when config doesn't provide them).
# These represent reasonable defaults for each pipeline stage.
_DEFAULT_CAMERA_POSES: dict[str, dict[str, Any]] = {
    "dream_preview": {
        "position": [0, 1.6, 5.0],
        "target": [0, 1.0, 0],
        "up": [0, 1, 0],
        "vfov": 60,
    },
    "blockout": {
        "position": [0, 1.6, 5.0],
        "target": [0, 1.0, 0],
        "up": [0, 1, 0],
        "vfov": 60,
    },
    "canon": {
        "position": [0, 1.6, 3.0],
        "target": [0, 1.0, 0],
        "up": [0, 1, 0],
        "vfov": 60,
    },
    "world": {
        "position": [0, 1.6, 3.0],
        "target": [0, 1.0, 0],
        "up": [0, 1, 0],
        "vfov": 60,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_model_version() -> str:
    """Read the pipeline model version from config or environment.

    Checks (in order):
    1. E2E_MODEL_VERSION environment variable
    2. Falls back to a default version string

    Returns:
        The pipeline model version identifier string.
    """
    env_version = os.environ.get("E2E_MODEL_VERSION")
    if env_version and env_version.strip():
        return env_version.strip()

    # Default version based on the current pipeline
    return "v16-model-default"


def _get_camera_pose_for_stage(stage_name: str) -> dict[str, Any]:
    """Get the camera pose configuration for a pipeline stage.

    Uses the default camera poses defined above. In the future this could
    load from the E2E config or WorldContract.

    Args:
        stage_name: Pipeline stage name.

    Returns:
        Camera pose dict with position, target, up, and vfov keys.
    """
    return _DEFAULT_CAMERA_POSES.get(stage_name, _DEFAULT_CAMERA_POSES["world"])


def _is_stage_enabled(e2e_config: E2EConfig, stage_name: str) -> bool:
    """Check whether a stage is enabled for visual regression testing.

    Args:
        e2e_config: The loaded E2E configuration.
        stage_name: Pipeline stage name.

    Returns:
        True if the stage is enabled, False otherwise.
    """
    stage_cfg = e2e_config.visual_regression.stages.get(stage_name)
    if stage_cfg is None:
        return False
    return stage_cfg.enabled


async def _run_visual_regression_for_stage(
    page: Any,
    stage_name: str,
    e2e_config: E2EConfig,
    artifact_store: ArtifactStore,
) -> None:
    """Run the visual regression workflow for a single pipeline stage.

    Flow:
    1. Capture screenshot at configured camera pose
    2. Check if baseline exists
    3. If no baseline: save as new baseline, mark "baseline created"
    4. If baseline exists: compare via PixelDiff
    5. On fail: store expected, actual, and diff in artifacts

    Args:
        page: Playwright page loaded with ?qa=1.
        stage_name: Pipeline stage (dream_preview, blockout, canon, world).
        e2e_config: The validated E2E configuration.
        artifact_store: The per-run artifact store.

    Raises:
        pytest.skip: If the stage is not enabled.
        AssertionError: If the pixel diff comparison fails.
    """
    # Skip disabled stages
    if not _is_stage_enabled(e2e_config, stage_name):
        pytest.skip(f"Stage '{stage_name}' is disabled in configuration")

    # Get model version and hardware ID for baseline keying
    model_version = get_model_version()
    hardware_id = detect_hardware_id()

    # Initialize components
    capture = ScreenshotCapture(
        artifact_store=artifact_store,
        model_version=model_version,
    )
    baseline_mgr = BaselineManager(
        model_version=model_version,
        hardware_id=hardware_id,
    )
    pixel_diff = PixelDiff(
        stage_thresholds={
            name: cfg.diff_threshold_pct
            for name, cfg in e2e_config.visual_regression.stages.items()
        }
    )

    # Get camera pose for this stage
    camera_pose = _get_camera_pose_for_stage(stage_name)

    # 1. Capture screenshot
    capture_result = await capture.capture_stage(
        page=page,
        stage_name=stage_name,
        camera_pose=camera_pose,
    )

    # Load the captured screenshot as a PIL Image for comparison
    actual_image_path = Path(capture_result.artifact_path)
    actual_image = Image.open(actual_image_path)

    # 2. Check if baseline exists
    if not baseline_mgr.baseline_exists(stage_name):
        # 3. No baseline — save current as new baseline (Req 3.3)
        actual_bytes = actual_image_path.read_bytes()
        baseline_mgr.save_baseline(
            stage=stage_name,
            image=actual_bytes,
            metadata={
                "camera_pose": camera_pose,
                "viewport": list(e2e_config.visual_regression.default_viewport),
                "deterministic_seed": e2e_config.visual_regression.deterministic_seed,
            },
        )
        pytest.skip(
            f"Baseline created for stage '{stage_name}' "
            f"(model: {model_version}, hardware: {hardware_id}). "
            f"Run tests again to compare against this baseline."
        )
        return

    # 4. Baseline exists — compare via PixelDiff
    baseline_result = baseline_mgr.get_baseline(stage_name)
    assert baseline_result is not None, (
        f"baseline_exists() returned True but get_baseline() returned None "
        f"for stage '{stage_name}'"
    )

    # Load baseline as PIL Image
    baseline_image = Image.open(baseline_result.image_path)

    # Get the diff output directory (visual layer in artifact store)
    diff_output_dir = artifact_store.get_artifact_path("visual", "").parent / "visual"

    # Perform pixel comparison
    diff_result = pixel_diff.compare(
        expected=baseline_image,
        actual=actual_image,
        stage_name=stage_name,
        diff_output_dir=diff_output_dir,
        diff_filename=f"diff_{stage_name}.png",
    )

    # 5. On pass: test passes
    if diff_result.passed:
        return

    # 6. On fail: store expected baseline, actual screenshot, and diff in artifacts
    # Store the baseline (expected) image in artifacts for comparison
    artifact_store.store_artifact(
        layer="visual",
        filename=f"expected_{stage_name}.png",
        data=baseline_result.image_path.read_bytes(),
    )

    # The actual screenshot is already stored by capture_stage.
    # Store a copy with a clear "actual_" prefix for easy identification.
    artifact_store.store_artifact(
        layer="visual",
        filename=f"actual_{stage_name}.png",
        data=actual_image_path.read_bytes(),
    )

    # Format the failure message with artifact path (Req 23.5)
    failure_msg = artifact_store.failure_message(
        layer="visual",
        test_name=f"test_visual_regression_{stage_name}",
        details=(
            f"Visual regression detected for stage '{stage_name}':\n"
            f"  Diff pixels: {diff_result.diff_pixel_count} / {diff_result.total_pixels}\n"
            f"  Diff percentage: {diff_result.diff_percentage:.4f}%\n"
            f"  Threshold: {pixel_diff.get_threshold(stage_name):.4f}%\n"
            f"  Diff image: {diff_result.diff_image_path}"
        ),
    )
    pytest.fail(failure_msg)


# ---------------------------------------------------------------------------
# Test functions — one per pipeline stage
# ---------------------------------------------------------------------------


@pytest.mark.layer("visual")
@pytest.mark.asyncio
async def test_visual_regression_dream_preview(
    page: Any,
    e2e_config: E2EConfig,
    artifact_store: ArtifactStore,
) -> None:
    """Visual regression test for the dream_preview stage.

    Captures a screenshot of the Dream Preview render and compares it against
    the golden baseline. Threshold: 1.0% diff pixels allowed.

    Requirements: 2.1, 3.1–3.5, 22.1, 23.1
    """
    await _run_visual_regression_for_stage(
        page=page,
        stage_name="dream_preview",
        e2e_config=e2e_config,
        artifact_store=artifact_store,
    )


@pytest.mark.layer("visual")
@pytest.mark.asyncio
async def test_visual_regression_blockout(
    page: Any,
    e2e_config: E2EConfig,
    artifact_store: ArtifactStore,
) -> None:
    """Visual regression test for the blockout stage.

    Captures a screenshot of the Blockout render and compares it against
    the golden baseline. Threshold: 1.0% diff pixels allowed.

    Requirements: 2.2, 3.1–3.5, 22.1, 23.1
    """
    await _run_visual_regression_for_stage(
        page=page,
        stage_name="blockout",
        e2e_config=e2e_config,
        artifact_store=artifact_store,
    )


@pytest.mark.layer("visual")
@pytest.mark.asyncio
async def test_visual_regression_canon(
    page: Any,
    e2e_config: E2EConfig,
    artifact_store: ArtifactStore,
) -> None:
    """Visual regression test for the canon stage.

    Captures a screenshot of the Canon render and compares it against
    the golden baseline. Threshold: 0.1% diff pixels allowed (tighter
    since Canon is the reference for perceptual identity).

    Requirements: 2.3, 3.1–3.5, 22.1, 23.1
    """
    await _run_visual_regression_for_stage(
        page=page,
        stage_name="canon",
        e2e_config=e2e_config,
        artifact_store=artifact_store,
    )


@pytest.mark.layer("visual")
@pytest.mark.asyncio
async def test_visual_regression_world(
    page: Any,
    e2e_config: E2EConfig,
    artifact_store: ArtifactStore,
) -> None:
    """Visual regression test for the world stage.

    Captures a screenshot of the final World render from the
    WorldContract-defined camera pose and compares it against the golden
    baseline. Threshold: 0.1% diff pixels allowed.

    Requirements: 2.4, 3.1–3.5, 22.1, 23.1
    """
    await _run_visual_regression_for_stage(
        page=page,
        stage_name="world",
        e2e_config=e2e_config,
        artifact_store=artifact_store,
    )
