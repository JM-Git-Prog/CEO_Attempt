"""Lightweight parity gate: CompilerPlan expected IDs vs scene inventory JSON.

This module provides a focused check that verifies the scene inventory produced
by the UPBGE sidecar contains exactly the expected object IDs from the CompilerPlan.
It is intentionally simpler than the full structural parity system in parity_gates.py —
it answers one question: "Did the compiler produce all the objects we asked for, and
only those objects?"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParityResult:
    """Result of a parity gate check between CompilerPlan expected IDs and scene inventory."""

    passed: bool
    missing_ids: tuple[str, ...]  # IDs in CompilerPlan but not in inventory
    extra_ids: tuple[str, ...]  # IDs in inventory but not in CompilerPlan
    expected_count: int
    actual_count: int
    reason_code: str  # "parity_ok", "missing_ids", "count_mismatch", "missing_ids_and_count_mismatch", "inventory_not_found", "inventory_parse_error"
    diagnostic: str


def check_parity(
    expected_ids: set[str],
    inventory_path: Path,
) -> ParityResult:
    """Verify scene inventory matches expected IDs from CompilerPlan.

    Args:
        expected_ids: Set of object IDs the CompilerPlan expects in the scene.
        inventory_path: Path to the scene inventory JSON file produced by the sidecar.

    The inventory JSON is expected to have a structure like:
        {"objects": [{"id": "obj_001", ...}, {"id": "obj_002", ...}]}
    or a flat list:
        [{"id": "obj_001", ...}, {"id": "obj_002", ...}]

    Returns ParityResult with pass/fail and discrepancy details.
    """
    # Edge case: file doesn't exist
    if not inventory_path.exists():
        return ParityResult(
            passed=False,
            missing_ids=tuple(sorted(expected_ids)),
            extra_ids=(),
            expected_count=len(expected_ids),
            actual_count=0,
            reason_code="inventory_not_found",
            diagnostic=f"Inventory file not found: {inventory_path}",
        )

    # Load and parse JSON
    try:
        raw_text = inventory_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        return ParityResult(
            passed=False,
            missing_ids=tuple(sorted(expected_ids)),
            extra_ids=(),
            expected_count=len(expected_ids),
            actual_count=0,
            reason_code="inventory_parse_error",
            diagnostic=f"Failed to parse inventory JSON: {exc}",
        )

    # Extract actual IDs from inventory
    # Handle both {"objects": [...]} format and flat list [{"id": ...}, ...]
    actual_ids: set[str] = set()
    try:
        if isinstance(data, dict) and "objects" in data:
            objects = data["objects"]
        elif isinstance(data, list):
            objects = data
        else:
            return ParityResult(
                passed=False,
                missing_ids=tuple(sorted(expected_ids)),
                extra_ids=(),
                expected_count=len(expected_ids),
                actual_count=0,
                reason_code="inventory_parse_error",
                diagnostic="Inventory JSON must be a dict with 'objects' key or a list of objects",
            )

        for obj in objects:
            if isinstance(obj, dict) and "id" in obj:
                actual_ids.add(obj["id"])
    except (TypeError, KeyError) as exc:
        return ParityResult(
            passed=False,
            missing_ids=tuple(sorted(expected_ids)),
            extra_ids=(),
            expected_count=len(expected_ids),
            actual_count=0,
            reason_code="inventory_parse_error",
            diagnostic=f"Failed to extract IDs from inventory: {exc}",
        )

    # Compute discrepancies
    missing_ids = expected_ids - actual_ids
    extra_ids = actual_ids - expected_ids
    expected_count = len(expected_ids)
    actual_count = len(actual_ids)

    # Determine pass/fail and reason code
    # Pass iff expected_ids ⊆ actual_ids AND |actual_ids| == |expected_ids|
    # (i.e., the sets must be exactly equal)
    has_missing = len(missing_ids) > 0
    has_count_mismatch = expected_count != actual_count

    if not has_missing and not has_count_mismatch:
        return ParityResult(
            passed=True,
            missing_ids=(),
            extra_ids=(),
            expected_count=expected_count,
            actual_count=actual_count,
            reason_code="parity_ok",
            diagnostic="All expected IDs present and counts match.",
        )

    # Determine reason code for failure
    if has_missing and has_count_mismatch:
        reason_code = "missing_ids_and_count_mismatch"
    elif has_missing:
        reason_code = "missing_ids"
    else:
        reason_code = "count_mismatch"

    # Build diagnostic message listing discrepancies
    parts: list[str] = []
    if has_missing:
        parts.append(f"Missing IDs ({len(missing_ids)}): {sorted(missing_ids)}")
    if extra_ids:
        parts.append(f"Extra IDs ({len(extra_ids)}): {sorted(extra_ids)}")
    if has_count_mismatch:
        parts.append(f"Count mismatch: expected {expected_count}, got {actual_count}")

    return ParityResult(
        passed=False,
        missing_ids=tuple(sorted(missing_ids)),
        extra_ids=tuple(sorted(extra_ids)),
        expected_count=expected_count,
        actual_count=actual_count,
        reason_code=reason_code,
        diagnostic=" | ".join(parts),
    )
