"""Focused tests for Task 4.7 unified resource arbitration.

Validates Requirements 15.1-15.6 without starting GPU services.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.photo_pipeline.comfyui_client import ComfyUIVRAMError
from src.unified_pipeline.resource_arbiter import (
    RESOURCE_SCHEDULE,
    ResourceKind,
    ResourceOwnershipTimeout,
    ResourceReleaseError,
    ResourceRequest,
    ResourceStallError,
    UnifiedResourceArbiter,
)


class FakeManager:
    def __init__(self, name: str, events: list[str], measured_gb: float = 0.0) -> None:
        self.name = name
        self.events = events
        self.measured_gb = measured_gb
        self.flash_attention_enabled = False

    async def acquire_model(self, model: str, estimated_gb: float) -> None:
        self.events.append(f"acquire:{self.name}:{model}:{estimated_gb}")

    async def hard_release(self) -> None:
        self.events.append(f"free:{self.name}")

    async def _get_vram_used_gb(self) -> float:
        self.events.append(f"measure:{self.name}")
        return self.measured_gb


def make_arbiter(
    tmp_path: Path,
    *,
    names: tuple[str, ...] = ("default",),
    events: list[str] | None = None,
    measured_gb: float = 0.0,
    **kwargs: Any,
) -> tuple[UnifiedResourceArbiter, list[str], dict[str, FakeManager]]:
    event_log = events if events is not None else []
    clients = {name: object() for name in names}
    managers = {
        name: FakeManager(name, event_log, measured_gb=measured_gb) for name in names
    }
    arbiter = UnifiedResourceArbiter(
        clients, diagnostics_dir=tmp_path, vram_managers=managers, **kwargs
    )
    return arbiter, event_log, managers


def test_schedule_covers_every_required_gpu_consumer() -> None:
    assert set(RESOURCE_SCHEDULE) == set(ResourceKind)
    assert ResourceKind.OLLAMA_PLANNER in RESOURCE_SCHEDULE
    assert ResourceKind.DREAM_FLUX in RESOURCE_SCHEDULE
    assert ResourceKind.CANON_FLUX in RESOURCE_SCHEDULE
    assert ResourceKind.SAM in RESOURCE_SCHEDULE
    assert ResourceKind.EDIT_INPAINT in RESOURCE_SCHEDULE
    assert ResourceKind.DA3 in RESOURCE_SCHEDULE
    assert ResourceKind.HUNYUAN3D in RESOURCE_SCHEDULE
    assert ResourceKind.TRELLIS2 in RESOURCE_SCHEDULE
    assert ResourceKind.PAINTING in RESOURCE_SCHEDULE
    assert ResourceKind.COMFYUI in RESOURCE_SCHEDULE


@pytest.mark.asyncio
async def test_planner_and_comfyui_never_overlap(tmp_path: Path) -> None:
    arbiter, _, _ = make_arbiter(tmp_path)
    planner_entered = asyncio.Event()
    allow_planner_exit = asyncio.Event()
    canon_entered = asyncio.Event()
    active = 0
    maximum_active = 0

    async def planner() -> None:
        nonlocal active, maximum_active
        request = ResourceRequest(ResourceKind.OLLAMA_PLANNER, "plan:session-1")
        async with arbiter.claim(request):
            active += 1
            maximum_active = max(maximum_active, active)
            planner_entered.set()
            await allow_planner_exit.wait()
            active -= 1

    async def canon() -> None:
        nonlocal active, maximum_active
        request = ResourceRequest(ResourceKind.CANON_FLUX, "canon:session-1", "flux")
        async with arbiter.claim(request):
            active += 1
            maximum_active = max(maximum_active, active)
            canon_entered.set()
            active -= 1

    planner_task = asyncio.create_task(planner())
    await planner_entered.wait()
    canon_task = asyncio.create_task(canon())
    await asyncio.sleep(0)
    assert not canon_entered.is_set()
    allow_planner_exit.set()
    await asyncio.gather(planner_task, canon_task)
    assert maximum_active == 1


@pytest.mark.asyncio
async def test_release_frees_and_measures_every_comfyui_instance(tmp_path: Path) -> None:
    arbiter, events, managers = make_arbiter(
        tmp_path, names=("desktop-8188", "mesh-8190")
    )
    request = ResourceRequest(
        ResourceKind.HUNYUAN3D,
        "mesh:chair",
        "hunyuan3d-v2",
        comfyui_instance="mesh-8190",
    )
    async with arbiter.claim(request):
        assert arbiter.active_owner is not None
        assert managers["mesh-8190"].flash_attention_enabled is True

    assert "free:desktop-8188" in events
    assert "free:mesh-8190" in events
    assert "measure:desktop-8188" in events
    assert "measure:mesh-8190" in events
    state = json.loads((tmp_path / "gpu_owner.json").read_text(encoding="utf-8"))
    assert state["phase"] == "idle"
    assert state["active_owner"] is None
    assert state["registered_comfyui_instances"] == ["desktop-8188", "mesh-8190"]


@pytest.mark.asyncio
async def test_host_ram_hysteresis_pauses_above_80_and_resumes_below_72(
    tmp_path: Path,
) -> None:
    ram = {"used": 81.0}
    sleeps: list[float] = []

    async def lower_ram(delay: float) -> None:
        sleeps.append(delay)
        ram["used"] = 71.9

    arbiter, _, _ = make_arbiter(
        tmp_path,
        ram_provider=lambda: ram["used"],
        sleep=lower_ram,
    )
    request = ResourceRequest(ResourceKind.SAM, "sam:session-1")
    async with arbiter.claim(request):
        assert ram["used"] < 72.0

    assert sleeps == [2.0]
    journal = (tmp_path / "gpu_owner.jsonl").read_text(encoding="utf-8")
    assert "host_ram_paused" in journal
    assert "host_ram_resumed" in journal


@pytest.mark.asyncio
async def test_oom_retries_once_then_falls_back_under_new_owner(tmp_path: Path) -> None:
    no_waits: list[float] = []

    async def no_wait(delay: float) -> None:
        no_waits.append(delay)

    arbiter, events, _ = make_arbiter(tmp_path, sleep=no_wait)
    attempts = 0

    async def primary() -> str:
        nonlocal attempts
        attempts += 1
        raise ComfyUIVRAMError("CUDA out of memory")

    async def fallback() -> str:
        return "trellis-result"

    result = await arbiter.execute(
        ResourceRequest(ResourceKind.HUNYUAN3D, "mesh:table", "hunyuan"),
        primary,
        fallback=fallback,
        fallback_request=ResourceRequest(
            ResourceKind.TRELLIS2, "mesh:table:fallback", "trellis"
        ),
    )

    assert result == "trellis-result"
    assert attempts == 2
    assert no_waits == [5.0]
    assert any(":hunyuan:" in event for event in events if event.startswith("acquire:"))
    assert any(":trellis:" in event for event in events if event.startswith("acquire:"))
    entries = [
        json.loads(line)
        for line in (tmp_path / "gpu_owner.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["event"] for entry in entries].count("oom") == 1
    assert [entry["event"] for entry in entries].count("oom_retry_exhausted") == 1
    assert [entry["event"] for entry in entries].count("fallback_succeeded") == 1


@pytest.mark.asyncio
async def test_ollama_unloader_runs_before_measured_release(tmp_path: Path) -> None:
    events: list[str] = []

    async def unload(request: ResourceRequest) -> None:
        events.append(f"unload:{request.model_name}")

    arbiter, events, _ = make_arbiter(
        tmp_path,
        events=events,
        unloaders={ResourceKind.OLLAMA_PLANNER: unload},
    )
    request = ResourceRequest(
        ResourceKind.OLLAMA_PLANNER, "planner:session-2", "qwen-planner"
    )
    async with arbiter.claim(request):
        pass

    assert events[0] == "unload:qwen-planner"
    assert events[1:] == ["free:default", "measure:default"]


@pytest.mark.asyncio
async def test_unsafe_measured_release_fails_closed_without_stuck_owner(
    tmp_path: Path,
) -> None:
    arbiter, _, _ = make_arbiter(tmp_path, measured_gb=4.0)
    request = ResourceRequest(ResourceKind.CANON_FLUX, "canon:unsafe")

    with pytest.raises(ResourceReleaseError, match="must be <4.0GB"):
        async with arbiter.claim(request):
            pass

    assert arbiter.active_owner is None
    assert arbiter.get_state().phase == "release_failed"


def test_initialization_records_and_clears_stale_diagnostic_owner(tmp_path: Path) -> None:
    stale = {
        "schema": "unified-resource-owner/v1",
        "sequence": 12,
        "active_owner": {"lease_id": "dead", "owner_id": "old-planner"},
    }
    (tmp_path / "gpu_owner.json").write_text(json.dumps(stale), encoding="utf-8")

    arbiter, _, _ = make_arbiter(tmp_path)

    assert arbiter.active_owner is None
    state = json.loads((tmp_path / "gpu_owner.json").read_text(encoding="utf-8"))
    assert state["active_owner"] is None
    assert state["sequence"] == 13
    journal = (tmp_path / "gpu_owner.jsonl").read_text(encoding="utf-8")
    assert "stale_owner_recovered" in journal


def test_unknown_comfyui_instance_is_rejected_before_queueing(tmp_path: Path) -> None:
    arbiter, _, _ = make_arbiter(tmp_path)
    request = ResourceRequest(
        ResourceKind.COMFYUI,
        "custom:job",
        comfyui_instance="unregistered-9000",
    )

    async def claim() -> None:
        async with arbiter.claim(request):
            raise AssertionError("must not enter")

    with pytest.raises(ValueError, match="unknown ComfyUI instance"):
        asyncio.run(claim())


@pytest.mark.asyncio
async def test_stall_is_bounded_released_and_falls_back(tmp_path: Path) -> None:
    arbiter, _, _ = make_arbiter(tmp_path, stall_timeout_s=0.01)
    attempts = 0

    async def stalled_primary() -> str:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.05)
        return "too-late"

    async def fallback() -> str:
        return "trellis-after-stall"

    result = await arbiter.execute(
        ResourceRequest(
            ResourceKind.HUNYUAN3D,
            "mesh:stalled",
            session_id="session-7",
            external_job_id="comfy-job-42",
        ),
        stalled_primary,
        fallback=fallback,
        fallback_request=ResourceRequest(
            ResourceKind.TRELLIS2,
            "mesh:stalled:fallback",
            attempt=2,
        ),
    )

    assert result == "trellis-after-stall"
    assert attempts == 1
    assert arbiter.active_owner is None
    assert not (tmp_path / "gpu_owner.lock").exists()
    journal = (tmp_path / "gpu_owner.jsonl").read_text(encoding="utf-8")
    assert "stall_detected" in journal
    assert "fallback_succeeded" in journal
    assert "comfy-job-42" in journal


@pytest.mark.asyncio
async def test_stall_without_fallback_fails_closed(tmp_path: Path) -> None:
    arbiter, _, _ = make_arbiter(tmp_path, stall_timeout_s=0.001)

    async def stalled() -> None:
        await asyncio.sleep(0.02)

    with pytest.raises(ResourceStallError, match="has no fallback"):
        await arbiter.execute(
            ResourceRequest(ResourceKind.PAINTING, "paint:stalled"),
            stalled,
        )

    assert arbiter.active_owner is None
    assert not (tmp_path / "gpu_owner.lock").exists()


@pytest.mark.asyncio
async def test_live_process_durable_owner_blocks_second_arbiter(tmp_path: Path) -> None:
    first, _, _ = make_arbiter(tmp_path, acquire_timeout_s=0.02)
    second, _, _ = make_arbiter(tmp_path, acquire_timeout_s=0.02)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def own_first() -> None:
        async with first.claim(
            ResourceRequest(ResourceKind.OLLAMA_PLANNER, "planner:durable")
        ):
            first_entered.set()
            await release_first.wait()

    first_task = asyncio.create_task(own_first())
    await first_entered.wait()
    lock = json.loads((tmp_path / "gpu_owner.lock").read_text(encoding="utf-8"))
    assert lock["owner_id"] == "planner:durable"
    assert lock["pid"] > 0

    with pytest.raises(ResourceOwnershipTimeout, match="live owner planner:durable"):
        async with second.claim(ResourceRequest(ResourceKind.SAM, "sam:blocked")):
            raise AssertionError("second arbiter must not overlap")

    release_first.set()
    await first_task
    assert not (tmp_path / "gpu_owner.lock").exists()


@pytest.mark.asyncio
async def test_dead_process_durable_owner_is_recovered(tmp_path: Path) -> None:
    stale = {
        "schema": "unified-resource-lease/v1",
        "pid": 2147483647,
        "lease_id": "dead-lease",
        "owner_id": "dead-worker",
        "kind": "sam",
    }
    (tmp_path / "gpu_owner.lock").write_text(json.dumps(stale), encoding="utf-8")
    arbiter, _, _ = make_arbiter(tmp_path, acquire_timeout_s=0.02)

    async with arbiter.claim(ResourceRequest(ResourceKind.SAM, "sam:replacement")):
        owner = json.loads((tmp_path / "gpu_owner.lock").read_text(encoding="utf-8"))
        assert owner["owner_id"] == "sam:replacement"

    journal = (tmp_path / "gpu_owner.jsonl").read_text(encoding="utf-8")
    assert "dead_process_owner_recovered" in journal
