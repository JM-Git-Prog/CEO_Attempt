"""FastAPI routes for the V16 approval overlay system.

Provides endpoints for listing pending approvals, casting verdicts,
and serving screenshot/diff images from the artifacts directory.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from src.web.approvals import ApprovalQueue, get_default_queue

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# Artifacts root for serving screenshots/diffs
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ARTIFACTS_DIR = _PROJECT_ROOT / "tests" / "e2e" / "artifacts"


def _queue() -> ApprovalQueue:
    """Get the approval queue (allows test injection later)."""
    return get_default_queue()


@router.get("")
async def list_pending():
    """Return all pending approval items."""
    queue = _queue()
    return [asdict(item) for item in queue.get_pending()]


@router.get("/all")
async def list_all():
    """Return all approval items including resolved ones."""
    queue = _queue()
    return [asdict(item) for item in queue.get_all()]


@router.post("/{item_id}/approve")
async def approve_item(item_id: str):
    """Mark an item as approved and trigger promotion."""
    queue = _queue()
    item = queue.verdict(item_id, approved=True)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Approval item {item_id!r} not found")
    return asdict(item)


@router.post("/{item_id}/reject")
async def reject_item(item_id: str):
    """Mark an item as rejected."""
    queue = _queue()
    item = queue.verdict(item_id, approved=False)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Approval item {item_id!r} not found")
    return asdict(item)


@router.get("/screenshot/{path:path}")
async def serve_screenshot(path: str):
    """Serve a screenshot or diff image from the artifacts directory."""
    # Resolve and validate the path is within artifacts
    file_path = (_ARTIFACTS_DIR / path).resolve()
    if not file_path.is_relative_to(_ARTIFACTS_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    # Determine media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    return FileResponse(file_path, media_type=media_type)
