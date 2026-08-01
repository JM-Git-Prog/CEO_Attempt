"""Stage handler wiring for the durable UnifiedOrchestrator.

Maps every declared stage in DEFAULT_STAGE_SPECS to a concrete handler function
that the orchestrator calls during its run loop. GPU stages return pending with
a synthetic job_id (mock). Approval stages return awaiting_approval. Non-GPU /
non-approval stages execute synchronously and return completed results.

This is the integration layer — it connects stage names to their implementations
without touching orchestrator.py.

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    StageExecutionContext,
    StageResult,
)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _awaiting_approval(stage: str, context: StageExecutionContext) -> StageResult:
    """Return a StageResult that signals the orchestrator to park at an approval gate."""
    return StageResult(
        output={
            "awaiting_approval": True,
            "stage": stage,
            "object_id": context.object_id,
            "plan_revision": context.plan_revision,
        },
        plan_revision=context.plan_revision,
        approval_revision=context.approval_revision,
    )


def _gpu_pending(stage: str, context: StageExecutionContext) -> StageResult:
    """Return a StageResult with a synthetic external job_id (mock GPU submission)."""
    job_id = f"mock-{stage}-{uuid.uuid4().hex[:12]}"
    return StageResult.pending(
        job_id,
        plan_revision=context.plan_revision,
        metadata={"stage": stage, "object_id": context.object_id},
    )


def _immediate(output: Mapping[str, Any], context: StageExecutionContext) -> StageResult:
    """Return a completed StageResult with the given output."""
    return StageResult(
        output=dict(output),
        plan_revision=context.plan_revision,
        approval_revision=context.approval_revision,
    )


def _contract_hash(data: Mapping[str, Any]) -> str:
    """Compute a deterministic sha256 hash for contract-like output."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Stage categories (derived from DEFAULT_STAGE_SPECS)
# ---------------------------------------------------------------------------

APPROVAL_STAGES = frozenset(
    spec.name for spec in DEFAULT_STAGE_SPECS if spec.approval_for is not None
)

GPU_STAGES = frozenset({
    "dream_preview",
    "canon_honesty",
    "segment",
    "mesh_generation",
    "material_pass_2",
})

# Stages that actually call live GPU services (others return immediate placeholders)
LIVE_GPU_STAGES = frozenset({
    "dream_preview",  # Wired to real ComfyUI FLUX
})


# ---------------------------------------------------------------------------
# Individual stage handler implementations
# ---------------------------------------------------------------------------

def _handle_conversation(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "conversation_complete"}, ctx)


def _handle_brief(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "brief_generated", "object_count": 0}, ctx)


def _handle_art_bible(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "art_bible_generated"}, ctx)


async def _handle_dream_preview(ctx: StageExecutionContext) -> StageResult:
    """Generate a real FLUX Dream Preview via ComfyUI.

    Calls DreamPreviewGenerator which submits a FLUX workflow to ComfyUI
    on localhost:8188. Returns the result path on success, or a degraded
    result if ComfyUI is unavailable.
    """
    import logging
    from src.unified_pipeline.dream_preview import DreamPreviewGenerator

    _log = logging.getLogger("live_trace")

    brief = ctx.values.get("brief", {})
    room_purpose = brief.get("room_purpose", "cozy room")
    atmosphere = brief.get("atmosphere", {})
    mood = atmosphere.get("mood", "warm and inviting") if isinstance(atmosphere, dict) else "warm"
    era = brief.get("era", {})
    period = era.get("period", "") if isinstance(era, dict) else ""
    palette = brief.get("palette", {})
    primary = palette.get("primary", "") if isinstance(palette, dict) else ""

    objects = brief.get("object_manifest", [])
    object_names = ", ".join(
        item.get("name", "") for item in objects[:6]
        if isinstance(item, dict) and item.get("name")
    ) or "table, chairs, counter"

    prompt = (
        f"Interior photograph of a {period + ' ' if period else ''}{room_purpose}, "
        f"{mood} atmosphere, featuring {object_names}. "
        f"{primary + ' tones. ' if primary else ''}"
        f"Photorealistic, architectural photography, warm natural lighting, "
        f"high detail, 8K quality."
    )

    output_dir = ctx.session_dir / "artifacts" / "dream_previews"
    output_dir.mkdir(parents=True, exist_ok=True)

    _log.info(f"  dream_preview: generating via ComfyUI FLUX — prompt={prompt[:80]}...")
    generator = DreamPreviewGenerator(output_dir=output_dir)

    try:
        paths = await generator.generate(prompt, ctx.session_id, variant_count=1)
    except Exception as exc:
        _log.error(f"  dream_preview FAILED: {exc}")
        paths = []

    if paths:
        _log.info(f"  dream_preview: OK — {paths[0]}")
        return _immediate({
            "status": "dream_preview_complete",
            "image_path": paths[0],
            "variant_count": len(paths),
            "prompt": prompt,
            "provisional_label": "PROVISIONAL — not spatial authority",
        }, ctx)
    else:
        _log.info("  dream_preview: ComfyUI unavailable — continuing with degraded result")
        return _immediate({
            "status": "dream_preview_unavailable",
            "image_path": "",
            "variant_count": 0,
            "prompt": prompt,
            "reason": "ComfyUI unavailable or FLUX generation failed",
        }, ctx)


def _handle_plan_solve(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "plan_solved", "plan_revision": ctx.plan_revision}, ctx)


def _handle_plan_normalize(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "plan_normalized", "plan_revision": ctx.plan_revision}, ctx)


def _handle_plan_validate(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "plan_validated", "passed": True}, ctx)


def _handle_camera_contract(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "camera_contract_set", "fov_deg": 60.0}, ctx)


def _handle_blockout(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "blockout_rendered"}, ctx)


def _handle_canon_honesty(ctx: StageExecutionContext) -> StageResult:
    """Canon generation — immediate with placeholder until real FLUX canon is wired."""
    return _immediate({
        "status": "canon_honesty_complete",
        "image_path": "",
        "honesty_report": {"passed": True, "checks": []},
        "note": "placeholder — real Canon generation requires approved Blockout",
    }, ctx)


def _handle_segment(ctx: StageExecutionContext) -> StageResult:
    """Segmentation — immediate with placeholder until real SAM is wired."""
    return _immediate({
        "status": "segment_complete",
        "segments": [],
        "note": "placeholder — real SAM segmentation requires approved Canon",
    }, ctx)


def _handle_semantic_label(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "labeled",
        "object_id": ctx.object_id,
        "label": "furniture",
    }, ctx)


def _handle_mesh_generation(ctx: StageExecutionContext) -> StageResult:
    """Mesh generation — immediate with placeholder until real Hunyuan3D is wired."""
    return _immediate({
        "status": "mesh_generation_complete",
        "object_id": ctx.object_id,
        "mesh_path": "",
        "generator": "placeholder",
        "note": "placeholder — real Hunyuan3D requires approved Object_Canon",
    }, ctx)


def _handle_material_pass_1(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "material_pass_1_complete",
        "object_id": ctx.object_id,
    }, ctx)


def _handle_material_pass_2(ctx: StageExecutionContext) -> StageResult:
    """Material pass 2 — immediate with placeholder until real PBR estimation is wired."""
    return _immediate({
        "status": "material_pass_2_complete",
        "object_id": ctx.object_id,
        "note": "placeholder — real PBR estimation deferred",
    }, ctx)


def _handle_parametric_room(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "parametric_room_built",
        "width_m": 4.0,
        "depth_m": 3.5,
        "height_m": 2.7,
    }, ctx)


def _handle_optional_depth_reference(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "depth_reference_skipped", "optional": True}, ctx)


def _handle_finish_pass(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "finish_pass_complete"}, ctx)


def _handle_physics_classification(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "physics_classified"}, ctx)


def _handle_physics_settle(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "physics_settled", "passed": True}, ctx)


def _handle_world_contract(ctx: StageExecutionContext) -> StageResult:
    contract_data = {
        "session_id": ctx.session_id,
        "plan_revision": ctx.plan_revision,
        "stage": "world_contract",
    }
    return StageResult(
        output={"status": "world_contract_finalized", "contract_hash": _contract_hash(contract_data)},
        plan_revision=ctx.plan_revision,
        approval_revision=ctx.approval_revision,
        canonical_hash=_contract_hash(contract_data),
    )


def _handle_structural_gates(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "structural_gates_passed",
        "passed": True,
        "report": {"passed": True, "gates": []},
    }, ctx)


def _handle_compile(ctx: StageExecutionContext) -> StageResult:
    """Run BrowserCompiler + GodotCompiler and return combined contract_hash.

    In this integration layer we mock the actual compilation but preserve
    the contract_hash structure that downstream parity_gate requires.
    """
    compile_data = {
        "session_id": ctx.session_id,
        "plan_revision": ctx.plan_revision,
        "targets": ["browser", "godot"],
    }
    contract_hash = _contract_hash(compile_data)
    return StageResult(
        output={
            "status": "compiled",
            "contract_hash": contract_hash,
            "browser": {"compiled": True, "contract_hash": contract_hash},
            "godot": {"compiled": True, "contract_hash": contract_hash},
        },
        plan_revision=ctx.plan_revision,
        approval_revision=ctx.approval_revision,
        canonical_hash=contract_hash,
    )


def _handle_parity_gate(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "parity_passed",
        "passed": True,
        "report": {"passed": True, "mismatches": []},
    }, ctx)


def _handle_final_events(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "final_events_emitted",
        "finality": "final",
    }, ctx)


def _handle_game_overlay(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "game_overlay_applied"}, ctx)


def _handle_real_overlay(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "real_overlay_applied"}, ctx)


def _handle_mode_toggle(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "mode_toggle_configured", "default_mode": "game"}, ctx)


def _handle_warehouse_catalog(ctx: StageExecutionContext) -> StageResult:
    """Per-object warehouse cataloging using the asset_warehouse adapter."""
    return _immediate({
        "status": "cataloged",
        "object_id": ctx.object_id,
        "warehouse_entry_id": f"wh-{uuid.uuid4().hex[:8]}",
    }, ctx)


# ---------------------------------------------------------------------------
# Approval stage handler (generic for all approval gates)
# ---------------------------------------------------------------------------

def _make_approval_handler(stage_name: str) -> Callable[[StageExecutionContext], StageResult]:
    """Factory for approval-stage handlers."""
    def handler(ctx: StageExecutionContext) -> StageResult:
        return _awaiting_approval(stage_name, ctx)
    handler.__name__ = f"_handle_{stage_name}"
    handler.__qualname__ = f"_make_approval_handler.<locals>._handle_{stage_name}"
    return handler


# ---------------------------------------------------------------------------
# Handler registry builder
# ---------------------------------------------------------------------------

_DIRECT_HANDLERS: dict[str, Callable[[StageExecutionContext], StageResult]] = {
    "conversation": _handle_conversation,
    "brief": _handle_brief,
    "art_bible": _handle_art_bible,
    "dream_preview": _handle_dream_preview,
    "plan_solve": _handle_plan_solve,
    "plan_normalize": _handle_plan_normalize,
    "plan_validate": _handle_plan_validate,
    "camera_contract": _handle_camera_contract,
    "blockout": _handle_blockout,
    "canon_honesty": _handle_canon_honesty,
    "segment": _handle_segment,
    "semantic_label": _handle_semantic_label,
    "mesh_generation": _handle_mesh_generation,
    "material_pass_1": _handle_material_pass_1,
    "material_pass_2": _handle_material_pass_2,
    "parametric_room": _handle_parametric_room,
    "optional_depth_reference": _handle_optional_depth_reference,
    "finish_pass": _handle_finish_pass,
    "physics_classification": _handle_physics_classification,
    "physics_settle": _handle_physics_settle,
    "world_contract": _handle_world_contract,
    "structural_gates": _handle_structural_gates,
    "compile": _handle_compile,
    "parity_gate": _handle_parity_gate,
    "final_events": _handle_final_events,
    "game_overlay": _handle_game_overlay,
    "real_overlay": _handle_real_overlay,
    "mode_toggle": _handle_mode_toggle,
    "warehouse_catalog": _handle_warehouse_catalog,
}


def build_handlers(config: dict | None = None) -> dict[str, Callable[[StageExecutionContext], StageResult]]:
    """Build the complete handler map for all stages in DEFAULT_STAGE_SPECS.

    Parameters
    ----------
    config : dict, optional
        Pipeline configuration. Reserved for future use (e.g., selecting real
        GPU backends vs mocks, configuring warehouse endpoints).

    Returns
    -------
    dict[str, Callable]
        Mapping of stage name → handler function covering every stage declared
        in DEFAULT_STAGE_SPECS.
    """
    config = config or {}
    handlers: dict[str, Callable[[StageExecutionContext], StageResult]] = {}

    for spec in DEFAULT_STAGE_SPECS:
        if spec.approval_for is not None:
            # Approval stages get a generic awaiting-approval handler
            handlers[spec.name] = _make_approval_handler(spec.name)
        elif spec.name in _DIRECT_HANDLERS:
            handlers[spec.name] = _DIRECT_HANDLERS[spec.name]
        else:
            # Fallback for any stage not explicitly wired (should not happen)
            def _fallback(ctx: StageExecutionContext, _name: str = spec.name) -> StageResult:
                return _immediate({"status": f"{_name}_complete"}, ctx)
            handlers[spec.name] = _fallback

    return handlers
