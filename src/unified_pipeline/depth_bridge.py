"""V16 adapter exposing DA3 output only as optional, non-authoritative evidence.

The adapter delegates estimation to the V14 ``DepthAnything3Estimator`` but
owns the V16 authority boundary and acquires DA3 through the unified resource
arbiter. Requirements: 14.1, 14.2, 14.3, 14.4, 14.5.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.models import DepthResult, PhotoPipelineConfig
from src.photo_pipeline.stages.depth_anything3 import DepthAnything3Estimator
from src.unified_pipeline.resource_arbiter import (
    ResourceArbiterError,
    ResourceKind,
    ResourceRequest,
    UnifiedResourceArbiter,
)

FORBIDDEN_DEPTH_AUTHORITIES = (
    "room_dimensions",
    "openings",
    "architectural_geometry",
    "collision_geometry",
    "navigation_geometry",
    "object_transforms",
    "camera",
)


class DepthAuthorityError(ValueError):
    """Raised when a caller attempts to promote depth to spatial authority."""


class DepthAlignmentError(ValueError):
    """Raised when evidence alignment is not one uniform camera transform."""


class DepthEvidenceValidationError(RuntimeError):
    """Raised when the reused estimator emits an invalid evidence artifact."""

@dataclass(frozen=True)
class CameraAnchoredSimilarity:
    """The only transform permitted for aligning depth appearance evidence."""

    camera_hash: str
    uniform_scale: float
    translation_to_fit_m: tuple[float, float, float]
    transform_kind: str = "camera_anchored_uniform_similarity"
    normalization: str = "none"
    per_axis_scale: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.transform_kind != "camera_anchored_uniform_similarity":
            raise DepthAlignmentError("only one camera-anchored uniform similarity is allowed")
        if self.normalization != "none":
            raise DepthAlignmentError("per-axis/min-max normalization is forbidden")
        if self.per_axis_scale is not None:
            raise DepthAlignmentError("per-axis scale is forbidden")
        if not self.camera_hash.strip():
            raise DepthAlignmentError("camera_hash is required to anchor evidence alignment")
        if isinstance(self.uniform_scale, bool) or not isinstance(self.uniform_scale, (int, float)):
            raise DepthAlignmentError("uniform_scale must be one scalar")
        if not math.isfinite(float(self.uniform_scale)) or self.uniform_scale <= 0:
            raise DepthAlignmentError("uniform_scale must be finite and positive")
        if len(self.translation_to_fit_m) != 3 or not all(
            math.isfinite(float(value)) for value in self.translation_to_fit_m
        ):
            raise DepthAlignmentError("translation_to_fit_m must contain three finite values")


@dataclass(frozen=True)
class DepthEvidenceProvenance:
    session_id: str
    source_image_path: str
    source_image_sha256: str
    source_resolution: tuple[int, int]
    depth_artifact_sha256: str
    producer: str = "src.photo_pipeline.stages.depth_anything3.DepthAnything3Estimator"
    estimator_chain: str = "depth_anything_3>moge2>flat_floor"

    def __post_init__(self) -> None:
        values = (
            self.session_id,
            self.source_image_path,
            self.source_image_sha256,
            self.depth_artifact_sha256,
            self.producer,
            self.estimator_chain,
        )
        if any(not value.strip() for value in values):
            raise DepthEvidenceValidationError("depth evidence provenance must be non-empty")
        hashes = (self.source_image_sha256, self.depth_artifact_sha256)
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in hashes
        ):
            raise DepthEvidenceValidationError("provenance hashes must be lowercase SHA-256")
        if len(self.source_resolution) != 2 or any(
            value <= 0 for value in self.source_resolution
        ):
            raise DepthEvidenceValidationError("source_resolution must be positive")


@dataclass(frozen=True)
class DepthEvidence:
    """Optional evidence/reference record that cannot carry spatial authority."""

    depth_map_path: str
    normal_map_path: str
    valid_pixel_ratio: float
    depth_range_m: tuple[float, float]
    provenance: DepthEvidenceProvenance
    alignment: CameraAnchoredSimilarity | None = None
    evidence_kind: str = "depth_evidence"
    optional: bool = True
    collision_enabled: bool = False
    spatial_authority: bool = False
    authority_claims: tuple[str, ...] = ()
    forbidden_authorities: tuple[str, ...] = FORBIDDEN_DEPTH_AUTHORITIES

    def __post_init__(self) -> None:
        if not self.optional or self.collision_enabled or self.spatial_authority:
            raise DepthAuthorityError("depth must remain optional, non-colliding evidence")
        if self.authority_claims:
            raise DepthAuthorityError("depth evidence cannot carry any authority claim")
        expected_kind = "aligned_appearance_reference" if self.alignment else "depth_evidence"
        if self.evidence_kind != expected_kind:
            raise DepthAuthorityError(f"evidence_kind must be {expected_kind!r}")
        if tuple(self.forbidden_authorities) != FORBIDDEN_DEPTH_AUTHORITIES:
            raise DepthAuthorityError("the depth authority deny-list is immutable")
        if not self.depth_map_path or not self.normal_map_path:
            raise DepthEvidenceValidationError("depth and normal evidence paths are required")
        if not 0.50 <= self.valid_pixel_ratio <= 1.0:
            raise DepthEvidenceValidationError("valid_pixel_ratio must be within [0.50, 1.0]")
        if len(self.depth_range_m) != 2 or not (
            0 < self.depth_range_m[0] <= self.depth_range_m[1] < 20.0
        ):
            raise DepthEvidenceValidationError("depth_range_m must be positive indoor meters")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DepthBridgeResult = DepthEvidence

class UnifiedDepthEstimator:
    """Run the reused estimator under the sole GPU owner and map its output."""

    def __init__(
        self,
        client: ComfyUIClient,
        output_dir: Path | str,
        *,
        arbiter: UnifiedResourceArbiter,
        comfyui_instance: str = "default",
        estimator: DepthAnything3Estimator | None = None,
    ) -> None:
        if arbiter is None:
            raise ValueError("the unified resource arbiter is required for DA3")
        self._arbiter = arbiter
        self._comfyui_instance = comfyui_instance
        self._estimator = estimator or DepthAnything3Estimator(client, Path(output_dir))

    async def estimate(
        self,
        source_image: Path | str,
        config: PhotoPipelineConfig,
        *,
        session_id: str,
        alignment: CameraAnchoredSimilarity | None = None,
        authority_claims: Iterable[str] = (),
    ) -> DepthEvidence:
        """Produce validated optional evidence; reject authority before GPU work."""
        claims = tuple(str(claim).strip() for claim in authority_claims if str(claim).strip())
        if claims:
            raise DepthAuthorityError(
                "depth cannot authorize any spatial concern: " + ", ".join(claims)
            )
        if alignment is not None and not isinstance(alignment, CameraAnchoredSimilarity):
            raise DepthAlignmentError("alignment must be one CameraAnchoredSimilarity")
        if not session_id.strip():
            raise DepthEvidenceValidationError("session_id is required for provenance")

        source_path = Path(source_image)
        if not source_path.is_file():
            raise DepthEvidenceValidationError(f"source image does not exist: {source_path}")
        source_hash = self._sha256(source_path)
        with Image.open(source_path) as image:
            source_resolution = image.size

        request = ResourceRequest(
            ResourceKind.DA3,
            owner_id=f"depth:{session_id}",
            model_name="depth_anything_3",
            comfyui_instance=self._comfyui_instance,
        )
        async with self._arbiter.claim(request):
            result = await self._estimator.estimate(source_path, config)

        return self._map_result(
            result,
            session_id=session_id,
            source_path=source_path,
            source_hash=source_hash,
            source_resolution=source_resolution,
            alignment=alignment,
        )

    async def estimate_optional(self, *args: Any, **kwargs: Any) -> DepthEvidence | None:
        """Skip unavailable optional evidence, but never suppress policy violations."""
        try:
            return await self.estimate(*args, **kwargs)
        except (DepthAuthorityError, DepthAlignmentError, ResourceArbiterError):
            raise
        except (OSError, DepthEvidenceValidationError):
            return None

    def _map_result(
        self,
        result: DepthResult,
        *,
        session_id: str,
        source_path: Path,
        source_hash: str,
        source_resolution: tuple[int, int],
        alignment: CameraAnchoredSimilarity | None,
    ) -> DepthEvidence:
        depth_path = Path(result.depth_map_path)
        normal_path = Path(result.normal_map_path)
        if depth_path.suffix.lower() != ".npy" or not depth_path.is_file():
            raise DepthEvidenceValidationError("depth output must be an existing .npy artifact")
        if normal_path.suffix.lower() != ".npy" or not normal_path.is_file():
            raise DepthEvidenceValidationError("normal evidence must be an existing .npy artifact")

        depth = np.load(depth_path, allow_pickle=False)
        expected_shape = (source_resolution[1], source_resolution[0])
        if depth.dtype != np.float32 or depth.ndim != 2 or depth.shape != expected_shape:
            raise DepthEvidenceValidationError(
                f"depth must be float32 at source resolution {expected_shape}; "
                f"got dtype={depth.dtype}, shape={depth.shape}"
            )
        normals = np.load(normal_path, allow_pickle=False)
        if normals.dtype != np.float32 or normals.shape != (*expected_shape, 3):
            raise DepthEvidenceValidationError(
                f"normals must be float32 at source resolution {(*expected_shape, 3)}"
            )
        valid = (depth > 0) & np.isfinite(depth) & (depth < 20.0)
        valid_ratio = float(np.count_nonzero(valid)) / depth.size if depth.size else 0.0
        if valid_ratio < 0.50:
            raise DepthEvidenceValidationError("depth evidence has fewer than 50% valid pixels")
        values = depth[valid]
        depth_range = (float(values.min()), float(values.max()))
        provenance = DepthEvidenceProvenance(
            session_id=session_id,
            source_image_path=str(source_path),
            source_image_sha256=source_hash,
            source_resolution=source_resolution,
            depth_artifact_sha256=self._sha256(depth_path),
        )
        return DepthEvidence(
            depth_map_path=str(depth_path),
            normal_map_path=str(normal_path),
            valid_pixel_ratio=valid_ratio,
            depth_range_m=depth_range,
            provenance=provenance,
            alignment=alignment,
            evidence_kind=("aligned_appearance_reference" if alignment else "depth_evidence"),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
