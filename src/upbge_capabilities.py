"""UPBGE executable discovery and bounded, truthful capability probing.

Regular Blender is never treated as UPBGE.  Discovery is policy-free evidence:
callers decide whether a reported incompatibility permits a fallback.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

CAPABILITY_SCHEMA_VERSION = "upbge-capability/v1"
_PROBE_MARKER = "KIRO_UPBGE_CAPABILITY="
_DEFAULT_TIMEOUT_S = 8.0
_DEFAULT_OUTPUT_LIMIT = 64 * 1024
_SECRET_FRAGMENTS = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "PRIVATE_KEY")


@dataclass(frozen=True)
class CapabilityAttempt:
    path: str
    source: str
    status: str
    reason_code: str
    detail: str = ""


@dataclass(frozen=True)
class UPBGECapabilityReport:
    schema_version: str = CAPABILITY_SCHEMA_VERSION
    available: bool = False
    verified: bool = False
    compatible: bool = False
    executable_path: str | None = None
    discovery_source: str | None = None
    product: str | None = None
    product_version: str | None = None
    blender_api_version: str | None = None
    python_version: str | None = None
    supports_game_runtime: bool = False
    supports_eevee: bool = False
    supports_gltf: bool = False
    probe_duration_ms: int = 0
    reason_code: str = "not_probed"
    diagnostics: tuple[str, ...] = ()
    attempts: tuple[CapabilityAttempt, ...] = ()
    blenderplayer_path: str | None = None
    blenderplayer_available: bool = False
    blenderplayer_verified: bool = False
    blenderplayer_reason_code: str = "not_probed"
    blenderplayer_diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _ProcessCapture:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    output_exceeded: bool
    duration_ms: int


def _sanitized_probe_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    incoming = dict(os.environ if source is None else source)
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TMP", "TEMP", "HOME"}
    return {
        key: value
        for key, value in incoming.items()
        if key.upper() in allowed
        and not any(fragment in key.upper() for fragment in _SECRET_FRAGMENTS)
    }


def _bounded_process(
    command: Sequence[str], *, timeout_s: float, output_limit: int, env: Mapping[str, str]
) -> _ProcessCapture:
    """Run a short probe while draining and bounding captured process output."""
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        text=False,
    )
    streams: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()

    def drain(name: str, pipe: object) -> None:
        while True:
            chunk = pipe.read(4096)  # type: ignore[attr-defined]
            if not chunk:
                break
            target = streams[name]
            remaining = output_limit - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                exceeded.set()
                try:
                    process.kill()
                except OSError:
                    pass
                break

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for thread in threads:
        thread.join(timeout=1.0)
    return _ProcessCapture(
        returncode=process.returncode,
        stdout=streams["stdout"].decode("utf-8", errors="replace"),
        stderr=streams["stderr"].decode("utf-8", errors="replace"),
        timed_out=timed_out,
        output_exceeded=exceeded.is_set(),
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def _probe_expression() -> str:
    # The marker is intentionally a single JSON line for robust parsing amid engine logs.
    return (
        "import bpy,importlib.util,json,platform;"
        "has_bge=importlib.util.find_spec('bge') is not None;"
        "engines={i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items};"
        "ops=bpy.ops.export_scene;"
        "branch=getattr(bpy.app,'build_branch',b'');"
        "branch=branch.decode('utf-8','replace') if isinstance(branch,bytes) else str(branch);"
        "p={'product':'UPBGE' if has_bge else 'Blender',"
        "'product_version':branch or bpy.app.version_string,"
        "'blender_api_version':bpy.app.version_string,"
        "'python_version':platform.python_version(),"
        "'supports_game_runtime':has_bge,"
        "'supports_eevee':bool({'BLENDER_EEVEE','BLENDER_EEVEE_NEXT'} & engines),"
        "'supports_gltf':hasattr(ops,'gltf')};"
        f"print('{_PROBE_MARKER}'+json.dumps(p,sort_keys=True,separators=(',',':')))"
    )


def probe_upbge_executable(
    executable: str | os.PathLike[str],
    *,
    source: str = "explicit",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    output_limit: int = _DEFAULT_OUTPUT_LIMIT,
    environment: Mapping[str, str] | None = None,
    required_product_version: str | None = None,
    required_blender_api_version: str | None = None,
) -> UPBGECapabilityReport:
    """Verify an executable by asking its Blender API whether UPBGE runtime exists."""
    if timeout_s <= 0 or output_limit <= 0:
        raise ValueError("probe timeout and output limit must be positive")
    path = Path(executable).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return UPBGECapabilityReport(
            reason_code="executable_not_found", diagnostics=(str(exc),),
            executable_path=str(path), discovery_source=source,
        )
    if not resolved.is_file():
        return UPBGECapabilityReport(
            reason_code="not_a_file", executable_path=str(resolved), discovery_source=source
        )
    try:
        capture = _bounded_process(
            [str(resolved), "--background", "--factory-startup", "--python-expr", _probe_expression()],
            timeout_s=timeout_s,
            output_limit=output_limit,
            env=_sanitized_probe_environment(environment),
        )
    except OSError as exc:
        return UPBGECapabilityReport(
            available=True, executable_path=str(resolved), discovery_source=source,
            reason_code="probe_start_failed", diagnostics=(str(exc),),
        )
    base = {
        "available": True,
        "executable_path": str(resolved),
        "discovery_source": source,
        "probe_duration_ms": capture.duration_ms,
    }
    if capture.timed_out:
        return UPBGECapabilityReport(**base, reason_code="probe_timeout")
    if capture.output_exceeded:
        return UPBGECapabilityReport(**base, reason_code="probe_output_limit")
    if capture.returncode != 0:
        detail = capture.stderr[-1000:] or capture.stdout[-1000:]
        return UPBGECapabilityReport(
            **base, reason_code="probe_process_failure", diagnostics=(detail,)
        )

    marker_lines = [line for line in capture.stdout.splitlines() if line.startswith(_PROBE_MARKER)]
    if len(marker_lines) != 1:
        return UPBGECapabilityReport(**base, reason_code="identity_marker_missing")
    try:
        payload = json.loads(marker_lines[0][len(_PROBE_MARKER):])
        product = str(payload["product"])
        product_version = str(payload["product_version"])
        blender_version = str(payload["blender_api_version"])
        python_version = str(payload["python_version"])
        runtime = payload["supports_game_runtime"] is True
        eevee = payload["supports_eevee"] is True
        gltf = payload["supports_gltf"] is True
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return UPBGECapabilityReport(
            **base, reason_code="malformed_identity", diagnostics=(str(exc),)
        )
    verified = product == "UPBGE" and runtime
    capabilities_present = eevee and gltf
    version_diagnostics: list[str] = []
    if required_product_version is not None and product_version != required_product_version:
        version_diagnostics.append(
            f"product_version expected {required_product_version!r}, got {product_version!r}"
        )
    if (
        required_blender_api_version is not None
        and blender_version != required_blender_api_version
    ):
        version_diagnostics.append(
            "blender_api_version expected "
            f"{required_blender_api_version!r}, got {blender_version!r}"
        )
    compatible = verified and capabilities_present and not version_diagnostics
    if compatible:
        reason = "verified"
    elif product != "UPBGE":
        reason = "regular_blender_rejected"
    elif not capabilities_present or not runtime:
        reason = "required_capability_missing"
    else:
        reason = "version_mismatch"
    return UPBGECapabilityReport(
        **base,
        verified=verified,
        compatible=compatible,
        product=product,
        product_version=product_version,
        blender_api_version=blender_version,
        python_version=python_version,
        supports_game_runtime=runtime,
        supports_eevee=eevee,
        supports_gltf=gltf,
        reason_code=reason,
        diagnostics=tuple(version_diagnostics),
    )


_BLENDERPLAYER_PROBE_TIMEOUT_S = 5.0


def discover_blenderplayer(editor_executable: str | os.PathLike[str] | None) -> Path | None:
    """Derive the expected blenderplayer path from the editor executable location.

    Looks alongside the editor executable for ``blenderplayer.exe`` (Windows)
    or ``blenderplayer`` (Linux/macOS).  Returns the path if the file exists,
    otherwise None.
    """
    if editor_executable is None:
        return None
    editor_path = Path(editor_executable)
    try:
        editor_dir = editor_path.resolve(strict=True).parent
    except (OSError, RuntimeError):
        # Editor path doesn't actually exist on disk — can't derive player location
        return None

    if sys_platform() == "win32" or sys_platform() == "cygwin":
        candidate = editor_dir / "blenderplayer.exe"
    else:
        candidate = editor_dir / "blenderplayer"

    if candidate.is_file():
        return candidate
    return None


def probe_blenderplayer(
    player_path: str | os.PathLike[str],
    *,
    timeout_s: float = _BLENDERPLAYER_PROBE_TIMEOUT_S,
    output_limit: int = _DEFAULT_OUTPUT_LIMIT,
    environment: Mapping[str, str] | None = None,
) -> tuple[bool, str, tuple[str, ...]]:
    """Lightweight probe of a blenderplayer executable.

    Attempts to run ``blenderplayer --version`` (or bare invocation) and confirms
    a clean exit (returncode 0, no crash/GPU errors, completes within timeout).

    Returns a tuple of:
      - verified: bool — True if the player started and exited cleanly
      - reason_code: str — machine-readable outcome
      - diagnostics: tuple[str, ...] — any diagnostic messages
    """
    path = Path(player_path)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return (False, "blenderplayer_not_found", (str(exc),))

    if not resolved.is_file():
        return (False, "blenderplayer_not_a_file", (str(resolved),))

    env = _sanitized_probe_environment(environment)

    # Try --version first — lightweight, no GPU needed
    try:
        capture = _bounded_process(
            [str(resolved), "--version"],
            timeout_s=timeout_s,
            output_limit=output_limit,
            env=env,
        )
    except OSError as exc:
        return (False, "blenderplayer_start_failed", (str(exc),))

    if capture.timed_out:
        return (False, "blenderplayer_timeout", ("Probe timed out",))

    if capture.output_exceeded:
        return (False, "blenderplayer_output_limit", ("Output limit exceeded",))

    # blenderplayer --version may return 0 (prints version info) or may not support
    # --version and exit with non-zero. Accept returncode 0 as verified.
    # Also accept returncode 1 with version-like output (some builds print version then exit 1).
    stdout_lower = capture.stdout.lower()
    stderr_lower = capture.stderr.lower()
    combined_output = capture.stdout + capture.stderr

    # Check for GPU crash indicators
    gpu_error_indicators = ("gpu error", "opengl error", "segfault", "access violation")
    for indicator in gpu_error_indicators:
        if indicator in stdout_lower or indicator in stderr_lower:
            return (
                False,
                "blenderplayer_gpu_error",
                (f"GPU/crash indicator detected: {indicator}",),
            )

    if capture.returncode == 0:
        return (True, "blenderplayer_verified", ())

    # Some blenderplayer builds exit with 1 on --version but still produce output
    # indicating they started correctly. Accept if we see version-like text.
    version_indicators = ("blender", "upbge", "version")
    has_version_output = any(ind in stdout_lower or ind in stderr_lower for ind in version_indicators)
    if has_version_output and capture.returncode is not None and capture.returncode <= 1:
        return (True, "blenderplayer_verified", ())

    # Non-zero exit without version output — player may be broken
    detail = combined_output[-500:] if combined_output else f"exit code {capture.returncode}"
    return (False, "blenderplayer_probe_failed", (detail,))


def approved_upbge_locations(environment: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Return deterministic, application-approved installation locations."""
    env = os.environ if environment is None else environment
    candidates: list[Path] = []
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = env.get(variable)
            if root:
                base = Path(root)
                candidates.extend((
                    base / "UPBGE" / "upbge.exe",
                    base / "UPBGE" / "blender.exe",
                    base / "Programs" / "UPBGE" / "upbge.exe",
                    base / "Programs" / "UPBGE" / "blender.exe",
                ))
    elif sys_platform() == "darwin":
        candidates.extend((
            Path("/Applications/UPBGE.app/Contents/MacOS/UPBGE"),
            Path.home() / "Applications/UPBGE.app/Contents/MacOS/UPBGE",
        ))
    else:
        candidates.extend((Path("/opt/upbge/upbge"), Path("/usr/local/bin/upbge")))
    return tuple(dict.fromkeys(candidates))


def sys_platform() -> str:
    """Small seam for platform-specific tests without mutating global interpreter state."""
    import sys
    return sys.platform


def _candidate_paths(
    explicit_path: str | os.PathLike[str] | None,
    config: Mapping[str, object] | None,
    known_locations: Iterable[str | os.PathLike[str]] | None,
    environment: Mapping[str, str] | None,
) -> list[tuple[Path, str]]:
    ordered: list[tuple[Path, str]] = []
    configured = explicit_path or (config or {}).get("UPBGE_PATH")
    if configured:
        ordered.append((Path(str(configured)), "explicit_config"))
    locations = approved_upbge_locations(environment) if known_locations is None else tuple(
        Path(item) for item in known_locations
    )
    ordered.extend((path, "approved_location") for path in locations)
    search_path = (environment or os.environ).get("PATH")
    for command in ("upbge", "upbge.exe"):
        found = shutil.which(command, path=search_path)
        if found:
            ordered.append((Path(found), "path"))
    unique: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, source in ordered:
        key = os.path.normcase(os.path.abspath(os.fspath(path.expanduser())))
        if key not in seen:
            seen.add(key)
            unique.append((path, source))
    return unique


def _enrich_with_blenderplayer(
    report: UPBGECapabilityReport,
    *,
    environment: Mapping[str, str] | None = None,
) -> UPBGECapabilityReport:
    """Probe blenderplayer alongside the editor and return an enriched report.

    Since UPBGECapabilityReport is frozen, this constructs a new instance with
    blenderplayer fields populated.
    """
    player_path = discover_blenderplayer(report.executable_path)

    if player_path is None:
        # Editor found but blenderplayer absent
        base = report.to_dict()
        base["blenderplayer_path"] = None
        base["blenderplayer_available"] = False
        base["blenderplayer_verified"] = False
        base["blenderplayer_reason_code"] = "blenderplayer_not_found"
        base["blenderplayer_diagnostics"] = (
            f"No blenderplayer found alongside editor at {report.executable_path}",
        )
        # Preserve attempts as CapabilityAttempt instances (asdict converts them to dicts)
        base["attempts"] = report.attempts
        return UPBGECapabilityReport(**base)

    # blenderplayer file exists — probe it
    verified, reason_code, diagnostics = probe_blenderplayer(
        player_path, environment=environment
    )
    base = report.to_dict()
    base["blenderplayer_path"] = str(player_path)
    base["blenderplayer_available"] = True
    base["blenderplayer_verified"] = verified
    base["blenderplayer_reason_code"] = reason_code
    base["blenderplayer_diagnostics"] = diagnostics
    # Preserve attempts as CapabilityAttempt instances (asdict converts them to dicts)
    base["attempts"] = report.attempts
    return UPBGECapabilityReport(**base)


def discover_upbge(
    *,
    explicit_path: str | os.PathLike[str] | None = None,
    config: Mapping[str, object] | None = None,
    known_locations: Iterable[str | os.PathLike[str]] | None = None,
    environment: Mapping[str, str] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> UPBGECapabilityReport:
    """Discover and verify UPBGE in explicit, approved-location, then PATH order.

    ``UPBGE_PRODUCT_VERSION`` and ``UPBGE_BLENDER_API_VERSION`` are optional exact
    pins. A discovered UPBGE build that does not match either configured pin is
    reported truthfully as incompatible and discovery continues.

    Also probes blenderplayer alongside the discovered editor executable.
    """
    settings = config or {}
    required_product_version = settings.get("UPBGE_PRODUCT_VERSION")
    required_blender_api_version = settings.get("UPBGE_BLENDER_API_VERSION")
    for name, value in (
        ("UPBGE_PRODUCT_VERSION", required_product_version),
        ("UPBGE_BLENDER_API_VERSION", required_blender_api_version),
    ):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{name} must be a non-empty string when configured")
    attempts: list[CapabilityAttempt] = []
    reports: list[UPBGECapabilityReport] = []
    for candidate, source in _candidate_paths(
        explicit_path, config, known_locations, environment
    ):
        report = probe_upbge_executable(
            candidate,
            source=source,
            timeout_s=timeout_s,
            environment=environment,
            required_product_version=required_product_version,
            required_blender_api_version=required_blender_api_version,
        )
        reports.append(report)
        attempts.append(CapabilityAttempt(
            path=report.executable_path or str(candidate),
            source=source,
            status="accepted" if report.compatible else "rejected",
            reason_code=report.reason_code,
            detail="; ".join(report.diagnostics),
        ))
        if report.compatible:
            enriched = _enrich_with_blenderplayer(
                UPBGECapabilityReport(
                    **{k: v for k, v in report.to_dict().items() if k != "attempts"},
                    attempts=tuple(attempts),
                ),
                environment=environment,
            )
            return enriched
    if reports:
        # Preserve real incompatible-engine evidence instead of collapsing it into
        # an indistinguishable "not found" result.
        best = next((item for item in reports if item.available), reports[0])
        enriched = _enrich_with_blenderplayer(
            UPBGECapabilityReport(
                **{k: v for k, v in best.to_dict().items() if k != "attempts"},
                attempts=tuple(attempts),
            ),
            environment=environment,
        )
        return enriched
    return UPBGECapabilityReport(
        reason_code="upbge_not_found",
        diagnostics=(
            "No UPBGE executable was found in configured, approved, or PATH locations.",
        ),
        attempts=(),
    )
