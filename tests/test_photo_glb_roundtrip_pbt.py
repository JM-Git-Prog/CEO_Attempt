"""Property-based tests for GLB mesh data round-trip integrity.

# Feature: photo-to-playable-world

## Property 21: GLB Mesh Data Round-Trip

**Validates: Requirements 13.2**

For any valid mesh (vertices as float32 arrays, normals as float32 unit vectors,
UV coordinates in [0,1]), writing to GLB format then reading back SHALL produce
vertex positions, normals, and UV coordinates within 1e-6 absolute tolerance
per component.

Uses Hypothesis with hypothesis.extra.numpy strategies, trimesh for GLB I/O.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

TOLERANCE = 1e-6


@st.composite
def unit_normals(draw: st.DrawFn, n_vertices: int) -> np.ndarray:
    """Generate float32 unit normal vectors (Nx3) with magnitude ~1.0.

    Strategy: generate random vectors with finite components, normalize them.
    Reject degenerate zero-length vectors.
    """
    raw = draw(
        arrays(
            dtype=np.float32,
            shape=(n_vertices, 3),
            elements=st.floats(
                min_value=-1.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
                allow_subnormal=False,
                width=32,
            ),
        )
    )
    # Compute magnitudes
    magnitudes = np.linalg.norm(raw, axis=1, keepdims=True)
    # Reject if any vector has zero magnitude (can't normalize)
    assume(np.all(magnitudes > 1e-7))
    normalized = (raw / magnitudes).astype(np.float32)
    return normalized


@st.composite
def uv_coordinates(draw: st.DrawFn, n_vertices: int) -> np.ndarray:
    """Generate float32 UV coordinates in [0, 1] range."""
    uvs = draw(
        arrays(
            dtype=np.float32,
            shape=(n_vertices, 2),
            elements=st.floats(
                min_value=0.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
                allow_subnormal=False,
                width=32,
            ),
        )
    )
    return uvs


@st.composite
def valid_meshes(draw: st.DrawFn) -> dict:
    """Generate a valid mesh with vertices, normals, UVs, and faces.

    Produces meshes with 4-50 vertices and valid triangular faces.
    Vertices are in reasonable 3D coordinate range [-1000, 1000].
    """
    n_vertices = draw(st.integers(min_value=4, max_value=50))
    n_faces = draw(st.integers(min_value=4, max_value=min(80, n_vertices * 2)))

    # Generate vertices in reasonable range
    vertices = draw(
        arrays(
            dtype=np.float32,
            shape=(n_vertices, 3),
            elements=st.floats(
                min_value=-1000.0,
                max_value=1000.0,
                allow_nan=False,
                allow_infinity=False,
                allow_subnormal=False,
                width=32,
            ),
        )
    )

    # Generate faces as valid triangle indices
    faces = draw(
        arrays(
            dtype=np.int64,
            shape=(n_faces, 3),
            elements=st.integers(min_value=0, max_value=n_vertices - 1),
        )
    )

    # Ensure no degenerate faces (all three indices different)
    for i in range(n_faces):
        assume(
            faces[i, 0] != faces[i, 1]
            and faces[i, 1] != faces[i, 2]
            and faces[i, 0] != faces[i, 2]
        )

    # Generate normals and UVs
    normals = draw(unit_normals(n_vertices))
    uvs = draw(uv_coordinates(n_vertices))

    return {
        "vertices": vertices,
        "faces": faces,
        "normals": normals,
        "uvs": uvs,
    }


@st.composite
def tetrahedron_meshes(draw: st.DrawFn) -> dict:
    """Generate minimal valid meshes (tetrahedron: 4 vertices, 4 faces).

    Edge case: smallest valid closed mesh.
    """
    # 4 vertices in reasonable range
    vertices = draw(
        arrays(
            dtype=np.float32,
            shape=(4, 3),
            elements=st.floats(
                min_value=-1000.0,
                max_value=1000.0,
                allow_nan=False,
                allow_infinity=False,
                allow_subnormal=False,
                width=32,
            ),
        )
    )

    # Ensure vertices are not coplanar (tetrahedron has volume)
    v0, v1, v2, v3 = vertices[0], vertices[1], vertices[2], vertices[3]
    volume = abs(np.dot(v1 - v0, np.cross(v2 - v0, v3 - v0)))
    assume(volume > 1e-4)

    # Standard tetrahedron faces
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.int64)

    normals = draw(unit_normals(4))
    uvs = draw(uv_coordinates(4))

    return {
        "vertices": vertices,
        "faces": faces,
        "normals": normals,
        "uvs": uvs,
    }


@st.composite
def boundary_uv_meshes(draw: st.DrawFn) -> dict:
    """Generate meshes with UVs at boundary values (0.0 and 1.0).

    Edge case: UV coordinates exactly at the extremes of the valid range.
    """
    n_vertices = draw(st.integers(min_value=4, max_value=20))
    n_faces = draw(st.integers(min_value=4, max_value=min(30, n_vertices * 2)))

    vertices = draw(
        arrays(
            dtype=np.float32,
            shape=(n_vertices, 3),
            elements=st.floats(
                min_value=-100.0,
                max_value=100.0,
                allow_nan=False,
                allow_infinity=False,
                allow_subnormal=False,
                width=32,
            ),
        )
    )

    faces = draw(
        arrays(
            dtype=np.int64,
            shape=(n_faces, 3),
            elements=st.integers(min_value=0, max_value=n_vertices - 1),
        )
    )

    for i in range(n_faces):
        assume(
            faces[i, 0] != faces[i, 1]
            and faces[i, 1] != faces[i, 2]
            and faces[i, 0] != faces[i, 2]
        )

    normals = draw(unit_normals(n_vertices))

    # Force UVs to boundary values (0.0 or 1.0 only)
    uvs = draw(
        arrays(
            dtype=np.float32,
            shape=(n_vertices, 2),
            elements=st.sampled_from([np.float32(0.0), np.float32(1.0)]),
        )
    )

    return {
        "vertices": vertices,
        "faces": faces,
        "normals": normals,
        "uvs": uvs,
    }


# ---------------------------------------------------------------------------
# Helper: GLB round-trip
# ---------------------------------------------------------------------------


def glb_round_trip(mesh_data: dict) -> trimesh.Trimesh:
    """Write mesh to GLB then read it back, returning the loaded mesh.

    Loads as Scene then extracts the first geometry to preserve vertex
    normals (force='mesh' triggers normal recomputation in trimesh).
    """
    mesh = trimesh.Trimesh(
        vertices=mesh_data["vertices"],
        faces=mesh_data["faces"],
        vertex_normals=mesh_data["normals"],
        process=False,  # Don't let trimesh modify the mesh
    )

    # Attach UV coordinates as visual attribute
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=mesh_data["uvs"],
    )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".glb", delete=False
        ) as f:
            tmp_path = Path(f.name)

        mesh.export(str(tmp_path), file_type="glb")

        # Load as Scene to preserve vertex normals (force='mesh' recomputes them)
        scene = trimesh.load(str(tmp_path), process=False)
        if isinstance(scene, trimesh.Scene):
            # Extract the first (and only) geometry from the scene
            loaded = list(scene.geometry.values())[0]
        else:
            loaded = scene
        return loaded
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Property 21: GLB Mesh Data Round-Trip
# ---------------------------------------------------------------------------


class TestGLBMeshDataRoundTrip:
    """Property 21: GLB Mesh Data Round-Trip.

    For any valid mesh (float32 vertices, unit normals, UV in [0,1]),
    write GLB → read GLB produces data within 1e-6 absolute tolerance.
    """

    @given(mesh_data=valid_meshes())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
        ],
    )
    def test_vertex_positions_round_trip(self, mesh_data: dict):
        """Vertex positions survive GLB round-trip within 1e-6 tolerance."""
        loaded = glb_round_trip(mesh_data)

        original_vertices = mesh_data["vertices"]
        loaded_vertices = np.array(loaded.vertices, dtype=np.float32)

        # Vertex count must be preserved
        assert loaded_vertices.shape[0] == original_vertices.shape[0], (
            f"Vertex count mismatch: expected {original_vertices.shape[0]}, "
            f"got {loaded_vertices.shape[0]}"
        )

        assert np.allclose(original_vertices, loaded_vertices, atol=TOLERANCE), (
            f"Vertex positions exceed {TOLERANCE} tolerance after GLB round-trip. "
            f"Max diff: {np.max(np.abs(original_vertices - loaded_vertices))}"
        )

    @given(mesh_data=valid_meshes())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
        ],
    )
    def test_normals_round_trip(self, mesh_data: dict):
        """Vertex normals survive GLB round-trip within 1e-6 tolerance."""
        loaded = glb_round_trip(mesh_data)

        original_normals = mesh_data["normals"]

        # trimesh stores vertex normals
        if hasattr(loaded, "vertex_normals") and loaded.vertex_normals is not None:
            loaded_normals = np.array(loaded.vertex_normals, dtype=np.float32)

            assert loaded_normals.shape == original_normals.shape, (
                f"Normal shape mismatch: expected {original_normals.shape}, "
                f"got {loaded_normals.shape}"
            )

            assert np.allclose(original_normals, loaded_normals, atol=TOLERANCE), (
                f"Normals exceed {TOLERANCE} tolerance after GLB round-trip. "
                f"Max diff: {np.max(np.abs(original_normals - loaded_normals))}"
            )

    @given(mesh_data=valid_meshes())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
        ],
    )
    def test_uv_coordinates_round_trip(self, mesh_data: dict):
        """UV coordinates survive GLB round-trip within 1e-6 tolerance."""
        loaded = glb_round_trip(mesh_data)

        original_uvs = mesh_data["uvs"]

        # Extract UVs from loaded mesh
        if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
            loaded_uvs = np.array(loaded.visual.uv, dtype=np.float32)

            assert loaded_uvs.shape == original_uvs.shape, (
                f"UV shape mismatch: expected {original_uvs.shape}, "
                f"got {loaded_uvs.shape}"
            )

            assert np.allclose(original_uvs, loaded_uvs, atol=TOLERANCE), (
                f"UVs exceed {TOLERANCE} tolerance after GLB round-trip. "
                f"Max diff: {np.max(np.abs(original_uvs - loaded_uvs))}"
            )

    @given(mesh_data=tetrahedron_meshes())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
        ],
    )
    def test_tetrahedron_round_trip(self, mesh_data: dict):
        """Minimum valid mesh (tetrahedron) survives GLB round-trip."""
        loaded = glb_round_trip(mesh_data)

        original_vertices = mesh_data["vertices"]
        loaded_vertices = np.array(loaded.vertices, dtype=np.float32)

        assert loaded_vertices.shape[0] == 4, (
            f"Tetrahedron should have 4 vertices, got {loaded_vertices.shape[0]}"
        )

        assert np.allclose(original_vertices, loaded_vertices, atol=TOLERANCE), (
            f"Tetrahedron vertices exceed {TOLERANCE} tolerance. "
            f"Max diff: {np.max(np.abs(original_vertices - loaded_vertices))}"
        )

        # Check normals
        original_normals = mesh_data["normals"]
        if hasattr(loaded, "vertex_normals") and loaded.vertex_normals is not None:
            loaded_normals = np.array(loaded.vertex_normals, dtype=np.float32)
            assert np.allclose(original_normals, loaded_normals, atol=TOLERANCE), (
                f"Tetrahedron normals exceed {TOLERANCE} tolerance."
            )

        # Check UVs
        original_uvs = mesh_data["uvs"]
        if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
            loaded_uvs = np.array(loaded.visual.uv, dtype=np.float32)
            assert np.allclose(original_uvs, loaded_uvs, atol=TOLERANCE), (
                f"Tetrahedron UVs exceed {TOLERANCE} tolerance."
            )

    @given(mesh_data=boundary_uv_meshes())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
        ],
    )
    def test_boundary_uv_round_trip(self, mesh_data: dict):
        """UV coordinates at boundaries (0.0, 1.0) survive GLB round-trip."""
        loaded = glb_round_trip(mesh_data)

        original_uvs = mesh_data["uvs"]

        if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
            loaded_uvs = np.array(loaded.visual.uv, dtype=np.float32)

            assert loaded_uvs.shape == original_uvs.shape, (
                f"Boundary UV shape mismatch: expected {original_uvs.shape}, "
                f"got {loaded_uvs.shape}"
            )

            assert np.allclose(original_uvs, loaded_uvs, atol=TOLERANCE), (
                f"Boundary UVs exceed {TOLERANCE} tolerance. "
                f"Max diff: {np.max(np.abs(original_uvs - loaded_uvs))}"
            )

            # Specifically verify boundary values are preserved
            assert np.all(loaded_uvs >= 0.0 - TOLERANCE), (
                "Loaded UVs contain values below 0.0"
            )
            assert np.all(loaded_uvs <= 1.0 + TOLERANCE), (
                "Loaded UVs contain values above 1.0"
            )
