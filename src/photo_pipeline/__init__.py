"""Photo-to-Playable-World pipeline.

Transforms a single RGB photograph of an indoor scene into a running 3D game
via UPBGE 0.50 by performing segmentation, depth estimation, 3D mesh generation,
audio synthesis, light estimation, scale calibration, layout estimation, and
WorldContract assembly.
"""

from src.photo_pipeline.models import (
    ObjectManifestEntry,
    PhotoPipelineConfig,
    PhotoSessionMetadata,
    PipelineManifest,
    SceneParseResult,
    SegmentedObject,
    StageResult,
)
from src.photo_pipeline.reason_codes import ReasonCode

__all__ = [
    "ObjectManifestEntry",
    "PhotoPipelineConfig",
    "PhotoSessionMetadata",
    "PipelineManifest",
    "ReasonCode",
    "SceneParseResult",
    "SegmentedObject",
    "StageResult",
]
