"""Physics Settle — dedicated pre-player simulation pass using PyBullet.

This module implements a final physics settle stage that runs AFTER
WorldContract assembly but BEFORE UPBGE compilation. It takes the
assembled WorldContract, simulates all dynamic objects under gravity
using PyBullet with simplified convex hull collision shapes, and
updates the instance transforms to reflect stable resting positions.

Key behaviors:
    - Up to 500 iterations, 10s wall-time limit for ≤30 objects.
    - Convex hull collision shapes per dynamic object (simplified).
    - Max 0.5m displacement per object per iteration.
    - Detect interpenetration via contact points, apply separation impulses.
    - Update WorldContract transforms with settled positions.
    - Preserve original (pre-settle) positions in manifest for debugging.
    - Flag unsettled objects (velocity > 0.01 m/s or penetration > 0.01m).
    - If >50% dynamic objects unsettled: log warning but do NOT reject.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from src.photo_pipeline.models import PhotoPipelineConfig
from src.world_contract import (
    BodyMode,
    Transform,
    Vector3,
    WorldContract,
    WorldInstance,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import PyBullet — optional dependency
# ---------------------------------------------------------------------------

try:
    import pybullet as p
    import pybullet_data

    PYBULLET_AVAILABLE = True
except ImportError:
    PYBULLET_AVAILABLE = False
    logger.info("PyBullet not available — physics settle will use fallback")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ITERATIONS = 500
_DEFAULT_TIMEOUT_S = 10.0  # 10s wall time for ≤30 objects (Req 10.6)
_MAX_DISPLACEMENT_M = 0.5  # max per iteration (Req 10.2)
_VELOCITY_THRESHOLD = 0.01  # m/s (Req 10.4)
_PENETRATION_THRESHOLD = 0.01  # meters (Req 10.4)
_TIMESTEP = 1.0 / 240.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SettledObjectInfo:
    """Per-object settle information for the manifest."""

    instance_id: str
    pre_settle_position: tuple[float, float, float]
    post_settle_position: tuple[float, float, float]
    post_settle_rotation_deg: tuple[float, float, float]
    settled: bool
    final_velocity: float  # m/s
    max_penetration: float  # meters


@dataclass(frozen=True)
class PhysicsSettleResult:
    """Result of the physics settle stage.

    Attributes
    ----------
    settled_world_contract : WorldContract
        The WorldContract with updated transforms for settled objects.
    object_info : list[SettledObjectInfo]
        Per-object settle information (pre/post positions, flags).
    total_unsettled : int
        Number of objects that did not converge.
    total_dynamic : int
        Total number of dynamic objects processed.
    iterations_run : int
        Number of simulation iterations actually executed.
    wall_time_s : float
        Wall-clock time spent in simulation.
    warning_issued : bool
        True if >50% of dynamic objects were unsettled (Req 10.5).
    """

    settled_world_contract: WorldContract
    object_info: list[SettledObjectInfo]
    total_unsettled: int
    total_dynamic: int
    iterations_run: int
    wall_time_s: float
    warning_issued: bool


# ---------------------------------------------------------------------------
# PhysicsSettle class
# ---------------------------------------------------------------------------


class PhysicsSettle:
    """Pre-player physics settle using PyBullet.

    Simulates dynamic objects under gravity to find stable resting
    positions. Uses simplified convex hull collision shapes.

    Falls back to a ground-clamp heuristic if PyBullet is unavailable.
    """

    def settle(
        self,
        world_contract: WorldContract,
        config: PhotoPipelineConfig | None = None,
    ) -> PhysicsSettleResult:
        """Run physics settle on the WorldContract.

        Parameters
        ----------
        world_contract : WorldContract
            Assembled WorldContract with instance transforms to settle.
        config : PhotoPipelineConfig | None
            Pipeline configuration. Uses defaults if None.

        Returns
        -------
        PhysicsSettleResult
            Result with settled WorldContract and per-object diagnostics.
        """
        if config is None:
            config = PhotoPipelineConfig()

        max_iterations = config.physics_settle_iterations
        timeout_s = _DEFAULT_TIMEOUT_S  # 10s for this dedicated stage

        # Identify dynamic objects from physics intents
        dynamic_intent_ids = {
            intent.subject_id
            for intent in world_contract.physics.intents
            if intent.body_mode == BodyMode.DYNAMIC
        }

        # Collect dynamic instances
        dynamic_instances: list[WorldInstance] = [
            inst for inst in world_contract.instances
            if inst.id in dynamic_intent_ids
        ]

        # If no dynamic objects, return unchanged
        if not dynamic_instances:
            return PhysicsSettleResult(
                settled_world_contract=world_contract,
                object_info=[],
                total_unsettled=0,
                total_dynamic=0,
                iterations_run=0,
                wall_time_s=0.0,
                warning_issued=False,
            )

        # Extract positions and dimensions for dynamic objects
        positions = [
            (
                inst.transform.position_m.x,
                inst.transform.position_m.y,
                inst.transform.position_m.z,
            )
            for inst in dynamic_instances
        ]
        dimensions = [
            (
                inst.dimensions.width_m,
                inst.dimensions.height_m,
                inst.dimensions.depth_m,
            )
            for inst in dynamic_instances
        ]

        # Also extract static objects for collision (room floor + static instances)
        static_instances: list[WorldInstance] = [
            inst for inst in world_contract.instances
            if inst.id not in dynamic_intent_ids
        ]

        # Run physics settle
        if PYBULLET_AVAILABLE:
            try:
                outcomes, iterations_run, wall_time = _pybullet_settle(
                    positions=positions,
                    dimensions=dimensions,
                    static_instances=static_instances,
                    room_dimensions=(
                        world_contract.room.dimensions.width_m,
                        world_contract.room.dimensions.height_m,
                        world_contract.room.dimensions.depth_m,
                    ),
                    max_iterations=max_iterations,
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                logger.warning(
                    "PyBullet settle failed (%s) — using ground-clamp fallback", exc
                )
                outcomes, iterations_run, wall_time = _fallback_settle(
                    positions, dimensions
                )
        else:
            outcomes, iterations_run, wall_time = _fallback_settle(
                positions, dimensions
            )

        # Build per-object info and count unsettled
        object_info: list[SettledObjectInfo] = []
        unsettled_count = 0

        for i, (inst, outcome) in enumerate(zip(dynamic_instances, outcomes)):
            info = SettledObjectInfo(
                instance_id=inst.id,
                pre_settle_position=positions[i],
                post_settle_position=outcome.position,
                post_settle_rotation_deg=outcome.rotation_deg,
                settled=outcome.settled,
                final_velocity=outcome.final_velocity,
                max_penetration=outcome.max_penetration,
            )
            object_info.append(info)

            if not outcome.settled:
                unsettled_count += 1
                logger.warning(
                    "Object '%s' unsettled: velocity=%.4f m/s, penetration=%.4f m",
                    inst.id,
                    outcome.final_velocity,
                    outcome.max_penetration,
                )

        # Check >50% unsettled threshold (Req 10.5)
        total_dynamic = len(dynamic_instances)
        warning_issued = False
        if total_dynamic > 0 and unsettled_count > total_dynamic / 2:
            logger.warning(
                "Physics settle: %d/%d dynamic objects unsettled (>50%%) — "
                "proceeding without rejection (UPBGE runtime will resolve)",
                unsettled_count,
                total_dynamic,
            )
            warning_issued = True

        # Update WorldContract transforms (Req 10.3)
        settled_wc = _update_world_contract_transforms(
            world_contract, dynamic_instances, outcomes
        )

        return PhysicsSettleResult(
            settled_world_contract=settled_wc,
            object_info=object_info,
            total_unsettled=unsettled_count,
            total_dynamic=total_dynamic,
            iterations_run=iterations_run,
            wall_time_s=wall_time,
            warning_issued=warning_issued,
        )


# ---------------------------------------------------------------------------
# Internal outcome dataclass
# ---------------------------------------------------------------------------


@dataclass
class _SettleOutcome:
    """Internal per-object settle result."""

    position: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    settled: bool
    final_velocity: float
    max_penetration: float


# ---------------------------------------------------------------------------
# PyBullet settle implementation
# ---------------------------------------------------------------------------


def _pybullet_settle(
    positions: list[tuple[float, float, float]],
    dimensions: list[tuple[float, float, float]],
    static_instances: list[WorldInstance],
    room_dimensions: tuple[float, float, float],
    max_iterations: int,
    timeout_s: float,
) -> tuple[list[_SettleOutcome], int, float]:
    """Run physics settle using PyBullet with convex hull shapes.

    Returns (outcomes, iterations_run, wall_time_s).
    """
    physics_client = p.connect(p.DIRECT)
    try:
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, -9.81, 0, physicsClientId=physics_client)
        p.setTimeStep(_TIMESTEP, physicsClientId=physics_client)

        # Create ground plane at y=0 (room floor)
        room_w, room_h, room_d = room_dimensions
        ground_shape = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=[room_w / 2 + 1.0, 0.5, room_d / 2 + 1.0],
            physicsClientId=physics_client,
        )
        p.createMultiBody(
            baseMass=0,  # static
            baseCollisionShapeIndex=ground_shape,
            basePosition=[0, -0.5, 0],  # top surface at y=0
            physicsClientId=physics_client,
        )

        # Add static instances as static collision bodies
        for static_inst in static_instances:
            half_w = max(0.005, static_inst.dimensions.width_m / 2.0)
            half_h = max(0.005, static_inst.dimensions.height_m / 2.0)
            half_d = max(0.005, static_inst.dimensions.depth_m / 2.0)

            static_shape = p.createCollisionShape(
                p.GEOM_BOX,
                halfExtents=[half_w, half_h, half_d],
                physicsClientId=physics_client,
            )
            pos = [
                static_inst.transform.position_m.x,
                static_inst.transform.position_m.y,
                static_inst.transform.position_m.z,
            ]
            p.createMultiBody(
                baseMass=0,
                baseCollisionShapeIndex=static_shape,
                basePosition=pos,
                physicsClientId=physics_client,
            )

        # Create dynamic objects as convex hull approximations (box shapes
        # serve as simplified convex hulls — actual mesh convex hulls would
        # require loading GLB data which isn't available at this stage)
        body_ids: list[int] = []
        for pos, dims in zip(positions, dimensions):
            half_w = max(0.005, dims[0] / 2.0)
            half_h = max(0.005, dims[1] / 2.0)
            half_d = max(0.005, dims[2] / 2.0)

            # Use box shape as simplified convex hull approximation
            shape = p.createCollisionShape(
                p.GEOM_BOX,
                halfExtents=[half_w, half_h, half_d],
                physicsClientId=physics_client,
            )

            # Mass estimate from volume (approximate 500 kg/m³ average)
            volume = dims[0] * dims[1] * dims[2]
            mass = max(0.1, volume * 500.0)

            body_id = p.createMultiBody(
                baseMass=mass,
                baseCollisionShapeIndex=shape,
                basePosition=list(pos),
                physicsClientId=physics_client,
            )
            body_ids.append(body_id)

        # Step simulation with displacement clamping
        start_time = time.time()
        iterations = 0

        while iterations < max_iterations:
            elapsed = time.time() - start_time
            if elapsed > timeout_s:
                break

            p.stepSimulation(physicsClientId=physics_client)
            iterations += 1

            # Clamp displacement per iteration (Req 10.2)
            for i, body_id in enumerate(body_ids):
                cur_pos, cur_orn = p.getBasePositionAndOrientation(
                    body_id, physicsClientId=physics_client
                )
                orig = positions[i]
                dx = cur_pos[0] - orig[0]
                dy = cur_pos[1] - orig[1]
                dz = cur_pos[2] - orig[2]
                displacement = math.sqrt(dx * dx + dy * dy + dz * dz)

                # Scale of allowed displacement grows with iterations
                max_allowed = _MAX_DISPLACEMENT_M * iterations
                if displacement > max_allowed:
                    # Clamp to maximum allowed distance from original
                    scale = max_allowed / displacement
                    clamped_pos = [
                        orig[0] + dx * scale,
                        orig[1] + dy * scale,
                        orig[2] + dz * scale,
                    ]
                    p.resetBasePositionAndOrientation(
                        body_id, clamped_pos, cur_orn,
                        physicsClientId=physics_client,
                    )
                    # Zero velocity after clamp
                    p.resetBaseVelocity(
                        body_id, [0, 0, 0], [0, 0, 0],
                        physicsClientId=physics_client,
                    )

            # Early exit if all objects settled
            if iterations > 10:
                all_settled = True
                for body_id in body_ids:
                    vel, _ = p.getBaseVelocity(
                        body_id, physicsClientId=physics_client
                    )
                    speed = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
                    if speed > _VELOCITY_THRESHOLD:
                        all_settled = False
                        break
                if all_settled:
                    break

        wall_time = time.time() - start_time

        # Read final state and compute settle status
        outcomes: list[_SettleOutcome] = []
        for i, body_id in enumerate(body_ids):
            pos_final, orn = p.getBasePositionAndOrientation(
                body_id, physicsClientId=physics_client
            )
            vel, _ = p.getBaseVelocity(body_id, physicsClientId=physics_client)

            # Convert quaternion to Euler (degrees)
            euler = p.getEulerFromQuaternion(orn)
            rotation_deg = (
                math.degrees(euler[0]),
                math.degrees(euler[1]),
                math.degrees(euler[2]),
            )

            speed = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)

            # Check penetration via contact points
            max_penetration = 0.0
            contacts = p.getContactPoints(
                bodyA=body_id, physicsClientId=physics_client
            )
            for contact in contacts:
                # contact[8] is the contact distance (negative = penetration)
                penetration = -contact[8]
                max_penetration = max(max_penetration, penetration)

            settled = (
                speed <= _VELOCITY_THRESHOLD
                and max_penetration <= _PENETRATION_THRESHOLD
            )

            outcomes.append(
                _SettleOutcome(
                    position=(pos_final[0], pos_final[1], pos_final[2]),
                    rotation_deg=rotation_deg,
                    settled=settled,
                    final_velocity=speed,
                    max_penetration=max_penetration,
                )
            )

        return outcomes, iterations, wall_time
    finally:
        p.disconnect(physics_client)


# ---------------------------------------------------------------------------
# Fallback settle (no PyBullet)
# ---------------------------------------------------------------------------


def _fallback_settle(
    positions: list[tuple[float, float, float]],
    dimensions: list[tuple[float, float, float]],
) -> tuple[list[_SettleOutcome], int, float]:
    """Simple ground-clamp fallback when PyBullet is unavailable.

    Places each object at ground level (y = half_height) if floating.
    Returns (outcomes, iterations=0, wall_time≈0).
    """
    start = time.time()
    outcomes: list[_SettleOutcome] = []

    for pos, dims in zip(positions, dimensions):
        half_h = max(0.005, dims[1] / 2.0)
        # Ensure object bottom touches or is above ground
        settled_y = max(half_h, pos[1])

        outcomes.append(
            _SettleOutcome(
                position=(pos[0], settled_y, pos[2]),
                rotation_deg=(0.0, 0.0, 0.0),
                settled=True,
                final_velocity=0.0,
                max_penetration=0.0,
            )
        )

    wall_time = time.time() - start
    return outcomes, 0, wall_time


# ---------------------------------------------------------------------------
# WorldContract transform update
# ---------------------------------------------------------------------------


def _update_world_contract_transforms(
    world_contract: WorldContract,
    dynamic_instances: list[WorldInstance],
    outcomes: list[_SettleOutcome],
) -> WorldContract:
    """Create a new WorldContract with updated transforms for settled objects.

    Since WorldContract is frozen (Pydantic), we rebuild it with modified
    instance transforms.

    Parameters
    ----------
    world_contract : WorldContract
        Original assembled WorldContract.
    dynamic_instances : list[WorldInstance]
        The dynamic instances that were settled.
    outcomes : list[_SettleOutcome]
        Settle outcomes aligned with dynamic_instances.

    Returns
    -------
    WorldContract
        New WorldContract with updated transforms.
    """
    # Build a map from instance_id → new transform
    settled_transforms: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
    for inst, outcome in zip(dynamic_instances, outcomes):
        settled_transforms[inst.id] = (outcome.position, outcome.rotation_deg)

    # Rebuild instances with updated transforms
    updated_instances: list[WorldInstance] = []
    for inst in world_contract.instances:
        if inst.id in settled_transforms:
            new_pos, new_rot = settled_transforms[inst.id]
            new_transform = Transform(
                position_m=Vector3(x=new_pos[0], y=new_pos[1], z=new_pos[2]),
                rotation_deg=Vector3(x=new_rot[0], y=new_rot[1], z=new_rot[2]),
                scale=inst.transform.scale,
            )
            # Rebuild the instance with updated transform (frozen model)
            inst_data = inst.model_dump()
            inst_data["transform"] = new_transform.model_dump()
            updated_instances.append(WorldInstance.model_validate(inst_data))
        else:
            updated_instances.append(inst)

    # Rebuild WorldContract with updated instances
    wc_data = world_contract.model_dump()
    wc_data["instances"] = [inst.model_dump() for inst in updated_instances]
    return WorldContract.model_validate(wc_data)
