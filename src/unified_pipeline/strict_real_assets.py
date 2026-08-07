"""Strict-real mesh normalization and fail-closed Bullet settling helpers."""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.unified_pipeline.object_manifest import file_sha256


def _scene_bounds(path: Path) -> tuple[Any, Any, int, int]:
    import numpy as np
    import trimesh

    loaded = trimesh.load(path, force="scene", process=False)
    scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
    vertices = []
    face_count = 0
    vertex_count = 0
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.vertices) or not len(mesh.faces):
            continue
        if not np.isfinite(mesh.vertices).all():
            raise RuntimeError(f"mesh contains non-finite vertices: {path}")
        vertices.append(mesh.vertices)
        face_count += int(len(mesh.faces))
        vertex_count += int(len(mesh.vertices))
    if not vertices:
        raise RuntimeError(f"GLB contains no nonempty triangle geometry: {path}")
    combined = np.concatenate(vertices, axis=0)
    return combined.min(axis=0), combined.max(axis=0), face_count, vertex_count


def normalize_generated_glb(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Create one centered-XZ, floor-origin, unit-bounds GLB with hash provenance."""
    import numpy as np
    import trimesh

    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    minimum, maximum, source_faces, source_vertices = _scene_bounds(source_path)
    extents = maximum - minimum
    if not np.isfinite(extents).all() or float(extents.min()) <= 1e-6:
        raise RuntimeError("generated mesh has invalid source extents")
    center = (minimum + maximum) / 2.0
    anchor = np.array([center[0], minimum[1], center[2]], dtype=float)
    transform = np.eye(4, dtype=float)
    transform[0, 0], transform[1, 1], transform[2, 2] = 1.0 / extents
    transform[:3, 3] = -anchor / extents
    loaded = trimesh.load(source_path, force="scene", process=False)
    scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
    scene.apply_transform(transform)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_suffix(".tmp.glb")
    scene.export(temporary, file_type="glb")
    temporary.replace(destination_path)

    normalized_min, normalized_max, face_count, vertex_count = _scene_bounds(destination_path)
    expected_min = np.array([-0.5, 0.0, -0.5])
    expected_max = np.array([0.5, 1.0, 0.5])
    if not (
        np.allclose(normalized_min, expected_min, atol=1e-5)
        and np.allclose(normalized_max, expected_max, atol=1e-5)
        and face_count == source_faces
        and vertex_count == source_vertices
    ):
        destination_path.unlink(missing_ok=True)
        raise RuntimeError("strict mesh normalization failed unit-bounds verification")
    return {
        "source_path": str(source_path),
        "source_sha256": file_sha256(source_path),
        "source_extents_m": [float(value) for value in extents],
        "source_bounds_min": [float(value) for value in minimum],
        "source_bounds_max": [float(value) for value in maximum],
        "normalized_path": str(destination_path),
        "normalized_sha256": file_sha256(destination_path),
        "normalized_bounds_min": [float(value) for value in normalized_min],
        "normalized_bounds_max": [float(value) for value in normalized_max],
        "normalization_scale": [float(1.0 / value) for value in extents],
        "origin_policy": "local-bounds-bottom-center",
        "normalization_count": 1,
        "face_count": face_count,
        "vertex_count": vertex_count,
        "fallback_used": False,
    }


def classify_selected_body(
    *, plan_revision: int, object_id: str, category: str,
    dimensions: Sequence[float], material: str,
) -> dict[str, Any]:
    """Reuse V14's density classifier behind the Plan-authority adapter."""
    from src.unified_pipeline.physics_bridge import PlanPhysicsInput, UnifiedPhysicsClassifier

    canonical_material = str(material).casefold()
    material_aliases = (
        (("steel", "metal", "iron", "chrome", "aluminum", "aluminium"), "metal"),
        (("wood", "oak", "walnut", "timber"), "wood"),
        (("glass",), "glass"),
        (("fabric", "cloth", "linen", "leather"), "fabric"),
        (("ceramic", "porcelain", "tile", "stone", "marble"), "ceramic"),
        (("plastic", "rubber"), "plastic"),
    )
    for aliases, candidate in material_aliases:
        if any(alias in canonical_material for alias in aliases):
            canonical_material = candidate
            break
    result = UnifiedPhysicsClassifier().classify(
        PlanPhysicsInput(
            plan_revision=plan_revision,
            object_id=object_id,
            category=category,
            dimensions_m=tuple(float(value) for value in dimensions),
        ),
        {"material": canonical_material},
    )
    return {
        "body_mode": result.body_mode,
        "mass_kg": result.mass_kg,
        "estimated_mass_kg": result.estimated_mass_kg,
        "volume_m3": result.volume_m3,
        "material_density": result.material_density,
        "friction": result.friction,
        "restitution": result.restitution,
        "can_topple": result.can_topple,
        "override_reason": result.override_reason,
        "category": result.category,
        "material": result.material,
    }

def settle_classified_bodies(
    *, bodies: Sequence[Mapping[str, Any]], placements: Mapping[str, Mapping[str, Any]],
    room_dimensions: Sequence[float], max_iterations: int = 500, timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Settle dynamic boxes in PyBullet DIRECT; preserve static DA3 anchors exactly."""
    width, depth, height = (float(value) for value in room_dimensions)
    by_id = {str(item["object_id"]): item for item in bodies}
    if set(by_id) != set(placements):
        raise RuntimeError("physics bodies and Plan placements differ")
    dynamic_ids = sorted(key for key, item in by_id.items() if item["body_mode"] == "DYNAMIC")
    static_ids = sorted(set(by_id) - set(dynamic_ids))
    transforms: dict[str, dict[str, Any]] = {}
    for object_id in static_ids:
        placement = placements[object_id]
        dimensions = list(by_id[object_id]["collision_dimensions_m"])
        transforms[object_id] = {
            "object_id": object_id,
            "position": [float(placement["x"]) - width / 2.0, float(placement.get("elevation", 0.0)), float(placement["y"]) - depth / 2.0],
            "rotation": [0.0, 0.0, 0.0, 1.0], "scale": dimensions,
            "body_mode": "STATIC", "settle_method": "static DA3 anchor preservation",
        }
    if not dynamic_ids:
        return {"transforms": [transforms[key] for key in sorted(transforms)], "iterations": 0, "elapsed_seconds": 0.0, "engine": "none-required-static-only"}

    try:
        import pybullet as bullet
    except ImportError as exc:
        raise RuntimeError("strict-real dynamic settling requires PyBullet") from exc
    client = bullet.connect(bullet.DIRECT)
    started = time.monotonic()
    try:
        bullet.setGravity(0.0, -9.81, 0.0, physicsClientId=client)
        bullet.setTimeStep(1.0 / 240.0, physicsClientId=client)
        floor_shape = bullet.createCollisionShape(bullet.GEOM_BOX, halfExtents=[width / 2.0, 0.05, depth / 2.0], physicsClientId=client)
        bullet.createMultiBody(baseMass=0.0, baseCollisionShapeIndex=floor_shape, basePosition=[0.0, -0.05, 0.0], physicsClientId=client)
        wall_specs = (([0.05, height / 2.0, depth / 2.0], [-width / 2.0, height / 2.0, 0.0]), ([0.05, height / 2.0, depth / 2.0], [width / 2.0, height / 2.0, 0.0]), ([width / 2.0, height / 2.0, 0.05], [0.0, height / 2.0, -depth / 2.0]), ([width / 2.0, height / 2.0, 0.05], [0.0, height / 2.0, depth / 2.0]))
        for half_extents, position in wall_specs:
            shape = bullet.createCollisionShape(bullet.GEOM_BOX, halfExtents=half_extents, physicsClientId=client)
            bullet.createMultiBody(baseMass=0.0, baseCollisionShapeIndex=shape, basePosition=position, physicsClientId=client)
        for object_id in static_ids:
            placement, body = placements[object_id], by_id[object_id]
            dims = [float(value) for value in body["collision_dimensions_m"]]
            shape = bullet.createCollisionShape(bullet.GEOM_BOX, halfExtents=[value / 2.0 for value in dims], physicsClientId=client)
            center = [float(placement["x"]) - width / 2.0, float(placement.get("elevation", 0.0)) + dims[1] / 2.0, float(placement["y"]) - depth / 2.0]
            bullet.createMultiBody(baseMass=0.0, baseCollisionShapeIndex=shape, basePosition=center, physicsClientId=client)
        runtime_ids: dict[str, int] = {}
        initial_orientations: dict[str, tuple[float, float, float, float]] = {}
        for object_id in dynamic_ids:
            placement, body = placements[object_id], by_id[object_id]
            dims = [float(value) for value in body["collision_dimensions_m"]]
            shape = bullet.createCollisionShape(bullet.GEOM_BOX, halfExtents=[value / 2.0 for value in dims], physicsClientId=client)
            center = [float(placement["x"]) - width / 2.0, float(placement.get("elevation", 0.0)) + dims[1] / 2.0, float(placement["y"]) - depth / 2.0]
            runtime_ids[object_id] = bullet.createMultiBody(baseMass=max(0.001, float(body["mass_kg"])), baseCollisionShapeIndex=shape, basePosition=center, physicsClientId=client)
            initial_orientations[object_id] = (0.0, 0.0, 0.0, 1.0)
            bullet.changeDynamics(runtime_ids[object_id], -1, lateralFriction=float(body["friction"]), restitution=float(body["restitution"]), physicsClientId=client)
        stable_frames = 0
        iterations = 0
        while iterations < max_iterations and time.monotonic() - started <= timeout_s:
            bullet.stepSimulation(physicsClientId=client)
            iterations += 1
            speeds = []
            for object_id, body_id in runtime_ids.items():
                position, _ = bullet.getBasePositionAndOrientation(body_id, physicsClientId=client)
                linear, _ = bullet.getBaseVelocity(body_id, physicsClientId=client)
                bullet.resetBasePositionAndOrientation(body_id, position, initial_orientations[object_id], physicsClientId=client)
                bullet.resetBaseVelocity(body_id, linearVelocity=linear, angularVelocity=[0.0, 0.0, 0.0], physicsClientId=client)
                speeds.append(math.sqrt(sum(float(value) ** 2 for value in linear)))
            stable_frames = stable_frames + 1 if speeds and max(speeds) <= 0.01 else 0
            if stable_frames >= 30:
                break
        elapsed = time.monotonic() - started
        for object_id, body_id in runtime_ids.items():
            center, rotation = bullet.getBasePositionAndOrientation(body_id, physicsClientId=client)
            linear, angular = bullet.getBaseVelocity(body_id, physicsClientId=client)
            dims = [float(value) for value in by_id[object_id]["collision_dimensions_m"]]
            speed = math.sqrt(sum(float(value) ** 2 for value in (*linear, *angular)))
            if speed > 0.02 or center[1] - dims[1] / 2.0 < -0.01 or center[1] + dims[1] / 2.0 > height + 0.01:
                raise RuntimeError(f"PyBullet did not produce a stable in-room transform for {object_id}")
            transforms[object_id] = {"object_id": object_id, "position": [float(center[0]), float(center[1] - dims[1] / 2.0), float(center[2])], "rotation": [float(value) for value in rotation], "scale": dims, "body_mode": "DYNAMIC", "settle_method": "PyBullet DIRECT upright-box settle", "final_speed": speed}
        return {"transforms": [transforms[key] for key in sorted(transforms)], "iterations": iterations, "elapsed_seconds": elapsed, "engine": "pybullet-direct"}
    finally:
        bullet.disconnect(client)
