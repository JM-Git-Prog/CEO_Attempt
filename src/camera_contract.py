"""Authoritative V9 camera and image-frame contract."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


class CameraVector(BaseModel):
    x: float
    y: float
    z: float


class CameraContract(BaseModel):
    schema_version: Literal["camera-lock/v1"] = "camera-lock/v1"
    contract_id: str
    coordinate_system: Literal["right-handed-x-right-y-up-z-depth"] = "right-handed-x-right-y-up-z-depth"
    projection: Literal["perspective"] = "perspective"
    position: CameraVector
    target: CameraVector
    up: CameraVector = Field(default_factory=lambda: CameraVector(x=0.0, y=1.0, z=0.0))
    vertical_fov_deg: float = Field(ge=1.0, lt=180.0)
    aspect_ratio: float = Field(gt=0.0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    near_plane: float = Field(default=0.05, gt=0.0)
    far_plane: float = Field(default=100.0, gt=0.0)
    reference_landmarks: list[dict] = Field(default_factory=list)

    @property
    def near(self) -> float:
        return self.near_plane

    @property
    def far(self) -> float:
        return self.far_plane


def horizontal_fov_deg(vertical_fov_deg: float, aspect_ratio: float) -> float:
    vertical = math.radians(vertical_fov_deg)
    return math.degrees(2.0 * math.atan(math.tan(vertical / 2.0) * aspect_ratio))


def camera_contract_for_plan(plan, *, width: int = 1024, height: int = 768) -> CameraContract:
    payload = {
        "position": {"x": plan.camera.x, "y": plan.camera.y, "z": plan.camera.z},
        "target": {"x": plan.camera.target_x, "y": plan.camera.target_y, "z": plan.camera.target_z},
        "vertical_fov_deg": plan.camera.fov_deg,
        "aspect_ratio": width / height,
        "image_width": width,
        "image_height": height,
        "near_plane": 0.05,
        "far_plane": 100.0,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["contract_id"] = f"camera-{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"
    contract = CameraContract.model_validate(payload)
    half_width, half_depth = plan.room.width / 2, plan.room.depth / 2
    world_points = [
        (f"room_floor_{index}", point)
        for index, point in enumerate((
            (-half_width, 0.0, -half_depth),
            (half_width, 0.0, -half_depth),
            (half_width, 0.0, half_depth),
            (-half_width, 0.0, half_depth),
        ), 1)
    ]
    world_points.extend(
        (item.id, (item.x, item.elevation + item.height / 2, item.z))
        for item in plan.items
    )
    landmarks = []
    for landmark_id, point in world_points:
        projected = project_point(contract, point)
        if projected:
            x, y, depth = projected
            landmarks.append({
                "id": landmark_id,
                "world": {"x": point[0], "y": point[1], "z": point[2]},
                "screen_px": {"x": round(x, 3), "y": round(y, 3)},
                "depth": round(depth, 6),
            })
    return contract.model_copy(update={"reference_landmarks": landmarks})


def project_point(contract: CameraContract, point: tuple[float, float, float]) -> tuple[float, float, float] | None:
    camera = np.array([contract.position.x, contract.position.y, contract.position.z], dtype=float)
    target = np.array([contract.target.x, contract.target.y, contract.target.z], dtype=float)
    world_up = np.array([contract.up.x, contract.up.y, contract.up.z], dtype=float)
    forward = target - camera
    forward /= max(float(np.linalg.norm(forward)), 1e-9)
    right = np.cross(forward, world_up)
    right /= max(float(np.linalg.norm(right)), 1e-9)
    up = np.cross(right, forward)
    relative = np.array(point, dtype=float) - camera
    depth = float(np.dot(relative, forward))
    if depth <= contract.near_plane or depth >= contract.far_plane:
        return None
    focal = (contract.image_height / 2) / math.tan(math.radians(contract.vertical_fov_deg) / 2)
    return (
        contract.image_width / 2 + float(np.dot(relative, right)) * focal / depth,
        contract.image_height / 2 - float(np.dot(relative, up)) * focal / depth,
        depth,
    )


def project_world_point(
    contract: CameraContract, point: tuple[float, float, float]
) -> tuple[float, float, float, tuple[float, float]]:
    projected = project_point(contract, point)
    if projected is None:
        return float("nan"), float("nan"), -1.0, (float("nan"), float("nan"))
    x, y, depth = projected
    ndc = (
        (x / contract.image_width) * 2.0 - 1.0,
        1.0 - (y / contract.image_height) * 2.0,
    )
    return x, y, depth, ndc


def build_camera_contract(plan, *, width: int = 1024, height: int = 768) -> CameraContract:
    return camera_contract_for_plan(plan, width=width, height=height)


def normalize_image_frame(path: Path, contract: CameraContract) -> dict:
    with Image.open(path) as source:
        before = source.size
        normalized = ImageOps.fit(
            source.convert("RGB"),
            (contract.image_width, contract.image_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        normalized.save(path, "PNG")
    return {"before": list(before), "after": [contract.image_width, contract.image_height], "changed": before != normalized.size}


def measure_edge_alignment(reference_path: Path, candidate_path: Path, contract: CameraContract) -> dict:
    def edges(path: Path) -> np.ndarray:
        with Image.open(path) as image:
            data = np.asarray(ImageOps.fit(image.convert("L"), (contract.image_width, contract.image_height)), dtype=np.float32)
        gradient = np.abs(np.diff(data, axis=1, prepend=data[:, :1])) + np.abs(np.diff(data, axis=0, prepend=data[:1, :]))
        threshold = max(8.0, float(np.percentile(gradient, 85)))
        return (gradient >= threshold)[::4, ::4]

    reference, candidate = edges(reference_path), edges(candidate_path)
    best = (0.0, 0, 0)
    for dy in range(-6, 7):
        for dx in range(-6, 7):
            shifted = np.roll(candidate, (dy, dx), axis=(0, 1))
            if dy > 0: shifted[:dy, :] = False
            elif dy < 0: shifted[dy:, :] = False
            if dx > 0: shifted[:, :dx] = False
            elif dx < 0: shifted[:, dx:] = False
            union = int(np.count_nonzero(reference | shifted))
            score = int(np.count_nonzero(reference & shifted)) / max(union, 1)
            if score > best[0]: best = (score, dx, dy)
    score, dx, dy = best
    shift_x, shift_y = dx * 4, dy * 4
    drift = math.hypot(shift_x, shift_y)
    return {
        "contract_id": contract.contract_id,
        "method": "edge-registration-v1",
        "edge_iou": round(score, 4),
        "best_translation_px": {"x": shift_x, "y": shift_y},
        "drift_px": round(drift, 2),
        "status": "aligned" if drift <= 8 and score >= 0.08 else "review_required",
        "suggested_correction": {"translate_x_px": shift_x, "translate_y_px": shift_y},
    }
