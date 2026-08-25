"""Focused Plan-bound selected-object authority tests."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from hypothesis import given, strategies as st

from src.unified_pipeline.object_manifest import (
    PLAN_SELECTED_SCHEMA,
    build_plan_bound_selected_manifest,
    load_selected_manifest,
    resolve_plan_selected_objects,
)

PLAN_IDS = ("table", "chair-1", "chair-2", "counter", "coffee")
DETECTION_IDS = ("d-table", "d-chair-left", "d-chair-right", "d-counter", "d-coffee")


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _documents() -> tuple[dict, dict]:
    bindings = [
        ("d-table", "table", "table", "furniture"),
        ("d-chair-left", "chair-1", "chair", "furniture"),
        ("d-chair-right", "chair-2", "chair", "furniture"),
        ("d-counter", "counter", "counter", "furniture"),
        ("d-coffee", "coffee", "coffee_maker", "appliance"),
        ("d-window", "opening:1", "window", "architectural"),
    ]
    objects = [
        {
            "id": index,
            "object_id": detection_id,
            "detection_index": index,
            "name": concept,
            "bbox": [index * 10, 0, index * 10 + 8, 8],
            "material": "wood",
            "category": category,
            "size_estimate": "medium",
        }
        for index, (detection_id, _plan_id, concept, category) in enumerate(bindings)
    ]
    detected = {
        "schema_version": "detected-objects/v1",
        "canon_sha256": "c" * 64,
        "document_sha256": "d" * 64,
        "objects": objects,
        "object_count": len(objects),
    }
    picker = {
        "schema_version": "candidate-object-picker/v1",
        "canon_sha256": "c" * 64,
        "detected_objects_sha256": "d" * 64,
        "metric_plan_sha256": "p" * 64,
        "camera_sha256": "a" * 64,
        "blockout_visibility_sha256": "v" * 64,
        "plan_revision": 2,
        "fuzzy_matching_used": False,
        "objects": [
            {
                **item,
                "required": True,
                "plan_binding_id": plan_id,
                "manifest_id": plan_id.split("-")[0],
                "semantic_concept": concept,
            }
            for item, (_detection_id, plan_id, concept, _category) in zip(objects, bindings)
        ],
        "required_bindings": [
            {"plan_binding_ids": ["table"]},
            {"plan_binding_ids": ["chair-1", "chair-2"]},
            {"plan_binding_ids": ["opening:1"]},
            {"plan_binding_ids": ["counter"]},
            {"plan_binding_ids": ["coffee"]},
        ],
    }
    picker["document_sha256"] = _digest(picker)
    return detected, picker


def test_plan_bound_manifest_excludes_opening_and_keeps_counter(tmp_path) -> None:
    detected, picker = _documents()
    manifest = build_plan_bound_selected_manifest(
        detected,
        picker,
        DETECTION_IDS,
        plan_revision=2,
        approval_revision=1,
        approval_evidence_sha256="e" * 64,
    )
    assert manifest["schema_version"] == PLAN_SELECTED_SCHEMA
    assert tuple(manifest["selected_plan_instance_ids"]) == PLAN_IDS
    assert {item["detection_object_id"] for item in manifest["objects"]} == set(DETECTION_IDS)
    assert "opening:1" not in manifest["selected_plan_instance_ids"]
    assert "counter" in manifest["selected_plan_instance_ids"]
    assert all(item["identity_authority"] == "approved_plan_instance_id" for item in manifest["objects"])

    path = tmp_path / "selected_objects.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert load_selected_manifest(path) == manifest


def test_window_or_duplicate_chair_cannot_substitute_for_plan_instance() -> None:
    detected, picker = _documents()
    with pytest.raises(ValueError, match="not a required Plan object placement"):
        resolve_plan_selected_objects(
            detected, picker, (*DETECTION_IDS[:-1], "d-window")
        )

    corrupted = deepcopy(picker)
    corrupted["objects"][2]["plan_binding_id"] = "chair-1"
    corrupted.pop("document_sha256")
    corrupted["document_sha256"] = _digest(corrupted)
    with pytest.raises(ValueError, match="duplicate Plan instance binding"):
        resolve_plan_selected_objects(detected, corrupted, DETECTION_IDS)


@given(st.permutations(DETECTION_IDS))
def test_selection_order_never_changes_plan_identity_authority(permutation) -> None:
    """**Validates: Requirements 9.2**"""
    detected, picker = _documents()
    selected, expected = resolve_plan_selected_objects(detected, picker, permutation)
    assert expected == PLAN_IDS
    assert tuple(item["plan_instance_id"] for item in selected) == PLAN_IDS
    assert {item["detection_object_id"] for item in selected} == set(DETECTION_IDS)
