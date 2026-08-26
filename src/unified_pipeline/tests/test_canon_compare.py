"""Focused tests for Task 8.4 strict three-view Canon comparison.

**Validates: Requirements 22.6, 31-36**
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from src.unified_pipeline.object_manifest import (
    build_plan_bound_selected_manifest,
    load_selected_manifest,
)
from src.unified_pipeline.canon_compare import (
    ArtifactEvidence,
    ComparisonBinding,
    ComparisonRequest,
    EvidenceWriteError,
    FidelityIntent,
    FidelityVerdict,
    FinalQABlockedError,
    RegionKind,
    RegionObservation,
    ReleasePolicy,
    ThreeViewIdentityComparator,
    ViewEvidence,
    ViewKind,
    authorize_final_qa,
    store_evidence,
)

PLAN_HASH = "1" * 64
CAMERA_HASH = "2" * 64
CANON_HASH = "3" * 64
WORLD_HASH = "4" * 64
TABLE_UUID = "7592bf0e-0173-4319-84cf-dfb1e42114ca"
CHAIR_UUID = "8e999cb3-b20a-4d72-b79c-dd311b98008e"


def _binding() -> ComparisonBinding:
    return ComparisonBinding(7, PLAN_HASH, CAMERA_HASH, CANON_HASH, WORLD_HASH)


def _artifact(tmp_path: Path, name: str, binding: ComparisonBinding) -> ArtifactEvidence:
    path = tmp_path / f"{name}.png"
    path.write_bytes(f"measured-{name}".encode())
    provenance = {
        "blockout": "approved_plan_blockout",
        "canon": "approved_scene_canon",
        "world": "world_contract_render",
    }[name]
    return ArtifactEvidence(
        str(path), hashlib.sha256(path.read_bytes()).hexdigest(),
        binding.plan_revision, binding.plan_hash, binding.camera_hash,
        binding.canon_hash, binding.world_contract_hash,
        source_approved=True, approval_revision=3, provenance=provenance,
    )


def _region(
    kind: RegionKind,
    subject_id: str,
    position: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    category: str = "",
    palette: tuple[str, ...] = ("#8B5A2B",),
    materials: tuple[str, ...] = ("oak wood",),
    tags: tuple[str, ...] = ("warm", "kitchen"),
) -> RegionObservation:
    resolved_category = category or {
        RegionKind.SHELL: "architecture",
        RegionKind.OPENING: "opening",
        RegionKind.OBJECT: "furniture",
    }[kind]
    return RegionObservation(
        region_id=subject_id if kind is not RegionKind.OBJECT else f"object-{subject_id}",
        kind=kind,
        stable_uuid=subject_id if kind is RegionKind.OBJECT else "",
        category=resolved_category,
        position_m=position,
        dimensions_m=dimensions,
        rotation_deg=rotation,
        palette=palette,
        materials=materials,
        prompt_tags=tags,
        prompt_fidelity=0.95,
    )


def _regions() -> tuple[RegionObservation, ...]:
    return (
        _region(RegionKind.SHELL, "room", (0.0, 1.35, 0.0), (4.0, 2.7, 3.5)),
        _region(
            RegionKind.OPENING, "window-north", (0.0, 1.5, -1.74),
            (1.2, 1.0, 0.05), palette=("#A8C4D8",),
            materials=("painted wood",), tags=("rain", "window"),
        ),
        _region(
            RegionKind.OBJECT, TABLE_UUID, (-0.8, 0.4, 0.0),
            (0.9, 0.8, 0.9), tags=("round table", "warm"),
        ),
        _region(
            RegionKind.OBJECT, CHAIR_UUID, (1.0, 0.5, 0.0),
            (0.5, 1.0, 0.5), palette=("#6E4425",),
            tags=("chair", "warm"),
        ),
    )


def _request() -> ComparisonRequest:
    regions = _regions()
    return ComparisonRequest(
        requested_object_uuids=(TABLE_UUID, CHAIR_UUID),
        intents=tuple(
            FidelityIntent(
                region.kind, region.subject_id, region.category, region.palette,
                region.materials, region.prompt_tags,
            )
            for region in regions
        ),
        forbidden_overlap_pairs=((f"object:{TABLE_UUID}", f"object:{CHAIR_UUID}"),),
    )


def _case(tmp_path: Path):
    binding = _binding()
    regions = _regions()
    views = tuple(
        ViewEvidence(kind, _artifact(tmp_path, kind.value, binding), regions)
        for kind in (ViewKind.BLOCKOUT, ViewKind.CANON, ViewKind.WORLD)
    )
    return binding, _request(), views


def _replace_region(view: ViewEvidence, key: str, **changes) -> ViewEvidence:
    return replace(
        view,
        regions=tuple(
            replace(region, **changes) if region.key == key else region
            for region in view.regions
        ),
    )


def _codes(report) -> set[str]:
    return {mismatch.code for mismatch in report.mismatches}


def test_green_report_is_hash_bound_append_only_and_authorizes_final_qa(
    tmp_path: Path,
) -> None:
    binding, request, views = _case(tmp_path)

    report = ThreeViewIdentityComparator().compare(
        *views, binding=binding, request=request,
    )
    evidence_path = store_evidence(
        report, tmp_path / "evidence", stored_at_utc="2026-08-01T00:00:00+00:00",
    )
    same_path = store_evidence(
        report, tmp_path / "evidence", stored_at_utc="2099-01-01T00:00:00+00:00",
    )
    token = authorize_final_qa(report)

    assert report.verdict is FidelityVerdict.GREEN
    assert report.verify_hash()
    assert all(check.passed for check in report.checks)
    assert dict(report.artifact_hashes).keys() == {"blockout", "canon", "world"}
    assert same_path == evidence_path
    stored = json.loads(evidence_path.read_text("utf-8"))
    assert stored["stored_at_utc"] == "2026-08-01T00:00:00+00:00"
    assert stored["report"]["binding"]["world_contract_hash"] == WORLD_HASH
    assert token.evidence_hash == report.evidence_hash
    assert token.plan_hash == PLAN_HASH
    assert token.canon_hash == CANON_HASH
    assert token.human_review_required
    assert report.human_review_required


def test_shell_and_opening_truth_require_matching_regions(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    canon = replace(
        canon,
        regions=tuple(region for region in canon.regions if region.region_id != "window-north"),
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    mismatch = next(item for item in report.mismatches if item.code == "identity.missing_region")
    assert mismatch.view == "canon"
    assert mismatch.subject_id == "window-north"


@pytest.mark.parametrize(
    ("key", "changes", "expected_code"),
    [
        ("shell:room", {"dimensions_m": (4.5, 2.7, 3.5)}, "geometry.dimensions"),
        (
            "opening:window-north",
            {"position_m": (0.4, 1.5, -1.74)},
            "geometry.placement",
        ),
    ],
)
def test_shell_and_opening_geometry_drift_is_red(
    tmp_path: Path, key: str, changes: dict, expected_code: str,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(world, key, **changes)

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert expected_code in _codes(report)


def test_every_requested_uuid_must_match_in_every_view(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(
        world, f"object:{CHAIR_UUID}", stable_uuid="different-stable-uuid",
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert {"identity.unplanned_region", "object.requested_missing"} <= _codes(report)
    assert any(item.subject_id == CHAIR_UUID for item in report.mismatches)


def test_missing_stable_uuid_is_red_even_when_object_name_is_present(
    tmp_path: Path,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(world, f"object:{CHAIR_UUID}", stable_uuid="")

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert "object.requested_missing" in _codes(report)


def test_stable_category_identity_cannot_be_replaced_by_name_or_order(
    tmp_path: Path,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(
        world, f"object:{CHAIR_UUID}", category="appliance",
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert "identity.category" in _codes(report)


def test_presence_and_order_alone_cannot_produce_green(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(
        world, f"object:{TABLE_UUID}", position_m=(0.2, 0.4, 0.0),
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert all(
        f"object:{object_id}" in {region.key for region in view.regions}
        for object_id in request.requested_object_uuids
        for view in (blockout, canon, world)
    )
    assert report.verdict is FidelityVerdict.AMBER
    assert "geometry.placement" in _codes(report)


def test_rotation_aware_extents_are_compared_not_raw_presence(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    key = f"object:{TABLE_UUID}"
    blockout = _replace_region(
        blockout, key, dimensions_m=(1.4, 0.8, 0.4), rotation_deg=(0.0, 90.0, 0.0),
    )
    canon = _replace_region(
        canon, key, dimensions_m=(1.4, 0.8, 0.4), rotation_deg=(0.0, 90.0, 0.0),
    )
    world = _replace_region(
        world, key, dimensions_m=(1.4, 0.8, 0.4), rotation_deg=(0.0, 0.0, 0.0),
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.AMBER
    mismatch = next(
        item for item in report.mismatches
        if item.code == "geometry.rotation_aware_extents" and item.view == "world"
    )
    assert mismatch.subject_id == TABLE_UUID
    assert mismatch.discrepancy == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"position_m": (-0.5, 0.4, 0.0)}, "geometry.placement"),
        ({"dimensions_m": (1.3, 0.8, 0.9)}, "geometry.dimensions"),
        ({"dimensions_m": (0.9, 1.2, 0.9)}, "geometry.height"),
    ],
)
def test_placement_dimensions_and_height_each_block_green(
    tmp_path: Path, changes: dict, expected_code: str,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(world, f"object:{TABLE_UUID}", **changes)

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.AMBER
    assert expected_code in _codes(report)


def test_zero_forbidden_overlap_is_computed_from_rotated_extents(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(
        world, f"object:{CHAIR_UUID}", position_m=(-0.55, 0.5, 0.0),
        rotation_deg=(0.0, 45.0, 0.0),
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    overlap = next(item for item in report.mismatches if item.code == "overlap.computed")
    assert overlap.view == "world"
    assert TABLE_UUID in overlap.subject_id and CHAIR_UUID in overlap.subject_id


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"palette": ("#00FF00",)}, "appearance.palette"),
        ({"materials": ("chrome",)}, "appearance.material"),
        ({"prompt_tags": ("warm",)}, "prompt.tags"),
        ({"prompt_fidelity": 0.5}, "prompt.score"),
    ],
)
def test_palette_material_and_prompt_fidelity_are_required(
    tmp_path: Path, changes: dict, expected_code: str,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = _replace_region(world, f"object:{TABLE_UUID}", **changes)

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.AMBER
    assert expected_code in _codes(report)


@pytest.mark.parametrize(
    ("artifact_change", "expected_code"),
    [
        ({"plan_revision": 8}, "binding.plan_revision_drift"),
        ({"plan_hash": "9" * 64}, "binding.plan_hash_drift"),
        ({"camera_hash": "9" * 64}, "binding.camera_hash_drift"),
        ({"canon_hash": "9" * 64}, "binding.canon_hash_drift"),
        ({"world_contract_hash": "9" * 64}, "binding.world_contract_hash_drift"),
        ({"sha256": "9" * 64}, "artifact.hash_drift"),
    ],
)
def test_revision_and_hash_drift_fail_closed(
    tmp_path: Path, artifact_change: dict, expected_code: str,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    world = replace(world, artifact=replace(world.artifact, **artifact_change))

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert expected_code in _codes(report)


def test_unapproved_or_mismatched_source_provenance_fails_closed(
    tmp_path: Path,
) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    canon = replace(
        canon,
        artifact=replace(
            canon.artifact,
            source_approved=False,
            approval_revision=0,
            provenance="unapproved_generation",
        ),
    )

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert "provenance.unapproved_or_mismatched" in _codes(report)


def test_evidence_cannot_claim_or_rewrite_plan_authority(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    canon = replace(canon, authority_claim="architecture_and_camera")

    report = ThreeViewIdentityComparator().compare(
        blockout, canon, world, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.RED
    assert "authority.forbidden_claim" in _codes(report)
    assert blockout.regions == _regions()  # frozen inputs remain untouched


def test_release_policy_blocks_red_and_amber_as_configured(tmp_path: Path) -> None:
    binding, request, (blockout, canon, world) = _case(tmp_path)
    amber_world = _replace_region(
        world, f"object:{TABLE_UUID}", prompt_fidelity=0.5,
    )
    amber = ThreeViewIdentityComparator().compare(
        blockout, canon, amber_world, binding=binding, request=request,
    )
    red = ThreeViewIdentityComparator().compare(
        blockout, replace(canon, authority_claim="geometry"), world,
        binding=binding, request=request,
    )

    with pytest.raises(FinalQABlockedError, match="amber"):
        authorize_final_qa(amber)
    with pytest.raises(FinalQABlockedError, match="red"):
        authorize_final_qa(red)
    diagnostic_token = authorize_final_qa(
        amber, ReleasePolicy(name="diagnostic-review", block_amber=False),
    )
    assert diagnostic_token.verdict is FidelityVerdict.AMBER
    with pytest.raises(FinalQABlockedError, match="red"):
        authorize_final_qa(
            red, ReleasePolicy(name="diagnostic-review", block_amber=False),
        )


def test_evidence_hash_is_deterministic_under_semantic_input_reordering(
    tmp_path: Path,
) -> None:
    binding, request, views = _case(tmp_path)
    first = ThreeViewIdentityComparator().compare(
        *views, binding=binding, request=request,
    )
    reordered_request = ComparisonRequest(
        requested_object_uuids=tuple(reversed(request.requested_object_uuids)),
        intents=tuple(reversed(request.intents)),
        forbidden_overlap_pairs=tuple(reversed(request.forbidden_overlap_pairs)),
    )
    reordered_views = tuple(
        replace(view, regions=tuple(reversed(view.regions))) for view in views
    )
    second = ThreeViewIdentityComparator().compare(
        *reordered_views, binding=binding, request=reordered_request,
    )

    assert second.evidence_hash == first.evidence_hash
    assert second.to_dict() == first.to_dict()


def test_append_only_store_refuses_corrupt_existing_record(tmp_path: Path) -> None:
    binding, request, views = _case(tmp_path)
    report = ThreeViewIdentityComparator().compare(
        *views, binding=binding, request=request,
    )
    evidence_path = store_evidence(report, tmp_path / "evidence")
    evidence_path.write_text('{"report":{"different":true}}', encoding="utf-8")

    with pytest.raises(EvidenceWriteError, match="refusing replacement"):
        store_evidence(report, tmp_path / "evidence")


# Property: identical measured transforms in all views remain GREEN regardless
# of valid object dimensions and Euler yaw.
# **Validates: Requirements 22.6, 35.2**
@given(
    width=st.floats(min_value=0.2, max_value=0.8, allow_nan=False, allow_infinity=False),
    height=st.floats(min_value=0.2, max_value=1.2, allow_nan=False, allow_infinity=False),
    depth=st.floats(min_value=0.2, max_value=0.8, allow_nan=False, allow_infinity=False),
    yaw=st.floats(min_value=-720.0, max_value=720.0, allow_nan=False, allow_infinity=False),
)
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[
        __import__("hypothesis").HealthCheck.function_scoped_fixture,
        __import__("hypothesis").HealthCheck.data_too_large,
    ],
)
def test_property_identical_rotation_aware_measurements_are_green(
    tmp_path: Path, width: float, height: float, depth: float, yaw: float,
) -> None:
    binding, request, views = _case(tmp_path)
    key = f"object:{TABLE_UUID}"
    changed = tuple(
        _replace_region(
            view, key, dimensions_m=(width, height, depth),
            rotation_deg=(0.0, yaw, 0.0),
        )
        for view in views
    )

    report = ThreeViewIdentityComparator().compare(
        *changed, binding=binding, request=request,
    )

    assert report.verdict is FidelityVerdict.GREEN
    assert report.verify_hash()


TASK_2_SELECTED_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "output"
    / "diag-browser-v8-q-18ee9af4-5673-47d5-a4aa-61c6e416c745"
    / "artifacts"
    / "selected_objects.json"
)
TASK_2_PLAN_INSTANCE_IDS = (
    "e307026a-2a6b-47e8-a2a9-42b8dc7904e0",
    "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-1",
    "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-2",
    "8c6119a5-f7b9-4eca-a30e-cb039aad9c71",
    "a4566944-5603-48e2-a0d0-ffc47dc8d225",
)


def _manifest_digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_manifest_inputs() -> tuple[dict, dict, tuple[str, ...]]:
    plan_ids = TASK_2_PLAN_INSTANCE_IDS
    detection_ids = tuple(f"detection-{index}" for index in range(len(plan_ids)))
    detected = {
        "canon_sha256": "a" * 64,
        "document_sha256": "b" * 64,
        "objects": [
            {"object_id": detection_id, "name": f"object-{index}"}
            for index, detection_id in enumerate(detection_ids)
        ],
    }
    picker = {
        "plan_revision": 4,
        "canon_sha256": detected["canon_sha256"],
        "detected_objects_sha256": detected["document_sha256"],
        "metric_plan_sha256": "c" * 64,
        "camera_sha256": "d" * 64,
        "blockout_visibility_sha256": "e" * 64,
        "fuzzy_matching_used": False,
        "required_bindings": [{"plan_binding_ids": list(plan_ids)}],
        "objects": [
            {
                "object_id": detection_id,
                "required": True,
                "plan_binding_id": plan_id,
                "manifest_id": plan_id.rsplit("-", 1)[0],
                "semantic_concept": "counter" if index == 3 else f"object-{index}",
            }
            for index, (detection_id, plan_id) in enumerate(zip(detection_ids, plan_ids))
        ],
    }
    picker["document_sha256"] = _manifest_digest(picker)
    return detected, picker, detection_ids


def test_property_2_build_plan_bound_manifest_is_input_order_independent() -> None:
    """Unit anchor for the existing Plan-bound manifest builder semantics.

    **Validates: Requirements 2.7, 2.8, 2.9, 3.4, 3.5, 3.14**
    """
    detected, picker, detection_ids = _plan_manifest_inputs()
    expected = build_plan_bound_selected_manifest(
        detected,
        picker,
        detection_ids,
        plan_revision=4,
        approval_revision=1,
        approval_evidence_sha256="f" * 64,
    )
    reordered = build_plan_bound_selected_manifest(
        detected,
        picker,
        reversed(detection_ids),
        plan_revision=4,
        approval_revision=1,
        approval_evidence_sha256="f" * 64,
    )

    assert reordered == expected
    assert tuple(expected["selected_plan_instance_ids"]) == TASK_2_PLAN_INSTANCE_IDS
    assert tuple(item["plan_instance_id"] for item in expected["objects"]) == TASK_2_PLAN_INSTANCE_IDS
    assert all(item["observation_authority"] is False for item in expected["objects"])
    assert expected["detection_role"] == "bounded_segmentation_observation_only"


def test_property_2_selected_manifest_preserves_plan_uuid_inventory_and_observation_boundary() -> None:
    """Unit anchor for stable Plan identity, inventory, and isolator boundaries.

    **Validates: Requirements 2.7, 2.8, 2.9, 3.4, 3.5, 3.7, 3.14, 3.18**
    """
    source_hash = hashlib.sha256(TASK_2_SELECTED_MANIFEST.read_bytes()).hexdigest()
    manifest = load_selected_manifest(TASK_2_SELECTED_MANIFEST)

    assert manifest["manifest_sha256"] == "dd0b648fac34c5ddbb490a6e521d25d3522372108303e234a3eb5a95aff3e75c"
    assert tuple(manifest["selected_plan_instance_ids"]) == TASK_2_PLAN_INSTANCE_IDS
    assert tuple(item["plan_instance_id"] for item in manifest["objects"]) == TASK_2_PLAN_INSTANCE_IDS
    assert manifest["object_count"] == len(TASK_2_PLAN_INSTANCE_IDS) == 5
    assert manifest["identity_authority"] == "approved_plan_instance_id"
    assert manifest["detection_role"] == "bounded_segmentation_observation_only"
    assert manifest["fuzzy_matching_used"] is False
    assert manifest["list_index_identity_used"] is False
    assert all(item["observation_authority"] is False for item in manifest["objects"])
    assert all(
        item["detection_object_id"] != item["plan_instance_id"]
        for item in manifest["objects"]
    )
    assert "8c6119a5-f7b9-4eca-a30e-cb039aad9c71" in manifest["selected_plan_instance_ids"]
    assert hashlib.sha256(TASK_2_SELECTED_MANIFEST.read_bytes()).hexdigest() == source_hash


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[
        __import__("hypothesis").HealthCheck.function_scoped_fixture,
        __import__("hypothesis").HealthCheck.filter_too_much,
    ],
)
@given(order=st.permutations(tuple(range(len(TASK_2_PLAN_INSTANCE_IDS)))).filter(
    lambda order: tuple(order) != tuple(range(len(TASK_2_PLAN_INSTANCE_IDS)))
))
def test_property_2_load_selected_manifest_rejects_generated_plan_order_drift(
    tmp_path: Path,
    order: tuple[int, ...],
) -> None:
    """Property 2: content-hashed object order cannot drift from Plan order.

    **Validates: Requirements 2.7, 2.8, 2.9, 3.4, 3.5, 3.6, 3.14**
    """
    source_bytes = TASK_2_SELECTED_MANIFEST.read_bytes()
    manifest = json.loads(source_bytes)
    manifest["objects"] = [manifest["objects"][index] for index in order]
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256")
    manifest["manifest_sha256"] = _manifest_digest(unsigned)
    generated = tmp_path / "generated-order-drift.json"
    generated.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="selected Plan identity order or set drifted"):
        load_selected_manifest(generated)
    assert TASK_2_SELECTED_MANIFEST.read_bytes() == source_bytes
