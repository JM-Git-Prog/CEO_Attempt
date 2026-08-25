"""Canonical canon-detection and approved-object manifest authority."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

DETECTED_SCHEMA = "detected-objects/v1"
SELECTED_SCHEMA = "selected-object-manifest/v1"
PLAN_SELECTED_SCHEMA = "plan-bound-selected-object-manifest/v2"


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
    """Build retained detection-keyed v1 manifests for legacy tooling only."""
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


def _validated_picker(picker: Mapping[str, Any]) -> None:
    payload = dict(picker)
    expected = str(payload.pop("document_sha256", ""))
    if not expected or expected != _digest(payload):
        raise ValueError("object-picker schema or hash is invalid")
    if picker.get("fuzzy_matching_used") is not False:
        raise ValueError("fuzzy matching cannot authorize selected objects")


def resolve_plan_selected_objects(
    detected: Mapping[str, Any], picker: Mapping[str, Any], selected_ids: Iterable[Any],
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Resolve detections to Plan instances using approved semantic bindings only."""
    _validated_picker(picker)
    detected_by_id = {
        str(item.get("object_id", "")): item
        for item in detected.get("objects", []) if isinstance(item, Mapping)
    }
    picker_by_detection = {
        str(item.get("object_id", "")): item
        for item in picker.get("objects", []) if isinstance(item, Mapping)
    }
    requested = tuple(str(value) for value in selected_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("selected detection IDs must be non-empty and unique")

    expected = tuple(
        str(plan_id)
        for binding in picker.get("required_bindings", [])
        if isinstance(binding, Mapping)
        for plan_id in binding.get("plan_binding_ids", [])
        if str(plan_id) and not str(plan_id).startswith("opening:")
    )
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("required Plan object placements must be non-empty and unique")

    resolved: list[dict[str, Any]] = []
    seen_plan_ids: set[str] = set()
    for detection_id in requested:
        detected_item = detected_by_id.get(detection_id)
        binding = picker_by_detection.get(detection_id)
        if detected_item is None or binding is None:
            raise ValueError(f"selected detection lacks approved semantic binding: {detection_id}")
        plan_id = str(binding.get("plan_binding_id", ""))
        if not binding.get("required") or not plan_id or plan_id.startswith("opening:"):
            raise ValueError(f"selected detection is not a required Plan object placement: {detection_id}")
        if plan_id in seen_plan_ids:
            raise ValueError(f"duplicate Plan instance binding: {plan_id}")
        seen_plan_ids.add(plan_id)
        entry = dict(detected_item)
        entry.update({
            "detection_object_id": detection_id,
            "object_id": plan_id,
            "plan_instance_id": plan_id,
            "manifest_id": str(binding.get("manifest_id", "")),
            "semantic_concept": str(binding.get("semantic_concept", "")),
            "identity_authority": "approved_plan_instance_id",
            "observation_authority": False,
        })
        resolved.append(entry)

    if set(seen_plan_ids) != set(expected) or len(resolved) != len(expected):
        raise ValueError("selected objects must equal the required Plan object-placement set")
    resolved.sort(key=lambda item: expected.index(str(item["plan_instance_id"])))
    return resolved, expected


def build_plan_bound_selected_manifest(
    detected: Mapping[str, Any], picker: Mapping[str, Any], selected_ids: Iterable[Any], *,
    plan_revision: int, approval_revision: int, approval_evidence_sha256: str,
) -> dict[str, Any]:
    """Build strict Plan-keyed selected-object authority for Object Canon."""
    if int(plan_revision) <= 0 or int(plan_revision) != int(picker.get("plan_revision", 0)):
        raise ValueError("selected manifest targets a stale Plan revision")
    if int(approval_revision) <= 0:
        raise ValueError("selected manifest requires a completed blockout approval")
    if len(str(approval_evidence_sha256)) != 64:
        raise ValueError("selected manifest requires blockout approval evidence hash")
    if str(detected.get("canon_sha256", "")) != str(picker.get("canon_sha256", "")):
        raise ValueError("object-picker Canon hash does not match detected inventory")
    if str(detected.get("document_sha256", "")) != str(picker.get("detected_objects_sha256", "")):
        raise ValueError("object-picker detection hash does not match detected inventory")

    selected, expected = resolve_plan_selected_objects(detected, picker, selected_ids)
    manifest: dict[str, Any] = {
        "schema_version": PLAN_SELECTED_SCHEMA,
        "canon_sha256": str(detected["canon_sha256"]),
        "detected_objects_sha256": str(detected["document_sha256"]),
        "object_picker_sha256": str(picker["document_sha256"]),
        "metric_plan_sha256": str(picker["metric_plan_sha256"]),
        "camera_sha256": str(picker["camera_sha256"]),
        "blockout_visibility_sha256": str(picker["blockout_visibility_sha256"]),
        "blockout_approval_evidence_sha256": str(approval_evidence_sha256),
        "plan_revision": int(plan_revision),
        "approval_revision": int(approval_revision),
        "identity_authority": "approved_plan_instance_id",
        "detection_role": "bounded_segmentation_observation_only",
        "fuzzy_matching_used": False,
        "list_index_identity_used": False,
        "architectural_selection_policy": (
            "exclude opening:* bindings; include every required Plan object_placement, "
            "including the built-in counter"
        ),
        "selected_plan_instance_ids": list(expected),
        "objects": selected,
        "object_count": len(selected),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def load_selected_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = manifest.pop("manifest_sha256", "")
    schema = manifest.get("schema_version")
    if schema not in {SELECTED_SCHEMA, PLAN_SELECTED_SCHEMA} or expected != _digest(manifest):
        raise ValueError("selected-object manifest schema or hash is invalid")
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects or manifest.get("object_count") != len(objects):
        raise ValueError("selected-object manifest must contain selected objects")
    if schema == PLAN_SELECTED_SCHEMA:
        plan_ids = [str(item.get("plan_instance_id", "")) for item in objects]
        if any(not value for value in plan_ids) or len(plan_ids) != len(set(plan_ids)):
            raise ValueError("Plan-bound selected identities must be non-empty and unique")
        if plan_ids != [str(value) for value in manifest.get("selected_plan_instance_ids", [])]:
            raise ValueError("selected Plan identity order or set drifted")
        if manifest.get("identity_authority") != "approved_plan_instance_id":
            raise ValueError("selected manifest identity authority is invalid")
    manifest["manifest_sha256"] = expected
    return manifest
