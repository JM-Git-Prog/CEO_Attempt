"""Immutable workflow profiles and complete per-session provenance snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from PIL import Image

WORKFLOW_SCHEMA_VERSION = 1

_PROFILE_VALUES = (
    {
        "id": "v3-legacy@f982288",
        "interface_version": 3,
        "release_commit": "f982288",
        "stages": {
            "canon": {
                "conditioning": "none",
                "prompt": "concept.image_prompt",
                "provider_policy": "mock_only",
            }
        },
        "source": "git show f982288",
    },
    {
        "id": "v4-reference-full@5069761",
        "interface_version": 4,
        "release_commit": "5069761",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "concept.image_prompt",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "git show 5069761",
    },
    {
        "id": "v5-reference-partial@964da06",
        "interface_version": 5,
        "release_commit": "b929f57",
        "compatibility_fixes": ["964da06", "4ac67dd"],
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "base_prompt": "concept.image_prompt",
                "latent": "encoded_blockout",
                "sigma_schedule": "partial_after_step_4",
            }
        },
        "source": "git show 964da06",
        "status": "historical",
    },
    {
        "id": "v5-reference-full-r2",
        "interface_version": 5,
        "release_commit": None,
        "supersedes": "v5-reference-partial@964da06",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "Unreleased V5 quality probe retained for provenance",
        "status": "experimental_unreleased",
    },
    {
        "id": "v6-reference-full-r1",
        "interface_version": 6,
        "release_commit": None,
        "supersedes": "v5-reference-partial@964da06",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "V6 photoreal full-generation workflow",
        "status": "active",
    },
    {
        "id": "v7-reference-full-r1",
        "interface_version": 7,
        "release_commit": None,
        "supersedes": "v6-reference-full-r1",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "V7 responsive resizable interface; V6 Canon contract retained",
        "status": "active",
    },
    {
        "id": "v8-reference-full-r1",
        "interface_version": 8,
        "release_commit": None,
        "supersedes": "v7-reference-full-r1",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "V8 historical stage replay and truthful telemetry; V7 Canon contract retained",
        "status": "active",
    },
    {
        "id": "v9-camera-locked-partial-r1",
        "interface_version": 9,
        "release_commit": None,
        "supersedes": "v8-reference-full-r1",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "encoded_blockout",
                "sigma_schedule": "partial_after_step_8",
                "camera_contract": "v9-camera-1",
            }
        },
        "source": "V9 authoritative vertical-FOV camera shared by Blockout, Canon, and World",
        "status": "active",
    },
    {
        "id": "v9-camera-locked-photoreal-r2",
        "interface_version": 9,
        "release_commit": None,
        "supersedes": "v9-camera-locked-partial-r1",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "encoded_blockout",
                "sigma_schedule": "full",
                "appearance_transform": "full_photoreal_resynthesis",
                "camera_contract": "v9-camera-1",
            }
        },
        "source": "V9 camera-locked full appearance resynthesis; encoded blockout remains the geometry reference",
        "status": "active",
    },
    {
        "id": "v9-camera-locked-photoreal-r3",
        "interface_version": 9,
        "release_commit": None,
        "supersedes": "v9-camera-locked-photoreal-r2",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "encoded_blockout",
                "sigma_schedule": "full",
                "appearance_transform": "full_photoreal_resynthesis",
                "camera_contract": "v9-camera-1",
                "blockout_detail": "articulated",
            }
        },
        "source": "V9 articulated blockout: sub-part decomposition with palette-mapped flat colors for denser geometry signal",
        "status": "experimental",
    },
    {
        "id": "v10-bounded-review-r1",
        "interface_version": 10,
        "release_commit": None,
        "supersedes": "v9-camera-locked-photoreal-r3",
        "stages": {
            "plan": {
                "validation": "bounded-sat-placement-v1",
                "block_on_unresolved_geometry": True,
            },
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "encoded_blockout",
                "sigma_schedule": "partial_after_step_8",
                "appearance_transform": "full_photoreal_resynthesis",
                "camera_contract": "v10-camera-1",
                "blockout_detail": "articulated",
                "alignment_policy": {
                    "method": "bounded-camera-review-v1",
                    "aligned_min_edge_iou": 0.04,
                    "aligned_max_drift_px": 12.0,
                    "misaligned_max_drift_px": 20.0,
                    "misaligned_max_edge_iou": 0.015,
                    "max_retries": 2,
                    "manual_review_for_inconclusive": True,
                },
            },
        },
        "source": "V10 bounded geometry validation and explainable Canon alignment review",
        "status": "experimental",
    },
    {
        "id": "v11-upbge-contract-r1",
        "interface_version": 11,
        "release_commit": None,
        "supersedes": "v10-bounded-review-r1",
        "stages": {
            "plan": {
                "validation": "relationship-solver/v1",
                "placement": "explicit-semantic-relations/v1",
                "block_on_unresolved_geometry": True,
                "composition_policy": {
                    "method": "full-rotated-bounds/v1",
                    "image_width": 1024,
                    "image_height": 768,
                    "safe_margin_ratio": 0.005,
                    "minimum_inset_m": 0.001,
                    "inset_offsets_m": [-0.449, -0.4, -0.35, -0.3, -0.2, 0.0],
                    "target_x_offsets_m": [0.0, -0.5, 0.5, -1.0, -1.5, -2.0],
                    "target_y_offsets_m": [0.0, -0.3, 0.3, -0.6, 0.6, -0.9, -1.2],
                    "target_z_offsets_m": [0.0, 0.5, 1.0, 1.5, 2.0],
                    "require_openings": False,
                },
            },
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "immutable-plan-conditioning/v1",
                "latent": "encoded_blockout",
                "sigma_schedule": "partial_after_step_8",
                "appearance_transform": "full_photoreal_resynthesis",
                "camera_contract": "v11-camera-1",
                "blockout_detail": "articulated",
                "alignment_policy": {
                    "method": "bounded-camera-review-v1",
                    "aligned_min_edge_iou": 0.04,
                    "aligned_max_drift_px": 12.0,
                    "misaligned_max_drift_px": 20.0,
                    "misaligned_max_edge_iou": 0.015,
                    "max_retries": 2,
                    "manual_review_for_inconclusive": True,
                },
                "qa": "qwen2.5vl-seven-category/v1",
            },
            "world": {
                "contract": "world-contract/v1",
                "commands": "semantic-command/v1",
                "primary_adapter": "upbge",
                "fallback_adapter": "godot",
                "fallback_triggers": [
                    "unavailable", "incompatible", "timeout", "process_failure",
                    "unsupported_required_feature"
                ],
                "outputs": {
                    "render": True,
                    "blend": True,
                    "glb": True,
                    "runtime": True,
                    "godot": True,
                    "three_js": True,
                },
                "runtime_required_for_native": True,
                "qa_required": True,
                "compiler": "upbge-compiler-plan/v1",
                "runtime": "upbge-runtime/v1",
                "parity": "structural-parity-report/v1",
            },
        },
        "source": "V11 engine-neutral contract with isolated UPBGE compiler and explicit Godot fallback",
        "status": "experimental",
    },
)
_PROFILE_DOCUMENTS = MappingProxyType(
    {value["id"]: json.dumps(value, sort_keys=True) for value in _PROFILE_VALUES}
)
_ACTIVE_PROFILE_IDS = MappingProxyType(
    {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
        8: "v8-reference-full-r1",
        9: "v9-camera-locked-photoreal-r3",
        10: "v10-bounded-review-r1",
        11: "v11-upbge-contract-r1",
    }
)
_HISTORICAL_PROFILE_IDS = MappingProxyType(
    {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
        8: "v8-reference-full-r1",
        9: "v9-camera-locked-photoreal-r2",
        10: "v10-bounded-review-r1",
        11: "v11-upbge-contract-r1",
    }
)


LATEST_INTERFACE_VERSION = 11


class UnsupportedInterfaceVersion(ValueError):
    """Raised when a request names an unregistered interface version."""


def normalize_interface_version(value: int | str | None) -> int:
    if value is None or value == "":
        return LATEST_INTERFACE_VERSION
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedInterfaceVersion(f"Invalid interface version: {value!r}") from exc
    if version <= 3:
        return 3
    if version not in _ACTIVE_PROFILE_IDS:
        raise UnsupportedInterfaceVersion(
            f"Unsupported interface version {version}; supported versions are 3-{LATEST_INTERFACE_VERSION}"
        )
    return version


def profile_by_id(profile_id: str) -> dict:
    document = _PROFILE_DOCUMENTS.get(profile_id)
    if document is None:
        raise ValueError(f"Unknown workflow profile: {profile_id}")
    return json.loads(document)


def profile_for(interface_version: int) -> dict:
    return profile_by_id(_ACTIVE_PROFILE_IDS[normalize_interface_version(interface_version)])


def historical_profile_for(interface_version: int) -> dict:
    return profile_by_id(_HISTORICAL_PROFILE_IDS[normalize_interface_version(interface_version)])


def workflow_profiles() -> list[dict]:
    return [profile_by_id(profile_id) for profile_id in _PROFILE_DOCUMENTS]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_metadata(path: str | Path) -> dict:
    artifact = Path(path)
    result = {"path": str(artifact), "exists": artifact.exists()}
    if not artifact.exists() or not artifact.is_file():
        return result
    result.update({"bytes": artifact.stat().st_size, "sha256": _sha256(artifact)})
    try:
        with Image.open(artifact) as image:
            result.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                    "format": image.format,
                }
            )
    except Exception:
        pass
    return result


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: dict, *, exclusive: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(_jsonable(payload), handle, indent=2, ensure_ascii=False)
    return path


def _pinned_profile(session) -> dict:
    profile = dict(session.workflow_profile or {})
    if not profile:
        profile = profile_by_id(session.workflow_profile_id)
    canonical = profile_by_id(profile["id"])
    if profile != canonical or session.workflow_profile_id != canonical["id"]:
        raise ValueError("Session workflow profile does not match its immutable registry contract")
    if session.interface_version != canonical["interface_version"]:
        raise ValueError("Session interface version does not match its workflow profile")
    return canonical


def snapshot_session(session, output_dir: Path) -> Path:
    """Write one immutable full-state snapshot and refresh the mutable session index."""
    profile = _pinned_profile(session)
    existing_sequences = []
    for candidate in (output_dir / "workflow").glob("snapshot_*.json"):
        try:
            existing_sequences.append(int(candidate.name.split("_")[1]))
        except (IndexError, ValueError):
            continue
    sequence = max([session.workflow_snapshot_count, *existing_sequences], default=0) + 1
    session.workflow_snapshot_count = sequence
    path = output_dir / "workflow" / f"snapshot_{sequence:04d}_{session.state.value}.json"
    session.workflow_records.append(str(path))

    artifact_paths: list[Path] = []
    for candidate in output_dir.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(output_dir)
        if relative.parts[0] == "workflow" or relative.name in {"session.json", "workflow_manifest.json"}:
            continue
        artifact_paths.append(candidate)

    snapshot = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "sequence": sequence,
        "session_id": session.session_id,
        "interface_version": session.interface_version,
        "workflow_profile": profile,
        "camera_contract": _jsonable(session.camera_contract),
        "canon_alignment": _jsonable(session.canon_alignment),
        "world_contract": _jsonable(session.world_contract),
        "semantic_command_records": _jsonable(session.semantic_command_records),
        "relationship_solver_report": _jsonable(session.relationship_solver_report),
        "conditioning_metadata": _jsonable(session.conditioning_metadata),
        "conditioning_records": _jsonable(session.conditioning_records),
        "compiler_manifests": list(session.compiler_manifests),
        "compiler_attempt_records": _jsonable(session.compiler_attempt_records),
        "compiler_result": _jsonable(session.compiler_result),
        "export_results": _jsonable(session.export_results),
        "structural_parity_report": _jsonable(session.parity_report),
        "runtime_smoke_report": _jsonable(session.runtime_smoke_report),
        "qa_evidence": _jsonable(session.qa_evidence),
        "session": session.model_dump(mode="json"),
        "artifacts": [artifact_metadata(artifact) for artifact in sorted(artifact_paths)],
    }
    write_json(path, snapshot, exclusive=True)
    write_json(
        output_dir / "workflow_manifest.json",
        {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "session_id": session.session_id,
            "interface_version": session.interface_version,
            "workflow_profile": profile,
            "camera_contract": _jsonable(session.camera_contract),
            "canon_alignment": _jsonable(session.canon_alignment),
            "latest_snapshot": str(path),
            "records": list(session.workflow_records),
            "generation_manifests": list(session.generation_manifests),
            "compiler_manifests": list(session.compiler_manifests),
            "world_contract": _jsonable(session.world_contract),
            "semantic_command_records": _jsonable(session.semantic_command_records),
            "conditioning_metadata": _jsonable(session.conditioning_metadata),
            "conditioning_records": _jsonable(session.conditioning_records),
            "compiler_attempt_records": _jsonable(session.compiler_attempt_records),
            "compiler_result": _jsonable(session.compiler_result),
            "export_results": _jsonable(session.export_results),
            "structural_parity_report": _jsonable(session.parity_report),
            "runtime_smoke_report": _jsonable(session.runtime_smoke_report),
            "qa_evidence": _jsonable(session.qa_evidence),
        },
    )
    return path


def write_generation_manifest(
    output_dir: Path, attempt: int, mode: str, payload: dict
) -> Path:
    """Persist one immutable generation lifecycle record."""
    base = output_dir / "workflow" / f"canon_v{attempt}_{mode}"
    path = base.with_suffix(".json")
    sequence = 2
    while path.exists():
        path = Path(f"{base}_{sequence}.json")
        sequence += 1
    document = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "attempt": attempt,
        "mode": mode,
        **payload,
    }
    return write_json(path, document, exclusive=True)
