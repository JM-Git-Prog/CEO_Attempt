"""Post-generation Asset Warehouse adapter for the Unified World Pipeline.

Reuses the V14 append-only warehouse while accepting unified ObjectCanon,
MeshApproval, GAME, and REAL models. This module deliberately exposes no
pre-generation lookup or reuse API.

Requirements: 26.1-26.6
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.photo_pipeline.asset_warehouse import AssetWarehouse
from src.unified_pipeline.models import MeshApproval, ObjectCanon


class WarehouseCatalogError(ValueError):
    """Raised when an asset is not eligible for append-only cataloging."""


def _json_copy(value: Any) -> Any:
    """Return a detached, finite JSON-compatible value."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise WarehouseCatalogError("warehouse metadata must be JSON-compatible") from exc


@dataclass(frozen=True)
class WarehouseCatalogMetadata:
    """Metadata not carried directly by ObjectCanon or MeshApproval."""

    semantic_label: str
    category: str
    era: str
    condition: str
    material_type: str
    dimensions_m: tuple[float, float, float]
    weight_estimate_kg: float
    has_pbr_textures: bool
    mask_id: str
    source_prompt: str
    generation_seed: int
    workflow_parameters: Mapping[str, Any] = field(default_factory=dict)
    approval_timestamp: str = ""
    working_status: str = "not-applicable"
    created_at: str = ""

    def __post_init__(self) -> None:
        required = {
            "semantic_label": self.semantic_label,
            "category": self.category,
            "era": self.era,
            "condition": self.condition,
            "material_type": self.material_type,
            "mask_id": self.mask_id,
            "source_prompt": self.source_prompt,
            "approval_timestamp": self.approval_timestamp,
        }
        empty = [name for name, value in required.items() if not str(value).strip()]
        if empty:
            raise WarehouseCatalogError(
                f"required warehouse metadata is empty: {', '.join(empty)}"
            )
        if self.category not in AssetWarehouse.CATEGORIES:
            raise WarehouseCatalogError(f"invalid warehouse category: {self.category}")
        if self.condition not in {"new", "worn", "broken"}:
            raise WarehouseCatalogError(f"invalid asset condition: {self.condition}")
        if len(self.dimensions_m) != 3 or any(value <= 0 for value in self.dimensions_m):
            raise WarehouseCatalogError("dimensions_m must contain three positive values")
        if self.weight_estimate_kg < 0:
            raise WarehouseCatalogError("weight_estimate_kg must be non-negative")
        if isinstance(self.generation_seed, bool) or not isinstance(self.generation_seed, int):
            raise WarehouseCatalogError("generation_seed must be an integer")
        object.__setattr__(
            self, "workflow_parameters", _json_copy(dict(self.workflow_parameters))
        )


@dataclass(frozen=True)
class UnifiedAssetRegistryEntry:
    """Complete unified registry sidecar accepted by the existing warehouse."""

    name: str
    object_id: str
    semantic_label: str
    category: str
    era: str
    condition: str
    working_status: str
    material_type: str
    dimensions_m: tuple[float, float, float]
    weight_estimate_kg: float
    generation_method: str
    source_photo_hash: str
    source_session_id: str
    face_count: int
    vertex_count: int
    has_pbr_textures: bool
    game_properties: Mapping[str, Any]
    real_bindings: Mapping[str, Any]
    asset_card: Mapping[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full metadata registry without shared mutable values."""
        return {
            "name": self.name,
            "object_id": self.object_id,
            "semantic_label": self.semantic_label,
            "category": self.category,
            "era": self.era,
            "condition": self.condition,
            "working_status": self.working_status,
            "material_type": self.material_type,
            "dimensions_m": list(self.dimensions_m),
            "weight_estimate_kg": self.weight_estimate_kg,
            "generation_method": self.generation_method,
            "source_photo_hash": self.source_photo_hash,
            "source_session_id": self.source_session_id,
            "face_count": self.face_count,
            "vertex_count": self.vertex_count,
            "has_pbr_textures": self.has_pbr_textures,
            "game_properties": _json_copy(dict(self.game_properties)),
            "real_bindings": _json_copy(dict(self.real_bindings)),
            "asset_card": _json_copy(dict(self.asset_card)),
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize using the same stable formatting as the reused V14 model."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)


class UnifiedAssetWarehouse(AssetWarehouse):
    """Append-only post-generation catalog for unified approved assets."""

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _resolve_collision(self, dest_path: Path) -> Path:
        """Preserve both existing GLBs and orphaned registry sidecars."""
        candidate = dest_path
        counter = 0
        while candidate.exists() or candidate.with_suffix(".json").exists():
            counter += 1
            candidate = dest_path.with_name(
                f"{dest_path.stem}_{counter}{dest_path.suffix}"
            )
        return candidate

    @staticmethod
    def _game_properties(object_id: str, overlay: Any | None) -> dict[str, Any]:
        if overlay is None:
            return {}
        bindings = getattr(overlay, "object_role_bindings", {})
        role = bindings.get(object_id)
        if role is None:
            return {}
        result = {
            "role": role,
            "rules": getattr(overlay, "rules", ""),
            "scoring": getattr(overlay, "scoring", ""),
            "win_condition": getattr(overlay, "win_condition", ""),
        }
        for optional in ("theme", "mechanics"):
            value = getattr(overlay, optional, "")
            if value:
                result[optional] = value
        return _json_copy(result)

    @staticmethod
    def _real_bindings(object_id: str, overlay: Any | None) -> dict[str, Any]:
        if overlay is None:
            return {}
        binding = getattr(overlay, "tool_bindings", {}).get(object_id)
        if binding is None:
            return {}
        if not isinstance(binding, Mapping):
            raise WarehouseCatalogError("REAL binding must be a mapping")
        result = dict(binding)
        result.setdefault("read_only", bool(getattr(overlay, "read_only", True)))
        return _json_copy(result)

    def catalog_asset(
        self,
        object_canon: ObjectCanon,
        mesh_approval: MeshApproval,
        *,
        session_id: str,
        metadata: WarehouseCatalogMetadata,
        game_overlay: Any | None = None,
        real_overlay: Any | None = None,
    ) -> Path:
        """Catalog one approved generated GLB after generation has completed."""
        if not object_canon.approved:
            raise WarehouseCatalogError("ObjectCanon must be approved before cataloging")
        if not mesh_approval.approved:
            raise WarehouseCatalogError("mesh must be approved before cataloging")
        if mesh_approval.is_placeholder or mesh_approval.generation_method == "placeholder":
            raise WarehouseCatalogError("placeholder meshes are not warehouse assets")
        if object_canon.object_id != mesh_approval.object_id:
            raise WarehouseCatalogError("ObjectCanon and mesh stable UUIDs do not match")
        if not object_canon.object_id or not object_canon.object_name:
            raise WarehouseCatalogError("ObjectCanon identity must be complete")
        if not session_id.strip():
            raise WarehouseCatalogError("source session ID must be non-empty")
        if mesh_approval.generation_method not in {"hunyuan3d_v2.1", "trellis2"}:
            raise WarehouseCatalogError("unsupported generation method for warehouse")
        if mesh_approval.face_count <= 0 or mesh_approval.vertex_count <= 0:
            raise WarehouseCatalogError("approved mesh counts must be positive")

        canon_path = Path(object_canon.image_path)
        if not canon_path.is_file():
            raise FileNotFoundError(f"ObjectCanon image not found: {canon_path}")
        mesh_path = Path(mesh_approval.mesh_path)
        if mesh_path.suffix.casefold() != ".glb":
            raise WarehouseCatalogError("approved warehouse asset must be a GLB")

        canon_hash = self._hash_file(canon_path)
        created_at = metadata.created_at or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        registry = UnifiedAssetRegistryEntry(
            name=object_canon.object_name,
            object_id=object_canon.object_id,
            semantic_label=metadata.semantic_label,
            category=metadata.category,
            era=metadata.era,
            condition=metadata.condition,
            working_status=metadata.working_status,
            material_type=metadata.material_type,
            dimensions_m=metadata.dimensions_m,
            weight_estimate_kg=metadata.weight_estimate_kg,
            generation_method=mesh_approval.generation_method,
            source_photo_hash=canon_hash,
            source_session_id=session_id,
            face_count=mesh_approval.face_count,
            vertex_count=mesh_approval.vertex_count,
            has_pbr_textures=metadata.has_pbr_textures,
            game_properties=self._game_properties(object_canon.object_id, game_overlay),
            real_bindings=self._real_bindings(object_canon.object_id, real_overlay),
            asset_card={
                "source_prompt": metadata.source_prompt,
                "object_canon_reference": {
                    "object_id": object_canon.object_id,
                    "image_path": object_canon.image_path,
                    "provenance": object_canon.provenance,
                    "sha256": canon_hash,
                },
                "generation_seed": metadata.generation_seed,
                "workflow_parameters": dict(metadata.workflow_parameters),
                "approval_timestamp": metadata.approval_timestamp,
                "tri_count": mesh_approval.face_count,
            },
            created_at=created_at,
        )
        return self.save_asset(mesh_path, registry, mask_id=metadata.mask_id)
