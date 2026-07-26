"""Restricted UPBGE compilation subprocess boundary.

The boundary is intentionally honest: POSIX CPU/address-space limits are hard limits;
on Windows, the standard library provides wall-time/output/path controls but no Job
Object memory/CPU containment.  Those limitations are returned as evidence.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_compiler import (
    FIRST_PARTY_SCRIPT,
    ApprovedAsset,
    CompilerLimitError,
    CompilerLimits,
    CompilerOutputFlags,
    build_compiler_plan,
)
from src.world_contract import canonical_world_contract, world_contract_from_json

SIDECAR_RESULT_VERSION = "upbge-sidecar-result/v1"
_SECRET_FRAGMENTS = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "PRIVATE_KEY")


@dataclass(frozen=True)
class SidecarLimits:
    max_input_bytes: int = 4 * 1024 * 1024
    max_objects: int = 2048
    max_polygons: int = 2_000_000
    max_texture_dimension: int = 8192
    max_output_bytes: int = 512 * 1024 * 1024
    max_process_output_bytes: int = 2 * 1024 * 1024
    wall_time_s: float = 180.0
    cpu_time_s: int = 150
    memory_bytes: int = 4 * 1024 * 1024 * 1024

    def validate(self) -> None:
        values = asdict(self)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0
               for value in values.values()):
            raise ValueError("all sidecar limits must be positive")
        if not math.isfinite(self.wall_time_s):
            raise ValueError("wall_time_s must be finite")


@dataclass(frozen=True)
class SidecarArtifact:
    role: str
    path: str
    bytes: int


@dataclass(frozen=True)
class SidecarResult:
    schema_version: str
    success: bool
    status: str
    reason_code: str
    output_dir: str | None
    artifacts: tuple[SidecarArtifact, ...]
    return_code: int | None
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    violated_limit: str | None
    isolation_controls: tuple[str, ...]
    isolation_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sanitized_environment(
    executable: str | os.PathLike[str], run_dir: Path, source: Mapping[str, str] | None = None
) -> dict[str, str]:
    incoming = dict(os.environ if source is None else source)
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    result = {
        key: value for key, value in incoming.items()
        if key.upper() in allowed
        and not any(fragment in key.upper() for fragment in _SECRET_FRAGMENTS)
    }
    executable_dir = str(Path(executable).resolve().parent)
    system_root = result.get("SYSTEMROOT") or result.get("WINDIR")
    path_parts = [executable_dir]
    if system_root:
        path_parts.extend((str(Path(system_root) / "System32"), system_root))
    result.update({
        "PATH": os.pathsep.join(path_parts),
        "HOME": str(run_dir),
        "TMP": str(run_dir / "tmp"),
        "TEMP": str(run_dir / "tmp"),
        "PYTHONNOUSERSITE": "1",
    })
    return result


def _posix_limit_hook(limits: SidecarLimits):
    def apply() -> None:
        import resource
        cpu = int(math.ceil(limits.cpu_time_s))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        os.umask(0o077)
    return apply


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _directory_size(root: Path, limit: int) -> tuple[int, bool]:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            return total, True
        if path.is_file():
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root.resolve())
                total += path.stat().st_size
            except (OSError, ValueError):
                return total, True
            if total > limit:
                return total, True
    return total, False


def _capture_reader(
    pipe: object, target: bytearray, limit: int, exceeded: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    while True:
        chunk = pipe.read(8192)  # type: ignore[attr-defined]
        if not chunk:
            return
        remaining = limit - len(target)
        if remaining > 0:
            target.extend(chunk[:remaining])
        if len(chunk) > remaining:
            exceeded.set()
            _terminate(process)
            return


def _failure(
    reason: str, *, output_dir: Path | None = None, status: str = "rejected",
    duration_ms: int = 0, return_code: int | None = None, stdout: str = "",
    stderr: str = "", violated: str | None = None,
    controls: tuple[str, ...] = (), limitations: tuple[str, ...] = (),
) -> SidecarResult:
    return SidecarResult(
        schema_version=SIDECAR_RESULT_VERSION, success=False, status=status,
        reason_code=reason, output_dir=str(output_dir) if output_dir else None,
        artifacts=(), return_code=return_code, duration_ms=duration_ms,
        stdout_tail=stdout[-4000:], stderr_tail=stderr[-4000:],
        violated_limit=violated, isolation_controls=controls,
        isolation_limitations=limitations,
    )


def run_upbge_sidecar(
    capability: UPBGECapabilityReport,
    canonical_contract: bytes,
    output_root: str | os.PathLike[str],
    *,
    outputs: CompilerOutputFlags = CompilerOutputFlags(),
    limits: SidecarLimits = SidecarLimits(),
    compiler_script: Path = FIRST_PARTY_SCRIPT,
    environment: Mapping[str, str] | None = None,
    asset_registry: Mapping[str, ApprovedAsset] | None = None,
) -> SidecarResult:
    """Compile one canonical contract in a unique, bounded subprocess directory."""
    limits.validate()
    controls = ["separate_process", "sanitized_environment", "wall_timeout",
                "bounded_process_output", "unique_output_directory",
                "read_only_canonical_input", "output_path_validation"]
    limitations = [
        "network_namespace_not_enforced",
        "filesystem_confinement_postvalidated",
        "read_only_mode_not_mandatory_against_same_user_process",
    ]
    if os.name == "posix":
        controls.extend(("posix_cpu_limit", "posix_address_space_limit", "process_group_kill"))
    else:
        limitations.extend((
            "windows_cpu_limit_not_hard_without_job_object",
            "windows_memory_limit_not_hard_without_job_object",
            "windows_child_process_tree_kill_not_guaranteed",
        ))
    evidence = (
        capability.verified and capability.compatible and capability.product == "UPBGE"
        and capability.supports_game_runtime and capability.executable_path
    )
    if not evidence:
        return _failure(
            "unverified_upbge_executable", controls=tuple(controls),
            limitations=tuple(limitations),
        )
    if not isinstance(canonical_contract, bytes):
        return _failure(
            "canonical_input_must_be_bytes", controls=tuple(controls),
            limitations=tuple(limitations),
        )
    if len(canonical_contract) > limits.max_input_bytes:
        return _failure(
            "input_limit_exceeded", violated="max_input_bytes", controls=tuple(controls),
            limitations=tuple(limitations),
        )
    try:
        contract = world_contract_from_json(canonical_contract)
        if canonical_world_contract(contract) != canonical_contract:
            raise ValueError("bytes differ from canonical serialization")
    except (ValueError, TypeError) as exc:
        return _failure(
            "noncanonical_world_contract", stderr=str(exc), controls=tuple(controls),
            limitations=tuple(limitations),
        )
    try:
        requested_root = Path(output_root).expanduser()
        requested_root.mkdir(parents=True, exist_ok=True)
        if requested_root.is_symlink():
            raise ValueError("output root must not be a symlink")
        root = requested_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("output root must be a directory")
        run_dir = Path(tempfile.mkdtemp(prefix="upbge-run-", dir=str(root))).resolve(strict=True)
        input_dir = run_dir / "input"
        output_dir = run_dir / "output"
        temp_dir = run_dir / "tmp"
        input_dir.mkdir(mode=0o700)
        output_dir.mkdir(mode=0o700)
        temp_dir.mkdir(mode=0o700)
        plan = build_compiler_plan(
            contract, outputs=outputs,
            limits=CompilerLimits(
                max_objects=limits.max_objects, max_polygons=limits.max_polygons,
                max_texture_dimension=limits.max_texture_dimension,
            ),
            asset_registry=asset_registry,
        )
        contract_path = input_dir / "world_contract.json"
        plan_path = input_dir / "compiler_plan.json"
        contract_path.write_bytes(canonical_contract)
        plan_bytes = plan.canonical_bytes()
        plan_path.write_bytes(plan_bytes)
        total_input_bytes = len(canonical_contract) + len(plan_bytes)
        materialized_assets: set[str] = set()
        for instance in plan.instances:
            if instance.geometry_strategy != "asset":
                continue
            registry_id = instance.asset_registry_id or ""
            binding = (asset_registry or {}).get(registry_id)
            if binding is None or not instance.asset_relative_path:
                raise ValueError(f"missing approved asset binding: {registry_id}")
            source = binding.validate()
            if instance.asset_relative_path in materialized_assets:
                continue
            materialized_assets.add(instance.asset_relative_path)
            total_input_bytes += source.stat().st_size
            if total_input_bytes > limits.max_input_bytes:
                raise CompilerLimitError(
                    "max_input_bytes", total_input_bytes, limits.max_input_bytes
                )
            destination = input_dir / instance.asset_relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.resolve().relative_to(input_dir.resolve())
            shutil.copyfile(source, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != instance.asset_sha256:
                raise ValueError(f"asset changed while preparing sidecar: {registry_id}")
            destination.chmod(0o444)
        contract_path.chmod(0o444)
        plan_path.chmod(0o444)
        script = compiler_script.resolve(strict=True)
        approved_script = FIRST_PARTY_SCRIPT.resolve(strict=True)
        if script.read_bytes() != approved_script.read_bytes():
            raise ValueError("compiler script is not the approved first-party source")
    except CompilerLimitError as exc:
        return _failure(
            "resource_limit_exceeded", output_dir=locals().get("output_dir"),
            stderr=str(exc), violated=exc.limit_name, controls=tuple(controls),
            limitations=tuple(limitations),
        )
    except (OSError, ValueError) as exc:
        return _failure(
            "sidecar_preparation_failed", stderr=str(exc), controls=tuple(controls),
            limitations=tuple(limitations),
        )

    command = [
        capability.executable_path,
        "--background", "--factory-startup", "--python", str(script), "--",
        "--input", str(contract_path), "--plan", str(plan_path),
        "--output-dir", str(output_dir),
        "--render", "1" if outputs.render else "0",
        "--blend", "1" if outputs.blend else "0",
        "--glb", "1" if outputs.glb else "0",
        "--runtime", "1" if outputs.runtime else "0",
        "--max-objects", str(limits.max_objects),
        "--max-polygons", str(limits.max_polygons),
        "--max-texture-dimension", str(limits.max_texture_dimension),
    ]
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(run_dir),
        "env": sanitized_environment(capability.executable_path, run_dir, environment),
        "text": False,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _posix_limit_hook(limits)
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
    except OSError as exc:
        return _failure(
            "process_start_failed", output_dir=output_dir, stderr=str(exc),
            controls=tuple(controls), limitations=tuple(limitations),
        )
    stdout_bytes, stderr_bytes = bytearray(), bytearray()
    process_output_exceeded = threading.Event()
    per_stream_limit = max(1, limits.max_process_output_bytes // 2)
    threads = [
        threading.Thread(
            target=_capture_reader,
            args=(process.stdout, stdout_bytes, per_stream_limit, process_output_exceeded, process),
            daemon=True,
        ),
        threading.Thread(
            target=_capture_reader,
            args=(process.stderr, stderr_bytes, per_stream_limit, process_output_exceeded, process),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    violated = None
    timed_out = False
    while process.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed > limits.wall_time_s:
            timed_out = True
            violated = "wall_time_s"
            _terminate(process)
            break
        _size, invalid_or_large = _directory_size(output_dir, limits.max_output_bytes)
        if invalid_or_large:
            violated = "max_output_bytes_or_path"
            _terminate(process)
            break
        if process_output_exceeded.is_set():
            violated = "max_process_output_bytes"
            _terminate(process)
            break
        time.sleep(0.05)
    for thread in threads:
        thread.join(timeout=2.0)
    duration_ms = round((time.monotonic() - started) * 1000)
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if timed_out:
        return _failure(
            "sidecar_timeout", output_dir=output_dir, status="timed_out",
            duration_ms=duration_ms, return_code=process.returncode, stdout=stdout,
            stderr=stderr, violated=violated, controls=tuple(controls),
            limitations=tuple(limitations),
        )
    if violated:
        return _failure(
            "resource_limit_exceeded", output_dir=output_dir, duration_ms=duration_ms,
            return_code=process.returncode, stdout=stdout, stderr=stderr,
            violated=violated, controls=tuple(controls), limitations=tuple(limitations),
        )
    if process.returncode != 0:
        # UPBGE 0.50+ may exit with non-zero due to plugin cleanup warnings
        # (Logic Nodes, Bricky Nodes) even when the script ran successfully.
        # Check if all expected output files exist before declaring failure.
        expected_check = dict(outputs.requested_names())
        expected_names_check = set(expected_check.values())
        missing_check = [fn for fn in expected_names_check if not (output_dir / fn).is_file()]
        if not missing_check:
            # All expected files present — treat as success despite non-zero exit
            pass  # Fall through to normal output validation below
        else:
            return _failure(
                "compiler_process_failure", output_dir=output_dir, status="failed",
                duration_ms=duration_ms, return_code=process.returncode, stdout=stdout,
                stderr=stderr, controls=tuple(controls), limitations=tuple(limitations),
            )

    expected = dict(outputs.requested_names())
    actual_files = [path for path in output_dir.rglob("*") if path.is_file() or path.is_symlink()]
    expected_names = set(expected.values())
    unexpected = [path.name for path in actual_files if path.name not in expected_names]
    missing = [filename for filename in expected_names if not (output_dir / filename).is_file()]
    total_size, invalid_or_large = _directory_size(output_dir, limits.max_output_bytes)
    if unexpected or missing or invalid_or_large or total_size > limits.max_output_bytes:
        detail = f"unexpected={sorted(unexpected)} missing={sorted(missing)} bytes={total_size}"
        return _failure(
            "output_validation_failed", output_dir=output_dir, stderr=detail,
            duration_ms=duration_ms, return_code=process.returncode,
            violated="output_paths_or_bytes" if invalid_or_large else None,
            controls=tuple(controls), limitations=tuple(limitations),
        )
    artifacts = tuple(
        SidecarArtifact(role=role, path=str(output_dir / filename), bytes=(output_dir / filename).stat().st_size)
        for role, filename in outputs.requested_names()
    )
    return SidecarResult(
        schema_version=SIDECAR_RESULT_VERSION, success=True, status="completed",
        reason_code="compiled", output_dir=str(output_dir), artifacts=artifacts,
        return_code=process.returncode, duration_ms=duration_ms,
        stdout_tail=stdout[-4000:], stderr_tail=stderr[-4000:], violated_limit=None,
        isolation_controls=tuple(controls), isolation_limitations=tuple(limitations),
    )
