"""Session integration for the photo-to-playable-world pipeline.

Bridges the photo pipeline with the existing session management infrastructure
(SessionManager, FIFO compilation queue). Creates sessions with source_type="photo"
metadata and stores PhotoSessionMetadata alongside the session for downstream
stages and diagnostics.

Requirements: 11.1, 11.7, 14.5
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from src.models import PipelineState, SessionMode, WorldSession
from src.photo_pipeline.models import PhotoSessionMetadata
from src.session_manager import SessionManager, SessionQueue

logger = logging.getLogger(__name__)

# Default output base for photo sessions — same root as text sessions
_DEFAULT_OUTPUT_BASE = Path("output/sessions")


def create_photo_session(
    session_manager: SessionManager,
    source_image_path: Path,
    *,
    mode: SessionMode = SessionMode.MVP,
    description: str = "Photo-to-world pipeline session",
) -> tuple[str, Path]:
    """Create a new session for the photo pipeline via the existing SessionManager.

    Uses the standard SessionManager.create_session() flow to get a unique session ID
    and isolated output directory, then writes a photo-specific metadata stub
    (source_type="photo") so that the session is distinguishable from text sessions.

    Args:
        session_manager: The existing SessionManager instance.
        source_image_path: Path to the source RGB image being processed.
        mode: Pipeline execution mode (MVP or FULL). Defaults to MVP.
        description: Human-readable session description.

    Returns:
        A tuple of (session_id, output_directory_path).
    """
    session = session_manager.create_session(description, mode)
    session_dir = Path(session.output_path)

    # Write a photo-session marker with source_type="photo" so downstream code
    # can distinguish photo sessions from text sessions (Requirement 14.5).
    photo_meta_stub = {
        "source_type": "photo",
        "source_image_path": str(source_image_path),
        "session_id": session.session_id,
    }
    meta_file = session_dir / "photo_session_meta.json"
    meta_file.write_text(json.dumps(photo_meta_stub, indent=2), encoding="utf-8")

    logger.info(
        "Created photo session %s for image %s",
        session.session_id,
        source_image_path,
    )

    return session.session_id, session_dir


def store_photo_session_metadata(
    session_dir: Path,
    metadata: PhotoSessionMetadata,
) -> Path:
    """Persist full PhotoSessionMetadata alongside the session.

    Called after the pipeline completes (or partially completes) to record
    the source_image_hash, resolution, quality classification, and pipeline
    statistics.

    Args:
        session_dir: The session's output directory (from create_photo_session).
        metadata: The completed PhotoSessionMetadata dataclass instance.

    Returns:
        Path to the written metadata JSON file.
    """
    meta_path = session_dir / "photo_session_meta.json"

    # Convert frozen dataclass to a serializable dict; Path fields → strings
    meta_dict = asdict(metadata)
    meta_dict["source_image_path"] = str(metadata.source_image_path)

    meta_path.write_text(json.dumps(meta_dict, indent=2, sort_keys=True), encoding="utf-8")

    logger.info(
        "Stored PhotoSessionMetadata for session in %s (quality=%s, objects=%d)",
        session_dir.name,
        metadata.quality_classification,
        metadata.object_count,
    )

    return meta_path


async def queue_for_compilation(
    session_queue: SessionQueue,
    session_id: str,
    session_manager: SessionManager,
) -> bool:
    """Enqueue a photo session for UPBGE compilation via the existing FIFO queue.

    The photo pipeline enters the queue at the WorldContract → UPBGE compilation
    stage, reusing the same serialized compilation path as the text pipeline
    (Requirement 14.3).

    Args:
        session_queue: The existing FIFO SessionQueue instance.
        session_id: The session ID to enqueue.
        session_manager: SessionManager to load the session.

    Returns:
        True if the session starts compilation immediately (queue was empty),
        False if it was queued behind another active compilation.
    """
    # Load the persisted session to pass to the queue
    session_file = session_manager.output_base / session_id / "session.json"
    session = WorldSession.model_validate_json(session_file.read_text(encoding="utf-8"))

    # Update state to indicate we're entering compilation
    session.state = PipelineState.ASSEMBLING_WORLD
    _save_session_state(session, session_manager)

    starts_immediately = await session_queue.enqueue(session)

    if starts_immediately:
        logger.info("Photo session %s starts UPBGE compilation immediately", session_id)
    else:
        logger.info(
            "Photo session %s queued for compilation (pending: %d)",
            session_id,
            session_queue.pending_count,
        )

    return starts_immediately


def get_session_source_type(session_dir: Path) -> Literal["photo", "text"]:
    """Determine whether a session is a photo or text session.

    Checks for the presence of photo_session_meta.json with source_type="photo".
    Falls back to "text" if the file is missing or doesn't contain a photo marker.

    Args:
        session_dir: Path to the session directory.

    Returns:
        "photo" or "text".
    """
    meta_file = session_dir / "photo_session_meta.json"
    if not meta_file.exists():
        return "text"

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("source_type") == "photo":
            return "photo"
    except (json.JSONDecodeError, OSError):
        pass

    return "text"


def _save_session_state(session: WorldSession, session_manager: SessionManager) -> None:
    """Persist updated session state back to session.json."""
    session_dir = session_manager.output_base / session.session_id
    session_file = session_dir / "session.json"
    session_file.write_text(session.model_dump_json(indent=2), encoding="utf-8")
