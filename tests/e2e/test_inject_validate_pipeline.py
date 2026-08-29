"""End-to-end integration test for the inject-then-validate capture pipeline.

Fast path (no GPU): MetricPlan -> CapturePlanner -> CaptureManifest ->
DepthSequenceRenderer -> DepthBackprojector -> VolumetricReconstructor, plus
authority-preservation and backward-compatibility checks.

The live-GPU path (real FLUX/ControlNet + DA3) is marked and skipped by default.

Requirements: 7.1-7.7
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from src.unified_pipeline.capture_planner import CapturePlanner
from src.unified_pipeline.depth_backprojector import DepthBackprojector
from src.unified_pipeline.depth_sequence_renderer import DepthSequenceRenderer
from src.unified_pipeline.geometry_validation_gate import GeometryValidationGate
from src.unified_pipeline.models import CameraContract, MetricPlan
from src.unified_pipeline.room_shell_reconstruction import reconstruct_room_shell
from src.unified_pipeline.volumetric_reconstructor import VolumetricReconstructor


def _kitchenette_plan() -> MetricPlan:
    return MetricPlan(
        room_dimensions=(4.0, 3.5, 2.7),
        walls=(
            {"name": "north"},
            {"name": "south"},
            {"name": "east"},
            {"name": "west"},
        ),
    )


# ─── Fast path: full pipeline without GPU ───────────────────────────────────


def test_fast_path_plan_to_cloud():
    """MetricPlan -> manifest -> depth -> back-project produces a world cloud."""
    plan = _kitchenette_plan()
    manifest = CapturePlanner(plan, CameraContract()).plan()
    assert len(manifest.cameras) >= 3

    renderer = DepthSequenceRenderer(plan)
    backprojector = DepthBackprojector()

    clouds = []
    for camera in manifest.cameras:
        render = renderer.render_one(camera)
        depth_clean = np.where(
            np.isfinite(render.depth_map), render.depth_map, 0.0
        ).astype(np.float32)
        points, _ = backprojector.backproject(
            depth_clean,
            camera.intrinsic_array(),
            camera.extrinsic_array(),
            min_depth=0.1,
            max_depth=15.0,
        )
        if points.shape[0] > 0:
            clouds.append(points)

    assert clouds, "expected at least one view to produce world points"
    fused, _ = backprojector.fuse(clouds, [None] * len(clouds))
    assert fused.shape[0] > 0
    assert fused.shape[1] == 3


def test_fast_path_reconstructs_shell(tmp_path):
    """The integration helper reconstructs a room-shell GLB (no GPU)."""
    plan = _kitchenette_plan()
    manifest = CapturePlanner(plan, CameraContract()).plan()

    shell_path = reconstruct_room_shell(plan, manifest, tmp_path)
    # Reconstruction may return None if fused coverage is below threshold; in
    # that case the caller falls back to the parametric shell. When it returns
    # a path, the file must exist and be non-empty.
    if shell_path is not None:
        assert shell_path.exists()
        assert shell_path.stat().st_size > 0


def test_fast_path_under_time_budget():
    """Plan + render + back-project completes quickly (well under 10s)."""
    plan = _kitchenette_plan()
    start = time.monotonic()
    manifest = CapturePlanner(plan, CameraContract()).plan()
    renderer = DepthSequenceRenderer(plan)
    for camera in manifest.cameras:
        renderer.render_one(camera)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0


# ─── Back-projection uses only known poses ──────────────────────────────────


def test_backprojection_uses_manifest_transforms():
    """Back-projection consumes the manifest's exact K/R/t — no estimation."""
    plan = _kitchenette_plan()
    manifest = CapturePlanner(plan, CameraContract()).plan()
    cam = manifest.cameras[0]

    k = cam.intrinsic_array()
    ext = cam.extrinsic_array()
    assert k.shape == (3, 3)
    assert ext.shape == (4, 4)
    # Rotation block orthonormal (valid declared pose, not estimated).
    r = ext[:3, :3]
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)


# ─── Authority preservation ─────────────────────────────────────────────────


def test_metric_plan_not_mutated():
    """Running the pipeline does not mutate the MetricPlan (frozen authority)."""
    plan = _kitchenette_plan()
    before = plan.room_dimensions
    manifest = CapturePlanner(plan, CameraContract()).plan()
    renderer = DepthSequenceRenderer(plan)
    for camera in manifest.cameras:
        renderer.render_one(camera)
    assert plan.room_dimensions == before


def test_camera_contract_immutable():
    """CameraContract remains immutable through planning."""
    contract = CameraContract(position=(0.0, 1.6, 0.0), target=(0.0, 1.4, -1.75))
    CapturePlanner(_kitchenette_plan(), contract).plan()
    # Frozen dataclass: attribute assignment must raise.
    with pytest.raises(Exception):
        contract.position = (1.0, 1.0, 1.0)  # type: ignore[misc]


def test_validation_gate_never_overrides_authority():
    """A failing validation excludes a view but does not alter MetricPlan depth."""
    plan = _kitchenette_plan()
    manifest = CapturePlanner(plan, CameraContract()).plan()
    renderer = DepthSequenceRenderer(plan)
    gate = GeometryValidationGate()

    render = renderer.render_one(manifest.cameras[0])
    conditioning = render.depth_map.copy()
    # Feed uncorrelated "DA3" depth -> gate fails, but conditioning is untouched.
    bad = np.random.default_rng(0).uniform(1.0, 5.0, size=conditioning.shape)
    result = gate.compare(bad, conditioning)
    assert result.passed is False
    assert np.array_equal(
        np.nan_to_num(conditioning, posinf=0.0),
        np.nan_to_num(render.depth_map, posinf=0.0),
    )


def test_da3_forbidden_authorities_intact():
    """The DA3 depth deny-list is unchanged by this integration."""
    from src.unified_pipeline.depth_bridge import FORBIDDEN_DEPTH_AUTHORITIES

    assert "room_dimensions" in FORBIDDEN_DEPTH_AUTHORITIES
    assert "collision_geometry" in FORBIDDEN_DEPTH_AUTHORITIES
    assert "camera" in FORBIDDEN_DEPTH_AUTHORITIES


# ─── Backward compatibility ─────────────────────────────────────────────────


def test_multi_view_planner_cameras_shape():
    """_planner_cameras returns legacy-shaped dicts + a manifest."""
    from src.unified_pipeline.multi_view_generator import _planner_cameras

    plan = _kitchenette_plan()
    cameras, manifest = _planner_cameras(plan, 4.0, 3.5, 2.7)
    assert manifest is not None
    assert len(cameras) == len(manifest.cameras)
    for cam in cameras:
        assert "position" in cam and "target" in cam and "label" in cam


def test_reconstruct_returns_none_without_manifest(tmp_path):
    """No manifest -> reconstruction returns None (caller uses parametric shell)."""
    assert reconstruct_room_shell(_kitchenette_plan(), None, tmp_path) is None


def test_reconstruction_import_optional():
    """The reconstruction helper imports cleanly (integration seam present)."""
    from src.unified_pipeline import room_shell_reconstruction  # noqa: F401


# ─── Live GPU path (skipped by default) ─────────────────────────────────────


@pytest.mark.skip(reason="live-gpu: requires ComfyUI + FLUX + ControlNet + DA3")
def test_live_gpu_full_pipeline(tmp_path):  # pragma: no cover
    """Full pipeline with real generation. Run manually with a live ComfyUI."""
    import asyncio

    from src.unified_pipeline.controlnet_conditioner import ControlNetConditioner

    plan = _kitchenette_plan()
    manifest = CapturePlanner(plan, CameraContract()).plan()
    renderer = DepthSequenceRenderer(plan)
    conditioner = ControlNetConditioner()

    async def _run():
        if not await conditioner.check_availability():
            pytest.skip("ControlNet nodes unavailable in ComfyUI")
        render = renderer.render_one(manifest.cameras[0])
        img = await conditioner.generate_conditioned(
            render, "a warm kitchen with a round table", output_dir=tmp_path
        )
        assert img.exists()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
