"""Unit tests for scene validation logic - object count, position, lighting, and interactions.

Tests the validation helpers (_euclidean_distance, validate_lighting_against_contract,
hex_to_rgb, format_interaction_failures) and the TestSceneValidation/TestSceneInteractions
methods with mocked QA bridge objects, without requiring a live browser or Playwright.

Requirements: 8.1-8.4, 9.1-9.3, 10.1-10.4
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.e2e.test_scene_validation import (
    DEFAULT_POSITION_TOLERANCE,
    DOOR_SETTLE_TIMEOUT_S,
    GRAB_RELEASE_SETTLE_TIMEOUT_S,
    PUSH_SETTLE_TIMEOUT_S,
    InteractionFailure,
    LightingMismatch,
    _euclidean_distance,
    _format_position,
    format_interaction_failures,
    format_lighting_mismatches,
    hex_to_rgb,
    validate_lighting_against_contract,
)
# Import the module (not the Test classes directly) to avoid pytest collecting them
import tests.e2e.test_scene_validation as _scene_validation_mod
_SceneValidationImpl = _scene_validation_mod.TestSceneValidation
_SceneInteractionsImpl = _scene_validation_mod.TestSceneInteractions


# ---------------------------------------------------------------------------
# _euclidean_distance tests
# ---------------------------------------------------------------------------


class TestEuclideanDistance:
    """Test the Euclidean distance helper. Requirements: 8.2, 8.4"""

    def test_identical_positions_zero_distance(self):
        pos = {"x": 1.0, "y": 2.0, "z": 3.0}
        assert _euclidean_distance(pos, pos) == 0.0

    def test_unit_x_distance(self):
        a = {"x": 0.0, "y": 0.0, "z": 0.0}
        b = {"x": 1.0, "y": 0.0, "z": 0.0}
        assert _euclidean_distance(a, b) == pytest.approx(1.0)

    def test_3d_diagonal(self):
        a = {"x": 0.0, "y": 0.0, "z": 0.0}
        b = {"x": 1.0, "y": 1.0, "z": 1.0}
        assert _euclidean_distance(a, b) == pytest.approx(math.sqrt(3))

    def test_small_delta_below_tolerance(self):
        a = {"x": 1.0, "y": 2.0, "z": 3.0}
        b = {"x": 1.005, "y": 2.005, "z": 3.005}
        assert _euclidean_distance(a, b) < DEFAULT_POSITION_TOLERANCE

    def test_small_delta_above_tolerance(self):
        a = {"x": 1.0, "y": 2.0, "z": 3.0}
        b = {"x": 1.01, "y": 2.01, "z": 3.0}
        assert _euclidean_distance(a, b) > DEFAULT_POSITION_TOLERANCE


class TestFormatPosition:
    """Test the position formatting helper."""

    def test_formats_with_4_decimals(self):
        pos = {"x": 1.0, "y": 2.5, "z": -3.123456}
        result = _format_position(pos)
        assert result == "(1.0000, 2.5000, -3.1235)"

    def test_zero_position(self):
        pos = {"x": 0.0, "y": 0.0, "z": 0.0}
        result = _format_position(pos)
        assert result == "(0.0000, 0.0000, 0.0000)"


# ---------------------------------------------------------------------------
# hex_to_rgb tests
# ---------------------------------------------------------------------------


class TestHexToRgb:
    """Test hex color string to normalized RGB tuple conversion."""

    def test_white(self):
        assert hex_to_rgb("#ffffff") == pytest.approx((1.0, 1.0, 1.0))

    def test_black(self):
        assert hex_to_rgb("#000000") == pytest.approx((0.0, 0.0, 0.0))

    def test_red(self):
        assert hex_to_rgb("#ff0000") == pytest.approx((1.0, 0.0, 0.0))

    def test_case_insensitive(self):
        assert hex_to_rgb("#FF8800") == hex_to_rgb("#ff8800")


# ---------------------------------------------------------------------------
# validate_lighting_against_contract tests
# ---------------------------------------------------------------------------


class TestValidateLightingAgainstContract:
    """Test lighting validation logic. Requirements: 9.1, 9.2, 9.3"""

    def _make_light(self, light_type="point", position=None, color="#ffffff", intensity=1.0):
        return {"type": light_type, "position": position or {"x": 0.0, "y": 0.0, "z": 0.0}, "color": color, "intensity": intensity}

    def _make_contract_light(self, light_type="point", position=None, color="#ffffff", intensity=1.0):
        return {"light_type": light_type, "position": position or {"x": 0.0, "y": 0.0, "z": 0.0}, "color": color, "intensity": intensity}

    def test_identical_lights_pass(self):
        expected = [self._make_contract_light("point", {"x": 1.0, "y": 2.0, "z": 3.0}, "#ff8800", 1.5)]
        actual = [self._make_light("point", {"x": 1.0, "y": 2.0, "z": 3.0}, "#ff8800", 1.5)]
        assert validate_lighting_against_contract(actual, expected) == []

    def test_position_within_tolerance_passes(self):
        expected = [self._make_contract_light("point", {"x": 1.0, "y": 2.0, "z": 3.0})]
        actual = [self._make_light("point", {"x": 1.01, "y": 2.0, "z": 3.0})]
        assert validate_lighting_against_contract(actual, expected) == []

    def test_type_mismatch_reported(self):
        expected = [self._make_contract_light("directional")]
        actual = [self._make_light("point")]
        result = validate_lighting_against_contract(actual, expected)
        assert len(result) == 1
        assert result[0].parameter == "type"

    def test_intensity_exceeds_5_percent_reported(self):
        expected = [self._make_contract_light(intensity=100.0)]
        actual = [self._make_light(intensity=106.0)]
        result = validate_lighting_against_contract(actual, expected)
        assert len(result) == 1
        assert result[0].parameter == "intensity"


class TestFormatLightingMismatches:
    """Test formatting of lighting mismatch reports. Requirements: 9.3"""

    def test_single_mismatch_format(self):
        mismatches = [LightingMismatch(0, "position.x", 1.0, 1.05, 0.05)]
        report = format_lighting_mismatches(mismatches)
        assert "1 mismatch" in report
        assert "Light[0]" in report
        assert "position.x" in report

    def test_multiple_mismatches_all_listed(self):
        mismatches = [
            LightingMismatch(0, "position.x", 1.0, 1.05, 0.05),
            LightingMismatch(1, "intensity", 100.0, 50.0, 0.5),
        ]
        report = format_lighting_mismatches(mismatches)
        assert "2 mismatch" in report
        assert "position.x" in report
        assert "intensity" in report


# ---------------------------------------------------------------------------
# Mocked QA Bridge tests for object count / position validation
# ---------------------------------------------------------------------------


class TestObjectCountValidation:
    """Test object count matching logic. Requirements: 8.1, 8.3"""

    def _make_bridge(self, object_count, scene_graph):
        bridge = MagicMock()
        bridge.get_object_count = AsyncMock(return_value=object_count)
        bridge.get_scene_graph = AsyncMock(return_value=scene_graph)
        return bridge

    def _make_instances(self, ids):
        return [{"object_id": i, "name": f"object_{i}", "position": {"x": 0.0, "y": 0.0, "z": 0.0}} for i in ids]

    @pytest.mark.asyncio
    async def test_matching_count_passes(self):
        instances = self._make_instances(["a", "b", "c"])
        bridge = self._make_bridge(object_count=3, scene_graph=[])
        validator = _SceneValidationImpl()
        await validator.test_object_count_matches_world_contract(qa_bridge=bridge, world_contract_instances=instances)
        bridge.get_scene_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_mismatch_reports_missing(self):
        instances = self._make_instances(["door_01", "table_01", "lamp_01"])
        scene_graph = [
            {"objectId": "door_01", "meshCount": 1, "position": {"x": 0, "y": 0, "z": 0}},
            {"objectId": "table_01", "meshCount": 1, "position": {"x": 1, "y": 0, "z": 0}},
        ]
        bridge = self._make_bridge(object_count=2, scene_graph=scene_graph)
        validator = _SceneValidationImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_object_count_matches_world_contract(qa_bridge=bridge, world_contract_instances=instances)
        msg = str(exc_info.value)
        assert "lamp_01" in msg
        assert "Missing" in msg


class TestObjectPositionValidation:
    """Test object position tolerance logic. Requirements: 8.2, 8.4"""

    def _make_bridge(self, position_map):
        bridge = MagicMock()
        async def get_pos(object_id):
            return position_map.get(object_id)
        bridge.get_object_position = AsyncMock(side_effect=get_pos)
        return bridge

    @pytest.mark.asyncio
    async def test_all_positions_within_tolerance_passes(self):
        instances = [{"object_id": "obj_a", "name": "Object A", "position": {"x": 1.0, "y": 2.0, "z": 3.0}}]
        bridge = self._make_bridge({"obj_a": {"x": 1.005, "y": 2.005, "z": 3.0}})
        validator = _SceneValidationImpl()
        await validator.test_object_positions_within_tolerance(qa_bridge=bridge, world_contract_instances=instances, position_tolerance=DEFAULT_POSITION_TOLERANCE)

    @pytest.mark.asyncio
    async def test_position_exceeding_tolerance_reports_delta(self):
        instances = [{"object_id": "table_01", "name": "Kitchen Table", "position": {"x": 2.0, "y": 0.0, "z": -1.0}}]
        bridge = self._make_bridge({"table_01": {"x": 2.05, "y": 0.0, "z": -1.0}})
        validator = _SceneValidationImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_object_positions_within_tolerance(qa_bridge=bridge, world_contract_instances=instances, position_tolerance=DEFAULT_POSITION_TOLERANCE)
        msg = str(exc_info.value)
        assert "Kitchen Table" in msg

    @pytest.mark.asyncio
    async def test_missing_object_in_scene_reported(self):
        instances = [{"object_id": "missing_obj", "name": "Missing Object", "position": {"x": 1.0, "y": 1.0, "z": 1.0}}]
        bridge = self._make_bridge({"missing_obj": None})
        validator = _SceneValidationImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_object_positions_within_tolerance(qa_bridge=bridge, world_contract_instances=instances, position_tolerance=DEFAULT_POSITION_TOLERANCE)
        msg = str(exc_info.value)
        assert "Missing Object" in msg
        assert "not found" in msg


# ---------------------------------------------------------------------------
# Interaction testing unit tests -- Requirements 10.1-10.4
# ---------------------------------------------------------------------------


class TestInteractionFailureFormatting:
    """Test format_interaction_failures helper. Requirement 10.4"""

    def test_single_failure_format(self):
        failures = [InteractionFailure(
            object_name="Front Door", object_id="door_01",
            interaction_type="click-to-open",
            expected_state="success=True, state.settled=True",
            actual_state="success=False, state.settled=False",
        )]
        report = format_interaction_failures(failures)
        assert "1 object(s)" in report
        assert "Front Door" in report
        assert "door_01" in report
        assert "click-to-open" in report

    def test_multiple_failures_all_listed(self):
        failures = [
            InteractionFailure("Door A", "door_a", "click-to-open", "ea", "aa"),
            InteractionFailure("Mug B", "mug_b", "grab-release", "eb", "ab"),
            InteractionFailure("Crate C", "crate_c", "push", "ec", "ac"),
        ]
        report = format_interaction_failures(failures)
        assert "3 object(s)" in report
        assert "Door A" in report
        assert "Mug B" in report
        assert "Crate C" in report

    def test_error_state_included(self):
        failures = [InteractionFailure("Broken", "b01", "push", "expected", "Error: timeout")]
        report = format_interaction_failures(failures)
        assert "Error: timeout" in report


class TestDoorClickInteraction:
    """Test click-to-open door interaction logic. Requirements: 10.1, 10.4"""

    def _make_bridge(self, interaction_results):
        bridge = MagicMock()
        bridge.timeout_ms = 10000
        async def trigger(object_id, action):
            if object_id in interaction_results:
                return interaction_results[object_id]
            raise Exception(f"Object {object_id} not found")
        bridge.trigger_interaction = AsyncMock(side_effect=trigger)
        return bridge

    @pytest.mark.asyncio
    async def test_door_opens_successfully(self):
        interactions = [{"object_id": "door_01", "name": "Front Door", "interaction_type": "click-to-open"}]
        bridge = self._make_bridge({"door_01": {"success": True, "state": {"settled": True, "open": True}}})
        validator = _SceneInteractionsImpl()
        await validator.test_door_click_to_open(qa_bridge=bridge, world_contract_interactions=interactions)
        bridge.trigger_interaction.assert_called_once_with("door_01", "click")

    @pytest.mark.asyncio
    async def test_door_fails_to_open(self):
        interactions = [{"object_id": "door_01", "name": "Stuck Door", "interaction_type": "click-to-open"}]
        bridge = self._make_bridge({"door_01": {"success": False, "state": {"settled": False}}})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_door_click_to_open(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Stuck Door" in msg
        assert "click-to-open" in msg
        assert "success=False" in msg

    @pytest.mark.asyncio
    async def test_door_timeout_reports_error(self):
        interactions = [{"object_id": "door_01", "name": "Slow Door", "interaction_type": "click-to-open"}]
        bridge = MagicMock()
        bridge.timeout_ms = 10000
        bridge.trigger_interaction = AsyncMock(side_effect=Exception("timed out"))
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_door_click_to_open(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Slow Door" in msg
        assert "Error" in msg

    @pytest.mark.asyncio
    async def test_no_door_interactions_skips(self):
        interactions = [{"object_id": "mug_01", "name": "Mug", "interaction_type": "grab-release"}]
        bridge = self._make_bridge({})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.skip.Exception):
            await validator.test_door_click_to_open(qa_bridge=bridge, world_contract_interactions=interactions)

    @pytest.mark.asyncio
    async def test_multiple_doors_partial_failure(self):
        interactions = [
            {"object_id": "door_01", "name": "Door A", "interaction_type": "click-to-open"},
            {"object_id": "door_02", "name": "Door B", "interaction_type": "click-to-open"},
        ]
        bridge = self._make_bridge({
            "door_01": {"success": True, "state": {"settled": True}},
            "door_02": {"success": True, "state": {"settled": False}},
        })
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_door_click_to_open(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Door B" in msg
        assert "Door A" not in msg


class TestGrabReleaseInteraction:
    """Test grab-and-release physics interaction logic. Requirements: 10.2, 10.4"""

    def _make_bridge(self, interaction_sequence):
        bridge = MagicMock()
        bridge.timeout_ms = 10000
        call_counts = {}
        async def trigger(object_id, action):
            if object_id not in interaction_sequence:
                raise Exception(f"Object {object_id} not found")
            idx = call_counts.get(object_id, 0)
            results = interaction_sequence[object_id]
            if idx >= len(results):
                raise Exception(f"Unexpected extra call for {object_id}")
            call_counts[object_id] = idx + 1
            return results[idx]
        bridge.trigger_interaction = AsyncMock(side_effect=trigger)
        return bridge

    @pytest.mark.asyncio
    async def test_grab_release_settles_successfully(self):
        interactions = [{"object_id": "mug_01", "name": "Coffee Mug", "interaction_type": "grab-release"}]
        bridge = self._make_bridge({"mug_01": [
            {"success": True, "state": {"held": True}},
            {"success": True, "state": {"settled": True, "held": False}},
        ]})
        validator = _SceneInteractionsImpl()
        await validator.test_grab_and_release_physics_settling(qa_bridge=bridge, world_contract_interactions=interactions)

    @pytest.mark.asyncio
    async def test_grab_fails_reports_error(self):
        interactions = [{"object_id": "mug_01", "name": "Heavy Mug", "interaction_type": "grab-release"}]
        bridge = self._make_bridge({"mug_01": [{"success": False, "state": {"held": False}}]})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_grab_and_release_physics_settling(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Heavy Mug" in msg
        assert "grab" in msg

    @pytest.mark.asyncio
    async def test_release_does_not_settle(self):
        interactions = [{"object_id": "ball_01", "name": "Bouncy Ball", "interaction_type": "grab-release"}]
        bridge = self._make_bridge({"ball_01": [
            {"success": True, "state": {"held": True}},
            {"success": True, "state": {"settled": False, "held": False}},
        ]})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_grab_and_release_physics_settling(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Bouncy Ball" in msg
        assert "settled=False" in msg

    @pytest.mark.asyncio
    async def test_no_grabbable_interactions_skips(self):
        interactions = [{"object_id": "door_01", "name": "Door", "interaction_type": "click-to-open"}]
        bridge = self._make_bridge({})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.skip.Exception):
            await validator.test_grab_and_release_physics_settling(qa_bridge=bridge, world_contract_interactions=interactions)


class TestPushInteraction:
    """Test pushable object displacement logic. Requirements: 10.3, 10.4"""

    def _make_bridge(self, interaction_results):
        bridge = MagicMock()
        bridge.timeout_ms = 10000
        async def trigger(object_id, action):
            if object_id in interaction_results:
                return interaction_results[object_id]
            raise Exception(f"Object {object_id} not found")
        bridge.trigger_interaction = AsyncMock(side_effect=trigger)
        return bridge

    @pytest.mark.asyncio
    async def test_push_settles_successfully(self):
        interactions = [{"object_id": "crate_01", "name": "Wooden Crate", "interaction_type": "push"}]
        bridge = self._make_bridge({"crate_01": {"success": True, "state": {"settled": True}}})
        validator = _SceneInteractionsImpl()
        await validator.test_pushable_object_displacement(qa_bridge=bridge, world_contract_interactions=interactions)
        bridge.trigger_interaction.assert_called_once_with("crate_01", "push")

    @pytest.mark.asyncio
    async def test_push_fails_reports_error(self):
        interactions = [{"object_id": "crate_01", "name": "Heavy Crate", "interaction_type": "push"}]
        bridge = self._make_bridge({"crate_01": {"success": False, "state": {"settled": False}}})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_pushable_object_displacement(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Heavy Crate" in msg
        assert "push" in msg
        assert "success=False" in msg

    @pytest.mark.asyncio
    async def test_push_does_not_settle(self):
        interactions = [{"object_id": "barrel_01", "name": "Barrel", "interaction_type": "push"}]
        bridge = self._make_bridge({"barrel_01": {"success": True, "state": {"settled": False}}})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_pushable_object_displacement(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Barrel" in msg
        assert "settled=False" in msg

    @pytest.mark.asyncio
    async def test_no_pushable_interactions_skips(self):
        interactions = [{"object_id": "door_01", "name": "Door", "interaction_type": "click-to-open"}]
        bridge = self._make_bridge({})
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.skip.Exception):
            await validator.test_pushable_object_displacement(qa_bridge=bridge, world_contract_interactions=interactions)

    @pytest.mark.asyncio
    async def test_multiple_pushables_partial_failure(self):
        interactions = [
            {"object_id": "crate_01", "name": "Crate A", "interaction_type": "push"},
            {"object_id": "crate_02", "name": "Crate B", "interaction_type": "push"},
        ]
        bridge = self._make_bridge({
            "crate_01": {"success": True, "state": {"settled": True}},
            "crate_02": {"success": True, "state": {"settled": False}},
        })
        validator = _SceneInteractionsImpl()
        with pytest.raises(pytest.fail.Exception) as exc_info:
            await validator.test_pushable_object_displacement(qa_bridge=bridge, world_contract_interactions=interactions)
        msg = str(exc_info.value)
        assert "Crate B" in msg
        assert "Crate A" not in msg


class TestInteractionTimeoutConstants:
    """Verify the interaction timeout constants match requirements."""

    def test_door_timeout_within_1s(self):
        """Requirement 10.1: door transitions within 1 second."""
        assert DOOR_SETTLE_TIMEOUT_S == 1.0

    def test_grab_release_timeout_within_2s(self):
        """Requirement 10.2: grab/release settling within 2 seconds."""
        assert GRAB_RELEASE_SETTLE_TIMEOUT_S == 2.0

    def test_push_timeout_within_2s(self):
        """Requirement 10.3: push settling within 2 seconds."""
        assert PUSH_SETTLE_TIMEOUT_S == 2.0
