"""Property-based tests for quality label determination.

**Validates: Requirements 8.5**

Uses Hypothesis to verify that determine_quality_label returns the correct quality
label for all (parity_passed, smoke_passed) boolean combinations, and that the
output is always one of the three valid labels.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.stage_result import determine_quality_label

VALID_LABELS = {"smoke_structural", "smoke_skipped", "parity_only"}


class TestParityAndSmokePassed:
    """Property: parity_passed=True AND smoke_passed=True → 'smoke_structural'."""

    @given(st.just(True), st.just(True))
    @settings(max_examples=200, deadline=None)
    def test_both_passed_returns_smoke_structural(self, parity: bool, smoke: bool):
        """When both parity and smoke pass, label is 'smoke_structural'."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)
        assert result == "smoke_structural", (
            f"Expected 'smoke_structural' for parity=True, smoke=True, got {result!r}"
        )


class TestParityPassedSmokeFailed:
    """Property: parity_passed=True AND smoke_passed=False → 'smoke_skipped'."""

    @given(st.just(True), st.just(False))
    @settings(max_examples=200, deadline=None)
    def test_parity_passed_smoke_failed_returns_smoke_skipped(self, parity: bool, smoke: bool):
        """When parity passes but smoke fails, label is 'smoke_skipped'."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)
        assert result == "smoke_skipped", (
            f"Expected 'smoke_skipped' for parity=True, smoke=False, got {result!r}"
        )


class TestParityFailed:
    """Property: parity_passed=False (regardless of smoke) → 'parity_only'."""

    @given(st.just(False), st.booleans())
    @settings(max_examples=200, deadline=None)
    def test_parity_failed_returns_parity_only(self, parity: bool, smoke: bool):
        """When parity fails, label is always 'parity_only' regardless of smoke."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)
        assert result == "parity_only", (
            f"Expected 'parity_only' for parity=False, smoke={smoke}, got {result!r}"
        )


class TestExhaustivenessAndValidity:
    """Property: for ANY boolean pair, the label is always one of the three valid values."""

    @given(st.booleans(), st.booleans())
    @settings(max_examples=200, deadline=None)
    def test_label_always_in_valid_set(self, parity: bool, smoke: bool):
        """The return value is always one of the three defined quality labels."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)
        assert result in VALID_LABELS, (
            f"Got unexpected label {result!r} for parity={parity}, smoke={smoke}. "
            f"Valid labels are: {VALID_LABELS}"
        )

    @given(st.booleans(), st.booleans())
    @settings(max_examples=200, deadline=None)
    def test_label_is_non_empty_string(self, parity: bool, smoke: bool):
        """The return value is always a non-empty string."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)
        assert isinstance(result, str), (
            f"Expected str, got {type(result).__name__} for parity={parity}, smoke={smoke}"
        )
        assert len(result) > 0, (
            f"Expected non-empty string for parity={parity}, smoke={smoke}"
        )


class TestCorrectMappingForAllInputs:
    """Core property: the full mapping is correct for any (parity, smoke) pair."""

    @given(st.booleans(), st.booleans())
    @settings(max_examples=200, deadline=None)
    def test_correct_mapping(self, parity: bool, smoke: bool):
        """Verify the complete decision logic for all boolean combinations."""
        result = determine_quality_label(parity_passed=parity, smoke_passed=smoke)

        if parity and smoke:
            expected = "smoke_structural"
        elif parity and not smoke:
            expected = "smoke_skipped"
        else:
            expected = "parity_only"

        assert result == expected, (
            f"For parity={parity}, smoke={smoke}: expected {expected!r}, got {result!r}"
        )
