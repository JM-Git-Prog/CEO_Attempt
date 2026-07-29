"""Property-based tests for V14 GLB mesh vertex round-trip integrity.

# Feature: photo-to-real-3d-world-v14

## Property 17: GLB Mesh Vertex Round-Trip

**Validates: Requirements 11.5, 15.2**

For any GLB file produced by the pipeline, loading with trimesh and
re-exporting as GLB SHALL produce vertex positions and normals that differ
by less than 1e-5 absolute tolerance per component.

Uses Hypothesis with trimesh-generated meshes (icospheres, boxes with textures)
at varied face counts representing the range of meshes the V14 pipeline produces:
- Small: icosphere subdivisions 1-2 (~80-320 faces)
- Medium: icosphere subdivisions 3 (~1280 faces)
- Large: icosphere subdivisions 4-5 (~5120-20480 faces)
- Boxes with textures (placeholder geometry style)

For each generated GLB:
1. Export mesh to GLB with trimesh
2. Load the GLB back with trimesh
3. Re-export to a second GLB
4. Load the second GLB
5. Compare vertices and normals between step 2 and step 4
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from PIL import Image


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOLERANCE = 1e-5


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Subdivision levels representing different pipeline output sizes:
# 1→80 faces, 2→320, 3→1280, 4→5120, 5→20480
_subdivision_small = st.integers(min_value=1, max_value=2)
_subdivision_medium = st.just(3)
_subdivision_large = st.integers(min_value=4, max_value=5)
_subdivision_any = st.integers(min_value=1, max_value=5)

# Texture size representing the V14 pipeline's texture dimension choices
_texture_size = st.sampled_from([(256, 256), (512, 512), (1024, 1024)])

# Box extents for placeholder geometry
_box_extent = st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)


def _create_textured_icosphere(subdivisions: int, tex_size: tuple[int, int]) -> trimesh.Trimesh:
    """Create an icosphere with an embedded texture, simulating pipeline output."""
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)

    # Generate UV coordinates
    uv = np.random.default_rng(42).random((len(mesh.vertices), 2)).astype(np.float32)

    # Create a texture image (simulates the base color map from the pipeline)
    img = Image.new("RGB", tex_size, color=(180, 140, 100))
    material = trimesh.visual.material.SimpleMaterial(image=img)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    return mesh


def _create_textured_box(
    extents: tuple[float, float, float], tex_size: tuple[int, int]
) -> trimesh.Trimesh:
    """Create a box mesh with texture, simulating placeholder geometry from the pipeline."""
    mesh = trimesh.creation.box(extents=extents)

    # Generate UV coordinates for the box
    uv = np.random.default_rng(7).random((len(mesh.vertices), 2)).astype(np.float32)

    img = Image.new("RGB", tex_size, color=(100, 150, 200))
    material = trimesh.visual.material.SimpleMaterial(image=img)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    return mesh


@st.composite
def pipeline_icosphere_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate textured icosphere meshes at various subdivision levels.

    Represents meshes produced by Hunyuan3D/Trellis2 in the V14 pipeline.
    """
    subdivisions = draw(_subdivision_any)
    tex_size = draw(_texture_size)
    return _create_textured_icosphere(subdivisions, tex_size)


@st.composite
def pipeline_box_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate textured box meshes with varied extents.

    Represents placeholder geometry produced by the V14 pipeline fallback.
    """
    ext_x = draw(_box_extent)
    ext_y = draw(_box_extent)
    ext_z = draw(_box_extent)
    tex_size = draw(_texture_size)
    return _create_textured_box((ext_x, ext_y, ext_z), tex_size)


@st.composite
def pipeline_large_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate large face-count meshes (subdivisions 4-5).

    Represents high-quality Hunyuan3D output (~5120-20480 faces).
    """
    subdivisions = draw(_subdivision_large)
    tex_size = draw(_texture_size)
    return _create_textured_icosphere(subdivisions, tex_size)


# ---------------------------------------------------------------------------
# Helper: GLB round-trip (export → load → re-export → load)
# ---------------------------------------------------------------------------


def glb_round_trip(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Perform a full GLB round-trip and return both loaded meshes.

    1. Export original mesh to GLB (first_glb)
    2. Load first_glb → first_loaded
    3. Export first_loaded to GLB (second_glb)
    4. Load second_glb → second_loaded
    5. Return (first_loaded, second_loaded)
    """
    first_path = None
    second_path = None

    try:
        # Step 1: Export original mesh to first GLB
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            first_path = Path(f.name)
        mesh.export(str(first_path), file_type="glb")

        # Step 2: Load first GLB
        first_loaded = _load_mesh_from_glb(first_path)

        # Step 3: Re-export loaded mesh to second GLB
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            second_path = Path(f.name)
        first_loaded.export(str(second_path), file_type="glb")

        # Step 4: Load second GLB
        second_loaded = _load_mesh_from_glb(second_path)

        return first_loaded, second_loaded

    finally:
        if first_path is not None:
            first_path.unlink(missing_ok=True)
        if second_path is not None:
            second_path.unlink(missing_ok=True)


def _load_mesh_from_glb(glb_path: Path) -> trimesh.Trimesh:
    """Load a GLB file and extract the mesh geometry.

    Uses process=False to preserve vertex data without modification.
    Handles both Scene and Trimesh return types from trimesh.load.
    """
    loaded = trimesh.load(str(glb_path), process=False)
    if isinstance(loaded, trimesh.Scene):
        # Extract first geometry from the scene
        geometries = list(loaded.geometry.values())
        return geometries[0]
    return loaded


# ---------------------------------------------------------------------------
# Property 17: GLB Mesh Vertex Round-Trip
# ---------------------------------------------------------------------------


class TestGLBMeshVertexRoundTrip:
    """Property 17: GLB Mesh Vertex Round-Trip.

    **Validates: Requirements 11.5, 15.2**

    For any GLB file produced by the pipeline, loading with trimesh and
    re-exporting as GLB SHALL produce vertex positions and normals that
    differ by less than 1e-5 absolute tolerance per component.
    """

    @given(mesh=pipeline_icosphere_meshes())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vertex_positions_round_trip_icospheres(self, mesh: trimesh.Trimesh) -> None:
        """Vertex positions survive GLB round-trip within 1e-5 for icospheres."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        first_verts = np.array(first_loaded.vertices, dtype=np.float32)
        second_verts = np.array(second_loaded.vertices, dtype=np.float32)

        assert first_verts.shape == second_verts.shape, (
            f"Vertex count mismatch: first={first_verts.shape[0]}, "
            f"second={second_verts.shape[0]}"
        )

        assert np.allclose(first_verts, second_verts, atol=TOLERANCE), (
            f"Vertex positions exceed {TOLERANCE} tolerance after round-trip. "
            f"Max diff: {np.max(np.abs(first_verts - second_verts)):.2e}"
        )

    @given(mesh=pipeline_icosphere_meshes())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_round_trip_icospheres(self, mesh: trimesh.Trimesh) -> None:
        """Vertex normals survive GLB round-trip within 1e-5 for icospheres."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        if (
            hasattr(first_loaded, "vertex_normals")
            and first_loaded.vertex_normals is not None
            and len(first_loaded.vertex_normals) > 0
        ):
            first_normals = np.array(first_loaded.vertex_normals, dtype=np.float32)
            second_normals = np.array(second_loaded.vertex_normals, dtype=np.float32)

            assert first_normals.shape == second_normals.shape, (
                f"Normal shape mismatch: first={first_normals.shape}, "
                f"second={second_normals.shape}"
            )

            assert np.allclose(first_normals, second_normals, atol=TOLERANCE), (
                f"Normals exceed {TOLERANCE} tolerance after round-trip. "
                f"Max diff: {np.max(np.abs(first_normals - second_normals)):.2e}"
            )

    @given(mesh=pipeline_box_meshes())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vertex_positions_round_trip_boxes(self, mesh: trimesh.Trimesh) -> None:
        """Vertex positions survive GLB round-trip within 1e-5 for box meshes."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        first_verts = np.array(first_loaded.vertices, dtype=np.float32)
        second_verts = np.array(second_loaded.vertices, dtype=np.float32)

        assert first_verts.shape == second_verts.shape, (
            f"Vertex count mismatch: first={first_verts.shape[0]}, "
            f"second={second_verts.shape[0]}"
        )

        assert np.allclose(first_verts, second_verts, atol=TOLERANCE), (
            f"Box vertex positions exceed {TOLERANCE} tolerance after round-trip. "
            f"Max diff: {np.max(np.abs(first_verts - second_verts)):.2e}"
        )

    @given(mesh=pipeline_box_meshes())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_round_trip_boxes(self, mesh: trimesh.Trimesh) -> None:
        """Vertex normals survive GLB round-trip within 1e-5 for box meshes."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        if (
            hasattr(first_loaded, "vertex_normals")
            and first_loaded.vertex_normals is not None
            and len(first_loaded.vertex_normals) > 0
        ):
            first_normals = np.array(first_loaded.vertex_normals, dtype=np.float32)
            second_normals = np.array(second_loaded.vertex_normals, dtype=np.float32)

            assert first_normals.shape == second_normals.shape, (
                f"Normal shape mismatch: first={first_normals.shape}, "
                f"second={second_normals.shape}"
            )

            assert np.allclose(first_normals, second_normals, atol=TOLERANCE), (
                f"Box normals exceed {TOLERANCE} tolerance after round-trip. "
                f"Max diff: {np.max(np.abs(first_normals - second_normals)):.2e}"
            )

    @given(mesh=pipeline_large_meshes())
    @settings(
        max_examples=20,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vertex_positions_round_trip_large_meshes(self, mesh: trimesh.Trimesh) -> None:
        """Large meshes (5120-20480 faces) survive GLB round-trip within 1e-5."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        first_verts = np.array(first_loaded.vertices, dtype=np.float32)
        second_verts = np.array(second_loaded.vertices, dtype=np.float32)

        assert first_verts.shape == second_verts.shape, (
            f"Large mesh vertex count mismatch: first={first_verts.shape[0]}, "
            f"second={second_verts.shape[0]}"
        )

        assert np.allclose(first_verts, second_verts, atol=TOLERANCE), (
            f"Large mesh vertices exceed {TOLERANCE} tolerance after round-trip. "
            f"Max diff: {np.max(np.abs(first_verts - second_verts)):.2e}"
        )

    @given(mesh=pipeline_large_meshes())
    @settings(
        max_examples=20,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_round_trip_large_meshes(self, mesh: trimesh.Trimesh) -> None:
        """Large mesh normals survive GLB round-trip within 1e-5."""
        first_loaded, second_loaded = glb_round_trip(mesh)

        if (
            hasattr(first_loaded, "vertex_normals")
            and first_loaded.vertex_normals is not None
            and len(first_loaded.vertex_normals) > 0
        ):
            first_normals = np.array(first_loaded.vertex_normals, dtype=np.float32)
            second_normals = np.array(second_loaded.vertex_normals, dtype=np.float32)

            assert first_normals.shape == second_normals.shape, (
                f"Large mesh normal shape mismatch: first={first_normals.shape}, "
                f"second={second_normals.shape}"
            )

            assert np.allclose(first_normals, second_normals, atol=TOLERANCE), (
                f"Large mesh normals exceed {TOLERANCE} tolerance after round-trip. "
                f"Max diff: {np.max(np.abs(first_normals - second_normals)):.2e}"
            )
