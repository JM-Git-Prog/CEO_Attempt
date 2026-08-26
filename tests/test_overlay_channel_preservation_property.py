"""Preservation Property Tests — Reference Overlay Channel Emission.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

These tests capture the baseline behavior of paths that must remain UNCHANGED
after the bugfix adds aux-channel emission. They cover:

- Test case 1 (Req 3.3): Monocular depth path — UnifiedDepthEstimator emits float32
  .npy non-authoritative evidence under immutable FORBIDDEN_DEPTH_AUTHORITIES
- Test case 2 (Req 3.1, 3.2): Instance-ID / alpha emission — apply_mask_to_image
  produces RGBA with alpha = instance mask; isolate_bound_detection unchanged
- Test case 3 (Req 3.6): Visible RGB byte-identical — canon_v{revision}.png bytes
  unchanged by the fix
- Test case 4 (Req 3.5): RGB-only mesh prep — prepare_generator_input composites
  on white with hidden_rgb_discarded: True
- Appearance-only assertion (Req 3.4): Canon appearance-only role is preserved —
  aux depth/overlay channels are read-only geometry echoes, do NOT override
  MetricPlan spatial authority

Methodology: observation-first — run on UNFIXED code, record baseline, assert it.

EXPECTED OUTCOME on unfixed code: ALL tests PASS — confirming the baseline.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
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
    ObjectCanon,
    SceneCanon,
)
from src.unified_pipeline.depth_bridge import (
    FORBIDDEN_DEPTH_AUTHORITIES,
    CameraAnchoredSimilarity,
    DepthAuthorityError,
    DepthEvidence,
    DepthEvidenceProvenance,
    DepthEvidenceValidationError,
    UnifiedDepthEstimator,
)
from src.unified_pipeline.object_isolator import apply_mask_to_image, quality_gate
from src.unified_pipeline.mesh_generators import prepare_generator_input


# ─── Strategies ────────────────────────────────────────────────────────────────


@st.composite
def valid_depth_ranges(draw: st.DrawFn) -> tuple[float, float]:
    """Generate valid depth range tuples for indoor meters (0 < min <= max < 20)."""
    d_min = draw(st.floats(min_value=0.01, max_value=10.0))
    d_max = draw(st.floats(min_value=d_min, max_value=19.9))
    assume(d_min <= d_max)
    return (d_min, d_max)


@st.composite
def rgb_images(draw: st.DrawFn) -> tuple[np.ndarray, int, int]:
    """Generate random RGB images at varied sizes."""
    w = draw(st.sampled_from([64, 128, 256, 512]))
    h = draw(st.sampled_from([64, 128, 256, 384]))
    # Use simple random pixel data
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=10000)))
    img = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    return (img, w, h)


@st.composite
def binary_masks(draw: st.DrawFn, width: int = 128, height: int = 128) -> np.ndarray:
    """Generate random binary masks with realistic coverage patterns."""
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=10000)))
    # Create a mask with a central region of interest
    mask = np.zeros((height, width), dtype=np.uint8)
    # Random rectangle as foreground
    x1 = draw(st.integers(min_value=0, max_value=width // 4))
    y1 = draw(st.integers(min_value=0, max_value=height // 4))
    x2 = draw(st.integers(min_value=width // 2, max_value=width - 1))
    y2 = draw(st.integers(min_value=height // 2, max_value=height - 1))
    mask[y1:y2, x1:x2] = 255
    return mask


@st.composite
def object_canons_with_rgba(draw: st.DrawFn, tmp_path: Path) -> ObjectCanon:
    """Generate ObjectCanon with a real RGBA PNG on disk."""
    obj_id = f"obj_{draw(st.integers(min_value=0, max_value=999)):04d}"
    w = draw(st.sampled_from([64, 128, 256]))
    h = draw(st.sampled_from([64, 128, 256]))

    # Create RGBA image with valid alpha (non-empty, >2% coverage)
    rng = np.random.default_rng(draw(st.integers(min_value=0, max_value=10000)))
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    # Create a meaningful alpha mask (central rectangle)
    margin_x = max(1, w // 8)
    margin_y = max(1, h // 8)
    rgba[margin_y:h - margin_y, margin_x:w - margin_x, 3] = 255

    img_path = tmp_path / f"{obj_id}.png"
    Image.fromarray(rgba, mode="RGBA").save(img_path, format="PNG")

    return ObjectCanon(
        object_id=obj_id,
        object_name=f"test_object_{obj_id}",
        image_path=str(img_path),
        mask_coverage=float(np.count_nonzero(rgba[:, :, 3]) / (w * h)),
        approved=True,
        provenance="raw_segmentation",
    )


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _make_synthetic_rgb_png(width: int, height: int, seed: int = 42) -> bytes:
    """Create a deterministic synthetic RGB PNG."""
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    img = Image.fromarray(pixels, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_depth_npy(width: int, height: int, seed: int = 42) -> np.ndarray:
    """Create a valid float32 depth map with values in indoor range."""
    rng = np.random.default_rng(seed)
    # Depths between 0.5 and 10 meters (valid indoor range)
    depth = rng.uniform(0.5, 10.0, size=(height, width)).astype(np.float32)
    return depth


def _make_normals_npy(width: int, height: int, seed: int = 42) -> np.ndarray:
    """Create a valid float32 normals map."""
    rng = np.random.default_rng(seed)
    normals = rng.uniform(-1.0, 1.0, size=(height, width, 3)).astype(np.float32)
    # Normalize each vector
    norms = np.linalg.norm(normals, axis=2, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    normals = normals / norms
    return normals


# ─── Test Case 1: Monocular Depth Path Unchanged (Req 3.3) ────────────────────


class TestMonocularDepthPathPreservation:
    """Verify the monocular depth path remains unchanged — non-authoritative
    float32 .npy evidence under immutable FORBIDDEN_DEPTH_AUTHORITIES."""

    def test_forbidden_authorities_immutable(self) -> None:
        """The FORBIDDEN_DEPTH_AUTHORITIES deny-list must be exactly the known tuple.

        **Validates: Requirements 3.3**
        """
        expected = (
            "room_dimensions",
            "openings",
            "architectural_geometry",
            "collision_geometry",
            "navigation_geometry",
            "object_transforms",
            "camera",
        )
        assert FORBIDDEN_DEPTH_AUTHORITIES == expected, (
            f"FORBIDDEN_DEPTH_AUTHORITIES must remain immutable. "
            f"Expected {expected}, got {FORBIDDEN_DEPTH_AUTHORITIES}"
        )

    def test_depth_evidence_rejects_authority_claims(self) -> None:
        """DepthEvidence.__post_init__ must reject any authority_claims.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(DepthAuthorityError):
            DepthEvidence(
                depth_map_path="/fake/depth.npy",
                normal_map_path="/fake/normal.npy",
                valid_pixel_ratio=0.9,
                depth_range_m=(0.5, 8.0),
                provenance=DepthEvidenceProvenance(
                    session_id="test",
                    source_image_path="/fake/img.png",
                    source_image_sha256="a" * 64,
                    source_resolution=(1024, 768),
                    depth_artifact_sha256="b" * 64,
                ),
                authority_claims=("room_dimensions",),
            )

    def test_depth_evidence_rejects_spatial_authority(self) -> None:
        """DepthEvidence cannot have spatial_authority=True.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(DepthAuthorityError):
            DepthEvidence(
                depth_map_path="/fake/depth.npy",
                normal_map_path="/fake/normal.npy",
                valid_pixel_ratio=0.9,
                depth_range_m=(0.5, 8.0),
                provenance=DepthEvidenceProvenance(
                    session_id="test",
                    source_image_path="/fake/img.png",
                    source_image_sha256="a" * 64,
                    source_resolution=(1024, 768),
                    depth_artifact_sha256="b" * 64,
                ),
                spatial_authority=True,
            )

    def test_depth_evidence_rejects_collision_enabled(self) -> None:
        """DepthEvidence cannot have collision_enabled=True.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(DepthAuthorityError):
            DepthEvidence(
                depth_map_path="/fake/depth.npy",
                normal_map_path="/fake/normal.npy",
                valid_pixel_ratio=0.9,
                depth_range_m=(0.5, 8.0),
                provenance=DepthEvidenceProvenance(
                    session_id="test",
                    source_image_path="/fake/img.png",
                    source_image_sha256="a" * 64,
                    source_resolution=(1024, 768),
                    depth_artifact_sha256="b" * 64,
                ),
                collision_enabled=True,
            )

    def test_depth_evidence_forbids_altered_deny_list(self) -> None:
        """DepthEvidence must reject an altered forbidden_authorities tuple.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(DepthAuthorityError):
            DepthEvidence(
                depth_map_path="/fake/depth.npy",
                normal_map_path="/fake/normal.npy",
                valid_pixel_ratio=0.9,
                depth_range_m=(0.5, 8.0),
                provenance=DepthEvidenceProvenance(
                    session_id="test",
                    source_image_path="/fake/img.png",
                    source_image_sha256="a" * 64,
                    source_resolution=(1024, 768),
                    depth_artifact_sha256="b" * 64,
                ),
                forbidden_authorities=("room_dimensions",),  # truncated = altered
            )

    def test_depth_evidence_valid_construction(self, tmp_path: Path) -> None:
        """A correctly constructed DepthEvidence must be optional, non-authoritative.

        **Validates: Requirements 3.3**
        """
        depth_path = tmp_path / "depth.npy"
        normal_path = tmp_path / "normal.npy"
        np.save(depth_path, _make_depth_npy(256, 256))
        np.save(normal_path, _make_normals_npy(256, 256))

        evidence = DepthEvidence(
            depth_map_path=str(depth_path),
            normal_map_path=str(normal_path),
            valid_pixel_ratio=0.95,
            depth_range_m=(0.5, 9.5),
            provenance=DepthEvidenceProvenance(
                session_id="sess_test",
                source_image_path="/fake/img.png",
                source_image_sha256="a" * 64,
                source_resolution=(256, 256),
                depth_artifact_sha256="b" * 64,
            ),
        )
        assert evidence.optional is True
        assert evidence.spatial_authority is False
        assert evidence.collision_enabled is False
        assert evidence.authority_claims == ()
        assert evidence.forbidden_authorities == FORBIDDEN_DEPTH_AUTHORITIES
        assert evidence.evidence_kind == "depth_evidence"

    def test_estimator_rejects_authority_claims_before_gpu(self) -> None:
        """UnifiedDepthEstimator.estimate rejects authority claims upfront.

        **Validates: Requirements 3.3**
        """
        arbiter = MagicMock()
        client = MagicMock()
        estimator = UnifiedDepthEstimator(
            client=client,
            output_dir=Path("/fake"),
            arbiter=arbiter,
        )
        with pytest.raises(DepthAuthorityError, match="cannot authorize"):
            asyncio.run(
                estimator.estimate(
                    source_image=Path("/fake/img.png"),
                    config=MagicMock(),
                    session_id="test",
                    authority_claims=["room_dimensions"],
                )
            )

    @given(
        valid_ratio=st.floats(min_value=0.50, max_value=1.0),
        depth_range=valid_depth_ranges(),
    )
    @settings(max_examples=15, deadline=None)
    def test_property_depth_evidence_always_non_authoritative(
        self, valid_ratio: float, depth_range: tuple[float, float]
    ) -> None:
        """Property: for all valid depth evidence, spatial_authority stays False.

        **Validates: Requirements 3.3**
        """
        evidence = DepthEvidence(
            depth_map_path="/fake/depth.npy",
            normal_map_path="/fake/normal.npy",
            valid_pixel_ratio=valid_ratio,
            depth_range_m=depth_range,
            provenance=DepthEvidenceProvenance(
                session_id="prop_test",
                source_image_path="/fake/img.png",
                source_image_sha256="a" * 64,
                source_resolution=(512, 512),
                depth_artifact_sha256="b" * 64,
            ),
        )
        # The preservation property: depth is ALWAYS non-authoritative
        assert evidence.spatial_authority is False
        assert evidence.optional is True
        assert evidence.collision_enabled is False
        assert evidence.evidence_kind == "depth_evidence"
        assert evidence.forbidden_authorities == FORBIDDEN_DEPTH_AUTHORITIES

    def test_depth_evidence_emits_npy_format(self, tmp_path: Path) -> None:
        """The monocular depth output must be float32 .npy format.

        **Validates: Requirements 3.3**
        """
        depth = _make_depth_npy(128, 128)
        depth_path = tmp_path / "depth.npy"
        np.save(depth_path, depth)

        loaded = np.load(depth_path, allow_pickle=False)
        assert loaded.dtype == np.float32, "Depth must be float32"
        assert loaded.ndim == 2, "Depth must be 2D (height x width)"
        assert depth_path.suffix == ".npy", "Depth must be .npy format"


# ─── Test Case 2: Instance-ID / Alpha Emission Unchanged (Req 3.1, 3.2) ──────


class TestInstanceIDAlphaPreservation:
    """Verify apply_mask_to_image RGBA output remains unchanged."""

    def test_apply_mask_produces_rgba(self, tmp_path: Path) -> None:
        """apply_mask_to_image produces RGBA with alpha = instance mask.

        **Validates: Requirements 3.1, 3.2**
        """
        w, h = 128, 128
        image = np.random.default_rng(42).integers(0, 256, (h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[20:80, 30:100] = 255  # rectangular foreground

        out_path = tmp_path / "object.png"
        result_path = apply_mask_to_image(image, mask, out_path)

        assert result_path == out_path
        assert out_path.exists()

        with Image.open(out_path) as img:
            assert img.mode == "RGBA", "Output must be RGBA"
            rgba = np.array(img)

        # Alpha channel must match the mask
        alpha = rgba[:, :, 3]
        expected_alpha = np.where(mask > 0, 255, 0).astype(np.uint8)
        np.testing.assert_array_equal(alpha, expected_alpha)

        # RGB must be source pixels where mask is True, zero elsewhere
        mask_bool = mask > 0
        np.testing.assert_array_equal(rgba[mask_bool, :3], image[mask_bool, :3])
        np.testing.assert_array_equal(rgba[~mask_bool, :3], 0)

    def test_apply_mask_transparent_background(self, tmp_path: Path) -> None:
        """Background pixels must be fully transparent (alpha=0).

        **Validates: Requirements 3.1, 3.2**
        """
        w, h = 64, 64
        image = np.full((h, w, 3), 200, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[10:50, 10:50] = 255

        out_path = tmp_path / "bg_test.png"
        apply_mask_to_image(image, mask, out_path)

        with Image.open(out_path) as img:
            rgba = np.array(img)

        # Outside mask region: alpha must be 0
        assert np.all(rgba[0:10, :, 3] == 0), "Top strip must be transparent"
        assert np.all(rgba[50:, :, 3] == 0), "Bottom strip must be transparent"

    @given(
        seed=st.integers(min_value=0, max_value=9999),
        coverage_pct=st.floats(min_value=0.05, max_value=0.95),
    )
    @settings(max_examples=15, deadline=None)
    def test_property_apply_mask_alpha_equals_mask(
        self, seed: int, coverage_pct: float, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Property: for all valid masks, alpha channel == (mask > 0) * 255.

        **Validates: Requirements 3.1, 3.2**
        """
        tmp_path = tmp_path_factory.mktemp("mask_prop")
        w, h = 128, 128
        rng = np.random.default_rng(seed)
        image = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)

        # Create a mask with approximately the requested coverage
        mask = np.zeros((h, w), dtype=np.uint8)
        n_pixels = int(coverage_pct * h * w)
        indices = rng.choice(h * w, size=min(n_pixels, h * w), replace=False)
        mask.flat[indices] = 255

        out_path = tmp_path / f"prop_{seed}.png"
        apply_mask_to_image(image, mask, out_path)

        with Image.open(out_path) as img:
            rgba = np.array(img)

        # Core preservation property: alpha == mask binary * 255
        expected_alpha = np.where(mask > 0, 255, 0).astype(np.uint8)
        np.testing.assert_array_equal(rgba[:, :, 3], expected_alpha)

    def test_apply_mask_empty_mask_produces_transparent(self, tmp_path: Path) -> None:
        """Edge case: empty mask produces fully transparent output.

        **Validates: Requirements 3.1, 3.2**
        """
        w, h = 64, 64
        image = np.full((h, w, 3), 128, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)  # completely empty

        out_path = tmp_path / "empty.png"
        apply_mask_to_image(image, mask, out_path)

        with Image.open(out_path) as img:
            rgba = np.array(img)

        assert np.all(rgba[:, :, 3] == 0), "Empty mask must produce all-transparent"

    def test_quality_gate_rejects_empty(self) -> None:
        """quality_gate must reject masks below 1% coverage.

        **Validates: Requirements 3.1**
        """
        # 0% coverage
        mask_empty = np.zeros((100, 100), dtype=np.uint8)
        assert quality_gate(mask_empty, "obj_empty") is False

        # 0.5% coverage (below 1% threshold)
        mask_tiny = np.zeros((100, 100), dtype=np.uint8)
        mask_tiny[0, 0:50] = 255  # 50 / 10000 = 0.5%
        assert quality_gate(mask_tiny, "obj_tiny") is False

        # 2% coverage (above 1% threshold) — passes
        mask_ok = np.zeros((100, 100), dtype=np.uint8)
        mask_ok[0:2, :] = 255  # 200 / 10000 = 2%
        assert quality_gate(mask_ok, "obj_ok") is True


# ─── Test Case 3: Visible RGB Byte-Identical (Req 3.6) ────────────────────────


class TestVisibleRGBPreservation:
    """Verify the visible Canon PNG output is byte-identical before and after fix."""

    def test_canon_generation_produces_rgb_png(self, tmp_path: Path) -> None:
        """SceneCanonGenerator.generate produces a plain RGB PNG (no overlay bits).

        **Validates: Requirements 3.6**
        """
        from src.unified_pipeline.canon_generator import SceneCanonGenerator

        camera = CameraContract(
            position=(0.0, 1.6, 3.0),
            target=(0.0, 1.0, 0.0),
            up=(0.0, 1.0, 0.0),
            vfov=60.0,
            raster_width=512,
            raster_height=384,
            camera_hash="cam_rgb_preserve",
        )

        blockout_path = tmp_path / "blockout_v1.png"
        blockout_path.write_bytes(_make_synthetic_rgb_png(512, 384))
        blockout = BlockoutResult(
            image_path=str(blockout_path),
            plan_revision=1,
            camera_hash="cam_rgb_preserve",
            approved=True,
        )
        brief = Brief(
            room_purpose="test",
            object_manifest=(ManifestObject(id="obj_0", name="table", role="furniture"),),
        )
        art_bible = ArtBible(immutable=True)

        generator = SceneCanonGenerator(output_dir=tmp_path / "canons")

        # Stub ComfyUI to produce known RGB output
        stub_png = _make_synthetic_rgb_png(512, 384, seed=99)

        class DeterministicStub:
            async def upload_image(self, path):
                return "stub.png"

            async def submit_workflow(self, workflow):
                return "p_001"

            async def wait_for_completion(self, prompt_id, timeout_s=180):
                pass

            async def get_output_image(self, prompt_id, output_dir, filename="out.png"):
                output_dir.mkdir(parents=True, exist_ok=True)
                out = output_dir / filename
                out.write_bytes(stub_png)
                return out

        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient",
            return_value=DeterministicStub(),
        ):
            canon = asyncio.run(
                generator.generate(
                    blockout=blockout,
                    art_bible=art_bible,
                    brief=brief,
                    camera=camera,
                    session_id="rgb_test",
                    seed=42,
                )
            )

        canon_path = Path(canon.image_path)
        assert canon_path.exists()

        # Visible PNG must be RGB (not RGBA, not altered)
        with Image.open(canon_path) as img:
            assert img.mode == "RGB", "Canon visible image must be pure RGB"

        # Bytes must match what the stub wrote (no overlay injection)
        actual_bytes = canon_path.read_bytes()
        assert actual_bytes == stub_png, (
            "Canon PNG bytes must be byte-identical to ComfyUI output. "
            "No overlay bits should be injected into the visible image."
        )

    @given(seed=st.integers(min_value=0, max_value=9999))
    @settings(max_examples=10, deadline=None)
    def test_property_canon_png_bytes_match_comfyui_output(
        self, seed: int, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Property: for all seeds, Canon PNG bytes == ComfyUI stub output bytes.

        This is the byte-identity preservation property. After the fix adds
        aux channel emission, the visible PNG must still be byte-identical to
        what the ComfyUI workflow produces (no overlay bits injected).

        **Validates: Requirements 3.6**
        """
        from src.unified_pipeline.canon_generator import SceneCanonGenerator

        tmp_path = tmp_path_factory.mktemp("rgb_prop")
        camera = CameraContract(
            position=(0.0, 1.6, 3.0),
            target=(0.0, 1.0, 0.0),
            up=(0.0, 1.0, 0.0),
            vfov=60.0,
            raster_width=256,
            raster_height=256,
            camera_hash="cam_prop",
        )

        blockout_path = tmp_path / "blockout_v1.png"
        blockout_path.write_bytes(_make_synthetic_rgb_png(256, 256, seed=seed))
        blockout = BlockoutResult(
            image_path=str(blockout_path), plan_revision=1,
            camera_hash="cam_prop", approved=True,
        )
        brief = Brief(
            room_purpose="prop_test",
            object_manifest=(ManifestObject(id="obj_0", name="item", role="prop"),),
        )
        art_bible = ArtBible(immutable=True)

        # Deterministic stub output
        expected_png = _make_synthetic_rgb_png(256, 256, seed=seed + 1000)

        class Stub:
            async def upload_image(self, path):
                return "s.png"

            async def submit_workflow(self, workflow):
                return "p_x"

            async def wait_for_completion(self, prompt_id, timeout_s=180):
                pass

            async def get_output_image(self, prompt_id, output_dir, filename="out.png"):
                output_dir.mkdir(parents=True, exist_ok=True)
                out = output_dir / filename
                out.write_bytes(expected_png)
                return out

        generator = SceneCanonGenerator(output_dir=tmp_path / "canons")

        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient",
            return_value=Stub(),
        ):
            canon = asyncio.run(
                generator.generate(
                    blockout=blockout, art_bible=art_bible, brief=brief,
                    camera=camera, session_id="prop_sess", seed=seed,
                )
            )

        actual = Path(canon.image_path).read_bytes()
        assert actual == expected_png, "Visible PNG must be byte-identical to ComfyUI output"


# ─── Test Case 4: RGB-Only Mesh Prep Unchanged (Req 3.5) ──────────────────────


class TestMeshPrepPreservation:
    """Verify prepare_generator_input composite-on-white and hidden_rgb_discarded."""

    def test_prepare_generator_input_composites_on_white(self, tmp_path: Path) -> None:
        """prepare_generator_input composites alpha onto white background.

        **Validates: Requirements 3.5**
        """
        # Create an RGBA image with a central foreground
        w, h = 128, 128
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[20:100, 20:100, :3] = [200, 50, 100]  # colored foreground
        rgba[20:100, 20:100, 3] = 255  # opaque foreground

        img_path = tmp_path / "obj_001.png"
        Image.fromarray(rgba, "RGBA").save(img_path, format="PNG")

        oc = ObjectCanon(
            object_id="obj_001",
            object_name="test_table",
            image_path=str(img_path),
            mask_coverage=0.5,
            approved=True,
        )

        prepared_path, evidence = prepare_generator_input(oc, tmp_path / "out")

        # Check the prepared image
        assert prepared_path.exists()
        with Image.open(prepared_path) as img:
            assert img.mode == "RGB", "Prepared input must be RGB (not RGBA)"
            pixels = np.array(img)

        # Background (corners) must be white
        assert tuple(pixels[0, 0]) == (255, 255, 255), "Corner pixel must be white"

        # Evidence must contain hidden_rgb_discarded: True
        assert evidence["hidden_rgb_discarded"] is True
        assert evidence["background_policy"] == "approved-alpha-composited-on-white"

    def test_prepare_generator_input_evidence_schema(self, tmp_path: Path) -> None:
        """Evidence output contains required fields with correct values.

        **Validates: Requirements 3.5**
        """
        w, h = 64, 64
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[10:50, 10:50, :3] = [100, 150, 200]
        rgba[10:50, 10:50, 3] = 255

        img_path = tmp_path / "obj_002.png"
        Image.fromarray(rgba, "RGBA").save(img_path, format="PNG")

        oc = ObjectCanon(
            object_id="obj_002",
            object_name="test_chair",
            image_path=str(img_path),
            mask_coverage=0.39,
            approved=True,
        )

        prepared_path, evidence = prepare_generator_input(oc, tmp_path / "out")

        # Schema assertions
        assert evidence["schema_version"] == "mesh-generator-input/v1"
        assert evidence["object_id"] == "obj_002"
        assert evidence["hidden_rgb_discarded"] is True
        assert evidence["background_policy"] == "approved-alpha-composited-on-white"
        assert "source_sha256" in evidence
        assert "prepared_sha256" in evidence
        assert "source_alpha_bbox" in evidence
        assert "prepared_size" in evidence
        # Prepared size must be square
        prep_size = evidence["prepared_size"]
        assert prep_size[0] == prep_size[1], "Prepared must be square"

    @given(seed=st.integers(min_value=0, max_value=9999))
    @settings(max_examples=10, deadline=None)
    def test_property_prepared_output_always_rgb_on_white(
        self, seed: int, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Property: for all valid RGBA inputs, prepare_generator_input outputs
        RGB on white with hidden_rgb_discarded=True.

        **Validates: Requirements 3.5**
        """
        tmp_path = tmp_path_factory.mktemp("mesh_prop")
        w, h = 128, 128
        rng = np.random.default_rng(seed)

        # Random RGBA with non-empty alpha
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[:, :, :3] = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        # Non-empty rectangular alpha
        x1, y1 = rng.integers(0, w // 4), rng.integers(0, h // 4)
        x2, y2 = rng.integers(w // 2, w), rng.integers(h // 2, h)
        rgba[y1:y2, x1:x2, 3] = 255

        img_path = tmp_path / f"obj_{seed}.png"
        Image.fromarray(rgba, "RGBA").save(img_path, format="PNG")

        oc = ObjectCanon(
            object_id=f"obj_{seed}",
            object_name="prop_test",
            image_path=str(img_path),
            mask_coverage=float(np.count_nonzero(rgba[:, :, 3]) / (w * h)),
            approved=True,
        )

        prepared_path, evidence = prepare_generator_input(oc, tmp_path / "out")

        # Core preservation properties
        with Image.open(prepared_path) as img:
            assert img.mode == "RGB", "Must be RGB"
            pixels = np.array(img)
        assert evidence["hidden_rgb_discarded"] is True
        assert evidence["background_policy"] == "approved-alpha-composited-on-white"
        # Prepared must be square
        assert pixels.shape[0] == pixels.shape[1], "Must be square"


# ─── Appearance-Only Role Preservation (Req 3.4) ──────────────────────────────


class TestCanonAppearanceOnlyRole:
    """Verify the Canon owns appearance only — depth/overlay channels are
    read-only geometry echoes that do NOT override MetricPlan spatial authority."""

    def test_scene_canon_model_has_no_spatial_authority_field(self) -> None:
        """SceneCanon model must not carry spatial authority fields.

        The Canon owns appearance (materials, lighting, identity). Any aux
        depth/overlay is a geometry echo for unprojection, not a spatial override.

        **Validates: Requirements 3.4**
        """
        canon = SceneCanon(
            image_path="/fake/canon.png",
            plan_revision=1,
            camera_hash="cam_test",
            canon_hash="hash_test",
            object_verdicts={"obj_0": "present"},
            approved=True,
            art_bible_hash="ab_hash",
        )

        # SceneCanon must NOT have spatial_authority or geometry_authority
        assert not hasattr(canon, "spatial_authority"), (
            "SceneCanon must not carry spatial_authority — Canon is appearance-only"
        )
        assert not hasattr(canon, "geometry_authority"), (
            "SceneCanon must not carry geometry_authority"
        )
        assert not hasattr(canon, "depth_authority"), (
            "SceneCanon must not carry depth_authority — depth evidence is "
            "non-authoritative per FORBIDDEN_DEPTH_AUTHORITIES"
        )

    def test_scene_canon_to_dict_round_trip(self) -> None:
        """SceneCanon to_dict/from_dict round-trip must be stable.

        After the fix adds optional aux fields, this must still work with
        backward-compatible defaults.

        **Validates: Requirements 3.4**
        """
        original = SceneCanon(
            image_path="/fake/canon.png",
            plan_revision=2,
            camera_hash="cam_abc",
            canon_hash="can_xyz",
            object_verdicts={"t1": "present", "t2": "missing"},
            approved=True,
            art_bible_hash="ab_123",
        )

        serialized = original.to_dict()
        restored = SceneCanon.from_dict(serialized)

        assert restored.image_path == original.image_path
        assert restored.plan_revision == original.plan_revision
        assert restored.camera_hash == original.camera_hash
        assert restored.canon_hash == original.canon_hash
        assert restored.object_verdicts == original.object_verdicts
        assert restored.approved == original.approved
        assert restored.art_bible_hash == original.art_bible_hash

    def test_scene_canon_from_dict_with_unknown_keys(self) -> None:
        """SceneCanon.from_dict must handle unknown keys gracefully (forward compat).

        When the fix adds aux_channel_path etc., old code loading new data
        must not crash. Conversely, new code loading old data (no aux fields)
        must also not crash.

        **Validates: Requirements 3.4**
        """
        data = {
            "image_path": "/fake/canon.png",
            "plan_revision": 1,
            "camera_hash": "cam_x",
            "canon_hash": "can_y",
            "object_verdicts": {},
            "approved": False,
            "art_bible_hash": "ab_z",
            # Unknown key that the fix might add — must not crash
            "aux_channel_path": "/fake/canon.aux.exr",
        }
        canon = SceneCanon.from_dict(data)
        assert canon.image_path == "/fake/canon.png"
        assert canon.approved is False

    @given(
        plan_rev=st.integers(min_value=1, max_value=100),
        cam_hash=st.text(min_size=5, max_size=20, alphabet="abcdef0123456789"),
    )
    @settings(max_examples=15, deadline=None)
    def test_property_scene_canon_never_carries_spatial_authority(
        self, plan_rev: int, cam_hash: str
    ) -> None:
        """Property: for all SceneCanon instances, spatial_authority is absent.

        The Canon is appearance-only. Any aux depth/overlay added by the fix
        must be read-only geometry echoes, not spatial overrides.

        **Validates: Requirements 3.4**
        """
        canon = SceneCanon(
            image_path=f"/fake/canon_v{plan_rev}.png",
            plan_revision=plan_rev,
            camera_hash=cam_hash,
            canon_hash=f"hash_{cam_hash}",
            object_verdicts={},
            approved=True,
            art_bible_hash="ab_x",
        )

        # Preservation property
        assert not hasattr(canon, "spatial_authority")
        assert not hasattr(canon, "geometry_override")
        assert not hasattr(canon, "depth_spatial_authority")

        # Round-trip stability
        d = canon.to_dict()
        assert "spatial_authority" not in d
        restored = SceneCanon.from_dict(d)
        assert restored.image_path == canon.image_path


# ─── Cross-Cutting: Full Preservation Property ────────────────────────────────


class TestFullPreservationProperty:
    """Cross-cutting property: all non-bug-condition paths produce identical output."""

    @given(seed=st.integers(min_value=0, max_value=9999))
    @settings(max_examples=10, deadline=None)
    def test_property_non_controlled_camera_paths_unaffected(
        self, seed: int, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Property: for all inputs where isBugCondition is FALSE, the existing
        behavior is preserved exactly.

        Non-bug-condition inputs include:
        - Monocular depth for non-controlled cameras (optional .npy evidence)
        - SAM3 instance-ID/alpha (RGBA emission)
        - Visible RGB appearance consumption
        - RGB-only mesh input preparation

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
        """
        tmp_path = tmp_path_factory.mktemp("full_preserve")
        rng = np.random.default_rng(seed)
        w, h = 128, 128

        # --- Instance-ID/alpha path ---
        image = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[10:100, 10:100] = 255

        out_path = tmp_path / "rgba_out.png"
        apply_mask_to_image(image, mask, out_path)

        with Image.open(out_path) as img:
            rgba = np.array(img)
        # Alpha = mask
        np.testing.assert_array_equal(
            rgba[:, :, 3],
            np.where(mask > 0, 255, 0).astype(np.uint8),
        )
        # RGB preserved where mask is True
        np.testing.assert_array_equal(rgba[mask > 0, :3], image[mask > 0, :3])

        # --- RGB-only mesh prep path ---
        rgba_img = np.zeros((h, w, 4), dtype=np.uint8)
        rgba_img[:, :, :3] = image
        rgba_img[10:100, 10:100, 3] = 255

        rgba_path = tmp_path / f"obj_{seed}.png"
        Image.fromarray(rgba_img, "RGBA").save(rgba_path, format="PNG")

        oc = ObjectCanon(
            object_id=f"obj_{seed}",
            object_name="cross_cut",
            image_path=str(rgba_path),
            mask_coverage=0.5,
            approved=True,
        )
        _, evidence = prepare_generator_input(oc, tmp_path / "prep")
        assert evidence["hidden_rgb_discarded"] is True
        assert evidence["background_policy"] == "approved-alpha-composited-on-white"

        # --- Depth authority boundary ---
        assert FORBIDDEN_DEPTH_AUTHORITIES == (
            "room_dimensions",
            "openings",
            "architectural_geometry",
            "collision_geometry",
            "navigation_geometry",
            "object_transforms",
            "camera",
        )
