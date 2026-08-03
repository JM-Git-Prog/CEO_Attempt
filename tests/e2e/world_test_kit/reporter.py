"""Report generation for the World Test Kit playtest results.

Produces both structured JSON reports and human-readable 20-line summaries.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from tests.e2e.world_test_kit.config import WorldTestKitConfig


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class PlaytestReport:
    """Structured playtest report."""

    session_id: str = ""
    prompt: str = ""
    timestamp: str = ""
    duration_s: float = 0.0
    overall_score: float = 0.0
    passed: bool = False
    pass_threshold: float = 60.0
    individual_minimum: float = 30.0
    layer_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    scripted_mode: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "session_id": self.session_id,
            "prompt": self.prompt,
            "timestamp": self.timestamp,
            "duration_s": round(self.duration_s, 2),
            "overall_score": round(self.overall_score, 2),
            "passed": self.passed,
            "pass_threshold": self.pass_threshold,
            "individual_minimum": self.individual_minimum,
            "layer_results": self.layer_results,
            "errors": self.errors,
            "scripted_mode": self.scripted_mode,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class PlaytestReporter:
    """Generates structured reports and human-readable summaries."""

    def __init__(self, config: WorldTestKitConfig) -> None:
        self._config = config

    def generate(self, results: dict[str, Any]) -> PlaytestReport:
        """Produce the structured PlaytestReport from raw layer results.

        Args:
            results: Dict with keys: session_id, prompt, duration_s, layers, error.

        Returns:
            A complete PlaytestReport with computed pass/fail.
        """
        report = PlaytestReport(
            session_id=results.get("session_id", ""),
            prompt=results.get("prompt", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_s=results.get("duration_s", 0.0),
            pass_threshold=self._config.pass_threshold,
            individual_minimum=self._config.individual_minimum,
            layer_results=results.get("layers", {}),
        )

        # Check for fatal errors
        if results.get("error"):
            report.errors.append(results["error"])
            report.passed = False
            report.overall_score = 0.0
            report.summary = self._build_summary(report)
            return report

        # Compute overall score from layer scores
        layers = results.get("layers", {})
        scores = []
        all_passed = True
        for name, layer_data in layers.items():
            if name.startswith("_"):
                if layer_data.get("error"):
                    report.errors.append(layer_data["error"])
                continue
            score = layer_data.get("score", 0.0)
            scores.append(score)
            if not layer_data.get("passed", False):
                all_passed = False
            if score < self._config.individual_minimum:
                all_passed = False

        if scores:
            report.overall_score = sum(scores) / len(scores)
        else:
            report.overall_score = 0.0

        # Pass criteria: overall >= threshold AND all layers >= individual minimum
        report.passed = (
            report.overall_score >= self._config.pass_threshold and all_passed
        )

        report.summary = self._build_summary(report)
        return report

    def print_summary(self, report: PlaytestReport) -> None:
        """Print 20-line human-readable summary to stdout."""
        print(report.summary)

    def _build_summary(self, report: PlaytestReport) -> str:
        """Build a ~20-line human-readable summary."""
        lines: list[str] = []
        status = "PASSED" if report.passed else "FAILED"
        lines.append(f"{'=' * 60}")
        lines.append(f"  World Test Kit — Playtest Report")
        lines.append(f"{'=' * 60}")
        lines.append(f"  Session:   {report.session_id}")
        lines.append(f"  Prompt:    {report.prompt[:50]}{'...' if len(report.prompt) > 50 else ''}")
        lines.append(f"  Duration:  {report.duration_s:.1f}s")
        lines.append(f"  Status:    {status}")
        lines.append(f"  Score:     {report.overall_score:.1f} / {report.pass_threshold}")
        lines.append(f"{'-' * 60}")
        lines.append(f"  {'Layer':<20} {'Score':>7} {'Status':>8}")
        lines.append(f"  {'-' * 37}")

        for name, data in report.layer_results.items():
            if name.startswith("_"):
                continue
            score = data.get("score", 0.0)
            passed = data.get("passed", False)
            marker = "OK" if passed else "FAIL"
            lines.append(f"  {name:<20} {score:>6.1f} {marker:>8}")

        lines.append(f"{'-' * 60}")

        if report.errors:
            lines.append(f"  Errors: {len(report.errors)}")
            for err in report.errors[:3]:
                lines.append(f"    • {err[:60]}")

        if report.scripted_mode:
            lines.append(f"  [!] Ran in scripted mode (Ollama unavailable)")

        lines.append(f"{'=' * 60}")
        return "\n".join(lines)
