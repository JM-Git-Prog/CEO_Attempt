"""Cloud model perceptual threshold calibration for the E2E testing framework.

Aggregates stored perceptual metric reports from nightly runs (triggered after
50 runs), computes distributions, and submits to a cloud reasoning model for
threshold recommendation.

Outputs to tests/e2e/config/threshold_recommendations.json with per-metric
justification text. Never auto-applies — requires human config file update.

Requirements: 26.1–26.4
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Default cloud model for calibration analysis
DEFAULT_CALIBRATION_MODEL = "deepseek-v3.1:671b-cloud"

# Number of nightly runs that trigger calibration
CALIBRATION_TRIGGER_RUNS = 50

# Output path for threshold recommendations
RECOMMENDATIONS_OUTPUT = (
    Path(__file__).resolve().parent.parent / "config" / "threshold_recommendations.json"
)

# Metrics tracked for calibration
TRACKED_METRICS = ("ssim", "lpips", "clip_cosine")


@dataclass
class MetricDistribution:
    """Statistical distribution of a single metric across nightly runs.

    Attributes:
        metric_name: Name of the metric (ssim, lpips, clip_cosine).
        mean: Mean value.
        std: Standard deviation.
        min_value: Minimum observed.
        max_value: Maximum observed.
        p5: 5th percentile.
        p25: 25th percentile.
        p50: Median (50th percentile).
        p75: 75th percentile.
        p95: 95th percentile.
        sample_count: Number of data points.
        pass_count: Number of runs where this metric passed.
        fail_count: Number of runs where this metric failed.
    """

    metric_name: str
    mean: float
    std: float
    min_value: float
    max_value: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    sample_count: int
    pass_count: int = 0
    fail_count: int = 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "metric_name": self.metric_name,
            "mean": self.mean,
            "std": self.std,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "p5": self.p5,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "p95": self.p95,
            "sample_count": self.sample_count,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
        }


@dataclass
class ThresholdRecommendation:
    """A recommended threshold value for a single metric.

    Attributes:
        metric_name: Name of the metric.
        current_threshold: The currently configured threshold.
        recommended_threshold: The recommended new threshold.
        justification: Statistical basis for the recommendation.
        distribution: The underlying metric distribution.
    """

    metric_name: str
    current_threshold: float
    recommended_threshold: float
    justification: str
    distribution: MetricDistribution

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "metric_name": self.metric_name,
            "current_threshold": self.current_threshold,
            "recommended_threshold": self.recommended_threshold,
            "justification": self.justification,
            "distribution": self.distribution.to_dict(),
        }


@dataclass
class ThresholdRecommendationReport:
    """Complete threshold recommendation report.

    Stored at tests/e2e/config/threshold_recommendations.json.

    Attributes:
        recommendations: Per-metric threshold recommendations.
        model_used: Cloud model that produced the recommendations.
        timestamp: ISO timestamp of recommendation generation.
        runs_analyzed: Number of nightly runs included in the analysis.
    """

    recommendations: list[ThresholdRecommendation]
    model_used: str = DEFAULT_CALIBRATION_MODEL
    timestamp: str = ""
    runs_analyzed: int = 0

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dictionary."""
        return {
            "recommendations": [r.to_dict() for r in self.recommendations],
            "model_used": self.model_used,
            "timestamp": self.timestamp,
            "runs_analyzed": self.runs_analyzed,
        }


def aggregate_metric_reports(
    artifacts_base: Path,
    min_runs: int = CALIBRATION_TRIGGER_RUNS,
) -> dict[str, list[dict[str, Any]]] | None:
    """Aggregate perceptual metric reports from stored nightly run artifacts.

    Scans tests/e2e/artifacts/*/perceptual/ for metric JSON reports.

    Args:
        artifacts_base: Base artifacts directory (tests/e2e/artifacts/).
        min_runs: Minimum number of runs required to trigger calibration.

    Returns:
        Dict mapping metric names to lists of report dicts,
        or None if insufficient runs are available.
    """
    all_reports: list[dict[str, Any]] = []

    if not artifacts_base.exists():
        logger.warning("Artifacts directory does not exist: %s", artifacts_base)
        return None

    # Scan all run directories for perceptual metric reports
    for run_dir in sorted(artifacts_base.iterdir()):
        if not run_dir.is_dir():
            continue
        perceptual_dir = run_dir / "perceptual"
        if not perceptual_dir.exists():
            continue

        # Look for metric report JSON files
        for report_file in perceptual_dir.glob("*metric*.json"):
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                data["_run_id"] = run_dir.name
                all_reports.append(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read report %s: %s", report_file, exc)

    if len(all_reports) < min_runs:
        logger.info(
            "Only %d metric reports found (need %d for calibration trigger)",
            len(all_reports),
            min_runs,
        )
        return None

    # Group values by metric name
    grouped: dict[str, list[dict[str, Any]]] = {m: [] for m in TRACKED_METRICS}
    for report in all_reports:
        for metric_name in TRACKED_METRICS:
            if metric_name in report:
                grouped[metric_name].append(report)

    return grouped


def compute_distributions(
    grouped_reports: dict[str, list[dict[str, Any]]],
    current_thresholds: dict[str, float],
) -> list[MetricDistribution]:
    """Compute statistical distributions from grouped metric reports.

    Args:
        grouped_reports: Dict mapping metric names to report lists.
        current_thresholds: Dict mapping metric names to current thresholds.

    Returns:
        List of MetricDistribution objects.
    """
    distributions: list[MetricDistribution] = []

    for metric_name in TRACKED_METRICS:
        reports = grouped_reports.get(metric_name, [])
        if not reports:
            continue

        # Extract values
        values: list[float] = []
        pass_count = 0
        fail_count = 0

        for report in reports:
            val = report.get(metric_name)
            if val is not None and isinstance(val, (int, float)):
                values.append(float(val))
                # Determine pass/fail based on current threshold
                threshold = current_thresholds.get(metric_name, 0.0)
                if metric_name == "lpips":
                    # Lower is better for LPIPS
                    if val <= threshold:
                        pass_count += 1
                    else:
                        fail_count += 1
                else:
                    # Higher is better for SSIM, CLIP
                    if val >= threshold:
                        pass_count += 1
                    else:
                        fail_count += 1

        if not values:
            continue

        arr = np.array(values)
        dist = MetricDistribution(
            metric_name=metric_name,
            mean=float(np.mean(arr)),
            std=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            min_value=float(np.min(arr)),
            max_value=float(np.max(arr)),
            p5=float(np.percentile(arr, 5)),
            p25=float(np.percentile(arr, 25)),
            p50=float(np.percentile(arr, 50)),
            p75=float(np.percentile(arr, 75)),
            p95=float(np.percentile(arr, 95)),
            sample_count=len(values),
            pass_count=pass_count,
            fail_count=fail_count,
        )
        distributions.append(dist)

    return distributions


def build_calibration_prompt(
    distributions: list[MetricDistribution],
    current_thresholds: dict[str, float],
) -> str:
    """Build a prompt for the cloud model to recommend thresholds.

    Args:
        distributions: Computed metric distributions.
        current_thresholds: Currently configured thresholds.

    Returns:
        Prompt string for cloud model submission.
    """
    prompt = """Analyze the following perceptual metric distributions from E2E test runs
and recommend optimal thresholds that reject genuine regressions while accepting
normal variance.

## Current Thresholds
"""
    for metric, threshold in sorted(current_thresholds.items()):
        prompt += f"- {metric}: {threshold}\n"

    prompt += "\n## Metric Distributions\n"
    for dist in distributions:
        prompt += f"""
### {dist.metric_name} (n={dist.sample_count}, {dist.pass_count} pass, {dist.fail_count} fail)
- Mean: {dist.mean:.4f}
- Std: {dist.std:.4f}
- Min: {dist.min_value:.4f}, Max: {dist.max_value:.4f}
- Percentiles: p5={dist.p5:.4f}, p25={dist.p25:.4f}, p50={dist.p50:.4f}, p75={dist.p75:.4f}, p95={dist.p95:.4f}
"""

    prompt += """
## Task
For each metric, recommend a threshold that:
1. Rejects genuine regressions (values far from the mean)
2. Accepts normal run-to-run variance (within 2-3 standard deviations)
3. Minimizes false positives while catching real issues

## Required Output Format
Respond with ONLY a JSON object:
{
    "recommendations": [
        {
            "metric_name": "ssim|lpips|clip_cosine",
            "recommended_threshold": 0.XX,
            "justification": "Statistical basis: mean=X, std=Y, using mean - 2*std = Z for the threshold because..."
        }
    ]
}
"""
    return prompt


def parse_calibration_response(
    response_text: str,
    distributions: list[MetricDistribution],
    current_thresholds: dict[str, float],
) -> list[ThresholdRecommendation]:
    """Parse the cloud model's calibration response.

    Args:
        response_text: Raw response from the cloud model.
        distributions: The distributions used for analysis.
        current_thresholds: Currently configured thresholds.

    Returns:
        List of ThresholdRecommendation objects.
    """
    try:
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            text = text.strip()

        data = json.loads(text)
        raw_recs = data.get("recommendations", [])

        dist_map = {d.metric_name: d for d in distributions}
        recommendations: list[ThresholdRecommendation] = []

        for item in raw_recs:
            metric_name = item.get("metric_name", "")
            if metric_name not in TRACKED_METRICS:
                continue

            dist = dist_map.get(metric_name)
            if dist is None:
                continue

            recommendations.append(
                ThresholdRecommendation(
                    metric_name=metric_name,
                    current_threshold=current_thresholds.get(metric_name, 0.0),
                    recommended_threshold=float(item.get("recommended_threshold", 0.0)),
                    justification=str(item.get("justification", "")),
                    distribution=dist,
                )
            )

        return recommendations

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse calibration response: %s", exc)
        return []


def store_recommendations(
    report: ThresholdRecommendationReport,
    output_path: Path | None = None,
) -> Path:
    """Store threshold recommendations as JSON.

    Args:
        report: The recommendation report.
        output_path: Override output path (defaults to config/threshold_recommendations.json).

    Returns:
        Path to the stored recommendations file.
    """
    target = output_path or RECOMMENDATIONS_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )
    logger.info("Threshold recommendations stored at %s", target)
    return target


def validate_recommendation_structure(data: dict) -> bool:
    """Validate that a threshold recommendation JSON has correct structure.

    Checks:
    - Has "recommendations" key with list value
    - Each recommendation has metric_name, recommended_threshold, justification
    - justification is non-empty and mentions statistical basis

    Args:
        data: Parsed JSON data to validate.

    Returns:
        True if structure is valid.
    """
    if "recommendations" not in data or not isinstance(data["recommendations"], list):
        return False

    for rec in data["recommendations"]:
        if not isinstance(rec, dict):
            return False
        if "metric_name" not in rec:
            return False
        if "recommended_threshold" not in rec:
            return False
        if "justification" not in rec or not rec["justification"]:
            return False
        # Justification should mention statistical basis
        justification = rec["justification"].lower()
        has_stats = any(
            term in justification
            for term in ("mean", "std", "percentile", "standard deviation", "average")
        )
        if not has_stats:
            return False

    return True
