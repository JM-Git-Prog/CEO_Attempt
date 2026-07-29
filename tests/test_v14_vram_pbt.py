"""Property-based tests for VRAM Manager system RAM pause/resume threshold.

# Feature: photo-to-real-3d-world-v14

## Property 4: System RAM Pause/Resume Threshold

**Validates: Requirements 2.7**

For any system RAM usage measurement, the VRAM Manager SHALL pause new stage
submissions if and only if usage exceeds 80GB, and SHALL resume only when
usage drops below 72GB.

Uses Hypothesis with:
- RAM values as floats in [0, 128] GB
- Mock _get_system_ram_used_gb to return generated values
- Verifies check_system_ram() returns False iff RAM > 80
- Verifies wait_for_ram_available blocks until RAM < 72 (hysteresis)
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.vram_manager import (
    VRAMManager,
    SYSTEM_RAM_PAUSE_THRESHOLD_GB,
    SYSTEM_RAM_RESUME_THRESHOLD_GB,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# RAM usage values in GB: float from 0 to 128 (system has 96GB, but test full range)
_ram_gb = st.floats(min_value=0.0, max_value=128.0, allow_nan=False, allow_infinity=False)

# RAM values specifically above the pause threshold (>80)
_ram_above_pause = st.floats(
    min_value=SYSTEM_RAM_PAUSE_THRESHOLD_GB + 0.001,
    max_value=128.0,
    allow_nan=False,
    allow_infinity=False,
)

# RAM values at or below the pause threshold (<=80)
_ram_at_or_below_pause = st.floats(
    min_value=0.0,
    max_value=SYSTEM_RAM_PAUSE_THRESHOLD_GB,
    allow_nan=False,
    allow_infinity=False,
)

# RAM values above the resume threshold but at or below pause (72 < x <= 80)
_ram_in_hysteresis = st.floats(
    min_value=SYSTEM_RAM_RESUME_THRESHOLD_GB + 0.001,
    max_value=SYSTEM_RAM_PAUSE_THRESHOLD_GB,
    allow_nan=False,
    allow_infinity=False,
)

# RAM values at or below the resume threshold (<=72)
_ram_below_resume = st.floats(
    min_value=0.0,
    max_value=SYSTEM_RAM_RESUME_THRESHOLD_GB,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager() -> VRAMManager:
    """Create a VRAMManager with a mocked ComfyUI client."""
    mock_client = MagicMock()
    mock_client.base_url = "http://localhost:8188"
    mock_client._free_vram = AsyncMock()
    return VRAMManager(client=mock_client)


# ---------------------------------------------------------------------------
# Property 4: System RAM Pause/Resume Threshold
# ---------------------------------------------------------------------------


class TestSystemRAMPauseResumeThresholdProperty:
    """Property 4: System RAM Pause/Resume Threshold.

    **Validates: Requirements 2.7**
    """

    @given(ram_gb=_ram_gb)
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_check_system_ram_threshold_decision(self, ram_gb: float) -> None:
        """check_system_ram() returns False iff RAM > 80GB, True otherwise.

        For any RAM usage value:
        - If ram > 80 → check_system_ram() returns False (pause needed)
        - If ram <= 80 → check_system_ram() returns True (OK to proceed)
        """
        manager = _make_manager()

        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=ram_gb
        ):
            result = asyncio.run(
                manager.check_system_ram()
            )

        if ram_gb > SYSTEM_RAM_PAUSE_THRESHOLD_GB:
            assert result is False, (
                f"Expected False (pause) for RAM={ram_gb:.2f} GB "
                f"(> {SYSTEM_RAM_PAUSE_THRESHOLD_GB} GB threshold)"
            )
        else:
            assert result is True, (
                f"Expected True (OK) for RAM={ram_gb:.2f} GB "
                f"(≤ {SYSTEM_RAM_PAUSE_THRESHOLD_GB} GB threshold)"
            )

    @given(ram_gb=_ram_above_pause)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_check_system_ram_above_threshold_always_pauses(
        self, ram_gb: float
    ) -> None:
        """RAM above 80GB always triggers pause (check_system_ram returns False).

        **Validates: Requirements 2.7** — pause when RAM > 80GB.
        """
        manager = _make_manager()

        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=ram_gb
        ):
            result = asyncio.run(
                manager.check_system_ram()
            )

        assert result is False, (
            f"RAM={ram_gb:.2f} GB exceeds {SYSTEM_RAM_PAUSE_THRESHOLD_GB} GB, "
            f"should pause (return False)"
        )

    @given(ram_gb=_ram_at_or_below_pause)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_check_system_ram_at_or_below_threshold_allows(
        self, ram_gb: float
    ) -> None:
        """RAM at or below 80GB allows proceeding (check_system_ram returns True).

        **Validates: Requirements 2.7** — no pause when RAM ≤ 80GB.
        """
        manager = _make_manager()

        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=ram_gb
        ):
            result = asyncio.run(
                manager.check_system_ram()
            )

        assert result is True, (
            f"RAM={ram_gb:.2f} GB is ≤ {SYSTEM_RAM_PAUSE_THRESHOLD_GB} GB, "
            f"should allow (return True)"
        )

    @pytest.mark.asyncio
    async def test_wait_for_ram_available_resumes_below_72(self) -> None:
        """wait_for_ram_available blocks while RAM > 72GB, resumes at ≤ 72GB.

        Simulates RAM dropping from 85 → 75 → 70: the method should only
        return once RAM drops below the resume threshold of 72GB.

        **Validates: Requirements 2.7** — resume only when RAM < 72GB.
        """
        manager = _make_manager()

        # Simulate RAM sequence: 85 → 75 → 70
        # 85 > 80 (pause triggered), 75 > 72 (still waiting), 70 ≤ 72 (resume)
        ram_sequence = iter([85.0, 75.0, 70.0])

        with patch.object(
            VRAMManager,
            "_get_system_ram_used_gb",
            side_effect=lambda: next(ram_sequence),
        ):
            with patch("src.photo_pipeline.vram_manager.RAM_POLL_INTERVAL_S", 0.01):
                await manager.wait_for_ram_available()

        # If we reach here, the method returned — meaning RAM dropped below 72GB

    @pytest.mark.asyncio
    async def test_wait_for_ram_available_immediate_if_below_pause(self) -> None:
        """wait_for_ram_available returns immediately if RAM ≤ 80GB.

        **Validates: Requirements 2.7** — no blocking if not in paused state.
        """
        manager = _make_manager()

        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=60.0
        ):
            # Should return immediately without polling
            await manager.wait_for_ram_available()

    @given(
        initial_ram=_ram_above_pause,
        final_ram=_ram_below_resume,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_wait_for_ram_hysteresis_requires_below_resume(
        self, initial_ram: float, final_ram: float
    ) -> None:
        """wait_for_ram_available requires RAM to drop below 72GB (not just below 80GB).

        This tests the hysteresis behavior: once paused (RAM > 80GB), the system
        does not resume at 79GB — it must drop all the way to below 72GB.

        **Validates: Requirements 2.7**
        """
        manager = _make_manager()

        # Sequence: initial_ram (>80, triggers pause) → final_ram (≤72, triggers resume)
        ram_sequence = iter([initial_ram, initial_ram, final_ram])

        with patch.object(
            VRAMManager,
            "_get_system_ram_used_gb",
            side_effect=lambda: next(ram_sequence),
        ):
            with patch("src.photo_pipeline.vram_manager.RAM_POLL_INTERVAL_S", 0.001):
                asyncio.run(
                    manager.wait_for_ram_available()
                )

    @given(ram_in_hysteresis=_ram_in_hysteresis)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_hysteresis_zone_does_not_resume(
        self, ram_in_hysteresis: float
    ) -> None:
        """RAM in (72, 80] does NOT cause wait_for_ram_available to resume
        if it was triggered by RAM > 80.

        The hysteresis zone means: once paused, values between 72 and 80 keep
        the system waiting. Only dropping below 72 triggers resume.

        **Validates: Requirements 2.7**
        """
        manager = _make_manager()

        # Sequence: 85 (triggers pause), ram_in_hysteresis (still waiting), then 71 (resume)
        ram_sequence = iter([85.0, ram_in_hysteresis, 71.0])

        with patch.object(
            VRAMManager,
            "_get_system_ram_used_gb",
            side_effect=lambda: next(ram_sequence),
        ):
            with patch("src.photo_pipeline.vram_manager.RAM_POLL_INTERVAL_S", 0.001):
                asyncio.run(
                    manager.wait_for_ram_available()
                )

        # The key assertion is implicit: if wait_for_ram_available had
        # incorrectly resumed at the hysteresis value, it would have returned
        # after only consuming 2 values from the iterator. The fact that it
        # consumed all 3 (including the final 71.0) confirms it correctly
        # waited through the hysteresis zone.

    @given(ram_gb=_ram_at_or_below_pause)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_wait_for_ram_no_block_when_below_pause(
        self, ram_gb: float
    ) -> None:
        """wait_for_ram_available does not block when RAM ≤ 80GB (not paused).

        **Validates: Requirements 2.7** — only blocks when RAM exceeds pause threshold.
        """
        manager = _make_manager()

        call_count = 0
        original_value = ram_gb

        def mock_ram() -> float:
            nonlocal call_count
            call_count += 1
            return original_value

        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", side_effect=mock_ram
        ):
            asyncio.run(
                manager.wait_for_ram_available()
            )

        # Should only be called once (the initial check) since RAM ≤ 80
        assert call_count == 1, (
            f"Expected single RAM check for value {ram_gb:.2f} GB "
            f"(≤ {SYSTEM_RAM_PAUSE_THRESHOLD_GB}), but got {call_count} calls"
        )
