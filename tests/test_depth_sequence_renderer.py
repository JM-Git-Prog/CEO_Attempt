"""Tests for the depth sequence renderer.

Verifies that DepthSequenceRenderer authors float32 depth maps from MetricPlan
geometry at each camera in a CaptureManifest, reusing render_controlled_depth.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.unified_pipeline.capture_planner import CapturePlanner
from src.unified_pipeline.depth_sequence_renderer import (
    DepthRender,
    DepthSequenceRenderer,
)
from src.unified_pipeline.models import CameraContract, MetricPlan


@pytest.fixture
def plan() -> MetricPlan:
    """A MetricPlan with a walled room so depth rasterization hits geometry."""
    return MetricPlan(
        room_dimensions=(4.0, 3.5, 2.7),
        walls=(
            {"name": "north"},
            {"name": "south"},
            {"name": "east"},
            {"name": "west"},
        ),
    )


@pytest.fixture
def manifest(plan: MetricPlan):
    """A CaptureManifest planned from the MetricPlan and default contract."""
    return CapturePlanner(plan, CameraContract()).plan()


@pytest.fixture
def renderer(plan: MetricPlan) -> DepthSequenceRenderer:
    return DepthSequenceRenderer(plan)


def _hero_camera(manifest):
    return manifest.hero() or manifest.cameras[0]


def test_render_one_shape(renderer, manifest):
    camera = _hero_camera(manifest)
    render = renderer.render_one(camera)

    assert isinstance(render, DepthRender)
    assert render.depth_map.dtype == np.float32
    assert render.depth_map.shape == (camera.raster_height, camera.raster_width)
    assert render.depth_map.shape == (768, 1024)


def test_render_one_depth_finite_somewhere(renderer, manifest):
    render = renderer.render_one(_hero_camera(manifest))
    assert np.isfinite(render.depth_map).any()


def test_render_one_depth_positive(renderer, manifest):
    render = renderer.render_one(_hero_camera(manifest))
    finite = render.depth_map[np.isfinite(render.depth_map)]
    assert finite.size > 0
    assert np.all(finite > 0)


def test_render_all_count(renderer, manifest):
    renders = renderer.render_all(manifest)
    assert len(renders) == len(manifest.cameras)
    assert all(isinstance(r, DepthRender) for r in renders)


def test_render_carries_provenance(renderer, manifest):
    camera = _hero_camera(manifest)
    render = renderer.render_one(camera)
    assert render.camera_hash != ""
    assert render.camera_label == camera.label


def test_save_writes_npy(renderer, manifest, tmp_path):
    render = renderer.render_one(_hero_camera(manifest))
    path = renderer.save(render, tmp_path)

    assert render.path != ""
    assert render.path == path
    saved = tmp_path / f"depth_{render.camera_label}.npy"
    assert saved.exists()

    loaded = np.load(str(saved))
    assert loaded.shape == render.depth_map.shape
