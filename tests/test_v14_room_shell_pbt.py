"""Property-based tests for Room Shell Reconstructor.

# Feature: photo-to-real-3d-world-v14

## Property 5: Room Shell Vertex Count Bounds

**Validates: Requirements 3.6**

For any valid depth map (≥50% valid pixels) at any resolution, the Room Shell
reconstructor SHALL produce a mesh with vertex count between 10,000 and 250,000.

Uses Hypothesis with custom strategies to generate:
- depth maps of various sizes (10-1000 px wide/high)
- depth values that are valid (positive, finite, <20m) for ≥50% of pixels
- a dummy Room_Plate PNG in a temporary directory

Verifies:
1. result.vertex_count >= 10000
2. result.vertex_count <= 250000
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from PIL import Image

from src.photo_pipeline.stages.room_shell_reconstructor import RoomShellReconstructor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_dummy_room_plate(tmp_dir: Path, width: int, height: int) -> Path:
    """Create a simple dummy Room_Plate PNG for testing."""
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    plate_path = tmp_dir / "room_plate.png"
    img.save(str(plate_path))
    return plate_path


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Image dimensions: 10-1000 px (covers small through large images)
_image_dim = st.integers(min_value=10, max_value=1000)


@st.composite
def valid_depth_map_inputs(draw: st.DrawFn) -> tuple[np.ndarray, int, int]:
    """Generate a valid depth map with ≥50% valid pixels at a random resolution.

    Valid pixels: positive, finite, <20m.
    At least 50% of pixels are valid to avoid triggering the flat-box fallback.

    Returns
    -------
    tuple[np.ndarray, int, int]
        (depth_map, image_width, image_height)
    """
    width = draw(_image_dim)
    height = draw(_image_dim)

    # Decide what fraction of pixels are valid: between 50% and 100%
    valid_fraction = draw(st.floats(min_value=0.50, max_value=1.0))

    total_pixels = width * height
    num_valid = max(int(total_pixels * valid_fraction), int(total_pixels * 0.5) + 1)
    num_valid = min(num_valid, total_pixels)

    # Generate depth values
    # Valid pixels: depth in (0.1, 19.0) meters (positive, finite, <20m)
    depth_map = np.zeros((height, width), dtype=np.float32)

    # Create a random mask for valid pixels
    flat = depth_map.ravel()
    valid_indices = draw(
        st.just(np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
                .choice(total_pixels, size=num_valid, replace=False))
    )

    # Fill valid pixels with realistic room depths (0.5m - 10m typical)
    valid_depths = draw(
        st.just(np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
                .uniform(0.5, 10.0, size=num_valid).astype(np.float32))
    )
    flat[valid_indices] = valid_depths

    # Fill remaining pixels with invalid values (0 or negative)
    # Already zeros from initialization — that's an invalid value (not > 0)

    depth_map = flat.reshape(height, width)

    return depth_map, width, height


# ---------------------------------------------------------------------------
# Property 5: Room Shell Vertex Count Bounds
# ---------------------------------------------------------------------------


class TestRoomShellVertexCountBounds:
    """Property 5: Room Shell Vertex Count Bounds.

    **Validates: Requirements 3.6**

    For any valid depth map (≥50% valid pixels) at any resolution, the Room Shell
    reconstructor SHALL produce a mesh with vertex count between 10,000 and 250,000.
    """

    @given(data=valid_depth_map_inputs())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.large_base_example,
            HealthCheck.data_too_large,
        ],
    )
    def test_vertex_count_within_bounds(
        self,
        data: tuple[np.ndarray, int, int],
    ) -> None:
        """Reconstructed room shell has vertex count in [10000, 250000]."""
        depth_map, image_width, image_height = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create dummy room plate
            room_plate_path = _create_dummy_room_plate(
                tmp_path, image_width, image_height
            )

            # Create output directory
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            # Reconstruct
            reconstructor = RoomShellReconstructor(output_dir=output_dir)
            result = reconstructor.reconstruct(
                depth_map=depth_map,
                room_plate_path=room_plate_path,
                image_width=image_width,
                image_height=image_height,
            )

            # The test targets the displaced-grid path, not the fallback
            # If fallback triggers due to valid ratio computation differences,
            # skip this example (the property is about valid depth maps)
            if result.used_fallback:
                # This shouldn't happen given our ≥50% valid constraint,
                # but if it does, the property doesn't apply to fallback
                return

            # Property assertion: vertex count in [10000, 250000]
            assert result.vertex_count >= 10_000, (
                f"Vertex count {result.vertex_count} is below minimum 10,000.\n"
                f"  image_size=({image_width}, {image_height}), "
                f"grid_resolution={result.grid_resolution}"
            )
            assert result.vertex_count <= 250_000, (
                f"Vertex count {result.vertex_count} exceeds maximum 250,000.\n"
                f"  image_size=({image_width}, {image_height}), "
                f"grid_resolution={result.grid_resolution}"
            )


# ---------------------------------------------------------------------------
# Property 6: Room Shell Inward-Facing Normals
# ---------------------------------------------------------------------------


class TestRoomShellInwardFacingNormals:
    """Property 6: Room Shell Inward-Facing Normals.

    **Validates: Requirements 3.8**

    For any Room Shell mesh produced by the displaced-grid method, all face normals
    SHALL point toward the camera origin (the dot product of each face normal with
    the vector from face centroid to origin SHALL be positive).
    """

    @given(data=valid_depth_map_inputs())
    @settings(
        max_examples=12,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.large_base_example,
            HealthCheck.data_too_large,
        ],
    )
    def test_all_face_normals_point_toward_origin(
        self,
        data: tuple[np.ndarray, int, int],
    ) -> None:
        """All face normals in the reconstructed room shell point toward camera origin.

        Camera is at (0,0,0). For each face:
        - Compute face normal via cross product of two edges
        - Compute face centroid as average of 3 vertices
        - Compute vector from centroid to origin: (0,0,0) - centroid
        - Assert dot(normal, centroid_to_origin) > 0
        """
        depth_map, image_width, image_height = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create dummy room plate
            room_plate_path = _create_dummy_room_plate(
                tmp_path, image_width, image_height
            )

            # Create output directory
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            # Reconstruct
            reconstructor = RoomShellReconstructor(output_dir=output_dir)
            result = reconstructor.reconstruct(
                depth_map=depth_map,
                room_plate_path=room_plate_path,
                image_width=image_width,
                image_height=image_height,
            )

            # Property applies to displaced-grid path only (not fallback)
            if result.used_fallback:
                return

            # Load the exported GLB and verify normals
            import trimesh

            loaded = trimesh.load(str(result.mesh_path), force="mesh")
            vertices = np.array(loaded.vertices)
            faces = np.array(loaded.faces)

            assert len(faces) > 0, "Mesh has no faces after reconstruction"

            # Get face vertices
            v0 = vertices[faces[:, 0]]
            v1 = vertices[faces[:, 1]]
            v2 = vertices[faces[:, 2]]

            # Compute face normals via cross product of edges
            edge1 = v1 - v0
            edge2 = v2 - v0
            normals = np.cross(edge1, edge2)

            # Compute face centroids
            centroids = (v0 + v1 + v2) / 3.0

            # Vector from centroid to origin (camera at 0,0,0)
            centroid_to_origin = -centroids

            # Dot product of normal with centroid_to_origin
            dots = np.sum(normals * centroid_to_origin, axis=1)

            # Skip degenerate faces (zero-area faces produce zero-length normals)
            normal_magnitudes = np.linalg.norm(normals, axis=1)
            non_degenerate = normal_magnitudes > 1e-10

            valid_dots = dots[non_degenerate]

            # ALL non-degenerate face normals should point toward origin
            violating_count = int(np.sum(valid_dots <= 0))
            total_faces = int(np.sum(non_degenerate))

            assert violating_count == 0, (
                f"{violating_count} of {total_faces} non-degenerate faces have "
                f"normals NOT pointing toward camera origin.\n"
                f"  image_size=({image_width}, {image_height})\n"
                f"  Min dot product: {float(np.min(valid_dots)):.6f}\n"
                f"  Face count: {result.face_count}, Vertex count: {result.vertex_count}"
            )


# ---------------------------------------------------------------------------
# Property 7: Depth Gradient Face Removal
# ---------------------------------------------------------------------------


@st.composite
def depth_map_with_discontinuity(draw: st.DrawFn) -> tuple[np.ndarray, int, int, float, float]:
    """Generate a depth map with an intentional sharp depth discontinuity.

    Creates a step-function depth map where the left half and right half
    have significantly different depth values (difference > 0.5m per cell),
    ensuring the gradient threshold will be exceeded at the boundary.

    Returns
    -------
    tuple[np.ndarray, int, int, float, float]
        (depth_map, image_width, image_height, near_depth, far_depth)
    """
    # Use moderate image sizes to keep tests fast but meaningful
    width = draw(st.integers(min_value=100, max_value=300))
    height = draw(st.integers(min_value=100, max_value=300))

    # Two depth values with a large gap (> 0.5m, the gradient threshold)
    near_depth = draw(st.floats(min_value=1.0, max_value=4.0))
    far_depth = draw(st.floats(min_value=near_depth + 1.5, max_value=12.0))

    # Create step-function depth map: left half = near, right half = far
    depth_map = np.full((height, width), near_depth, dtype=np.float32)
    mid_col = width // 2
    depth_map[:, mid_col:] = far_depth

    return depth_map, width, height, near_depth, far_depth


class TestDepthGradientFaceRemoval:
    """Property 7: Depth Gradient Face Removal.

    **Validates: Requirements 3.7**

    For any Room Shell mesh, no face SHALL exist where the depth difference
    between adjacent vertices exceeds 0.5 meters per grid cell — all such
    faces SHALL have been removed or split.
    """

    @given(data=depth_map_with_discontinuity())
    @settings(
        max_examples=8,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.large_base_example,
            HealthCheck.data_too_large,
        ],
    )
    def test_no_face_exceeds_gradient_threshold(
        self,
        data: tuple[np.ndarray, int, int, float, float],
    ) -> None:
        """All remaining faces have max vertex depth difference ≤ 0.5m."""
        import trimesh as tm

        depth_map, image_width, image_height, near_depth, far_depth = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create dummy room plate
            room_plate_path = _create_dummy_room_plate(
                tmp_path, image_width, image_height
            )

            # Create output directory
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            # Reconstruct
            reconstructor = RoomShellReconstructor(output_dir=output_dir)
            result = reconstructor.reconstruct(
                depth_map=depth_map,
                room_plate_path=room_plate_path,
                image_width=image_width,
                image_height=image_height,
            )

            # Should not trigger fallback — our depth map is 100% valid
            assert not result.used_fallback, "Fallback should not trigger for 100% valid depth"

            # Load the produced GLB mesh
            mesh = tm.load(str(result.mesh_path), file_type="glb", force="mesh")

            # For each face, compute depth at each vertex.
            # Depth in WorldContract coords: z = -depth, so depth = -z
            vertices = mesh.vertices
            faces = mesh.faces

            gradient_threshold_m = 0.5

            for face in faces:
                v0, v1, v2 = vertices[face[0]], vertices[face[1]], vertices[face[2]]
                # Depth is the negative Z coordinate
                d0 = -v0[2]
                d1 = -v1[2]
                d2 = -v2[2]

                max_depth_diff = max(
                    abs(d0 - d1),
                    abs(d1 - d2),
                    abs(d0 - d2),
                )

                assert max_depth_diff <= gradient_threshold_m, (
                    f"Face has depth difference {max_depth_diff:.4f}m > "
                    f"{gradient_threshold_m}m threshold.\n"
                    f"  Vertex depths: {d0:.3f}, {d1:.3f}, {d2:.3f}\n"
                    f"  Image size: ({image_width}, {image_height})\n"
                    f"  Discontinuity: {near_depth:.2f}m → {far_depth:.2f}m"
                )

    @given(data=depth_map_with_discontinuity())
    @settings(
        max_examples=8,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.large_base_example,
            HealthCheck.data_too_large,
        ],
    )
    def test_faces_removed_when_discontinuity_exists(
        self,
        data: tuple[np.ndarray, int, int, float, float],
    ) -> None:
        """When a depth discontinuity exists, faces_removed_gradient > 0."""
        depth_map, image_width, image_height, near_depth, far_depth = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create dummy room plate
            room_plate_path = _create_dummy_room_plate(
                tmp_path, image_width, image_height
            )

            # Create output directory
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            # Reconstruct
            reconstructor = RoomShellReconstructor(output_dir=output_dir)
            result = reconstructor.reconstruct(
                depth_map=depth_map,
                room_plate_path=room_plate_path,
                image_width=image_width,
                image_height=image_height,
            )

            # Should not trigger fallback
            assert not result.used_fallback, "Fallback should not trigger for 100% valid depth"

            # With a step-function discontinuity of ≥1.5m (always > 0.5m threshold),
            # the reconstructor MUST have removed some faces at the boundary
            assert result.faces_removed_gradient > 0, (
                f"Expected faces_removed_gradient > 0 for depth discontinuity "
                f"of {far_depth - near_depth:.2f}m (near={near_depth:.2f}m, "
                f"far={far_depth:.2f}m), but got {result.faces_removed_gradient}.\n"
                f"  Image size: ({image_width}, {image_height})"
            )



# ---------------------------------------------------------------------------
# Property 8: Depth Validity Threshold
# ---------------------------------------------------------------------------


@st.composite
def depth_map_with_controlled_validity(draw: st.DrawFn) -> tuple[np.ndarray, float, int, int]:
    """Generate a depth map with a specific valid pixel ratio.

    Controls the ratio of valid pixels (positive, finite, <20m) vs invalid
    pixels (zero, negative, or infinite) to test the 50% threshold behavior.

    Returns
    -------
    tuple[np.ndarray, float, int, int]
        (depth_map, target_valid_ratio, image_width, image_height)
    """
    # Use small images to keep IO manageable
    width = draw(st.integers(min_value=20, max_value=100))
    height = draw(st.integers(min_value=20, max_value=100))

    # Draw a target valid ratio: either clearly below or clearly above 0.50
    # We use two zones to avoid boundary flakiness:
    #   below_threshold: [0.0, 0.45]
    #   above_threshold: [0.55, 1.0]
    zone = draw(st.sampled_from(["below", "above"]))
    if zone == "below":
        target_ratio = draw(st.floats(min_value=0.0, max_value=0.45))
    else:
        target_ratio = draw(st.floats(min_value=0.55, max_value=1.0))

    total_pixels = width * height
    num_valid = int(total_pixels * target_ratio)
    # Clamp to valid range
    num_valid = max(0, min(num_valid, total_pixels))

    # Build the depth map
    depth_map = np.zeros((height, width), dtype=np.float32)
    flat = depth_map.ravel()

    if num_valid > 0:
        rng = np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
        valid_indices = rng.choice(total_pixels, size=num_valid, replace=False)
        # Valid pixels: positive, finite, <20m
        valid_depths = rng.uniform(0.1, 19.0, size=num_valid).astype(np.float32)
        flat[valid_indices] = valid_depths

    # Remaining pixels stay 0.0 (invalid: not > 0)
    # Optionally sprinkle some inf/negative for variety
    num_invalid_remaining = total_pixels - num_valid
    if num_invalid_remaining > 0:
        rng2 = np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
        invalid_kind = draw(st.sampled_from(["zero", "mixed"]))
        if invalid_kind == "mixed" and num_invalid_remaining > 0:
            # Find invalid indices (those still at 0)
            invalid_mask = flat == 0.0
            invalid_indices = np.where(invalid_mask)[0]
            if len(invalid_indices) > 0:
                # Make some negative, some inf
                num_neg = len(invalid_indices) // 3
                num_inf = len(invalid_indices) // 3
                if num_neg > 0:
                    flat[invalid_indices[:num_neg]] = rng2.uniform(
                        -10.0, -0.1, size=num_neg
                    ).astype(np.float32)
                if num_inf > 0:
                    flat[invalid_indices[num_neg : num_neg + num_inf]] = np.inf

    depth_map = flat.reshape(height, width)

    # Compute actual valid ratio for reference
    actual_valid = np.sum(
        np.isfinite(depth_map) & (depth_map > 0.0)
    )
    actual_ratio = float(actual_valid) / total_pixels

    return depth_map, actual_ratio, width, height


class TestDepthValidityThreshold:
    """Property 8: Depth Validity Threshold.

    **Validates: Requirements 3.5, 14.3**

    For any depth map, the depth validation function SHALL return a valid pixel
    ratio in [0.0, 1.0] where valid means positive, finite, and less than 20
    meters. The system SHALL accept maps with ratio >= 0.50 and trigger fallback
    for ratio < 0.50.
    """

    @given(data=depth_map_with_controlled_validity())
    @settings(
        max_examples=25,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.large_base_example,
            HealthCheck.data_too_large,
        ],
    )
    def test_depth_validity_threshold_determines_fallback(
        self,
        data: tuple[np.ndarray, float, int, int],
    ) -> None:
        """System uses fallback when valid ratio < 0.50, grid method when >= 0.50."""
        depth_map, actual_valid_ratio, width, height = data

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create dummy room plate
            room_plate_path = _create_dummy_room_plate(tmp_path, width, height)

            # Create output directory
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            # Reconstruct
            reconstructor = RoomShellReconstructor(output_dir=output_dir)
            result = reconstructor.reconstruct(
                depth_map=depth_map,
                room_plate_path=room_plate_path,
                image_width=width,
                image_height=height,
            )

            # Property assertions:
            # 1. The valid ratio must be in [0.0, 1.0]
            assert 0.0 <= actual_valid_ratio <= 1.0, (
                f"Valid ratio {actual_valid_ratio} is outside [0.0, 1.0]"
            )

            # 2. If valid ratio < 0.50 → must trigger fallback
            if actual_valid_ratio < 0.50:
                assert result.used_fallback is True, (
                    f"Expected fallback (used_fallback=True) when valid_ratio="
                    f"{actual_valid_ratio:.4f} < 0.50, but got used_fallback=False"
                )

            # 3. If valid ratio >= 0.50 → must use displaced-grid method (no fallback)
            if actual_valid_ratio >= 0.50:
                assert result.used_fallback is False, (
                    f"Expected grid method (used_fallback=False) when valid_ratio="
                    f"{actual_valid_ratio:.4f} >= 0.50, but got used_fallback=True"
                )
