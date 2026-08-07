"""Canonical canon-detection and approved-object manifest authority."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

DETECTED_SCHEMA = "detected-objects/v1"
SELECTED_SCHEMA = "selected-object-manifest/v1"


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_detected_document(
    raw_objects: Iterable[Any], *, canon_path: str | Path, width: int,
    height: int, model_used: str, strict: bool = True,
) -> dict[str, Any]:
    canon = Path(canon_path)
    if not canon.is_file() or width <= 0 or height <= 0:
        raise ValueError("canon image and positive dimensions are required")
    canon_hash = file_sha256(canon)
    objects: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_objects):
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("detection must be an object")
            name = str(raw.get("name", "")).strip()
            bbox_raw = raw.get("bbox")
            if not name or not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
                raise ValueError("detection requires name and four-value bbox")
            bbox = [int(round(float(value))) for value in bbox_raw]
            bbox = [max(0, min(value, width if i % 2 == 0 else height)) for i, value in enumerate(bbox)]
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise ValueError("detection bbox has no area")
            size_estimate = str(raw.get("size_estimate", "medium")).strip()
            if size_estimate not in {"large", "medium", "small", "tiny"}:
                raise ValueError("detection size_estimate is invalid")
            identity = f"{canon_hash}:{index}:{name.casefold()}:{','.join(map(str, bbox))}"
            objects.append({
                "id": index,
                "object_id": str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
                "detection_index": index,
                "name": name,
                "bbox": bbox,
                "material": str(raw.get("material", "unknown")).strip() or "unknown",
                "category": str(raw.get("category", "unknown")).strip() or "unknown",
                "size_estimate": size_estimate,
            })
        except (TypeError, ValueError):
            if strict:
                raise
    if strict and not objects:
        raise ValueError("strict-real vision inventory produced no valid objects")
    document: dict[str, Any] = {
        "schema_version": DETECTED_SCHEMA,
        "canon_sha256": canon_hash,
        "image_path": str(canon),
        "image_width": width,
        "image_height": height,
        "model_used": model_used,
        "objects": objects,
        "object_count": len(objects),
    }
    document["document_sha256"] = _digest(document)
    return document


def load_detected_document(path: str | Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = document.pop("document_sha256", "")
    if document.get("schema_version") != DETECTED_SCHEMA or expected != _digest(document):
        raise ValueError("detected-object document schema or hash is invalid")
    objects = document.get("objects")
    if not isinstance(objects, list) or document.get("object_count") != len(objects):
        raise ValueError("detected-object count is invalid")
    ids = [str(item.get("object_id", "")) for item in objects if isinstance(item, Mapping)]
    if not ids or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("detected-object IDs must be non-empty and unique")
    document["document_sha256"] = expected
    return document


def build_selected_manifest(
    detected: Mapping[str, Any], selected_ids: Iterable[Any], *,
    plan_revision: int, approval_revision: int,
) -> dict[str, Any]:
    objects = detected.get("objects", [])
    lookup: dict[str, Mapping[str, Any]] = {}
    for item in objects:
        if isinstance(item, Mapping):
            lookup[str(item.get("object_id", ""))] = item
            lookup[str(item.get("id", ""))] = item
    requested = [str(value) for value in selected_ids]
    if not requested:
        raise ValueError("blockout approval requires at least one selected object")
    selected: list[dict[str, Any]] = []
    stable_ids: set[str] = set()
    for value in requested:
        item = lookup.get(value)
        if item is None:
            raise ValueError(f"selected object is not in detected canon inventory: {value}")
        stable_id = str(item["object_id"])
        if stable_id in stable_ids:
            raise ValueError(f"duplicate selected object: {value}")
        stable_ids.add(stable_id)
        selected.append(dict(item))
    manifest: dict[str, Any] = {
        "schema_version": SELECTED_SCHEMA,
        "canon_sha256": str(detected["canon_sha256"]),
        "detected_objects_sha256": str(detected["document_sha256"]),
        "plan_revision": int(plan_revision),
        "approval_revision": int(approval_revision),
        "objects": selected,
        "object_count": len(selected),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def load_selected_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = manifest.pop("manifest_sha256", "")
    if manifest.get("schema_version") != SELECTED_SCHEMA or expected != _digest(manifest):
        raise ValueError("selected-object manifest schema or hash is invalid")
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects or manifest.get("object_count") != len(objects):
        raise ValueError("selected-object manifest must contain selected objects")
    manifest["manifest_sha256"] = expected
    return manifest