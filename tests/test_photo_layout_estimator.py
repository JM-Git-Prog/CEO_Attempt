"""Property-based tests for photo pipeline layout estimator.

# Feature: photo-to-playable-world

## Property 13: Back-Projection Satisfies Camera Model Inverse

**Validates: Requirements 7.3**

For any pixel (u,v) within image bounds, positive depth d, and valid camera
params, back-projecting then re-projecting yields original pixel within
±0.5px tolerance.

## Property 14: Physics Settle Convergence

**Validates: Requirements 7.4, 10.2**

For any set of objects with overlapping bounding boxes, after settle the
fallback path ensures all objects have y >= their half_height (not below
ground), and total displacement from ground is monotonically non-increasing
compared to initial conditions.
"""

from __future__ import annotations

import math

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.layout_estimator import (
    back_project,
    forward_project,
    _physics_settle_fallback,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random image sizes (100 to 2000 pixels per axis)
image_widths = st.integers(min_value=100, max_value=2000)
image_heights = st.integers(min_value=100, max_value=2000)

# Random FOV values (20 to 120 degrees) — avoids extreme tangent values
fov_values = st.floats(min_value=20.0, max_value=120.0, allow_nan=False, allow_infinity=False)

# Random positive depth (0.1 to 50 meters)
depth_values = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)

# Object dimensions for physics settle (0.05 to 3.0 meters per axis)
object_dim_values = st.floats(min_value=0.05, max_value=3.0, allow_nan=False, allow_infinity=False)


@st.composite
def pixel_within_bounds(draw: st.DrawFn, width: int, height: int) -> tuple[float, float]:
    """Generate a pixel coordinate strictly within image bounds.

    Avoids edges to prevent numerical issues with exact boundary projection.
    """
    u = draw(st.floats(min_value=1.0, max_value=float(width - 1), allow_nan=False, allow_infinity=False))
    v = draw(st.floats(min_value=1.0, max_value=float(height - 1), allow_nan=False, allow_infinity=False))
    return (u, v)


@st.composite
def back_projection_inputs(draw: st.DrawFn) -> dict:
    """Generate valid inputs for back-projection round-trip test.

    Returns a dict with:
      - pixel: (u, v) within image bounds
      - depth_m: positive depth
      - fov_v_deg: valid vertical FOV
      - image_size: (width, height)
    """
    w = draw(image_widths)
    h = draw(image_heights)
    fov = draw(fov_values)
    depth = draw(depth_values)

    # Generate pixel within bounds (with margin to avoid numerical edge issues)
    u = draw(st.floats(min_value=1.0, max_value=float(w - 1), allow_nan=False, allow_infinity=False))
    v = draw(st.floats(min_value=1.0, max_value=float(h - 1), allow_nan=False, allow_infinity=False))

    return {
        "pixel": (u, v),
        "depth_m": depth,
        "fov_v_deg": fov,
        "image_size": (w, h),
    }


@st.composite
def overlapping_objects(draw: st.DrawFn) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
]:
    """Generate a set of objects with positions above ground that need settling.

    Returns (positions, dimensions) where:
    - positions have y > 0 (floating above ground)
    - dimensions are reasonable object sizes
    """
    n_objects = draw(st.integers(min_value=1, max_value=8))

    positions = []
    dimensions = []

    for _ in range(n_objects):
        # x and z positions in a small area to encourage overlap
        x = draw(st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False))
        # y above ground (0.1 to 5.0 meters) — objects are floating
        y = draw(st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False))
        z = draw(st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False))
        positions.append((x, y, z))

        # Object dimensions
        w = draw(object_dim_values)
        h = draw(object_dim_values)
        d = draw(object_dim_values)
        dimensions.append((w, h, d))

    return (positions, dimensions)


# ---------------------------------------------------------------------------
# Property 13: Back-Projection Satisfies Camera Model Inverse
# ---------------------------------------------------------------------------


class TestBackProjectionCameraModelInverse:
    """Property 13: Back-Projection Satisfies Camera Model Inverse.

    **Validates: Requirements 7.3**

    For any pixel (u,v) within image bounds, positive depth d, and valid
    camera params, back-projecting then re-projecting yields original pixel
    within ±0.5px tolerance.
    """

    @given(inputs=back_projection_inputs())
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_back_project_then_forward_project_roundtrip(self, inputs: dict):
        """back_project → forward_project yields original pixel ±0.5px."""
        pixel = inputs["pixel"]
        depth_m = inputs["depth_m"]
        fov_v_deg = inputs["fov_v_deg"]
        image_size = inputs["image_size"]

        # Back-project pixel to 3D
        pos_3d = back_project(
            centroid_px=pixel,
            depth_m=depth_m,
            fov_v_deg=fov_v_deg,
            image_size=image_size,
        )

        # Forward-project 3D back to pixel
        reprojected = forward_project(
            position_3d=pos_3d,
            fov_v_deg=fov_v_deg,
            image_size=image_size,
        )

        # Check within ±0.5 pixel tolerance
        u_orig, v_orig = pixel
        u_reproj, v_reproj = reprojected

        u_err = abs(u_reproj - u_orig)
        v_err = abs(v_reproj - v_orig)

        assert u_err <= 0.5, (
            f"U-axis reprojection error {u_err:.6f}px exceeds ±0.5px tolerance. "
            f"Original pixel=({u_orig:.4f}, {v_orig:.4f}), "
            f"reprojected=({u_reproj:.4f}, {v_reproj:.4f}), "
            f"depth={depth_m:.4f}m, fov={fov_v_deg:.2f}°, "
            f"image_size={image_size}"
        )
        assert v_err <= 0.5, (
            f"V-axis reprojection error {v_err:.6f}px exceeds ±0.5px tolerance. "
            f"Original pixel=({u_orig:.4f}, {v_orig:.4f}), "
            f"reprojected=({u_reproj:.4f}, {v_reproj:.4f}), "
            f"depth={depth_m:.4f}m, fov={fov_v_deg:.2f}°, "
            f"image_size={image_size}"
        )

    @given(inputs=back_projection_inputs())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_back_project_depth_preserved(self, inputs: dict):
        """back_project produces a 3D point at the expected depth (z = -depth_m)."""
        pixel = inputs["pixel"]
        depth_m = inputs["depth_m"]
        fov_v_deg = inputs["fov_v_deg"]
        image_size = inputs["image_size"]

        pos_3d = back_project(
            centroid_px=pixel,
            depth_m=depth_m,
            fov_v_deg=fov_v_deg,
            image_size=image_size,
        )

        # z should equal -depth_m (camera looks along -Z)
        assert math.isclose(pos_3d[2], -depth_m, rel_tol=1e-9), (
            f"Z component should be -depth_m: got {pos_3d[2]}, expected {-depth_m}"
        )


# ---------------------------------------------------------------------------
# Property 14: Physics Settle Convergence (Fallback Path)
# ---------------------------------------------------------------------------


class TestPhysicsSettleConvergence:
    """Property 14: Physics Settle Convergence.

    **Validates: Requirements 7.4, 10.2**

    For any set of objects with positions above ground, after the fallback
    settle all objects have y >= their half_height (not below ground), and
    total ground penetration is zero (monotone non-increasing from any
    initial penetration).
    """

    @given(data=overlapping_objects())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_settled_objects_above_ground(
        self,
        data: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]],
    ):
        """After settle, all objects have y >= half_height (bottom at or above ground)."""
        positions, dimensions = data

        outcomes = _physics_settle_fallback(positions, dimensions)

        assert len(outcomes) == len(positions), (
            f"Expected {len(positions)} outcomes, got {len(outcomes)}"
        )

        for i, outcome in enumerate(outcomes):
            half_h = max(0.01, dimensions[i][1] / 2.0)
            final_y = outcome.position[1]

            assert final_y >= half_h, (
                f"Object {i} below ground after settle: y={final_y:.6f}m < "
                f"half_height={half_h:.6f}m. "
                f"Initial position={positions[i]}, dims={dimensions[i]}"
            )

    @given(data=overlapping_objects())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_settle_reduces_ground_penetration(
        self,
        data: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]],
    ):
        """After settle, total ground penetration is <= initial (monotone non-increasing).

        Ground penetration for an object = max(0, half_height - y_position).
        The settle should never increase total penetration.
        """
        positions, dimensions = data

        # Compute initial total ground penetration
        initial_penetration = 0.0
        for pos, dims in zip(positions, dimensions):
            half_h = max(0.01, dims[1] / 2.0)
            penetration = max(0.0, half_h - pos[1])
            initial_penetration += penetration

        outcomes = _physics_settle_fallback(positions, dimensions)

        # Compute final total ground penetration
        final_penetration = 0.0
        for i, outcome in enumerate(outcomes):
            half_h = max(0.01, dimensions[i][1] / 2.0)
            penetration = max(0.0, half_h - outcome.position[1])
            final_penetration += penetration

        assert final_penetration <= initial_penetration + 1e-9, (
            f"Settle increased ground penetration: "
            f"initial={initial_penetration:.6f}m, final={final_penetration:.6f}m. "
            f"Positions={positions}, dimensions={dimensions}"
        )

    @given(data=overlapping_objects())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_settle_preserves_horizontal_position(
        self,
        data: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]],
    ):
        """The fallback settle only modifies y-position (x, z unchanged)."""
        positions, dimensions = data

        outcomes = _physics_settle_fallback(positions, dimensions)

        for i, outcome in enumerate(outcomes):
            orig_x, _, orig_z = positions[i]
            final_x, _, final_z = outcome.position

            assert math.isclose(final_x, orig_x, abs_tol=1e-9), (
                f"Object {i} x-position changed: {orig_x} → {final_x}"
            )
            assert math.isclose(final_z, orig_z, abs_tol=1e-9), (
                f"Object {i} z-position changed: {orig_z} → {final_z}"
            )

    @given(data=overlapping_objects())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_settle_fallback_reports_settled(
        self,
        data: tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]],
    ):
        """Fallback settle always reports settled=True (by design)."""
        positions, dimensions = data

        outcomes = _physics_settle_fallback(positions, dimensions)

        for i, outcome in enumerate(outcomes):
            assert outcome.settled is True, (
                f"Object {i} reported unsettled in fallback path "
                f"(fallback should always report settled=True)"
            )
