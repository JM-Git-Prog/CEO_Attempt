"""Per-run artifact store for E2E test output management.

Organizes test artifacts under tests/e2e/artifacts/{run_id}/ with subdirectories
for each test layer: visual, perceptual, scene, accessibility, gpu, vision_qa.

Requirements: 23.4, 23.5
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

# Valid layer subdirectories for artifact organization
ARTIFACT_LAYERS = frozenset(
    ["visual", "perceptual", "scene", "accessibility", "gpu", "vision_qa"]
)

# Base directory for all artifacts (relative to project root)
_ARTIFACTS_BASE = Path(__file__).resolve().parent.parent / "artifacts"


class ArtifactStoreError(Exception):
    """Raised when artifact store operations fail."""


class ArtifactStore:
    """Manages per-run test artifact storage.

    Artifacts are organized under:
        tests/e2e/artifacts/{run_id}/
        ├── visual/
        ├── perceptual/
        ├── scene/
        ├── accessibility/
        ├── gpu/
        └── vision_qa/

    Usage:
        store = ArtifactStore()
        store.init_run("20260730-143000-abc123")
        store.store_artifact("visual", "canon_diff.png", diff_image_bytes)
        path = store.get_artifact_path("visual", "canon_diff.png")
    """

    def __init__(self, base_dir: Union[str, Path, None] = None) -> None:
        """Initialize artifact store.

        Args:
            base_dir: Override the default artifacts base directory.
                      Defaults to tests/e2e/artifacts/.
        """
        self._base_dir = Path(base_dir) if base_dir else _ARTIFACTS_BASE
        self._run_id: str | None = None
        self._run_dir: Path | None = None

    @property
    def run_id(self) -> str | None:
        """The current run identifier."""
        return self._run_id

    @property
    def run_dir(self) -> Path | None:
        """The current run directory path, or None if not initialized."""
        return self._run_dir

    def init_run(self, run_id: str) -> Path:
        """Initialize a new test run directory with all layer subdirectories.

        Creates the run directory and all layer subdirectories. Safe to call
        multiple times with the same run_id (idempotent).

        Args:
            run_id: Unique identifier for the test run (e.g. timestamp + hash).

        Returns:
            The path to the created run directory.

        Raises:
            ArtifactStoreError: If run_id is empty or directory creation fails.
        """
        if not run_id or not run_id.strip():
            raise ArtifactStoreError("run_id must be a non-empty string")

        self._run_id = run_id
        self._run_dir = self._base_dir / run_id

        # Create run directory and all layer subdirectories
        try:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            for layer in sorted(ARTIFACT_LAYERS):
                (self._run_dir / layer).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ArtifactStoreError(
                f"Failed to create artifact directories for run '{run_id}': {e}"
            ) from e

        return self._run_dir

    def store_artifact(
        self, layer: str, filename: str, data: Union[bytes, str]
    ) -> Path:
        """Store an artifact file in the appropriate layer subdirectory.

        Args:
            layer: The test layer (visual, perceptual, scene, accessibility,
                   gpu, or vision_qa).
            filename: The artifact filename (e.g. "canon_diff.png").
            data: The artifact content — bytes for binary files, str for text.

        Returns:
            The full path to the stored artifact file.

        Raises:
            ArtifactStoreError: If run not initialized, invalid layer, or
                                write fails.
        """
        self._ensure_initialized()
        self._validate_layer(layer)

        if not filename or not filename.strip():
            raise ArtifactStoreError("filename must be a non-empty string")

        artifact_path = self._run_dir / layer / filename

        try:
            # Create any intermediate directories in the filename path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)

            if isinstance(data, bytes):
                artifact_path.write_bytes(data)
            else:
                artifact_path.write_text(data, encoding="utf-8")
        except OSError as e:
            raise ArtifactStoreError(
                f"Failed to write artifact '{filename}' in layer '{layer}': {e}"
            ) from e

        return artifact_path

    def get_artifact_path(self, layer: str, filename: str) -> Path:
        """Get the full filesystem path for an artifact.

        Returns the path regardless of whether the file exists yet.
        Useful for constructing paths before writing or for retrieval.

        Args:
            layer: The test layer (visual, perceptual, scene, accessibility,
                   gpu, or vision_qa).
            filename: The artifact filename.

        Returns:
            The full path to the artifact file.

        Raises:
            ArtifactStoreError: If run not initialized or invalid layer.
        """
        self._ensure_initialized()
        self._validate_layer(layer)

        if not filename or not filename.strip():
            raise ArtifactStoreError("filename must be a non-empty string")

        return self._run_dir / layer / filename

    def failure_message(self, layer: str, test_name: str, details: str) -> str:
        """Format a pytest failure message that includes the artifact directory path.

        Satisfies Requirement 23.5: test failure output includes the artifact
        directory path for immediate developer access.

        Args:
            layer: The test layer where the failure occurred.
            test_name: Name of the failing test.
            details: Description of the failure.

        Returns:
            A formatted failure message string including the artifact path.
        """
        self._ensure_initialized()
        layer_dir = self._run_dir / layer if layer in ARTIFACT_LAYERS else self._run_dir

        return (
            f"FAILED: {test_name}\n"
            f"{details}\n"
            f"\n"
            f"Artifacts: {layer_dir}\n"
            f"Run directory: {self._run_dir}"
        )

    def _ensure_initialized(self) -> None:
        """Verify that init_run has been called."""
        if self._run_dir is None:
            raise ArtifactStoreError(
                "ArtifactStore not initialized. Call init_run(run_id) first."
            )

    def _validate_layer(self, layer: str) -> None:
        """Validate that the layer name is one of the known layers."""
        if layer not in ARTIFACT_LAYERS:
            raise ArtifactStoreError(
                f"Invalid layer '{layer}'. Must be one of: "
                f"{', '.join(sorted(ARTIFACT_LAYERS))}"
            )
