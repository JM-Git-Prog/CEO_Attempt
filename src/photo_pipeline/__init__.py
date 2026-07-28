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
    RoomMeshResult,
    SceneParseResult,
    SegmentedObject,
    StageResult,
)
from src.photo_pipeline.reason_codes import ReasonCode
from src.photo_pipeline.serialization import (
    ManifestSerializationError,
    deserialize_manifest,
    serialize_manifest,
)
from src.photo_pipeline.session_integration import (
    create_photo_session,
    get_session_source_type,
    queue_for_compilation,
    store_photo_session_metadata,
)

__all__ = [
    "ManifestSerializationError",
    "ObjectManifestEntry",
    "PhotoPipelineConfig",
    "PhotoSessionMetadata",
    "PipelineManifest",
    "ReasonCode",
    "RoomMeshResult",
    "SceneParseResult",
    "SegmentedObject",
    "StageResult",
    "create_photo_session",
    "deserialize_manifest",
    "get_session_source_type",
    "queue_for_compilation",
    "serialize_manifest",
    "store_photo_session_metadata",
]
