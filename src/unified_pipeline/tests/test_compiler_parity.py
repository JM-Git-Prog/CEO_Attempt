"""Focused tests for compiler selection and post-compile parity.

**Validates: Requirements 20.8, 21.4, 21.5**
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.compilers.parity import (
    CompilerAuthority,
    CompilerParityPayload,
    CompilerSelectionError,
    CompilerSelector,
    CompilerTarget,
    InvalidCompilerPayload,
    PublicationBlocked,
    RoomDimensions,
    adapt_compiler_manifest,
    build_parity_payload,
    run_parity_gate,
)
from src.unified_pipeline.event_system import EventFinality, EventSystem
from src.unified_pipeline.world_contract import (
    AssetBinding,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Vec3,
    WorldContract,
    finalize,
)


def _authority() -> CompilerAuthority:
    camera = CameraContract(
        position=(2.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        vfov=55.0,
        near=0.1,
        far=40.0,
    )
    instance = ObjectInstance(
        object_id="table-uuid",
        name="table",
        position=Vec3(0.75, 0.4, -0.5),
        rotation=Quaternion(0.0, 0.382683432365, 0.0, 0.923879532511),
        scale=Vec3(1.2, 0.8, 1.0),
        asset_binding=AssetBinding(
            asset_id="a" * 64,
            mesh_path="C:/approved/table.glb",
            triangle_count=1200,
            vertex_count=700,
            generator="hunyuan3d",
        ),
        physics_intent="static",
        material_intent=MaterialIntent(
            base_color="#7a4b2a", metallic=0.0, roughness=0.72,
            normal_map_ref="embedded:normal", pass_level=2,
        ),
        semantic_label="furniture/table",
    )
    contract = finalize(WorldContract(
        plan_revision="rev-7",
        camera_hash=camera.compute_hash(),
        camera=camera,
        room_shell_ref="parametric-room:sha256:" + "b" * 64,
        instances=(instance,),
        contract_id="parity-contract",
        created_at="2026-08-01T00:00:00Z",
    ))
    return CompilerAuthority(
        contract=contract,
        camera=camera,
        room_dimensions=RoomDimensions(4.0, 3.0, 2.7),
        asset_normalization_counts={"table-uuid": 1},
    )


class _FakeCompiler:
    def __init__(self, target: str, calls: list[str], mutate=None) -> None:
        self.target = target
        self.calls = calls
        self.mutate = mutate

    def compile(self, contract: WorldContract, output_dir: str | Path):
        self.calls.append(self.target)
        payload = build_parity_payload(_authority(), self.target).to_dict()
        assert contract.contract_hash == payload["contract_hash"]
        if self.mutate is not None:
            self.mutate(payload)
        return {"parity_payload": payload, "output_dir": str(output_dir)}


def test_selector_compiles_browser_then_selected_engine_and_only_then_authorizes(tmp_path):
    authority = _authority()
    calls: list[str] = []
    selector = CompilerSelector({
        "browser": _FakeCompiler("browser", calls),
        "godot": _FakeCompiler("godot", calls),
    })
    events = EventSystem("parity-order")
    registered = events.register_contract(authority.contract)

    batch = selector.compile_and_authorize(
        authority, [CompilerTarget.GODOT], tmp_path, events,
        structural_gates_passed=True,
    )

    assert calls == ["browser", "godot"]
    assert batch.parity_report.passed
    assert batch.parity_report.targets == ("browser", "godot")
    assert registered.finality is EventFinality.PROVISIONAL
    assert events.events[-1].event_type == "world_contract.finalized"
    assert events.events[-1].finality is EventFinality.FINAL


def _set_path(data, path, value):
    current = data
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("contract_hash",), "f" * 64, "hash_mismatch"),
        (("plan_revision",), "rev-8", "revision_mismatch"),
        (("camera", "vfov"), 54.0, "camera_drift"),
        (("room_dimensions", "width_m"), 3.9, "room_dimension_drift"),
        (("instances", 0, "transform", "position", "x"), 0.76, "solved_transform_drift"),
        (("instances", 0, "transform", "rotation", "w"), 1.0, "solved_transform_drift"),
        (("instances", 0, "transform", "scale", "x"), 1.0, "solved_transform_drift"),
        (("instances", 0, "asset_binding", "mesh_path"), "rescaled/table.glb", "asset_binding_drift"),
        (("instances", 0, "material_binding", "roughness"), 0.5, "material_binding_drift"),
        (("instances", 0, "material_binding", "shading_model"), "flat", "material_binding_drift"),
        (("lighting", "ambient_intensity"), 0.9, "lighting_drift"),
        (("navigation",), {"coordinate_system": "z-up"}, "navigation_collision_drift"),
        (("derivation", "consumer_defaults"), ["roughness=0.5"], "consumer_default"),
        (("derivation", "clamps"), ["position.x"], "clamp"),
        (("derivation", "rescalings"), ["meters_to_units"], "rescaling"),
        (("derivation", "rotation_substitutions"), ["quaternion_to_euler"], "rotation_substitution"),
        (("derivation", "offset_substitutions"), ["origin_shift"], "offset_substitution"),
        (("derivation", "camera_inferred"), True, "camera_inference"),
        (("derivation", "asset_normalization_counts", "table-uuid"), 2, "asset_normalization"),
    ],
)
def test_parity_rejects_every_authoritative_drift_and_consumer_operation(path, value, code):
    authority = _authority()
    browser = build_parity_payload(authority, "browser")
    engine = build_parity_payload(authority, "godot").to_dict()
    _set_path(engine, path, value)

    report = run_parity_gate(authority, (browser, engine))

    assert report.passed is False
    assert code in {issue.code for issue in report.issues}
    with pytest.raises(PublicationBlocked, match="compiler parity failed"):
        report.require_passed()


def test_concurrent_compiler_manifest_is_adapted_only_after_exact_contract_checks():
    authority = _authority()
    contract = authority.contract
    manifest = {
        "contract_hash": contract.contract_hash,
        "plan_revision": contract.plan_revision,
        "camera_hash": contract.camera_hash,
        "room_shell_ref": contract.room_shell_ref,
        "instances": [item.to_dict() for item in contract.instances],
        "lighting": contract.lighting.to_dict(),
        "navigation": contract.navigation.to_dict() if contract.navigation is not None else None,
        "authority": {
            "source": "one_canonical_world_contract",
            "transform_policy": "exact_no_clamp_rescale_offset_or_normalization",
        },
    }

    payload = adapt_compiler_manifest(authority, "godot", manifest)

    assert payload.camera == authority.camera.to_dict()
    assert payload.room_dimensions == authority.room_dimensions.to_dict()
    assert payload.derivation["asset_normalization_counts"] == {"table-uuid": 1}
    drifted = copy.deepcopy(manifest)
    drifted["instances"][0]["position"]["x"] += 0.01
    with pytest.raises(InvalidCompilerPayload, match="instances"):
        adapt_compiler_manifest(authority, "godot", drifted)


def test_selection_rejects_implicit_browser_duplicate_and_unavailable_engine(tmp_path):
    authority = _authority()
    selector = CompilerSelector({"browser": _FakeCompiler("browser", [])})

    with pytest.raises(CompilerSelectionError, match="select at least one"):
        selector.compile_selected(authority, [], tmp_path)
    with pytest.raises(CompilerSelectionError, match="compiled automatically"):
        selector.compile_selected(authority, ["browser"], tmp_path)
    with pytest.raises(CompilerSelectionError, match="unavailable"):
        selector.compile_selected(authority, ["upbge"], tmp_path)


def test_authority_rejects_camera_inference_and_second_normalization():
    valid = _authority()
    wrong_camera = CameraContract(position=(0.0, 1.0, 0.0), target=(0.0, 1.0, -1.0))

    with pytest.raises(InvalidCompilerPayload, match="CameraContract"):
        CompilerAuthority(
            valid.contract, wrong_camera, valid.room_dimensions,
            valid.asset_normalization_counts,
        )
    with pytest.raises(InvalidCompilerPayload, match="exactly once"):
        CompilerAuthority(
            valid.contract, valid.camera, valid.room_dimensions,
            {"table-uuid": 2},
        )


@given(st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=15, deadline=None)
def test_any_distinct_compiled_position_is_rejected(candidate_x):
    """Property: solved transforms permit no consumer-side numeric tolerance."""
    authority = _authority()
    expected_x = authority.contract.instances[0].position.x
    if candidate_x == expected_x:
        return
    browser = build_parity_payload(authority, "browser")
    godot = build_parity_payload(authority, "godot").to_dict()
    godot["instances"][0]["transform"]["position"]["x"] = candidate_x

    report = run_parity_gate(authority, (browser, godot))

    assert not report.passed
    assert any(issue.code == "solved_transform_drift" for issue in report.issues)
