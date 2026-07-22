from __future__ import annotations

import pytest

from src.composition_sidecar import qualify_v11_composition
from src.floor_plan.models import FloorPlanV11
from src.floor_plan.solver import solve_explicit_plan
from src.floor_plan.validator import validate_floor_plan
from src.orchestrator.mock_llm import _mock_floor_plan_v11


def _compact_plan() -> FloorPlanV11:
    raw = _mock_floor_plan_v11()
    for relation in raw["relationships"]:
        parameters = relation.get("parameters_m", {})
        if "distribution_span_m" not in parameters:
            continue
        parameters["distribution_span_m"] = (
            1.5 if relation["subject_id"].startswith("stool_") else 1.2
        )
    return solve_explicit_plan(FloorPlanV11.model_validate(raw))


def _policy(**updates) -> dict:
    policy = {
        "image_width": 1024,
        "image_height": 768,
        "safe_margin_ratio": 0.005,
        "minimum_inset_m": 0.22,
        "inset_offsets_m": [-0.449, -0.4, -0.35, -0.3, -0.2, 0.0],
        "target_x_offsets_m": [0.0, -0.5, 0.5, -1.0, -1.5, -2.0],
        "target_y_offsets_m": [0.0, -0.3, 0.3, -0.6, 0.6, -0.9, -1.2],
        "target_z_offsets_m": [0.0, 0.5, 1.0, 1.5, 2.0],
        "require_openings": False,
    }
    policy.update(updates)
    return policy


def test_full_rotated_bounds_fit_with_fixed_corner_and_fov():
    source = _compact_plan()
    source_geometry = [item.model_dump() for item in source.items]

    adjusted, evidence = qualify_v11_composition(source, _policy())

    assert evidence.status == "accepted"
    assert evidence.camera_corner == "southeast"
    assert evidence.vertical_fov_deg == 55.0
    assert adjusted.camera.fov_deg == source.camera_intent.fov_deg == 55.0
    assert adjusted.camera.x > 0 and adjusted.camera.z < 0
    assert evidence.selected is not None
    assert evidence.selected.inset_m >= 0.22
    camera_validation = validate_floor_plan(adjusted)
    assert not any(
        issue.code == "camera_out_of_bounds" for issue in camera_validation.blockers
    )
    assert [item.model_dump() for item in adjusted.items] == source_geometry
    assert evidence.selected.clipped_ids == ()
    assert len(evidence.selected.projected_bounds) == len(source.items)
    assert all(bound.fully_inside for bound in evidence.selected.projected_bounds)
    assert all(len(bound.corners) == 8 for bound in evidence.selected.projected_bounds)


def test_candidate_order_and_hash_are_deterministic():
    plan = _compact_plan()

    first_plan, first = qualify_v11_composition(plan, _policy())
    second_plan, second = qualify_v11_composition(plan, _policy())

    assert first == second
    assert first.evidence_sha256 == second.evidence_sha256
    assert first.candidate_set_sha256 == second.candidate_set_sha256
    assert first.selected.index == second.selected.index
    assert first_plan.camera == second_plan.camera


def test_impossible_framing_returns_structured_clipped_bounds_without_mutation():
    plan = _compact_plan()
    original_camera = plan.camera.model_copy(deep=True)
    oversized = plan.items[0].model_copy(update={"width": 12.0, "depth": 8.0})
    impossible = plan.model_copy(update={"items": [oversized, *plan.items[1:]]})

    unchanged, evidence = qualify_v11_composition(
        impossible,
        _policy(
            inset_offsets_m=[0.0], target_x_offsets_m=[0.0],
            target_y_offsets_m=[0.0], target_z_offsets_m=[0.0],
        ),
    )

    assert evidence.status == "rejected"
    assert evidence.selected is None
    assert evidence.best_rejected is not None
    assert oversized.id in evidence.best_rejected.clipped_ids
    rejected = next(
        value for value in evidence.best_rejected.projected_bounds
        if value.instance_id == oversized.id
    )
    assert not rejected.fully_inside
    assert any(not corner.inside for corner in rejected.corners)
    assert unchanged.camera == original_camera


def test_openings_use_deterministic_wall_bound_samples_when_required():
    plan = _compact_plan()
    _adjusted, evidence = qualify_v11_composition(
        plan,
        _policy(
            require_openings=True,
            inset_offsets_m=[-0.449], target_x_offsets_m=[-1.0],
            target_y_offsets_m=[-0.6], target_z_offsets_m=[1.0],
        ),
    )

    candidate = evidence.selected or evidence.best_rejected
    opening_bounds = [
        value for value in candidate.projected_bounds if value.instance_kind == "opening"
    ]
    assert [value.instance_id for value in opening_bounds] == sorted(
        opening.id for opening in plan.openings
    )
    assert all(len(value.corners) == 4 for value in opening_bounds)


def test_rotation_changes_projected_bounds_not_instance_center_only():
    plan = _compact_plan()
    base_policy = _policy(
        inset_offsets_m=[-0.449], target_x_offsets_m=[-1.0],
        target_y_offsets_m=[-0.6], target_z_offsets_m=[1.0],
    )
    _base_plan, base = qualify_v11_composition(plan, base_policy)
    items = [
        item.model_copy(update={"rotation_deg": 45.0, "width": 0.8, "depth": 0.2})
        if item.id == "stool_1" else item
        for item in plan.items
    ]
    rotated_plan = plan.model_copy(update={"items": items})
    _rotated_plan, rotated = qualify_v11_composition(rotated_plan, base_policy)

    base_candidate = base.selected or base.best_rejected
    rotated_candidate = rotated.selected or rotated.best_rejected
    base_bounds = next(v for v in base_candidate.projected_bounds if v.instance_id == "stool_1")
    rotated_bounds = next(v for v in rotated_candidate.projected_bounds if v.instance_id == "stool_1")
    assert (base_bounds.minimum_x, base_bounds.maximum_x) != (
        rotated_bounds.minimum_x, rotated_bounds.maximum_x
    )


def test_v11_rejected_composition_cannot_reach_canon(tmp_path, monkeypatch):
    import asyncio
    import src.pipeline as pipeline
    from src.models import SceneConcept

    monkeypatch.setattr(pipeline, "OUTPUT_BASE", tmp_path)
    builder = pipeline.WorldBuilder(session_id="composition-rejected", interface_version=11)
    builder.session.scene_concept = SceneConcept(
        era="1950s", mood="rainy", palette="mint",
        architecture_notes="diner", key_objects=["counter"],
        lighting_notes="pendants", image_prompt="diner",
    )
    builder.session.floor_plan = _compact_plan()
    builder.session.floor_plan_approved = True
    builder.session.composition_evidence = {"status": "rejected", "best_rejected": {}}
    builder.session.camera_contract = None

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Canon provider must not run after composition rejection")

    monkeypatch.setattr(pipeline, "generate_canon_image", forbidden)
    monkeypatch.setattr(pipeline, "generate_conditioned_canon", forbidden)
    with pytest.raises(RuntimeError, match="full-bounds composition"):
        asyncio.run(builder.step_generate_image())
