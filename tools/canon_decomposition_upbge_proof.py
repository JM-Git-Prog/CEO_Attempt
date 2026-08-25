"""Bounded Canon-decomposition plus deterministic Blender/UPBGE-compatible proof.

This diagnostic tool reuses the immutable Danny SAM3 workflow and existing empty-room
reference. It creates new deterministic geometry only; its outputs never replace
MetricPlan, CameraContract, or WorldContract authority and cannot manufacture human
approval, Demo Ready, qualification, or release evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / ".kiro" / "specs" / "unified-world-pipeline"
EVIDENCE_DIR = SPEC_DIR / "evidence"
CANON_PATH = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
RENDER_ROOT = CANON_PATH.parent
SHARED_CANON_PATH = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
ITEMS_API_PATH = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.api.json")
ITEMS_UI_PATH = ITEMS_API_PATH.with_name("danny-v4.1-items.ui.json")
APP_WORKFLOW_PATH = Path(r"C:\Users\JohnM\ComfyUI-Installs\ComfyUI\ComfyUI\user\default\workflows\danny-v4-pipeline-app.app.json")
QA_REPORT_PATH = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\danny-v4-pipeline-QA-report.md")
EMPTY_TWIN_PATH = RENDER_ROOT / "danny-v4-02-twin_00002_.png"
BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
COMFY_URL = "http://127.0.0.1:8188"
RECLINER_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
REJECTED_GLB_SHA256 = "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf"
REJECTED_GLB_PATH = EVIDENCE_DIR / "task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002" / "recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
REJECTION_RECORD_PATH = EVIDENCE_DIR / "task-11.8.4a-human-rejection-revocation-blocker-13500f5f-04dc-4085-a6c4-6407f69bf3b1.json"
NO_PASS_RECORD_PATH = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
UUID_NAMESPACE = uuid.UUID("93e6ca0f-056a-54b7-a47e-6863a4b3a242")

EXPECTED_HASHES = {
    CANON_PATH: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    SHARED_CANON_PATH: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    ITEMS_API_PATH: "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
    ITEMS_UI_PATH: "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    APP_WORKFLOW_PATH: "c903d91563056fe139091396572ffdfca84718c10eaa6f4ed63150b8bd0f4ef7",
    QA_REPORT_PATH: "ca442223247d66ae14c0fd3d65b6147a4b1997c7034219b68c437eed96ef7076",
    REJECTED_GLB_PATH: REJECTED_GLB_SHA256,
    REJECTION_RECORD_PATH: "34f39460cadf4a8c74c1b6f57d8f80b54ea0adced12a2ea2e20d8afc129e56e2",
    NO_PASS_RECORD_PATH: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
}

ITEM_PREFIXES = {
    "bookshelf": "danny-v4.1-item-bookshelf",
    "foreground_sofa": "danny-v4.1-item-couch",
    "ceiling_fan": "danny-v4.1-item-fan",
    "refrigerator": "danny-v4.1-item-fridge",
    "table_lamp": "danny-v4.1-item-lamp",
    "wall_mirror": "danny-v4.1-item-mirror",
    "paintings": "danny-v4.1-item-paintings",
    "phone_side_table": "danny-v4.1-item-phone-table",
    "recliner": "danny-v4.1-item-recliner",
    "area_rug": "danny-v4.1-item-rug",
    "trophy_shelf": "danny-v4.1-item-trophy-shelf",
    "crt_television": "danny-v4.1-item-tv-set",
    "wooden_tv_stand": "danny-v4.1-item-tv-stand",
}

# Dimensions are bounded appearance estimates only, never MetricPlan authority.
ITEM_SPECS: dict[str, dict[str, Any]] = {
    "ceiling_fan": dict(label="ceiling fan", geometry="radial_fixture", components=["hub", "downrod", "four blades", "light housing"], size=[[1.0, 1.6], [1.0, 1.6], [0.35, 0.7]], cues=["dark bronze", "warm wood blades"], placement=[0.50, 0.38, 0.94], orientation=[-10, 10], occlusion="low", confidence=0.96, relations=["ceiling-mounted", "above room center"]),
    "paintings": dict(label="paintings", geometry="framed_wall_art_set", components=["individual frames", "image planes"], size=[[1.3, 2.4], [0.03, 0.10], [0.55, 1.1]], cues=["dark wood frames", "warm multicolor art"], placement=[0.35, 0.72, 0.68], orientation=[-5, 5], occlusion="low", confidence=0.94, relations=["mounted on rear/left wall", "above furniture line"]),
    "trophy_shelf": dict(label="trophy shelf", geometry="wall_shelf_display", components=["shelf boards", "brackets", "display backing"], size=[[1.4, 2.4], [0.25, 0.5], [0.8, 1.5]], cues=["dark stained wood", "brass highlights"], placement=[0.36, 0.80, 0.63], orientation=[-5, 5], occlusion="medium", confidence=0.91, relations=["supports trophies", "against rear wall"]),
    "trophies": dict(label="trophies", geometry="small_display_objects", components=["cups", "stems", "bases"], size=[[0.08, 0.35], [0.08, 0.25], [0.18, 0.55]], cues=["brass/gold metal", "dark bases"], placement=[0.36, 0.80, 0.72], orientation=[-30, 30], occlusion="medium", confidence=0.86, relations=["on trophy shelf", "grouped display"]),
    "wall_mirror": dict(label="wall mirror", geometry="framed_reflective_plane", components=["frame", "reflective panel"], size=[[0.7, 1.2], [0.03, 0.12], [1.0, 1.8]], cues=["dark wood frame", "cool reflective glass"], placement=[0.73, 0.73, 0.63], orientation=[-10, 10], occlusion="low", confidence=0.95, relations=["wall-mounted", "near refrigerator"]),
    "refrigerator": dict(label="refrigerator", geometry="upright_appliance", components=["cabinet", "upper door", "lower door", "handles"], size=[[0.75, 1.0], [0.65, 0.9], [1.65, 2.05]], cues=["cream/off-white enamel", "dark handles"], placement=[0.69, 0.77, 0.25], orientation=[-10, 10], occlusion="low", confidence=0.97, relations=["floor-standing", "against rear-right wall"]),
    "area_rug": dict(label="area rug", geometry="thin_rectangular_textile", components=["rug body", "border", "pattern bands"], size=[[2.1, 3.6], [3.0, 5.2], [0.01, 0.04]], cues=["muted red", "tan geometric pattern"], placement=[0.50, 0.57, 0.01], orientation=[-8, 8], occlusion="high", confidence=0.91, relations=["on floor", "beneath seating area"]),
    "recliner": dict(label="recliner", geometry="articulated_upholstered_chair", components=["back", "upper/lower back cushions", "seat", "left arm", "right arm", "base", "footrest", "seams"], size=[[0.85, 1.15], [0.9, 1.55], [1.05, 1.35]], cues=["deep burgundy leather", "dark seam piping", "dark base"], placement=[0.37, 0.57, 0.16], orientation=[5, 25], occlusion="medium", confidence=0.98, relations=["on area rug", "faces CRT television", "left of phone side table"]),
    "phone_side_table": dict(label="telephone side table", geometry="small_wood_side_table", components=["top", "apron", "four legs", "lower shelf"], size=[[0.4, 0.7], [0.4, 0.7], [0.5, 0.75]], cues=["dark stained wood"], placement=[0.54, 0.57, 0.13], orientation=[-10, 10], occlusion="medium", confidence=0.92, relations=["supports telephone", "beside recliner"]),
    "telephone": dict(label="corded telephone", geometry="small_desktop_device", components=["base", "handset", "dial/keypad", "cord"], size=[[0.18, 0.35], [0.15, 0.3], [0.08, 0.2]], cues=["dark brown/black plastic"], placement=[0.54, 0.57, 0.28], orientation=[-25, 25], occlusion="medium", confidence=0.84, relations=["on phone side table", "beside recliner"]),
    "crt_television": dict(label="CRT television", geometry="box_cathode_ray_television", components=["cabinet", "curved screen", "bezel", "controls"], size=[[0.65, 1.0], [0.5, 0.8], [0.55, 0.85]], cues=["dark charcoal cabinet", "desaturated glass screen"], placement=[0.79, 0.58, 0.37], orientation=[-20, 0], occlusion="low", confidence=0.97, relations=["on wooden TV stand", "faces recliner"]),
    "wooden_tv_stand": dict(label="wooden TV stand", geometry="low_media_cabinet", components=["top", "cabinet", "doors/drawers", "feet"], size=[[0.9, 1.5], [0.45, 0.8], [0.5, 0.8]], cues=["medium/dark stained wood"], placement=[0.79, 0.58, 0.15], orientation=[-20, 0], occlusion="medium", confidence=0.96, relations=["supports CRT television", "against right wall"]),
    "bookshelf": dict(label="bookshelf", geometry="tall_open_shelving", components=["side panels", "shelves", "back", "books"], size=[[0.7, 1.2], [0.25, 0.5], [1.4, 2.1]], cues=["dark stained wood", "multicolor book spines"], placement=[0.88, 0.72, 0.28], orientation=[-15, 0], occlusion="medium", confidence=0.93, relations=["against right wall", "near television"]),
    "table_lamp": dict(label="table lamp", geometry="portable_luminaire", components=["base", "stem", "shade", "bulb glow"], size=[[0.25, 0.55], [0.25, 0.55], [0.55, 1.0]], cues=["warm cream shade", "dark base", "warm light"], placement=[0.61, 0.53, 0.40], orientation=[-15, 15], occlusion="medium", confidence=0.92, relations=["on side surface", "casts warm local light"]),
    "foreground_sofa": dict(label="foreground sofa", geometry="upholstered_sofa", components=["seat cushions", "back cushions", "arms", "base"], size=[[1.8, 2.8], [0.8, 1.2], [0.75, 1.1]], cues=["deep brown/burgundy upholstery"], placement=[0.18, 0.23, 0.17], orientation=[-10, 10], occlusion="high/cropped", confidence=0.90, relations=["foreground left", "partially outside Canon frame"]),
}

REQUIRED_COMPONENTS = {
    "recliner_root",
    "base",
    "seat_frame",
    "seat_cushion",
    "left_arm",
    "right_arm",
    "back_frame",
    "back_cushion_lower",
    "back_cushion_upper",
    "footrest_frame",
    "footrest_cushion",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def stable_uuid(key: str) -> str:
    if key == "recliner":
        return RECLINER_UUID
    return str(uuid.uuid5(UUID_NAMESPACE, f"{EXPECTED_HASHES[CANON_PATH]}:{key}"))


def hash_binding(path: Path, expected: str | None = None) -> dict[str, Any]:
    exists = path.is_file()
    observed = sha256_file(path) if exists else None
    return {
        "path": str(path),
        "exists": exists,
        "sha256_expected": expected,
        "sha256_observed": observed,
        "verified": exists and (expected is None or observed == expected),
    }


def verify_immutable_inputs() -> list[dict[str, Any]]:
    bindings = [hash_binding(path, expected) for path, expected in EXPECTED_HASHES.items()]
    failures = [binding for binding in bindings if not binding["verified"]]
    if failures:
        raise RuntimeError(f"Immutable input verification failed: {failures}")
    return bindings


def fetch_json(path: str, *, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{COMFY_URL}{path}", data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def discover_cutouts() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key, prefix in ITEM_PREFIXES.items():
        pattern = re.compile(re.escape(prefix) + r"_\d{5}_\.png$")
        candidates = [path for path in RENDER_ROOT.glob(prefix + "_*.png") if pattern.fullmatch(path.name)]
        if not candidates:
            raise FileNotFoundError(f"No exact cutout output for {prefix}")
        result[key] = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return result


def run_exact_item_workflow(refresh: bool, timeout_seconds: int) -> tuple[dict[str, Any], dict[str, Path]]:
    prior = discover_cutouts()
    status: dict[str, Any] = {
        "requested": refresh,
        "endpoint": COMFY_URL,
        "workflow_path": str(ITEMS_API_PATH),
        "workflow_sha256": sha256_file(ITEMS_API_PATH),
        "source_load_image": "danny-v4-01-canon_00002_.png [output]",
        "source_hash_verified": sha256_file(CANON_PATH) == EXPECTED_HASHES[CANON_PATH],
        "prior_cutouts": {key: str(path) for key, path in prior.items()},
    }
    try:
        stats = fetch_json("/system_stats")
        object_info = fetch_json("/object_info", timeout=30)
        queue = fetch_json("/queue")
        workflow = json.loads(ITEMS_API_PATH.read_text(encoding="utf-8"))
        node_types = sorted({node.get("class_type") for node in workflow.values()})
        missing = [name for name in node_types if name not in object_info]
        status.update({
            "available": True,
            "comfyui_version": stats.get("system", {}).get("comfyui_version"),
            "required_node_types": node_types,
            "missing_node_types": missing,
            "queue_running_before": len(queue.get("queue_running", [])),
            "queue_pending_before": len(queue.get("queue_pending", [])),
        })
        if missing:
            raise RuntimeError(f"Comfy workflow node types unavailable: {missing}")
        if not refresh:
            status.update({"execution": "VERIFIED_EXISTING_OUTPUTS_REUSED", "fallback": False})
            return status, prior
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise RuntimeError("Comfy queue was not idle; refusing to interfere with existing work")
        client_id = f"task-11.8.4b-{uuid.uuid4()}"
        response = fetch_json("/prompt", payload={"prompt": workflow, "client_id": client_id}, timeout=30)
        prompt_id = response["prompt_id"]
        deadline = time.monotonic() + timeout_seconds
        history_entry: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            history = fetch_json(f"/history/{prompt_id}", timeout=30)
            if prompt_id in history:
                history_entry = history[prompt_id]
                break
            time.sleep(2)
        if history_entry is None:
            raise TimeoutError(f"Comfy workflow did not finish within {timeout_seconds}s")
        workflow_status = history_entry.get("status", {})
        if workflow_status.get("status_str") == "error":
            raise RuntimeError(f"Comfy workflow error: {workflow_status}")
        outputs: list[str] = []
        for output in history_entry.get("outputs", {}).values():
            for image in output.get("images", []):
                outputs.append(str(RENDER_ROOT / image.get("subfolder", "") / image["filename"]))
        refreshed = discover_cutouts()
        changed = {key: refreshed[key] != prior[key] for key in ITEM_PREFIXES}
        status.update({
            "execution": "EXACT_IMMUTABLE_API_WORKFLOW_COMPLETED",
            "fallback": False,
            "prompt_id": prompt_id,
            "client_id": client_id,
            "history_status": workflow_status,
            "reported_outputs": sorted(outputs),
            "all_13_cutouts_refreshed": all(changed.values()),
            "cutout_path_changes": changed,
        })
        return status, refreshed
    except (URLError, OSError, KeyError, RuntimeError, TimeoutError, ValueError) as exc:
        existing = discover_cutouts()
        status.update({
            "available": status.get("available", False),
            "execution": "VERIFIED_EXISTING_OUTPUT_FALLBACK",
            "fallback": True,
            "fallback_reason": f"{type(exc).__name__}: {exc}",
        })
        return status, existing


def image_alpha_profile(path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        bands = image.getbands()
        if "A" not in bands:
            raise AssertionError(f"Cutout lacks alpha channel: {path}")
        alpha = image.getchannel("A")
        extrema = alpha.getextrema()
        return {
            "mode": image.mode,
            "size_px": list(image.size),
            "alpha_extrema": list(extrema),
            "alpha_bbox_px": list(alpha.getbbox() or (0, 0, 0, 0)),
            "alpha_mask_nonempty": extrema[1] > 0,
            "alpha_mask_has_transparency": extrema[0] < 255,
        }


def build_item_record(key: str, cutouts: dict[str, Path]) -> dict[str, Any]:
    source_key = key
    compound_note = None
    if key == "trophies":
        source_key = "trophy_shelf"
        compound_note = "Trophies share the trophy-shelf RGBA extraction and require component-level separation downstream."
    elif key == "telephone":
        source_key = "phone_side_table"
        compound_note = "Telephone shares the phone-table RGBA extraction and requires component-level separation downstream."
    source = cutouts[source_key]
    spec = ITEM_SPECS[key]
    return {
        "key": key,
        "label": spec["label"],
        "stable_uuid": stable_uuid(key),
        "source_mask_or_cutout": {
            "path": str(source),
            "sha256": sha256_file(source),
            "kind": "rgba_cutout_with_alpha_mask",
            "alpha_profile": image_alpha_profile(source),
            "workflow_path": str(ITEMS_API_PATH),
            "workflow_sha256": EXPECTED_HASHES[ITEMS_API_PATH],
            "compound_source_note": compound_note,
        },
        "prompts": {
            "positive": {
                "identity": spec["label"],
                "geometry": ", ".join(spec["components"]),
                "materials_and_color": ", ".join(spec["cues"]),
                "preservation": "Preserve the locked Canon silhouette, visible proportions, count, and orientation cues.",
            },
            "negative": [
                "no fused room or floor geometry",
                "no duplicated components",
                "no melted, inflated, or blob-like silhouette",
                "no invented occluded detail treated as authority",
                "no camera or placement inference promoted to spatial authority",
            ],
        },
        "geometry_class": spec["geometry"],
        "component_breakdown": spec["components"],
        "estimated_size_range_m": {
            "width": spec["size"][0],
            "depth": spec["size"][1],
            "height": spec["size"][2],
            "authority": "appearance_estimate_only",
        },
        "material_color_cues": spec["cues"],
        "relative_pose_estimate": {
            "canon_normalized_xyz": spec["placement"],
            "yaw_degrees_range": spec["orientation"],
            "authority": "reference_only_pending_MetricPlan_and_CameraContract",
        },
        "occlusion": spec["occlusion"],
        "confidence": spec["confidence"],
        "spatial_relationships": spec["relations"],
        "authority": "appearance_evidence_only_not_spatial_authority",
    }


def create_texture_tiles(output_dir: Path) -> dict[str, Path]:
    from PIL import Image, ImageDraw

    texture_dir = output_dir / "textures"
    texture_dir.mkdir(parents=True, exist_ok=False)
    definitions = {
        "leather": ((92, 26, 30), (119, 43, 45)),
        "leather_edge": ((36, 16, 17), (58, 24, 25)),
        "dark_base": ((29, 25, 24), (48, 40, 37)),
        "wood": ((82, 46, 25), (124, 76, 40)),
        "cream": ((203, 185, 151), (230, 215, 183)),
        "floor": ((104, 61, 32), (154, 95, 50)),
        "trim": ((55, 34, 23), (88, 52, 29)),
    }
    paths: dict[str, Path] = {}
    for name, (base, accent) in definitions.items():
        image = Image.new("RGB", (32, 32), base)
        draw = ImageDraw.Draw(image)
        for y in range(0, 32, 4):
            draw.line((0, y, 31, y), fill=accent, width=1)
        for x in range(2, 32, 8):
            draw.point((x, (x * 7) % 32), fill=accent)
        path = texture_dir / f"{name}.png"
        image.save(path, optimize=True)
        paths[name] = path
    return paths


def build_worker_config(output_dir: Path, textures: dict[str, Path]) -> Path:
    config = {
        "output_dir": str(output_dir),
        "textures": {name: str(path) for name, path in textures.items()},
        "recliner_uuid": RECLINER_UUID,
    }
    path = output_dir / "blender-worker-config.json"
    write_json(path, config)
    return path


def run_blender_worker(config_path: Path) -> dict[str, Any]:
    command = [
        str(BLENDER_EXE),
        "--background",
        "--factory-startup",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        str(config_path),
    ]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    expected_outputs = [
        config_path.parent / "deterministic-recliner.glb",
        config_path.parent / "deterministic-empty-room-shell.glb",
        config_path.parent / "recliner-front.png",
        config_path.parent / "recliner-right.png",
        config_path.parent / "recliner-rear.png",
        config_path.parent / "recliner-left.png",
        config_path.parent / "deterministic-shell-recliner-canon-camera.png",
        config_path.parent / "deterministic-shell-recliner-proof.blend",
    ]
    missing_outputs = [str(path) for path in expected_outputs if not path.is_file()]
    python_traceback = "Traceback (most recent call last)" in result.stdout or "Traceback (most recent call last)" in result.stderr
    record = {
        "command": command,
        "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": result.stdout[-8000:],
        "stderr_tail": result.stderr[-8000:],
        "python_traceback_detected": python_traceback,
        "missing_expected_outputs": missing_outputs,
    }
    if result.returncode != 0 or python_traceback or missing_outputs:
        raise RuntimeError(f"Blender worker failed: {record}")
    return record


def inspect_glb(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) < 20:
        raise AssertionError(f"GLB too short: {path}")
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(payload):
        raise AssertionError(f"Invalid GLB 2.0 container: {path}")
    offset = 12
    document: dict[str, Any] | None = None
    binary_length = 0
    while offset < len(payload):
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        chunk = payload[offset + 8 : offset + 8 + chunk_length]
        offset += 8 + chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif chunk_type == 0x004E4942:
            binary_length = chunk_length
    if document is None or binary_length <= 0:
        raise AssertionError(f"Missing GLB JSON or BIN chunk: {path}")
    buffers = document.get("buffers", [])
    images = document.get("images", [])
    buffer_views = document.get("bufferViews", [])
    external_buffers = [entry["uri"] for entry in buffers if entry.get("uri")]
    external_images = [entry["uri"] for entry in images if entry.get("uri") and not entry["uri"].startswith("data:")]
    in_bounds = all(int(view.get("byteOffset", 0)) + int(view["byteLength"]) <= binary_length for view in buffer_views)
    embedded_images = sum(1 for entry in images if "bufferView" in entry or entry.get("uri", "").startswith("data:"))
    node_names = {entry.get("name", "") for entry in document.get("nodes", [])}
    mesh_names = {entry.get("name", "") for entry in document.get("meshes", [])}
    primitive_count = sum(len(mesh.get("primitives", [])) for mesh in document.get("meshes", []))
    try:
        import trimesh

        scene = trimesh.load(path, force="scene", process=False)
        trimesh_geometry_count = len(scene.geometry)
        independently_loaded = trimesh_geometry_count > 0
    except Exception as exc:  # pragma: no cover - emitted into evidence
        trimesh_geometry_count = 0
        independently_loaded = False
        load_error = f"{type(exc).__name__}: {exc}"
    else:
        load_error = None
    return {
        "container": "GLB_2_0",
        "declared_bytes": declared_length,
        "actual_bytes": len(payload),
        "binary_chunk_bytes": binary_length,
        "buffer_views_in_bounds": in_bounds,
        "node_names": sorted(node_names),
        "mesh_names": sorted(mesh_names),
        "node_count": len(document.get("nodes", [])),
        "mesh_count": len(document.get("meshes", [])),
        "primitive_count": primitive_count,
        "material_count": len(document.get("materials", [])),
        "texture_count": len(document.get("textures", [])),
        "image_count": len(images),
        "embedded_image_count": embedded_images,
        "external_buffer_uris": external_buffers,
        "external_image_uris": external_images,
        "trimesh_geometry_count": trimesh_geometry_count,
        "independently_loaded": independently_loaded,
        "load_error": load_error,
    }


def combine_contact_sheet(canon: Path, empty_twin: Path, assembly: Path, destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    panel_size = (640, 360)
    header = 58
    footer = 52
    sheet = Image.new("RGB", (panel_size[0] * 3, header + panel_size[1] + footer), (25, 23, 21))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=19)
    small = ImageFont.load_default(size=15)
    draw.text((20, 16), "Task 11.8.4b — locked Canon / existing empty twin / deterministic shell + recliner", fill=(240, 232, 213), font=font)
    for index, (path, title) in enumerate(((canon, "LOCKED CANON"), (empty_twin, "EXISTING QWEN EMPTY-TWIN REFERENCE"), (assembly, "DETERMINISTIC PROOF ASSEMBLY"))):
        with Image.open(path) as source:
            panel = ImageOps.fit(source.convert("RGB"), panel_size, method=Image.Resampling.LANCZOS)
        x = panel_size[0] * index
        sheet.paste(panel, (x, header))
        draw.rectangle((x, header, x + panel_size[0] - 1, header + panel_size[1] - 1), outline=(225, 196, 129), width=2)
        draw.rectangle((x + 8, header + 8, x + 330, header + 36), fill=(20, 20, 20))
        draw.text((x + 16, header + 13), title, fill=(255, 235, 180), font=small)
    draw.text((20, header + panel_size[1] + 15), "Reference-only appearance proof. MetricPlan = spatial authority; CameraContract = camera authority; WorldContract = final binding authority.", fill=(231, 217, 190), font=small)
    sheet.save(destination, optimize=True)


def combine_multiangle(output_dir: Path, destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    views = [("front", "FRONT"), ("right", "RIGHT"), ("rear", "REAR"), ("left", "LEFT")]
    panel = 512
    header = 58
    footer = 48
    sheet = Image.new("RGB", (panel * 2, header + panel * 2 + footer), (28, 27, 26))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=19)
    small = ImageFont.load_default(size=16)
    draw.text((20, 16), "New deterministic recliner — separate procedural components", fill=(240, 232, 213), font=font)
    for index, (slug, title) in enumerate(views):
        with Image.open(output_dir / f"recliner-{slug}.png") as source:
            fitted = ImageOps.fit(source.convert("RGB"), (panel, panel), method=Image.Resampling.LANCZOS)
        x = (index % 2) * panel
        y = header + (index // 2) * panel
        sheet.paste(fitted, (x, y))
        draw.rectangle((x, y, x + panel - 1, y + panel - 1), outline=(220, 183, 110), width=2)
        draw.rectangle((x + 10, y + 10, x + 130, y + 42), fill=(22, 20, 18))
        draw.text((x + 20, y + 17), title, fill=(255, 235, 180), font=small)
    draw.text((20, header + panel * 2 + 14), f"Recliner UUID {RECLINER_UUID} — human visual approval is not inferred.", fill=(231, 217, 190), font=small)
    sheet.save(destination, optimize=True)


def build_pack(cutouts: dict[str, Path], comfy: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    items = [build_item_record(key, cutouts) for key in ITEM_SPECS]
    return {
        "schema": "unified-world-pipeline.canon-decomposition-pack.v1",
        "pack_id": str(uuid.uuid4()),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": "DIAGNOSTIC_TASK_11_8_4B_NON_QUALIFYING",
        "source": {
            "locked_canon": hash_binding(CANON_PATH, EXPECTED_HASHES[CANON_PATH]),
            "sam3_items_api_workflow": hash_binding(ITEMS_API_PATH, EXPECTED_HASHES[ITEMS_API_PATH]),
            "sam3_items_ui_workflow": hash_binding(ITEMS_UI_PATH, EXPECTED_HASHES[ITEMS_UI_PATH]),
            "empty_twin_app_workflow": hash_binding(APP_WORKFLOW_PATH, EXPECTED_HASHES[APP_WORKFLOW_PATH]),
            "empty_twin_qa_report": hash_binding(QA_REPORT_PATH, EXPECTED_HASHES[QA_REPORT_PATH]),
            "existing_empty_twin": hash_binding(EMPTY_TWIN_PATH),
            "comfy_execution": comfy,
        },
        "authority_contract": {
            "generated_references_are_spatial_authority": False,
            "metric_plan": "sole dimensions/transforms/placement/architecture/openings/collision/navigation authority",
            "camera_contract": "sole Plan-derived camera authority",
            "world_contract": "final object/relationship/binding authority",
            "pack_role": "appearance, decomposition, and deterministic reconstruction candidate evidence only",
        },
        "room_shell": {
            "stable_uuid": stable_uuid("room_shell"),
            "geometry_class": "long_rectangular_interior_shell",
            "appearance_estimate_m": {"width": [8.0, 11.0], "length": [11.0, 16.0], "height": [3.5, 5.5]},
            "materials": ["warm wood plank floor", "cream plaster walls", "dark wood opening trim"],
            "architectural_features": [
                {"key": "rear_door", "uuid": stable_uuid("rear_door"), "source": "locked Canon", "relationship": "rear wall opening"},
                {"key": "right_door", "uuid": stable_uuid("right_door"), "source": "locked Canon", "relationship": "right wall opening"},
                {"key": "right_window", "uuid": stable_uuid("right_window"), "source": "locked Canon", "relationship": "street-facing right wall opening"},
            ],
            "empty_twin_reference": str(EMPTY_TWIN_PATH),
            "deterministic_glb": str(output_dir / "deterministic-empty-room-shell.glb"),
            "authority": "appearance_estimate_only_pending_MetricPlan",
        },
        "camera_estimate": {
            "projection": "perspective",
            "source_resolution_px": [1536, 864],
            "estimated_focal_length_mm": [28, 42],
            "estimated_horizontal_fov_degrees": [45, 65],
            "estimated_pose": {"position_room_fraction": [0.50, -0.08, 0.60], "target_room_fraction": [0.50, 0.70, 0.35], "roll_degrees": [-1, 1]},
            "confidence": 0.62,
            "authority": "reference_only; immutable Plan-derived CameraContract remains authoritative",
        },
        "items": items,
        "inventory": {
            "item_count": len(items),
            "keys": [item["key"] for item in items],
            "all_clearly_visible_inventory_represented": True,
            "compound_cutout_components": ["trophies", "telephone"],
        },
        "deterministic_reconstruction": {
            "recliner_uuid": RECLINER_UUID,
            "recliner_glb": str(output_dir / "deterministic-recliner.glb"),
            "shell_glb": str(output_dir / "deterministic-empty-room-shell.glb"),
            "required_separate_components": sorted(REQUIRED_COMPONENTS),
            "rejected_glb_sha256": REJECTED_GLB_SHA256,
            "rejected_geometry_reused_modified_smoothed_or_rerendered": False,
        },
    }


def validate_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    required_item_fields = {
        "key", "label", "stable_uuid", "source_mask_or_cutout", "prompts", "geometry_class",
        "component_breakdown", "estimated_size_range_m", "material_color_cues", "relative_pose_estimate",
        "occlusion", "confidence", "spatial_relationships", "authority",
    }
    checks: list[dict[str, Any]] = []
    items = pack.get("items", [])
    item_keys = {item.get("key") for item in items}
    checks.append({"check": "schema", "pass": pack.get("schema") == "unified-world-pipeline.canon-decomposition-pack.v1"})
    checks.append({"check": "complete_visible_inventory", "pass": item_keys == set(ITEM_SPECS)})
    checks.append({"check": "item_required_fields", "pass": all(required_item_fields <= set(item) for item in items)})
    checks.append({"check": "stable_unique_uuids", "pass": len({item["stable_uuid"] for item in items}) == len(items) and next(item for item in items if item["key"] == "recliner")["stable_uuid"] == RECLINER_UUID})
    checks.append({"check": "hash_bound_alpha_cutouts", "pass": all(Path(item["source_mask_or_cutout"]["path"]).is_file() and sha256_file(Path(item["source_mask_or_cutout"]["path"])) == item["source_mask_or_cutout"]["sha256"] and item["source_mask_or_cutout"]["alpha_profile"]["alpha_mask_nonempty"] for item in items)})
    checks.append({"check": "authority_boundaries", "pass": pack.get("authority_contract", {}).get("generated_references_are_spatial_authority") is False and "sole" in pack.get("authority_contract", {}).get("metric_plan", "")})
    return checks


def artifact_binding(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def build_evidence(output_dir: Path, pack: dict[str, Any], comfy: dict[str, Any], immutable_bindings: list[dict[str, Any]], blender: dict[str, Any]) -> dict[str, Any]:
    pack_path = output_dir / "canon-decomposition-pack.json"
    recliner_path = output_dir / "deterministic-recliner.glb"
    shell_path = output_dir / "deterministic-empty-room-shell.glb"
    contact_path = output_dir / "canon-camera-comparison-contact-sheet.png"
    multiangle_path = output_dir / "recliner-neutral-multi-angle-sheet.png"
    recliner_inspection = inspect_glb(recliner_path)
    shell_inspection = inspect_glb(shell_path)
    pack_checks = validate_pack(pack)
    recliner_nodes = set(recliner_inspection["node_names"]) | set(recliner_inspection["mesh_names"])
    non_human_checks = pack_checks + [
        {"check": "immutable_source_hashes", "pass": all(binding["verified"] for binding in immutable_bindings)},
        {"check": "exact_sam3_workflow_or_verified_fallback", "pass": comfy.get("execution") in {"EXACT_IMMUTABLE_API_WORKFLOW_COMPLETED", "VERIFIED_EXISTING_OUTPUTS_REUSED", "VERIFIED_EXISTING_OUTPUT_FALLBACK"}},
        {"check": "recliner_independent_load", "pass": recliner_inspection["independently_loaded"] and recliner_inspection["mesh_count"] >= 10},
        {"check": "separate_recliner_components", "pass": all(any(required in name for name in recliner_nodes) for required in REQUIRED_COMPONENTS - {"recliner_root"}) and recliner_inspection["mesh_count"] >= 10},
        {"check": "embedded_durable_recliner_materials", "pass": recliner_inspection["material_count"] >= 3 and recliner_inspection["texture_count"] >= 3 and recliner_inspection["embedded_image_count"] >= 3},
        {"check": "recliner_no_external_uris", "pass": not recliner_inspection["external_buffer_uris"] and not recliner_inspection["external_image_uris"] and recliner_inspection["buffer_views_in_bounds"]},
        {"check": "shell_independent_load", "pass": shell_inspection["independently_loaded"] and shell_inspection["mesh_count"] >= 8},
        {"check": "shell_embedded_materials_no_external_uris", "pass": shell_inspection["material_count"] >= 3 and shell_inspection["embedded_image_count"] >= 3 and not shell_inspection["external_buffer_uris"] and not shell_inspection["external_image_uris"]},
        {"check": "new_geometry_distinct_from_rejected_glb", "pass": sha256_file(recliner_path) != REJECTED_GLB_SHA256 and sha256_file(REJECTED_GLB_PATH) == REJECTED_GLB_SHA256},
        {"check": "two_review_pngs", "pass": contact_path.is_file() and multiangle_path.is_file() and contact_path.stat().st_size > 10000 and multiangle_path.stat().st_size > 10000},
        {"check": "camera_and_authority_bindings", "pass": pack["camera_estimate"]["authority"].startswith("reference_only") and pack["authority_contract"]["generated_references_are_spatial_authority"] is False},
    ]
    failed = [check["check"] for check in non_human_checks if not check["pass"]]
    status = "AWAITING_EXPLICIT_HUMAN_REVIEW" if not failed else "FAIL_CLOSED_NON_HUMAN_VALIDATION"
    output_bindings = {
        "canon_decomposition_pack": artifact_binding(pack_path),
        "deterministic_recliner_glb": artifact_binding(recliner_path),
        "deterministic_empty_room_shell_glb": artifact_binding(shell_path),
        "canon_camera_comparison_contact_sheet": artifact_binding(contact_path),
        "recliner_neutral_multi_angle_sheet": artifact_binding(multiangle_path),
    }
    fingerprint_payload = json.dumps({key: value["sha256"] for key, value in output_bindings.items()}, sort_keys=True).encode("utf-8")
    return {
        "schema": "unified-world-pipeline.task-11.8.4b.canon-decomposition-deterministic-proof.v1",
        "task": "11.8.4b",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "result": status,
        "scope": "Diagnostic Canon-decomposition plus deterministic shell/recliner proof only; no Task 11.8.5 work, session, qualification, Demo Ready, release, or interface change.",
        "candidate_fingerprint": hashlib.sha256(fingerprint_payload).hexdigest(),
        "recliner_uuid": RECLINER_UUID,
        "comfy_execution": comfy,
        "immutable_input_bindings": immutable_bindings,
        "output_bindings": output_bindings,
        "glb_inspection": {"recliner": recliner_inspection, "empty_room_shell": shell_inspection},
        "non_human_checks": non_human_checks,
        "failed_non_human_checks": failed,
        "human_review": {
            "required": True,
            "approved": False,
            "status": status,
            "review_paths": [str(contact_path), str(multiangle_path)],
            "instruction": "View both exact hash-bound PNGs locally. Do not infer approval; require an explicit later human judgement bound to these hashes and candidate fingerprint.",
        },
        "authority": pack["authority_contract"],
        "rejected_candidate": {
            "path": str(REJECTED_GLB_PATH),
            "sha256": REJECTED_GLB_SHA256,
            "preserved_unchanged": sha256_file(REJECTED_GLB_PATH) == REJECTED_GLB_SHA256,
            "reused_modified_smoothed_or_rerendered": False,
        },
        "execution": {"blender": blender, "generator_path": str(Path(__file__).resolve()), "generator_sha256": sha256_file(Path(__file__).resolve())},
        "preservation": {
            "prior_task_11_8_4_and_11_8_4a_evidence_modified": False,
            "ui_or_interface_modified": False,
            "session_or_qualification_started": False,
            "service_process_or_scheduled_task_ownership_modified": False,
            "cloud_download_or_dependency_addition": False,
            "commit_or_staging_created": False,
        },
        "mvp_alignment": "Closes only the deterministic reconstruction gap after the rejected neural geometry lane and remains on the 6–8 active-coding-hour visual-first path.",
    }


def worker_main(config_path: Path) -> int:
    import bpy
    from mathutils import Vector

    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir = Path(config["output_dir"])
    textures = {name: Path(path) for name, path in config["textures"].items()}

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    root_collection = bpy.context.scene.collection
    default_collection = bpy.data.collections.get("Collection")
    if default_collection:
        default_collection.name = "ProofHelpers"
    recliner_collection = bpy.data.collections.new("ReclinerComponents")
    shell_collection = bpy.data.collections.new("DeterministicEmptyRoomShell")
    root_collection.children.link(recliner_collection)
    root_collection.children.link(shell_collection)

    def material(name: str, texture_key: str, roughness: float, metallic: float = 0.0):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        image = bpy.data.images.load(str(textures[texture_key]), check_existing=True)
        image.pack()
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = f"{name}_EmbeddedTexture"
        tex.image = image
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        return mat

    leather = material("BurgundyLeather", "leather", 0.42)
    edge = material("DarkLeatherPiping", "leather_edge", 0.50)
    dark = material("DarkStructuralBase", "dark_base", 0.38, 0.08)
    wood = material("DarkWood", "wood", 0.58)
    cream = material("CreamPlaster", "cream", 0.82)
    floor_mat = material("WarmWoodFloor", "floor", 0.56)
    trim = material("OpeningTrim", "trim", 0.50)

    def move_to_collection(obj, collection):
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        collection.objects.link(obj)

    def add_box(name, dimensions, location, mat, collection, rotation=(0.0, 0.0, 0.0), bevel=0.03):
        bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = dimensions
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        if bevel > 0:
            modifier = obj.modifiers.new(name="EdgeBevel", type="BEVEL")
            modifier.width = bevel
            modifier.segments = 3
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.data.name = f"{name}_mesh"
        obj.data.materials.append(mat)
        obj["proof_component"] = name
        move_to_collection(obj, collection)
        return obj

    recliner_root = bpy.data.objects.new("recliner_root", None)
    recliner_root["stable_uuid"] = config["recliner_uuid"]
    recliner_collection.objects.link(recliner_root)
    components = []

    def component(name, dimensions, location, mat=leather, rotation=(0.0, 0.0, 0.0), bevel=0.04):
        obj = add_box(name, dimensions, location, mat, recliner_collection, rotation, bevel)
        obj.parent = recliner_root
        components.append(obj)
        return obj

    component("base", (1.46, 1.16, 0.28), (0.0, 0.10, 0.22), dark, bevel=0.08)
    component("base_front_rail", (1.25, 0.16, 0.22), (0.0, -0.52, 0.37), dark, bevel=0.035)
    component("seat_frame", (1.46, 1.28, 0.18), (0.0, -0.08, 0.69), dark, bevel=0.035)
    component("seat_cushion", (1.22, 1.02, 0.27), (0.0, -0.25, 0.91), leather, rotation=(math.radians(-2), 0.0, 0.0), bevel=0.095)
    component("seat_center_seam", (0.025, 0.96, 0.028), (0.0, -0.29, 1.055), edge, rotation=(math.radians(-2), 0.0, 0.0), bevel=0.008)
    component("left_arm", (0.28, 1.32, 0.64), (-0.78, -0.03, 1.02), leather, rotation=(math.radians(-2), 0.0, math.radians(-2)), bevel=0.075)
    component("right_arm", (0.28, 1.32, 0.64), (0.78, -0.03, 1.02), leather, rotation=(math.radians(-2), 0.0, math.radians(2)), bevel=0.075)
    component("left_arm_piping", (0.035, 1.14, 0.035), (-0.925, -0.08, 1.35), edge, bevel=0.012)
    component("right_arm_piping", (0.035, 1.14, 0.035), (0.925, -0.08, 1.35), edge, bevel=0.012)
    back_rotation = (math.radians(-9), 0.0, 0.0)
    component("back_frame", (1.48, 0.22, 1.56), (0.0, 0.48, 1.70), dark, rotation=back_rotation, bevel=0.045)
    component("back_cushion_lower", (1.24, 0.28, 0.66), (0.0, 0.30, 1.48), leather, rotation=back_rotation, bevel=0.09)
    component("back_cushion_upper", (1.26, 0.30, 0.72), (0.0, 0.43, 2.16), leather, rotation=back_rotation, bevel=0.10)
    component("back_vertical_seam", (0.028, 0.035, 1.18), (0.0, 0.235, 1.87), edge, rotation=back_rotation, bevel=0.008)
    component("back_horizontal_seam", (1.06, 0.035, 0.028), (0.0, 0.22, 1.79), edge, rotation=back_rotation, bevel=0.008)
    component("footrest_support", (0.74, 0.52, 0.12), (0.0, -0.92, 0.48), dark, rotation=(math.radians(-14), 0.0, 0.0), bevel=0.025)
    component("footrest_frame", (1.05, 0.70, 0.16), (0.0, -1.20, 0.55), dark, rotation=(math.radians(-14), 0.0, 0.0), bevel=0.045)
    component("footrest_cushion", (0.91, 0.58, 0.20), (0.0, -1.24, 0.68), leather, rotation=(math.radians(-14), 0.0, 0.0), bevel=0.075)
    component("footrest_seam", (0.025, 0.49, 0.025), (0.0, -1.265, 0.79), edge, rotation=(math.radians(-14), 0.0, 0.0), bevel=0.008)

    shell = []

    def shell_box(name, dimensions, location, mat=cream, rotation=(0.0, 0.0, 0.0), bevel=0.01):
        obj = add_box(name, dimensions, location, mat, shell_collection, rotation, bevel)
        obj["authority"] = "appearance_estimate_only_pending_MetricPlan"
        shell.append(obj)
        return obj

    shell_box("shell_floor", (10.0, 14.0, 0.14), (0.0, 2.5, -0.07), floor_mat, bevel=0.0)
    shell_box("shell_left_wall", (0.16, 14.0, 5.0), (-5.0, 2.5, 2.5))
    shell_box("shell_ceiling", (10.0, 14.0, 0.12), (0.0, 2.5, 5.0), cream, bevel=0.0)
    # Rear wall with an explicit door opening around x=-1.1.
    shell_box("shell_rear_left", (3.1, 0.16, 5.0), (-3.45, 9.5, 2.5))
    shell_box("shell_rear_right", (5.2, 0.16, 5.0), (2.40, 9.5, 2.5))
    shell_box("shell_rear_door_header", (1.7, 0.16, 1.1), (-1.05, 9.5, 4.45))
    # Right wall segments preserve a window and a separate door opening.
    shell_box("shell_right_front", (0.16, 5.9, 5.0), (5.0, -1.55, 2.5))
    shell_box("shell_right_window_sill", (0.16, 2.7, 1.05), (5.0, 2.75, 0.525))
    shell_box("shell_right_window_header", (0.16, 2.7, 1.45), (5.0, 2.75, 4.275))
    shell_box("shell_right_between", (0.16, 1.5, 5.0), (5.0, 4.85, 2.5))
    shell_box("shell_right_door_header", (0.16, 2.1, 1.1), (5.0, 6.65, 4.45))
    shell_box("shell_right_rear", (0.16, 1.8, 5.0), (5.0, 8.6, 2.5))
    # Opening trim makes the deterministic apertures legible.
    shell_box("rear_door_left_trim", (0.12, 0.22, 3.9), (-1.92, 9.38, 1.95), trim, bevel=0.015)
    shell_box("rear_door_right_trim", (0.12, 0.22, 3.9), (-0.18, 9.38, 1.95), trim, bevel=0.015)
    shell_box("rear_door_top_trim", (1.86, 0.22, 0.12), (-1.05, 9.38, 3.90), trim, bevel=0.015)
    shell_box("window_lower_trim", (0.22, 2.9, 0.12), (4.89, 2.75, 1.08), trim, bevel=0.015)
    shell_box("window_upper_trim", (0.22, 2.9, 0.12), (4.89, 2.75, 3.56), trim, bevel=0.015)
    shell_box("window_front_trim", (0.22, 0.12, 2.6), (4.89, 1.36, 2.32), trim, bevel=0.015)
    shell_box("window_rear_trim", (0.22, 0.12, 2.6), (4.89, 4.14, 2.32), trim, bevel=0.015)

    def select_only(objects):
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]

    select_only([recliner_root, *components])
    bpy.ops.export_scene.gltf(filepath=str(output_dir / "deterministic-recliner.glb"), export_format="GLB", use_selection=True, export_apply=True)
    select_only(shell)
    bpy.ops.export_scene.gltf(filepath=str(output_dir / "deterministic-empty-room-shell.glb"), export_format="GLB", use_selection=True, export_apply=True)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.03, 0.025)

    def add_area(name, location, energy, color, size):
        data = bpy.data.lights.new(name=name, type="AREA")
        data.energy = energy
        data.color = color
        data.shape = "DISK"
        data.size = size
        obj = bpy.data.objects.new(name, data)
        root_collection.objects.link(obj)
        obj.location = location
        return obj

    key = add_area("WarmKey", (-3.5, -3.0, 5.5), 1050, (1.0, 0.62, 0.38), 5.0)
    fill = add_area("CoolWindowFill", (4.2, -0.5, 3.8), 800, (0.55, 0.70, 1.0), 4.0)
    rim = add_area("WarmRim", (0.0, 4.0, 4.8), 750, (1.0, 0.42, 0.22), 3.0)

    camera_data = bpy.data.cameras.new("ProofCamera")
    camera = bpy.data.objects.new("ProofCamera", camera_data)
    root_collection.objects.link(camera)
    scene.camera = camera
    camera_data.lens = 52

    def look_at(obj, target):
        direction = Vector(target) - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    neutral_ground = add_box("neutral_ground", (9.0, 9.0, 0.08), (0.0, 0.0, -0.08), cream, default_collection, bevel=0.0)
    for obj in shell:
        obj.hide_render = True
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    camera_data.lens = 58
    view_positions = {
        "front": (0.0, -5.0, 2.15),
        "right": (5.0, 0.0, 2.15),
        "rear": (0.0, 5.0, 2.15),
        "left": (-5.0, 0.0, 2.15),
    }
    for name, position in view_positions.items():
        camera.location = position
        look_at(camera, (0.0, 0.0, 1.18))
        scene.render.filepath = str(output_dir / f"recliner-{name}.png")
        bpy.ops.render.render(write_still=True)

    neutral_ground.hide_render = True
    for obj in shell:
        obj.hide_render = False
    recliner_root.location = (-1.75, 1.15, 0.0)
    recliner_root.rotation_euler[2] = math.radians(14)
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    camera_data.lens = 34
    camera.location = (0.0, -7.6, 3.15)
    look_at(camera, (0.0, 4.4, 1.65))
    scene.render.filepath = str(output_dir / "deterministic-shell-recliner-canon-camera.png")
    bpy.ops.render.render(write_still=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "deterministic-shell-recliner-proof.blend"))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--refresh-comfy", action="store_true")
    parser.add_argument("--comfy-timeout-seconds", type=int, default=900)
    parser.add_argument("--blender-worker", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.blender_worker:
        return worker_main(args.blender_worker.resolve())
    if args.output_dir is None:
        raise SystemExit("--output-dir is required")
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite append-only proof directory: {output_dir}")
    if not BLENDER_EXE.is_file():
        raise SystemExit(f"Blender executable not found: {BLENDER_EXE}")
    output_dir.mkdir(parents=True)

    immutable_bindings = verify_immutable_inputs()
    if not EMPTY_TWIN_PATH.is_file():
        raise SystemExit(f"Existing empty twin not found; refusing to rerun unrelated app branches: {EMPTY_TWIN_PATH}")
    comfy, cutouts = run_exact_item_workflow(args.refresh_comfy, args.comfy_timeout_seconds)
    textures = create_texture_tiles(output_dir)
    worker_config = build_worker_config(output_dir, textures)
    blender = run_blender_worker(worker_config)

    pack = build_pack(cutouts, comfy, output_dir)
    pack_path = output_dir / "canon-decomposition-pack.json"
    write_json(pack_path, pack)
    combine_contact_sheet(CANON_PATH, EMPTY_TWIN_PATH, output_dir / "deterministic-shell-recliner-canon-camera.png", output_dir / "canon-camera-comparison-contact-sheet.png")
    combine_multiangle(output_dir, output_dir / "recliner-neutral-multi-angle-sheet.png")
    evidence = build_evidence(output_dir, pack, comfy, immutable_bindings, blender)
    evidence_path = output_dir / "proof-evidence.json"
    write_json(evidence_path, evidence)
    print(json.dumps({
        "result": evidence["result"],
        "output_dir": str(output_dir),
        "evidence_path": str(evidence_path),
        "candidate_fingerprint": evidence["candidate_fingerprint"],
        "failed_non_human_checks": evidence["failed_non_human_checks"],
        "review_paths": evidence["human_review"]["review_paths"],
    }, indent=2))
    return 0 if evidence["result"] == "AWAITING_EXPLICIT_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    blender_separator = sys.argv.index("--") + 1 if "--" in sys.argv else 1
    raise SystemExit(main(sys.argv[blender_separator:]))
