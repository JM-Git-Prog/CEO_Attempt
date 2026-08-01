"""Tests for the unified pipeline warehouse adapter.

Validates:
- Cataloging an approved mesh writes GLB + JSON with all extended fields
- game_properties and real_bindings are preserved
- Pre-generation lookup attempts are rejected (always-fresh rule)
- Append-only: duplicate calls produce new unique files, never overwrite

Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.unified_pipeline.warehouse_adapter import (
    PreGenerationLookupError,
    UnifiedAssetEntry,
    UnifiedWarehouseAdapter,
    WarehouseAdapterError,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_glb(tmp_path: Path, name: str = "chair.glb") -> Path:
    """Create a fake GLB file for testing."""
    glb = tmp_path / name
    glb.write_bytes(b"\x67\x6c\x54\x46" + b"\x00" * 100)  # glTF magic + padding
    return glb


def _make_entry(**overrides: object) -> UnifiedAssetEntry:
    """Create a valid UnifiedAssetEntry with sensible defaults."""
    defaults = dict(
        name="wooden_chair",
        semantic_label="wooden dining chair",
        category="props",
        era="mid-century modern",
        condition="worn",
        material_type="wood",
        dimensions_m=(0.45, 0.85, 0.45),
        weight_estimate_kg=4.5,
        generation_method="hunyuan3d_v2.1",
        source_session_id="sess-abcdef1234",
        face_count=1200,
        vertex_count=650,
        has_pbr_textures=True,
        game_properties={"role": "clue", "scoring": "1 point"},
        real_bindings={"tool_type": "documents", "surface_binding": "seat"},
        source_prompt="a warm kitchen with two wooden chairs",
        object_canon_ref="canon/chair_001.png",
        generation_seed=8128,
        workflow_params={"steps": 50, "cfg": 7.0, "octree_resolution": 384},
        approval_timestamp="2026-08-01T12:00:00Z",
        created_at="2026-08-01T12:01:00Z",
    )
    defaults.update(overrides)
    return UnifiedAssetEntry(**defaults)


# ---------------------------------------------------------------------------
# Test: Cataloging writes GLB + JSON with all extended fields
# ---------------------------------------------------------------------------


class TestCatalogApprovedMesh:
    """Cataloging an approved mesh writes both GLB and JSON with full metadata."""

    def test_writes_glb_and_json_to_correct_category(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        assert saved.exists()
        assert saved.parent.name == "props"
        assert saved.suffix == ".glb"
        assert saved.with_suffix(".json").exists()

    def test_json_contains_all_extended_fields(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")
        registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))

        # Core fields
        assert registry["name"] == "wooden_chair"
        assert registry["semantic_label"] == "wooden dining chair"
        assert registry["category"] == "props"
        assert registry["era"] == "mid-century modern"
        assert registry["condition"] == "worn"
        assert registry["material_type"] == "wood"
        assert registry["dimensions_m"] == [0.45, 0.85, 0.45]
        assert registry["weight_estimate_kg"] == 4.5
        assert registry["generation_method"] == "hunyuan3d_v2.1"
        assert registry["source_session_id"] == "sess-abcdef1234"
        assert registry["face_count"] == 1200
        assert registry["vertex_count"] == 650
        assert registry["has_pbr_textures"] is True
        assert registry["created_at"] == "2026-08-01T12:01:00Z"

        # Extended fields
        assert registry["game_properties"] == {"role": "clue", "scoring": "1 point"}
        assert registry["real_bindings"] == {"tool_type": "documents", "surface_binding": "seat"}
        assert registry["source_prompt"] == "a warm kitchen with two wooden chairs"
        assert registry["object_canon_ref"] == "canon/chair_001.png"
        assert registry["generation_seed"] == 8128
        assert registry["workflow_params"] == {"steps": 50, "cfg": 7.0, "octree_resolution": 384}
        assert registry["approval_timestamp"] == "2026-08-01T12:00:00Z"

        # Asset card
        assert "asset_card" in registry
        card = registry["asset_card"]
        assert card["source_prompt"] == "a warm kitchen with two wooden chairs"
        assert card["object_canon_ref"] == "canon/chair_001.png"
        assert card["generation_seed"] == 8128
        assert card["workflow_params"] == {"steps": 50, "cfg": 7.0, "octree_resolution": 384}
        assert card["approval_timestamp"] == "2026-08-01T12:00:00Z"
        assert card["tri_count"] == 1200

    def test_glb_content_matches_source(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        original_content = glb.read_bytes()
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        assert saved.read_bytes() == original_content

    def test_all_five_categories_are_valid(self, tmp_path: Path) -> None:
        categories = ("props", "architecture", "foliage", "hard-surface", "set-dressing")
        for cat in categories:
            glb = _make_glb(tmp_path, name=f"{cat}_item.glb")
            entry = _make_entry(category=cat, name=f"{cat}_item")
            adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

            saved = adapter.catalog_approved_mesh(glb, entry, mask_id="m01")
            assert saved.parent.name == cat

    def test_raises_on_missing_glb(self, tmp_path: Path) -> None:
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")
        missing = tmp_path / "nonexistent.glb"

        with pytest.raises(FileNotFoundError, match="Source GLB file not found"):
            adapter.catalog_approved_mesh(missing, entry, mask_id="obj_04")

    def test_raises_on_non_glb_file(self, tmp_path: Path) -> None:
        fbx = tmp_path / "model.fbx"
        fbx.write_bytes(b"not a glb")
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        with pytest.raises(WarehouseAdapterError, match="Only GLB files"):
            adapter.catalog_approved_mesh(fbx, entry, mask_id="obj_04")


# ---------------------------------------------------------------------------
# Test: game_properties and real_bindings are preserved
# ---------------------------------------------------------------------------


class TestOverlayPreservation:
    """game_properties and real_bindings round-trip correctly."""

    def test_game_properties_preserved_from_entry(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        game_props = {
            "role": "target",
            "scoring": "10 points on hit",
            "mechanics": "throw",
        }
        entry = _make_entry(game_properties=game_props)
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_01")
        registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))

        assert registry["game_properties"] == game_props

    def test_real_bindings_preserved_from_entry(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        real_binds = {
            "tool_type": "calendar",
            "surface_binding": "desktop",
            "read_only": True,
        }
        entry = _make_entry(real_bindings=real_binds)
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_02")
        registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))

        assert registry["real_bindings"] == real_binds

    def test_overlay_data_params_override_entry(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry(
            game_properties={"role": "original"},
            real_bindings={"tool_type": "original"},
        )
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        override_game = {"role": "overridden", "extra": "value"}
        override_real = {"tool_type": "overridden", "extra": "binding"}

        saved = adapter.catalog_approved_mesh(
            glb,
            entry,
            mask_id="obj_03",
            game_overlay_data=override_game,
            real_overlay_data=override_real,
        )
        registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))

        assert registry["game_properties"] == override_game
        assert registry["real_bindings"] == override_real

    def test_none_overlays_written_as_null(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry(game_properties=None, real_bindings=None)
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_05")
        registry = json.loads(saved.with_suffix(".json").read_text(encoding="utf-8"))

        assert registry["game_properties"] is None
        assert registry["real_bindings"] is None


# ---------------------------------------------------------------------------
# Test: Rejects pre-generation lookup (always-fresh rule)
# ---------------------------------------------------------------------------


class TestAlwaysFreshRule:
    """The adapter must never allow pre-generation lookups."""

    def test_lookup_asset_raises(self, tmp_path: Path) -> None:
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        with pytest.raises(PreGenerationLookupError, match="never consulted before generation"):
            adapter.lookup_asset("wooden chair")

    def test_find_existing_raises(self, tmp_path: Path) -> None:
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        with pytest.raises(PreGenerationLookupError, match="never consulted before generation"):
            adapter.find_existing(category="props", label="chair")

    def test_lookup_with_kwargs_raises(self, tmp_path: Path) -> None:
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        with pytest.raises(PreGenerationLookupError):
            adapter.lookup_asset(name="table", category="props", session="abc")


# ---------------------------------------------------------------------------
# Test: Append-only — duplicate calls produce new unique files
# ---------------------------------------------------------------------------


class TestAppendOnly:
    """Duplicate cataloging calls must produce unique files, never overwrite."""

    def test_duplicate_calls_produce_unique_files(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        first = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")
        second = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")
        third = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        # All three should exist and have different names
        assert first.exists()
        assert second.exists()
        assert third.exists()
        assert first != second
        assert second != third
        assert first != third

    def test_originals_are_never_overwritten(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        first = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")
        first_content = first.read_bytes()
        first_json = first.with_suffix(".json").read_text(encoding="utf-8")

        # Catalog again — should not touch first
        _second = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        assert first.read_bytes() == first_content
        assert first.with_suffix(".json").read_text(encoding="utf-8") == first_json

    def test_existing_json_sidecar_not_overwritten(self, tmp_path: Path) -> None:
        """If only a JSON sidecar exists (orphan), the adapter skips it."""
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")
        adapter._warehouse.ensure_structure()

        # Pre-create an orphan JSON sidecar
        orphan = adapter.base_dir / "props" / "wooden-dining-chair_sess-a_obj_04.json"
        orphan.write_text("original orphan data", encoding="utf-8")

        glb = _make_glb(tmp_path)
        saved = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        # The orphan must remain untouched
        assert orphan.read_text(encoding="utf-8") == "original orphan data"
        # The saved file must use a suffixed name
        assert "_1" in saved.stem

    def test_each_catalog_call_creates_distinct_json(self, tmp_path: Path) -> None:
        glb = _make_glb(tmp_path)
        entry = _make_entry()
        adapter = UnifiedWarehouseAdapter(base_dir=tmp_path / "assets")

        first = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")
        second = adapter.catalog_approved_mesh(glb, entry, mask_id="obj_04")

        first_json = json.loads(first.with_suffix(".json").read_text(encoding="utf-8"))
        second_json = json.loads(second.with_suffix(".json").read_text(encoding="utf-8"))

        # Both should have valid complete registries
        assert first_json["name"] == second_json["name"] == "wooden_chair"
        assert first_json["category"] == second_json["category"] == "props"
        # But they are stored at different paths
        assert first.with_suffix(".json") != second.with_suffix(".json")


# ---------------------------------------------------------------------------
# Test: Entry validation
# ---------------------------------------------------------------------------


class TestEntryValidation:
    """UnifiedAssetEntry validates required fields on construction."""

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="name must not be empty"):
            _make_entry(name="")

    def test_rejects_invalid_category(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="category"):
            _make_entry(category="vehicles")

    def test_rejects_invalid_condition(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="condition"):
            _make_entry(condition="destroyed")

    def test_rejects_invalid_material(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="material_type"):
            _make_entry(material_type="unobtanium")

    def test_rejects_negative_weight(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="weight_estimate_kg"):
            _make_entry(weight_estimate_kg=-1.0)

    def test_rejects_invalid_generation_method(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="generation_method"):
            _make_entry(generation_method="blender_manual")

    def test_rejects_zero_face_count(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="face_count"):
            _make_entry(face_count=0)

    def test_rejects_zero_vertex_count(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="vertex_count"):
            _make_entry(vertex_count=0)

    def test_rejects_empty_session_id(self) -> None:
        with pytest.raises(WarehouseAdapterError, match="source_session_id"):
            _make_entry(source_session_id="")
