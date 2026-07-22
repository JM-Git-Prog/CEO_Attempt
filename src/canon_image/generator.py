"""Canon image generation through local ComfyUI, API fallback, or mock mode."""

from __future__ import annotations

import asyncio
import base64
import os
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from src.camera_contract import (
    CameraContract,
    camera_contract_coverage,
    measure_edge_alignment,
    normalize_image_frame,
)
from src.models import SceneConcept
from src.workflow_provenance import (
    artifact_metadata,
    profile_by_id,
    profile_for,
    write_generation_manifest,
)

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
COMFYUI_ENABLED = os.getenv("COMFYUI_ENABLED", "1").lower() in {"1", "true", "yes"}
COMFYUI_TIMEOUT = int(os.getenv("COMFYUI_TIMEOUT", "300"))
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

FLUX_MODEL = "flux-2-klein-base-4b-fp8.safetensors"
FLUX_CLIP = "qwen_3_4b.safetensors"
FLUX_VAE = "flux2-vae.safetensors"
_LAST_PROVIDER: dict[str, str] = {}


@dataclass(frozen=True)
class CanonGenerationResult:
    image_path: Path
    provider: str
    manifests: tuple[Path, ...]
    alignment: dict | None = None


def get_image_provider(session_id: str) -> str:
    return _LAST_PROVIDER.get(session_id, "pending")


def _profile_from_context(workflow_context: dict | None) -> dict:
    context = workflow_context or {}
    if context.get("workflow_profile"):
        profile = profile_by_id(context["workflow_profile"]["id"])
        if context["workflow_profile"] != profile:
            raise ValueError("Workflow context profile differs from its immutable contract")
    elif context.get("workflow_profile_id"):
        profile = profile_by_id(context["workflow_profile_id"])
    else:
        profile = profile_for(int(context.get("interface_version", 6)))
    if context.get("workflow_profile_id") not in {None, "", profile["id"]}:
        raise ValueError("Workflow profile ID does not match the pinned profile")
    return profile


def _generation_prompt(
    concept: SceneConcept,
    profile: dict,
    *,
    mode: str = "conditioned",
    plan_conditioning: tuple[str, ...] = (),
) -> str:
    canon = profile["stages"]["canon"]
    policy = canon.get("base_prompt", canon["prompt"]) if mode == "base" else canon["prompt"]
    if policy == "concept.image_prompt":
        return concept.image_prompt
    if policy in {"enriched_concept_and_plan", "immutable-plan-conditioning/v1"}:
        required_objects = (
            plan_conditioning
            if policy == "immutable-plan-conditioning/v1" and plan_conditioning
            else tuple(concept.key_objects)
        )
        if profile["id"] == "v5-reference-partial@964da06":
            return (
                "MANDATORY VISIBLE FINISH TRANSFORMATION: apply every specified floor, wall, "
                "ceiling, furniture, and fixture material; do not retain gray blockout surfaces. "
                f"{concept.image_prompt} Architecture and finishes: {concept.architecture_notes}. "
                f"Required visible objects: {'; '.join(required_objects)}. "
                f"Exact palette: {concept.palette}. Lighting: {concept.lighting_notes}. "
                "Preserve every stated count exactly."
            )
        return (
            "MANDATORY VISIBLE FINISH TRANSFORMATION: replace every blockout surface with the "
            "specified finished material; render a polished photorealistic interior, never a "
            "colored block model. "
            f"{concept.image_prompt} Architecture and finishes: {concept.architecture_notes}. "
            f"Required visible objects: {'; '.join(required_objects)}. "
            f"Exact palette: {concept.palette}. Lighting: {concept.lighting_notes}. "
            "Preserve every stated count exactly. Remove all blockout labels, guide lines, "
            "debug edges, flat shading, and placeholder geometry from the final photograph."
        )
    raise ValueError(f"Unsupported Canon prompt policy: {policy}")


def _generation_manifest(
    concept: SceneConcept,
    session_id: str,
    prompt: str,
    workflow_context: dict | None,
    workflow: dict | None,
    blockout_path: Path | None = None,
    uploaded_image_name: str | None = None,
) -> dict:
    context = workflow_context or {}
    profile = _profile_from_context(context)
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "prepared",
        "session_id": session_id,
        "interface_version": profile["interface_version"],
        "workflow_profile": profile,
        "workflow_profile_id": profile["id"],
        "models": {
            "diffusion": FLUX_MODEL,
            "text_encoder": FLUX_CLIP,
            "vae": FLUX_VAE,
        },
        "inputs": {
            "user_description": context.get("user_description", ""),
            "scene_concept": concept,
            "floor_plan": context.get("floor_plan"),
            "plan_revision": context.get("plan_revision"),
            "camera_contract": context.get("camera_contract"),
            "canon_attempt": context.get("canon_attempt"),
            "retry_mode": context.get("retry_mode"),
            "generation_feedback": context.get("generation_feedback", ""),
            "plan_conditioning": context.get("plan_conditioning"),
            "generation_prompt": prompt,
            "blockout": artifact_metadata(blockout_path) if blockout_path else None,
            "uploaded_image_name": uploaded_image_name,
        },
        "workflow_graph": workflow,
        "provider_attempts": [],
        "output": None,
    }


def _save_generation(
    output_dir: Path, attempt: int, mode: str, manifest: dict
) -> Path:
    return write_generation_manifest(output_dir, attempt, mode, manifest)


async def check_comfyui() -> dict:
    """Report whether the exact FLUX.2 stack required by the app is available."""
    if not COMFYUI_ENABLED:
        return {"ready": False, "enabled": False, "reason": "disabled"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            stats, models, encoders, vaes = await asyncio.gather(
                client.get(f"{COMFYUI_URL}/system_stats"),
                client.get(f"{COMFYUI_URL}/models/diffusion_models"),
                client.get(f"{COMFYUI_URL}/models/text_encoders"),
                client.get(f"{COMFYUI_URL}/models/vae"),
            )
        for response in (stats, models, encoders, vaes):
            response.raise_for_status()
        missing = [name for name, available in (
            (FLUX_MODEL, models.json()), (FLUX_CLIP, encoders.json()), (FLUX_VAE, vaes.json())
        ) if name not in available]
        device = (stats.json().get("devices") or [{}])[0].get("name", "unknown GPU")
        return {"ready": not missing, "enabled": True, "model": "FLUX.2 Klein 4B FP8", "device": device, "missing": missing}
    except Exception as exc:
        return {"ready": False, "enabled": True, "reason": str(exc)}


def _generate_mock(prompt: str, output_path: Path) -> Path:
    """Create an unmistakably labelled fallback image."""
    width, height = 1024, 768
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        tone = int(18 + 28 * y / height)
        draw.line((0, y, width, y), fill=(tone, tone + 4, tone + 12))
    floor_y = 500
    for y in range(floor_y, height, 48):
        for x in range(0, width, 48):
            color = "#d0cbc0" if ((x // 48 + y // 48) % 2) else "#25262a"
            draw.rectangle((x, y, x + 48, y + 48), fill=color)
    draw.rectangle((120, 360, 900, 510), fill="#594c3c", outline="#d4b78d", width=4)
    for x in (260, 410, 560, 710):
        draw.ellipse((x - 30, 455, x + 30, 485), fill="#b93c36")
        draw.line((x, 480, x, 620), fill="#c4c7ca", width=6)
    draw.rectangle((24, 22, 235, 62), fill="#a03d3d")
    draw.text((38, 34), "MOCK FALLBACK", fill="white")
    draw.text((24, 82), prompt[:145], fill="#c4cad4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def _flux_workflow(prompt: str) -> dict:
    positive = (
        f"{prompt}. Photorealistic interior architectural photography, coherent room layout, "
        "eye-level rectilinear lens, realistic materials, physically plausible designed lighting, "
        "clear furniture silhouettes, no people."
    )
    negative = "panorama, 360 view, equirectangular, fisheye, warped walls, text, watermark, blurry, low quality"
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": secrets.randbits(63), "steps": 20, "cfg": 5.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "living_room/canon"}},
    }


async def generate_canon_image(
    concept: SceneConcept,
    session_id: str,
    attempt: int = 1,
    workflow_context: dict | None = None,
    *,
    plan_conditioning: tuple[str, ...] = (),
) -> CanonGenerationResult:
    """Generate a text-guided Canon and retain immutable lifecycle manifests."""
    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _profile_from_context(workflow_context)
    prompt = _generation_prompt(
        concept, profile, mode="base", plan_conditioning=plan_conditioning
    )
    feedback = str((workflow_context or {}).get("generation_feedback", "")).strip()
    if profile["interface_version"] >= 10 and feedback:
        prompt = f"{prompt} Attempt-specific revision: {feedback}"
    mock_only = profile["stages"]["canon"].get("provider_policy") == "mock_only"
    workflow = None if mock_only else _flux_workflow(prompt)
    manifest = _generation_manifest(
        concept, session_id, prompt, workflow_context, workflow
    )
    manifests = [
        _save_generation(output_path.parent, attempt, "base_prepared", manifest)
    ]

    if COMFYUI_ENABLED and not mock_only:
        try:
            result = await _generate_with_comfyui(
                prompt, output_path, session_id, workflow
            )
            provider = "FLUX.2 Klein · ComfyUI"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
            )
            manifests.append(
                _save_generation(output_path.parent, attempt, "base_completed", manifest)
            )
            return CanonGenerationResult(result, provider, tuple(manifests))
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "ComfyUI", "status": "failed", "error": str(exc)}
            )
            print(f"ComfyUI generation failed: {exc}")
    elif not mock_only:
        manifest["provider_attempts"].append(
            {"provider": "ComfyUI", "status": "skipped", "reason": "disabled"}
        )

    if IMAGE_API_URL and not mock_only:
        try:
            result = await _generate_with_api(prompt, output_path)
            provider = "Image API"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
            )
            manifests.append(
                _save_generation(output_path.parent, attempt, "base_completed", manifest)
            )
            return CanonGenerationResult(result, provider, tuple(manifests))
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "Image API", "status": "failed", "error": str(exc)}
            )
            print(f"Image API generation failed: {exc}")

    provider = "Mock fallback"
    _LAST_PROVIDER[session_id] = provider
    result = _generate_mock(prompt, output_path)
    manifest["provider_attempts"].append(
        {"provider": provider, "status": "completed"}
    )
    manifest.update(
        status="completed",
        finalized_at=datetime.now(timezone.utc).isoformat(),
        output=artifact_metadata(result),
    )
    manifests.append(
        _save_generation(output_path.parent, attempt, "base_completed", manifest)
    )
    return CanonGenerationResult(result, provider, tuple(manifests))


async def _generate_with_comfyui(
    prompt: str,
    output_path: Path,
    session_id: str,
    workflow: dict | None = None,
) -> Path:
    submitted_workflow = workflow or _flux_workflow(prompt)
    timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _run_comfy_workflow(
            client, submitted_workflow, output_path, session_id
        )


async def _generate_with_api(prompt: str, output_path: Path) -> Path:
    headers = {"Authorization": f"Bearer {IMAGE_API_KEY}"} if IMAGE_API_KEY else {}
    async with httpx.AsyncClient(timeout=COMFYUI_TIMEOUT) as client:
        response = await client.post(f"{IMAGE_API_URL}/images/generations", headers=headers, json={"prompt": prompt, "n": 1, "size": "1024x768"})
        response.raise_for_status()
        item = response.json()["data"][0]
        if item.get("b64_json"):
            output_path.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            image_response = await client.get(item["url"])
            image_response.raise_for_status()
            output_path.write_bytes(image_response.content)
        else:
            raise RuntimeError("Image API returned no image data")
    return output_path


def _conditioned_flux_workflow(
    prompt: str,
    image_name: str,
    profile: dict,
    camera_contract: dict | None = None,
) -> dict:
    """Build the exact profile-pinned FLUX.2 reference graph."""
    canon = profile["stages"]["canon"]
    positive = (
        f"{prompt}. Transform the supplied blockout into a photorealistic interior photograph. "
        "STRICTLY preserve camera position, lens perspective, room proportions, wall openings, "
        "object count, placement, scale, and silhouettes. Change only materials, textures, "
        "lighting, atmosphere, and rendering quality. No people."
    )
    if canon.get("appearance_transform") == "full_photoreal_resynthesis":
        positive += (
            " Use the source only as a geometry and camera guide. Completely resynthesize every "
            "visible surface with physically plausible materials, microtexture, reflections, "
            "indirect light, contact shadows, lens response, and photographic depth. The result "
            "must look like a professionally photographed real interior, never a blockout, game "
            "viewport, diagram, clay render, flat-shaded model, or painted source image."
        )
    negative = (
        "changed layout, changed camera, moved furniture, added furniture, missing furniture, "
        "extra furniture, duplicate objects, extra lights, extra chairs, extra stools, "
        "more objects than shown in reference, additional items not in blockout, "
        "warped walls, fisheye, panorama, text, watermark, labels, guide lines, debug edges, "
        "blockout render, flat shading, placeholder materials, illustration, low quality"
    )
    latent_mode = canon.get("latent")
    sigma_schedule = canon.get("sigma_schedule")
    latent_input = ["11", 0] if latent_mode == "empty" else ["7", 0]
    sigma_input = ["12", 0]
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": (
            {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["4", 0],
                    "upscale_method": "lanczos",
                    "width": int(camera_contract["image_width"]),
                    "height": int(camera_contract["image_height"]),
                    "crop": "disabled",
                },
            }
            if profile["interface_version"] >= 9 and camera_contract
            else {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["4", 0],
                    "upscale_method": "lanczos",
                    "megapixels": 0.8,
                    "resolution_steps": 16,
                },
            }
        ),
        "6": {"class_type": "GetImageSize", "inputs": {"image": ["5", 0]}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "9": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["8", 0], "latent": ["7", 0]}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "12": {"class_type": "Flux2Scheduler", "inputs": {"steps": 20, "width": ["6", 0], "height": ["6", 1]}},
        "13": {"class_type": "RandomNoise", "inputs": {"noise_seed": secrets.randbits(63)}},
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "15": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["10", 0], "cfg": 3.5}},
        "16": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["13", 0], "guider": ["15", 0], "sampler": ["14", 0], "sigmas": sigma_input, "latent_image": latent_input}},
        "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 1], "vae": ["3", 0]}},
        "18": {"class_type": "SaveImage", "inputs": {"images": ["17", 0], "filename_prefix": "living_room/conditioned_canon"}},
    }
    if latent_mode == "empty":
        workflow["11"] = {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": ["6", 0], "height": ["6", 1], "batch_size": 1},
        }
    elif latent_mode != "encoded_blockout":
        raise ValueError(f"Unsupported conditioned latent mode: {latent_mode}")
    if sigma_schedule in {"partial_after_step_4", "partial_after_step_8"}:
        workflow["19"] = {
            "class_type": "SplitSigmas",
            "inputs": {
                "sigmas": ["12", 0],
                "step": 8 if sigma_schedule == "partial_after_step_8" else 4,
            },
        }
        workflow["16"]["inputs"]["sigmas"] = ["19", 1]
    elif sigma_schedule != "full":
        raise ValueError(f"Unsupported sigma schedule: {sigma_schedule}")
    return workflow


def _camera_contract_dict(value) -> dict | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _normalize_v9_canon(path: Path, camera_contract: dict | None) -> dict | None:
    if not camera_contract:
        return None
    return normalize_image_frame(path, CameraContract.model_validate(camera_contract))


def _edge_alignment_report(
    blockout_path: Path,
    canon_path: Path,
    camera_contract: dict | None,
    workflow_context: dict | None = None,
    attempt: int = 1,
) -> dict | None:
    """Return a profile-bound, explainable camera-alignment report."""
    if not camera_contract:
        return None
    context = workflow_context or {}
    profile = _profile_from_context(context)
    contract = CameraContract.model_validate(camera_contract)
    report = measure_edge_alignment(blockout_path, canon_path, contract)
    if profile["interface_version"] < 10:
        passed = report["status"] == "aligned"
        return {
            "camera_contract_id": contract.contract_id,
            **report,
            "passed": passed,
            "correction": (
                "none"
                if passed
                else "regenerate from the encoded blockout and review projected landmarks"
            ),
            "reference_landmark_count": len(contract.reference_landmarks),
            "width": contract.image_width,
            "height": contract.image_height,
        }

    policy = profile["stages"]["canon"]["alignment_policy"]
    drift = float(report["drift_px"])
    edge_iou = float(report["edge_iou"])
    aligned = (
        drift <= float(policy["aligned_max_drift_px"])
        and edge_iou >= float(policy["aligned_min_edge_iou"])
    )
    confidently_misaligned = (
        drift > float(policy["misaligned_max_drift_px"])
        or (
            drift > float(policy["aligned_max_drift_px"])
            and edge_iou < float(policy["misaligned_max_edge_iou"])
        )
    )
    status = "aligned" if aligned else "misaligned" if confidently_misaligned else "inconclusive"
    retries_used = max(0, attempt - 1)
    max_retries = int(policy["max_retries"])
    output = artifact_metadata(canon_path)
    coverage = camera_contract_coverage(contract)
    reasons = []
    if drift > float(policy["aligned_max_drift_px"]):
        reasons.append("translation_exceeds_aligned_limit")
    if edge_iou < float(policy["aligned_min_edge_iou"]):
        reasons.append("cross_domain_edge_overlap_is_low")
    if coverage["status"] != "valid":
        reasons.append("camera_landmark_coverage_is_incomplete")
    if status == "inconclusive":
        reasons.append("photoreal_edges_are_not_a_confident_pose_verdict")
    return {
        "camera_contract_id": contract.contract_id,
        **report,
        "method": policy["method"],
        "status": status,
        "passed": status == "aligned",
        "decision": status,
        "reasons": reasons,
        "camera_coverage": coverage,
        "binding": {
            "plan_revision": context.get("plan_revision"),
            "contract_id": contract.contract_id,
            "canon_sha256": output.get("sha256"),
            "attempt": attempt,
        },
        "retry_policy": {
            "max_retries": max_retries,
            "retries_used": retries_used,
            "retries_remaining": max(0, max_retries - retries_used),
            "manual_review_allowed": status == "inconclusive" and retries_used >= max_retries,
        },
        "correction": (
            "none" if status == "aligned" else
            "revise the approved Plan/Camera" if status == "misaligned" else
            "retry within the bounded policy, then explicitly review"
        ),
        "reference_landmark_count": len(contract.reference_landmarks),
        "width": contract.image_width,
        "height": contract.image_height,
    }


async def generate_conditioned_canon(
    concept: SceneConcept,
    blockout_path: Path,
    session_id: str,
    attempt: int = 1,
    workflow_context: dict | None = None,
    *,
    plan_conditioning: tuple[str, ...] = (),
) -> CanonGenerationResult:
    """Generate a profile-pinned Canon from the approved camera blockout."""
    profile = _profile_from_context(workflow_context)
    camera_contract = _camera_contract_dict((workflow_context or {}).get("camera_contract"))
    canon = profile["stages"]["canon"]
    if canon.get("conditioning") == "none":
        return await generate_canon_image(
            concept,
            session_id,
            attempt,
            workflow_context=workflow_context,
            plan_conditioning=plan_conditioning,
        )

    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = _generation_prompt(
        concept, profile, plan_conditioning=plan_conditioning
    )
    feedback = str((workflow_context or {}).get("generation_feedback", "")).strip()
    if profile["interface_version"] >= 10 and feedback:
        prompt = f"{prompt} Attempt-specific revision: {feedback}"
    manifest = _generation_manifest(
        concept,
        session_id,
        prompt,
        workflow_context,
        None,
        blockout_path=blockout_path,
    )
    manifests: list[Path] = []

    if COMFYUI_ENABLED:
        try:
            timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
            async with httpx.AsyncClient(timeout=timeout) as client:
                with blockout_path.open("rb") as image_file:
                    upload = await client.post(
                        f"{COMFYUI_URL}/upload/image",
                        files={"image": (blockout_path.name, image_file, "image/png")},
                        data={"overwrite": "true"},
                    )
                upload.raise_for_status()
                uploaded = upload.json()
                image_name = "/".join(
                    part
                    for part in (
                        uploaded.get("subfolder", ""),
                        uploaded.get("name", blockout_path.name),
                    )
                    if part
                )
                workflow = _conditioned_flux_workflow(
                    prompt, image_name, profile, camera_contract
                )
                manifest["inputs"]["uploaded_image_name"] = image_name
                manifest["workflow_graph"] = workflow
                manifests.append(
                    _save_generation(
                        output_path.parent, attempt, "conditioned_prepared", manifest
                    )
                )
                result = await _run_comfy_workflow(
                    client, workflow, output_path, session_id
                )
            _normalize_v9_canon(result, camera_contract)
            alignment = _edge_alignment_report(
                blockout_path,
                result,
                camera_contract,
                workflow_context=workflow_context,
                attempt=attempt,
            )
            provider = "FLUX.2 Klein · blockout conditioned"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
                camera_alignment=alignment,
            )
            manifests.append(
                _save_generation(
                    output_path.parent, attempt, "conditioned_completed", manifest
                )
            )
            return CanonGenerationResult(
                result, provider, tuple(manifests), alignment=alignment
            )
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "ComfyUI conditioned", "status": "failed", "error": str(exc)}
            )
            manifest.update(
                status="failed", finalized_at=datetime.now(timezone.utc).isoformat()
            )
            manifests.append(
                _save_generation(
                    output_path.parent, attempt, "conditioned_failed", manifest
                )
            )
            print(f"Conditioned ComfyUI generation failed: {exc}")
    else:
        manifest["provider_attempts"].append(
            {"provider": "ComfyUI conditioned", "status": "skipped", "reason": "disabled"}
        )
        manifest.update(
            status="skipped", finalized_at=datetime.now(timezone.utc).isoformat()
        )
        manifests.append(
            _save_generation(output_path.parent, attempt, "conditioned_skipped", manifest)
        )

    fallback = await generate_canon_image(
        concept,
        session_id,
        attempt,
        workflow_context=workflow_context,
        plan_conditioning=plan_conditioning,
    )
    _normalize_v9_canon(fallback.image_path, camera_contract)
    alignment = _edge_alignment_report(
        blockout_path,
        fallback.image_path,
        camera_contract,
        workflow_context=workflow_context,
        attempt=attempt,
    )
    return CanonGenerationResult(
        fallback.image_path,
        fallback.provider,
        tuple(manifests) + fallback.manifests,
        alignment=alignment,
    )


async def _run_comfy_workflow(
    client: httpx.AsyncClient,
    workflow: dict,
    output_path: Path,
    session_id: str,
) -> Path:
    response = await client.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": f"living-room-{session_id}"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow ({response.status_code}): {response.text[:500]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI returned no prompt id")
    started = time.monotonic()
    while time.monotonic() - started < COMFYUI_TIMEOUT:
        await asyncio.sleep(0.75)
        history = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        history.raise_for_status()
        entry = history.json().get(prompt_id)
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI execution failed: {status}")
        for output in entry.get("outputs", {}).values():
            for image in output.get("images", []):
                result = await client.get(f"{COMFYUI_URL}/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                result.raise_for_status()
                output_path.write_bytes(result.content)
                return output_path
        if status.get("completed"):
            raise RuntimeError("ComfyUI completed without an image")
    raise TimeoutError(f"ComfyUI did not finish within {COMFYUI_TIMEOUT} seconds")
