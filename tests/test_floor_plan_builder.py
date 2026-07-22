from __future__ import annotations

import asyncio

import pytest

from src.floor_plan.builder import build_floor_plan
from src.floor_plan.models import FloorPlanV11
from src.models import SceneConcept
from src.orchestrator.mock_llm import _mock_floor_plan_v11


def test_v11_semantic_relation_policy_solves_typed_authority(monkeypatch):
    raw_plan = _mock_floor_plan_v11()

    async def fake_generate(system, user, **kwargs):
        assert "V11 EXPLICIT-INTENT EXTENSION" in system
        assert "floor_plan_v11_json_schema" in user
        return raw_plan

    def forbidden_retained_solver(*args, **kwargs):
        raise AssertionError("V11 must not invoke the retained keyword solver")

    monkeypatch.setattr("src.floor_plan.builder.generate_json", fake_generate)
    monkeypatch.setattr("src.floor_plan.solver.solve_plan", forbidden_retained_solver)
    concept = SceneConcept(
        era="1950s", mood="warm", palette="mint and chrome",
        architecture_notes="diner", key_objects=["counter"],
        lighting_notes="pendants", image_prompt="A diner interior.",
    )

    plan, _warnings, report = asyncio.run(build_floor_plan(
        "A typed semantic layout", concept,
        placement_policy="explicit-semantic-relations/v1",
        strict_validation=True,
    ))

    assert isinstance(plan, FloorPlanV11)
    assert report.valid, report.model_dump()
    by_id = {item.id: item for item in plan.items}
    counter = by_id["counter_1"]
    assert counter.x == pytest.approx(0.0)
    assert counter.z > 0.0

    stools = [by_id[f"stool_{index}"] for index in range(1, 5)]
    assert [item.x for item in stools] == pytest.approx([-1.5, -0.5, 0.5, 1.5])
    assert len({item.z for item in stools}) == 1
    assert stools[0].z < counter.z

    lights = [by_id[f"light_{index}"] for index in range(1, 4)]
    assert [item.x for item in lights] == pytest.approx([-0.65, 0.0, 0.65])
    assert all(item.mount == "ceiling" for item in lights)
    assert all(item.z == pytest.approx(counter.z) for item in lights)
    assert all(item.elevation == pytest.approx(2.3) for item in lights)

    door, window = plan.openings
    assert door.wall == "west" and door.offset > 0.0
    assert window.wall == "south" and window.offset == pytest.approx(0.0)
    assert plan.camera.x > 0.0 and plan.camera.z < 0.0
    assert plan.camera.target_z == pytest.approx(counter.z)


def test_world_session_round_trip_preserves_v11_plan_intent():
    from src.models import WorldSession
    from src.workflow_provenance import profile_for

    plan = FloorPlanV11.model_validate(_mock_floor_plan_v11())
    profile = profile_for(11)
    session = WorldSession(
        session_id="typedplan", interface_version=11,
        workflow_profile_id=profile["id"], workflow_profile=profile,
        floor_plan=plan,
    )

    restored = WorldSession.model_validate_json(session.model_dump_json())
    assert isinstance(restored.floor_plan, FloorPlanV11)
    assert restored.floor_plan.relationships == plan.relationships
    assert restored.floor_plan.opening_intents == plan.opening_intents
    assert restored.floor_plan.camera_intent == plan.camera_intent


def test_v11_missing_redundant_base_fields_complete_from_typed_intent(monkeypatch):
    complete = _mock_floor_plan_v11()
    incomplete = {
        key: value for key, value in complete.items() if key not in {"name", "camera"}
    }
    incomplete["opening_intents"] = [
        {
            "id": intent["opening_id"],
            "placement": intent["placement"],
            **({"corner": intent["corner"]} if intent.get("corner") else {}),
        }
        for intent in complete["opening_intents"]
    ]
    calls: list[str] = []

    async def fake_generate(system, user, **kwargs):
        calls.append(user)
        return incomplete

    monkeypatch.setattr("src.floor_plan.builder.generate_json", fake_generate)
    concept = SceneConcept(
        era="1950s", mood="warm", palette="mint and chrome",
        architecture_notes="diner", key_objects=["counter"],
        lighting_notes="pendants", image_prompt="A diner interior.",
    )

    plan, _warnings, report = asyncio.run(build_floor_plan(
        "A typed semantic layout", concept,
        placement_policy="explicit-semantic-relations/v1",
        strict_validation=True,
    ))

    assert len(calls) == 1
    assert plan.name == concept.era
    assert plan.camera.x > 0.0 and plan.camera.z < 0.0
    assert report.valid


def test_v11_invalid_semantic_intent_gets_one_bounded_repair(monkeypatch):
    complete = _mock_floor_plan_v11()
    incomplete = dict(complete)
    incomplete["relationships"] = []
    calls: list[str] = []

    async def fake_generate(system, user, **kwargs):
        calls.append(user)
        return incomplete if len(calls) == 1 else complete

    monkeypatch.setattr("src.floor_plan.builder.generate_json", fake_generate)
    concept = SceneConcept(
        era="1950s", mood="warm", palette="mint and chrome",
        architecture_notes="diner", key_objects=["counter"],
        lighting_notes="pendants", image_prompt="A diner interior.",
    )

    _plan, _warnings, report = asyncio.run(build_floor_plan(
        "A typed semantic layout", concept,
        placement_policy="explicit-semantic-relations/v1",
        strict_validation=True,
    ))

    assert len(calls) == 2
    assert "validation_errors" in calls[1]
    assert "previous_response" in calls[1]
    assert report.valid
