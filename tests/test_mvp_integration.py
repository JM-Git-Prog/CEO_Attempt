"""Integration test for the full MVP pipeline with mock LLM calls.

Tests end-to-end flow: user text → interpret → plan (mocked) → scene graph →
contract → compile (mocked) → parity → smoke (mocked) → launch (mocked) → result.

Uses deterministic plan/scene data from the flywheel corpus test fixture.

Requirements: 1.1, 1.2, 1.3
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.auto_launch import LaunchResult
from src.floor_plan.models import FloorPlan, PlanValidationReport
from src.models import (
    MVPPipelineResult,
    PipelineState,
    SceneConcept,
    SceneGraph,
    SessionMode,
)
from src.parity_gates import NumericTolerances, StructuralParityReport
from src.pipeline import WorldBuilder, validate_input
from src.smoke_validator import SmokeCheck, SmokeValidationResult
from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_sidecar import SIDECAR_RESULT_VERSION, SidecarArtifact, SidecarResult

# ---------------------------------------------------------------------------
# Fixture data loaded from the flywheel corpus characterization file
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"


@pytest.fixture
def fixture_data():
    """Load the characterization fixture with plan + scene_graph."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def deterministic_plan(fixture_data):
    """Return a validated FloorPlan from the flywheel corpus."""
    return FloorPlan.model_validate(fixture_data["plan"])


@pytest.fixture
def deterministic_scene_graph(fixture_data):
    """Return a validated SceneGraph from the flywheel corpus."""
    return SceneGraph.model_validate(fixture_data["scene_graph"])


@pytest.fixture
def mock_concept():
    """Return a deterministic SceneConcept for the test prompt."""
    return SceneConcept(
        era="contemporary",
        mood="warm",
        palette="earth tones with cream walls",
        architecture_notes="Simple rectangular room with wooden floor",
        key_objects=["bookshelf", "armchair"],
        lighting_notes="Warm ambient from a floor lamp",
        image_prompt="A cozy reading room with bookshelf and armchair",
    )


@pytest.fixture
def mock_capability(tmp_path):
    """Return a mock UPBGECapabilityReport with compatible=True."""
    exe = tmp_path / "upbge.exe"
    exe.write_bytes(b"fake")
    player = tmp_path / "blenderplayer.exe"
    player.write_bytes(b"fake")
    return UPBGECapabilityReport(
        available=True,
        verified=True,
        compatible=True,
        executable_path=str(exe),
        product="UPBGE",
        product_version="0.36.1",
        supports_game_runtime=True,
        supports_eevee=True,
        supports_gltf=True,
        reason_code="verified",
        blenderplayer_path=str(player),
        blenderplayer_available=True,
        blenderplayer_verified=True,
        blenderplayer_reason_code="verified",
    )


# ---------------------------------------------------------------------------
# Integration test: full MVP pipeline with all external deps mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_mvp_pipeline_success(
    tmp_path,
    monkeypatch,
    fixture_data,
    deterministic_plan,
    deterministic_scene_graph,
    mock_concept,
    mock_capability,
):
    """End-to-end MVP pipeline test: text → interpret → plan → scene graph →
    contract → compile → parity → smoke → launch → MVPPipelineResult.

    All LLM calls, UPBGE subprocesses, and blenderplayer are mocked.
    Verifies: success, artifact_path, quality_label, launch, stage progression.
    """
    # Redirect output directory so no real filesystem pollution
    monkeypatch.setattr("src.pipeline.OUTPUT_BASE", tmp_path)

    # Create the builder
    builder = WorldBuilder(session_id="integration-test", interface_version=11)

    # --- Mock 1: interpret_description (LLM) ---
    async def fake_interpret(description, *, timeout_seconds=None):
        return mock_concept

    monkeypatch.setattr(
        "src.pipeline.interpret_description", fake_interpret
    )

    # --- Mock 2: generate_plan_with_ladder (LLM plan generation) ---
    async def fake_plan_with_ladder(description, concept, *, tolerance="mvp"):
        validation_report = PlanValidationReport(valid=True)
        return (deterministic_plan, [], validation_report, "planner-probe-v1:latest", 1)

    monkeypatch.setattr(
        "src.pipeline.generate_plan_with_ladder", fake_plan_with_ladder
    )

    # --- Mock 3: build_scene_graph (LLM scene graph builder) ---
    async def fake_build_scene_graph(concept, plan, *, timeout_seconds=None, enforce_plan_lights=True):
        return deterministic_scene_graph

    monkeypatch.setattr(
        "src.pipeline.build_scene_graph", fake_build_scene_graph
    )

    # --- Mock 4: discover_upbge ---
    monkeypatch.setattr(
        "src.pipeline.discover_upbge", lambda explicit_path=None: mock_capability
    )

    # --- Mock 5: run_upbge_sidecar (UPBGE subprocess compilation) ---
    # Create fake artifacts the pipeline expects
    compile_dir = tmp_path / "integration-test" / "mvp_compile"
    compile_dir.mkdir(parents=True, exist_ok=True)
    runtime_blend = compile_dir / "runtime_candidate.blend"
    runtime_blend.write_bytes(b"BLENDER_FAKE_RUNTIME")
    inventory_file = compile_dir / "scene_inventory.json"

    # Write an inventory that will pass the parity gate.
    # We need it to match the WorldContract object IDs — write a placeholder and
    # override parity validation directly below.

    def fake_sidecar(capability, contract_bytes, output_dir, *, outputs=None):
        # Create artifacts in output_dir consistent with expected roles
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        blend = out / "runtime_candidate.blend"
        blend.write_bytes(b"BLENDER_FAKE_RUNTIME")
        inv = out / "scene_inventory.json"
        inv.write_text("{}", encoding="utf-8")
        return SidecarResult(
            schema_version=SIDECAR_RESULT_VERSION,
            success=True,
            status="completed",
            reason_code="success",
            output_dir=str(out),
            artifacts=(
                SidecarArtifact(role="runtime_candidate", path=str(blend), bytes=blend.stat().st_size),
                SidecarArtifact(role="inventory", path=str(inv), bytes=inv.stat().st_size),
            ),
            return_code=0,
            duration_ms=500,
            stdout_tail="",
            stderr_tail="",
            violated_limit=None,
            isolation_controls=("wall_time", "output_size"),
            isolation_limitations=(),
        )

    monkeypatch.setattr("src.pipeline.run_upbge_sidecar", fake_sidecar)

    # --- Mock 6: validate_upbge_inventory (parity gate) ---
    def fake_parity(contract, path, tolerances=None):
        return StructuralParityReport(
            target="upbge",
            world_contract_hash=contract.content_hash(),
            passed=True,
            artifact_accepted=True,
            tolerances=NumericTolerances(),
        )

    monkeypatch.setattr("src.pipeline.validate_upbge_inventory", fake_parity)

    # --- Mock 7: run_structural_smoke (UPBGE headless bpy checks) ---
    def fake_smoke(capability, blend_path, runtime_plan, *, timeout_s=15.0):
        return SmokeValidationResult(
            passed=True,
            checks=(
                SmokeCheck(name="scene_loads", passed=True, detail="OK"),
                SmokeCheck(name="player_controller_exists", passed=True, detail="OK"),
                SmokeCheck(name="character_physics", passed=True, detail="OK"),
                SmokeCheck(name="logic_bricks_wired", passed=True, detail="OK"),
            ),
            reason_code="structural_ok",
            duration_ms=200,
        )

    monkeypatch.setattr("src.pipeline.run_structural_smoke", fake_smoke)

    # --- Mock 8: auto_launch_game (blenderplayer subprocess) ---
    def fake_launch(capability, blend_path, *, fullscreen=True, timeout_s=10.0):
        return LaunchResult(
            success=True,
            pid=99999,
            executable=str(capability.blenderplayer_path),
            blend_path=str(blend_path),
            reason_code="launched",
            diagnostics="blenderplayer running (PID 99999)",
            fallback_instructions=None,
        )

    monkeypatch.setattr("src.pipeline.auto_launch_game", fake_launch)

    # --- Execute the pipeline ---
    result = await builder.run_mvp(
        "a cozy reading room with a bookshelf and armchair"
    )

    # --- Assertions ---
    assert result.success is True
    assert result.artifact_path is not None
    assert result.quality_label == "smoke_structural"
    assert result.launch_result is not None
    assert result.launch_result.success is True
    assert result.launch_result.pid == 99999
    assert result.model_used == "planner-probe-v1:latest"
    assert result.attempts == 1
    assert result.failure_stage is None
    assert result.failure_reason_code is None
    assert result.duration_ms > 0

    # Verify the pipeline went through all stages (check session.progress_messages)
    msgs = builder.session.progress_messages
    # SSE events emitted at stage transitions
    sse_stages = [m for m in msgs if m.startswith("sse:")]
    # We expect at least: interpreting, planning, building_scene, compiling, validating, launching, game_running
    sse_stage_names = [s.split(":")[1] for s in sse_stages]
    assert "interpreting" in sse_stage_names
    assert "planning" in sse_stage_names
    assert "building_scene" in sse_stage_names
    assert "compiling" in sse_stage_names
    assert "validating" in sse_stage_names
    assert "launching" in sse_stage_names
    assert "game_running" in sse_stage_names

    # Session should be in READY state
    assert builder.session.state == PipelineState.READY
    assert builder.session.mode == SessionMode.MVP
    assert builder.session.game_pid == 99999
    assert builder.session.quality_label == "smoke_structural"


@pytest.mark.asyncio
async def test_mvp_pipeline_input_validation_rejects_empty(tmp_path, monkeypatch):
    """Empty string input should fail at input validation gate before any LLM call."""
    monkeypatch.setattr("src.pipeline.OUTPUT_BASE", tmp_path)

    builder = WorldBuilder(session_id="empty-input-test", interface_version=11)

    # No mocks needed — pipeline should fail at input validation
    result = await builder.run_mvp("")

    assert result.success is False
    assert result.failure_stage == "input_validation"
    assert result.failure_reason_code == "empty_input"
    assert result.artifact_path is None
    assert result.launch_result is None


@pytest.mark.asyncio
async def test_mvp_pipeline_input_validation_rejects_too_short(tmp_path, monkeypatch):
    """Strings < 3 chars should fail at input validation."""
    monkeypatch.setattr("src.pipeline.OUTPUT_BASE", tmp_path)

    builder = WorldBuilder(session_id="short-input-test", interface_version=11)

    result = await builder.run_mvp("ab")

    assert result.success is False
    assert result.failure_stage == "input_validation"
    assert result.failure_reason_code == "too_short"
