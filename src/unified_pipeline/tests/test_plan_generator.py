"""Tests for MetricPlanGenerator — constrained template selection.

Validates:
- Template selection from Brief.room_purpose
- Constrained parameterization (dimensions within bounds)
- Revision tracking with provenance
- Relative parameterization (openings reference wall by ID + parameter 0..1)
- Fallback behavior when LLM is unavailable

Requirements: 5.1, 5.2, 5.5, 5.6
"""

from __future__ import annotations

import asyncio
import os
import pytest

from src.unified_pipeline.models import (
    Atmosphere,
    Brief,
    Era,
    GameConcept,
    ManifestObject,
    MetricPlan,
    Palette,
    PlanRevision,
    RealCapability,
)
from src.unified_pipeline.plan_generator import (
    MetricPlanGenerator,
    ROOM_TEMPLATES,
    select_template,
    _compute_plan_hash,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _danny_kitchen_brief() -> Brief:
    """Danny's kitchenette — canonical test Brief."""
    return Brief(
        room_purpose="a small, warm kitchen",
        atmosphere=Atmosphere(
            mood="warm and cozy",
            lighting_direction="warm ambient",
            time_of_day="evening",
        ),
        era=Era(period="1950s diner", style_exclusions=()),
        palette=Palette(
            primary="warm white",
            accent="chrome",
            material_finishes=("formica", "chrome"),
        ),
        object_manifest=(
            ManifestObject(id="obj-1", name="round table", role="table", count=1, material_hint="wood"),
            ManifestObject(id="obj-2", name="chair", role="seating", count=2, material_hint="wood"),
            ManifestObject(id="obj-3", name="counter", role="counter", count=1, material_hint="formica"),
            ManifestObject(id="obj-4", name="coffee maker", role="appliance", count=1, material_hint="metal"),
            ManifestObject(id="obj-5", name="window", role="window", count=1, is_architectural=True),
        ),
        game_concept=GameConcept(
            theme="breakfast rush",
            mechanics="serve customers",
            scoring="tips earned",
            win_condition="all served",
        ),
        real_capabilities=(
            RealCapability(tool_type="timer", surface_binding="counter", read_only_v1=True),
        ),
        success_criteria="A warm kitchenette with a round table and rain outside.",
        provenance={"source": "test"},
    )


def _living_room_brief() -> Brief:
    """A living room Brief for template selection testing."""
    return Brief(
        room_purpose="cozy living room for family evenings",
        atmosphere=Atmosphere(mood="relaxed", lighting_direction="warm", time_of_day="evening"),
        era=Era(period="modern"),
        palette=Palette(primary="cream", accent="navy"),
        object_manifest=(
            ManifestObject(id="lr-1", name="sofa", role="seating", count=1),
            ManifestObject(id="lr-2", name="coffee table", role="surface", count=1),
        ),
        success_criteria="A comfortable living space.",
    )


def _studio_brief() -> Brief:
    """A studio Brief for template selection testing."""
    return Brief(
        room_purpose="open-plan creative studio",
        atmosphere=Atmosphere(mood="energetic", lighting_direction="bright", time_of_day="morning"),
        era=Era(period="industrial"),
        palette=Palette(primary="concrete", accent="rust"),
        object_manifest=(
            ManifestObject(id="st-1", name="drafting table", role="workspace", count=1),
            ManifestObject(id="st-2", name="easel", role="workspace", count=1),
        ),
        success_criteria="An inspiring creative space.",
    )


# ─── Template Selection Tests ──────────────────────────────────────────────────


class TestTemplateSelection:
    """Req 5.1: constrained template selection from Brief."""

    def test_kitchen_brief_selects_kitchen_template(self):
        brief = _danny_kitchen_brief()
        template_id = select_template(brief)
        assert template_id == "kitchen"

    def test_living_room_brief_selects_living_room_template(self):
        brief = _living_room_brief()
        template_id = select_template(brief)
        assert template_id == "living_room"

    def test_studio_brief_selects_studio_template(self):
        brief = _studio_brief()
        template_id = select_template(brief)
        assert template_id == "studio"

    def test_unknown_purpose_selects_generic(self):
        brief = Brief(room_purpose="mysterious void")
        template_id = select_template(brief)
        assert template_id == "generic"

    def test_all_templates_have_required_fields(self):
        for tid, template in ROOM_TEMPLATES.items():
            assert "base_dimensions" in template, f"{tid} missing base_dimensions"
            assert "min_dimensions" in template, f"{tid} missing min_dimensions"
            assert "max_dimensions" in template, f"{tid} missing max_dimensions"
            assert "default_openings" in template, f"{tid} missing default_openings"
            assert len(template["base_dimensions"]) == 3
            assert len(template["min_dimensions"]) == 3
            assert len(template["max_dimensions"]) == 3

    def test_template_library_has_5_templates(self):
        assert len(ROOM_TEMPLATES) == 5
        expected = {"kitchen", "living_room", "bedroom", "studio", "generic"}
        assert set(ROOM_TEMPLATES.keys()) == expected


# ─── Plan Generation Tests (fallback/deterministic) ────────────────────────────


class TestPlanGeneration:
    """Req 5.1, 5.2: MetricPlan generation with constrained templates."""

    @pytest.fixture
    def generator(self):
        # Force mock LLM so tests are deterministic
        os.environ["ALLOW_MOCK_LLM"] = "1"
        return MetricPlanGenerator(timeout=5.0)

    def test_generate_produces_metric_plan(self, generator):
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        assert isinstance(plan, MetricPlan)

    def test_generated_plan_has_room_dimensions(self, generator):
        """Req 5.2: room dimensions in meters."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        w, d, h = plan.room_dimensions
        assert w > 0 and d > 0 and h > 0
        # Kitchen template bounds: width 3-5, depth 3-5, height 2.4-3.0
        assert 3.0 <= w <= 5.0
        assert 3.0 <= d <= 5.0
        assert 2.4 <= h <= 3.0

    def test_generated_plan_has_walls(self, generator):
        """Req 5.2: wall positions."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        assert len(plan.walls) == 4  # rectangular room

    def test_generated_plan_has_openings(self, generator):
        """Req 5.2: door/window openings parameterized 0..1."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        assert len(plan.openings) >= 1
        for opening in plan.openings:
            assert "type" in opening
            assert opening["type"] in ("door", "window")
            assert "wall" in opening
            assert "parameter" in opening
            # Parameter must be 0..1 (Req 5.6)
            assert 0.0 <= opening["parameter"] <= 1.0

    def test_generated_plan_has_template_id(self, generator):
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        assert plan.template_id == "kitchen"


# ─── Revision Tracking Tests ───────────────────────────────────────────────────


class TestRevisionTracking:
    """Req 5.5: every Plan revision traceable."""

    @pytest.fixture
    def generator(self):
        os.environ["ALLOW_MOCK_LLM"] = "1"
        return MetricPlanGenerator(timeout=5.0)

    def test_initial_plan_has_revision_1(self, generator):
        """First generation is rev-1."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        assert len(plan.revisions) == 1
        assert plan.revisions[0].revision == 1

    def test_initial_revision_has_provenance(self, generator):
        """Req 5.5: revision records what changed and why."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        rev = plan.revisions[0]
        assert rev.changed != ""
        assert rev.reason != ""
        assert rev.plan_hash != ""

    def test_revise_increments_revision_number(self, generator):
        """Corrections create rev-2+."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))

        revised = generator.revise(
            plan,
            changed="room_dimensions",
            reason="validation failure: room too narrow",
            room_dimensions=(4.0, 3.5, 2.7),
        )

        assert len(revised.revisions) == 2
        assert revised.revisions[0].revision == 1
        assert revised.revisions[1].revision == 2

    def test_revise_preserves_original_revisions(self, generator):
        """All revision history is kept."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        original_rev = plan.revisions[0]

        revised = generator.revise(
            plan,
            changed="openings",
            reason="opening too close to corner",
        )

        assert revised.revisions[0] == original_rev
        assert revised.revisions[1].changed == "openings"
        assert revised.revisions[1].reason == "opening too close to corner"

    def test_revise_updates_plan_hash(self, generator):
        """Each revision has a distinct hash."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))

        revised = generator.revise(
            plan,
            changed="room_dimensions",
            reason="enlarge room",
            room_dimensions=(5.0, 4.0, 2.8),
        )

        assert revised.revisions[1].plan_hash != ""
        # Hash changes when content changes
        assert revised.revisions[1].plan_hash != plan.revisions[0].plan_hash

    def test_multiple_revisions(self, generator):
        """Can create rev-3, rev-4, etc."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))

        rev2 = generator.revise(plan, "dims", "too small", room_dimensions=(4.5, 3.5, 2.7))
        rev3 = generator.revise(rev2, "openings", "add window")

        assert len(rev3.revisions) == 3
        assert rev3.revisions[2].revision == 3


# ─── Relative Parameterization Tests ──────────────────────────────────────────


class TestRelativeParameterization:
    """Req 5.6: fixtures reference parent wall by ID and parameter 0..1."""

    @pytest.fixture
    def generator(self):
        os.environ["ALLOW_MOCK_LLM"] = "1"
        return MetricPlanGenerator(timeout=5.0)

    def test_openings_reference_wall_by_id(self, generator):
        """Openings specify which wall they belong to."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        for opening in plan.openings:
            assert "wall" in opening
            assert opening["wall"] in ("north", "south", "east", "west")

    def test_opening_position_is_0_to_1(self, generator):
        """Position along wall is parameter 0..1, not absolute coordinate."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        for opening in plan.openings:
            param = opening["parameter"]
            assert 0.0 <= param <= 1.0

    def test_plan_dimensions_are_meters(self, generator):
        """Room dimensions are in meters (plausible residential range)."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))
        w, d, h = plan.room_dimensions
        # Residential plausibility checks
        assert 1.5 <= w <= 10.0, f"Width {w}m implausible"
        assert 1.5 <= d <= 10.0, f"Depth {d}m implausible"
        assert 2.0 <= h <= 6.0, f"Height {h}m implausible"


# ─── Danny's Kitchenette Integration Test ─────────────────────────────────────


class TestDannyKitchenette:
    """Integration test with the canonical proving-ground prompt."""

    @pytest.fixture
    def generator(self):
        os.environ["ALLOW_MOCK_LLM"] = "1"
        return MetricPlanGenerator(timeout=5.0)

    def test_danny_kitchen_plan_is_plausible(self, generator):
        """Danny's kitchenette should produce a plausible kitchen plan."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))

        # Should select kitchen template
        assert plan.template_id == "kitchen"

        # Should have openings (doors and/or windows)
        assert len(plan.openings) >= 1

        # Check opening structure — all must have type, wall, parameter
        for opening in plan.openings:
            assert "type" in opening
            assert "wall" in opening
            assert "parameter" in opening

        # Should have object placements
        assert len(plan.object_placements) > 0

        # Should have circulation paths
        assert len(plan.circulation_paths) > 0

    def test_plan_serializes_round_trip(self, generator):
        """MetricPlan should serialize and deserialize correctly."""
        brief = _danny_kitchen_brief()
        plan = asyncio.run(generator.generate(brief))

        data = plan.to_dict()
        restored = MetricPlan.from_dict(data)

        assert restored.room_dimensions == plan.room_dimensions
        assert restored.template_id == plan.template_id
        assert len(restored.revisions) == len(plan.revisions)
        assert len(restored.walls) == len(plan.walls)
