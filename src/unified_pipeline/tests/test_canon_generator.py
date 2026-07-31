"""Tests for SceneCanonGenerator.

Validates prompt building, hash binding, object presence validation,
and approval gate logic for the Scene Canon pipeline.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.unified_pipeline.canon_generator import (
    CanonGenerationError,
    SceneCanonGenerator,
    _build_prompt,
    _compute_art_bible_hash,
    _compute_canon_hash,
    _parse_presence_verdicts,
    _validate_presence_heuristic,
    _build_canon_workflow,
)
from src.unified_pipeline.models import (
    ArtBible,
    BlockoutResult,
    Brief,
    CameraContract,
    ManifestObject,
    SceneCanon,
    Atmosphere,
    Era,
    Palette,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def art_bible() -> ArtBible:
    """Standard Art Bible for testing."""
    return ArtBible(
        era_rules={
            "belongs": ["mid-century modern furniture", "warm wood tones"],
            "excludes": ["smart home devices", "LED strips"],
        },
        material_palette=(
            "worn oak (metallic=0.0, roughness=0.7)",
            "brushed stainless (metallic=0.9, roughness=0.2)",
            "cream ceramic (metallic=0.0, roughness=0.4)",
        ),
        lighting_direction={
            "key": {"direction": "window north-facing", "color_temperature_k": 5600},
            "fill": {"direction": "ambient bounce", "color_temperature_k": 4000},
            "accent": {"direction": "pendant over table", "color_temperature_k": 2800},
        },
        color_palette=("#F5F0E8", "#8B7355", "#D4A574", "#4A4A4A", "#E8DCC8"),
        prop_style={
            "silhouette_language": "rounded",
            "detail_level": "medium",
            "wear_patina": "light surface wear, lived-in warmth",
        },
        era_exclusions=(
            "no smart thermostats",
            "no USB outlets",
            "no LED strip lighting",
        ),
        immutable=True,
    )


@pytest.fixture
def brief() -> Brief:
    """Danny's kitchenette Brief for testing."""
    return Brief(
        room_purpose="small warm kitchen",
        atmosphere=Atmosphere(
            mood="cozy and inviting",
            lighting_direction="natural from window",
            time_of_day="morning",
        ),
        era=Era(period="1960s mid-century", style_exclusions=("smart devices",)),
        palette=Palette(
            primary="warm wood",
            accent="cream ceramic",
            material_finishes=("oak", "stainless", "ceramic"),
        ),
        object_manifest=(
            ManifestObject(id="obj-table-001", name="round table", role="furniture", count=1),
            ManifestObject(id="obj-chair-001", name="chair", role="furniture", count=2),
            ManifestObject(id="obj-counter-001", name="counter", role="architecture", count=1, is_architectural=True),
            ManifestObject(id="obj-coffee-001", name="coffee maker", role="appliance", count=1),
        ),
    )


@pytest.fixture
def camera() -> CameraContract:
    """Standard CameraContract."""
    return CameraContract(
        position=(2.0, 1.6, -1.5),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        aspect=1024.0 / 768.0,
        near=0.05,
        far=100.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_abc123def456",
    )


@pytest.fixture
def approved_blockout(tmp_path: Path) -> BlockoutResult:
    """An approved BlockoutResult with a real temporary image."""
    img_path = tmp_path / "blockout_v1.png"
    # Create a small dummy PNG
    from PIL import Image

    img = Image.new("RGB", (1024, 768), color=(100, 100, 100))
    img.save(str(img_path), "PNG")

    return BlockoutResult(
        image_path=str(img_path),
        plan_revision=1,
        camera_hash="cam_abc123def456",
        approved=True,
        feedback="",
    )


@pytest.fixture
def unapproved_blockout() -> BlockoutResult:
    """An unapproved BlockoutResult."""
    return BlockoutResult(
        image_path="output/blockouts/test/blockout_v1.png",
        plan_revision=1,
        camera_hash="cam_abc123def456",
        approved=False,
        feedback="",
    )


# ─── Prompt Building Tests ─────────────────────────────────────────────────────


class TestBuildPrompt:
    """Test the FLUX prompt builder from Art_Bible + Brief."""

    def test_includes_room_purpose(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes the room purpose from Brief."""
        prompt = _build_prompt(art_bible, brief)
        assert "small warm kitchen" in prompt

    def test_includes_photorealistic(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes photorealistic quality keywords."""
        prompt = _build_prompt(art_bible, brief)
        assert "photorealistic" in prompt

    def test_includes_mood(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes the atmosphere mood."""
        prompt = _build_prompt(art_bible, brief)
        assert "cozy and inviting" in prompt

    def test_includes_materials(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes material palette from Art_Bible."""
        prompt = _build_prompt(art_bible, brief)
        assert "worn oak" in prompt

    def test_includes_objects(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes key objects from manifest."""
        prompt = _build_prompt(art_bible, brief)
        assert "round table" in prompt
        assert "coffee maker" in prompt

    def test_includes_lighting(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes lighting direction from Art_Bible."""
        prompt = _build_prompt(art_bible, brief)
        assert "window north-facing" in prompt

    def test_includes_time_of_day(self, art_bible: ArtBible, brief: Brief):
        """Prompt includes time of day."""
        prompt = _build_prompt(art_bible, brief)
        assert "morning" in prompt

    def test_empty_brief_produces_valid_prompt(self, art_bible: ArtBible):
        """An empty Brief still produces a valid non-empty prompt."""
        empty_brief = Brief()
        prompt = _build_prompt(art_bible, empty_brief)
        assert len(prompt) > 0
        assert "photorealistic" in prompt

    def test_empty_art_bible_produces_valid_prompt(self, brief: Brief):
        """An empty ArtBible still produces a valid prompt."""
        empty_art = ArtBible()
        prompt = _build_prompt(empty_art, brief)
        assert len(prompt) > 0
        assert "photorealistic" in prompt


# ─── Canon Hash Tests ──────────────────────────────────────────────────────────


class TestCanonHash:
    """Test hash computation and binding. Req 8.5."""

    def test_hash_deterministic(self, tmp_path: Path):
        """Same inputs produce the same hash."""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake image data for hash test")

        h1 = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam123")
        h2 = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam123")
        assert h1 == h2

    def test_hash_changes_with_plan_revision(self, tmp_path: Path):
        """Different plan revision produces different hash."""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake image data for hash test")

        h1 = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam123")
        h2 = _compute_canon_hash(str(img), plan_revision=2, camera_hash="cam123")
        assert h1 != h2

    def test_hash_changes_with_camera_hash(self, tmp_path: Path):
        """Different camera hash produces different hash."""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake image data for hash test")

        h1 = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam123")
        h2 = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam456")
        assert h1 != h2

    def test_hash_changes_with_image_content(self, tmp_path: Path):
        """Different image content produces different hash."""
        img1 = tmp_path / "test1.png"
        img1.write_bytes(b"image A data")

        img2 = tmp_path / "test2.png"
        img2.write_bytes(b"image B data")

        h1 = _compute_canon_hash(str(img1), plan_revision=1, camera_hash="cam123")
        h2 = _compute_canon_hash(str(img2), plan_revision=1, camera_hash="cam123")
        assert h1 != h2

    def test_hash_is_valid_sha256(self, tmp_path: Path):
        """Hash is a valid 64-character hex string (SHA-256)."""
        img = tmp_path / "test.png"
        img.write_bytes(b"image data")

        h = _compute_canon_hash(str(img), plan_revision=1, camera_hash="cam123")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_with_missing_file(self):
        """Hash still works when file doesn't exist (uses path string)."""
        h = _compute_canon_hash(
            "nonexistent/path.png", plan_revision=1, camera_hash="cam123"
        )
        assert len(h) == 64

    def test_art_bible_hash_deterministic(self, art_bible: ArtBible):
        """Art Bible hash is deterministic."""
        h1 = _compute_art_bible_hash(art_bible)
        h2 = _compute_art_bible_hash(art_bible)
        assert h1 == h2

    def test_art_bible_hash_changes_with_content(self, art_bible: ArtBible):
        """Different Art Bible content produces different hash."""
        different_art = ArtBible(
            material_palette=("glass", "steel"),
            era_exclusions=("no wooden furniture",),
        )
        h1 = _compute_art_bible_hash(art_bible)
        h2 = _compute_art_bible_hash(different_art)
        assert h1 != h2


# ─── Presence Validation Tests ─────────────────────────────────────────────────


class TestPresenceValidation:
    """Test object presence validation. Req 8.3."""

    def test_heuristic_returns_uncertain_for_all(self, brief: Brief):
        """Heuristic fallback marks all objects as uncertain."""
        manifest = list(brief.object_manifest)
        verdicts = _validate_presence_heuristic(manifest)

        assert len(verdicts) == len(manifest)
        for obj in manifest:
            assert verdicts[obj.id] == "uncertain"

    def test_heuristic_empty_manifest(self):
        """Empty manifest returns empty dict."""
        verdicts = _validate_presence_heuristic([])
        assert verdicts == {}

    def test_parse_verdicts_valid_json(self, brief: Brief):
        """Parse valid JSON verdicts from vision model."""
        manifest = list(brief.object_manifest)
        raw = json.dumps({
            "verdicts": [
                {"id": "obj-table-001", "verdict": "present"},
                {"id": "obj-chair-001", "verdict": "present"},
                {"id": "obj-counter-001", "verdict": "present"},
                {"id": "obj-coffee-001", "verdict": "missing"},
            ]
        })

        verdicts = _parse_presence_verdicts(raw, manifest)
        assert verdicts["obj-table-001"] == "present"
        assert verdicts["obj-chair-001"] == "present"
        assert verdicts["obj-counter-001"] == "present"
        assert verdicts["obj-coffee-001"] == "missing"

    def test_parse_verdicts_with_markdown_fences(self, brief: Brief):
        """Parse verdicts wrapped in markdown code fences."""
        manifest = list(brief.object_manifest)
        raw = '```json\n{"verdicts": [{"id": "obj-table-001", "verdict": "present"}]}\n```'

        verdicts = _parse_presence_verdicts(raw, manifest)
        assert verdicts["obj-table-001"] == "present"
        # Others default to uncertain
        assert verdicts["obj-chair-001"] == "uncertain"

    def test_parse_verdicts_invalid_json(self, brief: Brief):
        """Invalid JSON falls back to all uncertain."""
        manifest = list(brief.object_manifest)
        verdicts = _parse_presence_verdicts("not json at all", manifest)

        for obj in manifest:
            assert verdicts[obj.id] == "uncertain"

    def test_parse_verdicts_invalid_verdict_value(self, brief: Brief):
        """Invalid verdict values are kept as uncertain."""
        manifest = list(brief.object_manifest)
        raw = json.dumps({
            "verdicts": [
                {"id": "obj-table-001", "verdict": "INVALID_VALUE"},
                {"id": "obj-chair-001", "verdict": "present"},
            ]
        })

        verdicts = _parse_presence_verdicts(raw, manifest)
        assert verdicts["obj-table-001"] == "uncertain"  # invalid → default
        assert verdicts["obj-chair-001"] == "present"

    def test_parse_verdicts_unknown_id_ignored(self, brief: Brief):
        """Object IDs not in manifest are ignored."""
        manifest = list(brief.object_manifest)
        raw = json.dumps({
            "verdicts": [
                {"id": "unknown-id-999", "verdict": "present"},
                {"id": "obj-table-001", "verdict": "present"},
            ]
        })

        verdicts = _parse_presence_verdicts(raw, manifest)
        assert "unknown-id-999" not in verdicts
        assert verdicts["obj-table-001"] == "present"


# ─── Workflow Builder Tests ────────────────────────────────────────────────────


class TestBuildCanonWorkflow:
    """Test ComfyUI workflow construction."""

    def test_workflow_has_required_nodes(self):
        """Workflow contains all required ComfyUI nodes."""
        workflow = _build_canon_workflow(
            blockout_filename="test_blockout.png",
            prompt="test prompt",
        )

        # Must have checkpoint loader, image loader, encoder, sampler, decoder, saver
        class_types = {
            node["class_type"] for node in workflow.values()
        }
        assert "CheckpointLoaderSimple" in class_types
        assert "LoadImage" in class_types
        assert "KSampler" in class_types
        assert "VAEDecode" in class_types
        assert "SaveImage" in class_types

    def test_workflow_uses_blockout_filename(self):
        """Workflow references the uploaded blockout filename."""
        workflow = _build_canon_workflow(
            blockout_filename="my_blockout.png",
            prompt="test",
        )

        load_image_node = workflow["2"]
        assert load_image_node["inputs"]["image"] == "my_blockout.png"

    def test_workflow_uses_correct_dimensions(self):
        """Workflow scales to CameraContract dimensions."""
        workflow = _build_canon_workflow(
            blockout_filename="test.png",
            prompt="test",
            width=1024,
            height=768,
        )

        scale_node = workflow["3"]
        assert scale_node["inputs"]["width"] == 1024
        assert scale_node["inputs"]["height"] == 768

    def test_workflow_uses_prompt(self):
        """Workflow embeds the text prompt in CLIP encoder."""
        prompt_text = "photorealistic kitchen scene"
        workflow = _build_canon_workflow(
            blockout_filename="test.png",
            prompt=prompt_text,
        )

        clip_node = workflow["5"]
        assert clip_node["inputs"]["text"] == prompt_text

    def test_workflow_has_negative_prompt(self):
        """Workflow has a negative prompt to avoid common artifacts."""
        workflow = _build_canon_workflow(
            blockout_filename="test.png",
            prompt="test",
        )

        neg_clip = workflow["6"]
        assert "blurry" in neg_clip["inputs"]["text"]
        assert "wireframe" in neg_clip["inputs"]["text"]

    def test_workflow_respects_seed(self):
        """Fixed seed is passed to KSampler."""
        workflow = _build_canon_workflow(
            blockout_filename="test.png",
            prompt="test",
            seed=42,
        )

        sampler = workflow["7"]
        assert sampler["inputs"]["seed"] == 42

    def test_workflow_respects_steps_and_cfg(self):
        """Custom steps and cfg are passed to KSampler."""
        workflow = _build_canon_workflow(
            blockout_filename="test.png",
            prompt="test",
            steps=50,
            cfg=9.0,
        )

        sampler = workflow["7"]
        assert sampler["inputs"]["steps"] == 50
        assert sampler["inputs"]["cfg"] == 9.0


# ─── SceneCanonGenerator Integration Tests ─────────────────────────────────────


class TestSceneCanonGenerator:
    """Test the SceneCanonGenerator class. Req 8.1-8.7."""

    def test_rejects_unapproved_blockout(self, unapproved_blockout, art_bible, brief, camera):
        """Req 8.7: Cannot generate Canon from unapproved Blockout."""
        generator = SceneCanonGenerator()

        with pytest.raises(CanonGenerationError, match="approved"):
            import asyncio
            asyncio.run(
                generator.generate(unapproved_blockout, art_bible, brief, camera)
            )

    def test_build_prompt_method(self, art_bible, brief):
        """Instance method delegates to module-level prompt builder."""
        generator = SceneCanonGenerator()
        prompt = generator._build_prompt(art_bible, brief)
        assert "photorealistic" in prompt
        assert "small warm kitchen" in prompt

    def test_compute_hash_method(self, tmp_path):
        """Instance method delegates to module-level hash computation."""
        generator = SceneCanonGenerator()
        img = tmp_path / "test.png"
        img.write_bytes(b"test data")

        h = generator._compute_canon_hash(str(img), 1, "cam123")
        expected = _compute_canon_hash(str(img), 1, "cam123")
        assert h == expected

    @pytest.mark.asyncio
    async def test_validate_presence_empty_manifest(self):
        """Empty manifest returns empty dict."""
        generator = SceneCanonGenerator()
        verdicts = await generator.validate_presence("any/path.png", [])
        assert verdicts == {}

    @pytest.mark.asyncio
    async def test_validate_presence_falls_back_to_heuristic(self, brief):
        """When vision model unavailable, falls back to heuristic (all uncertain)."""
        generator = SceneCanonGenerator()
        manifest = list(brief.object_manifest)

        # Mock the vision call to fail
        with patch(
            "src.unified_pipeline.canon_generator._validate_presence_via_vision",
            side_effect=Exception("Vision model unavailable"),
        ):
            verdicts = await generator.validate_presence(
                "nonexistent.png", manifest
            )

        for obj in manifest:
            assert verdicts[obj.id] == "uncertain"

    @pytest.mark.asyncio
    async def test_generate_success(self, approved_blockout, art_bible, brief, camera, tmp_path):
        """Full generation flow with mocked ComfyUI produces valid SceneCanon."""
        generator = SceneCanonGenerator(output_dir=tmp_path / "canons")

        # Create the output image that get_output_image would produce
        output_dir = tmp_path / "canons" / "test_session"
        output_dir.mkdir(parents=True)
        output_file = output_dir / "canon_v1.png"

        from PIL import Image
        img = Image.new("RGB", (1024, 768), color=(200, 150, 100))
        img.save(str(output_file), "PNG")

        # Mock ComfyUI client at its import in canon_generator module
        with patch("src.unified_pipeline.canon_generator.ComfyUIClient") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.upload_image = AsyncMock(return_value="blockout_uploaded.png")
            mock_instance.submit_workflow = AsyncMock(return_value="prompt-123")
            mock_instance.wait_for_completion = AsyncMock(return_value={"status": {"completed": True}})
            mock_instance.get_output_image = AsyncMock(return_value=output_file)

            # Mock presence validation to succeed
            with patch(
                "src.unified_pipeline.canon_generator._validate_presence_via_vision",
                new_callable=AsyncMock,
                return_value={
                    "obj-table-001": "present",
                    "obj-chair-001": "present",
                    "obj-counter-001": "present",
                    "obj-coffee-001": "present",
                },
            ):
                canon = await generator.generate(
                    approved_blockout, art_bible, brief, camera,
                    session_id="test_session",
                    seed=42,
                )

        # Verify the SceneCanon output
        assert isinstance(canon, SceneCanon)
        assert canon.image_path == str(output_file)
        assert canon.plan_revision == 1
        assert canon.camera_hash == "cam_abc123def456"
        assert canon.approved is False  # Not yet approved
        assert len(canon.canon_hash) == 64  # SHA-256 hex
        assert len(canon.art_bible_hash) == 64
        assert canon.object_verdicts["obj-table-001"] == "present"

    @pytest.mark.asyncio
    async def test_generate_blockout_missing_file(self, art_bible, brief, camera, tmp_path):
        """Generation fails when blockout image file is missing."""
        missing_blockout = BlockoutResult(
            image_path=str(tmp_path / "nonexistent.png"),
            plan_revision=1,
            camera_hash="cam123",
            approved=True,
        )

        generator = SceneCanonGenerator()
        with pytest.raises(CanonGenerationError, match="not found"):
            await generator.generate(
                missing_blockout, art_bible, brief, camera
            )


# ─── SceneCanon Dataclass Tests ────────────────────────────────────────────────


class TestSceneCanonModel:
    """Test the SceneCanon model serialization."""

    def test_round_trip(self):
        """SceneCanon serializes and deserializes correctly."""
        canon = SceneCanon(
            image_path="output/canons/test/canon_v1.png",
            plan_revision=2,
            camera_hash="cam_hash_123",
            canon_hash="canon_hash_456",
            object_verdicts={"obj-1": "present", "obj-2": "missing"},
            approved=True,
            art_bible_hash="art_hash_789",
        )

        d = canon.to_dict()
        restored = SceneCanon.from_dict(d)

        assert restored.image_path == canon.image_path
        assert restored.plan_revision == canon.plan_revision
        assert restored.camera_hash == canon.camera_hash
        assert restored.canon_hash == canon.canon_hash
        assert restored.object_verdicts == canon.object_verdicts
        assert restored.approved == canon.approved
        assert restored.art_bible_hash == canon.art_bible_hash
