"""Tests for UPBGE 0.50 runtime pipeline orchestrator.

Verifies the graceful degradation chain:
- Probe timeout → fallback compile proceeds
- Compile failure → returns success=False with degradation event
- Smoke failure → returns with smoke_skipped degradation
- Full success path → returns success=True
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.runtime_pipeline_050 import (
    PipelineResult,
    _make_fallback_api_report,
    compile_runtime_050,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_upbge_path(tmp_path: Path) -> str:
    """Create a fake UPBGE executable path for testing."""
    fake_exe = tmp_path / "blender.exe"
    fake_exe.write_text("fake")
    return str(fake_exe)


@pytest.fixture
def fake_output_dir(tmp_path: Path) -> str:
    """Create a temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return str(out)


@pytest.fixture
def minimal_plan() -> dict:
    """Minimal plan dict with required keys."""
    return {
        "interactions": [],
        "player_args": {
            "move_speed": 4.0,
            "look_speed": 0.0025,
            "gravity": 9.81,
        },
    }


@pytest.fixture
def mock_object_by_id() -> dict:
    """Empty object mapping."""
    return {}


@pytest.fixture
def mock_camera_obj() -> MagicMock:
    """Mock camera object."""
    return MagicMock(name="MockCamera")


@pytest.fixture
def valid_api_report() -> UPBGEComponentAPI:
    """A valid probe report with native component API."""
    return UPBGEComponentAPI(
        has_game_attr=True,
        has_components_attr=True,
        component_api_path="obj.game.components",
        component_add_method="obj.game.components.new()",
        has_logic_ops=True,
        physics_api_path="obj.game.physics_type",
        has_game_physics=True,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=False,
    )


# ---------------------------------------------------------------------------
# Tests for _make_fallback_api_report
# ---------------------------------------------------------------------------


class TestMakeFallbackApiReport:
    """Tests for the fallback API report generator."""

    def test_fallback_report_has_fallback_required_true(self):
        report = _make_fallback_api_report()
        assert report.fallback_required is True

    def test_fallback_report_has_no_component_api(self):
        report = _make_fallback_api_report()
        assert report.component_api_path is None
        assert report.component_add_method is None

    def test_fallback_report_has_no_physics_api(self):
        report = _make_fallback_api_report()
        assert report.has_game_physics is False
        assert report.physics_api_path is None

    def test_fallback_report_upbge_not_detected(self):
        report = _make_fallback_api_report()
        assert report.upbge_detected is False

    def test_fallback_report_blender_version_zeroed(self):
        report = _make_fallback_api_report()
        assert report.blender_version == (0, 0, 0)


# ---------------------------------------------------------------------------
# Tests for probe failure → fallback compile
# ---------------------------------------------------------------------------


class TestProbeFailureDegradation:
    """When the API probe fails, compile should proceed with a fallback report."""

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_probe_timeout_uses_fallback_and_continues(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
    ):
        """Probe timeout should log degradation and proceed with fallback."""
        mock_probe.side_effect = ValueError("probe_timeout")
        mock_smoke.return_value = {"passed": True, "reason_code": "smoke_passed"}

        # Create a fake runtime_candidate.blend so smoke doesn't fail on missing file
        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert isinstance(result, PipelineResult)
        # Should have a degradation event about the probe failing
        assert any("probe_failed" in evt for evt in result.degradation_events)
        # The api_report used should be the fallback
        assert result.api_report is not None
        assert result.api_report.fallback_required is True

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_probe_parse_error_uses_fallback(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
    ):
        """Probe parse error should degrade gracefully."""
        mock_probe.side_effect = ValueError("probe_parse_error: PROBE_RESULT= marker not found")
        mock_smoke.return_value = {"passed": True, "reason_code": "smoke_passed"}

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert any("probe_failed" in evt for evt in result.degradation_events)
        assert "probe_parse_error" in result.degradation_events[0]

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_probe_version_mismatch_uses_fallback(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
    ):
        """Probe version_mismatch should degrade gracefully."""
        mock_probe.side_effect = ValueError("version_mismatch")
        mock_smoke.return_value = {"passed": True, "reason_code": "smoke_passed"}

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert any("probe_failed" in evt for evt in result.degradation_events)
        assert "version_mismatch" in result.degradation_events[0]


# ---------------------------------------------------------------------------
# Tests for compile failure → success=False with degradation
# ---------------------------------------------------------------------------


class TestCompileFailureDegradation:
    """When compile fails, should return success=False with degradation event."""

    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050._try_import_bpy")
    @patch("src.assembler.component_attach_050._configure_runtime_050")
    def test_compile_failure_returns_false(
        self,
        mock_configure,
        mock_try_bpy,
        mock_probe,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Compile failure should return success=False with degradation."""
        mock_probe.return_value = valid_api_report
        mock_try_bpy.return_value = MagicMock(name="bpy")
        mock_configure.side_effect = ValueError("Unrecoverable save failure")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is False
        assert result.runtime_path is None
        assert any("compile_failed" in evt for evt in result.degradation_events)

    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050._try_import_bpy")
    @patch("src.assembler.component_attach_050._configure_runtime_050")
    def test_compile_failure_includes_error_message(
        self,
        mock_configure,
        mock_try_bpy,
        mock_probe,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Compile failure degradation event should include the error message."""
        error_msg = "No player can be created"
        mock_probe.return_value = valid_api_report
        mock_try_bpy.return_value = MagicMock(name="bpy")
        mock_configure.side_effect = ValueError(error_msg)

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is False
        compile_events = [e for e in result.degradation_events if "compile_failed" in e]
        assert len(compile_events) == 1
        assert error_msg in compile_events[0]


# ---------------------------------------------------------------------------
# Tests for smoke failure → smoke_skipped degradation
# ---------------------------------------------------------------------------


class TestSmokeFailureDegradation:
    """When smoke validation fails, should proceed with smoke_skipped."""

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_smoke_exception_results_in_smoke_skipped(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Smoke exception should result in smoke_skipped degradation."""
        mock_probe.return_value = valid_api_report
        mock_smoke.side_effect = OSError("Cannot execute UPBGE")

        # Create fake runtime_candidate.blend
        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert any("smoke_skipped" in evt for evt in result.degradation_events)
        assert result.smoke_result == {"passed": False, "reason_code": "smoke_skipped"}

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_smoke_failure_returns_not_passed(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Smoke returning passed=False should still return a PipelineResult."""
        mock_probe.return_value = valid_api_report
        mock_smoke.return_value = {
            "passed": False,
            "reason_code": "player_component_missing",
            "detail": "No player component found",
        }

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is False
        assert result.runtime_path is not None
        assert result.smoke_result["reason_code"] == "player_component_missing"


# ---------------------------------------------------------------------------
# Tests for full success path
# ---------------------------------------------------------------------------


class TestFullSuccessPath:
    """When all stages succeed, should return success=True."""

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_full_success_returns_true(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """All stages passing should return success=True."""
        mock_probe.return_value = valid_api_report
        mock_smoke.return_value = {
            "passed": True,
            "reason_code": "smoke_passed",
            "detail": "All checks passed",
            "checks": {},
        }

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is True
        assert result.runtime_path is not None
        assert result.smoke_result["passed"] is True

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_full_success_has_no_degradation_events(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Full success path should have minimal degradation events."""
        mock_probe.return_value = valid_api_report
        mock_smoke.return_value = {
            "passed": True,
            "reason_code": "smoke_passed",
        }

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        # The only degradation that's acceptable is compile_deferred (bpy not on host)
        non_deferred = [
            e for e in result.degradation_events
            if "compile_deferred" not in e
        ]
        assert len(non_deferred) == 0

    @patch("src.assembler.runtime_pipeline_050._try_import_bpy", return_value=None)
    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    def test_full_success_includes_api_report(
        self,
        mock_smoke,
        mock_probe,
        mock_try_bpy,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """Success should include the api_report that was used."""
        mock_probe.return_value = valid_api_report
        mock_smoke.return_value = {"passed": True, "reason_code": "smoke_passed"}

        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.api_report is valid_api_report
        assert result.api_report.upbge_detected is True


# ---------------------------------------------------------------------------
# Tests for bpy unavailability (host-side orchestration)
# ---------------------------------------------------------------------------


class TestBpyUnavailable:
    """When bpy is not importable, compile defers to subprocess."""

    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050.run_structural_smoke_050")
    @patch("src.assembler.runtime_pipeline_050._try_import_bpy")
    def test_no_bpy_with_existing_blend_proceeds_to_smoke(
        self,
        mock_try_bpy,
        mock_smoke,
        mock_probe,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """If bpy unavailable but .blend exists, should proceed to smoke."""
        mock_probe.return_value = valid_api_report
        mock_try_bpy.return_value = None
        mock_smoke.return_value = {"passed": True, "reason_code": "smoke_passed"}

        # Create the runtime_candidate.blend that the subprocess would produce
        runtime_path = Path(fake_output_dir) / "runtime_candidate.blend"
        runtime_path.write_bytes(b"fake blend data")

        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is True
        assert any("compile_deferred" in evt for evt in result.degradation_events)

    @patch("src.assembler.runtime_pipeline_050.run_api_probe")
    @patch("src.assembler.runtime_pipeline_050._try_import_bpy")
    def test_no_bpy_and_no_blend_returns_failure(
        self,
        mock_try_bpy,
        mock_probe,
        fake_upbge_path,
        fake_output_dir,
        minimal_plan,
        mock_object_by_id,
        mock_camera_obj,
        valid_api_report,
    ):
        """If bpy unavailable and no .blend exists, should return failure."""
        mock_probe.return_value = valid_api_report
        mock_try_bpy.return_value = None

        # Don't create runtime_candidate.blend
        result = compile_runtime_050(
            upbge_path=fake_upbge_path,
            plan=minimal_plan,
            object_by_id=mock_object_by_id,
            camera_obj=mock_camera_obj,
            output_dir=fake_output_dir,
        )

        assert result.success is False
        assert result.runtime_path is None
        assert any("compile_failed" in evt for evt in result.degradation_events)
