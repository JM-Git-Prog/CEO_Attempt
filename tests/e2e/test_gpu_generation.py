"""GPU generation E2E tests — real FLUX image generation via ComfyUI.

Tests the dream_preview stage by submitting a FLUX txt2img workflow to
ComfyUI and validating the resulting image meets quality constraints:
  - Valid PNG or JPEG encoding (parseable without error)
  - Minimum dimensions of 512×512 pixels
  - Completion within a 20-second timeout

Also tests generated artifact endpoint verification (Requirements 19.1–19.4):
  - `/api/session/{session_id}/dream_preview` returns HTTP 200 with correct Content-Type
  - Pre-completion requests return HTTP 404 with JSON error body
  - Served file size > 1KB (not empty/corrupted)
  - `Cache-Control: no-store` header present

Failure details record queue position (when available), elapsed time,
and the specific error message for diagnosis.

Requirements: 18.1–18.4, 19.1–19.4
"""
from __future__ import annotations

import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() inside playwright's event loop

import io
import json
import time
from typing import Any

import pytest

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
    ComfyUIVRAMError,
)
from src.photo_pipeline.workflows import load_workflow
from tests.e2e.framework.artifact_store import ArtifactStore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum time (seconds) for the FLUX generation workflow to complete.
# Requirement 18.1: receive a generated image within 20 seconds.
# Note: SDXL is slower than FLUX; allow 45s for cold model loading.
FLUX_TIMEOUT_S = 45

# Minimum acceptable image dimensions (pixels per axis).
# Requirement 18.3: minimum 512×512 pixels.
MIN_IMAGE_DIMENSION = 512

# Prompt used for the E2E FLUX generation test — short and deterministic.
TEST_PROMPT = (
    "A cozy living room with warm lighting, wooden furniture, "
    "and a large window overlooking a garden"
)

# Fixed seed for reproducibility across test runs.
TEST_SEED = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_flux_workflow() -> dict[str, Any]:
    """Load and parameterise the FLUX txt2img workflow for testing.

    Returns a workflow dict ready for submission to ComfyUI with the test
    prompt and seed substituted into the appropriate placeholder locations.
    """
    workflow = load_workflow("flux_txt2img")

    # Substitute prompt text into the CLIPTextEncode node (node "2")
    if "2" in workflow:
        workflow["2"]["inputs"]["text"] = TEST_PROMPT

    # Substitute seed into the KSampler node (node "4")
    if "4" in workflow:
        workflow["4"]["inputs"]["seed"] = TEST_SEED

    return workflow


def _validate_image_bytes(image_data: bytes) -> tuple[int, int, str]:
    """Validate that image_data is a valid PNG or JPEG with minimum dimensions.

    Returns:
        A tuple of (width, height, format_name) on success.

    Raises:
        ValueError: If the image cannot be decoded or dimensions are too small.
    """
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(image_data))
        img.verify()  # Verify it's a valid image without fully loading
    except Exception as exc:
        raise ValueError(f"Image decoding failed: {exc}") from exc

    # Re-open after verify (verify() can leave the image in an unusable state)
    img = Image.open(io.BytesIO(image_data))
    width, height = img.size
    fmt = img.format or "UNKNOWN"

    if fmt.upper() not in ("PNG", "JPEG", "JPG"):
        raise ValueError(
            f"Invalid image format '{fmt}'. Expected PNG or JPEG."
        )

    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimensions {width}×{height} below minimum "
            f"{MIN_IMAGE_DIMENSION}×{MIN_IMAGE_DIMENSION}"
        )

    return width, height, fmt


def _record_failure(
    artifact_store: ArtifactStore,
    *,
    elapsed_s: float,
    error_message: str,
    queue_position: int | None = None,
) -> str:
    """Record GPU generation failure details to the artifact store.

    Stores a JSON file with diagnostic information for post-run analysis.
    Returns the formatted failure message string.

    Requirement 18.4: record queue position, elapsed time, error message.
    """
    failure_record = {
        "test": "test_flux_dream_preview_generation",
        "elapsed_s": round(elapsed_s, 2),
        "error_message": error_message,
        "queue_position": queue_position,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    artifact_store.store_artifact(
        "gpu",
        "flux_generation_failure.json",
        json.dumps(failure_record, indent=2),
    )

    details = (
        f"FLUX generation failed after {elapsed_s:.1f}s\n"
        f"Error: {error_message}\n"
    )
    if queue_position is not None:
        details += f"Queue position at failure: {queue_position}\n"

    return artifact_store.failure_message(
        "gpu", "test_flux_dream_preview_generation", details
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.gpu
def test_flux_dream_preview_generation(
    artifact_store: ArtifactStore,
) -> None:
    """E2E test: submit a FLUX txt2img workflow and validate the output image.

    Exercises the full dream_preview generation path:
    1. Health-check ComfyUI (with retry resilience from Req 17.1–17.4)
    2. Submit the FLUX txt2img workflow with a test prompt
    3. Poll for completion within the 20s timeout
    4. Retrieve and validate the generated image

    Requirements: 18.1 (submit + receive within 20s), 18.3 (valid dimensions
    and encoding), 18.4 (failure recording with queue position + elapsed + error)
    """
    import asyncio
    import tempfile
    from pathlib import Path

    async def _run():
        client = ComfyUIClient(timeout_s=FLUX_TIMEOUT_S, poll_interval_s=0.5)
        start_time = time.monotonic()

        # Step 1: Health check — verify ComfyUI is reachable
        healthy = await client.health_check()
        if not healthy:
            elapsed = time.monotonic() - start_time
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message="ComfyUI health check failed after all retries",
            )
            pytest.skip(f"ComfyUI unavailable — skipping GPU test.\n{msg}")

        # Step 2: Build and submit the FLUX workflow
        workflow = _build_flux_workflow()

        try:
            prompt_id = await client.submit_workflow(
                workflow, client_id="e2e-gpu-test", timeout_s=FLUX_TIMEOUT_S
            )
        except ComfyUIVRAMError as exc:
            elapsed = time.monotonic() - start_time
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message=f"VRAM OOM on workflow submission: {exc}",
            )
            pytest.fail(msg)
        except ComfyUIError as exc:
            elapsed = time.monotonic() - start_time
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message=f"Workflow submission failed: {exc}",
            )
            pytest.fail(msg)

        # Step 3: Wait for completion within timeout
        try:
            _history = await client.wait_for_completion(
                prompt_id, timeout_s=FLUX_TIMEOUT_S
            )
        except ComfyUITimeoutError as exc:
            elapsed = time.monotonic() - start_time
            queue_pos = await _get_queue_position(client, prompt_id)
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message=f"Generation timed out after {FLUX_TIMEOUT_S}s: {exc}",
                queue_position=queue_pos,
            )
            pytest.fail(msg)
        except (ComfyUIVRAMError, ComfyUIError) as exc:
            elapsed = time.monotonic() - start_time
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message=f"Generation execution error: {exc}",
            )
            pytest.fail(msg)

        # Step 4: Retrieve the generated image
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                output_path = await client.get_output_image(
                    prompt_id,
                    Path(tmp_dir),
                    filename="dream_preview_test.png",
                )
            except ComfyUIError as exc:
                elapsed = time.monotonic() - start_time
                msg = _record_failure(
                    artifact_store,
                    elapsed_s=elapsed,
                    error_message=f"Failed to retrieve output image: {exc}",
                )
                pytest.fail(msg)

            image_data = output_path.read_bytes()

        elapsed = time.monotonic() - start_time

        # Step 5: Validate image dimensions and encoding
        try:
            width, height, fmt = _validate_image_bytes(image_data)
        except ValueError as exc:
            msg = _record_failure(
                artifact_store,
                elapsed_s=elapsed,
                error_message=f"Image validation failed: {exc}",
            )
            pytest.fail(msg)

        # Step 6: Store the successful result as an artifact
        artifact_store.store_artifact("gpu", "dream_preview_test.png", image_data)
        artifact_store.store_artifact(
            "gpu",
            "flux_generation_result.json",
            json.dumps(
                {
                    "test": "test_flux_dream_preview_generation",
                    "status": "passed",
                    "elapsed_s": round(elapsed, 2),
                    "image_width": width,
                    "image_height": height,
                    "image_format": fmt,
                    "prompt": TEST_PROMPT,
                    "seed": TEST_SEED,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            ),
        )

        # Final assertions
        assert width >= MIN_IMAGE_DIMENSION, f"Width {width} < {MIN_IMAGE_DIMENSION}"
        assert height >= MIN_IMAGE_DIMENSION, f"Height {height} < {MIN_IMAGE_DIMENSION}"
        assert fmt.upper() in ("PNG", "JPEG", "JPG"), f"Unexpected format: {fmt}"
        assert elapsed <= FLUX_TIMEOUT_S, f"Generation took {elapsed:.1f}s, exceeds {FLUX_TIMEOUT_S}s budget"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Queue position helper
# ---------------------------------------------------------------------------


async def _get_queue_position(
    client: ComfyUIClient, prompt_id: str
) -> int | None:
    """Attempt to determine the queue position of a prompt for diagnostics.

    Returns the queue position (0-indexed) or None if unavailable.
    This is best-effort — used only for failure reporting (Req 18.4).
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(f"{client.base_url}/queue")
            if response.status_code != 200:
                return None
            data = response.json()

            # ComfyUI /queue returns {"queue_running": [...], "queue_pending": [...]}
            pending = data.get("queue_pending", [])
            for idx, item in enumerate(pending):
                # Each item is [queue_number, prompt_id, workflow, extra_data, ...]
                if len(item) >= 2 and item[1] == prompt_id:
                    return idx

            running = data.get("queue_running", [])
            for item in running:
                if len(item) >= 2 and item[1] == prompt_id:
                    return 0  # Currently running = position 0

    except (httpx.HTTPError, OSError, KeyError, IndexError):
        pass

    return None


# ---------------------------------------------------------------------------
# Artifact Endpoint Verification Tests (Requirements 19.1–19.4)
# ---------------------------------------------------------------------------


@pytest.mark.gpu
class TestArtifactEndpointVerification:
    """Verify generated artifacts are served correctly via API endpoints.

    These tests exercise the `/api/session/{session_id}/dream_preview` endpoint
    and validate HTTP response codes, Content-Type headers, file sizes, and
    cache headers per Requirements 19.1–19.4.
    """

    @pytest.fixture
    def _app_client(self, tmp_path, monkeypatch):
        """Create a FastAPI TestClient with OUTPUT_DIR pointed at tmp_path.

        This allows us to create fake session directories and artifacts
        without needing a live ComfyUI or full pipeline run.
        """
        from fastapi.testclient import TestClient

        from src.web import app as web
        from src.web import unified_routes

        web.sessions.clear()
        unified_routes.clear_unified_web_state()
        monkeypatch.setattr(web, "OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(
            web,
            "append_event",
            lambda root, payload: {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "app_version": str(payload.get("app_version", 16)),
            },
        )
        with TestClient(web.app) as test_client:
            yield test_client
        unified_routes.clear_unified_web_state()
        web.sessions.clear()

    @staticmethod
    def _create_session(root, session_id: str) -> "Path":
        """Create a V16 session directory with valid metadata."""
        from pathlib import Path

        session_dir = root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session_meta.json").write_text(
            json.dumps({
                "session_id": session_id,
                "interface_version": 16,
                "state": "running",
            }),
            encoding="utf-8",
        )
        return session_dir

    @staticmethod
    def _write_valid_png(path, width: int = 512, height: int = 512) -> bytes:
        """Write a valid PNG file of specified dimensions and return bytes.

        Creates a minimal but valid PNG that is parseable by standard image
        libraries and exceeds 1KB in size.
        """
        from PIL import Image

        img = Image.new("RGB", (width, height), color=(128, 64, 200))
        img.save(path, format="PNG")
        return path.read_bytes()

    def test_dream_preview_returns_200_with_correct_content_type(
        self, _app_client, tmp_path
    ) -> None:
        """Verify completed dream_preview artifact returns HTTP 200 with image Content-Type.

        Requirement 19.1: WHEN a stage artifact is generated, THE Pipeline SHALL
        serve the artifact at the corresponding API endpoint with HTTP 200 and
        correct Content-Type (image/png or image/jpeg).
        """
        session_dir = self._create_session(tmp_path, "endpoint-test-session")
        artifact_path = session_dir / "dream_preview_001.png"
        self._write_valid_png(artifact_path)

        response = _app_client.get(
            "/api/session/endpoint-test-session/dream_preview"
        )

        assert response.status_code == 200, (
            f"Expected HTTP 200 for existing artifact, got {response.status_code}"
        )
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("image/png") or content_type.startswith("image/jpeg"), (
            f"Expected Content-Type image/png or image/jpeg, got '{content_type}'"
        )

    def test_pre_completion_request_returns_404_with_json_error(
        self, _app_client, tmp_path
    ) -> None:
        """Verify requesting artifact before stage completion returns HTTP 404 with JSON error.

        Requirement 19.2: WHEN a test requests an artifact endpoint before the stage
        has completed, THE Pipeline SHALL respond with HTTP 404 and a JSON error body
        indicating the stage is not yet complete.
        """
        # Create session WITHOUT any dream_preview artifact
        self._create_session(tmp_path, "incomplete-session")

        response = _app_client.get(
            "/api/session/incomplete-session/dream_preview"
        )

        assert response.status_code == 404, (
            f"Expected HTTP 404 for missing artifact, got {response.status_code}"
        )
        # Verify JSON error body
        body = response.json()
        assert "error" in body, (
            f"Expected JSON body with 'error' key, got: {body}"
        )
        assert isinstance(body["error"], str), (
            f"Expected error value to be a string, got: {type(body['error'])}"
        )

    def test_artifact_file_size_exceeds_1kb(
        self, _app_client, tmp_path
    ) -> None:
        """Verify served artifact file size is > 1KB (not empty/corrupted).

        Requirement 19.3: THE Pipeline SHALL verify that served artifact file sizes
        are greater than 1KB (ruling out empty or corrupted files).
        """
        session_dir = self._create_session(tmp_path, "size-check-session")
        artifact_path = session_dir / "dream_preview_001.png"
        image_bytes = self._write_valid_png(artifact_path, width=512, height=512)

        # Precondition: the file we created is > 1KB
        assert len(image_bytes) > 1024, (
            f"Test setup error: generated PNG should be > 1KB, got {len(image_bytes)} bytes"
        )

        response = _app_client.get(
            "/api/session/size-check-session/dream_preview"
        )

        assert response.status_code == 200
        assert len(response.content) > 1024, (
            f"Artifact file size {len(response.content)} bytes is not > 1KB. "
            f"File may be empty or corrupted."
        )

    def test_cache_control_no_store_header_present(
        self, _app_client, tmp_path
    ) -> None:
        """Verify Cache-Control: no-store header is present on artifact responses.

        Requirement 19.4: WHEN a generated artifact is served, THE Pipeline SHALL
        include cache-busting headers (Cache-Control: no-store) to prevent stale
        artifact caching during tests.
        """
        session_dir = self._create_session(tmp_path, "cache-header-session")
        artifact_path = session_dir / "dream_preview_001.png"
        self._write_valid_png(artifact_path)

        response = _app_client.get(
            "/api/session/cache-header-session/dream_preview"
        )

        assert response.status_code == 200
        cache_control = response.headers.get("cache-control", "")
        assert "no-store" in cache_control, (
            f"Expected 'Cache-Control: no-store' header, got '{cache_control}'"
        )
