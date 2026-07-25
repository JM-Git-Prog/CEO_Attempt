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


# ─── blenderplayer discovery and probing ─────────────────────────────────────


def test_discover_blenderplayer_finds_exe_alongside_editor_on_windows(tmp_path, monkeypatch):
    """discover_blenderplayer returns the player path when it exists next to the editor."""
    monkeypatch.setattr(capabilities, "sys_platform", lambda: "win32")
    editor = tmp_path / "upbge.exe"
    player = tmp_path / "blenderplayer.exe"
    editor.write_bytes(b"fake")
    player.write_bytes(b"fake")

    result = capabilities.discover_blenderplayer(editor)
    assert result is not None
    assert result.name == "blenderplayer.exe"


def test_discover_blenderplayer_finds_binary_alongside_editor_on_linux(tmp_path, monkeypatch):
    """discover_blenderplayer returns the player path on non-Windows platforms."""
    monkeypatch.setattr(capabilities, "sys_platform", lambda: "linux")
    editor = tmp_path / "upbge"
    player = tmp_path / "blenderplayer"
    editor.write_bytes(b"fake")
    player.write_bytes(b"fake")

    result = capabilities.discover_blenderplayer(editor)
    assert result is not None
    assert result.name == "blenderplayer"


def test_discover_blenderplayer_returns_none_when_player_absent(tmp_path, monkeypatch):
    """discover_blenderplayer returns None when blenderplayer isn't alongside editor."""
    monkeypatch.setattr(capabilities, "sys_platform", lambda: "win32")
    editor = tmp_path / "upbge.exe"
    editor.write_bytes(b"fake")

    result = capabilities.discover_blenderplayer(editor)
    assert result is None


def test_discover_blenderplayer_returns_none_when_editor_path_is_none():
    """discover_blenderplayer returns None for None editor path."""
    result = capabilities.discover_blenderplayer(None)
    assert result is None


def test_probe_blenderplayer_verified_on_clean_exit(tmp_path, monkeypatch):
    """probe_blenderplayer returns verified=True when process exits 0."""
    player = tmp_path / "blenderplayer.exe"
    player.write_bytes(b"fake")

    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs:
        capabilities._ProcessCapture(0, "UPBGE blenderplayer 0.36", "", False, False, 5))

    verified, reason, diags = capabilities.probe_blenderplayer(player)
    assert verified is True
    assert reason == "blenderplayer_verified"
    assert diags == ()


def test_probe_blenderplayer_fails_on_timeout(tmp_path, monkeypatch):
    """probe_blenderplayer reports timeout when process exceeds time limit."""
    player = tmp_path / "blenderplayer.exe"
    player.write_bytes(b"fake")

    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs:
        capabilities._ProcessCapture(None, "", "", True, False, 5000))

    verified, reason, diags = capabilities.probe_blenderplayer(player)
    assert verified is False
    assert reason == "blenderplayer_timeout"


def test_probe_blenderplayer_detects_gpu_errors(tmp_path, monkeypatch):
    """probe_blenderplayer rejects on GPU error indicators in output."""
    player = tmp_path / "blenderplayer.exe"
    player.write_bytes(b"fake")

    monkeypatch.setattr(capabilities, "_bounded_process", lambda *args, **kwargs:
        capabilities._ProcessCapture(0, "GPU Error: failed to init", "", False, False, 5))

    verified, reason, diags = capabilities.probe_blenderplayer(player)
    assert verified is False
    assert reason == "blenderplayer_gpu_error"


def test_probe_blenderplayer_not_found_for_missing_path(tmp_path):
    """probe_blenderplayer returns not_found for a path that doesn't exist."""
    nonexistent = tmp_path / "no_such_player.exe"
    verified, reason, diags = capabilities.probe_blenderplayer(nonexistent)
    assert verified is False
    assert reason == "blenderplayer_not_found"


def test_discover_upbge_populates_blenderplayer_fields_when_player_present(tmp_path, monkeypatch):
    """discover_upbge enriches the report with blenderplayer fields when player is alongside editor."""
    editor = tmp_path / "upbge.exe"
    player = tmp_path / "blenderplayer.exe"
    editor.write_bytes(b"fake")
    player.write_bytes(b"fake")

    monkeypatch.setattr(capabilities, "sys_platform", lambda: "win32")
    monkeypatch.setattr(capabilities, "_bounded_process", lambda cmd, **kwargs:
        capabilities._ProcessCapture(0, "UPBGE blenderplayer 0.36", "", False, False, 5)
        if "blenderplayer" in str(cmd[0])
        else _capture({
            "product": "UPBGE", "product_version": "0.36", "blender_api_version": "3.6",
            "python_version": "3.10", "supports_game_runtime": True,
            "supports_eevee": True, "supports_gltf": True,
        })
    )

    report = discover_upbge(
        explicit_path=editor, known_locations=(), environment={"PATH": ""}
    )

    assert report.compatible
    assert report.blenderplayer_available is True
    assert report.blenderplayer_verified is True
    assert report.blenderplayer_reason_code == "blenderplayer_verified"
    assert report.blenderplayer_path is not None
    assert "blenderplayer" in report.blenderplayer_path


def test_discover_upbge_reports_blenderplayer_absent_when_only_editor_present(tmp_path, monkeypatch):
    """discover_upbge sets blenderplayer_available=False when player file doesn't exist."""
    editor = tmp_path / "upbge.exe"
    editor.write_bytes(b"fake")
    # No blenderplayer.exe alongside editor

    monkeypatch.setattr(capabilities, "sys_platform", lambda: "win32")
    monkeypatch.setattr(capabilities, "_bounded_process", lambda cmd, **kwargs:
        _capture({
            "product": "UPBGE", "product_version": "0.36", "blender_api_version": "3.6",
            "python_version": "3.10", "supports_game_runtime": True,
            "supports_eevee": True, "supports_gltf": True,
        })
    )

    report = discover_upbge(
        explicit_path=editor, known_locations=(), environment={"PATH": ""}
    )

    assert report.compatible
    assert report.blenderplayer_available is False
    assert report.blenderplayer_verified is False
    assert report.blenderplayer_reason_code == "blenderplayer_not_found"
    assert report.blenderplayer_path is None


def test_discover_upbge_editor_absent_does_not_probe_blenderplayer(monkeypatch):
    """When no editor is found, blenderplayer fields remain at defaults."""
    monkeypatch.setattr(capabilities.shutil, "which", lambda *args, **kwargs: None)

    report = discover_upbge(known_locations=(), environment={"PATH": ""})

    assert report.reason_code == "upbge_not_found"
    assert report.blenderplayer_available is False
    assert report.blenderplayer_verified is False
    assert report.blenderplayer_reason_code == "not_probed"
    assert report.blenderplayer_path is None
