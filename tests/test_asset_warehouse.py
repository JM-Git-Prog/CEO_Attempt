"""Unit tests for the AssetWarehouse component.

Tests cover:
- Directory structure creation (ensure_structure)
- Filename generation with slugification
- Asset saving (GLB copy + JSON registry)
- Append-only behavior (collision resolution)
- Edge cases (empty labels, special characters, long session IDs)

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.3
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.photo_pipeline.asset_warehouse import AssetWarehouse
from src.photo_pipeline.models_v14 import AssetRegistryEntry


@pytest.fixture
def tmp_warehouse(tmp_path: Path) -> AssetWarehouse:
    """Create an AssetWarehouse pointing at a temporary directory."""
    return AssetWarehouse(base_dir=tmp_path / "assets")


@pytest.fixture
def sample_glb(tmp_path: Path) -> Path:
    """Create a dummy GLB file for testing."""
    glb = tmp_path / "source.glb"
    glb.write_bytes(b"\x00" * 128)
    return glb


@pytest.fixture
def sample_registry() -> AssetRegistryEntry:
    """Create a sample AssetRegistryEntry for testing."""
    return AssetRegistryEntry(
        name="wooden-dining-chair_a1b2c3_obj_04",
        semantic_label="wooden dining chair",
        category="props",
        era="mid-century modern",
        condition="worn",
        working_status="not-applicable",
        material_type="wood",
        dimensions_m=(0.45, 0.85, 0.45),
        weight_estimate_kg=4.5,
        generation_method="hunyuan3d_v2.1",
        source_photo_hash="a1b2c3d4e5f6abcdef1234567890abcdef1234567890abcdef1234567890abcd",
        source_session_id="sess_abc123def456",
        face_count=45000,
        vertex_count=23000,
        has_pbr_textures=True,
        created_at="2025-01-15T10:30:00Z",
    )


class TestEnsureStructure:
    """Tests for ensure_structure method."""

    def test_creates_base_and_all_categories(self, tmp_warehouse: AssetWarehouse) -> None:
        tmp_warehouse.ensure_structure()

        assert tmp_warehouse.base_dir.exists()
        for category in AssetWarehouse.CATEGORIES:
            assert (tmp_warehouse.base_dir / category).exists()

    def test_idempotent(self, tmp_warehouse: AssetWarehouse) -> None:
        tmp_warehouse.ensure_structure()
        tmp_warehouse.ensure_structure()  # should not raise

        assert tmp_warehouse.base_dir.exists()

    def test_five_categories(self, tmp_warehouse: AssetWarehouse) -> None:
        tmp_warehouse.ensure_structure()
        dirs = [d.name for d in tmp_warehouse.base_dir.iterdir() if d.is_dir()]
        assert set(dirs) == {"props", "architecture", "foliage", "hard-surface", "set-dressing"}


class TestGenerateFilename:
    """Tests for _generate_filename method."""

    def test_basic_filename(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("wooden dining chair", "sess_abc123", "obj_04")
        assert result == "wooden-dining-chair_sess_a_obj_04.glb"

    def test_special_characters_stripped(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("chair (large!) @home", "session1", "m01")
        assert result == "chair-large-home_sessio_m01.glb"

    def test_multiple_spaces(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("big   wooden   table", "abcdef", "x")
        assert result == "big-wooden-table_abcdef_x.glb"

    def test_short_session_id(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("lamp", "abc", "01")
        assert result == "lamp_abc_01.glb"

    def test_empty_label_fallback(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("!!!!", "sess01", "m1")
        assert result == "asset_sess01_m1.glb"

    def test_session_truncated_to_6(self, tmp_warehouse: AssetWarehouse) -> None:
        result = tmp_warehouse._generate_filename("table", "abcdefghijklmnop", "obj1")
        assert result == "table_abcdef_obj1.glb"


class TestSaveAsset:
    """Tests for save_asset method."""

    def test_copies_glb_to_correct_category(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        dest = tmp_warehouse.save_asset(sample_glb, sample_registry)

        assert dest.exists()
        assert dest.parent.name == "props"
        assert dest.suffix == ".glb"
        assert dest.read_bytes() == sample_glb.read_bytes()

    def test_writes_json_registry_alongside(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        dest = tmp_warehouse.save_asset(sample_glb, sample_registry)
        json_path = dest.with_suffix(".json")

        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["semantic_label"] == "wooden dining chair"
        assert data["category"] == "props"
        assert data["generation_method"] == "hunyuan3d_v2.1"

    def test_raises_on_missing_glb(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        fake_path = Path("/nonexistent/file.glb")
        with pytest.raises(FileNotFoundError):
            tmp_warehouse.save_asset(fake_path, sample_registry)

    def test_creates_structure_on_first_save(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        # Don't call ensure_structure explicitly
        assert not tmp_warehouse.base_dir.exists()
        tmp_warehouse.save_asset(sample_glb, sample_registry)
        assert tmp_warehouse.base_dir.exists()


class TestAppendOnlyBehavior:
    """Tests for append-only collision resolution."""

    def test_no_overwrite_on_collision(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        dest1 = tmp_warehouse.save_asset(sample_glb, sample_registry)
        dest2 = tmp_warehouse.save_asset(sample_glb, sample_registry)

        # Both files exist, different paths
        assert dest1.exists()
        assert dest2.exists()
        assert dest1 != dest2

    def test_collision_appends_numeric_suffix(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        dest1 = tmp_warehouse.save_asset(sample_glb, sample_registry)
        dest2 = tmp_warehouse.save_asset(sample_glb, sample_registry)
        dest3 = tmp_warehouse.save_asset(sample_glb, sample_registry)

        # Second and third get numeric suffixes
        assert "_1.glb" in dest2.name
        assert "_2.glb" in dest3.name

    def test_json_also_created_for_collision(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        tmp_warehouse.save_asset(sample_glb, sample_registry)
        dest2 = tmp_warehouse.save_asset(sample_glb, sample_registry)

        json_path = dest2.with_suffix(".json")
        assert json_path.exists()

    def test_file_count_monotonically_increases(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
        sample_registry: AssetRegistryEntry,
    ) -> None:
        tmp_warehouse.ensure_structure()
        category_dir = tmp_warehouse.base_dir / "props"

        counts = []
        for _ in range(3):
            tmp_warehouse.save_asset(sample_glb, sample_registry)
            file_count = len(list(category_dir.iterdir()))
            counts.append(file_count)

        # Each save adds 2 files (GLB + JSON), count should strictly increase
        assert counts[0] < counts[1] < counts[2]


class TestCategoryDirectories:
    """Tests for category-based saving."""

    def test_architecture_category(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
    ) -> None:
        registry = AssetRegistryEntry(
            name="door-frame_a1b2c3_obj_01",
            semantic_label="wooden door frame",
            category="architecture",
            era="victorian",
            condition="worn",
            working_status="working",
            material_type="wood",
            dimensions_m=(0.9, 2.1, 0.15),
            weight_estimate_kg=25.0,
            generation_method="hunyuan3d_v2.1",
            source_photo_hash="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            source_session_id="sess_xyz789",
            face_count=12000,
            vertex_count=6000,
            has_pbr_textures=True,
            created_at="2025-01-15T11:00:00Z",
        )
        dest = tmp_warehouse.save_asset(sample_glb, registry)
        assert dest.parent.name == "architecture"

    def test_foliage_category(
        self,
        tmp_warehouse: AssetWarehouse,
        sample_glb: Path,
    ) -> None:
        registry = AssetRegistryEntry(
            name="potted-plant_a1b2c3_obj_02",
            semantic_label="potted fern plant",
            category="foliage",
            era="contemporary",
            condition="new",
            working_status="not-applicable",
            material_type="plastic",
            dimensions_m=(0.3, 0.5, 0.3),
            weight_estimate_kg=2.0,
            generation_method="trellis2",
            source_photo_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            source_session_id="sess_plant1",
            face_count=8000,
            vertex_count=4000,
            has_pbr_textures=False,
            created_at="2025-01-15T12:00:00Z",
        )
        dest = tmp_warehouse.save_asset(sample_glb, registry)
        assert dest.parent.name == "foliage"


class TestDefaultBaseDir:
    """Tests for default base directory behavior."""

    def test_default_base_dir(self) -> None:
        warehouse = AssetWarehouse()
        assert warehouse.base_dir == Path("assets")

    def test_custom_base_dir(self, tmp_path: Path) -> None:
        custom = tmp_path / "my_assets"
        warehouse = AssetWarehouse(base_dir=custom)
        assert warehouse.base_dir == custom
