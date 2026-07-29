"""Property-based tests for semantic labeling and heuristic fallback.

Uses Hypothesis to verify universal properties across all valid inputs.

Requirements: 13.3, 13.5
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.photo_pipeline.models_v14 import (
    VALID_CATEGORIES,
    VALID_CONDITIONS,
    VALID_MATERIALS,
    SemanticLabel,
)
from src.photo_pipeline.stages.semantic_labeler import SemanticLabeler


# ---------------------------------------------------------------------------
# Property 23: Heuristic Labeling Fallback Produces Valid Output
# ---------------------------------------------------------------------------


class TestHeuristicLabelingFallbackProperty:
    """Property 23: Heuristic Labeling Fallback Produces Valid Output.

    **Validates: Requirements 13.3**

    For any (width, height, area_px) inputs, the heuristic fallback SHALL
    produce a valid SemanticLabel with category from the 5 valid values
    and primary_material from the 6 valid values.
    """

    @given(
        width=st.integers(min_value=1, max_value=10000),
        height=st.integers(min_value=0, max_value=10000),
        area_px=st.integers(min_value=0, max_value=10_000_000),
    )
    @settings(max_examples=30)
    def test_fallback_always_produces_valid_semantic_label(
        self, width: int, height: int, area_px: int
    ) -> None:
        """For all valid dimension inputs, fallback_label returns a valid SemanticLabel."""
        labeler = SemanticLabeler()
        result = labeler.fallback_label(width, height, area_px)

        # Result must be a SemanticLabel instance
        assert isinstance(result, SemanticLabel), (
            f"Expected SemanticLabel, got {type(result).__name__}"
        )

        # Category must be one of the 5 valid values
        assert result.category in VALID_CATEGORIES, (
            f"category '{result.category}' not in {VALID_CATEGORIES}"
        )

        # Primary material must be one of the 6 valid values
        assert result.primary_material in VALID_MATERIALS, (
            f"primary_material '{result.primary_material}' not in {VALID_MATERIALS}"
        )

        # semantic_label must be non-empty
        assert result.semantic_label, "semantic_label must be non-empty"

        # estimated_era must be non-empty
        assert result.estimated_era, "estimated_era must be non-empty"

        # condition must be a valid condition value
        assert result.condition in VALID_CONDITIONS, (
            f"condition '{result.condition}' not in {VALID_CONDITIONS}"
        )
