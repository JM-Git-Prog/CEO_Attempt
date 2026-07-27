"""UPBGE 0.50 Runtime Pipeline Orchestrator.

HOST-side module that coordinates the full probe → compile → validate → launch
pipeline for UPBGE 0.50 component-based runtimes. This module runs on the host
Python process and invokes UPBGE headlessly via subprocesses. It does NOT import
bpy.

The pipeline stages are:
1. API Probe — discover the UPBGE 0.50 component/physics API surface
2. Compile — invoke the compile script inside UPBGE to build runtime_candidate.blend
3. Validate — run the smoke probe to verify structural integrity
4. Launch — start blenderplayer with the validated .blend

Each stage has graceful degradation:
- Probe fails → attempt compile with a fallback API report
- Compile fails → return success=False with degradation event
- Smoke fails → proceed with smoke_skipped degradation event
- Launch fails → return with download fallback instructions

Requirements: 5.1, 5.6, 5.7, 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.assembler.api_probe_050 import UPBGEComponentAPI, run_api_probe
from src.smoke_validator import run_structural_smoke_050

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback API Report
# ---------------------------------------------------------------------------


def _make_fallback_api_report() -> UPBGEComponentAPI:
    """Create a fallback API report when the probe cannot be run.

    Returns a UPBGEComponentAPI with all APIs marked as unavailable and
    fallback_required=True, so the compiler uses the ID-property + bootstrap
    path for component attachment.
    """
    return UPBGEComponentAPI(
        has_game_attr=False,
        has_components_attr=False,
        component_api_path=None,
        component_add_method=None,
        has_logic_ops=False,
        physics_api_path=None,
        has_game_physics=False,
        blender_version=(0, 0, 0),
        upbge_detected=False,
        fallback_required=True,
    )


# ---------------------------------------------------------------------------
# Pipeline Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineResult:
    """Result of the full probe → compile → validate pipeline.

    Attributes:
        success: True if the smoke validator passed (or was skipped with
            a valid runtime_candidate produced).
        runtime_path: Path to the runtime_candidate.blend (None if compile failed).
        smoke_result: Dict from run_structural_smoke_050 (None if smoke was not run).
        api_report: The UPBGEComponentAPI used for compilation.
        degradation_events: List of strings describing each degradation that occurred.
    """

    success: bool
    runtime_path: str | None
    smoke_result: dict | None
    api_report: UPBGEComponentAPI | None
    degradation_events: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------


def compile_runtime_050(
    upbge_path: str,
    plan: dict,
    object_by_id: dict[str, Any],
    camera_obj: Any,
    output_dir: str,
    *,
    probe_timeout_s: float = 15.0,
    smoke_timeout_s: float = 30.0,
) -> PipelineResult:
    """Full UPBGE 0.50 compilation pipeline: probe → compile → validate.

    This function runs on the HOST (not inside UPBGE). It orchestrates:
    1. Running the API probe subprocess to discover UPBGE's component API
    2. Invoking the compile-time configuration (which runs inside UPBGE)
    3. Running the smoke validator to verify structural integrity

    The compile step (_configure_runtime_050) runs INSIDE UPBGE's embedded Python
    where bpy is available. This orchestrator passes the api_report to it.

    Graceful degradation chain:
    - Probe fails → use fallback report (all APIs unavailable, bootstrap path)
    - Compile fails → return success=False with degradation event
    - Smoke fails → return with smoke_skipped degradation event

    Args:
        upbge_path: Absolute path to the UPBGE executable (blender.exe).
        plan: Runtime plan dict with 'interactions' and 'player_args' keys.
        object_by_id: Mapping of stable object IDs to object references.
        camera_obj: The camera object to parent to the player.
        output_dir: Directory where runtime_candidate.blend will be saved.
        probe_timeout_s: Timeout for the API probe subprocess (default 15s).
        smoke_timeout_s: Timeout for the smoke validation subprocess (default 30s).

    Returns:
        PipelineResult with success status, paths, and degradation events.
    """
    degradation_events: list[str] = []

    # -----------------------------------------------------------------------
    # Step 1: Run API probe
    # -----------------------------------------------------------------------
    api_report: UPBGEComponentAPI
    try:
        api_report = run_api_probe(upbge_path, timeout_s=probe_timeout_s)
        logger.info(
            "API probe succeeded: upbge_detected=%s, component_api_path=%s",
            api_report.upbge_detected,
            api_report.component_api_path,
        )
    except ValueError as exc:
        reason = str(exc)
        degradation_events.append(f"probe_failed: {reason}")
        logger.warning(
            "API probe failed (%s) — using fallback API report", reason
        )
        api_report = _make_fallback_api_report()

    # -----------------------------------------------------------------------
    # Step 2: Configure runtime (compile)
    # -----------------------------------------------------------------------
    # The actual _configure_runtime_050() call happens inside UPBGE's embedded
    # Python. From the host side, we check if bpy is available (i.e. we're
    # running inside UPBGE). If not, we verify that the compile subprocess
    # has already produced the .blend.
    from src.assembler.component_attach_050 import _configure_runtime_050

    try:
        runtime_path = str(Path(output_dir) / "runtime_candidate.blend")

        if _try_import_bpy() is not None:
            # Running inside UPBGE — compile directly
            bpy = _try_import_bpy()
            player_obj = _configure_runtime_050(
                bpy, plan, object_by_id, camera_obj, api_report
            )
        else:
            # Running on the host — compile step is deferred to the UPBGE
            # subprocess (upbge_compile.py). We verify the output exists.
            degradation_events.append(
                "compile_deferred: bpy unavailable on host — "
                "compile runs inside UPBGE subprocess via upbge_compile.py"
            )
            if not Path(runtime_path).exists():
                degradation_events.append(
                    "compile_failed: runtime_candidate.blend not found at "
                    f"{runtime_path}"
                )
                return PipelineResult(
                    success=False,
                    runtime_path=None,
                    smoke_result=None,
                    api_report=api_report,
                    degradation_events=tuple(degradation_events),
                )

    except ValueError as exc:
        degradation_events.append(f"compile_failed: {exc}")
        logger.error("Runtime compilation failed: %s", exc)
        return PipelineResult(
            success=False,
            runtime_path=None,
            smoke_result=None,
            api_report=api_report,
            degradation_events=tuple(degradation_events),
        )

    # -----------------------------------------------------------------------
    # Step 3: Validate (smoke)
    # -----------------------------------------------------------------------
    smoke_result: dict | None
    try:
        smoke_result = run_structural_smoke_050(
            upbge_path, runtime_path, timeout_s=smoke_timeout_s
        )
        if smoke_result.get("passed"):
            logger.info("Smoke validation passed")
        else:
            reason_code = smoke_result.get("reason_code", "unknown")
            detail = smoke_result.get("detail", "")
            logger.warning(
                "Smoke validation failed: %s — %s", reason_code, detail
            )
    except Exception as exc:
        degradation_events.append(f"smoke_skipped: {exc}")
        logger.warning(
            "Smoke validation skipped due to error: %s", exc
        )
        smoke_result = {"passed": False, "reason_code": "smoke_skipped"}

    return PipelineResult(
        success=smoke_result.get("passed", False),
        runtime_path=runtime_path,
        smoke_result=smoke_result,
        api_report=api_report,
        degradation_events=tuple(degradation_events),
    )


# ---------------------------------------------------------------------------
# Full Pipeline with Launch
# ---------------------------------------------------------------------------


def run_full_pipeline_050(
    upbge_path: str,
    plan: dict,
    object_by_id: dict[str, Any],
    camera_obj: Any,
    output_dir: str,
    *,
    probe_timeout_s: float = 15.0,
    smoke_timeout_s: float = 30.0,
    launch_timeout_s: float = 10.0,
    fullscreen: bool = True,
) -> dict[str, Any]:
    """Full UPBGE 0.50 pipeline: probe → compile → validate → launch.

    Extends compile_runtime_050 with the launch step and download fallback.

    Graceful degradation chain:
    - Probe fails → attempt compile with fallback report
    - Compile fails → scene-only .blend, download fallback
    - Smoke fails → proceed with smoke_skipped
    - Launch fails → download fallback instructions

    Args:
        upbge_path: Path to the UPBGE 0.50 executable.
        plan: Runtime plan dict.
        object_by_id: Mapping of stable object IDs to object references.
        camera_obj: The camera object.
        output_dir: Output directory for runtime_candidate.blend.
        probe_timeout_s: Timeout for API probe (default 15s).
        smoke_timeout_s: Timeout for smoke validation (default 30s).
        launch_timeout_s: Timeout for launch confirmation (default 10s).
        fullscreen: Whether to launch in fullscreen mode.

    Returns:
        Dict with keys: success, runtime_path, smoke_result, launch_result,
        degradation_events, download_fallback.
    """
    # Run probe → compile → validate
    pipeline_result = compile_runtime_050(
        upbge_path=upbge_path,
        plan=plan,
        object_by_id=object_by_id,
        camera_obj=camera_obj,
        output_dir=output_dir,
        probe_timeout_s=probe_timeout_s,
        smoke_timeout_s=smoke_timeout_s,
    )

    degradation_events = list(pipeline_result.degradation_events)
    result: dict[str, Any] = {
        "success": pipeline_result.success,
        "runtime_path": pipeline_result.runtime_path,
        "smoke_result": pipeline_result.smoke_result,
        "api_report": pipeline_result.api_report,
        "launch_result": None,
        "degradation_events": degradation_events,
        "download_fallback": None,
    }

    # If compile failed, provide download fallback
    if not pipeline_result.runtime_path:
        scene_blend = str(Path(output_dir) / "scene.blend")
        if Path(scene_blend).exists():
            result["download_fallback"] = scene_blend
            degradation_events.append(
                "download_fallback: serving scene.blend (walkability unavailable)"
            )
        else:
            degradation_events.append(
                "download_fallback: no scene.blend available either"
            )
        result["success"] = False
        result["degradation_events"] = degradation_events
        return result

    # Attempt launch (only if runtime_path exists)
    runtime_path = Path(pipeline_result.runtime_path)
    if not runtime_path.exists():
        degradation_events.append(
            f"launch_skipped: runtime_candidate.blend not found at {runtime_path}"
        )
        result["download_fallback"] = str(runtime_path)
        result["degradation_events"] = degradation_events
        return result

    try:
        from src.auto_launch import auto_launch_game
        from src.upbge_capabilities import UPBGECapabilityReport

        # Build a minimal capability report for the launch
        # The caller should normally pass a full report; we construct one
        # from the upbge_path for convenience
        blenderplayer_path = _derive_blenderplayer_path(upbge_path)

        capability = UPBGECapabilityReport(
            executable_path=upbge_path,
            blenderplayer_path=blenderplayer_path,
            blenderplayer_available=blenderplayer_path is not None,
            blenderplayer_reason_code=(
                "found" if blenderplayer_path else "not_found"
            ),
            blenderplayer_diagnostics=[],
        )

        launch_result = auto_launch_game(
            capability,
            runtime_path,
            fullscreen=fullscreen,
            timeout_s=launch_timeout_s,
        )

        result["launch_result"] = launch_result
        if not launch_result.success:
            degradation_events.append(
                f"launch_failed: {launch_result.reason_code} — "
                f"{launch_result.diagnostics}"
            )
            result["download_fallback"] = str(runtime_path)
            if launch_result.fallback_instructions:
                result["fallback_instructions"] = (
                    launch_result.fallback_instructions
                )

    except Exception as exc:
        degradation_events.append(f"launch_failed: {exc}")
        result["download_fallback"] = str(runtime_path)

    result["degradation_events"] = degradation_events
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import_bpy():
    """Attempt to import bpy. Returns the module or None if unavailable.

    This is a seam for testing — allows mocking without patching importlib globally.
    """
    try:
        import bpy  # noqa: F401
        return bpy
    except ImportError:
        return None


def _derive_blenderplayer_path(upbge_path: str) -> str | None:
    """Derive blenderplayer path from the UPBGE editor path.

    Assumes blenderplayer is in the same directory as the editor executable.
    """
    editor = Path(upbge_path)
    blenderplayer = editor.parent / "blenderplayer.exe"
    if blenderplayer.exists():
        return str(blenderplayer)
    # Try without .exe (Linux/macOS)
    blenderplayer_unix = editor.parent / "blenderplayer"
    if blenderplayer_unix.exists():
        return str(blenderplayer_unix)
    return None
