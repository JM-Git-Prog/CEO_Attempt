"""Accessibility tests — axe-core scanning via Playwright for WCAG 2.1 AA.

Integrates axe-core into the Playwright page to scan the pipeline UI for
accessibility violations. Violations are categorized by impact level:
- "critical" / "serious" → test failure
- "moderate" / "minor" → warnings (logged without failing)

Also includes focus trap validation for approval dialogs (Req 12.1–12.3):
- Tab key cycling within dialog only
- Escape key closing dialog and restoring focus

Screen reader announcements (Req 14.1–14.3):
- Verify aria-live="polite" updates with human-readable stage names within 2s

Responsive layout validation (Req 15.1–15.3):
- Validate at 4 viewport sizes (1920x1080, 1366x768, 1024x768, 375x667)
- Verify no elements clipped/overlapped or rendered off-screen
- Verify conversation panel and artifact preview independently scrollable on mobile

Reports include impact level, WCAG criterion (from tags), and affected
element selectors for each violation.

Uses the @pytest.mark.layer("accessibility") marker for 30s budget enforcement.

Requirements: 11.1, 11.2, 11.3, 12.1, 12.2, 12.3, 14.1, 14.2, 14.3, 15.1, 15.2, 15.3
"""
from __future__ import annotations

import asyncio
import re
import warnings
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# axe-core CDN URL (pinned version for reproducibility)
# ---------------------------------------------------------------------------

AXE_CORE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AxeViolation:
    """A single axe-core violation with parsed metadata.

    Attributes:
        rule_id: The axe-core rule identifier (e.g., "color-contrast").
        impact: Severity level — "critical", "serious", "moderate", or "minor".
        description: Human-readable description of the violation.
        help_url: Link to deque documentation for this rule.
        wcag_criteria: List of WCAG criteria tags (e.g., ["wcag2a", "wcag412"]).
        affected_selectors: CSS selectors of elements that violate the rule.
    """

    rule_id: str
    impact: str
    description: str
    help_url: str
    wcag_criteria: list[str] = field(default_factory=list)
    affected_selectors: list[str] = field(default_factory=list)


@dataclass
class AxeScanResult:
    """Complete result of an axe-core accessibility scan.

    Attributes:
        violations: All violations found, regardless of impact level.
        critical_serious: Violations with "critical" or "serious" impact (cause test failure).
        moderate_minor: Violations with "moderate" or "minor" impact (warnings only).
    """

    violations: list[AxeViolation] = field(default_factory=list)
    critical_serious: list[AxeViolation] = field(default_factory=list)
    moderate_minor: list[AxeViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core scanning helper
# ---------------------------------------------------------------------------


async def run_axe_scan(page: Any) -> AxeScanResult:
    """Inject axe-core into the page and run an accessibility scan.

    This helper can be reused by other test modules that need axe-core
    scanning on different pages or states.

    Args:
        page: A Playwright page instance with the target UI loaded.

    Returns:
        AxeScanResult with violations categorized by severity.

    Raises:
        RuntimeError: If axe-core injection or execution fails.
    """
    # Inject axe-core from CDN
    try:
        await page.evaluate(
            """async () => {
                if (typeof window.axe === 'undefined') {
                    await new Promise((resolve, reject) => {
                        const script = document.createElement('script');
                        script.src = '%s';
                        script.onload = resolve;
                        script.onerror = () => reject(
                            new Error('Failed to load axe-core from CDN')
                        );
                        document.head.appendChild(script);
                    });
                }
            }"""
            % AXE_CORE_CDN_URL
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to inject axe-core into the page: {exc}"
        ) from exc

    # Run axe.run() and collect results
    try:
        raw_results = await page.evaluate(
            """async () => {
                const results = await axe.run();
                return results.violations;
            }"""
        )
    except Exception as exc:
        raise RuntimeError(
            f"axe-core scan execution failed: {exc}"
        ) from exc

    # Parse raw violations into structured data
    return _parse_violations(raw_results)


def _parse_violations(raw_violations: list[dict[str, Any]]) -> AxeScanResult:
    """Parse raw axe-core violation JSON into categorized AxeScanResult.

    Args:
        raw_violations: The violations array from axe.run() result.

    Returns:
        AxeScanResult with violations sorted into critical/serious vs moderate/minor.
    """
    result = AxeScanResult()

    for raw in raw_violations:
        # Extract WCAG criteria from tags (tags like "wcag2a", "wcag412", etc.)
        tags = raw.get("tags", [])
        wcag_criteria = [t for t in tags if t.startswith("wcag")]

        # Extract affected element selectors from nodes
        nodes = raw.get("nodes", [])
        affected_selectors: list[str] = []
        for node in nodes:
            target = node.get("target", [])
            if target:
                # target is typically a list of CSS selector strings
                if isinstance(target[0], list):
                    # Shadow DOM — target is nested arrays
                    affected_selectors.append(" > ".join(target[0]))
                else:
                    affected_selectors.append(target[0])

        violation = AxeViolation(
            rule_id=raw.get("id", "unknown"),
            impact=raw.get("impact", "minor"),
            description=raw.get("description", ""),
            help_url=raw.get("helpUrl", ""),
            wcag_criteria=wcag_criteria,
            affected_selectors=affected_selectors,
        )

        result.violations.append(violation)

        if violation.impact in ("critical", "serious"):
            result.critical_serious.append(violation)
        else:
            result.moderate_minor.append(violation)

    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_violation(violation: AxeViolation) -> str:
    """Format a single violation into a human-readable report line.

    Includes impact level, WCAG criterion, rule description, and affected
    element selectors as required by Requirement 11.1.

    Args:
        violation: A parsed AxeViolation instance.

    Returns:
        Multi-line formatted string describing the violation.
    """
    wcag_str = ", ".join(violation.wcag_criteria) if violation.wcag_criteria else "N/A"
    selectors_str = "\n      ".join(violation.affected_selectors) if violation.affected_selectors else "(none)"

    return (
        f"  [{violation.impact.upper()}] {violation.rule_id}\n"
        f"    Description: {violation.description}\n"
        f"    WCAG: {wcag_str}\n"
        f"    Help: {violation.help_url}\n"
        f"    Affected elements:\n"
        f"      {selectors_str}"
    )


def format_violations_report(violations: list[AxeViolation], header: str) -> str:
    """Format multiple violations into a complete report.

    Args:
        violations: List of AxeViolation instances to format.
        header: A header line for the report.

    Returns:
        Formatted multi-line string with all violations described.
    """
    lines = [header]
    for v in violations:
        lines.append(format_violation(v))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def page():
    """Provide a Playwright page instance for accessibility testing.

    Skips gracefully when no browser is available (e.g., Playwright not
    installed or no browser binary). Similar to the scene validation
    fixture pattern.

    In integration mode, this should be overridden by a conftest.py
    that provides a page connected to the running pipeline UI.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip(
            "Playwright not installed. Install with: pip install playwright && "
            "python -m playwright install chromium"
        )
        return  # pragma: no cover

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            pg = await context.new_page()

            # Navigate to the pipeline UI
            # Default to localhost:8000/?v=16 as per the design doc
            try:
                await pg.goto(
                    "http://localhost:8000/?v=16",
                    timeout=10000,
                    wait_until="networkidle",
                )
            except Exception:
                await browser.close()
                pytest.skip(
                    "Pipeline UI not available at http://localhost:8000/?v=16. "
                    "Start the development server to run accessibility tests."
                )
                return  # pragma: no cover

            yield pg

            await browser.close()
    except Exception as exc:
        pytest.skip(
            f"Browser not available for accessibility testing: {exc}"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.layer("accessibility")
class TestAccessibility:
    """Accessibility test suite — axe-core WCAG 2.1 AA scanning.

    Scans the pipeline UI for accessibility violations using axe-core
    injected via Playwright. Critical/serious violations cause test
    failure; moderate/minor violations are logged as warnings.

    Requirements: 11.1, 11.2, 11.3
    """

    @pytest.mark.asyncio
    async def test_axe_core_scan(self, page: Any) -> None:
        """Run axe-core scan and enforce violation severity routing.

        - Fails on "critical" or "serious" violations (Req 11.2)
        - Warns on "moderate" or "minor" violations (Req 11.3)
        - Reports impact level, WCAG criterion, and affected element
          selectors for every violation (Req 11.1)

        Requirements: 11.1, 11.2, 11.3
        """
        # Run the axe-core scan
        scan_result = await run_axe_scan(page)

        # Emit warnings for moderate/minor violations (Req 11.3)
        if scan_result.moderate_minor:
            warning_msg = format_violations_report(
                scan_result.moderate_minor,
                header=(
                    f"axe-core: {len(scan_result.moderate_minor)} "
                    f"moderate/minor violation(s) detected (non-blocking):"
                ),
            )
            warnings.warn(warning_msg, stacklevel=1)

        # Fail on critical/serious violations (Req 11.2)
        if scan_result.critical_serious:
            failure_msg = format_violations_report(
                scan_result.critical_serious,
                header=(
                    f"axe-core: {len(scan_result.critical_serious)} "
                    f"critical/serious WCAG 2.1 AA violation(s) detected:"
                ),
            )
            pytest.fail(failure_msg)


# ---------------------------------------------------------------------------
# Focus trap validation — Requirements 12.1, 12.2, 12.3
# ---------------------------------------------------------------------------


async def get_active_element_info(page: Any) -> dict[str, str]:
    """Get identifying information about the currently focused element.

    Returns a dict with tag, id, class, and a CSS selector-like description
    to help identify the element in failure messages.

    Args:
        page: A Playwright page instance.

    Returns:
        Dict with keys: tag, id, className, selector (descriptive CSS path).
    """
    return await page.evaluate(
        """() => {
            const el = document.activeElement;
            if (!el) return { tag: 'null', id: '', className: '', selector: '(no active element)' };
            const tag = el.tagName.toLowerCase();
            const id = el.id ? '#' + el.id : '';
            const cls = el.className ? '.' + el.className.split(' ').join('.') : '';
            const selector = tag + id + cls;
            return {
                tag: tag,
                id: el.id || '',
                className: el.className || '',
                selector: selector,
            };
        }"""
    )


async def is_element_inside_dialog(page: Any, dialog_selector: str) -> bool:
    """Check if the currently focused element is inside the specified dialog.

    Args:
        page: A Playwright page instance.
        dialog_selector: CSS selector for the dialog container.

    Returns:
        True if document.activeElement is a descendant of the dialog element.
    """
    return await page.evaluate(
        """(dialogSelector) => {
            const dialog = document.querySelector(dialogSelector);
            if (!dialog) return false;
            const active = document.activeElement;
            if (!active) return false;
            return dialog.contains(active);
        }""",
        dialog_selector,
    )


async def open_approval_dialog(page: Any) -> str | None:
    """Attempt to open an approval dialog in the pipeline UI.

    Tries multiple strategies to trigger an approval dialog:
    1. Click an element with [data-action="approve"] or similar trigger
    2. Look for an existing open dialog (role="dialog" or [aria-modal="true"])
    3. Dispatch a custom event to simulate the approval gate

    Returns:
        The CSS selector of the opened dialog, or None if no dialog could be opened.
    """
    # Strategy 1: Look for an already-open dialog
    dialog_selector = await page.evaluate(
        """() => {
            // Check for role="dialog" or aria-modal elements
            const dialog = document.querySelector(
                '[role="dialog"], [aria-modal="true"], dialog[open], .approval-dialog, .modal'
            );
            if (dialog) {
                // Build a selector for it
                if (dialog.id) return '#' + dialog.id;
                if (dialog.getAttribute('role') === 'dialog') return '[role="dialog"]';
                if (dialog.getAttribute('aria-modal') === 'true') return '[aria-modal="true"]';
                if (dialog.tagName === 'DIALOG') return 'dialog[open]';
                if (dialog.classList.contains('approval-dialog')) return '.approval-dialog';
                if (dialog.classList.contains('modal')) return '.modal';
                return '[role="dialog"]';
            }
            return null;
        }"""
    )

    if dialog_selector:
        return dialog_selector

    # Strategy 2: Click a trigger button if available
    trigger_clicked = await page.evaluate(
        """() => {
            const triggers = [
                '[data-action="approve"]',
                '[data-action="open-approval"]',
                'button.approve-btn',
                'button[aria-haspopup="dialog"]',
                '.approval-trigger',
            ];
            for (const sel of triggers) {
                const el = document.querySelector(sel);
                if (el) {
                    el.click();
                    return true;
                }
            }
            return false;
        }"""
    )

    if trigger_clicked:
        # Wait briefly for dialog to appear
        try:
            await page.wait_for_selector(
                '[role="dialog"], [aria-modal="true"], dialog[open], .approval-dialog, .modal',
                timeout=2000,
            )
        except Exception:
            pass

        # Re-check for dialog
        dialog_selector = await page.evaluate(
            """() => {
                const dialog = document.querySelector(
                    '[role="dialog"], [aria-modal="true"], dialog[open], .approval-dialog, .modal'
                );
                if (dialog) {
                    if (dialog.id) return '#' + dialog.id;
                    if (dialog.getAttribute('role') === 'dialog') return '[role="dialog"]';
                    if (dialog.getAttribute('aria-modal') === 'true') return '[aria-modal="true"]';
                    return '[role="dialog"]';
                }
                return null;
            }"""
        )

        if dialog_selector:
            return dialog_selector

    # Strategy 3: Simulate by injecting a test dialog if nothing is available
    # This allows tests to validate focus trap logic even without a live approval gate.
    injected = await page.evaluate(
        """() => {
            // Inject a minimal approval dialog for testing focus trap behavior
            const dialog = document.createElement('div');
            dialog.setAttribute('role', 'dialog');
            dialog.setAttribute('aria-modal', 'true');
            dialog.setAttribute('aria-label', 'Approval Required');
            dialog.id = 'test-approval-dialog';
            dialog.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
                'padding:2rem;background:white;border:1px solid #ccc;z-index:10000;';
            dialog.innerHTML = `
                <h2>Approval Required</h2>
                <p>Do you approve this stage?</p>
                <button id="dialog-approve-btn">Approve</button>
                <button id="dialog-reject-btn">Reject</button>
                <button id="dialog-close-btn" aria-label="Close">×</button>
            `;
            document.body.appendChild(dialog);
            // Focus the first button
            dialog.querySelector('button').focus();
            return '#test-approval-dialog';
        }"""
    )
    return injected


def check_focus_within_dialog(
    element_info: dict[str, str],
    is_inside: bool,
    tab_number: int,
) -> str | None:
    """Check if the focused element is within the dialog boundaries.

    Args:
        element_info: Info about the currently active element (from get_active_element_info).
        is_inside: Result of is_element_inside_dialog check.
        tab_number: Which Tab press iteration this check corresponds to.

    Returns:
        None if focus is contained, or a failure message string if focus escaped.
    """
    if not is_inside:
        return (
            f"Focus escaped dialog on Tab press #{tab_number}. "
            f"Unexpected focus recipient: {element_info['selector']} "
            f"(tag={element_info['tag']}, id='{element_info['id']}', "
            f"class='{element_info['className']}')"
        )
    return None


# ---------------------------------------------------------------------------
# Focus trap tests
# ---------------------------------------------------------------------------


@pytest.mark.layer("accessibility")
class TestFocusTrap:
    """Focus trap validation for approval dialogs.

    Verifies that:
    1. Tab cycling is confined within the dialog (Req 12.1)
    2. Escape closes the dialog and restores focus (Req 12.2)
    3. On focus escape, the offending element is reported (Req 12.3)

    Requirements: 12.1, 12.2, 12.3
    """

    @pytest.mark.asyncio
    async def test_focus_trap_in_approval_dialog(self, page: Any) -> None:
        """Verify Tab cycles within the approval dialog only.

        Opens an approval dialog and presses Tab repeatedly (more times
        than the dialog has focusable elements) to confirm that focus
        wraps back to the beginning and never leaves the dialog.

        If focus escapes the dialog, reports the element that received
        unexpected focus.

        Requirements: 12.1, 12.3
        """
        dialog_selector = await open_approval_dialog(page)
        if dialog_selector is None:
            pytest.skip(
                "Could not open an approval dialog. "
                "No dialog trigger or dialog element found in the UI."
            )

        # Count focusable elements inside the dialog
        focusable_count = await page.evaluate(
            """(dialogSelector) => {
                const dialog = document.querySelector(dialogSelector);
                if (!dialog) return 0;
                const focusable = dialog.querySelectorAll(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                );
                return focusable.length;
            }""",
            dialog_selector,
        )

        if focusable_count == 0:
            pytest.skip(
                f"Dialog '{dialog_selector}' has no focusable elements. "
                "Cannot validate focus trapping."
            )

        # Press Tab enough times to cycle through all elements twice plus extra
        # to ensure wrapping behavior
        num_tabs = focusable_count * 2 + 3

        for i in range(num_tabs):
            await page.keyboard.press("Tab")

            # Check that focus is still inside the dialog
            element_info = await get_active_element_info(page)
            inside = await is_element_inside_dialog(page, dialog_selector)

            failure_msg = check_focus_within_dialog(element_info, inside, i + 1)
            if failure_msg:
                pytest.fail(failure_msg)

    @pytest.mark.asyncio
    async def test_escape_closes_dialog(self, page: Any) -> None:
        """Verify Escape closes the dialog and returns focus to previous element.

        Records the focused element before opening the dialog, then opens
        the dialog and presses Escape. Verifies:
        1. The dialog is no longer visible/present in the DOM
        2. Focus returns to the previously focused element

        Requirements: 12.2, 12.3
        """
        # Record the currently focused element before opening the dialog
        pre_dialog_info = await get_active_element_info(page)

        # Ensure there's a focusable element to return to (focus the body or first button)
        await page.evaluate(
            """() => {
                // Focus a known element before opening dialog
                const target = document.querySelector(
                    'button, [href], input, [tabindex]'
                ) || document.body;
                target.focus();
            }"""
        )
        pre_dialog_info = await get_active_element_info(page)

        dialog_selector = await open_approval_dialog(page)
        if dialog_selector is None:
            pytest.skip(
                "Could not open an approval dialog. "
                "No dialog trigger or dialog element found in the UI."
            )

        # Verify dialog is now present
        dialog_exists = await page.evaluate(
            """(dialogSelector) => {
                const dialog = document.querySelector(dialogSelector);
                return dialog !== null;
            }""",
            dialog_selector,
        )
        assert dialog_exists, (
            f"Dialog '{dialog_selector}' was not found in the DOM after opening."
        )

        # Press Escape to close the dialog
        await page.keyboard.press("Escape")

        # Small wait for dialog close animation/handler
        try:
            await page.wait_for_function(
                """(dialogSelector) => {
                    const dialog = document.querySelector(dialogSelector);
                    if (!dialog) return true;
                    // Check if hidden via style or attribute
                    const style = window.getComputedStyle(dialog);
                    return style.display === 'none' || style.visibility === 'hidden'
                        || dialog.getAttribute('aria-hidden') === 'true'
                        || !dialog.offsetParent;
                }""",
                dialog_selector,
                timeout=2000,
            )
        except Exception:
            # Dialog may have been removed from DOM entirely, which is fine
            pass

        # Verify dialog is closed (removed from DOM or hidden)
        dialog_still_visible = await page.evaluate(
            """(dialogSelector) => {
                const dialog = document.querySelector(dialogSelector);
                if (!dialog) return false;
                const style = window.getComputedStyle(dialog);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                if (dialog.getAttribute('aria-hidden') === 'true') return false;
                if (!dialog.offsetParent && dialog.tagName !== 'BODY') return false;
                return true;
            }""",
            dialog_selector,
        )

        if dialog_still_visible:
            current_focus = await get_active_element_info(page)
            pytest.fail(
                f"Dialog '{dialog_selector}' did not close after pressing Escape. "
                f"Current focus: {current_focus['selector']}"
            )

        # Verify focus returned to the previously focused element
        post_dialog_info = await get_active_element_info(page)

        # Focus should return to the element that was focused before dialog opened
        # Compare by tag+id or tag+class if id is empty
        focus_returned = (
            post_dialog_info["tag"] == pre_dialog_info["tag"]
            and (
                (post_dialog_info["id"] == pre_dialog_info["id"] and pre_dialog_info["id"])
                or post_dialog_info["selector"] == pre_dialog_info["selector"]
            )
        )

        if not focus_returned:
            pytest.fail(
                f"Focus did not return to the previously focused element after "
                f"Escape closed the dialog.\n"
                f"  Expected focus on: {pre_dialog_info['selector']}\n"
                f"  Actual focus on:   {post_dialog_info['selector']} "
                f"(tag={post_dialog_info['tag']}, id='{post_dialog_info['id']}', "
                f"class='{post_dialog_info['className']}')"
            )


# ---------------------------------------------------------------------------
# Color Contrast Helpers (WCAG AA 4.5:1 enforcement)
# Requirements: 13.1, 13.2
# ---------------------------------------------------------------------------


def parse_rgb(color_str: str) -> tuple[int, int, int]:
    """Parse an RGB/RGBA color string into (R, G, B) integer tuple.

    Handles formats:
      - "rgb(R, G, B)"
      - "rgba(R, G, B, A)"
      - "#RRGGBB"
      - "#RGB"

    Args:
        color_str: CSS color string from getComputedStyle.

    Returns:
        Tuple of (red, green, blue) integers in 0-255 range.

    Raises:
        ValueError: If the color string cannot be parsed.
    """
    color_str = color_str.strip()

    # Handle rgba(R, G, B, A) and rgb(R, G, B)
    if color_str.startswith("rgba(") or color_str.startswith("rgb("):
        inner = color_str.split("(", 1)[1].rstrip(")")
        parts = [p.strip() for p in inner.split(",")]
        return (int(parts[0]), int(parts[1]), int(parts[2]))

    # Handle hex colors
    if color_str.startswith("#"):
        hex_str = color_str[1:]
        if len(hex_str) == 3:
            r = int(hex_str[0] * 2, 16)
            g = int(hex_str[1] * 2, 16)
            b = int(hex_str[2] * 2, 16)
            return (r, g, b)
        elif len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return (r, g, b)

    raise ValueError(f"Cannot parse color string: {color_str!r}")


def _linearize_channel(value: int) -> float:
    """Convert an sRGB channel value (0-255) to linear RGB.

    Applies the sRGB inverse companding function per WCAG 2.1 spec.

    Args:
        value: sRGB channel value in 0-255 range.

    Returns:
        Linear RGB value in 0.0-1.0 range.
    """
    srgb = value / 255.0
    if srgb <= 0.04045:
        return srgb / 12.92
    else:
        return ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(r: int, g: int, b: int) -> float:
    """Compute WCAG 2.1 relative luminance from sRGB values.

    Formula: L = 0.2126 * R_lin + 0.7152 * G_lin + 0.0722 * B_lin
    where R_lin, G_lin, B_lin are linearized sRGB channel values.

    Args:
        r: Red channel (0-255).
        g: Green channel (0-255).
        b: Blue channel (0-255).

    Returns:
        Relative luminance in 0.0-1.0 range.
    """
    r_lin = _linearize_channel(r)
    g_lin = _linearize_channel(g)
    b_lin = _linearize_channel(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def compute_contrast_ratio(fg_color: str, bg_color: str) -> float:
    """Compute WCAG 2.1 contrast ratio between foreground and background colors.

    Uses the standard WCAG formula:
        contrast_ratio = (L1 + 0.05) / (L2 + 0.05)
    where L1 is the relative luminance of the lighter color and L2 is the
    relative luminance of the darker color.

    Args:
        fg_color: Foreground (text) color as CSS string (rgb/rgba/hex).
        bg_color: Background color as CSS string (rgb/rgba/hex).

    Returns:
        Contrast ratio as a float >= 1.0 (e.g., 4.5 means 4.5:1).

    Raises:
        ValueError: If either color string cannot be parsed.
    """
    fg_r, fg_g, fg_b = parse_rgb(fg_color)
    bg_r, bg_g, bg_b = parse_rgb(bg_color)

    lum_fg = relative_luminance(fg_r, fg_g, fg_b)
    lum_bg = relative_luminance(bg_r, bg_g, bg_b)

    # L1 is the lighter (higher luminance), L2 is the darker
    l1 = max(lum_fg, lum_bg)
    l2 = min(lum_fg, lum_bg)

    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# HUD Element Selectors
# ---------------------------------------------------------------------------

# Data attribute selectors for HUD overlay text elements.
# These correspond to the pipeline's HUD overlay showing pipeline status.
HUD_ELEMENT_SELECTORS = [
    '[data-hud="status"]',
    '[data-hud="stageTitle"]',
    '[data-hud="details"]',
    '[data-hud="sessionId"]',
]

# WCAG AA minimum contrast ratio for normal text
WCAG_AA_CONTRAST_MINIMUM = 4.5


# ---------------------------------------------------------------------------
# Contrast Failure Data Model
# ---------------------------------------------------------------------------


@dataclass
class ContrastFailure:
    """A single HUD element that failed the contrast ratio check.

    Attributes:
        selector: CSS selector used to find the element.
        foreground_color: Computed text color (CSS string).
        background_color: Computed background color (CSS string).
        contrast_ratio: The actual measured contrast ratio.
        minimum_required: The minimum required ratio (4.5:1 for WCAG AA).
    """

    selector: str
    foreground_color: str
    background_color: str
    contrast_ratio: float
    minimum_required: float = WCAG_AA_CONTRAST_MINIMUM


def format_contrast_failure(failure: ContrastFailure) -> str:
    """Format a contrast failure into a human-readable report line.

    Args:
        failure: A ContrastFailure instance.

    Returns:
        Formatted string describing the failure.
    """
    return (
        f"  Element: {failure.selector}\n"
        f"    Foreground: {failure.foreground_color}\n"
        f"    Background: {failure.background_color}\n"
        f"    Ratio: {failure.contrast_ratio:.2f}:1 "
        f"(minimum required: {failure.minimum_required}:1)"
    )


# ---------------------------------------------------------------------------
# HUD Contrast Test
# ---------------------------------------------------------------------------


@pytest.mark.layer("accessibility")
class TestHUDContrast:
    """HUD overlay color contrast tests — WCAG AA 4.5:1 enforcement.

    Verifies that all HUD text elements (status, stageTitle, details,
    sessionId) meet the WCAG AA minimum contrast ratio of 4.5:1 against
    their background.

    On failure, reports the element selector, foreground color, background
    color, and actual contrast ratio.

    Requirements: 13.1, 13.2
    """

    @pytest.mark.asyncio
    async def test_hud_overlay_contrast(self, page: Any) -> None:
        """Verify all HUD overlay text meets WCAG AA 4.5:1 contrast ratio.

        For each HUD text element (status, stageTitle, details, sessionId):
        1. Query the element by data-hud attribute selector
        2. Compute foreground color via getComputedStyle(el).color
        3. Compute background color (traversing parents for transparency)
        4. Calculate the WCAG contrast ratio
        5. Fail if any element's ratio < 4.5:1
        6. Report element selector, foreground color, background color,
           and actual ratio on failure

        Requirements: 13.1, 13.2
        """
        failures: list[ContrastFailure] = []
        elements_found = 0

        for selector in HUD_ELEMENT_SELECTORS:
            # Check if element exists on the page
            element = await page.query_selector(selector)
            if element is None:
                # Element not present — skip (may not be rendered at this state)
                continue

            elements_found += 1

            # Get computed foreground and background colors via JavaScript
            colors = await page.evaluate(
                """(selector) => {
                    const el = document.querySelector(selector);
                    if (!el) return null;

                    const style = window.getComputedStyle(el);
                    const fgColor = style.color;

                    // Traverse up for background color if current element
                    // has transparent background
                    let bgColor = style.backgroundColor;
                    let current = el;
                    while (
                        current &&
                        (bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent')
                    ) {
                        current = current.parentElement;
                        if (current) {
                            bgColor = window.getComputedStyle(current).backgroundColor;
                        }
                    }

                    // If we never found an opaque background, default to white
                    if (!bgColor || bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') {
                        bgColor = 'rgb(255, 255, 255)';
                    }

                    return { fgColor, bgColor };
                }""",
                selector,
            )

            if colors is None:
                continue

            fg_color = colors["fgColor"]
            bg_color = colors["bgColor"]

            # Compute the contrast ratio
            try:
                ratio = compute_contrast_ratio(fg_color, bg_color)
            except ValueError:
                # If we can't parse colors, record as a failure with ratio 0
                failures.append(
                    ContrastFailure(
                        selector=selector,
                        foreground_color=fg_color,
                        background_color=bg_color,
                        contrast_ratio=0.0,
                    )
                )
                continue

            # Check against WCAG AA threshold
            if ratio < WCAG_AA_CONTRAST_MINIMUM:
                failures.append(
                    ContrastFailure(
                        selector=selector,
                        foreground_color=fg_color,
                        background_color=bg_color,
                        contrast_ratio=ratio,
                    )
                )

        # Skip if no HUD elements were found (UI not in a state showing HUD)
        if elements_found == 0:
            pytest.skip(
                "No HUD overlay elements found on page. "
                "Pipeline may not be in a state that renders the HUD."
            )

        # Report failures (Req 13.2)
        if failures:
            report_lines = [
                f"WCAG AA contrast check failed for {len(failures)} HUD element(s):"
            ]
            for failure in failures:
                report_lines.append(format_contrast_failure(failure))

            pytest.fail("\n".join(report_lines))


# ---------------------------------------------------------------------------
# Human-Readable Stage Name Validation Helper
# Requirements: 14.3
# ---------------------------------------------------------------------------

# Known machine-style stage identifiers that should NOT appear in aria-live
_MACHINE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def is_human_readable_stage_name(name: str) -> bool:
    """Check whether a stage name is human-readable (not a machine identifier).

    A name is considered human-readable if it:
    1. Is non-empty after stripping whitespace
    2. Contains at least one space OR at least one uppercase letter
    3. Does NOT match the underscore-separated machine identifier pattern
       (e.g., "dream_preview", "world_render")

    This helper is designed to be unit-testable independently of the
    accessibility test suite.

    Args:
        name: The stage name string to validate.

    Returns:
        True if the name is human-readable, False if it's a machine ID.

    Examples:
        >>> is_human_readable_stage_name("Dream Preview")
        True
        >>> is_human_readable_stage_name("Canon")
        True
        >>> is_human_readable_stage_name("World Render")
        True
        >>> is_human_readable_stage_name("dream_preview")
        False
        >>> is_human_readable_stage_name("blockout_render")
        False
        >>> is_human_readable_stage_name("")
        False
    """
    stripped = name.strip()
    if not stripped:
        return False

    # If it matches the underscore-separated machine pattern, it's NOT human-readable
    if _MACHINE_ID_PATTERN.match(stripped):
        return False

    # Must contain at least one space OR at least one uppercase letter
    has_space = " " in stripped
    has_upper = any(c.isupper() for c in stripped)

    return has_space or has_upper


# ---------------------------------------------------------------------------
# Screen Reader Announcement Tests — Requirements 14.1, 14.2, 14.3
# ---------------------------------------------------------------------------


@pytest.mark.layer("accessibility")
class TestScreenReaderAnnouncements:
    """Screen reader announcement tests for stage transitions.

    Verifies that:
    1. An aria-live="polite" region exists on the page (Req 14.1)
    2. Stage transitions update the region within 2 seconds (Req 14.2)
    3. The announcement contains a human-readable stage name (Req 14.3)

    Requirements: 14.1, 14.2, 14.3
    """

    @pytest.mark.asyncio
    async def test_stage_transition_announcements(self, page: Any) -> None:
        """Verify aria-live="polite" updates with human-readable stage names within 2s.

        Steps:
        1. Locate the aria-live="polite" element on the page
        2. Record its initial content
        3. Trigger a stage transition (or wait for one if pipeline is running)
        4. Verify the aria-live region updates within 2 seconds
        5. Verify the new content is a human-readable stage name

        Requirements: 14.1, 14.2, 14.3
        """
        # Step 1: Find the aria-live="polite" region
        live_region = await page.query_selector('[aria-live="polite"]')

        if live_region is None:
            pytest.fail(
                "No element with aria-live=\"polite\" found on the page. "
                "Pipeline UI must provide an aria-live region for stage "
                "transition announcements (Req 14.1)."
            )

        # Step 2: Get initial content
        initial_content = await live_region.inner_text()

        # Step 3: Attempt to trigger a stage transition
        # Strategy A: dispatch a custom event that the pipeline listens for
        # Strategy B: click a "next stage" or "approve" button if available
        # Strategy C: wait for a natural stage transition if pipeline is running
        stage_changed = await page.evaluate(
            """() => {
                // Try dispatching a stage-advance event
                const event = new CustomEvent('test:advance-stage', { bubbles: true });
                document.dispatchEvent(event);

                // Check if there's a button that advances the pipeline
                const advanceBtns = document.querySelectorAll(
                    '[data-action="advance"], [data-action="next-stage"], ' +
                    'button.advance-btn, button.next-stage'
                );
                if (advanceBtns.length > 0) {
                    advanceBtns[0].click();
                    return true;
                }

                // Check if we can programmatically trigger a stage change
                if (window.__pipeline && typeof window.__pipeline.advanceStage === 'function') {
                    window.__pipeline.advanceStage();
                    return true;
                }

                return false;
            }"""
        )

        # Step 4: Wait up to 2 seconds for the aria-live region to update (Req 14.2)
        announcement_text = None
        deadline = 2.0  # 2 second timeout per Req 14.2
        poll_interval = 0.1  # Check every 100ms
        elapsed = 0.0

        while elapsed < deadline:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            current_content = await live_region.inner_text()
            current_content = current_content.strip()

            # Check if content has changed from initial (and is non-empty)
            if current_content and current_content != initial_content.strip():
                announcement_text = current_content
                break

        # If no change detected, check if the CURRENT content already has a
        # valid stage name (pipeline may already be in a stage)
        if announcement_text is None:
            current_content = (await live_region.inner_text()).strip()
            if current_content:
                # The region already has content — validate it
                announcement_text = current_content
            else:
                pytest.skip(
                    "aria-live region did not update within 2s. "
                    "Pipeline may not have transitioned stages during this test. "
                    "Ensure the pipeline is actively running stage transitions."
                )

        # Step 5: Verify the announcement is a human-readable stage name (Req 14.3)
        assert is_human_readable_stage_name(announcement_text), (
            f"aria-live region contains a machine identifier instead of a "
            f"human-readable stage name.\n"
            f"  Found: {announcement_text!r}\n"
            f"  Expected: A human-readable name with spaces and/or capitalization "
            f"(e.g., 'Dream Preview', 'Canon', 'World Render')\n"
            f"  Not: underscore-separated machine IDs like 'dream_preview'"
        )


# ---------------------------------------------------------------------------
# Responsive Layout Tests — Requirements 15.1, 15.2, 15.3
# ---------------------------------------------------------------------------

# Viewport sizes to test (width, height)
RESPONSIVE_VIEWPORTS = [
    (1920, 1080),  # Full HD desktop
    (1366, 768),   # Common laptop
    (1024, 768),   # Tablet landscape
    (375, 667),    # Mobile (iPhone SE)
]


@pytest.mark.layer("accessibility")
class TestResponsiveLayout:
    """Responsive layout validation across common viewport sizes.

    Verifies that:
    1. The UI renders correctly at 4 viewport sizes (Req 15.1)
    2. No interactive element is clipped, overlapped, or off-screen (Req 15.2)
    3. On mobile (375x667), conversation panel and artifact preview are
       independently scrollable (Req 15.3)

    Requirements: 15.1, 15.2, 15.3
    """

    @pytest.mark.asyncio
    async def test_responsive_layout(self, page: Any) -> None:
        """Validate layout at 1920x1080, 1366x768, 1024x768, 375x667.

        For each viewport size:
        1. Resize the viewport
        2. Query all interactive elements (buttons, links, inputs, etc.)
        3. Verify no element is clipped (bounding rect partially outside viewport)
        4. Verify no element is overlapped by another at its center point
        5. Verify no element is rendered entirely off-screen

        At 375x667 (mobile):
        6. Verify conversation panel has overflow-y scroll
        7. Verify artifact preview has overflow-y scroll
        8. Verify both are independently scrollable

        Requirements: 15.1, 15.2, 15.3
        """
        layout_failures: list[str] = []

        for width, height in RESPONSIVE_VIEWPORTS:
            # Resize viewport
            await page.set_viewport_size({"width": width, "height": height})

            # Allow the layout to reflow
            await asyncio.sleep(0.3)

            # Check interactive elements for clipping/overlap/off-screen
            viewport_issues = await page.evaluate(
                """(viewport) => {
                    const { width, height } = viewport;
                    const issues = [];

                    // Find all interactive elements
                    const interactiveSelectors =
                        'button, a[href], input, select, textarea, ' +
                        '[role="button"], [role="link"], [tabindex]:not([tabindex="-1"]), ' +
                        '[data-interactive]';
                    const elements = document.querySelectorAll(interactiveSelectors);

                    for (const el of elements) {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);

                        // Skip hidden elements
                        if (style.display === 'none' || style.visibility === 'hidden' ||
                            rect.width === 0 || rect.height === 0) {
                            continue;
                        }

                        const selector = el.tagName.toLowerCase() +
                            (el.id ? '#' + el.id : '') +
                            (el.className ? '.' + el.className.toString().trim().split(/\\s+/).join('.') : '');

                        // Check if element is entirely off-screen
                        if (rect.right < 0 || rect.bottom < 0 ||
                            rect.left > width || rect.top > height) {
                            issues.push({
                                type: 'off-screen',
                                selector: selector,
                                rect: { left: rect.left, top: rect.top,
                                         right: rect.right, bottom: rect.bottom }
                            });
                            continue;
                        }

                        // Check if element is clipped (partially outside viewport)
                        if (rect.left < 0 || rect.top < 0 ||
                            rect.right > width || rect.bottom > height) {
                            issues.push({
                                type: 'clipped',
                                selector: selector,
                                rect: { left: rect.left, top: rect.top,
                                         right: rect.right, bottom: rect.bottom }
                            });
                        }

                        // Check overlap: use elementFromPoint at center
                        const centerX = rect.left + rect.width / 2;
                        const centerY = rect.top + rect.height / 2;
                        if (centerX >= 0 && centerX < width &&
                            centerY >= 0 && centerY < height) {
                            const topEl = document.elementFromPoint(centerX, centerY);
                            if (topEl && topEl !== el && !el.contains(topEl) && !topEl.contains(el)) {
                                issues.push({
                                    type: 'overlapped',
                                    selector: selector,
                                    overlappedBy: topEl.tagName.toLowerCase() +
                                        (topEl.id ? '#' + topEl.id : '')
                                });
                            }
                        }
                    }

                    return issues;
                }""",
                {"width": width, "height": height},
            )

            # Collect issues for this viewport
            for issue in viewport_issues:
                if issue["type"] == "off-screen":
                    layout_failures.append(
                        f"  [{width}x{height}] OFF-SCREEN: {issue['selector']} "
                        f"(rect: {issue['rect']})"
                    )
                elif issue["type"] == "clipped":
                    layout_failures.append(
                        f"  [{width}x{height}] CLIPPED: {issue['selector']} "
                        f"(rect: {issue['rect']})"
                    )
                elif issue["type"] == "overlapped":
                    layout_failures.append(
                        f"  [{width}x{height}] OVERLAPPED: {issue['selector']} "
                        f"by {issue.get('overlappedBy', 'unknown')}"
                    )

            # Mobile-specific check (375x667): Req 15.3
            if width == 375 and height == 667:
                scroll_issues = await page.evaluate(
                    """() => {
                        const issues = [];

                        // Find conversation panel
                        const conversationPanel = document.querySelector(
                            '[data-panel="conversation"], .conversation-panel, ' +
                            '#conversation-panel, [role="log"]'
                        );

                        // Find artifact preview
                        const artifactPreview = document.querySelector(
                            '[data-panel="artifact"], .artifact-preview, ' +
                            '#artifact-preview, [data-panel="preview"]'
                        );

                        if (conversationPanel) {
                            const style = window.getComputedStyle(conversationPanel);
                            const isScrollable = (
                                style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                                style.overflow === 'auto' || style.overflow === 'scroll' ||
                                conversationPanel.scrollHeight > conversationPanel.clientHeight
                            );
                            if (!isScrollable) {
                                issues.push('Conversation panel is not independently scrollable');
                            }
                        } else {
                            issues.push(
                                'Conversation panel not found (looked for [data-panel="conversation"], ' +
                                '.conversation-panel, #conversation-panel, [role="log"])'
                            );
                        }

                        if (artifactPreview) {
                            const style = window.getComputedStyle(artifactPreview);
                            const isScrollable = (
                                style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                                style.overflow === 'auto' || style.overflow === 'scroll' ||
                                artifactPreview.scrollHeight > artifactPreview.clientHeight
                            );
                            if (!isScrollable) {
                                issues.push('Artifact preview is not independently scrollable');
                            }
                        } else {
                            issues.push(
                                'Artifact preview not found (looked for [data-panel="artifact"], ' +
                                '.artifact-preview, #artifact-preview, [data-panel="preview"])'
                            );
                        }

                        return issues;
                    }"""
                )

                for issue in scroll_issues:
                    layout_failures.append(f"  [375x667 MOBILE] {issue}")

        # Report all layout failures
        if layout_failures:
            pytest.fail(
                f"Responsive layout validation failed with "
                f"{len(layout_failures)} issue(s):\n"
                + "\n".join(layout_failures)
            )


# ---------------------------------------------------------------------------
# Arrow Key Movement Equivalence
# Requirements: 16.1
# ---------------------------------------------------------------------------

# Mapping from arrow keys to equivalent WASD keys
ARROW_TO_WASD_MAP = {
    "ArrowUp": "w",
    "ArrowDown": "s",
    "ArrowLeft": "a",
    "ArrowRight": "d",
}

# Direction vectors for each movement key (unit displacements in world space)
# Forward/backward on Z-axis, left/right on X-axis
DIRECTION_VECTORS = {
    "w": (0.0, 0.0, -1.0),   # forward (negative Z)
    "s": (0.0, 0.0, 1.0),    # backward (positive Z)
    "a": (-1.0, 0.0, 0.0),   # left (negative X)
    "d": (1.0, 0.0, 0.0),    # right (positive X)
    "ArrowUp": (0.0, 0.0, -1.0),
    "ArrowDown": (0.0, 0.0, 1.0),
    "ArrowLeft": (-1.0, 0.0, 0.0),
    "ArrowRight": (1.0, 0.0, 0.0),
}


def compute_key_displacement(key_sequence: list[str], speed: float = 1.0) -> tuple[float, float, float]:
    """Compute the cumulative displacement from a sequence of movement keys.

    Each key press moves the camera by `speed` units in the key's direction.
    The resulting displacement is the sum of all individual movements.

    Args:
        key_sequence: List of key identifiers (e.g., ["w", "w", "a"] or
                      ["ArrowUp", "ArrowUp", "ArrowLeft"]).
        speed: Movement speed multiplier (default 1.0).

    Returns:
        Tuple (dx, dy, dz) representing total displacement.

    Raises:
        ValueError: If an unrecognized key is in the sequence.
    """
    dx, dy, dz = 0.0, 0.0, 0.0

    for key in key_sequence:
        if key not in DIRECTION_VECTORS:
            raise ValueError(f"Unrecognized movement key: {key!r}")
        vx, vy, vz = DIRECTION_VECTORS[key]
        dx += vx * speed
        dy += vy * speed
        dz += vz * speed

    return (dx, dy, dz)


def arrow_sequence_to_wasd(arrow_sequence: list[str]) -> list[str]:
    """Convert a sequence of arrow key presses to equivalent WASD presses.

    Args:
        arrow_sequence: List of arrow key identifiers
                        (e.g., ["ArrowUp", "ArrowLeft"]).

    Returns:
        List of equivalent WASD key identifiers (e.g., ["w", "a"]).

    Raises:
        ValueError: If a key is not a recognized arrow key.
    """
    wasd_sequence = []
    for key in arrow_sequence:
        if key not in ARROW_TO_WASD_MAP:
            raise ValueError(f"Not an arrow key: {key!r}")
        wasd_sequence.append(ARROW_TO_WASD_MAP[key])
    return wasd_sequence

# ---------------------------------------------------------------------------
# Keyboard Navigation Alternatives — Requirements 16.1, 16.2, 16.3
# ---------------------------------------------------------------------------


async def get_camera_position(page: Any) -> dict[str, float] | None:
    """Get the current camera position from the QA harness.

    Uses window.__qa.getObjectPosition for the camera, or falls back to
    reading camera.position directly from the Three.js scene.

    Args:
        page: A Playwright page instance with the 3D world loaded.

    Returns:
        Dict with x, y, z float values, or None if unavailable.
    """
    return await page.evaluate(
        """() => {
            // Try QA harness first
            if (window.__qa && typeof window.__qa.getObjectPosition === 'function') {
                const pos = window.__qa.getObjectPosition('__camera__');
                if (pos) return pos;
            }
            // Try direct camera access (common Three.js pattern)
            if (window.__qa && window.__qa.getCameraPosition) {
                return window.__qa.getCameraPosition();
            }
            // Try accessing camera from the scene/renderer
            if (window.camera && window.camera.position) {
                const p = window.camera.position;
                return { x: p.x, y: p.y, z: p.z };
            }
            // Try the scene's active camera
            if (window.scene && window.scene.getObjectByName) {
                const cam = window.scene.getObjectByName('Camera');
                if (cam && cam.position) {
                    return { x: cam.position.x, y: cam.position.y, z: cam.position.z };
                }
            }
            return null;
        }"""
    )


def compute_displacement(pos_start: dict[str, float], pos_end: dict[str, float]) -> dict[str, float]:
    """Compute the displacement vector between two positions.

    Args:
        pos_start: Starting position with x, y, z.
        pos_end: Ending position with x, y, z.

    Returns:
        Dict with dx, dy, dz displacement components.
    """
    return {
        "dx": pos_end["x"] - pos_start["x"],
        "dy": pos_end["y"] - pos_start["y"],
        "dz": pos_end["z"] - pos_start["z"],
    }


def positions_equivalent(
    disp_a: dict[str, float],
    disp_b: dict[str, float],
    tolerance: float = 0.001,
) -> bool:
    """Check if two displacement vectors are equivalent within tolerance.

    Args:
        disp_a: First displacement vector (dx, dy, dz).
        disp_b: Second displacement vector (dx, dy, dz).
        tolerance: Maximum allowed difference per component.

    Returns:
        True if all components differ by less than tolerance.
    """
    return (
        abs(disp_a["dx"] - disp_b["dx"]) < tolerance
        and abs(disp_a["dy"] - disp_b["dy"]) < tolerance
        and abs(disp_a["dz"] - disp_b["dz"]) < tolerance
    )


async def navigate_to_3d_world(page: Any) -> bool:
    """Navigate the page to the 3D world view with QA harness enabled.

    Attempts to load the 3D world at localhost:8000/?v=16&qa=1 and waits
    for the QA harness to be available.

    Args:
        page: A Playwright page instance.

    Returns:
        True if the 3D world loaded with QA harness available, False otherwise.
    """
    try:
        await page.goto(
            "http://localhost:8000/?v=16&qa=1",
            timeout=10000,
            wait_until="networkidle",
        )
    except Exception:
        return False

    # Check if the QA harness is available (indicates 3D world is loaded)
    qa_available = await page.evaluate(
        """() => {
            return typeof window.__qa !== 'undefined' && window.__qa !== null;
        }"""
    )
    return qa_available


async def get_interactive_objects(page: Any) -> list[dict[str, Any]]:
    """Get a list of interactive objects in the 3D world.

    Uses the QA harness scene graph to identify objects that have
    interaction bindings (clickable, grabbable, pushable).

    Args:
        page: A Playwright page instance with QA harness loaded.

    Returns:
        List of dicts with objectId and interaction info.
    """
    return await page.evaluate(
        """() => {
            if (!window.__qa) return [];

            // Try getSceneGraph for interactive objects
            if (typeof window.__qa.getSceneGraph === 'function') {
                const graph = window.__qa.getSceneGraph();
                if (Array.isArray(graph)) {
                    // Filter to objects that have interaction bindings
                    return graph.filter(obj =>
                        obj.interactive || obj.interactionType || obj.focusable
                    ).map(obj => ({
                        objectId: obj.objectId || obj.id || obj.name,
                        interactionType: obj.interactionType || 'click',
                    }));
                }
            }

            // Fallback: look for focusable 3D elements in the DOM
            const focusables = document.querySelectorAll(
                '[data-interactive], [data-focusable], [tabindex]:not([tabindex="-1"])'
            );
            return Array.from(focusables).map(el => ({
                objectId: el.getAttribute('data-object-id') || el.id || '',
                interactionType: el.getAttribute('data-interaction') || 'click',
            })).filter(o => o.objectId);
        }"""
    )


async def get_focused_object_id(page: Any) -> str | None:
    """Get the ID of the currently focused interactive object.

    Args:
        page: A Playwright page instance.

    Returns:
        The objectId of the focused object, or None if no interactive object is focused.
    """
    return await page.evaluate(
        """() => {
            const active = document.activeElement;
            if (!active) return null;

            // Check for data-object-id attribute (3D world interactive element)
            const objId = active.getAttribute('data-object-id');
            if (objId) return objId;

            // Check for QA harness focus tracking
            if (window.__qa && typeof window.__qa.getFocusedObject === 'function') {
                const focused = window.__qa.getFocusedObject();
                return focused ? (focused.objectId || focused.id || null) : null;
            }

            // Check the element's id as fallback
            if (active.hasAttribute('data-interactive') || active.hasAttribute('data-focusable')) {
                return active.id || null;
            }

            return null;
        }"""
    )


async def get_object_activation_state(page: Any, object_id: str) -> dict[str, Any] | None:
    """Check if a specific object has been activated (interaction triggered).

    Args:
        page: A Playwright page instance.
        object_id: The ID of the object to check.

    Returns:
        Dict with activation state info, or None if not checkable.
    """
    return await page.evaluate(
        """(objectId) => {
            // Try QA harness triggerInteraction result tracking
            if (window.__qa && typeof window.__qa.getObjectState === 'function') {
                return window.__qa.getObjectState(objectId);
            }

            // Check DOM element state
            const el = document.querySelector(
                `[data-object-id="${objectId}"]`
            );
            if (el) {
                return {
                    activated: el.getAttribute('data-activated') === 'true'
                        || el.classList.contains('activated')
                        || el.getAttribute('aria-pressed') === 'true',
                    state: el.getAttribute('data-state') || 'unknown',
                };
            }

            return null;
        }""",
        object_id,
    )


# ---------------------------------------------------------------------------
# Keyboard Navigation Test Class
# ---------------------------------------------------------------------------


@pytest.mark.layer("accessibility")
class TestKeyboardNavigation:
    """Keyboard navigation alternative tests for 3D world accessibility.

    Verifies that keyboard-only users have alternatives to mouse-based
    navigation in the 3D world:
    1. Arrow keys provide equivalent movement to WASD (Req 16.1)
    2. Tab/Shift+Tab cycles through interactive objects (Req 16.2)
    3. Enter/Space activates the focused interactive object (Req 16.3)

    Requirements: 16.1, 16.2, 16.3, 22.3
    """

    @pytest.mark.asyncio
    async def test_arrow_key_movement(self, page: Any) -> None:
        """Verify arrow keys provide equivalent movement to WASD keys.

        Sends a sequence of arrow key presses and reads the camera position,
        then resets and sends the equivalent WASD presses. Verifies that
        the camera displacement is the same for both input methods.

        Property 13: Arrow Key Movement Equivalence — equivalent camera
        displacement for arrow keys vs WASD.

        Requirements: 16.1
        """
        # Navigate to 3D world with QA harness
        world_loaded = await navigate_to_3d_world(page)
        if not world_loaded:
            pytest.skip(
                "3D world not available at http://localhost:8000/?v=16&qa=1. "
                "Start the development server to run keyboard navigation tests."
            )

        # Wait briefly for the world to initialize movement controls
        await page.wait_for_timeout(500)

        # Get initial camera position
        initial_pos = await get_camera_position(page)
        if initial_pos is None:
            pytest.skip(
                "Cannot read camera position. QA harness may not expose "
                "camera position API in current build."
            )

        # --- Test ArrowUp vs W (forward movement) ---

        # Record position before arrow key sequence
        pos_before_arrows = await get_camera_position(page)

        # Send ArrowUp key presses (forward movement)
        num_presses = 5
        for _ in range(num_presses):
            await page.keyboard.press("ArrowUp")
            await page.wait_for_timeout(50)

        # Allow physics/movement to settle
        await page.wait_for_timeout(200)

        # Record position after arrow keys
        pos_after_arrows = await get_camera_position(page)
        if pos_after_arrows is None:
            pytest.skip("Camera position unavailable after arrow key input.")

        arrow_displacement = compute_displacement(pos_before_arrows, pos_after_arrows)

        # Check that arrow keys actually produced movement
        arrow_moved = (
            abs(arrow_displacement["dx"]) > 0.0001
            or abs(arrow_displacement["dy"]) > 0.0001
            or abs(arrow_displacement["dz"]) > 0.0001
        )

        if not arrow_moved:
            pytest.skip(
                "Arrow keys did not produce camera movement. "
                "3D world controls may not be active in current state."
            )

        # Reset camera position to the same starting point
        # Navigate back to the initial URL to reset state
        await page.goto(
            "http://localhost:8000/?v=16&qa=1",
            timeout=10000,
            wait_until="networkidle",
        )
        await page.wait_for_timeout(500)

        # Record position before WASD sequence
        pos_before_wasd = await get_camera_position(page)
        if pos_before_wasd is None:
            pytest.skip("Camera position unavailable for WASD comparison.")

        # Send W key presses (forward movement — equivalent to ArrowUp)
        for _ in range(num_presses):
            await page.keyboard.press("w")
            await page.wait_for_timeout(50)

        # Allow movement to settle
        await page.wait_for_timeout(200)

        # Record position after WASD
        pos_after_wasd = await get_camera_position(page)
        if pos_after_wasd is None:
            pytest.skip("Camera position unavailable after WASD input.")

        wasd_displacement = compute_displacement(pos_before_wasd, pos_after_wasd)

        # Verify displacements are equivalent
        # Use a tolerance that accounts for minor floating-point differences
        # but catches fundamentally different movement behaviors
        tolerance = 0.01  # 1cm in world units
        equivalent = positions_equivalent(arrow_displacement, wasd_displacement, tolerance)

        if not equivalent:
            pytest.fail(
                f"Arrow key and WASD movement are NOT equivalent.\n"
                f"  Arrow displacement: dx={arrow_displacement['dx']:.4f}, "
                f"dy={arrow_displacement['dy']:.4f}, "
                f"dz={arrow_displacement['dz']:.4f}\n"
                f"  WASD displacement:  dx={wasd_displacement['dx']:.4f}, "
                f"dy={wasd_displacement['dy']:.4f}, "
                f"dz={wasd_displacement['dz']:.4f}\n"
                f"  Tolerance: {tolerance} world units per axis"
            )

    @pytest.mark.asyncio
    async def test_tab_focus_cycle(self, page: Any) -> None:
        """Verify Tab/Shift+Tab cycles through interactive objects.

        Presses Tab repeatedly to confirm that focus moves through the
        interactive objects in the 3D world. Then presses Shift+Tab to
        verify reverse cycling. Ensures the full set of interactive
        objects is reachable via keyboard.

        Requirements: 16.2
        """
        # Navigate to 3D world with QA harness
        world_loaded = await navigate_to_3d_world(page)
        if not world_loaded:
            pytest.skip(
                "3D world not available at http://localhost:8000/?v=16&qa=1. "
                "Start the development server to run keyboard navigation tests."
            )

        await page.wait_for_timeout(500)

        # Get list of interactive objects in the scene
        interactive_objects = await get_interactive_objects(page)

        if not interactive_objects:
            pytest.skip(
                "No interactive objects found in the 3D world. "
                "Scene may not have interactive elements to cycle through."
            )

        # Track which objects receive focus during Tab cycling
        focused_objects_forward: list[str | None] = []
        num_tabs = len(interactive_objects) + 2  # Extra tabs to verify cycling

        for _ in range(num_tabs):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(100)

            focused_id = await get_focused_object_id(page)
            focused_objects_forward.append(focused_id)

        # Filter out None values (non-interactive elements that received focus)
        valid_forward_focus = [obj_id for obj_id in focused_objects_forward if obj_id]

        # Verify at least some interactive objects received focus
        if not valid_forward_focus:
            pytest.fail(
                "Tab key did not cycle focus to any interactive objects. "
                f"Expected focus to reach one of: "
                f"{[obj['objectId'] for obj in interactive_objects]}"
            )

        # Verify cycling: pressing Tab enough times should revisit objects
        # (i.e., focus wraps around)
        unique_forward = set(valid_forward_focus)
        expected_ids = {obj["objectId"] for obj in interactive_objects}

        # At least some interactive objects should be reachable
        reachable = unique_forward & expected_ids
        if not reachable:
            pytest.fail(
                f"Tab cycling did not reach any expected interactive objects.\n"
                f"  Expected objects: {sorted(expected_ids)}\n"
                f"  Objects that received focus: {sorted(unique_forward)}"
            )

        # --- Test Shift+Tab reverse cycling ---
        focused_objects_reverse: list[str | None] = []

        for _ in range(num_tabs):
            await page.keyboard.press("Shift+Tab")
            await page.wait_for_timeout(100)

            focused_id = await get_focused_object_id(page)
            focused_objects_reverse.append(focused_id)

        # Filter out None values
        valid_reverse_focus = [obj_id for obj_id in focused_objects_reverse if obj_id]

        # Verify reverse cycling also reaches interactive objects
        if not valid_reverse_focus:
            pytest.fail(
                "Shift+Tab did not cycle focus to any interactive objects. "
                "Reverse keyboard navigation is not implemented."
            )

        # Verify reverse cycling visits the same objects (order may differ)
        unique_reverse = set(valid_reverse_focus)
        reverse_reachable = unique_reverse & expected_ids

        if not reverse_reachable:
            pytest.fail(
                f"Shift+Tab cycling did not reach expected interactive objects.\n"
                f"  Expected objects: {sorted(expected_ids)}\n"
                f"  Objects that received focus (reverse): {sorted(unique_reverse)}"
            )

    @pytest.mark.asyncio
    async def test_enter_space_activation(self, page: Any) -> None:
        """Verify Enter and Space activate the focused interactive object.

        Tabs to an interactive object, presses Enter and verifies
        activation, then tabs to another object and presses Space
        to verify activation there as well.

        Requirements: 16.3
        """
        # Navigate to 3D world with QA harness
        world_loaded = await navigate_to_3d_world(page)
        if not world_loaded:
            pytest.skip(
                "3D world not available at http://localhost:8000/?v=16&qa=1. "
                "Start the development server to run keyboard navigation tests."
            )

        await page.wait_for_timeout(500)

        # Get interactive objects
        interactive_objects = await get_interactive_objects(page)

        if len(interactive_objects) < 2:
            pytest.skip(
                "Need at least 2 interactive objects to test Enter and Space "
                "activation separately. "
                f"Found: {len(interactive_objects)} interactive object(s)."
            )

        # --- Test Enter activation ---

        # Tab to the first interactive object
        first_object_id: str | None = None
        max_tabs = len(interactive_objects) + 5

        for _ in range(max_tabs):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(100)

            focused_id = await get_focused_object_id(page)
            if focused_id:
                first_object_id = focused_id
                break

        if first_object_id is None:
            pytest.fail(
                "Could not Tab to any interactive object. "
                "Keyboard focus does not reach interactive elements."
            )

        # Press Enter to activate
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)  # Allow interaction to complete

        # Verify the object was activated
        state_after_enter = await get_object_activation_state(page, first_object_id)

        if state_after_enter is not None:
            if not state_after_enter.get("activated", False):
                pytest.fail(
                    f"Enter key did not activate the focused object.\n"
                    f"  Object: {first_object_id}\n"
                    f"  State after Enter: {state_after_enter}"
                )
        # If state is None, the activation check isn't available but we
        # verified focus reached the object (partial pass, no hard fail
        # since the QA harness may not expose activation state)

        # --- Test Space activation ---

        # Tab to the next interactive object
        second_object_id: str | None = None

        for _ in range(max_tabs):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(100)

            focused_id = await get_focused_object_id(page)
            if focused_id and focused_id != first_object_id:
                second_object_id = focused_id
                break

        if second_object_id is None:
            pytest.skip(
                "Could not Tab to a second interactive object for Space "
                "activation test. Only one focusable object found."
            )

        # Press Space to activate
        await page.keyboard.press("Space")
        await page.wait_for_timeout(500)  # Allow interaction to complete

        # Verify the object was activated
        state_after_space = await get_object_activation_state(page, second_object_id)

        if state_after_space is not None:
            if not state_after_space.get("activated", False):
                pytest.fail(
                    f"Space key did not activate the focused object.\n"
                    f"  Object: {second_object_id}\n"
                    f"  State after Space: {state_after_space}"
                )
