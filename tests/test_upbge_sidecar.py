from __future__ import annotations

import hashlib
import io
from pathlib import Path

import src.upbge_sidecar as sidecar
from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_compiler import ApprovedAsset, CompilerOutputFlags
from src.upbge_sidecar import SidecarLimits, run_upbge_sidecar, sanitized_environment
from src.world_contract import WorldContract
from tests.upbge_test_support import build_test_contract


def _capability(executable: Path) -> UPBGECapabilityReport:
    return UPBGECapabilityReport(
        available=True, verified=True, compatible=True, executable_path=str(executable),
        product="UPBGE", supports_game_runtime=True, supports_eevee=True,
        supports_gltf=True, reason_code="verified",
    )


def test_sidecar_rejects_unverified_engine_and_noncanonical_input(tmp_path):
    canonical = build_test_contract().canonical_bytes()

    unverified = run_upbge_sidecar(UPBGECapabilityReport(), canonical, tmp_path)
    noncanonical = run_upbge_sidecar(
        _capability(tmp_path / "upbge.exe"), canonical + b"\n", tmp_path
    )

    assert unverified.reason_code == "unverified_upbge_executable"
    assert noncanonical.reason_code == "noncanonical_world_contract"
    assert not unverified.success and not noncanonical.success


def test_sanitized_environment_does_not_inherit_secrets(tmp_path):
    executable = tmp_path / "engine" / "upbge.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"fake")

    result = sanitized_environment(executable, tmp_path, {
        "SYSTEMROOT": "C:/Windows", "PATH": "C:/untrusted", "API_TOKEN": "secret",
        "AWS_SECRET_ACCESS_KEY": "secret", "PYTHONPATH": "C:/injected",
    })

    assert "API_TOKEN" not in result and "AWS_SECRET_ACCESS_KEY" not in result
    assert "PYTHONPATH" not in result
    assert result["PATH"].split(sidecar.os.pathsep)[0] == str(executable.parent.resolve())
    assert result["HOME"] == str(tmp_path)


def test_success_uses_read_only_canonical_copy_unique_output_and_explicit_flags(
    tmp_path, monkeypatch,
):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    observed: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = 0
            self.stdout = io.BytesIO(b"ok")
            self.stderr = io.BytesIO()
            output_dir = Path(command[command.index("--output-dir") + 1])
            input_path = Path(command[command.index("--input") + 1])
            (output_dir / "scene_inventory.json").write_text("{}", encoding="utf-8")
            observed.append({
                "command": command, "env": kwargs["env"], "input": input_path,
                "output": output_dir,
            })

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sidecar.subprocess, "Popen", FakeProcess)
    flags = CompilerOutputFlags(render=False, blend=False, glb=False, runtime=False)
    canonical = build_test_contract().canonical_bytes()

    first = run_upbge_sidecar(_capability(executable), canonical, tmp_path, outputs=flags)
    second = run_upbge_sidecar(_capability(executable), canonical, tmp_path, outputs=flags)

    assert first.success and second.success
    assert first.output_dir != second.output_dir
    assert [artifact.role for artifact in first.artifacts] == ["inventory"]
    command = observed[0]["command"]
    assert command[command.index("--render") + 1] == "0"
    assert command[command.index("--blend") + 1] == "0"
    assert command[command.index("--glb") + 1] == "0"
    assert command[command.index("--runtime") + 1] == "0"
    assert Path(observed[0]["input"]).read_bytes() == canonical
    assert Path(observed[0]["input"]).stat().st_mode & 0o222 == 0
    assert "API_TOKEN" not in observed[0]["env"]


def test_plan_resource_limit_is_reported_structurally_before_launch(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(
        sidecar.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    result = run_upbge_sidecar(
        _capability(executable), build_test_contract().canonical_bytes(), tmp_path,
        limits=SidecarLimits(max_objects=1),
    )

    assert not result.success
    assert result.reason_code == "resource_limit_exceeded"
    assert result.violated_limit == "max_objects"


def test_timeout_and_nonzero_exit_return_distinct_structured_failures(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    modes = iter(("timeout", "failure"))

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.mode = next(modes)
            self.returncode = None if self.mode == "timeout" else 17
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO(b"engine failed" if self.mode == "failure" else b"")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sidecar.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(sidecar, "_terminate", lambda process: process.kill())
    canonical = build_test_contract().canonical_bytes()

    timed_out = run_upbge_sidecar(
        _capability(executable), canonical, tmp_path,
        limits=SidecarLimits(wall_time_s=0.001),
    )
    failed = run_upbge_sidecar(_capability(executable), canonical, tmp_path)

    assert timed_out.status == "timed_out"
    assert timed_out.reason_code == "sidecar_timeout"
    assert timed_out.violated_limit == "wall_time_s"
    assert failed.status == "failed"
    assert failed.reason_code == "compiler_process_failure"
    assert failed.return_code == 17
    assert failed.stderr_tail == "engine failed"


def test_each_output_can_be_enabled_independently(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    cases = (
        ("render", "render", "reference.png"),
        ("blend", "blend", "scene.blend"),
        ("glb", "glb", "scene.glb"),
        ("runtime", "runtime_candidate", "runtime_candidate.blend"),
    )

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.returncode = 0
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "scene_inventory.json").write_text("{}", encoding="utf-8")
            for cli_role, _artifact_role, filename in cases:
                if command[command.index(f"--{cli_role}") + 1] == "1":
                    (output_dir / filename).write_bytes(cli_role.encode("ascii"))

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sidecar.subprocess, "Popen", FakeProcess)
    canonical = build_test_contract().canonical_bytes()
    for enabled_role, expected_artifact_role, _filename in cases:
        flags = CompilerOutputFlags(**{
            cli_role: cli_role == enabled_role for cli_role, _artifact_role, _name in cases
        })
        result = run_upbge_sidecar(
            _capability(executable), canonical, tmp_path, outputs=flags
        )
        assert result.success
        assert {artifact.role for artifact in result.artifacts} == {
            expected_artifact_role, "inventory"
        }


def test_sidecar_materializes_only_hash_bound_registry_assets(tmp_path, monkeypatch):
    executable = tmp_path / "upbge.exe"
    executable.write_bytes(b"fake")
    asset = tmp_path / "reviewed.glb"
    asset.write_bytes(b"approved glb payload")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    payload = build_test_contract().model_dump(mode="json")
    instance = next(item for item in payload["instances"] if item["id"] == "table_1")
    instance.update({
        "geometry_strategy": "asset", "primitive_shape": None,
        "asset_registry_id": "asset:table:v1",
    })
    contract = WorldContract.model_validate(payload)
    observed_asset = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.returncode = 0
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            plan_path = Path(command[command.index("--plan") + 1])
            copied = plan_path.parent / "assets" / f"{digest}.glb"
            observed_asset.append((copied.read_bytes(), copied.stat().st_mode & 0o222))
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "scene_inventory.json").write_text("{}", encoding="utf-8")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sidecar.subprocess, "Popen", FakeProcess)
    result = run_upbge_sidecar(
        _capability(executable), contract.canonical_bytes(), tmp_path / "runs",
        outputs=CompilerOutputFlags(render=False, blend=False, glb=False, runtime=False),
        asset_registry={
            "asset:table:v1": ApprovedAsset(asset, digest, triangle_count=12)
        },
    )

    assert result.success
    assert observed_asset == [(b"approved glb payload", 0)]
