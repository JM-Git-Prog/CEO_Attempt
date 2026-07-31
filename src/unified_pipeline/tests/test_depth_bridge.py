"""Focused Task 4.8 tests for optional, non-authoritative depth evidence."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from src.photo_pipeline.models import DepthResult, PhotoPipelineConfig
from src.photo_pipeline.stages.depth_anything3 import DepthAnything3Estimator
from src.unified_pipeline.depth_bridge import (
    FORBIDDEN_DEPTH_AUTHORITIES,
    CameraAnchoredSimilarity,
    DepthAlignmentError,
    DepthAuthorityError,
    DepthEvidence,
    DepthEvidenceProvenance,
    DepthEvidenceValidationError,
    UnifiedDepthEstimator,
)
from src.unified_pipeline.resource_arbiter import ResourceKind, ResourceReleaseError


class FakeArbiter:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.active = 0
        self.maximum_active = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def claim(self, request: Any):
        async with self._lock:
            self.requests.append(request)
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            try:
                yield object()
            finally:
                self.active -= 1


class FakeEstimator:
    def __init__(self, result: DepthResult, arbiter: FakeArbiter) -> None:
        self.result = result
        self.arbiter = arbiter
        self.calls = 0

    async def estimate(self, source_image: Path, config: PhotoPipelineConfig) -> DepthResult:
        assert self.arbiter.active == 1
        self.calls += 1
        await asyncio.sleep(0)
        return self.result

@pytest.fixture
def artifacts(tmp_path: Path) -> tuple[Path, DepthResult]:
    source = tmp_path / "canon.png"
    Image.new("RGB", (8, 6), (30, 40, 50)).save(source)
    depth = np.linspace(1.0, 4.0, 48, dtype=np.float32).reshape(6, 8)
    normals = np.zeros((6, 8, 3), dtype=np.float32)
    normals[:, :, 2] = 1.0
    depth_path = tmp_path / "depth.npy"
    normal_path = tmp_path / "normal.npy"
    np.save(depth_path, depth)
    np.save(normal_path, normals)
    return source, DepthResult(depth_path, normal_path, 1.0, (1.0, 4.0))


def make_adapter(artifacts: tuple[Path, DepthResult]):
    _, result = artifacts
    arbiter = FakeArbiter()
    estimator = FakeEstimator(result, arbiter)
    adapter = UnifiedDepthEstimator(
        client=object(),
        output_dir=result.depth_map_path.parent,
        arbiter=arbiter,
        estimator=estimator,
    )
    return adapter, arbiter, estimator


@pytest.mark.asyncio
async def test_emits_provenance_bearing_optional_depth_evidence(artifacts) -> None:
    source, _ = artifacts
    adapter, arbiter, estimator = make_adapter(artifacts)

    evidence = await adapter.estimate(
        source, PhotoPipelineConfig(), session_id="session-48"
    )

    assert evidence.evidence_kind == "depth_evidence"
    assert evidence.optional is True
    assert evidence.spatial_authority is False
    assert evidence.collision_enabled is False
    assert evidence.authority_claims == ()
    assert evidence.forbidden_authorities == FORBIDDEN_DEPTH_AUTHORITIES
    assert evidence.provenance.session_id == "session-48"
    assert len(evidence.provenance.source_image_sha256) == 64
    assert len(evidence.provenance.depth_artifact_sha256) == 64
    assert evidence.provenance.source_resolution == (8, 6)
    assert estimator.calls == 1
    assert arbiter.requests[0].kind is ResourceKind.DA3
    assert arbiter.requests[0].owner_id == "depth:session-48"


@pytest.mark.asyncio
async def test_aligned_reference_allows_only_camera_uniform_similarity(artifacts) -> None:
    source, _ = artifacts
    adapter, _, _ = make_adapter(artifacts)
    alignment = CameraAnchoredSimilarity(
        camera_hash="camera-sha256",
        uniform_scale=1.25,
        translation_to_fit_m=(0.5, -0.1, 2.0),
    )

    evidence = await adapter.estimate(
        source,
        PhotoPipelineConfig(),
        session_id="aligned",
        alignment=alignment,
    )

    assert evidence.evidence_kind == "aligned_appearance_reference"
    assert evidence.alignment is alignment
    assert evidence.alignment.transform_kind == "camera_anchored_uniform_similarity"
    assert evidence.alignment.normalization == "none"


@pytest.mark.parametrize("claim", FORBIDDEN_DEPTH_AUTHORITIES)
@pytest.mark.asyncio
async def test_every_spatial_authority_claim_fails_before_gpu(artifacts, claim) -> None:
    source, _ = artifacts
    adapter, arbiter, estimator = make_adapter(artifacts)

    with pytest.raises(DepthAuthorityError, match="cannot authorize"):
        await adapter.estimate(
            source,
            PhotoPipelineConfig(),
            session_id="reject-authority",
            authority_claims=(claim,),
        )

    assert arbiter.requests == []
    assert estimator.calls == 0

def test_alignment_rejects_per_axis_and_min_max_normalization() -> None:
    with pytest.raises(DepthAlignmentError, match="per-axis scale"):
        CameraAnchoredSimilarity(
            camera_hash="camera",
            uniform_scale=1.0,
            translation_to_fit_m=(0.0, 0.0, 0.0),
            per_axis_scale=(1.0, 2.0, 3.0),
        )
    with pytest.raises(DepthAlignmentError, match="min-max"):
        CameraAnchoredSimilarity(
            camera_hash="camera",
            uniform_scale=1.0,
            translation_to_fit_m=(0.0, 0.0, 0.0),
            normalization="min_max",
        )
    with pytest.raises(DepthAlignmentError, match="one scalar"):
        CameraAnchoredSimilarity(
            camera_hash="camera",
            uniform_scale=(1.0, 2.0, 3.0),  # type: ignore[arg-type]
            translation_to_fit_m=(0.0, 0.0, 0.0),
        )


def test_evidence_model_itself_rejects_authority_escalation(tmp_path: Path) -> None:
    provenance = DepthEvidenceProvenance(
        session_id="session",
        source_image_path=str(tmp_path / "source.png"),
        source_image_sha256="a" * 64,
        source_resolution=(8, 6),
        depth_artifact_sha256="b" * 64,
    )
    base = dict(
        depth_map_path=str(tmp_path / "depth.npy"),
        normal_map_path=str(tmp_path / "normal.npy"),
        valid_pixel_ratio=1.0,
        depth_range_m=(1.0, 4.0),
        provenance=provenance,
    )
    with pytest.raises(DepthAuthorityError):
        DepthEvidence(**base, spatial_authority=True)
    with pytest.raises(DepthAuthorityError):
        DepthEvidence(**base, collision_enabled=True)
    with pytest.raises(DepthAuthorityError):
        DepthEvidence(**base, authority_claims=("camera",))


@pytest.mark.asyncio
async def test_invalid_dtype_fails_closed(artifacts) -> None:
    source, result = artifacts
    np.save(result.depth_map_path, np.ones((6, 8), dtype=np.float64))
    adapter, _, _ = make_adapter(artifacts)

    with pytest.raises(DepthEvidenceValidationError, match="float32"):
        await adapter.estimate(source, PhotoPipelineConfig(), session_id="bad-dtype")


@pytest.mark.asyncio
async def test_optional_path_skips_invalid_artifact_but_not_policy_errors(artifacts) -> None:
    source, result = artifacts
    np.save(result.depth_map_path, np.zeros((6, 8), dtype=np.float32))
    adapter, arbiter, _ = make_adapter(artifacts)

    assert await adapter.estimate_optional(
        source, PhotoPipelineConfig(), session_id="optional"
    ) is None
    with pytest.raises(DepthAuthorityError):
        await adapter.estimate_optional(
            source,
            PhotoPipelineConfig(),
            session_id="optional-policy",
            authority_claims=("camera",),
        )
    assert len(arbiter.requests) == 1


@pytest.mark.asyncio
async def test_concurrent_depth_calls_remain_single_owner(artifacts) -> None:
    source, _ = artifacts
    adapter, arbiter, estimator = make_adapter(artifacts)

    await asyncio.gather(
        adapter.estimate(source, PhotoPipelineConfig(), session_id="one"),
        adapter.estimate(source, PhotoPipelineConfig(), session_id="two"),
    )

    assert estimator.calls == 2
    assert arbiter.maximum_active == 1


def test_default_adapter_reuses_v14_estimator(artifacts) -> None:
    _, result = artifacts
    adapter = UnifiedDepthEstimator(
        client=object(),
        output_dir=result.depth_map_path.parent,
        arbiter=FakeArbiter(),
    )
    assert isinstance(adapter._estimator, DepthAnything3Estimator)


def test_adapter_cannot_be_constructed_without_arbiter(artifacts) -> None:
    _, result = artifacts
    with pytest.raises(ValueError, match="arbiter is required"):
        UnifiedDepthEstimator(
            client=object(),
            output_dir=result.depth_map_path.parent,
            arbiter=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_optional_path_never_swallows_unsafe_resource_release(artifacts) -> None:
    source, result = artifacts

    class UnsafeReleaseArbiter(FakeArbiter):
        @asynccontextmanager
        async def claim(self, request: Any):
            async with super().claim(request):
                yield object()
            raise ResourceReleaseError("VRAM remains above safe threshold")

    arbiter = UnsafeReleaseArbiter()
    estimator = FakeEstimator(result, arbiter)
    adapter = UnifiedDepthEstimator(
        client=object(),
        output_dir=result.depth_map_path.parent,
        arbiter=arbiter,
        estimator=estimator,
    )

    with pytest.raises(ResourceReleaseError, match="above safe threshold"):
        await adapter.estimate_optional(
            source, PhotoPipelineConfig(), session_id="unsafe-release"
        )
