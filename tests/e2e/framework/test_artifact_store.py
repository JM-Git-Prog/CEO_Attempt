"""Unit tests for the ArtifactStore module.

Tests directory creation, file storage, path retrieval, and failure messaging.
"""
import pytest

from tests.e2e.framework.artifact_store import (
    ARTIFACT_LAYERS,
    ArtifactStore,
    ArtifactStoreError,
)


class TestArtifactStoreInitRun:
    """Tests for ArtifactStore.init_run()."""

    def test_creates_run_directory(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        run_dir = store.init_run("run-001")
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_creates_all_layer_subdirectories(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")

        for layer in ARTIFACT_LAYERS:
            layer_dir = tmp_path / "run-001" / layer
            assert layer_dir.exists(), f"Missing layer directory: {layer}"
            assert layer_dir.is_dir()

    def test_returns_run_directory_path(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        run_dir = store.init_run("run-001")
        assert run_dir == tmp_path / "run-001"

    def test_sets_run_id_property(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("my-run-id")
        assert store.run_id == "my-run-id"

    def test_sets_run_dir_property(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("my-run-id")
        assert store.run_dir == tmp_path / "my-run-id"

    def test_idempotent_on_repeated_calls(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        # Store a file
        store.store_artifact("visual", "test.txt", "hello")
        # Re-init same run — should not destroy existing files
        store.init_run("run-001")
        assert (tmp_path / "run-001" / "visual" / "test.txt").exists()

    def test_empty_run_id_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        with pytest.raises(ArtifactStoreError, match="non-empty"):
            store.init_run("")

    def test_whitespace_only_run_id_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        with pytest.raises(ArtifactStoreError, match="non-empty"):
            store.init_run("   ")


class TestArtifactStoreStoreArtifact:
    """Tests for ArtifactStore.store_artifact()."""

    def test_stores_binary_data(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake PNG header
        path = store.store_artifact("visual", "screenshot.png", data)
        assert path.exists()
        assert path.read_bytes() == data

    def test_stores_text_data(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        data = '{"ssim": 0.92, "lpips": 0.15}'
        path = store.store_artifact("perceptual", "metrics.json", data)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == data

    def test_returns_correct_path(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        path = store.store_artifact("gpu", "flux_output.png", b"data")
        assert path == tmp_path / "run-001" / "gpu" / "flux_output.png"

    def test_stores_in_correct_layer_directory(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        store.store_artifact("accessibility", "axe_report.json", '{"violations": []}')
        assert (tmp_path / "run-001" / "accessibility" / "axe_report.json").exists()

    def test_invalid_layer_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ArtifactStoreError, match="Invalid layer"):
            store.store_artifact("unknown_layer", "file.txt", "data")

    def test_not_initialized_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        with pytest.raises(ArtifactStoreError, match="not initialized"):
            store.store_artifact("visual", "file.txt", "data")

    def test_empty_filename_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ArtifactStoreError, match="non-empty"):
            store.store_artifact("visual", "", "data")

    def test_handles_nested_filename_paths(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        path = store.store_artifact("scene", "objects/door_01.json", '{"state": "open"}')
        assert path.exists()
        assert path.parent.name == "objects"


class TestArtifactStoreGetArtifactPath:
    """Tests for ArtifactStore.get_artifact_path()."""

    def test_returns_expected_path(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        path = store.get_artifact_path("visual", "baseline.png")
        assert path == tmp_path / "run-001" / "visual" / "baseline.png"

    def test_path_returned_regardless_of_file_existence(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        path = store.get_artifact_path("perceptual", "nonexistent.json")
        # Should return path even if file doesn't exist
        assert not path.exists()
        assert path == tmp_path / "run-001" / "perceptual" / "nonexistent.json"

    def test_invalid_layer_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ArtifactStoreError, match="Invalid layer"):
            store.get_artifact_path("invalid", "file.txt")

    def test_not_initialized_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        with pytest.raises(ArtifactStoreError, match="not initialized"):
            store.get_artifact_path("visual", "file.txt")

    def test_empty_filename_raises_error(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        with pytest.raises(ArtifactStoreError, match="non-empty"):
            store.get_artifact_path("visual", "")


class TestArtifactStoreFailureMessage:
    """Tests for ArtifactStore.failure_message() — Requirement 23.5."""

    def test_includes_artifact_directory_path(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        msg = store.failure_message("visual", "test_canon_diff", "Pixel diff exceeded 0.1%")
        assert str(tmp_path / "run-001" / "visual") in msg

    def test_includes_run_directory_path(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        msg = store.failure_message("visual", "test_canon_diff", "Pixel diff exceeded 0.1%")
        assert str(tmp_path / "run-001") in msg

    def test_includes_test_name(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        msg = store.failure_message("scene", "test_object_count", "Expected 5, got 3")
        assert "test_object_count" in msg

    def test_includes_failure_details(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        store.init_run("run-001")
        msg = store.failure_message("perceptual", "test_ssim", "SSIM 0.72 < 0.85")
        assert "SSIM 0.72 < 0.85" in msg


class TestArtifactStoreLayers:
    """Tests validating the layer constants match the design spec."""

    def test_all_specified_layers_present(self):
        expected = {"visual", "perceptual", "scene", "accessibility", "gpu", "vision_qa"}
        assert ARTIFACT_LAYERS == expected

    def test_layers_is_immutable(self):
        # ARTIFACT_LAYERS is a frozenset — verify it can't be mutated
        with pytest.raises(AttributeError):
            ARTIFACT_LAYERS.add("new_layer")
