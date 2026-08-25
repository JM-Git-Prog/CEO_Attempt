"""Unit tests for UnifiedPlaceholderGenerator.

Tests the placeholder mesh generator wrapper that adapts the V14
placeholder_generator to the unified pipeline's ObjectCanon → MeshApproval
interface.

Requirements: 10.5, 11.5
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.unified_pipeline.mesh_generators import (
    UnifiedPlaceholderGenerator,
    prepare_generator_input,
)
from src.unified_pipeline.models import MeshApproval, ObjectCanon


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def object_png(tmp_path: Path) -> Path:
    """Create a dummy Object_Canon RGBA image."""
    png_path = tmp_path / "coffee_maker.png"
    img = Image.new("RGBA", (256, 512), (120, 80, 40, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def wide_object_png(tmp_path: Path) -> Path:
    """Create a wide Object_Canon (box shape expected)."""
    png_path = tmp_path / "counter.png"
    img = Image.new("RGBA", (800, 200), (180, 160, 140, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def small_object_png(tmp_path: Path) -> Path:
    """Create a tiny Object_Canon (sphere expected due to small area)."""
    png_path = tmp_path / "knob.png"
    # Very small image → area below SPHERE_AREA_THRESHOLD
    img = Image.new("RGBA", (20, 20), (200, 200, 200, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def object_canon(object_png: Path) -> ObjectCanon:
    """Create an ObjectCanon pointing to the test image."""
    return ObjectCanon(
        object_id="obj-coffee-001",
        object_name="coffee_maker",
        image_path=str(object_png),
        mask_coverage=0.45,
        approved=True,
        provenance="raw_segmentation",
    )


# ---------------------------------------------------------------------------
# Tests: Successful Generation
# ---------------------------------------------------------------------------


class TestUnifiedPlaceholderGeneratorSuccess:
    """Test successful placeholder generation from ObjectCanon."""

    def test_generates_mesh_approval(self, object_canon: ObjectCanon, tmp_path: Path) -> None:
        """generate() returns a valid MeshApproval."""
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(object_canon)

        assert isinstance(result, MeshApproval)
        assert result.object_id == "obj-coffee-001"
        assert result.generation_method == "placeholder"

    def test_is_placeholder_true(self, object_canon: ObjectCanon, tmp_path: Path) -> None:
        """MeshApproval.is_placeholder is always True for placeholders."""
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(object_canon)

        assert result.is_placeholder is True

    def test_auto_approves(self, object_canon: ObjectCanon, tmp_path: Path) -> None:
        """Placeholders auto-approve (no shape approval needed, Req 11.5)."""
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(object_canon)

        assert result.approved is True
        assert result.rejection_reason == ""

    def test_mesh_file_created(self, object_canon: ObjectCanon, tmp_path: Path) -> None:
        """A .glb file is created on disk."""
        output_dir = tmp_path / "output"
        gen = UnifiedPlaceholderGenerator(output_dir=output_dir)
        result = gen.generate(object_canon)

        assert result.mesh_path != ""
        assert Path(result.mesh_path).exists()
        assert Path(result.mesh_path).suffix == ".glb"

    def test_nonzero_face_vertex_counts(self, object_canon: ObjectCanon, tmp_path: Path) -> None:
        """Generated mesh has positive face and vertex counts."""
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(object_canon)

        assert result.face_count > 0
        assert result.vertex_count > 0

    def test_output_dir_none_writes_alongside_image(self, object_canon: ObjectCanon) -> None:
        """When output_dir is None, writes next to the Object_Canon image."""
        gen = UnifiedPlaceholderGenerator(output_dir=None)
        result = gen.generate(object_canon)

        image_dir = Path(object_canon.image_path).parent
        assert Path(result.mesh_path).parent == image_dir

    def test_wide_image_generates_box(self, wide_object_png: Path, tmp_path: Path) -> None:
        """Wide aspect ratio produces a box placeholder."""
        canon = ObjectCanon(
            object_id="obj-counter-001",
            object_name="counter",
            image_path=str(wide_object_png),
            mask_coverage=0.8,
            approved=True,
        )
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(canon)

        # Should succeed regardless of shape
        assert result.approved is True
        assert result.face_count > 0


# ---------------------------------------------------------------------------
# Tests: Error Handling
# ---------------------------------------------------------------------------


class TestUnifiedPlaceholderGeneratorErrors:
    """Test error handling when Object_Canon image is missing or invalid."""

    def test_missing_image_returns_failed_approval(self, tmp_path: Path) -> None:
        """Non-existent image_path → MeshApproval with approved=False."""
        canon = ObjectCanon(
            object_id="obj-missing-001",
            object_name="ghost",
            image_path=str(tmp_path / "nonexistent.png"),
            mask_coverage=0.0,
            approved=True,
        )
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(canon)

        assert result.approved is False
        assert result.is_placeholder is True
        assert "not found" in result.rejection_reason.lower()
        assert result.mesh_path == ""

    def test_missing_image_preserves_object_id(self, tmp_path: Path) -> None:
        """Even on failure, object_id is preserved in the result."""
        canon = ObjectCanon(
            object_id="obj-gone-999",
            object_name="missing_thing",
            image_path=str(tmp_path / "nope.png"),
            mask_coverage=0.0,
            approved=True,
        )
        gen = UnifiedPlaceholderGenerator(output_dir=tmp_path / "output")
        result = gen.generate(canon)

        assert result.object_id == "obj-gone-999"


# ---------------------------------------------------------------------------
# Tests: Approved RGBA preparation for RGB-only mesh encoders
# ---------------------------------------------------------------------------


def _rgba_with_hidden_scene(
    path: Path,
    size: tuple[int, int],
    hidden_rgb: tuple[int, int, int],
    subject_rgb: tuple[int, int, int],
) -> None:
    image = Image.new("RGBA", size, (*hidden_rgb, 0))
    x0, y0 = max(1, size[0] // 4), max(1, size[1] // 4)
    x1, y1 = max(x0 + 1, size[0] * 3 // 4), max(y0 + 1, size[1] * 3 // 4)
    subject = Image.new("RGBA", (x1 - x0, y1 - y0), (*subject_rgb, 255))
    image.paste(subject, (x0, y0))
    image.save(path)


def test_prepare_generator_input_discards_hidden_scene_rgb(tmp_path: Path) -> None:
    source = tmp_path / "approved-object-canon.png"
    _rgba_with_hidden_scene(source, (40, 24), (255, 0, 0), (0, 80, 220))
    source_bytes = source.read_bytes()
    canon = ObjectCanon(
        object_id="approved-table", object_name="table", image_path=str(source),
        mask_coverage=0.25, approved=True, provenance="raw_segmentation",
    )

    prepared, evidence = prepare_generator_input(canon, tmp_path / "mesh-output")

    pixels = np.asarray(Image.open(prepared).convert("RGB"))
    assert source.read_bytes() == source_bytes
    assert pixels.shape[0] == pixels.shape[1]
    assert np.all(pixels[0, 0] == [255, 255, 255])
    assert not np.any(np.all(pixels == [255, 0, 0], axis=2))
    assert np.any(np.all(pixels == [0, 80, 220], axis=2))
    assert evidence["background_policy"] == "approved-alpha-composited-on-white"
    assert evidence["hidden_rgb_discarded"] is True
    assert Path(evidence["prepared_path"]) == prepared.resolve()


@pytest.mark.parametrize(
    ("size", "hidden_rgb", "subject_rgb"),
    [
        ((9, 7), (250, 10, 10), (10, 120, 220)),
        ((17, 31), (4, 200, 40), (220, 70, 15)),
        ((64, 16), (90, 30, 180), (12, 14, 16)),
        ((33, 33), (1, 2, 3), (200, 210, 220)),
    ],
)
def test_prepared_input_property_contains_only_subject_or_white(
    tmp_path: Path,
    size: tuple[int, int],
    hidden_rgb: tuple[int, int, int],
    subject_rgb: tuple[int, int, int],
) -> None:
    """For varied RGBA shapes, transparent scene RGB never reaches the encoder input.

    **Validates: Requirements 9.4, 10.1**
    """
    source = tmp_path / f"object-{size[0]}-{size[1]}.png"
    _rgba_with_hidden_scene(source, size, hidden_rgb, subject_rgb)
    canon = ObjectCanon(
        object_id=f"object-{size[0]}-{size[1]}", object_name="object",
        image_path=str(source), mask_coverage=0.25, approved=True,
        provenance="raw_segmentation",
    )

    prepared, evidence = prepare_generator_input(canon, tmp_path / "mesh-output")
    colors = np.unique(np.asarray(Image.open(prepared).convert("RGB")).reshape(-1, 3), axis=0)

    allowed = {subject_rgb, (255, 255, 255)}
    assert {tuple(int(channel) for channel in color) for color in colors} <= allowed
    assert hidden_rgb not in allowed
    assert evidence["source_alpha_bbox"][2] > evidence["source_alpha_bbox"][0]
    assert evidence["source_alpha_bbox"][3] > evidence["source_alpha_bbox"][1]
