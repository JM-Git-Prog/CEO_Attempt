"""Screenshot capture module for E2E visual regression tests.

Captures Playwright screenshots at fixed camera poses for each pipeline stage.
Filenames encode stage name, pipeline model version, and capture timestamp in a
format that can be unambiguously parsed back (round-trippable).

Filename format: {stage_name}_{model_version}_{timestamp}.png
  - stage_name: pipeline stage (dream_preview, blockout, canon, world)
  - model_version: pipeline model version identifier (e.g. v16-model-a1b2c3)
  - timestamp: ISO 8601 without colons, filesystem-safe (e.g. 20260730T142200Z)

Requirements: 2.1–2.5, 1.1
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.deterministic_render import (
    DeterministicRenderConfig,
    DeterministicRenderError,
    verify_determinism,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Separator between filename components. Double underscore avoids ambiguity
# since stage names use single underscores (e.g. dream_preview).
_FIELD_SEP = "__"

# Regex for parsing filenames back into components.
# Groups: stage_name, model_version, timestamp
_FILENAME_PATTERN = re.compile(
    r"^(?P<stage_name>[a-z][a-z0-9_]*)__(?P<model_version>[A-Za-z0-9][A-Za-z0-9._-]*)__(?P<timestamp>\d{8}T\d{6}Z)\.png$"
)

# Timestamp format used in filenames — ISO 8601 basic without colons.
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraPose:
    """Camera pose definition for screenshot capture.

    Attributes:
        position: Camera position as [x, y, z].
        target: Look-at target as [x, y, z].
        up: Up vector as [x, y, z].
        vfov: Vertical field of view in degrees.
    """

    position: list[float]
    target: list[float]
    up: list[float]
    vfov: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraPose:
        """Create a CameraPose from a dictionary.

        Args:
            data: Dict with keys position, target, up, vfov.

        Returns:
            A CameraPose instance.

        Raises:
            ValueError: If required keys are missing.
        """
        required_keys = {"position", "target", "up", "vfov"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"CameraPose missing required keys: {sorted(missing)}"
            )
        return cls(
            position=list(data["position"]),
            target=list(data["target"]),
            up=list(data["up"]),
            vfov=float(data["vfov"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "position": self.position,
            "target": self.target,
            "up": self.up,
            "vfov": self.vfov,
        }


@dataclass(frozen=True)
class CaptureResult:
    """Result of a screenshot capture operation.

    Attributes:
        filename: The generated filename (without directory path).
        stage_name: The pipeline stage that was captured.
        model_version: The pipeline model version.
        timestamp: The capture timestamp (UTC).
        artifact_path: Full filesystem path where the screenshot was stored.
        camera_pose: The camera pose used for capture.
    """

    filename: str
    stage_name: str
    model_version: str
    timestamp: datetime
    artifact_path: str
    camera_pose: CameraPose


@dataclass(frozen=True)
class ParsedFilename:
    """Components parsed from a screenshot filename.

    Attributes:
        stage_name: The pipeline stage name.
        model_version: The pipeline model version string.
        timestamp: The capture timestamp (UTC).
    """

    stage_name: str
    model_version: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ScreenshotCaptureError(Exception):
    """Raised when screenshot capture fails."""


class FilenameParseError(Exception):
    """Raised when a filename cannot be parsed back into components."""


# ---------------------------------------------------------------------------
# Filename helpers (public — used by Property 2 tests)
# ---------------------------------------------------------------------------


def generate_filename(
    stage_name: str,
    model_version: str,
    timestamp: datetime | None = None,
) -> str:
    """Generate a screenshot filename encoding stage, version, and timestamp.

    The filename format uses double-underscore separators to avoid ambiguity
    with stage names that contain single underscores (e.g. dream_preview).

    Format: {stage_name}__{model_version}__{timestamp}.png

    Args:
        stage_name: Pipeline stage (e.g. "dream_preview", "canon").
        model_version: Pipeline model version (e.g. "v16-model-a1b2c3").
        timestamp: Capture time (UTC). Defaults to now.

    Returns:
        The generated filename string.

    Raises:
        ValueError: If stage_name or model_version contain invalid characters.
    """
    if not stage_name or not re.match(r"^[a-z][a-z0-9_]*$", stage_name):
        raise ValueError(
            f"stage_name must be lowercase alphanumeric with underscores, "
            f"starting with a letter. Got: {stage_name!r}"
        )

    if not model_version or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", model_version):
        raise ValueError(
            f"model_version must be alphanumeric (with dots, hyphens, underscores), "
            f"starting with alphanumeric. Got: {model_version!r}"
        )

    # Double-underscore in model_version would break parsing
    if _FIELD_SEP in model_version:
        raise ValueError(
            f"model_version must not contain '{_FIELD_SEP}'. Got: {model_version!r}"
        )

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    ts_str = timestamp.strftime(_TIMESTAMP_FORMAT)
    return f"{stage_name}{_FIELD_SEP}{model_version}{_FIELD_SEP}{ts_str}.png"


def parse_filename(filename: str) -> ParsedFilename:
    """Parse a screenshot filename back into its components.

    This is the inverse of generate_filename — validates that the encoding
    is round-trippable (Property 2: Screenshot Filename Encoding Completeness).

    Args:
        filename: A filename string (with or without directory path).

    Returns:
        ParsedFilename with stage_name, model_version, and timestamp.

    Raises:
        FilenameParseError: If the filename does not match the expected format.
    """
    # Strip any directory prefix — only parse the basename
    basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    match = _FILENAME_PATTERN.match(basename)
    if not match:
        raise FilenameParseError(
            f"Filename does not match expected format "
            f"'{{stage}}_{{version}}_{{timestamp}}.png'. Got: {basename!r}"
        )

    stage_name = match.group("stage_name")
    model_version = match.group("model_version")
    ts_str = match.group("timestamp")

    try:
        timestamp = datetime.strptime(ts_str, _TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError as e:
        raise FilenameParseError(
            f"Failed to parse timestamp '{ts_str}' from filename: {e}"
        ) from e

    return ParsedFilename(
        stage_name=stage_name,
        model_version=model_version,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ScreenshotCapture:
    """Captures Playwright screenshots at fixed camera poses for pipeline stages.

    Verifies deterministic render settings before capturing, generates filenames
    encoding stage/version/timestamp, and stores captures via ArtifactStore.

    Usage:
        capture = ScreenshotCapture(
            artifact_store=store,
            model_version="v16-model-a1b2c3",
        )
        result = await capture.capture_stage(
            page=playwright_page,
            stage_name="canon",
            camera_pose={"position": [0, 1.6, 3], "target": [0, 1, 0],
                         "up": [0, 1, 0], "vfov": 60},
        )
    """

    def __init__(
        self,
        artifact_store: ArtifactStore,
        model_version: str,
        render_config: DeterministicRenderConfig | None = None,
    ) -> None:
        """Initialize the screenshot capture module.

        Args:
            artifact_store: Store for saving captured screenshots.
            model_version: Pipeline model version string (encoded in filenames).
            render_config: Deterministic render configuration. Defaults to
                          standard settings (antialias off, seed 42, etc.).

        Raises:
            ValueError: If model_version is empty or invalid.
        """
        if not model_version or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._-]*$", model_version
        ):
            raise ValueError(
                f"model_version must be alphanumeric (with dots, hyphens, "
                f"underscores), starting with alphanumeric. Got: {model_version!r}"
            )
        if _FIELD_SEP in model_version:
            raise ValueError(
                f"model_version must not contain '{_FIELD_SEP}'. "
                f"Got: {model_version!r}"
            )

        self._artifact_store = artifact_store
        self._model_version = model_version
        self._render_config = render_config or DeterministicRenderConfig()

    @property
    def model_version(self) -> str:
        """The pipeline model version used in filenames."""
        return self._model_version

    @property
    def render_config(self) -> DeterministicRenderConfig:
        """The deterministic render configuration."""
        return self._render_config

    async def capture_stage(
        self,
        page: Any,
        stage_name: str,
        camera_pose: dict[str, Any] | CameraPose,
    ) -> CaptureResult:
        """Capture a screenshot for a pipeline stage.

        This method:
        1. Verifies deterministic render settings are active
        2. Sets the camera to the specified pose
        3. Captures the screenshot via Playwright
        4. Generates a filename encoding stage/version/timestamp
        5. Stores the capture via ArtifactStore in the "visual" layer

        Args:
            page: A Playwright page object with window.__qa available.
            stage_name: The pipeline stage (e.g. "dream_preview", "canon").
            camera_pose: Camera pose as a dict with position/target/up/vfov
                        keys, or a CameraPose instance.

        Returns:
            CaptureResult with filename, paths, and metadata.

        Raises:
            ScreenshotCaptureError: If capture fails (render not deterministic,
                                    page error, or storage failure).
            DeterministicRenderError: If renderer settings are not deterministic.
        """
        # Normalize camera pose
        if isinstance(camera_pose, dict):
            try:
                pose = CameraPose.from_dict(camera_pose)
            except (ValueError, KeyError, TypeError) as e:
                raise ScreenshotCaptureError(
                    f"Invalid camera_pose dict: {e}"
                ) from e
        else:
            pose = camera_pose

        # 1. Verify deterministic render settings
        try:
            await verify_determinism(page)
        except DeterministicRenderError:
            raise  # Let DeterministicRenderError propagate as-is

        # 2. Set camera pose via window.__qa (if supported)
        await self._set_camera_pose(page, pose)

        # 3. Wait for render to stabilize then capture screenshot
        capture_time = datetime.now(timezone.utc)
        try:
            screenshot_bytes = await self._capture_screenshot(page)
        except Exception as e:
            raise ScreenshotCaptureError(
                f"Failed to capture screenshot for stage '{stage_name}': {e}"
            ) from e

        # 4. Generate filename
        filename = generate_filename(stage_name, self._model_version, capture_time)

        # 5. Store via ArtifactStore in the "visual" layer
        try:
            artifact_path = self._artifact_store.store_artifact(
                layer="visual",
                filename=filename,
                data=screenshot_bytes,
            )
        except Exception as e:
            raise ScreenshotCaptureError(
                f"Failed to store screenshot artifact '{filename}': {e}"
            ) from e

        return CaptureResult(
            filename=filename,
            stage_name=stage_name,
            model_version=self._model_version,
            timestamp=capture_time,
            artifact_path=str(artifact_path),
            camera_pose=pose,
        )

    async def _set_camera_pose(self, page: Any, pose: CameraPose) -> None:
        """Set the camera pose via the QA harness.

        Calls a JavaScript expression to position the camera at the specified
        pose. If the QA harness doesn't support setCameraPose, this is a
        best-effort operation that logs a warning rather than failing.

        Args:
            page: Playwright page.
            pose: Target camera pose.
        """
        # Check if setCameraPose is available (may not be in all QA harness versions)
        has_set_pose = await page.evaluate(
            "() => typeof window.__qa !== 'undefined' && "
            "typeof window.__qa.setCameraPose === 'function'"
        )

        if has_set_pose:
            await page.evaluate(
                """(pose) => window.__qa.setCameraPose(pose)""",
                pose.to_dict(),
            )
            # Wait a frame for camera to update
            await page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(resolve))"
            )
        else:
            # If setCameraPose isn't available, use manual camera manipulation
            # via Three.js camera properties through __qa or direct script
            await page.evaluate(
                """(pose) => {
                    if (window.__qa && window.__qa._camera) {
                        const cam = window.__qa._camera;
                        cam.position.set(pose.position[0], pose.position[1], pose.position[2]);
                        cam.lookAt(pose.target[0], pose.target[1], pose.target[2]);
                        cam.fov = pose.vfov;
                        cam.updateProjectionMatrix();
                    }
                }""",
                pose.to_dict(),
            )
            # Wait a frame for the render to reflect the new pose
            await page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(resolve))"
            )

    async def _capture_screenshot(self, page: Any) -> bytes:
        """Capture a PNG screenshot from the Playwright page.

        Uses the deterministic render config viewport dimensions to ensure
        consistent capture size.

        Args:
            page: Playwright page.

        Returns:
            PNG image data as bytes.
        """
        # Set viewport to match deterministic config
        await page.set_viewport_size(
            {
                "width": self._render_config.viewport_width,
                "height": self._render_config.viewport_height,
            }
        )

        # Force a render cycle to ensure the frame is current
        await page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => "
            "requestAnimationFrame(resolve)))"
        )

        # Capture the full page screenshot as PNG
        screenshot_bytes = await page.screenshot(type="png", full_page=False)

        return screenshot_bytes
