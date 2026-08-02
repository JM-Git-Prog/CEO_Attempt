"""Unit tests for the composite gate module.

Tests the CompositeGate class, threshold checking logic, failure reporting,
and structured JSON report generation.

Validates: Requirements 5.5, 5.6, 6.3
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.e2e.framework.composite_gate import (
    CompositeGate,
    DEFAULT_THRESHOLDS,
    GateResult,
    MetricDirection,
    MetricResult,
    MetricThreshold,
)


# ---------------------------------------------------------------------------
# Default Gate — all pass
# ---------------------------------------------------------------------------


class TestCompositeGateAllPass:
    """Tests where all metrics pass their thresholds."""

    def test_all_metrics_pass_with_defaults(self):
        """Gate passes when SSIM >= 0.85, LPIPS <= 0.3, CLIP >= 0.9."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)

        assert result.passed is True
        assert len(result.metric_results) == 3
        assert all(r.passed for r in result.metric_results)
        assert result.failures == []

    def test_all_metrics_at_exact_thresholds(self):
        """Gate passes when metrics are exactly at threshold boundaries."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.85, lpips=0.3, clip_cosine=0.9)

        assert result.passed is True
        assert all(r.passed for r in result.metric_results)

    def test_ssim_delta_positive_on_pass(self):
        """SSIM delta is positive (pass margin) when above threshold."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)

        ssim_result = next(r for r in result.metric_results if r.name == "SSIM")
        assert ssim_result.delta == pytest.approx(0.05)

    def test_lpips_delta_positive_on_pass(self):
        """LPIPS delta is positive (pass margin) when below threshold."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)

        lpips_result = next(r for r in result.metric_results if r.name == "LPIPS")
        assert lpips_result.delta == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Single metric failure
# ---------------------------------------------------------------------------


class TestCompositeGateSingleFailure:
    """Tests where exactly one metric fails."""

    def test_ssim_below_threshold_fails_gate(self):
        """Gate fails when SSIM < 0.85 even if other metrics pass."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].name == "SSIM"
        assert result.failures[0].value == pytest.approx(0.80)
        assert result.failures[0].threshold == pytest.approx(0.85)
        assert result.failures[0].delta == pytest.approx(-0.05)

    def test_lpips_above_threshold_fails_gate(self):
        """Gate fails when LPIPS > 0.3 even if other metrics pass."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.35, clip_cosine=0.95)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].name == "LPIPS"
        assert result.failures[0].value == pytest.approx(0.35)
        assert result.failures[0].threshold == pytest.approx(0.3)
        assert result.failures[0].delta == pytest.approx(-0.05)

    def test_clip_below_threshold_fails_gate(self):
        """Gate fails when CLIP_Cosine < 0.9 even if other metrics pass."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.85)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].name == "CLIP_Cosine"
        assert result.failures[0].value == pytest.approx(0.85)
        assert result.failures[0].threshold == pytest.approx(0.9)
        assert result.failures[0].delta == pytest.approx(-0.05)


# ---------------------------------------------------------------------------
# Multiple metric failures
# ---------------------------------------------------------------------------


class TestCompositeGateMultipleFailures:
    """Tests where multiple metrics fail simultaneously."""

    def test_all_metrics_fail(self):
        """Gate fails with all three metrics reported when all are bad."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.50, lpips=0.80, clip_cosine=0.50)

        assert result.passed is False
        assert len(result.failures) == 3

    def test_two_metrics_fail(self):
        """Gate fails and reports exactly the two failing metrics."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.70, lpips=0.20, clip_cosine=0.80)

        assert result.passed is False
        assert len(result.failures) == 2
        failed_names = {f.name for f in result.failures}
        assert failed_names == {"SSIM", "CLIP_Cosine"}


# ---------------------------------------------------------------------------
# Failure reporting (Requirement 5.6)
# ---------------------------------------------------------------------------


class TestFailureReporting:
    """Tests for the failure report output format."""

    def test_failure_report_contains_metric_name(self):
        """Failure report includes the name of the failed metric."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert "SSIM" in report

    def test_failure_report_contains_measured_value(self):
        """Failure report includes the measured value."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert "0.800000" in report

    def test_failure_report_contains_threshold(self):
        """Failure report includes the threshold."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert "0.850000" in report

    def test_failure_report_contains_delta(self):
        """Failure report includes the delta."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert "-0.050000" in report

    def test_passing_gate_report_message(self):
        """A passing gate produces a descriptive pass message."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert "PASSED" in report

    def test_failure_report_indicates_direction_for_higher_is_better(self):
        """Report shows >= for SSIM/CLIP direction."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        report = result.failure_report()

        assert ">=" in report

    def test_failure_report_indicates_direction_for_lower_is_better(self):
        """Report shows <= for LPIPS direction."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.40, clip_cosine=0.95)
        report = result.failure_report()

        assert "<=" in report


# ---------------------------------------------------------------------------
# JSON report (Requirement 6.3)
# ---------------------------------------------------------------------------


class TestJsonReport:
    """Tests for the structured JSON report output."""

    def test_to_dict_contains_all_metric_values(self):
        """JSON report includes all computed metric values."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        assert len(data["metrics"]) == 3
        metric_names = {m["name"] for m in data["metrics"]}
        assert metric_names == {"SSIM", "LPIPS", "CLIP_Cosine"}

    def test_to_dict_contains_thresholds(self):
        """JSON report includes threshold for each metric."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        for m in data["metrics"]:
            assert "threshold" in m
            assert isinstance(m["threshold"], float)

    def test_to_dict_contains_pass_fail_status(self):
        """JSON report includes pass/fail status for each metric and overall."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        assert "passed" in data
        assert data["passed"] is True
        for m in data["metrics"]:
            assert "passed" in m

    def test_to_dict_contains_timestamp(self):
        """JSON report includes an ISO timestamp."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)
        # Should be parseable as ISO 8601
        assert "T" in data["timestamp"]

    def test_to_dict_failures_section_on_failure(self):
        """JSON report includes a failures section with failed metric details."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.80, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        assert len(data["failures"]) == 1
        failure = data["failures"][0]
        assert failure["name"] == "SSIM"
        assert "value" in failure
        assert "threshold" in failure
        assert "delta" in failure

    def test_to_dict_empty_failures_on_pass(self):
        """JSON report has empty failures list when all pass."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        data = result.to_dict()

        assert data["failures"] == []

    def test_to_json_is_valid_json(self):
        """to_json() produces parseable JSON."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)
        json_str = result.to_json()

        parsed = json.loads(json_str)
        assert parsed["passed"] is True

    def test_log_result_writes_file(self):
        """log_result() writes a valid JSON file to the specified path."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.87, lpips=0.25, clip_cosine=0.92)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.json"
            returned_path = gate.log_result(result, output_path)

            assert returned_path == output_path
            assert output_path.exists()

            data = json.loads(output_path.read_text(encoding="utf-8"))
            assert data["passed"] is True
            assert len(data["metrics"]) == 3

    def test_log_result_creates_parent_directories(self):
        """log_result() creates intermediate directories as needed."""
        gate = CompositeGate()
        result = gate.evaluate(ssim=0.87, lpips=0.25, clip_cosine=0.92)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "dir" / "report.json"
            gate.log_result(result, output_path)

            assert output_path.exists()


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    """Tests with user-configured custom thresholds."""

    def test_stricter_ssim_threshold(self):
        """A stricter SSIM threshold (0.95) correctly fails values below it."""
        gate = CompositeGate(
            thresholds=[
                MetricThreshold("SSIM", 0.95, MetricDirection.HIGHER_IS_BETTER),
                MetricThreshold("LPIPS", 0.3, MetricDirection.LOWER_IS_BETTER),
                MetricThreshold("CLIP_Cosine", 0.9, MetricDirection.HIGHER_IS_BETTER),
            ]
        )
        result = gate.evaluate(ssim=0.90, lpips=0.20, clip_cosine=0.95)

        assert result.passed is False
        assert result.failures[0].name == "SSIM"

    def test_relaxed_lpips_threshold(self):
        """A relaxed LPIPS threshold (0.5) passes higher values."""
        gate = CompositeGate(
            thresholds=[
                MetricThreshold("SSIM", 0.85, MetricDirection.HIGHER_IS_BETTER),
                MetricThreshold("LPIPS", 0.5, MetricDirection.LOWER_IS_BETTER),
                MetricThreshold("CLIP_Cosine", 0.9, MetricDirection.HIGHER_IS_BETTER),
            ]
        )
        result = gate.evaluate(ssim=0.90, lpips=0.45, clip_cosine=0.95)

        assert result.passed is True

    def test_single_metric_gate(self):
        """Gate works with a single metric threshold."""
        gate = CompositeGate(
            thresholds=[
                MetricThreshold("SSIM", 0.85, MetricDirection.HIGHER_IS_BETTER),
            ]
        )
        result = gate.evaluate(ssim=0.90)

        assert result.passed is True
        assert len(result.metric_results) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for input validation and error cases."""

    def test_missing_metric_raises_value_error(self):
        """Raises ValueError when a configured metric has no provided value."""
        gate = CompositeGate()

        with pytest.raises(ValueError, match="SSIM"):
            gate.evaluate(lpips=0.20, clip_cosine=0.95)

    def test_missing_lpips_raises_value_error(self):
        """Raises ValueError when LPIPS is not provided."""
        gate = CompositeGate()

        with pytest.raises(ValueError, match="LPIPS"):
            gate.evaluate(ssim=0.90, clip_cosine=0.95)

    def test_missing_clip_raises_value_error(self):
        """Raises ValueError when CLIP_Cosine is not provided."""
        gate = CompositeGate()

        with pytest.raises(ValueError, match="CLIP_Cosine"):
            gate.evaluate(ssim=0.90, lpips=0.20)


# ---------------------------------------------------------------------------
# Threshold property
# ---------------------------------------------------------------------------


class TestThresholdsProperty:
    """Tests for the thresholds property accessor."""

    def test_default_thresholds_returned(self):
        """Default thresholds are accessible via property."""
        gate = CompositeGate()
        thresholds = gate.thresholds

        assert len(thresholds) == 3
        names = {t.name for t in thresholds}
        assert names == {"SSIM", "LPIPS", "CLIP_Cosine"}

    def test_thresholds_property_returns_copy(self):
        """Thresholds property returns a copy, not the internal list."""
        gate = CompositeGate()
        thresholds = gate.thresholds
        thresholds.clear()

        # Internal state unaffected
        assert len(gate.thresholds) == 3
