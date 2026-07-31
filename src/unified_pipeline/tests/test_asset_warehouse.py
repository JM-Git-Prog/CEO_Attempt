"""Tests for the unified post-generation Asset Warehouse adapter.

Validates: Requirements 26.1-26.6
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.unified_pipeline.asset_warehouse import (
    UnifiedAssetWarehouse,
    WarehouseCatalogError,
    WarehouseCatalogMetadata,
)
from src.unified_pipeline.models import GameOverlay, MeshApproval, ObjectCanon, RealOverlay


OBJECT_ID = "2b0f302b-7f95-44c0-a9c5-788729621f7f"


def _inputs(tmp_path: Path):
    canon_path = tmp_path / "chair.png"
    canon_path.write_bytes(b"approved object canon pixels")
    mesh_path = tmp_path / "chair.glb"
    mesh_path.write_bytes(b"glTF approved generated mesh")
    canon = ObjectCanon(
        object_id=OBJECT_ID,
        object_name="wooden chair",
        image_path=str(canon_path),
        mask_coverage=0.42,
        approved=True,
        provenance="raw_segmentation",
    )
    mesh = MeshApproval(
        object_id=OBJECT_ID,
        mesh_path=str(mesh_path),
        generation_method="hunyuan3d_v2.1",
        face_count=1200,
        vertex_count=650,
        approved=True,
    )
    metadata = WarehouseCatalogMetadata(
        semantic_label="wooden chair",
        category="props",
        era="mid-century modern",
        condition="worn",
        material_type="wood",
        dimensions_m=(0.45, 0.85, 0.45),
        weight_estimate_kg=4.5,
        has_pbr_textures=True,
        mask_id="obj_04",
        source_prompt="a warm kitchen with two wooden chairs",
        generation_seed=8128,
        workflow_parameters={"steps": 50, "cfg": 7.0, "octree_resolution": 384},
        approval_timestamp="2026-08-01T12:00:00Z",
        created_at="2026-08-01T12:01:00Z",
    )
    return canon, mesh, metadata


def test_catalogs_approved_unified_asset_with_complete_registry(tmp_path: Path) -> None:
    canon, mesh, metadata = _inputs(tmp_path)
    game = GameOverlay(
        rules="Inspect the room",
        scoring="one point per clue",
        win_condition="find all clues",
        object_role_bindings={OBJECT_ID: "clue"},
        theme="Kitchen Mystery",
        mechanics="inspection",
    )
    real = RealOverlay(
        tool_bindings={
            OBJECT_ID: {
                "tool_type": "documents",
                "surface_binding": "seat",
                "read_only": True,
            }
        },
        read_only=True,
    )
    warehouse = UnifiedAssetWarehouse(tmp_path / "assets")

    saved = warehouse.catalog_asset(
        canon,
        mesh,
        session_id="sess-abcdef",
        metadata=metadata,
        game_overlay=game,
        real_overlay=real,
    )

    assert saved == tmp_path / "assets" / "props" / "wooden-chair_sess-a_obj_04.glb"
    assert saved.read_bytes() == Path(mesh.mesh_path).read_bytes()
    registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))
    assert registry["object_id"] == OBJECT_ID
    assert registry["name"] == "wooden chair"
    assert registry["dimensions_m"] == [0.45, 0.85, 0.45]
    assert registry["game_properties"]["role"] == "clue"
    assert registry["real_bindings"]["tool_type"] == "documents"
    assert registry["source_photo_hash"] == hashlib.sha256(
        Path(canon.image_path).read_bytes()
    ).hexdigest()
    assert registry["asset_card"] == {
        "approval_timestamp": "2026-08-01T12:00:00Z",
        "generation_seed": 8128,
        "object_canon_reference": {
            "image_path": canon.image_path,
            "object_id": OBJECT_ID,
            "provenance": "raw_segmentation",
            "sha256": registry["source_photo_hash"],
        },
        "source_prompt": "a warm kitchen with two wooden chairs",
        "tri_count": 1200,
        "workflow_parameters": {"cfg": 7.0, "octree_resolution": 384, "steps": 50},
    }


def test_cataloging_is_append_only_even_with_orphaned_sidecar(tmp_path: Path) -> None:
    canon, mesh, metadata = _inputs(tmp_path)
    warehouse = UnifiedAssetWarehouse(tmp_path / "assets")
    warehouse.ensure_structure()
    orphan = warehouse.base_dir / "props" / "wooden-chair_sess-a_obj_04.json"
    orphan.write_text("original registry", encoding="utf-8")

    first = warehouse.catalog_asset(
        canon, mesh, session_id="sess-abcdef", metadata=metadata
    )
    second = warehouse.catalog_asset(
        canon, mesh, session_id="sess-abcdef", metadata=metadata
    )

    assert first.name == "wooden-chair_sess-a_obj_04_1.glb"
    assert second.name == "wooden-chair_sess-a_obj_04_2.glb"
    assert orphan.read_text(encoding="utf-8") == "original registry"
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    ("canon_change", "mesh_change", "message"),
    [
        ({"approved": False}, {}, "ObjectCanon must be approved"),
        ({}, {"approved": False}, "mesh must be approved"),
        ({}, {"is_placeholder": True, "generation_method": "placeholder"}, "placeholder"),
        ({}, {"object_id": "different-id"}, "stable UUIDs do not match"),
    ],
)
def test_rejects_assets_that_are_not_approved_generated_identity_matches(
    tmp_path: Path,
    canon_change: dict[str, object],
    mesh_change: dict[str, object],
    message: str,
) -> None:
    canon, mesh, metadata = _inputs(tmp_path)
    warehouse = UnifiedAssetWarehouse(tmp_path / "assets")

    with pytest.raises(WarehouseCatalogError, match=message):
        warehouse.catalog_asset(
            replace(canon, **canon_change),
            replace(mesh, **mesh_change),
            session_id="sess-abcdef",
            metadata=metadata,
        )

    assert not warehouse.base_dir.exists()


def test_unbound_overlays_write_empty_optional_fields(tmp_path: Path) -> None:
    canon, mesh, metadata = _inputs(tmp_path)
    warehouse = UnifiedAssetWarehouse(tmp_path / "assets")

    saved = warehouse.catalog_asset(
        canon,
        replace(mesh, generation_method="trellis2"),
        session_id="sess-abcdef",
        metadata=metadata,
        game_overlay=GameOverlay(object_role_bindings={"other-id": "target"}),
        real_overlay=RealOverlay(tool_bindings={"other-id": {"tool_type": "inbox"}}),
    )

    registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))
    assert registry["generation_method"] == "trellis2"
    assert registry["game_properties"] == {}
    assert registry["real_bindings"] == {}
