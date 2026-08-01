"""Unit tests for the baseline manager module.

Tests BaselineManager class methods: get_baseline, save_baseline,
baseline_exists, plus metadata sidecar generation and directory organization.

Requirements: 3.3, 4.1, 4.2, 4.3
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.e2e.framework.baseline_manager import (
    BaselineManager,
    BaselineManagerError,
    BaselineMetadata,
    BaselineResult,
    SaveBaselineResult,
    get_commit_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_baselines(tmp_path: Path) -> Path:
    """Create a temporary baselines directory."""
    baselines_dir = tmp_path / "baselines"
    baselines_dir.mkdir()
    return baselines_dir


@pytest.fixture
def manager(tmp_baselines: Path) -> BaselineManager:
    """Create a BaselineManager with temporary directory."""
    return BaselineManager(
        model_version="v16-model-a1b2c3",
        hardware_id="rtx4090-driver560-ab12cd34",
        base_dir=tmp_baselines,
    )


@pytest.fixture
def sample_image() -> bytes:
    """A minimal valid PNG-like byte sequence for testing."""
    # Minimal PNG header + IEND (not a real image but enough for file I/O tests)
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def sample_metadata() -> dict:
    """Sample metadata overrides for save_baseline."""
    return {
        "camera_pose": {
            "position": [0, 1.6, 3.0],
            "target": [0, 1.0, 0],
            "up": [0, 1, 0],
            "vfov": 60,
        },
        "viewport": [1920, 1080],
        "deterministic_seed": 42,
    }


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestBaselineManagerInit:
    """Tests for BaselineManager construction."""

    def test_creates_with_valid_params(self, tmp_baselines: Path) -> None:
        mgr = BaselineManager(
            model_version="v16-model-abc",
            hardware_id="rtx4090-driver560",
            base_dir=tmp_baselines,
        )
        assert mgr.model_version == "v16-model-abc"
        assert mgr.hardware_id == "rtx4090-driver560"

    def test_baseline_dir_path_structure(self, tmp_baselines: Path) -> None:
        """Baselines are organized under {base}/{model_version}/{hardware_id}/."""
        mgr = BaselineManager(
            model_version="v16-model-xyz",
            hardware_id="rtx3080-driver555",
            base_dir=tmp_baselines,
        )
        expected = tmp_baselines / "v16-model-xyz" / "rtx3080-driver555"
        assert mgr.baseline_dir == expected

    def test_raises_on_empty_model_version(self, tmp_baselines: Path) -> None:
        with pytest.raises(BaselineManagerError, match="model_version"):
            BaselineManager(
                model_version="",
                hardware_id="rtx4090",
                base_dir=tmp_baselines,
            )

    def test_raises_on_empty_hardware_id(self, tmp_baselines: Path) -> None:
        with pytest.raises(BaselineManagerError, match="hardware_id"):
            BaselineManager(
                model_version="v16-model-abc",
                hardware_id="",
                base_dir=tmp_baselines,
            )

    def test_raises_on_whitespace_only_model_version(
        self, tmp_baselines: Path
    ) -> None:
        with pytest.raises(BaselineManagerError, match="model_version"):
            BaselineManager(
                model_version="   ",
                hardware_id="rtx4090",
                base_dir=tmp_baselines,
            )


# ---------------------------------------------------------------------------
# baseline_exists tests
# ---------------------------------------------------------------------------


class TestBaselineExists:
    """Tests for BaselineManager.baseline_exists()."""

    def test_returns_false_when_no_baseline(self, manager: BaselineManager) -> None:
        assert manager.baseline_exists("canon") is False

    def test_returns_true_after_save(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        manager.save_baseline("canon", sample_image)
        assert manager.baseline_exists("canon") is True

    def test_returns_false_for_different_stage(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        manager.save_baseline("canon", sample_image)
        assert manager.baseline_exists("dream_preview") is False

    def test_raises_on_empty_stage(self, manager: BaselineManager) -> None:
        with pytest.raises(BaselineManagerError, match="stage"):
            manager.baseline_exists("")


# ---------------------------------------------------------------------------
# get_baseline tests
# ---------------------------------------------------------------------------


class TestGetBaseline:
    """Tests for BaselineManager.get_baseline()."""

    def test_returns_none_when_no_baseline_exists(
        self, manager: BaselineManager
    ) -> None:
        """Requirement 3.3: no baseline is not a failure."""
        result = manager.get_baseline("canon")
        assert result is None

    def test_returns_baseline_after_save(
        self, manager: BaselineManager, sample_image: bytes, sample_metadata: dict
    ) -> None:
        manager.save_baseline("canon", sample_image, sample_metadata)
        result = manager.get_baseline("canon")

        assert result is not None
        assert isinstance(result, BaselineResult)
        assert result.image_data == sample_image
        assert result.metadata.stage == "canon"
        assert result.metadata.model_version == "v16-model-a1b2c3"
        assert result.metadata.hardware_id == "rtx4090-driver560-ab12cd34"

    def test_get_baseline_with_version_override(
        self, tmp_baselines: Path, sample_image: bytes
    ) -> None:
        """Can look up baselines for a different model version."""
        # Save baseline under version A
        mgr_a = BaselineManager(
            model_version="v16-model-aaa",
            hardware_id="rtx4090",
            base_dir=tmp_baselines,
        )
        mgr_a.save_baseline("canon", sample_image)

        # Look up from version B with override
        mgr_b = BaselineManager(
            model_version="v16-model-bbb",
            hardware_id="rtx4090",
            base_dir=tmp_baselines,
        )
        result = mgr_b.get_baseline(
            "canon", model_version="v16-model-aaa"
        )
        assert result is not None
        assert result.metadata.model_version == "v16-model-aaa"

    def test_raises_on_empty_stage(self, manager: BaselineManager) -> None:
        with pytest.raises(BaselineManagerError, match="stage"):
            manager.get_baseline("")


# ---------------------------------------------------------------------------
# save_baseline tests
# ---------------------------------------------------------------------------


class TestSaveBaseline:
    """Tests for BaselineManager.save_baseline()."""

    def test_creates_directory_structure(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        """Requirement 4.1: organize by model version directory."""
        result = manager.save_baseline("canon", sample_image)

        assert result.image_path.exists()
        # Verify directory structure: baselines / model_version / hardware_id / stage.png
        assert result.image_path.parent.name == "rtx4090-driver560-ab12cd34"
        assert result.image_path.parent.parent.name == "v16-model-a1b2c3"

    def test_writes_png_file(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        result = manager.save_baseline("canon", sample_image)
        stored_data = result.image_path.read_bytes()
        assert stored_data == sample_image

    def test_writes_metadata_sidecar(
        self, manager: BaselineManager, sample_image: bytes, sample_metadata: dict
    ) -> None:
        """Requirement 4.3: metadata sidecar alongside each baseline."""
        result = manager.save_baseline("canon", sample_image, sample_metadata)

        assert result.metadata_path.exists()
        assert result.metadata_path.name == "canon.meta.json"

        # Parse and validate the JSON sidecar
        meta_content = json.loads(
            result.metadata_path.read_text(encoding="utf-8")
        )
        assert meta_content["model_version"] == "v16-model-a1b2c3"
        assert meta_content["hardware_id"] == "rtx4090-driver560-ab12cd34"
        assert meta_content["stage"] == "canon"
        assert meta_content["viewport"] == [1920, 1080]
        assert meta_content["deterministic_seed"] == 42
        assert meta_content["camera_pose"]["position"] == [0, 1.6, 3.0]
        assert meta_content["camera_pose"]["vfov"] == 60

    def test_metadata_contains_timestamp(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        """Requirement 4.3: creation timestamp in metadata."""
        result = manager.save_baseline("canon", sample_image)
        assert result.metadata.created_at is not None
        assert "T" in result.metadata.created_at  # ISO format

    def test_metadata_contains_commit_hash(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        """Requirement 4.3: commit hash in metadata."""
        result = manager.save_baseline("canon", sample_image)
        # Will be either a real git hash or "unknown"
        assert result.metadata.commit_hash is not None
        assert len(result.metadata.commit_hash) > 0

    def test_is_new_flag_on_first_save(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        result = manager.save_baseline("canon", sample_image)
        assert result.is_new is True

    def test_is_new_flag_on_overwrite(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        manager.save_baseline("canon", sample_image)
        result = manager.save_baseline("canon", sample_image)
        assert result.is_new is False

    def test_raises_on_empty_stage(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        with pytest.raises(BaselineManagerError, match="stage"):
            manager.save_baseline("", sample_image)

    def test_raises_on_empty_image(self, manager: BaselineManager) -> None:
        with pytest.raises(BaselineManagerError, match="image data"):
            manager.save_baseline("canon", b"")

    def test_approval_info_in_metadata(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        """Requirement 4.3: approval info in metadata."""
        result = manager.save_baseline(
            "canon",
            sample_image,
            {"approved_by": "PR #142", "approved_at": "2026-07-30T15:00:00Z"},
        )
        assert result.metadata.approved_by == "PR #142"
        assert result.metadata.approved_at == "2026-07-30T15:00:00Z"

    def test_unapproved_baseline_has_null_approval(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        result = manager.save_baseline("canon", sample_image)
        assert result.metadata.approved_by is None
        assert result.metadata.approved_at is None


# ---------------------------------------------------------------------------
# Version isolation tests (Property 5)
# ---------------------------------------------------------------------------


class TestVersionIsolation:
    """Tests ensuring baselines from different model versions never share a directory."""

    def test_different_versions_different_directories(
        self, tmp_baselines: Path, sample_image: bytes
    ) -> None:
        """Property 5: baselines from different versions NEVER share a directory."""
        mgr_a = BaselineManager(
            model_version="v16-model-aaa",
            hardware_id="rtx4090",
            base_dir=tmp_baselines,
        )
        mgr_b = BaselineManager(
            model_version="v16-model-bbb",
            hardware_id="rtx4090",
            base_dir=tmp_baselines,
        )

        result_a = mgr_a.save_baseline("canon", sample_image)
        result_b = mgr_b.save_baseline("canon", sample_image)

        # Different directories
        assert result_a.image_path.parent != result_b.image_path.parent
        # Version is in the path
        assert "v16-model-aaa" in str(result_a.image_path)
        assert "v16-model-bbb" in str(result_b.image_path)

    def test_same_version_different_hardware_different_directories(
        self, tmp_baselines: Path, sample_image: bytes
    ) -> None:
        """Different hardware IDs also get separate directories."""
        mgr_a = BaselineManager(
            model_version="v16-model-aaa",
            hardware_id="rtx4090-driver560",
            base_dir=tmp_baselines,
        )
        mgr_b = BaselineManager(
            model_version="v16-model-aaa",
            hardware_id="rtx3080-driver555",
            base_dir=tmp_baselines,
        )

        result_a = mgr_a.save_baseline("canon", sample_image)
        result_b = mgr_b.save_baseline("canon", sample_image)

        assert result_a.image_path.parent != result_b.image_path.parent


# ---------------------------------------------------------------------------
# list_stages tests
# ---------------------------------------------------------------------------


class TestListStages:
    """Tests for BaselineManager.list_stages()."""

    def test_empty_when_no_baselines(self, manager: BaselineManager) -> None:
        assert manager.list_stages() == []

    def test_lists_saved_stages(
        self, manager: BaselineManager, sample_image: bytes
    ) -> None:
        manager.save_baseline("canon", sample_image)
        manager.save_baseline("dream_preview", sample_image)
        stages = manager.list_stages()
        assert sorted(stages) == ["canon", "dream_preview"]


# ---------------------------------------------------------------------------
# BaselineMetadata tests
# ---------------------------------------------------------------------------


class TestBaselineMetadata:
    """Tests for BaselineMetadata dataclass."""

    def test_to_dict_roundtrip(self) -> None:
        meta = BaselineMetadata(
            created_at="2026-07-30T14:22:00Z",
            commit_hash="a1b2c3d4",
            model_version="v16-model-a1b2c3",
            hardware_id="rtx4090-driver560",
            viewport=[1920, 1080],
            stage="canon",
            camera_pose={
                "position": [0, 1.6, 3.0],
                "target": [0, 1.0, 0],
                "up": [0, 1, 0],
                "vfov": 60,
            },
            deterministic_seed=42,
            approved_by="PR #142",
            approved_at="2026-07-30T15:00:00Z",
        )
        d = meta.to_dict()
        restored = BaselineMetadata.from_dict(d)
        assert restored == meta

    def test_from_dict_missing_required_key(self) -> None:
        with pytest.raises(ValueError, match="missing required keys"):
            BaselineMetadata.from_dict({"created_at": "now"})

    def test_from_dict_optional_fields_default(self) -> None:
        data = {
            "created_at": "2026-07-30T14:22:00Z",
            "commit_hash": "abc123",
            "model_version": "v16-model-test",
            "hardware_id": "gpu-test",
            "viewport": [1920, 1080],
            "stage": "canon",
            "camera_pose": {"position": [0, 0, 0]},
        }
        meta = BaselineMetadata.from_dict(data)
        assert meta.deterministic_seed == 42  # default
        assert meta.approved_by is None
        assert meta.approved_at is None


# ---------------------------------------------------------------------------
# get_commit_hash tests
# ---------------------------------------------------------------------------


class TestGetCommitHash:
    """Tests for get_commit_hash() helper."""

    def test_returns_string(self) -> None:
        result = get_commit_hash()
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("tests.e2e.framework.baseline_manager.subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run) -> None:
        mock_run.side_effect = FileNotFoundError("git not found")
        result = get_commit_hash()
        assert result == "unknown"

    @patch("tests.e2e.framework.baseline_manager.subprocess.run")
    def test_returns_unknown_on_timeout(self, mock_run) -> None:
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="git", timeout=10)
        result = get_commit_hash()
        assert result == "unknown"
