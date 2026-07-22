from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
import trimesh
from hypothesis import given, settings, strategies as st

from src.camera_contract import camera_contract_for_plan
from src.export_adapters import (
    AdapterCapabilities,
    ExportAdapterResult,
    FeatureRepresentation,
    GLBThreeMetadataAdapter,
    GodotWorldContractAdapter,
    assemble_godot_world_contract,
)
from src.floor_plan.models import FloorPlan
from src.models import SceneGraph
from src.parity_gates import (
    NumericTolerances,
    compare_inventory,
    inventory_from_world_contract,
    run_runtime_smoke,
    validate_glb_reload,
    write_gate_report,
)
from src.world_contract import ExportPolicy, build_world_contract

FIXTURE = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"


def _contract():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = FloorPlan.model_validate(payload["plan"])
    scene = SceneGraph.model_validate(payload["scene_graph"])
    return build_world_contract(
        plan, scene, camera_contract_for_plan(plan), session_id="portable-test",
        interface_version=11, profile_id="upbge-r1", plan_revision=4,
        appearance_intent={"mood": "warm"},
        export_policy=ExportPolicy(targets=("godot", "glb")),
        interactions=({"id": "grab-table", "kind": "grab", "subject_id": "table_1"},),
    )


def _rewrite_glb_document(path: Path, mutate) -> None:
    data = path.read_bytes()
    version, _total = struct.unpack_from("<II", data, 4)
    chunks = []
    cursor = 12
    while cursor < len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        chunk = data[cursor:cursor + length]
        cursor += length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            mutate(document)
            chunk = json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
            chunk += b" " * (-len(chunk) % 4)
        chunks.append((chunk_type, chunk))
    body = b"".join(
        struct.pack("<II", len(chunk), chunk_type) + chunk
        for chunk_type, chunk in chunks
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", version, 12 + len(body)) + body)


def _add_glb_gate_metadata(document: dict, *, camera_id: str, light_id: str) -> None:
    nodes = document.setdefault("nodes", [])
    mesh_node = next(node for node in nodes if "mesh" in node)
    mesh_node["extras"] = {"kiro_stable_id": "table_1"}
    camera_node = len(nodes)
    nodes.append({"camera": 0, "extras": {"kiro_stable_id": camera_id}})
    light_node = len(nodes)
    nodes.append({
        "extensions": {"KHR_lights_punctual": {"light": 0}},
        "extras": {"kiro_stable_id": light_id},
    })
    document["cameras"] = [{
        "type": "perspective",
        "perspective": {"yfov": 0.785398, "znear": 0.1, "zfar": 100.0},
    }]
    document.setdefault("extensions", {})["KHR_lights_punctual"] = {
        "lights": [{"type": "point", "color": [1.0, 1.0, 1.0], "intensity": 1.0}]
    }
    used = document.setdefault("extensionsUsed", [])
    if "KHR_lights_punctual" not in used:
        used.append("KHR_lights_punctual")
    for scene in document.get("scenes", []):
        scene.setdefault("nodes", []).extend((camera_node, light_node))


def test_world_contract_adapters_preserve_authority_and_emit_hash_bound_metadata(tmp_path):
    contract = _contract()
    before = contract.canonical_bytes()

    godot = GodotWorldContractAdapter().export(contract, tmp_path / "godot")
    three = GLBThreeMetadataAdapter().export(contract, tmp_path / "three")

    assert godot.status == "partial"
    assert {item.feature_id for item in godot.unsupported_features} == {
        "godot.project", "interaction_runtime:grab-table",
    }
    assert three.status == "partial"
    assert three.unsupported_features[0].feature_id == "glb.geometry"
    assert not any(item.media_type == "model/gltf-binary" for item in three.artifacts)
    assert godot.world_contract_hash == three.world_contract_hash == contract.content_hash()
    assert contract.canonical_bytes() == before
    metadata = json.loads(Path(three.manifests[0].path).read_text(encoding="utf-8"))
    assert metadata["instances"][1]["id"] == "table_1"
    assert metadata["interactions"][0]["id"] == "grab-table"
    assert metadata["length_unit"] == "meter"


def test_structural_parity_checks_exact_identity_and_numeric_tolerance():
    contract = _contract()
    inventory = inventory_from_world_contract(contract, target="upbge")
    assert compare_inventory(contract, inventory).passed is True

    first = inventory.objects[0]
    moved = first.model_copy(update={
        "transform": first.transform.model_copy(update={
            "position_m": first.transform.position_m.model_copy(update={"x": 0.25})
        })
    })
    drifted = inventory.model_copy(update={"objects": (moved, *inventory.objects[1:])})
    report = compare_inventory(
        contract, drifted, NumericTolerances(position_m=0.001)
    )

    assert report.passed is False
    assert report.artifact_accepted is False
    assert any(issue.code == "numeric_tolerance_exceeded" for issue in report.issues)


def test_glb_reload_uses_trimesh_and_runtime_absence_is_honest(tmp_path):
    glb_path = tmp_path / "box.glb"
    trimesh.Scene(trimesh.creation.box()).export(glb_path)

    reload_report = validate_glb_reload(
        glb_path, require_camera=False, require_lights=False
    )
    smoke = run_runtime_smoke(
        engine_path=None, package_path=tmp_path / "runtime-package"
    )

    assert reload_report.passed is True
    assert reload_report.geometry_count == 1
    assert smoke.available is False
    assert smoke.status == "unavailable"
    assert smoke.passed is smoke.artifact_accepted is False


def test_glb_reload_validates_exact_camera_light_identities_and_preserves_rejection(tmp_path):
    glb_path = tmp_path / "scene.glb"
    trimesh.Scene(trimesh.creation.box()).export(glb_path)
    _rewrite_glb_document(
        glb_path,
        lambda document: _add_glb_gate_metadata(
            document, camera_id="canon-camera", light_id="ceiling-light"
        ),
    )

    accepted = validate_glb_reload(
        glb_path,
        expected_stable_ids=("table_1",),
        expected_camera_ids=("canon-camera",),
        expected_light_ids=("ceiling-light",),
    )
    rejected = validate_glb_reload(
        glb_path,
        expected_stable_ids=("table_1",),
        expected_camera_ids=("wrong-camera",),
        expected_light_ids=("ceiling-light", "unexpected-light"),
    )
    evidence_path = write_gate_report(rejected, tmp_path / "reports" / "glb_reload.json")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert accepted.passed is accepted.artifact_accepted is True
    assert accepted.stable_ids == ("canon-camera", "ceiling-light", "table_1")
    assert accepted.camera_ids == ("canon-camera",)
    assert accepted.light_ids == ("ceiling-light",)
    assert rejected.passed is rejected.artifact_accepted is False
    assert {check.name for check in rejected.checks if not check.passed} == {
        "cameras", "punctual_lights",
    }
    assert evidence["artifact_accepted"] is False
    assert any(check["diagnostic"] for check in evidence["checks"] if not check["passed"])
    with pytest.raises(FileExistsError):
        write_gate_report(rejected, evidence_path)


def test_adapter_manifests_are_non_overwriting_and_preserve_full_contract(tmp_path):
    contract = _contract()
    output = tmp_path / "godot"

    result = GodotWorldContractAdapter().export(contract, output)
    metadata = json.loads(Path(result.manifests[0].path).read_text(encoding="utf-8"))

    assert metadata["artifact_scope"] == "metadata_only"
    assert metadata["target_independent_schema_version"] == "portable-world-metadata/v1"
    assert metadata["world_contract"] == contract.model_dump(mode="json")
    with pytest.raises(FileExistsError):
        GodotWorldContractAdapter().export(contract, output)


def test_glb_adapter_rejects_missing_named_geometry_without_creating_glb(tmp_path):
    contract = _contract()
    missing = tmp_path / "missing.glb"

    result = GLBThreeMetadataAdapter(missing).export(contract, tmp_path / "three")

    assert result.status == "rejected"
    assert result.unsupported_features[0].reason_code == "missing_glb"
    assert not missing.exists()
    assert not any(item.media_type == "model/gltf-binary" for item in result.artifacts)


def test_contract_native_godot_project_preserves_authority_and_reports_runtime_gap(tmp_path):
    contract = _contract()
    before = contract.canonical_bytes()

    project, result = assemble_godot_world_contract(contract, tmp_path, {})
    main_scene = (project / "main.tscn").read_text(encoding="utf-8")
    player_scene = (project / "player.tscn").read_text(encoding="utf-8")

    assert result.status == "partial"
    assert {item.feature_id for item in result.unsupported_features} == {
        "interaction_runtime:grab-table"
    }
    assert all(not item.feature_id.startswith("opening_aperture:")
               for item in result.unsupported_features)
    assert 'type="CSGCombiner3D"' in main_scene
    assert 'metadata/_kiro_stable_id = "door_south"' in main_scene
    assert f'metadata/_kiro_stable_id = "{contract.camera.id}"' in main_scene
    assert f"fov = {contract.camera.vertical_fov_deg}" in main_scene
    assert f"near = {contract.camera.near_plane_m}" in main_scene
    assert f"far = {contract.camera.far_plane_m}" in main_scene
    assert "current = false" in player_scene
    assert {item.target_role for item in result.artifacts} >= {
        "godot_project", "godot_main_scene", "godot_world_metadata"
    }
    assert contract.canonical_bytes() == before


def test_glb_three_adapter_copies_portable_asset_and_emits_loader_binding(tmp_path):
    contract = _contract()
    source = tmp_path / "compiled" / "source.glb"
    source.parent.mkdir()
    trimesh.Scene(trimesh.creation.box()).export(source)

    result = GLBThreeMetadataAdapter(source).export(contract, tmp_path / "portable")
    glb = next(item for item in result.artifacts if item.media_type == "model/gltf-binary")
    metadata = json.loads(Path(result.manifests[0].path).read_text(encoding="utf-8"))

    assert result.status == "success"
    assert Path(glb.path) == tmp_path / "portable" / "scene.glb"
    assert Path(glb.path).read_bytes() == source.read_bytes()
    assert metadata["target"]["asset_uri"] == "scene.glb"
    assert metadata["target"]["camera_source"] == contract.camera.id
    assert metadata["target"]["stable_id_extra_keys"][0] == "kiro_stable_id"
    dispositions = {item.feature_id: item.disposition for item in result.feature_representations}
    assert dispositions["physics"] == "sidecar_metadata"
    assert dispositions["interactions"] == "sidecar_metadata"


def test_adapter_result_rejects_unsupported_feature_without_matching_disposition():
    capabilities = AdapterCapabilities(
        adapter_id="test/v1", target="godot", metadata_schema_version="test/v1"
    )
    contract = _contract()

    with pytest.raises(ValueError, match="unsupported disposition"):
        ExportAdapterResult(
            adapter_id="test/v1", target="godot", status="partial",
            world_contract_hash=contract.content_hash(), capabilities=capabilities,
            feature_representations=(FeatureRepresentation(
                feature_id="runtime", disposition="native"
            ),),
            unsupported_features=({
                "feature_id": "runtime", "reason_code": "missing",
                "message": "missing", "required": False,
            },),
        )


# Property 5: Instance Conservation
# **Validates: Requirements 5.2, 7.5**
@settings(max_examples=10, deadline=None)
@given(reverse_instances=st.booleans(), reverse_materials=st.booleans())
def test_property_portable_metadata_conserves_every_instance_once(
    reverse_instances: bool, reverse_materials: bool,
):
    from tempfile import TemporaryDirectory

    contract = _contract()
    payload = contract.model_dump(mode="json")
    if reverse_instances:
        payload["instances"].reverse()
    if reverse_materials:
        payload["materials"].reverse()
    equivalent = type(contract).model_validate(payload)

    with TemporaryDirectory() as directory:
        result = GLBThreeMetadataAdapter().export(equivalent, Path(directory) / "three")
        metadata = json.loads(Path(result.manifests[0].path).read_text(encoding="utf-8"))

    expected = sorted(item.id for item in equivalent.instances)
    actual = [item["id"] for item in metadata["instances"]]
    assert actual == expected
    assert len(actual) == len(set(actual))
    assert result.world_contract_hash == contract.content_hash()
