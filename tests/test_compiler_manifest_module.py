from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.compiler_manifest import (
    ArtifactMetadata,
    CanonicalDocument,
    CompilerDiagnostic,
    CompilerManifestStore,
    CompilerVersions,
    ManifestBinding,
    TimingRecord,
    read_terminal_manifest,
)

H = "a" * 64
WORLD = CanonicalDocument.from_value({
    "schema_version": "world-contract/v1",
    "source": {"session_id": "manifest-session"},
    "instances": [],
})
INPUT_BYTES = len(WORLD.canonical_json.encode("utf-8"))


def _binding() -> ManifestBinding:
    return ManifestBinding(
        session_id="manifest-session", interface_version=11,
        workflow_profile_id="upbge-r1",
        workflow_profile=CanonicalDocument.from_value({"id": "upbge-r1", "version": 1}),
        world_contract_version="world-contract/v1", world_contract_hash=WORLD.sha256,
        world_contract=WORLD,
        plan_revision=7, plan_hash="f" * 64,
        camera_contract_id="camera-1", camera_contract_hash="e" * 64,
        compiler_script_hash=H,
        command_log_hash="b" * 64,
    )


def _compiler() -> CompilerVersions:
    return CompilerVersions(
        product="UPBGE", product_version="0.36", blender_version="4.2",
        python_version="3.11", compiler_version="scene-compiler/v1",
        runtime_capable=True,
    )


def test_prepared_and_terminal_manifests_are_exclusive_and_exactly_bound(tmp_path):
    store = CompilerManifestStore(tmp_path / "manifests")
    prepared, prepared_path = store.prepare(
        binding=_binding(), compiler=_compiler(), configuration={"seed": 4, "quality": "high"},
        input_bytes=INPUT_BYTES,
    )
    artifact_path = tmp_path / "scene.glb"
    artifact_path.write_bytes(b"glb")
    now = datetime.now(timezone.utc)
    timing = TimingRecord(
        stage="compile", started_at=now, ended_at=now + timedelta(milliseconds=5),
        duration_ms=5,
    )

    terminal, terminal_path = store.terminate(
        prepared, status="completed", timings=(timing,),
        artifacts=(ArtifactMetadata.from_path(
            artifact_path, media_type="model/gltf-binary", target_role="neutral_scene"
        ),),
    )

    restored = read_terminal_manifest(terminal_path)
    assert prepared_path.exists()
    assert restored == terminal
    assert restored.binding.world_contract_hash == WORLD.sha256
    assert restored.binding.world_contract.value()["schema_version"] == "world-contract/v1"
    assert restored.configuration.value() == {"quality": "high", "seed": 4}
    assert restored.artifacts[0].bytes == 3

    with pytest.raises(FileExistsError):
        store.write_terminal(terminal)


def test_recompile_ids_never_overwrite_prior_attempts(tmp_path):
    store = CompilerManifestStore(tmp_path)
    first, first_path = store.prepare(
        binding=_binding(), compiler=_compiler(), configuration={"seed": 1},
        input_bytes=INPUT_BYTES,
    )
    second, second_path = store.prepare(
        binding=_binding(), compiler=_compiler(), configuration={"seed": 1},
        input_bytes=INPUT_BYTES,
    )

    assert first.compilation_id != second.compilation_id
    assert first_path != second_path
    assert first_path.exists() and second_path.exists()


def test_failed_terminal_preserves_structured_diagnostic(tmp_path):
    store = CompilerManifestStore(tmp_path)
    prepared, _ = store.prepare(
        binding=_binding(), compiler=_compiler(), configuration={},
        input_bytes=INPUT_BYTES,
    )
    diagnostic = CompilerDiagnostic(
        stage="compile", code="object_limit", severity="error",
        message="object count exceeded", violated_limit="max_objects",
    )
    terminal, _ = store.terminate(
        prepared, status="rejected", diagnostics=(diagnostic,)
    )

    assert terminal.status == "rejected"
    assert terminal.diagnostics[0].violated_limit == "max_objects"


def test_prepared_manifest_rejects_non_exact_canonical_input_size(tmp_path):
    store = CompilerManifestStore(tmp_path)
    with pytest.raises(ValueError, match="input_bytes"):
        store.prepare(
            binding=_binding(), compiler=_compiler(), configuration={},
            input_bytes=INPUT_BYTES + 1,
        )


def test_binding_rejects_world_contract_hash_or_version_drift():
    payload = _binding().model_dump()
    payload["world_contract_hash"] = "0" * 64
    with pytest.raises(ValueError, match="world contract document"):
        ManifestBinding.model_validate(payload)
