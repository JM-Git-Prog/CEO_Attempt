"""Unit tests for ArtBibleDeriver.

Tests fallback derivation, lock/immutability enforcement, and ArtBible structure.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**
"""

from __future__ import annotations

import asyncio
import pytest

from src.unified_pipeline.art_bible import (
    ArtBibleDeriver,
    ArtBibleError,
    ArtBibleLockedError,
    _fallback_art_bible,
    _art_bible_from_dict,
    _build_brief_context,
)
from src.unified_pipeline.models import (
    ArtBible,
    Atmosphere,
    Brief,
    Era,
    ManifestObject,
    Palette,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def danny_kitchenette_brief() -> Brief:
    """Danny's kitchenette — the canonical test Brief."""
    return Brief(
        room_purpose="A small, warm kitchen for morning coffee and cooking",
        atmosphere=Atmosphere(
            mood="warm and cozy",
            lighting_direction="warm overhead pendant",
            time_of_day="morning",
        ),
        era=Era(
            period="1950s diner",
            style_exclusions=(
                "smart thermostats",
                "LED strip lights",
                "USB outlets",
            ),
        ),
        palette=Palette(
            primary="warm wood",
            accent="brass",
            material_finishes=("matte wood", "brushed brass", "ceramic tile"),
        ),
        object_manifest=(
            ManifestObject(name="round table", role="dining surface", count=1, material_hint="wood"),
            ManifestObject(name="chair", role="seating", count=2, material_hint="wood"),
            ManifestObject(name="counter", role="prep surface", count=1, material_hint="laminate", is_architectural=True),
            ManifestObject(name="coffee maker", role="appliance", count=1, material_hint="chrome"),
        ),
    )


@pytest.fixture
def minimal_brief() -> Brief:
    """Minimal Brief with defaults."""
    return Brief(room_purpose="a simple room")


# ─── Fallback Derivation Tests ─────────────────────────────────────────────────


class TestFallbackArtBible:
    """Test the fallback derivation path (no Ollama)."""

    def test_fallback_produces_valid_art_bible(self, danny_kitchenette_brief: Brief):
        """Fallback should produce a complete ArtBible with all required fields."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert isinstance(art_bible, ArtBible)
        assert art_bible.era_rules is not None
        assert art_bible.material_palette
        assert art_bible.lighting_direction
        assert art_bible.color_palette
        assert art_bible.prop_style
        assert art_bible.immutable is False

    def test_fallback_era_rules_structure(self, danny_kitchenette_brief: Brief):
        """Req 4.1: era_rules contains 'belongs' and 'excludes' lists."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert "belongs" in art_bible.era_rules
        assert "excludes" in art_bible.era_rules
        assert isinstance(art_bible.era_rules["belongs"], list)
        assert isinstance(art_bible.era_rules["excludes"], list)

    def test_fallback_era_exclusions_from_brief(self, danny_kitchenette_brief: Brief):
        """Req 4.2: Era exclusions include Brief's style_exclusions."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert "smart thermostats" in art_bible.era_exclusions
        assert "LED strip lights" in art_bible.era_exclusions
        assert "USB outlets" in art_bible.era_exclusions

    def test_fallback_material_palette_from_brief(self, danny_kitchenette_brief: Brief):
        """Req 4.1: material_palette derived from Brief palette."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        # Should use material_finishes when available
        assert "matte wood" in art_bible.material_palette
        assert "brushed brass" in art_bible.material_palette
        assert "ceramic tile" in art_bible.material_palette

    def test_fallback_lighting_direction_structure(self, danny_kitchenette_brief: Brief):
        """Req 4.1: lighting_direction has key/fill/accent with color temps."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert "key" in art_bible.lighting_direction
        assert "fill" in art_bible.lighting_direction
        assert "accent" in art_bible.lighting_direction
        assert "color_temperature_k" in art_bible.lighting_direction["key"]
        assert "direction" in art_bible.lighting_direction["key"]

    def test_fallback_color_palette_is_tuple_of_hex(self, danny_kitchenette_brief: Brief):
        """Req 4.1: color_palette is a tuple of hex values."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert isinstance(art_bible.color_palette, tuple)
        for color in art_bible.color_palette:
            assert color.startswith("#")
            assert len(color) == 7  # #RRGGBB

    def test_fallback_prop_style_structure(self, danny_kitchenette_brief: Brief):
        """Req 4.1: prop_style has silhouette_language, detail_level, wear_patina."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)

        assert "silhouette_language" in art_bible.prop_style
        assert "detail_level" in art_bible.prop_style
        assert "wear_patina" in art_bible.prop_style

    def test_fallback_with_minimal_brief(self, minimal_brief: Brief):
        """Fallback gracefully handles Brief with minimal/empty fields."""
        art_bible = _fallback_art_bible(minimal_brief)

        assert isinstance(art_bible, ArtBible)
        assert art_bible.era_rules is not None
        assert art_bible.lighting_direction is not None
        assert art_bible.color_palette  # Should have defaults


# ─── ArtBible from Dict Tests ─────────────────────────────────────────────────


class TestArtBibleFromDict:
    """Test _art_bible_from_dict parsing of LLM responses."""

    def test_complete_dict(self):
        """Full valid JSON produces complete ArtBible."""
        data = {
            "era_rules": {
                "belongs": ["chrome stools", "formica countertops"],
                "excludes": ["USB chargers", "smart displays"],
            },
            "material_palette": [
                "chrome (metallic=0.95, roughness=0.1)",
                "formica (metallic=0.0, roughness=0.4)",
            ],
            "lighting_direction": {
                "key": {"direction": "overhead pendant", "color_temperature_k": 3200},
                "fill": {"direction": "window natural", "color_temperature_k": 5600},
                "accent": {"direction": "under-cabinet", "color_temperature_k": 2800},
            },
            "color_palette": ["#FF5733", "#C9A961", "#F4F1DE", "#264653", "#E76F51"],
            "prop_style": {
                "silhouette_language": "rounded mid-century curves",
                "detail_level": "medium",
                "wear_patina": "chrome shows wear at edges, formica lightly scratched",
            },
            "era_exclusions": [
                "no smart thermostats in a 1950s diner",
                "no flat-screen displays",
                "no USB charging ports",
            ],
        }

        art_bible = _art_bible_from_dict(data)

        assert art_bible.era_rules["belongs"] == ["chrome stools", "formica countertops"]
        assert art_bible.era_rules["excludes"] == ["USB chargers", "smart displays"]
        assert len(art_bible.material_palette) == 2
        assert len(art_bible.color_palette) == 5
        assert art_bible.prop_style["detail_level"] == "medium"
        assert len(art_bible.era_exclusions) == 3

    def test_empty_dict_produces_empty_art_bible(self):
        """Empty dict produces ArtBible with empty collections."""
        art_bible = _art_bible_from_dict({})

        assert art_bible.era_rules == {"belongs": [], "excludes": []}
        assert art_bible.material_palette == ()
        assert art_bible.lighting_direction == {}
        assert art_bible.color_palette == ()
        assert art_bible.prop_style == {}
        assert art_bible.era_exclusions == ()

    def test_malformed_era_rules_handled(self):
        """Non-dict era_rules gets replaced with default structure."""
        data = {"era_rules": "not a dict"}
        art_bible = _art_bible_from_dict(data)
        assert art_bible.era_rules == {"belongs": [], "excludes": []}


# ─── ArtBibleDeriver Tests ─────────────────────────────────────────────────────


class TestArtBibleDeriver:
    """Test the ArtBibleDeriver class behavior."""

    def test_initial_state(self):
        """Deriver starts unlocked with no art_bible."""
        deriver = ArtBibleDeriver()
        assert deriver.is_locked() is False
        assert deriver.art_bible is None

    def test_lock_sets_locked(self):
        """Req 4.4: lock() sets immutable flag."""
        deriver = ArtBibleDeriver()
        deriver.lock()
        assert deriver.is_locked() is True

    def test_derive_after_lock_raises(self, danny_kitchenette_brief: Brief):
        """Req 4.4: derive() raises ArtBibleLockedError when locked."""
        deriver = ArtBibleDeriver()
        deriver.lock()

        with pytest.raises(ArtBibleLockedError):
            asyncio.run(deriver.derive(danny_kitchenette_brief))

    def test_derive_fallback_when_ollama_unavailable(self, danny_kitchenette_brief: Brief):
        """Derive falls back gracefully when Ollama is unavailable."""
        # Use an invalid URL to force fallback
        deriver = ArtBibleDeriver(timeout=1.0)

        # Set env to invalid URL temporarily
        import os
        original_url = os.environ.get("OLLAMA_URL", "")
        os.environ["OLLAMA_URL"] = "http://localhost:99999"

        try:
            # This should fall back, not raise
            art_bible = asyncio.run(deriver.derive(danny_kitchenette_brief))
            assert isinstance(art_bible, ArtBible)
            assert deriver.art_bible is art_bible
        finally:
            if original_url:
                os.environ["OLLAMA_URL"] = original_url
            else:
                os.environ.pop("OLLAMA_URL", None)

    def test_custom_model_and_timeout(self):
        """Constructor accepts custom model and timeout."""
        deriver = ArtBibleDeriver(model="custom:latest", timeout=60.0)
        assert deriver._model == "custom:latest"
        assert deriver._timeout == 60.0


# ─── Brief Context Builder Tests ──────────────────────────────────────────────


class TestBriefContextBuilder:
    """Test _build_brief_context output formatting."""

    def test_includes_room_purpose(self, danny_kitchenette_brief: Brief):
        context = _build_brief_context(danny_kitchenette_brief, None)
        assert "small, warm kitchen" in context

    def test_includes_era(self, danny_kitchenette_brief: Brief):
        context = _build_brief_context(danny_kitchenette_brief, None)
        assert "1950s diner" in context

    def test_includes_objects(self, danny_kitchenette_brief: Brief):
        context = _build_brief_context(danny_kitchenette_brief, None)
        assert "round table" in context
        assert "coffee maker" in context

    def test_includes_dream_preview_reference(self, danny_kitchenette_brief: Brief):
        context = _build_brief_context(danny_kitchenette_brief, "/path/to/dream.png")
        assert "/path/to/dream.png" in context
        assert "Dream_Preview" in context

    def test_no_dream_preview_when_none(self, danny_kitchenette_brief: Brief):
        context = _build_brief_context(danny_kitchenette_brief, None)
        assert "Dream_Preview" not in context


# ─── Round-Trip Serialization Test ─────────────────────────────────────────────


class TestArtBibleSerialization:
    """Test ArtBible to_dict/from_dict round-trip."""

    def test_round_trip(self, danny_kitchenette_brief: Brief):
        """ArtBible serializes and deserializes correctly."""
        art_bible = _fallback_art_bible(danny_kitchenette_brief)
        serialized = art_bible.to_dict()
        restored = ArtBible.from_dict(serialized)

        assert restored.era_rules == art_bible.era_rules
        assert restored.material_palette == art_bible.material_palette
        assert restored.lighting_direction == art_bible.lighting_direction
        assert restored.color_palette == art_bible.color_palette
        assert restored.prop_style == art_bible.prop_style
        assert restored.era_exclusions == art_bible.era_exclusions
        assert restored.immutable == art_bible.immutable
