"""Append-only, privacy-conscious interface event logging."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_ALLOWED_TYPES = {"click", "process", "lifecycle", "test"}


def _text(value: object, limit: int) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def append_event(output_dir: Path, event: dict) -> dict:
    """Validate and append one event to its interface-version JSONL file."""
    raw_version = _text(event.get("app_version"), 2)
    version = raw_version if re.fullmatch(r"\d{1,2}", raw_version) else "unknown"
    event_type = _text(event.get("event_type"), 24)
    if event_type not in _ALLOWED_TYPES:
        raise ValueError("Unsupported event type")
    raw_session = _text(event.get("session_id"), 40)
    session_id = raw_session if re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", raw_session) else None
    raw_details = event.get("details") if isinstance(event.get("details"), dict) else {}
    details = {
        _text(key, 40): value if isinstance(value, (bool, int, float)) else _text(value, 200)
        for key, value in list(raw_details.items())[:16]
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_version": version,
        "session_id": session_id,
        "event_type": event_type,
        "action": _text(event.get("action"), 120),
        "details": details,
    }
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK, (log_dir / f"v{version}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record
