"""
Tests for ConversationEngine.

Validates core behaviors:
- Default Brief is schema-correct (Req 2.1, 2.2)
- Brief extraction from dict produces valid Brief with UUIDs (Req 2.2)
- Fallback on LLM failure returns schema-correct Brief (Req 1.8)
- Conversation state management
- Steering stability detection

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 2.1, 2.2, 2.3**
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.unified_pipeline.conversation import (
    ConversationEngine,
    ConversationState,
    _default_brief,
)
from src.unified_pipeline.models import (
    Brief,
    Atmosphere,
    Era,
    GameConcept,
    ManifestObject,
    Palette,
    RealCapability,
)


# ─── Default Brief Tests ───────────────────────────────────────────────────────


class TestDefaultBrief:
    """Test the fallback Brief used when conversation times out."""

    def test_default_brief_is_valid_brief(self):
        brief = _default_brief()
        assert isinstance(brief, Brief)

    def test_default_brief_has_room_purpose(self):
        brief = _default_brief()
        assert brief.room_purpose != ""

    def test_default_brief_has_atmosphere(self):
        brief = _default_brief()
        assert isinstance(brief.atmosphere, Atmosphere)
        assert brief.atmosphere.mood != ""

    def test_default_brief_has_era(self):
        brief = _default_brief()
        assert isinstance(brief.era, Era)
        assert brief.era.period != ""

    def test_default_brief_has_palette(self):
        brief = _default_brief()
        assert isinstance(brief.palette, Palette)
        assert brief.palette.primary != ""

    def test_default_brief_has_objects_with_uuids(self):
        """Req 2.2: each object gets a stable UUID."""
        brief = _default_brief()
        assert len(brief.object_manifest) > 0
        for obj in brief.object_manifest:
            assert isinstance(obj, ManifestObject)
            assert obj.id != ""
            assert obj.name != ""

    def test_default_brief_has_game_concept(self):
        brief = _default_brief()
        assert isinstance(brief.game_concept, GameConcept)
        assert brief.game_concept.theme != ""

    def test_default_brief_has_real_capabilities(self):
        brief = _default_brief()
        assert len(brief.real_capabilities) > 0
        for rc in brief.real_capabilities:
            assert isinstance(rc, RealCapability)
            assert rc.read_only_v1 is True

    def test_default_brief_has_provenance(self):
        """Req 2.3: Brief records provenance."""
        brief = _default_brief()
        assert "source" in brief.provenance

    def test_default_brief_serializes_roundtrip(self):
        """Req 29.2: JSON round-trip."""
        brief = _default_brief()
        d = brief.to_dict()
        restored = Brief.from_dict(d)
        assert restored.room_purpose == brief.room_purpose
        assert restored.atmosphere.mood == brief.atmosphere.mood
        assert len(restored.object_manifest) == len(brief.object_manifest)


# ─── ConversationEngine Unit Tests ─────────────────────────────────────────────


class TestConversationEngine:
    """Test ConversationEngine initialization and state management."""

    def test_creates_with_fresh_state(self):
        engine = ConversationEngine()
        assert engine.state.turn_count == 0
        assert engine.state.steering_stable is False
        assert engine.state.session_id != ""

    def test_reset_clears_state(self):
        engine = ConversationEngine()
        engine._state.turn_count = 5
        engine._state.steering_stable = True
        engine.reset()
        assert engine.state.turn_count == 0
        assert engine.state.steering_stable is False

    def test_is_stable_property(self):
        engine = ConversationEngine()
        assert engine.is_stable is False
        engine._state.steering_stable = True
        assert engine.is_stable is True


# ─── Brief Extraction Tests ────────────────────────────────────────────────────


class TestBriefExtraction:
    """Test the _dict_to_brief and _brief_from_state methods."""

    def test_dict_to_brief_produces_valid_brief(self):
        engine = ConversationEngine()
        data = {
            "room_purpose": "Danny's kitchenette",
            "atmosphere": {
                "mood": "warm and cozy",
                "lighting_direction": "warm overhead",
                "time_of_day": "evening",
            },
            "era": {
                "period": "modern casual",
                "style_exclusions": ["industrial", "minimalist"],
            },
            "palette": {
                "primary": "warm white",
                "accent": "natural wood",
                "material_finishes": ["matte paint", "butcher block"],
            },
            "object_manifest": [
                {"name": "round table", "role": "dining", "count": 1, "material_hint": "wood", "is_architectural": False},
                {"name": "chair", "role": "seating", "count": 2, "material_hint": "wood", "is_architectural": False},
                {"name": "counter", "role": "prep surface", "count": 1, "material_hint": "stone", "is_architectural": True},
                {"name": "coffee maker", "role": "appliance", "count": 1, "material_hint": "metal", "is_architectural": False},
                {"name": "window", "role": "opening", "count": 1, "material_hint": "glass", "is_architectural": True},
            ],
            "game_concept": {
                "theme": "breakfast rush",
                "mechanics": "prepare orders in sequence",
                "scoring": "orders completed",
                "win_condition": "all orders served within time",
            },
            "real_capabilities": [
                {"tool_type": "recipe", "surface_binding": "counter", "read_only_v1": True},
            ],
            "success_criteria": "A warm kitchenette with rain outside the window.",
        }

        brief = engine._dict_to_brief(data)
        assert isinstance(brief, Brief)
        assert brief.room_purpose == "Danny's kitchenette"
        assert brief.atmosphere.mood == "warm and cozy"
        assert brief.era.period == "modern casual"
        assert "industrial" in brief.era.style_exclusions
        assert brief.palette.primary == "warm white"
        assert len(brief.object_manifest) == 5
        assert brief.game_concept.theme == "breakfast rush"
        assert len(brief.real_capabilities) == 1
        assert brief.success_criteria != ""

    def test_dict_to_brief_assigns_uuids(self):
        """Req 2.2: Each object gets a stable UUID."""
        engine = ConversationEngine()
        data = {
            "room_purpose": "test",
            "object_manifest": [
                {"name": "table", "role": "surface", "count": 1},
                {"name": "chair", "role": "seating", "count": 2},
            ],
        }
        brief = engine._dict_to_brief(data)
        ids = [obj.id for obj in brief.object_manifest]
        assert len(ids) == 2
        assert ids[0] != ids[1]  # Unique per object
        # Each should be a valid UUID
        import uuid
        for obj_id in ids:
            uuid.UUID(obj_id)  # Raises if not valid

    def test_dict_to_brief_records_provenance(self):
        """Req 2.3: Brief records provenance."""
        engine = ConversationEngine()
        engine._state.turn_count = 3
        data = {"room_purpose": "test"}
        brief = engine._dict_to_brief(data)
        assert brief.provenance["session_id"] == engine.state.session_id
        assert brief.provenance["turn_count"] == "3"
        assert brief.provenance["extraction_method"] == "llm"

    def test_brief_from_state_with_accumulated_data(self):
        """Fallback extraction uses accumulated conversation state."""
        engine = ConversationEngine()
        engine._state.proposed_brief = {
            "room_purpose": "kitchen",
            "atmosphere": {"mood": "cozy", "lighting_direction": "warm", "time_of_day": "morning"},
            "era": {"period": "1970s", "style_exclusions": ["modern"]},
            "objects": [
                {"name": "fridge", "role": "appliance", "count": 1, "material_hint": "metal"},
            ],
        }
        brief = engine._brief_from_state()
        assert isinstance(brief, Brief)
        assert brief.room_purpose == "kitchen"
        assert brief.atmosphere.mood == "cozy"
        assert brief.era.period == "1970s"
        assert len(brief.object_manifest) == 1
        assert brief.object_manifest[0].name == "fridge"

    def test_brief_from_state_empty_returns_default(self):
        """Empty state should return the full default brief."""
        engine = ConversationEngine()
        brief = engine._brief_from_state()
        assert isinstance(brief, Brief)
        assert brief.room_purpose != ""  # Has default content
        assert len(brief.object_manifest) > 0


# ─── Async Integration Tests ──────────────────────────────────────────────────


class TestConversationAsync:
    """Test async methods with mocked LLM."""

    @pytest.mark.asyncio
    async def test_generate_opening_with_mock(self):
        """Req 1.1: Present a conversational prompt."""
        mock_response = {
            "greeting": "Welcome to your room design session! I'm picturing a cozy space.",
            "proposed_era": "mid-century modern",
            "proposed_mood": "warm and inviting",
            "proposed_palette": "teak, cream, mustard yellow",
            "proposed_objects": ["lounge chair", "side table", "floor lamp", "bookcase"],
        }
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            engine = ConversationEngine()
            greeting = await engine.generate_opening()
            assert "Welcome" in greeting
            assert len(engine.state.turns) == 1
            assert engine.state.turns[0].role == "assistant"

    @pytest.mark.asyncio
    async def test_generate_opening_fallback_on_error(self):
        """Req 1.1: Graceful fallback when LLM fails."""
        from src.orchestrator.llm import LLMError
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = LLMError("Ollama down")
            engine = ConversationEngine()
            greeting = await engine.generate_opening()
            assert greeting != ""  # Fallback should produce something
            assert len(engine.state.turns) == 1

    @pytest.mark.asyncio
    async def test_interpret_response_updates_state(self):
        """Req 1.2, 1.7: Interpret user responses and update state."""
        mock_response = {
            "interpretation": "User wants a 1950s diner",
            "room_purpose": "diner",
            "atmosphere": {"mood": "nostalgic", "lighting_direction": "warm neon", "time_of_day": "evening"},
            "era": {"period": "1950s", "style_exclusions": ["modern tech"]},
            "palette": {"primary": "chrome", "accent": "red vinyl", "material_finishes": ["chrome", "formica"]},
            "objects": [{"name": "counter stool", "role": "seating", "count": 4}],
            "game_concept": {"theme": "diner dash", "mechanics": "serve customers", "scoring": "tips earned", "win_condition": "shift complete"},
            "real_capabilities": [{"tool_type": "orders", "surface_binding": "counter", "read_only_v1": True}],
            "steering_stable": False,
            "response_to_user": "A 1950s diner — love it! Chrome stools, red vinyl, neon signs...",
        }
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            engine = ConversationEngine()
            response = await engine.interpret_response("Make it a 1950s diner")
            assert "1950s" in response or "diner" in response.lower() or "Chrome" in response
            assert engine.state.turn_count == 1
            assert engine.state.proposed_brief.get("room_purpose") == "diner"
            assert engine.is_stable is False

    @pytest.mark.asyncio
    async def test_interpret_response_detects_stability(self):
        """Req 1.8: Detect when steering stabilizes."""
        mock_response = {
            "interpretation": "User confirms the design",
            "room_purpose": "diner",
            "steering_stable": True,
            "response_to_user": "Perfect! Let me put the brief together.",
        }
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            engine = ConversationEngine()
            await engine.interpret_response("Yes, that's exactly what I want!")
            assert engine.is_stable is True

    @pytest.mark.asyncio
    async def test_extract_brief_produces_valid_brief(self):
        """Req 1.8, 2.1: Extract structured Brief from conversation."""
        mock_brief_json = {
            "room_purpose": "Danny's kitchenette",
            "atmosphere": {"mood": "warm", "lighting_direction": "soft overhead", "time_of_day": "evening"},
            "era": {"period": "contemporary", "style_exclusions": []},
            "palette": {"primary": "white", "accent": "wood", "material_finishes": ["matte"]},
            "object_manifest": [
                {"name": "round table", "role": "dining", "count": 1, "material_hint": "wood"},
                {"name": "chair", "role": "seating", "count": 2, "material_hint": "wood"},
            ],
            "game_concept": {"theme": "breakfast", "mechanics": "cook", "scoring": "dishes", "win_condition": "all fed"},
            "real_capabilities": [{"tool_type": "recipe", "surface_binding": "counter", "read_only_v1": True}],
            "success_criteria": "Cozy kitchen with rain outside",
        }
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_brief_json
            engine = ConversationEngine()
            brief = await engine.extract_brief()
            assert isinstance(brief, Brief)
            assert brief.room_purpose == "Danny's kitchenette"
            assert len(brief.object_manifest) == 2
            assert brief.object_manifest[0].id != ""  # Has UUID

    @pytest.mark.asyncio
    async def test_extract_brief_fallback_on_timeout(self):
        """Req 1.8: Fallback to schema-correct Brief on timeout."""
        from src.orchestrator.llm import LLMError
        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = LLMError("Timeout")
            engine = ConversationEngine()
            brief = await engine.extract_brief()
            assert isinstance(brief, Brief)
            # Should produce some valid Brief (default or from state)
            assert brief.room_purpose != "" or len(brief.object_manifest) > 0

    @pytest.mark.asyncio
    async def test_steering_loop_terminates_on_user_done(self):
        """Req 1.7: Steering loop handles user signaling done."""
        call_count = 0

        async def mock_input():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Make it a kitchen"
            return None  # Done

        mock_interpret = {
            "interpretation": "kitchen",
            "room_purpose": "kitchen",
            "steering_stable": False,
            "response_to_user": "A kitchen — great!",
        }
        mock_brief = {
            "room_purpose": "kitchen",
            "atmosphere": {"mood": "warm", "lighting_direction": "warm", "time_of_day": "morning"},
            "era": {"period": "modern", "style_exclusions": []},
            "palette": {"primary": "white", "accent": "wood", "material_finishes": []},
            "object_manifest": [{"name": "stove", "role": "cooking", "count": 1}],
            "game_concept": {"theme": "cooking", "mechanics": "prep", "scoring": "dishes", "win_condition": "dinner ready"},
            "real_capabilities": [],
            "success_criteria": "A working kitchen",
        }

        with patch("src.unified_pipeline.conversation.generate_json", new_callable=AsyncMock) as mock_gen:
            # First call is interpret, second is extract
            mock_gen.side_effect = [mock_interpret, mock_brief]
            engine = ConversationEngine(deadline=60.0)
            # Pre-add an opening turn so steering loop doesn't call generate_opening
            engine._state.turns.append(
                __import__("src.unified_pipeline.conversation", fromlist=["ConversationTurn"]).ConversationTurn(
                    role="assistant", content="Hello!"
                )
            )
            brief = await engine.run_steering_loop(mock_input)
            assert isinstance(brief, Brief)
            assert brief.room_purpose == "kitchen"
