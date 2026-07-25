"""Unit tests for the lane ladder module."""

from __future__ import annotations

import pytest

from src.lane_ladder import (
    CLOUD_FALLBACK,
    LANE_LADDER,
    LaneDef,
    _simplify_prompt,
)


class TestLaneDefinitions:
    """Test that lane ladder data is correctly configured."""

    def test_lane_ladder_has_three_local_lanes(self):
        assert len(LANE_LADDER) == 3
        assert all(lane.local for lane in LANE_LADDER)

    def test_lane_ladder_models(self):
        models = [lane.model for lane in LANE_LADDER]
        assert models == ["planner-probe-v1:latest", "gpt-oss:20b", "qwen3.6:27b"]

    def test_lane_ladder_timeouts_increase(self):
        timeouts = [lane.timeout_s for lane in LANE_LADDER]
        assert timeouts == [20, 25, 30]

    def test_lane_ladder_priorities_ascending(self):
        priorities = [lane.priority for lane in LANE_LADDER]
        assert priorities == [1, 2, 3]

    def test_cloud_fallback_not_local(self):
        assert len(CLOUD_FALLBACK) == 2
        assert all(not lane.local for lane in CLOUD_FALLBACK)

    def test_cloud_fallback_models(self):
        models = [lane.model for lane in CLOUD_FALLBACK]
        assert models == ["glm-5.2:cloud", "kimi-k2.6:cloud"]

    def test_lane_def_is_frozen(self):
        lane = LaneDef(model="test", timeout_s=10, local=True)
        with pytest.raises(Exception):
            lane.model = "other"  # type: ignore[misc]


class TestPromptSimplification:
    """Test progressive prompt simplification logic."""

    @pytest.fixture
    def sample_prompt(self) -> str:
        from src.floor_plan.builder import PLAN_SYSTEM
        return PLAN_SYSTEM

    def test_full_prompt_unchanged(self, sample_prompt: str):
        result = _simplify_prompt(sample_prompt, remove_relationships=False, remove_clearance=False)
        assert result == sample_prompt

    def test_remove_relationships_shortens_prompt(self, sample_prompt: str):
        result = _simplify_prompt(sample_prompt, remove_relationships=True, remove_clearance=False)
        assert len(result) < len(sample_prompt)
        assert "RELATIONSHIPS" not in result
        # Other sections remain
        assert "ZONES" in result
        assert "CIRCULATION" in result

    def test_remove_clearance_shortens_further(self, sample_prompt: str):
        no_rel = _simplify_prompt(sample_prompt, remove_relationships=True, remove_clearance=False)
        no_both = _simplify_prompt(sample_prompt, remove_relationships=True, remove_clearance=True)
        assert len(no_both) < len(no_rel)
        assert "DOOR CLEARANCE" not in no_both
        assert "WINDOW CLEARANCE" not in no_both

    def test_clearance_only_without_relationships(self, sample_prompt: str):
        result = _simplify_prompt(sample_prompt, remove_relationships=False, remove_clearance=True)
        assert "DOOR CLEARANCE" not in result
        # Relationships still present
        assert "RELATIONSHIPS" in result

    def test_schema_section_preserved(self, sample_prompt: str):
        """Schema section should never be removed."""
        result = _simplify_prompt(sample_prompt, remove_relationships=True, remove_clearance=True)
        assert "Schema:" in result


class TestGeneratePlanWithLadder:
    """Test the async lane ladder generation function (mocked LLM)."""

    @pytest.fixture
    def mock_valid_plan(self) -> dict:
        """Minimal valid floor plan response."""
        return {
            "name": "Test Room",
            "room": {"width": 5.0, "depth": 4.0, "height": 3.0},
            "items": [
                {
                    "id": "table_1",
                    "name": "Table",
                    "category": "furniture",
                    "mount": "floor",
                    "x": 0.0,
                    "z": 0.0,
                    "width": 1.2,
                    "depth": 0.8,
                    "height": 0.75,
                    "elevation": 0.0,
                    "rotation_deg": 0,
                    "fixed": False,
                    "clearance_m": 0.5,
                    "description": "A wooden table",
                }
            ],
            "openings": [
                {
                    "id": "door_1",
                    "kind": "door",
                    "wall": "south",
                    "offset": 0.0,
                    "width": 0.9,
                    "height": 2.1,
                    "sill_height": 0.0,
                }
            ],
            "camera": {
                "x": -2.0,
                "y": 1.6,
                "z": -1.5,
                "target_x": 0.0,
                "target_y": 1.2,
                "target_z": 0.0,
                "fov_deg": 55,
            },
            "circulation_notes": ["Clear path from door to table"],
            "design_notes": ["Simple test room"],
        }

    @pytest.mark.asyncio
    async def test_returns_on_first_valid_plan(self, mock_valid_plan, monkeypatch):
        """If the first model produces a valid plan, return immediately."""
        call_log: list[str] = []

        async def fake_generate_json(system, user, model=None, *, timeout_seconds=None):
            call_log.append(model or "default")
            return mock_valid_plan

        import src.orchestrator.llm
        monkeypatch.setattr(src.orchestrator.llm, "generate_json", fake_generate_json)

        from src.lane_ladder import generate_plan_with_ladder
        from src.models import SceneConcept

        concept = SceneConcept(
            era="modern",
            mood="warm",
            palette="neutral tones",
            architecture_notes="simple walls",
            key_objects=["table"],
            lighting_notes="natural light",
            image_prompt="a modern room with a table",
        )

        plan, warnings, report, model_used, attempts = await generate_plan_with_ladder(
            "A simple room with a table", concept
        )

        assert model_used == "planner-probe-v1:latest"
        assert attempts == 1
        assert report.valid
        assert plan.room.width == 5.0

    @pytest.mark.asyncio
    async def test_escalates_on_llm_error(self, mock_valid_plan, monkeypatch):
        """If the first model errors, escalate to next lane."""
        from src.orchestrator.llm import LLMError

        call_count = {"n": 0}

        async def fake_generate_json(system, user, model=None, *, timeout_seconds=None):
            call_count["n"] += 1
            if model == "planner-probe-v1:latest":
                raise LLMError("Timeout")
            return mock_valid_plan

        import src.orchestrator.llm
        monkeypatch.setattr(src.orchestrator.llm, "generate_json", fake_generate_json)

        from src.lane_ladder import generate_plan_with_ladder
        from src.models import SceneConcept

        concept = SceneConcept(
            era="modern",
            mood="warm",
            palette="neutral tones",
            architecture_notes="simple walls",
            key_objects=["table"],
            lighting_notes="natural light",
            image_prompt="a modern room with a table",
        )

        plan, warnings, report, model_used, attempts = await generate_plan_with_ladder(
            "A simple room with a table", concept
        )

        # Should have escalated past the first lane
        assert model_used == "gpt-oss:20b"
        assert attempts >= 2
