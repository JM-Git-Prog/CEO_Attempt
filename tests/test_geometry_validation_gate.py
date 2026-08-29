"""Tests for the geometry validation QA gate.

Exercises the depth-map comparison logic that verifies ControlNet depth
conditioning held during generation. The gate is diagnostic only; these tests
confirm its metrics and threshold behavior, not any spatial-authority override.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.unified_pipeline.geometry_validation_gate import (
    GeometryValidationGate,
    ValidationConfig,
    ValidationResult,
)


def _gradient(h: int = 16, w: int = 16, lo: float = 1.0, hi: float = 5.0) -> np.ndarray:
    """A smooth depth gradient from ``lo`` to ``hi`` meters."""
    return np.linspace(lo, hi, h * w, dtype=np.float64).reshape(h, w)


def test_perfect_match_passes():
    gate = GeometryValidationGate()
    depth = _gradient()
    result = gate.compare(depth, depth.copy())

    assert isinstance(result, ValidationResult)
    assert result.passed is True
    assert result.pearson_r == pytest.approx(1.0, abs=1e-6)
    assert result.scale_aligned_mae_m == pytest.approx(0.0, abs=1e-6)
    assert result.scale_factor == pytest.approx(1.0, abs=1e-6)
    assert result.coverage_fraction == pytest.approx(1.0, abs=1e-9)
    assert result.failure_reason == ""


def test_scaled_match_passes():
    gate = GeometryValidationGate()
    estimated = _gradient()
    conditioning = 2.0 * estimated
    result = gate.compare(estimated, conditioning)

    assert result.passed is True
    assert result.scale_factor == pytest.approx(2.0, abs=1e-6)
    assert result.pearson_r == pytest.approx(1.0, abs=1e-6)
    assert result.scale_aligned_mae_m == pytest.approx(0.0, abs=1e-6)


def test_uncorrelated_fails():
    gate = GeometryValidationGate()
    rng = np.random.default_rng(1234)
    estimated = rng.uniform(1.0, 5.0, size=(16, 16))
    conditioning = _gradient()
    result = gate.compare(estimated, conditioning)

    assert result.passed is False
    assert result.pearson_r < 0.7
    assert "correlation" in result.failure_reason


def test_high_mae_fails():
    gate = GeometryValidationGate()
    estimated = _gradient()
    conditioning = estimated + 2.0  # constant 2m offset scale cannot remove
    result = gate.compare(estimated, conditioning)

    assert result.passed is False
    assert result.scale_aligned_mae_m > gate.config.max_mae_m
    assert "mae" in result.failure_reason


def test_conditioning_inf_treated_invalid():
    gate = GeometryValidationGate()
    estimated = _gradient()
    conditioning = estimated.copy()
    # Mark the bottom half as "no geometry" via inf.
    conditioning[8:, :] = np.inf

    result = gate.compare(estimated, conditioning)

    assert result.coverage_fraction == pytest.approx(0.5, abs=1e-6)
    # Metrics still computed on the valid upper half; the valid half matches.
    assert result.passed is True
    assert result.pearson_r == pytest.approx(1.0, abs=1e-6)


def test_insufficient_coverage():
    gate = GeometryValidationGate()
    estimated = _gradient()
    conditioning = np.full_like(estimated, np.inf)

    result = gate.compare(estimated, conditioning)

    assert result.passed is False
    assert result.coverage_fraction == pytest.approx(0.0, abs=1e-9)
    assert "coverage" in result.failure_reason.lower()


def test_next_strength_increments():
    gate = GeometryValidationGate()
    assert gate.next_strength(0.7) == pytest.approx(0.8, abs=1e-6)
    # 0.95 + 0.1 would be 1.05 -> capped at 1.0.
    assert gate.next_strength(0.95) == pytest.approx(1.0, abs=1e-6)


def test_next_strength_caps():
    gate = GeometryValidationGate()
    assert gate.next_strength(1.0) == pytest.approx(1.0, abs=1e-6)


def test_custom_config_thresholds_applied():
    strict = GeometryValidationGate(
        ValidationConfig(min_correlation=0.99, max_mae_m=0.01, min_ssim=0.99)
    )
    estimated = _gradient()
    conditioning = estimated + 0.2  # small offset, still fails strict mae
    result = strict.compare(estimated, conditioning)
    assert result.passed is False
