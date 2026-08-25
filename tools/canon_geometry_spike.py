"""Artifact-only MiniMax H3 visual-quality diagnostic.

This tool never resumes the source session and never writes inside it. Its output
is diagnostic evidence only and cannot authorize spatial or release decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SESSION_ID = "11bdb38d-9064-4633-ab3b-09673f70c36d"
SOURCE_DIR = ROOT / "output" / SOURCE_SESSION_ID
CANON_PATH = SOURCE_DIR / "artifacts" / "canon.png"
BRIEF_PATH = SOURCE_DIR / "artifacts" / "brief.json"
INELIGIBLE_PATH = SOURCE_DIR / "QUALIFICATION_INELIGIBLE.txt"
COMFY_URL = "http://127.0.0.1:8188"
MODEL_ROOT = Path(r"C:\Users\JohnM\ComfyUI-Shared\models")
MODELS = {
    "unet": (
        MODEL_ROOT / "diffusion_models" / "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a",
    ),
    "video_vae": (
        MODEL_ROOT / "vae" / "minimax_h3_video_vae_fp16.safetensors",
        "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522",
    ),
    "text_encoder": (
        MODEL_ROOT / "text_encoders" / "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6",
    ),
    "turbo_lora": (
        MODEL_ROOT / "loras" / "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        "2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e",
    ),
}
REQUIRED_NODES = {
    "LoadImage",
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "MiniMaxH3ImageToVideo",
    "MiniMaxH3SigmaShift",
    "BasicGuider",
    "RandomNoise",
    "BasicScheduler",
    "KSamplerSelect",
    "SamplerCustomAdvanced",
    "VAEDecode",
    "SaveImage",
    "CreateVideo",
    "SaveVideo",
}
PROMPT = (
    "One continuous single-shot architectural walkthrough beginning exactly from <Picture 1>. "
    "Over approximately five seconds, the camera makes one slow physically plausible dolly forward "
    "with a very small rightward arc, no more than ten degrees, while preserving the original 4:3 "
    "framing and room geometry. The exact fixed inventory remains unchanged: one round wooden table, "
    "two separate chairs, one built-in counter, one coffee maker resting on that counter, and one "
    "window looking out at rain. No cuts, transitions, zoom jumps, object motion, people, additions, "
    "removals, duplication, shape changes, opening changes, material changes, lighting changes, or "
    "morphing. Preserve object identity, dimensions, placement, architecture, warm materials, and "
    "steady illumination throughout. Silent video; camera motion only."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")
    temporary.replace(path)


def occurrence_bindings(brief: dict[str, Any]) -> list[dict[str, Any]]:
    wanted = {"round table", "two chairs", "counter", "coffee maker"}
    entries = {item["name"]: item for item in brief["object_manifest"] if item["name"] in wanted}
    if set(entries) != wanted:
        raise ValueError(f"Brief lacks required diagnostic assets: {sorted(wanted - set(entries))}")
    result: list[dict[str, Any]] = []
    for name in ("round table", "two chairs", "counter", "coffee maker"):
        item = entries[name]
        parent = uuid.UUID(item["id"])
        if name == "two chairs":
            for index in (1, 2):
                result.append({
                    "label": f"chair-{index}",
                    "uuid": str(uuid.uuid5(parent, f"diagnostic-occurrence-{index}")),
                    "brief_uuid": item["id"],
                    "occurrence": index,
                    "status": "not_run",
                })
        else:
            result.append({
                "label": name,
                "uuid": item["id"],
                "brief_uuid": item["id"],
                "occurrence": 1,
                "status": "not_run",
            })
    return result


def build_minimax_workflow(
    image_name: str,
    output_prefix: str,
    *,
    seed: int,
    steps: int = 20,
    turbo: bool = False,
) -> dict[str, Any]:
    if turbo and steps != 8:
        raise ValueError("Turbo is diagnostic draft-only and must use exactly 8 steps")
    if not turbo and steps != 20:
        raise ValueError("Accepted diagnostic video must use exactly 20 steps")
    workflow: dict[str, Any] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "UNETLoader", "inputs": {
            "unet_name": MODELS["unet"][0].name, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": MODELS["text_encoder"][0].name, "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["video_vae"][0].name}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "prompt": PROMPT,
            "width": 1024, "height": 768, "length": 124, "first_frame": ["1", 0]}},
        "6": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["2", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "7": {"class_type": "BasicGuider", "inputs": {
            "model": ["6", 0], "conditioning": ["5", 0]}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicScheduler", "inputs": {
            "model": ["6", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["8", 0], "guider": ["7", 0], "sampler": ["10", 0],
            "sigmas": ["9", 0], "latent_image": ["5", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {
            "images": ["12", 0], "filename_prefix": output_prefix + "/frames/frame"}},
        "14": {"class_type": "CreateVideo", "inputs": {
            "images": ["12", 0], "fps": 24.0, "bit_depth": 8}},
        "15": {"class_type": "SaveVideo", "inputs": {
            "video": ["14", 0], "filename_prefix": output_prefix + "/minimax_h3_20step",
            "format": "auto", "codec": "auto"}},
    }
    if turbo:
        workflow["16"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["2", 0], "lora_name": MODELS["turbo_lora"][0].name, "strength_model": 1.0}}
        workflow["6"]["inputs"]["model"] = ["16", 0]
        workflow["15"]["inputs"]["filename_prefix"] = output_prefix + "/minimax_h3_8step_draft"
    return workflow


def command_output(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    return {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def stop_loaded_ollama_models() -> dict[str, Any]:
    before = command_output(["ollama", "ps"])
    lines = [line for line in before["stdout"].splitlines()[1:] if line.strip()]
    stopped = []
    for line in lines:
        model = line.split()[0]
        result = command_output(["ollama", "stop", model])
        stopped.append({"model": model, **result})
    after = command_output(["ollama", "ps"])
    if len([line for line in after["stdout"].splitlines()[1:] if line.strip()]) != 0:
        raise RuntimeError("Ollama still has a loaded model after explicit stop")
    return {"before": before, "stopped": stopped, "after": after}


def wait_for_vram_release(client: httpx.Client, timeout_seconds: int = 90) -> dict[str, Any]:
    client.post("/free", json={"unload_models": True, "free_memory": True}).raise_for_status()
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        stats = client.get("/system_stats").json()
        device = stats["devices"][0]
        used = int(device["vram_total"]) - int(device["vram_free"])
        last = {"vram_total": device["vram_total"], "vram_free": device["vram_free"], "vram_used": used}
        if used < 4 * 1024**3:
            return last
        time.sleep(2)
    raise RuntimeError(f"Comfy VRAM did not fall below 4 GiB used: {last}")


def preflight(client: httpx.Client) -> dict[str, Any]:
    for path in (CANON_PATH, BRIEF_PATH, INELIGIBLE_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    if "PERMANENTLY INELIGIBLE" not in INELIGIBLE_PATH.read_text(encoding="utf-8"):
        raise RuntimeError("Source session lacks permanent ineligibility marker")
    object_info = client.get("/object_info").json()
    missing_nodes = sorted(REQUIRED_NODES - set(object_info))
    if missing_nodes:
        raise RuntimeError(f"ComfyUI missing required nodes: {missing_nodes}")
    queue = client.get("/queue").json()
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI queue is not empty; refusing to share the GPU")
    models = {}
    for role, (path, expected_hash) in MODELS.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise RuntimeError(f"Model hash mismatch for {path.name}: {actual_hash}")
        models[role] = {"path": str(path), "bytes": path.stat().st_size, "sha256": actual_hash}
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    return {
        "status": "pass",
        "checked_at": datetime.now(UTC).isoformat(),
        "comfy_url": COMFY_URL,
        "comfy_system": client.get("/system_stats").json(),
        "queue": queue,
        "required_nodes": sorted(REQUIRED_NODES),
        "models": models,
        "source": {
            "session_id": SOURCE_SESSION_ID,
            "canon": {"path": str(CANON_PATH), "bytes": CANON_PATH.stat().st_size, "sha256": sha256_file(CANON_PATH)},
            "brief": {"path": str(BRIEF_PATH), "bytes": BRIEF_PATH.stat().st_size, "sha256": sha256_file(BRIEF_PATH)},
            "permanently_ineligible": True,
            "resumed": False,
        },
        "objects": occurrence_bindings(brief),
        "metric_plan": {"available": False, "plan_revision": 0, "reason": "source session failed before MetricPlan generation"},
        "gpu": command_output(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader"]),
    }


def upload_canon(client: httpx.Client, run_id: str) -> str:
    upload_name = f"canon_geometry_spike_{run_id}.png"
    with CANON_PATH.open("rb") as stream:
        response = client.post(
            "/upload/image",
            files={"image": (upload_name, stream, "image/png")},
            data={"type": "input", "overwrite": "false"},
        )
    response.raise_for_status()
    data = response.json()
    return str(Path(data.get("subfolder", "")) / data["name"]).replace("\\", "/")


def wait_for_history(client: httpx.Client, prompt_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        history = client.get(f"/history/{prompt_id}").json()
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(10)
    raise TimeoutError(f"MiniMax prompt {prompt_id} exceeded {timeout_seconds}s")


def download_outputs(client: httpx.Client, history: dict[str, Any], destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    video_suffixes = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
    for node_id, output in sorted(history.get("outputs", {}).items(), key=lambda item: int(item[0])):
        for reported_kind in ("images", "video", "videos"):
            raw_items = output.get(reported_kind, [])
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
            for index, item in enumerate(raw_items):
                if not isinstance(item, dict) or "filename" not in item:
                    continue
                suffix = Path(item["filename"]).suffix.lower()
                kind = "video" if suffix in video_suffixes else reported_kind
                query = urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                data = client.get(f"/view?{query}").content
                local = destination / f"node-{node_id}-{kind}-{index:03d}{suffix}"
                local.write_bytes(data)
                records.append({"node_id": node_id, "kind": kind, "reported_kind": reported_kind, "path": str(local), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "comfy_output": item})
    if not any(record["kind"] == "video" for record in records):
        raise RuntimeError(f"MiniMax history contains no saved video: {history.get('outputs', {})}")
    images = [record for record in records if record["kind"] == "images"]
    if len(images) < 8:
        raise RuntimeError(f"MiniMax history contains only {len(images)} frame images")
    return {"artifacts": records, "frame_count": len(images)}


def finalize_bundle(bundle_path: Path, bundle: dict[str, Any]) -> Path:
    bundle["completed_at"] = datetime.now(UTC).isoformat()
    without_digest = {key: value for key, value in bundle.items() if key != "bundle_content_sha256"}
    bundle["bundle_content_sha256"] = hashlib.sha256(canonical_json(without_digest)).hexdigest()
    write_json(bundle_path, bundle)
    return bundle_path


def reconcile_completed_video(run_id: str, prompt_id: str) -> Path:
    output_dir = ROOT / "output" / "diagnostics" / run_id
    bundle_path = output_dir / "evidence_bundle.json"
    preserved_failure = output_dir / "evidence_bundle.attempt-1-output-classification-failure.json"
    if not preserved_failure.exists():
        preserved_failure.write_bytes(bundle_path.read_bytes())
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    with httpx.Client(base_url=COMFY_URL, timeout=120) as client:
        history_response = client.get(f"/history/{prompt_id}").json()
        if prompt_id not in history_response:
            raise RuntimeError(f"Completed prompt not found in Comfy history: {prompt_id}")
        history = history_response[prompt_id]
        status = history.get("status", {})
        if status.get("status_str") not in {None, "success"} or status.get("completed") is False:
            raise RuntimeError(f"Cannot reconcile failed MiniMax prompt: {status}")
        outputs = download_outputs(client, history, output_dir / "minimax")
    bundle.setdefault("workflow", {})["prompt_id"] = prompt_id
    bundle.setdefault("harness_defects", []).append({
        "attempt": 1,
        "status": "fixed_and_reconciled",
        "defect": "SaveVideo MP4 was reported by Comfy under the generic images output key",
        "preserved_evidence": str(preserved_failure),
        "gpu_rerun": False,
    })
    bundle["stages"]["minimax_h3_20step_video"] = {
        "status": "pass",
        "reconciled_from_completed_prompt": True,
        **outputs,
    }
    bundle["furthest_completed_stage"] = "minimax_h3_20step_video"
    bundle["verdict"] = "PARTIAL"
    bundle["blocker"] = "temporal gate not yet executed"
    return finalize_bundle(bundle_path, bundle)


def run_video(run_id: str, timeout_seconds: int) -> Path:
    output_dir = ROOT / "output" / "diagnostics" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    bundle_path = output_dir / "evidence_bundle.json"
    bundle: dict[str, Any] = {
        "schema_version": "canon-to-geometry-diagnostic/v1",
        "run_id": run_id,
        "diagnostic_only": True,
        "non_authoritative": True,
        "release_eligible": False,
        "source_session_resumed": False,
        "metric_plan_is_sole_spatial_authority": True,
        "verdict": "IN_PROGRESS",
        "furthest_completed_stage": "none",
        "stages": {
            "preflight": {"status": "running"},
            "minimax_h3_20step_video": {"status": "not_run"},
            "temporal_gate": {"status": "not_run"},
            "depth_camera": {"status": "not_run"},
            "uuid_tracking": {"status": "not_run"},
            "rgbd_point_clouds": {"status": "not_run"},
            "hunyuan_candidates": {"status": "not_run"},
            "neutral_turntable": {"status": "not_run"},
            "metric_plan_placement": {"status": "not_applicable", "reason": "no source MetricPlan"},
            "deterministic_comparison": {"status": "not_run"},
        },
    }
    write_json(bundle_path, bundle)
    try:
        with httpx.Client(base_url=COMFY_URL, timeout=120) as client:
            bundle["preflight"] = preflight(client)
            bundle["objects"] = bundle["preflight"]["objects"]
            bundle["stages"]["preflight"] = {"status": "pass"}
            bundle["furthest_completed_stage"] = "preflight"
            bundle["ollama_unload"] = stop_loaded_ollama_models()
            bundle["vram_after_release"] = wait_for_vram_release(client)
            image_name = upload_canon(client, run_id)
            workflow = build_minimax_workflow(image_name, f"diagnostics/{run_id}", seed=3700117, steps=20)
            workflow_path = output_dir / "minimax_h3_20step_workflow.json"
            write_json(workflow_path, workflow)
            bundle["workflow"] = {"path": str(workflow_path), "sha256": hashlib.sha256(canonical_json(workflow)).hexdigest(), "seed": 3700117, "steps": 20, "turbo": False, "width": 1024, "height": 768, "length_frames": 124, "fps": 24}
            bundle["stages"]["minimax_h3_20step_video"] = {"status": "running"}
            write_json(bundle_path, bundle)
            started = time.monotonic()
            response = client.post("/prompt", json={"prompt": workflow, "client_id": run_id})
            response.raise_for_status()
            submission = response.json()
            if submission.get("node_errors"):
                raise RuntimeError(f"Comfy workflow validation failed: {submission['node_errors']}")
            prompt_id = submission["prompt_id"]
            bundle["workflow"]["prompt_id"] = prompt_id
            history = wait_for_history(client, prompt_id, timeout_seconds)
            status = history.get("status", {})
            if status.get("status_str") not in {None, "success"} or status.get("completed") is False:
                raise RuntimeError(f"MiniMax execution failed: {status}")
            outputs = download_outputs(client, history, output_dir / "minimax")
            bundle["stages"]["minimax_h3_20step_video"] = {"status": "pass", "elapsed_seconds": round(time.monotonic() - started, 3), **outputs}
            bundle["furthest_completed_stage"] = "minimax_h3_20step_video"
            bundle["verdict"] = "PARTIAL"
            bundle["blocker"] = "temporal gate not yet executed"
    except Exception as exc:
        current_stage = "minimax_h3_20step_video" if bundle["stages"]["preflight"]["status"] == "pass" else "preflight"
        bundle["stages"][current_stage] = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        bundle["verdict"] = "FAILURE"
        bundle["blocker"] = f"{type(exc).__name__}: {exc}"
    return finalize_bundle(bundle_path, bundle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--reconcile-prompt-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.reconcile_prompt_id:
        bundle_path = reconcile_completed_video(args.run_id, args.reconcile_prompt_id)
    else:
        bundle_path = run_video(args.run_id, args.timeout_seconds)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    print(json.dumps({"bundle": str(bundle_path), "verdict": bundle["verdict"], "furthest_completed_stage": bundle["furthest_completed_stage"], "blocker": bundle.get("blocker")}, indent=2))
    return 0 if bundle["furthest_completed_stage"] == "minimax_h3_20step_video" else 1


if __name__ == "__main__":
    raise SystemExit(main())
