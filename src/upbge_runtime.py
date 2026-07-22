"""Immutable first-party UPBGE runtime templates and release gates."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.upbge_capabilities import UPBGECapabilityReport
from src.world_contract import WorldContract

RUNTIME_SCHEMA_VERSION = "upbge-runtime/v1"
TEMPLATE_VERSION = "upbge-runtime-template/v1"
DYNAMIC_STATE_SCHEMA_VERSION = "upbge-runtime-state/v1"
RUNTIME_CANDIDATE_FILENAME = "runtime_candidate.blend"

PLAYER_CONTROLLER_SOURCE = r'''import bge
from mathutils import Vector

def main(controller):
    owner = controller.owner
    keyboard = bge.logic.keyboard.events
    if "kiro_runtime_ready" not in owner:
        owner["kiro_runtime_ready"] = True
        owner["kiro_paused"] = False
    if keyboard.get(bge.events.ESCKEY) == bge.logic.KX_INPUT_JUST_ACTIVATED:
        owner["kiro_paused"] = not owner["kiro_paused"]
    if keyboard.get(bge.events.F10KEY) == bge.logic.KX_INPUT_JUST_ACTIVATED:
        bge.logic.endGame()
        return
    if owner["kiro_paused"]:
        return
    mouse = bge.logic.mouse
    look_speed = max(0.0001, min(float(owner.get("kiro_look_speed", 0.0025)), 0.02))
    delta_x = mouse.position[0] - 0.5
    delta_y = mouse.position[1] - 0.5
    owner.applyRotation((0.0, 0.0, -delta_x*look_speed*100.0), False)
    camera = bge.logic.getCurrentScene().active_camera
    camera_rotation = camera.localOrientation.to_euler()
    camera_rotation.x = max(-1.5, min(1.5, camera_rotation.x-delta_y*look_speed*100.0))
    camera.localOrientation = camera_rotation.to_matrix()
    bge.render.setMousePosition(bge.render.getWindowWidth()//2, bge.render.getWindowHeight()//2)
    direction = Vector((0.0, 0.0, 0.0))
    direction.y += keyboard.get(bge.events.WKEY, 0) > 0
    direction.y -= keyboard.get(bge.events.SKEY, 0) > 0
    direction.x -= keyboard.get(bge.events.AKEY, 0) > 0
    direction.x += keyboard.get(bge.events.DKEY, 0) > 0
    if direction.length:
        direction.normalize()
    speed = max(0.1, min(float(owner.get("kiro_move_speed", 4.0)), 20.0))
    owner.applyMovement((direction.x*speed/60.0, direction.y*speed/60.0, 0.0), True)
    gravity = max(0.0, min(float(owner.get("kiro_gravity", 9.81)), 50.0))
    owner.applyForce((0.0, 0.0, -gravity*max(owner.mass, 1.0)), False)
'''

DOOR_COMPONENT_SOURCE = r'''import bge
import math

def main(controller):
    owner = controller.owner
    if "kiro_closed_angle" not in owner:
        owner["kiro_closed_angle"] = owner.localOrientation.to_euler().z
        owner["kiro_door_open"] = bool(owner.get("kiro_initially_open", False))
    if owner.get("kiro_interact_requested", False):
        owner["kiro_interact_requested"] = False
        owner["kiro_door_open"] = not owner["kiro_door_open"]
    closed = float(owner["kiro_closed_angle"])
    offset = math.radians(float(owner.get("kiro_open_angle_deg", 90.0)))
    target = closed + offset if owner["kiro_door_open"] else closed
    rotation = owner.localOrientation.to_euler()
    step = math.radians(float(owner.get("kiro_speed_deg_s", 120.0))) / 60.0
    difference = target - rotation.z
    rotation.z += max(-step, min(step, difference))
    owner.localOrientation = rotation.to_matrix()
'''

GRAB_COMPONENT_SOURCE = r'''import bge
import json

def main(controller):
    owner = controller.owner
    keyboard = bge.logic.keyboard.events
    scene = bge.logic.getCurrentScene()
    active_name = owner.get("kiro_grabbed_name", "")
    if keyboard.get(bge.events.EKEY) == bge.logic.KX_INPUT_JUST_ACTIVATED:
        if active_name:
            owner["kiro_grabbed_name"] = ""
            return
        camera = scene.active_camera
        distance = float(owner.get("kiro_max_distance_m", 3.0))
        ray_to = camera.worldPosition + camera.getAxisVect((0.0, 0.0, -distance))
        hit, _point, _normal = owner.rayCast(ray_to, camera.worldPosition, distance)
        if hit and "kiro_open_angle_deg" in hit:
            hit["kiro_interact_requested"] = True
        elif hit and hit.get("kiro_body_mode", "") == "dynamic":
            stable_id = hit.get("kiro_stable_id", "")
            rules = json.loads(owner.get("kiro_grab_rules_json", "{}"))
            rule = rules.get(stable_id)
            if rule and float(hit.get("kiro_mass_kg", 0.0)) <= float(rule["max_mass_kg"]):
                owner["kiro_grabbed_name"] = hit.name
                owner["kiro_grab_hold_distance"] = float(rule["hold_distance_m"])
    active_name = owner.get("kiro_grabbed_name", "")
    if active_name and active_name in scene.objects:
        grabbed = scene.objects[active_name]
        camera = scene.active_camera
        hold = float(owner.get("kiro_grab_hold_distance", 1.5))
        target = camera.worldPosition + camera.getAxisVect((0.0, 0.0, -hold))
        grabbed.setLinearVelocity((target - grabbed.worldPosition) * 10.0, False)
'''


@dataclass(frozen=True)
class RuntimeTemplateSpec:
    template_id: str
    version: str
    entrypoint: str
    source: str
    allowed_parameters: tuple[str, ...]
    behaviors: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()


PLAYER_TEMPLATE = RuntimeTemplateSpec(
    template_id="player.first_person",
    version=TEMPLATE_VERSION,
    entrypoint="main",
    source=PLAYER_CONTROLLER_SOURCE,
    allowed_parameters=("move_speed", "look_speed", "gravity"),
    behaviors=("spawn", "movement", "collision", "gravity", "pause", "exit"),
)
DOOR_TEMPLATE = RuntimeTemplateSpec(
    template_id="interaction.door",
    version=TEMPLATE_VERSION,
    entrypoint="main",
    source=DOOR_COMPONENT_SOURCE,
    allowed_parameters=("open_angle_deg", "speed_deg_s", "initially_open"),
    behaviors=("door_toggle",),
)
GRAB_TEMPLATE = RuntimeTemplateSpec(
    template_id="interaction.grab",
    version=TEMPLATE_VERSION,
    entrypoint="main",
    source=GRAB_COMPONENT_SOURCE,
    allowed_parameters=("max_distance_m", "hold_distance_m", "max_mass_kg"),
    behaviors=("raycast", "grab", "release"),
)
RUNTIME_TEMPLATES = (PLAYER_TEMPLATE, DOOR_TEMPLATE, GRAB_TEMPLATE)
_TEMPLATE_BY_KIND = {"door": DOOR_TEMPLATE, "grab": GRAB_TEMPLATE}


@dataclass(frozen=True)
class RuntimeInteractionBinding:
    interaction_id: str
    kind: str
    subject_id: str
    target_id: str | None
    template_id: str
    parameters: tuple[tuple[str, bool | int | float | str], ...]


@dataclass(frozen=True)
class RuntimePlan:
    schema_version: str
    world_contract_hash: str
    player_template_id: str
    template_hashes: tuple[tuple[str, str], ...]
    template_sources: tuple[tuple[str, str, str], ...]
    gravity_upbge: tuple[float, float, float]
    interactions: tuple[RuntimeInteractionBinding, ...]
    dynamic_state_schema: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DynamicObjectState:
    stable_id: str
    position_upbge: tuple[float, float, float]
    rotation_upbge_deg: tuple[float, float, float]
    linear_velocity_upbge: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if not self.stable_id or any(value in self.stable_id for value in ("/", "\\", "\x00")):
            raise ValueError("dynamic state stable_id must be a safe identifier")
        for label, vector in (
            ("position_upbge", self.position_upbge),
            ("rotation_upbge_deg", self.rotation_upbge_deg),
            ("linear_velocity_upbge", self.linear_velocity_upbge),
        ):
            if len(vector) != 3 or not all(
                not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(float(value)) for value in vector
            ):
                raise ValueError(f"{label} must contain three finite numbers")
            object.__setattr__(self, label, tuple(float(value) for value in vector))


@dataclass(frozen=True)
class RuntimeDynamicState:
    schema_version: str
    world_contract_hash: str
    sequence: int
    objects: tuple[DynamicObjectState, ...]

    def __post_init__(self) -> None:
        if self.schema_version != DYNAMIC_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported dynamic state schema")
        _validated_sha256(self.world_contract_hash, "world_contract_hash")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("dynamic state sequence must be a non-negative integer")
        identifiers = [item.stable_id for item in self.objects]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("dynamic state contains duplicate object identifiers")
        if identifiers != sorted(identifiers):
            raise ValueError("dynamic state objects must use stable identifier order")

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, value: bytes) -> "RuntimeDynamicState":
        if not isinstance(value, bytes):
            raise ValueError("dynamic state must be encoded bytes")
        payload = json.loads(value.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
            raise ValueError("dynamic state payload must be an object")
        payload["objects"] = tuple(DynamicObjectState(
            stable_id=item["stable_id"],
            position_upbge=tuple(item["position_upbge"]),
            rotation_upbge_deg=tuple(item["rotation_upbge_deg"]),
            linear_velocity_upbge=tuple(item.get("linear_velocity_upbge", (0.0, 0.0, 0.0))),
        ) for item in payload["objects"])
        state = cls(**payload)
        if state.canonical_bytes() != value:
            raise ValueError("dynamic state bytes are not canonical")
        return state


@dataclass(frozen=True)
class RuntimeSmokeHarnessConfig:
    """Bounded process and evidence limits for first-party runtime smoke execution."""

    timeout_seconds: float = 30.0
    max_report_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or not 0.1 <= self.timeout_seconds <= 300.0:
            raise ValueError("timeout_seconds must be finite and within [0.1, 300]")
        if not 1024 <= self.max_report_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_report_bytes must be within [1024, 4194304]")


@dataclass(frozen=True)
class RuntimeSmokeHarnessRequest:
    schema_version: str
    package_path: str
    checks: tuple[str, ...]

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")


RuntimeSmokeCommandFactory = Callable[[Path, Path, Path, Path], tuple[str, ...]]


def _default_smoke_command(
    executable: Path, package: Path, request: Path, report: Path,
) -> tuple[str, ...]:
    """Invoke the package smoke entrypoint; exit zero alone is never success evidence."""
    return (
        str(executable), str(package),
        "--kiro-runtime-smoke-request", str(request),
        "--kiro-runtime-smoke-report", str(report),
    )


class BoundedUPBGERuntimeSmokeRunner:
    """Callable first-party runner for ``run_runtime_smoke`` pipeline injection.

    A bounded subprocess must write strict JSON evidence for every requested behavior.
    Stdout, process exit, and runtime presence are deliberately not treated as evidence.
    """

    def __init__(
        self,
        config: RuntimeSmokeHarnessConfig = RuntimeSmokeHarnessConfig(),
        *,
        command_factory: RuntimeSmokeCommandFactory = _default_smoke_command,
    ) -> None:
        self.config = config
        self.command_factory = command_factory

    @staticmethod
    def _failure(checks: tuple[str, ...], diagnostic: str) -> dict[str, str]:
        return {name: diagnostic for name in checks}

    def __call__(
        self, executable: Path, package: Path, required_interactions: tuple[str, ...],
    ) -> Mapping[str, bool | str]:
        checks = (
            "load", "player_spawn", "movement", "collision", "opening_traversal",
            *(f"interaction:{identity}" for identity in required_interactions),
        )
        if not executable.is_file():
            return self._failure(checks, "UPBGE executable is unavailable")
        if not package.is_file():
            return self._failure(checks, "UPBGE runtime package is unavailable")
        if len(required_interactions) != len(set(required_interactions)):
            return self._failure(checks, "required interaction IDs are not unique")

        with tempfile.TemporaryDirectory(prefix="kiro-upbge-smoke-") as temporary:
            root = Path(temporary)
            request_path = root / "request.json"
            report_path = root / "report.json"
            request = RuntimeSmokeHarnessRequest(
                schema_version="upbge-runtime-smoke-request/v1",
                package_path=str(package.resolve()), checks=checks,
            )
            request_path.write_bytes(request.canonical_bytes())
            command = self.command_factory(executable, package, request_path, report_path)
            if not command or Path(command[0]) != executable:
                return self._failure(checks, "runtime smoke command is not bound to the executable")
            environment = {
                key: value for key, value in os.environ.items()
                if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
            }
            try:
                completed = subprocess.run(
                    command, cwd=str(package.parent), env=environment, shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=self.config.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return self._failure(checks, f"runtime smoke process failed: {exc}")
            if completed.returncode != 0:
                return self._failure(
                    checks, f"runtime smoke process exited with code {completed.returncode}"
                )
            try:
                if not report_path.is_file():
                    raise ValueError("runtime produced no smoke evidence")
                if report_path.stat().st_size > self.config.max_report_bytes:
                    raise ValueError("runtime smoke evidence exceeds the configured limit")
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != "upbge-runtime-smoke-evidence/v1":
                    raise ValueError("runtime smoke evidence schema is unsupported")
                evidence = payload.get("checks")
                if not isinstance(evidence, dict) or set(evidence) != set(checks):
                    raise ValueError("runtime smoke evidence check IDs/count do not match the request")
                if any(not isinstance(value, bool) for value in evidence.values()):
                    raise ValueError("runtime smoke evidence values must be boolean")
                return {name: evidence[name] for name in checks}
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                return self._failure(checks, f"invalid runtime smoke evidence: {exc}")


FirstPartyUPBGERuntimeSmokeRunner = BoundedUPBGERuntimeSmokeRunner


@dataclass(frozen=True)
class ValidationEvidence:
    schema_version: str
    passed: bool
    evidence_hash: str | None
    mandatory_checks: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    world_contract_hash: str | None = None
    artifact_hash: str | None = None


@dataclass(frozen=True)
class RuntimePackageGate:
    allowed: bool
    reason_code: str
    failed_gates: tuple[str, ...]
    capability_path: str | None


@dataclass(frozen=True)
class PublishedRuntimeArtifact:
    role: str
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RuntimePublishResult:
    gate: RuntimePackageGate
    artifact: PublishedRuntimeArtifact | None
    reason_code: str


def _validated_sha256(value: str, label: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase hexadecimal SHA-256")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _validated_interaction_parameters(
    kind: str, parameters: Mapping[str, object]
) -> tuple[tuple[str, bool | int | float | str], ...]:
    template = _TEMPLATE_BY_KIND[kind]
    unknown = sorted(set(parameters) - set(template.allowed_parameters))
    if unknown:
        raise ValueError(f"unsupported {kind} parameters: {', '.join(unknown)}")
    defaults: dict[str, bool | float] = (
        {"open_angle_deg": 90.0, "speed_deg_s": 120.0, "initially_open": False}
        if kind == "door"
        else {"max_distance_m": 3.0, "hold_distance_m": 1.5, "max_mass_kg": 25.0}
    )
    values = {**defaults, **parameters}
    if kind == "door":
        angle = _finite_number(values["open_angle_deg"], "open_angle_deg")
        speed = _finite_number(values["speed_deg_s"], "speed_deg_s")
        initially_open = values["initially_open"]
        if not -180.0 <= angle <= 180.0 or angle == 0.0:
            raise ValueError("open_angle_deg must be non-zero and within [-180, 180]")
        if not 0.0 < speed <= 720.0:
            raise ValueError("speed_deg_s must be within (0, 720]")
        if not isinstance(initially_open, bool):
            raise ValueError("initially_open must be boolean")
        normalized: dict[str, bool | float] = {
            "open_angle_deg": angle,
            "speed_deg_s": speed,
            "initially_open": initially_open,
        }
    else:
        normalized = {
            key: _finite_number(values[key], key)
            for key in ("max_distance_m", "hold_distance_m", "max_mass_kg")
        }
        if not 0.1 <= normalized["max_distance_m"] <= 20.0:
            raise ValueError("max_distance_m must be within [0.1, 20]")
        if not 0.1 <= normalized["hold_distance_m"] <= normalized["max_distance_m"]:
            raise ValueError("hold_distance_m must not exceed max_distance_m")
        if not 0.1 <= normalized["max_mass_kg"] <= 1000.0:
            raise ValueError("max_mass_kg must be within [0.1, 1000]")
    return tuple(sorted(normalized.items()))


def _validate_dynamic_state_binding(
    state: RuntimeDynamicState, contract: WorldContract
) -> None:
    if state.world_contract_hash != contract.content_hash():
        raise ValueError("dynamic state is bound to a different WorldContract")
    dynamic_ids = {
        item.subject_id for item in contract.physics.intents
        if item.body_mode.value == "dynamic"
    }
    unexpected = sorted({item.stable_id for item in state.objects} - dynamic_ids)
    if unexpected:
        raise ValueError(f"dynamic state contains non-dynamic subjects: {', '.join(unexpected)}")


def persist_runtime_state(
    state: RuntimeDynamicState, state_root: str | os.PathLike[str], contract: WorldContract
) -> Path:
    """Atomically save mutable simulation data outside the approved WorldContract."""
    _validate_dynamic_state_binding(state, contract)
    root = Path(state_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("dynamic state root must not be a symlink")
    root = root.resolve(strict=True)
    target = root / "runtime_state.json"
    if target.is_symlink():
        raise ValueError("dynamic state path must not be a symlink")
    if target.exists():
        previous = RuntimeDynamicState.from_bytes(target.read_bytes())
        if previous.world_contract_hash != state.world_contract_hash:
            raise ValueError("refusing to overwrite state from a different WorldContract")
        if state.sequence <= previous.sequence:
            raise ValueError("dynamic state sequence must advance")
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".runtime-state-", suffix=".tmp", dir=root, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(state.canonical_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return target


def load_runtime_state(
    state_root: str | os.PathLike[str], contract: WorldContract
) -> RuntimeDynamicState:
    root = Path(state_root).expanduser().resolve(strict=True)
    target = root / "runtime_state.json"
    if target.is_symlink() or not target.is_file():
        raise ValueError("dynamic state file is unavailable")
    state = RuntimeDynamicState.from_bytes(target.read_bytes())
    _validate_dynamic_state_binding(state, contract)
    return state


def build_runtime_plan(contract: WorldContract) -> RuntimePlan:
    """Select reviewed templates; semantic data can only fill allowlisted parameters."""
    bindings = []
    binding_keys: set[tuple[str, str]] = set()
    physics_by_subject = {item.subject_id: item for item in contract.physics.intents}
    opening_kinds = {item.id: item.kind for item in contract.openings}
    for interaction in sorted(contract.interactions, key=lambda item: item.id):
        if interaction.kind not in _TEMPLATE_BY_KIND:
            raise ValueError(f"unsupported runtime interaction: {interaction.kind}")
        binding_key = (interaction.kind, interaction.subject_id)
        if binding_key in binding_keys:
            raise ValueError(
                f"duplicate {interaction.kind} interaction for {interaction.subject_id}"
            )
        binding_keys.add(binding_key)
        physics = physics_by_subject.get(interaction.subject_id)
        if physics is None:
            raise ValueError(f"interaction {interaction.id} requires explicit physics intent")
        if interaction.kind == "door":
            if opening_kinds.get(interaction.subject_id, "door") != "door":
                raise ValueError(f"door interaction {interaction.id} requires a door subject")
            if physics.body_mode.value == "trigger":
                raise ValueError(f"door interaction {interaction.id} cannot use a trigger body")
        if interaction.kind == "grab" and physics.body_mode.value != "dynamic":
            raise ValueError(f"grab interaction {interaction.id} requires a dynamic body")
        template = _TEMPLATE_BY_KIND[interaction.kind]
        bindings.append(RuntimeInteractionBinding(
            interaction_id=interaction.id,
            kind=interaction.kind,
            subject_id=interaction.subject_id,
            target_id=interaction.target_id,
            template_id=template.template_id,
            parameters=_validated_interaction_parameters(interaction.kind, interaction.parameters),
        ))
    gravity = contract.physics.gravity_m_s2
    return RuntimePlan(
        schema_version=RUNTIME_SCHEMA_VERSION,
        world_contract_hash=contract.content_hash(),
        player_template_id=PLAYER_TEMPLATE.template_id,
        template_hashes=tuple((item.template_id, item.sha256) for item in RUNTIME_TEMPLATES),
        template_sources=tuple(
            (item.template_id, item.entrypoint, item.source) for item in RUNTIME_TEMPLATES
        ),
        gravity_upbge=(gravity.x, gravity.z, gravity.y),
        interactions=tuple(bindings),
        dynamic_state_schema=DYNAMIC_STATE_SCHEMA_VERSION,
    )


def _valid_evidence(
    evidence: ValidationEvidence,
    expected_schema: str,
    *,
    world_contract_hash: str | None = None,
    artifact_hash: str | None = None,
) -> bool:
    if evidence.schema_version != expected_schema or not evidence.passed:
        return False
    try:
        _validated_sha256(evidence.evidence_hash or "", "evidence_hash")
    except ValueError:
        return False
    if evidence.failed_checks:
        return False
    if world_contract_hash is not None and evidence.world_contract_hash != world_contract_hash:
        return False
    if artifact_hash is not None and evidence.artifact_hash != artifact_hash:
        return False
    return True


def evaluate_runtime_package_gate(
    capability: UPBGECapabilityReport,
    parity: ValidationEvidence,
    runtime_smoke: ValidationEvidence,
    *,
    world_contract_hash: str | None = None,
    runtime_candidate_hash: str | None = None,
) -> RuntimePackageGate:
    """Authorize distribution only from verified capability and bound QA evidence."""
    failed: list[str] = []
    if not (
        capability.verified
        and capability.compatible
        and capability.product == "UPBGE"
        and capability.supports_game_runtime
        and capability.executable_path
    ):
        failed.append("capability")
    if not _valid_evidence(
        parity, "structural-parity/v1", world_contract_hash=world_contract_hash
    ):
        failed.append("parity")
    if not _valid_evidence(
        runtime_smoke, "runtime-smoke/v1", world_contract_hash=world_contract_hash,
        artifact_hash=runtime_candidate_hash,
    ):
        failed.append("runtime_smoke")
    return RuntimePackageGate(
        allowed=not failed,
        reason_code="runtime_package_authorized" if not failed else "runtime_package_rejected",
        failed_gates=tuple(failed),
        capability_path=capability.executable_path if capability.verified else None,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_runtime_candidate(
    candidate_path: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    contract: WorldContract,
    capability: UPBGECapabilityReport,
    parity: ValidationEvidence,
    runtime_smoke: ValidationEvidence,
) -> RuntimePublishResult:
    """Publish an immutable playable copy only after capability, parity, and smoke gates."""
    candidate_input = Path(candidate_path).expanduser()
    if candidate_input.is_symlink():
        raise ValueError("runtime candidate must not be a symlink")
    candidate = candidate_input.resolve(strict=True)
    if not candidate.is_file() or candidate.name != RUNTIME_CANDIDATE_FILENAME:
        raise ValueError("runtime candidate must be the compiler-produced candidate file")
    candidate_hash = _file_sha256(candidate)
    contract_hash = contract.content_hash()
    gate = evaluate_runtime_package_gate(
        capability, parity, runtime_smoke, world_contract_hash=contract_hash,
        runtime_candidate_hash=candidate_hash,
    )
    if not gate.allowed:
        return RuntimePublishResult(gate=gate, artifact=None, reason_code=gate.reason_code)
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("playable runtime output root must not be a symlink")
    root = root.resolve(strict=True)
    destination = root / f"playable_runtime-{candidate_hash[:16]}.blend"
    if destination.exists():
        if destination.is_symlink() or _file_sha256(destination) != candidate_hash:
            raise ValueError("immutable playable runtime path already contains different bytes")
    else:
        try:
            with destination.open("xb") as target, candidate.open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        except FileExistsError:
            if destination.is_symlink() or _file_sha256(destination) != candidate_hash:
                raise ValueError("immutable playable runtime path raced with different bytes")
    artifact = PublishedRuntimeArtifact(
        role="playable_runtime", path=str(destination), bytes=destination.stat().st_size,
        sha256=candidate_hash,
    )
    return RuntimePublishResult(gate=gate, artifact=artifact, reason_code="runtime_published")
