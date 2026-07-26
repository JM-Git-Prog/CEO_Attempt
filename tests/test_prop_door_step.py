"""Property-based tests for door animation step convergence (Property 8).

**Validates: Requirements 5.3**

Property 8: Door Animation Step Convergence
- Per-frame step advances toward target without overshooting;
  step = min(|target - current|, speed_deg_s / frame_rate)
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.player_math import compute_door_step


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Angles in a reasonable range for door rotation (degrees)
angles = st.floats(min_value=-360.0, max_value=360.0, allow_nan=False, allow_infinity=False)

# Speed must be strictly positive (degrees per second)
speeds = st.floats(min_value=0.01, max_value=720.0, allow_nan=False, allow_infinity=False)

# Frame rate must be strictly positive
frame_rates = st.floats(min_value=1.0, max_value=240.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestDoorStepNoOvershooting:
    """Property 8a: The result never overshoots the target.

    For any current_angle, target_angle, speed_deg_s > 0, frame_rate > 0:
    if current < target then current <= result <= target;
    if current > target then target <= result <= current.

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=500)
    def test_result_between_current_and_target(
        self, current: float, target: float, speed: float, fps: float
    ):
        """Result is always between current and target (inclusive)."""
        # Skip near-equal cases where floating-point arithmetic can't
        # distinguish between "overshooting" and "at target"
        assume(abs(current - target) > 1e-9)

        result = compute_door_step(current, target, speed, fps)

        if current <= target:
            assert current <= result <= target, (
                f"Overshoot: current={current}, target={target}, result={result}"
            )
        else:
            assert target <= result <= current, (
                f"Overshoot: current={current}, target={target}, result={result}"
            )


class TestDoorStepConvergence:
    """Property 8b: Repeated application converges to target within finite steps.

    Given max_step = speed_deg_s / frame_rate, the number of frames needed is
    at most ceil(|target - current| / max_step).

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=500, deadline=None)
    def test_convergence_within_bounded_steps(
        self, current: float, target: float, speed: float, fps: float
    ):
        """Repeated stepping reaches target exactly within theoretical max steps."""
        max_step = speed / fps
        distance = abs(target - current)
        # Bound iterations to avoid extremely long-running cases
        assume(distance / max_step <= 10000)

        max_frames = math.ceil(distance / max_step) + 1  # +1 for rounding safety

        angle = current
        for _ in range(max_frames):
            angle = compute_door_step(angle, target, speed, fps)

        assert angle == pytest.approx(target, abs=1e-9), (
            f"Did not converge: current={current}, target={target}, "
            f"final={angle}, max_frames={max_frames}"
        )


class TestDoorStepSize:
    """Property 8c: Each step advances by exactly the correct amount.

    step_taken = min(|target - current|, speed_deg_s / frame_rate) in correct direction.

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=500)
    def test_step_size_is_correct(
        self, current: float, target: float, speed: float, fps: float
    ):
        """The advancement equals min(|difference|, max_step) toward target."""
        result = compute_door_step(current, target, speed, fps)
        max_step = speed / fps
        difference = target - current
        expected_advance = max(-max_step, min(max_step, difference))

        assert result == pytest.approx(current + expected_advance, abs=1e-12), (
            f"Step size wrong: current={current}, target={target}, "
            f"result={result}, expected={current + expected_advance}"
        )


class TestDoorStepIdempotence:
    """Property 8d: Once current == target, the result stays at target.

    No oscillation or drift when already at the target angle.

    **Validates: Requirements 5.3**
    """

    @given(
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=500)
    def test_at_target_stays_at_target(
        self, target: float, speed: float, fps: float
    ):
        """When current equals target, result equals target exactly."""
        result = compute_door_step(target, target, speed, fps)
        assert result == target, (
            f"Oscillation: target={target}, result={result}"
        )
