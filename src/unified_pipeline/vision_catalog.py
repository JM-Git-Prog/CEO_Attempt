"""V2.0 Vision Catalog — Phase 3 (Catalog).

Sends all generated views to a vision model (qwen2.5vl:7b) to detect
every visible object, then merges results across views to produce a
unified, deduplicated object catalog with stable UUIDs.

Cross-view deduplication uses name similarity to identify the same
object seen from multiple angles and select the best reference crop.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import httpx

from src.unified_pipeline.multi_view_generator import MultiViewResult, ViewResult

logger = logging.getLogger("live_trace")

OLLAMA_URL = "http://127.0.0.1:11434"
VISION_TIMEOUT = 180.0


@dataclass
class CatalogEntry:
    """One unique object in the unified catalog."""

    uuid: str
    name: str
    material: str
    category: str
    size_estimate: str
    best_view_index: int
    bbox_in_best_view: list[int]
    views_visible_in: list[int]
    brief_manifest_match: str = ""
    count: int = 1


@dataclass
class ObjectCatalog:
    """Complete catalog of all unique objects detected across views."""

    entries: list[CatalogEntry] = field(default_factory=list)
    total_detections: int = 0
    views_analyzed: int = 0


def _name_similarity(a: str, b: str) -> float:
    """Compute normalized name similarity between two object names."""
    a_clean = re.sub(r"[^a-z0-9 ]", "", a.lower().strip())
    b_clean = re.sub(r"[^a-z0-9 ]", "", b.lower().strip())
    if a_clean == b_clean:
        return 1.0
    return SequenceMatcher(None, a_clean, b_clean).ratio()


def _bbox_area(bbox: list[int]) -> int:
    """Compute bounding box area."""
    if len(bbox) != 4:
        return 0
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


async def _analyze_view(
    view: ViewResult,
    model: str = "qwen2.5vl:7b",
) -> list[dict[str, Any]]:
    """Send one view to the vision model and extract detected objects.

    Returns a list of detection dicts with name, bbox, material, category, size_estimate.
    """
    canon_path = Path(view.canon_path)
    if not canon_path.is_file():
        logger.warning(f"  catalog: view {view.index} canon not found: {canon_path}")
        return []

    # Read and encode the image
    with open(canon_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Get image dimensions
    from PIL import Image
    with Image.open(canon_path) as img:
        width, height = img.size

    # Structured extraction prompt
    vision_prompt = (
        f"Analyze this interior room photograph ({width}x{height} pixels). "
        f"List EVERY distinct object you can identify.\n"
        f"For each object provide:\n"
        f"- name: short descriptive name (e.g. 'round wooden table', 'pendant light')\n"
        f"- bbox: [x1, y1, x2, y2] pixel bounding box\n"
        f"- material: primary material (wood, metal, glass, fabric, ceramic, plastic, stone)\n"
        f"- category: one of (furniture, lighting, decor, appliance, utensil, plant, architectural, storage)\n"
        f"- size_estimate: one of (large, medium, small, tiny)\n\n"
        f"Respond ONLY with a JSON array. No markdown, no explanation.\n"
        f'Example: [{{"name":"kitchen island","bbox":[100,200,600,500],"material":"wood","category":"furniture","size_estimate":"large"}}]'
    )

    # Schema for constrained output
    inventory_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "bbox": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                "material": {"type": "string"},
                "category": {"type": "string"},
                "size_estimate": {"type": "string"},
            },
            "required": ["name", "bbox", "material", "category", "size_estimate"],
        },
    }

    # Try vision models in order
    for model_name in [model, "qwen3.6:27b"]:
        try:
            async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "user", "content": vision_prompt, "images": [image_b64]},
                        ],
                        "stream": False,
                        "keep_alive": 0,
                        "format": inventory_schema,
                        "options": {"temperature": 0.0, "num_predict": 2048},
                    },
                )
                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("message", {}).get("content", "")
                    return _parse_detections(content, width, height)
                else:
                    logger.warning(f"  catalog: {model_name} returned {resp.status_code}")
        except httpx.TimeoutException:
            logger.warning(f"  catalog: {model_name} timed out for view {view.index}")
        except Exception as exc:
            logger.warning(f"  catalog: {model_name} failed for view {view.index}: {exc}")

    return []


def _parse_detections(content: str, width: int, height: int) -> list[dict[str, Any]]:
    """Parse vision model response into a list of detection dicts."""
    content = content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        content = "\n".join(lines).strip()

    # Find JSON array in content
    json_match = re.search(r"\[.*\]", content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            # Validate and clamp bounding boxes
            valid = []
            for item in parsed:
                if not isinstance(item, dict) or "name" not in item:
                    continue
                bbox = item.get("bbox", [0, 0, 100, 100])
                if isinstance(bbox, list) and len(bbox) == 4:
                    bbox = [
                        max(0, min(int(bbox[0]), width)),
                        max(0, min(int(bbox[1]), height)),
                        max(0, min(int(bbox[2]), width)),
                        max(0, min(int(bbox[3]), height)),
                    ]
                    item["bbox"] = bbox
                valid.append(item)
            return valid
    except json.JSONDecodeError:
        # Try fixing trailing commas
        try:
            fixed = re.sub(r",\s*]", "]", content)
            fixed = re.sub(r",\s*}", "}", fixed)
            parsed = json.loads(fixed)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict) and "name" in item]
        except json.JSONDecodeError:
            pass

    return []


def _merge_detections(
    all_detections: list[tuple[int, list[dict[str, Any]]]],
    brief: dict[str, Any],
    similarity_threshold: float = 0.65,
) -> ObjectCatalog:
    """Merge detections from multiple views into a deduplicated catalog.

    Objects with similar names (>= threshold) are considered the same object
    seen from different angles. The best reference crop is the one with the
    largest bounding box area (least occluded, most detail).
    """
    # Flatten all detections with view index
    all_items: list[dict[str, Any]] = []
    for view_idx, detections in all_detections:
        for det in detections:
            all_items.append({**det, "_view_index": view_idx})

    if not all_items:
        return ObjectCatalog()

    # Greedy deduplication by name similarity
    clusters: list[list[dict[str, Any]]] = []
    used: set[int] = set()

    for i, item in enumerate(all_items):
        if i in used:
            continue
        cluster = [item]
        used.add(i)

        for j in range(i + 1, len(all_items)):
            if j in used:
                continue
            if _name_similarity(item.get("name", ""), all_items[j].get("name", "")) >= similarity_threshold:
                cluster.append(all_items[j])
                used.add(j)

        clusters.append(cluster)

    # Build catalog entries from clusters
    entries: list[CatalogEntry] = []
    brief_objects = brief.get("object_manifest", [])

    for cluster in clusters:
        # Pick the detection with largest bbox as "best"
        best = max(cluster, key=lambda d: _bbox_area(d.get("bbox", [0, 0, 0, 0])))

        # Collect all views this object appears in
        views_visible = sorted(set(d["_view_index"] for d in cluster))

        # Match to Brief manifest
        name = best.get("name", "unknown")
        manifest_match = ""
        for obj in brief_objects:
            if isinstance(obj, dict):
                obj_name = obj.get("name", "")
                if _name_similarity(name, obj_name) >= 0.5:
                    manifest_match = obj_name
                    break

        entry = CatalogEntry(
            uuid=str(uuid.uuid4()),
            name=name,
            material=best.get("material", "unknown"),
            category=best.get("category", "furniture"),
            size_estimate=best.get("size_estimate", "medium"),
            best_view_index=best["_view_index"],
            bbox_in_best_view=best.get("bbox", [0, 0, 0, 0]),
            views_visible_in=views_visible,
            brief_manifest_match=manifest_match,
        )
        entries.append(entry)

    total_detections = sum(len(dets) for _, dets in all_detections)

    return ObjectCatalog(
        entries=entries,
        total_detections=total_detections,
        views_analyzed=len(all_detections),
    )


async def catalog_objects(
    views: MultiViewResult,
    brief: dict[str, Any],
    session_dir: Path,
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> ObjectCatalog:
    """Analyze all views with vision model and produce unified object catalog (Phase 3).

    Args:
        views: MultiViewResult from Phase 2.
        brief: Structured Brief dict.
        session_dir: Session output directory.
        emit_fn: Optional SSE event emitter.

    Returns:
        ObjectCatalog with deduplicated entries.
    """
    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    logger.info(f"  V2 catalog: analyzing {len(views.views)} views...")

    # Analyze each view
    all_detections: list[tuple[int, list[dict[str, Any]]]] = []

    for view in views.views:
        logger.info(f"  V2 catalog: analyzing view {view.index}...")
        detections = await _analyze_view(view)
        all_detections.append((view.index, detections))
        logger.info(f"  V2 catalog: view {view.index} → {len(detections)} objects detected")

    # Merge and deduplicate
    catalog = _merge_detections(all_detections, brief)

    # Save catalog to disk
    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    catalog_data = {
        "entries": [
            {
                "uuid": e.uuid,
                "name": e.name,
                "material": e.material,
                "category": e.category,
                "size_estimate": e.size_estimate,
                "best_view_index": e.best_view_index,
                "bbox_in_best_view": e.bbox_in_best_view,
                "views_visible_in": e.views_visible_in,
                "brief_manifest_match": e.brief_manifest_match,
                "count": e.count,
            }
            for e in catalog.entries
        ],
        "total_detections": catalog.total_detections,
        "views_analyzed": catalog.views_analyzed,
        "unique_objects": len(catalog.entries),
    }
    (artifacts_dir / "catalog.json").write_text(
        json.dumps(catalog_data, indent=2), encoding="utf-8"
    )

    emit("catalog_complete", {
        "object_count": len(catalog.entries),
        "objects": [e.name for e in catalog.entries],
        "views_analyzed": catalog.views_analyzed,
        "total_detections": catalog.total_detections,
    })

    logger.info(
        f"  V2 catalog complete: {len(catalog.entries)} unique objects "
        f"from {catalog.total_detections} detections across {catalog.views_analyzed} views"
    )
    return catalog
