"""Deterministic GLB normal audit for explicit engine-neutral shading authority."""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MeshShadingAudit:
    mesh_sha256: str
    primitive_count: int
    primitives_with_normals: int
    shading_model: str
    provenance_sha256: str
    schema_version: str = "mesh-shading-audit/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mesh_sha256": self.mesh_sha256,
            "primitive_count": self.primitive_count,
            "primitives_with_normals": self.primitives_with_normals,
            "shading_model": self.shading_model,
            "provenance_sha256": self.provenance_sha256,
        }


def audit_glb_shading(path: str | Path, *, expected_sha256: str) -> MeshShadingAudit:
    """Inspect GLB JSON attributes without mutating or normalizing asset bytes.

    Meshes with a NORMAL attribute on every primitive use smooth asset normals.
    Any missing primitive normal selects derivative-based flat shading.  Mixed
    normal coverage also selects flat shading so consumers never invent normals.
    """
    source = Path(path)
    data = source.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise ValueError("mesh shading audit hash does not match approved asset")
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("mesh shading audit requires a GLB v2 asset")
    _, version, length = struct.unpack_from("<4sII", data, 0)
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if version != 2 or length != len(data) or chunk_type != 0x4E4F534A:
        raise ValueError("mesh shading audit requires valid GLB v2 JSON framing")
    payload = json.loads(data[20:20 + chunk_length].decode("utf-8").rstrip(" \t\r\n\0"))
    primitives = [
        primitive
        for mesh in payload.get("meshes", [])
        for primitive in mesh.get("primitives", [])
    ]
    if not primitives:
        raise ValueError("mesh shading audit found no GLB primitives")
    with_normals = sum("NORMAL" in item.get("attributes", {}) for item in primitives)
    model = "smooth" if with_normals == len(primitives) else "flat"
    proof = {
        "schema_version": "mesh-shading-audit/v1",
        "mesh_sha256": actual,
        "primitive_count": len(primitives),
        "primitives_with_normals": with_normals,
        "shading_model": model,
        "policy": "all-primitives-NORMAL=>smooth; otherwise derivative-flat; no byte mutation",
    }
    provenance = hashlib.sha256(
        json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return MeshShadingAudit(actual, len(primitives), with_normals, model, provenance)
