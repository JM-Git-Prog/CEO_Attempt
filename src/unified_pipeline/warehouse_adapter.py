"""Unified pipeline warehouse adapter — wraps V14 AssetWarehouse for unified models.

Provides a clean adapter layer that accepts unified pipeline models
(ObjectInstance, ApprovedAssetRecord) and delegates persistence to the
existing append-only V14 AssetWarehouse. Enforces the always-fresh rule:
the warehouse is never consulted before generation.

Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.photo_pipeline.asset_warehouse import AssetWarehouse
from src.photo_pipeline.models_v14 import AssetRegistryEntry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = ("props", "architecture", "foliage", "hard-surface", "set-dressing")
VALID_CONDITIONS = ("new", "worn", "broken")
VALID_MATERIALS = ("wood", "metal", "glass", "fabric", "ceramic", "plastic")
VALID_GENERATION_METHODS = ("hunyuan3d_v2.1", "trellis2")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WarehouseAdapterError(Exception):
    """Raised when the warehouse adapter detects an invalid operation."""


class PreGenerationLookupError(WarehouseAdapterError):
    """Raised when caller attempts to consult the warehouse before generation."""


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnifiedAssetEntry:
    """Complete metadata entry for a unified pipeline asset.

    Extends the V14 AssetRegistryEntry fields with:
    - game_properties: dict or None for game overlay bindings by UUID
    - real_bindings: dict or None for real overlay bindings by UUID
    - source_prompt: the original user prompt
    - object_canon_ref: reference to the approved ObjectCanon image
    - generation_seed: seed used for mesh generation
    - workflow_params: generation workflow parameters
    - approval_timestamp: ISO timestamp of mesh approval
    """

    # Core identity
    name: str
    semantic_label: str
    category: str
    era: str
    condition: str
    material_type: str

    # Physical
    dimensions_m: tuple[float, float, float]
    weight_estimate_kg: float

    # Generation provenance
    generation_method: str
    source_session_id: str
    face_count: int
    vertex_count: int
    has_pbr_textures: bool

    # Extended unified fields
    game_properties: dict[str, Any] | None = None
    real_bindings: dict[str, Any] | None = None
    source_prompt: str = ""
    object_canon_ref: str = ""
    generation_seed: int = 0
    workflow_params: dict[str, Any] = field(default_factory=dict)
    approval_timestamp: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise WarehouseAdapterError("name must not be empty")
        if not self.semantic_label:
            raise WarehouseAdapterError("semantic_label must not be empty")
        if self.category not in VALID_CATEGORIES:
            raise WarehouseAdapterError(
                f"category must be one of {VALID_CATEGORIES}, got '{self.category}'"
            )
        if self.condition not in VALID_CONDITIONS:
            raise WarehouseAdapterError(
                f"condition must be one of {VALID_CONDITIONS}, got '{self.condition}'"
            )
        if self.material_type not in VALID_MATERIALS:
            raise WarehouseAdapterError(
                f"material_type must be one of {VALID_MATERIALS}, got '{self.material_type}'"
            )
        if len(self.dimensions_m) != 3 or any(d <= 0 for d in self.dimensions_m):
            raise WarehouseAdapterError("dimensions_m must be 3 positive floats")
        if self.weight_estimate_kg < 0:
            raise WarehouseAdapterError("weight_estimate_kg must be >= 0")
        if self.generation_method not in VALID_GENERATION_METHODS:
            raise WarehouseAdapterError(
                f"generation_method must be one of {VALID_GENERATION_METHODS}, "
                f"got '{self.generation_method}'"
            )
        if not self.source_session_id:
            raise WarehouseAdapterError("source_session_id must not be empty")
        if self.face_count < 1:
            raise WarehouseAdapterError("face_count must be >= 1")
        if self.vertex_count < 1:
            raise WarehouseAdapterError("vertex_count must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary with all extended fields."""
        return {
            "name": self.name,
            "semantic_label": self.semantic_label,
            "category": self.category,
            "era": self.era,
            "condition": self.condition,
            "material_type": self.material_type,
            "dimensions_m": list(self.dimensions_m),
            "weight_estimate_kg": self.weight_estimate_kg,
            "generation_method": self.generation_method,
            "source_session_id": self.source_session_id,
            "face_count": self.face_count,
            "vertex_count": self.vertex_count,
            "has_pbr_textures": self.has_pbr_textures,
            "game_properties": self.game_properties,
            "real_bindings": self.real_bindings,
            "source_prompt": self.source_prompt,
            "object_canon_ref": self.object_canon_ref,
            "generation_seed": self.generation_seed,
            "workflow_params": dict(self.workflow_params),
            "approval_timestamp": self.approval_timestamp,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize to canonical JSON (sorted keys, 2-space indent)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class UnifiedWarehouseAdapter:
    """Wraps the existing V14 AssetWarehouse to accept unified pipeline models.

    Behavior:
    - Append-only: never overwrites or deletes existing files.
    - Session-independent: assets persist across pipeline runs.
    - Always-fresh: the warehouse is never consulted before generation.
      Any pre-generation lookup attempt raises PreGenerationLookupError.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize the adapter wrapping an AssetWarehouse instance.

        Args:
            base_dir: Root directory for asset storage. Defaults to 'assets/'.
        """
        self._warehouse = AssetWarehouse(base_dir)

    @property
    def base_dir(self) -> Path:
        """Return the base directory of the underlying warehouse."""
        return self._warehouse.base_dir

    def lookup_asset(self, *args: Any, **kwargs: Any) -> None:
        """Pre-generation lookup is forbidden (always-fresh rule).

        Raises:
            PreGenerationLookupError: Always. The warehouse is append-only
                and must never be consulted before generation.
        """
        raise PreGenerationLookupError(
            "Warehouse is append-only and never consulted before generation. "
            "The always-fresh rule requires each asset to be generated independently."
        )

    def find_existing(self, *args: Any, **kwargs: Any) -> None:
        """Pre-generation search is forbidden (always-fresh rule).

        Raises:
            PreGenerationLookupError: Always.
        """
        raise PreGenerationLookupError(
            "Warehouse is append-only and never consulted before generation. "
            "The always-fresh rule requires each asset to be generated independently."
        )

    def catalog_approved_mesh(
        self,
        glb_path: Path,
        entry: UnifiedAssetEntry,
        *,
        mask_id: str | None = None,
        game_overlay_data: dict[str, Any] | None = None,
        real_overlay_data: dict[str, Any] | None = None,
    ) -> Path:
        """Catalog an approved generated mesh into the warehouse.

        Writes the GLB file and a JSON sidecar with the full unified metadata
        registry into the appropriate category directory. The operation is
        append-only: collisions are resolved by appending a numeric suffix.

        Args:
            glb_path: Path to the approved GLB mesh file.
            entry: Complete metadata entry for the asset.
            mask_id: Mask identifier for filename construction.
            game_overlay_data: Optional game overlay bindings (stored as-is).
            real_overlay_data: Optional real overlay bindings (stored as-is).

        Returns:
            The destination path where the GLB was saved.

        Raises:
            FileNotFoundError: If glb_path does not exist.
            WarehouseAdapterError: If entry is invalid.
        """
        if not glb_path.exists():
            raise FileNotFoundError(f"Source GLB file not found: {glb_path}")

        if glb_path.suffix.casefold() != ".glb":
            raise WarehouseAdapterError("Only GLB files can be cataloged")

        # Merge overlay data into entry if provided
        game_props = game_overlay_data if game_overlay_data is not None else entry.game_properties
        real_binds = real_overlay_data if real_overlay_data is not None else entry.real_bindings

        # Compute created_at if not provided
        created_at = entry.created_at or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

        # Build the extended JSON sidecar data
        registry_data = entry.to_dict()
        registry_data["game_properties"] = game_props
        registry_data["real_bindings"] = real_binds
        registry_data["created_at"] = created_at

        # Build asset card
        registry_data["asset_card"] = {
            "source_prompt": entry.source_prompt,
            "object_canon_ref": entry.object_canon_ref,
            "generation_seed": entry.generation_seed,
            "workflow_params": dict(entry.workflow_params),
            "approval_timestamp": entry.approval_timestamp,
            "tri_count": entry.face_count,
        }

        # Ensure warehouse directory structure exists
        self._warehouse.ensure_structure()

        # Determine destination
        category_dir = self._warehouse.base_dir / entry.category
        resolved_mask_id = mask_id or entry.name.rsplit("_", 1)[-1] if "_" in entry.name else (mask_id or entry.name)

        filename = self._warehouse._generate_filename(
            label=entry.semantic_label,
            session_id=entry.source_session_id,
            mask_id=resolved_mask_id,
        )

        # Resolve collision (append-only: never overwrite)
        dest_path = category_dir / filename
        dest_path = self._resolve_collision(dest_path)

        # Copy GLB
        import shutil
        shutil.copy2(str(glb_path), str(dest_path))

        # Write JSON sidecar
        json_path = dest_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(registry_data, sort_keys=True, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return dest_path

    def _resolve_collision(self, dest_path: Path) -> Path:
        """Resolve filename collision preserving both GLB and JSON sidecars.

        If either the GLB or its JSON sidecar already exists, appends a
        numeric suffix until a unique pair of paths is found.
        """
        if not dest_path.exists() and not dest_path.with_suffix(".json").exists():
            return dest_path

        stem = dest_path.stem
        suffix = dest_path.suffix
        parent = dest_path.parent
        counter = 1

        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists() and not candidate.with_suffix(".json").exists():
                return candidate
            counter += 1
