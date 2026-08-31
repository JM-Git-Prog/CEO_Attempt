"""Focused tests for the strict-real Canon-first candidate authority bridge."""
from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from PIL import Image

from src.unified_pipeline.blockout_renderer import load_blockout_visibility
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.canon_first_authority import (
    CandidateAuthorityError,
    canonical_sha256,
)
from src.unified_pipeline.depth_bridge import FORBIDDEN_DEPTH_AUTHORITIES
from src.unified_pipeline.models import MetricPlan
from src.unified_pipeline.object_manifest import build_detected_document
from src.unified_pipeline.orchestrator import StageExecutionContext
from src.unified_pipeline.plan_validator import PlanValidator
from src.unified_pipeline.strict_real_handlers import handle_spatial_reconstruction


MANIFEST_IDS = {
    "table": "e307026a-2a6b-47e8-a2a9-42b8dc7904e0",
    "chairs": "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53",
    "window": "520d6846-bfd7-4f0d-b2c7-120791ebbcfa",
    "counter": "8c6119a5-f7b9-4eca-a30e-cb039aad9c71",
    "coffee": "a4566944-5603-48e2-a0d0-ffc47dc8d225",
}


COUNTER_ALIASES = (
    "counter",
    "countertop",
    "kitchen counter",
    "built-in counter",
    "cabinet",
    "cabinet/storage",
)


def _brief(*, counter_name: str = "counter") -> dict:
    return {
        "room_purpose": "kitchenette",
        "atmosphere": {"mood": "cozy", "lighting_direction": "warm", "time_of_day": "morning"},
        "era": {"period": "contemporary", "style_exclusions": []},
        "palette": {"primary": "#F7D2C4", "accent": "#964B00", "material_finishes": ["wood"]},
        "object_manifest": [
            {"id": MANIFEST_IDS["table"], "name": "round table", "role": "dining", "count": 1, "material_hint": "wood", "is_architectural": False},
            {"id": MANIFEST_IDS["chairs"], "name": "two chairs", "role": "seating", "count": 2, "material_hint": "wood", "is_architectural": False},
            {"id": MANIFEST_IDS["window"], "name": "window", "role": "rain view", "count": 1, "material_hint": "glass", "is_architectural": True},
            {"id": MANIFEST_IDS["counter"], "name": counter_name, "role": "work surface", "count": 1, "material_hint": "stone", "is_architectural": True},
            {"id": MANIFEST_IDS["coffee"], "name": "coffee maker", "role": "appliance", "count": 1, "material_hint": "metal", "is_architectural": False},
        ],
        "game_concept": {},
        "real_capabilities": [],
        "success_criteria": "The window must visibly look out at rain.",
        "provenance": {"source_prompt": "canonical kitchenette"},
    }


def _detections(
    *,
    missing: str = "",
    duplicate: str = "",
    counter_name: str = "countertop",
    counter_category: str = "furniture",
    counter_bbox: list[int] | None = None,
) -> list[dict]:
    values = [
        {"name": "coffee machine", "bbox": [20, 20, 80, 100], "material": "metal", "category": "appliance", "size_estimate": "medium"},
        {"name": "cups", "bbox": [90, 20, 130, 70], "material": "ceramic", "category": "utensil", "size_estimate": "small"},
        {"name": "chair", "bbox": [20, 120, 100, 230], "material": "wood", "category": "furniture", "size_estimate": "medium"},
        {"name": "chair", "bbox": [120, 120, 200, 230], "material": "wood", "category": "furniture", "size_estimate": "medium"},
        {"name": "table", "bbox": [70, 100, 180, 220], "material": "wood", "category": "furniture", "size_estimate": "large"},
        {"name": "window", "bbox": [210, 20, 310, 120], "material": "glass", "category": "architectural", "size_estimate": "large"},
        {"name": counter_name, "bbox": counter_bbox or [0, 230, 320, 270], "material": "stone", "category": counter_category, "size_estimate": "large"},
    ]
    if missing:
        values = [item for item in values if item["name"] != missing]
    if duplicate:
        source = next(item for item in values if item["name"] == duplicate)
        extra = dict(source)
        extra["bbox"] = [220, 130, 300, 230]
        values.append(extra)
    return values


def _prepare_session(
    root: Path,
    *,
    depth_bytes: bytes = b"depth-reference-a",
    missing: str = "",
    duplicate: str = "",
    raster: tuple[int, int] = (320, 270),
    counter_name: str = "countertop",
    brief_counter_name: str = "counter",
    counter_category: str = "furniture",
    counter_bbox: list[int] | None = None,
) -> StageExecutionContext:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    canon = artifacts / "canon.png"
    width, height = raster
    Image.new("RGB", raster, (72, 58, 45)).save(canon)
    (artifacts / "brief.json").write_text(
        json.dumps(_brief(counter_name=brief_counter_name)), encoding="utf-8"
    )
    detected = build_detected_document(
        _detections(
            missing=missing,
            duplicate=duplicate,
            counter_name=counter_name,
            counter_category=counter_category,
            counter_bbox=counter_bbox,
        ),
        canon_path=canon,
        width=width,
        height=height,
        model_used="cached-semantic-observer",
    )
    (artifacts / "detected_objects.json").write_text(
        json.dumps(detected, indent=2), encoding="utf-8"
    )
    mesh = artifacts / "room_shell_raw.glb"
    mesh.write_bytes(depth_bytes)
    depth_doc = {
        "schema_version": "da3-metric-room-evidence/v1",
        "mesh": {"sha256": hashlib.sha256(depth_bytes).hexdigest()},
        "evidence_kind": "depth_evidence",
        "evidence_only": True,
        "optional": True,
        "spatial_authority": False,
        "collision_enabled": False,
        "authority_claims": [],
        "forbidden_authorities": list(FORBIDDEN_DEPTH_AUTHORITIES),
    }
    depth_doc["evidence_sha256"] = canonical_sha256(depth_doc)
    (artifacts / "depth_evidence.json").write_text(
        json.dumps(depth_doc, indent=2), encoding="utf-8"
    )
    return StageExecutionContext(
        session_id=root.name,
        session_dir=root,
        stage="spatial_reconstruction",
        object_id=None,
        values={"execution_profile": "strict_real"},
        plan_revision=0,
        approval_revision=0,
        attempt=1,
    )


def _load_hashed(path: Path, hash_field: str) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    expected = document.pop(hash_field)
    assert canonical_sha256(document) == expected
    document[hash_field] = expected
    return document


def test_candidate_plan_camera_bindings_and_depth_non_authority(tmp_path: Path) -> None:
    first = tmp_path / "candidate-a"
    second = tmp_path / "candidate-b"
    failed_evidence = first / "slice_c_result.json"
    failed_evidence.parent.mkdir(parents=True)
    failed_evidence.write_text('{"status":"blocked_fail_closed"}\n', encoding="utf-8")
    failed_hash = hashlib.sha256(failed_evidence.read_bytes()).hexdigest()

    result_a = handle_spatial_reconstruction(_prepare_session(first, depth_bytes=b"depth-a"))
    result_b = handle_spatial_reconstruction(_prepare_session(second, depth_bytes=b"different-depth-b"))

    assert result_a.output["authority_state"] == "validated_candidate_pending_blockout_approval"
    assert result_a.output["human_approved"] is False
    assert result_a.output["blockout_approved"] is False
    assert result_a.plan_revision > 0
    assert not (first / "artifacts" / "approved_metric_plan.json").exists()
    assert hashlib.sha256(failed_evidence.read_bytes()).hexdigest() == failed_hash

    spatial_a = _load_hashed(first / "artifacts" / "spatial_solution.json", "solution_sha256")
    spatial_b = _load_hashed(second / "artifacts" / "spatial_solution.json", "solution_sha256")
    plan = MetricPlan.from_dict(spatial_a["metric_plan"])
    assert PlanValidator().validate(plan).valid
    assert plan.room_dimensions == (4.0, 3.5, 2.7)
    assert any(item["type"] == "window" for item in plan.openings)
    assert min(item["min_width"] for item in plan.circulation_paths) >= 0.6
    assert len(plan.object_placements) == 5
    assert {item["id"] for item in plan.object_placements} == {
        MANIFEST_IDS["table"],
        f'{MANIFEST_IDS["chairs"]}-1',
        f'{MANIFEST_IDS["chairs"]}-2',
        MANIFEST_IDS["counter"],
        MANIFEST_IDS["coffee"],
    }
    assert spatial_a["metric_plan_sha256"] == spatial_b["metric_plan_sha256"]
    assert spatial_a["camera_sha256"] == spatial_b["camera_sha256"]

    camera = CameraContract.from_dict(spatial_a["camera"])
    assert camera.compute_hash() == spatial_a["camera_sha256"]
    width, depth, height = plan.room_dimensions
    assert -width / 2 < camera.position[0] < width / 2
    assert 0 < camera.position[1] < height
    assert -depth / 2 < camera.position[2] < depth / 2
    with pytest.raises(FrozenInstanceError):
        camera.vfov = 70.0  # type: ignore[misc]

    bindings = spatial_a["semantic_bindings"]
    assert {item["manifest_id"] for item in bindings["required_bindings"]} == set(MANIFEST_IDS.values())
    chair_binding = next(item for item in bindings["required_bindings"] if item["semantic_concept"] == "chair")
    counter_binding = next(item for item in bindings["required_bindings"] if item["semantic_concept"] == "counter")
    assert len(chair_binding["detected_object_ids"]) == 2
    assert len(chair_binding["plan_binding_ids"]) == 2
    assert counter_binding["plan_binding_ids"] == [MANIFEST_IDS["counter"]]
    assert bindings["semantic_gate_precedes_plan_generation"] is True
    assert [item["name"] for item in bindings["extra_observations"]] == ["cups"]
    assert bindings["fuzzy_matching_used"] is False
    assert bindings["detection_coordinates_used_for_plan"] is False

    depth = spatial_a["depth_reference"]
    assert depth["spatial_authority"] is False
    assert depth["collision_enabled"] is False
    assert depth["authority_claims"] == []
    assert depth["used_for_plan"] is False
    assert depth["used_for_camera"] is False
    assert depth["used_for_object_transforms"] is False
    assert set(depth["forbidden_authorities"]) == set(FORBIDDEN_DEPTH_AUTHORITIES)

    assert (first / "artifacts" / "blockout.png").is_file()
    assert (first / "artifacts" / "object_picker.json").is_file()
    picker = _load_hashed(first / "artifacts" / "object_picker.json", "document_sha256")
    assert picker["human_approved"] is False
    assert len(picker["extra_observation_ids"]) == 1


@pytest.mark.parametrize("counter_alias", COUNTER_ALIASES)
def test_builtin_counter_aliases_bind_to_required_uuid(
    tmp_path: Path, counter_alias: str
) -> None:
    root = tmp_path / counter_alias.replace("/", "-").replace(" ", "-")
    handle_spatial_reconstruction(
        _prepare_session(
            root,
            brief_counter_name=counter_alias,
            counter_name=counter_alias,
            counter_category="architectural",
        )
    )

    solution = _load_hashed(
        root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    binding = next(
        item
        for item in solution["semantic_bindings"]["required_bindings"]
        if item["semantic_concept"] == "counter"
    )
    assert binding["manifest_id"] == MANIFEST_IDS["counter"]
    assert binding["plan_binding_ids"] == [MANIFEST_IDS["counter"]]
    assert binding["identity_authority"] == "brief_manifest_uuid"
    assert binding["observation_authority"] is False


def test_builtin_counter_accepts_live_cabinet_storage_without_spatial_authority(
    tmp_path: Path,
) -> None:
    reference_root = tmp_path / "countertop-reference"
    cabinet_root = tmp_path / "cabinet-storage-observation"
    raster = (1024, 768)
    handle_spatial_reconstruction(_prepare_session(reference_root, raster=raster))
    handle_spatial_reconstruction(
        _prepare_session(
            cabinet_root,
            raster=raster,
            counter_name="cabinet/storage",
            counter_category="storage",
            counter_bbox=[0, 0, 1024, 768],
        )
    )

    reference = _load_hashed(
        reference_root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    cabinet = _load_hashed(
        cabinet_root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    binding = next(
        item
        for item in cabinet["semantic_bindings"]["required_bindings"]
        if item["semantic_concept"] == "counter"
    )

    assert binding["manifest_id"] == MANIFEST_IDS["counter"]
    assert binding["identity_authority"] == "brief_manifest_uuid"
    assert binding["is_architectural"] is True
    assert binding["required_count"] == 1
    assert len(binding["detected_object_ids"]) == 1
    assert binding["detected_categories"] == ["storage"]
    assert binding["plan_binding_ids"] == [MANIFEST_IDS["counter"]]
    assert binding["observation_authority"] is False
    assert "bbox" not in binding
    assert cabinet["semantic_bindings"]["detection_coordinates_used_for_plan"] is False
    assert cabinet["metric_plan_sha256"] == reference["metric_plan_sha256"]
    assert cabinet["camera_sha256"] == reference["camera_sha256"]

    # Brief count is authority (Option 1): when vision reports a surplus
    # spatially-distinct instance of a required singular object, the Brief wins
    # — bind the required count and preserve the surplus as an extra
    # observation rather than failing closed. The identity of the bound object
    # is still the Brief manifest UUID.
    duplicate_root = tmp_path / "duplicate-cabinet-storage"
    handle_spatial_reconstruction(
        _prepare_session(
            duplicate_root,
            counter_name="cabinet/storage",
            counter_category="storage",
            duplicate="cabinet/storage",
        )
    )
    duplicate = _load_hashed(
        duplicate_root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    dup_binding = next(
        item
        for item in duplicate["semantic_bindings"]["required_bindings"]
        if item["semantic_concept"] == "counter"
    )
    assert dup_binding["manifest_id"] == MANIFEST_IDS["counter"]
    assert dup_binding["plan_binding_ids"] == [MANIFEST_IDS["counter"]]
    assert len(dup_binding["detected_object_ids"]) == 1
    assert len(dup_binding["surplus_observation_ids"]) == 1
    # The surplus distinct detection is preserved, never silently dropped.
    surplus_id = dup_binding["surplus_observation_ids"][0]
    assert surplus_id in {
        str(item.get("object_id", ""))
        for item in duplicate["semantic_bindings"]["extra_observations"]
    }

    wrong_category_root = tmp_path / "cabinet-wrong-category"
    with pytest.raises(CandidateAuthorityError, match="missing required semantic observations"):
        handle_spatial_reconstruction(
            _prepare_session(
                wrong_category_root,
                counter_name="cabinet",
                counter_category="props",
            )
        )
    assert not (wrong_category_root / "artifacts" / "spatial_solution.json").exists()

    unrelated_full_frame_root = tmp_path / "unrelated-full-frame"
    with pytest.raises(CandidateAuthorityError, match="missing required semantic observations"):
        handle_spatial_reconstruction(
            _prepare_session(
                unrelated_full_frame_root,
                counter_name="room",
                counter_category="storage",
                counter_bbox=[0, 0, 320, 270],
            )
        )
    assert not (
        unrelated_full_frame_root / "artifacts" / "spatial_solution.json"
    ).exists()


@pytest.mark.parametrize(
    ("missing", "duplicate", "message"),
    [
        ("coffee machine", "", "missing required semantic observations"),
    ],
)
def test_missing_required_object_fails_closed(
    tmp_path: Path, missing: str, duplicate: str, message: str
) -> None:
    """Too FEW observations of a required object still fails closed."""
    root = tmp_path / f"failure-{missing or duplicate}"
    ctx = _prepare_session(root, missing=missing, duplicate=duplicate)

    with pytest.raises(CandidateAuthorityError, match=message):
        handle_spatial_reconstruction(ctx)


def test_surplus_distinct_observation_defers_to_brief_count(tmp_path: Path) -> None:
    """Brief count is authority (Option 1).

    When vision reports MORE spatially-distinct instances of a required object
    than the Brief specifies (here a second, disjoint 'table'), the pipeline
    does not fail: it binds the Brief's required count and preserves the surplus
    distinct detection as an extra observation. This is over-DETECTION of a
    countable object, distinct from over-SEGMENTATION of one surface (counter),
    and distinct from too-few observations (which still fails closed).
    """
    root = tmp_path / "surplus-table"
    handle_spatial_reconstruction(
        _prepare_session(root, duplicate="table", raster=(1024, 768))
    )
    solution = _load_hashed(
        root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    table_binding = next(
        item
        for item in solution["semantic_bindings"]["required_bindings"]
        if item["semantic_concept"] == "table"
    )
    # Brief says one round table → exactly one bound instance.
    assert table_binding["manifest_id"] == MANIFEST_IDS["table"]
    assert len(table_binding["detected_object_ids"]) == 1
    assert len(table_binding["surplus_observation_ids"]) == 1
    # The surplus distinct table is preserved as an extra observation.
    surplus_id = table_binding["surplus_observation_ids"][0]
    assert surplus_id in {
        str(item.get("object_id", ""))
        for item in solution["semantic_bindings"]["extra_observations"]
    }
    # Identity/plan authority unchanged: still the Brief manifest UUID.
    assert table_binding["plan_binding_ids"] == [MANIFEST_IDS["table"]]
    assert solution["semantic_bindings"]["detection_coordinates_used_for_plan"] is False


def test_blockout_renderer_consumes_generator_opening_and_placement_fields(tmp_path: Path) -> None:
    root = tmp_path / "renderer-contract"
    handle_spatial_reconstruction(_prepare_session(root))
    spatial = _load_hashed(root / "artifacts" / "spatial_solution.json", "solution_sha256")
    picker = _load_hashed(root / "artifacts" / "object_picker.json", "document_sha256")

    assert {opening["type"] for opening in spatial["metric_plan"]["openings"]} == {"door", "window"}
    assert all("x" in item and "y" in item for item in spatial["metric_plan"]["object_placements"])
    assert picker["camera_sha256"] == spatial["camera_sha256"]
    with Image.open(root / "artifacts" / "blockout.png") as image:
        assert image.size == (320, 270)


def test_rejected_blockout_creates_revision_two_with_green_projection_evidence(
    tmp_path: Path,
) -> None:
    revision_1_root = tmp_path / "revision-1"
    handle_spatial_reconstruction(_prepare_session(revision_1_root, raster=(1024, 768)))
    revision_1_spatial = _load_hashed(
        revision_1_root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    preserved_paths = [
        revision_1_root / "artifacts" / name
        for name in (
            "candidate_metric_plan.json",
            "camera_contract.json",
            "spatial_solution.json",
            "blockout.png",
            "blockout_visibility.json",
            "object_picker.json",
        )
    ]
    preserved_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in preserved_paths
    }
    rejection = tmp_path / "slice_e_result.json"
    rejection.write_text(
        json.dumps({
            "decision": "do_not_approve",
            "plan_revision": 1,
            "feedback": "all Plan instances and both openings must be visible",
        }),
        encoding="utf-8",
    )

    revision_2_root = tmp_path / "revision-2"
    ctx = _prepare_session(revision_2_root, raster=(1024, 768))
    ctx.values["plan_revision_feedback"] = {
        "prior_metric_plan": revision_1_spatial["metric_plan"],
        "prior_plan_revision": 1,
        "prior_metric_plan_sha256": revision_1_spatial["metric_plan_sha256"],
        "rejection_sha256": hashlib.sha256(rejection.read_bytes()).hexdigest(),
        "feedback": "all Plan instances and both openings must be visible",
    }
    result = handle_spatial_reconstruction(ctx)

    spatial = _load_hashed(
        revision_2_root / "artifacts" / "spatial_solution.json", "solution_sha256"
    )
    camera_doc = _load_hashed(
        revision_2_root / "artifacts" / "camera_contract.json", "document_sha256"
    )
    visibility = load_blockout_visibility(
        revision_2_root / "artifacts" / "blockout.png"
    )
    plan = MetricPlan.from_dict(spatial["metric_plan"])

    assert result.plan_revision == 2
    assert [revision.revision for revision in plan.revisions] == [1, 2]
    assert plan.revisions[-1].changed == "camera_contract_and_blockout_framing"
    assert "Blockout rejection" in plan.revisions[-1].reason
    assert spatial["provenance"]["revision"]["geometry_changed"] is False
    assert spatial["provenance"]["revision"]["prior_plan_revision"] == 1
    assert camera_doc["plan_revision"] == 2
    assert camera_doc["camera_sha256"] == spatial["camera_sha256"]
    assert visibility["plan_revision"] == 2
    assert visibility["metric_plan_sha256"] == spatial["metric_plan_sha256"]
    assert visibility["camera_sha256"] == spatial["camera_sha256"]
    assert visibility["raster"] == [1024, 768]
    assert visibility["projection"] == "perspective"
    assert visibility["labels_non_overlapping"] is True
    assert visibility["all_labels_readable"] is True
    assert visibility["all_required_visible"] is True
    assert visibility["fully_green"] is True
    assert set(visibility["elements"]) == {
        "opening:0",
        "opening:1",
        MANIFEST_IDS["table"],
        f'{MANIFEST_IDS["chairs"]}-1',
        f'{MANIFEST_IDS["chairs"]}-2',
        MANIFEST_IDS["counter"],
        MANIFEST_IDS["coffee"],
    }
    assert all(
        element["geometry_visible"]
        and element["geometry_distinct"]
        and not element["behind_camera"]
        and not element["clipped"]
        for element in visibility["elements"].values()
    )
    with Image.open(revision_2_root / "artifacts" / "blockout.png") as image:
        assert image.size == (1024, 768)
        assert len(image.getcolors(maxcolors=1_000_000) or []) > 12

    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in preserved_paths
    } == preserved_hashes
