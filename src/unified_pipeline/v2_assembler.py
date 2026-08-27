"""V2.0 Assembler — Phase 5 (Assemble).

Takes the generated meshes + room shell + MetricPlan placements and
produces a scene.json manifest that the V2.0 Three.js client can load
directly to create a walkable 3D world.

This is a simplified version of the full WorldContractAssembler — it skips
the full solve chain, revision binding, and structural gates in favor of
getting a loadable scene quickly. The scene manifest provides:
- Room dimensions and camera position
- List of objects with GLB URLs, positions, rotations, and scales
- Room shell GLB URL
- Lighting configuration
- First-person navigation parameters
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.unified_pipeline.v2_mesh_builder import MeshResult

logger = logging.getLogger("live_trace")


@dataclass
class SceneManifest:
    """The assembled scene ready for Three.js loading."""

    room_dimensions: tuple[float, float, float]
    camera: dict[str, Any]
    objects: list[dict[str, Any]]
    shell_url: str
    lighting: list[dict[str, Any]]
    navigation: dict[str, Any]
    metadata: dict[str, Any]


async def assemble_world(
    brief: dict[str, Any],
    meshes: list[MeshResult],
    session_dir: Path,
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> SceneManifest:
    """Assemble the walkable world from generated meshes (Phase 5).

    Produces a scene.json manifest that the V2.0 client JS uses to load
    all GLBs into the Three.js scene at their correct positions.

    Args:
        brief: Structured Brief dict.
        meshes: List of MeshResult from Phase 4.
        session_dir: Session output directory.
        emit_fn: Optional SSE event emitter.

    Returns:
        SceneManifest with all scene data.
    """
    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    session_id = session_dir.name

    # Load room dimensions from MetricPlan
    plan_path = session_dir / "artifacts" / "metric_plan.json"
    if plan_path.is_file():
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        room_dims = tuple(plan_data.get("room_dimensions", [4.0, 4.0, 2.7]))
    else:
        room_dims = (4.0, 4.0, 2.7)

    width, depth, ceiling = room_dims

    # Camera — positioned at center of room at eye height, looking at primary wall
    eye_height = min(1.62, ceiling * 0.6)
    camera = {
        "position": {"x": 0.0, "y": eye_height, "z": 0.0},
        "target": {"x": 0.0, "y": eye_height * 0.9, "z": -depth / 2},
        "fov": 60,
        "near": 0.05,
        "far": 100.0,
    }

    # Build object list for the scene manifest
    objects = []
    for mesh in meshes:
        obj = {
            "uuid": mesh.uuid,
            "name": mesh.name,
            "glb_url": f"/api/v2/session/{session_id}/artifact/mesh_{mesh.uuid}",
            "position": {
                "x": mesh.position[0],
                "y": mesh.position[1],
                "z": mesh.position[2],
            },
            "rotation_y_deg": mesh.rotation_deg,
            "scale": {
                "x": mesh.dimensions[0],
                "y": mesh.dimensions[1],
                "z": mesh.dimensions[2],
            },
            "face_count": mesh.face_count,
            "method": mesh.generation_method,
            "is_placeholder": mesh.is_placeholder,
        }
        objects.append(obj)

    # Room shell
    shell_path = session_dir / "artifacts" / "meshes" / "room_shell.glb"
    shell_url = ""
    if shell_path.is_file():
        shell_url = f"/api/v2/session/{session_id}/artifact/mesh_room_shell"

    # Lighting — warm ambient + overhead point light
    lighting = [
        {
            "type": "ambient",
            "color": "#ffffff",
            "intensity": 0.4,
        },
        {
            "type": "point",
            "position": {"x": 0.0, "y": ceiling - 0.3, "z": 0.0},
            "color": "#fff5e6",
            "intensity": 1.0,
            "distance": max(width, depth) * 1.5,
        },
    ]

    # Add secondary lights for larger rooms
    if width > 3.5 or depth > 3.5:
        lighting.append({
            "type": "point",
            "position": {"x": width * 0.3, "y": ceiling - 0.5, "z": depth * 0.3},
            "color": "#fff8f0",
            "intensity": 0.5,
            "distance": 5.0,
        })

    # Navigation parameters for first-person controls
    navigation = {
        "spawn_position": {"x": 0.0, "y": eye_height, "z": depth * 0.3},
        "player_height": 1.75,
        "player_eye_height": eye_height,
        "player_radius": 0.25,
        "move_speed": 3.0,
        "room_bounds": {
            "min_x": -width / 2 + 0.3,
            "max_x": width / 2 - 0.3,
            "min_z": -depth / 2 + 0.3,
            "max_z": depth / 2 - 0.3,
        },
    }

    # Metadata
    metadata = {
        "interface_version": "2.0",
        "pipeline": "multi-view",
        "room_purpose": brief.get("room_purpose", "room"),
        "object_count": len(objects),
        "placeholder_count": sum(1 for o in objects if o["is_placeholder"]),
        "real_mesh_count": sum(1 for o in objects if not o["is_placeholder"]),
    }

    manifest = SceneManifest(
        room_dimensions=room_dims,
        camera=camera,
        objects=objects,
        shell_url=shell_url,
        lighting=lighting,
        navigation=navigation,
        metadata=metadata,
    )

    # Serialize to scene.json
    scene_data = {
        "schema_version": "v2.0-scene/1",
        "room_dimensions": list(room_dims),
        "camera": camera,
        "objects": objects,
        "shell_url": shell_url,
        "lighting": lighting,
        "navigation": navigation,
        "metadata": metadata,
    }

    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    scene_path = artifacts_dir / "scene.json"
    scene_path.write_text(json.dumps(scene_data, indent=2), encoding="utf-8")

    # Compute a simple scene hash for provenance
    scene_hash = hashlib.sha256(
        json.dumps(scene_data, sort_keys=True).encode()
    ).hexdigest()[:16]

    emit("world_assembled", {
        "scene_url": f"/api/v2/session/{session_id}/scene",
        "object_count": len(objects),
        "room_dimensions": list(room_dims),
        "scene_hash": scene_hash,
    })

    logger.info(
        f"  V2 assembly complete: {len(objects)} objects, "
        f"room={width:.1f}x{depth:.1f}x{ceiling:.1f}m, hash={scene_hash}"
    )

    return manifest
