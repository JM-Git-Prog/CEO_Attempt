"""Unit tests for the lightweight parity gate (src/parity_gate.py).

Covers:
- Perfect match → pass
- Missing IDs → fail with correct missing list
- Extra IDs → fail (count mismatch)
- Missing + extra → fail
- Inventory file not found → fail
- Malformed JSON → fail
- Empty sets → pass
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.parity_gate import ParityResult, check_parity


class TestParityGatePerfectMatch:
    """Inventory exactly matches expected IDs."""

    def test_dict_format(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b", "c"}, inventory)
        assert result.passed is True
        assert result.missing_ids == ()
        assert result.extra_ids == ()
        assert result.expected_count == 3
        assert result.actual_count == 3
        assert result.reason_code == "parity_ok"

    def test_flat_list_format(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps([{"id": "x"}, {"id": "y"}]),
            encoding="utf-8",
        )
        result = check_parity({"x", "y"}, inventory)
        assert result.passed is True
        assert result.reason_code == "parity_ok"
        assert result.expected_count == 2
        assert result.actual_count == 2


class TestParityGateMissingIDs:
    """Inventory is missing some expected IDs."""

    def test_some_missing(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b", "c"}, inventory)
        assert result.passed is False
        assert result.missing_ids == ("b", "c")
        assert result.expected_count == 3
        assert result.actual_count == 1
        assert result.reason_code == "missing_ids_and_count_mismatch"

    def test_all_missing(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(json.dumps({"objects": []}), encoding="utf-8")
        result = check_parity({"a", "b"}, inventory)
        assert result.passed is False
        assert result.missing_ids == ("a", "b")
        assert result.actual_count == 0
        assert result.reason_code == "missing_ids_and_count_mismatch"


class TestParityGateExtraIDs:
    """Inventory has extra IDs not in the expected set — fails due to count mismatch."""

    def test_extra_ids_only(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}, {"id": "b"}, {"id": "extra"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b"}, inventory)
        assert result.passed is False
        assert result.missing_ids == ()
        assert result.extra_ids == ("extra",)
        assert result.expected_count == 2
        assert result.actual_count == 3
        assert result.reason_code == "count_mismatch"


class TestParityGateMissingAndExtra:
    """Both missing and extra IDs present — hardest failure mode."""

    def test_mixed_discrepancy(self, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}, {"id": "extra1"}, {"id": "extra2"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b"}, inventory)
        assert result.passed is False
        assert result.missing_ids == ("b",)
        assert result.extra_ids == ("extra1", "extra2")
        assert result.expected_count == 2
        assert result.actual_count == 3
        assert result.reason_code == "missing_ids_and_count_mismatch"


class TestParityGateFileNotFound:
    """Inventory file does not exist."""

    def test_missing_file(self, tmp_path: Path) -> None:
        inventory = tmp_path / "does_not_exist.json"
        result = check_parity({"a", "b"}, inventory)
        assert result.passed is False
        assert result.reason_code == "inventory_not_found"
        assert result.missing_ids == ("a", "b")
        assert result.actual_count == 0
        assert "not found" in result.diagnostic.lower()


class TestParityGateMalformedJSON:
    """Inventory file contains invalid JSON."""

    def test_invalid_json(self, tmp_path: Path) -> None:
        inventory = tmp_path / "bad.json"
        inventory.write_text("{not valid json!!!", encoding="utf-8")
        result = check_parity({"a"}, inventory)
        assert result.passed is False
        assert result.reason_code == "inventory_parse_error"
        assert "parse" in result.diagnostic.lower() or "json" in result.diagnostic.lower()

    def test_wrong_structure(self, tmp_path: Path) -> None:
        """JSON is valid but not an object with 'objects' or a list."""
        inventory = tmp_path / "wrong.json"
        inventory.write_text(json.dumps("just a string"), encoding="utf-8")
        result = check_parity({"a"}, inventory)
        assert result.passed is False
        assert result.reason_code == "inventory_parse_error"


class TestParityGateEmptySets:
    """Both expected and actual are empty — should pass."""

    def test_empty_expected_empty_inventory(self, tmp_path: Path) -> None:
        inventory = tmp_path / "empty.json"
        inventory.write_text(json.dumps({"objects": []}), encoding="utf-8")
        result = check_parity(set(), inventory)
        assert result.passed is True
        assert result.reason_code == "parity_ok"
        assert result.expected_count == 0
        assert result.actual_count == 0

    def test_empty_flat_list(self, tmp_path: Path) -> None:
        inventory = tmp_path / "empty_list.json"
        inventory.write_text(json.dumps([]), encoding="utf-8")
        result = check_parity(set(), inventory)
        assert result.passed is True
        assert result.reason_code == "parity_ok"


class TestParityGateEdgeCases:
    """Additional edge cases for robustness."""

    def test_objects_without_id_field_ignored(self, tmp_path: Path) -> None:
        """Objects missing 'id' field are silently skipped."""
        inventory = tmp_path / "partial.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}, {"name": "no_id"}, {"id": "b"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b"}, inventory)
        assert result.passed is True
        assert result.reason_code == "parity_ok"

    def test_dict_with_extra_fields(self, tmp_path: Path) -> None:
        """Extra fields in inventory objects don't affect the check."""
        inventory = tmp_path / "extra_fields.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "obj_1", "mesh": "cube", "position": [0, 0, 0]}]}),
            encoding="utf-8",
        )
        result = check_parity({"obj_1"}, inventory)
        assert result.passed is True
        assert result.reason_code == "parity_ok"

    def test_diagnostic_lists_discrepancies(self, tmp_path: Path) -> None:
        """Diagnostic string includes meaningful discrepancy info."""
        inventory = tmp_path / "inventory.json"
        inventory.write_text(
            json.dumps({"objects": [{"id": "a"}]}),
            encoding="utf-8",
        )
        result = check_parity({"a", "b", "c"}, inventory)
        assert "b" in result.diagnostic
        assert "c" in result.diagnostic
