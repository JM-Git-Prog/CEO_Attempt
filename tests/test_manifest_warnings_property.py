"""Property-based tests for warnings recorded in manifest (Property 3).

**Validates: Requirements 2.5**

Property 3: Warnings Recorded in Manifest
- For any plan accepted under MVP tolerance with warnings, verify every warning
  appears in the manifest's plan_validation_warnings field.
- Verify warning structure is preserved (all 4 fields present and equal).
- Verify propagation through create_terminal_manifest().
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from hypothesis import assume, given, settings, strategies as st

from src.compiler_manifest import (
    CanonicalDocument,
    CompilerVersions,
    ManifestBinding,
    create_prepared_manifest,
    create_terminal_manifest,
    manifest_hash,
)
from src.floor_plan.models import FloorPlan, PlanValidationReport
from src.floor_plan.validator import validate_floor_plan


# ---------------------------------------------------------------------------
# Hypothesis strategies (reused from test_mvp_tolerance_property.py)
# ---------------------------------------------------------------------------

room_width_st = st.floats(min_value=4.0, max_value=20.0, allow_nan=False, allow_infinity=False)
room_depth_st = st.floats(min_value=4.0, max_value=20.0, allow_nan=False, allow_infinity=False)
room_height_st = st.floats(min_value=2.5, max_value=6.0, allow_nan=False, allow_infinity=False)

item_width_st = st.floats(min_value=0.3, max_value=2.0, allow_nan=False, allow_infinity=False)
item_depth_st = st.floats(min_value=0.3, max_value=2.0, allow_nan=False, allow_infinity=False)
item_height_st = st.floats(min_value=0.3, max_value=2.5, allow_nan=False, allow_infinity=False)

# Small controlled overlap: > 0.03m (geometry tolerance) and ≤ 0.1m (MVP threshold)
overlap_amount_st = st.floats(min_value=0.04, max_value=0.09, allow_nan=False, allow_infinity=False)


def _make_camera(room_width: float, room_depth: float) -> dict:
    """Create a camera safely within room bounds."""
    return {
        "x": room_width * 0.3,
        "y": 1.6,
        "z": -(room_depth * 0.3),
        "target_x": 0.0,
        "target_y": 1.1,
        "target_z": 0.0,
        "fov_deg": 55.0,
    }


def _make_item(item_id: str, x: float, z: float, width: float, depth: float,
               height: float = 1.0, clearance_m: float = 0.0) -> dict:
    """Create an item dict for FloorPlan construction."""
    return {
        "id": item_id,
        "name": item_id.replace("_", " ").title(),
        "category": "furniture",
        "mount": "floor",
        "x": x,
        "z": z,
        "width": width,
        "depth": depth,
        "height": height,
        "elevation": 0.0,
        "rotation_deg": 0.0,
        "fixed": False,
        "clearance_m": clearance_m,
        "description": "",
    }


# ---------------------------------------------------------------------------
# Helpers: minimal valid ManifestBinding and CompilerVersions
# ---------------------------------------------------------------------------


def _make_binding() -> ManifestBinding:
    """Create a minimal valid ManifestBinding for testing."""
    session_id = f"test-session-{uuid.uuid4().hex[:8]}"
    profile_id = "mvp-test-profile"
    profile_doc = CanonicalDocument.from_value({"id": profile_id, "version": "1.0"})

    contract_value = {"schema_version": "1.0.0", "objects": [], "room": {}}
    contract_doc = CanonicalDocument.from_value(contract_value)

    # Generate deterministic hashes for the binding fields
    dummy_hash = hashlib.sha256(b"dummy-content").hexdigest()

    return ManifestBinding(
        session_id=session_id,
        interface_version=11,
        workflow_profile_id=profile_id,
        workflow_profile=profile_doc,
        world_contract_version="1.0.0",
        world_contract_hash=contract_doc.sha256,
        world_contract=contract_doc,
        plan_revision=0,
        plan_hash=dummy_hash,
        camera_contract_id="camera-test",
        camera_contract_hash=dummy_hash,
        compiler_script_hash=dummy_hash,
        command_log_hash=dummy_hash,
    )


def _make_compiler_versions() -> CompilerVersions:
    """Create minimal valid CompilerVersions for testing."""
    return CompilerVersions(
        product="UPBGE",
        product_version="0.36.1",
        blender_version="3.6.0",
        python_version="3.11.0",
        compiler_version="1.0.0",
        runtime_capable=True,
    )


# ---------------------------------------------------------------------------
# Property 3: Warnings Recorded in Manifest
# ---------------------------------------------------------------------------


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    item_w=item_width_st,
    item_d=item_depth_st,
    item_h=item_height_st,
    overlap=overlap_amount_st,
)
@settings(max_examples=200)
def test_property_3_warnings_recorded_in_prepared_manifest(
    room_w: float,
    room_d: float,
    room_h: float,
    item_w: float,
    item_d: float,
    item_h: float,
    overlap: float,
):
    """Property 3: Every tolerance warning from validation appears in the PreparedManifest.

    **Validates: Requirements 2.5**

    Strategy: Generate a floor plan with a controlled overlap that produces
    tolerance_warnings. Then pass those warnings to create_prepared_manifest()
    and verify they all appear in the manifest's plan_validation_warnings field.
    """
    # Place two items with controlled overlap (same pattern as Property 2a)
    distance = item_w - overlap
    left_x = -(distance / 2)
    right_x = distance / 2

    half_room_w = room_w / 2
    half_room_d = room_d / 2
    margin = 0.05

    left_edge = abs(left_x) + item_w / 2
    right_edge = abs(right_x) + item_w / 2
    depth_edge = item_d / 2

    assume(left_edge < half_room_w - margin)
    assume(right_edge < half_room_w - margin)
    assume(depth_edge < half_room_d - margin)

    plan = FloorPlan.model_validate({
        "name": "Property 3 manifest warnings test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("item_a", left_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
            _make_item("item_b", right_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # Only proceed if the plan was accepted with warnings
    assume(report.valid)
    assume(len(report.tolerance_warnings) > 0)

    # Create the prepared manifest with the validation warnings
    binding = _make_binding()
    compiler = _make_compiler_versions()
    config = CanonicalDocument.from_value({"mode": "mvp", "tolerance": "mvp"})
    input_bytes = len(binding.world_contract.canonical_json.encode("utf-8"))

    prepared = create_prepared_manifest(
        compilation_id=f"test-{uuid.uuid4().hex[:12]}",
        binding=binding,
        compiler=compiler,
        configuration=config,
        input_bytes=input_bytes,
        plan_validation_warnings=report.tolerance_warnings,
    )

    # PROPERTY: Every warning from validation appears in the manifest
    assert len(prepared.plan_validation_warnings) == len(report.tolerance_warnings), (
        f"Expected {len(report.tolerance_warnings)} warnings in manifest, "
        f"got {len(prepared.plan_validation_warnings)}"
    )

    for i, warning in enumerate(report.tolerance_warnings):
        manifest_warning = prepared.plan_validation_warnings[i]

        # All 4 fields must be present and equal
        assert "warning_type" in manifest_warning, (
            f"Warning {i} missing 'warning_type' in manifest"
        )
        assert "affected_id" in manifest_warning, (
            f"Warning {i} missing 'affected_id' in manifest"
        )
        assert "measured_deviation" in manifest_warning, (
            f"Warning {i} missing 'measured_deviation' in manifest"
        )
        assert "threshold" in manifest_warning, (
            f"Warning {i} missing 'threshold' in manifest"
        )

        assert manifest_warning["warning_type"] == warning["warning_type"], (
            f"Warning {i} type mismatch: manifest={manifest_warning['warning_type']} "
            f"vs validation={warning['warning_type']}"
        )
        assert manifest_warning["affected_id"] == warning["affected_id"], (
            f"Warning {i} affected_id mismatch: manifest={manifest_warning['affected_id']} "
            f"vs validation={warning['affected_id']}"
        )
        assert manifest_warning["measured_deviation"] == warning["measured_deviation"], (
            f"Warning {i} measured_deviation mismatch: "
            f"manifest={manifest_warning['measured_deviation']} "
            f"vs validation={warning['measured_deviation']}"
        )
        assert manifest_warning["threshold"] == warning["threshold"], (
            f"Warning {i} threshold mismatch: manifest={manifest_warning['threshold']} "
            f"vs validation={warning['threshold']}"
        )


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    item_w=item_width_st,
    item_d=item_depth_st,
    item_h=item_height_st,
    overlap=overlap_amount_st,
)
@settings(max_examples=200)
def test_property_3_warnings_propagated_to_terminal_manifest(
    room_w: float,
    room_d: float,
    room_h: float,
    item_w: float,
    item_d: float,
    item_h: float,
    overlap: float,
):
    """Property 3: Warnings propagate from PreparedManifest through TerminalManifest.

    **Validates: Requirements 2.5**

    Strategy: Create a prepared manifest with tolerance warnings, then create a
    terminal manifest from it. Verify all warnings survive the propagation.
    """
    # Place two items with controlled overlap
    distance = item_w - overlap
    left_x = -(distance / 2)
    right_x = distance / 2

    half_room_w = room_w / 2
    half_room_d = room_d / 2
    margin = 0.05

    left_edge = abs(left_x) + item_w / 2
    right_edge = abs(right_x) + item_w / 2
    depth_edge = item_d / 2

    assume(left_edge < half_room_w - margin)
    assume(right_edge < half_room_w - margin)
    assume(depth_edge < half_room_d - margin)

    plan = FloorPlan.model_validate({
        "name": "Property 3 terminal manifest test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("item_a", left_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
            _make_item("item_b", right_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    assume(report.valid)
    assume(len(report.tolerance_warnings) > 0)

    # Create prepared manifest
    binding = _make_binding()
    compiler = _make_compiler_versions()
    config = CanonicalDocument.from_value({"mode": "mvp", "tolerance": "mvp"})
    input_bytes = len(binding.world_contract.canonical_json.encode("utf-8"))

    prepared = create_prepared_manifest(
        compilation_id=f"test-{uuid.uuid4().hex[:12]}",
        binding=binding,
        compiler=compiler,
        configuration=config,
        input_bytes=input_bytes,
        plan_validation_warnings=report.tolerance_warnings,
    )

    # Create terminal manifest from the prepared manifest
    terminal = create_terminal_manifest(
        prepared,
        status="completed",
    )

    # PROPERTY: Every warning from the prepared manifest appears in the terminal manifest
    assert len(terminal.plan_validation_warnings) == len(prepared.plan_validation_warnings), (
        f"Expected {len(prepared.plan_validation_warnings)} warnings in terminal manifest, "
        f"got {len(terminal.plan_validation_warnings)}"
    )

    for i, prep_warning in enumerate(prepared.plan_validation_warnings):
        term_warning = terminal.plan_validation_warnings[i]

        # All 4 fields present and equal between prepared and terminal
        assert term_warning["warning_type"] == prep_warning["warning_type"], (
            f"Warning {i} type mismatch: terminal={term_warning['warning_type']} "
            f"vs prepared={prep_warning['warning_type']}"
        )
        assert term_warning["affected_id"] == prep_warning["affected_id"], (
            f"Warning {i} affected_id mismatch: terminal={term_warning['affected_id']} "
            f"vs prepared={prep_warning['affected_id']}"
        )
        assert term_warning["measured_deviation"] == prep_warning["measured_deviation"], (
            f"Warning {i} measured_deviation mismatch: "
            f"terminal={term_warning['measured_deviation']} "
            f"vs prepared={prep_warning['measured_deviation']}"
        )
        assert term_warning["threshold"] == prep_warning["threshold"], (
            f"Warning {i} threshold mismatch: terminal={term_warning['threshold']} "
            f"vs prepared={prep_warning['threshold']}"
        )

    # Also verify against the original validation warnings
    for i, original_warning in enumerate(report.tolerance_warnings):
        term_warning = terminal.plan_validation_warnings[i]
        assert term_warning == original_warning, (
            f"Warning {i} not preserved through full chain: "
            f"original={original_warning} vs terminal={term_warning}"
        )
