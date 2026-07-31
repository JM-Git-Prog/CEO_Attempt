"""Focused tests for procedural, Plan-derived FinishPass output.

**Validates: Requirements 17.1-17.7, 31.1-31.4, 34.1**
"""

from __future__ import annotations

import pytest

from src.unified_pipeline.finish_pass import FinishPass, FinishPassError
from src.unified_pipeline.models import ArtBible, MetricPlan, PlanRevision


def _art_bible(*exclusions: str, era: str = "1950s diner") -> ArtBible:
    return ArtBible(
        era_rules={"belongs": [f"furnishings typical of {era}"], "excludes": list(exclusions)},
        era_exclusions=tuple(exclusions),
        immutable=True,
    )


def _plan(*, window_sill: bool = True, fixtures: bool = True) -> MetricPlan:
    north = {
        "id": "north",
        "start": (0.0, 0.0, 0.0),
        "end": (4.0, 0.0, 0.0),
        "height": 2.7,
    }
    if fixtures:
        north["finish_fixtures"] = (
            {"id": "outlet-n-1", "kind": "outlet", "parameter": 0.18, "elevation_m": 0.30},
            {"id": "switch-n-1", "kind": "switch", "parameter": 0.82, "elevation_m": 1.20},
        )
    window = {
        "id": "window-n-1",
        "type": "window",
        "wall": "north",
        "parameter": 0.70,
        "width": 1.0,
        "height": 1.1,
    }
    if window_sill:
        window["sill_height"] = 0.9
    return MetricPlan(
        room_dimensions=(4.0, 3.0, 2.7),
        walls=(
            north,
            {"id": "east", "start": (4.0, 0.0, 0.0), "end": (4.0, 3.0, 0.0), "height": 2.7},
            {"id": "south", "start": (4.0, 3.0, 0.0), "end": (0.0, 3.0, 0.0), "height": 2.7},
            {"id": "west", "start": (0.0, 3.0, 0.0), "end": (0.0, 0.0, 0.0), "height": 2.7},
        ),
        openings=(
            {"id": "door-n-1", "type": "door", "wall": "north", "parameter": 0.35, "width": 0.9, "height": 2.1},
            window,
        ),
        revisions=(PlanRevision(revision=3, changed="approved", reason="human approval", plan_hash="plan-hash-3"),),
        template_id="kitchen",
    )


def _run(plan: MetricPlan | None = None, bible: ArtBible | None = None):
    return FinishPass().run(
        plan or _plan(),
        bible or _art_bible(),
        approved_plan_revision=3,
    )


class TestPrimitiveGeneration:
    def test_generates_only_allowed_primitive_geometry(self):
        result = _run()

        assert result.primitives
        assert {item.geometry for item in result.primitives} == {
            "profile_sweep", "box_extrusion", "quad_decal"
        }
        assert result.uses_csg is False
        assert all("csg" not in item.geometry and "boolean" not in item.geometry for item in result.primitives)

    def test_baseboards_are_profile_sweeps_split_around_door(self):
        baseboards = [item for item in _run().primitives if item.kind == "baseboard"]
        north = [item for item in baseboards if item.parent_wall_id == "north"]

        assert len(baseboards) == 5
        assert len(north) == 2
        assert all(item.geometry == "profile_sweep" and item.profile_m for item in baseboards)
        assert north[0].path[-1].parameter <= north[1].path[0].parameter

    def test_door_and_window_frames_use_box_extrusions(self):
        primitives = _run().primitives
        door_frames = [item for item in primitives if item.kind == "door_frame"]
        window_frames = [item for item in primitives if item.kind == "window_frame"]

        assert len(door_frames) == 3
        assert len(window_frames) == 4
        assert all(item.geometry == "box_extrusion" for item in door_frames + window_frames)
        assert {item.parent_opening_id for item in door_frames} == {"door-n-1"}
        assert {item.parent_opening_id for item in window_frames} == {"window-n-1"}

    def test_casing_sweeps_opening_perimeters(self):
        casing = [item for item in _run().primitives if item.kind == "casing"]

        assert len(casing) == 2
        assert all(item.geometry == "profile_sweep" and item.profile_m for item in casing)
        door = next(item for item in casing if item.parent_opening_id == "door-n-1")
        window = next(item for item in casing if item.parent_opening_id == "window-n-1")
        assert len(door.path) == 4
        assert window.path[0] == window.path[-1]

    def test_electrical_decals_use_only_approved_wall_parameters_and_heights(self):
        electrical = [item for item in _run().primitives if item.kind in {"outlet", "switch"}]

        assert [(item.source_detail_id, item.path[0].parameter, item.path[0].elevation_m) for item in electrical] == [
            ("outlet-n-1", 0.18, 0.30),
            ("switch-n-1", 0.82, 1.20),
        ]
        assert all(item.geometry == "quad_decal" for item in electrical)
        assert {item.style for item in electrical} == {"period_duplex", "period_toggle"}

    def test_every_placement_remains_parent_wall_parameterized(self):
        for item in _run().primitives:
            assert item.parent_wall_id in {"north", "east", "south", "west"}
            assert item.authority_claim == "derived_only"
            assert item.path
            assert all(0.0 <= point.parameter <= 1.0 for point in item.path)

    def test_ids_are_stable_for_identical_approved_input(self):
        first = _run()
        second = _run()

        assert [item.id for item in first.primitives] == [item.id for item in second.primitives]
        assert len({item.id for item in first.primitives}) == len(first.primitives)
        assert first.plan_revision == 3
        assert first.plan_hash == "plan-hash-3"


class TestOmitRatherThanHallucinate:
    def test_window_without_approved_sill_height_is_omitted(self):
        result = _run(_plan(window_sill=False))

        assert not any(item.kind == "window_frame" for item in result.primitives)
        assert not any(item.parent_opening_id == "window-n-1" for item in result.primitives)
        assert any("sill height is unknown" in reason for reason in result.omitted_details)

    def test_no_electrical_is_invented_without_plan_directives(self):
        result = _run(_plan(fixtures=False))

        assert not any(item.kind in {"outlet", "switch"} for item in result.primitives)
        assert "electrical fixtures omitted: no approved parent-wall directives" in result.omitted_details

    def test_unknown_era_omits_electrical_details(self):
        result = _run(bible=_art_bible(era="unspecified eclectic period"))

        assert not any(item.kind in {"outlet", "switch"} for item in result.primitives)
        assert sum("era is not safely classifiable" in reason for reason in result.omitted_details) == 2

    def test_art_bible_exclusions_remove_outlets_and_switches(self):
        bible = _art_bible("no electrical outlets visible", "no modern light switches")
        result = _run(bible=bible)

        assert not any(item.kind in {"outlet", "switch"} for item in result.primitives)
        assert sum("excluded by ArtBible" in reason for reason in result.omitted_details) == 2

    def test_era_inappropriate_plan_height_is_omitted_not_rewritten(self):
        plan = _plan()
        walls = [dict(wall) for wall in plan.walls]
        walls[0]["finish_fixtures"] = (
            {"id": "outlet-high", "kind": "outlet", "parameter": 0.2, "elevation_m": 1.8},
        )
        changed = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=tuple(walls),
            openings=plan.openings,
            revisions=plan.revisions,
            template_id=plan.template_id,
        )

        result = _run(changed)

        assert not any(item.source_detail_id == "outlet-high" for item in result.primitives)
        assert any("conflicts with ArtBible era profile" in reason for reason in result.omitted_details)


class TestAuthorityAndDeferredInterfaces:
    def test_rejects_missing_stale_or_unhashed_approval(self):
        finish = FinishPass()
        with pytest.raises(FinishPassError, match="nonzero Plan revision"):
            finish.run(MetricPlan(walls=_plan().walls), _art_bible(), approved_plan_revision=1)
        with pytest.raises(FinishPassError, match="match the latest"):
            finish.run(_plan(), _art_bible(), approved_plan_revision=2)
        unhashed = MetricPlan(
            walls=_plan().walls,
            openings=_plan().openings,
            revisions=(PlanRevision(revision=3),),
        )
        with pytest.raises(FinishPassError, match="plan hash"):
            finish.run(unhashed, _art_bible(), approved_plan_revision=3)

    def test_rejects_opening_outside_approved_parent_wall(self):
        plan = _plan()
        invalid = dict(plan.openings[0])
        invalid["parameter"] = 0.02
        changed = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=plan.walls,
            openings=(invalid,),
            revisions=plan.revisions,
        )

        with pytest.raises(FinishPassError, match="outside"):
            _run(changed)

    def test_post_mvp_finish_interfaces_are_defined_and_inert(self):
        finish = FinishPass()
        plan = _plan()
        bible = _art_bible()

        assert finish.crown_molding(plan, bible) == ()
        assert finish.wainscoting(plan, bible) == ()
        assert finish.vent_covers(plan, bible) == ()

    def test_result_reports_plan_as_only_spatial_authority(self):
        result = _run()

        assert result.spatial_authority == "approved_normalized_metric_plan"
        assert result.authority_claim == "derived_only"
        payload = result.to_dict()
        assert payload["uses_csg"] is False
        assert payload["plan_revision"] == 3
