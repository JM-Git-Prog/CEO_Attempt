"""Bridge between the test improvement loop and the approval queue.

The failure_analyzer, coverage_discoverer, threshold_calibrator, and
checklist_evolver call `queue_approval_from_improvement(...)` to enqueue
items after their analysis runs. The user then approves/rejects from the
browser overlay.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.web.approvals import ApprovalItem, get_default_queue


def queue_approval_from_improvement(
    *,
    approval_type: str,
    title: str,
    description: str,
    context: dict[str, Any] | None = None,
    screenshot_url: str | None = None,
    diff_url: str | None = None,
) -> ApprovalItem:
    """Enqueue an approval item from the improvement loop.

    Parameters
    ----------
    approval_type : str
        One of: threshold_change, checklist_update, new_test,
        baseline_update, vision_qa_verdict
    title : str
        One-line human-readable summary shown in the overlay card.
    description : str
        Multi-line detail shown when the card is expanded.
    context : dict, optional
        Type-specific data. For threshold_change, include metric_key.
        For new_test, include filename. For baseline_update, include
        baseline_path. For vision_qa_verdict, include image path and
        model verdict.
    screenshot_url : str, optional
        Relative path (within tests/e2e/artifacts/) to a screenshot image.
    diff_url : str, optional
        Relative path (within tests/e2e/artifacts/) to a diff image.

    Returns
    -------
    ApprovalItem
        The created and enqueued item.
    """
    item = ApprovalItem(
        id=uuid.uuid4().hex[:12],
        type=approval_type,
        title=title,
        description=description,
        context=context or {},
        screenshot_url=screenshot_url,
        diff_url=diff_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        status="pending",
        verdict_at=None,
    )
    queue = get_default_queue()
    queue.add(item)
    return item


# --- Convenience wrappers for each improvement module ---


def queue_threshold_change(
    metric_key: str,
    old_value: Any,
    new_value: Any,
    reason: str,
    screenshot_url: str | None = None,
) -> ApprovalItem:
    """Queue a threshold calibration change for approval."""
    return queue_approval_from_improvement(
        approval_type="threshold_change",
        title=f"Threshold: {metric_key} → {new_value}",
        description=f"Recommended change from {old_value} to {new_value}. {reason}",
        context={
            "metric_key": metric_key,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
        },
        screenshot_url=screenshot_url,
    )


def queue_checklist_update(
    summary: str,
    changes: list[str],
    diff_url: str | None = None,
) -> ApprovalItem:
    """Queue a vision QA checklist update for approval."""
    return queue_approval_from_improvement(
        approval_type="checklist_update",
        title=f"Checklist: {summary}",
        description="\n".join(f"• {c}" for c in changes),
        context={"summary": summary, "changes": changes},
        diff_url=diff_url,
    )


def queue_new_test(
    filename: str,
    test_summary: str,
    discovered_from: str | None = None,
) -> ApprovalItem:
    """Queue a newly discovered test for approval."""
    return queue_approval_from_improvement(
        approval_type="new_test",
        title=f"New test: {filename}",
        description=f"{test_summary}\nDiscovered from: {discovered_from or 'analysis'}",
        context={
            "filename": filename,
            "test_summary": test_summary,
            "discovered_from": discovered_from,
        },
    )


def queue_baseline_update(
    baseline_path: str,
    reason: str,
    screenshot_url: str | None = None,
    diff_url: str | None = None,
) -> ApprovalItem:
    """Queue a baseline image update for approval."""
    return queue_approval_from_improvement(
        approval_type="baseline_update",
        title=f"Baseline: {baseline_path.split('/')[-1] if '/' in baseline_path else baseline_path}",
        description=reason,
        context={"baseline_path": baseline_path, "reason": reason},
        screenshot_url=screenshot_url,
        diff_url=diff_url,
    )


def queue_vision_qa_verdict(
    image_path: str,
    model_verdict: dict[str, Any],
    screenshot_url: str | None = None,
) -> ApprovalItem:
    """Queue a vision QA model verdict for human confirmation."""
    confidence = model_verdict.get("confidence", "?")
    passed = model_verdict.get("pass", False)
    status_text = "PASS" if passed else "FAIL"
    return queue_approval_from_improvement(
        approval_type="vision_qa_verdict",
        title=f"Vision QA: {status_text} ({confidence})",
        description=f"Model says {status_text} with confidence {confidence}.\nFailed checks: {model_verdict.get('failed_checks', [])}",
        context={
            "image_path": image_path,
            "model_verdict": model_verdict,
        },
        screenshot_url=screenshot_url,
    )
