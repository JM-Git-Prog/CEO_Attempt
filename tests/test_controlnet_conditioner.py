"""Tests for ControlNetConditioner — depth-conditioned FLUX workflow building.

Covers workflow structure, depth normalization, node availability logic, and
strength wiring. Actual generation (live ComfyUI) is not exercised here.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.unified_pipeline.controlnet_conditioner import (
    REQUIRED_CONTROLNET_NODES,
    ControlNetConditioner,
    normalize_depth_for_controlnet,
)


# ─── Depth normalization ────────────────────────────────────────────────────


def test_depth_normalization_shape_and_dtype():
    depth = np.full((12, 16), 3.0, dtype=np.float32)
    img = normalize_depth_for_controlnet(depth)
    assert img.shape == (12, 16, 3)
    assert img.dtype == np.uint8


def test_depth_normalization_near_bright_far_dark():
    """Near surfaces map bright; far surfaces map dark (disparity convention)."""
    depth = np.array([[1.0, 14.0]], dtype=np.float32)  # near, far
    img = normalize_depth_for_controlnet(depth, far_clip_m=15.0)
    near_val = int(img[0, 0, 0])
    far_val = int(img[0, 1, 0])
    assert near_val > far_val


def test_depth_normalization_inf_is_background():
    """inf (no geometry) maps to the darkest value (far background)."""
    depth = np.array([[np.inf, 0.5]], dtype=np.float32)
    img = normalize_depth_for_controlnet(depth, far_clip_m=15.0)
    inf_val = int(img[0, 0, 0])
    near_val = int(img[0, 1, 0])
    assert inf_val < near_val
    assert inf_val == 0  # far_clip -> disparity 0 -> 0


def test_depth_normalization_range():
    depth = np.linspace(0.1, 15.0, 100, dtype=np.float32).reshape(10, 10)
    img = normalize_depth_for_controlnet(depth)
    assert img.min() >= 0
    assert img.max() <= 255


# ─── Workflow structure ─────────────────────────────────────────────────────


def test_workflow_has_controlnet_nodes():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "a warm kitchen")
    class_types = {node["class_type"] for node in wf.values()}
    for required in REQUIRED_CONTROLNET_NODES:
        assert required in class_types


def test_workflow_controlnet_wiring():
    """ControlNetApply consumes the positive conditioning, control net, and image."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt")
    apply_node = next(
        n for n in wf.values() if n["class_type"] == "ControlNetApply"
    )
    inputs = apply_node["inputs"]
    assert "conditioning" in inputs
    assert "control_net" in inputs
    assert "image" in inputs
    assert "strength" in inputs


def test_workflow_loads_depth_image():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("my_depth.png", "prompt")
    load_node = next(n for n in wf.values() if n["class_type"] == "LoadImage")
    assert load_node["inputs"]["image"] == "my_depth.png"


def test_strength_parameter_wired():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt", strength=0.65)
    apply_node = next(
        n for n in wf.values() if n["class_type"] == "ControlNetApply"
    )
    assert apply_node["inputs"]["strength"] == pytest.approx(0.65)


def test_strength_clamped():
    cond = ControlNetConditioner()
    wf_high = cond.build_workflow("d.png", "p", strength=1.5)
    wf_low = cond.build_workflow("d.png", "p", strength=-0.2)
    high = next(n for n in wf_high.values() if n["class_type"] == "ControlNetApply")
    low = next(n for n in wf_low.values() if n["class_type"] == "ControlNetApply")
    assert high["inputs"]["strength"] == pytest.approx(1.0)
    assert low["inputs"]["strength"] == pytest.approx(0.0)


def test_default_strength_used():
    cond = ControlNetConditioner(default_strength=0.75)
    wf = cond.build_workflow("depth.png", "prompt")
    apply_node = next(
        n for n in wf.values() if n["class_type"] == "ControlNetApply"
    )
    assert apply_node["inputs"]["strength"] == pytest.approx(0.75)


def test_workflow_dimensions():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt", width=512, height=384)
    latent = next(
        n for n in wf.values() if n["class_type"] == "EmptyFlux2LatentImage"
    )
    assert latent["inputs"]["width"] == 512
    assert latent["inputs"]["height"] == 384


# ─── Node availability ──────────────────────────────────────────────────────


def test_nodes_present_true():
    cond = ControlNetConditioner()
    info = {"ControlNetLoader": {}, "ControlNetApply": {}, "KSampler": {}}
    assert cond._controlnet_nodes_present(info) is True


def test_nodes_present_false_when_missing():
    cond = ControlNetConditioner()
    info = {"KSampler": {}, "UNETLoader": {}}  # no ControlNet nodes
    assert cond._controlnet_nodes_present(info) is False


def test_nodes_present_false_on_bad_payload():
    cond = ControlNetConditioner()
    assert cond._controlnet_nodes_present(None) is False  # type: ignore[arg-type]
    assert cond._controlnet_nodes_present([]) is False  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
