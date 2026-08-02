"""Unit tests for accessibility assertion logic — focus trap validation.

Tests the helper functions and assertion logic for focus trap validation
in approval dialogs (check_focus_within_dialog, format_violation, etc.)
without requiring a live browser or Playwright.

Also validates the axe-core violation severity routing logic
(_parse_violations) which routes critical/serious to failure and
moderate/minor to warnings.

Requirements: 11.1–11.3, 12.1–12.3
"""
from __future__ import annotations

import pytest

from tests.e2e.test_accessibility import (
    AxeScanResult,
    AxeViolation,
    _parse_violations,
    check_focus_within_dialog,
    format_violation,
    format_violations_report,
    is_human_readable_stage_name,
)


# ---------------------------------------------------------------------------
# check_focus_within_dialog unit tests (Req 12.1, 12.3)
# ---------------------------------------------------------------------------


class TestCheckFocusWithinDialog:
    """Test focus trap assertion logic — check_focus_within_dialog().

    This function returns None when focus is inside the dialog, or a
    descriptive failure message when focus has escaped, including
    the element that received unexpected focus (Req 12.3).

    Requirements: 12.1, 12.3
    """

    def test_focus_inside_dialog_returns_none(self):
        """When focus is inside the dialog, no failure message is generated."""
        element_info = {
            "tag": "button",
            "id": "approve-btn",
            "className": "btn primary",
            "selector": "button#approve-btn.btn.primary",
        }
        result = check_focus_within_dialog(element_info, is_inside=True, tab_number=1)
        assert result is None

    def test_focus_escaped_dialog_returns_failure_message(self):
        """When focus escapes, returns message identifying the offending element."""
        element_info = {
            "tag": "input",
            "id": "background-search",
            "className": "search-field",
            "selector": "input#background-search.search-field",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=5)
        assert result is not None
        # Must identify the element that received unexpected focus (Req 12.3)
        assert "input#background-search.search-field" in result
        assert "background-search" in result
        assert "search-field" in result
        assert "Tab press #5" in result

    def test_focus_escaped_on_first_tab(self):
        """Focus escaping on the very first Tab is reported with tab_number=1."""
        element_info = {
            "tag": "a",
            "id": "",
            "className": "nav-link",
            "selector": "a.nav-link",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=1)
        assert result is not None
        assert "Tab press #1" in result
        assert "a.nav-link" in result

    def test_focus_escaped_reports_tag(self):
        """Failure message includes the tag name of the focused element."""
        element_info = {
            "tag": "div",
            "id": "main-content",
            "className": "",
            "selector": "div#main-content",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=3)
        assert "tag=div" in result

    def test_focus_escaped_reports_id(self):
        """Failure message includes the id of the focused element."""
        element_info = {
            "tag": "button",
            "id": "outside-button",
            "className": "btn",
            "selector": "button#outside-button.btn",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=2)
        assert "id='outside-button'" in result

    def test_focus_escaped_reports_class(self):
        """Failure message includes the className of the focused element."""
        element_info = {
            "tag": "span",
            "id": "",
            "className": "toolbar-item active",
            "selector": "span.toolbar-item.active",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=4)
        assert "class='toolbar-item active'" in result

    def test_focus_inside_on_various_tab_numbers(self):
        """Focus remaining inside returns None regardless of tab number."""
        element_info = {
            "tag": "button",
            "id": "reject-btn",
            "className": "",
            "selector": "button#reject-btn",
        }
        for tab_num in [1, 5, 10, 20, 100]:
            result = check_focus_within_dialog(element_info, is_inside=True, tab_number=tab_num)
            assert result is None

    def test_empty_element_info_still_reports(self):
        """Even with minimal element info, failure is reported clearly."""
        element_info = {
            "tag": "body",
            "id": "",
            "className": "",
            "selector": "body",
        }
        result = check_focus_within_dialog(element_info, is_inside=False, tab_number=7)
        assert result is not None
        assert "body" in result
        assert "Tab press #7" in result


# ---------------------------------------------------------------------------
# Axe violation severity routing unit tests (Req 11.2, 11.3)
# ---------------------------------------------------------------------------


class TestParseViolations:
    """Test _parse_violations severity routing logic.

    - "critical" / "serious" impact → critical_serious list (causes test failure)
    - "moderate" / "minor" impact → moderate_minor list (warnings only)

    Requirements: 11.2, 11.3
    """

    def test_critical_violation_routes_to_critical_serious(self):
        """Critical violations go into the critical_serious category."""
        raw = [{
            "id": "image-alt",
            "impact": "critical",
            "description": "Images must have alternate text",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.9/image-alt",
            "tags": ["wcag2a", "wcag111"],
            "nodes": [{"target": ["img.hero-image"]}],
        }]
        result = _parse_violations(raw)
        assert len(result.critical_serious) == 1
        assert len(result.moderate_minor) == 0
        assert result.critical_serious[0].impact == "critical"

    def test_serious_violation_routes_to_critical_serious(self):
        """Serious violations go into the critical_serious category."""
        raw = [{
            "id": "color-contrast",
            "impact": "serious",
            "description": "Elements must have sufficient color contrast",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.9/color-contrast",
            "tags": ["wcag2aa", "wcag143"],
            "nodes": [{"target": [".status-text"]}],
        }]
        result = _parse_violations(raw)
        assert len(result.critical_serious) == 1
        assert len(result.moderate_minor) == 0
        assert result.critical_serious[0].impact == "serious"

    def test_moderate_violation_routes_to_moderate_minor(self):
        """Moderate violations go into the moderate_minor category (warning)."""
        raw = [{
            "id": "heading-order",
            "impact": "moderate",
            "description": "Heading levels should only increase by one",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.9/heading-order",
            "tags": ["wcag2a", "wcag131"],
            "nodes": [{"target": ["h4.subtitle"]}],
        }]
        result = _parse_violations(raw)
        assert len(result.critical_serious) == 0
        assert len(result.moderate_minor) == 1
        assert result.moderate_minor[0].impact == "moderate"

    def test_minor_violation_routes_to_moderate_minor(self):
        """Minor violations go into the moderate_minor category (warning)."""
        raw = [{
            "id": "region",
            "impact": "minor",
            "description": "All page content should be contained by landmarks",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.9/region",
            "tags": ["wcag2a"],
            "nodes": [{"target": ["div.orphan-content"]}],
        }]
        result = _parse_violations(raw)
        assert len(result.critical_serious) == 0
        assert len(result.moderate_minor) == 1
        assert result.moderate_minor[0].impact == "minor"

    def test_mixed_severities_route_correctly(self):
        """Mix of severities routes each to the correct list."""
        raw = [
            {"id": "rule-a", "impact": "critical", "description": "A", "helpUrl": "", "tags": [], "nodes": []},
            {"id": "rule-b", "impact": "minor", "description": "B", "helpUrl": "", "tags": [], "nodes": []},
            {"id": "rule-c", "impact": "serious", "description": "C", "helpUrl": "", "tags": [], "nodes": []},
            {"id": "rule-d", "impact": "moderate", "description": "D", "helpUrl": "", "tags": [], "nodes": []},
        ]
        result = _parse_violations(raw)
        assert len(result.violations) == 4
        assert len(result.critical_serious) == 2
        assert len(result.moderate_minor) == 2
        critical_ids = {v.rule_id for v in result.critical_serious}
        assert critical_ids == {"rule-a", "rule-c"}

    def test_empty_violations_list(self):
        """Empty violations list produces empty result."""
        result = _parse_violations([])
        assert result.violations == []
        assert result.critical_serious == []
        assert result.moderate_minor == []

    def test_wcag_criteria_extracted_from_tags(self):
        """WCAG criteria are correctly extracted from axe-core tags."""
        raw = [{
            "id": "color-contrast",
            "impact": "serious",
            "description": "Contrast",
            "helpUrl": "",
            "tags": ["wcag2aa", "wcag143", "cat.color"],
            "nodes": [],
        }]
        result = _parse_violations(raw)
        assert "wcag2aa" in result.critical_serious[0].wcag_criteria
        assert "wcag143" in result.critical_serious[0].wcag_criteria
        # Non-wcag tags are excluded
        assert "cat.color" not in result.critical_serious[0].wcag_criteria

    def test_affected_selectors_extracted_from_nodes(self):
        """Element selectors are extracted from violation nodes."""
        raw = [{
            "id": "image-alt",
            "impact": "critical",
            "description": "Images alt",
            "helpUrl": "",
            "tags": [],
            "nodes": [
                {"target": ["img.hero"]},
                {"target": ["img.logo"]},
            ],
        }]
        result = _parse_violations(raw)
        selectors = result.critical_serious[0].affected_selectors
        assert "img.hero" in selectors
        assert "img.logo" in selectors

    def test_unknown_impact_defaults_to_moderate_minor(self):
        """Unknown or missing impact defaults to moderate_minor (not failure)."""
        raw = [{
            "id": "unknown-rule",
            "impact": None,  # Missing impact
            "description": "Unknown",
            "helpUrl": "",
            "tags": [],
            "nodes": [],
        }]
        result = _parse_violations(raw)
        # Impact defaults to "minor" in the parser, which routes to moderate_minor
        assert len(result.moderate_minor) == 1
        assert len(result.critical_serious) == 0


# ---------------------------------------------------------------------------
# format_violation tests
# ---------------------------------------------------------------------------


class TestFormatViolation:
    """Test violation formatting produces the required report fields.

    Reports must include impact level, WCAG criterion, and affected
    element selectors (Req 11.1).
    """

    def test_includes_impact_level(self):
        """Report includes the impact level in uppercase."""
        violation = AxeViolation(
            rule_id="color-contrast",
            impact="serious",
            description="Contrast issue",
            help_url="https://example.com",
            wcag_criteria=["wcag2aa"],
            affected_selectors=[".text-element"],
        )
        report = format_violation(violation)
        assert "[SERIOUS]" in report

    def test_includes_wcag_criterion(self):
        """Report includes the WCAG criterion."""
        violation = AxeViolation(
            rule_id="image-alt",
            impact="critical",
            description="Images need alt",
            help_url="",
            wcag_criteria=["wcag2a", "wcag111"],
            affected_selectors=["img"],
        )
        report = format_violation(violation)
        assert "wcag2a" in report
        assert "wcag111" in report

    def test_includes_affected_selectors(self):
        """Report includes the CSS selectors of affected elements."""
        violation = AxeViolation(
            rule_id="button-name",
            impact="critical",
            description="Buttons must have names",
            help_url="",
            wcag_criteria=[],
            affected_selectors=["button.icon-btn", "#submit-form button:nth-child(2)"],
        )
        report = format_violation(violation)
        assert "button.icon-btn" in report
        assert "#submit-form button:nth-child(2)" in report

    def test_missing_wcag_shows_na(self):
        """When no WCAG criteria, shows N/A."""
        violation = AxeViolation(
            rule_id="custom-rule",
            impact="minor",
            description="Custom",
            help_url="",
            wcag_criteria=[],
            affected_selectors=[],
        )
        report = format_violation(violation)
        assert "N/A" in report


# ---------------------------------------------------------------------------
# format_violations_report tests
# ---------------------------------------------------------------------------


class TestFormatViolationsReport:
    """Test multi-violation report formatting."""

    def test_includes_header(self):
        """Report starts with the provided header."""
        violations = [
            AxeViolation("r1", "critical", "desc", "", [], []),
        ]
        report = format_violations_report(violations, header="Test Header:")
        assert report.startswith("Test Header:")

    def test_multiple_violations_all_included(self):
        """All violations appear in the report."""
        violations = [
            AxeViolation("rule-1", "critical", "First issue", "", ["wcag2a"], [".el1"]),
            AxeViolation("rule-2", "serious", "Second issue", "", ["wcag2aa"], [".el2"]),
        ]
        report = format_violations_report(violations, header="2 violations:")
        assert "rule-1" in report
        assert "rule-2" in report
        assert "First issue" in report
        assert "Second issue" in report


# ---------------------------------------------------------------------------
# is_human_readable_stage_name unit tests (Req 14.3)
# ---------------------------------------------------------------------------


class TestIsHumanReadableStageName:
    """Test the helper that validates stage announcements are human-readable.

    Human-readable names have spaces and/or capitalization.
    Machine identifiers use underscores and all-lowercase (e.g., "dream_preview").

    Requirements: 14.3
    """

    # --- Valid human-readable names ---

    def test_spaced_capitalized_name(self):
        """'Dream Preview' is human-readable (has space + capital)."""
        assert is_human_readable_stage_name("Dream Preview") is True

    def test_single_word_capitalized(self):
        """'Canon' is human-readable (has capital letter)."""
        assert is_human_readable_stage_name("Canon") is True

    def test_multi_word_title_case(self):
        """'World Render' is human-readable."""
        assert is_human_readable_stage_name("World Render") is True

    def test_sentence_case(self):
        """'Dream preview' is human-readable (has capital D)."""
        assert is_human_readable_stage_name("Dream preview") is True

    def test_all_caps(self):
        """'BLOCKOUT' is human-readable (has uppercase)."""
        assert is_human_readable_stage_name("BLOCKOUT") is True

    def test_mixed_with_numbers(self):
        """'Stage 3 Preview' is human-readable."""
        assert is_human_readable_stage_name("Stage 3 Preview") is True

    def test_with_leading_trailing_spaces(self):
        """Leading/trailing whitespace is stripped before validation."""
        assert is_human_readable_stage_name("  Dream Preview  ") is True

    def test_spaced_all_lower(self):
        """'dream preview' is human-readable (has space)."""
        assert is_human_readable_stage_name("dream preview") is True

    # --- Invalid machine identifiers ---

    def test_underscore_separated_lowercase(self):
        """'dream_preview' is a machine identifier (underscore-separated lowercase)."""
        assert is_human_readable_stage_name("dream_preview") is False

    def test_underscore_separated_multi_segment(self):
        """'world_render_final' is a machine identifier."""
        assert is_human_readable_stage_name("world_render_final") is False

    def test_blockout_render_machine_id(self):
        """'blockout_render' is a machine identifier."""
        assert is_human_readable_stage_name("blockout_render") is False

    def test_canon_compare_machine_id(self):
        """'canon_compare' is a machine identifier."""
        assert is_human_readable_stage_name("canon_compare") is False

    def test_empty_string(self):
        """Empty string is not a valid stage name."""
        assert is_human_readable_stage_name("") is False

    def test_whitespace_only(self):
        """Whitespace-only string is not a valid stage name."""
        assert is_human_readable_stage_name("   ") is False

    # --- Edge cases ---

    def test_single_lowercase_word(self):
        """A single lowercase word like 'canon' is not human-readable (no space/capital)."""
        assert is_human_readable_stage_name("canon") is False

    def test_single_word_with_number(self):
        """'stage3' without space or capital is not human-readable."""
        assert is_human_readable_stage_name("stage3") is False

    def test_underscore_with_uppercase(self):
        """'Dream_Preview' has uppercase so it passes (mixed convention)."""
        # This has uppercase letters, so it's considered human-readable
        # even though it uses underscores
        assert is_human_readable_stage_name("Dream_Preview") is True

    def test_hyphenated_with_capital(self):
        """'Dream-Preview' has capital and no underscores — human-readable."""
        assert is_human_readable_stage_name("Dream-Preview") is True
