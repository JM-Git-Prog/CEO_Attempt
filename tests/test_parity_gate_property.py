"""Property-based tests for parity gate ID verification (Property 10).

**Validates: Requirements 8.1, 8.2**

Property 10: Parity Gate ID Verification
- For any CompilerPlan with expected IDs E and inventory with actual IDs A,
  parity passes iff E ⊆ A AND |A| == |E|; failure lists E \\ A (missing IDs).
- Since IDs are unique, E ⊆ A AND |A| == |E| simplifies to E == A as sets.
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings, assume
from hypothesis import strategies as st

import src.assembler.upbge_compile as engine_compiler
from src.parity_gates import validate_upbge_inventory, StructuralParityReport
from src.upbge_compiler import build_compiler_plan
from tests.upbge_test_support import build_test_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_baseline_inventory(tmp_path: Path):
    """Write a valid inventory from the test contract and return (contract, path, payload)."""
    contract = build_test_contract(interactions=(
        {"id": "grab-table", "kind": "grab", "subject_id": "table_1"},
    ))
    plan = build_compiler_plan(contract)
    plan_payload = plan.to_dict()
    objects = []
    for spec in (*plan.room_geometry, *plan.instances):
        payload = dict(spec.__dict__)
        payload["compiled_dimensions_upbge"] = [
            dimension * scale
            for dimension, scale in zip(spec.dimensions_upbge, spec.scale_upbge)
        ]
        objects.append(payload)
    engine_compiler._write_inventory(
        tmp_path, contract.model_dump(mode="json"), plan_payload, objects,
    )
    inventory_path = tmp_path / "scene_inventory.json"
    inventory_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    return contract, inventory_path, inventory_payload


def _get_collection_ids(payload: dict, label: str) -> list[str]:
    """Extract the stable_id values from a collection in the inventory payload."""
    return [item["stable_id"] for item in payload.get(label, [])]


def _set_collection_ids(payload: dict, label: str, ids: list[str]) -> dict:
    """Return a modified payload where the collection has items with the given IDs.

    Duplicates existing items to fill new IDs, removes items to match the target list.
    """
    items = payload.get(label, [])
    if not items:
        return payload

    result_items = []
    for target_id in ids:
        # Find existing item with this ID, or clone the first item
        existing = next((item for item in items if item.get("stable_id") == target_id), None)
        if existing:
            result_items.append(existing)
        else:
            # Clone the first item with the new ID
            clone = dict(items[0])
            clone["stable_id"] = target_id
            result_items.append(clone)

    modified = dict(payload)
    modified[label] = result_items
    return modified


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a set of IDs to remove from the baseline (simulating missing items)
remove_indices_st = st.lists(
    st.integers(min_value=0, max_value=20),
    min_size=0,
    max_size=5,
    unique=True,
)

# Generate extra IDs to add to the inventory (simulating extra items)
extra_ids_st = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), min_codepoint=97, max_codepoint=122,
        ),
        min_size=3,
        max_size=12,
    ),
    min_size=0,
    max_size=5,
    unique=True,
)


# ---------------------------------------------------------------------------
# Property 10: Parity Gate ID Verification
# ---------------------------------------------------------------------------


@given(
    remove_indices=remove_indices_st,
    extra_ids=extra_ids_st,
)
@settings(max_examples=100, deadline=None)
def test_property_10_parity_gate_id_verification(
    tmp_path_factory,
    remove_indices: list[int],
    extra_ids: list[str],
):
    """Property 10: Parity passes iff E == A as sets; failure lists E \\ A.

    **Validates: Requirements 8.1, 8.2**

    For any inventory with actual IDs A and expected IDs E (from the contract):
    - Parity passes iff E ⊆ A AND |A| == |E| (i.e., E == A as sets)
    - On failure, the issues contain the missing IDs (E \\ A)
    """
    tmp_path = tmp_path_factory.mktemp("parity")
    contract, inventory_path, payload = _write_baseline_inventory(tmp_path)

    # Use "objects" collection as the target for ID manipulation
    label = "objects"
    expected_ids = sorted(item.id for item in contract.instances)
    actual_ids = list(expected_ids)  # Start with a perfect match

    # Remove some IDs from the actual inventory (bounded by collection size)
    valid_remove = [i for i in remove_indices if i < len(actual_ids)]
    removed_ids = set()
    for idx in sorted(valid_remove, reverse=True):
        removed_ids.add(actual_ids[idx])
        actual_ids.pop(idx)

    # Add extra IDs to the actual inventory (ensure no collision with expected)
    added_ids = [eid for eid in extra_ids if eid not in set(expected_ids)]
    actual_ids.extend(added_ids)

    # Modify the inventory payload
    modified_payload = _set_collection_ids(payload, label, actual_ids)
    inventory_path.write_text(
        json.dumps(modified_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    # Run parity validation
    report = validate_upbge_inventory(contract, inventory_path)

    # Compute expected result
    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    ids_match = (expected_set <= actual_set) and (len(actual_set) == len(expected_set))
    # ids_match is equivalent to expected_set == actual_set (since both are sets)

    if ids_match:
        # No ID-related issues should appear for this collection
        id_issues = [
            issue for issue in report.issues
            if issue.path in (f"{label}.count", f"{label}.ids")
        ]
        assert not id_issues, (
            f"Expected no ID issues when E == A, but got: {id_issues}"
        )
    else:
        # There should be ID-related issues
        id_issues = [
            issue for issue in report.issues
            if issue.path in (f"{label}.count", f"{label}.ids")
        ]
        assert id_issues, (
            f"Expected ID issues when E != A "
            f"(expected={sorted(expected_set)}, actual={sorted(actual_set)}), "
            f"but got no issues"
        )

        # Verify missing IDs (E \ A) are detectable from issues
        missing_ids = expected_set - actual_set
        if missing_ids:
            # The ids mismatch issue should reflect the missing IDs:
            # expected has sorted(expected_ids), actual has sorted(actual_ids without missing)
            ids_issue = next(
                (issue for issue in id_issues if issue.path == f"{label}.ids"),
                None,
            )
            if ids_issue:
                # The expected tuple contains the full expected set
                expected_in_issue = set(ids_issue.expected) if ids_issue.expected else set()
                actual_in_issue = set(ids_issue.actual) if ids_issue.actual else set()
                # Missing IDs = expected - actual in the issue
                reported_missing = expected_in_issue - actual_in_issue
                assert missing_ids <= reported_missing, (
                    f"Missing IDs {missing_ids} should be in reported difference "
                    f"{reported_missing}"
                )
