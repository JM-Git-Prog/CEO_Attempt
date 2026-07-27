"""Property-based test for door rotation convergence (Property 8).

**Validates: Requirements 3.6**

Property 8: Door Rotation Convergence
- For any open_angle_deg in [-180, 180] \\ {0} and speed_deg_s in (0, 720],
  iterating the animation for bounded frames SHALL converge within tolerance.
- The door rotation SHALL reach the target angle and stop (convergence property).
"""
from __future__ import annotations

import math

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.upbge_runtime import compute_door_target_angle, compute_door_rotation_step


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

closed_angles = st.floats(min_value=-math.pi, max_value=math.pi)

open_angle_degs = st.floats(
    min_value=-180.0, max_value=180.0
).filter(lambda x: abs(x) > 0.01)

speed_degs = st.floats(min_value=0.1, max_value=720.0)


# ---------------------------------------------------------------------------
# Property 8: Door rotation convergence
# ---------------------------------------------------------------------------


class TestDoorRotationConvergence:
    """Property 8: Door rotation converges to target within bounded frames.

    **Validates: Requirements 3.6**
    """

    @given(
        closed_angle=closed_angles,
        open_angle_deg=open_angle_degs,
        speed_deg_s=speed_degs,
    )
    @settings(max_examples=300)
    def test_converges_within_bounded_frames(
        self,
        closed_angle: float,
        open_angle_deg: float,
        speed_deg_s: float,
    ):
        """Iterating compute_door_rotation_step converges within tolerance."""
        target_angle = compute_door_target_angle(
            closed_angle, open_angle_deg, is_open=True
        )

        current_angle = closed_angle  # door starts closed

        # Max frames needed: ceil(|open_angle_deg| / speed_deg_s * 60) + 1
        max_frames = math.ceil(abs(open_angle_deg) / speed_deg_s * 60) + 1

        for _ in range(max_frames):
            current_angle = compute_door_rotation_step(
                current_angle, target_angle, speed_deg_s
            )

        # After max_frames iterations, angle should be within one step of target
        one_step = math.radians(speed_deg_s) / 60.0
        assert abs(current_angle - target_angle) <= one_step + 1e-9, (
            f"Did not converge: final={current_angle}, target={target_angle}, "
            f"diff={abs(current_angle - target_angle)}, one_step={one_step}, "
            f"closed_angle={closed_angle}, open_angle_deg={open_angle_deg}, "
            f"speed_deg_s={speed_deg_s}, max_frames={max_frames}"
        )

    @given(
        closed_angle=closed_angles,
        open_angle_deg=open_angle_degs,
        speed_deg_s=speed_degs,
    )
    @settings(max_examples=300)
    def test_monotonic_convergence(
        self,
        closed_angle: float,
        open_angle_deg: float,
        speed_deg_s: float,
    ):
        """Angle never overshoots the target (monotonic convergence)."""
        target_angle = compute_door_target_angle(
            closed_angle, open_angle_deg, is_open=True
        )

        current_angle = closed_angle  # door starts closed

        max_frames = math.ceil(abs(open_angle_deg) / speed_deg_s * 60) + 1

        for i in range(max_frames):
            dist_before = abs(target_angle - current_angle)
            new_angle = compute_door_rotation_step(
                current_angle, target_angle, speed_deg_s
            )
            dist_after = abs(target_angle - new_angle)

            # Distance to target must never increase (monotonic approach)
            assert dist_after <= dist_before + 1e-9, (
                f"Overshoot at frame {i}: distance increased from "
                f"{dist_before} to {dist_after}. "
                f"current={current_angle}, new={new_angle}, target={target_angle}, "
                f"closed_angle={closed_angle}, open_angle_deg={open_angle_deg}, "
                f"speed_deg_s={speed_deg_s}"
            )

            current_angle = new_angle
