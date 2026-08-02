"""Composite gate for multi-metric perceptual fidelity pass/fail decisions.

The CompositeGate evaluates multiple perceptual metrics (SSIM, LPIPS, CLIP cosine)
against independently configurable thresholds. The gate passes only when ALL metrics
independently pass their thresholds.

On failure, reports which metric(s) failed with measured value, threshold, and delta.
All metric evaluations (pass or fail) are logged to a structured JSON report.

Validates: Requirements 5.5, 5.6, 6.3
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums and Data Models
# ---------------------------------------------------------------------------


class MetricDirection(Enum):
    """Indicates whether higher or lower metric values indicate better quality."""

    HIGHER_IS_BETTER = "higher_is_better"  # SSIM, CLIP — pass when >= threshold
    LOWER_IS_BETTER = "lower_is_better"  # LPIPS — pass when <= threshold


@dataclass(frozen=True)
class MetricThreshold:
    """Configuration for a single metric's pass/fail threshold.

    Attributes:
        name: Human-readable metric name (e.g. "SSIM", "LPIPS", "CLIP_Cosine").
        threshold: The pass/fail boundary value.
        direction: Whether higher or lower values indicate better quality.
    """

    name: str
    threshold: float
    direction: MetricDirection


@dataclass(frozen=True)
class MetricResult:
    """Result of evaluating a single metric against its threshold.

    Attributes:
        name: The metric name.
        value: The measured metric value.
        threshold: The configured threshold.
        direction: Whether higher or lower is better.
        passed: Whether this metric passed its threshold check.
        delta: The difference between value and threshold.
               For HIGHER_IS_BETTER: value - threshold (positive = pass margin).
               For LOWER_IS_BETTER: threshold - value (positive = pass margin).
    """

    name: str
    value: float
    threshold: float
    direction: MetricDirection
    passed: bool
    delta: float


@dataclass
class GateResult:
    """Result of the composite gate evaluation.

    Attributes:
        passed: True only when ALL metrics independently pass.
        metric_results: Individual result for each evaluated metric.
        failures: List of MetricResults that failed (convenience accessor).
        timestamp: ISO 8601 timestamp of the evaluation.
    """

    passed: bool
    metric_results: list[MetricResult]
    timestamp: str

    @property
    def failures(self) -> list[MetricResult]:
        """Return only the metrics that failed their threshold check."""
        return [r for r in self.metric_results if not r.passed]

    def failure_report(self) -> str:
        """Generate a human-readable failure report.

        Returns a multi-line string describing each failed metric with
        its name, measured value, threshold, and delta.
        """
        if self.passed:
            return "Composite gate PASSED — all metrics within thresholds."

        lines = ["Composite gate FAILED:"]
        for f in self.failures:
            direction_label = (
                ">=" if f.direction == MetricDirection.HIGHER_IS_BETTER else "<="
            )
            lines.append(
                f"  • {f.name}: measured={f.value:.6f}, "
                f"threshold={f.threshold:.6f} ({direction_label}), "
                f"delta={f.delta:.6f}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the gate result to a JSON-compatible dictionary.

        The output includes all computed values, thresholds, pass/fail status,
        and timestamp as required by Requirement 6.3.
        """
        return {
            "passed": self.passed,
            "timestamp": self.timestamp,
            "metrics": [
                {
                    "name": r.name,
                    "value": r.value,
                    "threshold": r.threshold,
                    "direction": r.direction.value,
                    "passed": r.passed,
                    "delta": r.delta,
                }
                for r in self.metric_results
            ],
            "failures": [
                {
                    "name": f.name,
                    "value": f.value,
                    "threshold": f.threshold,
                    "delta": f.delta,
                }
                for f in self.failures
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the gate result as a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Composite Gate
# ---------------------------------------------------------------------------


# Default thresholds per the design document
DEFAULT_THRESHOLDS: list[MetricThreshold] = [
    MetricThreshold(
        name="SSIM",
        threshold=0.85,
        direction=MetricDirection.HIGHER_IS_BETTER,
    ),
    MetricThreshold(
        name="LPIPS",
        threshold=0.3,
        direction=MetricDirection.LOWER_IS_BETTER,
    ),
    MetricThreshold(
        name="CLIP_Cosine",
        threshold=0.9,
        direction=MetricDirection.HIGHER_IS_BETTER,
    ),
]


class CompositeGate:
    """Multi-metric perceptual fidelity gate.

    The gate evaluates a set of perceptual metrics against independently
    configurable thresholds. It passes only when ALL metrics independently
    pass (conjunction logic):
      - SSIM: pass iff value >= threshold (default 0.85)
      - LPIPS: pass iff value <= threshold (default 0.3)
      - CLIP_Cosine: pass iff value >= threshold (default 0.9)

    Usage:
        gate = CompositeGate()  # uses defaults
        result = gate.evaluate(ssim=0.87, lpips=0.25, clip_cosine=0.92)
        if not result.passed:
            print(result.failure_report())

        # With custom thresholds
        gate = CompositeGate(thresholds=[
            MetricThreshold("SSIM", 0.90, MetricDirection.HIGHER_IS_BETTER),
            MetricThreshold("LPIPS", 0.2, MetricDirection.LOWER_IS_BETTER),
            MetricThreshold("CLIP_Cosine", 0.95, MetricDirection.HIGHER_IS_BETTER),
        ])

    Validates: Requirements 5.5, 5.6, 6.3
    """

    def __init__(
        self,
        thresholds: list[MetricThreshold] | None = None,
    ) -> None:
        """Initialize the composite gate with metric thresholds.

        Args:
            thresholds: List of MetricThreshold configurations. If None,
                       uses the default thresholds (SSIM >= 0.85,
                       LPIPS <= 0.3, CLIP_Cosine >= 0.9).
        """
        self._thresholds = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    @property
    def thresholds(self) -> list[MetricThreshold]:
        """The configured metric thresholds."""
        return list(self._thresholds)

    def evaluate(
        self,
        ssim: float | None = None,
        lpips: float | None = None,
        clip_cosine: float | None = None,
        **extra_metrics: float,
    ) -> GateResult:
        """Evaluate all configured metrics against their thresholds.

        Accepts metric values by name. Any configured metric not provided
        will raise a ValueError.

        Args:
            ssim: The SSIM value (higher is more similar, 0.0–1.0 typical).
            lpips: The LPIPS value (lower is more similar, 0.0+ typical).
            clip_cosine: The CLIP cosine similarity (higher is better, 0.0–1.0).
            **extra_metrics: Additional named metrics for custom thresholds.

        Returns:
            A GateResult indicating overall pass/fail and per-metric details.

        Raises:
            ValueError: If a configured metric has no provided value.
        """
        # Build a lookup of provided metric values
        provided: dict[str, float] = {}
        if ssim is not None:
            provided["SSIM"] = ssim
        if lpips is not None:
            provided["LPIPS"] = lpips
        if clip_cosine is not None:
            provided["CLIP_Cosine"] = clip_cosine
        provided.update(extra_metrics)

        results: list[MetricResult] = []
        timestamp = datetime.now(timezone.utc).isoformat()

        for threshold in self._thresholds:
            if threshold.name not in provided:
                raise ValueError(
                    f"Metric '{threshold.name}' is configured in the composite gate "
                    f"but no value was provided."
                )

            value = provided[threshold.name]
            passed, delta = self._check_threshold(value, threshold)

            results.append(
                MetricResult(
                    name=threshold.name,
                    value=value,
                    threshold=threshold.threshold,
                    direction=threshold.direction,
                    passed=passed,
                    delta=delta,
                )
            )

        all_passed = all(r.passed for r in results)

        return GateResult(
            passed=all_passed,
            metric_results=results,
            timestamp=timestamp,
        )

    def log_result(
        self,
        result: GateResult,
        output_path: str | Path,
    ) -> Path:
        """Write the gate result to a structured JSON report file.

        Logs all metric values (pass or fail) to a structured JSON report
        for trend analysis as required by Requirement 6.3.

        Args:
            result: The GateResult to log.
            output_path: Path to write the JSON report.

        Returns:
            The path to the written report file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.to_json(), encoding="utf-8")
        return output_path

    @staticmethod
    def _check_threshold(
        value: float, threshold: MetricThreshold
    ) -> tuple[bool, float]:
        """Check a single metric value against its threshold.

        Returns:
            A tuple of (passed, delta) where:
            - passed: True if the metric meets its threshold
            - delta: The signed difference (positive = pass margin,
                     negative = fail margin)
        """
        if threshold.direction == MetricDirection.HIGHER_IS_BETTER:
            # Pass iff value >= threshold
            delta = value - threshold.threshold
            passed = value >= threshold.threshold
        else:
            # LOWER_IS_BETTER: Pass iff value <= threshold
            delta = threshold.threshold - value
            passed = value <= threshold.threshold

        return passed, delta
