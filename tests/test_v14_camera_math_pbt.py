"""Property-based tests for camera math utilities.

# Feature: photo-to-real-3d-world-v14

## Property 9: Back-Projection Formula Correctness

**Validates: Requirements 4.1, 4.2**

For any pixel coordinate (u, v), positive depth value d, and camera intrinsics
(fx, fy, cx, cy), the back-projection SHALL produce:
  x = (u - cx) * d / fx
  y = -(v - cy) * d / fy
  z = -d

## Property 10: Position Clamping to Room Bounds

**Validates: Requirements 4.4**

For any 3D position and room shell bounding volume, the clamped position
SHALL lie within the bounding volume minus a 0.05m margin on all axes.

Uses Hypothesis with custom strategies to generate:
- position: 3-tuple of floats (-100 to 100)
- bbox_min: 3-tuple of floats (-50 to 0)
- bbox_max: 3-tuple where each component > corresponding bbox_min + 0.2
- margin: positive float (default 0.05, also test other positive values)

Verifies:
1. For each axis i: bbox_min[i] + margin <= result[i] <= bbox_max[i] - margin
2. If position is already inside bounds, it passes through unchanged
"""

from __future__ import annotations

import math

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.camera_math import back_project, clamp_to_bounds


# ---------------------------------------------------------------------------
# Property 9: Back-Projection Formula Correctness
# ---------------------------------------------------------------------------

# Strategies for back-projection inputs
_pixel_coord = st.floats(min_value=0.0, max_value=4000.0, allow_nan=False, allow_infinity=False)
_depth_value = st.floats(min_value=0.01, max_value=20.0, allow_nan=False, allow_infinity=False)
_focal_length = st.floats(min_value=100.0, max_value=5000.0, allow_nan=False, allow_infinity=False)
_principal_point = st.floats(min_value=0.0, max_value=4000.0, allow_nan=False, allow_infinity=False)


class TestBackProjectionFormulaProperty:
    """Property 9: Back-Projection Formula Correctness.

    **Validates: Requirements 4.1, 4.2**

    For any pixel coordinate (u, v), positive depth value d, and camera
    intrinsics (fx, fy, cx, cy), the back-projection SHALL produce:
      x = (u - cx) * d / fx
      y = -(v - cy) * d / fy
      z = -d
    """

    @given(
        u=_pixel_coord,
        v=_pixel_coord,
        d=_depth_value,
        fx=_focal_length,
        fy=_focal_length,
        cx=_principal_point,
        cy=_principal_point,
    )
    @settings(max_examples=50, deadline=None)
    def test_back_projection_formula_correctness(
        self,
        u: float,
        v: float,
        d: float,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
    ) -> None:
        """Back-projection produces exact formula results for all valid inputs."""
        x, y, z = back_project(u, v, d, fx, fy, cx, cy)

        expected_x = (u - cx) * d / fx
        expected_y = -(v - cy) * d / fy
        expected_z = -d

        assert math.isclose(x, expected_x, rel_tol=1e-9, abs_tol=1e-12), (
            f"x mismatch: got {x}, expected {expected_x}\n"
            f"  u={u}, cx={cx}, d={d}, fx={fx}"
        )
        assert math.isclose(y, expected_y, rel_tol=1e-9, abs_tol=1e-12), (
            f"y mismatch: got {y}, expected {expected_y}\n"
            f"  v={v}, cy={cy}, d={d}, fy={fy}"
        )
        assert z == expected_z, (
            f"z mismatch: got {z}, expected {expected_z}\n"
            f"  d={d}"
        )

    @given(
        u=_pixel_coord,
        v=_pixel_coord,
        d=_depth_value,
        fx=_focal_length,
        fy=_focal_length,
        cx=_principal_point,
        cy=_principal_point,
    )
    @settings(max_examples=50, deadline=None)
    def test_back_projection_z_always_negative(
        self,
        u: float,
        v: float,
        d: float,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
    ) -> None:
        """z component is always -d (negative) for any positive depth."""
        _, _, z = back_project(u, v, d, fx, fy, cx, cy)
        assert z < 0, f"z should be negative for positive depth d={d}, got z={z}"
        assert z == -d

    @given(
        d=_depth_value,
        fx=_focal_length,
        fy=_focal_length,
        cx=_principal_point,
        cy=_principal_point,
    )
    @settings(max_examples=50, deadline=None)
    def test_back_projection_at_principal_point_yields_zero_xy(
        self,
        d: float,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
    ) -> None:
        """When pixel is at principal point (cx, cy), x=0 and y=0."""
        x, y, z = back_project(cx, cy, d, fx, fy, cx, cy)

        assert x == 0.0, f"x should be 0 at principal point, got {x}"
        assert y == 0.0, f"y should be 0 at principal point, got {y}"
        assert z == -d


# ---------------------------------------------------------------------------
# Strategies for Position Clamping (Property 10)
# ---------------------------------------------------------------------------

# Position components: wide range to test extreme out-of-bounds cases
_position_component = st.floats(
    min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

# Bounding box min components: negative or zero
_bbox_min_component = st.floats(
    min_value=-50.0, max_value=0.0, allow_nan=False, allow_infinity=False
)

# Margin: positive values (minimum ensures room for margin on both sides)
_margin = st.floats(
    min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def bounded_inputs(draw: st.DrawFn) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    float,
]:
    """Generate valid (position, bbox_min, bbox_max, margin) tuples.

    Ensures bbox_max[i] > bbox_min[i] + 2*margin for each axis so the
    clamped region is non-degenerate.
    """
    margin = draw(_margin)

    # Generate bbox_min
    min_x = draw(_bbox_min_component)
    min_y = draw(_bbox_min_component)
    min_z = draw(_bbox_min_component)

    # Generate bbox_max ensuring each component > min + 2*margin + 0.01
    # This guarantees the inner clamped region has positive extent
    min_extent = 2 * margin + 0.01
    max_x = draw(st.floats(
        min_value=min_x + min_extent, max_value=min_x + 100.0,
        allow_nan=False, allow_infinity=False,
    ))
    max_y = draw(st.floats(
        min_value=min_y + min_extent, max_value=min_y + 100.0,
        allow_nan=False, allow_infinity=False,
    ))
    max_z = draw(st.floats(
        min_value=min_z + min_extent, max_value=min_z + 100.0,
        allow_nan=False, allow_infinity=False,
    ))

    # Generate position (any value, clamping should handle it)
    pos_x = draw(_position_component)
    pos_y = draw(_position_component)
    pos_z = draw(_position_component)

    position = (pos_x, pos_y, pos_z)
    bbox_min = (min_x, min_y, min_z)
    bbox_max = (max_x, max_y, max_z)

    return position, bbox_min, bbox_max, margin


@st.composite
def inside_position_inputs(draw: st.DrawFn) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    float,
]:
    """Generate inputs where position is strictly inside the clamped bounds.

    Used to verify pass-through behavior for in-bounds positions.
    """
    margin = draw(_margin)

    # Generate bbox_min
    min_x = draw(_bbox_min_component)
    min_y = draw(_bbox_min_component)
    min_z = draw(_bbox_min_component)

    # Generate bbox_max with room for margin
    min_extent = 2 * margin + 0.1
    max_x = draw(st.floats(
        min_value=min_x + min_extent, max_value=min_x + 100.0,
        allow_nan=False, allow_infinity=False,
    ))
    max_y = draw(st.floats(
        min_value=min_y + min_extent, max_value=min_y + 100.0,
        allow_nan=False, allow_infinity=False,
    ))
    max_z = draw(st.floats(
        min_value=min_z + min_extent, max_value=min_z + 100.0,
        allow_nan=False, allow_infinity=False,
    ))

    # Generate position strictly within clamped bounds
    inner_min_x = min_x + margin
    inner_max_x = max_x - margin
    inner_min_y = min_y + margin
    inner_max_y = max_y - margin
    inner_min_z = min_z + margin
    inner_max_z = max_z - margin

    pos_x = draw(st.floats(
        min_value=inner_min_x, max_value=inner_max_x,
        allow_nan=False, allow_infinity=False,
    ))
    pos_y = draw(st.floats(
        min_value=inner_min_y, max_value=inner_max_y,
        allow_nan=False, allow_infinity=False,
    ))
    pos_z = draw(st.floats(
        min_value=inner_min_z, max_value=inner_max_z,
        allow_nan=False, allow_infinity=False,
    ))

    position = (pos_x, pos_y, pos_z)
    bbox_min = (min_x, min_y, min_z)
    bbox_max = (max_x, max_y, max_z)

    return position, bbox_min, bbox_max, margin


# ---------------------------------------------------------------------------
# Property 10: Position Clamping to Room Bounds
# ---------------------------------------------------------------------------


class TestPositionClampingProperty:
    """Property 10: Position Clamping to Room Bounds.

    **Validates: Requirements 4.4**

    For any 3D position and room shell bounding volume, the clamped position
    SHALL lie within the bounding volume minus a 0.05m margin on all axes.
    """

    @given(data=bounded_inputs())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_clamped_position_within_margin_bounds(
        self,
        data: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            float,
        ],
    ) -> None:
        """Clamped position lies within [bbox_min + margin, bbox_max - margin]."""
        position, bbox_min, bbox_max, margin = data

        result = clamp_to_bounds(position, bbox_min, bbox_max, margin)

        for i in range(3):
            lower = bbox_min[i] + margin
            upper = bbox_max[i] - margin
            assert lower <= result[i] <= upper, (
                f"Axis {i}: result {result[i]} not in "
                f"[{lower}, {upper}]\n"
                f"  position={position}, bbox_min={bbox_min}, "
                f"bbox_max={bbox_max}, margin={margin}"
            )

    @given(data=bounded_inputs())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_clamped_position_with_default_margin(
        self,
        data: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            float,
        ],
    ) -> None:
        """Using default margin=0.05 still satisfies bounds constraint."""
        position, bbox_min, bbox_max, _ = data
        default_margin = 0.05

        # Ensure the bbox is large enough for default margin
        for i in range(3):
            assume(bbox_max[i] - bbox_min[i] > 2 * default_margin + 0.01)

        result = clamp_to_bounds(position, bbox_min, bbox_max)

        for i in range(3):
            lower = bbox_min[i] + default_margin
            upper = bbox_max[i] - default_margin
            assert lower <= result[i] <= upper, (
                f"Axis {i}: result {result[i]} not in "
                f"[{lower}, {upper}] with default margin\n"
                f"  position={position}, bbox_min={bbox_min}, bbox_max={bbox_max}"
            )

    @given(data=inside_position_inputs())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_inside_position_passes_through_unchanged(
        self,
        data: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            float,
        ],
    ) -> None:
        """Position already inside bounds passes through unchanged."""
        position, bbox_min, bbox_max, margin = data

        result = clamp_to_bounds(position, bbox_min, bbox_max, margin)

        for i in range(3):
            assert result[i] == position[i], (
                f"Axis {i}: in-bounds position {position[i]} was modified "
                f"to {result[i]}\n"
                f"  bbox_min={bbox_min}, bbox_max={bbox_max}, margin={margin}"
            )
