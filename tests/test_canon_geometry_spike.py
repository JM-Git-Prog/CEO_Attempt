from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canon_geometry_spike import (
    BRIEF_PATH,
    MODELS,
    build_minimax_workflow,
    canonical_json,
    occurrence_bindings,
)


def test_accepted_workflow_is_native_20_step_4_by_3_video() -> None:
    workflow = build_minimax_workflow("canon.png", "diagnostics/test", seed=7, steps=20)

    assert workflow["5"]["inputs"]["width"] == 1024
    assert workflow["5"]["inputs"]["height"] == 768
    assert workflow["5"]["inputs"]["length"] == 124
    assert workflow["9"]["inputs"]["steps"] == 20
    assert workflow["10"]["inputs"]["sampler_name"] == "res_multistep"
    assert workflow["15"]["class_type"] == "SaveVideo"
    assert all(node["class_type"] != "LoraLoaderModelOnly" for node in workflow.values())
    assert "no cuts" in workflow["5"]["inputs"]["prompt"].lower()
    assert "two separate chairs" in workflow["5"]["inputs"]["prompt"].lower()


def test_turbo_workflow_is_draft_only_and_exactly_eight_steps() -> None:
    workflow = build_minimax_workflow("canon.png", "diagnostics/test", seed=7, steps=8, turbo=True)

    assert workflow["9"]["inputs"]["steps"] == 8
    assert workflow["16"]["inputs"]["lora_name"] == MODELS["turbo_lora"][0].name
    assert workflow["15"]["inputs"]["filename_prefix"].endswith("8step_draft")

    with pytest.raises(ValueError, match="exactly 8 steps"):
        build_minimax_workflow("canon.png", "diagnostics/test", seed=7, steps=7, turbo=True)
    with pytest.raises(ValueError, match="exactly 20 steps"):
        build_minimax_workflow("canon.png", "diagnostics/test", seed=7, steps=19)


def test_required_brief_assets_expand_to_five_stable_occurrence_bindings() -> None:
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))

    first = occurrence_bindings(brief)
    second = occurrence_bindings(brief)

    assert first == second
    assert [item["label"] for item in first] == [
        "round table",
        "chair-1",
        "chair-2",
        "counter",
        "coffee maker",
    ]
    assert len({item["uuid"] for item in first}) == 5
    chair_parent = next(item["id"] for item in brief["object_manifest"] if item["name"] == "two chairs")
    assert first[1]["brief_uuid"] == first[2]["brief_uuid"] == chair_parent
    assert first[1]["uuid"] != chair_parent
    assert first[2]["uuid"] != chair_parent


def test_canonical_workflow_bytes_ignore_mapping_insertion_order() -> None:
    left = {"b": {"x": 1}, "a": [2, 3]}
    right = {"a": [2, 3], "b": {"x": 1}}

    assert canonical_json(left) == canonical_json(right)
