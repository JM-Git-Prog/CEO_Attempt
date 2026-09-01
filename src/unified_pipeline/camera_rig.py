"""The nine-camera rig — every room gets nine cameras, by construction.

Standing rule (John, 2026-08-31): every room we build carries nine cameras.

The reason is measured, not stylistic. Getting nine consistent views of one room
out of an image generator failed twice in a row: asked for a 3x3 grid, got 12
panels all from the same angle; rewrote the prompt naming the count three times,
got 6 panels and lost room consistency in the trade. Anchoring a video model to
a reference frame did hold identity (MAE 9.6) but cost ~19 minutes for five
frames and cannot reach a true overhead shot at all.

A room we built ourselves has no such problem. The geometry IS the consistency -
nine cameras looking at the same meshes cannot disagree about the room - and the
count is exactly nine because a list has a length. What took an hour and failed
becomes a render.

Poses are parametric on the room's own dimensions, so a broom cupboard and a
ballroom both get a sensible rig without hand-tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

# Standing eye height, and the height of a typical work surface. The rig aims
# at what a person would look at, not at the geometric centre of the volume.
EYE_HEIGHT = 1.6
SURFACE_HEIGHT = 0.75


@dataclass(frozen=True)
class Camera:
    """One camera in the rig. Position and target are in room-centred metres."""

    name: str
    purpose: str
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    fov: float

    def to_dict(self) -> dict:
        return asdict(self)


def rig_for_room(
    width: float,
    depth: float,
    height: float,
    focus: Sequence[float] | None = None,
) -> list[Camera]:
    """Build the nine cameras for a room of these dimensions.

    Room space is centred on the origin: x spans -width/2..width/2, z spans
    -depth/2..depth/2, y runs 0 (floor) to height (ceiling) - the same
    convention plan_preview uses to place its boxes.

    `focus` is what the detail shots aim at, defaulting to the middle of the
    room at table height (usually the centrepiece object).
    """
    hw, hd = width / 2.0, depth / 2.0
    aim = tuple(focus) if focus else (0.0, SURFACE_HEIGHT, 0.0)

    # Keep cameras just inside the walls so they never sit in the geometry.
    inset = min(0.35, hw * 0.25, hd * 0.25)
    # How far the detail shot pulls back from the centrepiece. Clamped to the
    # room: a fixed pullback puts the camera through the wall of a small room
    # (a 2m room has only 1m of half-depth to work with).
    detail_pullback = min(1.05, hd - inset)

    return [
        Camera(
            "bird_eye", "plan view - reads the whole layout at once",
            (0.0, height - 0.15, 0.0), (0.0, SURFACE_HEIGHT, 0.001), 55.0,
        ),
        Camera(
            "doorway", "establishing shot from the entrance",
            (0.0, EYE_HEIGHT, hd - inset), (0.0, EYE_HEIGHT * 0.7, -hd), 60.0,
        ),
        Camera(
            "floor_up", "low angle - exaggerates height and ceiling light",
            (0.0, 0.25, hd * 0.55), (0.0, height, -hd * 0.25), 70.0,
        ),
        Camera(
            "high_corner", "three-quarter overview from the far corner",
            (hw - inset, height - 0.4, hd - inset), (0.0, SURFACE_HEIGHT, 0.0), 55.0,
        ),
        Camera(
            "side_left", "side profile across the left wall",
            (-hw + inset, EYE_HEIGHT * 0.9, 0.0), (hw, EYE_HEIGHT * 0.7, 0.0), 60.0,
        ),
        Camera(
            "side_right", "side profile across the right wall",
            (hw - inset, EYE_HEIGHT * 0.9, 0.0), (-hw, EYE_HEIGHT * 0.7, 0.0), 60.0,
        ),
        Camera(
            "centre_detail", "close on the centrepiece",
            (0.0, SURFACE_HEIGHT + 0.55, detail_pullback), aim, 40.0,
        ),
        Camera(
            "over_shoulder", "seated point of view across the table",
            (0.0, EYE_HEIGHT * 0.75, hd * 0.45), (0.0, SURFACE_HEIGHT, -hd * 0.35), 50.0,
        ),
        Camera(
            "back_corner_low", "opposite low corner - catches floor and shadow",
            (-hw + inset, 0.65, -hd + inset), (hw * 0.5, EYE_HEIGHT * 0.8, hd * 0.5), 65.0,
        ),
    ]


def rig_payload(width: float, depth: float, height: float, focus=None) -> dict:
    """Serialisable rig for the world contract / preview API."""
    cameras = rig_for_room(width, depth, height, focus)
    return {
        "count": len(cameras),
        "room": {"width": width, "depth": depth, "height": height},
        "convention": "room-centred metres, y up, target is a look-at point",
        "cameras": [camera.to_dict() for camera in cameras],
    }
