"""Compilation bridge — wires photo pipeline WorldContract to existing UPBGE chain.

This module is the thin integration layer that passes a fully assembled
WorldContract from the photo pipeline to the existing compilation
infrastructure:

    WorldContract → build_compiler_plan → run_upbge_sidecar
                  → parity gate → smoke validation → auto_launch

No modifications are made to the existing compilation, parity gate, smoke
validation, or auto-launch modules. This bridge only orchestrates the calls
in the correct order and reports results.

Requirements: 1.2, 14.2, 14.3
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.auto_launch import LaunchResult, auto_launch_game
from src.parity_gates import StructuralParityReport, validate_upbge_inventory
from src.smoke_validator import SmokeValidationResult, run_structural_smoke
from src.upbge_capabilities import UPBGECapabilityReport, discover_upbge
from src.upbge_compiler import (
    CompilerOutputFlags,
    CompilerPlan,
    build_compiler_plan,
)
from src.upbge_sidecar import SidecarResult, run_upbge_sidecar
from src.world_contract import WorldContract

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompilationBridgeResult:
    """Result of the full compilation chain for a photo-pipeline WorldContract.

    Captures success/failure at each stage so the orchestrator can emit
    appropriate SSE events and record diagnostics.
    """

    success: bool
    reason_code: str
    diagnostic: str

    # Stage-level results (None if stage was not reached)
    compiler_plan: CompilerPlan | None = None
    sidecar_result: SidecarResult | None = None
    parity_result: StructuralParityReport | None = None
    smoke_result: SmokeValidationResult | None = None
    launch_result: LaunchResult | None = None

    # Paths to key artifacts
    runtime_candidate_path: Path | None = None
    inventory_path: Path | None = None

    # Timing
    total_duration_ms: int = 0


def run_compilation_chain(
    contract: WorldContract,
    session_dir: Path,
    *,
    upbge_path: str | None = None,
    fullscreen: bool = True,
    launch_timeout_s: float = 10.0,
    smoke_timeout_s: float = 15.0,
) -> CompilationBridgeResult:
    """Execute the full UPBGE compilation chain on an assembled WorldContract.

    This function is the single entry point for the photo pipeline to hand off
    a WorldContract to the existing compilation infrastructure. It runs
    synchronously through all stages in order:

        1. Discover UPBGE executable
        2. Build CompilerPlan (includes V-HACD, LOD at compile time)
        3. Run UPBGE sidecar compilation
        4. Run parity gate (validates scene inventory matches plan)
        5. Run smoke validation (structural checks via bpy headless)
        6. Auto-launch via blenderplayer

    Args:
        contract: The fully assembled and validated WorldContract from the
            photo pipeline assembler.
        session_dir: The photo session's output directory. A subdirectory
            ``photo_compile/`` will be created for compilation artifacts.
        upbge_path: Optional explicit path to UPBGE executable. If None,
            uses UPBGE_PATH environment variable or auto-discovery.
        fullscreen: Whether to launch blenderplayer in fullscreen mode.
        launch_timeout_s: Seconds to wait confirming blenderplayer is running.
        smoke_timeout_s: Timeout for smoke validation subprocess.

    Returns:
        CompilationBridgeResult capturing success/failure and all stage results.
    """
    started = time.monotonic()

    # --- Stage 1: Discover UPBGE ---
    explicit_path = upbge_path or os.getenv("UPBGE_PATH")
    capability = discover_upbge(explicit_path=explicit_path)

    if not capability.compatible or not capability.available:
        return CompilationBridgeResult(
            success=False,
            reason_code=capability.reason_code,
            diagnostic=(
                f"UPBGE not available: {'; '.join(capability.diagnostics)}"
            ),
            total_duration_ms=_elapsed_ms(started),
        )

    # --- Stage 2: Build CompilerPlan ---
    try:
        compiler_plan = build_compiler_plan(
            contract,
            outputs=CompilerOutputFlags(
                blend=True, runtime=True, render=False, glb=False
            ),
        )
    except (ValueError, TypeError) as exc:
        return CompilationBridgeResult(
            success=False,
            reason_code="compiler_plan_failed",
            diagnostic=f"Failed to build compiler plan: {exc}",
            total_duration_ms=_elapsed_ms(started),
        )

    runtime_plan = compiler_plan.runtime

    # --- Stage 3: Run UPBGE Sidecar Compilation ---
    compile_output_dir = session_dir / "photo_compile"
    compile_output_dir.mkdir(parents=True, exist_ok=True)

    canonical_bytes = contract.canonical_bytes()

    sidecar_result = run_upbge_sidecar(
        capability,
        canonical_bytes,
        compile_output_dir,
        outputs=CompilerOutputFlags(
            blend=True, runtime=True, render=False, glb=False
        ),
    )

    if not sidecar_result.success:
        # Check for partial success (scene.blend exists without runtime logic)
        runtime_candidate = None
        inventory_path = None
        if sidecar_result.output_dir:
            out_dir = Path(sidecar_result.output_dir)
            blend_file = out_dir / "scene.blend"
            inv_file = out_dir / "scene_inventory.json"
            if blend_file.is_file() and inv_file.is_file():
                runtime_candidate = blend_file
                inventory_path = inv_file
                logger.warning(
                    "Sidecar failed (%s) but scene.blend exists — "
                    "proceeding with partial compilation",
                    sidecar_result.reason_code,
                )
            else:
                return CompilationBridgeResult(
                    success=False,
                    reason_code=f"sidecar_{sidecar_result.reason_code}",
                    diagnostic=(
                        f"UPBGE sidecar compilation failed: "
                        f"{sidecar_result.reason_code}"
                    ),
                    compiler_plan=compiler_plan,
                    sidecar_result=sidecar_result,
                    total_duration_ms=_elapsed_ms(started),
                )
        else:
            return CompilationBridgeResult(
                success=False,
                reason_code=f"sidecar_{sidecar_result.reason_code}",
                diagnostic=(
                    f"UPBGE sidecar compilation failed: "
                    f"{sidecar_result.reason_code}"
                ),
                compiler_plan=compiler_plan,
                sidecar_result=sidecar_result,
                total_duration_ms=_elapsed_ms(started),
            )
    else:
        # Normal success path — locate artifacts
        artifact_map = {
            item.role: Path(item.path) for item in sidecar_result.artifacts
        }
        runtime_candidate = (
            artifact_map.get("runtime_candidate") or artifact_map.get("blend")
        )
        inventory_path = artifact_map.get("inventory")

    if runtime_candidate is None or inventory_path is None:
        return CompilationBridgeResult(
            success=False,
            reason_code="missing_artifacts",
            diagnostic=(
                "Sidecar did not produce expected .blend or inventory artifacts"
            ),
            compiler_plan=compiler_plan,
            sidecar_result=sidecar_result,
            total_duration_ms=_elapsed_ms(started),
        )

    # --- Stage 4: Parity Gate ---
    try:
        parity_report = validate_upbge_inventory(contract, inventory_path)
    except Exception as exc:
        logger.warning("Parity gate raised exception: %s", exc)
        return CompilationBridgeResult(
            success=False,
            reason_code="parity_gate_error",
            diagnostic=f"Parity gate error: {exc}",
            compiler_plan=compiler_plan,
            sidecar_result=sidecar_result,
            runtime_candidate_path=runtime_candidate,
            inventory_path=inventory_path,
            total_duration_ms=_elapsed_ms(started),
        )

    if not parity_report.passed:
        # Extract issue summary for diagnostics
        issue_summary = "parity_check_failed"
        if hasattr(parity_report, "issues") and parity_report.issues:
            issue_summary = "; ".join(
                f"{issue.code}@{issue.path}"
                for issue in parity_report.issues[:5]
            )
        return CompilationBridgeResult(
            success=False,
            reason_code="parity_failed",
            diagnostic=f"Parity gate failed: {issue_summary}",
            compiler_plan=compiler_plan,
            sidecar_result=sidecar_result,
            parity_result=parity_report,
            runtime_candidate_path=runtime_candidate,
            inventory_path=inventory_path,
            total_duration_ms=_elapsed_ms(started),
        )

    # --- Stage 5: Smoke Validation ---
    smoke_result: SmokeValidationResult | None = None
    try:
        if runtime_plan is not None:
            smoke_result = run_structural_smoke(
                capability,
                runtime_candidate,
                runtime_plan,
                timeout_s=smoke_timeout_s,
            )
        else:
            logger.info(
                "Skipping smoke validation — no RuntimePlan available"
            )
    except Exception as exc:
        logger.warning("Smoke validation raised exception: %s — proceeding", exc)

    # Smoke validation is non-blocking (graceful degradation):
    # failure logs a warning but does not abort the chain.
    if smoke_result and not smoke_result.passed:
        logger.warning(
            "Smoke validation did not pass (%s) — proceeding with launch",
            smoke_result.reason_code,
        )

    # --- Stage 6: Auto-Launch ---
    launch_result = auto_launch_game(
        capability,
        runtime_candidate,
        fullscreen=fullscreen,
        timeout_s=launch_timeout_s,
    )

    if launch_result.success:
        logger.info(
            "Photo pipeline game launched (PID %s)", launch_result.pid
        )
    else:
        logger.warning(
            "Auto-launch failed (%s): %s",
            launch_result.reason_code,
            launch_result.diagnostics,
        )

    return CompilationBridgeResult(
        success=launch_result.success,
        reason_code=launch_result.reason_code if launch_result.success else f"launch_{launch_result.reason_code}",
        diagnostic=(
            launch_result.diagnostics
            if launch_result.success
            else f"Auto-launch failed: {launch_result.diagnostics}"
        ),
        compiler_plan=compiler_plan,
        sidecar_result=sidecar_result,
        parity_result=parity_report,
        smoke_result=smoke_result,
        launch_result=launch_result,
        runtime_candidate_path=runtime_candidate,
        inventory_path=inventory_path,
        total_duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    """Compute elapsed milliseconds since a monotonic start time."""
    return int((time.monotonic() - started) * 1000)
