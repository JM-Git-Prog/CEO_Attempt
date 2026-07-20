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
    }
)
_HISTORICAL_PROFILE_IDS = MappingProxyType(
    {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
    }
)


def normalize_interface_version(value: int | str | None) -> int:
    try:
        version = int(value or 7)
    except (TypeError, ValueError):
        version = 7
    if version <= 3:
        return 3
    if version == 4:
        return 4
    if version == 5:
        return 5
    if version == 6:
        return 6
    return 7


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
            "latest_snapshot": str(path),
            "records": list(session.workflow_records),
            "generation_manifests": list(session.generation_manifests),
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
