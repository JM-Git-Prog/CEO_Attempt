"""Tests for conversation → Brief → ArtBible flow.

Tests the full pipeline from Danny's kitchenette canonical prompt through
Brief extraction to Art_Bible derivation, with mocked Ollama HTTP calls.

**Validates: Requirements 1.8, 2.5, 4.2**
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.unified_pipeline.conversation import ConversationEngine
from src.unified_pipeline.art_bible import ArtBibleDeriver, _fallback_art_bible
from src.unified_pipeline.models import (
    Brief,
    ArtBible,
    Atmosphere,
    Era,
    Palette,
    ManifestObject,
    GameConcept,
    RealCapability,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DANNY_KITCHENETTE_PROMPT = (
    "a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)

# Simulated LLM JSON response for opening prompt
MOCK_OPENING_RESPONSE = {
    "greeting": (
        "Welcome! I'm already picturing a cozy, rain-lit kitchenette — "
        "warm wood tones, a round table for two, soft afternoon light through "
        "a rain-streaked window. Let me know what resonates!"
    ),
    "proposed_era": "warm traditional",
    "proposed_mood": "intimate and rain-lit, afternoon warmth",
    "proposed_palette": "warm oak, copper accents, cream ceramic",
    "proposed_objects": ["round table", "spindle chairs", "counter", "coffee maker", "window"],
}

# Simulated LLM JSON response for interpret_response
MOCK_INTERPRET_RESPONSE = {
    "interpretation": "User wants a warm traditional kitchen with specific objects",
    "room_purpose": "cozy breakfast kitchen for quiet mornings",
    "atmosphere": {
        "mood": "warm and intimate",
        "lighting_direction": "natural from window",
        "time_of_day": "afternoon",
    },
    "era": {
        "period": "warm traditional",
        "style_exclusions": ["smart thermostat", "LED strip lighting", "industrial fixtures"],
    },
    "palette": {
        "primary": "#8B6914",
        "accent": "#B87333",
        "material_finishes": ["matte oak", "brushed copper", "cream ceramic"],
    },
    "objects": [
        {"name": "round table", "role": "furniture", "count": 1,
         "material_hint": "oak", "is_architectural": False},
        {"name": "chair", "role": "furniture", "count": 2,
         "material_hint": "wood spindle", "is_architectural": False},
        {"name": "counter", "role": "furniture", "count": 1,
         "material_hint": "butcher block", "is_architectural": True},
        {"name": "coffee maker", "role": "appliance", "count": 1,
         "material_hint": "brushed steel", "is_architectural": False},
        {"name": "window", "role": "architectural", "count": 1,
         "material_hint": "wood frame", "is_architectural": True},
    ],
    "game_concept": {
        "theme": "cozy morning routine",
        "mechanics": "brew and serve coffee in order",
        "scoring": "time-based with style bonus",
        "win_condition": "perfect cup served before timer",
    },
    "real_capabilities": [
        {"tool_type": "calendar", "surface_binding": "window", "read_only_v1": True},
        {"tool_type": "inbox", "surface_binding": "counter", "read_only_v1": True},
    ],
    "steering_stable": True,
    "response_to_user": (
        "I see a warm traditional kitchenette — oak table, spindle chairs, "
        "rain on the window. Let me put this together for you."
    ),
}

# Simulated LLM JSON response for Brief extraction
MOCK_BRIEF_EXTRACTION = {
    "room_purpose": "cozy breakfast kitchen for quiet mornings",
    "atmosphere": {
        "mood": "warm and intimate",
        "lighting_direction": "natural from window",
        "time_of_day": "afternoon",
    },
    "era": {
        "period": "warm traditional",
        "style_exclusions": ["smart thermostat", "LED strip lighting", "industrial fixtures"],
    },
    "palette": {
        "primary": "#8B6914",
        "accent": "#B87333",
        "material_finishes": ["matte oak", "brushed copper", "cream ceramic"],
    },
    "object_manifest": [
        {"name": "round table", "role": "furniture", "count": 1,
         "material_hint": "oak", "is_architectural": False},
        {"name": "chair", "role": "furniture", "count": 2,
         "material_hint": "wood spindle", "is_architectural": False},
        {"name": "counter", "role": "furniture", "count": 1,
         "material_hint": "butcher block", "is_architectural": True},
        {"name": "coffee maker", "role": "appliance", "count": 1,
         "material_hint": "brushed steel", "is_architectural": False},
        {"name": "window", "role": "architectural", "count": 1,
         "material_hint": "wood frame", "is_architectural": True},
    ],
    "game_concept": {
        "theme": "cozy morning routine",
        "mechanics": "brew and serve coffee in order",
        "scoring": "time-based with style bonus",
        "win_condition": "perfect cup served before timer",
    },
    "real_capabilities": [
        {"tool_type": "calendar", "surface_binding": "window", "read_only_v1": True},
        {"tool_type": "inbox", "surface_binding": "counter", "read_only_v1": True},
    ],
    "success_criteria": "A warm, rain-lit kitchen where everything feels touchable and real",
}

# Simulated LLM JSON response for Art Bible derivation
MOCK_ART_BIBLE_RESPONSE = json.dumps({
    "era_rules": {
        "belongs": ["warm wood furniture", "ceramic dishware", "natural textiles", "brass hardware"],
        "excludes": ["smart thermostat", "LED strips", "wireless speaker", "robot vacuum"],
    },
    "material_palette": [
        "warm oak (metallic=0.0, roughness=0.7)",
        "brushed copper (metallic=0.85, roughness=0.3)",
        "cream ceramic (metallic=0.0, roughness=0.4)",
        "cotton linen (metallic=0.0, roughness=0.9)",
    ],
    "lighting_direction": {
        "key": {"direction": "natural from window (left)", "color_temperature_k": 4000},
        "fill": {"direction": "ambient bounce from walls", "color_temperature_k": 5000},
        "accent": {"direction": "under-cabinet warm", "color_temperature_k": 2700},
    },
    "color_palette": ["#8B6914", "#B87333", "#F5F0E8", "#4A3728", "#E8DCC8"],
    "prop_style": {
        "silhouette_language": "rounded, classic proportions",
        "detail_level": "medium",
        "wear_patina": "light surface wear — lived-in but cared for",
    },
    "era_exclusions": [
        "smart thermostat",
        "LED strip lighting",
        "wireless speaker",
        "robot vacuum",
        "minimalist furniture",
        "industrial fixtures",
        "futuristic appliances",
    ],
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_generate_json():
    """Mock generate_json to return appropriate responses based on call context."""
    call_count = {"value": 0}

    async def _mock_generate(system, user, model=None, *, timeout_seconds=None):
        call_count["value"] += 1
        # Determine what kind of call this is based on system prompt content
        if "opening" in system.lower() or "greet" in system.lower():
            return MOCK_OPENING_RESPONSE
        elif "extract" in system.lower() or "final structured brief" in system.lower():
            return MOCK_BRIEF_EXTRACTION
        else:
            # interpret_response / general calls
            return MOCK_INTERPRET_RESPONSE

    with patch("src.unified_pipeline.conversation.generate_json", new=_mock_generate):
        yield _mock_generate


@pytest.fixture
def mock_art_bible_ollama():
    """Mock _call_ollama_json for art bible derivation."""
    async def _mock_call(system, user, *, timeout=30):
        return MOCK_ART_BIBLE_RESPONSE

    with patch("src.unified_pipeline.art_bible._call_ollama_json", new=_mock_call):
        yield _mock_call


# ---------------------------------------------------------------------------
# Test 1: ConversationEngine.generate_opening() returns non-empty prompt
# ---------------------------------------------------------------------------

class TestStartSession:
    """Verify generate_opening produces a valid opening prompt."""

    @pytest.mark.asyncio
    async def test_returns_nonempty_opening_prompt(self, mock_generate_json):
        """generate_opening() returns a non-empty opening prompt.

        **Validates: Requirements 1.8**
        """
        engine = ConversationEngine()
        prompt = await engine.generate_opening()

        assert prompt is not None
        assert len(prompt) > 0
        assert isinstance(prompt, str)

    @pytest.mark.asyncio
    async def test_session_id_assigned(self, mock_generate_json):
        """ConversationEngine creates a valid session ID on init.

        **Validates: Requirements 1.8**
        """
        engine = ConversationEngine()

        # Session ID should be a valid UUID
        session_id = engine.state.session_id
        assert session_id
        uuid.UUID(session_id)  # raises if invalid


# ---------------------------------------------------------------------------
# Test 2: interpret_response with Danny's kitchenette prompt (mocked Ollama)
# ---------------------------------------------------------------------------

class TestProcessMessage:
    """Verify interpret_response handles user input and returns AI response."""

    @pytest.mark.asyncio
    async def test_produces_response_for_kitchenette_prompt(self, mock_generate_json):
        """interpret_response with Danny's kitchenette prompt returns non-empty response.

        **Validates: Requirements 1.8**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        response = await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)

        assert response is not None
        assert len(response) > 0
        assert isinstance(response, str)


# ---------------------------------------------------------------------------
# Test 3: extract_brief returns Brief with all required fields
# ---------------------------------------------------------------------------

class TestExtractBrief:
    """Verify Brief extraction produces complete structured data."""

    @pytest.mark.asyncio
    async def test_brief_has_all_required_fields(self, mock_generate_json):
        """extract_brief() returns a Brief with all required fields populated.

        **Validates: Requirements 1.8, 2.5**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        # All required fields present and non-empty
        assert brief.room_purpose != ""
        assert brief.atmosphere.mood != ""
        assert brief.atmosphere.lighting_direction != ""
        assert brief.atmosphere.time_of_day != ""
        assert brief.era.period != ""
        assert brief.era.style_exclusions  # non-empty tuple
        assert brief.palette.primary != ""
        assert brief.palette.accent != ""
        assert brief.palette.material_finishes  # non-empty tuple
        assert len(brief.object_manifest) > 0
        assert brief.game_concept.theme != ""
        assert brief.game_concept.mechanics != ""
        assert brief.game_concept.scoring != ""
        assert brief.game_concept.win_condition != ""
        assert len(brief.real_capabilities) > 0
        assert all(cap.read_only_v1 is True for cap in brief.real_capabilities)
        assert "rain" in brief.success_criteria.lower()
        assert brief.provenance["source_prompt"] == DANNY_KITCHENETTE_PROMPT
        assert len(brief.provenance["source_prompt_sha256"]) == 64


# ---------------------------------------------------------------------------
# Test 4: UUID stability — same manifest → same UUIDs preserved on re-extraction
# ---------------------------------------------------------------------------

class TestUUIDStability:
    """Verify object manifest UUIDs are stable across Brief instances."""

    @pytest.mark.asyncio
    async def test_uuids_are_valid_uuid4(self, mock_generate_json):
        """Each object in the manifest has a valid UUID.

        **Validates: Requirements 1.8, 2.5**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        for obj in brief.object_manifest:
            assert obj.id, f"Object '{obj.name}' missing UUID"
            # Should be a valid UUID string
            parsed = uuid.UUID(obj.id)
            assert str(parsed) == obj.id

    @pytest.mark.asyncio
    async def test_uuids_unique_per_object(self, mock_generate_json):
        """Each object in the manifest has a unique UUID.

        **Validates: Requirements 1.8, 2.5**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        ids = [obj.id for obj in brief.object_manifest]
        assert len(ids) == len(set(ids)), f"Duplicate UUIDs found: {ids}"

    @pytest.mark.asyncio
    async def test_manifest_uuids_persist_through_serialization(self, mock_generate_json):
        """UUIDs survive a to_dict/from_dict round-trip.

        **Validates: Requirements 1.8, 2.5**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        # Round-trip through dict
        brief_dict = brief.to_dict()
        restored = Brief.from_dict(brief_dict)

        assert len(restored.object_manifest) == len(brief.object_manifest)
        for orig, rest in zip(brief.object_manifest, restored.object_manifest):
            assert orig.id == rest.id, (
                f"UUID changed for '{orig.name}': {orig.id} → {rest.id}"
            )


# ---------------------------------------------------------------------------
# Test 5: ArtBibleDeriver.derive(brief) returns ArtBible with era_exclusions
# ---------------------------------------------------------------------------

class TestArtBibleDerivation:
    """Verify ArtBible derivation from Brief produces era_exclusions."""

    @pytest.mark.asyncio
    async def test_derive_returns_art_bible_with_era_exclusions(
        self, mock_generate_json, mock_art_bible_ollama
    ):
        """ArtBibleDeriver.derive(brief) returns ArtBible with era_exclusions populated.

        **Validates: Requirements 4.2**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        deriver = ArtBibleDeriver()
        art_bible = await deriver.derive(brief)

        assert isinstance(art_bible, ArtBible)
        assert len(art_bible.era_exclusions) > 0
        assert art_bible.era_rules is not None
        assert len(art_bible.material_palette) > 0
        assert art_bible.lighting_direction is not None
        assert len(art_bible.color_palette) > 0
        assert art_bible.prop_style is not None


# ---------------------------------------------------------------------------
# Test 6: Era exclusions contain reasonable entries (no futuristic items)
# ---------------------------------------------------------------------------

class TestEraExclusionsContent:
    """Verify era exclusions are reasonable for a warm traditional kitchen."""

    @pytest.mark.asyncio
    async def test_no_futuristic_items_in_traditional_kitchen(
        self, mock_generate_json, mock_art_bible_ollama
    ):
        """Era exclusions should ban futuristic/anachronistic items for warm traditional era.

        **Validates: Requirements 4.2**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        deriver = ArtBibleDeriver()
        art_bible = await deriver.derive(brief)

        exclusions_lower = [e.lower() for e in art_bible.era_exclusions]

        # A warm traditional kitchen should exclude futuristic items
        futuristic_keywords = ["smart", "led", "wireless", "robot"]
        found_any = any(
            any(kw in excl for kw in futuristic_keywords)
            for excl in exclusions_lower
        )
        assert found_any, (
            f"Expected futuristic items excluded for warm traditional era. "
            f"Got exclusions: {art_bible.era_exclusions}"
        )

    def test_fallback_art_bible_has_exclusions_for_warm_traditional(self):
        """Direct test: fallback Art Bible for warm traditional Brief has era exclusions.

        **Validates: Requirements 4.2**
        """
        brief = Brief(
            room_purpose="kitchen",
            atmosphere=Atmosphere(
                mood="warm", lighting_direction="natural", time_of_day="afternoon"
            ),
            era=Era(
                period="warm traditional",
                style_exclusions=("smart thermostat", "industrial fixtures"),
            ),
            palette=Palette(
                primary="#8B6914", accent="#B87333",
                material_finishes=("matte oak", "brushed copper"),
            ),
            object_manifest=(
                ManifestObject(name="table", role="furniture"),
                ManifestObject(name="chair", role="furniture", count=2),
            ),
            game_concept=GameConcept(
                theme="cooking", mechanics="prep",
                scoring="time", win_condition="serve",
            ),
            real_capabilities=(
                RealCapability(tool_type="calendar", surface_binding="wall"),
            ),
            success_criteria="cozy kitchen",
        )

        art_bible = _fallback_art_bible(brief)

        # Should include the Brief's own exclusions
        assert "smart thermostat" in art_bible.era_exclusions
        assert "industrial fixtures" in art_bible.era_exclusions
        # Should have at least the user-specified exclusions
        assert len(art_bible.era_exclusions) >= 2


# ---------------------------------------------------------------------------
# Test 7: Brief completeness — all fields non-empty after extraction
# ---------------------------------------------------------------------------

class TestBriefCompleteness:
    """Verify all Brief fields populated after Danny's kitchenette extraction."""

    @pytest.mark.asyncio
    async def test_all_fields_nonempty(self, mock_generate_json):
        """Every Brief field is populated after extraction from Danny's kitchenette prompt.

        **Validates: Requirements 1.8, 2.5**
        """
        engine = ConversationEngine()
        await engine.generate_opening()
        await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
        brief = await engine.extract_brief()

        # Top-level fields
        assert brief.room_purpose, "room_purpose is empty"
        assert brief.success_criteria, "success_criteria is empty"

        # Atmosphere sub-fields
        assert brief.atmosphere.mood, "atmosphere.mood is empty"
        assert brief.atmosphere.lighting_direction, "atmosphere.lighting_direction is empty"
        assert brief.atmosphere.time_of_day, "atmosphere.time_of_day is empty"

        # Era sub-fields
        assert brief.era.period, "era.period is empty"
        assert brief.era.style_exclusions, "era.style_exclusions is empty"

        # Palette sub-fields
        assert brief.palette.primary, "palette.primary is empty"
        assert brief.palette.accent, "palette.accent is empty"
        assert brief.palette.material_finishes, "palette.material_finishes is empty"

        # Object manifest — kitchenette should have 5 objects
        assert len(brief.object_manifest) >= 3, (
            f"Expected at least 3 objects, got {len(brief.object_manifest)}"
        )
        for obj in brief.object_manifest:
            assert obj.id, f"Object '{obj.name}' missing UUID"
            assert obj.name, "Object missing name"
            assert obj.role, f"Object '{obj.name}' missing role"

        # Game concept
        assert brief.game_concept.theme, "game_concept.theme is empty"
        assert brief.game_concept.mechanics, "game_concept.mechanics is empty"
        assert brief.game_concept.scoring, "game_concept.scoring is empty"
        assert brief.game_concept.win_condition, "game_concept.win_condition is empty"

        # Real capabilities
        assert len(brief.real_capabilities) >= 1, "No real_capabilities"
        for cap in brief.real_capabilities:
            assert cap.tool_type, "real_capability missing tool_type"
            assert cap.surface_binding, "real_capability missing surface_binding"


# ---------------------------------------------------------------------------
# Test 8: Fallback — valid Brief even on Ollama timeout (30s deadline)
# ---------------------------------------------------------------------------

class TestFallbackBrief:
    """Verify fallback produces a valid Brief when Ollama is unavailable."""

    @pytest.mark.asyncio
    async def test_timeout_produces_valid_fallback_brief(self):
        """ConversationEngine produces valid Brief on Ollama timeout (30s deadline → fallback).

        **Validates: Requirements 1.8, 2.5**
        """
        from src.orchestrator.llm import LLMError

        async def _timeout_generate(system, user, model=None, *, timeout_seconds=None):
            raise LLMError("Ollama timed out after 30s")

        with patch("src.unified_pipeline.conversation.generate_json", new=_timeout_generate):
            engine = ConversationEngine()

            # generate_opening should not raise — falls back gracefully
            opening = await engine.generate_opening()
            assert opening  # fallback greeting is non-empty

            # interpret_response should not raise — marks as stable on failure
            response = await engine.interpret_response(DANNY_KITCHENETTE_PROMPT)
            assert response  # fallback response is non-empty

            # extract_brief should produce a schema-correct Brief from state
            brief = await engine.extract_brief()

            # Validate the fallback Brief is schema-complete
            assert isinstance(brief, Brief)
            assert brief.room_purpose != "" or brief.object_manifest  # has something useful
            assert brief.atmosphere.mood != ""
            assert brief.game_concept.theme != ""

    @pytest.mark.asyncio
    async def test_timeout_art_bible_fallback(self):
        """ArtBibleDeriver produces valid ArtBible on Ollama timeout.

        **Validates: Requirements 4.2**
        """
        import httpx

        async def _timeout_call(system, user, *, timeout=30):
            raise httpx.TimeoutException("Connection timed out")

        brief = Brief(
            room_purpose="kitchen",
            atmosphere=Atmosphere(
                mood="warm", lighting_direction="natural", time_of_day="afternoon"
            ),
            era=Era(period="warm traditional", style_exclusions=("smart thermostat",)),
            palette=Palette(primary="#8B6914", accent="#B87333", material_finishes=("oak",)),
            object_manifest=(ManifestObject(name="table", role="furniture"),),
            game_concept=GameConcept(theme="cooking", mechanics="prep", scoring="time", win_condition="serve"),
            real_capabilities=(),
            success_criteria="cozy kitchen",
        )

        with patch("src.unified_pipeline.art_bible._call_ollama_json", new=_timeout_call):
            deriver = ArtBibleDeriver()
            art_bible = await deriver.derive(brief)

            assert isinstance(art_bible, ArtBible)
            assert len(art_bible.era_exclusions) > 0
            assert len(art_bible.material_palette) > 0
            assert art_bible.lighting_direction is not None
