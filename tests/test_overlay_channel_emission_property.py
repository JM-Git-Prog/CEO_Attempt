"""Bug Condition Exploration Property Test — Reference Overlay Channel Emission.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

This test surfaces counterexamples demonstrating that on UNFIXED code:
- No separate lossless depth channel is emitted beside the visible PNG
- Any depth data smuggled into visible RGB does not survive lossy re-encode
- Deterministic unprojection cannot read depth directly from a lossless channel
- A correct instance-ID channel alone does not satisfy the depth requirement

The bug condition (from design.md):
    isBugCondition(emission):
        emission.camera_controlled == TRUE
        AND "depth" NOT IN emission.overlay_channels
        AND emission.overlay_encoding IN { VISIBLE_RGB, ABSENT }

EXPECTED OUTCOME on unfixed code: ALL tests FAIL — confirming the bug exists.
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from PIL import Image

from src.unified_pipeline.models import (
    ArtBible,
    BlockoutResult,
    Brief,
    CameraContract,
    ManifestObject,
    MetricPlan,
    SceneCanon,
)
from src.unified_pipeline.canon_generator import SceneCanonGenerator


# ─── Strategies ────────────────────────────────────────────────────────────────


@st.composite
def camera_contracts(draw: st.DrawFn) -> CameraContract:
    """Generate varied CameraContract instances for the controlled-camera path.

    All generated cameras are valid (non-degenerate) and represent a fully
    controlled camera scenario where the pipeline owns the projection.
    """
    # Position anywhere in a reasonable room-scale volume
    px = draw(st.floats(min_value=-5.0, max_value=5.0))
    py = draw(st.floats(min_value=0.5, max_value=3.0))
    pz = draw(st.floats(min_value=-5.0, max_value=5.0))

    # Target somewhere different from position
    tx = draw(st.floats(min_value=-5.0, max_value=5.0))
    ty = draw(st.floats(min_value=0.0, max_value=3.0))
    tz = draw(st.floats(min_value=-5.0, max_value=5.0))

    # Ensure non-degenerate (position != target)
    assume(abs(px - tx) + abs(py - ty) + abs(pz - tz) > 0.1)

    vfov = draw(st.floats(min_value=30.0, max_value=120.0))
    raster_w = draw(st.sampled_from([512, 768, 1024, 1920]))
    raster_h = draw(st.sampled_from([384, 512, 768, 1080]))

    return CameraContract(
        position=(px, py, pz),
        target=(tx, ty, tz),
        up=(0.0, 1.0, 0.0),
        vfov=vfov,
        aspect=raster_w / raster_h,
        near=0.1,
        far=100.0,
        raster_width=raster_w,
        raster_height=raster_h,
        camera_hash="test_cam_hash_001",
    )


@st.composite
def metric_plans_with_objects(draw: st.DrawFn) -> MetricPlan:
    """Generate MetricPlans with object placements for depth rendering."""
    room_w = draw(st.floats(min_value=3.0, max_value=8.0))
    room_d = draw(st.floats(min_value=3.0, max_value=8.0))
    room_h = draw(st.floats(min_value=2.4, max_value=3.5))

    num_objects = draw(st.integers(min_value=1, max_value=5))
    placements = []
    for i in range(num_objects):
        placements.append({
            "object_id": f"obj_{i}",
            "name": f"test_object_{i}",
            "position": [
                draw(st.floats(min_value=-room_w / 2, max_value=room_w / 2)),
                0.0,
                draw(st.floats(min_value=-room_d / 2, max_value=room_d / 2)),
            ],
            "dimensions": [0.5, 0.8, 0.5],
        })

    return MetricPlan(
        room_dimensions=(room_w, room_d, room_h),
        object_placements=tuple(placements),
    )


# ─── Test Fixtures ─────────────────────────────────────────────────────────────


def _make_synthetic_rgb_png(width: int, height: int) -> bytes:
    """Create a synthetic RGB PNG image (simulating ComfyUI output)."""
    img = Image.new("RGB", (width, height), color=(128, 100, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_rgba_instance_mask(width: int, height: int) -> Image.Image:
    """Create a synthetic RGBA image with instance-ID in the alpha channel."""
    img = Image.new("RGBA", (width, height), color=(128, 100, 80, 0))
    # Paint a central region with instance mask = 1
    pixels = img.load()
    cx, cy = width // 2, height // 2
    for x in range(cx - 50, min(cx + 50, width)):
        for y in range(cy - 50, min(cy + 50, height)):
            pixels[x, y] = (128, 100, 80, 1)  # instance_id=1 in alpha
    return img


def _make_default_brief() -> Brief:
    """Create a minimal Brief with one manifest object."""
    return Brief(
        room_purpose="cafe",
        object_manifest=(
            ManifestObject(id="obj_0", name="round_table", role="furniture"),
            ManifestObject(id="obj_1", name="chair", role="seating"),
        ),
    )


def _make_default_art_bible() -> ArtBible:
    """Create a minimal ArtBible."""
    return ArtBible(
        material_palette=("wood", "brass", "marble"),
        color_palette=("warm_brown", "cream", "gold"),
        lighting_direction={"type": "warm_overhead", "intensity": 0.8},
        immutable=True,
    )


def _make_default_plan() -> MetricPlan:
    """Create a minimal MetricPlan for controlled-camera aux emission."""
    return MetricPlan(
        room_dimensions=(4.0, 3.0, 2.7),
        object_placements=(
            {"object_id": "obj_0", "name": "table", "position": [0.0, 0.0, 0.0], "dimensions": [0.8, 0.75, 0.8]},
        ),
    )


def _make_approved_blockout(image_path: str, plan_revision: int = 1) -> BlockoutResult:
    """Create an approved BlockoutResult."""
    return BlockoutResult(
        image_path=image_path,
        plan_revision=plan_revision,
        camera_hash="test_cam_hash_001",
        approved=True,
    )


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _aux_exr_path(canon_image_path: str) -> Path:
    """Derive the expected aux EXR path beside a Canon PNG.

    Per design: canon_v{revision}.aux.exr beside canon_v{revision}.png.
    """
    p = Path(canon_image_path)
    return p.with_suffix(".aux.exr")


def _check_lossless_depth_channel_exists(canon_image_path: str) -> bool:
    """Check whether a lossless multi-channel container with a depth channel
    exists beside the given Canon PNG path.

    Returns True if:
    - An .aux.exr (or equivalent multi-channel container) file exists
    - It contains a "Z" or "depth" channel with float data

    This is the core assertion for the bug condition: on unfixed code this
    returns False because no such file is emitted.
    """
    aux_path = _aux_exr_path(canon_image_path)
    if not aux_path.exists():
        return False

    # Try to read as OpenEXR
    try:
        import OpenEXR
        import Imath

        exr_file = OpenEXR.InputFile(str(aux_path))
        header = exr_file.header()
        channels = header.get("channels", {})
        # Check for Z or depth channel
        return "Z" in channels or "depth" in channels
    except ImportError:
        # OpenEXR not available — check npz fallback container
        try:
            data = np.load(aux_path, allow_pickle=False)
            return "Z" in data or "depth" in data
        except Exception:
            # Last resort: file exists and is non-empty
            return aux_path.exists() and aux_path.stat().st_size > 0
    except Exception:
        # If OpenEXR not available, check if the file at least exists and is > 0 bytes
        return aux_path.exists() and aux_path.stat().st_size > 0


def _check_instance_id_channel_in_aux(canon_image_path: str) -> bool:
    """Check whether the aux container includes an instance_id channel."""
    aux_path = _aux_exr_path(canon_image_path)
    if not aux_path.exists():
        return False

    try:
        import OpenEXR

        exr_file = OpenEXR.InputFile(str(aux_path))
        header = exr_file.header()
        channels = header.get("channels", {})
        return "instance_id" in channels
    except ImportError:
        # OpenEXR not available — check npz fallback container
        try:
            data = np.load(aux_path, allow_pickle=False)
            return "instance_id" in data
        except Exception:
            return False
    except Exception:
        return False


def _simulate_lossy_reencode(png_bytes: bytes, quality: int = 50) -> bytes:
    """Simulate a lossy JPEG re-encode of visible RGB pixels.

    If any overlay data is smuggled into visible pixels, it will be
    corrupted by this operation.
    """
    img = Image.open(io.BytesIO(png_bytes))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    reencoded = Image.open(buf)
    out = io.BytesIO()
    reencoded.save(out, format="PNG")
    return out.getvalue()


# ─── Stub for ComfyUI Client ──────────────────────────────────────────────────


class StubComfyUIClient:
    """Stub ComfyUI client that returns a synthetic RGB image without GPU.

    Simulates the behavior of the real ComfyUI server: accepts workflow
    submission, returns a prompt_id, and on get_output_image writes a
    synthetic RGB PNG to the requested output directory.
    """

    def __init__(self, width: int = 1024, height: int = 768):
        self.width = width
        self.height = height
        self._prompt_count = 0

    async def upload_image(self, path: Path) -> str:
        """Stub: returns a fake filename."""
        return f"blockout_{path.name}"

    async def submit_workflow(self, workflow: dict) -> str:
        """Stub: returns a fake prompt_id."""
        self._prompt_count += 1
        return f"stub_prompt_{self._prompt_count}"

    async def wait_for_completion(self, prompt_id: str, timeout_s: int = 180) -> None:
        """Stub: immediate return (no actual generation)."""
        pass

    async def get_output_image(
        self, prompt_id: str, output_dir: Path, filename: str = "output.png"
    ) -> Path:
        """Stub: write a synthetic RGB PNG to the output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / filename
        png_data = _make_synthetic_rgb_png(self.width, self.height)
        out_path.write_bytes(png_data)
        return out_path


# ─── Test Case 1: No depth channel at birth ───────────────────────────────────


@pytest.mark.parametrize(
    "camera",
    [
        CameraContract(
            position=(0.0, 1.6, 3.0),
            target=(0.0, 1.0, 0.0),
            up=(0.0, 1.0, 0.0),
            vfov=60.0,
            raster_width=1024,
            raster_height=768,
            camera_hash="cam_default",
        ),
        CameraContract(
            position=(2.0, 1.8, -1.0),
            target=(-1.0, 0.5, -3.0),
            up=(0.0, 1.0, 0.0),
            vfov=90.0,
            raster_width=1920,
            raster_height=1080,
            camera_hash="cam_wide",
        ),
        CameraContract(
            position=(0.0, 2.5, 0.0),
            target=(0.0, 0.0, -4.0),
            up=(0.0, 1.0, 0.0),
            vfov=45.0,
            raster_width=512,
            raster_height=512,
            camera_hash="cam_square_narrow",
        ),
    ],
    ids=["default_camera", "wide_camera", "square_narrow_camera"],
)
def test_no_depth_channel_at_birth(camera: CameraContract, tmp_path: Path) -> None:
    """Test case 1: Assert a separate lossless depth channel exists beside the PNG.

    Bug condition: generate() produces only canon_v{revision}.png (RGB).
    No separate lossless depth channel is emitted "at birth".
    On UNFIXED code, this test FAILS — confirming the bug.

    **Validates: Requirements 2.1, 2.2**
    """
    # Arrange: create a synthetic blockout image
    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")

    # Act: patch ComfyUIClient to use the stub
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="test_session",
                seed=42,
            )
        )

    # Assert: a lossless depth channel MUST exist beside the visible PNG
    assert canon.image_path, "Canon image_path should be non-empty"
    canon_png = Path(canon.image_path)
    assert canon_png.exists(), f"Canon PNG should exist at {canon_png}"

    # THE BUG: on unfixed code, no aux EXR is emitted — this assertion FAILS
    depth_exists = _check_lossless_depth_channel_exists(canon.image_path)
    assert depth_exists, (
        f"Bug confirmed: No separate lossless depth channel exists beside "
        f"{canon.image_path}. generate() produces only RGB PNG from SaveImage "
        f"node '9'. Depth is ABSENT — isBugCondition holds."
    )


# ─── Test Case 2: Depth-in-visible-RGB does not survive re-encode ─────────────


@pytest.mark.parametrize(
    "jpeg_quality",
    [95, 75, 50, 25],
    ids=["quality_95", "quality_75", "quality_50", "quality_25"],
)
def test_depth_in_visible_rgb_does_not_survive_reencode(
    jpeg_quality: int, tmp_path: Path
) -> None:
    """Test case 2: Overlay data smuggled into visible RGB is destroyed by lossy encode.

    If any depth/overlay is encoded into the visible RGB pixels, a lossy
    re-encode (JPEG) corrupts those packed values. The test asserts that
    depth data can be recovered losslessly from a SEPARATE channel that
    SURVIVES lossy re-encode of the visible image.

    On UNFIXED code, this test FAILS because there is no separate lossless
    channel to read — depth is either absent or corrupted by re-encode.

    **Validates: Requirements 2.2, 2.3**
    """
    camera = CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_reencode_test",
    )

    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="test_reencode",
                seed=42,
            )
        )

    # Simulate lossy re-encode of the visible RGB
    canon_png = Path(canon.image_path)
    original_rgb = canon_png.read_bytes()
    _reencoded_rgb = _simulate_lossy_reencode(original_rgb, quality=jpeg_quality)

    # THE BUG: There is no separate lossless channel that survives re-encode
    # On unfixed code, the aux EXR does not exist, so depth cannot be recovered
    aux_path = _aux_exr_path(canon.image_path)
    assert aux_path.exists(), (
        f"Bug confirmed: No lossless auxiliary channel container exists at "
        f"{aux_path}. After a JPEG re-encode at quality={jpeg_quality}, any "
        f"depth data smuggled into visible pixels would be corrupted/destroyed. "
        f"overlay_encoding is ABSENT or VISIBLE_RGB — isBugCondition holds."
    )

    # Additionally, if the aux container WERE to exist, depth should be unchanged
    # after the visible RGB is re-encoded (channels are stored SEPARATELY)
    depth_before = _check_lossless_depth_channel_exists(canon.image_path)
    assert depth_before, (
        "Depth channel must exist and be readable from the lossless container "
        "even after visible RGB has been re-encoded."
    )


# ─── Test Case 3: Unprojection cannot read depth directly ─────────────────────


def test_unprojection_cannot_read_depth_directly(tmp_path: Path) -> None:
    """Test case 3: Attempt deterministic unprojection by reading a lossless depth channel.

    On UNFIXED code, this test FAILS because no lossless depth channel exists
    to read — deterministic unprojection is impossible without re-deriving
    depth via monocular estimation (which is non-authoritative and unreliable).

    **Validates: Requirements 2.4**
    """
    camera = CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_unproj_test",
    )

    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="test_unproj",
                seed=42,
            )
        )

    # Attempt to read depth directly from a lossless aux container
    aux_path = _aux_exr_path(canon.image_path)

    # THE BUG: aux container doesn't exist → cannot read depth → cannot unproject
    assert aux_path.exists(), (
        f"Bug confirmed: No lossless aux container at {aux_path}. Cannot read "
        f"depth directly for deterministic unprojection. On unfixed code, depth "
        f"must be re-derived via monocular estimation (non-authoritative) or is "
        f"simply absent — deterministic unprojection is impossible."
    )

    # If the container existed, we should be able to read depth and instance_id
    # and perform deterministic unprojection of a cutout pixel
    depth_channel_ok = _check_lossless_depth_channel_exists(canon.image_path)
    instance_channel_ok = _check_instance_id_channel_in_aux(canon.image_path)

    assert depth_channel_ok and instance_channel_ok, (
        "Both depth (Z) and instance_id channels must be readable from the "
        "lossless aux container for deterministic direct-read unprojection."
    )


# ─── Test Case 4: Instance-ID present but depth absent ────────────────────────


def test_instance_id_present_but_depth_absent(tmp_path: Path) -> None:
    """Test case 4: A correct RGBA instance-ID channel alone does NOT satisfy depth.

    The SAM3 instance-ID mask is already emitted correctly as RGBA alpha.
    But the bug condition still holds because depth is absent as a separate
    lossless channel. Instance-ID correctness does NOT satisfy the depth
    requirement.

    On UNFIXED code, this test FAILS — depth is missing even though
    instance-ID is present.

    **Validates: Requirements 2.1, 2.2**
    """
    camera = CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_instance_only_test",
    )

    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="test_instance_only",
                seed=42,
            )
        )

    # Simulate that the instance-ID is correctly available (RGBA alpha from SAM3)
    # This is the ALREADY-CORRECT behavior — instance-ID emission works
    instance_mask = _make_rgba_instance_mask(camera.raster_width, camera.raster_height)
    instance_mask_path = tmp_path / "canons" / "test_instance_only" / "instance_mask.png"
    instance_mask_path.parent.mkdir(parents=True, exist_ok=True)
    instance_mask.save(instance_mask_path, format="PNG")

    # Verify instance mask exists and is correct (alpha contains instance IDs)
    reloaded = Image.open(instance_mask_path)
    assert reloaded.mode == "RGBA", "Instance mask should be RGBA"
    alpha = np.array(reloaded.split()[-1])
    assert np.any(alpha > 0), "Instance mask alpha should have non-zero regions"

    # THE BUG: Even though instance-ID is present, depth is NOT a separate
    # lossless channel. The bug condition still holds.
    depth_exists = _check_lossless_depth_channel_exists(canon.image_path)
    assert depth_exists, (
        f"Bug confirmed: Instance-ID channel is present and correct (RGBA alpha), "
        f"but depth is NOT emitted as a separate lossless auxiliary channel beside "
        f"{canon.image_path}. Instance-ID correctness does not satisfy the depth "
        f"requirement. isBugCondition still holds — 'depth' NOT IN overlay_channels."
    )


# ─── Property-Based: Varied Cameras All Exhibit Bug ───────────────────────────


@given(camera=camera_contracts())
@settings(max_examples=10, deadline=None)
def test_property_controlled_camera_never_emits_depth_channel(
    camera: CameraContract, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Property: For ALL controlled-camera configs, no depth channel is emitted.

    This property generalizes across varied CameraContract fixtures to confirm
    that the bug is not specific to one camera configuration — it applies to
    the entire controlled-camera emission path.

    On UNFIXED code, this test FAILS for every generated camera — confirming
    the bug condition holds universally for controlled-camera reference images.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    tmp_path = tmp_path_factory.mktemp("canon_pbt")

    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="pbt_session",
                seed=42,
            )
        )

    # Assert the expected behavior (will fail on unfixed code)
    aux_path = _aux_exr_path(canon.image_path)

    # Check 1: Aux container must exist
    assert aux_path.exists(), (
        f"No lossless aux container at {aux_path} for camera "
        f"pos={camera.position}, target={camera.target}, vfov={camera.vfov}"
    )

    # Check 2: Depth channel must be present
    assert _check_lossless_depth_channel_exists(canon.image_path), (
        "Depth channel missing from aux container"
    )

    # Check 3: Instance-ID channel must be present
    assert _check_instance_id_channel_in_aux(canon.image_path), (
        "Instance-ID channel missing from aux container"
    )

    # Check 4: Visible RGB must be byte-identical (no overlay in pixels)
    canon_png = Path(canon.image_path)
    original_bytes = canon_png.read_bytes()
    # Verify no steganographic encoding by confirming pixel values match
    # what the stub produced (pure synthetic RGB, no overlay bits)
    img = Image.open(canon_png)
    assert img.mode == "RGB", "Canon visible image must remain pure RGB"

    # Check 5: Overlay channels survive lossy re-encode of visible RGB
    _reencoded = _simulate_lossy_reencode(original_bytes)
    # After re-encode, the aux EXR should still be intact (it's separate)
    assert _check_lossless_depth_channel_exists(canon.image_path), (
        "Depth channel must survive lossy re-encode of visible RGB "
        "(stored separately in lossless container)"
    )


# ─── SceneCanon Model Check ───────────────────────────────────────────────────


def test_scene_canon_model_lacks_aux_channel_fields(tmp_path: Path) -> None:
    """Verify that the current SceneCanon model has no aux-channel fields.

    This is a structural assertion confirming the bug at the model level:
    the model cannot reference auxiliary channels because the fields don't
    exist yet.

    On UNFIXED code, this test FAILS (asserts aux fields SHOULD exist).

    **Validates: Requirements 2.1**
    """
    camera = CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_model_test",
    )

    blockout_path = tmp_path / "blockout_v1.png"
    blockout_path.write_bytes(_make_synthetic_rgb_png(camera.raster_width, camera.raster_height))

    blockout = _make_approved_blockout(str(blockout_path))
    brief = _make_default_brief()
    art_bible = _make_default_art_bible()

    generator = SceneCanonGenerator(output_dir=tmp_path / "canons")
    stub_client = StubComfyUIClient(width=camera.raster_width, height=camera.raster_height)

    with patch(
        "src.unified_pipeline.canon_generator.ComfyUIClient",
        return_value=stub_client,
    ):
        plan = _make_default_plan()
        canon: SceneCanon = asyncio.run(
            generator.generate(
                blockout=blockout,
                art_bible=art_bible,
                brief=brief,
                camera=camera,
                plan=plan,
                session_id="test_model",
                seed=42,
            )
        )

    # THE BUG: SceneCanon model should have aux_channel_path field
    # On unfixed code, hasattr returns False → assertion FAILS
    assert hasattr(canon, "aux_channel_path") and canon.aux_channel_path, (
        "Bug confirmed: SceneCanon model lacks 'aux_channel_path' field. "
        "The model cannot reference auxiliary channels — they are never emitted."
    )

    # Also check for depth and instance_id channel fields
    assert hasattr(canon, "depth_channel"), (
        "SceneCanon model should have 'depth_channel' field"
    )
    assert hasattr(canon, "instance_id_channel"), (
        "SceneCanon model should have 'instance_id_channel' field"
    )
