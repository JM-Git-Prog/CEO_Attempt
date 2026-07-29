"""Property-based tests for photo pipeline object generator.

# Feature: photo-to-playable-world

## Property 6: Mesh Validation Correctness

**Validates: Requirements 4.6**

For any mesh, the validation function SHALL return True if and only if the mesh
has at least 4 faces, at least 4 vertices, and the ratio of zero-area faces to
total faces does not exceed 0.05.

## Property 7: Placeholder Geometry Selection by Aspect Ratio

**Validates: Requirements 4.4**

For any Object_PNG bounding box with dimensions (width, height), the placeholder
geometry SHALL be deterministically selected based on aspect ratio (box for
near-square, cylinder for tall/narrow, sphere for small uniform objects) and
textured with the average color extracted from the non-transparent pixels.

Uses Hypothesis with numpy strategies.
"""

from __future__ import annotations

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.object_generator import (
    validate_mesh,
    select_placeholder_type,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def valid_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes that should pass validation.

    Creates meshes with >= 4 faces, >= 4 vertices, and zero-area face
    ratio <= 0.05.
    """
    # Use trimesh primitives which guarantee valid geometry
    shape_type = draw(st.sampled_from(["box", "sphere", "cylinder"]))

    if shape_type == "box":
        extents = [
            draw(st.floats(min_value=0.1, max_value=10.0)) for _ in range(3)
        ]
        mesh = trimesh.creation.box(extents=extents)
    elif shape_type == "sphere":
        radius = draw(st.floats(min_value=0.1, max_value=5.0))
        subdivisions = draw(st.integers(min_value=2, max_value=4))
        mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    else:  # cylinder
        radius = draw(st.floats(min_value=0.1, max_value=5.0))
        height = draw(st.floats(min_value=0.1, max_value=10.0))
        mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=8)

    return mesh


@st.composite
def meshes_with_few_faces(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes with fewer than 4 faces (should fail validation).

    Creates degenerate meshes with 1-3 faces.
    """
    num_faces = draw(st.integers(min_value=1, max_value=3))

    # Build a mesh manually with the specified number of triangular faces
    # We need at least num_faces + 2 vertices for num_faces triangles
    vertices = []
    faces = []

    # Create a fan of triangles from a central vertex
    vertices.append([0.0, 0.0, 0.0])
    for i in range(num_faces + 1):
        angle = 2.0 * np.pi * i / (num_faces + 1)
        vertices.append([np.cos(angle), np.sin(angle), 0.0])

    for i in range(num_faces):
        faces.append([0, i + 1, (i + 1) % (num_faces + 1) + 1])

    mesh = trimesh.Trimesh(
        vertices=np.array(vertices, dtype=np.float64),
        faces=np.array(faces, dtype=np.int64),
    )
    return mesh


@st.composite
def meshes_with_few_vertices(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes with fewer than 4 vertices (should fail validation).

    Creates a single triangle (3 vertices, 1 face).
    """
    # A single triangle has exactly 3 vertices and 1 face
    scale = draw(st.floats(min_value=0.1, max_value=10.0))
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [scale, 0.0, 0.0],
        [0.0, scale, 0.0],
    ], dtype=np.float64)
    faces = np.array([[0, 1, 2]], dtype=np.int64)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    return mesh


@st.composite
def meshes_with_high_zero_area_ratio(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes where > 5% of faces have zero area.

    Takes a valid mesh and collapses enough faces to exceed the 5% threshold.
    """
    # Start with a box (12 faces)
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))

    num_faces = len(mesh.faces)
    # We need to make more than 5% of faces zero-area
    # For a box with 12 faces, we need > 0.6 faces -> at least 1 face
    # Let's collapse enough faces to guarantee > 5%
    num_to_collapse = max(1, int(np.ceil(num_faces * 0.06)))

    # Collapse faces by setting two vertices of the face to the same point
    vertices = mesh.vertices.copy()
    for i in range(num_to_collapse):
        face = mesh.faces[i]
        # Collapse by moving vertex 1 to vertex 0 position
        vertices[face[1]] = vertices[face[0]]
        vertices[face[2]] = vertices[face[0]]

    mesh = trimesh.Trimesh(vertices=vertices, faces=mesh.faces.copy())
    return mesh


@st.composite
def bounding_box_dimensions(draw: st.DrawFn):
    """Generate random bounding box dimensions (width, height, area_px).

    Returns (width, height, area_px) with positive values.
    """
    width = draw(st.integers(min_value=1, max_value=4000))
    height = draw(st.integers(min_value=1, max_value=4000))
    # area_px can be any positive value up to width * height
    max_area = width * height
    area_px = draw(st.integers(min_value=1, max_value=max(1, max_area)))
    return (width, height, area_px)


# ---------------------------------------------------------------------------
# Property 6: Mesh Validation Correctness
# ---------------------------------------------------------------------------


class TestMeshValidationCorrectness:
    """Property 6: Mesh Validation Correctness.

    **Validates: Requirements 4.6**

    For any mesh, validation returns True iff faces >= 4, vertices >= 4,
    and zero-area face ratio <= 0.05.
    """

    @given(mesh=valid_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_valid_meshes_pass_validation(self, mesh: trimesh.Trimesh):
        """Meshes with >= 4 faces, >= 4 vertices, and low zero-area ratio pass."""
        # Precondition: confirm this mesh actually meets the criteria
        assume(len(mesh.faces) >= 4)
        assume(len(mesh.vertices) >= 4)

        areas = mesh.area_faces
        zero_area_ratio = np.count_nonzero(areas < 1e-10) / len(areas)
        assume(zero_area_ratio <= 0.05)

        assert validate_mesh(mesh) is True, (
            f"Valid mesh rejected: {len(mesh.faces)} faces, "
            f"{len(mesh.vertices)} vertices, "
            f"zero-area ratio={zero_area_ratio:.4f}"
        )

    @given(mesh=meshes_with_few_faces())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_meshes_with_fewer_than_4_faces_fail(self, mesh: trimesh.Trimesh):
        """Meshes with < 4 faces are rejected."""
        assume(len(mesh.faces) < 4)

        assert validate_mesh(mesh) is False, (
            f"Mesh with {len(mesh.faces)} faces should be rejected"
        )

    @given(mesh=meshes_with_few_vertices())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_meshes_with_fewer_than_4_vertices_fail(self, mesh: trimesh.Trimesh):
        """Meshes with < 4 vertices are rejected."""
        assume(len(mesh.vertices) < 4)

        assert validate_mesh(mesh) is False, (
            f"Mesh with {len(mesh.vertices)} vertices should be rejected"
        )

    @given(mesh=meshes_with_high_zero_area_ratio())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_meshes_with_high_zero_area_ratio_fail(self, mesh: trimesh.Trimesh):
        """Meshes with > 5% zero-area faces are rejected."""
        areas = mesh.area_faces
        if len(areas) == 0:
            return  # skip degenerate case
        zero_area_ratio = np.count_nonzero(areas < 1e-10) / len(areas)

        # Only test when the ratio is clearly above threshold
        assume(zero_area_ratio > 0.05)
        # Also ensure face/vertex counts meet thresholds
        # (otherwise rejection could be for a different reason)
        assume(len(mesh.faces) >= 4)
        assume(len(mesh.vertices) >= 4)

        assert validate_mesh(mesh) is False, (
            f"Mesh with zero-area ratio {zero_area_ratio:.4f} should be rejected"
        )

    @given(
        face_count=st.integers(min_value=4, max_value=500),
        vertex_count=st.integers(min_value=4, max_value=500),
        zero_area_pct=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_validation_biconditional(
        self, face_count: int, vertex_count: int, zero_area_pct: float
    ):
        """validate_mesh returns True iff all three conditions are met.

        Constructs a mesh with controlled properties and verifies the
        biconditional: True iff faces>=4 AND vertices>=4 AND zero_area_ratio<=0.05.
        """
        # Build a mesh with controlled face and vertex count
        # Use an icosphere and truncate/expand as needed
        mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)

        # Trim faces if needed
        if face_count < len(mesh.faces):
            mesh = trimesh.Trimesh(
                vertices=mesh.vertices,
                faces=mesh.faces[:face_count],
            )

        # Ensure we have the right number of faces after construction
        actual_face_count = len(mesh.faces)
        actual_vertex_count = len(mesh.vertices)

        # Skip if mesh construction resulted in different than intended
        # (trimesh may merge/remove unused vertices)
        assume(actual_face_count >= 4)
        assume(actual_vertex_count >= 4)

        # Now introduce zero-area faces according to zero_area_pct
        num_zero_area = int(round(zero_area_pct * actual_face_count))
        num_zero_area = min(num_zero_area, actual_face_count)

        vertices = mesh.vertices.copy()
        faces = mesh.faces.copy()

        for i in range(num_zero_area):
            # Collapse face by duplicating vertex positions
            face = faces[i]
            vertices[face[1]] = vertices[face[0]]
            vertices[face[2]] = vertices[face[0]]

        test_mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

        # Compute actual properties
        actual_faces = len(test_mesh.faces)
        actual_verts = len(test_mesh.vertices)
        areas = test_mesh.area_faces
        actual_zero_ratio = (
            np.count_nonzero(areas < 1e-10) / len(areas) if len(areas) > 0 else 1.0
        )

        # Expected result
        should_pass = (
            actual_faces >= 4
            and actual_verts >= 4
            and actual_zero_ratio <= 0.05
        )

        result = validate_mesh(test_mesh)
        assert result == should_pass, (
            f"Expected {should_pass}, got {result}: "
            f"faces={actual_faces}, vertices={actual_verts}, "
            f"zero_area_ratio={actual_zero_ratio:.4f}"
        )


# ---------------------------------------------------------------------------
# Property 7: Placeholder Geometry Selection by Aspect Ratio
# ---------------------------------------------------------------------------


class TestPlaceholderGeometrySelection:
    """Property 7: Placeholder Geometry Selection by Aspect Ratio.

    **Validates: Requirements 4.4**

    For any bounding box dimensions, placeholder type is deterministically
    selected by aspect ratio rules:
    - area_px < 1000 → sphere
    - 0.8 <= width/height <= 1.2 → box
    - width/height < 0.5 → cylinder
    - width/height > 2.0 → box
    - default → box
    """

    @given(
        width=st.integers(min_value=1, max_value=4000),
        height=st.integers(min_value=1, max_value=4000),
        area_px=st.integers(min_value=1, max_value=999),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_small_area_returns_sphere(
        self, width: int, height: int, area_px: int
    ):
        """Objects with area < 1000 pixels always get sphere."""
        assume(area_px < 1000)

        result = select_placeholder_type(width, height, area_px)
        assert result == "sphere", (
            f"Expected sphere for area_px={area_px}, got {result}"
        )

    @given(
        width=st.integers(min_value=1, max_value=4000),
        height=st.integers(min_value=1, max_value=4000),
        area_px=st.integers(min_value=1000, max_value=16000000),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_near_square_returns_box(
        self, width: int, height: int, area_px: int
    ):
        """Near-square objects (0.8 <= aspect <= 1.2) with area >= 1000 get box."""
        assume(height > 0)
        aspect = width / height
        assume(0.8 <= aspect <= 1.2)
        assume(area_px >= 1000)

        result = select_placeholder_type(width, height, area_px)
        assert result == "box", (
            f"Expected box for aspect={aspect:.3f}, got {result}"
        )

    @given(
        height=st.integers(min_value=3, max_value=4000),
        area_px=st.integers(min_value=1000, max_value=16000000),
        data=st.data(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_tall_narrow_returns_cylinder(
        self, height: int, area_px: int, data
    ):
        """Tall/narrow objects (aspect < 0.5) with area >= 1000 get cylinder."""
        # Generate width directly to satisfy aspect < 0.5 constraint
        max_width = max(1, int(height * 0.49))
        width = data.draw(st.integers(min_value=1, max_value=max_width))
        aspect = width / height

        result = select_placeholder_type(width, height, area_px)
        assert result == "cylinder", (
            f"Expected cylinder for aspect={aspect:.3f}, got {result}"
        )

    @given(
        width=st.integers(min_value=1, max_value=4000),
        height=st.integers(min_value=1, max_value=4000),
        area_px=st.integers(min_value=1000, max_value=16000000),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_wide_flat_returns_box(
        self, width: int, height: int, area_px: int
    ):
        """Wide/flat objects (aspect > 2.0) with area >= 1000 get box."""
        assume(height > 0)
        aspect = width / height
        assume(aspect > 2.0)
        assume(area_px >= 1000)

        result = select_placeholder_type(width, height, area_px)
        assert result == "box", (
            f"Expected box for aspect={aspect:.3f}, got {result}"
        )

    @given(data=bounding_box_dimensions())
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_deterministic_selection(self, data: tuple[int, int, int]):
        """Calling select_placeholder_type twice with same inputs gives same result."""
        width, height, area_px = data

        result1 = select_placeholder_type(width, height, area_px)
        result2 = select_placeholder_type(width, height, area_px)

        assert result1 == result2, (
            f"Non-deterministic: first={result1}, second={result2} "
            f"for width={width}, height={height}, area={area_px}"
        )

    @given(data=bounding_box_dimensions())
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_result_is_valid_type(self, data: tuple[int, int, int]):
        """Result is always one of 'box', 'cylinder', or 'sphere'."""
        width, height, area_px = data

        result = select_placeholder_type(width, height, area_px)

        assert result in ("box", "cylinder", "sphere"), (
            f"Invalid result '{result}' for width={width}, "
            f"height={height}, area={area_px}"
        )

    @given(data=bounding_box_dimensions())
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_selection_matches_documented_rules(self, data: tuple[int, int, int]):
        """Comprehensive check: result matches the documented selection rules."""
        width, height, area_px = data

        result = select_placeholder_type(width, height, area_px)

        # Determine expected result according to documented rules
        if area_px < 1000:
            expected = "sphere"
        elif height <= 0:
            expected = "box"
        else:
            aspect = width / height
            if 0.8 <= aspect <= 1.2:
                expected = "box"
            elif aspect < 0.5:
                expected = "cylinder"
            elif aspect > 2.0:
                expected = "box"
            else:
                expected = "box"

        assert result == expected, (
            f"Expected {expected}, got {result} for "
            f"width={width}, height={height}, area={area_px}"
        )
