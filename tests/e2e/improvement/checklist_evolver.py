"""Cloud model vision QA checklist evolution for the E2E testing framework.

Triggers after 20+ vision QA results have accumulated. Submits the result
corpus (verdicts, failed_checks, confidence) to a cloud reasoning model
to analyze false positives, missed issues, and propose new categories.

Outputs proposed revision to tests/e2e/config/vision_qa_checklist_proposed.json.
Never auto-modifies the active checklist — requires human approval.

Requirements: 27.1–27.4
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Trigger threshold: minimum vision QA results before evolution
EVOLUTION_TRIGGER_VERDICTS = 20

# Output path for proposed checklist revision
PROPOSED_CHECKLIST_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "vision_qa_checklist_proposed.json"
)

# Active checklist path
ACTIVE_CHECKLIST_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "vision_qa_checklist.json"
)

# Default cloud model for checklist evolution
DEFAULT_EVOLUTION_MODEL = "deepseek-v3.1:671b-cloud"


@dataclass
class VisionQAResult:
    """A single vision QA result from a nightly run.

    Attributes:
        run_id: The test run identifier.
        verdict_pass: Whether the vision model passed the image.
        failed_checks: List of checklist categories that failed.
        confidence: Model confidence in the verdict.
        timestamp: When the verdict was produced.
    """

    run_id: str
    verdict_pass: bool
    failed_checks: list[str]
    confidence: float
    timestamp: str = ""


@dataclass
class ChecklistCategory:
    """A single category in the vision QA checklist.

    Attributes:
        name: Category identifier (e.g., "geometry", "count").
        description: What this category checks.
        criteria: Specific evaluation criteria.
        weight: Relative importance (0.0–1.0).
    """

    name: str
    description: str
    criteria: list[str] = field(default_factory=list)
    weight: float = 1.0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "criteria": self.criteria,
            "weight": self.weight,
        }


@dataclass
class ChecklistProposal:
    """Proposed revision to the vision QA checklist.

    Attributes:
        categories: The proposed category list.
        changes_summary: Human-readable summary of what changed.
        added_categories: New categories proposed.
        removed_categories: Categories proposed for removal.
        modified_categories: Categories with modified criteria.
        justification: Overall justification for the revision.
        diff_against_current: Textual diff against the current checklist.
    """

    categories: list[ChecklistCategory]
    changes_summary: str = ""
    added_categories: list[str] = field(default_factory=list)
    removed_categories: list[str] = field(default_factory=list)
    modified_categories: list[str] = field(default_factory=list)
    justification: str = ""
    diff_against_current: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "categories": [c.to_dict() for c in self.categories],
            "changes_summary": self.changes_summary,
            "added_categories": self.added_categories,
            "removed_categories": self.removed_categories,
            "modified_categories": self.modified_categories,
            "justification": self.justification,
            "diff_against_current": self.diff_against_current,
        }


def collect_vision_qa_results(
    artifacts_base: Path,
    min_verdicts: int = EVOLUTION_TRIGGER_VERDICTS,
) -> list[VisionQAResult] | None:
    """Collect vision QA results from stored nightly run artifacts.

    Scans tests/e2e/artifacts/*/vision_qa/ for verdict JSON files.

    Args:
        artifacts_base: Base artifacts directory.
        min_verdicts: Minimum verdicts required to trigger evolution.

    Returns:
        List of VisionQAResult objects, or None if below threshold.
    """
    results: list[VisionQAResult] = []

    if not artifacts_base.exists():
        logger.warning("Artifacts directory does not exist: %s", artifacts_base)
        return None

    for run_dir in sorted(artifacts_base.iterdir()):
        if not run_dir.is_dir():
            continue
        vision_dir = run_dir / "vision_qa"
        if not vision_dir.exists():
            continue

        for verdict_file in vision_dir.glob("*.json"):
            try:
                data = json.loads(verdict_file.read_text(encoding="utf-8"))
                result = VisionQAResult(
                    run_id=run_dir.name,
                    verdict_pass=bool(data.get("pass", False)),
                    failed_checks=data.get("failed_checks", []),
                    confidence=float(data.get("confidence", 0.0)),
                    timestamp=data.get("timestamp", ""),
                )
                results.append(result)
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("Could not read verdict %s: %s", verdict_file, exc)

    if len(results) < min_verdicts:
        logger.info(
            "Only %d vision QA results found (need %d for evolution trigger)",
            len(results),
            min_verdicts,
        )
        return None

    return results


def load_active_checklist(
    checklist_path: Path | None = None,
) -> list[ChecklistCategory]:
    """Load the active vision QA checklist.

    Args:
        checklist_path: Override path to the checklist JSON.

    Returns:
        List of ChecklistCategory objects.
    """
    path = checklist_path or ACTIVE_CHECKLIST_PATH
    if not path.exists():
        logger.warning("Active checklist not found at %s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        categories: list[ChecklistCategory] = []
        for item in data.get("categories", []):
            categories.append(
                ChecklistCategory(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    criteria=item.get("criteria", []),
                    weight=float(item.get("weight", 1.0)),
                )
            )
        return categories
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load active checklist: %s", exc)
        return []


def build_evolution_prompt(
    results: list[VisionQAResult],
    current_checklist: list[ChecklistCategory],
) -> str:
    """Build a prompt for the cloud model to analyze and propose checklist changes.

    Args:
        results: Collected vision QA results.
        current_checklist: The current active checklist categories.

    Returns:
        Prompt string for cloud model submission.
    """
    # Compute statistics per category
    category_stats: dict[str, dict[str, int]] = {}
    total_pass = sum(1 for r in results if r.verdict_pass)
    total_fail = sum(1 for r in results if not r.verdict_pass)

    for result in results:
        for check in result.failed_checks:
            if check not in category_stats:
                category_stats[check] = {"count": 0, "high_conf": 0, "low_conf": 0}
            category_stats[check]["count"] += 1
            if result.confidence >= 0.8:
                category_stats[check]["high_conf"] += 1
            else:
                category_stats[check]["low_conf"] += 1

    prompt = f"""Analyze the following vision QA results corpus and propose improvements
to the evaluation checklist.

## Summary
- Total verdicts: {len(results)}
- Pass: {total_pass}, Fail: {total_fail}
- Pass rate: {total_pass / len(results) * 100:.1f}%

## Current Checklist Categories
"""
    for cat in current_checklist:
        prompt += f"- **{cat.name}**: {cat.description}\n"
        for criterion in cat.criteria:
            prompt += f"  - {criterion}\n"

    prompt += "\n## Failed Check Statistics\n"
    for check, stats in sorted(category_stats.items(), key=lambda x: -x[1]["count"]):
        prompt += (
            f"- {check}: {stats['count']} failures "
            f"({stats['high_conf']} high-confidence, {stats['low_conf']} low-confidence)\n"
        )

    prompt += f"""
## Confidence Distribution
- High confidence (>= 0.8): {sum(1 for r in results if r.confidence >= 0.8)} verdicts
- Low confidence (< 0.8): {sum(1 for r in results if r.confidence < 0.8)} verdicts
- Average confidence: {sum(r.confidence for r in results) / len(results):.2f}

## Task
Analyze:
1. Which categories produce the most false positives (high failure count + low confidence)?
2. Which categories miss genuine issues (never fail but should)?
3. What new categories might be valuable?
4. Should any criteria be tightened or relaxed?

## Required Output Format
Respond with ONLY a JSON object:
{{
    "changes_summary": "Brief summary of proposed changes",
    "justification": "Overall reasoning",
    "added_categories": ["new_category_name"],
    "removed_categories": ["category_to_remove"],
    "modified_categories": ["category_with_changes"],
    "categories": [
        {{
            "name": "category_name",
            "description": "What this checks",
            "criteria": ["criterion 1", "criterion 2"],
            "weight": 1.0
        }}
    ]
}}
"""
    return prompt


def parse_evolution_response(
    response_text: str,
    current_checklist: list[ChecklistCategory],
) -> ChecklistProposal | None:
    """Parse the cloud model's checklist evolution response.

    Args:
        response_text: Raw response from the cloud model.
        current_checklist: Current active checklist for diff generation.

    Returns:
        ChecklistProposal if parsing succeeds, None otherwise.
    """
    try:
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            text = text.strip()

        data = json.loads(text)

        categories: list[ChecklistCategory] = []
        for item in data.get("categories", []):
            categories.append(
                ChecklistCategory(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    criteria=item.get("criteria", []),
                    weight=float(item.get("weight", 1.0)),
                )
            )

        # Generate diff against current
        current_names = {c.name for c in current_checklist}
        proposed_names = {c.name for c in categories}
        diff_lines = []
        for name in proposed_names - current_names:
            diff_lines.append(f"+ Added: {name}")
        for name in current_names - proposed_names:
            diff_lines.append(f"- Removed: {name}")
        for name in current_names & proposed_names:
            diff_lines.append(f"~ Modified: {name}")

        proposal = ChecklistProposal(
            categories=categories,
            changes_summary=data.get("changes_summary", ""),
            added_categories=data.get("added_categories", []),
            removed_categories=data.get("removed_categories", []),
            modified_categories=data.get("modified_categories", []),
            justification=data.get("justification", ""),
            diff_against_current="\n".join(diff_lines),
        )

        return proposal

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse evolution response: %s", exc)
        return None


def store_proposed_checklist(
    proposal: ChecklistProposal,
    output_path: Path | None = None,
) -> Path:
    """Store the proposed checklist revision as JSON.

    Args:
        proposal: The checklist proposal.
        output_path: Override output path.

    Returns:
        Path to the stored proposed checklist file.
    """
    target = output_path or PROPOSED_CHECKLIST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(proposal.to_dict(), indent=2),
        encoding="utf-8",
    )
    logger.info("Proposed checklist stored at %s", target)
    return target
