"""Tests for Plan generation and validation.

Tests constrained template selection, validation rules (closure, overlap,
circulation), revision tracking. Tests Danny's kitchenette dimensions are
plausible.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.unified_pipeline.plan_generator import (
    MetricPlanGenerator,
    select_template,
    ROOM_TEMPLATES,
    _build_walls_from_dimensions,
)
from src.unified_pipeline.plan_validator import (
    PlanValidator,
    ValidationResult,
    ValidationViolation,
    MIN_ROOM_WIDTH,
    MAX_ROOM_HEIGHT,
    MIN_OPENING_CORNER_DIST,
    MIN_DOOR_SWING_CLEARANCE,
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
# Fixtures — Danny's kitchenette Brief
# ---------------------------------------------------------------------------

DANNY_KITCHENETTE_PROMPT = (
    "a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)


def _danny_brief() -> Brief:
    """Create Danny's kitchenette Brief for testing."""
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


# Mock LLM response for plan generation
# Note: Danny's Brief has 6 total object-count (table×1 + chair×2 + counter×1 + coffee_maker×1 + window×1)
# The window is architectural and part of openings, so it may not have a floor placement.
# We provide 5 placements for the 5 non-window objects (window is in openings).
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
        {"name": "round table", "x": 0.4, "y": 0.4, "rotation_deg": 0, "width": 0.8, "depth": 0.8, "height": 0.75},
        {"name": "chair", "x": 0.2, "y": 0.4, "rotation_deg": 90, "width": 0.4, "depth": 0.4, "height": 0.85},
        {"name": "chair", "x": 0.6, "y": 0.4, "rotation_deg": 270, "width": 0.4, "depth": 0.4, "height": 0.85},
        {"name": "counter", "x": 0.5, "y": 0.85, "rotation_deg": 0, "width": 1.4, "depth": 0.5, "height": 0.9},
        {"name": "coffee maker", "x": 0.82, "y": 0.85, "rotation_deg": 0, "width": 0.25, "depth": 0.25, "height": 0.4},
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
    """Danny's kitchenette Brief fixture."""
    return _danny_brief()


@pytest.fixture
def validator():
    """PlanValidator instance."""
    return PlanValidator()


def _well_formed_plan() -> MetricPlan:
    """Create a well-formed plan that should pass all validation."""
    width, depth, ceiling = 4.0, 3.5, 2.7
    walls = _build_walls_from_dimensions(width, depth, ceiling)
    return MetricPlan(
        room_dimensions=(width, depth, ceiling),
        walls=walls,
        openings=(
            {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ),
        object_placements=(
            {"name": "table", "x": 1.5, "y": 1.75, "width": 0.9, "depth": 0.9, "height": 0.75},
            {"name": "chair", "x": 3.0, "y": 1.75, "width": 0.45, "depth": 0.45, "height": 0.85},
        ),
        circulation_paths=(
            {"from": "door_0", "to": "center", "min_width": 0.6},
        ),
        revisions=(
            PlanRevision(revision=1, changed="initial", reason="test", plan_hash="abc123"),
        ),
        template_id="kitchen",
    )


# ---------------------------------------------------------------------------
# Test 1: MetricPlanGenerator selects "kitchen" template for Danny's Brief
# ---------------------------------------------------------------------------

class TestTemplateSelection:
    """Verify constrained template selection from Brief content."""

    def test_selects_kitchen_for_danny_brief(self, danny_brief):
        """MetricPlanGenerator selects 'kitchen' template for Danny's kitchenette Brief.

        **Validates: Requirements 5.1**
        """
        template_id = select_template(danny_brief)
        assert template_id == "kitchen", (
            f"Expected 'kitchen' template, got '{template_id}'"
        )

    def test_selects_living_room_for_lounge(self):
        """Selects living_room template for a lounge-type Brief.

        **Validates: Requirements 5.1**
        """
        brief = Brief(
            room_purpose="comfortable living room for family time",
            object_manifest=(
                ManifestObject(name="sofa", role="seating"),
                ManifestObject(name="TV", role="entertainment"),
            ),
        )
        template_id = select_template(brief)
        assert template_id == "living_room"

    def test_selects_generic_for_unknown_purpose(self):
        """Selects generic template when no keywords match.

        **Validates: Requirements 5.1**
        """
        brief = Brief(
            room_purpose="mysterious void",
            object_manifest=(
                ManifestObject(name="orb", role="mystical"),
            ),
        )
        template_id = select_template(brief)
        assert template_id == "generic"


# ---------------------------------------------------------------------------
# Test 2: Generated plan has plausible dimensions (3-5m × 3-5m, ceiling 2.4-2.7m)
# ---------------------------------------------------------------------------

class TestDannyDimensions:
    """Verify Danny's kitchenette has plausible real-world dimensions."""

    @pytest.mark.asyncio
    async def test_kitchenette_dimensions_plausible(self, mock_generate_json, danny_brief):
        """Generated plan has plausible dimensions: 3-5m × 3-5m, ceiling 2.4-2.7m.

        **Validates: Requirements 5.2**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        width, depth, ceiling = plan.room_dimensions
        assert 3.0 <= width <= 5.0, f"Width {width}m not in 3-5m range"
        assert 3.0 <= depth <= 5.0, f"Depth {depth}m not in 3-5m range"
        assert 2.4 <= ceiling <= 2.7, f"Ceiling {ceiling}m not in 2.4-2.7m range"


# ---------------------------------------------------------------------------
# Test 3: Generated plan has at least one door and one window
# ---------------------------------------------------------------------------

class TestPlanOpenings:
    """Verify generated plan has required openings."""

    @pytest.mark.asyncio
    async def test_has_door_and_window(self, mock_generate_json, danny_brief):
        """Generated plan has at least one door opening and one window opening.

        **Validates: Requirements 5.2**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        opening_types = [o.get("type", "") for o in plan.openings]
        assert "door" in opening_types, "Plan has no door opening"
        assert "window" in opening_types, "Plan has no window opening"


# ---------------------------------------------------------------------------
# Test 4: Generated plan has object placements matching Brief manifest count
# ---------------------------------------------------------------------------

class TestObjectPlacements:
    """Verify object placements match Brief manifest."""

    @pytest.mark.asyncio
    async def test_placement_count_matches_manifest(self, mock_generate_json, danny_brief):
        """Generated plan has object placements matching Brief manifest count
        (excluding architectural objects like windows that are in openings).

        **Validates: Requirements 5.2**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        # Total floor-placed objects (excluding architectural items in openings)
        # Window is architectural and represented in openings, not floor placements
        expected_count = sum(
            obj.count for obj in danny_brief.object_manifest
            if not obj.is_architectural or obj.name.lower() not in ("window", "door")
        )
        actual_count = len(plan.object_placements)

        assert actual_count == expected_count, (
            f"Expected {expected_count} placements, got {actual_count}"
        )


# ---------------------------------------------------------------------------
# Test 5: PlanValidator passes a well-formed plan
# ---------------------------------------------------------------------------

class TestValidatorPass:
    """Verify PlanValidator passes a well-formed plan."""

    def test_well_formed_plan_passes(self, validator):
        """PlanValidator passes a well-formed plan with no violations.

        **Validates: Requirements 5.3**
        """
        plan = _well_formed_plan()
        result = validator.validate(plan)

        assert result.valid is True, (
            f"Well-formed plan should pass. Violations: "
            f"{[(v.rule, v.message) for v in result.violations]}"
        )
        assert result.error_count == 0


# ---------------------------------------------------------------------------
# Test 6: PlanValidator catches room too narrow (<1.5m)
# ---------------------------------------------------------------------------

class TestRoomTooNarrow:
    """Verify PlanValidator detects rooms that are too narrow."""

    def test_catches_narrow_room(self, validator):
        """PlanValidator catches room too narrow (<1.5m) — returns violation.

        **Validates: Requirements 5.3**
        """
        narrow_plan = MetricPlan(
            room_dimensions=(1.0, 3.0, 2.7),  # width=1.0m < 1.5m minimum
            walls=_build_walls_from_dimensions(1.0, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(narrow_plan)

        assert result.valid is False
        width_violations = [v for v in result.violations if v.rule == "room_width_min"]
        assert len(width_violations) >= 1, "Expected room_width_min violation"
        assert width_violations[0].severity == "error"


# ---------------------------------------------------------------------------
# Test 7: PlanValidator catches room too tall (>6m)
# ---------------------------------------------------------------------------

class TestRoomTooTall:
    """Verify PlanValidator detects rooms that are too tall."""

    def test_catches_tall_room(self, validator):
        """PlanValidator catches room too tall (>6m) — returns violation.

        **Validates: Requirements 5.3**
        """
        tall_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 7.0),  # height=7.0m > 6.0m maximum
            walls=_build_walls_from_dimensions(4.0, 4.0, 7.0),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(tall_plan)

        assert result.valid is False
        height_violations = [v for v in result.violations if v.rule == "room_height_max"]
        assert len(height_violations) >= 1, "Expected room_height_max violation"
        assert height_violations[0].severity == "error"


# ---------------------------------------------------------------------------
# Test 8: PlanValidator catches overlapping objects
# ---------------------------------------------------------------------------

class TestObjectOverlap:
    """Verify PlanValidator detects overlapping object placements."""

    def test_catches_overlapping_objects(self, validator):
        """PlanValidator catches overlapping objects — returns violation.

        **Validates: Requirements 5.3**
        """
        overlap_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
                {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
            ),
            object_placements=(
                {"name": "table", "x": 2.0, "y": 2.0, "width": 1.0, "depth": 1.0, "height": 0.75},
                {"name": "chair", "x": 2.0, "y": 2.0, "width": 0.5, "depth": 0.5, "height": 0.85},  # same position
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="kitchen",
        )

        result = validator.validate(overlap_plan)

        assert result.valid is False
        overlap_violations = [v for v in result.violations if v.rule == "object_overlap"]
        assert len(overlap_violations) >= 1, "Expected object_overlap violation"


# ---------------------------------------------------------------------------
# Test 9: PlanValidator catches opening too close to corner (<0.3m)
# ---------------------------------------------------------------------------

class TestOpeningCorner:
    """Verify PlanValidator detects openings too close to wall corners."""

    def test_catches_opening_near_corner(self, validator):
        """PlanValidator catches opening too close to corner (<0.15m) — returns violation.

        **Validates: Requirements 5.3**
        """
        corner_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                # parameter=0.01 means opening is at 0.04m from left edge of 4m wall
                # With width=0.9m, center is at 0.04m → left edge at -0.41m (clamped to 0)
                # distance to corner = 0.04 - 0.45 = negative → definitely too close
                {"type": "door", "wall": "south", "parameter": 0.01, "width": 0.9, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(corner_plan)

        assert result.valid is False
        corner_violations = [v for v in result.violations if v.rule == "opening_corner_distance"]
        assert len(corner_violations) >= 1, "Expected opening_corner_distance violation"


# ---------------------------------------------------------------------------
# Test 10: PlanValidator auto-corrects violations and creates new revision
# ---------------------------------------------------------------------------

class TestAutoCorrection:
    """Verify auto-correction creates a new revision."""

    def test_auto_corrects_and_new_revision(self, validator):
        """PlanValidator auto-corrects violations and creates new revision.

        **Validates: Requirements 5.4**
        """
        # Plan with a narrow room — should be auto-corrected
        narrow_plan = MetricPlan(
            room_dimensions=(1.2, 3.0, 2.7),  # width too narrow
            walls=_build_walls_from_dimensions(1.2, 3.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.8, "height": 2.1},
            ),
            object_placements=(),
            circulation_paths=(),
            revisions=(
                PlanRevision(revision=1, changed="initial", reason="test", plan_hash="orig"),
            ),
            template_id="generic",
        )

        result = validator.validate(narrow_plan)

        assert result.valid is False
        assert result.plan is not None, "Auto-correction should produce a corrected plan"

        # Corrected plan should have fixed dimensions
        corrected = result.plan
        assert corrected.room_dimensions[0] >= MIN_ROOM_WIDTH, (
            f"Corrected width {corrected.room_dimensions[0]} still below minimum"
        )

        # Should have a new revision
        assert len(corrected.revisions) > len(narrow_plan.revisions)


# ---------------------------------------------------------------------------
# Test 11: Revision tracking — corrected plan has revision > original
# ---------------------------------------------------------------------------

class TestRevisionTracking:
    """Verify revision tracking on auto-correction."""

    def test_corrected_revision_higher(self, validator):
        """Revision tracking: corrected plan has revision > original.

        **Validates: Requirements 5.4**
        """
        original_plan = MetricPlan(
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

        result = validator.validate(original_plan)
        corrected = result.plan

        assert corrected is not None
        original_max_rev = max(r.revision for r in original_plan.revisions)
        corrected_max_rev = max(r.revision for r in corrected.revisions)
        assert corrected_max_rev > original_max_rev, (
            f"Corrected revision {corrected_max_rev} should be > original {original_max_rev}"
        )

    def test_revision_has_reason(self, validator):
        """Each revision records what changed and why.

        **Validates: Requirements 5.4**
        """
        narrow_plan = MetricPlan(
            room_dimensions=(1.0, 3.0, 2.7),
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

        result = validator.validate(narrow_plan)
        corrected = result.plan
        new_revision = corrected.revisions[-1]

        assert new_revision.changed != "", "Revision should describe what changed"
        assert new_revision.reason != "", "Revision should describe why"
        assert new_revision.plan_hash != "", "Revision should have a plan hash"


# ---------------------------------------------------------------------------
# Test 12: Danny's kitchenette plan passes validation with no violations
# ---------------------------------------------------------------------------

class TestDannyFullValidation:
    """Integration test: Danny's kitchenette plan passes complete validation."""

    @pytest.mark.asyncio
    async def test_danny_plan_passes_validation(self, mock_generate_json, danny_brief, validator):
        """Danny's kitchenette plan passes validation with no error violations.
        Warnings (e.g. counter near wall) are acceptable for kitchens.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        result = validator.validate(plan)

        # Should have no ERROR-level violations
        # Warnings (like counter near wall) are acceptable for kitchen layouts
        errors = [v for v in result.violations if v.severity == "error"]
        assert len(errors) == 0, (
            f"Danny's kitchenette plan should have no errors. Errors: "
            f"{[(v.rule, v.message) for v in errors]}"
        )

    @pytest.mark.asyncio
    async def test_danny_plan_has_kitchen_template(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan uses the kitchen template.

        **Validates: Requirements 5.1**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        assert plan.template_id == "kitchen"

    @pytest.mark.asyncio
    async def test_danny_plan_has_revision_tracking(self, mock_generate_json, danny_brief):
        """Danny's kitchenette plan has at least one revision recorded.

        **Validates: Requirements 5.2**
        """
        generator = MetricPlanGenerator()
        plan = await generator.generate(danny_brief)

        assert len(plan.revisions) >= 1
        assert plan.revisions[0].revision == 1
        assert plan.revisions[0].reason != ""


# ---------------------------------------------------------------------------
# Test 13: PlanValidator catches object in door swing arc
# ---------------------------------------------------------------------------

class TestDoorSwingClearance:
    """Verify PlanValidator detects objects blocking door swing."""

    def test_catches_object_in_door_swing(self, validator):
        """PlanValidator catches object within door swing arc — returns violation.

        **Validates: Requirements 5.3**
        """
        # Door is on south wall at parameter 0.5 (center of 4m wall = 2.0m)
        # Door width = 0.9m, so hinge at x=1.55, y=4.0 (south wall y=depth)
        # Swing radius = 0.9m. An object at x=1.5, y=3.5 is within 0.9m of hinge.
        swing_blocked_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
                {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
            ),
            object_placements=(
                # Object placed right next to the door — within swing arc
                {"name": "shelf", "x": 1.6, "y": 3.7, "width": 0.4, "depth": 0.4, "height": 1.0},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="generic",
        )

        result = validator.validate(swing_blocked_plan)

        swing_violations = [v for v in result.violations if v.rule == "door_swing_clearance"]
        assert len(swing_violations) >= 1, (
            f"Expected door_swing_clearance violation. Got violations: "
            f"{[(v.rule, v.message) for v in result.violations]}"
        )

    def test_object_far_from_door_passes(self, validator):
        """Object far from door swing arc does NOT trigger violation.

        **Validates: Requirements 5.3**
        """
        ok_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
                {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
            ),
            object_placements=(
                # Object in center of room — well away from door swing
                {"name": "table", "x": 2.0, "y": 2.0, "width": 0.8, "depth": 0.8, "height": 0.75},
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="kitchen",
        )

        result = validator.validate(ok_plan)

        swing_violations = [v for v in result.violations if v.rule == "door_swing_clearance"]
        assert len(swing_violations) == 0, (
            f"Object far from door should NOT trigger door_swing_clearance. "
            f"Got: {[(v.rule, v.message) for v in swing_violations]}"
        )


# ---------------------------------------------------------------------------
# Test 14: PlanValidator auto-corrects door swing violations
# ---------------------------------------------------------------------------

class TestDoorSwingAutoCorrect:
    """Verify auto-correction moves objects out of door swing arc."""

    def test_auto_corrects_door_swing(self, validator):
        """Auto-correction moves object out of door swing and creates new revision.

        **Validates: Requirements 5.4**
        """
        blocked_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
                {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
            ),
            object_placements=(
                {"name": "shelf", "x": 1.6, "y": 3.7, "width": 0.4, "depth": 0.4, "height": 1.0},
            ),
            circulation_paths=(),
            revisions=(
                PlanRevision(revision=1, changed="initial", reason="test", plan_hash="abc"),
            ),
            template_id="generic",
        )

        result = validator.validate(blocked_plan)

        assert result.plan is not None, "Expected auto-corrected plan"
        # The corrected plan should have moved the shelf
        corrected_placements = result.plan.object_placements
        assert len(corrected_placements) == 1
        # Y should be smaller (moved away from south wall)
        original_y = 3.7
        corrected_y = corrected_placements[0].get("y", original_y)
        assert corrected_y < original_y, (
            f"Expected shelf moved away from south wall: "
            f"original y={original_y}, corrected y={corrected_y}"
        )


# ---------------------------------------------------------------------------
# Test 15: PlanValidator catches insufficient inter-object circulation
# ---------------------------------------------------------------------------

class TestInterObjectCirculation:
    """Verify PlanValidator detects objects too close to each other."""

    def test_catches_tight_object_gap(self, validator):
        """Objects with <0.6m gap trigger circulation_clearance warning.

        **Validates: Requirements 5.3**
        """
        tight_plan = MetricPlan(
            room_dimensions=(4.0, 4.0, 2.7),
            walls=_build_walls_from_dimensions(4.0, 4.0, 2.7),
            openings=(
                {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
                {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
            ),
            object_placements=(
                # Two objects with only 0.3m gap between them
                {"name": "table", "x": 2.0, "y": 2.0, "width": 0.8, "depth": 0.8, "height": 0.75},
                {"name": "chair", "x": 2.0, "y": 2.9, "width": 0.4, "depth": 0.4, "height": 0.85},
                # Gap: |2.0 - 2.9| = 0.9, minus half-depths = 0.9 - 0.4 - 0.2 = 0.3m < 0.6m
            ),
            circulation_paths=(),
            revisions=(PlanRevision(revision=1, changed="test", reason="test"),),
            template_id="kitchen",
        )

        result = validator.validate(tight_plan)

        circ_violations = [
            v for v in result.violations
            if v.rule == "circulation_clearance"
            and "table" in v.message and "chair" in v.message
        ]
        assert len(circ_violations) >= 1, (
            f"Expected inter-object circulation_clearance warning. "
            f"Got: {[(v.rule, v.message) for v in result.violations]}"
        )
