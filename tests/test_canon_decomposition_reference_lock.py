"""Focused Task 3.1 tests for the Golden Room immutable reference lock."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import canon_decomposition_upbge_proof as proof
import validate_canon_decomposition_upbge_proof as validator


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(role: str, path: Path) -> dict[str, object]:
    return {"role": role, "path": path, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def test_exact_canon_and_empty_twin_bindings_are_immutable() -> None:
    """The exact design paths, byte count, and hashes are table-bound.

    **Validates: Requirements 2.16, 3.3**
    """
    assert proof.CANON_PATH == Path(
        r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png"
    )
    assert proof.EXPECTED_HASHES[proof.CANON_PATH] == "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6"
    assert proof.EMPTY_TWIN_PATH == Path(
        r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-02-twin_00002_.png"
    )
    assert proof.EXPECTED_HASHES[proof.EMPTY_TWIN_PATH] == "2f67a5f3d3b44a4fb1eacf1ada5e57d4fbf401662358b01ccf087c4a83a59103"
    twin_spec = next(item for item in proof.REFERENCE_SPECS if item["role"] == "locked_empty_twin")
    assert twin_spec["bytes"] == 1_372_293
    assert twin_spec["sha256"] == proof.EXPECTED_HASHES[proof.EMPTY_TWIN_PATH]


def test_reference_specs_accept_only_exact_regular_unique_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact unique regular references pass without glob/latest selection.

    **Validates: Requirements 2.16**
    """
    canon = tmp_path / "canon.png"
    twin = tmp_path / "twin.png"
    canon.write_bytes(b"canon-exact")
    twin.write_bytes(b"twin-exact")
    specs = (_spec("locked_canon", canon), _spec("locked_empty_twin", twin))
    monkeypatch.setattr(proof, "EXPECTED_HASHES", {canon: _sha256(canon), twin: _sha256(twin)})
    bindings = proof.verify_reference_specs(specs)
    assert [item["role"] for item in bindings] == ["locked_canon", "locked_empty_twin"]
    assert all(item["verified"] and item["is_regular_file"] and not item["is_symlink"] for item in bindings)


@pytest.mark.parametrize("mutation", ["missing", "drift", "duplicate_role", "duplicate_path", "symlink"])
def test_reference_specs_fail_closed_for_invalid_candidates(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing, drifted, ambiguous, aliased, or symlinked references are rejected.

    **Validates: Requirements 2.16**
    """
    canon = tmp_path / "canon.png"
    twin = tmp_path / "twin.png"
    canon.write_bytes(b"canon-exact")
    twin.write_bytes(b"twin-exact")
    specs = [_spec("locked_canon", canon), _spec("locked_empty_twin", twin)]
    expected = {canon: _sha256(canon), twin: _sha256(twin)}
    if mutation == "missing":
        twin.unlink()
    elif mutation == "drift":
        twin.write_bytes(b"substituted")
    elif mutation == "duplicate_role":
        specs[1]["role"] = "locked_canon"
    elif mutation == "duplicate_path":
        specs[1]["path"] = canon
        specs[1]["bytes"] = canon.stat().st_size
        specs[1]["sha256"] = _sha256(canon)
    elif mutation == "symlink":
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == twin or original_is_symlink(self))
    monkeypatch.setattr(proof, "EXPECTED_HASHES", expected)
    with pytest.raises(proof.ReferenceLockError, match="INITIALIZE_REFERENCES"):
        proof.verify_reference_specs(specs)


def test_reference_specs_reject_filesystem_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct path spellings cannot alias the same underlying reference file.

    **Validates: Requirements 2.16**
    """
    canon = tmp_path / "canon.png"
    alias = tmp_path / "twin.png"
    canon.write_bytes(b"same-bytes")
    os.link(canon, alias)
    specs = (_spec("locked_canon", canon), _spec("locked_empty_twin", alias))
    monkeypatch.setattr(proof, "EXPECTED_HASHES", {canon: _sha256(canon), alias: _sha256(alias)})
    with pytest.raises(proof.ReferenceLockError, match="aliases are forbidden"):
        proof.verify_reference_specs(specs)


def _valid_decomposition() -> dict[str, object]:
    return {
        "schema": "unified-world-pipeline.canon-decomposition-pack.v1",
        "inventory": {"item_count": 1, "keys": ["chair"]},
        "items": [{
            "key": "chair",
            "authority": "appearance_evidence_only_not_spatial_authority",
            "confidence": 0.95,
        }],
        "source": {"comfy_execution": {
            "available": True,
            "requested": True,
            "fallback": False,
            "source_hash_verified": True,
            "execution": "EXECUTED",
        }},
    }


def test_decomposition_authority_rejects_skipped_or_uncertain_isolation() -> None:
    """Skipped/fallback isolation evidence cannot authorize the inventory.

    **Validates: Requirements 2.8, 2.16, 3.5**
    """
    pack = _valid_decomposition()
    observed = proof.validate_decomposition_authority(pack)
    assert observed["item_count"] == 1
    for field, value in (("available", False), ("requested", False), ("fallback", True), ("source_hash_verified", False)):
        candidate = copy.deepcopy(pack)
        candidate["source"]["comfy_execution"][field] = value  # type: ignore[index]
        with pytest.raises(proof.ReferenceLockError, match="skipped or uncertain"):
            proof.validate_decomposition_authority(candidate)


def test_failure_checkpoint_is_hash_bound_and_independently_reproduced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed gate writes no reference/calibration/candidate/score and skips 3.2–3.11.

    **Validates: Requirements 2.9, 2.16, 2.30**
    """
    error = proof.ReferenceLockError("INITIALIZE_REFERENCES: exact test blocker")
    checkpoint = proof.write_initialize_references_failure(tmp_path / "checkpoint.json", error)
    monkeypatch.setattr(proof, "build_reference_lock", lambda: (_ for _ in ()).throw(error))
    result = validator.validate_reference_initialization(tmp_path)
    assert result["result"] == "BLOCKED"
    assert result["first_failure"] == str(error)
    assert checkpoint["skipped_subtasks"] == [f"3.{index}" for index in range(2, 12)]
    assert not (tmp_path / "references.json").exists()
    assert not any((tmp_path / name).exists() for name in ("calibration-manifest.json", "candidate.png", "score.json"))


def test_independent_validator_rejects_checkpoint_tampering(tmp_path: Path) -> None:
    """Independent replay rejects a modified INITIALIZE_REFERENCES checkpoint.

    **Validates: Requirements 2.9, 2.16**
    """
    path = tmp_path / "checkpoint.json"
    proof.write_initialize_references_failure(
        path, proof.ReferenceLockError("INITIALIZE_REFERENCES: exact test blocker")
    )
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["candidate_written"] = True
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(AssertionError, match="checkpoint hash mismatch"):
        validator.validate_reference_initialization(tmp_path)


def test_asset_provenance_rejects_placeholder_and_binds_real_source(tmp_path: Path) -> None:
    """Approved normalized/source bytes pass, while placeholder provenance fails.

    **Validates: Requirements 2.11, 2.16**
    """
    normalized = tmp_path / "meshes" / "asset-id" / "normalized" / "asset.glb"
    source = tmp_path / "meshes" / "asset-id" / "source" / "asset.glb"
    normalized.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    normalized.write_bytes(b"normalized-real-mesh")
    source.write_bytes(b"source-real-mesh")
    expected = {"normalized": _sha256(normalized), "source": _sha256(source)}
    provenance = {
        "generator": "hunyuan3d_v2.1",
        "mesh_path": str(normalized),
        "asset_id": expected["normalized"],
    }
    record = proof.validate_asset_provenance("asset-id", provenance, expected)
    assert record["generator"] == "hunyuan3d_v2.1"
    assert record["normalized"]["verified"] and record["source"]["verified"]

    placeholder = dict(provenance, generator="UnifiedPlaceholderGenerator")
    with pytest.raises(proof.ReferenceLockError, match="placeholder or missing provenance"):
        proof.validate_asset_provenance("asset-id", placeholder, expected)
