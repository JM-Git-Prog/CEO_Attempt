"""Cloud model failure analysis and triage for the E2E testing framework.

Collects failure artifacts from nightly test runs, submits bounded analysis
prompts to cloud reasoning models via Ollama, and produces structured JSON
verdicts with root cause, suggested fix, confidence, and category.

Results are stored in tests/e2e/artifacts/{run_id}/cloud_analysis.json
and are ADVISORY only — no auto-remediation without human approval.

Requirements: 24.1–24.5
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid failure categories from cloud model analysis
FAILURE_CATEGORIES = frozenset(
    ["regression", "flaky", "threshold", "infrastructure", "genuine_bug"]
)

# Confidence threshold for automated tagging actions
CONFIDENCE_THRESHOLD = 0.8

# Default cloud model for failure analysis
DEFAULT_ANALYSIS_MODEL = "glm-5.2:cloud"
FALLBACK_ANALYSIS_MODEL = "deepseek-v3.1:671b-cloud"


@dataclass
class FailureArtifact:
    """A single failure artifact collected from a test run.

    Attributes:
        test_name: Fully qualified test name (e.g. test_visual_regression::test_canon_stage).
        layer: Test layer (visual, perceptual, scene, etc.).
        error_message: The pytest failure message.
        artifact_paths: List of paths to relevant artifacts (diffs, screenshots, logs).
        metric_values: Optional dict of metric values if perceptual test.
    """

    test_name: str
    layer: str
    error_message: str
    artifact_paths: list[str] = field(default_factory=list)
    metric_values: dict[str, float] = field(default_factory=dict)


@dataclass
class AnalysisVerdict:
    """Structured verdict from cloud model failure analysis.

    Attributes:
        root_cause: Human-readable description of the root cause.
        suggested_fix: Actionable suggestion for fixing the failure.
        confidence: Model confidence in the analysis (0.0–1.0).
        category: Classification of the failure type.
        test_name: The test this verdict applies to.
        tagged_flaky: Whether this test was tagged for retry-tolerance review.
        proposed_threshold: If category is "threshold", the proposed new value.
    """

    root_cause: str
    suggested_fix: str
    confidence: float
    category: str
    test_name: str
    tagged_flaky: bool = False
    proposed_threshold: float | None = None

    def __post_init__(self):
        """Validate the verdict structure."""
        if self.category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"Invalid category '{self.category}'. "
                f"Must be one of: {', '.join(sorted(FAILURE_CATEGORIES))}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )


@dataclass
class CloudAnalysisReport:
    """Complete cloud analysis report for a nightly run.

    Stored at tests/e2e/artifacts/{run_id}/cloud_analysis.json

    Attributes:
        run_id: The test run identifier.
        verdicts: List of analysis verdicts for each failure.
        flaky_tests: List of test names tagged as flaky for review.
        threshold_proposals: Dict mapping metric names to proposed values.
        model_used: Which cloud model performed the analysis.
        timestamp: ISO timestamp of analysis completion.
    """

    run_id: str
    verdicts: list[AnalysisVerdict]
    flaky_tests: list[str] = field(default_factory=list)
    threshold_proposals: dict[str, float] = field(default_factory=dict)
    model_used: str = DEFAULT_ANALYSIS_MODEL
    timestamp: str = ""

    def to_dict(self) -> dict:
        """Serialize the report to a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "verdicts": [asdict(v) for v in self.verdicts],
            "flaky_tests": self.flaky_tests,
            "threshold_proposals": self.threshold_proposals,
            "model_used": self.model_used,
            "timestamp": self.timestamp,
        }


def collect_failure_artifacts(
    artifacts_dir: Path,
    failures: list[dict[str, Any]],
) -> list[FailureArtifact]:
    """Collect and organize failure artifacts from a test run.

    Args:
        artifacts_dir: Path to the run's artifact directory
            (tests/e2e/artifacts/{run_id}/).
        failures: List of failure dicts from pytest with keys:
            test_name, layer, error_message, artifact_files (optional),
            metric_values (optional).

    Returns:
        List of FailureArtifact objects ready for analysis submission.
    """
    collected: list[FailureArtifact] = []

    for failure in failures:
        test_name = failure.get("test_name", "unknown_test")
        layer = failure.get("layer", "unknown")
        error_message = failure.get("error_message", "No error message")

        # Gather artifact paths from the layer subdirectory
        artifact_paths: list[str] = []
        layer_dir = artifacts_dir / layer
        if layer_dir.exists():
            # Include any files related to this test
            test_stem = test_name.split("::")[-1] if "::" in test_name else test_name
            for f in layer_dir.iterdir():
                if f.is_file() and (test_stem in f.name or f.suffix in (".png", ".json")):
                    artifact_paths.append(str(f))

        # Also include any explicitly listed artifact files
        explicit_files = failure.get("artifact_files", [])
        artifact_paths.extend(str(p) for p in explicit_files if Path(p).exists())

        metric_values = failure.get("metric_values", {})

        collected.append(
            FailureArtifact(
                test_name=test_name,
                layer=layer,
                error_message=error_message,
                artifact_paths=artifact_paths,
                metric_values=metric_values,
            )
        )

    return collected


def build_analysis_prompt(artifact: FailureArtifact) -> str:
    """Build a bounded analysis prompt for a single failure artifact.

    The prompt instructs the cloud model to return structured JSON with
    root_cause, suggested_fix, confidence, and category fields.

    Args:
        artifact: The failure artifact to analyze.

    Returns:
        A prompt string suitable for submission to the cloud model.
    """
    prompt = f"""Analyze this E2E test failure and provide a structured diagnosis.

## Test Information
- Test: {artifact.test_name}
- Layer: {artifact.layer}
- Error: {artifact.error_message}
"""

    if artifact.metric_values:
        prompt += "\n## Metric Values\n"
        for metric, value in artifact.metric_values.items():
            prompt += f"- {metric}: {value}\n"

    if artifact.artifact_paths:
        prompt += "\n## Artifacts Available\n"
        for path in artifact.artifact_paths[:5]:  # Limit to 5 paths
            prompt += f"- {Path(path).name}\n"

    prompt += """
## Required Output Format
Respond with ONLY a JSON object (no markdown, no explanation):
{
    "root_cause": "Brief description of the root cause",
    "suggested_fix": "Actionable fix suggestion",
    "confidence": 0.0-1.0,
    "category": "regression|flaky|threshold|infrastructure|genuine_bug"
}

Categories:
- regression: Code change caused a real visual/behavioral change
- flaky: Non-deterministic failure (timing, resource contention, race condition)
- threshold: Metric barely missed threshold; threshold may need recalibration
- infrastructure: External dependency failure (ComfyUI down, VRAM OOM, network)
- genuine_bug: Real defect in pipeline code
"""
    return prompt


def parse_analysis_response(response_text: str, test_name: str) -> AnalysisVerdict | None:
    """Parse a cloud model's JSON response into an AnalysisVerdict.

    Handles malformed JSON gracefully by returning None.

    Args:
        response_text: The raw text response from the cloud model.
        test_name: The test name to associate with the verdict.

    Returns:
        AnalysisVerdict if parsing succeeds, None otherwise.
    """
    try:
        # Strip markdown code fences if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            text = text.strip()

        data = json.loads(text)

        root_cause = str(data.get("root_cause", "Unknown"))
        suggested_fix = str(data.get("suggested_fix", "No suggestion"))
        confidence = float(data.get("confidence", 0.0))
        category = str(data.get("category", "genuine_bug"))

        # Validate category
        if category not in FAILURE_CATEGORIES:
            logger.warning(
                "Cloud model returned invalid category '%s' for %s, defaulting to 'genuine_bug'",
                category,
                test_name,
            )
            category = "genuine_bug"

        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))

        verdict = AnalysisVerdict(
            root_cause=root_cause,
            suggested_fix=suggested_fix,
            confidence=confidence,
            category=category,
            test_name=test_name,
        )

        # Apply automated tagging based on confidence and category
        if confidence >= CONFIDENCE_THRESHOLD:
            if category == "flaky":
                verdict.tagged_flaky = True
            elif category == "threshold":
                # Extract proposed threshold if mentioned in suggested_fix
                verdict.proposed_threshold = _extract_threshold_value(suggested_fix)

        return verdict

    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "Failed to parse cloud analysis response for %s: %s",
            test_name,
            exc,
        )
        return None


def _extract_threshold_value(suggested_fix: str) -> float | None:
    """Attempt to extract a numeric threshold value from the suggested fix text."""
    import re

    # Look for patterns like "threshold to 0.82" or "threshold: 0.35"
    patterns = [
        r"threshold\s*(?:to|=|:)\s*(\d+\.?\d*)",
        r"(\d+\.\d+)\s*(?:threshold|as threshold)",
    ]
    for pattern in patterns:
        match = re.search(pattern, suggested_fix, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def route_verdicts(verdicts: list[AnalysisVerdict]) -> CloudAnalysisReport:
    """Route analysis verdicts to appropriate actions.

    - "flaky" (confidence >= 0.8): Tagged for retry-tolerance review
    - "threshold" (confidence >= 0.8): Proposes updated threshold value

    All results are advisory — no auto-application.

    Args:
        verdicts: List of analysis verdicts from cloud model.

    Returns:
        CloudAnalysisReport with routed actions.
    """
    from datetime import datetime, timezone

    flaky_tests: list[str] = []
    threshold_proposals: dict[str, float] = {}

    for verdict in verdicts:
        if verdict.tagged_flaky:
            flaky_tests.append(verdict.test_name)
        if verdict.proposed_threshold is not None and verdict.category == "threshold":
            threshold_proposals[verdict.test_name] = verdict.proposed_threshold

    report = CloudAnalysisReport(
        run_id="",  # Set by caller
        verdicts=verdicts,
        flaky_tests=flaky_tests,
        threshold_proposals=threshold_proposals,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return report


def store_analysis_report(
    report: CloudAnalysisReport,
    artifacts_dir: Path,
) -> Path:
    """Store the cloud analysis report as JSON in the artifacts directory.

    Args:
        report: The completed analysis report.
        artifacts_dir: Path to the run's artifact directory.

    Returns:
        Path to the stored cloud_analysis.json file.
    """
    output_path = artifacts_dir / "cloud_analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )
    logger.info("Cloud analysis report stored at %s", output_path)
    return output_path
