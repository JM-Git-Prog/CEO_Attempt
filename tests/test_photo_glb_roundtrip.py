"""Property-based tests for GLB mesh data round-trip integrity.

# Feature: photo-to-playable-world

## Property 21: GLB Mesh Data Round-Trip

**Validates: Requirements 13.2**

For any valid mesh (vertices as float32 arrays, normals as float32 unit vectors,
UV coordinates in [0,1]), writing to GLB format then reading back SHALL produce
vertex positions, normals, and UV coordinates within 1e-6 absolute tolerance
per component.

Uses Hypothesis with trimesh and numpy for mesh generation strategies.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def finite_float32_arrays(
    draw: st.DrawFn,
    shape: tuple[int, ...],
    min_value: float = -100.0,
    max_value: float = 100.0,
) -> np.ndarray:
    """Generate finite float32 arrays with values in a reasonable range."""
    elements = st.floats(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    )
    flat = draw(st.lists(elements, min_size=shape[0] * shape[1], max_size=shape[0] * shape[1]))
    arr = np.array(flat, dtype=np.float32).reshape(shape)
    return arr


@st.composite
def valid_vertices(draw: st.DrawFn, num_vertices: int) -> np.ndarray:
    """Generate valid vertex positions as float32 within a reasonable range.

    Vertices are finite float32 values in [-100, 100] range to avoid
    precision issues at extreme values while still exercising the format.
    
    Ensures vertices are not all coincident (which would create degenerate
    geometry where trimesh cannot preserve normals during GLB roundtrip).
    """
    verts = draw(finite_float32_arrays(shape=(num_vertices, 3), min_value=-100.0, max_value=100.0))
    
    # Ensure at least some spatial extent - if all vertices are identical,
    # add small offsets to make them distinct. This prevents degenerate 
    # zero-area triangles that cause trimesh to recompute normals.
    extent = np.ptp(verts, axis=0)  # range per axis
    if np.all(extent < 1e-4):
        # Add small deterministic offsets to spread vertices out
        offsets = np.linspace(0, 0.1, num_vertices).reshape(-1, 1) * np.array([[1.0, 0.5, 0.25]])
        verts = verts + offsets.astype(np.float32)
    
    return verts


@st.composite
def unit_normals(draw: st.DrawFn, num_normals: int) -> np.ndarray:
    """Generate unit normal vectors (magnitude ~1.0).

    Strategy: generate random float32 vectors with at least one component
    having significant magnitude, then normalize to unit length.
    This avoids near-zero vectors that would be filtered out.
    """
    normals = []
    for _ in range(num_normals):
        # Generate a vector guaranteed to have magnitude > 0.1
        # by ensuring at least one axis has abs value >= 0.1
        axis = draw(st.integers(min_value=0, max_value=2))
        components = [
            draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False,
                           allow_infinity=False, allow_subnormal=False))
            for _ in range(3)
        ]
        # Force the chosen axis to have significant magnitude
        sign = draw(st.sampled_from([-1.0, 1.0]))
        components[axis] = sign * draw(
            st.floats(min_value=0.1, max_value=1.0, allow_nan=False,
                      allow_infinity=False, allow_subnormal=False)
        )
        normals.append(components)

    raw = np.array(normals, dtype=np.float32)
    magnitudes = np.linalg.norm(raw, axis=1, keepdims=True)
    normalized = raw / magnitudes
    return normalized.astype(np.float32)


@st.composite
def valid_uvs(draw: st.DrawFn, num_vertices: int) -> np.ndarray:
    """Generate UV coordinates clamped to [0, 1] range."""
    return draw(
        finite_float32_arrays(shape=(num_vertices, 2), min_value=0.0, max_value=1.0)
    )


@st.composite
def valid_faces(draw: st.DrawFn, num_vertices: int, num_faces: int) -> np.ndarray:
    """Generate valid triangle face indices referencing existing vertices.

    Each face is a triple of distinct vertex indices within [0, num_vertices).
    Distinct indices ensure non-degenerate triangles (when combined with
    non-coincident vertices).
    """
    faces = []
    for _ in range(num_faces):
        # Draw 3 distinct indices to avoid degenerate triangles
        if num_vertices >= 3:
            idx_list = draw(
                st.lists(
                    st.integers(min_value=0, max_value=num_vertices - 1),
                    min_size=3,
                    max_size=3,
                    unique=True,
                )
            )
        else:
            # Fallback for very small vertex counts (shouldn't happen with min 4)
            idx_list = draw(
                st.lists(
                    st.integers(min_value=0, max_value=num_vertices - 1),
                    min_size=3,
                    max_size=3,
                )
            )
        faces.append(idx_list)

    return np.array(faces, dtype=np.int64)


@st.composite
def valid_mesh_data(draw: st.DrawFn) -> dict:
    """Generate a complete valid mesh with vertices, normals, UVs, and faces.

    Produces meshes with:
    - 4 to 50 vertices (float32, finite, reasonable range)
    - 4 to 30 triangle faces (valid indices referencing existing vertices)
    - Per-vertex unit normals (float32, magnitude ~1.0)
    - Per-vertex UV coordinates (float32, in [0, 1])

    The mesh size is kept small for test speed while still being
    representative of real pipeline meshes.
    """
    num_vertices = draw(st.integers(min_value=4, max_value=50))
    num_faces = draw(st.integers(min_value=4, max_value=30))

    vertices = draw(valid_vertices(num_vertices))
    normals = draw(unit_normals(num_vertices))
    uvs = draw(valid_uvs(num_vertices))
    faces = draw(valid_faces(num_vertices, num_faces))

    return {
        "vertices": vertices,
        "normals": normals,
        "uvs": uvs,
        "faces": faces,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_mesh_with_attributes(
    vertices: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray,
    uvs: np.ndarray,
) -> trimesh.Trimesh:
    """Create a trimesh.Trimesh with explicit vertex normals and UV coordinates.

    GLB format stores vertex normals as accessor data and UVs as
    TEXCOORD_0 attributes. We use trimesh's visual.TextureVisuals
    to attach UV coordinates that survive GLB serialization.
    """
    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        vertex_normals=normals,
        process=False,  # Don't modify topology
    )

    # Attach UV coordinates via texture visuals
    # trimesh stores UVs on the visual object for GLB export
    visual = trimesh.visual.TextureVisuals(uv=uvs)
    mesh.visual = visual

    return mesh


def _write_and_read_glb(mesh: trimesh.Trimesh, tmp_dir: Path) -> trimesh.Trimesh:
    """Write mesh to GLB, then read it back via trimesh.

    This exercises the exact same write/read path used by the photo pipeline:
    mesh.export(path, file_type="glb") → trimesh.load(path, force="mesh")
    """
    glb_path = tmp_dir / "roundtrip_test.glb"
    mesh.export(str(glb_path), file_type="glb")

    # Read back
    loaded = trimesh.load(str(glb_path), force="mesh", process=False)
    return loaded


def _write_and_read_glb_raw(mesh: trimesh.Trimesh, tmp_dir: Path) -> dict:
    """Write mesh to GLB, then read it back using the low-level GLB loader.

    Returns the raw geometry data dict which preserves the stored normals
    exactly as they appear in the GLB file's NORMAL accessor, without
    trimesh recomputing them from face geometry.
    """
    from trimesh.exchange.gltf import load_glb

    glb_path = tmp_dir / "roundtrip_test.glb"
    mesh.export(str(glb_path), file_type="glb")

    with open(glb_path, "rb") as f:
        kwargs = load_glb(f)

    # Get first geometry (our exported mesh)
    geom_data = next(iter(kwargs["geometry"].values()))
    return geom_data


# ---------------------------------------------------------------------------
# Property 21: GLB Mesh Data Round-Trip
# ---------------------------------------------------------------------------


class TestGLBMeshDataRoundTrip:
    """Property 21: GLB Mesh Data Round-Trip.

    **Validates: Requirements 13.2**

    For any valid mesh (vertices as float32 arrays, normals as float32 unit
    vectors, UV coordinates in [0,1]), writing to GLB format then reading
    back SHALL produce vertex positions, normals, and UV coordinates within
    1e-6 absolute tolerance per component.

    Tests use real trimesh GLB export/import, exercising the same code path
    used by the photo pipeline's Object_Generator and Room_Reconstructor.
    """

    @given(data=valid_mesh_data())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_vertex_positions_survive_roundtrip(self, data: dict):
        """Vertex positions are preserved within 1e-6 absolute tolerance.

        GLB stores vertex positions as float32 accessors. Since our input
        is already float32, the round-trip should be essentially lossless
        (within floating point representation limits).
        """
        vertices = data["vertices"]
        faces = data["faces"]
        normals = data["normals"]
        uvs = data["uvs"]

        mesh = _create_mesh_with_attributes(vertices, faces, normals, uvs)

        tmp_dir = Path(tempfile.mkdtemp(prefix="glb_rt_vert_"))
        try:
            loaded = _write_and_read_glb(mesh, tmp_dir)

            assert loaded.vertices.shape == vertices.shape, (
                f"Vertex shape mismatch: original {vertices.shape} vs "
                f"loaded {loaded.vertices.shape}"
            )
            assert np.allclose(
                loaded.vertices.astype(np.float32),
                vertices,
                atol=1e-6,
                rtol=0,
            ), (
                f"Vertex positions differ beyond 1e-6 tolerance. "
                f"Max abs diff: {np.max(np.abs(loaded.vertices.astype(np.float32) - vertices))}"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(data=valid_mesh_data())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_normals_survive_roundtrip(self, data: dict):
        """Normal vectors are preserved within 1e-6 absolute tolerance.

        GLB stores normals as float32 unit vectors in the NORMAL accessor.
        We use the low-level GLB loader to read back the stored normals
        directly (since trimesh recomputes vertex_normals from geometry
        on high-level load).
        """
        vertices = data["vertices"]
        faces = data["faces"]
        normals = data["normals"]
        uvs = data["uvs"]

        mesh = _create_mesh_with_attributes(vertices, faces, normals, uvs)

        tmp_dir = Path(tempfile.mkdtemp(prefix="glb_rt_norm_"))
        try:
            raw_data = _write_and_read_glb_raw(mesh, tmp_dir)

            assert "vertex_normals" in raw_data, (
                "vertex_normals not found in GLB raw data"
            )
            loaded_normals = raw_data["vertex_normals"].astype(np.float32)

            assert loaded_normals.shape == normals.shape, (
                f"Normal shape mismatch: original {normals.shape} vs "
                f"loaded {loaded_normals.shape}"
            )
            assert np.allclose(
                loaded_normals,
                normals,
                atol=1e-6,
                rtol=0,
            ), (
                f"Normals differ beyond 1e-6 tolerance. "
                f"Max abs diff: {np.max(np.abs(loaded_normals - normals))}"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(data=valid_mesh_data())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_uv_coordinates_survive_roundtrip(self, data: dict):
        """UV coordinates are preserved within 1e-6 absolute tolerance.

        GLB stores UVs as TEXCOORD_0 float32 accessors. Since our input
        UVs are float32 in [0,1], the round-trip should preserve them
        with negligible error.
        """
        vertices = data["vertices"]
        faces = data["faces"]
        normals = data["normals"]
        uvs = data["uvs"]

        mesh = _create_mesh_with_attributes(vertices, faces, normals, uvs)

        tmp_dir = Path(tempfile.mkdtemp(prefix="glb_rt_uv_"))
        try:
            loaded = _write_and_read_glb(mesh, tmp_dir)

            # Extract UVs from loaded mesh visual
            loaded_uvs = None
            if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
                loaded_uvs = loaded.visual.uv.astype(np.float32)
            elif hasattr(loaded.visual, "to_texture"):
                tex_visual = loaded.visual.to_texture()
                if tex_visual.uv is not None:
                    loaded_uvs = tex_visual.uv.astype(np.float32)

            assert loaded_uvs is not None, (
                "UV coordinates not found in loaded GLB mesh. "
                f"Visual type: {type(loaded.visual).__name__}"
            )
            assert loaded_uvs.shape == uvs.shape, (
                f"UV shape mismatch: original {uvs.shape} vs "
                f"loaded {loaded_uvs.shape}"
            )
            assert np.allclose(
                loaded_uvs,
                uvs,
                atol=1e-6,
                rtol=0,
            ), (
                f"UV coordinates differ beyond 1e-6 tolerance. "
                f"Max abs diff: {np.max(np.abs(loaded_uvs - uvs))}"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(data=valid_mesh_data())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    def test_all_mesh_attributes_roundtrip_simultaneously(self, data: dict):
        """Combined property: vertices, normals, AND UVs all survive round-trip.

        Verifies in a single pass that all three mesh data channels
        (positions, normals, UVs) survive the GLB write→read cycle
        within 1e-6 absolute tolerance per component.

        This combined test exercises the complete Property 21 specification
        in one assertion block for efficient counterexample discovery.
        """
        vertices = data["vertices"]
        faces = data["faces"]
        normals = data["normals"]
        uvs = data["uvs"]

        mesh = _create_mesh_with_attributes(vertices, faces, normals, uvs)

        tmp_dir = Path(tempfile.mkdtemp(prefix="glb_rt_all_"))
        try:
            # Use high-level load for vertices and UVs
            loaded = _write_and_read_glb(mesh, tmp_dir)
            # Use low-level load for normals (trimesh recomputes on high-level load)
            raw_data = _write_and_read_glb_raw(mesh, tmp_dir)

            # Check vertices
            assert loaded.vertices.shape == vertices.shape, (
                f"Vertex shape mismatch: {vertices.shape} vs {loaded.vertices.shape}"
            )
            loaded_verts = loaded.vertices.astype(np.float32)
            assert np.allclose(loaded_verts, vertices, atol=1e-6, rtol=0), (
                f"Vertices differ. Max diff: "
                f"{np.max(np.abs(loaded_verts - vertices))}"
            )

            # Check normals via raw GLB data
            assert "vertex_normals" in raw_data, (
                "vertex_normals not found in GLB raw data"
            )
            loaded_normals = raw_data["vertex_normals"].astype(np.float32)
            assert loaded_normals.shape == normals.shape, (
                f"Normal shape mismatch: {normals.shape} vs {loaded_normals.shape}"
            )
            assert np.allclose(loaded_normals, normals, atol=1e-6, rtol=0), (
                f"Normals differ. Max diff: "
                f"{np.max(np.abs(loaded_normals - normals))}"
            )

            # Check UVs
            loaded_uvs = None
            if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
                loaded_uvs = loaded.visual.uv.astype(np.float32)
            elif hasattr(loaded.visual, "to_texture"):
                tex_visual = loaded.visual.to_texture()
                if tex_visual.uv is not None:
                    loaded_uvs = tex_visual.uv.astype(np.float32)

            assert loaded_uvs is not None, (
                f"UVs not found. Visual type: {type(loaded.visual).__name__}"
            )
            assert loaded_uvs.shape == uvs.shape, (
                f"UV shape mismatch: {uvs.shape} vs {loaded_uvs.shape}"
            )
            assert np.allclose(loaded_uvs, uvs, atol=1e-6, rtol=0), (
                f"UVs differ. Max diff: {np.max(np.abs(loaded_uvs - uvs))}"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
