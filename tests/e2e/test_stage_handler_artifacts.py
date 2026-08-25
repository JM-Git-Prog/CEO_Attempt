"""Strict-real artifact tests for the current Canon generation handler."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.unified_pipeline.orchestrator import StageExecutionContext
from src.unified_pipeline.stage_handlers import _handle_canon_generation

COMFYUI_CLIENT_PATCH = "src.photo_pipeline.comfyui_client.ComfyUIClient"
CANONICAL_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)


def _make_ctx(tmp_path: Path) -> StageExecutionContext:
    session_dir = tmp_path / "strict-canon"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text(json.dumps({"turns": [
        {"role": "assistant", "content": "opening proposal"},
        {"role": "user", "content": CANONICAL_PROMPT},
    ]}), encoding="utf-8")
    return StageExecutionContext(
        session_id="strict-canon", session_dir=session_dir,
        stage="canon_generation", object_id=None, plan_revision=0,
        approval_revision=0, attempt=1, values={
            "execution_profile": "strict_real",
            "brief": {
                "room_purpose": "kitchen",
                "atmosphere": {"mood": "warm"},
                "era": {"period": "modern"},
                "palette": {"primary": "warm oak"},
                "success_criteria": "a cozy kitchenette",
                "object_manifest": [
                    {"name": "round table", "count": 1},
                    {"name": "chairs", "count": 2},
                    {"name": "counter", "count": 1},
                    {"name": "coffee maker", "count": 1},
                    {"name": "window", "count": 1},
                ],
            },
        },
    )


@pytest.mark.layer("scene")
def test_canon_fails_closed_without_comfyui(tmp_path):
    with patch(COMFYUI_CLIENT_PATCH) as client:
        client.return_value.health_check = AsyncMock(return_value=False)
        with pytest.raises(RuntimeError, match="requires GPU"):
            asyncio.run(_handle_canon_generation(_make_ctx(tmp_path)))


@pytest.mark.layer("scene")
def test_canon_uses_exact_authority_and_strict_workflow(tmp_path):
    submitted: dict = {}

    async def submit(workflow, **_kwargs):
        submitted.update(workflow)
        return "prompt-1"

    async def save(prompt_id, output_dir, filename):
        assert prompt_id == "prompt-1"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    with patch(COMFYUI_CLIENT_PATCH) as client:
        instance = client.return_value
        instance.health_check = AsyncMock(return_value=True)
        instance.submit_workflow = AsyncMock(side_effect=submit)
        instance.wait_for_completion = AsyncMock(return_value={"outputs": {}})
        instance.get_output_image = AsyncMock(side_effect=save)
        instance.release_vram = AsyncMock()
        result = asyncio.run(_handle_canon_generation(_make_ctx(tmp_path)))

    prompt = result.output["prompt"]
    assert result.output["source_prompt"] == CANONICAL_PROMPT
    instance.release_vram.assert_awaited_once()
    assert len(result.output["source_prompt_sha256"]) == 64
    assert submitted["1"]["class_type"] == "UNETLoader"
    assert "flux-2-klein" in submitted["1"]["inputs"]["unet_name"]
    assert submitted["6"]["class_type"] == "EmptyFlux2LatentImage"
    assert submitted["7"]["inputs"]["steps"] == 20
    assert "Exact user request (authoritative)" in prompt
    assert "exactly two distinct chairs" in prompt
    assert "sole coffee-making appliance" in prompt
    assert "second machine-like countertop appliance" in prompt
    assert "falling rain" in prompt
    negative = submitted["5"]["inputs"]["text"]
    assert "two coffee makers" in negative
    assert "multiple coffee machines" in negative
    assert "duplicate countertop appliances" in negative