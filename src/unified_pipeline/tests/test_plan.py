"""Tests for Plan generation and validation.

Tests constrained template selection, validation rules (closure, overlap,
circulation), revision tracking. Tests Danny's kitchenette dimensions and
object presence are plausible.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.unified_pipeline.plan_generator import (
    MetricPlanGenerator,
    select_template,
    ROOM_TEMPLATES,
    _build_walls_from_dimensions,
)
from src.unified_pipeline.plan_validator import (
    PlanValidator,
    MIN_ROOM_WIDTH,
    MAX_ROOM_HEIGHT,
    MIN_ROOM_HEIGHT,
    MIN_OPENING_CORNER_DIST,
    MIN_CIRCULATION_WIDTH,
)
from src.unified_pipeline.models import (
    Brief,
    MetricPlan,
    PlanRevision,
    Atmosphere,
    Era,
    Palette,
    ManifestObject,
    GameConcept,
    RealCapability,
)


# ---------------------------------------------------------------------------
# Constants and Fixtures
# ---------------------------------------------------------------------------

DANNY_KITCHENETTE_PROMPT = (
    "a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)


def _danny_brief() -> Brief:
    """Create Danny's kitchenette Brief — canonical test input."""
    return Brief(
        room_purpose="cozy breakfast kitchen for quiet mornings",
        atmosphere=Atmosphere(
            mood="warm and intimate",
            lighting_direction="natural from window",
            time_of_day="afternoon",
        ),
        era=Era(
            period="warm traditional",
            style_exclusions=("smart thermostat", "LED strip lighting"),
        ),
        palette=Palette(
            primary="#8B6914",
            accent="#B87333",
            material_finishes=("matte oak", "brushed copper", "cream ceramic"),
        ),
        object_manifest=(
            ManifestObject(name="round table", role="furniture", count=1, material_hint="oak"),
            ManifestObject(name="chair", role="furniture", count=2, material_hint="wood spindle"),
            ManifestObject(name="counter", role="furniture", count=1, material_hint="butcher block", is_architectural=True),
            ManifestObject(name="coffee maker", role="appliance", count=1, material_hint="brushed steel"),
            ManifestObject(name="window", role="architectural", count=1, material_hint="wood frame", is_architectural=True),
        ),
        game_concept=GameConcept(
            theme="cozy morning routine",
            mechanics="brew and serve coffee in order",
            scoring="time-based with style bonus",
            win_condition="perfect cup served before timer",
        ),
        real_capabilities=(
            RealCapability(tool_type="calendar", surface_binding="window", read_only_v1=True),
        ),
        success_criteria="A warm, rain-lit kitchen where everything feels touchable and real",
    )


# Mock LLM response for Danny's kitchenette plan
MOCK_PLAN_LLM_RESPONSE = {
    "template_id": "kitchen",
    "dimensions": {
        "width": 4.0,
        "depth": 3.5,
        "ceiling_height": 2.7,
    },
    "openings": [
        {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.9, "height": 2.1},
        {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
    ],
    "object_placements": [
        {"name": "round table", "x": 0.35, "y": 0.4, "rotation_deg": 0, "width": 0.8, "depth": 0.8, "height": 0.75},
        {"name": "chair", "x": 0.18, "y": 0.4, "rotation_deg": 90, "width": 0.4, "depth": 0.4, "height": 0.85},
        {"name": "chair", "x": 0.52, "y": 0.4, "rotation_deg": 270, "width": 0.4, "depth": 0.4, "height": 0.85},
        {"name": "counter", "x": 0.7, "y": 0.15, "rotation_deg": 0, "width": 1.0, "depth": 0.5, "height": 0.9},
        {"name": "coffee maker", "x": 0.9, "y": 0.15, "rotation_deg": 0, "width": 0.25, "depth": 0.25, "height": 0.4},
    ],
    "circulation_paths": [
        {"from": "door_0", "to": "center", "min_width": 0.6},
    ],
}


@pytest.fixture
def mock_generate_json():
    """Mock generate_json to return plan generation response."""
    async def _mock_gen(system, user, model=None, *, timeout_seconds=None):
        return MOCK_PLAN_LLM_RESPONSE

    with patch("src.unified_pipeline.plan_generator.generate_json", new=_mock_gen):
        yield _mock_gen


@pytest.fixture
def danny_brief():
    return _danny_brief()


@pytest.fixture
def validator():
    return PlanValidator()


# ---------------------------------------------------------------------------
# Test 1: Template selection — constrained to library, not free-form
# ---------------------------------------------------------------------------

class TestConstrainedTemplateSelection:
    """Verify MetricPlanGenerator selects from template library (not free-form).

    **Validates: Requirements 5.1**
    """

    def test_kitchen_selected_for_danny(self, danny_brief):
        """Danny's kitchenette Brief maps to 'kitchen' template."""
        assert select_template(danny_brief) == "kitchen"

    def test_all_templates_have_required_fields(self):
        """Every template in ROOM_TEMPLATES has base, min, max dimensions."""
        for tid, t in ROOM_TEMPLATES.items():
            assert "base_dimensions" in t, f"Template '{tid}' missing base_dimensions"
            assert "min_dimensions" in t, f"Template '{tid}' missing min_dimensions"
            assert "max_dimensions" in t, f"Template '{tid}' missing max_dimensions"
            assert len(t["base_dimensions"]) == 3
            assert len(t["min_dimensions"]) == 3
            assert len(t["max_dimensions"]) == 3

    def test_template_selection_never_returns_unknown(self):
        """select_template always returns a known template ID."""
        brief = Brief(room_purpose="alien spaceship control room")
        result = select_template(brief)
        assert result in ROOM_TEMPLATES

    @pytest.mark.asyncio
    async def test_generated_plan_uses_template_id(self, mock_generate_json, danny_brief):
        """Generated plan carries the selected template_id."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        assert plan.template_id in ROOM_TEMPLATES


# ---------------------------------------------------------------------------
# Test 2: Generated plans have valid dimensions within template ranges
# ---------------------------------------------------------------------------

class TestDimensionsWithinTemplateRanges:
    """Verify generated plan dimensions stay within template bounds.

    **Validates: Requirements 5.2**
    """

    @pytest.mark.asyncio
    async def test_dimensions_within_kitchen_bounds(self, mock_generate_json, danny_brief):
        """Plan dimensions are clamped to kitchen template min/max."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)

        template = ROOM_TEMPLATES["kitchen"]
        min_d = template["min_dimensions"]
        max_d = template["max_dimensions"]
        w, d, h = plan.room_dimensions

        assert min_d[0] <= w <= max_d[0], f"Width {w} not in [{min_d[0]}, {max_d[0]}]"
        assert min_d[1] <= d <= max_d[1], f"Depth {d} not in [{min_d[1]}, {max_d[1]}]"
        assert min_d[2] <= h <= max_d[2], f"Height {h} not in [{min_d[2]}, {max_d[2]}]"

    @pytest.mark.asyncio
    async def test_fallback_uses_template_base_dimensions(self, danny_brief):
        """When LLM fails, fallback uses template base dimensions."""
        from src.orchestrator.llm import LLMError

        async def _fail(*a, **kw):
            raise LLMError("timeout")

        with patch("src.unified_pipeline.plan_generator.generate_json", new=_fail):
            gen = MetricPlanGenerator()
            plan = await gen.generate(danny_brief)

        template = ROOM_TEMPLATES["kitchen"]
        assert plan.room_dimensions == tuple(template["base_dimensions"])


# ---------------------------------------------------------------------------
# Test 3: PlanValidator catches room not closed (walls don't connect)
# ---------------------------------------------------------------------------

class TestValidationRoomClosure:
    """Verify PlanValidator catches rooms that aren't closed.

    **Validates: Requirements 5.3**
    """

    def test_catches_disconnected_walls(self, validator):
        """Walls with gaps between end→start trigger closure violation."""
        # Create walls that don't connect — gap between wall 2 end and wall 3 start
        broken_walls = (
            {"id": "north", "start": (0, 0, 0), "end": (4, 0, 0), "height": 2.7},
            {"id": "east", "start": (4, 0, 0), "end": (4, 3, 0), "height": 2.7},
            {"id": "south", "start": (4, 3, 0), "end": (1, 3, 0), "height": 2.7},  # ends at 1, not 0
            {"id": "west", "start": (0, 3, 0), "end": (0, 0, 0), "height": 2.7},
        )
        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            walls=broken_walls,
            openings=(),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        closure_violations = [v for v in result.violations if v.rule == "room_closure"]
        assert len(closure_violations) >= 1, "Expected closure violation for disconnected walls"

    def test_too_few_walls(self, validator):
        """Fewer than 3 walls always fails closure check."""
        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            walls=(
                {"id": "north", "start": (0, 0, 0), "end": (4, 0, 0), "height": 2.7},
                {"id": "east", "start": (4, 0, 0), "end": (4, 3, 0), "height": 2.7},
            ),
            openings=(),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        closure_violations = [v for v in result.violations if v.rule == "room_closure"]
        assert len(closure_violations) >= 1

    def test_closed_walls_pass(self, validator):
        """Properly connected walls pass closure check."""
        walls = _build_walls_from_dimensions(4.0, 3.0, 2.7)
        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            walls=walls,
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        closure_violations = [v for v in result.violations if v.rule == "room_closure"]
        assert len(closure_violations) == 0


# ---------------------------------------------------------------------------
# Test 4: PlanValidator catches objects overlapping
# ---------------------------------------------------------------------------

class TestValidationObjectOverlap:
    """Verify PlanValidator detects overlapping objects.

    **Validates: Requirements 5.3**
    """

    def test_identical_position_detected(self, validator):
        """Two objects at the same position are detected as overlapping."""
        plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(
                {"name": "table", "x": 2.0, "y": 2.0, "width": 1.0, "depth": 1.0},
                {"name": "lamp", "x": 2.0, "y": 2.0, "width": 0.3, "depth": 0.3},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        overlap_violations = [v for v in result.violations if v.rule == "object_overlap"]
        assert len(overlap_violations) >= 1

    def test_separated_objects_pass(self, validator):
        """Well-separated objects don't trigger overlap violations."""
        plan = MetricPlan(
            room_dimensions=(5.0, 5.0, 2.7),
            walls=_build_walls_from_dimensions(5.0, 5.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(
                {"name": "table", "x": 1.5, "y": 1.5, "width": 0.8, "depth": 0.8},
                {"name": "chair", "x": 3.5, "y": 3.5, "width": 0.4, "depth": 0.4},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        overlap_violations = [v for v in result.violations if v.rule == "object_overlap"]
        assert len(overlap_violations) == 0


# ---------------------------------------------------------------------------
# Test 5: PlanValidator catches insufficient circulation (<0.6m)
# ---------------------------------------------------------------------------

class TestValidationCirculation:
    """Verify PlanValidator detects insufficient circulation clearance.

    **Validates: Requirements 5.3**
    """

    def test_object_too_close_to_wall(self, validator):
        """Object placed <0.6m from wall triggers circulation warning."""
        plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(
                # Object at x=0.3 with width=0.4 → left edge at 0.1m from wall
                {"name": "cabinet", "x": 0.3, "y": 2.0, "width": 0.4, "depth": 0.5},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        circ_violations = [v for v in result.violations if v.rule == "circulation_clearance"]
        assert len(circ_violations) >= 1
        assert circ_violations[0].details["clearance"] < MIN_CIRCULATION_WIDTH

    def test_well_placed_object_passes_circulation(self, validator):
        """Object with >0.6m clearance to all walls passes circulation check."""
        plan = MetricPlan(
            room_dimensions=(5.0, 5.0, 2.7),
            walls=_build_walls_from_dimensions(5.0, 5.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(
                # Center of 5m room with small object — plenty of clearance
                {"name": "table", "x": 2.5, "y": 2.5, "width": 0.8, "depth": 0.8},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        circ_violations = [v for v in result.violations if v.rule == "circulation_clearance"]
        assert len(circ_violations) == 0


# ---------------------------------------------------------------------------
# Test 6: PlanValidator catches openings too close to corners
# ---------------------------------------------------------------------------

class TestValidationOpeningCornerDistance:
    """Verify PlanValidator detects openings too close to wall corners.

    **Validates: Requirements 5.3**
    """

    def test_opening_at_wall_edge(self, validator):
        """Opening at parameter=0.05 on a 4m wall is too close to corner."""
        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 3.0, 2.7),
            openings=(
                # parameter=0.05 → center at 0.2m, with width=0.9 → left edge at -0.25m
                {"type": "door", "wall": "south", "parameter": 0.05, "width": 0.9, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        corner_violations = [v for v in result.violations if v.rule == "opening_corner_distance"]
        assert len(corner_violations) >= 1

    def test_centered_opening_passes(self, validator):
        """Opening at parameter=0.5 is far enough from both corners."""
        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        corner_violations = [v for v in result.violations if v.rule == "opening_corner_distance"]
        assert len(corner_violations) == 0


# ---------------------------------------------------------------------------
# Test 7: PlanValidator auto-corrects violations and increments revision
# ---------------------------------------------------------------------------

class TestAutoCorrectAndRevision:
    """Verify auto-correction creates new revision with traceable changes.

    **Validates: Requirements 5.4**
    """

    def test_auto_correct_increments_revision(self, validator):
        """Auto-correction creates revision with number > original."""
        plan = MetricPlan(
            room_dimensions=(1.0, 3.0, 2.7),  # too narrow
            walls=_build_walls_from_dimensions(1.0, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(
                PlanRevision(revision=1, changed="initial", reason="test", plan_hash="abc"),
            ),
            template_id="generic",
        )

        result = validator.validate(plan)
        assert result.plan is not None

        corrected = result.plan
        latest_rev = max(r.revision for r in corrected.revisions)
        assert latest_rev == 2, f"Expected revision 2, got {latest_rev}"

    def test_auto_correct_fixes_narrow_width(self, validator):
        """Auto-correction expands width to meet minimum."""
        plan = MetricPlan(
            room_dimensions=(1.0, 3.0, 2.7),
            walls=_build_walls_from_dimensions(1.0, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="initial", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        corrected = result.plan
        assert corrected.room_dimensions[0] >= MIN_ROOM_WIDTH

    def test_revision_records_what_changed(self, validator):
        """New revision describes what was corrected."""
        plan = MetricPlan(
            room_dimensions=(1.0, 3.0, 2.7),
            walls=_build_walls_from_dimensions(1.0, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="initial", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        new_rev = result.plan.revisions[-1]
        assert new_rev.changed != ""
        assert "width" in new_rev.changed.lower()  # should mention width correction
        assert new_rev.reason != ""
        assert new_rev.plan_hash != ""

    def test_multiple_corrections_in_one_revision(self, validator):
        """Multiple violations are corrected in a single new revision."""
        plan = MetricPlan(
            room_dimensions=(1.0, 1.0, 7.0),  # too narrow AND too tall
            walls=_build_walls_from_dimensions(1.0, 1.0, 7.0),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="initial", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(plan)
        corrected = result.plan
        # Should still be exactly one new revision (not one per violation)
        assert len(corrected.revisions) == 2  # original + one correction


# ---------------------------------------------------------------------------
# Test 8: Danny's kitchenette — dimensions, objects, and plausibility
# ---------------------------------------------------------------------------

class TestDannyKitchenette:
    """Integration: Danny's kitchenette plan is dimensionally plausible.

    Room 3-5m width, 3-5m depth, 2.4-2.7m height, has table, chairs,
    counter, coffee maker, window.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """

    @pytest.mark.asyncio
    async def test_room_width_3_to_5m(self, mock_generate_json, danny_brief):
        """Danny's kitchenette width is between 3 and 5 meters."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        w = plan.room_dimensions[0]
        assert 3.0 <= w <= 5.0, f"Width {w}m outside 3-5m range"

    @pytest.mark.asyncio
    async def test_room_depth_3_to_5m(self, mock_generate_json, danny_brief):
        """Danny's kitchenette depth is between 3 and 5 meters."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        d = plan.room_dimensions[1]
        assert 3.0 <= d <= 5.0, f"Depth {d}m outside 3-5m range"

    @pytest.mark.asyncio
    async def test_ceiling_height_2_4_to_2_7m(self, mock_generate_json, danny_brief):
        """Danny's kitchenette ceiling is between 2.4 and 2.7 meters."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        h = plan.room_dimensions[2]
        assert 2.4 <= h <= 2.7, f"Ceiling {h}m outside 2.4-2.7m range"

    @pytest.mark.asyncio
    async def test_has_table(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan contains a table placement."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        names = [p.get("name", "").lower() for p in plan.object_placements]
        assert any("table" in n for n in names), f"No table found in placements: {names}"

    @pytest.mark.asyncio
    async def test_has_chairs(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan contains chair placements."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        chair_count = sum(
            1 for p in plan.object_placements if "chair" in p.get("name", "").lower()
        )
        assert chair_count >= 2, f"Expected at least 2 chairs, got {chair_count}"

    @pytest.mark.asyncio
    async def test_has_counter(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan contains a counter placement."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        names = [p.get("name", "").lower() for p in plan.object_placements]
        assert any("counter" in n for n in names), f"No counter found: {names}"

    @pytest.mark.asyncio
    async def test_has_coffee_maker(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan contains a coffee maker placement."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        names = [p.get("name", "").lower() for p in plan.object_placements]
        assert any("coffee" in n for n in names), f"No coffee maker found: {names}"

    @pytest.mark.asyncio
    async def test_has_window_opening(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan has a window opening."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        opening_types = [o.get("type", "") for o in plan.openings]
        assert "window" in opening_types, f"No window opening found: {opening_types}"

    @pytest.mark.asyncio
    async def test_passes_validation(self, mock_generate_json, danny_brief, validator):
        """Danny's generated plan passes validation with no error-level violations."""
        gen = MetricPlanGenerator()
        plan = await gen.generate(danny_brief)
        result = validator.validate(plan)

        errors = [v for v in result.violations if v.severity == "error"]
        assert len(errors) == 0, (
            f"Danny's plan should have no errors: "
            f"{[(v.rule, v.message) for v in errors]}"
        )
