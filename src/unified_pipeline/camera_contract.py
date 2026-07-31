"""Immutable CameraContract for the unified world pipeline.

Defines a frozen dataclass enforcing strict immutability after construction.
Right-handed coordinate system: X-right, Y-up, Z-depth perspective.
Default raster: 1024×768.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CameraContract:
    """Immutable camera projection shared by Blockout, Canon, and World.

    Coordinate system: right-handed, X-right, Y-up, Z-depth perspective.
    Once created, no field may be mutated by any downstream stage.

    Immutability is enforced by:
    1. frozen=True — raises FrozenInstanceError on attribute assignment
    2. slots=True — prevents adding new attributes via __dict__
    """

    position: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    vfov: float = 60.0
    aspect: float = 1024.0 / 768.0
    near: float = 0.05
    far: float = 100.0
    raster_width: int = 1024
    raster_height: int = 768

    def compute_hash(self) -> str:
        """Compute SHA-256 of canonical field values for binding verification.

        Uses deterministic JSON serialization of all fields in declaration
        order with sorted keys and no whitespace.
        """
        canonical = json.dumps(
            self._canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _canonical_dict(self) -> dict:
        """Internal canonical representation for hashing."""
        return {
            "position": list(self.position),
            "target": list(self.target),
            "up": list(self.up),
            "vfov": self.vfov,
            "aspect": self.aspect,
            "near": self.near,
            "far": self.far,
            "raster_width": self.raster_width,
            "raster_height": self.raster_height,
        }

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON round-trip."""
        return {
            "position": list(self.position),
            "target": list(self.target),
            "up": list(self.up),
            "vfov": self.vfov,
            "aspect": self.aspect,
            "near": self.near,
            "far": self.far,
            "raster_width": self.raster_width,
            "raster_height": self.raster_height,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CameraContract:
        """Deserialize from a plain dict (JSON round-trip counterpart)."""
        return cls(
            position=tuple(data["position"]),
            target=tuple(data["target"]),
            up=tuple(data.get("up", [0.0, 1.0, 0.0])),
            vfov=float(data.get("vfov", 60.0)),
            aspect=float(data.get("aspect", 1024.0 / 768.0)),
            near=float(data.get("near", 0.05)),
            far=float(data.get("far", 100.0)),
            raster_width=int(data.get("raster_width", 1024)),
            raster_height=int(data.get("raster_height", 768)),
        )

    def __repr__(self) -> str:
        return (
            f"CameraContract(position={self.position}, target={self.target}, "
            f"up={self.up}, vfov={self.vfov}, aspect={self.aspect:.6f}, "
            f"near={self.near}, far={self.far}, "
            f"raster={self.raster_width}\u00d7{self.raster_height}, "
            f"hash={self.compute_hash()[:12]}\u2026)"
        )
