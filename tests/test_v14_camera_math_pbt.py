"""Property-based tests for camera math utilities.

# Feature: photo-to-real-3d-world-v14

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

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.camera_math import clamp_to_bounds


# ---------------------------------------------------------------------------
# Strategies
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
