"""Property-based tests for input length validation.

**Validates: Requirements 1.6**

Uses Hypothesis to verify that validate_input rejects iff char count < 3 or > 500,
and that no LLM invocation occurs on rejection (stage is always "input_validation").
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models import StageFailure
from src.pipeline import validate_input


class TestShortStringsAlwaysRejected:
    """Property: any string with len < 3 must be rejected."""

    @given(st.text(max_size=2))
    @settings(max_examples=200, deadline=None)
    def test_short_strings_always_rejected(self, s: str):
        """For any string with len < 3, validate_input returns a StageFailure (not None)."""
        result = validate_input(s)
        assert result is not None, f"Expected rejection for string of length {len(s)!r}, got None"
        assert isinstance(result, StageFailure)


class TestLongStringsAlwaysRejected:
    """Property: any string with len > 500 must be rejected."""

    @given(
        st.integers(min_value=501, max_value=1000).flatmap(
            lambda n: st.text(min_size=n, max_size=n)
        )
    )
    @settings(max_examples=200, deadline=None)
    def test_long_strings_always_rejected(self, s: str):
        """For any string with len > 500, validate_input returns a StageFailure."""
        result = validate_input(s)
        assert result is not None, f"Expected rejection for string of length {len(s)}, got None"
        assert isinstance(result, StageFailure)


class TestValidLengthStringsAlwaysAccepted:
    """Property: any string with 3 <= len <= 500 must be accepted."""

    @given(st.text(min_size=3, max_size=500).filter(lambda s: len(s) >= 3))
    @settings(max_examples=200, deadline=None)
    def test_valid_length_strings_always_accepted(self, s: str):
        """For any string with 3 <= len <= 500, validate_input returns None."""
        result = validate_input(s)
        assert result is None, (
            f"Expected acceptance for string of length {len(s)}, "
            f"got StageFailure(reason_code={result.reason_code!r})"
        )


class TestRejectionIffLengthOutOfBounds:
    """Core property: for ANY string, rejection iff len < 3 or len > 500."""

    @given(st.text(max_size=1000))
    @settings(max_examples=300, deadline=None)
    def test_rejection_iff_length_out_of_bounds(self, s: str):
        """The bidirectional implication: rejected ⟺ len < 3 or len > 500."""
        result = validate_input(s)
        out_of_bounds = len(s) < 3 or len(s) > 500

        if out_of_bounds:
            assert result is not None, (
                f"String of length {len(s)} should be rejected but was accepted"
            )
            assert isinstance(result, StageFailure)
        else:
            assert result is None, (
                f"String of length {len(s)} should be accepted but was rejected "
                f"with reason_code={result.reason_code!r}"
            )


class TestNoLLMInvocationOnRejection:
    """Property: rejected inputs have stage='input_validation' and no LLM stage name."""

    @given(st.text(max_size=1000))
    @settings(max_examples=200, deadline=None)
    def test_no_llm_invocation_on_rejection(self, s: str):
        """For rejected inputs, verify stage is 'input_validation' — no LLM stage appears."""
        result = validate_input(s)
        if result is not None:
            # Stage must be input_validation, not any LLM stage
            assert result.stage == "input_validation", (
                f"Rejected input has stage={result.stage!r}, expected 'input_validation'"
            )
            # Ensure no LLM-related stage names appear
            llm_stages = {"planning", "interpretation", "generation", "llm", "model"}
            assert result.stage not in llm_stages, (
                f"Rejection should not involve LLM stage, but got stage={result.stage!r}"
            )
