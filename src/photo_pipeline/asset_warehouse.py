"""Persistent, append-only asset library organized by game industry taxonomy.

The Asset Warehouse catalogs every generated GLB asset with extensive metadata,
organized into five category directories following game development conventions.
Assets persist across sessions and are never overwritten or deleted.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.3
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.photo_pipeline.models_v14 import AssetRegistryEntry


class AssetWarehouse:
    """Persistent modular asset library organized by game industry taxonomy.

    Directory structure:
        assets/
        ├── props/
        ├── architecture/
        ├── foliage/
        ├── hard-surface/
        └── set-dressing/

    Behavior:
    - Append-only: never overwrites or deletes existing files.
    - Session-independent: assets persist across pipeline runs.
    - Filenames use pattern: {semantic_label_slug}_{session_short}_{mask_id}.glb
    """

    CATEGORIES = ("props", "architecture", "foliage", "hard-surface", "set-dressing")
    BASE_DIR = Path("assets")

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize the Asset Warehouse.

        Args:
            base_dir: Root directory for the warehouse. Defaults to 'assets/'.
        """
        self._base_dir = base_dir if base_dir is not None else self.BASE_DIR

    @property
    def base_dir(self) -> Path:
        """Return the base directory for the warehouse."""
        return self._base_dir

    def save_asset(
        self,
        glb_path: Path,
        registry: AssetRegistryEntry,
    ) -> Path:
        """Copy GLB to category dir, write JSON registry. Returns saved path.

        The GLB file is copied into the appropriate category directory based on
        registry.category. A JSON metadata file (same name, .json extension) is
        written alongside it containing the serialized AssetRegistryEntry.

        This method is append-only: if a filename collision occurs, a numeric
        suffix is appended to guarantee uniqueness. Existing files are never
        overwritten or deleted.

        Args:
            glb_path: Path to the source GLB file to catalog.
            registry: Metadata entry describing the asset.

        Returns:
            The destination path where the GLB was saved.

        Raises:
            FileNotFoundError: If the source GLB file does not exist.
            ValueError: If registry.category is not a valid category.
        """
        if not glb_path.exists():
            raise FileNotFoundError(f"Source GLB file not found: {glb_path}")

        if registry.category not in self.CATEGORIES:
            raise ValueError(
                f"Invalid category '{registry.category}'. "
                f"Must be one of {self.CATEGORIES}"
            )

        # Ensure directory structure exists
        self.ensure_structure()

        # Determine destination directory
        category_dir = self._base_dir / registry.category

        # Generate the filename
        filename = self._generate_filename(
            label=registry.semantic_label,
            session_id=registry.source_session_id,
            mask_id=registry.name.rsplit("_", 1)[-1] if "_" in registry.name else registry.name,
        )

        # Resolve collision with numeric suffix (append-only: never overwrite)
        dest_path = category_dir / filename
        dest_path = self._resolve_collision(dest_path)

        # Copy GLB file
        shutil.copy2(str(glb_path), str(dest_path))

        # Write JSON registry file alongside
        json_path = dest_path.with_suffix(".json")
        json_path.write_text(registry.to_json(), encoding="utf-8")

        return dest_path

    def _generate_filename(self, label: str, session_id: str, mask_id: str) -> str:
        """Generate filename: {semantic_label_slug}_{session_short}_{mask_id}.glb

        The semantic label is slugified:
        - Lowercase
        - Spaces replaced with hyphens
        - Special characters stripped (only alphanumeric and hyphens kept)
        - Leading/trailing hyphens removed
        - Multiple consecutive hyphens collapsed

        Session ID is truncated to first 6 characters.

        Args:
            label: The semantic label (e.g., "wooden dining chair").
            session_id: The full session ID.
            mask_id: The mask identifier for this object.

        Returns:
            A filename string ending in .glb.
        """
        # Slugify the label
        slug = label.lower()
        slug = slug.replace(" ", "-")
        # Strip everything except alphanumeric and hyphens
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        # Collapse multiple hyphens
        slug = re.sub(r"-{2,}", "-", slug)
        # Strip leading/trailing hyphens
        slug = slug.strip("-")

        # Fallback if slug is empty after processing
        if not slug:
            slug = "asset"

        # First 6 chars of session_id
        session_short = session_id[:6]

        return f"{slug}_{session_short}_{mask_id}.glb"

    def ensure_structure(self) -> None:
        """Create category directories if they don't exist.

        Creates the base directory and all five category subdirectories
        on first run. Safe to call multiple times (idempotent).
        """
        self._base_dir.mkdir(parents=True, exist_ok=True)
        for category in self.CATEGORIES:
            (self._base_dir / category).mkdir(parents=True, exist_ok=True)

    def _resolve_collision(self, dest_path: Path) -> Path:
        """Resolve filename collision by appending a numeric suffix.

        If the destination path already exists, appends _1, _2, etc.
        before the .glb extension until a unique path is found.

        Args:
            dest_path: The initially desired destination path.

        Returns:
            A path that does not currently exist on disk.
        """
        if not dest_path.exists():
            return dest_path

        stem = dest_path.stem
        suffix = dest_path.suffix
        parent = dest_path.parent
        counter = 1

        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
