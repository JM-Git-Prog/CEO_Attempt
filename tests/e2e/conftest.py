"""Shared E2E test configuration — fixtures and markers.

Extends the base Playwright E2E conftest with:
- Custom pytest markers for test segmentation (nightly, gpu, proposed, layer)
- enforce_budget autouse fixture for per-layer timeout enforcement
- artifact_store fixture for per-run artifact directory management
- e2e_config fixture for validated configuration loading

Requirements: 22.1–22.6
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.config_loader import E2EConfig, load_config


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