"""Deterministic render configuration for E2E visual regression tests.

Ensures Three.js renders produce byte-identical PNG output across consecutive
runs on the same hardware by disabling non-deterministic features and fixing
all random state.

The hardware ID (GPU model + driver version hash) is used to key baseline
directories so different hardware produces separate baselines rather than
false failures.

Requirements: 1.1, 1.2, 1.3
"""
from __future__ import annotations

import hashlib
import platform
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any


class DeterministicRenderError(Exception):
    """Raised when deterministic render configuration or verification fails."""


@dataclass(frozen=True)
class DeterministicRenderConfig:
    """Configuration for deterministic Three.js rendering.

    All settings are chosen to eliminate sources of non-determinism in WebGL
    rendering so that pixel comparisons are reliable across consecutive runs
    on identical hardware.

    Attributes:
        antialias: Disable antialiasing to eliminate driver-specific smoothing.
        preserve_draw_buffer: Keep framebuffer contents for screenshot capture.
        seed: Fixed random seed for shader noise and procedural effects.
        viewport_width: Fixed viewport width in pixels.
        viewport_height: Fixed viewport height in pixels.
        output_color_space: Explicit color space (not driver default).
    """

    antialias: bool = False
    preserve_draw_buffer: bool = True
    seed: int = 42
    viewport_width: int = 1920
    viewport_height: int = 1080
    output_color_space: str = "SRGBColorSpace"

    def to_renderer_args(self) -> dict[str, Any]:
        """Convert config to Three.js WebGLRenderer constructor arguments.

        Returns:
            Dictionary suitable for passing to WebGLRenderer initialization.
        """
        return {
            "antialias": self.antialias,
            "preserveDrawingBuffer": self.preserve_draw_buffer,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to a plain dictionary for comparison and logging.

        Returns:
            Dictionary with all configuration values.
        """
        return {
            "antialias": self.antialias,
            "preserveDrawingBuffer": self.preserve_draw_buffer,
            "seed": self.seed,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "outputColorSpace": self.output_color_space,
        }


def detect_hardware_id() -> str:
    """Detect GPU model and driver version, returning a stable hash identifier.

    The hardware ID is a short hash of the GPU model string concatenated with
    the driver version. This is used to key baseline directories so that
    different hardware (GPU model or driver version) produces separate baselines.

    On Windows: uses WMIC to query GPU adapter info.
    On Linux: uses lspci and nvidia-smi or mesa version.

    Returns:
        A string like "rtx4090-driverXXX" or a hex hash if clean parsing fails.
        Falls back to "unknown-hardware" if detection fails entirely.
    """
    gpu_model = _detect_gpu_model()
    driver_version = _detect_driver_version()

    if not gpu_model and not driver_version:
        return "unknown-hardware"

    # Create a human-readable slug when possible, fall back to hash
    raw_id = f"{gpu_model}|{driver_version}"
    hash_suffix = hashlib.sha256(raw_id.encode()).hexdigest()[:8]

    # Try to create a readable slug from the GPU model
    slug = _slugify_gpu(gpu_model) if gpu_model else "gpu"
    driver_slug = _slugify_driver(driver_version) if driver_version else "nodriver"

    return f"{slug}-{driver_slug}-{hash_suffix}"


def _detect_gpu_model() -> str:
    """Detect the GPU model string from the system.

    Returns:
        GPU model name string, or empty string on failure.
    """
    system = platform.system()

    try:
        if system == "Windows":
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = [
                    line.strip()
                    for line in result.stdout.strip().splitlines()
                    if line.strip() and line.strip().lower() != "name"
                ]
                if lines:
                    return lines[0]

        elif system == "Linux":
            # Try nvidia-smi first for NVIDIA GPUs
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0].strip()

            # Fall back to lspci
            result = subprocess.run(
                ["lspci"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "VGA" in line or "3D" in line:
                        # Extract the device name after the colon
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            return parts[2].strip()

        elif system == "Darwin":
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "Chipset Model" in line or "Chip" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            return parts[1].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return ""


def _detect_driver_version() -> str:
    """Detect the GPU driver version string.

    Returns:
        Driver version string, or empty string on failure.
    """
    system = platform.system()

    try:
        if system == "Windows":
            result = subprocess.run(
                [
                    "wmic",
                    "path",
                    "win32_VideoController",
                    "get",
                    "DriverVersion",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = [
                    line.strip()
                    for line in result.stdout.strip().splitlines()
                    if line.strip() and line.strip().lower() != "driverversion"
                ]
                if lines:
                    return lines[0]

        elif system == "Linux":
            # Try nvidia-smi for NVIDIA driver version
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=driver_version",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0].strip()

            # Fall back to mesa version
            result = subprocess.run(
                ["glxinfo"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "OpenGL version" in line:
                        return line.split(":", 1)[1].strip()

        elif system == "Darwin":
            # macOS Metal driver version is tied to OS version
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return f"macOS-{result.stdout.strip()}"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return ""


def _slugify_gpu(gpu_model: str) -> str:
    """Create a filesystem-safe slug from a GPU model name.

    Examples:
        "NVIDIA GeForce RTX 4090" -> "rtx4090"
        "AMD Radeon RX 7900 XTX" -> "rx7900xtx"
        "Apple M2 Pro" -> "m2pro"
    """
    name = gpu_model.lower()

    # Remove common vendor prefixes
    for prefix in ["nvidia geforce ", "nvidia ", "amd radeon ", "amd ", "apple "]:
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break

    # Keep only alphanumeric characters
    slug = re.sub(r"[^a-z0-9]", "", name)
    return slug[:20] if slug else "gpu"


def _slugify_driver(driver_version: str) -> str:
    """Create a filesystem-safe slug from a driver version string.

    Examples:
        "32.0.15.6081" -> "driver32015"
        "560.35.03" -> "driver56035"
        "macOS-14.5" -> "drivermacos145"
    """
    # Extract digits and create a short version
    digits = re.sub(r"[^a-z0-9]", "", driver_version.lower())
    # Take first 10 chars to keep it manageable
    return f"driver{digits[:10]}" if digits else "driver"


async def verify_determinism(page: Any) -> dict[str, Any]:
    """Verify that the browser page has deterministic render settings applied.

    Calls window.__qa.getRendererInfo() via Playwright and confirms that the
    renderer settings match the expected deterministic configuration.

    If the renderer fails to initialize with deterministic settings, raises
    a DeterministicRenderError with a descriptive message identifying the
    missing capability.

    Args:
        page: A Playwright page object with window.__qa available.

    Returns:
        The renderer info dictionary from window.__qa.getRendererInfo().

    Raises:
        DeterministicRenderError: If window.__qa is unavailable, getRendererInfo
            returns unexpected values, or the renderer lacks required settings.
    """
    expected = DeterministicRenderConfig()

    # Check that window.__qa is available
    qa_available = await page.evaluate("() => typeof window.__qa !== 'undefined'")
    if not qa_available:
        raise DeterministicRenderError(
            "window.__qa is not available. Ensure the viewer is loaded with "
            "?qa=1 URL parameter. The QA harness must be active for "
            "deterministic render verification."
        )

    # Check that getRendererInfo method exists
    method_exists = await page.evaluate(
        "() => typeof window.__qa.getRendererInfo === 'function'"
    )
    if not method_exists:
        raise DeterministicRenderError(
            "window.__qa.getRendererInfo() is not available. The QA harness "
            "may be an older version that does not support renderer introspection."
        )

    # Get renderer info from the browser
    renderer_info = await page.evaluate("() => window.__qa.getRendererInfo()")

    if not renderer_info or not isinstance(renderer_info, dict):
        raise DeterministicRenderError(
            "window.__qa.getRendererInfo() returned invalid data. "
            f"Got: {renderer_info!r}"
        )

    # Validate each deterministic setting
    errors: list[str] = []

    # Check antialias is disabled
    if renderer_info.get("antialias") is not False:
        errors.append(
            f"antialias must be false for deterministic rendering, "
            f"got: {renderer_info.get('antialias')!r}"
        )

    # Check preserveDrawingBuffer is enabled
    if renderer_info.get("preserveDrawingBuffer") is not True:
        errors.append(
            f"preserveDrawingBuffer must be true for screenshot capture, "
            f"got: {renderer_info.get('preserveDrawingBuffer')!r}"
        )

    # Check seed is the expected value
    actual_seed = renderer_info.get("seed")
    if actual_seed != expected.seed:
        errors.append(
            f"shader noise seed must be {expected.seed}, "
            f"got: {actual_seed!r}"
        )

    if errors:
        error_details = "\n  - ".join(errors)
        raise DeterministicRenderError(
            f"Renderer is not configured for deterministic output. "
            f"The following settings are incorrect:\n  - {error_details}\n\n"
            f"Aborting test — pixel comparisons will be unreliable without "
            f"deterministic settings."
        )

    return renderer_info
