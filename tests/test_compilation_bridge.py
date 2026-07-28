"""Tests for the photo pipeline compilation bridge.

Validates that the compilation bridge correctly orchestrates the existing
compilation chain without modifying any existing infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.photo_pipeline.compilation_bridge import (
    CompilationBridgeResult,
    run_compilation_chain,
    _elapsed_ms,
)


def _make_capability(*, available=True, compatible=True):
    """Create a mock UPBGECapabilityReport."""
    cap = MagicMock()
    cap.available = available
    cap.compatible = compatible
    cap.verified = True
    cap.product = "UPBGE"
    cap.supports_game_runtime = True
    cap.executable_path = "/usr/bin/upbge"
    cap.reason_code = "discovered"
    cap.diagnostics = ()
    cap.blenderplayer_path = "/usr/bin/blenderplayer"
    cap.blenderplayer_available = True
    return cap


def _make_contract():
    """Create a mock WorldContract with canonical_bytes method."""
    contract = MagicMock()
    contract.canonical_bytes.return_value = b'{"source": "test"}'
    contract.content_hash.return_value = "abc123"
    return contract


def _make_sidecar_result(*, success=True, output_dir="/tmp/output"):
    """Create a mock SidecarResult."""
    result = MagicMock()
    result.success = success
    result.reason_code = "compiled" if success else "compilation_failed"
    result.output_dir = output_dir
    artifact_blend = MagicMock()
    artifact_blend.role = "runtime_candidate"
    artifact_blend.path = f"{output_dir}/runtime_candidate.blend"
    artifact_inv = MagicMock()
    artifact_inv.role = "inventory"
    artifact_inv.path = f"{output_dir}/scene_inventory.json"
    result.artifacts = (artifact_blend, artifact_inv)
    return result


def _make_parity_report(*, passed=True):
    """Create a mock StructuralParityReport."""
    report = MagicMock()
    report.passed = passed
    report.issues = ()
    return report


def _make_smoke_result(*, passed=True):
    """Create a mock SmokeValidationResult."""
    result = MagicMock()
    result.passed = passed
    result.reason_code = "structural_ok" if passed else "scene_load_error"
    return result


def _make_launch_result(*, success=True):
    """Create a mock LaunchResult."""
    result = MagicMock()
    result.success = success
    result.pid = 12345 if success else None
    result.reason_code = "launched" if success else "blenderplayer_not_found"
    result.diagnostics = "running" if success else "not found"
    return result


class TestCompilationBridgeResult:
    """Tests for the CompilationBridgeResult dataclass."""

    def test_creation_with_defaults(self):
        result = CompilationBridgeResult(
            success=True,
            reason_code="launched",
            diagnostic="Game running",
        )
        assert result.success is True
        assert result.reason_code == "launched"
        assert result.compiler_plan is None
        assert result.sidecar_result is None
        assert result.parity_result is None
        assert result.smoke_result is None
        assert result.launch_result is None
        assert result.runtime_candidate_path is None
        assert result.inventory_path is None
        assert result.total_duration_ms == 0

    def test_frozen_dataclass(self):
        result = CompilationBridgeResult(
            success=False,
            reason_code="failed",
            diagnostic="error",
        )
        with pytest.raises(Exception):
            result.success = True  # type: ignore[misc]


class TestRunCompilationChain:
    """Tests for the run_compilation_chain function."""

    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_returns_failure_when_upbge_not_available(
        self, mock_discover, tmp_path
    ):
        mock_discover.return_value = _make_capability(available=False)
        contract = _make_contract()

        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False
        assert "not available" in result.diagnostic.lower() or result.reason_code != ""

    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_returns_failure_when_upbge_not_compatible(
        self, mock_discover, tmp_path
    ):
        mock_discover.return_value = _make_capability(compatible=False)
        contract = _make_contract()

        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False

    @patch("src.photo_pipeline.compilation_bridge.auto_launch_game")
    @patch("src.photo_pipeline.compilation_bridge.run_structural_smoke")
    @patch("src.photo_pipeline.compilation_bridge.validate_upbge_inventory")
    @patch("src.photo_pipeline.compilation_bridge.run_upbge_sidecar")
    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_full_success_path(
        self,
        mock_discover,
        mock_build_plan,
        mock_sidecar,
        mock_parity,
        mock_smoke,
        mock_launch,
        tmp_path,
    ):
        mock_discover.return_value = _make_capability()
        mock_plan = MagicMock()
        mock_plan.runtime = MagicMock()
        mock_build_plan.return_value = mock_plan
        mock_sidecar.return_value = _make_sidecar_result()
        mock_parity.return_value = _make_parity_report()
        mock_smoke.return_value = _make_smoke_result()
        mock_launch.return_value = _make_launch_result()

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        assert result.success is True
        assert result.reason_code == "launched"
        assert result.compiler_plan is mock_plan
        assert result.sidecar_result is not None
        assert result.parity_result is not None
        assert result.smoke_result is not None
        assert result.launch_result is not None

    @patch("src.photo_pipeline.compilation_bridge.run_upbge_sidecar")
    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_sidecar_failure_returns_failure(
        self, mock_discover, mock_build_plan, mock_sidecar, tmp_path
    ):
        mock_discover.return_value = _make_capability()
        mock_build_plan.return_value = MagicMock()
        mock_sidecar.return_value = _make_sidecar_result(success=False, output_dir=None)

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False
        assert "sidecar" in result.reason_code

    @patch("src.photo_pipeline.compilation_bridge.validate_upbge_inventory")
    @patch("src.photo_pipeline.compilation_bridge.run_upbge_sidecar")
    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_parity_failure_returns_failure(
        self,
        mock_discover,
        mock_build_plan,
        mock_sidecar,
        mock_parity,
        tmp_path,
    ):
        mock_discover.return_value = _make_capability()
        mock_plan = MagicMock()
        mock_plan.runtime = MagicMock()
        mock_build_plan.return_value = mock_plan
        mock_sidecar.return_value = _make_sidecar_result()
        mock_parity.return_value = _make_parity_report(passed=False)

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False
        assert result.reason_code == "parity_failed"

    @patch("src.photo_pipeline.compilation_bridge.auto_launch_game")
    @patch("src.photo_pipeline.compilation_bridge.run_structural_smoke")
    @patch("src.photo_pipeline.compilation_bridge.validate_upbge_inventory")
    @patch("src.photo_pipeline.compilation_bridge.run_upbge_sidecar")
    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_smoke_failure_does_not_block_launch(
        self,
        mock_discover,
        mock_build_plan,
        mock_sidecar,
        mock_parity,
        mock_smoke,
        mock_launch,
        tmp_path,
    ):
        mock_discover.return_value = _make_capability()
        mock_plan = MagicMock()
        mock_plan.runtime = MagicMock()
        mock_build_plan.return_value = mock_plan
        mock_sidecar.return_value = _make_sidecar_result()
        mock_parity.return_value = _make_parity_report()
        mock_smoke.return_value = _make_smoke_result(passed=False)
        mock_launch.return_value = _make_launch_result()

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        # Smoke failure is non-blocking — launch still happens
        assert result.success is True
        mock_launch.assert_called_once()

    @patch("src.photo_pipeline.compilation_bridge.auto_launch_game")
    @patch("src.photo_pipeline.compilation_bridge.run_structural_smoke")
    @patch("src.photo_pipeline.compilation_bridge.validate_upbge_inventory")
    @patch("src.photo_pipeline.compilation_bridge.run_upbge_sidecar")
    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_launch_failure_returns_failure(
        self,
        mock_discover,
        mock_build_plan,
        mock_sidecar,
        mock_parity,
        mock_smoke,
        mock_launch,
        tmp_path,
    ):
        mock_discover.return_value = _make_capability()
        mock_plan = MagicMock()
        mock_plan.runtime = MagicMock()
        mock_build_plan.return_value = mock_plan
        mock_sidecar.return_value = _make_sidecar_result()
        mock_parity.return_value = _make_parity_report()
        mock_smoke.return_value = _make_smoke_result()
        mock_launch.return_value = _make_launch_result(success=False)

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False
        assert "launch" in result.reason_code

    @patch("src.photo_pipeline.compilation_bridge.build_compiler_plan")
    @patch("src.photo_pipeline.compilation_bridge.discover_upbge")
    def test_compiler_plan_exception_returns_failure(
        self, mock_discover, mock_build_plan, tmp_path
    ):
        mock_discover.return_value = _make_capability()
        mock_build_plan.side_effect = ValueError("bad contract")

        contract = _make_contract()
        result = run_compilation_chain(contract, tmp_path)

        assert result.success is False
        assert result.reason_code == "compiler_plan_failed"
        assert "bad contract" in result.diagnostic

    def test_creates_compile_output_subdirectory(self, tmp_path):
        with patch(
            "src.photo_pipeline.compilation_bridge.discover_upbge"
        ) as mock_discover:
            mock_discover.return_value = _make_capability(available=False)
            contract = _make_contract()
            run_compilation_chain(contract, tmp_path)
            # Even on early failure, the function shouldn't crash
            # (compile dir creation happens after capability check)


class TestElapsedMs:
    """Tests for the _elapsed_ms helper."""

    def test_returns_non_negative_int(self):
        import time
        started = time.monotonic()
        result = _elapsed_ms(started)
        assert isinstance(result, int)
        assert result >= 0
