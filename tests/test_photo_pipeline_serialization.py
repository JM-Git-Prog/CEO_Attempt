"""Tests for photo pipeline manifest serialization round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from src.photo_pipeline.models import (
    ObjectManifestEntry,
    PipelineManifest,
    StageResult,
)
from src.photo_pipeline.serialization import (
    ManifestSerializationError,
    deserialize_manifest,
    serialize_manifest,
)


def _make_stage_result(**overrides: object) -> StageResult:
    defaults = {
        "stage_name": "scene_parse",
        "success": True,
        "duration_s": 12.5,
        "reason_code": "COMPLETED",
        "diagnostics": "ok",
        "artifacts": {"room_plate": Path("output/room_plate.png")},
        "fallback_used": None,
    }
    defaults.update(overrides)
    return StageResult(**defaults)


def _make_object_entry(**overrides: object) -> ObjectManifestEntry:
    defaults = {
        "mask_id": "obj_001",
        "bbox_px": (10, 20, 100, 200),
        "area_px": 5000,
        "centroid_px": (60.0, 120.0),
        "object_png_path": Path("output/obj_001.png"),
        "mesh_path": Path("output/obj_001.glb"),
        "mesh_method": "hunyuan3d",
        "mesh_gen_time_s": 45.2,
        "audio_path": Path("output/obj_001.wav"),
        "audio_method": "comfyui_audio",
        "material_category": "wood",
        "scale_m": (0.5, 1.2, 0.3),
        "scale_confidence": 0.85,
        "position_m": (1.0, 0.0, -2.0),
        "rotation_deg": (0.0, 45.0, 0.0),
        "settled": True,
        "collision_method": "vhacd",
        "lod_levels": 4,
        "fallbacks_triggered": [],
    }
    defaults.update(overrides)
    return ObjectManifestEntry(**defaults)


def _make_manifest(**overrides: object) -> PipelineManifest:
    defaults = {
        "session_id": "test-session-001",
        "source_image_path": Path("input/photo.jpg"),
        "stages": [_make_stage_result()],
        "objects": [_make_object_entry()],
        "quality_classification": "full",
        "total_duration_s": 120.5,
        "source_type": "photo",
        "world_contract_path": Path("output/contract.json"),
    }
    defaults.update(overrides)
    return PipelineManifest(**defaults)


class TestSerializeManifest:
    """Unit tests for serialize_manifest."""

    def test_produces_bytes(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        assert isinstance(result, bytes)

    def test_produces_valid_json(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_sorted_keys(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        text = result.decode("utf-8")
        parsed = json.loads(text)
        # Top-level keys should be alphabetically sorted
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_no_whitespace(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        text = result.decode("utf-8")
        # No spaces after colons or commas (canonical separators)
        assert ": " not in text
        assert ", " not in text

    def test_utf8_encoding(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        # Should decode as valid UTF-8
        text = result.decode("utf-8")
        assert isinstance(text, str)

    def test_paths_serialized_as_posix(self) -> None:
        manifest = _make_manifest(
            source_image_path=Path("C:/Users/test/photo.jpg")
        )
        result = serialize_manifest(manifest)
        parsed = json.loads(result)
        assert parsed["source_image_path"] == "C:/Users/test/photo.jpg"

    def test_none_serialized_as_null(self) -> None:
        manifest = _make_manifest(world_contract_path=None)
        result = serialize_manifest(manifest)
        parsed = json.loads(result)
        assert parsed["world_contract_path"] is None

    def test_tuples_serialized_as_arrays(self) -> None:
        manifest = _make_manifest()
        result = serialize_manifest(manifest)
        parsed = json.loads(result)
        obj = parsed["objects"][0]
        assert isinstance(obj["bbox_px"], list)
        assert obj["bbox_px"] == [10, 20, 100, 200]

    def test_fallback_used_string(self) -> None:
        stage = _make_stage_result(fallback_used="unique3d")
        manifest = _make_manifest(stages=[stage])
        result = serialize_manifest(manifest)
        parsed = json.loads(result)
        assert parsed["stages"][0]["fallback_used"] == "unique3d"


class TestDeserializeManifest:
    """Unit tests for deserialize_manifest."""

    def test_invalid_json_raises(self) -> None:
        import pytest

        with pytest.raises(ManifestSerializationError, match="invalid manifest JSON"):
            deserialize_manifest(b"not json")

    def test_non_object_json_raises(self) -> None:
        import pytest

        with pytest.raises(
            ManifestSerializationError, match="expected JSON object"
        ):
            deserialize_manifest(b"[1, 2, 3]")

    def test_reconstructs_paths(self) -> None:
        manifest = _make_manifest()
        data = serialize_manifest(manifest)
        result = deserialize_manifest(data)
        assert isinstance(result.source_image_path, Path)
        assert result.source_image_path == Path("input/photo.jpg")

    def test_reconstructs_tuples(self) -> None:
        manifest = _make_manifest()
        data = serialize_manifest(manifest)
        result = deserialize_manifest(data)
        assert isinstance(result.objects[0].bbox_px, tuple)
        assert result.objects[0].bbox_px == (10, 20, 100, 200)

    def test_reconstructs_none(self) -> None:
        manifest = _make_manifest(world_contract_path=None)
        data = serialize_manifest(manifest)
        result = deserialize_manifest(data)
        assert result.world_contract_path is None

    def test_reconstructs_dict_with_path_values(self) -> None:
        manifest = _make_manifest()
        data = serialize_manifest(manifest)
        result = deserialize_manifest(data)
        artifacts = result.stages[0].artifacts
        assert isinstance(artifacts, dict)
        assert isinstance(artifacts["room_plate"], Path)
        assert artifacts["room_plate"] == Path("output/room_plate.png")


class TestRoundTrip:
    """Tests that serialize → deserialize produces structurally equal manifests."""

    def test_basic_round_trip(self) -> None:
        manifest = _make_manifest()
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest

    def test_round_trip_with_none_fields(self) -> None:
        obj = _make_object_entry(
            mesh_path=None,
            mesh_method=None,
            audio_path=None,
            audio_method=None,
            collision_method=None,
        )
        manifest = _make_manifest(objects=[obj], world_contract_path=None)
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest

    def test_round_trip_with_fallbacks(self) -> None:
        obj = _make_object_entry(
            fallbacks_triggered=["hunyuan3d", "unique3d"],
            mesh_method="triposr",
        )
        stage = _make_stage_result(fallback_used="triposr")
        manifest = _make_manifest(
            objects=[obj],
            stages=[stage],
            quality_classification="degraded",
        )
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest

    def test_round_trip_multiple_stages_and_objects(self) -> None:
        stages = [
            _make_stage_result(stage_name="scene_parse", duration_s=30.0),
            _make_stage_result(stage_name="depth_estimation", duration_s=15.0),
            _make_stage_result(stage_name="object_generation", duration_s=90.0),
        ]
        objects = [
            _make_object_entry(mask_id="obj_001"),
            _make_object_entry(mask_id="obj_002", mesh_method="triposr"),
            _make_object_entry(mask_id="obj_003", mesh_path=None, mesh_method=None),
        ]
        manifest = _make_manifest(stages=stages, objects=objects)
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest

    def test_round_trip_windows_paths(self) -> None:
        """Windows-style paths should survive round-trip via POSIX normalization."""
        manifest = _make_manifest(
            source_image_path=Path("C:/Users/test/images/photo.jpg"),
            world_contract_path=Path("output/sessions/abc/contract.json"),
        )
        result = deserialize_manifest(serialize_manifest(manifest))
        # Paths round-trip through POSIX form, so they should be equal
        assert result.source_image_path == manifest.source_image_path
        assert result.world_contract_path == manifest.world_contract_path

    def test_round_trip_empty_lists(self) -> None:
        manifest = _make_manifest(
            stages=[],
            objects=[],
        )
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest

    def test_round_trip_minimal_quality(self) -> None:
        manifest = _make_manifest(
            quality_classification="minimal",
            objects=[],
        )
        result = deserialize_manifest(serialize_manifest(manifest))
        assert result == manifest
