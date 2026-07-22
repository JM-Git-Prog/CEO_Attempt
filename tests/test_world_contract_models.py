from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.world_contract import (
    BodyMode,
    CameraBinding,
    Dimensions,
    ExportPolicy,
    InteractionIntent,
    MaterialIntent,
    Mount,
    PhysicsIntent,
    PhysicsPolicy,
    RoomShell,
    Transform,
    Vector3,
    Wall,
    WorldInstance,
    WorldLight,
    WorldOpening,
)


def component_models():
    material = MaterialIntent(id="material:oak", base_color="#8B5A2B")
    room = RoomShell(
        dimensions=Dimensions(width_m=6.0, height_m=3.0, depth_m=4.0),
        floor_material_id=material.id,
        wall_material_id=material.id,
        ceiling_material_id=material.id,
    )
    opening = WorldOpening(
        id="opening:south-door",
        kind="door",
        wall=Wall.SOUTH,
        width_m=0.9,
        height_m=2.1,
        physics_intent_id="physics:south-door",
    )
    instance = WorldInstance(
        id="instance:table",
        name="Dining table",
        category="furniture",
        mount=Mount.FLOOR,
        transform=Transform(position_m=Vector3(x=0.5, y=0.0, z=-0.25)),
        dimensions=Dimensions(width_m=1.8, height_m=0.75, depth_m=0.9),
        material_id=material.id,
        physics_intent_id="physics:table",
        primitive_shape="box",
    )
    light = WorldLight(
        id="light:pendant",
        name="Pendant",
        light_type="point",
        position_m=Vector3(x=0.0, y=2.4, z=0.0),
        color="#FFE0B0",
        fixture_instance_id=instance.id,
    )
    camera = CameraBinding(
        id="camera:canon",
        source_schema_version="camera-lock/v1",
        position_m=Vector3(x=3.0, y=1.6, z=3.0),
        target_m=Vector3(x=0.0, y=1.1, z=0.0),
        up=Vector3(x=0.0, y=1.0, z=0.0),
        vertical_fov_deg=55.0,
        aspect_ratio=4 / 3,
        image_width_px=1024,
        image_height_px=768,
        near_plane_m=0.05,
        far_plane_m=100.0,
    )
    physics_intent = PhysicsIntent(
        id="physics:table",
        subject_id=instance.id,
        body_mode=BodyMode.STATIC,
    )
    physics_policy = PhysicsPolicy(intents=(physics_intent,))
    interaction = InteractionIntent(
        id="interaction:door",
        kind="door",
        subject_id=opening.id,
        parameters={"open_angle_deg": 90.0},
    )
    exports = ExportPolicy(targets=("glb", "godot"))
    return (
        material,
        room,
        opening,
        instance,
        light,
        camera,
        physics_intent,
        physics_policy,
        interaction,
        exports,
    )


def test_requested_component_models_have_explicit_v1_discriminators():
    versions = [model.schema_version for model in component_models()]

    assert versions == [
        "material-intent/v1",
        "room-shell/v1",
        "world-opening/v1",
        "world-instance/v1",
        "world-light/v1",
        "camera-binding/v1",
        "physics-intent/v1",
        "physics-policy/v1",
        "interaction-intent/v1",
        "export-policy/v1",
    ]


def test_models_use_domain_coordinates_and_engine_neutral_values():
    _, room, opening, instance, light, camera, _, physics, interaction, exports = (
        component_models()
    )

    assert room.dimensions == Dimensions(width_m=6.0, height_m=3.0, depth_m=4.0)
    assert opening.wall is Wall.SOUTH
    assert instance.transform.position_m == Vector3(x=0.5, y=0.0, z=-0.25)
    assert light.position_m.y == 2.4
    assert camera.source_schema_version == "camera-lock/v1"
    assert physics.gravity_m_s2 == Vector3(x=0.0, y=-9.81, z=0.0)
    assert interaction.parameters == {"open_angle_deg": 90.0}
    assert tuple(target.value for target in exports.targets) == ("glb", "godot")


@pytest.mark.parametrize("model", component_models())
def test_component_models_reject_unknown_versions_and_are_immutable(model):
    payload = model.model_dump(mode="json")
    payload["schema_version"] = "unsupported/v2"

    with pytest.raises(ValidationError):
        type(model).model_validate(payload)
    with pytest.raises(ValidationError, match="frozen"):
        model.schema_version = "unsupported/v2"
