"""Fail-closed V16 adapters backed by Canon, DA3, and approved real meshes."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from src.unified_pipeline.depth_bridge import FORBIDDEN_DEPTH_AUTHORITIES
from src.unified_pipeline.object_manifest import (
    file_sha256,
    load_detected_document,
    load_selected_manifest,
)
from src.unified_pipeline.orchestrator import StageExecutionContext, StageResult


# A Canon-derived monocular shell may be metrically self-consistent but too
# small for a human-scale playable room. Normalize it once with a single
# camera-anchored similarity; never stretch axes independently.
MIN_PLAYABLE_ROOM_SPAN_M = 2.5
MIN_PLAYABLE_ROOM_HEIGHT_M = 2.4


def _depth_authority_labels() -> dict[str, Any]:
    """Return the fail-closed authority envelope for every DA3 artifact."""
    return {
        "evidence_kind": "depth_evidence",
        "evidence_only": True,
        "optional": True,
        "spatial_authority": False,
        "collision_enabled": False,
        "authority_claims": [],
        "forbidden_authorities": list(FORBIDDEN_DEPTH_AUTHORITIES),
    }


def _strict(ctx: StageExecutionContext) -> bool:
    return ctx.values.get("execution_profile") == "strict_real"


def _legacy(name: str, ctx: StageExecutionContext) -> StageResult:
    from src.unified_pipeline import stage_handlers
    return getattr(stage_handlers, name)(ctx)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stage_result(ctx: StageExecutionContext, output: Mapping[str, Any], *, revision: int | None = None) -> StageResult:
    return StageResult(
        output=dict(output),
        plan_revision=ctx.plan_revision if revision is None else revision,
        approval_revision=ctx.approval_revision,
        canonical_hash=_canonical_hash(dict(output)),
    )


def _mesh_parts(path: Path) -> list[Any]:
    import numpy as np
    import trimesh

    loaded = trimesh.load(path, force="scene", process=False)
    scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
    parts: list[Any] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            continue
        if not np.isfinite(mesh.vertices).all():
            raise RuntimeError(f"mesh contains non-finite vertices: {path}")
        parts.append(mesh)
    if not parts:
        raise RuntimeError(f"GLB contains no nonempty triangle geometry: {path}")
    return parts


def _mesh_evidence(path: Path, *, require_uv: bool) -> dict[str, Any]:
    import numpy as np

    if not path.is_file() or path.suffix.lower() != ".glb" or path.stat().st_size < 1024:
        raise RuntimeError(f"real GLB artifact is missing or trivial: {path}")
    parts = _mesh_parts(path)
    vertices = np.concatenate([part.vertices for part in parts], axis=0)
    bounds_min = vertices.min(axis=0)
    bounds_max = vertices.max(axis=0)
    extents = bounds_max - bounds_min
    if not np.isfinite(extents).all() or float(extents.min()) <= 0.01:
        raise RuntimeError("DA3 room mesh has invalid metric extents")
    uv_vertices = 0
    for part in parts:
        uv = getattr(part.visual, "uv", None)
        if uv is not None and len(uv) == len(part.vertices):
            uv_vertices += len(uv)
    if require_uv and uv_vertices != len(vertices):
        raise RuntimeError("DA3 room mesh lacks complete UV authority")
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "byte_count": path.stat().st_size,
        "geometry_count": len(parts),
        "vertex_count": int(sum(len(part.vertices) for part in parts)),
        "face_count": int(sum(len(part.faces) for part in parts)),
        "uv_vertex_count": int(uv_vertices),
        "bounds_minimum_m": [float(value) for value in bounds_min],
        "bounds_maximum_m": [float(value) for value in bounds_max],
        "extents_m": [float(value) for value in extents],
    }


def _uv_geometry(path: Path) -> tuple[Any, Any, list[Any]]:
    import numpy as np

    parts = _mesh_parts(path)
    vertices: list[Any] = []
    uvs: list[Any] = []
    for part in parts:
        uv = getattr(part.visual, "uv", None)
        if uv is None or len(uv) != len(part.vertices):
            raise RuntimeError("DA3 geometry must provide one UV coordinate per vertex")
        vertices.append(np.asarray(part.vertices, dtype=np.float64))
        uvs.append(np.asarray(uv, dtype=np.float64))
    return np.concatenate(vertices), np.concatenate(uvs), parts


def _load_spatial(ctx: StageExecutionContext) -> dict[str, Any]:
    path = ctx.session_dir / "artifacts" / "spatial_solution.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("solution_sha256", "")
    if expected != _canonical_hash(value):
        raise RuntimeError("spatial solution hash is invalid")
    value["solution_sha256"] = expected
    return value


def _load_plan_camera(ctx: StageExecutionContext, *, approved: bool = False):
    from src.unified_pipeline.camera_contract import CameraContract
    from src.unified_pipeline.models import MetricPlan

    spatial = _load_spatial(ctx)
    plan_data = spatial["metric_plan"]
    if approved:
        approved_path = ctx.session_dir / "artifacts" / "approved_metric_plan.json"
        approved_doc = json.loads(approved_path.read_text(encoding="utf-8"))
        expected = approved_doc.pop("document_sha256", "")
        if expected != _canonical_hash(approved_doc):
            raise RuntimeError("approved MetricPlan hash document is invalid")
        plan_data = approved_doc["metric_plan"]
    return MetricPlan.from_dict(plan_data), CameraContract.from_dict(spatial["camera"]), spatial


async def handle_depth_estimation(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        from src.unified_pipeline.stage_handlers import _handle_depth_estimation
        return await _handle_depth_estimation(ctx)

    import httpx
    from src.photo_pipeline.comfyui_client import ComfyUIClient

    artifacts = ctx.session_dir / "artifacts"
    canon_output = ctx.values.get("stage_outputs", {}).get("canon_generation", {})
    canon = Path(str(canon_output.get("image_path", artifacts / "canon.png")))
    if not canon.is_file():
        canon = artifacts / "canon.png"
    if not canon.is_file():
        raise RuntimeError("strict-real DA3 requires the approved Canon image")

    required_nodes = {
        "LoadImage", "LoadDA3Model", "DA3Inference", "DA3GeometryToMesh", "SaveGLB"
    }
    model_name = "depth_anything_3_metric_large.safetensors"
    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.get("http://127.0.0.1:8188/object_info")
        response.raise_for_status()
        object_info = response.json()
    missing = sorted(required_nodes - set(object_info))
    if missing:
        raise RuntimeError("ComfyUI lacks required DA3 nodes: " + ", ".join(missing))
    model_spec = json.dumps(object_info["LoadDA3Model"], sort_keys=True)
    if model_name not in model_spec:
        raise RuntimeError(f"ComfyUI LoadDA3Model does not expose {model_name}")

    client = ComfyUIClient(
        base_url="http://127.0.0.1:8188", timeout_s=900, poll_interval_s=0.75
    )
    if not await client.health_check():
        raise RuntimeError("ComfyUI is unavailable; strict-real DA3 has no fallback")
    uploaded_name = await client.upload_image(canon)
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
        "2": {"class_type": "LoadDA3Model", "inputs": {
            "model_name": model_name, "weight_dtype": "fp16"
        }},
        "3": {"class_type": "DA3Inference", "inputs": {
            "da3_model": ["2", 0], "image": ["1", 0], "resolution": 504,
            "resize_method": "upper_bound_resize", "mode": "mono"
        }},
        "4": {"class_type": "DA3GeometryToMesh", "inputs": {
            "da3_geometry": ["3", 0], "batch_index": 0, "decimation": 2,
            "discontinuity_threshold": 0.04, "confidence_threshold": 0.1,
            "use_sky_mask": True, "texture": True
        }},
        "5": {"class_type": "SaveGLB", "inputs": {
            "mesh": ["4", 0],
            "filename_prefix": f"3d/v16-{ctx.session_id[:12]}-room-raw"
        }},
    }
    started = time.monotonic()
    prompt_id = await client.submit_workflow(
        workflow, client_id=f"v16-da3-{ctx.session_id}", timeout_s=900
    )
    history = await client.wait_for_completion(prompt_id, timeout_s=900)
    output_path = await client.get_output_mesh(
        prompt_id, artifacts, filename="room_shell_raw.glb", node_id="5"
    )
    elapsed = time.monotonic() - started
    evidence = _mesh_evidence(output_path, require_uv=True)
    source_hash = file_sha256(canon)
    record: dict[str, Any] = {
        "schema_version": "da3-metric-room-evidence/v1",
        "source_canon_path": str(canon),
        "source_canon_sha256": source_hash,
        "model": model_name,
        "nodes": sorted(required_nodes),
        "workflow_sha256": _canonical_hash(workflow),
        "prompt_id": prompt_id,
        "comfy_status": history.get("status", {}).get("status_str", "success"),
        "elapsed_seconds": round(elapsed, 3),
        "mesh": evidence,
        "fallback_used": False,
        "spatial_scale": "metric",
        "coordinate_provenance": "DA3 mono camera-space geometry",
        **_depth_authority_labels(),
    }
    record["evidence_sha256"] = _canonical_hash(record)
    _atomic_json(artifacts / "depth_evidence.json", record)
    return _stage_result(ctx, {
        "status": "da3_metric_room_complete",
        "depth_path": str(output_path),
        "room_shell_raw_path": str(output_path),
        "room_shell_raw_sha256": evidence["sha256"],
        "vertex_count": evidence["vertex_count"],
        "face_count": evidence["face_count"],
        "uv_vertex_count": evidence["uv_vertex_count"],
        "metric_extents_m": evidence["extents_m"],
        "model": model_name,
        "elapsed_seconds": round(elapsed, 3),
        "fallback_used": False,
        "evidence_path": str(artifacts / "depth_evidence.json"),
        "evidence_sha256": record["evidence_sha256"],
        **_depth_authority_labels(),
    })


def handle_spatial_reconstruction(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_spatial_reconstruction", ctx)

    from src.unified_pipeline.blockout_renderer import (
        blockout_visibility_path,
        load_blockout_visibility,
        render_blockout,
    )
    from src.unified_pipeline.canon_first_authority import (
        build_candidate_authority,
        canonical_sha256,
    )
    from src.unified_pipeline.models import Brief

    artifacts = ctx.session_dir / "artifacts"
    brief_path = artifacts / "brief.json"
    detected_path = artifacts / "detected_objects.json"
    canon_path = artifacts / "canon.png"
    if not brief_path.is_file():
        raise RuntimeError(
            "strict-real spatial reconstruction requires a durable Brief; "
            "depth-only authority remains forbidden"
        )
    if not detected_path.is_file() or not canon_path.is_file():
        raise RuntimeError(
            "strict-real spatial reconstruction requires Canon-bound semantic detections"
        )

    brief_data = json.loads(brief_path.read_text(encoding="utf-8"))
    brief = Brief.from_dict(brief_data)
    detected = load_detected_document(detected_path)
    canon_sha256 = file_sha256(canon_path)
    if canon_sha256 != str(detected.get("canon_sha256", "")):
        raise RuntimeError("strict-real semantic detections are not bound to local Canon")

    revision_feedback = ctx.values.get("plan_revision_feedback")
    if revision_feedback is not None and not isinstance(revision_feedback, Mapping):
        raise RuntimeError("strict-real Plan revision feedback must be a mapping")
    candidate = build_candidate_authority(
        brief,
        detected,
        artifacts=artifacts,
        revision_feedback=revision_feedback,
    )
    documents = candidate.documents(
        brief_sha256=canonical_sha256(brief_data),
        detected_sha256=str(detected["document_sha256"]),
        canon_sha256=canon_sha256,
    )
    blockout_path = artifacts / "blockout.png"
    blockout = render_blockout(candidate.plan, candidate.camera, blockout_path)
    visibility = load_blockout_visibility(blockout_path)
    if visibility["plan_revision"] != candidate.plan.revisions[-1].revision:
        raise RuntimeError("blockout visibility evidence revision mismatch")
    if visibility["camera_sha256"] != candidate.camera.compute_hash():
        raise RuntimeError("blockout visibility evidence camera mismatch")
    if candidate.plan.revisions[-1].revision >= 2 and not visibility["fully_green"]:
        raise RuntimeError("revised blockout failed deterministic visibility gate")
    if blockout.approved:
        raise RuntimeError("candidate blockout must remain unapproved at spatial reconstruction")

    binding_by_detection: dict[str, dict[str, Any]] = {}
    for binding in candidate.bindings["required_bindings"]:
        for index, detection_id in enumerate(binding["detected_object_ids"]):
            plan_ids = binding["plan_binding_ids"]
            binding_by_detection[detection_id] = {
                "required": True,
                "manifest_id": binding["manifest_id"],
                "semantic_concept": binding["semantic_concept"],
                "plan_binding_id": plan_ids[index] if index < len(plan_ids) else "",
                "observation_authority": False,
            }
    picker_objects = []
    for item in detected["objects"]:
        detection_id = str(item["object_id"])
        picker_objects.append({
            **dict(item),
            **binding_by_detection.get(detection_id, {
                "required": False,
                "manifest_id": "",
                "semantic_concept": "extra_observation",
                "plan_binding_id": "",
                "observation_authority": False,
            }),
        })
    picker: dict[str, Any] = {
        "schema_version": "candidate-object-picker/v1",
        "authority_state": "semantic_observations_pending_blockout_approval",
        "human_approved": False,
        "blockout_image": "blockout.png",
        "plan_revision": candidate.plan.revisions[-1].revision,
        "metric_plan_sha256": documents["spatial"]["metric_plan_sha256"],
        "camera_sha256": candidate.camera.compute_hash(),
        "blockout_visibility_sha256": visibility["report_sha256"],
        "blockout_visibility_path": str(blockout_visibility_path(blockout_path)),
        "canon_sha256": canon_sha256,
        "detected_objects_sha256": detected["document_sha256"],
        "objects": picker_objects,
        "required_bindings": candidate.bindings["required_bindings"],
        "extra_observation_ids": [
            str(item["object_id"])
            for item in candidate.bindings["extra_observations"]
        ],
        "fuzzy_matching_used": False,
        "detection_coordinates_used_for_plan": False,
    }
    picker["document_sha256"] = canonical_sha256(picker)

    _atomic_json(artifacts / "candidate_metric_plan.json", documents["plan"])
    _atomic_json(artifacts / "camera_contract.json", documents["camera"])
    _atomic_json(artifacts / "spatial_solution.json", documents["spatial"])
    _atomic_json(artifacts / "object_picker.json", picker)

    return _stage_result(ctx, {
        "status": "strict_real_candidate_spatial_reconstruction_complete",
        "authority_state": "validated_candidate_pending_blockout_approval",
        "human_approved": False,
        "candidate_metric_plan_path": str(artifacts / "candidate_metric_plan.json"),
        "camera_contract_path": str(artifacts / "camera_contract.json"),
        "spatial_solution_path": str(artifacts / "spatial_solution.json"),
        "spatial_solution_sha256": documents["spatial"]["solution_sha256"],
        "image_path": str(blockout_path),
        "object_picker_path": str(artifacts / "object_picker.json"),
        "blockout_visibility_path": str(blockout_visibility_path(blockout_path)),
        "blockout_visibility_sha256": visibility["report_sha256"],
        "blockout_visibility_green": visibility["fully_green"],
        "plan_revision": candidate.plan.revisions[-1].revision,
        "room_dimensions_m": list(candidate.plan.room_dimensions),
        "opening_count": len(candidate.plan.openings),
        "circulation_minimum_m": min(
            float(item["min_width"]) for item in candidate.plan.circulation_paths
        ),
        "required_binding_count": len(candidate.bindings["required_bindings"]),
        "extra_observation_count": len(candidate.bindings["extra_observations"]),
        "camera_sha256": candidate.camera.compute_hash(),
        "depth_reference": candidate.depth_reference,
        "blockout_approved": False,
    }, revision=candidate.plan.revisions[-1].revision)


def _unsafe_depth_authority_spatial_reconstruction(
    ctx: StageExecutionContext,
) -> StageResult:
    """Quarantined historical implementation; never dispatch in production.

    Retained temporarily as diagnostic evidence for Task 11.8. It promotes DA3
    camera-space geometry into spatial authority and therefore violates the
    corrected authority boundary.
    """
    if not _strict(ctx):
        return _legacy("_handle_spatial_reconstruction", ctx)

    import numpy as np
    from PIL import Image
    from src.unified_pipeline.models import MetricPlan, PlanRevision
    from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
    from src.unified_pipeline.plan_validator import _compute_plan_hash
    from src.unified_pipeline.camera_contract import CameraContract

    artifacts = ctx.session_dir / "artifacts"
    detected = load_detected_document(artifacts / "detected_objects.json")
    raw_room = artifacts / "room_shell_raw.glb"
    evidence = json.loads((artifacts / "depth_evidence.json").read_text(encoding="utf-8"))
    if file_sha256(raw_room) != evidence.get("mesh", {}).get("sha256"):
        raise RuntimeError("DA3 room mesh does not match depth evidence")
    canon = Path(str(detected["image_path"]))
    if not canon.is_file() or file_sha256(canon) != detected["canon_sha256"]:
        raise RuntimeError("spatial reconstruction Canon binding is invalid")

    vertices, uvs, _ = _uv_geometry(raw_room)
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    extents = maximum - minimum
    raw_width_m, raw_height_m, raw_depth_m = map(
        float, (extents[0], extents[1], extents[2])
    )
    if min(raw_width_m, raw_height_m, raw_depth_m) <= 0.1:
        raise RuntimeError("DA3 room dimensions are not physically valid")
    uniform_scale = max(
        1.0,
        MIN_PLAYABLE_ROOM_SPAN_M / raw_width_m,
        MIN_PLAYABLE_ROOM_SPAN_M / raw_depth_m,
        MIN_PLAYABLE_ROOM_HEIGHT_M / raw_height_m,
    )
    width_m = raw_width_m * uniform_scale
    height_m = raw_height_m * uniform_scale
    depth_m = raw_depth_m * uniform_scale
    negative_z_ratio = float(np.mean(vertices[:, 2] < -0.01))
    if negative_z_ratio < 0.75:
        raise RuntimeError("DA3 camera-space convention could not be verified")

    depth = -vertices[:, 2]
    fy_mask = (
        (depth > 0.05) & (np.abs(vertices[:, 1]) > 1e-4)
        & (np.abs(uvs[:, 1] - 0.5) > 0.02)
    )
    fy_samples = np.abs((uvs[fy_mask, 1] - 0.5) * depth[fy_mask] / vertices[fy_mask, 1])
    fy_samples = fy_samples[np.isfinite(fy_samples) & (fy_samples > 0.05) & (fy_samples < 10.0)]
    if len(fy_samples) < 100:
        raise RuntimeError("DA3 UV geometry cannot recover authoritative camera intrinsics")
    fy_normalized = float(np.median(fy_samples))
    vfov = math.degrees(2.0 * math.atan(0.5 / fy_normalized))
    if not 20.0 <= vfov <= 120.0:
        raise RuntimeError(f"recovered DA3 vertical FOV is invalid: {vfov}")

    image_width = int(detected["image_width"])
    image_height = int(detected["image_height"])
    with Image.open(canon) as image:
        if image.size != (image_width, image_height):
            raise RuntimeError("detected-object raster does not match Canon")
    center = (minimum + maximum) / 2.0
    raw_translation = np.asarray(
        [-float(center[0]), -float(minimum[1]), -float(center[2])],
        dtype=float,
    )
    camera_position = raw_translation * uniform_scale
    camera = CameraContract(
        position=tuple(float(value) for value in camera_position),
        target=(
            float(camera_position[0]),
            float(camera_position[1]),
            float(camera_position[2] - uniform_scale),
        ),
        up=(0.0, 1.0, 0.0), vfov=vfov,
        aspect=image_width / image_height, near=0.05,
        far=max(100.0, depth_m * 10.0),
        raster_width=image_width, raster_height=image_height,
    )

    placements: list[dict[str, Any]] = []
    solved_objects: list[dict[str, Any]] = []
    for item in detected["objects"]:
        x1, y1, x2, y2 = (float(value) for value in item["bbox"])
        u1, u2 = x1 / image_width, x2 / image_width
        v1, v2 = 1.0 - y2 / image_height, 1.0 - y1 / image_height
        region = (
            (uvs[:, 0] >= u1) & (uvs[:, 0] <= u2)
            & (uvs[:, 1] >= v1) & (uvs[:, 1] <= v2)
        )
        local = vertices[region]
        if len(local) < 12:
            raise RuntimeError(f"DA3 has insufficient UV geometry for {item['object_id']}")
        lower = np.percentile(local, 5.0, axis=0)
        upper = np.percentile(local, 95.0, axis=0)
        local_extents = np.maximum(upper - lower, 0.03) * uniform_scale
        uv_center = np.array([(u1 + u2) / 2.0, (v1 + v2) / 2.0])
        nearest = np.argsort(np.sum((uvs - uv_center) ** 2, axis=1))[:25]
        anchor_raw = np.median(vertices[nearest], axis=0)
        object_width = min(float(local_extents[0]), width_m)
        object_height = min(float(local_extents[1]), height_m)
        object_depth = min(float(local_extents[2]), depth_m)
        elevation = max(
            0.0,
            float(anchor_raw[1] - minimum[1]) * uniform_scale
            - object_height / 2.0,
        )
        placement = {
            "id": str(item["object_id"]), "name": str(item["name"]),
            "x": float(anchor_raw[0] - minimum[0]) * uniform_scale,
            "y": float(anchor_raw[2] - minimum[2]) * uniform_scale,
            "elevation": elevation,
            "width": object_width, "height": object_height, "depth": object_depth,
            "rotation_deg": 0.0,
        }
        placements.append(placement)
        solved_objects.append({
            "object_id": str(item["object_id"]), "name": str(item["name"]),
            "bbox": list(item["bbox"]),
            "position_camera_m": [float(value) for value in anchor_raw],
            "position_contract_m": [
                float(anchor_raw[0] - center[0]) * uniform_scale,
                elevation,
                float(anchor_raw[2] - center[2]) * uniform_scale,
            ],
            "dimensions_m": [object_width, object_height, object_depth],
            "uv_region": [u1, v1, u2, v2],
            "sample_count": int(len(local)),
            "provenance": "DA3 metric GLB UV-region percentile solve",
        })

    revision = max(1, int(ctx.plan_revision))
    base_plan = MetricPlan(
        room_dimensions=(width_m, depth_m, height_m),
        walls=_build_walls_from_dimensions(width_m, depth_m, height_m),
        object_placements=tuple(placements),
        template_id="da3-canon-metric-room",
    )
    plan = replace(base_plan, revisions=(PlanRevision(
        revision=revision, changed="uniformly normalized DA3 metric Canon reconstruction",
        reason="camera-anchored playable-room normalization before blockout approval",
        plan_hash=_compute_plan_hash(base_plan),
    ),))
    solution: dict[str, Any] = {
        "schema_version": "strict-real-spatial-solution/v1",
        "canon_sha256": detected["canon_sha256"],
        "detected_objects_sha256": detected["document_sha256"],
        "room_shell_raw_sha256": file_sha256(raw_room),
        "room_bounds_camera_m": {
            "minimum": [float(value) for value in minimum],
            "maximum": [float(value) for value in maximum],
        },
        "raw_room_dimensions_m": [raw_width_m, raw_depth_m, raw_height_m],
        "room_dimensions_m": [width_m, depth_m, height_m],
        "uniform_scale_camera_to_contract": uniform_scale,
        "camera": camera.to_dict(), "camera_sha256": camera.compute_hash(),
        "camera_intrinsics_provenance": "recovered from DA3 metric vertices and texture UVs",
        "metric_plan": plan.to_dict(), "objects": solved_objects,
        "coordinate_transform": {
            "translation_camera_to_contract_m": [
                float(value) for value in raw_translation
            ],
            "uniform_scale_camera_to_contract": uniform_scale,
            "operation_order": ["translate", "uniform_scale"],
            "rotation": [0.0, 0.0, 0.0, 1.0],
        },
        "fallback_used": False,
    }
    solution["solution_sha256"] = _canonical_hash(solution)
    _atomic_json(artifacts / "spatial_solution.json", solution)

    visual = _legacy("_handle_spatial_reconstruction", ctx)
    return _stage_result(ctx, {
        **visual.output,
        "status": "strict_real_spatial_reconstruction_complete",
        "spatial_solution_path": str(artifacts / "spatial_solution.json"),
        "spatial_solution_sha256": solution["solution_sha256"],
        "camera_sha256": solution["camera_sha256"],
        "room_dimensions_m": solution["room_dimensions_m"],
        "object_count": len(solved_objects), "fallback_used": False,
    }, revision=revision)


def _material_parameters(material: str) -> tuple[str, float, float]:
    """Return explicit environment-free PBR intent before contract assembly.

    The current WorldContract has no environment-map authority.  A nearly pure
    metal (0.9) therefore reflects mostly the black scene background even when
    direct lighting is valid.  Preserve metallic identity as a bounded mixed
    conductor/dielectric value instead of erasing it, and require a future
    explicit environment binding before restoring near-pure metalness.
    """
    value = material.casefold()
    table = (
        (("steel", "metal", "iron", "chrome", "aluminum"), ("#B7BDC5", 0.35, 0.32)),
        (("glass",), ("#D6F0F5", 0.0, 0.08)),
        (("wood", "oak", "walnut", "timber", "cabinet", "countertop"), ("#8A5A32", 0.0, 0.68)),
        (("ceramic", "porcelain", "tile", "stone", "marble"), ("#E9E0D2", 0.0, 0.36)),
        (("fabric", "cloth", "linen", "leather"), ("#8F6B55", 0.0, 0.88)),
        (("plastic", "rubber"), ("#C9A86A", 0.0, 0.48)),
    )
    for names, result in table:
        if any(name in value for name in names):
            return result
    raise RuntimeError(f"strict-real material classification is not authoritative: {material!r}")


def handle_material_pass_1(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_material_pass_1", ctx)
    selected = load_selected_manifest(ctx.session_dir / "artifacts" / "selected_objects.json")
    item = next((
        value for value in selected["objects"]
        if str(value.get("plan_instance_id") or value["object_id"]) == ctx.object_id
    ), None)
    if item is None:
        raise RuntimeError(f"material object is not selected: {ctx.object_id}")
    mesh_output = ctx.values.get("stage_outputs", {}).get("mesh_generation", {}).get(ctx.object_id, {})
    mesh = Path(str(mesh_output.get("mesh_path", "")))
    evidence = _mesh_evidence(mesh, require_uv=False)
    if mesh_output.get("generator") not in {"hunyuan3d_v2.1", "trellis2"}:
        raise RuntimeError(f"material stage rejects non-real generator for {ctx.object_id}")
    if evidence["sha256"] != mesh_output.get("mesh_sha256"):
        raise RuntimeError(f"approved mesh hash drift for {ctx.object_id}")
    from src.unified_pipeline.mesh_shading import audit_glb_shading

    shading = audit_glb_shading(mesh, expected_sha256=evidence["sha256"])
    base_color, metallic, roughness = _material_parameters(str(item.get("material", "")))
    intent = {
        "base_color": base_color, "metallic": metallic, "roughness": roughness,
        "normal_map_ref": "", "pass_level": 1,
        "shading_model": shading.shading_model,
        "shading_provenance": shading.provenance_sha256,
        "render_profile": "environment-free-bounded-metallic/v1",
    }
    return _stage_result(ctx, {
        "status": "material_pass_1_complete", "object_id": ctx.object_id,
        "material_intent": intent,
        "material_source": "Canon detected-object inventory plus approved-GLB normal audit",
        "material_render_profile": "environment-free-bounded-metallic/v1",
        "material_label": item["material"], "category": item["category"],
        "mesh_sha256": evidence["sha256"],
        "shading_audit": shading.to_dict(),
        "fallback_used": False,
    })


def _approved_plan(ctx: StageExecutionContext):
    from src.unified_pipeline.models import MetricPlan, PlanRevision
    from src.unified_pipeline.plan_validator import _compute_plan_hash

    plan, camera, spatial = _load_plan_camera(ctx)
    selected = load_selected_manifest(ctx.session_dir / "artifacts" / "selected_objects.json")
    if selected["canon_sha256"] != spatial["canon_sha256"]:
        raise RuntimeError("selected objects do not bind the spatial Canon")
    selected_ids = {
        str(item.get("plan_instance_id") or item["object_id"])
        for item in selected["objects"]
    }
    placements = tuple(
        item for item in plan.object_placements if str(item.get("id")) in selected_ids
    )
    if {str(item["id"]) for item in placements} != selected_ids:
        raise RuntimeError("selected objects and spatial placements are not equal")
    revision = int(selected["plan_revision"])
    if revision <= 0 or revision != plan.revisions[-1].revision:
        raise RuntimeError("selected manifest targets a stale spatial Plan")
    base = replace(plan, object_placements=placements, revisions=())
    approved = replace(base, revisions=(PlanRevision(
        revision=revision,
        changed="approved Canon object selection",
        reason=f"selected manifest {selected['manifest_sha256']}",
        plan_hash=_compute_plan_hash(base),
    ),))
    return approved, camera, spatial, selected


def _approval_gate(plan: Any, camera: Any):
    from src.unified_pipeline.approval_gates import ApprovalGate

    gate = ApprovalGate("blockout", "plan_blockout")
    gate.present({
        "plan_revision": plan.revisions[-1].revision,
        "camera_hash": camera.compute_hash(),
    })
    gate.approve()
    return gate


def _carve_and_transform_room(ctx: StageExecutionContext, spatial: Mapping[str, Any], selected: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    import numpy as np
    import trimesh

    artifacts = ctx.session_dir / "artifacts"
    raw_path = artifacts / "room_shell_raw.glb"
    if file_sha256(raw_path) != spatial["room_shell_raw_sha256"]:
        raise RuntimeError("raw room shell hash drifted after spatial approval")
    detected = load_detected_document(artifacts / "detected_objects.json")
    width, height = float(detected["image_width"]), float(detected["image_height"])
    regions = []
    for item in selected["objects"]:
        x1, y1, x2, y2 = map(float, item["bbox"])
        object_id = str(item.get("plan_instance_id") or item["object_id"])
        regions.append((object_id, x1 / width, 1.0 - y2 / height, x2 / width, 1.0 - y1 / height))
    transform = spatial["coordinate_transform"]
    translation = np.asarray(
        transform["translation_camera_to_contract_m"], dtype=float
    )
    uniform_scale = float(transform.get("uniform_scale_camera_to_contract", 1.0))
    if not math.isfinite(uniform_scale) or uniform_scale <= 0.0:
        raise RuntimeError("room transform uniform scale is invalid")
    parts = _mesh_parts(raw_path)
    hits = {object_id: 0 for object_id, *_ in regions}
    removed_total = 0
    transformed: list[Any] = []
    for mesh in parts:
        uv = getattr(mesh.visual, "uv", None)
        if uv is None or len(uv) != len(mesh.vertices):
            raise RuntimeError("room carve requires complete DA3 UVs")
        face_uv = np.asarray(uv)[mesh.faces].mean(axis=1)
        remove = np.zeros(len(mesh.faces), dtype=bool)
        for object_id, u1, v1, u2, v2 in regions:
            inside = (
                (face_uv[:, 0] >= u1) & (face_uv[:, 0] <= u2)
                & (face_uv[:, 1] >= v1) & (face_uv[:, 1] <= v2)
            )
            hits[object_id] += int(inside.sum())
            remove |= inside
        removed_total += int(remove.sum())
        mesh.update_faces(~remove)
        mesh.remove_unreferenced_vertices()
        mesh.apply_translation(translation)
        mesh.apply_scale(uniform_scale)
        if len(mesh.faces):
            transformed.append(mesh)
    if any(count <= 0 for count in hits.values()):
        missing = sorted(key for key, count in hits.items() if count <= 0)
        raise RuntimeError(f"selected UV regions removed no room geometry: {missing}")
    if not transformed or removed_total <= 0:
        raise RuntimeError("room carve removed no selected-object geometry")
    output = artifacts / "room_shell.glb"
    trimesh.Scene(transformed).export(output, file_type="glb")
    evidence = _mesh_evidence(output, require_uv=True)
    evidence.update({
        "source_sha256": spatial["room_shell_raw_sha256"],
        "selected_manifest_sha256": selected["manifest_sha256"],
        "removed_face_count": removed_total,
        "removed_faces_by_object": hits,
        "transform_translation_m": translation.tolist(),
        "transform_uniform_scale": uniform_scale,
        "fallback_used": False,
    })
    return output, evidence


def _build_room(ctx: StageExecutionContext):
    from src.unified_pipeline.parametric_room import build_authoritative_parametric_room

    plan, camera, spatial, selected = _approved_plan(ctx)
    room_path = ctx.session_dir / "artifacts" / "room_shell.glb"
    room_sha = file_sha256(room_path)
    room = build_authoritative_parametric_room(plan, camera, _approval_gate(plan, camera))
    room = replace(room, render_shell_path=str(room_path), render_shell_sha256=room_sha)
    return plan, camera, spatial, selected, room


def handle_parametric_room(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_parametric_room", ctx)
    plan, camera, spatial, selected = _approved_plan(ctx)
    from src.unified_pipeline.parametric_room import (
        build_authoritative_parametric_room,
        export_authoritative_room_glb,
    )

    room = build_authoritative_parametric_room(
        plan,
        camera,
        _approval_gate(plan, camera),
        authority_claims=(),
    )
    output_path = ctx.session_dir / "artifacts" / "room_shell.glb"
    mesh_evidence = export_authoritative_room_glb(room, output_path)
    room = replace(
        room, render_shell_path=str(output_path),
        render_shell_sha256=mesh_evidence["sha256"],
    )
    approved_document: dict[str, Any] = {
        "schema_version": "approved-metric-plan/v1",
        "selected_manifest_sha256": selected["manifest_sha256"],
        "spatial_solution_sha256": spatial["solution_sha256"],
        "metric_plan": plan.to_dict(),
    }
    approved_document["document_sha256"] = _canonical_hash(approved_document)
    artifacts = ctx.session_dir / "artifacts"
    _atomic_json(artifacts / "approved_metric_plan.json", approved_document)
    room_document: dict[str, Any] = {
        "schema_version": "strict-real-parametric-room/v2",
        "authority_policy": "approved MetricPlan and immutable CameraContract only",
        "depth_reference_role": "optional non-colliding appearance/reference only",
        "room": room.to_dict(), "mesh_evidence": mesh_evidence,
    }
    room_document["document_sha256"] = _canonical_hash(room_document)
    _atomic_json(artifacts / "parametric_room.json", room_document)
    return _stage_result(ctx, {
        "status": "parametric_room_built",
        "width_m": plan.room_dimensions[0], "depth_m": plan.room_dimensions[1],
        "height_m": plan.room_dimensions[2],
        "room_shell_path": str(output_path),
        "room_shell_sha256": mesh_evidence["sha256"],
        "room_collision_sha256": mesh_evidence["collision_sha256"],
        "geometry_count": mesh_evidence["geometry_count"],
        "face_count": mesh_evidence["face_count"],
        "vertex_count": mesh_evidence["vertex_count"],
        "opening_checks": mesh_evidence["opening_checks"],
        "depth_geometry_used": False,
        "plan_hash": plan.revisions[-1].plan_hash,
        "camera_sha256": camera.compute_hash(),
        "selected_manifest_sha256": selected["manifest_sha256"],
        "fallback_used": False,
    })


def handle_physics_classification(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_physics_classification", ctx)
    from src.unified_pipeline.strict_real_assets import classify_selected_body

    plan, _, _, selected, room = _build_room(ctx)
    meshes = ctx.values.get("stage_outputs", {}).get("mesh_generation", {})
    selected_by_id = {
        str(item.get("plan_instance_id") or item["object_id"]): item
        for item in selected["objects"]
    }
    selected_ids = set(selected_by_id)
    if set(meshes) != selected_ids:
        raise RuntimeError("physics mesh set does not exactly match approved selection")
    placements = {str(item["id"]): item for item in plan.object_placements}
    bodies: list[dict[str, Any]] = []
    for object_id in sorted(selected_ids):
        mesh_info = meshes[object_id]
        evidence = _mesh_evidence(Path(mesh_info["mesh_path"]), require_uv=False)
        if evidence["sha256"] != mesh_info.get("mesh_sha256"):
            raise RuntimeError(f"physics source mesh hash drift for {object_id}")
        normalization = mesh_info.get("normalization", {})
        if (
            normalization.get("normalization_count") != 1
            or normalization.get("normalized_sha256") != evidence["sha256"]
            or normalization.get("source_sha256") != mesh_info.get("source_mesh_sha256")
            or normalization.get("origin_policy") != "local-bounds-bottom-center"
        ):
            raise RuntimeError(f"physics rejects missing mesh normalization proof: {object_id}")
        placement = placements[object_id]
        dimensions = [
            float(placement["width"]), float(placement["height"]),
            float(placement["depth"]),
        ]
        item = selected_by_id[object_id]
        classified = classify_selected_body(
            plan_revision=plan.revisions[-1].revision,
            object_id=object_id,
            category=str(item["category"]),
            dimensions=dimensions,
            material=str(item["material"]),
        )
        bodies.append({
            "object_id": object_id,
            **classified,
            "shape": "box",
            "source_mesh_sha256": mesh_info["source_mesh_sha256"],
            "normalized_mesh_sha256": evidence["sha256"],
            "source_mesh_extents": list(mesh_info["source_mesh_extents"]),
            "collision_dimensions_m": dimensions,
            "classification_source": "approved Canon category/material plus V14 density policy",
        })
    document: dict[str, Any] = {
        "schema_version": "strict-real-physics-classification/v2",
        "selected_manifest_sha256": selected["manifest_sha256"],
        "plan_hash": plan.revisions[-1].plan_hash,
        "room_shell_sha256": room.render_shell_sha256,
        "bodies": bodies, "fallback_used": False,
    }
    document["document_sha256"] = _canonical_hash(document)
    path = ctx.session_dir / "artifacts" / "physics_classification.json"
    _atomic_json(path, document)
    return _stage_result(ctx, {
        "status": "physics_classified", "body_count": len(bodies),
        "dynamic_count": sum(item["body_mode"] == "DYNAMIC" for item in bodies),
        "static_count": sum(item["body_mode"] == "STATIC" for item in bodies),
        "classification_path": str(path),
        "classification_sha256": document["document_sha256"],
        "fallback_used": False,
    })


def handle_physics_settle(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_physics_settle", ctx)
    from src.unified_pipeline.strict_real_assets import settle_classified_bodies

    plan, _, _, selected, room = _build_room(ctx)
    classification_path = ctx.session_dir / "artifacts" / "physics_classification.json"
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    expected = classification.pop("document_sha256", "")
    if expected != _canonical_hash(classification):
        raise RuntimeError("physics classification hash is invalid")
    classification["document_sha256"] = expected
    bodies = {item["object_id"]: item for item in classification["bodies"]}
    selected_ids = {
        str(item.get("plan_instance_id") or item["object_id"])
        for item in selected["objects"]
    }
    if set(bodies) != selected_ids:
        raise RuntimeError("physics classification does not match selected objects")
    placements = {str(item["id"]): item for item in plan.object_placements}
    settled = settle_classified_bodies(
        bodies=classification["bodies"], placements=placements,
        room_dimensions=plan.room_dimensions,
        architectural_collision=[item.to_dict() for item in room.collision],
    )
    transforms = settled["transforms"]
    if {item["object_id"] for item in transforms} != selected_ids:
        raise RuntimeError("physics settle lost selected objects")
    for transform in transforms:
        body = bodies[transform["object_id"]]
        dimensions = transform["scale"]
        position = transform["position"]
        transform["collision"] = {
            "center": [position[0], position[1] + dimensions[1] / 2.0, position[2]],
            "dimensions": dimensions, "shape": "box",
            "body_mode": body["body_mode"],
            "source_mesh_sha256": body["source_mesh_sha256"],
            "normalized_mesh_sha256": body["normalized_mesh_sha256"],
        }
    document: dict[str, Any] = {
        "schema_version": "strict-real-physics-settle/v2",
        "selected_manifest_sha256": selected["manifest_sha256"],
        "classification_sha256": expected,
        "room_shell_sha256": room.render_shell_sha256,
        "engine": settled["engine"],
        "iterations": settled["iterations"],
        "elapsed_seconds": settled["elapsed_seconds"],
        "transforms": transforms, "passed": True, "fallback_used": False,
    }
    document["document_sha256"] = _canonical_hash(document)
    path = ctx.session_dir / "artifacts" / "physics_settle.json"
    _atomic_json(path, document)
    return _stage_result(ctx, {
        "status": "physics_settled", "passed": True,
        "object_count": len(transforms), "settle_path": str(path),
        "settle_sha256": document["document_sha256"],
        "engine": settled["engine"], "iterations": settled["iterations"],
        "elapsed_seconds": settled["elapsed_seconds"], "fallback_used": False,
    })


def _canon_lighting(ctx: StageExecutionContext, room_height: float):
    from PIL import Image, ImageStat
    from src.unified_pipeline.lighting_authority import derive_canon_lighting

    canon = ctx.session_dir / "artifacts" / "canon.png"
    if not canon.is_file():
        raise RuntimeError("Canon-derived lighting requires canon.png")
    with Image.open(canon).convert("RGB") as image:
        mean = tuple(float(value) for value in ImageStat.Stat(image.resize((64, 64))).mean)
    lighting, _ = derive_canon_lighting(
        mean,
        room_height_m=room_height,
        source_sha256=file_sha256(canon),
    )
    return lighting


def _plan_relationship_bindings(plan: Any, selected_ids: set[str]):
    """Convert only explicit MetricPlan-owned relations into canonical bindings."""
    from src.unified_pipeline.world_contract import Relationship

    bindings = []
    required = {"source_id", "target_id", "relationship_type", "authority", "semantic"}
    for index, raw in enumerate(plan.relationships):
        relation = dict(raw)
        missing = sorted(required - set(relation))
        if missing:
            raise RuntimeError(
                f"MetricPlan relationship {index} lacks explicit authority: {missing}"
            )
        source_id = str(relation["source_id"])
        target_id = str(relation["target_id"])
        if relation["authority"] != "metric_plan":
            raise RuntimeError(f"MetricPlan relationship {index} has non-Plan authority")
        if source_id not in selected_ids or target_id not in selected_ids | {"room"}:
            raise RuntimeError(
                f"MetricPlan relationship {index} references an unselected object"
            )
        metadata = json.dumps(
            {
                "authority": str(relation["authority"]),
                "semantic": str(relation["semantic"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        bindings.append(Relationship(
            source_id=source_id,
            target_id=target_id,
            relationship_type=str(relation["relationship_type"]),
            metadata=metadata,
        ))
    return tuple(sorted(bindings, key=lambda item: (
        item.source_id, item.target_id, item.relationship_type, item.metadata,
    )))


def handle_world_contract(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_world_contract", ctx)
    import uuid

    from src.unified_pipeline.assembler import (
        ApprovedAssetRecord, InstanceAssemblyInput, WorldContractAssembler,
    )
    from src.unified_pipeline.world_contract import (
        DynamicInteractionMetadata, InteractionBinding, InteractionCollider,
        MaterialIntent, Quaternion, Relationship, Vec3,
    )

    plan, camera, spatial, selected, room = _build_room(ctx)
    selected_ids = {
        str(item.get("plan_instance_id") or item["object_id"])
        for item in selected["objects"]
    }
    selected_by_id = {
        str(item.get("plan_instance_id") or item["object_id"]): item
        for item in selected["objects"]
    }
    placements_by_id = {
        str(item["id"]): item for item in plan.object_placements
    }
    if set(placements_by_id) != selected_ids:
        raise RuntimeError("WorldContract Plan placements do not match approved selection")
    outputs = ctx.values.get("stage_outputs", {})
    meshes = outputs.get("mesh_generation", {})
    materials = outputs.get("material_pass_1", {})
    if set(meshes) != selected_ids or set(materials) != selected_ids:
        raise RuntimeError("WorldContract inputs do not exactly match approved selection")

    artifacts = ctx.session_dir / "artifacts"
    settle = json.loads((artifacts / "physics_settle.json").read_text(encoding="utf-8"))
    settle_hash = settle.pop("document_sha256", "")
    if settle_hash != _canonical_hash(settle) or not settle.get("passed"):
        raise RuntimeError("WorldContract requires valid passing physics evidence")
    settled = {item["object_id"]: item for item in settle["transforms"]}
    if set(settled) != selected_ids:
        raise RuntimeError("physics settled set does not match approved selection")
    classification = json.loads(
        (artifacts / "physics_classification.json").read_text(encoding="utf-8")
    )
    classification_hash = classification.pop("document_sha256", "")
    if (
        classification_hash != _canonical_hash(classification)
        or settle.get("classification_sha256") != classification_hash
    ):
        raise RuntimeError("WorldContract physics classification binding is invalid")
    bodies = {item["object_id"]: item for item in classification["bodies"]}
    if set(bodies) != selected_ids:
        raise RuntimeError("physics body set does not match approved selection")

    instance_inputs = []
    relationships = []
    interactions = []
    normalization_records = []
    for object_id in sorted(selected_ids):
        mesh = meshes[object_id]
        mesh_path = Path(str(mesh.get("mesh_path", ""))).resolve()
        mesh_evidence = _mesh_evidence(mesh_path, require_uv=False)
        generator = str(mesh.get("generator", ""))
        if generator not in {"hunyuan3d_v2.1", "trellis2"}:
            raise RuntimeError(f"WorldContract rejects generator {generator!r}")
        if mesh_evidence["sha256"] != mesh.get("mesh_sha256"):
            raise RuntimeError(f"WorldContract mesh hash mismatch for {object_id}")
        normalization = dict(mesh.get("normalization", {}))
        source_path = Path(str(normalization.get("source_path", ""))).resolve()
        if (
            normalization.get("normalization_count") != 1
            or normalization.get("normalized_path") != str(mesh_path)
            or normalization.get("normalized_sha256") != mesh_evidence["sha256"]
            or normalization.get("origin_policy") != "local-bounds-bottom-center"
            or not source_path.is_file()
            or file_sha256(source_path) != normalization.get("source_sha256")
        ):
            raise RuntimeError(f"WorldContract normalization proof failed for {object_id}")
        normalization_records.append({"object_id": object_id, **normalization})
        material_data = materials[object_id]
        if material_data.get("mesh_sha256") != mesh_evidence["sha256"]:
            raise RuntimeError(f"material authority targets another mesh: {object_id}")
        material = MaterialIntent.from_dict(material_data["material_intent"])
        from src.unified_pipeline.mesh_shading import audit_glb_shading
        shading_audit = audit_glb_shading(
            mesh_path, expected_sha256=mesh_evidence["sha256"]
        )
        if (
            material.shading_model != shading_audit.shading_model
            or material.shading_provenance != shading_audit.provenance_sha256
        ):
            raise RuntimeError(f"material shading authority drift for {object_id}")
        selected_item = selected_by_id[object_id]
        body = bodies[object_id]
        transform = settled[object_id]
        is_dynamic = body["body_mode"] == "DYNAMIC"
        instance_inputs.append(InstanceAssemblyInput(
            object_id=object_id, name=str(selected_item["name"]),
            approved_asset=ApprovedAssetRecord(
                path=str(mesh_path), sha256=mesh_evidence["sha256"],
                triangle_count=int(mesh_evidence["face_count"]),
                vertex_count=int(mesh_evidence["vertex_count"]), generator=generator,
            ),
            physics_intent="dynamic" if is_dynamic else "static",
            material_intent=material,
            semantic_label=f"{selected_item['category']}/{selected_item['name']}",
            is_architectural=bool(
                placements_by_id[object_id].get("is_architectural", False)
            ),
            settled_position=(tuple(float(value) for value in transform["position"]) if is_dynamic else None),
            settled_rotation=(Quaternion(*map(float, transform["rotation"])) if is_dynamic else None),
        ))
        if is_dynamic:
            dimensions = [float(value) for value in transform["scale"]]
            interactions.append(InteractionBinding(
                interaction_id=str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"strict-real-dynamic-interaction/v1:{object_id}",
                )),
                object_id=object_id, kind="dynamic",
                collider=InteractionCollider(
                    center_offset=Vec3(0.0, dimensions[1] / 2.0, 0.0),
                    dimensions=Vec3(*dimensions),
                ),
                dynamic=DynamicInteractionMetadata(
                    mass_kg=float(body["mass_kg"]),
                    friction=float(body["friction"]),
                    restitution=float(body["restitution"]),
                    can_grab=True, can_push=True, can_topple=True,
                    grab_distance_m=3.0, hold_distance_m=1.5,
                    hold_stiffness=12.0,
                    push_impulse_ns=max(1.0, min(100.0, float(body["mass_kg"]) * 1.5)),
                    linear_damping=1.0, angular_damping=1.5,
                ),
            ))
        relationships.append(Relationship(object_id, "room", "containment"))

    relationships.extend(_plan_relationship_bindings(plan, selected_ids))
    normalization_document: dict[str, Any] = {
        "schema_version": "strict-real-mesh-normalization/v1",
        "selected_manifest_sha256": selected["manifest_sha256"],
        "records": normalization_records,
        "fallback_used": False,
    }
    normalization_document["document_sha256"] = _canonical_hash(normalization_document)
    _atomic_json(artifacts / "mesh_normalization.json", normalization_document)

    lighting = _canon_lighting(ctx, float(plan.room_dimensions[2]))
    assembled = WorldContractAssembler().assemble(
        plan, camera, room, tuple(instance_inputs),
        approved_plan_revision=plan.revisions[-1].revision,
        relationships=tuple(relationships), interactions=tuple(interactions),
        lighting=lighting, consumer_defaults=(),
    )
    contract = assembled.contract
    contract_ids = {item.object_id for item in contract.instances}
    if not contract_ids or contract_ids != selected_ids:
        raise RuntimeError("final WorldContract instance set differs from approved selection")
    if Path(contract.room_shell_ref).resolve() != Path(room.render_shell_path).resolve():
        raise RuntimeError("WorldContract does not bind the renderable room shell")

    for instance in contract.instances:
        expected = settled[instance.object_id]
        actual_position = [instance.position.x, instance.position.y, instance.position.z]
        actual_scale = [instance.scale.x, instance.scale.y, instance.scale.z]
        if any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(actual_position, expected["position"])):
            raise RuntimeError(f"contract transform drift for {instance.object_id}")
        if any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(actual_scale, expected["scale"])):
            raise RuntimeError(f"contract scale drift for {instance.object_id}")
        expected_architectural = bool(
            placements_by_id[instance.object_id].get("is_architectural", False)
        )
        if instance.is_architectural != expected_architectural:
            raise RuntimeError(f"contract architectural intent drift for {instance.object_id}")
        expected_intent = "dynamic" if bodies[instance.object_id]["body_mode"] == "DYNAMIC" else "static"
        if instance.physics_intent != expected_intent:
            raise RuntimeError(f"contract physics intent drift for {instance.object_id}")

    (artifacts / "world_contract.json").write_text(assembled.canonical_json, encoding="utf-8")
    graph_document = {
        "schema_version": "constrained-scene-graph/v1",
        "contract_hash": assembled.contract_hash,
        "plan_revision": assembled.scene_graph.plan_revision,
        "plan_hash": assembled.scene_graph.plan_hash,
        "camera_hash": assembled.scene_graph.camera_hash,
        "room_authority_hash": assembled.scene_graph.room_authority_hash,
        "room_shell_ref": contract.room_shell_ref,
        "instances": [item.to_dict() for item in assembled.scene_graph.instances],
        "relationships": [item.to_dict() for item in assembled.scene_graph.relationships],
        "interactions": [item.to_dict() for item in assembled.scene_graph.interactions],
        "lighting": assembled.scene_graph.lighting.to_dict(),
        "selected_manifest_sha256": selected["manifest_sha256"],
        "spatial_solution_sha256": spatial["solution_sha256"],
        "physics_settle_sha256": settle_hash,
        "mesh_normalization_sha256": normalization_document["document_sha256"],
        "stage_trace": list(assembled.stage_trace),
    }
    graph_document["document_sha256"] = _canonical_hash(graph_document)
    _atomic_json(artifacts / "scene_graph.json", graph_document)
    return StageResult(
        output={
            "status": "world_contract_finalized",
            "contract_hash": assembled.contract_hash,
            "instance_count": len(contract.instances),
            "dynamic_instance_count": len(interactions),
            "selected_manifest_sha256": selected["manifest_sha256"],
            "room_shell_sha256": room.render_shell_sha256,
            "scene_graph_path": str(artifacts / "scene_graph.json"),
            "stage_trace": list(assembled.stage_trace), "fallback_used": False,
        },
        plan_revision=ctx.plan_revision, approval_revision=ctx.approval_revision,
        canonical_hash=assembled.contract_hash,
    )


def handle_compile(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _legacy("_handle_compile", ctx)
    from src.unified_pipeline.compilers.browser import BrowserCompiler
    from src.unified_pipeline.world_contract import WorldContract

    artifacts = ctx.session_dir / "artifacts"
    contract = WorldContract.from_dict(json.loads(
        (artifacts / "world_contract.json").read_text(encoding="utf-8")
    ))
    output_dir = ctx.session_dir / "compiled" / "browser"
    result = BrowserCompiler().compile(
        contract, output_dir, require_renderable_room=True,
        require_real_instances=True,
    )
    return StageResult(
        output={
            "status": "compiled", "contract_hash": result.contract_hash,
            "browser": {
                "compiled": True, "contract_hash": result.contract_hash,
                "index_file": str(result.index_file),
                "scene_manifest_file": str(result.scene_manifest_file),
                "compiler_manifest_file": str(result.compiler_manifest_file),
                "artifact_paths": [str(path) for path in result.artifact_paths],
            },
            "godot": {
                "compiled": False, "contract_hash": result.contract_hash,
                "reason": "browser is the qualified strict-real target; Godot is not claimed",
            },
            "fallback_used": False,
        },
        plan_revision=ctx.plan_revision, approval_revision=ctx.approval_revision,
        canonical_hash=result.contract_hash,
    )


STRICT_REAL_HANDLERS: dict[str, Callable[[StageExecutionContext], Any]] = {
    "depth_estimation": handle_depth_estimation,
    "spatial_reconstruction": handle_spatial_reconstruction,
    "material_pass_1": handle_material_pass_1,
    "parametric_room": handle_parametric_room,
    "physics_classification": handle_physics_classification,
    "physics_settle": handle_physics_settle,
    "world_contract": handle_world_contract,
    "compile": handle_compile,
}


def _point_clear(point: Mapping[str, float], contract: Any, *, radius: float, height: float) -> bool:
    from src.unified_pipeline.compilers.browser import _body_aabb_half_extents

    navigation = contract.navigation
    if navigation is None:
        return False
    player_half = (radius, height / 2.0, radius)
    player_center = (
        float(point["x"]),
        float(point["y"]) - navigation.eye_height + player_half[1],
        float(point["z"]),
    )
    bounds_min = (
        navigation.bounds_minimum.x,
        navigation.bounds_minimum.y,
        navigation.bounds_minimum.z,
    )
    bounds_max = (
        navigation.bounds_maximum.x,
        navigation.bounds_maximum.y,
        navigation.bounds_maximum.z,
    )
    if any(
        player_center[index] - player_half[index] < bounds_min[index]
        or player_center[index] + player_half[index] > bounds_max[index]
        for index in range(3)
    ):
        return False
    for body in navigation.static_bodies:
        body_center = (body.center.x, body.center.y, body.center.z)
        body_half = _body_aabb_half_extents(body)
        if all(
            abs(player_center[index] - body_center[index])
            < player_half[index] + body_half[index] - 1e-9
            for index in range(3)
        ):
            return False
    return True


def handle_automated_final_validation(ctx: StageExecutionContext) -> StageResult:
    if not _strict(ctx):
        return _stage_result(ctx, {"status": "automated_final_validation_skipped", "strict_real": False})
    from src.unified_pipeline.world_contract import WorldContract, verify_hash

    artifacts = ctx.session_dir / "artifacts"
    compiled = ctx.session_dir / "compiled" / "browser"
    selected = load_selected_manifest(artifacts / "selected_objects.json")
    contract = WorldContract.from_dict(json.loads(
        (artifacts / "world_contract.json").read_text(encoding="utf-8")
    ))
    if not verify_hash(contract):
        raise RuntimeError("final validation rejects an invalid WorldContract hash")
    selected_ids = {
        str(item.get("plan_instance_id") or item["object_id"])
        for item in selected["objects"]
    }
    contract_ids = {item.object_id for item in contract.instances}
    if not selected_ids or contract_ids != selected_ids:
        raise RuntimeError("final selected-set equality check failed")

    room = Path(contract.room_shell_ref)
    room_evidence = json.loads((artifacts / "parametric_room.json").read_text(encoding="utf-8"))
    room_doc_hash = room_evidence.pop("document_sha256", "")
    if room_doc_hash != _canonical_hash(room_evidence):
        raise RuntimeError("final room evidence hash is invalid")
    if not room.is_file() or file_sha256(room) != room_evidence["mesh_evidence"]["sha256"]:
        raise RuntimeError("final renderable room shell does not match room evidence")

    normalization = json.loads((artifacts / "mesh_normalization.json").read_text(encoding="utf-8"))
    normalization_hash = normalization.pop("document_sha256", "")
    if normalization_hash != _canonical_hash(normalization):
        raise RuntimeError("final mesh normalization evidence hash is invalid")
    normalization_by_id = {
        item["object_id"]: item for item in normalization.get("records", [])
    }
    if set(normalization_by_id) != selected_ids:
        raise RuntimeError("final mesh normalization set differs from selection")
    for instance in contract.instances:
        mesh = Path(instance.asset_binding.mesh_path)
        evidence = normalization_by_id[instance.object_id]
        source = Path(str(evidence.get("source_path", "")))
        if (
            not mesh.is_file() or file_sha256(mesh) != instance.asset_binding.asset_id
            or evidence.get("normalized_sha256") != instance.asset_binding.asset_id
            or evidence.get("normalized_path") != str(mesh.resolve())
            or evidence.get("normalization_count") != 1
            or evidence.get("origin_policy") != "local-bounds-bottom-center"
            or not source.is_file() or file_sha256(source) != evidence.get("source_sha256")
            or "placeholder" in instance.asset_binding.generator.casefold()
            or instance.asset_binding.generator not in {"hunyuan3d_v2.1", "trellis2"}
        ):
            raise RuntimeError(f"final mesh provenance failed for {instance.object_id}")
    navigation = contract.navigation
    if navigation is None or not navigation.static_bodies or not navigation.spawn_candidates:
        raise RuntimeError("final navigation/collision authority is incomplete")
    static_instance_ids = {
        body.source_id for body in navigation.static_bodies if body.source_kind == "instance"
    }
    expected_static_ids = {
        item.object_id for item in contract.instances
        if item.physics_intent == "static" or item.is_architectural
    }
    dynamic_ids = {
        item.object_id for item in contract.instances
        if item.physics_intent == "dynamic" and not item.is_architectural
    }
    interaction_ids = {
        item.object_id for item in contract.interactions if item.kind == "dynamic"
    }
    if static_instance_ids != expected_static_ids or interaction_ids != dynamic_ids:
        raise RuntimeError("final static/dynamic collision and interaction sets are invalid")
    if contract.camera is None or contract.camera.compute_hash() != contract.camera_hash:
        raise RuntimeError("final camera hash binding failed")

    scene_path = compiled / "scene.json"
    compiler_manifest_path = compiled / "compiler_manifest.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    compiler_manifest = json.loads(compiler_manifest_path.read_text(encoding="utf-8"))
    if scene.get("contract_hash") != contract.contract_hash or compiler_manifest.get("contract_hash") != contract.contract_hash:
        raise RuntimeError("compiled render artifacts do not bind the final contract")
    room_asset = compiled / str(scene.get("room_asset_uri", ""))
    if not room_asset.is_file() or file_sha256(room_asset) != file_sha256(room):
        raise RuntimeError("compiled render room is missing or changed")
    scene_ids = {item.get("object_id") for item in scene.get("instances", [])}
    if scene_ids != selected_ids:
        raise RuntimeError("compiled scene instance set differs from selection")
    for item in scene["instances"]:
        if not (compiled / item["asset_uri"]).is_file():
            raise RuntimeError(f"compiled scene mesh is missing for {item['object_id']}")

    spawn = scene.get("selected_spawn")
    if not isinstance(spawn, dict) or not _point_clear(
        spawn, contract, radius=navigation.player_radius, height=navigation.player_height
    ):
        raise RuntimeError("compiled selected spawn is not collision-safe")
    movement_probe = None
    for dx, dz in ((0.25, 0.0), (-0.25, 0.0), (0.0, 0.25), (0.0, -0.25)):
        candidate = {"x": float(spawn["x"]) + dx, "y": float(spawn["y"]), "z": float(spawn["z"]) + dz}
        if _point_clear(candidate, contract, radius=navigation.player_radius, height=navigation.player_height):
            movement_probe = candidate
            break
    if movement_probe is None:
        raise RuntimeError("camera movement probe found no collision-safe adjacent position")

    provenance_files = (
        "depth_evidence.json", "spatial_solution.json", "selected_objects.json",
        "approved_metric_plan.json", "parametric_room.json",
        "mesh_normalization.json", "physics_classification.json",
        "physics_settle.json", "world_contract.json", "scene_graph.json",
    )
    provenance = {name: file_sha256(artifacts / name) for name in provenance_files}
    report: dict[str, Any] = {
        "schema_version": "strict-real-final-validation/v1",
        "contract_hash": contract.contract_hash,
        "selected_manifest_sha256": selected["manifest_sha256"],
        "selected_object_count": len(selected_ids),
        "room_shell_sha256": file_sha256(room),
        "camera_sha256": contract.camera_hash,
        "collision_body_count": len(navigation.static_bodies),
        "static_instance_count": len(expected_static_ids),
        "dynamic_instance_count": len(dynamic_ids),
        "mesh_normalization_sha256": normalization_hash,
        "selected_spawn": spawn, "movement_probe": movement_probe,
        "render_scene_sha256": file_sha256(scene_path),
        "compiler_manifest_sha256": file_sha256(compiler_manifest_path),
        "provenance_files": provenance,
        "checks": [
            "contract_hash", "selected_set_equality", "real_mesh_provenance",
            "mesh_normalization", "renderable_room", "compiled_asset_parity",
            "camera_hash", "physics_body_sets", "safe_spawn", "camera_movement",
        ],
        "passed": True, "fallback_used": False,
    }
    report["report_sha256"] = _canonical_hash(report)
    report_path = artifacts / "final_validation.json"
    _atomic_json(report_path, report)
    return StageResult(
        output={
            "status": "automated_final_validation_passed", "passed": True,
            "contract_hash": contract.contract_hash,
            "report_path": str(report_path), "report_sha256": report["report_sha256"],
            "check_count": len(report["checks"]), "fallback_used": False,
        },
        plan_revision=ctx.plan_revision, approval_revision=ctx.approval_revision,
        canonical_hash=report["report_sha256"],
    )


STRICT_REAL_HANDLERS["automated_final_validation"] = handle_automated_final_validation
