"""Shared E2E test configuration — fixtures and markers.

Extends the base Playwright E2E conftest with:
- Custom pytest markers for test segmentation (nightly, gpu, proposed, layer)
- enforce_budget autouse fixture for per-layer timeout enforcement
- artifact_store fixture for per-run artifact directory management
- e2e_config fixture for validated configuration loading
- vram_lease fixture for VRAM scheduling in perceptual/vision tests

Requirements: 21.1–21.5, 22.1–22.6
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

import pytest

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.config_loader import E2EConfig, load_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy import helper for resource_arbiter (avoids heavy __init__.py chain)
# ---------------------------------------------------------------------------

def _import_resource_arbiter():
    """Import resource_arbiter module directly to avoid triggering
    src.unified_pipeline.__init__.py which loads torch/CUDA modules.

    We import the minimal dependency chain (src.photo_pipeline) which is
    lightweight, then load resource_arbiter directly from file.
    """
    import importlib.util
    import sys
    from pathlib import Path

    module_name = "src.unified_pipeline.resource_arbiter"
    if module_name in sys.modules:
        return sys.modules[module_name]

    # Import the lightweight photo_pipeline package (no torch/CUDA)
    if "src.photo_pipeline" not in sys.modules:
        import src.photo_pipeline  # noqa: F401
    if "src.photo_pipeline.comfyui_client" not in sys.modules:
        import src.photo_pipeline.comfyui_client  # noqa: F401
    if "src.photo_pipeline.vram_manager" not in sys.modules:
        import src.photo_pipeline.vram_manager  # noqa: F401

    # Create a minimal src.unified_pipeline package entry without __init__
    if "src.unified_pipeline" not in sys.modules:
        import types
        pkg = types.ModuleType("src.unified_pipeline")
        pkg.__path__ = [str(Path("src/unified_pipeline"))]
        pkg.__package__ = "src.unified_pipeline"
        sys.modules["src.unified_pipeline"] = pkg

    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("src/unified_pipeline/resource_arbiter.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for E2E test segmentation."""
    config.addinivalue_line(
        "markers",
        "nightly: perceptual fidelity tests excluded from PR CI (Req 22.4)",
    )
    config.addinivalue_line(
        "markers",
        "gpu: tests requiring NVIDIA GPU hardware (Req 22.5, 22.6)",
    )
    config.addinivalue_line(
        "markers",
        "proposed: cloud-proposed tests awaiting human approval (Req 25.3)",
    )
    config.addinivalue_line(
        "markers",
        'layer(name): test layer for time budget enforcement — '
        '"visual" (120s), "scene" (60s), "accessibility" (30s) (Req 22.1–22.3)',
    )


# ---------------------------------------------------------------------------
# Layer → budget mapping
# ---------------------------------------------------------------------------

# Maps the layer marker argument to the corresponding TimeBudgetConfig field name
_LAYER_BUDGET_MAP: dict[str, str] = {
    "visual": "visual_regression_s",
    "scene": "scene_validation_s",
    "accessibility": "accessibility_s",
    "perceptual": "perceptual_s",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Playwright browser launch arguments for headless E2E testing."""
    return {"headless": True}


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    """Load and validate the E2E testing configuration from e2e_config.yaml.

    Returns:
        A fully validated E2EConfig instance loaded from
        tests/e2e/config/e2e_config.yaml.

    Raises:
        ConfigLoadError: If the config file is missing or unparseable.
        ConfigValidationError: If required fields are missing or invalid.
    """
    return load_config()


@pytest.fixture(scope="session")
def artifact_store() -> ArtifactStore:
    """Initialize a per-run artifact directory with a unique run_id.

    The run_id is composed of an ISO timestamp and a short UUID suffix
    to ensure uniqueness across concurrent runs.

    Returns:
        An initialized ArtifactStore with the run directory created and
        all layer subdirectories ready for artifact storage.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    run_id = f"{timestamp}-{short_uuid}"

    store = ArtifactStore()
    store.init_run(run_id)
    return store


@pytest.fixture(autouse=True)
def enforce_budget(request: pytest.FixtureRequest, e2e_config: E2EConfig) -> None:
    """Abort individual tests that exceed their layer's time budget.

    Applies a pytest-timeout marker based on the test's @pytest.mark.layer(...)
    annotation and the corresponding budget from e2e_config.yaml.

    This is an autouse fixture — it runs for every test automatically.
    Tests without a layer marker are unaffected.

    Requirements: 22.1, 22.2, 22.3
    """
    layer_marker = request.node.get_closest_marker("layer")
    if layer_marker and layer_marker.args:
        layer_name = layer_marker.args[0]
        budget_field = _LAYER_BUDGET_MAP.get(layer_name)
        if budget_field:
            budget = getattr(e2e_config.time_budgets, budget_field)
            request.node.add_marker(pytest.mark.timeout(budget))


# ---------------------------------------------------------------------------
# VRAM Scheduling Fixtures (Requirements 21.1–21.5)
# ---------------------------------------------------------------------------

# Maximum seconds allowed between metric computation completion and lease release.
_LEASE_RELEASE_DEADLINE_S: float = 5.0

# Default VRAM lease timeout (matches resource_arbiter.VRAM_LEASE_TIMEOUT_S).
_VRAM_LEASE_TIMEOUT_S: float = 60.0


@pytest.fixture(scope="session")
def resource_arbiter():
    """Provide the shared Resource Arbiter instance for VRAM scheduling.

    Returns None if the arbiter cannot be initialized (e.g., no ComfyUI
    available). Tests using vram_lease will skip gracefully when None.
    """
    from pathlib import Path

    try:
        ra = _import_resource_arbiter()
        UnifiedResourceArbiter = ra.UnifiedResourceArbiter
        VRAM_LEASE_TIMEOUT_S = ra.VRAM_LEASE_TIMEOUT_S
    except Exception as exc:
        logger.warning(
            "Resource Arbiter import failed, VRAM scheduling disabled: %s", exc
        )
        return None

    from src.photo_pipeline.comfyui_client import ComfyUIClient

    # Try to connect to the local ComfyUI instance
    comfyui_url = "http://127.0.0.1:8188"
    client = ComfyUIClient(base_url=comfyui_url)

    diagnostics_dir = Path("tests/e2e/artifacts/.vram_diagnostics")
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    try:
        arbiter = UnifiedResourceArbiter(
            comfyui_clients={"default": client},
            diagnostics_dir=diagnostics_dir,
            acquire_timeout_s=VRAM_LEASE_TIMEOUT_S,
        )
        return arbiter
    except Exception as exc:
        logger.warning(
            "Resource Arbiter unavailable, VRAM scheduling disabled: %s", exc
        )
        return None


async def _wait_for_comfyui_idle(
    arbiter,
    *,
    poll_interval_s: float = 2.0,
    timeout_s: float = _VRAM_LEASE_TIMEOUT_S,
) -> bool:
    """Wait for ComfyUI to finish any active generation before model loading.

    Polls the arbiter state to confirm no FLUX/generation lease is active.
    Returns True when ComfyUI is idle, False on timeout.

    Requirements: 21.2, 21.5 — perceptual tests wait for ComfyUI generation
    to complete before loading models into VRAM.
    """
    import httpx

    ra = _import_resource_arbiter()
    ResourceKind = ra.ResourceKind

    deadline = time.monotonic() + timeout_s
    comfyui_url = "http://127.0.0.1:8188"

    while time.monotonic() < deadline:
        # Check arbiter state — if a generation kind is active, wait
        state = arbiter.get_state()
        if state.active_owner:
            active_kind = state.active_owner.get("kind", "")
            generation_kinds = {
                ResourceKind.DREAM_FLUX.value,
                ResourceKind.CANON_FLUX.value,
                ResourceKind.COMFYUI.value,
                ResourceKind.HUNYUAN3D.value,
            }
            if active_kind in generation_kinds:
                await asyncio.sleep(poll_interval_s)
                continue

        # Also poll ComfyUI /queue endpoint to confirm no running workflows
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{comfyui_url}/queue")
                if resp.status_code == 200:
                    data = resp.json()
                    running = data.get("queue_running", [])
                    pending = data.get("queue_pending", [])
                    if not running and not pending:
                        return True
        except (httpx.HTTPError, OSError):
            # ComfyUI not reachable — treat as idle (no generation active)
            return True

        await asyncio.sleep(poll_interval_s)

    return False


@pytest.fixture
def vram_lease(
    request: pytest.FixtureRequest,
    resource_arbiter,
):
    """VRAM lease fixture for perceptual and vision test fixtures.

    Wraps the Resource_Arbiter's claim_for_test() context manager to provide:
    - Waiting for ComfyUI generation to complete before model loading (21.2, 21.5)
    - 60s timeout with graceful skip on contention (21.4)
    - Lease release enforcement within 5s of metric computation (21.3)
    - Logging "vram_contention_timeout" and skip without failing suite (21.4)

    Usage in test::

        def test_perceptual_lpips(vram_lease):
            result = vram_lease.acquire(ResourceKind.PERCEPTUAL_LPIPS)
            if not result.acquired:
                pytest.skip(result.status)
            # ... compute metric ...
            vram_lease.mark_computation_done()
            vram_lease.release()  # must be called within 5s of completion

    Requirements: 21.1–21.5
    """
    ra = _import_resource_arbiter()
    ResourceKind = ra.ResourceKind
    ResourceRequest = ra.ResourceRequest
    VRAMLeaseResult = ra.VRAMLeaseResult

    class VRAMLeaseFacade:
        """Facade providing synchronous-style access to async VRAM leasing.

        Manages the lifecycle of a single VRAM lease with timing enforcement.
        """

        def __init__(self, arbiter) -> None:
            self._arbiter = arbiter
            self._result = None
            self._computation_done_at: float | None = None
            self._released: bool = False
            self._lease_context = None

        def acquire(self, kind, owner_id: str | None = None):
            """Acquire a VRAM lease for the given resource kind.

            Waits for ComfyUI generation to complete first (Req 21.2, 21.5),
            then attempts lease acquisition with 60s timeout (Req 21.4).

            Args:
                kind: The ResourceKind to acquire (PERCEPTUAL_LPIPS,
                      PERCEPTUAL_CLIP, or VISION_QA).
                owner_id: Optional owner identifier. Defaults to test node name.

            Returns:
                VRAMLeaseResult with acquired=True on success, or
                acquired=False with status="vram_contention_timeout" on timeout.
            """
            if self._arbiter is None:
                logger.warning(
                    "Resource Arbiter unavailable — skipping VRAM lease for %s",
                    kind.value,
                )
                return VRAMLeaseResult(
                    acquired=False,
                    lease=None,
                    status="vram_contention_timeout",
                )

            if owner_id is None:
                owner_id = request.node.nodeid

            loop = _get_or_create_event_loop()

            # Wait for ComfyUI to finish active generation (Req 21.2, 21.5)
            comfyui_idle = loop.run_until_complete(
                _wait_for_comfyui_idle(self._arbiter)
            )
            if not comfyui_idle:
                logger.warning(
                    "vram_contention_timeout: ComfyUI did not become idle "
                    "within %ds — skipping %s",
                    int(_VRAM_LEASE_TIMEOUT_S),
                    kind.value,
                )
                return VRAMLeaseResult(
                    acquired=False,
                    lease=None,
                    status="vram_contention_timeout",
                )

            # Acquire the lease via claim_for_test (60s timeout)
            req = ResourceRequest(
                kind=kind,
                owner_id=owner_id,
                model_name=kind.value,
                estimated_vram_gb=None,  # uses default from _DEFAULT_VRAM_GB
            )

            self._result = loop.run_until_complete(
                self._async_acquire(req)
            )

            if not self._result.acquired:
                logger.warning(
                    "vram_contention_timeout: lease for %s not acquired "
                    "within %.0fs — metric skipped",
                    kind.value,
                    _VRAM_LEASE_TIMEOUT_S,
                )

            return self._result

        async def _async_acquire(self, req):
            """Internal async lease acquisition using claim_for_test."""
            self._lease_context = self._arbiter.claim_for_test(req)
            result = await self._lease_context.__aenter__()
            return result

        def mark_computation_done(self) -> None:
            """Mark the end of metric computation for release timing enforcement.

            Call this immediately after the metric computation finishes.
            The lease must be released within 5s of this call (Req 21.3).
            """
            self._computation_done_at = time.monotonic()

        def release(self) -> None:
            """Release the VRAM lease.

            Must be called within 5s of mark_computation_done() (Req 21.3).
            If called after the 5s deadline, a warning is logged but the
            release still proceeds.
            """
            if self._released:
                return
            if self._result is None or not self._result.acquired:
                self._released = True
                return

            # Check 5s release deadline (Req 21.3)
            if self._computation_done_at is not None:
                elapsed = time.monotonic() - self._computation_done_at
                if elapsed > _LEASE_RELEASE_DEADLINE_S:
                    logger.warning(
                        "VRAM lease release exceeded 5s deadline: "
                        "%.2fs elapsed since computation completed",
                        elapsed,
                    )

            # Exit the async context manager to release the lease
            loop = _get_or_create_event_loop()
            if self._lease_context is not None:
                loop.run_until_complete(
                    self._lease_context.__aexit__(None, None, None)
                )

            self._released = True
            release_time = time.monotonic()
            if self._computation_done_at is not None:
                logger.info(
                    "VRAM lease released %.2fs after computation completed",
                    release_time - self._computation_done_at,
                )

    facade = VRAMLeaseFacade(resource_arbiter)
    yield facade

    # Teardown: ensure lease is always released, enforce 5s deadline (Req 21.3)
    if not facade._released and facade._result and facade._result.acquired:
        if facade._computation_done_at is not None:
            elapsed = time.monotonic() - facade._computation_done_at
            if elapsed > _LEASE_RELEASE_DEADLINE_S:
                logger.error(
                    "VRAM lease teardown: release deadline VIOLATED — "
                    "%.2fs elapsed (max %.1fs). Forcing release.",
                    elapsed,
                    _LEASE_RELEASE_DEADLINE_S,
                )
        else:
            logger.warning(
                "VRAM lease teardown: computation_done was never marked — "
                "forcing release"
            )
        facade.release()


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get the running event loop or create a new one for sync contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop