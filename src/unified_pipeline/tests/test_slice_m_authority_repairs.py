"""Focused regressions for Task 11.8 Slice M authority repairs.

**Validates: Requirements 19.2, 19.3, 21.4, 22.1, 22.5**
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from src.unified_pipeline.lighting_authority import (
    AMBIENT_MAX,
    AMBIENT_MIN,
    EXPOSURE_MAX,
    EXPOSURE_MIN,
    POINT_CANDELA_MAX,
    POINT_CANDELA_MIN,
    PROFILE,
    derive_canon_lighting,
)
from src.unified_pipeline.mesh_shading import audit_glb_shading
from src.unified_pipeline.strict_real_handlers import _material_parameters
from src.unified_pipeline.world_contract import (
    AssetBinding,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    WorldContract,
    compute_hash,
    validate_lighting_config,
)


def _minimal_glb(path: Path, *, normals: bool) -> str:
    attributes = {"POSITION": 0}
    if normals:
        attributes["NORMAL"] = 1
    payload = json.dumps(
        {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": attributes}]}]},
        separators=(",", ":"),
    ).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    data = struct.pack("<4sII", b"glTF", 2, 20 + len(payload))
    data += struct.pack("<II", len(payload), 0x4E4F534A) + payload
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_canon_luminance_maps_deterministically_to_bounded_physical_units() -> None:
    mean = (119.389404296875, 88.150390625, 67.166015625)
    first, evidence = derive_canon_lighting(mean, room_height_m=2.7, source_sha256="a" * 64)
    second, duplicate = derive_canon_lighting(mean, room_height_m=2.7, source_sha256="a" * 64)

    assert first == second
    assert evidence == duplicate
    assert evidence.normalized_luminance == pytest.approx(0.3657911100260417)
    assert first.derivation_profile == PROFILE
    assert first.ambient_intensity == pytest.approx(0.98894933203125)
    assert first.exposure == pytest.approx(1.106053777018229)
    assert first.lights[0].intensity == pytest.approx(25.55797328125)
    assert first.ambient_intensity_unit == "scene-linear-multiplier"
    assert first.lights[0].intensity_unit == "candela"
    assert first.white_balance_color == first.lights[0].white_balance_color
    assert first.lights[0].color != "#775843"
    assert first.legacy_ambient_color == "#775843"
    assert first.legacy_ambient_intensity == pytest.approx(0.20118511051432295)
    assert first.lights[0].legacy_intensity == pytest.approx(0.7315822200520834)
    validate_lighting_config(first, supported_light_types=frozenset({"point"}))


@pytest.mark.parametrize("mean", [(0.0, 0.0, 0.0), (255.0, 255.0, 255.0), (255.0, 0.0, 128.0)])
def test_physical_lighting_profile_is_readable_and_bounded(mean) -> None:
    lighting, _ = derive_canon_lighting(mean, room_height_m=2.7, source_sha256="b" * 64)
    assert AMBIENT_MIN <= lighting.ambient_intensity <= AMBIENT_MAX
    assert EXPOSURE_MIN <= lighting.exposure <= EXPOSURE_MAX
    assert POINT_CANDELA_MIN <= lighting.lights[0].intensity <= POINT_CANDELA_MAX


def test_invalid_physical_lighting_fails_closed() -> None:
    lighting, _ = derive_canon_lighting((100.0, 90.0, 80.0), room_height_m=2.7, source_sha256="c" * 64)
    with pytest.raises(ValueError, match="candela"):
        validate_lighting_config(
            replace(lighting, lights=(replace(lighting.lights[0], intensity=1000.0),)),
            supported_light_types=frozenset({"point"}),
        )
    with pytest.raises(ValueError, match="0..255"):
        derive_canon_lighting((300.0, 0.0, 0.0), room_height_m=2.7, source_sha256="c" * 64)


def test_missing_normal_strategy_is_explicit_hash_bound_and_nonmutating(tmp_path: Path) -> None:
    source = tmp_path / "without-normals.glb"
    digest = _minimal_glb(source, normals=False)
    before = source.read_bytes()

    audit = audit_glb_shading(source, expected_sha256=digest)

    assert audit.shading_model == "flat"
    assert audit.primitive_count == 1
    assert audit.primitives_with_normals == 0
    assert len(audit.provenance_sha256) == 64
    assert source.read_bytes() == before
    intent = MaterialIntent(
        base_color="#886644",
        metallic=0.0,
        roughness=0.7,
        shading_model=audit.shading_model,
        shading_provenance=audit.provenance_sha256,
    )
    instance = ObjectInstance(
        object_id="mesh-without-normals",
        asset_binding=AssetBinding(
            asset_id=digest,
            mesh_path=str(source),
            triangle_count=1,
            vertex_count=3,
            generator="hunyuan3d",
        ),
        material_intent=intent,
    )
    baseline = WorldContract(contract_id="slice-m", instances=(instance,))
    changed = replace(
        baseline,
        instances=(replace(
            instance,
            material_intent=replace(intent, shading_provenance="f" * 64),
        ),),
    )
    assert compute_hash(baseline) != compute_hash(changed)


def test_complete_asset_normals_select_smooth_without_byte_repair(tmp_path: Path) -> None:
    source = tmp_path / "with-normals.glb"
    digest = _minimal_glb(source, normals=True)
    before = source.read_bytes()
    audit = audit_glb_shading(source, expected_sha256=digest)
    assert audit.shading_model == "smooth"
    assert audit.primitives_with_normals == audit.primitive_count == 1
    assert source.read_bytes() == before


def test_legacy_lighting_payload_remains_readable_with_explicit_compatibility_values() -> None:
    restored = LightingConfig.from_dict({
        "ambient_color": "#223344",
        "ambient_intensity": 0.25,
        "lights": [{
            "light_id": "legacy",
            "light_type": "point",
            "position": {"x": 0.0, "y": 2.0, "z": 0.0},
            "color": "#ffeecc",
            "intensity": 0.75,
            "temperature": 4500.0,
            "cast_shadows": False,
        }],
    })
    assert restored.derivation_profile == "legacy-normalized/v1"
    assert restored.legacy_ambient_color == "#223344"
    assert restored.legacy_ambient_intensity == 0.25
    assert restored.lights[0].legacy_color == "#ffeecc"
    assert restored.lights[0].legacy_intensity == 0.75


def test_environment_free_metal_intent_remains_metallic_but_renderable() -> None:
    """Near-pure metalness is invalid until an environment map is authoritative."""
    base_color, metallic, roughness = _material_parameters("brushed steel")

    assert base_color == "#B7BDC5"
    assert metallic == pytest.approx(0.35)
    assert 0.0 < metallic < 0.9
    assert roughness == pytest.approx(0.32)

    intent = MaterialIntent(
        base_color=base_color,
        metallic=metallic,
        roughness=roughness,
        render_profile="environment-free-bounded-metallic/v1",
    )
    assert MaterialIntent.from_dict(intent.to_dict()) == intent
    legacy = replace(intent, render_profile="legacy-authoritative/v1")
    assert intent.to_dict() != legacy.to_dict()
