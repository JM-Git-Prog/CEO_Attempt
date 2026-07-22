from __future__ import annotations

import json
from pathlib import Path

import src.upbge_capabilities as capabilities
from src.upbge_capabilities import UPBGECapabilityReport, discover_upbge, probe_upbge_executable


def _capture(payload: dict[str, object]) -> capabilities._ProcessCapture:
    line = capabilities._PROBE_MARKER + json.dumps(payload)
    return capabilities._ProcessCapture(0, line, "", False, False, 7)


def test_probe_rejects_regular_blender_even_when_executable_exists(tmp_path, monkeypatch):
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs: _capture({
        "product": "Blender", "product_version": "4.2", "blender_api_version": "4.2",
        "python_version": "3.11", "supports_game_runtime": False,
        "supports_eevee": True, "supports_gltf": True,
    }))

    report = probe_upbge_executable(executable)

    assert report.available is True
    assert report.verified is False
    assert report.compatible is False
    assert report.reason_code == "regular_blender_rejected"


def test_probe_only_verifies_complete_upbge_identity(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs: _capture({
        "product": "UPBGE", "product_version": "0.36", "blender_api_version": "3.6",
        "python_version": "3.10", "supports_game_runtime": True,
        "supports_eevee": True, "supports_gltf": True,
    }))

    report = probe_upbge_executable(executable)

    assert report.verified and report.compatible
    assert report.product == "UPBGE"
    assert report.supports_game_runtime


def test_discovery_order_is_explicit_then_approved_then_path(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.exe"
    approved = tmp_path / "approved.exe"
    path_candidate = tmp_path / "path-upbge.exe"
    for path in (explicit, approved, path_candidate):
        path.write_bytes(b"fake")
    seen: list[tuple[Path, str]] = []

    def fake_probe(path, *, source, **kwargs):
        seen.append((Path(path), source))
        accepted = Path(path) == approved
        return UPBGECapabilityReport(
            available=True, verified=accepted, compatible=accepted,
            executable_path=str(Path(path).resolve()), discovery_source=source,
            product="UPBGE" if accepted else "Blender",
            supports_game_runtime=accepted, supports_eevee=accepted, supports_gltf=accepted,
            reason_code="verified" if accepted else "regular_blender_rejected",
        )

    monkeypatch.setattr(capabilities, "probe_upbge_executable", fake_probe)
    monkeypatch.setattr(capabilities.shutil, "which", lambda *args, **kwargs: str(path_candidate))

    report = discover_upbge(
        explicit_path=explicit, known_locations=(approved,), environment={"PATH": str(tmp_path)}
    )

    assert seen == [(explicit, "explicit_config"), (approved, "approved_location")]
    assert report.compatible
    assert [attempt.reason_code for attempt in report.attempts] == [
        "regular_blender_rejected", "verified"
    ]


def test_configured_version_pins_reject_otherwise_capable_build(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs: _capture({
        "product": "UPBGE", "product_version": "0.36", "blender_api_version": "3.6",
        "python_version": "3.10", "supports_game_runtime": True,
        "supports_eevee": True, "supports_gltf": True,
    }))

    report = probe_upbge_executable(
        executable,
        required_product_version="0.37",
        required_blender_api_version="4.2",
    )

    assert report.available and report.verified
    assert not report.compatible
    assert report.reason_code == "version_mismatch"
    assert report.diagnostics == (
        "product_version expected '0.37', got '0.36'",
        "blender_api_version expected '4.2', got '3.6'",
    )


def test_discovery_passes_exact_version_pins_from_configuration(tmp_path, monkeypatch):
    executable = tmp_path / "configured-upbge.exe"
    executable.write_bytes(b"fake")
    observed: dict[str, object] = {}

    def fake_probe(path, **kwargs):
        observed.update(kwargs)
        return UPBGECapabilityReport(
            available=True, verified=True, compatible=True,
            executable_path=str(Path(path).resolve()), product="UPBGE",
            product_version="0.36", blender_api_version="3.6",
            supports_game_runtime=True, supports_eevee=True, supports_gltf=True,
            reason_code="verified",
        )

    monkeypatch.setattr(capabilities, "probe_upbge_executable", fake_probe)
    report = discover_upbge(config={
        "UPBGE_PATH": str(executable),
        "UPBGE_PRODUCT_VERSION": "0.36",
        "UPBGE_BLENDER_API_VERSION": "3.6",
    }, known_locations=(), environment={"PATH": ""})

    assert report.compatible
    assert observed["required_product_version"] == "0.36"
    assert observed["required_blender_api_version"] == "3.6"


def test_discovery_distinguishes_absent_from_incompatible_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities.shutil, "which", lambda *args, **kwargs: None)
    absent = discover_upbge(known_locations=(), environment={"PATH": ""})

    regular_blender = tmp_path / "blender.exe"
    regular_blender.write_bytes(b"fake")
    monkeypatch.setattr(capabilities, "probe_upbge_executable", lambda path, **kwargs: (
        UPBGECapabilityReport(
            available=True, executable_path=str(Path(path).resolve()), product="Blender",
            reason_code="regular_blender_rejected",
        )
    ))
    incompatible = discover_upbge(
        explicit_path=regular_blender, known_locations=(), environment={"PATH": ""}
    )

    assert absent.reason_code == "upbge_not_found"
    assert not absent.available and absent.attempts == ()
    assert incompatible.available and not incompatible.compatible
    assert incompatible.reason_code == "regular_blender_rejected"
    assert incompatible.attempts[0].status == "rejected"
