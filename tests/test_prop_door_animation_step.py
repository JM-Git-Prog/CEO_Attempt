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

# Reasonable angle range in degrees
angles = st.floats(min_value=-360.0, max_value=360.0)
# Positive speed (degrees/second), avoids degenerate zero/negative
speeds = st.floats(min_value=1.0, max_value=720.0)
# Positive frame rates
frame_rates = st.floats(min_value=1.0, max_value=240.0)


# ---------------------------------------------------------------------------
# Property 8a: Single step never overshoots
# ---------------------------------------------------------------------------


class TestDoorStepNoOvershoot:
    """Property 8a: A single step never overshoots the target.

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=50)
    def test_result_between_current_and_target(
        self, current: float, target: float, speed: float, fps: float
    ):
        """After one step, the new angle lies between current and target (inclusive)."""
        result = compute_door_step(current, target, speed, fps)

        lo = min(current, target)
        hi = max(current, target)
        assert lo - 1e-9 <= result <= hi + 1e-9, (
            f"result={result} not in [{lo}, {hi}] "
            f"(current={current}, target={target}, speed={speed}, fps={fps})"
        )


# ---------------------------------------------------------------------------
# Property 8b: Step size is correct
# ---------------------------------------------------------------------------


class TestDoorStepSize:
    """Property 8b: The absolute advancement equals min(|target - current|, step).

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=50)
    def test_advancement_equals_expected(
        self, current: float, target: float, speed: float, fps: float
    ):
        """The distance moved equals min(|difference|, max_step)."""
        result = compute_door_step(current, target, speed, fps)

        max_step = speed / fps
        difference = abs(target - current)
        expected_advance = min(difference, max_step)
        actual_advance = abs(result - current)

        assert actual_advance == pytest.approx(expected_advance, abs=1e-9), (
            f"actual_advance={actual_advance} != expected={expected_advance} "
            f"(current={current}, target={target}, speed={speed}, fps={fps})"
        )


# ---------------------------------------------------------------------------
# Property 8c: Convergence — repeated application reaches the target
# ---------------------------------------------------------------------------


class TestDoorStepConvergence:
    """Property 8c: Repeatedly applying the step function reaches the target.

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=50)
    def test_converges_to_target(
        self, current: float, target: float, speed: float, fps: float
    ):
        """Iterating compute_door_step converges to target within finite steps."""
        angle = current
        max_step = speed / fps
        # Upper bound on iterations: distance / step + a small margin
        distance = abs(target - current)
        if max_step == 0:
            return
        max_iterations = int(distance / max_step) + 10

        for _ in range(max_iterations):
            angle = compute_door_step(angle, target, speed, fps)
            if abs(angle - target) < 1e-9:
                break

        assert angle == pytest.approx(target, abs=1e-9), (
            f"Did not converge: final={angle}, target={target} "
            f"after {max_iterations} iterations "
            f"(current={current}, speed={speed}, fps={fps})"
        )


# ---------------------------------------------------------------------------
# Property 8d: Monotonic approach — each step brings angle closer to target
# ---------------------------------------------------------------------------


class TestDoorStepMonotonic:
    """Property 8d: Each step brings the angle closer to or equal to the target.

    **Validates: Requirements 5.3**
    """

    @given(
        current=angles,
        target=angles,
        speed=speeds,
        fps=frame_rates,
    )
    @settings(max_examples=50)
    def test_distance_never_increases(
        self, current: float, target: float, speed: float, fps: float
    ):
        """The distance to target is non-increasing after each step."""
        dist_before = abs(target - current)
        result = compute_door_step(current, target, speed, fps)
        dist_after = abs(target - result)

        assert dist_after <= dist_before + 1e-9, (
            f"Distance increased: {dist_before} -> {dist_after} "
            f"(current={current}, target={target}, speed={speed}, fps={fps})"
        )
