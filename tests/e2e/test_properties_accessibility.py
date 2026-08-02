"""Property-based tests for accessibility assertion logic.

Tests four correctness properties specified in the design document:

Property 10: Accessibility Violation Severity Routing
    For ANY axe-core violation:
    - "critical" or "serious" impact → causes test failure
    - "moderate" or "minor" impact → logged as warning without failure
    The routing logic in _parse_violations correctly categorizes all
    violations by impact severity.

Property 11: Contrast Ratio Enforcement
    For ANY foreground/background color pair:
    - If contrast ratio >= 4.5 → passes WCAG AA check
    - If contrast ratio < 4.5 → fails with element, foreground, background,
      ratio reported
    The compute_contrast_ratio function is mathematically correct and
    the threshold gate routes pass/fail correctly.

Property 12: Stage Transition Announcement
    For ANY valid stage name announcement:
    - Human-readable names (with spaces/capitalization) pass
    - Machine identifiers (underscored, all lowercase) fail
    The is_human_readable_stage_name function correctly distinguishes
    human-readable announcements from machine identifiers.

Property 13: Arrow Key Movement Equivalence
    For ANY movement sequence:
    - Applying via arrow keys produces same displacement as equivalent WASD
    - Up=W, Down=S, Left=A, Right=D
    The compute_displacement function produces identical results for
    arrow key sequences and their WASD equivalents.

**Validates: Requirements 11.2, 11.3, 13.1, 13.2, 14.1, 14.3, 16.1**

Testing framework: Hypothesis (as specified in design document)
"""
from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from tests.e2e.test_accessibility import (
    _parse_violations,
    compute_contrast_ratio,
    WCAG_AA_CONTRAST_MINIMUM,
    is_human_readable_stage_name,
    compute_key_displacement,
    arrow_sequence_to_wasd,
    ARROW_TO_WASD_MAP,
    DIRECTION_VECTORS,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Impact levels from axe-core (the four possible severity values)
_impact_st = st.sampled_from(["critical", "serious", "moderate", "minor"])

# RGB channel values (0-255)
_rgb_channel_st = st.integers(min_value=0, max_value=255)

# Arrow keys
_arrow_keys_st = st.sampled_from(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"])

# WASD keys
_wasd_keys_st = st.sampled_from(["w", "s", "a", "d"])

# Movement speed (positive, reasonable range)
_speed_st = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Helpers for building test data
# ---------------------------------------------------------------------------


def _make_raw_violation(
    rule_id: str = "test-rule",
    impact: str = "minor",
    description: str = "Test description",
    help_url: str = "https://example.com/help",
    tags: list[str] | None = None,
    selectors: list[str] | None = None,
) -> dict:
    """Build a raw axe-core violation dict for testing _parse_violations."""
    if tags is None:
        tags = ["wcag2a"]
    if selectors is None:
        selectors = [".test-element"]

    nodes = [{"target": [sel]} for sel in selectors]

    return {
        "id": rule_id,
        "impact": impact,
        "description": description,
        "helpUrl": help_url,
        "tags": tags,
        "nodes": nodes,
    }


def _rgb_to_css(r: int, g: int, b: int) -> str:
    """Convert RGB integers to CSS rgb() string."""
    return f"rgb({r}, {g}, {b})"


# ---------------------------------------------------------------------------
# Property 10: Accessibility Violation Severity Routing
# ---------------------------------------------------------------------------


class TestProperty10ViolationSeverityRouting:
    """**Validates: Requirements 11.2, 11.3**

    For ANY axe-core violation with any impact level:
    - "critical" or "serious" → categorized in critical_serious list (causes failure)
    - "moderate" or "minor" → categorized in moderate_minor list (warning only)

    The routing is exhaustive: every violation appears in exactly one category.
    """

    @given(impact=_impact_st)
    @settings(deadline=None)
    def test_single_violation_routes_to_correct_category(self, impact: str) -> None:
        """A single violation with any impact routes to the correct bucket."""
        raw = [_make_raw_violation(impact=impact)]
        result = _parse_violations(raw)

        # Violation should appear in the full list
        assert len(result.violations) == 1
        assert result.violations[0].impact == impact

        if impact in ("critical", "serious"):
            # Should cause test failure (in critical_serious)
            assert len(result.critical_serious) == 1
            assert len(result.moderate_minor) == 0
            assert result.critical_serious[0].impact == impact
        else:
            # Should only warn (in moderate_minor)
            assert len(result.moderate_minor) == 1
            assert len(result.critical_serious) == 0
            assert result.moderate_minor[0].impact == impact

    @given(
        impacts=st.lists(
            _impact_st, min_size=1, max_size=20
        )
    )
    @settings(deadline=None)
    def test_multiple_violations_all_correctly_routed(
        self, impacts: list[str]
    ) -> None:
        """Multiple violations with varied impacts all route correctly."""
        raw = [_make_raw_violation(impact=imp, rule_id=f"rule-{i}")
               for i, imp in enumerate(impacts)]
        result = _parse_violations(raw)

        # Total violations equals input count
        assert len(result.violations) == len(impacts)

        # Count expected per category
        expected_critical_serious = sum(
            1 for imp in impacts if imp in ("critical", "serious")
        )
        expected_moderate_minor = sum(
            1 for imp in impacts if imp in ("moderate", "minor")
        )

        assert len(result.critical_serious) == expected_critical_serious
        assert len(result.moderate_minor) == expected_moderate_minor

        # Sum of categories equals total
        assert (
            len(result.critical_serious) + len(result.moderate_minor)
            == len(result.violations)
        )

    @given(impact=_impact_st)
    @settings(deadline=None)
    def test_violation_preserves_metadata(self, impact: str) -> None:
        """Parsed violations preserve rule_id, description, selectors."""
        raw = [_make_raw_violation(
            impact=impact,
            rule_id="color-contrast",
            description="Elements must have sufficient color contrast",
            selectors=[".header", "#main-nav"],
        )]
        result = _parse_violations(raw)

        v = result.violations[0]
        assert v.rule_id == "color-contrast"
        assert v.description == "Elements must have sufficient color contrast"
        assert ".header" in v.affected_selectors
        assert "#main-nav" in v.affected_selectors


# ---------------------------------------------------------------------------
# Property 11: Contrast Ratio Enforcement
# ---------------------------------------------------------------------------


class TestProperty11ContrastRatioEnforcement:
    """**Validates: Requirements 13.1, 13.2**

    For ANY foreground/background color pair:
    - If contrast ratio >= 4.5 → passes WCAG AA check
    - If contrast ratio < 4.5 → fails

    The compute_contrast_ratio function correctly implements WCAG 2.1
    relative luminance and contrast ratio formula.
    """

    @given(
        fg_r=_rgb_channel_st, fg_g=_rgb_channel_st, fg_b=_rgb_channel_st,
        bg_r=_rgb_channel_st, bg_g=_rgb_channel_st, bg_b=_rgb_channel_st,
    )
    @settings(deadline=None)
    def test_contrast_ratio_always_at_least_one(
        self,
        fg_r: int, fg_g: int, fg_b: int,
        bg_r: int, bg_g: int, bg_b: int,
    ) -> None:
        """Contrast ratio is always >= 1.0 (by WCAG definition)."""
        fg_css = _rgb_to_css(fg_r, fg_g, fg_b)
        bg_css = _rgb_to_css(bg_r, bg_g, bg_b)

        ratio = compute_contrast_ratio(fg_css, bg_css)
        assert ratio >= 1.0

    @given(
        fg_r=_rgb_channel_st, fg_g=_rgb_channel_st, fg_b=_rgb_channel_st,
        bg_r=_rgb_channel_st, bg_g=_rgb_channel_st, bg_b=_rgb_channel_st,
    )
    @settings(deadline=None)
    def test_contrast_ratio_at_most_21(
        self,
        fg_r: int, fg_g: int, fg_b: int,
        bg_r: int, bg_g: int, bg_b: int,
    ) -> None:
        """Contrast ratio is always <= 21.0 (black vs white maximum)."""
        fg_css = _rgb_to_css(fg_r, fg_g, fg_b)
        bg_css = _rgb_to_css(bg_r, bg_g, bg_b)

        ratio = compute_contrast_ratio(fg_css, bg_css)
        assert ratio <= 21.0 + 0.01  # small epsilon for float precision

    @given(
        fg_r=_rgb_channel_st, fg_g=_rgb_channel_st, fg_b=_rgb_channel_st,
        bg_r=_rgb_channel_st, bg_g=_rgb_channel_st, bg_b=_rgb_channel_st,
    )
    @settings(deadline=None)
    def test_contrast_ratio_symmetric(
        self,
        fg_r: int, fg_g: int, fg_b: int,
        bg_r: int, bg_g: int, bg_b: int,
    ) -> None:
        """Contrast ratio is symmetric: ratio(A, B) == ratio(B, A)."""
        fg_css = _rgb_to_css(fg_r, fg_g, fg_b)
        bg_css = _rgb_to_css(bg_r, bg_g, bg_b)

        ratio_fg_bg = compute_contrast_ratio(fg_css, bg_css)
        ratio_bg_fg = compute_contrast_ratio(bg_css, fg_css)

        assert abs(ratio_fg_bg - ratio_bg_fg) < 1e-10

    @given(
        fg_r=_rgb_channel_st, fg_g=_rgb_channel_st, fg_b=_rgb_channel_st,
        bg_r=_rgb_channel_st, bg_g=_rgb_channel_st, bg_b=_rgb_channel_st,
    )
    @settings(deadline=None)
    def test_threshold_gate_correct(
        self,
        fg_r: int, fg_g: int, fg_b: int,
        bg_r: int, bg_g: int, bg_b: int,
    ) -> None:
        """The 4.5:1 threshold correctly gates pass/fail decisions."""
        fg_css = _rgb_to_css(fg_r, fg_g, fg_b)
        bg_css = _rgb_to_css(bg_r, bg_g, bg_b)

        ratio = compute_contrast_ratio(fg_css, bg_css)
        passes = ratio >= WCAG_AA_CONTRAST_MINIMUM

        if passes:
            assert ratio >= 4.5
        else:
            assert ratio < 4.5

    def test_known_black_on_white_passes(self) -> None:
        """Black text on white background (21:1) passes WCAG AA."""
        ratio = compute_contrast_ratio("rgb(0, 0, 0)", "rgb(255, 255, 255)")
        assert ratio >= WCAG_AA_CONTRAST_MINIMUM
        # Black/white should be approximately 21:1
        assert abs(ratio - 21.0) < 0.1

    def test_known_low_contrast_fails(self) -> None:
        """Light gray on white (below 4.5:1) fails WCAG AA."""
        # Light gray (#AAAAAA = rgb(170, 170, 170)) on white
        ratio = compute_contrast_ratio("rgb(170, 170, 170)", "rgb(255, 255, 255)")
        assert ratio < WCAG_AA_CONTRAST_MINIMUM


# ---------------------------------------------------------------------------
# Property 12: Stage Transition Announcement
# ---------------------------------------------------------------------------


class TestProperty12StageTransitionAnnouncement:
    """**Validates: Requirements 14.1, 14.3**

    For ANY valid stage name announcement:
    - Human-readable names (with spaces/capitalization) pass validation
    - Machine identifiers (underscored, all lowercase) fail validation

    The distinction ensures screen reader users hear proper English names,
    not internal identifiers like "dream_preview" or "world_build".
    """

    @given(
        words=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"),
                min_size=2,
                max_size=10,
            ),
            min_size=1,
            max_size=4,
        )
    )
    @settings(deadline=None)
    def test_title_case_names_pass(self, words: list[str]) -> None:
        """Title-cased multi-word names are human-readable (pass).

        Generated names like "Dream Preview", "World Build", "Canon" pass
        because they have capitalized first letters and use spaces.
        """
        # Build a title-case name from generated words
        title_words = [w.capitalize() for w in words if w.strip()]
        assume(len(title_words) > 0)
        name = " ".join(title_words)
        assume(len(name.strip()) > 0)
        # Ensure first char is actually uppercase ASCII after capitalize()
        assume(name[0].isupper())

        assert is_human_readable_stage_name(name) is True

    @given(
        parts=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("Ll",)),
                min_size=2,
                max_size=10,
            ),
            min_size=2,
            max_size=4,
        )
    )
    @settings(deadline=None)
    def test_underscored_names_fail(self, parts: list[str]) -> None:
        """Underscore-joined lowercase names are machine identifiers (fail).

        Generated names like "dream_preview", "world_build" fail because
        they contain underscores — the hallmark of machine identifiers.
        """
        valid_parts = [p for p in parts if p.strip()]
        assume(len(valid_parts) >= 2)
        name = "_".join(valid_parts)

        assert is_human_readable_stage_name(name) is False

    @given(
        word=st.text(
            alphabet=st.characters(whitelist_categories=("Ll",)),
            min_size=2,
            max_size=15,
        )
    )
    @settings(deadline=None)
    def test_all_lowercase_no_underscore_fails(self, word: str) -> None:
        """All-lowercase single words fail (not title-cased).

        Names like "blockout", "canon" fail because they don't start
        with an uppercase character.
        """
        assume(word.strip() == word and len(word) > 0)
        # Ensure it's purely lowercase
        assume(word == word.lower())

        assert is_human_readable_stage_name(word) is False

    def test_empty_string_fails(self) -> None:
        """Empty strings are not valid stage names."""
        assert is_human_readable_stage_name("") is False
        assert is_human_readable_stage_name("   ") is False

    def test_known_human_readable_names_pass(self) -> None:
        """Known pipeline stage names in human-readable format pass."""
        assert is_human_readable_stage_name("Dream Preview") is True
        assert is_human_readable_stage_name("Blockout") is True
        assert is_human_readable_stage_name("Canon") is True
        assert is_human_readable_stage_name("World") is True
        assert is_human_readable_stage_name("World Build") is True

    def test_known_machine_identifiers_fail(self) -> None:
        """Known machine identifier formats fail validation."""
        assert is_human_readable_stage_name("dream_preview") is False
        assert is_human_readable_stage_name("world_build") is False
        assert is_human_readable_stage_name("canon_stage") is False
        assert is_human_readable_stage_name("blockout") is False


# ---------------------------------------------------------------------------
# Property 13: Arrow Key Movement Equivalence
# ---------------------------------------------------------------------------


class TestProperty13ArrowKeyMovementEquivalence:
    """**Validates: Requirements 16.1**

    For ANY movement sequence:
    - Applying via arrow keys produces same displacement as equivalent WASD
    - Up=W, Down=S, Left=A, Right=D

    The mapping is exact and the displacement computation is deterministic.
    """

    @given(
        arrow_sequence=st.lists(_arrow_keys_st, min_size=1, max_size=50),
        speed=_speed_st,
    )
    @settings(deadline=None)
    def test_arrow_keys_produce_same_displacement_as_wasd(
        self, arrow_sequence: list[str], speed: float
    ) -> None:
        """Any arrow key sequence produces identical displacement to WASD equivalent."""
        # Convert arrows to WASD
        wasd_sequence = arrow_sequence_to_wasd(arrow_sequence)

        # Compute displacement for both
        arrow_displacement = compute_key_displacement(arrow_sequence, speed)
        wasd_displacement = compute_key_displacement(wasd_sequence, speed)

        # They must be exactly equal
        assert abs(arrow_displacement[0] - wasd_displacement[0]) < 1e-10
        assert abs(arrow_displacement[1] - wasd_displacement[1]) < 1e-10
        assert abs(arrow_displacement[2] - wasd_displacement[2]) < 1e-10

    @given(arrow_key=_arrow_keys_st)
    @settings(deadline=None)
    def test_single_arrow_maps_to_correct_wasd(self, arrow_key: str) -> None:
        """Each individual arrow key maps to the correct WASD equivalent."""
        wasd_key = ARROW_TO_WASD_MAP[arrow_key]

        # Their direction vectors must be identical
        arrow_vec = DIRECTION_VECTORS[arrow_key]
        wasd_vec = DIRECTION_VECTORS[wasd_key]

        assert arrow_vec == wasd_vec

    @given(
        arrow_sequence=st.lists(_arrow_keys_st, min_size=0, max_size=30),
    )
    @settings(deadline=None)
    def test_displacement_is_additive(self, arrow_sequence: list[str]) -> None:
        """Displacement of combined sequence equals sum of individual displacements."""
        if not arrow_sequence:
            # Empty sequence → zero displacement
            dx, dy, dz = compute_key_displacement(arrow_sequence)
            assert dx == 0.0 and dy == 0.0 and dz == 0.0
            return

        # Compute full sequence displacement
        full_dx, full_dy, full_dz = compute_key_displacement(arrow_sequence)

        # Compute sum of individual key displacements
        sum_dx, sum_dy, sum_dz = 0.0, 0.0, 0.0
        for key in arrow_sequence:
            kdx, kdy, kdz = compute_key_displacement([key])
            sum_dx += kdx
            sum_dy += kdy
            sum_dz += kdz

        assert abs(full_dx - sum_dx) < 1e-10
        assert abs(full_dy - sum_dy) < 1e-10
        assert abs(full_dz - sum_dz) < 1e-10

    @given(
        arrow_sequence=st.lists(_arrow_keys_st, min_size=1, max_size=20),
    )
    @settings(deadline=None)
    def test_y_component_always_zero(self, arrow_sequence: list[str]) -> None:
        """Arrow keys only affect X/Z (horizontal plane); Y is always 0."""
        dx, dy, dz = compute_key_displacement(arrow_sequence)
        assert dy == 0.0

    def test_known_mapping_up_is_w(self) -> None:
        """ArrowUp maps to W (forward)."""
        assert ARROW_TO_WASD_MAP["ArrowUp"] == "w"
        assert DIRECTION_VECTORS["ArrowUp"] == DIRECTION_VECTORS["w"]

    def test_known_mapping_down_is_s(self) -> None:
        """ArrowDown maps to S (backward)."""
        assert ARROW_TO_WASD_MAP["ArrowDown"] == "s"
        assert DIRECTION_VECTORS["ArrowDown"] == DIRECTION_VECTORS["s"]

    def test_known_mapping_left_is_a(self) -> None:
        """ArrowLeft maps to A (strafe left)."""
        assert ARROW_TO_WASD_MAP["ArrowLeft"] == "a"
        assert DIRECTION_VECTORS["ArrowLeft"] == DIRECTION_VECTORS["a"]

    def test_known_mapping_right_is_d(self) -> None:
        """ArrowRight maps to D (strafe right)."""
        assert ARROW_TO_WASD_MAP["ArrowRight"] == "d"
        assert DIRECTION_VECTORS["ArrowRight"] == DIRECTION_VECTORS["d"]
