"""Unit tests for input validation gate.

Validates: Requirements 1.6
- Empty string → rejection
- Strings < 3 characters → rejection
- Strings of exactly 3 characters → acceptance
- Strings of exactly 500 characters → acceptance
- Strings > 500 characters → rejection
- Normal descriptions → acceptance
"""

from __future__ import annotations

from src.pipeline import validate_input


class TestInputValidationRejections:
    """Test cases where validate_input should return a StageFailure."""

    def test_empty_string_rejected(self):
        result = validate_input("")
        assert result is not None
        assert result.stage == "input_validation"
        assert result.reason_code == "empty_input"
        assert "empty" in result.diagnostic.lower()

    def test_none_rejected(self):
        result = validate_input(None)
        assert result is not None
        assert result.stage == "input_validation"
        assert result.reason_code == "empty_input"

    def test_one_character_rejected(self):
        result = validate_input("a")
        assert result is not None
        assert result.stage == "input_validation"
        assert result.reason_code == "too_short"
        assert "minimum 3" in result.diagnostic

    def test_two_characters_rejected(self):
        result = validate_input("ab")
        assert result is not None
        assert result.stage == "input_validation"
        assert result.reason_code == "too_short"
        assert "minimum 3" in result.diagnostic

    def test_501_characters_rejected(self):
        result = validate_input("x" * 501)
        assert result is not None
        assert result.stage == "input_validation"
        assert result.reason_code == "too_long"
        assert "maximum 500" in result.diagnostic

    def test_very_long_string_rejected(self):
        result = validate_input("a" * 1000)
        assert result is not None
        assert result.reason_code == "too_long"


class TestInputValidationAcceptance:
    """Test cases where validate_input should return None (accepted)."""

    def test_three_characters_accepted(self):
        result = validate_input("abc")
        assert result is None

    def test_500_characters_accepted(self):
        result = validate_input("x" * 500)
        assert result is None

    def test_normal_description_accepted(self):
        result = validate_input("A cozy living room with a fireplace and leather sofa")
        assert result is None

    def test_minimal_valid_description(self):
        result = validate_input("big")
        assert result is None

    def test_description_at_boundary(self):
        # Exactly 499 chars — should pass
        result = validate_input("y" * 499)
        assert result is None


class TestInputValidationMetadata:
    """Test that StageFailure metadata is correct."""

    def test_all_rejections_are_not_recoverable(self):
        for desc in ["", "a", "x" * 501]:
            result = validate_input(desc)
            assert result is not None
            assert result.recoverable is False

    def test_stage_is_always_input_validation(self):
        for desc in ["", "ab", "z" * 600]:
            result = validate_input(desc)
            assert result is not None
            assert result.stage == "input_validation"
