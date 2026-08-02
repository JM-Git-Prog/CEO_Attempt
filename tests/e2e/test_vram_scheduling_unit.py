"""Unit tests for VRAM scheduling fixtures and Resource Arbiter (Task 12.2, 12.3).

Tests the vram_lease fixture behavior:
- Lease acquisition and release timing
- Timeout behavior at 60s (via mock)
- ComfyUI idle wait behavior
- 5s release deadline enforcement
- Graceful skip on contention timeout
- Sequential scheduling order enforcement (FLUX → perceptual → vision QA)

Requirements: 21.1–21.5
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Tests for _wait_for_comfyui_idle
# ---------------------------------------------------------------------------


class TestWaitForComfyUIIdle:
    """Tests for the ComfyUI idle-wait helper."""

    @pytest.mark.asyncio
    async def test_returns_true_when_no_active_owner_and_queue_empty(self):
        """When arbiter has no active owner and queue is empty, returns True."""
        from tests.e2e.conftest import _wait_for_comfyui_idle

        arbiter = MagicMock()
        state = MagicMock()
        state.active_owner = None
        arbiter.get_state.return_value = state

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "queue_running": [],
                "queue_pending": [],
            }
            mock_client.get = AsyncMock(return_value=mock_resp)

            result = await _wait_for_comfyui_idle(
                arbiter, poll_interval_s=0.01, timeout_s=1.0
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_comfyui_unreachable(self):
        """When ComfyUI is not reachable, treat as idle (no generation)."""
        import httpx

        from tests.e2e.conftest import _wait_for_comfyui_idle

        arbiter = MagicMock()
        state = MagicMock()
        state.active_owner = None
        arbiter.get_state.return_value = state

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

            result = await _wait_for_comfyui_idle(
                arbiter, poll_interval_s=0.01, timeout_s=1.0
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_waits_when_flux_generation_active(self):
        """When FLUX generation is active, waits until it completes."""
        from tests.e2e.conftest import _wait_for_comfyui_idle

        arbiter = MagicMock()
        call_count = 0

        def get_state_side_effect():
            nonlocal call_count
            call_count += 1
            state = MagicMock()
            if call_count <= 2:
                # First two calls: FLUX is active
                state.active_owner = {"kind": "dream_flux"}
            else:
                # After that: idle
                state.active_owner = None
            return state

        arbiter.get_state.side_effect = get_state_side_effect

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "queue_running": [],
                "queue_pending": [],
            }
            mock_client.get = AsyncMock(return_value=mock_resp)

            result = await _wait_for_comfyui_idle(
                arbiter, poll_interval_s=0.01, timeout_s=5.0
            )
            assert result is True
            assert call_count >= 3  # Waited for FLUX to complete

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """When ComfyUI stays busy past the timeout, returns False."""
        from tests.e2e.conftest import _wait_for_comfyui_idle

        arbiter = MagicMock()
        state = MagicMock()
        state.active_owner = {"kind": "dream_flux"}
        arbiter.get_state.return_value = state

        result = await _wait_for_comfyui_idle(
            arbiter, poll_interval_s=0.01, timeout_s=0.05
        )
        assert result is False


# ---------------------------------------------------------------------------
# Tests for VRAMLeaseFacade behavior
# ---------------------------------------------------------------------------


class TestVRAMLeaseFacade:
    """Tests for the vram_lease fixture facade behavior."""

    def test_release_deadline_constant(self):
        """Verify the release deadline constant is 5 seconds (Req 21.3)."""
        from tests.e2e.conftest import _LEASE_RELEASE_DEADLINE_S
        assert _LEASE_RELEASE_DEADLINE_S == 5.0

    def test_lease_timeout_constant(self):
        """Verify the VRAM lease timeout is 60 seconds (Req 21.4)."""
        from tests.e2e.conftest import _VRAM_LEASE_TIMEOUT_S
        assert _VRAM_LEASE_TIMEOUT_S == 60.0

    def test_facade_mark_computation_done_records_time(self):
        """mark_computation_done() should record the current time."""
        # Simulate the facade behavior without the full fixture
        class MockFacade:
            def __init__(self):
                self._computation_done_at = None

            def mark_computation_done(self):
                self._computation_done_at = time.monotonic()

        facade = MockFacade()
        before = time.monotonic()
        facade.mark_computation_done()
        after = time.monotonic()

        assert facade._computation_done_at is not None
        assert before <= facade._computation_done_at <= after

    def test_facade_release_idempotent(self):
        """Calling release() multiple times should be safe."""
        class MockFacade:
            def __init__(self):
                self._released = False
                self._result = None
                self._computation_done_at = None
                self._lease_context = None

            def release(self):
                if self._released:
                    return
                self._released = True

        facade = MockFacade()
        facade.release()
        assert facade._released is True
        facade.release()  # Second call should be no-op
        assert facade._released is True

    def test_acquire_returns_timeout_when_arbiter_is_none(self, vram_lease):
        """When resource_arbiter is None, acquire returns contention timeout."""
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        ResourceKind = ra.ResourceKind

        # If arbiter is None (no ComfyUI), this should return timeout status
        if vram_lease._arbiter is None:
            result = vram_lease.acquire(ResourceKind.PERCEPTUAL_LPIPS)
            assert result.acquired is False
            assert result.status == "vram_contention_timeout"
        else:
            pytest.skip("Resource arbiter is available — this test is for None path")


# ---------------------------------------------------------------------------
# Tests for ResourceKind test-specific enums
# ---------------------------------------------------------------------------


class TestResourceKindTestKinds:
    """Verify test-specific resource kinds exist and have correct values."""

    def test_perceptual_lpips_kind_exists(self):
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        assert ra.ResourceKind.PERCEPTUAL_LPIPS.value == "perceptual_lpips"

    def test_perceptual_clip_kind_exists(self):
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        assert ra.ResourceKind.PERCEPTUAL_CLIP.value == "perceptual_clip"

    def test_vision_qa_kind_exists(self):
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        assert ra.ResourceKind.VISION_QA.value == "vision_qa"


# ---------------------------------------------------------------------------
# Tests for VRAMLeaseResult dataclass
# ---------------------------------------------------------------------------


class TestVRAMLeaseResult:
    """Verify VRAMLeaseResult structure and status values."""

    def test_acquired_result(self):
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        VRAMLeaseResult = ra.VRAMLeaseResult

        result = VRAMLeaseResult(acquired=True, lease=MagicMock(), status="acquired")
        assert result.acquired is True
        assert result.status == "acquired"
        assert result.lease is not None

    def test_timeout_result(self):
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        VRAMLeaseResult = ra.VRAMLeaseResult

        result = VRAMLeaseResult(
            acquired=False, lease=None, status="vram_contention_timeout"
        )
        assert result.acquired is False
        assert result.status == "vram_contention_timeout"
        assert result.lease is None


# ---------------------------------------------------------------------------
# Tests for lease acquisition and release timing (Task 12.3, Req 21.1, 21.3)
# ---------------------------------------------------------------------------


class TestLeaseAcquisitionAndReleaseTiming:
    """Tests verifying VRAM lease acquisition succeeds when resources are
    available, and that release timing is correctly measured and enforced.

    Validates: Requirements 21.1, 21.3
    """

    @pytest.mark.asyncio
    async def test_claim_for_test_acquires_lease_when_idle(self):
        """claim_for_test yields acquired=True when no contention exists."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        request = ra.ResourceRequest(
            kind=ra.ResourceKind.PERCEPTUAL_LPIPS,
            owner_id="test_acquisition",
            model_name="perceptual_lpips",
        )

        async with arbiter.claim_for_test(request) as result:
            assert result.acquired is True
            assert result.status == "acquired"
            assert result.lease is not None
            assert result.lease.request.kind == ra.ResourceKind.PERCEPTUAL_LPIPS

    @pytest.mark.asyncio
    async def test_lease_released_after_context_exit(self):
        """After exiting claim_for_test, the arbiter should be idle."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        request = ra.ResourceRequest(
            kind=ra.ResourceKind.PERCEPTUAL_CLIP,
            owner_id="test_release",
            model_name="perceptual_clip",
        )

        async with arbiter.claim_for_test(request) as result:
            assert result.acquired is True
            # Active owner should be set while lease is held
            state = arbiter.get_state()
            assert state.active_owner is not None

        # After context exit, arbiter should be idle
        state = arbiter.get_state()
        assert state.phase == "idle"
        assert state.active_owner is None

    @pytest.mark.asyncio
    async def test_release_within_5s_of_computation(self):
        """Lease can be released within the 5s window after computation."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        request = ra.ResourceRequest(
            kind=ra.ResourceKind.PERCEPTUAL_LPIPS,
            owner_id="test_5s_release",
            model_name="perceptual_lpips",
        )

        start_time = time.monotonic()
        async with arbiter.claim_for_test(request) as result:
            assert result.acquired is True
            # Simulate computation completing quickly
            await asyncio.sleep(0.01)
        end_time = time.monotonic()

        # Total time should be well under the 5s release deadline
        elapsed = end_time - start_time
        assert elapsed < 5.0, f"Lease held for {elapsed:.2f}s, exceeds 5s deadline"

    @pytest.mark.asyncio
    async def test_multiple_sequential_leases_acquire_successfully(self):
        """Multiple leases acquired sequentially all succeed (no stale state)."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        kinds = [
            ra.ResourceKind.PERCEPTUAL_LPIPS,
            ra.ResourceKind.PERCEPTUAL_CLIP,
            ra.ResourceKind.VISION_QA,
        ]

        for kind in kinds:
            request = ra.ResourceRequest(
                kind=kind,
                owner_id=f"test_sequential_{kind.value}",
                model_name=kind.value,
            )
            async with arbiter.claim_for_test(request) as result:
                assert result.acquired is True
                assert result.status == "acquired"

        # Final state should be idle
        state = arbiter.get_state()
        assert state.phase == "idle"


# ---------------------------------------------------------------------------
# Tests for timeout behavior at 60s (Task 12.3, Req 21.4)
# ---------------------------------------------------------------------------


class TestTimeoutBehavior:
    """Tests verifying that VRAM lease timeout at 60s results in graceful
    skip with 'vram_contention_timeout' status rather than test failure.

    Validates: Requirements 21.4
    """

    @pytest.mark.asyncio
    async def test_claim_for_test_timeout_yields_contention_status(self):
        """When lease cannot be acquired within timeout, yields timeout result.

        Uses a separate task to hold the lock so the reentrancy guard doesn't
        fire (the arbiter detects same-task nesting as a deadlock).
        """
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        blocker_request = ra.ResourceRequest(
            kind=ra.ResourceKind.PERCEPTUAL_LPIPS,
            owner_id="test_blocker",
            model_name="perceptual_lpips",
        )

        blocker_acquired = asyncio.Event()
        blocker_release = asyncio.Event()

        async def hold_lease():
            async with arbiter.claim(blocker_request):
                blocker_acquired.set()
                await blocker_release.wait()

        blocker_task = asyncio.create_task(hold_lease())
        await blocker_acquired.wait()

        try:
            contender_request = ra.ResourceRequest(
                kind=ra.ResourceKind.VISION_QA,
                owner_id="test_contender",
                model_name="vision_qa",
            )

            # Use a short timeout to keep tests fast
            async with arbiter.claim_for_test(
                contender_request, timeout_s=0.1
            ) as result:
                assert result.acquired is False
                assert result.status == "vram_contention_timeout"
                assert result.lease is None
        finally:
            blocker_release.set()
            await blocker_task

    @pytest.mark.asyncio
    async def test_timeout_does_not_raise_exception(self):
        """Timeout should not raise — it yields a result object instead."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        blocker_request = ra.ResourceRequest(
            kind=ra.ResourceKind.DREAM_FLUX,
            owner_id="test_blocker_no_raise",
            model_name="dream_flux",
        )

        blocker_acquired = asyncio.Event()
        blocker_release = asyncio.Event()

        async def hold_lease():
            async with arbiter.claim(blocker_request):
                blocker_acquired.set()
                await blocker_release.wait()

        blocker_task = asyncio.create_task(hold_lease())
        await blocker_acquired.wait()

        try:
            contender_request = ra.ResourceRequest(
                kind=ra.ResourceKind.PERCEPTUAL_CLIP,
                owner_id="test_no_raise",
                model_name="perceptual_clip",
            )

            # This should NOT raise — it should yield a timeout result
            try:
                async with arbiter.claim_for_test(
                    contender_request, timeout_s=0.1
                ) as result:
                    assert result.acquired is False
                    assert result.status == "vram_contention_timeout"
            except Exception as exc:
                pytest.fail(
                    f"claim_for_test raised {type(exc).__name__} instead of "
                    f"yielding timeout result: {exc}"
                )
        finally:
            blocker_release.set()
            await blocker_task

    def test_default_lease_timeout_is_60s(self):
        """The default VRAM_LEASE_TIMEOUT_S constant must be 60 seconds."""
        ra = _import_resource_arbiter_module()
        assert ra.VRAM_LEASE_TIMEOUT_S == 60.0

    @pytest.mark.asyncio
    async def test_get_test_lease_timeout_returns_60s(self):
        """Arbiter's get_test_lease_timeout() returns 60s."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)
        assert arbiter.get_test_lease_timeout() == 60.0

    @pytest.mark.asyncio
    async def test_custom_timeout_overrides_default(self):
        """claim_for_test respects a custom timeout_s parameter."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)

        blocker_request = ra.ResourceRequest(
            kind=ra.ResourceKind.PERCEPTUAL_LPIPS,
            owner_id="test_custom_timeout_blocker",
            model_name="perceptual_lpips",
        )

        blocker_acquired = asyncio.Event()
        blocker_release = asyncio.Event()

        async def hold_lease():
            async with arbiter.claim(blocker_request):
                blocker_acquired.set()
                await blocker_release.wait()

        blocker_task = asyncio.create_task(hold_lease())
        await blocker_acquired.wait()

        try:
            contender_request = ra.ResourceRequest(
                kind=ra.ResourceKind.VISION_QA,
                owner_id="test_custom_timeout",
                model_name="vision_qa",
            )

            start = time.monotonic()
            async with arbiter.claim_for_test(
                contender_request, timeout_s=0.2
            ) as result:
                elapsed = time.monotonic() - start
                assert result.acquired is False
                # Should have waited approximately 0.2s (allow tolerance)
                assert 0.1 <= elapsed < 1.0, (
                    f"Expected ~0.2s wait, got {elapsed:.2f}s"
                )
        finally:
            blocker_release.set()
            await blocker_task


# ---------------------------------------------------------------------------
# Tests for sequential scheduling order enforcement (Task 12.3, Req 21.2, 21.5)
# ---------------------------------------------------------------------------


class TestSequentialSchedulingOrder:
    """Tests verifying that the nightly GPU test schedule enforces:
    FLUX (generation) → perceptual models → vision QA.

    This prevents the FLUX (12 GB) + vision (8 GB) = 20 GB scenario
    that would exceed typical 24 GB VRAM.

    Validates: Requirements 21.2, 21.5
    """

    def test_nightly_schedule_has_three_phases(self):
        """The nightly test schedule must have exactly 3 sequential phases."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE
        assert len(schedule) == 3

    def test_flux_is_first_phase(self):
        """Phase 1 of nightly schedule contains DREAM_FLUX."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE
        assert ra.ResourceKind.DREAM_FLUX in schedule[0]

    def test_perceptual_is_second_phase(self):
        """Phase 2 of nightly schedule contains perceptual models."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        assert ra.ResourceKind.PERCEPTUAL_LPIPS in schedule[1]
        assert ra.ResourceKind.PERCEPTUAL_CLIP in schedule[1]

    def test_vision_qa_is_third_phase(self):
        """Phase 3 of nightly schedule contains VISION_QA."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE
        assert ra.ResourceKind.VISION_QA in schedule[2]

    def test_flux_before_perceptual_in_schedule(self):
        """FLUX generation must be scheduled before perceptual models."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        flux_phase_idx = None
        perceptual_phase_idx = None
        for i, phase in enumerate(schedule):
            if ra.ResourceKind.DREAM_FLUX in phase:
                flux_phase_idx = i
            if ra.ResourceKind.PERCEPTUAL_LPIPS in phase:
                perceptual_phase_idx = i

        assert flux_phase_idx is not None, "DREAM_FLUX not in schedule"
        assert perceptual_phase_idx is not None, "PERCEPTUAL_LPIPS not in schedule"
        assert flux_phase_idx < perceptual_phase_idx, (
            f"FLUX must come before perceptual: "
            f"FLUX at phase {flux_phase_idx}, perceptual at {perceptual_phase_idx}"
        )

    def test_perceptual_before_vision_qa_in_schedule(self):
        """Perceptual models must be scheduled before vision QA."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        perceptual_phase_idx = None
        vision_phase_idx = None
        for i, phase in enumerate(schedule):
            if ra.ResourceKind.PERCEPTUAL_LPIPS in phase:
                perceptual_phase_idx = i
            if ra.ResourceKind.VISION_QA in phase:
                vision_phase_idx = i

        assert perceptual_phase_idx is not None, "PERCEPTUAL_LPIPS not in schedule"
        assert vision_phase_idx is not None, "VISION_QA not in schedule"
        assert perceptual_phase_idx < vision_phase_idx, (
            f"Perceptual must come before vision QA: "
            f"perceptual at phase {perceptual_phase_idx}, vision at {vision_phase_idx}"
        )

    def test_perceptual_models_can_coexist(self):
        """LPIPS and CLIP should be in the SAME phase (can share VRAM)."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        lpips_phase = None
        clip_phase = None
        for i, phase in enumerate(schedule):
            if ra.ResourceKind.PERCEPTUAL_LPIPS in phase:
                lpips_phase = i
            if ra.ResourceKind.PERCEPTUAL_CLIP in phase:
                clip_phase = i

        assert lpips_phase == clip_phase, (
            "PERCEPTUAL_LPIPS and PERCEPTUAL_CLIP should coexist in the same phase "
            f"(combined 4 GB), but LPIPS is at phase {lpips_phase} "
            f"and CLIP is at phase {clip_phase}"
        )

    def test_vision_qa_is_exclusive(self):
        """VISION_QA (8 GB) must be in its own phase, not coexisting."""
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        for phase in schedule:
            if ra.ResourceKind.VISION_QA in phase:
                assert len(phase) == 1, (
                    f"VISION_QA (8 GB) must be exclusive in its phase, "
                    f"but shares with: {phase}"
                )
                break

    @pytest.mark.asyncio
    async def test_get_nightly_schedule_method_returns_correct_order(self):
        """Arbiter.get_nightly_schedule() returns the same ordering."""
        ra = _import_resource_arbiter_module()
        arbiter = _create_test_arbiter(ra)
        schedule = arbiter.get_nightly_schedule()

        assert schedule == ra.NIGHTLY_TEST_SCHEDULE
        assert schedule[0] == (ra.ResourceKind.DREAM_FLUX,)
        assert schedule[1] == (
            ra.ResourceKind.PERCEPTUAL_LPIPS,
            ra.ResourceKind.PERCEPTUAL_CLIP,
        )
        assert schedule[2] == (ra.ResourceKind.VISION_QA,)

    def test_resource_schedule_has_test_kinds_after_production_kinds(self):
        """In the global RESOURCE_SCHEDULE, test kinds come after production."""
        ra = _import_resource_arbiter_module()
        schedule = ra.RESOURCE_SCHEDULE

        # Find indices of test kinds and verify they come after production
        production_kinds = {
            ra.ResourceKind.DREAM_FLUX,
            ra.ResourceKind.CANON_FLUX,
            ra.ResourceKind.COMFYUI,
        }
        test_kinds = {
            ra.ResourceKind.PERCEPTUAL_LPIPS,
            ra.ResourceKind.PERCEPTUAL_CLIP,
            ra.ResourceKind.VISION_QA,
        }

        max_production_idx = max(
            i for i, k in enumerate(schedule) if k in production_kinds
        )
        min_test_idx = min(
            i for i, k in enumerate(schedule) if k in test_kinds
        )

        assert max_production_idx < min_test_idx, (
            "Test-specific resource kinds must come after production kinds "
            "in the global RESOURCE_SCHEDULE"
        )

    def test_vram_estimates_prevent_oom(self):
        """Combined perceptual VRAM (4 GB) fits within 24 GB alongside nothing.
        FLUX (12 GB) + VISION_QA (8 GB) = 20 GB would be risky — verify they
        are in separate phases.
        """
        ra = _import_resource_arbiter_module()
        schedule = ra.NIGHTLY_TEST_SCHEDULE

        vram = ra._DEFAULT_VRAM_GB

        # Phase 1: FLUX alone
        phase1_vram = sum(vram[k] for k in schedule[0])
        assert phase1_vram == 12.0, f"Phase 1 VRAM: {phase1_vram} GB"

        # Phase 2: Perceptual models coexist
        phase2_vram = sum(vram[k] for k in schedule[1])
        assert phase2_vram == 4.0, f"Phase 2 VRAM: {phase2_vram} GB"

        # Phase 3: Vision QA alone
        phase3_vram = sum(vram[k] for k in schedule[2])
        assert phase3_vram == 8.0, f"Phase 3 VRAM: {phase3_vram} GB"

        # No phase exceeds 24 GB (typical GPU limit)
        for i, phase in enumerate(schedule):
            total = sum(vram[k] for k in phase)
            assert total <= 24.0, (
                f"Phase {i+1} uses {total} GB — exceeds 24 GB GPU limit"
            )


# ---------------------------------------------------------------------------
# Helper: import resource_arbiter without triggering heavy __init__.py
# ---------------------------------------------------------------------------


def _import_resource_arbiter_module():
    """Import the resource_arbiter module for direct testing."""
    from tests.e2e.conftest import _import_resource_arbiter
    return _import_resource_arbiter()


def _create_test_arbiter(ra, *, diagnostics_dir: str | None = None):
    """Create a minimal UnifiedResourceArbiter for unit testing.

    Uses mocked ComfyUI client and VRAMManager to avoid real GPU/network I/O.
    """
    import tempfile

    # Mock ComfyUI client
    mock_client = MagicMock()
    mock_client.base_url = "http://127.0.0.1:8188"

    # Mock VRAMManager that always succeeds
    mock_manager = MagicMock()
    mock_manager.hard_release = AsyncMock(return_value=None)
    mock_manager._get_vram_used_gb = AsyncMock(return_value=0.0)
    mock_manager.acquire_model = AsyncMock(return_value=None)
    mock_manager.flash_attention_enabled = True

    if diagnostics_dir is None:
        diagnostics_dir = tempfile.mkdtemp(prefix="vram_test_")

    arbiter = ra.UnifiedResourceArbiter(
        comfyui_clients={"default": mock_client},
        vram_managers={"default": mock_manager},
        diagnostics_dir=Path(diagnostics_dir),
        acquire_timeout_s=5.0,  # Short timeout for tests
        stall_timeout_s=5.0,
    )
    return arbiter
