"""Tests for the Canon pipeline: SceneCanonGenerator, ObjectIsolator, RoomPlateGenerator.

Validates:
- SceneCanonGenerator.generate() returns SceneCanon with all required fields
- SceneCanon object_verdicts maps each manifest UUID to present/missing/uncertain
- Canon hash is bound to plan_revision and camera_hash
- Canon hash changes when plan_revision changes
- ObjectIsolator.segment() returns list of ObjectCanon
- ObjectIsolator quality gate rejects masks with <1% coverage
- ObjectIsolator quality gate accepts masks with >1% coverage
- Each ObjectCanon.object_id matches a Brief manifest UUID
- RoomPlateGenerator.generate() returns a valid path
- Approval gate blocks downstream when Canon is PENDING

**Validates: Requirements 8.3, 9.4**

Requirements: 8.3, 9.4
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.unified_pipeline.approval_gates import ApprovalGate, ApprovalStatus
from src.unified_pipeline.canon_generator import (
    SceneCanonGenerator,
    _compute_canon_hash,
)
from src.unified_pipeline.models import (
    ArtBible,
    BlockoutResult,
    Brief,
    CameraContract,
    ManifestObject,
    ObjectCanon,
    SceneCanon,
)
from src.unified_pipeline.object_isolator import (
    MIN_COVERAGE_THRESHOLD,
    ObjectIsolator,
    quality_gate,
)
from src.unified_pipeline.room_plate import RoomPlateGenerator
from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_brief() -> Brief:
    """A Brief with 3 manifest objects (Danny's kitchenette objects)."""
    return Brief(
        room_purpose="small warm kitchen",
        object_manifest=(
            ManifestObject(id="uuid-table", name="round_table", role="furniture", count=1),
            ManifestObject(id="uuid-chair1", name="chair", role="furniture", count=1),
            ManifestObject(
                id="uuid-coffeemaker", name="coffee_maker", role="appliance", count=1
            ),
        ),
    )


@pytest.fixture
def sample_blockout(tmp_path) -> BlockoutResult:
    """Approved blockout result with a real image file on disk."""
    img = Image.new("RGB", (1024, 768), color=(128, 128, 128))
    blockout_path = tmp_path / "blockout_r1.png"
    img.save(blockout_path)
    return BlockoutResult(
        image_path=str(blockout_path),
        plan_revision=1,
        camera_hash="cam_hash_abc123",
        approved=True,
    )


@pytest.fixture
def sample_art_bible() -> ArtBible:
    """Art bible for Canon generation."""
    return ArtBible(
        era_rules={"period": "1950s", "belongs": ["retro chrome diner"]},
        material_palette=("wood", "chrome", "linoleum"),
        lighting_direction={"key": {"direction": "warm side", "temperature": 3200}},
        color_palette=("#F5E6D3", "#8B4513"),
        era_exclusions=("smart_thermostat", "led_strip"),
    )


@pytest.fixture
def sample_camera() -> CameraContract:
    """Immutable camera contract."""
    return CameraContract(
        position=(0.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        aspect=1024.0 / 768.0,
        near=0.1,
        far=100.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_hash_abc123",
    )


@pytest.fixture
def sample_canon(tmp_path) -> SceneCanon:
    """An approved SceneCanon with a real image file on disk."""
    img = Image.new("RGB", (1024, 768), color=(200, 180, 160))
    canon_path = tmp_path / "scene_canon_rev1.png"
    img.save(canon_path)
    return SceneCanon(
        image_path=str(canon_path),
        plan_revision=1,
        camera_hash="cam_hash_abc123",
        canon_hash="canon_hash_xyz",
        object_verdicts={
            "uuid-table": "present",
            "uuid-chair1": "present",
            "uuid-coffeemaker": "present",
        },
        approved=True,
    )


@pytest.fixture
def mock_comfyui_client():
    """A mocked ComfyUI client for Canon generation."""
    client = MagicMock(spec=ComfyUIClient)
    client.health_check = AsyncMock(return_value=True)
    client.upload_image = AsyncMock(return_value="blockout_uploaded.png")
    client.submit_workflow = AsyncMock(return_value="prompt-canon-001")
    client.wait_for_completion = AsyncMock(return_value={"outputs": {}})
    client.get_output_image = AsyncMock(
        return_value=Path("output/canons/test/canon_v1.png")
    )
    return client


# ─── SceneCanonGenerator Tests ─────────────────────────────────────────────────


class TestSceneCanonGenerator:
    """Tests for SceneCanonGenerator.generate() behavior."""

    @pytest.mark.asyncio
    async def test_generate_returns_scene_canon_with_all_required_fields(
        self, sample_blockout, sample_art_bible, sample_brief, sample_camera,
        mock_comfyui_client, tmp_path,
    ):
        """SceneCanonGenerator.generate() returns SceneCanon with all required fields."""
        # Create canon output image so hash computation works
        output_dir = tmp_path / "canons"
        output_dir.mkdir()
        canon_img = Image.new("RGB", (1024, 768), color=(200, 180, 160))
        canon_output = output_dir / "test" / "canon_v1.png"
        canon_output.parent.mkdir(parents=True)
        canon_img.save(canon_output)
        mock_comfyui_client.get_output_image = AsyncMock(return_value=canon_output)

        gen = SceneCanonGenerator(
            output_dir=output_dir,
            comfyui_url="http://localhost:8188",
        )

        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient",
            return_value=mock_comfyui_client,
        ), patch(
            "src.unified_pipeline.canon_generator._validate_presence_via_vision",
            new_callable=AsyncMock,
            return_value={
                "uuid-table": "present",
                "uuid-chair1": "present",
                "uuid-coffeemaker": "uncertain",
            },
        ):
            result = await gen.generate(
                sample_blockout,
                sample_art_bible,
                sample_brief,
                sample_camera,
                session_id="test",
            )

        assert isinstance(result, SceneCanon)
        assert result.image_path != ""
        assert result.plan_revision == sample_blockout.plan_revision
        assert result.camera_hash == sample_camera.camera_hash
        assert result.canon_hash != ""
        assert isinstance(result.object_verdicts, dict)
        assert result.approved is False  # Starts unapproved
        assert result.art_bible_hash != ""

    @pytest.mark.asyncio
    async def test_object_verdicts_maps_each_manifest_uuid(
        self, sample_blockout, sample_art_bible, sample_brief, sample_camera,
        mock_comfyui_client, tmp_path,
    ):
        """Req 8.3: object_verdicts maps each manifest UUID to present/missing/uncertain."""
        output_dir = tmp_path / "canons"
        canon_output = output_dir / "test" / "canon_v1.png"
        canon_output.parent.mkdir(parents=True)
        Image.new("RGB", (1024, 768)).save(canon_output)
        mock_comfyui_client.get_output_image = AsyncMock(return_value=canon_output)

        gen = SceneCanonGenerator(output_dir=output_dir)

        verdicts = {
            "uuid-table": "present",
            "uuid-chair1": "missing",
            "uuid-coffeemaker": "uncertain",
        }

        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient",
            return_value=mock_comfyui_client,
        ), patch(
            "src.unified_pipeline.canon_generator._validate_presence_via_vision",
            new_callable=AsyncMock,
            return_value=verdicts,
        ):
            result = await gen.generate(
                sample_blockout, sample_art_bible, sample_brief, sample_camera,
                session_id="test",
            )

        # Every manifest object must have a verdict
        manifest_ids = {obj.id for obj in sample_brief.object_manifest}
        verdict_ids = set(result.object_verdicts.keys())
        assert manifest_ids == verdict_ids

        # Each verdict must be one of the valid values
        valid_verdicts = {"present", "missing", "uncertain"}
        for verdict in result.object_verdicts.values():
            assert verdict in valid_verdicts

    def test_canon_hash_bound_to_plan_revision_and_camera_hash(self, tmp_path):
        """Canon hash is bound to plan_revision and camera_hash (Req 8.5)."""
        # Create a test image for deterministic hashing
        img_path = tmp_path / "test_canon.png"
        Image.new("RGB", (100, 100)).save(img_path)

        hash1 = _compute_canon_hash(str(img_path), plan_revision=1, camera_hash="cam_aaa")
        hash2 = _compute_canon_hash(str(img_path), plan_revision=1, camera_hash="cam_aaa")

        # Same inputs → same hash (deterministic)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_canon_hash_changes_when_plan_revision_changes(self, tmp_path):
        """Canon hash changes when plan_revision changes (hash sensitivity)."""
        img_path = tmp_path / "test_canon.png"
        Image.new("RGB", (100, 100)).save(img_path)

        hash_v1 = _compute_canon_hash(str(img_path), plan_revision=1, camera_hash="cam_aaa")
        hash_v2 = _compute_canon_hash(str(img_path), plan_revision=2, camera_hash="cam_aaa")

        assert hash_v1 != hash_v2

    def test_canon_hash_changes_when_camera_hash_changes(self, tmp_path):
        """Canon hash changes when camera_hash changes."""
        img_path = tmp_path / "test_canon.png"
        Image.new("RGB", (100, 100)).save(img_path)

        hash_a = _compute_canon_hash(str(img_path), plan_revision=1, camera_hash="camera_aaa")
        hash_b = _compute_canon_hash(str(img_path), plan_revision=1, camera_hash="camera_bbb")

        assert hash_a != hash_b


# ─── ObjectIsolator Tests ──────────────────────────────────────────────────────


class TestObjectIsolator:
    """Tests for ObjectIsolator segmentation and quality gating."""

    @pytest.mark.asyncio
    async def test_segment_returns_list_of_object_canon(
        self, sample_canon, sample_brief, tmp_path,
    ):
        """ObjectIsolator.segment() returns list of ObjectCanon instances."""
        manifest = list(sample_brief.object_manifest)

        # Create masks that cover >1% each (to pass quality gate)
        h, w = 768, 1024
        masks = []
        for i in range(len(manifest)):
            mask = np.zeros((h, w), dtype=np.uint8)
            # Each mask covers a different area, all >1%
            y_start = i * 100
            mask[y_start:y_start + 100, 0:200] = 255  # 20000 pixels → ~2.6%
            masks.append(mask)

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        assert isinstance(results, list)
        assert all(isinstance(r, ObjectCanon) for r in results)
        assert len(results) == len(manifest)

    @pytest.mark.asyncio
    async def test_quality_gate_rejects_low_coverage(
        self, sample_canon, sample_brief, tmp_path,
    ):
        """Req 9.3/9.4: Quality gate rejects masks with <1% coverage."""
        manifest = list(sample_brief.object_manifest)
        h, w = 768, 1024

        # Create masks with <1% coverage for all objects
        masks = []
        for i in range(len(manifest)):
            mask = np.zeros((h, w), dtype=np.uint8)
            # Only 4 pixels → way below 1% threshold
            mask[0, i] = 255
            masks.append(mask)

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        # All objects should be rejected (empty results)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_quality_gate_accepts_sufficient_coverage(
        self, sample_canon, sample_brief, tmp_path,
    ):
        """Req 9.3/9.4: Quality gate accepts masks with >=1% coverage."""
        manifest = list(sample_brief.object_manifest)
        h, w = 768, 1024

        # Create masks with >1% coverage for all objects
        masks = []
        for i in range(len(manifest)):
            mask = np.zeros((h, w), dtype=np.uint8)
            # 200*200 = 40000 pixels → ~5% coverage
            y_start = i * 200
            mask[y_start:y_start + 200, 0:200] = 255
            masks.append(mask)

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        # All objects should pass quality gate
        assert len(results) == len(manifest)

    @pytest.mark.asyncio
    async def test_each_object_canon_matches_brief_manifest_uuid(
        self, sample_canon, sample_brief, tmp_path,
    ):
        """Each ObjectCanon.object_id matches a Brief manifest UUID (Req 9.2)."""
        manifest = list(sample_brief.object_manifest)
        h, w = 768, 1024

        masks = []
        for i in range(len(manifest)):
            mask = np.zeros((h, w), dtype=np.uint8)
            y_start = i * 150
            mask[y_start:y_start + 150, 0:150] = 255
            masks.append(mask)

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        manifest_ids = {obj.id for obj in manifest}
        for oc in results:
            assert oc.object_id in manifest_ids

    @pytest.mark.asyncio
    async def test_object_canon_has_correct_provenance(
        self, sample_canon, sample_brief, tmp_path,
    ):
        """ObjectCanon provenance is 'raw_segmentation' for MVP (Req 9.4)."""
        manifest = list(sample_brief.object_manifest)
        h, w = 768, 1024

        masks = []
        for i in range(len(manifest)):
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[i * 100:(i + 1) * 100, 0:200] = 255
            masks.append(mask)

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        for oc in results:
            assert oc.provenance == "raw_segmentation"

    def test_quality_gate_function_rejects_below_threshold(self):
        """quality_gate() rejects masks with <1% coverage."""
        h, w = 768, 1024
        # Create a mask with ~0.1% coverage
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[0:3, 0:3] = 255  # 9 pixels → ~0.001%

        assert quality_gate(mask, "test-obj") is False

    def test_quality_gate_function_accepts_above_threshold(self):
        """quality_gate() accepts masks with >=1% coverage."""
        h, w = 768, 1024
        # Create a mask with ~5% coverage
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[0:200, 0:200] = 255  # 40000 pixels → ~5%

        assert quality_gate(mask, "test-obj") is True

    def test_quality_gate_at_exact_threshold(self):
        """quality_gate() at exactly 1% boundary."""
        h, w = 768, 1024
        total_pixels = h * w
        # Need enough pixels to hit exactly >=1% after division
        # Use ceil to ensure we're at or above the threshold
        needed = int(total_pixels * MIN_COVERAGE_THRESHOLD) + 1

        mask = np.zeros((h, w), dtype=np.uint8)
        # Fill exactly `needed` pixels
        flat = mask.ravel()
        flat[:needed] = 255
        mask = flat.reshape((h, w))

        # At/above the threshold → should pass
        assert quality_gate(mask, "test-obj") is True

    @pytest.mark.asyncio
    async def test_mixed_coverage_filters_correctly(self, sample_canon, tmp_path):
        """Objects with mixed coverage: some pass, some rejected."""
        manifest = [
            ManifestObject(id="good-obj-1", name="table", role="furniture"),
            ManifestObject(id="good-obj-2", name="chair", role="furniture"),
            ManifestObject(id="bad-obj-3", name="crumb", role="debris"),
        ]

        h, w = 768, 1024

        # _match_masks_to_manifest sorts masks by area (largest first) and
        # assigns greedily to objects in manifest order. So:
        # - largest mask → good-obj-1
        # - next mask → good-obj-2
        # - smallest mask → bad-obj-3
        mask_large = np.zeros((h, w), dtype=np.uint8)
        mask_large[0:150, 0:200] = 255  # ~3.9% (passes)

        mask_medium = np.zeros((h, w), dtype=np.uint8)
        mask_medium[200:300, 0:200] = 255  # ~2.6% (passes)

        mask_tiny = np.zeros((h, w), dtype=np.uint8)
        mask_tiny[0, 0] = 255  # ~0.0001% (fails quality gate)

        # Order doesn't matter — they get sorted by area internally
        masks = [mask_medium, mask_tiny, mask_large]

        isolator = ObjectIsolator(output_dir=tmp_path / "objects")

        with patch.object(isolator, "_run_sam", new_callable=AsyncMock, return_value=masks):
            results = await isolator.segment(
                sample_canon.image_path,
                manifest,
                session_id="test",
            )

        # bad-obj-3 gets the tiny mask → rejected by quality gate
        result_ids = {r.object_id for r in results}
        assert "good-obj-1" in result_ids
        assert "good-obj-2" in result_ids
        assert "bad-obj-3" not in result_ids
        assert len(results) == 2


# ─── RoomPlateGenerator Tests ──────────────────────────────────────────────────


class TestRoomPlateGenerator:
    """Tests for RoomPlateGenerator.generate() behavior."""

    @pytest.mark.asyncio
    async def test_generate_returns_valid_path(self, sample_canon, tmp_path):
        """RoomPlateGenerator.generate() returns a valid path string."""
        mock_client = MagicMock(spec=ComfyUIClient)
        mock_client.health_check = AsyncMock(return_value=False)

        gen = RoomPlateGenerator(
            comfyui_client=mock_client,
            output_dir=tmp_path / "room_plates",
        )

        # With ComfyUI unavailable, fallback copies Canon → returns path
        result = await gen.generate(
            canon_path=sample_canon.image_path,
            object_masks=[],
            session_id="test",
        )

        assert isinstance(result, str)
        assert result != ""
        # Path should exist when there are no masks (Canon used directly)
        assert Path(result).exists()

    @pytest.mark.asyncio
    async def test_generate_with_no_masks_uses_canon(self, sample_canon, tmp_path):
        """When no object masks provided, Canon is used as Room_Plate."""
        mock_client = MagicMock(spec=ComfyUIClient)

        gen = RoomPlateGenerator(
            comfyui_client=mock_client,
            output_dir=tmp_path / "room_plates",
        )

        result = await gen.generate(
            canon_path=sample_canon.image_path,
            object_masks=[],
            session_id="test-no-masks",
        )

        assert isinstance(result, str)
        assert result != ""
        # Should NOT have called ComfyUI at all
        mock_client.upload_image.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_comfyui_failure(self, sample_canon, tmp_path):
        """Falls back to Canon when ComfyUI is unavailable."""
        mock_client = MagicMock(spec=ComfyUIClient)
        mock_client.health_check = AsyncMock(return_value=False)

        gen = RoomPlateGenerator(
            comfyui_client=mock_client,
            output_dir=tmp_path / "room_plates",
        )

        # Provide a mask so it tries inpainting
        mask_arr = np.zeros((768, 1024), dtype=np.uint8)
        mask_arr[100:300, 100:300] = 255

        result = await gen.generate(
            canon_path=sample_canon.image_path,
            object_masks=[{"mask_array": mask_arr}],
            session_id="test-fallback",
        )

        assert isinstance(result, str)
        assert result != ""
        # Fallback should produce a file
        assert Path(result).exists()


# ─── Approval Gate Integration (Canon Stage) ──────────────────────────────────


class TestCanonApprovalGate:
    """Tests for approval gate behavior in the Canon stage."""

    def test_gate_blocks_downstream_when_pending(self, sample_canon):
        """Approval gate blocks downstream when Canon is PENDING (Req 8.7)."""
        gate = ApprovalGate(gate_id="canon", stage="scene_canon")
        gate.present(
            {
                "image_path": sample_canon.image_path,
                "canon_hash": sample_canon.canon_hash,
                "object_verdicts": dict(sample_canon.object_verdicts),
            }
        )

        # While pending, downstream is blocked
        assert gate.is_blocking()
        assert gate.status == ApprovalStatus.PENDING
        assert not gate.is_approved()

    def test_gate_unblocks_on_approval(self, sample_canon):
        """Downstream unblocks after Canon approval."""
        gate = ApprovalGate(gate_id="canon", stage="scene_canon")
        gate.present({"image_path": sample_canon.image_path})
        gate.approve()

        assert not gate.is_blocking()
        assert gate.is_approved()

    def test_gate_remains_blocked_after_rejection_then_reset(self, sample_canon):
        """After rejection and reset, gate blocks again for re-presentation."""
        gate = ApprovalGate(gate_id="canon", stage="scene_canon")
        gate.present({"image_path": sample_canon.image_path})
        gate.reject("Lighting too dark")

        assert gate.is_rejected()
        assert not gate.is_blocking()  # Signals orchestrator

        # After reset for re-presentation, it blocks again
        gate.reset()
        assert gate.is_blocking()

    def test_canon_gate_preserves_object_verdicts(self, sample_canon):
        """Gate records preserve the object verdicts for inspection."""
        gate = ApprovalGate(gate_id="canon", stage="scene_canon")
        gate.present(
            {
                "image_path": sample_canon.image_path,
                "object_verdicts": dict(sample_canon.object_verdicts),
            }
        )
        gate.approve()

        records = gate.records
        assert len(records) == 1
        assert records[0].presented_data["object_verdicts"] == {
            "uuid-table": "present",
            "uuid-chair1": "present",
            "uuid-coffeemaker": "present",
        }
