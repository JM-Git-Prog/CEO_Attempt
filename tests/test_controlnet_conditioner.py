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
    """ControlNetApplyAdvanced consumes positive/negative, control net, image."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt")
    apply_node = next(
        n for n in wf.values() if n["class_type"] == "ControlNetApplyAdvanced"
    )
    inputs = apply_node["inputs"]
    assert "positive" in inputs
    assert "negative" in inputs
    assert "control_net" in inputs
    assert "image" in inputs
    assert "strength" in inputs
    assert "end_percent" in inputs


def test_workflow_union_type_depth():
    """The promax union ControlNet is set to depth mode."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt")
    union = next(
        n for n in wf.values() if n["class_type"] == "SetUnionControlNetType"
    )
    assert union["inputs"]["type"] == "depth"


def test_workflow_uses_sdxl_checkpoint():
    """The workflow loads an SDXL checkpoint (not a FLUX UNet)."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt")
    ckpt = next(
        n for n in wf.values() if n["class_type"] == "CheckpointLoaderSimple"
    )
    assert ckpt["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"


def test_workflow_loads_depth_image():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("my_depth.png", "prompt")
    load_node = next(n for n in wf.values() if n["class_type"] == "LoadImage")
    assert load_node["inputs"]["image"] == "my_depth.png"


def _apply_node(wf):
    return next(
        n for n in wf.values() if n["class_type"] == "ControlNetApplyAdvanced"
    )


def test_strength_parameter_wired():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt", strength=0.65)
    assert _apply_node(wf)["inputs"]["strength"] == pytest.approx(0.65)


def test_strength_clamped():
    cond = ControlNetConditioner()
    wf_high = cond.build_workflow("d.png", "p", strength=1.5)
    wf_low = cond.build_workflow("d.png", "p", strength=-0.2)
    assert _apply_node(wf_high)["inputs"]["strength"] == pytest.approx(1.0)
    assert _apply_node(wf_low)["inputs"]["strength"] == pytest.approx(0.0)


def test_default_strength_used():
    cond = ControlNetConditioner(default_strength=0.75)
    wf = cond.build_workflow("depth.png", "prompt")
    assert _apply_node(wf)["inputs"]["strength"] == pytest.approx(0.75)


def test_default_strength_is_proven_value():
    """Default strength matches the proven geometry_injection.py value (0.45)."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt")
    assert _apply_node(wf)["inputs"]["strength"] == pytest.approx(0.45)
    assert _apply_node(wf)["inputs"]["end_percent"] == pytest.approx(0.6)


def test_workflow_dimensions():
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt", width=512, height=384)
    latent = next(
        n for n in wf.values() if n["class_type"] == "EmptyLatentImage"
    )
    assert latent["inputs"]["width"] == 512
    assert latent["inputs"]["height"] == 384


# ─── Node availability ──────────────────────────────────────────────────────


def test_nodes_present_true():
    cond = ControlNetConditioner()
    info = {
        "ControlNetLoader": {},
        "SetUnionControlNetType": {},
        "ControlNetApplyAdvanced": {},
        "KSampler": {},
    }
    assert cond._controlnet_nodes_present(info) is True


def test_nodes_present_false_when_missing():
    cond = ControlNetConditioner()
    info = {"KSampler": {}, "CheckpointLoaderSimple": {}}  # no ControlNet nodes
    assert cond._controlnet_nodes_present(info) is False


def test_nodes_present_false_on_bad_payload():
    cond = ControlNetConditioner()
    assert cond._controlnet_nodes_present(None) is False  # type: ignore[arg-type]
    assert cond._controlnet_nodes_present([]) is False  # type: ignore[arg-type]


# ─── Seed handling (regression: KSampler rejects seed < 0) ──────────────────


def test_workflow_seed_passthrough():
    """A valid non-negative seed is passed straight into the KSampler."""
    cond = ControlNetConditioner()
    wf = cond.build_workflow("depth.png", "prompt", seed=12345)
    ksampler = next(n for n in wf.values() if n["class_type"] == "KSampler")
    assert ksampler["inputs"]["seed"] == 12345


def test_live_seed_normalized_positive(monkeypatch):
    """generate_conditioned must convert seed=-1 to a positive seed.

    ComfyUI's KSampler enforces seed >= 0; passing -1 raises a 400. This test
    verifies the workflow submitted to the client carries a non-negative seed,
    without touching a live ComfyUI (client calls are stubbed).
    """
    import asyncio
    import types

    import numpy as np

    cond = ControlNetConditioner()
    captured = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def health_check(self):
            return True

        async def upload_image(self, p):
            return "cond.png"

        async def submit_workflow(self, wf, *a, **k):
            ksampler = next(
                n for n in wf.values() if n["class_type"] == "KSampler"
            )
            captured["seed"] = ksampler["inputs"]["seed"]
            return "pid-1"

        async def wait_for_completion(self, *a, **k):
            return None

        async def get_output_image(self, pid, out_dir, filename=""):
            from pathlib import Path

            p = Path(out_dir) / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"PNGDATA")
            return p

    monkeypatch.setattr(
        "src.photo_pipeline.comfyui_client.ComfyUIClient",
        lambda *a, **k: _FakeClient(),
    )

    render = types.SimpleNamespace(
        depth_map=np.full((768, 1024), 3.0, dtype=np.float32),
        camera_label="hero",
    )

    async def _run():
        return await cond.generate_conditioned(
            render, "prompt", seed=-1, output_dir="output/_seedtest"
        )

    asyncio.run(_run())
    assert captured["seed"] >= 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
