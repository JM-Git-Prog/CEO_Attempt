"""Approval queue for V16 pipeline proposed improvements.

Human-in-the-loop system: test infrastructure proposes changes (thresholds,
checklists, new tests, baselines) and the user thumbs-up or thumbs-down each
item from the browser overlay.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


APPROVAL_TYPES = (
    "threshold_change",
    "checklist_update",
    "new_test",
    "baseline_update",
    "vision_qa_verdict",
)


@dataclass
class ApprovalItem:
    id: str
    type: str  # one of APPROVAL_TYPES
    title: str  # one-line human summary
    description: str  # detail
    context: dict  # type-specific data (screenshot path, metrics, diff, etc.)
    screenshot_url: str | None = None  # relative URL to the relevant screenshot
    diff_url: str | None = None  # relative URL to diff image if applicable
    created_at: str = ""  # ISO timestamp
    status: str = "pending"  # "pending", "approved", "rejected"
    verdict_at: str | None = None  # ISO timestamp of verdict

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.type not in APPROVAL_TYPES:
            raise ValueError(f"Invalid approval type: {self.type!r}; must be one of {APPROVAL_TYPES}")


class ApprovalQueue:
    """Persists approval items to a single JSON file."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[ApprovalItem] = []
        self._load()

    def _load(self) -> None:
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                self._items = [ApprovalItem(**item) for item in data]
            except (json.JSONDecodeError, TypeError, KeyError):
                self._items = []
        else:
            self._items = []

    def _save(self) -> None:
        self.store_path.write_text(
            json.dumps([asdict(item) for item in self._items], indent=2),
            encoding="utf-8",
        )

    def add(self, item: ApprovalItem) -> None:
        """Add a new approval item to the queue."""
        self._items.append(item)
        self._save()

    def get_pending(self) -> list[ApprovalItem]:
        """Return all items with status 'pending'."""
        return [item for item in self._items if item.status == "pending"]

    def get_all(self) -> list[ApprovalItem]:
        """Return all items regardless of status."""
        return list(self._items)

    def verdict(self, item_id: str, approved: bool) -> ApprovalItem | None:
        """Mark an item as approved or rejected. Returns the item or None if not found."""
        for item in self._items:
            if item.id == item_id:
                item.status = "approved" if approved else "rejected"
                item.verdict_at = datetime.now(timezone.utc).isoformat()
                self._save()
                if approved:
                    promote_approved_item(item)
                return item
        return None

    def clear_completed(self) -> int:
        """Remove approved/rejected items older than 7 days. Returns count removed."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        before = len(self._items)
        self._items = [
            item for item in self._items
            if item.status == "pending"
            or (
                item.verdict_at
                and datetime.fromisoformat(item.verdict_at) > cutoff
            )
        ]
        removed = before - len(self._items)
        if removed:
            self._save()
        return removed


# --- Promotion logic ---

# Project root for resolving relative paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_E2E_DIR = _PROJECT_ROOT / "tests" / "e2e"
_CONFIG_DIR = _E2E_DIR / "config"


def promote_approved_item(item: ApprovalItem) -> None:
    """Execute promotion logic when an item is approved."""
    try:
        if item.type == "threshold_change":
            _promote_threshold(item)
        elif item.type == "checklist_update":
            _promote_checklist(item)
        elif item.type == "new_test":
            _promote_new_test(item)
        elif item.type == "baseline_update":
            _promote_baseline(item)
        elif item.type == "vision_qa_verdict":
            _promote_vision_verdict(item)
    except Exception as exc:
        # Log but don't crash the approval flow
        import logging
        logging.getLogger("approvals").warning(
            f"Promotion failed for {item.id} ({item.type}): {exc}"
        )


def _promote_threshold(item: ApprovalItem) -> None:
    """Copy recommended threshold into e2e_config.yaml."""
    recommendations_path = _CONFIG_DIR / "threshold_recommendations.json"
    config_path = _CONFIG_DIR / "e2e_config.yaml"

    if not recommendations_path.exists() or not config_path.exists():
        return

    recommendations = json.loads(recommendations_path.read_text(encoding="utf-8"))
    metric_key = item.context.get("metric_key")
    if not metric_key or metric_key not in recommendations:
        return

    new_value = recommendations[metric_key]
    # Read existing YAML, update the threshold line
    import re
    config_text = config_path.read_text(encoding="utf-8")
    # Pattern: key: old_value → key: new_value
    pattern = rf"^(\s*{re.escape(metric_key)}\s*:\s*)(.+)$"
    replacement = rf"\g<1>{new_value}"
    updated = re.sub(pattern, replacement, config_text, flags=re.MULTILINE)
    if updated != config_text:
        config_path.write_text(updated, encoding="utf-8")


def _promote_checklist(item: ApprovalItem) -> None:
    """Copy proposed checklist to active checklist."""
    proposed = _CONFIG_DIR / "vision_qa_checklist_proposed.json"
    active = _CONFIG_DIR / "vision_qa_checklist.json"
    if proposed.exists():
        shutil.copy2(proposed, active)


def _promote_new_test(item: ApprovalItem) -> None:
    """Move test from proposed/ to tests/e2e/ and remove proposed marker."""
    filename = item.context.get("filename")
    if not filename:
        return
    source = _E2E_DIR / "proposed" / filename
    dest = _E2E_DIR / filename
    if not source.exists():
        return
    content = source.read_text(encoding="utf-8")
    # Remove @pytest.mark.proposed decorator
    import re
    content = re.sub(r"@pytest\.mark\.proposed\s*\n", "", content)
    dest.write_text(content, encoding="utf-8")
    source.unlink()


def _promote_baseline(item: ApprovalItem) -> None:
    """Mark baseline as approved in its .meta.json."""
    baseline_path = item.context.get("baseline_path")
    if not baseline_path:
        return
    meta_path = Path(baseline_path).with_suffix(".meta.json")
    if not meta_path.exists():
        # Create meta file
        meta = {}
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["approved"] = True
    meta["approved_at"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _promote_vision_verdict(item: ApprovalItem) -> None:
    """Record human verdict for training data — no file promotion needed."""
    # The verdict is already recorded in the queue item itself.
    # Optionally append to a training log for future model improvement.
    training_log = _E2E_DIR / "artifacts" / "vision_qa_training_log.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "item_id": item.id,
        "context": item.context,
        "human_verdict": "approved",
    }
    with training_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# --- Default queue instance ---

_DEFAULT_STORE = _E2E_DIR / "artifacts" / ".approval_queue.json"


def get_default_queue() -> ApprovalQueue:
    """Get the singleton approval queue instance."""
    return ApprovalQueue(_DEFAULT_STORE)
