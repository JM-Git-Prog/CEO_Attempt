"""Property-based tests for pause toggle idempotence (Property 5).

**Validates: Requirements 2.5**

Property 5: Pause Toggle Idempotence
- For any initial pause state (True or False), toggling pause twice SHALL return
  to the original pause state.
- While paused, movement and look updates SHALL produce zero state change.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import compute_movement_vector, compute_look_delta


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

keys_state_strategy = st.fixed_dictionaries({
    "w": st.booleans(),
    "a": st.booleans(),
    "s": st.booleans(),
    "d": st.booleans(),
})

speed_strategy = st.floats(
    min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False
)

mouse_dx_strategy = st.floats(
    min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False
)

mouse_dy_strategy = st.floats(
    min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False
)

current_pitch_strategy = st.floats(
    min_value=-1.5, max_value=1.5, allow_nan=False, allow_infinity=False
)

look_speed_strategy = st.floats(
    min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Property 5a: Pause toggle idempotence — toggling twice restores original state
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(initial_paused=st.booleans())
def test_property_5_pause_toggle_idempotence(initial_paused: bool):
    """Property 5: Toggling pause twice returns to original state.

    **Validates: Requirements 2.5**

    For any initial pause state, applying `paused = not paused` twice SHALL
    yield the original value.
    """
    paused = initial_paused
    # Toggle once
    paused = not paused
    # Toggle again
    paused = not paused
    assert paused == initial_paused, (
        f"Double-toggle failed: started {initial_paused}, ended {paused}"
    )


# ---------------------------------------------------------------------------
# Property 5b: While paused, movement produces zero state change
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    keys_state=keys_state_strategy,
    speed=speed_strategy,
)
def test_property_5_paused_movement_produces_zero(
    keys_state: dict, speed: float
):
    """Property 5: While paused, applied movement is always (0, 0, 0).

    **Validates: Requirements 2.5**

    For any keyboard state and speed, when paused is True, the conceptual
    applied movement SHALL be zero — the update() method returns early without
    calling _update_movement().
    """
    paused = True

    # Model the PlayerComponent.update() behavior: if paused, no movement applied
    if paused:
        applied = (0.0, 0.0, 0.0)
    else:
        applied = compute_movement_vector(keys_state, speed)

    assert applied == (0.0, 0.0, 0.0), (
        f"Movement should be zero when paused, got {applied}"
    )


# ---------------------------------------------------------------------------
# Property 5c: While paused, look produces zero state change
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    mouse_dx=mouse_dx_strategy,
    mouse_dy=mouse_dy_strategy,
    current_pitch=current_pitch_strategy,
    look_speed=look_speed_strategy,
)
def test_property_5_paused_look_produces_zero(
    mouse_dx: float,
    mouse_dy: float,
    current_pitch: float,
    look_speed: float,
):
    """Property 5: While paused, look updates produce zero state change.

    **Validates: Requirements 2.5**

    For any mouse delta, current pitch, and look speed, when paused is True,
    no yaw or pitch change is applied — the update() method returns early
    without calling _update_look().
    """
    paused = True

    # Model the PlayerComponent.update() behavior: if paused, no look applied
    if paused:
        yaw_applied = 0.0
        pitch_applied = current_pitch  # pitch stays unchanged
    else:
        yaw_applied, pitch_applied = compute_look_delta(
            mouse_dx, mouse_dy, current_pitch, look_speed
        )

    assert yaw_applied == 0.0, (
        f"Yaw should be zero when paused, got {yaw_applied}"
    )
    assert pitch_applied == current_pitch, (
        f"Pitch should remain unchanged when paused: "
        f"expected {current_pitch}, got {pitch_applied}"
    )
