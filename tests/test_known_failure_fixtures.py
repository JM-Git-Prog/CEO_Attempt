from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "known_failures"
EXPECTED_TYPES = {
    "duplicate_counts", "missing_ceiling_fixtures", "blocked_openings",
    "camera_drift", "mismatched_transforms",
}
FIXTURES = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json"))]


def _overlap(left: dict, right: dict) -> bool:
    return all(left["min"][axis] < right["max"][axis] and right["min"][axis] < left["max"][axis] for axis in range(3))


def _detect(fixture: dict) -> bool:
    authority, observed, oracle = fixture["authority"], fixture["observed"], fixture["oracle"]
    match fixture["defect_type"]:
        case "duplicate_counts":
            counts = Counter(entry["source_id"] for entry in observed["instances"])
            return observed["observed_count"] != authority["expected_count"] and sorted(key for key, count in counts.items() if count > 1) == oracle["duplicate_source_ids"]
        case "missing_ceiling_fixtures":
            fixtures = sorted(set(authority["ceiling_fixture_ids"]) - set(observed["ceiling_fixture_ids"]))
            lights = sorted(set(authority["associated_light_ids"]) - set(observed["associated_light_ids"]))
            return fixtures == oracle["missing_fixture_ids"] and lights == oracle["missing_light_ids"]
        case "blocked_openings":
            blockers = [entry["stable_id"] for entry in observed["opaque_geometry"] if _overlap(authority["keep_clear_aabb"], entry["aabb"])]
            return authority["traversable"] and not observed["traversable"] and blockers == oracle["blocking_ids"]
        case "camera_drift":
            distances = [math.dist(point, observed["landmarks_px"][key]) for key, point in authority["landmarks_px"].items()]
            return max(distances) > oracle["max_translation_px"] and all(authority.get(key) != observed.get(key) for key in oracle["drifted_fields"])
        case "mismatched_transforms":
            mapped = [authority["position"][0], authority["position"][2], authority["position"][1]]
            error = max(abs(a - b) for a, b in zip(mapped, observed["position"], strict=True))
            return mapped == fixture["adapter_contract"]["expected_position"] and error > fixture["adapter_contract"]["tolerance_m"] and error == oracle["maximum_axis_error_m"]
    return False


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_fixture_catalog_is_complete_versioned_and_unique():
    assert len(FIXTURES) == 5
    assert {fixture["defect_type"] for fixture in FIXTURES} == EXPECTED_TYPES
    assert len({fixture["fixture_id"] for fixture in FIXTURES}) == len(FIXTURES)
    for fixture in FIXTURES:
        assert fixture["fixture_version"] == "known-failure/v1"
        assert fixture["requirements"] == [1, 7, 8, 9, 12]
        assert fixture["capture"]["kind"] == "synthetic-regression-seed"
        assert fixture["capture"]["data_only"] is True
        assert fixture["oracle"]["reason_code"]
        assert fixture["oracle"]["expected_detection"] is True


def test_fixtures_are_finite_data_without_executable_or_path_fields():
    forbidden = {"command", "executable", "path", "script", "source_code"}
    for fixture in FIXTURES:
        for key, value in _walk(fixture):
            assert key not in forbidden
            if isinstance(value, float):
                assert math.isfinite(value)
            if isinstance(value, str):
                assert "://" not in value and "..\\" not in value and "../" not in value


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["defect_type"])
def test_each_fixture_independently_encodes_its_declared_failure(fixture: dict):
    assert _detect(fixture), fixture["fixture_id"]
