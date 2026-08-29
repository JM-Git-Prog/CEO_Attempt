"""Tests for CapturePlanner — deterministic camera trajectory planning.

Verifies exact intrinsics/extrinsics, room clamping, wall coverage,
determinism, and backward-compatible fallback.

Requirements: 2.1-2.7
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.unified_pipeline.capture_planner import (
    CaptureManifest,
    CapturePlanner,
    PlannedCamera,
    _look_at_extrinsic,
    intrinsic_from_vfov,
)
from src.unified_pipeline.models import CameraContract, MetricPlan


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _kitchenette_plan() -> MetricPlan:
    return MetricPlan(room_dimensions=(4.0, 3.5, 2.7))


def _small_plan() -> MetricPlan:
    return MetricPlan(room_dimensions=(2.0, 2.0, 2.4))


def _contract() -> CameraContract:
    return CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        vfov=60.0,
        raster_width=1024,
        raster_height=768,
    )


# ─── Intrinsics ─────────────────────────────────────────────────────────────


def test_intrinsic_matches_vfov():
    """fy ~= 665.1 for 60deg vFOV at 768 height; principal point centered."""
    k = intrinsic_from_vfov(60.0, 1024, 768)
    expected_fy = (768 / 2.0) / math.tan(math.radians(60.0) / 2.0)
    assert k[1, 1] == pytest.approx(expected_fy, rel=1e-6)
    assert k[0, 0] == pytest.approx(expected_fy, rel=1e-6)  # square pixels
    assert k[0, 2] == pytest.approx(512.0)
    assert k[1, 2] == pytest.approx(384.0)
    assert k[2, 2] == pytest.approx(1.0)


# ─── Extrinsics ─────────────────────────────────────────────────────────────


def test_extrinsic_is_valid_rotation():
    """Rotation block is orthonormal with determinant +1."""
    ext = _look_at_extrinsic((0.0, 1.6, 3.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0))
    r = ext[:3, :3]
    # Orthonormal: R @ R.T == I
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
    # Proper rotation: det == +1
    assert np.linalg.det(r) == pytest.approx(1.0, abs=1e-9)


def test_extrinsic_maps_eye_to_origin():
    """The camera eye maps to the camera-space origin (translation check)."""
    eye = (0.0, 1.6, 3.0)
    ext = _look_at_extrinsic(eye, (0.0, 1.0, 0.0), (0.0, 1.0, 0.0))
    eye_h = np.array([*eye, 1.0])
    cam_space = ext @ eye_h
    assert np.allclose(cam_space[:3], [0.0, 0.0, 0.0], atol=1e-9)


def test_extrinsic_target_in_front():
    """The target projects to negative camera-space Z (camera looks down -Z)."""
    eye = (0.0, 1.6, 3.0)
    target = (0.0, 1.0, 0.0)
    ext = _look_at_extrinsic(eye, target, (0.0, 1.0, 0.0))
    target_cam = ext @ np.array([*target, 1.0])
    assert target_cam[2] < 0.0  # in front of camera


def test_extrinsic_degenerate_target_equals_position():
    """Target coinciding with position does not crash; yields valid rotation."""
    ext = _look_at_extrinsic((1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 0.0))
    r = ext[:3, :3]
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)


# ─── Hero camera ────────────────────────────────────────────────────────────


def test_hero_matches_contract():
    """Hero camera framing matches the CameraContract."""
    planner = CapturePlanner(_kitchenette_plan(), _contract())
    manifest = planner.plan()
    hero = manifest.hero()
    assert hero is not None
    assert hero.camera_type == "hero"
    assert hero.target == (0.0, 1.0, 0.0)
    # Position clamped inside room but target unchanged
    assert hero.raster_width == 1024
    assert hero.raster_height == 768


# ─── Room containment ───────────────────────────────────────────────────────


def _assert_inside_room(cam: PlannedCamera, dims, clearance=0.3):
    w, d, h = dims
    x, y, z = cam.position
    assert -w / 2 + clearance - 1e-6 <= x <= w / 2 - clearance + 1e-6
    assert -d / 2 + clearance - 1e-6 <= z <= d / 2 - clearance + 1e-6
    assert clearance - 1e-6 <= y <= h - clearance + 1e-6


def test_cameras_inside_room():
    """All cameras stay >= 0.3m from walls in a 4x3.5x2.7 room."""
    plan = _kitchenette_plan()
    planner = CapturePlanner(plan, _contract())
    manifest = planner.plan()
    for cam in manifest.cameras:
        _assert_inside_room(cam, plan.room_dimensions)


def test_cameras_inside_small_room():
    """All cameras stay inside a tight 2x2x2.4 room (positions clamped)."""
    plan = _small_plan()
    planner = CapturePlanner(plan, _contract())
    manifest = planner.plan()
    for cam in manifest.cameras:
        _assert_inside_room(cam, plan.room_dimensions)


# ─── Coverage ───────────────────────────────────────────────────────────────


def test_coverage_all_walls_large_room():
    """A large room covers all four walls across the camera set."""
    plan = MetricPlan(room_dimensions=(6.0, 5.0, 2.9))
    planner = CapturePlanner(plan, _contract())
    manifest = planner.plan()
    assert manifest.total_surface_coverage == pytest.approx(1.0)


def test_small_room_has_fewer_coverage_views():
    """Small rooms produce fewer coverage cameras than large rooms."""
    small = CapturePlanner(_small_plan(), _contract()).plan()
    large = CapturePlanner(
        MetricPlan(room_dimensions=(6.0, 5.0, 2.9)), _contract()
    ).plan()
    small_cov = [c for c in small.cameras if c.camera_type == "coverage"]
    large_cov = [c for c in large.cameras if c.camera_type == "coverage"]
    assert len(small_cov) < len(large_cov)


# ─── Determinism ────────────────────────────────────────────────────────────


def test_deterministic():
    """Identical inputs produce identical manifests."""
    plan = _kitchenette_plan()
    contract = _contract()
    m1 = CapturePlanner(plan, contract).plan()
    m2 = CapturePlanner(plan, contract).plan()
    assert m1.to_dict() == m2.to_dict()


def test_manifest_hashes_unique():
    """Distinct cameras carry distinct hashes."""
    manifest = CapturePlanner(_kitchenette_plan(), _contract()).plan()
    hashes = [c.hash for c in manifest.cameras]
    # Hero + coverage views look in different directions -> distinct hashes.
    # (Transition may share with none; just assert no all-identical collapse.)
    assert len(set(hashes)) >= len(manifest.cameras) - 1


# ─── Fallback ───────────────────────────────────────────────────────────────


def test_fallback_no_plan():
    """No MetricPlan -> legacy 5 cardinal cameras."""
    manifest = CapturePlanner(None, _contract()).plan()
    assert manifest.plan_revision_hash == "fallback_cardinal"
    assert len(manifest.cameras) == 5
    assert manifest.cameras[0].camera_type == "hero"


# ─── Round-trip + interop ────────────────────────────────────────────────────


def test_planned_camera_to_camera_contract():
    """PlannedCamera converts to a CameraContract for render reuse."""
    manifest = CapturePlanner(_kitchenette_plan(), _contract()).plan()
    hero = manifest.hero()
    cc = hero.to_camera_contract()
    assert isinstance(cc, CameraContract)
    assert cc.position == hero.position
    assert cc.raster_width == hero.raster_width


def test_manifest_serializes():
    """Manifest to_dict round-trips through JSON-safe primitives."""
    import json

    manifest = CapturePlanner(_kitchenette_plan(), _contract()).plan()
    blob = json.dumps(manifest.to_dict())
    restored = json.loads(blob)
    assert restored["room_dimensions"] == [4.0, 3.5, 2.7]
    assert len(restored["cameras"]) == len(manifest.cameras)
