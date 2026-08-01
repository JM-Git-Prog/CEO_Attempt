"""Versioned golden baseline manager for E2E visual regression tests.

Manages golden baselines organized under:
    tests/e2e/baselines/{model_version}/{hardware_id}/

Each baseline PNG has a JSON sidecar metadata file (*.meta.json) containing
creation timestamp, commit hash, model version, hardware ID, camera pose,
and approval information.

When no baseline exists for a stage, the test module should treat this as
"baseline created" (not a failure) — satisfying Requirement 3.3.

Baselines from different model versions NEVER share a directory (Property 5).

Requirements: 3.3, 4.1, 4.2, 4.3
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union


# Base directory for all baselines (relative to project root)
_BASELINES_BASE = Path(__file__).resolve().parent.parent / "baselines"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineMetadata:
    """Metadata sidecar for a golden baseline image.

    Attributes:
        created_at: ISO 8601 timestamp of baseline creation.
        commit_hash: Git commit hash at time of baseline creation.
        model_version: Pipeline model version identifier.
        hardware_id: GPU model + driver version identifier.
        viewport: Capture viewport dimensions as [width, height].
        stage: Pipeline stage name.
        camera_pose: Camera pose used for capture.
        deterministic_seed: RNG seed used for deterministic rendering.
        approved_by: PR or user that approved the baseline (null if pending).
        approved_at: ISO 8601 timestamp of approval (null if pending).
    """

    created_at: str
    commit_hash: str
    model_version: str
    hardware_id: str
    viewport: list[int]
    stage: str
    camera_pose: dict[str, Any]
    deterministic_seed: int = 42
    approved_by: str | None = None
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata to a plain dictionary for JSON output."""
        return {
            "created_at": self.created_at,
            "commit_hash": self.commit_hash,
            "model_version": self.model_version,
            "hardware_id": self.hardware_id,
            "viewport": self.viewport,
            "stage": self.stage,
            "camera_pose": self.camera_pose,
            "deterministic_seed": self.deterministic_seed,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineMetadata:
        """Deserialize metadata from a dictionary.

        Args:
            data: Dictionary with metadata fields.

        Returns:
            A BaselineMetadata instance.

        Raises:
            ValueError: If required fields are missing.
        """
        required_keys = {
            "created_at",
            "commit_hash",
            "model_version",
            "hardware_id",
            "viewport",
            "stage",
            "camera_pose",
        }
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"BaselineMetadata missing required keys: {sorted(missing)}"
            )
        return cls(
            created_at=data["created_at"],
            commit_hash=data["commit_hash"],
            model_version=data["model_version"],
            hardware_id=data["hardware_id"],
            viewport=list(data["viewport"]),
            stage=data["stage"],
            camera_pose=data["camera_pose"],
            deterministic_seed=data.get("deterministic_seed", 42),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
        )


@dataclass(frozen=True)
class BaselineResult:
    """Result of a baseline retrieval operation.

    Attributes:
        image_path: Path to the baseline PNG file.
        metadata: Parsed metadata sidecar.
        image_data: Raw image bytes (loaded lazily if None).
    """

    image_path: Path
    metadata: BaselineMetadata
    image_data: bytes | None = None


@dataclass(frozen=True)
class SaveBaselineResult:
    """Result of saving a new baseline.

    Attributes:
        image_path: Path where the baseline PNG was stored.
        metadata_path: Path where the JSON sidecar was stored.
        metadata: The metadata that was written.
        is_new: True if this was the first baseline for this stage/version/hw.
    """

    image_path: Path
    metadata_path: Path
    metadata: BaselineMetadata
    is_new: bool


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BaselineManagerError(Exception):
    """Raised when baseline management operations fail."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_commit_hash() -> str:
    """Get the current git commit hash.

    Uses `git rev-parse HEAD` and falls back to "unknown" if git is
    unavailable or not in a repository.

    Returns:
        Short commit hash string, or "unknown".
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class BaselineManager:
    """Manages versioned golden baselines for visual regression tests.

    Baselines are organized under:
        {base_dir}/{model_version}/{hardware_id}/
        ├── dream_preview.png
        ├── dream_preview.meta.json
        ├── blockout.png
        ├── blockout.meta.json
        ├── canon.png
        ├── canon.meta.json
        ├── world.png
        └── world.meta.json

    Key behaviors:
    - get_baseline() returns None when no baseline exists (not an error)
    - baseline_exists() returns False when no baseline exists
    - save_baseline() creates directories as needed and writes both PNG + JSON
    - Baselines from different model versions NEVER share a directory (Property 5)

    Usage:
        manager = BaselineManager(
            model_version="v16-model-a1b2c3",
            hardware_id="rtx4090-driver560-ab12cd34",
        )

        # Check and retrieve
        if manager.baseline_exists("canon"):
            result = manager.get_baseline("canon")
            # result.image_data, result.metadata available
        else:
            # No baseline — treat as "baseline created" (Req 3.3)
            manager.save_baseline("canon", image_data, metadata_kwargs)
    """

    def __init__(
        self,
        model_version: str,
        hardware_id: str,
        base_dir: Union[str, Path, None] = None,
    ) -> None:
        """Initialize the baseline manager.

        Args:
            model_version: Pipeline model version identifier
                          (e.g. "v16-model-a1b2c3").
            hardware_id: Hardware identifier from detect_hardware_id()
                        (e.g. "rtx4090-driver560-ab12cd34").
            base_dir: Override the default baselines base directory.
                     Defaults to tests/e2e/baselines/.

        Raises:
            BaselineManagerError: If model_version or hardware_id is empty.
        """
        if not model_version or not model_version.strip():
            raise BaselineManagerError(
                "model_version must be a non-empty string"
            )
        if not hardware_id or not hardware_id.strip():
            raise BaselineManagerError(
                "hardware_id must be a non-empty string"
            )

        self._model_version = model_version.strip()
        self._hardware_id = hardware_id.strip()
        self._base_dir = Path(base_dir) if base_dir else _BASELINES_BASE
        self._baseline_dir = self._base_dir / self._model_version / self._hardware_id

    @property
    def model_version(self) -> str:
        """The pipeline model version."""
        return self._model_version

    @property
    def hardware_id(self) -> str:
        """The hardware identifier."""
        return self._hardware_id

    @property
    def baseline_dir(self) -> Path:
        """The directory where baselines for this version/hardware are stored."""
        return self._baseline_dir

    def get_baseline(
        self,
        stage: str,
        model_version: str | None = None,
        hardware_id: str | None = None,
    ) -> BaselineResult | None:
        """Retrieve the golden baseline for a given stage.

        Looks up the baseline PNG and its JSON sidecar metadata for the
        specified stage. If model_version or hardware_id are provided, they
        override the instance defaults (for cross-version lookup).

        When no baseline exists, returns None (Requirement 3.3 — not a failure).

        Args:
            stage: Pipeline stage name (e.g. "canon", "dream_preview").
            model_version: Override model version. Defaults to instance value.
            hardware_id: Override hardware ID. Defaults to instance value.

        Returns:
            BaselineResult with image path, metadata, and image data.
            None if no baseline exists.

        Raises:
            BaselineManagerError: If the baseline file exists but is corrupted
                                  or the metadata is invalid.
        """
        if not stage or not stage.strip():
            raise BaselineManagerError("stage must be a non-empty string")

        # Determine the directory to look in
        lookup_dir = self._resolve_dir(model_version, hardware_id)
        image_path = lookup_dir / f"{stage}.png"
        meta_path = lookup_dir / f"{stage}.meta.json"

        # No baseline exists — return None (Req 3.3)
        if not image_path.exists():
            return None

        # Load image data
        try:
            image_data = image_path.read_bytes()
        except OSError as e:
            raise BaselineManagerError(
                f"Failed to read baseline image at '{image_path}': {e}"
            ) from e

        # Load metadata sidecar
        metadata = self._load_metadata(meta_path, stage)

        return BaselineResult(
            image_path=image_path,
            metadata=metadata,
            image_data=image_data,
        )

    def save_baseline(
        self,
        stage: str,
        image: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> SaveBaselineResult:
        """Save a new golden baseline for a stage.

        Creates the directory structure if needed, writes the PNG file,
        and generates the JSON sidecar metadata file.

        Args:
            stage: Pipeline stage name (e.g. "canon", "dream_preview").
            image: PNG image data as bytes.
            metadata: Optional metadata overrides. Supported keys:
                      camera_pose, viewport, deterministic_seed,
                      approved_by, approved_at.
                      Defaults are auto-generated for timestamp, commit, etc.

        Returns:
            SaveBaselineResult with paths and metadata.

        Raises:
            BaselineManagerError: If stage is empty, image is empty,
                                  or write operations fail.
        """
        if not stage or not stage.strip():
            raise BaselineManagerError("stage must be a non-empty string")
        if not image:
            raise BaselineManagerError("image data must not be empty")

        stage = stage.strip()
        metadata = metadata or {}

        # Determine if this is a new baseline
        is_new = not self.baseline_exists(stage)

        # Ensure directory exists
        try:
            self._baseline_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BaselineManagerError(
                f"Failed to create baseline directory '{self._baseline_dir}': {e}"
            ) from e

        # Build file paths
        image_path = self._baseline_dir / f"{stage}.png"
        meta_path = self._baseline_dir / f"{stage}.meta.json"

        # Build metadata
        now = datetime.now(timezone.utc)
        baseline_meta = BaselineMetadata(
            created_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            commit_hash=get_commit_hash(),
            model_version=self._model_version,
            hardware_id=self._hardware_id,
            viewport=metadata.get("viewport", [1920, 1080]),
            stage=stage,
            camera_pose=metadata.get("camera_pose", {
                "position": [0, 1.6, 3.0],
                "target": [0, 1.0, 0],
                "up": [0, 1, 0],
                "vfov": 60,
            }),
            deterministic_seed=metadata.get("deterministic_seed", 42),
            approved_by=metadata.get("approved_by"),
            approved_at=metadata.get("approved_at"),
        )

        # Write image file
        try:
            image_path.write_bytes(image)
        except OSError as e:
            raise BaselineManagerError(
                f"Failed to write baseline image '{image_path}': {e}"
            ) from e

        # Write metadata sidecar
        try:
            meta_json = json.dumps(baseline_meta.to_dict(), indent=2)
            meta_path.write_text(meta_json, encoding="utf-8")
        except (OSError, TypeError) as e:
            raise BaselineManagerError(
                f"Failed to write baseline metadata '{meta_path}': {e}"
            ) from e

        return SaveBaselineResult(
            image_path=image_path,
            metadata_path=meta_path,
            metadata=baseline_meta,
            is_new=is_new,
        )

    def baseline_exists(self, stage: str) -> bool:
        """Check whether a golden baseline exists for the given stage.

        Args:
            stage: Pipeline stage name (e.g. "canon", "dream_preview").

        Returns:
            True if a baseline PNG exists for this stage, model version,
            and hardware ID. False otherwise.

        Raises:
            BaselineManagerError: If stage is empty.
        """
        if not stage or not stage.strip():
            raise BaselineManagerError("stage must be a non-empty string")

        image_path = self._baseline_dir / f"{stage.strip()}.png"
        return image_path.exists()

    def list_stages(self) -> list[str]:
        """List all stages that have baselines in the current version/hardware directory.

        Returns:
            List of stage names that have baseline PNGs.
        """
        if not self._baseline_dir.exists():
            return []

        stages = []
        for path in sorted(self._baseline_dir.glob("*.png")):
            stages.append(path.stem)
        return stages

    def _resolve_dir(
        self,
        model_version: str | None,
        hardware_id: str | None,
    ) -> Path:
        """Resolve the baseline directory for optional overrides.

        Args:
            model_version: Optional override model version.
            hardware_id: Optional override hardware ID.

        Returns:
            The resolved baseline directory path.
        """
        mv = model_version or self._model_version
        hw = hardware_id or self._hardware_id
        return self._base_dir / mv / hw

    def _load_metadata(self, meta_path: Path, stage: str) -> BaselineMetadata:
        """Load and parse a metadata sidecar JSON file.

        If the metadata file doesn't exist, returns a minimal metadata object
        with "unknown" values for backwards compatibility.

        Args:
            meta_path: Path to the .meta.json file.
            stage: The stage name (used for fallback metadata).

        Returns:
            Parsed BaselineMetadata instance.

        Raises:
            BaselineManagerError: If the file exists but is corrupt/unparseable.
        """
        if not meta_path.exists():
            # Backwards compatibility: baseline exists but no metadata
            return BaselineMetadata(
                created_at="unknown",
                commit_hash="unknown",
                model_version=self._model_version,
                hardware_id=self._hardware_id,
                viewport=[1920, 1080],
                stage=stage,
                camera_pose={},
            )

        try:
            raw_text = meta_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as e:
            raise BaselineManagerError(
                f"Failed to read or parse baseline metadata at "
                f"'{meta_path}': {e}"
            ) from e

        if not isinstance(data, dict):
            raise BaselineManagerError(
                f"Baseline metadata at '{meta_path}' must be a JSON object, "
                f"got {type(data).__name__}"
            )

        try:
            return BaselineMetadata.from_dict(data)
        except (ValueError, TypeError) as e:
            raise BaselineManagerError(
                f"Invalid baseline metadata at '{meta_path}': {e}"
            ) from e
