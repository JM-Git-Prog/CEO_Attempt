"""Focused strict-real normalization, classification, and Bullet tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from src.unified_pipeline.strict_real_assets import (
    classify_selected_body,
    normalize_generated_glb,
    settle_classified_bodies,
)


OBJECT_ID = "db2790ad-331f-5411-9347-1815acb004bd"


def test_normalize_generated_glb_has_unit_bounds_and_source_provenance(tmp_path: Path):
    source = tmp_path / "source.glb"
    mesh = trimesh.creation.box(extents=(2.0, 4.0, 6.0))
    mesh.apply_translation((3.0, 5.0, -2.0))
    mesh.export(source, file_type="glb")

    evidence = normalize_generated_glb(source, tmp_path / "normalized.glb")

    assert evidence["source_extents_m"] == pytest.approx([2.0, 4.0, 6.0])
    assert evidence["normalized_bounds_min"] == pytest.approx([-0.5, 0.0, -0.5])
    assert evidence["normalized_bounds_max"] == pytest.approx([0.5, 1.0, 0.5])
    assert evidence["origin_policy"] == "local-bounds-bottom-center"
    assert evidence["normalization_count"] == 1
    assert evidence["source_sha256"] != evidence["normalized_sha256"]


def test_classification_reuses_category_material_and_mass_policy():
    dynamic = classify_selected_body(
        plan_revision=1, object_id=OBJECT_ID, category="utensil",
        dimensions=(0.1, 0.1, 0.1), material="plastic",
    )
    static = classify_selected_body(
        plan_revision=1, object_id=OBJECT_ID, category="architecture",
        dimensions=(0.1, 0.1, 0.1), material="plastic",
    )

    assert dynamic["body_mode"] == "DYNAMIC"
    assert dynamic["mass_kg"] > 0.0
    assert static["body_mode"] == "STATIC"
    assert static["override_reason"] == "architectural_function"


def test_dynamic_body_uses_pybullet_without_fallback():
    body = {
        "object_id": OBJECT_ID,
        "body_mode": "DYNAMIC",
        "mass_kg": 1.0,
        "friction": 0.5,
        "restitution": 0.0,
        "collision_dimensions_m": [0.2, 0.2, 0.2],
    }
    placement = {
        "id": OBJECT_ID, "x": 1.0, "y": 1.0, "elevation": 0.8,
        "width": 0.2, "height": 0.2, "depth": 0.2,
    }

    result = settle_classified_bodies(
        bodies=[body], placements={OBJECT_ID: placement},
        room_dimensions=(2.0, 2.0, 2.5),
    )

    assert result["engine"] == "pybullet-direct"
    assert 0 < result["iterations"] <= 500
    transform = result["transforms"][0]
    assert transform["body_mode"] == "DYNAMIC"
    assert transform["position"][1] == pytest.approx(0.0, abs=0.02)
    assert transform["settle_method"] == "PyBullet DIRECT upright-box settle"
