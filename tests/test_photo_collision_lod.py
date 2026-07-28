"""Property-based tests for photo pipeline collision and LOD generation.

# Feature: photo-to-playable-world

## Property 17: Collision Method Selection by Face Count

**Validates: Requirements 9.1, 9.2**

For any mesh with face_count > 100, the collision generation SHALL use V-HACD
decomposition (max 16 hulls) or fall back to bounding_box — never direct
convex_hull. For any mesh with face_count ≤ 100, the collision generation SHALL
use direct convex hull (hull_count == 1).

## Property 18: LOD Generation Invariants

**Validates: Requirements 9.3, 9.4**

For any input mesh, LOD generation SHALL produce exactly 4 levels where:
LOD0 face_count equals the original, each subsequent level has face_count
≤ the previous level, and no level has fewer than 4 faces.

Uses Hypothesis with trimesh for mesh generation strategies.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.collision_lod import CollisionLODGenerator
from src.photo_pipeline.models import CollisionResult, PhotoPipelineConfig


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def icosphere_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate icosphere meshes with varying subdivision levels.

    subdivisions=1 → 80 faces
    subdivisions=2 → 320 faces
    subdivisions=3 → 1280 faces
    subdivisions=4 → 5120 faces
    """
    subdivisions = draw(st.integers(min_value=1, max_value=4))
    radius = draw(st.floats(min_value=0.5, max_value=5.0))
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


@st.composite
def box_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate box meshes (always 12 faces)."""
    extents = [
        draw(st.floats(min_value=0.1, max_value=10.0)) for _ in range(3)
    ]
    return trimesh.creation.box(extents=extents)


@st.composite
def cylinder_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate cylinder meshes with varying section counts.

    sections controls face count: sections=8 → ~28 faces,
    sections=32 → ~124 faces, sections=64 → ~252 faces.
    """
    radius = draw(st.floats(min_value=0.1, max_value=5.0))
    height = draw(st.floats(min_value=0.1, max_value=10.0))
    sections = draw(st.integers(min_value=8, max_value=64))
    return trimesh.creation.cylinder(radius=radius, height=height, sections=sections)


@st.composite
def minimal_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes with exactly 4 faces (tetrahedron — near minimum).

    A tetrahedron has exactly 4 triangular faces — the minimum allowed
    by the LOD invariant.
    """
    scale = draw(st.floats(min_value=0.1, max_value=5.0))
    vertices = np.array([
        [1, 1, 1],
        [1, -1, -1],
        [-1, 1, -1],
        [-1, -1, 1],
    ], dtype=np.float64) * scale
    faces = np.array([
        [0, 1, 2],
        [0, 1, 3],
        [0, 2, 3],
        [1, 2, 3],
    ], dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=faces)


@st.composite
def varied_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate diverse meshes from different creation methods.

    Covers: icospheres (80-5120 faces), boxes (12 faces),
    cylinders (28-252 faces), and minimal tetrahedra (4 faces).
    """
    mesh_type = draw(st.sampled_from(["icosphere", "box", "cylinder", "minimal"]))

    if mesh_type == "icosphere":
        return draw(icosphere_meshes())
    elif mesh_type == "box":
        return draw(box_meshes())
    elif mesh_type == "cylinder":
        return draw(cylinder_meshes())
    else:
        return draw(minimal_meshes())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_lod_on_mesh(mesh: trimesh.Trimesh):
    """Export mesh to a temp GLB, run LOD generation, clean up, and return result.

    Returns (LODResult, original_face_count_after_roundtrip).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="lod_test_"))
    try:
        mesh_path = tmp_dir / "test_mesh.glb"
        mesh.export(str(mesh_path), file_type="glb")

        # Reload to get the face count as stored (GLB round-trip may differ)
        reloaded = trimesh.load(str(mesh_path), force="mesh")
        original_face_count = len(reloaded.faces)

        generator = CollisionLODGenerator(output_dir=tmp_dir)
        config = PhotoPipelineConfig()
        result = generator.generate_lod(mesh_path, config)

        return result, original_face_count
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 18: LOD Generation Invariants
# ---------------------------------------------------------------------------


class TestLODGenerationInvariants:
    """Property 18: LOD Generation Invariants.

    **Validates: Requirements 9.3, 9.4**

    For any input mesh, LOD generation SHALL produce exactly 4 levels where:
    - LOD0 face_count equals the original mesh's face count
    - Each subsequent level has face_count ≤ the previous level (monotone non-increasing)
    - No level has fewer than 4 faces

    Tests use real meshes written to GLB format, exercising the actual
    generate_lod method including file I/O and decimation logic.
    """

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_lod_produces_exactly_4_levels(self, mesh: trimesh.Trimesh):
        """LOD generation always produces exactly 4 levels (keys 0, 1, 2, 3).

        Regardless of input mesh complexity, the result must contain
        exactly 4 LOD levels corresponding to the configured ratios
        (1.0, 0.5, 0.25, 0.1).
        """
        assume(len(mesh.faces) >= 4)

        result, _ = _run_lod_on_mesh(mesh)

        # Must have exactly 4 levels
        assert len(result.face_counts) == 4, (
            f"Expected 4 face count entries, got {len(result.face_counts)}: "
            f"keys={list(result.face_counts.keys())}"
        )
        # Keys must be 0, 1, 2, 3
        assert set(result.face_counts.keys()) == {0, 1, 2, 3}, (
            f"Expected face_count keys {{0, 1, 2, 3}}, got {set(result.face_counts.keys())}"
        )

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_lod0_equals_original_face_count(self, mesh: trimesh.Trimesh):
        """LOD0 face count equals the original mesh's face count.

        Since LOD0 uses ratio 1.0 (100%), it should preserve the exact
        face count of the input mesh.
        """
        assume(len(mesh.faces) >= 4)

        result, original_face_count = _run_lod_on_mesh(mesh)
        assume(original_face_count >= 4)

        assert result.face_counts[0] == original_face_count, (
            f"LOD0 face count ({result.face_counts[0]}) != "
            f"original ({original_face_count})"
        )

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_lod_face_counts_monotone_non_increasing(self, mesh: trimesh.Trimesh):
        """Each LOD level has face_count ≤ the previous level.

        Face counts must be monotone non-increasing across levels:
        LOD0 >= LOD1 >= LOD2 >= LOD3.

        Note: decimation may not always reduce face count (e.g., when the
        target is close to the original, or decimation fails and the
        original is returned), but it should never increase it.
        """
        assume(len(mesh.faces) >= 4)

        result, _ = _run_lod_on_mesh(mesh)

        for level in range(1, 4):
            assert result.face_counts[level] <= result.face_counts[level - 1], (
                f"LOD{level} face count ({result.face_counts[level]}) > "
                f"LOD{level - 1} face count ({result.face_counts[level - 1]}). "
                f"All face counts: {dict(result.face_counts)}"
            )

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_no_lod_level_below_4_faces(self, mesh: trimesh.Trimesh):
        """No LOD level has fewer than 4 faces.

        The _decimate method clamps target_face_count to max(4, ...)
        and validates decimation results have at least 4 faces,
        falling back to the original mesh if decimation produces
        degenerate geometry.
        """
        assume(len(mesh.faces) >= 4)

        result, _ = _run_lod_on_mesh(mesh)

        for level in range(4):
            assert result.face_counts[level] >= 4, (
                f"LOD{level} has {result.face_counts[level]} faces (< 4 minimum). "
                f"All face counts: {dict(result.face_counts)}"
            )

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_all_lod_invariants_hold_simultaneously(self, mesh: trimesh.Trimesh):
        """Combined property: all LOD invariants hold for any valid input mesh.

        Verifies in a single pass:
        1. Exactly 4 levels produced (keys 0, 1, 2, 3)
        2. LOD0 == original face count
        3. Monotone non-increasing across levels
        4. No level < 4 faces

        This combined test exercises the complete Property 18 specification
        in one assertion block for efficient counterexample discovery.
        """
        assume(len(mesh.faces) >= 4)

        result, original_face_count = _run_lod_on_mesh(mesh)
        assume(original_face_count >= 4)

        # Invariant 1: exactly 4 levels
        assert set(result.face_counts.keys()) == {0, 1, 2, 3}, (
            f"Expected 4 levels {{0,1,2,3}}, got {set(result.face_counts.keys())}"
        )

        # Invariant 2: LOD0 == original face count
        assert result.face_counts[0] == original_face_count, (
            f"LOD0={result.face_counts[0]} != original={original_face_count}"
        )

        # Invariant 3: monotone non-increasing
        for level in range(1, 4):
            assert result.face_counts[level] <= result.face_counts[level - 1], (
                f"LOD{level}={result.face_counts[level]} > "
                f"LOD{level-1}={result.face_counts[level-1]}"
            )

        # Invariant 4: minimum 4 faces at every level
        for level in range(4):
            assert result.face_counts[level] >= 4, (
                f"LOD{level}={result.face_counts[level]} < 4 minimum"
            )

    @given(mesh=icosphere_meshes())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_lod_produces_valid_glb_files(self, mesh: trimesh.Trimesh):
        """All LOD levels produce valid GLB files loadable by trimesh.

        Each generated LOD level must produce a real GLB file on disk
        whose loaded face count matches the reported face_counts dict.
        """
        assume(len(mesh.faces) >= 4)

        tmp_dir = Path(tempfile.mkdtemp(prefix="lod_glb_test_"))
        try:
            mesh_path = tmp_dir / "test_mesh.glb"
            mesh.export(str(mesh_path), file_type="glb")

            generator = CollisionLODGenerator(output_dir=tmp_dir)
            config = PhotoPipelineConfig()
            result = generator.generate_lod(mesh_path, config)

            for level, lod_path in result.lod_paths.items():
                assert lod_path.exists(), (
                    f"LOD{level} path does not exist: {lod_path}"
                )
                loaded = trimesh.load(str(lod_path), force="mesh")
                assert len(loaded.faces) == result.face_counts[level], (
                    f"LOD{level} file has {len(loaded.faces)} faces but "
                    f"result reports {result.face_counts[level]}"
                )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Strategies (additional for Property 17)
# ---------------------------------------------------------------------------


@st.composite
def high_face_count_meshes(draw: st.DrawFn) -> trimesh.Trimesh:
    """Generate meshes guaranteed to have > 100 faces.

    Uses icosphere subdivisions 2+ (320+ faces) to ensure the collision
    logic takes the V-HACD / complex-mesh path.
    """
    subdivisions = draw(st.integers(min_value=2, max_value=4))
    radius = draw(st.floats(min_value=0.5, max_value=5.0))
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


# ---------------------------------------------------------------------------
# Helpers (Property 17)
# ---------------------------------------------------------------------------


def _run_collision_on_mesh(mesh: trimesh.Trimesh) -> CollisionResult:
    """Export mesh to a temp GLB, run collision generation, clean up, return result.

    Uses tempfile.mkdtemp for Hypothesis compatibility (no pytest fixtures).

    Returns
    -------
    CollisionResult
        The collision result including method used and hull count.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="collision_test_"))
    try:
        mesh_path = tmp_dir / "test_mesh.glb"
        mesh.export(str(mesh_path), file_type="glb")

        generator = CollisionLODGenerator(output_dir=tmp_dir)
        config = PhotoPipelineConfig()
        result = generator.generate_collision(mesh_path, config)

        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 17: Collision Method Selection by Face Count
# ---------------------------------------------------------------------------


class TestCollisionMethodSelection:
    """Property 17: Collision Method Selection by Face Count.

    **Validates: Requirements 9.1, 9.2**

    For any mesh with face_count > 100, the collision generation SHALL use
    V-HACD decomposition (max 16 hulls). For any mesh with face_count ≤ 100,
    the collision generation SHALL use direct convex hull.

    The V-HACD plugin may not be available in all environments, so when
    face_count > 100 and V-HACD fails, the system falls back to bounding_box.
    The key invariant is that simple meshes (≤ 100 faces) always use
    convex_hull, and complex meshes (> 100 faces) never use convex_hull
    directly — they go through the V-HACD path (which may fall back to
    bounding_box on failure, but never to direct convex_hull).
    """

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_low_face_count_uses_convex_hull(self, mesh: trimesh.Trimesh):
        """Meshes with ≤ 100 faces use direct convex hull (method="convex_hull", hull_count=1).

        For simple geometry the system bypasses V-HACD entirely and produces
        a single convex hull as the collision shape. This is both faster and
        sufficient for low-poly objects.

        Note: GLB round-trip may slightly alter face count, so we check the
        reloaded face count against the threshold.
        """
        assume(len(mesh.faces) >= 4)

        # Export and reload to get the actual face count after GLB round-trip
        tmp_dir = Path(tempfile.mkdtemp(prefix="collision_fc_check_"))
        try:
            mesh_path = tmp_dir / "test_mesh.glb"
            mesh.export(str(mesh_path), file_type="glb")
            reloaded = trimesh.load(str(mesh_path), force="mesh")
            reloaded_face_count = len(reloaded.faces)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Only test meshes that land at ≤ 100 faces after round-trip
        assume(reloaded_face_count <= 100)

        result = _run_collision_on_mesh(mesh)

        assert result.method == "convex_hull", (
            f"Mesh with {reloaded_face_count} faces (≤100) should use 'convex_hull', "
            f"got '{result.method}'"
        )
        assert result.hull_count == 1, (
            f"Convex hull method should produce exactly 1 hull, got {result.hull_count}"
        )

    @given(mesh=high_face_count_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_high_face_count_never_uses_convex_hull(self, mesh: trimesh.Trimesh):
        """Meshes with > 100 faces never use direct convex_hull method.

        Complex geometry (> 100 faces) is routed through the V-HACD
        decomposition path. If V-HACD succeeds, method is "vhacd". If it
        fails or times out, the fallback is "bounding_box". The direct
        "convex_hull" method is never selected for complex meshes.
        """
        assume(len(mesh.faces) > 100)

        result = _run_collision_on_mesh(mesh)

        assert result.method in ("vhacd", "bounding_box"), (
            f"Mesh with > 100 faces should use 'vhacd' or 'bounding_box', "
            f"got '{result.method}'. The 'convex_hull' method is reserved for "
            f"simple meshes (≤ 100 faces)."
        )

    @given(mesh=high_face_count_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vhacd_respects_max_hull_limit(self, mesh: trimesh.Trimesh):
        """When V-HACD succeeds, hull_count never exceeds config.vhacd_max_hulls (16).

        The V-HACD decomposition is configured with maxhulls=16. If the
        method reports "vhacd", the resulting hull count must respect this
        upper bound.
        """
        assume(len(mesh.faces) > 100)

        result = _run_collision_on_mesh(mesh)
        config = PhotoPipelineConfig()

        if result.method == "vhacd":
            assert result.hull_count <= config.vhacd_max_hulls, (
                f"V-HACD produced {result.hull_count} hulls, exceeding "
                f"max_hulls={config.vhacd_max_hulls}"
            )

    @given(mesh=varied_meshes())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_collision_mesh_file_is_created(self, mesh: trimesh.Trimesh):
        """Collision generation always produces a GLB file on disk.

        Regardless of which collision method is selected (convex_hull,
        vhacd, or bounding_box), the collision_mesh_path in the result
        must point to an existing file that can be loaded by trimesh.
        """
        assume(len(mesh.faces) >= 4)

        tmp_dir = Path(tempfile.mkdtemp(prefix="collision_file_test_"))
        try:
            mesh_path = tmp_dir / "test_mesh.glb"
            mesh.export(str(mesh_path), file_type="glb")

            generator = CollisionLODGenerator(output_dir=tmp_dir)
            config = PhotoPipelineConfig()
            result = generator.generate_collision(mesh_path, config)

            assert result.collision_mesh_path.exists(), (
                f"Collision mesh file does not exist: {result.collision_mesh_path}"
            )

            # Verify the file is a loadable mesh
            loaded = trimesh.load(str(result.collision_mesh_path), force="mesh")
            assert len(loaded.faces) >= 4, (
                f"Collision mesh has {len(loaded.faces)} faces (< 4 minimum)"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
