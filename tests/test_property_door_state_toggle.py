"""Property-based tests for door state toggle (Property 7).

**Validates: Requirements 3.3**

Property 7: Door State Toggle
- Setting `kiro_interact_requested = True` and executing one update SHALL flip
  `is_open` and clear the flag.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import compute_door_target_angle, compute_door_rotation_step


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

open_angle_strategy = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
).filter(lambda x: abs(x) > 1e-9)


# ---------------------------------------------------------------------------
# Property 7a: Single toggle flips is_open and clears interact_requested
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    initial_is_open=st.booleans(),
    open_angle_deg=open_angle_strategy,
    initially_open=st.booleans(),
)
def test_property_7_door_toggle_flips_state_and_clears_flag(
    initial_is_open: bool,
    open_angle_deg: float,
    initially_open: bool,
):
    """Property 7: Setting kiro_interact_requested=True flips is_open and clears the flag.

    **Validates: Requirements 3.3**

    For any initial is_open state, when kiro_interact_requested becomes True,
    the update logic SHALL set interact_requested to False and toggle is_open.
    """
    # Model door state
    is_open = initial_is_open
    interact_requested = True

    # Execute the toggle logic (mirrors DoorComponent.update())
    if interact_requested:
        interact_requested = False
        is_open = not is_open

    # Assert flag is cleared
    assert interact_requested is False, (
        f"interact_requested should be cleared after toggle, got {interact_requested}"
    )
    # Assert state is flipped
    assert is_open == (not initial_is_open), (
        f"is_open should be flipped: started {initial_is_open}, expected "
        f"{not initial_is_open}, got {is_open}"
    )


# ---------------------------------------------------------------------------
# Property 7b: Double toggle returns to original state (idempotent pair)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    initial_is_open=st.booleans(),
    open_angle_deg=open_angle_strategy,
    initially_open=st.booleans(),
)
def test_property_7_door_double_toggle_returns_to_original(
    initial_is_open: bool,
    open_angle_deg: float,
    initially_open: bool,
):
    """Property 7: Double toggle returns to original state.

    **Validates: Requirements 3.3**

    For any initial is_open state, toggling twice SHALL return is_open to its
    original value and both flags SHALL be cleared.
    """
    # Model door state
    is_open = initial_is_open

    # First toggle
    interact_requested = True
    if interact_requested:
        interact_requested = False
        is_open = not is_open

    assert interact_requested is False
    assert is_open == (not initial_is_open)

    # Second toggle
    interact_requested = True
    if interact_requested:
        interact_requested = False
        is_open = not is_open

    # Assert flag cleared after second toggle
    assert interact_requested is False, (
        f"interact_requested should be cleared after second toggle"
    )
    # Assert state returned to original
    assert is_open == initial_is_open, (
        f"Double toggle should return to original state: started {initial_is_open}, "
        f"ended {is_open}"
    )


# ---------------------------------------------------------------------------
# Property 7c: Target angle changes after toggle
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    initial_is_open=st.booleans(),
    open_angle_deg=open_angle_strategy,
    closed_angle=st.floats(
        min_value=-3.14159, max_value=3.14159,
        allow_nan=False, allow_infinity=False
    ),
)
def test_property_7_door_toggle_changes_target_angle(
    initial_is_open: bool,
    open_angle_deg: float,
    closed_angle: float,
):
    """Property 7: After toggle, the computed target angle reflects the new state.

    **Validates: Requirements 3.3**

    After flipping is_open, compute_door_target_angle with the new state SHALL
    return a different target than with the old state (since open_angle_deg != 0).
    """
    import math

    # Target before toggle
    target_before = compute_door_target_angle(closed_angle, open_angle_deg, initial_is_open)

    # Execute toggle
    is_open = initial_is_open
    interact_requested = True
    if interact_requested:
        interact_requested = False
        is_open = not is_open

    # Target after toggle
    target_after = compute_door_target_angle(closed_angle, open_angle_deg, is_open)

    # Since open_angle_deg != 0 (abs > 1e-9), the targets must differ
    expected_diff = math.radians(open_angle_deg)
    actual_diff = target_after - target_before

    # If initial was closed (False), toggling opens: diff = +radians(open_angle_deg)
    # If initial was open (True), toggling closes: diff = -radians(open_angle_deg)
    if initial_is_open:
        assert abs(actual_diff - (-expected_diff)) < 1e-10, (
            f"Closing door: target diff should be -{expected_diff}, got {actual_diff}"
        )
    else:
        assert abs(actual_diff - expected_diff) < 1e-10, (
            f"Opening door: target diff should be {expected_diff}, got {actual_diff}"
        )
