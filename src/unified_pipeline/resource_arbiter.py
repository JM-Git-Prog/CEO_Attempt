"""Process-local GPU ownership arbiter for the unified world pipeline.

Wraps the proven V14 ``VRAMManager`` while making every GPU consumer use one
lease, including Ollama.  Releases are hard, measured, and recorded durably.
Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable, Mapping

import psutil

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIVRAMError
from src.photo_pipeline.vram_manager import (
    OOM_RETRY_WAIT_S,
    SYSTEM_RAM_PAUSE_THRESHOLD_GB,
    SYSTEM_RAM_RESUME_THRESHOLD_GB,
    VRAM_FREE_THRESHOLD_GB,
    VRAMManager,
)

AsyncCallable = Callable[..., Awaitable[Any]]
UnloadCallable = Callable[["ResourceRequest"], Awaitable[None] | None]


class ResourceKind(str, Enum):
    """All GPU consumers in the V16 schedule."""

    OLLAMA_PLANNER = "ollama_planner"
    OLLAMA_VISION = "ollama_vision"
    DREAM_FLUX = "dream_flux"
    CANON_FLUX = "canon_flux"
    SAM = "sam"
    EDIT_INPAINT = "edit_inpaint"
    DA3 = "depth_anything_3"
    HUNYUAN3D = "hunyuan3d"
    TRELLIS2 = "trellis2"
    PAINTING = "painting"
    COMFYUI = "comfyui"
    # Test-specific resource kinds (Requirements 21.1–21.5)
    PERCEPTUAL_LPIPS = "perceptual_lpips"
    PERCEPTUAL_CLIP = "perceptual_clip"
    VISION_QA = "vision_qa"


RESOURCE_SCHEDULE: tuple[ResourceKind, ...] = (
    ResourceKind.OLLAMA_PLANNER,
    ResourceKind.DREAM_FLUX,
    ResourceKind.CANON_FLUX,
    ResourceKind.OLLAMA_VISION,
    ResourceKind.SAM,
    ResourceKind.EDIT_INPAINT,
    ResourceKind.DA3,
    ResourceKind.HUNYUAN3D,
    ResourceKind.TRELLIS2,
    ResourceKind.PAINTING,
    ResourceKind.COMFYUI,
    ResourceKind.PERCEPTUAL_LPIPS,
    ResourceKind.PERCEPTUAL_CLIP,
    ResourceKind.VISION_QA,
)

# Sequential scheduling for nightly GPU tests (Requirement 21.2, 21.5):
# FLUX generation first (12 GB) → perceptual models (4 GB) → vision QA (8 GB).
# PERCEPTUAL_LPIPS and PERCEPTUAL_CLIP may coexist (combined 4 GB),
# but VISION_QA must wait for perceptual models to release.
NIGHTLY_TEST_SCHEDULE: tuple[tuple[ResourceKind, ...], ...] = (
    (ResourceKind.DREAM_FLUX,),
    (ResourceKind.PERCEPTUAL_LPIPS, ResourceKind.PERCEPTUAL_CLIP),
    (ResourceKind.VISION_QA,),
)

# Default VRAM lease timeout for test resources (seconds).
# If a lease cannot be acquired within this window, the metric is skipped
# with "vram_contention_timeout" status — not a test failure (Requirement 21.4).
VRAM_LEASE_TIMEOUT_S: float = 60.0

_COMFY_KINDS = frozenset(
    {
        ResourceKind.DREAM_FLUX,
        ResourceKind.CANON_FLUX,
        ResourceKind.SAM,
        ResourceKind.EDIT_INPAINT,
        ResourceKind.DA3,
        ResourceKind.HUNYUAN3D,
        ResourceKind.TRELLIS2,
        ResourceKind.PAINTING,
        ResourceKind.COMFYUI,
    }
)

# Test-specific kinds that do NOT route through ComfyUI (they load their own models).
_TEST_KINDS = frozenset(
    {
        ResourceKind.PERCEPTUAL_LPIPS,
        ResourceKind.PERCEPTUAL_CLIP,
        ResourceKind.VISION_QA,
    }
)

# Perceptual kinds that may coexist concurrently (total 4 GB).
_PERCEPTUAL_COEXIST = frozenset(
    {
        ResourceKind.PERCEPTUAL_LPIPS,
        ResourceKind.PERCEPTUAL_CLIP,
    }
)

_DEFAULT_VRAM_GB = {
    ResourceKind.OLLAMA_PLANNER: 16.0,
    ResourceKind.OLLAMA_VISION: 8.0,
    ResourceKind.DREAM_FLUX: 12.0,
    ResourceKind.CANON_FLUX: 12.0,
    ResourceKind.SAM: 4.0,
    ResourceKind.EDIT_INPAINT: 12.0,
    ResourceKind.DA3: 6.0,
    ResourceKind.HUNYUAN3D: 14.0,
    ResourceKind.TRELLIS2: 10.0,
    ResourceKind.PAINTING: 8.0,
    ResourceKind.COMFYUI: 8.0,
    ResourceKind.PERCEPTUAL_LPIPS: 2.0,
    ResourceKind.PERCEPTUAL_CLIP: 2.0,
    ResourceKind.VISION_QA: 8.0,
}


@dataclass(frozen=True)
class ResourceRequest:
    """A named request for the sole GPU lease."""

    kind: ResourceKind
    owner_id: str
    model_name: str = ""
    comfyui_instance: str = "default"
    estimated_vram_gb: float | None = None
    session_id: str = ""
    external_job_id: str = ""
    attempt: int = 1

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("owner_id must be non-empty for durable diagnostics")
        if self.estimated_vram_gb is not None and self.estimated_vram_gb <= 0:
            raise ValueError("estimated_vram_gb must be positive")
        if self.attempt < 1:
            raise ValueError("attempt must be at least one")


@dataclass(frozen=True)
class ResourceLease:
    lease_id: str
    request: ResourceRequest
    acquired_at: float


@dataclass(frozen=True)
class ArbiterState:
    phase: str
    active_owner: dict[str, Any] | None
    queued: int
    sequence: int
    host_ram_gb: float
    vram_used_gb: dict[str, float]
    updated_at: float


class ResourceArbiterError(RuntimeError):
    """Base error for resource arbitration failures."""


class ResourceReleaseError(ResourceArbiterError):
    """Raised when /free does not produce a measured safe VRAM level."""


class ResourceReentrancyError(ResourceArbiterError):
    """Raised when one task attempts to nest GPU ownership."""


class ResourceOwnershipTimeout(ResourceArbiterError):
    """Raised when another live process retains the durable GPU lease."""


class ResourceStallError(ResourceArbiterError):
    """Raised when an owner exceeds its bounded no-progress interval."""


class VRAMContentionTimeout(ResourceArbiterError):
    """Raised when a test-specific VRAM lease cannot be acquired within the timeout.

    This is a soft failure for test infrastructure: the metric should be skipped
    with status "vram_contention_timeout" rather than failing the test suite.
    (Requirement 21.4)
    """


@dataclass(frozen=True)
class VRAMLeaseResult:
    """Result of a test VRAM lease attempt.

    Attributes:
        acquired: True if the lease was successfully acquired.
        lease: The ResourceLease if acquired, else None.
        status: "acquired" or "vram_contention_timeout".
    """

    acquired: bool
    lease: ResourceLease | None
    status: str


class UnifiedResourceArbiter:
    """Serialize every V16 GPU user and persist ownership transitions.

    One instance is shared by the orchestrator.  All registered ComfyUI
    instances are hard-freed and measured whenever any lease exits, so a model
    hosted by one server cannot remain resident while another owner starts.
    """

    def __init__(
        self,
        comfyui_clients: Mapping[str, ComfyUIClient],
        *,
        diagnostics_dir: Path | str,
        vram_managers: Mapping[str, VRAMManager] | None = None,
        unloaders: Mapping[ResourceKind, UnloadCallable] | None = None,
        ram_provider: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], float] = time.time,
        acquire_timeout_s: float = 300.0,
        stall_timeout_s: float = 180.0,
    ) -> None:
        if not comfyui_clients and not vram_managers:
            raise ValueError("register at least one ComfyUI instance")
        self._clients = dict(comfyui_clients)
        if vram_managers is None:
            self._managers = {
                name: VRAMManager(client) for name, client in self._clients.items()
            }
        else:
            self._managers = dict(vram_managers)
        if set(self._clients) != set(self._managers):
            raise ValueError("comfyui_clients and vram_managers must name the same instances")
        self._unloaders = dict(unloaders or {})
        self._ram_provider = ram_provider or self._system_ram_used_gb
        self._sleep = sleep
        self._clock = wall_clock
        self._acquire_timeout_s = acquire_timeout_s
        self._stall_timeout_s = stall_timeout_s
        if acquire_timeout_s <= 0 or stall_timeout_s <= 0:
            raise ValueError("acquire and stall timeouts must be positive")
        self._lock = asyncio.Lock()
        self._active: ResourceLease | None = None
        self._active_task: asyncio.Task[Any] | None = None
        self._queued = 0
        self._sequence = 0
        self._phase = "idle"
        self._vram_used = {name: 0.0 for name in self._clients}
        self._diagnostics_dir = Path(diagnostics_dir)
        self._state_path = self._diagnostics_dir / "gpu_owner.json"
        self._journal_path = self._diagnostics_dir / "gpu_owner.jsonl"
        self._lease_path = self._diagnostics_dir / "gpu_owner.lock"
        self._diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self._recover_diagnostic_state()
        self._write_state()

    @property
    def active_owner(self) -> ResourceLease | None:
        return self._active

    @property
    def registered_comfyui_instances(self) -> tuple[str, ...]:
        return tuple(sorted(self._clients))

    def get_state(self) -> ArbiterState:
        return ArbiterState(
            phase=self._phase,
            active_owner=self._owner_dict(),
            queued=self._queued,
            sequence=self._sequence,
            host_ram_gb=float(self._ram_provider()),
            vram_used_gb=dict(self._vram_used),
            updated_at=self._clock(),
        )

    @asynccontextmanager
    async def claim(self, request: ResourceRequest) -> AsyncGenerator[ResourceLease, None]:
        """Wait for and hold the sole local and process-visible GPU lease."""
        task = asyncio.current_task()
        if task is not None and task is self._active_task:
            raise ResourceReentrancyError("nested GPU ownership would deadlock")
        self._validate_request(request)
        self._queued += 1
        self._record("queued", request=request)
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self._acquire_timeout_s)
        except BaseException as exc:
            self._queued -= 1
            self._record("queue_cancelled", request=request, detail=repr(exc))
            if isinstance(exc, asyncio.TimeoutError):
                raise ResourceOwnershipTimeout(
                    f"timed out waiting for local GPU lease for {request.owner_id}"
                ) from exc
            raise
        self._queued -= 1
        lease = ResourceLease(str(uuid.uuid4()), request, self._clock())
        claimed = False
        release_error: BaseException | None = None
        try:
            await self._claim_durable_owner(lease)
            claimed = True
            self._active = lease
            self._active_task = task
            await self._wait_for_host_ram()
            await self._activate(request)
            self._phase = "owned"
            self._record("acquired", request=request, lease_id=lease.lease_id)
            yield lease
        except BaseException as exc:
            self._record(
                "owner_failed" if not isinstance(exc, asyncio.CancelledError) else "owner_cancelled",
                request=request,
                lease_id=lease.lease_id,
                detail=repr(exc),
            )
            raise
        finally:
            if claimed:
                self._phase = "releasing"
                try:
                    await self._release_all(request)
                except BaseException as exc:
                    release_error = exc
                    self._record("release_failed", request=request, detail=repr(exc))
                self._release_durable_owner(lease)
            self._active = None
            self._active_task = None
            self._phase = "idle" if release_error is None else "release_failed"
            self._record("released", request=request, lease_id=lease.lease_id)
            self._lock.release()
            if release_error is not None and not isinstance(release_error, asyncio.CancelledError):
                raise release_error

    @asynccontextmanager
    async def claim_for_test(
        self,
        request: ResourceRequest,
        *,
        timeout_s: float | None = None,
    ) -> AsyncGenerator[VRAMLeaseResult, None]:
        """Acquire a test-specific VRAM lease with graceful timeout.

        If the lease cannot be acquired within ``timeout_s`` (default
        :data:`VRAM_LEASE_TIMEOUT_S` = 60s), yields a ``VRAMLeaseResult``
        with ``acquired=False`` and ``status="vram_contention_timeout"``
        instead of raising — the caller should skip the metric without
        failing the test suite.  (Requirements 21.4)

        Sequential scheduling (Requirements 21.2, 21.5) is enforced by the
        caller's test fixture ordering: FLUX completes and releases before
        perceptual metrics start, and perceptual models release before
        VISION_QA starts.  This context manager provides the timeout safety
        net when contention from other processes unexpectedly delays a lease.
        """
        lease_timeout = timeout_s if timeout_s is not None else VRAM_LEASE_TIMEOUT_S

        # Override the arbiter's default acquire_timeout_s for this specific claim.
        original_timeout = self._acquire_timeout_s
        self._acquire_timeout_s = lease_timeout
        try:
            async with self.claim(request) as lease:
                yield VRAMLeaseResult(acquired=True, lease=lease, status="acquired")
        except (ResourceOwnershipTimeout, asyncio.TimeoutError):
            self._record(
                "vram_contention_timeout",
                request=request,
                detail=f"lease not acquired within {lease_timeout:.1f}s — metric skipped",
            )
            yield VRAMLeaseResult(acquired=False, lease=None, status="vram_contention_timeout")
        finally:
            self._acquire_timeout_s = original_timeout

    def get_nightly_schedule(self) -> tuple[tuple[ResourceKind, ...], ...]:
        """Return the sequential scheduling order for nightly GPU tests.

        The schedule defines which resource kinds run in each phase:
        - Phase 1: FLUX generation (12 GB exclusive)
        - Phase 2: Perceptual models (LPIPS + CLIP can coexist, 4 GB total)
        - Phase 3: Vision QA (8 GB exclusive)

        Requirements: 21.2, 21.5
        """
        return NIGHTLY_TEST_SCHEDULE

    def get_test_lease_timeout(self) -> float:
        """Return the configured VRAM lease timeout for test resources (seconds).

        Requirement: 21.4
        """
        return VRAM_LEASE_TIMEOUT_S

    async def execute(
        self,
        request: ResourceRequest,
        primary: AsyncCallable,
        *args: Any,
        fallback: AsyncCallable | None = None,
        fallback_request: ResourceRequest | None = None,
        stall_timeout_s: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run with one OOM retry, bounded stalls, then one declared fallback."""
        timeout = self._stall_timeout_s if stall_timeout_s is None else stall_timeout_s
        if timeout <= 0:
            raise ValueError("stall_timeout_s must be positive")
        exhausted_reason = ""
        async with self.claim(request):
            try:
                return await self._run_bounded(primary, timeout, *args, **kwargs)
            except asyncio.TimeoutError:
                exhausted_reason = "stall"
                self._record(
                    "stall_detected",
                    request=request,
                    attempt=1,
                    detail=f"no completion within {timeout:.3f}s",
                )
            except BaseException as exc:
                if not self._is_oom(exc):
                    raise
                self._record("oom", request=request, detail=repr(exc), attempt=1)
                await self._release_all(request)
                await self._sleep(OOM_RETRY_WAIT_S)
                await self._wait_for_host_ram()
                await self._activate(request)
                try:
                    result = await self._run_bounded(primary, timeout, *args, **kwargs)
                    self._record("oom_retry_succeeded", request=request, attempt=2)
                    return result
                except asyncio.TimeoutError:
                    exhausted_reason = "stall"
                    self._record(
                        "stall_detected",
                        request=request,
                        attempt=2,
                        detail=f"OOM retry stalled beyond {timeout:.3f}s",
                    )
                except BaseException as retry_exc:
                    if not self._is_oom(retry_exc):
                        raise
                    exhausted_reason = "oom"
                    self._record(
                        "oom_retry_exhausted",
                        request=request,
                        detail=repr(retry_exc),
                        attempt=2,
                    )
        if exhausted_reason and fallback is not None:
            next_request = fallback_request or request
            self._record(
                "fallback_started",
                request=next_request,
                detail=f"after {request.kind.value} {exhausted_reason}",
            )
            async with self.claim(next_request):
                try:
                    result = await self._run_bounded(fallback, timeout, *args, **kwargs)
                except asyncio.TimeoutError as exc:
                    self._record(
                        "fallback_stalled",
                        request=next_request,
                        detail=f"no completion within {timeout:.3f}s",
                    )
                    raise ResourceStallError(
                        f"fallback {next_request.kind.value} stalled after {timeout:.3f}s"
                    ) from exc
                self._record("fallback_succeeded", request=next_request)
                return result
        if exhausted_reason == "stall":
            raise ResourceStallError(
                f"{request.kind.value} stalled and has no fallback"
            )
        raise ComfyUIVRAMError(
            f"{request.kind.value} exhausted its OOM retry and has no fallback"
        )

    async def _run_bounded(
        self,
        operation: AsyncCallable,
        timeout_s: float,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await asyncio.wait_for(operation(*args, **kwargs), timeout=timeout_s)

    async def hard_cleanup(self) -> None:
        """Release every service while holding the same global ownership lock."""
        async with self._lock:
            await self._release_all(None)
            self._active = None
            self._active_task = None
            self._phase = "idle"
            self._record("hard_cleanup")

    async def _claim_durable_owner(self, lease: ResourceLease) -> None:
        deadline = time.monotonic() + self._acquire_timeout_s
        payload = {
            "schema": "unified-resource-lease/v1",
            "pid": os.getpid(),
            "lease_id": lease.lease_id,
            "owner_id": lease.request.owner_id,
            "session_id": lease.request.session_id,
            "external_job_id": lease.request.external_job_id,
            "attempt": lease.request.attempt,
            "kind": lease.request.kind.value,
            "acquired_at": lease.acquired_at,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        while True:
            try:
                descriptor = os.open(
                    self._lease_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                )
            except FileExistsError:
                existing = self._read_durable_lease()
                existing_pid = existing.get("pid") if existing else None
                if isinstance(existing_pid, int) and not psutil.pid_exists(existing_pid):
                    self._record("dead_process_owner_recovered", stale_owner=existing)
                    try:
                        self._lease_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    owner = existing.get("owner_id", "unknown") if existing else "unknown"
                    raise ResourceOwnershipTimeout(
                        f"GPU durable lease remains owned by live owner {owner}"
                    )
                await asyncio.sleep(0.05)
                continue
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return

    def _release_durable_owner(self, lease: ResourceLease) -> None:
        existing = self._read_durable_lease()
        if existing and existing.get("lease_id") == lease.lease_id:
            try:
                self._lease_path.unlink()
            except FileNotFoundError:
                pass

    def _read_durable_lease(self) -> dict[str, Any]:
        try:
            value = json.loads(self._lease_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _validate_request(self, request: ResourceRequest) -> None:
        if request.kind in _TEST_KINDS:
            return  # Test-specific kinds do not route through ComfyUI
        if request.kind in _COMFY_KINDS and request.comfyui_instance not in self._clients:
            raise ValueError(
                f"unknown ComfyUI instance {request.comfyui_instance!r}; "
                f"registered={sorted(self._clients)}"
            )

    async def _activate(self, request: ResourceRequest) -> None:
        if request.kind in _TEST_KINDS:
            return  # Test-specific kinds load their own models outside ComfyUI
        if request.kind not in _COMFY_KINDS:
            return
        manager = self._managers[request.comfyui_instance]
        model_name = request.model_name or request.kind.value
        estimate = request.estimated_vram_gb or _DEFAULT_VRAM_GB[request.kind]
        manager.flash_attention_enabled = True
        await manager.acquire_model(model_name, estimate)

    async def _release_all(self, request: ResourceRequest | None) -> None:
        if request is not None:
            unloader = self._unloaders.get(request.kind)
            if unloader is not None:
                result = unloader(request)
                if inspect.isawaitable(result):
                    await result
        failures: list[str] = []
        measurements: dict[str, float] = {}
        for name, manager in self._managers.items():
            try:
                await manager.hard_release()
                used = float(await manager._get_vram_used_gb())
                measurements[name] = used
                if used >= VRAM_FREE_THRESHOLD_GB:
                    failures.append(
                        f"{name} measured {used:.2f}GB after /free "
                        f"(must be <{VRAM_FREE_THRESHOLD_GB:.1f}GB)"
                    )
            except BaseException as exc:
                failures.append(f"{name}: {exc!r}")
        self._vram_used.update(measurements)
        self._record("measured_release", measurements=measurements)
        if failures:
            raise ResourceReleaseError("; ".join(failures))


    async def _wait_for_host_ram(self) -> None:
        used = float(self._ram_provider())
        if used <= SYSTEM_RAM_PAUSE_THRESHOLD_GB:
            return
        self._phase = "host_ram_paused"
        self._record("host_ram_paused", host_ram_gb=used)
        while used >= SYSTEM_RAM_RESUME_THRESHOLD_GB:
            await self._sleep(2.0)
            used = float(self._ram_provider())
        self._record("host_ram_resumed", host_ram_gb=used)

    @staticmethod
    def _is_oom(exc: BaseException) -> bool:
        if isinstance(exc, ComfyUIVRAMError):
            return True
        message = str(exc).lower()
        return "out of memory" in message or "cuda oom" in message

    def _owner_dict(self) -> dict[str, Any] | None:
        if self._active is None:
            durable = self._read_durable_lease()
            return durable or None
        request = asdict(self._active.request)
        request["kind"] = self._active.request.kind.value
        return {
            "lease_id": self._active.lease_id,
            "acquired_at": self._active.acquired_at,
            **request,
        }

    def _record(self, event: str, **details: Any) -> None:
        self._sequence += 1
        request = details.pop("request", None)
        if isinstance(request, ResourceRequest):
            request_data = asdict(request)
            request_data["kind"] = request.kind.value
            details["request"] = request_data
        entry = {
            "sequence": self._sequence,
            "event": event,
            "timestamp": self._clock(),
            "phase": self._phase,
            "active_owner": self._owner_dict(),
            **details,
        }
        self._diagnostics_dir.mkdir(parents=True, exist_ok=True)
        with self._journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._write_state()

    def _write_state(self) -> None:
        state = {
            "schema": "unified-resource-owner/v1",
            "phase": self._phase,
            "active_owner": self._owner_dict(),
            "queued": self._queued,
            "sequence": self._sequence,
            "host_ram_gb": float(self._ram_provider()),
            "vram_used_gb": dict(self._vram_used),
            "registered_comfyui_instances": list(self.registered_comfyui_instances),
            "updated_at": self._clock(),
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, self._state_path)

    def _recover_diagnostic_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            previous = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._sequence = int(previous.get("sequence", 0))
            stale_owner = previous.get("active_owner")
            durable = self._read_durable_lease()
            durable_pid = durable.get("pid") if durable else None
            live_durable_owner = (
                isinstance(durable_pid, int) and psutil.pid_exists(durable_pid)
            )
            if stale_owner and not live_durable_owner:
                self._record(
                    "stale_owner_recovered",
                    detail="previous process ended with an active diagnostic owner",
                    stale_owner=stale_owner,
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._sequence = 0

    @staticmethod
    def _system_ram_used_gb() -> float:
        return psutil.virtual_memory().used / (1024**3)
