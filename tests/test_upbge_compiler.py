from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, strategies as st

import src.assembler.upbge_compile as engine_compiler
from src.parity_gates import validate_upbge_inventory
from src.upbge_compiler import (
    FIRST_PARTY_SCRIPT,
    ApprovedAsset,
    CompilerOutputFlags,
    build_compiler_plan,
    domain_to_upbge_xyz,
    upbge_to_domain_xyz,
)
from src.world_contract import WorldContract
from tests.upbge_test_support import build_test_contract


def test_compiler_plan_is_deterministic_bound_to_contract_and_first_party_script():
    contract = build_test_contract()
    flags = CompilerOutputFlags(render=True, blend=True, glb=True, runtime=False)

    first = build_compiler_plan(contract, outputs=flags)
    second = build_compiler_plan(contract, outputs=flags)

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.world_contract_hash == contract.content_hash()
    assert first.compiler_script_sha256 == hashlib.sha256(FIRST_PARTY_SCRIPT.read_bytes()).hexdigest()
    assert dict(first.outputs) == {
        "render": "reference.png", "blend": "scene.blend", "glb": "scene.glb",
        "inventory": "scene_inventory.json",
    }


def test_room_wall_plan_leaves_real_aperture_gaps_without_opening_panels():
    plan = build_compiler_plan(build_test_contract())
    wall_segments = [item for item in plan.room_geometry if item.role == "wall_segment"]

    assert wall_segments
    assert {gap.stable_id for gap in plan.opening_gaps} == {"door_south", "window_east"}
    assert not ({gap.stable_id for gap in plan.opening_gaps} & {
        item.stable_id for item in plan.room_geometry
    })
    for gap in plan.opening_gaps:
        horizontal_axis = 0 if gap.wall in {"north", "south"} else 1
        vertical_axis = 2
        for segment in [item for item in wall_segments if dict(item.metadata)["wall"] == gap.wall]:
            inside_horizontal = (
                abs(gap.position_upbge[horizontal_axis] - segment.position_upbge[horizontal_axis])
                < segment.dimensions_upbge[horizontal_axis] / 2.0
            )
            inside_vertical = (
                abs(gap.position_upbge[vertical_axis] - segment.position_upbge[vertical_axis])
                < segment.dimensions_upbge[vertical_axis] / 2.0
            )
            assert not (inside_horizontal and inside_vertical)


def test_plan_preserves_instances_camera_lights_and_explicit_physics():
    contract = build_test_contract()
    plan = build_compiler_plan(contract)
    table = next(item for item in plan.instances if item.stable_id == "table_1")
    authored = next(item for item in contract.instances if item.id == "table_1")

    assert table.position_upbge == domain_to_upbge_xyz(
        authored.transform.position_m.x,
        authored.transform.position_m.y,
        authored.transform.position_m.z,
    )
    assert table.rotation_upbge_deg == (0.0, 0.0, authored.transform.rotation_deg.y)
    assert plan.camera.vertical_fov_deg == contract.camera.vertical_fov_deg
    assert plan.camera.raster_px == (
        contract.camera.image_width_px, contract.camera.image_height_px
    )
    assert len(plan.lights) == len(contract.lights)
    assert {(item.subject_id, item.body_mode) for item in plan.physics} == {
        (item.subject_id, item.body_mode.value) for item in contract.physics.intents
    }


@given(
    x=st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
    y=st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
    z=st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
)
def test_coordinate_mapping_round_trips(x: float, y: float, z: float):
    assert upbge_to_domain_xyz(*domain_to_upbge_xyz(x, y, z)) == (x, y, z)


def test_runtime_only_player_and_door_are_included_in_resource_estimates():
    contract = build_test_contract(interactions=(
        {"id": "door-action", "kind": "door", "subject_id": "door_south"},
        {"id": "grab-action", "kind": "grab", "subject_id": "door_south"},
    ))
    core = build_compiler_plan(contract)
    runtime = build_compiler_plan(contract, outputs=CompilerOutputFlags(runtime=True))

    assert runtime.runtime is not None
    assert runtime.estimated_object_count == core.estimated_object_count + 2
    assert runtime.estimated_polygon_count == core.estimated_polygon_count + 24


def _replace_instance(contract: WorldContract, stable_id: str, **updates) -> WorldContract:
    payload = contract.model_dump(mode="json")
    instance = next(item for item in payload["instances"] if item["id"] == stable_id)
    instance.update(updates)
    return WorldContract.model_validate(payload)


def test_instance_plan_preserves_strategy_scale_mount_material_identity_and_count():
    contract = build_test_contract()
    table = next(item for item in contract.instances if item.id == "table_1")
    transform = table.transform.model_dump(mode="json")
    transform["scale"] = {"x": 1.25, "y": 0.75, "z": 2.0}
    contract = _replace_instance(contract, "table_1", transform=transform)

    plan = build_compiler_plan(contract)
    compiled = next(item for item in plan.instances if item.stable_id == "table_1")

    assert len(plan.instances) == len(contract.instances)
    assert {item.stable_id for item in plan.instances} == {item.id for item in contract.instances}
    assert compiled.geometry_strategy == table.geometry_strategy
    assert compiled.scale_upbge == (1.25, 2.0, 0.75)
    assert compiled.material_id == table.material_id
    assert dict(compiled.metadata)["mount"] == table.mount.value
    assert dict(compiled.metadata)["category"] == table.category


def test_geometry_and_physics_never_depend_on_instance_name():
    contract = build_test_contract()
    renamed = _replace_instance(contract, "table_1", name="dynamic sphere door")

    original_plan = build_compiler_plan(contract)
    renamed_plan = build_compiler_plan(renamed)
    original = next(item for item in original_plan.instances if item.stable_id == "table_1")
    changed = next(item for item in renamed_plan.instances if item.stable_id == "table_1")

    assert changed == original
    assert renamed_plan.physics == original_plan.physics


def test_approved_asset_strategy_is_hash_bound_and_resource_accounted(tmp_path: Path):
    source = tmp_path / "chair.glb"
    source.write_bytes(b"reviewed self-contained glb")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    contract = _replace_instance(
        build_test_contract(), "table_1", geometry_strategy="asset",
        primitive_shape=None, asset_registry_id="asset:chair:v1",
    )
    binding = ApprovedAsset(source_path=source, sha256=digest, triangle_count=432)

    plan = build_compiler_plan(contract, asset_registry={"asset:chair:v1": binding})
    item = next(value for value in plan.instances if value.stable_id == "table_1")

    assert item.shape == "asset"
    assert item.asset_registry_id == "asset:chair:v1"
    assert item.asset_relative_path == f"assets/{digest}.glb"
    assert item.asset_sha256 == digest
    assert item.estimated_polygons == 432
    with pytest.raises(ValueError, match="no approved registry binding"):
        build_compiler_plan(contract)


def test_camera_plan_preserves_every_camera_contract_field_with_one_axis_mapping():
    contract = build_test_contract()
    camera = contract.camera
    compiled = build_compiler_plan(contract).camera

    assert compiled.position_upbge == domain_to_upbge_xyz(*camera.position_m.model_dump().values())
    assert compiled.target_upbge == domain_to_upbge_xyz(*camera.target_m.model_dump().values())
    assert compiled.up_upbge == domain_to_upbge_xyz(*camera.up.model_dump().values())
    assert compiled.vertical_fov_deg == camera.vertical_fov_deg
    assert compiled.aspect_ratio == camera.aspect_ratio
    assert compiled.near_plane_m == camera.near_plane_m
    assert compiled.far_plane_m == camera.far_plane_m
    assert compiled.raster_px == (camera.image_width_px, camera.image_height_px)


@pytest.mark.parametrize("role", ["render", "blend", "glb", "runtime"])
def test_each_requested_output_flag_is_signed_into_the_plan(role: str):
    flags = CompilerOutputFlags(**{
        name: name == role for name in ("render", "blend", "glb", "runtime")
    })
    outputs = dict(build_compiler_plan(build_test_contract(), outputs=flags).outputs)

    if role == "runtime":
        assert outputs == {
            "runtime_candidate": "runtime_candidate.blend",
            "inventory": "scene_inventory.json",
        }
    else:
        assert set(outputs) == {role, "inventory"}


def test_engine_script_rejects_cli_flags_that_disagree_with_signed_plan(tmp_path: Path):
    contract = build_test_contract()
    plan = build_compiler_plan(contract, outputs=CompilerOutputFlags(blend=True))
    input_path = tmp_path / "world_contract.json"
    plan_path = tmp_path / "compiler_plan.json"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    input_path.write_bytes(contract.canonical_bytes())
    plan_path.write_bytes(plan.canonical_bytes())
    args = SimpleNamespace(
        input=str(input_path), plan=str(plan_path), output_dir=str(output_dir),
        render="0", blend="0", glb="0", runtime="0", max_objects=2048,
        max_polygons=2_000_000, max_texture_dimension=8192,
    )

    with pytest.raises(ValueError, match="output flags do not match"):
        engine_compiler._validate_inputs(args)


# Property 4: Authority Preservation
# **Validates: Requirements 1.2, 5.2, 5.3**
@given(
    x=st.floats(-100.0, 100.0, allow_nan=False, allow_infinity=False),
    y=st.floats(-100.0, 100.0, allow_nan=False, allow_infinity=False),
    z=st.floats(-100.0, 100.0, allow_nan=False, allow_infinity=False),
    scale=st.floats(0.01, 10.0, allow_nan=False, allow_infinity=False),
)
def test_property_compiler_preserves_authored_instance_transform(
    x: float, y: float, z: float, scale: float,
):
    contract = build_test_contract()
    authored = next(item for item in contract.instances if item.id == "table_1")
    transform = authored.transform.model_dump(mode="json")
    transform["position_m"] = {"x": x, "y": y, "z": z}
    transform["scale"] = {"x": scale, "y": scale, "z": scale}
    changed = _replace_instance(contract, "table_1", transform=transform)
    before = changed.canonical_bytes()

    compiled = next(
        item for item in build_compiler_plan(changed).instances
        if item.stable_id == "table_1"
    )

    assert compiled.position_upbge == domain_to_upbge_xyz(x, y, z)
    assert compiled.scale_upbge == (scale, scale, scale)
    assert changed.canonical_bytes() == before


def _write_compiler_inventory(tmp_path: Path, contract: WorldContract) -> Path:
    plan = build_compiler_plan(contract)
    plan_payload = plan.to_dict()
    objects = []
    for spec in (*plan.room_geometry, *plan.instances):
        payload = dict(spec.__dict__)
        payload["compiled_dimensions_upbge"] = [
            dimension * scale
            for dimension, scale in zip(spec.dimensions_upbge, spec.scale_upbge)
        ]
        objects.append(payload)
    engine_compiler._write_inventory(
        tmp_path, contract.model_dump(mode="json"), plan_payload, objects,
    )
    return tmp_path / "scene_inventory.json"


def test_compiler_inventory_round_trip_covers_all_authoritative_domains(tmp_path: Path):
    contract = build_test_contract(interactions=(
        {"id": "grab-table", "kind": "grab", "subject_id": "table_1"},
    ))

    inventory_path = _write_compiler_inventory(tmp_path, contract)
    report = validate_upbge_inventory(contract, inventory_path)
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))

    assert report.passed is True
    assert dict(report.compared_counts) == {
        "rooms": 1, "openings": len(contract.openings),
        "objects": len(contract.instances), "materials": len(contract.materials),
        "lights": len(contract.lights), "cameras": 1,
        "physics": len(contract.physics.intents), "interactions": 1,
    }
    assert payload["objects"][0]["rotation_upbge_deg"] is not None
    assert payload["objects"][0]["scale_upbge"] is not None
    assert payload["camera"]["projection"] == contract.camera.projection
    with pytest.raises(FileExistsError):
        engine_compiler._write_inventory(
            tmp_path, contract.model_dump(mode="json"),
            build_compiler_plan(contract).to_dict(), [],
        )


def test_upbge_inventory_rejects_drift_across_every_authoritative_domain(tmp_path: Path):
    contract = build_test_contract(interactions=(
        {"id": "grab-table", "kind": "grab", "subject_id": "table_1"},
    ))
    inventory_path = _write_compiler_inventory(tmp_path, contract)
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    payload["room"]["floor_material_id"] = "wrong"
    payload["openings"][0]["wall"] = "west"
    instance = next(item for item in payload["objects"] if item["stable_id"] == "table_1")
    instance["rotation_upbge_deg"][2] += 5.0
    instance["scale_upbge"][0] += 0.5
    instance["mount"] = "ceiling"
    instance["material_id"] = "wrong"
    instance["relations"] = [{"kind": "centered", "weight": 99.0}]
    payload["materials"][0]["roughness"] += 0.2
    payload["lights"][0]["direction_upbge"][0] += 1.0
    payload["camera"]["far_plane_m"] += 10.0
    payload["physics"][0]["friction"] += 0.2
    payload["interactions"][0]["parameters"] = {"max_mass_kg": 999.0}
    inventory_path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_upbge_inventory(contract, inventory_path)
    paths = {issue.path for issue in report.issues}

    assert report.passed is report.artifact_accepted is False
    assert "room.floor_material_id" in paths
    assert any(path.endswith(".wall") for path in paths)
    assert any("rotation_upbge_deg" in path for path in paths)
    assert any("scale_upbge" in path for path in paths)
    assert any(path.endswith(".mount") for path in paths)
    assert any(path.endswith(".material_id") for path in paths)
    assert any(path.endswith(".relations") for path in paths)
    assert any(path.endswith(".roughness") for path in paths)
    assert any("direction_upbge" in path for path in paths)
    assert "camera.far_plane_m" in paths
    assert any(path.endswith(".friction") for path in paths)
    assert any(path.endswith(".parameters") for path in paths)
