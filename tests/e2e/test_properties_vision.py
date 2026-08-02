"""Property-based tests for vision verdict structure and routing.

Tests the correctness property specified in the design document:

Property 17: Vision Verdict Structure
    For any response from the qwen2.5vl:7b vision model, the structured output
    SHALL contain `pass` (boolean), `failed_checks` (list of strings), and
    `confidence` (float 0.0-1.0). Auto-acceptance SHALL occur only when
    `pass == true` AND `confidence >= 0.8`.

**Validates: Requirements 20.2, 20.3**

Testing framework: Hypothesis (as specified in design document)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# Use a reasonable max_examples for CI performance
_SETTINGS = settings(deadline=None, max_examples=100, suppress_health_check=[HealthCheck.too_slow])


# ---------------------------------------------------------------------------
# Domain models for property testing
# ---------------------------------------------------------------------------

# The seven-category QA checklist items (from the design doc)
SEVEN_CATEGORY_CHECKS = [
    "geometry",
    "count",
    "camera",
    "openings",
    "finish",
    "mood",
    "scale",
]

# Auto-acceptance threshold (from design doc and requirements 20.3)
AUTO_ACCEPT_CONFIDENCE_THRESHOLD = 0.8


@dataclass
class VisionVerdict:
    """Structured verdict from the qwen2.5vl:7b vision model.

    Requirements 20.2 specifies: structured JSON verdict containing
    `pass` (boolean), `failed_checks` (list), and `confidence` (0.0-1.0).
    """

    pass_: bool  # `pass` in the JSON output (reserved word in Python)
    failed_checks: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# Implementation-under-test: Vision verdict validation and routing
# ---------------------------------------------------------------------------


def validate_verdict_structure(verdict: VisionVerdict) -> tuple[bool, list[str]]:
    """Validate that a vision verdict has the required structure.

    Checks:
    - `pass` is a boolean
    - `failed_checks` is a list of strings
    - `confidence` is a float in [0.0, 1.0]

    Returns (valid, list_of_violations).
    """
    violations: list[str] = []

    if not isinstance(verdict.pass_, bool):
        violations.append(
            f"'pass' must be boolean, got {type(verdict.pass_).__name__}"
        )

    if not isinstance(verdict.failed_checks, list):
        violations.append(
            f"'failed_checks' must be a list, got {type(verdict.failed_checks).__name__}"
        )
    else:
        for i, check in enumerate(verdict.failed_checks):
            if not isinstance(check, str):
                violations.append(
                    f"'failed_checks[{i}]' must be a string, got {type(check).__name__}"
                )

    if not isinstance(verdict.confidence, (int, float)):
        violations.append(
            f"'confidence' must be a float, got {type(verdict.confidence).__name__}"
        )
    else:
        if verdict.confidence < 0.0 or verdict.confidence > 1.0:
            violations.append(
                f"'confidence' must be in [0.0, 1.0], got {verdict.confidence}"
            )

    return (len(violations) == 0, violations)


def should_auto_accept(verdict: VisionVerdict) -> bool:
    """Determine if a vision verdict qualifies for auto-acceptance.

    Requirements 20.3: Auto-accept ONLY when pass == true AND confidence >= 0.8.
    All other cases require manual review or are logged as advisory warnings.
    """
    return verdict.pass_ is True and verdict.confidence >= AUTO_ACCEPT_CONFIDENCE_THRESHOLD


def route_verdict(verdict: VisionVerdict) -> str:
    """Route a vision verdict to the appropriate action.

    Returns one of:
    - "auto_accept" — pass=True AND confidence >= 0.8
    - "advisory_warning" — pass=False OR confidence < 0.8 (log, don't fail)

    Requirements 20.3: auto-accept when pass=true AND confidence >= 0.8
    Requirements 20.4: log failed checks as warnings (advisory gate, not blocking)
    """
    if should_auto_accept(verdict):
        return "auto_accept"
    return "advisory_warning"


def parse_verdict_json(data: dict) -> tuple[Optional[VisionVerdict], list[str]]:
    """Parse a raw JSON dict into a VisionVerdict.

    Returns (verdict_or_none, parse_errors).
    Validates the required fields exist and have correct types.
    """
    errors: list[str] = []

    # Check required fields exist
    if "pass" not in data:
        errors.append("Missing required field 'pass'")
    if "failed_checks" not in data:
        errors.append("Missing required field 'failed_checks'")
    if "confidence" not in data:
        errors.append("Missing required field 'confidence'")

    if errors:
        return None, errors

    # Validate types
    pass_val = data["pass"]
    failed_checks_val = data["failed_checks"]
    confidence_val = data["confidence"]

    if not isinstance(pass_val, bool):
        errors.append(f"'pass' must be boolean, got {type(pass_val).__name__}")
    if not isinstance(failed_checks_val, list):
        errors.append(f"'failed_checks' must be a list, got {type(failed_checks_val).__name__}")
    elif not all(isinstance(c, str) for c in failed_checks_val):
        errors.append("'failed_checks' must contain only strings")
    if not isinstance(confidence_val, (int, float)):
        errors.append(f"'confidence' must be a number, got {type(confidence_val).__name__}")
    elif confidence_val < 0.0 or confidence_val > 1.0:
        errors.append(f"'confidence' must be in [0.0, 1.0], got {confidence_val}")

    if errors:
        return None, errors

    verdict = VisionVerdict(
        pass_=pass_val,
        failed_checks=failed_checks_val,
        confidence=float(confidence_val),
    )
    return verdict, []


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Confidence values: floats in [0.0, 1.0]
_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# High confidence (auto-accept eligible)
_high_confidence_st = st.floats(
    min_value=0.8, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Low confidence (never auto-accept)
_low_confidence_st = st.floats(
    min_value=0.0, max_value=0.7999999, allow_nan=False, allow_infinity=False
)

# Failed check names (subset of seven categories or arbitrary strings)
_check_name_st = st.one_of(
    st.sampled_from(SEVEN_CATEGORY_CHECKS),
    st.text(min_size=1, max_size=50, alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        whitelist_characters="_- ",
    )),
)

# List of failed checks (can be empty or contain any check names)
_failed_checks_st = st.lists(_check_name_st, min_size=0, max_size=7)

# Valid vision verdicts
_verdict_st = st.builds(
    VisionVerdict,
    pass_=st.booleans(),
    failed_checks=_failed_checks_st,
    confidence=_confidence_st,
)

# Verdict that auto-accepts: pass=True AND confidence >= 0.8
_auto_accept_verdict_st = st.builds(
    VisionVerdict,
    pass_=st.just(True),
    failed_checks=st.just([]),  # No failed checks when pass=True
    confidence=_high_confidence_st,
)

# Verdict that does NOT auto-accept: pass=False OR confidence < 0.8
_non_auto_accept_verdict_st = st.one_of(
    # Case 1: pass=False (any confidence)
    st.builds(
        VisionVerdict,
        pass_=st.just(False),
        failed_checks=st.lists(_check_name_st, min_size=1, max_size=7),
        confidence=_confidence_st,
    ),
    # Case 2: pass=True but confidence < 0.8
    st.builds(
        VisionVerdict,
        pass_=st.just(True),
        failed_checks=st.just([]),
        confidence=_low_confidence_st,
    ),
)

# Invalid confidence values (outside [0.0, 1.0])
_invalid_confidence_st = st.one_of(
    st.floats(min_value=-100.0, max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, max_value=100.0, allow_nan=False, allow_infinity=False),
)


# ---------------------------------------------------------------------------
# Property 17: Vision Verdict Structure
# ---------------------------------------------------------------------------


class TestProperty17VisionVerdictStructure:
    """**Validates: Requirements 20.2, 20.3**

    For any response from the qwen2.5vl:7b vision model, the structured output
    SHALL contain `pass` (boolean), `failed_checks` (list of strings), and
    `confidence` (float 0.0-1.0). Auto-acceptance SHALL occur only when
    `pass == true` AND `confidence >= 0.8`.
    """

    # -------------------------------------------------------------------
    # Structure validation tests
    # -------------------------------------------------------------------

    @given(verdict=_verdict_st)
    @_SETTINGS
    def test_valid_verdict_passes_structure_check(
        self, verdict: VisionVerdict
    ) -> None:
        """Any verdict with bool pass, list[str] failed_checks, float confidence
        in [0.0, 1.0] passes structure validation.

        **Validates: Requirements 20.2**
        """
        valid, violations = validate_verdict_structure(verdict)
        assert valid is True, (
            f"Valid verdict should pass structure check. "
            f"Violations: {violations}. Verdict: {verdict}"
        )
        assert violations == []

    @given(confidence=_invalid_confidence_st)
    @_SETTINGS
    def test_confidence_outside_range_fails_validation(
        self, confidence: float
    ) -> None:
        """Confidence values outside [0.0, 1.0] fail structure validation.

        **Validates: Requirements 20.2**
        """
        verdict = VisionVerdict(pass_=True, failed_checks=[], confidence=confidence)
        valid, violations = validate_verdict_structure(verdict)
        assert valid is False, (
            f"Confidence {confidence} outside [0.0, 1.0] should fail"
        )
        assert any("confidence" in v.lower() for v in violations)

    @given(
        pass_val=st.booleans(),
        failed_checks=_failed_checks_st,
        confidence=_confidence_st,
    )
    @_SETTINGS
    def test_verdict_always_has_three_required_fields(
        self, pass_val: bool, failed_checks: list[str], confidence: float
    ) -> None:
        """Every well-formed verdict contains exactly the three required fields.

        **Validates: Requirements 20.2**
        """
        verdict = VisionVerdict(
            pass_=pass_val,
            failed_checks=failed_checks,
            confidence=confidence,
        )
        # Verify all fields are accessible and correctly typed
        assert isinstance(verdict.pass_, bool)
        assert isinstance(verdict.failed_checks, list)
        assert all(isinstance(c, str) for c in verdict.failed_checks)
        assert isinstance(verdict.confidence, float)
        assert 0.0 <= verdict.confidence <= 1.0

    # -------------------------------------------------------------------
    # Auto-acceptance logic tests
    # -------------------------------------------------------------------

    @given(verdict=_auto_accept_verdict_st)
    @_SETTINGS
    def test_auto_accept_when_pass_true_and_high_confidence(
        self, verdict: VisionVerdict
    ) -> None:
        """Auto-acceptance fires when pass=True AND confidence >= 0.8.

        **Validates: Requirements 20.3**
        """
        assert verdict.pass_ is True
        assert verdict.confidence >= 0.8
        assert should_auto_accept(verdict) is True
        assert route_verdict(verdict) == "auto_accept"

    @given(verdict=_non_auto_accept_verdict_st)
    @_SETTINGS
    def test_no_auto_accept_when_conditions_not_met(
        self, verdict: VisionVerdict
    ) -> None:
        """Auto-acceptance does NOT fire when pass=False OR confidence < 0.8.

        **Validates: Requirements 20.3**
        """
        assert should_auto_accept(verdict) is False
        assert route_verdict(verdict) == "advisory_warning"

    @given(confidence=_confidence_st)
    @_SETTINGS
    def test_pass_false_never_auto_accepts(
        self, confidence: float
    ) -> None:
        """When pass=False, auto-accept never fires regardless of confidence.

        **Validates: Requirements 20.3**
        """
        verdict = VisionVerdict(
            pass_=False,
            failed_checks=["geometry"],
            confidence=confidence,
        )
        assert should_auto_accept(verdict) is False
        assert route_verdict(verdict) == "advisory_warning"

    @given(confidence=_low_confidence_st)
    @_SETTINGS
    def test_low_confidence_never_auto_accepts(
        self, confidence: float
    ) -> None:
        """When confidence < 0.8, auto-accept never fires even if pass=True.

        **Validates: Requirements 20.3**
        """
        verdict = VisionVerdict(
            pass_=True,
            failed_checks=[],
            confidence=confidence,
        )
        assert should_auto_accept(verdict) is False
        assert route_verdict(verdict) == "advisory_warning"

    @given(
        confidence=st.just(0.8),
    )
    @_SETTINGS
    def test_boundary_confidence_0_8_auto_accepts(
        self, confidence: float
    ) -> None:
        """Exactly 0.8 confidence with pass=True qualifies for auto-acceptance.

        **Validates: Requirements 20.3**
        """
        verdict = VisionVerdict(pass_=True, failed_checks=[], confidence=confidence)
        assert should_auto_accept(verdict) is True

    @given(
        confidence=st.floats(
            min_value=0.7999, max_value=0.79999999,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @_SETTINGS
    def test_just_below_threshold_does_not_auto_accept(
        self, confidence: float
    ) -> None:
        """Confidence just below 0.8 does not auto-accept.

        **Validates: Requirements 20.3**
        """
        assume(confidence < 0.8)
        verdict = VisionVerdict(pass_=True, failed_checks=[], confidence=confidence)
        assert should_auto_accept(verdict) is False

    # -------------------------------------------------------------------
    # Both conditions must be met simultaneously
    # -------------------------------------------------------------------

    @given(verdict=_verdict_st)
    @_SETTINGS
    def test_auto_accept_requires_both_conditions(
        self, verdict: VisionVerdict
    ) -> None:
        """Auto-accept is True if and only if BOTH pass=True AND confidence >= 0.8.

        This is the core invariant: the conjunction of both conditions.

        **Validates: Requirements 20.3**
        """
        expected = (verdict.pass_ is True) and (verdict.confidence >= AUTO_ACCEPT_CONFIDENCE_THRESHOLD)
        actual = should_auto_accept(verdict)
        assert actual == expected, (
            f"should_auto_accept({verdict}) = {actual}, "
            f"expected {expected} (pass={verdict.pass_}, "
            f"confidence={verdict.confidence})"
        )

    # -------------------------------------------------------------------
    # JSON parsing validation
    # -------------------------------------------------------------------

    @given(
        pass_val=st.booleans(),
        failed_checks=_failed_checks_st,
        confidence=_confidence_st,
    )
    @_SETTINGS
    def test_valid_json_parses_correctly(
        self, pass_val: bool, failed_checks: list[str], confidence: float
    ) -> None:
        """Valid JSON dict with all required fields parses to a VisionVerdict.

        **Validates: Requirements 20.2**
        """
        data = {
            "pass": pass_val,
            "failed_checks": failed_checks,
            "confidence": confidence,
        }
        verdict, errors = parse_verdict_json(data)
        assert verdict is not None, f"Valid data should parse: errors={errors}"
        assert errors == []
        assert verdict.pass_ == pass_val
        assert verdict.failed_checks == failed_checks
        assert verdict.confidence == confidence

    @given(
        missing_field=st.sampled_from(["pass", "failed_checks", "confidence"]),
    )
    @_SETTINGS
    def test_missing_required_field_fails_parse(
        self, missing_field: str
    ) -> None:
        """JSON missing any required field fails to parse.

        **Validates: Requirements 20.2**
        """
        data = {
            "pass": True,
            "failed_checks": [],
            "confidence": 0.9,
        }
        del data[missing_field]
        verdict, errors = parse_verdict_json(data)
        assert verdict is None
        assert len(errors) > 0
        assert any(missing_field in e for e in errors)

    @given(confidence=_invalid_confidence_st)
    @_SETTINGS
    def test_invalid_confidence_in_json_fails_parse(
        self, confidence: float
    ) -> None:
        """JSON with confidence outside [0.0, 1.0] fails to parse.

        **Validates: Requirements 20.2**
        """
        data = {
            "pass": True,
            "failed_checks": [],
            "confidence": confidence,
        }
        verdict, errors = parse_verdict_json(data)
        assert verdict is None
        assert len(errors) > 0
        assert any("confidence" in e.lower() for e in errors)
