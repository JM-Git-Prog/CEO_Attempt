"""The event log — one append per model-backed turn, misses included.

John's decision, 2026-09-04 (Model Router research, card 1): **capture everything,
curate later.** Capture and curation are different decisions and only capture is
irreversible — filtering is a query you can run any day, but a rejected candidate
never written down is a preference pair destroyed forever.

Before this file, ``/api/v17/say`` classified every sentence John typed — the kind,
the confidence, the reason, which model answered, what the photo showed, whether the
backend failed — handed it to the browser and dropped it. That is the exact shape of
the north star ("a text generated complete walkable world"): sentence in, judged world
action out. It was being thrown away on every single turn.

WHAT MUST BE WRITTEN AT THE MOMENT (unrecoverable afterwards):
  * ``prompt_rendered`` — the exact string sent to the model. The prompt is assembled
    from the standing line, the picture summary and the sentence; that template drifts,
    so the sentence alone does not reproduce the call.
  * ``model.digest``   — a tag repoints to different weights over time. Only the digest
    freezes which weights actually answered.
  * ``router.candidates`` — the lane as considered, in order, with the chosen one and
    its rank. A log naming only the winner cannot train a better router later, because
    it never says what the alternatives were.
  * ``outcome.error.kind`` — transport vs bad_answer, kept apart. A backend outage must
    never score as a bad answer (house law).
  * ``versions`` — the meaning of a row depends on the code that produced it.

NEVER FATAL. Every failure here is swallowed: the chat must answer John even when the
disk is full. Append-only, one JSON object per line, never read-modify-write.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Lives with the rest of the training material (doc 27 §4's training-data/ tree).
# Override with V17_EVENT_LOG for a sim- namespace run.
DEFAULT_LOG = (
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\training-data\events.jsonl"
)

SCHEMA_VERSION = 1
APP = "V17"


def log_path() -> Path:
    return Path(os.getenv("V17_EVENT_LOG", DEFAULT_LOG))


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def append_event(**fields) -> str | None:
    """Append one row. Returns its event_id, or None if the write failed.

    Never raises: a logging failure must not cost John an answer.
    """
    try:
        event_id = uuid.uuid4().hex
        row = {
            "event_id": event_id,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "schema_v": SCHEMA_VERSION,
            "app": APP,
            **fields,
        }
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return event_id
    except Exception as exc:  # noqa: BLE001 - deliberately total
        try:
            logging.getLogger("live_trace").warning("  EVENT LOG write failed: %s", exc)
        except Exception:  # noqa: BLE001
            pass
        return None
