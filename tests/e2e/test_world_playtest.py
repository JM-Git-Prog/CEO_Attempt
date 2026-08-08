"""Pytest integration for the E2E World Test Kit.

Runs the full LLM-driven playtest via the orchestrator and asserts the
overall score passes the configured threshold.

Usage:
    pytest tests/e2e/test_world_playtest.py -m e2e_playtest
    pytest tests/e2e/test_world_playtest.py --collect-only  # verify collection
"""
from __future__ import annotations

import pytest

from tests.e2e.world_test_kit.config import load_wtk_config
from tests.e2e.world_test_kit.orchestrator import WorldTestOrchestrator


# Canonical release-qualification prompt (Requirement 30.2)
DEFAULT_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)


@pytest.mark.e2e_playtest
def test_world_playtest():
    """Full LLM-driven playtest — runs the orchestrator and asserts pass.

    This test:
    1. Loads the World Test Kit configuration
    2. Creates an orchestrator instance
    3. Runs the full 9-layer playtest with the default prompt
    4. Asserts the overall score meets the pass threshold
    5. Asserts no individual layer falls below the minimum

    Requires:
    - The V16 web server running at the configured URL
    - Playwright browsers installed
    - (Optional) Ollama with qwen3-coder-next and qwen2.5vl:7b for full evaluation
      Falls back to scripted mode if Ollama is unavailable.
    """
    config = load_wtk_config()
    orchestrator = WorldTestOrchestrator(config)

    report = orchestrator.run(DEFAULT_PROMPT)

    # Print summary for CI visibility
    orchestrator._reporter.print_summary(report)

    # Assertions
    assert report.passed, (
        f"Playtest report failed despite score {report.overall_score:.1f}: "
        f"{report.errors or report.layer_results}"
    )
    assert not report.errors, f"Playtest report contains errors: {report.errors}"
    assert report.overall_score >= config.pass_threshold, (
        f"Overall score {report.overall_score:.1f} below threshold {config.pass_threshold}"
    )

    # Check individual layer minimums and explicit pass verdicts.
    for name, data in report.layer_results.items():
        if name.startswith("_"):
            continue
        assert data.get("passed") is True, f"Layer '{name}' did not pass: {data}"
        score = data.get("score", 0.0)
        assert score >= config.individual_minimum, (
            f"Layer '{name}' score {score:.1f} below minimum {config.individual_minimum}"
        )


@pytest.mark.e2e_playtest
def test_world_playtest_config_loads():
    """Verify the World Test Kit config loads without error."""
    config = load_wtk_config()
    assert config.playtester_model
    assert config.vision_model
    assert config.pass_threshold > 0
    assert config.individual_minimum > 0
    assert config.pass_threshold >= config.individual_minimum


@pytest.mark.e2e_playtest
def test_world_playtest_orchestrator_creates():
    """Verify the orchestrator can be instantiated."""
    config = load_wtk_config()
    orchestrator = WorldTestOrchestrator(config)
    assert orchestrator is not None
